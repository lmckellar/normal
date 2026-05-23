from __future__ import annotations

from typing import Any

from normal.models import ProposedChange
from normal.movie_apply import apply_changes_in_place
from normal.movie_plan import DEFAULT_MOVIE_NAMING_STYLE, MOVIE_NAMING_STYLES, build_movie_plan
from normal.movie_scan import discover_video_files

from .http import RequestContext
from .scan_guard import guarded_heavy_scan
from .serializers import build_movie_normalize_results
from .state import MOVIE_PROFILE_CACHE


def _build_normalize_payload(source, requested_style, movie_files, plans_by_style):
    response = plans_by_style[requested_style].to_dict()
    response["naming_style"] = requested_style
    response["default_naming_style"] = DEFAULT_MOVIE_NAMING_STYLE
    response["proposed_changes_by_naming_style"] = {
        style: plans_by_style[style].to_dict()["proposed_changes"] for style in MOVIE_NAMING_STYLES
    }
    response["warnings_by_naming_style"] = {
        style: plans_by_style[style].to_dict()["warnings"] for style in MOVIE_NAMING_STYLES
    }
    response["movie_results_by_naming_style"] = {
        style: build_movie_normalize_results(source, movie_files, plans_by_style[style].proposed_changes)
        for style in MOVIE_NAMING_STYLES
    }
    response["movie_files"] = [str(path) for path in movie_files]
    return response


def handle_movies_normalize(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    requested_style = str(payload.get("naming_style") or DEFAULT_MOVIE_NAMING_STYLE)
    if requested_style not in MOVIE_NAMING_STYLES:
        raise ValueError(f"unknown movie naming style: {requested_style}")
    with guarded_heavy_scan(source, "Movie normalize plan"):
        with ctx.handler.activity_tracker.track(source, "Movie normalize plan"):
            movie_files = discover_video_files(source)
            plans_by_style = {style: build_movie_plan(source, naming_style=style, movie_files=movie_files) for style in MOVIE_NAMING_STYLES}
            response = _build_normalize_payload(source, requested_style, movie_files, plans_by_style)
    ctx.respond_json(response)


def handle_movies_apply(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    requested_style = str(payload.get("naming_style") or DEFAULT_MOVIE_NAMING_STYLE)
    if requested_style not in MOVIE_NAMING_STYLES:
        raise ValueError(f"unknown movie naming style: {requested_style}")
    raw_changes = payload.get("changes", [])
    if not isinstance(raw_changes, list):
        raise ValueError("changes must be a list")
    changes = [ProposedChange(**c) for c in raw_changes]
    with ctx.handler.activity_tracker.track(source, "Movie apply"):
        report = apply_changes_in_place(source, changes)
        MOVIE_PROFILE_CACHE.invalidate(source)
        movie_files = discover_video_files(source)
        plans_by_style = {style: build_movie_plan(source, naming_style=style, movie_files=movie_files) for style in MOVIE_NAMING_STYLES}
    response = report.to_dict()
    remaining_payload = _build_normalize_payload(source, requested_style, movie_files, plans_by_style)
    remaining_changes = remaining_payload["proposed_changes"]
    response["remaining_changes"] = remaining_changes
    response["remaining_safe_count"] = len([change for change in remaining_changes if change["confidence"] == "safe"])
    response["remaining_review_count"] = len([change for change in remaining_changes if change["confidence"] == "review"])
    response["remaining_plan"] = remaining_payload if remaining_changes else None
    ctx.respond_json(response)
