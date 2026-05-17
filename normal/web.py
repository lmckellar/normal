from __future__ import annotations

import json
import os
import select
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator

from PIL import Image

from normal.movie_audio_fix import fix_english_audio_defaults
from normal.movie_canonical_lists import build_canonical_lists_report
from normal.movie_inspect import inspect_movie_file
from normal.movie_junk import (
    detect_movie_junk_document_reasons,
    detect_movie_junk_reasons,
    scan_movie_cleanup,
)
from normal.movie_omdb import lookup_omdb_ratings
from normal.movie_plan import DEFAULT_MOVIE_NAMING_STYLE, MOVIE_NAMING_STYLES, build_movie_plan
from normal.movie_scan import MovieScanProgress
from normal.movie_profile import (
    build_histogram_payload,
    build_histogram_payload_from_items,
    build_movie_profile_definitions,
    build_movie_profile_item,
    build_replacement_candidate_definition,
    load_movie_standards,
    movie_standards_revision,
    MovieStandardsConflictError,
    scan_movie_profiles,
    update_movie_profile_definition,
)
from normal.movie_subtitle_fix import fix_movie_subtitle_defaults
from normal.movie_subtitle_history import (
    dismiss_items as dismiss_subtitle_history_items,
    history_for_source as subtitle_history_for_source,
    upsert_items as upsert_subtitle_history_items,
)
from normal.movie_replacement_queue import (
    add_profile_items_to_queue,
    clear_pending_queue_items,
    delete_replacement_queue_media,
    dismiss_replacement_queue_items,
    queue_for_source,
    reconcile_replacement_queue,
)
from normal.movie_scan import discover_video_files, media_facts_from_dict, probe_media_facts, scan_movie_library
from normal.probe_cache import ProbeCache
from normal.output import write_movie_register_xlsx
from normal.models import ProposedChange, utc_now_iso
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts


def build_movie_normalize_results(source_root: Path, movie_files: list[Path], plan_changes: list[ProposedChange]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for movie_path in sorted(movie_files, key=lambda path: str(path.relative_to(source_root)).casefold()):
        relative_path = movie_path.relative_to(source_root)
        linked_changes = movie_normalize_changes_for_file(relative_path, movie_path, plan_changes)
        projected_path = projected_movie_normalize_path(relative_path, movie_path, linked_changes)
        confidence = "unchanged"
        if linked_changes:
            confidence = "review" if any(change.confidence == "review" for change in linked_changes) else "safe"
        results.append(
            {
                "result_id": f"movie:{relative_path}",
                "kind": "movie_file",
                "path": str(movie_path),
                "current_value": str(relative_path),
                "proposed_value": str(projected_path),
                "confidence": confidence,
                "actionable": bool(linked_changes),
                "change_ids": [change.item_id for change in linked_changes],
            }
        )
    return results


def movie_normalize_changes_for_file(
    relative_path: Path,
    movie_path: Path,
    plan_changes: list[ProposedChange],
) -> list[ProposedChange]:
    linked: list[ProposedChange] = []
    relative_text = str(relative_path)
    relative_parent = str(relative_path.parent) if str(relative_path.parent) != "." else ""
    for change in plan_changes:
        if change.change_type in {"file_rename", "file_move"} and change.path and Path(change.path).resolve() == movie_path.resolve():
            linked.append(change)
            continue
        if change.change_type == "folder_rename":
            current = change.current_value or ""
            if relative_parent == current or relative_parent.startswith(current + "/") or relative_text == current:
                linked.append(change)
    return linked


def projected_movie_normalize_path(relative_path: Path, movie_path: Path, changes: list[ProposedChange]) -> Path:
    for change in changes:
        if change.change_type == "file_move" and change.path and Path(change.path).resolve() == movie_path.resolve():
            return Path(change.proposed_value)

    proposed_dir = relative_path.parent
    if str(proposed_dir) == ".":
        proposed_dir = Path("")
    for change in sorted((change for change in changes if change.change_type == "folder_rename"), key=lambda item: len(item.current_value), reverse=True):
        current = Path(change.current_value)
        proposed = Path(change.proposed_value)
        try:
            suffix = proposed_dir.relative_to(current)
        except ValueError:
            continue
        proposed_dir = proposed / suffix

    proposed_filename = relative_path.name
    for change in changes:
        if change.change_type == "file_rename" and change.path and Path(change.path).resolve() == movie_path.resolve():
            proposed_filename = change.proposed_value
            break
    return proposed_dir / proposed_filename


@dataclass
class ActivityItem:
    id: int
    source: str
    label: str
    kind: str
    started_at: float
    current_path: str | None = None
    status_text: str | None = None
    processed: int | None = None
    total: int | None = None
    progress_fraction: float | None = None
    completed_seconds: float | None = None
    total_seconds: float | None = None
    eta_seconds: float | None = None
    output_size_bytes: int | None = None
    output_path: str | None = None
    speed: str | None = None


class ActivityTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 1
        self._items: dict[int, ActivityItem] = {}

    @contextmanager
    def track(
        self,
        source: Path,
        label: str,
        *,
        kind: str = "job",
        current_path: Path | None = None,
    ) -> Iterator[int]:
        item_id = self.start(source, label, kind=kind, current_path=current_path)
        try:
            yield item_id
        finally:
            self.finish(item_id)

    def start(self, source: Path, label: str, *, kind: str, current_path: Path | None = None) -> int:
        with self._lock:
            item_id = self._next_id
            self._next_id += 1
            self._items[item_id] = ActivityItem(
                id=item_id,
                source=str(source.resolve()),
                label=label,
                kind=kind,
                started_at=time.time(),
                current_path=str(current_path.resolve()) if current_path else None,
            )
            return item_id

    def finish(self, item_id: int) -> None:
        with self._lock:
            self._items.pop(item_id, None)

    def update_current_path(self, item_id: int, current_path: Path | None) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if item is not None:
                item.current_path = str(current_path.resolve()) if current_path else None

    def update(self, item_id: int, **changes: Any) -> None:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return
            for key, value in changes.items():
                if key == "current_path" and value is not None:
                    setattr(item, key, str(Path(value).resolve()))
                elif key == "output_path" and value is not None:
                    setattr(item, key, str(Path(value).resolve()))
                elif hasattr(item, key):
                    setattr(item, key, value)

    def snapshot(self, source: Path) -> list[dict[str, Any]]:
        resolved_source = source.resolve()
        now = time.time()
        with self._lock:
            items = list(self._items.values())
        return [
            {
                "id": item.id,
                "source": item.source,
                "label": item.label,
                "kind": item.kind,
                "current_path": item.current_path,
                "elapsed_seconds": round(now - item.started_at, 1),
                "status_text": item.status_text,
                "processed": item.processed,
                "total": item.total,
                "progress_fraction": item.progress_fraction,
                "completed_seconds": item.completed_seconds,
                "total_seconds": item.total_seconds,
                "eta_seconds": item.eta_seconds,
                "output_size_bytes": item.output_size_bytes,
                "output_path": item.output_path,
                "speed": item.speed,
            }
            for item in items
            if source_paths_overlap(Path(item.source), resolved_source)
            or (item.current_path is not None and path_is_under(Path(item.current_path), resolved_source))
        ]


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



ACTIVITY_TRACKER = ActivityTracker()
HEAVY_SCAN_REGISTRY = HeavyScanRegistry()
MOVIE_PROFILE_CACHE = MovieProfileCache()
PROBE_CACHE = ProbeCache()


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>normal workbench</title>
  <style>
    :root {
      --bg: #f4efe5;
      --panel: #fffaf1;
      --panel-2: #f7efe2;
      --ink: #1f1d1a;
      --muted: #6c675f;
      --line: #d7cbb8;
      --accent: #0f5c4d;
      --accent-2: #c86a2d;
      --movies: #0f5c4d;
      --danger: #8a3341;
      --warn: #8a5b00;
      --shadow: rgba(31, 29, 26, 0.08);
      --font-body: Georgia, "Iowan Old Style", "Palatino Linotype", serif;
      --radius: 22px;
      --input-bg: #fffdf8;
      --btn-secondary: #efe3d4;
      --btn-nav: #fbf5ea;
      --th-bg: #f7f0e3;
      --surface: rgba(255,255,255,0.55);
      --bar-track: #ebdfce;
      --accent-glow: rgba(15,92,77,0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font-body);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(200,106,45,0.12), transparent 28%),
        linear-gradient(180deg, #f7f3eb 0%, #efe6d8 100%);
      min-height: 100vh;
    }
    .shell {
      max-width: 3000px;
      margin: 0 auto;
      padding: 24px;
    }
    .card {
      background: color-mix(in srgb, var(--panel) 92%, white);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: 0 18px 48px var(--shadow);
    }
    .masthead {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(280px, 0.65fr);
      gap: 18px;
      margin-bottom: 18px;
    }
    .mast-main { padding: 24px; }
    .eyebrow {
      text-transform: uppercase;
      letter-spacing: 0.13em;
      font-size: 12px;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 6px;
    }
    h1 {
      margin: 0 0 10px;
      font-size: clamp(32px, 5vw, 58px);
      line-height: 0.94;
    }
    .lede {
      margin: 0;
      color: var(--muted);
      font-size: 18px;
      line-height: 1.45;
      max-width: 54rem;
    }
    .controls {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      margin-top: 22px;
    }
    input[type="text"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px 16px;
      font-size: 15px;
      background: var(--input-bg);
      color: var(--ink);
      font-family: ui-monospace, Menlo, Consolas, monospace;
    }
    button {
      border: 0;
      border-radius: 14px;
      padding: 13px 16px;
      font-size: 14px;
      font-weight: 700;
      color: var(--ink);
      cursor: pointer;
      transition: filter 120ms ease, opacity 120ms ease;
    }
    button:hover { filter: brightness(0.92); }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .primary { background: var(--accent); color: white; }
    .secondary { background: var(--btn-secondary); color: var(--ink); }
    .warn { background: var(--warn); color: white; }
    .caution { background: var(--accent-2); color: white; }
    .danger { background: var(--danger); color: white; }
    .page-nav {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }
    .page-button, .filter-button {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--btn-nav);
      padding: 8px 12px;
      font-size: 13px;
      color: var(--ink);
      cursor: pointer;
      transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
    }
    .sel-toggle { padding: 8px 12px; font-size: 13px; }
    .page-button.active, .filter-button.active {
      color: white;
      border-color: transparent;
    }
    .page-button.active, .filter-button.active { background: var(--accent); }
    .mast-side {
      padding: 20px;
      display: grid;
      gap: 10px;
      align-content: start;
    }
    .library-switcher {
      display: grid;
      gap: 8px;
    }
    .library-subhead {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-top: 4px;
    }
    .library-root {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,0.48);
    }
    .library-root.current {
      border-color: color-mix(in srgb, var(--accent) 70%, var(--line));
      background: color-mix(in srgb, var(--accent) 8%, rgba(255,255,255,0.62));
    }
    .library-root-title {
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      margin-bottom: 3px;
    }
    .library-root strong {
      font-size: 13px;
    }
    .library-current-chip {
      border-radius: 999px;
      background: var(--accent);
      color: white;
      padding: 2px 7px;
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .library-root-path {
      color: var(--muted);
      font-family: ui-monospace, Menlo, Consolas, monospace;
      font-size: 11px;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .library-root button {
      padding: 8px 10px;
      border-radius: 10px;
      font-size: 12px;
    }
    .library-root-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.55);
    }
    .metric strong {
      display: block;
      font-size: 28px;
      margin-bottom: 4px;
    }
    .metric span {
      color: var(--muted);
      font-size: 13px;
    }
    .status-bar { margin-top: 14px; }
    .status-row { display: flex; align-items: center; gap: 7px; }
    .status-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--line);
      flex-shrink: 0;
      transition: background 200ms;
    }
    .status-dot.running { background: var(--accent); animation: dot-pulse 1.1s ease-in-out infinite; }
    .status-dot.error { background: var(--danger); }
    @keyframes dot-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
    .status {
      color: var(--muted);
      font-size: 13px;
      flex: 1;
      min-height: 18px;
    }
    .status-timer {
      color: var(--muted);
      font-size: 12px;
      font-family: ui-monospace, Menlo, Consolas, monospace;
      letter-spacing: 0.03em;
    }
    .status-track {
      height: 2px;
      background: var(--line);
      border-radius: 2px;
      margin-top: 7px;
      overflow: hidden;
      position: relative;
    }
    .status-fill {
      position: absolute;
      top: 0; left: -55%; height: 100%; width: 55%;
      background: var(--accent);
      border-radius: 2px;
      opacity: 0;
    }
    .status-fill.running { opacity: 1; animation: status-sweep 1.7s cubic-bezier(0.4,0,0.6,1) infinite; }
    @keyframes status-sweep { 0% { left: -55%; } 100% { left: 110%; } }
    .activity-bar {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      gap: 9px;
      align-items: start;
      margin-top: 12px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,0.5);
    }
    .activity-bar.active {
      border-color: color-mix(in srgb, var(--accent) 55%, var(--line));
      background: color-mix(in srgb, var(--accent) 7%, rgba(255,255,255,0.62));
    }
    .activity-bar.external {
      border-color: color-mix(in srgb, var(--warn) 70%, var(--line));
      background: color-mix(in srgb, var(--warn) 9%, rgba(255,255,255,0.62));
    }
    .activity-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--line);
      margin-top: 5px;
    }
    .activity-bar.active .activity-dot { background: var(--accent); animation: dot-pulse 1.1s ease-in-out infinite; }
    .activity-bar.external .activity-dot { background: var(--warn); animation: dot-pulse 1.1s ease-in-out infinite; }
    .activity-title {
      font-size: 13px;
      font-weight: 700;
      line-height: 1.25;
    }
    .activity-detail {
      margin-top: 3px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
      gap: 18px;
    }
    .panel { padding: 18px; min-width: 0; }
    .panel h2 {
      margin: 0 0 8px;
      font-size: 23px;
    }
    .tagline {
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 12px;
    }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.6);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 980px;
    }
    th, td {
      text-align: left;
      padding: 12px 14px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
      vertical-align: top;
      font-size: 13px;
    }
    th {
      position: sticky;
      top: 0;
      background: var(--th-bg);
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 12px;
    }
    tr:hover td { background: color-mix(in srgb, var(--accent) 5%, transparent); }
    th.sortable-th { cursor: pointer; user-select: none; }
    th.sortable-th:hover { color: var(--ink); }
    .sort-ind { margin-left: 3px; opacity: 0.35; }
    .sort-ind.on { opacity: 1; }
    .junk-table {
      min-width: 0;
      width: 100%;
      table-layout: fixed;
    }
    .junk-table th:nth-child(1), .junk-table td:nth-child(1) { width: 42px; text-align: center; }
    .junk-table th:nth-child(2), .junk-table td:nth-child(2) { width: 30%; }
    .junk-table th:nth-child(4), .junk-table td:nth-child(4) { width: 120px; white-space: nowrap; }
    .junk-table td:nth-child(3) .mono { word-break: normal; overflow-wrap: anywhere; }
    .junk-table td:nth-child(2) { word-break: break-word; overflow-wrap: anywhere; }
    .subtitle-table {
      min-width: 0;
      width: 100%;
      table-layout: fixed;
    }
    .subtitle-table th:nth-child(1), .subtitle-table td:nth-child(1) { width: 28px; text-align: center; }
    .subtitle-table td { word-break: break-word; overflow-wrap: anywhere; }
    .junk-actions {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }
    .triage-action-spacer {
      flex: 1 1 auto;
      min-width: 16px;
    }
    .triage-action-note {
      flex: 0 1 auto;
    }
    @media (max-width: 900px) {
      .junk-actions.audio-packaging-actions {
        flex-wrap: wrap;
      }
      .junk-actions.audio-packaging-actions .triage-action-spacer {
        display: none;
      }
      .junk-actions.audio-packaging-actions .danger {
        margin-left: 0;
      }
      .junk-actions.audio-packaging-actions .triage-action-note {
        flex-basis: 100%;
      }
    }
    .chip {
      display: inline-flex;
      align-items: center;
      padding: 5px 9px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      margin: 2px 6px 2px 0;
      border: 1px solid transparent;
    }
    .chip.safe { background: rgba(15,92,77,0.12); color: var(--accent); border-color: rgba(15,92,77,0.2); }
    .chip.high { background: rgba(138,51,65,0.12); color: var(--danger); border-color: rgba(138,51,65,0.22); }
    .chip.review { background: rgba(200,106,45,0.12); color: var(--accent-2); border-color: rgba(200,106,45,0.2); }
    .chip.unchanged { background: color-mix(in srgb, var(--muted) 12%, transparent); color: var(--muted); border-color: color-mix(in srgb, var(--muted) 24%, transparent); }
    .chip.playback { background: rgba(15,92,77,0.12); color: var(--accent); border-color: rgba(15,92,77,0.2); }
    .chip.indexing { background: rgba(138,91,0,0.12); color: var(--warn); border-color: rgba(138,91,0,0.2); }
    .chip.meta { background: rgba(45,94,168,0.12); color: var(--muted); border-color: rgba(45,94,168,0.2); }
    .queue-inline-remove {
      border: 0;
      background: transparent;
      color: var(--danger);
      padding: 0 0 0 8px;
      font-size: 16px;
      font-weight: 700;
      line-height: 1;
      vertical-align: middle;
    }
    .mono {
      font-family: ui-monospace, Menlo, Consolas, monospace;
      word-break: break-all;
    }
    .details {
      min-height: 560px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .finding, .empty {
      border-radius: 18px;
      padding: 16px;
    }
    .finding {
      border: 1px solid var(--line);
      background: var(--surface);
    }
    .empty {
      border: 1px dashed var(--line);
      background: var(--surface);
      color: var(--muted);
    }
    .finding h3 {
      margin: 0 0 8px;
      font-size: 17px;
    }
    .finding p {
      margin: 6px 0;
      font-size: 14px;
      line-height: 1.45;
    }
    .queue-list {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      max-height: 340px;
      overflow: auto;
    }
    .queue-list-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      padding: 9px 10px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
      align-items: start;
    }
    .queue-list-row:last-child { border-bottom: 0; }
    .queue-list-title {
      font-size: 13px;
      font-weight: 700;
      line-height: 1.25;
      overflow-wrap: anywhere;
    }
    .queue-list-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 3px;
      overflow-wrap: anywhere;
    }
    .bars {
      display: grid;
      gap: 8px;
    }
    .bar-row {
      display: grid;
      grid-template-columns: 135px 1fr auto;
      gap: 10px;
      align-items: center;
      font-size: 13px;
    }
    .bar {
      height: 10px;
      border-radius: 999px;
      overflow: hidden;
      background: var(--bar-track);
    }
    .bar > span {
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
    }
    .placeholder-grid {
      display: grid;
      gap: 12px;
      margin-top: 12px;
    }
    .placeholder {
      padding: 16px;
      border-radius: 18px;
      border: 1px dashed var(--line);
      background: var(--surface);
    }
    .dash-stats {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }
    .dash-stats .metric {
      flex: 1 1 120px;
    }
    .dash-section-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      font-weight: 700;
      margin: 16px 0 8px;
    }
    .dash-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      margin: 0 0 16px;
    }
    .profile-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 12px;
    }
    .profile-card {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--surface);
      padding: 16px;
    }
    .profile-card-head {
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 10px;
    }
    .profile-card-head .secondary {
      padding: 8px 10px;
      border-radius: 10px;
      font-size: 12px;
      flex-shrink: 0;
    }
    .profile-card-group {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
    }
    .profile-card-name {
      font-size: 14px;
      font-weight: 700;
      margin-bottom: 8px;
      line-height: 1.3;
    }
    .profile-card-count {
      font-size: 32px;
      font-weight: 700;
      line-height: 1;
      margin-bottom: 4px;
    }
    .profile-card-pct {
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 10px;
    }
    .profile-card-band {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      margin: -4px 0 10px;
    }
    .profile-card-definition {
      color: var(--ink);
      font-size: 12px;
      line-height: 1.4;
      margin: 0 0 12px;
    }
    .profile-card-editor {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
      display: grid;
      gap: 10px;
    }
    .profile-card-editor-row {
      display: grid;
      gap: 5px;
    }
    .profile-card-editor-row label {
      font-size: 12px;
      font-weight: 700;
      color: var(--ink);
    }
    .profile-card-editor-row input[type="number"],
    .profile-card-editor-row input[type="text"],
    .profile-card-editor-row select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 13px;
      background: var(--input-bg);
      color: var(--ink);
      font-family: inherit;
    }
    .profile-card-checklist {
      display: grid;
      gap: 6px;
    }
    .profile-card-checklist label,
    .profile-card-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      font-weight: 400;
      color: var(--ink);
    }
    .profile-card-editor-actions {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .profile-card-bar {
      height: 6px;
      border-radius: 999px;
      overflow: hidden;
      background: var(--bar-track);
    }
    .profile-card-bar > span {
      display: block;
      height: 100%;
      background: linear-gradient(90deg, var(--accent), var(--accent-2));
    }
    .coverage-card-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      margin-top: 10px;
      min-height: 32px;
    }
    .badge-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
      gap: 10px;
    }
    .badge-tile {
      border-radius: 18px;
      padding: 14px 12px;
      color: #fff;
      min-height: 98px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      box-shadow: 0 10px 20px rgba(31, 29, 26, 0.12);
    }
    .badge-tile.locked {
      background: #b8aa96 !important;
      box-shadow: none;
      color: rgba(255, 255, 255, 0.92);
    }
    .badge-kicker {
      font-size: 10px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      opacity: 0.92;
    }
    .badge-name {
      font-size: 18px;
      font-weight: 700;
      line-height: 1.1;
    }
    .badge-meta {
      font-size: 11px;
      opacity: 0.95;
    }
    .dash-res-bars {
      display: grid;
      gap: 7px;
    }
    .dash-risk-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 4px;
    }
    .artist-toolbar {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }
    .switcher-list {
      display: grid;
      gap: 10px;
    }
    .switcher-option {
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--surface);
      padding: 14px 15px;
      color: inherit;
      font-family: inherit;
    }
    .switcher-option.active {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 55%, transparent);
      background: color-mix(in srgb, var(--accent) 6%, var(--surface));
    }
    .switcher-option-title {
      font-size: 14px;
      font-weight: 700;
      line-height: 1.3;
    }
    .switcher-option-meta {
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
    }
    .switcher-option-state {
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
    }
    .artist-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(142px, 1fr));
      gap: 14px;
    }
    .candidate-section {
      margin-top: 16px;
    }
    .candidate-section h4 {
      margin: 0 0 8px;
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0;
    }
    .candidate-section-heading {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }
    .candidate-section-heading h4 {
      margin: 0;
    }
    .subtle {
      color: var(--muted);
      font-size: 13px;
    }
    @media (max-width: 1100px) {
      .masthead, .layout { grid-template-columns: 1fr; }
    }
    .theme-picker {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line);
      flex-wrap: wrap;
    }
    .theme-picker-label {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--muted);
      white-space: nowrap;
    }
    .theme-btn {
      background: none;
      border: 1px solid var(--line);
      border-radius: calc(var(--radius) * 0.4);
      padding: 4px 10px;
      font-size: 12px;
      color: var(--muted);
      cursor: pointer;
      margin: 2px;
      font-family: var(--font-body);
    }
    .theme-btn.active {
      border-color: var(--accent);
      color: var(--accent);
      background: color-mix(in srgb, var(--accent) 8%, transparent);
    }
    .theme-btn:hover:not(.active) {
      border-color: var(--muted);
      color: var(--ink);
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="masthead">
      <div class="card mast-main">
        <div class="eyebrow">normal workbench</div>
        <h1 id="heroTitle">Movies</h1>
        <p class="lede" id="heroLede">Local workbench for diagnosing and cleaning movie libraries.</p>
        <div class="controls">
          <input id="sourcePath" type="text" placeholder="/path/to/library">
          <button id="runButton" class="primary">Run</button>
        </div>
        <div class="page-nav" id="pageNav"></div>
        <div class="status-bar">
          <div class="status-row">
            <span class="status-dot" id="statusDot"></span>
            <span class="status" id="statusText">Idle.</span>
            <span class="status-timer" id="statusTimer"></span>
          </div>
          <div class="status-track"><div class="status-fill" id="statusFill"></div></div>
        </div>
        <div class="activity-bar" id="activityBar">
          <span class="activity-dot"></span>
          <div>
            <div class="activity-title" id="activityTitle">Drive activity: idle</div>
            <div class="activity-detail" id="activityDetail">No normal job or media probe detected for the selected source.</div>
          </div>
        </div>
      </div>
      <div class="card mast-side">
        <div class="theme-picker">
          <div class="theme-picker-label">Theme</div>
          <div id="themeBtns"></div>
        </div>
        <div class="eyebrow">Library Switcher</div>
        <div class="library-switcher" id="libraryRoots"></div>
      </div>
    </section>

    <section class="layout">
      <div class="card panel">
        <h2 id="mainTitle">Library</h2>
        <div class="tagline" id="mainTagline">Choose a lane and run a scan.</div>
        <div id="filterBar" class="page-nav"></div>
        <div id="mainContent"></div>
      </div>
      <div class="card panel">
        <h2>Detail</h2>
        <div class="details" id="detailPanel">
          <div class="empty">For movies, this pane stays attached to the current directory's Replacement Queue.</div>
        </div>
      </div>
    </section>
  </div>
  <script>
    const state = {
      lane: 'movies',
      page: 'library',
      filter: 'all',
      qualitySort: { col: null, dir: 'asc' },
      fixDefaultsTab: 'audio',
      movieAudioFixBusy: false,
      movieSubtitleFixBusy: false,
      subtitleHistory: null,
      subtitleHistoryFilter: 'all',
      movieStandardsEditorLabel: '',
      movieStandardsSaveBusy: false,
      movieProfileInspectorLabel: '',
      movieProfileInspectorType: '',
      movieProfileInspectorSort: { col: 'title', dir: 'asc' },
      movieCanonicalInspectorId: '',
      movieCanonicalInspectorSort: { col: 'rank', dir: 'asc' },
      movieStandardsPendingDraft: null,
      replacementHistoryFilter: 'deleted',
      replacementHistorySort: { col: null, dir: 'asc' },
      omdbRatings: new Map(),
      omdbStatus: '',
      selectedJunkPaths: new Set(),
      junkDeleteHistory: [],
      selectedReplacementPaths: new Set(),
      selectedChangeIds: new Set(),
      selectedNormalizeResultIds: new Set(),
      movieNamingStyle: 'concise',
      results: {
        movies: { profile: null, canonical: null, normalize: null, apply: null, junk: null, replacementQueue: null, replacementQueueSource: '' }
      }
    };

    const CONFIG = {
      movies: {
        title: 'Movies',
        lede: 'Assess, fix, and standardize your movie and TV library. Diagnostics here focus on quality, compatibility, and repairable playback or visibility issues.',
        sourceLabel: '/path/to/movie or TV library',
        pages: [
          { id: 'library', label: 'Dashboard View', action: 'scan', endpoint: '/api/movies/profile' },
          { id: 'normalize', label: 'Normalize Movie Files & Folders', action: 'plan', endpoint: '/api/movies/normalize' },
          { id: 'quality', label: 'Delete Weak Encodes', action: 'scan', endpoint: '/api/movies/profile' },
          { id: 'fix_defaults', label: 'Repair Defaults', action: 'scan', endpoint: '/api/movies/profile' },
          { id: 'junk', label: 'Delete Junk & Spam Files', action: 'scan', endpoint: '/api/movies/junk' },
          { id: 'canonical_lists', label: 'Canonical Lists', action: 'scan', endpoint: '/api/movies/canonical-lists' }
        ]
      }
    };

    const sourceInput = document.getElementById('sourcePath');
    const runButton = document.getElementById('runButton');
    const statusText = document.getElementById('statusText');
    const libraryRoots = document.getElementById('libraryRoots');
    const pageNav = document.getElementById('pageNav');
    const mainTitle = document.getElementById('mainTitle');
    const mainTagline = document.getElementById('mainTagline');
    const mainContent = document.getElementById('mainContent');
    const detailPanel = document.getElementById('detailPanel');
    const filterBar = document.getElementById('filterBar');
    const activityBar = document.getElementById('activityBar');
    const activityTitle = document.getElementById('activityTitle');
    const activityDetail = document.getElementById('activityDetail');

    let _scanTimer = null;
    let _activityGeneration = 0;
    let _scanStart = null;
    let _activeRunController = null;
    let _activityTimer = null;
    let _activityRequest = null;
    let _activityRequestSource = '';
    const _scanDurations = (() => { try { return JSON.parse(localStorage.getItem('n_scan_durations') || '{}'); } catch { return {}; } })();
    const _libraryRoots = (() => {
      try {
        const roots = JSON.parse(localStorage.getItem('n_library_roots') || '{}');
        return {
          movies: typeof roots.movies === 'string' ? roots.movies : ''
        };
      } catch {
        return { movies: '' };
      }
    })();
    let _recentLibraries = (() => {
      try {
        const recent = JSON.parse(localStorage.getItem('n_recent_libraries') || '[]');
        if (!Array.isArray(recent)) return [];
        return recent
          .filter(item => item && item.lane === 'movies' && typeof item.source === 'string' && item.source)
          .slice(0, 2);
      } catch {
        return [];
      }
    })();
    let _movieDashboardCache = (() => {
      try {
        const cache = JSON.parse(localStorage.getItem('n_movie_dashboard_cache_v2') || '{}');
        return cache && typeof cache === 'object' && !Array.isArray(cache) ? cache : {};
      } catch {
        return {};
      }
    })();
    let _movieCanonicalListsCache = (() => {
      try {
        const cache = JSON.parse(localStorage.getItem('n_movie_canonical_lists_cache_v3') || '{}');
        return cache && typeof cache === 'object' && !Array.isArray(cache) ? cache : {};
      } catch {
        return {};
      }
    })();
    let _movieReplacementQueueCache = (() => {
      try {
        const cache = JSON.parse(localStorage.getItem('n_movie_replacement_queue_cache') || '{}');
        return cache && typeof cache === 'object' && !Array.isArray(cache) ? cache : {};
      } catch {
        return {};
      }
    })();
    function setStatus(text, mode) {
      const dot = document.getElementById('statusDot');
      const fill = document.getElementById('statusFill');
      statusText.textContent = text;
      dot.className = 'status-dot' + (mode && mode !== 'idle' ? ' ' + mode : '');
      fill.className = 'status-fill' + (mode === 'running' ? ' running' : '');
    }

    function formatEta(seconds) {
      if (seconds == null || !Number.isFinite(seconds)) return 'eta unknown';
      const rounded = Math.max(0, Math.round(seconds));
      const mins = Math.floor(rounded / 60);
      const secs = rounded % 60;
      return mins ? `eta ${mins}m ${secs}s` : `eta ${secs}s`;
    }

    function formatByteSize(bytes) {
      if (!bytes || !Number.isFinite(bytes)) return '';
      if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
      if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
      if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
      return `${Math.round(bytes / 1e3)} KB`;
    }

    function activityProgressPieces(job) {
      const pieces = [];
      if (job.progress_fraction != null) pieces.push(`${Math.round(job.progress_fraction * 100)}%`);
      if (job.processed != null) {
        pieces.push(job.total && job.total > job.processed ? `${job.processed}/${job.total} files` : `${job.processed} files processed`);
      }
      pieces.push(`${Math.floor(job.elapsed_seconds || 0)}s elapsed`);
      pieces.push(formatEta(job.eta_seconds));
      return pieces.filter(Boolean);
    }

    function setActivityState(payload, errorMessage = '') {
      activityBar.classList.remove('active', 'external');
      if (errorMessage) {
        activityTitle.textContent = 'Drive activity: unknown';
        activityDetail.textContent = errorMessage;
        return;
      }
      const app = payload?.app || [];
      const probes = payload?.probes || [];
      const external = payload?.external || [];
      const source = sourceInput.value.trim();
      if (!source) {
        activityTitle.textContent = 'Drive activity: no source selected';
        activityDetail.textContent = 'Choose a library path to watch normal, ffprobe, and ffmpeg activity.';
        return;
      }
      if (probes.length) {
        activityBar.classList.add('active');
        const probe = probes[0];
        const job = app.find(item => item.kind !== 'probe') || null;
        const path = probe.current_path || '';
        activityTitle.textContent = 'Drive activity: ffprobe active';
        const progress = job ? activityProgressPieces(job).join(' · ') : '';
        activityDetail.textContent = `${probe.label}${path ? ' on ' + path.split('/').pop() : ''}${progress ? ' · ' + progress : ''}`;
        return;
      }
      if (app.length) {
        activityBar.classList.add('active');
        const job = app[0];
        if (job.kind === 'remux') {
          const name = (job.current_path || '').split('/').pop() || 'current file';
          const percent = job.progress_fraction != null ? `${Math.round(job.progress_fraction * 100)}%` : 'working';
          const size = formatByteSize(job.output_size_bytes);
          const speed = job.speed ? ` at ${job.speed}` : '';
          const pieces = [
            `${percent}${speed}`,
            `${Math.floor(job.elapsed_seconds || 0)}s elapsed`,
            formatEta(job.eta_seconds),
            size ? `${size} written` : ''
          ].filter(Boolean);
          activityTitle.textContent = 'Drive activity: ffmpeg remux active';
          activityDetail.textContent = `${job.label} on ${name} · ${pieces.join(' · ')}`;
          return;
        }
        activityTitle.textContent = 'Drive activity: normal is running';
        const pieces = activityProgressPieces(job);
        const path = job.current_path ? ` on ${job.current_path.split('/').pop()}` : '';
        activityDetail.textContent = `${job.label}${path}${pieces.length ? ' · ' + pieces.join(' · ') : ''}`;
        return;
      }
      if (external.length) {
        activityBar.classList.add('external');
        const process = external[0];
        activityTitle.textContent = `Drive activity: external ${process.command} detected`;
        activityDetail.textContent = `PID ${process.pid}: ${process.summary}`;
        return;
      }
      activityTitle.textContent = 'Drive activity: idle';
      activityDetail.textContent = payload?.os_note || 'No normal job or media probe detected for the selected source.';
    }

    async function refreshActivityState() {
      const source = sourceInput.value.trim();
      if (!source) {
        setActivityState(null);
        return null;
      }
      if (_activityRequest) {
        if (_activityRequestSource === source) return _activityRequest;
        return null;
      }
      const requestSource = source;
      const request = (async () => {
      try {
        const response = await fetch('/api/activity?source=' + encodeURIComponent(requestSource));
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Activity check failed.');
        if (sourceInput.value.trim() === requestSource) setActivityState(payload);
        return payload;
      } catch (error) {
        if (sourceInput.value.trim() === requestSource) setActivityState(null, error.message);
        return null;
      }
      })();
      _activityRequest = request;
      _activityRequestSource = requestSource;
      try {
        return await request;
      } finally {
        if (_activityRequest === request) {
          _activityRequest = null;
          _activityRequestSource = '';
        }
      }
    }

    async function _runActivityPollLoop(gen) {
      const payload = await refreshActivityState();
      if (gen !== _activityGeneration) return;
      _activityTimer = setTimeout(() => _runActivityPollLoop(gen), payload?.active ? 2000 : 10000);
    }

    function startActivityPolling() {
      clearTimeout(_activityTimer);
      const gen = ++_activityGeneration;
      _runActivityPollLoop(gen);
    }

    function startScanTimer(estimatedSecs) {
      _scanStart = Date.now();
      const timerEl = document.getElementById('statusTimer');
      timerEl.textContent = estimatedSecs ? `~${estimatedSecs}s est.` : '';
      clearInterval(_scanTimer);
      _scanTimer = setInterval(() => {
        const secs = Math.floor((Date.now() - _scanStart) / 1000);
        timerEl.textContent = estimatedSecs ? `${secs}s / ~${estimatedSecs}s` : `${secs}s elapsed`;
      }, 500);
    }

    function stopScanTimer() {
      clearInterval(_scanTimer);
      _scanTimer = null;
      const elapsed = _scanStart ? (Date.now() - _scanStart) / 1000 : null;
      _scanStart = null;
      if (elapsed !== null) document.getElementById('statusTimer').textContent = `done in ${elapsed.toFixed(1)}s`;
      return elapsed;
    }

    function setRunButtonRunning(running) {
      runButton.disabled = false;
      runButton.textContent = running ? 'Stop' : 'Run';
      runButton.classList.toggle('danger', running);
      runButton.classList.toggle('primary', !running);
    }

    function persistLibraryRoots() {
      try { localStorage.setItem('n_library_roots', JSON.stringify(_libraryRoots)); } catch {}
      fetch('/api/library-roots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movies: _libraryRoots.movies, recent: _recentLibraries })
      }).catch(() => {});
    }

    function persistRecentLibraries() {
      try { localStorage.setItem('n_recent_libraries', JSON.stringify(_recentLibraries)); } catch {}
      fetch('/api/library-roots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movies: _libraryRoots.movies, recent: _recentLibraries })
      }).catch(() => {});
    }

    function persistMovieDashboardCache() {
      try { localStorage.setItem('n_movie_dashboard_cache_v2', JSON.stringify(_movieDashboardCache)); } catch {}
    }

    function persistMovieCanonicalListsCache() {
      try { localStorage.setItem('n_movie_canonical_lists_cache_v3', JSON.stringify(_movieCanonicalListsCache)); } catch {}
    }

    function persistMovieReplacementQueueCache() {
      try { localStorage.setItem('n_movie_replacement_queue_cache', JSON.stringify(_movieReplacementQueueCache)); } catch {}
    }

    function dashboardCacheKey(source) {
      return source || '';
    }

    function trimDashboardCache(cache) {
      const entries = Object.entries(cache);
      if (entries.length <= 8) return cache;
      return Object.fromEntries(entries
        .sort((a, b) => String(b[1].cached_at || '').localeCompare(String(a[1].cached_at || '')))
        .slice(0, 8));
    }

    function cacheMovieDashboard(payload) {
      if (!payload || !payload.source_root || !payload.histogram) return;
      _movieDashboardCache[dashboardCacheKey(payload.source_root)] = {
        source_root: payload.source_root,
        histogram: payload.histogram,
        replacement_queue: payload.replacement_queue || null,
        movie_standards: payload.movie_standards || null,
        movie_standards_revision: payload.movie_standards_revision || '',
        quality_profile_definitions: payload.quality_profile_definitions || [],
        replacement_candidate_definition: payload.replacement_candidate_definition || null,
        cached_at: new Date().toISOString()
      };
      _movieDashboardCache = trimDashboardCache(_movieDashboardCache);
      persistMovieDashboardCache();
    }

    function cacheMovieCanonicalLists(payload) {
      if (!payload || !payload.source_root || !payload.library_summary || !Array.isArray(payload.list_summaries)) return;
      _movieCanonicalListsCache[dashboardCacheKey(payload.source_root)] = {
        source_root: payload.source_root,
        provider: payload.provider || '',
        cache_state: payload.cache_state || '',
        library_summary: payload.library_summary,
        list_summaries: payload.list_summaries,
        badges: payload.badges || [],
        warnings: payload.warnings || [],
        cached_at: new Date().toISOString()
      };
      _movieCanonicalListsCache = trimDashboardCache(_movieCanonicalListsCache);
      persistMovieCanonicalListsCache();
    }

    function cacheMovieReplacementQueue(queue) {
      if (!queue || !queue.source_root || !Array.isArray(queue.items)) return;
      _movieReplacementQueueCache[dashboardCacheKey(queue.source_root)] = {
        source_root: queue.source_root,
        issue_family: queue.issue_family || null,
        items: queue.items,
        cached_at: new Date().toISOString()
      };
      _movieReplacementQueueCache = trimDashboardCache(_movieReplacementQueueCache);
      persistMovieReplacementQueueCache();
    }

    function cachedMovieReplacementQueue(source) {
      const cached = _movieReplacementQueueCache[dashboardCacheKey(source)];
      if (!cached || !Array.isArray(cached.items)) return null;
      return {
        source_root: cached.source_root || source,
        issue_family: cached.issue_family || null,
        generated_at: cached.cached_at || new Date().toISOString(),
        items: cached.items
      };
    }

    function cachedMovieDashboard(source) {
      const cached = _movieDashboardCache[dashboardCacheKey(source)];
      if (!cached || !cached.histogram) return null;
      return {
        source_root: cached.source_root || source,
        histogram: cached.histogram,
        dashboard_snapshot_only: true,
        replacement_queue: cached.replacement_queue || null,
        movie_standards: cached.movie_standards || null,
        movie_standards_revision: cached.movie_standards_revision || '',
        quality_profile_definitions: cached.quality_profile_definitions || [],
        replacement_candidate_definition: cached.replacement_candidate_definition || null,
        movies: []
      };
    }

    function cachedMovieCanonicalLists(source) {
      const cached = _movieCanonicalListsCache[dashboardCacheKey(source)];
      if (!cached || !cached.library_summary || !Array.isArray(cached.list_summaries)) return null;
      return {
        source_root: cached.source_root || source,
        generated_at: cached.cached_at || new Date().toISOString(),
        provider: cached.provider || 'tmdb',
        cache_state: cached.cache_state || 'fresh',
        library_summary: cached.library_summary,
        list_summaries: cached.list_summaries,
        badges: cached.badges || [],
        warnings: cached.warnings || []
      };
    }

    function currentMovieProfileForSource() {
      const source = sourceInput.value.trim();
      const profile = state.results.movies.profile;
      return profile && profile.source_root === source ? profile : null;
    }

    function currentMovieCanonicalForSource() {
      const source = sourceInput.value.trim();
      const payload = state.results.movies.canonical;
      return payload && payload.source_root === source ? payload : null;
    }

    function restoreCachedMovieDashboard(source) {
      const cached = cachedMovieDashboard(source);
      if (!cached) return null;
      state.results.movies.profile = cached;
      if (cached.replacement_queue) {
        state.results.movies.replacementQueue = cached.replacement_queue;
        state.results.movies.replacementQueueSource = cached.source_root || '';
        cacheMovieReplacementQueue(cached.replacement_queue);
      }
      return cached;
    }

    function restoreCachedMovieCanonicalLists(source) {
      const cached = cachedMovieCanonicalLists(source);
      if (!cached) return null;
      state.results.movies.canonical = cached;
      return cached;
    }

    function restoreCachedMovieReplacementQueue(source) {
      const cached = cachedMovieReplacementQueue(source);
      if (!cached) return null;
      state.results.movies.replacementQueue = cached;
      state.results.movies.replacementQueueSource = cached.source_root || source;
      if (state.results.movies.profile && state.results.movies.profile.source_root === (cached.source_root || source)) {
        state.results.movies.profile.replacement_queue = cached;
      }
      return cached;
    }

    function rememberScannedLibrary(source) {
      if (!source) return;
      const lane = state.lane;
      _recentLibraries = [
        { lane, source },
        ..._recentLibraries.filter(item => !(item.lane === lane && item.source === source))
      ].slice(0, 2);
      persistRecentLibraries();
      renderLibraryRoots();
    }

    function promoteRecentLibrary(index) {
      const item = _recentLibraries[index];
      if (!item) return;
      const lane = item.lane;
      const source = item.source;
      if (!source) {
        setStatus('Choose a recent library before making it main.', 'error');
        return;
      }
      _libraryRoots[lane] = source;
      persistLibraryRoots();
      renderLibraryRoots();
      setStatus(`Set main ${CONFIG[lane].title} library.`, 'idle');
    }

    function useLibraryRoot(lane) {
      const source = _libraryRoots[lane] || '';
      if (!source) return;
      setLane(lane, { forceSource: source });
      if (lane === 'movies') {
        restoreCachedMovieDashboard(source);
      }
      setStatus(`Using saved ${CONFIG[lane].title} library.`, 'idle');
      renderCurrentPage();
    }

    function useRecentLibrary(index) {
      const item = _recentLibraries[index];
      if (!item) return;
      setLane(item.lane, { forceSource: item.source });
      if (item.lane === 'movies') {
        restoreCachedMovieDashboard(item.source);
      }
      setStatus(`Using recent ${CONFIG[item.lane].title} library.`, 'idle');
      renderCurrentPage();
    }

    function removeRecentLibrary(index) {
      const item = _recentLibraries[index];
      if (!item) return;
      _recentLibraries = _recentLibraries.filter((_, itemIndex) => itemIndex !== index);
      persistRecentLibraries();
      renderLibraryRoots();
      setStatus(`Removed recent ${CONFIG[item.lane].title} library.`, 'idle');
    }

    function renderLibraryRoots() {
      const currentSource = sourceInput.value.trim();
      const rootRows = ['movies'].map(lane => {
        const source = _libraryRoots[lane] || '';
        const isCurrent = state.lane === lane && source && source === currentSource;
        return `
          <div class="library-root ${isCurrent ? 'current' : ''}">
            <div>
              <div class="library-root-title">
                <strong>${escapeHtml(CONFIG[lane].title)}</strong>
                ${isCurrent ? '<span class="library-current-chip">Current</span>' : ''}
              </div>
              <div class="library-root-path">${escapeHtml(source || 'Not set')}</div>
            </div>
            <div class="library-root-actions">
              ${lane === 'movies' && source ? `<button class="secondary" data-catalogue-source="${escapeHtml(source)}">Export</button>` : ''}
              <button class="${isCurrent ? 'primary' : 'secondary'}" data-library-lane="${lane}" ${source ? '' : 'disabled'}>${isCurrent ? 'Using' : 'Use'}</button>
            </div>
          </div>
        `;
      }).join('');
      const uniqueRecentLibraries = _recentLibraries
        .map((item, index) => ({ ...item, index }))
        .filter(item => _libraryRoots[item.lane] !== item.source);
      const recentRows = uniqueRecentLibraries.map(item => {
        const isCurrent = state.lane === item.lane && item.source === currentSource;
        return `
          <div class="library-root ${isCurrent ? 'current' : ''}">
            <div>
              <div class="library-root-title">
                <strong>${escapeHtml(CONFIG[item.lane].title)}</strong>
                ${isCurrent ? '<span class="library-current-chip">Current</span>' : ''}
              </div>
              <div class="library-root-path">${escapeHtml(item.source)}</div>
            </div>
            <div class="library-root-actions">
              ${item.lane === 'movies' ? `<button class="secondary" data-catalogue-source="${escapeHtml(item.source)}">Export</button>` : ''}
              <button class="${isCurrent ? 'primary' : 'secondary'}" data-recent-library-index="${item.index}">${isCurrent ? 'Using' : 'Use'}</button>
              ${isCurrent ? `<button class="secondary" data-promote-library-index="${item.index}">Make Main ${escapeHtml(CONFIG[item.lane].title)} Library</button>` : ''}
              <button class="secondary" data-remove-recent-library-index="${item.index}">Remove</button>
            </div>
          </div>
        `;
      }).join('');
      libraryRoots.innerHTML = `
        <div class="library-subhead">Main Libraries</div>
        ${rootRows}
        ${recentRows ? `<div class="library-subhead">Recently Scanned Libraries</div>${recentRows}` : ''}
      `;
      libraryRoots.querySelectorAll('[data-library-lane]').forEach(button => {
        button.addEventListener('click', () => useLibraryRoot(button.dataset.libraryLane));
      });
      libraryRoots.querySelectorAll('[data-recent-library-index]').forEach(button => {
        button.addEventListener('click', () => useRecentLibrary(Number(button.dataset.recentLibraryIndex)));
      });
      libraryRoots.querySelectorAll('[data-promote-library-index]').forEach(button => {
        button.addEventListener('click', () => promoteRecentLibrary(Number(button.dataset.promoteLibraryIndex)));
      });
      libraryRoots.querySelectorAll('[data-remove-recent-library-index]').forEach(button => {
        button.addEventListener('click', () => removeRecentLibrary(Number(button.dataset.removeRecentLibraryIndex)));
      });
      libraryRoots.querySelectorAll('[data-catalogue-source]').forEach(btn => {
        btn.addEventListener('click', () => generateCatalogue(btn, btn.dataset.catalogueSource));
      });
    }

    sourceInput.value = window.DEFAULT_SOURCE || _libraryRoots.movies || '';
    renderLibraryRoots();

    fetch('/api/library-roots').then(r => r.json()).then(data => {
      let changed = false;
      if (data.movies && data.movies !== _libraryRoots.movies) { _libraryRoots.movies = data.movies; changed = true; }
      if (Array.isArray(data.recent) && JSON.stringify(data.recent) !== JSON.stringify(_recentLibraries)) {
        _recentLibraries = data.recent; changed = true;
      }
      if (changed) {
        if (!window.DEFAULT_SOURCE && !sourceInput.value.trim()) sourceInput.value = _libraryRoots.movies || '';
        renderLibraryRoots();
      }
    }).catch(() => {});

    runButton.addEventListener('click', runCurrentPage);

    sourceInput.addEventListener('input', () => {
      refreshActivityState();
    });

    const THEMES = {
      default: {
        label: 'Default',
        css: `
          :root {
            --bg: #f2f2f7;
            --panel: #ffffff;
            --panel-2: #f9f9fb;
            --ink: #1c1c1e;
            --muted: #8e8e93;
            --line: #e5e5ea;
            --accent: #007aff;
            --accent-2: #5856d6;
            --movies: #007aff;
            --danger: #ff3b30;
            --warn: #ff9500;
            --shadow: rgba(0,0,0,0.08);
            --font-body: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif;
            --radius: 12px;
            --input-bg: #ffffff;
            --btn-secondary: #e9e9ed;
            --btn-nav: #f2f2f7;
            --th-bg: #f9f9fb;
            --surface: rgba(255,255,255,0.85);
            --bar-track: #e5e5ea;
            --accent-glow: rgba(0,122,255,0.08);
          }
          body {
            background: linear-gradient(180deg, #f2f2f7 0%, #e8e8ed 100%) !important;
          }
          .card {
            box-shadow: 0 2px 12px var(--shadow), 0 1px 2px rgba(0,0,0,0.04) !important;
          }
          h1 { font-weight: 700; letter-spacing: -0.02em; }
          h2 { font-weight: 600; letter-spacing: -0.01em; }
          button { letter-spacing: -0.01em; }
        `
      },
      win95: {
        label: 'Win95',
        css: `
          :root {
            --bg: #c0c0c0;
            --panel: #c0c0c0;
            --panel-2: #c0c0c0;
            --ink: #000000;
            --muted: #444444;
            --line: #808080;
            --accent: #000080;
            --accent-2: #800000;
            --movies: #000080;
            --danger: #800000;
            --warn: #808000;
            --shadow: rgba(0,0,0,0.4);
            --font-body: Tahoma, "MS Sans Serif", Arial, sans-serif;
            --radius: 0px;
            --input-bg: #ffffff;
            --btn-secondary: #c0c0c0;
            --btn-nav: #c0c0c0;
            --th-bg: #c0c0c0;
            --surface: #c0c0c0;
            --bar-track: #808080;
            --accent-glow: rgba(0,0,128,0.08);
          }
          body { background: #c0c0c0 !important; }
          .card {
            border: 2px solid !important;
            border-color: #ffffff #808080 #808080 #ffffff !important;
            box-shadow: 1px 1px 0 #000 !important;
          }
          button {
            border: 2px solid !important;
            border-color: #ffffff #808080 #808080 #ffffff !important;
            background: #c0c0c0 !important;
            box-shadow: none !important;
          }
          button:active {
            border-color: #808080 #ffffff #ffffff #808080 !important;
          }
          .eyebrow {
            background: linear-gradient(to right, #000080, #1084d0);
            color: #ffffff;
            margin: -12px -12px 12px -12px;
            padding: 3px 6px;
            font-size: 11px;
            letter-spacing: 0.05em;
          }
          .mast-side { padding: 12px; }
        `
      },
      dark: {
        label: 'Dark',
        css: `
          :root {
            --bg: #121212;
            --panel: #181818;
            --panel-2: #282828;
            --ink: #ffffff;
            --muted: #b3b3b3;
            --line: #282828;
            --accent: #1db954;
            --accent-2: #1ed760;
            --movies: #1db954;
            --danger: #e91429;
            --warn: #e38b28;
            --shadow: rgba(0,0,0,0.5);
            --font-body: "DM Sans", Inter, "Helvetica Neue", Arial, sans-serif;
            --radius: 8px;
            --input-bg: #282828;
            --btn-secondary: #282828;
            --btn-nav: #1a1a1a;
            --th-bg: #181818;
            --surface: rgba(255,255,255,0.05);
            --bar-track: #333333;
            --accent-glow: rgba(29,185,84,0.1);
          }
          body { background: #121212 !important; }
          .card {
            border-color: transparent !important;
            box-shadow: none !important;
          }
          h1 { font-weight: 800; letter-spacing: -0.03em; }
          h2 { font-weight: 700; letter-spacing: -0.02em; }
        `
      },
      matrix: {
        label: 'Matrix',
        css: `
          :root {
            --bg: #000000;
            --panel: #050f05;
            --panel-2: #071007;
            --ink: #00ff41;
            --muted: #007a1f;
            --line: #003a10;
            --accent: #00ff41;
            --accent-2: #00c832;
            --movies: #00ff41;
            --danger: #ff3a00;
            --warn: #c8a000;
            --shadow: rgba(0,255,65,0.08);
            --font-body: "Courier New", Courier, monospace;
            --radius: 2px;
            --input-bg: #050f05;
            --btn-secondary: #071007;
            --btn-nav: #050f05;
            --th-bg: #050f05;
            --surface: rgba(0,255,65,0.04);
            --bar-track: #003a10;
            --accent-glow: rgba(0,255,65,0.08);
          }
          body { background: #000000 !important; }
          .card {
            border-color: #003a10 !important;
            box-shadow: 0 0 24px rgba(0,255,65,0.07), inset 0 0 1px rgba(0,255,65,0.15) !important;
          }
          h1, h2, .eyebrow { text-shadow: 0 0 12px rgba(0,255,65,0.6); }
          .page-button.active, .filter-button.active {
            box-shadow: 0 0 8px rgba(0,255,65,0.4) !important;
          }
        `
      },
      sand: {
        label: 'Sand',
        css: ''
      }
    };

    function applyTheme(id) {
      const theme = THEMES[id] || THEMES['default'];
      let el = document.getElementById('n-theme');
      if (!el) { el = document.createElement('style'); el.id = 'n-theme'; document.head.appendChild(el); }
      el.textContent = theme.css;
      try { localStorage.setItem('n_theme', id); } catch {}
      document.querySelectorAll('.theme-btn').forEach(b => b.classList.toggle('active', b.dataset.theme === id));
    }

    function renderThemePicker() {
      const container = document.getElementById('themeBtns');
      if (!container) return;
      container.innerHTML = Object.entries(THEMES).map(([id, t]) =>
        `<button class="theme-btn" data-theme="${id}">${t.label}</button>`
      ).join('');
      container.querySelectorAll('.theme-btn').forEach(btn => btn.addEventListener('click', () => applyTheme(btn.dataset.theme)));
    }

    const _savedTheme = (() => { try { return localStorage.getItem('n_theme') || 'default'; } catch { return 'default'; } })();
    applyTheme(_savedTheme);
    renderThemePicker();
    setLane('movies');
    startActivityPolling();

    function setLane(lane, options = {}) {
      state.lane = lane;
      state.page = CONFIG[lane].pages[0].id;
      state.filter = 'all';
      if (options.forceSource !== undefined) sourceInput.value = options.forceSource;
      else if (!sourceInput.value.trim() && _libraryRoots[lane]) sourceInput.value = _libraryRoots[lane];
      document.getElementById('heroTitle').textContent = CONFIG[lane].title;
      document.getElementById('heroLede').textContent = CONFIG[lane].lede;
      sourceInput.placeholder = CONFIG[lane].sourceLabel;
      renderLibraryRoots();
      renderPageNav();
      renderCurrentPage();
      refreshActivityState();
    }

    function setPage(page) {
      state.page = page;
      state.filter = page === 'quality' ? 'strict_weak' : 'all';
      state.fixDefaultsTab = 'audio';
      state.qualitySort = { col: null, dir: 'asc' };
      state.subtitleSort = { col: null, dir: 'asc' };
      state.replacementHistoryFilter = 'deleted';
      state.replacementHistorySort = { col: null, dir: 'asc' };
      state.movieProfileInspectorLabel = '';
      state.movieProfileInspectorType = '';
      state.movieCanonicalInspectorId = '';
      renderPageNav();
      renderCurrentPage();
    }

    function renderPageNav() {
      pageNav.innerHTML = CONFIG[state.lane].pages.map(page => `
        <button class="page-button ${page.id === state.page ? 'active' : ''}" data-page="${page.id}">${page.label}</button>
      `).join('');
      pageNav.querySelectorAll('.page-button').forEach(button => button.addEventListener('click', () => setPage(button.dataset.page)));
    }

    async function generateCatalogue(btn, sourceOverride) {
      const source = sourceOverride || sourceInput.value.trim();
      if (!source) { setStatus('Enter a source path first.', 'error'); return; }
      if (!await confirmSourceScope(source)) return;
      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Generating…';
      try {
        const response = await fetch('/api/movies/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source })
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({ error: 'unknown error' }));
          setStatus('Catalogue failed: ' + (err.error || response.statusText), 'error');
          return;
        }
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'movie-catalogue.xlsx';
        a.click();
        URL.revokeObjectURL(url);
        setStatus('Catalogue downloaded.', 'idle');
      } catch (e) {
        setStatus('Catalogue failed: ' + e.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    }

    async function runCurrentPage() {
      if (_activeRunController) {
        _activeRunController.abort();
        _activeRunController = null;
        setRunButtonRunning(false);
        stopScanTimer();
        setStatus('Stopping scan…', 'idle');
        refreshActivityState();
        return;
      }
      const pageConfig = CONFIG[state.lane].pages.find(page => page.id === state.page);
      if (!pageConfig || !pageConfig.endpoint) {
        setStatus(`${pageConfig?.label || 'This page'} is not wired yet.`, 'idle');
        renderCurrentPage();
        return;
      }
      const source = sourceInput.value.trim();
      if (!source) {
        setStatus('Enter a source path first.', 'error');
        return;
      }
      if (!await confirmSourceScope(source)) return;
      _activeRunController = new AbortController();
      setRunButtonRunning(true);
      const _durationKey = `${state.lane}:${state.page}`;
      setStatus(`Running — ${pageConfig.label}…`, 'running');
      startScanTimer(_scanDurations[_durationKey]);
      refreshActivityState();
      try {
        const requestBody = { source };
        if (state.lane === 'movies' && pageConfig.id === 'normalize') {
          requestBody.naming_style = state.movieNamingStyle || 'concise';
        }
        async function fetchPagePayload(body) {
          const response = await fetch(pageConfig.endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: _activeRunController.signal
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || 'Request failed.');
          return payload;
        }
        const payload = await fetchPagePayload(requestBody);
        storePayload(pageConfig.id, payload);
        if (state.lane !== 'movies') detailPanel.innerHTML = '<div class="empty">Run complete.</div>';
        const _elapsed = stopScanTimer();
        if (_elapsed) { _scanDurations[_durationKey] = Math.round(_elapsed); try { localStorage.setItem('n_scan_durations', JSON.stringify(_scanDurations)); } catch {} }
        rememberScannedLibrary(payload.source_root || source);
        setStatus(`Complete — ${payload.source_root}`, 'idle');
        renderCurrentPage();
      } catch (error) {
        stopScanTimer();
        if (error.name === 'AbortError') setStatus('Scan stopped.', 'idle');
        else setStatus(error.message, 'error');
      } finally {
        _activeRunController = null;
        setRunButtonRunning(false);
        refreshActivityState();
      }
    }

    async function confirmSourceScope(source) {
      try {
        const response = await fetch('/api/source/scan-warning', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Unable to check source path.');
        if (!payload.warn) return true;
        const warning = payload.message || 'This source may be risky for a heavy recursive scan.';
        return confirm(`${warning}\n\nTotal size: ${payload.total_size_label}\n\nOnly run one heavy scan for this source at a time.\n\nContinue?`);
      } catch (error) {
        setStatus(error.message, 'error');
        return false;
      }
    }

    function storePayload(page, payload) {
      {
        if (['library', 'quality', 'fix_defaults', 'compatibility'].includes(page)) {
          state.results.movies.profile = payload;
          cacheMovieDashboard(payload);
          if (payload.replacement_queue) {
            state.results.movies.replacementQueue = payload.replacement_queue;
            state.results.movies.replacementQueueSource = payload.source_root || '';
            cacheMovieReplacementQueue(payload.replacement_queue);
          }
          state.selectedReplacementPaths.clear();
          if (page === 'fix_defaults' && state.fixDefaultsTab === 'subtitle') {
            state.subtitleHistory = null;
            state.subtitleHistoryFilter = 'all';
            syncSubtitleReviewOnlyHistory(payload);
          }
        }
        if (page === 'canonical_lists') {
          state.results.movies.canonical = payload;
          cacheMovieCanonicalLists(payload);
        }
        if (page === 'normalize') {
          state.results.movies.normalize = payload;
          state.results.movies.apply = null;
          state.movieNamingStyle = payload.naming_style || payload.default_naming_style || state.movieNamingStyle || 'concise';
          state.selectedChangeIds = new Set();
          state.selectedNormalizeResultIds = new Set();
        }
        if (page === 'junk') {
          state.results.movies.junk = payload;
          state.selectedJunkPaths.clear();
        }
      }
    }

    function renderCurrentPage() {
      const lane = state.lane;
      const page = state.page;
      const titleMap = {
        normalize: 'Normalize',
        canonical_lists: 'Canonical Lists',
        quality: 'Delete Weak Encodes',
        fix_defaults: 'Repair Defaults',
        compatibility: 'Compatibility',
        junk: 'Delete Junk & Spam Files',
        library: 'Dashboard'
      };
      mainTitle.textContent = `${CONFIG[lane].title} / ${titleMap[page]}`;
      renderMoviePage(page);
    }

    function renderMoviePage(page) {
      const source = sourceInput.value.trim();
      const profile = currentMovieProfileForSource();
      const canonical = currentMovieCanonicalForSource();
      const normalize = state.results.movies.normalize;
      if (page === 'normalize') {
        renderMovieNormalize(normalize);
        return;
      }
      if (page === 'junk') {
        renderMovieJunk(state.results.movies.junk);
        return;
      }
      if (page === 'library') {
        renderMovieLibrary(profile || restoreCachedMovieDashboard(source));
        return;
      }
      if (page === 'canonical_lists') {
        renderMovieCanonicalLists(canonical || restoreCachedMovieCanonicalLists(source));
        return;
      }
      if (page === 'quality') {
        loadMovieReplacementQueue();
        renderMovieQuality(profile);
        return;
      }
      if (page === 'fix_defaults') {
        if (state.fixDefaultsTab === 'audio') loadMovieReplacementQueue();
        else if (!state.subtitleHistory) syncSubtitleReviewOnlyHistory(profile);
        renderMovieFixDefaults(profile);
        return;
      }
      if (page === 'compatibility') {
        renderMovieCompatibility(profile);
        return;
      }
    }

    async function loadMovieReplacementQueue(force = false) {
      const source = sourceInput.value.trim();
      if (!source) {
        renderReplacementQueueDetail(state.results.movies.profile);
        return;
      }
      if (!force && !state.results.movies.replacementQueue) {
        restoreCachedMovieReplacementQueue(source);
      }
      if (!force && state.results.movies.replacementQueue && state.results.movies.replacementQueueSource === source) {
        renderReplacementQueueDetail(state.results.movies.profile);
        return;
      }
      try {
        const response = await fetch('/api/movies/replacement-queue/list', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Queue load failed.');
        state.results.movies.replacementQueue = result;
        state.results.movies.replacementQueueSource = source;
        cacheMovieReplacementQueue(result);
        if (state.results.movies.profile) state.results.movies.profile.replacement_queue = result;
        if (state.page === 'quality' && state.results.movies.profile) renderMovieQuality(state.results.movies.profile);
        else if (state.page === 'fix_defaults' && state.results.movies.profile) renderMovieFixDefaults(state.results.movies.profile);
        else renderReplacementQueueDetail(state.results.movies.profile);
      } catch (error) {
        detailPanel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      }
    }

    function renderMovieLibrary(payload) {
      mainTagline.textContent = 'Collection overview: quality tier distribution, resolution breakdown, and at-a-glance diagnostics.';
      renderMetrics(buildMovieMetrics(payload));
      renderBars(buildMovieBars(payload));
      filterBar.innerHTML = '';
      if (state.movieProfileInspectorLabel && payload) {
        mainContent.innerHTML = buildMovieProfileInspector(payload, state.movieProfileInspectorLabel, state.movieProfileInspectorType);
        attachMovieProfileInspectorHandlers(payload);
        detailPanel.innerHTML = buildBitrateBellCurve(payload);
        return;
      }
      mainContent.innerHTML = buildMovieDashboard(payload);
      attachMovieDashboardHandlers(payload);
      if (!payload) {
        detailPanel.innerHTML = '<div class="empty">Run Movies / Dashboard to see bitrate distribution.</div>';
        return;
      }
      detailPanel.innerHTML = buildBitrateBellCurve(payload);
    }

    function attachMovieDashboardHandlers(payload) {
      document.querySelectorAll('.movie-profile-view-btn').forEach(button => {
        button.addEventListener('click', () => {
          state.movieProfileInspectorLabel = button.dataset.profileLabel || '';
          state.movieProfileInspectorType = button.dataset.profileType || 'quality';
          state.movieProfileInspectorSort = { col: 'title', dir: 'asc' };
          renderMovieLibrary(payload);
        });
      });
      document.querySelectorAll('.movie-profile-definition-toggle').forEach(button => {
        button.addEventListener('click', () => {
          const label = button.dataset.profileLabel || '';
          state.movieStandardsEditorLabel = state.movieStandardsEditorLabel === label ? '' : label;
          renderMovieLibrary(payload);
        });
      });
      document.querySelectorAll('.movie-profile-definition-save').forEach(button => {
        button.addEventListener('click', () => saveMovieProfileDefinition(button.dataset.profileLabel || ''));
      });
      document.querySelectorAll('.movie-profile-definition-cancel').forEach(button => {
        button.addEventListener('click', () => {
          state.movieStandardsEditorLabel = '';
          renderMovieLibrary(payload);
        });
      });
    }

    function renderMovieCanonicalLists(payload) {
      mainTagline.textContent = 'Canonical title coverage against live all-time movie lists. This page ignores bitrate, quality, and warning telemetry.';
      renderMetrics([]);
      renderBars([]);
      filterBar.innerHTML = '';
      if (state.movieCanonicalInspectorId && payload) {
        mainContent.innerHTML = buildMovieCanonicalInspector(payload, state.movieCanonicalInspectorId);
        attachMovieCanonicalInspectorHandlers(payload);
        detailPanel.innerHTML = buildMovieCanonicalBadgePanel(payload);
        return;
      }
      mainContent.innerHTML = buildMovieCanonicalListsDashboard(payload);
      if (!payload) {
        detailPanel.innerHTML = '<div class="empty">Run Movies / Canonical Lists to see badge progress.</div>';
        return;
      }
      detailPanel.innerHTML = buildMovieCanonicalBadgePanel(payload);
      document.querySelectorAll('.movie-canonical-view-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          state.movieCanonicalInspectorId = btn.dataset.canonicalListId || '';
          state.movieCanonicalInspectorSort = { col: 'rank', dir: 'asc' };
          renderMovieCanonicalLists(payload);
        });
      });
    }

    function buildMovieCanonicalListsDashboard(payload) {
      if (!payload) return '<div class="empty">Run Movies / Canonical Lists to compare the library against curated movie lists.</div>';
      const summary = payload.library_summary || {};
      const lists = Array.isArray(payload.list_summaries) ? payload.list_summaries : [];
      const cacheLabel = payload.cache_state === 'stale' ? 'cached snapshot' : payload.cache_state === 'live' ? 'live fetch' : 'fresh cache';
      const statsHtml = `
        <div class="dash-stats">
          <div class="metric"><strong>${String(summary.owned_movies || 0)}</strong><span>owned movies</span></div>
          <div class="metric"><strong>${String(summary.matched_canonical_titles || 0)}</strong><span>matched canonical titles</span></div>
          <div class="metric"><strong>${String(summary.lists_cleared || 0)}</strong><span>lists cleared</span></div>
          <div class="metric"><strong>${String(summary.unparsed_files || 0)}</strong><span>unparsed files</span></div>
        </div>
      `;
      const maxCovered = Math.max(...lists.map(item => item.covered_count || 0), 1);
      const cardsHtml = lists.map(item => {
        const barWidth = ((item.covered_count || 0) / maxCovered) * 100;
        const missingPreview = (item.missing_titles || []).slice(0, 2).map(entry => `${entry.title} (${entry.year})`).join(' · ');
        return `
          <div class="profile-card">
            <div class="profile-card-group">${escapeHtml(item.provider_label || 'Canonical list')}</div>
            <div class="profile-card-name">${escapeHtml(item.label || 'List')}</div>
            <div class="profile-card-count">${escapeHtml(`${item.covered_count || 0}/${item.total_count || 0}`)}</div>
            <div class="profile-card-pct">${escapeHtml(formatPercent(item.coverage_percent || 0))} coverage</div>
            <div class="profile-card-bar"><span style="width:${barWidth}%"></span></div>
            <div class="coverage-card-note">${escapeHtml(item.missing_count ? `${item.missing_count} missing${missingPreview ? ` · ${missingPreview}` : ''}` : 'Complete or near-complete coverage.')}</div>
            <button class="secondary movie-canonical-view-btn" data-canonical-list-id="${escapeHtml(item.id || '')}">View</button>
          </div>
        `;
      }).join('');
      return `
        <div class="dash-actions">
          <span class="subtle">Provider: TMDb canonical lists</span>
          <span class="subtle">Data source: ${escapeHtml(cacheLabel)}</span>
          ${(summary.duplicate_files || 0) ? `<span class="subtle">Duplicate files ignored: ${summary.duplicate_files}</span>` : ''}
        </div>
        ${statsHtml}
        <div class="dash-section-label">Canonical List Coverage</div>
        <div class="profile-grid">${cardsHtml || '<div class="subtle">No canonical list data.</div>'}</div>
      `;
    }

    function buildMovieCanonicalBadgePanel(payload) {
      const badges = Array.isArray(payload?.badges) ? payload.badges : [];
      const badgeHtml = badges.map(badge => `
        <div class="badge-tile ${badge.unlocked ? '' : 'locked'}" style="${badge.unlocked ? `background:${escapeHtml(badge.color || '#577590')}` : ''}">
          <div class="badge-kicker">${badge.unlocked ? 'Unlocked' : 'Locked'}</div>
          <div class="badge-name">${escapeHtml(badge.label || 'Badge')}</div>
          <div class="badge-meta">${escapeHtml(`${formatPercent(badge.coverage_percent || 0)} / ${formatPercent(badge.threshold_percent || 0)}`)}</div>
        </div>
      `).join('');
      return `
        <div class="finding">
          <h3>Badge Collection</h3>
          <p>${badges.filter(item => item.unlocked).length} of ${badges.length} unlocked</p>
          <div class="badge-grid">${badgeHtml || '<div class="subtle">No badges yet.</div>'}</div>
        </div>
      `;
    }

    function buildMovieCanonicalInspector(payload, listId) {
      const lists = Array.isArray(payload?.list_summaries) ? payload.list_summaries : [];
      const listSummary = lists.find(item => item.id === listId);
      if (!listSummary) return '<div class="empty">List not found.</div>';
      const allEntries = Array.isArray(listSummary.all_entries) ? listSummary.all_entries : [];
      if (!allEntries.length) {
        const hint = (listSummary.total_count || 0) > 0
          ? `Re-run Movies / Canonical Lists to load ${listSummary.total_count} titles for this list.`
          : 'Run Movies / Canonical Lists to compare your library against this list.';
        return `
          <div style="margin-bottom:1em">
            <button class="secondary movie-canonical-inspector-back">← Back to Dashboard</button>
          </div>
          <div class="empty">${escapeHtml(hint)}</div>
        `;
      }
      const profileMovies = Array.isArray(state.results.movies.profile?.movies) ? state.results.movies.profile.movies : [];
      const qualityByPath = {};
      for (const m of profileMovies) {
        if (m.path) qualityByPath[m.path] = { label: m.profile?.quality_label || '', res: m.facts?.resolution_bucket || '' };
      }
      const sort = state.movieCanonicalInspectorSort;
      const mul = sort.dir === 'asc' ? 1 : -1;
      const indexed = allEntries.map((entry, i) => ({ ...entry, rank: i + 1 }));
      indexed.sort((a, b) => {
        if (sort.col === 'year') return (a.year - b.year) * mul;
        if (sort.col === 'status') return ((a.owned ? 0 : 1) - (b.owned ? 0 : 1)) * mul;
        if (sort.col === 'rank') return (a.rank - b.rank) * mul;
        return a.title.localeCompare(b.title) * mul;
      });
      function ind(col) {
        if (sort.col !== col) return '<span class="sort-ind">↕</span>';
        return `<span class="sort-ind on">${sort.dir === 'asc' ? '↑' : '↓'}</span>`;
      }
      const ownedCount = allEntries.filter(e => e.owned).length;
      const missingCount = allEntries.length - ownedCount;
      const rows = indexed.map(entry => `
        <tr>
          <td class="mono" style="width:5%;text-align:right;padding-right:1em">${entry.rank}</td>
          <td style="width:55%">${escapeHtml(entry.title)}</td>
          <td style="width:10%">${escapeHtml(String(entry.year))}</td>
          <td style="width:30%">${(() => { if (!entry.owned) return '<span class="subtle">Missing</span>'; const q = entry.path ? qualityByPath[entry.path] : null; if (!q || (!q.label && !q.res)) return 'Owned'; return `Owned <span class="subtle">· ${escapeHtml([q.label, q.res].filter(Boolean).join(' · '))}</span>`; })()}</td>
        </tr>
      `).join('');
      return `
        <div style="margin-bottom:1em">
          <button class="secondary movie-canonical-inspector-back">← Back to Dashboard</button>
          <span style="margin-left:1em">${escapeHtml(listSummary.label)} — ${allEntries.length} titles · ${ownedCount} owned · ${missingCount} missing</span>
        </div>
        <table class="subtitle-table" style="width:100%">
          <thead><tr>
            <th class="movie-inspector-th sortable-th" data-sort-col="rank" style="width:5%;text-align:right;padding-right:1em"># ${ind('rank')}</th>
            <th class="movie-inspector-th sortable-th" data-sort-col="title" style="width:55%">Title ${ind('title')}</th>
            <th class="movie-inspector-th sortable-th" data-sort-col="year" style="width:10%">Year ${ind('year')}</th>
            <th class="movie-inspector-th sortable-th" data-sort-col="status" style="width:30%">Status ${ind('status')}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    function attachMovieCanonicalInspectorHandlers(payload) {
      document.querySelector('.movie-canonical-inspector-back')?.addEventListener('click', () => {
        state.movieCanonicalInspectorId = '';
        renderMovieCanonicalLists(payload);
      });
      document.querySelectorAll('.movie-inspector-th[data-sort-col]').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.sortCol;
          if (state.movieCanonicalInspectorSort.col === col) {
            state.movieCanonicalInspectorSort.dir = state.movieCanonicalInspectorSort.dir === 'asc' ? 'desc' : 'asc';
          } else {
            state.movieCanonicalInspectorSort = { col, dir: 'asc' };
          }
          renderMovieCanonicalLists(payload);
        });
      });
    }

    function renderMovieQuality(payload) {
      mainTagline.textContent = 'Replacement candidates and inline standards review. This page keeps low-confidence hygiene issues visible without expanding the table.';
      renderMetrics(buildMovieMetrics(payload));
      renderBars(buildMovieBars(payload));
      filterBar.innerHTML = '';
      if (!payload) {
        mainContent.innerHTML = '<div class="empty">Run Movies / Delete Weak Encodes to see standards results.</div>';
        return;
      }
      const items = sortedMovies(movieStandardsWorkflowItems(payload));
      mainContent.innerHTML = buildMovieQualityTable(payload, items);
      renderReplacementQueueDetail(payload);
      attachMovieReplacementHandlers(payload, items);
    }

    function renderMovieFixDefaults(payload) {
      const tab = state.fixDefaultsTab;
      mainTagline.textContent = tab === 'audio'
        ? 'Files where the default audio is the wrong language, or the English track is weaker than expected.'
        : 'Repair subtitle defaults without deleting files: no subtitle by default when appropriate, forced English when needed, and English subtitles for non-English default audio.';
      renderMetrics(buildMovieMetrics(payload));
      renderBars(buildMovieBars(payload));
      if (tab === 'audio') {
        renderFilters([
          ['all', 'All'],
          ['weak_english', 'Weak English Fallback'],
          ['wrong_default', 'Wrong Default Language']
        ]);
      } else {
        renderFilters([
          ['all', 'All'],
          ['forced_english', 'Forced English'],
          ['non_english_audio', 'Non-English Audio'],
          ['clear_default', 'Clear Default']
        ]);
      }
      if (!payload) {
        mainContent.innerHTML = tab === 'audio'
          ? '<div class="empty">Run Movies / Repair Defaults to review language-default mistakes.</div>'
          : '<div class="empty">Run Movies / Repair Defaults to review subtitle-default mistakes.</div>';
        if (tab === 'subtitle') detailPanel.innerHTML = '<div class="empty">No review-only items.</div>';
        return;
      }
      if (tab === 'audio') {
        const items = sortedMovies(filteredAudioPackagingMovies(payload));
        mainContent.innerHTML = buildMovieFixDefaultsTabs(tab) + buildMovieAudioPackagingTable(payload, items);
        renderReplacementQueueDetail(payload);
        attachMovieReplacementHandlers(payload, items);
      } else {
        const items = sortedSubtitleItems(filteredSubtitleReadinessMovies(payload));
        mainContent.innerHTML = buildMovieFixDefaultsTabs(tab) + buildMovieSubtitleReadinessTable(payload, items);
        renderSubtitleReadinessDetail(payload);
        attachMovieSubtitleReadinessHandlers(payload, items);
      }
      document.querySelectorAll('.fix-defaults-tab').forEach(btn => {
        btn.addEventListener('click', () => {
          if (btn.dataset.tab === state.fixDefaultsTab) return;
          state.fixDefaultsTab = btn.dataset.tab;
          state.filter = 'all';
          state.qualitySort = { col: null, dir: 'asc' };
          state.subtitleSort = { col: null, dir: 'asc' };
          state.selectedReplacementPaths.clear();
          if (state.fixDefaultsTab === 'audio') loadMovieReplacementQueue();
          else syncSubtitleReviewOnlyHistory(payload);
          renderMovieFixDefaults(payload);
        });
      });
    }

    function buildMovieFixDefaultsTabs(activeTab) {
      return `<div class="page-nav" style="margin-bottom:12px;">
        <button class="filter-button fix-defaults-tab${activeTab === 'audio' ? ' active' : ''}" data-tab="audio">Audio Packaging</button>
        <button class="filter-button fix-defaults-tab${activeTab === 'subtitle' ? ' active' : ''}" data-tab="subtitle">Subtitle Readiness</button>
      </div>`;
    }


    function formatPercent(value) {
      if (value == null || !Number.isFinite(value)) return 'n/a';
      return `${value.toFixed(1)}%`;
    }

    function renderMovieCompatibility(payload) {
      mainTagline.textContent = 'Playback-risk and visibility-risk heuristics, especially for anime and TV indexing edge cases.';
      renderMetrics(buildMovieMetrics(payload));
      renderBars(buildMovieBars(payload));
      renderFilters([
        ['all', 'All'],
        ['playback_risk', 'Playback Risk'],
        ['indexing_visibility_risk', 'Visibility Risk'],
        ['anime', 'Anime / TV']
      ]);
      if (!payload) {
        mainContent.innerHTML = '<div class="empty">Run Movies / Compatibility to inspect heuristic risk clusters.</div>';
        return;
      }
      mainContent.innerHTML = buildMovieTable(filteredMovies(payload, state.filter));
      renderReplacementQueueDetail(payload);
      attachMovieReplacementHandlers(payload, []);
    }

    function renderMovieNormalize(payload) {
      mainTagline.textContent = 'Review proposed movie file and folder renames, approve, and apply.';
      const activePayload = activeMovieNormalizePayload(payload);
      renderMetrics(buildMovieNormalizeMetrics(activePayload));
      renderBars(buildMovieNormalizeBars(activePayload));
      const applyResult = state.results.movies.apply;
      if (!activePayload) {
        filterBar.innerHTML = '';
        const applyBanner = applyResult ? buildApplyResultBanner(applyResult) : '';
        mainContent.innerHTML = applyBanner + '<div class="empty">Run Movies / Normalize to generate rename proposals.</div>';
        showMovieNormalizeTreeDetail(null);
        return;
      }
      if (state.filter === 'all') state.filter = 'all_results';

      renderFilters([
        ['all_results', 'All Results'],
        ['safe', 'Safe'],
        ['review', 'Flagged for review'],
        ['warnings', 'Warnings']
      ]);

      const rowsPayload = filteredMovieNormalizeRows(activePayload);
      const selectedCount = selectedProposedChanges(activePayload).length;
      const selectedResultCount = selectedMovieNormalizeResults(activePayload).length;
      const visibleKeys = rowsPayload.map(row => row.type === 'result' ? row.result.result_id : row.change.item_id);
      const visibleSelectedCount = rowsPayload.filter(row => row.type === 'result'
        ? isMovieNormalizeResultSelected(row.result)
        : state.selectedChangeIds.has(row.change.item_id)
      ).length;
      const allVisibleSelected = visibleKeys.length > 0 && visibleSelectedCount === visibleKeys.length;
      const rows = rowsPayload.map(row => {
        const result = row.result || null;
        const change = row.change || null;
        const rowId = result?.result_id || '';
        const changeId = change?.item_id || '';
        const checked = result ? isMovieNormalizeResultSelected(result) : state.selectedChangeIds.has(changeId);
        const confidence = change?.confidence || result?.confidence || 'unchanged';
        const typeLabel = change?.change_type || (result?.actionable ? 'movie_file' : 'no_change');
        const path = change?.path || result?.path || '';
        const currentValue = change?.current_value || result?.current_value || '';
        const proposedValue = change?.proposed_value || result?.proposed_value || '';
        const chipLabel = confidence === 'unchanged' ? 'no change' : confidence;
        return `
        <tr>
          <td style="width:28px;text-align:center"><input type="checkbox" class="movie-normalize-checkbox" data-row-type="${row.type}" data-result-id="${escapeHtml(rowId)}" data-item-id="${escapeHtml(changeId)}" ${checked ? 'checked' : ''}></td>
          <td><span class="chip ${escapeHtml(confidence)}">${escapeHtml(chipLabel)}</span></td>
          <td>${escapeHtml(typeLabel)}</td>
          <td><div class="mono">${escapeHtml(path)}</div></td>
          <td>${escapeHtml(currentValue)}</td>
          <td>${escapeHtml(proposedValue)}</td>
        </tr>
      `}).join('');
      const warningCounts = CounterFromArray((activePayload.warnings || []).map(w => w.code));
      const warningList = Object.entries(warningCounts).map(([code, count]) => `<span class="chip review">${escapeHtml(code)}${count > 1 ? ` ×${count}` : ''}</span>`).join('');
      const applyBanner = applyResult ? buildApplyResultBanner(applyResult) : '';
      mainContent.innerHTML = `
        ${applyBanner}
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
          <label class="subtle" for="movieNamingStyleSelect">Naming</label>
          <select id="movieNamingStyleSelect" style="min-width:280px">
            <option value="concise" ${activePayload.naming_style === 'concise' ? 'selected' : ''}>Concise Naming</option>
            <option value="verbose" ${activePayload.naming_style === 'verbose' ? 'selected' : ''}>Verbose Naming - Include Extra Information</option>
          </select>
        </div>
        <div class="subtle" style="margin-bottom:10px;">Warnings: ${warningList || 'none'}</div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
          <button class="secondary sel-toggle" id="selToggle">${allVisibleSelected ? 'Deselect All' : 'Select All'}</button>
          <span class="subtle" id="selCount" style="margin-left:4px">${selectedCount} actionable${selectedResultCount ? `, ${selectedResultCount} result${selectedResultCount === 1 ? '' : 's'}` : ''} selected</span>
          <div style="flex:1"></div>
          <button class="primary" id="applyBtn" ${selectedCount === 0 ? 'disabled' : ''} style="min-width:160px">Apply ${selectedCount} Changes</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th><th>Confidence</th><th>Type</th><th>Path</th><th>Current</th><th>Proposed</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="6" class="subtle">No normalize results for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;

      document.getElementById('selToggle').addEventListener('click', () => {
        toggleVisibleMovieNormalizeRows(activePayload, rowsPayload, allVisibleSelected);
        renderMovieNormalize(payload);
      });
      document.getElementById('applyBtn').addEventListener('click', applySelectedMovieChanges);
      document.getElementById('movieNamingStyleSelect').addEventListener('change', event => {
        state.movieNamingStyle = event.target.value;
        renderMovieNormalize(payload);
      });

      mainContent.querySelectorAll('.movie-normalize-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
          updateMovieNormalizeSelection(activePayload, cb.dataset.rowType, cb.dataset.resultId, cb.dataset.itemId, cb.checked);
          const nextPayload = activeMovieNormalizePayload(payload);
          const count = selectedProposedChanges(nextPayload).length;
          const resultCount = selectedMovieNormalizeResults(nextPayload).length;
          const nextVisibleRows = filteredMovieNormalizeRows(nextPayload);
          const nextVisibleSelectedCount = nextVisibleRows.filter(row => row.type === 'result'
            ? isMovieNormalizeResultSelected(row.result)
            : state.selectedChangeIds.has(row.change.item_id)
          ).length;
          const nextAllVisibleSelected = nextVisibleRows.length > 0 && nextVisibleSelectedCount === nextVisibleRows.length;
          const countEl = document.getElementById('selCount');
          if (countEl) countEl.textContent = `${count} actionable${resultCount ? `, ${resultCount} result${resultCount === 1 ? '' : 's'}` : ''} selected`;
          const toggle = document.getElementById('selToggle');
          if (toggle) toggle.textContent = nextAllVisibleSelected ? 'Deselect All' : 'Select All';
          const btn = document.getElementById('applyBtn');
          if (btn) { btn.disabled = count === 0; btn.textContent = `Apply ${count} Changes`; }
          showMovieNormalizeTreeDetail(nextPayload);
        });
      });

      showMovieNormalizeTreeDetail(activePayload);
    }

    async function applySelectedMovieChanges() {
      const payload = activeMovieNormalizePayload(state.results.movies.normalize);
      const source = sourceInput.value.trim();
      if (!payload || !source) return;
      const changes = (payload.proposed_changes || []).filter(c => state.selectedChangeIds.has(c.item_id));
      if (changes.length === 0) return;
      const btn = document.getElementById('applyBtn');
      if (btn) btn.disabled = true;
      setStatus(`Applying ${changes.length} changes…`, 'running');
      try {
        const response = await fetch('/api/movies/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, changes, naming_style: payload.naming_style || state.movieNamingStyle || 'concise' })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Apply failed.');
        state.results.movies.apply = result;
        state.results.movies.normalize = result.remaining_plan || null;
        state.selectedChangeIds = new Set();
        state.selectedNormalizeResultIds = new Set();
        const remaining = result.remaining_safe_count || 0;
        const suffix = remaining ? ` ${remaining} safe rename${remaining === 1 ? '' : 's'} still pending.` : '';
        setStatus(`Applied: ${result.applied.length}, skipped: ${result.skipped.length}, failed: ${result.failed.length}.${suffix}`, remaining ? 'error' : 'idle');
        renderMovieNormalize(state.results.movies.normalize);
      } catch (error) {
        setStatus(error.message, 'error');
        if (btn) btn.disabled = false;
      }
    }

    function renderPlaceholder(title, bullets) {
      mainTagline.textContent = 'Wireframe-level page with the agreed responsibilities, held here until the backend workflow exists.';
      renderMetrics([]);
      renderBars([]);
      filterBar.innerHTML = '';
      mainContent.innerHTML = `
        <div class="placeholder-grid">
          <div class="placeholder">
            <h3 style="margin:0 0 8px;">${escapeHtml(title)}</h3>
            ${bullets.map(item => `<p>${escapeHtml(item)}</p>`).join('')}
          </div>
        </div>
      `;
    }

    function renderMetrics(metrics) {
      renderLibraryRoots();
    }

    function renderBars(bars) {
      renderLibraryRoots();
    }

    function renderFilters(filters) {
      filterBar.innerHTML = filters.map(([id, label]) => `
        <button class="filter-button ${state.filter === id ? 'active' : ''}" data-filter="${id}">${label}</button>
      `).join('');
      filterBar.querySelectorAll('.filter-button').forEach(button => {
        button.addEventListener('click', () => {
          state.filter = button.dataset.filter;
          renderCurrentPage();
        });
      });
    }

    function fmtFileSize(bytes) {
      if (!bytes) return '—';
      if (bytes >= 1e12) return (bytes / 1e12).toFixed(2) + ' TB';
      if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
      return (bytes / 1e6).toFixed(1) + ' MB';
    }
    function fmtAudioBitrate(facts) {
      if (!facts?.audio_bitrate_kbps) return '<span class="subtle">—</span>';
      const val = Math.round(facts.audio_bitrate_kbps).toLocaleString();
      return facts.audio_bitrate_estimated ? `${val}+ kbps <span class="subtle">est.</span>` : `${val} kbps`;
    }

    const LOSSLESS_FAMILIES = new Set(['truehd', 'dtshd', 'flac', 'pcm']);
    const NORM_MULT = { aac: 1.30, eac3: 1.12, dts: 0.95, ac3: 1.00 };
    const TAPER_START_PER_CH = 75;
    const TAPER_END_PER_CH = 110;

    function normalizeAudioBitrate(facts) {
      const family = (facts?.audio_format_family || '').toLowerCase();
      if (LOSSLESS_FAMILIES.has(family)) return { lossless: true };
      const raw = facts?.audio_bitrate_kbps;
      if (!raw) return { missing: true };
      const mult = NORM_MULT[family] ?? 1.00;
      const channels = facts?.audio_channels || 6;
      const taperStart = TAPER_START_PER_CH * channels;
      const taperEnd = TAPER_END_PER_CH * channels;
      const normalizedRaw = raw * mult;
      if (normalizedRaw >= taperEnd) return { nearTransparent: true, threshold: Math.round(taperEnd) };
      let normalized;
      if (normalizedRaw >= taperStart) {
        const t = (normalizedRaw - taperStart) / (taperEnd - taperStart);
        const effectiveMult = mult + t * (1.0 - mult);
        normalized = Math.round(raw * effectiveMult);
      } else {
        normalized = Math.round(normalizedRaw);
      }
      return { normalized, raw };
    }

    function fmtNormAudioBitrate(facts) {
      const n = normalizeAudioBitrate(facts);
      if (!n || n.missing) return '<span class="subtle">—</span>';
      if (n.lossless) return '<span class="subtle">Lossless</span>';
      const ch = facts?.audio_channels || 6;
      if (n.nearTransparent) return `<span title="Near transparent for ${ch}-channel audio">≥${n.threshold.toLocaleString()} kbps eq. <span class="subtle">~</span></span>`;
      return `${n.normalized.toLocaleString()} kbps eq. <span class="subtle" title="AC3-equivalent estimate">~</span>`;
    }

    function humanProfileLabel(label) {
      if (label === 'standard_definition') return 'Standard Definition';
      if (label === 'library_grade') return 'Library Grade';
      if (label === 'collector_grade') return 'Collector Grade';
      if (label === 'reference') return 'Reference';
      if (label === 'meets_minimum') return 'Meets Minimum';
      if (label === 'needs_review') return 'Needs Review';
      if (label === 'replacement_candidate') return 'Replacement Candidate';
      return label.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    }

    function movieProfileInlineSummary(item) {
      const failed = (item?.profile?.domain_results || []).filter(result => result?.status === 'fail');
      const reviews = (item?.profile?.domain_results || []).filter(result => result?.status === 'review_low_confidence');
      if (failed.length) return failed[0]?.summary || '';
      if (reviews.length) return `Low confidence: ${reviews[0]?.summary || ''}`.trim();
      if (item?.profile?.legacy_bitrate_label) return `Legacy bitrate: ${humanLegacyBitrateLabel(item.profile.legacy_bitrate_label)}`;
      return '';
    }

    function humanLegacyBitrateLabel(label) {
      if (!label) return '';
      if (label === '1080p_uhd') return '1080p UHD';
      if (label === '4k_uhd') return '4K UHD';
      if (label === 'weak_4k') return 'Weak 4K';
      if (label === 'compressed_4k') return 'Compressed 4K';
      if (label === '4k_remux') return '4K Remux';
      return label.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    }

    function buildMovieTable(items) {
      const rows = items.map(item => {
        const videoBitrate = item.facts.video_bitrate_kbps ? `${Math.round(item.facts.video_bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
        const audioBitrate = fmtAudioBitrate(item.facts);
        const audioSummary = item.facts.audio_summary ? escapeHtml(item.facts.audio_summary) : '<span class="subtle">—</span>';
        const diagnostics = item.profile.diagnostics.slice(0, 3).map(diag => {
          const categoryClass = diag.category === 'indexing_visibility_risk'
            ? 'indexing'
            : (diag.category === 'standards_review' ? 'review' : 'playback');
          return `<span class="chip ${categoryClass}">${escapeHtml(diag.code)}</span>`;
        }).join('');
        const profileSummary = movieProfileInlineSummary(item);
        return `
          <tr>
            <td><div class="mono">${escapeHtml(item.path)}</div></td>
            <td>${escapeHtml(humanProfileLabel(item.profile.label))}${profileSummary ? `<div class="subtle">${escapeHtml(profileSummary)}</div>` : ''}</td>
            <td>${escapeHtml(item.facts.resolution_bucket || '')}</td>
            <td>${videoBitrate}</td>
            <td>${audioBitrate}</td>
            <td>${audioSummary}</td>
            <td>${diagnostics || '<span class="subtle">none</span>'}</td>
          </tr>
        `;
      }).join('');
      return `
        <div class="table-wrap">
          <table>
            <thead><tr><th>File</th><th>Profile</th><th>Resolution</th><th>Video Bitrate</th><th>Audio Bitrate</th><th>Audio</th><th>Diagnostics</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="7" class="subtle">No files for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function activeMovieTriageFamily() {
      if (state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio') return 'audio_packaging';
      return 'weak_encode';
    }

    function activeMovieTriageFamilyLabel() {
      return activeMovieTriageFamily() === 'audio_packaging' ? 'Audio Packaging' : 'Weak Encode';
    }

    function movieQueueItemsForFamily(payload, issueFamily = activeMovieTriageFamily()) {
      const queue = currentMovieReplacementQueue(payload);
      const items = queue?.items || [];
      return items.filter(item => (item.issue_family || 'weak_encode') === issueFamily);
    }

    function buildMovieQualityTable(payload, items) {
      const queue = currentMovieReplacementQueue(payload);
      const queueItems = movieQueueItemsForFamily(payload, 'weak_encode');
      const qPending = queueItems.filter(i => i.status === 'pending').length;
      const qDeleted = queueItems.filter(i => i.status === 'deleted').length;
      const qDismissed = queueItems.filter(i => i.status === 'dismissed').length;
      const qCompleted = queueItems.filter(i => i.status === 'completed').length;
      const qSource = sourceInput.value.trim() || queue?.source_root || '';
      const queueSummary = (qPending || qDeleted || qCompleted || qDismissed) ? `
        <div class="finding">
          <h3>Replacement Queue · Weak Encode</h3>
          <p>${qPending} pending delete · ${qDeleted} deleted and waiting replacement · ${qCompleted} successfully replaced · ${qDismissed} deleted from queue</p>
          ${qSource ? `<p><strong>Directory:</strong> <span class="mono">${escapeHtml(qSource)}</span></p>` : ''}
        </div>
      ` : '';
      const rows = items.map(item => {
        const path = item.path || '';
        const isWeak = isStrictWeakMovie(item);
        const queueItem = replacementQueueItemForPath(payload, path, 'weak_encode');
        const checked = state.selectedReplacementPaths.has(path) ? 'checked' : '';
        const videoBitrate = item.facts.video_bitrate_kbps ? `${Math.round(item.facts.video_bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
        const audioBitrate = fmtAudioBitrate(item.facts);
        const audioSummary = item.facts.audio_summary ? escapeHtml(item.facts.audio_summary) : '<span class="subtle">—</span>';
        const fileSize = item.facts.file_size_bytes ? fmtFileSize(item.facts.file_size_bytes) : '<span class="subtle">—</span>';
        const profileSummary = movieProfileInlineSummary(item);
        const selectable = isWeak && !queueItem;
        return `
          <tr>
            <td style="width:28px;text-align:center">${selectable ? `<input type="checkbox" class="replacement-select" data-path="${encodeURIComponent(path)}" ${checked}>` : ''}</td>
            <td><div class="mono">${escapeHtml(path)}</div></td>
            <td>${escapeHtml(humanProfileLabel(item.profile.label))}${profileSummary ? `<div class="subtle">${escapeHtml(profileSummary)}</div>` : ''}</td>
            <td>${escapeHtml(item.facts.resolution_bucket || '')}</td>
            <td>${videoBitrate}</td>
            <td>${audioBitrate}</td>
            <td>${audioSummary}</td>
            <td>${fileSize}</td>
            <td>${replacementQueueStatusChip(queueItem)}</td>
          </tr>
        `;
      }).join('');
      const selectedCount = selectedVisibleReplacementCount(payload, items);
      const selectableCount = selectableVisibleReplacementItems(payload, items).length;
      const allVisibleSelected = selectableCount > 0 && selectedCount === selectableCount;
      const toggleLabel = allVisibleSelected ? 'Deselect All' : 'Select All';
      return `
        ${queueSummary}
        <div class="junk-actions">
          <button class="secondary sel-toggle" id="toggleAllReplacementButton" ${selectableCount ? '' : 'disabled'}>${toggleLabel}</button>
          <button class="danger" id="deleteSelectedFilesButton" ${selectedCount ? '' : 'disabled'}>Delete Selected Files</button>
          <span class="subtle">${selectedCount} of ${selectableCount} selected</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th>${['file','profile','resolution','video_bitrate','audio_bitrate','audio_summary','file_size'].map(col => { const active = state.qualitySort.col === col; const ind = active ? (state.qualitySort.dir === 'asc' ? '↑' : '↓') : '↕'; const label = {file:'File',profile:'Profile',resolution:'Resolution',video_bitrate:'Video Bitrate',audio_bitrate:'Audio Bitrate',audio_summary:'Audio',file_size:'File Size'}[col]; return `<th class="sortable-th" data-sort-col="${col}">${label}<span class="sort-ind${active?' on':''}">${ind}</span></th>`; }).join('')}<th>Status</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="9" class="subtle">No files for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function buildMovieAudioPackagingTable(payload, items) {
      const queue = currentMovieReplacementQueue(payload);
      const queueItems = movieQueueItemsForFamily(payload, 'audio_packaging');
      const qPending = queueItems.filter(i => i.status === 'pending').length;
      const qDeleted = queueItems.filter(i => i.status === 'deleted').length;
      const qDismissed = queueItems.filter(i => i.status === 'dismissed').length;
      const qCompleted = queueItems.filter(i => i.status === 'completed').length;
      const qSource = sourceInput.value.trim() || queue?.source_root || '';
      const queueSummary = (qPending || qDeleted || qCompleted) ? `
        <div class="finding">
          <h3>Replacement Queue · Audio Packaging</h3>
          <p>${qPending} pending delete · ${qDeleted} deleted and waiting replacement · ${qCompleted} successfully replaced · ${qDismissed} deleted from queue</p>
          ${qSource ? `<p><strong>Directory:</strong> <span class="mono">${escapeHtml(qSource)}</span></p>` : ''}
        </div>
      ` : '';
      const rows = items.map(item => {
        const path = item.path || '';
        const queueItem = replacementQueueItemForPath(payload, path, 'audio_packaging');
        const checked = state.selectedReplacementPaths.has(path) ? 'checked' : '';
        const locked = state.movieAudioFixBusy ? 'disabled' : '';
        const issueCode = movieAudioPackagingIssueCode(item);
        const issueLabel = issueCode === 'default_non_english_audio_with_weak_english'
          ? '<span class="chip high">wrong language · weak English</span>'
          : '<span class="chip review">wrong language</span>';
        const audioSummary = item.facts.audio_summary ? escapeHtml(item.facts.audio_summary) : '<span class="subtle">—</span>';
        const profileSummary = movieProfileInlineSummary(item);
        const defaultStream = describeAudioStream(movieDefaultAudioStream(item));
        const englishStream = describeAudioStream(movieBestEnglishAudioStream(item));
        const selectable = !!issueCode;
        return `
          <tr>
            <td style="width:28px;text-align:center">${selectable ? `<input type="checkbox" class="replacement-select" data-path="${encodeURIComponent(path)}" ${checked} ${locked}>` : ''}</td>
            <td><div class="mono">${escapeHtml(path)}</div></td>
            <td>${issueLabel}${profileSummary ? `<div class="subtle">${escapeHtml(profileSummary)}</div>` : ''}</td>
            <td>${audioSummary}</td>
            <td>${defaultStream}</td>
            <td>${englishStream}</td>
            <td>${replacementQueueStatusChip(queueItem)}</td>
          </tr>
        `;
      }).join('');
      const selectedCount = selectedVisibleReplacementCount(payload, items);
      const selectableCount = selectableVisibleReplacementItems(payload, items).length;
      const allVisibleSelected = selectableCount > 0 && selectedCount === selectableCount;
      const toggleLabel = allVisibleSelected ? 'Deselect All' : 'Select All';
      const lockNote = state.movieAudioFixBusy
        ? '<span class="subtle">Selection locked while ffmpeg remux is running.</span>'
        : `<span class="subtle">${selectedCount} of ${selectableCount} selected</span>`;
      const wrongLangCount = items.filter(i => movieAudioPackagingIssueCode(i) === 'default_non_english_audio').length;
      const weakEnglishCount = items.filter(i => movieAudioPackagingIssueCode(i) === 'default_non_english_audio_with_weak_english').length;
      const issueSummary = items.length
        ? `<div class="subtle" style="margin-bottom:8px;">${wrongLangCount} wrong language · ${weakEnglishCount} weak English fallback</div>`
        : '';
      return `
        ${queueSummary}
        ${issueSummary}
        <div class="junk-actions audio-packaging-actions">
          <button class="secondary sel-toggle" id="toggleAllReplacementButton" ${(selectableCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>${toggleLabel}</button>
          <button class="warn sel-toggle" id="fixSelectedAudioButton" ${(selectedCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>Set English Default</button>
          <button class="caution sel-toggle" id="fixSelectedAudioAndDropForeignButton" ${(selectedCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>Set English Default + Drop Foreign</button>
          <span class="triage-action-spacer"></span>
          <button class="danger sel-toggle" id="deleteSelectedFilesButton" ${(selectedCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>Delete Selected Files</button>
          <span class="triage-action-note">${lockNote}</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th><th>File</th><th>Issue</th><th>Audio</th><th>Current Default</th><th>English Track</th><th>Status</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="7" class="subtle">No files for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function buildMovieSubtitleReadinessTable(payload, items) {
      const rows = items.map(item => {
        const path = item.path || '';
        const checked = state.selectedReplacementPaths.has(path) ? 'checked' : '';
        const locked = state.movieSubtitleFixBusy ? 'disabled' : '';
        const issueCode = movieSubtitleReadinessIssueCode(item);
        const issueLabel = humanSubtitleReadinessIssueLabel(issueCode);
        const targetSummary = itemSubtitleTargetSummary(item, { forcedOnly: true });
        const englishSummary = itemSubtitleTargetSummary(item);
        const selectable = movieSubtitleReadinessIsRepairable(item);
        return `
          <tr>
            <td style="width:28px;text-align:center">${selectable ? `<input type="checkbox" class="subtitle-repair-select" data-path="${encodeURIComponent(path)}" ${checked} ${locked}>` : ''}</td>
            <td>${(() => { const stem = path.split('/').pop().replace(/\\.[^.]+$/, ''); const m = stem.match(/^(.+?)\\s*\\((\\d{4})\\)/); return m ? escapeHtml(`${m[1]} (${m[2]})`) : `<span class="mono">${escapeHtml(stem || path)}</span>`; })()}</td>
            <td>${escapeHtml(issueLabel)}</td>
            <td>${describeAudioStream(movieDefaultAudioStream(item))}</td>
            <td>${describeSubtitleStream(movieDefaultSubtitleStream(item))}</td>
            <td>${targetSummary}</td>
            <td>${englishSummary}</td>
          </tr>
        `;
      }).join('');
      const selectedCount = selectedVisibleSubtitleRepairCount(payload, items);
      const selectableCount = selectableVisibleSubtitleRepairItems(payload, items).length;
      const allVisibleSelected = selectableCount > 0 && selectedCount === selectableCount;
      const toggleLabel = allVisibleSelected ? 'Deselect All' : 'Select All';
      const lockNote = state.movieSubtitleFixBusy
        ? '<span class="subtle">Selection locked while ffmpeg remux is running.</span>'
        : `<span class="subtle">${selectedCount} of ${selectableCount} selected</span>`;
      return `
        <div class="junk-actions audio-packaging-actions">
          <button class="secondary sel-toggle" id="toggleSubtitleRepairButton" ${(selectableCount && !state.movieSubtitleFixBusy) ? '' : 'disabled'}>${toggleLabel}</button>
          <button class="primary" id="fixSelectedSubtitleButton" ${(selectedCount && !state.movieSubtitleFixBusy) ? '' : 'disabled'}>Repair Subtitle Defaults</button>
          <span class="subtle">This page is non-destructive.</span>
          <span class="triage-action-note">${lockNote}</span>
        </div>
        <div class="table-wrap">
          <table class="subtitle-table">
            <thead><tr><th></th>${[['title','Title'],['issue','Issue'],['default_audio','Default Audio'],['current_default_subtitle','Current Default Subtitle'],['english_forced_subtitle','English Forced Subtitle'],['english_subtitle','English Subtitle']].map(([col,label]) => { const active = state.subtitleSort.col === col; const ind = active ? (state.subtitleSort.dir === 'asc' ? '↑' : '↓') : '↕'; return `<th class="subtitle-sortable-th sortable-th" data-sort-col="${col}">${label}<span class="sort-ind${active?' on':''}">${ind}</span></th>`; }).join('')}</tr></thead>
            <tbody>${rows || '<tr><td colspan="7" class="subtle">No files for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function buildSubtitleHistoryTable(items) {
      const rows = items.map(item => {
        const title = item.title ? (item.year ? `${item.title} (${item.year})` : item.title) : (item.path || '').split('/').pop().replace(/\.[^.]+$/, '');
        const issueLabel = humanSubtitleReadinessIssueLabel(item.issue_code || '');
        const typeChip = item.entry_type === 'fixed'
          ? '<span class="chip safe">fixed</span>'
          : '<span class="chip review">review only</span>';
        const dismissBtn = `<button class="subtitle-history-dismiss" data-item-id="${escapeHtml(item.item_id)}" title="Dismiss">×</button>`;
        return `<tr><td>${escapeHtml(title)}</td><td>${issueLabel ? escapeHtml(issueLabel) : '<span class="subtle">—</span>'}</td><td>${typeChip}</td><td style="text-align:right">${dismissBtn}</td></tr>`;
      }).join('');
      return `
        <div class="table-wrap">
          <table>
            <thead><tr><th style="width:45%">Title</th><th style="width:30%">Issue</th><th style="width:15%">Type</th><th style="width:10%"></th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    }

    function renderSubtitleReadinessDetail(payload) {
      const history = state.subtitleHistory;
      const historyItems = history ? (history.items || []) : null;
      const activeItems = historyItems ? historyItems.filter(i => !i.dismissed_at) : null;
      const filter = state.subtitleHistoryFilter || 'all';
      const filteredItems = activeItems ? activeItems.filter(i => {
        if (filter === 'fixed') return i.entry_type === 'fixed';
        if (filter === 'review_only') return i.entry_type === 'review_only';
        return true;
      }) : null;
      const hasHistory = activeItems && activeItems.length > 0;
      const filterButtons = hasHistory ? `
        <div class="page-nav">
          ${[['all', 'All'], ['fixed', 'Fixed'], ['review_only', 'Review Only']].map(([id, label]) =>
            `<button class="filter-button subtitle-history-filter ${filter === id ? 'active' : ''}" data-history-filter="${id}">${label}</button>`
          ).join('')}
        </div>
      ` : '';
      const tableHtml = filteredItems && filteredItems.length
        ? buildSubtitleHistoryTable(filteredItems)
        : (hasHistory ? '<div class="empty">No items matching this filter.</div>' : null);
      if (!historyItems) {
        detailPanel.innerHTML = '<div class="empty">No subtitle history yet.</div>';
      } else if (!hasHistory) {
        detailPanel.innerHTML = '<div class="empty">No subtitle history yet.</div>';
      } else {
        detailPanel.innerHTML = `
          <div style="font-weight:600;margin:10px 0 6px">Subtitle History</div>
          ${filterButtons}
          ${tableHtml || ''}
        `;
        attachSubtitleHistoryHandlers(payload);
      }
    }

    function attachSubtitleHistoryHandlers(payload) {
      document.querySelectorAll('.subtitle-history-dismiss').forEach(button => {
        button.addEventListener('click', () => dismissSubtitleHistoryItem(button.dataset.itemId, payload));
      });
      document.querySelectorAll('.subtitle-history-filter').forEach(button => {
        button.addEventListener('click', () => {
          state.subtitleHistoryFilter = button.dataset.historyFilter || 'all';
          renderSubtitleReadinessDetail(payload);
        });
      });
    }

    async function syncSubtitleReviewOnlyHistory(payload) {
      const source = sourceInput.value.trim();
      if (!source || !payload) return;
      const reviewOnlyItems = reviewOnlySubtitleReadinessMovies(payload);
      const items = reviewOnlyItems.map(item => ({
        path: item.path || '',
        issue_code: movieSubtitleReadinessIssueCode(item),
      })).filter(i => i.path);
      try {
        const response = await fetch('/api/movies/subtitle-readiness/history/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, items }),
        });
        if (!response.ok) return;
        const history = await response.json();
        state.subtitleHistory = history;
        renderSubtitleReadinessDetail(payload);
      } catch (_) {}
    }

    async function dismissSubtitleHistoryItem(itemId, payload) {
      const source = sourceInput.value.trim();
      if (!source || !itemId) return;
      try {
        const response = await fetch('/api/movies/subtitle-readiness/history/dismiss', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, item_ids: [itemId] }),
        });
        if (!response.ok) return;
        const history = await response.json();
        state.subtitleHistory = history;
        renderSubtitleReadinessDetail(payload);
      } catch (_) {}
    }

    function currentMovieReplacementQueue(payload) {
      return payload?.replacement_queue || state.results.movies.replacementQueue || null;
    }

    function replacementQueueItemForPath(payload, path, issueFamily = activeMovieTriageFamily()) {
      if (!path) return null;
      return movieQueueItemsForFamily(payload, issueFamily).find(item =>
        item.original_path === path && ['pending', 'deleted', 'completed'].includes(item.status)
      ) || null;
    }

    function replacementQueueStatusChip(item) {
      if (!item) return '<span class="subtle">—</span>';
      if (item.status === 'pending') return '<span class="chip meta">queued</span>';
      if (item.status === 'deleted') return '<span class="chip review">deleted, waiting replacement</span>';
      if (item.status === 'dismissed') return '<span class="chip meta">deleted from queue</span>';
      if (item.status === 'completed') return '<span class="chip safe">replaced</span>';
      return '<span class="subtle">—</span>';
    }

    function buildPendingReplacementTable(items) {
      const replacementQueueReferenceFields = ['original_folder_path'];
      const rows = items.slice(0, 8).map(item => {
        const title = `${item.title || ''}${item.year ? ` (${item.year})` : ''}`;
        const videoBitrate = item.video_bitrate_kbps ? `${Math.round(item.video_bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
        return `
          <tr>
            <td>${escapeHtml(title)}</td>
            <td>${escapeHtml(item.issue_family === 'audio_packaging' ? (item.issue_label || 'audio packaging') : humanProfileLabel(item.original_profile_label || ''))}</td>
            <td>${escapeHtml(item.resolution_bucket || '')}</td>
            <td>${videoBitrate}</td>
            <td><button class="danger replacement-delete" data-item-id="${escapeHtml(item.item_id)}">Delete media</button></td>
          </tr>
        `;
      }).join('');
      return `
        <div class="table-wrap">
          <table>
            <thead><tr><th>Movie Title</th><th>Issue</th><th>Resolution</th><th>Video Bitrate</th><th>Action</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="5" class="subtle">No pending delete items.</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function buildReplacementHistoryTable(items) {
      const grouped = groupedReplacementHistoryItems(items);
      const baseline = replacementHistoryBaselineOrder(grouped);
      const seqMap = new Map(baseline.map((item, i) => [item.group_id, i + 1]));
      const { col, dir } = state.replacementHistorySort;
      const mult = dir === 'asc' ? 1 : -1;
      const hasOmdb = !!(window.OMDB_AVAILABLE);
      const sorted = col ? [...grouped].sort((a, b) => {
        if (col === 'seq') return mult * ((seqMap.get(a.group_id) || 0) - (seqMap.get(b.group_id) || 0));
        if (col === 'title') return mult * (a.title || '').localeCompare(b.title || '', undefined, { sensitivity: 'base' });
        if (col === 'year') return mult * ((a.year || 0) - (b.year || 0));
        if (col === 'count') return mult * ((a.count || 0) - (b.count || 0));
        if (col === 'imdb') {
          const ra = replacementHistoryRatingValue(a);
          const rb = replacementHistoryRatingValue(b);
          return mult * (ra - rb);
        }
        return 0;
      }) : baseline;
      const cols = [['seq','#'],['title','Title'],['year','Year'],['count','Count']];
      if (hasOmdb) cols.push(['imdb', 'IMDb']);
      const thead = cols.map(([c, label]) => {
        const active = state.replacementHistorySort.col === c;
        const ind = active ? (state.replacementHistorySort.dir === 'asc' ? '↑' : '↓') : '↕';
        return `<th class="replacement-history-sort-th sortable-th" data-sort-col="${c}">${label}<span class="sort-ind${active?' on':''}">${ind}</span></th>`;
      }).join('') + '<th>Status</th>';
      const rows = sorted.map(item => {
        const rating = state.omdbRatings.get(item.group_id);
        const ratingCell = hasOmdb ? `<td>${replacementHistoryRatingCell(rating)}</td>` : '';
        const dismissButton = item.status === 'deleted'
          ? `<button class="queue-inline-remove replacement-history-remove" data-item-ids="${escapeHtml(item.item_ids.join(','))}" title="Remove from queue">x</button>`
          : '';
        return `
          <tr>
            <td>${seqMap.get(item.group_id)}</td>
            <td>${escapeHtml(item.title || '')}</td>
            <td>${item.year ? escapeHtml(String(item.year)) : '<span class="subtle">—</span>'}</td>
            <td>${item.count > 1 ? escapeHtml(String(item.count)) : '<span class="subtle">—</span>'}</td>
            ${ratingCell}
            <td>${replacementHistoryStatusChip(item.status)}${dismissButton}</td>
          </tr>
        `;
      }).join('');
      if (hasOmdb) fetchMissingOmdbRatings(grouped);
      const status = hasOmdb && state.omdbStatus ? `<div class="subtle" style="margin:0 0 8px">${escapeHtml(state.omdbStatus)}</div>` : '';
      return `${status}<div class="table-wrap"><table style="min-width:0"><thead><tr>${thead}</tr></thead><tbody>${rows}</tbody></table></div>`;
    }

    function replacementHistoryRatingValue(item) {
      const result = state.omdbRatings.get(item.group_id);
      return result && result.status === 'matched' && Number.isFinite(result.rating) ? result.rating : -1;
    }

    function replacementHistoryRatingCell(result) {
      if (!result) return '<span class="subtle">…</span>';
      if (result.status === 'pending') return '<span class="subtle">…</span>';
      if (result.status === 'matched' && Number.isFinite(result.rating)) return result.rating.toFixed(1);
      if (result.status === 'api_limited') return '<span class="subtle">limit</span>';
      return '<span class="subtle">—</span>';
    }

    async function fetchMissingOmdbRatings(items) {
      const missing = items.filter(item => !state.omdbRatings.has(item.group_id));
      if (!missing.length) return;
      missing.forEach(item => state.omdbRatings.set(item.group_id, { status: 'pending', rating: null }));
      try {
        const response = await fetch('/api/movies/omdb/ratings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            items: missing.map(item => ({
              key: item.group_id,
              title: item.title || '',
              year: item.year || null
            }))
          })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'IMDb rating lookup failed.');
        let limited = false;
        for (const result of (payload.items || [])) {
          if (!result || !result.key) continue;
          state.omdbRatings.set(result.key, result);
          if (result.status === 'api_limited') limited = true;
        }
        state.omdbStatus = limited ? 'IMDb limit reached. Cached ratings still show; new ratings retry later.' : '';
      } catch (error) {
        missing.forEach(item => state.omdbRatings.set(item.group_id, { status: 'error', rating: null }));
        state.omdbStatus = error.message || 'IMDb rating lookup failed.';
      }
      renderReplacementQueueDetail(state.results.movies.profile);
    }

    function groupedReplacementHistoryItems(items) {
      const groups = new Map();
      for (const item of items) {
        const historyTitleKey = item.history_title_key || item.title_key || item.title || '';
        const issueFamily = item.issue_family || 'weak_encode';
        const key = `${historyTitleKey}\\u0000${item.year || ''}\\u0000${issueFamily}`;
        const existing = groups.get(key);
        if (existing) {
          existing.count += 1;
          existing.item_ids.push(String(item.item_id || ''));
          existing.deleted_at = minIso(existing.deleted_at, item.deleted_at);
          existing.dismissed_at = maxIso(existing.dismissed_at, item.dismissed_at);
          existing.queued_at = minIso(existing.queued_at, item.queued_at);
          existing.completed_at = maxIso(existing.completed_at, item.completed_at);
          existing.status = mergeReplacementHistoryStatus(existing.status, item.status);
        } else {
          groups.set(key, {
            ...item,
            group_id: key,
            count: 1,
            item_ids: [String(item.item_id || '')],
            status: item.status || 'deleted'
          });
        }
      }
      return Array.from(groups.values());
    }

    function replacementHistoryStatusChip(status) {
      if (status === 'completed') return '<span class="chip safe">replaced</span>';
      if (status === 'dismissed') return '<span class="chip meta">deleted from queue</span>';
      if (status === 'mixed') return '<span class="chip meta">mixed history</span>';
      return '<span class="chip review">deleted</span>';
    }

    function mergeReplacementHistoryStatus(a, b) {
      if (a === b) return a;
      if (!a) return b || 'deleted';
      if (!b) return a;
      return 'mixed';
    }

    function replacementHistoryGroupActivityAt(item) {
      if (item.status === 'completed') return item.completed_at || item.deleted_at || item.queued_at || '';
      if (item.status === 'dismissed') return item.dismissed_at || item.deleted_at || item.queued_at || '';
      if (item.status === 'mixed') return maxIso(maxIso(item.completed_at, item.dismissed_at), item.deleted_at) || item.queued_at || '';
      return item.deleted_at || item.queued_at || '';
    }

    function replacementHistoryBaselineOrder(items) {
      const filter = state.replacementHistoryFilter;
      const sorted = [...items].sort((a, b) => {
        const aWhen = replacementHistoryGroupActivityAt(a);
        const bWhen = replacementHistoryGroupActivityAt(b);
        return aWhen.localeCompare(bWhen);
      });
      return filter === 'all' || filter === 'completed' || filter === 'dismissed' ? sorted.reverse() : sorted;
    }

    function minIso(a, b) {
      if (!a) return b || '';
      if (!b) return a || '';
      return a.localeCompare(b) <= 0 ? a : b;
    }

    function maxIso(a, b) {
      if (!a) return b || '';
      if (!b) return a || '';
      return a.localeCompare(b) >= 0 ? a : b;
    }

    function replacementHistoryFilterLabel(filter) {
      if (filter === 'completed') return 'Replaced';
      if (filter === 'dismissed') return 'Deleted From Queue';
      if (filter === 'all') return 'All Items';
      return 'Deleted, Waiting Replacement';
    }

    function renderReplacementQueueDetail(payload) {
      const queue = currentMovieReplacementQueue(payload);
      const queueItems = isMovieTriagePage() ? movieQueueItemsForFamily(payload, activeMovieTriageFamily()) : (queue?.items || []);
      const headingPrefix = isMovieTriagePage() ? `${activeMovieTriageFamilyLabel()} ` : '';
      const pending = queueItems.filter(item => item.status === 'pending');
      const allHistoryItems = queueItems.filter(item => ['deleted', 'dismissed', 'completed'].includes(item.status));
      const filteredHistoryItems = allHistoryItems.filter(item => {
        if (state.replacementHistoryFilter === 'all') return true;
        if (state.replacementHistoryFilter === 'dismissed') return item.status === 'dismissed';
        return state.replacementHistoryFilter === 'completed' ? item.status === 'completed' : item.status === 'deleted';
      });
      const source = sourceInput.value.trim() || queue?.source_root || '';
      const pendingRows = pending.length ? buildPendingReplacementTable(pending) : '';
      const hasHistory = allHistoryItems.length > 0;
      const filterButtons = hasHistory ? `
        <div class="page-nav">
          ${[
            ['deleted', 'Deleted, Awaiting Replacement'],
            ['completed', 'Replaced'],
            ['dismissed', 'Deleted From Queue'],
            ['all', 'All Items']
          ].map(([id, label]) => `<button class="filter-button replacement-history-filter ${state.replacementHistoryFilter === id ? 'active' : ''}" data-history-filter="${id}">${label}</button>`).join('')}
        </div>
      ` : '';
      const historyTable = filteredHistoryItems.length ? buildReplacementHistoryTable(filteredHistoryItems) : `<div class="empty">No ${escapeHtml(replacementHistoryFilterLabel(state.replacementHistoryFilter).toLowerCase())} items in the replacement queue.</div>`;
      detailPanel.innerHTML = `
        ${pendingRows ? `<div style="font-weight:600;margin:10px 0 6px">${escapeHtml(headingPrefix)}Pending Delete</div>${pendingRows}` : ''}
        ${hasHistory ? `<div style="font-weight:600;margin:10px 0 6px">${escapeHtml(headingPrefix)}Replacement History</div>${filterButtons}${historyTable}` : ''}
        ${!pendingRows && !hasHistory ? '<div class="empty">No items in the replacement queue.</div>' : ''}
      `;
      attachReplacementQueueDetailHandlers();
    }

    function buildMovieDashboard(payload) {
      if (!payload) return `<div class="empty">Run Movies / Dashboard to see the dashboard.</div>`;
      const histogram = payload.histogram || {};
      const total = histogram.movie_count ?? (payload.movies || []).length;

      function fmtSize(bytes) {
        if (!bytes) return '—';
        if (bytes >= 1e12) return (bytes / 1e12).toFixed(1) + ' TB';
        return (bytes / 1e9).toFixed(1) + ' GB';
      }
      function fmtHours(mins) {
        if (!mins) return '—';
        const h = Math.floor(mins / 60);
        const m = Math.round(mins % 60);
        return h ? `${h}h ${m}m` : `${m}m`;
      }
      function fmtVideoBitrate(kbps) {
        return kbps ? (kbps / 1000).toFixed(1) + ' Mbps' : '—';
      }
      function tierGroup(label) {
        if (label === 'reference') return 'Reference';
        if (label === 'meets_minimum') return 'Pass';
        if (label === 'needs_review') return 'Review';
        if (label === 'replacement_candidate') return 'Replace';
        return 'Other';
      }

      const avgVideoBitrate = histogram.video_bitrate_kbps?.mean;
      const avgAudioBitrate = histogram.audio_bitrate_kbps?.mean;
      const statsHtml = `
        <div class="dash-stats">
          <div class="metric"><strong>${total.toLocaleString()}</strong><span>movies</span></div>
          <div class="metric"><strong>${fmtSize(histogram.total_size_bytes)}</strong><span>total size</span></div>
          <div class="metric"><strong>${fmtHours(histogram.total_runtime_minutes)}</strong><span>total runtime</span></div>
          <div class="metric"><strong>${fmtVideoBitrate(avgVideoBitrate)}</strong><span>avg video bitrate</span></div>
          <div class="metric"><strong>${avgAudioBitrate ? Math.round(avgAudioBitrate).toLocaleString() + ' kbps' : '—'}</strong><span>avg audio bitrate</span></div>
        </div>
      `;

      const profileCounts = histogram.profile_counts || {};
      const qualityProfileCounts = histogram.quality_profile_counts || {};
      const queueItems = (currentMovieReplacementQueue(payload)?.items || []);
      const deletedAwaitingReplacementCount = queueItems.filter(item => item.status === 'deleted').length;
      const definitions = Array.isArray(payload.quality_profile_definitions) ? payload.quality_profile_definitions : [];
      const replacementCandidateDefinition = payload.replacement_candidate_definition || null;
      const replacementQueueCard = deletedAwaitingReplacementCount ? [[
        'deleted_awaiting_replacement',
        deletedAwaitingReplacementCount,
        {
          group: 'Action Based',
          name: 'Deleted, Awaiting Replacement',
          pctLabel: 'from Replacement Queue'
        }
      ]] : [];
      const actionCards = [
        ...replacementQueueCard,
        [
          'replacement_candidate',
          profileCounts.replacement_candidate || 0,
          replacementCandidateDefinition || {
            group: 'Action Based',
            name: 'Replacement Candidate',
            display_name: 'Replacement Candidate',
            summary: 'Quality profile at or below the configured cutoff and eligible for delete/replace triage.'
          }
        ],
        [
          'needs_review',
          profileCounts.needs_review || 0,
          {
            group: 'Action Based',
            name: 'Needs Review',
            summary: 'Low-confidence hygiene, subtitle-default, or packaging issues need manual attention.'
          }
        ],
      ];
      const actionCardsHtml = actionCards.map(([label, count, options]) => {
        const pct = total ? ((count / total) * 100).toFixed(1) : '0.0';
        const barWidth = total ? (count / total) * 100 : 0;
        const isEditable = label === 'replacement_candidate' && !!options?.fields;
        const inlineSummary = options?.summary || '';
        const definitionSummary = options?.rule_summary || '';
        const isEditorOpen = state.movieStandardsEditorLabel === label;
        return `
          <div class="profile-card">
            <div class="profile-card-head">
              <div>
                <div class="profile-card-group">${escapeHtml(options?.group || 'Action Based')}</div>
                <div class="profile-card-name">${escapeHtml(options?.display_name || options?.name || humanProfileLabel(label))}</div>
              </div>
              <div style="display:flex;gap:6px;align-items:center">
                ${count > 0 ? `<button class="secondary movie-profile-view-btn" data-profile-label="${escapeHtml(label)}" data-profile-type="action">View</button>` : ''}
                ${isEditable ? `<button class="secondary movie-profile-definition-toggle" data-profile-label="${escapeHtml(label)}">${isEditorOpen ? 'Close' : 'Edit'}</button>` : ''}
              </div>
            </div>
            <div class="profile-card-count">${count.toLocaleString()}</div>
            <div class="profile-card-pct">${escapeHtml(options?.pctLabel || `${pct}% of library`)}</div>
            ${inlineSummary ? `<div class="profile-card-band">${escapeHtml(inlineSummary)}</div>` : ''}
            ${definitionSummary ? `<div class="profile-card-definition">${escapeHtml(definitionSummary)}</div>` : ''}
            <div class="profile-card-bar"><span style="width:${barWidth}%"></span></div>
            ${isEditable && isEditorOpen ? buildMovieProfileDefinitionEditor(options) : ''}
          </div>
        `;
      }).join('');
      const qualityCards = definitions.map(definition => [definition.label, qualityProfileCounts[definition.label] || 0, definition]);
      const qualityCardsHtml = qualityCards.map(([label, count, options]) => {
        const pct = total ? ((count / total) * 100).toFixed(1) : '0.0';
        const barWidth = total ? (count / total) * 100 : 0;
        const isEditable = !!options;
        const inlineSummary = options?.summary || '';
        const definitionSummary = options?.rule_summary || '';
        const inheritedSummary = options?.inherits_summary || '';
        const isEditorOpen = state.movieStandardsEditorLabel === label;
        return `
          <div class="profile-card">
            <div class="profile-card-head">
              <div>
                <div class="profile-card-group">${escapeHtml(options?.group || 'Quality Profile')}</div>
                <div class="profile-card-name">${escapeHtml(options?.display_name || options?.name || humanProfileLabel(label))}</div>
              </div>
              <div style="display:flex;gap:6px;align-items:center">
                ${count > 0 ? `<button class="secondary movie-profile-view-btn" data-profile-label="${escapeHtml(label)}" data-profile-type="quality">View</button>` : ''}
                ${isEditable ? `<button class="secondary movie-profile-definition-toggle" data-profile-label="${escapeHtml(label)}">${isEditorOpen ? 'Close' : 'Edit'}</button>` : ''}
              </div>
            </div>
            <div class="profile-card-count">${count.toLocaleString()}</div>
            <div class="profile-card-pct">${escapeHtml(options?.pctLabel || `${pct}% of library`)}</div>
            ${inlineSummary ? `<div class="profile-card-band">${escapeHtml(inlineSummary)}</div>` : ''}
            ${inheritedSummary ? `<div class="profile-card-band">${escapeHtml(inheritedSummary)}</div>` : ''}
            ${definitionSummary ? `<div class="profile-card-definition">${escapeHtml(definitionSummary)}</div>` : ''}
            <div class="profile-card-bar"><span style="width:${barWidth}%"></span></div>
            ${isEditable && isEditorOpen ? buildMovieProfileDefinitionEditor(options) : ''}
          </div>
        `;
      }).join('');

      const resCounts = histogram.resolution_counts || {};
      const resOrder = ['2160p', '1080p', '720p', 'sd', 'unknown'];
      const resMax = Math.max(...Object.values(resCounts), 1);
      const resBarsHtml = resOrder.filter(r => resCounts[r]).map(r => `
        <div class="bar-row">
          <span>${escapeHtml(r)}</span>
          <div class="bar"><span style="width:${(resCounts[r] / resMax) * 100}%"></span></div>
          <strong>${resCounts[r]}</strong>
        </div>
      `).join('');

      return `
        ${statsHtml}
        <div class="dash-section-label">Action Based</div>
        <div class="profile-grid">${actionCardsHtml || '<div class="subtle">No action data.</div>'}</div>
        <div class="dash-section-label">Quality Profile</div>
        <div class="profile-grid">${qualityCardsHtml || '<div class="subtle">No quality profile data.</div>'}</div>
        <div class="dash-section-label">Resolution Breakdown</div>
        <div class="dash-res-bars bars">${resBarsHtml || '<div class="subtle">No resolution data.</div>'}</div>
      `;
    }

    function buildMovieProfileInspector(payload, label, profileType) {
      const movies = payload.movies || [];
      const definitions = Array.isArray(payload.quality_profile_definitions) ? payload.quality_profile_definitions : [];
      const definition = definitions.find(d => d.label === label);
      const displayName = definition?.display_name || humanProfileLabel(label);

      if (!movies.length) {
        return `
          <div style="margin-bottom:12px">
            <button class="secondary movie-profile-inspector-back">← Back to Dashboard</button>
            <span style="margin-left:12px;font-weight:700">${escapeHtml(displayName)}</span>
          </div>
          <div class="empty">Run a fresh Movies / Dashboard scan to browse titles in this profile.</div>
        `;
      }

      function parseStem(item) {
        const stem = (item.path || '').split('/').pop().replace(/\.[^.]+$/, '');
        const m = stem.match(/^(.+?)\s*\((\d{4})\)/);
        return m ? { title: m[1].trim(), year: parseInt(m[2], 10) } : { title: stem, year: null };
      }

      const filtered = movies
        .filter(m => profileType === 'action' ? m.profile?.label === label : m.profile?.quality_label === label)
        .map(m => ({ ...m, _parsed: parseStem(m), _normAudio: normalizeAudioBitrate(m.facts) }));

      const sort = state.movieProfileInspectorSort;
      const mult = sort.dir === 'asc' ? 1 : -1;
      const RES_RANK = { '2160p': 4, '1080p': 3, '720p': 2, 'sd': 1 };
      function normSortVal(n) { return n?.lossless ? 999999 : (n?.nearTransparent ? n.threshold : (n?.normalized || 0)); }
      const sorted = filtered.slice().sort((a, b) => {
        if (sort.col === 'year') return mult * ((a._parsed.year || 0) - (b._parsed.year || 0));
        if (sort.col === 'resolution') return mult * ((RES_RANK[a.facts?.resolution_bucket] || 0) - (RES_RANK[b.facts?.resolution_bucket] || 0));
        if (sort.col === 'codec') return mult * (a.facts?.audio_format_family || '').localeCompare(b.facts?.audio_format_family || '');
        if (sort.col === 'channels') return mult * ((a.facts?.audio_channels || 0) - (b.facts?.audio_channels || 0));
        if (sort.col === 'video_bitrate') return mult * ((a.facts?.video_bitrate_kbps || 0) - (b.facts?.video_bitrate_kbps || 0));
        if (sort.col === 'audio_bitrate') return mult * ((a.facts?.audio_bitrate_kbps || 0) - (b.facts?.audio_bitrate_kbps || 0));
        if (sort.col === 'norm_bitrate') return mult * (normSortVal(a._normAudio) - normSortVal(b._normAudio));
        if (sort.col === 'file_size') return mult * ((a.facts?.file_size_bytes || 0) - (b.facts?.file_size_bytes || 0));
        return mult * a._parsed.title.localeCompare(b._parsed.title, undefined, { sensitivity: 'base' });
      });

      function sortTh(col, label) {
        const active = sort.col === col;
        const ind = active ? (sort.dir === 'asc' ? '↑' : '↓') : '↕';
        return `<th class="sortable-th movie-inspector-th" data-sort-col="${col}">${escapeHtml(label)}<span class="sort-ind${active ? ' on' : ''}">${ind}</span></th>`;
      }

      const rows = sorted.map(item => {
        const title = item._parsed.title;
        const year = item._parsed.year ? escapeHtml(String(item._parsed.year)) : '<span class="subtle">—</span>';
        const res = item.facts?.resolution_bucket ? escapeHtml(item.facts.resolution_bucket) : '<span class="subtle">—</span>';
        const codec = item.facts?.audio_summary ? escapeHtml(item.facts.audio_summary) : (item.facts?.audio_format_family ? escapeHtml(item.facts.audio_format_family.toUpperCase()) : '<span class="subtle">—</span>');
        const ch = item.facts?.audio_channels != null ? String(item.facts.audio_channels) : '<span class="subtle">—</span>';
        const abr = fmtAudioBitrate(item.facts);
        const nabr = fmtNormAudioBitrate(item.facts);
        const vbr = item.facts?.video_bitrate_kbps ? `${Math.round(item.facts.video_bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
        const size = item.facts?.file_size_bytes ? fmtFileSize(item.facts.file_size_bytes) : '<span class="subtle">—</span>';
        return `<tr><td>${escapeHtml(title)}</td><td>${year}</td><td>${res}</td><td>${codec}</td><td>${ch}</td><td>${abr}</td><td>${nabr}</td><td>${vbr}</td><td>${size}</td></tr>`;
      }).join('');

      return `
        <div style="margin-bottom:12px;display:flex;align-items:center;gap:16px">
          <button class="secondary movie-profile-inspector-back">← Back to Dashboard</button>
          <span style="font-weight:700">${escapeHtml(displayName)}</span>
          <span class="subtle">${filtered.length.toLocaleString()} title${filtered.length === 1 ? '' : 's'}</span>
        </div>
        <table style="width:100%;border-collapse:collapse;table-layout:fixed" class="subtitle-table">
          <colgroup><col style="width:26%"><col style="width:6%"><col style="width:7%"><col style="width:13%"><col style="width:4%"><col style="width:9%"><col style="width:10%"><col style="width:10%"><col style="width:8%"></colgroup>
          <thead><tr>
            ${sortTh('title', 'Title')}
            ${sortTh('year', 'Year')}
            ${sortTh('resolution', 'Resolution')}
            ${sortTh('codec', 'Codec')}
            ${sortTh('channels', 'Ch')}
            ${sortTh('audio_bitrate', 'Raw Audio')}
            ${sortTh('norm_bitrate', 'Norm. Audio')}
            ${sortTh('video_bitrate', 'Video Bitrate')}
            ${sortTh('file_size', 'File Size')}
          </tr></thead>
          <tbody>${rows || '<tr><td colspan="9" class="subtle" style="text-align:center;padding:16px">No titles in this profile.</td></tr>'}</tbody>
        </table>
      `;
    }

    function attachMovieProfileInspectorHandlers(payload) {
      document.querySelector('.movie-profile-inspector-back')?.addEventListener('click', () => {
        state.movieProfileInspectorLabel = '';
        state.movieProfileInspectorType = '';
        renderMovieLibrary(payload);
      });
      document.querySelectorAll('.movie-inspector-th[data-sort-col]').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.sortCol;
          if (state.movieProfileInspectorSort.col === col) {
            state.movieProfileInspectorSort.dir = state.movieProfileInspectorSort.dir === 'asc' ? 'desc' : 'asc';
          } else {
            state.movieProfileInspectorSort = { col, dir: 'asc' };
          }
          renderMovieLibrary(payload);
        });
      });
    }

    function movieProfileDefinitionDraft(label) {
      const draft = state.movieStandardsPendingDraft;
      return draft && draft.label === label ? draft.values : null;
    }

    function buildMovieProfileDefinitionEditor(definition) {
      const draftValues = movieProfileDefinitionDraft(definition.label);
      const isBusy = !!(state.movieStandardsSaveBusy && draftValues);
      const rows = (definition.fields || []).map(field => {
        const hasDraftValue = !!draftValues && Object.prototype.hasOwnProperty.call(draftValues, field.key);
        const fieldValue = hasDraftValue ? draftValues[field.key] : field.value;
        const disabledAttr = isBusy ? ' disabled' : '';
        if (field.type === 'text') {
          return `
            <div class="profile-card-editor-row">
              <label for="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label>
              <input id="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}" data-profile-field="${escapeHtml(field.key)}" type="text" value="${escapeHtml(fieldValue)}"${disabledAttr}>
            </div>
          `;
        }
        if (field.type === 'number') {
          return `
            <div class="profile-card-editor-row">
              <label for="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label>
              <input id="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}" data-profile-field="${escapeHtml(field.key)}" type="number" value="${escapeHtml(fieldValue)}"${disabledAttr}>
            </div>
          `;
        }
        if (field.type === 'csv') {
          return `
            <div class="profile-card-editor-row">
              <label for="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label>
              <input id="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}" data-profile-field="${escapeHtml(field.key)}" type="text" value="${escapeHtml(fieldValue)}"${disabledAttr}>
            </div>
          `;
        }
        if (field.type === 'select') {
          return `
            <div class="profile-card-editor-row">
              <label for="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}">${escapeHtml(field.label)}</label>
              <select id="movie-profile-field-${escapeHtml(definition.label)}-${escapeHtml(field.key)}" data-profile-field="${escapeHtml(field.key)}"${disabledAttr}>
                ${(field.options || []).map(option => `<option value="${escapeHtml(option.value)}" ${String(option.value) === String(fieldValue) ? 'selected' : ''}>${escapeHtml(option.label)}</option>`).join('')}
              </select>
            </div>
          `;
        }
        if (field.type === 'toggle') {
          return `
            <div class="profile-card-editor-row">
              <label class="profile-card-toggle"><input data-profile-field="${escapeHtml(field.key)}" type="checkbox" ${fieldValue ? 'checked' : ''}${disabledAttr}>${escapeHtml(field.label)}</label>
            </div>
          `;
        }
        if (field.type === 'checklist') {
          return `
            <div class="profile-card-editor-row">
              <label>${escapeHtml(field.label)}</label>
              <div class="profile-card-checklist">
                ${(field.options || []).map(option => {
                  const checked = Array.isArray(fieldValue) && fieldValue.includes(option.value);
                  return `<label><input data-profile-field="${escapeHtml(field.key)}" type="checkbox" value="${escapeHtml(option.value)}" ${checked ? 'checked' : ''}${disabledAttr}>${escapeHtml(option.label)}</label>`;
                }).join('')}
              </div>
            </div>
          `;
        }
        return '';
      }).join('');
      return `
        <div class="profile-card-editor" data-profile-editor="${escapeHtml(definition.label)}">
          ${rows}
          <div class="profile-card-editor-actions">
            <button class="primary movie-profile-definition-save" data-profile-label="${escapeHtml(definition.label)}" ${state.movieStandardsSaveBusy ? 'disabled' : ''}>Save</button>
            <button class="secondary movie-profile-definition-cancel" data-profile-label="${escapeHtml(definition.label)}" ${state.movieStandardsSaveBusy ? 'disabled' : ''}>Cancel</button>
            <span class="subtle">Saves to repo-local <span class="mono">movie_standards.json</span> and reruns the dashboard.</span>
          </div>
        </div>
      `;
    }

    function movieProfileEditorValues(label) {
      const editor = document.querySelector(`[data-profile-editor="${label}"]`);
      if (!editor) return {};
      const values = {};
      editor.querySelectorAll('[data-profile-field]').forEach(input => {
        const key = input.dataset.profileField;
        if (!key) return;
        if (input.type === 'checkbox') {
          if (input.value && input.value !== 'on') {
            if (!Object.prototype.hasOwnProperty.call(values, key)) values[key] = [];
            if (input.checked) values[key].push(input.value);
          } else {
            values[key] = !!input.checked;
          }
          return;
        }
        values[key] = input.value;
      });
      return values;
    }

    async function saveMovieProfileDefinition(label) {
      if (!label || state.movieStandardsSaveBusy || _activeRunController) return;
      const source = sourceInput.value.trim();
      const currentPayload = state.results.movies.profile || restoreCachedMovieDashboard(source);
      const revision = currentPayload?.movie_standards_revision || '';
      const editorValues = movieProfileEditorValues(label);
      state.movieStandardsPendingDraft = { label, values: editorValues };
      state.movieStandardsSaveBusy = true;
      setStatus(`Saving ${humanProfileLabel(label)} definition…`, 'running');
      renderMovieLibrary(currentPayload);
      try {
        const response = await fetch('/api/movies/standards/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label, revision, values: editorValues })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Standards save failed.');
        if (state.results.movies.profile) {
          state.results.movies.profile.movie_standards = result.movie_standards;
          state.results.movies.profile.movie_standards_revision = result.movie_standards_revision || '';
          state.results.movies.profile.quality_profile_definitions = result.quality_profile_definitions || [];
          state.results.movies.profile.replacement_candidate_definition = result.replacement_candidate_definition || null;
          cacheMovieDashboard(state.results.movies.profile);
        }
        state.movieStandardsPendingDraft = null;
        state.movieStandardsEditorLabel = '';
        setStatus(`Saved ${humanProfileLabel(label)} definition.`, 'idle');
        renderMovieLibrary(state.results.movies.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        state.movieStandardsSaveBusy = false;
        if (state.page === 'library') {
          renderMovieLibrary(state.results.movies.profile || restoreCachedMovieDashboard(source));
        }
      }
    }

    function renderJunkDeleteHistory() {
      const items = state.junkDeleteHistory;
      if (!items.length) {
        detailPanel.innerHTML = '<div class="empty">No files deleted yet this session.</div>';
        return;
      }
      const rows = items.map(item => {
        const ext = (item.file_name || '').split('.').pop().toLowerCase();
        const isDoc = ext === 'txt' || ext === 'html' || ext === 'htm';
        const time = item.deleted_at ? new Date(item.deleted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
        return `<tr>
          <td><span class="chip ${isDoc ? 'meta' : 'review'}" style="font-size:0.7em;padding:2px 7px">${isDoc ? 'Doc' : 'Vid'}</span></td>
          <td style="word-break:break-word;overflow-wrap:anywhere">${escapeHtml(item.file_name || '')}</td>
          <td style="white-space:nowrap;color:var(--muted);font-size:0.85em">${escapeHtml(item.file_size_label || '')}</td>
          <td style="white-space:nowrap;color:var(--muted);font-size:0.85em">${escapeHtml(time)}</td>
        </tr>`;
      }).join('');
      detailPanel.innerHTML = `
        <div style="font-weight:600;margin:10px 0 6px">Deleted This Session</div>
        <table style="width:100%;border-collapse:collapse;font-size:0.9em">
          <thead><tr>
            <th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border);width:52px">Type</th>
            <th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border)">File</th>
            <th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border);width:80px">Size</th>
            <th style="text-align:left;padding:4px 6px;border-bottom:1px solid var(--border);width:60px">Time</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    function renderMovieJunk(payload) {
      mainTagline.textContent = 'High-confidence junk videos and spam sidecar files ready for deletion.';
      renderMetrics(buildMovieJunkMetrics(payload));
      renderBars(buildMovieJunkBars(payload));
      renderFilters([
        ['all', 'All'],
        ['high', 'High'],
        ['review', 'Review']
      ]);
      if (!payload) {
        mainContent.innerHTML = `<div class="empty">Run Movies / Delete Junk &amp; Spam Files to build a review list.</div>`;
        renderJunkDeleteHistory();
        return;
      }
      renderJunkDeleteHistory();
      const rows = filteredMovieJunk(payload).map(item => {
        const path = item.path || '';
        const checked = state.selectedJunkPaths.has(path) ? 'checked' : '';
        const ext = (item.file_name || '').split('.').pop().toLowerCase();
        const isDoc = ext === 'txt' || ext === 'html' || ext === 'htm';
        return `
          <tr>
            <td><input type="checkbox" class="junk-select" data-path="${encodeURIComponent(path)}" ${checked}></td>
            <td><span class="chip ${isDoc ? 'meta' : 'review'}" style="font-size:0.7em;padding:2px 7px;margin-right:5px">${isDoc ? 'Doc' : 'Vid'}</span>${escapeHtml(item.file_name || '')}</td>
            <td><div class="mono">${escapeHtml(item.relative_path || item.path || '')}</div></td>
            <td>${escapeHtml(item.file_size_label || '')}</td>
          </tr>
        `;
      }).join('');
      const selectedCount = selectedVisibleJunkCount(payload);
      mainContent.innerHTML = `
        <div class="junk-actions">
          <button class="secondary" id="selectAllJunkButton">Select all</button>
          <button class="secondary" id="deselectAllJunkButton" ${selectedCount ? '' : 'disabled'}>Deselect all</button>
          <button class="danger" id="deleteJunkButton" ${selectedCount ? '' : 'disabled'}>Delete selected</button>
          <span class="subtle">${selectedCount} selected</span>
        </div>
        <div class="table-wrap">
          <table class="junk-table">
            <thead><tr><th></th><th>File Name</th><th>File Path</th><th>File Size</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="4" class="subtle">No junk candidates for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;
      attachMovieJunkHandlers(payload);
    }

    function selectedVisibleJunkCount(payload) {
      return filteredMovieJunk(payload).filter(item => state.selectedJunkPaths.has(item.path || '')).length;
    }

    function attachMovieJunkHandlers(payload) {
      document.querySelectorAll('.junk-select').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          const path = decodeURIComponent(checkbox.dataset.path);
          if (checkbox.checked) state.selectedJunkPaths.add(path);
          else state.selectedJunkPaths.delete(path);
          renderMovieJunk(payload);
        });
      });
      const selectAllButton = document.getElementById('selectAllJunkButton');
      if (selectAllButton) {
        selectAllButton.addEventListener('click', () => {
          filteredMovieJunk(payload).forEach(item => state.selectedJunkPaths.add(item.path || ''));
          renderMovieJunk(payload);
        });
      }
      const deselectAllButton = document.getElementById('deselectAllJunkButton');
      if (deselectAllButton) {
        deselectAllButton.addEventListener('click', () => {
          filteredMovieJunk(payload).forEach(item => state.selectedJunkPaths.delete(item.path || ''));
          renderMovieJunk(payload);
        });
      }
      const deleteButton = document.getElementById('deleteJunkButton');
      if (deleteButton) deleteButton.addEventListener('click', deleteSelectedJunk);
    }

    async function deleteSelectedJunk() {
      const source = sourceInput.value.trim();
      const paths = Array.from(state.selectedJunkPaths);
      if (!source || !paths.length) return;
      const message = `Delete ${paths.length} selected junk file${paths.length === 1 ? '' : 's'}? This cannot be undone.`;
      if (!window.confirm(message)) return;
      statusText.textContent = `Deleting ${paths.length} junk file${paths.length === 1 ? '' : 's'}…`;
      try {
        const response = await fetch('/api/movies/junk/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, paths })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Delete failed.');
        const deletedSet = new Set(payload.deleted || []);
        const deletedAt = new Date().toISOString();
        (state.results.movies.junk?.junk || []).forEach(item => {
          if (deletedSet.has(item.path || '')) {
            state.junkDeleteHistory.unshift({ ...item, deleted_at: deletedAt });
          }
        });
        state.results.movies.junk = removeDeletedJunk(state.results.movies.junk, payload.deleted || []);
        state.selectedJunkPaths.clear();
        const skipped = payload.skipped?.length || 0;
        statusText.textContent = `Deleted ${payload.deleted.length} file${payload.deleted.length === 1 ? '' : 's'}${skipped ? `; skipped ${skipped}` : ''}.`;
        renderMovieJunk(state.results.movies.junk);
      } catch (error) {
        statusText.textContent = error.message;
      }
    }

    function removeDeletedJunk(payload, deletedPaths) {
      if (!payload) return payload;
      const deleted = new Set(deletedPaths);
      return { ...payload, junk: (payload.junk || []).filter(item => !deleted.has(item.path || '')) };
    }

    function isStrictWeakMovie(item) {
      return !!item?.profile?.weak_candidate;
    }

    function strictWeakMovies(payload) {
      return (payload?.movies || []).filter(isStrictWeakMovie);
    }

    function movieStandardsWorkflowItems(payload) {
      return (payload?.movies || []).filter(item => {
        const label = item?.profile?.label || '';
        return item?.profile?.weak_candidate || label === 'needs_review';
      });
    }

    function isMovieTriagePage() {
      return state.page === 'quality' || (state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio');
    }

    function movieAudioPackagingIssueCode(item) {
      const diagnostics = item?.profile?.diagnostics || [];
      if (diagnostics.some(d => d?.code === 'default_non_english_audio_with_weak_english')) return 'default_non_english_audio_with_weak_english';
      if (diagnostics.some(d => d?.code === 'default_non_english_audio')) return 'default_non_english_audio';
      return '';
    }

    function movieSubtitleSetupResult(item) {
      return (item?.profile?.domain_results || []).find(result => result?.domain === 'subtitle_setup') || null;
    }

    function movieSubtitleReadinessIssueCode(item) {
      return movieSubtitleSetupResult(item)?.code || '';
    }

    function movieDefaultSubtitleStream(item) {
      const streams = item?.facts?.subtitle_streams || [];
      return streams.find(stream => stream?.is_default) || streams[0] || null;
    }

    function subtitleStreamLanguage(stream) {
      const value = String(stream?.language || '').toLowerCase();
      if (['eng', 'en', 'english'].includes(value)) return 'english';
      if (['ita', 'it', 'italian'].includes(value)) return 'italian';
      return value;
    }

    function isEnglishSubtitleStream(stream) {
      return subtitleStreamLanguage(stream) === 'english';
    }

    function chooseBestEnglishSubtitleStream(item, options = {}) {
      const streams = item?.facts?.subtitle_streams || [];
      const forcedOnly = !!options.forcedOnly;
      const matching = streams.filter(stream => isEnglishSubtitleStream(stream) && (stream?.is_forced || !forcedOnly));
      if (!matching.length) return null;
      const currentDefault = movieDefaultSubtitleStream(item);
      if (currentDefault && matching.includes(currentDefault)) return currentDefault;
      return matching[0];
    }

    function itemDefaultAudioLanguage(item) {
      return audioStreamLanguage(movieDefaultAudioStream(item)) || '';
    }

    function movieSubtitleReadinessRepairTarget(item) {
      const forced = chooseBestEnglishSubtitleStream(item, { forcedOnly: true });
      if (forced) return forced;
      if (!['', 'english'].includes(itemDefaultAudioLanguage(item))) {
        return chooseBestEnglishSubtitleStream(item);
      }
      return null;
    }

    function movieSubtitleReadinessIsRepairable(item) {
      const issueCode = movieSubtitleReadinessIssueCode(item);
      if (!issueCode) return false;
      if (!String(item?.path || '').toLowerCase().endsWith('.mkv')) return false;
      if (!Array.isArray(item?.facts?.subtitle_streams) || !item.facts.subtitle_streams.length) return false;
      if (issueCode === 'missing_default_english_subtitle') return false;
      if (issueCode === 'multiple_default_subtitles') return !!movieSubtitleReadinessRepairTarget(item) || itemDefaultAudioLanguage(item) === 'english';
      if (['english_forced_not_default', 'wrong_default_forced_subtitle', 'wrong_default_subtitle_language'].includes(issueCode)) {
        return !!movieSubtitleReadinessRepairTarget(item);
      }
      if (issueCode === 'unnecessary_default_subtitle') return true;
      return false;
    }

    function subtitleReadinessMovies(payload) {
      return (payload?.movies || []).filter(item => {
        const result = movieSubtitleSetupResult(item);
        return result && result.status !== 'pass';
      });
    }

    function repairableSubtitleReadinessMovies(payload) {
      return subtitleReadinessMovies(payload).filter(item => movieSubtitleReadinessIsRepairable(item));
    }

    function reviewOnlySubtitleReadinessMovies(payload) {
      return subtitleReadinessMovies(payload).filter(item => !movieSubtitleReadinessIsRepairable(item));
    }

    function filteredSubtitleReadinessMovies(payload) {
      const items = repairableSubtitleReadinessMovies(payload);
      if (state.filter === 'forced_english') {
        return items.filter(item => ['english_forced_not_default', 'wrong_default_forced_subtitle'].includes(movieSubtitleReadinessIssueCode(item)));
      }
      if (state.filter === 'non_english_audio') {
        return items.filter(item => ['wrong_default_subtitle_language'].includes(movieSubtitleReadinessIssueCode(item)));
      }
      if (state.filter === 'clear_default') {
        return items.filter(item => ['unnecessary_default_subtitle', 'multiple_default_subtitles'].includes(movieSubtitleReadinessIssueCode(item)));
      }
      return items;
    }

    function humanSubtitleReadinessIssueLabel(code) {
      const labels = {
        english_forced_not_default: 'forced English exists but is not default',
        wrong_default_forced_subtitle: 'wrong subtitle is default instead of forced English',
        missing_default_english_subtitle: 'non-English audio but no default English subtitle',
        wrong_default_subtitle_language: 'non-English audio but default subtitle is not English',
        unnecessary_default_subtitle: 'English audio should default to no subtitles',
        multiple_default_subtitles: 'multiple subtitle streams are default'
      };
      return labels[code] || code.replaceAll('_', ' ');
    }

    function describeSubtitleStream(stream) {
      if (!stream) return '<span class="subtle">—</span>';
      const language = subtitleStreamLanguage(stream);
      const parts = [
        language ? language.charAt(0).toUpperCase() + language.slice(1) : 'Unknown',
        stream?.is_forced ? 'forced' : null,
        stream?.title || null
      ].filter(Boolean);
      return escapeHtml(parts.join(' · '));
    }

    function itemSubtitleTargetSummary(item, options = {}) {
      return describeSubtitleStream(chooseBestEnglishSubtitleStream(item, options));
    }

    function subtitleRepairStatusChip(item) {
      return movieSubtitleReadinessIsRepairable(item)
        ? '<span class="chip meta">repairable</span>'
        : '<span class="chip review">review only</span>';
    }

    function audioPackagingMovies(payload) {
      return (payload?.movies || []).filter(item => !!movieAudioPackagingIssueCode(item));
    }

    function filteredAudioPackagingMovies(payload) {
      const items = audioPackagingMovies(payload);
      if (state.filter === 'weak_english') {
        return items.filter(item => movieAudioPackagingIssueCode(item) === 'default_non_english_audio_with_weak_english');
      }
      if (state.filter === 'wrong_default') {
        return items.filter(item => movieAudioPackagingIssueCode(item) === 'default_non_english_audio');
      }
      return items;
    }

    function movieDefaultAudioStream(item) {
      const streams = item?.facts?.audio_streams || [];
      return streams.find(stream => stream?.is_default) || streams[0] || null;
    }

    function movieBestEnglishAudioStream(item) {
      const streams = (item?.facts?.audio_streams || []).filter(stream => audioStreamLanguage(stream) === 'english');
      if (!streams.length) return null;
      return [...streams].sort((a, b) => {
        const ach = a?.channels || 0;
        const bch = b?.channels || 0;
        if (bch !== ach) return bch - ach;
        const abr = a?.bitrate_kbps || 0;
        const bbr = b?.bitrate_kbps || 0;
        return bbr - abr;
      })[0];
    }

    function audioStreamLanguage(stream) {
      const value = String(stream?.language || '').toLowerCase();
      if (['eng', 'en', 'english'].includes(value)) return 'english';
      if (['ita', 'it', 'italian'].includes(value)) return 'italian';
      return value;
    }

    function describeAudioStream(stream) {
      if (!stream) return '<span class="subtle">—</span>';
      const language = audioStreamLanguage(stream);
      const parts = [
        language ? language.charAt(0).toUpperCase() + language.slice(1) : 'Unknown',
        describeAudioFormat(stream),
        stream.bitrate_kbps ? `${Math.round(stream.bitrate_kbps).toLocaleString()} kbps` : null
      ].filter(Boolean);
      return escapeHtml(parts.join(' · '));
    }

    function audioChannelLayout(channels) {
      if (channels === null || channels === undefined) return '';
      if (channels === 1) return 'Mono';
      if (channels === 2) return '2.0';
      if (channels === 6) return '5.1';
      if (channels === 8) return '7.1';
      return `${channels}ch`;
    }

    function audioImmersiveExtension(profile, title = '') {
      const combined = `${String(profile || '').toLowerCase()} ${String(title || '').toLowerCase()}`;
      if (combined.includes('atmos') || combined.includes('dolby atmos')) return 'Atmos';
      if (combined.includes('dts:x') || combined.includes('dts-x') || combined.includes('dtsx')) return 'DTS:X';
      return '';
    }

    function audioCodecDisplayName(codec, profile = '') {
      const codecText = String(codec || '').toLowerCase();
      const profileText = String(profile || '').toLowerCase();
      if (codecText === 'aac') return 'AAC';
      if (codecText === 'ac3') return 'Dolby Digital';
      if (codecText === 'eac3') return 'Dolby Digital Plus';
      if (codecText === 'truehd') return 'Dolby TrueHD';
      if (codecText === 'dts') {
        if (profileText.includes('master audio') || /\bma\b/.test(profileText)) return 'DTS-HD MA';
        if (profileText.includes('high resolution') || /\bhra\b/.test(profileText)) return 'DTS-HD HRA';
        return 'DTS';
      }
      if (codecText === 'flac') return 'FLAC';
      if (codecText.startsWith('pcm')) return 'PCM';
      if (codecText === 'opus') return 'Opus';
      if (codecText === 'mp3') return 'MP3';
      return codecText ? codecText.toUpperCase() : '';
    }

    function describeAudioFormat(stream) {
      if (!stream) return '';
      const parts = [
        audioCodecDisplayName(stream.codec, stream.profile),
        audioChannelLayout(stream.channels)
      ].filter(Boolean);
      const immersive = audioImmersiveExtension(stream.profile, stream.title);
      const summary = parts.join(' ');
      return immersive ? `${summary} ${immersive}`.trim() : summary;
    }

    function selectedVisibleReplacementCount(payload, items) {
      return selectableVisibleReplacementItems(payload, items).filter(item => state.selectedReplacementPaths.has(item.path)).length;
    }

    function selectableVisibleReplacementItems(payload, items) {
      if (state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio') {
        return items.filter(item => item.path && movieMatchesActiveTriageFamily(item));
      }
      return items.filter(item => item.path && movieMatchesActiveTriageFamily(item) && !replacementQueueItemForPath(payload, item.path));
    }

    function selectedVisibleSubtitleRepairCount(payload, items) {
      return selectableVisibleSubtitleRepairItems(payload, items).filter(item => state.selectedReplacementPaths.has(item.path)).length;
    }

    function selectableVisibleSubtitleRepairItems(payload, items) {
      return items.filter(item => item.path && movieSubtitleReadinessIsRepairable(item));
    }

    function movieMatchesActiveTriageFamily(item) {
      if (state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio') return !!movieAudioPackagingIssueCode(item);
      return isStrictWeakMovie(item);
    }

    function rerenderActiveMovieTriagePage(payload) {
      if (state.page === 'fix_defaults') renderMovieFixDefaults(payload);
      else renderMovieQuality(payload);
    }

    function movieAudioFixSelectionLocked() {
      return state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio' && state.movieAudioFixBusy;
    }

    function movieSubtitleFixSelectionLocked() {
      return state.page === 'fix_defaults' && state.fixDefaultsTab === 'subtitle' && state.movieSubtitleFixBusy;
    }

    function attachMovieReplacementHandlers(payload, items) {
      const selectableItems = selectableVisibleReplacementItems(payload, items);
      document.querySelectorAll('.replacement-select').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          if (movieAudioFixSelectionLocked()) {
            checkbox.checked = state.selectedReplacementPaths.has(decodeURIComponent(checkbox.dataset.path));
            return;
          }
          const path = decodeURIComponent(checkbox.dataset.path);
          if (checkbox.checked) state.selectedReplacementPaths.add(path);
          else state.selectedReplacementPaths.delete(path);
          rerenderActiveMovieTriagePage(payload);
          renderReplacementQueueDetail(payload);
        });
      });
      const toggleAllButton = document.getElementById('toggleAllReplacementButton');
      if (toggleAllButton) {
        toggleAllButton.addEventListener('click', () => {
          if (movieAudioFixSelectionLocked()) return;
          const selectedCount = selectedVisibleReplacementCount(payload, selectableItems);
          const allVisibleSelected = selectableItems.length > 0 && selectedCount === selectableItems.length;
          selectableItems.forEach(item => {
            if (!item.path) return;
            if (allVisibleSelected) state.selectedReplacementPaths.delete(item.path);
            else state.selectedReplacementPaths.add(item.path);
          });
          rerenderActiveMovieTriagePage(payload);
          renderReplacementQueueDetail(payload);
        });
      }
      const fixButton = document.getElementById('fixSelectedAudioButton');
      if (fixButton) fixButton.addEventListener('click', () => fixSelectedAudioDefaults());
      const fixAndDropButton = document.getElementById('fixSelectedAudioAndDropForeignButton');
      if (fixAndDropButton) fixAndDropButton.addEventListener('click', () => fixSelectedAudioDefaults({ dropForeignAudio: true }));
      const fileButton = document.getElementById('deleteSelectedFilesButton');
      if (fileButton) fileButton.addEventListener('click', () => deleteSelectedFiles());
      document.querySelectorAll('.sortable-th').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.sortCol;
          if (state.qualitySort.col === col) {
            state.qualitySort.dir = state.qualitySort.dir === 'asc' ? 'desc' : 'asc';
          } else {
            state.qualitySort = { col, dir: 'asc' };
          }
          renderMovieQuality(payload);
          renderReplacementQueueDetail(payload);
        });
      });
    }

    function attachMovieSubtitleReadinessHandlers(payload, items) {
      const selectableItems = selectableVisibleSubtitleRepairItems(payload, items);
      document.querySelectorAll('.subtitle-repair-select').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          if (movieSubtitleFixSelectionLocked()) {
            checkbox.checked = state.selectedReplacementPaths.has(decodeURIComponent(checkbox.dataset.path));
            return;
          }
          const path = decodeURIComponent(checkbox.dataset.path);
          if (checkbox.checked) state.selectedReplacementPaths.add(path);
          else state.selectedReplacementPaths.delete(path);
          renderMovieFixDefaults(payload);
        });
      });
      const toggleButton = document.getElementById('toggleSubtitleRepairButton');
      if (toggleButton) {
        toggleButton.addEventListener('click', () => {
          if (movieSubtitleFixSelectionLocked()) return;
          const selectedCount = selectedVisibleSubtitleRepairCount(payload, selectableItems);
          const allVisibleSelected = selectableItems.length > 0 && selectedCount === selectableItems.length;
          selectableItems.forEach(item => {
            if (!item.path) return;
            if (allVisibleSelected) state.selectedReplacementPaths.delete(item.path);
            else state.selectedReplacementPaths.add(item.path);
          });
          renderMovieFixDefaults(payload);
        });
      }
      const fixButton = document.getElementById('fixSelectedSubtitleButton');
      if (fixButton) fixButton.addEventListener('click', () => fixSelectedSubtitleDefaults());
      document.querySelectorAll('.subtitle-sortable-th').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.sortCol;
          if (state.subtitleSort.col === col) {
            state.subtitleSort.dir = state.subtitleSort.dir === 'asc' ? 'desc' : 'asc';
          } else {
            state.subtitleSort = { col, dir: 'asc' };
          }
          renderMovieFixDefaults(payload);
        });
      });
    }

    function attachReplacementQueueDetailHandlers() {
      document.querySelectorAll('.replacement-delete').forEach(button => {
        button.addEventListener('click', () => deleteReplacementMedia([button.dataset.itemId]));
      });
      document.querySelectorAll('.replacement-history-remove').forEach(button => {
        button.addEventListener('click', () => {
          const itemIds = (button.dataset.itemIds || '').split(',').filter(Boolean);
          dismissReplacementQueueItems(itemIds);
        });
      });
      document.querySelectorAll('.replacement-history-filter').forEach(button => {
        button.addEventListener('click', () => {
          state.replacementHistoryFilter = button.dataset.historyFilter || 'deleted';
          state.replacementHistorySort = { col: null, dir: 'asc' };
          renderReplacementQueueDetail(state.results.movies.profile);
        });
      });
      document.querySelectorAll('.replacement-history-sort-th').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.sortCol;
          if (state.replacementHistorySort.col === col) {
            state.replacementHistorySort.dir = state.replacementHistorySort.dir === 'asc' ? 'desc' : 'asc';
          } else {
            state.replacementHistorySort = { col, dir: col === 'imdb' ? 'desc' : 'asc' };
          }
          renderReplacementQueueDetail(state.results.movies.profile);
        });
      });
    }

    async function queueSelectedReplacements(mode) {
      const source = sourceInput.value.trim();
      const payload = state.results.movies.profile;
      const issueFamily = activeMovieTriageFamily();
      if (!source || !payload) return;
      const items = (payload.movies || []).filter(item =>
        state.selectedReplacementPaths.has(item.path || '') &&
        movieMatchesActiveTriageFamily(item) &&
        !replacementQueueItemForPath(payload, item.path || '', issueFamily)
      );
      if (!items.length) return;
      setStatus(`Queueing ${items.length} replacement item${items.length === 1 ? '' : 's'}…`, 'running');
      try {
        const response = await fetch('/api/movies/replacement-queue/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, mode, issue_family: issueFamily, items })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Queue failed.');
        state.results.movies.replacementQueue = result;
        state.results.movies.replacementQueueSource = source;
        cacheMovieReplacementQueue(result);
        if (state.results.movies.profile) state.results.movies.profile.replacement_queue = result;
        state.selectedReplacementPaths.clear();
        const skipped = result.skipped?.length || 0;
        setStatus(`Queued ${result.added.length} item${result.added.length === 1 ? '' : 's'}${skipped ? `; skipped ${skipped}` : ''}.`, 'idle');
        rerenderActiveMovieTriagePage(state.results.movies.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    function applyUpdatedMovieProfileItems(payload, updatedItems) {
      if (!payload || !Array.isArray(payload.movies) || !Array.isArray(updatedItems) || !updatedItems.length) return;
      const updates = new Map(updatedItems.filter(item => item?.path).map(item => [item.path, item]));
      payload.movies = payload.movies.map(item => {
        const updated = updates.get(item.path);
        if (!updated) return item;
        const existingPercentile = item?.profile?.percentile ?? 0;
        return {
          ...item,
          ...updated,
          profile: {
            ...(updated.profile || {}),
            percentile: existingPercentile
          }
        };
      });
    }

    function removeDeletedMovieProfileItems(payload, deletedItems) {
      if (!payload || !Array.isArray(payload.movies) || !Array.isArray(deletedItems) || !deletedItems.length) return;
      const deletedPaths = (deletedItems || []).map(item => item?.path).filter(Boolean);
      if (!deletedPaths.length) return;
      payload.movies = payload.movies.filter(item => {
        const path = item?.path || '';
        return !deletedPaths.some(deletedPath => path === deletedPath || path.startsWith(deletedPath + '/'));
      });
    }

    async function refreshMovieDashboardHistogram(payload) {
      if (!payload || payload.dashboard_snapshot_only || !Array.isArray(payload.movies)) return;
      const source = sourceInput.value.trim() || payload.source_root || '';
      if (!source) return;
      const response = await fetch('/api/movies/dashboard/histogram', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, movies: payload.movies })
      });
      const histogram = await response.json();
      if (!response.ok) throw new Error(histogram.error || 'Dashboard histogram refresh failed.');
      payload.histogram = histogram;
      payload.dashboard_snapshot_only = false;
      cacheMovieDashboard(payload);
    }

    function humanAudioFixMessage(code) {
      const labels = {
        outside_source: 'outside source',
        path_missing: 'path missing',
        unsupported_container: 'unsupported container',
        probe_failed: 'probe failed',
        not_multi_audio: 'not multi-audio',
        english_audio_missing: 'English audio missing',
        english_audio_not_retained: 'English audio would not be retained',
        already_default_english: 'English already default',
        english_default_set: 'English set as default',
        english_default_set_and_removed_foreign_audio: 'English set as default and tagged foreign audio removed',
        english_default_set_no_foreign_audio_removed: 'English set as default; no tagged foreign audio removed',
        ffmpeg_missing: 'ffmpeg missing'
      };
      if (!code) return 'unknown result';
      if (labels[code]) return labels[code];
      if (code.startsWith('probe_failed:')) return `probe failed: ${code.slice('probe_failed:'.length).trim()}`;
      if (code.startsWith('fix_failed:')) return `fix failed: ${code.slice('fix_failed:'.length).trim()}`;
      return code.replaceAll('_', ' ');
    }

    function humanSubtitleFixMessage(code) {
      const labels = {
        outside_source: 'outside source',
        path_missing: 'path missing',
        unsupported_container: 'unsupported container',
        subtitle_streams_missing: 'subtitle streams missing',
        clear_default_subtitles: 'subtitle defaults need clearing',
        repair_subtitle_defaults: 'subtitle defaults need repair',
        already_repaired: 'subtitle defaults already correct',
        english_forced_defaulted: 'forced English set as default',
        english_subtitle_defaulted: 'English subtitle set as default',
        subtitle_defaults_cleared: 'subtitle defaults cleared',
        ffmpeg_missing: 'ffmpeg missing'
      };
      if (!code) return 'unknown result';
      if (labels[code]) return labels[code];
      if (code.startsWith('probe_failed:')) return `probe failed: ${code.slice('probe_failed:'.length).trim()}`;
      if (code.startsWith('fix_failed:')) return `fix failed: ${code.slice('fix_failed:'.length).trim()}`;
      return code.replaceAll('_', ' ');
    }

    function summarizeAudioFixResult(result, dropForeignAudio) {
      const fixed = result?.fixed?.length || 0;
      const skipped = result?.skipped?.length || 0;
      const verb = dropForeignAudio ? 'Fixed and pruned' : 'Fixed';
      const parts = [`${verb} ${fixed} file${fixed === 1 ? '' : 's'}`];
      if (skipped) {
        const skipReasons = Array.from(new Set((result.skipped || []).map(item => humanAudioFixMessage(item.message)).filter(Boolean))).slice(0, 3);
        parts.push(`skipped ${skipped}`);
        if (skipReasons.length) parts.push(skipReasons.join('; '));
      }
      return parts.join('; ') + '.';
    }

    function summarizeSubtitleFixResult(result) {
      const fixed = result?.fixed?.length || 0;
      const skipped = result?.skipped?.length || 0;
      const parts = [`Fixed ${fixed} file${fixed === 1 ? '' : 's'}`];
      if (skipped) {
        const skipReasons = Array.from(new Set((result.skipped || []).map(item => humanSubtitleFixMessage(item.message)).filter(Boolean))).slice(0, 3);
        parts.push(`skipped ${skipped}`);
        if (skipReasons.length) parts.push(skipReasons.join('; '));
      }
      return parts.join('; ') + '.';
    }

    async function deleteSelectedFiles() {
      if (movieAudioFixSelectionLocked()) {
        setStatus('Wait for the active remux to finish before changing audio-packaging selections.', 'error');
        return;
      }
      const source = sourceInput.value.trim();
      const payload = state.results.movies.profile;
      const issueFamily = activeMovieTriageFamily();
      if (!source || !payload) return;
      const items = (payload.movies || []).filter(item =>
        state.selectedReplacementPaths.has(item.path || '') &&
        movieMatchesActiveTriageFamily(item)
      );
      if (!items.length) return;
      const message = `Permanently delete ${items.length} file${items.length === 1 ? '' : 's'}? This cannot be undone.`;
      if (!window.confirm(message)) return;
      setStatus(`Deleting ${items.length} file${items.length === 1 ? '' : 's'}…`, 'running');
      try {
        const existingPendingIds = items.map(item => replacementQueueItemForPath(payload, item.path || '', issueFamily))
          .filter(item => item && item.status === 'pending')
          .map(item => item.item_id)
          .filter(Boolean);
        const newItems = items.filter(item => !replacementQueueItemForPath(payload, item.path || '', issueFamily));
        let itemIds = [...existingPendingIds];
        if (newItems.length) {
          const addResponse = await fetch('/api/movies/replacement-queue/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source, mode: 'file', issue_family: issueFamily, items: newItems })
          });
          const addResult = await addResponse.json();
          if (!addResponse.ok) throw new Error(addResult.error || 'Queue failed.');
          itemIds = itemIds.concat((addResult.added || []).map(i => i.item_id).filter(Boolean));
        }
        if (!itemIds.length) { setStatus('Nothing to delete.', 'idle'); return; }
        const delResponse = await fetch('/api/movies/replacement-queue/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, item_ids: itemIds })
        });
        const delResult = await delResponse.json();
        if (!delResponse.ok) throw new Error(delResult.error || 'Delete failed.');
        state.results.movies.replacementQueue = delResult;
        state.results.movies.replacementQueueSource = source;
        cacheMovieReplacementQueue(delResult);
        if (state.results.movies.profile) {
          state.results.movies.profile.replacement_queue = delResult;
          removeDeletedMovieProfileItems(state.results.movies.profile, delResult.deleted || []);
          await refreshMovieDashboardHistogram(state.results.movies.profile);
        }
        state.selectedReplacementPaths.clear();
        const skipped = delResult.skipped?.length || 0;
        const sidecars = delResult.cleaned_sidecars?.length || 0;
        const folders = delResult.removed_folders?.length || 0;
        const cleanup = sidecars || folders ? `; cleaned ${sidecars} sidecar${sidecars === 1 ? '' : 's'}${folders ? ` and ${folders} folder${folders === 1 ? '' : 's'}` : ''}` : '';
        setStatus(`Deleted ${delResult.deleted.length} file${delResult.deleted.length === 1 ? '' : 's'}${cleanup}${skipped ? `; skipped ${skipped}` : ''}.`, 'idle');
        rerenderActiveMovieTriagePage(state.results.movies.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    async function fixSelectedAudioDefaults(options = {}) {
      const source = sourceInput.value.trim();
      const payload = state.results.movies.profile;
      const dropForeignAudio = !!options.dropForeignAudio;
      if (state.movieAudioFixBusy) {
        setStatus('An audio remux is already running.', 'error');
        return;
      }
      if (!source || !payload) return;
      const paths = selectableVisibleReplacementItems(payload, payload.movies || [])
        .filter(item => state.selectedReplacementPaths.has(item.path || ''))
        .map(item => item.path)
        .filter(Boolean);
      if (!paths.length) return;
      const actionLabel = dropForeignAudio ? 'Setting English default and dropping foreign' : 'Setting English default';
      state.movieAudioFixBusy = true;
      rerenderActiveMovieTriagePage(payload);
      renderReplacementQueueDetail(payload);
      setStatus(`${actionLabel} for ${paths.length} file${paths.length === 1 ? '' : 's'}…`, 'running');
      try {
        const response = await fetch('/api/movies/audio-packaging/fix', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, paths, drop_foreign_audio: dropForeignAudio })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Audio fix failed.');
        state.results.movies.replacementQueue = result.replacement_queue || state.results.movies.replacementQueue;
        state.results.movies.replacementQueueSource = source;
        if (result.replacement_queue) cacheMovieReplacementQueue(result.replacement_queue);
        if (state.results.movies.profile) {
          state.results.movies.profile.replacement_queue = result.replacement_queue || state.results.movies.profile.replacement_queue;
          applyUpdatedMovieProfileItems(state.results.movies.profile, result.updated_items || []);
          await refreshMovieDashboardHistogram(state.results.movies.profile);
        }
        state.selectedReplacementPaths.clear();
        setStatus(summarizeAudioFixResult(result, dropForeignAudio), 'idle');
        rerenderActiveMovieTriagePage(state.results.movies.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        state.movieAudioFixBusy = false;
        rerenderActiveMovieTriagePage(state.results.movies.profile || payload);
        renderReplacementQueueDetail(state.results.movies.profile || payload);
      }
    }

    async function fixSelectedSubtitleDefaults() {
      const source = sourceInput.value.trim();
      const payload = state.results.movies.profile;
      if (state.movieSubtitleFixBusy) {
        setStatus('A subtitle remux is already running.', 'error');
        return;
      }
      if (!source || !payload) return;
      const selectedItems = selectableVisibleSubtitleRepairItems(payload, payload.movies || [])
        .filter(item => state.selectedReplacementPaths.has(item.path || ''));
      const paths = selectedItems.map(item => item.path).filter(Boolean);
      if (!paths.length) return;
      const issueCodes = {};
      selectedItems.forEach(item => { if (item.path) issueCodes[item.path] = movieSubtitleReadinessIssueCode(item); });
      state.movieSubtitleFixBusy = true;
      renderMovieFixDefaults(payload);
      setStatus(`Repairing subtitle defaults for ${paths.length} file${paths.length === 1 ? '' : 's'}…`, 'running');
      try {
        const response = await fetch('/api/movies/subtitle-readiness/fix', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, paths, issue_codes: issueCodes })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Subtitle fix failed.');
        if (state.results.movies.profile) {
          applyUpdatedMovieProfileItems(state.results.movies.profile, result.updated_items || []);
          await refreshMovieDashboardHistogram(state.results.movies.profile);
        }
        state.selectedReplacementPaths.clear();
        if (result.subtitle_history) state.subtitleHistory = result.subtitle_history;
        setStatus(summarizeSubtitleFixResult(result), 'idle');
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        state.movieSubtitleFixBusy = false;
        renderMovieFixDefaults(state.results.movies.profile || payload);
      }
    }

    async function deleteReplacementMedia(itemIds) {
      const queue = currentMovieReplacementQueue(state.results.movies.profile);
      const source = sourceInput.value.trim() || queue?.source_root || '';
      if (!source) {
        setStatus('Choose a source directory before deleting replacement media.', 'error');
        return;
      }
      if (!itemIds.length) {
        setStatus('No pending replacement media is selected for deletion.', 'error');
        return;
      }
      const message = `Delete media for ${itemIds.length} replacement queue item${itemIds.length === 1 ? '' : 's'}? This cannot be undone.`;
      if (!window.confirm(message)) return;
      setStatus(`Deleting ${itemIds.length} replacement queue item${itemIds.length === 1 ? '' : 's'}…`, 'running');
      try {
        const response = await fetch('/api/movies/replacement-queue/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, item_ids: itemIds })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Delete failed.');
        state.results.movies.replacementQueue = result;
        state.results.movies.replacementQueueSource = source;
        cacheMovieReplacementQueue(result);
        if (state.results.movies.profile) {
          state.results.movies.profile.replacement_queue = result;
          removeDeletedMovieProfileItems(state.results.movies.profile, result.deleted || []);
          await refreshMovieDashboardHistogram(state.results.movies.profile);
        }
        const skipped = result.skipped?.length || 0;
        const sidecars = result.cleaned_sidecars?.length || 0;
        const folders = result.removed_folders?.length || 0;
        const cleanup = sidecars || folders ? `; cleaned ${sidecars} sidecar${sidecars === 1 ? '' : 's'}${folders ? ` and ${folders} folder${folders === 1 ? '' : 's'}` : ''}` : '';
        setStatus(`Deleted ${result.deleted.length} item${result.deleted.length === 1 ? '' : 's'}${cleanup}${skipped ? `; skipped ${skipped}` : ''}.`, 'idle');
        if (state.page === 'quality' || (state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio')) rerenderActiveMovieTriagePage(state.results.movies.profile);
        else renderReplacementQueueDetail(state.results.movies.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    async function dismissReplacementQueueItems(itemIds) {
      const queue = currentMovieReplacementQueue(state.results.movies.profile);
      const source = sourceInput.value.trim() || queue?.source_root || '';
      if (!source) {
        setStatus('Choose a source directory before removing items from the replacement queue.', 'error');
        return;
      }
      if (!itemIds.length) {
        setStatus('No deleted replacement queue items are selected for removal.', 'error');
        return;
      }
      const message = `Remove ${itemIds.length} replacement queue item${itemIds.length === 1 ? '' : 's'} from history? This will not delete media.`;
      if (!window.confirm(message)) return;
      setStatus(`Removing ${itemIds.length} replacement queue item${itemIds.length === 1 ? '' : 's'} from history…`, 'running');
      try {
        const response = await fetch('/api/movies/replacement-queue/dismiss', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, item_ids: itemIds })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Queue removal failed.');
        state.results.movies.replacementQueue = result;
        state.results.movies.replacementQueueSource = source;
        cacheMovieReplacementQueue(result);
        if (state.results.movies.profile) state.results.movies.profile.replacement_queue = result;
        const skipped = result.skipped?.length || 0;
        setStatus(`Removed ${result.dismissed.length} item${result.dismissed.length === 1 ? '' : 's'} from the replacement queue${skipped ? `; skipped ${skipped}` : ''}.`, 'idle');
        if (state.page === 'quality' || (state.page === 'fix_defaults' && state.fixDefaultsTab === 'audio')) rerenderActiveMovieTriagePage(state.results.movies.profile);
        else renderReplacementQueueDetail(state.results.movies.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    function buildMovieMetrics(payload) {
      if (!payload) return [];
      const histogram = payload.histogram || {};
      const topProfile = Object.entries(histogram.quality_profile_counts || {}).sort((a, b) => b[1] - a[1])[0]?.[0] || '-';
      return [
        { value: String(histogram.movie_count ?? (payload.movies || []).length), label: 'files scanned' },
        { value: String(histogram.risk_counts?.playback_risk || 0), label: 'playback-risk hits' },
        { value: String(histogram.risk_counts?.indexing_visibility_risk || 0), label: 'visibility-risk hits' },
        { value: humanProfileLabel(topProfile), label: 'top profile' }
      ];
    }

    function buildMovieBars(payload) {
      if (!payload) return [];
      const counts = payload.histogram?.risk_counts || {};
      const entries = Object.entries(counts);
      const max = Math.max(...entries.map(([, value]) => value), 1);
      return entries.map(([key, value]) => ({ label: key.replaceAll('_', ' '), value: String(value), width: (value / max) * 100 }));
    }

    function subtitleItemSortKey(item, col) {
      const stripHtml = s => String(s || '').replace(/<[^>]*>/g, '').trim();
      if (col === 'title') { const stem = (item.path || '').split('/').pop().replace(/\.[^.]+$/, ''); const m = stem.match(/^(.+?)\s*\((\d{4})\)/); return m ? `${m[1]} ${m[2]}` : stem; }
      if (col === 'issue') return humanSubtitleReadinessIssueLabel(movieSubtitleReadinessIssueCode(item)) || '';
      if (col === 'default_audio') return stripHtml(describeAudioStream(movieDefaultAudioStream(item)));
      if (col === 'current_default_subtitle') return stripHtml(describeSubtitleStream(movieDefaultSubtitleStream(item)));
      if (col === 'english_forced_subtitle') return stripHtml(itemSubtitleTargetSummary(item, { forcedOnly: true }));
      if (col === 'english_subtitle') return stripHtml(itemSubtitleTargetSummary(item));
      return '';
    }

    function sortedSubtitleItems(items) {
      const { col, dir } = state.subtitleSort;
      if (!col) return items;
      const mult = dir === 'asc' ? 1 : -1;
      return [...items].sort((a, b) => mult * subtitleItemSortKey(a, col).localeCompare(subtitleItemSortKey(b, col), undefined, { sensitivity: 'base' }));
    }

    function sortedMovies(items) {
      const { col, dir } = state.qualitySort;
      if (!col) return items;
      const mult = dir === 'asc' ? 1 : -1;
      const RES_RANK = { '2160p': 4, '1080p': 3, '720p': 2, 'sd': 1 };
      return [...items].sort((a, b) => {
        if (col === 'file') return mult * (a.path || '').split('/').pop().localeCompare((b.path || '').split('/').pop(), undefined, { sensitivity: 'base' });
        if (col === 'profile') return mult * ((a.profile?.rank || 0) - (b.profile?.rank || 0));
        if (col === 'resolution') return mult * ((RES_RANK[a.facts?.resolution_bucket] || 0) - (RES_RANK[b.facts?.resolution_bucket] || 0));
        if (col === 'video_bitrate') return mult * ((a.facts?.video_bitrate_kbps || 0) - (b.facts?.video_bitrate_kbps || 0));
        if (col === 'audio_bitrate') return mult * ((a.facts?.audio_bitrate_kbps || 0) - (b.facts?.audio_bitrate_kbps || 0));
        if (col === 'audio_summary') return mult * (String(a.facts?.audio_summary || '').localeCompare(String(b.facts?.audio_summary || ''), undefined, { sensitivity: 'base' }));
        if (col === 'file_size') return mult * ((a.facts?.file_size_bytes || 0) - (b.facts?.file_size_bytes || 0));
        return 0;
      });
    }

    function filteredMovies(payload, filter) {
      const movies = payload?.movies || [];
      if (filter === 'all') return movies;
      if (filter === 'strict_weak') return strictWeakMovies(payload);
      if (filter === 'anime') {
        return movies.filter(item => item.profile.diagnostics.some(diag =>
          ['anime_subtitle_attachment_risk', 'anime_absolute_numbering_risk', 'episodic_naming_parse_risk', 'multi_audio_anime_mux_risk']
            .includes(diag.code)
        ));
      }
      if (filter.includes('_risk')) {
        return movies.filter(item => (item.profile.risk_counts?.[filter] || 0) > 0);
      }
      return movies.filter(item => item.profile.label === filter);
    }

    function buildMovieNormalizeMetrics(payload) {
      if (!payload) return [];
      const safe = (payload.proposed_changes || []).filter(change => change.confidence === 'safe').length;
      const review = (payload.proposed_changes || []).filter(change => change.confidence === 'review').length;
      return [
        { value: String((payload.movie_results || []).length), label: 'all results' },
        { value: String((payload.proposed_changes || []).length), label: 'rename proposals' },
        { value: String(safe), label: 'safe renames' },
        { value: String(review), label: 'review renames' }
      ];
    }

    function buildMovieNormalizeBars(payload) {
      if (!payload) return [];
      const warningCodes = CounterFromArray((payload.warnings || []).map(w => w.code));
      const total = Math.max(...Object.values(warningCodes), 1);
      return Object.entries(warningCodes).slice(0, 4).map(([key, value]) => ({ label: key, value: String(value), width: (value / total) * 100 }));
    }

    function filteredMovieChanges(payload) {
      if (!payload) return [];
      if (state.filter === 'warnings') return [];
      const changes = payload.proposed_changes || [];
      if (state.filter === 'all') return changes;
      return changes.filter(change => change.confidence === state.filter);
    }

    function movieNormalizeFilter() {
      return state.page === 'normalize' && state.lane === 'movies' && state.filter === 'all' ? 'all_results' : state.filter;
    }

    function filteredMovieNormalizeRows(payload) {
      if (!payload) return [];
      const filter = movieNormalizeFilter();
      if (filter === 'warnings') return [];
      if (filter === 'all_results') {
        return (payload.movie_results || []).map(result => ({ type: 'result', result }));
      }
      const resultRows = movieNormalizeResultsForConfidence(payload, filter).map(result => ({ type: 'result', result }));
      const resultChangeIds = new Set(resultRows.flatMap(row => row.result.change_ids || []));
      const orphanChangeRows = (payload.proposed_changes || [])
        .filter(change => change.confidence === filter && !resultChangeIds.has(change.item_id))
        .map(change => ({ type: 'change', change, result: movieNormalizeResultForChange(payload, change) }));
      return [...resultRows, ...orphanChangeRows];
    }

    function buildMovieJunkMetrics(payload) {
      if (!payload) return [];
      const junk = payload.junk || [];
      const high = junk.filter(item => item.confidence === 'high').length;
      const review = junk.filter(item => item.confidence === 'review').length;
      return [
        { value: String(junk.length), label: 'junk files' },
        { value: String(high), label: 'high confidence' },
        { value: String(review), label: 'review' },
        { value: String((payload.warnings || []).length), label: 'warnings' }
      ];
    }

    function buildMovieJunkBars(payload) {
      if (!payload) return [];
      const reasonCounts = CounterFromArray((payload.junk || []).flatMap(item => (item.reasons || []).map(reason => reason.code)));
      const total = Math.max(...Object.values(reasonCounts), 1);
      return Object.entries(reasonCounts).slice(0, 4).map(([key, value]) => ({ label: key, value: String(value), width: (value / total) * 100 }));
    }

    function filteredMovieJunk(payload) {
      const junk = payload?.junk || [];
      if (state.filter === 'all') return junk;
      return junk.filter(item => item.confidence === state.filter);
    }

    function CounterFromArray(items) {
      return items.reduce((acc, item) => {
        acc[item] = (acc[item] || 0) + 1;
        return acc;
      }, {});
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      }[char]));
    }
  </script>
</body>
</html>
"""


def library_roots_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "library-roots.json"


def load_library_roots() -> dict[str, Any]:
    path = library_roots_path()
    if not path.exists():
        return {"movies": "", "recent": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"movies": "", "recent": []}
        movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
        recent = data.get("recent") if isinstance(data.get("recent"), list) else []
        recent = [
            r for r in recent
            if isinstance(r, dict)
            and r.get("lane") == "movies"
            and isinstance(r.get("source"), str)
            and r["source"]
        ][:2]
        return {"movies": movies, "recent": recent}
    except (OSError, json.JSONDecodeError):
        return {"movies": "", "recent": []}


def save_library_roots(data: dict[str, Any]) -> None:
    path = library_roots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
    recent = data.get("recent") if isinstance(data.get("recent"), list) else []
    recent = [
        r for r in recent
        if isinstance(r, dict)
        and r.get("lane") == "movies"
        and isinstance(r.get("source"), str)
        and r["source"]
    ][:2]
    payload = json.dumps({"movies": movies, "recent": recent}, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def serve_web_ui(
    host: str,
    port: int,
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
) -> None:
    handler = build_handler(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key)
    server = ThreadingHTTPServer((host, port), handler)
    source_hint = f" default source {default_source}" if default_source else ""
    print(f"normal web UI listening on http://{host}:{port}/{source_hint}")
    server.serve_forever()


def render_index_html(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    return INDEX_HTML.replace(
        "<script>",
        (
            "<script>\n"
            f"    window.DEFAULT_SOURCE = {json.dumps(str(default_source) if default_source else '')};\n"
            f"    window.OMDB_AVAILABLE = {json.dumps(bool(omdb_key))};\n"
            f"    window.TMDB_KEY = {json.dumps(tmdb_key or '')};"
        ),
        1,
    )


def build_handler(
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.startswith("/api/activity"):
                try:
                    self.handle_activity()
                except Exception as exc:
                    self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if self.path == "/api/library-roots":
                try:
                    self.respond_json(load_library_roots())
                except Exception as exc:
                    self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if self.path not in {"/", "/index.html"}:
                self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            html = render_index_html(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key)
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def handle_activity(self) -> None:
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            raw_source = qs.get("source", [None])[0]
            source = resolve_source_path(raw_source, default_source=default_source)
            self.respond_json(build_activity_payload(source))

        def do_POST(self) -> None:
            try:
                payload = self.read_json_body()
                route = self.path
                if route == "/api/library-roots":
                    save_library_roots(payload)
                    self.respond_json(load_library_roots())
                    return
                if route == "/api/movies/profile":
                    self.handle_movies_profile(payload)
                    return
                if route == "/api/movies/dashboard/histogram":
                    self.handle_movies_dashboard_histogram(payload)
                    return
                if route == "/api/movies/standards/update":
                    self.handle_movies_standards_update(payload)
                    return
                if route == "/api/movies/canonical-lists":
                    self.handle_movies_canonical_lists(payload)
                    return
                if route == "/api/movies/omdb/ratings":
                    self.handle_movies_omdb_ratings(payload)
                    return
                if route == "/api/source/scan-warning":
                    self.handle_source_scan_warning(payload)
                    return
                if route == "/api/movies/register":
                    self.handle_movies_register(payload)
                    return
                if route == "/api/movies/inspect":
                    self.handle_movies_inspect(payload)
                    return
                if route == "/api/movies/normalize":
                    self.handle_movies_normalize(payload)
                    return
                if route == "/api/movies/apply":
                    self.handle_movies_apply(payload)
                    return
                if route == "/api/movies/junk":
                    self.handle_movies_junk(payload)
                    return
                if route == "/api/movies/junk/delete":
                    self.handle_movies_junk_delete(payload)
                    return
                if route == "/api/movies/replacement-queue/list":
                    self.handle_movies_replacement_queue_list(payload)
                    return
                if route == "/api/movies/replacement-queue/add":
                    self.handle_movies_replacement_queue_add(payload)
                    return
                if route == "/api/movies/replacement-queue/delete":
                    self.handle_movies_replacement_queue_delete(payload)
                    return
                if route == "/api/movies/replacement-queue/dismiss":
                    self.handle_movies_replacement_queue_dismiss(payload)
                    return
                if route == "/api/movies/audio-packaging/fix":
                    self.handle_movies_audio_packaging_fix(payload)
                    return
                if route == "/api/movies/subtitle-readiness/fix":
                    self.handle_movies_subtitle_readiness_fix(payload)
                    return
                if route == "/api/movies/subtitle-readiness/history":
                    self.handle_movies_subtitle_readiness_history_list(payload)
                    return
                if route == "/api/movies/subtitle-readiness/history/sync":
                    self.handle_movies_subtitle_readiness_history_sync(payload)
                    return
                if route == "/api/movies/subtitle-readiness/history/dismiss":
                    self.handle_movies_subtitle_readiness_history_dismiss(payload)
                    return
                self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except RequestConflictError as exc:
                self.respond_json({"error": str(exc)}, status=HTTPStatus.CONFLICT)
            except Exception as exc:
                self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def handle_movies_profile(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            cached = MOVIE_PROFILE_CACHE.get(source)
            if cached is not None:
                self.respond_json(_build_profile_response(source, cached, load_movie_standards()))
                return
            with guarded_heavy_scan(source, "Movie profile scan"):
                with ACTIVITY_TRACKER.track(source, "Movie profile scan") as activity_id:
                    def update_profile_activity(progress: MovieScanProgress) -> None:
                        has_total = progress.total > progress.processed
                        ACTIVITY_TRACKER.update(
                            activity_id,
                            current_path=progress.current_path,
                            status_text=f"{progress.processed} files processed",
                            processed=progress.processed,
                            total=progress.total if has_total else None,
                            progress_fraction=(progress.processed / progress.total) if has_total else None,
                            eta_seconds=progress.eta_seconds if has_total else None,
                        )

                    report = scan_movie_profiles(
                        source,
                        probe_media=tracked_probe(source, "ffprobe movie metadata", cache=PROBE_CACHE),
                        progress_callback=update_profile_activity,
                        should_cancel=self.client_disconnected,
                    )
                MOVIE_PROFILE_CACHE.put(source, report)
                standards = load_movie_standards()
                response = _build_profile_response(source, report, standards)
            self.respond_json(response)

        def handle_movies_dashboard_histogram(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            movies = payload.get("movies")
            if not isinstance(movies, list):
                raise ValueError("movies must be a list")
            self.respond_json(
                build_histogram_payload_from_items(
                    str(source),
                    utc_now_iso(),
                    [item for item in movies if isinstance(item, dict)],
                )
            )

        def handle_movies_standards_update(self, payload: dict[str, Any]) -> None:
            label = str(payload.get("label") or "").strip()
            values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
            revision = str(payload.get("revision") or "").strip() or None
            try:
                standards = update_movie_profile_definition(label, values, expected_revision=revision)
            except MovieStandardsConflictError as exc:
                raise RequestConflictError(str(exc)) from exc
            self.respond_json(
                {
                    "movie_standards": standards,
                    "movie_standards_revision": movie_standards_revision(standards),
                    "quality_profile_definitions": build_movie_profile_definitions(standards),
                    "replacement_candidate_definition": build_replacement_candidate_definition(standards),
                }
            )

        def handle_movies_canonical_lists(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with guarded_heavy_scan(source, "Movie canonical lists"):
                with ACTIVITY_TRACKER.track(source, "Movie canonical lists"):
                    report = build_canonical_lists_report(
                        source,
                        tmdb_key=tmdb_key,
                        should_cancel=self.client_disconnected,
                    )
            self.respond_json(report.to_dict())

        def handle_movies_omdb_ratings(self, payload: dict[str, Any]) -> None:
            items = payload.get("items")
            if not isinstance(items, list):
                raise ValueError("items must be a list")
            self.respond_json(lookup_omdb_ratings([item for item in items if isinstance(item, dict)], omdb_key))

        def handle_source_scan_warning(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            self.respond_json(build_source_scan_warning(source))

        def client_disconnected(self) -> bool:
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                if not readable:
                    return False
                return self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                return True

        def handle_movies_register(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with guarded_heavy_scan(source, "Movie catalogue export"):
                with ACTIVITY_TRACKER.track(source, "Movie catalogue export"):
                    scan_report = scan_movie_library(source, probe_media=tracked_probe(source, "ffprobe movie catalogue", cache=PROBE_CACHE))
                    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as jf:
                        json.dump(scan_report.to_dict(), jf)
                        report_path = Path(jf.name)
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as xf:
                            xlsx_path = Path(xf.name)
                        write_movie_register_xlsx(report_path, xlsx_path)
                        data = xlsx_path.read_bytes()
                    finally:
                        report_path.unlink(missing_ok=True)
                        xlsx_path.unlink(missing_ok=True)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", 'attachment; filename="movie-catalogue.xlsx"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def handle_movies_inspect(self, payload: dict[str, Any]) -> None:
            raw_path = payload.get("path")
            if not raw_path:
                raise ValueError("path is required")
            resolved = Path(str(raw_path)).expanduser().resolve()
            if not resolved.exists() or not resolved.is_file():
                raise FileNotFoundError(f"path does not exist: {resolved}")
            source = resolved.parent
            with ACTIVITY_TRACKER.track(source, "Movie inspect"):
                self.respond_json(
                    inspect_movie_file(
                        resolved,
                        probe_media=tracked_probe(source, "ffprobe movie inspect", cache=PROBE_CACHE),
                    ).to_dict()
                )

        def handle_movies_normalize(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            requested_style = str(payload.get("naming_style") or DEFAULT_MOVIE_NAMING_STYLE)
            if requested_style not in MOVIE_NAMING_STYLES:
                raise ValueError(f"unknown movie naming style: {requested_style}")
            with guarded_heavy_scan(source, "Movie normalize plan"):
                with ACTIVITY_TRACKER.track(source, "Movie normalize plan"):
                    movie_files = discover_video_files(source)
                    plans_by_style = {style: build_movie_plan(source, naming_style=style, movie_files=movie_files) for style in MOVIE_NAMING_STYLES}
                    response = plans_by_style[requested_style].to_dict()
                    response["naming_style"] = requested_style
                    response["default_naming_style"] = DEFAULT_MOVIE_NAMING_STYLE
                    response["proposed_changes_by_naming_style"] = {
                        style: plans_by_style[style].to_dict()["proposed_changes"] for style in MOVIE_NAMING_STYLES
                    }
                    response["warnings_by_naming_style"] = {
                        style: plans_by_style[style].to_dict()["warnings"] for style in MOVIE_NAMING_STYLES
                    }
                    response["movie_results_by_naming_style"] = {
                        style: build_movie_normalize_results(source, movie_files, plans_by_style[style].proposed_changes)
                        for style in MOVIE_NAMING_STYLES
                    }
                    response["movie_files"] = [str(path) for path in movie_files]
            self.respond_json(response)

        def handle_movies_apply(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            requested_style = str(payload.get("naming_style") or DEFAULT_MOVIE_NAMING_STYLE)
            if requested_style not in MOVIE_NAMING_STYLES:
                raise ValueError(f"unknown movie naming style: {requested_style}")
            raw_changes = payload.get("changes", [])
            if not isinstance(raw_changes, list):
                raise ValueError("changes must be a list")
            changes = [ProposedChange(**c) for c in raw_changes]
            with ACTIVITY_TRACKER.track(source, "Movie apply"):
                report = apply_changes_in_place(source, changes)
                MOVIE_PROFILE_CACHE.invalidate(source)
                movie_files = discover_video_files(source)
                plans_by_style = {style: build_movie_plan(source, naming_style=style, movie_files=movie_files) for style in MOVIE_NAMING_STYLES}
            response = report.to_dict()
            remaining_payload = plans_by_style[requested_style].to_dict()
            remaining_payload["naming_style"] = requested_style
            remaining_payload["default_naming_style"] = DEFAULT_MOVIE_NAMING_STYLE
            remaining_payload["proposed_changes_by_naming_style"] = {
                style: plans_by_style[style].to_dict()["proposed_changes"] for style in MOVIE_NAMING_STYLES
            }
            remaining_payload["warnings_by_naming_style"] = {
                style: plans_by_style[style].to_dict()["warnings"] for style in MOVIE_NAMING_STYLES
            }
            remaining_payload["movie_results_by_naming_style"] = {
                style: build_movie_normalize_results(source, movie_files, plans_by_style[style].proposed_changes)
                for style in MOVIE_NAMING_STYLES
            }
            remaining_payload["movie_files"] = [str(path) for path in movie_files]
            remaining_changes = remaining_payload["proposed_changes"]
            response["remaining_changes"] = remaining_changes
            response["remaining_safe_count"] = len([change for change in remaining_changes if change["confidence"] == "safe"])
            response["remaining_review_count"] = len([change for change in remaining_changes if change["confidence"] == "review"])
            response["remaining_plan"] = remaining_payload if remaining_changes else None
            self.respond_json(response)

        def handle_movies_junk(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with guarded_heavy_scan(source, "Movie junk scan"):
                with ACTIVITY_TRACKER.track(source, "Movie junk scan"):
                    report = scan_movie_cleanup(source, probe_media=tracked_probe(source, "ffprobe junk scan", cache=PROBE_CACHE))
            self.respond_json(report.to_dict())

        def handle_movies_junk_delete(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            paths = payload.get("paths")
            if not isinstance(paths, list):
                raise ValueError("paths must be a list")
            with ACTIVITY_TRACKER.track(source, "Movie junk delete"):
                result = delete_movie_junk_files(source, paths, probe_media=tracked_probe(source, "ffprobe junk delete check", cache=PROBE_CACHE))
            self.respond_json(result)

        def handle_movies_replacement_queue_list(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            issue_family = payload.get("issue_family")
            self.respond_json(queue_for_source(source, issue_family=issue_family))

        def handle_movies_replacement_queue_add(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            items = payload.get("items")
            if not isinstance(items, list):
                raise ValueError("items must be a list")
            mode = str(payload.get("mode") or "file")
            issue_family = str(payload.get("issue_family") or "weak_encode")
            self.respond_json(add_profile_items_to_queue(source, items, mode=mode, issue_family=issue_family))

        def handle_movies_replacement_queue_delete(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            item_ids = payload.get("item_ids")
            if not isinstance(item_ids, list):
                raise ValueError("item_ids must be a list")
            self.respond_json(delete_replacement_queue_media(source, item_ids))

        def handle_movies_replacement_queue_dismiss(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            item_ids = payload.get("item_ids")
            if not isinstance(item_ids, list):
                raise ValueError("item_ids must be a list")
            self.respond_json(dismiss_replacement_queue_items(source, item_ids))

        def handle_movies_audio_packaging_fix(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            paths = payload.get("paths")
            if not isinstance(paths, list):
                raise ValueError("paths must be a list")
            drop_foreign_audio = bool(payload.get("drop_foreign_audio"))
            label = "Movie audio fix: make English default + drop foreign audio" if drop_foreign_audio else "Movie audio fix: make English default"
            with ACTIVITY_TRACKER.track(source, label, kind="remux") as activity_id:
                result = fix_english_audio_defaults(
                    source,
                    [str(path) for path in paths],
                    probe_media=tracked_probe(source, "ffprobe audio packaging fix", cache=PROBE_CACHE),
                    drop_foreign_audio=drop_foreign_audio,
                    progress_callback=lambda update: ACTIVITY_TRACKER.update(activity_id, **update),
                )
            fixed_paths = [str(item.get("path") or "") for item in result["fixed"]]
            if fixed_paths:
                MOVIE_PROFILE_CACHE.invalidate(source)
            queue = (
                clear_pending_queue_items(source, fixed_paths, issue_family="audio_packaging")
                if fixed_paths
                else queue_for_source(source, issue_family="audio_packaging")
            )
            updated_items = []
            for item in result["fixed"]:
                raw_facts = item.get("facts")
                if not isinstance(raw_facts, dict):
                    continue
                movie_path = Path(str(item["path"]))
                profiled = build_movie_profile_item(source, movie_path, media_facts_from_dict(raw_facts))
                updated_items.append(asdict(profiled))
            result["replacement_queue"] = queue
            result["updated_items"] = updated_items
            self.respond_json(result)

        def handle_movies_subtitle_readiness_fix(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            paths = payload.get("paths")
            if not isinstance(paths, list):
                raise ValueError("paths must be a list")
            issue_codes: dict[str, str] = payload.get("issue_codes") or {}
            with ACTIVITY_TRACKER.track(source, "Movie subtitle fix: repair defaults", kind="remux") as activity_id:
                result = fix_movie_subtitle_defaults(
                    source,
                    [str(path) for path in paths],
                    probe_media=tracked_probe(source, "ffprobe subtitle readiness fix", cache=PROBE_CACHE),
                    progress_callback=lambda update: ACTIVITY_TRACKER.update(activity_id, **update),
                )
            updated_items = []
            for item in result["fixed"]:
                raw_facts = item.get("facts")
                if not isinstance(raw_facts, dict):
                    continue
                movie_path = Path(str(item["path"]))
                profiled = build_movie_profile_item(source, movie_path, media_facts_from_dict(raw_facts))
                updated_items.append(asdict(profiled))
            if updated_items:
                MOVIE_PROFILE_CACHE.invalidate(source)
            result["updated_items"] = updated_items
            fixed_raw = [{"path": str(item["path"]), "issue_code": issue_codes.get(str(item["path"]), "")} for item in result["fixed"]]
            if fixed_raw:
                result["subtitle_history"] = upsert_subtitle_history_items(source, fixed_raw, entry_type="fixed")
            self.respond_json(result)

        def handle_movies_subtitle_readiness_history_list(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            self.respond_json(subtitle_history_for_source(source))

        def handle_movies_subtitle_readiness_history_sync(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            items = payload.get("items")
            if not isinstance(items, list):
                raise ValueError("items must be a list")
            self.respond_json(upsert_subtitle_history_items(source, items, entry_type="review_only"))

        def handle_movies_subtitle_readiness_history_dismiss(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            item_ids = payload.get("item_ids")
            if not isinstance(item_ids, list):
                raise ValueError("item_ids must be a list")
            self.respond_json(dismiss_subtitle_history_items(source, item_ids))


        def read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b"{}"
            if not body:
                return {}
            return json.loads(body.decode("utf-8"))

        def respond_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def resolve_source_path(raw_source: Any, default_source: Path | None = None) -> Path:
    if raw_source:
        resolved = Path(str(raw_source)).expanduser().resolve()
    elif default_source is not None:
        resolved = default_source.resolve()
    else:
        raise ValueError("source is required")
    if not resolved.exists():
        raise FileNotFoundError(f"source does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"source is not a directory: {resolved}")
    return resolved


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def source_paths_overlap(left: Path, right: Path) -> bool:
    left_resolved = left.resolve()
    right_resolved = right.resolve()
    return path_is_under(left_resolved, right_resolved) or path_is_under(right_resolved, left_resolved)


def tracked_probe(source: Path, label: str, cache: ProbeCache | None = None) -> Callable[[Path], Any]:
    def probe(path: Path) -> Any:
        if cache is not None:
            cached = cache.get(path)
            if cached is not None:
                return cached
        with ACTIVITY_TRACKER.track(source, label, kind="probe", current_path=path):
            facts = probe_media_facts(path)
        if cache is not None:
            cache.put(path, facts)
        return facts

    return probe


def build_activity_payload(source: Path) -> dict[str, Any]:
    app_items = ACTIVITY_TRACKER.snapshot(source)
    if app_items:
        external_items, os_note = [], None
    else:
        external_items, os_note = find_external_activity(source)
    active_probes = [item for item in app_items if item["kind"] == "probe"]
    return {
        "source_root": str(source.resolve()),
        "active": bool(app_items or external_items),
        "app": app_items,
        "probes": active_probes,
        "external": external_items,
        "os_note": os_note,
    }


def find_external_activity(source: Path) -> tuple[list[dict[str, Any]], str | None]:
    resolved = source.resolve()
    source_tokens = {str(resolved), str(source.expanduser())}
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,ppid=,comm=,args="],
            text=True,
            capture_output=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], f"os_process_check_unavailable: {exc}"
    if result.returncode != 0:
        return [], "os_process_check_unavailable"

    matches: list[dict[str, Any]] = []
    current_pid = str(os.getpid())
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, command, args = parts
        if pid == current_pid:
            continue
        command_lower = command.lower()
        args_lower = args.lower()
        is_shell = command_lower in {"bash", "sh", "zsh", "fish", "dash"}
        is_relevant_process = (
            command_lower in {"ffprobe", "ffmpeg", "normal", "python", "python3"}
            or "ffprobe" in args_lower
            or "ffmpeg" in args_lower
            or (not is_shell and "normal " in args_lower)
        )
        if not is_relevant_process:
            continue
        if not any(token and token in args for token in source_tokens):
            continue
        matches.append(
            {
                "pid": int(pid),
                "ppid": int(ppid),
                "command": command,
                "summary": summarize_process_args(args),
            }
        )
    return matches, None


def summarize_process_args(args: str) -> str:
    if len(args) <= 180:
        return args
    return args[:177] + "..."


@dataclass(frozen=True, slots=True)
class SourceMountDetails:
    fstype: str | None
    target: str | None


def source_mount_details(source: Path) -> SourceMountDetails:
    try:
        result = subprocess.run(
            ["findmnt", "-T", str(source.resolve()), "-o", "TARGET,FSTYPE", "-n"],
            text=True,
            capture_output=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return SourceMountDetails(fstype=None, target=None)
    if result.returncode != 0:
        return SourceMountDetails(fstype=None, target=None)
    line = result.stdout.strip()
    if not line:
        return SourceMountDetails(fstype=None, target=None)
    parts = line.split()
    if len(parts) < 2:
        return SourceMountDetails(fstype=None, target=None)
    return SourceMountDetails(target=parts[0], fstype=parts[1].lower())


def risky_mount_flags(source: Path) -> list[str]:
    details = source_mount_details(source)
    flags: list[str] = []
    if details.fstype in {"fuseblk", "ntfs", "ntfs3"}:
        flags.append(f"mount:{details.fstype}")
    return flags


def build_source_scan_warning(source: Path) -> dict[str, Any]:
    resolved = source.resolve()
    usage = shutil.disk_usage(resolved)
    reasons: list[str] = []
    if looks_like_drive_directory(resolved):
        reasons.append("drive_directory")
    reasons.extend(risky_mount_flags(resolved))
    mount_details = source_mount_details(resolved)
    warn = bool(reasons)
    message_parts: list[str] = []
    if "drive_directory" in reasons:
        message_parts.append("It looks like you are scanning a drive directory.")
    if any(reason.startswith("mount:") for reason in reasons):
        fstype = mount_details.fstype.upper() if mount_details.fstype else "FUSE/NTFS"
        message_parts.append(f"This source is on a {fstype} mount, which is higher risk for heavy recursive scans on Ubuntu GNOME.")
    return {
        "source": str(resolved),
        "warn": warn,
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "message": " ".join(message_parts).strip(),
        "mount_fstype": mount_details.fstype,
        "mount_target": mount_details.target,
        "total_size_bytes": usage.total,
        "total_size_label": format_storage_size(usage.total),
    }


def looks_like_drive_directory(path: Path) -> bool:
    if path == path.anchor:
        return True
    if path.is_mount():
        return True
    parts = path.parts
    if len(parts) == 3 and parts[1] in {"mnt", "Volumes"}:
        return True
    if len(parts) == 4 and parts[1] == "media":
        return True
    if len(parts) == 4 and parts[1:3] == ("run", "media"):
        return True
    return False


@contextmanager
def guarded_heavy_scan(source: Path, label: str, *, category: str = "heavy_scan") -> Iterator[None]:
    with HEAVY_SCAN_REGISTRY.claim(source, category, label):
        yield


def _build_profile_response(source: Path, report: MovieProfileReport, standards: dict[str, Any]) -> dict[str, Any]:
    response = report.to_dict()
    response["histogram"] = build_histogram_payload(report)
    response["replacement_queue"] = reconcile_replacement_queue(source, response["movies"])
    response["movie_standards"] = standards
    response["movie_standards_revision"] = movie_standards_revision(standards)
    response["quality_profile_definitions"] = build_movie_profile_definitions(standards)
    response["replacement_candidate_definition"] = build_replacement_candidate_definition(standards)
    return response


def format_storage_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000_000_000:
        return f"{size_bytes / 1_000_000_000_000:.1f} TB"
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{size_bytes / 1_000_000:.1f} MB"


def delete_movie_junk_files(
    source: Path,
    raw_paths: list[Any],
    probe_media: Callable[[Path], Any] = probe_media_facts,
) -> dict[str, Any]:
    source_root = source.resolve()
    deleted = []
    skipped = []

    for raw_path in raw_paths:
        resolved = Path(str(raw_path)).expanduser().resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError:
            skipped.append({"path": str(resolved), "reason": "outside_source"})
            continue
        if not resolved.exists() or not resolved.is_file():
            skipped.append({"path": str(resolved), "reason": "not_file"})
            continue
        try:
            reasons = detect_movie_junk_reasons(resolved, probe_media(resolved))
        except Exception:
            reasons = detect_movie_junk_reasons(resolved)
        if not reasons:
            reasons = detect_movie_junk_document_reasons(resolved)
        if not reasons:
            skipped.append({"path": str(resolved), "reason": "not_current_junk_candidate"})
            continue
        resolved.unlink()
        deleted.append(str(resolved))

    return {"deleted": deleted, "skipped": skipped}
