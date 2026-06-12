from __future__ import annotations

import functools
from importlib import resources
import json
from pathlib import Path
import tempfile
from typing import Any

from normal.models import utc_now_iso
from normal.movie_naming import match_variant_keys, title_match_key


STORE_VERSION = 1
VALID_VERDICTS = {"available", "final_below_target", "unknown"}


def default_store_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "immersive-confirmations.json"


def confirmation_key(title: str, year: int) -> str:
    return f"{title_match_key(title)}|{int(year)}"


# --- Bundled seed lists (temporary) -------------------------------------------
# Title-level object-audio (Dolby Atmos / DTS:X) availability seeds, loaded from
# the versioned, provenance-carrying data file rather than inlined here. Each
# entry is a title-level claim, not a claim about any local file: the seed only
# corroborates a candidate; the file-level probe still does the confirming. Both
# lists are merged *under* the user store in confirmation_index() and overridable
# by it, so they can be retired once crowdsourced confirmations cover the library
# (see docs/internal/atmos-availability-and-crowdsource-of-truth.md).
SEED_DATA_RESOURCE = ("normal", "data", "immersive_seeds.json")
SEED_DATA_VERSION = 1


@functools.lru_cache(maxsize=1)
def _load_seed_data() -> dict[str, Any]:
    package, *parts = SEED_DATA_RESOURCE
    raw = resources.files(package).joinpath(*parts).read_text(encoding="utf-8")
    payload = json.loads(raw)
    version = payload.get("version")
    if version != SEED_DATA_VERSION:
        raise ValueError(f"unsupported immersive seed data version: {version}")
    return payload


def _seed_list(list_name: str) -> dict[str, Any]:
    return _load_seed_data()["lists"][list_name]


def _seed_entries(list_name: str) -> tuple[tuple[str, int], ...]:
    return tuple((entry["title"], int(entry["year"])) for entry in _seed_list(list_name)["entries"])


def seed_provenance(list_name: str) -> dict[str, Any]:
    """Provenance metadata (source, reference, asserted_on, note, verdict) for a
    seed list, for audit/UI surfacing of where a seed claim came from."""
    info = _seed_list(list_name)
    keys = ("verdict", "source", "reference", "asserted_on", "note")
    return {key: info[key] for key in keys if key in info}


SEED_VERDICT = _seed_list("available")["verdict"]
SEED_TITLES: tuple[tuple[str, int], ...] = _seed_entries("available")

SEED_NOT_AVAILABLE_VERDICT = _seed_list("not_available")["verdict"]
SEED_NOT_AVAILABLE: tuple[tuple[str, int], ...] = _seed_entries("not_available")


def seed_index() -> dict[str, str]:
    return {confirmation_key(title, year): SEED_VERDICT for title, year in SEED_TITLES}


def not_available_seed_index() -> dict[str, str]:
    return {
        confirmation_key(title, year): SEED_NOT_AVAILABLE_VERDICT
        for title, year in SEED_NOT_AVAILABLE
    }


# Availability always outranks unavailability: a single proven object-audio
# observation falsifies any "not available" claim, no matter how much absence
# evidence accumulated.
_VERDICT_PRECEDENCE = {"final_below_target": 1, "available": 2}


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
        if not (isinstance(record, dict) and record.get("verdict") in VALID_VERDICTS):
            continue
        # Self-migrate: re-key from the record's stored title/year so records
        # written under an older title_match_key (e.g. before accent/& folding)
        # are looked up under the current key without a one-shot migration.
        resolved_key = str(key)
        title = record.get("title")
        year = record.get("year")
        if title is not None and year is not None:
            try:
                resolved_key = confirmation_key(str(title), int(year))
            except (TypeError, ValueError):
                resolved_key = str(key)
        record = {**record, "key": resolved_key}
        normalized[resolved_key] = record
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
    index: dict[str, str] = {}

    def consider(key: str, verdict: Any) -> None:
        if verdict not in _VERDICT_PRECEDENCE:
            return
        current = index.get(key)
        if current is None or _VERDICT_PRECEDENCE[verdict] >= _VERDICT_PRECEDENCE[current]:
            index[key] = verdict

    for key, verdict in not_available_seed_index().items():
        consider(key, verdict)
    for key, verdict in seed_index().items():
        consider(key, verdict)
    payload = load_confirmations(state_path)
    for key, record in payload["records"].items():
        verdict = record.get("verdict")
        if verdict == "unknown":
            index.pop(key, None)
        else:
            consider(key, verdict)
    return index


def lookup_verdict(index: dict[str, str], title: str, year: int) -> str | None:
    """Resolve a title/year against a confirmation index, bridging numeral
    spelling. Accents and ``&`` are already folded by ``title_match_key``; this
    additionally tries roman/arabic variants so ``Part II`` finds a ``Part 2``
    seed and vice versa."""
    try:
        resolved_year = int(year)
    except (TypeError, ValueError):
        return None
    for variant in match_variant_keys(title):
        verdict = index.get(f"{variant}|{resolved_year}")
        if verdict is not None:
            return verdict
    return None


def record_available_observations(
    observations: Any,
    source: str = "local_probe",
    state_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Record titles observed to carry object audio as immersive-available.

    `observations` is an iterable of (title, year). A single load/save covers
    the whole batch. Only titles not already resolved to `available` are
    written; the records newly added are returned (for audit emission).
    """
    index = confirmation_index(state_path)
    payload = load_confirmations(state_path)
    added: list[dict[str, Any]] = []
    seen: set[str] = set()
    for title, year in observations:
        if not str(title or "").strip():
            continue
        try:
            resolved_year = int(year)
        except (TypeError, ValueError):
            continue
        key = confirmation_key(title, resolved_year)
        if key in seen or index.get(key) == "available":
            continue
        seen.add(key)
        record = {
            "key": key,
            "title": title,
            "year": resolved_year,
            "verdict": "available",
            "source": source,
            "recorded_at": utc_now_iso(),
        }
        payload["records"][key] = record
        added.append(record)
    if added:
        save_confirmations(payload, state_path)
    return added


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
