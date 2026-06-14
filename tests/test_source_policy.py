from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.source_policy import (
    DRIVE_DIRECTORY,
    SOURCE_MISSING,
    SourcePolicyError,
    classify_source,
    enforce_source_policy,
)


class SourcePolicyTests(unittest.TestCase):
    def test_normal_directory_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            risk = classify_source(Path(tmpdir), operation="mutate")
            self.assertEqual(risk.severity, "ok")
            self.assertEqual(risk.flags, ())

    def test_filesystem_root_blocks_mutation(self) -> None:
        risk = classify_source(Path(Path("/").anchor), operation="mutate")
        self.assertEqual(risk.severity, "block")
        self.assertIn(DRIVE_DIRECTORY, risk.flags)

    def test_missing_source_blocks_mutation(self) -> None:
        risk = classify_source(Path("/no/such/source/here"), operation="mutate")
        self.assertEqual(risk.severity, "block")
        self.assertIn(SOURCE_MISSING, risk.flags)

    def test_enforce_raises_on_block(self) -> None:
        with self.assertRaises(SourcePolicyError):
            enforce_source_policy(Path(Path("/").anchor), operation="mutate")

    def test_enforce_allows_normal_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            enforce_source_policy(Path(tmpdir), operation="mutate")


if __name__ == "__main__":
    unittest.main()
