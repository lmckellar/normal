from __future__ import annotations

import unittest

from normal import movie_moron_encoders as me


class MoronEncoderDataTest(unittest.TestCase):
    def test_data_loads_with_expected_version(self):
        payload = me._load_data()
        self.assertEqual(payload["version"], me.DATA_VERSION)

    def test_every_entry_is_well_formed(self):
        payload = me._load_data()
        tiers = payload["tiers"]
        self.assertTrue(payload["encoders"])
        for entry in payload["encoders"]:
            self.assertIn(entry["tier"], tiers)
            self.assertTrue(entry["name"])
            self.assertTrue(entry["aliases"])
            self.assertTrue(entry["note"])
        for tier in tiers.values():
            self.assertIn(tier["severity"], {"severe", "review"})
            self.assertTrue(tier["code"])
            self.assertTrue(tier["category"])


class MoronEncoderLookupTest(unittest.TestCase):
    def test_release_group_match_is_case_and_punctuation_insensitive(self):
        verdict = me.lookup_moron_encoder("YIFY")
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict.tier, "punt")
        self.assertEqual(verdict.code, "known_moron_encoder")
        self.assertEqual(verdict.severity, "severe")

    def test_bracket_tagged_uploader_caught_via_stem(self):
        verdict = me.lookup_moron_encoder(None, stem="Some Movie (2015) [1080p] [YTS.MX]")
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict.name, "YIFY")

    def test_warn_tier_match(self):
        verdict = me.lookup_moron_encoder("moviesbyrizzo")
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict.tier, "warn")
        self.assertEqual(verdict.code, "suspect_encoder")

    def test_punt_outranks_warn_when_both_present(self):
        verdict = me.lookup_moron_encoder("PSA", stem="Movie.2015.1080p.BluRay.x264-YIFY")
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict.tier, "punt")

    def test_unknown_group_returns_none(self):
        self.assertIsNone(me.lookup_moron_encoder("SPARKS"))
        self.assertIsNone(me.lookup_moron_encoder(None, stem="Clean.Movie.2020.1080p.BluRay-RARBG"))

    def test_summary_leads_with_name(self):
        verdict = me.lookup_moron_encoder("YIFY")
        self.assertTrue(verdict.summary.startswith("YIFY — "))


if __name__ == "__main__":
    unittest.main()
