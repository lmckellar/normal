from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

from normal.models import WarningItem, utc_now_iso
from normal.movie_plan import parse_movie_name
from normal.movie_profile import MovieProfileItem, scan_movie_profiles
from normal.movie_scan import MovieScanProgress
from normal.quality_review import MediaFacts


MATCH_TITLE_PATTERN = re.compile(r"[^a-z0-9]+")
MINIMUM_ACCEPTABLE_LABELS = {
    "minimum_acceptable_1080p",
    "compressed_1080p",
    "1080p_uhd",
    "compressed_4k",
    "4k_uhd",
    "4k_remux",
}
WEAK_MATCH_LABELS = {"sd_low_quality", "weak_1080p", "weak_4k", "unclassified"}
PROFILE_STRENGTH = {
    "unclassified": 0,
    "sd_low_quality": 1,
    "weak_1080p": 2,
    "weak_4k": 2,
    "minimum_acceptable_1080p": 3,
    "compressed_1080p": 4,
    "1080p_uhd": 5,
    "compressed_4k": 6,
    "4k_uhd": 7,
    "4k_remux": 8,
}
SUPPORTED_DATASET_KINDS = {"service", "prestige", "recent"}


@dataclass(slots=True)
class ComparisonDatasetMetadata:
    dataset_id: str
    dataset_name: str
    dataset_kind: str
    snapshot_date: str | None
    freshness_label: str
    entry_count: int
    path: str


@dataclass(slots=True)
class ComparisonDatasetEntry:
    title: str
    year: int
    dataset_id: str
    dataset_name: str
    release_date: str | None = None


@dataclass(slots=True)
class LocalNormalizedMovie:
    normalized_title: str
    display_title: str
    year: int
    paths: list[str]
    copy_count: int
    strongest_profile_label: str
    strongest_profile_rank: int


@dataclass(slots=True)
class ComparisonMatchItem:
    title: str
    year: int
    local_paths: list[str]
    copy_count: int
    strongest_profile_label: str
    minimum_acceptable_or_better: bool
    weak_match: bool
    release_date: str | None = None


@dataclass(slots=True)
class ComparisonDatasetReport:
    metadata: ComparisonDatasetMetadata
    overlap_count: int
    overlap_pct: float
    total_dataset_titles: int
    matched_titles: list[ComparisonMatchItem] = field(default_factory=list)


@dataclass(slots=True)
class MovieComparisonAggregates:
    total_normalized_movies: int
    skipped_non_normalized_movies: int
    recent_releases_18m_count: int
    recent_releases_18m_pct: float
    imdb_top_250_coverage_pct: float | None
    imdb_top_1000_coverage_pct: float | None
    minimum_acceptable_or_better_pct_within_service_matches: float | None
    weak_matches_count: int
    service_union_overlap_count: int
    service_union_overlap_pct: float


@dataclass(slots=True)
class MovieComparisonReport:
    source_root: str
    dataset_root: str
    generated_at: str
    available_datasets: list[ComparisonDatasetMetadata] = field(default_factory=list)
    selected_dataset_ids: list[str] = field(default_factory=list)
    aggregates: MovieComparisonAggregates | None = None
    service_datasets: list[ComparisonDatasetReport] = field(default_factory=list)
    prestige_datasets: list[ComparisonDatasetReport] = field(default_factory=list)
    recent_datasets: list[ComparisonDatasetReport] = field(default_factory=list)
    unmatched_local_titles: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_comparison_dataset_root() -> Path:
    override = os.environ.get("NORMAL_MOVIE_COMPARISON_DATASET_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "datasets" / "movie_comparison"


def build_movie_comparison_report(
    source_root: Path,
    *,
    dataset_root: Path | None = None,
    selected_dataset_ids: list[str] | None = None,
    probe_media: Callable[[Path], MediaFacts],
    progress_callback: Callable[[MovieScanProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    now: datetime | None = None,
) -> MovieComparisonReport:
    resolved_dataset_root = (dataset_root or default_comparison_dataset_root()).resolve()
    report = MovieComparisonReport(
        source_root=str(source_root.resolve()),
        dataset_root=str(resolved_dataset_root),
        generated_at=utc_now_iso(),
    )

    movie_profiles = scan_movie_profiles(
        source_root,
        probe_media=probe_media,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )
    report.warnings.extend(movie_profiles.warnings)

    local_movies, skipped_non_normalized = normalize_local_movies(movie_profiles.movies, report.warnings)
    available_datasets, loaded_datasets = load_comparison_datasets(resolved_dataset_root, report.warnings)
    report.available_datasets = available_datasets

    available_ids = {item.dataset_id for item in available_datasets}
    if selected_dataset_ids is None:
        selected = [item.dataset_id for item in available_datasets]
    else:
        selected = [dataset_id for dataset_id in selected_dataset_ids if dataset_id in available_ids]
    report.selected_dataset_ids = selected

    if not available_datasets:
        report.warnings.append(
            WarningItem(
                code="no_comparison_datasets",
                message="No comparison datasets were found. Install JSON dataset snapshots to enable the dashboard.",
                path=str(resolved_dataset_root),
            )
        )

    selected_datasets = [dataset for dataset in loaded_datasets if dataset["metadata"].dataset_id in set(selected)]
    report.service_datasets = build_dataset_reports(local_movies, selected_datasets, "service")
    report.prestige_datasets = build_dataset_reports(local_movies, selected_datasets, "prestige")
    report.recent_datasets = build_dataset_reports(local_movies, selected_datasets, "recent")
    report.unmatched_local_titles = build_unmatched_local_titles(local_movies, selected_datasets)
    report.aggregates = build_aggregates(
        local_movies,
        report.service_datasets,
        report.prestige_datasets,
        report.recent_datasets,
        skipped_non_normalized=skipped_non_normalized,
        now=now,
    )
    return report


def normalize_local_movies(
    movies: list[MovieProfileItem],
    warnings: list[WarningItem],
) -> tuple[dict[tuple[str, int], LocalNormalizedMovie], int]:
    normalized: dict[tuple[str, int], LocalNormalizedMovie] = {}
    skipped = 0
    for item in movies:
        movie_path = Path(item.path)
        parsed = parse_movie_name(movie_path)
        if parsed.title is None or parsed.year is None or parsed.confidence != "safe":
            skipped += 1
            warnings.append(
                WarningItem(
                    code="comparison_skipped_non_normalized_movie",
                    message="Movie was skipped because title/year normalization was not confident enough for strict comparison matching.",
                    path=item.path,
                )
            )
            continue
        key = (normalize_match_title(parsed.title), parsed.year)
        existing = normalized.get(key)
        strength = PROFILE_STRENGTH.get(item.profile.label, 0)
        if existing is None:
            normalized[key] = LocalNormalizedMovie(
                normalized_title=key[0],
                display_title=parsed.title,
                year=parsed.year,
                paths=[item.path],
                copy_count=1,
                strongest_profile_label=item.profile.label,
                strongest_profile_rank=strength,
            )
            continue
        existing.paths.append(item.path)
        existing.copy_count += 1
        if strength > existing.strongest_profile_rank:
            existing.strongest_profile_rank = strength
            existing.strongest_profile_label = item.profile.label
    for item in normalized.values():
        item.paths.sort()
    return normalized, skipped


def load_comparison_datasets(
    dataset_root: Path,
    warnings: list[WarningItem],
) -> tuple[list[ComparisonDatasetMetadata], list[dict[str, Any]]]:
    if not dataset_root.exists():
        return [], []
    if not dataset_root.is_dir():
        warnings.append(
            WarningItem(
                code="comparison_dataset_root_invalid",
                message="Comparison dataset root exists but is not a directory.",
                path=str(dataset_root),
            )
        )
        return [], []

    available: list[ComparisonDatasetMetadata] = []
    loaded: list[dict[str, Any]] = []
    for dataset_path in sorted(dataset_root.rglob("*.json")):
        parsed = load_comparison_dataset_file(dataset_path, warnings)
        if parsed is None:
            continue
        metadata, entries = parsed
        available.append(metadata)
        loaded.append({"metadata": metadata, "entries": entries})
    return available, loaded


def load_comparison_dataset_file(
    dataset_path: Path,
    warnings: list[WarningItem],
) -> tuple[ComparisonDatasetMetadata, list[ComparisonDatasetEntry]] | None:
    try:
        payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(
            WarningItem(
                code="comparison_dataset_read_error",
                message=f"Dataset could not be read: {exc}",
                path=str(dataset_path),
            )
        )
        return None
    if not isinstance(payload, dict):
        warnings.append(
            WarningItem(
                code="comparison_dataset_invalid_payload",
                message="Dataset JSON must be an object with metadata and entries.",
                path=str(dataset_path),
            )
        )
        return None
    dataset_id = payload.get("dataset_id")
    dataset_name = payload.get("dataset_name")
    dataset_kind = payload.get("dataset_kind")
    entries_payload = payload.get("entries")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        warnings.append(
            WarningItem(
                code="comparison_dataset_missing_metadata",
                message="Dataset is missing a valid dataset_id.",
                path=str(dataset_path),
            )
        )
        return None
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        warnings.append(
            WarningItem(
                code="comparison_dataset_missing_metadata",
                message=f"Dataset '{dataset_id}' is missing a valid dataset_name.",
                path=str(dataset_path),
            )
        )
        return None
    if dataset_kind not in SUPPORTED_DATASET_KINDS:
        warnings.append(
            WarningItem(
                code="comparison_dataset_missing_metadata",
                message=f"Dataset '{dataset_id}' is missing a supported dataset_kind.",
                path=str(dataset_path),
            )
        )
        return None
    if not isinstance(entries_payload, list):
        warnings.append(
            WarningItem(
                code="comparison_dataset_invalid_entries",
                message=f"Dataset '{dataset_id}' is missing an entries list.",
                path=str(dataset_path),
            )
        )
        return None

    snapshot_date = payload.get("snapshot_date") if isinstance(payload.get("snapshot_date"), str) else None
    freshness_label = payload.get("freshness_label") if isinstance(payload.get("freshness_label"), str) and payload.get("freshness_label") else "freshness unknown"
    if snapshot_date is None:
        warnings.append(
            WarningItem(
                code="comparison_dataset_missing_snapshot_date",
                message=f"Dataset '{dataset_id}' is missing snapshot_date metadata.",
                path=str(dataset_path),
            )
        )

    entries: list[ComparisonDatasetEntry] = []
    seen_keys: set[tuple[str, int]] = set()
    for raw_entry in entries_payload:
        entry = normalize_dataset_entry(raw_entry, dataset_id, dataset_name)
        if entry is None:
            warnings.append(
                WarningItem(
                    code="comparison_dataset_invalid_entry",
                    message=f"Dataset '{dataset_id}' contains an invalid title/year entry that was skipped.",
                    path=str(dataset_path),
                )
            )
            continue
        key = (normalize_match_title(entry.title), entry.year)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        entries.append(entry)

    return (
        ComparisonDatasetMetadata(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            dataset_kind=dataset_kind,
            snapshot_date=snapshot_date,
            freshness_label=freshness_label,
            entry_count=len(entries),
            path=str(dataset_path),
        ),
        entries,
    )


def normalize_dataset_entry(
    raw_entry: Any,
    dataset_id: str,
    dataset_name: str,
) -> ComparisonDatasetEntry | None:
    if not isinstance(raw_entry, dict):
        return None
    title = raw_entry.get("title")
    year = raw_entry.get("year")
    if not isinstance(title, str) or not title.strip():
        return None
    try:
        parsed_year = int(year)
    except (TypeError, ValueError):
        return None
    release_date = raw_entry.get("release_date") if isinstance(raw_entry.get("release_date"), str) else None
    return ComparisonDatasetEntry(
        title=title.strip(),
        year=parsed_year,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        release_date=release_date,
    )


def build_dataset_reports(
    local_movies: dict[tuple[str, int], LocalNormalizedMovie],
    datasets: list[dict[str, Any]],
    dataset_kind: str,
) -> list[ComparisonDatasetReport]:
    reports: list[ComparisonDatasetReport] = []
    total_local = len(local_movies)
    for dataset in datasets:
        metadata: ComparisonDatasetMetadata = dataset["metadata"]
        if metadata.dataset_kind != dataset_kind:
            continue
        matched = []
        for entry in dataset["entries"]:
            key = (normalize_match_title(entry.title), entry.year)
            local = local_movies.get(key)
            if local is None:
                continue
            matched.append(
                ComparisonMatchItem(
                    title=local.display_title,
                    year=local.year,
                    local_paths=local.paths,
                    copy_count=local.copy_count,
                    strongest_profile_label=local.strongest_profile_label,
                    minimum_acceptable_or_better=local.strongest_profile_label in MINIMUM_ACCEPTABLE_LABELS,
                    weak_match=local.strongest_profile_label in WEAK_MATCH_LABELS,
                    release_date=entry.release_date,
                )
            )
        matched.sort(key=lambda item: (item.year, item.title.casefold()))
        pct_total = metadata.entry_count if dataset_kind == "prestige" else total_local
        reports.append(
            ComparisonDatasetReport(
                metadata=metadata,
                overlap_count=len(matched),
                overlap_pct=percent(len(matched), pct_total),
                total_dataset_titles=metadata.entry_count,
                matched_titles=matched,
            )
        )
    return reports


def build_unmatched_local_titles(
    local_movies: dict[tuple[str, int], LocalNormalizedMovie],
    datasets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dataset_keys = {
        (normalize_match_title(entry.title), entry.year)
        for dataset in datasets
        for entry in dataset["entries"]
    }
    unmatched = []
    for key, local in sorted(local_movies.items(), key=lambda item: (item[1].year, item[1].display_title.casefold())):
        if key in dataset_keys:
            continue
        unmatched.append(
            {
                "title": local.display_title,
                "year": local.year,
                "paths": local.paths,
                "copy_count": local.copy_count,
                "strongest_profile_label": local.strongest_profile_label,
            }
        )
    return unmatched


def build_aggregates(
    local_movies: dict[tuple[str, int], LocalNormalizedMovie],
    service_datasets: list[ComparisonDatasetReport],
    prestige_datasets: list[ComparisonDatasetReport],
    recent_datasets: list[ComparisonDatasetReport],
    *,
    skipped_non_normalized: int,
    now: datetime | None,
) -> MovieComparisonAggregates:
    total_normalized = len(local_movies)
    service_union_keys = matched_identity_keys(service_datasets)
    benchmark_union_keys = matched_identity_keys(service_datasets + prestige_datasets)
    weak_matches_count = sum(
        1
        for key in benchmark_union_keys
        if local_movies[key].strongest_profile_label in WEAK_MATCH_LABELS
    )
    acceptable_matches = sum(
        1
        for key in benchmark_union_keys
        if local_movies[key].strongest_profile_label in MINIMUM_ACCEPTABLE_LABELS
    )
    recent_cutoff = subtract_months((now or datetime.now(UTC)).date(), 18)
    recent_keys = recent_release_identity_keys(recent_datasets, recent_cutoff)
    return MovieComparisonAggregates(
        total_normalized_movies=total_normalized,
        skipped_non_normalized_movies=skipped_non_normalized,
        recent_releases_18m_count=len(recent_keys),
        recent_releases_18m_pct=percent(len(recent_keys), total_normalized),
        imdb_top_250_coverage_pct=coverage_for_dataset(prestige_datasets, "imdb_top_250"),
        imdb_top_1000_coverage_pct=coverage_for_dataset(prestige_datasets, "imdb_top_1000"),
        minimum_acceptable_or_better_pct_within_service_matches=(
            percent(acceptable_matches, len(benchmark_union_keys)) if benchmark_union_keys else None
        ),
        weak_matches_count=weak_matches_count,
        service_union_overlap_count=len(service_union_keys),
        service_union_overlap_pct=percent(len(service_union_keys), total_normalized),
    )


def matched_identity_keys(reports: list[ComparisonDatasetReport]) -> set[tuple[str, int]]:
    return {
        (normalize_match_title(item.title), item.year)
        for report in reports
        for item in report.matched_titles
    }


def recent_release_identity_keys(
    recent_datasets: list[ComparisonDatasetReport],
    cutoff: date,
) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    for report in recent_datasets:
        for item in report.matched_titles:
            parsed_date = parse_iso_date(item.release_date)
            if parsed_date is not None and parsed_date >= cutoff:
                keys.add((normalize_match_title(item.title), item.year))
    return keys


def coverage_for_dataset(reports: list[ComparisonDatasetReport], dataset_id: str) -> float | None:
    report = next((item for item in reports if item.metadata.dataset_id == dataset_id), None)
    if report is None:
        return None
    return report.overlap_pct


def normalize_match_title(value: str) -> str:
    collapsed = MATCH_TITLE_PATTERN.sub(" ", value.casefold()).strip()
    return " ".join(collapsed.split())


def percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100, 1)


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def subtract_months(current: date, months: int) -> date:
    year = current.year
    month = current.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(current.day, days_in_month(year, month))
    return date(year, month, day)


def days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    if month in {4, 6, 9, 11}:
        return 30
    return 31
