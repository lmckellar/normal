from __future__ import annotations

from dataclasses import dataclass
import functools
from importlib import resources
import json
import re
from typing import Any

from normal.movie_naming import cleanup_group_text


# Versioned seed corpus of known-bad release groups / uploaders. Loaded from the
# data file rather than inlined so the list (a dozen-plus names over time) stays
# editorial data, not Python. See docs/internal/weak-encode-badge-taxonomy.md.
DATA_RESOURCE = ("normal", "data", "moron_encoders.json")
DATA_VERSION = 1

# Punt always outranks warn when a filename carries more than one signal.
_TIER_PRECEDENCE = {"warn": 1, "punt": 2}

_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True, slots=True)
class MoronEncoderVerdict:
    name: str
    tier: str
    code: str
    severity: str
    category: str
    label: str
    note: str

    @property
    def summary(self) -> str:
        # Name leads, separated by an em dash, so the render layer can split the
        # encoder name back out for the short reason label and the badge.
        return f"{self.name} — {self.note}"


@functools.lru_cache(maxsize=1)
def _load_data() -> dict[str, Any]:
    package, *parts = DATA_RESOURCE
    raw = resources.files(package).joinpath(*parts).read_text(encoding="utf-8")
    payload = json.loads(raw)
    version = payload.get("version")
    if version != DATA_VERSION:
        raise ValueError(f"unsupported moron encoder data version: {version}")
    return payload


@functools.lru_cache(maxsize=1)
def _alias_index() -> dict[str, MoronEncoderVerdict]:
    payload = _load_data()
    tiers = payload["tiers"]
    index: dict[str, MoronEncoderVerdict] = {}
    for entry in payload["encoders"]:
        tier = tiers[entry["tier"]]
        verdict = MoronEncoderVerdict(
            name=entry["name"],
            tier=entry["tier"],
            code=tier["code"],
            severity=tier["severity"],
            category=tier["category"],
            label=tier["label"],
            note=entry["note"],
        )
        for alias in (*entry["aliases"], entry["name"]):
            key = cleanup_group_text(alias)
            if key:
                index.setdefault(key, verdict)
    return index


def lookup_moron_encoder(
    release_group: str | None, *, stem: str | None = None
) -> MoronEncoderVerdict | None:
    """Match a parsed release group (and, as a fallback, the raw filename stem) against
    the known-moron corpus. Bracket-tagged uploaders such as ``[YTS.MX]`` never reach the
    release-group slot, so the stem is tokenised on non-alphanumeric boundaries and each
    token is checked too. Returns the highest-severity match, or ``None``."""
    index = _alias_index()
    keys: list[str] = []
    if release_group:
        cleaned = cleanup_group_text(release_group)
        if cleaned:
            keys.append(cleaned)
    if stem:
        for token in _TOKEN_SPLIT.split(stem):
            cleaned = cleanup_group_text(token)
            if cleaned:
                keys.append(cleaned)
    matches = [index[key] for key in keys if key in index]
    if not matches:
        return None
    return max(matches, key=lambda verdict: _TIER_PRECEDENCE.get(verdict.tier, 0))
