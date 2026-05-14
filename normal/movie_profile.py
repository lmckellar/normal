from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
from itertools import chain
import json
import os
from pathlib import Path
import re
from statistics import mean, median
import tempfile
import time
from typing import Any, Callable

from normal.models import WarningItem, utc_now_iso
from normal.movie_junk import detect_movie_junk_document_reasons
from normal.movie_plan import concise_movie_base, parse_movie_name
from normal.movie_scan import (
    MovieScanProgress,
    emit_progress,
    iter_video_files,
    movie_id_for,
    probe_media_facts,
)
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts, classify_resolution


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
    quality_label: str
    quality_rank: int
    percentile: float
    anchor_distance: float | None
    legacy_bitrate_label: str | None = None
    weak_candidate: bool = False
    confidence: str = "high"
    diagnostics: list[DiagnosticFinding] = field(default_factory=list)
    domain_results: list[dict[str, Any]] = field(default_factory=list)
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
    "replacement_candidate": 1,
    "needs_review": 2,
    "meets_minimum": 3,
    "reference": 4,
}

QUALITY_STANCE_RANKS = {
    "standard_definition": 1,
    "library_grade": 2,
    "collector_grade": 3,
    "reference": 4,
}

QUALITY_STANCE_ORDER = [
    "standard_definition",
    "library_grade",
    "collector_grade",
    "reference",
]

DEFAULT_MOVIE_STANDARDS: dict[str, Any] = {
    "video": {
        "1080p": {"minimum_kbps": 2500, "reference_kbps": 16000},
        "2160p": {"minimum_kbps": 6000, "reference_kbps": 24000},
        "720p": {"minimum_kbps": 1800, "reference_kbps": 6000},
        "sd": {"minimum_kbps": 1200, "reference_kbps": 3000},
    },
    "audio": {
        "minimum_channels": 2,
        "minimum_bitrate_kbps": 192,
        "minimum_codecs": ["aac", "ac3", "eac3", "dts", "dtshd", "truehd", "flac", "pcm"],
        "reference_codecs": ["truehd", "dtshd", "flac", "pcm"],
    },
    "subtitle_setup": {"mode": "conservative"},
    "folder_hygiene": {
        "require_normalized_naming": True,
        "junk_sidecar_extensions": [".txt", ".html", ".htm"],
    },
    "replacement_candidate_rules": {
        "quality_profile_floor": "standard_definition",
    },
    "quality_stances": {
        "standard_definition": {
            "display_name": "Standard Definition",
            "summary": "Edge cases and legacy files that are still worth keeping.",
            "video_floor": "minimum",
            "audio_floor": "minimum",
            "audio_codecs": ["aac", "ac3", "eac3", "dts", "dtshd", "truehd", "flac", "pcm"],
            "require_audio_language_hygiene": False,
            "require_subtitle_setup": False,
            "require_folder_hygiene": False,
            "require_lossless_audio": False,
        },
        "library_grade": {
            "display_name": "Library Grade",
            "summary": "Good enough for casual viewing, including compact encode favourites like Tigole.",
            "video_floor": "custom",
            "video_custom": {"1080p": 4500, "2160p": 12000},
            "audio_floor": "custom",
            "audio_channels": 2,
            "audio_bitrate_kbps": 192,
            "audio_codecs": ["aac", "ac3", "eac3", "dts", "dtshd", "truehd", "flac", "pcm"],
            "require_audio_language_hygiene": True,
            "require_subtitle_setup": False,
            "require_folder_hygiene": False,
            "require_lossless_audio": False,
        },
        "collector_grade": {
            "display_name": "Collector Grade",
            "summary": "Solid compact encodes that hold up better on difficult material.",
            "video_floor": "custom",
            "video_custom": {"1080p": 8000, "2160p": 18000},
            "audio_floor": "custom",
            "audio_channels": 6,
            "audio_bitrate_kbps": 384,
            "audio_codecs": ["ac3", "eac3", "dts", "dtshd", "truehd", "flac", "pcm"],
            "require_audio_language_hygiene": True,
            "require_subtitle_setup": True,
            "require_folder_hygiene": False,
            "require_lossless_audio": False,
        },
        "reference": {
            "display_name": "Reference",
            "summary": "Mild to no compression to visual quality with lossless audio.",
            "video_floor": "custom",
            "video_custom": {"1080p": 16000, "2160p": 24000},
            "audio_floor": "custom",
            "audio_channels": 6,
            "audio_bitrate_kbps": 384,
            "audio_codecs": ["truehd", "dtshd", "flac", "pcm"],
            "require_audio_language_hygiene": True,
            "require_subtitle_setup": True,
            "require_folder_hygiene": True,
            "require_lossless_audio": True,
        },
    },
}

MOVIE_STANDARDS_PATH = Path(__file__).resolve().parent.parent / "movie_standards.json"
ENGLISH_AUDIO_LANGUAGES = {"eng", "en", "english"}
ENGLISH_SUBTITLE_LANGUAGES = {"eng", "en", "english"}


class MovieStandardsConflictError(RuntimeError):
    pass


def scan_movie_profiles(
    source_root: Path,
    probe_media: Callable[[Path], MediaFacts] = probe_media_facts,
    progress_callback: Callable[[MovieScanProgress], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> MovieProfileReport:
    report = MovieProfileReport(source_root=str(source_root.resolve()), generated_at=utc_now_iso())
    standards = load_movie_standards()
    cancelled = False
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
    processed = 0
    emit_progress(progress_callback, processed, 0, None, started, "starting")

    for index, movie_path in enumerate(chain([first_movie], movie_files), start=1):
        if should_cancel is not None and should_cancel():
            cancelled = True
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
            processed = index
            emit_progress(progress_callback, processed, 0, movie_path, started, "warning")
            continue

        facts.resolution_bucket = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
        report.movies.append(build_movie_profile_item(source_root, movie_path, facts, standards))
        processed = index
        emit_progress(progress_callback, processed, 0, movie_path, started, "running")

    if (
        should_cancel is not None
        and should_cancel()
        and not cancelled
        and not any(warning.code == "movie_profile_cancelled" for warning in report.warnings)
    ):
        report.warnings.append(
            WarningItem(
                code="movie_profile_cancelled",
                message="Movie profile scan was cancelled before completion.",
                path=str(source_root),
            )
        )

    assign_percentiles(report.movies)
    report.movies.sort(key=lambda item: (total_risk_score(item.profile.diagnostics), item.profile.rank, item.path.lower()), reverse=True)
    emit_progress(progress_callback, processed, processed, None, started, "complete")
    return report


def build_movie_profile_item(
    source_root: Path,
    movie_path: Path,
    facts: MediaFacts,
    standards: dict[str, Any] | None = None,
) -> MovieProfileItem:
    facts.resolution_bucket = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
    active_standards = standards or load_movie_standards()
    legacy_label = classify_profile_label(facts)
    domain_results = evaluate_movie_standards(movie_path, facts, active_standards)
    quality_label = classify_quality_stance(movie_path, facts, domain_results, active_standards)
    weak_candidate = is_replacement_candidate_quality(quality_label, active_standards)
    label = classify_standard_label(domain_results, active_standards, weak_candidate=weak_candidate)
    diagnostics = detect_plex_diagnostics(movie_path, facts)
    diagnostics.extend(domain_results_to_diagnostics(domain_results))
    confidence = "low" if any(result["confidence"] == "low" for result in domain_results) else "high"
    return MovieProfileItem(
        movie_id=movie_id_for(movie_path, source_root),
        path=str(movie_path),
        facts=facts,
        runtime_minutes=round(facts.runtime_seconds / 60, 1) if facts.runtime_seconds else None,
        profile=MovieProfile(
            label=label,
            rank=PROFILE_RANKS[label],
            quality_label=quality_label,
            quality_rank=QUALITY_STANCE_RANKS[quality_label],
            percentile=0.0,
            anchor_distance=compute_anchor_distance(facts),
            legacy_bitrate_label=legacy_label,
            weak_candidate=weak_candidate,
            confidence=confidence,
            diagnostics=diagnostics,
            domain_results=domain_results,
            risk_counts=build_risk_counts(diagnostics),
        ),
    )


def load_movie_standards() -> dict[str, Any]:
    standards = json.loads(json.dumps(DEFAULT_MOVIE_STANDARDS))
    if not MOVIE_STANDARDS_PATH.exists():
        return standards
    try:
        payload = json.loads(MOVIE_STANDARDS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return standards
    if not isinstance(payload, dict):
        return standards
    return deep_merge_dicts(standards, payload)


def movie_standards_revision(standards: dict[str, Any] | None = None) -> str:
    normalized = deep_merge_dicts(DEFAULT_MOVIE_STANDARDS, standards or load_movie_standards())
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save_movie_standards(standards: dict[str, Any]) -> dict[str, Any]:
    normalized = deep_merge_dicts(DEFAULT_MOVIE_STANDARDS, standards)
    payload = json.dumps(normalized, indent=2) + "\n"
    MOVIE_STANDARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=MOVIE_STANDARDS_PATH.parent,
            prefix=f"{MOVIE_STANDARDS_PATH.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temp_path = Path(handle.name)
        temp_path.replace(MOVIE_STANDARDS_PATH)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return normalized


def build_movie_profile_definitions(standards: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    active = standards or load_movie_standards()
    stances = active.get("quality_stances") or {}
    definitions: list[dict[str, Any]] = []
    for label in QUALITY_STANCE_ORDER:
        stance = stances.get(label) or {}
        video_custom = stance.get("video_custom") or {}
        definitions.append(
            {
                "label": label,
                "display_name": str(stance.get("display_name") or human_quality_stance_label(label)),
                "group": "Quality Profile",
                "summary": str(stance.get("summary") or ""),
                "rule_summary": build_quality_stance_rule_summary(label, stance, active),
                "inherits_summary": build_quality_stance_inherits_summary(label, stance),
                "fields": [
                    {
                        "key": "display_name",
                        "label": "Card label",
                        "type": "text",
                        "value": str(stance.get("display_name") or human_quality_stance_label(label)),
                    },
                    {
                        "key": "summary",
                        "label": "Card summary",
                        "type": "text",
                        "value": str(stance.get("summary") or ""),
                    },
                    {
                        "key": "video_1080p_kbps",
                        "label": "1080p video kbps floor",
                        "type": "select",
                        "value": int(resolve_stance_video_floor(label, stance, active, "1080p")),
                        "options": [
                            {"value": 1200, "label": "1,200 kbps — SD minimum"},
                            {"value": 1800, "label": "1,800 kbps — 720p minimum"},
                            {"value": 3000, "label": "3,000 kbps — compact encode"},
                            {"value": 4500, "label": "4,500 kbps — library grade"},
                            {"value": 6000, "label": "6,000 kbps — solid encode"},
                            {"value": 8000, "label": "8,000 kbps — collector grade"},
                            {"value": 12000, "label": "12,000 kbps — high bitrate"},
                            {"value": 16000, "label": "16,000 kbps — reference"},
                            {"value": 20000, "label": "20,000 kbps — near-lossless"},
                            {"value": 25000, "label": "25,000 kbps — remux tier"},
                        ],
                    },
                    {
                        "key": "video_2160p_kbps",
                        "label": "4K video kbps floor",
                        "type": "select",
                        "value": int(resolve_stance_video_floor(label, stance, active, "2160p")),
                        "options": [
                            {"value": 5000, "label": "5,000 kbps — compact 4K"},
                            {"value": 8000, "label": "8,000 kbps — efficient encode"},
                            {"value": 10000, "label": "10,000 kbps — library grade"},
                            {"value": 12000, "label": "12,000 kbps — solid 4K"},
                            {"value": 15000, "label": "15,000 kbps — collector grade"},
                            {"value": 18000, "label": "18,000 kbps — high bitrate"},
                            {"value": 24000, "label": "24,000 kbps — reference"},
                            {"value": 30000, "label": "30,000 kbps — near-lossless"},
                            {"value": 40000, "label": "40,000 kbps — remux tier"},
                            {"value": 50000, "label": "50,000 kbps — full remux"},
                        ],
                    },
                    {
                        "key": "audio_channels",
                        "label": "Minimum main-audio channels",
                        "type": "select",
                        "value": int(resolve_stance_audio_channels(label, stance, active)),
                        "options": [
                            {"value": 1, "label": "1 — Mono"},
                            {"value": 2, "label": "2 — Stereo"},
                            {"value": 6, "label": "6 — 5.1 Surround"},
                            {"value": 8, "label": "8 — 7.1 Surround"},
                        ],
                    },
                    {
                        "key": "audio_channels_vintage_cutoff",
                        "label": "Exempt pre-surround era films from channel minimum",
                        "type": "select",
                        "value": int(stance.get("audio_channels_vintage_cutoff", 0)),
                        "options": [
                            {"value": 0, "label": "Off — apply to all films"},
                            {"value": 1970, "label": "Pre-1970 films exempt"},
                            {"value": 1980, "label": "Pre-1980 films exempt"},
                            {"value": 1985, "label": "Pre-1985 films exempt"},
                            {"value": 1990, "label": "Pre-1990 films exempt"},
                            {"value": 1999, "label": "Pre-1999 films exempt"},
                        ],
                    },
                    {
                        "key": "audio_channels_atmos_cutoff",
                        "label": "Exempt pre-Atmos era films from 8-channel minimum",
                        "type": "select",
                        "value": int(stance.get("audio_channels_atmos_cutoff", 0)),
                        "options": [
                            {"value": 0, "label": "Off — apply 8-channel minimum to all films"},
                            {"value": 2005, "label": "Pre-2005 films exempt"},
                            {"value": 2010, "label": "Pre-2010 films exempt"},
                            {"value": 2015, "label": "Pre-2015 films exempt"},
                        ],
                    },
                    {
                        "key": "audio_bitrate_kbps",
                        "label": "Minimum main-audio kbps",
                        "type": "select",
                        "value": int(resolve_stance_audio_bitrate(label, stance, active)),
                        "options": [
                            {"value": 320, "label": "320 kbps"},
                            {"value": 384, "label": "384 kbps"},
                            {"value": 448, "label": "448 kbps"},
                            {"value": 640, "label": "640 kbps"},
                            {"value": 768, "label": "768 kbps"},
                            {"value": 1024, "label": "1024 kbps"},
                            {"value": 1536, "label": "1536 kbps"},
                        ],
                    },
                    {
                        "key": "require_audio_language_hygiene",
                        "label": "Require sensible default audio language",
                        "type": "toggle",
                        "value": bool(stance.get("require_audio_language_hygiene", False)),
                    },
                    {
                        "key": "require_subtitle_setup",
                        "label": "Require subtitle default hygiene",
                        "type": "toggle",
                        "value": bool(stance.get("require_subtitle_setup", False)),
                    },
                    {
                        "key": "require_folder_hygiene",
                        "label": "Require normalized folder hygiene",
                        "type": "toggle",
                        "value": bool(stance.get("require_folder_hygiene", False)),
                    },
                    {
                        "key": "require_lossless_audio",
                        "label": "Require lossless audio",
                        "type": "toggle",
                        "value": bool(stance.get("require_lossless_audio", False)),
                    },
                ],
            }
        )
    return definitions


def build_replacement_candidate_definition(standards: dict[str, Any] | None = None) -> dict[str, Any]:
    active = standards or load_movie_standards()
    cutoff = replacement_candidate_quality_floor(active)
    stances = active.get("quality_stances") or {}
    display = human_quality_stance_label(cutoff)
    cutoff_stance = stances.get(cutoff) or {}
    if cutoff_stance.get("display_name"):
        display = str(cutoff_stance["display_name"])
    return {
        "label": "replacement_candidate",
        "display_name": "Replacement Candidate",
        "group": "Action Based",
        "summary": "Quality profile at or below the configured cutoff and eligible for delete/replace triage.",
        "rule_summary": f"Current cutoff: {display} and lower.",
        "fields": [
            {
                "key": "quality_profile_floor",
                "label": "Quality profile cutoff",
                "type": "select",
                "value": cutoff,
                "options": [
                    {
                        "value": label,
                        "label": str((stances.get(label) or {}).get("display_name") or human_quality_stance_label(label)),
                    }
                    for label in QUALITY_STANCE_ORDER
                ],
            }
        ],
    }


def update_movie_profile_definition(
    label: str,
    values: dict[str, Any],
    expected_revision: str | None = None,
    standards: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = deep_merge_dicts(DEFAULT_MOVIE_STANDARDS, standards or load_movie_standards())
    if expected_revision and expected_revision != movie_standards_revision(current):
        raise MovieStandardsConflictError("Movie standards changed since this dashboard view loaded. Refresh and retry.")
    active = deep_merge_dicts(DEFAULT_MOVIE_STANDARDS, current)
    if label == "replacement_candidate":
        active.setdefault("replacement_candidate_rules", {})["quality_profile_floor"] = normalize_quality_stance_label(
            values.get("quality_profile_floor"),
            replacement_candidate_quality_floor(active),
        )
        return save_movie_standards(active)
    if label in QUALITY_STANCE_ORDER:
        stance = active.setdefault("quality_stances", {}).setdefault(label, {})
        stance["display_name"] = str(values.get("display_name") or human_quality_stance_label(label)).strip() or human_quality_stance_label(label)
        stance["summary"] = str(values.get("summary") or "").strip()
        stance["video_floor"] = "custom"
        stance["audio_floor"] = "custom"
        stance.setdefault("video_custom", {})
        stance["video_custom"]["1080p"] = normalize_positive_int(
            values.get("video_1080p_kbps"),
            int(resolve_stance_video_floor(label, stance, active, "1080p")),
        )
        stance["video_custom"]["2160p"] = normalize_positive_int(
            values.get("video_2160p_kbps"),
            int(resolve_stance_video_floor(label, stance, active, "2160p")),
        )
        stance["audio_channels"] = normalize_positive_int(
            values.get("audio_channels"),
            int(resolve_stance_audio_channels(label, stance, active)),
        )
        cutoff_raw = values.get("audio_channels_vintage_cutoff")
        stance["audio_channels_vintage_cutoff"] = int(cutoff_raw) if cutoff_raw is not None and str(cutoff_raw).isdigit() else 0
        atmos_raw = values.get("audio_channels_atmos_cutoff")
        stance["audio_channels_atmos_cutoff"] = int(atmos_raw) if atmos_raw is not None and str(atmos_raw).isdigit() else 0
        stance["audio_bitrate_kbps"] = normalize_positive_int(
            values.get("audio_bitrate_kbps"),
            int(resolve_stance_audio_bitrate(label, stance, active)),
        )
        stance["require_audio_language_hygiene"] = bool(values.get("require_audio_language_hygiene", False))
        stance["require_subtitle_setup"] = bool(values.get("require_subtitle_setup", False))
        stance["require_folder_hygiene"] = bool(values.get("require_folder_hygiene", False))
        stance["require_lossless_audio"] = bool(values.get("require_lossless_audio", False))
        return save_movie_standards(active)
    raise ValueError(f"Unsupported movie profile definition: {label}")


def deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge_dicts(current, value)
        else:
            merged[key] = value
    return merged


def normalize_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def normalize_codec_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        items = []
    result: list[str] = []
    for item in items:
        token = str(item).strip().casefold()
        if token and token not in result:
            result.append(token)
    return result or list(default)


def normalize_extension_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, list):
        items = value
    else:
        items = []
    result: list[str] = []
    for item in items:
        token = str(item).strip().casefold()
        if not token:
            continue
        if not token.startswith("."):
            token = "." + token
        if token not in result:
            result.append(token)
    return result or list(DEFAULT_MOVIE_STANDARDS["folder_hygiene"]["junk_sidecar_extensions"])


def normalize_quality_stance_label(value: Any, default: str | None = None) -> str:
    label = str(value or "").strip()
    if label in QUALITY_STANCE_RANKS:
        return label
    return default if default in QUALITY_STANCE_RANKS else QUALITY_STANCE_ORDER[0]


def replacement_candidate_quality_floor(standards: dict[str, Any]) -> str:
    config = standards.get("replacement_candidate_rules") or {}
    return normalize_quality_stance_label(config.get("quality_profile_floor"), QUALITY_STANCE_ORDER[0])


def normalize_subtitle_mode(value: Any) -> str:
    mode = str(value or "").strip().casefold()
    return mode if mode == "conservative" else "conservative"


def human_quality_stance_label(label: str) -> str:
    if label == "standard_definition":
        return "Standard Definition"
    if label == "library_grade":
        return "Library Grade"
    if label == "collector_grade":
        return "Collector Grade"
    if label == "reference":
        return "Reference"
    return label.replace("_", " ").title()


def build_quality_stance_rule_summary(label: str, stance: dict[str, Any], standards: dict[str, Any]) -> str:
    parts = [
        f"1080p >= {resolve_stance_video_floor(label, stance, standards, '1080p')} kbps",
        f"4K >= {resolve_stance_video_floor(label, stance, standards, '2160p')} kbps",
        f"audio >= {resolve_stance_audio_channels(label, stance, standards)} ch / {resolve_stance_audio_bitrate(label, stance, standards)} kbps",
    ]
    if stance.get("require_lossless_audio"):
        parts.append("lossless audio required")
    return "; ".join(parts) + "."


def build_quality_stance_inherits_summary(label: str, stance: dict[str, Any]) -> str:
    if label == "standard_definition":
        return "Inherited default: tolerant keep posture for legacy and edge-case files."
    if label == "library_grade":
        return "Inherited default: casual-viewing baseline with relaxed subtitle and folder hygiene."
    if label == "collector_grade":
        return "Inherited default: stronger encode floor with subtitle hygiene enabled."
    if label == "reference":
        return "Inherited default: reference-grade video floor with lossless audio and tidy packaging."
    return str(stance.get("inherits_summary") or "")


def resolve_stance_video_floor(label: str, stance: dict[str, Any], standards: dict[str, Any], resolution: str) -> int:
    video = standards.get("video") or {}
    default_video = DEFAULT_MOVIE_STANDARDS["video"]
    floor_mode = str(stance.get("video_floor") or "custom")
    if floor_mode == "reference":
        config = (video.get(resolution) or {}) or (default_video.get(resolution) or {})
        return int(config.get("reference_kbps") or 0)
    if floor_mode == "minimum":
        config = (video.get(resolution) or {}) or (default_video.get(resolution) or {})
        return int(config.get("minimum_kbps") or 0)
    custom = stance.get("video_custom") or {}
    value = custom.get(resolution)
    if value is not None:
        return int(value)
    fallback = (DEFAULT_MOVIE_STANDARDS["quality_stances"].get(label) or {}).get("video_custom") or {}
    if resolution in fallback:
        return int(fallback[resolution])
    config = (video.get(resolution) or {}) or (default_video.get(resolution) or {})
    return int(config.get("minimum_kbps") or 0)


def resolve_stance_audio_channels(label: str, stance: dict[str, Any], standards: dict[str, Any]) -> int:
    audio = standards.get("audio") or {}
    if str(stance.get("audio_floor") or "custom") == "reference":
        return int(audio.get("minimum_channels") or DEFAULT_MOVIE_STANDARDS["audio"]["minimum_channels"])
    if stance.get("audio_channels") is not None:
        return int(stance["audio_channels"])
    fallback = DEFAULT_MOVIE_STANDARDS["quality_stances"].get(label) or {}
    if fallback.get("audio_channels") is not None:
        return int(fallback["audio_channels"])
    return int(audio.get("minimum_channels") or DEFAULT_MOVIE_STANDARDS["audio"]["minimum_channels"])


def resolve_stance_audio_bitrate(label: str, stance: dict[str, Any], standards: dict[str, Any]) -> int:
    audio = standards.get("audio") or {}
    if str(stance.get("audio_floor") or "custom") == "reference":
        return int(audio.get("minimum_bitrate_kbps") or DEFAULT_MOVIE_STANDARDS["audio"]["minimum_bitrate_kbps"])
    if stance.get("audio_bitrate_kbps") is not None:
        return int(stance["audio_bitrate_kbps"])
    fallback = DEFAULT_MOVIE_STANDARDS["quality_stances"].get(label) or {}
    if fallback.get("audio_bitrate_kbps") is not None:
        return int(fallback["audio_bitrate_kbps"])
    return int(audio.get("minimum_bitrate_kbps") or DEFAULT_MOVIE_STANDARDS["audio"]["minimum_bitrate_kbps"])


def resolve_stance_audio_codecs(label: str, stance: dict[str, Any], standards: dict[str, Any]) -> list[str]:
    audio = standards.get("audio") or {}
    if str(stance.get("audio_floor") or "custom") == "reference":
        return list(audio.get("reference_codecs") or DEFAULT_MOVIE_STANDARDS["audio"]["reference_codecs"])
    if stance.get("audio_codecs"):
        return [str(codec).casefold() for codec in stance.get("audio_codecs") or []]
    fallback = DEFAULT_MOVIE_STANDARDS["quality_stances"].get(label) or {}
    if fallback.get("audio_codecs"):
        return [str(codec).casefold() for codec in fallback.get("audio_codecs") or []]
    return list(audio.get("minimum_codecs") or DEFAULT_MOVIE_STANDARDS["audio"]["minimum_codecs"])


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


def evaluate_movie_standards(path: Path, facts: MediaFacts, standards: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        evaluate_video_domain(facts, standards),
        evaluate_audio_domain(facts, standards),
        evaluate_audio_language_hygiene_domain(facts),
        evaluate_subtitle_setup_domain(facts, standards),
        evaluate_folder_hygiene_domain(path, facts, standards),
    ]


def evaluate_video_domain(facts: MediaFacts, standards: dict[str, Any]) -> dict[str, Any]:
    resolution = facts.resolution_bucket or classify_resolution(facts.width, facts.height) or "unknown"
    bitrate = facts.video_bitrate_kbps or 0
    config = (standards.get("video") or {}).get(resolution) or {}
    minimum = int(config.get("minimum_kbps") or 0)
    reference = int(config.get("reference_kbps") or 0)
    if not bitrate or not minimum:
        return standard_result("video_minimum", "review_low_confidence", "video_signal_missing", "Video bitrate is missing or incomplete.", "low")
    if bitrate < minimum:
        return standard_result(
            "video_minimum",
            "fail",
            "video_below_minimum",
            f"Video bitrate {bitrate:,} kbps is below the {resolution} minimum of {minimum:,} kbps.",
            "high",
        )
    if reference and bitrate >= reference:
        return standard_result(
            "video_minimum",
            "pass",
            "video_reference",
            f"Video bitrate meets the {resolution} reference floor.",
            "high",
        )
    return standard_result(
        "video_minimum",
        "pass",
        "video_meets_minimum",
        f"Video bitrate meets the {resolution} minimum floor.",
        "high",
    )


def evaluate_audio_domain(facts: MediaFacts, standards: dict[str, Any]) -> dict[str, Any]:
    config = standards.get("audio") or {}
    minimum_channels = int(config.get("minimum_channels") or 0)
    minimum_bitrate = int(config.get("minimum_bitrate_kbps") or 0)
    allowed_codecs = {str(codec).casefold() for codec in config.get("minimum_codecs") or []}
    reference_codecs = {str(codec).casefold() for codec in config.get("reference_codecs") or []}
    codec = (facts.audio_format_family or facts.audio_codec or "").casefold()
    channels = facts.audio_channels or 0
    bitrate = facts.audio_bitrate_kbps or 0

    if not codec and not channels and not bitrate:
        return standard_result("audio_minimum", "review_low_confidence", "audio_signal_missing", "Audio facts are too sparse to verify the minimum standard.", "low")
    if allowed_codecs and codec and codec not in allowed_codecs:
        return standard_result("audio_minimum", "fail", "audio_codec_below_minimum", f"Main audio codec `{codec}` is below the configured minimum standard.", "high")
    if minimum_channels and channels and channels < minimum_channels:
        return standard_result("audio_minimum", "fail", "audio_channels_below_minimum", f"Main audio layout is below the configured minimum of {minimum_channels} channels.", "high")
    if minimum_bitrate and bitrate and bitrate < minimum_bitrate:
        return standard_result("audio_minimum", "fail", "audio_bitrate_below_minimum", f"Main audio bitrate {bitrate:,} kbps is below the configured minimum of {minimum_bitrate:,} kbps.", "high")
    if reference_codecs and codec in reference_codecs and channels >= minimum_channels and bitrate >= minimum_bitrate:
        return standard_result("audio_minimum", "pass", "audio_reference", "Main audio meets the configured reference standard.", "high")
    return standard_result("audio_minimum", "pass", "audio_meets_minimum", "Main audio meets the configured minimum standard.", "high")


def evaluate_audio_language_hygiene_domain(facts: MediaFacts) -> dict[str, Any]:
    default_stream = choose_default_audio_stream(facts.audio_streams)
    if default_stream is None:
        return standard_result("audio_language_hygiene", "review_low_confidence", "audio_default_unknown", "No clear default audio stream was visible.", "low")
    default_language = canonical_audio_language(default_stream.language)
    if default_language in {None, "english"}:
        return standard_result("audio_language_hygiene", "pass", "audio_default_ok", "Default audio language looks sensible.", "high")
    english_streams = [stream for stream in facts.audio_streams if canonical_audio_language(stream.language) == "english"]
    if not english_streams:
        return standard_result("audio_language_hygiene", "review_low_confidence", "audio_default_non_english_no_english_alt", "Default audio is non-English and no English alternate was clearly tagged.", "low")
    return standard_result("audio_language_hygiene", "review_low_confidence", "audio_default_non_english", "Default audio is non-English while an English track is present.", "low")


def evaluate_subtitle_setup_domain(facts: MediaFacts, standards: dict[str, Any]) -> dict[str, Any]:
    mode = str((standards.get("subtitle_setup") or {}).get("mode") or "conservative")
    if mode != "conservative":
        return standard_result("subtitle_setup", "review_low_confidence", "subtitle_policy_unknown", "Subtitle policy is unsupported by the current standards engine.", "low")
    if facts.default_subtitle_streams > 1:
        return standard_result("subtitle_setup", "fail", "multiple_default_subtitles", "Multiple subtitle streams are marked default.", "high")

    default_audio = choose_default_audio_stream(facts.audio_streams)
    default_audio_language = canonical_audio_language(default_audio.language) if default_audio else None
    english_forced = [stream for stream in facts.subtitle_streams if is_english_subtitle(stream) and stream.is_forced]
    default_subtitle = choose_default_subtitle_stream(facts.subtitle_streams) if facts.default_subtitle_streams else None

    if english_forced:
        if default_subtitle is None:
            return standard_result("subtitle_setup", "review_low_confidence", "english_forced_not_default", "English forced subtitles exist but no default subtitle is set.", "low")
        if not (is_english_subtitle(default_subtitle) and default_subtitle.is_forced):
            return standard_result("subtitle_setup", "review_low_confidence", "wrong_default_forced_subtitle", "English forced subtitles exist but the default subtitle is not the forced English track.", "low")
        return standard_result("subtitle_setup", "pass", "english_forced_defaulted", "English forced subtitles are present and defaulted.", "high")

    if default_audio_language not in {None, "english"}:
        if default_subtitle is None:
            return standard_result("subtitle_setup", "review_low_confidence", "missing_default_english_subtitle", "Default audio is non-English and no default subtitle was visible.", "low")
        if not is_english_subtitle(default_subtitle):
            return standard_result("subtitle_setup", "review_low_confidence", "wrong_default_subtitle_language", "Default audio is non-English but the default subtitle is not English.", "low")
        return standard_result("subtitle_setup", "pass", "english_subtitle_defaulted", "English subtitles are defaulted for non-English main audio.", "high")

    if default_subtitle is not None:
        return standard_result("subtitle_setup", "review_low_confidence", "unnecessary_default_subtitle", "Default subtitles are set even though default audio is English.", "low")
    return standard_result("subtitle_setup", "pass", "subtitle_defaults_ok", "Subtitle defaults look tidy.", "high")


def evaluate_folder_hygiene_domain(path: Path, facts: MediaFacts, standards: dict[str, Any]) -> dict[str, Any]:
    config = standards.get("folder_hygiene") or {}
    if config.get("require_normalized_naming", True) and not path_matches_normalized_shape(path):
        return standard_result("folder_hygiene", "review_low_confidence", "path_not_normalized", "Path does not match the normalized movie naming shape.", "low")
    junk_extensions = {str(value).casefold() for value in config.get("junk_sidecar_extensions") or []}
    try:
        siblings = list(path.parent.iterdir())
    except OSError:
        siblings = []
    for sibling in siblings:
        if sibling == path or not sibling.is_file():
            continue
        if sibling.suffix.casefold() in junk_extensions and detect_movie_junk_document_reasons(sibling):
            return standard_result("folder_hygiene", "review_low_confidence", "promo_sidecar_present", "Folder contains a likely promo or spam sidecar file.", "low")
    return standard_result("folder_hygiene", "pass", "folder_hygiene_ok", "Folder looks tidy enough for the current standard.", "high")


def path_matches_normalized_shape(path: Path) -> bool:
    parsed = parse_movie_name(path)
    if parsed.title is None or parsed.year is None:
        return False
    concise_base = concise_movie_base(parsed)
    if path.stem != concise_base:
        return False
    return path.parent.name == concise_base


def standard_result(domain: str, status: str, code: str, summary: str, confidence: str) -> dict[str, Any]:
    return {
        "domain": domain,
        "status": status,
        "code": code,
        "summary": summary,
        "confidence": confidence,
    }


def classify_quality_stance(
    path: Path,
    facts: MediaFacts,
    domain_results: list[dict[str, Any]],
    standards: dict[str, Any],
) -> str:
    stances = standards.get("quality_stances") or {}
    for label in reversed(QUALITY_STANCE_ORDER):
        stance = stances.get(label) or {}
        if movie_matches_quality_stance(label, stance, path, facts, domain_results, standards):
            return label
    return "standard_definition"


def movie_matches_quality_stance(
    label: str,
    stance: dict[str, Any],
    path: Path,
    facts: MediaFacts,
    domain_results: list[dict[str, Any]],
    standards: dict[str, Any],
) -> bool:
    resolution = facts.resolution_bucket or classify_resolution(facts.width, facts.height) or "unknown"
    required_video = resolve_stance_video_floor(label, stance, standards, resolution)
    if required_video and (facts.video_bitrate_kbps or 0) < required_video:
        return False

    codec = (facts.audio_format_family or facts.audio_codec or "").casefold()
    channels = facts.audio_channels or 0
    bitrate = facts.audio_bitrate_kbps or 0
    required_channels = resolve_stance_audio_channels(label, stance, standards)
    if required_channels and channels < required_channels:
        vintage_cutoff = int(stance.get("audio_channels_vintage_cutoff") or 0)
        atmos_cutoff = int(stance.get("audio_channels_atmos_cutoff") or 0)
        exempt = False
        if vintage_cutoff or atmos_cutoff:
            parsed_identity = parse_movie_name(path)
            year = parsed_identity.year
            if vintage_cutoff and year and year < vintage_cutoff:
                exempt = True
            if not exempt and atmos_cutoff and required_channels > 6 and channels >= 6 and year and year < atmos_cutoff:
                exempt = True
        if not exempt:
            return False
    if resolve_stance_audio_bitrate(label, stance, standards) and bitrate < resolve_stance_audio_bitrate(label, stance, standards):
        return False
    if stance.get("require_lossless_audio") and codec not in {"truehd", "dtshd", "flac", "pcm", "pcm_s16le", "pcm_s24le"}:
        return False

    if stance.get("require_audio_language_hygiene") and not domain_passed(domain_results, "audio_language_hygiene"):
        return False
    if stance.get("require_subtitle_setup") and not domain_passed(domain_results, "subtitle_setup"):
        return False
    if stance.get("require_folder_hygiene") and not domain_passed(domain_results, "folder_hygiene"):
        return False

    return True


def domain_passed(domain_results: list[dict[str, Any]], domain: str) -> bool:
    return any(result["domain"] == domain and result["status"] == "pass" for result in domain_results)


def classify_standard_label(
    domain_results: list[dict[str, Any]],
    standards: dict[str, Any],
    weak_candidate: bool = False,
) -> str:
    if weak_candidate:
        return "replacement_candidate"
    statuses = {result["status"] for result in domain_results}
    if "fail" in statuses or "review_low_confidence" in statuses:
        return "needs_review"
    if is_reference_standard(domain_results):
        return "reference"
    return "meets_minimum"


def is_replacement_candidate_quality(quality_label: str, standards: dict[str, Any]) -> bool:
    cutoff = replacement_candidate_quality_floor(standards)
    return QUALITY_STANCE_RANKS.get(quality_label, 99) <= QUALITY_STANCE_RANKS.get(cutoff, QUALITY_STANCE_RANKS[QUALITY_STANCE_ORDER[0]])


def is_reference_standard(domain_results: list[dict[str, Any]]) -> bool:
    return any(result["code"] == "video_reference" for result in domain_results) and any(
        result["code"] == "audio_reference" for result in domain_results
    )


def domain_results_to_diagnostics(domain_results: list[dict[str, Any]]) -> list[DiagnosticFinding]:
    diagnostics: list[DiagnosticFinding] = []
    for result in domain_results:
        if result["status"] == "pass":
            continue
        severity = "review" if result["status"] == "review_low_confidence" else "severe"
        category = "standards_review" if severity == "review" else "standards_failure"
        diagnostics.append(
            DiagnosticFinding(
                code=result["code"],
                severity=severity,
                category=category,
                summary=result["summary"],
                remedy="Review the title against the configured movie standards.",
            )
        )
    return diagnostics


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


def choose_default_subtitle_stream(streams: list[SubtitleStreamFacts]) -> SubtitleStreamFacts | None:
    defaults = [stream for stream in streams if stream.is_default]
    if defaults:
        return defaults[0]
    if streams:
        return streams[0]
    return None


def is_english_subtitle(stream: SubtitleStreamFacts | None) -> bool:
    if stream is None:
        return False
    language = (stream.language or "").casefold()
    return language in ENGLISH_SUBTITLE_LANGUAGES


def choose_best_english_subtitle_stream(
    streams: list[SubtitleStreamFacts],
    *,
    forced_only: bool = False,
) -> SubtitleStreamFacts | None:
    matching = [stream for stream in streams if is_english_subtitle(stream) and (stream.is_forced or not forced_only)]
    if not matching:
        return None
    current_default = choose_default_subtitle_stream(streams)
    if current_default in matching:
        return current_default
    return matching[0]


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
    return build_histogram_payload_from_items(report.source_root, report.generated_at, report.movies)


def build_histogram_payload_from_items(source_root: str, generated_at: str, movies: list[Any]) -> dict[str, Any]:
    video_bitrates = [bitrate for item in movies if (bitrate := item_fact_value(item, "video_bitrate_kbps"))]
    audio_bitrates = [bitrate for item in movies if (bitrate := item_fact_value(item, "audio_bitrate_kbps"))]
    profile_counts: dict[str, int] = {}
    quality_profile_counts: dict[str, int] = {}
    resolution_counts: dict[str, int] = {}
    risk_counts: dict[str, int] = {}
    for item in movies:
        profile_label = item_profile_value(item, "label") or "unknown"
        quality_label = item_profile_value(item, "quality_label") or "unknown"
        profile_counts[profile_label] = profile_counts.get(profile_label, 0) + 1
        quality_profile_counts[quality_label] = quality_profile_counts.get(quality_label, 0) + 1
        resolution = item_fact_value(item, "resolution_bucket") or "unknown"
        resolution_counts[resolution] = resolution_counts.get(resolution, 0) + 1
        risk_values = item_profile_value(item, "risk_counts") or {}
        if isinstance(risk_values, dict):
            for category, count in risk_values.items():
                risk_counts[str(category)] = risk_counts.get(str(category), 0) + int(count or 0)

    total_size_bytes = sum(value for item in movies if (value := item_fact_value(item, "file_size_bytes")))
    total_runtime_minutes = round(sum(value for item in movies if (value := item_value(item, "runtime_minutes"))), 1)

    return {
        "source_root": source_root,
        "generated_at": generated_at,
        "movie_count": len(movies),
        "total_size_bytes": total_size_bytes,
        "total_runtime_minutes": total_runtime_minutes,
        "video_bitrate_kbps": summarize_distribution(video_bitrates),
        "audio_bitrate_kbps": summarize_distribution(audio_bitrates, bin_width=150),
        "profile_counts": profile_counts,
        "quality_profile_counts": quality_profile_counts,
        "resolution_counts": resolution_counts,
        "risk_counts": risk_counts,
        "anchor_reference": {"1080p_uhd_kbps": ANCHOR_KBPS["1080p"]},
    }


def item_value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def item_fact_value(item: Any, key: str) -> Any:
    facts = item_value(item, "facts")
    if isinstance(facts, dict):
        return facts.get(key)
    return getattr(facts, key, None)


def item_profile_value(item: Any, key: str) -> Any:
    profile = item_value(item, "profile")
    if isinstance(profile, dict):
        return profile.get(key)
    return getattr(profile, key, None)


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
