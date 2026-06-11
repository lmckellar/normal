from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from normal.models import utc_now_iso
from normal.movie_naming import title_match_key


STORE_VERSION = 1
VALID_VERDICTS = {"available", "final_below_target", "unknown"}


def default_store_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "immersive-confirmations.json"


def confirmation_key(title: str, year: int) -> str:
    return f"{title_match_key(title)}|{int(year)}"


# --- Booster seed (temporary) -------------------------------------------------
# Titles known to ship an object-based (Dolby Atmos / DTS:X) release. These are
# title-level facts, not claims about any local file: the seed only corroborates
# a candidate, the file-level probe still does the confirming. Merged *under* the
# user store in confirmation_index() and overridable by it, so this whole block
# can be deleted once crowdsourced confirmations cover the library. Swap
# SEED_TITLES for a bundled JSON load when the real list lands.
SEED_VERDICT = "available"
SEED_TITLES: tuple[tuple[str, int], ...] = (
    ("Mission: Impossible - Fallout", 2018),
    ("Mad Max: Fury Road", 2015),
    ("Blade Runner 2049", 2017),
    ("Dune", 2021),
    ("Top Gun: Maverick", 2022),
    ("John Wick: Chapter 4", 2023),
)


def seed_index() -> dict[str, str]:
    return {confirmation_key(title, year): SEED_VERDICT for title, year in SEED_TITLES}


def normalize_verdict(value: Any) -> str:
    verdict = str(value or "").strip().casefold()
    if verdict not in VALID_VERDICTS:
        raise ValueError(f"unsupported verdict: {verdict}")
    return verdict


def load_confirmations(state_path: Path | None = None) -> dict[str, Any]:
    path = state_path or default_store_path()
    if not path.exists():
        return {"version": STORE_VERSION, "records": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": STORE_VERSION, "records": {}}
    if not isinstance(payload, dict):
        return {"version": STORE_VERSION, "records": {}}
    records = payload.get("records")
    if not isinstance(records, dict):
        records = {}
    normalized: dict[str, Any] = {}
    for key, record in records.items():
        if isinstance(record, dict) and record.get("verdict") in VALID_VERDICTS:
            normalized[str(key)] = record
    return {"version": STORE_VERSION, "records": normalized}


def save_confirmations(payload: dict[str, Any], state_path: Path | None = None) -> None:
    path = state_path or default_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"version": STORE_VERSION, "records": payload.get("records", {})}, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def confirmation_index(state_path: Path | None = None) -> dict[str, str]:
    index = dict(seed_index())
    payload = load_confirmations(state_path)
    for key, record in payload["records"].items():
        verdict = record.get("verdict")
        if verdict == "unknown":
            index.pop(key, None)
        elif verdict in VALID_VERDICTS:
            index[key] = verdict
    return index


def set_confirmation(
    title: str,
    year: int,
    verdict: Any,
    source: str = "user_confirm",
    state_path: Path | None = None,
) -> dict[str, Any]:
    resolved = normalize_verdict(verdict)
    key = confirmation_key(title, year)
    payload = load_confirmations(state_path)
    if resolved == "unknown":
        record = {
            "key": key,
            "title": title,
            "year": int(year),
            "verdict": "unknown",
            "source": source,
            "recorded_at": utc_now_iso(),
        }
        payload["records"][key] = record
    else:
        record = {
            "key": key,
            "title": title,
            "year": int(year),
            "verdict": resolved,
            "source": source,
            "recorded_at": utc_now_iso(),
        }
        payload["records"][key] = record
    save_confirmations(payload, state_path)
    return record
