from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_apply import apply_changes_in_place
from normal.movie_enriched import scan_enriched_library
from normal.quality_review import MediaFacts
from normal.tv_plan import build_tv_plan, parsed_tv_from_enriched


class TvPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.source = Path(self._tmp.name)

    def add_video(self, relative_path: str) -> Path:
        path = self.source / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("video", encoding="utf-8")
        return path

    def test_plan_emits_filename_only_per_file_changes(self) -> None:
        first = self.add_video("Show/Show.1x01.Pilot.1080p.mkv")
        second = self.add_video("Show/Show.S01E02.Second.mkv")

        plan = build_tv_plan(self.source)

        self.assertEqual(len(plan.proposed_changes), 2)
        self.assertEqual({change.change_type for change in plan.proposed_changes}, {"file_rename"})
        self.assertEqual({change.path for change in plan.proposed_changes}, {str(first), str(second)})
        self.assertEqual(
            {change.proposed_value for change in plan.proposed_changes},
            {"Show - S01E01 - Pilot.mkv", "Show - S01E02 - Second.mkv"},
        )

    def test_multi_episode_span_stays_one_change(self) -> None:
        self.add_video("Mad Men/Mad Men S05E01-E02.mkv")

        plan = build_tv_plan(self.source)

        self.assertEqual(len(plan.proposed_changes), 1)
        self.assertEqual(plan.proposed_changes[0].proposed_value, "Mad Men - S05E01-E02.mkv")

    def test_plan_preserves_filename_extension_case(self) -> None:
        self.add_video("Show/Show.S01E01.MKV")

        plan = build_tv_plan(self.source)

        self.assertEqual(plan.proposed_changes[0].proposed_value, "Show - S01E01.MKV")

    def test_absolute_numbering_is_not_converted_without_folder_season(self) -> None:
        self.add_video("Tokyo Ghoul/Tokyo Ghoul - 01 [1080p][x265].mkv")

        plan = build_tv_plan(self.source)

        change = plan.proposed_changes[0]
        self.assertEqual(change.proposed_value, "Tokyo Ghoul - 01.mkv")
        self.assertEqual(change.confidence, "safe")
        self.assertIn("anime_absolute_numbering_risk", change.reason_codes)

    def test_loose_root_episode_and_special_are_review_only(self) -> None:
        root_episode = self.add_video("Show.S01E01.mkv")
        special = self.add_video("Show/OVA/Show.S01E02.mkv")

        plan = build_tv_plan(self.source)
        changes = {Path(change.path): change for change in plan.proposed_changes}

        self.assertEqual(changes[root_episode].confidence, "review")
        self.assertIn("tv_loose_root_episode", changes[root_episode].reason_codes)
        self.assertEqual(changes[special].confidence, "review")
        self.assertIn("tv_special_content_review", changes[special].reason_codes)

    def test_ambiguous_file_emits_review_record_and_executor_skips_it(self) -> None:
        movie = self.add_video("Futurama/Movies/Benders.Game.2008.mkv")

        plan = build_tv_plan(self.source)
        report = apply_changes_in_place(self.source, plan.proposed_changes)

        self.assertEqual(len(plan.proposed_changes), 1)
        self.assertEqual(plan.proposed_changes[0].confidence, "review")
        self.assertEqual(len(report.skipped), 1)
        self.assertTrue(movie.exists())

    def test_enriched_tv_lane_retains_identity_and_skips_movie_priority(self) -> None:
        episode = self.add_video("Show/Show.S01E01.mkv")

        enriched = scan_enriched_library(
            self.source,
            lane="tv",
            probe_media=lambda _: MediaFacts(),
        )

        self.assertEqual(enriched.files[0].identity.lane, "tv")
        self.assertEqual(parsed_tv_from_enriched(enriched)[episode].series, "Show")
        self.assertIsNone(enriched.files[0].replacement_priority_score)
        plan = build_tv_plan(self.source, enriched_report=enriched)
        self.assertEqual(plan.proposed_changes[0].proposed_value, "Show - S01E01.mkv")


if __name__ == "__main__":
    unittest.main()
