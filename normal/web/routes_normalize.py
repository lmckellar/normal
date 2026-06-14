from __future__ import annotations

from pathlib import Path
from typing import Any

from normal.audit import AuditEffect, AuditEvent, AuditSubject, make_event_id
from normal.models import utc_now_iso
from normal.movie_apply import apply_changes_in_place
from normal.movie_enriched import parsed_movies_from_enriched, scan_enriched_library
from normal.movie_plan import build_movie_plan
from normal.source_policy import Operation, validate_source_for_operation
from normal.tv_plan import build_tv_plan, parsed_tv_from_enriched

from .activity import tracked_probe
from .http import RequestContext
from .routes_audit import build_reversal_entries_for_normalize_effects, record_scan_event
from .scan_guard import guarded_heavy_scan, guarded_mutation
from .serializers import build_movie_normalize_results, build_tv_normalize_results
from .state import AUDIT_STORE, MOVIE_CANONICAL_CACHE, MOVIE_ENRICHED_CACHE, MOVIE_PROFILE_CACHE, PROBE_CACHE


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


def _build_tv_normalize_payload(source, tv_files, plan, parsed_tv):
    response = plan.to_dict()
    response["tv_results"] = build_tv_normalize_results(
        source,
        tv_files,
        plan.proposed_changes,
        plan.warnings,
        parsed_tv=parsed_tv,
    )
    response["tv_files"] = [str(path) for path in tv_files]
    return response


def handle_movies_normalize(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = validate_source_for_operation(
        ctx.resolve_source(payload.get("source")),
        operation=Operation.PLAN,
        approved_roots=ctx.approved_roots,
    )
    with guarded_heavy_scan(source, "Movie normalize plan"):
        with ctx.handler.activity_tracker.track(source, "Movie normalize plan"):
            enriched = MOVIE_ENRICHED_CACHE.get(source)
            if enriched is None:
                enriched = scan_enriched_library(
                    source,
                    probe_media=tracked_probe(source, "ffprobe movie library", cache=PROBE_CACHE),
                )
                MOVIE_ENRICHED_CACHE.put(source, enriched)
            movie_files = [Path(item.path) for item in enriched.files]
            parsed_movies = parsed_movies_from_enriched(enriched)
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
    validate_source_for_operation(source, operation=Operation.APPLY, approved_roots=ctx.approved_roots)
    raw_ids = payload.get("change_ids", [])
    if not isinstance(raw_ids, list):
        raise ValueError("change_ids must be a list")
    requested_ids = {str(item_id) for item_id in raw_ids}
    with guarded_mutation(source, "Movie apply"), ctx.handler.activity_tracker.track(source, "Movie apply"):
        enriched = scan_enriched_library(
            source,
            probe_media=tracked_probe(source, "ffprobe movie library", cache=PROBE_CACHE),
        )
        plan_movie_files = [Path(item.path) for item in enriched.files]
        plan_parsed_movies = parsed_movies_from_enriched(enriched)
        authoritative_plan = build_movie_plan(source, movie_files=plan_movie_files, parsed_movies=plan_parsed_movies)
        changes = [change for change in authoritative_plan.proposed_changes if change.item_id in requested_ids]
        validate_source_for_operation(
            source,
            operation=Operation.APPLY,
            approved_roots=ctx.approved_roots,
            candidate_paths=[change.path for change in changes if change.path],
        )
        report = apply_changes_in_place(source, changes, approved_roots=ctx.approved_roots)
        MOVIE_ENRICHED_CACHE.invalidate(source)
        MOVIE_PROFILE_CACHE.invalidate(source)
        MOVIE_CANONICAL_CACHE.invalidate(source)
        _record_normalize_apply_event(source, changes, report.to_dict())
        enriched = scan_enriched_library(
            source,
            probe_media=tracked_probe(source, "ffprobe movie library", cache=PROBE_CACHE),
        )
        MOVIE_ENRICHED_CACHE.put(source, enriched)
        movie_files = [Path(item.path) for item in enriched.files]
        parsed_movies = parsed_movies_from_enriched(enriched)
        plan = build_movie_plan(source, movie_files=movie_files, parsed_movies=parsed_movies)
    response = report.to_dict()
    remaining_payload = _build_normalize_payload(source, movie_files, plan, parsed_movies)
    remaining_changes = remaining_payload["proposed_changes"]
    response["remaining_changes"] = remaining_changes
    response["remaining_safe_count"] = len([change for change in remaining_changes if change["confidence"] == "safe"])
    response["remaining_review_count"] = len([change for change in remaining_changes if change["confidence"] == "review"])
    response["remaining_plan"] = remaining_payload if remaining_changes else None
    ctx.respond_json(response)


def handle_tv_normalize(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = validate_source_for_operation(
        ctx.resolve_source(payload.get("source")),
        operation=Operation.PLAN,
        approved_roots=ctx.approved_roots,
    )
    with guarded_heavy_scan(source, "TV normalize plan"):
        with ctx.handler.activity_tracker.track(source, "TV normalize plan") as activity_id:
            def update_tv_activity(progress) -> None:
                has_total = progress.total > progress.processed
                ctx.handler.activity_tracker.update(
                    activity_id,
                    current_path=progress.current_path,
                    status_text=f"{progress.processed} files processed",
                    processed=progress.processed,
                    total=progress.total if has_total else None,
                    progress_fraction=(progress.processed / progress.total) if has_total else None,
                    eta_seconds=progress.eta_seconds if has_total else None,
                )

            enriched = MOVIE_ENRICHED_CACHE.get(source, lane="tv")
            if enriched is None:
                enriched = scan_enriched_library(
                    source,
                    lane="tv",
                    probe_media=tracked_probe(source, "ffprobe TV library", cache=PROBE_CACHE),
                    progress_callback=update_tv_activity,
                    should_cancel=ctx.client_disconnected,
                )
                MOVIE_ENRICHED_CACHE.put(source, enriched, lane="tv")
            tv_files = [Path(item.path) for item in enriched.files]
            parsed_tv = parsed_tv_from_enriched(enriched)
            plan = build_tv_plan(source, tv_files=tv_files, parsed_tv=parsed_tv)
            response = _build_tv_normalize_payload(source, tv_files, plan, parsed_tv)
    record_scan_event(
        source,
        workflow="tv_normalize",
        label="TV normalize plan",
        metadata={
            "lane": "tv",
            "tv_file_count": len(response["tv_files"]),
            "proposed_change_count": len(response["proposed_changes"]),
            "warning_count": len(response["warnings"]),
        },
    )
    ctx.respond_json(response)


def handle_tv_apply(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    validate_source_for_operation(source, operation=Operation.APPLY, approved_roots=ctx.approved_roots)
    raw_ids = payload.get("change_ids", [])
    if not isinstance(raw_ids, list):
        raise ValueError("change_ids must be a list")
    requested_ids = {str(item_id) for item_id in raw_ids}
    with guarded_mutation(source, "TV apply"), ctx.handler.activity_tracker.track(source, "TV apply"):
        enriched = scan_enriched_library(
            source,
            lane="tv",
            probe_media=tracked_probe(source, "ffprobe TV library", cache=PROBE_CACHE),
        )
        plan_tv_files = [Path(item.path) for item in enriched.files]
        plan_parsed_tv = parsed_tv_from_enriched(enriched)
        authoritative_plan = build_tv_plan(source, tv_files=plan_tv_files, parsed_tv=plan_parsed_tv)
        changes = [change for change in authoritative_plan.proposed_changes if change.item_id in requested_ids]
        validate_source_for_operation(
            source,
            operation=Operation.APPLY,
            approved_roots=ctx.approved_roots,
            candidate_paths=[change.path for change in changes if change.path],
        )
        report = apply_changes_in_place(source, changes, approved_roots=ctx.approved_roots)
        if report.applied:
            MOVIE_ENRICHED_CACHE.invalidate(source, lane="tv")
        _record_normalize_apply_event(source, changes, report.to_dict(), lane="tv")
        enriched = scan_enriched_library(
            source,
            lane="tv",
            probe_media=tracked_probe(source, "ffprobe TV library", cache=PROBE_CACHE),
        )
        MOVIE_ENRICHED_CACHE.put(source, enriched, lane="tv")
        tv_files = [Path(item.path) for item in enriched.files]
        parsed_tv = parsed_tv_from_enriched(enriched)
        plan = build_tv_plan(source, tv_files=tv_files, parsed_tv=parsed_tv)
    response = report.to_dict()
    remaining_payload = _build_tv_normalize_payload(source, tv_files, plan, parsed_tv)
    remaining_changes = remaining_payload["proposed_changes"]
    response["remaining_changes"] = remaining_changes
    response["remaining_safe_count"] = len([change for change in remaining_changes if change["confidence"] == "safe"])
    response["remaining_review_count"] = len([change for change in remaining_changes if change["confidence"] == "review"])
    response["remaining_plan"] = remaining_payload if remaining_changes else None
    ctx.respond_json(response)


def _record_normalize_apply_event(source, changes, report: dict[str, Any], *, lane: str = "movie") -> None:
    workflow = "normalize" if lane == "movie" else "tv_normalize"
    subject_kind = "movie_change" if lane == "movie" else "tv_change"
    label = "Normalize" if lane == "movie" else "TV normalize"
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
                    kind=subject_kind,
                    path=previous_path,
                    item_id=item_id,
                    details={
                        "change_type": change.change_type,
                        "current_value": change.current_value,
                        "proposed_value": change.proposed_value,
                    },
                )
    event = AuditEvent(
        event_id=make_event_id(str(source.resolve()), workflow, "apply", recorded_at, salt=str(len(changes))),
        recorded_at=recorded_at,
        source_root=str(source.resolve()),
        workflow=workflow,
        action="apply",
        summary=f"Applied {label} changes to {len(report.get('applied', []))} item{'s' if len(report.get('applied', [])) != 1 else ''}.",
        subjects=list(subjects_by_id.values()),
        effects=effects,
        reversal=build_reversal_entries_for_normalize_effects(effects),
        metadata={
            **({"lane": lane} if lane != "movie" else {}),
            "applied_count": len(report.get("applied", [])),
            "skipped_count": len(report.get("skipped", [])),
            "failed_count": len(report.get("failed", [])),
        },
    )
    AUDIT_STORE.append(event)
