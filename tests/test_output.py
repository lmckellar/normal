from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.models import AlbumReport, TrackReport
from normal.output import _build_register_rows, build_collection_rows, build_movie_review_rows, write_collection_csv, write_movie_review_csv


class OutputTests(unittest.TestCase):
    def test_build_collection_rows_emits_consensus_values(self) -> None:
        tracks = [
            TrackReport(
                track_id="Artist/1999 - Album/01 Song.flac",
                path="/library/Artist/1999 - Album/01 Song.flac",
                tags={
                    "artist": "Artist",
                    "albumartist": "Artist",
                    "album": "Album",
                    "title": "Song",
                    "tracknumber": "1",
                    "discnumber": "1",
                    "date": "1999-01-01",
                    "genre": "Rock",
                },
                issues=[],
            ),
            TrackReport(
                track_id="Artist/1999 - Album/02 Song.flac",
                path="/library/Artist/1999 - Album/02 Song.flac",
                tags={
                    "artist": "Artist",
                    "albumartist": "Artist",
                    "album": "Album",
                    "title": "Song 2",
                    "tracknumber": "2",
                    "discnumber": "1",
                    "date": "1999",
                    "genre": "Rock",
                },
                issues=[],
            ),
        ]
        albums = [
            AlbumReport(album_id="Artist::Album", path="/library/Artist/1999 - Album", track_count=2, warnings=[])
        ]
        report = type("Report", (), {"tracks": tracks, "albums": albums})()

        rows = build_collection_rows(report)

        self.assertEqual(rows, [["Artist", "Album", "1999", "Rock", "2", "/library/Artist/1999 - Album"]])

    def test_build_collection_rows_joins_mixed_genres_deterministically(self) -> None:
        tracks = [
            TrackReport(
                track_id="Artist/Album/01 Song.flac",
                path="/library/Artist/Album/01 Song.flac",
                tags={"artist": "Artist", "album": "Album", "genre": "Rock"},
                issues=[],
            ),
            TrackReport(
                track_id="Artist/Album/02 Song.flac",
                path="/library/Artist/Album/02 Song.flac",
                tags={"artist": "Artist", "album": "Album", "genre": "Pop"},
                issues=[],
            ),
        ]
        albums = [AlbumReport(album_id="Artist::Album", path="/library/Artist/Album", track_count=2, warnings=[])]
        report = type("Report", (), {"tracks": tracks, "albums": albums})()

        rows = build_collection_rows(report)

        self.assertEqual(rows[0][3], "Pop;Rock")

    def test_write_collection_csv_writes_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "library"
            source.mkdir()
            csv_path = root / "out" / "collection.csv"
            tracks = [
                TrackReport(
                    track_id="Artist/Album/01 Song.flac",
                    path=str(source / "Artist" / "Album" / "01 Song.flac"),
                    tags={"artist": "Artist", "album": "Album", "genre": "Rock", "date": "2001"},
                    issues=[],
                )
            ]
            albums = [
                AlbumReport(
                    album_id="Artist::Album",
                    path=str(source / "Artist" / "Album"),
                    track_count=1,
                    warnings=[],
                )
            ]
            report = type("Report", (), {"tracks": tracks, "albums": albums})()

            with patch("normal.output.analyze_library", return_value=report):
                write_collection_csv(source, csv_path)

            self.assertTrue(csv_path.exists())
            contents = csv_path.read_text(encoding="utf-8")
            self.assertIn("album_artist,album,date,genre,track_count,path", contents)
            self.assertIn("Artist,Album,2001,Rock,1", contents)

    def test_build_movie_review_rows_filters_and_sorts_worst_first(self) -> None:
        payload = {
            "movies": [
                {
                    "path": "/movies/ok.mkv",
                    "triage_score": 5.0,
                    "replacement_priority_score": 1.00,
                    "replacement_priority_label": "medium",
                    "replacement_year_hint": 2015,
                    "review": {
                        "status": "ok",
                        "score": 5,
                        "confidence": "high",
                        "facts": {"resolution_bucket": "1080p", "runtime_seconds": 7200},
                        "derived": {"mb_per_min": 50.2},
                        "reasons": [],
                    },
                },
                {
                    "path": "/movies/review.mkv",
                    "triage_score": 36.0,
                    "replacement_priority_score": 0.90,
                    "replacement_priority_label": "low",
                    "replacement_year_hint": 2005,
                    "review": {
                        "status": "review",
                        "score": 40,
                        "confidence": "medium",
                        "facts": {
                            "resolution_bucket": "1080p",
                            "runtime_seconds": 7200,
                            "video_bitrate_kbps": 3200,
                            "audio_bitrate_kbps": 128,
                            "audio_channels": 2,
                            "audio_summary": "AAC 2.0",
                            "container": "matroska",
                            "video_codec": "h264",
                            "audio_codec": "aac",
                        },
                        "derived": {"mb_per_min": 14.3},
                        "reasons": [{"code": "low_video_bitrate"}],
                    },
                },
                {
                    "path": "/movies/severe.mkv",
                    "triage_score": 87.8,
                    "replacement_priority_score": 0.75,
                    "replacement_priority_label": "low",
                    "replacement_year_hint": 1999,
                    "review": {
                        "status": "severe",
                        "score": 117,
                        "confidence": "high",
                        "facts": {
                            "resolution_bucket": "1080p",
                            "runtime_seconds": 7200,
                            "video_bitrate_kbps": 2200,
                            "audio_bitrate_kbps": 96,
                            "audio_channels": 2,
                            "audio_summary": "AAC 2.0",
                            "container": "mp4",
                            "video_codec": "h264",
                            "audio_codec": "aac",
                        },
                        "derived": {"mb_per_min": 10.8},
                        "reasons": [{"code": "low_video_bitrate"}, {"code": "weak_audio_bitrate"}],
                    },
                },
            ]
        }

        rows = build_movie_review_rows(payload, minimum_status="review")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "severe")
        self.assertEqual(rows[0][1], "87.8")
        self.assertEqual(rows[0][2], "117")
        self.assertEqual(rows[0][-1], "/movies/severe.mkv")
        self.assertEqual(rows[0][11], "2")
        self.assertEqual(rows[0][12], "AAC 2.0")
        self.assertEqual(rows[1][0], "review")

    def test_write_movie_review_csv_writes_triage_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_path = root / "movie-quality.json"
            csv_path = root / "out" / "movie-quality.csv"
            report_path.write_text(
                """
{
  "movies": [
    {
      "path": "/movies/severe.mkv",
      "triage_score": 70.2,
      "replacement_priority_score": 0.60,
      "replacement_priority_label": "very_low",
      "replacement_year_hint": 1980,
      "review": {
        "status": "severe",
        "score": 117,
        "confidence": "high",
        "facts": {
          "resolution_bucket": "1080p",
          "runtime_seconds": 7200,
          "video_bitrate_kbps": 2200,
          "audio_bitrate_kbps": 96,
          "audio_channels": 2,
          "audio_summary": "AAC 2.0",
          "container": "mp4",
          "video_codec": "h264",
          "audio_codec": "aac"
        },
        "derived": {"mb_per_min": 10.8},
        "reasons": [{"code": "low_video_bitrate"}]
      }
    }
  ]
}
""".strip(),
                encoding="utf-8",
            )

            write_movie_review_csv(report_path, csv_path)

            contents = csv_path.read_text(encoding="utf-8")
            self.assertIn(
                "status,triage_score,score,replacement_priority_score,replacement_priority_label,replacement_year_hint",
                contents,
            )
            self.assertIn(
                "severe,70.2,117,0.60,very_low,1980,high,1080p,120.0,2200,96,2,AAC 2.0,10.8,mp4,h264,aac,,,,,,,low_video_bitrate,/movies/severe.mkv",
                contents,
            )

    def test_movie_register_rows_parse_numeric_titles(self) -> None:
        payload = {
            "movies": [
                {
                    "path": "/movies/(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO]/(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO].mkv",
                    "review": {
                        "facts": {
                            "resolution_bucket": "1080p",
                            "video_codec": "h264",
                            "audio_codec": "dts",
                            "audio_channels": 2,
                            "audio_summary": "Dolby TrueHD 7.1 Atmos",
                            "container": "matroska",
                            "file_size_bytes": 11_800_000_000,
                        }
                    },
                },
                {
                    "path": "/movies/(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE]/(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE].mkv",
                    "review": {
                        "facts": {
                            "resolution_bucket": "2160p",
                            "video_codec": "hevc",
                            "audio_codec": "aac",
                            "audio_channels": 6,
                            "audio_summary": "AAC 5.1",
                            "container": "matroska",
                            "file_size_bytes": 22_700_000_000,
                        }
                    },
                },
            ]
        }

        rows = _build_register_rows(payload)

        self.assertEqual(rows[0][0:2], ["1917", "2019"])
        self.assertEqual(rows[0][4], "Dolby TrueHD 7.1 Atmos")
        self.assertEqual(rows[1][0:2], ["2001 A Space Odyssey", "1968"])


if __name__ == "__main__":
    unittest.main()
