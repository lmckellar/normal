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
    scan_movie_junk,
    scan_movie_promo_documents,
)
from normal.quality_review import MediaFacts


class MovieJunkTests(unittest.TestCase):
    def test_detects_sample_and_featurette_path_tokens(self) -> None:
        sample_reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Movie.1999.sample.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=5_000 * 1024 * 1024),
        )
        featurette_reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/Featurettes/Behind The Scenes.mkv"),
            MediaFacts(runtime_seconds=7200, file_size_bytes=5_000 * 1024 * 1024),
        )

        self.assertIn("junk_file_token", {reason.code for reason in sample_reasons})
        self.assertIn("junk_ancestor_token", {reason.code for reason in featurette_reasons})

    def test_detects_short_video_as_high_confidence_junk(self) -> None:
        reasons = detect_movie_junk_reasons(
            Path("/movies/Movie.1999/clip.mkv"),
            MediaFacts(runtime_seconds=299, file_size_bytes=800 * 1024 * 1024),
        )

        self.assertEqual([reason.code for reason in reasons], ["short_video"])
        self.assertEqual(reasons[0].confidence, "high")

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

            report = scan_movie_junk(
                source,
                probe_media=lambda _: MediaFacts(runtime_seconds=7200, file_size_bytes=4_000 * 1024 * 1024),
            )

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

    def test_scan_movie_junk_reports_probe_failures_but_still_uses_path_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie.sample.mkv"
            sample.write_text("video", encoding="utf-8")

            # Under 2 GB, marker-backed junk remains actionable without probe success.
            report = scan_movie_junk(
                source,
                probe_media=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
            )

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

    def test_scan_movie_junk_probes_ambiguous_2gb_to_3gb_marker_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            sample = source / "Movie" / "Movie.sample.mkv"
            sample.parent.mkdir()
            sample.touch()
            os.truncate(sample, int(2.5 * 1024 * 1024 * 1024))

            report = scan_movie_junk(
                source,
                probe_media=lambda _: MediaFacts(runtime_seconds=299, file_size_bytes=int(2.5 * 1024 * 1024 * 1024)),
            )

            self.assertEqual(len(report.junk), 1)
            self.assertEqual(report.junk[0].confidence, "high")
            self.assertEqual(report.junk[0].runtime_label, "4:59")

    def test_formats_file_size_and_runtime_for_review(self) -> None:
        self.assertEqual(format_file_size(75 * 1024 * 1024), "75.0 MB")
        self.assertEqual(format_file_size(2 * 1024 * 1024 * 1024), "2.00 GB")
        self.assertEqual(format_runtime(299), "4:59")
        self.assertEqual(format_runtime(3723), "1:02:03")


if __name__ == "__main__":
    unittest.main()
