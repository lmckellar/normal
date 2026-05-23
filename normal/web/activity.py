from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from normal.movie_scan import probe_media_facts
from normal.probe_cache import ProbeCache

from . import state
from .scan_guard import path_is_under, source_paths_overlap


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


def tracked_probe(source: Path, label: str, cache: ProbeCache | None = None) -> Callable[[Path], Any]:
    def probe(path: Path) -> Any:
        if cache is not None:
            cached = cache.get(path)
            if cached is not None:
                return cached
        with state.ACTIVITY_TRACKER.track(source, label, kind="probe", current_path=path):
            facts = probe_media_facts(path)
        if cache is not None:
            cache.put(path, facts)
        return facts

    return probe


def build_activity_payload(source: Path) -> dict[str, Any]:
    app_items = state.ACTIVITY_TRACKER.snapshot(source)
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
