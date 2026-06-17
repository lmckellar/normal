from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from normal import library_roots
from normal.source_policy import ApprovedRoots, Operation, SourcePolicyError, validate_source_for_operation
from .activity import build_activity_payload
from .http import RequestContext
from .scan_guard import build_source_scan_warning


def library_roots_path():
    return library_roots.library_roots_path()


def _validated_library_root(source: str, approved_roots: ApprovedRoots) -> str:
    validated = validate_source_for_operation(
        Path(source),
        operation=Operation.APPLY,
        approved_roots=approved_roots,
    )
    return str(validated)


def load_library_roots(approved_roots: ApprovedRoots) -> dict[str, Any]:
    data = library_roots.load_library_roots_payload()
    movies = data["movies"]
    tv = data["tv"]
    recent = library_roots.normalize_recent_library_roots(data["recent"])
    try:
        movies = _validated_library_root(movies, approved_roots) if movies else ""
    except (OSError, ValueError, SourcePolicyError):
        movies = ""
    try:
        tv = _validated_library_root(tv, approved_roots) if tv else ""
    except (OSError, ValueError, SourcePolicyError):
        tv = ""
    validated_recent = []
    for item in recent:
        try:
            source = _validated_library_root(item["source"], approved_roots)
        except (OSError, ValueError, SourcePolicyError):
            continue
        validated_recent.append({**item, "source": source})
    return {"movies": movies, "tv": tv, "recent": validated_recent}


def save_library_roots(data: dict[str, Any], approved_roots: ApprovedRoots) -> None:
    movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
    tv = data.get("tv") if isinstance(data.get("tv"), str) else ""
    recent = library_roots.normalize_recent_library_roots(data.get("recent"))
    movies = _validated_library_root(movies, approved_roots) if movies else ""
    tv = _validated_library_root(tv, approved_roots) if tv else ""
    recent = [
        {**item, "source": _validated_library_root(item["source"], approved_roots)}
        for item in recent
    ]
    path = library_roots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {**library_roots.empty_library_roots_payload(), "movies": movies, "tv": tv, "recent": recent},
        indent=2,
    ) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def handle_activity(ctx: RequestContext) -> None:
    qs = parse_qs(urlparse(ctx.handler.path).query)
    raw_source = qs.get("source", [None])[0]
    source = ctx.resolve_source(raw_source)
    ctx.respond_json(build_activity_payload(source))


def handle_library_roots_get(ctx: RequestContext) -> None:
    ctx.respond_json(load_library_roots(ctx.approved_roots))


def handle_library_roots_post(ctx: RequestContext, payload: dict[str, Any]) -> None:
    save_library_roots(payload, ctx.approved_roots)
    ctx.respond_json(load_library_roots(ctx.approved_roots))


def handle_source_scan_warning(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    ctx.respond_json(build_source_scan_warning(source))
