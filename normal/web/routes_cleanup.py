from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from normal.audit import (
    AuditEffect,
    AuditEvent,
    AuditFollowUpUpdate,
    AuditSubject,
    FOLLOW_UP_KIND_REPLACEMENT,
    make_event_id,
    make_follow_up_id,
)
from normal.models import utc_now_iso
from normal.movie_audio_fix import fix_english_audio_defaults
from normal.movie_junk import (
    detect_movie_junk_document_reasons,
    detect_movie_junk_reasons,
    scan_movie_cleanup,
)
from normal.movie_repair_fix import fix_movie_repair_defaults
from normal.movie_subtitle_fix import fix_movie_subtitle_defaults
from normal.movie_scan import VIDEO_EXTENSIONS
from normal.movie_profile import load_operator_preferences, normalize_delete_mode
from normal.pathsafe import contained_resolve
from normal.source_policy import enforce_source_policy

from .activity import tracked_probe
from .http import RequestContext
from .routes_audit import normalize_subject_from_path, record_scan_event
from .scan_guard import guarded_heavy_scan
from .serializers import build_updated_profile_items
from .state import AUDIT_STORE, MOVIE_CANONICAL_CACHE, MOVIE_PROFILE_CACHE, PROBE_CACHE


SAFE_MOVIE_SIDECAR_EXTENSIONS = {
    ".ass",
    ".htm",
    ".html",
    ".idx",
    ".jpeg",
    ".jpg",
    ".nfo",
    ".png",
    ".srt",
    ".ssa",
    ".sub",
    ".sup",
    ".txt",
    ".url",
    ".vtt",
    ".webp",
    ".xml",
}
RECYCLE_COMMANDS = (
    ("gio", "trash"),
    ("trash-put",),
)


def delete_mode_for_kind(kind: str, preferences: dict[str, Any] | None = None) -> str:
    mode = normalize_delete_mode((preferences or load_operator_preferences()).get("delete_mode"))
    if mode == "hard_delete_all":
        return "hard_delete"
    if mode == "recycle_all":
        return "recycle"
    if mode == "hybrid_media_to_bin_junk_hard_delete":
        return "hard_delete" if kind == "junk" else "recycle"
    if mode == "hybrid_junk_to_bin_media_hard_delete":
        return "recycle" if kind == "junk" else "hard_delete"
    return "recycle"


def move_path_to_recycle_bin(path: Path) -> None:
    for command in RECYCLE_COMMANDS:
        if shutil.which(command[0]) is None:
            continue
        subprocess.run([*command, str(path)], check=True, capture_output=True, text=True)
        return
    raise RuntimeError("Recycle mode is configured, but no supported trash command is available.")


def execute_delete_path(path: Path, kind: str, preferences: dict[str, Any] | None = None) -> str:
    action = delete_mode_for_kind(kind, preferences)
    if action == "recycle":
        move_path_to_recycle_bin(path)
    elif path.is_dir():
        path.rmdir()
    else:
        path.unlink()
    return action


def delete_movie_junk_files(
    source: Path,
    raw_paths: list[Any],
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_root = source.resolve()
    deleted = []
    deleted_media: list[dict[str, Any]] = []
    skipped = []

    for raw_path in raw_paths:
        resolved, contained = contained_resolve(raw_path, source_root)
        if not contained:
            skipped.append({"path": str(resolved), "reason": "outside_source"})
            continue
        if not resolved.exists() or not resolved.is_file():
            skipped.append({"path": str(resolved), "reason": "not_file"})
            continue
        reasons = detect_movie_junk_reasons(resolved)
        if not reasons:
            reasons = detect_movie_junk_document_reasons(resolved)
        if not reasons:
            skipped.append({"path": str(resolved), "reason": "not_current_junk_candidate"})
            continue
        size_bytes = resolved.stat().st_size
        execute_delete_path(resolved, "junk", preferences)
        deleted.append(str(resolved))
        deleted_media.append({"path": str(resolved), "size_bytes": size_bytes})

    return {"deleted": deleted, "deleted_media": deleted_media, "skipped": skipped}


def handle_movies_junk(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    with guarded_heavy_scan(source, "Movie junk scan"):
        with ctx.handler.activity_tracker.track(source, "Movie junk scan"):
            report = scan_movie_cleanup(
                source,
                probe_media=tracked_probe(source, "ffprobe movie junk", cache=PROBE_CACHE),
            )
    document_junk_count = sum(1 for item in report.junk if Path(item.path).suffix.lower() in {".txt", ".html", ".htm"})
    record_scan_event(
        source,
        workflow="junk",
        label="Movie junk scan",
        metadata={
            "video_junk_count": len(report.junk) - document_junk_count,
            "document_junk_count": document_junk_count,
        },
    )
    ctx.respond_json(report.to_dict())


def handle_movies_junk_delete(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    enforce_source_policy(source, operation="mutate")
    with ctx.handler.activity_tracker.track(source, "Movie junk delete"):
        result = delete_movie_junk_files(source, paths, load_operator_preferences())
    _record_junk_delete_event(source, result)
    ctx.respond_json(result)


def is_safe_movie_sidecar(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SAFE_MOVIE_SIDECAR_EXTENSIONS


def preview_safe_movie_sidecar_cleanup(
    source: Path,
    folder: Path,
    deleted_paths: set[Path] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"sidecars": [], "folder": None}
    if not folder.exists() or not folder.is_dir() or folder == source:
        return result
    try:
        folder.relative_to(source)
    except ValueError:
        return result

    deleted = {path.resolve() for path in (deleted_paths or set())}
    entries = [entry for entry in folder.iterdir() if entry.resolve() not in deleted]
    if not entries:
        result["folder"] = str(folder)
        return result
    if any(entry.is_dir() for entry in entries):
        return result
    if any(entry.suffix.lower() in VIDEO_EXTENSIONS for entry in entries):
        return result
    if any(not is_safe_movie_sidecar(entry) for entry in entries):
        return result

    result["sidecars"] = [str(entry) for entry in entries]
    result["folder"] = str(folder)
    return result


def cleanup_safe_movie_sidecars(
    source: Path,
    folder: Path,
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = preview_safe_movie_sidecar_cleanup(source, folder)
    if not result["folder"]:
        return result
    for sidecar in result["sidecars"]:
        sidecar_path = Path(sidecar)
        if sidecar_path.exists():
            execute_delete_path(sidecar_path, "media", preferences)
    if folder.exists():
        execute_delete_path(folder, "media", preferences)
    return result


def preview_movie_delete(source_root: Path, paths: list[Any]) -> dict[str, Any]:
    source = source_root.resolve()
    deleted: list[str] = []
    cleaned_sidecars: list[str] = []
    removed_folders: list[str] = []
    skipped: list[dict[str, str]] = []

    for raw_path in paths:
        resolved, contained = contained_resolve(raw_path, source)
        if not contained:
            skipped.append({"path": str(resolved), "reason": "outside_source"})
            continue
        if resolved == source:
            skipped.append({"path": str(resolved), "reason": "source_root"})
            continue
        if not resolved.exists():
            skipped.append({"path": str(resolved), "reason": "missing"})
            continue
        if not resolved.is_file():
            skipped.append({"path": str(resolved), "reason": "not_file"})
            continue
        deleted.append(str(resolved))
        cleanup = preview_safe_movie_sidecar_cleanup(source, resolved.parent, deleted_paths={resolved})
        cleaned_sidecars.extend(cleanup["sidecars"])
        if cleanup["folder"]:
            removed_folders.append(cleanup["folder"])

    return {
        "deleted": deleted,
        "cleaned_sidecars": cleaned_sidecars,
        "removed_folders": removed_folders,
        "skipped": skipped,
    }


def delete_movie_files(
    source_root: Path,
    paths: list[Any],
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    deleted: list[str] = []
    deleted_media: list[dict[str, Any]] = []
    cleaned_sidecars: list[str] = []
    removed_folders: list[str] = []
    skipped: list[dict[str, str]] = []

    for raw_path in paths:
        resolved, contained = contained_resolve(raw_path, source)
        if not contained:
            skipped.append({"path": str(resolved), "reason": "outside_source"})
            continue
        if resolved == source:
            skipped.append({"path": str(resolved), "reason": "source_root"})
            continue
        if not resolved.exists():
            skipped.append({"path": str(resolved), "reason": "missing"})
            continue
        if not resolved.is_file():
            skipped.append({"path": str(resolved), "reason": "not_file"})
            continue
        size_bytes = resolved.stat().st_size
        execute_delete_path(resolved, "media", preferences)
        deleted.append(str(resolved))
        deleted_media.append({"path": str(resolved), "size_bytes": size_bytes})
        cleanup = cleanup_safe_movie_sidecars(source, resolved.parent, preferences)
        cleaned_sidecars.extend(cleanup["sidecars"])
        if cleanup["folder"]:
            removed_folders.append(cleanup["folder"])

    return {
        "deleted": deleted,
        "deleted_media": deleted_media,
        "cleaned_sidecars": cleaned_sidecars,
        "removed_folders": removed_folders,
        "skipped": skipped,
    }


def handle_movies_delete_preview(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    ctx.respond_json(preview_movie_delete(source, paths))


def handle_movies_delete(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    issue_family = str(payload.get("issue_family") or "").strip() or None
    enforce_source_policy(source, operation="mutate")
    with ctx.handler.activity_tracker.track(source, "Movie delete"):
        result = delete_movie_files(source, paths, load_operator_preferences())
    _record_media_delete_event(source, result, issue_family=issue_family)
    if result["deleted"]:
        MOVIE_PROFILE_CACHE.invalidate(source)
        MOVIE_CANONICAL_CACHE.invalidate(source)
    ctx.respond_json(result)


def handle_movies_audio_packaging_fix(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    drop_foreign_audio = bool(payload.get("drop_foreign_audio"))
    enforce_source_policy(source, operation="mutate")
    label = "Movie audio fix: make English default + drop foreign audio" if drop_foreign_audio else "Movie audio fix: make English default"
    with ctx.handler.activity_tracker.track(source, label, kind="remux") as activity_id:
        result = fix_english_audio_defaults(
            source,
            [str(path) for path in paths],
            probe_media=tracked_probe(source, "ffprobe audio packaging fix", cache=PROBE_CACHE),
            drop_foreign_audio=drop_foreign_audio,
            progress_callback=lambda update: ctx.handler.activity_tracker.update(activity_id, **update),
        )
    if result["fixed"]:
        MOVIE_PROFILE_CACHE.invalidate(source)
        MOVIE_CANONICAL_CACHE.invalidate(source)
    result["updated_items"] = build_updated_profile_items(source, result["fixed"], resolve_language=ctx.language_resolver())
    removed_audio = _summarize_removed_audio_from_fixed(result.get("fixed", []))
    _record_repair_event(
        source,
        workflow="audio_packaging",
        action="repair",
        summary=(
            _repair_summary(
                fixed_count=len(result["fixed"]),
                base_label="audio defaults",
                removed_audio_tracks=removed_audio["count"] if drop_foreign_audio else 0,
            )
            if result["fixed"]
            else "Audio defaults repair made no changes."
        ),
        fixed_paths=result["fixed"],
        metadata={
            "drop_foreign_audio": drop_foreign_audio,
            "skipped": result.get("skipped", []),
            "audio_tracks_removed": removed_audio,
        },
    )
    ctx.respond_json(result)


def handle_movies_subtitle_readiness_fix(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    enforce_source_policy(source, operation="mutate")
    with ctx.handler.activity_tracker.track(source, "Movie subtitle fix: repair defaults", kind="remux") as activity_id:
        result = fix_movie_subtitle_defaults(
            source,
            [str(path) for path in paths],
            probe_media=tracked_probe(source, "ffprobe subtitle readiness fix", cache=PROBE_CACHE),
            progress_callback=lambda update: ctx.handler.activity_tracker.update(activity_id, **update),
        )
    result["updated_items"] = build_updated_profile_items(source, result["fixed"], resolve_language=ctx.language_resolver())
    if result["updated_items"]:
        MOVIE_PROFILE_CACHE.invalidate(source)
        MOVIE_CANONICAL_CACHE.invalidate(source)
    _record_repair_event(
        source,
        workflow="subtitle_readiness",
        action="repair",
        summary=(
            f"Repaired subtitle defaults for {len(result['fixed'])} title{'s' if len(result['fixed']) != 1 else ''}."
            if result["fixed"]
            else "Subtitle defaults repair made no changes."
        ),
        fixed_paths=result["fixed"],
        metadata={"skipped": result.get("skipped", [])},
    )
    ctx.respond_json(result)


def handle_movies_repair_defaults_fix(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    enforce_source_policy(source, operation="mutate")
    include_audio = bool(payload.get("include_audio"))
    include_subtitle = bool(payload.get("include_subtitle"))
    if not include_audio and not include_subtitle:
        raise ValueError("at least one repair family must be enabled")
    drop_foreign_audio = bool(payload.get("drop_foreign_audio"))
    if drop_foreign_audio and not include_audio:
        raise ValueError("drop_foreign_audio requires audio repair")
    label_parts = []
    if include_audio:
        label_parts.append("audio default")
    if drop_foreign_audio:
        label_parts.append("foreign-audio prune")
    if include_subtitle:
        label_parts.append("subtitle default")
    label = "Movie repair defaults: " + " + ".join(label_parts)
    with ctx.handler.activity_tracker.track(source, label, kind="remux") as activity_id:
        result = fix_movie_repair_defaults(
            source,
            [str(path) for path in paths],
            include_audio=include_audio,
            include_subtitle=include_subtitle,
            drop_foreign_audio=drop_foreign_audio,
            probe_media=tracked_probe(source, "ffprobe repair defaults fix", cache=PROBE_CACHE),
            progress_callback=lambda update: ctx.handler.activity_tracker.update(activity_id, **update),
        )
    result["updated_items"] = build_updated_profile_items(source, result["fixed"], resolve_language=ctx.language_resolver())
    if result["updated_items"]:
        MOVIE_PROFILE_CACHE.invalidate(source)
        MOVIE_CANONICAL_CACHE.invalidate(source)
    removed_audio = _summarize_removed_audio_from_fixed(result.get("fixed", []))
    summary_bits = []
    if include_audio:
        summary_bits.append("audio defaults")
    if drop_foreign_audio:
        summary_bits.append("foreign-audio prune")
    if include_subtitle:
        summary_bits.append("subtitle defaults")
    _record_repair_event(
        source,
        workflow="repair_defaults",
        action="repair",
        summary=(
            _repair_summary(
                fixed_count=len(result["fixed"]),
                base_label=_join_repair_labels(summary_bits),
                removed_audio_tracks=removed_audio["count"] if drop_foreign_audio else 0,
            )
            if result["fixed"]
            else "Repair defaults action made no changes."
        ),
        fixed_paths=result["fixed"],
        metadata={
            "include_audio": include_audio,
            "include_subtitle": include_subtitle,
            "drop_foreign_audio": drop_foreign_audio,
            "skipped": result.get("skipped", []),
            "audio_tracks_removed": removed_audio,
        },
    )
    ctx.respond_json(result)


def _record_junk_delete_event(source: Path, result: dict[str, Any]) -> None:
    if not result.get("deleted") and not result.get("skipped"):
        return
    recorded_at = utc_now_iso()
    effects = [
        AuditEffect(kind="junk_delete", status="applied", path=str(path), message="Junk file deleted.")
        for path in result.get("deleted", [])
    ]
    effects.extend(
        AuditEffect(
            kind="junk_delete",
            status="skipped",
            path=str(item.get("path") or "") or None,
            message=str(item.get("reason") or "skipped"),
        )
        for item in result.get("skipped", [])
        if isinstance(item, dict)
    )
    deleted_media = [item for item in result.get("deleted_media", []) if isinstance(item, dict)]
    event = AuditEvent(
        event_id=make_event_id(str(source.resolve()), "junk", "delete", recorded_at, salt=str(len(effects))),
        recorded_at=recorded_at,
        source_root=str(source.resolve()),
        workflow="junk",
        action="delete",
        summary=f"Deleted {len(result.get('deleted', []))} junk file{'s' if len(result.get('deleted', [])) != 1 else ''}.",
        subjects=[AuditSubject(kind="file", path=str(path)) for path in result.get("deleted", [])],
        effects=effects,
        metadata={
            "deleted_media": deleted_media,
            "skipped": result.get("skipped", []),
        },
    )
    AUDIT_STORE.append(event)


def _record_media_delete_event(source: Path, result: dict[str, Any], *, issue_family: str | None) -> None:
    deleted = [str(path) for path in result.get("deleted", [])]
    deleted_media = [item for item in result.get("deleted_media", []) if isinstance(item, dict)]
    skipped = [item for item in result.get("skipped", []) if isinstance(item, dict)]
    if not deleted and not skipped:
        return
    recorded_at = utc_now_iso()
    subjects = [normalize_subject_from_path(Path(path), issue_family=issue_family) for path in deleted]
    effects = [AuditEffect(kind="delete", status="applied", path=path, message="Media file deleted.") for path in deleted]
    effects.extend(
        AuditEffect(kind="cleanup_sidecar_delete", status="applied", path=str(path), message="Safe sidecar deleted.")
        for path in result.get("cleaned_sidecars", [])
    )
    effects.extend(
        AuditEffect(kind="cleanup_folder_delete", status="applied", path=str(path), message="Empty folder removed.")
        for path in result.get("removed_folders", [])
    )
    effects.extend(
        AuditEffect(
            kind="delete",
            status="skipped",
            path=str(item.get("path") or "") or None,
            message=str(item.get("reason") or "skipped"),
        )
        for item in skipped
    )
    follow_up_updates: list[AuditFollowUpUpdate] = []
    if issue_family in {"weak_encode", "audio_packaging"}:
        for subject in subjects:
            follow_up_id = make_follow_up_id(
                str(source.resolve()),
                FOLLOW_UP_KIND_REPLACEMENT,
                issue_family,
                subject.title,
                subject.year,
                subject.path,
            )
            follow_up_updates.append(
                AuditFollowUpUpdate(
                    follow_up_id=follow_up_id,
                    kind=FOLLOW_UP_KIND_REPLACEMENT,
                    action="create",
                    status="active",
                    summary=f"{subject.title or Path(subject.path or '').stem} is awaiting replacement.",
                    details={
                        "path": subject.path,
                        "title": subject.title,
                        "year": subject.year,
                        "issue_family": issue_family,
                    },
                )
            )
    summary = f"Deleted {len(deleted)} media file{'s' if len(deleted) != 1 else ''}."
    if issue_family in {"weak_encode", "audio_packaging"} and deleted:
        summary = f"Deleted {len(deleted)} {issue_family.replace('_', ' ')} file{'s' if len(deleted) != 1 else ''}."
    event = AuditEvent(
        event_id=make_event_id(str(source.resolve()), issue_family or "movies", "delete", recorded_at, salt=str(len(deleted))),
        recorded_at=recorded_at,
        source_root=str(source.resolve()),
        workflow=issue_family or "movies",
        action="delete",
        summary=summary,
        subjects=subjects,
        effects=effects,
        follow_up_updates=follow_up_updates,
        metadata={
            "deleted_media": deleted_media,
            "cleaned_sidecars": result.get("cleaned_sidecars", []),
            "removed_folders": result.get("removed_folders", []),
            "skipped": skipped,
        },
    )
    AUDIT_STORE.append(event)


def _record_repair_event(
    source: Path,
    *,
    workflow: str,
    action: str,
    summary: str,
    fixed_paths: list[Any],
    metadata: dict[str, Any],
) -> None:
    normalized_paths = _normalized_repair_paths(fixed_paths)
    if not normalized_paths and not metadata.get("skipped"):
        return
    recorded_at = utc_now_iso()
    event = AuditEvent(
        event_id=make_event_id(str(source.resolve()), workflow, action, recorded_at, salt=str(len(normalized_paths))),
        recorded_at=recorded_at,
        source_root=str(source.resolve()),
        workflow=workflow,
        action=action,
        summary=summary,
        subjects=[normalize_subject_from_path(Path(path), issue_family=workflow) for path in normalized_paths],
        effects=_repair_effects(fixed_paths, summary),
        reversal={"capability": "none"},
        metadata=metadata,
    )
    AUDIT_STORE.append(event)


def _normalized_repair_paths(fixed_paths: list[Any]) -> list[str]:
    normalized_paths: list[str] = []
    for item in fixed_paths:
        path_value = item.get("path") if isinstance(item, dict) else item
        raw_path = str(path_value or "").strip()
        if not raw_path:
            continue
        normalized_paths.append(str(Path(raw_path).expanduser().resolve()))
    return normalized_paths


def _summarize_removed_audio_from_fixed(fixed_items: list[Any]) -> dict[str, int]:
    count = 0
    total_bytes = 0
    for item in fixed_items:
        if not isinstance(item, dict):
            continue
        count += max(int(item.get("removed_audio_tracks") or 0), 0)
        total_bytes += max(int(item.get("removed_audio_bytes") or 0), 0)
    return {"count": count, "total_bytes": total_bytes}


def _join_repair_labels(labels: list[str]) -> str:
    active = [str(label).strip() for label in labels if str(label).strip()]
    if not active:
        return "repairs"
    if len(active) == 1:
        return active[0]
    if len(active) == 2:
        return f"{active[0]} and {active[1]}"
    return f"{', '.join(active[:-1])}, and {active[-1]}"


def _repair_summary(*, fixed_count: int, base_label: str, removed_audio_tracks: int = 0) -> str:
    summary = f"Repaired {base_label} for {fixed_count} title{'s' if fixed_count != 1 else ''}."
    if removed_audio_tracks > 0:
        summary += (
            f" Removed {removed_audio_tracks} foreign audio "
            f"track{'s' if removed_audio_tracks != 1 else ''}."
        )
    return summary


def _repair_effects(fixed_paths: list[Any], summary: str) -> list[AuditEffect]:
    effects: list[AuditEffect] = []
    for item in fixed_paths:
        path_value = item.get("path") if isinstance(item, dict) else item
        raw_path = str(path_value or "").strip()
        if not raw_path:
            continue
        details: dict[str, Any] = {}
        if isinstance(item, dict):
            details = {
                "message": str(item.get("message") or "").strip(),
                "removed_audio_tracks": max(int(item.get("removed_audio_tracks") or 0), 0),
                "removed_audio_bytes": max(int(item.get("removed_audio_bytes") or 0), 0),
            }
        effects.append(
            AuditEffect(
                kind="remux_repair",
                status="applied",
                path=str(Path(raw_path).expanduser().resolve()),
                message=summary,
                details=details,
            )
        )
    return effects
