from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_profile import (
    build_movie_profile_definitions,
    build_histogram_payload,
    classify_profile_label,
    classify_standard_label,
    detect_plex_diagnostics,
    looks_like_absolute_numbering,
    scan_movie_profiles,
    evaluate_movie_standards,
    update_movie_profile_definition,
)
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts, build_audio_summary


class MovieProfileTests(unittest.TestCase):
    def test_build_audio_summary_formats_common_home_theater_variants(self) -> None:
        self.assertEqual(build_audio_summary("aac", 2)[-1], "AAC 2.0")
        self.assertEqual(build_audio_summary("ac3", 6)[-1], "Dolby Digital 5.1")
        self.assertEqual(build_audio_summary("eac3", 6, "Dolby Digital Plus + Dolby Atmos")[-1], "Dolby Digital Plus 5.1 Atmos")
        self.assertEqual(build_audio_summary("truehd", 8, "Dolby Atmos")[-1], "Dolby TrueHD 7.1 Atmos")
        self.assertEqual(build_audio_summary("dts", 6, "DTS-HD Master Audio")[-1], "DTS-HD MA 5.1")
        self.assertEqual(build_audio_summary("pcm_s16le", 2)[-1], "PCM 2.0")

    def test_classify_profile_label_keeps_legacy_bitrate_label_for_compatibility(self) -> None:
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

    def test_evaluate_movie_standards_flags_missing_forced_default_inline(self) -> None:
        results = evaluate_movie_standards(
            Path("Movie (2001)/Movie (2001).mkv"),
            MediaFacts(
                container="matroska",
                width=1920,
                height=1080,
                video_bitrate_kbps=6000,
                audio_codec="ac3",
                audio_bitrate_kbps=640,
                audio_channels=6,
                audio_streams=[AudioStreamFacts(index=1, codec="ac3", bitrate_kbps=640, channels=6, language="eng", is_default=True)],
                subtitle_streams=[
                    SubtitleStreamFacts(index=2, codec="subrip", language="eng", title="English Forced", is_default=False, is_forced=True),
                ],
                default_audio_streams=1,
                default_audio_stream_index=1,
            ),
            {},
        )

        subtitle = next(result for result in results if result["domain"] == "subtitle_setup")
        self.assertEqual(subtitle["status"], "review_low_confidence")
        self.assertEqual(subtitle["code"], "english_forced_not_default")

    def test_classify_standard_label_marks_failed_core_standard_as_replacement_candidate(self) -> None:
        label = classify_standard_label(
            [
                {"domain": "video_minimum", "status": "fail", "code": "video_below_minimum", "summary": "", "confidence": "high"},
                {"domain": "audio_minimum", "status": "pass", "code": "audio_meets_minimum", "summary": "", "confidence": "high"},
            ],
            {"weak_candidate_rules": {"any_failed_domains": ["video_minimum", "audio_minimum"]}},
        )

        self.assertEqual(label, "replacement_candidate")

    def test_build_movie_profile_definitions_exposes_dashboard_owned_controls(self) -> None:
        definitions = build_movie_profile_definitions()

        self.assertEqual([definition["label"] for definition in definitions], ["replacement_candidate", "needs_review", "meets_minimum", "reference"])
        self.assertEqual(definitions[0]["fields"][0]["key"], "failed_domains")
        self.assertEqual(definitions[-1]["fields"][0]["key"], "video_1080p_reference_kbps")

    def test_update_movie_profile_definition_persists_reference_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", path):
                standards = update_movie_profile_definition(
                    "reference",
                    {
                        "video_1080p_reference_kbps": "18000",
                        "video_2160p_reference_kbps": "26000",
                        "audio_reference_codecs": "truehd, dtshd, flac",
                    },
                )

            self.assertEqual(standards["video"]["1080p"]["reference_kbps"], 18000)
            self.assertEqual(standards["video"]["2160p"]["reference_kbps"], 26000)
            self.assertEqual(standards["audio"]["reference_codecs"], ["truehd", "dtshd", "flac"])
            self.assertIn('"reference_kbps": 18000', path.read_text(encoding="utf-8"))

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

    def test_detect_plex_diagnostics_flags_default_non_english_audio_with_weak_english(self) -> None:
        findings = detect_plex_diagnostics(
            "Movie.mkv",
            MediaFacts(
                container="matroska",
                audio_stream_count=2,
                default_audio_streams=1,
                audio_streams=[
                    AudioStreamFacts(index=1, codec="ac3", bitrate_kbps=640, channels=6, language="ita", is_default=True),
                    AudioStreamFacts(index=2, codec="aac", bitrate_kbps=128, channels=2, language="eng", is_default=False),
                ],
            ),
        )

        codes = {finding.code for finding in findings}
        self.assertIn("default_non_english_audio_with_weak_english", codes)

    def test_detect_plex_diagnostics_flags_default_non_english_audio_even_when_english_is_not_weaker(self) -> None:
        findings = detect_plex_diagnostics(
            "Movie.mkv",
            MediaFacts(
                container="matroska",
                audio_stream_count=2,
                default_audio_streams=1,
                audio_streams=[
                    AudioStreamFacts(index=1, codec="ac3", bitrate_kbps=640, channels=6, language="ita", is_default=True),
                    AudioStreamFacts(index=2, codec="ac3", bitrate_kbps=640, channels=6, language="eng", is_default=False),
                ],
            ),
        )

        codes = {finding.code for finding in findings}
        self.assertIn("default_non_english_audio", codes)

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
            self.assertEqual(first_item.profile.label, "replacement_candidate")
            self.assertEqual(second_item.profile.label, "needs_review")
            self.assertFalse(second_item.profile.weak_candidate)
            self.assertTrue(first_item.profile.weak_candidate)
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
            self.assertEqual(payload["profile_counts"]["replacement_candidate"], 1)
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
