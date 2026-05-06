from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from normal.movie_comparison import build_movie_comparison_report
from normal.quality_review import MediaFacts


class MovieComparisonTests(unittest.TestCase):
    def test_strict_normalized_matching_and_punctuation_case_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            datasets = root / "datasets"
            source.mkdir()
            datasets.mkdir()
            movie = source / "Spider-Man.No.Way.Home.2021.1080p.BluRay.mkv"
            movie.write_text("video", encoding="utf-8")
            self.write_dataset(
                datasets / "service.json",
                {
                    "dataset_id": "netflix_snapshot",
                    "dataset_name": "Netflix",
                    "dataset_kind": "service",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [
                        {"title": "spider man: no way home", "year": 2021},
                    ],
                },
            )

            report = build_movie_comparison_report(
                source,
                dataset_root=datasets,
                probe_media=lambda _: MediaFacts(width=1920, height=1080, video_bitrate_kbps=6000),
            )

            self.assertEqual(report.aggregates.total_normalized_movies, 1)
            self.assertEqual(report.service_datasets[0].overlap_count, 1)
            self.assertEqual(report.service_datasets[0].overlap_pct, 100.0)

    def test_skips_non_normalized_titles_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            datasets = root / "datasets"
            source.mkdir()
            datasets.mkdir()
            (source / "Unknown.Title.mkv").write_text("video", encoding="utf-8")
            self.write_dataset(
                datasets / "service.json",
                {
                    "dataset_id": "netflix_snapshot",
                    "dataset_name": "Netflix",
                    "dataset_kind": "service",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [],
                },
            )

            report = build_movie_comparison_report(
                source,
                dataset_root=datasets,
                probe_media=lambda _: MediaFacts(width=1920, height=1080, video_bitrate_kbps=6000),
            )

            self.assertEqual(report.aggregates.total_normalized_movies, 0)
            self.assertEqual(report.aggregates.skipped_non_normalized_movies, 1)
            self.assertIn("comparison_skipped_non_normalized_movie", {item.code for item in report.warnings})

    def test_duplicate_local_copies_collapse_and_choose_strongest_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            datasets = root / "datasets"
            source.mkdir()
            datasets.mkdir()
            weak = source / "Alien.1979.1080p.WEBRip.mkv"
            strong = source / "disc2" / "Alien.1979.2160p.BluRay.mkv"
            strong.parent.mkdir()
            weak.write_text("video", encoding="utf-8")
            strong.write_text("video", encoding="utf-8")
            self.write_dataset(
                datasets / "service.json",
                {
                    "dataset_id": "max_snapshot",
                    "dataset_name": "Max",
                    "dataset_kind": "service",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [{"title": "Alien", "year": 1979}],
                },
            )

            def probe(path: Path) -> MediaFacts:
                if path == weak:
                    return MediaFacts(width=1920, height=1080, video_bitrate_kbps=2000)
                return MediaFacts(width=3840, height=2160, video_bitrate_kbps=25000)

            report = build_movie_comparison_report(source, dataset_root=datasets, probe_media=probe)

            self.assertEqual(report.aggregates.total_normalized_movies, 1)
            self.assertEqual(report.service_datasets[0].overlap_count, 1)
            self.assertEqual(report.service_datasets[0].matched_titles[0].copy_count, 2)
            self.assertEqual(report.service_datasets[0].matched_titles[0].strongest_profile_label, "4k_remux")
            self.assertEqual(report.aggregates.minimum_acceptable_or_better_pct_within_service_matches, 100.0)

    def test_service_union_prestige_and_recent_release_math(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            datasets = root / "datasets"
            source.mkdir()
            datasets.mkdir()
            names = [
                "Alien.1979.2160p.BluRay.mkv",
                "The.Matrix.1999.1080p.BluRay.mkv",
                "Parasite.2019.1080p.BluRay.mkv",
                "Dune.Part.Two.2024.1080p.WEB-DL.mkv",
            ]
            for name in names:
                (source / name).write_text("video", encoding="utf-8")
            self.write_dataset(
                datasets / "services.json",
                {
                    "dataset_id": "netflix_snapshot",
                    "dataset_name": "Netflix",
                    "dataset_kind": "service",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [
                        {"title": "Alien", "year": 1979},
                        {"title": "The Matrix", "year": 1999},
                    ],
                },
            )
            self.write_dataset(
                datasets / "max.json",
                {
                    "dataset_id": "max_snapshot",
                    "dataset_name": "Max",
                    "dataset_kind": "service",
                    "snapshot_date": "2026-05-02",
                    "freshness_label": "snapshot May 2026",
                    "entries": [
                        {"title": "The Matrix", "year": 1999},
                        {"title": "Parasite", "year": 2019},
                    ],
                },
            )
            self.write_dataset(
                datasets / "imdb250.json",
                {
                    "dataset_id": "imdb_top_250",
                    "dataset_name": "IMDb Top 250",
                    "dataset_kind": "prestige",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [
                        {"title": "Alien", "year": 1979},
                        {"title": "The Matrix", "year": 1999},
                        {"title": "Seven Samurai", "year": 1954},
                        {"title": "Parasite", "year": 2019},
                    ],
                },
            )
            self.write_dataset(
                datasets / "imdb1000.json",
                {
                    "dataset_id": "imdb_top_1000",
                    "dataset_name": "IMDb Top 1000",
                    "dataset_kind": "prestige",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [
                        {"title": "Alien", "year": 1979},
                        {"title": "Dune Part Two", "year": 2024},
                        {"title": "The Thing", "year": 1982},
                        {"title": "Parasite", "year": 2019},
                        {"title": "The Matrix", "year": 1999},
                    ],
                },
            )
            self.write_dataset(
                datasets / "cannes.json",
                {
                    "dataset_id": "cannes_palme_dor",
                    "dataset_name": "Palme d'Or",
                    "dataset_kind": "prestige",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [
                        {"title": "Parasite", "year": 2019},
                        {"title": "Anatomy of a Fall", "year": 2023},
                    ],
                },
            )
            self.write_dataset(
                datasets / "recent.json",
                {
                    "dataset_id": "recent_releases",
                    "dataset_name": "Recent Releases",
                    "dataset_kind": "recent",
                    "snapshot_date": "2026-05-01",
                    "freshness_label": "snapshot May 2026",
                    "entries": [
                        {"title": "Dune Part Two", "year": 2024, "release_date": "2024-03-01"},
                        {"title": "Parasite", "year": 2019, "release_date": "2019-05-30"},
                    ],
                },
            )

            report = build_movie_comparison_report(
                source,
                dataset_root=datasets,
                probe_media=self.probe_for_names(),
                now=datetime(2025, 6, 1, tzinfo=UTC),
            )

            self.assertEqual(report.aggregates.total_normalized_movies, 4)
            self.assertEqual(report.service_datasets[0].overlap_pct, 50.0)
            self.assertEqual(report.service_datasets[1].overlap_pct, 50.0)
            self.assertEqual(report.aggregates.service_union_overlap_count, 3)
            self.assertEqual(report.aggregates.service_union_overlap_pct, 75.0)
            self.assertEqual(report.aggregates.imdb_top_250_coverage_pct, 75.0)
            self.assertEqual(report.aggregates.imdb_top_1000_coverage_pct, 80.0)
            self.assertEqual(report.aggregates.recent_releases_18m_count, 1)
            self.assertEqual(report.aggregates.recent_releases_18m_pct, 25.0)

    def test_missing_snapshot_date_warns_but_keeps_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            datasets = root / "datasets"
            source.mkdir()
            datasets.mkdir()
            (source / "Alien.1979.1080p.mkv").write_text("video", encoding="utf-8")
            self.write_dataset(
                datasets / "service.json",
                {
                    "dataset_id": "service_one",
                    "dataset_name": "Service One",
                    "dataset_kind": "service",
                    "freshness_label": "unknown",
                    "entries": [{"title": "Alien", "year": 1979}],
                },
            )

            report = build_movie_comparison_report(
                source,
                dataset_root=datasets,
                probe_media=lambda _: MediaFacts(width=1920, height=1080, video_bitrate_kbps=6000),
            )

            self.assertEqual(report.service_datasets[0].overlap_count, 1)
            self.assertIn("comparison_dataset_missing_snapshot_date", {item.code for item in report.warnings})

    def test_no_datasets_installed_returns_empty_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            datasets = root / "datasets"
            source.mkdir()
            datasets.mkdir()
            (source / "Alien.1979.1080p.mkv").write_text("video", encoding="utf-8")

            report = build_movie_comparison_report(
                source,
                dataset_root=datasets,
                probe_media=lambda _: MediaFacts(width=1920, height=1080, video_bitrate_kbps=6000),
            )

            self.assertEqual(report.available_datasets, [])
            self.assertEqual(report.selected_dataset_ids, [])
            self.assertIn("no_comparison_datasets", {item.code for item in report.warnings})

    def write_dataset(self, path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def probe_for_names(self):
        def probe(path: Path) -> MediaFacts:
            name = path.name
            if "Alien" in name:
                return MediaFacts(width=3840, height=2160, video_bitrate_kbps=25000)
            if "Matrix" in name:
                return MediaFacts(width=1920, height=1080, video_bitrate_kbps=6500)
            if "Parasite" in name:
                return MediaFacts(width=1920, height=1080, video_bitrate_kbps=2000)
            return MediaFacts(width=1920, height=1080, video_bitrate_kbps=5000)

        return probe


if __name__ == "__main__":
    unittest.main()
