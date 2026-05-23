from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from normal.models import ProposedChange
from normal.movie_profile import (
    MovieProfileReport,
    build_histogram_payload,
    build_movie_profile_definitions,
    build_movie_profile_item,
    build_replacement_candidate_definition,
    load_movie_standards,
    movie_standards_revision,
)
from normal.movie_replacement_queue import reconcile_replacement_queue
from normal.movie_scan import media_facts_from_dict


def build_movie_normalize_results(source_root: Path, movie_files: list[Path], plan_changes: list[ProposedChange]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for movie_path in sorted(movie_files, key=lambda path: str(path.relative_to(source_root)).casefold()):
        relative_path = movie_path.relative_to(source_root)
        linked_changes = movie_normalize_changes_for_file(relative_path, movie_path, plan_changes)
        projected_path = projected_movie_normalize_path(relative_path, movie_path, linked_changes)
        confidence = "unchanged"
        if linked_changes:
            confidence = "review" if any(change.confidence == "review" for change in linked_changes) else "safe"
        results.append(
            {
                "result_id": f"movie:{relative_path}",
                "kind": "movie_file",
                "path": str(movie_path),
                "current_value": str(relative_path),
                "proposed_value": str(projected_path),
                "confidence": confidence,
                "actionable": bool(linked_changes),
                "change_ids": [change.item_id for change in linked_changes],
            }
        )
    return results


def movie_normalize_changes_for_file(
    relative_path: Path,
    movie_path: Path,
    plan_changes: list[ProposedChange],
) -> list[ProposedChange]:
    linked: list[ProposedChange] = []
    relative_text = str(relative_path)
    relative_parent = str(relative_path.parent) if str(relative_path.parent) != "." else ""
    for change in plan_changes:
        if change.change_type in {"file_rename", "file_move"} and change.path and Path(change.path).resolve() == movie_path.resolve():
            linked.append(change)
            continue
        if change.change_type == "folder_rename":
            current = change.current_value or ""
            if relative_parent == current or relative_parent.startswith(current + "/") or relative_text == current:
                linked.append(change)
    return linked


def projected_movie_normalize_path(relative_path: Path, movie_path: Path, changes: list[ProposedChange]) -> Path:
    for change in changes:
        if change.change_type == "file_move" and change.path and Path(change.path).resolve() == movie_path.resolve():
            return Path(change.proposed_value)

    proposed_dir = relative_path.parent
    if str(proposed_dir) == ".":
        proposed_dir = Path("")
    for change in sorted((change for change in changes if change.change_type == "folder_rename"), key=lambda item: len(item.current_value), reverse=True):
        current = Path(change.current_value)
        proposed = Path(change.proposed_value)
        try:
            suffix = proposed_dir.relative_to(current)
        except ValueError:
            continue
        proposed_dir = proposed / suffix

    proposed_filename = relative_path.name
    for change in changes:
        if change.change_type == "file_rename" and change.path and Path(change.path).resolve() == movie_path.resolve():
            proposed_filename = change.proposed_value
            break
    return proposed_dir / proposed_filename


def build_profile_response(source: Path, report: MovieProfileReport, standards: dict[str, Any] | None = None) -> dict[str, Any]:
    standards_payload = standards if standards is not None else load_movie_standards()
    response = report.to_dict()
    response["histogram"] = build_histogram_payload(report)
    response["replacement_queue"] = reconcile_replacement_queue(source, response["movies"])
    response["movie_standards"] = standards_payload
    response["movie_standards_revision"] = movie_standards_revision(standards_payload)
    response["quality_profile_definitions"] = build_movie_profile_definitions(standards_payload)
    response["replacement_candidate_definition"] = build_replacement_candidate_definition(standards_payload)
    return response


def build_updated_profile_items(source: Path, fixed_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated_items = []
    for item in fixed_items:
        raw_facts = item.get("facts")
        if not isinstance(raw_facts, dict):
            continue
        movie_path = Path(str(item["path"]))
        profiled = build_movie_profile_item(source, movie_path, media_facts_from_dict(raw_facts))
        updated_items.append(asdict(profiled))
    return updated_items
