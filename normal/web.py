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
    scan_movie_junk,
    scan_movie_promo_documents,
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
from normal.movie_artwork import apply_movie_posters, scan_movie_posters
from normal.movie_subtitle_fix import fix_movie_subtitle_defaults
from normal.movie_subtitle_history import (
    dismiss_items as dismiss_subtitle_history_items,
    history_for_source as subtitle_history_for_source,
    upsert_items as upsert_subtitle_history_items,
)
from normal.music_profile import build_music_histogram_payload, scan_music_profiles
from normal.movie_replacement_queue import (
    add_profile_items_to_queue,
    clear_pending_queue_items,
    delete_replacement_queue_media,
    dismiss_replacement_queue_items,
    queue_for_source,
    reconcile_replacement_queue,
)
from normal.music_replacement_queue import (
    add_profile_items_to_queue as music_add_profile_items_to_queue,
    delete_replacement_queue_media as music_delete_replacement_queue_media,
    queue_for_source as music_queue_for_source,
    reconcile_replacement_queue as music_reconcile_replacement_queue,
)
from normal.movie_scan import discover_video_files, probe_media_facts, scan_movie_library
from normal.output import write_movie_register_xlsx
from normal.apply import apply_changes_in_place
from normal.models import ProposedChange, utc_now_iso
from normal.plan import build_plan
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts
from normal.artwork import (
    PROVENANCE_FILENAME,
    ArtworkGapItem,
    apply_artwork,
    backfill_jellyfin_artist_artwork,
    find_album_artwork_candidates,
    find_image_search_artist_candidates,
    find_web_artist_candidates,
    resolve_cached_artwork,
    resolve_data_url_artwork,
    resolve_file_artwork,
    resolve_remote_artwork,
    scan_artist_artwork,
    search_wikimedia_artist_candidates,
)


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


def media_facts_from_dict(payload: dict[str, Any]) -> MediaFacts:
    audio_streams = []
    for raw_stream in payload.get("audio_streams", []):
        if isinstance(raw_stream, dict):
            audio_streams.append(AudioStreamFacts(**raw_stream))
    subtitle_streams = []
    for raw_stream in payload.get("subtitle_streams", []):
        if isinstance(raw_stream, dict):
            subtitle_streams.append(SubtitleStreamFacts(**raw_stream))
    normalized = dict(payload)
    normalized["audio_streams"] = audio_streams
    normalized["subtitle_streams"] = subtitle_streams
    return MediaFacts(**normalized)


ACTIVITY_TRACKER = ActivityTracker()
HEAVY_SCAN_REGISTRY = HeavyScanRegistry()


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
      --music: #2d5ea8;
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
      transition: transform 120ms ease, opacity 120ms ease;
    }
    button:hover { transform: translateY(-1px); }
    button:disabled { opacity: 0.45; cursor: not-allowed; transform: none; }
    .primary { background: var(--accent); color: white; }
    .secondary { background: var(--btn-secondary); color: var(--ink); }
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
    }
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
    .chip.playback { background: rgba(15,92,77,0.12); color: var(--accent); border-color: rgba(15,92,77,0.2); }
    .chip.indexing { background: rgba(138,91,0,0.12); color: var(--warn); border-color: rgba(138,91,0,0.2); }
    .chip.meta { background: rgba(45,94,168,0.12); color: var(--music); border-color: rgba(45,94,168,0.2); }
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
    .artwork-drop-zone {
      width: 100%;
      max-width: 340px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      color: var(--muted);
      background: var(--surface);
      font-size: 13px;
      margin: 10px 0 12px;
    }
    .artwork-drop-zone.dragover {
      border-color: var(--accent);
      background: var(--accent-glow);
      color: var(--ink);
    }
    .artist-tile {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow: hidden;
      cursor: pointer;
      min-width: 0;
      padding: 0;
      text-align: left;
      color: var(--ink);
      font-family: inherit;
    }
    .artist-tile:hover { border-color: color-mix(in srgb, var(--music) 45%, var(--line)); }
    .artist-art {
      aspect-ratio: 1 / 1;
      width: 100%;
      background: var(--bar-track);
      display: grid;
      place-items: center;
      overflow: hidden;
    }
    .artist-art img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .artist-art.missing {
      border-bottom: 1px dashed var(--line);
      color: var(--muted);
      font-size: 12px;
      text-align: center;
      padding: 12px;
    }
    .artist-meta {
      padding: 9px 10px 10px;
      min-height: 74px;
    }
    .artist-name {
      font-size: 13px;
      font-weight: 700;
      line-height: 1.25;
      overflow-wrap: anywhere;
      margin-bottom: 7px;
    }
    .artist-path {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.25;
      overflow-wrap: anywhere;
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
        <h1 id="heroTitle">Music + Movies</h1>
        <p class="lede" id="heroLede">Two operational lanes: one curatorial for music, one diagnostic for movies. Same shell, different semantics.</p>
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
      musicQualitySort: { col: null, dir: 'asc' },
      movieAudioFixBusy: false,
      movieSubtitleFixBusy: false,
      subtitleHistory: null,
      subtitleHistoryFilter: 'all',
      movieStandardsEditorLabel: '',
      movieStandardsSaveBusy: false,
      movieStandardsPendingDraft: null,
      replacementHistoryFilter: 'deleted',
      replacementHistorySort: { col: null, dir: 'asc' },
      omdbRatings: new Map(),
      omdbStatus: '',
      selectedJunkPaths: new Set(),
      selectedReplacementPaths: new Set(),
      selectedChangeIds: new Set(),
      movieNamingStyle: 'concise',
      selectedArtistNames: new Set(),
      approvedArtworkCandidates: {},
      approvedMoviePosterCandidates: {},
      artworkCandidates: {},
      artworkImageSearchOffsets: {},
      results: {
        music: { profile: null, normalize: null, apply: null, artwork: null, replacementQueue: null, replacementQueueSource: '' },
        movies: { profile: null, canonical: null, normalize: null, apply: null, junk: null, promo: null, artwork: null, replacementQueue: null, replacementQueueSource: '' }
      }
    };

    const CONFIG = {
      music: {
        title: 'Music',
        lede: 'Clean, complete, and browse your FLAC library. Diagnostics here are about metadata, artwork readiness, and safe normalization work.',
        sourceLabel: '/path/to/music library',
        pages: [
          { id: 'library', label: 'Dashboard View', action: 'scan', endpoint: '/api/music/profile' },
          { id: 'normalize', label: 'Normalize Music Files & Folders', action: 'plan', endpoint: '/api/music/normalize' },
          { id: 'music_quality', label: 'Delete Weak Encodes', action: 'scan', endpoint: '/api/music/profile' },
          { id: 'artwork', label: 'Repair Artwork for Jellyfin', action: 'scan', endpoint: '/api/music/artwork/scan' },
          { id: 'recommend', label: 'Music Recommendation Engine', action: 'scan' }
        ]
      },
      movies: {
        title: 'Movies',
        lede: 'Assess, fix, and standardize your movie and TV library. Diagnostics here focus on quality, compatibility, and repairable playback or visibility issues.',
        sourceLabel: '/path/to/movie or TV library',
        pages: [
          { id: 'library', label: 'Dashboard View', action: 'scan', endpoint: '/api/movies/profile' },
          { id: 'normalize', label: 'Normalize Movie Files & Folders', action: 'plan', endpoint: '/api/movies/normalize' },
          { id: 'quality', label: 'Delete Weak Encodes', action: 'scan', endpoint: '/api/movies/profile' },
          { id: 'audio_packaging', label: 'Fix Multi-Audio Packaging', action: 'scan', endpoint: '/api/movies/profile' },
          { id: 'subtitle_readiness', label: 'Repair Subtitle Readiness', action: 'scan', endpoint: '/api/movies/profile' },
          { id: 'movie_artwork', label: 'Repair Artwork for Plex', action: 'scan', endpoint: '/api/movies/artwork/scan' },
          { id: 'junk', label: 'Delete Junk Videos', action: 'scan', endpoint: '/api/movies/junk' },
          { id: 'promo', label: 'Delete Junk Sidecar & Spam Files', action: 'scan', endpoint: '/api/movies/promo-docs' },
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
          music: typeof roots.music === 'string' ? roots.music : '',
          movies: typeof roots.movies === 'string' ? roots.movies : ''
        };
      } catch {
        return { music: '', movies: '' };
      }
    })();
    let _recentLibraries = (() => {
      try {
        const recent = JSON.parse(localStorage.getItem('n_recent_libraries') || '[]');
        if (!Array.isArray(recent)) return [];
        return recent
          .filter(item => item && ['music', 'movies'].includes(item.lane) && typeof item.source === 'string' && item.source)
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
        const cache = JSON.parse(localStorage.getItem('n_movie_canonical_lists_cache_v2') || '{}');
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
    let _musicDashboardCache = (() => {
      try {
        const cache = JSON.parse(localStorage.getItem('n_music_dashboard_cache') || '{}');
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
        body: JSON.stringify({ music: _libraryRoots.music, movies: _libraryRoots.movies, recent: _recentLibraries })
      }).catch(() => {});
    }

    function persistRecentLibraries() {
      try { localStorage.setItem('n_recent_libraries', JSON.stringify(_recentLibraries)); } catch {}
      fetch('/api/library-roots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ music: _libraryRoots.music, movies: _libraryRoots.movies, recent: _recentLibraries })
      }).catch(() => {});
    }

    function persistMovieDashboardCache() {
      try { localStorage.setItem('n_movie_dashboard_cache_v2', JSON.stringify(_movieDashboardCache)); } catch {}
    }

    function persistMovieCanonicalListsCache() {
      try { localStorage.setItem('n_movie_canonical_lists_cache_v2', JSON.stringify(_movieCanonicalListsCache)); } catch {}
    }

    function persistMovieReplacementQueueCache() {
      try { localStorage.setItem('n_movie_replacement_queue_cache', JSON.stringify(_movieReplacementQueueCache)); } catch {}
    }

    function persistMusicDashboardCache() {
      try { localStorage.setItem('n_music_dashboard_cache', JSON.stringify(_musicDashboardCache)); } catch {}
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

    function cacheMusicDashboard(payload) {
      if (!payload || !payload.source_root || !payload.histogram) return;
      _musicDashboardCache[dashboardCacheKey(payload.source_root)] = {
        source_root: payload.source_root,
        histogram: payload.histogram,
        cached_at: new Date().toISOString()
      };
      _musicDashboardCache = trimDashboardCache(_musicDashboardCache);
      persistMusicDashboardCache();
    }

    function cachedMusicDashboard(source) {
      const cached = _musicDashboardCache[dashboardCacheKey(source)];
      if (!cached || !cached.histogram) return null;
      return {
        source_root: cached.source_root || source,
        histogram: cached.histogram,
        tracks: []
      };
    }

    function currentMusicProfileForSource() {
      const source = sourceInput.value.trim();
      const profile = state.results.music.profile;
      return profile && profile.source_root === source ? profile : null;
    }

    function restoreCachedMusicDashboard(source) {
      const cached = cachedMusicDashboard(source);
      if (!cached) return null;
      state.results.music.profile = cached;
      return cached;
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
      if (lane === 'music') restoreCachedMusicDashboard(source);
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
      if (item.lane === 'music') restoreCachedMusicDashboard(item.source);
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
      const rootRows = ['movies', 'music'].map(lane => {
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
    }

    sourceInput.value = window.DEFAULT_SOURCE || _libraryRoots.movies || '';
    renderLibraryRoots();

    fetch('/api/library-roots').then(r => r.json()).then(data => {
      let changed = false;
      if (data.music && data.music !== _libraryRoots.music) { _libraryRoots.music = data.music; changed = true; }
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
      const p = sourceInput.value;
      const lower = p.toLowerCase();
      const musicIdx = lower.lastIndexOf('music');
      const moviesIdx = lower.lastIndexOf('movie');
      refreshActivityState();
      if (musicIdx === -1 && moviesIdx === -1) return;
      const detectedLane = moviesIdx > musicIdx ? 'movies' : 'music';
      if (detectedLane !== state.lane) setLane(detectedLane);
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
            --music: #5856d6;
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
            --music: #000080;
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
            --music: #1db954;
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
            --music: #00ff41;
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
      state.qualitySort = { col: null, dir: 'asc' };
      state.musicQualitySort = { col: null, dir: 'asc' };
      state.subtitleSort = { col: null, dir: 'asc' };
      state.replacementHistoryFilter = 'deleted';
      state.replacementHistorySort = { col: null, dir: 'asc' };
      renderPageNav();
      renderCurrentPage();
    }

    function renderPageNav() {
      pageNav.innerHTML = CONFIG[state.lane].pages.map(page => `
        <button class="page-button ${page.id === state.page ? 'active' : ''}" data-page="${page.id}">${page.label}</button>
      `).join('');
      pageNav.querySelectorAll('.page-button').forEach(button => button.addEventListener('click', () => setPage(button.dataset.page)));
    }

    async function generateCatalogue(btn) {
      const source = sourceInput.value.trim();
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
      if (state.lane === 'music') {
        if (page === 'library') {
          state.results.music.profile = payload;
          cacheMusicDashboard(payload);
        }
        if (page === 'music_quality') {
          state.results.music.profile = payload;
          cacheMusicDashboard(payload);
          if (payload.replacement_queue) {
            state.results.music.replacementQueue = payload.replacement_queue;
            state.results.music.replacementQueueSource = payload.source_root || '';
          }
          state.selectedReplacementPaths.clear();
        }
        if (page === 'artwork') {
          state.results.music.artwork = payload;
          state.approvedArtworkCandidates = {};
          state.artworkCandidates = {};
          state.artworkImageSearchOffsets = {};
          state.selectedArtistNames = new Set((payload.present || []).filter(item => item.source === 'jellyfin').map(item => item.artist_name));
        }
        if (page === 'normalize') {
          state.results.music.normalize = payload;
          state.results.music.apply = null;
          state.selectedChangeIds = new Set();
        }
      } else {
        if (['library', 'quality', 'audio_packaging', 'subtitle_readiness', 'compatibility'].includes(page)) {
          state.results.movies.profile = payload;
          cacheMovieDashboard(payload);
          if (payload.replacement_queue) {
            state.results.movies.replacementQueue = payload.replacement_queue;
            state.results.movies.replacementQueueSource = payload.source_root || '';
            cacheMovieReplacementQueue(payload.replacement_queue);
          }
          state.selectedReplacementPaths.clear();
          if (page === 'subtitle_readiness') {
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
        }
        if (page === 'junk') {
          state.results.movies.junk = payload;
          state.selectedJunkPaths.clear();
        }
        if (page === 'promo') {
          state.results.movies.promo = payload;
          state.selectedJunkPaths.clear();
        }
        if (page === 'movie_artwork') {
          state.results.movies.artwork = payload;
          state.approvedMoviePosterCandidates = {};
        }
      }
    }

    function renderCurrentPage() {
      const lane = state.lane;
      const page = state.page;
      const titleMap = {
        normalize: 'Normalize',
        artwork: 'Artwork',
        recommend: 'Recommend',
        canonical_lists: 'Canonical Lists',
        quality: 'Delete Weak Encodes',
        audio_packaging: 'Fix Multi-Audio Packaging',
        subtitle_readiness: 'Repair Subtitle Readiness',
        movie_artwork: 'Repair Artwork for Plex',
        music_quality: 'Delete Weak Encodes',
        compatibility: 'Compatibility',
        junk: 'Delete Junk Videos',
        promo: 'Delete Junk Sidecar & Spam Files',
        library: 'Dashboard'
      };
      mainTitle.textContent = `${CONFIG[lane].title} / ${titleMap[page]}`;
      if (lane === 'music') renderMusicPage(page);
      else renderMoviePage(page);
    }

    function renderMusicPage(page) {
      const source = sourceInput.value.trim();
      const profile = currentMusicProfileForSource();
      const normalize = state.results.music.normalize;
      if (page === 'library') {
        renderMusicLibrary(profile || restoreCachedMusicDashboard(source));
        return;
      }
      if (page === 'normalize') {
        renderMusicNormalize(normalize);
        return;
      }
      if (page === 'artwork') {
        renderMusicArtwork(state.results.music.artwork);
        return;
      }
      if (page === 'music_quality') {
        loadMusicReplacementQueue();
        renderMusicQuality(profile);
        return;
      }
      renderPlaceholder(
        'Recommendation workflow next',
        ['artist/album recommendation sets', 'related release clusters', 'curatorial discovery tools']
      );
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
      if (page === 'promo') {
        renderMovieJunk(state.results.movies.promo);
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
      if (page === 'audio_packaging') {
        loadMovieReplacementQueue();
        renderMovieAudioPackaging(profile);
        return;
      }
      if (page === 'subtitle_readiness') {
        renderMovieSubtitleReadiness(profile);
        return;
      }
      if (page === 'movie_artwork') {
        renderMovieArtwork(state.results.movies.artwork);
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
        else if (state.page === 'audio_packaging' && state.results.movies.profile) renderMovieAudioPackaging(state.results.movies.profile);
        else if (state.page === 'subtitle_readiness' && state.results.movies.profile) renderMovieSubtitleReadiness(state.results.movies.profile);
        else renderReplacementQueueDetail(state.results.movies.profile);
      } catch (error) {
        detailPanel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      }
    }

    async function loadMusicReplacementQueue(force = false) {
      const source = sourceInput.value.trim();
      if (!source) {
        renderMusicReplacementQueueDetail(state.results.music.profile);
        return;
      }
      if (!force && state.results.music.replacementQueue && state.results.music.replacementQueueSource === source) {
        renderMusicReplacementQueueDetail(state.results.music.profile);
        return;
      }
      try {
        const response = await fetch('/api/music/replacement-queue/list', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Queue load failed.');
        state.results.music.replacementQueue = result;
        state.results.music.replacementQueueSource = source;
        if (state.results.music.profile) state.results.music.profile.replacement_queue = result;
        if (state.page === 'music_quality' && state.results.music.profile) renderMusicQuality(state.results.music.profile);
        else renderMusicReplacementQueueDetail(state.results.music.profile);
      } catch (error) {
        detailPanel.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      }
    }

    function renderMusicQuality(payload) {
      mainTagline.textContent = 'Weak encodes in the music library. Shows mp3_trash and unknown_unreadable tracks for removal.';
      renderMetrics(buildMusicQualityMetrics(payload));
      renderBars(buildMusicQualityBars(payload));
      filterBar.innerHTML = '';
      if (!payload) {
        mainContent.innerHTML = '<div class="empty">Run Music / Delete Weak Encodes to see profile results.</div>';
        return;
      }
      mainContent.innerHTML = buildMusicQualityTable(payload, sortedMusicTracks(strictWeakTracks(payload)));
      renderMusicReplacementQueueDetail(payload);
      attachMusicReplacementHandlers(payload);
    }

    function buildMusicQualityMetrics(payload) {
      if (!payload) return [];
      const tracks = payload.tracks || [];
      const weak = tracks.filter(isStrictWeakTrack);
      const queue = currentMusicReplacementQueue(payload);
      const queueItems = queue?.items || [];
      const pending = queueItems.filter(i => i.status === 'pending').length;
      const deleted = queueItems.filter(i => i.status === 'deleted').length;
      return [
        { value: String(tracks.length), label: 'total tracks' },
        { value: String(weak.length), label: 'weak tracks' },
        { value: String(pending), label: 'pending delete' },
        { value: String(deleted), label: 'deleted' },
      ];
    }

    function buildMusicQualityBars(payload) {
      if (!payload) return [];
      const tracks = payload.tracks || [];
      const total = Math.max(tracks.length, 1);
      const weak = tracks.filter(isStrictWeakTrack).length;
      return [
        { label: 'weak tracks', value: String(weak), width: (weak / total) * 100 },
      ];
    }

    function buildMusicQualityTable(payload, items) {
      const queue = currentMusicReplacementQueue(payload);
      const queueItems = queue?.items || [];
      const qPending = queueItems.filter(i => i.status === 'pending').length;
      const qDeleted = queueItems.filter(i => i.status === 'deleted').length;
      const qCompleted = queueItems.filter(i => i.status === 'completed').length;
      const qSource = sourceInput.value.trim() || queue?.source_root || '';
      const queueSummary = (qPending || qDeleted || qCompleted || qDismissed) ? `
        <div class="finding">
          <h3>Replacement Queue</h3>
          <p>${qPending} pending delete · ${qDeleted} deleted and waiting replacement · ${qCompleted} successfully replaced</p>
          ${qSource ? `<p><strong>Directory:</strong> <span class="mono">${escapeHtml(qSource)}</span></p>` : ''}
        </div>
      ` : '';
      const rows = items.map(item => {
        const path = item.path || '';
        const isWeak = isStrictWeakTrack(item);
        const queueItem = musicReplacementQueueItemForPath(payload, path);
        const checked = state.selectedReplacementPaths.has(path) ? 'checked' : '';
        const bitrate = item.facts.bitrate_kbps ? `${Math.round(item.facts.bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
        const sampleRate = item.facts.sample_rate_hz ? `${(item.facts.sample_rate_hz / 1000).toLocaleString()} kHz` : '<span class="subtle">—</span>';
        const fileSize = item.facts.file_size_bytes ? fmtFileSize(item.facts.file_size_bytes) : '<span class="subtle">—</span>';
        const format = item.facts.format ? item.facts.format.toUpperCase() : '<span class="subtle">—</span>';
        const selectable = isWeak && !queueItem;
        return `
          <tr>
            <td style="width:28px;text-align:center">${selectable ? `<input type="checkbox" class="music-replacement-select" data-path="${encodeURIComponent(path)}" ${checked}>` : ''}</td>
            <td><div class="mono">${escapeHtml(path)}</div></td>
            <td>${escapeHtml(humanMusicProfileLabel(item.profile.label))}</td>
            <td>${format}</td>
            <td>${bitrate}</td>
            <td>${sampleRate}</td>
            <td>${fileSize}</td>
            <td>${musicReplacementQueueStatusChip(queueItem)}</td>
          </tr>
        `;
      }).join('');
      const selectedCount = selectedVisibleMusicReplacementCount(payload, items);
      const selectableCount = selectableMusicReplacementItems(payload, items).length;
      const allVisibleSelected = selectableCount > 0 && selectedCount === selectableCount;
      const toggleLabel = allVisibleSelected ? 'Deselect All' : 'Select All';
      return `
        ${queueSummary}
        <div class="junk-actions">
          <button class="secondary" id="toggleAllMusicReplacementButton" ${selectableCount ? '' : 'disabled'}>${toggleLabel}</button>
          <button class="danger" id="deleteMusicSelectedFilesButton" ${selectedCount ? '' : 'disabled'}>Delete Selected Files</button>
          <span class="subtle">${selectedCount} of ${selectableCount} selected</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th>${['file','profile','format','bitrate','sample_rate','file_size'].map(col => { const active = state.musicQualitySort.col === col; const ind = active ? (state.musicQualitySort.dir === 'asc' ? '↑' : '↓') : '↕'; const label = {file:'File',profile:'Profile',format:'Format',bitrate:'Bitrate',sample_rate:'Sample Rate',file_size:'File Size'}[col]; return `<th class="music-sortable-th sortable-th" data-sort-col="${col}">${label}<span class="sort-ind${active?' on':''}">${ind}</span></th>`; }).join('')}<th>Status</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="8" class="subtle">No weak tracks found.</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function currentMusicReplacementQueue(payload) {
      return payload?.replacement_queue || state.results.music.replacementQueue || null;
    }

    function musicReplacementQueueItemForPath(payload, path) {
      if (!path) return null;
      return (currentMusicReplacementQueue(payload)?.items || []).find(item =>
        item.original_path === path && ['pending', 'deleted', 'completed'].includes(item.status)
      ) || null;
    }

    function musicReplacementQueueStatusChip(item) {
      if (!item) return '<span class="subtle">—</span>';
      if (item.status === 'pending') return '<span class="chip meta">queued</span>';
      if (item.status === 'deleted') return '<span class="chip review">deleted, waiting replacement</span>';
      if (item.status === 'completed') return '<span class="chip safe">replaced</span>';
      return '<span class="subtle">—</span>';
    }

    function isStrictWeakTrack(item) {
      return ['mp3_trash', 'unknown_unreadable'].includes(item?.profile?.label || '');
    }

    function strictWeakTracks(payload) {
      return (payload?.tracks || []).filter(isStrictWeakTrack);
    }

    function selectedVisibleMusicReplacementCount(payload, items) {
      return selectableMusicReplacementItems(payload, items).filter(item => state.selectedReplacementPaths.has(item.path)).length;
    }

    function selectableMusicReplacementItems(payload, items) {
      return items.filter(item => isStrictWeakTrack(item) && item.path && !musicReplacementQueueItemForPath(payload, item.path));
    }

    function sortedMusicTracks(items) {
      const { col, dir } = state.musicQualitySort;
      if (!col) return items;
      const mult = dir === 'asc' ? 1 : -1;
      return [...items].sort((a, b) => {
        if (col === 'file') return mult * (a.path || '').split('/').pop().localeCompare((b.path || '').split('/').pop(), undefined, { sensitivity: 'base' });
        if (col === 'profile') return mult * ((a.profile?.rank || 0) - (b.profile?.rank || 0));
        if (col === 'format') return mult * (a.facts?.format || '').localeCompare(b.facts?.format || '', undefined, { sensitivity: 'base' });
        if (col === 'bitrate') return mult * ((a.facts?.bitrate_kbps || 0) - (b.facts?.bitrate_kbps || 0));
        if (col === 'sample_rate') return mult * ((a.facts?.sample_rate_hz || 0) - (b.facts?.sample_rate_hz || 0));
        if (col === 'file_size') return mult * ((a.facts?.file_size_bytes || 0) - (b.facts?.file_size_bytes || 0));
        return 0;
      });
    }

    function attachMusicReplacementHandlers(payload) {
      const items = selectableMusicReplacementItems(payload, sortedMusicTracks(strictWeakTracks(payload)));
      document.querySelectorAll('.music-replacement-select').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
          const path = decodeURIComponent(checkbox.dataset.path);
          if (checkbox.checked) state.selectedReplacementPaths.add(path);
          else state.selectedReplacementPaths.delete(path);
          renderMusicQuality(payload);
          renderMusicReplacementQueueDetail(payload);
        });
      });
      const toggleAllButton = document.getElementById('toggleAllMusicReplacementButton');
      if (toggleAllButton) {
        toggleAllButton.addEventListener('click', () => {
          const selectedCount = selectedVisibleMusicReplacementCount(payload, items);
          const allVisibleSelected = items.length > 0 && selectedCount === items.length;
          items.forEach(item => {
            if (!item.path) return;
            if (allVisibleSelected) state.selectedReplacementPaths.delete(item.path);
            else state.selectedReplacementPaths.add(item.path);
          });
          renderMusicQuality(payload);
          renderMusicReplacementQueueDetail(payload);
        });
      }
      const fileButton = document.getElementById('deleteMusicSelectedFilesButton');
      if (fileButton) fileButton.addEventListener('click', () => deleteMusicSelectedFiles());
      document.querySelectorAll('.music-sortable-th').forEach(th => {
        th.addEventListener('click', () => {
          const col = th.dataset.sortCol;
          if (state.musicQualitySort.col === col) {
            state.musicQualitySort.dir = state.musicQualitySort.dir === 'asc' ? 'desc' : 'asc';
          } else {
            state.musicQualitySort = { col, dir: 'asc' };
          }
          renderMusicQuality(payload);
          renderMusicReplacementQueueDetail(payload);
        });
      });
    }

    function renderMusicReplacementQueueDetail(payload) {
      const queue = currentMusicReplacementQueue(payload);
      const queueItems = queue?.items || [];
      const pending = queueItems.filter(item => item.status === 'pending');
      const deleted = queueItems.filter(item => item.status === 'deleted');
      const completed = queueItems.filter(item => item.status === 'completed');
      const pendingRows = pending.length ? buildMusicPendingReplacementTable(pending) : '';
      const deletedRows = deleted.slice(0, 8).map(item => {
        const label = [item.album_artist || item.artist, item.album].filter(Boolean).join(' — ') || item.original_path || '';
        return `
          <div class="finding">
            <h3>${escapeHtml(label)}</h3>
            <p>deleted, waiting replacement</p>
            <p class="mono">${escapeHtml(item.original_path || '')}</p>
          </div>
        `;
      }).join('');
      const completedRows = completed.slice(0, 8).map(item => {
        const label = [item.album_artist || item.artist, item.album].filter(Boolean).join(' — ') || item.original_path || '';
        return `
          <div class="finding">
            <h3>${escapeHtml(label)}</h3>
            <p>successfully replaced</p>
            <p class="mono">${escapeHtml(item.completed_by_path || '')}</p>
          </div>
        `;
      }).join('');
      detailPanel.innerHTML = `
        ${pendingRows ? `<div style="font-weight:600;margin:10px 0 6px">Pending Delete</div>${pendingRows}` : ''}
        ${deletedRows ? `<div style="font-weight:600;margin:10px 0 6px">Deleted, Waiting Replacement</div>${deletedRows}` : ''}
        ${completedRows ? `<div style="font-weight:600;margin:10px 0 6px">Successfully Replaced</div>${completedRows}` : ''}
        ${!pendingRows && !deletedRows && !completedRows ? '<div class="empty">No items in the music replacement queue.</div>' : ''}
      `;
      attachMusicReplacementQueueDetailHandlers();
    }

    function buildMusicPendingReplacementTable(items) {
      const rows = items.slice(0, 8).map(item => {
        const label = [item.album_artist || item.artist, item.album].filter(Boolean).join(' — ') || item.original_path || '';
        const bitrate = item.bitrate_kbps ? `${Math.round(item.bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
        return `
          <tr>
            <td>${escapeHtml(label)}</td>
            <td>${escapeHtml(humanMusicProfileLabel(item.original_profile_label || ''))}</td>
            <td>${bitrate}</td>
            <td><button class="danger music-replacement-delete" data-item-id="${escapeHtml(item.item_id)}">Delete media</button></td>
          </tr>
        `;
      }).join('');
      return `
        <div class="table-wrap">
          <table>
            <thead><tr><th>Album</th><th>Profile</th><th>Bitrate</th><th>Action</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="4" class="subtle">No pending delete items.</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function attachMusicReplacementQueueDetailHandlers() {
      document.querySelectorAll('.music-replacement-delete').forEach(button => {
        button.addEventListener('click', () => deleteMusicReplacementMedia([button.dataset.itemId]));
      });
    }

    async function deleteMusicSelectedFiles() {
      const source = sourceInput.value.trim();
      const payload = state.results.music.profile;
      if (!source || !payload) return;
      const items = (payload.tracks || []).filter(item =>
        state.selectedReplacementPaths.has(item.path || '') &&
        isStrictWeakTrack(item) &&
        !musicReplacementQueueItemForPath(payload, item.path || '')
      );
      if (!items.length) return;
      const message = `Permanently delete ${items.length} file${items.length === 1 ? '' : 's'}? This cannot be undone.`;
      if (!window.confirm(message)) return;
      setStatus(`Deleting ${items.length} file${items.length === 1 ? '' : 's'}…`, 'running');
      try {
        const addResponse = await fetch('/api/music/replacement-queue/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, items })
        });
        const addResult = await addResponse.json();
        if (!addResponse.ok) throw new Error(addResult.error || 'Queue failed.');
        const itemIds = (addResult.added || []).map(i => i.item_id).filter(Boolean);
        if (!itemIds.length) { setStatus('Nothing to delete.', 'idle'); return; }
        const delResponse = await fetch('/api/music/replacement-queue/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, item_ids: itemIds })
        });
        const delResult = await delResponse.json();
        if (!delResponse.ok) throw new Error(delResult.error || 'Delete failed.');
        state.results.music.replacementQueue = delResult;
        state.results.music.replacementQueueSource = source;
        if (state.results.music.profile) state.results.music.profile.replacement_queue = delResult;
        state.selectedReplacementPaths.clear();
        const skipped = delResult.skipped?.length || 0;
        const sidecars = delResult.cleaned_sidecars?.length || 0;
        const folders = delResult.removed_folders?.length || 0;
        const cleanup = sidecars || folders ? `; cleaned ${sidecars} sidecar${sidecars === 1 ? '' : 's'}${folders ? ` and ${folders} folder${folders === 1 ? '' : 's'}` : ''}` : '';
        setStatus(`Deleted ${delResult.deleted.length} file${delResult.deleted.length === 1 ? '' : 's'}${cleanup}${skipped ? `; skipped ${skipped}` : ''}.`, 'idle');
        renderMusicQuality(state.results.music.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    async function deleteMusicReplacementMedia(itemIds) {
      const queue = currentMusicReplacementQueue(state.results.music.profile);
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
        const response = await fetch('/api/music/replacement-queue/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, item_ids: itemIds })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Delete failed.');
        state.results.music.replacementQueue = result;
        state.results.music.replacementQueueSource = source;
        if (state.results.music.profile) state.results.music.profile.replacement_queue = result;
        const skipped = result.skipped?.length || 0;
        const sidecars = result.cleaned_sidecars?.length || 0;
        const folders = result.removed_folders?.length || 0;
        const cleanup = sidecars || folders ? `; cleaned ${sidecars} sidecar${sidecars === 1 ? '' : 's'}${folders ? ` and ${folders} folder${folders === 1 ? '' : 's'}` : ''}` : '';
        setStatus(`Deleted ${result.deleted.length} item${result.deleted.length === 1 ? '' : 's'}${cleanup}${skipped ? `; skipped ${skipped}` : ''}.`, 'idle');
        if (state.page === 'music_quality') renderMusicQuality(state.results.music.profile);
        else renderMusicReplacementQueueDetail(state.results.music.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    function renderMusicLibrary(payload) {
      mainTagline.textContent = 'Collection overview: format mix, fidelity profile, artwork readiness, and early library signals.';
      renderMetrics(buildMusicDashboardMetrics(payload));
      renderBars(buildMusicDashboardBars(payload));
      filterBar.innerHTML = '';
      mainContent.innerHTML = buildMusicDashboard(payload);
      if (!payload) {
        detailPanel.innerHTML = '<div class="empty">Run Music / Dashboard to profile the library.</div>';
        return;
      }
      detailPanel.innerHTML = buildMusicProfileDetail(payload);
    }

    function buildMusicDashboard(payload) {
      if (!payload) return '<div class="empty">Run Music / Dashboard to profile the library.</div>';
      const histogram = payload.histogram || {};
      const total = histogram.track_count ?? (payload.tracks || []).length;
      const profileCounts = histogram.profile_counts || {};
      const topProfile = Object.entries(profileCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || '';
      const statsHtml = `
        <div class="dash-stats">
          <div class="metric"><strong>${total.toLocaleString()}</strong><span>tracks</span></div>
          <div class="metric"><strong>${String(histogram.album_count ?? 0)}</strong><span>albums</span></div>
          <div class="metric"><strong>${String(histogram.artist_count ?? 0)}</strong><span>album artists</span></div>
          <div class="metric"><strong>${formatDashboardSize(histogram.total_size_bytes)}</strong><span>total size</span></div>
          <div class="metric"><strong>${escapeHtml(humanMusicProfileLabel(topProfile || '—'))}</strong><span>dominant profile</span></div>
        </div>
      `;
      const PROFILE_ORDER = [
        'mp3_trash', 'mp3_high_quality', 'flac_other',
        'flac_44_1', 'flac_16_44_1', 'flac_24_44_1',
        'flac_48', 'flac_16_48', 'flac_24_48',
        'flac_88_2', 'flac_16_88_2', 'flac_24_88_2',
        'flac_96', 'flac_16_96', 'flac_24_96',
        'flac_176_4', 'flac_16_176_4', 'flac_24_176_4',
        'flac_192', 'flac_16_192', 'flac_24_192',
        'unknown_unreadable'
      ];
      const maxCount = Math.max(...Object.values(profileCounts), 1);
      const profileCardsHtml = PROFILE_ORDER.filter(label => profileCounts[label]).map(label => {
        const count = profileCounts[label];
        const pct = total ? ((count / total) * 100).toFixed(1) : '0.0';
        const barWidth = (count / maxCount) * 100;
        return `
          <div class="profile-card">
            <div class="profile-card-group">${escapeHtml(musicProfileGroup(label))}</div>
            <div class="profile-card-name">${escapeHtml(humanMusicProfileLabel(label))}</div>
            <div class="profile-card-count">${count.toLocaleString()}</div>
            <div class="profile-card-pct">${pct}% of library</div>
            <div class="profile-card-bar"><span style="width:${barWidth}%"></span></div>
          </div>
        `;
      }).join('');
      const formatCounts = histogram.format_counts || {};
      const formatMax = Math.max(...Object.values(formatCounts), 1);
      const formatBarsHtml = Object.entries(formatCounts).sort((a, b) => b[1] - a[1]).map(([label, count]) => `
        <div class="bar-row">
          <span>${escapeHtml(label.toUpperCase())}</span>
          <div class="bar"><span style="width:${(count / formatMax) * 100}%"></span></div>
          <strong>${count}</strong>
        </div>
      `).join('');
      const warningCount = histogram.warning_count || 0;
      const signalHtml = `
        <div class="dash-section-label">Signals Under Development</div>
        <div class="dash-risk-row">
          <span class="chip review">feature confidence: low</span>
          <span class="chip ${warningCount ? 'review' : 'safe'}">unreadable / unknown: ${profileCounts.unknown_unreadable || 0}</span>
          <span class="chip review">music risk flags: not reliable yet</span>
        </div>
      `;
      return `
        ${statsHtml}
        <div class="dash-section-label">Quality Profiles</div>
        <div class="profile-grid">${profileCardsHtml || '<div class="subtle">No profile data.</div>'}</div>
        <div class="dash-section-label">Format / Fidelity Breakdown</div>
        <div class="dash-res-bars bars">${formatBarsHtml || '<div class="subtle">No format data.</div>'}</div>
        ${signalHtml}
      `;
    }

    function buildMusicProfileDetail(payload) {
      const histogram = payload.histogram || {};
      const counts = histogram.sample_rate_counts || {};
      const entries = Object.entries(counts).sort((a, b) => {
        if (a[0] === 'unknown') return 1;
        if (b[0] === 'unknown') return -1;
        return parseFloat(a[0]) - parseFloat(b[0]);
      });
      const max = Math.max(...entries.map(([, value]) => value), 1);
      const rows = entries.map(([label, value]) => `
        <div class="bar-row">
          <span>${escapeHtml(label)}</span>
          <div class="bar"><span style="width:${(value / max) * 100}%"></span></div>
          <strong>${value}</strong>
        </div>
      `).join('');
      return `
        <div class="finding" style="padding:14px 16px 14px">
          <div class="dash-section-label">Sample Rate Distribution</div>
          <div class="bars">${rows || '<div class="subtle">No sample-rate data.</div>'}</div>
        </div>
      `;
    }

    function renderMusicNormalize(payload) {
      mainTagline.textContent = 'Review proposed changes, approve, and apply.';
      renderMetrics(buildMusicNormalizeMetrics(payload));
      renderBars(buildMusicNormalizeBars(payload));

      const applyResult = state.results.music.apply;

      if (!payload) {
        filterBar.innerHTML = '';
        const applyBanner = applyResult ? buildApplyResultBanner(applyResult) : '';
        mainContent.innerHTML = applyBanner + '<div class="empty">Run Music / Normalize to generate a plan of tag, file, and folder fixes.</div>';
        showNormalizeTreeDetail(null);
        return;
      }

      renderFilters([
        ['all', 'All'],
        ['safe', 'Safe'],
        ['review', 'Review'],
        ['warnings', 'Warnings']
      ]);

      const changes = filteredMusicChanges(payload);
      const total = (payload.proposed_changes || []).length;
      const selectedCount = state.selectedChangeIds.size;

      const rows = changes.map(change => `
        <tr>
          <td style="width:28px;text-align:center"><input type="checkbox" class="change-checkbox" data-item-id="${escapeHtml(change.item_id)}" ${state.selectedChangeIds.has(change.item_id) ? 'checked' : ''}></td>
          <td><span class="chip ${change.confidence}">${escapeHtml(change.confidence)}</span></td>
          <td>${escapeHtml(change.change_type)}</td>
          <td><div class="mono" style="font-size:0.8em">${escapeHtml(change.path || '')}</div></td>
          <td><div class="mono">${escapeHtml(change.current_value)}</div></td>
          <td><div class="mono">${escapeHtml(change.proposed_value)}</div></td>
        </tr>
      `).join('');

      const warningCounts = CounterFromArray((payload.warnings || []).map(w => w.code));
      const warningList = Object.entries(warningCounts).map(([code, count]) => `<span class="chip review">${escapeHtml(code)}${count > 1 ? ` ×${count}` : ''}</span>`).join('');
      const applyBanner = applyResult ? buildApplyResultBanner(applyResult) : '';

      mainContent.innerHTML = `
        ${applyBanner}
        <div class="subtle" style="margin-bottom:10px;">Warnings: ${warningList || 'none'}</div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
          <button class="secondary" id="selAllSafe">All Safe</button>
          <button class="secondary" id="selToggle">${selectedCount === total && total > 0 ? 'Deselect All' : 'Select All'}</button>
          <span class="subtle" id="selCount" style="margin-left:4px">${selectedCount} of ${total} selected</span>
          <div style="flex:1"></div>
          <button class="primary" id="applyBtn" ${selectedCount === 0 ? 'disabled' : ''} style="min-width:160px">Apply ${selectedCount} Changes</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th><th>Confidence</th><th>Type</th><th>Path</th><th>Current</th><th>Proposed</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="6" class="subtle">No changes for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;

      document.getElementById('selAllSafe').addEventListener('click', () => {
        state.selectedChangeIds = new Set((payload.proposed_changes || []).filter(c => c.confidence === 'safe').map(c => c.item_id));
        renderMusicNormalize(payload);
      });
      document.getElementById('selToggle').addEventListener('click', () => {
        const allChangeIds = (payload.proposed_changes || []).map(c => c.item_id);
        state.selectedChangeIds = state.selectedChangeIds.size === allChangeIds.length && allChangeIds.length > 0
          ? new Set()
          : new Set(allChangeIds);
        renderMusicNormalize(payload);
      });
      document.getElementById('applyBtn').addEventListener('click', applySelectedChanges);

      mainContent.querySelectorAll('.change-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) state.selectedChangeIds.add(cb.dataset.itemId);
          else state.selectedChangeIds.delete(cb.dataset.itemId);
          const count = state.selectedChangeIds.size;
          const countEl = document.getElementById('selCount');
          if (countEl) countEl.textContent = `${count} of ${total} selected`;
          const toggle = document.getElementById('selToggle');
          if (toggle) toggle.textContent = count === total && total > 0 ? 'Deselect All' : 'Select All';
          const btn = document.getElementById('applyBtn');
          if (btn) { btn.disabled = count === 0; btn.textContent = `Apply ${count} Changes`; }
          showNormalizeTreeDetail(payload);
        });
      });

      showNormalizeTreeDetail(payload);
    }

    async function applySelectedChanges() {
      const payload = state.results.music.normalize;
      const source = sourceInput.value.trim();
      if (!payload || !source) return;
      const changes = (payload.proposed_changes || []).filter(c => state.selectedChangeIds.has(c.item_id));
      if (changes.length === 0) return;
      const btn = document.getElementById('applyBtn');
      if (btn) btn.disabled = true;
      setStatus(`Applying ${changes.length} changes…`, 'running');
      try {
        const response = await fetch('/api/music/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, changes })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Apply failed.');
        state.results.music.apply = result;
        state.results.music.normalize = null;
        state.selectedChangeIds = new Set();
        setStatus(`Applied: ${result.applied.length}, skipped: ${result.skipped.length}, failed: ${result.failed.length}.`, 'idle');
        renderMusicNormalize(null);
      } catch (error) {
        setStatus(error.message, 'error');
        if (btn) btn.disabled = false;
      }
    }

    function buildApplyResultBanner(result) {
      const applied = result.applied || [];
      const skipped = result.skipped || [];
      const failed = result.failed || [];
      const remainingSafe = result.remaining_safe_count || 0;
      const remainingReview = result.remaining_review_count || 0;
      const complete = failed.length === 0 && remainingSafe === 0;
      const failedDetail = failed.length > 0 ? `
        <details style="margin-top:8px">
          <summary style="cursor:pointer;color:var(--danger)">${failed.length} failed — expand</summary>
          <div style="margin-top:6px">${failed.map(f => `<div class="mono" style="font-size:0.82em;color:var(--danger);margin-bottom:2px">${escapeHtml(f.path || f.item_id)}: ${escapeHtml(f.message)}</div>`).join('')}</div>
        </details>` : '';
      const remainingDetail = remainingSafe || remainingReview
        ? `<div style="margin-top:8px;color:${remainingSafe ? 'var(--danger)' : 'var(--muted)'}">${remainingSafe} safe rename${remainingSafe === 1 ? '' : 's'} and ${remainingReview} review rename${remainingReview === 1 ? '' : 's'} still pending.</div>`
        : '';
      return `
        <div style="background:var(--accent-glow);border:1px solid color-mix(in srgb, var(--accent) 30%, transparent);border-radius:12px;padding:14px 18px;margin-bottom:16px">
          <div style="font-weight:600;margin-bottom:6px">${complete ? 'Apply complete' : 'Apply needs review'}</div>
          <div style="display:flex;gap:20px;flex-wrap:wrap">
            <span style="color:var(--accent)">&#10003; ${applied.length} applied</span>
            <span style="color:var(--muted)">${skipped.length} skipped</span>
            ${failed.length > 0 ? `<span style="color:var(--danger)">&#10007; ${failed.length} failed</span>` : ''}
          </div>
          ${remainingDetail}
          ${failedDetail}
        </div>`;
    }

    function buildProposedFileTree(payload) {
      const source = payload.source_root || '';
      const sep = source.endsWith('/') ? source : source + '/';
      const changes = selectedProposedChanges(payload);
      const folderRenames = {};
      const fileRenames = {};
      for (const c of changes) {
        if (c.change_type === 'folder_rename') folderRenames[c.current_value] = c.proposed_value;
        if (c.change_type === 'file_rename') fileRenames[c.path] = c.proposed_value;
      }
      const tree = {};
      for (const track of (payload.tracks || [])) {
        const absPath = track.path;
        const relPath = absPath.startsWith(sep) ? absPath.slice(sep.length) : absPath;
        if (!isPathAffectedBySelectedChanges(absPath, relPath, changes)) continue;
        const slashIdx = relPath.lastIndexOf('/');
        const relDir = slashIdx >= 0 ? relPath.slice(0, slashIdx) : '';
        const filename = slashIdx >= 0 ? relPath.slice(slashIdx + 1) : relPath;
        let proposedDir = relDir;
        const orderedFolderRenames = Object.entries(folderRenames).sort((a, b) => b[0].length - a[0].length);
        for (const [cur, prop] of orderedFolderRenames) {
          if (proposedDir === cur) { proposedDir = prop; continue; }
          if (proposedDir.startsWith(cur + '/')) { proposedDir = prop + proposedDir.slice(cur.length); }
        }
        const proposedFilename = fileRenames[absPath] || filename;
        const parts = proposedDir ? proposedDir.split('/') : [];
        let node = tree;
        for (const part of parts) {
          if (!node[part]) node[part] = {};
          node = node[part];
        }
        if (!node._files) node._files = [];
        node._files.push(proposedFilename);
      }
      return tree;
    }

    function flattenTree(node, lines, depth) {
      const keys = Object.keys(node).filter(k => k !== '_files').sort((a, b) => a.localeCompare(b));
      for (const key of keys) {
        lines.push({ label: key + '/', depth, type: 'dir' });
        flattenTree(node[key], lines, depth + 1);
      }
      for (const file of (node._files || []).sort((a, b) => a.localeCompare(b))) {
        lines.push({ label: file, depth, type: 'file' });
      }
    }

    function showNormalizeTreeDetail(payload) {
      if (!payload) {
        detailPanel.innerHTML = '<div class="empty">Run Music / Normalize to preview the proposed structure.</div>';
        return;
      }
      const selectedChanges = selectedProposedChanges(payload);
      const tree = buildProposedFileTree(payload);
      const lines = [];
      flattenTree(tree, lines, 0);
      const html = lines.map(line => {
        const pad = line.depth * 14;
        const isDir = line.type === 'dir';
        return `<div style="padding-left:${pad}px;color:${isDir ? 'var(--accent)' : 'var(--ink)'};font-weight:${isDir ? 600 : 400};white-space:nowrap">${escapeHtml(line.label)}</div>`;
      }).join('');
      const folderMoves = selectedChanges.filter(c => c.change_type === 'folder_rename').length;
      const fileRenames = selectedChanges.filter(c => c.change_type === 'file_rename').length;
      detailPanel.innerHTML = `
        <div style="margin-bottom:10px">
          <div style="font-weight:600;margin-bottom:3px">Proposed Structure</div>
          <div class="subtle" style="font-size:0.83em">${folderMoves} folder move${folderMoves !== 1 ? 's' : ''} &middot; ${fileRenames} file rename${fileRenames !== 1 ? 's' : ''}</div>
        </div>
        <div class="mono" style="font-size:0.8em;line-height:1.75;overflow:auto;max-height:62vh">
          ${selectedChanges.length ? html : '<span class="subtle">Select changes to preview the proposed structure.</span>'}
        </div>`;
    }

    function buildProposedMovieFileTree(payload) {
      const source = payload.source_root || '';
      const sep = source.endsWith('/') ? source : source + '/';
      const changes = selectedProposedChanges(payload);
      const folderRenames = {};
      const fileRenames = {};
      const fileMoves = {};
      for (const c of changes) {
        if (c.change_type === 'folder_rename') folderRenames[c.current_value] = c.proposed_value;
        if (c.change_type === 'file_rename') fileRenames[c.path] = c.proposed_value;
        if (c.change_type === 'file_move') fileMoves[c.path] = c.proposed_value;
      }
      const tree = {};
      for (const absPath of (payload.movie_files || [])) {
        const relPath = absPath.startsWith(sep) ? absPath.slice(sep.length) : absPath;
        if (!isPathAffectedBySelectedChanges(absPath, relPath, changes)) continue;
        const moveRelPath = fileMoves[absPath];
        if (moveRelPath) {
          const slashIdx = moveRelPath.lastIndexOf('/');
          const proposedDir = slashIdx >= 0 ? moveRelPath.slice(0, slashIdx) : '';
          const proposedFilename = slashIdx >= 0 ? moveRelPath.slice(slashIdx + 1) : moveRelPath;
          const parts = proposedDir ? proposedDir.split('/') : [];
          let node = tree;
          for (const part of parts) {
            if (!node[part]) node[part] = {};
            node = node[part];
          }
          if (!node._files) node._files = [];
          node._files.push(proposedFilename);
          continue;
        }
        const slashIdx = relPath.lastIndexOf('/');
        const relDir = slashIdx >= 0 ? relPath.slice(0, slashIdx) : '';
        const filename = slashIdx >= 0 ? relPath.slice(slashIdx + 1) : relPath;
        let proposedDir = relDir;
        const orderedFolderRenames = Object.entries(folderRenames).sort((a, b) => b[0].length - a[0].length);
        for (const [cur, prop] of orderedFolderRenames) {
          if (proposedDir === cur) { proposedDir = prop; continue; }
          if (proposedDir.startsWith(cur + '/')) { proposedDir = prop + proposedDir.slice(cur.length); }
        }
        const proposedFilename = fileRenames[absPath] || filename;
        const parts = proposedDir ? proposedDir.split('/') : [];
        let node = tree;
        for (const part of parts) {
          if (!node[part]) node[part] = {};
          node = node[part];
        }
        if (!node._files) node._files = [];
        node._files.push(proposedFilename);
      }
      return tree;
    }

    function showMovieNormalizeTreeDetail(payload) {
      if (!payload) {
        detailPanel.innerHTML = '<div class="empty">Run Movies / Normalize to preview the proposed structure.</div>';
        return;
      }
      const selectedChanges = selectedProposedChanges(payload);
      const tree = buildProposedMovieFileTree(payload);
      const lines = [];
      flattenTree(tree, lines, 0);
      const html = lines.map(line => {
        const pad = line.depth * 14;
        const isDir = line.type === 'dir';
        return `<div style="padding-left:${pad}px;color:${isDir ? 'var(--accent)' : 'var(--ink)'};font-weight:${isDir ? 600 : 400};white-space:nowrap">${escapeHtml(line.label)}</div>`;
      }).join('');
      const folderMoves = selectedChanges.filter(c => c.change_type === 'folder_rename').length;
      const fileRenames = selectedChanges.filter(c => c.change_type === 'file_rename' || c.change_type === 'file_move').length;
      detailPanel.innerHTML = `
        <div style="margin-bottom:10px">
          <div style="font-weight:600;margin-bottom:3px">Proposed Structure</div>
          <div class="subtle" style="font-size:0.83em">${folderMoves} folder move${folderMoves !== 1 ? 's' : ''} &middot; ${fileRenames} file rename${fileRenames !== 1 ? 's' : ''}</div>
        </div>
        <div class="mono" style="font-size:0.8em;line-height:1.75;overflow:auto;max-height:62vh">
          ${selectedChanges.length ? html : '<span class="subtle">Select changes to preview the proposed structure.</span>'}
        </div>`;
    }

    function activeMovieNormalizePayload(payload) {
      if (!payload) return payload;
      const style = state.movieNamingStyle || payload.default_naming_style || payload.naming_style || 'concise';
      const changesByStyle = payload.proposed_changes_by_naming_style || {};
      const warningsByStyle = payload.warnings_by_naming_style || {};
      return {
        ...payload,
        naming_style: style,
        proposed_changes: changesByStyle[style] || payload.proposed_changes || [],
        warnings: warningsByStyle[style] || payload.warnings || []
      };
    }

    function selectedProposedChanges(payload) {
      return (payload.proposed_changes || []).filter(c => state.selectedChangeIds.has(c.item_id));
    }

    function isPathAffectedBySelectedChanges(absPath, relPath, changes) {
      return changes.some(change => {
        if (change.change_type === 'file_rename' || change.change_type === 'file_move') {
          return change.path === absPath;
        }
        if (change.change_type === 'folder_rename') {
          const current = change.current_value || '';
          return relPath === current || relPath.startsWith(current + '/');
        }
        return false;
      });
    }

    function buildBitrateChart(dist, title) {
      if (!dist || !dist.bins || dist.bins.length === 0) {
        return '<div style="font-size:11px;color:var(--muted);padding:6px 0">' + title + ': no data</div>';
      }
      const bins = dist.bins;
      const p10 = dist.p10, mean = dist.mean, p90 = dist.p90, p95 = dist.p95;

      const maxBinKbps = Math.max.apply(null, bins.map(b => b.end_kbps));
      const clipKbps = p95 ? Math.max(p95, mean || 0) : maxBinKbps;
      const visibleBins = bins.filter(b => b.start_kbps <= clipKbps);
      const overflowCount = bins.filter(b => b.start_kbps > clipKbps).reduce((s, b) => s + b.count, 0);

      const W = 280, H = 78, ml = 12, mr = 12, mt = 18, mb = 9;
      const pw = W - ml - mr, ph = H - mt - mb;
      const baseY = mt + ph;
      const maxKbps = clipKbps;
      const maxCount = Math.max.apply(null, visibleBins.map(b => b.count));

      const sx = k => ml + (k / maxKbps) * pw;
      const sy = c => mt + ph * (1 - c / maxCount);
      const binPts = visibleBins.map(b => [sx((b.start_kbps + Math.min(b.end_kbps, maxKbps)) / 2), sy(b.count)]);
      const edgePts = [
        [sx(visibleBins[0].start_kbps), baseY],
        ...binPts,
        [sx(Math.min(visibleBins[visibleBins.length - 1].end_kbps, maxKbps)), baseY]
      ];

      function smoothLine(ps) {
        if (!ps.length) return '';
        let d = 'M' + ps[0][0].toFixed(1) + ',' + ps[0][1].toFixed(1);
        for (let i = 1; i < ps.length; i++) {
          const cx = ((ps[i-1][0] + ps[i][0]) / 2).toFixed(1);
          d += ' C' + cx + ',' + ps[i-1][1].toFixed(1) + ' ' + cx + ',' + ps[i][1].toFixed(1) + ' ' + ps[i][0].toFixed(1) + ',' + ps[i][1].toFixed(1);
        }
        return d;
      }

      const curveD = smoothLine(edgePts);
      const areaD = curveD + ' Z';

      function vline(kbps, label, clr) {
        if (!kbps || kbps > maxKbps) return '';
        const x = sx(kbps).toFixed(1);
        return '<line x1="' + x + '" y1="' + mt + '" x2="' + x + '" y2="' + baseY + '" stroke="' + clr + '" stroke-width="1" stroke-dasharray="3,2" opacity="0.8"/>' +
          '<text x="' + x + '" y="' + (mt - 9).toFixed(1) + '" text-anchor="middle" font-size="3.5" fill="' + clr + '">' + label + '</text>' +
          '<text x="' + x + '" y="' + (mt - 3).toFixed(1) + '" text-anchor="middle" font-size="3.5" fill="' + clr + '">' + fmtM(kbps) + '</text>';
      }

      function fmtM(kbps) { return (kbps / 1000).toFixed(1) + ' Mbps'; }

      const ticks = [0, 0.5, 1].map(f => {
        const k = f * maxKbps;
        return '<text x="' + sx(k).toFixed(1) + '" y="' + (baseY + 5).toFixed(1) + '" text-anchor="middle" font-size="3.5" fill="#6c675f">' + fmtM(k) + '</text>';
      }).join('');

      const overflowText = overflowCount
        ? '<text x="' + (ml + pw) + '" y="' + (mt - 3).toFixed(1) + '" text-anchor="end" font-size="3.5" fill="#6c675f">+' + overflowCount + ' beyond ' + fmtM(clipKbps) + '</text>'
        : '';

      return '<div style="font-size:20px;font-weight:800;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted);margin-bottom:6px">' + title + '</div>' +
        '<svg viewBox="0 0 ' + W + ' ' + H + '" width="100%" style="display:block;overflow:visible;font-family:Georgia,serif">' +
          '<path d="' + areaD + '" fill="var(--accent)" opacity="0.13"/>' +
          '<path d="' + curveD + '" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>' +
          '<line x1="' + ml + '" y1="' + baseY + '" x2="' + (ml + pw) + '" y2="' + baseY + '" stroke="var(--line)" stroke-width="1"/>' +
          vline(p10, 'p10', 'var(--warn)') +
          vline(mean, 'mean', 'var(--accent-2)') +
          vline(p90, 'p90', 'var(--danger)') +
          ticks +
          overflowText +
        '</svg>';
    }

    function buildBitrateBellCurve(payload) {
      const histogram = payload && payload.histogram;
      if (!histogram) return '<div class="empty">Run Movies / Dashboard to see bitrate distributions.</div>';
      const snapshotNote = payload.dashboard_snapshot_only ? '<div class="subtle" style="margin-bottom:10px">Cached dashboard snapshot. Run Movies / Dashboard to rebuild after library changes.</div>' : '';
      return '<div class="finding" style="padding:14px 16px 14px">' +
        snapshotNote +
        buildBitrateChart(histogram.video_bitrate_kbps, 'Video Bitrate') +
        '<div style="margin-top:14px">' +
        buildBitrateChart(histogram.audio_bitrate_kbps, 'Audio Bitrate') +
        '</div></div>';
    }

    function renderMovieLibrary(payload) {
      mainTagline.textContent = 'Collection overview: quality tier distribution, resolution breakdown, and at-a-glance diagnostics.';
      renderMetrics(buildMovieMetrics(payload));
      renderBars(buildMovieBars(payload));
      filterBar.innerHTML = '';
      mainContent.innerHTML = buildMovieDashboard(payload);
      attachMovieDashboardHandlers(payload);
      if (!payload) {
        detailPanel.innerHTML = '<div class="empty">Run Movies / Dashboard to see bitrate distribution.</div>';
        return;
      }
      detailPanel.innerHTML = buildBitrateBellCurve(payload);
    }

    function attachMovieDashboardHandlers(payload) {
      const exportBtn = document.getElementById('exportCatalogueButton');
      if (exportBtn) exportBtn.addEventListener('click', () => generateCatalogue(exportBtn));
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
      mainContent.innerHTML = buildMovieCanonicalListsDashboard(payload);
      if (!payload) {
        detailPanel.innerHTML = '<div class="empty">Run Movies / Canonical Lists to see badge progress.</div>';
        return;
      }
      detailPanel.innerHTML = buildMovieCanonicalBadgePanel(payload);
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

    function renderMovieAudioPackaging(payload) {
      mainTagline.textContent = 'Multi-audio packaging mistakes where the default track is the wrong language or the English fallback is materially weaker.';
      renderMetrics(buildMovieMetrics(payload));
      renderBars(buildMovieBars(payload));
      renderFilters([
        ['all', 'All'],
        ['weak_english', 'Weak English Fallback'],
        ['wrong_default', 'Wrong Default Language']
      ]);
      if (!payload) {
        mainContent.innerHTML = '<div class="empty">Run Movies / Fix Multi-Audio Packaging to review language-default mistakes.</div>';
        return;
      }
      const items = sortedMovies(filteredAudioPackagingMovies(payload));
      mainContent.innerHTML = buildMovieAudioPackagingTable(payload, items);
      renderReplacementQueueDetail(payload);
      attachMovieReplacementHandlers(payload, items);
    }

    function renderMovieSubtitleReadiness(payload) {
      mainTagline.textContent = 'Repair subtitle defaults without deleting files: no subtitle by default when appropriate, forced English when needed, and English subtitles for non-English default audio.';
      renderMetrics(buildMovieMetrics(payload));
      renderBars(buildMovieBars(payload));
      renderFilters([
        ['all', 'All'],
        ['forced_english', 'Forced English'],
        ['non_english_audio', 'Non-English Audio'],
        ['clear_default', 'Clear Default']
      ]);
      if (!payload) {
        mainContent.innerHTML = '<div class="empty">Run Movies / Repair Subtitle Readiness to review subtitle-default mistakes.</div>';
        detailPanel.innerHTML = '<div class="empty">No review-only items.</div>';
        return;
      }
      const items = sortedSubtitleItems(filteredSubtitleReadinessMovies(payload));
      mainContent.innerHTML = buildMovieSubtitleReadinessTable(payload, items);
      renderSubtitleReadinessDetail(payload);
      attachMovieSubtitleReadinessHandlers(payload, items);
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

      renderFilters([
        ['all', 'All'],
        ['safe', 'Safe'],
        ['review', 'Flagged for review'],
        ['warnings', 'Warnings']
      ]);

      const changes = filteredMovieChanges(activePayload);
      const total = (activePayload.proposed_changes || []).length;
      const selectedCount = selectedProposedChanges(activePayload).length;
      const visibleChangeIds = changes.map(c => c.item_id);
      const visibleSelectedCount = changes.filter(c => state.selectedChangeIds.has(c.item_id)).length;
      const allVisibleSelected = visibleChangeIds.length > 0 && visibleSelectedCount === visibleChangeIds.length;
      const rows = changes.map(change => `
        <tr>
          <td style="width:28px;text-align:center"><input type="checkbox" class="change-checkbox" data-item-id="${escapeHtml(change.item_id)}" ${state.selectedChangeIds.has(change.item_id) ? 'checked' : ''}></td>
          <td><span class="chip ${change.confidence}">${escapeHtml(change.confidence)}</span></td>
          <td>${escapeHtml(change.change_type)}</td>
          <td><div class="mono">${escapeHtml(change.path || '')}</div></td>
          <td>${escapeHtml(change.current_value)}</td>
          <td>${escapeHtml(change.proposed_value)}</td>
        </tr>
      `).join('');
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
          <button class="secondary" id="selAllSafe">All Safe</button>
          <button class="secondary" id="selFlaggedReview">Flagged for review</button>
          <button class="secondary" id="selToggle">${allVisibleSelected ? 'Deselect All' : 'Select All'}</button>
          <span class="subtle" id="selCount" style="margin-left:4px">${selectedCount} of ${total} selected</span>
          <div style="flex:1"></div>
          <button class="primary" id="applyBtn" ${selectedCount === 0 ? 'disabled' : ''} style="min-width:160px">Apply ${selectedCount} Changes</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th><th>Confidence</th><th>Type</th><th>Path</th><th>Current</th><th>Proposed</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="6" class="subtle">No rename proposals for this filter.</td></tr>'}</tbody>
          </table>
        </div>
      `;

      document.getElementById('selAllSafe').addEventListener('click', () => {
        state.selectedChangeIds = new Set((activePayload.proposed_changes || []).filter(c => c.confidence === 'safe').map(c => c.item_id));
        renderMovieNormalize(payload);
      });
      document.getElementById('selFlaggedReview').addEventListener('click', () => {
        state.selectedChangeIds = new Set((activePayload.proposed_changes || []).filter(c => c.confidence === 'review').map(c => c.item_id));
        renderMovieNormalize(payload);
      });
      document.getElementById('selToggle').addEventListener('click', () => {
        state.selectedChangeIds = allVisibleSelected
          ? new Set()
          : new Set(visibleChangeIds);
        renderMovieNormalize(payload);
      });
      document.getElementById('applyBtn').addEventListener('click', applySelectedMovieChanges);
      document.getElementById('movieNamingStyleSelect').addEventListener('change', event => {
        state.movieNamingStyle = event.target.value;
        renderMovieNormalize(payload);
      });

      mainContent.querySelectorAll('.change-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) state.selectedChangeIds.add(cb.dataset.itemId);
          else state.selectedChangeIds.delete(cb.dataset.itemId);
          const nextPayload = activeMovieNormalizePayload(payload);
          const count = selectedProposedChanges(nextPayload).length;
          const nextVisibleChanges = filteredMovieChanges(nextPayload);
          const nextVisibleSelectedCount = nextVisibleChanges.filter(c => state.selectedChangeIds.has(c.item_id)).length;
          const nextAllVisibleSelected = nextVisibleChanges.length > 0 && nextVisibleSelectedCount === nextVisibleChanges.length;
          const countEl = document.getElementById('selCount');
          if (countEl) countEl.textContent = `${count} of ${total} selected`;
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
        const remaining = result.remaining_safe_count || 0;
        const suffix = remaining ? ` ${remaining} safe rename${remaining === 1 ? '' : 's'} still pending.` : '';
        setStatus(`Applied: ${result.applied.length}, skipped: ${result.skipped.length}, failed: ${result.failed.length}.${suffix}`, remaining ? 'error' : 'idle');
        renderMovieNormalize(state.results.movies.normalize);
      } catch (error) {
        setStatus(error.message, 'error');
        if (btn) btn.disabled = false;
      }
    }

    function renderMusicArtwork(payload) {
      mainTagline.textContent = 'Browse album artists as local sidecar artwork. Missing artist images are shown in place.';

      if (!payload) {
        renderMetrics([]);
        renderBars([]);
        filterBar.innerHTML = '';
        mainContent.innerHTML = '<div class="empty">Run Music / Artwork to browse album artist folders and sidecar artwork.</div>';
        detailPanel.innerHTML = '<div class="empty">Run a scan first.</div>';
        return;
      }

      const present = payload.present || [];
      const missing = payload.missing || [];
      const total = present.length + missing.length;

      const LOW_SIZE = 30 * 1024;
      const LOW_DIM = 300;
      const lowQuality = present.filter(p => p.file_size_bytes > 0 && (p.file_size_bytes < LOW_SIZE || p.width < LOW_DIM || p.height < LOW_DIM));
      const presentByArtist = new Map(present.map(item => [item.artist_name, item]));
      const writable = present.filter(item => item.source === 'jellyfin');
      const approved = Object.values(state.approvedArtworkCandidates);
      const artists = [
        ...present.map(item => ({ artist_name: item.artist_name, folder_path: item.folder_path, status: 'present', artwork: item })),
        ...missing.map(item => ({ artist_name: item.artist_name, folder_path: item.folder_path, status: 'missing', artwork: null }))
      ].sort((a, b) => a.artist_name.localeCompare(b.artist_name));

      renderMetrics([
        { value: String(total), label: 'album artists' },
        { value: String(present.length), label: 'with image' },
        { value: String(missing.length), label: 'missing image' },
        { value: String(lowQuality.length), label: 'low quality' },
      ]);
      renderBars([
        { label: 'with image', value: String(present.length), width: total ? (present.length / total) * 100 : 0 },
        { label: 'missing image', value: String(missing.length), width: total ? (missing.length / total) * 100 : 0 },
      ]);
      renderFilters([
        ['all', 'All'],
        ['missing', 'Missing'],
        ['present', 'With Image'],
        ['low', 'Low Quality']
      ]);

      function qualityBadge(item) {
        if (!item.width) return '';
        const isLow = item.file_size_bytes < LOW_SIZE || item.width < LOW_DIM || item.height < LOW_DIM;
        const label = item.width + '\xd7' + item.height;
        const color = isLow ? 'var(--danger)' : 'var(--accent)';
        return `<span style="font-size:10px;font-weight:600;color:${color};letter-spacing:0.03em">${label}</span>`;
      }

      const visibleArtists = artists.filter(artist => {
        if (state.filter === 'missing') return artist.status === 'missing';
        if (state.filter === 'present') return artist.status === 'present';
        if (state.filter === 'low') {
          const item = artist.artwork;
          return item && item.file_size_bytes > 0 && (item.file_size_bytes < LOW_SIZE || item.width < LOW_DIM || item.height < LOW_DIM);
        }
        return true;
      });

      const artistTiles = visibleArtists.map(artist => {
        const item = artist.artwork;
        const isLow = item && item.file_size_bytes > 0 && (item.file_size_bytes < LOW_SIZE || item.width < LOW_DIM || item.height < LOW_DIM);
        const imgPath = item ? (item.image_path || (item.folder_path + '/' + item.filename)) : '';
        const imgSrc = item ? artworkImageUrl(imgPath, item) : '';
        const sourceLabel = item ? artworkSourceLabel(item.source) || 'local' : '';
        const sourceChip = item && isLowConfidenceArtworkSource(item.source) ? 'review' : 'safe';
        return `
          <button class="artist-tile" data-artist="${escapeHtml(artist.artist_name)}">
            ${item ? `
              <div class="artist-art" style="${isLow ? 'outline:3px solid rgba(138,51,65,0.65);outline-offset:-3px' : ''}">
                <img src="${imgSrc}" alt="${escapeHtml(artist.artist_name)}" loading="lazy">
              </div>
            ` : '<div class="artist-art missing">Missing artist image</div>'}
            <div class="artist-meta">
              <div class="artist-name">${escapeHtml(artist.artist_name)}</div>
              <div>${item ? `<span class="chip ${sourceChip}" style="font-size:0.72em">${escapeHtml(sourceLabel)}</span>` : state.approvedArtworkCandidates[artist.artist_name] ? '<span class="chip review" style="font-size:0.72em">approved</span>' : '<span class="chip high" style="font-size:0.72em">missing</span>'}${item ? qualityBadge(item) : ''}</div>
              <div class="artist-path">${escapeHtml(artist.folder_path)}</div>
            </div>
          </button>
        `;
      }).join('');

      mainContent.innerHTML = `
        <div class="artist-toolbar">
          <span class="subtle" id="artworkSelCount">${state.selectedArtistNames.size + approved.length} selected</span>
          <button class="primary" id="artworkApplyBtn" ${state.selectedArtistNames.size + approved.length === 0 ? 'disabled' : ''}>Write Selected to Library</button>
        </div>
        ${writable.length > 0 ? `
          <div class="artist-toolbar" style="margin-top:-4px">
            <button class="secondary" id="artworkSelectWritable">Select Jellyfin</button>
            <button class="secondary" id="artworkSelectNone">Select None</button>
            <button class="secondary" id="artworkBackfillJellyfin">Backfill Jellyfin</button>
            <span class="subtle">Writes cached Jellyfin images to album artist <span class="mono">artist.jpg</span> files.</span>
          </div>
        ` : `
          <div class="artist-toolbar" style="margin-top:-4px">
            <button class="secondary" id="artworkBackfillJellyfin">Backfill Jellyfin</button>
          </div>
        `}
        <div class="artist-grid">
          ${artistTiles || '<div class="empty">No album artists match this filter.</div>'}
        </div>
      `;

      function updateArtworkSelection() {
        const countEl = document.getElementById('artworkSelCount');
        const approvedCount = Object.keys(state.approvedArtworkCandidates).length;
        if (countEl) countEl.textContent = `${state.selectedArtistNames.size + approvedCount} selected`;
        const btn = document.getElementById('artworkApplyBtn');
        if (btn) btn.disabled = state.selectedArtistNames.size + approvedCount === 0;
      }
      document.getElementById('artworkSelectWritable')?.addEventListener('click', () => {
        state.selectedArtistNames = new Set(writable.map(item => item.artist_name));
        updateArtworkSelection();
      });
      document.getElementById('artworkSelectNone')?.addEventListener('click', () => {
        state.selectedArtistNames = new Set();
        updateArtworkSelection();
      });
      document.getElementById('artworkBackfillJellyfin')?.addEventListener('click', backfillJellyfinArtwork);
      mainContent.querySelectorAll('.artist-tile').forEach(button => {
        button.addEventListener('click', () => showArtworkArtistDetail(button.dataset.artist, artists, presentByArtist));
        attachArtworkDropTarget(button, button.dataset.artist);
      });
      document.getElementById('artworkApplyBtn')?.addEventListener('click', applyArtwork);
    }

    function showArtworkArtistDetail(artistName, artists, presentByArtist) {
      const artist = artists.find(item => item.artist_name === artistName);
      if (!artist) return;
      const item = presentByArtist.get(artistName);
      const imgPath = item ? (item.image_path || (item.folder_path + '/' + item.filename)) : '';
      const imgSrc = item ? artworkImageUrl(imgPath, item) : '';
      const sourceLabel = item?.source === 'jellyfin' ? 'jellyfin metadata' : isLowConfidenceArtworkSource(item?.source) ? artworkSourceLabel(item.source) : 'local sidecar';
      const sourceChip = item && isLowConfidenceArtworkSource(item.source) ? 'review' : 'safe';
      const approved = state.approvedArtworkCandidates[artistName];
      const previewSrc = approved ? candidatePreviewUrl(approved) : imgSrc;
      const candidates = state.artworkCandidates[artistName] || [];
      const imageSearchOffset = state.artworkImageSearchOffsets[artistName] || 0;
      detailPanel.innerHTML = `
        <div class="finding">
          <h3>${escapeHtml(artistName)}</h3>
          <p class="mono">${escapeHtml(artist.folder_path)}</p>
          ${item ? `
            <div style="width:100%;max-width:340px;aspect-ratio:1/1;border-radius:8px;overflow:hidden;border:1px solid var(--line);background:#eee6d8;margin:12px 0">
              <img src="${escapeHtml(previewSrc)}" alt="${escapeHtml(artistName)}" style="width:100%;height:100%;object-fit:cover">
            </div>
            <div class="artwork-drop-zone" id="artworkDropZone">Drop image or image URL here</div>
            ${approved ? `
              <p><span class="chip review">approved candidate</span> ${escapeHtml(artworkSourceLabel(approved.source))}</p>
              <p class="subtle">${escapeHtml(approved.title || '')}</p>
              <p class="subtle">Current: ${escapeHtml(sourceLabel)} · ${escapeHtml(item.filename)}${item.width && item.height ? ` · ${item.width}\xd7${item.height}` : ''}</p>
              <button class="primary" id="saveArtworkCandidate">Approve & Save</button>
              <button class="secondary" id="clearArtworkCandidate">Clear Approval</button>
            ` : `
              <p><span class="chip ${sourceChip}">${escapeHtml(sourceLabel)}</span> ${escapeHtml(item.filename)}</p>
              ${item.source === 'jellyfin' ? `<p class="mono subtle">${escapeHtml(imgPath)}</p>` : ''}
              <p class="subtle">${item.width && item.height ? `${item.width}\xd7${item.height}` : 'dimensions unknown'} &middot; ${Math.round((item.file_size_bytes || 0) / 1024)} KB</p>
            `}
            <div class="artist-toolbar" style="margin-top:12px">
              <button class="primary" id="findArtworkCandidates">Find Candidates</button>
            </div>
          ` : `
            ${approved ? `
              <div style="width:100%;max-width:340px;aspect-ratio:1/1;border-radius:8px;overflow:hidden;border:1px solid var(--line);background:#eee6d8;margin:12px 0">
                <img src="${escapeHtml(candidatePreviewUrl(approved))}" alt="${escapeHtml(artistName)} candidate" style="width:100%;height:100%;object-fit:cover">
              </div>
              <div class="artwork-drop-zone" id="artworkDropZone">Drop image or image URL here</div>
              <p><span class="chip review">approved candidate</span> ${escapeHtml(approved.source)}</p>
              <p class="subtle">${escapeHtml(approved.title || '')}</p>
              <button class="primary" id="saveArtworkCandidate">Approve & Save</button>
              <button class="secondary" id="clearArtworkCandidate">Clear Approval</button>
            ` : `
              <div class="artist-art missing" style="width:100%;max-width:340px;aspect-ratio:1/1;border:1px dashed var(--line);border-radius:8px;margin:12px 0">Missing artist image</div>
              <div class="artwork-drop-zone" id="artworkDropZone">Drop image or image URL here</div>
              <p><span class="chip high">missing</span> Add <span class="mono">artist.jpg</span> to this album artist folder.</p>
            `}
            <div class="artist-toolbar" style="margin-top:12px">
              <button class="primary" id="findArtworkCandidates">Find Candidates</button>
            </div>
          `}
          ${renderArtworkCandidateSections(artistName, candidates, imageSearchOffset)}
        </div>
      `;
      document.getElementById('findArtworkCandidates')?.addEventListener('click', () => findArtworkCandidates(artistName, artists, presentByArtist));
      document.getElementById('clearArtworkCandidate')?.addEventListener('click', () => {
        delete state.approvedArtworkCandidates[artistName];
        renderCurrentPage();
        showArtworkArtistDetail(artistName, artists, presentByArtist);
      });
      document.getElementById('saveArtworkCandidate')?.addEventListener('click', () => applySingleArtworkCandidate(artistName));
      document.getElementById('previousImageSearchCandidates')?.addEventListener('click', () => previousImageSearchCandidates(artistName, artists, presentByArtist));
      document.getElementById('nextImageSearchCandidates')?.addEventListener('click', () => nextImageSearchCandidates(artistName, artists, presentByArtist));
      const dropZone = document.getElementById('artworkDropZone');
      if (dropZone) attachArtworkDropTarget(dropZone, artistName);
      detailPanel.querySelectorAll('.artwork-candidate').forEach(button => {
        button.addEventListener('click', () => {
          const candidate = (state.artworkCandidates[artistName] || []).find(item => item.image_url === button.dataset.candidate);
          if (!candidate) return;
          state.approvedArtworkCandidates[artistName] = candidate;
          renderCurrentPage();
          showArtworkArtistDetail(artistName, artists, presentByArtist);
        });
      });
    }

    function renderArtworkCandidateSections(artistName, candidates, imageSearchOffset) {
      const regularCandidates = candidates.filter(candidate => candidate.source !== 'image-search');
      const bingCandidates = candidates.filter(candidate => candidate.source === 'image-search');
      return [
        renderArtworkCandidateSection('Artwork candidates', artistName, regularCandidates),
        renderArtworkCandidateSection('Bing image search', artistName, bingCandidates, {
          actions: [
            imageSearchOffset ? { id: 'previousImageSearchCandidates', label: 'Back' } : null,
            { id: 'nextImageSearchCandidates', label: 'Next' },
          ].filter(Boolean),
          meta: imageSearchOffset ? `showing ${imageSearchOffset + 1}-${imageSearchOffset + bingCandidates.length}` : '',
        }),
      ].join('');
    }

    function renderArtworkCandidateSection(title, artistName, candidates, options = {}) {
      if (!candidates.length) return '';
      return `
        <section class="candidate-section">
          <div class="candidate-section-heading">
            <h4>${escapeHtml(title)}</h4>
            <div>
              ${options.meta ? `<span class="subtle" style="font-size:12px;margin-right:8px">${escapeHtml(options.meta)}</span>` : ''}
              ${(options.actions || []).map(action => `<button class="secondary" id="${escapeHtml(action.id)}" style="padding:6px 10px;font-size:12px;margin-left:6px">${escapeHtml(action.label)}</button>`).join('')}
            </div>
          </div>
          <div class="artist-grid" style="grid-template-columns:repeat(auto-fill,minmax(118px,1fr))">
            ${candidates.map(candidate => renderArtworkCandidateCard(artistName, candidate)).join('')}
          </div>
        </section>
      `;
    }

    function renderArtworkCandidateCard(artistName, candidate) {
      return `
        <button class="artist-tile artwork-candidate" data-artist="${escapeHtml(artistName)}" data-candidate="${escapeHtml(candidate.image_url)}">
          <div class="artist-art"><img src="${escapeHtml(candidatePreviewUrl(candidate))}" alt="${escapeHtml(candidate.title)}" loading="lazy"></div>
          <div class="artist-meta">
            <div class="artist-name">${escapeHtml(candidate.title || candidate.source)}</div>
            <div><span class="chip review" style="font-size:0.72em">${escapeHtml(artworkSourceLabel(candidate.source))}</span></div>
          </div>
        </button>
      `;
    }

    function attachArtworkDropTarget(element, artistName) {
      element.addEventListener('dragover', event => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
        element.classList.add('dragover');
      });
      element.addEventListener('dragleave', () => {
        element.classList.remove('dragover');
      });
      element.addEventListener('drop', event => {
        event.preventDefault();
        event.stopPropagation();
        element.classList.remove('dragover');
        approveDroppedArtwork(event.dataTransfer, artistName);
      });
    }

    function approveDroppedArtwork(dataTransfer, artistName) {
      const file = Array.from(dataTransfer.files || []).find(item => item.type && item.type.startsWith('image/'));
      if (file) {
        const reader = new FileReader();
        reader.onload = () => {
          approveArtworkCandidate(artistName, {
            artist_name: artistName,
            folder_path: artworkArtistFolderPath(artistName),
            source: 'drop',
            title: file.name || 'dropped image',
            preview_url: String(reader.result || ''),
            image_url: String(reader.result || ''),
            page_url: ''
          });
        };
        reader.onerror = () => setStatus('Could not read dropped image file.', 'error');
        reader.readAsDataURL(file);
        return;
      }

      const url = droppedArtworkUrl(dataTransfer);
      if (!url) {
        setStatus('Drop an image file or a direct image URL.', 'error');
        return;
      }
      approveArtworkCandidate(artistName, {
        artist_name: artistName,
        folder_path: artworkArtistFolderPath(artistName),
        source: 'drop',
        title: urlHostLabel(url),
        preview_url: url,
        image_url: url,
        page_url: url
      });
    }

    function approveArtworkCandidate(artistName, candidate) {
      state.approvedArtworkCandidates[artistName] = candidate;
      setStatus(`${artistName} replacement approved from drop.`, 'idle');
      renderCurrentPage();
      showArtworkArtistDetailFromPayload(artistName);
    }

    function artworkArtistFolderPath(artistName) {
      const payload = state.results.music.artwork;
      const item = (payload?.present || []).find(item => item.artist_name === artistName)
        || (payload?.missing || []).find(item => item.artist_name === artistName);
      return item?.folder_path || '';
    }

    function droppedArtworkUrl(dataTransfer) {
      const uriList = dataTransfer.getData('text/uri-list').split(/\\r?\\n/).find(line => line && !line.startsWith('#'));
      if (isDroppableArtworkUrl(uriList)) return uriList;
      const plain = dataTransfer.getData('text/plain').trim();
      if (isDroppableArtworkUrl(plain)) return plain;
      const htmlPayload = dataTransfer.getData('text/html');
      const match = htmlPayload.match(/<img[^>]+src=["']([^"']+)["']/i);
      if (match && isDroppableArtworkUrl(match[1])) return match[1];
      return '';
    }

    function isDroppableArtworkUrl(value) {
      try {
        return new URL(value || '').protocol === 'https:';
      } catch {
        return false;
      }
    }

    function urlHostLabel(url) {
      try {
        return new URL(url).hostname || 'dropped image URL';
      } catch {
        return 'dropped image URL';
      }
    }

    function candidatePreviewUrl(candidate) {
      if (!candidate) return '';
      if (candidate.preview_url && candidate.preview_url.startsWith('data:image/')) return candidate.preview_url;
      if (candidate.preview_url && candidate.preview_url.startsWith('https://')) return candidate.preview_url;
      const path = candidate.preview_url || candidate.image_url || '';
      return '/api/music/artwork/image?path=' + encodeURIComponent(path);
    }

    function artworkImageUrl(path, item) {
      const version = item?.mtime_ns || item?.image_cache_key || [item?.file_size_bytes || 0, item?.width || 0, item?.height || 0].join('-');
      return '/api/music/artwork/image?path=' + encodeURIComponent(path) + '&v=' + encodeURIComponent(version);
    }

    async function findArtworkCandidates(artistName, artists, presentByArtist) {
      const source = sourceInput.value.trim();
      if (!source) return;
      setStatus(`Finding artwork candidates for ${artistName}…`, 'running');
      try {
        const response = await fetch('/api/music/artwork/candidates', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, artist_name: artistName })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Candidate search failed.');
        state.artworkCandidates[artistName] = (payload.candidates || []).map(candidate => (
          candidate.source === 'image-search' ? { ...candidate, search_offset: 0 } : candidate
        ));
        state.artworkImageSearchOffsets[artistName] = 0;
        setStatus(`Found ${state.artworkCandidates[artistName].length} candidate${state.artworkCandidates[artistName].length !== 1 ? 's' : ''} for ${artistName}.`, 'idle');
        showArtworkArtistDetail(artistName, artists, presentByArtist);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    async function nextImageSearchCandidates(artistName, artists, presentByArtist) {
      const currentOffset = state.artworkImageSearchOffsets[artistName] || 0;
      await loadImageSearchCandidates(artistName, artists, presentByArtist, currentOffset + 8, 'next');
    }

    async function previousImageSearchCandidates(artistName, artists, presentByArtist) {
      const currentOffset = state.artworkImageSearchOffsets[artistName] || 0;
      await loadImageSearchCandidates(artistName, artists, presentByArtist, Math.max(currentOffset - 8, 0), 'previous');
    }

    async function loadImageSearchCandidates(artistName, artists, presentByArtist, offset, direction) {
      const source = sourceInput.value.trim();
      if (!source) return;
      setStatus(`Finding ${direction} Bing image results for ${artistName}…`, 'running');
      try {
        const response = await fetch('/api/music/artwork/image-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, artist_name: artistName, offset })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || 'Image search failed.');
        const existing = state.artworkCandidates[artistName] || [];
        const regularCandidates = existing.filter(candidate => candidate.source !== 'image-search');
        const imageCandidates = (payload.candidates || []).map(candidate => ({ ...candidate, search_offset: offset }));
        state.artworkCandidates[artistName] = regularCandidates.concat(imageCandidates);
        state.artworkImageSearchOffsets[artistName] = offset;
        setStatus(`Loaded ${imageCandidates.length} Bing image result${imageCandidates.length !== 1 ? 's' : ''} for ${artistName}.`, 'idle');
        showArtworkArtistDetail(artistName, artists, presentByArtist);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    async function applyArtwork() {
      const source = sourceInput.value.trim();
      const payload = state.results.music.artwork;
      if (!source || !payload) return;

      const items = (payload.present || [])
        .filter(item => item.source === 'jellyfin' && state.selectedArtistNames.has(item.artist_name))
        .map(item => item.artist_name);
      const candidates = Object.values(state.approvedArtworkCandidates);
      const candidateNames = new Set(candidates.map(candidate => candidate.artist_name));
      const filteredItems = items.filter(name => !candidateNames.has(name));

      if (filteredItems.length + candidates.length === 0) return;

      const btn = document.getElementById('artworkApplyBtn');
      if (btn) btn.disabled = true;
      setStatus(`Writing artwork for ${filteredItems.length + candidates.length} artist${filteredItems.length + candidates.length !== 1 ? 's' : ''}…`, 'running');

      try {
        const response = await fetch('/api/music/artwork/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source,
            items: filteredItems,
            candidates
          })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Apply failed.');

        const resultItems = result.results || [];
        const written = resultItems.filter(r => r.status === 'written').length;
        const failed = resultItems.filter(r => r.status === 'failed').length;
        setStatus(`Artwork write: ${written} written, ${failed} failed.`, 'idle');
        applyArtworkResultsToPayload(resultItems, payload);

        detailPanel.innerHTML = `
          <div class="finding">
            <h3>Apply Results</h3>
            ${resultItems.map(r => `
              <p>
                <span class="chip ${r.status === 'written' ? (isLowConfidenceArtworkSource(r.source) ? 'review' : 'safe') : r.status === 'failed' ? 'high' : 'indexing'}" style="font-size:0.78em">${escapeHtml(r.status)}</span>
                <span>${escapeHtml(r.artist_name)}</span>
                ${r.source ? `<span class="subtle"> ${escapeHtml(artworkSourceLabel(r.source))}</span>` : ''}
                ${r.message ? `<span class="subtle"> — ${escapeHtml(r.message)}</span>` : ''}
              </p>
            `).join('')}
          </div>`;

        renderCurrentPage();
      } catch (error) {
        setStatus(error.message, 'error');
        if (btn) btn.disabled = false;
      }
    }

    async function applySingleArtworkCandidate(artistName) {
      const source = sourceInput.value.trim();
      const payload = state.results.music.artwork;
      const candidate = state.approvedArtworkCandidates[artistName];
      if (!source || !payload || !candidate) return;

      const btn = document.getElementById('saveArtworkCandidate');
      if (btn) btn.disabled = true;
      setStatus(`Writing artwork for ${artistName}…`, 'running');

      try {
        const response = await fetch('/api/music/artwork/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source,
            items: [],
            candidates: [candidate]
          })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Apply failed.');

        const resultItems = result.results || [];
        applyArtworkResultsToPayload(resultItems, payload);
        const written = resultItems.some(r => r.status === 'written');
        const failed = resultItems.find(r => r.status === 'failed');
        if (failed) {
          setStatus(`${artistName} artwork write failed: ${failed.message || 'unknown error'}`, 'error');
        } else {
          setStatus(`${artistName} artwork ${written ? 'saved' : 'not changed'}.`, 'idle');
        }
        renderCurrentPage();
        showArtworkArtistDetailFromPayload(artistName);
      } catch (error) {
        setStatus(error.message, 'error');
        if (btn) btn.disabled = false;
      }
    }

    async function backfillJellyfinArtwork() {
      const source = sourceInput.value.trim();
      if (!source) return;
      const btn = document.getElementById('artworkBackfillJellyfin');
      if (btn) btn.disabled = true;
      setStatus('Backfilling Jellyfin folder.jpg files…', 'running');
      try {
        const response = await fetch('/api/music/artwork/backfill-jellyfin', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Backfill failed.');
        setStatus(`Backfill complete: ${result.written.length} folder.jpg file${result.written.length !== 1 ? 's' : ''} written.`, 'idle');
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    function showArtworkArtistDetailFromPayload(artistName) {
      const payload = state.results.music.artwork;
      if (!payload) return;
      const present = payload.present || [];
      const missing = payload.missing || [];
      const presentByArtist = new Map(present.map(item => [item.artist_name, item]));
      const artists = [
        ...present.map(item => ({ artist_name: item.artist_name, folder_path: item.folder_path, status: 'present', artwork: item })),
        ...missing.map(item => ({ artist_name: item.artist_name, folder_path: item.folder_path, status: 'missing', artwork: null }))
      ].sort((a, b) => a.artist_name.localeCompare(b.artist_name));
      showArtworkArtistDetail(artistName, artists, presentByArtist);
    }

    function applyArtworkResultsToPayload(results, payload) {
      if (!payload) return;
      payload.present = payload.present || [];
      payload.missing = payload.missing || [];
      results.filter(result => result.status === 'written').forEach(result => {
        const imagePath = result.folder_path + '/artist.jpg';
        payload.missing = payload.missing.filter(item => item.artist_name !== result.artist_name);
        payload.present = payload.present.filter(item => item.artist_name !== result.artist_name);
        payload.present.push({
          artist_name: result.artist_name,
          folder_path: result.folder_path,
          filename: 'artist.jpg',
          image_path: imagePath,
          source: result.source || 'local',
          file_size_bytes: result.file_size_bytes || 0,
          width: result.width || 0,
          height: result.height || 0,
          mtime_ns: result.mtime_ns || 0,
          image_cache_key: result.mtime_ns || Date.now()
        });
        state.selectedArtistNames.delete(result.artist_name);
        delete state.approvedArtworkCandidates[result.artist_name];
        delete state.artworkCandidates[result.artist_name];
        delete state.artworkImageSearchOffsets[result.artist_name];
      });
    }

    function movieDisplayName(item) {
      return item.display_name || item.movie_name;
    }

    function movieSortKey(item) {
      if (item.plex_title_sort) return item.plex_title_sort;
      return (item.display_name || item.movie_name).replace(/^(?:The |A |An )/i, '');
    }

    function moviePosterSrc(item) {
      if (item.plex_thumb) return '/api/movies/artwork/plex-image?path=' + encodeURIComponent(item.plex_thumb);
      if (item.image_path || item.filename) return moviePosterImageUrl(item.image_path || (item.folder_path + '/' + item.filename), item);
      return '';
    }

    function resolveMovieStatus(item, isMissing) {
      if (item.plex_thumb !== undefined && item.plex_thumb !== null) {
        // Plex data available: trust Plex
        return item.plex_thumb ? 'present' : 'missing';
      }
      // Plex not configured or movie not indexed: fall back to filesystem
      return isMissing ? 'missing' : 'present';
    }

    function renderMovieArtwork(payload) {
      const plexConfigured = !!(window.PLEX_CONFIGURED || (payload && payload.plex_configured));
      mainTagline.textContent = plexConfigured
        ? 'Showing Plex artwork. Missing = Plex has no poster for this title.'
        : 'Browse movie folders as Plex-compatible poster art. Missing poster.jpg files are shown in place. Add PLEX_TOKEN for Plex-synced view.';

      if (!payload) {
        renderMetrics([]);
        renderBars([]);
        filterBar.innerHTML = '';
        mainContent.innerHTML = '<div class="empty">Run Movies / Repair Artwork for Plex to browse movie folders and poster art.</div>';
        detailPanel.innerHTML = '<div class="empty">Run a scan first.</div>';
        return;
      }

      const present = payload.present || [];
      const missing = payload.missing || [];
      const total = present.length + missing.length;

      const LOW_SIZE = 30 * 1024;
      const LOW_W = 400;
      const LOW_H = 600;
      const lowQuality = present.filter(p => p.file_size_bytes > 0 && (p.file_size_bytes < LOW_SIZE || p.width < LOW_W || p.height < LOW_H));
      const presentByMovie = new Map(present.map(item => [item.movie_name, item]));
      const approved = Object.values(state.approvedMoviePosterCandidates);

      const movies = [
        ...present.map(item => ({ movie_name: item.movie_name, display_name: movieDisplayName(item), sort_key: movieSortKey(item), folder_path: item.folder_path, status: resolveMovieStatus(item, false), poster: item, plex_thumb: item.plex_thumb || null })),
        ...missing.map(item => ({ movie_name: item.movie_name, display_name: movieDisplayName(item), sort_key: movieSortKey(item), folder_path: item.folder_path, status: resolveMovieStatus(item, true), poster: null, plex_thumb: item.plex_thumb || null }))
      ].sort((a, b) => a.sort_key.localeCompare(b.sort_key, undefined, { numeric: true, sensitivity: 'base' }));

      renderMetrics([
        { value: String(total), label: 'movie folders' },
        { value: String(present.length), label: 'with poster' },
        { value: String(missing.length), label: 'missing poster' },
        { value: String(lowQuality.length), label: 'low quality' },
      ]);
      renderBars([
        { label: 'with poster', value: String(present.length), width: total ? (present.length / total) * 100 : 0 },
        { label: 'missing poster', value: String(missing.length), width: total ? (missing.length / total) * 100 : 0 },
      ]);
      renderFilters([
        ['all', 'All'],
        ['missing', 'Missing'],
        ['present', 'With Poster'],
        ['low', 'Low Quality']
      ]);

      function posterQualityBadge(item) {
        if (!item.width) return '';
        const isLow = item.file_size_bytes < LOW_SIZE || item.width < LOW_W || item.height < LOW_H;
        const label = item.width + '\xd7' + item.height;
        const color = isLow ? 'var(--danger)' : 'var(--accent)';
        return `<span style="font-size:10px;font-weight:600;color:${color};letter-spacing:0.03em">${label}</span>`;
      }

      const visibleMovies = movies.filter(movie => {
        if (state.filter === 'missing') return movie.status === 'missing';
        if (state.filter === 'present') return movie.status === 'present';
        if (state.filter === 'low') {
          const item = movie.poster;
          return item && item.file_size_bytes > 0 && (item.file_size_bytes < LOW_SIZE || item.width < LOW_W || item.height < LOW_H);
        }
        return true;
      });

      const movieTiles = visibleMovies.map(movie => {
        const item = movie.poster;
        const isPresent = movie.status === 'present';
        const isLow = item && item.file_size_bytes > 0 && (item.file_size_bytes < LOW_SIZE || item.width < LOW_W || item.height < LOW_H);
        const effectiveThumb = movie.plex_thumb;
        const imgSrc = effectiveThumb
          ? '/api/movies/artwork/plex-image?path=' + encodeURIComponent(effectiveThumb)
          : (item ? moviePosterSrc(item) : '');
        const hasApproved = !!state.approvedMoviePosterCandidates[movie.movie_name];
        const chipLabel = isPresent ? (effectiveThumb ? 'plex' : 'poster.jpg') : (hasApproved ? 'approved' : 'missing');
        const chipClass = isPresent ? 'safe' : (hasApproved ? 'review' : 'high');
        return `
          <button class="artist-tile" data-movie="${escapeHtml(movie.movie_name)}" style="width:140px">
            ${isPresent || effectiveThumb ? `
              <div class="artist-art" style="aspect-ratio:2/3;${isLow ? 'outline:3px solid rgba(138,51,65,0.65);outline-offset:-3px' : ''}">
                <img src="${escapeHtml(imgSrc)}" alt="${escapeHtml(movie.display_name)}" loading="lazy" style="object-fit:cover;width:100%;height:100%">
              </div>
            ` : '<div class="artist-art missing" style="aspect-ratio:2/3">Missing poster</div>'}
            <div class="artist-meta">
              <div class="artist-name">${escapeHtml(movie.display_name)}</div>
              <div><span class="chip ${chipClass}" style="font-size:0.72em">${chipLabel}</span>${item ? posterQualityBadge(item) : ''}</div>
            </div>
          </button>
        `;
      }).join('');

      const approvedCount = approved.length;
      mainContent.innerHTML = `
        <div class="artist-toolbar">
          <span class="subtle" id="moviePosterSelCount">${approvedCount} approved</span>
          <button class="primary" id="moviePosterApplyBtn" ${approvedCount === 0 ? 'disabled' : ''}>Write Approved to Library</button>
        </div>
        <div class="artist-grid" style="grid-template-columns:repeat(auto-fill,minmax(140px,1fr))">
          ${movieTiles || '<div class="empty">No movie folders match this filter.</div>'}
        </div>
      `;

      mainContent.querySelectorAll('.artist-tile').forEach(button => {
        button.addEventListener('click', () => showMoviePosterDetail(button.dataset.movie, movies, presentByMovie));
        attachMoviePosterDropTarget(button, button.dataset.movie);
      });
      document.getElementById('moviePosterApplyBtn')?.addEventListener('click', applyMoviePosters);
    }

    function showMoviePosterDetail(movieName, movies, presentByMovie) {
      const movie = movies.find(item => item.movie_name === movieName);
      if (!movie) return;
      const displayName = movie.display_name || movieName;
      const item = presentByMovie.get(movieName);
      const plexThumb = item ? item.plex_thumb : null;
      const plexImgSrc = plexThumb ? '/api/movies/artwork/plex-image?path=' + encodeURIComponent(plexThumb) : '';
      const localImgSrc = item ? moviePosterSrc(item) : '';
      const imgSrc = plexImgSrc || localImgSrc;
      const isPresent = movie.status === 'present';
      const approved = state.approvedMoviePosterCandidates[movieName];
      const previewSrc = approved ? (approved.preview_url || '') : imgSrc;
      detailPanel.innerHTML = `
        <div class="finding">
          <h3>${escapeHtml(displayName)}</h3>
          <p class="mono">${escapeHtml(movie.folder_path)}</p>
          ${isPresent ? `
            <div style="width:100%;max-width:220px;aspect-ratio:2/3;border-radius:8px;overflow:hidden;border:1px solid var(--line);background:#eee6d8;margin:12px 0">
              <img src="${escapeHtml(previewSrc)}" alt="${escapeHtml(displayName)}" style="width:100%;height:100%;object-fit:cover">
            </div>
            <div class="artwork-drop-zone" id="moviePosterDropZone">Drop poster image or image URL here</div>
            ${approved ? `
              <p><span class="chip review">approved replacement</span></p>
              ${item ? `<p class="subtle">Current: <span class="mono">${escapeHtml(item.filename)}</span>${item.width && item.height ? ` &middot; ${item.width}\xd7${item.height}` : ''} &middot; ${Math.round((item.file_size_bytes || 0) / 1024)} KB</p>` : ''}
              <button class="primary" id="saveMoviePosterBtn">Save Poster</button>
              <button class="secondary" id="clearMoviePosterBtn">Clear Approval</button>
            ` : `
              ${plexThumb ? '<p><span class="chip safe">plex</span> artwork from Plex</p>' : item ? `<p><span class="chip safe">poster.jpg</span> ${escapeHtml(item.filename)}</p><p class="subtle">${item.width && item.height ? item.width + '\xd7' + item.height : 'dimensions unknown'} &middot; ${Math.round((item.file_size_bytes || 0) / 1024)} KB</p>` : ''}
              <p class="subtle">Drop a replacement image to write a local poster.jpg.</p>
            `}
          ` : `
            ${approved ? `
              <div style="width:100%;max-width:220px;aspect-ratio:2/3;border-radius:8px;overflow:hidden;border:1px solid var(--line);background:#eee6d8;margin:12px 0">
                <img src="${escapeHtml(approved.preview_url || '')}" alt="${escapeHtml(displayName)} poster" style="width:100%;height:100%;object-fit:cover">
              </div>
              <div class="artwork-drop-zone" id="moviePosterDropZone">Drop poster image or image URL here</div>
              <p><span class="chip review">approved</span></p>
              <button class="primary" id="saveMoviePosterBtn">Save Poster</button>
              <button class="secondary" id="clearMoviePosterBtn">Clear Approval</button>
            ` : `
              <div class="artist-art missing" style="width:100%;max-width:220px;aspect-ratio:2/3;border:1px dashed var(--line);border-radius:8px;margin:12px 0">Missing poster</div>
              <div class="artwork-drop-zone" id="moviePosterDropZone">Drop poster image or image URL here</div>
              <p><span class="chip high">missing</span> Add <span class="mono">poster.jpg</span> to this movie folder.</p>
            `}
          `}
        </div>
      `;
      document.getElementById('clearMoviePosterBtn')?.addEventListener('click', () => {
        delete state.approvedMoviePosterCandidates[movieName];
        renderCurrentPage();
        showMoviePosterDetailFromPayload(movieName);
      });
      document.getElementById('saveMoviePosterBtn')?.addEventListener('click', () => applySingleMoviePoster(movieName));
      const dropZone = document.getElementById('moviePosterDropZone');
      if (dropZone) attachMoviePosterDropTarget(dropZone, movieName);
    }

    function showMoviePosterDetailFromPayload(movieName) {
      const payload = state.results.movies.artwork;
      if (!payload) return;
      const present = payload.present || [];
      const missing = payload.missing || [];
      const presentByMovie = new Map(present.map(item => [item.movie_name, item]));
      const movies = [
        ...present.map(item => ({ movie_name: item.movie_name, display_name: movieDisplayName(item), sort_key: movieSortKey(item), folder_path: item.folder_path, status: resolveMovieStatus(item, false), poster: item, plex_thumb: item.plex_thumb || null })),
        ...missing.map(item => ({ movie_name: item.movie_name, display_name: movieDisplayName(item), sort_key: movieSortKey(item), folder_path: item.folder_path, status: resolveMovieStatus(item, true), poster: null, plex_thumb: item.plex_thumb || null }))
      ].sort((a, b) => a.sort_key.localeCompare(b.sort_key, undefined, { numeric: true, sensitivity: 'base' }));
      showMoviePosterDetail(movieName, movies, presentByMovie);
    }

    function attachMoviePosterDropTarget(element, movieName) {
      element.addEventListener('dragover', event => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'copy';
        element.classList.add('dragover');
      });
      element.addEventListener('dragleave', () => {
        element.classList.remove('dragover');
      });
      element.addEventListener('drop', event => {
        event.preventDefault();
        event.stopPropagation();
        element.classList.remove('dragover');
        approveDroppedMoviePoster(event.dataTransfer, movieName);
      });
    }

    function approveDroppedMoviePoster(dataTransfer, movieName) {
      const file = Array.from(dataTransfer.files || []).find(item => item.type && item.type.startsWith('image/'));
      if (file) {
        const reader = new FileReader();
        reader.onload = () => {
          approveMoviePosterCandidate(movieName, {
            movie_name: movieName,
            folder_path: moviePosterFolderPath(movieName),
            source: 'drop',
            preview_url: String(reader.result || ''),
            image_url: String(reader.result || ''),
          });
        };
        reader.onerror = () => setStatus('Could not read dropped image file.', 'error');
        reader.readAsDataURL(file);
        return;
      }
      const url = droppedArtworkUrl(dataTransfer);
      if (!url) {
        setStatus('Drop an image file or a direct image URL.', 'error');
        return;
      }
      approveMoviePosterCandidate(movieName, {
        movie_name: movieName,
        folder_path: moviePosterFolderPath(movieName),
        source: 'drop',
        preview_url: url,
        image_url: url,
      });
    }

    function approveMoviePosterCandidate(movieName, candidate) {
      state.approvedMoviePosterCandidates[movieName] = candidate;
      setStatus(`${movieName} poster approved from drop.`, 'idle');
      renderCurrentPage();
      showMoviePosterDetailFromPayload(movieName);
    }

    function moviePosterFolderPath(movieName) {
      const payload = state.results.movies.artwork;
      const item = (payload?.present || []).find(item => item.movie_name === movieName)
        || (payload?.missing || []).find(item => item.movie_name === movieName);
      return item?.folder_path || '';
    }

    function moviePosterImageUrl(path, item) {
      const version = item?.mtime_ns || [item?.file_size_bytes || 0, item?.width || 0, item?.height || 0].join('-');
      return '/api/movies/artwork/image?path=' + encodeURIComponent(path) + '&v=' + encodeURIComponent(version);
    }

    function applyMoviePosterResultsToPayload(results, payload) {
      if (!payload) return;
      payload.present = payload.present || [];
      payload.missing = payload.missing || [];
      results.filter(result => result.status === 'written').forEach(result => {
        const imagePath = result.folder_path + '/poster.jpg';
        payload.missing = payload.missing.filter(item => item.movie_name !== result.movie_name);
        payload.present = payload.present.filter(item => item.movie_name !== result.movie_name);
        payload.present.push({
          movie_name: result.movie_name,
          folder_path: result.folder_path,
          filename: 'poster.jpg',
          image_path: imagePath,
          file_size_bytes: result.file_size_bytes || 0,
          width: result.width || 0,
          height: result.height || 0,
          mtime_ns: Date.now(),
        });
        delete state.approvedMoviePosterCandidates[result.movie_name];
      });
    }

    async function applyMoviePosters() {
      const source = sourceInput.value.trim();
      const payload = state.results.movies.artwork;
      if (!source || !payload) return;

      const candidates = Object.values(state.approvedMoviePosterCandidates);
      if (candidates.length === 0) return;

      const btn = document.getElementById('moviePosterApplyBtn');
      if (btn) btn.disabled = true;
      setStatus(`Writing posters for ${candidates.length} movie${candidates.length !== 1 ? 's' : ''}…`, 'running');

      try {
        const response = await fetch('/api/movies/artwork/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, candidates })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Apply failed.');

        const resultItems = result.results || [];
        const written = resultItems.filter(r => r.status === 'written').length;
        const failed = resultItems.filter(r => r.status === 'failed').length;
        setStatus(`Poster write: ${written} written, ${failed} failed.`, 'idle');
        applyMoviePosterResultsToPayload(resultItems, payload);

        detailPanel.innerHTML = `
          <div class="finding">
            <h3>Apply Results</h3>
            ${resultItems.map(r => `
              <p>
                <span class="chip ${r.status === 'written' ? 'safe' : r.status === 'failed' ? 'high' : 'indexing'}" style="font-size:0.78em">${escapeHtml(r.status)}</span>
                <span>${escapeHtml(r.movie_name)}</span>
                ${r.message ? `<span class="subtle"> — ${escapeHtml(r.message)}</span>` : ''}
              </p>
            `).join('')}
          </div>`;

        renderCurrentPage();
      } catch (error) {
        setStatus(error.message, 'error');
        if (btn) btn.disabled = false;
      }
    }

    async function applySingleMoviePoster(movieName) {
      const source = sourceInput.value.trim();
      const payload = state.results.movies.artwork;
      const candidate = state.approvedMoviePosterCandidates[movieName];
      if (!source || !payload || !candidate) return;

      const btn = document.getElementById('saveMoviePosterBtn');
      if (btn) btn.disabled = true;
      setStatus(`Writing poster for ${movieName}…`, 'running');

      try {
        const response = await fetch('/api/movies/artwork/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, candidates: [candidate] })
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || 'Apply failed.');

        const resultItems = result.results || [];
        applyMoviePosterResultsToPayload(resultItems, payload);
        const written = resultItems.some(r => r.status === 'written');
        const failed = resultItems.find(r => r.status === 'failed');
        if (failed) {
          setStatus(`${movieName} poster write failed: ${failed.message || 'unknown error'}`, 'error');
        } else {
          setStatus(`${movieName} poster ${written ? 'saved' : 'not changed'}.`, 'idle');
        }
        renderCurrentPage();
        showMoviePosterDetailFromPayload(movieName);
      } catch (error) {
        setStatus(error.message, 'error');
        if (btn) btn.disabled = false;
      }
    }

    function isLowConfidenceArtworkSource(source) {
      return source === 'web' || source === 'album' || source === 'wikimedia' || source === 'image-search' || source === 'drop';
    }

    function artworkSourceLabel(source) {
      if (source === 'web') return 'low confidence web';
      if (source === 'album') return 'low confidence album';
      if (source === 'wikimedia') return 'low confidence wikimedia';
      if (source === 'image-search') return 'low confidence Bing';
      if (source === 'drop') return 'low confidence dropped image';
      if (source === 'jellyfin') return 'jellyfin';
      return source || '';
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
        const audioBitrate = item.facts.audio_bitrate_kbps ? `${Math.round(item.facts.audio_bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
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
      if (state.page === 'audio_packaging') return 'audio_packaging';
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
        const audioBitrate = item.facts.audio_bitrate_kbps ? `${Math.round(item.facts.audio_bitrate_kbps).toLocaleString()} kbps` : '<span class="subtle">—</span>';
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
          <button class="secondary" id="toggleAllReplacementButton" ${selectableCount ? '' : 'disabled'}>${toggleLabel}</button>
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
          ? 'wrong default + weak English'
          : 'wrong default language';
        const audioSummary = item.facts.audio_summary ? escapeHtml(item.facts.audio_summary) : '<span class="subtle">—</span>';
        const profileSummary = movieProfileInlineSummary(item);
        const defaultStream = describeAudioStream(movieDefaultAudioStream(item));
        const englishStream = describeAudioStream(movieBestEnglishAudioStream(item));
        const selectable = !!issueCode;
        return `
          <tr>
            <td style="width:28px;text-align:center">${selectable ? `<input type="checkbox" class="replacement-select" data-path="${encodeURIComponent(path)}" ${checked} ${locked}>` : ''}</td>
            <td><div class="mono">${escapeHtml(path)}</div></td>
            <td>${escapeHtml(issueLabel)}${profileSummary ? `<div class="subtle">${escapeHtml(profileSummary)}</div>` : ''}</td>
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
      return `
        ${queueSummary}
        <div class="junk-actions audio-packaging-actions">
          <button class="secondary" id="toggleAllReplacementButton" ${(selectableCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>${toggleLabel}</button>
          <button class="primary" id="fixSelectedAudioButton" ${(selectedCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>Make English Default</button>
          <button class="primary" id="fixSelectedAudioAndDropForeignButton" ${(selectedCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>Make English Default + Delete Foreign Audio</button>
          <span class="triage-action-spacer"></span>
          <button class="danger" id="deleteSelectedFilesButton" ${(selectedCount && !state.movieAudioFixBusy) ? '' : 'disabled'}>Delete Selected Files</button>
          <span class="triage-action-note">${lockNote}</span>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th></th><th>File</th><th>Issue</th><th>Main Audio</th><th>Default Audio</th><th>English Audio</th><th>Status</th></tr></thead>
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
          <button class="secondary" id="toggleSubtitleRepairButton" ${(selectableCount && !state.movieSubtitleFixBusy) ? '' : 'disabled'}>${toggleLabel}</button>
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
      const actionsHtml = `
        <div class="dash-actions">
          <button class="secondary" id="exportCatalogueButton">Export Catalogue</button>
          <span class="subtle">Downloads movie-catalogue.xlsx for the selected library.</span>
        </div>
      `;
      if (!payload) return `${actionsHtml}<div class="empty">Run Movies / Dashboard to see the dashboard.</div>`;
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
              ${isEditable ? `<button class="secondary movie-profile-definition-toggle" data-profile-label="${escapeHtml(label)}">${isEditorOpen ? 'Close' : 'Edit'}</button>` : ''}
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
              ${isEditable ? `<button class="secondary movie-profile-definition-toggle" data-profile-label="${escapeHtml(label)}">${isEditorOpen ? 'Close' : 'Edit definition'}</button>` : ''}
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

      const riskCounts = histogram.risk_counts || {};
      const totalRisks = Object.values(riskCounts).reduce((a, b) => a + b, 0);
      const riskHtml = totalRisks > 0 ? `
        <div class="dash-section-label">Risks</div>
        <div class="dash-risk-row">
          ${Object.entries(riskCounts).map(([k, v]) => {
            const cls = k === 'indexing_visibility_risk' ? 'indexing' : 'playback';
            return `<span class="chip ${cls}">${escapeHtml(k.replace(/_/g, ' '))}: ${v}</span>`;
          }).join('')}
        </div>
      ` : '';

      return `
        ${actionsHtml}
        ${statsHtml}
        <div class="dash-section-label">Action Based</div>
        <div class="profile-grid">${actionCardsHtml || '<div class="subtle">No action data.</div>'}</div>
        <div class="dash-section-label">Quality Profile</div>
        <div class="profile-grid">${qualityCardsHtml || '<div class="subtle">No quality profile data.</div>'}</div>
        <div class="dash-section-label">Resolution Breakdown</div>
        <div class="dash-res-bars bars">${resBarsHtml || '<div class="subtle">No resolution data.</div>'}</div>
        ${riskHtml}
      `;
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
        setStatus(`Saved ${humanProfileLabel(label)} definition. Re-running dashboard…`, 'running');
        if (!source) {
          state.movieStandardsPendingDraft = null;
          state.movieStandardsEditorLabel = '';
          state.movieStandardsSaveBusy = false;
          renderMovieLibrary(state.results.movies.profile);
          setStatus(`Saved ${humanProfileLabel(label)} definition.`, 'idle');
          return;
        }
        const rerunResponse = await fetch('/api/movies/profile', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source })
        });
        const rerunPayload = await rerunResponse.json();
        if (!rerunResponse.ok) throw new Error(rerunPayload.error || 'Movie dashboard refresh failed.');
        storePayload('library', rerunPayload);
        state.movieStandardsPendingDraft = null;
        state.movieStandardsEditorLabel = '';
        setStatus(`Saved ${humanProfileLabel(label)} definition and refreshed ${rerunPayload.source_root}.`, 'idle');
        renderMovieLibrary(rerunPayload);
      } catch (error) {
        setStatus(error.message, 'error');
      } finally {
        state.movieStandardsSaveBusy = false;
        if (state.page === 'library') {
          renderMovieLibrary(state.results.movies.profile || restoreCachedMovieDashboard(source));
        }
      }
    }

    function renderMovieJunk(payload) {
      mainTagline.textContent = state.page === 'promo'
        ? 'Review likely promotional .txt and .html sidecar files before deletion.'
        : 'Review likely sample, featurette, short, and tiny video files before deletion.';
      renderMetrics(buildMovieJunkMetrics(payload));
      renderBars(buildMovieJunkBars(payload));
      renderFilters([
        ['all', 'All'],
        ['high', 'High'],
        ['review', 'Review']
      ]);
      if (!payload) {
        mainContent.innerHTML = `<div class="empty">Run Movies / ${state.page === 'promo' ? 'Delete Junk Sidecar & Spam Files' : 'Delete Junk Videos'} to build a review list.</div>`;
        return;
      }
      const rows = filteredMovieJunk(payload).map(item => {
        const path = item.path || '';
        const checked = state.selectedJunkPaths.has(path) ? 'checked' : '';
        return `
          <tr>
            <td><input type="checkbox" class="junk-select" data-path="${encodeURIComponent(path)}" ${checked}></td>
            <td>${escapeHtml(item.file_name || '')}</td>
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
        const resultKey = state.page === 'promo' ? 'promo' : 'junk';
        state.results.movies[resultKey] = removeDeletedJunk(state.results.movies[resultKey], payload.deleted || []);
        state.selectedJunkPaths.clear();
        const skipped = payload.skipped?.length || 0;
        statusText.textContent = `Deleted ${payload.deleted.length} file${payload.deleted.length === 1 ? '' : 's'}${skipped ? `; skipped ${skipped}` : ''}.`;
        renderMovieJunk(state.results.movies[resultKey]);
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
      return state.page === 'quality' || state.page === 'audio_packaging';
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
      if (state.page === 'audio_packaging') {
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
      if (state.page === 'audio_packaging') return !!movieAudioPackagingIssueCode(item);
      return isStrictWeakMovie(item);
    }

    function rerenderActiveMovieTriagePage(payload) {
      if (state.page === 'audio_packaging') renderMovieAudioPackaging(payload);
      else if (state.page === 'subtitle_readiness') renderMovieSubtitleReadiness(payload);
      else renderMovieQuality(payload);
    }

    function movieAudioFixSelectionLocked() {
      return state.page === 'audio_packaging' && state.movieAudioFixBusy;
    }

    function movieSubtitleFixSelectionLocked() {
      return state.page === 'subtitle_readiness' && state.movieSubtitleFixBusy;
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
          renderMovieSubtitleReadiness(payload);
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
          renderMovieSubtitleReadiness(payload);
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
          renderMovieSubtitleReadiness(payload);
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
      const actionLabel = dropForeignAudio ? 'Repairing and pruning foreign audio' : 'Repairing';
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
      renderMovieSubtitleReadiness(payload);
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
        renderMovieSubtitleReadiness(state.results.movies.profile || payload);
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
        if (state.page === 'quality' || state.page === 'audio_packaging') rerenderActiveMovieTriagePage(state.results.movies.profile);
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
        if (state.page === 'quality' || state.page === 'audio_packaging') rerenderActiveMovieTriagePage(state.results.movies.profile);
        else renderReplacementQueueDetail(state.results.movies.profile);
      } catch (error) {
        setStatus(error.message, 'error');
      }
    }

    function buildMusicNormalizeMetrics(payload) {
      if (!payload) return [];
      const safe = (payload.proposed_changes || []).filter(change => change.confidence === 'safe').length;
      const review = (payload.proposed_changes || []).filter(change => change.confidence === 'review').length;
      return [
        { value: String((payload.proposed_changes || []).length), label: 'planned changes' },
        { value: String(safe), label: 'safe changes' },
        { value: String(review), label: 'review changes' },
        { value: String((payload.warnings || []).length), label: 'warnings' }
      ];
    }

    function buildMusicDashboardMetrics(payload) {
      if (!payload) return [];
      const histogram = payload.histogram || {};
      const profileCounts = histogram.profile_counts || {};
      const topProfile = Object.entries(profileCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || '-';
      return [
        { value: String(histogram.track_count ?? (payload.tracks || []).length), label: 'tracks scanned' },
        { value: String(histogram.album_count ?? 0), label: 'albums' },
        { value: String(histogram.artist_count ?? 0), label: 'album artists' },
        { value: humanMusicProfileLabel(topProfile), label: 'top profile' }
      ];
    }

    function buildMusicDashboardBars(payload) {
      if (!payload) return [];
      const counts = payload.histogram?.profile_counts || {};
      const entries = Object.entries(counts).sort((a, b) => musicProfileRank(a[0]) - musicProfileRank(b[0]));
      const max = Math.max(...entries.map(([, value]) => value), 1);
      return entries.map(([key, value]) => ({ label: humanMusicProfileLabel(key), value: String(value), width: (value / max) * 100 }));
    }

    function humanMusicProfileLabel(label) {
      if (label === 'mp3_trash') return 'MP3 Trash';
      if (label === 'mp3_high_quality') return 'MP3 High Quality';
      if (label === 'flac_other') return 'FLAC Other';
      if (label === 'flac_44_1') return 'FLAC 44.1 kHz';
      if (label === 'flac_16_44_1') return 'FLAC 16-bit / 44.1 kHz';
      if (label === 'flac_24_44_1') return 'FLAC 24-bit / 44.1 kHz';
      if (label === 'flac_48') return 'FLAC 48 kHz';
      if (label === 'flac_16_48') return 'FLAC 16-bit / 48 kHz';
      if (label === 'flac_24_48') return 'FLAC 24-bit / 48 kHz';
      if (label === 'flac_88_2') return 'FLAC 88.2 kHz';
      if (label === 'flac_16_88_2') return 'FLAC 16-bit / 88.2 kHz';
      if (label === 'flac_24_88_2') return 'FLAC 24-bit / 88.2 kHz';
      if (label === 'flac_96') return 'FLAC 96 kHz';
      if (label === 'flac_16_96') return 'FLAC 16-bit / 96 kHz';
      if (label === 'flac_24_96') return 'FLAC 24-bit / 96 kHz';
      if (label === 'flac_176_4') return 'FLAC 176.4 kHz';
      if (label === 'flac_16_176_4') return 'FLAC 16-bit / 176.4 kHz';
      if (label === 'flac_24_176_4') return 'FLAC 24-bit / 176.4 kHz';
      if (label === 'flac_192') return 'FLAC 192 kHz';
      if (label === 'flac_16_192') return 'FLAC 16-bit / 192 kHz';
      if (label === 'flac_24_192') return 'FLAC 24-bit / 192 kHz';
      if (label === 'unknown_unreadable') return 'Unknown / Unreadable';
      return label || '—';
    }

    function musicProfileRank(label) {
      const order = [
        'mp3_trash', 'mp3_high_quality', 'flac_other',
        'flac_44_1', 'flac_16_44_1', 'flac_24_44_1',
        'flac_48', 'flac_16_48', 'flac_24_48',
        'flac_88_2', 'flac_16_88_2', 'flac_24_88_2',
        'flac_96', 'flac_16_96', 'flac_24_96',
        'flac_176_4', 'flac_16_176_4', 'flac_24_176_4',
        'flac_192', 'flac_16_192', 'flac_24_192',
        'unknown_unreadable'
      ];
      const index = order.indexOf(label);
      return index === -1 ? 98 : index;
    }

    function musicProfileGroup(label) {
      if (label.startsWith('flac')) return 'FLAC';
      if (label.startsWith('mp3')) return 'MP3';
      return 'Unknown';
    }

    function formatDashboardSize(bytes) {
      if (!bytes) return '—';
      if (bytes >= 1e12) return (bytes / 1e12).toFixed(1) + ' TB';
      if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
      return (bytes / 1e6).toFixed(1) + ' MB';
    }

    function buildMusicNormalizeBars(payload) {
      if (!payload) return [];
      const total = Math.max((payload.proposed_changes || []).length, 1);
      const safe = (payload.proposed_changes || []).filter(change => change.confidence === 'safe').length;
      const review = (payload.proposed_changes || []).filter(change => change.confidence === 'review').length;
      return [
        { label: 'safe', value: String(safe), width: (safe / total) * 100 },
        { label: 'review', value: String(review), width: (review / total) * 100 }
      ];
    }

    function filteredMusicChanges(payload) {
      if (!payload) return [];
      if (state.filter === 'warnings') return [];
      const changes = payload.proposed_changes || [];
      if (state.filter === 'all') return changes;
      return changes.filter(change => change.confidence === state.filter);
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
        { value: String((payload.proposed_changes || []).length), label: 'rename proposals' },
        { value: String(safe), label: 'safe renames' },
        { value: String(review), label: 'review renames' },
        { value: String((payload.warnings || []).length), label: 'warnings' }
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

    function buildMovieJunkMetrics(payload) {
      if (!payload) return [];
      const junk = payload.junk || [];
      const high = junk.filter(item => item.confidence === 'high').length;
      const review = junk.filter(item => item.confidence === 'review').length;
      return [
        { value: String(junk.length), label: state.page === 'promo' ? 'misc junk' : 'junk videos' },
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
        return {"music": "", "movies": "", "recent": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"music": "", "movies": "", "recent": []}
        music = data.get("music") if isinstance(data.get("music"), str) else ""
        movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
        recent = data.get("recent") if isinstance(data.get("recent"), list) else []
        recent = [
            r for r in recent
            if isinstance(r, dict)
            and r.get("lane") in {"music", "movies"}
            and isinstance(r.get("source"), str)
            and r["source"]
        ][:2]
        return {"music": music, "movies": movies, "recent": recent}
    except (OSError, json.JSONDecodeError):
        return {"music": "", "movies": "", "recent": []}


def save_library_roots(data: dict[str, Any]) -> None:
    path = library_roots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    music = data.get("music") if isinstance(data.get("music"), str) else ""
    movies = data.get("movies") if isinstance(data.get("movies"), str) else ""
    recent = data.get("recent") if isinstance(data.get("recent"), list) else []
    recent = [
        r for r in recent
        if isinstance(r, dict)
        and r.get("lane") in {"music", "movies"}
        and isinstance(r.get("source"), str)
        and r["source"]
    ][:2]
    payload = json.dumps({"music": music, "movies": movies, "recent": recent}, indent=2) + "\n"
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
    plex_token: str | None = None,
    plex_url: str = "http://localhost:32400",
) -> None:
    handler = build_handler(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key, plex_token=plex_token, plex_url=plex_url)
    server = ThreadingHTTPServer((host, port), handler)
    source_hint = f" default source {default_source}" if default_source else ""
    print(f"normal web UI listening on http://{host}:{port}/{source_hint}")
    server.serve_forever()


def render_index_html(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None, plex_configured: bool = False) -> str:
    return INDEX_HTML.replace(
        "<script>",
        (
            "<script>\n"
            f"    window.DEFAULT_SOURCE = {json.dumps(str(default_source) if default_source else '')};\n"
            f"    window.OMDB_AVAILABLE = {json.dumps(bool(omdb_key))};\n"
            f"    window.TMDB_KEY = {json.dumps(tmdb_key or '')};\n"
            f"    window.PLEX_CONFIGURED = {json.dumps(plex_configured)};"
        ),
        1,
    )


def build_handler(
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
    plex_token: str | None = None,
    plex_url: str = "http://localhost:32400",
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
            if self.path.startswith("/api/music/artwork/image"):
                self.handle_artwork_image()
                return
            if self.path.startswith("/api/movies/artwork/image"):
                self.handle_artwork_image()
                return
            if self.path.startswith("/api/movies/artwork/plex-image"):
                self.handle_plex_image()
                return
            if self.path not in {"/", "/index.html"}:
                self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            html = render_index_html(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key, plex_configured=bool(plex_token))
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
                if route == "/api/movies/promo-docs":
                    self.handle_movies_promo_docs(payload)
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
                if route == "/api/music/replacement-queue/list":
                    self.handle_music_replacement_queue_list(payload)
                    return
                if route == "/api/music/replacement-queue/add":
                    self.handle_music_replacement_queue_add(payload)
                    return
                if route == "/api/music/replacement-queue/delete":
                    self.handle_music_replacement_queue_delete(payload)
                    return
                if route == "/api/music/profile":
                    self.handle_music_profile(payload)
                    return
                if route == "/api/music/normalize":
                    self.handle_music_normalize(payload)
                    return
                if route == "/api/music/apply":
                    self.handle_music_apply(payload)
                    return
                if route == "/api/music/artwork/scan":
                    self.handle_music_artwork_scan(payload)
                    return
                if route == "/api/music/artwork/candidates":
                    self.handle_music_artwork_candidates(payload)
                    return
                if route == "/api/music/artwork/image-search":
                    self.handle_music_artwork_image_search(payload)
                    return
                if route == "/api/music/artwork/apply":
                    self.handle_music_artwork_apply(payload)
                    return
                if route == "/api/music/artwork/backfill-jellyfin":
                    self.handle_music_artwork_backfill_jellyfin(payload)
                    return
                if route == "/api/music/artwork/promote":
                    self.handle_music_artwork_promote(payload)
                    return
                if route == "/api/movies/artwork/scan":
                    self.handle_movies_artwork_scan(payload)
                    return
                if route == "/api/movies/artwork/apply":
                    self.handle_movies_artwork_apply(payload)
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
                        probe_media=tracked_probe(source, "ffprobe movie metadata"),
                        progress_callback=update_profile_activity,
                        should_cancel=self.client_disconnected,
                    )
                    response = report.to_dict()
                    response["histogram"] = build_histogram_payload(report)
                    response["replacement_queue"] = reconcile_replacement_queue(source, response["movies"])
                    standards = load_movie_standards()
                    response["movie_standards"] = standards
                    response["movie_standards_revision"] = movie_standards_revision(standards)
                    response["quality_profile_definitions"] = build_movie_profile_definitions(standards)
                    response["replacement_candidate_definition"] = build_replacement_candidate_definition(standards)
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

        def handle_music_profile(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with guarded_heavy_scan(source, "Music profile scan"):
                with ACTIVITY_TRACKER.track(source, "Music profile scan"):
                    report = scan_music_profiles(source)
                    response = report.to_dict()
                    response["histogram"] = build_music_histogram_payload(report)
                    response["replacement_queue"] = music_reconcile_replacement_queue(source, response["tracks"])
            self.respond_json(response)

        def handle_music_replacement_queue_list(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            self.respond_json(music_queue_for_source(source))

        def handle_music_replacement_queue_add(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            items = payload.get("items")
            if not isinstance(items, list):
                raise ValueError("items must be a list")
            self.respond_json(music_add_profile_items_to_queue(source, items))

        def handle_music_replacement_queue_delete(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            item_ids = payload.get("item_ids")
            if not isinstance(item_ids, list):
                raise ValueError("item_ids must be a list")
            self.respond_json(music_delete_replacement_queue_media(source, item_ids))

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
                    scan_report = scan_movie_library(source, probe_media=tracked_probe(source, "ffprobe movie catalogue"))
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
                        probe_media=tracked_probe(source, "ffprobe movie inspect"),
                    ).to_dict()
                )

        def handle_movies_normalize(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            requested_style = str(payload.get("naming_style") or DEFAULT_MOVIE_NAMING_STYLE)
            if requested_style not in MOVIE_NAMING_STYLES:
                raise ValueError(f"unknown movie naming style: {requested_style}")
            with guarded_heavy_scan(source, "Movie normalize plan"):
                with ACTIVITY_TRACKER.track(source, "Movie normalize plan"):
                    plans_by_style = {style: build_movie_plan(source, naming_style=style) for style in MOVIE_NAMING_STYLES}
                    response = plans_by_style[requested_style].to_dict()
                    response["naming_style"] = requested_style
                    response["default_naming_style"] = DEFAULT_MOVIE_NAMING_STYLE
                    response["proposed_changes_by_naming_style"] = {
                        style: plans_by_style[style].to_dict()["proposed_changes"] for style in MOVIE_NAMING_STYLES
                    }
                    response["warnings_by_naming_style"] = {
                        style: plans_by_style[style].to_dict()["warnings"] for style in MOVIE_NAMING_STYLES
                    }
                    response["movie_files"] = [str(path) for path in discover_video_files(source)]
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
                plans_by_style = {style: build_movie_plan(source, naming_style=style) for style in MOVIE_NAMING_STYLES}
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
            remaining_payload["movie_files"] = [str(path) for path in discover_video_files(source)]
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
                    report = scan_movie_junk(source, probe_media=tracked_probe(source, "ffprobe junk scan"))
            self.respond_json(report.to_dict())

        def handle_movies_promo_docs(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with guarded_heavy_scan(source, "Movie misc junk scan"):
                with ACTIVITY_TRACKER.track(source, "Movie misc junk scan"):
                    report = scan_movie_promo_documents(source)
            self.respond_json(report.to_dict())

        def handle_movies_junk_delete(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            paths = payload.get("paths")
            if not isinstance(paths, list):
                raise ValueError("paths must be a list")
            with ACTIVITY_TRACKER.track(source, "Movie junk delete"):
                result = delete_movie_junk_files(source, paths, probe_media=tracked_probe(source, "ffprobe junk delete check"))
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
                    probe_media=tracked_probe(source, "ffprobe audio packaging fix"),
                    drop_foreign_audio=drop_foreign_audio,
                    progress_callback=lambda update: ACTIVITY_TRACKER.update(activity_id, **update),
                )
            fixed_paths = [str(item.get("path") or "") for item in result["fixed"]]
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
                    probe_media=tracked_probe(source, "ffprobe subtitle readiness fix"),
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

        def handle_music_normalize(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with ACTIVITY_TRACKER.track(source, "Music normalize plan"):
                plan = build_plan(source)
                response = plan.to_dict()
                response["summary"] = summarize_music_plan(response)
            self.respond_json(response)

        def handle_music_apply(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            raw_changes = payload.get("changes", [])
            if not isinstance(raw_changes, list):
                raise ValueError("changes must be a list")
            changes = [ProposedChange(**c) for c in raw_changes]
            with ACTIVITY_TRACKER.track(source, "Music apply"):
                report = apply_changes_in_place(source, changes)
            self.respond_json(report.to_dict())

        def handle_music_artwork_scan(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with ACTIVITY_TRACKER.track(source, "Music artwork scan"):
                report = scan_artist_artwork(source)
            self.respond_json(report.to_dict())

        def handle_music_artwork_backfill_jellyfin(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            with ACTIVITY_TRACKER.track(source, "Music artwork backfill"):
                result = backfill_jellyfin_artist_artwork(source)
            self.respond_json(result)

        def handle_music_artwork_candidates(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            artist_name = payload.get("artist_name")
            if not isinstance(artist_name, str) or not artist_name.strip():
                raise ValueError("artist_name is required")
            with ACTIVITY_TRACKER.track(source, "Music artwork candidates"):
                gap = self.find_artwork_gap(source, artist_name)
                candidates = (
                    find_album_artwork_candidates(gap)
                    + search_wikimedia_artist_candidates(gap)
                    + find_web_artist_candidates(gap)
                    + find_image_search_artist_candidates(gap)
                )
            self.respond_json({
                "source_root": str(source),
                "artist_name": artist_name,
                "candidates": [candidate.to_dict() for candidate in candidates],
            })

        def handle_music_artwork_image_search(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            artist_name = payload.get("artist_name")
            if not isinstance(artist_name, str) or not artist_name.strip():
                raise ValueError("artist_name is required")
            raw_offset = payload.get("offset", 0)
            if not isinstance(raw_offset, int):
                raise ValueError("offset must be an integer")
            offset = max(raw_offset, 0)
            with ACTIVITY_TRACKER.track(source, "Music artwork image search"):
                gap = self.find_artwork_gap(source, artist_name)
                candidates = find_image_search_artist_candidates(gap, offset=offset)
            self.respond_json({
                "source_root": str(source),
                "artist_name": artist_name,
                "offset": offset,
                "candidates": [candidate.to_dict() for candidate in candidates],
            })

        def find_artwork_gap(self, source: Path, artist_name: str) -> ArtworkGapItem:
            report = scan_artist_artwork(source)
            gap = next((item for item in report.missing if item.artist_name == artist_name), None)
            if gap is None:
                present = next((item for item in report.present if item.artist_name == artist_name), None)
                if present is not None:
                    gap = ArtworkGapItem(artist_name=present.artist_name, folder_path=present.folder_path)
            if gap is None:
                raise ValueError("artist was not found in the current artwork scan")
            return gap

        def handle_music_artwork_apply(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            requested_names = payload.get("items")
            if not isinstance(requested_names, list):
                raise ValueError("items must be a list of artist names")
            requested_set = set(requested_names)
            report = scan_artist_artwork(source)
            candidates = [
                item
                for item in report.present
                if item.source == "jellyfin" and item.artist_name in requested_set
            ]
            approved_candidates = payload.get("candidates", [])
            if not isinstance(approved_candidates, list):
                raise ValueError("candidates must be a list")
            missing_by_name = {item.artist_name: item for item in report.missing}
            present_by_name = {item.artist_name: item for item in report.present}
            resolutions = [resolve_cached_artwork(item) for item in candidates]
            replacement_resolutions = []
            for candidate in approved_candidates:
                if not isinstance(candidate, dict):
                    continue
                artist_name = candidate.get("artist_name")
                image_url = candidate.get("image_url")
                source_name = candidate.get("source", "remote")
                if not isinstance(artist_name, str) or not isinstance(image_url, str):
                    continue
                gap = missing_by_name.get(artist_name)
                if gap is None and artist_name in present_by_name:
                    present_item = present_by_name[artist_name]
                    gap = ArtworkGapItem(artist_name=present_item.artist_name, folder_path=present_item.folder_path)
                if gap is None:
                    continue
                approved_gap = ArtworkGapItem(artist_name=gap.artist_name, folder_path=gap.folder_path)
                if source_name == "album":
                    candidate_path = Path(image_url).resolve()
                    artist_folder = Path(gap.folder_path).resolve()
                    try:
                        candidate_path.relative_to(artist_folder)
                    except ValueError:
                        continue
                    replacement_resolutions.append(resolve_file_artwork(
                        approved_gap,
                        str(candidate_path),
                        "album",
                        title=str(candidate.get("title") or candidate_path.name),
                    ))
                elif source_name == "web":
                    rediscovered = {
                        candidate.image_url
                        for candidate in find_web_artist_candidates(gap)
                    }
                    if image_url not in rediscovered:
                        continue
                    replacement_resolutions.append(resolve_remote_artwork(
                        approved_gap,
                        image_url,
                        "web",
                        allowed_hosts=set(),
                        title=str(candidate.get("title") or ""),
                        page_url=str(candidate.get("page_url") or ""),
                    ))
                elif source_name == "image-search":
                    search_offset = candidate.get("search_offset", 0)
                    if not isinstance(search_offset, int):
                        search_offset = 0
                    rediscovered = {
                        candidate.image_url
                        for candidate in find_image_search_artist_candidates(gap, offset=search_offset)
                    }
                    if image_url not in rediscovered:
                        continue
                    replacement_resolutions.append(resolve_remote_artwork(
                        approved_gap,
                        image_url,
                        "image-search",
                        allowed_hosts=set(),
                        title=str(candidate.get("title") or ""),
                        page_url=str(candidate.get("page_url") or ""),
                    ))
                elif source_name == "drop":
                    title = str(candidate.get("title") or "dropped image")
                    if image_url.startswith("data:image/"):
                        replacement_resolutions.append(resolve_data_url_artwork(
                            approved_gap,
                            image_url,
                            "drop",
                            title=title,
                        ))
                    else:
                        replacement_resolutions.append(resolve_remote_artwork(
                            approved_gap,
                            image_url,
                            "drop",
                            allowed_hosts=set(),
                            title=title,
                            page_url=str(candidate.get("page_url") or ""),
                        ))
                else:
                    replacement_resolutions.append(resolve_remote_artwork(
                        approved_gap,
                        image_url,
                        str(source_name),
                        title=str(candidate.get("title") or ""),
                        page_url=str(candidate.get("page_url") or ""),
                    ))
            results = apply_artwork(resolutions, dry_run=False)
            if replacement_resolutions:
                results.extend(apply_artwork(replacement_resolutions, dry_run=False, overwrite=True))
            result_payload = []
            for result in results:
                item = {
                    "artist_name": result.artist_name,
                    "folder_path": result.folder_path,
                    "status": result.status,
                    "source": result.source,
                    "message": result.message,
                }
                if result.status == "written":
                    image_path = Path(result.folder_path) / "artist.jpg"
                    try:
                        stat = image_path.stat()
                        item["file_size_bytes"] = stat.st_size
                        item["mtime_ns"] = stat.st_mtime_ns
                        with Image.open(image_path) as img:
                            item["width"], item["height"] = img.size
                    except Exception:
                        pass
                result_payload.append(item)
            self.respond_json({
                "source_root": str(source),
                "results": result_payload,
            })

        def handle_music_artwork_promote(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            folder_path = payload.get("folder_path")
            if not isinstance(folder_path, str) or not folder_path.strip():
                raise ValueError("folder_path is required")
            folder = Path(folder_path).resolve()
            try:
                folder.relative_to(source.resolve())
            except ValueError:
                raise ValueError("folder_path is not within the source root")
            provenance_file = folder / PROVENANCE_FILENAME
            with ACTIVITY_TRACKER.track(source, "Music artwork promote"):
                if provenance_file.exists():
                    provenance_file.unlink()
            self.respond_json({"ok": True, "folder_path": str(folder)})

        def handle_movies_artwork_scan(self, payload: dict[str, Any]) -> None:
            from normal.movie_artwork import fetch_plex_movie_index
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            plex_index = fetch_plex_movie_index(plex_url, plex_token) if plex_token else None
            with ACTIVITY_TRACKER.track(source, "Movie poster scan"):
                report = scan_movie_posters(source, plex_index=plex_index)
            result = report.to_dict()
            result["plex_configured"] = bool(plex_token)
            self.respond_json(result)

        def handle_movies_artwork_apply(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            candidates = payload.get("candidates", [])
            if not isinstance(candidates, list):
                raise ValueError("candidates must be a list")
            with ACTIVITY_TRACKER.track(source, "Movie poster apply"):
                result = apply_movie_posters(source, candidates)
            self.respond_json(result)

        def handle_artwork_image(self) -> None:
            from urllib.parse import parse_qs, urlparse
            qs = parse_qs(urlparse(self.path).query)
            paths = qs.get("path", [])
            if not paths:
                self.respond_json({"error": "missing path"}, status=HTTPStatus.BAD_REQUEST)
                return
            img_path = Path(paths[0])
            if not img_path.is_file():
                self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            suffix = img_path.suffix.lower()
            mime = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png" if suffix == ".png" else "image/jpeg"
            data = img_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def handle_plex_image(self) -> None:
            from urllib.parse import parse_qs, urlparse
            if not plex_token:
                self.respond_json({"error": "plex not configured"}, status=HTTPStatus.NOT_FOUND)
                return
            qs = parse_qs(urlparse(self.path).query)
            paths = qs.get("path", [])
            if not paths or not paths[0].startswith("/library/"):
                self.respond_json({"error": "invalid path"}, status=HTTPStatus.BAD_REQUEST)
                return
            thumb_url = f"{plex_url}{paths[0]}?X-Plex-Token={plex_token}"
            try:
                req = urllib.request.Request(thumb_url, headers={"Accept": "image/*"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()
                    content_type = resp.headers.get("Content-Type", "image/jpeg")
            except Exception:
                self.respond_json({"error": "plex fetch failed"}, status=HTTPStatus.BAD_GATEWAY)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(data)

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


def summarize_music_plan(payload: dict[str, Any]) -> dict[str, Any]:
    changes = payload.get("proposed_changes", [])
    confidence_counts = Counter(change.get("confidence", "") for change in changes)
    change_type_counts = Counter(change.get("change_type", "") for change in changes)
    return {
      "change_count": len(changes),
      "confidence_counts": dict(confidence_counts),
      "change_type_counts": dict(change_type_counts),
      "warning_count": len(payload.get("warnings", [])),
    }


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


def tracked_probe(source: Path, label: str) -> Callable[[Path], Any]:
    def probe(path: Path) -> Any:
        with ACTIVITY_TRACKER.track(source, label, kind="probe", current_path=path):
            return probe_media_facts(path)

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
