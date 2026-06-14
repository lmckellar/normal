from __future__ import annotations

import json
import select
import shutil
import socket
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from normal.source_policy import ApprovedRoots, path_is_under, resolve_source_path, source_paths_overlap
from . import state


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


RISKY_FSTYPES = frozenset(
    {
        "ntfs",
        "ntfs3",
        "fuseblk",
        "exfat",
        "vfat",
        "drvfs",
        "cifs",
        "smbfs",
        "nfs",
        "nfs4",
        "sshfs",
        "fuse.sshfs",
        "rclone",
        "fuse.rclone",
        "mergerfs",
        "fuse.mergerfs",
    }
)

FILESYSTEM_BOUNDARY_WARNING = (
    "This source looks like a filesystem boundary or translated/network/removable filesystem. "
    "Heavy recursive scans may be slow, incomplete, or surprising. "
    "Choose a specific movie-library folder below this root, or restart with an explicit override."
)

UNC_SHARE_ROOT_WARNING = (
    "You selected a network share root. "
    "Normal will not recursively scan or mutate a whole share by default. "
    "Choose a specific library folder inside the share."
)


def _findmnt_mount_details(source: Path) -> SourceMountDetails | None:
    try:
        result = subprocess.run(
            ["findmnt", "--json", "-T", str(source), "-o", "TARGET,FSTYPE"],
            text=True,
            capture_output=True,
            check=False,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        filesystems = json.loads(result.stdout).get("filesystems", [])
    except (ValueError, AttributeError):
        return None
    if not filesystems:
        return None
    entry = filesystems[0]
    target = entry.get("target")
    fstype = entry.get("fstype")
    return SourceMountDetails(target=target, fstype=fstype.lower() if fstype else None)


def _unescape_proc_mount_field(field: str) -> str:
    return (
        field.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _proc_mounts_mount_details(source: Path) -> SourceMountDetails | None:
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    best: SourceMountDetails | None = None
    best_len = -1
    for line in lines:
        parts = line.split(" ")
        if len(parts) < 3:
            continue
        target = _unescape_proc_mount_field(parts[1])
        fstype = parts[2]
        target_path = Path(target)
        if path_is_under(source, target_path) and len(target_path.parts) > best_len:
            best_len = len(target_path.parts)
            best = SourceMountDetails(target=target, fstype=fstype.lower())
    return best


def source_mount_details(source: Path) -> SourceMountDetails:
    resolved = source.resolve()
    details = _findmnt_mount_details(resolved)
    if details is None:
        details = _proc_mounts_mount_details(resolved)
    if details is None:
        return SourceMountDetails(fstype=None, target=None)
    return details


def risky_mount_flags(source: Path) -> list[str]:
    details = source_mount_details(source)
    flags: list[str] = []
    if details.fstype in RISKY_FSTYPES:
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


def looks_like_unc_share_root(path: Path) -> bool:
    anchor = path.anchor
    return anchor.startswith("\\\\") and path == path.__class__(anchor)


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
    if looks_like_unc_share_root(resolved):
        message = UNC_SHARE_ROOT_WARNING
    elif reasons:
        message = FILESYSTEM_BOUNDARY_WARNING
    else:
        message = ""
    return {
        "source": str(resolved),
        "warn": bool(reasons),
        "reason": reasons[0] if reasons else None,
        "reasons": reasons,
        "message": message,
        "mount_fstype": mount_details.fstype,
        "mount_target": mount_details.target,
        "total_size_bytes": usage.total,
        "total_size_label": format_storage_size(usage.total),
    }


@contextmanager
def guarded_heavy_scan(source: Path, label: str, *, category: str = "heavy_scan") -> Iterator[None]:
    with state.HEAVY_SCAN_REGISTRY.claim(source, category, label):
        yield
