from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.music_profile import (
    MusicFacts,
    build_music_histogram_payload,
    classify_music_profile,
    scan_music_profiles,
)


class MusicProfileTests(unittest.TestCase):
    def test_classifies_mp3_trash_at_or_below_floor(self) -> None:
        self.assertEqual(classify_music_profile(MusicFacts(format="mp3", bitrate_kbps=256)), "mp3_trash")
        self.assertEqual(classify_music_profile(MusicFacts(format="mp3")), "mp3_trash")

    def test_classifies_high_quality_mp3_above_floor(self) -> None:
        self.assertEqual(classify_music_profile(MusicFacts(format="mp3", bitrate_kbps=320)), "mp3_high_quality")

    def test_classifies_flac_sample_rate_brackets(self) -> None:
        self.assertEqual(classify_music_profile(MusicFacts(format="flac", sample_rate_hz=44100)), "flac_44_1")
        self.assertEqual(classify_music_profile(MusicFacts(format="flac", sample_rate_hz=44100, bits_per_sample=16)), "flac_16_44_1")
        self.assertEqual(classify_music_profile(MusicFacts(format="flac", sample_rate_hz=48000, bits_per_sample=24)), "flac_24_48")
        self.assertEqual(classify_music_profile(MusicFacts(format="flac", sample_rate_hz=96000, bits_per_sample=24)), "flac_24_96")
        self.assertEqual(classify_music_profile(MusicFacts(format="flac", sample_rate_hz=192000, bits_per_sample=24)), "flac_24_192")

    def test_scan_music_profiles_reports_unreadable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            track = source / "Artist" / "Album" / "track.mp3"
            track.parent.mkdir(parents=True)
            track.write_text("not audio", encoding="utf-8")

            report = scan_music_profiles(
                source,
                read_track=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
            )

            self.assertEqual(report.tracks[0].profile.label, "unknown_unreadable")
            self.assertEqual(report.warnings[0].code, "music_profile_read_error")

    def test_histogram_counts_profiles_and_library_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "Artist" / "Album" / "01.flac"
            second = source / "Artist" / "Album" / "02.mp3"
            first.parent.mkdir(parents=True)
            first.write_bytes(b"flac")
            second.write_bytes(b"mp3")

            facts = {
                first: MusicFacts(format="flac", sample_rate_hz=44100, bits_per_sample=16, file_size_bytes=4, album_artist="Artist", album="Album"),
                second: MusicFacts(format="mp3", bitrate_kbps=320, file_size_bytes=3, album_artist="Artist", album="Album"),
            }
            report = scan_music_profiles(source, read_track=lambda path: facts[path])
            histogram = build_music_histogram_payload(report)

            self.assertEqual(histogram["track_count"], 2)
            self.assertEqual(histogram["album_count"], 1)
            self.assertEqual(histogram["artist_count"], 1)
            self.assertEqual(histogram["total_size_bytes"], 7)
            self.assertEqual(histogram["profile_counts"]["flac_16_44_1"], 1)
            self.assertEqual(histogram["profile_counts"]["mp3_high_quality"], 1)


if __name__ == "__main__":
    unittest.main()
