from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from normal.models import ProposedChange
from normal.source_policy import ApprovedRoots, validate_candidate_for_mutation


MOVIE_SIDECAR_EXTENSIONS = {
    ".nfo",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".srt",
    ".sub",
    ".idx",
    ".ass",
    ".ssa",
    ".vtt",
    ".txt",
    ".xml",
}


@dataclass(slots=True)
class ApplyResult:
    item_id: str
    change_type: str
    status: str
    path: str | None = None
    message: str = ""


@dataclass(slots=True)
class ApplyReport:
    source_root: str
    plan_path: str
    target_root: str
    mode: str
    applied: list[ApplyResult] = field(default_factory=list)
    skipped: list[ApplyResult] = field(default_factory=list)
    failed: list[ApplyResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_plan(plan_path: Path) -> dict[str, Any]:
    return json.loads(plan_path.read_text(encoding="utf-8"))


def apply_plan(
    source_root: Path,
    plan_path: Path,
    target_root: Path | None,
    in_place: bool,
    report_filename: str = "normal-apply-report.json",
) -> ApplyReport:
    payload = load_plan(plan_path)
    planned_source = Path(payload["source_root"]).resolve()
    if planned_source != source_root.resolve():
        raise ValueError(
            f"plan source_root does not match --source: {planned_source} != {source_root.resolve()}"
        )

    skipped_symlinks: list[ApplyResult] = []
    if in_place:
        destination_root = source_root.resolve()
    else:
        destination_root, skipped_symlinks = prepare_target_root(source_root, target_root)
    report = ApplyReport(
        source_root=str(source_root.resolve()),
        plan_path=str(plan_path.resolve()),
        target_root=str(destination_root),
        mode="in_place" if in_place else "target",
    )
    report.skipped.extend(skipped_symlinks)

    proposed_changes = [ProposedChange(**change_data) for change_data in payload.get("proposed_changes", [])]

    for change in [c for c in proposed_changes if c.change_type not in {"folder_rename", "folder_merge", "folder_delete"}]:
        if change.confidence != "safe":
            report.skipped.append(
                ApplyResult(
                    item_id=change.item_id,
                    change_type=change.change_type,
                    status="skipped",
                    path=change.path,
                    message="Skipped review change.",
                )
            )
            continue

        try:
            result = apply_change(source_root, destination_root, change)
        except Exception as exc:
            report.failed.append(
                ApplyResult(
                    item_id=change.item_id,
                    change_type=change.change_type,
                    status="failed",
                    path=change.path,
                    message=str(exc),
                )
            )
            continue

        collection = report.applied if result.status == "applied" else report.skipped
        collection.append(result)

    for change in sorted(
        [c for c in proposed_changes if c.change_type in {"folder_rename", "folder_merge", "folder_delete"}],
        key=lambda c: len(Path(c.current_value).parts),
        reverse=True,
    ):
        if change.confidence != "safe":
            report.skipped.append(
                ApplyResult(
                    item_id=change.item_id,
                    change_type=change.change_type,
                    status="skipped",
                    path=change.path,
                    message="Skipped review change.",
                )
            )
            continue

        try:
            result = apply_change(source_root, destination_root, change)
        except Exception as exc:
            report.failed.append(
                ApplyResult(
                    item_id=change.item_id,
                    change_type=change.change_type,
                    status="failed",
                    path=change.path,
                    message=str(exc),
                )
            )
            continue

        collection = report.applied if result.status == "applied" else report.skipped
        collection.append(result)

    write_apply_report(destination_root, report, report_filename=report_filename)
    return report


def prepare_target_root(source_root: Path, target_root: Path | None) -> tuple[Path, list[ApplyResult]]:
    if target_root is None:
        raise ValueError("target_root is required when not applying in place")

    destination_root = target_root.expanduser().resolve()
    if destination_root.exists():
        existing_entries = list(destination_root.iterdir())
        if existing_entries:
            raise FileExistsError(f"target directory is not empty: {destination_root}")
    else:
        destination_root.mkdir(parents=True, exist_ok=True)

    skipped_symlinks = copy_source_tree(source_root.resolve(), destination_root)
    return destination_root, skipped_symlinks


def copy_source_tree(source_root: Path, destination_root: Path) -> list[ApplyResult]:
    skipped_symlinks: list[ApplyResult] = []
    for source_path in sorted(source_root.rglob("*")):
        relative_path = source_path.relative_to(source_root)
        destination_path = destination_root / relative_path
        if source_path.is_symlink():
            try:
                source_path.resolve().relative_to(source_root)
                escaped = False
            except ValueError:
                escaped = True
            message = f"Skipped symlink -> {source_path.readlink()}"
            if escaped:
                message += " (target outside source root)"
            skipped_symlinks.append(
                ApplyResult(
                    item_id=str(relative_path),
                    change_type="symlink",
                    status="skipped",
                    path=str(source_path),
                    message=message,
                )
            )
            continue
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        if destination_path.exists():
            raise FileExistsError(f"refusing to overwrite existing file in target: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
    return skipped_symlinks


def validate_basename(value: str) -> str:
    if value in {"", ".", ".."} or "/" in value or "\\" in value or Path(value).is_absolute():
        raise ValueError(f"unsafe rename target: {value!r}")
    return value


def validate_relative_destination(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"unsafe destination path: {value!r}")
    root_resolved = root.resolve()
    resolved = (root_resolved / candidate).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(f"destination path escapes source root: {value!r}")
    return resolved


def apply_change(
    source_root: Path,
    destination_root: Path,
    change: ProposedChange,
    approved_roots: ApprovedRoots | None = None,
) -> ApplyResult:
    if change.path is None:
        raise ValueError("proposed change is missing path")

    source_path = validate_candidate_for_mutation(change.path, source_root, approved_roots)
    relative_path = source_path.relative_to(source_root.resolve())
    destination_path = destination_root / relative_path
    destination_path = validate_candidate_for_mutation(
        destination_path,
        destination_root,
        approved_roots if destination_root.resolve() == source_root.resolve() else None,
    )

    if not destination_path.exists():
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_path),
            message="Destination path is missing.",
        )

    if change.change_type == "file_rename":
        return apply_file_rename(destination_path, destination_root, change, approved_roots)
    if change.change_type == "file_delete":
        return apply_file_delete(destination_path, change)
    if change.change_type == "file_move":
        return apply_file_move(destination_path, destination_root, change, approved_roots)
    if change.change_type == "folder_merge":
        return apply_folder_merge(source_root, destination_root, change, approved_roots)
    if change.change_type == "folder_delete":
        return apply_folder_delete(source_root, destination_root, change, approved_roots)
    if change.change_type == "folder_rename":
        return apply_folder_rename(source_root, destination_root, change, approved_roots)
    return ApplyResult(
        item_id=change.item_id,
        change_type=change.change_type,
        status="skipped",
        path=str(destination_path),
        message="Unsupported change type.",
    )


def apply_file_rename(
    destination_path: Path,
    destination_root: Path,
    change: ProposedChange,
    approved_roots: ApprovedRoots | None,
) -> ApplyResult:
    validate_basename(change.proposed_value)
    if destination_path.name != change.current_value:
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_path),
            message="Filename drifted from the plan current_value.",
        )

    renamed_path = destination_path.with_name(change.proposed_value)
    if renamed_path.exists():
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(renamed_path),
            message="Rename target already exists.",
        )

    destination_path = validate_candidate_for_mutation(
        destination_path,
        destination_root,
        approved_roots,
    )
    destination_path.rename(renamed_path)
    sidecar_count = move_matching_sidecars(
        destination_path,
        renamed_path,
        destination_root,
        approved_roots,
    )
    return ApplyResult(
        item_id=change.item_id,
        change_type=change.change_type,
        status="applied",
        path=str(renamed_path),
        message=f"File renamed{format_sidecar_count(sidecar_count)}.",
    )


def apply_file_move(
    destination_path: Path,
    destination_root: Path,
    change: ProposedChange,
    approved_roots: ApprovedRoots | None,
) -> ApplyResult:
    if destination_path.name != change.current_value:
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_path),
            message="Filename drifted from the plan current_value.",
        )

    moved_path = validate_relative_destination(destination_root, change.proposed_value)
    if moved_path.exists():
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(moved_path),
            message="Move target already exists.",
        )

    moved_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path = validate_candidate_for_mutation(
        destination_path,
        destination_root,
        approved_roots,
    )
    destination_path.rename(moved_path)
    sidecar_count = move_matching_sidecars(
        destination_path,
        moved_path,
        destination_root,
        approved_roots,
    )
    return ApplyResult(
        item_id=change.item_id,
        change_type=change.change_type,
        status="applied",
        path=str(moved_path),
        message=f"File moved{format_sidecar_count(sidecar_count)}.",
    )


def apply_file_delete(destination_path: Path, change: ProposedChange) -> ApplyResult:
    destination_path.unlink()
    return ApplyResult(
        item_id=change.item_id,
        change_type=change.change_type,
        status="applied",
        path=str(destination_path),
        message="File deleted.",
    )


def move_matching_sidecars(
    old_media_path: Path,
    new_media_path: Path,
    destination_root: Path,
    approved_roots: ApprovedRoots | None,
) -> int:
    moved_count = 0
    for sidecar in discover_matching_sidecars(old_media_path):
        target = new_media_path.parent / renamed_sidecar_name(sidecar.name, old_media_path.stem, new_media_path.stem)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        sidecar = validate_candidate_for_mutation(
            sidecar,
            destination_root,
            approved_roots,
        )
        sidecar.rename(target)
        moved_count += 1
    return moved_count


def discover_matching_sidecars(media_path: Path) -> list[Path]:
    if not media_path.parent.exists():
        return []
    old_stem = media_path.stem
    sidecars: list[Path] = []
    for entry in sorted(media_path.parent.iterdir()):
        if entry == media_path or not entry.is_file():
            continue
        if entry.suffix.lower() not in MOVIE_SIDECAR_EXTENSIONS:
            continue
        if is_matching_sidecar_stem(entry.stem, old_stem):
            sidecars.append(entry)
    return sidecars


def is_matching_sidecar_stem(sidecar_stem: str, media_stem: str) -> bool:
    return (
        sidecar_stem == media_stem
        or sidecar_stem.startswith(media_stem + "-")
        or sidecar_stem.startswith(media_stem + ".")
    )


def renamed_sidecar_name(sidecar_name: str, old_stem: str, new_stem: str) -> str:
    if sidecar_name.startswith(old_stem):
        return new_stem + sidecar_name[len(old_stem):]
    return sidecar_name


def format_sidecar_count(count: int) -> str:
    if count == 0:
        return ""
    return f" with {count} sidecar{'s' if count != 1 else ''}"


def apply_folder_rename(
    source_root: Path,
    destination_root: Path,
    change: ProposedChange,
    approved_roots: ApprovedRoots | None,
) -> ApplyResult:
    if change.path is None:
        raise ValueError("folder rename is missing path")

    source_dir = Path(change.path).resolve()
    relative_current = source_dir.relative_to(source_root.resolve())
    destination_dir = destination_root / relative_current
    if not destination_dir.exists():
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_dir),
            message="Folder path is missing.",
        )

    if str(relative_current) != change.current_value:
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_dir),
            message="Folder path drifted from the plan current_value.",
        )

    target_dir = validate_relative_destination(destination_root, change.proposed_value)
    if target_dir.exists():
        if target_dir.samefile(destination_dir):
            return ApplyResult(
                item_id=change.item_id,
                change_type=change.change_type,
                status="skipped",
                path=str(target_dir),
                message="Folder already matches proposed path.",
            )
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(target_dir),
            message="Folder rename target already exists.",
        )

    validate_candidate_for_mutation(target_dir, destination_root, approved_roots)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    destination_dir = validate_candidate_for_mutation(destination_dir, destination_root, approved_roots)
    target_dir = validate_candidate_for_mutation(target_dir, destination_root, approved_roots)
    destination_dir.rename(target_dir)
    move_wrapper_sidecars_after_collapse(
        destination_root,
        relative_current,
        target_dir,
        destination_dir.parent,
        approved_roots,
    )
    prune_empty_parents(destination_root, destination_dir.parent, approved_roots)
    return ApplyResult(
        item_id=change.item_id,
        change_type=change.change_type,
        status="applied",
        path=str(target_dir),
        message="Folder renamed.",
    )


def apply_folder_merge(
    source_root: Path,
    destination_root: Path,
    change: ProposedChange,
    approved_roots: ApprovedRoots | None,
) -> ApplyResult:
    if change.path is None:
        raise ValueError("folder merge is missing path")

    source_dir = Path(change.path).resolve()
    relative_current = source_dir.relative_to(source_root.resolve())
    destination_dir = destination_root / relative_current
    if not destination_dir.exists():
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_dir),
            message="Folder path is missing.",
        )
    if str(relative_current) != change.current_value:
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_dir),
            message="Folder path drifted from the plan current_value.",
        )

    target_dir = validate_relative_destination(destination_root, change.proposed_value)
    if not target_dir.exists() or not target_dir.is_dir():
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(target_dir),
            message="Folder merge target is missing.",
        )

    moved_count = 0
    for entry in sorted(destination_dir.iterdir()):
        target = target_dir / entry.name
        if target.exists():
            return ApplyResult(
                item_id=change.item_id,
                change_type=change.change_type,
                status="skipped",
                path=str(target),
                message="Folder merge target already contains an entry with the same name.",
            )
        entry = validate_candidate_for_mutation(entry, destination_root, approved_roots)
        target = validate_candidate_for_mutation(target, destination_root, approved_roots)
        entry.rename(target)
        moved_count += 1
    prune_empty_parents(destination_root, destination_dir, approved_roots)
    return ApplyResult(
        item_id=change.item_id,
        change_type=change.change_type,
        status="applied",
        path=str(target_dir),
        message=f"Folder merged with {moved_count} entr{'y' if moved_count == 1 else 'ies'}.",
    )


def apply_folder_delete(
    source_root: Path,
    destination_root: Path,
    change: ProposedChange,
    approved_roots: ApprovedRoots | None,
) -> ApplyResult:
    if change.path is None:
        raise ValueError("folder delete is missing path")

    source_dir = Path(change.path).resolve()
    relative_current = source_dir.relative_to(source_root.resolve())
    destination_dir = destination_root / relative_current
    if not destination_dir.exists():
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_dir),
            message="Folder path is missing.",
        )
    if str(relative_current) != change.current_value:
        return ApplyResult(
            item_id=change.item_id,
            change_type=change.change_type,
            status="skipped",
            path=str(destination_dir),
            message="Folder path drifted from the plan current_value.",
        )
    destination_dir = validate_candidate_for_mutation(destination_dir, destination_root, approved_roots)
    shutil.rmtree(destination_dir)
    prune_empty_parents(destination_root, destination_dir.parent, approved_roots)
    return ApplyResult(
        item_id=change.item_id,
        change_type=change.change_type,
        status="applied",
        path=str(destination_dir),
        message="Folder deleted.",
    )


def move_wrapper_sidecars_after_collapse(
    destination_root: Path,
    relative_current: Path,
    target_dir: Path,
    old_parent: Path,
    approved_roots: ApprovedRoots | None,
) -> None:
    current_parts = relative_current.parts
    target_relative = target_dir.relative_to(destination_root)
    target_parts = target_relative.parts
    is_collapse = (
        len(current_parts) >= 2
        and len(target_parts) == len(current_parts) - 1
        and target_parts[:-1] == current_parts[:-2]
    )
    if not is_collapse:
        return

    for entry in sorted(old_parent.iterdir()):
        if entry.is_dir():
            return
        target = target_dir / entry.name
        if target.exists():
            continue
        entry = validate_candidate_for_mutation(entry, destination_root, approved_roots)
        target = validate_candidate_for_mutation(target, destination_root, approved_roots)
        entry.rename(target)


def prune_empty_parents(
    destination_root: Path,
    start: Path,
    approved_roots: ApprovedRoots | None,
) -> None:
    current = start
    root = destination_root.resolve()
    while current.resolve() != root:
        try:
            current = validate_candidate_for_mutation(current, root, approved_roots)
            current.rmdir()
        except OSError:
            break
        current = current.parent


def apply_changes_in_place(
    source_root: Path,
    changes: list[ProposedChange],
    approved_roots: ApprovedRoots | None = None,
) -> ApplyReport:
    root = source_root.resolve()
    report = ApplyReport(
        source_root=str(root),
        plan_path="",
        target_root=str(root),
        mode="in_place",
    )
    non_folder = [c for c in changes if c.change_type not in {"folder_rename", "folder_merge", "folder_delete"}]
    folder_changes = sorted(
        [c for c in changes if c.change_type in {"folder_rename", "folder_merge", "folder_delete"}],
        key=lambda c: len(Path(c.current_value).parts),
        reverse=True,
    )
    for change in non_folder + folder_changes:
        if change.confidence != "safe":
            report.skipped.append(ApplyResult(
                item_id=change.item_id,
                change_type=change.change_type,
                status="skipped",
                path=change.path,
                message="Skipped review change.",
            ))
            continue
        try:
            result = apply_change(root, root, change, approved_roots)
        except Exception as exc:
            report.failed.append(ApplyResult(
                item_id=change.item_id,
                change_type=change.change_type,
                status="failed",
                path=change.path,
                message=str(exc),
            ))
            continue
        if result.status == "applied":
            report.applied.append(result)
        else:
            report.skipped.append(result)
    return report


def write_apply_report(destination_root: Path, report: ApplyReport, report_filename: str = "normal-apply-report.json") -> Path:
    report_path = destination_root / report_filename
    report_path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return report_path
