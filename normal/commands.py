from __future__ import annotations

import json
from pathlib import Path
import sys

from normal.apply import apply_plan
from normal.artwork import apply_artwork, resolve_gap, scan_artist_artwork, sync_jellyfin_artist_metadata_artwork
from normal.movie_inspect import inspect_movie_file
from normal.movie_junk import scan_movie_junk
from normal.movie_plan import build_movie_plan
from normal.movie_profile import build_histogram_payload, scan_movie_profiles
from normal.movie_scan import MovieScanProgress, scan_movie_library
from normal.output import write_collection_csv, write_movie_register_xlsx, write_movie_review_csv
from normal.plan import build_plan
from normal.scan import analyze_library
from normal.web import serve_web_ui


def ensure_source_directory(source: Path) -> Path:
    resolved = source.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"source does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"source is not a directory: {resolved}")
    return resolved


def ensure_parent_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    ensure_parent_directory(path)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_scan(source: Path, report_path: Path) -> int:
    source_root = ensure_source_directory(source)
    report = analyze_library(source_root)
    write_json(report_path, report.to_dict())
    return 0


def run_plan(source: Path, plan_path: Path, summary_path: Path | None) -> int:
    source_root = ensure_source_directory(source)
    plan = build_plan(source_root)
    write_json(plan_path, plan.to_dict())

    if summary_path is not None:
        ensure_parent_directory(summary_path)
        safe_count = sum(1 for change in plan.proposed_changes if change.confidence == "safe")
        review_count = sum(1 for change in plan.proposed_changes if change.confidence == "review")
        summary_path.write_text(
            "# normal plan summary\n\n"
            "- source: "
            f"{source_root}\n"
            f"- proposed_changes: {len(plan.proposed_changes)}\n"
            f"- safe_changes: {safe_count}\n"
            f"- review_changes: {review_count}\n"
            f"- warnings: {len(plan.warnings)}\n",
            encoding="utf-8",
        )
    return 0


def run_apply(source: Path, plan_path: Path, target: Path | None, in_place: bool) -> int:
    source_root = ensure_source_directory(source)
    resolved_plan = plan_path.expanduser().resolve()
    if not resolved_plan.exists():
        raise FileNotFoundError(f"plan does not exist: {resolved_plan}")

    apply_plan(
        source_root=source_root,
        plan_path=resolved_plan,
        target_root=target,
        in_place=in_place,
    )
    return 0


def run_output(source: Path, csv_path: Path) -> int:
    source_root = ensure_source_directory(source)
    write_collection_csv(source_root, csv_path)
    return 0


def run_movie_register(report_path: Path, xlsx_path: Path) -> int:
    resolved_report = report_path.expanduser().resolve()
    if not resolved_report.exists():
        raise FileNotFoundError(f"report does not exist: {resolved_report}")
    write_movie_register_xlsx(resolved_report, xlsx_path)
    return 0


def run_movie_output(report_path: Path, csv_path: Path, minimum_status: str) -> int:
    resolved_report = report_path.expanduser().resolve()
    if not resolved_report.exists():
        raise FileNotFoundError(f"report does not exist: {resolved_report}")
    write_movie_review_csv(resolved_report, csv_path, minimum_status=minimum_status)
    return 0


def run_movie_plan(source: Path, plan_path: Path, summary_path: Path | None) -> int:
    source_root = ensure_source_directory(source)
    plan = build_movie_plan(source_root)
    write_json(plan_path, plan.to_dict())

    if summary_path is not None:
        ensure_parent_directory(summary_path)
        safe_count = sum(1 for change in plan.proposed_changes if change.confidence == "safe")
        review_count = sum(1 for change in plan.proposed_changes if change.confidence == "review")
        summary_path.write_text(
            "# normal movie plan summary\n\n"
            "- source: "
            f"{source_root}\n"
            f"- proposed_changes: {len(plan.proposed_changes)}\n"
            f"- safe_changes: {safe_count}\n"
            f"- review_changes: {review_count}\n"
            f"- warnings: {len(plan.warnings)}\n",
            encoding="utf-8",
        )
    return 0


def run_movie_apply(source: Path, plan_path: Path, target: Path | None, in_place: bool) -> int:
    source_root = ensure_source_directory(source)
    resolved_plan = plan_path.expanduser().resolve()
    if not resolved_plan.exists():
        raise FileNotFoundError(f"plan does not exist: {resolved_plan}")

    apply_plan(
        source_root=source_root,
        plan_path=resolved_plan,
        target_root=target,
        in_place=in_place,
        report_filename="normal-movie-apply-report.json",
    )
    return 0


def run_movie_scan(source: Path, report_path: Path, progress: bool = False) -> int:
    source_root = ensure_source_directory(source)
    progress_callback = build_movie_scan_progress_callback() if progress else None
    report = scan_movie_library(source_root, progress_callback=progress_callback)
    write_json(report_path, report.to_dict())
    if progress_callback is not None:
        sys.stderr.write("\n")
    return 0


def run_movie_profile(
    source: Path,
    report_path: Path,
    histogram_path: Path | None = None,
    progress: bool = False,
) -> int:
    source_root = ensure_source_directory(source)
    progress_callback = build_movie_scan_progress_callback() if progress else None
    report = scan_movie_profiles(source_root, progress_callback=progress_callback)
    write_json(report_path, report.to_dict())
    if histogram_path is not None:
        write_json(histogram_path, build_histogram_payload(report))
    if progress_callback is not None:
        sys.stderr.write("\n")
    return 0


def run_movie_inspect(path: Path, report_path: Path) -> int:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"path does not exist: {resolved}")
    if not resolved.is_file():
        raise FileNotFoundError(f"path is not a file: {resolved}")
    report = inspect_movie_file(resolved)
    write_json(report_path, report.to_dict())
    return 0


def run_movie_junk(source: Path, report_path: Path) -> int:
    source_root = ensure_source_directory(source)
    report = scan_movie_junk(source_root)
    write_json(report_path, report.to_dict())
    return 0


def run_artwork_scan(source: Path) -> int:
    source_root = ensure_source_directory(source)
    report = scan_artist_artwork(source_root)
    present_count = len(report.present)
    missing_count = len(report.missing)
    print(f"artwork-scan: {present_count + missing_count} artists | {present_count} have artwork | {missing_count} missing")
    for gap in report.missing:
        print(f"  MISSING  {gap.artist_name}")
    for item in report.present:
        print(f"  PRESENT  {item.artist_name}  ({item.filename})")
    return 0


def run_artwork_apply(
    source: Path,
    strategy: str,
    lastfm_api_key: str | None,
    dry_run: bool,
) -> int:
    source_root = ensure_source_directory(source)
    report = scan_artist_artwork(source_root)
    resolutions = [resolve_gap(gap, strategy, lastfm_api_key) for gap in report.missing]
    results = apply_artwork(resolutions, dry_run=dry_run)
    written = sum(1 for r in results if r.status == "written")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    print(f"artwork-apply: {written} written | {skipped} skipped | {failed} failed")
    for result in results:
        suffix = f"  ({result.message})" if result.message else ""
        print(f"  {result.status.upper():8s}  {result.artist_name}{suffix}")
    return 0 if failed == 0 else 1


def run_artwork_sync_jellyfin_metadata(source: Path, dry_run: bool) -> int:
    source_root = ensure_source_directory(source)
    result = sync_jellyfin_artist_metadata_artwork(source_root, dry_run=dry_run)
    written = len(result["written"])
    backed_up = len(result["backed_up"])
    skipped = len(result["skipped"])
    mode = "dry-run" if dry_run else "write"
    print(f"artwork-sync-jellyfin-metadata ({mode}): {written} target files | {backed_up} backups | {skipped} skipped")
    for path in result["written"]:
        print(f"  TARGET   {path}")
    for path in result["backed_up"]:
        print(f"  BACKUP   {path}")
    for item in result["skipped"]:
        print(f"  SKIP     {item['path']}  ({item['reason']})")
    return 0


def run_web(host: str, port: int, source: Path | None = None) -> int:
    default_source = None
    if source is not None:
        default_source = ensure_source_directory(source)
    serve_web_ui(host=host, port=port, default_source=default_source)
    return 0


def build_movie_scan_progress_callback():
    def callback(progress: MovieScanProgress) -> None:
        total = progress.total or 1
        percent = (progress.processed / total) * 100
        eta = format_duration(progress.eta_seconds)
        elapsed = format_duration(progress.elapsed_seconds)
        current_name = Path(progress.current_path).name if progress.current_path else ""
        line = (
            f"\rmovie-scan {percent:5.1f}% "
            f"({progress.processed}/{progress.total}) "
            f"elapsed {elapsed} eta {eta}"
        )
        if current_name:
            line += f" {current_name[:80]}"
        sys.stderr.write(line)
        sys.stderr.flush()

    return callback


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total_seconds = max(0, int(round(seconds)))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
