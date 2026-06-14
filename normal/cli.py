from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from normal.commands import (
    run_movie_apply,
    run_movie_inspect,
    run_movie_junk,
    run_movie_output,
    run_movie_plan,
    run_movie_profile,
    run_movie_register,
    run_movie_scan,
    run_web,
)
from normal.output import MissingDependencyError
from normal.source_policy import SourcePolicyError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="normal")
    subparsers = parser.add_subparsers(dest="command", required=True)

    movie_register_parser = subparsers.add_parser(
        "movie-register",
        help="Export a formatted movie catalogue spreadsheet (XLSX).",
    )
    movie_register_parser.add_argument("--report", type=Path, required=True)
    movie_register_parser.add_argument("--xlsx", type=Path, required=True)
    movie_register_parser.set_defaults(func=handle_movie_register)

    movie_output_parser = subparsers.add_parser(
        "movie-output",
        help="Export a movie quality report to CSV for triage.",
    )
    movie_output_parser.add_argument("--report", type=Path, required=True)
    movie_output_parser.add_argument("--csv", type=Path, required=True)
    movie_output_parser.add_argument(
        "--minimum-status",
        choices=("severe", "review", "ok", "unscored"),
        default="review",
    )
    movie_output_parser.set_defaults(func=handle_movie_output)

    movie_plan_parser = subparsers.add_parser(
        "movie-plan",
        help="Generate a reviewable movie rename plan without mutating the library.",
    )
    movie_plan_parser.add_argument("--source", type=Path, required=True)
    movie_plan_parser.add_argument("--plan", type=Path, required=True)
    movie_plan_parser.add_argument("--summary", type=Path)
    movie_plan_parser.set_defaults(func=handle_movie_plan)

    movie_apply_parser = subparsers.add_parser(
        "movie-apply",
        help="Apply an existing movie plan to a target or in place.",
    )
    movie_apply_parser.add_argument("--source", type=Path, required=True)
    movie_apply_parser.add_argument("--plan", type=Path, required=True)
    movie_apply_group = movie_apply_parser.add_mutually_exclusive_group(required=True)
    movie_apply_group.add_argument("--target", type=Path)
    movie_apply_group.add_argument("--in-place", action="store_true")
    movie_apply_parser.set_defaults(func=handle_movie_apply)

    movie_scan_parser = subparsers.add_parser(
        "movie-scan",
        help="Analyze a movie library for likely poor encodes without changing it.",
    )
    movie_scan_parser.add_argument("--source", type=Path, required=True)
    movie_scan_parser.add_argument("--report", type=Path, required=True)
    movie_scan_parser.add_argument("--progress", action="store_true")
    movie_scan_parser.set_defaults(func=handle_movie_scan)

    movie_profile_parser = subparsers.add_parser(
        "movie-profile",
        help="Profile movie quality across the library and emit aggregate distribution data.",
    )
    movie_profile_parser.add_argument("--source", type=Path, required=True)
    movie_profile_parser.add_argument("--report", type=Path, required=True)
    movie_profile_parser.add_argument("--histogram", type=Path)
    movie_profile_parser.add_argument("--progress", action="store_true")
    movie_profile_parser.set_defaults(func=handle_movie_profile)

    movie_inspect_parser = subparsers.add_parser(
        "movie-inspect",
        help="Inspect one movie file for likely Plex playback risks.",
    )
    movie_inspect_parser.add_argument("--path", type=Path, required=True)
    movie_inspect_parser.add_argument("--report", type=Path, required=True)
    movie_inspect_parser.set_defaults(func=handle_movie_inspect)

    movie_junk_parser = subparsers.add_parser(
        "movie-junk",
        help="Find likely sample, featurette, and short junk videos without changing the library.",
    )
    movie_junk_parser.add_argument("--source", type=Path, required=True)
    movie_junk_parser.add_argument("--report", type=Path, required=True)
    movie_junk_parser.set_defaults(func=handle_movie_junk)

    web_parser = subparsers.add_parser(
        "web",
        help="Run a small local web UI for movie profiling and inspection.",
    )
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument("--source", type=Path)
    web_parser.add_argument("--allow-root", type=Path, action="append", metavar="PATH")
    web_parser.add_argument("--omdb-key", default=os.environ.get("OMDB_KEY"), metavar="KEY")
    web_parser.add_argument("--tmdb-key", default=os.environ.get("TMDB_KEY"), metavar="KEY")
    web_parser.add_argument("--unsafe-remote", action="store_true")
    web_parser.add_argument("--allow-peer", action="append", default=[], metavar="IP/CIDR")
    web_parser.add_argument("--allow-host", action="append", default=[], metavar="HOST")
    web_parser.add_argument("--allow-origin", action="append", default=[], metavar="ORIGIN")
    web_parser.set_defaults(func=handle_web)

    return parser


def handle_movie_register(args: argparse.Namespace) -> int:
    return run_movie_register(report_path=args.report, xlsx_path=args.xlsx)


def handle_movie_output(args: argparse.Namespace) -> int:
    return run_movie_output(report_path=args.report, csv_path=args.csv, minimum_status=args.minimum_status)


def handle_movie_plan(args: argparse.Namespace) -> int:
    return run_movie_plan(source=args.source, plan_path=args.plan, summary_path=args.summary)


def handle_movie_apply(args: argparse.Namespace) -> int:
    return run_movie_apply(source=args.source, plan_path=args.plan, target=args.target, in_place=args.in_place)


def handle_movie_scan(args: argparse.Namespace) -> int:
    return run_movie_scan(source=args.source, report_path=args.report, progress=args.progress)


def handle_movie_profile(args: argparse.Namespace) -> int:
    return run_movie_profile(
        source=args.source,
        report_path=args.report,
        histogram_path=args.histogram,
        progress=args.progress,
    )


def handle_movie_inspect(args: argparse.Namespace) -> int:
    return run_movie_inspect(path=args.path, report_path=args.report)


def handle_movie_junk(args: argparse.Namespace) -> int:
    return run_movie_junk(source=args.source, report_path=args.report)


def handle_web(args: argparse.Namespace) -> int:
    try:
        return run_web(
            host=args.host,
            port=args.port,
            source=args.source,
            omdb_key=args.omdb_key,
            tmdb_key=args.tmdb_key,
            unsafe_remote=args.unsafe_remote,
            allow_roots=args.allow_root,
            allow_peers=args.allow_peer,
            allow_hosts=args.allow_host,
            allow_origins=args.allow_origin,
        )
    except ValueError as exc:
        print(f"normal: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (MissingDependencyError, SourcePolicyError) as exc:
        print(f"normal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
