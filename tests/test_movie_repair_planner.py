from __future__ import annotations

import unittest

from normal.movie_repair_planner import audio_repair_issue_code, build_movie_repair_plan
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


class MovieRepairPlannerForeignAudioTests(unittest.TestCase):
    def test_audio_repair_issue_code_suppresses_confirmed_foreign_original(self) -> None:
        facts = build_facts(default_audio_language="jpn")

        self.assertEqual(audio_repair_issue_code(facts), "default_non_english_audio")
        self.assertEqual(
            audio_repair_issue_code(
                facts, title="Seven Samurai", year=1954, resolve_language=lambda title, year: "japanese"
            ),
            "",
        )

    def test_audio_repair_issue_code_fails_open_when_unknown_or_english(self) -> None:
        facts = build_facts(default_audio_language="jpn")
        for resolver in (None, lambda title, year: None, lambda title, year: "english"):
            self.assertEqual(
                audio_repair_issue_code(facts, title="Some Title", year=2000, resolve_language=resolver),
                "default_non_english_audio",
            )

    def test_build_movie_repair_plan_threads_resolver_to_drop_foreign_from_queue(self) -> None:
        facts = build_facts(default_audio_language="jpn")
        plan = build_movie_repair_plan(
            facts,
            path="/movies/Seven Samurai (1954)/Seven Samurai (1954).mkv",
            resolve_language=lambda title, year: "japanese",
        )

        self.assertEqual(plan["audio"]["issue_code"], "")
        self.assertFalse(plan["audio"]["repairable"])
        self.assertNotIn("audio", plan["issue_families"])


class MovieRepairPlannerTests(unittest.TestCase):
    def test_build_plan_repairs_flag_only_forced_english_subtitle(self) -> None:
        # Forced via the container flag alone — plain "English" title, no "Forced"
        # text — so this proves the disposition path, not the title regex.
        audio_streams = [
            AudioStreamFacts(index=1, codec="ac3", language="eng", channels=6, bitrate_kbps=640, is_default=True),
        ]
        subtitle_streams = [
            SubtitleStreamFacts(index=2, codec="hdmv_pgs_subtitle", language="eng", title="English", is_default=False, is_forced=True),
            SubtitleStreamFacts(index=3, codec="hdmv_pgs_subtitle", language="eng", title="English", is_default=False, is_forced=False),
        ]
        facts = MediaFacts(
            container="matroska",
            audio_stream_count=len(audio_streams),
            default_audio_streams=1,
            default_audio_stream_index=1,
            audio_streams=audio_streams,
            subtitle_stream_count=len(subtitle_streams),
            default_subtitle_streams=0,
            default_subtitle_stream_index=None,
            subtitle_streams=subtitle_streams,
        )

        plan = build_movie_repair_plan(
            facts,
            path="/library/Movie.mkv",
            subtitle_preferences={
                "foreign_audio_subtitles": "forced_english",
                "english_audio_subtitles": "forced_english",
            },
        )

        self.assertEqual(plan["subtitle"]["issue_code"], "english_forced_not_default")
        self.assertTrue(plan["subtitle"]["repairable"])
        self.assertTrue(plan["subtitle"]["target_forced"])
        self.assertEqual(plan["subtitle"]["target_stream_index"], 2)

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

    def test_second_order_subtitle_stage_exposes_target_mode_for_preview(self) -> None:
        # The preview projects subtitle_after_audio.mode/target_stream_index, so the
        # planner must keep emitting them for the second-order forced-English case.
        facts = build_facts(default_audio_language="ita", default_subtitle_index=None)

        plan = build_movie_repair_plan(
            facts,
            path="/library/Movie.mkv",
            subtitle_preferences={
                "foreign_audio_subtitles": "off",
                "english_audio_subtitles": "forced_english",
            },
        )

        sub = plan["combined"]["subtitle_after_audio"]
        self.assertTrue(sub["repairable"])
        self.assertEqual(sub["mode"], "target")
        self.assertEqual(sub["target_stream_index"], 3)

    def test_clear_mode_subtitle_plan_for_unnecessary_default(self) -> None:
        # English audio with an Italian default subtitle and an "off" policy resolves
        # to a clear (no target) — the preview renders this as an intentional
        # "no subtitle default" landing rather than an unresolved node.
        facts = build_facts(
            default_audio_language="ita",
            english_audio_default=True,
            include_forced_english=False,
            include_full_english=False,
            default_subtitle_index=5,
        )

        plan = build_movie_repair_plan(
            facts,
            path="/library/Movie.mkv",
            subtitle_preferences={
                "foreign_audio_subtitles": "off",
                "english_audio_subtitles": "off",
            },
        )

        sub = plan["subtitle"]
        self.assertEqual(sub["issue_code"], "unnecessary_default_subtitle")
        self.assertTrue(sub["repairable"])
        self.assertEqual(sub["mode"], "clear")
        self.assertIsNone(sub["target_stream_index"])

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
