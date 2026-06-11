from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_immersive_confirmations import (
    SEED_NOT_AVAILABLE,
    confirmation_index,
    confirmation_key,
    not_available_seed_index,
    record_available_observations,
    seed_index,
    set_confirmation,
)


class ImmersiveConfirmationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "immersive-confirmations.json"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_available_roundtrips_into_index(self) -> None:
        set_confirmation("Dune", 2021, "available", state_path=self.path)
        index = confirmation_index(self.path)
        self.assertEqual(index.get(confirmation_key("Dune", 2021)), "available")

    def test_final_below_target_stored(self) -> None:
        set_confirmation("Heat", 1995, "final_below_target", state_path=self.path)
        index = confirmation_index(self.path)
        self.assertEqual(index.get(confirmation_key("Heat", 1995)), "final_below_target")

    def test_unknown_clears_record_and_index(self) -> None:
        set_confirmation("Dune", 2021, "available", state_path=self.path)
        set_confirmation("Dune", 2021, "unknown", state_path=self.path)
        index = confirmation_index(self.path)
        self.assertNotIn(confirmation_key("Dune", 2021), index)

    def test_invalid_verdict_rejected(self) -> None:
        with self.assertRaises(ValueError):
            set_confirmation("Dune", 2021, "maybe", state_path=self.path)

    def test_missing_store_returns_seeds_only(self) -> None:
        expected = {**not_available_seed_index(), **seed_index()}
        self.assertEqual(confirmation_index(self.path), expected)

    def test_unknown_shadows_seed(self) -> None:
        key = confirmation_key("Dune", 2021)
        self.assertIn(key, seed_index())
        set_confirmation("Dune", 2021, "unknown", state_path=self.path)
        self.assertNotIn(key, confirmation_index(self.path))

    def test_not_available_seed_present(self) -> None:
        title, year = SEED_NOT_AVAILABLE[0]
        self.assertEqual(
            confirmation_index(self.path).get(confirmation_key(title, year)),
            "final_below_target",
        )

    def test_available_always_overrides_not_available(self) -> None:
        title, year = SEED_NOT_AVAILABLE[0]
        key = confirmation_key(title, year)
        # A telemetry/user available vote falsifies the not-available seed.
        set_confirmation(title, year, "available", state_path=self.path)
        self.assertEqual(confirmation_index(self.path).get(key), "available")
        # And the reverse never wins: a stale final vote cannot beat available.
        set_confirmation("Dune", 2021, "final_below_target", state_path=self.path)
        self.assertEqual(
            confirmation_index(self.path).get(confirmation_key("Dune", 2021)),
            "available",
        )

    def test_harvest_records_new_titles_and_dedupes(self) -> None:
        added = record_available_observations(
            [("Heat", 1995), ("Heat", 1995), ("", 2000), ("Bad", None)],
            state_path=self.path,
        )
        self.assertEqual([record["key"] for record in added], [confirmation_key("Heat", 1995)])
        self.assertEqual(
            confirmation_index(self.path).get(confirmation_key("Heat", 1995)),
            "available",
        )
        # Already-available titles produce no new records.
        self.assertEqual(record_available_observations([("Heat", 1995)], state_path=self.path), [])


if __name__ == "__main__":
    unittest.main()
