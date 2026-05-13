from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NormalCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "normal", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_scan_writes_report_with_expected_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            source.mkdir()
            report_path = Path(tmpdir) / "out" / "scan.json"

            result = self.run_cli("scan", "--source", str(source), "--report", str(report_path))

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_root"], str(source.resolve()))
            self.assertEqual(payload["ruleset_version"], "1")
            self.assertIn("tracks", payload)
            self.assertIn("albums", payload)
            self.assertIn("warnings", payload)

    def test_movie_scan_writes_report_with_expected_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            source.mkdir()
            report_path = Path(tmpdir) / "out" / "movie-scan.json"

            result = self.run_cli("movie-scan", "--source", str(source), "--report", str(report_path))

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_root"], str(source.resolve()))
            self.assertIn("movies", payload)
            self.assertIn("warnings", payload)

    def test_movie_scan_accepts_progress_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            source.mkdir()
            report_path = Path(tmpdir) / "out" / "movie-scan.json"

            result = self.run_cli("movie-scan", "--source", str(source), "--report", str(report_path), "--progress")

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(report_path.exists())

    def test_movie_output_writes_triage_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_path = root / "movie-quality.json"
            csv_path = root / "out" / "movie-quality.csv"
            report_path.write_text(
                json.dumps(
                    {
                        "movies": [
                            {
                                "path": "/movies/severe.mkv",
                                "review": {
                                    "status": "severe",
                                    "score": 100,
                                    "confidence": "high",
                                    "facts": {"resolution_bucket": "1080p", "runtime_seconds": 7200},
                                    "derived": {"mb_per_min": 10.0},
                                    "reasons": [{"code": "low_video_bitrate"}],
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli("movie-output", "--report", str(report_path), "--csv", str(csv_path))

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(csv_path.exists())

    def test_movie_plan_writes_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            folder = source / "Loose Folder"
            folder.mkdir(parents=True)
            (folder / "The.Matrix.1999.1080p.bluray.mkv").write_text("video", encoding="utf-8")
            plan_path = Path(tmpdir) / "out" / "movie-plan.json"

            result = self.run_cli("movie-plan", "--source", str(source), "--plan", str(plan_path))

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_root"], str(source.resolve()))
            self.assertIn("proposed_changes", payload)
            self.assertIn("The Matrix (1999).mkv", {change["proposed_value"] for change in payload["proposed_changes"]})

    def test_movie_plan_can_write_verbose_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            folder = source / "Loose Folder"
            folder.mkdir(parents=True)
            (folder / "The.Matrix.1999.1080p.bluray.mkv").write_text("video", encoding="utf-8")
            plan_path = Path(tmpdir) / "out" / "movie-plan.json"

            result = self.run_cli(
                "movie-plan",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--naming-style",
                "verbose",
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertIn("The Matrix (1999) [1080p BluRay].mkv", {change["proposed_value"] for change in payload["proposed_changes"]})

    def test_movie_profile_writes_report_and_histogram(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            source.mkdir()
            (source / "Movie.1999.1080p.mkv").write_text("video", encoding="utf-8")
            report_path = Path(tmpdir) / "out" / "movie-profile.json"
            histogram_path = Path(tmpdir) / "out" / "movie-histogram.json"

            result = self.run_cli(
                "movie-profile",
                "--source",
                str(source),
                "--report",
                str(report_path),
                "--histogram",
                str(histogram_path),
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(report_path.exists())
            self.assertTrue(histogram_path.exists())

    def test_movie_junk_writes_report_with_expected_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "movies"
            source.mkdir()
            report_path = Path(tmpdir) / "out" / "movie-junk.json"

            result = self.run_cli("movie-junk", "--source", str(source), "--report", str(report_path))

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_root"], str(source.resolve()))
            self.assertIn("junk", payload)
            self.assertIn("warnings", payload)

    def test_plan_writes_plan_and_optional_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            album_dir = source / "Artist" / "Album"
            album_dir.mkdir(parents=True)
            (album_dir / "01 Song.flac").write_text("not a flac", encoding="utf-8")
            plan_path = Path(tmpdir) / "out" / "plan.json"
            summary_path = Path(tmpdir) / "out" / "plan.md"

            result = self.run_cli(
                "plan",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--summary",
                str(summary_path),
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_root"], str(source.resolve()))
            self.assertIn("proposed_changes", payload)
            self.assertIn("warnings", payload)
            self.assertTrue(summary_path.exists())

    def test_apply_requires_exactly_one_destination_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            source.mkdir()
            plan_path = Path(tmpdir) / "plan.json"
            plan_path.write_text("{}", encoding="utf-8")

            result = self.run_cli("apply", "--source", str(source), "--plan", str(plan_path))

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("one of the arguments --target --in-place is required", result.stderr)

    def test_output_writes_csv_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            artist_dir = source / "Artist" / "Album"
            artist_dir.mkdir(parents=True)
            (artist_dir / "01 Song.flac").write_text("not a flac", encoding="utf-8")
            csv_path = Path(tmpdir) / "out" / "collection.csv"

            result = self.run_cli("output", "--source", str(source), "--csv", str(csv_path))

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(
                rows[0],
                ["album_artist", "album", "date", "genre", "track_count", "path"],
            )

    def test_apply_writes_report_into_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            source_file = source / "01 Old.flac"
            source_file.write_text("audio", encoding="utf-8")
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "source_root": str(source.resolve()),
                        "generated_at": "2024-01-01T00:00:00+00:00",
                        "ruleset_version": "1",
                        "tracks": [],
                        "albums": [],
                        "proposed_changes": [
                            {
                                "item_id": "01 Old.flac#file",
                                "change_type": "file_rename",
                                "current_value": "01 Old.flac",
                                "proposed_value": "01 New.flac",
                                "confidence": "safe",
                                "reason": "rename",
                                "path": str(source_file),
                            }
                        ],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "apply",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--target",
                str(target),
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue((target / "01 New.flac").exists())
            self.assertTrue((target / "normal-apply-report.json").exists())

    def test_movie_apply_writes_movie_report_into_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            source_file = source / "Old.Name.1999.1080p.mkv"
            source_file.write_text("video", encoding="utf-8")
            plan_path = root / "movie-plan.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "source_root": str(source.resolve()),
                        "generated_at": "2024-01-01T00:00:00+00:00",
                        "ruleset_version": "1",
                        "tracks": [],
                        "albums": [],
                        "proposed_changes": [
                            {
                                "item_id": "Old.Name.1999.1080p.mkv#file",
                                "change_type": "file_rename",
                                "current_value": "Old.Name.1999.1080p.mkv",
                                "proposed_value": "Old Name (1999) [1080p].mkv",
                                "confidence": "safe",
                                "reason": "rename",
                                "path": str(source_file),
                            }
                        ],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            result = self.run_cli(
                "movie-apply",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--target",
                str(target),
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue((target / "Old Name (1999) [1080p].mkv").exists())
            self.assertTrue((target / "normal-movie-apply-report.json").exists())


if __name__ == "__main__":
    unittest.main()
