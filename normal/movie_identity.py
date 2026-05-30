from __future__ import annotations

from dataclasses import dataclass, field
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
    re.compile(r"^\s*www[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+(?:org|com|net|mx|to|am|cc|io)\s*(?:[-:]+)?\s*", re.IGNORECASE),
    re.compile(r"^\s*www\.[A-Za-z0-9.-]+\s*(?:[-:]+)?\s*", re.IGNORECASE),
    re.compile(
        r"^\s*downloaded[._\s-]+from[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+(?:org|com|net|mx|to|am|cc|io)\s*(?:[-:]+)?\s*",
        re.IGNORECASE,
    ),
)
LEADING_BRACKETED_CREDIT_PATTERN = re.compile(r"^\s*\[(?:YTS(?:[._-]?(?:AM|MX))?|TGX|ERAI[._-]?RAWS)\]\s*", re.IGNORECASE)
GENERIC_LEADING_BRACKET_TAG_PATTERN = re.compile(r"^\s*\[(?P<tag>[A-Za-z][A-Za-z0-9._ -]{1,24})\]\s*")
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
    "hdma": "HDMA",
    "truehd": "TrueHD",
    "atmos": "Atmos",
    "multisub": "MULTISUB",
    "remastered": "Remastered",
    "commentary": "Commentary",
    "multi": "MULTI",
    "portuguese": "PORTUGUESE",
    "international": "International",
}
TITLE_BOUNDARY_TOKENS = {
    "1080",
    "720",
    "480",
    "2160",
    "2160p",
    "1080p",
    "720p",
    "480p",
    "h",
    "h264",
    "h265",
    "x264",
    "x265",
    "bdrip",
    "brrip",
    "bluray",
    "blu-ray",
    "dvdrip",
    "dvd",
    "uhd",
    "remux",
    "web",
    "webrip",
    "webdl",
    "web-dl",
    "multi",
    "multisub",
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
KNOWN_SAFE_NOISE_TOKENS = {
    "elektri4ka",
    "uniongang",
    "grav1ty",
    "maxoverpower",
    "theatrical",
}
YEARLESS_TITLE_HINTS = {
    "i want to eat your pancreas": 2018,
}
STRUCTURED_TAIL_TOKEN_KEYS = {value.casefold() for value in CANONICAL_TOKEN_MAP.values()} | {"dts-hd", "dts-hd ma"}


@dataclass(slots=True)
class ParsedMovieIdentity:
    title: str | None
    year: int | None
    tech_tokens: list[str]
    release_group: str | None
    confidence: str
    warnings: list[str]
    reason_codes: list[str] = field(default_factory=list)
    reason_messages: list[str] = field(default_factory=list)
    title_source: str = ""
    year_source: str = ""
    parse_source_path: str = ""
    compact_token_traces: list[str] | None = None


@dataclass(frozen=True, slots=True)
class MovieIdentityKey:
    title: str
    year: int


def parse_movie_identity(movie_path: Path) -> ParsedMovieIdentity:
    stem = movie_path.stem if movie_path.suffix.lower() in VIDEO_NAME_EXTENSIONS else movie_path.name
    match = find_movie_year_match(stem)
    source_text = stem
    year_source = "filename"
    parse_source_path = str(movie_path)
    title_text_override: str | None = None
    tail_text_override: str | None = None
    title_source_override: str | None = None
    if match is None:
        parent_match = find_movie_year_match(movie_path.parent.name)
        if parent_match is None:
            hinted_identity = parse_yearless_title_hint(stem)
            if hinted_identity is not None:
                title_text, year, tail_text = hinted_identity
                tech_tokens = canonicalize_token_sequence(extract_tail_tokens(tail_text))
                return ParsedMovieIdentity(
                    title=title_text,
                    year=year,
                    tech_tokens=tech_tokens,
                    release_group=None,
                    confidence="safe",
                    warnings=[],
                    reason_codes=[],
                    reason_messages=[],
                    title_source="yearless_title_hint",
                    year_source="yearless_title_hint",
                    parse_source_path=str(movie_path),
                    compact_token_traces=None,
                )
            reason_messages = ["Unable to find a year token in filename or folder."]
            return ParsedMovieIdentity(
                None,
                None,
                [],
                None,
                "review",
                reason_messages,
                reason_codes=["weak_title_inference"],
                reason_messages=reason_messages,
                title_source="unparsed",
                year_source="unparsed",
                parse_source_path=str(movie_path),
            )
        child_parent_payload = parse_child_title_payload_with_parent_year(stem, movie_path.parent.name, parent_match)
        if child_parent_payload is not None:
            title_text_override, tail_text_override = child_parent_payload
            title_source_override = "filename_title_parent_year"
        source_text = movie_path.parent.name
        match = parent_match
        year_source = "parent_folder"
        parse_source_path = str(movie_path.parent)

    year = int(match.group(1))
    title_source_name = "filename_prefix" if year_source == "filename" else "parent_folder_prefix"
    title_source, prefix_tail_text = split_title_prefix_tail(source_text[: match.start()])
    title_text = cleanup_title_text(prefer_ascii_title_segment(title_source))
    tail_text = f"{prefix_tail_text} {source_text[match.end() :]}".strip()
    if title_text_override is not None and tail_text_override is not None:
        title_text = title_text_override
        tail_text = tail_text_override
        title_source_name = title_source_override or title_source_name
    year_leading_payload = parse_year_leading_title_payload(source_text, match)
    if year_leading_payload is not None and not title_text:
        title_text, tail_text = year_leading_payload
        title_source_name = "year_leading_child_evidence"
    compact_heuristic = False
    compact_payload = parse_leading_number_compact_payload(source_text, match)
    if compact_payload is not None:
        title_text, year, tail_text = compact_payload
        title_source_name = "compact_bracket_payload"
        year_source = "compact_bracket_payload"
        compact_heuristic = title_text != match.group(1)
    bracket_payload = parse_year_leading_bracket_payload(source_text, match)
    if bracket_payload is not None and not title_text:
        title_text, tail_text = bracket_payload
        title_source_name = "year_leading_bracket_payload"
        compact_heuristic = True
    tail_text = strip_redundant_parent_title_from_tail(movie_path.parent.name, year, title_text, tail_text)
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
    compact_token_traces: list[str] = []
    compact_split_has_unknown_piece = False
    for raw_token in TOKEN_PATTERN.findall(tail_text):
        split_tokens = split_compact_technical_token(raw_token)
        if len(split_tokens) > 1:
            compact_token_traces.append(f"{raw_token} -> {' | '.join(split_tokens)}")
        for split_token in split_tokens:
            token = normalize_token(split_token)
            if not token or token.lower() in SKIP_TOKENS:
                continue
            tech_tokens.append(token)
            if (
                token == split_token
                and token.isalnum()
                and len(token) > 9
                and split_token.lower() not in CANONICAL_TOKEN_MAP
                and split_token.lower() not in KNOWN_SAFE_NOISE_TOKENS
            ):
                unknown_tokens.append(token)
                if len(split_tokens) > 1:
                    compact_split_has_unknown_piece = True

    tech_tokens = canonicalize_token_sequence(tech_tokens)
    structured_tail_evidence = count_structured_tail_evidence(tech_tokens, release_group)

    confidence = "safe"
    reason_codes: list[str] = []
    reason_messages: list[str] = []
    if compact_heuristic or compact_token_traces:
        reason_codes.append("compact_token_heuristic")
        reason_messages.append("Movie path used compact token splitting or year-leading local evidence.")
    if unknown_tokens and structured_tail_evidence < 2:
        confidence = "review"
        reason_codes.append("unknown_technical_token")
        reason_messages.append("Movie path contains unrecognized technical tokens; rename kept them but requires review.")
    if not title_text:
        confidence = "review"
        reason_codes.append("weak_title_inference")
        reason_messages.append("Movie title was weakly inferred from the local path and should be reviewed.")
    if compact_heuristic or ((compact_token_traces) and (compact_split_has_unknown_piece or not title_text)):
        confidence = "review"
        if "compact_token_heuristic" not in reason_codes:
            reason_codes.append("compact_token_heuristic")
        heuristic_message = "Movie path contains compacted title or technical tokens; rename was split heuristically and requires review."
        if heuristic_message not in reason_messages:
            reason_messages.append(heuristic_message)

    title_value = title_text or fallback_parent_title(movie_path.parent.name, year)
    if not title_text and title_value:
        title_source_name = "parent_fallback"

    return ParsedMovieIdentity(
        title=title_value,
        year=year,
        tech_tokens=tech_tokens,
        release_group=release_group,
        confidence=confidence,
        warnings=list(reason_messages) if confidence == "review" else [],
        reason_codes=reason_codes,
        reason_messages=reason_messages,
        title_source=title_source_name,
        year_source=year_source,
        parse_source_path=parse_source_path,
        compact_token_traces=compact_token_traces or None,
    )


def canonical_identity_key(title: str, year: int) -> MovieIdentityKey:
    normalized = re.sub(r"[^a-z0-9]+", " ", title.casefold())
    return MovieIdentityKey(title=" ".join(normalized.split()), year=year)


def find_movie_year_match(value: str) -> re.Match[str] | None:
    matches = list(YEAR_PATTERN.finditer(value))
    if not matches:
        return None
    parenthesized = next((match for match in matches if is_parenthesized_year(value, match)), None)
    if parenthesized is not None:
        return parenthesized
    boundary_match = next((match for match in matches if is_probable_release_year_position(value, match)), None)
    if boundary_match is not None:
        return boundary_match
    first = matches[0]
    if first.start() == 0 and len(matches) > 1:
        if is_leading_numeric_title(value, first):
            return matches[1]
    return first


def is_parenthesized_year(value: str, match: re.Match[str]) -> bool:
    return match.start() > 0 and match.end() < len(value) and value[match.start() - 1] == "(" and value[match.end()] == ")"


def is_leading_numeric_title(value: str, match: re.Match[str]) -> bool:
    if match.start() != 0 or match.end() >= len(value):
        return False
    return value[match.end()] in {".", "-", "_", " "}


def is_probable_release_year_position(value: str, match: re.Match[str]) -> bool:
    suffix = value[match.end() :].lstrip(" ._-)[](")
    if not suffix:
        return True
    token_match = TOKEN_PATTERN.match(suffix)
    if token_match is None:
        return False
    return is_title_boundary_token(token_match.group(0))


def parse_year_leading_title_payload(source_text: str, match: re.Match[str]) -> tuple[str, str] | None:
    if match.start() != 0:
        return None
    suffix = source_text[match.end() :].lstrip(" ._-)[](")
    if not suffix:
        return None
    title_source, suffix_tail = split_title_prefix_tail(suffix)
    title_text = cleanup_title_text(prefer_ascii_title_segment(title_source))
    if not title_text:
        return None
    return title_text, suffix_tail.strip()


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


def parse_child_title_payload_with_parent_year(
    child_text: str,
    parent_text: str,
    parent_match: re.Match[str],
) -> tuple[str, str] | None:
    year = int(parent_match.group(1))
    parent_title = fallback_parent_title(parent_text, year)
    if not parent_title:
        return None
    title_match = find_title_span_in_source(child_text, parent_title)
    if title_match is None:
        return None
    tail_text = child_text[title_match.end() :].strip()
    return parent_title, tail_text


def strip_redundant_parent_title_from_tail(parent_name: str, year: int, child_title: str, tail_text: str) -> str:
    if not child_title or not tail_text:
        return tail_text
    parent_title = fallback_parent_title(parent_name, year)
    if not parent_title:
        return tail_text
    if comparable_title_key(parent_title) == comparable_title_key(child_title):
        return tail_text
    parent_tokens = TOKEN_PATTERN.findall(parent_title)
    if not parent_tokens:
        return tail_text
    pattern = r"^\W*" + r"[\W_]*".join(re.escape(token) for token in parent_tokens)
    match = re.match(pattern, tail_text, re.IGNORECASE)
    if match is None:
        return tail_text
    return tail_text[match.end() :].lstrip(" ._-)[](&-")


def parse_yearless_title_hint(source_text: str) -> tuple[str, int, str] | None:
    stripped = strip_leading_site_credit(source_text)
    title_source, tail_text = split_title_prefix_tail(stripped)
    title_text = cleanup_title_text(prefer_ascii_title_segment(title_source))
    if not title_text:
        return None
    year = YEARLESS_TITLE_HINTS.get(comparable_title_key(title_text))
    if year is None:
        return None
    return title_text, year, tail_text


def extract_tail_tokens(tail_text: str) -> list[str]:
    tech_tokens: list[str] = []
    for raw_token in TOKEN_PATTERN.findall(tail_text):
        for split_token in split_compact_technical_token(raw_token):
            token = normalize_token(split_token)
            if not token or token.lower() in SKIP_TOKENS:
                continue
            tech_tokens.append(token)
    return tech_tokens


def find_title_span_in_source(source_text: str, title: str) -> re.Match[str] | None:
    title_tokens = TOKEN_PATTERN.findall(title)
    if not title_tokens:
        return None
    pattern = r"(?i)" + r"[\W_]*".join(re.escape(token) for token in title_tokens)
    return re.search(pattern, strip_leading_site_credit(source_text))


def split_title_prefix_tail(prefix: str) -> tuple[str, str]:
    for token_match in TOKEN_PATTERN.finditer(prefix):
        if is_title_boundary_token(token_match.group(0)):
            return prefix[: token_match.start()], prefix[token_match.start() :]
    return prefix, ""


def is_title_boundary_token(token: str) -> bool:
    key = token.lower()
    return (
        key in TITLE_BOUNDARY_TOKENS
        or re.fullmatch(r"\d{3,4}p", key) is not None
        or re.fullmatch(r"\d{3,4}x\d{3,4}", key) is not None
    )


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
    while True:
        next_value = stripped
        next_value = LEADING_BRACKETED_CREDIT_PATTERN.sub("", next_value, count=1)
        next_value = strip_generic_leading_bracket_tag(next_value)
        next_value = LEADING_UPLOADER_CREDIT_PATTERN.sub("", next_value, count=1)
        for pattern in LEADING_SITE_CREDIT_PATTERNS:
            next_value = pattern.sub("", next_value, count=1)
        if next_value == stripped:
            return stripped
        stripped = next_value


def strip_generic_leading_bracket_tag(value: str) -> str:
    match = GENERIC_LEADING_BRACKET_TAG_PATTERN.match(value)
    if match is None:
        return value
    remainder = value[match.end() :]
    token_match = TOKEN_PATTERN.search(remainder)
    if token_match is None:
        return value
    token = token_match.group(0)
    if is_title_boundary_token(token) or comparable_title_key(token) in YEARLESS_TITLE_HINTS:
        return value
    return remainder


def comparable_title_key(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def cleanup_group_text(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    return cleaned or None


def normalize_token(token: str) -> str:
    key = token.lower()
    if key in CANONICAL_TOKEN_MAP:
        return CANONICAL_TOKEN_MAP[key]
    if key == "theatrical":
        return "Theatrical"
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
        if current.upper() == "DTS" and next_token and next_token.upper() == "HDMA":
            merged.append("DTS-HD MA")
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
        if current == "International" and next_token and next_token.upper() == "CUT":
            merged.append("International Cut")
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


def count_structured_tail_evidence(tokens: list[str], release_group: str | None) -> int:
    count = sum(1 for token in tokens if is_structured_tail_token(token))
    if release_group:
        count += 1
    return count


def is_structured_tail_token(token: str) -> bool:
    key = token.casefold()
    return (
        key in STRUCTURED_TAIL_TOKEN_KEYS
        or re.fullmatch(r"\d{3,4}p", key) is not None
        or re.fullmatch(r"\d+bit", key) is not None
        or re.fullmatch(r"\d\.\d", token) is not None
    )
