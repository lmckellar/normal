from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_repair_fix import build_execution_plan, fix_movie_repair_default
from normal.movie_repair_planner import build_movie_repair_plan
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
    *,
    english_audio_default: bool = False,
    default_subtitle_index: int | None = 5,
    subtitle_default_count: int | None = None,
) -> MediaFacts:
    audio_streams = [
        AudioStreamFacts(index=1, codec="ac3", language="ita", channels=6, bitrate_kbps=640, is_default=not english_audio_default),
        AudioStreamFacts(index=2, codec="ac3", language="eng", channels=6, bitrate_kbps=640, is_default=english_audio_default),
        AudioStreamFacts(index=3, codec="aac", language=None, channels=2, bitrate_kbps=192, is_default=False),
    ]
    subtitle_streams = [
        SubtitleStreamFacts(index=4, codec="subrip", language="eng", title="English Forced", is_default=default_subtitle_index == 4, is_forced=True),
        SubtitleStreamFacts(index=5, codec="subrip", language="eng", title="English", is_default=default_subtitle_index == 5, is_forced=False),
        SubtitleStreamFacts(index=6, codec="subrip", language="ita", title="Italian", is_default=default_subtitle_index == 6, is_forced=False),
    ]
    return MediaFacts(
        container="matroska",
        runtime_seconds=120,
        audio_stream_count=len(audio_streams),
        default_audio_streams=1,
        default_audio_stream_index=2 if english_audio_default else 1,
        audio_streams=audio_streams,
        subtitle_stream_count=len(subtitle_streams),
        default_subtitle_streams=subtitle_default_count if subtitle_default_count is not None else sum(1 for stream in subtitle_streams if stream.is_default),
        default_subtitle_stream_index=default_subtitle_index,
        subtitle_streams=subtitle_streams,
    )


class MovieRepairFixTests(unittest.TestCase):
    def test_drop_foreign_audio_does_not_apply_to_subtitle_only_row(self) -> None:
        facts = build_facts(english_audio_default=True, default_subtitle_index=6)
        plan = build_movie_repair_plan(
            facts,
            path="/library/Movie.mkv",
            subtitle_preferences={
                "foreign_audio_subtitles": "forced_english",
                "english_audio_subtitles": "forced_english",
            },
        )

        execution = build_execution_plan(
            facts,
            plan,
            include_audio=True,
            include_subtitle=True,
            drop_foreign_audio=True,
        )

        self.assertFalse(execution["audio_mutation"])
        self.assertFalse(execution["drop_foreign_audio"])
        self.assertEqual(execution["kept_audio_ordinals"], [0, 1, 2])
        self.assertTrue(execution["subtitle_mutation"])

    def test_combined_fix_runs_single_mux_with_audio_and_subtitle_dispositions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")
            commands: list[list[str]] = []

            def probe_media(path: Path) -> MediaFacts:
                if path == movie:
                    return build_facts(english_audio_default=False, default_subtitle_index=6)
                return MediaFacts(
                    container="matroska",
                    audio_stream_count=2,
                    default_audio_streams=1,
                    audio_streams=[
                        AudioStreamFacts(index=2, codec="ac3", language="eng", channels=6, bitrate_kbps=640, is_default=True),
                        AudioStreamFacts(index=3, codec="aac", language=None, channels=2, bitrate_kbps=192, is_default=False),
                    ],
                    subtitle_stream_count=3,
                    default_subtitle_streams=1,
                    subtitle_streams=[
                        SubtitleStreamFacts(index=4, codec="subrip", language="eng", title="English Forced", is_default=True, is_forced=True),
                        SubtitleStreamFacts(index=5, codec="subrip", language="eng", title="English", is_default=False, is_forced=False),
                        SubtitleStreamFacts(index=6, codec="subrip", language="ita", title="Italian", is_default=False, is_forced=False),
                    ],
                )

            def fake_popen(command: list[str], text: bool, stdout, stderr):
                del text, stdout, stderr
                commands.append(command)
                return FakePopen(command, Path(command[-1]))

            with patch("normal.movie_repair_fix.subprocess.Popen", side_effect=fake_popen):
                result = fix_movie_repair_default(
                    movie,
                    include_audio=True,
                    include_subtitle=True,
                    drop_foreign_audio=True,
                    probe_media=probe_media,
                    subtitle_preferences={
                        "foreign_audio_subtitles": "off",
                        "english_audio_subtitles": "forced_english",
                    },
                )

            self.assertEqual(result.status, "fixed")
            self.assertEqual(result.message, "english_default_subtitle_normalized_and_foreign_audio_removed")
            self.assertEqual(movie.read_text(encoding="utf-8"), "fixed")
            self.assertEqual(len(commands), 1)
            self.assertIn("-0:a:0", commands[0])
            self.assertEqual(commands[0][commands[0].index("-disposition:a:0") + 1], "default")
            self.assertEqual(commands[0][commands[0].index("-disposition:a:1") + 1], "0")
            self.assertEqual(commands[0][commands[0].index("-disposition:s:0") + 1], "default+forced")
            self.assertEqual(commands[0][commands[0].index("-disposition:s:1") + 1], "0")
            self.assertEqual(commands[0][commands[0].index("-disposition:s:2") + 1], "0")

    def test_combined_fix_skips_when_no_repairable_changes_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")

            result = fix_movie_repair_default(
                movie,
                include_audio=True,
                include_subtitle=True,
                probe_media=lambda _: build_facts(english_audio_default=True, default_subtitle_index=4),
                subtitle_preferences={
                    "foreign_audio_subtitles": "forced_english",
                    "english_audio_subtitles": "forced_english",
                },
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.message, "already_repaired")


if __name__ == "__main__":
    unittest.main()
