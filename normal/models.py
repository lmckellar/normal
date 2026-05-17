from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


RULESET_VERSION = "1"


@dataclass(slots=True)
class WarningItem:
    code: str
    message: str
    path: str | None = None


@dataclass(slots=True)
class ProposedChange:
    item_id: str
    change_type: str
    current_value: str
    proposed_value: str
    confidence: str
    reason: str
    path: str | None = None


@dataclass(slots=True)
class ChangePlan:
    source_root: str
    generated_at: str
    ruleset_version: str = RULESET_VERSION
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def build_empty_plan(source_root: Path) -> ChangePlan:
    return ChangePlan(
        source_root=str(source_root.resolve()),
        generated_at=utc_now_iso(),
    )
