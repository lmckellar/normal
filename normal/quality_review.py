from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import re
from typing import Any


THRESHOLDS: dict[str, dict[str, dict[str, int]]] = {
    "2160p": {
        "video_kbps": {"severe_below": 8000, "review_below": 12000},
        "mb_per_min": {"severe_below": 35, "review_below": 55},
    },
    "1080p": {
        "video_kbps": {"severe_below": 3000, "review_below": 4500},
        "mb_per_min": {"severe_below": 12, "review_below": 20},
    },
    "720p": {
        "video_kbps": {"severe_below": 1800, "review_below": 2500},
        "mb_per_min": {"severe_below": 7, "review_below": 11},
    },
}

WEIGHTS = {
    "video_severe": 60,
    "video_review": 35,
    "size_severe": 35,
    "size_review": 20,
    "audio_severe": 25,
    "audio_review": 12,
    "resolution_mismatch": 25,
    "legacy_codec": 8,
}

NAME_RESOLUTION_PATTERN = re.compile(r"(?<!\d)(2160p|1080p|720p|4k)(?!\d)", re.IGNORECASE)
LEGACY_VIDEO_CODECS = {"mpeg2video", "mpeg4", "msmpeg4", "xvid", "divx"}


@dataclass(slots=True)
class QualityReason:
    code: str
    severity: str
    message: str


@dataclass(slots=True)
class MediaFacts:
    runtime_seconds: int | None = None
    file_size_bytes: int | None = None
    container: str | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    video_bitrate_kbps: int | None = None
    audio_codec: str | None = None
    audio_bitrate_kbps: int | None = None
    audio_channels: int | None = None
    audio_profile: str | None = None
    total_bitrate_kbps: int | None = None
    name_resolution_hint: str | None = None
    resolution_bucket: str | None = None
    video_bitrate_approximate: bool = False
    video_profile: str | None = None
    video_level: int | None = None
    pixel_format: str | None = None
    frame_rate: float | None = None
    average_frame_rate: float | None = None
    video_stream_count: int = 0
    audio_stream_count: int = 0
    subtitle_stream_count: int = 0
    subtitle_codecs: list[str] = field(default_factory=list)
    audio_codecs: list[str] = field(default_factory=list)
    attachment_stream_count: int = 0
    default_audio_streams: int = 0
    default_subtitle_streams: int = 0


@dataclass(slots=True)
class DerivedMetrics:
    mb_per_min: float | None = None


@dataclass(slots=True)
class QualityReview:
    status: str
    score: int
    confidence: str
    reasons: list[QualityReason] = field(default_factory=list)
    facts: MediaFacts = field(default_factory=MediaFacts)
    derived: DerivedMetrics = field(default_factory=DerivedMetrics)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_resolution(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None

    long_edge = max(width, height)
    short_edge = min(width, height)
    if long_edge >= 3000:
        return "2160p"
    if long_edge >= 1800 or short_edge >= 1080:
        return "1080p"
    if long_edge >= 1200:
        return "720p"
    return "sd"


def calc_mb_per_min(file_size_bytes: int | None, runtime_seconds: int | None) -> float | None:
    if not file_size_bytes or not runtime_seconds or runtime_seconds <= 0:
        return None
    return (file_size_bytes / 1024 / 1024) / (runtime_seconds / 60)


def parse_name_resolution_hint(path: str | Path | None) -> str | None:
    if path is None:
        return None

    match = NAME_RESOLUTION_PATTERN.search(Path(path).name)
    if match is None:
        return None

    value = match.group(1).lower()
    if value == "4k":
        return "2160p"
    return value


def is_legacy_codec(video_codec: str | None) -> bool:
    if not video_codec:
        return False
    return video_codec.lower() in LEGACY_VIDEO_CODECS


def classify_confidence(facts: MediaFacts, resolution_bucket: str | None) -> str:
    primary_available = sum(
        [
            1 if facts.runtime_seconds else 0,
            1 if resolution_bucket else 0,
            1 if facts.video_bitrate_kbps else 0,
        ]
    )
    if primary_available == 3:
        return "high"
    if primary_available >= 2:
        return "medium"
    return "low"


def approximate_video_bitrate_kbps(
    video_bitrate_kbps: int | None,
    total_bitrate_kbps: int | None,
    audio_bitrate_kbps: int | None,
) -> tuple[int | None, bool]:
    if video_bitrate_kbps:
        return video_bitrate_kbps, False
    if total_bitrate_kbps and audio_bitrate_kbps and total_bitrate_kbps > audio_bitrate_kbps:
        return total_bitrate_kbps - audio_bitrate_kbps, True
    return None, False


def score_quality_review(facts: MediaFacts, path: str | Path | None = None) -> QualityReview:
    resolved_hint = facts.name_resolution_hint or parse_name_resolution_hint(path)
    resolution_bucket = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
    video_bitrate_kbps, bitrate_is_approximate = approximate_video_bitrate_kbps(
        facts.video_bitrate_kbps,
        facts.total_bitrate_kbps,
        facts.audio_bitrate_kbps,
    )
    derived = DerivedMetrics(
        mb_per_min=calc_mb_per_min(facts.file_size_bytes, facts.runtime_seconds),
    )

    normalized_facts = MediaFacts(
        runtime_seconds=facts.runtime_seconds,
        file_size_bytes=facts.file_size_bytes,
        container=facts.container,
        width=facts.width,
        height=facts.height,
        video_codec=facts.video_codec,
        video_bitrate_kbps=video_bitrate_kbps,
        audio_codec=facts.audio_codec,
        audio_bitrate_kbps=facts.audio_bitrate_kbps,
        audio_channels=facts.audio_channels,
        total_bitrate_kbps=facts.total_bitrate_kbps,
        name_resolution_hint=resolved_hint,
        resolution_bucket=resolution_bucket,
        video_bitrate_approximate=bitrate_is_approximate,
    )

    score = 0
    reasons: list[QualityReason] = []

    if resolution_bucket in THRESHOLDS:
        limits = THRESHOLDS[resolution_bucket]

        if video_bitrate_kbps:
            if video_bitrate_kbps < limits["video_kbps"]["severe_below"]:
                score += WEIGHTS["video_severe"]
                reasons.append(
                    QualityReason(
                        code="low_video_bitrate",
                        severity="severe",
                        message=f"Video bitrate is very low for {resolution_bucket}.",
                    )
                )
            elif video_bitrate_kbps < limits["video_kbps"]["review_below"]:
                score += WEIGHTS["video_review"]
                reasons.append(
                    QualityReason(
                        code="low_video_bitrate",
                        severity="review",
                        message=f"Video bitrate is low for {resolution_bucket}.",
                    )
                )

        if derived.mb_per_min is not None:
            if derived.mb_per_min < limits["mb_per_min"]["severe_below"]:
                score += WEIGHTS["size_severe"]
                reasons.append(
                    QualityReason(
                        code="low_mb_per_min",
                        severity="severe",
                        message=f"File size is very low for a {resolution_bucket} title.",
                    )
                )
            elif derived.mb_per_min < limits["mb_per_min"]["review_below"]:
                score += WEIGHTS["size_review"]
                reasons.append(
                    QualityReason(
                        code="low_mb_per_min",
                        severity="review",
                        message=f"File size is low for a {resolution_bucket} title.",
                    )
                )

    if facts.audio_bitrate_kbps:
        if facts.audio_bitrate_kbps < 96:
            score += WEIGHTS["audio_severe"]
            reasons.append(
                QualityReason(
                    code="weak_audio_bitrate",
                    severity="severe",
                    message="Audio bitrate is very low.",
                )
            )
        elif facts.audio_bitrate_kbps < 160:
            score += WEIGHTS["audio_review"]
            reasons.append(
                QualityReason(
                    code="weak_audio_bitrate",
                    severity="review",
                    message="Audio bitrate is low.",
                )
            )

    if facts.audio_channels is not None and facts.runtime_seconds and facts.audio_channels <= 2 and facts.runtime_seconds >= 5400:
        score += WEIGHTS["audio_review"]
        reasons.append(
            QualityReason(
                code="stereo_long_feature",
                severity="review",
                message="Long feature has stereo audio only.",
            )
        )

    if resolved_hint and resolution_bucket and resolved_hint != resolution_bucket:
        score += WEIGHTS["resolution_mismatch"]
        reasons.append(
            QualityReason(
                code="resolution_mismatch",
                severity="review",
                message=f"Filename suggests {resolved_hint} but stream is {resolution_bucket}.",
            )
        )

    if is_legacy_codec(facts.video_codec):
        score += WEIGHTS["legacy_codec"]
        reasons.append(
            QualityReason(
                code="legacy_video_codec",
                severity="review",
                message="Codec is associated with older weak encodes.",
            )
        )

    confidence = classify_confidence(normalized_facts, resolution_bucket)
    reasons = dedupe_reasons(reasons)

    if resolution_bucket is None and video_bitrate_kbps is None and derived.mb_per_min is None:
        status = "unscored"
    elif score >= 60:
        status = "severe"
    elif score >= 30:
        status = "review"
    else:
        status = "ok"

    return QualityReview(
        status=status,
        score=score,
        confidence=confidence,
        reasons=reasons,
        facts=normalized_facts,
        derived=derived,
    )


def dedupe_reasons(reasons: list[QualityReason]) -> list[QualityReason]:
    deduped: list[QualityReason] = []
    seen: set[tuple[str, str, str]] = set()
    for reason in reasons:
        key = (reason.code, reason.severity, reason.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reason)
    return deduped
