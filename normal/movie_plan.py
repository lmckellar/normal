from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

from normal.models import ChangePlan, ProposedChange, WarningItem, build_empty_plan
from normal.movie_scan import VIDEO_EXTENSIONS, discover_video_files


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


@dataclass(slots=True)
class ParsedMovieName:
    title: str | None
    year: int | None
    tech_tokens: list[str]
    release_group: str | None
    confidence: str
    warnings: list[str]


def build_movie_plan(source_root: Path) -> ChangePlan:
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
        return plan

    files_by_folder: dict[Path, list[Path]] = defaultdict(list)
    for movie_path in movie_files:
        files_by_folder[movie_path.parent].append(movie_path)

    for folder_path, folder_files in sorted(files_by_folder.items()):
        if folder_path.resolve() == source_root.resolve():
            for movie_path in sorted(folder_files):
                append_movie_file_changes(plan, source_root, folder_path, movie_path, loose_root_file=True)
            continue

        if len(folder_files) != 1:
            plan.warnings.append(
                WarningItem(
                    code="movie_folder_multiple_videos",
                    message="Folder contains multiple supported video files; movie normalization was skipped for safety.",
                    path=str(folder_path),
                )
            )
            continue

        movie_path = folder_files[0]
        append_movie_file_changes(plan, source_root, folder_path, movie_path, loose_root_file=False)

    for folder_change in plan_collection_folder_cleanup(source_root, movie_files, files_by_folder):
        plan.proposed_changes.append(folder_change)

    return plan


def append_movie_file_changes(
    plan: ChangePlan,
    source_root: Path,
    folder_path: Path,
    movie_path: Path,
    loose_root_file: bool,
) -> None:
    parsed = parse_movie_name(movie_path)
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
        return

    canonical_base = canonical_movie_base(parsed)
    if loose_root_file:
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
    stem = movie_path.stem
    match = find_movie_year_match(stem)
    source_text = stem
    if match is None:
        parent_match = find_movie_year_match(movie_path.parent.name)
        if parent_match is None:
            return ParsedMovieName(None, None, [], None, "review", ["Unable to find a year token in filename or folder."])
        source_text = movie_path.parent.name
        match = parent_match

    year = int(match.group(1))
    title_text = cleanup_title_text(strip_leading_collection_index(strip_leading_site_credit(source_text[: match.start()])))
    tail_text = source_text[match.end() :]
    compact_review = False
    compact_payload = parse_leading_number_compact_payload(source_text, match)
    if compact_payload is not None:
        title_text, year, tail_text = compact_payload
        compact_review = title_text != match.group(1)
    bracket_payload = parse_year_leading_bracket_payload(source_text, match, year)
    if bracket_payload is not None and not title_text:
        title_text, tail_text = bracket_payload
        compact_review = True
    release_group = None

    if " - " in tail_text:
        tail_text, release_group = tail_text.rsplit(" - ", 1)
        release_group = cleanup_group_text(release_group)
    else:
        group_match = RELEASE_GROUP_SUFFIX_PATTERN.search(tail_text)
        if group_match is not None:
            tail_text = tail_text[: group_match.start()]
            release_group = cleanup_group_text(group_match.group("group"))

    tech_tokens = []
    unknown_tokens = []
    for raw_token in TOKEN_PATTERN.findall(tail_text):
        split_tokens = split_compact_technical_token(raw_token)
        if len(split_tokens) > 1 and should_mark_compact_split_for_review(raw_token):
            compact_review = True
        for split_token in split_tokens:
            token = normalize_token(split_token)
            if not token or token.lower() in SKIP_TOKENS:
                continue
            tech_tokens.append(token)
            if token == split_token and token.isalnum() and len(token) > 9 and split_token.lower() not in CANONICAL_TOKEN_MAP:
                unknown_tokens.append(token)

    confidence = "safe"
    warnings: list[str] = []
    if compact_review:
        confidence = "review"
        warnings.append("Movie path contains compacted title or technical tokens; rename was split heuristically and requires review.")
    if unknown_tokens:
        confidence = "review"
        warnings.append("Movie path contains unrecognized technical tokens; rename kept them but requires review.")
    if not title_text:
        confidence = "review"
        warnings.append("Movie title was weakly inferred from the local path and should be reviewed.")

    return ParsedMovieName(
        title=title_text or fallback_parent_title(movie_path.parent.name, year),
        year=year,
        tech_tokens=canonicalize_token_sequence(tech_tokens),
        release_group=release_group,
        confidence=confidence,
        warnings=warnings,
    )


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
    details = list(parsed.tech_tokens)
    if parsed.release_group:
        details.append(parsed.release_group)
    if details:
        return f"{base} [{' '.join(details)}]"
    return base


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
