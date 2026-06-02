from __future__ import annotations

from pathlib import Path
from typing import Any

from normal.movie_audio_fix import fix_english_audio_defaults
from normal.movie_junk import (
    detect_movie_junk_document_reasons,
    detect_movie_junk_reasons,
    scan_movie_cleanup,
)
from normal.movie_subtitle_fix import fix_movie_subtitle_defaults
from normal.movie_scan import VIDEO_EXTENSIONS

from .activity import tracked_probe
from .http import RequestContext
from .scan_guard import guarded_heavy_scan
from .serializers import build_updated_profile_items
from .state import MOVIE_PROFILE_CACHE, PROBE_CACHE


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


def delete_movie_junk_files(
    source: Path,
    raw_paths: list[Any],
) -> dict[str, Any]:
    source_root = source.resolve()
    deleted = []
    skipped = []

    for raw_path in raw_paths:
        resolved = Path(str(raw_path)).expanduser().resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError:
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
        resolved.unlink()
        deleted.append(str(resolved))

    return {"deleted": deleted, "skipped": skipped}


def handle_movies_junk(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    with guarded_heavy_scan(source, "Movie junk scan"):
        with ctx.handler.activity_tracker.track(source, "Movie junk scan"):
            report = scan_movie_cleanup(
                source,
                probe_media=tracked_probe(source, "ffprobe movie junk", cache=PROBE_CACHE),
            )
    ctx.respond_json(report.to_dict())


def handle_movies_junk_delete(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    with ctx.handler.activity_tracker.track(source, "Movie junk delete"):
        result = delete_movie_junk_files(source, paths)
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


def cleanup_safe_movie_sidecars(source: Path, folder: Path) -> dict[str, Any]:
    result = preview_safe_movie_sidecar_cleanup(source, folder)
    if not result["folder"]:
        return result
    for sidecar in result["sidecars"]:
        Path(sidecar).unlink(missing_ok=True)
    folder.rmdir()
    return result


def preview_movie_delete(source_root: Path, paths: list[Any]) -> dict[str, Any]:
    source = source_root.resolve()
    deleted: list[str] = []
    cleaned_sidecars: list[str] = []
    removed_folders: list[str] = []
    skipped: list[dict[str, str]] = []

    for raw_path in paths:
        resolved = Path(str(raw_path)).expanduser().resolve()
        try:
            resolved.relative_to(source)
        except ValueError:
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


def delete_movie_files(source_root: Path, paths: list[Any]) -> dict[str, Any]:
    source = source_root.resolve()
    deleted: list[str] = []
    cleaned_sidecars: list[str] = []
    removed_folders: list[str] = []
    skipped: list[dict[str, str]] = []

    for raw_path in paths:
        resolved = Path(str(raw_path)).expanduser().resolve()
        try:
            resolved.relative_to(source)
        except ValueError:
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
        resolved.unlink()
        deleted.append(str(resolved))
        cleanup = cleanup_safe_movie_sidecars(source, resolved.parent)
        cleaned_sidecars.extend(cleanup["sidecars"])
        if cleanup["folder"]:
            removed_folders.append(cleanup["folder"])

    return {
        "deleted": deleted,
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
    with ctx.handler.activity_tracker.track(source, "Movie delete"):
        result = delete_movie_files(source, paths)
    if result["deleted"]:
        MOVIE_PROFILE_CACHE.invalidate(source)
    ctx.respond_json(result)


def handle_movies_audio_packaging_fix(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    drop_foreign_audio = bool(payload.get("drop_foreign_audio"))
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
    result["updated_items"] = build_updated_profile_items(source, result["fixed"])
    ctx.respond_json(result)


def handle_movies_subtitle_readiness_fix(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    with ctx.handler.activity_tracker.track(source, "Movie subtitle fix: repair defaults", kind="remux") as activity_id:
        result = fix_movie_subtitle_defaults(
            source,
            [str(path) for path in paths],
            probe_media=tracked_probe(source, "ffprobe subtitle readiness fix", cache=PROBE_CACHE),
            progress_callback=lambda update: ctx.handler.activity_tracker.update(activity_id, **update),
        )
    result["updated_items"] = build_updated_profile_items(source, result["fixed"])
    if result["updated_items"]:
        MOVIE_PROFILE_CACHE.invalidate(source)
    ctx.respond_json(result)
