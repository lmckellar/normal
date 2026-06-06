from __future__ import annotations

import unittest

from normal.movie_repair_planner import build_movie_repair_plan
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts


def build_facts(
    *,
    default_audio_language: str = "ita",
    english_audio_default: bool = False,
    include_forced_english: bool = True,
    include_full_english: bool = True,
    default_subtitle_index: int | None = None,
) -> MediaFacts:
    audio_streams = [
        AudioStreamFacts(index=1, codec="ac3", language=default_audio_language, channels=6, bitrate_kbps=640, is_default=not english_audio_default),
        AudioStreamFacts(index=2, codec="ac3", language="eng", channels=6, bitrate_kbps=640, is_default=english_audio_default),
    ]
    subtitle_streams = []
    if include_forced_english:
        subtitle_streams.append(
            SubtitleStreamFacts(index=3, codec="subrip", language="eng", title="English Forced", is_default=default_subtitle_index == 3, is_forced=True)
        )
    if include_full_english:
        subtitle_streams.append(
            SubtitleStreamFacts(index=4, codec="subrip", language="eng", title="English", is_default=default_subtitle_index == 4, is_forced=False)
        )
    subtitle_streams.append(
        SubtitleStreamFacts(index=5, codec="subrip", language="ita", title="Italian", is_default=default_subtitle_index == 5, is_forced=False)
    )
    return MediaFacts(
        container="matroska",
        audio_stream_count=len(audio_streams),
        default_audio_streams=1,
        default_audio_stream_index=2 if english_audio_default else 1,
        audio_streams=audio_streams,
        subtitle_stream_count=len(subtitle_streams),
        default_subtitle_streams=sum(1 for stream in subtitle_streams if stream.is_default),
        default_subtitle_stream_index=default_subtitle_index,
        subtitle_streams=subtitle_streams,
    )


class MovieRepairPlannerTests(unittest.TestCase):
    def test_build_plan_marks_second_order_subtitle_when_audio_flip_changes_branch(self) -> None:
        facts = build_facts(default_audio_language="ita", default_subtitle_index=None)

        plan = build_movie_repair_plan(
            facts,
            path="/library/Movie.mkv",
            subtitle_preferences={
                "foreign_audio_subtitles": "off",
                "english_audio_subtitles": "forced_english",
            },
        )

        self.assertEqual(plan["audio"]["issue_code"], "default_non_english_audio")
        self.assertFalse(plan["subtitle"]["repairable"])
        self.assertTrue(plan["combined"]["staged"])
        self.assertTrue(plan["combined"]["second_order_subtitle"])
        self.assertEqual(plan["combined"]["subtitle_after_audio"]["issue_code"], "english_forced_not_default")
        self.assertTrue(plan["combined"]["subtitle_after_audio"]["repairable"])
        self.assertEqual(plan["combined"]["subtitle_after_audio"]["target_stream_index"], 3)

    def test_build_plan_preserves_forced_target_when_policy_matches_pre_and_post_audio(self) -> None:
        facts = build_facts(default_audio_language="ita", default_subtitle_index=5)

        plan = build_movie_repair_plan(
            facts,
            path="/library/Movie.mkv",
            subtitle_preferences={
                "foreign_audio_subtitles": "forced_english",
                "english_audio_subtitles": "forced_english",
            },
        )

        self.assertTrue(plan["subtitle"]["repairable"])
        self.assertEqual(plan["subtitle"]["target_stream_index"], 3)
        self.assertEqual(plan["combined"]["subtitle_after_audio"]["target_stream_index"], 3)
        self.assertFalse(plan["combined"]["second_order_subtitle"])


if __name__ == "__main__":
    unittest.main()
