from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from normal.models import ProposedChange, WarningItem
from normal.movie_canonical_lists import resolve_imdb_ids
from normal.movie_plan import parse_movie_name_with_sidecar_fallback
from normal.movie_profile import (
    build_default_source_definition,
    MovieProfileReport,
    build_delete_mode_definition,
    build_histogram_payload,
    build_movie_profile_definitions,
    build_policy_definitions,
    build_movie_profile_item,
    build_library_defaults_definition,
    library_policy_revision,
    load_library_policy,
    load_operator_preferences,
    operator_preferences_revision,
    build_replacement_candidate_definition,
    load_movie_standards,
    movie_standards_revision,
    movie_identity_from_slot,
    normalized_subtitle_preferences,
)
from normal.movie_repair_planner import build_movie_repair_plan
from normal.movie_scan import media_facts_from_dict
from normal.tv_identity import TvIdentity


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
        serialized_linked_changes = [serialize_proposed_change(change) for change in linked_changes]
        safe_linked_changes = [change for change in linked_changes if change.confidence == "safe"]
        projected_path = projected_movie_normalize_path(relative_path, movie_path, linked_changes)
        parsed = parsed_movies.get(movie_path) if parsed_movies is not None else None
        if parsed is None:
            parsed = parse_movie_name_with_sidecar_fallback(movie_path)
        linked_warnings = warning_details_for_movie(relative_path, movie_path, warning_index)
        linked_warning_codes = [warning["code"] for warning in linked_warnings]
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
                "actionable": bool(safe_linked_changes),
                "change_ids": [change.item_id for change in safe_linked_changes],
                "linked_change_types": dedupe_strings([change.change_type for change in linked_changes]),
                "linked_changes": serialized_linked_changes,
                "reason_codes": reason_codes,
                "reason_messages": reason_messages,
                "warning_codes": dedupe_strings(warning_codes),
                "warning_messages": dedupe_strings([warning["message"] for warning in linked_warnings]),
                "warnings": linked_warnings,
                "title_source": parsed.title_source,
                "year_source": parsed.year_source,
                "parse_source_path": parsed.parse_source_path,
                "compact_token_traces": parsed.compact_token_traces or [],
            }
        )
    return results


def build_tv_normalize_results(
    source_root: Path,
    tv_files: list[Path],
    plan_changes: list[ProposedChange],
    warnings: list[WarningItem] | None = None,
    parsed_tv: dict[Path, TvIdentity] | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    warning_index = index_movie_normalize_warnings(source_root, warnings or [])
    changes_by_path: dict[str, list[ProposedChange]] = {}
    for change in plan_changes:
        if change.change_type == "file_rename" and change.path:
            changes_by_path.setdefault(change.path, []).append(change)

    for tv_path in sorted(tv_files, key=lambda path: str(path.relative_to(source_root)).casefold()):
        relative_path = tv_path.relative_to(source_root)
        linked_changes = changes_by_path.get(str(tv_path), [])
        safe_linked_changes = [change for change in linked_changes if change.confidence == "safe"]
        identity = parsed_tv.get(tv_path) if parsed_tv is not None else None
        if identity is None:
            from normal.tv_identity import parse_tv_identity

            identity = parse_tv_identity(tv_path, source_root=source_root)
        linked_warnings = warning_details_for_movie(relative_path, tv_path, warning_index)
        projected_path = relative_path
        if linked_changes:
            projected_path = relative_path.with_name(linked_changes[0].proposed_value)
        confidence = "unchanged"
        if linked_changes:
            confidence = "review" if any(change.confidence == "review" for change in linked_changes) else "safe"
        elif linked_warnings or identity.confidence == "review":
            confidence = "review"

        results.append(
            {
                "result_id": f"tv:{relative_path}",
                "kind": "tv_file",
                "path": str(tv_path),
                "current_value": str(relative_path),
                "proposed_value": str(projected_path),
                "projected_path": str(projected_path),
                "confidence": confidence,
                "actionable": bool(safe_linked_changes),
                "change_ids": [change.item_id for change in safe_linked_changes],
                "linked_change_types": dedupe_strings([change.change_type for change in linked_changes]),
                "linked_changes": [serialize_proposed_change(change) for change in linked_changes],
                "reason_codes": dedupe_strings(
                    [
                        *identity.reason_codes,
                        *(code for change in linked_changes for code in change.reason_codes),
                    ]
                ),
                "reason_messages": dedupe_strings(
                    [
                        *identity.warnings,
                        *(change.reason for change in linked_changes if change.reason),
                    ]
                ),
                "warning_codes": dedupe_strings(
                    [
                        *(warning["code"] for warning in linked_warnings),
                        *(identity.reason_codes if identity.confidence == "review" else []),
                    ]
                ),
                "warning_messages": dedupe_strings([warning["message"] for warning in linked_warnings]),
                "warnings": linked_warnings,
                "series": identity.series,
                "season": identity.season,
                "episode_first": identity.episode_first,
                "episode_last": identity.episode_last,
                "absolute_episode": identity.absolute_episode,
                "season_length": identity.season_length,
                "episode_title": identity.episode_title,
                "numbering": identity.numbering,
                "identity_confidence": identity.confidence,
                "series_source": identity.series_source,
                "season_source": identity.season_source,
                "parse_source_path": identity.parse_source_path,
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
    index: dict[str, list[dict[str, Any]]] = {}
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
            index.setdefault(key, []).append(
                {
                    "code": warning.code,
                    "message": warning.message,
                    "path": warning.path,
                    "reason_codes": list(warning.reason_codes),
                }
            )
    return index


def warning_details_for_movie(relative_path: Path, movie_path: Path, warning_index: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    relative_text = str(relative_path)
    parent_text = str(relative_path.parent)
    movie_text = str(movie_path)
    parent_abs = str(movie_path.parent)
    return dedupe_warning_details(
        [
            *warning_index.get(relative_text, []),
            *warning_index.get(movie_text, []),
            *warning_index.get(parent_text, []),
            *warning_index.get(parent_abs, []),
        ]
    )


def serialize_proposed_change(change: ProposedChange) -> dict[str, Any]:
    return {
        "item_id": change.item_id,
        "change_type": change.change_type,
        "current_value": change.current_value,
        "proposed_value": change.proposed_value,
        "confidence": change.confidence,
        "reason": change.reason,
        "path": change.path,
        "reason_codes": list(change.reason_codes),
        "warning_codes": list(change.warning_codes),
    }


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def dedupe_warning_details(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    ordered: list[dict[str, Any]] = []
    for value in values:
        code = str(value.get("code") or "")
        message = str(value.get("message") or "")
        path = str(value.get("path") or "")
        key = (code, message, path)
        if not code or key in seen:
            continue
        seen.add(key)
        ordered.append(
            {
                "code": code,
                "message": message,
                "path": path,
                "reason_codes": [str(item) for item in value.get("reason_codes", []) if str(item)],
            }
        )
    return ordered


def build_profile_response(
    source: Path,
    report: MovieProfileReport,
    standards: dict[str, Any] | None = None,
    *,
    resolve_language: Callable[[str, int | None], str | None] | None = None,
) -> dict[str, Any]:
    standards_payload = standards if standards is not None else load_library_policy()
    operator_preferences = load_operator_preferences()
    response = report.to_dict()
    identities = [movie_identity_from_slot(item.identity) for item in report.movies]
    imdb_ids = resolve_imdb_ids(identities)
    for payload_item, identity, imdb_id in zip(response.get("movies", []), identities, imdb_ids):
        if identity is None:
            continue
        payload_item["title"] = identity.title
        payload_item["year"] = identity.year
        payload_item["imdb_id"] = imdb_id
    attach_repair_plans_to_payload_movies(response.get("movies"), standards_payload, resolve_language=resolve_language)
    response["histogram"] = build_histogram_payload(report)
    response["policy"] = standards_payload
    response["policy_revision"] = library_policy_revision(standards_payload)
    response["operator_preferences"] = operator_preferences
    response["operator_preferences_revision"] = operator_preferences_revision(operator_preferences)
    response["policy_definitions"] = build_policy_definitions(standards_payload, operator_preferences)
    response["default_source_definition"] = build_default_source_definition(operator_preferences)
    response["library_defaults_definition"] = build_library_defaults_definition(standards_payload)
    response["delete_mode_definition"] = build_delete_mode_definition(operator_preferences)
    response["movie_standards"] = standards_payload
    response["movie_standards_revision"] = movie_standards_revision(standards_payload)
    response["quality_profile_definitions"] = build_movie_profile_definitions(standards_payload)
    response["replacement_candidate_definition"] = build_replacement_candidate_definition(standards_payload)
    return response


def build_updated_profile_items(
    source: Path,
    fixed_items: list[dict[str, Any]],
    *,
    resolve_language: Callable[[str, int | None], str | None] | None = None,
) -> list[dict[str, Any]]:
    subtitle_preferences = normalized_subtitle_preferences(load_library_policy().get("subtitle_preferences"))
    updated_items = []
    for item in fixed_items:
        raw_facts = item.get("facts")
        if not isinstance(raw_facts, dict):
            continue
        movie_path = Path(str(item["path"]))
        parsed_facts = media_facts_from_dict(raw_facts)
        profiled = build_movie_profile_item(source, movie_path, parsed_facts, resolve_language=resolve_language)
        payload = asdict(profiled)
        payload["repair_plan"] = build_movie_repair_plan(
            parsed_facts,
            path=payload.get("path"),
            subtitle_preferences=subtitle_preferences,
            resolve_language=resolve_language,
        )
        updated_items.append(payload)
    return updated_items


def attach_repair_plans_to_payload_movies(
    movies: Any,
    standards_payload: dict[str, Any],
    *,
    resolve_language: Callable[[str, int | None], str | None] | None = None,
) -> None:
    if not isinstance(movies, list):
        return
    subtitle_preferences = normalized_subtitle_preferences(standards_payload.get("subtitle_preferences"))
    for item in movies:
        if not isinstance(item, dict):
            continue
        raw_facts = item.get("facts")
        if not isinstance(raw_facts, dict):
            continue
        item["repair_plan"] = build_movie_repair_plan(
            media_facts_from_dict(raw_facts),
            path=str(item.get("path") or ""),
            subtitle_preferences=subtitle_preferences,
            resolve_language=resolve_language,
        )
