from __future__ import annotations

from pathlib import Path
from typing import Any

from normal.execution_queue import (
    QueueDocument,
    drain_queue,
    planned_actions_from_changes,
    proposed_change_from_action,
)
from normal.movie_enriched import parsed_movies_from_enriched, scan_enriched_library
from normal.movie_plan import build_movie_plan
from normal.source_policy import Operation, validate_source_for_operation
from normal.tv_plan import build_tv_plan, parsed_tv_from_enriched

from .activity import tracked_probe
from .http import RequestContext
from .routes_audit import record_scan_event
from .routes_normalize import _record_normalize_apply_event
from .scan_guard import guarded_heavy_scan, guarded_mutation
from .state import (
    EXECUTION_QUEUE_STORE,
    MOVIE_CANONICAL_CACHE,
    MOVIE_ENRICHED_CACHE,
    MOVIE_PROFILE_CACHE,
    PROBE_CACHE,
)


def _resolve_lane(payload: dict[str, Any]) -> str:
    lane = str(payload.get("lane") or "movie")
    if lane not in {"movie", "tv"}:
        raise ValueError(f"Unsupported lane: {lane}")
    return lane


def _authoritative_changes(source: Path, lane: str):
    probe = tracked_probe(source, f"ffprobe {lane} library", cache=PROBE_CACHE)
    enriched = scan_enriched_library(source, lane=lane, probe_media=probe)
    files = [Path(item.path) for item in enriched.files]
    if lane == "movie":
        plan = build_movie_plan(source, movie_files=files, parsed_movies=parsed_movies_from_enriched(enriched))
    else:
        plan = build_tv_plan(source, tv_files=files, parsed_tv=parsed_tv_from_enriched(enriched))
    return plan.proposed_changes


def _snapshot(document: QueueDocument | None, source: Path, lane: str) -> dict[str, Any]:
    if document is None:
        return {
            "source_root": str(source.resolve()),
            "lane": lane,
            "exists": False,
            "counts": {"pending": 0, "done": 0, "skipped": 0, "failed": 0},
            "actions": [],
        }
    return {
        "source_root": document.source_root,
        "lane": document.lane,
        "exists": True,
        "queue_id": document.queue_id,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "counts": document.counts(),
        "actions": [action.to_dict() for action in document.actions],
    }


def handle_queue_stage(ctx: RequestContext, payload: dict[str, Any]) -> None:
    lane = _resolve_lane(payload)
    source = validate_source_for_operation(
        ctx.resolve_source(payload.get("source")),
        operation=Operation.PLAN,
        approved_roots=ctx.approved_roots,
    )
    raw_ids = payload.get("change_ids", [])
    if not isinstance(raw_ids, list):
        raise ValueError("change_ids must be a list")
    requested_ids = {str(item_id) for item_id in raw_ids}
    label = f"{'Movie' if lane == 'movie' else 'TV'} queue stage"
    with guarded_heavy_scan(source, label):
        with ctx.handler.activity_tracker.track(source, label):
            changes = [
                change
                for change in _authoritative_changes(source, lane)
                if change.item_id in requested_ids
            ]
            actions = planned_actions_from_changes(changes, lane=lane)
            document = EXECUTION_QUEUE_STORE.stage(source, lane, actions)
    record_scan_event(
        source,
        workflow="normalize" if lane == "movie" else "tv_normalize",
        label=label,
        metadata={
            **({"lane": lane} if lane != "movie" else {}),
            "staged_action_count": len(actions),
            "requested_change_count": len(requested_ids),
        },
    )
    ctx.respond_json(_snapshot(document, source, lane))


def handle_queue_drain(ctx: RequestContext, payload: dict[str, Any]) -> None:
    lane = _resolve_lane(payload)
    source = ctx.resolve_source(payload.get("source"))
    validate_source_for_operation(source, operation=Operation.APPLY, approved_roots=ctx.approved_roots)
    document = EXECUTION_QUEUE_STORE.load(source, lane)
    if document is None:
        ctx.respond_json({**_snapshot(None, source, lane), **{"applied": [], "skipped": [], "failed": [], "processed": 0, "stopped": False}})
        return

    pending_paths = [
        action.source_path
        for action in document.pending()
        if action.confidence == "safe" and action.source_path
    ]
    validate_source_for_operation(
        source,
        operation=Operation.APPLY,
        approved_roots=ctx.approved_roots,
        candidate_paths=pending_paths,
    )

    label = f"{'Movie' if lane == 'movie' else 'TV'} queue drain"
    with guarded_mutation(source, label), ctx.handler.activity_tracker.track(source, label) as activity_id:
        total = len(document.pending())
        progress = {"done": 0}

        def on_item(action) -> None:
            ctx.handler.activity_tracker.update(
                activity_id,
                current_path=action.source_path,
                status_text=f"{progress['done']} of {total} drained",
                processed=progress["done"],
                total=total,
                progress_fraction=(progress["done"] / total) if total else None,
            )
            progress["done"] += 1

        report = drain_queue(
            document,
            EXECUTION_QUEUE_STORE,
            source_root=source,
            approved_roots=ctx.approved_roots,
            should_cancel=ctx.client_disconnected,
            on_item=on_item,
        )
        if report.applied:
            MOVIE_ENRICHED_CACHE.invalidate(source, lane=lane)
            if lane == "movie":
                MOVIE_PROFILE_CACHE.invalidate(source)
                MOVIE_CANONICAL_CACHE.invalidate(source)
        if report.processed:
            changes = [proposed_change_from_action(action) for action in document.actions]
            _record_normalize_apply_event(source, changes, report.to_dict(), lane=lane)

    response = report.to_dict()
    response.update(_snapshot(document, source, lane))
    ctx.respond_json(response)


def handle_queue_status(ctx: RequestContext, payload: dict[str, Any]) -> None:
    lane = _resolve_lane(payload)
    source = validate_source_for_operation(
        ctx.resolve_source(payload.get("source")),
        operation=Operation.PLAN,
        approved_roots=ctx.approved_roots,
    )
    document = EXECUTION_QUEUE_STORE.load(source, lane)
    ctx.respond_json(_snapshot(document, source, lane))
