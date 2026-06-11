from __future__ import annotations

import gzip
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.audit import AuditStore
from normal.movie_canonical_lists import (
    CanonicalListEntry,
    build_canonical_lists_report,
    ensure_imdb_dataset_ready,
    load_cache_entries,
    write_cache_entries,
)


def write_imdb_dataset(dataset_dir: Path, rows: list[dict[str, object]]) -> None:
    ratings_lines = ["tconst\taverageRating\tnumVotes"]
    basics_lines = ["tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear\truntimeMinutes\tgenres"]
    for row in rows:
        ratings_lines.append(f"{row['tconst']}\t{row['rating']}\t{row['votes']}")
        basics_lines.append(
            "\t".join(
                [
                    str(row["tconst"]),
                    "movie",
                    str(row["title"]),
                    str(row.get("original_title") or row["title"]),
                    "0",
                    str(row["year"]),
                    r"\N",
                    "120",
                    str(row.get("genres") or r"\N"),
                ]
            )
        )
    with gzip.open(dataset_dir / "title.ratings.tsv.gz", "wt", encoding="utf-8") as handle:
        handle.write("\n".join(ratings_lines) + "\n")
    with gzip.open(dataset_dir / "title.basics.tsv.gz", "wt", encoding="utf-8") as handle:
        handle.write("\n".join(basics_lines) + "\n")


class MovieCanonicalListsTests(unittest.TestCase):
    def test_build_canonical_lists_report_defaults_to_imdb_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien (1979).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as data_home:
                with tempfile.TemporaryDirectory() as dataset_tmp:
                    with patch.dict(os.environ):
                        os.environ["XDG_DATA_HOME"] = data_home
                        dataset_dir = Path(dataset_tmp)
                        os.environ["IMDB_DATASET_DIR"] = str(dataset_dir)
                        rows = [
                            {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                        ]
                        rows.extend(
                            {
                                "tconst": f"tt{index:07d}",
                                "title": f"Top {index}",
                                "year": 1950 + index,
                                "rating": max(5.0, 9.7 - (index / 1000)),
                                "votes": 50000 + index,
                                "genres": "Comedy",
                            }
                            for index in range(2, 620)
                        )
                        write_imdb_dataset(dataset_dir, rows)

                        report = build_canonical_lists_report(
                            source,
                            standards={},
                            tmdb_key=None,
                        )
        self.assertEqual(report.provider, "imdb")
        self.assertEqual(report.cache_state, "live")

    def test_build_canonical_lists_report_routes_tmdb_provider_and_unlocks_badges(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien.1979.1080p.mkv").write_text("video", encoding="utf-8")
            (source / "Alien.1979.2160p.mkv").write_text("video", encoding="utf-8")
            (source / "Blade.Runner.1982.1080p.mkv").write_text("video", encoding="utf-8")
            (source / "No.Year.Movie.mkv").write_text("video", encoding="utf-8")

            top_entries = [{"title": f"Top {index}", "year": 2000 + index} for index in range(1, 1001)]
            top_entries[0] = {"title": "Alien", "year": 1979}
            top_entries[1] = {"title": "Blade Runner", "year": 1982}
            genre_entries = [{"title": f"Genre {index}", "year": 1990 + index} for index in range(1, 101)]
            genre_entries[0] = {"title": "Alien", "year": 1979}

            def fake_http_get(url: str) -> dict[str, object]:
                if "/movie/top_rated" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 50,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in top_entries[start : start + 20]
                        ],
                    }
                if "/discover/movie" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 5,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in genre_entries[start : start + 20]
                        ],
                    }
                raise AssertionError(url)

            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    report = build_canonical_lists_report(
                        source,
                        standards={"canonical_list_provider": "tmdb"},
                        tmdb_key="test-key",
                        http_get=fake_http_get,
                    )
            self.assertEqual(report.library_summary.owned_movies, 2)
            self.assertEqual(report.library_summary.unparsed_files, 1)
            self.assertEqual(report.library_summary.duplicate_files, 1)
            self.assertEqual(report.provider, "tmdb")
            self.assertEqual(report.cache_state, "live")

            top_100 = next(item for item in report.list_summaries if item.id == "top_100")
            self.assertEqual(top_100.provider_label, "TMDb canonical list")
            self.assertEqual(top_100.covered_count, 2)
            self.assertEqual(top_100.total_count, 100)
            self.assertEqual(top_100.missing_count, 98)

            top_500 = next(item for item in report.list_summaries if item.id == "top_500")
            self.assertEqual(top_500.covered_count, 2)
            self.assertEqual(top_500.total_count, 500)
            self.assertEqual(top_500.missing_count, 498)

            animation = next(item for item in report.list_summaries if item.id == "animation")
            self.assertEqual(animation.covered_count, 1)
            self.assertEqual(animation.total_count, 100)
            self.assertFalse(any(item.id == "anime" for item in report.list_summaries))
            drama_romance = next(item for item in report.list_summaries if item.id == "drama_romance")
            self.assertEqual(drama_romance.label, "Drama / Romance")
            self.assertEqual(drama_romance.total_count, 100)

            sci_fi_badge = next(item for item in report.badges if item.id == "sci_fi")
            self.assertFalse(sci_fi_badge.unlocked)
            self.assertEqual(sci_fi_badge.coverage_percent, 1.0)

    def test_build_canonical_lists_report_routes_imdb_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien (1979).mkv").write_text("video", encoding="utf-8")
            (source / "Blade Runner (1982).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as data_home:
                with tempfile.TemporaryDirectory() as dataset_tmp:
                    with patch.dict(os.environ):
                        os.environ["XDG_DATA_HOME"] = data_home
                        dataset_dir = Path(dataset_tmp)
                        rows = [
                            {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                            {"tconst": "tt0000002", "title": "Blade Runner", "year": 1982, "rating": 9.8, "votes": 250000, "genres": "Sci-Fi,Action"},
                        ]
                        rows.extend(
                            {
                                "tconst": f"tt{index:07d}",
                                "title": f"Top {index}",
                                "year": 1950 + index,
                                "rating": max(5.0, 9.7 - (index / 1000)),
                                "votes": 50000 + index,
                                "genres": (
                                    "Animation,Comedy"
                                    if index % 7 == 0
                                    else "Fantasy,Action"
                                    if index % 7 == 1
                                    else "Documentary"
                                    if index % 7 == 2
                                    else "Sci-Fi,Thriller"
                                    if index % 7 == 3
                                    else "Mystery,Thriller"
                                    if index % 7 == 4
                                    else "Drama,Romance"
                                    if index % 7 == 5
                                    else "Action"
                                ),
                            }
                            for index in range(3, 720)
                        )
                        rows[2]["genres"] = "Animation,Comedy"
                        rows[3]["genres"] = "Fantasy,Action"
                        rows[4]["genres"] = "Documentary"
                        write_imdb_dataset(dataset_dir, rows)

                        report = build_canonical_lists_report(
                            source,
                            standards={"canonical_list_provider": "imdb"},
                            tmdb_key=None,
                            imdb_dataset_dir=dataset_dir,
                        )
            self.assertEqual(report.provider, "imdb")
            self.assertEqual(report.cache_state, "live")
            top_100 = next(item for item in report.list_summaries if item.id == "top_100")
            self.assertEqual(top_100.provider_label, "IMDb canonical list")
            self.assertEqual(top_100.covered_count, 2)
            self.assertEqual(top_100.total_count, 100)
            top_500 = next(item for item in report.list_summaries if item.id == "top_500")
            self.assertEqual(top_500.covered_count, 2)
            self.assertEqual(top_500.total_count, 500)
            animation = next(item for item in report.list_summaries if item.id == "animation")
            self.assertEqual(animation.label, "Animation")
            self.assertEqual(animation.total_count, 100)
            self.assertFalse(any(item.id == "anime" for item in report.list_summaries))
            drama_romance = next(item for item in report.list_summaries if item.id == "drama_romance")
            self.assertEqual(drama_romance.label, "Drama / Romance")
            self.assertEqual(drama_romance.total_count, 100)

    def test_imdb_top_lists_weight_votes_over_raw_average(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "The Lord of the Rings The Fellowship of the Ring (2001).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as dataset_tmp:
                dataset_dir = Path(dataset_tmp)
                rows = [
                    {
                        "tconst": "ttregional1",
                        "title": "Obscure Regional Darling",
                        "year": 1975,
                        "rating": 9.4,
                        "votes": 100500,
                        "genres": "Comedy",
                    },
                    {
                        "tconst": "tt0120737",
                        "title": "The Lord of the Rings: The Fellowship of the Ring",
                        "year": 2001,
                        "rating": 8.9,
                        "votes": 1900000,
                        "genres": "Adventure,Drama,Fantasy",
                    },
                ]
                rows.extend(
                    {
                        "tconst": f"tt{index:07d}",
                        "title": f"Top {index}",
                        "year": 1950 + index,
                        "rating": max(5.0, 8.0 - (index / 1000)),
                        "votes": 140000 + index,
                        "genres": "Comedy",
                    }
                    for index in range(3, 620)
                )
                write_imdb_dataset(dataset_dir, rows)

                report = build_canonical_lists_report(
                    source,
                    standards={"canonical_list_provider": "imdb"},
                    tmdb_key=None,
                    imdb_dataset_dir=dataset_dir,
                )

        top_100 = next(item for item in report.list_summaries if item.id == "top_100")
        self.assertEqual(top_100.all_entries[0]["title"], "The Lord of the Rings: The Fellowship of the Ring")
        self.assertEqual(top_100.all_entries[1]["title"], "Obscure Regional Darling")

    def test_imdb_genre_lists_use_weighted_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            with tempfile.TemporaryDirectory() as dataset_tmp:
                dataset_dir = Path(dataset_tmp)
                rows = [
                    {
                        "tconst": "ttregional2",
                        "title": "Tiny Cult Comedy",
                        "year": 1980,
                        "rating": 9.3,
                        "votes": 50500,
                        "genres": "Comedy",
                    },
                    {
                        "tconst": "tt0107048",
                        "title": "Groundhog Day",
                        "year": 1993,
                        "rating": 8.0,
                        "votes": 750000,
                        "genres": "Comedy,Fantasy",
                    },
                ]
                rows.extend(
                    {
                        "tconst": f"tt2{index:06d}",
                        "title": f"Comedy {index}",
                        "year": 1950 + index,
                        "rating": max(5.0, 7.7 - (index / 1000)),
                        "votes": 70000 + index,
                        "genres": "Comedy",
                    }
                    for index in range(3, 130)
                )
                write_imdb_dataset(dataset_dir, rows)

                report = build_canonical_lists_report(
                    source,
                    standards={"canonical_list_provider": "imdb"},
                    tmdb_key=None,
                    imdb_dataset_dir=dataset_dir,
                )

        comedy = next(item for item in report.list_summaries if item.id == "comedy")
        self.assertEqual(comedy.all_entries[0]["title"], "Groundhog Day")
        self.assertEqual(comedy.all_entries[1]["title"], "Tiny Cult Comedy")

    def test_imdb_hybrid_genre_lists_require_all_genres(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            with tempfile.TemporaryDirectory() as dataset_tmp:
                dataset_dir = Path(dataset_tmp)
                rows = [
                    {
                        "tconst": "tt0111161",
                        "title": "The Shawshank Redemption",
                        "year": 1994,
                        "rating": 9.3,
                        "votes": 3100000,
                        "genres": "Drama",
                    },
                    {
                        "tconst": "tt0068646",
                        "title": "The Godfather",
                        "year": 1972,
                        "rating": 9.2,
                        "votes": 2200000,
                        "genres": "Crime,Drama",
                    },
                    {
                        "tconst": "tt0120737",
                        "title": "The Lord of the Rings: The Fellowship of the Ring",
                        "year": 2001,
                        "rating": 8.9,
                        "votes": 2100000,
                        "genres": "Adventure,Drama,Fantasy",
                    },
                    {
                        "tconst": "tt0332280",
                        "title": "The Notebook",
                        "year": 2004,
                        "rating": 7.8,
                        "votes": 650000,
                        "genres": "Drama,Romance",
                    },
                    {
                        "tconst": "tt0109830",
                        "title": "Forrest Gump",
                        "year": 1994,
                        "rating": 8.8,
                        "votes": 2400000,
                        "genres": "Drama,Romance",
                    },
                ]
                rows.extend(
                    {
                        "tconst": f"tt9{index:06d}",
                        "title": f"Drama Romance {index}",
                        "year": 1950 + index,
                        "rating": max(5.0, 7.7 - (index / 1000)),
                        "votes": 70000 + index,
                        "genres": "Drama,Romance",
                    }
                    for index in range(3, 130)
                )
                write_imdb_dataset(dataset_dir, rows)

                report = build_canonical_lists_report(
                    source,
                    standards={"canonical_list_provider": "imdb"},
                    tmdb_key=None,
                    imdb_dataset_dir=dataset_dir,
                )

        drama_romance = next(item for item in report.list_summaries if item.id == "drama_romance")
        titles = [item["title"] for item in drama_romance.all_entries[:5]]
        self.assertIn("Forrest Gump", titles)
        self.assertIn("The Notebook", titles)
        self.assertNotIn("The Shawshank Redemption", titles)
        self.assertNotIn("The Godfather", titles)
        self.assertNotIn("The Lord of the Rings: The Fellowship of the Ring", titles)

    def test_imdb_genre_lists_fall_back_to_base_vote_floor_when_pool_is_small(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            with tempfile.TemporaryDirectory() as dataset_tmp:
                dataset_dir = Path(dataset_tmp)
                rows = []
                for index in range(1, 71):
                    rows.append(
                        {
                            "tconst": f"ttdoc{index:04d}",
                            "title": f"Documentary {index}",
                            "year": 1980 + index,
                            "rating": 7.5 - (index / 1000),
                            "votes": 30000 + index,
                            "genres": "Documentary",
                        }
                    )
                for index in range(71, 106):
                    rows.append(
                        {
                            "tconst": f"ttdoc{index:04d}",
                            "title": f"Documentary {index}",
                            "year": 1980 + index,
                            "rating": 7.5 - (index / 1000),
                            "votes": 52000 + index,
                            "genres": "Documentary",
                        }
                    )
                rows.extend(
                    {
                        "tconst": f"tt3{index:06d}",
                        "title": f"Top {index}",
                        "year": 1900 + index,
                        "rating": 6.0,
                        "votes": 200000 + index,
                        "genres": "Comedy",
                    }
                    for index in range(1, 520)
                )
                write_imdb_dataset(dataset_dir, rows)

                report = build_canonical_lists_report(
                    source,
                    standards={"canonical_list_provider": "imdb"},
                    tmdb_key=None,
                    imdb_dataset_dir=dataset_dir,
                )

        documentary = next(item for item in report.list_summaries if item.id == "documentary")
        self.assertEqual(documentary.label, "Documentary")
        self.assertEqual(documentary.total_count, 100)
        self.assertTrue(any(item["title"] == "Documentary 40" for item in documentary.all_entries))

    def test_build_canonical_lists_report_matches_imdb_primary_title_to_stylized_owned_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Se7en (1995)" / "Se7en (1995).mkv").parent.mkdir(parents=True)
            (source / "Se7en (1995)" / "Se7en (1995).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as dataset_tmp:
                dataset_dir = Path(dataset_tmp)
                rows = [
                    {
                        "tconst": "tt0114369",
                        "title": "Seven",
                        "original_title": "Se7en",
                        "year": 1995,
                        "rating": 8.6,
                        "votes": 2025160,
                        "genres": "Crime,Drama,Mystery",
                    }
                ]
                rows.extend(
                    {
                        "tconst": f"tt{index:07d}",
                        "title": f"Top {index}",
                        "year": 1950 + index,
                        "rating": max(5.0, 8.4 - (index / 1000)),
                        "votes": 50000 + index,
                        "genres": "Comedy",
                    }
                    for index in range(2, 620)
                )
                write_imdb_dataset(dataset_dir, rows)

                report = build_canonical_lists_report(
                    source,
                    standards={"canonical_list_provider": "imdb"},
                    tmdb_key=None,
                    imdb_dataset_dir=dataset_dir,
                )

        top_100 = next(item for item in report.list_summaries if item.id == "top_100")
        seven = next(item for item in top_100.all_entries if item["title"] == "Seven")
        self.assertTrue(seven["owned"])
        self.assertIn("Se7en (1995).mkv", seven["path"])

    def test_build_canonical_lists_report_includes_imdb_id_for_imdb_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien (1979).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as dataset_tmp:
                dataset_dir = Path(dataset_tmp)
                rows = [
                    {"tconst": "tt0078748", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                    {"tconst": "tt0083658", "title": "Blade Runner", "year": 1982, "rating": 9.8, "votes": 250000, "genres": "Sci-Fi,Action"},
                ]
                rows.extend(
                    {
                        "tconst": f"tt{index:07d}",
                        "title": f"Top {index}",
                        "year": 1950 + index,
                        "rating": max(5.0, 9.7 - (index / 1000)),
                        "votes": 50000 + index,
                        "genres": "Comedy",
                    }
                    for index in range(3, 620)
                )
                write_imdb_dataset(dataset_dir, rows)

                report = build_canonical_lists_report(
                    source,
                    standards={"canonical_list_provider": "imdb"},
                    tmdb_key=None,
                    imdb_dataset_dir=dataset_dir,
                )

        top_100 = next(item for item in report.list_summaries if item.id == "top_100")
        alien = next(item for item in top_100.all_entries if item["title"] == "Alien")
        blade_runner = next(item for item in top_100.all_entries if item["title"] == "Blade Runner")
        self.assertEqual(alien["imdb_id"], "tt0078748")
        self.assertEqual(blade_runner["imdb_id"], "tt0083658")
        self.assertTrue(alien["owned"])
        self.assertFalse(blade_runner["owned"])

    def test_build_canonical_lists_report_uses_stale_cache_on_tmdb_fetch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien.1979.1080p.mkv").write_text("video", encoding="utf-8")

            top_entries = [{"title": f"Top {index}", "year": 2000 + index} for index in range(1, 1001)]
            genre_entries = [{"title": f"Genre {index}", "year": 1990 + index} for index in range(1, 101)]

            def fake_http_get(url: str) -> dict[str, object]:
                if "/movie/top_rated" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 50,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in top_entries[start : start + 20]
                        ],
                    }
                if "/discover/movie" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 5,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in genre_entries[start : start + 20]
                        ],
                    }
                raise AssertionError(url)

            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    build_canonical_lists_report(
                        source,
                        standards={"canonical_list_provider": "tmdb"},
                        tmdb_key="test-key",
                        http_get=fake_http_get,
                        now=lambda: 1000.0,
                    )
                    stale_report = build_canonical_lists_report(
                        source,
                        standards={"canonical_list_provider": "tmdb"},
                        tmdb_key="test-key",
                        http_get=lambda _url: (_ for _ in ()).throw(TimeoutError("boom")),
                        now=lambda: 1000.0 + (8 * 24 * 60 * 60),
                    )
            self.assertEqual(stale_report.cache_state, "stale")

    def test_build_canonical_lists_report_uses_stale_cache_on_imdb_refresh_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien (1979).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as data_home:
                with tempfile.TemporaryDirectory() as dataset_tmp:
                    with patch.dict(os.environ):
                        os.environ["XDG_DATA_HOME"] = data_home
                        dataset_dir = Path(dataset_tmp)
                        rows = [
                            {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                        ]
                        rows.extend(
                            {
                                "tconst": f"tt{index:07d}",
                                "title": f"Top {index}",
                                "year": 1950 + index,
                                "rating": max(5.0, 9.7 - (index / 1000)),
                                "votes": 50000 + index,
                                "genres": "Animation,Comedy" if index % 3 == 0 else "Comedy",
                            }
                            for index in range(2, 620)
                        )
                        write_imdb_dataset(dataset_dir, rows)
                        build_canonical_lists_report(
                            source,
                            standards={"canonical_list_provider": "imdb"},
                            tmdb_key=None,
                            imdb_dataset_dir=dataset_dir,
                            now=lambda: 1000.0,
                        )
                        (dataset_dir / "title.basics.tsv.gz").unlink()
                        stale_report = build_canonical_lists_report(
                            source,
                            standards={"canonical_list_provider": "imdb"},
                            tmdb_key=None,
                            imdb_dataset_dir=dataset_dir,
                            now=lambda: 1000.0 + (8 * 24 * 60 * 60),
                        )
            self.assertEqual(stale_report.cache_state, "stale")

    def test_imdb_provider_bootstraps_to_pending_status_without_manual_dataset_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien (1979).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    os.environ.pop("IMDB_DATASET_DIR", None)
                    with patch("normal.movie_canonical_lists._download_managed_imdb_dataset", side_effect=lambda *, now: time.sleep(0.05)):
                        report = build_canonical_lists_report(
                            source,
                            standards={"canonical_list_provider": "imdb"},
                            tmdb_key=None,
                        )
        self.assertEqual(report.provider, "imdb")
        self.assertEqual(report.canonical_status["state"], "bootstrapping")
        self.assertEqual(report.library_summary.matched_canonical_titles, 0)

    def test_ensure_imdb_dataset_ready_downloads_managed_store(self) -> None:
        with tempfile.TemporaryDirectory() as data_home:
            with patch.dict(os.environ):
                os.environ["XDG_DATA_HOME"] = data_home
                os.environ.pop("IMDB_DATASET_DIR", None)
                rows = [
                    {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                    {"tconst": "tt0000002", "title": "Blade Runner", "year": 1982, "rating": 9.8, "votes": 250000, "genres": "Sci-Fi,Action"},
                ]
                rows.extend(
                    {
                        "tconst": f"tt{index:07d}",
                        "title": f"Top {index}",
                        "year": 1950 + index,
                        "rating": max(5.0, 9.7 - (index / 1000)),
                        "votes": 50000 + index,
                        "genres": "Comedy",
                    }
                    for index in range(3, 620)
                )

                def fake_download(*, now):
                    del now
                    dataset_dir = Path(data_home) / "normal" / "imdb-datasets"
                    dataset_dir.mkdir(parents=True, exist_ok=True)
                    write_imdb_dataset(dataset_dir, rows)
                    manifest_path = dataset_dir / "manifest.json"
                    manifest_path.write_text(json.dumps({"refresh_in_progress": True}) + "\n", encoding="utf-8")

                with patch("normal.movie_canonical_lists._download_managed_imdb_dataset", side_effect=fake_download):
                    status = ensure_imdb_dataset_ready(block=True)
        self.assertTrue(status["ready"])
        self.assertEqual(status["state"], "ready")

    def test_imdb_cache_namespace_is_provider_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien (1979).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as data_home:
                with tempfile.TemporaryDirectory() as dataset_tmp:
                    with patch.dict(os.environ):
                        os.environ["XDG_DATA_HOME"] = data_home
                        rows = [
                            {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                        ]
                        rows.extend(
                            {
                                "tconst": f"tt{index:07d}",
                                "title": f"Top {index}",
                                "year": 1950 + index,
                                "rating": max(5.0, 9.7 - (index / 1000)),
                                "votes": 50000 + index,
                                "genres": "Animation,Comedy" if index % 3 == 0 else "Comedy",
                            }
                            for index in range(2, 620)
                        )
                        dataset_dir = Path(dataset_tmp)
                        write_imdb_dataset(dataset_dir, rows)
                        build_canonical_lists_report(
                            source,
                            standards={"canonical_list_provider": "imdb"},
                            tmdb_key=None,
                            imdb_dataset_dir=dataset_dir,
                        )
                imdb_dir = Path(data_home) / "normal" / "canonical_lists" / "v6" / "imdb"
                tmdb_dir = Path(data_home) / "normal" / "canonical_lists" / "v6" / "tmdb"
                self.assertTrue(imdb_dir.exists())
                self.assertGreater(len(list(imdb_dir.glob("*.json"))), 0)
                self.assertFalse(tmdb_dir.exists() and list(tmdb_dir.glob("*.json")))

    def test_imdb_cache_namespace_changes_when_dataset_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien (1979).mkv").write_text("video", encoding="utf-8")
            with tempfile.TemporaryDirectory() as data_home:
                with tempfile.TemporaryDirectory() as dataset_a_tmp:
                    with tempfile.TemporaryDirectory() as dataset_b_tmp:
                        with patch.dict(os.environ):
                            os.environ["XDG_DATA_HOME"] = data_home
                            dataset_a = Path(dataset_a_tmp)
                            dataset_b = Path(dataset_b_tmp)
                            rows_a = [
                                {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                                {"tconst": "tt0000002", "title": "Top 2", "year": 1952, "rating": 9.8, "votes": 250000, "genres": "Comedy"},
                            ]
                            rows_a.extend(
                                {
                                    "tconst": f"tt{index:07d}",
                                    "title": f"Top {index}",
                                    "year": 1950 + index,
                                    "rating": max(5.0, 9.7 - (index / 1000)),
                                    "votes": 50000 + index,
                                    "genres": "Comedy",
                                }
                                for index in range(3, 620)
                            )
                            rows_b = [
                                {"tconst": "tt1000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                                {"tconst": "tt1000002", "title": "Blade Runner", "year": 1982, "rating": 9.8, "votes": 250000, "genres": "Sci-Fi,Action"},
                            ]
                            rows_b.extend(
                                {
                                    "tconst": f"tt1{index:06d}",
                                    "title": f"Real {index}",
                                    "year": 1950 + index,
                                    "rating": max(5.0, 9.7 - (index / 1000)),
                                    "votes": 50000 + index,
                                    "genres": "Comedy",
                                }
                                for index in range(3, 620)
                            )
                            write_imdb_dataset(dataset_a, rows_a)
                            report_a = build_canonical_lists_report(
                                source,
                                standards={"canonical_list_provider": "imdb"},
                                tmdb_key=None,
                                imdb_dataset_dir=dataset_a,
                                now=lambda: 1000.0,
                            )
                            write_imdb_dataset(dataset_b, rows_b)
                            report_b = build_canonical_lists_report(
                                source,
                                standards={"canonical_list_provider": "imdb"},
                                tmdb_key=None,
                                imdb_dataset_dir=dataset_b,
                                now=lambda: 1000.0,
                            )
            top_100_a = next(item for item in report_a.list_summaries if item.id == "top_100")
            top_100_b = next(item for item in report_b.list_summaries if item.id == "top_100")
            self.assertEqual(top_100_a.all_entries[1]["title"], "Top 2")
            self.assertEqual(top_100_b.all_entries[1]["title"], "Blade Runner")

    def test_ensure_imdb_dataset_ready_records_bootstrap_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(ledger_path=root / "audit-ledger.jsonl")
            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    os.environ.pop("IMDB_DATASET_DIR", None)
                    rows = [
                        {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                    ]
                    rows.extend(
                        {
                            "tconst": f"tt{index:07d}",
                            "title": f"Top {index}",
                            "year": 1950 + index,
                            "rating": max(5.0, 9.7 - (index / 1000)),
                            "votes": 50000 + index,
                            "genres": "Comedy",
                        }
                        for index in range(2, 620)
                    )

                    def fake_download(*, now):
                        del now
                        dataset_dir = Path(data_home) / "normal" / "imdb-datasets"
                        dataset_dir.mkdir(parents=True, exist_ok=True)
                        write_imdb_dataset(dataset_dir, rows)

                    with patch("normal.movie_canonical_lists._download_managed_imdb_dataset", side_effect=fake_download):
                        ensure_imdb_dataset_ready(
                            block=True,
                            audit_store=store,
                            audit_source_root=source,
                        )
            actions = [event.action for event in store.read_events(source, limit=10)]
            self.assertEqual(actions, ["imdb_dataset_bootstrap_started", "imdb_dataset_bootstrap_completed"])

    def test_ensure_imdb_dataset_ready_late_source_subscription_records_bootstrap_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(ledger_path=root / "audit-ledger.jsonl")
            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    os.environ.pop("IMDB_DATASET_DIR", None)
                    rows = [
                        {"tconst": "tt0000001", "title": "Alien", "year": 1979, "rating": 9.9, "votes": 300000, "genres": "Sci-Fi,Thriller"},
                    ]
                    rows.extend(
                        {
                            "tconst": f"tt{index:07d}",
                            "title": f"Top {index}",
                            "year": 1950 + index,
                            "rating": max(5.0, 9.7 - (index / 1000)),
                            "votes": 50000 + index,
                            "genres": "Comedy",
                        }
                        for index in range(2, 620)
                    )
                    started = threading.Event()
                    finish = threading.Event()

                    def fake_download(*, now):
                        del now
                        started.set()
                        finish.wait(timeout=5)
                        dataset_dir = Path(data_home) / "normal" / "imdb-datasets"
                        dataset_dir.mkdir(parents=True, exist_ok=True)
                        write_imdb_dataset(dataset_dir, rows)

                    with patch("normal.movie_canonical_lists._download_managed_imdb_dataset", side_effect=fake_download):
                        ensure_imdb_dataset_ready(block=False)
                        self.assertTrue(started.wait(timeout=5))
                        ensure_imdb_dataset_ready(
                            block=False,
                            audit_store=store,
                            audit_source_root=source,
                        )
                        finish.set()
                        ensure_imdb_dataset_ready(
                            block=True,
                            audit_store=store,
                            audit_source_root=source,
                        )
            actions = [event.action for event in store.read_events(source, limit=10)]
            self.assertEqual(actions, ["imdb_dataset_bootstrap_started", "imdb_dataset_bootstrap_completed"])

    def test_franchise_prefix_and_subtitle_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Star Wars Episode V The Empire Strikes Back (1980).mkv").write_text("video", encoding="utf-8")
            (source / "The Lord of the Rings The Return of the King (2003).mkv").write_text("video", encoding="utf-8")
            (source / "The Fellowship of the Ring (2001).mkv").write_text("video", encoding="utf-8")

            top_entries = [
                {"title": "The Empire Strikes Back", "year": 1980},
                {"title": "The Lord of the Rings: The Return of the King", "year": 2003},
                {"title": "The Lord of the Rings: The Fellowship of the Ring", "year": 2001},
            ] + [{"title": f"Filler {i}", "year": 2000 + i} for i in range(97)]

            def fake_http_get(url: str) -> dict[str, object]:
                if "/movie/top_rated" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 50,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in top_entries[start : start + 20]
                        ],
                    }
                if "/discover/movie" in url:
                    return {"page": 1, "total_pages": 1, "results": []}
                raise AssertionError(url)

            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    report = build_canonical_lists_report(
                        source,
                        standards={"canonical_list_provider": "tmdb"},
                        tmdb_key="test-key",
                        http_get=fake_http_get,
                    )
            top_100 = next(item for item in report.list_summaries if item.id == "top_100")
            self.assertEqual(top_100.covered_count, 3)
            self.assertEqual(top_100.missing_count, 97)

            empire = next(e for e in top_100.all_entries if "Empire" in e["title"])
            rotk = next(e for e in top_100.all_entries if "Return of the King" in e["title"])
            fellowship = next(e for e in top_100.all_entries if "Fellowship" in e["title"])
            self.assertTrue(empire["owned"])
            self.assertTrue(rotk["owned"])
            self.assertTrue(fellowship["owned"])
            self.assertIn("Empire Strikes Back", empire["path"])
            self.assertIn("Return of the King", rotk["path"])
            self.assertIn("Fellowship", fellowship["path"])

    def test_build_canonical_lists_report_matches_punctuation_light_local_title_via_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "K 19 The Widowmaker (2002)" / "K 19 The Widowmaker (2002).mkv").parent.mkdir(parents=True)
            (source / "K 19 The Widowmaker (2002)" / "K 19 The Widowmaker (2002).mkv").write_text("video", encoding="utf-8")

            top_entries = [{"title": "K-19: The Widowmaker", "year": 2002}] + [
                {"title": f"Filler {i}", "year": 2000 + i} for i in range(99)
            ]

            def fake_http_get(url: str) -> dict[str, object]:
                if "/movie/top_rated" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 50,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in top_entries[start : start + 20]
                        ],
                    }
                if "/discover/movie" in url:
                    return {"page": 1, "total_pages": 1, "results": []}
                raise AssertionError(url)

            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    report = build_canonical_lists_report(
                        source,
                        standards={"canonical_list_provider": "tmdb"},
                        tmdb_key="test-key",
                        http_get=fake_http_get,
                    )
            top_100 = next(item for item in report.list_summaries if item.id == "top_100")
            k19 = next(e for e in top_100.all_entries if e["title"] == "K-19: The Widowmaker")
            self.assertTrue(k19["owned"])
            self.assertIn("K 19 The Widowmaker", k19["path"])

    def test_build_canonical_lists_report_does_not_fabricate_imdb_id_for_tmdb_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Alien.1979.1080p.mkv").write_text("video", encoding="utf-8")

            top_entries = [{"title": "Alien", "year": 1979}] + [{"title": f"Top {i}", "year": 2000 + i} for i in range(2, 101)]

            def fake_http_get(url: str) -> dict[str, object]:
                if "/movie/top_rated" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 5,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in top_entries[start : start + 20]
                        ],
                    }
                if "/discover/movie" in url:
                    return {"page": 1, "total_pages": 1, "results": []}
                raise AssertionError(url)

            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    report = build_canonical_lists_report(
                        source,
                        standards={"canonical_list_provider": "tmdb"},
                        tmdb_key="test-key",
                        http_get=fake_http_get,
                    )
        top_100 = next(item for item in report.list_summaries if item.id == "top_100")
        alien = next(item for item in top_100.all_entries if item["title"] == "Alien")
        self.assertIsNone(alien.get("imdb_id"))

    def test_canonical_cache_round_trip_preserves_optional_imdb_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "entries.json"
            write_cache_entries(
                cache_path,
                [
                    CanonicalListEntry(title="Alien", year=1979, imdb_id="tt0078748"),
                    CanonicalListEntry(title="The Third Man", year=1949),
                ],
                fetched_at=1000.0,
            )

            cached = load_cache_entries(cache_path, now=lambda: 1000.0)

        self.assertIsNotNone(cached)
        entries = cached["entries"]
        self.assertEqual(entries[0].imdb_id, "tt0078748")
        self.assertIsNone(entries[1].imdb_id)

    def test_build_canonical_lists_report_matches_abbreviation_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "L A Confidential (1997)" / "L A Confidential (1997).mkv").parent.mkdir(parents=True)
            (source / "L A Confidential (1997)" / "L A Confidential (1997).mkv").write_text("video", encoding="utf-8")

            top_entries = [{"title": "L.A. Confidential", "year": 1997}] + [
                {"title": f"Filler {i}", "year": 2000 + i} for i in range(99)
            ]

            def fake_http_get(url: str) -> dict[str, object]:
                if "/movie/top_rated" in url:
                    page = int(url.split("page=")[1].split("&")[0])
                    start = (page - 1) * 20
                    return {
                        "page": page,
                        "total_pages": 50,
                        "results": [
                            {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                            for item in top_entries[start : start + 20]
                        ],
                    }
                if "/discover/movie" in url:
                    return {"page": 1, "total_pages": 1, "results": []}
                raise AssertionError(url)

            with tempfile.TemporaryDirectory() as data_home:
                with patch.dict(os.environ):
                    os.environ["XDG_DATA_HOME"] = data_home
                    report = build_canonical_lists_report(
                        source,
                        standards={"canonical_list_provider": "tmdb"},
                        tmdb_key="test-key",
                        http_get=fake_http_get,
                    )
            top_100 = next(item for item in report.list_summaries if item.id == "top_100")
            la_confidential = next(e for e in top_100.all_entries if e["title"] == "L.A. Confidential")
            self.assertTrue(la_confidential["owned"])
            self.assertIn("L A Confidential", la_confidential["path"])


if __name__ == "__main__":
    unittest.main()
