from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.movie_immersive_confirmations import (
    confirmation_index,
    confirmation_key,
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

    def test_missing_store_returns_seed_only(self) -> None:
        self.assertEqual(confirmation_index(self.path), seed_index())

    def test_unknown_shadows_seed(self) -> None:
        key = confirmation_key("Dune", 2021)
        self.assertIn(key, seed_index())
        set_confirmation("Dune", 2021, "unknown", state_path=self.path)
        self.assertNotIn(key, confirmation_index(self.path))


if __name__ == "__main__":
    unittest.main()
