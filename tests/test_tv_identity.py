from __future__ import annotations

import unittest
from pathlib import Path

from normal.tv_identity import parse_tv_identity


class TvIdentityTests(unittest.TestCase):
    def test_numbering_precedence_and_series_sources(self) -> None:
        cases = (
            (
                Path("/tv/Mad Men/Mad Men S05E01-E02 1080p.mkv"),
                ("Mad Men", 5, 1, 2, "span", "file"),
            ),
            (
                Path("/tv/Game of Thrones The Complete Collection (2011-2019)/S01 - E01 - Winter Is Coming.mkv"),
                ("Game Of Thrones", 1, 1, None, "loose_sxe", "folder"),
            ),
            (
                Path("/tv/Fullmetal Alchemist/Fullmetal Alchemist 1x01.mkv"),
                ("Fullmetal Alchemist", 1, 1, None, "x", "file"),
            ),
        )

        for path, expected in cases:
            with self.subTest(path=path):
                identity = parse_tv_identity(path, source_root=Path("/tv"))
                self.assertEqual(
                    (
                        identity.series,
                        identity.season,
                        identity.episode_first,
                        identity.episode_last,
                        identity.numbering,
                        identity.series_source,
                    ),
                    expected,
                )
                self.assertEqual(identity.confidence, "safe")

    def test_absolute_numbering_is_preserved_without_season_evidence(self) -> None:
        identity = parse_tv_identity(
            Path("/tv/Tokyo Ghoul/Tokyo Ghoul - 01 [1080p][x265].mkv"),
            source_root=Path("/tv"),
        )

        self.assertIsNone(identity.season)
        self.assertIsNone(identity.episode_first)
        self.assertEqual(identity.absolute_episode, 1)
        self.assertIn("anime_absolute_numbering_risk", identity.reason_codes)
        self.assertEqual(identity.confidence, "safe")

    def test_absolute_numbering_converts_only_with_folder_season(self) -> None:
        identity = parse_tv_identity(
            Path("/tv/Darker Than Black Season 1/Darker Than Black - 01.mkv"),
            source_root=Path("/tv"),
        )

        self.assertEqual((identity.season, identity.episode_first), (1, 1))
        self.assertEqual(identity.season_source, "folder")
        self.assertIn("tv_absolute_converted_from_folder_season", identity.reason_codes)

        outside_season = parse_tv_identity(
            Path("/Season 9/tv/Show/Show - 01.mkv"),
            source_root=Path("/Season 9/tv"),
        )
        self.assertIsNone(outside_season.season)
        self.assertEqual(outside_season.absolute_episode, 1)

    def test_n_of_m_permits_miniseries_conversion(self) -> None:
        identity = parse_tv_identity(
            Path("/tv/Miniseries/Miniseries - 1 of 3 - Love and Power.avi"),
            source_root=Path("/tv"),
        )

        self.assertEqual((identity.season, identity.episode_first, identity.season_length), (1, 1, 3))
        self.assertEqual(identity.episode_title, "Love And Power")
        self.assertEqual(identity.confidence, "safe")

    def test_cosmetic_stripping_preserves_hyphenated_series(self) -> None:
        identity = parse_tv_identity(
            Path("/tv/mushi-shi/[AnimeRG]mushi-shi_-_01_-_The Green Seat_[D07A158D].mkv"),
            source_root=Path("/tv"),
        )

        self.assertEqual(identity.series, "Mushi-shi")
        self.assertEqual(identity.absolute_episode, 1)
        self.assertEqual(identity.episode_title, "The Green Seat")

    def test_specials_and_embedded_movies_route_to_review(self) -> None:
        for path in (
            Path("/tv/Show/OVA/Show S01E01.mkv"),
            Path("/tv/Futurama/Movies/Benders.Game.2008.mkv"),
            Path("/tv/Show/Show S00E01.mkv"),
        ):
            with self.subTest(path=path):
                identity = parse_tv_identity(path, source_root=Path("/tv"))
                self.assertEqual(identity.confidence, "review")
                self.assertIn("tv_special_content_review", identity.reason_codes)


if __name__ == "__main__":
    unittest.main()
