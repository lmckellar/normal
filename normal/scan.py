from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from mutagen import MutagenError
from mutagen.flac import FLAC, FLACNoHeaderError
from mutagen.id3 import ID3NoHeaderError

from normal.models import AlbumReport, AnalysisReport, TrackReport, WarningItem, build_empty_report


REQUIRED_TAGS = ("artist", "album", "albumartist", "title", "tracknumber", "date", "genre")
OPTIONAL_TAGS = ("discnumber",)
DISC_DIR_PATTERN = re.compile(r"^(cd|disc|disk)\s*-?\s*\d+$", re.IGNORECASE)


@dataclass(slots=True)
class TrackMetadata:
    path: Path
    tags: dict[str, str]
    issues: list[WarningItem]


def discover_flac_files(source_root: Path) -> list[Path]:
    return sorted(path for path in source_root.rglob("*.flac") if path.is_file())


def normalize_tag_value(value: str) -> str:
    return " ".join(value.split())


def read_flac_metadata(path: Path) -> TrackMetadata:
    issues: list[WarningItem] = []
    try:
        audio = FLAC(path)
    except (FLACNoHeaderError, ID3NoHeaderError, MutagenError, OSError) as exc:
        issues.append(
            WarningItem(
                code="flac_read_error",
                message=f"Unable to read FLAC metadata: {exc}",
                path=str(path),
            )
        )
        return TrackMetadata(path=path, tags={}, issues=issues)

    tags: dict[str, str] = {}
    for key in REQUIRED_TAGS:
        values = audio.get(key, [])
        if values:
            tags[key] = normalize_tag_value(str(values[0]))
        else:
            issues.append(
                WarningItem(
                    code="missing_tag",
                    message=f"Missing tag: {key}",
                    path=str(path),
                )
            )

    for key in OPTIONAL_TAGS:
        values = audio.get(key, [])
        if values:
            tags[key] = normalize_tag_value(str(values[0]))

    return TrackMetadata(path=path, tags=tags, issues=issues)


def track_id_for(path: Path, source_root: Path) -> str:
    return str(path.relative_to(source_root))


def album_key_for(tags: dict[str, str], path: Path) -> str:
    return str(infer_album_root(path))


def infer_album_root(path: Path) -> Path:
    parent = path.parent
    if DISC_DIR_PATTERN.match(parent.name):
        return parent.parent
    return parent


def analyze_library(
    source_root: Path,
    read_track: Callable[[Path], TrackMetadata] = read_flac_metadata,
) -> AnalysisReport:
    report = build_empty_report(source_root)
    flac_files = discover_flac_files(source_root)

    if not flac_files:
        report.warnings.append(
            WarningItem(
                code="no_flac_files",
                message="No FLAC files were found under the source directory.",
                path=str(source_root),
            )
        )
        return report

    grouped_tracks: dict[str, list[TrackMetadata]] = defaultdict(list)
    for flac_path in flac_files:
        metadata = read_track(flac_path)
        report.tracks.append(
            TrackReport(
                track_id=track_id_for(flac_path, source_root),
                path=str(flac_path),
                tags=metadata.tags,
                issues=metadata.issues,
            )
        )
        grouped_tracks[album_key_for(metadata.tags, flac_path)].append(metadata)

    for album_tracks in grouped_tracks.values():
        report.albums.append(build_album_report(album_tracks))

    report.albums.sort(key=lambda album: album.album_id)
    return report


def build_album_report(album_tracks: list[TrackMetadata]) -> AlbumReport:
    first_track = album_tracks[0]
    album_root = infer_album_root(first_track.path)
    album_artist_values = {track.tags.get("albumartist") or track.tags.get("artist") for track in album_tracks}
    album_values = {track.tags.get("album") for track in album_tracks}
    artist_values = {track.tags.get("artist") for track in album_tracks if track.tags.get("artist")}

    warnings: list[WarningItem] = []
    if None in album_values:
        warnings.append(
            WarningItem(
                code="album_missing_album_tag",
                message="One or more tracks are missing an album tag.",
                path=str(album_root),
            )
        )
    if len({value for value in album_values if value}) > 1:
        warnings.append(
            WarningItem(
                code="album_conflicting_titles",
                message="Conflicting album titles found within one folder group.",
                path=str(album_root),
            )
        )
    if len({value for value in album_artist_values if value}) > 1:
        warnings.append(
            WarningItem(
                code="album_conflicting_album_artists",
                message="Conflicting album artist values found within one folder group.",
                path=str(album_root),
            )
        )
    if not any(track.tags.get("albumartist") for track in album_tracks) and len(artist_values) > 1:
        warnings.append(
            WarningItem(
                code="album_missing_consistent_albumartist",
                message="Album artist is missing and track artists are not unanimous.",
                path=str(album_root),
            )
        )

    album_artist = first_track.tags.get("albumartist") or first_track.tags.get("artist") or "__missing_album_artist__"
    album = first_track.tags.get("album") or "__missing_album__"
    album_id = f"{album_artist}::{album}"

    return AlbumReport(
        album_id=album_id,
        path=str(album_root),
        track_count=len(album_tracks),
        warnings=warnings,
    )
