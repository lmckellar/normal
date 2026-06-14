from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from normal import paths
from normal.models import utc_now_iso


HISTORY_VERSION = 1
_TITLE_YEAR_RE = re.compile(r"^(.+?)\s*\((\d{4})\)")


def default_history_path() -> Path:
    return paths.subtitle_history_path()


def load_history(state_path: Path | None = None) -> dict[str, Any]:
    path = state_path or default_history_path()
    if not path.exists():
        return {"version": HISTORY_VERSION, "items": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": HISTORY_VERSION, "items": []}
    if not isinstance(payload, dict):
        return {"version": HISTORY_VERSION, "items": []}
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    return {"version": HISTORY_VERSION, "items": [i for i in items if isinstance(i, dict)]}


def save_history(payload: dict[str, Any], state_path: Path | None = None) -> None:
    path = state_path or default_history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"version": HISTORY_VERSION, "items": payload.get("items", [])}, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _item_id(source_root: str, path: str, entry_type: str) -> str:
    raw = f"{source_root}\x00{path}\x00{entry_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _parse_title_year(path: str) -> tuple[str, int | None]:
    stem = Path(path).stem
    m = _TITLE_YEAR_RE.match(stem)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return stem, None


def history_for_source(source_root: str, state_path: Path | None = None) -> dict[str, Any]:
    source = str(Path(source_root).resolve())
    history = load_history(state_path)
    items = [i for i in history["items"] if i.get("source_root") == source]
    return {"source_root": source, "items": items}


def upsert_items(
    source_root: str,
    raw_items: list[dict[str, Any]],
    entry_type: str,
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = str(Path(source_root).resolve())
    history = load_history(state_path)
    now = utc_now_iso()
    by_id = {i["item_id"]: i for i in history["items"] if i.get("item_id")}

    for raw in raw_items:
        path = str(raw.get("path") or "")
        if not path:
            continue
        issue_code = str(raw.get("issue_code") or "")
        item_id = _item_id(source, path, entry_type)
        title, year = _parse_title_year(path)
        existing = by_id.get(item_id) or {}
        by_id[item_id] = {
            "item_id": item_id,
            "source_root": source,
            "path": path,
            "title": title,
            "year": year,
            "issue_code": issue_code,
            "entry_type": entry_type,
            "recorded_at": existing.get("recorded_at") or now,
            "updated_at": now,
            "dismissed_at": existing.get("dismissed_at"),
        }

    history["items"] = list(by_id.values())
    save_history(history, state_path)
    return history_for_source(source, state_path)


def dismiss_items(
    source_root: str,
    item_ids: list[str],
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = str(Path(source_root).resolve())
    history = load_history(state_path)
    now = utc_now_iso()
    ids = set(item_ids)
    history["items"] = [
        {**i, "dismissed_at": now} if (i.get("item_id") in ids and i.get("source_root") == source) else i
        for i in history["items"]
    ]
    save_history(history, state_path)
    return history_for_source(source, state_path)
