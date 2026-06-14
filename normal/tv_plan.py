from __future__ import annotations

from pathlib import Path

from normal.models import ChangePlan, ProposedChange, WarningItem, build_empty_plan
from normal.movie_enriched import EnrichedLibraryReport
from normal.movie_scan import discover_video_files
from normal.tv_identity import TvIdentity, parse_tv_identity


def build_tv_plan(
    source_root: Path,
    *,
    tv_files: list[Path] | None = None,
    parsed_tv: dict[Path, TvIdentity] | None = None,
    enriched_report: EnrichedLibraryReport | None = None,
) -> ChangePlan:
    plan = build_empty_plan(source_root)
    if enriched_report is not None:
        tv_files = [Path(item.path) for item in enriched_report.files]
        parsed_tv = parsed_tv_from_enriched(enriched_report)
    elif tv_files is None:
        tv_files = discover_video_files(source_root)

    if not tv_files:
        plan.warnings.append(
            WarningItem(
                code="no_video_files",
                message="No supported video files were found under the source directory.",
                path=str(source_root),
            )
        )
        return plan

    identities = parsed_tv or {}
    for path in sorted(tv_files):
        identity = identities.get(path) or parse_tv_identity(path, source_root=source_root)
        append_tv_file_change(plan, source_root, path, identity)
    return plan


def parsed_tv_from_enriched(report: EnrichedLibraryReport) -> dict[Path, TvIdentity]:
    parsed: dict[Path, TvIdentity] = {}
    for item in report.files:
        if item.identity is None or item.identity.lane != "tv":
            continue
        if isinstance(item.identity.value, TvIdentity):
            parsed[Path(item.path)] = item.identity.value
    return parsed


def append_tv_file_change(plan: ChangePlan, source_root: Path, path: Path, identity: TvIdentity) -> None:
    target_name = canonical_tv_filename(path, identity)
    reason_codes = list(identity.reason_codes)
    warnings = list(identity.warnings)
    confidence = identity.confidence

    if path.parent.resolve() == source_root.resolve() and identity.season is not None:
        confidence = "review"
        reason_codes.append("tv_loose_root_episode")
        warnings.append("Season-numbered episode is loose at the TV source root; folder restructuring is out of scope.")

    target_path = path.with_name(target_name)
    if target_name != path.name and target_path.exists():
        confidence = "review"
        reason_codes.append("tv_filename_target_collision")
        warnings.append("The proposed filename already exists.")

    if target_name == path.name and confidence == "safe":
        return

    if warnings:
        plan.warnings.append(
            WarningItem(
                code=reason_codes[-1] if reason_codes else "tv_identity_review",
                message=" ".join(warnings),
                path=str(path),
                reason_codes=reason_codes,
            )
        )

    plan.proposed_changes.append(
        ProposedChange(
            item_id=f"{path.relative_to(source_root)}#file",
            change_type="file_rename",
            current_value=path.name,
            proposed_value=target_name,
            confidence=confidence,
            reason=tv_change_reason(identity, confidence),
            path=str(path),
            reason_codes=reason_codes,
            warning_codes=reason_codes if confidence == "review" else [],
        )
    )


def canonical_tv_filename(path: Path, identity: TvIdentity) -> str:
    if not identity.series or identity.episode_first is None and identity.absolute_episode is None:
        return path.name

    if identity.season is not None and identity.episode_first is not None:
        number = f"S{identity.season:02d}E{identity.episode_first:02d}"
        if identity.episode_last is not None:
            number += f"-E{identity.episode_last:02d}"
    else:
        number = f"{identity.absolute_episode:02d}"

    parts = [identity.series, number]
    if identity.episode_title:
        parts.append(identity.episode_title)
    return " - ".join(parts) + path.suffix


def tv_change_reason(identity: TvIdentity, confidence: str) -> str:
    if confidence == "review":
        return "TV filename needs review before numbering or renaming can be applied."
    if identity.numbering == "absolute" and identity.season_source != "folder":
        return "TV filename was cosmetically normalized while preserving absolute episode numbering."
    if identity.season_source == "folder":
        return "TV filename was normalized using absolute episode numbering corroborated by a season folder."
    if identity.numbering == "of_total":
        return "TV miniseries filename was normalized from explicit N of M numbering."
    return "TV filename was normalized from explicit season and episode numbering."
