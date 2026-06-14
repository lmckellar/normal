from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Severity = Literal["ok", "warn", "block"]
Operation = Literal["inspect", "scan", "mutate"]

DRIVE_DIRECTORY = "drive_directory"
MOUNT_ROOT = "mount_root"
JUNCTION = "junction"
SOURCE_MISSING = "source_missing"
NOT_DIRECTORY = "not_directory"

_BLOCK_FLAGS_BY_OPERATION: dict[Operation, frozenset[str]] = {
    "mutate": frozenset({DRIVE_DIRECTORY, MOUNT_ROOT, JUNCTION, SOURCE_MISSING, NOT_DIRECTORY}),
    "scan": frozenset({DRIVE_DIRECTORY, MOUNT_ROOT, SOURCE_MISSING, NOT_DIRECTORY}),
    "inspect": frozenset(),
}


@dataclass(frozen=True, slots=True)
class SourceRisk:
    source: Path
    flags: tuple[str, ...]
    severity: Severity


def detect_source_flags(source: Path) -> tuple[str, ...]:
    if not source.exists():
        return (SOURCE_MISSING,)
    if not source.is_dir():
        return (NOT_DIRECTORY,)
    flags: list[str] = []
    if source == Path(source.anchor):
        flags.append(DRIVE_DIRECTORY)
    elif os.path.ismount(source):
        flags.append(MOUNT_ROOT)
    if hasattr(os.path, "isjunction") and os.path.isjunction(source):
        flags.append(JUNCTION)
    return tuple(flags)


def classify_source(source: Path, *, operation: Operation) -> SourceRisk:
    flags = detect_source_flags(source)
    blocking = _BLOCK_FLAGS_BY_OPERATION[operation]
    if any(flag in blocking for flag in flags):
        severity: Severity = "block"
    elif flags:
        severity = "warn"
    else:
        severity = "ok"
    return SourceRisk(source=source, flags=flags, severity=severity)


def enforce_source_policy(source: Path, *, operation: Operation) -> None:
    risk = classify_source(source, operation=operation)
    if risk.severity != "block":
        return
    raise SourcePolicyError(
        f"Refusing {operation} on {source}: it is a {', '.join(risk.flags)}. "
        "Point the source at a folder inside a drive, not a whole drive, mount, or junction."
    )


class SourcePolicyError(RuntimeError):
    pass
