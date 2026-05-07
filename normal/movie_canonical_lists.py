from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from normal.models import WarningItem, utc_now_iso
from normal.movie_identity import MovieIdentityKey, canonical_identity_key, parse_movie_identity
from normal.movie_scan import iter_video_files


TMDB_API_ROOT = "https://api.themoviedb.org/3"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
GENRE_VOTE_FLOOR = 5000
TOP_RATED_PAGE_LIMIT = 50
CACHE_SCHEMA_VERSION = "v2"


@dataclass(frozen=True, slots=True)
class CanonicalListConfig:
    id: str
    label: str
    size: int
    badge_label: str
    badge_threshold_percent: float
    color: str
    source_kind: str
    genre_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalListEntry:
    title: str
    year: int

    def to_key(self) -> MovieIdentityKey:
        return canonical_identity_key(self.title, self.year)


@dataclass(slots=True)
class OwnedMovie:
    title: str
    year: int
    path: str


@dataclass(slots=True)
class CanonicalListSummary:
    id: str
    label: str
    provider_label: str
    total_count: int
    covered_count: int
    coverage_percent: float
    missing_count: int
    owned_titles: list[dict[str, Any]] = field(default_factory=list)
    missing_titles: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class CanonicalBadge:
    id: str
    label: str
    color: str
    unlocked: bool
    coverage_percent: float
    threshold_percent: float


@dataclass(slots=True)
class CanonicalLibrarySummary:
    owned_movies: int
    matched_canonical_titles: int
    lists_cleared: int
    unparsed_files: int
    duplicate_files: int


@dataclass(slots=True)
class CanonicalListsReport:
    source_root: str
    generated_at: str
    provider: str
    cache_state: str
    library_summary: CanonicalLibrarySummary
    list_summaries: list[CanonicalListSummary] = field(default_factory=list)
    badges: list[CanonicalBadge] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CANONICAL_LISTS: tuple[CanonicalListConfig, ...] = (
    CanonicalListConfig("top_100", "Top 100", 100, "TOP 100", 75.0, "#f94144", "top_rated"),
    CanonicalListConfig("top_250", "Top 250", 250, "TOP 250", 65.0, "#f3722c", "top_rated"),
    CanonicalListConfig("top_1000", "Top 1000", 1000, "TOP 1000", 40.0, "#f8961e", "top_rated"),
    CanonicalListConfig("sci_fi", "Sci-Fi", 100, "SCI-FI", 60.0, "#f9c74f", "genre", (878,)),
    CanonicalListConfig("fantasy", "Fantasy", 100, "FANTASY", 60.0, "#90be6d", "genre", (14,)),
    CanonicalListConfig("action", "Action", 100, "ACTION", 60.0, "#43aa8b", "genre", (28,)),
    CanonicalListConfig("thriller_mystery", "Thriller / Mystery", 100, "THRILLER", 60.0, "#577590", "genre", (53, 9648)),
    CanonicalListConfig("suspense_horror", "Suspense / Horror", 100, "HORROR", 60.0, "#277da1", "genre", (27, 53)),
    CanonicalListConfig("comedy", "Comedy", 100, "COMEDY", 60.0, "#4d908e", "genre", (35,)),
)


def build_canonical_lists_report(
    source_root: Path,
    tmdb_key: str | None,
    http_get: Callable[[str], dict[str, Any]] | None = None,
    now: Callable[[], float] = time.time,
    should_cancel: Callable[[], bool] | None = None,
) -> CanonicalListsReport:
    if not tmdb_key:
        raise ValueError("TMDb API key is required for Movies / Canonical Lists. Pass --tmdb-key or set TMDB_KEY.")

    cache_states: list[str] = []
    inventory, unparsed_files, duplicate_files = build_movie_inventory(source_root, should_cancel=should_cancel)
    provider = TMDbCanonicalProvider(tmdb_key=tmdb_key, http_get=http_get, now=now)
    list_summaries: list[CanonicalListSummary] = []
    badges: list[CanonicalBadge] = []
    matched_keys: set[MovieIdentityKey] = set()

    for config in CANONICAL_LISTS:
        entries, cache_state = provider.list_entries(config)
        cache_states.append(cache_state)
        reference_keys = {entry.to_key() for entry in entries}
        covered_keys = sorted(reference_keys & set(inventory), key=lambda item: (inventory[item].title, inventory[item].year))
        missing_keys = sorted(reference_keys - set(inventory), key=lambda item: (item.title, item.year))
        matched_keys.update(covered_keys)
        total_count = len(reference_keys)
        covered_count = len(covered_keys)
        coverage_percent = round((covered_count / total_count) * 100, 1) if total_count else 0.0
        list_summaries.append(
            CanonicalListSummary(
                id=config.id,
                label=config.label,
                provider_label="TMDb canonical list",
                total_count=total_count,
                covered_count=covered_count,
                coverage_percent=coverage_percent,
                missing_count=len(missing_keys),
                owned_titles=[{"title": inventory[key].title, "year": inventory[key].year} for key in covered_keys[:12]],
                missing_titles=[{"title": key.title, "year": key.year} for key in missing_keys[:12]],
            )
        )
        badges.append(
            CanonicalBadge(
                id=config.id,
                label=config.badge_label,
                color=config.color,
                unlocked=coverage_percent >= config.badge_threshold_percent,
                coverage_percent=coverage_percent,
                threshold_percent=config.badge_threshold_percent,
            )
        )

    cache_state = "fresh"
    if cache_states and any(state == "stale" for state in cache_states):
        cache_state = "stale"
    elif cache_states and all(state == "live" for state in cache_states):
        cache_state = "live"

    library_summary = CanonicalLibrarySummary(
        owned_movies=len(inventory),
        matched_canonical_titles=len(matched_keys),
        lists_cleared=sum(1 for badge in badges if badge.unlocked),
        unparsed_files=unparsed_files,
        duplicate_files=duplicate_files,
    )
    return CanonicalListsReport(
        source_root=str(source_root.resolve()),
        generated_at=utc_now_iso(),
        provider="tmdb",
        cache_state=cache_state,
        library_summary=library_summary,
        list_summaries=list_summaries,
        badges=badges,
    )


def build_movie_inventory(
    source_root: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[dict[MovieIdentityKey, OwnedMovie], int, int]:
    inventory: dict[MovieIdentityKey, OwnedMovie] = {}
    unparsed_files = 0
    duplicate_files = 0
    for movie_path in iter_video_files(source_root, should_cancel=should_cancel):
        parsed = parse_movie_identity(movie_path)
        if parsed.title is None or parsed.year is None:
            unparsed_files += 1
            continue
        key = canonical_identity_key(parsed.title, parsed.year)
        if key in inventory:
            duplicate_files += 1
            continue
        inventory[key] = OwnedMovie(title=parsed.title, year=parsed.year, path=str(movie_path))
    return inventory, unparsed_files, duplicate_files


class TMDbCanonicalProvider:
    def __init__(
        self,
        *,
        tmdb_key: str,
        http_get: Callable[[str], dict[str, Any]] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.tmdb_key = tmdb_key
        self.http_get = http_get or self._http_get
        self.now = now
        self._top_rated_cache: list[CanonicalListEntry] | None = None
        self._top_rated_cache_state: str | None = None

    def list_entries(self, config: CanonicalListConfig) -> tuple[list[CanonicalListEntry], str]:
        if config.source_kind == "top_rated":
            entries, cache_state = self._top_rated_entries()
            return entries[: config.size], cache_state
        entries, cache_state = self._genre_entries(config)
        return entries[: config.size], cache_state

    def _top_rated_entries(self) -> tuple[list[CanonicalListEntry], str]:
        if self._top_rated_cache is not None and self._top_rated_cache_state is not None:
            return self._top_rated_cache, self._top_rated_cache_state
        config_key = hashlib.sha1(b"tmdb_top_rated").hexdigest()[:10]
        entries, cache_state = self._fetch_with_cache(
            cache_name=f"top_rated_{config_key}.json",
            build_entries=self._fetch_top_rated_entries,
        )
        self._top_rated_cache = entries
        self._top_rated_cache_state = cache_state
        return entries, cache_state

    def _genre_entries(self, config: CanonicalListConfig) -> tuple[list[CanonicalListEntry], str]:
        genre_key = "-".join(str(item) for item in config.genre_ids)
        cache_key = hashlib.sha1(f"{config.id}:{genre_key}".encode("utf-8")).hexdigest()[:10]
        return self._fetch_with_cache(
            cache_name=f"{config.id}_{cache_key}.json",
            build_entries=lambda: self._fetch_genre_entries(config),
        )

    def _fetch_with_cache(
        self,
        *,
        cache_name: str,
        build_entries: Callable[[], list[CanonicalListEntry]],
    ) -> tuple[list[CanonicalListEntry], str]:
        cache_path = canonical_cache_dir() / cache_name
        cached = load_cache_entries(cache_path, now=self.now)
        if cached is not None and not cached["stale"]:
            return cached["entries"], "fresh"
        try:
            entries = build_entries()
            write_cache_entries(cache_path, entries, fetched_at=self.now())
            return entries, "live"
        except (HTTPError, URLError, TimeoutError, ValueError):
            if cached is not None:
                return cached["entries"], "stale"
            raise

    def _fetch_top_rated_entries(self) -> list[CanonicalListEntry]:
        entries: list[CanonicalListEntry] = []
        seen: set[MovieIdentityKey] = set()
        for page in range(1, TOP_RATED_PAGE_LIMIT + 1):
            payload = self.http_get(
                f"{TMDB_API_ROOT}/movie/top_rated?{urlencode({'api_key': self.tmdb_key, 'page': page})}"
            )
            for item in payload.get("results", []):
                entry = canonical_entry_from_tmdb_item(item)
                if entry is None:
                    continue
                key = entry.to_key()
                if key in seen:
                    continue
                seen.add(key)
                entries.append(entry)
                if len(entries) >= 1000:
                    return entries
            if page >= int(payload.get("total_pages") or 0):
                break
        return entries

    def _fetch_genre_entries(self, config: CanonicalListConfig) -> list[CanonicalListEntry]:
        entries: list[CanonicalListEntry] = []
        seen: set[MovieIdentityKey] = set()
        page = 1
        while len(entries) < config.size and page <= 25:
            payload = self.http_get(
                f"{TMDB_API_ROOT}/discover/movie?{urlencode({'api_key': self.tmdb_key, 'page': page, 'sort_by': 'vote_average.desc', 'vote_count.gte': GENRE_VOTE_FLOOR, 'with_genres': ','.join(str(item) for item in config.genre_ids), 'include_adult': 'false', 'include_video': 'false'})}"
            )
            for item in payload.get("results", []):
                entry = canonical_entry_from_tmdb_item(item)
                if entry is None:
                    continue
                key = entry.to_key()
                if key in seen:
                    continue
                seen.add(key)
                entries.append(entry)
                if len(entries) >= config.size:
                    return entries
            if page >= int(payload.get("total_pages") or 0):
                break
            page += 1
        return entries

    def _http_get(self, url: str) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "normal/1"})
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("TMDb response was not a JSON object.")
        return payload


def canonical_entry_from_tmdb_item(item: dict[str, Any]) -> CanonicalListEntry | None:
    title = str(item.get("title") or "").strip()
    release_date = str(item.get("release_date") or "").strip()
    if not title or len(release_date) < 4 or not release_date[:4].isdigit():
        return None
    return CanonicalListEntry(title=title, year=int(release_date[:4]))


def canonical_cache_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    path = base / "normal" / "canonical_lists" / CACHE_SCHEMA_VERSION
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_cache_entries(cache_path: Path, *, now: Callable[[], float]) -> dict[str, Any] | None:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    raw_entries = payload.get("entries")
    fetched_at = payload.get("fetched_at")
    if not isinstance(raw_entries, list) or not isinstance(fetched_at, (int, float)):
        return None
    entries = [
        CanonicalListEntry(title=str(item["title"]), year=int(item["year"]))
        for item in raw_entries
        if isinstance(item, dict) and item.get("title") and item.get("year")
    ]
    return {
        "entries": entries,
        "stale": (now() - float(fetched_at)) > CACHE_TTL_SECONDS,
    }


def write_cache_entries(cache_path: Path, entries: list[CanonicalListEntry], *, fetched_at: float) -> None:
    payload = {
        "fetched_at": fetched_at,
        "fetched_at_iso": datetime.fromtimestamp(fetched_at, UTC).replace(microsecond=0).isoformat(),
        "entries": [asdict(entry) for entry in entries],
    }
    cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
