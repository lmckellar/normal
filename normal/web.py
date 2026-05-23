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
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
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


WEB_ASSET_ROOT = "web_assets"
WEB_ASSET_TEMPLATE = "index.html"
WEB_STATIC_ASSETS = {
    "/assets/app.css": ("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
WEB_BOOTSTRAP_SENTINEL = "__NORMAL_BOOTSTRAP__"


@lru_cache(maxsize=None)
def read_web_asset_text(name: str) -> str:
    return resources.files("normal").joinpath(WEB_ASSET_ROOT, name).read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def read_web_asset_bytes(name: str) -> bytes:
    return read_web_asset_text(name).encode("utf-8")


def render_web_bootstrap(default_source: Path | None = None, omdb_key: str | None = None, tmdb_key: str | None = None) -> str:
    return "\n".join(
        (
            f"window.DEFAULT_SOURCE = {json.dumps(str(default_source) if default_source else '')};",
            f"window.OMDB_AVAILABLE = {json.dumps(bool(omdb_key))};",
            f"window.TMDB_KEY = {json.dumps(tmdb_key or '')};",
        )
    )



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
    template = read_web_asset_text(WEB_ASSET_TEMPLATE)
    return template.replace(
        WEB_BOOTSTRAP_SENTINEL,
        render_web_bootstrap(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key),
        1,
    )


def build_handler(
    default_source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            route = self.path.split("?", 1)[0]
            if route.startswith("/api/activity"):
                try:
                    self.handle_activity()
                except Exception as exc:
                    self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if route == "/api/library-roots":
                try:
                    self.respond_json(load_library_roots())
                except Exception as exc:
                    self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            if route in WEB_STATIC_ASSETS:
                self.serve_static_asset(route)
                return
            if route not in {"/", "/index.html"}:
                self.respond_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
            html = render_index_html(default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key)
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def serve_static_asset(self, route: str) -> None:
            asset_name, content_type = WEB_STATIC_ASSETS[route]
            body = read_web_asset_bytes(asset_name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
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
                    report = scan_movie_cleanup(source)
            self.respond_json(report.to_dict())

        def handle_movies_junk_delete(self, payload: dict[str, Any]) -> None:
            source = resolve_source_path(payload.get("source"), default_source=default_source)
            paths = payload.get("paths")
            if not isinstance(paths, list):
                raise ValueError("paths must be a list")
            with ACTIVITY_TRACKER.track(source, "Movie junk delete"):
                result = delete_movie_junk_files(source, paths)
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
        reasons = detect_movie_junk_reasons(resolved)
        if not reasons:
            reasons = detect_movie_junk_document_reasons(resolved)
        if not reasons:
            skipped.append({"path": str(resolved), "reason": "not_current_junk_candidate"})
            continue
        resolved.unlink()
        deleted.append(str(resolved))

    return {"deleted": deleted, "skipped": skipped}
