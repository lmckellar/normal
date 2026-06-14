from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.execution_queue import (
    ACTION_STATE_DONE,
    ACTION_STATE_PENDING,
    ACTION_STATE_SKIPPED,
    ExecutionQueueStore,
    drain_queue,
    make_action_id,
    planned_actions_from_changes,
)
from normal.models import ProposedChange


def _rename(path: Path, current: str, proposed: str, *, confidence: str = "safe") -> ProposedChange:
    return ProposedChange(
        item_id=f"{current}#file",
        change_type="file_rename",
        current_value=current,
        proposed_value=proposed,
        confidence=confidence,
        reason="test",
        path=str(path),
    )


class PlannedActionContractTests(unittest.TestCase):
    def test_only_rename_and_move_actions_are_queueable(self) -> None:
        changes = [
            _rename(Path("/lib/a.mkv"), "a.mkv", "A (2000).mkv"),
            ProposedChange(
                item_id="b",
                change_type="file_move",
                current_value="b.mkv",
                proposed_value="B (2001)/B (2001).mkv",
                confidence="safe",
                reason="test",
                path="/lib/b.mkv",
            ),
            ProposedChange(
                item_id="folder",
                change_type="folder_rename",
                current_value="messy",
                proposed_value="Clean (2002)",
                confidence="safe",
                reason="test",
                path="/lib/messy",
            ),
            ProposedChange(
                item_id="delete",
                change_type="file_delete",
                current_value="junk.mkv",
                proposed_value="",
                confidence="safe",
                reason="test",
                path="/lib/junk.mkv",
            ),
        ]
        actions = planned_actions_from_changes(changes, lane="movie")
        self.assertEqual([action.action_kind for action in actions], ["file_rename", "file_move"])
        self.assertTrue(all(action.reversible for action in actions))
        self.assertTrue(all(action.lane == "movie" for action in actions))

    def test_action_id_is_stable_and_dedupes(self) -> None:
        change = _rename(Path("/lib/a.mkv"), "a.mkv", "A (2000).mkv")
        actions = planned_actions_from_changes([change, change], lane="movie")
        self.assertEqual(len(actions), 1)
        self.assertEqual(
            actions[0].id,
            make_action_id("/lib/a.mkv", "file_rename", "a.mkv", "A (2000).mkv"),
        )


class ExecutionQueuePersistenceTests(unittest.TestCase):
    def test_stage_persists_and_reloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lib"
            source.mkdir()
            store = ExecutionQueueStore(base_dir=root / "queue")
            actions = planned_actions_from_changes(
                [_rename(source / "a.mkv", "a.mkv", "A (2000).mkv")], lane="movie"
            )
            document = store.stage(source, "movie", actions)
            self.assertTrue((root / "queue" / f"{document.queue_id}.json").exists())

            reloaded = store.load(source, "movie")
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded.actions[0].id, actions[0].id)
            self.assertEqual(reloaded.actions[0].state, ACTION_STATE_PENDING)

    def test_lanes_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lib"
            source.mkdir()
            store = ExecutionQueueStore(base_dir=root / "queue")
            store.stage(source, "movie", [])
            self.assertIsNone(store.load(source, "tv"))


class DrainTests(unittest.TestCase):
    def _store(self, root: Path) -> ExecutionQueueStore:
        return ExecutionQueueStore(base_dir=root / "queue")

    def test_drain_applies_safe_rename_and_checkpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lib"
            source.mkdir()
            (source / "a.mkv").write_text("video", encoding="utf-8")
            store = self._store(root)
            actions = planned_actions_from_changes(
                [_rename(source / "a.mkv", "a.mkv", "A (2000).mkv")], lane="movie"
            )
            document = store.stage(source, "movie", actions)

            report = drain_queue(document, store, source_root=source)

            self.assertEqual(report.processed, 1)
            self.assertEqual(len(report.applied), 1)
            self.assertFalse((source / "a.mkv").exists())
            self.assertTrue((source / "A (2000).mkv").exists())
            self.assertEqual(store.load(source, "movie").actions[0].state, ACTION_STATE_DONE)

    def test_review_action_is_skipped_not_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lib"
            source.mkdir()
            (source / "a.mkv").write_text("video", encoding="utf-8")
            store = self._store(root)
            actions = planned_actions_from_changes(
                [_rename(source / "a.mkv", "a.mkv", "A.mkv", confidence="review")], lane="movie"
            )
            document = store.stage(source, "movie", actions)

            report = drain_queue(document, store, source_root=source)

            self.assertEqual(len(report.skipped), 1)
            self.assertTrue((source / "a.mkv").exists())
            self.assertEqual(document.actions[0].state, ACTION_STATE_SKIPPED)

    def test_cooperative_stop_leaves_remaining_pending_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lib"
            source.mkdir()
            (source / "a.mkv").write_text("video", encoding="utf-8")
            (source / "b.mkv").write_text("video", encoding="utf-8")
            store = self._store(root)
            actions = planned_actions_from_changes(
                [
                    _rename(source / "a.mkv", "a.mkv", "A (2000).mkv"),
                    _rename(source / "b.mkv", "b.mkv", "B (2001).mkv"),
                ],
                lane="movie",
            )
            document = store.stage(source, "movie", actions)

            calls = {"n": 0}

            def should_cancel() -> bool:
                fire = calls["n"] >= 1
                calls["n"] += 1
                return fire

            first = drain_queue(document, store, source_root=source, should_cancel=should_cancel)
            self.assertTrue(first.stopped)
            self.assertEqual(first.processed, 1)
            self.assertTrue((source / "A (2000).mkv").exists())
            self.assertTrue((source / "b.mkv").exists())

            # Simulate a restart: a fresh store reading the checkpointed file.
            resumed_store = self._store(root)
            resumed = resumed_store.load(source, "movie")
            self.assertEqual(len(resumed.pending()), 1)

            second = drain_queue(resumed, resumed_store, source_root=source)
            self.assertEqual(second.processed, 1)
            self.assertTrue((source / "B (2001).mkv").exists())
            self.assertEqual(resumed_store.load(source, "movie").counts()[ACTION_STATE_DONE], 2)

    def test_redraining_completed_queue_is_a_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lib"
            source.mkdir()
            (source / "a.mkv").write_text("video", encoding="utf-8")
            store = self._store(root)
            actions = planned_actions_from_changes(
                [_rename(source / "a.mkv", "a.mkv", "A (2000).mkv")], lane="movie"
            )
            document = store.stage(source, "movie", actions)

            drain_queue(document, store, source_root=source)
            again = drain_queue(store.load(source, "movie"), store, source_root=source)

            self.assertEqual(again.processed, 0)
            self.assertEqual(again.applied, [])

    def test_drift_after_stage_degrades_to_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "lib"
            source.mkdir()
            (source / "a.mkv").write_text("video", encoding="utf-8")
            store = self._store(root)
            actions = planned_actions_from_changes(
                [_rename(source / "a.mkv", "a.mkv", "A (2000).mkv")], lane="movie"
            )
            document = store.stage(source, "movie", actions)

            (source / "a.mkv").rename(source / "moved-elsewhere.mkv")
            report = drain_queue(document, store, source_root=source)

            self.assertEqual(len(report.skipped), 1)
            self.assertEqual(len(report.failed), 0)
            self.assertEqual(document.actions[0].state, ACTION_STATE_SKIPPED)


if __name__ == "__main__":
    unittest.main()
