from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .activity import build_activity_payload
from .http import RequestContext
from .scan_guard import build_source_scan_warning


def library_roots_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "library-roots.json"


def load_library_roots() -> dict[str, Any]:
    path = library_roots_path()
    if not path.exists():
        return {"movies": "", "recent": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"movies": "", "recent": []}
        movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
        recent = data.get("recent") if isinstance(data.get("recent"), list) else []
        recent = [
            r for r in recent
            if isinstance(r, dict)
            and r.get("lane") == "movies"
            and isinstance(r.get("source"), str)
            and r["source"]
        ][:2]
        return {"movies": movies, "recent": recent}
    except (OSError, json.JSONDecodeError):
        return {"movies": "", "recent": []}


def save_library_roots(data: dict[str, Any]) -> None:
    path = library_roots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
    recent = data.get("recent") if isinstance(data.get("recent"), list) else []
    recent = [
        r for r in recent
        if isinstance(r, dict)
        and r.get("lane") == "movies"
        and isinstance(r.get("source"), str)
        and r["source"]
    ][:2]
    payload = json.dumps({"movies": movies, "recent": recent}, indent=2) + "\n"
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
    ctx.respond_json(load_library_roots())


def handle_library_roots_post(ctx: RequestContext, payload: dict[str, Any]) -> None:
    save_library_roots(payload)
    ctx.respond_json(load_library_roots())


def handle_source_scan_warning(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.inspect_source(payload.get("source"))
    ctx.respond_json(build_source_scan_warning(source))
