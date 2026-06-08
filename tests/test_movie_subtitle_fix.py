from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_subtitle_fix import choose_subtitle_fix_plan, fix_movie_subtitle_default
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts


class FakePopen:
    def __init__(self, command: list[str], output_path: Path, progress_lines: list[str] | None = None):
        self.command = command
        self.stdout = iter(progress_lines or ["out_time_us=30000000\n", "total_size=1048576\n", "speed=2.0x\n", "progress=end\n"])
        self.stderr = self
        self._output_path = output_path
        self._output_path.write_text("fixed", encoding="utf-8")

    def read(self) -> str:
        return ""

    def wait(self) -> int:
        return 0


def build_facts(
    default_audio_language: str = "eng",
    *,
    default_subtitle: int | None = None,
    forced_default: bool = False,
    multiple_defaults: bool = False,
) -> MediaFacts:
    subtitle_streams = [
        SubtitleStreamFacts(index=2, codec="subrip", language="eng", title="English Forced", is_default=forced_default or multiple_defaults, is_forced=True),
        SubtitleStreamFacts(index=3, codec="subrip", language="eng", title="English", is_default=(default_subtitle == 1) or multiple_defaults, is_forced=False),
        SubtitleStreamFacts(index=4, codec="subrip", language="ita", title="Italian", is_default=default_subtitle == 2, is_forced=False),
    ]
    return MediaFacts(
        container="matroska",
        default_audio_streams=1,
        audio_streams=[AudioStreamFacts(index=1, codec="ac3", language=default_audio_language, channels=6, bitrate_kbps=640, is_default=True)],
        subtitle_stream_count=len(subtitle_streams),
        default_subtitle_streams=sum(1 for stream in subtitle_streams if stream.is_default),
        subtitle_streams=subtitle_streams,
    )


class MovieSubtitleFixTests(unittest.TestCase):
    def test_choose_plan_defaults_forced_english_for_english_audio_under_conservative_policy(self) -> None:
        plan = choose_subtitle_fix_plan(build_facts(default_audio_language="eng", default_subtitle=1))

        self.assertEqual(plan.target_ordinal, 0)
        self.assertEqual(plan.success_message, "english_forced_defaulted")

    def test_choose_plan_targets_forced_english_even_with_non_english_default_audio(self) -> None:
        facts = build_facts(default_audio_language="ita", default_subtitle=2)
        plan = choose_subtitle_fix_plan(facts)

        self.assertEqual(plan.target_ordinal, 0)
        self.assertEqual(plan.success_message, "english_forced_defaulted")

    def test_choose_plan_targets_first_english_for_non_english_default_audio_when_no_forced_exists(self) -> None:
        facts = build_facts(default_audio_language="ita", default_subtitle=2)
        facts.subtitle_streams[0].is_forced = False
        plan = choose_subtitle_fix_plan(facts)

        self.assertEqual(plan.target_ordinal, 0)
        self.assertEqual(plan.success_message, "english_subtitle_defaulted")

    def test_choose_plan_targets_full_english_for_english_audio_when_requested(self) -> None:
        facts = build_facts(default_audio_language="eng", default_subtitle=1)
        facts.subtitle_streams[0].is_forced = False
        plan = choose_subtitle_fix_plan(facts, subtitle_preferences={"english_audio_subtitles": "english"})

        self.assertEqual(plan.target_ordinal, 1)
        self.assertEqual(plan.success_message, "english_subtitle_defaulted")

    def test_choose_plan_targets_forced_english_for_english_audio_when_requested(self) -> None:
        facts = build_facts(default_audio_language="eng", default_subtitle=1)
        plan = choose_subtitle_fix_plan(facts, subtitle_preferences={"english_audio_subtitles": "forced_english"})

        self.assertEqual(plan.target_ordinal, 0)
        self.assertEqual(plan.success_message, "english_forced_defaulted")

    def test_choose_plan_keeps_subtitles_off_for_english_audio_when_forced_requested_but_missing(self) -> None:
        facts = build_facts(default_audio_language="eng", default_subtitle=1)
        facts.subtitle_streams[0].is_forced = False
        plan = choose_subtitle_fix_plan(facts, subtitle_preferences={"english_audio_subtitles": "forced_english"})

        self.assertIsNone(plan.target_ordinal)
        self.assertEqual(plan.success_message, "subtitle_defaults_cleared")

    def test_choose_plan_targets_primary_language_for_english_audio_when_requested(self) -> None:
        facts = build_facts(default_audio_language="eng", default_subtitle=1)
        facts.subtitle_streams[0].is_forced = False
        plan = choose_subtitle_fix_plan(facts, subtitle_preferences={"english_audio_subtitles": "primary_language"})

        self.assertEqual(plan.target_ordinal, 1)
        self.assertEqual(plan.success_message, "english_subtitle_defaulted")

    def test_choose_plan_targets_full_english_for_non_english_audio_when_requested(self) -> None:
        facts = build_facts(default_audio_language="ita", default_subtitle=2)
        plan = choose_subtitle_fix_plan(facts, subtitle_preferences={"foreign_audio_subtitles": "english"})

        self.assertEqual(plan.target_ordinal, 1)
        self.assertEqual(plan.success_message, "english_subtitle_defaulted")

    def test_choose_plan_clears_default_for_non_english_audio_when_off_requested(self) -> None:
        facts = build_facts(default_audio_language="ita", default_subtitle=2)
        plan = choose_subtitle_fix_plan(facts, subtitle_preferences={"foreign_audio_subtitles": "off"})

        self.assertIsNone(plan.target_ordinal)
        self.assertEqual(plan.success_message, "subtitle_defaults_cleared")

    def test_fixes_mkv_by_setting_forced_english_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")
            commands: list[list[str]] = []

            def probe_media(path: Path) -> MediaFacts:
                if path == movie:
                    return build_facts(default_audio_language="ita", default_subtitle=1)
                return build_facts(default_audio_language="ita", forced_default=True)

            def fake_popen(command: list[str], text: bool, stdout, stderr):
                del text, stdout, stderr
                commands.append(command)
                return FakePopen(command, Path(command[-1]))

            with patch("normal.movie_subtitle_fix.subprocess.Popen", side_effect=fake_popen):
                result = fix_movie_subtitle_default(movie, probe_media=probe_media)

            self.assertEqual(result.status, "fixed")
            self.assertEqual(result.message, "english_forced_defaulted")
            self.assertEqual(movie.read_text(encoding="utf-8"), "fixed")
            # Forced English target keeps its forced bit when promoted to default, so a
            # re-probe still sees a forced track and the issue actually resolves.
            self.assertEqual(commands[0][commands[0].index("-disposition:s:0") + 1], "default+forced")
            self.assertEqual(commands[0][commands[0].index("-disposition:s:1") + 1], "0")

    def test_fixes_mkv_by_clearing_unnecessary_subtitle_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")
            commands: list[list[str]] = []

            def probe_media(path: Path) -> MediaFacts:
                if path == movie:
                    facts = build_facts(default_audio_language="eng", default_subtitle=1)
                    facts.subtitle_streams[0].is_forced = False
                    return facts
                cleared = build_facts(default_audio_language="eng", default_subtitle=None)
                cleared.subtitle_streams[0].is_forced = False
                return cleared

            def fake_popen(command: list[str], text: bool, stdout, stderr):
                del text, stdout, stderr
                commands.append(command)
                return FakePopen(command, Path(command[-1]))

            with patch("normal.movie_subtitle_fix.subprocess.Popen", side_effect=fake_popen):
                result = fix_movie_subtitle_default(movie, probe_media=probe_media)

            self.assertEqual(result.status, "fixed")
            self.assertEqual(result.message, "subtitle_defaults_cleared")
            self.assertEqual(commands[0][commands[0].index("-disposition:s:0") + 1], "0")
            self.assertEqual(commands[0][commands[0].index("-disposition:s:1") + 1], "0")

    def test_skips_when_already_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")

            result = fix_movie_subtitle_default(movie, probe_media=lambda _: build_facts(default_audio_language="ita", forced_default=True))

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.message, "already_repaired")


if __name__ == "__main__":
    unittest.main()
