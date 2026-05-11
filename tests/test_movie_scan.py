from __future__ import annotations

import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_scan import (
    MovieScanProgress,
    choose_display_audio_stream,
    discover_video_files,
    extract_year_hint,
    media_facts_from_ffprobe_payload,
    run_ffprobe,
    score_replacement_priority,
    scan_movie_library,
)
from normal.quality_review import AudioStreamFacts, MediaFacts


class MovieScanTests(unittest.TestCase):
    def test_discover_video_files_ignores_hidden_and_sidecar_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Movie.mkv"
            hidden_sidecar = source / "._Movie.mkv"
            poster = source / "Movie.jpg"
            nested_hidden = source / ".stash" / "Secret.mkv"
            movie.touch()
            hidden_sidecar.touch()
            poster.touch()
            nested_hidden.parent.mkdir()
            nested_hidden.touch()

            discovered = discover_video_files(source)

            self.assertEqual(discovered, [movie])

    def test_run_ffprobe_reports_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie_path = Path(tmpdir) / "Movie.mkv"
            movie_path.touch()

            with patch("normal.movie_scan.subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 30)):
                with self.assertRaisesRegex(RuntimeError, "ffprobe timed out"):
                    run_ffprobe(movie_path)

    def test_media_facts_from_ffprobe_payload_extracts_primary_streams(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie_path = Path(tmpdir) / "Movie.mkv"
            movie_path.write_bytes(b"x" * 100)

            facts = media_facts_from_ffprobe_payload(
                {
                    "format": {
                        "duration": "7200.2",
                        "size": "1048576000",
                        "bit_rate": "4200000",
                        "format_name": "matroska,webm",
                    },
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1920,
                            "height": 1080,
                            "bit_rate": "3500000",
                        },
                        {
                            "codec_type": "audio",
                            "codec_name": "aac",
                            "channels": 2,
                            "bit_rate": "128000",
                        },
                    ],
                },
                movie_path,
            )

            self.assertEqual(facts.runtime_seconds, 7200)
            self.assertEqual(facts.file_size_bytes, 1048576000)
            self.assertEqual(facts.container, "matroska")
            self.assertEqual(facts.video_bitrate_kbps, 3500)
            self.assertEqual(facts.audio_bitrate_kbps, 128)
            self.assertEqual(facts.total_bitrate_kbps, 4200)

    def test_media_facts_from_ffprobe_payload_reads_mkv_bps_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie_path = Path(tmpdir) / "Movie.mkv"
            movie_path.write_bytes(b"x" * 100)

            facts = media_facts_from_ffprobe_payload(
                {
                    "format": {
                        "duration": "7200",
                        "size": "1048576000",
                        "bit_rate": "4200000",
                        "format_name": "matroska,webm",
                    },
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "hevc",
                            "width": 1920,
                            "height": 1080,
                            "tags": {"BPS-eng": "3931961"},
                        },
                        {
                            "codec_type": "audio",
                            "codec_name": "aac",
                            "channels": 2,
                            "tags": {"BPS": "128000"},
                        },
                    ],
                },
                movie_path,
            )

            self.assertEqual(facts.video_bitrate_kbps, 3931)
            self.assertEqual(facts.audio_bitrate_kbps, 128)

    def test_media_facts_from_ffprobe_payload_captures_audio_stream_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie_path = Path(tmpdir) / "Movie.mkv"
            movie_path.write_bytes(b"x" * 100)

            facts = media_facts_from_ffprobe_payload(
                {
                    "format": {
                        "duration": "7200",
                        "size": "1048576000",
                        "bit_rate": "6000000",
                        "format_name": "matroska,webm",
                    },
                    "streams": [
                        {
                            "index": 0,
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1920,
                            "height": 1080,
                            "bit_rate": "5000000",
                        },
                        {
                            "index": 1,
                            "codec_type": "audio",
                            "codec_name": "ac3",
                            "channels": 6,
                            "bit_rate": "640000",
                            "profile": "Dolby Digital",
                            "disposition": {"default": 1},
                            "tags": {"language": "ita", "title": "Italian 5.1"},
                        },
                        {
                            "index": 2,
                            "codec_type": "audio",
                            "codec_name": "aac",
                            "channels": 2,
                            "bit_rate": "128000",
                            "disposition": {"default": 0},
                            "tags": {"language": "eng", "title": "English stereo"},
                        },
                    ],
                },
                movie_path,
            )

            self.assertEqual(len(facts.audio_streams), 2)
            self.assertEqual(facts.audio_streams[0].language, "ita")
            self.assertTrue(facts.audio_streams[0].is_default)
            self.assertEqual(facts.audio_streams[0].profile, "Dolby Digital")
            self.assertEqual(facts.audio_streams[1].language, "eng")
            self.assertEqual(facts.audio_streams[1].title, "English stereo")
            self.assertEqual(facts.audio_display_stream_index, 1)
            self.assertEqual(facts.audio_format_family, "ac3")
            self.assertEqual(facts.audio_format_variant, "dolby_digital")
            self.assertEqual(facts.audio_channel_layout, "5.1")
            self.assertIsNone(facts.audio_immersive_extension)
            self.assertEqual(facts.audio_summary, "Dolby Digital 5.1")

    def test_media_facts_from_ffprobe_payload_detects_immersive_audio_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie_path = Path(tmpdir) / "Movie.mkv"
            movie_path.write_bytes(b"x" * 100)

            facts = media_facts_from_ffprobe_payload(
                {
                    "format": {
                        "duration": "7200",
                        "size": "1048576000",
                        "bit_rate": "18000000",
                        "format_name": "matroska,webm",
                    },
                    "streams": [
                        {
                            "index": 0,
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1920,
                            "height": 1080,
                            "bit_rate": "15000000",
                        },
                        {
                            "index": 1,
                            "codec_type": "audio",
                            "codec_name": "eac3",
                            "channels": 6,
                            "bit_rate": "768000",
                            "profile": "Dolby Digital Plus + Dolby Atmos",
                            "disposition": {"default": 1},
                            "tags": {"language": "eng", "title": "English Atmos"},
                        },
                    ],
                },
                movie_path,
            )

            self.assertEqual(facts.audio_format_family, "eac3")
            self.assertEqual(facts.audio_format_variant, "dolby_digital_plus")
            self.assertEqual(facts.audio_immersive_extension, "atmos")
            self.assertEqual(facts.audio_summary, "Dolby Digital Plus 5.1 Atmos")

    def test_choose_display_audio_stream_prefers_single_default(self) -> None:
        chosen = choose_display_audio_stream(
            [
                AudioStreamFacts(index=1, codec="aac", channels=2, is_default=False),
                AudioStreamFacts(index=2, codec="ac3", channels=6, is_default=True),
            ]
        )

        self.assertTrue(chosen.is_default)
        self.assertEqual(chosen.index, 2)

    def test_media_facts_from_ffprobe_payload_approximates_video_bitrate_from_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            movie_path = Path(tmpdir) / "Movie.mkv"
            movie_path.write_bytes(b"x" * 100)

            facts = media_facts_from_ffprobe_payload(
                {
                    "format": {
                        "duration": "7200",
                        "size": "1048576000",
                        "bit_rate": "9294800",
                        "format_name": "matroska,webm",
                    },
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1920,
                            "height": 1080,
                        },
                        {
                            "codec_type": "audio",
                            "codec_name": "ac3",
                            "channels": 6,
                            "bit_rate": "640000",
                        },
                    ],
                },
                movie_path,
            )

            self.assertEqual(facts.video_bitrate_kbps, 8654)
            self.assertTrue(facts.video_bitrate_approximate)

    def test_scan_movie_library_scores_and_sorts_movies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            severe_movie = source / "The Matrix (1999) 1080p.mkv"
            ok_movie = source / "Bad Timing (1980) 1080p.mkv"
            severe_movie.touch()
            ok_movie.touch()

            fake_facts = {
                severe_movie: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=2_000 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    video_codec="h264",
                    video_bitrate_kbps=2500,
                    audio_bitrate_kbps=128,
                    audio_channels=2,
                ),
                ok_movie: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=7_000 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    video_codec="hevc",
                    video_bitrate_kbps=6500,
                    audio_bitrate_kbps=640,
                    audio_channels=6,
                ),
            }

            report = scan_movie_library(source, probe_media=lambda path: fake_facts[path])

            self.assertEqual([item.path for item in report.movies], [str(severe_movie), str(ok_movie)])
            self.assertEqual(report.movies[0].review.status, "severe")
            self.assertEqual(report.movies[0].replacement_priority_score, 0.75)
            self.assertEqual(report.movies[1].replacement_priority_score, 0.6)
            self.assertGreater(report.movies[0].triage_score, report.movies[1].triage_score)

    def test_scan_movie_library_reports_probe_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Broken.mkv"
            movie.touch()

            report = scan_movie_library(source, probe_media=lambda _: (_ for _ in ()).throw(RuntimeError("boom")))

            self.assertEqual(report.movies, [])
            self.assertEqual(report.warnings[0].code, "movie_probe_error")

    def test_scan_movie_library_emits_progress_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "One.mkv"
            second = source / "Two.mkv"
            first.touch()
            second.touch()
            events: list[MovieScanProgress] = []

            fake_facts = MediaFacts(
                runtime_seconds=7200,
                file_size_bytes=4_000 * 1024 * 1024,
                width=1920,
                height=1080,
                video_codec="h264",
                video_bitrate_kbps=5000,
                audio_bitrate_kbps=640,
                audio_channels=6,
            )

            scan_movie_library(
                source,
                probe_media=lambda _: fake_facts,
                progress_callback=events.append,
            )

            self.assertEqual(events[0].status, "starting")
            self.assertEqual(events[0].processed, 0)
            self.assertEqual(events[-1].status, "complete")
            self.assertEqual(events[-1].processed, 2)
            self.assertEqual(events[-1].total, 2)

    def test_extract_year_hint_reads_year_from_path(self) -> None:
        self.assertEqual(extract_year_hint(Path("/movies/Bad Timing (1980).mkv")), 1980)

    def test_score_replacement_priority_dampens_older_titles(self) -> None:
        score, label, year_hint = score_replacement_priority(Path("/movies/Bad Timing (1980).mkv"))

        self.assertEqual(score, 0.6)
        self.assertEqual(label, "very_low")
        self.assertEqual(year_hint, 1980)


if __name__ == "__main__":
    unittest.main()
