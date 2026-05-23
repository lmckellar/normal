from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from normal.web.activity import (
    ActivityTracker,
    build_activity_payload,
    find_external_activity,
    summarize_process_args,
    tracked_probe,
)


class WebActivityTests(unittest.TestCase):
    def test_activity_tracker_snapshot_filters_to_overlapping_source(self) -> None:
        tracker = ActivityTracker()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Movies"
            other = root / "Music"
            movie = source / "Movie.mkv"
            song = other / "Song.mp3"
            source.mkdir()
            other.mkdir()
            movie.write_text("movie", encoding="utf-8")
            song.write_text("song", encoding="utf-8")

            movie_id = tracker.start(source, "Movie probe", kind="probe", current_path=movie)
            tracker.start(other, "Song probe", kind="probe", current_path=song)

            items = tracker.snapshot(source)

        self.assertEqual([item["id"] for item in items], [movie_id])
        self.assertEqual(items[0]["current_path"], str(movie.resolve()))

    def test_activity_tracker_update_normalizes_paths(self) -> None:
        tracker = ActivityTracker()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.mkv"
            output = source / "out" / "Movie.tmp.mkv"
            movie.write_text("movie", encoding="utf-8")
            output.parent.mkdir()

            item_id = tracker.start(source, "Movie remux", kind="remux")
            tracker.update(item_id, current_path=movie, output_path=output, status_text="running")

            items = tracker.snapshot(source)

        self.assertEqual(items[0]["current_path"], str(movie.resolve()))
        self.assertEqual(items[0]["output_path"], str(output.resolve()))
        self.assertEqual(items[0]["status_text"], "running")

    def test_tracked_probe_uses_cache_before_probng(self) -> None:
        class Cache:
            def __init__(self) -> None:
                self.put_calls: list[tuple[Path, object]] = []

            def get(self, path: Path) -> object | None:
                return {"path": str(path)}

            def put(self, path: Path, facts: object) -> None:
                self.put_calls.append((path, facts))

        cache = Cache()
        probe = tracked_probe(Path("/library"), "ffprobe", cache=cache)

        with patch("normal.web.activity.probe_media_facts") as probe_media_facts:
            result = probe(Path("/library/Movie.mkv"))

        self.assertEqual(result, {"path": "/library/Movie.mkv"})
        probe_media_facts.assert_not_called()
        self.assertEqual(cache.put_calls, [])

    def test_tracked_probe_tracks_and_caches_fresh_probe(self) -> None:
        class Cache:
            def __init__(self) -> None:
                self.values: dict[Path, object] = {}

            def get(self, path: Path) -> object | None:
                return self.values.get(path)

            def put(self, path: Path, facts: object) -> None:
                self.values[path] = facts

        tracker = ActivityTracker()
        cache = Cache()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.mkv"
            movie.write_text("movie", encoding="utf-8")
            probe = tracked_probe(source, "ffprobe metadata", cache=cache)

            with patch("normal.web.activity.state.ACTIVITY_TRACKER", tracker):
                with patch("normal.web.activity.probe_media_facts", return_value={"streams": 1}) as probe_media_facts:
                    result = probe(movie)

        self.assertEqual(result, {"streams": 1})
        probe_media_facts.assert_called_once_with(movie)
        self.assertEqual(cache.values[movie], {"streams": 1})
        self.assertEqual(tracker.snapshot(source), [])

    def test_build_activity_payload_skips_external_when_app_activity_exists(self) -> None:
        tracker = ActivityTracker()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.mkv"
            movie.write_text("movie", encoding="utf-8")

            with tracker.track(source, "Movie audio fix", kind="remux", current_path=movie):
                with patch("normal.web.activity.state.ACTIVITY_TRACKER", tracker):
                    with patch("normal.web.activity.find_external_activity") as find_external:
                        payload = build_activity_payload(source)

        find_external.assert_not_called()
        self.assertTrue(payload["active"])
        self.assertEqual(payload["external"], [])
        self.assertEqual(payload["probes"], [])

    def test_build_activity_payload_uses_external_when_idle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            external = [{"pid": 123, "ppid": 1, "command": "ffprobe", "summary": "ffprobe Movie.mkv"}]

            with patch("normal.web.activity.find_external_activity", return_value=(external, None)) as find_external:
                payload = build_activity_payload(source)

        find_external.assert_called_once_with(source)
        self.assertTrue(payload["active"])
        self.assertEqual(payload["app"], [])
        self.assertEqual(payload["external"], external)

    def test_find_external_activity_filters_relevant_processes(self) -> None:
        source = Path("/srv/media").resolve()
        ps_output = "\n".join(
            [
                "111 1 ffprobe ffprobe -v error /srv/media/Movie.mkv",
                "222 1 bash bash -lc normal scan /srv/media",
                "333 1 python python -m normal scan /srv/media",
                "444 1 sleep sleep 10",
            ]
        )
        completed = CompletedProcess(args=[], returncode=0, stdout=ps_output, stderr="")

        with patch("normal.web.activity.os.getpid", return_value=999):
            with patch("normal.web.activity.subprocess.run", return_value=completed):
                matches, note = find_external_activity(source)

        self.assertIsNone(note)
        self.assertEqual([item["pid"] for item in matches], [111, 333])
        self.assertEqual(matches[1]["command"], "python")

    def test_summarize_process_args_truncates_long_values(self) -> None:
        args = "x" * 220

        summary = summarize_process_args(args)

        self.assertEqual(len(summary), 180)
        self.assertTrue(summary.endswith("..."))


if __name__ == "__main__":
    unittest.main()
