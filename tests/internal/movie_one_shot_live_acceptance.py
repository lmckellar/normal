from __future__ import annotations

import os
import unittest
from pathlib import Path

from normal.movie_plan import build_movie_plan
from normal.movie_preclean import filter_movie_files_with_preclean, load_movie_preclean_entries
from normal.movie_scan import discover_video_files


class MovieOneShotLiveAcceptanceTests(unittest.TestCase):
    """Internal hardening pass against a real movie library."""

    def test_live_library_acceptance_after_logged_preclean(self) -> None:
        source_env = os.environ.get("NORMAL_TEST_MOVIE_SOURCE", "").strip()
        ledger_env = os.environ.get("NORMAL_TEST_MOVIE_PRECLEAN_LEDGER", "").strip()
        if not source_env:
            self.skipTest("NORMAL_TEST_MOVIE_SOURCE is not set")
        if not ledger_env:
            self.skipTest("NORMAL_TEST_MOVIE_PRECLEAN_LEDGER is not set")

        source = Path(source_env)
        ledger = Path(ledger_env)
        if not source.exists():
            self.skipTest(f"movie source does not exist: {source}")
        if not ledger.exists():
            self.skipTest(f"preclean ledger does not exist: {ledger}")

        entries = load_movie_preclean_entries(ledger)
        movie_files = filter_movie_files_with_preclean(discover_video_files(source), entries)
        plan = build_movie_plan(source, movie_files=movie_files)

        warning_codes = {warning.code for warning in plan.warnings}
        self.assertTrue(
            warning_codes.issubset({"movie_name_existing_target_collision"}),
            msg=f"unexpected warnings: {sorted(warning_codes)}",
        )
        self.assertTrue(
            all(
                change.confidence == "safe"
                for change in plan.proposed_changes
                if "Target path already exists in the library." not in change.reason
            )
        )


if __name__ == "__main__":
    unittest.main()
