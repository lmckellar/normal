from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from normal import paths

SUPPORTED_LIBRARY_ROOT_LANES = frozenset({"movies", "tv"})
MAX_RECENT_LIBRARY_ROOTS = 2


def library_roots_path() -> Path:
    return paths.data_dir() / "library-roots.json"


def empty_library_roots_payload() -> dict[str, Any]:
    return {"movies": "", "tv": "", "recent": []}


def normalize_library_root_lane(value: Any) -> str:
    lane = str(value or "").strip().lower()
    if lane in {"movie", "movies"}:
        return "movies"
    if lane in {"tv", "tv_shows"}:
        return "tv"
    return ""


def normalize_recent_library_roots(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    recent: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        lane = normalize_library_root_lane(item.get("lane"))
        source = item.get("source")
        if not lane or not isinstance(source, str) or not source:
            continue
        recent.append({"lane": lane, "source": source})
    return recent[:MAX_RECENT_LIBRARY_ROOTS]


def load_library_roots_payload() -> dict[str, Any]:
    path = library_roots_path()
    if not path.exists():
        return empty_library_roots_payload()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_library_roots_payload()
    if not isinstance(data, dict):
        return empty_library_roots_payload()
    movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
    tv = data.get("tv") if isinstance(data.get("tv"), str) else ""
    recent = normalize_recent_library_roots(data.get("recent"))
    return {"movies": movies, "tv": tv, "recent": recent}


def iter_saved_library_root_paths() -> list[Path]:
    payload = load_library_roots_payload()
    seen: set[Path] = set()
    roots: list[Path] = []
    for raw_source in [payload.get("movies"), payload.get("tv"), *[item["source"] for item in payload["recent"]]]:
        if not isinstance(raw_source, str) or not raw_source:
            continue
        try:
            resolved = Path(raw_source).expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots
