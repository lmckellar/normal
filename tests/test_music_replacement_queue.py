from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.music_replacement_queue import (
    add_profile_items_to_queue,
    delete_replacement_queue_media,
    load_queue,
    reconcile_replacement_queue,
)


def track_item(path: Path, label: str, bitrate: int = 128, album_artist: str | None = "Artist", album: str | None = "Album") -> dict:
    return {
        "path": str(path),
        "facts": {
            "bitrate_kbps": bitrate,
            "format": "mp3",
            "file_size_bytes": 1234,
            "album_artist": album_artist,
            "artist": None,
            "album": album,
        },
        "profile": {"label": label},
    }


class MusicReplacementQueueTests(unittest.TestCase):
    def test_adds_and_dedupes_mp3_trash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            track = source / "Artist" / "Album" / "track.mp3"
            track.parent.mkdir(parents=True)
            track.write_text("audio", encoding="utf-8")

            first = add_profile_items_to_queue(source, [track_item(track, "mp3_trash")], state_path=state)
            second = add_profile_items_to_queue(source, [track_item(track, "mp3_trash")], state_path=state)

            self.assertEqual(len(first["added"]), 1)
            self.assertEqual(len(second["items"]), 1)

    def test_adds_unknown_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            track = source / "Artist" / "Album" / "track.mp3"
            track.parent.mkdir(parents=True)
            track.write_text("audio", encoding="utf-8")

            result = add_profile_items_to_queue(source, [track_item(track, "unknown_unreadable")], state_path=state)

            self.assertEqual(len(result["added"]), 1)
            self.assertEqual(result["items"][0]["original_profile_label"], "unknown_unreadable")

    def test_skips_mp3_high_quality_and_flac(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            high = source / "Artist" / "Album" / "high.mp3"
            flac = source / "Artist" / "Album" / "track.flac"
            high.parent.mkdir(parents=True)
            high.write_text("audio", encoding="utf-8")
            flac.write_text("audio", encoding="utf-8")

            result = add_profile_items_to_queue(
                source,
                [
                    track_item(high, "mp3_high_quality", bitrate=320),
                    track_item(flac, "flac_16_44_1"),
                ],
                state_path=state,
            )

            self.assertEqual(result["items"], [])
            self.assertEqual(len(result["skipped"]), 2)
            self.assertTrue(all(s["reason"] == "not_strict_weak" for s in result["skipped"]))

    def test_source_root_scoping_prevents_outside_source_addition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            outside = root / "other" / "Artist" / "Album" / "track.mp3"
            outside.parent.mkdir(parents=True)
            outside.write_text("audio", encoding="utf-8")
            source.mkdir()

            result = add_profile_items_to_queue(source, [track_item(outside, "mp3_trash")], state_path=state)

            self.assertEqual(result["items"], [])
            self.assertEqual(result["skipped"][0]["reason"], "outside_source")

    def test_album_level_reconcile_completes_deleted_and_pending_when_non_weak_same_album_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            weak = source / "Artist" / "Album" / "track.mp3"
            replacement = source / "Artist" / "Album" / "track.flac"
            weak.parent.mkdir(parents=True)
            weak.write_text("audio", encoding="utf-8")
            replacement.write_text("audio", encoding="utf-8")

            add_profile_items_to_queue(source, [track_item(weak, "mp3_trash")], state_path=state)
            still_pending = reconcile_replacement_queue(
                source,
                [track_item(replacement, "mp3_trash", album_artist="Artist", album="Album")],
                state_path=state,
            )
            completed = reconcile_replacement_queue(
                source,
                [track_item(replacement, "flac_16_44_1", album_artist="Artist", album="Album")],
                state_path=state,
            )

            self.assertEqual(still_pending["items"][0]["status"], "pending")
            self.assertEqual(completed["items"][0]["status"], "completed")
            self.assertEqual(completed["items"][0]["completed_by_path"], str(replacement.resolve()))

    def test_deletion_removes_file_and_safe_sidecars_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            track = source / "Artist" / "Album" / "track.mp3"
            track.parent.mkdir(parents=True)
            track.write_text("audio", encoding="utf-8")
            cover = track.parent / "cover.jpg"
            log = track.parent / "rip.log"
            cover.write_text("image", encoding="utf-8")
            log.write_text("log", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [track_item(track, "mp3_trash")], state_path=state)
            result = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)

            self.assertEqual(len(result["deleted"]), 1)
            self.assertFalse(track.exists())
            self.assertEqual(set(result["cleaned_sidecars"]), {str(cover), str(log)})
            self.assertEqual(result["removed_folders"], [str(track.parent)])
            self.assertFalse(track.parent.exists())

    def test_deletion_preserves_folder_when_another_music_file_remains(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            track1 = source / "Artist" / "Album" / "track1.mp3"
            track2 = source / "Artist" / "Album" / "track2.flac"
            track1.parent.mkdir(parents=True)
            track1.write_text("audio", encoding="utf-8")
            track2.write_text("audio", encoding="utf-8")
            cover = track1.parent / "cover.jpg"
            cover.write_text("image", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [track_item(track1, "mp3_trash")], state_path=state)
            result = delete_replacement_queue_media(source, [queued["added"][0]["item_id"]], state_path=state)

            self.assertFalse(track1.exists())
            self.assertTrue(track2.exists())
            self.assertTrue(cover.exists())
            self.assertEqual(result["cleaned_sidecars"], [])
            self.assertEqual(result["removed_folders"], [])

    def test_deletion_is_source_root_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state = root / "queue.json"
            source = root / "music"
            track = source / "Artist" / "Album" / "track.mp3"
            track.parent.mkdir(parents=True)
            track.write_text("audio", encoding="utf-8")

            queued = add_profile_items_to_queue(source, [track_item(track, "mp3_trash")], state_path=state)
            item_id = queued["added"][0]["item_id"]

            other_source = root / "other_music"
            other_source.mkdir()
            result = delete_replacement_queue_media(other_source, [item_id], state_path=state)

            self.assertEqual(result["deleted"], [])
            self.assertTrue(track.exists())

    def test_load_queue_migrates_deleted_pending_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state = Path(tmpdir) / "queue.json"
            state.write_text(
                '{"version": 1, "items": [{"item_id": "1", "status": "pending", "deleted_at": "now"}]}',
                encoding="utf-8",
            )

            payload = load_queue(state)

            self.assertEqual(payload["items"][0]["status"], "deleted")


if __name__ == "__main__":
    unittest.main()
