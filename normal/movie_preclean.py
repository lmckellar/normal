from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


MOVIE_PRECLEAN_LEDGER_PATH = Path("out/manual-cleanup/movie-preclean.jsonl")
MOVIE_PRECLEAN_BUCKETS = {
    "junk_extras",
    "misplaced_non_movie",
    "nonrecoverable_identity",
    "duplicate_or_collision_cleanup",
}


@dataclass(frozen=True, slots=True)
class MoviePrecleanEntry:
    path: str
    action: str
    reason: str
    bucket: str
    notes: str
    timestamp: str


def load_movie_preclean_entries(ledger_path: Path = MOVIE_PRECLEAN_LEDGER_PATH) -> list[MoviePrecleanEntry]:
    if not ledger_path.exists():
        return []

    entries: list[MoviePrecleanEntry] = []
    for raw_line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        bucket = payload.get("bucket", "")
        if bucket not in MOVIE_PRECLEAN_BUCKETS:
            raise ValueError(f"unknown movie pre-clean bucket: {bucket}")
        entries.append(
            MoviePrecleanEntry(
                path=str(payload.get("path", "")),
                action=str(payload.get("action", "")),
                reason=str(payload.get("reason", "")),
                bucket=bucket,
                notes=str(payload.get("notes", "")),
                timestamp=str(payload.get("timestamp", "")),
            )
        )
    return entries


def filter_movie_files_with_preclean(movie_files: list[Path], entries: list[MoviePrecleanEntry]) -> list[Path]:
    excluded_roots = [Path(entry.path).resolve() for entry in entries]
    filtered: list[Path] = []
    for movie_path in movie_files:
        resolved = movie_path.resolve()
        if any(is_relative_to(resolved, excluded_root) for excluded_root in excluded_roots):
            continue
        filtered.append(movie_path)
    return filtered


def is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True
