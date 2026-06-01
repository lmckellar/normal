from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from normal.movie_junk import (
    detect_movie_junk_document_reasons,
    detect_movie_junk_reasons,
    format_file_size,
    format_runtime,
    scan_movie_cleanup,
    scan_movie_junk,
    scan_movie_promo_documents,
)
from normal.quality_review import AudioStreamFacts, MediaFacts


class MovieJunkTests(unittest.TestCase):
    def test_detects_sample_and_featurette_path_tokens(self) -> None:
        sample_reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Movie.1999.sample.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=500 * 1024 * 1024),
        )
        featurette_reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Featurettes/Behind The Scenes.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=500 * 1024 * 1024),
        )

        self.assertIn("junk_file_token", {reason.code for reason in sample_reasons})
        self.assertIn("junk_ancestor_token", {reason.code for reason in featurette_reasons})

    def test_does_not_use_size_only_as_junk_signal(self) -> None:
        reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Movie.1999.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=50 * 1024 * 1024),
        )

        self.assertEqual(reasons, [])

    def test_treats_junk_marker_under_2gb_as_high_confidence(self) -> None:
        reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Extras/Behind.The.Scenes.sample.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=1_500 * 1024 * 1024),
        )

        self.assertEqual({reason.code for reason in reasons}, {"junk_file_token", "junk_ancestor_token"})
        self.assertTrue(all(reason.confidence == "high" for reason in reasons))

    def test_keeps_single_marker_between_2gb_and_3gb_as_review(self) -> None:
        reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Movie.1999.sample.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=2_500 * 1024 * 1024),
        )

        self.assertEqual([reason.code for reason in reasons], ["junk_file_token"])
        self.assertEqual(reasons[0].confidence, "review")

    def test_promotes_between_2gb_and_3gb_when_signals_stack(self) -> None:
        reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Extras/Movie.1999.sample.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=2_500 * 1024 * 1024),
        )

        self.assertEqual({reason.code for reason in reasons}, {"junk_file_token", "junk_ancestor_token"})
        self.assertTrue(all(reason.confidence == "high" for reason in reasons))

    def test_keeps_marker_only_junk_at_or_above_3gb_as_review(self) -> None:
        reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Featurettes/Behind.The.Scenes.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=3_500 * 1024 * 1024),
        )

        self.assertEqual([reason.code for reason in reasons], ["junk_ancestor_token"])
        self.assertEqual(reasons[0].confidence, "review")

    def test_suppresses_marker_only_junk_at_or_above_4gb(self) -> None:
        reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Featurettes/Behind.The.Scenes.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=4 * 1024 * 1024 * 1024),
        )

        self.assertEqual(reasons, [])

    def test_suppresses_reported_large_extra_false_positives(self) -> None:
        filename_only = detect_movie_junk_reasons(
            Path("/movies/E.T.The.Extra-Terrestrial.1982.Bluray.1080p.DTS-HD-7.1.x264-Grym.(@BTNET).mkv"),
            MediaFacts(runtime_seconds=6900, file_size_bytes=15_450_000_000),
        )
        ancestor_only = detect_movie_junk_reasons(
            Path("/movies/The Game 1997 Criterion BDRip 1080p DTS extra-HighCode/The Game 1997 Criterion BDRip 1080p DTS-HighCode.mkv"),
            MediaFacts(runtime_seconds=7800, file_size_bytes=13_360_000_000),
        )

        self.assertEqual(filename_only, [])
        self.assertEqual(ancestor_only, [])

    def test_detects_promo_document_junk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            promo = source / "Movie.1999" / "RARBG.txt"
            neutral = source / "Movie.1999" / "notes.txt"
            promo.parent.mkdir()
            promo.write_text("Downloaded from example", encoding="utf-8")
            neutral.write_text("Keep this restoration note.", encoding="utf-8")

            promo_reasons = detect_movie_junk_document_reasons(promo)
            neutral_reasons = detect_movie_junk_document_reasons(neutral)

            self.assertIn("promo_document_name", {reason.code for reason in promo_reasons})
            self.assertIn("promo_document_content", {reason.code for reason in promo_reasons})
            self.assertEqual(neutral_reasons, [])

    def test_scan_movie_junk_ignores_full_length_movie(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.1999.1080p.mkv"
            movie.touch()
            os.truncate(movie, 101 * 1024 * 1024)

            report = scan_movie_junk(source)

            self.assertEqual(report.junk, [])
            self.assertEqual(report.warnings, [])

    def test_scan_movie_junk_excludes_promo_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            promo = source / "Movie" / "www.example.com.html"
            neutral = source / "Movie" / "notes.txt"
            promo.parent.mkdir()
            promo.write_text("<html>Visit us at example</html>", encoding="utf-8")
            neutral.write_text("Director commentary note.", encoding="utf-8")

            report = scan_movie_junk(source)

            self.assertEqual(report.junk, [])

    def test_scan_movie_promo_documents_includes_promo_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            promo = source / "Movie" / "www.example.com.html"
            neutral = source / "Movie" / "notes.txt"
            promo.parent.mkdir()
            promo.write_text("<html>Visit us at example</html>", encoding="utf-8")
            neutral.write_text("Director commentary note.", encoding="utf-8")

            report = scan_movie_promo_documents(source)

            self.assertEqual([item.relative_path for item in report.junk], ["Movie/www.example.com.html"])
            self.assertEqual(report.junk[0].runtime_label, None)

    def test_scan_movie_junk_still_uses_path_tokens_without_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie.sample.mkv"
            sample.write_text("video", encoding="utf-8")

            report = scan_movie_junk(source)

            self.assertEqual(len(report.junk), 1)
            self.assertEqual(report.junk[0].confidence, "high")

    def test_scan_movie_junk_includes_review_table_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie" / "Movie.sample.mkv"
            sample.parent.mkdir()
            sample.write_text("video", encoding="utf-8")

            report = scan_movie_junk(source)

            item = report.junk[0]
            self.assertEqual(item.relative_path, "Movie/Movie.sample.mkv")
            self.assertEqual(item.file_name, "Movie.sample.mkv")
            self.assertIsNotNone(item.file_size_label)
            self.assertIsNone(item.runtime_label)

    def test_scan_movie_cleanup_enriches_video_junk_with_probe_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie" / "Movie.sample.mkv"
            sample.parent.mkdir()
            sample.write_text("video", encoding="utf-8")

            def probe_media(_: Path) -> MediaFacts:
                return MediaFacts(
                    runtime_seconds=301,
                    file_size_bytes=75 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    resolution_bucket="1080p",
                    video_bitrate_kbps=3200,
                    audio_bitrate_kbps=640,
                    audio_channels=6,
                    audio_summary="Dolby Digital 5.1",
                    audio_streams=[
                        AudioStreamFacts(index=1, language="eng", channels=6, bitrate_kbps=640, is_default=True),
                    ],
                )

            report = scan_movie_cleanup(source, probe_media=probe_media)

            item = report.junk[0]
            self.assertEqual(item.runtime_label, "5:01")
            self.assertEqual(item.facts["resolution_bucket"], "1080p")
            self.assertEqual(item.facts["video_bitrate_kbps"], 3200)
            self.assertEqual(item.facts["audio_bitrate_kbps"], 640)
            self.assertEqual(item.facts["audio_channels"], 6)
            self.assertEqual(item.facts["audio_summary"], "Dolby Digital 5.1")
            self.assertEqual(item.facts["audio_streams"][0]["language"], "eng")

    def test_scan_movie_cleanup_keeps_promo_document_media_facts_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            promo = source / "Movie" / "RARBG.txt"
            promo.parent.mkdir()
            promo.write_text("Downloaded from RARBG", encoding="utf-8")

            report = scan_movie_cleanup(source, probe_media=lambda _: self.fail("promo docs should not be probed"))

            item = report.junk[0]
            self.assertEqual(item.relative_path, "Movie/RARBG.txt")
            self.assertIsNone(item.facts)

    def test_scan_movie_junk_suppresses_large_marker_only_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie" / "Featurettes" / "Behind.The.Scenes.mkv"
            sample.parent.mkdir(parents=True)
            sample.touch()
            os.truncate(sample, 4 * 1024 * 1024 * 1024)

            report = scan_movie_junk(source)

            self.assertEqual(report.junk, [])

    def test_formats_file_size_and_runtime_for_review(self) -> None:
        self.assertEqual(format_file_size(75 * 1024 * 1024), "75.0 MB")
        self.assertEqual(format_file_size(2 * 1024 * 1024 * 1024), "2.00 GB")
        self.assertEqual(format_runtime(299), "4:59")
        self.assertEqual(format_runtime(3723), "1:02:03")


if __name__ == "__main__":
    unittest.main()
