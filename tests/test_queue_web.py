from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from normal.audit import AuditStore
from normal.execution_queue import ExecutionQueueStore
from normal.quality_review import MediaFacts
from normal.source_policy import ApprovedRoots
from normal.web.security import MUTATION_TOKEN
from normal.web.server import build_handler
from normal.web.state import MovieEnrichedCache


WORKBENCH_HTML = (Path(__file__).resolve().parent.parent / "normal" / "web_assets" / "normalize_lab.html").read_text(encoding="utf-8")
WORKBENCH_JS = (Path(__file__).resolve().parent.parent / "normal" / "web_assets" / "normalize_lab.js").read_text(encoding="utf-8")


class QueueWorkbenchStringTests(unittest.TestCase):
    def test_workbench_surfaces_queue_status_line(self) -> None:
        self.assertIn('id="queueStatusLine"', WORKBENCH_HTML)
        self.assertIn("function renderQueueStatus()", WORKBENCH_JS)
        self.assertIn("function queueCountsLabel(counts)", WORKBENCH_JS)

    def test_workbench_reads_queue_status_per_lane_on_load(self) -> None:
        self.assertIn("function refreshQueueStatus(lane)", WORKBENCH_JS)
        self.assertIn("function refreshQueueStatusAllLanes()", WORKBENCH_JS)
        self.assertIn("refreshQueueStatus('movie')", WORKBENCH_JS)
        self.assertIn("refreshQueueStatus('tv')", WORKBENCH_JS)
        self.assertIn("'/api/normalize/queue/status'", WORKBENCH_JS)
        self.assertIn("await refreshQueueStatusAllLanes();", WORKBENCH_JS)

    def test_workbench_busy_phase_becomes_stop_affordance(self) -> None:
        self.assertIn("function stopDrain()", WORKBENCH_JS)
        self.assertIn("state.drainController.abort()", WORKBENCH_JS)
        self.assertIn("new AbortController()", WORKBENCH_JS)
        self.assertIn("signal: controller.signal", WORKBENCH_JS)
        self.assertIn("error?.name === 'AbortError'", WORKBENCH_JS)
        self.assertIn("if (state.drainInFlight) {", WORKBENCH_JS)
        self.assertIn("el.confirmButton.textContent = 'Stop';", WORKBENCH_JS)

    def test_workbench_stages_then_drains_alongside_direct_apply(self) -> None:
        self.assertIn("function stageAndDrainSelected()", WORKBENCH_JS)
        self.assertIn("function normalizeQueueLane()", WORKBENCH_JS)
        self.assertIn("'/api/normalize/queue/stage'", WORKBENCH_JS)
        self.assertIn("'/api/normalize/queue/drain'", WORKBENCH_JS)
        self.assertIn("isTvNormalizeMode() ? '/api/tv/apply' : '/api/movies/apply'", WORKBENCH_JS)


class QueueWebTests(unittest.TestCase):
    @contextmanager
    def harness(self, root: Path):
        cache = MovieEnrichedCache()
        audit_store = AuditStore(
            ledger_path=root / "audit-ledger.jsonl",
            replacement_queue_path=root / "missing-replacement-queue.json",
            subtitle_history_path=root / "missing-subtitle-history.json",
        )
        queue_store = ExecutionQueueStore(base_dir=root / "queue")
        with (
            patch("normal.web.routes_normalize.MOVIE_ENRICHED_CACHE", cache),
            patch("normal.web.routes_queue.MOVIE_ENRICHED_CACHE", cache),
            patch("normal.web.routes_normalize.AUDIT_STORE", audit_store),
            patch("normal.web.routes_audit.AUDIT_STORE", audit_store),
            patch("normal.web.routes_queue.EXECUTION_QUEUE_STORE", queue_store),
            patch("normal.web.routes_normalize.tracked_probe", return_value=lambda _: MediaFacts()),
            patch("normal.web.routes_queue.tracked_probe", return_value=lambda _: MediaFacts()),
            self.run_test_server(root) as base_url,
        ):
            yield base_url, cache, audit_store, queue_store

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

    def test_movie_stage_drain_status_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Movies"
            source.mkdir()
            (source / "Movie.2000.mkv").write_text("video", encoding="utf-8")

            with self.harness(root) as (base_url, cache, audit_store, queue_store):
                normalize_payload = self.post(base_url, "/api/movies/normalize", {"source": str(source)})
                change_ids = [change["item_id"] for change in normalize_payload["proposed_changes"]]
                self.assertTrue(change_ids)

                staged = self.post(
                    base_url,
                    "/api/normalize/queue/stage",
                    {"source": str(source), "change_ids": change_ids},
                )
                self.assertTrue(staged["exists"])
                self.assertEqual(staged["counts"]["pending"], len(staged["actions"]))

                with patch.object(cache, "invalidate", wraps=cache.invalidate) as invalidate:
                    drained = self.post(base_url, "/api/normalize/queue/drain", {"source": str(source)})

                self.assertEqual(drained["processed"], len(staged["actions"]))
                self.assertEqual(len(drained["applied"]), len(staged["actions"]))
                self.assertFalse(drained["stopped"])
                self.assertEqual(drained["counts"]["done"], len(staged["actions"]))
                invalidate.assert_called_with(source, lane="movie")

                status = self.post(base_url, "/api/normalize/queue/status", {"source": str(source)})
                self.assertEqual(status["counts"]["pending"], 0)

            self.assertTrue((source / "Movie (2000)" / "Movie (2000).mkv").exists())
            events = audit_store.read_events(source, limit=20)
            self.assertIn(("normalize", "apply"), [(e.workflow, e.action) for e in events])

    def test_tv_stage_drain_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "TV"
            episode = source / "Show" / "Show.S01E01.Pilot.1080p.mkv"
            episode.parent.mkdir(parents=True)
            episode.write_text("video", encoding="utf-8")

            with self.harness(root) as (base_url, cache, audit_store, queue_store):
                normalize_payload = self.post(base_url, "/api/tv/normalize", {"source": str(source), "lane": "tv"})
                change_ids = [change["item_id"] for change in normalize_payload["proposed_changes"]]

                staged = self.post(
                    base_url,
                    "/api/normalize/queue/stage",
                    {"source": str(source), "lane": "tv", "change_ids": change_ids},
                )
                self.assertEqual(staged["lane"], "tv")

                drained = self.post(
                    base_url,
                    "/api/normalize/queue/drain",
                    {"source": str(source), "lane": "tv"},
                )

            self.assertEqual(len(drained["applied"]), 1)
            self.assertTrue((source / "Show" / "Show - S01E01 - Pilot.mkv").exists())
            events = audit_store.read_events(source, limit=20)
            self.assertEqual(events[-1].metadata["lane"], "tv")
            self.assertEqual(events[-1].subjects[0].kind, "tv_change")

    def test_drain_without_staged_queue_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Movies"
            source.mkdir()
            (source / "Movie.2000.mkv").write_text("video", encoding="utf-8")

            with self.harness(root) as (base_url, cache, audit_store, queue_store):
                drained = self.post(base_url, "/api/normalize/queue/drain", {"source": str(source)})

            self.assertFalse(drained["exists"])
            self.assertEqual(drained["processed"], 0)
            self.assertTrue((source / "Movie.2000.mkv").exists())

    def test_stage_rejects_unapproved_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as other:
            root = Path(tmpdir)
            outside = Path(other)
            with self.harness(root) as (base_url, cache, audit_store, queue_store):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.post(
                        base_url,
                        "/api/normalize/queue/stage",
                        {"source": str(outside), "change_ids": []},
                    )
                self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
