from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_canonical_lists import build_canonical_lists_report


class MovieCanonicalListsTests(unittest.TestCase):
    def test_build_canonical_lists_report_dedupes_library_and_unlocks_badges(self) -> None:
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
                import os

                previous = os.environ.get("XDG_DATA_HOME")
                os.environ["XDG_DATA_HOME"] = data_home
                try:
                    report = build_canonical_lists_report(source, tmdb_key="test-key", http_get=fake_http_get)
                finally:
                    if previous is None:
                        os.environ.pop("XDG_DATA_HOME", None)
                    else:
                        os.environ["XDG_DATA_HOME"] = previous

            self.assertEqual(report.library_summary.owned_movies, 2)
            self.assertEqual(report.library_summary.unparsed_files, 1)
            self.assertEqual(report.library_summary.duplicate_files, 1)
            self.assertEqual(report.provider, "tmdb")
            self.assertEqual(report.cache_state, "live")

            top_100 = next(item for item in report.list_summaries if item.id == "top_100")
            self.assertEqual(top_100.covered_count, 2)
            self.assertEqual(top_100.total_count, 100)
            self.assertEqual(top_100.missing_count, 98)

            top_1000 = next(item for item in report.list_summaries if item.id == "top_1000")
            self.assertEqual(top_1000.covered_count, 2)
            self.assertEqual(top_1000.total_count, 1000)

            sci_fi_badge = next(item for item in report.badges if item.id == "sci_fi")
            self.assertFalse(sci_fi_badge.unlocked)
            self.assertEqual(sci_fi_badge.coverage_percent, 1.0)

    def test_build_canonical_lists_report_uses_stale_cache_on_fetch_failure(self) -> None:
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
                self.addCleanup(lambda: None)
                import os

                previous = os.environ.get("XDG_DATA_HOME")
                os.environ["XDG_DATA_HOME"] = data_home
                try:
                    build_canonical_lists_report(source, tmdb_key="test-key", http_get=fake_http_get, now=lambda: 1000.0)
                    stale_report = build_canonical_lists_report(
                        source,
                        tmdb_key="test-key",
                        http_get=lambda _url: (_ for _ in ()).throw(TimeoutError("boom")),
                        now=lambda: 1000.0 + (8 * 24 * 60 * 60),
                    )
                finally:
                    if previous is None:
                        os.environ.pop("XDG_DATA_HOME", None)
                    else:
                        os.environ["XDG_DATA_HOME"] = previous

            self.assertEqual(stale_report.cache_state, "stale")


    def test_franchise_prefix_and_subtitle_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            # File has franchise prefix; TMDb has no colon prefix (real ESB case)
            (source / "Star Wars Episode V The Empire Strikes Back (1980).mkv").write_text("video", encoding="utf-8")
            # TMDb uses "Franchise: Subtitle"; local file has exact match via colon normalization
            (source / "The Lord of the Rings The Return of the King (2003).mkv").write_text("video", encoding="utf-8")
            # TMDb uses "Franchise: Subtitle"; local file is subtitle-only
            (source / "The Fellowship of the Ring (2001).mkv").write_text("video", encoding="utf-8")

            top_entries = [
                # TMDb has no colon; file has franchise prefix words before the title
                {"title": "The Empire Strikes Back", "year": 1980},
                # TMDb colon normalizes away; file title matches exactly
                {"title": "The Lord of the Rings: The Return of the King", "year": 2003},
                # TMDb colon subtitle; file is subtitle-only
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
                import os

                previous = os.environ.get("XDG_DATA_HOME")
                os.environ["XDG_DATA_HOME"] = data_home
                try:
                    report = build_canonical_lists_report(source, tmdb_key="test-key", http_get=fake_http_get)
                finally:
                    if previous is None:
                        os.environ.pop("XDG_DATA_HOME", None)
                    else:
                        os.environ["XDG_DATA_HOME"] = previous

            top_100 = next(item for item in report.list_summaries if item.id == "top_100")
            self.assertEqual(top_100.covered_count, 3)
            self.assertEqual(top_100.missing_count, 97)

            empire = next(e for e in top_100.all_entries if "Empire" in e["title"])
            rotk = next(e for e in top_100.all_entries if "Return of the King" in e["title"])
            fellowship = next(e for e in top_100.all_entries if "Fellowship" in e["title"])
            self.assertTrue(empire["owned"], "ESB should match via suffix (file has franchise prefix, TMDb does not)")
            self.assertTrue(rotk["owned"], "LOTR ROTK should match via colon normalization")
            self.assertTrue(fellowship["owned"], "LOTR Fellowship should match via TMDb subtitle fallback")
            self.assertIn("Empire Strikes Back", empire["path"])
            self.assertIn("Return of the King", rotk["path"])
            self.assertIn("Fellowship", fellowship["path"])


if __name__ == "__main__":
    unittest.main()
