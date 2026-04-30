from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_inspect import inspect_movie_file
from normal.quality_review import MediaFacts


class MovieInspectTests(unittest.TestCase):
    def test_inspect_movie_file_reports_likely_causes_and_remedies(self) -> None:
        with patch(
            "normal.movie_inspect.probe_media_facts",
            return_value=MediaFacts(
                width=1920,
                height=1080,
                container="avi",
                subtitle_codecs=["hdmv_pgs_subtitle"],
            ),
        ):
            report = inspect_movie_file(Path("/movies/Test.mkv"))

        self.assertEqual(report.facts.resolution_bucket, "1080p")
        self.assertTrue(report.likely_causes)
        self.assertTrue(report.remedy_plan)
        self.assertIn("Plex", report.playback_gap_summary)


if __name__ == "__main__":
    unittest.main()
