from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_omdb import lookup_omdb_ratings


class MovieOmdbTests(unittest.TestCase):
    def test_punctuated_title_candidate_matches_k19(self) -> None:
        calls: list[dict[str, str]] = []

        def fake_get(params: dict[str, str]) -> dict:
            calls.append(params)
            if params.get("t") == "K-19: The Widowmaker":
                return {"Response": "True", "Title": "K-19: The Widowmaker", "Year": "2002", "imdbRating": "6.7", "imdbID": "tt0267626"}
            return {"Response": "False", "Error": "Movie not found!"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = lookup_omdb_ratings(
                [{"key": "k19", "title": "K 19 The Widowmaker", "year": 2002}],
                "key",
                http_get=fake_get,
                cache_dir=Path(tmpdir),
            )["items"][0]

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["rating"], 6.7)
        self.assertIn({"t": "K-19: The Widowmaker", "y": "2002"}, calls)

    def test_strips_unrated_edition_noise(self) -> None:
        def fake_get(params: dict[str, str]) -> dict:
            if params.get("t") == "Step Brothers":
                return {"Response": "True", "Title": "Step Brothers", "Year": "2008", "imdbRating": "6.9", "imdbID": "tt0838283"}
            return {"Response": "False", "Error": "Movie not found!"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = lookup_omdb_ratings(
                [{"key": "step", "title": "Step Brothers Unrated", "year": 2008}],
                "key",
                http_get=fake_get,
                cache_dir=Path(tmpdir),
            )["items"][0]

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["matched_title"], "Step Brothers")

    def test_search_fallback_matches_jurassic_park_two(self) -> None:
        def fake_get(params: dict[str, str]) -> dict:
            if params.get("i") == "tt0119567":
                return {
                    "Response": "True",
                    "Title": "The Lost World: Jurassic Park",
                    "Year": "1997",
                    "imdbRating": "6.6",
                    "imdbID": "tt0119567",
                }
            if params.get("s"):
                return {
                    "Response": "True",
                    "Search": [
                        {"Title": "The Lost World: Jurassic Park", "Year": "1997", "imdbID": "tt0119567", "Type": "movie"}
                    ],
                }
            return {"Response": "False", "Error": "Movie not found!"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = lookup_omdb_ratings(
                [{"key": "jp2", "title": "Jurassic Park II The Lost World", "year": 1997}],
                "key",
                http_get=fake_get,
                cache_dir=Path(tmpdir),
            )["items"][0]

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["rating"], 6.6)
        self.assertEqual(result["imdb_id"], "tt0119567")

    def test_search_fallback_matches_mummy_collection_noise(self) -> None:
        def fake_get(params: dict[str, str]) -> dict:
            if params.get("i") == "tt0859163":
                return {
                    "Response": "True",
                    "Title": "The Mummy: Tomb of the Dragon Emperor",
                    "Year": "2008",
                    "imdbRating": "5.2",
                    "imdbID": "tt0859163",
                }
            if params.get("s"):
                return {
                    "Response": "True",
                    "Search": [
                        {
                            "Title": "The Mummy: Tomb of the Dragon Emperor",
                            "Year": "2008",
                            "imdbID": "tt0859163",
                            "Type": "movie",
                        }
                    ],
                }
            return {"Response": "False", "Error": "Movie not found!"}

        with tempfile.TemporaryDirectory() as tmpdir:
            result = lookup_omdb_ratings(
                [{"key": "mummy3", "title": "The Mummy 3 Tomb Of The Dragon Emperor Action", "year": 2008}],
                "key",
                http_get=fake_get,
                cache_dir=Path(tmpdir),
            )["items"][0]

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["matched_title"], "The Mummy: Tomb of the Dragon Emperor")

    def test_api_limit_is_not_cached_as_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            calls = 0

            def limited_then_ok(params: dict[str, str]) -> dict:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return {"Response": "False", "Error": "Request limit reached!"}
                return {"Response": "True", "Title": "Ran", "Year": "1985", "imdbRating": "8.2", "imdbID": "tt0089881"}

            first = lookup_omdb_ratings(
                [{"key": "ran", "title": "Ran", "year": 1985}],
                "key",
                http_get=limited_then_ok,
                cache_dir=cache_dir,
            )["items"][0]
            second = lookup_omdb_ratings(
                [{"key": "ran", "title": "Ran", "year": 1985}],
                "key",
                http_get=limited_then_ok,
                cache_dir=cache_dir,
            )["items"][0]

            self.assertEqual(first["status"], "api_limited")
            self.assertEqual(second["status"], "matched")
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
