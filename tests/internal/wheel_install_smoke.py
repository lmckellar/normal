from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that must never be copied into the isolated build tree: build
# staging (the source of the stale-`web.py` contamination this test guards
# against), the dev venv, VCS metadata, and bytecode/egg caches.
_COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "build", "dist", "*.egg-info", "__pycache__", "*.pyc"
)

# Runs inside the freshly installed wheel's interpreter, from a cwd *outside* the
# repo, so import resolution and asset loading exercise the installed package
# only — never the source checkout. Touches the real asset load path
# (`read_web_asset_text`) so a wheel that ships `normal.web` but drops the
# `web_assets` package-data still fails.
_VERIFY_SCRIPT = """
import normal.web.server as server
import normal.movie_immersive_confirmations as immersive

html = server.read_web_asset_text("normalize_lab.html")
assert html.strip(), "normalize_lab.html shipped empty"
for _route, (asset_name, _mime) in server.WEB_STATIC_ASSETS.items():
    assert server.read_web_asset_text(asset_name).strip(), asset_name + " missing/empty"

# Bundled data/*.json package-data must ship too (immersive seed lists).
assert immersive.SEED_TITLES, "immersive seed data missing from wheel"
print("WHEEL_SMOKE_OK")
"""


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


class WheelInstallSmokeTests(unittest.TestCase):
    """Build a wheel, install it into a throwaway venv, and confirm the package
    boots and serves its bundled assets from *outside* the source checkout.

    Out of the default suite because it shells out to a real build + venv + pip
    install (seconds to minutes). Opt in explicitly:

        NORMAL_TEST_WHEEL=1 python3 -m unittest tests.internal.wheel_install_smoke
    """

    def test_wheel_ships_web_package_and_assets(self) -> None:
        if os.environ.get("NORMAL_TEST_WHEEL", "").strip() not in {"1", "true", "yes"}:
            self.skipTest("set NORMAL_TEST_WHEEL=1 to run the wheel install smoke test")
        if importlib.util.find_spec("build") is None:
            self.skipTest("the 'build' package is required (pip install build)")

        with tempfile.TemporaryDirectory(prefix="normal-wheel-smoke-") as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "src"
            dist = tmp_path / "dist"
            venv_dir = tmp_path / "venv"

            # Isolated copy so the build never depends on or mutates the working
            # tree, and stale build/ staging cannot leak into the wheel.
            shutil.copytree(REPO_ROOT, src, ignore=_COPY_IGNORE)

            self._run([sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)], cwd=src)
            wheels = list(dist.glob("*.whl"))
            self.assertEqual(len(wheels), 1, f"expected one wheel, got {wheels}")

            self._run([sys.executable, "-m", "venv", str(venv_dir)], cwd=tmp_path)
            venv_py = _venv_python(venv_dir)
            self._run([str(venv_py), "-m", "pip", "install", "--quiet", str(wheels[0])], cwd=tmp_path)

            # cwd=tmp_path keeps `normal` off the path as a source dir.
            result = self._run([str(venv_py), "-c", _VERIFY_SCRIPT], cwd=tmp_path)
            self.assertIn("WHEEL_SMOKE_OK", result.stdout)

    def _run(self, cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
        if result.returncode != 0:
            self.fail(
                f"command failed ({result.returncode}): {' '.join(cmd)}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result
