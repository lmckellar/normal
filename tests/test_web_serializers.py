from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from normal.models import ProposedChange
from normal.movie_profile import MovieProfileReport
from normal.web.serializers import (
    build_movie_normalize_results,
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

    def test_build_profile_response_merges_helper_payloads(self) -> None:
        report = MovieProfileReport(source_root="/library", generated_at="2026-05-23T00:00:00+00:00")
        standards = {"video": {"1080p": {"minimum_kbps": 2500}}}

        with patch("normal.web.serializers.build_histogram_payload", return_value={"movie_count": 3}) as histogram:
            with patch("normal.web.serializers.reconcile_replacement_queue", return_value={"items": []}) as queue:
                with patch("normal.web.serializers.movie_standards_revision", return_value="rev-1") as revision:
                    with patch("normal.web.serializers.build_movie_profile_definitions", return_value=[{"label": "library_grade"}]) as definitions:
                        with patch(
                            "normal.web.serializers.build_replacement_candidate_definition",
                            return_value={"label": "replacement_candidate"},
                        ) as replacement_definition:
                            payload = build_profile_response(Path("/library"), report, standards=standards)

        histogram.assert_called_once_with(report)
        queue.assert_called_once_with(Path("/library"), [])
        revision.assert_called_once_with(standards)
        definitions.assert_called_once_with(standards)
        replacement_definition.assert_called_once_with(standards)
        self.assertEqual(payload["movie_standards"], standards)
        self.assertEqual(payload["histogram"], {"movie_count": 3})
        self.assertEqual(payload["replacement_queue"], {"items": []})
        self.assertEqual(payload["movie_standards_revision"], "rev-1")

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
                updated = build_updated_profile_items(source, items)

        media_facts.assert_called_once_with({"video_codec": "h264"})
        build_item.assert_called_once_with(source, Path("/library/Movie.mkv"), {"parsed": True})
        self.assertEqual(updated, [{"path": "/library/Movie.mkv", "facts": {"parsed": True}, "status": "ok"}])


if __name__ == "__main__":
    unittest.main()
