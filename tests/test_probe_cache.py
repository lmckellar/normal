from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from normal.probe_cache import ProbeCache
from normal.quality_review import MediaFacts


class ProbeCacheTests(unittest.TestCase):
    def test_ignores_cache_entries_from_older_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "probe-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "version": ProbeCache._VERSION - 1,
                        "entries": {
                            "ignored": {
                                "width": 1440,
                                "height": 1080,
                                "sample_aspect_ratio": "4:3",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            original_path = ProbeCache._PATH
            try:
                ProbeCache._PATH = cache_path
                cache = ProbeCache()
                movie_path = Path(tmpdir) / "Movie.mkv"
                movie_path.write_bytes(b"x")

                self.assertIsNone(cache.get(movie_path))
            finally:
                ProbeCache._PATH = original_path

    def test_round_trips_new_aspect_ratio_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "probe-cache.json"
            original_path = ProbeCache._PATH
            try:
                ProbeCache._PATH = cache_path
                cache = ProbeCache()
                movie_path = Path(tmpdir) / "Movie.mkv"
                movie_path.write_bytes(b"x")
                facts = MediaFacts(width=1440, height=1080, sample_aspect_ratio="4:3", display_aspect_ratio="16:9")

                cache.put(movie_path, facts)
                cached = cache.get(movie_path)

                self.assertIsNotNone(cached)
                assert cached is not None
                self.assertEqual(cached.sample_aspect_ratio, "4:3")
                self.assertEqual(cached.display_aspect_ratio, "16:9")
            finally:
                ProbeCache._PATH = original_path

    def test_has_entries_reflects_persisted_cache_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "probe-cache.json"
            original_path = ProbeCache._PATH
            try:
                ProbeCache._PATH = cache_path
                cache = ProbeCache()
                self.assertFalse(cache.has_entries())

                movie_path = Path(tmpdir) / "Movie.mkv"
                movie_path.write_bytes(b"x")
                cache.put(movie_path, MediaFacts(width=1920, height=1080))
                cache.flush()

                fresh_cache = ProbeCache()
                self.assertTrue(fresh_cache.has_entries())
            finally:
                ProbeCache._PATH = original_path

    def test_put_batches_writes_until_flush(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "probe-cache.json"
            original_path = ProbeCache._PATH
            original_every = ProbeCache._FLUSH_EVERY
            original_interval = ProbeCache._FLUSH_INTERVAL_S
            try:
                ProbeCache._PATH = cache_path
                # Force pure count-based batching, well above the writes below.
                ProbeCache._FLUSH_EVERY = 1000
                ProbeCache._FLUSH_INTERVAL_S = 3600.0
                cache = ProbeCache()
                for index in range(3):
                    movie_path = Path(tmpdir) / f"Movie{index}.mkv"
                    movie_path.write_bytes(b"x")
                    cache.put(movie_path, MediaFacts(width=1920, height=1080))

                # Below the flush threshold: nothing on disk yet, but readable in-memory.
                self.assertFalse(cache_path.exists())
                self.assertFalse(ProbeCache().has_entries())

                cache.flush()
                self.assertTrue(cache_path.exists())
                self.assertTrue(ProbeCache().has_entries())
            finally:
                ProbeCache._PATH = original_path
                ProbeCache._FLUSH_EVERY = original_every
                ProbeCache._FLUSH_INTERVAL_S = original_interval


if __name__ == "__main__":
    unittest.main()
