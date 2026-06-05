from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable

from normal.audit import AuditEvent, AuditStore
from normal.movie_canonical_lists import CANONICAL_LISTS, CanonicalListEntry, build_canonical_provider
from normal.movie_identity import MovieIdentityKey, canonical_identity_key, parse_movie_identity
from normal.movie_naming import title_alias_keys
from normal.movie_profile import (
    MovieProfileReport,
    QUALITY_STANCE_RANKS,
    normalize_quality_stance_label,
    replacement_candidate_quality_floor,
)


def build_library_improvement_payload(
    source_root: Path,
    report: MovieProfileReport,
    standards: dict[str, Any] | None,
    *,
    audit_store: AuditStore,
    tmdb_key: str | None,
    http_get: Callable[[str], dict[str, Any]] | None = None,
    now: Callable[[], float] = time.time,
    pending_scan_count: int = 0,
) -> dict[str, Any]:
    events = audit_store.read_events(source_root)
    file_removals = summarize_file_removals(events)
    audio_removals = summarize_audio_track_removals(events)
    scan_count = sum(1 for event in events if event.action == "scan") + max(pending_scan_count, 0)
    current_top_500 = canonical_top_500_above_floor_count(report, standards, tmdb_key=tmdb_key, http_get=http_get, now=now)
    baseline = current_top_500["count"]
    latest = current_top_500["count"]
    history = [
        int(event.metadata["canonical_top_500_above_floor_count"])
        for event in events
        if event.workflow == "profile"
        and event.action == "scan"
        and isinstance(event.metadata.get("canonical_top_500_above_floor_count"), int)
    ]
    if history:
        baseline = history[0]
        latest = current_top_500["count"] if current_top_500["count"] is not None else history[-1]
    score_percent = canonical_improvement_percent(baseline, latest)
    return {
        "files_removed": file_removals,
        "audio_tracks_removed": audio_removals,
        "canonical_top_500_above_floor": current_top_500,
        "canonical_improvement": {
            "percent": score_percent,
            "baseline_count": baseline,
            "latest_count": latest,
            "denominator": 500,
            "available": score_percent is not None and baseline is not None and latest is not None,
        },
        "total_scans_performed": scan_count,
    }


def summarize_file_removals(events: list[AuditEvent]) -> dict[str, int]:
    count = 0
    total_bytes = 0
    for event in events:
        value = event.metadata.get("deleted_media")
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            count += 1
            total_bytes += max(int(item.get("size_bytes") or 0), 0)
    return {"count": count, "total_bytes": total_bytes}


def summarize_audio_track_removals(events: list[AuditEvent]) -> dict[str, int]:
    count = 0
    total_bytes = 0
    for event in events:
        value = event.metadata.get("audio_tracks_removed")
        if not isinstance(value, dict):
            continue
        count += max(int(value.get("count") or 0), 0)
        total_bytes += max(int(value.get("total_bytes") or 0), 0)
    return {"count": count, "total_bytes": total_bytes}


def canonical_improvement_percent(baseline: int | None, latest: int | None) -> int | None:
    if baseline is None or latest is None:
        return None
    if baseline <= 0:
        return 100 if latest <= 0 else None
    return int(round((latest / baseline) * 100))


def canonical_top_500_above_floor_count(
    report: MovieProfileReport,
    standards: dict[str, Any] | None,
    *,
    tmdb_key: str | None,
    http_get: Callable[[str], dict[str, Any]] | None = None,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    denominator = 500
    active_standards = standards or {}
    try:
        provider = build_canonical_provider(standards=active_standards, tmdb_key=tmdb_key, http_get=http_get, now=now)
    except ValueError:
        if not tmdb_key:
            return {"count": None, "denominator": denominator, "available": False}
        provider = build_canonical_provider(
            standards={"canonical_list_provider": "tmdb"},
            tmdb_key=tmdb_key,
            http_get=http_get,
            now=now,
        )
    config = next(item for item in CANONICAL_LISTS if item.id == "top_500")
    try:
        entries, cache_state = provider.list_entries(config)
    except ValueError:
        if not tmdb_key:
            return {"count": None, "denominator": denominator, "available": False}
        provider = build_canonical_provider(
            standards={"canonical_list_provider": "tmdb"},
            tmdb_key=tmdb_key,
            http_get=http_get,
            now=now,
        )
        entries, cache_state = provider.list_entries(config)
    inventory = build_profile_inventory(report, active_standards)
    alias_index = build_alias_index(inventory)
    count = 0
    for entry in entries:
        if profile_inventory_match(entry, inventory, alias_index):
            count += 1
    return {"count": count, "denominator": denominator, "available": True, "cache_state": cache_state}


def build_profile_inventory(
    report: MovieProfileReport,
    standards: dict[str, Any] | None,
) -> dict[MovieIdentityKey, int]:
    active_standards = standards or {}
    floor = normalize_quality_stance_label(replacement_candidate_quality_floor(active_standards), "standard_definition")
    floor_rank = QUALITY_STANCE_RANKS.get(floor, 0)
    inventory: dict[MovieIdentityKey, int] = {}
    for item in report.movies:
        parsed = parse_movie_identity(Path(item.path))
        if parsed.title is None or parsed.year is None:
            continue
        quality_label = getattr(item.profile, "quality_label", None)
        quality_rank = QUALITY_STANCE_RANKS.get(str(quality_label or ""), 0)
        if quality_rank <= floor_rank:
            continue
        key = canonical_identity_key(parsed.title, parsed.year)
        inventory[key] = max(inventory.get(key, 0), quality_rank)
    return inventory


def build_alias_index(inventory: dict[MovieIdentityKey, int]) -> dict[tuple[str, int], MovieIdentityKey | None]:
    index: dict[tuple[str, int], MovieIdentityKey | None] = {}
    for inv_key in inventory:
        for alias in title_alias_keys(inv_key.title):
            tag = (alias, inv_key.year)
            index[tag] = None if tag in index else inv_key
    return index


def profile_inventory_match(
    entry: CanonicalListEntry,
    inventory: dict[MovieIdentityKey, int],
    alias_index: dict[tuple[str, int], MovieIdentityKey | None],
) -> MovieIdentityKey | None:
    primary = entry.to_key()
    if primary in inventory:
        return primary
    for alias in title_alias_keys(entry.title):
        inv_key = alias_index.get((alias, entry.year))
        if inv_key is not None:
            return inv_key
    return None
