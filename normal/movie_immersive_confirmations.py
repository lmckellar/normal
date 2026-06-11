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
