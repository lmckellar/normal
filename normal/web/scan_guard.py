from __future__ import annotations

import os
import select
import shutil
import socket
import sys
from contextlib import contextmanager
from pathlib import Path, PurePath, PureWindowsPath
from typing import Any, Iterator

from normal.source_policy import ApprovedRoots, resolve_source_path, source_paths_overlap
from normal.mounts import MountDetails, is_mount_root, is_unc_share_root, mount_details
from . import state


def client_disconnected(connection: socket.socket) -> bool:
    try:
        readable, _, _ = select.select([connection], [], [], 0)
        if not readable:
            return False
        return connection.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True


LINUX_RISKY_FSTYPES = frozenset(
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

PORTABLE_RISKY_FSTYPES = frozenset({"exfat", "fat", "fat32", "vfat"})
RISKY_MOUNT_KINDS = frozenset({"network", "removable", "optical", "ramdisk"})

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


def mount_risk_flags(details: MountDetails, *, platform: str) -> list[str]:
    flags: list[str] = []
    fstype = details.fstype.lower() if details.fstype else None
    if platform == "windows":
        risky_fstypes = PORTABLE_RISKY_FSTYPES
    else:
        risky_fstypes = LINUX_RISKY_FSTYPES
    if fstype in risky_fstypes:
        flags.append(f"mount:{fstype}")
    if details.kind in RISKY_MOUNT_KINDS and not flags:
        flags.append(f"mount:{details.kind}")
    return flags


def _mount_platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def risky_mount_flags(source: Path) -> list[str]:
    details = mount_details(source)
    return mount_risk_flags(details, platform=_mount_platform())


def _looks_like_windows_root(path: PurePath) -> bool:
    windows_path = PureWindowsPath(str(path))
    return bool(
        windows_path.drive
        and windows_path.root == "\\"
        and len(windows_path.parts) == 1
    )


def looks_like_drive_directory(path: PurePath) -> bool:
    if _looks_like_windows_root(path):
        return True
    if isinstance(path, Path) and is_mount_root(path):
        return True
    parts = path.parts
    if len(parts) == 3 and parts[1] in {"mnt", "Volumes"}:
        return True
    if len(parts) == 4 and parts[1] == "media":
        return True
    if len(parts) == 4 and parts[1:3] == ("run", "media"):
        return True
    return False


def looks_like_unc_share_root(path: PurePath) -> bool:
    return is_unc_share_root(path)


def format_storage_size(size_bytes: int) -> str:
    if size_bytes >= 1_000_000_000_000:
        return f"{size_bytes / 1_000_000_000_000:.1f} TB"
    if size_bytes >= 1_000_000_000:
        return f"{size_bytes / 1_000_000_000:.1f} GB"
    return f"{size_bytes / 1_000_000:.1f} MB"


def build_source_scan_warning(source: Path) -> dict[str, Any]:
    resolved = source.resolve()
    usage = shutil.disk_usage(resolved)
    details = mount_details(resolved)
    reasons: list[str] = []
    if looks_like_drive_directory(resolved):
        reasons.append("drive_directory")
    reasons.extend(mount_risk_flags(details, platform=_mount_platform()))
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
        "mount_fstype": details.fstype,
        "mount_target": details.target,
        "total_size_bytes": usage.total,
        "total_size_label": format_storage_size(usage.total),
    }


@contextmanager
def guarded_heavy_scan(source: Path, label: str, *, category: str = "heavy_scan") -> Iterator[None]:
    with state.HEAVY_SCAN_REGISTRY.claim(source, category, label):
        yield


@contextmanager
def guarded_mutation(source: Path, label: str, *, category: str = "mutation") -> Iterator[None]:
    with state.HEAVY_SCAN_REGISTRY.claim(source, category, label, mutating=True):
        yield
