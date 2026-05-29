from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from normal.models import ProposedChange, WarningItem
from normal.movie_plan import parse_movie_name_with_sidecar_fallback
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


def build_movie_normalize_results(
    source_root: Path,
    movie_files: list[Path],
    plan_changes: list[ProposedChange],
    warnings: list[WarningItem] | None = None,
    parsed_movies: dict[Path, Any] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    warnings = warnings or []
    change_index = index_movie_normalize_changes(plan_changes)
    warning_index = index_movie_normalize_warnings(source_root, warnings)
    for movie_path in sorted(movie_files, key=lambda path: str(path.relative_to(source_root)).casefold()):
        relative_path = movie_path.relative_to(source_root)
        linked_changes = movie_normalize_changes_for_file(relative_path, movie_path, change_index)
        projected_path = projected_movie_normalize_path(relative_path, movie_path, linked_changes)
        parsed = parsed_movies.get(movie_path) if parsed_movies is not None else None
        if parsed is None:
            parsed = parse_movie_name_with_sidecar_fallback(movie_path)
        linked_warning_codes = warning_codes_for_movie(relative_path, movie_path, warning_index)
        confidence = "unchanged"
        if linked_changes:
            confidence = "review" if any(change.confidence == "review" for change in linked_changes) else "safe"
        elif linked_warning_codes or parsed.confidence == "review":
            confidence = "review"
        reason_codes = dedupe_strings(
            [
                *parsed.reason_codes,
                *(code for change in linked_changes for code in change.reason_codes),
            ]
        )
        reason_messages = dedupe_strings(
            [
                *parsed.reason_messages,
                *(change.reason for change in linked_changes if change.reason),
            ]
        )
        warning_codes = list(linked_warning_codes)
        if parsed.confidence == "review":
            warning_codes.extend(parsed.reason_codes)
        results.append(
            {
                "result_id": f"movie:{relative_path}",
                "kind": "movie_file",
                "path": str(movie_path),
                "current_value": str(relative_path),
                "proposed_value": str(projected_path),
                "projected_path": str(projected_path),
                "confidence": confidence,
                "actionable": bool(linked_changes),
                "change_ids": [change.item_id for change in linked_changes],
                "linked_change_types": dedupe_strings([change.change_type for change in linked_changes]),
                "reason_codes": reason_codes,
                "reason_messages": reason_messages,
                "warning_codes": dedupe_strings(warning_codes),
                "title_source": parsed.title_source,
                "year_source": parsed.year_source,
                "parse_source_path": parsed.parse_source_path,
                "compact_token_traces": parsed.compact_token_traces or [],
            }
        )
    return results


def movie_normalize_changes_for_file(
    relative_path: Path,
    movie_path: Path,
    change_index: dict[str, Any] | list[ProposedChange],
) -> list[ProposedChange]:
    if isinstance(change_index, list):
        change_index = index_movie_normalize_changes(change_index)
    relative_text = str(relative_path)
    relative_parent = str(relative_path.parent) if str(relative_path.parent) != "." else ""
    linked = list(change_index["file_changes"].get(str(movie_path), []))
    for current, change in change_index["folder_renames"]:
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


def warning_codes_for_movie(relative_path: Path, movie_path: Path, warning_index: dict[str, list[str]]) -> list[str]:
    relative_text = str(relative_path)
    parent_text = str(relative_path.parent)
    movie_text = str(movie_path)
    parent_abs = str(movie_path.parent)
    return dedupe_strings(
        [
            *warning_index.get(relative_text, []),
            *warning_index.get(movie_text, []),
            *warning_index.get(parent_text, []),
            *warning_index.get(parent_abs, []),
        ]
    )


def index_movie_normalize_changes(plan_changes: list[ProposedChange]) -> dict[str, Any]:
    file_changes: dict[str, list[ProposedChange]] = {}
    folder_renames: list[tuple[str, ProposedChange]] = []
    for change in plan_changes:
        if change.change_type in {"file_rename", "file_move"} and change.path:
            file_changes.setdefault(change.path, []).append(change)
            continue
        if change.change_type == "folder_rename" and change.current_value:
            folder_renames.append((change.current_value, change))
    folder_renames.sort(key=lambda item: len(item[0]), reverse=True)
    return {"file_changes": file_changes, "folder_renames": folder_renames}


def index_movie_normalize_warnings(source_root: Path, warnings: list[WarningItem]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for warning in warnings:
        if not warning.path:
            continue
        keys = [warning.path]
        try:
            path = Path(warning.path)
            if path.is_absolute():
                keys.append(str(path.relative_to(source_root)))
        except ValueError:
            pass
        for key in keys:
            index.setdefault(key, []).append(warning.code)
    return index


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


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
