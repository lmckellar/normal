from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import chain
from pathlib import Path
import re
from statistics import mean, median
import time
from typing import Any, Callable

from normal.models import WarningItem, utc_now_iso
from normal.movie_scan import (
    MovieScanProgress,
    emit_progress,
    iter_video_files,
    movie_id_for,
    probe_media_facts,
)
from normal.quality_review import AudioStreamFacts, MediaFacts, classify_resolution


ANCHOR_KBPS = {"1080p": 18000, "2160p": 45000}
ANIME_EPISODE_PATTERN = re.compile(r"\b\d{1,3}\b")
SEASON_EPISODE_PATTERN = re.compile(r"\bs\d{1,2}e\d{1,3}\b", re.IGNORECASE)


@dataclass(slots=True)
class DiagnosticFinding:
    code: str
    severity: str
    category: str
    summary: str
    remedy: str


@dataclass(slots=True)
class MovieProfile:
    label: str
    rank: int
    percentile: float
    anchor_distance: float | None
    diagnostics: list[DiagnosticFinding] = field(default_factory=list)
    risk_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class MovieProfileItem:
    movie_id: str
    path: str
    facts: MediaFacts
    runtime_minutes: float | None
    profile: MovieProfile


@dataclass(slots=True)
class MovieProfileReport:
    source_root: str
    generated_at: str
    movies: list[MovieProfileItem] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILE_RANKS = {
    "sd_low_quality": 1,
    "weak_1080p": 2,
    "minimum_acceptable_1080p": 3,
    "compressed_1080p": 4,
    "1080p_uhd": 5,
    "weak_4k": 6,
    "compressed_4k": 7,
    "4k_uhd": 8,
    "4k_remux": 9,
    "unclassified": 10,
}


def scan_movie_profiles(
    source_root: Path,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: Callable[[MovieScanProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> MovieProfileReport:
    report = MovieProfileReport(source_root=str(source_root.resolve()), generated_at=utc_now_iso())
    movie_files = iter_video_files(source_root, should_cancel=should_cancel)
    first_movie = next(movie_files, None)
    if first_movie is None:
        report.warnings.append(
            WarningItem(
                code="no_video_files",
                message="No supported video files were found under the source directory.",
                path=str(source_root),
            )
        )
        return report

    started = time.monotonic()
    total = 0
    emit_progress(progress_callback, 0, total, None, started, "starting")

    for index, movie_path in enumerate(chain([first_movie], movie_files), start=1):
        if should_cancel is not None and should_cancel():
            report.warnings.append(
                WarningItem(
                    code="movie_profile_cancelled",
                    message="Movie profile scan was cancelled before completion.",
                    path=str(source_root),
                )
            )
            break
        try:
            facts = probe_media(movie_path)
        except Exception as exc:
            report.warnings.append(
                WarningItem(
                    code="movie_profile_probe_error",
                    message=f"Unable to probe media metadata: {exc}",
                    path=str(movie_path),
                )
            )
            emit_progress(progress_callback, index, total, movie_path, started, "warning")
            continue

        facts.resolution_bucket = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
        report.movies.append(build_movie_profile_item(source_root, movie_path, facts))
        emit_progress(progress_callback, index, total, movie_path, started, "running")

    assign_percentiles(report.movies)
    report.movies.sort(key=lambda item: (total_risk_score(item.profile.diagnostics), item.profile.rank, item.path.lower()), reverse=True)
    emit_progress(progress_callback, total, total, None, started, "complete")
    return report


def build_movie_profile_item(source_root: Path, movie_path: Path, facts: MediaFacts) -> MovieProfileItem:
    facts.resolution_bucket = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
    label = classify_profile_label(facts)
    diagnostics = detect_plex_diagnostics(movie_path, facts)
    return MovieProfileItem(
        movie_id=movie_id_for(movie_path, source_root),
        path=str(movie_path),
        facts=facts,
        runtime_minutes=round(facts.runtime_seconds / 60, 1) if facts.runtime_seconds else None,
        profile=MovieProfile(
            label=label,
            rank=PROFILE_RANKS[label],
            percentile=0.0,
            anchor_distance=compute_anchor_distance(facts),
            diagnostics=diagnostics,
            risk_counts=build_risk_counts(diagnostics),
        ),
    )


def classify_profile_label(facts: MediaFacts) -> str:
    resolution = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
    video = facts.video_bitrate_kbps or 0

    if resolution == "2160p":
        if video >= 24000:
            return "4k_remux"
        if video >= 12000:
            return "4k_uhd"
        if video >= 6000:
            return "compressed_4k"
        if video > 0:
            return "weak_4k"
        return "unclassified"
    if resolution == "1080p":
        if video >= 16000:
            return "1080p_uhd"
        if video >= 6000:
            return "compressed_1080p"
        if video >= 4500:
            return "minimum_acceptable_1080p"
        if video > 0:
            return "weak_1080p"
        return "unclassified"
    if resolution in {"720p", "sd"}:
        return "sd_low_quality"
    return "unclassified"


def compute_anchor_distance(facts: MediaFacts) -> float | None:
    resolution = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
    anchor = ANCHOR_KBPS.get(resolution or "")
    bitrate = facts.video_bitrate_kbps
    if not anchor or not bitrate:
        return None
    return round((bitrate / anchor) - 1.0, 3)


def assign_percentiles(items: list[MovieProfileItem]) -> None:
    by_resolution: dict[str, list[MovieProfileItem]] = {}
    for item in items:
        resolution = item.facts.resolution_bucket or "unknown"
        by_resolution.setdefault(resolution, []).append(item)

    for bucket_items in by_resolution.values():
        ordered = sorted(bucket_items, key=profile_sort_key)
        total = len(ordered)
        if total == 1:
            ordered[0].profile.percentile = 100.0
            continue
        for index, item in enumerate(ordered, start=1):
            item.profile.percentile = round(((index - 1) / (total - 1)) * 100, 1)


def profile_sort_key(item: MovieProfileItem) -> tuple[float, int, str]:
    bitrate = float(item.facts.video_bitrate_kbps or 0)
    return (bitrate, item.profile.rank, item.path.lower())


def detect_plex_diagnostics(path: Path | str, facts: MediaFacts) -> list[DiagnosticFinding]:
    findings: list[DiagnosticFinding] = []
    lower_audio = {codec.lower() for codec in facts.audio_codecs}
    lower_subs = {codec.lower() for codec in facts.subtitle_codecs}
    path_text = str(path)

    if "dts" in lower_audio and not has_compat_audio_track(lower_audio):
        findings.append(
            DiagnosticFinding(
                code="dts_no_compat_track",
                severity="review",
                category="playback_risk",
                summary="DTS is present without an AC3 or AAC fallback track, which can break smooth Plex playback on some clients.",
                remedy="Add an AC3 compatibility track while preserving the original DTS stream.",
            )
        )
    if facts.container in {"avi", "asf", "wmv"}:
        findings.append(
            DiagnosticFinding(
                code="legacy_container",
                severity="review",
                category="playback_risk",
                summary="Legacy container is more likely to trigger Plex remuxing or playback issues.",
                remedy="Remux to MKV first before attempting a full transcode.",
            )
        )
    if lower_subs & {"hdmv_pgs_subtitle", "dvd_subtitle"}:
        findings.append(
            DiagnosticFinding(
                code="image_subtitle_transcode_risk",
                severity="review",
                category="playback_risk",
                summary="Image-based subtitles are likely to force a transcode in Plex clients.",
                remedy="Strip or convert subtitle streams for a direct-play test.",
            )
        )
    if facts.video_stream_count > 1:
        findings.append(
            DiagnosticFinding(
                code="multiple_video_streams",
                severity="severe",
                category="playback_risk",
                summary="Multiple video streams can confuse Plex playback and force remuxing.",
                remedy="Remux the file to keep only the intended primary video stream.",
            )
        )
    if facts.default_audio_streams > 1 or facts.default_subtitle_streams > 1:
        findings.append(
            DiagnosticFinding(
                code="multiple_default_streams",
                severity="review",
                category="playback_risk",
                summary="Multiple default streams can lead to unstable stream selection in Plex.",
                remedy="Reset stream default flags so only one audio and one subtitle stream are default.",
            )
        )
    findings.extend(detect_audio_language_selection_risks(facts))
    if facts.video_bitrate_kbps is None and facts.total_bitrate_kbps is None:
        findings.append(
            DiagnosticFinding(
                code="missing_bitrate_metadata",
                severity="review",
                category="playback_risk",
                summary="Sparse bitrate metadata can indicate a muxing issue that VLC tolerates better than Plex.",
                remedy="Remux with ffmpeg or mkvmerge to rebuild container indexes and metadata.",
            )
        )
    if facts.frame_rate and facts.average_frame_rate and abs(facts.frame_rate - facts.average_frame_rate) > 0.5:
        findings.append(
            DiagnosticFinding(
                code="variable_frame_rate_risk",
                severity="review",
                category="playback_risk",
                summary="Frame rate metadata suggests a variable or inconsistent cadence that may stutter in Plex.",
                remedy="Remux first; if the issue persists, normalize to CFR during a controlled transcode.",
            )
        )
    if facts.video_level and facts.video_level >= 51 and (facts.video_codec or "").lower() in {"h264", "x264"}:
        findings.append(
            DiagnosticFinding(
                code="high_h264_level",
                severity="review",
                category="playback_risk",
                summary="High H.264 level values can exceed some Plex client direct-play capabilities.",
                remedy="Test a remux, then consider a compatibility transcode if the client still buffers.",
            )
        )
    if is_attachment_heavy_anime_mux(path_text, facts):
        findings.append(
            DiagnosticFinding(
                code="anime_subtitle_attachment_risk",
                severity="review",
                category="playback_risk",
                summary="Anime-style ASS subtitles with many embedded font attachments are a common Plex and Jellyfin trouble pattern.",
                remedy="Test with subtitles disabled, then consider a compatibility file with simplified subtitles or no attachments.",
            )
        )
    if facts.audio_stream_count >= 3 and is_episode_like_path(path_text):
        findings.append(
            DiagnosticFinding(
                code="multi_audio_anime_mux_risk",
                severity="review",
                category="playback_risk",
                summary="Multiple audio tracks in an episodic release increase the chance of Plex selecting an awkward transcode path.",
                remedy="Review stream defaults and consider adding one compatibility-default audio track.",
            )
        )
    if facts.video_codec and facts.video_codec.lower() in {"hevc", "h265"} and facts.pixel_format and "10" in facts.pixel_format and is_episode_like_path(path_text):
        findings.append(
            DiagnosticFinding(
                code="high_complexity_hevc_tv_risk",
                severity="review",
                category="playback_risk",
                summary="HEVC 10-bit episodic encodes are more likely to expose Plex client playback limits than movie remuxes.",
                remedy="Keep the original, but consider a lighter compatibility encode for the problematic client path.",
            )
        )
    if not looks_like_plex_friendly_episode_name(path_text) and is_episode_like_path(path_text):
        findings.append(
            DiagnosticFinding(
                code="episodic_naming_parse_risk",
                severity="review",
                category="indexing_visibility_risk",
                summary="Episode naming does not look Plex-friendly, which can cause TV files to index inconsistently or disappear from the library view.",
                remedy="Rename episodic files to a standard pattern like `Series Name - s01e01 - Episode Title.ext`.",
            )
        )
    if looks_like_absolute_numbering(path_text):
        findings.append(
            DiagnosticFinding(
                code="anime_absolute_numbering_risk",
                severity="review",
                category="indexing_visibility_risk",
                summary="Absolute-number anime naming without explicit season/episode markers is a common Plex indexing failure mode.",
                remedy="Add explicit season and episode numbering to the filename or folder structure.",
            )
        )
    if facts.attachment_stream_count >= 4:
        findings.append(
            DiagnosticFinding(
                code="attachment_heavy_visibility_risk",
                severity="review",
                category="indexing_visibility_risk",
                summary="Attachment-heavy MKV files are more likely to be malformed or to behave inconsistently in library scanners.",
                remedy="Remux to a clean MKV and confirm the scanner sees the new file consistently.",
            )
        )
    if facts.default_audio_streams == 0 and facts.audio_stream_count > 1:
        findings.append(
            DiagnosticFinding(
                code="missing_default_audio_flag_risk",
                severity="review",
                category="indexing_visibility_risk",
                summary="Multiple audio tracks without a default flag can lead to inconsistent client and scanner behavior.",
                remedy="Set one preferred audio stream as default.",
            )
        )

    if not findings:
        findings.append(
            DiagnosticFinding(
                code="container_timestamp_unknown",
                severity="review",
                category="playback_risk",
                summary="No obvious Plex-risk flag was visible in ffprobe output, so the issue may be container or timestamp damage.",
                remedy="First-line remedy is a lossless remux to rebuild timestamps and indexes, then re-test in Plex.",
            )
        )
    return findings


def has_compat_audio_track(audio_codecs: set[str]) -> bool:
    return any(codec in {"ac3", "aac", "eac3"} for codec in audio_codecs)


def detect_audio_language_selection_risks(facts: MediaFacts) -> list[DiagnosticFinding]:
    default_stream = choose_default_audio_stream(facts.audio_streams)
    if default_stream is None:
        return []

    default_language = canonical_audio_language(default_stream.language)
    if default_language is None or default_language == "english":
        return []

    english_streams = [stream for stream in facts.audio_streams if canonical_audio_language(stream.language) == "english"]
    if not english_streams:
        return []

    best_english = max(english_streams, key=audio_stream_quality_key)
    if english_stream_is_materially_weaker(default_stream, best_english):
        return [
            DiagnosticFinding(
                code="default_non_english_audio_with_weak_english",
                severity="review",
                category="playback_risk",
                summary=(
                    f"Default audio is {display_audio_language(default_language)} while the best English track looks materially weaker, "
                    "which matches a common multi-audio MKV packaging mistake."
                ),
                remedy=(
                    "Review audio stream order and defaults, then remux so the intended English track is clearly preferred "
                    "or replace the file with a release whose main English track is not the weak fallback."
                ),
            )
        ]

    return [
        DiagnosticFinding(
            code="default_non_english_audio",
            severity="review",
            category="playback_risk",
            summary=(
                f"Default audio is {display_audio_language(default_language)} even though an English track is present, "
                "so clients may auto-pick the wrong language."
            ),
            remedy="Set the intended English stream as default or remux the file so stream flags match playback preference.",
        )
    ]


def choose_default_audio_stream(streams: list[AudioStreamFacts]) -> AudioStreamFacts | None:
    defaults = [stream for stream in streams if stream.is_default]
    if defaults:
        return defaults[0]
    if streams:
        return streams[0]
    return None


def audio_stream_quality_key(stream: AudioStreamFacts) -> tuple[int, int, int]:
    return (
        stream.channels or 0,
        stream.bitrate_kbps or 0,
        -(stream.index or 0),
    )


def english_stream_is_materially_weaker(default_stream: AudioStreamFacts, english_stream: AudioStreamFacts) -> bool:
    default_channels = default_stream.channels or 0
    english_channels = english_stream.channels or 0
    if default_channels >= 6 and english_channels and english_channels <= 2:
        return True
    if default_channels > english_channels:
        return True

    default_bitrate = default_stream.bitrate_kbps or 0
    english_bitrate = english_stream.bitrate_kbps or 0
    if default_bitrate >= 192 and english_bitrate and english_bitrate <= int(default_bitrate * 0.7):
        return True
    if default_bitrate >= 256 and english_bitrate == 0:
        return True
    return False


def canonical_audio_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if not normalized:
        return None
    aliases = {
        "eng": "english",
        "en": "english",
        "english": "english",
        "ita": "italian",
        "it": "italian",
        "italian": "italian",
    }
    return aliases.get(normalized, normalized)


def display_audio_language(value: str) -> str:
    return value.capitalize()


def is_attachment_heavy_anime_mux(path_text: str, facts: MediaFacts) -> bool:
    lower_subs = {codec.lower() for codec in facts.subtitle_codecs}
    return facts.attachment_stream_count >= 4 and bool(lower_subs & {"ass", "ssa"})


def is_episode_like_path(path_text: str) -> bool:
    lower = path_text.lower()
    if SEASON_EPISODE_PATTERN.search(lower):
        return True
    return any(token in lower for token in ("season", "episode", " ep", "tv", "anime"))


def looks_like_plex_friendly_episode_name(path_text: str) -> bool:
    name = Path(path_text).stem
    return SEASON_EPISODE_PATTERN.search(name) is not None or re.search(r"\b\d{1,2}x\d{1,3}\b", name, re.IGNORECASE) is not None


def looks_like_absolute_numbering(path_text: str) -> bool:
    name = Path(path_text).stem
    if looks_like_plex_friendly_episode_name(path_text):
        return False
    stripped = re.sub(r"[\[\]()_.-]+", " ", name)
    return ANIME_EPISODE_PATTERN.search(stripped) is not None


def build_risk_counts(diagnostics: list[DiagnosticFinding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in diagnostics:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    return counts


def total_risk_score(diagnostics: list[DiagnosticFinding]) -> int:
    score = 0
    for finding in diagnostics:
        score += 3 if finding.severity == "severe" else 1
    return score


def build_histogram_payload(report: MovieProfileReport) -> dict[str, Any]:
    video_bitrates = [item.facts.video_bitrate_kbps for item in report.movies if item.facts.video_bitrate_kbps]
    audio_bitrates = [item.facts.audio_bitrate_kbps for item in report.movies if item.facts.audio_bitrate_kbps]
    profile_counts: dict[str, int] = {}
    resolution_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for item in report.movies:
        profile_counts[item.profile.label] = profile_counts.get(item.profile.label, 0) + 1
        resolution = item.facts.resolution_bucket or "unknown"
        resolution_counts[resolution] = resolution_counts.get(resolution, 0) + 1
        for category, count in item.profile.risk_counts.items():
            risk_counts[category] = risk_counts.get(category, 0) + count

    total_size_bytes = sum(item.facts.file_size_bytes for item in report.movies if item.facts.file_size_bytes)
    total_runtime_minutes = round(sum(item.runtime_minutes for item in report.movies if item.runtime_minutes), 1)

    return {
        "source_root": report.source_root,
        "generated_at": report.generated_at,
        "movie_count": len(report.movies),
        "total_size_bytes": total_size_bytes,
        "total_runtime_minutes": total_runtime_minutes,
        "video_bitrate_kbps": summarize_distribution(video_bitrates),
        "audio_bitrate_kbps": summarize_distribution(audio_bitrates, bin_width=150),
        "profile_counts": profile_counts,
        "resolution_counts": resolution_counts,
        "risk_counts": risk_counts,
        "anchor_reference": {"1080p_uhd_kbps": ANCHOR_KBPS["1080p"]},
    }


def summarize_distribution(values: list[int], bin_width: int = 2000) -> dict[str, Any]:
    if not values:
        return {"mean": None, "median": None, "p10": None, "p50": None, "p90": None, "p95": None, "bins": []}
    ordered = sorted(values)
    return {
        "mean": round(mean(ordered), 1),
        "median": round(median(ordered), 1),
        "p10": percentile(ordered, 10),
        "p50": percentile(ordered, 50),
        "p90": percentile(ordered, 90),
        "p95": percentile(ordered, 95),
        "bins": build_bins(ordered, bin_width),
    }


def percentile(values: list[int], target: int) -> float:
    index = (len(values) - 1) * (target / 100)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return round(values[lower] + (values[upper] - values[lower]) * weight, 1)


def build_bins(values: list[int], width: int = 2000) -> list[dict[str, int]]:
    bins: dict[int, int] = {}
    for value in values:
        floor = (value // width) * width
        bins[floor] = bins.get(floor, 0) + 1
    return [{"start_kbps": start, "end_kbps": start + width - 1, "count": count} for start, count in sorted(bins.items())]
