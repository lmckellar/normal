from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable

from normal.movie_audio_fix import build_ffmpeg_progress_update
from normal.movie_profile import (
    canonical_audio_language,
    choose_best_english_subtitle_stream,
    choose_default_audio_stream,
    choose_default_subtitle_stream,
    is_english_subtitle,
)
from normal.movie_scan import probe_media_facts
from normal.quality_review import MediaFacts, SubtitleStreamFacts


SUPPORTED_SUBTITLE_DEFAULT_FIX_EXTENSIONS = {".mkv"}


@dataclass(slots=True)
class SubtitleDefaultFixResult:
    path: str
    status: str
    message: str
    facts: MediaFacts | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ProgressCallback = Callable[[dict[str, Any]], None]


def fix_movie_subtitle_defaults(
    source_root: Path,
    paths: list[str],
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    fixed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for raw_path in paths:
        resolved = Path(str(raw_path)).expanduser().resolve()
        try:
            resolved.relative_to(source)
        except ValueError:
            skipped.append(SubtitleDefaultFixResult(str(resolved), "skipped", "outside_source").to_dict())
            continue
        result = fix_movie_subtitle_default(
            resolved,
            probe_media=probe_media,
            progress_callback=progress_callback,
        )
        payload = result.to_dict()
        if result.status == "fixed":
            fixed.append(payload)
        else:
            skipped.append(payload)

    return {
        "source_root": str(source),
        "fixed": fixed,
        "skipped": skipped,
    }


def fix_movie_subtitle_default(
    path: Path,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: ProgressCallback | None = None,
) -> SubtitleDefaultFixResult:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        return SubtitleDefaultFixResult(str(resolved), "skipped", "path_missing")
    if resolved.suffix.lower() not in SUPPORTED_SUBTITLE_DEFAULT_FIX_EXTENSIONS:
        return SubtitleDefaultFixResult(str(resolved), "skipped", "unsupported_container")

    try:
        original_facts = probe_media(resolved)
    except Exception as exc:
        return SubtitleDefaultFixResult(str(resolved), "skipped", f"probe_failed: {exc}")

    subtitle_streams = list(original_facts.subtitle_streams)
    if not subtitle_streams:
        return SubtitleDefaultFixResult(str(resolved), "skipped", "subtitle_streams_missing")

    plan = choose_subtitle_fix_plan(original_facts)
    if plan.message == "already_repaired":
        return SubtitleDefaultFixResult(str(resolved), "skipped", "already_repaired", facts=original_facts)
    if plan.target_ordinal is None and plan.mode != "clear":
        return SubtitleDefaultFixResult(str(resolved), "skipped", plan.message)

    with tempfile.NamedTemporaryFile(
        prefix=f"{resolved.stem}.normal-subtitle-fix.",
        suffix=resolved.suffix,
        dir=resolved.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    try:
        run_ffmpeg_subtitle_default_fix(
            resolved,
            temp_path,
            len(subtitle_streams),
            plan.target_ordinal,
            input_duration_seconds=original_facts.runtime_seconds,
            progress_callback=progress_callback,
        )
        fixed_facts = probe_media(temp_path)
        verify_fixed_subtitle_stream(fixed_facts.subtitle_streams, target_ordinal=plan.target_ordinal)
        temp_path.replace(resolved)
        return SubtitleDefaultFixResult(str(resolved), "fixed", plan.success_message, facts=fixed_facts)
    except FileNotFoundError:
        return SubtitleDefaultFixResult(str(resolved), "skipped", "ffmpeg_missing")
    except Exception as exc:
        return SubtitleDefaultFixResult(str(resolved), "skipped", f"fix_failed: {exc}")
    finally:
        temp_path.unlink(missing_ok=True)


@dataclass(slots=True)
class SubtitleFixPlan:
    mode: str
    target_ordinal: int | None
    message: str
    success_message: str


def choose_subtitle_fix_plan(facts: MediaFacts) -> SubtitleFixPlan:
    subtitle_streams = list(facts.subtitle_streams)
    if not subtitle_streams:
        return SubtitleFixPlan("review", None, "subtitle_streams_missing", "subtitle_defaults_cleared")

    target_ordinal = choose_target_subtitle_ordinal(facts)
    default_ordinals = [index for index, stream in enumerate(subtitle_streams) if stream.is_default]

    if target_ordinal is None:
        if not default_ordinals:
            return SubtitleFixPlan("clear", None, "already_repaired", "subtitle_defaults_cleared")
        return SubtitleFixPlan("clear", None, "clear_default_subtitles", "subtitle_defaults_cleared")

    if default_ordinals == [target_ordinal]:
        return SubtitleFixPlan("target", target_ordinal, "already_repaired", subtitle_target_success_message(facts, target_ordinal))
    return SubtitleFixPlan("target", target_ordinal, "repair_subtitle_defaults", subtitle_target_success_message(facts, target_ordinal))


def choose_target_subtitle_ordinal(facts: MediaFacts) -> int | None:
    subtitle_streams = list(facts.subtitle_streams)
    forced_target = choose_best_english_subtitle_stream(subtitle_streams, forced_only=True)
    if forced_target is not None:
        return subtitle_streams.index(forced_target)

    default_audio = choose_default_audio_stream(facts.audio_streams)
    default_audio_language = canonical_audio_language(default_audio.language) if default_audio else None
    if default_audio_language not in {None, "english"}:
        english_target = choose_best_english_subtitle_stream(subtitle_streams)
        if english_target is None:
            return None
        return subtitle_streams.index(english_target)
    return None


def subtitle_target_success_message(facts: MediaFacts, target_ordinal: int) -> str:
    stream = facts.subtitle_streams[target_ordinal]
    if is_english_subtitle(stream) and stream.is_forced:
        return "english_forced_defaulted"
    return "english_subtitle_defaulted"


def run_ffmpeg_subtitle_default_fix(
    path: Path,
    temp_path: Path,
    subtitle_stream_count: int,
    target_ordinal: int | None,
    input_duration_seconds: int | None,
    *,
    progress_callback: ProgressCallback | None = None,
) -> None:
    command = [
        "ffmpeg",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(path),
        "-map",
        "0",
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
    ]
    for output_ordinal in range(subtitle_stream_count):
        command.extend(
            [
                f"-disposition:s:{output_ordinal}",
                "default" if output_ordinal == target_ordinal else "0",
            ]
        )
    command.append(str(temp_path))
    try:
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise

    progress_state: dict[str, str] = {}
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        progress_state[key] = value
        if key == "progress" and progress_callback is not None:
            progress_callback(build_ffmpeg_progress_update(progress_state, input_duration_seconds, path, temp_path))
    stderr = process.stderr.read() if process.stderr is not None else ""
    result_code = process.wait()
    if progress_callback is not None:
        progress_callback(build_ffmpeg_progress_update(progress_state, input_duration_seconds, path, temp_path))
    if result_code != 0:
        message = stderr.strip() or "ffmpeg failed"
        raise RuntimeError(message)


def verify_fixed_subtitle_stream(streams: list[SubtitleStreamFacts], target_ordinal: int | None) -> None:
    defaults = [index for index, stream in enumerate(streams) if stream.is_default]
    if target_ordinal is None:
        if defaults:
            raise RuntimeError("verification_failed_default_subtitle_present")
        return
    if defaults != [target_ordinal]:
        raise RuntimeError("verification_failed_default_subtitle")
