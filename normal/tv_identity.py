from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

from normal.movie_naming import normalize_display_title, strip_leading_site_credit


MULTI_EPISODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})\s*E(?P<first>\d{1,3})\s*-\s*E?(?P<last>\d{1,3})(?!\d)",
    re.IGNORECASE,
)
SEASON_EPISODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})E(?P<first>\d{1,3})(?!\d)",
    re.IGNORECASE,
)
LOOSE_SEASON_EPISODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})\s*[-.\s]\s*E(?P<first>\d{1,3})(?!\d)",
    re.IGNORECASE,
)
X_SEASON_EPISODE_PATTERN = re.compile(
    r"(?<!\d)(?P<season>\d{1,2})x(?P<first>\d{1,3})(?!\d)",
    re.IGNORECASE,
)
OF_TOTAL_PATTERN = re.compile(
    r"(?<!\d)(?P<first>\d{1,2})\s+of\s+(?P<total>\d{1,2})(?!\d)",
    re.IGNORECASE,
)
ABSOLUTE_EPISODE_PATTERN = re.compile(
    r"(?:\s|_)-(?:\s|_)*0*(?P<absolute>\d{1,3})(?!\d)",
    re.IGNORECASE,
)
FOLDER_SEASON_PATTERN = re.compile(
    r"(?:^|[\s._-])(?:season|s)\s*0*(?P<season>\d{1,2})(?:$|[\s._-])",
    re.IGNORECASE,
)
CRC32_PATTERN = re.compile(r"\[[0-9A-Fa-f]{8}\]")
BRACKET_TAG_PATTERN = re.compile(r"\[[^\]]+\]")
YEAR_SPAN_PATTERN = re.compile(r"\((?:19|20)\d{2}\s*-\s*(?:19|20)\d{2}\)")
COLLECTION_NOISE_PATTERN = re.compile(
    r"\b(?:the\s+)?(?:complete\s+)?(?:collection|series|seasons?\s+\d+(?:\s*-\s*\d+)?)\b",
    re.IGNORECASE,
)
TECH_TAIL_PATTERN = re.compile(
    r"(?:^|[\s._-])(?:"
    r"\d{3,4}p|2160|1080|720|480|"
    r"bluray|blu-ray|bdrip|brrip|webrip|web-dl|webdl|hdtv|dvdrip|remux|"
    r"x26[45]|h[._-]?26[45]|hevc|av1|10bit|8bit|hdr10?|sdr|"
    r"aac|ac3|eac3|ddp|dts(?:-hd)?|truehd|flac|atmos|multi|dual[\s._-]?audio"
    r")\b.*$",
    re.IGNORECASE,
)
RELEASE_GROUP_PATTERN = re.compile(r"(?<!\s)-[A-Za-z0-9][A-Za-z0-9-]{1,20}$")
SPECIAL_MARKERS = {"special", "specials", "ova", "ovas", "oav", "oavs", "sp", "extras", "extra", "bonus", "featurette"}


@dataclass(slots=True)
class TvIdentity:
    series: str | None
    season: int | None
    episode_first: int | None
    episode_last: int | None = None
    absolute_episode: int | None = None
    season_length: int | None = None
    episode_title: str | None = None
    numbering: str = ""
    confidence: str = "review"
    warnings: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    series_source: str = ""
    season_source: str = ""
    parse_source_path: str = ""


def parse_tv_identity(path: Path, source_root: Path | None = None) -> TvIdentity:
    stem = cosmetic_text(path.stem)
    numbering, match = match_numbering(stem)
    if match is None:
        series = series_from_ancestors(path, source_root=source_root)
        reason_codes = ["tv_numbering_unrecognized"]
        warnings = ["No supported TV episode numbering was found."]
        if has_special_routing_marker(path, source_root=source_root):
            reason_codes.append("tv_special_content_review")
            warnings.append("Special, OVA, extra, or embedded movie content requires review.")
        return TvIdentity(
            series=series,
            season=None,
            episode_first=None,
            confidence="review",
            warnings=warnings,
            reason_codes=reason_codes,
            series_source="folder" if series else "",
            parse_source_path=str(path),
        )

    series, series_source = resolve_series(path, stem[: match.start()], source_root=source_root)
    episode_title = clean_episode_title(stem[match.end() :])
    season: int | None = None
    episode_first: int | None = None
    episode_last: int | None = None
    absolute_episode: int | None = None
    season_length: int | None = None
    season_source = ""
    reason_codes: list[str] = []
    warnings: list[str] = []

    if numbering in {"span", "sxe", "loose_sxe", "x"}:
        season = int(match.group("season"))
        episode_first = int(match.group("first"))
        episode_last = int(match.group("last")) if numbering == "span" else None
        season_source = "file"
    elif numbering == "of_total":
        season = 1
        episode_first = int(match.group("first"))
        season_length = int(match.group("total"))
        season_source = "n_of_m"
    else:
        absolute_episode = int(match.group("absolute"))
        folder_season = season_from_ancestors(path, source_root=source_root)
        if folder_season is not None:
            season = folder_season
            episode_first = absolute_episode
            season_source = "folder"
            reason_codes.append("tv_absolute_converted_from_folder_season")
        else:
            reason_codes.append("anime_absolute_numbering_risk")

    if not series:
        warnings.append("Series name could not be resolved from the filename or parent folders.")
        reason_codes.append("tv_series_unresolved")

    invalid_numbering = (
        episode_first == 0
        or episode_last is not None and episode_last < (episode_first or 0)
        or season_length is not None and (episode_first or 0) > season_length
    )
    if invalid_numbering:
        warnings.append("Episode numbering is internally inconsistent.")
        reason_codes.append("tv_numbering_ambiguous")

    if season == 0 or has_special_routing_marker(path, source_root=source_root):
        warnings.append("Special, OVA, extra, or embedded movie content requires review.")
        reason_codes.append("tv_special_content_review")

    confidence = (
        "safe"
        if series and not {"tv_special_content_review", "tv_numbering_ambiguous"} & set(reason_codes)
        else "review"
    )
    return TvIdentity(
        series=series,
        season=season,
        episode_first=episode_first,
        episode_last=episode_last,
        absolute_episode=absolute_episode,
        season_length=season_length,
        episode_title=episode_title,
        numbering=numbering,
        confidence=confidence,
        warnings=warnings,
        reason_codes=reason_codes,
        series_source=series_source,
        season_source=season_source,
        parse_source_path=str(path),
    )


def match_numbering(value: str) -> tuple[str, re.Match[str] | None]:
    for name, pattern in (
        ("span", MULTI_EPISODE_PATTERN),
        ("sxe", SEASON_EPISODE_PATTERN),
        ("loose_sxe", LOOSE_SEASON_EPISODE_PATTERN),
        ("x", X_SEASON_EPISODE_PATTERN),
        ("of_total", OF_TOTAL_PATTERN),
        ("absolute", ABSOLUTE_EPISODE_PATTERN),
    ):
        match = pattern.search(value)
        if match is not None:
            return name, match
    return "", None


def cosmetic_text(value: str) -> str:
    cleaned = strip_leading_site_credit(value)
    cleaned = CRC32_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def resolve_series(path: Path, prefix: str, *, source_root: Path | None = None) -> tuple[str | None, str]:
    cleaned_prefix = clean_series_name(prefix)
    if cleaned_prefix:
        return cleaned_prefix, "file"
    folder_series = series_from_ancestors(path, source_root=source_root)
    return folder_series, "folder" if folder_series else ""


def series_from_ancestors(path: Path, *, source_root: Path | None = None) -> str | None:
    resolved_root = source_root.resolve() if source_root is not None else None
    for parent in path.parents:
        if resolved_root is not None and parent.resolve() == resolved_root:
            break
        name = parent.name
        if not name:
            continue
        if FOLDER_SEASON_PATTERN.search(cosmetic_text(name)) and not clean_series_name(name):
            continue
        cleaned = clean_series_name(name)
        if cleaned and cleaned.casefold() not in {"tv", "tv shows", "anime", "shows", "season", "movies"}:
            return cleaned
    return None


def season_from_ancestors(path: Path, *, source_root: Path | None = None) -> int | None:
    resolved_root = source_root.resolve() if source_root is not None else None
    for parent in path.parents:
        if resolved_root is not None and parent.resolve() == resolved_root:
            break
        match = FOLDER_SEASON_PATTERN.search(cosmetic_text(parent.name))
        if match is not None:
            return int(match.group("season"))
    return None


def clean_series_name(value: str) -> str | None:
    cleaned = cosmetic_text(value)
    cleaned = BRACKET_TAG_PATTERN.sub(" ", cleaned)
    cleaned = YEAR_SPAN_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"\((?:19|20)\d{2}\)", " ", cleaned)
    cleaned = FOLDER_SEASON_PATTERN.sub(" ", cleaned)
    cleaned = COLLECTION_NOISE_PATTERN.sub(" ", cleaned)
    cleaned = TECH_TAIL_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"^[\s.-]+|[\s.-]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or not re.search(r"[A-Za-z]", cleaned):
        return None
    return normalize_display_title(cleaned)


def clean_episode_title(value: str) -> str | None:
    cleaned = cosmetic_text(value)
    cleaned = re.sub(r"^[\s.-]+", "", cleaned)
    cleaned = CRC32_PATTERN.sub(" ", cleaned)
    cleaned = BRACKET_TAG_PATTERN.sub(" ", cleaned)
    cleaned = TECH_TAIL_PATTERN.sub(" ", cleaned)
    cleaned = RELEASE_GROUP_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"[\s.-]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or not re.search(r"[A-Za-z0-9]", cleaned):
        return None
    return normalize_display_title(cleaned)


def has_special_routing_marker(path: Path, *, source_root: Path | None = None) -> bool:
    parts = path.parts
    if source_root is not None:
        try:
            parts = path.relative_to(source_root).parts
        except ValueError:
            pass
    for part in parts:
        words = {word.casefold() for word in re.findall(r"[A-Za-z]+", part)}
        if words & SPECIAL_MARKERS:
            return True
        if part.casefold() in {"movie", "movies"}:
            return True
    return False
