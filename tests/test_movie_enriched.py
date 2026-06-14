from __future__ import annotations

from dataclasses import asdict
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_canonical_lists import build_movie_inventory_from_items
from normal.movie_enriched import (
    build_movie_scan_from_enriched,
    build_movie_cleanup_from_enriched,
    parsed_movies_from_enriched,
    scan_enriched_library,
)
from normal.movie_junk import scan_movie_cleanup
from normal.movie_profile import scan_movie_profiles
from normal.movie_scan import scan_movie_library
from normal.quality_review import MediaFacts
from normal.web.state import MovieEnrichedCache


class MovieEnrichedTests(unittest.TestCase):
    def test_scan_composes_facts_review_junk_identity_and_movie_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.1999.sample.mkv"
            movie.write_text("video", encoding="utf-8")

            report = scan_enriched_library(
                source,
                probe_media=lambda _: MediaFacts(
                    runtime_seconds=301,
                    file_size_bytes=75 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    video_bitrate_kbps=3200,
                ),
            )

            self.assertEqual(len(report.files), 1)
            item = report.files[0]
            self.assertEqual(item.movie_id, movie.name)
            self.assertEqual(item.identity.lane, "movie")
            self.assertEqual(item.identity.value.title, "Movie")
            self.assertEqual(item.identity.value.year, 1999)
            self.assertIn("junk_file_token", {reason.code for reason in item.junk_reasons})
            self.assertEqual(item.replacement_priority_label, "low")
            self.assertIsNone(item.probe_error)

    def test_probe_failure_keeps_path_and_identity_for_normalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "The.Matrix.1999.mkv"
            movie.write_text("video", encoding="utf-8")

            report = scan_enriched_library(
                source,
                probe_media=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
            )

            self.assertEqual([Path(item.path) for item in report.files], [movie])
            self.assertEqual(parsed_movies_from_enriched(report)[movie].title, "The Matrix")
            self.assertEqual(report.files[0].probe_error, "boom")
            self.assertEqual([warning.code for warning in report.warnings], ["movie_probe_error"])

    def test_junk_projection_keeps_probe_failures_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.sample.mkv"
            movie.write_text("video", encoding="utf-8")

            enriched = scan_enriched_library(
                source,
                probe_media=lambda _: (_ for _ in ()).throw(ValueError("bad probe payload")),
            )
            projected = build_movie_cleanup_from_enriched(source, enriched)

            self.assertEqual(len(projected.junk), 1)
            self.assertNotIn("movie_probe_error", {warning.code for warning in projected.warnings})

    def test_junk_projection_matches_existing_cleanup_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie" / "Movie.sample.mkv"
            movie.parent.mkdir()
            movie.write_text("video", encoding="utf-8")
            facts = MediaFacts(runtime_seconds=301, file_size_bytes=75 * 1024 * 1024, width=1920, height=1080)

            existing = scan_movie_cleanup(source, probe_media=lambda _: facts)
            enriched = scan_enriched_library(source, probe_media=lambda _: facts)
            projected = build_movie_cleanup_from_enriched(source, enriched)

            self.assertEqual([asdict(item) for item in projected.junk], [asdict(item) for item in existing.junk])
            self.assertEqual([asdict(item) for item in projected.warnings], [asdict(item) for item in existing.warnings])

    def test_source_keyed_cache_reuses_and_invalidates_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            cache = MovieEnrichedCache()
            report = scan_enriched_library(source, probe_media=lambda _: MediaFacts())

            cache.put(source, report)
            self.assertIs(cache.get(source), report)
            cache.invalidate(source)
            self.assertIsNone(cache.get(source))

    def test_enriched_cache_keeps_identity_lanes_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            cache = MovieEnrichedCache()
            movie_report = scan_enriched_library(source, probe_media=lambda _: MediaFacts())
            tv_report = scan_enriched_library(source, lane="tv", probe_media=lambda _: MediaFacts())

            cache.put(source, movie_report)
            cache.put(source, tv_report, lane="tv")

            self.assertIs(cache.get(source), movie_report)
            self.assertIs(cache.get(source, lane="tv"), tv_report)
            cache.invalidate(source)
            self.assertIsNone(cache.get(source))
            self.assertIsNone(cache.get(source, lane="tv"))

    def test_profile_projection_reuses_enriched_facts_and_identity_without_serializing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.1999.1080p.mkv"
            movie.write_text("video", encoding="utf-8")
            enriched = scan_enriched_library(
                source,
                probe_media=lambda _: MediaFacts(
                    width=1920,
                    height=1080,
                    video_bitrate_kbps=8000,
                ),
            )

            with patch("normal.movie_profile.parse_movie_name", side_effect=AssertionError("identity reparsed")):
                report = scan_movie_profiles(
                    source,
                    probe_media=lambda _: (_ for _ in ()).throw(AssertionError("media reprobed")),
                    enriched_report=enriched,
                )

            self.assertEqual(len(report.movies), 1)
            self.assertIs(report.movies[0].facts, enriched.files[0].facts)
            self.assertIs(report.movies[0].identity, enriched.files[0].identity)
            self.assertNotIn("identity", report.to_dict()["movies"][0])

    def test_canonical_inventory_consumes_retained_enriched_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.1999.mkv"
            movie.write_text("video", encoding="utf-8")
            enriched = scan_enriched_library(source, probe_media=lambda _: MediaFacts())

            with patch(
                "normal.movie_canonical_lists.parse_movie_identity",
                side_effect=AssertionError("identity reparsed"),
            ):
                inventory, unparsed, duplicates = build_movie_inventory_from_items(enriched.files)

            self.assertEqual([(key.title, key.year) for key in inventory], [("movie", 1999)])
            self.assertEqual(unparsed, 0)
            self.assertEqual(duplicates, 0)

    def test_catalogue_projection_matches_standalone_movie_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.1999.mkv"
            movie.write_text("video", encoding="utf-8")
            facts = MediaFacts(
                runtime_seconds=7200,
                file_size_bytes=2_000 * 1024 * 1024,
                width=1920,
                height=1080,
                video_bitrate_kbps=2500,
                audio_bitrate_kbps=128,
            )

            standalone = scan_movie_library(source, probe_media=lambda _: facts)
            projected = build_movie_scan_from_enriched(
                scan_enriched_library(source, probe_media=lambda _: facts)
            )

            self.assertEqual(
                [asdict(item) for item in projected.movies],
                [asdict(item) for item in standalone.movies],
            )
            self.assertEqual(
                [asdict(warning) for warning in projected.warnings],
                [asdict(warning) for warning in standalone.warnings],
            )


if __name__ == "__main__":
    unittest.main()
