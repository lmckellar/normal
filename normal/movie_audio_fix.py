from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable

from normal.mkvpropedit_fix import build_mkvpropedit_command, mkvpropedit_available, run_mkvpropedit
from normal.movie_profile import (
    audio_stream_quality_key,
    canonical_audio_language,
    choose_default_audio_stream,
)
from normal.movie_scan import probe_media_facts
from normal.pathsafe import contained_resolve
from normal.quality_review import AudioStreamFacts, MediaFacts
from normal.source_policy import ApprovedRoots, SourcePolicyError, validate_candidate_for_mutation


SUPPORTED_AUDIO_DEFAULT_FIX_EXTENSIONS = {".mkv"}


@dataclass(slots=True)
class AudioDefaultFixResult:
    path: str
    status: str
    message: str
    facts: MediaFacts | None = None
    removed_audio_tracks: int = 0
    removed_audio_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ProgressCallback = Callable[[dict[str, Any]], None]


def fix_english_audio_defaults(
    source_root: Path,
    paths: list[str],
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    drop_foreign_audio: bool = False,
    progress_callback: ProgressCallback | None = None,
    approved_roots: ApprovedRoots | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    fixed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for raw_path in paths:
        resolved, contained = contained_resolve(raw_path, source)
        if not contained:
            skipped.append(AudioDefaultFixResult(str(resolved), "skipped", "outside_source").to_dict())
            continue
        try:
            resolved = validate_candidate_for_mutation(raw_path, source, approved_roots)
            result = fix_english_audio_default(
                resolved,
                probe_media=probe_media,
                drop_foreign_audio=drop_foreign_audio,
                progress_callback=progress_callback,
                mutation_source=source,
                approved_roots=approved_roots,
            )
        except SourcePolicyError as exc:
            result = AudioDefaultFixResult(str(resolved), "skipped", f"safety_check_failed: {exc}")
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


def fix_english_audio_default(
    path: Path,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    drop_foreign_audio: bool = False,
    progress_callback: ProgressCallback | None = None,
    mutation_source: Path | None = None,
    approved_roots: ApprovedRoots | None = None,
) -> AudioDefaultFixResult:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        return AudioDefaultFixResult(str(resolved), "skipped", "path_missing")
    if resolved.suffix.lower() not in SUPPORTED_AUDIO_DEFAULT_FIX_EXTENSIONS:
        return AudioDefaultFixResult(str(resolved), "skipped", "unsupported_container")

    try:
        original_facts = probe_media(resolved)
    except Exception as exc:
        return AudioDefaultFixResult(str(resolved), "skipped", f"probe_failed: {exc}")

    audio_streams = list(original_facts.audio_streams)
    if len(audio_streams) < 2:
        return AudioDefaultFixResult(str(resolved), "skipped", "not_multi_audio")

    target_ordinal, target_stream = choose_best_english_audio_stream(audio_streams)
    if target_stream is None:
        return AudioDefaultFixResult(str(resolved), "skipped", "english_audio_missing")

    kept_ordinals = choose_retained_audio_ordinals(audio_streams, drop_foreign_audio=drop_foreign_audio)
    if target_ordinal not in kept_ordinals:
        return AudioDefaultFixResult(str(resolved), "skipped", "english_audio_not_retained")

    default_stream = choose_default_audio_stream(audio_streams)
    if (
        default_stream is not None
        and default_stream.is_default
        and canonical_audio_language(default_stream.language) == "english"
        and target_ordinal == audio_streams.index(default_stream)
        and kept_ordinals == list(range(len(audio_streams)))
    ):
        return AudioDefaultFixResult(str(resolved), "skipped", "already_default_english", facts=original_facts)

    if not drop_foreign_audio and mkvpropedit_available():
        if mutation_source is not None:
            resolved = validate_candidate_for_mutation(resolved, mutation_source, approved_roots)
        command = build_mkvpropedit_command(
            resolved,
            audio_defaults=[index == target_ordinal for index in range(len(audio_streams))],
        )
        try:
            run_mkvpropedit(resolved, command, progress_callback=progress_callback)
            fixed_facts = probe_media(resolved)
            verify_fixed_default_stream(
                fixed_facts.audio_streams,
                target_ordinal=target_ordinal,
                drop_foreign_audio=False,
            )
        except FileNotFoundError:
            pass
        except Exception as exc:
            return AudioDefaultFixResult(str(resolved), "skipped", f"fix_failed: {exc}")
        else:
            return AudioDefaultFixResult(str(resolved), "fixed", "english_default_set", facts=fixed_facts)

    with tempfile.NamedTemporaryFile(
        prefix=f"{resolved.stem}.normal-audio-fix.",
        suffix=resolved.suffix,
        dir=resolved.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    try:
        if mutation_source is not None:
            resolved = validate_candidate_for_mutation(resolved, mutation_source, approved_roots)
        run_ffmpeg_audio_default_fix(
            resolved,
            temp_path,
            len(audio_streams),
            target_ordinal,
            input_duration_seconds=original_facts.runtime_seconds,
            kept_ordinals=kept_ordinals,
            progress_callback=progress_callback,
        )
        fixed_facts = probe_media(temp_path)
        verify_fixed_default_stream(
            fixed_facts.audio_streams,
            target_ordinal=kept_ordinals.index(target_ordinal),
            drop_foreign_audio=drop_foreign_audio,
        )
        if mutation_source is not None:
            resolved = validate_candidate_for_mutation(resolved, mutation_source, approved_roots)
        temp_path.replace(resolved)
        message = "english_default_set"
        removed_count = 0
        removed_bytes = 0
        if drop_foreign_audio:
            removed_count = len(audio_streams) - len(kept_ordinals)
            original_size = original_facts.file_size_bytes or 0
            fixed_size = fixed_facts.file_size_bytes or 0
            removed_bytes = max(original_size - fixed_size, 0)
            message = "english_default_set_and_removed_foreign_audio" if removed_count > 0 else "english_default_set_no_foreign_audio_removed"
        return AudioDefaultFixResult(
            str(resolved),
            "fixed",
            message,
            facts=fixed_facts,
            removed_audio_tracks=removed_count,
            removed_audio_bytes=removed_bytes,
        )
    except FileNotFoundError:
        return AudioDefaultFixResult(str(resolved), "skipped", "ffmpeg_missing")
    except Exception as exc:
        return AudioDefaultFixResult(str(resolved), "skipped", f"fix_failed: {exc}")
    finally:
        temp_path.unlink(missing_ok=True)


def choose_best_english_audio_stream(streams: list[AudioStreamFacts]) -> tuple[int | None, AudioStreamFacts | None]:
    english_streams = [
        (index, stream)
        for index, stream in enumerate(streams)
        if canonical_audio_language(stream.language) == "english"
    ]
    if not english_streams:
        return None, None
    return max(english_streams, key=lambda item: audio_stream_quality_key(item[1]))


def choose_retained_audio_ordinals(streams: list[AudioStreamFacts], *, drop_foreign_audio: bool) -> list[int]:
    if not drop_foreign_audio:
        return list(range(len(streams)))
    kept_ordinals = [
        index
        for index, stream in enumerate(streams)
        if canonical_audio_language(stream.language) in {None, "english"}
    ]
    return kept_ordinals or list(range(len(streams)))


def run_ffmpeg_audio_default_fix(
    path: Path,
    temp_path: Path,
    audio_stream_count: int,
    target_ordinal: int,
    input_duration_seconds: int | None,
    *,
    kept_ordinals: list[int],
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
    ]
    removed_ordinals = [ordinal for ordinal in range(audio_stream_count) if ordinal not in kept_ordinals]
    for ordinal in removed_ordinals:
        command.extend(["-map", f"-0:a:{ordinal}"])
    command.extend(
        [
        "-map_metadata",
        "0",
        "-map_chapters",
        "0",
        "-c",
        "copy",
        ]
    )
    for output_ordinal, original_ordinal in enumerate(kept_ordinals):
        command.extend(
            [
                f"-disposition:a:{output_ordinal}",
                "default" if original_ordinal == target_ordinal else "0",
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


def verify_fixed_default_stream(streams: list[AudioStreamFacts], target_ordinal: int, *, drop_foreign_audio: bool) -> None:
    defaults = [index for index, stream in enumerate(streams) if stream.is_default]
    if defaults != [target_ordinal]:
        raise RuntimeError("verification_failed_default_track")
    default_stream = streams[target_ordinal]
    if canonical_audio_language(default_stream.language) != "english":
        raise RuntimeError("verification_failed_non_english_default")
    if drop_foreign_audio:
        for stream in streams:
            language = canonical_audio_language(stream.language)
            if language is not None and language != "english":
                raise RuntimeError("verification_failed_foreign_audio_retained")


def build_ffmpeg_progress_update(
    progress_state: dict[str, str],
    input_duration_seconds: int | None,
    source_path: Path,
    temp_path: Path,
) -> dict[str, Any]:
    completed_seconds = parse_ffmpeg_out_time_seconds(progress_state)
    progress_fraction = None
    eta_seconds = None
    if input_duration_seconds and input_duration_seconds > 0 and completed_seconds is not None:
        progress_fraction = min(max(completed_seconds / input_duration_seconds, 0.0), 1.0)
        if progress_fraction > 0 and progress_fraction < 1:
            elapsed = time_elapsed_seconds(progress_state)
            if elapsed is not None and elapsed > 0:
                eta_seconds = max(int(round(elapsed * (1 - progress_fraction) / progress_fraction)), 0)
    return {
        "current_path": str(source_path.resolve()),
        "output_path": str(temp_path.resolve()),
        "status_text": "ffmpeg remux active",
        "progress_state": progress_state.get("progress"),
        "completed_seconds": completed_seconds,
        "total_seconds": input_duration_seconds,
        "progress_fraction": progress_fraction,
        "eta_seconds": eta_seconds,
        "output_size_bytes": parse_int(progress_state.get("total_size")),
        "speed": first_text(progress_state.get("speed")),
    }


def parse_ffmpeg_out_time_seconds(progress_state: dict[str, str]) -> float | None:
    if progress_state.get("out_time_ms"):
        try:
            return int(progress_state["out_time_ms"]) / 1_000_000
        except ValueError:
            return None
    if progress_state.get("out_time_us"):
        try:
            return int(progress_state["out_time_us"]) / 1_000_000
        except ValueError:
            return None
    return None


def time_elapsed_seconds(progress_state: dict[str, str]) -> float | None:
    speed = progress_state.get("speed")
    completed = parse_ffmpeg_out_time_seconds(progress_state)
    if completed is None or not speed:
        return None
    try:
        normalized = speed.rstrip("x")
        speed_value = float(normalized)
    except ValueError:
        return None
    if speed_value <= 0:
        return None
    return completed / speed_value


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def first_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
