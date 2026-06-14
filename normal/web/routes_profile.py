from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from normal.models import utc_now_iso
from normal.library_improvement import build_library_improvement_payload
from normal.movie_canonical_lists import (
    build_canonical_lists_report,
    build_canonical_summary,
    canonical_status_payload,
    ensure_canonical_provider_ready,
)
from normal.movie_immersive_confirmations import record_available_observations
from normal.movie_inspect import inspect_movie_file
from normal.movie_plan import parse_movie_name
from normal.movie_omdb import lookup_omdb_ratings
from normal.movie_profile import (
    build_default_source_definition,
    build_delete_mode_definition,
    build_histogram_payload_from_items,
    build_library_defaults_definition,
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
from normal.source_policy import Operation, validate_source_for_operation
from .activity import tracked_probe
from .http import RequestContext
from .routes_audit import (
    reconcile_replacement_followups,
    record_export_event,
    record_trait_observation_event,
    record_immersive_telemetry_event,
    record_policy_update_event,
    record_scan_event,
)
from .scan_guard import guarded_heavy_scan
from .serializers import build_profile_response
from .state import AUDIT_STORE, MOVIE_CANONICAL_CACHE, MOVIE_PROFILE_CACHE, PROBE_CACHE, RequestConflictError


def invalidate_policy_caches(source: Path | None, label: str) -> None:
    if source is None:
        return
    if label in {"default_source", "delete_mode"}:
        return
    MOVIE_PROFILE_CACHE.invalidate(source)
    MOVIE_CANONICAL_CACHE.invalidate(source)


def handle_movies_profile(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = validate_source_for_operation(
        ctx.resolve_source(payload.get("source")),
        operation=Operation.HEAVY_SCAN,
        approved_roots=ctx.approved_roots,
    )
    standards = load_movie_standards()
    effective_standards = profile_request_standards(payload, standards)
    floor_overridden = replacement_candidate_quality_floor(effective_standards) != replacement_candidate_quality_floor(standards)
    resolve_language = ctx.language_resolver()
    cached = MOVIE_PROFILE_CACHE.get(source)
    if cached is not None:
        response_report = reclassify_report_with_standards(cached, effective_standards, resolve_language=resolve_language) if floor_overridden else cached
        reconcile_replacement_followups(source, response_report)
        response = build_profile_response(source, response_report, effective_standards, resolve_language=resolve_language)
        response["canonical_summary"] = build_canonical_summary(
            source,
            standards=effective_standards,
            tmdb_key=ctx.tmdb_key,
            movie_paths=[Path(item.path) for item in response_report.movies],
            audit_store=AUDIT_STORE,
        )
        response["canonical_status"] = response["canonical_summary"].get("canonical_status")
        improvement = build_library_improvement_payload(
            source,
            response_report,
            effective_standards,
            audit_store=AUDIT_STORE,
            tmdb_key=ctx.tmdb_key,
            pending_scan_count=1,
        )
        response["library_improvement_metrics"] = improvement
        record_scan_event(
            source,
            workflow="profile",
            label="Movie profile scan",
            status="cached",
            summary="Reused cached Movie profile scan.",
            metadata={
                "movie_count": len(cached.movies),
                "cache_hit": True,
                "canonical_top_500_above_floor_count": improvement["canonical_top_500_above_floor"]["count"],
            },
        )
        ctx.respond_json(response)
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
                resolve_language=resolve_language,
            )
        PROBE_CACHE.flush()
        MOVIE_PROFILE_CACHE.put(source, report)
        record_trait_observation_event(source, added=report.trait_observations)
        response_report = reclassify_report_with_standards(report, effective_standards, resolve_language=resolve_language) if floor_overridden else report
        reconcile_replacement_followups(source, response_report)
        response = build_profile_response(source, response_report, effective_standards, resolve_language=resolve_language)
        response["canonical_summary"] = build_canonical_summary(
            source,
            standards=effective_standards,
            tmdb_key=ctx.tmdb_key,
            movie_paths=[Path(item.path) for item in response_report.movies],
            audit_store=AUDIT_STORE,
        )
        response["canonical_status"] = response["canonical_summary"].get("canonical_status")
        improvement = build_library_improvement_payload(
            source,
            response_report,
            effective_standards,
            audit_store=AUDIT_STORE,
            tmdb_key=ctx.tmdb_key,
            pending_scan_count=1,
        )
        response["library_improvement_metrics"] = improvement
        record_scan_event(
            source,
            workflow="profile",
            label="Movie profile scan",
            metadata={
                "movie_count": len(report.movies),
                "cache_hit": False,
                "canonical_top_500_above_floor_count": improvement["canonical_top_500_above_floor"]["count"],
            },
        )
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
    source = ctx.resolve_source(payload.get("source"))
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
    invalidate_policy_caches(source, label)
    record_policy_update_event(
        source,
        label=label or "unnamed",
        request_kind="movies_standards_update",
        metadata={"updated_keys": sorted(values.keys())},
    )
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
            "library_defaults_definition": build_library_defaults_definition(standards),
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
            "default_source_definition": build_default_source_definition(preferences),
            "quality_profile_definitions": build_movie_profile_definitions(standards),
            "replacement_candidate_definition": build_replacement_candidate_definition(standards),
            "delete_mode_definition": build_delete_mode_definition(preferences),
            "library_defaults_definition": build_library_defaults_definition(standards),
            "movie_standards": standards,
            "movie_standards_revision": movie_standards_revision(standards),
        }
    )


def handle_policy_update(ctx: RequestContext, payload: dict[str, Any]) -> None:
    label = str(payload.get("label") or "").strip()
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    policy_revision = str(payload.get("policy_revision") or "").strip() or None
    preferences_revision = str(payload.get("operator_preferences_revision") or "").strip() or None
    source = ctx.resolve_source(payload.get("source")) if payload.get("source") else None
    if source is None and label not in {"default_source", "delete_mode"}:
        source = ctx.resolve_source(payload.get("source"))
    try:
        standards, preferences = update_policy_definition(
            label,
            values,
            expected_policy_revision=policy_revision,
            expected_preferences_revision=preferences_revision,
        )
    except MovieStandardsConflictError as exc:
        raise RequestConflictError(str(exc)) from exc
    invalidate_policy_caches(source, label)
    if source is not None:
        record_policy_update_event(
            source,
            label=label or "unnamed",
            request_kind="policy_update",
            metadata={"updated_keys": sorted(values.keys())},
        )
    ctx.respond_json(
        {
            "policy": standards,
            "policy_revision": library_policy_revision(standards),
            "operator_preferences": preferences,
            "operator_preferences_revision": operator_preferences_revision(preferences),
            "policy_definitions": build_policy_definitions(standards, preferences),
            "default_source_definition": build_default_source_definition(preferences),
            "quality_profile_definitions": build_movie_profile_definitions(standards),
            "replacement_candidate_definition": build_replacement_candidate_definition(standards),
            "delete_mode_definition": build_delete_mode_definition(preferences),
            "library_defaults_definition": build_library_defaults_definition(standards),
            "movie_standards": standards,
            "movie_standards_revision": movie_standards_revision(standards),
        }
    )


def handle_movies_canonical_lists(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = validate_source_for_operation(
        ctx.resolve_source(payload.get("source")),
        operation=Operation.HEAVY_SCAN,
        approved_roots=ctx.approved_roots,
    )
    standards = load_movie_standards()
    force_refresh = bool(payload.get("refresh"))
    if force_refresh:
        ensure_canonical_provider_ready(
            standards=standards,
            tmdb_key=ctx.tmdb_key,
            force_refresh=True,
            block=False,
            audit_store=AUDIT_STORE,
            audit_source_root=source,
        )
    cached = MOVIE_CANONICAL_CACHE.get(source)
    if cached is not None and not force_refresh and (cached.canonical_status or {}).get("ready", True):
        record_scan_event(
            source,
            workflow="canonical_lists",
            label="Movie canonical lists",
            status="cached",
            summary="Reused cached Movie canonical lists.",
            metadata={"cache_hit": True},
        )
        ctx.respond_json(cached.to_dict())
        return
    with guarded_heavy_scan(source, "Movie canonical lists"):
        with ctx.handler.activity_tracker.track(source, "Movie canonical lists"):
            report = build_canonical_lists_report(
                source,
                standards=standards,
                tmdb_key=ctx.tmdb_key,
                should_cancel=ctx.client_disconnected,
                movie_paths=[Path(item.path) for item in MOVIE_PROFILE_CACHE.get(source).movies] if MOVIE_PROFILE_CACHE.get(source) is not None else None,
                audit_store=AUDIT_STORE,
            )
    MOVIE_CANONICAL_CACHE.put(source, report)
    record_scan_event(
        source,
        workflow="canonical_lists",
        label="Movie canonical lists",
        metadata={"cache_hit": False},
    )
    ctx.respond_json(report.to_dict())


def handle_movies_canonical_status(ctx: RequestContext, payload: dict[str, Any]) -> None:
    del payload
    standards = load_movie_standards()
    status = canonical_status_payload(
        standards=standards,
        tmdb_key=ctx.tmdb_key,
    )
    ctx.respond_json(status)


def handle_movies_canonical_refresh(ctx: RequestContext, payload: dict[str, Any]) -> None:
    standards = load_movie_standards()
    source = ctx.resolve_source(payload.get("source")) if payload.get("source") else None
    status = ensure_canonical_provider_ready(
        standards=standards,
        tmdb_key=ctx.tmdb_key,
        force_refresh=True,
        block=False,
        audit_store=AUDIT_STORE,
        audit_source_root=source,
    )
    ctx.respond_json(status)


def handle_movies_omdb_ratings(ctx: RequestContext, payload: dict[str, Any]) -> None:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    ctx.respond_json(lookup_omdb_ratings([item for item in items if isinstance(item, dict)], ctx.omdb_key))


def handle_movies_register(ctx: RequestContext, payload: dict[str, Any]) -> None:
    from normal.output import write_movie_register_xlsx

    source = validate_source_for_operation(
        ctx.resolve_source(payload.get("source")),
        operation=Operation.HEAVY_SCAN,
        approved_roots=ctx.approved_roots,
    )
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
    record_export_event(
        source,
        workflow="catalogue",
        label="movie catalogue",
        metadata={"movie_count": len(scan_report.movies), "filename": "movie-catalogue.xlsx"},
    )
    ctx.respond_bytes(
        data,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        content_disposition='attachment; filename="movie-catalogue.xlsx"',
    )


def _harvest_local_immersive_votes(source: Path, report: Any) -> None:
    """Legacy compatibility hook; the active profile path uses generic traits."""
    preferences = load_operator_preferences()
    if not preferences.get("immersive_local_probe_telemetry", True):
        return
    observations: list[tuple[str, int]] = []
    for item in report.movies:
        if not getattr(item.facts, "audio_immersive_extension", None):
            continue
        identity = parse_movie_name(Path(item.path))
        if identity.title and identity.year:
            observations.append((identity.title, identity.year))
    added = record_available_observations(observations, source="local_probe")
    record_immersive_telemetry_event(source, added=added)


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
