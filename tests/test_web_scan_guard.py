from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from normal.web.scan_guard import (
    SourceMountDetails,
    build_source_scan_warning,
    client_disconnected,
    format_storage_size,
    guarded_heavy_scan,
    looks_like_drive_directory,
    resolve_source_path,
    risky_mount_flags,
    source_mount_details,
    source_paths_overlap,
)
from normal.web.state import HeavyScanRegistry, RequestConflictError


class WebScanGuardTests(unittest.TestCase):
    def test_resolve_source_path_requires_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "Movies"
            source.mkdir()
            file_path = source / "movie.txt"
            file_path.write_text("movie", encoding="utf-8")

            self.assertEqual(resolve_source_path(source), source.resolve())
            self.assertEqual(resolve_source_path(None, default_source=source), source.resolve())
            with self.assertRaises(FileNotFoundError):
                resolve_source_path(source / "missing")
            with self.assertRaises(NotADirectoryError):
                resolve_source_path(file_path)

    def test_source_paths_overlap_checks_both_directions(self) -> None:
        self.assertTrue(source_paths_overlap(Path("/srv/media"), Path("/srv/media/movies")))
        self.assertTrue(source_paths_overlap(Path("/srv/media/movies"), Path("/srv/media")))
        self.assertFalse(source_paths_overlap(Path("/srv/media"), Path("/srv/music")))

    def test_client_disconnected_detects_open_and_closed_socket(self) -> None:
        left, right = socket.socketpair()
        try:
            self.assertFalse(client_disconnected(left))
            right.close()
            self.assertTrue(client_disconnected(left))
        finally:
            left.close()

    def test_source_mount_details_parses_findmnt_output(self) -> None:
        completed = CompletedProcess(args=[], returncode=0, stdout="/mnt/media ntfs3\n", stderr="")

        with patch("normal.web.scan_guard.subprocess.run", return_value=completed):
            details = source_mount_details(Path("/mnt/media/Movies"))

        self.assertEqual(details, SourceMountDetails(fstype="ntfs3", target="/mnt/media"))

    def test_risky_mount_flags_marks_ntfs_variants(self) -> None:
        with patch("normal.web.scan_guard.source_mount_details", return_value=SourceMountDetails(fstype="fuseblk", target="/mnt/media")):
            flags = risky_mount_flags(Path("/mnt/media/Movies"))

        self.assertEqual(flags, ["mount:fuseblk"])

    def test_build_source_scan_warning_combines_drive_and_mount_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            usage = type("Usage", (), {"total": 4_500_000_000_000})()

            with patch("normal.web.scan_guard.shutil.disk_usage", return_value=usage):
                with patch("normal.web.scan_guard.looks_like_drive_directory", return_value=True):
                    with patch(
                        "normal.web.scan_guard.source_mount_details",
                        return_value=SourceMountDetails(fstype="fuseblk", target="/mnt/media"),
                    ):
                        payload = build_source_scan_warning(source)

        self.assertTrue(payload["warn"])
        self.assertEqual(payload["reason"], "drive_directory")
        self.assertEqual(payload["reasons"], ["drive_directory", "mount:fuseblk"])
        self.assertIn("drive directory", payload["message"])
        self.assertIn("higher risk", payload["message"])
        self.assertEqual(payload["total_size_label"], "4.5 TB")

    def test_guarded_heavy_scan_rejects_same_source_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            registry = HeavyScanRegistry()

            with patch("normal.web.scan_guard.state.HEAVY_SCAN_REGISTRY", registry):
                with guarded_heavy_scan(source, "Movie profile scan"):
                    with self.assertRaises(RequestConflictError):
                        with guarded_heavy_scan(source, "Movie canonical lists"):
                            self.fail("overlapping heavy scan should not be allowed")

    def test_looks_like_drive_directory_covers_common_mount_roots(self) -> None:
        self.assertTrue(looks_like_drive_directory(Path("/mnt/media_storage")))
        self.assertTrue(looks_like_drive_directory(Path("/media/lachlan/Drive")))
        self.assertTrue(looks_like_drive_directory(Path("/Volumes/Media")))
        self.assertFalse(looks_like_drive_directory(Path("/mnt/media_storage/Movies")))

    def test_format_storage_size_uses_expected_units(self) -> None:
        self.assertEqual(format_storage_size(4_500_000_000_000), "4.5 TB")
        self.assertEqual(format_storage_size(4_500_000_000), "4.5 GB")
        self.assertEqual(format_storage_size(4_500_000), "4.5 MB")


if __name__ == "__main__":
    unittest.main()
