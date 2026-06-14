from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from normal import paths

_SECRETS_FILENAME = "secrets.env"
_MANAGED_KEYS = ("OMDB_KEY", "TMDB_KEY")
_FORBIDDEN_VALUE_CHARS = ("\n", "\r", "\x00")


def _ensure_storable(value: str) -> None:
    if any(char in value for char in _FORBIDDEN_VALUE_CHARS):
        raise ValueError("key value may not contain newline or NUL characters")


def secrets_file_path() -> Path:
    return paths.data_dir() / _SECRETS_FILENAME


def _field_name(env_key: str) -> str:
    return env_key.removesuffix("_KEY").lower()


def _key_status(value: str | None, source: str | None) -> dict[str, Any]:
    if not value:
        return {"present": False, "last4": None, "source": None}
    return {"present": True, "last4": value[-4:], "source": source or "saved"}


class CredentialStore:
    """Process-wide store for plan-B remote enricher keys.

    Boot keys arrive via env (the launch contract merges the saved secrets file
    into the environment before launch). UI saves update the live values and
    re-persist the file, so a pasted key takes effect on the next request without
    a restart.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, str | None] = {key: None for key in _MANAGED_KEYS}
        self._source: dict[str, str] = {}

    def seed_from_boot(self, *, omdb_key: str | None, tmdb_key: str | None) -> None:
        boot = {"OMDB_KEY": omdb_key, "TMDB_KEY": tmdb_key}
        with self._lock:
            for env_key, value in boot.items():
                if value:
                    self._keys[env_key] = value
                    self._source[env_key] = "env"

    def get(self, env_key: str) -> str | None:
        with self._lock:
            return self._keys.get(env_key)

    def omdb_key(self) -> str | None:
        return self.get("OMDB_KEY")

    def tmdb_key(self) -> str | None:
        return self.get("TMDB_KEY")

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                _field_name(env_key): _key_status(self._keys.get(env_key), self._source.get(env_key))
                for env_key in _MANAGED_KEYS
            }

    def set_keys(self, updates: dict[str, str | None]) -> dict[str, Any]:
        with self._lock:
            for env_key in _MANAGED_KEYS:
                value = updates.get(env_key)
                if isinstance(value, str) and value.strip():
                    _ensure_storable(value.strip())
            for env_key in _MANAGED_KEYS:
                if env_key not in updates:
                    continue
                value = updates[env_key]
                if value is None:
                    continue
                value = value.strip()
                if value:
                    self._keys[env_key] = value
                    self._source[env_key] = "saved"
                else:
                    self._keys[env_key] = None
                    self._source.pop(env_key, None)
            self._persist_locked()
            return {
                _field_name(env_key): _key_status(self._keys.get(env_key), self._source.get(env_key))
                for env_key in _MANAGED_KEYS
            }

    def _persist_locked(self) -> None:
        path = secrets_file_path()
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(parent, 0o700)
        lines = [f"{env_key}={self._keys[env_key]}" for env_key in _MANAGED_KEYS if self._keys.get(env_key)]
        content = ("\n".join(lines) + "\n") if lines else ""
        fd, tmp_name = tempfile.mkstemp(dir=str(parent), prefix=f".{_SECRETS_FILENAME}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, path)
            if os.name == "posix":
                os.chmod(path, 0o600)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
