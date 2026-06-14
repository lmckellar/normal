from __future__ import annotations

import os
import socket
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from normal.web.scan_guard import (
    ApprovedRoots,
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


class ApprovedRootsTests(unittest.TestCase):
    @contextmanager
    def _library(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            movies = base / "Movies"
            (movies / "sub").mkdir(parents=True)
            (base / "Music").mkdir()
            yield base, movies

    def test_from_paths_resolves_and_dedupes(self) -> None:
        with self._library() as (base, movies):
            approved = ApprovedRoots.from_paths([movies, movies, str(movies) + "/"])
            self.assertEqual(approved.roots, (movies,))

    def test_equal_and_under_root_pass(self) -> None:
        with self._library() as (base, movies):
            approved = ApprovedRoots.from_paths([movies])
            self.assertEqual(approved.resolve_approved(str(movies)), movies)
            self.assertEqual(approved.resolve_approved(str(movies / "sub")), movies / "sub")

    def test_multiple_roots_are_each_honored(self) -> None:
        with self._library() as (base, movies):
            other = base / "Music"
            approved = ApprovedRoots.from_paths([movies, other])
            self.assertEqual(approved.resolve_approved(str(other)), other)

    def test_sibling_and_parent_are_rejected(self) -> None:
        with self._library() as (base, movies):
            approved = ApprovedRoots.from_paths([movies])
            with self.assertRaises(PermissionError):
                approved.resolve_approved(str(base / "Music"))
            with self.assertRaises(PermissionError):
                approved.resolve_approved(str(base))

    def test_empty_roots_reject_everything(self) -> None:
        with self._library() as (base, movies):
            with self.assertRaises(PermissionError):
                ApprovedRoots().resolve_approved(str(movies))

    def test_approval_survives_trailing_slash_and_relative_segments(self) -> None:
        with self._library() as (base, movies):
            approved = ApprovedRoots.from_paths([movies])
            self.assertEqual(approved.resolve_approved(str(movies) + "/"), movies)
            self.assertEqual(approved.resolve_approved(str(movies / "sub" / "..")), movies)

    def test_approval_survives_home_expansion(self) -> None:
        with self._library() as (base, movies):
            with patch.dict(os.environ, {"HOME": str(base)}):
                approved = ApprovedRoots.from_paths([Path("~/Movies")])
                self.assertEqual(approved.roots, (movies,))
                self.assertEqual(approved.resolve_approved("~/Movies"), movies)

    def test_approval_survives_symlinked_source(self) -> None:
        with self._library() as (base, movies):
            link = base / "MoviesLink"
            link.symlink_to(movies)
            approved = ApprovedRoots.from_paths([movies])
            self.assertEqual(approved.resolve_approved(str(link)), movies)


if __name__ == "__main__":
    unittest.main()
