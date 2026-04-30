from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.apply import apply_plan


def write_plan(plan_path: Path, source_root: Path, proposed_changes: list[dict]) -> None:
    plan_path.write_text(
        json.dumps(
            {
                "source_root": str(source_root.resolve()),
                "generated_at": "2024-01-01T00:00:00+00:00",
                "ruleset_version": "1",
                "tracks": [],
                "albums": [],
                "proposed_changes": proposed_changes,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )


class ApplyTests(unittest.TestCase):
    def test_apply_plan_copies_tree_and_renames_safe_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            album_dir = source / "Artist" / "Album"
            album_dir.mkdir(parents=True)
            source_file = album_dir / "01 Old.flac"
            source_file.write_text("audio", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Artist/Album/01 Old.flac#file",
                        "change_type": "file_rename",
                        "current_value": "01 Old.flac",
                        "proposed_value": "01 New.flac",
                        "confidence": "safe",
                        "reason": "deterministic rename",
                        "path": str(source_file),
                    }
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertTrue((target / "Artist" / "Album" / "01 New.flac").exists())
            self.assertTrue((source / "Artist" / "Album" / "01 Old.flac").exists())
            self.assertEqual(len(report.applied), 1)
            self.assertTrue((target / "normal-apply-report.json").exists())

    def test_apply_plan_skips_review_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            source_file = source / "01 Old.flac"
            source_file.write_text("audio", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "01 Old.flac#file",
                        "change_type": "file_rename",
                        "current_value": "01 Old.flac",
                        "proposed_value": "01 New.flac",
                        "confidence": "review",
                        "reason": "manual review",
                        "path": str(source_file),
                    }
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.applied), 0)
            self.assertEqual(len(report.skipped), 1)
            self.assertTrue((target / "01 Old.flac").exists())

    def test_apply_plan_skips_filename_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            source_file = source / "actual.flac"
            source_file.write_text("audio", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "actual.flac#file",
                        "change_type": "file_rename",
                        "current_value": "wrong.flac",
                        "proposed_value": "renamed.flac",
                        "confidence": "safe",
                        "reason": "deterministic rename",
                        "path": str(source_file),
                    }
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.skipped), 1)
            self.assertTrue((target / "actual.flac").exists())
            self.assertFalse((target / "renamed.flac").exists())

    def test_apply_plan_rejects_nonempty_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (target / "existing.txt").write_text("keep", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(plan_path, source, [])

            with self.assertRaises(FileExistsError):
                apply_plan(source, plan_path, target, in_place=False)

    def test_apply_plan_updates_safe_tag_edit_when_metadata_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            source_file = source / "track.flac"
            source_file.write_text("audio", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "track.flac#tag:albumartist",
                        "change_type": "tag_edit",
                        "current_value": "",
                        "proposed_value": "Artist",
                        "confidence": "safe",
                        "reason": "fill tag",
                        "path": str(source_file),
                    }
                ],
            )

            fake_audio = {}

            class FakeFlac(dict):
                def get(self, key, default=None):
                    return super().get(key, default if default is not None else [])

                def save(self):
                    fake_audio["saved"] = True

            with patch("normal.apply.FLAC", return_value=FakeFlac()):
                report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.applied), 1)
            self.assertTrue(fake_audio["saved"])

    def test_apply_plan_renames_folder_after_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            album_dir = source / "Wrong Artist" / "Album"
            album_dir.mkdir(parents=True)
            source_file = album_dir / "01 Old.flac"
            source_file.write_text("audio", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Wrong Artist/Album#folder",
                        "change_type": "folder_rename",
                        "current_value": "Wrong Artist/Album",
                        "proposed_value": "Artist/1999 - Album",
                        "confidence": "safe",
                        "reason": "canonical folder rename",
                        "path": str(album_dir),
                    }
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertTrue((target / "Artist" / "1999 - Album").exists())
            self.assertFalse((target / "Wrong Artist" / "Album").exists())
            self.assertEqual(len(report.applied), 1)

    def test_apply_plan_renames_nested_folders_deepest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            movie_dir = source / "Dotted.Collection" / "Dotted.Movie.1972"
            movie_dir.mkdir(parents=True)
            (movie_dir / "movie.mkv").write_text("video", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Dotted.Collection#collection-folder",
                        "change_type": "folder_rename",
                        "current_value": "Dotted.Collection",
                        "proposed_value": "Dotted Collection",
                        "confidence": "safe",
                        "reason": "collection cleanup",
                        "path": str(source / "Dotted.Collection"),
                    },
                    {
                        "item_id": "Dotted.Collection/Dotted.Movie.1972#folder",
                        "change_type": "folder_rename",
                        "current_value": "Dotted.Collection/Dotted.Movie.1972",
                        "proposed_value": "Dotted.Collection/Dotted Movie (1972)",
                        "confidence": "safe",
                        "reason": "movie folder cleanup",
                        "path": str(movie_dir),
                    },
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.applied), 2)
            self.assertTrue((target / "Dotted Collection" / "Dotted Movie (1972)" / "movie.mkv").exists())
            self.assertFalse((target / "Dotted.Collection").exists())

    def test_apply_plan_collapses_duplicate_wrapper_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            movie_dir = source / "Full.Stop.Movie.2019" / "Full.Stop.Movie.2019"
            movie_dir.mkdir(parents=True)
            (movie_dir / "movie.mkv").write_text("video", encoding="utf-8")
            (source / "Full.Stop.Movie.2019" / "movie.nfo").write_text("metadata", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Full.Stop.Movie.2019/Full.Stop.Movie.2019#folder",
                        "change_type": "folder_rename",
                        "current_value": "Full.Stop.Movie.2019/Full.Stop.Movie.2019",
                        "proposed_value": "Full Stop Movie (2019)",
                        "confidence": "safe",
                        "reason": "duplicate wrapper collapse",
                        "path": str(movie_dir),
                    },
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.applied), 1)
            self.assertTrue((target / "Full Stop Movie (2019)" / "movie.mkv").exists())
            self.assertTrue((target / "Full Stop Movie (2019)" / "movie.nfo").exists())
            self.assertFalse((target / "Full.Stop.Movie.2019").exists())

    def test_apply_plan_moves_loose_file_into_new_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            source_file = source / "Loose.Movie.2019.mkv"
            source_file.write_text("video", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Loose.Movie.2019.mkv#file-move",
                        "change_type": "file_move",
                        "current_value": "Loose.Movie.2019.mkv",
                        "proposed_value": "Loose Movie (2019)/Loose Movie (2019).mkv",
                        "confidence": "safe",
                        "reason": "loose root file",
                        "path": str(source_file),
                    },
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.applied), 1)
            self.assertTrue((target / "Loose Movie (2019)" / "Loose Movie (2019).mkv").exists())
            self.assertFalse((target / "Loose.Movie.2019.mkv").exists())

    def test_apply_plan_moves_loose_movie_sidecars_into_new_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            source_file = source / "Loose.Movie.2019.mkv"
            source_file.write_text("video", encoding="utf-8")
            (source / "Loose.Movie.2019.nfo").write_text("metadata", encoding="utf-8")
            (source / "Loose.Movie.2019-poster.jpg").write_text("poster", encoding="utf-8")
            (source / "Loose.Movie.2019.eng.srt").write_text("subtitle", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Loose.Movie.2019.mkv#file-move",
                        "change_type": "file_move",
                        "current_value": "Loose.Movie.2019.mkv",
                        "proposed_value": "Loose Movie (2019)/Loose Movie (2019).mkv",
                        "confidence": "safe",
                        "reason": "loose root file",
                        "path": str(source_file),
                    },
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.applied), 1)
            self.assertEqual(report.applied[0].message, "File moved with 3 sidecars.")
            movie_folder = target / "Loose Movie (2019)"
            self.assertTrue((movie_folder / "Loose Movie (2019).mkv").exists())
            self.assertTrue((movie_folder / "Loose Movie (2019).nfo").exists())
            self.assertTrue((movie_folder / "Loose Movie (2019)-poster.jpg").exists())
            self.assertTrue((movie_folder / "Loose Movie (2019).eng.srt").exists())
            self.assertFalse((target / "Loose.Movie.2019.nfo").exists())
            self.assertFalse((target / "Loose.Movie.2019-poster.jpg").exists())
            self.assertFalse((target / "Loose.Movie.2019.eng.srt").exists())

    def test_apply_plan_renames_movie_sidecars_with_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            movie_dir = source / "Movie"
            movie_dir.mkdir(parents=True)
            source_file = movie_dir / "Old.Movie.2019.mkv"
            source_file.write_text("video", encoding="utf-8")
            (movie_dir / "Old.Movie.2019.nfo").write_text("metadata", encoding="utf-8")
            (movie_dir / "Old.Movie.2019-backdrop.jpg").write_text("backdrop", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Movie/Old.Movie.2019.mkv#file",
                        "change_type": "file_rename",
                        "current_value": "Old.Movie.2019.mkv",
                        "proposed_value": "Old Movie (2019).mkv",
                        "confidence": "safe",
                        "reason": "movie filename",
                        "path": str(source_file),
                    },
                ],
            )

            report = apply_plan(source, plan_path, target, in_place=False)

            self.assertEqual(len(report.applied), 1)
            self.assertEqual(report.applied[0].message, "File renamed with 2 sidecars.")
            self.assertTrue((target / "Movie" / "Old Movie (2019).mkv").exists())
            self.assertTrue((target / "Movie" / "Old Movie (2019).nfo").exists())
            self.assertTrue((target / "Movie" / "Old Movie (2019)-backdrop.jpg").exists())
            self.assertFalse((target / "Movie" / "Old.Movie.2019.nfo").exists())
            self.assertFalse((target / "Movie" / "Old.Movie.2019-backdrop.jpg").exists())

    def test_apply_plan_skips_folder_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            album_dir = source / "Wrong Artist" / "Album"
            album_dir.mkdir(parents=True)
            (album_dir / "01 Old.flac").write_text("audio", encoding="utf-8")
            plan_path = root / "plan.json"
            write_plan(
                plan_path,
                source,
                [
                    {
                        "item_id": "Wrong Artist/Album#folder",
                        "change_type": "folder_rename",
                        "current_value": "Wrong Artist/Album",
                        "proposed_value": "Artist/1999 - Album",
                        "confidence": "safe",
                        "reason": "canonical folder rename",
                        "path": str(album_dir),
                    }
                ],
            )

            target_collision = target / "Artist" / "1999 - Album"
            target_collision.mkdir(parents=True)
            (target_collision / "existing.flac").write_text("audio", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                apply_plan(source, plan_path, target, in_place=False)


if __name__ == "__main__":
    unittest.main()
