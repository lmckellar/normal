from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

ProgressCallback = Callable[[dict[str, Any]], None]


def mkvpropedit_available() -> bool:
    return shutil.which("mkvpropedit") is not None


def build_mkvpropedit_command(
    path: Path,
    *,
    audio_defaults: list[bool] | None = None,
    subtitle_defaults: list[bool] | None = None,
    subtitle_forced: list[bool] | None = None,
) -> list[str]:
    command = ["mkvpropedit", str(path)]
    if audio_defaults is not None:
        for ordinal, is_default in enumerate(audio_defaults):
            command.extend(
                [
                    "--edit",
                    f"track:a{ordinal + 1}",
                    "--set",
                    f"flag-default={1 if is_default else 0}",
                ]
            )
    if subtitle_defaults is not None:
        forced = subtitle_forced or [False] * len(subtitle_defaults)
        for ordinal, is_default in enumerate(subtitle_defaults):
            command.extend(
                [
                    "--edit",
                    f"track:s{ordinal + 1}",
                    "--set",
                    f"flag-default={1 if is_default else 0}",
                    "--set",
                    f"flag-forced={1 if forced[ordinal] else 0}",
                ]
            )
    return command


def build_instant_progress_update(source_path: Path, fraction: float) -> dict[str, Any]:
    resolved = str(source_path.resolve())
    return {
        "current_path": resolved,
        "output_path": resolved,
        "status_text": "mkvpropedit header edit",
        "progress_state": "end" if fraction >= 1 else "continue",
        "completed_seconds": None,
        "total_seconds": None,
        "progress_fraction": fraction,
        "eta_seconds": 0,
        "output_size_bytes": None,
        "speed": None,
    }


def run_mkvpropedit(
    path: Path,
    command: list[str],
    *,
    progress_callback: ProgressCallback | None = None,
) -> None:
    if progress_callback is not None:
        progress_callback(build_instant_progress_update(path, 0.0))
    process = subprocess.run(command, capture_output=True, text=True)
    # mkvtoolnix: 0 = success, 1 = warnings (changes still written), 2 = error.
    if process.returncode >= 2:
        message = (process.stderr or process.stdout or "mkvpropedit failed").strip()
        raise RuntimeError(message)
    if progress_callback is not None:
        progress_callback(build_instant_progress_update(path, 1.0))
