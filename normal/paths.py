from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "normal"


def replacement_queue_path() -> Path:
    return data_dir() / "movie-replacement-queue.json"


def subtitle_history_path() -> Path:
    return data_dir() / "subtitle-fix-history.json"
