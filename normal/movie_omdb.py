from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from normal.movie_naming import provider_title_candidates, title_similarity_key


OMDB_API_ROOT = "https://www.omdbapi.com/"
CACHE_SCHEMA_VERSION = "v1"
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


@dataclass(slots=True)
class OmdbRatingResult:
    key: str
    title: str
    year: int | None
    rating: float | None
    status: str
    matched_title: str | None = None
    matched_year: str | None = None
    imdb_id: str | None = None
    language: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def lookup_omdb_ratings(
    items: list[dict[str, Any]],
    omdb_key: str | None,
    *,
    http_get: Callable[[dict[str, str]], dict[str, Any]] | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    results = []
    for item in items:
        key = str(item.get("key") or "")
        title = str(item.get("title") or "").strip()
        year = coerce_year(item.get("year"))
        if not omdb_key:
            results.append(OmdbRatingResult(key, title, year, None, "no_key").to_dict())
            continue
        cached = load_cached_rating(key, title, year, cache_dir=cache_dir)
        if cached is not None:
            results.append(cached)
            continue
        result = lookup_one_rating(key, title, year, omdb_key, http_get=http_get)
        if result.status in {"matched", "not_found"}:
            write_cached_rating(result, cache_dir=cache_dir)
        results.append(result.to_dict())
    return {"items": results}


def lookup_one_rating(
    key: str,
    title: str,
    year: int | None,
    omdb_key: str,
    *,
    http_get: Callable[[dict[str, str]], dict[str, Any]] | None = None,
) -> OmdbRatingResult:
    if not title:
        return OmdbRatingResult(key, title, year, None, "not_found")
    getter = http_get or omdb_http_get(omdb_key)
    try:
        for candidate in omdb_title_candidates(title):
            payload = getter(query_params({"t": candidate, "y": year}))
            status = omdb_error_status(payload)
            if status:
                if status == "not_found":
                    continue
                return OmdbRatingResult(key, title, year, None, status, error=str(payload.get("Error") or ""))
            result = result_from_omdb_payload(key, title, year, payload)
            if result is not None:
                return result

        for candidate in omdb_title_candidates(title):
            search_payload = getter(query_params({"s": candidate, "y": year, "type": "movie"}))
            status = omdb_error_status(search_payload)
            if status and status != "not_found":
                return OmdbRatingResult(key, title, year, None, status, error=str(search_payload.get("Error") or ""))
            match = best_search_match(candidate, year, search_payload.get("Search") if isinstance(search_payload, dict) else None)
            if match is not None and match.get("imdbID"):
                detail = getter(query_params({"i": str(match["imdbID"])}))
                detail_status = omdb_error_status(detail)
                if detail_status:
                    return OmdbRatingResult(key, title, year, None, detail_status, error=str(detail.get("Error") or ""))
                result = result_from_omdb_payload(key, title, year, detail)
                if result is not None:
                    return result
        return OmdbRatingResult(key, title, year, None, "not_found")
    except HTTPError as exc:
        if exc.code in {401, 403, 429}:
            return OmdbRatingResult(key, title, year, None, "api_limited", error="OMDB request limit or authorization failure.")
        return OmdbRatingResult(key, title, year, None, "error", error=str(exc))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return OmdbRatingResult(key, title, year, None, "error", error=str(exc))


def omdb_http_get(omdb_key: str) -> Callable[[dict[str, str]], dict[str, Any]]:
    def get(params: dict[str, str]) -> dict[str, Any]:
        url = f"{OMDB_API_ROOT}?{urlencode({'apikey': omdb_key, **params})}"
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "normal/1"})
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))

    return get


def query_params(values: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in values.items() if value not in {None, ""}}


def result_from_omdb_payload(key: str, title: str, year: int | None, payload: dict[str, Any]) -> OmdbRatingResult | None:
    if not isinstance(payload, dict) or payload.get("Response") != "True":
        return None
    raw_rating = str(payload.get("imdbRating") or "")
    rating = None if raw_rating in {"", "N/A"} else float(raw_rating)
    return OmdbRatingResult(
        key=key,
        title=title,
        year=year,
        rating=rating,
        status="matched",
        matched_title=str(payload.get("Title") or ""),
        matched_year=str(payload.get("Year") or ""),
        imdb_id=str(payload.get("imdbID") or ""),
        language=str(payload.get("Language") or "") or None,
    )


def omdb_error_status(payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict) or payload.get("Response") == "True":
        return None
    error = str(payload.get("Error") or "").casefold()
    if "request limit" in error or "invalid api key" in error or "api key" in error:
        return "api_limited"
    return "not_found"


def omdb_title_candidates(title: str) -> list[str]:
    return provider_title_candidates(title)


def clean_lookup_title(title: str) -> str:
    cleaned = re.sub(r"[._]+", " ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def punctuate_letter_number_title(title: str) -> str:
    replaced = re.sub(r"\b([A-Za-z])\s+(\d+)\b", r"\1-\2", title, count=1)
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
    seen = set()
    result = []
    for value in values:
        normalized = " ".join(str(value or "").split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def best_search_match(title: str, year: int | None, results: Any) -> dict[str, Any] | None:
    if not isinstance(results, list):
        return None
    candidates = []
    for item in results:
        if not isinstance(item, dict) or item.get("Type") not in {None, "movie"}:
            continue
        item_year = coerce_year(str(item.get("Year") or "")[:4])
        if year is not None and item_year != year:
            continue
        score = title_similarity(title, str(item.get("Title") or ""))
        if score >= 0.58:
            candidates.append((score, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def title_similarity(a: str, b: str) -> float:
    a_key = normalized_title_key(a)
    b_key = normalized_title_key(b)
    if not a_key or not b_key:
        return 0.0
    a_tokens = set(a_key.split())
    b_tokens = set(b_key.split())
    token_overlap = len(a_tokens & b_tokens) / max(len(a_tokens), len(b_tokens), 1)
    sequence = SequenceMatcher(None, a_key, b_key).ratio()
    return max(token_overlap, sequence)


def normalized_title_key(title: str) -> str:
    return title_similarity_key(title)


def coerce_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1800 <= year <= 2100 else None


def omdb_cache_dir() -> Path:
    return Path.home() / ".cache" / "normal" / "omdb_ratings" / CACHE_SCHEMA_VERSION


def cache_key(key: str, title: str, year: int | None) -> str:
    source = f"{key}\0{title}\0{year or ''}"
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:20]


def cache_path_for(key: str, title: str, year: int | None, *, cache_dir: Path | None = None) -> Path:
    root = cache_dir or omdb_cache_dir()
    return root / f"{cache_key(key, title, year)}.json"


def load_cached_rating(key: str, title: str, year: int | None, *, cache_dir: Path | None = None) -> dict[str, Any] | None:
    path = cache_path_for(key, title, year, cache_dir=cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("key") != key:
        return None
    return payload


def write_cached_rating(result: OmdbRatingResult, *, cache_dir: Path | None = None) -> None:
    path = cache_path_for(result.key, result.title, result.year, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result.to_dict(), indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(path)


LANGUAGE_CACHE_KEY = "original-language"


def primary_language(language: str | None) -> str | None:
    if not language:
        return None
    first = language.split(",")[0].strip().casefold()
    if first in {"", "n/a", "na", "none", "unknown"}:
        return None
    return first


def resolve_original_language(
    title: str,
    year: int | None,
    omdb_key: str | None,
    *,
    http_get: Callable[[dict[str, str]], dict[str, Any]] | None = None,
    cache_dir: Path | None = None,
) -> str | None:
    if not omdb_key or not title:
        return None
    cached = load_cached_rating(LANGUAGE_CACHE_KEY, title, year, cache_dir=cache_dir)
    if cached is not None and "language" in cached:
        if cached.get("status") == "matched":
            return primary_language(cached.get("language"))
        return None
    result = lookup_one_rating(LANGUAGE_CACHE_KEY, title, year, omdb_key, http_get=http_get)
    if result.status in {"matched", "not_found"}:
        write_cached_rating(result, cache_dir=cache_dir)
    if result.status == "matched":
        return primary_language(result.language)
    return None
