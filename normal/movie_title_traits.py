from __future__ import annotations

from dataclasses import asdict, dataclass
from importlib import resources
import json
from pathlib import Path
import tempfile
from typing import Any, Iterable

from normal import paths
from normal.models import utc_now_iso
from normal.movie_immersive_confirmations import load_confirmations
from normal.movie_naming import match_variant_keys, title_match_key


STORE_VERSION = 1
CORPUS_VERSION = 1
TRAITS = ("immersive_audio", "uhd", "dolby_vision", "open_matte", "hybrid")
DIRECTIONS = ("present", "absent")
BASES = (
    "local_probe",
    "curated_research",
    "manual_verification",
    "imported_report",
    "user_report",
)
RELIABILITIES = ("confirmed", "high", "plausible", "unknown")
HARD_POSITIVE_BASES = {"local_probe", "curated_research", "manual_verification"}
INDEPENDENT_HARD_POSITIVE_BASES = {"curated_research", "manual_verification"}
PROVISIONAL_NEGATIVE_BASES = {"curated_research", "manual_verification"}
CORPUS_RESOURCE = ("normal", "data", "title_trait_corpus.json")


@dataclass(frozen=True, slots=True)
class TraitEvidence:
    evidence_id: str
    title: str
    year: int
    trait: str
    direction: str
    basis: str
    reliability: str
    source: str
    reference: str
    observed_at: str | None = None
    reviewed_at: str | None = None


@dataclass(frozen=True, slots=True)
class TraitAssessment:
    title: str
    year: int
    trait: str
    capability: str
    claim_direction: str
    certainty: str
    release_status: str
    status: str
    opportunity: str
    evidence_count: int
    present_evidence_count: int
    absent_evidence_count: int
    local_copy_count: int = 0
    local_present_count: int = 0
    local_rejected_count: int = 0
    local_paths: tuple[str, ...] = ()


def default_store_path() -> Path:
    return paths.data_dir() / "title-trait-evidence.json"


def trait_key(title: str, year: int, trait: str) -> str:
    return f"{title_match_key(title)}|{int(year)}|{trait}"


def validate_evidence(raw: dict[str, Any]) -> TraitEvidence:
    required = ("evidence_id", "title", "year", "trait", "direction", "basis", "reliability", "source", "reference")
    missing = [key for key in required if raw.get(key) in (None, "")]
    if missing:
        raise ValueError(f"trait evidence missing fields: {', '.join(missing)}")
    evidence = TraitEvidence(
        evidence_id=str(raw["evidence_id"]).strip(),
        title=str(raw["title"]).strip(),
        year=int(raw["year"]),
        trait=str(raw["trait"]).strip(),
        direction=str(raw["direction"]).strip(),
        basis=str(raw["basis"]).strip(),
        reliability=str(raw["reliability"]).strip(),
        source=str(raw["source"]).strip(),
        reference=str(raw["reference"]).strip(),
        observed_at=str(raw["observed_at"]).strip() if raw.get("observed_at") else None,
        reviewed_at=str(raw["reviewed_at"]).strip() if raw.get("reviewed_at") else None,
    )
    if evidence.trait not in TRAITS:
        raise ValueError(f"unsupported trait: {evidence.trait}")
    if evidence.direction not in DIRECTIONS:
        raise ValueError(f"unsupported evidence direction: {evidence.direction}")
    if evidence.basis not in BASES:
        raise ValueError(f"unsupported evidence basis: {evidence.basis}")
    if evidence.reliability not in RELIABILITIES:
        raise ValueError(f"unsupported evidence reliability: {evidence.reliability}")
    if evidence.basis == "local_probe" and (
        evidence.direction != "present" or evidence.reliability != "confirmed"
    ):
        raise ValueError("local_probe evidence must be confirmed present")
    if evidence.basis == "curated_research":
        expected = "confirmed" if evidence.direction == "present" else "high"
        if evidence.reliability != expected:
            raise ValueError(f"curated_research {evidence.direction} evidence must be {expected}")
    if evidence.basis == "manual_verification":
        expected = "confirmed" if evidence.direction == "present" else "high"
        if evidence.reliability != expected:
            raise ValueError(f"manual_verification {evidence.direction} evidence must be {expected}")
    if evidence.basis in {"imported_report", "user_report"} and evidence.reliability not in {
        "plausible",
        "unknown",
    }:
        raise ValueError("soft report evidence cannot be confirmed or high reliability")
    return evidence


def validate_corpus(payload: dict[str, Any]) -> list[TraitEvidence]:
    if payload.get("version") != CORPUS_VERSION:
        raise ValueError(f"unsupported title-trait corpus version: {payload.get('version')}")
    records = payload.get("evidence")
    if not isinstance(records, list):
        raise ValueError("title-trait corpus evidence must be a list")
    validated: list[TraitEvidence] = []
    seen: set[str] = set()
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("title-trait corpus entries must be objects")
        evidence = validate_evidence(raw)
        if evidence.evidence_id in seen:
            raise ValueError(f"duplicate evidence id: {evidence.evidence_id}")
        seen.add(evidence.evidence_id)
        validated.append(evidence)
    return validated


def bundled_evidence() -> list[TraitEvidence]:
    package, *parts = CORPUS_RESOURCE
    payload = json.loads(resources.files(package).joinpath(*parts).read_text(encoding="utf-8"))
    evidence = validate_corpus(payload)
    evidence.extend(_legacy_seed_evidence())
    ids: set[str] = set()
    for item in evidence:
        if item.evidence_id in ids:
            raise ValueError(f"duplicate bundled evidence id: {item.evidence_id}")
        ids.add(item.evidence_id)
    return evidence


def _legacy_seed_evidence() -> list[TraitEvidence]:
    raw = json.loads(
        resources.files("normal").joinpath("data", "immersive_seeds.json").read_text(encoding="utf-8")
    )
    evidence: list[TraitEvidence] = []
    for list_name, direction, reliability in (
        ("available", "present", "confirmed"),
        ("not_available", "absent", "high"),
    ):
        info = raw["lists"][list_name]
        for index, entry in enumerate(info["entries"], start=1):
            evidence.append(
                validate_evidence(
                    {
                        "evidence_id": f"legacy-immersive-seed-{list_name}-{index}",
                        "title": entry["title"],
                        "year": entry["year"],
                        "trait": "immersive_audio",
                        "direction": direction,
                        "basis": "curated_research",
                        "reliability": reliability,
                        "source": info["source"],
                        "reference": info["reference"],
                        "reviewed_at": info["asserted_on"],
                    }
                )
            )
    return evidence


def load_store(state_path: Path | None = None, legacy_path: Path | None = None) -> dict[str, Any]:
    path = state_path or default_store_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") != STORE_VERSION:
                raise ValueError("unsupported title-trait evidence store version")
            records = payload.get("evidence")
            suppressions = payload.get("suppressions")
            if not isinstance(records, list) or not isinstance(suppressions, list):
                raise ValueError("malformed title-trait evidence store")
            validated = [asdict(validate_evidence(raw)) for raw in records if isinstance(raw, dict)]
            return {"version": STORE_VERSION, "evidence": validated, "suppressions": suppressions}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {"version": STORE_VERSION, "evidence": [], "suppressions": []}
    migrated = migrate_legacy_store(legacy_path=legacy_path)
    if migrated["evidence"] or migrated["suppressions"]:
        save_store(migrated, path)
    return migrated


def save_store(payload: dict[str, Any], state_path: Path | None = None) -> None:
    path = state_path or default_store_path()
    validated = [asdict(validate_evidence(raw)) for raw in payload.get("evidence", [])]
    suppressions = [item for item in payload.get("suppressions", []) if isinstance(item, dict)]
    data = json.dumps(
        {"version": STORE_VERSION, "evidence": validated, "suppressions": suppressions},
        indent=2,
        sort_keys=True,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def migrate_legacy_store(legacy_path: Path | None = None) -> dict[str, Any]:
    legacy = load_confirmations(legacy_path)
    migrated: list[dict[str, Any]] = []
    suppressions: list[dict[str, Any]] = []
    for index, record in enumerate(legacy["records"].values(), start=1):
        title = str(record.get("title") or "").strip()
        year = record.get("year")
        if not title or year is None:
            continue
        verdict = record.get("verdict")
        if verdict == "unknown":
            suppressions.append(
                {
                    "title": title,
                    "year": int(year),
                    "trait": "immersive_audio",
                    "recorded_at": record.get("recorded_at"),
                }
            )
            continue
        direction = "present" if verdict == "available" else "absent"
        basis = "local_probe" if record.get("source") == "local_probe" and direction == "present" else "manual_verification"
        migrated.append(
            asdict(
                validate_evidence(
                    {
                        "evidence_id": f"legacy-immersive-record-{index}-{title_match_key(title)}-{year}",
                        "title": title,
                        "year": int(year),
                        "trait": "immersive_audio",
                        "direction": direction,
                        "basis": basis,
                        "reliability": "confirmed" if direction == "present" else "high",
                        "source": str(record.get("source") or "legacy_immersive_store"),
                        "reference": str(record.get("reference") or "immersive-confirmations.json"),
                        "observed_at": record.get("recorded_at"),
                    }
                )
            )
        )
    return {"version": STORE_VERSION, "evidence": migrated, "suppressions": suppressions}


def all_evidence(
    state_path: Path | None = None,
    *,
    legacy_path: Path | None = None,
) -> tuple[list[TraitEvidence], set[str]]:
    local = load_store(state_path, legacy_path=legacy_path)
    evidence = bundled_evidence()
    evidence.extend(validate_evidence(raw) for raw in local["evidence"])
    suppressed = {
        trait_key(item["title"], int(item["year"]), item["trait"])
        for item in local["suppressions"]
        if isinstance(item, dict)
        and item.get("title")
        and item.get("year") is not None
        and item.get("trait") in TRAITS
    }
    return evidence, suppressed


def lookup_evidence(
    evidence: Iterable[TraitEvidence],
    title: str,
    year: int,
    trait: str,
) -> list[TraitEvidence]:
    keys = {f"{variant}|{int(year)}|{trait}" for variant in match_variant_keys(title)}
    return [item for item in evidence if trait_key(item.title, item.year, item.trait) in keys]


def resolve_claim(evidence: Iterable[TraitEvidence]) -> tuple[str, str, str]:
    items = list(evidence)
    hard_positive = any(
        item.direction == "present"
        and item.reliability == "confirmed"
        and item.basis in (
            INDEPENDENT_HARD_POSITIVE_BASES
            if item.trait == "hybrid"
            else HARD_POSITIVE_BASES
        )
        for item in items
    )
    if hard_positive:
        return "present", "confirmed", "upgrade_available"
    provisional_negative = any(
        item.direction == "absent"
        and item.reliability == "high"
        and item.basis in PROVISIONAL_NEGATIVE_BASES
        for item in items
    )
    soft_directions = {
        item.direction
        for item in items
        if item.basis in {"imported_report", "user_report"}
    }
    if len(soft_directions) > 1:
        return "unknown", "unknown", "contested"
    if provisional_negative and "present" in soft_directions:
        return "unknown", "unknown", "contested"
    if provisional_negative:
        return "absent", "high", "no_known_release"
    if soft_directions == {"present"}:
        return "present", "plausible", "likely_available"
    if soft_directions == {"absent"}:
        return "absent", "plausible", "unverified"
    return "unknown", "unknown", "unverified"


def has_independent_confirmed_positive(evidence: Iterable[TraitEvidence]) -> bool:
    return any(
        item.direction == "present"
        and item.reliability == "confirmed"
        and item.basis in INDEPENDENT_HARD_POSITIVE_BASES
        for item in evidence
    )


def assess_trait(
    title: str,
    year: int,
    trait: str,
    *,
    capability: str = "unknown",
    evidence: Iterable[TraitEvidence] = (),
    local_paths: Iterable[str] = (),
    local_present_count: int = 0,
    local_rejected_count: int = 0,
) -> TraitAssessment:
    items = list(evidence)
    claim_direction, certainty, claim_status = resolve_claim(items)
    paths = tuple(sorted(set(local_paths), key=str.casefold))
    status = "owned" if capability == "present" else claim_status
    if paths and local_present_count == len(paths):
        opportunity = "already_covered"
    elif local_present_count:
        opportunity = "partial_coverage"
    elif local_rejected_count:
        opportunity = "quality_review"
    elif claim_status in {"upgrade_available", "likely_available"}:
        opportunity = "upgrade_found"
    elif claim_status == "no_known_release":
        opportunity = "no_known_upgrade"
    elif claim_status == "contested":
        opportunity = "conflicting_reports"
    else:
        opportunity = "research_needed"
    return TraitAssessment(
        title=title,
        year=int(year),
        trait=trait,
        capability=capability,
        claim_direction=claim_direction,
        certainty=certainty,
        release_status=claim_status,
        status=status,
        opportunity=opportunity,
        evidence_count=len(items),
        present_evidence_count=sum(item.direction == "present" for item in items),
        absent_evidence_count=sum(item.direction == "absent" for item in items),
        local_copy_count=len(paths),
        local_present_count=local_present_count,
        local_rejected_count=local_rejected_count,
        local_paths=paths,
    )


def record_local_observations(
    observations: Iterable[tuple[str, int, str, str]],
    *,
    state_path: Path | None = None,
    legacy_path: Path | None = None,
) -> list[dict[str, Any]]:
    payload = load_store(state_path, legacy_path=legacy_path)
    existing = {
        (raw["title"], int(raw["year"]), raw["trait"], raw["basis"], raw["direction"])
        for raw in payload["evidence"]
    }
    added: list[dict[str, Any]] = []
    now = utc_now_iso()
    for title, year, trait, reference in observations:
        if not str(title).strip() or trait not in TRAITS:
            continue
        identity = (str(title), int(year), trait, "local_probe", "present")
        if identity in existing:
            continue
        record = asdict(
            validate_evidence(
                {
                    "evidence_id": f"local-{trait}-{title_match_key(title)}-{int(year)}",
                    "title": title,
                    "year": int(year),
                    "trait": trait,
                    "direction": "present",
                    "basis": "local_probe",
                    "reliability": "confirmed",
                    "source": "local_probe",
                    "reference": reference,
                    "observed_at": now,
                }
            )
        )
        payload["evidence"].append(record)
        existing.add(identity)
        added.append(record)
    if added:
        save_store(payload, state_path)
    return added
