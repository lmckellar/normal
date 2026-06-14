from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from normal.models import ProposedChange
from normal.movie_enriched import IdentitySlot, scan_enriched_library
from normal.movie_identity import parse_movie_identity
from normal.movie_profile import MovieProfileReport, build_movie_profile_item
from normal.quality_review import MediaFacts
from normal.tv_plan import build_tv_plan, parsed_tv_from_enriched
from normal.web.serializers import (
    build_movie_normalize_results,
    build_tv_normalize_results,
    build_profile_response,
    build_updated_profile_items,
    movie_normalize_changes_for_file,
    projected_movie_normalize_path,
)


@dataclass
class FakeProfiledItem:
    path: str
    facts: dict[str, object]
    status: str


class WebSerializersTests(unittest.TestCase):
    def test_build_tv_normalize_results_serializes_tv_identity_without_movie_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            episode = source / "Show" / "Show.S01E02.Pilot.1080p.mkv"
            episode.parent.mkdir()
            episode.write_text("video", encoding="utf-8")
            enriched = scan_enriched_library(source, lane="tv", probe_media=lambda _: MediaFacts())
            plan = build_tv_plan(source, enriched_report=enriched)

            results = build_tv_normalize_results(
                source,
                [episode],
                plan.proposed_changes,
                plan.warnings,
                parsed_tv=parsed_tv_from_enriched(enriched),
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["kind"], "tv_file")
        self.assertEqual(results[0]["series"], "Show")
        self.assertEqual(results[0]["season"], 1)
        self.assertEqual(results[0]["episode_first"], 2)
        self.assertEqual(results[0]["episode_title"], "Pilot")
        self.assertEqual(results[0]["projected_path"], "Show/Show - S01E02 - Pilot.mkv")
        self.assertEqual(results[0]["change_ids"], [f"{episode.relative_to(source)}#file"])
        self.assertNotIn("title_source", results[0])

    def test_build_profile_response_adds_render_identity_and_imdb_id(self) -> None:
        source = Path("/library")
        movie = source / "Arrival.2016.mkv"
        identity = parse_movie_identity(movie)
        report = MovieProfileReport(
            source_root=str(source),
            generated_at="2026-06-15T00:00:00+00:00",
            movies=[
                build_movie_profile_item(
                    source,
                    movie,
                    MediaFacts(width=1920, height=1080, video_bitrate_kbps=8000),
                    identity=IdentitySlot(lane="movie", value=identity),
                )
            ],
        )

        with patch("normal.web.serializers.resolve_imdb_ids", return_value=["tt2543164"]):
            payload = build_profile_response(source, report)

        self.assertEqual(payload["movies"][0]["title"], "Arrival")
        self.assertEqual(payload["movies"][0]["year"], 2016)
        self.assertEqual(payload["movies"][0]["imdb_id"], "tt2543164")

    def test_movie_normalize_changes_for_file_links_file_and_folder_changes(self) -> None:
        movie_path = Path("/library/Action/Movie.2000/Movie.mkv")
        relative_path = Path("Action/Movie.2000/Movie.mkv")
        changes = [
            ProposedChange("move", "file_move", "", "Curated/Movie.mkv", "safe", "", path=str(movie_path)),
            ProposedChange("rename", "file_rename", "", "Movie (2000).mkv", "review", "", path=str(movie_path)),
            ProposedChange("folder", "folder_rename", "Action/Movie.2000", "Action/Movie (2000)", "safe", ""),
            ProposedChange("other", "folder_rename", "Comedy", "Comedy 2", "safe", ""),
        ]

        linked = movie_normalize_changes_for_file(relative_path, movie_path, changes)

        self.assertEqual([change.item_id for change in linked], ["move", "rename", "folder"])

    def test_projected_movie_normalize_path_prefers_file_move(self) -> None:
        movie_path = Path("/library/Action/Movie.2000/Movie.mkv")
        changes = [
            ProposedChange("move", "file_move", "", "Curated/Movie (2000).mkv", "safe", "", path=str(movie_path)),
            ProposedChange("rename", "file_rename", "", "Ignored.mkv", "safe", "", path=str(movie_path)),
        ]

        projected = projected_movie_normalize_path(Path("Action/Movie.2000/Movie.mkv"), movie_path, changes)

        self.assertEqual(projected, Path("Curated/Movie (2000).mkv"))

    def test_projected_movie_normalize_path_applies_longest_folder_match_then_file_rename(self) -> None:
        movie_path = Path("/library/Movies/Marvel/Phase 1/Iron Man.mkv")
        changes = [
            ProposedChange("root", "folder_rename", "Movies", "Films", "safe", ""),
            ProposedChange("nested", "folder_rename", "Movies/Marvel", "Films/Marvel Studios", "safe", ""),
            ProposedChange("file", "file_rename", "", "Iron Man (2008).mkv", "safe", "", path=str(movie_path)),
        ]

        projected = projected_movie_normalize_path(Path("Movies/Marvel/Phase 1/Iron Man.mkv"), movie_path, changes)

        self.assertEqual(projected, Path("Films/Marvel Studios/Phase 1/Iron Man (2008).mkv"))

    def test_build_movie_normalize_results_sorts_and_sets_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            alpha = source / "B" / "Alpha.mkv"
            zulu = source / "A" / "Zulu.mkv"
            alpha.parent.mkdir()
            zulu.parent.mkdir()
            alpha.write_text("alpha", encoding="utf-8")
            zulu.write_text("zulu", encoding="utf-8")
            changes = [
                ProposedChange("rename-zulu", "file_rename", "", "Zulu (2001).mkv", "review", "", path=str(zulu)),
                ProposedChange("folder-alpha", "folder_rename", "B", "B Renamed", "safe", ""),
            ]

            results = build_movie_normalize_results(source, [alpha, zulu], changes)

        self.assertEqual([item["current_value"] for item in results], ["A/Zulu.mkv", "B/Alpha.mkv"])
        self.assertEqual(results[0]["confidence"], "review")
        self.assertTrue(results[0]["actionable"])
        self.assertEqual(results[0]["change_ids"], ["rename-zulu"])
        self.assertEqual(results[0]["projected_path"], "A/Zulu (2001).mkv")
        self.assertEqual(results[0]["linked_change_types"], ["file_rename"])
        self.assertEqual(results[1]["proposed_value"], "B Renamed/Alpha.mkv")
        self.assertEqual(results[1]["confidence"], "safe")

    def test_build_movie_normalize_results_exposes_warning_messages_and_linked_change_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.2000.mkv"
            movie.write_text("movie", encoding="utf-8")
            existing_target_folder = source / "Movie (2000)"
            existing_target_folder.mkdir()
            (existing_target_folder / "Movie (2000).mkv").write_text("existing", encoding="utf-8")

            from normal.movie_plan import build_movie_plan
            from normal.movie_scan import discover_video_files

            movie_files = discover_video_files(source)
            plan = build_movie_plan(source, movie_files=movie_files)
            results = build_movie_normalize_results(source, movie_files, plan.proposed_changes, plan.warnings)

        result = next(item for item in results if item["current_value"] == "Movie.2000.mkv")
        self.assertEqual(result["confidence"], "review")
        existing_target_result = next(item for item in results if item["current_value"] == "Movie (2000)/Movie (2000).mkv")
        self.assertIn("Movie normalization target already exists in the library.", existing_target_result["warning_messages"])
        self.assertTrue(any("Target path already exists in the library." in change["reason"] for change in result["linked_changes"]))

    def test_build_profile_response_merges_helper_payloads(self) -> None:
        report = MovieProfileReport(source_root="/library", generated_at="2026-05-23T00:00:00+00:00")
        standards = {"video": {"1080p": {"minimum_kbps": 2500}}}

        with patch("normal.web.serializers.build_histogram_payload", return_value={"movie_count": 3}) as histogram:
            with patch("normal.web.serializers.load_operator_preferences", return_value={"delete_mode": "recycle_all", "default_source": "/library"}):
                with patch("normal.web.serializers.library_policy_revision", return_value="policy-rev-1") as policy_revision:
                    with patch("normal.web.serializers.operator_preferences_revision", return_value="prefs-rev-1") as preferences_revision:
                        with patch("normal.web.serializers.build_policy_definitions", return_value=[{"label": "library_defaults"}]) as policy_definitions:
                            with patch("normal.web.serializers.movie_standards_revision", return_value="rev-1") as revision:
                                with patch("normal.web.serializers.build_movie_profile_definitions", return_value=[{"label": "library_grade"}]) as definitions:
                                    with patch(
                                        "normal.web.serializers.build_replacement_candidate_definition",
                                        return_value={"label": "replacement_candidate"},
                                    ) as replacement_definition:
                                        with patch(
                                            "normal.web.serializers.build_default_source_definition",
                                            return_value={"label": "default_source"},
                                        ) as default_source_definition:
                                            with patch(
                                                "normal.web.serializers.build_library_defaults_definition",
                                                return_value={"label": "library_defaults"},
                                            ) as library_defaults:
                                                with patch(
                                                    "normal.web.serializers.build_delete_mode_definition",
                                                    return_value={"label": "delete_mode"},
                                                ) as delete_mode_definition:
                                                    payload = build_profile_response(Path("/library"), report, standards=standards)

        histogram.assert_called_once_with(report)
        policy_revision.assert_called_once_with(standards)
        preferences_revision.assert_called_once_with({"delete_mode": "recycle_all", "default_source": "/library"})
        policy_definitions.assert_called_once_with(standards, {"delete_mode": "recycle_all", "default_source": "/library"})
        revision.assert_called_once_with(standards)
        definitions.assert_called_once_with(standards)
        replacement_definition.assert_called_once_with(standards)
        default_source_definition.assert_called_once_with({"delete_mode": "recycle_all", "default_source": "/library"})
        library_defaults.assert_called_once_with(standards)
        delete_mode_definition.assert_called_once_with({"delete_mode": "recycle_all", "default_source": "/library"})
        self.assertEqual(payload["policy"], standards)
        self.assertEqual(payload["policy_revision"], "policy-rev-1")
        self.assertEqual(payload["operator_preferences"], {"delete_mode": "recycle_all", "default_source": "/library"})
        self.assertEqual(payload["operator_preferences_revision"], "prefs-rev-1")
        self.assertEqual(payload["policy_definitions"], [{"label": "library_defaults"}])
        self.assertEqual(payload["default_source_definition"], {"label": "default_source"})
        self.assertEqual(payload["movie_standards"], standards)
        self.assertEqual(payload["histogram"], {"movie_count": 3})
        self.assertEqual(payload["movie_standards_revision"], "rev-1")
        self.assertNotIn("replacement_queue", payload)

    def test_build_updated_profile_items_skips_items_without_fact_dict(self) -> None:
        source = Path("/library")
        items = [
            {"path": "/library/Movie.mkv", "facts": {"video_codec": "h264"}},
            {"path": "/library/Skip.mkv", "facts": None},
        ]

        with patch("normal.web.serializers.media_facts_from_dict", return_value={"parsed": True}) as media_facts:
            with patch(
                "normal.web.serializers.build_movie_profile_item",
                return_value=FakeProfiledItem(path="/library/Movie.mkv", facts={"parsed": True}, status="ok"),
            ) as build_item:
                with patch("normal.web.serializers.load_library_policy", return_value={"subtitle_preferences": {}}):
                    with patch("normal.web.serializers.build_movie_repair_plan", return_value={"audio": {}, "subtitle": {}, "combined": {}, "issue_families": []}) as repair_plan:
                        updated = build_updated_profile_items(source, items)

        media_facts.assert_called_once_with({"video_codec": "h264"})
        build_item.assert_called_once_with(source, Path("/library/Movie.mkv"), {"parsed": True}, resolve_language=None)
        repair_plan.assert_called_once_with({"parsed": True}, path="/library/Movie.mkv", subtitle_preferences={"english_audio_subtitles": "forced_english", "foreign_audio_subtitles": "forced_english"}, resolve_language=None)
        self.assertEqual(updated, [{"path": "/library/Movie.mkv", "facts": {"parsed": True}, "status": "ok", "repair_plan": {"audio": {}, "subtitle": {}, "combined": {}, "issue_families": []}}])


if __name__ == "__main__":
    unittest.main()
