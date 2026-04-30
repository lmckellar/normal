from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from normal.models import utc_now_iso
from normal.movie_profile import DiagnosticFinding, detect_plex_diagnostics
from normal.movie_scan import probe_media_facts
from normal.quality_review import MediaFacts, classify_resolution


@dataclass(slots=True)
class MovieInspectReport:
    path: str
    generated_at: str
    facts: MediaFacts
    likely_causes: list[DiagnosticFinding] = field(default_factory=list)
    playback_gap_summary: str = ""
    remedy_plan: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def inspect_movie_file(path: Path, probe_media: Callable[[Path], MediaFacts] | None = None) -> MovieInspectReport:
    if probe_media is None:
        probe_media = probe_media_facts
    facts = probe_media(path)
    facts.resolution_bucket = facts.resolution_bucket or classify_resolution(facts.width, facts.height)
    findings = detect_plex_diagnostics(path, facts)
    return MovieInspectReport(
        path=str(path),
        generated_at=utc_now_iso(),
        facts=facts,
        likely_causes=findings,
        playback_gap_summary=build_playback_gap_summary(findings),
        remedy_plan=build_remedy_plan(findings),
    )


def build_playback_gap_summary(findings: list[DiagnosticFinding]) -> str:
    primary = findings[0]
    return (
        "VLC is tolerant of damaged timestamps, unusual stream layouts, and image-subtitle edge cases, "
        f"while Plex clients may stutter or pause when {primary.summary.lower()}"
    )


def build_remedy_plan(findings: list[DiagnosticFinding]) -> list[str]:
    steps: list[str] = []
    for finding in findings:
        if finding.remedy not in steps:
            steps.append(finding.remedy)
    if "Remux to MKV first before attempting a full transcode." not in steps:
        steps.insert(0, "Remux the file losslessly and retest in Plex before transcoding.")
    return steps
