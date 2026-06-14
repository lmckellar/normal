from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from normal.audit import AuditStore
from normal.quality_review import MediaFacts
from normal.source_policy import ApprovedRoots
from normal.web.security import MUTATION_TOKEN
from normal.web.server import build_handler
from normal.web.state import MovieEnrichedCache


WORKBENCH_HTML = (Path(__file__).resolve().parent.parent / "normal" / "web_assets" / "normalize_lab.html").read_text(encoding="utf-8")
WORKBENCH_JS = (Path(__file__).resolve().parent.parent / "normal" / "web_assets" / "normalize_lab.js").read_text(encoding="utf-8")


class TvWebTests(unittest.TestCase):
    @contextmanager
    def run_test_server(self, root: Path):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            build_handler(approved_roots=ApprovedRoots.from_paths([root])),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def post(self, base_url: str, route: str, payload: dict[str, object]) -> dict[str, object]:
        request = urllib.request.Request(
            f"{base_url}{route}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Normal-Token": MUTATION_TOKEN},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_tv_normalize_and_apply_use_explicit_lane_cache_and_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "TV"
            episode = source / "Show" / "Show.S01E01.Pilot.1080p.mkv"
            episode.parent.mkdir(parents=True)
            episode.write_text("video", encoding="utf-8")
            movie_cache = MovieEnrichedCache()
            audit_store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )

            with (
                patch("normal.web.routes_normalize.MOVIE_ENRICHED_CACHE", movie_cache),
                patch("normal.web.routes_normalize.AUDIT_STORE", audit_store),
                patch("normal.web.routes_audit.AUDIT_STORE", audit_store),
                patch("normal.web.routes_normalize.tracked_probe", return_value=lambda _: MediaFacts()),
                patch.object(movie_cache, "invalidate", wraps=movie_cache.invalidate) as invalidate,
                self.run_test_server(root) as base_url,
            ):
                normalize_payload = self.post(base_url, "/api/tv/normalize", {"source": str(source)})
                change_ids = [change["item_id"] for change in normalize_payload["proposed_changes"]]
                apply_payload = self.post(
                    base_url,
                    "/api/tv/apply",
                    {"source": str(source), "change_ids": change_ids},
                )

            renamed = source / "Show" / "Show - S01E01 - Pilot.mkv"
            self.assertTrue(renamed.exists())
            self.assertEqual(len(apply_payload["applied"]), 1)
            self.assertIsNone(apply_payload["remaining_plan"])
            self.assertIn("tv_results", normalize_payload)
            self.assertIn("tv_files", normalize_payload)
            self.assertNotIn("movie_results", normalize_payload)
            invalidate.assert_called_once_with(source, lane="tv")
            self.assertIsNotNone(movie_cache.get(source, lane="tv"))
            self.assertIsNone(movie_cache.get(source, lane="movie"))

            events = audit_store.read_events(source, limit=10)
            self.assertEqual([(event.workflow, event.action) for event in events], [
                ("tv_normalize", "scan"),
                ("tv_normalize", "apply"),
            ])
            self.assertEqual(events[0].metadata["lane"], "tv")
            self.assertEqual(events[1].subjects[0].kind, "tv_change")
            self.assertEqual(events[1].metadata["applied_count"], 1)

    def test_tv_apply_does_not_invalidate_cache_when_review_change_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "TV"
            episode = source / "Show.S01E01.mkv"
            source.mkdir()
            episode.write_text("video", encoding="utf-8")
            cache = MovieEnrichedCache()
            audit_store = AuditStore(ledger_path=root / "audit-ledger.jsonl")

            with (
                patch("normal.web.routes_normalize.MOVIE_ENRICHED_CACHE", cache),
                patch("normal.web.routes_normalize.AUDIT_STORE", audit_store),
                patch("normal.web.routes_audit.AUDIT_STORE", audit_store),
                patch("normal.web.routes_normalize.tracked_probe", return_value=lambda _: MediaFacts()),
                patch.object(cache, "invalidate", wraps=cache.invalidate) as invalidate,
                self.run_test_server(root) as base_url,
            ):
                normalize_payload = self.post(base_url, "/api/tv/normalize", {"source": str(source)})
                apply_payload = self.post(
                    base_url,
                    "/api/tv/apply",
                    {
                        "source": str(source),
                        "change_ids": [normalize_payload["proposed_changes"][0]["item_id"]],
                    },
                )

            self.assertEqual(len(apply_payload["skipped"]), 1)
            self.assertTrue(episode.exists())
            invalidate.assert_not_called()

    def test_movie_normalize_payload_remains_movie_specific(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Movies"
            movie = source / "Movie.2000.mkv"
            source.mkdir()
            movie.write_text("video", encoding="utf-8")
            cache = MovieEnrichedCache()
            audit_store = AuditStore(ledger_path=root / "audit-ledger.jsonl")

            with (
                patch("normal.web.routes_normalize.MOVIE_ENRICHED_CACHE", cache),
                patch("normal.web.routes_normalize.AUDIT_STORE", audit_store),
                patch("normal.web.routes_audit.AUDIT_STORE", audit_store),
                patch("normal.web.routes_normalize.tracked_probe", return_value=lambda _: MediaFacts()),
                self.run_test_server(root) as base_url,
            ):
                payload = self.post(base_url, "/api/movies/normalize", {"source": str(source)})

        self.assertIn("movie_results", payload)
        self.assertIn("movie_files", payload)
        self.assertNotIn("tv_results", payload)
        self.assertNotIn("tv_files", payload)

    def test_workbench_exposes_explicit_tv_normalize_lane(self) -> None:
        self.assertIn('data-workflow="tv-normalize"', WORKBENCH_HTML)
        self.assertIn("if (workflow === 'tv-normalize'", WORKBENCH_JS)
        self.assertIn("isTvNormalizeMode() ? '/api/tv/normalize' : '/api/movies/normalize'", WORKBENCH_JS)
        self.assertIn("isTvNormalizeMode() ? '/api/tv/apply' : '/api/movies/apply'", WORKBENCH_JS)
        self.assertIn("state.normalizePayload?.tv_results", WORKBENCH_JS)
        self.assertIn("state.normalizePayload?.movie_results", WORKBENCH_JS)

    def test_workbench_tv_rows_render_identity_warnings_and_change_records(self) -> None:
        self.assertIn("const TV_NORMALIZE_HEADERS = [", WORKBENCH_JS)
        for field in ("series", "season", "episode_first", "episode_last", "absolute_episode", "numbering", "identity_confidence"):
            self.assertIn(field, WORKBENCH_JS)
        self.assertIn("function tvWarningsLabel(row)", WORKBENCH_JS)
        self.assertIn("row.warning_messages", WORKBENCH_JS)
        self.assertIn("row.reason_messages", WORKBENCH_JS)
        self.assertIn("function tvChangesLabel(row)", WORKBENCH_JS)
        self.assertIn("row.linked_changes", WORKBENCH_JS)


if __name__ == "__main__":
    unittest.main()
