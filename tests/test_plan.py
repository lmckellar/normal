from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.models import AlbumReport, ProposedChange, TrackReport, WarningItem
from normal.plan import build_plan, deduplicate_artist_case, plan_album_folder_rename, plan_filename_rename


class PlanTests(unittest.TestCase):
    def test_build_plan_derives_albumartist_and_filename_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            track_path = source / "Artist" / "Album" / "1  Song.flac"
            track_path.parent.mkdir(parents=True)
            track_path.touch()

            fake_report_tracks = [
                TrackReport(
                    track_id="Artist/Album/1  Song.flac",
                    path=str(track_path),
                    tags={
                        "artist": "Artist",
                        "album": "Album",
                        "title": "Song",
                        "tracknumber": "1",
                        "date": "2024",
                        "genre": "Rock",
                    },
                    issues=[WarningItem(code="missing_tag", message="Missing tag: albumartist", path=str(track_path))],
                )
            ]
            fake_report_albums = [
                AlbumReport(album_id="Artist::Album", path=str(track_path.parent), track_count=1, warnings=[])
            ]

            with patch("normal.plan.analyze_library") as analyze_library:
                analyze_library.return_value.source_root = str(source)
                analyze_library.return_value.generated_at = "2024-01-01T00:00:00+00:00"
                analyze_library.return_value.ruleset_version = "1"
                analyze_library.return_value.tracks = fake_report_tracks
                analyze_library.return_value.albums = fake_report_albums
                analyze_library.return_value.warnings = []

                plan = build_plan(source)

            item_ids = {change.item_id for change in plan.proposed_changes}
            self.assertIn("Artist/Album/1  Song.flac#tag:albumartist", item_ids)
            self.assertIn("Artist/Album/1  Song.flac#file", item_ids)
            filename_change = next(change for change in plan.proposed_changes if change.change_type == "file_rename")
            self.assertEqual(filename_change.proposed_value, "01 Song.flac")
            self.assertEqual(filename_change.confidence, "safe")

    def test_plan_filename_rename_is_safe_when_track_is_complete(self) -> None:
        track = TrackReport(
            track_id="Artist/Album/01 Old.flac",
            path="/tmp/Artist/Album/01 Old.flac",
            tags={
                "artist": "Artist",
                "albumartist": "Artist",
                "album": "Album",
                "title": "Song Name",
                "tracknumber": "1/12",
                "date": "2024",
                "genre": "Rock",
            },
            issues=[],
        )

        change = plan_filename_rename(track)

        self.assertIsNotNone(change)
        assert change is not None
        self.assertEqual(change.proposed_value, "01 Song Name.flac")
        self.assertEqual(change.confidence, "safe")

    def test_build_plan_carries_scan_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)

            with patch("normal.plan.analyze_library") as analyze_library:
                analyze_library.return_value.source_root = str(source)
                analyze_library.return_value.generated_at = "2024-01-01T00:00:00+00:00"
                analyze_library.return_value.ruleset_version = "1"
                analyze_library.return_value.tracks = []
                analyze_library.return_value.albums = []
                analyze_library.return_value.warnings = [
                    WarningItem(code="no_flac_files", message="No FLAC files were found.", path=str(source))
                ]

                plan = build_plan(source)

            self.assertEqual(plan.warnings[0].code, "no_flac_files")
            self.assertEqual(plan.proposed_changes, [])

    def test_plan_album_folder_rename_is_safe_with_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            album_dir = source / "Wrong Artist" / "Album"
            track_path = album_dir / "01 Song.flac"
            album_dir.mkdir(parents=True)
            track = TrackReport(
                track_id="Wrong Artist/Album/01 Song.flac",
                path=str(track_path),
                tags={
                    "artist": "Artist",
                    "albumartist": "Artist",
                    "album": "Album",
                    "title": "Song",
                    "tracknumber": "1",
                    "date": "1999-02-01",
                    "genre": "Rock",
                },
                issues=[],
            )
            album = AlbumReport(album_id="Artist::Album", path=str(album_dir), track_count=1, warnings=[])

            change, warning = plan_album_folder_rename(album, [track], source)

            self.assertIsNotNone(change)
            assert change is not None
            self.assertEqual(change.change_type, "folder_rename")
            self.assertEqual(change.proposed_value, "Artist/1999 - Album")
            self.assertEqual(change.confidence, "safe")
            self.assertIsNone(warning)

    def test_plan_album_folder_rename_is_review_without_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            album_dir = source / "Artist" / "Old Name"
            track_path = album_dir / "01 Song.flac"
            album_dir.mkdir(parents=True)
            track = TrackReport(
                track_id="Artist/Old Name/01 Song.flac",
                path=str(track_path),
                tags={
                    "artist": "Artist",
                    "albumartist": "Artist",
                    "album": "Album",
                    "title": "Song",
                    "tracknumber": "1",
                    "genre": "Rock",
                },
                issues=[],
            )
            album = AlbumReport(album_id="Artist::Album", path=str(album_dir), track_count=1, warnings=[])

            change, warning = plan_album_folder_rename(album, [track], source)

            self.assertIsNotNone(change)
            assert change is not None
            self.assertEqual(change.proposed_value, "Artist/Album")
            self.assertEqual(change.confidence, "review")
            self.assertIsNotNone(warning)
            assert warning is not None
            self.assertEqual(warning.code, "album_missing_year")


    def test_deduplicate_artist_case_keeps_safe_when_canonical_is_established(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            # Established canonical: Alt-J exists on disk with an album subdir inside it
            canonical_dir = source / "Alt-J"
            (canonical_dir / "2014 - This Is All Yours").mkdir(parents=True)

            # Two pending folder_renames pointing to the non-canonical 'alt-J' form
            changes = [
                ProposedChange(
                    item_id="alt-J - An Awesome Wave#folder",
                    change_type="folder_rename",
                    current_value="alt-J - An Awesome Wave",
                    proposed_value="alt-J/2012 - An Awesome Wave",
                    confidence="safe",
                    reason="original reason",
                    path=str(source / "alt-J - An Awesome Wave"),
                ),
                ProposedChange(
                    item_id="alt-J - RELAXER#folder",
                    change_type="folder_rename",
                    current_value="alt-J - RELAXER",
                    proposed_value="alt-J/2017 - RELAXER",
                    confidence="safe",
                    reason="original reason",
                    path=str(source / "alt-J - RELAXER"),
                ),
            ]

            updated, warnings = deduplicate_artist_case(changes, [], source)

            folder_renames = [c for c in updated if c.change_type == "folder_rename"]
            self.assertEqual(len(folder_renames), 2)
            for change in folder_renames:
                self.assertTrue(change.proposed_value.startswith("Alt-J/"), change.proposed_value)
                self.assertEqual(change.confidence, "safe")
            self.assertEqual(len(warnings), 1)
            self.assertEqual(warnings[0].code, "artist_name_case_conflict")

    def test_deduplicate_artist_case_keeps_review_when_canonical_is_not_established(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            # Alt-J exists on disk but contains only files (no album subdirs) —
            # not established, so the collision remains ambiguous.
            alt_j_dir = source / "Alt-J"
            alt_j_dir.mkdir()
            (alt_j_dir / "cover.jpg").touch()

            changes = [
                ProposedChange(
                    item_id="alt-J - An Awesome Wave#folder",
                    change_type="folder_rename",
                    current_value="alt-J - An Awesome Wave",
                    proposed_value="alt-J/2012 - An Awesome Wave",
                    confidence="safe",
                    reason="original reason",
                    path=str(source / "alt-J - An Awesome Wave"),
                ),
            ]

            updated, warnings = deduplicate_artist_case(changes, [], source)

            folder_renames = [c for c in updated if c.change_type == "folder_rename"]
            self.assertEqual(len(folder_renames), 1)
            self.assertEqual(folder_renames[0].confidence, "review")
            self.assertTrue(folder_renames[0].proposed_value.startswith("Alt-J/"))


if __name__ == "__main__":
    unittest.main()
