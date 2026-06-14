from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.source_policy import (
    ApprovedRoots,
    DRIVE_DIRECTORY,
    Operation,
    SOURCE_MISSING,
    SourcePolicyError,
    classify_source,
    path_is_under,
    source_paths_overlap,
    validate_source_for_operation,
)


class SourcePolicyTests(unittest.TestCase):
    def test_normal_directory_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            risk = classify_source(Path(tmpdir), operation=Operation.APPLY)
            self.assertEqual(risk.severity, "ok")
            self.assertEqual(risk.flags, ())

    def test_filesystem_root_blocks_mutation(self) -> None:
        risk = classify_source(Path(Path("/").anchor), operation=Operation.APPLY)
        self.assertEqual(risk.severity, "block")
        self.assertIn(DRIVE_DIRECTORY, risk.flags)

    def test_missing_source_blocks_mutation(self) -> None:
        risk = classify_source(Path("/no/such/source/here"), operation=Operation.APPLY)
        self.assertEqual(risk.severity, "block")
        self.assertIn(SOURCE_MISSING, risk.flags)

    def test_enforce_raises_on_block(self) -> None:
        with self.assertRaises(SourcePolicyError):
            validate_source_for_operation(Path(Path("/").anchor), operation=Operation.DELETE)

    def test_enforce_allows_normal_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            validate_source_for_operation(Path(tmpdir), operation=Operation.REMUX)

    def test_inspect_warns_instead_of_blocking_root(self) -> None:
        risk = classify_source(Path(Path("/").anchor), operation=Operation.INSPECT)
        self.assertEqual(risk.severity, "warn")

    def test_candidate_must_resolve_under_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Movies"
            source.mkdir()
            outside = root / "outside.mkv"
            outside.write_text("video", encoding="utf-8")
            with self.assertRaisesRegex(SourcePolicyError, "escapes source root"):
                validate_source_for_operation(
                    source,
                    operation=Operation.DELETE,
                    candidate_paths=[outside],
                )

    def test_approved_root_is_enforced_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            approved = root / "Approved"
            source = root / "Other"
            approved.mkdir()
            source.mkdir()
            with self.assertRaisesRegex(SourcePolicyError, "not under an approved root"):
                validate_source_for_operation(
                    source,
                    operation=Operation.APPLY,
                    approved_roots=ApprovedRoots.from_paths([approved]),
                )

    def test_shared_containment_and_overlap_helpers(self) -> None:
        self.assertTrue(path_is_under(Path("/srv/media/movies"), Path("/srv/media")))
        self.assertTrue(source_paths_overlap(Path("/srv/media"), Path("/srv/media/movies")))
        self.assertFalse(source_paths_overlap(Path("/srv/media"), Path("/srv/music")))


if __name__ == "__main__":
    unittest.main()
