from __future__ import annotations

import json
from pathlib import Path
import sys

from normal.movie_apply import apply_plan
from normal.movie_inspect import inspect_movie_file
from normal.movie_junk import scan_movie_junk
from normal.movie_plan import build_movie_plan
from normal.movie_profile import build_histogram_payload, scan_movie_profiles
from normal.movie_scan import MovieScanProgress, scan_movie_library
from normal.output import write_movie_register_xlsx, write_movie_review_csv
from normal.web import ApprovedRoots, parse_allowed_peers, serve_web_ui


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


def run_web(
    host: str,
    port: int,
    source: Path | None = None,
    omdb_key: str | None = None,
    tmdb_key: str | None = None,
    unsafe_remote: bool = False,
    allow_roots: list[Path] | None = None,
    allow_peers: list[str] | None = None,
) -> int:
    default_source = None
    if source is not None:
        default_source = ensure_source_directory(source)
    seed_roots: list[Path] = []
    if default_source is not None:
        seed_roots.append(default_source)
    for raw_root in allow_roots or []:
        seed_roots.append(ensure_source_directory(raw_root))
    approved_roots = ApprovedRoots.from_paths(seed_roots)
    allowed_peers = parse_allowed_peers(allow_peers or [])
    serve_web_ui(host=host, port=port, default_source=default_source, omdb_key=omdb_key, tmdb_key=tmdb_key, unsafe_remote=unsafe_remote, approved_roots=approved_roots, allowed_peers=allowed_peers)
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
