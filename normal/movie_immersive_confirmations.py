from __future__ import annotations

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
    ("1917", 2019),
    ("A Quiet Place", 2018),
    ("A Quiet Place Part II", 2020),
    ("Alien: Romulus", 2024),
    ("Aliens", 1986),
    ("Alita: Battle Angel", 2019),
    ("Apollo 13", 1995),
    ("Aquaman", 2018),
    ("Atomic Blonde", 2017),
    ("Avatar", 2009),
    ("Avatar: The Way of Water", 2022),
    ("Avengers: Endgame", 2019),
    ("Avengers: Infinity War", 2018),
    ("Batman v Superman: Dawn of Justice", 2016),
    ("Black Hawk Down", 2001),
    ("Black Panther", 2018),
    ("Blade Runner", 1982),
    ("Bohemian Rhapsody", 2018),
    ("Bram Stoker's Dracula", 1992),
    ("Braveheart", 1995),
    ("Captain Marvel", 2019),
    ("Casino", 1995),
    ("Crouching Tiger, Hidden Dragon", 2000),
    ("Deadpool", 2016),
    ("Deadpool 2", 2018),
    ("Doctor Strange", 2016),
    ("Edge of Tomorrow", 2014),
    ("First Man", 2018),
    ("Ford v Ferrari", 2019),
    ("Fury", 2014),
    ("Gladiator", 2000),
    ("Godzilla", 2014),
    ("Godzilla vs. Kong", 2021),
    ("Godzilla: King of the Monsters", 2019),
    ("Gravity", 2013),
    ("Guardians of the Galaxy", 2014),
    ("Guardians of the Galaxy Vol. 2", 2017),
    ("Guardians of the Galaxy Vol. 3", 2023),
    ("Hacksaw Ridge", 2016),
    ("Harry Potter and the Sorcerer's Stone", 2001),
    ("It", 2017),
    ("Jaws", 1975),
    ("John Wick", 2014),
    ("John Wick: Chapter 2", 2017),
    ("John Wick: Chapter 3 - Parabellum", 2019),
    ("Joker", 2019),
    ("Jurassic Park", 1993),
    ("Jurassic Park III", 2001),
    ("Jurassic World", 2015),
    ("Knives Out", 2019),
    ("Kong: Skull Island", 2017),
    ("La La Land", 2016),
    ("Logan", 2017),
    ("Man of Steel", 2013),
    ("Pacific Rim", 2013),
    ("Ready Player One", 2018),
    ("Saving Private Ryan", 1998),
    ("Spider-Man", 2002),
    ("Spider-Man: Across the Spider-Verse", 2023),
    ("Spider-Man: Far from Home", 2019),
    ("Spider-Man: Homecoming", 2017),
    ("Spider-Man: Into the Spider-Verse", 2018),
    ("Spider-Man: No Way Home", 2021),
    ("The Abyss", 1989),
    ("The Batman", 2022),
    ("The Fifth Element", 1997),
    ("The Great Wall", 2016),
    ("The Lord of the Rings: The Fellowship of the Ring", 2001),
    ("The Lord of the Rings: The Return of the King", 2003),
    ("The Lord of the Rings: The Two Towers", 2002),
    ("The Matrix", 1999),
    ("The Matrix Reloaded", 2003),
    ("The Matrix Revolutions", 2003),
    ("The Super Mario Bros. Movie", 2023),
    ("Thor: Ragnarok", 2017),
    ("Titanic", 1997),
    ("True Lies", 1994),
    ("Wonder Woman", 2017),
)


def seed_index() -> dict[str, str]:
    return {confirmation_key(title, year): SEED_VERDICT for title, year in SEED_TITLES}


# --- Not-available seed (temporary) -------------------------------------------
# Titles editorially asserted to have NO object-based (Atmos / DTS:X) release at
# present — only channel/bed mixes have ever shipped. Same epistemic status as
# SEED_TITLES: a title-level claim, not a file claim, and provisional ("for
# now") — the moment one object-audio copy surfaces anywhere, the available
# signal must override this (see confirmation_index precedence). This hand seed
# is a stand-in for the deferred consensus-of-absence engine documented in
# docs/internal/atmos-availability-and-crowdsource-of-truth.md.
SEED_NOT_AVAILABLE_VERDICT = "final_below_target"
SEED_NOT_AVAILABLE: tuple[tuple[str, int], ...] = (
    ("A Good Day to Die Hard", 2013),
    ("Election", 1999),
    ("The Firm", 1993),
    ("Vanilla Sky", 2001),
    ("Mission: Impossible", 1996),
    ("Mission: Impossible II", 2000),
    ("Days of Thunder", 1990),
    ("Beverly Hills Cop", 1984),
    ("Beverly Hills Cop II", 1987),
    ("Beverly Hills Cop III", 1994),
    ("Ferris Bueller's Day Off", 1986),
    ("Flashdance", 1983),
    ("Footloose", 1984),
    ("Planes, Trains & Automobiles", 1987),
    ("Scrooged", 1988),
    ("Indecent Proposal", 1993),
    ("Saturday Night Fever", 1977),
    ("Trading Places", 1983),
    ("Chinatown", 1974),
    ("The Italian Job", 1969),
    ("The Naked Gun: From the Files of Police Squad!", 1988),
    ("The Hunt for Red October", 1990),
    ("Patriot Games", 1992),
    ("Clear and Present Danger", 1994),
    ("The Sum of All Fears", 2002),
    ("Coming to America", 1988),
    ("The War of the Worlds", 1953),
    ("Blood Simple", 1984),
    ("Lone Star", 1996),
    ("The Piano", 1993),
    ("The Last Picture Show", 1971),
    ("Raging Bull", 1980),
    ("Trainspotting", 1996),
    ("Bound", 1996),
    ("The Fisher King", 1991),
    ("The Sting", 1973),
)


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
