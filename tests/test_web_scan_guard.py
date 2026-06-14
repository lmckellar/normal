from __future__ import annotations

import os
import socket
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from pathlib import PureWindowsPath
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
    looks_like_unc_share_root,
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
        stdout = '{"filesystems": [{"target": "/mnt/My Media", "fstype": "NTFS3"}]}\n'
        completed = CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")

        with patch("normal.web.scan_guard.subprocess.run", return_value=completed):
            details = source_mount_details(Path("/mnt/My Media/Movies"))

        self.assertEqual(details, SourceMountDetails(fstype="ntfs3", target="/mnt/My Media"))

    def test_source_mount_details_falls_back_to_proc_mounts(self) -> None:
        proc_mounts = "//srv/share /mnt/My\\040Share cifs rw 0 0\n/dev/sda1 / ext4 rw 0 0\n"

        with patch("normal.web.scan_guard.subprocess.run", side_effect=OSError):
            with patch("normal.web.scan_guard.Path.read_text", return_value=proc_mounts):
                details = source_mount_details(Path("/mnt/My Share/Movies"))

        self.assertEqual(details, SourceMountDetails(fstype="cifs", target="/mnt/My Share"))

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
        self.assertEqual(
            payload["message"],
            "This source looks like a filesystem boundary or translated/network/removable filesystem. "
            "Heavy recursive scans may be slow, incomplete, or surprising. "
            "Choose a specific movie-library folder below this root, or restart with an explicit override.",
        )
        self.assertEqual(payload["total_size_label"], "4.5 TB")

    def test_build_source_scan_warning_uses_unc_share_root_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            usage = type("Usage", (), {"total": 4_500_000_000_000})()

            with patch("normal.web.scan_guard.shutil.disk_usage", return_value=usage):
                with patch("normal.web.scan_guard.looks_like_drive_directory", return_value=True):
                    with patch("normal.web.scan_guard.looks_like_unc_share_root", return_value=True):
                        payload = build_source_scan_warning(source)

        self.assertEqual(
            payload["message"],
            "You selected a network share root. "
            "Normal will not recursively scan or mutate a whole share by default. "
            "Choose a specific library folder inside the share.",
        )

    def test_guarded_heavy_scan_rejects_same_source_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            registry = HeavyScanRegistry()

            with patch("normal.web.scan_guard.state.HEAVY_SCAN_REGISTRY", registry):
                with guarded_heavy_scan(source, "Movie profile scan"):
                    with self.assertRaises(RequestConflictError):
                        with guarded_heavy_scan(source, "Movie canonical lists"):
                            self.fail("overlapping heavy scan should not be allowed")

    def test_heavy_scan_registry_rejects_nested_child_of_active_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir) / "lib"
            (parent / "Sub").mkdir(parents=True)
            registry = HeavyScanRegistry()

            with registry.claim(parent, "heavy_scan", "Parent scan"):
                with self.assertRaises(RequestConflictError):
                    with registry.claim(parent / "Sub", "heavy_scan", "Child scan"):
                        self.fail("scan of a child of an active scan should not be allowed")

    def test_heavy_scan_registry_allows_non_overlapping_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "lib"
            (base / "A").mkdir(parents=True)
            (base / "B").mkdir()
            registry = HeavyScanRegistry()

            with registry.claim(base / "A", "heavy_scan", "Scan A"):
                with registry.claim(base / "B", "heavy_scan", "Scan B"):
                    pass

    def test_looks_like_drive_directory_covers_common_mount_roots(self) -> None:
        self.assertTrue(looks_like_drive_directory(Path("/mnt/media_storage")))
        self.assertTrue(looks_like_drive_directory(Path("/media/lachlan/Drive")))
        self.assertTrue(looks_like_drive_directory(Path("/Volumes/Media")))
        self.assertFalse(looks_like_drive_directory(Path("/mnt/media_storage/Movies")))

    def test_looks_like_unc_share_root_only_matches_share_root(self) -> None:
        self.assertTrue(looks_like_unc_share_root(PureWindowsPath(r"\\server\share")))
        self.assertFalse(looks_like_unc_share_root(PureWindowsPath(r"\\server\share\Movies")))
        self.assertFalse(looks_like_unc_share_root(PureWindowsPath(r"C:\\")))

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
