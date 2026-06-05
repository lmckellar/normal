from __future__ import annotations

from typing import Any

from normal.audit import AuditEffect, AuditEvent, AuditSubject, make_event_id
from normal.models import ProposedChange
from normal.models import utc_now_iso
from normal.movie_apply import apply_changes_in_place
from normal.movie_plan import build_movie_plan, parse_movie_name_with_sidecar_fallback
from normal.movie_scan import discover_video_files

from .http import RequestContext
from .routes_audit import build_reversal_entries_for_normalize_effects, record_scan_event
from .scan_guard import guarded_heavy_scan
from .serializers import build_movie_normalize_results
from .state import AUDIT_STORE, MOVIE_CANONICAL_CACHE, MOVIE_PROFILE_CACHE


def _build_normalize_payload(source, movie_files, plan, parsed_movies):
    response = plan.to_dict()
    response["movie_results"] = build_movie_normalize_results(
        source,
        movie_files,
        plan.proposed_changes,
        plan.warnings,
        parsed_movies=parsed_movies,
    )
    response["movie_files"] = [str(path) for path in movie_files]
    return response


def handle_movies_normalize(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    with guarded_heavy_scan(source, "Movie normalize plan"):
        with ctx.handler.activity_tracker.track(source, "Movie normalize plan"):
            movie_files = discover_video_files(source)
            parsed_movies = {movie_path: parse_movie_name_with_sidecar_fallback(movie_path) for movie_path in movie_files}
            plan = build_movie_plan(source, movie_files=movie_files, parsed_movies=parsed_movies)
            response = _build_normalize_payload(source, movie_files, plan, parsed_movies)
    record_scan_event(
        source,
        workflow="normalize",
        label="Movie normalize plan",
        metadata={
            "movie_file_count": len(response["movie_files"]),
            "proposed_change_count": len(response["proposed_changes"]),
            "warning_count": len(response["warnings"]),
        },
    )
    ctx.respond_json(response)


def handle_movies_apply(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    raw_changes = payload.get("changes", [])
    if not isinstance(raw_changes, list):
        raise ValueError("changes must be a list")
    changes = [ProposedChange(**c) for c in raw_changes]
    with ctx.handler.activity_tracker.track(source, "Movie apply"):
        report = apply_changes_in_place(source, changes)
        MOVIE_PROFILE_CACHE.invalidate(source)
        MOVIE_CANONICAL_CACHE.invalidate(source)
        _record_normalize_apply_event(source, changes, report.to_dict())
        movie_files = discover_video_files(source)
        parsed_movies = {movie_path: parse_movie_name_with_sidecar_fallback(movie_path) for movie_path in movie_files}
        plan = build_movie_plan(source, movie_files=movie_files, parsed_movies=parsed_movies)
    response = report.to_dict()
    remaining_payload = _build_normalize_payload(source, movie_files, plan, parsed_movies)
    remaining_changes = remaining_payload["proposed_changes"]
    response["remaining_changes"] = remaining_changes
    response["remaining_safe_count"] = len([change for change in remaining_changes if change["confidence"] == "safe"])
    response["remaining_review_count"] = len([change for change in remaining_changes if change["confidence"] == "review"])
    response["remaining_plan"] = remaining_payload if remaining_changes else None
    ctx.respond_json(response)


def _record_normalize_apply_event(source, changes, report: dict[str, Any]) -> None:
    recorded_at = utc_now_iso()
    by_item_id = {change.item_id: change for change in changes}
    effects: list[AuditEffect] = []
    subjects_by_id: dict[str, AuditSubject] = {}
    for bucket in ("applied", "skipped", "failed"):
        for item in report.get(bucket, []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id") or "")
            change = by_item_id.get(item_id)
            if change is None:
                continue
            previous_path = str(change.path or "") or None
            current_path = str(item.get("path") or "") or previous_path
            effects.append(
                AuditEffect(
                    kind=change.change_type,
                    status=bucket,
                    path=current_path,
                    previous_path=previous_path,
                    message=str(item.get("message") or ""),
                    details={
                        "current_value": change.current_value,
                        "proposed_value": change.proposed_value,
                        "confidence": change.confidence,
                        "reason": change.reason,
                        "reason_codes": list(change.reason_codes),
                        "warning_codes": list(change.warning_codes),
                    },
                )
            )
            if item_id not in subjects_by_id:
                subjects_by_id[item_id] = AuditSubject(
                    kind="movie_change",
                    path=previous_path,
                    item_id=item_id,
                    details={
                        "change_type": change.change_type,
                        "current_value": change.current_value,
                        "proposed_value": change.proposed_value,
                    },
                )
    event = AuditEvent(
        event_id=make_event_id(str(source.resolve()), "normalize", "apply", recorded_at, salt=str(len(changes))),
        recorded_at=recorded_at,
        source_root=str(source.resolve()),
        workflow="normalize",
        action="apply",
        summary=f"Applied Normalize changes to {len(report.get('applied', []))} item{'s' if len(report.get('applied', [])) != 1 else ''}.",
        subjects=list(subjects_by_id.values()),
        effects=effects,
        reversal=build_reversal_entries_for_normalize_effects(effects),
        metadata={
            "applied_count": len(report.get("applied", [])),
            "skipped_count": len(report.get("skipped", [])),
            "failed_count": len(report.get("failed", [])),
        },
    )
    AUDIT_STORE.append(event)
