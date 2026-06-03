from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from normal.models import utc_now_iso
from normal.movie_canonical_lists import build_canonical_lists_report
from normal.movie_inspect import inspect_movie_file
from normal.movie_omdb import lookup_omdb_ratings
from normal.movie_profile import (
    build_delete_mode_definition,
    build_histogram_payload_from_items,
    build_movie_profile_definitions,
    build_policy_definitions,
    build_replacement_candidate_definition,
    deep_merge_dicts,
    library_policy_revision,
    load_movie_standards,
    load_operator_preferences,
    movie_standards_revision,
    MovieStandardsConflictError,
    normalize_weak_encode_floor,
    operator_preferences_revision,
    replacement_candidate_quality_floor,
    reclassify_report_with_standards,
    scan_movie_profiles,
    update_policy_definition,
    update_movie_profile_definition,
)
from normal.movie_scan import MovieScanProgress, scan_movie_library
from .activity import tracked_probe
from .http import RequestContext
from .scan_guard import guarded_heavy_scan
from .serializers import build_profile_response
from .state import MOVIE_PROFILE_CACHE, PROBE_CACHE, RequestConflictError


def handle_movies_profile(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    standards = load_movie_standards()
    effective_standards = profile_request_standards(payload, standards)
    floor_overridden = replacement_candidate_quality_floor(effective_standards) != replacement_candidate_quality_floor(standards)
    cached = MOVIE_PROFILE_CACHE.get(source)
    if cached is not None:
        response_report = reclassify_report_with_standards(cached, effective_standards) if floor_overridden else cached
        ctx.respond_json(build_profile_response(source, response_report, effective_standards))
        return
    with guarded_heavy_scan(source, "Movie profile scan"):
        with ctx.handler.activity_tracker.track(source, "Movie profile scan") as activity_id:
            def update_profile_activity(progress: MovieScanProgress) -> None:
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

            report = scan_movie_profiles(
                source,
                probe_media=tracked_probe(source, "ffprobe movie metadata", cache=PROBE_CACHE),
                progress_callback=update_profile_activity,
                should_cancel=ctx.client_disconnected,
            )
        MOVIE_PROFILE_CACHE.put(source, report)
        response_report = reclassify_report_with_standards(report, effective_standards) if floor_overridden else report
        response = build_profile_response(source, response_report, effective_standards)
    ctx.respond_json(response)


def profile_request_standards(payload: dict[str, Any], standards: dict[str, Any]) -> dict[str, Any]:
    if "weak_floor" not in payload:
        return standards
    weak_floor = normalize_weak_encode_floor(payload.get("weak_floor"), standards)
    return deep_merge_dicts(
        standards,
        {"replacement_candidate_rules": {"quality_profile_floor": weak_floor}},
    )


def handle_movies_dashboard_histogram(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    movies = payload.get("movies")
    if not isinstance(movies, list):
        raise ValueError("movies must be a list")
    ctx.respond_json(
        build_histogram_payload_from_items(
            str(source),
            utc_now_iso(),
            [item for item in movies if isinstance(item, dict)],
        )
    )


def handle_movies_standards_update(ctx: RequestContext, payload: dict[str, Any]) -> None:
    label = str(payload.get("label") or "").strip()
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    revision = str(payload.get("revision") or "").strip() or None
    try:
        standards, preferences = update_policy_definition(
            label,
            values,
            expected_policy_revision=revision,
            expected_preferences_revision=str(payload.get("operator_preferences_revision") or "").strip() or None,
        )
    except MovieStandardsConflictError as exc:
        raise RequestConflictError(str(exc)) from exc
    ctx.respond_json(
        {
            "policy": standards,
            "policy_revision": library_policy_revision(standards),
            "operator_preferences": preferences,
            "operator_preferences_revision": operator_preferences_revision(preferences),
            "policy_definitions": build_policy_definitions(standards, preferences),
            "movie_standards": standards,
            "movie_standards_revision": movie_standards_revision(standards),
            "quality_profile_definitions": build_movie_profile_definitions(standards),
            "replacement_candidate_definition": build_replacement_candidate_definition(standards),
            "delete_mode_definition": build_delete_mode_definition(preferences),
        }
    )


def handle_policy_read(ctx: RequestContext, payload: dict[str, Any]) -> None:
    standards = load_movie_standards()
    preferences = load_operator_preferences()
    ctx.respond_json(
        {
            "policy": standards,
            "policy_revision": library_policy_revision(standards),
            "operator_preferences": preferences,
            "operator_preferences_revision": operator_preferences_revision(preferences),
            "policy_definitions": build_policy_definitions(standards, preferences),
            "quality_profile_definitions": build_movie_profile_definitions(standards),
            "replacement_candidate_definition": build_replacement_candidate_definition(standards),
            "delete_mode_definition": build_delete_mode_definition(preferences),
        }
    )


def handle_policy_update(ctx: RequestContext, payload: dict[str, Any]) -> None:
    label = str(payload.get("label") or "").strip()
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    policy_revision = str(payload.get("policy_revision") or "").strip() or None
    preferences_revision = str(payload.get("operator_preferences_revision") or "").strip() or None
    try:
        standards, preferences = update_policy_definition(
            label,
            values,
            expected_policy_revision=policy_revision,
            expected_preferences_revision=preferences_revision,
        )
    except MovieStandardsConflictError as exc:
        raise RequestConflictError(str(exc)) from exc
    ctx.respond_json(
        {
            "policy": standards,
            "policy_revision": library_policy_revision(standards),
            "operator_preferences": preferences,
            "operator_preferences_revision": operator_preferences_revision(preferences),
            "policy_definitions": build_policy_definitions(standards, preferences),
            "quality_profile_definitions": build_movie_profile_definitions(standards),
            "replacement_candidate_definition": build_replacement_candidate_definition(standards),
            "delete_mode_definition": build_delete_mode_definition(preferences),
        }
    )


def handle_movies_canonical_lists(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    with guarded_heavy_scan(source, "Movie canonical lists"):
        with ctx.handler.activity_tracker.track(source, "Movie canonical lists"):
            report = build_canonical_lists_report(
                source,
                tmdb_key=ctx.tmdb_key,
                should_cancel=ctx.client_disconnected,
            )
    ctx.respond_json(report.to_dict())


def handle_movies_omdb_ratings(ctx: RequestContext, payload: dict[str, Any]) -> None:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    ctx.respond_json(lookup_omdb_ratings([item for item in items if isinstance(item, dict)], ctx.omdb_key))


def handle_movies_register(ctx: RequestContext, payload: dict[str, Any]) -> None:
    from normal.output import write_movie_register_xlsx

    source = ctx.resolve_source(payload.get("source"))
    with guarded_heavy_scan(source, "Movie catalogue export"):
        with ctx.handler.activity_tracker.track(source, "Movie catalogue export"):
            scan_report = scan_movie_library(source, probe_media=tracked_probe(source, "ffprobe movie catalogue", cache=PROBE_CACHE))
            with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as jf:
                json.dump(scan_report.to_dict(), jf)
                report_path = Path(jf.name)
            try:
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as xf:
                    xlsx_path = Path(xf.name)
                write_movie_register_xlsx(report_path, xlsx_path)
                data = xlsx_path.read_bytes()
            finally:
                report_path.unlink(missing_ok=True)
                xlsx_path.unlink(missing_ok=True)
    ctx.respond_bytes(
        data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content_disposition='attachment; filename="movie-catalogue.xlsx"',
    )


def handle_movies_inspect(ctx: RequestContext, payload: dict[str, Any]) -> None:
    raw_path = payload.get("path")
    if not raw_path:
        raise ValueError("path is required")
    resolved = Path(str(raw_path)).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"path does not exist: {resolved}")
    source = resolved.parent
    with ctx.handler.activity_tracker.track(source, "Movie inspect"):
        ctx.respond_json(
            inspect_movie_file(
                resolved,
                probe_media=tracked_probe(source, "ffprobe movie inspect", cache=PROBE_CACHE),
            ).to_dict()
        )
