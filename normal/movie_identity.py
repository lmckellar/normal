from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


YEAR_PATTERN = re.compile(r"(?<!\d)(19\d{2}|20\d{2}|2100)(?!\d)(?![xX]\d)")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
RELEASE_GROUP_SUFFIX_PATTERN = re.compile(r"-(?P<group>[A-Za-z0-9][A-Za-z0-9-]{1,20})$")
BRACKET_CONTENT_PATTERN = re.compile(r"\[(?P<content>[^\]]+)\]")
VIDEO_NAME_EXTENSIONS = {
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
    "remux",
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
class ParsedMovieIdentity:
    title: str | None
    year: int | None
    tech_tokens: list[str]
    release_group: str | None
    confidence: str
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class MovieIdentityKey:
    title: str
    year: int


def parse_movie_identity(movie_path: Path) -> ParsedMovieIdentity:
    stem = movie_path.stem if movie_path.suffix.lower() in VIDEO_NAME_EXTENSIONS else movie_path.name
    match = find_movie_year_match(stem)
    source_text = stem
    if match is None:
        parent_match = find_movie_year_match(movie_path.parent.name)
        if parent_match is None:
            return ParsedMovieIdentity(None, None, [], None, "review", ["Unable to find a year token in filename or folder."])
        source_text = movie_path.parent.name
        match = parent_match

    year = int(match.group(1))
    title_text = cleanup_title_text(prefer_ascii_title_segment(source_text[: match.start()]))
    tail_text = source_text[match.end() :]
    compact_review = False
    compact_payload = parse_leading_number_compact_payload(source_text, match)
    if compact_payload is not None:
        title_text, year, tail_text = compact_payload
        compact_review = title_text != match.group(1)
    bracket_payload = parse_year_leading_bracket_payload(source_text, match)
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

    return ParsedMovieIdentity(
        title=title_text or fallback_parent_title(movie_path.parent.name, year),
        year=year,
        tech_tokens=canonicalize_token_sequence(tech_tokens),
        release_group=release_group,
        confidence=confidence,
        warnings=warnings,
    )


def canonical_identity_key(title: str, year: int) -> MovieIdentityKey:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold())
    return MovieIdentityKey(title=" ".join(normalized.split()), year=year)


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


def parse_year_leading_bracket_payload(source_text: str, match: re.Match[str]) -> tuple[str, str] | None:
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


def prefer_ascii_title_segment(value: str) -> str:
    cleaned = strip_leading_collection_index(strip_leading_site_credit(value))
    if not has_non_latin_letter(cleaned):
        return cleaned

    ascii_segments = [
        segment
        for segment in re.split(r"[._]+", cleaned)
        if has_ascii_letter(segment) and not has_non_latin_letter(segment)
    ]
    if not ascii_segments:
        return cleaned
    return " ".join(ascii_segments)


def has_ascii_letter(value: str) -> bool:
    return any(("A" <= char <= "Z") or ("a" <= char <= "z") for char in value)


def has_non_latin_letter(value: str) -> bool:
    for char in value:
        if not char.isalpha() or char.isascii():
            continue
        try:
            name = unicodedata.name(char)
        except ValueError:
            return True
        if "LATIN" not in name:
            return True
    return False


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
    if re.fullmatch(r"(?i)blurayremux", token):
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
        if current.lower() == "director" and next_token == "S" and next_next and next_next.upper() == "CUT":
            merged.append("Director's Cut")
            index += 3
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
