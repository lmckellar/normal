from __future__ import annotations

import ctypes
import json
import os
import plistlib
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


@dataclass(frozen=True, slots=True)
class MountDetails:
    fstype: str | None = None
    target: str | None = None
    kind: str | None = None


def _run(command: list[str]) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _macos_diskutil_details(source: Path) -> MountDetails | None:
    boundary = _macos_mount_details(source)
    query_target = boundary.target if boundary and boundary.target else str(source)
    result = _run(["diskutil", "info", "-plist", query_target])
    if result is None or result.returncode != 0 or not result.stdout:
        return boundary
    try:
        info = plistlib.loads(result.stdout)
    except (plistlib.InvalidFileException, ValueError):
        return boundary

    target = boundary.target if boundary else info.get("MountPoint")
    fstype = info.get("FilesystemType") or info.get("Type (Bundle)")
    protocol = str(info.get("BusProtocol") or "").lower()
    removable = bool(info.get("RemovableMedia") or info.get("Ejectable"))
    network = protocol in {"smb", "nfs"} or str(fstype or "").lower() in {"smbfs", "nfs"}
    kind = "network" if network else "removable" if removable else None
    return MountDetails(
        fstype=str(fstype).lower() if fstype else None,
        target=str(target) if target else None,
        kind=kind,
    )


def _macos_mount_details(source: Path) -> MountDetails | None:
    result = _run(["mount", "-p"])
    if result is None or result.returncode != 0:
        return None
    best: MountDetails | None = None
    best_parts = -1
    for raw_line in result.stdout.decode(errors="replace").splitlines():
        fields = raw_line.replace("\\040", "\0").split()
        if len(fields) < 3:
            continue
        target = fields[1].replace("\0", " ")
        target_path = Path(target)
        try:
            source.relative_to(target_path)
        except ValueError:
            continue
        if len(target_path.parts) > best_parts:
            best_parts = len(target_path.parts)
            best = MountDetails(fstype=fields[2].lower(), target=target)
    return best


def _findmnt_mount_details(source: Path) -> MountDetails | None:
    result = _run(["findmnt", "--json", "-T", str(source), "-o", "TARGET,FSTYPE"])
    if result is None or result.returncode != 0 or not result.stdout.strip():
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
    return MountDetails(target=target, fstype=fstype.lower() if fstype else None)


def _unescape_proc_mount_field(field: str) -> str:
    return (
        field.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _proc_mounts_mount_details(source: Path) -> MountDetails | None:
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    best: MountDetails | None = None
    best_parts = -1
    for line in lines:
        fields = line.split(" ")
        if len(fields) < 3:
            continue
        target = _unescape_proc_mount_field(fields[1])
        target_path = Path(target)
        try:
            source.relative_to(target_path)
        except ValueError:
            continue
        if len(target_path.parts) > best_parts:
            best_parts = len(target_path.parts)
            best = MountDetails(fstype=fields[2].lower(), target=target)
    return best


def _windows_share_root(path: str) -> str | None:
    windows_path = PureWindowsPath(path)
    drive = windows_path.drive
    if drive.lower().startswith("\\\\?\\unc\\"):
        return "\\\\" + drive[8:]
    if drive.startswith("\\\\"):
        return drive
    return None


def _windows_details(source: Path) -> MountDetails | None:
    path = str(source)
    share_root = _windows_share_root(path)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetVolumePathNameW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.GetVolumePathNameW.restype = wintypes.BOOL
    kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetDriveTypeW.restype = wintypes.UINT
    kernel32.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    kernel32.GetVolumeInformationW.restype = wintypes.BOOL

    volume_buffer = ctypes.create_unicode_buffer(32768)
    target = share_root
    if kernel32.GetVolumePathNameW(path, volume_buffer, len(volume_buffer)):
        target = volume_buffer.value

    root = target or path
    drive_type = kernel32.GetDriveTypeW(root)
    kinds = {2: "removable", 4: "network", 5: "optical", 6: "ramdisk"}
    kind = kinds.get(drive_type)

    fs_buffer = ctypes.create_unicode_buffer(256)
    volume_name = ctypes.create_unicode_buffer(256)
    serial = wintypes.DWORD()
    max_component = wintypes.DWORD()
    flags = wintypes.DWORD()
    fstype = None
    if kernel32.GetVolumeInformationW(
        root,
        volume_name,
        len(volume_name),
        ctypes.byref(serial),
        ctypes.byref(max_component),
        ctypes.byref(flags),
        fs_buffer,
        len(fs_buffer),
    ):
        fstype = fs_buffer.value.lower() or None
    return MountDetails(fstype=fstype, target=target, kind=kind)


def mount_details(source: Path) -> MountDetails:
    resolved = source.resolve()
    if sys.platform == "darwin":
        return _macos_diskutil_details(resolved) or MountDetails()
    if os.name == "nt":
        return _windows_details(resolved) or MountDetails()
    if sys.platform.startswith("linux"):
        return _findmnt_mount_details(resolved) or _proc_mounts_mount_details(resolved) or MountDetails()
    return MountDetails()


def is_mount_root(path: Path, details: MountDetails | None = None) -> bool:
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        return True
    details = details or mount_details(resolved)
    if details.target:
        try:
            return os.path.normcase(os.path.normpath(str(resolved))) == os.path.normcase(
                os.path.normpath(details.target)
            )
        except OSError:
            pass
    return os.path.ismount(resolved)


def is_unc_share_root(path: Path | PureWindowsPath) -> bool:
    windows_path = PureWindowsPath(str(path))
    share_root = _windows_share_root(str(windows_path))
    return bool(
        share_root
        and windows_path.root == "\\"
        and len(windows_path.parts) == 1
    )


def is_blocked_reparse_point(path: Path) -> bool:
    if hasattr(os.path, "isjunction") and os.path.isjunction(path):
        return True
    if os.name != "nt":
        return False
    get_attributes = ctypes.WinDLL(
        "kernel32", use_last_error=True
    ).GetFileAttributesW
    get_attributes.argtypes = [wintypes.LPCWSTR]
    get_attributes.restype = wintypes.DWORD
    attributes = get_attributes(str(path))
    invalid = 0xFFFFFFFF
    reparse_point = 0x400
    return attributes != invalid and bool(attributes & reparse_point) and not path.is_symlink()
