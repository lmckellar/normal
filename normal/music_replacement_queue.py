from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any

from normal.models import utc_now_iso
from normal.music_profile import SUPPORTED_EXTENSIONS


QUEUE_VERSION = 1
STRICT_WEAK_LABELS = {"mp3_trash", "unknown_unreadable"}
SAFE_MUSIC_SIDECAR_EXTENSIONS = {
    ".cue",
    ".jpg",
    ".jpeg",
    ".log",
    ".m3u",
    ".m3u8",
    ".nfo",
    ".png",
    ".txt",
    ".url",
    ".webp",
    ".xml",
}


@dataclass(slots=True)
class MusicReplacementQueueItem:
    item_id: str
    source_root: str
    album_artist: str | None
    artist: str | None
    album: str | None
    album_key: str
    original_path: str
    original_profile_label: str
    bitrate_kbps: int | None
    format: str | None
    file_size_bytes: int | None
    queued_at: str
    status: str = "pending"
    deleted_at: str | None = None
    completed_at: str | None = None
    completed_by_path: str | None = None


def default_queue_path() -> Path:
    return Path.home() / ".local" / "share" / "normal" / "music-replacement-queue.json"


def album_identity_key(album_artist: str | None, artist: str | None, album: str | None) -> str:
    a = album_artist or artist or ""
    b = album or ""
    return " ".join(f"{a}::{b}".casefold().split())


def album_identity_key_from_path(path: Path) -> str:
    return " ".join(str(path.parent).casefold().split())


def is_strict_weak_label(label: str | None) -> bool:
    return label in STRICT_WEAK_LABELS


def load_queue(state_path: Path | None = None) -> dict[str, Any]:
    path = state_path or default_queue_path()
    if not path.exists():
        return {"version": QUEUE_VERSION, "items": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": QUEUE_VERSION, "items": []}
    if not isinstance(payload, dict):
        return {"version": QUEUE_VERSION, "items": []}
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    normalized_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") == "pending" and item.get("deleted_at"):
            item = {**item, "status": "deleted"}
        normalized_items.append(item)
    return {"version": QUEUE_VERSION, "items": normalized_items}


def save_queue(payload: dict[str, Any], state_path: Path | None = None) -> None:
    path = state_path or default_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps({"version": QUEUE_VERSION, "items": payload.get("items", [])}, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def queue_for_source(source_root: Path, state_path: Path | None = None) -> dict[str, Any]:
    source = str(source_root.resolve())
    payload = load_queue(state_path)
    return {
        "source_root": source,
        "generated_at": utc_now_iso(),
        "items": [item for item in payload["items"] if item.get("source_root") == source],
    }


def extract_album_identity(raw_item: dict[str, Any], path: Path) -> tuple[str | None, str | None, str | None, str]:
    facts = raw_item.get("facts") if isinstance(raw_item.get("facts"), dict) else {}
    album_artist = facts.get("album_artist") or None
    artist = facts.get("artist") or None
    album = facts.get("album") or None
    if album_artist or artist or album:
        key = album_identity_key(album_artist, artist, album)
    else:
        key = album_identity_key_from_path(path)
    return album_artist, artist, album, key


def add_profile_items_to_queue(
    source_root: Path,
    raw_items: list[Any],
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    payload = load_queue(state_path)
    existing_by_id = {str(item.get("item_id")): item for item in payload["items"]}
    added: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            skipped.append({"reason": "invalid_item"})
            continue
        label = str((raw_item.get("profile") or {}).get("label") or "")
        if not is_strict_weak_label(label):
            skipped.append({"path": str(raw_item.get("path") or ""), "reason": "not_strict_weak"})
            continue
        path = Path(str(raw_item.get("path") or "")).expanduser().resolve()
        try:
            path.relative_to(source)
        except ValueError:
            skipped.append({"path": str(path), "reason": "outside_source"})
            continue

        album_artist, artist, album, key = extract_album_identity(raw_item, path)
        item = build_queue_item(source, path, raw_item, label, album_artist, artist, album, key)
        existing = existing_by_id.get(item.item_id)
        if existing is None:
            payload["items"].append(asdict(item))
            existing_by_id[item.item_id] = payload["items"][-1]
            added.append(payload["items"][-1])
        else:
            existing["status"] = "pending"
            existing["deleted_at"] = None
            existing["completed_at"] = None
            existing["completed_by_path"] = None
            added.append(existing)

    save_queue(payload, state_path)
    response = queue_for_source(source, state_path)
    response["added"] = added
    response["skipped"] = skipped
    return response


def build_queue_item(
    source: Path,
    path: Path,
    raw_item: dict[str, Any],
    label: str,
    album_artist: str | None,
    artist: str | None,
    album: str | None,
    key: str,
) -> MusicReplacementQueueItem:
    facts = raw_item.get("facts") if isinstance(raw_item.get("facts"), dict) else {}
    item_id = music_replacement_item_id(str(source), key, str(path))
    return MusicReplacementQueueItem(
        item_id=item_id,
        source_root=str(source),
        album_artist=album_artist,
        artist=artist,
        album=album,
        album_key=key,
        original_path=str(path),
        original_profile_label=label,
        bitrate_kbps=facts.get("bitrate_kbps"),
        format=facts.get("format"),
        file_size_bytes=facts.get("file_size_bytes"),
        queued_at=utc_now_iso(),
    )


def music_replacement_item_id(source: str, key: str, path: str) -> str:
    digest = hashlib.sha1(f"{source}\0{key}\0{path}".encode("utf-8")).hexdigest()
    return digest[:16]


def reconcile_replacement_queue(
    source_root: Path,
    raw_tracks: list[Any],
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    payload = load_queue(state_path)
    replacements = replacement_identities(source, raw_tracks)
    changed = False
    now = utc_now_iso()

    for item in payload["items"]:
        if item.get("source_root") != str(source) or item.get("status") not in {"pending", "deleted"}:
            continue
        album_key = item.get("album_key", "")
        matched_path = replacements.get(album_key)
        if matched_path is None:
            continue
        item["status"] = "completed"
        item["completed_at"] = now
        item["completed_by_path"] = matched_path
        changed = True

    if changed:
        save_queue(payload, state_path)
    return queue_for_source(source, state_path)


def replacement_identities(source: Path, raw_tracks: list[Any]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for raw_item in raw_tracks:
        if not isinstance(raw_item, dict):
            continue
        label = str((raw_item.get("profile") or {}).get("label") or "")
        if is_strict_weak_label(label):
            continue
        raw_path = raw_item.get("path")
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser().resolve()
        try:
            path.relative_to(source)
        except ValueError:
            continue
        _, _, _, key = extract_album_identity(raw_item, path)
        replacements.setdefault(key, str(path))
    return replacements


def delete_replacement_queue_media(
    source_root: Path,
    item_ids: list[Any],
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    requested = {str(item_id) for item_id in item_ids}
    payload = load_queue(state_path)
    deleted: list[dict[str, str]] = []
    cleaned_sidecars: list[str] = []
    removed_folders: list[str] = []
    skipped: list[dict[str, str]] = []
    now = utc_now_iso()

    for item in payload["items"]:
        item_id = str(item.get("item_id") or "")
        if item_id not in requested or item.get("source_root") != str(source):
            continue
        target = Path(str(item.get("original_path"))).expanduser().resolve()
        try:
            target.relative_to(source)
        except ValueError:
            skipped.append({"item_id": item_id, "path": str(target), "reason": "outside_source"})
            continue
        if target == source:
            skipped.append({"item_id": item_id, "path": str(target), "reason": "source_root"})
            continue
        if not target.exists():
            skipped.append({"item_id": item_id, "path": str(target), "reason": "missing"})
            continue
        if not target.is_file():
            skipped.append({"item_id": item_id, "path": str(target), "reason": "not_file"})
            continue
        try:
            target.unlink()
            cleanup = cleanup_safe_music_sidecars(source, target.parent)
            cleaned_sidecars.extend(cleanup["sidecars"])
            if cleanup["folder"]:
                removed_folders.append(cleanup["folder"])
        except OSError as exc:
            skipped.append({"item_id": item_id, "path": str(target), "reason": str(exc)})
            continue
        item["status"] = "deleted"
        item["deleted_at"] = now
        deleted.append({"item_id": item_id, "path": str(target)})

    save_queue(payload, state_path)
    response = queue_for_source(source, state_path)
    response["deleted"] = deleted
    response["cleaned_sidecars"] = cleaned_sidecars
    response["removed_folders"] = removed_folders
    response["skipped"] = skipped
    return response


def cleanup_safe_music_sidecars(source: Path, folder: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"sidecars": [], "folder": None}
    if not folder.exists() or not folder.is_dir() or folder == source:
        return result
    try:
        folder.relative_to(source)
    except ValueError:
        return result

    entries = list(folder.iterdir())
    if not entries:
        folder.rmdir()
        result["folder"] = str(folder)
        return result

    if any(entry.is_dir() for entry in entries):
        return result
    if any(entry.suffix.lower() in SUPPORTED_EXTENSIONS for entry in entries):
        return result
    if any(not is_safe_music_sidecar(entry) for entry in entries):
        return result

    for entry in entries:
        entry.unlink()
        result["sidecars"].append(str(entry))
    folder.rmdir()
    result["folder"] = str(folder)
    return result


def is_safe_music_sidecar(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SAFE_MUSIC_SIDECAR_EXTENSIONS
