from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.models import ProposedChange
from normal.movie_apply import apply_changes_in_place


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


if __name__ == "__main__":
    unittest.main()
