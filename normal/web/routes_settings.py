from __future__ import annotations

from typing import Any

from .http import RequestContext
from .state import CREDENTIAL_STORE

_FIELD_TO_ENV = {"omdb": "OMDB_KEY", "tmdb": "TMDB_KEY"}


def handle_settings_read(ctx: RequestContext, payload: dict[str, Any]) -> None:
    del payload
    ctx.respond_json({"keys": CREDENTIAL_STORE.status()})


def handle_settings_keys_update(ctx: RequestContext, payload: dict[str, Any]) -> None:
    updates: dict[str, str | None] = {}
    for field, env_key in _FIELD_TO_ENV.items():
        if field not in payload:
            continue
        value = payload[field]
        if value is None or isinstance(value, str):
            updates[env_key] = value
    ctx.respond_json({"keys": CREDENTIAL_STORE.set_keys(updates)})
