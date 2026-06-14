from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from normal import paths
from normal.models import ProposedChange, utc_now_iso
from normal.movie_apply import ApplyResult, apply_change
from normal.source_policy import ApprovedRoots


QUEUE_SCHEMA_VERSION = 1

QUEUEABLE_CHANGE_TYPES = frozenset({"file_rename", "file_move"})
REVERSIBLE_CHANGE_TYPES = frozenset({"file_rename", "file_move"})

ACTION_STATE_PENDING = "pending"
ACTION_STATE_DONE = "done"
ACTION_STATE_SKIPPED = "skipped"
ACTION_STATE_FAILED = "failed"
TERMINAL_ACTION_STATES = frozenset(
    {ACTION_STATE_DONE, ACTION_STATE_SKIPPED, ACTION_STATE_FAILED}
)


@dataclass(slots=True)
class PlannedAction:
    id: str
    action_kind: str
    source_path: str
    current_value: str
    proposed_value: str
    lane: str
    confidence: str
    reversible: bool
    item_id: str = ""
    reason: str = ""
    reason_codes: list[str] = field(default_factory=list)
    warning_codes: list[str] = field(default_factory=list)
    state: str = ACTION_STATE_PENDING
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlannedAction":
        return cls(
            id=str(payload.get("id") or ""),
            action_kind=str(payload.get("action_kind") or ""),
            source_path=str(payload.get("source_path") or ""),
            current_value=str(payload.get("current_value") or ""),
            proposed_value=str(payload.get("proposed_value") or ""),
            lane=str(payload.get("lane") or ""),
            confidence=str(payload.get("confidence") or ""),
            reversible=bool(payload.get("reversible", False)),
            item_id=str(payload.get("item_id") or ""),
            reason=str(payload.get("reason") or ""),
            reason_codes=[str(code) for code in payload.get("reason_codes", [])],
            warning_codes=[str(code) for code in payload.get("warning_codes", [])],
            state=str(payload.get("state") or ACTION_STATE_PENDING),
            message=str(payload.get("message") or ""),
        )


@dataclass(slots=True)
class QueueDocument:
    queue_id: str
    source_root: str
    lane: str
    created_at: str
    updated_at: str
    schema_version: int = QUEUE_SCHEMA_VERSION
    actions: list[PlannedAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_id": self.queue_id,
            "source_root": self.source_root,
            "lane": self.lane,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "schema_version": self.schema_version,
            "actions": [action.to_dict() for action in self.actions],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "QueueDocument":
        return cls(
            queue_id=str(payload.get("queue_id") or ""),
            source_root=str(payload.get("source_root") or ""),
            lane=str(payload.get("lane") or ""),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            schema_version=int(payload.get("schema_version") or QUEUE_SCHEMA_VERSION),
            actions=[
                PlannedAction.from_dict(item)
                for item in payload.get("actions", [])
                if isinstance(item, dict)
            ],
        )

    def pending(self) -> list[PlannedAction]:
        return [action for action in self.actions if action.state == ACTION_STATE_PENDING]

    def counts(self) -> dict[str, int]:
        tally = {
            ACTION_STATE_PENDING: 0,
            ACTION_STATE_DONE: 0,
            ACTION_STATE_SKIPPED: 0,
            ACTION_STATE_FAILED: 0,
        }
        for action in self.actions:
            tally[action.state] = tally.get(action.state, 0) + 1
        return tally


@dataclass(slots=True)
class DrainReport:
    applied: list[ApplyResult] = field(default_factory=list)
    skipped: list[ApplyResult] = field(default_factory=list)
    failed: list[ApplyResult] = field(default_factory=list)
    processed: int = 0
    stopped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": [asdict(result) for result in self.applied],
            "skipped": [asdict(result) for result in self.skipped],
            "failed": [asdict(result) for result in self.failed],
            "processed": self.processed,
            "stopped": self.stopped,
        }


def default_queue_dir() -> Path:
    return paths.data_dir() / "execution-queue"


def make_action_id(source_path: str, action_kind: str, current_value: str, proposed_value: str) -> str:
    digest = hashlib.sha1(
        f"{source_path}\0{action_kind}\0{current_value}\0{proposed_value}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


def queue_id_for(source_root: Path | str, lane: str) -> str:
    resolved = str(Path(source_root).expanduser().resolve())
    digest = hashlib.sha1(f"{resolved}\0{lane}".encode("utf-8")).hexdigest()
    return digest[:16]


def planned_actions_from_changes(changes: list[ProposedChange], *, lane: str) -> list[PlannedAction]:
    actions: list[PlannedAction] = []
    seen: set[str] = set()
    for change in changes:
        if change.change_type not in QUEUEABLE_CHANGE_TYPES:
            continue
        if change.path is None:
            continue
        action_id = make_action_id(
            change.path, change.change_type, change.current_value, change.proposed_value
        )
        if action_id in seen:
            continue
        seen.add(action_id)
        actions.append(
            PlannedAction(
                id=action_id,
                action_kind=change.change_type,
                source_path=change.path,
                current_value=change.current_value,
                proposed_value=change.proposed_value,
                lane=lane,
                confidence=change.confidence,
                reversible=change.change_type in REVERSIBLE_CHANGE_TYPES,
                item_id=change.item_id,
                reason=change.reason,
                reason_codes=list(change.reason_codes),
                warning_codes=list(change.warning_codes),
            )
        )
    return actions


def proposed_change_from_action(action: PlannedAction) -> ProposedChange:
    return ProposedChange(
        item_id=action.item_id or action.id,
        change_type=action.action_kind,
        current_value=action.current_value,
        proposed_value=action.proposed_value,
        confidence=action.confidence,
        reason=action.reason,
        path=action.source_path,
        reason_codes=list(action.reason_codes),
        warning_codes=list(action.warning_codes),
    )


class ExecutionQueueStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = (base_dir or default_queue_dir()).expanduser()
        self._lock = threading.Lock()

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def _path_for(self, queue_id: str) -> Path:
        return self._base_dir / f"{queue_id}.json"

    def stage(self, source_root: Path, lane: str, actions: list[PlannedAction]) -> QueueDocument:
        queue_id = queue_id_for(source_root, lane)
        now = utc_now_iso()
        document = QueueDocument(
            queue_id=queue_id,
            source_root=str(source_root.resolve()),
            lane=lane,
            created_at=now,
            updated_at=now,
            actions=actions,
        )
        self.save(document)
        return document

    def load(self, source_root: Path, lane: str) -> QueueDocument | None:
        path = self._path_for(queue_id_for(source_root, lane))
        with self._lock:
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return QueueDocument.from_dict(payload)

    def save(self, document: QueueDocument) -> None:
        path = self._path_for(document.queue_id)
        body = json.dumps(document.to_dict(), indent=2, sort_keys=True) + "\n"
        with self._lock:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_suffix(".json.tmp")
            temp_path.write_text(body, encoding="utf-8")
            os.replace(temp_path, path)

    def delete(self, source_root: Path, lane: str) -> None:
        path = self._path_for(queue_id_for(source_root, lane))
        with self._lock:
            try:
                path.unlink()
            except OSError:
                pass


def drain_queue(
    document: QueueDocument,
    store: ExecutionQueueStore,
    *,
    source_root: Path,
    approved_roots: ApprovedRoots | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_item: Callable[[PlannedAction], None] | None = None,
) -> DrainReport:
    report = DrainReport()
    root = source_root.resolve()
    for action in document.actions:
        if action.state != ACTION_STATE_PENDING:
            continue
        if should_cancel is not None and should_cancel():
            report.stopped = True
            break
        if on_item is not None:
            on_item(action)

        change = proposed_change_from_action(action)
        if action.confidence != "safe":
            action.state = ACTION_STATE_SKIPPED
            action.message = "Skipped review change."
            report.skipped.append(
                ApplyResult(
                    item_id=change.item_id,
                    change_type=change.change_type,
                    status="skipped",
                    path=action.source_path,
                    message=action.message,
                )
            )
        else:
            try:
                result = apply_change(root, root, change, approved_roots)
            except Exception as exc:
                action.state = ACTION_STATE_FAILED
                action.message = str(exc)
                report.failed.append(
                    ApplyResult(
                        item_id=change.item_id,
                        change_type=change.change_type,
                        status="failed",
                        path=action.source_path,
                        message=str(exc),
                    )
                )
            else:
                action.message = result.message
                if result.status == "applied":
                    action.state = ACTION_STATE_DONE
                    report.applied.append(result)
                else:
                    action.state = ACTION_STATE_SKIPPED
                    report.skipped.append(result)

        report.processed += 1
        document.updated_at = utc_now_iso()
        store.save(document)

    return report
