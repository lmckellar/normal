from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_audio_fix import build_ffmpeg_progress_update, fix_english_audio_default
from normal.quality_review import AudioStreamFacts, MediaFacts


def build_facts(default_language: str, english_default: bool = False, *, include_untagged: bool = False) -> MediaFacts:
    audio_streams = [
        AudioStreamFacts(index=1, language=default_language, channels=6, bitrate_kbps=640, is_default=not english_default),
        AudioStreamFacts(index=2, language="eng", channels=6, bitrate_kbps=640, is_default=english_default),
    ]
    if include_untagged:
        audio_streams.append(AudioStreamFacts(index=3, language=None, channels=2, bitrate_kbps=192, is_default=False))
    return MediaFacts(
        audio_stream_count=len(audio_streams),
        default_audio_streams=1,
        audio_streams=audio_streams,
    )


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


class MovieAudioFixTests(unittest.TestCase):
    def test_build_ffmpeg_progress_update_computes_fraction_and_eta(self) -> None:
        update = build_ffmpeg_progress_update(
            {"out_time_us": "30000000", "total_size": "1048576", "speed": "2.0x", "progress": "continue"},
            input_duration_seconds=120,
            source_path=Path("/tmp/Movie.mkv"),
            temp_path=Path("/tmp/Movie.tmp.mkv"),
        )

        self.assertAlmostEqual(update["progress_fraction"], 0.25)
        self.assertEqual(update["eta_seconds"], 45)
        self.assertEqual(update["output_size_bytes"], 1048576)
        self.assertEqual(update["speed"], "2.0x")

    def test_fixes_mkv_by_setting_english_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")
            commands: list[list[str]] = []

            def probe_media(path: Path) -> MediaFacts:
                return build_facts("ita", english_default=False) if path == movie else build_facts("ita", english_default=True)

            def fake_popen(command: list[str], text: bool, stdout, stderr):
                del text, stdout, stderr
                commands.append(command)
                return FakePopen(command, Path(command[-1]))

            with patch("normal.movie_audio_fix.subprocess.Popen", side_effect=fake_popen):
                result = fix_english_audio_default(movie, probe_media=probe_media)

            self.assertEqual(result.status, "fixed")
            self.assertEqual(result.message, "english_default_set")
            self.assertEqual(movie.read_text(encoding="utf-8"), "fixed")
            self.assertIn("-disposition:a:0", commands[0])
            self.assertIn("-disposition:a:1", commands[0])
            self.assertEqual(commands[0][commands[0].index("-disposition:a:0") + 1], "0")
            self.assertEqual(commands[0][commands[0].index("-disposition:a:1") + 1], "default")

    def test_fixes_mkv_and_drops_tagged_foreign_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")
            commands: list[list[str]] = []

            def probe_media(path: Path) -> MediaFacts:
                if path == movie:
                    return build_facts("ita", english_default=False, include_untagged=True)
                return MediaFacts(
                    audio_stream_count=2,
                    default_audio_streams=1,
                    audio_streams=[
                        AudioStreamFacts(index=2, language="eng", channels=6, bitrate_kbps=640, is_default=True),
                        AudioStreamFacts(index=3, language=None, channels=2, bitrate_kbps=192, is_default=False),
                    ],
                )

            def fake_popen(command: list[str], text: bool, stdout, stderr):
                del text, stdout, stderr
                commands.append(command)
                return FakePopen(command, Path(command[-1]))

            with patch("normal.movie_audio_fix.subprocess.Popen", side_effect=fake_popen):
                result = fix_english_audio_default(movie, probe_media=probe_media, drop_foreign_audio=True)

            self.assertEqual(result.status, "fixed")
            self.assertEqual(result.message, "english_default_set_and_removed_foreign_audio")
            self.assertIn("-map", commands[0])
            self.assertIn("-0:a:0", commands[0])
            self.assertEqual(commands[0][commands[0].index("-disposition:a:0") + 1], "default")
            self.assertEqual(commands[0][commands[0].index("-disposition:a:1") + 1], "0")

    def test_skips_when_english_is_already_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")

            result = fix_english_audio_default(movie, probe_media=lambda _: build_facts("ita", english_default=True))

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.message, "already_default_english")

    def test_skips_unsupported_container(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mp4"
            movie.write_text("original", encoding="utf-8")

            result = fix_english_audio_default(movie)

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.message, "unsupported_container")

    def test_drop_foreign_audio_reports_when_nothing_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie = Path(tmpdir) / "Movie (2001).mkv"
            movie.write_text("original", encoding="utf-8")

            def probe_media(path: Path) -> MediaFacts:
                if path == movie:
                    return MediaFacts(
                        audio_stream_count=2,
                        default_audio_streams=1,
                        audio_streams=[
                            AudioStreamFacts(index=1, language=None, channels=6, bitrate_kbps=640, is_default=True),
                            AudioStreamFacts(index=2, language="eng", channels=6, bitrate_kbps=640, is_default=False),
                        ],
                    )
                return MediaFacts(
                    audio_stream_count=2,
                    default_audio_streams=1,
                    audio_streams=[
                        AudioStreamFacts(index=1, language=None, channels=6, bitrate_kbps=640, is_default=False),
                        AudioStreamFacts(index=2, language="eng", channels=6, bitrate_kbps=640, is_default=True),
                    ],
                )

            def fake_popen(command: list[str], text: bool, stdout, stderr):
                del text, stdout, stderr
                return FakePopen(command, Path(command[-1]))

            with patch("normal.movie_audio_fix.subprocess.Popen", side_effect=fake_popen):
                result = fix_english_audio_default(movie, probe_media=probe_media, drop_foreign_audio=True)

            self.assertEqual(result.status, "fixed")
            self.assertEqual(result.message, "english_default_set_no_foreign_audio_removed")


if __name__ == "__main__":
    unittest.main()
