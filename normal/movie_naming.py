from __future__ import annotations

import re
import unicodedata


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
DOMAIN_CREDIT_TLD_PATTERN = r"(?:org|com|net|mx|to|am|cc|io)"
LEADING_SITE_CREDIT_PATTERNS = (
    re.compile(
        rf"^\s*www[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+{DOMAIN_CREDIT_TLD_PATTERN}(?![A-Za-z0-9])\s*(?:[-:]+)?\s*",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*www\.[A-Za-z0-9.-]+\s*(?:[-:]+)?\s*", re.IGNORECASE),
    re.compile(
        rf"^\s*downloaded[._\s-]+from[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+{DOMAIN_CREDIT_TLD_PATTERN}(?![A-Za-z0-9])\s*(?:[-:]+)?\s*",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^\s*(?:[A-Za-z0-9-]{{4,}}[._\s-]+)+{DOMAIN_CREDIT_TLD_PATTERN}(?![A-Za-z0-9])\s*(?:[-:]+)?\s*",
        re.IGNORECASE,
    ),
)
TRAILING_SITE_CREDIT_PATTERNS = (
    re.compile(
        rf"\s*(?:[-:]+)?\s*www[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+{DOMAIN_CREDIT_TLD_PATTERN}(?![A-Za-z0-9])\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"\s*(?:[-:]+)?\s*www\.[A-Za-z0-9.-]+\s*$", re.IGNORECASE),
    re.compile(
        rf"\s*(?:[-:]+)?\s*downloaded[._\s-]+from[._\s-]+(?:[A-Za-z0-9-]+[._\s-]+)+{DOMAIN_CREDIT_TLD_PATTERN}(?![A-Za-z0-9])\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\s*(?:[-:]+)?\s*(?:[A-Za-z0-9-]{{4,}}[._\s-]+)+{DOMAIN_CREDIT_TLD_PATTERN}(?![A-Za-z0-9])\s*$",
        re.IGNORECASE,
    ),
)
LEADING_BRACKETED_CREDIT_PATTERN = re.compile(r"^\s*\[(?:YTS(?:[._-]?(?:AM|MX))?|TGX|ERAI[._-]?RAWS)\]\s*", re.IGNORECASE)
GENERIC_LEADING_BRACKET_TAG_PATTERN = re.compile(r"^\s*\[\s*(?P<tag>[A-Za-z][A-Za-z0-9._ -]{1,24})\s*\]\s*")
GENERIC_TRAILING_BRACKET_TAG_PATTERN = re.compile(r"\s*\[\s*(?P<tag>[A-Za-z][A-Za-z0-9._ -]{1,24})\s*\]\s*$")
LEADING_UPLOADER_CREDIT_PATTERN = re.compile(
    r"^\s*(?:moviesbyrizzo|anoxmous|etrg|hdchina|rarbg(?:[._-]?com)?)\s*(?:[-:]+)\s*",
    re.IGNORECASE,
)
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
SKIP_TOKENS = {"sample"}
EDITION_WORDS = {
    "directors",
    "director",
    "extended",
    "final",
    "remastered",
    "theatrical",
    "ultimate",
    "uncut",
    "unrated",
}
TRAILING_NOISE_WORDS = {
    "action",
    "adventure",
    "comedy",
    "drama",
    "fantasy",
    "horror",
    "sci fi",
    "scifi",
    "thriller",
}
SHORT_UPPER_WORDS = {"OF", "ON", "IN", "AN", "THE", "FOR", "AND", "FROM", "APES"}
TITLE_ABBREVIATIONS = {
    "dr": "Dr.",
    "mr": "Mr.",
    "mrs": "Mrs.",
    "ms": "Ms.",
}
ORDINAL_SUFFIXES = {"st", "nd", "rd", "th"}
CANONICAL_TITLE_PUNCTUATION_OVERRIDES = {
    "fantastic mr fox": "Fantastic Mr. Fox",
    "k pax": "K-Pax",
    "mr brooks": "Mr. Brooks",
    "shoot em up": "Shoot 'Em Up",
    "sympathy for mr vengeance": "Sympathy For Mr. Vengeance",
    "tron legacy": "TRON: Legacy",
    "wall e": "WALL-E",
}
CANONICAL_TITLE_ALIAS_EQUIVALENTS = {
    "se7en": ("seven",),
    "seven": ("se7en",),
}


def normalize_display_title(value: str) -> str:
    value = strip_leading_site_credit(value)
    value = strip_leading_collection_index(value)
    cleaned = re.sub(r"[._]+", " ", value)
    cleaned = re.sub(r"[\[\]()]+", " ", cleaned)
    cleaned = re.sub(r"\s+-\s+", " ", cleaned)
    cleaned = re.sub(r"(?<=\w)-(?=\s)", " ", cleaned)
    cleaned = re.sub(r"(?<=\s)-(?=\w)", " ", cleaned)
    cleaned = re.sub(r"\s*:\s*", ": ", cleaned)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    cleaned = re.sub(r"\s+([,:!?])", r"\1", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" -")
    if not cleaned:
        return ""
    cleaned = maybe_normalize_shouting_title(cleaned)
    cleaned = punctuate_letter_number_title(cleaned)
    words = [_display_word(word) for word in cleaned.split()]
    normalized = reconstruct_display_title(words)
    normalized = re.sub(r"\s+([,:!?])", r"\1", normalized)
    normalized = re.sub(r":(?!\s|$)", ": ", normalized)
    normalized = re.sub(r",(?=[^\s])", ", ", normalized)
    normalized = re.sub(r"'([A-Z])\b", lambda match: "'" + match.group(1).lower(), normalized)
    normalized = " ".join(normalized.split())
    return apply_canonical_title_punctuation_override(normalized)


def apply_canonical_title_punctuation_override(title: str) -> str:
    return CANONICAL_TITLE_PUNCTUATION_OVERRIDES.get(title_match_key(title), title)


def maybe_normalize_shouting_title(value: str) -> str:
    words = re.findall(r"[A-Za-z]+", value)
    if len(words) < 2:
        return value
    if any(not word.isupper() for word in words if len(word) > 1):
        return value
    if sum(1 for word in words if len(word) > 3) < 2 and not (
        len(words) == 2 and len(words[0]) == 1 and len(words[1]) >= 2
    ):
        return value
    return re.sub(r"[A-Za-z]+", lambda match: match.group(0).lower(), value)


def _display_word(word: str) -> str:
    if word.isupper() and len(word) <= 4:
        return word.capitalize() if word in SHORT_UPPER_WORDS else word

    def normalize_fragment(match: re.Match[str]) -> str:
        fragment = match.group(0)
        if fragment.isupper() and len(fragment) <= 4:
            return fragment.capitalize() if fragment in SHORT_UPPER_WORDS else fragment
        return fragment[0].upper() + fragment[1:].lower()

    return re.sub(r"[A-Za-z]+", normalize_fragment, word)


def reconstruct_display_title(words: list[str]) -> str:
    rebuilt: list[str] = []
    index = 0
    while index < len(words):
        if index == 0:
            initialism = rebuild_leading_initialism(words)
            if initialism is not None:
                rebuilt.append(initialism[0])
                index = initialism[1]
                continue
        rebuilt.append(rebuild_display_word(words[index]))
        index += 1
    return " ".join(rebuilt)


def rebuild_leading_initialism(words: list[str]) -> tuple[str, int] | None:
    run: list[str] = []
    index = 0
    while index < len(words) and len(words[index]) == 1 and words[index].isalpha():
        run.append(words[index].upper())
        index += 1
    if len(run) < 2:
        return None
    return "".join(f"{token}." for token in run), index


def rebuild_display_word(word: str) -> str:
    lower = word.casefold()
    if lower in TITLE_ABBREVIATIONS:
        return TITLE_ABBREVIATIONS[lower]
    return re.sub(r"\b(\d+)([A-Za-z]{2})\b", normalize_ordinal_suffix, word)


def normalize_ordinal_suffix(match: re.Match[str]) -> str:
    suffix = match.group(2).casefold()
    if suffix not in ORDINAL_SUFFIXES:
        return match.group(0)
    return f"{match.group(1)}{suffix}"


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
    cleaned = normalize_display_title(value)
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
        next_value = strip_generic_trailing_bracket_tag(next_value)
        for pattern in TRAILING_SITE_CREDIT_PATTERNS:
            next_value = pattern.sub("", next_value, count=1)
        if next_value == stripped:
            return stripped
        stripped = next_value


def strip_generic_leading_bracket_tag(value: str) -> str:
    match = GENERIC_LEADING_BRACKET_TAG_PATTERN.match(value)
    if match is None:
        return value
    if is_domain_credit_tag(match.group("tag")):
        return value[match.end() :]
    remainder = value[match.end() :]
    token_match = TOKEN_PATTERN.search(remainder)
    if token_match is None:
        return value
    token = token_match.group(0)
    if is_title_boundary_token(token):
        return value
    return remainder


def strip_generic_trailing_bracket_tag(value: str) -> str:
    match = GENERIC_TRAILING_BRACKET_TAG_PATTERN.search(value)
    if match is None or not is_domain_credit_tag(match.group("tag")):
        return value
    return value[: match.start()]


def is_domain_credit_tag(value: str) -> bool:
    return re.fullmatch(rf"(?:[A-Za-z0-9-]{{4,}}[._\s-]+)+{DOMAIN_CREDIT_TLD_PATTERN}", value.strip(), re.IGNORECASE) is not None


def cleanup_group_text(value: str) -> str | None:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value).upper()
    return cleaned or None


def extract_tail_tokens(tail_text: str) -> list[str]:
    tech_tokens: list[str] = []
    for raw_token in TOKEN_PATTERN.findall(tail_text):
        for split_token in split_compact_technical_token(raw_token):
            token = normalize_token(split_token)
            if not token or token.lower() in SKIP_TOKENS:
                continue
            tech_tokens.append(token)
    return tech_tokens


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


def title_match_key(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", title.casefold()).split())


def title_similarity_key(title: str) -> str:
    tokens = [token for token in title_match_key(title).split() if token not in {"the", "a", "an"}]
    return " ".join(tokens)


def title_alias_keys(title: str) -> list[str]:
    aliases: list[str] = []
    full_key = title_match_key(title)
    if full_key:
        aliases.append(full_key)
        aliases.extend(CANONICAL_TITLE_ALIAS_EQUIVALENTS.get(full_key, ()))
    if ":" in title:
        subtitle = title.split(":", 1)[1].strip()
        subtitle_key = title_match_key(subtitle)
        if subtitle_key:
            aliases.append(subtitle_key)
    words = full_key.split()
    for index in range(1, len(words)):
        aliases.append(" ".join(words[index:]))
    return unique_nonempty(aliases)


def provider_title_candidates(title: str) -> list[str]:
    cleaned = clean_lookup_title(title)
    normalized = normalize_display_title(cleaned)
    candidates = [cleaned, normalized]
    candidates.append(punctuate_letter_number_title(cleaned))
    candidates.append(strip_edition_noise(cleaned))
    candidates.append(strip_trailing_noise(candidates[-1]))
    candidates.append(strip_edition_noise(normalized))
    candidates.append(strip_trailing_noise(candidates[-1]))
    return unique_nonempty(candidates)


def clean_lookup_title(title: str) -> str:
    cleaned = re.sub(r"[._]+", " ", title)
    return " ".join(cleaned.split()).strip()


def punctuate_letter_number_title(title: str) -> str:
    if ":" in title:
        return " ".join(title.split()).strip()
    replaced = re.sub(r"\b([A-Za-z])(\d+)\b", r"\1-\2", title, count=1)
    replaced = re.sub(r"\b([A-Za-z])\s*-\s*(\d+)\b", r"\1-\2", replaced, count=1)
    replaced = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1-\2", replaced, count=1)
    return re.sub(r"^([A-Za-z]-\d+)\s+(.+)$", r"\1: \2", replaced, count=1)


def strip_edition_noise(title: str) -> str:
    tokens = title.split()
    while tokens and tokens[-1].casefold().strip(":") in EDITION_WORDS:
        tokens.pop()
    return " ".join(tokens)


def strip_trailing_noise(title: str) -> str:
    lowered = title.casefold()
    for noise in sorted(TRAILING_NOISE_WORDS, key=len, reverse=True):
        suffix = " " + noise
        if lowered.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def unique_nonempty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = " ".join(str(value or "").split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result
