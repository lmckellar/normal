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
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import normal.web.server as server
import normal.movie_immersive_confirmations as immersive
import normal.movie_moron_encoders as moron

template = server.read_web_asset_text("normalize_lab.html")
assert template.strip(), "normalize_lab.html shipped empty"
for _route, (asset_name, _mime) in server.WEB_STATIC_ASSETS.items():
    assert server.read_web_asset_text(asset_name).strip(), asset_name + " missing/empty"

# Bundled data/*.json package-data must ship too (immersive seed lists).
assert immersive.SEED_TITLES, "immersive seed data missing from wheel"
assert moron.lookup_moron_encoder("YIFY"), "moron encoder seed data missing from wheel"

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]

omdb_key = "wheel-smoke-omdb-secret"
tmdb_key = "wheel-smoke-tmdb-secret"
env = os.environ.copy()
env["OMDB_KEY"] = omdb_key
env["TMDB_KEY"] = tmdb_key
process = subprocess.Popen(
    [sys.executable, "-m", "normal", "web", "--host", "127.0.0.1", "--port", str(port)],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env,
)
base_url = "http://127.0.0.1:" + str(port)

def request(path, *, data=None, token=None):
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["X-Normal-Token"] = token
    return urllib.request.urlopen(
        urllib.request.Request(base_url + path, data=data, headers=headers),
        timeout=2,
    )

try:
    deadline = time.monotonic() + 10
    while True:
        try:
            root_response = request("/")
            break
        except (OSError, urllib.error.URLError):
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError("web server exited early\\nstdout:\\n" + stdout + "\\nstderr:\\n" + stderr)
            if time.monotonic() >= deadline:
                raise AssertionError("timed out waiting for installed web server")
            time.sleep(0.1)

    assert root_response.status == 200
    html = root_response.read().decode("utf-8")
    for header in server.SECURITY_HEADERS:
        assert root_response.headers.get(header), header + " missing from /"
    assert omdb_key not in html, "raw OMDB key leaked into bootstrap"
    assert tmdb_key not in html, "raw TMDB key leaked into bootstrap"

    bootstrap_match = re.search(
        r'<script type="application/json" id="normal-boot">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert bootstrap_match, "bootstrap JSON missing"
    bootstrap = json.loads(bootstrap_match.group(1))
    assert bootstrap["omdbAvailable"] is True
    assert bootstrap["tmdbAvailable"] is True
    token = bootstrap["token"]
    assert token

    asset_urls = re.findall(r'(?:href|src)="(/assets/[^"]+\\?v=[0-9a-f]{12})"', html)
    assert len(asset_urls) == len(server.WEB_STATIC_ASSETS), asset_urls
    for asset_url in asset_urls:
        with request(asset_url) as asset_response:
            assert asset_response.status == 200
            assert asset_response.read(), asset_url + " served empty"
            for header in server.SECURITY_HEADERS:
                assert asset_response.headers.get(header), header + " missing from " + asset_url

    body = b"{}"
    try:
        request("/api/settings/preferences", data=body)
        raise AssertionError("mutation POST without token unexpectedly succeeded")
    except urllib.error.HTTPError as exc:
        assert exc.code == 403, exc.code

    with request("/api/settings/preferences", data=body, token=token) as mutation_response:
        assert mutation_response.status == 200
        assert "operator_preferences" in json.load(mutation_response)
finally:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

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
        if importlib.util.find_spec("build.__main__") is None:
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
