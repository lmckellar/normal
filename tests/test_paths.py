import os
import unittest
from pathlib import Path
from unittest import mock

from normal import paths
from normal.audit import (
    default_audit_path,
    default_replacement_queue_path,
    default_subtitle_history_path,
)
from normal.movie_immersive_confirmations import default_store_path as immersive_store_path
from normal.movie_profile import MOVIE_STANDARDS_PATH, OPERATOR_PREFERENCES_PATH
from normal.movie_replacement_queue import default_queue_path
from normal.movie_subtitle_history import default_history_path
from normal.movie_title_traits import default_store_path as trait_store_path
from normal.probe_cache import ProbeCache
from normal.web.credentials import secrets_file_path
from normal.web.routes_core import library_roots_path


class DataDirTests(unittest.TestCase):
    def test_defaults_to_legacy_location_without_xdg(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_DATA_HOME", None)
            self.assertEqual(paths.data_dir(), Path.home() / ".local" / "share" / "normal")

    def test_honors_xdg_data_home(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/srv/state"}):
            self.assertEqual(paths.data_dir(), Path("/srv/state") / "normal")

    def test_runtime_state_files_relocate_together_under_xdg(self) -> None:
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/srv/state"}):
            root = Path("/srv/state") / "normal"
            for resolved in (
                default_audit_path(),
                default_replacement_queue_path(),
                default_subtitle_history_path(),
                default_queue_path(),
                default_history_path(),
                immersive_store_path(),
                trait_store_path(),
                secrets_file_path(),
                library_roots_path(),
            ):
                self.assertEqual(resolved.parent, root)

    def test_import_time_constants_sit_under_data_dir(self) -> None:
        self.assertEqual(MOVIE_STANDARDS_PATH, paths.data_dir() / "movie-standards.json")
        self.assertEqual(OPERATOR_PREFERENCES_PATH, paths.data_dir() / "operator-preferences.json")
        self.assertEqual(ProbeCache._PATH, paths.data_dir() / "probe-cache.json")


if __name__ == "__main__":
    unittest.main()
