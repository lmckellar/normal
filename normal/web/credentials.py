from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

_SECRETS_FILENAME = "secrets.env"
_MANAGED_KEYS = ("OMDB_KEY", "TMDB_KEY")


def _data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "normal"


def secrets_file_path() -> Path:
    return _data_dir() / _SECRETS_FILENAME


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
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{env_key}={self._keys[env_key]}" for env_key in _MANAGED_KEYS if self._keys.get(env_key)]
        content = ("\n".join(lines) + "\n") if lines else ""
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
