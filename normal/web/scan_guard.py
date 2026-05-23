from __future__ import annotations

import select
import shutil
import socket
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from . import state


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


def client_disconnected(connection: socket.socket) -> bool:
    try:
        readable, _, _ = select.select([connection], [], [], 0)
        if not readable:
            return False
        return connection.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


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


def format_storage_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000_000_000:
        return f"{size_bytes / 1_000_000_000_000:.1f} TB"
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{size_bytes / 1_000_000:.1f} MB"


def build_source_scan_warning(source: Path) -> dict[str, Any]:
    resolved = source.resolve()
    usage = shutil.disk_usage(resolved)
    reasons: list[str] = []
    if looks_like_drive_directory(resolved):
        reasons.append("drive_directory")
    reasons.extend(risky_mount_flags(resolved))
    mount_details = source_mount_details(resolved)
    message_parts: list[str] = []
    if "drive_directory" in reasons:
        message_parts.append("It looks like you are scanning a drive directory.")
    if any(reason.startswith("mount:") for reason in reasons):
        fstype = mount_details.fstype.upper() if mount_details.fstype else "FUSE/NTFS"
        message_parts.append(f"This source is on a {fstype} mount, which is higher risk for heavy recursive scans on Ubuntu GNOME.")
    return {
        "source": str(resolved),
        "warn": bool(reasons),
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "message": " ".join(message_parts).strip(),
        "mount_fstype": mount_details.fstype,
        "mount_target": mount_details.target,
        "total_size_bytes": usage.total,
        "total_size_label": format_storage_size(usage.total),
    }


@contextmanager
def guarded_heavy_scan(source: Path, label: str, *, category: str = "heavy_scan") -> Iterator[None]:
    with state.HEAVY_SCAN_REGISTRY.claim(source, category, label):
        yield
