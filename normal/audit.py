from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import queue
import threading
from typing import Any

from normal.models import utc_now_iso


LEDGER_VERSION = 1
SYSTEM_SOURCE_ROOT = "__system__"
FOLLOW_UP_KIND_REPLACEMENT = "replacement"
FOLLOW_UP_KIND_REPAIR_REVIEW = "repair_review"
FOLLOW_UP_STATUS_ACTIVE = "active"
FOLLOW_UP_STATUS_RESOLVED = "resolved"
FOLLOW_UP_STATUS_DISMISSED = "dismissed"


@dataclass(slots=True)
class AuditSubject:
    kind: str
    path: str | None = None
    title: str | None = None
    year: int | None = None
    item_id: str | None = None
    issue_family: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuditEffect:
    kind: str
    status: str
    path: str | None = None
    previous_path: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuditFollowUpUpdate:
    follow_up_id: str
    kind: str
    action: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuditEvent:
    event_id: str
    recorded_at: str
    source_root: str
    workflow: str
    action: str
    summary: str
    subjects: list[AuditSubject] = field(default_factory=list)
    effects: list[AuditEffect] = field(default_factory=list)
    follow_up_updates: list[AuditFollowUpUpdate] = field(default_factory=list)
    reversal: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class DerivedFollowUp:
    follow_up_id: str
    source_root: str
    kind: str
    status: str
    summary: str
    created_at: str
    updated_at: str
    workflow: str
    subject: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditRevisionNotice:
    revision: int
    source_roots: list[str]
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_audit_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "audit-ledger.jsonl"


def default_replacement_queue_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "movie-replacement-queue.json"


def default_subtitle_history_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "subtitle-fix-history.json"


def normalize_source_root(source_root: Path | str) -> str:
    raw = str(source_root).strip()
    if raw == SYSTEM_SOURCE_ROOT:
        return SYSTEM_SOURCE_ROOT
    return str(Path(raw).expanduser().resolve())


def make_event_id(
    source_root: str,
    workflow: str,
    action: str,
    recorded_at: str,
    salt: str = "",
) -> str:
    digest = hashlib.sha1(f"{source_root}\0{workflow}\0{action}\0{recorded_at}\0{salt}".encode("utf-8")).hexdigest()
    return digest[:16]


def make_follow_up_id(
    source_root: str,
    kind: str,
    issue_family: str,
    title: str | None,
    year: int | None,
    path: str | None,
) -> str:
    digest = hashlib.sha1(
        f"{source_root}\0{kind}\0{issue_family}\0{title or ''}\0{year or 0}\0{path or ''}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


class AuditStore:
    def __init__(
        self,
        ledger_path: Path | None = None,
        replacement_queue_path: Path | None = None,
        subtitle_history_path: Path | None = None,
    ) -> None:
        self._ledger_path = (ledger_path or default_audit_path()).expanduser()
        self._replacement_queue_path = (replacement_queue_path or default_replacement_queue_path()).expanduser()
        self._subtitle_history_path = (subtitle_history_path or default_subtitle_history_path()).expanduser()
        self._lock = threading.Lock()
        self._revision = 0
        self._events_cache_signature: tuple[int, int] | None = None
        self._events_cache: list[AuditEvent] | None = None
        self._followups_cache_signature: tuple[int, int] | None = None
        self._followups_cache: dict[str, DerivedFollowUp] | None = None
        self._revision_subscribers: set[queue.Queue[AuditRevisionNotice]] = set()

    @property
    def ledger_path(self) -> Path:
        return self._ledger_path

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def append(self, event: AuditEvent) -> None:
        self.append_batch([event])

    def append_batch(self, events: list[AuditEvent]) -> None:
        if not events:
            return
        self.migrate_legacy_if_needed()
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(json.dumps(event.to_dict(), sort_keys=True) + "\n" for event in events)
        with self._lock:
            with self._ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(lines)
            self._revision += len(events)
            self._invalidate_caches_unlocked()
            self._publish_revision_notice_unlocked(events)

    def read_events(
        self,
        source_root: Path | str,
        *,
        limit: int | None = None,
        before_event_id: str | None = None,
        workflow: str | None = None,
        action: str | None = None,
    ) -> list[AuditEvent]:
        return self.read_events_for_sources(
            [source_root],
            limit=limit,
            before_event_id=before_event_id,
            workflow=workflow,
            action=action,
        )

    def read_events_for_sources(
        self,
        source_roots: list[Path | str],
        *,
        limit: int | None = None,
        before_event_id: str | None = None,
        workflow: str | None = None,
        action: str | None = None,
    ) -> list[AuditEvent]:
        self.migrate_legacy_if_needed()
        allowed_sources = {normalize_source_root(source_root) for source_root in source_roots}
        events = [event for event in self._load_all_events() if event.source_root in allowed_sources]
        if before_event_id:
            filtered: list[AuditEvent] = []
            for event in events:
                if event.event_id == before_event_id:
                    break
                filtered.append(event)
            events = filtered
        if workflow:
            events = [event for event in events if event.workflow == workflow]
        if action:
            events = [event for event in events if event.action == action]
        if limit is not None and limit >= 0:
            events = events[-limit:]
        return events

    def read_followups(
        self,
        source_root: Path | str,
        *,
        kind: str | None = None,
        status: str = FOLLOW_UP_STATUS_ACTIVE,
    ) -> list[DerivedFollowUp]:
        source = normalize_source_root(source_root)
        followups = list(self._derive_followups().values())
        followups = [item for item in followups if item.source_root == source]
        if kind:
            followups = [item for item in followups if item.kind == kind]
        if status:
            followups = [item for item in followups if item.status == status]
        followups.sort(key=lambda item: (item.updated_at, item.created_at, item.follow_up_id))
        return followups

    def migrate_legacy_if_needed(self) -> None:
        with self._lock:
            if self._ledger_path.exists():
                return
            events = self._build_legacy_migration_events()
            if not events:
                return
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self._ledger_path.open("w", encoding="utf-8") as handle:
                for event in events:
                    handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
            self._revision += len(events)
            self._invalidate_caches_unlocked()
            self._publish_revision_notice_unlocked(events)

    def subscribe_revisions(self) -> queue.Queue[AuditRevisionNotice]:
        subscriber: queue.Queue[AuditRevisionNotice] = queue.Queue(maxsize=1)
        with self._lock:
            self._revision_subscribers.add(subscriber)
        return subscriber

    def unsubscribe_revisions(self, subscriber: queue.Queue[AuditRevisionNotice]) -> None:
        with self._lock:
            self._revision_subscribers.discard(subscriber)

    def _invalidate_caches_unlocked(self) -> None:
        self._events_cache_signature = None
        self._events_cache = None
        self._followups_cache_signature = None
        self._followups_cache = None

    def _publish_revision_notice_unlocked(self, events: list[AuditEvent]) -> None:
        if not self._revision_subscribers:
            return
        notice = AuditRevisionNotice(
            revision=self._revision,
            source_roots=sorted({event.source_root for event in events if event.source_root}),
            recorded_at=events[-1].recorded_at or utc_now_iso(),
        )
        stale_subscribers: list[queue.Queue[AuditRevisionNotice]] = []
        for subscriber in self._revision_subscribers:
            try:
                while True:
                    subscriber.get_nowait()
            except queue.Empty:
                pass
            try:
                subscriber.put_nowait(notice)
            except queue.Full:
                stale_subscribers.append(subscriber)
        for subscriber in stale_subscribers:
            self._revision_subscribers.discard(subscriber)

    def _ledger_signature(self) -> tuple[int, int] | None:
        try:
            stat_result = self._ledger_path.stat()
        except OSError:
            return None
        return (stat_result.st_mtime_ns, stat_result.st_size)

    def _build_legacy_migration_events(self) -> list[AuditEvent]:
        events: list[AuditEvent] = []
        queue_events = self._migrate_legacy_replacement_queue()
        subtitle_events = self._migrate_legacy_subtitle_history()
        events.extend(queue_events)
        events.extend(subtitle_events)
        if events:
            migrated_at = utc_now_iso()
            source_root = SYSTEM_SOURCE_ROOT
            events.append(
                AuditEvent(
                    event_id=make_event_id(source_root, "audit", "legacy_migration", migrated_at, salt="marker"),
                    recorded_at=migrated_at,
                    source_root=source_root,
                    workflow="audit",
                    action="legacy_migration",
                    summary="Imported legacy replacement and subtitle history into the audit ledger.",
                    metadata={
                        "replacement_queue_path": str(self._replacement_queue_path),
                        "subtitle_history_path": str(self._subtitle_history_path),
                        "migrated_event_count": len(events),
                        "ledger_version": LEDGER_VERSION,
                    },
                )
            )
        return events

    def _migrate_legacy_replacement_queue(self) -> list[AuditEvent]:
        if not self._replacement_queue_path.exists():
            return []
        try:
            payload = json.loads(self._replacement_queue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return []
        events: list[AuditEvent] = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                continue
            source_root = normalize_source_root(str(item.get("source_root") or ""))
            if not source_root or source_root == ".":
                continue
            title = str(item.get("title") or "").strip() or None
            year = int(item.get("year")) if item.get("year") not in (None, "") else None
            path = str(item.get("original_path") or "").strip() or None
            issue_family = str(item.get("issue_family") or "weak_encode")
            follow_up_id = make_follow_up_id(source_root, FOLLOW_UP_KIND_REPLACEMENT, issue_family, title, year, path)
            item_id = str(item.get("item_id") or follow_up_id)
            queued_at = str(item.get("queued_at") or utc_now_iso())
            subjects = [
                AuditSubject(
                    kind="movie",
                    path=path,
                    title=title,
                    year=year,
                    item_id=item_id,
                    issue_family=issue_family,
                    details={"mode": item.get("mode"), "original_folder_path": item.get("original_folder_path")},
                )
            ]
            follow_up_updates = [
                AuditFollowUpUpdate(
                    follow_up_id=follow_up_id,
                    kind=FOLLOW_UP_KIND_REPLACEMENT,
                    action="create",
                    status=FOLLOW_UP_STATUS_ACTIVE,
                    summary=f"{title or 'Title'} is awaiting replacement.",
                    details={"issue_family": issue_family, "path": path, "title": title, "year": year, "item_id": item_id},
                )
            ]
            effects = [
                AuditEffect(
                    kind="replacement_queue",
                    status=str(item.get("status") or "pending"),
                    path=path,
                    message="Legacy replacement queue item imported.",
                    details={"issue_family": issue_family, "item_id": item_id},
                )
            ]
            events.append(
                AuditEvent(
                    event_id=make_event_id(source_root, issue_family, "legacy_queue_import", queued_at, salt=f"{index}-queued"),
                    recorded_at=queued_at,
                    source_root=source_root,
                    workflow=issue_family,
                    action="legacy_queue_import",
                    summary=f"Imported replacement history for {title or 'unknown title'}.",
                    subjects=subjects,
                    effects=effects,
                    follow_up_updates=follow_up_updates,
                    metadata={"legacy_status": str(item.get("status") or "pending"), "item": item},
                )
            )
            deleted_at = str(item.get("deleted_at") or "").strip()
            if deleted_at:
                events.append(
                    AuditEvent(
                        event_id=make_event_id(source_root, issue_family, "delete", deleted_at, salt=f"{index}-deleted"),
                        recorded_at=deleted_at,
                        source_root=source_root,
                        workflow=issue_family,
                        action="delete",
                        summary=f"Deleted {title or 'title'} while tracking a replacement follow-up.",
                        subjects=subjects,
                        effects=[
                            AuditEffect(
                                kind="delete",
                                status="applied",
                                path=path,
                                message="Legacy queued media deletion imported.",
                                details={"item_id": item_id},
                            )
                        ],
                        metadata={"item": item},
                    )
                )
            completed_at = str(item.get("completed_at") or "").strip()
            if completed_at:
                completed_path = str(item.get("completed_by_path") or "").strip() or None
                events.append(
                    AuditEvent(
                        event_id=make_event_id(source_root, issue_family, "replacement_completed", completed_at, salt=f"{index}-completed"),
                        recorded_at=completed_at,
                        source_root=source_root,
                        workflow=issue_family,
                        action="replacement_completed",
                        summary=f"Replacement follow-up completed for {title or 'title'}.",
                        subjects=subjects,
                        effects=[
                            AuditEffect(
                                kind="replacement_completed",
                                status="applied",
                                path=completed_path,
                                previous_path=path,
                                message="Legacy replacement completion imported.",
                                details={"item_id": item_id},
                            )
                        ],
                        follow_up_updates=[
                            AuditFollowUpUpdate(
                                follow_up_id=follow_up_id,
                                kind=FOLLOW_UP_KIND_REPLACEMENT,
                                action="resolve",
                                status=FOLLOW_UP_STATUS_RESOLVED,
                                summary=f"Replacement found for {title or 'title'}.",
                                details={"completed_by_path": completed_path, "item_id": item_id},
                            )
                        ],
                    )
                )
            dismissed_at = str(item.get("dismissed_at") or "").strip()
            if dismissed_at:
                events.append(
                    AuditEvent(
                        event_id=make_event_id(source_root, issue_family, "replacement_dismissed", dismissed_at, salt=f"{index}-dismissed"),
                        recorded_at=dismissed_at,
                        source_root=source_root,
                        workflow=issue_family,
                        action="replacement_dismissed",
                        summary=f"Removed {title or 'title'} from the replacement plan without replacement.",
                        subjects=subjects,
                        follow_up_updates=[
                            AuditFollowUpUpdate(
                                follow_up_id=follow_up_id,
                                kind=FOLLOW_UP_KIND_REPLACEMENT,
                                action="dismiss",
                                status=FOLLOW_UP_STATUS_DISMISSED,
                                summary=f"Replacement follow-up dismissed for {title or 'title'}.",
                                details={"item_id": item_id},
                            )
                        ],
                        metadata={"item": item},
                    )
                )
        return events

    def _migrate_legacy_subtitle_history(self) -> list[AuditEvent]:
        if not self._subtitle_history_path.exists():
            return []
        try:
            payload = json.loads(self._subtitle_history_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            return []
        events: list[AuditEvent] = []
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                continue
            source_root = normalize_source_root(str(item.get("source_root") or ""))
            if not source_root or source_root == ".":
                continue
            path = str(item.get("path") or "").strip() or None
            title = str(item.get("title") or "").strip() or None
            year = int(item.get("year")) if item.get("year") not in (None, "") else None
            issue_code = str(item.get("issue_code") or "").strip() or None
            item_id = str(item.get("item_id") or "")
            follow_up_id = make_follow_up_id(source_root, FOLLOW_UP_KIND_REPAIR_REVIEW, "subtitle_readiness", title, year, path)
            recorded_at = str(item.get("recorded_at") or utc_now_iso())
            subjects = [
                AuditSubject(
                    kind="movie",
                    path=path,
                    title=title,
                    year=year,
                    item_id=item_id or follow_up_id,
                    issue_family="subtitle_readiness",
                    details={"issue_code": issue_code},
                )
            ]
            events.append(
                AuditEvent(
                    event_id=make_event_id(source_root, "subtitle_readiness", "legacy_repair_review_import", recorded_at, salt=f"{index}-recorded"),
                    recorded_at=recorded_at,
                    source_root=source_root,
                    workflow="subtitle_readiness",
                    action="legacy_repair_review_import",
                    summary=f"Imported subtitle repair review history for {title or 'unknown title'}.",
                    subjects=subjects,
                    effects=[
                        AuditEffect(
                            kind="repair_review",
                            status="recorded",
                            path=path,
                            message="Legacy subtitle review item imported.",
                            details={"issue_code": issue_code, "item_id": item_id},
                        )
                    ],
                    follow_up_updates=[
                        AuditFollowUpUpdate(
                            follow_up_id=follow_up_id,
                            kind=FOLLOW_UP_KIND_REPAIR_REVIEW,
                            action="create",
                            status=FOLLOW_UP_STATUS_ACTIVE,
                            summary=f"Subtitle repair review remains for {title or 'title'}.",
                            details={"issue_code": issue_code, "path": path, "title": title, "year": year, "item_id": item_id},
                        )
                    ],
                    metadata={"item": item},
                )
            )
            dismissed_at = str(item.get("dismissed_at") or "").strip()
            if dismissed_at:
                events.append(
                    AuditEvent(
                        event_id=make_event_id(source_root, "subtitle_readiness", "repair_review_dismissed", dismissed_at, salt=f"{index}-dismissed"),
                        recorded_at=dismissed_at,
                        source_root=source_root,
                        workflow="subtitle_readiness",
                        action="repair_review_dismissed",
                        summary=f"Marked subtitle repair review handled for {title or 'title'}.",
                        subjects=subjects,
                        follow_up_updates=[
                            AuditFollowUpUpdate(
                                follow_up_id=follow_up_id,
                                kind=FOLLOW_UP_KIND_REPAIR_REVIEW,
                                action="dismiss",
                                status=FOLLOW_UP_STATUS_DISMISSED,
                                summary=f"Subtitle repair review handled for {title or 'title'}.",
                                details={"item_id": item_id},
                            )
                        ],
                        metadata={"item": item},
                    )
                )
        return events

    def _load_all_events(self) -> list[AuditEvent]:
        signature = self._ledger_signature()
        with self._lock:
            if signature is not None and self._events_cache_signature == signature and self._events_cache is not None:
                return self._events_cache
        if signature is None:
            with self._lock:
                self._events_cache_signature = None
                self._events_cache = []
            return []
        events: list[AuditEvent] = []
        for line in self._ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            event = _event_from_payload(payload)
            if event is not None:
                events.append(event)
        events.sort(key=lambda item: item.recorded_at)
        with self._lock:
            current_signature = self._ledger_signature()
            self._events_cache_signature = current_signature
            self._events_cache = events
        return events

    def _derive_followups(self) -> dict[str, DerivedFollowUp]:
        signature = self._ledger_signature()
        with self._lock:
            if signature is not None and self._followups_cache_signature == signature and self._followups_cache is not None:
                return self._followups_cache
        derived: dict[str, DerivedFollowUp] = {}
        for event in self._load_all_events():
            for update in event.follow_up_updates:
                existing = derived.get(update.follow_up_id)
                if existing is None:
                    derived[update.follow_up_id] = DerivedFollowUp(
                        follow_up_id=update.follow_up_id,
                        source_root=event.source_root,
                        kind=update.kind,
                        status=update.status,
                        summary=update.summary,
                        created_at=event.recorded_at,
                        updated_at=event.recorded_at,
                        workflow=event.workflow,
                        subject=_followup_subject_from_update(update),
                        details=dict(update.details),
                    )
                    continue
                existing.status = update.status
                existing.summary = update.summary
                existing.updated_at = event.recorded_at
                existing.details.update(update.details)
                subject = _followup_subject_from_update(update)
                if subject:
                    existing.subject.update(subject)
        with self._lock:
            current_signature = self._ledger_signature()
            self._followups_cache_signature = current_signature
            self._followups_cache = derived
        return derived


def _event_from_payload(payload: dict[str, Any]) -> AuditEvent | None:
    if not isinstance(payload, dict):
        return None
    return AuditEvent(
        event_id=str(payload.get("event_id") or ""),
        recorded_at=str(payload.get("recorded_at") or ""),
        source_root=str(payload.get("source_root") or ""),
        workflow=str(payload.get("workflow") or ""),
        action=str(payload.get("action") or ""),
        summary=str(payload.get("summary") or ""),
        subjects=[
            AuditSubject(
                kind=str(item.get("kind") or ""),
                path=item.get("path"),
                title=item.get("title"),
                year=item.get("year"),
                item_id=item.get("item_id"),
                issue_family=item.get("issue_family"),
                details=item.get("details") if isinstance(item.get("details"), dict) else {},
            )
            for item in payload.get("subjects", [])
            if isinstance(item, dict)
        ],
        effects=[
            AuditEffect(
                kind=str(item.get("kind") or ""),
                status=str(item.get("status") or ""),
                path=item.get("path"),
                previous_path=item.get("previous_path"),
                message=str(item.get("message") or ""),
                details=item.get("details") if isinstance(item.get("details"), dict) else {},
            )
            for item in payload.get("effects", [])
            if isinstance(item, dict)
        ],
        follow_up_updates=[
            AuditFollowUpUpdate(
                follow_up_id=str(item.get("follow_up_id") or ""),
                kind=str(item.get("kind") or ""),
                action=str(item.get("action") or ""),
                status=str(item.get("status") or ""),
                summary=str(item.get("summary") or ""),
                details=item.get("details") if isinstance(item.get("details"), dict) else {},
            )
            for item in payload.get("follow_up_updates", [])
            if isinstance(item, dict)
        ],
        reversal=payload.get("reversal") if isinstance(payload.get("reversal"), dict) else {},
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    )


def _followup_subject_from_update(update: AuditFollowUpUpdate) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("path", "title", "year", "issue_family", "item_id", "completed_by_path"):
        if key in update.details and update.details[key] not in (None, ""):
            result[key] = update.details[key]
    return result
