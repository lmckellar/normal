from __future__ import annotations

import unittest

from normal.quality_review import (
    MediaFacts,
    classify_resolution,
    effective_display_dimensions,
    parse_name_resolution_hint,
    score_quality_review,
)


class QualityReviewTests(unittest.TestCase):
    def test_classify_resolution_uses_cropped_height_for_hd_buckets(self) -> None:
        self.assertEqual(classify_resolution(1916, 952), "1080p")
        self.assertEqual(classify_resolution(1920, 800), "1080p")
        self.assertEqual(classify_resolution(1440, 1080), "720p")
        self.assertEqual(classify_resolution(1440, 1080, sample_aspect_ratio="4:3"), "1080p")

    def test_classify_resolution_falls_back_when_aspect_ratio_is_unusable(self) -> None:
        self.assertEqual(classify_resolution(1440, 1080, sample_aspect_ratio="0:1"), "720p")
        self.assertEqual(classify_resolution(1440, 1080, sample_aspect_ratio="N/A"), "720p")

    def test_effective_display_dimensions_respects_orientation(self) -> None:
        self.assertEqual(effective_display_dimensions(1440, 1080, "4:3"), (1920, 1080))
        self.assertEqual(effective_display_dimensions(1080, 1440, "3:4"), (810, 1440))

    def test_score_quality_review_marks_low_bitrate_1080p_as_severe(self) -> None:
        review = score_quality_review(
            MediaFacts(
                runtime_seconds=7200,
                file_size_bytes=2_400 * 1024 * 1024,
                width=1920,
                height=1080,
                video_codec="h264",
                video_bitrate_kbps=2800,
                audio_bitrate_kbps=128,
                audio_channels=2,
            ),
            path="Movie.1080p.mkv",
        )

        self.assertEqual(review.status, "severe")
        self.assertEqual(review.confidence, "high")
        self.assertEqual(review.facts.resolution_bucket, "1080p")
        self.assertIn("low_video_bitrate", {reason.code for reason in review.reasons})

    def test_score_quality_review_uses_mb_per_min_when_bitrate_is_missing(self) -> None:
        review = score_quality_review(
            MediaFacts(
                runtime_seconds=7200,
                file_size_bytes=1_300 * 1024 * 1024,
                width=1920,
                height=1080,
                video_codec="h264",
                audio_bitrate_kbps=192,
                audio_channels=6,
            ),
            path="Movie.mkv",
        )

        self.assertEqual(review.status, "review")
        self.assertEqual(review.confidence, "medium")
        self.assertIn("low_mb_per_min", {reason.code for reason in review.reasons})

    def test_score_quality_review_flags_resolution_mismatch(self) -> None:
        review = score_quality_review(
            MediaFacts(
                runtime_seconds=6000,
                file_size_bytes=900 * 1024 * 1024,
                width=1280,
                height=720,
                video_codec="h264",
                video_bitrate_kbps=1700,
                audio_bitrate_kbps=128,
                audio_channels=2,
            ),
            path="Movie.1080p.mkv",
        )

        self.assertEqual(review.status, "severe")
        self.assertIn("resolution_mismatch", {reason.code for reason in review.reasons})

    def test_score_quality_review_is_unscored_without_core_signals(self) -> None:
        review = score_quality_review(
            MediaFacts(
                file_size_bytes=700 * 1024 * 1024,
                audio_codec="aac",
            ),
            path="Movie.mkv",
        )

        self.assertEqual(review.status, "unscored")
        self.assertEqual(review.confidence, "low")

    def test_score_quality_review_can_approximate_video_bitrate(self) -> None:
        review = score_quality_review(
            MediaFacts(
                runtime_seconds=7200,
                file_size_bytes=2_800 * 1024 * 1024,
                width=1920,
                height=1080,
                total_bitrate_kbps=3400,
                audio_bitrate_kbps=192,
                audio_channels=6,
            ),
            path="Movie.1080p.mkv",
        )

        self.assertTrue(review.facts.video_bitrate_approximate)
        self.assertEqual(review.facts.video_bitrate_kbps, 3208)
        self.assertEqual(review.status, "review")

    def test_parse_name_resolution_hint_normalizes_4k(self) -> None:
        self.assertEqual(parse_name_resolution_hint("Movie.4K.Remux.mkv"), "2160p")


if __name__ == "__main__":
    unittest.main()
