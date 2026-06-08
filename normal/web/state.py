from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from normal.audit import AuditStore
from .credentials import CredentialStore
from normal.movie_canonical_lists import CanonicalListsReport
from normal.movie_profile import MovieProfileReport
from normal.probe_cache import ProbeCache


class RequestConflictError(RuntimeError):
    pass


class HeavyScanRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[tuple[str, str]] = set()

    @contextmanager
    def claim(self, source: Path, category: str, label: str) -> Iterator[None]:
        key = (category, str(source.resolve()))
        with self._lock:
            if key in self._active:
                raise RequestConflictError(f"{label} is already running for {key[1]}")
            self._active.add(key)
        try:
            yield
        finally:
            with self._lock:
                self._active.discard(key)


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


ACTIVITY_TRACKER = None
HEAVY_SCAN_REGISTRY = HeavyScanRegistry()
MOVIE_PROFILE_CACHE = MovieProfileCache()
MOVIE_CANONICAL_CACHE = MovieCanonicalCache()
PROBE_CACHE = ProbeCache()
AUDIT_STORE = AuditStore()
CREDENTIAL_STORE = CredentialStore()
