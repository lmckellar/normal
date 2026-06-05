from __future__ import annotations

from pathlib import Path
from typing import Any

from normal.audit import (
    AuditEffect,
    AuditEvent,
    AuditFollowUpUpdate,
    AuditSubject,
    FOLLOW_UP_STATUS_DISMISSED,
    FOLLOW_UP_STATUS_RESOLVED,
    SYSTEM_SOURCE_ROOT,
    make_event_id,
    normalize_source_root,
)
from normal.models import utc_now_iso

from .http import RequestContext
from .state import AUDIT_STORE


def handle_audit_read(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    limit = payload.get("limit")
    if limit is not None and not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    workflow = str(payload.get("workflow") or "").strip() or None
    action = str(payload.get("action") or "").strip() or None
    before_event_id = str(payload.get("before_event_id") or "").strip() or None
    kind = str(payload.get("follow_up_kind") or "").strip() or None
    follow_up_status = str(payload.get("follow_up_status") or "active").strip() or "active"
    include_system_events = workflow in (None, "system") and action in (None, "start")
    event_sources: list[Path | str] = [source, SYSTEM_SOURCE_ROOT] if include_system_events else [source]
    events = AUDIT_STORE.read_events_for_sources(
        event_sources,
        limit=None,
        before_event_id=before_event_id,
        workflow=workflow,
        action=action,
    )
    if include_system_events:
        source_root = str(source.resolve())
        events = [event for event in events if event.source_root == source_root or event.workflow == "system"]
        latest_system_start = next(
            (
                event
                for event in reversed(events)
                if event.source_root == SYSTEM_SOURCE_ROOT and event.workflow == "system" and event.action == "start"
            ),
            None,
        )
        if latest_system_start is not None:
            events = [event for event in events if event.event_id != latest_system_start.event_id]
            events.append(latest_system_start)
    if limit is not None and limit >= 0:
        events = events[-limit:]
    followups = AUDIT_STORE.read_followups(source, kind=kind, status=follow_up_status)
    ctx.respond_json(
        {
            "source_root": str(source.resolve()),
            "events": [event.to_dict() for event in events],
            "active_followups": [item.to_dict() for item in followups],
        }
    )


def handle_audit_follow_up_update(ctx: RequestContext, payload: dict[str, Any]) -> None:
    source = ctx.resolve_source(payload.get("source"))
    follow_up_id = str(payload.get("follow_up_id") or "").strip()
    if not follow_up_id:
        raise ValueError("follow_up_id is required")
    action = str(payload.get("action") or "").strip()
    if action not in {"dismiss", "resolve", "mark_handled"}:
        raise ValueError("action must be dismiss, resolve, or mark_handled")
    followups = {item.follow_up_id: item for item in AUDIT_STORE.read_followups(source, status="")}
    target = followups.get(follow_up_id)
    if target is None:
        raise FileNotFoundError(f"follow-up not found: {follow_up_id}")
    recorded_at = utc_now_iso()
    status = FOLLOW_UP_STATUS_RESOLVED if action == "resolve" else FOLLOW_UP_STATUS_DISMISSED
    summary = (
        f"Marked {target.kind.replace('_', ' ')} follow-up handled."
        if action == "mark_handled"
        else f"{target.kind.replace('_', ' ').capitalize()} follow-up {action}."
    )
    event = AuditEvent(
        event_id=make_event_id(normalize_source_root(source), "audit", f"follow_up_{action}", recorded_at, salt=follow_up_id),
        recorded_at=recorded_at,
        source_root=normalize_source_root(source),
        workflow="audit",
        action=f"follow_up_{action}",
        summary=summary,
        subjects=[
            AuditSubject(
                kind="follow_up",
                path=str(target.subject.get("path") or "") or None,
                title=str(target.subject.get("title") or "") or None,
                year=int(target.subject["year"]) if target.subject.get("year") not in (None, "") else None,
                item_id=str(target.subject.get("item_id") or "") or None,
                issue_family=str(target.subject.get("issue_family") or "") or None,
            )
        ],
        effects=[AuditEffect(kind="follow_up", status=status, path=target.subject.get("path"), message=summary)],
        follow_up_updates=[
            AuditFollowUpUpdate(
                follow_up_id=follow_up_id,
                kind=target.kind,
                action="dismiss" if status == FOLLOW_UP_STATUS_DISMISSED else "resolve",
                status=status,
                summary=summary,
                details=dict(target.subject),
            )
        ],
    )
    AUDIT_STORE.append(event)
    ctx.respond_json(
        {
            "source_root": str(source.resolve()),
            "event": event.to_dict(),
            "active_followups": [item.to_dict() for item in AUDIT_STORE.read_followups(source)],
        }
    )


def build_reversal_entries_for_normalize_effects(effects: list[AuditEffect]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for effect in effects:
        if effect.status != "applied":
            continue
        if effect.kind in {"file_rename", "file_move", "folder_rename", "folder_merge"} and effect.path and effect.previous_path:
            entries.append(
                {
                    "kind": effect.kind,
                    "from_path": effect.path,
                    "to_path": effect.previous_path,
                }
            )
        elif effect.kind in {"file_delete", "folder_delete"} and effect.previous_path:
            entries.append(
                {
                    "kind": effect.kind,
                    "deleted_path": effect.previous_path,
                    "restore_supported": False,
                }
            )
    if not entries:
        return {"capability": "none"}
    return {"capability": "recorded_only", "entries": entries}


def record_scan_event(
    source: Path,
    *,
    workflow: str,
    label: str,
    status: str = "applied",
    summary: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    recorded_at = utc_now_iso()
    source_root = normalize_source_root(source)
    event_summary = summary or f"Performed {label}."
    event = AuditEvent(
        event_id=make_event_id(source_root, workflow, "scan", recorded_at, salt=label),
        recorded_at=recorded_at,
        source_root=source_root,
        workflow=workflow,
        action="scan",
        summary=event_summary,
        subjects=[AuditSubject(kind="source_root", path=source_root)],
        effects=[AuditEffect(kind="scan", status=status, path=source_root, message=event_summary)],
        reversal={"capability": "none"},
        metadata={"label": label, **(metadata or {})},
    )
    AUDIT_STORE.append(event)


def record_policy_update_event(
    source: Path,
    *,
    label: str,
    request_kind: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    recorded_at = utc_now_iso()
    source_root = normalize_source_root(source)
    summary = f"Updated policy definition {label}."
    event = AuditEvent(
        event_id=make_event_id(source_root, "policy", "update", recorded_at, salt=f"{request_kind}:{label}"),
        recorded_at=recorded_at,
        source_root=source_root,
        workflow="policy",
        action="update",
        summary=summary,
        subjects=[AuditSubject(kind="policy_definition", path=source_root, item_id=label)],
        effects=[AuditEffect(kind="policy_update", status="applied", path=source_root, message=summary)],
        reversal={"capability": "none"},
        metadata={"label": label, "request_kind": request_kind, **(metadata or {})},
    )
    AUDIT_STORE.append(event)


def record_export_event(
    source: Path,
    *,
    workflow: str,
    label: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    recorded_at = utc_now_iso()
    source_root = normalize_source_root(source)
    summary = f"Exported {label}."
    event = AuditEvent(
        event_id=make_event_id(source_root, workflow, "export", recorded_at, salt=label),
        recorded_at=recorded_at,
        source_root=source_root,
        workflow=workflow,
        action="export",
        summary=summary,
        subjects=[AuditSubject(kind="source_root", path=source_root)],
        effects=[AuditEffect(kind="export", status="applied", path=source_root, message=summary)],
        reversal={"capability": "none"},
        metadata={"label": label, **(metadata or {})},
    )
    AUDIT_STORE.append(event)


def normalize_subject_from_path(path: Path, *, issue_family: str | None = None) -> AuditSubject:
    from normal.movie_plan import parse_movie_name

    parsed = parse_movie_name(path)
    return AuditSubject(
        kind="movie",
        path=str(path.resolve()),
        title=parsed.title,
        year=parsed.year,
        issue_family=issue_family,
    )


def record_system_event(
    *,
    action: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    recorded_at = utc_now_iso()
    event = AuditEvent(
        event_id=make_event_id(SYSTEM_SOURCE_ROOT, "system", action, recorded_at),
        recorded_at=recorded_at,
        source_root=SYSTEM_SOURCE_ROOT,
        workflow="system",
        action=action,
        summary=summary,
        subjects=[AuditSubject(kind="system", item_id="normal-web-ui")],
        effects=[AuditEffect(kind="system", status="applied", message=summary)],
        reversal={"capability": "none"},
        metadata=metadata or {},
    )
    AUDIT_STORE.append(event)
