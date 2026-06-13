from __future__ import annotations

from dataclasses import asdict
import json
import threading
import time
from pathlib import Path
from typing import Any

from normal.movie_scan import media_facts_from_dict
from normal.quality_review import MediaFacts


class ProbeCache:
    _PATH = Path.home() / ".local" / "share" / "normal" / "probe-cache.json"
    _VERSION = 5
    # Writes are batched: a full-tree scan calls put() once per file, and each
    # _save rewrites the whole entries dict, so per-put persistence was O(n^2)
    # rewrites across thousands of files. Coalesce into one write per FLUSH_EVERY
    # puts, with a time bound so a slow trickle still lands, plus an atexit flush.
    # The cache is derived/rebuildable, so the cost of a lost trailing batch is a
    # re-probe, not data loss.
    _FLUSH_EVERY = 64
    _FLUSH_INTERVAL_S = 5.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._dirty = 0
        self._last_flush = time.monotonic()

    def get(self, path: Path) -> MediaFacts | None:
        key = self._key(path)
        if key is None:
            return None
        with self._lock:
            self._ensure_loaded()
            raw = self._entries.get(key)
        if raw is None:
            return None
        try:
            return media_facts_from_dict(raw)
        except Exception:
            return None

    def put(self, path: Path, facts: MediaFacts) -> None:
        key = self._key(path)
        if key is None:
            return
        with self._lock:
            self._ensure_loaded()
            self._entries[key] = asdict(facts)
            self._dirty += 1
            self._maybe_flush_locked()

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                self._save()

    def has_entries(self) -> bool:
        with self._lock:
            self._ensure_loaded()
            return bool(self._entries)

    def _maybe_flush_locked(self) -> None:
        if self._dirty >= self._FLUSH_EVERY or (
            time.monotonic() - self._last_flush >= self._FLUSH_INTERVAL_S
        ):
            self._save()

    def _key(self, path: Path) -> str | None:
        try:
            st = path.stat()
            return f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}"
        except OSError:
            return None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        cache_path = self._PATH
        if not cache_path.exists():
            return
        try:
            payload = json.loads(cache_path.read_text())
            if payload.get("version") == self._VERSION:
                self._entries = payload.get("entries", {})
        except Exception:
            self._entries = {}

    def _save(self) -> None:
        cache_path = self._PATH
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": self._VERSION, "entries": self._entries}))
        tmp.replace(cache_path)
        self._dirty = 0
        self._last_flush = time.monotonic()
