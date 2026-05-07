from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_replacement_queue import (
    add_profile_items_to_queue,
    clear_pending_queue_items,
    delete_replacement_queue_media,
    dismiss_replacement_queue_items,
    history_title_key,
    load_queue,
    reconcile_replacement_queue,
)


def profile_item(path: Path, label: str, bitrate: int = 3000) -> dict:
    return {
        "path": str(path),
        "facts": {
            "resolution_bucket": "1080p",
            "video_bitrate_kbps": bitrate,
            "file_size_bytes": 1234,
        },
        "profile": {"label": label},
    }


def audio_packaging_item(path: Path, code: str) -> dict:
    return {
        "path": str(path),
        "facts": {
            "resolution_bucket": "1080p",
            "video_bitrate_kbps": 7000,
            "file_size_bytes": 1234,
        },
        "profile": {
            "label": "compressed_1080p",
            "diagnostics": [
                {
                    "code": code,
                    "summary": "Default audio is Italian while English is the weaker fallback.",
                }
            ],
        },
    }


class MovieReplacementQueueTests(unittest.TestCase):
    def test_adds_and_dedupes_strict_weak_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")

            first = add_profile_items_to_queue(source, [profile_item(movie, "unclassified")], state_path=state)
            second = add_profile_items_to_queue(source, [profile_item(movie, "unclassified")], state_path=state)

            self.assertEqual(len(first["added"]), 1)
            self.assertEqual(len(second["items"]), 1)
            self.assertEqual(second["items"][0]["title"], "Bad Movie")
            self.assertEqual(second["items"][0]["issue_family"], "weak_encode")

    def test_add_strips_zero_padded_collection_index_from_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Critters Collection" / "01 Critters 1 (1986).mkv"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")

            result = add_profile_items_to_queue(source, [profile_item(movie, "sd_low_quality")], state_path=state)

            self.assertEqual(result["items"][0]["title"], "Critters 1")
            self.assertEqual(result["items"][0]["year"], 1986)

    def test_add_uses_parent_folder_when_filename_has_year_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "The Long Goodbye" / "1973.mkv"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")

            result = add_profile_items_to_queue(source, [profile_item(movie, "sd_low_quality")], state_path=state)

            self.assertEqual(result["items"][0]["title"], "The Long Goodbye")
            self.assertEqual(result["items"][0]["year"], 1973)
            self.assertEqual(result["items"][0]["history_title_key"], "the long goodbye")

    def test_history_title_key_collapses_punctuation_and_unicode_prefix_variants(self) -> None:
        self.assertEqual(history_title_key("*batteries Not Included"), "batteries not included")
        self.assertEqual(history_title_key("\uf021batteries Not Included"), "batteries not included")
        self.assertEqual(history_title_key("Top Secret!"), "top secret")
        self.assertEqual(history_title_key("Robot & Frank"), "robot frank")

    def test_load_queue_keeps_identity_locked_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Robocop 3 Sci Fi (1993)" / "Robocop 3 Sci Fi (1993).mp4"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")
            state.write_text(
                """{
  "version": 2,
  "items": [
    {
      "item_id": "x",
      "source_root": "%s",
      "title": "Robocop 3",
      "year": 1993,
      "title_key": "robocop 3",
      "original_path": "%s",
      "original_folder_path": "%s",
      "mode": "file",
      "issue_family": "weak_encode",
      "original_profile_label": "sd_low_quality",
      "queued_at": "2026-01-01T00:00:00+00:00",
      "status": "deleted",
      "identity_locked": true
    }
  ]
}
"""
                % (source.resolve(), movie.resolve(), movie.parent.resolve()),
                encoding="utf-8",
            )

            result = load_queue(state)

            self.assertEqual(result["items"][0]["title"], "Robocop 3")
            self.assertEqual(result["items"][0]["title_key"], "robocop 3")
            self.assertEqual(result["items"][0]["history_title_key"], "robocop 3")

    def test_skips_non_strict_weak_and_unparsed_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            good = source / "Good Movie (2001)" / "Good Movie (2001).mkv"
            unparsed = source / "No Year" / "No Year.mkv"
            good.parent.mkdir(parents=True)
            unparsed.parent.mkdir()
            good.write_text("video", encoding="utf-8")
            unparsed.write_text("video", encoding="utf-8")

            result = add_profile_items_to_queue(
                source,
                [profile_item(good, "compressed_1080p"), profile_item(unparsed, "sd_low_quality")],
                state_path=state,
            )

            self.assertEqual(result["items"], [])
            self.assertEqual({item["reason"] for item in result["skipped"]}, {"not_strict_weak", "unparsed_identity"})

    def test_adds_audio_packaging_items_in_separate_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Audio Movie (2001)" / "Audio Movie (2001).mkv"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")

            result = add_profile_items_to_queue(
                source,
                [audio_packaging_item(movie, "default_non_english_audio_with_weak_english")],
                issue_family="audio_packaging",
                state_path=state,
            )

            self.assertEqual(len(result["items"]), 1)
            self.assertEqual(result["items"][0]["issue_family"], "audio_packaging")
            self.assertEqual(result["items"][0]["issue_code"], "default_non_english_audio_with_weak_english")

    def test_clear_pending_audio_packaging_items_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Audio Movie (2001)" / "Audio Movie (2001).mkv"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")

            add_profile_items_to_queue(
                source,
                [audio_packaging_item(movie, "default_non_english_audio")],
                issue_family="audio_packaging",
                state_path=state,
            )
            result = clear_pending_queue_items(
                source,
                [str(movie)],
                issue_family="audio_packaging",
                state_path=state,
            )

            self.assertEqual(len(result["cleared"]), 1)
            self.assertEqual(result["items"], [])

    def test_reconcile_completes_only_when_replacement_is_not_strict_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            weak = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            replacement = source / "Bad Movie (2001) [BluRay]" / "Bad Movie (2001) [BluRay].mkv"
            weak.parent.mkdir(parents=True)
            replacement.parent.mkdir()
            weak.write_text("video", encoding="utf-8")
            replacement.write_text("video", encoding="utf-8")

            add_profile_items_to_queue(source, [profile_item(weak, "sd_low_quality")], state_path=state)
            still_pending = reconcile_replacement_queue(source, [profile_item(replacement, "unclassified")], state_path=state)
            completed = reconcile_replacement_queue(source, [profile_item(replacement, "compressed_1080p", 7000)], state_path=state)

            self.assertEqual(still_pending["items"][0]["status"], "pending")
            self.assertEqual(completed["items"][0]["status"], "completed")
            self.assertEqual(completed["items"][0]["completed_by_path"], str(replacement.resolve()))

    def test_audio_packaging_reconcile_completes_when_replacement_is_no_longer_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            flagged = source / "Audio Movie (2001)" / "Audio Movie (2001).mkv"
            replacement = source / "Audio Movie (2001) [Remux]" / "Audio Movie (2001) [Remux].mkv"
            flagged.parent.mkdir(parents=True)
            replacement.parent.mkdir()
            flagged.write_text("video", encoding="utf-8")
            replacement.write_text("video", encoding="utf-8")

            add_profile_items_to_queue(
                source,
                [audio_packaging_item(flagged, "default_non_english_audio_with_weak_english")],
                issue_family="audio_packaging",
                state_path=state,
            )
            still_pending = reconcile_replacement_queue(
                source,
                [audio_packaging_item(replacement, "default_non_english_audio")],
                state_path=state,
            )
            completed = reconcile_replacement_queue(
                source,
                [profile_item(replacement, "compressed_1080p", 7000)],
                state_path=state,
            )

            self.assertEqual(still_pending["items"][0]["status"], "pending")
            self.assertEqual(completed["items"][0]["status"], "completed")

    def test_delete_file_mode_and_folder_mode_are_source_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            file_movie = source / "File Movie (2001)" / "File Movie (2001).mkv"
            folder_movie = source / "Folder Movie (2002)" / "Folder Movie (2002).mkv"
            file_movie.parent.mkdir(parents=True)
            folder_movie.parent.mkdir()
            file_movie.write_text("video", encoding="utf-8")
            folder_movie.write_text("video", encoding="utf-8")
            sidecar = folder_movie.parent / "poster.jpg"
            sidecar.write_text("image", encoding="utf-8")

            file_result = add_profile_items_to_queue(source, [profile_item(file_movie, "unclassified")], "file", state)
            folder_result = add_profile_items_to_queue(source, [profile_item(folder_movie, "unclassified")], "folder", state)
            item_ids = [file_result["added"][0]["item_id"], folder_result["added"][0]["item_id"]]

            result = delete_replacement_queue_media(source, item_ids, state_path=state)

            self.assertEqual(len(result["deleted"]), 2)
            self.assertEqual({item["status"] for item in result["items"]}, {"deleted"})
            self.assertFalse(file_movie.exists())
            self.assertFalse(folder_movie.parent.exists())
            self.assertEqual(result["skipped"], [])

    def test_file_delete_removes_parent_folder_when_only_safe_sidecars_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")
            poster = movie.parent / "poster.jpg"
            metadata = movie.parent / "movie.nfo"
            subtitle = movie.parent / "subtitle.srt"
            poster.write_text("image", encoding="utf-8")
            metadata.write_text("metadata", encoding="utf-8")
            subtitle.write_text("subtitle", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [profile_item(movie, "sd_low_quality")], state_path=state)
            result = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)

            self.assertEqual(len(result["deleted"]), 1)
            self.assertEqual(set(result["cleaned_sidecars"]), {str(poster), str(metadata), str(subtitle)})
            self.assertEqual(result["removed_folders"], [str(movie.parent)])
            self.assertFalse(movie.parent.exists())

    def test_file_delete_keeps_parent_folder_when_another_video_remains(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            folder = source / "Bad Movie (2001)"
            movie = folder / "Bad Movie (2001).mkv"
            other_video = folder / "Featurette (2001).mkv"
            poster = folder / "poster.jpg"
            folder.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")
            other_video.write_text("video", encoding="utf-8")
            poster.write_text("image", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [profile_item(movie, "sd_low_quality")], state_path=state)
            result = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)

            self.assertEqual(result["cleaned_sidecars"], [])
            self.assertEqual(result["removed_folders"], [])
            self.assertFalse(movie.exists())
            self.assertTrue(other_video.exists())
            self.assertTrue(poster.exists())

    def test_delete_marks_item_deleted_when_media_is_already_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Gone Movie (2001)" / "Gone Movie (2001).mp4"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [profile_item(movie, "sd_low_quality")], state_path=state)
            movie.unlink()

            result = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)

            self.assertEqual(len(result["deleted"]), 1)
            self.assertEqual(result["deleted"][0]["path"], str(movie.resolve()))
            self.assertEqual(result["items"][0]["status"], "deleted")
            self.assertEqual(result["skipped"], [])

    def test_deleted_items_await_replacement_then_complete_on_good_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            weak = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            replacement = source / "Bad Movie (2001) [BluRay]" / "Bad Movie (2001) [BluRay].mkv"
            weak.parent.mkdir(parents=True)
            weak.write_text("video", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [profile_item(weak, "sd_low_quality")], state_path=state)
            deleted = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)

            self.assertEqual(deleted["items"][0]["status"], "deleted")
            self.assertIsNotNone(deleted["items"][0]["deleted_at"])
            self.assertFalse(weak.exists())

            replacement.parent.mkdir()
            replacement.write_text("video", encoding="utf-8")
            completed = reconcile_replacement_queue(
                source,
                [profile_item(replacement, "compressed_1080p", 7000)],
                state_path=state,
            )

            self.assertEqual(completed["items"][0]["status"], "completed")
            self.assertEqual(completed["items"][0]["completed_by_path"], str(replacement.resolve()))

    def test_deleted_items_can_be_dismissed_from_queue_without_touching_media(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            weak = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            replacement = source / "Bad Movie (2001) [BluRay]" / "Bad Movie (2001) [BluRay].mkv"
            weak.parent.mkdir(parents=True)
            weak.write_text("video", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [profile_item(weak, "sd_low_quality")], state_path=state)
            deleted = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)
            dismissed = dismiss_replacement_queue_items(source, [deleted["items"][0]["item_id"]], state_path=state)

            self.assertEqual(dismissed["items"][0]["status"], "dismissed")
            self.assertIsNotNone(dismissed["items"][0]["dismissed_at"])

            replacement.parent.mkdir()
            replacement.write_text("video", encoding="utf-8")
            reconciled = reconcile_replacement_queue(
                source,
                [profile_item(replacement, "compressed_1080p", 7000)],
                state_path=state,
            )

            self.assertEqual(reconciled["items"][0]["status"], "dismissed")

    def test_requeue_clears_dismissed_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "movies"
            movie = source / "Bad Movie (2001)" / "Bad Movie (2001).mkv"
            movie.parent.mkdir(parents=True)
            movie.write_text("video", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [profile_item(movie, "sd_low_quality")], state_path=state)
            deleted = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)
            dismiss_replacement_queue_items(source, [deleted["items"][0]["item_id"]], state_path=state)
            requeued = add_profile_items_to_queue(source, [profile_item(movie, "sd_low_quality")], state_path=state)

            self.assertEqual(requeued["items"][0]["status"], "pending")
            self.assertIsNone(requeued["items"][0]["dismissed_at"])

    def test_load_queue_migrates_deleted_pending_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = Path(tmpdir) / "queue.json"
            state.write_text(
                '{"version": 1, "items": [{"item_id": "1", "status": "pending", "deleted_at": "now"}]}',
                encoding="utf-8",
            )

            payload = load_queue(state)

            self.assertEqual(payload["items"][0]["status"], "deleted")

    def test_load_queue_repairs_stored_title_from_original_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = Path(tmpdir) / "queue.json"
            original_path = str(Path(tmpdir) / "movies" / "Critters Collection" / "01 Critters 1 (1986).mkv")
            state.write_text(
                (
                    '{"version": 1, "items": [{'
                    '"item_id": "1", "status": "deleted", "source_root": "src", '
                    '"title": "01 Critters 1", "year": 1986, "title_key": "01 critters 1", '
                    f'"original_path": "{original_path}"'
                    '}]}'
                ),
                encoding="utf-8",
            )

            payload = load_queue(state)

            self.assertEqual(payload["items"][0]["title"], "Critters 1")
            self.assertEqual(payload["items"][0]["title_key"], "critters 1")

    def test_load_queue_repairs_year_leading_bracket_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = Path(tmpdir) / "queue.json"
            original_path = str(
                Path(tmpdir)
                / "movies"
                / "Planet of the Apes Collection"
                / " (1973) [BATTLE FOR THE PLANET OF APES 1080p H 264 MULTI moviesbyrizzo]"
                / " (1973) [BATTLE FOR THE PLANET OF APES 1080p H 264 MULTI moviesbyrizzo].mp4"
            )
            state.write_text(
                (
                    '{"version": 1, "items": [{'
                    '"item_id": "1", "status": "deleted", "source_root": "src", '
                    '"title": "", "year": 1973, "title_key": "", '
                    f'"original_path": "{original_path}"'
                    '}]}'
                ),
                encoding="utf-8",
            )

            payload = load_queue(state)

            self.assertEqual(payload["items"][0]["title"], "Battle For The Planet Of Apes")
            self.assertEqual(payload["items"][0]["title_key"], "battle for the planet of apes")


if __name__ == "__main__":
    unittest.main()
