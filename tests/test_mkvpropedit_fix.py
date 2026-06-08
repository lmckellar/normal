from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from normal.mkvpropedit_fix import (
    build_instant_progress_update,
    build_mkvpropedit_command,
    run_mkvpropedit,
)
from normal.movie_repair_fix import build_execution_plan, fix_movie_repair_default
from normal.movie_repair_planner import build_movie_repair_plan
from normal.quality_review import MediaFacts

from tests.test_movie_repair_fix import build_facts


SUBTITLE_PREFS = {"foreign_audio_subtitles": "off", "english_audio_subtitles": "english"}


def multiple_default_facts() -> MediaFacts:
    # English audio already default; two subtitle streams flagged default (like the
    # real Big Trouble In Little China file) so the repair targets the English sub.
    return build_facts(english_audio_default=True, default_subtitle_index=5, subtitle_default_count=2)


def repaired_facts() -> MediaFacts:
    return build_facts(english_audio_default=True, default_subtitle_index=5)


class BuildCommandTests(unittest.TestCase):
    def test_subtitle_command_targets_default_and_preserves_forced(self) -> None:
        command = build_mkvpropedit_command(
            Path("/library/Movie.mkv"),
            subtitle_defaults=[False, True, False],
            subtitle_forced=[True, False, False],
        )
        self.assertEqual(command[:2], ["mkvpropedit", "/library/Movie.mkv"])
        self.assertIn("track:s1", command)
        self.assertIn("track:s2", command)
        s2 = command.index("track:s2")
        self.assertEqual(command[s2 + 2], "flag-default=1")
        self.assertEqual(command[s2 + 4], "flag-forced=0")
        s1 = command.index("track:s1")
        self.assertEqual(command[s1 + 2], "flag-default=0")
        self.assertEqual(command[s1 + 4], "flag-forced=1")

    def test_audio_command_uses_per_type_one_based_addressing(self) -> None:
        command = build_mkvpropedit_command(
            Path("/library/Movie.mkv"),
            audio_defaults=[False, True],
        )
        self.assertIn("track:a1", command)
        self.assertIn("track:a2", command)
        a2 = command.index("track:a2")
        self.assertEqual(command[a2 + 2], "flag-default=1")
        self.assertNotIn("track:s1", command)


class RunMkvpropeditTests(unittest.TestCase):
    def test_returncode_two_raises(self) -> None:
        with patch(
            "normal.mkvpropedit_fix.subprocess.run",
            return_value=SimpleNamespace(returncode=2, stderr="boom", stdout=""),
        ):
            with self.assertRaises(RuntimeError):
                run_mkvpropedit(Path("/library/Movie.mkv"), ["mkvpropedit"])

    def test_warning_returncode_is_accepted_and_emits_terminal_progress(self) -> None:
        updates: list[dict] = []
        with patch(
            "normal.mkvpropedit_fix.subprocess.run",
            return_value=SimpleNamespace(returncode=1, stderr="", stdout=""),
        ):
            run_mkvpropedit(Path("/library/Movie.mkv"), ["mkvpropedit"], progress_callback=updates.append)
        self.assertEqual(updates[0]["progress_fraction"], 0.0)
        self.assertEqual(updates[-1]["progress_fraction"], 1.0)
        self.assertEqual(updates[-1]["progress_state"], "end")


class ClassifierTests(unittest.TestCase):
    def _execution(self, facts: MediaFacts, *, drop_foreign_audio: bool) -> dict:
        plan = build_movie_repair_plan(facts, path="/library/Movie.mkv", subtitle_preferences=SUBTITLE_PREFS)
        return build_execution_plan(
            facts,
            plan,
            include_audio=True,
            include_subtitle=True,
            drop_foreign_audio=drop_foreign_audio,
        )

    def test_subtitle_only_repair_is_metadata_only(self) -> None:
        execution = self._execution(multiple_default_facts(), drop_foreign_audio=False)
        self.assertTrue(execution["subtitle_mutation"])
        self.assertTrue(execution["metadata_only"])

    def test_track_drop_is_not_metadata_only(self) -> None:
        # Non-English default audio so the foreign-audio prune actually engages.
        facts = build_facts(english_audio_default=False, default_subtitle_index=5, subtitle_default_count=2)
        execution = self._execution(facts, drop_foreign_audio=True)
        self.assertTrue(execution["drop_foreign_audio"])
        self.assertFalse(execution["metadata_only"])


class FastLaneIntegrationTests(unittest.TestCase):
    def test_metadata_only_repair_uses_mkvpropedit_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")
            commands: list[list[str]] = []
            probes = [multiple_default_facts(), repaired_facts()]

            def probe_media(path: Path) -> MediaFacts:
                return probes.pop(0) if len(probes) > 1 else probes[0]

            def fake_run(command, **kwargs):
                commands.append(command)
                # mkvpropedit lands the english default; reflected by the second probe.
                return SimpleNamespace(returncode=0, stderr="", stdout="")

            with patch("normal.movie_repair_fix.mkvpropedit_available", return_value=True), patch(
                "normal.mkvpropedit_fix.subprocess.run", side_effect=fake_run
            ), patch("normal.movie_repair_fix.subprocess.Popen", side_effect=AssertionError("ffmpeg must not run")):
                result = fix_movie_repair_default(
                    movie,
                    include_audio=False,
                    include_subtitle=True,
                    probe_media=probe_media,
                    subtitle_preferences=SUBTITLE_PREFS,
                )

            self.assertEqual(result.status, "fixed")
            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0][0], "mkvpropedit")
            self.assertEqual(movie.read_text(encoding="utf-8"), "original")  # edited in place, no temp swap

    def test_falls_back_to_ffmpeg_when_mkvpropedit_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")
            popen_calls: list[list[str]] = []

            class FakePopen:
                def __init__(self, command, **kwargs):
                    popen_calls.append(command)
                    self.stdout = iter(["progress=end\n"])
                    self.stderr = self
                    Path(command[-1]).write_text("fixed", encoding="utf-8")

                def read(self) -> str:
                    return ""

                def wait(self) -> int:
                    return 0

            def probe_media(path: Path) -> MediaFacts:
                if path == movie:
                    return multiple_default_facts()
                return repaired_facts()

            with patch("normal.movie_repair_fix.mkvpropedit_available", return_value=False), patch(
                "normal.movie_repair_fix.subprocess.Popen", side_effect=FakePopen
            ):
                result = fix_movie_repair_default(
                    movie,
                    include_audio=False,
                    include_subtitle=True,
                    probe_media=probe_media,
                    subtitle_preferences=SUBTITLE_PREFS,
                )

            self.assertEqual(result.status, "fixed")
            self.assertEqual(len(popen_calls), 1)
            self.assertEqual(popen_calls[0][0], "ffmpeg")


if __name__ == "__main__":
    unittest.main()
