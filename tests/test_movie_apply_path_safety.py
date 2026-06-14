from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.models import ProposedChange
from normal.movie_apply import apply_changes_in_place, copy_source_tree
from normal.source_policy import ApprovedRoots, validate_candidate_for_mutation


ESCAPING_DESTINATIONS = ["/tmp/pwned", "../../pwned", "Good Movie (2024)/../../pwned"]
UNSAFE_BASENAMES = ESCAPING_DESTINATIONS + ["..", "."]


class MovieApplyPathSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.source = Path(self._tmp.name)

    def _change(self, change_type: str, current_value: str, proposed_value: str, path: Path) -> ProposedChange:
        return ProposedChange(
            item_id="x",
            change_type=change_type,
            current_value=current_value,
            proposed_value=proposed_value,
            confidence="safe",
            reason="",
            path=str(path),
        )

    def test_file_rename_rejects_unsafe_basenames(self) -> None:
        for bad in UNSAFE_BASENAMES:
            with self.subTest(bad=bad):
                movie = self.source / "Movie (2024).mkv"
                movie.write_text("video", encoding="utf-8")
                change = self._change("file_rename", "Movie (2024).mkv", bad, movie)
                report = apply_changes_in_place(self.source, [change])
                self.assertEqual(report.applied, [])
                self.assertEqual(len(report.failed), 1)
                self.assertTrue(movie.exists())
                movie.unlink()

    def test_file_move_rejects_escaping_destinations(self) -> None:
        for bad in ESCAPING_DESTINATIONS:
            with self.subTest(bad=bad):
                movie = self.source / "Movie (2024).mkv"
                movie.write_text("video", encoding="utf-8")
                change = self._change("file_move", "Movie (2024).mkv", bad, movie)
                report = apply_changes_in_place(self.source, [change])
                self.assertEqual(report.applied, [])
                self.assertEqual(len(report.failed), 1)
                self.assertTrue(movie.exists())
                movie.unlink()

    def test_folder_rename_rejects_escaping_destinations(self) -> None:
        for bad in ESCAPING_DESTINATIONS:
            with self.subTest(bad=bad):
                folder = self.source / "Movie (2024)"
                folder.mkdir()
                (folder / "Movie (2024).mkv").write_text("video", encoding="utf-8")
                change = self._change("folder_rename", "Movie (2024)", bad, folder)
                report = apply_changes_in_place(self.source, [change])
                self.assertEqual(report.applied, [])
                self.assertEqual(len(report.failed), 1)
                self.assertTrue(folder.is_dir())
                for entry in folder.iterdir():
                    entry.unlink()
                folder.rmdir()

    def test_folder_merge_rejects_escaping_destinations(self) -> None:
        for bad in ESCAPING_DESTINATIONS:
            with self.subTest(bad=bad):
                folder = self.source / "Movie (2024)"
                folder.mkdir()
                (folder / "Movie (2024).mkv").write_text("video", encoding="utf-8")
                change = self._change("folder_merge", "Movie (2024)", bad, folder)
                report = apply_changes_in_place(self.source, [change])
                self.assertEqual(report.applied, [])
                self.assertEqual(len(report.failed), 1)
                self.assertTrue(folder.is_dir())
                for entry in folder.iterdir():
                    entry.unlink()
                folder.rmdir()

    def test_apply_rejects_stale_symlink_candidate(self) -> None:
        movie = self.source / "Movie (2024).mkv"
        target = self.source / "Real Movie (2024).mkv"
        target.write_text("video", encoding="utf-8")
        movie.symlink_to(target)
        change = self._change("file_delete", movie.name, "", movie)

        report = apply_changes_in_place(self.source, [change])

        self.assertEqual(report.applied, [])
        self.assertEqual(len(report.failed), 1)
        self.assertTrue(movie.is_symlink())
        self.assertTrue(target.exists())

    def test_folder_rename_revalidates_source_and_target_with_approved_roots(self) -> None:
        folder = self.source / "Movie"
        folder.mkdir()
        target = self.source / "Movie (2024)"
        change = self._change("folder_rename", "Movie", "Movie (2024)", folder)
        approved_roots = ApprovedRoots.from_paths([self.source])

        with patch(
            "normal.movie_apply.validate_candidate_for_mutation",
            wraps=validate_candidate_for_mutation,
        ) as validate:
            report = apply_changes_in_place(self.source, [change], approved_roots)

        self.assertEqual(len(report.applied), 1)
        validate.assert_any_call(folder, self.source.resolve(), approved_roots)
        validate.assert_any_call(target, self.source.resolve(), approved_roots)

    def test_folder_merge_revalidates_each_entry_and_target_with_approved_roots(self) -> None:
        folder = self.source / "Movie"
        folder.mkdir()
        entry = folder / "Movie.mkv"
        entry.write_text("video", encoding="utf-8")
        target_folder = self.source / "Movie (2024)"
        target_folder.mkdir()
        target = target_folder / entry.name
        change = self._change("folder_merge", "Movie", "Movie (2024)", folder)
        approved_roots = ApprovedRoots.from_paths([self.source])

        with patch(
            "normal.movie_apply.validate_candidate_for_mutation",
            wraps=validate_candidate_for_mutation,
        ) as validate:
            report = apply_changes_in_place(self.source, [change], approved_roots)

        self.assertEqual(len(report.applied), 1)
        validate.assert_any_call(entry, self.source.resolve(), approved_roots)
        validate.assert_any_call(target, self.source.resolve(), approved_roots)

    def test_folder_delete_revalidates_target_with_approved_roots(self) -> None:
        folder = self.source / "Movie"
        folder.mkdir()
        change = self._change("folder_delete", "Movie", "", folder)
        approved_roots = ApprovedRoots.from_paths([self.source])

        with patch(
            "normal.movie_apply.validate_candidate_for_mutation",
            wraps=validate_candidate_for_mutation,
        ) as validate:
            report = apply_changes_in_place(self.source, [change], approved_roots)

        self.assertEqual(len(report.applied), 1)
        validate.assert_any_call(folder, self.source.resolve(), approved_roots)


class CopySourceTreeSymlinkTests(unittest.TestCase):
    def test_symlinks_are_skipped_and_reported_without_dereferencing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            dest = root / "target"
            source.mkdir()

            real = source / "Movie (2024).mkv"
            real.write_text("video", encoding="utf-8")

            outside = root / "outside.mkv"
            outside.write_text("secret", encoding="utf-8")

            (source / "link_inside.mkv").symlink_to(real)
            (source / "link_outside.mkv").symlink_to(outside)
            (source / "link_dir").symlink_to(source)
            (source / "link_broken.mkv").symlink_to(source / "missing.mkv")

            skipped = copy_source_tree(source.resolve(), dest)

            self.assertTrue((dest / "Movie (2024).mkv").exists())
            for name in ("link_inside.mkv", "link_outside.mkv", "link_dir", "link_broken.mkv"):
                self.assertFalse((dest / name).exists())
                self.assertFalse((dest / name).is_symlink())

            skipped_names = {Path(result.path).name for result in skipped}
            self.assertEqual(
                skipped_names,
                {"link_inside.mkv", "link_outside.mkv", "link_dir", "link_broken.mkv"},
            )
            self.assertTrue(all(result.change_type == "symlink" for result in skipped))
            outside_result = next(r for r in skipped if Path(r.path).name == "link_outside.mkv")
            self.assertIn("outside source root", outside_result.message)


if __name__ == "__main__":
    unittest.main()
