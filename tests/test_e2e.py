from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mutagen.flac import FLAC


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def ffmpeg_is_available() -> bool:
    result = subprocess.run(
        ["ffmpeg", "-version"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


@unittest.skipUnless(ffmpeg_is_available(), "ffmpeg is required for end-to-end fixture tests")
class EndToEndFixtureTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "normal", *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def materialize_fixture(self, fixture_name: str, destination_root: Path) -> Path:
        manifest_path = FIXTURES / fixture_name / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        library_root = destination_root / fixture_name
        for track in manifest["tracks"]:
            track_path = library_root / track["relative_path"]
            track_path.parent.mkdir(parents=True, exist_ok=True)
            self.create_flac(track_path, track["tags"])
        return library_root

    def create_flac(self, output_path: Path, tags: dict[str, str]) -> None:
        subprocess.run(
            [
                "ffmpeg",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                "0.1",
                "-c:a",
                "flac",
                "-y",
                str(output_path),
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        audio = FLAC(output_path)
        for key, value in tags.items():
            audio[key] = [value]
        audio.save()

    def test_straightforward_fixture_runs_full_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.materialize_fixture("straightforward_album", root)
            plan_path = root / "plan.json"
            summary_path = root / "plan.md"
            target = root / "clean"
            csv_path = root / "collection.csv"

            plan_result = self.run_cli(
                "plan",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--summary",
                str(summary_path),
            )
            self.assertEqual(plan_result.returncode, 0, msg=plan_result.stderr)

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            change_types = {(change["change_type"], change["confidence"]) for change in plan["proposed_changes"]}
            self.assertIn(("file_rename", "safe"), change_types)
            self.assertIn(("folder_rename", "safe"), change_types)

            apply_result = self.run_cli(
                "apply",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--target",
                str(target),
            )
            self.assertEqual(apply_result.returncode, 0, msg=apply_result.stderr)
            self.assertTrue((target / "Artist" / "1999 - Album" / "01 Song One.flac").exists())
            self.assertTrue((target / "Artist" / "1999 - Album" / "02 Song Two.flac").exists())

            output_result = self.run_cli(
                "output",
                "--source",
                str(target),
                "--csv",
                str(csv_path),
            )
            self.assertEqual(output_result.returncode, 0, msg=output_result.stderr)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["album_artist"], "Artist")
            self.assertEqual(rows[0]["album"], "Album")
            self.assertEqual(rows[0]["date"], "1999")
            self.assertEqual(rows[0]["genre"], "Rock")

    def test_missing_year_fixture_keeps_review_folder_change_unapplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.materialize_fixture("missing_year_review", root)
            plan_path = root / "plan.json"
            target = root / "clean"
            csv_path = root / "collection.csv"

            plan_result = self.run_cli(
                "plan",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
            )
            self.assertEqual(plan_result.returncode, 0, msg=plan_result.stderr)

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            warning_codes = {warning["code"] for warning in plan["warnings"]}
            review_folder_changes = [
                change for change in plan["proposed_changes"]
                if change["change_type"] == "folder_rename" and change["confidence"] == "review"
            ]
            self.assertIn("album_missing_year", warning_codes)
            self.assertEqual(len(review_folder_changes), 1)

            apply_result = self.run_cli(
                "apply",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--target",
                str(target),
            )
            self.assertEqual(apply_result.returncode, 0, msg=apply_result.stderr)

            apply_report = json.loads((target / "normal-apply-report.json").read_text(encoding="utf-8"))
            skipped_review = [item for item in apply_report["skipped"] if item["change_type"] == "folder_rename"]
            self.assertEqual(len(skipped_review), 1)
            self.assertTrue((target / "Wrong Artist" / "Album Name" / "01 Song One.flac").exists())
            self.assertFalse((target / "Artist" / "Album").exists())

            output_result = self.run_cli(
                "output",
                "--source",
                str(target),
                "--csv",
                str(csv_path),
            )
            self.assertEqual(output_result.returncode, 0, msg=output_result.stderr)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["album_artist"], "Artist")
            self.assertEqual(rows[0]["album"], "Album")
            self.assertEqual(rows[0]["date"], "")

    def test_conflicting_album_fixture_surfaces_review_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.materialize_fixture("conflicting_album", root)
            plan_path = root / "plan.json"

            plan_result = self.run_cli(
                "plan",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
            )
            self.assertEqual(plan_result.returncode, 0, msg=plan_result.stderr)

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            warning_codes = {warning["code"] for warning in plan["warnings"]}
            self.assertIn("album_conflicting_titles", warning_codes)
            self.assertIn("album_conflicting_album_artists", warning_codes)

    def test_multi_disc_fixture_preserves_disc_subfolders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.materialize_fixture("multi_disc_album", root)
            plan_path = root / "plan.json"
            target = root / "clean"
            csv_path = root / "collection.csv"

            plan_result = self.run_cli(
                "plan",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
            )
            self.assertEqual(plan_result.returncode, 0, msg=plan_result.stderr)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            folder_changes = [change for change in plan["proposed_changes"] if change["change_type"] == "folder_rename"]
            self.assertEqual(len(folder_changes), 1)
            self.assertEqual(folder_changes[0]["proposed_value"], "Artist/2003 - Album")

            apply_result = self.run_cli(
                "apply",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--target",
                str(target),
            )
            self.assertEqual(apply_result.returncode, 0, msg=apply_result.stderr)
            self.assertTrue((target / "Artist" / "2003 - Album" / "CD1" / "01 Opener.flac").exists())
            self.assertTrue((target / "Artist" / "2003 - Album" / "CD2" / "01 Closer.flac").exists())

            output_result = self.run_cli(
                "output",
                "--source",
                str(target),
                "--csv",
                str(csv_path),
            )
            self.assertEqual(output_result.returncode, 0, msg=output_result.stderr)
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["path"], str(target / "Artist" / "2003 - Album"))

    def test_apply_reports_folder_collision_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = self.materialize_fixture("straightforward_album", root)
            plan_path = root / "plan.json"
            target = root / "clean"

            plan_result = self.run_cli(
                "plan",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
            )
            self.assertEqual(plan_result.returncode, 0, msg=plan_result.stderr)

            collision_dir = target / "Artist" / "1999 - Album"
            collision_dir.mkdir(parents=True)
            (collision_dir / "existing.flac").write_text("audio", encoding="utf-8")

            apply_result = self.run_cli(
                "apply",
                "--source",
                str(source),
                "--plan",
                str(plan_path),
                "--target",
                str(target),
            )
            self.assertNotEqual(apply_result.returncode, 0)
            self.assertIn("target directory is not empty", apply_result.stderr)


if __name__ == "__main__":
    unittest.main()
