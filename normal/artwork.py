from __future__ import annotations

import base64
import colorsys
import html
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from normal.models import WarningItem, utc_now_iso


ARTWORK_FILENAMES = ("artist.jpg", "artist.png", "folder.jpg")
ALBUM_ARTWORK_FILENAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png")
TARGET_FILENAME = "artist.jpg"
JELLYFIN_COMPAT_FILENAME = "folder.jpg"
PROVENANCE_FILENAME = "artist.normal-artwork.json"
LASTFM_API_BASE = "http://ws.audioscrobbler.com/2.0/"
COMMONS_API_BASE = "https://commons.wikimedia.org/w/api.php"
BING_IMAGE_SEARCH_BASE = "https://www.bing.com/images/search"
PLACEHOLDER_SIZE = 500
LASTFM_SIZE_PREFERENCE = ["mega", "extralarge", "large", "medium", "small"]
ALLOWED_REMOTE_IMAGE_HOSTS = {"upload.wikimedia.org"}
WEB_SEARCH_BASE = "https://duckduckgo.com/html/"
EXCLUDED_WEB_HOST_PARTS = (
    "facebook.com",
    "instagram.com",
    "spotify.com",
    "youtube.com",
    "youtu.be",
    "reddit.com",
    "last.fm",
)

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
_LEADING_ARTICLES = {"the", "a", "an"}


@dataclass(slots=True)
class ArtworkGapItem:
    artist_name: str
    folder_path: str


@dataclass(slots=True)
class ArtworkPresentItem:
    artist_name: str
    folder_path: str
    filename: str
    image_path: str = ""
    source: str = "local"
    file_size_bytes: int = 0
    width: int = 0
    height: int = 0
    mtime_ns: int = 0


@dataclass(slots=True)
class ArtworkReport:
    source_root: str
    generated_at: str
    present: list[ArtworkPresentItem] = field(default_factory=list)
    missing: list[ArtworkGapItem] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArtworkResolution:
    gap: ArtworkGapItem
    source: str
    image_bytes: bytes | None
    title: str = ""
    page_url: str = ""


@dataclass(slots=True)
class ArtworkApplyResult:
    artist_name: str
    folder_path: str
    status: str
    source: str = ""
    message: str = ""


@dataclass(slots=True)
class ArtworkCandidate:
    artist_name: str
    folder_path: str
    source: str
    title: str
    preview_url: str
    image_url: str
    page_url: str
    width: int = 0
    height: int = 0
    mime: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scan_artist_artwork(library_root: Path, jellyfin_artists_root: Path | None = None) -> ArtworkReport:
    report = ArtworkReport(
        source_root=str(library_root.resolve()),
        generated_at=utc_now_iso(),
    )
    jellyfin_artists = load_jellyfin_artist_artwork(jellyfin_artists_root)
    try:
        entries = sorted(library_root.iterdir(), key=lambda e: e.name.lower())
    except PermissionError as exc:
        report.warnings.append(WarningItem(code="permission_denied", message=str(exc)))
        return report

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        artist_name = entry.name
        found = None
        try:
            for fname in ARTWORK_FILENAMES:
                if (entry / fname).exists():
                    found = fname
                    break
        except PermissionError:
            report.warnings.append(WarningItem(
                code="permission_denied",
                message=f"cannot read {entry}",
                path=str(entry),
            ))
            continue
        if found:
            img_path = entry / found
            provenance = read_artwork_provenance(entry)
            if not provenance and found == TARGET_FILENAME:
                provenance = infer_artwork_provenance(entry, img_path)
            stat = img_path.stat()
            size_bytes = stat.st_size
            width = height = 0
            try:
                with Image.open(img_path) as img:
                    width, height = img.size
            except Exception:
                pass
            report.present.append(ArtworkPresentItem(
                artist_name=artist_name,
                folder_path=str(entry),
                filename=found,
                image_path=str(img_path),
                source=provenance.get("source", "local") if found == TARGET_FILENAME else "local",
                file_size_bytes=size_bytes,
                width=width,
                height=height,
                mtime_ns=stat.st_mtime_ns,
            ))
        elif artist_key(artist_name) in jellyfin_artists:
            img_path = jellyfin_artists[artist_key(artist_name)]
            stat = img_path.stat()
            size_bytes = stat.st_size
            width = height = 0
            try:
                with Image.open(img_path) as img:
                    width, height = img.size
            except Exception:
                pass
            report.present.append(ArtworkPresentItem(
                artist_name=artist_name,
                folder_path=str(entry),
                filename=img_path.name,
                image_path=str(img_path),
                source="jellyfin",
                file_size_bytes=size_bytes,
                width=width,
                height=height,
                mtime_ns=stat.st_mtime_ns,
            ))
        else:
            report.missing.append(ArtworkGapItem(
                artist_name=artist_name,
                folder_path=str(entry),
            ))
    return report


def artist_key(name: str) -> str:
    return " ".join(name.casefold().split())


def default_jellyfin_artists_roots() -> list[Path]:
    home = Path.home()
    return [
        home / "mediastack/config/jellyfin/data/metadata/artists",
        home / ".local/share/jellyfin/metadata/artists",
        Path("/var/lib/jellyfin/metadata/artists"),
        Path("/config/metadata/artists"),
    ]


def load_jellyfin_artist_artwork(jellyfin_artists_root: Path | None = None) -> dict[str, Path]:
    roots = [jellyfin_artists_root] if jellyfin_artists_root else default_jellyfin_artists_roots()
    artwork: dict[str, Path] = {}
    for root in roots:
        if root is None or not root.is_dir():
            continue
        try:
            entries = sorted(root.iterdir(), key=lambda e: e.name.lower())
        except PermissionError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            for fname in ARTWORK_FILENAMES:
                candidate = entry / fname
                if candidate.is_file():
                    artwork.setdefault(artist_key(entry.name), candidate)
                    break
    return artwork


def read_artwork_provenance(artist_folder: Path) -> dict[str, Any]:
    path = artist_folder / PROVENANCE_FILENAME
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    source = payload.get("source")
    if source not in {"album", "web", "wikimedia", "image-search", "drop", "jellyfin", "placeholder"}:
        return {}
    return payload


def write_artwork_provenance(artist_folder: Path, resolution: ArtworkResolution) -> None:
    if resolution.source == "local":
        return
    payload = {
        "source": resolution.source,
        "title": resolution.title,
        "page_url": resolution.page_url,
        "written_at": utc_now_iso(),
    }
    try:
        (artist_folder / PROVENANCE_FILENAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def infer_artwork_provenance(artist_folder: Path, image_path: Path) -> dict[str, Any]:
    try:
        with Image.open(image_path) as current:
            current_size = current.size
    except Exception:
        return {}
    gap = ArtworkGapItem(artist_name=artist_folder.name, folder_path=str(artist_folder))
    for candidate in find_album_artwork_candidates(gap):
        candidate_path = Path(candidate.image_url)
        try:
            with Image.open(candidate_path) as candidate_image:
                if candidate_image.size == current_size:
                    return {"source": "album", "title": candidate.title, "page_url": candidate.image_url}
        except Exception:
            continue
    return {}


def find_album_artwork_candidates(gap: ArtworkGapItem, limit: int = 6) -> list[ArtworkCandidate]:
    artist_folder = Path(gap.folder_path)
    candidates: list[ArtworkCandidate] = []
    if not artist_folder.is_dir():
        return candidates
    try:
        album_dirs = sorted((item for item in artist_folder.iterdir() if item.is_dir()), key=lambda p: p.name.lower())
    except PermissionError:
        return candidates
    for album_dir in album_dirs:
        for fname in ALBUM_ARTWORK_FILENAMES:
            image_path = album_dir / fname
            if not image_path.is_file():
                continue
            width = height = 0
            mime = ""
            try:
                with Image.open(image_path) as img:
                    width, height = img.size
                    mime = Image.MIME.get(img.format or "", "")
            except Exception:
                pass
            candidates.append(ArtworkCandidate(
                artist_name=gap.artist_name,
                folder_path=gap.folder_path,
                source="album",
                title=f"{album_dir.name}/{fname}",
                preview_url=str(image_path),
                image_url=str(image_path),
                page_url="",
                width=width,
                height=height,
                mime=mime,
            ))
            if len(candidates) >= limit:
                return candidates
    return candidates


def find_web_artist_candidates(gap: ArtworkGapItem, limit: int = 8) -> list[ArtworkCandidate]:
    page_urls = search_artist_pages(gap.artist_name, limit=6)
    candidates: list[ArtworkCandidate] = []
    seen: set[str] = set()
    for page_url in page_urls:
        for candidate in extract_page_image_candidates(gap, page_url, limit=4):
            if candidate.image_url in seen:
                continue
            seen.add(candidate.image_url)
            candidates.append(candidate)
            if len(candidates) >= limit:
                return candidates
    return candidates


def find_image_search_artist_candidates(gap: ArtworkGapItem, limit: int = 8, offset: int = 0) -> list[ArtworkCandidate]:
    query = f"{gap.artist_name} band"
    first = max(offset, 0) + 1
    url = BING_IMAGE_SEARCH_BASE + "?" + urllib.parse.urlencode({"q": query, "first": str(first)})
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 normal local artwork review"})
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read().decode("utf-8", "ignore")
    except Exception:
        return []
    return extract_bing_image_search_candidates(gap, payload, limit=limit)


def extract_bing_image_search_candidates(gap: ArtworkGapItem, payload: str, limit: int = 8) -> list[ArtworkCandidate]:
    candidates: list[ArtworkCandidate] = []
    seen: set[str] = set()
    for raw_metadata in re.findall(r'class="iusc"[^>]+m="([^"]+)"', payload):
        try:
            metadata = json.loads(html.unescape(raw_metadata))
        except json.JSONDecodeError:
            continue
        image_url = str(metadata.get("murl") or "")
        if image_url in seen:
            continue
        if not is_http_image_url(image_url):
            continue
        if is_excluded_web_host(image_url):
            continue
        if not has_reasonable_image_size_hint(image_url):
            continue
        page_url = str(metadata.get("purl") or "")
        if page_url and is_excluded_web_host(page_url):
            continue
        seen.add(image_url)
        preview_url = str(metadata.get("turl") or image_url)
        candidates.append(ArtworkCandidate(
            artist_name=gap.artist_name,
            folder_path=gap.folder_path,
            source="image-search",
            title=str(metadata.get("t") or urllib.parse.urlparse(page_url).hostname or "image search"),
            preview_url=preview_url,
            image_url=image_url,
            page_url=page_url,
        ))
        if len(candidates) >= limit:
            return candidates
    return candidates


def search_artist_pages(artist_name: str, limit: int = 6) -> list[str]:
    query = f'"{artist_name}" official artist photo'
    url = WEB_SEARCH_BASE + "?" + urllib.parse.urlencode({"q": query})
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 normal local artwork review"})
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = response.read().decode("utf-8", "ignore")
    except Exception:
        return []
    links: list[str] = []
    for raw_href in re.findall(r'class="result__a"[^>]*href="([^"]+)"', payload):
        href = html.unescape(raw_href)
        parsed = urllib.parse.urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com"):
            qs = urllib.parse.parse_qs(parsed.query)
            href = qs.get("uddg", [href])[0]
        if not is_candidate_page_url(href, artist_name):
            continue
        if href not in links:
            links.append(href)
            if len(links) >= limit:
                return links
    return links


def is_candidate_page_url(url: str, artist_name: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if is_excluded_web_host(url):
        return False
    host = parsed.hostname.casefold()
    compact_artist = "".join(re_tokens(artist_name))
    compact_host = re.sub(r"[^a-z0-9]+", "", host)
    compact_url = re.sub(r"[^a-z0-9]+", "", (host + parsed.path).casefold())
    return compact_artist in compact_host or "official" in compact_url


def is_excluded_web_host(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname
    if not host:
        return False
    return any(part in host.casefold() for part in EXCLUDED_WEB_HOST_PARTS)


def extract_page_image_candidates(gap: ArtworkGapItem, page_url: str, limit: int = 4) -> list[ArtworkCandidate]:
    try:
        request = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0 normal local artwork review"})
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read().decode("utf-8", "ignore")
    except Exception:
        return []
    urls = extract_image_urls(payload, page_url)
    candidates: list[ArtworkCandidate] = []
    for image_url in urls:
        if not is_http_image_url(image_url):
            continue
        if not has_reasonable_image_size_hint(image_url):
            continue
        candidates.append(ArtworkCandidate(
            artist_name=gap.artist_name,
            folder_path=gap.folder_path,
            source="web",
            title=urllib.parse.urlparse(page_url).hostname or page_url,
            preview_url=image_url,
            image_url=image_url,
            page_url=page_url,
        ))
        if len(candidates) >= limit:
            return candidates
    return candidates


def extract_image_urls(payload: str, page_url: str) -> list[str]:
    urls: list[str] = []
    patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']',
        r'<img[^>]+src=["\']([^"\']+)["\']',
        r'https?:\\?/\\?/[^"\\\s<>]+?\.(?:jpg|jpeg|png|webp)(?:[^"\\\s<>]*)',
    ]
    for pattern in patterns:
        for raw in re.findall(pattern, payload, flags=re.IGNORECASE):
            cleaned = html.unescape(raw).replace("\\/", "/")
            absolute = urllib.parse.urljoin(page_url, cleaned)
            if absolute not in urls:
                urls.append(absolute)
    return urls


def is_http_image_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    path = parsed.path.casefold()
    return any(ext in path for ext in (".jpg", ".jpeg", ".png", ".webp"))


def has_reasonable_image_size_hint(url: str, minimum: int = 300) -> bool:
    width_match = re.search(r"(?:^|[/?&,])w[_=](\d+)", url)
    height_match = re.search(r"(?:^|[/?&,])h[_=](\d+)", url)
    if not width_match and not height_match:
        return True
    width = int(width_match.group(1)) if width_match else minimum
    height = int(height_match.group(1)) if height_match else minimum
    return width >= minimum and height >= minimum


def search_wikimedia_artist_candidates(gap: ArtworkGapItem, limit: int = 8) -> list[ArtworkCandidate]:
    artist_tokens = [token for token in re_tokens(gap.artist_name) if token not in {"the", "and"}]
    params = {
        "action": "query",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": f"\"{gap.artist_name}\"",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": "500",
        "format": "json",
    }
    url = COMMONS_API_BASE + "?" + urllib.parse.urlencode(params)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "normal/0.1 local artwork review"})
        with urllib.request.urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    pages = (payload.get("query") or {}).get("pages") or {}
    candidates: list[ArtworkCandidate] = []
    for page in pages.values():
        title = str(page.get("title") or "")
        title_tokens = set(re_tokens(title))
        if artist_tokens and not all(token in title_tokens for token in artist_tokens):
            continue
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = str(info.get("mime") or "")
        if not mime.startswith("image/"):
            continue
        image_url = str(info.get("url") or "")
        preview_url = str(info.get("thumburl") or image_url)
        if not image_url or urlparse(image_url).hostname not in ALLOWED_REMOTE_IMAGE_HOSTS:
            continue
        candidates.append(ArtworkCandidate(
            artist_name=gap.artist_name,
            folder_path=gap.folder_path,
            source="wikimedia",
            title=title.removeprefix("File:"),
            preview_url=preview_url,
            image_url=image_url,
            page_url=f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            mime=mime,
        ))
    return candidates


def re_tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^\w]+", value.casefold()) if token]


def fetch_lastfm_artist_image(artist_name: str, api_key: str) -> bytes | None:
    params = {
        "method": "artist.getinfo",
        "artist": artist_name,
        "api_key": api_key,
        "format": "json",
    }
    url = LASTFM_API_BASE + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if "error" in data:
        return None

    try:
        images = data["artist"]["image"]
    except (KeyError, TypeError):
        return None

    image_by_size = {img.get("size"): img.get("#text", "") for img in images}
    image_url = None
    for size in LASTFM_SIZE_PREFERENCE:
        candidate = image_by_size.get(size, "")
        if candidate:
            image_url = candidate
            break

    if not image_url:
        return None

    try:
        with urllib.request.urlopen(image_url, timeout=10) as resp:
            return resp.read()
    except Exception:
        return None


def _artist_color(artist_name: str) -> tuple[int, int, int]:
    digest = int(hashlib.md5(artist_name.encode("utf-8")).hexdigest(), 16)
    hue = (digest % 360) / 360.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.42)
    return (int(r * 255), int(g * 255), int(b * 255))


def _artist_initials(artist_name: str) -> str:
    words = artist_name.split()
    if not words:
        return "?"
    filtered = [w for w in words if w.lower() not in _LEADING_ARTICLES] if len(words) > 1 else words
    if not filtered:
        filtered = words
    initials = "".join(w[0].upper() for w in filtered[:3] if w and w[0].isalpha())
    return initials or "?"


def generate_placeholder_image(artist_name: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    bg = _artist_color(artist_name)
    img = Image.new("RGB", (PLACEHOLDER_SIZE, PLACEHOLDER_SIZE), color=bg)
    draw = ImageDraw.Draw(img)
    initials = _artist_initials(artist_name)

    font = None
    for font_path in _FONT_PATHS:
        try:
            font = ImageFont.truetype(font_path, size=160)
            break
        except (OSError, IOError):
            continue

    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), initials, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (PLACEHOLDER_SIZE - text_w) / 2 - bbox[0]
    y = (PLACEHOLDER_SIZE - text_h) / 2 - bbox[1]
    draw.text((x, y), initials, fill=(255, 255, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def resolve_gap(
    gap: ArtworkGapItem,
    strategy: str,
    lastfm_api_key: str | None,
) -> ArtworkResolution:
    if strategy == "placeholder_only":
        return ArtworkResolution(gap=gap, source="placeholder", image_bytes=generate_placeholder_image(gap.artist_name), title="generated placeholder")

    if strategy == "fetch_only":
        if not lastfm_api_key:
            return ArtworkResolution(gap=gap, source="none", image_bytes=None)
        image_bytes = fetch_lastfm_artist_image(gap.artist_name, lastfm_api_key)
        if image_bytes:
            return ArtworkResolution(gap=gap, source="lastfm", image_bytes=image_bytes)
        return ArtworkResolution(gap=gap, source="none", image_bytes=None)

    # fetch_or_placeholder
    if lastfm_api_key:
        image_bytes = fetch_lastfm_artist_image(gap.artist_name, lastfm_api_key)
        if image_bytes:
            return ArtworkResolution(gap=gap, source="lastfm", image_bytes=image_bytes)
    return ArtworkResolution(gap=gap, source="placeholder", image_bytes=generate_placeholder_image(gap.artist_name))


def resolve_cached_artwork(item: ArtworkPresentItem) -> ArtworkResolution:
    image_path = Path(item.image_path or (str(Path(item.folder_path) / item.filename)))
    gap = ArtworkGapItem(artist_name=item.artist_name, folder_path=item.folder_path)
    try:
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=92)
            return ArtworkResolution(gap=gap, source=item.source, image_bytes=buf.getvalue(), title=item.filename, page_url=item.image_path)
    except Exception:
        return ArtworkResolution(gap=gap, source=item.source, image_bytes=None)


def resolve_file_artwork(gap: ArtworkGapItem, image_path: str, source: str, title: str = "") -> ArtworkResolution:
    path = Path(image_path)
    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=92)
            return ArtworkResolution(gap=gap, source=source, image_bytes=buf.getvalue(), title=title or Path(image_path).name, page_url=image_path)
    except Exception:
        return ArtworkResolution(gap=gap, source=source, image_bytes=None)


def resolve_remote_artwork(
    gap: ArtworkGapItem,
    image_url: str,
    source: str,
    allowed_hosts: set[str] | None = None,
    title: str = "",
    page_url: str = "",
) -> ArtworkResolution:
    if allowed_hosts is None:
        allowed_hosts = ALLOWED_REMOTE_IMAGE_HOSTS
    parsed = urlparse(image_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return ArtworkResolution(gap=gap, source=source, image_bytes=None)
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        return ArtworkResolution(gap=gap, source=source, image_bytes=None)
    try:
        request = urllib.request.Request(image_url, headers={"User-Agent": "normal/0.1 local artwork review"})
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read()
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=92)
            return ArtworkResolution(gap=gap, source=source, image_bytes=buf.getvalue(), title=title, page_url=page_url)
    except Exception:
        return ArtworkResolution(gap=gap, source=source, image_bytes=None)


def resolve_data_url_artwork(
    gap: ArtworkGapItem,
    data_url: str,
    source: str = "drop",
    title: str = "",
) -> ArtworkResolution:
    header, sep, encoded = data_url.partition(",")
    if sep != "," or not header.startswith("data:image/") or ";base64" not in header:
        return ArtworkResolution(gap=gap, source=source, image_bytes=None)
    try:
        data = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=92)
            return ArtworkResolution(gap=gap, source=source, image_bytes=buf.getvalue(), title=title, page_url="dropped image")
    except Exception:
        return ArtworkResolution(gap=gap, source=source, image_bytes=None)


def apply_artwork(
    resolutions: list[ArtworkResolution],
    dry_run: bool = False,
    overwrite: bool = False,
) -> list[ArtworkApplyResult]:
    results: list[ArtworkApplyResult] = []
    for resolution in resolutions:
        folder = Path(resolution.gap.folder_path)
        target = folder / TARGET_FILENAME
        artist_name = resolution.gap.artist_name
        folder_path = resolution.gap.folder_path

        if resolution.image_bytes is None:
            results.append(ArtworkApplyResult(artist_name=artist_name, folder_path=folder_path, status="skipped", source=resolution.source, message=f"no image resolved (source={resolution.source})"))
            continue
        if target.exists() and not overwrite:
            results.append(ArtworkApplyResult(artist_name=artist_name, folder_path=folder_path, status="skipped", source=resolution.source, message="artist.jpg already exists"))
            continue
        if dry_run:
            results.append(ArtworkApplyResult(artist_name=artist_name, folder_path=folder_path, status="skipped", source=resolution.source, message="dry_run"))
            continue
        if not folder.is_dir():
            results.append(ArtworkApplyResult(artist_name=artist_name, folder_path=folder_path, status="failed", source=resolution.source, message="folder does not exist"))
            continue
        try:
            target.write_bytes(resolution.image_bytes)
            (folder / JELLYFIN_COMPAT_FILENAME).write_bytes(resolution.image_bytes)
            write_artwork_provenance(folder, resolution)
            results.append(ArtworkApplyResult(artist_name=artist_name, folder_path=folder_path, status="written", source=resolution.source))
        except OSError as exc:
            results.append(ArtworkApplyResult(artist_name=artist_name, folder_path=folder_path, status="failed", source=resolution.source, message=str(exc)))
    return results


def backfill_jellyfin_artist_artwork(library_root: Path) -> dict[str, Any]:
    written: list[str] = []
    skipped: list[dict[str, str]] = []
    try:
        entries = sorted(library_root.iterdir(), key=lambda e: e.name.lower())
    except PermissionError as exc:
        return {"source_root": str(library_root), "written": written, "skipped": [{"path": str(library_root), "reason": str(exc)}]}

    for entry in entries:
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        source = entry / TARGET_FILENAME
        target = entry / JELLYFIN_COMPAT_FILENAME
        if not source.is_file():
            skipped.append({"path": str(entry), "reason": "missing_artist_jpg"})
            continue
        try:
            data = source.read_bytes()
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
            target.write_bytes(data)
            written.append(str(target))
        except Exception as exc:
            skipped.append({"path": str(entry), "reason": str(exc)})
    return {"source_root": str(library_root), "written": written, "skipped": skipped}


def sync_jellyfin_artist_metadata_artwork(
    library_root: Path,
    jellyfin_artists_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    roots = [jellyfin_artists_root] if jellyfin_artists_root else default_jellyfin_artists_roots()
    metadata_root = next((root for root in roots if root is not None and root.is_dir()), None)
    if metadata_root is None:
        return {
            "source_root": str(library_root),
            "jellyfin_artists_root": "",
            "written": [],
            "backed_up": [],
            "skipped": [{"path": str(library_root), "reason": "jellyfin_artists_root_not_found"}],
        }

    try:
        metadata_dirs = [entry for entry in metadata_root.iterdir() if entry.is_dir() and not entry.name.startswith(".")]
    except PermissionError as exc:
        return {
            "source_root": str(library_root),
            "jellyfin_artists_root": str(metadata_root),
            "written": [],
            "backed_up": [],
            "skipped": [{"path": str(metadata_root), "reason": str(exc)}],
        }

    metadata_by_key = {artist_key(entry.name): entry for entry in metadata_dirs}
    backup_root = metadata_root / ".normal-backups"
    written: list[str] = []
    backed_up: list[str] = []
    skipped: list[dict[str, str]] = []

    try:
        artist_dirs = sorted(library_root.iterdir(), key=lambda e: e.name.lower())
    except PermissionError as exc:
        return {
            "source_root": str(library_root),
            "jellyfin_artists_root": str(metadata_root),
            "written": written,
            "backed_up": backed_up,
            "skipped": [{"path": str(library_root), "reason": str(exc)}],
        }

    for artist_dir in artist_dirs:
        if not artist_dir.is_dir() or artist_dir.name.startswith("."):
            continue
        source = artist_dir / JELLYFIN_COMPAT_FILENAME
        if not source.is_file():
            skipped.append({"path": str(artist_dir), "reason": "missing_folder_jpg"})
            continue
        metadata_dir = metadata_by_key.get(artist_key(artist_dir.name))
        if metadata_dir is None:
            skipped.append({"path": str(artist_dir), "reason": "missing_jellyfin_metadata_artist"})
            continue
        target = metadata_dir / JELLYFIN_COMPAT_FILENAME
        try:
            source_bytes = source.read_bytes()
            with Image.open(io.BytesIO(source_bytes)) as img:
                img.verify()
            if target.is_file() and target.read_bytes() == source_bytes:
                skipped.append({"path": str(target), "reason": "already_in_sync"})
                continue
            if dry_run:
                written.append(str(target))
                continue
            if target.is_file():
                backup_dir = backup_root / metadata_dir.name
                backup_dir.mkdir(parents=True, exist_ok=True)
                backup_path = backup_dir / f"folder.{target.stat().st_mtime_ns}.jpg"
                backup_path.write_bytes(target.read_bytes())
                backed_up.append(str(backup_path))
            target.write_bytes(source_bytes)
            written.append(str(target))
        except Exception as exc:
            skipped.append({"path": str(artist_dir), "reason": str(exc)})

    return {
        "source_root": str(library_root),
        "jellyfin_artists_root": str(metadata_root),
        "written": written,
        "backed_up": backed_up,
        "skipped": skipped,
    }
