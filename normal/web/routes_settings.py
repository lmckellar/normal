from __future__ import annotations

from typing import Any

from normal.movie_profile import (
    load_operator_preferences,
    operator_preferences_revision,
    save_operator_preferences,
)

from .http import RequestContext
from .state import CREDENTIAL_STORE

_FIELD_TO_ENV = {"omdb": "OMDB_KEY", "tmdb": "TMDB_KEY"}


def _settings_payload() -> dict[str, Any]:
    preferences = load_operator_preferences()
    return {
        "keys": CREDENTIAL_STORE.status(),
        "fun_mode": bool(preferences.get("fun_mode")),
        "operator_preferences": preferences,
        "operator_preferences_revision": operator_preferences_revision(preferences),
    }


def handle_settings_read(ctx: RequestContext, payload: dict[str, Any]) -> None:
    del payload
    ctx.respond_json(_settings_payload())


def handle_settings_keys_update(ctx: RequestContext, payload: dict[str, Any]) -> None:
    updates: dict[str, str | None] = {}
    for field, env_key in _FIELD_TO_ENV.items():
        if field not in payload:
            continue
        value = payload[field]
        if value is None or isinstance(value, str):
            updates[env_key] = value
    CREDENTIAL_STORE.set_keys(updates)
    ctx.respond_json(_settings_payload())


def handle_settings_preferences_update(ctx: RequestContext, payload: dict[str, Any]) -> None:
    preferences = load_operator_preferences()
    if "fun_mode" in payload:
        preferences["fun_mode"] = bool(payload["fun_mode"])
    save_operator_preferences(preferences)
    ctx.respond_json(_settings_payload())
