from __future__ import annotations

from collections import Counter
from pathlib import Path

from normal.models import ChangePlan, ProposedChange, TrackReport, WarningItem, build_empty_plan
from normal.scan import analyze_library, infer_album_root


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def build_plan(source_root: Path) -> ChangePlan:
    report = analyze_library(source_root)
    plan = build_empty_plan(source_root)
    plan.tracks = report.tracks
    plan.albums = report.albums
    plan.warnings.extend(report.warnings)

    for track in report.tracks:
        plan.warnings.extend(track.issues)
    for album in report.albums:
        plan.warnings.extend(album.warnings)

    for album in report.albums:
        album_tracks = [track for track in report.tracks if infer_album_root(Path(track.path)) == Path(album.path)]
        plan.proposed_changes.extend(plan_albumartist_fill(album_tracks))
        folder_change, folder_warning = plan_album_folder_rename(album, album_tracks, source_root)
        if folder_change is not None:
            plan.proposed_changes.append(folder_change)
        if folder_warning is not None:
            plan.warnings.append(folder_warning)

    for track in report.tracks:
        plan.proposed_changes.extend(plan_track_tag_cleanup(track))
        rename_change = plan_filename_rename(track)
        if rename_change is not None:
            plan.proposed_changes.append(rename_change)

    dedup_changes, dedup_warnings = deduplicate_artist_case(plan.proposed_changes, plan.tracks, source_root)
    plan.proposed_changes = dedup_changes
    plan.warnings.extend(dedup_warnings)

    return plan


def plan_albumartist_fill(album_tracks: list[TrackReport]) -> list[ProposedChange]:
    if not album_tracks:
        return []

    if any(track.tags.get("albumartist") for track in album_tracks):
        return []

    artists = {track.tags.get("artist", "") for track in album_tracks if track.tags.get("artist")}
    if len(artists) != 1:
        return []

    artist = next(iter(artists))
    changes: list[ProposedChange] = []
    for track in album_tracks:
        changes.append(
            ProposedChange(
                item_id=f"{track.track_id}#tag:albumartist",
                change_type="tag_edit",
                current_value="",
                proposed_value=artist,
                confidence="safe",
                reason="albumartist can be filled from unanimous track artist values within the album folder.",
                path=track.path,
            )
        )
    return changes


def plan_track_tag_cleanup(track: TrackReport) -> list[ProposedChange]:
    changes: list[ProposedChange] = []
    for field, value in track.tags.items():
        normalized = normalize_whitespace(value)
        if normalized != value:
            changes.append(
                ProposedChange(
                    item_id=f"{track.track_id}#tag:{field}",
                    change_type="tag_edit",
                    current_value=value,
                    proposed_value=normalized,
                    confidence="safe",
                    reason="Whitespace normalization is deterministic and low risk.",
                    path=track.path,
                )
            )
    return changes


def plan_filename_rename(track: TrackReport) -> ProposedChange | None:
    tracknumber = parse_tracknumber(track.tags.get("tracknumber"))
    title = track.tags.get("title")
    if tracknumber is None or not title:
        return None

    normalized_title = normalize_filename_component(title)
    proposed_name = f"{tracknumber:02d} {normalized_title}{Path(track.path).suffix}"
    current_name = Path(track.path).name
    if proposed_name == current_name:
        return None

    return ProposedChange(
        item_id=f"{track.track_id}#file",
        change_type="file_rename",
        current_value=current_name,
        proposed_value=proposed_name,
        confidence="safe",
        reason="Filename can be derived directly from tracknumber and title.",
        path=track.path,
    )


def parse_tracknumber(value: str | None) -> int | None:
    if not value:
        return None
    head = value.split("/", 1)[0].strip()
    if not head.isdigit():
        return None
    return int(head)


def normalize_filename_component(value: str) -> str:
    normalized = normalize_whitespace(value)
    hostile = '<>:"/\\|?*'
    return "".join("_" if char in hostile else char for char in normalized)


def plan_album_folder_rename(
    album,
    album_tracks: list[TrackReport],
    source_root: Path,
) -> tuple[ProposedChange | None, WarningItem | None]:
    if not album_tracks:
        return None, None

    first_track = album_tracks[0]
    album_artist = first_track.tags.get("albumartist") or first_track.tags.get("artist")
    album_title = first_track.tags.get("album")
    if not album_artist or not album_title:
        return None, None

    normalized_artist = normalize_path_component(album_artist)
    normalized_album = normalize_path_component(album_title)
    year = normalize_release_year(first_track.tags.get("date"))

    target_album_dir_name = f"{year} - {normalized_album}" if year else normalized_album
    target_album_dir = source_root / normalized_artist / target_album_dir_name
    current_album_dir = Path(album.path)

    if target_album_dir == current_album_dir:
        return None, None

    try:
        target_album_dir.relative_to(current_album_dir)
        return None, WarningItem(
            code="album_folder_inside_self",
            message=(
                f"Cannot rename '{current_album_dir.relative_to(source_root)}' to "
                f"'{target_album_dir.relative_to(source_root)}' — target is inside the source folder. "
                "Tracks may be flat in the artist folder instead of in an album subfolder."
            ),
            path=str(current_album_dir),
        )
    except ValueError:
        pass

    confidence = "safe"
    reason = "Folder path can be derived directly from albumartist, album, and year."
    warning = None
    if year is None:
        confidence = "review"
        reason = "Year is missing, so the yearless folder fallback requires review."
        warning = WarningItem(
            code="album_missing_year",
            message="Album is missing a usable year; planner proposed a yearless folder fallback for review.",
            path=str(current_album_dir),
        )

    return (
        ProposedChange(
            item_id=f"{current_album_dir.relative_to(source_root)}#folder",
            change_type="folder_rename",
            current_value=str(current_album_dir.relative_to(source_root)),
            proposed_value=str(target_album_dir.relative_to(source_root)),
            confidence=confidence,
            reason=reason,
            path=str(current_album_dir),
        ),
        warning,
    )


def normalize_release_year(value: str | None) -> str | None:
    if not value:
        return None
    head = value.strip()[:4]
    if len(head) == 4 and head.isdigit():
        return head
    return None


def normalize_path_component(value: str) -> str:
    return normalize_filename_component(value)


def deduplicate_artist_case(
    changes: list[ProposedChange],
    tracks: list[TrackReport],
    source_root: Path,
) -> tuple[list[ProposedChange], list[WarningItem]]:
    folder_renames = [c for c in changes if c.change_type == "folder_rename"]

    def proposed_artist(change: ProposedChange) -> str:
        parts = Path(change.proposed_value).parts
        return parts[0] if parts else ""

    def artist_key(name: str) -> str:
        return name.lower().replace(" & ", " and ")

    artist_counts: Counter[str] = Counter(
        proposed_artist(c) for c in folder_renames if proposed_artist(c)
    )

    # Include existing depth-1 directories so albums already in the correct place
    # are visible to collision detection even when they have no pending folder rename.
    existing_artist_names: set[str] = set()
    for d in source_root.iterdir():
        if d.is_dir():
            existing_artist_names.add(d.name)
            if d.name not in artist_counts:
                artist_counts[d.name] = 0

    groups: dict[str, list[str]] = {}
    for artist in artist_counts:
        groups.setdefault(artist_key(artist), []).append(artist)

    collisions = {k: v for k, v in groups.items() if len(v) > 1}
    if not collisions:
        return changes, []

    # canonical: existing dirs on disk first, then most albums, then alphabetical
    canonical_map: dict[str, str] = {}
    for variants in collisions.values():
        canonical = sorted(variants, key=lambda v: (
            0 if v in existing_artist_names else 1,
            -artist_counts[v],
            v,
        ))[0]
        for v in variants:
            if v != canonical:
                canonical_map[v] = canonical

    # An established canonical is one that already exists on disk with album subdirs —
    # unambiguous enough that renames targeting it don't need manual review.
    established_canonicals: set[str] = set()
    for canonical in set(canonical_map.values()):
        canonical_dir = source_root / canonical
        if canonical_dir.is_dir() and any(child.is_dir() for child in canonical_dir.iterdir()):
            established_canonicals.add(canonical)

    # Step 1: update pending folder_renames that point to non-canonical artist dirs
    updated: list[ProposedChange] = []
    for change in changes:
        if change.change_type == "folder_rename":
            old_artist = proposed_artist(change)
            if old_artist in canonical_map:
                canonical = canonical_map[old_artist]
                new_proposed = canonical + change.proposed_value[len(old_artist):]
                if canonical in established_canonicals:
                    confidence = change.confidence
                    reason = f"Artist folder normalized from '{old_artist}' to established canonical '{canonical}'."
                else:
                    confidence = "review"
                    reason = f"Artist folder normalized from '{old_artist}' to '{canonical}' to resolve case-insensitive name conflict."
                updated.append(ProposedChange(
                    item_id=change.item_id,
                    change_type="folder_rename",
                    current_value=change.current_value,
                    proposed_value=new_proposed,
                    confidence=confidence,
                    reason=reason,
                    path=change.path,
                ))
                continue
        updated.append(change)

    # Step 2: for non-canonical artist dirs that already exist on disk, generate
    # folder_renames to move their album subdirs into the canonical artist dir.
    existing_rename_current_values = {c.current_value for c in updated if c.change_type == "folder_rename"}
    merge_renames: list[ProposedChange] = []
    for non_canonical, canonical in canonical_map.items():
        if non_canonical not in existing_artist_names:
            continue
        non_canonical_dir = source_root / non_canonical
        if not non_canonical_dir.is_dir():
            continue
        for album_dir in sorted(non_canonical_dir.iterdir()):
            if not album_dir.is_dir():
                continue
            current_rel = str(Path(non_canonical) / album_dir.name)
            proposed_rel = str(Path(canonical) / album_dir.name)
            if current_rel in existing_rename_current_values:
                continue
            if (source_root / proposed_rel).exists():
                continue
            merge_renames.append(ProposedChange(
                item_id=f"{current_rel}#folder",
                change_type="folder_rename",
                current_value=current_rel,
                proposed_value=proposed_rel,
                confidence="review",
                reason=f"Album moved from '{non_canonical}/' to canonical artist folder '{canonical}/' to resolve case-insensitive name conflict.",
                path=str(album_dir),
            ))

    # Step 3: tag edits for non-canonical albumartist tags
    existing_tag_ids = {c.item_id for c in updated if c.change_type == "tag_edit"}
    tag_fixes: list[ProposedChange] = []
    for track in tracks:
        album_artist = track.tags.get("albumartist", "")
        if album_artist in canonical_map:
            canonical = canonical_map[album_artist]
            item_id = f"{track.track_id}#tag:albumartist"
            if item_id not in existing_tag_ids:
                tag_fixes.append(ProposedChange(
                    item_id=item_id,
                    change_type="tag_edit",
                    current_value=album_artist,
                    proposed_value=canonical,
                    confidence="safe" if canonical in established_canonicals else "review",
                    reason=(
                        f"albumartist normalized from '{album_artist}' to established canonical '{canonical}'."
                        if canonical in established_canonicals else
                        f"albumartist normalized from '{album_artist}' to '{canonical}' to resolve case-insensitive name conflict."
                    ),
                    path=track.path,
                ))

    warnings: list[WarningItem] = [
        WarningItem(
            code="artist_name_case_conflict",
            message=f"Case-insensitive artist name conflict: {sorted(variants)!r} — canonical form set to '{sorted(variants, key=lambda v: (-artist_counts[v], v))[0]}'.",
        )
        for variants in collisions.values()
    ]

    return updated + merge_renames + tag_fixes, warnings
