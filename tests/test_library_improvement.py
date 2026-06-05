from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from normal.audit import AuditEvent, AuditStore
from normal.library_improvement import build_library_improvement_payload
from normal.movie_profile import MovieProfileReport


class LibraryImprovementTests(unittest.TestCase):
    def test_build_library_improvement_payload_aggregates_removals_and_canonical_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            for index in range(1, 16):
                (source / f"Top Movie {index} ({2000 + index}).mkv").write_text("video", encoding="utf-8")
            report = MovieProfileReport(
                source_root=str(source),
                generated_at="2026-06-04T00:00:00+00:00",
                movies=[
                    SimpleNamespace(
                        path=str(source / f"Top Movie {index} ({2000 + index}).mkv"),
                        profile=SimpleNamespace(quality_label="library_grade"),
                    )
                    for index in range(1, 16)
                ],
            )
            store = AuditStore(ledger_path=source / "audit-ledger.jsonl")
            store.append_batch(
                [
                    AuditEvent(
                        event_id="scan-1",
                        recorded_at="2026-06-01T00:00:00+00:00",
                        source_root=str(source.resolve()),
                        workflow="profile",
                        action="scan",
                        summary="First profile scan.",
                        metadata={"canonical_top_500_above_floor_count": 5},
                    ),
                    AuditEvent(
                        event_id="scan-2",
                        recorded_at="2026-06-02T00:00:00+00:00",
                        source_root=str(source.resolve()),
                        workflow="canonical_lists",
                        action="scan",
                        summary="Canonical scan.",
                    ),
                    AuditEvent(
                        event_id="delete-1",
                        recorded_at="2026-06-03T00:00:00+00:00",
                        source_root=str(source.resolve()),
                        workflow="weak_encode",
                        action="delete",
                        summary="Deleted weak files.",
                        metadata={"deleted_media": [{"path": "a", "size_bytes": 1048576}, {"path": "b", "size_bytes": 2097152}]},
                    ),
                    AuditEvent(
                        event_id="repair-1",
                        recorded_at="2026-06-03T01:00:00+00:00",
                        source_root=str(source.resolve()),
                        workflow="audio_packaging",
                        action="repair",
                        summary="Removed foreign audio.",
                        metadata={"audio_tracks_removed": {"count": 3, "total_bytes": 3145728}},
                    ),
                ]
            )

            def fake_http_get(url: str) -> dict[str, object]:
                if "/movie/top_rated" not in url:
                    return {"page": 1, "total_pages": 1, "results": []}
                page = int(url.split("page=")[1].split("&")[0])
                entries = [{"title": f"Top Movie {index}", "year": 2000 + index} for index in range(1, 501)]
                start = (page - 1) * 20
                return {
                    "page": page,
                    "total_pages": 25,
                    "results": [
                        {"title": item["title"], "release_date": f"{item['year']}-01-01"}
                        for item in entries[start : start + 20]
                    ],
                }

            with tempfile.TemporaryDirectory() as data_home:
                previous_data_home = os.environ.get("XDG_DATA_HOME")
                os.environ["XDG_DATA_HOME"] = data_home
                try:
                    payload = build_library_improvement_payload(
                        source,
                        report,
                        {
                            "canonical_list_provider": "tmdb",
                            "replacement_candidate_rules": {"quality_profile_floor": "standard_definition"},
                        },
                        audit_store=store,
                        tmdb_key="test-key",
                        http_get=fake_http_get,
                        pending_scan_count=1,
                    )
                finally:
                    if previous_data_home is None:
                        os.environ.pop("XDG_DATA_HOME", None)
                    else:
                        os.environ["XDG_DATA_HOME"] = previous_data_home

        self.assertEqual(payload["files_removed"]["count"], 2)
        self.assertEqual(payload["files_removed"]["total_bytes"], 3145728)
        self.assertEqual(payload["audio_tracks_removed"]["count"], 3)
        self.assertEqual(payload["audio_tracks_removed"]["total_bytes"], 3145728)
        self.assertEqual(payload["canonical_top_500_above_floor"]["count"], 15)
        self.assertEqual(payload["canonical_improvement"]["percent"], 300)
        self.assertEqual(payload["total_scans_performed"], 3)


if __name__ == "__main__":
    unittest.main()
