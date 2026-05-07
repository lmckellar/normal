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


if __name__ == "__main__":
    unittest.main()
