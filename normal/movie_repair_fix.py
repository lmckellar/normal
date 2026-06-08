from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Callable

from normal.movie_audio_fix import (
    ProgressCallback,
    build_ffmpeg_progress_update,
    choose_retained_audio_ordinals,
)
from normal.movie_profile import load_library_policy, normalized_subtitle_preferences
from normal.movie_repair_planner import build_movie_repair_plan, subtitle_disposition_value
from normal.movie_scan import probe_media_facts
from normal.quality_review import MediaFacts


SUPPORTED_REPAIR_EXTENSIONS = {".mkv"}


@dataclass(slots=True)
class RepairDefaultsFixResult:
    path: str
    status: str
    message: str
    facts: MediaFacts | None = None
    removed_audio_tracks: int = 0
    removed_audio_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fix_movie_repair_defaults(
    source_root: Path,
    paths: list[str],
    *,
    include_audio: bool,
    include_subtitle: bool,
    drop_foreign_audio: bool = False,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: ProgressCallback | None = None,
    subtitle_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    fixed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    active_subtitle_preferences = subtitle_preferences or normalized_subtitle_preferences(
        load_library_policy().get("subtitle_preferences")
    )

    for raw_path in paths:
        resolved = Path(str(raw_path)).expanduser().resolve()
        try:
            resolved.relative_to(source)
        except ValueError:
            skipped.append(RepairDefaultsFixResult(str(resolved), "skipped", "outside_source").to_dict())
            continue
        result = fix_movie_repair_default(
            resolved,
            include_audio=include_audio,
            include_subtitle=include_subtitle,
            drop_foreign_audio=drop_foreign_audio,
            probe_media=probe_media,
            progress_callback=progress_callback,
            subtitle_preferences=active_subtitle_preferences,
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


def fix_movie_repair_default(
    path: Path,
    *,
    include_audio: bool,
    include_subtitle: bool,
    drop_foreign_audio: bool = False,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: ProgressCallback | None = None,
    subtitle_preferences: dict[str, Any] | None = None,
) -> RepairDefaultsFixResult:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        return RepairDefaultsFixResult(str(resolved), "skipped", "path_missing")
    if resolved.suffix.lower() not in SUPPORTED_REPAIR_EXTENSIONS:
        return RepairDefaultsFixResult(str(resolved), "skipped", "unsupported_container")

    try:
        original_facts = probe_media(resolved)
    except Exception as exc:
        return RepairDefaultsFixResult(str(resolved), "skipped", f"probe_failed: {exc}")

    active_subtitle_preferences = subtitle_preferences or normalized_subtitle_preferences(
        load_library_policy().get("subtitle_preferences")
    )
    plan = build_movie_repair_plan(
        original_facts,
        path=str(resolved),
        subtitle_preferences=active_subtitle_preferences,
    )
    execution = build_execution_plan(
        original_facts,
        plan,
        include_audio=include_audio,
        include_subtitle=include_subtitle,
        drop_foreign_audio=drop_foreign_audio,
    )
    if not execution["run_mux"]:
        return RepairDefaultsFixResult(str(resolved), "skipped", "already_repaired", facts=original_facts)

    with tempfile.NamedTemporaryFile(
        prefix=f"{resolved.stem}.normal-repair-fix.",
        suffix=resolved.suffix,
        dir=resolved.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)

    try:
        run_ffmpeg_repair_defaults_fix(
            resolved,
            temp_path,
            original_facts=original_facts,
            execution=execution,
            progress_callback=progress_callback,
        )
        fixed_facts = probe_media(temp_path)
        verify_repair_defaults_result(fixed_facts, execution)
        temp_path.replace(resolved)
        removed_count = 0
        removed_bytes = 0
        if execution["drop_foreign_audio"]:
            removed_count = len(original_facts.audio_streams) - len(execution["kept_audio_ordinals"])
            original_size = original_facts.file_size_bytes or 0
            fixed_size = fixed_facts.file_size_bytes or 0
            removed_bytes = max(original_size - fixed_size, 0)
        return RepairDefaultsFixResult(
            str(resolved),
            "fixed",
            execution_result_message(execution),
            facts=fixed_facts,
            removed_audio_tracks=removed_count,
            removed_audio_bytes=removed_bytes,
        )
    except FileNotFoundError:
        return RepairDefaultsFixResult(str(resolved), "skipped", "ffmpeg_missing")
    except Exception as exc:
        return RepairDefaultsFixResult(str(resolved), "skipped", f"fix_failed: {exc}")
    finally:
        temp_path.unlink(missing_ok=True)


def build_execution_plan(
    facts: MediaFacts,
    repair_plan: dict[str, Any],
    *,
    include_audio: bool,
    include_subtitle: bool,
    drop_foreign_audio: bool,
) -> dict[str, Any]:
    audio_plan = repair_plan.get("audio") or {}
    subtitle_plan = repair_plan.get("subtitle") or {}
    combined_plan = repair_plan.get("combined") or {}

    audio_mutation = bool(include_audio and audio_plan.get("repairable"))
    apply_drop_foreign_audio = bool(audio_mutation and drop_foreign_audio)
    kept_audio_ordinals = choose_retained_audio_ordinals(
        list(facts.audio_streams),
        drop_foreign_audio=apply_drop_foreign_audio,
    )
    subtitle_after_audio = combined_plan.get("subtitle_after_audio") or subtitle_plan
    effective_subtitle = subtitle_after_audio if audio_mutation else subtitle_plan
    subtitle_mutation = bool(include_subtitle and effective_subtitle.get("repairable"))

    run_mux = audio_mutation or subtitle_mutation or len(kept_audio_ordinals) != len(facts.audio_streams)
    return {
        "run_mux": run_mux,
        "audio_mutation": audio_mutation,
        "subtitle_mutation": subtitle_mutation,
        "drop_foreign_audio": apply_drop_foreign_audio,
        "kept_audio_ordinals": kept_audio_ordinals,
        "target_audio_ordinal": audio_plan.get("target_ordinal") if audio_mutation else None,
        "target_subtitle_ordinal": effective_subtitle.get("target_ordinal") if subtitle_mutation else None,
        "subtitle_mode": effective_subtitle.get("mode") if subtitle_mutation else None,
        "second_order_subtitle": bool(audio_mutation and combined_plan.get("second_order_subtitle")),
        "subtitle_changes_after_audio": bool(audio_mutation and combined_plan.get("subtitle_changes_after_audio")),
        "families": [
            family
            for family, enabled in (
                ("audio", audio_mutation or len(kept_audio_ordinals) != len(facts.audio_streams)),
                ("subtitle", subtitle_mutation),
            )
            if enabled
        ],
    }


def run_ffmpeg_repair_defaults_fix(
    path: Path,
    temp_path: Path,
    *,
    original_facts: MediaFacts,
    execution: dict[str, Any],
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
    removed_ordinals = [
        ordinal
        for ordinal in range(len(original_facts.audio_streams))
        if ordinal not in execution["kept_audio_ordinals"]
    ]
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
    if execution["audio_mutation"] or execution["drop_foreign_audio"]:
        for output_ordinal, original_ordinal in enumerate(execution["kept_audio_ordinals"]):
            command.extend(
                [
                    f"-disposition:a:{output_ordinal}",
                    "default" if original_ordinal == execution["target_audio_ordinal"] else "0",
                ]
            )
    if execution["subtitle_mutation"]:
        target_subtitle_ordinal = execution["target_subtitle_ordinal"]
        for output_ordinal in range(len(original_facts.subtitle_streams)):
            command.extend(
                [
                    f"-disposition:s:{output_ordinal}",
                    subtitle_disposition_value(
                        is_default=output_ordinal == target_subtitle_ordinal,
                        is_forced=original_facts.subtitle_streams[output_ordinal].is_forced,
                    ),
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
            progress_callback(build_ffmpeg_progress_update(progress_state, original_facts.runtime_seconds, path, temp_path))
    stderr = process.stderr.read() if process.stderr is not None else ""
    result_code = process.wait()
    if progress_callback is not None:
        progress_callback(build_ffmpeg_progress_update(progress_state, original_facts.runtime_seconds, path, temp_path))
    if result_code != 0:
        message = stderr.strip() or "ffmpeg failed"
        raise RuntimeError(message)


def verify_repair_defaults_result(facts: MediaFacts, execution: dict[str, Any]) -> None:
    if execution["audio_mutation"] or execution["drop_foreign_audio"]:
        defaults = [index for index, stream in enumerate(facts.audio_streams) if stream.is_default]
        target_audio_ordinal = execution["kept_audio_ordinals"].index(execution["target_audio_ordinal"])
        if defaults != [target_audio_ordinal]:
            raise RuntimeError("verification_failed_default_audio")
    if execution["drop_foreign_audio"]:
        for stream in facts.audio_streams:
            language = str(stream.language or "").strip().casefold()
            if language and language not in {"eng", "en", "english"}:
                raise RuntimeError("verification_failed_foreign_audio_retained")
    if execution["subtitle_mutation"]:
        defaults = [index for index, stream in enumerate(facts.subtitle_streams) if stream.is_default]
        if execution["target_subtitle_ordinal"] is None:
            if defaults:
                raise RuntimeError("verification_failed_default_subtitle_present")
        elif defaults != [execution["target_subtitle_ordinal"]]:
            raise RuntimeError("verification_failed_default_subtitle")


def execution_result_message(execution: dict[str, Any]) -> str:
    if execution["audio_mutation"] and execution["subtitle_mutation"] and execution["drop_foreign_audio"]:
        return "english_default_subtitle_normalized_and_foreign_audio_removed"
    if execution["audio_mutation"] and execution["subtitle_mutation"]:
        return "english_default_and_subtitle_normalized"
    if execution["audio_mutation"] and execution["drop_foreign_audio"]:
        return "english_default_set_and_removed_foreign_audio"
    if execution["audio_mutation"]:
        return "english_default_set"
    if execution["subtitle_mutation"]:
        return "subtitle_defaults_normalized"
    return "already_repaired"
