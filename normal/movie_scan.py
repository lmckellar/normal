from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Callable

from normal.models import WarningItem, utc_now_iso
from normal.quality_review import (
    AudioStreamFacts,
    MediaFacts,
    SubtitleStreamFacts,
    build_audio_summary,
    QualityReview,
    score_quality_review,
)


VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".m4v",
    ".avi",
    ".mov",
    ".wmv",
    ".mpg",
    ".mpeg",
    ".ts",
    ".m2ts",
    ".webm",
}

STATUS_PRIORITY = {"severe": 0, "review": 1, "ok": 2, "unscored": 3}
YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|2100)(?!\d)")
FFPROBE_TIMEOUT_SECONDS = 30


@dataclass(slots=True)
class MovieReviewItem:
    movie_id: str
    path: str
    review: QualityReview
    replacement_priority_score: float
    replacement_priority_label: str
    replacement_year_hint: int | None
    triage_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MovieScanReport:
    source_root: str
    generated_at: str
    movies: list[MovieReviewItem] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MovieScanProgress:
    processed: int
    total: int
    current_path: str | None
    elapsed_seconds: float
    eta_seconds: float | None
    status: str


def build_empty_movie_scan_report(source_root: Path) -> MovieScanReport:
    return MovieScanReport(
        source_root=str(source_root.resolve()),
        generated_at=utc_now_iso(),
    )


def iter_video_files(
    source_root: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
) -> Any:
    yield from _iter_video_files(source_root, source_root=source_root, should_cancel=should_cancel)


def discover_video_files(source_root: Path) -> list[Path]:
    return list(iter_video_files(source_root))


def _iter_video_files(
    current_root: Path,
    *,
    source_root: Path,
    should_cancel: Callable[[], bool] | None,
) -> Any:
    if should_cancel is not None and should_cancel():
        return
    try:
        with os.scandir(current_root) as entries:
            ordered = sorted(entries, key=lambda entry: entry.name.lower())
    except OSError:
        return
    for entry in ordered:
        if should_cancel is not None and should_cancel():
            return
        path = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            if entry.name.startswith("."):
                continue
            yield from _iter_video_files(path, source_root=source_root, should_cancel=should_cancel)
            continue
        if not entry.is_file(follow_symlinks=False):
            continue
        if is_supported_video_file(path, source_root):
            yield path


def is_supported_video_file(path: Path, source_root: Path | None = None) -> bool:
    if path.name.startswith(".") or path.name.startswith("._"):
        return False
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return False

    relative_parts = path.relative_to(source_root).parts if source_root is not None else path.parts
    return not any(part.startswith(".") for part in relative_parts)


def movie_id_for(path: Path, source_root: Path) -> str:
    return str(path.relative_to(source_root))


def extract_year_hint(path: Path) -> int | None:
    match = YEAR_PATTERN.search(str(path))
    if match is None:
        return None
    year = int(match.group(1))
    if 1888 <= year <= 2100:
        return year
    return None


def score_replacement_priority(path: Path) -> tuple[float, str, int | None]:
    year_hint = extract_year_hint(path)
    score = 1.0
    if year_hint is not None:
        if year_hint <= 1989:
            score = 0.6
        elif year_hint <= 1999:
            score = 0.75
        elif year_hint <= 2009:
            score = 0.9
        elif year_hint <= 2019:
            score = 1.0
        else:
            score = 1.1

    if score >= 1.05:
        label = "high"
    elif score >= 0.95:
        label = "medium"
    elif score >= 0.7:
        label = "low"
    else:
        label = "very_low"
    return score, label, year_hint


def probe_media_facts(path: Path) -> MediaFacts:
    payload = run_ffprobe(path)
    return media_facts_from_ffprobe_payload(payload, path)


def run_ffprobe(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,bit_rate,format_name,start_time:stream=index,codec_type,codec_name,width,height,bit_rate,channels,pix_fmt,profile,level,avg_frame_rate,r_frame_rate:stream_disposition=default:stream_tags",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS}s") from exc
    if result.returncode != 0:
        stderr = result.stderr.strip() or "ffprobe failed"
        raise RuntimeError(stderr)
    return json.loads(result.stdout)


def media_facts_from_ffprobe_payload(payload: dict[str, Any], path: Path) -> MediaFacts:
    streams = payload.get("streams", [])
    format_payload = payload.get("format", {})
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    subtitle_streams = [stream for stream in streams if stream.get("codec_type") == "subtitle"]
    attachment_streams = [stream for stream in streams if stream.get("codec_type") == "attachment"]
    video_stream = video_streams[0] if video_streams else {}
    audio_stream = audio_streams[0] if audio_streams else {}
    total_bitrate_kbps = parse_bitrate_kbps(format_payload.get("bit_rate"))
    audio_bitrates = [bitrate for bitrate in (parse_stream_bitrate_kbps(stream) for stream in audio_streams) if bitrate]
    primary_audio_bitrate = parse_stream_bitrate_kbps(audio_stream) or (audio_bitrates[0] if audio_bitrates else None)
    video_bitrate_kbps = parse_stream_bitrate_kbps(video_stream)
    video_bitrate_approximate = False
    if video_bitrate_kbps is None and total_bitrate_kbps is not None:
        estimated = total_bitrate_kbps - sum(audio_bitrates) if audio_bitrates else total_bitrate_kbps
        if estimated > 0:
            video_bitrate_kbps = estimated
            video_bitrate_approximate = True
    detailed_audio_streams = [audio_stream_facts_from_ffprobe_stream(stream) for stream in audio_streams]
    detailed_subtitle_streams = [subtitle_stream_facts_from_ffprobe_stream(stream) for stream in subtitle_streams]
    display_audio_stream = choose_display_audio_stream(detailed_audio_streams)
    default_audio_stream = choose_default_audio_stream(detailed_audio_streams)
    default_subtitle_stream = choose_default_subtitle_stream(detailed_subtitle_streams)
    (
        audio_format_family,
        audio_format_variant,
        audio_channel_layout,
        audio_immersive_extension,
        audio_summary,
    ) = build_audio_summary(
        display_audio_stream.codec if display_audio_stream else audio_stream.get("codec_name"),
        display_audio_stream.channels if display_audio_stream else parse_int(audio_stream.get("channels")),
        display_audio_stream.profile if display_audio_stream else (audio_stream.get("profile") or None),
        display_audio_stream.title if display_audio_stream else None,
    )

    return MediaFacts(
        runtime_seconds=parse_seconds(format_payload.get("duration")),
        file_size_bytes=parse_int(format_payload.get("size")) or path.stat().st_size,
        container=first_csv_value(format_payload.get("format_name")),
        width=parse_int(video_stream.get("width")),
        height=parse_int(video_stream.get("height")),
        video_codec=video_stream.get("codec_name"),
        video_bitrate_kbps=video_bitrate_kbps,
        audio_codec=audio_stream.get("codec_name"),
        audio_bitrate_kbps=primary_audio_bitrate,
        audio_channels=parse_int(audio_stream.get("channels")),
        audio_profile=audio_stream.get("profile") or None,
        audio_display_stream_index=display_audio_stream.index if display_audio_stream else None,
        audio_format_family=audio_format_family,
        audio_format_variant=audio_format_variant,
        audio_channel_layout=audio_channel_layout,
        audio_immersive_extension=audio_immersive_extension,
        audio_summary=audio_summary,
        total_bitrate_kbps=total_bitrate_kbps,
        name_resolution_hint=None,
        resolution_bucket=None,
        video_bitrate_approximate=video_bitrate_approximate,
        video_profile=video_stream.get("profile"),
        video_level=parse_int(video_stream.get("level")),
        pixel_format=video_stream.get("pix_fmt"),
        frame_rate=parse_ratio(video_stream.get("r_frame_rate")),
        average_frame_rate=parse_ratio(video_stream.get("avg_frame_rate")),
        video_stream_count=len(video_streams),
        audio_stream_count=len(audio_streams),
        subtitle_stream_count=len(subtitle_streams),
        audio_codecs=[stream.get("codec_name", "") for stream in audio_streams if stream.get("codec_name")],
        subtitle_codecs=[stream.get("codec_name", "") for stream in subtitle_streams if stream.get("codec_name")],
        attachment_stream_count=len(attachment_streams),
        default_audio_streams=count_default_streams(audio_streams),
        default_subtitle_streams=count_default_streams(subtitle_streams),
        default_audio_stream_index=default_audio_stream.index if default_audio_stream else None,
        default_subtitle_stream_index=default_subtitle_stream.index if default_subtitle_stream else None,
        audio_streams=detailed_audio_streams,
        subtitle_streams=detailed_subtitle_streams,
    )


def parse_seconds(value: Any) -> int | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return int(round(seconds))


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bitrate_kbps(value: Any) -> int | None:
    parsed = parse_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed // 1000


def parse_stream_bitrate_kbps(stream: dict[str, Any]) -> int | None:
    bitrate = parse_bitrate_kbps(stream.get("bit_rate"))
    if bitrate is not None:
        return bitrate
    tags = stream.get("tags")
    if not isinstance(tags, dict):
        return None
    for key, value in tags.items():
        if str(key).casefold() == "bps" or str(key).casefold().startswith("bps-"):
            bitrate = parse_bitrate_kbps(value)
            if bitrate is not None:
                return bitrate
    return None


def audio_stream_facts_from_ffprobe_stream(stream: dict[str, Any]) -> AudioStreamFacts:
    tags = stream.get("tags")
    if not isinstance(tags, dict):
        tags = {}
    disposition = stream.get("disposition")
    if not isinstance(disposition, dict):
        disposition = {}
    return AudioStreamFacts(
        index=parse_int(stream.get("index")),
        codec=stream.get("codec_name"),
        bitrate_kbps=parse_stream_bitrate_kbps(stream),
        channels=parse_int(stream.get("channels")),
        profile=stream.get("profile") or None,
        language=normalize_language_tag(tags.get("language")),
        title=first_text(tags.get("title"), tags.get("handler_name")),
        is_default=bool(disposition.get("default")),
    )


def subtitle_stream_facts_from_ffprobe_stream(stream: dict[str, Any]) -> SubtitleStreamFacts:
    tags = stream.get("tags")
    if not isinstance(tags, dict):
        tags = {}
    disposition = stream.get("disposition")
    if not isinstance(disposition, dict):
        disposition = {}
    return SubtitleStreamFacts(
        index=parse_int(stream.get("index")),
        codec=stream.get("codec_name"),
        language=normalize_language_tag(tags.get("language")),
        title=first_text(tags.get("title"), tags.get("handler_name")),
        is_default=bool(disposition.get("default")),
        is_forced=bool(disposition.get("forced")),
    )


def choose_display_audio_stream(streams: list[AudioStreamFacts]) -> AudioStreamFacts | None:
    default_streams = [stream for stream in streams if stream.is_default]
    if len(default_streams) == 1:
        return default_streams[0]
    return streams[0] if streams else None


def choose_default_audio_stream(streams: list[AudioStreamFacts]) -> AudioStreamFacts | None:
    for stream in streams:
        if stream.is_default:
            return stream
    return streams[0] if streams else None


def choose_default_subtitle_stream(streams: list[SubtitleStreamFacts]) -> SubtitleStreamFacts | None:
    for stream in streams:
        if stream.is_default:
            return stream
    return streams[0] if streams else None


def normalize_language_tag(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.casefold()


def first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def parse_ratio(value: Any) -> float | None:
    if value in (None, "", "0/0"):
        return None
    text = str(value)
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_float = float(denominator)
            if denominator_float == 0:
                return None
            return float(numerator) / denominator_float
        except (TypeError, ValueError):
            return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def count_default_streams(streams: list[dict[str, Any]]) -> int:
    total = 0
    for stream in streams:
        disposition = stream.get("disposition") or {}
        if disposition.get("default") == 1:
            total += 1
    return total


def first_csv_value(value: Any) -> str | None:
    if not value:
        return None
    return str(value).split(",", 1)[0].strip() or None


def scan_movie_library(
    source_root: Path,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: Callable[[MovieScanProgress], None] | None = None,
) -> MovieScanReport:
    report = build_empty_movie_scan_report(source_root)
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

    total_files = len(movie_files)
    started_at = time.monotonic()
    emit_progress(progress_callback, 0, total_files, None, started_at, "starting")

    for index, movie_path in enumerate(movie_files, start=1):
        try:
            facts = probe_media(movie_path)
        except (OSError, RuntimeError, json.JSONDecodeError) as exc:
            report.warnings.append(
                WarningItem(
                    code="movie_probe_error",
                    message=f"Unable to probe media metadata: {exc}",
                    path=str(movie_path),
                )
            )
            emit_progress(progress_callback, index, total_files, movie_path, started_at, "warning")
            continue

        replacement_priority_score, replacement_priority_label, replacement_year_hint = score_replacement_priority(
            movie_path
        )
        report.movies.append(
            MovieReviewItem(
                movie_id=movie_id_for(movie_path, source_root),
                path=str(movie_path),
                review=score_quality_review(facts, path=movie_path.name),
                replacement_priority_score=replacement_priority_score,
                replacement_priority_label=replacement_priority_label,
                replacement_year_hint=replacement_year_hint,
                triage_score=0.0,
            )
        )
        item = report.movies[-1]
        item.triage_score = round(item.review.score * item.replacement_priority_score, 1)
        emit_progress(progress_callback, index, total_files, movie_path, started_at, "running")

    report.movies.sort(
        key=lambda item: (
            -item.triage_score,
            STATUS_PRIORITY.get(item.review.status, 99),
            -item.review.score,
            item.path.lower(),
        )
    )
    emit_progress(progress_callback, total_files, total_files, None, started_at, "complete")
    return report


def emit_progress(
    progress_callback: Callable[[MovieScanProgress], None] | None,
    processed: int,
    total: int,
    current_path: Path | None,
    started_at: float,
    status: str,
) -> None:
    if progress_callback is None:
        return

    elapsed_seconds = max(0.0, time.monotonic() - started_at)
    eta_seconds = estimate_eta_seconds(processed, total, elapsed_seconds)
    progress_callback(
        MovieScanProgress(
            processed=processed,
            total=total,
            current_path=str(current_path) if current_path is not None else None,
            elapsed_seconds=elapsed_seconds,
            eta_seconds=eta_seconds,
            status=status,
        )
    )


def estimate_eta_seconds(processed: int, total: int, elapsed_seconds: float) -> float | None:
    if processed <= 0 or total <= processed:
        return 0.0 if total and processed >= total else None
    rate = elapsed_seconds / processed
    return rate * (total - processed)
