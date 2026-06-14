from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

from normal import paths
from normal.models import utc_now_iso
from normal.movie_naming import title_match_key
from normal.movie_plan import parse_movie_name
from normal.movie_scan import VIDEO_EXTENSIONS


QUEUE_VERSION = 2
MOVIE_TRIAGE_FAMILIES = {"weak_encode", "audio_packaging"}
AUDIO_PACKAGING_CODES = {
    "default_non_english_audio_with_weak_english",
    "default_non_english_audio",
}
SAFE_MOVIE_SIDECAR_EXTENSIONS = {
    ".ass",
    ".htm",
    ".html",
    ".idx",
    ".jpeg",
    ".jpg",
    ".nfo",
    ".png",
    ".srt",
    ".ssa",
    ".sub",
    ".sup",
    ".txt",
    ".url",
    ".vtt",
    ".webp",
    ".xml",
}
HISTORY_TITLE_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(slots=True)
class ReplacementQueueItem:
    item_id: str
    source_root: str
    title: str
    year: int
    title_key: str
    history_title_key: str
    original_path: str
    original_folder_path: str
    mode: str
    issue_family: str
    issue_code: str | None
    issue_label: str | None
    original_profile_label: str
    resolution_bucket: str | None
    video_bitrate_kbps: int | None
    file_size_bytes: int | None
    queued_at: str
    status: str = "pending"
    deleted_at: str | None = None
    dismissed_at: str | None = None
    completed_at: str | None = None
    completed_by_path: str | None = None


def default_queue_path() -> Path:
    return paths.replacement_queue_path()


def title_key(title: str) -> str:
    return title_match_key(title)


def history_title_key(title: str) -> str:
    return title_match_key(title)


def is_strict_weak_item(raw_item: dict[str, Any]) -> bool:
    profile = raw_item.get("profile") or {}
    if not isinstance(profile, dict):
        return False
    return bool(profile.get("weak_candidate"))


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
        item = normalize_queue_item(item)
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


def normalize_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    normalized["issue_family"] = normalize_issue_family(normalized.get("issue_family"))
    normalized["item_id"] = normalized_item_id(normalized)
    normalized = normalize_queue_item_identity(normalized)
    return normalized


def normalize_queue_item_identity(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("identity_locked"):
        title = str(item.get("title") or "")
        if not title:
            return item
        key = title_key(title)
        history_key = history_title_key(title)
        normalized = dict(item)
        normalized["title_key"] = key
        normalized["history_title_key"] = history_key
        return normalized
    raw_path = item.get("original_path")
    if not raw_path:
        title = str(item.get("title") or "")
        history_key = history_title_key(title) if title else ""
        if item.get("history_title_key") == history_key:
            return item
        return {**item, "history_title_key": history_key}
    parsed = parse_movie_name(Path(str(raw_path)))
    if parsed.title is None or parsed.year is None:
        title = str(item.get("title") or "")
        history_key = history_title_key(title) if title else ""
        if item.get("history_title_key") == history_key:
            return item
        return {**item, "history_title_key": history_key}
    key = title_key(parsed.title)
    history_key = history_title_key(parsed.title)
    if (
        item.get("title") == parsed.title
        and item.get("year") == parsed.year
        and item.get("title_key") == key
        and item.get("history_title_key") == history_key
    ):
        return item
    return {
        **item,
        "title": parsed.title,
        "year": parsed.year,
        "title_key": key,
        "history_title_key": history_key,
    }


def normalized_item_id(item: dict[str, Any]) -> str:
    source = str(item.get("source_root") or "")
    key = str(item.get("title_key") or "")
    year = int(item.get("year") or 0)
    path = str(item.get("original_path") or "")
    mode = str(item.get("mode") or "file")
    family = normalize_issue_family(item.get("issue_family"))
    return replacement_item_id(source, key, year, path, mode, family)


def normalize_issue_family(value: Any) -> str:
    family = str(value or "weak_encode").strip().casefold().replace("-", "_")
    if family not in MOVIE_TRIAGE_FAMILIES:
        raise ValueError(f"unsupported issue family: {family}")
    return family


def queue_for_source(source_root: Path, state_path: Path | None = None, issue_family: str | None = None) -> dict[str, Any]:
    source = str(source_root.resolve())
    payload = load_queue(state_path)
    family = normalize_issue_family(issue_family) if issue_family is not None else None
    return {
        "source_root": source,
        "issue_family": family,
        "generated_at": utc_now_iso(),
        "items": [
            item
            for item in payload["items"]
            if item.get("source_root") == source and (family is None or item.get("issue_family") == family)
        ],
    }


def clear_pending_queue_items(
    source_root: Path,
    paths: list[str],
    issue_family: str,
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = str(source_root.resolve())
    family = normalize_issue_family(issue_family)
    target_paths = {str(Path(path).expanduser().resolve()) for path in paths}
    payload = load_queue(state_path)
    cleared: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []

    for item in payload["items"]:
        if (
            item.get("source_root") == source
            and item.get("issue_family") == family
            and item.get("status") == "pending"
            and str(item.get("original_path") or "") in target_paths
        ):
            cleared.append(item)
            continue
        kept.append(item)

    payload["items"] = kept
    save_queue(payload, state_path)
    response = queue_for_source(source_root, state_path=state_path, issue_family=family)
    response["cleared"] = cleared
    return response


def add_profile_items_to_queue(
    source_root: Path,
    raw_items: list[Any],
    mode: str = "file",
    state_path: Path | None = None,
    issue_family: str = "weak_encode",
) -> dict[str, Any]:
    if mode not in {"file", "folder"}:
        raise ValueError("mode must be file or folder")
    family = normalize_issue_family(issue_family)

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
        issue = queue_issue_for_raw_item(raw_item, family)
        if issue is None:
            skipped.append({"path": str(raw_item.get("path") or ""), "reason": skip_reason_for_issue_family(family)})
            continue
        path = Path(str(raw_item.get("path") or "")).expanduser().resolve()
        try:
            path.relative_to(source)
        except ValueError:
            skipped.append({"path": str(path), "reason": "outside_source"})
            continue
        parsed = parse_movie_name(path)
        if parsed.title is None or parsed.year is None:
            skipped.append({"path": str(path), "reason": "unparsed_identity"})
            continue

        item = build_queue_item(source, path, raw_item, label, mode, parsed.title, parsed.year, family, issue)
        existing = existing_by_id.get(item.item_id)
        if existing is None:
            payload["items"].append(asdict(item))
            existing_by_id[item.item_id] = payload["items"][-1]
            added.append(payload["items"][-1])
        else:
            existing["status"] = "pending"
            existing["deleted_at"] = None
            existing["dismissed_at"] = None
            existing["completed_at"] = None
            existing["completed_by_path"] = None
            added.append(existing)

    save_queue(payload, state_path)
    response = queue_for_source(source, state_path, family)
    response["added"] = added
    response["skipped"] = skipped
    return response


def build_queue_item(
    source: Path,
    path: Path,
    raw_item: dict[str, Any],
    label: str,
    mode: str,
    title: str,
    year: int,
    issue_family: str,
    issue: dict[str, str | None],
) -> ReplacementQueueItem:
    facts = raw_item.get("facts") if isinstance(raw_item.get("facts"), dict) else {}
    folder = path.parent
    key = title_key(title)
    item_id = replacement_item_id(str(source), key, year, str(path), mode, issue_family)
    return ReplacementQueueItem(
        item_id=item_id,
        source_root=str(source),
        title=title,
        year=year,
        title_key=key,
        history_title_key=history_title_key(title),
        original_path=str(path),
        original_folder_path=str(folder),
        mode=mode,
        issue_family=issue_family,
        issue_code=issue.get("issue_code"),
        issue_label=issue.get("issue_label"),
        original_profile_label=label,
        resolution_bucket=facts.get("resolution_bucket"),
        video_bitrate_kbps=facts.get("video_bitrate_kbps"),
        file_size_bytes=facts.get("file_size_bytes"),
        queued_at=utc_now_iso(),
    )


def replacement_item_id(source: str, key: str, year: int, path: str, mode: str, issue_family: str) -> str:
    digest = hashlib.sha1(f"{source}\0{key}\0{year}\0{path}\0{mode}\0{issue_family}".encode("utf-8")).hexdigest()
    return digest[:16]


def reconcile_replacement_queue(
    source_root: Path,
    raw_movies: list[Any],
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    payload = load_queue(state_path)
    replacements_by_family: dict[str, dict[tuple[str, int], str]] = {}
    changed = False
    now = utc_now_iso()

    for item in payload["items"]:
        if item.get("source_root") != str(source) or item.get("status") not in {"pending", "deleted"}:
            continue
        family = normalize_issue_family(item.get("issue_family"))
        identity = (item.get("title_key"), item.get("year"))
        if family not in replacements_by_family:
            replacements_by_family[family] = replacement_identities(source, raw_movies, family)
        replacements = replacements_by_family[family]
        matched_path = replacements.get(identity)
        if matched_path is None:
            continue
        item["status"] = "completed"
        item["completed_at"] = now
        item["completed_by_path"] = matched_path
        changed = True

    if changed:
        save_queue(payload, state_path)
    return queue_for_source(source, state_path)


def replacement_identities(source: Path, raw_movies: list[Any], issue_family: str) -> dict[tuple[str, int], str]:
    replacements: dict[tuple[str, int], str] = {}
    for raw_item in raw_movies:
        if not isinstance(raw_item, dict):
            continue
        if queue_issue_for_raw_item(raw_item, issue_family) is not None:
            continue
        raw_path = raw_item.get("path")
        if not raw_path:
            continue
        path = Path(str(raw_path)).expanduser().resolve()
        try:
            path.relative_to(source)
        except ValueError:
            continue
        parsed = parse_movie_name(path)
        if parsed.title is None or parsed.year is None:
            continue
        replacements.setdefault((title_key(parsed.title), parsed.year), str(path))
    return replacements


def queue_issue_for_raw_item(raw_item: dict[str, Any], issue_family: str) -> dict[str, str | None] | None:
    if issue_family == "weak_encode":
        profile = raw_item.get("profile") or {}
        if not isinstance(profile, dict) or not profile.get("weak_candidate"):
            return None
        label = str(profile.get("label") or "")
        domains = profile.get("domain_results") if isinstance(profile.get("domain_results"), list) else []
        domain_codes = [str(result.get("code") or "") for result in domains if isinstance(result, dict) and result.get("status") == "fail"]
        issue_code = ",".join(domain_codes) if domain_codes else label
        return {"issue_code": issue_code, "issue_label": label.replace("_", " ")}
    if issue_family == "audio_packaging":
        diagnostics = (raw_item.get("profile") or {}).get("diagnostics")
        if not isinstance(diagnostics, list):
            return None
        for code in ("default_non_english_audio_with_weak_english", "default_non_english_audio"):
            for diagnostic in diagnostics:
                if not isinstance(diagnostic, dict) or diagnostic.get("code") != code:
                    continue
                return {
                    "issue_code": code,
                    "issue_label": str(diagnostic.get("summary") or code.replace("_", " ")),
                }
        return None
    raise ValueError(f"unsupported issue family: {issue_family}")


def skip_reason_for_issue_family(issue_family: str) -> str:
    if issue_family == "weak_encode":
        return "not_strict_weak"
    if issue_family == "audio_packaging":
        return "not_audio_packaging"
    return "not_candidate"


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
        target = Path(str(item.get("original_folder_path") if item.get("mode") == "folder" else item.get("original_path"))).expanduser().resolve()
        try:
            target.relative_to(source)
        except ValueError:
            skipped.append({"item_id": item_id, "path": str(target), "reason": "outside_source"})
            continue
        if target == source:
            skipped.append({"item_id": item_id, "path": str(target), "reason": "source_root"})
            continue
        if not target.exists():
            item["status"] = "deleted"
            item["deleted_at"] = now
            deleted.append({"item_id": item_id, "path": str(target)})
            continue
        try:
            if item.get("mode") == "folder":
                if not target.is_dir():
                    skipped.append({"item_id": item_id, "path": str(target), "reason": "not_folder"})
                    continue
                shutil.rmtree(target)
            else:
                if not target.is_file():
                    skipped.append({"item_id": item_id, "path": str(target), "reason": "not_file"})
                    continue
                target.unlink()
                cleanup = cleanup_safe_movie_sidecars(source, target.parent)
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


def preview_replacement_queue_delete(
    source_root: Path,
    paths: list[Any],
) -> dict[str, Any]:
    source = source_root.resolve()
    deleted: list[str] = []
    cleaned_sidecars: list[str] = []
    removed_folders: list[str] = []
    skipped: list[dict[str, str]] = []

    for raw_path in paths:
        resolved = Path(str(raw_path)).expanduser().resolve()
        try:
            resolved.relative_to(source)
        except ValueError:
            skipped.append({"path": str(resolved), "reason": "outside_source"})
            continue
        if resolved == source:
            skipped.append({"path": str(resolved), "reason": "source_root"})
            continue
        if not resolved.exists():
            skipped.append({"path": str(resolved), "reason": "missing"})
            continue
        if not resolved.is_file():
            skipped.append({"path": str(resolved), "reason": "not_file"})
            continue
        deleted.append(str(resolved))
        cleanup = preview_safe_movie_sidecar_cleanup(source, resolved.parent, deleted_paths={resolved})
        cleaned_sidecars.extend(cleanup["sidecars"])
        if cleanup["folder"]:
          removed_folders.append(cleanup["folder"])

    return {
        "deleted": deleted,
        "cleaned_sidecars": cleaned_sidecars,
        "removed_folders": removed_folders,
        "skipped": skipped,
    }


def dismiss_replacement_queue_items(
    source_root: Path,
    item_ids: list[Any],
    state_path: Path | None = None,
) -> dict[str, Any]:
    source = source_root.resolve()
    requested = {str(item_id) for item_id in item_ids}
    payload = load_queue(state_path)
    dismissed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    now = utc_now_iso()

    for item in payload["items"]:
        item_id = str(item.get("item_id") or "")
        if item_id not in requested or item.get("source_root") != str(source):
            continue
        if item.get("status") != "deleted":
            skipped.append({"item_id": item_id, "reason": "not_deleted"})
            continue
        item["status"] = "dismissed"
        item["dismissed_at"] = now
        dismissed.append({"item_id": item_id, "path": str(item.get("original_path") or "")})

    save_queue(payload, state_path)
    response = queue_for_source(source, state_path)
    response["dismissed"] = dismissed
    response["skipped"] = skipped
    return response


def cleanup_safe_movie_sidecars(source: Path, folder: Path) -> dict[str, Any]:
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
    if any(entry.suffix.lower() in VIDEO_EXTENSIONS for entry in entries):
        return result
    if any(not is_safe_movie_sidecar(entry) for entry in entries):
        return result

    for entry in entries:
        entry.unlink()
        result["sidecars"].append(str(entry))
    folder.rmdir()
    result["folder"] = str(folder)
    return result


def preview_safe_movie_sidecar_cleanup(
    source: Path,
    folder: Path,
    deleted_paths: set[Path] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"sidecars": [], "folder": None}
    if not folder.exists() or not folder.is_dir() or folder == source:
        return result
    try:
        folder.relative_to(source)
    except ValueError:
        return result

    deleted = {path.resolve() for path in (deleted_paths or set())}
    entries = [entry for entry in folder.iterdir() if entry.resolve() not in deleted]
    if not entries:
        result["folder"] = str(folder)
        return result

    if any(entry.is_dir() for entry in entries):
        return result
    if any(entry.suffix.lower() in VIDEO_EXTENSIONS for entry in entries):
        return result
    if any(not is_safe_movie_sidecar(entry) for entry in entries):
        return result

    result["sidecars"] = [str(entry) for entry in entries]
    result["folder"] = str(folder)
    return result


def is_safe_movie_sidecar(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SAFE_MOVIE_SIDECAR_EXTENSIONS
