from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from normal.audit import AuditStore
from .credentials import CredentialStore
from normal.execution_queue import ExecutionQueueStore
from normal.movie_canonical_lists import CanonicalListsReport
from normal.movie_enriched import EnrichedLibraryReport
from normal.movie_profile import MovieProfileReport
from normal.probe_cache import ProbeCache


class RequestConflictError(RuntimeError):
    pass


@dataclass
class _ActiveScan:
    category: str
    source: Path
    label: str
    mutating: bool = False


class HeavyScanRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: list[_ActiveScan] = []

    @contextmanager
    def claim(self, source: Path, category: str, label: str, *, mutating: bool = False) -> Iterator[None]:
        from normal.source_policy import source_paths_overlap

        resolved = source.resolve()
        entry = _ActiveScan(category=category, source=resolved, label=label, mutating=mutating)
        with self._lock:
            for active in self._active:
                if source_paths_overlap(active.source, resolved):
                    raise RequestConflictError(_conflict_message(label, mutating, active))
            self._active.append(entry)
        try:
            yield
        finally:
            with self._lock:
                self._active.remove(entry)


def _conflict_message(label: str, mutating: bool, active: _ActiveScan) -> str:
    verb = "is blocked while" if mutating or active.mutating else "cannot start while"
    return f"{label} {verb} {active.label} is already running on this library."


@dataclass
class _ProfileCacheEntry:
    report: MovieProfileReport


class MovieProfileCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, _ProfileCacheEntry] = {}

    def get(self, source: Path) -> MovieProfileReport | None:
        key = str(source.resolve())
        with self._lock:
            entry = self._entries.get(key)
            return entry.report if entry is not None else None

    def put(self, source: Path, report: MovieProfileReport) -> None:
        key = str(source.resolve())
        with self._lock:
            self._entries[key] = _ProfileCacheEntry(report=report)

    def invalidate(self, source: Path) -> None:
        key = str(source.resolve())
        with self._lock:
            self._entries.pop(key, None)


@dataclass
class _CanonicalCacheEntry:
    report: CanonicalListsReport


class MovieCanonicalCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, _CanonicalCacheEntry] = {}

    def get(self, source: Path) -> CanonicalListsReport | None:
        key = str(source.resolve())
        with self._lock:
            entry = self._entries.get(key)
            return entry.report if entry is not None else None

    def put(self, source: Path, report: CanonicalListsReport) -> None:
        key = str(source.resolve())
        with self._lock:
            self._entries[key] = _CanonicalCacheEntry(report=report)

    def invalidate(self, source: Path) -> None:
        key = str(source.resolve())
        with self._lock:
            self._entries.pop(key, None)


@dataclass
class _EnrichedCacheEntry:
    report: EnrichedLibraryReport


class MovieEnrichedCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, _EnrichedCacheEntry] = {}

    def get(self, source: Path, *, lane: str = "movie") -> EnrichedLibraryReport | None:
        key = self._key(source, lane)
        with self._lock:
            entry = self._entries.get(key)
            return entry.report if entry is not None else None

    def put(self, source: Path, report: EnrichedLibraryReport, *, lane: str = "movie") -> None:
        key = self._key(source, lane)
        with self._lock:
            self._entries[key] = _EnrichedCacheEntry(report=report)

    def invalidate(self, source: Path, *, lane: str | None = None) -> None:
        source_key = str(source.resolve())
        with self._lock:
            if lane is not None:
                self._entries.pop(self._key(source, lane), None)
                return
            for key in [key for key in self._entries if key.startswith(source_key + "\0")]:
                self._entries.pop(key, None)

    @staticmethod
    def _key(source: Path, lane: str) -> str:
        return f"{source.resolve()}\0{lane}"


ACTIVITY_TRACKER = None
HEAVY_SCAN_REGISTRY = HeavyScanRegistry()
MOVIE_ENRICHED_CACHE = MovieEnrichedCache()
MOVIE_PROFILE_CACHE = MovieProfileCache()
MOVIE_CANONICAL_CACHE = MovieCanonicalCache()
PROBE_CACHE = ProbeCache()
# Persist any trailing batched probe writes when the long-lived server exits.
atexit.register(PROBE_CACHE.flush)
AUDIT_STORE = AuditStore()
CREDENTIAL_STORE = CredentialStore()
EXECUTION_QUEUE_STORE = ExecutionQueueStore()
