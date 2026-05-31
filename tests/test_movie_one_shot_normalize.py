from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from normal.movie_identity import parse_movie_identity
from normal.movie_plan import build_movie_plan
from normal.movie_preclean import MOVIE_PRECLEAN_BUCKETS, load_movie_preclean_entries


class MovieOneShotNormalizeTests(unittest.TestCase):
    ROUND2_CASES_PATH = Path(__file__).parent / "data" / "normalize_round2_cases.json"

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

            plan = build_movie_plan(source)

            self.assertFalse(plan.warnings)
            self.assertTrue(plan.proposed_changes)
            self.assertTrue(all(change.confidence == "safe" for change in plan.proposed_changes))

    def test_leading_release_credit_noise_is_removed_from_title_inference(self) -> None:
        cases = {
            "www.YTS.mx.The.Big.Lebowski.1998.1080p.BluRay.x264.AAC.mkv": "The Big Lebowski (1998)",
            "Downloaded.from.TorrentGalaxy.to.The.Thing.1982.1080p.BluRay.x264-GRP.mkv": "The Thing (1982)",
            "Oxtorrent Com Apollo 11 (2019).mkv": "Apollo 11 (2019)",
            "Apollo 11 (2019) Oxtorrent Com.mkv": "Apollo 11 (2019)",
            "[Oxtorrent Com] Apollo 11 (2019).mkv": "Apollo 11 (2019)",
            "www.Oxtorrent.com [TorrentGalaxy.to] Apollo 11 (2019) [Oxtorrent Com].mkv": "Apollo 11 (2019)",
            "MoviesByRizzo - The Sting 1973 1080p BluRay x264 AAC.mkv": "The Sting (1973)",
            "anoXmous - The Godfather 1972 1080p BluRay x264.mp4": "The Godfather (1972)",
            "ETRG - The Social Network 2010 720p BluRay x264.mp4": "The Social Network (2010)",
            "[YTS.AM] Casablanca (1942) [1080p] [BluRay] [YTS.AM].mp4": "Casablanca (1942)",
            "[TGx] The Apartment 1960 1080p BluRay x264-GRP.mkv": "The Apartment (1960)",
            "[Erai-raws] Perfect Blue (1997) [1080p][Multiple Subtitle].mkv": "Perfect Blue (1997)",
        }

        for filename, expected_base in cases.items():
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir)
                    movie = source / filename
                    movie.parent.mkdir(parents=True, exist_ok=True)
                    movie.write_text("video", encoding="utf-8")

                    plan = build_movie_plan(source, movie_files=[movie])

                    self.assertFalse(plan.warnings)
                    self.assertIn(
                        f"{expected_base}/{expected_base}{movie.suffix.lower()}",
                        {change.proposed_value for change in plan.proposed_changes},
                    )

    def test_split_domain_credit_rule_does_not_strip_short_real_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Dot.Com.2003.1080p.BluRay.x264.mkv"
            movie.write_text("video", encoding="utf-8")

            plan = build_movie_plan(source, movie_files=[movie])

            self.assertIn(
                "Dot Com (2003)/Dot Com (2003).mkv",
                {change.proposed_value for change in plan.proposed_changes},
            )

    def test_domain_credit_rules_do_not_strip_short_or_mid_title_tokens(self) -> None:
        cases = {
            "Dot.Com.2003.1080p.BluRay.x264.mkv": "Dot Com (2003)",
            "Coma.1978.1080p.BluRay.x264.mkv": "Coma (1978)",
            "To.Die.For.1995.1080p.BluRay.x264.mkv": "To Die For (1995)",
            "Bone.Tomahawk.2015.1080p.BluRay.x264.mkv": "Bone Tomahawk (2015)",
        }

        for filename, expected_base in cases.items():
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir)
                    movie = source / filename
                    movie.write_text("video", encoding="utf-8")

                    plan = build_movie_plan(source, movie_files=[movie])

                    self.assertIn(
                        f"{expected_base}/{expected_base}.mkv",
                        {change.proposed_value for change in plan.proposed_changes},
                    )

    def test_shouting_titles_normalize_to_title_case_when_safe(self) -> None:
        cases = {
            "DEEP BLUE SEA.1999.mkv": "Deep Blue Sea (1999)",
            "STAR WARS.1977.mkv": "Star Wars (1977)",
            "X MEN.2000.mkv": "X Men (2000)",
        }

        for filename, expected_base in cases.items():
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir)
                    movie = source / filename
                    movie.write_text("video", encoding="utf-8")

                    plan = build_movie_plan(source, movie_files=[movie])

                    self.assertIn(
                        f"{expected_base}/{expected_base}.mkv",
                        {change.proposed_value for change in plan.proposed_changes},
                    )

    def test_already_normalized_parent_child_title_is_not_truncated_by_domain_credit_rule(self) -> None:
        parsed = parse_movie_identity(Path("Bone Tomahawk (2015)/Bone Tomahawk (2015).mkv"))
        self.assertEqual(parsed.title, "Bone Tomahawk")
        self.assertEqual(parsed.year, 2015)
        self.assertEqual(parsed.confidence, "safe")

    def test_trailing_domain_credit_is_not_preserved_as_technical_tail(self) -> None:
        parsed = parse_movie_identity(Path("Apollo 11 (2019) Oxtorrent Com.mkv"))
        self.assertEqual(parsed.title, "Apollo 11")
        self.assertEqual(parsed.year, 2019)
        self.assertEqual(parsed.tech_tokens, [])

    def test_known_language_and_cut_tokens_remain_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            for filename in [
                "City.of.God.2002.PORTUGUESE.1080p.BluRay.x264.DTS-GRP.mkv",
                "Leon.The.Professional.1994.International.Cut.1080p.BluRay.x264-GRP.mkv",
            ]:
                (source / filename).write_text("video", encoding="utf-8")

            plan = build_movie_plan(source)

            self.assertFalse(plan.warnings)
            proposed = {change.proposed_value for change in plan.proposed_changes}
            self.assertIn(
                "City Of God (2002)/City Of God (2002).mkv",
                proposed,
            )
            self.assertIn(
                "Leon The Professional (1994)/Leon The Professional (1994).mkv",
                proposed,
            )

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
            "Land.of.the.Dead.2005.BluRayRemux.1080p.x264.3Rus.Eng.-CME-v0.mkv": "Land Of The Dead (2005)",
            "Resolution.Trap.2017.1920x820.1080p.BluRay.x264-GRP.mkv": "Resolution Trap (2017)",
        }
        review_cases = [
            (
                "(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE]",
                "(2001) [ASPACEODYSSEY1968V22160PBLURAYX26510BITHDRTIGOLE].mkv",
            ),
        ]
        safe_compact_cases = [
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
                    plan = build_movie_plan(source, movie_files=[movie])
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
                    plan = build_movie_plan(source, movie_files=[movie])
                    self.assertIn("compact_token_heuristic", {warning.code for warning in plan.warnings})
                    self.assertTrue(any(change.confidence == "review" for change in plan.proposed_changes))

        for folder_name, filename in safe_compact_cases:
            with self.subTest(folder_name=folder_name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir)
                    folder = source / folder_name
                    folder.mkdir()
                    movie = folder / filename
                    movie.write_text("video", encoding="utf-8")
                    plan = build_movie_plan(source, movie_files=[movie])
                    self.assertFalse(plan.warnings)
                    self.assertTrue(all(change.confidence == "safe" for change in plan.proposed_changes))

    def test_load_movie_preclean_entries_without_path_returns_empty(self) -> None:
        self.assertEqual(load_movie_preclean_entries(), [])

    def test_committed_round2_regression_cases(self) -> None:
        cases = json.loads(self.ROUND2_CASES_PATH.read_text(encoding="utf-8"))
        for case in cases:
            with self.subTest(path=case["path"]):
                with tempfile.TemporaryDirectory() as tmpdir:
                    source = Path(tmpdir)
                    movie = source / case["path"]
                    movie.parent.mkdir(parents=True, exist_ok=True)
                    movie.write_text("video", encoding="utf-8")
                    plan = build_movie_plan(source, movie_files=[movie])
                    proposed = {(change.proposed_value, change.confidence) for change in plan.proposed_changes}
                    self.assertIn((case["expected_target"], case["expected_confidence"]), proposed)

    def test_load_movie_preclean_entries_with_missing_path_returns_empty(self) -> None:
        missing = Path("/tmp/normal-missing-preclean.jsonl")
        if missing.exists():
            missing.unlink()
        self.assertEqual(load_movie_preclean_entries(missing), [])

    def test_load_movie_preclean_entries_loads_valid_jsonl(self) -> None:
        payload = {
            "path": "/tmp/example",
            "action": "remove",
            "reason": "test",
            "bucket": sorted(MOVIE_PRECLEAN_BUCKETS)[0],
            "notes": "note",
            "timestamp": "2026-05-23T00:00:00+10:00",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "movie-preclean.jsonl"
            ledger.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            entries = load_movie_preclean_entries(ledger)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, payload["path"])
        self.assertEqual(entries[0].bucket, payload["bucket"])

    def test_load_movie_preclean_entries_rejects_unknown_bucket(self) -> None:
        payload = {
            "path": "/tmp/example",
            "action": "remove",
            "reason": "test",
            "bucket": "unknown_bucket",
            "notes": "note",
            "timestamp": "2026-05-23T00:00:00+10:00",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "movie-preclean.jsonl"
            ledger.write_text(json.dumps(payload) + "\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_movie_preclean_entries(ledger)


if __name__ == "__main__":
    unittest.main()
