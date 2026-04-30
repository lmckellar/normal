from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_profile import (
    build_histogram_payload,
    classify_profile_label,
    detect_plex_diagnostics,
    looks_like_absolute_numbering,
    scan_movie_profiles,
)
from normal.quality_review import MediaFacts


class MovieProfileTests(unittest.TestCase):
    def test_classify_profile_label_marks_small_1080p_as_minimum_acceptable(self) -> None:
        label = classify_profile_label(
            MediaFacts(
                runtime_seconds=90 * 60,
                file_size_bytes=int(4.5 * 1024 * 1024 * 1024),
                width=1920,
                height=1080,
                video_bitrate_kbps=5000,
                audio_bitrate_kbps=192,
            )
        )

        self.assertEqual(label, "minimum_acceptable_1080p")

    def test_classify_profile_label_uses_kind_floor_for_compressed_tiers(self) -> None:
        compressed_1080p = classify_profile_label(
            MediaFacts(width=1920, height=1080, video_bitrate_kbps=6000)
        )
        compressed_4k = classify_profile_label(
            MediaFacts(width=3840, height=2160, video_bitrate_kbps=6000)
        )

        self.assertEqual(compressed_1080p, "compressed_1080p")
        self.assertEqual(compressed_4k, "compressed_4k")

    def test_classify_profile_label_names_high_bitrate_1080p_as_uhd(self) -> None:
        label = classify_profile_label(
            MediaFacts(width=1920, height=1080, video_bitrate_kbps=16000)
        )

        self.assertEqual(label, "1080p_uhd")

    def test_classify_profile_label_names_weak_resolution_tiers(self) -> None:
        weak_1080p = classify_profile_label(
            MediaFacts(width=1916, height=952, video_bitrate_kbps=1962)
        )
        weak_4k = classify_profile_label(
            MediaFacts(width=3840, height=2160, video_bitrate_kbps=5500)
        )

        self.assertEqual(weak_1080p, "weak_1080p")
        self.assertEqual(weak_4k, "weak_4k")

    def test_detect_plex_diagnostics_flags_image_subtitles_and_multiple_defaults(self) -> None:
        findings = detect_plex_diagnostics(
            "Show - s01e01.mkv",
            MediaFacts(
                container="matroska",
                subtitle_codecs=["hdmv_pgs_subtitle"],
                default_audio_streams=2,
                default_subtitle_streams=1,
            )
        )

        codes = {finding.code for finding in findings}
        self.assertIn("image_subtitle_transcode_risk", codes)
        self.assertIn("multiple_default_streams", codes)

    def test_detect_plex_diagnostics_flags_dts_and_anime_visibility_risks(self) -> None:
        findings = detect_plex_diagnostics(
            "Berserk 01.mkv",
            MediaFacts(
                container="matroska",
                audio_codecs=["dts"],
                audio_stream_count=3,
                subtitle_codecs=["ass"],
                attachment_stream_count=5,
            ),
        )

        codes = {finding.code for finding in findings}
        self.assertIn("dts_no_compat_track", codes)
        self.assertIn("anime_subtitle_attachment_risk", codes)
        self.assertIn("anime_absolute_numbering_risk", codes)
        self.assertIn("attachment_heavy_visibility_risk", codes)

    def test_looks_like_absolute_numbering_accepts_plain_anime_episode_names(self) -> None:
        self.assertTrue(looks_like_absolute_numbering("Berserk 01.mkv"))
        self.assertFalse(looks_like_absolute_numbering("Show.S01E01.mkv"))

    def test_scan_movie_profiles_assigns_profile_and_percentile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "First.1999.1080p.mkv"
            second = source / "Second.1999.1080p.mkv"
            first.write_text("video", encoding="utf-8")
            second.write_text("video", encoding="utf-8")

            fake_facts = {
                first: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=3_000 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    video_bitrate_kbps=3500,
                    audio_bitrate_kbps=128,
                ),
                second: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=25_000 * 1024 * 1024,
                    width=3840,
                    height=2160,
                    video_bitrate_kbps=46000,
                    audio_bitrate_kbps=4000,
                ),
            }

            report = scan_movie_profiles(source, probe_media=lambda path: fake_facts[path])

            self.assertEqual(len(report.movies), 2)
            first_item = next(item for item in report.movies if item.path == str(first))
            second_item = next(item for item in report.movies if item.path == str(second))
            self.assertEqual(first_item.profile.label, "weak_1080p")
            self.assertEqual(second_item.profile.label, "4k_remux")
            self.assertEqual(first_item.profile.percentile, 100.0)
            self.assertIn("playback_risk", first_item.profile.risk_counts)

    def test_build_histogram_payload_summarizes_bitrates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Only.1999.1080p.mkv"
            movie.write_text("video", encoding="utf-8")
            report = scan_movie_profiles(
                source,
                probe_media=lambda _: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=3_000 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    video_bitrate_kbps=3500,
                    audio_bitrate_kbps=128,
                ),
            )

            payload = build_histogram_payload(report)

            self.assertEqual(payload["movie_count"], 1)
            self.assertEqual(payload["profile_counts"]["weak_1080p"], 1)
            self.assertEqual(payload["video_bitrate_kbps"]["median"], 3500.0)
            self.assertIn("risk_counts", payload)

    def test_scan_movie_profiles_can_cancel_between_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "First.1999.1080p.mkv"
            second = source / "Second.1999.1080p.mkv"
            first.write_text("video", encoding="utf-8")
            second.write_text("video", encoding="utf-8")
            calls = 0

            def probe(_: Path) -> MediaFacts:
                nonlocal calls
                calls += 1
                return MediaFacts(width=1920, height=1080, video_bitrate_kbps=3500)

            report = scan_movie_profiles(source, probe_media=probe, should_cancel=lambda: calls >= 1)

            self.assertEqual(calls, 1)
            self.assertEqual(len(report.movies), 1)
            self.assertEqual(report.warnings[0].code, "movie_profile_cancelled")


if __name__ == "__main__":
    unittest.main()
