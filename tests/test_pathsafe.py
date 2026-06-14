from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from normal.pathsafe import contained_resolve


class ContainedResolveTests(unittest.TestCase):
    def test_path_inside_source_is_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            target = source / "movie.mkv"
            target.write_text("x", encoding="utf-8")
            resolved, contained = contained_resolve(str(target), source)
            self.assertTrue(contained)
            self.assertEqual(resolved, target.resolve())

    def test_parent_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "library"
            source.mkdir()
            resolved, contained = contained_resolve(str(source / ".." / "outside.mkv"), source)
            self.assertFalse(contained)
            self.assertEqual(resolved, (Path(tmp) / "outside.mkv").resolve())

    def test_absolute_outside_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "library"
            source.mkdir()
            _, contained = contained_resolve("/tmp/outside.mkv", source)
            self.assertFalse(contained)

    def test_symlink_escaping_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "library"
            source.mkdir()
            outside = Path(tmp) / "outside.mkv"
            outside.write_text("x", encoding="utf-8")
            link = source / "link.mkv"
            link.symlink_to(outside)
            resolved, contained = contained_resolve(str(link), source)
            self.assertFalse(contained)
            self.assertEqual(resolved, outside.resolve())

    def test_symlink_inside_source_is_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            real = source / "real.mkv"
            real.write_text("x", encoding="utf-8")
            link = source / "link.mkv"
            link.symlink_to(real)
            _, contained = contained_resolve(str(link), source)
            self.assertTrue(contained)


if __name__ == "__main__":
    unittest.main()
