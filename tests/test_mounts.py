from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from subprocess import CompletedProcess
from unittest.mock import patch

from normal.mounts import (
    MountDetails,
    _macos_diskutil_details,
    _macos_mount_details,
    is_junction,
    is_mount_root,
    is_unc_share_root,
    mount_details,
)


class MacOSMountTests(unittest.TestCase):
    def test_diskutil_reports_apfs_volume_boundary(self) -> None:
        payload = plistlib.dumps(
            {
                "MountPoint": "/Volumes/Media",
                "FilesystemType": "apfs",
                "BusProtocol": "PCI",
            }
        )
        result = CompletedProcess([], 0, payload, b"")

        with patch("normal.mounts._run", return_value=result):
            details = _macos_diskutil_details(Path("/Volumes/Media/Movies"))

        self.assertEqual(details, MountDetails("apfs", "/Volumes/Media", None))
        if os.name != "nt":
            self.assertTrue(is_mount_root(Path("/Volumes/Media"), details))
            self.assertFalse(is_mount_root(Path("/Volumes/Media/Movies"), details))

    def test_diskutil_marks_exfat_removable_media(self) -> None:
        payload = plistlib.dumps(
            {
                "MountPoint": "/Volumes/Camera",
                "FilesystemType": "ExFAT",
                "RemovableMedia": True,
            }
        )
        result = CompletedProcess([], 0, payload, b"")

        with patch("normal.mounts._run", return_value=result):
            details = _macos_diskutil_details(Path("/Volumes/Camera"))

        self.assertEqual(details, MountDetails("exfat", "/Volumes/Camera", "removable"))

    def test_diskutil_marks_smb_and_nfs_as_network(self) -> None:
        for fstype in ("smbfs", "nfs"):
            with self.subTest(fstype=fstype):
                payload = plistlib.dumps(
                    {"MountPoint": "/Volumes/Share", "FilesystemType": fstype}
                )
                result = CompletedProcess([], 0, payload, b"")
                with patch("normal.mounts._run", return_value=result):
                    details = _macos_diskutil_details(Path("/Volumes/Share/Movies"))
                self.assertEqual(details, MountDetails(fstype, "/Volumes/Share", "network"))

    def test_mount_p_fallback_uses_longest_boundary_and_escaped_spaces(self) -> None:
        output = (
            b"/dev/disk3s1 /Volumes/My\\040Media exfat rw 0 0\n"
            b"server:/share /Volumes/My\\040Media/NFS nfs rw 0 0\n"
        )
        result = CompletedProcess([], 0, output, b"")

        with patch("normal.mounts._run", return_value=result):
            details = _macos_mount_details(Path("/Volumes/My Media/NFS/Movies"))

        self.assertEqual(details, MountDetails("nfs", "/Volumes/My Media/NFS", None))


class WindowsMountTests(unittest.TestCase):
    def test_unc_share_root_detection(self) -> None:
        self.assertTrue(is_unc_share_root(PureWindowsPath(r"\\server\share")))
        self.assertTrue(is_unc_share_root(PureWindowsPath(r"\\?\UNC\server\share")))
        self.assertFalse(is_unc_share_root(PureWindowsPath(r"\\server\share\Movies")))

    @unittest.skipUnless(os.name == "nt", "Windows native API test")
    def test_native_volume_root_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            details = mount_details(source)
            self.assertIsNotNone(details.target)
            self.assertTrue(is_mount_root(Path(details.target), details))
            self.assertFalse(is_mount_root(source, details))

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_native_junction_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "target"
            junction = root / "junction"
            target.mkdir()
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                check=True,
                capture_output=True,
            )
            self.assertTrue(is_junction(junction))


if __name__ == "__main__":
    unittest.main()
