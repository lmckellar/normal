from __future__ import annotations

from typing import Any

from normal.models import ProposedChange
from normal.movie_apply import apply_changes_in_place
from normal.movie_plan import build_movie_plan, parse_movie_name_with_sidecar_fallback
from normal.movie_scan import discover_video_files

from .http import RequestContext
from .scan_guard import guarded_heavy_scan
from .serializers import build_movie_normalize_results
from .state import MOVIE_PROFILE_CACHE


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
