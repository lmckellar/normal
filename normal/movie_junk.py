from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any, Callable

from normal.models import WarningItem, utc_now_iso
from normal.movie_scan import discover_video_files, movie_id_for, probe_media_facts
from normal.quality_review import MediaFacts


SHORT_VIDEO_SECONDS = 5 * 60
SMALL_VIDEO_BYTES = 100 * 1024 * 1024
GENERAL_PROBE_SIZE_CEILING = 500 * 1024 * 1024
JUNK_MARKER_PROBE_SIZE_CEILING = 3 * 1024 * 1024 * 1024
SAFE_JUNK_MARKER_SIZE_BYTES = 2 * 1024 * 1024 * 1024
JUNK_DOCUMENT_EXTENSIONS = {".txt", ".html", ".htm"}
STRONG_JUNK_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])("
    r"sample|"
    r"samples|"
    r"featurette|featurettes|"
    r"featurrette|featurrettes"
    r")(?![A-Za-z0-9])",
    re.IGNORECASE,
)
WEAK_JUNK_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])(extra|extras)(?![A-Za-z0-9])", re.IGNORECASE)
PROMO_DOCUMENT_NAME_PATTERN = re.compile(
    r"(?i)("
    r"rarbg|yts|yify|ettv|eztv|tgx|torrentgalaxy|"
    r"1337x|kickass|kat\.cr|limetorrents|torrent|"
    r"www\.|\.com|\.net|\.org"
    r")"
)
PROMO_DOCUMENT_CONTENT_PATTERN = re.compile(
    r"(?i)("
    r"download(?:ed)? from|"
    r"torrent|"
    r"visit (?:us )?(?:at )?|"
    r"www\.|https?://|"
    r"rarbg|yts|yify|ettv|eztv|tgx|torrentgalaxy"
    r")"
)
PROMO_DOCUMENT_READ_LIMIT = 16 * 1024


@dataclass(slots=True)
class MovieJunkReason:
    code: str
    message: str
    confidence: str
    matched_value: str | None = None


@dataclass(slots=True)
class MovieJunkItem:
    movie_id: str
    path: str
    relative_path: str
    file_name: str
    file_size_bytes: int | None
    file_size_label: str | None
    runtime_seconds: int | None
    runtime_label: str | None
    confidence: str
    reasons: list[MovieJunkReason] = field(default_factory=list)


@dataclass(slots=True)
class MovieJunkReport:
    source_root: str
    generated_at: str
    junk: list[MovieJunkItem] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scan_movie_junk(
    source_root: Path,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
) -> MovieJunkReport:
    report = MovieJunkReport(source_root=str(source_root.resolve()), generated_at=utc_now_iso())
    movie_files = discover_video_files(source_root)

    if not movie_files:
        report.warnings.append(
            WarningItem(
                code="no_video_files",
                message="No supported video files were found under the source directory.",
                path=str(source_root),
            )
        )
        return report

    for movie_path in movie_files:
        file_size_bytes = safe_file_size(movie_path)

        # Marker-based junk can now stay actionable up to 3 GB, but ambiguous
        # 2-3 GB cases may need probe confirmation for a second signal.
        cheap_reasons = detect_movie_junk_reasons(movie_path, facts=None)
        if cheap_reasons:
            if highest_confidence(cheap_reasons) == "review" and should_probe_marker_junk(movie_path, file_size_bytes):
                cheap_reasons = probe_junk_reasons(report, movie_path, cheap_reasons, probe_media)
            report.junk.append(
                MovieJunkItem(
                    movie_id=movie_id_for(movie_path, source_root),
                    path=str(movie_path),
                    relative_path=movie_id_for(movie_path, source_root),
                    file_name=movie_path.name,
                    file_size_bytes=file_size_bytes,
                    file_size_label=format_file_size(file_size_bytes),
                    runtime_seconds=runtime_for_probe_reasons(cheap_reasons),
                    runtime_label=format_runtime(runtime_for_probe_reasons(cheap_reasons)),
                    confidence=highest_confidence(cheap_reasons),
                    reasons=cheap_reasons,
                )
            )
            continue

        # No marker hit — only probe small files for short-video junk.
        if file_size_bytes is None or file_size_bytes >= GENERAL_PROBE_SIZE_CEILING:
            continue

        facts = probe_media_with_warning(report, movie_path, probe_media)
        if facts is None:
            continue
        reasons = detect_movie_junk_reasons(movie_path, facts)
        if not reasons:
            continue

        runtime_seconds = runtime_for(facts)
        report.junk.append(
            MovieJunkItem(
                movie_id=movie_id_for(movie_path, source_root),
                path=str(movie_path),
                relative_path=movie_id_for(movie_path, source_root),
                file_name=movie_path.name,
                file_size_bytes=file_size_bytes,
                file_size_label=format_file_size(file_size_bytes),
                runtime_seconds=runtime_seconds,
                runtime_label=format_runtime(runtime_seconds),
                confidence=highest_confidence(reasons),
                reasons=reasons,
            )
        )

    report.junk.sort(key=lambda item: (confidence_rank(item.confidence), item.path.lower()))
    return report


def scan_movie_promo_documents(source_root: Path) -> MovieJunkReport:
    report = MovieJunkReport(source_root=str(source_root.resolve()), generated_at=utc_now_iso())
    document_files = discover_junk_document_files(source_root)

    if not document_files:
        report.warnings.append(
            WarningItem(
                code="no_promo_document_files",
                message="No supported promo document files were found under the source directory.",
                path=str(source_root),
            )
        )
        return report

    for document_path in document_files:
        reasons = detect_movie_junk_document_reasons(document_path)
        if not reasons:
            continue
        file_size_bytes = safe_file_size(document_path)
        report.junk.append(
            MovieJunkItem(
                movie_id=movie_id_for(document_path, source_root),
                path=str(document_path),
                relative_path=movie_id_for(document_path, source_root),
                file_name=document_path.name,
                file_size_bytes=file_size_bytes,
                file_size_label=format_file_size(file_size_bytes),
                runtime_seconds=None,
                runtime_label=None,
                confidence=highest_confidence(reasons),
                reasons=reasons,
            )
        )

    report.junk.sort(key=lambda item: (confidence_rank(item.confidence), item.path.lower()))
    return report


def scan_movie_cleanup(
    source_root: Path,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
) -> MovieJunkReport:
    video_report = scan_movie_junk(source_root, probe_media)
    doc_report = scan_movie_promo_documents(source_root)
    merged = MovieJunkReport(
        source_root=str(source_root.resolve()),
        generated_at=utc_now_iso(),
        junk=video_report.junk + doc_report.junk,
        warnings=video_report.warnings + doc_report.warnings,
    )
    merged.junk.sort(key=lambda item: (confidence_rank(item.confidence), item.path.lower()))
    return merged


def discover_junk_document_files(source_root: Path) -> list[Path]:
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and is_supported_junk_document_file(path, source_root)
    )


def is_supported_junk_document_file(path: Path, source_root: Path | None = None) -> bool:
    if path.name.startswith(".") or path.name.startswith("._"):
        return False
    if path.suffix.lower() not in JUNK_DOCUMENT_EXTENSIONS:
        return False
    relative_parts = path.relative_to(source_root).parts if source_root is not None else path.parts
    return not any(part.startswith(".") for part in relative_parts)


def detect_movie_junk_reasons(path: Path, facts: MediaFacts | None = None) -> list[MovieJunkReason]:
    reasons: list[MovieJunkReason] = []
    marker_signals = detect_junk_marker_signals(path)
    file_size = file_size_for(path, facts)
    is_short_video = facts is not None and facts.runtime_seconds is not None and facts.runtime_seconds < SHORT_VIDEO_SECONDS
    is_very_small = file_size is not None and file_size < SMALL_VIDEO_BYTES

    if marker_signals.file_tokens:
        confidence = junk_marker_confidence(
            file_size=file_size,
            has_file_marker=True,
            has_ancestor_marker=bool(marker_signals.ancestor_tokens),
            ancestor_marker_count=len(marker_signals.ancestor_tokens),
            has_strong_marker=marker_signals.has_strong_marker,
            is_short_video=is_short_video,
            is_very_small=is_very_small,
        )
        reasons.append(
            MovieJunkReason(
                code="junk_file_token",
                message=f"Filename contains junk marker: {', '.join(marker_signals.file_tokens)}",
                confidence=confidence,
                matched_value=",".join(marker_signals.file_tokens),
            )
        )

    if marker_signals.ancestor_tokens:
        confidence = junk_marker_confidence(
            file_size=file_size,
            has_file_marker=bool(marker_signals.file_tokens),
            has_ancestor_marker=True,
            ancestor_marker_count=len(marker_signals.ancestor_tokens),
            has_strong_marker=marker_signals.has_strong_marker,
            is_short_video=is_short_video,
            is_very_small=is_very_small,
        )
        reasons.append(
            MovieJunkReason(
                code="junk_ancestor_token",
                message=f"Ancestor path contains junk marker: {', '.join(marker_signals.ancestor_tokens)}",
                confidence=confidence,
                matched_value=",".join(marker_signals.ancestor_tokens),
            )
        )

    if is_short_video:
        reasons.append(
            MovieJunkReason(
                code="short_video",
                message=f"Runtime is under {SHORT_VIDEO_SECONDS // 60} minutes.",
                confidence="high",
                matched_value=str(facts.runtime_seconds),
            )
        )

    if is_very_small and (marker_signals.file_tokens or marker_signals.ancestor_tokens):
        reasons.append(
            MovieJunkReason(
                code="small_video_file",
                message=f"File size is under {SMALL_VIDEO_BYTES // 1024 // 1024} MB.",
                confidence="review",
                matched_value=str(file_size),
            )
        )

    return reasons


@dataclass(frozen=True, slots=True)
class JunkMarkerSignals:
    file_tokens: list[str]
    ancestor_tokens: list[str]
    has_strong_marker: bool


def detect_junk_marker_signals(path: Path) -> JunkMarkerSignals:
    file_tokens = detect_junk_tokens(path.stem)
    ancestor_tokens: list[str] = []
    for part in path.parent.parts:
        for token in detect_junk_tokens(part):
            if token not in ancestor_tokens:
                ancestor_tokens.append(token)
    has_strong_marker = any(is_strong_junk_token(token) for token in [*file_tokens, *ancestor_tokens])
    return JunkMarkerSignals(file_tokens=file_tokens, ancestor_tokens=ancestor_tokens, has_strong_marker=has_strong_marker)


def detect_junk_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    for pattern in (STRONG_JUNK_TOKEN_PATTERN, WEAK_JUNK_TOKEN_PATTERN):
        for match in pattern.finditer(value):
            token = match.group(1).lower()
            if token not in tokens:
                tokens.append(token)
    return tokens


def is_strong_junk_token(token: str) -> bool:
    return STRONG_JUNK_TOKEN_PATTERN.fullmatch(token) is not None


def junk_marker_confidence(
    *,
    file_size: int | None,
    has_file_marker: bool,
    has_ancestor_marker: bool,
    ancestor_marker_count: int,
    has_strong_marker: bool,
    is_short_video: bool,
    is_very_small: bool,
) -> str:
    if is_short_video:
        return "high"

    if file_size is None:
        return "review"

    stacked_signal = is_very_small or (has_file_marker and has_ancestor_marker) or ancestor_marker_count > 1
    if file_size < SAFE_JUNK_MARKER_SIZE_BYTES:
        if has_strong_marker or has_ancestor_marker:
            return "high"
        return "review"
    if file_size < JUNK_MARKER_PROBE_SIZE_CEILING:
        if stacked_signal:
            return "high"
        return "review"
    return "review"


def should_probe_marker_junk(path: Path, file_size: int | None) -> bool:
    marker_signals = detect_junk_marker_signals(path)
    if not (marker_signals.file_tokens or marker_signals.ancestor_tokens):
        return False
    return file_size is not None and file_size < JUNK_MARKER_PROBE_SIZE_CEILING


def probe_junk_reasons(
    report: MovieJunkReport,
    movie_path: Path,
    cheap_reasons: list[MovieJunkReason],
    probe_media: Callable[[Path], MediaFacts],
) -> list[MovieJunkReason]:
    facts = probe_media_with_warning(report, movie_path, probe_media)
    if facts is None:
        return cheap_reasons
    return detect_movie_junk_reasons(movie_path, facts)


def probe_media_with_warning(
    report: MovieJunkReport,
    movie_path: Path,
    probe_media: Callable[[Path], MediaFacts],
) -> MediaFacts | None:
    try:
        return probe_media(movie_path)
    except Exception as exc:
        report.warnings.append(
            WarningItem(
                code="movie_junk_probe_error",
                message=f"Unable to probe media metadata for duration checks: {exc}",
                path=str(movie_path),
            )
        )
        return None


def runtime_for_probe_reasons(reasons: list[MovieJunkReason]) -> int | None:
    short_reason = next((reason for reason in reasons if reason.code == "short_video"), None)
    if short_reason is None or short_reason.matched_value is None:
        return None
    try:
        return int(short_reason.matched_value)
    except ValueError:
        return None


def detect_movie_junk_document_reasons(path: Path) -> list[MovieJunkReason]:
    reasons = []
    name_match = PROMO_DOCUMENT_NAME_PATTERN.search(path.name)
    if name_match is not None:
        reasons.append(
            MovieJunkReason(
                code="promo_document_name",
                message=f"Document name contains promo marker: {name_match.group(1)}",
                confidence="high",
                matched_value=name_match.group(1),
            )
        )

    content_match = promo_document_content_match(path)
    if content_match is not None:
        reasons.append(
            MovieJunkReason(
                code="promo_document_content",
                message=f"Document content contains promo marker: {content_match}",
                confidence="review" if reasons else "high",
                matched_value=content_match,
            )
        )

    return reasons


def promo_document_content_match(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read(PROMO_DOCUMENT_READ_LIMIT)
    except OSError:
        return None
    match = PROMO_DOCUMENT_CONTENT_PATTERN.search(content)
    if match is None:
        return None
    return match.group(1)


def safe_file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def file_size_for(path: Path, facts: MediaFacts | None) -> int | None:
    return facts.file_size_bytes if facts is not None else safe_file_size(path)


def runtime_for(facts: MediaFacts | None) -> int | None:
    return facts.runtime_seconds if facts is not None else None


def format_file_size(size_bytes: int | None) -> str | None:
    if size_bytes is None:
        return None
    if size_bytes < 1024:
        return f"{size_bytes} B"
    mib = size_bytes / 1024 / 1024
    if mib < 1024:
        return f"{mib:.1f} MB"
    gib = mib / 1024
    return f"{gib:.2f} GB"


def format_runtime(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    total_seconds = max(0, int(seconds))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def highest_confidence(reasons: list[MovieJunkReason]) -> str:
    return min((reason.confidence for reason in reasons), key=confidence_rank)


def confidence_rank(confidence: str) -> int:
    return {"high": 0, "review": 1}.get(confidence, 99)
