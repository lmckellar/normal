"""Take docs screenshots by hydrating the web UI from local dashboard objects."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

BASE_URL = "http://localhost:8765"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "assets"

MUSIC_SOURCE = Path("/mnt/media_storage/Music")
MOVIES_SOURCE = Path("/mnt/media_storage/Movies")

MUSIC_EXTENSIONS = {".flac", ".mp3", ".m4a", ".wav"}
MOVIE_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts", ".webm"}


def files_under(root: Path, extensions: set[str]) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in extensions and not path.name.startswith("._")
    )


def total_size(paths: list[Path]) -> int:
    size = 0
    for path in paths:
        try:
            size += path.stat().st_size
        except OSError:
            pass
    return size


def music_profile_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "mp3_high_quality"
    if suffix != ".flac":
        return "unknown_unreadable"
    text = str(path).lower()
    if re.search(r"(24[ -]?bit|24bit|24-)", text) and re.search(r"(96|192|88[._ -]?2|176[._ -]?4)", text):
        return "flac_24_96"
    if re.search(r"(24[ -]?bit|24bit|24-)", text):
        return "flac_24_44_1"
    return "flac_16_44_1"


def sample_rate_for(profile: str) -> str:
    if profile.endswith("_96"):
        return "96 kHz"
    if profile.endswith("_48"):
        return "48 kHz"
    if profile.startswith("flac"):
        return "44.1 kHz"
    return "unknown"


def build_music_cache() -> dict[str, object]:
    tracks = files_under(MUSIC_SOURCE, MUSIC_EXTENSIONS)
    artist_dirs = [path for path in MUSIC_SOURCE.iterdir() if path.is_dir()] if MUSIC_SOURCE.exists() else []
    album_dirs = [
        path
        for artist in artist_dirs
        for path in artist.iterdir()
        if path.is_dir()
    ]
    profiles = Counter(music_profile_for(path) for path in tracks)
    formats = Counter(path.suffix.lower().lstrip(".") or "unknown" for path in tracks)
    sample_rates = Counter(sample_rate_for(profile) for profile, count in profiles.items() for _ in range(count))
    histogram = {
        "track_count": len(tracks),
        "album_count": len(album_dirs),
        "artist_count": len(artist_dirs),
        "total_size_bytes": total_size(tracks),
        "profile_counts": dict(profiles),
        "format_counts": dict(formats),
        "sample_rate_counts": dict(sample_rates),
        "warning_count": profiles.get("unknown_unreadable", 0),
    }
    source = str(MUSIC_SOURCE)
    return {
        source: {
            "source_root": source,
            "histogram": histogram,
            "cached_at": "2026-04-30T00:00:00.000Z",
        }
    }


def movie_resolution_for(path: Path) -> str:
    text = str(path).lower()
    if re.search(r"(2160p|4k|uhd)", text):
        return "2160p"
    if "1080p" in text:
        return "1080p"
    if "720p" in text:
        return "720p"
    return "unknown"


def movie_profile_for(path: Path) -> str:
    text = str(path).lower()
    resolution = movie_resolution_for(path)
    if resolution == "2160p":
        if "remux" in text:
            return "4k_remux"
        if re.search(r"(web-dl|webrip|yts|galaxyrg|x265|hevc)", text):
            return "compressed_4k"
        return "4k_uhd"
    if resolution == "1080p":
        if re.search(r"(yts|ano?xmous|moviesbyrizzo|etrg|web-dl)", text):
            return "weak_1080p"
        if re.search(r"(x265|hevc|10bit|aac|afm72|tigole|silence)", text):
            return "compressed_1080p"
        return "1080p_uhd"
    if resolution == "720p":
        return "sd_low_quality"
    return "unclassified"


def risk_counts(paths: list[Path]) -> dict[str, int]:
    playback = 0
    visibility = 0
    for path in paths:
        text = str(path).lower()
        if re.search(r"(dts|truehd|atmos|remux|10bit|hevc|x265)", text):
            playback += 1
        if re.search(r"(sample|extras?|featurette|subs?|multi|dual|commentary|disc)", text):
            visibility += 1
    return {
        "playback_risk": playback,
        "indexing_visibility_risk": visibility,
    }


def bitrate_summary(paths: list[Path], *, audio: bool = False) -> dict[str, object]:
    count = max(len(paths), 1)
    if audio:
        mean = 384
        bins = [
            {"start_kbps": 150, "end_kbps": 299, "count": count // 4},
            {"start_kbps": 300, "end_kbps": 449, "count": count // 2},
            {"start_kbps": 450, "end_kbps": 899, "count": count - (count // 4) - (count // 2)},
        ]
        return {"mean": mean, "p10": 192, "p50": 320, "p90": 640, "p95": 768, "bins": bins}
    mean = 8200
    bins = [
        {"start_kbps": 0, "end_kbps": 3999, "count": count // 8},
        {"start_kbps": 4000, "end_kbps": 7999, "count": count // 3},
        {"start_kbps": 8000, "end_kbps": 11999, "count": count // 3},
        {"start_kbps": 12000, "end_kbps": 23999, "count": count - (count // 8) - (count // 3) - (count // 3)},
    ]
    return {"mean": mean, "p10": 3600, "p50": 7800, "p90": 16000, "p95": 22000, "bins": bins}


def build_movie_cache() -> dict[str, object]:
    movies = files_under(MOVIES_SOURCE, MOVIE_EXTENSIONS)
    profile_counts = Counter(movie_profile_for(path) for path in movies)
    resolution_counts = Counter(movie_resolution_for(path) for path in movies)
    source = str(MOVIES_SOURCE)
    histogram = {
        "movie_count": len(movies),
        "total_size_bytes": total_size(movies),
        "total_runtime_minutes": len(movies) * 105,
        "profile_counts": dict(profile_counts),
        "resolution_counts": dict(resolution_counts),
        "risk_counts": risk_counts(movies),
        "video_bitrate_kbps": bitrate_summary(movies),
        "audio_bitrate_kbps": bitrate_summary(movies, audio=True),
    }
    return {
        source: {
            "source_root": source,
            "histogram": histogram,
            "replacement_queue": {"source_root": source, "items": []},
            "cached_at": "2026-04-30T00:00:00.000Z",
        }
    }


def hydrate(page: Page, music_cache: dict[str, object], movie_cache: dict[str, object], theme: str) -> None:
    library_roots = {"music": str(MUSIC_SOURCE), "movies": str(MOVIES_SOURCE)}
    page.add_init_script(
        f"""(() => {{
          const musicCache = {json.dumps(music_cache)};
          const movieCache = {json.dumps(movie_cache)};
          const roots = {json.dumps(library_roots)};
          const theme = {json.dumps(theme)};
          localStorage.setItem('n_music_dashboard_cache', JSON.stringify(musicCache));
          localStorage.setItem('n_movie_dashboard_cache', JSON.stringify(movieCache));
          localStorage.setItem('n_library_roots', JSON.stringify(roots));
          localStorage.setItem('n_recent_libraries', JSON.stringify([
            {{ lane: 'music', source: roots.music }},
            {{ lane: 'movies', source: roots.movies }}
          ]));
          localStorage.setItem('n_theme', theme);
        }})()""",
    )


def render_dashboard(page: Page, lane: str, source: Path) -> None:
    page.evaluate(
        """([lane, source]) => {
          setLane(lane, { forceSource: source });
          if (lane === 'music') restoreCachedMusicDashboard(source);
          else restoreCachedMovieDashboard(source);
          setStatus(`Complete - ${source}`, 'idle');
          renderCurrentPage();
        }""",
        [lane, str(source)],
    )
    page.wait_for_timeout(400)


def take_shot(page: Page, name: str) -> None:
    path = OUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"saved {path}")


def capture(theme: str, lane: str, name: str, music_cache: dict[str, object], movie_cache: dict[str, object]) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        hydrate(page, music_cache, movie_cache, theme)
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        render_dashboard(page, lane, MUSIC_SOURCE if lane == "music" else MOVIES_SOURCE)
        page.wait_for_timeout(300)
        take_shot(page, name)
        browser.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    music_cache = build_music_cache()
    movie_cache = build_movie_cache()

    capture("default", "music", "music_dashboard_default", music_cache, movie_cache)
    capture("default", "movies", "movies_dashboard_default", music_cache, movie_cache)
    for theme in ("win95", "dark", "matrix", "sand"):
        capture(theme, "movies", f"movies_dashboard_{theme}", music_cache, movie_cache)


if __name__ == "__main__":
    main()
