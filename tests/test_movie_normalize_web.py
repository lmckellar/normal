from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_plan import build_movie_plan
from normal.movie_scan import discover_video_files
from normal.web import build_movie_normalize_results


class MovieNormalizeWebTests(unittest.TestCase):
    def test_all_results_include_already_normalized_movies_and_pending_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            for index in range(1, 10):
                folder = source / f"Clean Movie {index} (200{index})"
                folder.mkdir()
                (folder / f"Clean Movie {index} (200{index}).mkv").write_text("video", encoding="utf-8")
            pending_folder = source / "Messy Folder"
            pending_folder.mkdir()
            (pending_folder / "The.Matrix.1999.1080p.bluray.x264-GRP.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)
            results = build_movie_normalize_results(source, discover_video_files(source), plan.proposed_changes)

            self.assertEqual(len(results), 10)
            self.assertEqual(len(plan.proposed_changes), 2)
            pending = next(result for result in results if result["current_value"].endswith("The.Matrix.1999.1080p.bluray.x264-GRP.mkv"))
            self.assertEqual(pending["confidence"], "safe")
            self.assertEqual(pending["proposed_value"], "The Matrix (1999)/The Matrix (1999).mkv")
            self.assertEqual(pending["projected_path"], "The Matrix (1999)/The Matrix (1999).mkv")
            self.assertEqual(len(pending["change_ids"]), 2)
            self.assertEqual(pending["title_source"], "filename_prefix")
            unchanged = [result for result in results if result["confidence"] == "unchanged"]
            self.assertEqual(len(unchanged), 9)
            self.assertTrue(all(not result["change_ids"] for result in unchanged))

    def test_all_results_include_unparsed_video_as_noop_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "unknown.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)
            results = build_movie_normalize_results(source, discover_video_files(source), plan.proposed_changes, plan.warnings)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["confidence"], "review")
            self.assertEqual(results[0]["current_value"], "unknown.mkv")
            self.assertEqual(results[0]["proposed_value"], "unknown.mkv")
            self.assertEqual(results[0]["change_ids"], [])
            self.assertIn("weak_title_inference", results[0]["warning_codes"])


if __name__ == "__main__":
    unittest.main()
