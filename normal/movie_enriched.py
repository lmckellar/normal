from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Callable

from normal.models import WarningItem, utc_now_iso
from normal.movie_identity import ParsedMovieIdentity
from normal.movie_junk import (
    MovieJunkItem,
    MovieJunkReason,
    MovieJunkReport,
    confidence_rank,
    detect_movie_junk_reasons,
    format_file_size,
    format_runtime,
    highest_confidence,
    movie_junk_facts,
    safe_file_size,
    scan_movie_promo_documents,
)
from normal.movie_plan import parse_movie_name_with_sidecar_fallback
from normal.movie_scan import (
    MovieReviewItem,
    MovieScanReport,
    MovieScanProgress,
    STATUS_PRIORITY,
    emit_progress,
    iter_video_files,
    movie_id_for,
    probe_media_facts,
    score_replacement_priority,
)
from normal.quality_review import MediaFacts, QualityReview, score_quality_review


@dataclass(slots=True)
class IdentitySlot:
    lane: str
    value: object


@dataclass(slots=True)
class EnrichedFacts:
    movie_id: str
    path: str
    facts: MediaFacts
    review: QualityReview
    junk_reasons: list[MovieJunkReason]
    identity: IdentitySlot | None = None
    imdb_id: str | None = None
    replacement_priority_score: float | None = None
    replacement_priority_label: str | None = None
    replacement_year_hint: int | None = None
    probe_error: str | None = None


@dataclass(slots=True)
class EnrichedLibraryReport:
    source_root: str
    generated_at: str
    files: list[EnrichedFacts] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)


def scan_enriched_library(
    source_root: Path,
    *,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: Callable[[MovieScanProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    lane: str = "movie",
    parse_identity: Callable[[Path], ParsedMovieIdentity] = parse_movie_name_with_sidecar_fallback,
) -> EnrichedLibraryReport:
    if lane != "movie":
        raise ValueError(f"Unsupported identity lane: {lane}")

    report = EnrichedLibraryReport(
        source_root=str(source_root.resolve()),
        generated_at=utc_now_iso(),
    )
    movie_files = list(iter_video_files(source_root, should_cancel=should_cancel))
    if not movie_files:
        report.warnings.append(
            WarningItem(
                code="no_video_files",
                message="No supported video files were found under the source directory.",
                path=str(source_root),
            )
        )
        return report

    started_at = time.monotonic()
    total_files = len(movie_files)
    emit_progress(progress_callback, 0, total_files, None, started_at, "starting")

    for index, movie_path in enumerate(movie_files, start=1):
        if should_cancel is not None and should_cancel():
            report.warnings.append(
                WarningItem(
                    code="movie_enriched_cancelled",
                    message="Movie enriched scan was cancelled before completion.",
                    path=str(source_root),
                )
            )
            break

        probe_error = None
        try:
            facts = probe_media(movie_path)
            junk_reasons = detect_movie_junk_reasons(movie_path, facts)
        except Exception as exc:
            probe_error = str(exc)
            facts = MediaFacts()
            junk_reasons = detect_movie_junk_reasons(movie_path)
            report.warnings.append(
                WarningItem(
                    code="movie_probe_error",
                    message=f"Unable to probe media metadata: {exc}",
                    path=str(movie_path),
                )
            )

        replacement_score, replacement_label, replacement_year = score_replacement_priority(movie_path)
        report.files.append(
            EnrichedFacts(
                movie_id=movie_id_for(movie_path, source_root),
                path=str(movie_path),
                facts=facts,
                review=score_quality_review(facts, path=movie_path.name),
                junk_reasons=junk_reasons,
                identity=IdentitySlot(lane=lane, value=parse_identity(movie_path)),
                replacement_priority_score=replacement_score,
                replacement_priority_label=replacement_label,
                replacement_year_hint=replacement_year,
                probe_error=probe_error,
            )
        )
        emit_progress(
            progress_callback,
            index,
            total_files,
            movie_path,
            started_at,
            "warning" if probe_error else "running",
        )

    status = "complete" if len(report.files) == total_files else "cancelled"
    emit_progress(progress_callback, len(report.files), total_files, None, started_at, status)
    return report


def parsed_movies_from_enriched(report: EnrichedLibraryReport) -> dict[Path, ParsedMovieIdentity]:
    parsed: dict[Path, ParsedMovieIdentity] = {}
    for item in report.files:
        if item.identity is None or item.identity.lane != "movie":
            continue
        if isinstance(item.identity.value, ParsedMovieIdentity):
            parsed[Path(item.path)] = item.identity.value
    return parsed


def build_movie_scan_from_enriched(report: EnrichedLibraryReport) -> MovieScanReport:
    projected = MovieScanReport(
        source_root=report.source_root,
        generated_at=report.generated_at,
    )
    for item in report.files:
        if item.probe_error:
            projected.warnings.append(
                WarningItem(
                    code="movie_probe_error",
                    message=f"Unable to probe media metadata: {item.probe_error}",
                    path=item.path,
                )
            )
            continue
        priority_score = item.replacement_priority_score or 1.0
        review_item = MovieReviewItem(
            movie_id=item.movie_id,
            path=item.path,
            review=item.review,
            replacement_priority_score=priority_score,
            replacement_priority_label=item.replacement_priority_label or "medium",
            replacement_year_hint=item.replacement_year_hint,
            triage_score=round(item.review.score * priority_score, 1),
        )
        projected.movies.append(review_item)
    if not report.files:
        projected.warnings.extend(warning for warning in report.warnings if warning.code == "no_video_files")
    projected.movies.sort(
        key=lambda item: (
            -item.triage_score,
            STATUS_PRIORITY.get(item.review.status, 99),
            -item.review.score,
            item.path.lower(),
        )
    )
    return projected


def build_movie_cleanup_from_enriched(
    source_root: Path,
    report: EnrichedLibraryReport,
) -> MovieJunkReport:
    video_junk: list[MovieJunkItem] = []
    for item in report.files:
        if not item.junk_reasons:
            continue
        path = Path(item.path)
        facts = None if item.probe_error else item.facts
        file_size_bytes = safe_file_size(path)
        runtime_seconds = facts.runtime_seconds if facts is not None else None
        video_junk.append(
            MovieJunkItem(
                movie_id=item.movie_id,
                path=item.path,
                relative_path=item.movie_id,
                file_name=path.name,
                file_size_bytes=file_size_bytes,
                file_size_label=format_file_size(file_size_bytes),
                runtime_seconds=runtime_seconds,
                runtime_label=format_runtime(runtime_seconds),
                confidence=highest_confidence(item.junk_reasons),
                facts=movie_junk_facts(facts),
                reasons=item.junk_reasons,
            )
        )

    document_report = scan_movie_promo_documents(source_root)
    merged = MovieJunkReport(
        source_root=str(source_root.resolve()),
        generated_at=utc_now_iso(),
        junk=video_junk + document_report.junk,
        warnings=[warning for warning in report.warnings if warning.code != "movie_probe_error"]
        + document_report.warnings,
    )
    merged.junk.sort(key=lambda junk_item: (confidence_rank(junk_item.confidence), junk_item.path.lower()))
    return merged
