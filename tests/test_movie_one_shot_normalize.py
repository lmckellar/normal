from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_identity import parse_movie_identity
from normal.movie_plan import build_movie_plan
from normal.movie_preclean import MOVIE_PRECLEAN_LEDGER_PATH, filter_movie_files_with_preclean, load_movie_preclean_entries
from normal.movie_scan import discover_video_files


class MovieOneShotNormalizeTests(unittest.TestCase):
    def test_year_leading_collection_files_split_as_safe(self) -> None:
        cases = [
            (
                "The Rambo Collection (1982-2019)",
                [
                    "1982.First.Blood.1920x818.BDRip.x264.DTS-HD.MA.mkv",
                    "1985.Rambo-.First.Blood.Part.II.1920x820.BDRip.x264.DTS-HD.MA.mkv",
                    "1988.Rambo.III.1920x820.BDRip.x264.DTS-HD.MA.mkv",
                    "2008.Rambo.1920x798.BDRip.x264.DTS-HD.MA.mkv",
                ],
                {
                    "First Blood (1982)/First Blood (1982).mkv",
                    "Rambo First Blood Part II (1985)/Rambo First Blood Part II (1985).mkv",
                    "Rambo III (1988)/Rambo III (1988).mkv",
                    "Rambo (2008)/Rambo (2008).mkv",
                },
            ),
            (
                "Speed - The Complete Collection (1994-1997)",
                [
                    "1994.Speed.1920x820.BDRip.x264.DTS-HD.MA.mkv",
                    "1997.Speed.2-.Cruise.Control.1920x820.BDRip.x264.DTS-HD.MA.mkv",
                ],
                {
                    "Speed (1994)/Speed (1994).mkv",
                    "Speed 2 Cruise Control (1997)/Speed 2 Cruise Control (1997).mkv",
                },
            ),
            (
                "The Ace Ventura Collection (1994-1995)",
                [
                    "1994.Ace.Ventura-.Pet.Detective.1920x820.BDRip.x264.DTS-HD.MA.mkv",
                    "1995.Ace.Ventura-.When.Nature.Calls.1920x820.BDRip.x264.DTS-HD.MA.mkv",
                ],
                {
                    "Ace Ventura Pet Detective (1994)/Ace Ventura Pet Detective (1994).mkv",
                    "Ace Ventura When Nature Calls (1995)/Ace Ventura When Nature Calls (1995).mkv",
                },
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            for folder_name, filenames, expected_moves in cases:
                with self.subTest(folder_name=folder_name):
                    folder = source / folder_name
                    folder.mkdir()
                    for filename in filenames:
                        (folder / filename).write_text("video", encoding="utf-8")

                    plan = build_movie_plan(source)

                    moves = {
                        change.proposed_value
                        for change in plan.proposed_changes
                        if change.change_type == "file_move" and change.path and Path(change.path).parent == folder
                    }
                    self.assertEqual(moves, expected_moves)
                    self.assertTrue(
                        all(
                            change.confidence == "safe"
                            for change in plan.proposed_changes
                            if change.path and Path(change.path).parent == folder
                        )
                    )

    def test_the_legend_of_1900_prefers_release_year_over_title_internal_year(self) -> None:
        parsed = parse_movie_identity(Path("The.Legend.of.1900.1998.1080p.BluRay.x264.mkv"))
        self.assertEqual(parsed.title, "The Legend Of 1900")
        self.assertEqual(parsed.year, 1998)
        self.assertEqual(parsed.confidence, "safe")

    def test_live_noise_tokens_no_longer_force_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            for filename in [
                "Se7en.1995.BDRip.1080p.ELEKTRI4KA.UNIONGANG.mkv",
                "Cinema.Paradiso.1988.Theatrical.1080p.BluRay.x265.HEVC.EAC3-SARTRE.mkv",
                "How To Train Your Dragon (2010) [GRAV1TY & Maxoverpower].mkv",
            ]:
                (source / filename).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            self.assertFalse(plan.warnings)
            self.assertTrue(plan.proposed_changes)
            self.assertTrue(all(change.confidence == "safe" for change in plan.proposed_changes))

    def test_ambiguous_single_child_double_feature_folder_is_not_collapsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Grindhouse Planet Terror & Death Proof 1080p Unrated [mkvonly]"
            folder.mkdir()
            (folder / "Death Proof (2007).mkv").write_text("video", encoding="utf-8")
            (folder / "._Planet Terror Unrated 1080p [mkvonly].mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            self.assertFalse(
                any(
                    change.change_type == "folder_rename"
                    and change.path == str(folder)
                    and change.proposed_value == "Death Proof (2007)"
                    for change in plan.proposed_changes
                )
            )

    def test_already_normalized_multi_part_folder_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "White Mischief (1987)"
            folder.mkdir()
            (folder / "White Mischief (1987) CD1.mkv").write_text("video", encoding="utf-8")
            (folder / "White Mischief (1987) CD2.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            self.assertEqual(plan.proposed_changes, [])
            self.assertFalse(plan.warnings)

    def test_selected_raw_corpus_cases_hold_safe_and_review_boundaries(self) -> None:
        safe_cases = {
            "Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0.mkv": "Land Of The Dead (2005) [BluRay Remux 1080p x264]",
            "Resolution.Trap.2017.1920x820.1080p.BluRay.x264-GRP.mkv": "Resolution Trap (2017) [1080p BluRay x264]",
        }
        review_cases = [
            (
                "Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV]",
                "Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV].mkv",
            ),
        ]

        for filename, base in safe_cases.items():
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir)
                    movie = source / filename
                    movie.write_text("video", encoding="utf-8")
                    plan = build_movie_plan(source, naming_style="verbose", movie_files=[movie])
                    self.assertFalse(plan.warnings)
                    self.assertTrue(all(change.confidence == "safe" for change in plan.proposed_changes))
                    self.assertIn(f"{base}/{base}.mkv", {change.proposed_value for change in plan.proposed_changes})

        for folder_name, filename in review_cases:
            with self.subTest(folder_name=folder_name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir)
                    folder = source / folder_name
                    folder.mkdir()
                    movie = folder / filename
                    movie.write_text("video", encoding="utf-8")
                    plan = build_movie_plan(source, naming_style="verbose", movie_files=[movie])
                    self.assertIn("movie_name_review", {warning.code for warning in plan.warnings})
                    self.assertTrue(any(change.confidence == "review" for change in plan.proposed_changes))

    def test_live_library_acceptance_after_logged_preclean(self) -> None:
        source = Path("/mnt/media_storage/Movies")
        if not source.exists():
            self.skipTest("/mnt/media_storage/Movies is not available in this environment")

        entries = load_movie_preclean_entries(MOVIE_PRECLEAN_LEDGER_PATH)
        movie_files = filter_movie_files_with_preclean(discover_video_files(source), entries)
        plan = build_movie_plan(source, movie_files=movie_files)

        warning_codes = {warning.code for warning in plan.warnings}
        self.assertTrue(
            warning_codes.issubset({"movie_name_existing_target_collision"}),
            msg=f"unexpected warnings: {sorted(warning_codes)}",
        )
        self.assertTrue(
            all(change.confidence == "safe" for change in plan.proposed_changes if "Target path already exists in the library." not in change.reason)
        )


if __name__ == "__main__":
    unittest.main()
