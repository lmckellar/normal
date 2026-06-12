from __future__ import annotations

import unittest

from normal.movie_naming import (
    canonicalize_match_text,
    match_variant_keys,
    numeral_variant_keys,
    title_alias_keys,
    title_match_key,
)


class CanonicalizeMatchTextTests(unittest.TestCase):
    def test_accents_fold_to_ascii(self) -> None:
        self.assertEqual(title_match_key("Café"), "cafe")
        self.assertEqual(title_match_key("Amélie"), "amelie")
        # The accented and unaccented spellings must converge on one key.
        self.assertEqual(title_match_key("Amélie"), title_match_key("Amelie"))

    def test_ampersand_becomes_and(self) -> None:
        self.assertEqual(title_match_key("Sex & the City"), "sex and the city")
        self.assertEqual(
            title_match_key("Sex & the City"), title_match_key("Sex and the City")
        )

    def test_canonicalize_is_pre_key_only(self) -> None:
        # The helper folds noise but does not lower-case or strip punctuation;
        # that stays the job of title_match_key.
        self.assertEqual(canonicalize_match_text("Café & Bar"), "Cafe  and  Bar")


class NumeralVariantTests(unittest.TestCase):
    def test_trailing_arabic_expands_to_roman(self) -> None:
        self.assertIn("spider man ii", match_variant_keys("Spider-Man 2"))

    def test_trailing_roman_expands_to_arabic(self) -> None:
        self.assertIn("spider man 2", match_variant_keys("Spider-Man II"))

    def test_sequel_keyword_position_expands(self) -> None:
        self.assertIn("john wick chapter iv", match_variant_keys("John Wick: Chapter 4"))
        self.assertIn("star wars episode 4", match_variant_keys("Star Wars: Episode IV"))

    def test_ambiguous_single_roman_not_expanded_without_keyword(self) -> None:
        # "Malcolm X" / "V for Vendetta" must not gain a bogus numeric variant.
        self.assertEqual(numeral_variant_keys("malcolm x"), [])
        self.assertEqual(numeral_variant_keys("v for vendetta"), [])

    def test_arabic_and_roman_spellings_meet_at_a_shared_key(self) -> None:
        # Even where a single trailing roman is intentionally not expanded,
        # the arabic side expands so the two spellings still share a key.
        shared = set(title_alias_keys("Rocky 5")) & set(title_alias_keys("Rocky V"))
        self.assertIn("rocky v", shared)


if __name__ == "__main__":
    unittest.main()
