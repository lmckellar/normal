from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from normal.models import ChangePlan, ProposedChange, WarningItem, build_empty_plan
from normal.movie_identity import ParsedMovieIdentity, parse_movie_identity
from normal.movie_scan import VIDEO_EXTENSIONS, discover_video_files


MOVIE_NAMING_STYLES = ("concise", "verbose")
DEFAULT_MOVIE_NAMING_STYLE = "concise"
YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|2100)(?!\d)")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
RELEASE_GROUP_SUFFIX_PATTERN = re.compile(r"-(?P<group>[A-Za-z0-9]{2,12})$")
BRACKET_CONTENT_PATTERN = re.compile(r"\[(?P<content>[^\]]+)\]")
LEADING_SITE_CREDIT_PATTERNS = (
    re.compile(r"^\s*www[._\s-]+[A-Za-z0-9]+[._\s-]+(?:org|com|net)\s*(?:[-:]+)?\s*", re.IGNORECASE),
    re.compile(r"^\s*www\.[A-Za-z0-9.-]+\s*(?:[-:]+)?\s*", re.IGNORECASE),
)
CANONICAL_TOKEN_MAP = {
    "bluray": "BluRay",
    "blauray": "BluRay",
    "blu-ray": "BluRay",
    "bdrip": "BDRip",
    "brrip": "BRRip",
    "web": "WEB",
    "webrip": "WEBRip",
    "webdl": "WEB-DL",
    "web-dl": "WEB-DL",
    "dvdrip": "DVDRip",
    "dvd": "DVD",
    "remux": "Remux",
    "uhd": "UHD",
    "hdr": "HDR",
    "hdr10": "HDR10",
    "sdr": "SDR",
    "x264": "x264",
    "x265": "x265",
    "h264": "H.264",
    "h265": "H.265",
    "hevc": "HEVC",
    "av1": "AV1",
    "aac": "AAC",
    "ac3": "AC3",
    "eac3": "EAC3",
    "ddp": "DDP",
    "dts": "DTS",
    "dtshd": "DTS-HD",
    "truehd": "TrueHD",
    "atmos": "Atmos",
    "multisub": "MULTISUB",
    "remastered": "Remastered",
    "commentary": "Commentary",
    "multi": "MULTI",
}
TITLE_BOUNDARY_TOKENS = {
    "1080",
    "720",
    "480",
    "2160p",
    "1080p",
    "720p",
    "480p",
    "h",
    "h264",
    "h265",
    "x264",
    "x265",
    "bluray",
    "webrip",
    "webdl",
    "multi",
}
SKIP_TOKENS = {"sample"}
SAFE_DELETE_ARTIFACT_EXTENSIONS = {".nfo", ".ds_store"}
SAFE_DELETE_ARTIFACT_NAMES = {".ds_store"}
PACKAGE_FOLDER_MARKERS = {
    "collection",
    "duology",
    "pack",
    "saga",
    "series",
    "trilogy",
}
VERBOSE_KEEP_TOKENS = {
    "Extended",
    "Final Cut",
    "Director's Cut",
    "Open Matte",
    "Remastered",
    "Unrated",
    "BluRay",
    "BDRip",
    "BRRip",
    "DVD",
    "DVDRip",
    "HDR",
    "HDR10",
    "HEVC",
    "H.264",
    "H.265",
    "Remux",
    "SDR",
    "UHD",
    "WEB",
    "WEB-DL",
    "WEBRip",
    "x264",
    "x265",
}
VERBOSE_DROP_TOKENS = {
    "AAC",
    "AC3",
    "Atmos",
    "Commentary",
    "DDP",
    "DTS",
    "DTS-HD",
    "EAC3",
    "MULTI",
    "MULTISUB",
    "TrueHD",
}
LANGUAGE_TOKEN_PATTERN = re.compile(
    r"(?i)(?:"
    r"eng|english|fre|french|ger|german|ita|italian|spa|spanish|rus|russian|"
    r"jpn|japanese|hin|hindi|ukr|ukrainian|telugu|korean|portuguese|mandarin|"
    r"chinese|persian"
    r"|[2-9](?:rus|eng|fre|ger|ita|spa|jpn|hin|ukr)"
    r"|multi(?:lang|sub)?"
    r")"
)
UPLOADER_TOKEN_PATTERN = re.compile(r"(?i)(?:gerald99|mkvonly|moviesbyrizzo|anoxmous|hon3y|gprs?|etrg|evo|nvee|shiv|tigo?le)")
COMPACT_TECH_MARKERS = (
    "2160p",
    "1080p",
    "720p",
    "480p",
    "bluray",
    "webrip",
    "webdl",
    "bdrip",
    "brrip",
    "dvdrip",
    "x265",
    "x264",
    "h265",
    "h264",
    "hevc",
    "10bit",
    "8bit",
    "hdr10",
    "hdr",
    "sdr",
    "multisub",
    "eng",
    "ita",
    "v2",
)
COMPACT_TITLE_WORDS = {
    "A": "A",
    "AN": "An",
    "THE": "The",
    "AND": "And",
    "OF": "Of",
    "SPACE": "Space",
    "ODYSSEY": "Odyssey",
}

ParsedMovieName = ParsedMovieIdentity


@dataclass(slots=True)
class PlannedMovieFile:
    folder_path: Path
    movie_path: Path
    loose_root_file: bool
    parsed: ParsedMovieName


def build_movie_plan(source_root: Path, naming_style: str = DEFAULT_MOVIE_NAMING_STYLE) -> ChangePlan:
    naming_style = normalize_movie_naming_style(naming_style)
    plan = build_empty_plan(source_root)
    movie_files = discover_video_files(source_root)

    if not movie_files:
        plan.warnings.append(
            WarningItem(
                code="no_video_files",
                message="No supported video files were found under the source directory.",
                path=str(source_root),
            )
        )
        for artifact_change in plan_movie_artifact_folder_cleanup(source_root, movie_files):
            plan.proposed_changes.append(artifact_change)
        for junk_change in plan_root_junk_file_cleanup(source_root):
            plan.proposed_changes.append(junk_change)
        return plan

    files_by_folder: dict[Path, list[Path]] = defaultdict(list)
    for movie_path in movie_files:
        files_by_folder[movie_path.parent].append(movie_path)

    planned_files: list[PlannedMovieFile] = []
    for folder_path, folder_files in sorted(files_by_folder.items()):
        if folder_path.resolve() == source_root.resolve():
            for movie_path in sorted(folder_files):
                planned_file = parse_planned_movie_file(plan, folder_path, movie_path, loose_root_file=True)
                if planned_file is not None:
                    planned_files.append(planned_file)
            continue

        if len(folder_files) != 1:
            multi_changes = plan_multi_part_movie_folder(source_root, folder_path, sorted(folder_files), naming_style)
            if not multi_changes:
                multi_changes = plan_multi_movie_package_folder(source_root, folder_path, sorted(folder_files), naming_style)
            if multi_changes:
                plan.proposed_changes.extend(multi_changes)
            else:
                plan.warnings.append(
                    WarningItem(
                        code="movie_folder_multiple_videos",
                        message="Folder contains multiple supported video files; movie normalization was skipped for safety.",
                        path=str(folder_path),
                    )
                )
            continue

        movie_path = folder_files[0]
        planned_file = parse_planned_movie_file(plan, folder_path, movie_path, loose_root_file=False)
        if planned_file is not None:
            planned_files.append(planned_file)

    movie_bases = movie_bases_for_planned_files(planned_files, naming_style)
    for planned_file in planned_files:
        append_movie_file_changes(plan, source_root, planned_file, movie_bases[planned_file.movie_path])

    for folder_change in plan_collection_folder_cleanup(source_root, movie_files, files_by_folder):
        plan.proposed_changes.append(folder_change)

    for artifact_change in plan_movie_artifact_folder_cleanup(source_root, movie_files):
        plan.proposed_changes.append(artifact_change)

    for junk_change in plan_root_junk_file_cleanup(source_root):
        plan.proposed_changes.append(junk_change)

    mark_movie_target_collisions(plan, source_root)
    return plan


def normalize_movie_naming_style(value: str) -> str:
    if value in MOVIE_NAMING_STYLES:
        return value
    raise ValueError(f"unknown movie naming style: {value}")


def parse_planned_movie_file(
    plan: ChangePlan,
    folder_path: Path,
    movie_path: Path,
    loose_root_file: bool,
) -> PlannedMovieFile | None:
    parsed = parse_movie_name(movie_path)
    if parsed.title is None or parsed.year is None:
        parsed = parsed_movie_identity_from_sidecar(movie_path) or parsed
    for warning in parsed.warnings:
        plan.warnings.append(
            WarningItem(
                code="movie_name_review",
                message=warning,
                path=str(movie_path),
            )
        )

    if parsed.title is None or parsed.year is None:
        plan.warnings.append(
            WarningItem(
                code="movie_name_unparsed",
                message="Movie title/year could not be parsed confidently from the local path.",
                path=str(movie_path),
            )
        )
        return None

    return PlannedMovieFile(folder_path=folder_path, movie_path=movie_path, loose_root_file=loose_root_file, parsed=parsed)


def parsed_movie_identity_from_sidecar(movie_path: Path) -> ParsedMovieName | None:
    nfo_path = movie_path.with_suffix(".nfo")
    if not nfo_path.exists():
        return None
    try:
        root = ET.fromstring(nfo_path.read_text(encoding="utf-8-sig", errors="ignore"))
    except (OSError, ET.ParseError):
        return None
    title = (root.findtext("title") or root.findtext("originaltitle") or "").strip()
    year_text = (root.findtext("year") or "").strip()
    if not title or not re.fullmatch(r"(19\d{2}|20\d{2}|2100)", year_text):
        return None
    return ParsedMovieIdentity(title=title, year=int(year_text), tech_tokens=[], release_group=None, confidence="safe", warnings=[])


def append_movie_file_changes(
    plan: ChangePlan,
    source_root: Path,
    planned_file: PlannedMovieFile,
    canonical_base: str,
) -> None:
    parsed = planned_file.parsed
    movie_path = planned_file.movie_path
    folder_path = planned_file.folder_path
    if planned_file.loose_root_file:
        file_move = build_loose_file_move_change(source_root, movie_path, canonical_base, parsed.confidence)
        if file_move is not None:
            plan.proposed_changes.append(file_move)
        return

    file_change = build_file_change(source_root, movie_path, canonical_base, parsed.confidence)
    if file_change is not None:
        plan.proposed_changes.append(file_change)

    folder_change = build_folder_change(source_root, folder_path, canonical_base, parsed.confidence)
    if folder_change is not None:
        plan.proposed_changes.append(folder_change)


def parse_movie_name(movie_path: Path) -> ParsedMovieName:
    return parse_movie_identity(movie_path)


def plan_multi_part_movie_folder(
    source_root: Path,
    folder_path: Path,
    folder_files: list[Path],
    naming_style: str,
) -> list[ProposedChange]:
    parsed_files = [(movie_path, parse_movie_name(movie_path)) for movie_path in folder_files]
    if any(parsed.title is None or parsed.year is None for _, parsed in parsed_files):
        return []
    identities = {(parsed.title, parsed.year) for _, parsed in parsed_files}
    if len(identities) != 1:
        return []
    part_labels = [movie_part_label(parsed) for _, parsed in parsed_files]
    if any(label is None for label in part_labels):
        return []
    labels = [label or "" for label in part_labels]
    if len(set(label.casefold() for label in labels)) != len(labels):
        return []

    first = parsed_files[0][1]
    base = movie_base_for_naming_style(first, naming_style)
    changes: list[ProposedChange] = []
    for movie_path, parsed in parsed_files:
        label = movie_part_label(parsed) or ""
        proposed_name = f"{base} {label}{movie_path.suffix.lower()}"
        if movie_path.name != proposed_name:
            changes.append(
                ProposedChange(
                    item_id=f"{movie_path.relative_to(source_root)}#file",
                    change_type="file_rename",
                    current_value=movie_path.name,
                    proposed_value=proposed_name,
                    confidence="safe",
                    reason="Multi-part movie filename was normalized with its parsed part label.",
                    path=str(movie_path),
                )
            )
    if folder_path.name != base:
        changes.append(
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#folder",
                change_type="folder_rename",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value=str(folder_path.with_name(base).relative_to(source_root)),
                confidence="safe",
                reason="Multi-part movie folder was normalized to the shared movie title and year.",
                path=str(folder_path),
            )
        )
    return changes


def plan_multi_movie_package_folder(
    source_root: Path,
    folder_path: Path,
    folder_files: list[Path],
    naming_style: str,
) -> list[ProposedChange]:
    if not is_multi_movie_package_folder_name(folder_path.name.casefold()):
        return []

    parsed_files = [(movie_path, parse_movie_name(movie_path)) for movie_path in folder_files]
    if any(parsed.title is None or parsed.year is None for _, parsed in parsed_files):
        return []

    identities = {(parsed.title.casefold(), parsed.year) for _, parsed in parsed_files if parsed.title is not None}
    if len(identities) != len(parsed_files):
        return []

    changes: list[ProposedChange] = []
    for movie_path, parsed in parsed_files:
        base = movie_base_for_naming_style(parsed, naming_style)
        proposed_path = Path(base) / f"{base}{movie_path.suffix.lower()}"
        if movie_path.relative_to(source_root) == proposed_path:
            continue
        changes.append(
            ProposedChange(
                item_id=f"{movie_path.relative_to(source_root)}#file-move",
                change_type="file_move",
                current_value=movie_path.name,
                proposed_value=str(proposed_path),
                confidence=parsed.confidence,
                reason="Multi-movie package file was split into its parsed movie folder.",
                path=str(movie_path),
            )
        )

    if changes and is_safe_delete_after_multi_movie_split(folder_path, set(folder_files)):
        changes.append(
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#package-folder-delete",
                change_type="folder_delete",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value="",
                confidence="safe",
                reason="Multi-movie package folder was deleted after its movies were split out.",
                path=str(folder_path),
            )
        )
    return changes


def movie_part_label(parsed: ParsedMovieName) -> str | None:
    for token in parsed.tech_tokens:
        if re.fullmatch(r"(?i)(?:cd|disc|disk|part)\d+", token):
            return token.upper()
    return None


def find_movie_year_match(value: str) -> re.Match[str] | None:
    matches = list(YEAR_PATTERN.finditer(value))
    if not matches:
        return None
    first = matches[0]
    if first.start() == 0 and len(matches) > 1:
        parenthesized = next((match for match in matches[1:] if is_parenthesized_year(value, match)), None)
        if parenthesized is not None:
            return parenthesized
        if is_leading_numeric_title(value, first):
            return matches[1]
    return first


def is_parenthesized_year(value: str, match: re.Match[str]) -> bool:
    return match.start() > 0 and match.end() < len(value) and value[match.start() - 1] == "(" and value[match.end()] == ")"


def is_leading_numeric_title(value: str, match: re.Match[str]) -> bool:
    if match.start() != 0 or match.end() >= len(value):
        return False
    return value[match.end()] in {".", "-", "_", " "}


def parse_leading_number_compact_payload(source_text: str, match: re.Match[str]) -> tuple[str, int, str] | None:
    prefix = source_text[: match.start()]
    if cleanup_title_text(prefix):
        return None
    leading_number = match.group(1)
    bracket_match = BRACKET_CONTENT_PATTERN.search(source_text[match.end() :])
    if bracket_match is None:
        return None
    content = bracket_match.group("content")
    inner_match = YEAR_PATTERN.search(content)
    if inner_match is None:
        return None
    compact_title = content[: inner_match.start()]
    tail_text = content[inner_match.end() :]
    title_tail = cleanup_compact_title_text(compact_title)
    if not title_tail and not compact_title.strip():
        return leading_number, int(inner_match.group(1)), tail_text
    if not title_tail:
        return None
    return f"{leading_number} {title_tail}", int(inner_match.group(1)), tail_text


def parse_year_leading_bracket_payload(source_text: str, match: re.Match[str], year: int) -> tuple[str, str] | None:
    prefix = source_text[: match.start()]
    if cleanup_title_text(prefix):
        return None
    bracket_match = BRACKET_CONTENT_PATTERN.search(source_text[match.end() :])
    if bracket_match is None:
        return None
    content = bracket_match.group("content")
    if YEAR_PATTERN.search(content):
        return None
    tokens = TOKEN_PATTERN.findall(content)
    if not tokens:
        return None
    boundary = next((index for index, token in enumerate(tokens) if token.lower() in TITLE_BOUNDARY_TOKENS), len(tokens))
    title_tokens = tokens[:boundary]
    if not title_tokens:
        return None
    tail_tokens = tokens[boundary:]
    return cleanup_title_text(" ".join(title_tokens)), " ".join(tail_tokens)


def cleanup_compact_title_text(value: str) -> str:
    cleaned = cleanup_title_text(value)
    if not cleaned:
        return ""
    if re.search(r"[\s._\-]", value):
        return cleaned
    split_words = split_known_compact_title_words(value)
    return " ".join(split_words) if split_words else cleaned


def split_known_compact_title_words(value: str) -> list[str]:
    upper_value = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    words: list[str] = []
    index = 0
    ordered_keys = sorted(COMPACT_TITLE_WORDS, key=len, reverse=True)
    while index < len(upper_value):
        match_key = next((key for key in ordered_keys if upper_value.startswith(key, index)), None)
        if match_key is None:
            return []
        words.append(COMPACT_TITLE_WORDS[match_key])
        index += len(match_key)
    return words


def cleanup_title_text(value: str) -> str:
    value = strip_leading_site_credit(value)
    value = strip_leading_collection_index(value)
    cleaned = re.sub(r"[._]+", " ", value)
    cleaned = re.sub(r"[\[\]()\-]+", " ", cleaned)
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned:
        return ""
    words = []
    for word in cleaned.split():
        if word.isupper() and len(word) <= 4:
            if word in {"OF", "ON", "IN", "AN", "THE", "FOR", "AND", "FROM", "APES"}:
                words.append(word.capitalize())
            else:
                words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def fallback_parent_title(parent_name: str, year: int) -> str:
    year_index = parent_name.find(str(year))
    if year_index >= 0:
        return cleanup_title_text(parent_name[:year_index])
    return cleanup_title_text(parent_name)


def strip_leading_collection_index(value: str) -> str:
    return re.sub(r"^\s*0+\d{1,2}[\s._-]+", "", value, count=1)


def strip_leading_site_credit(value: str) -> str:
    stripped = value
    for pattern in LEADING_SITE_CREDIT_PATTERNS:
        stripped = pattern.sub("", stripped, count=1)
    return stripped


def cleanup_group_text(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    return cleaned or None


def cleanup_collection_folder_name(value: str) -> str:
    cleaned = value.replace("_", " ")
    cleaned = re.sub(r"\.", " ", cleaned)
    cleaned = re.sub(r"\s*\[\s*", " [", cleaned)
    cleaned = re.sub(r"\s*\]\s*", "] ", cleaned)
    cleaned = re.sub(r"\[\s+", "[", cleaned)
    cleaned = re.sub(r"\s+\]", "]", cleaned)
    return " ".join(cleaned.split()).strip()


def normalize_token(token: str) -> str:
    key = token.lower()
    if key in CANONICAL_TOKEN_MAP:
        return CANONICAL_TOKEN_MAP[key]
    if re.fullmatch(r"\d{3,4}p", key):
        return key
    if re.fullmatch(r"\d+bit", key):
        return key
    if re.fullmatch(r"\d\.\d", token):
        return token
    if key.isdigit():
        return key
    if len(token) <= 6:
        return token.upper()
    return token


def split_compact_technical_token(token: str) -> list[str]:
    audio_match = re.fullmatch(r"(?i)(ddp|dd)(\d)", token)
    if audio_match is not None:
        return [audio_match.group(1), audio_match.group(2)]
    video_match = re.fullmatch(r"(?i)h(26[45])", token)
    if video_match is not None:
        return ["h" + video_match.group(1)]
    if not should_split_compact_technical_token(token):
        return [token]

    upper_token = token.upper()
    marker_lookup = {marker.upper(): marker for marker in COMPACT_TECH_MARKERS}
    marker_keys = sorted(marker_lookup, key=len, reverse=True)
    pieces: list[str] = []
    index = 0

    while index < len(token):
        match_key = next((key for key in marker_keys if upper_token.startswith(key, index)), None)
        if match_key is not None:
            pieces.append(marker_lookup[match_key])
            index += len(match_key)
            continue

        next_marker_index = len(token)
        for key in marker_keys:
            found = upper_token.find(key, index + 1)
            if found != -1:
                next_marker_index = min(next_marker_index, found)
        pieces.append(token[index:next_marker_index])
        index = next_marker_index

    return [piece for piece in pieces if piece]


def should_mark_compact_split_for_review(token: str) -> bool:
    if re.fullmatch(r"(?i)(ddp|dd)\d", token):
        return False
    if re.fullmatch(r"(?i)h26[45]", token):
        return False
    return True


def should_split_compact_technical_token(token: str) -> bool:
    if len(token) <= 8:
        return False
    upper_token = token.upper()
    marker_count = sum(1 for marker in COMPACT_TECH_MARKERS if marker.upper() in upper_token)
    return marker_count >= 2


def canonicalize_token_sequence(tokens: list[str]) -> list[str]:
    merged: list[str] = []
    index = 0
    while index < len(tokens):
        current = tokens[index]
        next_token = tokens[index + 1] if index + 1 < len(tokens) else None
        next_next = tokens[index + 2] if index + 2 < len(tokens) else None

        if current.upper() == "BLU" and next_token and next_token.upper() == "RAY":
            merged.append("BluRay")
            index += 2
            continue
        if current.upper() == "WEB" and next_token and next_token.upper() == "DL":
            merged.append("WEB-DL")
            index += 2
            continue
        if current.upper() == "DTS" and next_token and next_token.upper() == "HD":
            merged.append("DTS-HD")
            index += 2
            continue
        if current.upper() == "H" and next_token in {"264", "265"}:
            merged.append(f"H.{next_token}")
            index += 2
            continue
        if current.upper() == "OPEN" and next_token and next_token.upper() == "MATTE":
            merged.append("Open Matte")
            index += 2
            continue
        if current.upper() in {"DD", "DDP"} and is_single_digit_token(next_token) and is_single_digit_token(next_next):
            merged.append(f"{current.upper()} {next_token}.{next_next}")
            index += 3
            continue
        if is_single_digit_token(current) and is_single_digit_token(next_token):
            merged.append(f"{current}.{next_token}")
            index += 2
            continue

        merged.append(current)
        index += 1
    return dedupe_preserve_order(merged)


def is_single_digit_token(value: str | None) -> bool:
    return value is not None and re.fullmatch(r"\d", value) is not None


def dedupe_preserve_order(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        marker = token.lower()
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(token)
    return ordered


def canonical_movie_base(parsed: ParsedMovieName) -> str:
    base = f"{parsed.title} ({parsed.year})"
    details = verbose_technical_tokens(parsed.tech_tokens)
    if details:
        return f"{base} [{' '.join(details)}]"
    return base


def verbose_technical_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if should_keep_verbose_token(token)]


def should_keep_verbose_token(token: str) -> bool:
    if token in VERBOSE_DROP_TOKENS:
        return False
    if LANGUAGE_TOKEN_PATTERN.fullmatch(token):
        return False
    if UPLOADER_TOKEN_PATTERN.fullmatch(token):
        return False
    if re.fullmatch(r"\d\.\d", token):
        return False
    if re.fullmatch(r"\d{3,4}p", token):
        return True
    if re.fullmatch(r"\d+bit", token):
        return True
    if re.fullmatch(r"(?i)v\d+", token):
        return True
    return token in VERBOSE_KEEP_TOKENS


def concise_movie_base(parsed: ParsedMovieName) -> str:
    return f"{parsed.title} ({parsed.year})"


def movie_base_for_naming_style(parsed: ParsedMovieName, naming_style: str) -> str:
    if normalize_movie_naming_style(naming_style) == "verbose":
        return canonical_movie_base(parsed)
    return concise_movie_base(parsed)


def movie_bases_for_planned_files(planned_files: list[PlannedMovieFile], naming_style: str) -> dict[Path, str]:
    bases = {planned_file.movie_path: movie_base_for_naming_style(planned_file.parsed, naming_style) for planned_file in planned_files}
    grouped: dict[str, list[PlannedMovieFile]] = defaultdict(list)
    for planned_file in planned_files:
        grouped[bases[planned_file.movie_path]].append(planned_file)

    for base, collisions in grouped.items():
        if len(collisions) < 2:
            continue
        differentiators = concise_collision_differentiators(collisions)
        if differentiators is None:
            continue
        for planned_file, differentiator in zip(collisions, differentiators, strict=True):
            if differentiator:
                bases[planned_file.movie_path] = f"{base} {differentiator}"
    return bases


def concise_collision_differentiators(planned_files: list[PlannedMovieFile]) -> list[str] | None:
    candidates = [planned_movie_differentiator_candidates(planned_file) for planned_file in planned_files]
    max_candidate_count = max((len(candidate) for candidate in candidates), default=0)
    for count in range(1, max_candidate_count + 1):
        labels = [" ".join(candidate[:count]) for candidate in candidates]
        if all(labels) and len(set(label.casefold() for label in labels)) == len(labels):
            return labels
        non_empty_labels = [label for label in labels if label]
        if non_empty_labels and len(set(label.casefold() for label in non_empty_labels)) == len(non_empty_labels):
            return labels
    return None


def planned_movie_differentiator_candidates(planned_file: PlannedMovieFile) -> list[str]:
    candidates = movie_differentiator_candidates(planned_file.parsed)
    folder_parsed = parse_movie_name(planned_file.folder_path)
    if folder_parsed.title == planned_file.parsed.title and folder_parsed.year == planned_file.parsed.year:
        for token in movie_differentiator_candidates(folder_parsed):
            if token not in candidates:
                candidates.append(token)
    return candidates


def movie_differentiator_candidates(parsed: ParsedMovieName) -> list[str]:
    tokens = list(parsed.tech_tokens)
    if parsed.release_group:
        tokens.append(parsed.release_group)

    priority_groups = [
        lambda token: re.fullmatch(r"\d{3,4}p", token) is not None,
        lambda token: token in {"UHD", "BluRay", "WEB-DL", "WEBRip", "BDRip", "BRRip", "DVDRip", "DVD", "Remux"},
        lambda token: token in {"x264", "x265", "H.264", "H.265", "HEVC", "AV1"},
        lambda token: token in {"AAC", "AC3", "EAC3", "DDP", "DTS", "DTS-HD", "TrueHD", "Atmos"},
        lambda token: True,
    ]
    ordered: list[str] = []
    for predicate in priority_groups:
        for token in tokens:
            if predicate(token) and token not in ordered:
                ordered.append(token)
    return ordered


def mark_movie_target_collisions(plan: ChangePlan, source_root: Path) -> None:
    targets: dict[str, list[ProposedChange]] = defaultdict(list)
    for change in plan.proposed_changes:
        target = movie_change_target_key(change, source_root)
        if target is not None:
            targets[target].append(change)

    for target, changes in sorted(targets.items()):
        if len(changes) < 2:
            continue
        for change in changes:
            change.confidence = "review"
            if "Target path collides with another proposed movie normalization change." not in change.reason:
                change.reason = f"{change.reason} Target path collides with another proposed movie normalization change."
        plan.warnings.append(
            WarningItem(
                code="movie_name_target_collision",
                message="Multiple movie normalization changes propose the same target path.",
                path=target,
            )
        )

    mark_existing_movie_target_collisions(plan, source_root)


def mark_existing_movie_target_collisions(plan: ChangePlan, source_root: Path) -> None:
    source_resolved = source_root.resolve()
    for change in plan.proposed_changes:
        target = movie_change_target_key(change, source_root)
        if target is None or change.path is None:
            continue
        target_path = source_resolved / target
        if not target_path.exists():
            continue
        source_path = Path(change.path).resolve()
        try:
            if target_path.samefile(source_path):
                continue
        except OSError:
            pass
        mark_change_for_existing_target_collision(change)
        if change.change_type == "folder_rename":
            mark_related_folder_changes_for_existing_target_collision(plan, change)
        plan.warnings.append(
            WarningItem(
                code="movie_name_existing_target_collision",
                message="Movie normalization target already exists in the library.",
                path=str(target_path),
            )
        )


def mark_related_folder_changes_for_existing_target_collision(plan: ChangePlan, folder_change: ProposedChange) -> None:
    current = folder_change.current_value
    for change in plan.proposed_changes:
        if change is folder_change or change.path is None:
            continue
        if change.change_type not in {"file_rename", "file_move"}:
            continue
        try:
            relative_path = Path(change.path).resolve().relative_to(Path(folder_change.path or "").resolve())
        except ValueError:
            continue
        if relative_path.parts:
            mark_change_for_existing_target_collision(change)


def mark_change_for_existing_target_collision(change: ProposedChange) -> None:
    change.confidence = "review"
    message = "Target path already exists in the library."
    if message not in change.reason:
        change.reason = f"{change.reason} {message}"


def movie_change_target_key(change: ProposedChange, source_root: Path) -> str | None:
    if change.change_type == "file_move":
        return change.proposed_value
    if change.change_type == "folder_rename":
        return change.proposed_value
    if change.change_type == "file_rename" and change.path is not None:
        source_path = Path(change.path)
        try:
            relative_parent = source_path.parent.resolve().relative_to(source_root.resolve())
        except ValueError:
            return None
        return str(relative_parent / change.proposed_value)
    return None


def plan_collection_folder_cleanup(
    source_root: Path,
    movie_files: list[Path],
    files_by_folder: dict[Path, list[Path]],
) -> list[ProposedChange]:
    direct_video_folders = set(files_by_folder)
    candidate_folders: set[Path] = set()
    source_resolved = source_root.resolve()

    for movie_path in movie_files:
        for parent in movie_path.parent.parents:
            parent_resolved = parent.resolve()
            if parent_resolved == source_resolved:
                break
            try:
                parent_resolved.relative_to(source_resolved)
            except ValueError:
                break
            if is_redundant_single_movie_wrapper(source_root, movie_path.parent):
                continue
            if parent in direct_video_folders:
                continue
            candidate_folders.add(parent)

    changes: list[ProposedChange] = []
    for folder_path in sorted(candidate_folders, key=lambda path: str(path.relative_to(source_root))):
        proposed_name = cleanup_collection_folder_name(folder_path.name)
        if not proposed_name or proposed_name == folder_path.name:
            continue
        changes.append(
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#collection-folder",
                change_type="folder_rename",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value=str(folder_path.with_name(proposed_name).relative_to(source_root)),
                confidence="safe",
                reason="Collection folder punctuation and spacing were normalized without inferring title or year.",
                path=str(folder_path),
            )
        )
    return changes


def plan_movie_artifact_folder_cleanup(source_root: Path, movie_files: list[Path]) -> list[ProposedChange]:
    movie_file_roots = {movie_path.relative_to(source_root).parts[0] for movie_path in movie_files if movie_path.relative_to(source_root).parts}
    changes: list[ProposedChange] = []
    try:
        entries = sorted(source_root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        return changes

    for folder_path in entries:
        if not folder_path.is_dir() or folder_path.name.startswith("."):
            continue
        if folder_path.name in movie_file_roots:
            continue
        if is_safe_delete_artifact_collection_folder(folder_path):
            changes.append(
                ProposedChange(
                    item_id=f"{folder_path.relative_to(source_root)}#artifact-folder-delete",
                    change_type="folder_delete",
                    current_value=str(folder_path.relative_to(source_root)),
                    proposed_value="",
                    confidence="safe",
                    reason="No-video collection artifact folder contained only metadata/system files and was deleted.",
                    path=str(folder_path),
                )
            )
            continue
        parsed = parse_movie_name(folder_path)
        if parsed.title is None or parsed.year is None:
            continue
        concise_base = concise_movie_base(parsed)
        if folder_path.name == concise_base:
            continue
        target_path = source_root / concise_base
        if target_path.exists():
            if not target_path.is_dir() or folder_tree_has_relative_collisions(folder_path, target_path):
                changes.append(
                    ProposedChange(
                        item_id=f"{folder_path.relative_to(source_root)}#artifact-folder",
                        change_type="folder_rename",
                        current_value=str(folder_path.relative_to(source_root)),
                        proposed_value=str(target_path.relative_to(source_root)),
                        confidence="review",
                        reason="No-video movie artifact folder matched an existing concise target, but merge safety requires review.",
                        path=str(folder_path),
                    )
                )
                continue
            changes.append(
                ProposedChange(
                    item_id=f"{folder_path.relative_to(source_root)}#artifact-folder-merge",
                    change_type="folder_merge",
                    current_value=str(folder_path.relative_to(source_root)),
                    proposed_value=str(target_path.relative_to(source_root)),
                    confidence="safe",
                    reason="No-video movie artifact folder was merged into the existing concise movie folder.",
                    path=str(folder_path),
                )
            )
            continue
        changes.append(
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#artifact-folder",
                change_type="folder_rename",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value=str(target_path.relative_to(source_root)),
                confidence=parsed.confidence,
                reason="No-video movie artifact folder was normalized from its locally parsed title and year.",
                path=str(folder_path),
            )
        )
    return changes


def plan_root_junk_file_cleanup(source_root: Path) -> list[ProposedChange]:
    changes: list[ProposedChange] = []
    try:
        entries = sorted(source_root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        return changes
    for path in entries:
        if not path.is_file():
            continue
        if not path.name.startswith("._"):
            continue
        changes.append(
            ProposedChange(
                item_id=f"{path.relative_to(source_root)}#junk-file-delete",
                change_type="file_delete",
                current_value=str(path.relative_to(source_root)),
                proposed_value="",
                confidence="safe",
                reason="Root AppleDouble metadata file was deleted.",
                path=str(path),
            )
        )
    return changes


def is_safe_delete_artifact_collection_folder(folder_path: Path) -> bool:
    name = folder_path.name.casefold()
    if not is_package_artifact_folder_name(name):
        return False
    try:
        files = [path for path in folder_path.rglob("*") if path.is_file()]
    except OSError:
        return False
    if not files:
        return True
    return all(is_safe_delete_artifact_file(path) for path in files)


def is_package_artifact_folder_name(name: str) -> bool:
    if re.search(r"\b19\d{2}\s*-\s*(?:19|20)\d{2}\b", name):
        return True
    tokens = set(TOKEN_PATTERN.findall(name.casefold()))
    return bool(tokens & PACKAGE_FOLDER_MARKERS)


def is_multi_movie_package_folder_name(name: str) -> bool:
    if is_package_artifact_folder_name(name):
        return True
    return bool(re.search(r"\s(?:&|and)\s", name))


def is_safe_delete_after_multi_movie_split(folder_path: Path, moved_files: set[Path]) -> bool:
    try:
        files = [path for path in folder_path.rglob("*") if path.is_file()]
    except OSError:
        return False
    moved_resolved = {path.resolve() for path in moved_files}
    for path in files:
        if path.resolve() in moved_resolved:
            continue
        if not is_safe_delete_artifact_file(path):
            return False
    return True


def is_safe_delete_artifact_file(path: Path) -> bool:
    name = path.name.casefold()
    if name.startswith("._"):
        return True
    if name in SAFE_DELETE_ARTIFACT_NAMES:
        return True
    return path.suffix.casefold() in SAFE_DELETE_ARTIFACT_EXTENSIONS


def folder_tree_has_relative_collisions(source_folder: Path, target_folder: Path) -> bool:
    try:
        source_entries = list(source_folder.rglob("*"))
    except OSError:
        return True
    for source_entry in source_entries:
        relative = source_entry.relative_to(source_folder)
        target_entry = target_folder / relative
        if target_entry.exists():
            return True
    return False


def build_file_change(
    source_root: Path,
    movie_path: Path,
    canonical_base: str,
    confidence: str,
) -> ProposedChange | None:
    proposed_name = f"{canonical_base}{movie_path.suffix.lower()}"
    current_name = movie_path.name
    if proposed_name == current_name:
        return None

    return ProposedChange(
        item_id=f"{movie_path.relative_to(source_root)}#file",
        change_type="file_rename",
        current_value=current_name,
        proposed_value=proposed_name,
        confidence=confidence,
        reason="Movie filename was normalized from locally parsed title, year, and technical tokens.",
        path=str(movie_path),
    )


def build_loose_file_move_change(
    source_root: Path,
    movie_path: Path,
    canonical_base: str,
    confidence: str,
) -> ProposedChange | None:
    proposed_path = Path(canonical_base) / f"{canonical_base}{movie_path.suffix.lower()}"
    current_value = movie_path.name
    if movie_path.relative_to(source_root) == proposed_path:
        return None

    return ProposedChange(
        item_id=f"{movie_path.relative_to(source_root)}#file-move",
        change_type="file_move",
        current_value=current_value,
        proposed_value=str(proposed_path),
        confidence=confidence,
        reason="Loose movie file was moved into its canonical movie folder.",
        path=str(movie_path),
    )


def build_folder_change(
    source_root: Path,
    folder_path: Path,
    canonical_base: str,
    confidence: str,
) -> ProposedChange | None:
    if folder_path.resolve() == source_root.resolve():
        return None
    current_name = folder_path.name
    if current_name == canonical_base:
        return None

    proposed_folder = folder_path.with_name(canonical_base)
    reason = "Movie folder was normalized to match the canonical movie release name."
    if is_redundant_single_movie_wrapper(source_root, folder_path):
        proposed_folder = folder_path.parent.with_name(canonical_base)
        reason = "Duplicate wrapper folder was collapsed into the canonical movie folder."

    return ProposedChange(
        item_id=f"{folder_path.relative_to(source_root)}#folder",
        change_type="folder_rename",
        current_value=str(folder_path.relative_to(source_root)),
        proposed_value=str(proposed_folder.relative_to(source_root)),
        confidence=confidence,
        reason=reason,
        path=str(folder_path),
    )


def is_redundant_single_movie_wrapper(source_root: Path, folder_path: Path) -> bool:
    parent = folder_path.parent
    if parent.resolve() == source_root.resolve():
        return False
    if cleanup_collection_folder_name(parent.name) != cleanup_collection_folder_name(folder_path.name):
        return False
    try:
        entries = list(parent.iterdir())
    except OSError:
        return False
    child_dirs = [entry for entry in entries if entry.is_dir()]
    if len(child_dirs) != 1 or child_dirs[0] != folder_path:
        return False
    return all(entry.is_dir() or entry.suffix.lower() not in VIDEO_EXTENSIONS for entry in entries)
