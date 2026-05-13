from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_plan import build_movie_plan, canonical_movie_base, parse_movie_name


class MoviePlanTests(unittest.TestCase):
    def test_build_movie_plan_defaults_to_concise_filename_and_folder_renames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Matrix Folder"
            folder.mkdir()
            movie = folder / "The.Matrix.1999.1080p.bluray.x264.aac-GRP.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("The Matrix (1999).mkv", proposed_values)
            self.assertIn("The Matrix (1999)", proposed_values)

    def test_build_movie_plan_splits_technical_tokens_before_trailing_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Hooligans Bdrip 1080p Ita Eng X264 Blauray (2005).mkv").write_text("video", encoding="utf-8")
            (source / "Spaceballs Bdrip 1080p ENG ITA FRE GER SPA Multisub X264 Bluray (1987).mkv").write_text(
                "video",
                encoding="utf-8",
            )

            concise_plan = build_movie_plan(source)
            verbose_plan = build_movie_plan(source, naming_style="verbose")

            concise_values = {change.proposed_value for change in concise_plan.proposed_changes}
            verbose_values = {change.proposed_value for change in verbose_plan.proposed_changes}
            self.assertIn("Hooligans (2005)/Hooligans (2005).mkv", concise_values)
            self.assertIn("Spaceballs (1987)/Spaceballs (1987).mkv", concise_values)
            self.assertIn("Hooligans (2005) [BDRip 1080p ITA ENG x264 BluRay]/Hooligans (2005) [BDRip 1080p ITA ENG x264 BluRay].mkv", verbose_values)
            self.assertIn(
                "Spaceballs (1987) [BDRip 1080p ENG ITA FRE GER SPA MULTISUB x264 BluRay]/Spaceballs (1987) [BDRip 1080p ENG ITA FRE GER SPA MULTISUB x264 BluRay].mkv",
                verbose_values,
            )

    def test_build_movie_plan_moves_loose_root_movies_into_concise_folders_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Dune.1984.Extended.1080p.BluRay.AC3.x264-ETRG.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value) for change in plan.proposed_changes}
            self.assertIn(("file_move", "Dune (1984)/Dune (1984).mkv"), proposed)

    def test_build_movie_plan_adds_concise_resolution_differentiators_for_duplicate_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "Movie.One"
            second = source / "Movie.Two"
            first.mkdir()
            second.mkdir()
            (first / "Collision.Movie.2001.1080p.BluRay.x264-GRP.mkv").write_text("video", encoding="utf-8")
            (second / "Collision.Movie.2001.720p.WEBRip.x264-GRP.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("folder_rename", "Collision Movie (2001) 1080p", "safe"), proposed)
            self.assertIn(("folder_rename", "Collision Movie (2001) 720p", "safe"), proposed)
            self.assertIn(("file_rename", "Collision Movie (2001) 1080p.mkv", "safe"), proposed)
            self.assertIn(("file_rename", "Collision Movie (2001) 720p.mkv", "safe"), proposed)
            self.assertNotIn("movie_name_target_collision", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_marks_unresolved_concise_target_collisions_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "Movie.One"
            second = source / "Movie.Two"
            first.mkdir()
            second.mkdir()
            (first / "Collision.Movie.2001.mkv").write_text("video", encoding="utf-8")
            (second / "Collision.Movie.2001.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            folder_changes = [change for change in plan.proposed_changes if change.change_type == "folder_rename"]
            self.assertTrue(folder_changes)
            self.assertTrue(all(change.confidence == "review" for change in folder_changes))
            self.assertIn("movie_name_target_collision", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_proposes_rich_filename_and_folder_renames(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Matrix Folder"
            folder.mkdir()
            movie = folder / "The.Matrix.1999.1080p.bluray.x264.aac-GRP.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("The Matrix (1999) [1080p BluRay x264 AAC GRP].mkv", proposed_values)
            self.assertIn("The Matrix (1999) [1080p BluRay x264 AAC GRP]", proposed_values)

    def test_build_movie_plan_handles_dotted_edition_resolution_and_release_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Dune Folder"
            folder.mkdir()
            movie = folder / "Dune.1984.Extended.1080p.BluRay.ACE.x264-ETRG.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("Dune (1984) [Extended 1080p BluRay ACE x264 ETRG].mkv", proposed_values)
            self.assertIn("Dune (1984) [Extended 1080p BluRay ACE x264 ETRG]", proposed_values)
            self.assertEqual([change.confidence for change in plan.proposed_changes], ["safe", "safe"])

    def test_build_movie_plan_prefers_ascii_title_for_mixed_script_movie_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Movies"
            folder.mkdir()
            movie = folder / "Коммандос.Commando.1985.Director's.Cut.BDRip-HEVC.1080p.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Commando (1985) [Director's Cut BDRip HEVC 1080p].mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "Commando (1985) [Director's Cut BDRip HEVC 1080p]",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_build_movie_plan_splits_bluray_remux_and_preserves_language_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Land Of The Dead (2005) [BluRay Remux 1080p x264 3RUS ENG CMEV0]/Land Of The Dead (2005) [BluRay Remux 1080p x264 3RUS ENG CMEV0].mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_parse_movie_name_preserves_release_group_when_sample_has_no_extension(self) -> None:
        parsed = parse_movie_name(Path("/mnt/media_storage/Movies/Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0"))

        self.assertEqual(
            canonical_movie_base(parsed),
            "Land Of The Dead (2005) [BluRay Remux 1080p x264 3RUS ENG CMEV0]",
        )
        self.assertEqual(parsed.confidence, "safe")
        self.assertEqual(parsed.warnings, [])

    def test_build_movie_plan_cleans_dotted_collection_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            collection = source / "The.Godfather.Trilogy.[ I. II. III ].1080p.BluRay.x264.anoXmous"
            movie_folder = collection / "The.Godfather.1972.1080p.BluRay.x264.anoXmous"
            movie_folder.mkdir(parents=True)
            movie = movie_folder / "The.Godfather.1972.1080p.BluRay.x264.anoXmous_.mp4"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "The.Godfather.Trilogy.[ I. II. III ].1080p.BluRay.x264.anoXmous/The Godfather (1972) [1080p BluRay x264 anoXmous]",
                proposed_values,
            )
            self.assertIn(
                "The Godfather Trilogy [I II III] 1080p BluRay x264 anoXmous",
                proposed_values,
            )

    def test_build_movie_plan_collapses_duplicate_single_movie_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            wrapper = source / "A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs"
            movie_folder = wrapper / "A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs"
            movie_folder.mkdir(parents=True)
            movie = movie_folder / "A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs.mkv"
            movie.write_text("video", encoding="utf-8")
            (wrapper / "A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs.nfo").write_text(
                "metadata",
                encoding="utf-8",
            )

            plan = build_movie_plan(source, naming_style="verbose")

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "A Dangerous Method (2011) [1080p MKV x264 AC3 DTS MultiSubs]",
                proposed_values,
            )
            self.assertNotIn(
                "A Dangerous Method 2011 1080p MKV x264 AC3 DTS MultiSubs",
                proposed_values,
            )
            self.assertNotIn(
                "A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs/A Dangerous Method (2011) [1080p MKV x264 AC3 DTS MultiSubs]",
                proposed_values,
            )

    def test_build_movie_plan_moves_loose_root_movies_into_canonical_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Dune.1984.Extended.1080p.BluRay.AC3.x264-ETRG.mkv").write_text("video", encoding="utf-8")
            (source / "Zootopia.2016.2160p.uhd.bluray.x265-terminal.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.change_type, change.proposed_value) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "file_move",
                    "Dune (1984) [Extended 1080p BluRay AC3 x264 ETRG]/Dune (1984) [Extended 1080p BluRay AC3 x264 ETRG].mkv",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "file_move",
                    "Zootopia (2016) [2160p UHD BluRay x265 TERMINAL]/Zootopia (2016) [2160p UHD BluRay x265 TERMINAL].mkv",
                ),
                proposed,
            )
            self.assertFalse(any(warning.code == "movie_folder_multiple_videos" for warning in plan.warnings))

    def test_build_movie_plan_preserves_known_technical_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "John.Wick.Chapter.2.2017..Blu-Ray.1080p.HDR.HEVC.DD.5.1-DDR.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "John Wick Chapter 2 (2017) [BluRay 1080p HDR HEVC DD 5.1 DDR]/John Wick Chapter 2 (2017) [BluRay 1080p HDR HEVC DD 5.1 DDR].mkv",
                proposed_values,
            )
            self.assertNotIn(
                "John Wick Chapter 2 (2017) [BLU RAY 1080p HDR HEVC DD 5 1 DDR]/John Wick Chapter 2 (2017) [BLU RAY 1080p HDR HEVC DD 5 1 DDR].mkv",
                proposed_values,
            )

    def test_build_movie_plan_splits_leading_number_compact_bracket_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE]"
            folder.mkdir()
            movie = folder / "(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968) [V2 2160p BluRay x265 10bit HDR TIGOLE].mkv",
                    "review",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968) [V2 2160p BluRay x265 10bit HDR TIGOLE]",
                    "review",
                ),
                proposed,
            )

    def test_build_movie_plan_prefers_parenthesized_year_after_numeric_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "2001 - A Space Odyssey (1968) V2 (2160p BluRay x265 HEVC 10bit HDR AAC 5.1 Tigole)"
            folder.mkdir()
            movie = folder / "2001 - A Space Odyssey (1968) V2 (2160p BluRay x265 10bit HDR Tigole).mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968) [V2 2160p BluRay x265 10bit HDR TIGOLE].mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968) [V2 2160p BluRay x265 10bit HDR TIGOLE]",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_handles_parenthesized_numeric_title_with_bracketed_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO]"
            folder.mkdir()
            movie = folder / "(1917) [2019 1080p BluRay Atmos TrueHD 7.1 x264 EVO].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "1917 (2019) [1080p BluRay Atmos TrueHD 7.1 x264 EVO].mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "1917 (2019) [1080p BluRay Atmos TrueHD 7.1 x264 EVO]",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_handles_dotted_numeric_title_with_release_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "1917.2019.1080p.Bluray.Atmos.TrueHD.7.1.x264-EVO.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "1917 (2019) [1080p BluRay Atmos TrueHD 7.1 x264 EVO]/1917 (2019) [1080p BluRay Atmos TrueHD 7.1 x264 EVO].mkv",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_treats_common_long_descriptors_as_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "A.Nightmare.on.Elm.Street.1984.Remastered.1080p.BluRay.x265.hevc.10bit.AAC.7.1.commentary-HeVK.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "A Nightmare On Elm Street (1984) [Remastered 1080p BluRay x265 HEVC 10bit AAC 7.1 Commentary HEVK]/A Nightmare On Elm Street (1984) [Remastered 1080p BluRay x265 HEVC 10bit AAC 7.1 Commentary HEVK].mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_build_movie_plan_strips_leading_website_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "www.UIndex.org    -    Wings Of Desire 1987 1080p MAX WEB-DL DDP5 1 H 264-GPRS.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Wings Of Desire (1987) [1080p MAX WEB-DL DDP 5.1 H.264 GPRS]/Wings Of Desire (1987) [1080p MAX WEB-DL DDP 5.1 H.264 GPRS].mkv",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_strips_spaced_website_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Www Hdsector Com Hachi A Dog's Tale (2009) [BluRay 1080p x264 AAC 5.1 HON3Y].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Hachi A Dog's Tale (2009) [BluRay 1080p x264 AAC 5.1 HON3Y]/Hachi A Dog's Tale (2009) [BluRay 1080p x264 AAC 5.1 HON3Y].mkv",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_allows_nine_character_unknown_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Boundary.1999.NineChars.1080p.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Boundary (1999) [NineChars 1080p]/Boundary (1999) [NineChars 1080p].mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_build_movie_plan_splits_compact_technical_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV]"
            folder.mkdir()
            movie = folder / "Basic Instinct (1992) [Unrated 1080PENGITAMULTISUBX264BLURAYSHIV].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Basic Instinct (1992) [Unrated 1080p ENG ITA MULTISUB x264 BluRay SHIV].mkv",
                    "review",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "Basic Instinct (1992) [Unrated 1080p ENG ITA MULTISUB x264 BluRay SHIV]",
                    "review",
                ),
                proposed,
            )

    def test_build_movie_plan_skips_multi_video_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Movie"
            folder.mkdir()
            (folder / "Feature.1999.1080p.mkv").write_text("video", encoding="utf-8")
            (folder / "Sample.1999.1080p.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, naming_style="verbose")

            self.assertEqual(plan.proposed_changes, [])
            self.assertEqual(plan.warnings[0].code, "movie_folder_multiple_videos")


if __name__ == "__main__":
    unittest.main()
