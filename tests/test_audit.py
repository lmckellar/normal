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

from normal.audit import AuditEvent, AuditFollowUpUpdate, AuditStore
from normal.models import utc_now_iso
from normal.movie_canonical_lists import CanonicalLibrarySummary, CanonicalListsReport
from normal.web import build_handler


class AuditStoreTests(unittest.TestCase):
    def test_repeated_reads_reuse_cached_ledger_state_until_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            store.append(
                AuditEvent(
                    event_id="event-1",
                    recorded_at="2026-01-01T00:00:00+00:00",
                    source_root=str(source.resolve()),
                    workflow="audit",
                    action="start",
                    summary="Started normal web UI.",
                    follow_up_updates=[
                        AuditFollowUpUpdate(
                            follow_up_id="followup-1",
                            kind="replacement",
                            action="create",
                            status="active",
                            summary="Replacement follow-up created.",
                            details={"path": str(source.resolve()), "title": "Movie"},
                        )
                    ],
                )
            )
            original_read_text = Path.read_text
            read_count = 0

            def counting_read_text(path: Path, *args: object, **kwargs: object) -> str:
                nonlocal read_count
                if path == store._ledger_path:
                    read_count += 1
                return original_read_text(path, *args, **kwargs)

            with patch.object(Path, "read_text", autospec=True, side_effect=counting_read_text):
                first_events = store.read_events(source, limit=10)
                second_events = store.read_events(source, limit=10)
                first_followups = store.read_followups(source, status="")
                second_followups = store.read_followups(source, status="")

                store.append(
                    AuditEvent(
                        event_id="event-2",
                        recorded_at="2026-01-01T00:01:00+00:00",
                        source_root=str(source.resolve()),
                        workflow="audit",
                        action="follow_up_resolve",
                        summary="Resolved replacement follow-up.",
                        follow_up_updates=[
                            AuditFollowUpUpdate(
                                follow_up_id="followup-1",
                                kind="replacement",
                                action="resolve",
                                status="resolved",
                                summary="Replacement follow-up resolved.",
                                details={"path": str(source.resolve()), "title": "Movie"},
                            )
                        ],
                    )
                )
                post_append_events = store.read_events(source, limit=10)
                post_append_followups = store.read_followups(source, status="")

        self.assertEqual([event.event_id for event in first_events], ["event-1"])
        self.assertEqual([event.event_id for event in second_events], ["event-1"])
        self.assertEqual([item.status for item in first_followups], ["active"])
        self.assertEqual([item.status for item in second_followups], ["active"])
        self.assertEqual([event.event_id for event in post_append_events], ["event-1", "event-2"])
        self.assertEqual([item.status for item in post_append_followups], ["resolved"])
        self.assertEqual(read_count, 2)

    def test_migrates_legacy_queue_and_subtitle_history_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            ledger = root / "audit-ledger.jsonl"
            queue = root / "movie-replacement-queue.json"
            subtitle = root / "subtitle-fix-history.json"
            source = root / "movies"
            source.mkdir()
            movie = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            movie.parent.mkdir()
            movie.write_text("video", encoding="utf-8")
            queue.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "items": [
                            {
                                "item_id": "queue-1",
                                "source_root": str(source.resolve()),
                                "title": "Bad Movie",
                                "year": 2001,
                                "original_path": str(movie.resolve()),
                                "issue_family": "weak_encode",
                                "queued_at": "2026-01-01T00:00:00+00:00",
                                "status": "dismissed",
                                "deleted_at": "2026-01-02T00:00:00+00:00",
                                "dismissed_at": "2026-01-03T00:00:00+00:00",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            subtitle.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "items": [
                            {
                                "item_id": "sub-1",
                                "source_root": str(source.resolve()),
                                "path": str(movie.resolve()),
                                "title": "Bad Movie",
                                "year": 2001,
                                "issue_code": "english_missing",
                                "recorded_at": "2026-01-04T00:00:00+00:00",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            store = AuditStore(ledger_path=ledger, replacement_queue_path=queue, subtitle_history_path=subtitle)

            first_events = store.read_events(source, limit=20)
            second_events = store.read_events(source, limit=20)
            replacement_followups = store.read_followups(source, kind="replacement", status="")
            review_followups = store.read_followups(source, kind="repair_review", status="")

        self.assertEqual(len(first_events), len(second_events))
        self.assertEqual([event.action for event in first_events], ["legacy_queue_import", "delete", "replacement_dismissed", "legacy_repair_review_import"])
        self.assertEqual(replacement_followups[0].status, "dismissed")
        self.assertEqual(review_followups[0].status, "active")

    def test_read_followups_derives_active_after_delete_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            movie = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            movie.parent.mkdir()
            movie.write_text("video", encoding="utf-8")
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            with patch("normal.web.routes_cleanup.AUDIT_STORE", store):
                from normal.web.routes_cleanup import _record_media_delete_event

                _record_media_delete_event(
                    source,
                    {
                        "deleted": [str(movie.resolve())],
                        "cleaned_sidecars": [],
                        "removed_folders": [],
                        "skipped": [],
                    },
                    issue_family="weak_encode",
                )

            followups = store.read_followups(source, kind="replacement")

        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0].status, "active")
        self.assertEqual(followups[0].subject["title"], "Bad Movie")

    def test_read_followups_respects_append_order_for_same_second_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            recorded_at = "2026-01-01T00:00:00+00:00"
            store.append_batch(
                [
                    AuditEvent(
                        event_id="create-1",
                        recorded_at=recorded_at,
                        source_root=str(source.resolve()),
                        workflow="audit",
                        action="follow_up_create",
                        summary="Created follow-up.",
                        follow_up_updates=[
                            AuditFollowUpUpdate(
                                follow_up_id="follow-1",
                                kind="replacement",
                                action="create",
                                status="active",
                                summary="Awaiting replacement.",
                                details={"path": str(source / "Bad Movie.mkv"), "title": "Bad Movie"},
                            )
                        ],
                    ),
                    AuditEvent(
                        event_id="dismiss-1",
                        recorded_at=recorded_at,
                        source_root=str(source.resolve()),
                        workflow="audit",
                        action="follow_up_dismiss",
                        summary="Dismissed follow-up.",
                        follow_up_updates=[
                            AuditFollowUpUpdate(
                                follow_up_id="follow-1",
                                kind="replacement",
                                action="dismiss",
                                status="dismissed",
                                summary="Handled.",
                                details={},
                            )
                        ],
                    ),
                ]
            )

            followups = store.read_followups(source, kind="replacement", status="")

        self.assertEqual(len(followups), 1)
        self.assertEqual(followups[0].status, "dismissed")


class AuditRouteTests(unittest.TestCase):
    @contextmanager
    def run_test_server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler())
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_normalize_scan_and_apply_write_audit_events_and_read_endpoint_returns_them(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            folder = source / "Messy Folder"
            folder.mkdir()
            movie = folder / "The.Matrix.1999.1080p.bluray.x264-GRP.mkv"
            movie.write_text("video", encoding="utf-8")
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
                patch("normal.web.routes_cleanup.AUDIT_STORE", store),
                patch("normal.web.routes_normalize.AUDIT_STORE", store),
            ]
            for mocked in patches:
                mocked.start()
            try:
                with self.run_test_server() as base_url:
                    normalize_request = urllib.request.Request(
                        f"{base_url}/api/movies/normalize",
                        data=json.dumps({"source": str(source)}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(normalize_request) as response:
                        normalize_payload = json.loads(response.read().decode("utf-8"))
                    apply_request = urllib.request.Request(
                        f"{base_url}/api/movies/apply",
                        data=json.dumps({"source": str(source), "changes": normalize_payload["proposed_changes"]}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(apply_request) as response:
                        apply_payload = json.loads(response.read().decode("utf-8"))
                    audit_request = urllib.request.Request(
                        f"{base_url}/api/audit/read",
                        data=json.dumps({"source": str(source), "limit": 10}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(audit_request) as response:
                        audit_payload = json.loads(response.read().decode("utf-8"))
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

        self.assertEqual(len(apply_payload["applied"]), 2)
        self.assertEqual(len(audit_payload["events"]), 2)
        events_by_action = {event["action"]: event for event in audit_payload["events"]}
        self.assertEqual(set(events_by_action), {"scan", "apply"})
        self.assertEqual(events_by_action["scan"]["workflow"], "normalize")
        self.assertEqual(events_by_action["scan"]["summary"], "Performed Movie normalize plan.")
        self.assertEqual(events_by_action["apply"]["workflow"], "normalize")
        self.assertEqual(events_by_action["apply"]["reversal"]["capability"], "recorded_only")

    def test_follow_up_update_route_resolves_active_follow_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            movie = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            movie.parent.mkdir()
            movie.write_text("video", encoding="utf-8")
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
                patch("normal.web.routes_cleanup.AUDIT_STORE", store),
            ]
            for mocked in patches:
                mocked.start()
            try:
                from normal.web.routes_cleanup import _record_media_delete_event

                _record_media_delete_event(
                    source,
                    {
                        "deleted": [str(movie.resolve())],
                        "cleaned_sidecars": [],
                        "removed_folders": [],
                        "skipped": [],
                    },
                    issue_family="weak_encode",
                )
                active = store.read_followups(source, kind="replacement")
                self.assertEqual(len(active), 1)
                with self.run_test_server() as base_url:
                    update_request = urllib.request.Request(
                        f"{base_url}/api/audit/follow-up/update",
                        data=json.dumps(
                            {
                                "source": str(source),
                                "follow_up_id": active[0].follow_up_id,
                                "action": "mark_handled",
                            }
                        ).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(update_request) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

        self.assertEqual(payload["event"]["action"], "follow_up_mark_handled")
        self.assertEqual(payload["active_followups"], [])

    def test_policy_update_route_writes_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
            ]
            for mocked in patches:
                mocked.start()
            try:
                with patch(
                    "normal.web.routes_profile.update_policy_definition",
                    return_value=({"replacement_candidate_rules": {}}, {"delete_mode": "recycle_all"}),
                ):
                    with self.run_test_server() as base_url:
                        request = urllib.request.Request(
                            f"{base_url}/api/policy/update",
                            data=json.dumps(
                                {
                                    "source": str(source),
                                    "label": "Replacement Candidate Rules",
                                    "values": {"quality_profile_floor": "Standard"},
                                }
                            ).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(request):
                            pass
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

            events = store.read_events(source, limit=10)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].workflow, "policy")
        self.assertEqual(events[0].action, "update")
        self.assertEqual(events[0].summary, "Updated policy definition Replacement Candidate Rules.")

    def test_default_source_policy_update_without_source_skips_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
            ]
            for mocked in patches:
                mocked.start()
            try:
                with patch(
                    "normal.web.routes_profile.update_policy_definition",
                    return_value=({"replacement_candidate_rules": {}}, {"delete_mode": "recycle_all", "default_source": "~/Movies"}),
                ):
                    with self.run_test_server() as base_url:
                        request = urllib.request.Request(
                            f"{base_url}/api/policy/update",
                            data=json.dumps(
                                {
                                    "label": "default_source",
                                    "values": {"default_source": "~/Movies"},
                                }
                            ).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(request) as response:
                            payload = json.loads(response.read().decode("utf-8"))
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

            events = store.read_events_for_sources([], limit=10)

        self.assertEqual(payload["operator_preferences"]["default_source"], "~/Movies")
        self.assertEqual(events, [])

    def test_movie_catalogue_export_writes_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            movie = source / "The Matrix (1999).mkv"
            movie.write_text("video", encoding="utf-8")
            store = AuditStore(ledger_path=root / "audit-ledger.jsonl")
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
            ]
            for mocked in patches:
                mocked.start()
            try:
                with self.run_test_server() as base_url:
                    request = urllib.request.Request(
                        f"{base_url}/api/movies/register",
                        data=json.dumps({"source": str(source)}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        payload = response.read()
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

            events = store.read_events(source, limit=10)

        self.assertTrue(payload)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].workflow, "catalogue")
        self.assertEqual(events[0].action, "export")
        self.assertEqual(events[0].summary, "Exported movie catalogue.")

    def test_movie_profile_cached_run_writes_cached_scan_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            movie = source / "The Matrix (1999).mkv"
            movie.write_text("video", encoding="utf-8")
            store = AuditStore(ledger_path=root / "audit-ledger.jsonl")
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
            ]
            for mocked in patches:
                mocked.start()
            try:
                with self.run_test_server() as base_url:
                    request = urllib.request.Request(
                        f"{base_url}/api/movies/profile",
                        data=json.dumps({"source": str(source)}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request):
                        pass
                    with urllib.request.urlopen(request):
                        pass
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

            events = store.read_events(source, limit=10)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].workflow, "profile")
        self.assertEqual(events[0].action, "scan")
        self.assertEqual(events[0].summary, "Performed Movie profile scan.")
        self.assertEqual(events[0].effects[0].status, "applied")
        self.assertEqual(events[0].metadata["cache_hit"], False)
        self.assertEqual(events[1].workflow, "profile")
        self.assertEqual(events[1].action, "scan")
        self.assertEqual(events[1].summary, "Reused cached Movie profile scan.")
        self.assertEqual(events[1].effects[0].status, "cached")
        self.assertEqual(events[1].metadata["cache_hit"], True)

    def test_movie_canonical_lists_cached_run_writes_cached_scan_audit_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(ledger_path=root / "audit-ledger.jsonl")
            report = CanonicalListsReport(
                source_root=str(source.resolve()),
                generated_at=utc_now_iso(),
                provider="imdb",
                cache_state="live",
                library_summary=CanonicalLibrarySummary(
                    owned_movies=0,
                    matched_canonical_titles=0,
                    lists_cleared=0,
                    unparsed_files=0,
                    duplicate_files=0,
                ),
                canonical_status={"ready": True},
            )
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
                patch("normal.web.routes_profile.AUDIT_STORE", store),
                patch("normal.web.routes_profile.build_canonical_lists_report", return_value=report),
            ]
            for mocked in patches:
                mocked.start()
            try:
                with self.run_test_server() as base_url:
                    request = urllib.request.Request(
                        f"{base_url}/api/movies/canonical-lists",
                        data=json.dumps({"source": str(source)}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request):
                        pass
                    with urllib.request.urlopen(request):
                        pass
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

            events = store.read_events(source, limit=10, workflow="canonical_lists")

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].summary, "Performed Movie canonical lists.")
        self.assertEqual(events[0].effects[0].status, "applied")
        self.assertEqual(events[0].metadata["cache_hit"], False)
        self.assertEqual(events[1].summary, "Reused cached Movie canonical lists.")
        self.assertEqual(events[1].effects[0].status, "cached")
        self.assertEqual(events[1].metadata["cache_hit"], True)

    def test_audit_read_includes_system_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(ledger_path=root / "audit-ledger.jsonl")
            patches = [
                patch("normal.web.state.AUDIT_STORE", store),
                patch("normal.web.routes_audit.AUDIT_STORE", store),
            ]
            for mocked in patches:
                mocked.start()
            try:
                from normal.web.routes_audit import record_scan_event, record_system_event

                record_system_event(action="start", summary="Started normal web UI.")
                record_scan_event(source, workflow="canonical_lists", label="Movie canonical lists")
                with self.run_test_server() as base_url:
                    request = urllib.request.Request(
                        f"{base_url}/api/audit/read",
                        data=json.dumps({"source": str(source), "limit": 10}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request) as response:
                        payload = json.loads(response.read().decode("utf-8"))
            finally:
                for mocked in reversed(patches):
                    mocked.stop()

        actions = [event["action"] for event in payload["events"]]
        self.assertEqual(actions, ["start", "scan"])
        self.assertEqual(payload["events"][0]["workflow"], "system")
        self.assertEqual(payload["events"][0]["action"], "start")
        self.assertIn("ledger_revision", payload)
        self.assertGreaterEqual(payload["ledger_revision"], 1)
        self.assertIn("latest_event_id", payload)
        self.assertTrue(payload["latest_event_id"])
        self.assertEqual(payload["latest_event_id"], payload["events"][-1]["event_id"])
        self.assertIn("latest_system_start", payload)
        self.assertIsNotNone(payload["latest_system_start"])
        self.assertEqual(payload["latest_system_start"]["workflow"], "system")
        self.assertEqual(payload["latest_system_start"]["action"], "start")
        self.assertIn("read_at", payload)
        self.assertTrue(payload["read_at"])

    def test_audit_store_revision_advances_with_appends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            first_revision = store.revision
            store.append(
                AuditEvent(
                    event_id="event-1",
                    recorded_at="2026-01-01T00:00:00+00:00",
                    source_root=str(source.resolve()),
                    workflow="audit",
                    action="start",
                    summary="Started normal web UI.",
                )
            )
            second_revision = store.revision

        self.assertEqual(first_revision, 0)
        self.assertEqual(second_revision, 1)

    def test_audit_store_revision_subscription_reports_changed_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "movies"
            source.mkdir()
            store = AuditStore(
                ledger_path=root / "audit-ledger.jsonl",
                replacement_queue_path=root / "missing-replacement-queue.json",
                subtitle_history_path=root / "missing-subtitle-history.json",
            )
            subscriber = store.subscribe_revisions()
            try:
                store.append(
                    AuditEvent(
                        event_id="event-1",
                        recorded_at="2026-01-01T00:00:00+00:00",
                        source_root=str(source.resolve()),
                        workflow="audit",
                        action="update",
                        summary="Recorded change.",
                    )
                )
                notice = subscriber.get(timeout=1)
            finally:
                store.unsubscribe_revisions(subscriber)

        self.assertEqual(notice.revision, 1)
        self.assertEqual(notice.source_roots, [str(source.resolve())])
        self.assertEqual(notice.recorded_at, "2026-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
