from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from mutagen import File as MutagenFile
from mutagen import MutagenError

from normal.models import WarningItem, utc_now_iso
from normal.scan import infer_album_root, normalize_tag_value


SUPPORTED_EXTENSIONS = {".flac", ".mp3"}
MP3_HIGH_QUALITY_FLOOR_KBPS = 256


@dataclass(slots=True)
class MusicFacts:
    format: str
    sample_rate_hz: int | None = None
    bits_per_sample: int | None = None
    bitrate_kbps: int | None = None
    file_size_bytes: int | None = None
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None


@dataclass(slots=True)
class MusicProfile:
    label: str
    rank: int


@dataclass(slots=True)
class MusicProfileItem:
    track_id: str
    path: str
    facts: MusicFacts
    profile: MusicProfile


@dataclass(slots=True)
class MusicProfileReport:
    source_root: str
    generated_at: str
    tracks: list[MusicProfileItem] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILE_RANKS = {
    "mp3_trash": 1,
    "mp3_high_quality": 2,
    "flac_other": 3,
    "flac_44_1": 4,
    "flac_16_44_1": 5,
    "flac_24_44_1": 6,
    "flac_48": 7,
    "flac_16_48": 8,
    "flac_24_48": 9,
    "flac_88_2": 10,
    "flac_16_88_2": 11,
    "flac_24_88_2": 12,
    "flac_96": 13,
    "flac_16_96": 14,
    "flac_24_96": 15,
    "flac_176_4": 16,
    "flac_16_176_4": 17,
    "flac_24_176_4": 18,
    "flac_192": 19,
    "flac_16_192": 20,
    "flac_24_192": 21,
    "unknown_unreadable": 99,
}


def discover_music_files(source_root: Path) -> list[Path]:
    return sorted(path for path in source_root.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)


def scan_music_profiles(
    source_root: Path,
    read_track: Callable[[Path], MusicFacts] | None = None,
) -> MusicProfileReport:
    if read_track is None:
        read_track = read_music_facts
    report = MusicProfileReport(source_root=str(source_root.resolve()), generated_at=utc_now_iso())
    music_files = discover_music_files(source_root)
    if not music_files:
        report.warnings.append(
            WarningItem(
                code="no_music_files",
                message="No supported music files were found under the source directory.",
                path=str(source_root),
            )
        )
        return report

    for music_path in music_files:
        try:
            facts = read_track(music_path)
        except Exception as exc:
            facts = MusicFacts(format="unknown", file_size_bytes=file_size(music_path))
            report.warnings.append(
                WarningItem(
                    code="music_profile_read_error",
                    message=f"Unable to read music metadata: {exc}",
                    path=str(music_path),
                )
            )
        label = classify_music_profile(facts)
        report.tracks.append(
            MusicProfileItem(
                track_id=str(music_path.relative_to(source_root)),
                path=str(music_path),
                facts=facts,
                profile=MusicProfile(label=label, rank=PROFILE_RANKS.get(label, 98)),
            )
        )

    report.tracks.sort(key=lambda item: (item.profile.rank, item.path.lower()))
    return report


def read_music_facts(path: Path) -> MusicFacts:
    try:
        audio = MutagenFile(path)
    except (MutagenError, OSError) as exc:
        raise RuntimeError(exc) from exc
    if audio is None:
        raise RuntimeError("unsupported or unreadable music file")

    info = getattr(audio, "info", None)
    bitrate = getattr(info, "bitrate", None)
    bitrate_kbps = round(bitrate / 1000) if bitrate else None
    facts = MusicFacts(
        format=path.suffix.lower().lstrip("."),
        sample_rate_hz=getattr(info, "sample_rate", None),
        bits_per_sample=getattr(info, "bits_per_sample", None),
        bitrate_kbps=bitrate_kbps,
        file_size_bytes=file_size(path),
    )
    tags = getattr(audio, "tags", None)
    if tags is not None:
        facts.artist = first_tag_value(tags, ("artist", "TPE1"))
        facts.album_artist = first_tag_value(tags, ("albumartist", "album artist", "TPE2"))
        facts.album = first_tag_value(tags, ("album", "TALB"))
    return facts


def first_tag_value(tags: Any, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        try:
            value = tags.get(key)
        except AttributeError:
            value = None
        if not value:
            continue
        if isinstance(value, list):
            value = value[0] if value else None
        if hasattr(value, "text"):
            value = value.text[0] if value.text else None
        if value is not None:
            return normalize_tag_value(str(value))
    return None


def classify_music_profile(facts: MusicFacts) -> str:
    format_name = facts.format.lower()
    if format_name == "mp3":
        if facts.bitrate_kbps and facts.bitrate_kbps > MP3_HIGH_QUALITY_FLOOR_KBPS:
            return "mp3_high_quality"
        return "mp3_trash"
    if format_name == "flac":
        sample_rate_label = profile_sample_rate_token(facts.sample_rate_hz)
        if sample_rate_label is None:
            return "flac_other"
        bit_depth = facts.bits_per_sample
        if bit_depth in {16, 24}:
            return f"flac_{bit_depth}_{sample_rate_label}"
        return f"flac_{sample_rate_label}"
    return "unknown_unreadable"


def profile_sample_rate_token(sample_rate_hz: int | None) -> str | None:
    if sample_rate_hz == 44100:
        return "44_1"
    if sample_rate_hz == 48000:
        return "48"
    if sample_rate_hz == 88200:
        return "88_2"
    if sample_rate_hz == 96000:
        return "96"
    if sample_rate_hz == 176400:
        return "176_4"
    if sample_rate_hz == 192000:
        return "192"
    return None


def build_music_histogram_payload(report: MusicProfileReport) -> dict[str, Any]:
    profile_counts = Counter(item.profile.label for item in report.tracks)
    format_counts = Counter(item.facts.format.lower() or "unknown" for item in report.tracks)
    sample_rate_counts = Counter(sample_rate_label(item.facts.sample_rate_hz) for item in report.tracks)
    album_keys = {album_key(item) for item in report.tracks if album_key(item)}
    artist_keys = {artist_key(item) for item in report.tracks if artist_key(item)}
    total_size = sum(item.facts.file_size_bytes or 0 for item in report.tracks)
    return {
        "track_count": len(report.tracks),
        "album_count": len(album_keys),
        "artist_count": len(artist_keys),
        "total_size_bytes": total_size,
        "profile_counts": dict(profile_counts),
        "format_counts": dict(format_counts),
        "sample_rate_counts": dict(sample_rate_counts),
        "warning_count": len(report.warnings),
    }


def album_key(item: MusicProfileItem) -> str | None:
    if item.facts.album_artist or item.facts.artist or item.facts.album:
        return f"{item.facts.album_artist or item.facts.artist or ''}::{item.facts.album or ''}"
    return str(infer_album_root(Path(item.path)))


def artist_key(item: MusicProfileItem) -> str | None:
    return item.facts.album_artist or item.facts.artist


def sample_rate_label(sample_rate_hz: int | None) -> str:
    if sample_rate_hz is None:
        return "unknown"
    if sample_rate_hz == 44100:
        return "44.1 kHz"
    return f"{sample_rate_hz / 1000:g} kHz"


def file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None
