from __future__ import annotations

import base64
import io
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image

from normal.models import WarningItem, utc_now_iso
from normal.movie_scan import discover_video_files


POSTER_FILENAMES = ("poster.jpg", "poster.png", "folder.jpg", "folder.png")
TARGET_POSTER_FILENAME = "poster.jpg"


@dataclass(slots=True)
class MoviePosterGapItem:
    movie_name: str
    folder_path: str


@dataclass(slots=True)
class MoviePosterPresentItem:
    movie_name: str
    folder_path: str
    filename: str
    image_path: str = ""
    file_size_bytes: int = 0
    width: int = 0
    height: int = 0
    mtime_ns: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MoviePosterReport:
    source_root: str
    generated_at: str
    present: list[MoviePosterPresentItem] = field(default_factory=list)
    missing: list[MoviePosterGapItem] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MoviePosterApplyResult:
    movie_name: str
    folder_path: str
    status: str
    source: str = ""
    message: str = ""
    file_size_bytes: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def scan_movie_posters(library_root: Path) -> MoviePosterReport:
    report = MoviePosterReport(
        source_root=str(library_root.resolve()),
        generated_at=utc_now_iso(),
    )
    try:
        video_files = discover_video_files(library_root)
    except (OSError, PermissionError) as exc:
        report.warnings.append(WarningItem(code="scan_error", message=str(exc)))
        return report

    # Group video files by parent folder.
    folder_videos: dict[Path, list[Path]] = {}
    for vf in video_files:
        folder_videos.setdefault(vf.parent, []).append(vf)

    # Build entries: one per folder for dedicated movie folders, one per video
    # file for flat folders that contain multiple video files.
    entries: list[tuple[str, Path, list[Path]]] = []
    for folder, videos in folder_videos.items():
        if len(videos) == 1:
            entries.append((folder.name, folder, videos))
        else:
            # Multiple videos share a folder — treat each video as its own entry.
            for vf in videos:
                entries.append((vf.stem, folder, [vf]))

    entries.sort(key=lambda item: item[0].lower())

    for movie_name, folder, videos in entries:
        found_filename: str | None = None
        try:
            for fname in POSTER_FILENAMES:
                if (folder / fname).exists():
                    found_filename = fname
                    break
            if found_filename is None:
                # Check stem-based names: {stem}-poster.jpg, {stem}.jpg
                for vf in videos:
                    for stem_name in (f"{vf.stem}-poster.jpg", f"{vf.stem}.jpg"):
                        if (folder / stem_name).exists():
                            found_filename = stem_name
                            break
                    if found_filename:
                        break
        except PermissionError:
            report.warnings.append(WarningItem(
                code="permission_denied",
                message=f"cannot read {folder}",
                path=str(folder),
            ))
            continue

        if found_filename:
            img_path = folder / found_filename
            stat = img_path.stat()
            width = height = 0
            try:
                with Image.open(img_path) as img:
                    width, height = img.size
            except Exception:
                pass
            report.present.append(MoviePosterPresentItem(
                movie_name=movie_name,
                folder_path=str(folder),
                filename=found_filename,
                image_path=str(img_path),
                file_size_bytes=stat.st_size,
                width=width,
                height=height,
                mtime_ns=stat.st_mtime_ns,
            ))
        else:
            report.missing.append(MoviePosterGapItem(
                movie_name=movie_name,
                folder_path=str(folder),
            ))

    return report


def apply_movie_poster(
    source_root: Path,
    folder_path: str,
    movie_name: str,
    image_bytes: bytes,
    source: str,
) -> MoviePosterApplyResult:
    folder = Path(folder_path).resolve()
    try:
        folder.relative_to(source_root.resolve())
    except ValueError:
        return MoviePosterApplyResult(movie_name=movie_name, folder_path=folder_path, status="skipped", source=source, message="outside_source")

    if not folder.is_dir():
        return MoviePosterApplyResult(movie_name=movie_name, folder_path=folder_path, status="skipped", source=source, message="folder_missing")

    target = folder / TARGET_POSTER_FILENAME
    try:
        target.write_bytes(image_bytes)
        stat = target.stat()
        width = height = 0
        try:
            with Image.open(target) as img:
                width, height = img.size
        except Exception:
            pass
        return MoviePosterApplyResult(
            movie_name=movie_name,
            folder_path=folder_path,
            status="written",
            source=source,
            file_size_bytes=stat.st_size,
            width=width,
            height=height,
        )
    except Exception as exc:
        return MoviePosterApplyResult(movie_name=movie_name, folder_path=folder_path, status="failed", source=source, message=str(exc))


def apply_movie_posters(
    source_root: Path,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    results = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        movie_name = str(candidate.get("movie_name") or "")
        folder_path = str(candidate.get("folder_path") or "")
        image_url = str(candidate.get("image_url") or "")
        source = str(candidate.get("source") or "drop")

        if not movie_name or not folder_path or not image_url:
            results.append(MoviePosterApplyResult(
                movie_name=movie_name,
                folder_path=folder_path,
                status="skipped",
                source=source,
                message="missing_fields",
            ).to_dict())
            continue

        image_bytes = _resolve_poster_image(image_url)
        if image_bytes is None:
            results.append(MoviePosterApplyResult(
                movie_name=movie_name,
                folder_path=folder_path,
                status="skipped",
                source=source,
                message="image_resolution_failed",
            ).to_dict())
            continue

        result = apply_movie_poster(source_root, folder_path, movie_name, image_bytes, source)
        results.append(result.to_dict())

    return {
        "source_root": str(source_root),
        "results": results,
    }


def _resolve_poster_image(image_url: str) -> bytes | None:
    if image_url.startswith("data:image/"):
        return _resolve_data_url(image_url)
    if image_url.startswith("https://"):
        return _resolve_remote_url(image_url)
    return None


def _resolve_data_url(data_url: str) -> bytes | None:
    header, sep, encoded = data_url.partition(",")
    if sep != "," or not header.startswith("data:image/") or ";base64" not in header:
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=92)
            return buf.getvalue()
    except Exception:
        return None


def _resolve_remote_url(url: str) -> bytes | None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "normal/0.1 local artwork review"})
        with urllib.request.urlopen(request, timeout=15) as response:
            data = response.read()
        with Image.open(io.BytesIO(data)) as img:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=92)
            return buf.getvalue()
    except Exception:
        return None
