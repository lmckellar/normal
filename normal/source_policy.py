from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal

Severity = Literal["ok", "warn", "block"]

DRIVE_DIRECTORY = "drive_directory"
MOUNT_ROOT = "mount_root"
JUNCTION = "junction"
SOURCE_MISSING = "source_missing"
NOT_DIRECTORY = "not_directory"


class Operation(str, Enum):
    INSPECT = "inspect"
    HEAVY_SCAN = "heavy_scan"
    PLAN = "plan"
    APPLY = "apply"
    DELETE = "delete"
    REMUX = "remux"


_BLOCK_FLAGS_BY_OPERATION: dict[Operation, frozenset[str]] = {
    Operation.INSPECT: frozenset(),
    Operation.HEAVY_SCAN: frozenset({DRIVE_DIRECTORY, MOUNT_ROOT, SOURCE_MISSING, NOT_DIRECTORY}),
    Operation.PLAN: frozenset({DRIVE_DIRECTORY, MOUNT_ROOT, SOURCE_MISSING, NOT_DIRECTORY}),
    Operation.APPLY: frozenset({DRIVE_DIRECTORY, MOUNT_ROOT, JUNCTION, SOURCE_MISSING, NOT_DIRECTORY}),
    Operation.DELETE: frozenset({DRIVE_DIRECTORY, MOUNT_ROOT, JUNCTION, SOURCE_MISSING, NOT_DIRECTORY}),
    Operation.REMUX: frozenset({DRIVE_DIRECTORY, MOUNT_ROOT, JUNCTION, SOURCE_MISSING, NOT_DIRECTORY}),
}


@dataclass(frozen=True, slots=True)
class SourceRisk:
    source: Path
    flags: tuple[str, ...]
    severity: Severity


def resolve_source_path(raw_source: Any, default_source: Path | None = None) -> Path:
    if raw_source:
        resolved = Path(str(raw_source)).expanduser().resolve()
    elif default_source is not None:
        resolved = default_source.expanduser().resolve()
    else:
        raise ValueError("source is required")
    if not resolved.exists():
        raise FileNotFoundError(f"source does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"source is not a directory: {resolved}")
    return resolved


def path_is_under(path: Path | str, root: Path | str) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).expanduser().resolve())
        return True
    except ValueError:
        return False


def source_paths_overlap(left: Path | str, right: Path | str) -> bool:
    return path_is_under(left, right) or path_is_under(right, left)


@dataclass(frozen=True, slots=True)
class ApprovedRoots:
    roots: tuple[Path, ...] = ()

    @classmethod
    def from_paths(cls, paths: Iterable[Path]) -> "ApprovedRoots":
        resolved: list[Path] = []
        for raw in paths:
            candidate = Path(raw).expanduser().resolve()
            if candidate not in resolved:
                resolved.append(candidate)
        return cls(roots=tuple(resolved))

    def is_approved(self, path: Path) -> bool:
        return any(path_is_under(path, root) for root in self.roots)

    def resolve_approved(self, raw_source: Any, default_source: Path | None = None) -> Path:
        source = resolve_source_path(raw_source, default_source=default_source)
        if not self.is_approved(source):
            raise PermissionError(self.denial_message(source))
        return source

    def denial_message(self, source: Path) -> str:
        listed = "\n".join(f"  {root}" for root in self.roots) if self.roots else "  (none)"
        return (
            f"Source is not under an approved root: {source}\n\n"
            f"Approved roots:\n{listed}\n\n"
            "Restart with:\n"
            f"  normal web --allow-root {source}"
        )


def detect_source_flags(source: Path) -> tuple[str, ...]:
    candidate = source.expanduser()
    if not candidate.exists():
        return (SOURCE_MISSING,)
    if not candidate.is_dir():
        return (NOT_DIRECTORY,)

    flags: list[str] = []
    resolved = candidate.resolve()
    if resolved == Path(resolved.anchor):
        flags.append(DRIVE_DIRECTORY)
    elif os.path.ismount(resolved):
        flags.append(MOUNT_ROOT)
    if hasattr(os.path, "isjunction") and os.path.isjunction(candidate):
        flags.append(JUNCTION)
    return tuple(flags)


def classify_source(source: Path, *, operation: Operation | str) -> SourceRisk:
    operation = Operation(operation)
    flags = detect_source_flags(source)
    blocking = _BLOCK_FLAGS_BY_OPERATION[operation]
    if any(flag in blocking for flag in flags):
        severity: Severity = "block"
    elif flags:
        severity = "warn"
    else:
        severity = "ok"
    return SourceRisk(source=source.expanduser().resolve(), flags=flags, severity=severity)


def validate_source_for_operation(
    source: Path,
    *,
    operation: Operation | str,
    approved_roots: ApprovedRoots | None = None,
    candidate_paths: Iterable[Path | str] = (),
) -> Path:
    operation = Operation(operation)
    risk = classify_source(source, operation=operation)
    if risk.severity == "block":
        raise SourcePolicyError(
            f"Refusing {operation.value} on {risk.source}: it is a {', '.join(risk.flags)}. "
            "Point the source at a library folder inside the drive or mount."
        )
    if approved_roots is not None and not approved_roots.is_approved(risk.source):
        raise SourcePolicyError(approved_roots.denial_message(risk.source))
    for candidate in candidate_paths:
        if not path_is_under(candidate, risk.source):
            raise SourcePolicyError(
                f"Refusing {operation.value}: candidate path escapes source root: "
                f"{Path(candidate).expanduser().resolve()}"
            )
    return risk.source


class SourcePolicyError(RuntimeError):
    pass


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    return bool(hasattr(os.path, "isjunction") and os.path.isjunction(path))


def validate_candidate_for_mutation(
    candidate: Path | str,
    source: Path | str,
    approved_roots: ApprovedRoots | None = None,
) -> Path:
    resolved_source = Path(source).expanduser().resolve()
    lexical_candidate = Path(candidate).expanduser()
    if not lexical_candidate.is_absolute():
        lexical_candidate = lexical_candidate.absolute()

    try:
        lexical_candidate.relative_to(resolved_source)
    except ValueError as exc:
        raise SourcePolicyError(
            f"Refusing mutation: candidate path escapes source root: {lexical_candidate}"
        ) from exc

    current = lexical_candidate
    while current != resolved_source:
        if _is_link_or_junction(current):
            raise SourcePolicyError(
                f"Refusing mutation through symlink or junction: {lexical_candidate}"
            )
        current = current.parent

    resolved_candidate = lexical_candidate.resolve()
    if not path_is_under(resolved_candidate, resolved_source):
        raise SourcePolicyError(
            f"Refusing mutation: candidate path escapes source root: {resolved_candidate}"
        )
    if approved_roots is not None and not approved_roots.is_approved(resolved_candidate):
        raise SourcePolicyError(approved_roots.denial_message(resolved_candidate))
    return resolved_candidate
