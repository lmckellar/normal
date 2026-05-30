from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
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


NORMALIZE_LAB_EXPORT_ROOT = Path(__file__).resolve().parents[2] / "out" / "parser-tester-ui"


def handle_movies_normalize_lab_export(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a non-empty list")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    NORMALIZE_LAB_EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    filename = f"parser-tester-ui-{timestamp}.jsonl"
    export_path = NORMALIZE_LAB_EXPORT_ROOT / filename
    exported = 0
    with export_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = {
                "source_root": str(source),
                "raw_path": str(row.get("current_value") or row.get("path") or ""),
                "proposed_path": str(row.get("projected_path") or row.get("proposed_value") or ""),
                "confidence": str(row.get("confidence") or ""),
                "reason_codes": [str(value) for value in row.get("reason_codes", []) if str(value)],
                "warning_codes": [str(value) for value in row.get("warning_codes", []) if str(value)],
                "title_source": str(row.get("title_source") or ""),
                "year_source": str(row.get("year_source") or ""),
                "linked_changes": row.get("linked_changes") or row.get("change_ids") or [],
                "linked_change_types": row.get("linked_change_types") or [],
            }
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
            exported += 1
    ctx.respond_json({"exported": exported, "path": str(export_path)})
