from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.scan import TrackMetadata, analyze_library
from normal.models import WarningItem


class ScanAnalysisTests(unittest.TestCase):
    def test_analyze_library_groups_tracks_into_album_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            album_dir = source / "Artist" / "2024 - Album"
            album_dir.mkdir(parents=True)
            track_one = album_dir / "01 First.flac"
            track_two = album_dir / "02 Second.flac"
            track_one.touch()
            track_two.touch()

            fake_metadata = {
                track_one: TrackMetadata(
                    path=track_one,
                    tags={
                        "artist": "Artist",
                        "albumartist": "Artist",
                        "album": "Album",
                        "title": "First",
                        "tracknumber": "1",
                        "discnumber": "1",
                        "date": "2024",
                        "genre": "Rock",
                    },
                    issues=[],
                ),
                track_two: TrackMetadata(
                    path=track_two,
                    tags={
                        "artist": "Artist",
                        "albumartist": "Artist",
                        "album": "Album",
                        "title": "Second",
                        "tracknumber": "2",
                        "discnumber": "1",
                        "date": "2024",
                        "genre": "Rock",
                    },
                    issues=[],
                ),
            }

            report = analyze_library(source, read_track=lambda path: fake_metadata[path])

            self.assertEqual(len(report.tracks), 2)
            self.assertEqual(len(report.albums), 1)
            self.assertEqual(report.albums[0].album_id, "Artist::Album")
            self.assertEqual(report.albums[0].track_count, 2)
            self.assertEqual(report.tracks[0].tags["discnumber"], "1")

    def test_analyze_library_reports_missing_flac_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)

            report = analyze_library(source)

            self.assertEqual(len(report.tracks), 0)
            self.assertEqual(len(report.albums), 0)
            self.assertEqual(report.warnings[0].code, "no_flac_files")

    def test_analyze_library_surfaces_album_level_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            album_dir = source / "Mixed"
            album_dir.mkdir()
            track_one = album_dir / "01 First.flac"
            track_two = album_dir / "02 Second.flac"
            track_one.touch()
            track_two.touch()

            fake_metadata = {
                track_one: TrackMetadata(
                    path=track_one,
                    tags={
                        "artist": "Artist A",
                        "album": "Album",
                        "title": "First",
                        "tracknumber": "1",
                        "date": "2024",
                        "genre": "Rock",
                    },
                    issues=[WarningItem(code="missing_tag", message="Missing tag: albumartist", path=str(track_one))],
                ),
                track_two: TrackMetadata(
                    path=track_two,
                    tags={
                        "artist": "Artist B",
                        "album": "Album",
                        "title": "Second",
                        "tracknumber": "2",
                        "date": "2024",
                        "genre": "Rock",
                    },
                    issues=[WarningItem(code="missing_tag", message="Missing tag: albumartist", path=str(track_two))],
                ),
            }

            report = analyze_library(source, read_track=lambda path: fake_metadata[path])

            self.assertEqual(len(report.albums), 1)
            album_warning_codes = {warning.code for warning in report.albums[0].warnings}
            self.assertIn("album_conflicting_album_artists", album_warning_codes)
            self.assertIn("album_missing_consistent_albumartist", album_warning_codes)
            warning_codes = [issue.code for track in report.tracks for issue in track.issues]
            self.assertEqual(warning_codes.count("missing_tag"), 2)

    def test_analyze_library_reports_unreadable_real_flac(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            broken = source / "broken.flac"
            broken.write_text("not a flac", encoding="utf-8")

            report = analyze_library(source)

            self.assertEqual(len(report.tracks), 1)
            self.assertEqual(report.tracks[0].issues[0].code, "flac_read_error")

    def test_analyze_library_groups_disc_subfolders_under_one_album(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            album_dir = source / "Artist" / "Album"
            disc_one = album_dir / "CD1"
            disc_two = album_dir / "Disc 2"
            disc_one.mkdir(parents=True)
            disc_two.mkdir(parents=True)
            track_one = disc_one / "01 First.flac"
            track_two = disc_two / "01 Second.flac"
            track_one.touch()
            track_two.touch()

            fake_metadata = {
                track_one: TrackMetadata(
                    path=track_one,
                    tags={
                        "artist": "Artist",
                        "albumartist": "Artist",
                        "album": "Album",
                        "title": "First",
                        "tracknumber": "1",
                        "discnumber": "1",
                        "date": "2024",
                        "genre": "Rock",
                    },
                    issues=[],
                ),
                track_two: TrackMetadata(
                    path=track_two,
                    tags={
                        "artist": "Artist",
                        "albumartist": "Artist",
                        "album": "Album",
                        "title": "Second",
                        "tracknumber": "1",
                        "discnumber": "2",
                        "date": "2024",
                        "genre": "Rock",
                    },
                    issues=[],
                ),
            }

            report = analyze_library(source, read_track=lambda path: fake_metadata[path])

            self.assertEqual(len(report.albums), 1)
            self.assertEqual(report.albums[0].path, str(album_dir))


if __name__ == "__main__":
    unittest.main()
