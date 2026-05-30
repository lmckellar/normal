from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_apply import apply_changes_in_place
from normal.movie_plan import build_movie_plan, parse_movie_name


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

    def test_build_movie_plan_detects_verbose_folder_after_concise_file_rename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "The Matrix (1999) [1080p BluRay x264 AAC GRP]"
            folder.mkdir()
            movie = folder / "The Matrix (1999).mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.current_value, change.proposed_value) for change in plan.proposed_changes}
            self.assertEqual(
                proposed,
                {
                    (
                        "folder_rename",
                        "The Matrix (1999) [1080p BluRay x264 AAC GRP]",
                        "The Matrix (1999)",
                    )
                },
            )

    def test_build_movie_plan_detects_verbose_file_inside_concise_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "The Matrix (1999)"
            folder.mkdir()
            movie = folder / "The Matrix (1999) [1080p BluRay x264 AAC GRP].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.current_value, change.proposed_value) for change in plan.proposed_changes}
            self.assertEqual(
                proposed,
                {
                    (
                        "file_rename",
                        "The Matrix (1999) [1080p BluRay x264 AAC GRP].mkv",
                        "The Matrix (1999).mkv",
                    )
                },
            )

    def test_build_movie_plan_rescan_is_clean_after_concise_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "The Matrix (1999) [1080p BluRay x264 AAC GRP]"
            folder.mkdir()
            movie = folder / "The Matrix (1999) [1080p BluRay x264 AAC GRP].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)
            report = apply_changes_in_place(source, plan.proposed_changes)
            rescanned = build_movie_plan(source)

            self.assertEqual(len(report.applied), 2)
            self.assertEqual(rescanned.proposed_changes, [])
            self.assertTrue((source / "The Matrix (1999)" / "The Matrix (1999).mkv").exists())

    def test_build_movie_plan_marks_existing_concise_target_collision_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            concise = source / "Ace Ventura Pet Detective (1994)"
            verbose = source / "Ace Ventura Pet Detective (1994) [BluRay 1080p DDP 5.1 x264 HALLOWED]"
            concise.mkdir()
            verbose.mkdir()
            (concise / "Ace Ventura Pet Detective (1994).mkv").write_text("video", encoding="utf-8")
            (verbose / "Ace.Ventura.Pet.Detective.1994.BluRay.1080p.DDP.5.1.x264-HALLOWED.mkv").write_text(
                "video",
                encoding="utf-8",
            )

            plan = build_movie_plan(source)

            folder_change = next(change for change in plan.proposed_changes if change.change_type == "folder_rename")
            file_change = next(change for change in plan.proposed_changes if change.change_type == "file_rename")
            self.assertEqual(folder_change.proposed_value, "Ace Ventura Pet Detective (1994) 1080p")
            self.assertEqual(file_change.proposed_value, "Ace Ventura Pet Detective (1994) 1080p.mkv")
            self.assertEqual(folder_change.confidence, "safe")
            self.assertEqual(file_change.confidence, "safe")
            self.assertNotIn("movie_name_existing_target_collision", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_uses_differentiator_for_package_split_existing_target_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            canonical = source / "Ace Ventura When Nature Calls (1995)"
            canonical.mkdir()
            (canonical / "Ace Ventura When Nature Calls (1995).mkv").write_text("video", encoding="utf-8")
            collection = source / "The Ace Ventura Collection (1994-1995)"
            collection.mkdir()
            (
                collection / "1994.Ace.Ventura-.Pet.Detective.1920x1080.BDRip.x264.DTS-HD.MA.mkv"
            ).write_text("video", encoding="utf-8")
            (
                collection / "1995.Ace.Ventura-.When.Nature.Calls.1920x800.BDRip.x264.DTS-HD.MA.mkv"
            ).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            move = next(
                change for change in plan.proposed_changes
                if change.change_type == "file_move" and "When.Nature.Calls" in change.current_value
            )
            self.assertEqual(
                move.proposed_value,
                "Ace Ventura When Nature Calls (1995) BDRip/Ace Ventura When Nature Calls (1995) BDRip.mkv",
            )
            self.assertEqual(move.confidence, "safe")
            self.assertNotIn("unresolved_duplicate_video_target_collision", move.reason_codes)
            self.assertNotIn("movie_name_existing_target_collision", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_uses_differentiator_for_folder_existing_target_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            canonical = source / "Battle Royale (2000)"
            canonical.mkdir()
            (canonical / "Battle Royale (2000).mkv").write_text("video", encoding="utf-8")
            verbose = source / "Battle.Royale.2000.1080p.BluRay.3D.H-SBS.DTS.x264-PublicHD"
            verbose.mkdir()
            (
                verbose / "battle.royale.2000.1080p.bluray.3D.h-sbs.dts.x264-publichd.mkv"
            ).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            folder_change = next(change for change in plan.proposed_changes if change.change_type == "folder_rename")
            file_change = next(change for change in plan.proposed_changes if change.change_type == "file_rename")
            self.assertEqual(folder_change.proposed_value, "Battle Royale (2000) 1080p")
            self.assertEqual(file_change.proposed_value, "Battle Royale (2000) 1080p.mkv")
            self.assertEqual(folder_change.confidence, "safe")
            self.assertEqual(file_change.confidence, "safe")
            self.assertNotIn("movie_name_existing_target_collision", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_renames_no_video_movie_artifact_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            artifact = source / "A Few Good Men (1992) [1080p BluRay AC3 x264 ETRG]"
            artifact.mkdir()
            (artifact / "A.Few.Good.Men.1992.1080p.BluRay.AC3.x264-ETRG.nfo").write_text("metadata", encoding="utf-8")

            plan = build_movie_plan(source)

            self.assertIn("no_video_files", {warning.code for warning in plan.warnings})
            self.assertEqual(len(plan.proposed_changes), 1)
            change = plan.proposed_changes[0]
            self.assertEqual(change.change_type, "folder_rename")
            self.assertEqual(change.proposed_value, "A Few Good Men (1992)")
            self.assertEqual(change.confidence, "safe")

    def test_build_movie_plan_deletes_metadata_only_collection_artifact_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            artifact = source / "The Mummy 1, 2, 3, 4 - Collection 1999-2017 Eng Subs 1080p [H264-mp4]"
            child = artifact / "The Mummy Collection 1999-2017 1080p"
            child.mkdir(parents=True)
            (artifact / ".DS_Store").write_text("metadata", encoding="utf-8")
            (child / "01 The Mummy 1 - Action 1999 Eng Subs 1080p [H264-mp4].nfo").write_text(
                "metadata",
                encoding="utf-8",
            )

            plan = build_movie_plan(source)

            self.assertEqual(len(plan.proposed_changes), 1)
            change = plan.proposed_changes[0]
            self.assertEqual(change.change_type, "folder_delete")
            self.assertEqual(change.confidence, "safe")

    def test_build_movie_plan_moves_loose_movie_with_sidecar_nfo_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Se7en [1080p, x264, dts ita, ac3 ita-eng, subs] by GuglielmoDaBaskerville.mkv"
            movie.write_text("video", encoding="utf-8")
            movie.with_suffix(".nfo").write_text("<movie><title>Se7en</title><year>1995</year></movie>", encoding="utf-8")

            plan = build_movie_plan(source)

            move = next(change for change in plan.proposed_changes if change.change_type == "file_move")
            self.assertEqual(move.proposed_value, "Se7en (1995)/Se7en (1995).mkv")
            self.assertEqual(move.confidence, "safe")

    def test_build_movie_plan_deletes_root_appledouble_junk_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "._Movie.mkv").write_text("metadata", encoding="utf-8")

            plan = build_movie_plan(source)

            delete = next(change for change in plan.proposed_changes if change.change_type == "file_delete")
            self.assertEqual(delete.current_value, "._Movie.mkv")
            self.assertEqual(delete.confidence, "safe")

    def test_build_movie_plan_normalizes_multi_part_movie_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "White Mischief (1987) Greta Scacchi 2CD 2160p H.264 ENG-GER (moviesbyrizzo) MULTISUB"
            folder.mkdir()
            (folder / "White Mischief (1987) Greta Scacchi 2160p CD1 H.264 ENG-GER (moviesbyrizzo).mkv").write_text(
                "video",
                encoding="utf-8",
            )
            (folder / "White Mischief (1987) Greta Scacchi 2160p CD2 H.264 ENG-GER (moviesbyrizzo).mkv").write_text(
                "video",
                encoding="utf-8",
            )

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("folder_rename", "White Mischief (1987)", "safe"), proposed)
            self.assertIn(("file_rename", "White Mischief (1987) CD1.mkv", "safe"), proposed)
            self.assertIn(("file_rename", "White Mischief (1987) CD2.mkv", "safe"), proposed)

    def test_build_movie_plan_deletes_metadata_and_poster_residue_when_winner_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            concise = source / "A Few Good Men (1992)"
            artifact = source / "A Few Good Men (1992) [1080p BluRay AC3 x264 ETRG]"
            concise.mkdir()
            artifact.mkdir()
            (concise / "A Few Good Men (1992).mkv").write_text("video", encoding="utf-8")
            (artifact / "A.Few.Good.Men.1992.1080p.BluRay.AC3.x264-ETRG.nfo").write_text("metadata", encoding="utf-8")
            (artifact / "poster.jpg").write_text("artwork", encoding="utf-8")

            plan = build_movie_plan(source)

            change = next(change for change in plan.proposed_changes if change.change_type == "folder_delete")
            self.assertEqual(change.current_value, "A Few Good Men (1992) [1080p BluRay AC3 x264 ETRG]")
            self.assertEqual(change.proposed_value, "")
            self.assertEqual(change.confidence, "safe")

    def test_build_movie_plan_splits_technical_tokens_before_trailing_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Hooligans Bdrip 1080p Ita Eng X264 Blauray (2005).mkv").write_text("video", encoding="utf-8")
            (source / "Spaceballs Bdrip 1080p ENG ITA FRE GER SPA Multisub X264 Bluray (1987).mkv").write_text(
                "video",
                encoding="utf-8",
            )

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("Hooligans (2005)/Hooligans (2005).mkv", proposed_values)
            self.assertIn("Spaceballs (1987)/Spaceballs (1987).mkv", proposed_values)

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

    def test_build_movie_plan_uses_local_folder_labels_to_resolve_concise_target_collisions(self) -> None:
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
            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("folder_rename", "Collision Movie (2001) Movie One", "safe"), proposed)
            self.assertIn(("folder_rename", "Collision Movie (2001) Movie Two", "safe"), proposed)
            self.assertIn(("file_rename", "Collision Movie (2001) Movie One.mkv", "safe"), proposed)
            self.assertIn(("file_rename", "Collision Movie (2001) Movie Two.mkv", "safe"), proposed)
            self.assertNotIn("movie_name_target_collision", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_keeps_root_level_duplicate_titles_as_review_without_local_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            normalized = source / "Collision Movie (2001)"
            normalized.mkdir()
            (normalized / "Collision Movie (2001).mkv").write_text("video", encoding="utf-8")
            (source / "Collision.Movie.2001.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            review_changes = [change for change in plan.proposed_changes if change.change_type in {"file_move", "folder_rename"}]
            self.assertTrue(any(change.confidence == "review" for change in review_changes))
            self.assertIn("movie_name_existing_target_collision", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_marks_composed_file_target_collision_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            verbose = source / "Ace Ventura Pet Detective (1994) 1080p"
            verbose.mkdir()
            (verbose / "Ace Ventura Pet Detective (1994) 1080p.mkv").write_text("video", encoding="utf-8")
            collection = source / "The Ace Ventura Collection (1994-1995)"
            collection.mkdir()
            (
                collection / "1994.Ace.Ventura-.Pet.Detective.1920x1080.BDRip.x264.DTS-HD.MA.mkv"
            ).write_text("video", encoding="utf-8")
            (
                collection / "1995.Ace.Ventura-.When.Nature.Calls.1920x800.BDRip.x264.DTS-HD.MA.mkv"
            ).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            pet_changes = [
                change for change in plan.proposed_changes
                if "Ace Ventura Pet Detective" in change.proposed_value
            ]
            self.assertEqual(len(pet_changes), 3)
            move = next(
                change for change in plan.proposed_changes
                if change.change_type == "file_move" and "Pet.Detective" in change.current_value
            )
            self.assertEqual(
                move.proposed_value,
                "Ace Ventura Pet Detective (1994) BDRip/Ace Ventura Pet Detective (1994) BDRip.mkv",
            )
            self.assertEqual(move.confidence, "safe")
            self.assertNotIn("movie_name_target_collision", {warning.code for warning in plan.warnings})
            self.assertFalse(
                any("unresolved_duplicate_video_target_collision" in change.reason_codes for change in pet_changes)
            )
            collection_delete = next(change for change in plan.proposed_changes if change.change_type == "folder_delete")
            self.assertEqual(collection_delete.confidence, "safe")

    def test_build_movie_plan_proposes_rich_filename_and_folder_renames(self) -> None:
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

    def test_build_movie_plan_handles_dotted_edition_resolution_and_release_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Dune Folder"
            folder.mkdir()
            movie = folder / "Dune.1984.Extended.1080p.BluRay.ACE.x264-ETRG.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("Dune (1984).mkv", proposed_values)
            self.assertIn("Dune (1984)", proposed_values)
            self.assertEqual([change.confidence for change in plan.proposed_changes], ["safe", "safe"])

    def test_build_movie_plan_keeps_known_structure_safe_despite_long_unknown_tail_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "The Last Starfighter (1984) 25th Anniversary Ed 1080p Blu-ray x264 DTS-HDMA 5.1-DTOne.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "The Last Starfighter (1984)/The Last Starfighter (1984).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_build_movie_plan_still_reviews_long_unknown_tail_token_when_structure_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Mystery Film (1984) AnniversaryWord.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Mystery Film (1984)/Mystery Film (1984).mkv",
                    "review",
                ),
                proposed,
            )
            self.assertIn("unknown_technical_token", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_prefers_ascii_title_for_mixed_script_movie_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Movies"
            folder.mkdir()
            movie = folder / "Коммандос.Commando.1985.Director's.Cut.BDRip-HEVC.1080p.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Commando (1985).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "Commando (1985)",
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

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Land Of The Dead (2005)/Land Of The Dead (2005).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_parse_movie_name_preserves_release_group_when_sample_has_no_extension(self) -> None:
        parsed = parse_movie_name(Path("/mnt/media_storage/Movies/Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0"))

        self.assertEqual(parsed.title, "Land Of The Dead")
        self.assertEqual(parsed.year, 2005)
        self.assertEqual(parsed.tech_tokens, ["BluRay", "Remux", "1080p", "x264", "3RUS", "ENG"])
        self.assertEqual(parsed.release_group, "CMEV0")
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

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "The.Godfather.Trilogy.[ I. II. III ].1080p.BluRay.x264.anoXmous/The Godfather (1972)",
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

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "A Dangerous Method (2011)",
                proposed_values,
            )
            self.assertNotIn(
                "A Dangerous Method 2011 1080p MKV x264 AC3 DTS MultiSubs",
                proposed_values,
            )
            self.assertNotIn(
                "A.Dangerous.Method.2011.1080p.MKV.x264.AC3.DTS.MultiSubs/A Dangerous Method (2011)",
                proposed_values,
            )

    def test_build_movie_plan_moves_loose_root_movies_into_canonical_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "Dune.1984.Extended.1080p.BluRay.AC3.x264-ETRG.mkv").write_text("video", encoding="utf-8")
            (source / "Zootopia.2016.2160p.uhd.bluray.x265-terminal.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "file_move",
                    "Dune (1984)/Dune (1984).mkv",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "file_move",
                    "Zootopia (2016)/Zootopia (2016).mkv",
                ),
                proposed,
            )
            self.assertFalse(any(warning.code == "movie_folder_multiple_videos" for warning in plan.warnings))

    def test_build_movie_plan_preserves_known_technical_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "John.Wick.Chapter.2.2017..Blu-Ray.1080p.HDR.HEVC.DD.5.1-DDR.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "John Wick Chapter 2 (2017)/John Wick Chapter 2 (2017).mkv",
                proposed_values,
            )
            self.assertFalse(plan.warnings)

    def test_build_movie_plan_reconstructs_k19_punctuation_for_raw_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "K.19.The.Widowmaker.2002.1080p.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            move = next(change for change in plan.proposed_changes if change.change_type == "file_move")
            self.assertEqual(move.proposed_value, "K-19: The Widowmaker (2002)/K-19: The Widowmaker (2002).mkv")
            self.assertEqual(move.confidence, "safe")

    def test_build_movie_plan_reconstructs_compact_k19_punctuation_for_raw_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "K19.The.Widowmaker.2002.1080p.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            move = next(change for change in plan.proposed_changes if change.change_type == "file_move")
            self.assertEqual(move.proposed_value, "K-19: The Widowmaker (2002)/K-19: The Widowmaker (2002).mkv")
            self.assertEqual(move.confidence, "safe")

    def test_build_movie_plan_reconstructs_ordinal_suffixes_for_raw_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "25Th.Hour.2002.1080p.mkv").write_text("video", encoding="utf-8")
            (source / "Friday.The.13Th.1980.1080p.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("25th Hour (2002)/25th Hour (2002).mkv", proposed_values)
            self.assertIn("Friday The 13th (1980)/Friday The 13th (1980).mkv", proposed_values)

    def test_build_movie_plan_reconstructs_abbreviation_punctuation_for_raw_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "L.A.Confidential.1997.1080p.mkv").write_text("video", encoding="utf-8")
            (source / "Mr.Nobody.2009.1080p.mkv").write_text("video", encoding="utf-8")
            (source / "Dr.Strangelove.1964.1080p.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("L.A. Confidential (1997)/L.A. Confidential (1997).mkv", proposed_values)
            self.assertIn("Mr. Nobody (2009)/Mr. Nobody (2009).mkv", proposed_values)
            self.assertIn("Dr. Strangelove (1964)/Dr. Strangelove (1964).mkv", proposed_values)

    def test_build_movie_plan_marks_legacy_normalized_punctuation_upgrade_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "K 19 The Widowmaker (2002)"
            folder.mkdir()
            movie = folder / "K 19 The Widowmaker (2002).mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            folder_change = next(change for change in plan.proposed_changes if change.change_type == "folder_rename")
            file_change = next(change for change in plan.proposed_changes if change.change_type == "file_rename")
            self.assertEqual(folder_change.proposed_value, "K-19: The Widowmaker (2002)")
            self.assertEqual(file_change.proposed_value, "K-19: The Widowmaker (2002).mkv")
            self.assertEqual(folder_change.confidence, "review")
            self.assertEqual(file_change.confidence, "review")
            self.assertIn("normalized_title_punctuation_upgrade", folder_change.reason_codes)
            self.assertIn("normalized_title_punctuation_upgrade", file_change.reason_codes)

    def test_build_movie_plan_marks_legacy_normalized_ordinal_and_abbreviation_upgrades_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            ordinal_folder = source / "25Th Hour (2002)"
            ordinal_folder.mkdir()
            (ordinal_folder / "25Th Hour (2002).mkv").write_text("video", encoding="utf-8")
            abbreviation_folder = source / "Mr Nobody (2009)"
            abbreviation_folder.mkdir()
            (abbreviation_folder / "Mr Nobody (2009).mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            ordinal_folder_change = next(
                change for change in plan.proposed_changes if change.current_value == "25Th Hour (2002)"
            )
            ordinal_file_change = next(
                change for change in plan.proposed_changes if change.current_value == "25Th Hour (2002).mkv"
            )
            abbreviation_folder_change = next(
                change for change in plan.proposed_changes if change.current_value == "Mr Nobody (2009)"
            )
            abbreviation_file_change = next(
                change for change in plan.proposed_changes if change.current_value == "Mr Nobody (2009).mkv"
            )

            self.assertEqual(ordinal_folder_change.proposed_value, "25th Hour (2002)")
            self.assertEqual(ordinal_file_change.proposed_value, "25th Hour (2002).mkv")
            self.assertEqual(abbreviation_folder_change.proposed_value, "Mr. Nobody (2009)")
            self.assertEqual(abbreviation_file_change.proposed_value, "Mr. Nobody (2009).mkv")
            for change in (
                ordinal_folder_change,
                ordinal_file_change,
                abbreviation_folder_change,
                abbreviation_file_change,
            ):
                self.assertEqual(change.confidence, "review")
                self.assertIn("normalized_title_punctuation_upgrade", change.reason_codes)

    def test_build_movie_plan_does_not_overreach_into_unsettled_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            (source / "21.Jump.Street.2012.1080p.mkv").write_text("video", encoding="utf-8")
            (source / "Mission.Impossible.Dead.Reckoning.Part.One.2023.1080p.mkv").write_text("video", encoding="utf-8")
            (source / "The.Devils.Advocate.1997.1080p.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn("21 Jump Street (2012)/21 Jump Street (2012).mkv", proposed_values)
            self.assertIn(
                "Mission Impossible Dead Reckoning Part One (2023)/Mission Impossible Dead Reckoning Part One (2023).mkv",
                proposed_values,
            )
            self.assertIn("The Devils Advocate (1997)/The Devils Advocate (1997).mkv", proposed_values)

    def test_build_movie_plan_splits_leading_number_compact_bracket_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE]"
            folder.mkdir()
            movie = folder / "(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968).mkv",
                    "review",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968)",
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

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "2001 A Space Odyssey (1968)",
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

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "1917 (2019).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "1917 (2019)",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_handles_dotted_numeric_title_with_release_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "1917.2019.1080p.Bluray.Atmos.TrueHD.7.1.x264-EVO.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "1917 (2019)/1917 (2019).mkv",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_treats_common_long_descriptors_as_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "A.Nightmare.on.Elm.Street.1984.Remastered.1080p.BluRay.x265.hevc.10bit.AAC.7.1.commentary-HeVK.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "A Nightmare On Elm Street (1984)/A Nightmare On Elm Street (1984).mkv",
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

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Wings Of Desire (1987)/Wings Of Desire (1987).mkv",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_strips_spaced_website_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Www Hdsector Com Hachi A Dog's Tale (2009) [BluRay 1080p x264 AAC 5.1 HON3Y].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Hachi A Dog's Tale (2009)/Hachi A Dog's Tale (2009).mkv",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_uses_parent_year_with_yearless_release_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "I Want to Eat Your Pancreas (2018)"
            folder.mkdir()
            movie = folder / "[Arid] I Want to Eat Your Pancreas (BDRip 1080p HEVC OPUS) [BCB2E441].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "I Want To Eat Your Pancreas (2018).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "I Want To Eat Your Pancreas (2018)",
                    "safe",
                ),
                proposed,
            )

    def test_build_movie_plan_uses_known_yearless_title_hint_for_pancreas_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "[Arid] I Want to Eat Your Pancreas (BDRip 1080p HEVC OPUS) [BCB2E441].mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "I Want To Eat Your Pancreas (2018)/I Want To Eat Your Pancreas (2018).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_build_movie_plan_strips_generic_leading_bracket_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "The Apartment (1960)"
            folder.mkdir()
            movie = folder / "[Arid] The Apartment 1960 1080p BluRay x264-GRP.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "The Apartment (1960).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertFalse(plan.warnings)

    def test_build_movie_plan_allows_nine_character_unknown_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Boundary.1999.NineChars.1080p.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Boundary (1999)/Boundary (1999).mkv",
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

            plan = build_movie_plan(source)

            proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(
                (
                    "Basic Instinct (1992).mkv",
                    "safe",
                ),
                proposed,
            )
            self.assertIn(
                (
                    "Basic Instinct (1992)",
                    "safe",
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

            plan = build_movie_plan(source)

            self.assertEqual(plan.proposed_changes, [])
            self.assertEqual(plan.warnings[0].code, "movie_folder_multiple_videos")

    def test_build_movie_plan_uses_resolution_differentiator_for_shining_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            clean = source / "The Shining (1980)"
            noisy = source / "The Shining (1980) [Extended 1072p BluRay 5.1 x264 NVEE]"
            clean.mkdir()
            noisy.mkdir()
            (clean / "The Shining (1980).mkv").write_text("video", encoding="utf-8")
            (noisy / "The Shining (1980) [Extended 1072p BluRay 5.1 x264 NVEE].mkv").write_text(
                "video",
                encoding="utf-8",
            )

            plan = build_movie_plan(source)
            report = apply_changes_in_place(source, plan.proposed_changes)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("file_rename", "The Shining (1980) 1072p.mkv", "safe"), proposed)
            self.assertIn(("folder_rename", "The Shining (1980) 1072p", "safe"), proposed)
            self.assertEqual(len(report.applied), 2)
            self.assertFalse(report.failed)
            self.assertTrue((source / "The Shining (1980) 1072p" / "The Shining (1980) 1072p.mkv").exists())

    def test_build_movie_plan_deletes_metadata_only_duplicate_movie_artifact_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            clean = source / "The Shining (1980)"
            noisy = source / "The Shining (1980) [Extended 1072p BluRay 5.1 x264 NVEE]"
            clean.mkdir()
            noisy.mkdir()
            (clean / "The Shining (1980).mkv").write_text("video", encoding="utf-8")
            (noisy / "The Shining (1980) [Extended 1072p BluRay 5.1 x264 NVEE].nfo").write_text(
                "metadata",
                encoding="utf-8",
            )

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.current_value, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("folder_delete", noisy.name, "", "safe"), proposed)
            self.assertNotIn("folder_rename", {change.change_type for change in plan.proposed_changes})
            self.assertNotIn("folder_merge", {change.change_type for change in plan.proposed_changes})

    def test_build_movie_plan_deletes_metadata_only_duplicate_movie_artifact_folder_with_nfo_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            clean = source / "The Shining (1980)"
            noisy = source / "The Shining (1980) [Extended 1072p BluRay 5.1 x264 NVEE]"
            clean.mkdir()
            noisy.mkdir()
            (clean / "The Shining (1980).mkv").write_text("video", encoding="utf-8")
            (clean / "The Shining (1980).nfo").write_text("metadata", encoding="utf-8")
            (noisy / "The Shining (1980).nfo").write_text("metadata", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.current_value, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("folder_delete", noisy.name, "", "safe"), proposed)
            self.assertNotIn("folder_rename", {change.change_type for change in plan.proposed_changes})
            self.assertNotIn("folder_merge", {change.change_type for change in plan.proposed_changes})

    def test_build_movie_plan_merges_subtitle_only_residue_into_existing_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            clean = source / "The Shining (1980)"
            residue = source / "The Shining (1980) [1080p BluRay x264]"
            clean.mkdir()
            residue.mkdir()
            (clean / "The Shining (1980).mkv").write_text("video", encoding="utf-8")
            (residue / "The Shining (1980).eng.srt").write_text("subs", encoding="utf-8")
            (residue / "poster.jpg").write_text("art", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("file_move", "The Shining (1980)/The Shining (1980).eng.srt", "safe"), proposed)
            self.assertIn(("folder_delete", "", "safe"), proposed)

    def test_build_movie_plan_keeps_subtitle_collision_as_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            clean = source / "The Shining (1980)"
            residue = source / "The Shining (1980) [1080p BluRay x264]"
            clean.mkdir()
            residue.mkdir()
            (clean / "The Shining (1980).mkv").write_text("video", encoding="utf-8")
            (clean / "The Shining (1980).eng.srt").write_text("subs", encoding="utf-8")
            (residue / "The Shining (1980).eng.srt").write_text("subs", encoding="utf-8")

            plan = build_movie_plan(source)

            review = next(change for change in plan.proposed_changes if change.confidence == "review")
            self.assertIn("subtitle_merge_collision", review.reason_codes)

    def test_build_movie_plan_deletes_empty_package_artifacts_without_year(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            godfather = source / "The Godfather Trilogy [I II III] 1080p BluRay x264 anoXmous"
            apes = source / "Planet of the Apes Legends The Collection 1080p H 264 ENG-FRE-SPA (moviesbyrizzo)"
            godfather.mkdir()
            apes.mkdir()

            plan = build_movie_plan(source)

            deletes = {(change.current_value, change.change_type, change.confidence) for change in plan.proposed_changes}
            self.assertIn((godfather.name, "folder_delete", "safe"), deletes)
            self.assertIn((apes.name, "folder_delete", "safe"), deletes)

    def test_build_movie_plan_splits_distinct_movies_from_package_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Short Circuit Duology (1986-1988) BDRip 1080p HighCode"
            folder.mkdir()
            (folder / "Short Circuit 1986 BDRip 1080p HighCode.mkv").write_text("video", encoding="utf-8")
            (folder / "Short Circuit 2 1988 BDRip 1080p HighCode.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("file_move", "Short Circuit (1986)/Short Circuit (1986).mkv", "safe"), proposed)
            self.assertIn(("file_move", "Short Circuit 2 (1988)/Short Circuit 2 (1988).mkv", "safe"), proposed)
            self.assertIn(("folder_delete", "", "safe"), proposed)

    def test_build_movie_plan_does_not_project_trilogy_marker_into_year_only_package_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Mad Max Trilogy 1080p BluRay x264"
            folder.mkdir()
            for filename in [
                "1979 1080p BluRay x264.mkv",
                "1981 1080p BluRay x264.mkv",
                "1985 1080p BluRay x264.mkv",
            ]:
                (folder / filename).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed_values = {change.proposed_value for change in plan.proposed_changes}
            self.assertFalse(any("Mad Max Trilogy" in proposed_value for proposed_value in proposed_values))
            self.assertFalse(any(change.change_type == "file_move" for change in plan.proposed_changes))
            self.assertIn("multi_video_package_skipped_lack_child_evidence", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_splits_trilogy_package_when_child_titles_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Mad Max Trilogy 1080p BluRay x264"
            folder.mkdir()
            for filename in [
                "Mad Max 1979 1080p BluRay x264.mkv",
                "Mad Max 2 1981 1080p BluRay x264.mkv",
                "Mad Max Beyond Thunderdome 1985 1080p BluRay x264.mkv",
            ]:
                (folder / filename).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("file_move", "Mad Max (1979)/Mad Max (1979).mkv", "safe"), proposed)
            self.assertIn(("file_move", "Mad Max 2 (1981)/Mad Max 2 (1981).mkv", "safe"), proposed)
            self.assertIn(("file_move", "Mad Max Beyond Thunderdome (1985)/Mad Max Beyond Thunderdome (1985).mkv", "safe"), proposed)
            self.assertIn(("folder_delete", "", "safe"), proposed)

    def test_build_movie_plan_splits_ampersand_double_feature_when_files_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Grindhouse Planet Terror & Death Proof 1080p Unrated [mkvonly]"
            folder.mkdir()
            (folder / "Planet Terror 2007 1080p Unrated mkvonly.mkv").write_text("video", encoding="utf-8")
            (folder / "Death Proof 2007 1080p Unrated mkvonly.mkv").write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("file_move", "Planet Terror (2007)/Planet Terror (2007).mkv", "safe"), proposed)
            self.assertIn(("file_move", "Death Proof (2007)/Death Proof (2007).mkv", "safe"), proposed)
            self.assertIn(("folder_delete", "", "safe"), proposed)

    def test_build_movie_plan_splits_ampersand_double_feature_with_sidecar_nfo_years(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Grindhouse Planet Terror & Death Proof 1080p Unrated [mkvonly]"
            folder.mkdir()
            planet_terror = folder / "Planet Terror 1080p Unrated mkvonly.mkv"
            death_proof = folder / "Death Proof 1080p Unrated mkvonly.mkv"
            planet_terror.write_text("video", encoding="utf-8")
            death_proof.write_text("video", encoding="utf-8")
            planet_terror.with_suffix(".nfo").write_text(
                "<movie><title>Planet Terror</title><year>2007</year></movie>",
                encoding="utf-8",
            )
            death_proof.with_suffix(".nfo").write_text(
                "<movie><title>Death Proof</title><year>2007</year></movie>",
                encoding="utf-8",
            )

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("file_move", "Planet Terror (2007)/Planet Terror (2007).mkv", "safe"), proposed)
            self.assertIn(("file_move", "Death Proof (2007)/Death Proof (2007).mkv", "safe"), proposed)
            self.assertIn(("folder_delete", "", "safe"), proposed)

    def test_build_movie_plan_recovers_garbled_post_split_double_feature_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            folder = source / "Grindhouse Planet Terror & Death Proof 1080p Unrated [mkvonly]"
            folder.mkdir()
            (
                folder / "Death Proof (2007) Grindhouse Planet Terror & Death Proof 1080p Unrated Mkvonly.mkv"
            ).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {(change.change_type, change.proposed_value, change.confidence) for change in plan.proposed_changes}
            self.assertIn(("file_rename", "Death Proof (2007).mkv", "safe"), proposed)
            self.assertNotIn(("file_rename", "Death Proof (2007) Grindhouse Planet Terror & Death Proof 1080p Unrated Mkvonly.mkv", "review"), proposed)
            self.assertNotIn("unknown_technical_token", {warning.code for warning in plan.warnings})

    def test_build_movie_plan_keeps_package_folder_when_existing_target_collision_needs_salvage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            canonical = source / "Death Proof (2007)"
            canonical.mkdir()
            (canonical / "Death Proof (2007).mkv").write_text("video", encoding="utf-8")
            folder = source / "Grindhouse Planet Terror & Death Proof 1080p Unrated [mkvonly]"
            folder.mkdir()
            (
                folder / "Death Proof (2007) Grindhouse Planet Terror & Death Proof 1080p Unrated Mkvonly.mkv"
            ).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            file_change = next(change for change in plan.proposed_changes if change.change_type == "file_rename")
            self.assertEqual(file_change.proposed_value, "Death Proof (2007) 1080p.mkv")
            self.assertEqual(file_change.confidence, "safe")
            self.assertNotIn("movie_name_existing_target_collision", {warning.code for warning in plan.warnings})
            self.assertFalse(any(change.change_type == "folder_rename" for change in plan.proposed_changes))

    def test_build_movie_plan_trims_reported_verbose_parser_slips(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            for filename in [
                "Star Trek III The Search for Spock 1984 BDRip 2160p UHD HDR Multilang TrueHD DD5 1 gerald99.mkv",
                "Man on Fire 2004 WEBRip 2160p HEVC Open Matte Eng DTS DDP5 1 gerald99.mkv",
                "Land of the Dead 2005 BluRayRemux 1080p x264 3Rus Eng -CME.mkv",
            ]:
                (source / filename).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            proposed = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "Star Trek III The Search For Spock (1984)/Star Trek III The Search For Spock (1984).mkv",
                proposed,
            )
            self.assertIn(
                "Man On Fire (2004)/Man On Fire (2004).mkv",
                proposed,
            )
            self.assertIn(
                "Land Of The Dead (2005)/Land Of The Dead (2005).mkv",
                proposed,
            )


if __name__ == "__main__":
    unittest.main()
