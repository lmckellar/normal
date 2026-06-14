from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from normal import paths
from normal.audit import AuditEffect, AuditEvent, AuditStore, AuditSubject, make_event_id
from normal.models import WarningItem, utc_now_iso
from normal.movie_identity import MovieIdentityKey, canonical_identity_key, parse_movie_identity
from normal.movie_naming import title_alias_keys
from normal.movie_profile import movie_identity_from_slot, normalize_canonical_list_provider
from normal.movie_scan import iter_video_files


TMDB_API_ROOT = "https://api.themoviedb.org/3"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
IMDB_CANONICAL_CACHE_VERSION = 2
GENRE_VOTE_FLOOR = 5000
TOP_RATED_PAGE_LIMIT = 50
CACHE_SCHEMA_VERSION = "v6"
IMDB_MIN_VOTES = 25000
IMDB_TOP_RATED_MIN_VOTES = 100000
IMDB_GENRE_MIN_VOTES = 50000
IMDB_TOP_RATED_WEIGHT_VOTES = 500000
IMDB_GENRE_WEIGHT_VOTES = 400000
IMDB_DATASET_DIR_ENV = "IMDB_DATASET_DIR"
IMDB_DATASET_REFRESH_SECONDS = 7 * 24 * 60 * 60
IMDB_DATASET_URLS = {
    "title.basics.tsv.gz": "https://datasets.imdbws.com/title.basics.tsv.gz",
    "title.ratings.tsv.gz": "https://datasets.imdbws.com/title.ratings.tsv.gz",
}
IMDB_MANIFEST_NAME = "manifest.json"
CanonicalProviderKind = Literal["tmdb", "imdb"]

_IMDB_DATASET_LOCK = threading.Lock()
_IMDB_DATASET_REFRESH_THREAD: threading.Thread | None = None
_IMDB_DATASET_REFRESH_AUDIT_SOURCES: set[str] = set()
_IMDB_DATASET_REFRESH_AUDIT_STORE: AuditStore | None = None
_IMDB_SESSION_CACHE_LOCK = threading.RLock()
_IMDB_SESSION_RECORDS: dict[str, list[IMDbMovieRecord]] = {}
_IMDB_SESSION_REVERSE_INDEXES: dict[str, dict[tuple[str, int], str | None]] = {}


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
    imdb_id: str | None = None

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
    all_entries: list[dict[str, Any]] = field(default_factory=list)


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
    canonical_status: dict[str, Any] | None = None
    list_summaries: list[CanonicalListSummary] = field(default_factory=list)
    badges: list[CanonicalBadge] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class IMDbMovieRecord:
    imdb_id: str
    title: str
    year: int
    rating: float
    votes: int
    genres: frozenset[str]

    def to_entry(self) -> CanonicalListEntry:
        return CanonicalListEntry(title=self.title, year=self.year, imdb_id=self.imdb_id)


class CanonicalListProvider(Protocol):
    provider_kind: CanonicalProviderKind
    provider_label: str

    def list_entries(self, config: CanonicalListConfig) -> tuple[list[CanonicalListEntry], str]:
        ...


CANONICAL_LISTS: tuple[CanonicalListConfig, ...] = (
    CanonicalListConfig("top_100", "Top 100", 100, "TOP 100", 75.0, "#f94144", "top_rated"),
    CanonicalListConfig("top_250", "Top 250", 250, "TOP 250", 65.0, "#f3722c", "top_rated"),
    CanonicalListConfig("top_500", "Top 500", 500, "TOP 500", 55.0, "#f9844a", "top_rated"),
    CanonicalListConfig("animation", "Animation", 100, "ANIMATION", 60.0, "#f8961e", "genre", (16,)),
    CanonicalListConfig("sci_fi", "Sci-Fi", 100, "SCI-FI", 60.0, "#f9c74f", "genre", (878,)),
    CanonicalListConfig("fantasy", "Fantasy", 100, "FANTASY", 60.0, "#90be6d", "genre", (14,)),
    CanonicalListConfig("action", "Action", 100, "ACTION", 60.0, "#43aa8b", "genre", (28,)),
    CanonicalListConfig("thriller_mystery", "Thriller / Mystery", 100, "THRILLER", 60.0, "#577590", "genre", (53, 9648)),
    CanonicalListConfig("drama_romance", "Drama / Romance", 100, "DRAMA", 60.0, "#7b6d8d", "genre", (18, 10749)),
    CanonicalListConfig("documentary", "Documentary", 100, "DOCUMENTARY", 60.0, "#277da1", "genre", (99,)),
    CanonicalListConfig("comedy", "Comedy", 100, "COMEDY", 60.0, "#4d908e", "genre", (35,)),
)

TMDB_GENRE_TO_IMDB_GENRES: dict[tuple[int, ...], frozenset[str]] = {
    (16,): frozenset({"animation"}),
    (878,): frozenset({"sci-fi"}),
    (14,): frozenset({"fantasy"}),
    (28,): frozenset({"action"}),
    (53, 9648): frozenset({"thriller", "mystery"}),
    (18, 10749): frozenset({"drama", "romance"}),
    (99,): frozenset({"documentary"}),
    (35,): frozenset({"comedy"}),
}


def canonical_provider_label(provider_kind: CanonicalProviderKind) -> str:
    return "IMDb canonical list" if provider_kind == "imdb" else "TMDb canonical list"


def resolve_canonical_provider_kind(standards: dict[str, Any] | None) -> CanonicalProviderKind:
    return normalize_canonical_list_provider((standards or {}).get("canonical_list_provider"))  # type: ignore[return-value]


def build_canonical_provider(
    *,
    standards: dict[str, Any] | None,
    tmdb_key: str | None,
    http_get: Callable[[str], dict[str, Any]] | None = None,
    now: Callable[[], float] = time.time,
    imdb_dataset_dir: Path | None = None,
) -> CanonicalListProvider:
    provider_kind = resolve_canonical_provider_kind(standards)
    if provider_kind == "imdb":
        return IMDbCanonicalProvider(dataset_dir=imdb_dataset_dir, now=now)
    return TMDbCanonicalProvider(tmdb_key=tmdb_key, http_get=http_get, now=now)


def canonical_status_payload(
    *,
    standards: dict[str, Any] | None,
    tmdb_key: str | None,
    now: Callable[[], float] = time.time,
    imdb_dataset_dir: Path | None = None,
) -> dict[str, Any]:
    provider_kind = resolve_canonical_provider_kind(standards)
    if provider_kind == "tmdb":
        available = bool(tmdb_key)
        return {
            "provider": "tmdb",
            "state": "ready" if available else "error",
            "ready": available,
            "refresh_in_progress": False,
            "stale": False,
            "dataset_dir": "",
            "fetched_at": None,
            "age_seconds": None,
            "last_error": "" if available else "TMDb API key is required for Canonical Lists.",
            "status_message": "TMDb provider ready." if available else "TMDb API key is required for Canonical Lists.",
        }
    return imdb_dataset_status(now=now, dataset_dir=imdb_dataset_dir)


def ensure_canonical_provider_ready(
    *,
    standards: dict[str, Any] | None,
    tmdb_key: str | None,
    now: Callable[[], float] = time.time,
    imdb_dataset_dir: Path | None = None,
    force_refresh: bool = False,
    block: bool = False,
    audit_store: AuditStore | None = None,
    audit_source_root: Path | None = None,
) -> dict[str, Any]:
    provider_kind = resolve_canonical_provider_kind(standards)
    if provider_kind == "imdb":
        return ensure_imdb_dataset_ready(
            now=now,
            dataset_dir=imdb_dataset_dir,
            force_refresh=force_refresh,
            block=block,
            audit_store=audit_store,
            audit_source_root=audit_source_root,
        )
    return canonical_status_payload(
        standards=standards,
        tmdb_key=tmdb_key,
        now=now,
        imdb_dataset_dir=imdb_dataset_dir,
    )


def _build_alias_index(inventory: dict[MovieIdentityKey, OwnedMovie]) -> dict[tuple[str, int], MovieIdentityKey | None]:
    index: dict[tuple[str, int], MovieIdentityKey | None] = {}
    for inv_key, owned in inventory.items():
        for alias in title_alias_keys(owned.title):
            tag = (alias, inv_key.year)
            index[tag] = None if tag in index else inv_key
    return index


def _find_inventory_match(
    entry: CanonicalListEntry,
    inventory: dict[MovieIdentityKey, OwnedMovie],
    alias_index: dict[tuple[str, int], MovieIdentityKey | None],
) -> MovieIdentityKey | None:
    primary = entry.to_key()
    if primary in inventory:
        return primary
    for alias in title_alias_keys(entry.title):
        inv_key = alias_index.get((alias, entry.year))
        if inv_key is not None:
            return inv_key
    return None


def build_canonical_lists_report(
    source_root: Path,
    *,
    standards: dict[str, Any] | None,
    tmdb_key: str | None,
    http_get: Callable[[str], dict[str, Any]] | None = None,
    now: Callable[[], float] = time.time,
    should_cancel: Callable[[], bool] | None = None,
    imdb_dataset_dir: Path | None = None,
    movie_paths: list[Path] | None = None,
    movie_items: list[Any] | None = None,
    include_all_entries: bool = True,
    audit_store: AuditStore | None = None,
) -> CanonicalListsReport:
    provider_kind = resolve_canonical_provider_kind(standards)
    status = ensure_canonical_provider_ready(
        standards=standards,
        tmdb_key=tmdb_key,
        now=now,
        imdb_dataset_dir=imdb_dataset_dir,
        block=False,
        audit_store=audit_store,
        audit_source_root=source_root,
    )
    inventory, unparsed_files, duplicate_files = (
        build_movie_inventory_from_items(movie_items)
        if movie_items is not None
        else build_movie_inventory_from_paths(movie_paths)
        if movie_paths is not None
        else build_movie_inventory(source_root, should_cancel=should_cancel)
    )
    if (
        provider_kind == "imdb"
        and not status["ready"]
        and imdb_dataset_dir is None
        and _imdb_dataset_dir_from_env() is None
    ):
        return CanonicalListsReport(
            source_root=str(source_root.resolve()),
            generated_at=utc_now_iso(),
            provider="imdb",
            cache_state="fresh",
            library_summary=CanonicalLibrarySummary(
                owned_movies=len(inventory),
                matched_canonical_titles=0,
                lists_cleared=0,
                unparsed_files=unparsed_files,
                duplicate_files=duplicate_files,
            ),
            canonical_status=status,
        )
    provider = build_canonical_provider(
        standards=standards,
        tmdb_key=tmdb_key,
        http_get=http_get,
        now=now,
        imdb_dataset_dir=imdb_dataset_dir,
    )
    return _build_report_from_inventory(
        source_root=source_root,
        provider=provider,
        inventory=inventory,
        unparsed_files=unparsed_files,
        duplicate_files=duplicate_files,
        canonical_status=status,
        include_all_entries=include_all_entries,
    )


def build_canonical_summary(
    source_root: Path,
    *,
    standards: dict[str, Any] | None,
    tmdb_key: str | None,
    movie_paths: list[Path] | None = None,
    movie_items: list[Any] | None = None,
    now: Callable[[], float] = time.time,
    imdb_dataset_dir: Path | None = None,
    audit_store: AuditStore | None = None,
) -> dict[str, Any]:
    report = build_canonical_lists_report(
        source_root,
        standards=standards,
        tmdb_key=tmdb_key,
        now=now,
        imdb_dataset_dir=imdb_dataset_dir,
        movie_paths=movie_paths,
        movie_items=movie_items,
        include_all_entries=False,
        audit_store=audit_store,
    )
    return {
        "provider": report.provider,
        "cache_state": report.cache_state,
        "canonical_status": report.canonical_status,
        "library_summary": asdict(report.library_summary),
        "badges": [asdict(item) for item in report.badges],
        "list_summaries": [
            {
                "id": item.id,
                "label": item.label,
                "provider_label": item.provider_label,
                "total_count": item.total_count,
                "covered_count": item.covered_count,
                "coverage_percent": item.coverage_percent,
                "missing_count": item.missing_count,
            }
            for item in report.list_summaries
        ],
    }


def _build_report_from_inventory(
    *,
    source_root: Path,
    provider: CanonicalListProvider,
    inventory: dict[MovieIdentityKey, OwnedMovie],
    unparsed_files: int,
    duplicate_files: int,
    canonical_status: dict[str, Any] | None,
    include_all_entries: bool,
) -> CanonicalListsReport:
    cache_states: list[str] = []
    alias_index = _build_alias_index(inventory)
    list_summaries: list[CanonicalListSummary] = []
    badges: list[CanonicalBadge] = []
    matched_keys: set[MovieIdentityKey] = set()
    for config in CANONICAL_LISTS:
        entries, cache_state = provider.list_entries(config)
        cache_states.append(cache_state)
        entry_inv_key: dict[CanonicalListEntry, MovieIdentityKey] = {}
        for entry in entries:
            inv_key = _find_inventory_match(entry, inventory, alias_index)
            if inv_key is not None:
                entry_inv_key[entry] = inv_key
        covered_entries_set = set(entry_inv_key)
        covered_inv_keys = sorted(set(entry_inv_key.values()), key=lambda k: (inventory[k].title, inventory[k].year))
        missing_entries = sorted((e for e in entries if e not in covered_entries_set), key=lambda e: (e.title, e.year))
        matched_keys.update(entry_inv_key.values())
        total_count = len(entries)
        covered_count = len(covered_entries_set)
        coverage_percent = round((covered_count / total_count) * 100, 1) if total_count else 0.0
        list_summaries.append(
            CanonicalListSummary(
                id=config.id,
                label=config.label,
                provider_label=provider.provider_label,
                total_count=total_count,
                covered_count=covered_count,
                coverage_percent=coverage_percent,
                missing_count=len(missing_entries),
                owned_titles=[{"title": inventory[k].title, "year": inventory[k].year} for k in covered_inv_keys[:12]],
                missing_titles=[{"title": e.title, "year": e.year} for e in missing_entries[:12]],
                all_entries=(
                    [
                        {
                            "title": entry.title,
                            "year": entry.year,
                            "imdb_id": entry.imdb_id,
                            "owned": entry in covered_entries_set,
                            "path": inventory[entry_inv_key[entry]].path if entry in covered_entries_set else "",
                        }
                        for entry in entries
                    ]
                    if include_all_entries
                    else []
                ),
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
    return CanonicalListsReport(
        source_root=str(source_root.resolve()),
        generated_at=utc_now_iso(),
        provider=provider.provider_kind,
        cache_state=cache_state,
        library_summary=CanonicalLibrarySummary(
            owned_movies=len(inventory),
            matched_canonical_titles=len(matched_keys),
            lists_cleared=sum(1 for badge in badges if badge.unlocked),
            unparsed_files=unparsed_files,
            duplicate_files=duplicate_files,
        ),
        canonical_status=canonical_status,
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


def build_movie_inventory_from_paths(movie_paths: list[Path]) -> tuple[dict[MovieIdentityKey, OwnedMovie], int, int]:
    inventory: dict[MovieIdentityKey, OwnedMovie] = {}
    unparsed_files = 0
    duplicate_files = 0
    for movie_path in movie_paths:
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


def build_movie_inventory_from_items(movie_items: list[Any]) -> tuple[dict[MovieIdentityKey, OwnedMovie], int, int]:
    inventory: dict[MovieIdentityKey, OwnedMovie] = {}
    unparsed_files = 0
    duplicate_files = 0
    for item in movie_items:
        movie_path = Path(str(item.path))
        parsed = movie_identity_from_slot(getattr(item, "identity", None))
        if parsed is None or parsed.title is None or parsed.year is None:
            unparsed_files += 1
            continue
        key = canonical_identity_key(parsed.title, parsed.year)
        if key in inventory:
            duplicate_files += 1
            continue
        inventory[key] = OwnedMovie(title=parsed.title, year=parsed.year, path=str(movie_path))
    return inventory, unparsed_files, duplicate_files


class TMDbCanonicalProvider:
    provider_kind: CanonicalProviderKind = "tmdb"
    provider_label = canonical_provider_label("tmdb")

    def __init__(
        self,
        *,
        tmdb_key: str | None,
        http_get: Callable[[str], dict[str, Any]] | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        if not tmdb_key:
            raise ValueError("TMDb API key is required for Movies / Canonical Lists. Pass --tmdb-key or set TMDB_KEY.")
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
        cache_path = canonical_cache_dir(self.provider_kind) / cache_name
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


class IMDbCanonicalProvider:
    provider_kind: CanonicalProviderKind = "imdb"
    provider_label = canonical_provider_label("imdb")

    def __init__(
        self,
        *,
        dataset_dir: Path | None = None,
        now: Callable[[], float] = time.time,
    ) -> None:
        resolved_dir = _resolve_imdb_dataset_dir(dataset_dir)
        if resolved_dir is None:
            raise ValueError(
                "IMDb canonical list provider is not ready yet. The managed dataset bootstrap has not completed."
            )
        self.dataset_dir = resolved_dir
        self.now = now
        self._movie_cache: list[IMDbMovieRecord] | None = None

    def list_entries(self, config: CanonicalListConfig) -> tuple[list[CanonicalListEntry], str]:
        namespace = imdb_dataset_cache_namespace(self.dataset_dir)
        cache_key = hashlib.sha1(
            (
                f"imdb:v{IMDB_CANONICAL_CACHE_VERSION}:"
                f"{namespace}:{config.id}:{config.source_kind}:{config.genre_ids}"
            ).encode("utf-8")
        ).hexdigest()[:10]
        return self._fetch_with_cache(
            cache_name=f"{config.id}_{cache_key}.json",
            build_entries=lambda: self._build_entries(config),
        )

    def _fetch_with_cache(
        self,
        *,
        cache_name: str,
        build_entries: Callable[[], list[CanonicalListEntry]],
    ) -> tuple[list[CanonicalListEntry], str]:
        cache_path = canonical_cache_dir(self.provider_kind) / cache_name
        cached = load_cache_entries(cache_path, now=self.now)
        if cached is not None and not cached["stale"]:
            return cached["entries"], "fresh"
        try:
            entries = build_entries()
            write_cache_entries(cache_path, entries, fetched_at=self.now())
            return entries, "live"
        except (OSError, ValueError):
            if cached is not None:
                return cached["entries"], "stale"
            raise

    def _build_entries(self, config: CanonicalListConfig) -> list[CanonicalListEntry]:
        if config.source_kind == "top_rated":
            ranked = self._rank_records(
                self._records_with_desired_floor(
                    self._load_movies(),
                    preferred_min_votes=IMDB_TOP_RATED_MIN_VOTES,
                    desired_size=config.size,
                ),
                weight_votes=IMDB_TOP_RATED_WEIGHT_VOTES,
        )
            return [record.to_entry() for record in ranked[: config.size]]
        target_genres = TMDB_GENRE_TO_IMDB_GENRES.get(config.genre_ids)
        if not target_genres:
            return []
        require_all_genres = len(target_genres) > 1
        genre_records = [
            record
            for record in self._load_movies()
            if (
                target_genres.issubset(record.genres)
                if require_all_genres
                else bool(record.genres.intersection(target_genres))
            )
        ]
        ranked = self._rank_records(
            self._records_with_genre_floor(genre_records, desired_size=config.size),
            weight_votes=IMDB_GENRE_WEIGHT_VOTES,
        )
        return [record.to_entry() for record in ranked[: config.size]]

    def _load_movies(self) -> list[IMDbMovieRecord]:
        if self._movie_cache is not None:
            return self._movie_cache
        namespace = imdb_dataset_session_namespace(self.dataset_dir)
        with _IMDB_SESSION_CACHE_LOCK:
            cached = _IMDB_SESSION_RECORDS.get(namespace)
        if cached is not None:
            self._movie_cache = cached
            return cached
        ratings_path = self.dataset_dir / "title.ratings.tsv.gz"
        basics_path = self.dataset_dir / "title.basics.tsv.gz"
        if not ratings_path.exists() or not basics_path.exists():
            raise ValueError(
                "IMDb canonical list provider could not find title.basics.tsv.gz and title.ratings.tsv.gz under "
                f"{self.dataset_dir}."
            )

        ratings: dict[str, tuple[float, int]] = {}
        with gzip.open(ratings_path, "rt", encoding="utf-8", newline="") as handle:
            next(handle, None)
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue
                tconst, raw_rating, raw_votes = parts[:3]
                try:
                    votes = int(raw_votes)
                    rating = float(raw_rating)
                except ValueError:
                    continue
                if votes < IMDB_MIN_VOTES:
                    continue
                ratings[tconst] = (rating, votes)

        movies: list[IMDbMovieRecord] = []
        with gzip.open(basics_path, "rt", encoding="utf-8", newline="") as handle:
            next(handle, None)
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 9:
                    continue
                tconst, title_type, primary_title, _original_title, is_adult, start_year, _end_year, _runtime, genres = parts[:9]
                rating_data = ratings.get(tconst)
                if rating_data is None or title_type != "movie" or is_adult != "0":
                    continue
                if not primary_title or start_year == r"\N" or not start_year.isdigit():
                    continue
                genre_set = frozenset(
                    token.strip().casefold()
                    for token in genres.split(",")
                    if token and token != r"\N"
                )
                movies.append(
                    IMDbMovieRecord(
                        imdb_id=tconst,
                        title=primary_title,
                        year=int(start_year),
                        rating=rating_data[0],
                        votes=rating_data[1],
                        genres=genre_set,
                    )
                )
        self._movie_cache = movies
        with _IMDB_SESSION_CACHE_LOCK:
            _IMDB_SESSION_RECORDS[namespace] = movies
        return movies

    def _records_with_min_votes(self, records: list[IMDbMovieRecord], minimum_votes: int) -> list[IMDbMovieRecord]:
        return [record for record in records if record.votes >= minimum_votes]

    def _records_with_desired_floor(
        self,
        records: list[IMDbMovieRecord],
        *,
        preferred_min_votes: int,
        desired_size: int,
    ) -> list[IMDbMovieRecord]:
        preferred = self._records_with_min_votes(records, preferred_min_votes)
        if len(preferred) >= desired_size:
            return preferred
        return self._records_with_min_votes(records, IMDB_MIN_VOTES)

    def _records_with_genre_floor(self, records: list[IMDbMovieRecord], *, desired_size: int) -> list[IMDbMovieRecord]:
        return self._records_with_desired_floor(
            records,
            preferred_min_votes=IMDB_GENRE_MIN_VOTES,
            desired_size=desired_size,
        )

    def _rank_records(self, records: list[IMDbMovieRecord], *, weight_votes: int) -> list[IMDbMovieRecord]:
        if not records:
            return []
        pool_mean = sum(record.rating for record in records) / len(records)

        def weighted_score(record: IMDbMovieRecord) -> float:
            votes = float(record.votes)
            prior_votes = float(weight_votes)
            return (votes / (votes + prior_votes)) * record.rating + (prior_votes / (votes + prior_votes)) * pool_mean

        return sorted(
            records,
            key=lambda item: (-weighted_score(item), -item.votes, item.title.casefold(), item.year),
        )


def _imdb_dataset_dir_from_env() -> Path | None:
    raw = os.environ.get(IMDB_DATASET_DIR_ENV)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _managed_data_root() -> Path:
    return paths.data_dir()


def managed_imdb_dataset_dir() -> Path:
    path = _managed_data_root() / "imdb-datasets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def managed_imdb_manifest_path() -> Path:
    return managed_imdb_dataset_dir() / IMDB_MANIFEST_NAME


def _read_managed_imdb_manifest() -> dict[str, Any]:
    path = managed_imdb_manifest_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_managed_imdb_manifest(payload: dict[str, Any]) -> None:
    path = managed_imdb_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _dataset_files_present(dataset_dir: Path | None) -> bool:
    if dataset_dir is None:
        return False
    return all((dataset_dir / name).exists() for name in IMDB_DATASET_URLS)


def _resolve_imdb_dataset_dir(dataset_dir: Path | None = None) -> Path | None:
    if dataset_dir is not None:
        return dataset_dir.expanduser().resolve()
    managed_dir = managed_imdb_dataset_dir()
    if _dataset_files_present(managed_dir):
        return managed_dir
    return _imdb_dataset_dir_from_env()


def imdb_dataset_cache_namespace(dataset_dir: Path) -> str:
    resolved = dataset_dir.expanduser().resolve()
    managed_dir = managed_imdb_dataset_dir()
    if resolved == managed_dir:
        manifest = _read_managed_imdb_manifest()
        stamp = manifest.get("updated_at_iso") or manifest.get("fetched_at_iso") or manifest.get("refresh_started_at_iso")
        if isinstance(stamp, str) and stamp:
            return hashlib.sha1(f"managed:{stamp}".encode("utf-8")).hexdigest()[:12]
    return hashlib.sha1(f"path:{resolved}".encode("utf-8")).hexdigest()[:12]


def imdb_dataset_session_namespace(dataset_dir: Path) -> str:
    cache_namespace = imdb_dataset_cache_namespace(dataset_dir)
    file_fingerprint = []
    for name in sorted(IMDB_DATASET_URLS):
        path = dataset_dir / name
        try:
            stat = path.stat()
        except OSError:
            file_fingerprint.append(f"{name}:missing")
        else:
            file_fingerprint.append(f"{name}:{stat.st_mtime_ns}:{stat.st_size}")
    return hashlib.sha1(f"{cache_namespace}:{'|'.join(file_fingerprint)}".encode("utf-8")).hexdigest()[:16]


def build_imdb_reverse_index(records: list[IMDbMovieRecord]) -> dict[tuple[str, int], str | None]:
    index: dict[tuple[str, int], str | None] = {}
    for record in records:
        for alias in title_alias_keys(record.title):
            key = (alias, record.year)
            if key not in index:
                index[key] = record.imdb_id
            elif index[key] != record.imdb_id:
                index[key] = None
    return index


def resolve_imdb_ids(
    identities: list[ParsedMovieIdentity | None],
    *,
    dataset_dir: Path | None = None,
) -> list[str | None]:
    if not any(identity and identity.title and identity.year for identity in identities):
        return [None] * len(identities)
    resolved_dir = _resolve_imdb_dataset_dir(dataset_dir)
    if resolved_dir is None or not _dataset_files_present(resolved_dir):
        return [None] * len(identities)
    namespace = imdb_dataset_session_namespace(resolved_dir)
    with _IMDB_SESSION_CACHE_LOCK:
        reverse_index = _IMDB_SESSION_REVERSE_INDEXES.get(namespace)
    if reverse_index is None:
        provider = IMDbCanonicalProvider(dataset_dir=resolved_dir)
        reverse_index = build_imdb_reverse_index(provider._load_movies())
        with _IMDB_SESSION_CACHE_LOCK:
            _IMDB_SESSION_REVERSE_INDEXES[namespace] = reverse_index
    resolved: list[str | None] = []
    for identity in identities:
        imdb_id = None
        if identity is not None and identity.title and identity.year:
            for alias in title_alias_keys(identity.title):
                imdb_id = reverse_index.get((alias, identity.year))
                if imdb_id is not None:
                    break
        resolved.append(imdb_id)
    return resolved


def clear_imdb_session_cache() -> None:
    with _IMDB_SESSION_CACHE_LOCK:
        _IMDB_SESSION_RECORDS.clear()
        _IMDB_SESSION_REVERSE_INDEXES.clear()


def imdb_dataset_status(
    *,
    now: Callable[[], float] = time.time,
    dataset_dir: Path | None = None,
) -> dict[str, Any]:
    if dataset_dir is not None:
        resolved = dataset_dir.expanduser().resolve()
        ready = _dataset_files_present(resolved)
        return {
            "provider": "imdb",
            "state": "ready" if ready else "error",
            "ready": ready,
            "refresh_in_progress": False,
            "stale": False,
            "dataset_dir": str(resolved),
            "fetched_at": None,
            "age_seconds": None,
            "last_error": "" if ready else f"IMDb canonical list provider could not find dataset files under {resolved}.",
            "status_message": "IMDb dataset ready." if ready else "IMDb dataset path is missing required files.",
        }
    env_dir = _imdb_dataset_dir_from_env()
    if env_dir is not None and _dataset_files_present(env_dir):
        return {
            "provider": "imdb",
            "state": "ready",
            "ready": True,
            "refresh_in_progress": False,
            "stale": False,
            "dataset_dir": str(env_dir),
            "fetched_at": None,
            "age_seconds": None,
            "last_error": "",
            "status_message": "IMDb dataset ready.",
        }
    manifest = _read_managed_imdb_manifest()
    managed_dir = managed_imdb_dataset_dir()
    ready = _dataset_files_present(managed_dir)
    fetched_at = manifest.get("fetched_at") if isinstance(manifest.get("fetched_at"), (int, float)) else None
    age_seconds = int(max(0, now() - float(fetched_at))) if fetched_at is not None else None
    stale = bool(ready and age_seconds is not None and age_seconds > IMDB_DATASET_REFRESH_SECONDS)
    refresh_in_progress = bool(manifest.get("refresh_in_progress"))
    last_error = str(manifest.get("last_error") or "")
    if refresh_in_progress and ready:
        state = "stale_refreshing" if stale else "bootstrapping"
    elif refresh_in_progress:
        state = "bootstrapping"
    elif ready:
        state = "ready"
    elif last_error:
        state = "error"
    else:
        state = "missing"
    if state == "ready":
        status_message = "IMDb dataset ready."
    elif state == "stale_refreshing":
        status_message = "Refreshing local IMDb dataset in the background."
    elif state == "bootstrapping":
        status_message = "Downloading local IMDb dataset."
    elif state == "error":
        status_message = last_error or "IMDb dataset bootstrap failed."
    else:
        status_message = "IMDb dataset has not been downloaded yet."
    return {
        "provider": "imdb",
        "state": state,
        "ready": ready,
        "refresh_in_progress": refresh_in_progress,
        "stale": stale,
        "dataset_dir": str(managed_dir),
        "fetched_at": manifest.get("fetched_at_iso"),
        "age_seconds": age_seconds,
        "last_error": last_error,
        "status_message": status_message,
    }


def ensure_imdb_dataset_ready(
    *,
    now: Callable[[], float] = time.time,
    dataset_dir: Path | None = None,
    force_refresh: bool = False,
    block: bool = False,
    audit_store: AuditStore | None = None,
    audit_source_root: Path | None = None,
) -> dict[str, Any]:
    newly_registered_sources = _register_imdb_refresh_audit_targets(
        audit_store=audit_store,
        audit_source_root=audit_source_root,
    )
    if dataset_dir is not None:
        return imdb_dataset_status(now=now, dataset_dir=dataset_dir)
    status = imdb_dataset_status(now=now)
    should_refresh = force_refresh or not status["ready"] or bool(status["stale"])
    if status["refresh_in_progress"] and newly_registered_sources:
        refresh_kind = "bootstrap" if status["state"] == "bootstrapping" and not status["ready"] else "refresh"
        _record_imdb_dataset_event(
            _current_imdb_refresh_audit_store(),
            newly_registered_sources,
            action=f"imdb_dataset_{refresh_kind}_started",
            summary=(
                "Started local IMDb dataset bootstrap."
                if refresh_kind == "bootstrap"
                else "Started local IMDb dataset refresh."
            ),
            status="started",
            metadata={"refresh_kind": refresh_kind},
        )
    if should_refresh and not status["refresh_in_progress"]:
        thread = _start_imdb_dataset_refresh(
            now=now,
            force_refresh=force_refresh,
            audit_store=audit_store,
            audit_source_root=audit_source_root,
            refresh_kind="refresh" if (force_refresh or status["ready"]) else "bootstrap",
        )
        if block and thread is not None:
            thread.join()
        status = imdb_dataset_status(now=now)
    elif block and status["refresh_in_progress"]:
        thread = _current_imdb_refresh_thread()
        if thread is not None:
            thread.join()
        status = imdb_dataset_status(now=now)
    return status


def _current_imdb_refresh_thread() -> threading.Thread | None:
    with _IMDB_DATASET_LOCK:
        return _IMDB_DATASET_REFRESH_THREAD


def _current_imdb_refresh_audit_store() -> AuditStore | None:
    with _IMDB_DATASET_LOCK:
        return _IMDB_DATASET_REFRESH_AUDIT_STORE


def _register_imdb_refresh_audit_targets(
    *,
    audit_store: AuditStore | None,
    audit_source_root: Path | None,
) -> list[str]:
    normalized_source = str(audit_source_root.resolve()) if audit_source_root is not None else ""
    with _IMDB_DATASET_LOCK:
        global _IMDB_DATASET_REFRESH_AUDIT_STORE
        if audit_store is not None:
            _IMDB_DATASET_REFRESH_AUDIT_STORE = audit_store
        if not normalized_source:
            return []
        if normalized_source in _IMDB_DATASET_REFRESH_AUDIT_SOURCES:
            return []
        _IMDB_DATASET_REFRESH_AUDIT_SOURCES.add(normalized_source)
        return [normalized_source]


def _start_imdb_dataset_refresh(
    *,
    now: Callable[[], float] = time.time,
    force_refresh: bool = False,
    audit_store: AuditStore | None = None,
    audit_source_root: Path | None = None,
    refresh_kind: str = "bootstrap",
) -> threading.Thread | None:
    del force_refresh
    global _IMDB_DATASET_REFRESH_THREAD
    new_sources = _register_imdb_refresh_audit_targets(
        audit_store=audit_store,
        audit_source_root=audit_source_root,
    )
    with _IMDB_DATASET_LOCK:
        if _IMDB_DATASET_REFRESH_THREAD is not None and _IMDB_DATASET_REFRESH_THREAD.is_alive():
            return _IMDB_DATASET_REFRESH_THREAD
        manifest = _read_managed_imdb_manifest()
        manifest["refresh_in_progress"] = True
        manifest["last_error"] = ""
        manifest["refresh_started_at"] = now()
        manifest["refresh_started_at_iso"] = datetime.fromtimestamp(now(), UTC).replace(microsecond=0).isoformat()
        _write_managed_imdb_manifest(manifest)
        _record_imdb_dataset_event(
            _IMDB_DATASET_REFRESH_AUDIT_STORE,
            new_sources or sorted(_IMDB_DATASET_REFRESH_AUDIT_SOURCES),
            action=f"imdb_dataset_{refresh_kind}_started",
            summary=(
                "Started local IMDb dataset bootstrap."
                if refresh_kind == "bootstrap"
                else "Started local IMDb dataset refresh."
            ),
            status="started",
            metadata={"refresh_kind": refresh_kind},
        )
        thread = threading.Thread(target=_refresh_imdb_dataset_worker, args=(now, refresh_kind), daemon=True)
        _IMDB_DATASET_REFRESH_THREAD = thread
        thread.start()
        return thread


def _refresh_imdb_dataset_worker(now: Callable[[], float], refresh_kind: str) -> None:
    global _IMDB_DATASET_REFRESH_THREAD
    try:
        _download_managed_imdb_dataset(now=now)
        manifest = _read_managed_imdb_manifest()
        fetched_at = now()
        manifest.update(
            {
                "refresh_in_progress": False,
                "last_error": "",
                "fetched_at": fetched_at,
                "fetched_at_iso": datetime.fromtimestamp(fetched_at, UTC).replace(microsecond=0).isoformat(),
            }
        )
        _write_managed_imdb_manifest(manifest)
        _record_imdb_dataset_completion(refresh_kind, "completed", "")
    except Exception as exc:
        manifest = _read_managed_imdb_manifest()
        manifest["refresh_in_progress"] = False
        manifest["last_error"] = str(exc)
        _write_managed_imdb_manifest(manifest)
        _record_imdb_dataset_completion(refresh_kind, "failed", str(exc))
    finally:
        with _IMDB_DATASET_LOCK:
            _IMDB_DATASET_REFRESH_THREAD = None
            _IMDB_DATASET_REFRESH_AUDIT_SOURCES.clear()


def _download_managed_imdb_dataset(*, now: Callable[[], float]) -> None:
    dataset_dir = managed_imdb_dataset_dir()
    temp_dir = Path(tempfile.mkdtemp(prefix="imdb-dataset.", dir=dataset_dir.parent))
    manifest = _read_managed_imdb_manifest()
    files_meta: dict[str, Any] = {}
    try:
        for name, url in IMDB_DATASET_URLS.items():
            request = Request(url, headers={"User-Agent": "normal/1", "Accept": "*/*"})
            target = temp_dir / name
            with urlopen(request, timeout=60) as response, target.open("wb") as handle:
                shutil.copyfileobj(response, handle)
                files_meta[name] = {
                    "url": url,
                    "content_length": int(response.headers.get("Content-Length") or 0),
                    "etag": str(response.headers.get("ETag") or ""),
                    "last_modified": str(response.headers.get("Last-Modified") or ""),
                }
        dataset_dir.mkdir(parents=True, exist_ok=True)
        for name in IMDB_DATASET_URLS:
            (temp_dir / name).replace(dataset_dir / name)
        clear_imdb_session_cache()
        manifest["files"] = files_meta
        manifest["dataset_dir"] = str(dataset_dir)
        manifest["dataset_urls"] = dict(IMDB_DATASET_URLS)
        manifest["managed"] = True
        manifest["updated_at"] = now()
        manifest["updated_at_iso"] = datetime.fromtimestamp(now(), UTC).replace(microsecond=0).isoformat()
        _write_managed_imdb_manifest(manifest)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _record_imdb_dataset_completion(refresh_kind: str, outcome: str, error_message: str) -> None:
    with _IMDB_DATASET_LOCK:
        store = _IMDB_DATASET_REFRESH_AUDIT_STORE
        sources = sorted(_IMDB_DATASET_REFRESH_AUDIT_SOURCES)
    if outcome == "completed":
        summary = "Completed local IMDb dataset bootstrap." if refresh_kind == "bootstrap" else "Completed local IMDb dataset refresh."
    else:
        summary = "Local IMDb dataset bootstrap failed." if refresh_kind == "bootstrap" else "Local IMDb dataset refresh failed."
    metadata: dict[str, Any] = {"refresh_kind": refresh_kind}
    if error_message:
        metadata["error"] = error_message
    _record_imdb_dataset_event(
        store,
        sources,
        action=f"imdb_dataset_{refresh_kind}_{outcome}",
        summary=summary,
        status="applied" if outcome == "completed" else "error",
        metadata=metadata,
    )


def _record_imdb_dataset_event(
    audit_store: AuditStore | None,
    source_roots: list[str],
    *,
    action: str,
    summary: str,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    if audit_store is None or not source_roots:
        return
    recorded_at = utc_now_iso()
    audit_store.append_batch(
        [
            AuditEvent(
                event_id=make_event_id(source_root, "canonical_lists", action, recorded_at),
                recorded_at=recorded_at,
                source_root=source_root,
                workflow="canonical_lists",
                action=action,
                summary=summary,
                subjects=[AuditSubject(kind="source_root", path=source_root)],
                effects=[AuditEffect(kind="dataset_refresh", status=status, path=source_root, message=summary)],
                reversal={"capability": "none"},
                metadata={"provider": "imdb", **(metadata or {})},
            )
            for source_root in source_roots
        ]
    )


def canonical_entry_from_tmdb_item(item: dict[str, Any]) -> CanonicalListEntry | None:
    title = str(item.get("title") or "").strip()
    release_date = str(item.get("release_date") or "").strip()
    if not title or len(release_date) < 4 or not release_date[:4].isdigit():
        return None
    return CanonicalListEntry(title=title, year=int(release_date[:4]))


def canonical_cache_dir(provider_kind: CanonicalProviderKind) -> Path:
    path = paths.data_dir() / "canonical_lists" / CACHE_SCHEMA_VERSION / provider_kind
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
        CanonicalListEntry(
            title=str(item["title"]),
            year=int(item["year"]),
            imdb_id=str(item.get("imdb_id") or "") or None,
        )
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
