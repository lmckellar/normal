from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.source_policy import (
    ApprovedRoots,
    DRIVE_DIRECTORY,
    Operation,
    REPARSE_POINT,
    SOURCE_MISSING,
    SourcePolicyError,
    classify_source,
    path_is_under,
    source_paths_overlap,
    validate_candidate_for_mutation,
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

    def test_reparse_point_flag_blocks_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            with patch(
                "normal.source_policy.is_blocked_reparse_point",
                return_value=True,
            ):
                risk = classify_source(source, operation=Operation.APPLY)

        self.assertEqual(risk.severity, "block")
        self.assertIn(REPARSE_POINT, risk.flags)

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

    def test_mutation_candidate_rejects_symlink_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Movies"
            source.mkdir()
            movie = source / "Movie.mkv"
            movie.write_text("video", encoding="utf-8")
            link = source / "Linked.mkv"
            link.symlink_to(movie)

            with self.assertRaisesRegex(SourcePolicyError, "symlink or reparse point"):
                validate_candidate_for_mutation(link, source)

    def test_mutation_candidate_accepts_source_path_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            real_root = root / "real"
            source = real_root / "Movies"
            source.mkdir(parents=True)
            movie = source / "Movie.mkv"
            movie.write_text("video", encoding="utf-8")
            alias = root / "alias"
            try:
                alias.symlink_to(real_root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")

            resolved = validate_candidate_for_mutation(
                alias / "Movies" / "Movie.mkv",
                alias / "Movies",
            )

            self.assertEqual(resolved, movie.resolve())

    def test_mutation_candidate_rechecks_approved_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "Movies"
            source.mkdir()
            movie = source / "Movie.mkv"
            movie.write_text("video", encoding="utf-8")

            with self.assertRaisesRegex(SourcePolicyError, "not under an approved root"):
                validate_candidate_for_mutation(
                    movie,
                    source,
                    ApprovedRoots.from_paths([root / "Other"]),
                )


if __name__ == "__main__":
    unittest.main()
