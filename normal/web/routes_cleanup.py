from __future__ import annotations

from pathlib import Path
from typing import Any

from normal.movie_audio_fix import fix_english_audio_defaults
from normal.movie_junk import (
    detect_movie_junk_document_reasons,
    detect_movie_junk_reasons,
    scan_movie_cleanup,
)
from normal.movie_replacement_queue import (
    add_profile_items_to_queue,
    clear_pending_queue_items,
    delete_replacement_queue_media,
    dismiss_replacement_queue_items,
    preview_replacement_queue_delete,
    queue_for_source,
)
from normal.movie_subtitle_fix import fix_movie_subtitle_defaults
from normal.movie_subtitle_history import (
    dismiss_items as dismiss_subtitle_history_items,
    history_for_source as subtitle_history_for_source,
    upsert_items as upsert_subtitle_history_items,
)

from .activity import tracked_probe
from .http import RequestContext
from .scan_guard import guarded_heavy_scan
from .serializers import build_updated_profile_items
from .state import MOVIE_PROFILE_CACHE, PROBE_CACHE


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
            report = scan_movie_cleanup(source)
    ctx.respond_json(report.to_dict())


def handle_movies_junk_delete(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    with ctx.handler.activity_tracker.track(source, "Movie junk delete"):
        result = delete_movie_junk_files(source, paths)
    ctx.respond_json(result)


def handle_movies_replacement_queue_list(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    issue_family = payload.get("issue_family")
    ctx.respond_json(queue_for_source(source, issue_family=issue_family))


def handle_movies_replacement_queue_add(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    mode = str(payload.get("mode") or "file")
    issue_family = str(payload.get("issue_family") or "weak_encode")
    ctx.respond_json(add_profile_items_to_queue(source, items, mode=mode, issue_family=issue_family))


def handle_movies_replacement_queue_delete(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    item_ids = payload.get("item_ids")
    if not isinstance(item_ids, list):
        raise ValueError("item_ids must be a list")
    ctx.respond_json(delete_replacement_queue_media(source, item_ids))


def handle_movies_replacement_queue_delete_preview(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    ctx.respond_json(preview_replacement_queue_delete(source, paths))


def handle_movies_replacement_queue_dismiss(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    item_ids = payload.get("item_ids")
    if not isinstance(item_ids, list):
        raise ValueError("item_ids must be a list")
    ctx.respond_json(dismiss_replacement_queue_items(source, item_ids))


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
    fixed_paths = [str(item.get("path") or "") for item in result["fixed"]]
    if fixed_paths:
        MOVIE_PROFILE_CACHE.invalidate(source)
    result["replacement_queue"] = (
        clear_pending_queue_items(source, fixed_paths, issue_family="audio_packaging")
        if fixed_paths
        else queue_for_source(source, issue_family="audio_packaging")
    )
    result["updated_items"] = build_updated_profile_items(source, result["fixed"])
    ctx.respond_json(result)


def handle_movies_subtitle_readiness_fix(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")
    issue_codes: dict[str, str] = payload.get("issue_codes") or {}
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
    fixed_raw = [{"path": str(item["path"]), "issue_code": issue_codes.get(str(item["path"]), "")} for item in result["fixed"]]
    if fixed_raw:
        result["subtitle_history"] = upsert_subtitle_history_items(source, fixed_raw, entry_type="fixed")
    ctx.respond_json(result)


def handle_movies_subtitle_readiness_history_list(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    ctx.respond_json(subtitle_history_for_source(source))


def handle_movies_subtitle_readiness_history_sync(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    ctx.respond_json(upsert_subtitle_history_items(source, items, entry_type="review_only"))


def handle_movies_subtitle_readiness_history_dismiss(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    item_ids = payload.get("item_ids")
    if not isinstance(item_ids, list):
        raise ValueError("item_ids must be a list")
    ctx.respond_json(dismiss_subtitle_history_items(source, item_ids))
