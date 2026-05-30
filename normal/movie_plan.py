from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from normal.models import ChangePlan, ProposedChange, WarningItem, build_empty_plan
from normal.movie_identity import ParsedMovieIdentity, parse_movie_identity, split_title_prefix_tail
from normal.movie_scan import VIDEO_EXTENSIONS, discover_video_files


YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|2100)(?!\d)")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
RELEASE_GROUP_SUFFIX_PATTERN = re.compile(r"-(?P<group>[A-Za-z0-9]{2,12})$")
BRACKET_CONTENT_PATTERN = re.compile(r"\[(?P<content>[^\]]+)\]")
LEADING_SITE_CREDIT_PATTERNS = (
    re.compile(r"^\s*www[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+(?:org|com|net|mx|to|am|cc|io)\s*(?:[-:]+)?\s*", re.IGNORECASE),
    re.compile(r"^\s*www\.[A-Za-z0-9.-]+\s*(?:[-:]+)?\s*", re.IGNORECASE),
    re.compile(
        r"^\s*downloaded[._\s-]+from[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+(?:org|com|net|mx|to|am|cc|io)\s*(?:[-:]+)?\s*",
        re.IGNORECASE,
    ),
)
LEADING_BRACKETED_CREDIT_PATTERN = re.compile(r"^\s*\[(?:YTS(?:[._-]?(?:AM|MX))?|TGX|ERAI[._-]?RAWS)\]\s*", re.IGNORECASE)
LEADING_UPLOADER_CREDIT_PATTERN = re.compile(
    r"^\s*(?:moviesbyrizzo|anoxmous|etrg|hdchina|rarbg(?:[._-]?com)?)\s*(?:[-:]+)\s*",
    re.IGNORECASE,
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
SAFE_DELETE_POSTER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUBTITLE_EXTENSIONS = {".srt", ".sub", ".idx", ".ass", ".ssa", ".vtt"}
PACKAGE_FOLDER_MARKERS = {
    "collection",
    "duology",
    "pack",
    "saga",
    "series",
    "trilogy",
}
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
    source_root: Path
    folder_path: Path
    movie_path: Path
    loose_root_file: bool
    parsed: ParsedMovieName


def build_movie_plan(
    source_root: Path,
    *,
    movie_files: list[Path] | None = None,
    parsed_movies: dict[Path, ParsedMovieName] | None = None,
) -> ChangePlan:
    plan = build_empty_plan(source_root)
    if movie_files is None:
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
                planned_file = parse_planned_movie_file(
                    plan,
                    folder_path,
                    movie_path,
                    loose_root_file=True,
                    parsed_movies=parsed_movies,
                )
                if planned_file is not None:
                    planned_files.append(planned_file)
            continue

        if len(folder_files) != 1:
            multi_changes = plan_multi_part_movie_folder(
                source_root,
                folder_path,
                sorted(folder_files),
                parsed_movies=parsed_movies,
            )
            if multi_changes is None:
                multi_changes = plan_multi_movie_package_folder(
                    source_root,
                    folder_path,
                    sorted(folder_files),
                    parsed_movies=parsed_movies,
                )
            if multi_changes is not None:
                plan.proposed_changes.extend(multi_changes)
            else:
                warning_code = "movie_folder_multiple_videos"
                warning_message = "Folder contains multiple supported video files; movie normalization was skipped for safety."
                if is_multi_movie_package_folder_name(folder_path.name.casefold()):
                    warning_code = "multi_video_package_skipped_lack_child_evidence"
                    warning_message = "Package-style folder contains multiple video files, but child title/year evidence was too weak to split safely."
                plan.warnings.append(
                    WarningItem(
                        code=warning_code,
                        message=warning_message,
                        path=str(folder_path),
                        reason_codes=[warning_code],
                    )
                )
            continue

        movie_path = folder_files[0]
        planned_file = parse_planned_movie_file(
            plan,
            folder_path,
            movie_path,
            loose_root_file=False,
            parsed_movies=parsed_movies,
        )
        if planned_file is not None:
            planned_files.append(planned_file)

    movie_bases = movie_bases_for_planned_files(planned_files)
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
def parse_planned_movie_file(
    plan: ChangePlan,
    folder_path: Path,
    movie_path: Path,
    loose_root_file: bool,
    *,
    parsed_movies: dict[Path, ParsedMovieName] | None = None,
) -> PlannedMovieFile | None:
    parsed = parsed_movie_for_path(movie_path, parsed_movies)
    if parsed.confidence == "review":
        for code, message in zip(parsed.reason_codes, parsed.reason_messages, strict=False):
            plan.warnings.append(
                WarningItem(
                    code=code,
                    message=message,
                    path=str(movie_path),
                    reason_codes=[code],
                )
            )

    if parsed.title is None or parsed.year is None:
        plan.warnings.append(
            WarningItem(
                code="movie_name_unparsed",
                message="Movie title/year could not be parsed confidently from the local path.",
                path=str(movie_path),
                reason_codes=list(parsed.reason_codes),
            )
        )
        return None

    return PlannedMovieFile(
        source_root=plan_source_root(plan),
        folder_path=folder_path,
        movie_path=movie_path,
        loose_root_file=loose_root_file,
        parsed=parsed,
    )


def plan_source_root(plan: ChangePlan) -> Path:
    return Path(plan.source_root)


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
    return ParsedMovieIdentity(
        title=title,
        year=int(year_text),
        tech_tokens=[],
        release_group=None,
        confidence="safe",
        warnings=[],
        title_source="sidecar_nfo",
        year_source="sidecar_nfo",
        parse_source_path=str(nfo_path),
    )


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
        file_move = build_loose_file_move_change(source_root, movie_path, canonical_base, parsed)
        if file_move is not None:
            plan.proposed_changes.append(file_move)
        return

    file_change = build_file_change(source_root, movie_path, canonical_base, parsed)
    if file_change is not None:
        plan.proposed_changes.append(file_change)

    if should_skip_single_movie_folder_change(folder_path, parsed):
        return

    folder_change = build_folder_change(source_root, folder_path, canonical_base, parsed)
    if folder_change is not None:
        plan.proposed_changes.append(folder_change)


def parse_movie_name(movie_path: Path) -> ParsedMovieName:
    return parse_movie_identity(movie_path)


def parse_movie_name_with_sidecar_fallback(movie_path: Path) -> ParsedMovieName:
    parsed = parse_movie_name(movie_path)
    if parsed.title is not None and parsed.year is not None:
        return parsed
    return parsed_movie_identity_from_sidecar(movie_path) or parsed


def parsed_movie_for_path(movie_path: Path, parsed_movies: dict[Path, ParsedMovieName] | None = None) -> ParsedMovieName:
    if parsed_movies is not None:
        cached = parsed_movies.get(movie_path)
        if cached is not None:
            return cached
    parsed = parse_movie_name_with_sidecar_fallback(movie_path)
    if parsed_movies is not None:
        parsed_movies[movie_path] = parsed
    return parsed


def plan_multi_part_movie_folder(
    source_root: Path,
    folder_path: Path,
    folder_files: list[Path],
    *,
    parsed_movies: dict[Path, ParsedMovieName] | None = None,
) -> list[ProposedChange] | None:
    parsed_files = [(movie_path, parsed_movie_for_path(movie_path, parsed_movies)) for movie_path in folder_files]
    if any(parsed.title is None or parsed.year is None for _, parsed in parsed_files):
        return None
    identities = {(parsed.title, parsed.year) for _, parsed in parsed_files}
    if len(identities) != 1:
        return None
    part_labels = [movie_part_label(parsed) for _, parsed in parsed_files]
    if any(label is None for label in part_labels):
        return None
    labels = [label or "" for label in part_labels]
    if len(set(label.casefold() for label in labels)) != len(labels):
        return None

    first = parsed_files[0][1]
    base = concise_movie_base(first)
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
                    reason_codes=["multi_part_movie"],
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
                reason_codes=["multi_part_movie"],
            )
        )
    return changes


def plan_multi_movie_package_folder(
    source_root: Path,
    folder_path: Path,
    folder_files: list[Path],
    *,
    parsed_movies: dict[Path, ParsedMovieName] | None = None,
) -> list[ProposedChange] | None:
    if not is_multi_movie_package_folder_name(folder_path.name.casefold()):
        return None

    parsed_files = [(movie_path, parsed_movie_for_path(movie_path, parsed_movies)) for movie_path in folder_files]
    if any(parsed.title is None or parsed.year is None for _, parsed in parsed_files):
        return None
    if any(movie_title_contains_package_marker(parsed.title or "") for _, parsed in parsed_files):
        return None

    identities = {(parsed.title.casefold(), parsed.year) for _, parsed in parsed_files if parsed.title is not None}
    if len(identities) != len(parsed_files):
        return None

    changes: list[ProposedChange] = []
    for movie_path, parsed in parsed_files:
        base = concise_movie_base(parsed)
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
                reason_codes=merge_reason_codes(parsed.reason_codes, "package_split"),
                warning_codes=list(parsed.reason_codes) if parsed.confidence == "review" else [],
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
                reason_codes=["package_split"],
            )
        )
    return changes


def should_skip_single_movie_folder_change(folder_path: Path, parsed: ParsedMovieName) -> bool:
    if not parsed.title or not is_multi_movie_package_folder_name(folder_path.name.casefold()):
        return False
    return folder_name_contains_distinct_package_segments(folder_path.name, parsed.title)


def folder_name_contains_distinct_package_segments(folder_name: str, parsed_title: str) -> bool:
    if re.search(r"\s(?:&|and)\s", folder_name, re.IGNORECASE) is None:
        return False

    parsed_key = comparable_movie_title(parsed_title)
    segment_titles = [segment_title_from_package_name(part) for part in re.split(r"(?i)\s(?:&|and)\s", folder_name)]
    matching_segments = [title for title in segment_titles if title and comparable_movie_title(title) == parsed_key]
    other_segments = [title for title in segment_titles if title and comparable_movie_title(title) != parsed_key]
    return bool(matching_segments and other_segments)


def segment_title_from_package_name(value: str) -> str:
    cleaned = cleanup_collection_folder_name(strip_leading_site_credit(value))
    cleaned = YEAR_PATTERN.sub(" ", cleaned)
    title_source, _tail = split_title_prefix_tail(cleaned)
    return cleanup_title_text(title_source)


def comparable_movie_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


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
    while True:
        next_value = stripped
        next_value = LEADING_BRACKETED_CREDIT_PATTERN.sub("", next_value, count=1)
        next_value = LEADING_UPLOADER_CREDIT_PATTERN.sub("", next_value, count=1)
        for pattern in LEADING_SITE_CREDIT_PATTERNS:
            next_value = pattern.sub("", next_value, count=1)
        if next_value == stripped:
            return stripped
        stripped = next_value


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
def concise_movie_base(parsed: ParsedMovieName) -> str:
    return f"{parsed.title} ({parsed.year})"


def movie_bases_for_planned_files(planned_files: list[PlannedMovieFile]) -> dict[Path, str]:
    bases = {planned_file.movie_path: concise_movie_base(planned_file.parsed) for planned_file in planned_files}
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
    for token in local_context_differentiator_candidates(planned_file):
        if token not in candidates:
            candidates.append(token)
    return candidates


def local_context_differentiator_candidates(planned_file: PlannedMovieFile) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for folder in relevant_local_context_folders(planned_file):
        label = local_context_differentiator_label(folder, planned_file.parsed)
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(label)
    return candidates


def relevant_local_context_folders(planned_file: PlannedMovieFile) -> list[Path]:
    folders: list[Path] = []
    current = planned_file.folder_path
    root = planned_file.source_root.resolve()
    while True:
        try:
            if current.resolve() == root:
                break
        except OSError:
            break
        folders.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return folders


def local_context_differentiator_label(folder: Path, parsed: ParsedMovieName) -> str:
    raw_label = cleanup_title_text(folder.name)
    if not raw_label:
        return ""
    folder_parsed = parse_movie_name(folder)
    same_identity = folder_parsed.title == parsed.title and folder_parsed.year == parsed.year
    if same_identity:
        return ""
    if raw_label.casefold() == concise_movie_base(parsed).casefold():
        return ""
    return raw_label


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
        target = movie_change_target_key(change, source_root, plan=plan)
        if target is not None:
            targets[target].append(change)

    for target, changes in sorted(targets.items()):
        if len(changes) < 2:
            continue
        for change in changes:
            change.confidence = "review"
            change.reason_codes = merge_reason_codes(change.reason_codes, "unresolved_duplicate_video_target_collision")
            change.warning_codes = merge_reason_codes(change.warning_codes, "unresolved_duplicate_video_target_collision")
            if "Target path collides with another proposed movie normalization change." not in change.reason:
                change.reason = f"{change.reason} Target path collides with another proposed movie normalization change."
        plan.warnings.append(
            WarningItem(
                code="movie_name_target_collision",
                message="Multiple movie normalization changes propose the same target path.",
                path=target,
                reason_codes=["unresolved_duplicate_video_target_collision"],
            )
        )

    mark_existing_movie_target_collisions(plan, source_root)


def mark_existing_movie_target_collisions(plan: ChangePlan, source_root: Path) -> None:
    source_resolved = source_root.resolve()
    for change in plan.proposed_changes:
        target = movie_change_target_key(change, source_root, plan=plan)
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
        if try_resolve_existing_target_collision(plan, change, source_root):
            continue
        mark_change_for_existing_target_collision(change)
        if change.change_type == "folder_rename":
            mark_related_folder_changes_for_existing_target_collision(plan, change)
        plan.warnings.append(
            WarningItem(
                code="movie_name_existing_target_collision",
                message="Movie normalization target already exists in the library.",
                path=str(target_path),
                reason_codes=["unresolved_duplicate_video_target_collision"],
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
    change.reason_codes = merge_reason_codes(change.reason_codes, "unresolved_duplicate_video_target_collision")
    change.warning_codes = merge_reason_codes(change.warning_codes, "unresolved_duplicate_video_target_collision")
    message = "Target path already exists in the library."
    if message not in change.reason:
        change.reason = f"{change.reason} {message}"


def movie_change_target_key(change: ProposedChange, source_root: Path, *, plan: ChangePlan | None = None) -> str | None:
    if change.change_type == "file_move":
        return change.proposed_value
    if change.change_type == "folder_rename":
        return change.proposed_value
    if change.change_type == "file_rename" and change.path is not None:
        source_path = Path(change.path).resolve()
        relative_parent = projected_relative_parent_for_file_change(source_path, source_root, plan)
        if relative_parent is None:
            return None
        return str(relative_parent / change.proposed_value) if str(relative_parent) else change.proposed_value
    return None


def projected_relative_parent_for_file_change(
    source_path: Path,
    source_root: Path,
    plan: ChangePlan | None,
) -> Path | None:
    try:
        relative_parent = source_path.parent.resolve().relative_to(source_root.resolve())
    except ValueError:
        return None
    if plan is None:
        return relative_parent

    projected_parent = relative_parent
    folder_changes = sorted(
        (
            change for change in plan.proposed_changes
            if change.change_type == "folder_rename" and change.path is not None
        ),
        key=lambda change: len(Path(change.current_value).parts),
        reverse=True,
    )
    for change in folder_changes:
        folder_path = Path(change.path).resolve()
        try:
            folder_relative = folder_path.relative_to(source_root.resolve())
        except ValueError:
            continue
        if projected_parent == folder_relative:
            projected_parent = Path(change.proposed_value)
            continue
        try:
            suffix = projected_parent.relative_to(folder_relative)
        except ValueError:
            continue
        projected_parent = Path(change.proposed_value) / suffix
    return projected_parent


def try_resolve_existing_target_collision(plan: ChangePlan, change: ProposedChange, source_root: Path) -> bool:
    if change.path is None:
        return False
    if change.change_type == "file_move":
        return try_resolve_existing_file_move_collision(change, source_root)
    if change.change_type == "folder_rename":
        return try_resolve_existing_folder_collision(plan, change, source_root)
    return False


def try_resolve_existing_file_move_collision(change: ProposedChange, source_root: Path) -> bool:
    source_path = Path(change.path).resolve()
    parsed = parse_movie_name_with_sidecar_fallback(source_path)
    alternate_base = first_available_collision_alternate_base(source_root, source_path, parsed, suffix=source_path.suffix.lower())
    if alternate_base is None:
        return False
    change.proposed_value = str(Path(alternate_base) / f"{alternate_base}{source_path.suffix.lower()}")
    change.reason = "Multi-movie package file was split into an alternate movie folder because the canonical target already exists."
    change.reason_codes = [code for code in change.reason_codes if code != "unresolved_duplicate_video_target_collision"]
    change.warning_codes = [code for code in change.warning_codes if code != "unresolved_duplicate_video_target_collision"]
    change.confidence = "safe"
    return True


def try_resolve_existing_folder_collision(plan: ChangePlan, folder_change: ProposedChange, source_root: Path) -> bool:
    if folder_change.path is None:
        return False
    folder_path = Path(folder_change.path).resolve()
    related_file_change = next(
        (
            change for change in plan.proposed_changes
            if change.change_type == "file_rename"
            and change.path is not None
            and Path(change.path).resolve().parent == folder_path
        ),
        None,
    )
    if related_file_change is None or related_file_change.path is None:
        return False
    source_path = Path(related_file_change.path).resolve()
    parsed = parse_movie_name_with_sidecar_fallback(source_path)
    alternate_base = first_available_collision_alternate_base(source_root, source_path, parsed, suffix=source_path.suffix.lower())
    if alternate_base is None:
        return False
    folder_change.proposed_value = alternate_base
    folder_change.reason = "Movie folder was normalized into an alternate movie folder because the canonical target already exists."
    folder_change.reason_codes = [code for code in folder_change.reason_codes if code != "unresolved_duplicate_video_target_collision"]
    folder_change.warning_codes = [code for code in folder_change.warning_codes if code != "unresolved_duplicate_video_target_collision"]
    folder_change.confidence = "safe"
    related_file_change.proposed_value = f"{alternate_base}{source_path.suffix.lower()}"
    related_file_change.reason = "Movie filename was normalized into an alternate movie folder because the canonical target already exists."
    related_file_change.reason_codes = [code for code in related_file_change.reason_codes if code != "unresolved_duplicate_video_target_collision"]
    related_file_change.warning_codes = [code for code in related_file_change.warning_codes if code != "unresolved_duplicate_video_target_collision"]
    related_file_change.confidence = "safe"
    return True


def first_available_collision_alternate_base(
    source_root: Path,
    source_path: Path,
    parsed: ParsedMovieName,
    *,
    suffix: str,
) -> str | None:
    if parsed.title is None or parsed.year is None:
        return None
    for differentiator in existing_target_collision_differentiators(source_root, source_path, parsed):
        alternate_base = f"{parsed.title} ({parsed.year}) {differentiator}"
        alternate_target = Path(alternate_base) / f"{alternate_base}{suffix}"
        if collision_target_available(alternate_target, source_root, source_path):
            return alternate_base
    return None


def existing_target_collision_differentiators(source_root: Path, movie_path: Path, parsed: ParsedMovieName) -> list[str]:
    candidates = list(movie_differentiator_candidates(parsed))
    planned = PlannedMovieFile(
        source_root=source_root.resolve(),
        folder_path=movie_path.parent,
        movie_path=movie_path,
        loose_root_file=movie_path.parent.resolve() == source_root.resolve(),
        parsed=parsed,
    )
    for token in local_context_differentiator_candidates(planned):
        if token not in candidates:
            candidates.append(token)
    return candidates


def collision_target_available(target_relative: Path, source_root: Path, source_path: Path) -> bool:
    target_path = source_root.resolve() / target_relative
    if not target_path.exists():
        return True
    try:
        return target_path.samefile(source_path)
    except OSError:
        return False


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
            residue_changes = plan_existing_target_artifact_residue(source_root, folder_path, target_path)
            if residue_changes is not None:
                changes.extend(residue_changes)
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
                reason_codes=merge_reason_codes(parsed.reason_codes, "artifact_cleanup"),
                warning_codes=list(parsed.reason_codes) if parsed.confidence == "review" else [],
            )
        )
    return changes


def folder_contains_only_safe_delete_artifacts(folder_path: Path) -> bool:
    try:
        files = [path for path in folder_path.rglob("*") if path.is_file()]
    except OSError:
        return False
    return all(is_safe_delete_artifact_file(path) for path in files)


def plan_existing_target_artifact_residue(source_root: Path, folder_path: Path, target_path: Path) -> list[ProposedChange] | None:
    try:
        files = [path for path in sorted(folder_path.rglob("*")) if path.is_file()]
    except OSError:
        return [
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#artifact-folder-review",
                change_type="folder_merge",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value=str(target_path.relative_to(source_root)),
                confidence="review",
                reason="Existing-target artifact residue could not be inspected safely.",
                path=str(folder_path),
                reason_codes=["existing_target_artifact_residue"],
                warning_codes=["existing_target_artifact_residue"],
            )
        ]
    if not target_path.is_dir():
        return [
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#artifact-folder-review",
                change_type="folder_merge",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value=str(target_path.relative_to(source_root)),
                confidence="review",
                reason="Existing-target artifact residue matched a non-directory target and requires review.",
                path=str(folder_path),
                reason_codes=["existing_target_artifact_residue"],
                warning_codes=["existing_target_artifact_residue"],
            )
        ]
    if all(is_safe_delete_artifact_file(path) for path in files):
        return [
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#artifact-folder-delete",
                change_type="folder_delete",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value="",
                confidence="safe",
                reason="No-video duplicate movie artifact folder contained only metadata/poster/system files and was deleted.",
                path=str(folder_path),
                reason_codes=["artifact_cleanup"],
            )
        ]

    subtitle_files = [path for path in files if is_subtitle_file(path)]
    substantive_files = [path for path in files if not is_safe_delete_artifact_file(path) and not is_subtitle_file(path)]
    if substantive_files:
        return [
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#artifact-folder-review",
                change_type="folder_merge",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value=str(target_path.relative_to(source_root)),
                confidence="review",
                reason="Existing-target artifact residue contains substantive non-subtitle files and requires review.",
                path=str(folder_path),
                reason_codes=["existing_target_artifact_residue"],
                warning_codes=["existing_target_artifact_residue"],
            )
        ]
    if not subtitle_files:
        return None

    collisions: list[Path] = []
    subtitle_changes: list[ProposedChange] = []
    for subtitle_path in subtitle_files:
        relative = subtitle_path.relative_to(folder_path)
        target_relative = target_path.relative_to(source_root) / relative
        if (source_root / target_relative).exists():
            collisions.append(target_relative)
            continue
        subtitle_changes.append(
            ProposedChange(
                item_id=f"{subtitle_path.relative_to(source_root)}#subtitle-merge",
                change_type="file_move",
                current_value=subtitle_path.name,
                proposed_value=str(target_relative),
                confidence="safe",
                reason="Subtitle-only residue was merged into the surviving movie folder.",
                path=str(subtitle_path),
                reason_codes=["subtitle_merge_safe"],
            )
        )
    if collisions:
        return [
            ProposedChange(
                item_id=f"{folder_path.relative_to(source_root)}#subtitle-merge-review",
                change_type="folder_merge",
                current_value=str(folder_path.relative_to(source_root)),
                proposed_value=str(target_path.relative_to(source_root)),
                confidence="review",
                reason="Subtitle merge would collide with an existing target path and requires review.",
                path=str(folder_path),
                reason_codes=["subtitle_merge_collision"],
                warning_codes=["subtitle_merge_collision"],
            )
        ]

    subtitle_changes.append(
        ProposedChange(
            item_id=f"{folder_path.relative_to(source_root)}#artifact-folder-delete",
            change_type="folder_delete",
            current_value=str(folder_path.relative_to(source_root)),
            proposed_value="",
            confidence="safe",
            reason="Subtitle-only residue folder was removed after safe subtitle merge.",
            path=str(folder_path),
            reason_codes=["artifact_cleanup", "subtitle_merge_safe"],
        )
    )
    return subtitle_changes


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


def movie_title_contains_package_marker(title: str) -> bool:
    tokens = set(TOKEN_PATTERN.findall(title.casefold()))
    return bool(tokens & PACKAGE_FOLDER_MARKERS)


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
    suffix = path.suffix.casefold()
    return suffix in SAFE_DELETE_ARTIFACT_EXTENSIONS or suffix in SAFE_DELETE_POSTER_EXTENSIONS


def is_subtitle_file(path: Path) -> bool:
    return path.suffix.casefold() in SUBTITLE_EXTENSIONS


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
    parsed: ParsedMovieName,
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
        confidence=parsed.confidence,
        reason="Movie filename was normalized from locally parsed title, year, and technical tokens.",
        path=str(movie_path),
        reason_codes=list(parsed.reason_codes),
        warning_codes=list(parsed.reason_codes) if parsed.confidence == "review" else [],
    )


def build_loose_file_move_change(
    source_root: Path,
    movie_path: Path,
    canonical_base: str,
    parsed: ParsedMovieName,
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
        confidence=parsed.confidence,
        reason="Loose movie file was moved into its canonical movie folder.",
        path=str(movie_path),
        reason_codes=list(parsed.reason_codes),
        warning_codes=list(parsed.reason_codes) if parsed.confidence == "review" else [],
    )


def build_folder_change(
    source_root: Path,
    folder_path: Path,
    canonical_base: str,
    parsed: ParsedMovieName,
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
        confidence=parsed.confidence,
        reason=reason,
        path=str(folder_path),
        reason_codes=list(parsed.reason_codes),
        warning_codes=list(parsed.reason_codes) if parsed.confidence == "review" else [],
    )


def merge_reason_codes(reason_codes: list[str], *extras: str) -> list[str]:
    merged = list(reason_codes)
    for extra in extras:
        if extra not in merged:
            merged.append(extra)
    return merged


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
