from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_profile import scan_movie_profiles
from normal.movie_profile import DEFAULT_MOVIE_STANDARDS, build_title_trait_assessments
from normal.movie_title_traits import (
    TraitEvidence,
    all_evidence,
    bundled_evidence,
    load_store,
    lookup_evidence,
    migrate_legacy_store,
    resolve_claim,
    save_store,
    validate_corpus,
)
from normal.quality_review import MediaFacts


def evidence(
    direction: str,
    basis: str,
    reliability: str,
    *,
    evidence_id: str = "evidence",
    trait: str = "uhd",
) -> TraitEvidence:
    return TraitEvidence(
        evidence_id=evidence_id,
        title="Example",
        year=2000,
        trait=trait,
        direction=direction,
        basis=basis,
        reliability=reliability,
        source="test",
        reference="test://evidence",
    )


class TitleTraitConsensusTests(unittest.TestCase):
    def test_confirmed_positive_overrides_negative(self) -> None:
        self.assertEqual(
            resolve_claim(
                [
                    evidence("absent", "curated_research", "high", evidence_id="negative"),
                    evidence("present", "local_probe", "confirmed", evidence_id="positive"),
                ]
            ),
            ("present", "confirmed", "upgrade_available"),
        )

    def test_curated_negative_is_provisional(self) -> None:
        self.assertEqual(
            resolve_claim([evidence("absent", "curated_research", "high")]),
            ("absent", "high", "no_known_release"),
        )

    def test_soft_positive_is_likely_not_confirmed(self) -> None:
        self.assertEqual(
            resolve_claim([evidence("present", "imported_report", "plausible")]),
            ("present", "plausible", "likely_available"),
        )

    def test_soft_contradiction_is_contested(self) -> None:
        self.assertEqual(
            resolve_claim(
                [
                    evidence("present", "user_report", "plausible", evidence_id="present"),
                    evidence("absent", "imported_report", "plausible", evidence_id="absent"),
                ]
            ),
            ("unknown", "unknown", "contested"),
        )

    def test_empty_evidence_is_unverified(self) -> None:
        self.assertEqual(resolve_claim([]), ("unknown", "unknown", "unverified"))

    def test_hybrid_local_probe_does_not_confirm_the_claim(self) -> None:
        self.assertEqual(
            resolve_claim(
                [
                    evidence(
                        "present",
                        "local_probe",
                        "confirmed",
                        trait="hybrid",
                    )
                ]
            ),
            ("unknown", "unknown", "unverified"),
        )

    def test_hybrid_independent_confirmation_remains_actionable(self) -> None:
        self.assertEqual(
            resolve_claim(
                [
                    evidence(
                        "present",
                        "curated_research",
                        "confirmed",
                        trait="hybrid",
                    )
                ]
            ),
            ("present", "confirmed", "upgrade_available"),
        )


class TitleTraitStoreTests(unittest.TestCase):
    def test_bundled_corpus_is_valid_and_covers_all_traits(self) -> None:
        traits = {item.trait for item in bundled_evidence()}
        self.assertEqual(traits, {"immersive_audio", "uhd", "dolby_vision"})

    def test_validation_rejects_duplicate_ids_and_bad_reliability(self) -> None:
        raw = {
            "evidence_id": "duplicate",
            "title": "Example",
            "year": 2000,
            "trait": "uhd",
            "direction": "present",
            "basis": "curated_research",
            "reliability": "confirmed",
            "source": "test",
            "reference": "test://reference",
        }
        with self.assertRaisesRegex(ValueError, "duplicate evidence id"):
            validate_corpus({"version": 1, "evidence": [raw, raw]})
        with self.assertRaisesRegex(ValueError, "must be confirmed"):
            validate_corpus(
                {
                    "version": 1,
                    "evidence": [{**raw, "evidence_id": "bad", "reliability": "plausible"}],
                }
            )

    def test_migrates_legacy_records_and_keeps_tombstones_as_suppressions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy_path = Path(tmpdir) / "immersive-confirmations.json"
            legacy_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "records": {
                            "one": {
                                "title": "Amélie II",
                                "year": 2001,
                                "verdict": "available",
                                "source": "local_probe",
                                "recorded_at": "2026-01-01T00:00:00Z",
                            },
                            "two": {
                                "title": "Dune",
                                "year": 2021,
                                "verdict": "unknown",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            migrated = migrate_legacy_store(legacy_path)
            self.assertEqual(migrated["evidence"][0]["basis"], "local_probe")
            self.assertEqual(migrated["evidence"][0]["title"], "Amélie II")
            self.assertEqual(migrated["suppressions"][0]["title"], "Dune")

    def test_invalid_save_does_not_replace_existing_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "title-trait-evidence.json"
            original = {"version": 1, "evidence": [], "suppressions": []}
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ValueError):
                save_store(
                    {
                        "evidence": [
                            {
                                "evidence_id": "bad",
                                "title": "Bad",
                                "year": 2000,
                                "trait": "invalid",
                                "direction": "present",
                                "basis": "local_probe",
                                "reliability": "confirmed",
                                "source": "test",
                                "reference": "test",
                            }
                        ]
                    },
                    path,
                )
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_accent_and_numeral_variants_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "title-trait-evidence.json"
            legacy = Path(tmpdir) / "missing-legacy.json"
            save_store(
                {
                    "evidence": [
                        {
                            "evidence_id": "variant",
                            "title": "Amélie II",
                            "year": 2001,
                            "trait": "uhd",
                            "direction": "present",
                            "basis": "manual_verification",
                            "reliability": "confirmed",
                            "source": "test",
                            "reference": "test://variant",
                        }
                    ],
                    "suppressions": [],
                },
                path,
            )
            items, _ = all_evidence(path, legacy_path=legacy)
            matches = lookup_evidence(items, "Amelie 2", 2001, "uhd")
            self.assertEqual(resolve_claim(matches), ("present", "confirmed", "upgrade_available"))


class TitleTraitAggregationTests(unittest.TestCase):
    def test_open_matte_filename_claim_requires_the_copy_to_clear_the_selected_quality_floor(self) -> None:
        accepted = Path("Example (2000) 1080p Open Matte Hybrid.mkv")
        rejected = Path("Weak Example (2001) 1080p Open Matte Hybrid.mkv")
        rows, _ = build_title_trait_assessments(
            [
                (
                    accepted,
                    MediaFacts(
                        width=1920,
                        height=1080,
                        video_stream_count=1,
                        video_bitrate_kbps=5000,
                        audio_stream_count=1,
                        audio_codec="aac",
                        audio_channels=2,
                        audio_bitrate_kbps=320,
                    ),
                ),
                (
                    rejected,
                    MediaFacts(
                        width=1920,
                        height=1080,
                        video_stream_count=1,
                        video_bitrate_kbps=2000,
                        audio_stream_count=1,
                        audio_codec="aac",
                        audio_channels=2,
                        audio_bitrate_kbps=192,
                    ),
                ),
            ],
            evidence=[],
            standards=DEFAULT_MOVIE_STANDARDS,
        )

        by_key = {(row["title"], row["trait"]): row for row in rows}
        self.assertEqual(by_key[("Example", "open_matte")]["local_present_count"], 1)
        self.assertEqual(by_key[("Example", "open_matte")]["opportunity"], "already_covered")
        self.assertEqual(by_key[("Weak Example", "open_matte")]["local_present_count"], 0)
        self.assertEqual(by_key[("Weak Example", "open_matte")]["local_rejected_count"], 1)
        self.assertEqual(by_key[("Weak Example", "open_matte")]["opportunity"], "quality_review")

    def test_hybrid_filename_claim_requires_independent_title_corroboration(self) -> None:
        path = Path("Example (2000) 1080p Hybrid.mkv")
        facts = MediaFacts(
            width=1920,
            height=1080,
            video_stream_count=1,
            video_bitrate_kbps=5000,
            audio_stream_count=1,
            audio_codec="aac",
            audio_channels=2,
            audio_bitrate_kbps=320,
        )

        rows, _ = build_title_trait_assessments(
            [(path, facts)],
            evidence=[],
            standards=DEFAULT_MOVIE_STANDARDS,
        )
        uncorroborated = next(row for row in rows if row["trait"] == "hybrid")
        self.assertEqual(uncorroborated["capability"], "claim_unverified")
        self.assertEqual(uncorroborated["status"], "unverified")
        self.assertEqual(uncorroborated["opportunity"], "research_needed")
        self.assertEqual(uncorroborated["local_present_count"], 0)

        rows, _ = build_title_trait_assessments(
            [(path, facts)],
            evidence=[
                evidence(
                    "present",
                    "curated_research",
                    "confirmed",
                    trait="hybrid",
                )
            ],
            standards=DEFAULT_MOVIE_STANDARDS,
        )
        corroborated = next(row for row in rows if row["trait"] == "hybrid")
        self.assertEqual(corroborated["capability"], "present")
        self.assertEqual(corroborated["status"], "owned")
        self.assertEqual(corroborated["opportunity"], "already_covered")

    def test_scan_records_open_matte_but_not_hybrid_filename_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            trait_store = Path(tmpdir) / "title-trait-evidence.json"
            legacy_store = Path(tmpdir) / "missing-legacy.json"
            movie = source / "Example (2000) Open Matte Hybrid.mkv"
            source.mkdir()
            movie.write_bytes(b"video")

            with patch("normal.movie_profile.load_movie_standards", return_value=DEFAULT_MOVIE_STANDARDS):
                report = scan_movie_profiles(
                    source,
                    probe_media=lambda _path: MediaFacts(
                        width=1920,
                        height=1080,
                        video_stream_count=1,
                        video_bitrate_kbps=5000,
                        audio_stream_count=1,
                        audio_codec="aac",
                        audio_channels=2,
                        audio_bitrate_kbps=320,
                    ),
                    trait_store_path=trait_store,
                    legacy_trait_store_path=legacy_store,
                )

                self.assertEqual(
                    {item["trait"] for item in report.trait_observations},
                    {"open_matte"},
                )

    def test_same_scan_duplicate_records_evidence_and_marks_missing_copy_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "library"
            trait_store = Path(tmpdir) / "title-trait-evidence.json"
            legacy_store = Path(tmpdir) / "missing-legacy.json"
            carrying = source / "copy-a" / "Example (2000).mkv"
            missing = source / "copy-b" / "Example (2000).mkv"
            carrying.parent.mkdir(parents=True)
            missing.parent.mkdir(parents=True)
            carrying.write_bytes(b"a")
            missing.write_bytes(b"b")

            def probe(path: Path) -> MediaFacts:
                return MediaFacts(
                    width=1920,
                    height=1080,
                    video_stream_count=1,
                    audio_stream_count=1,
                    audio_immersive_extension="atmos" if path == carrying else None,
                )

            with patch("normal.movie_profile.load_movie_standards", return_value=DEFAULT_MOVIE_STANDARDS):
                report = scan_movie_profiles(
                    source,
                    probe_media=probe,
                    trait_store_path=trait_store,
                    legacy_trait_store_path=legacy_store,
                )
                aggregate = next(
                    row for row in report.trait_assessments
                    if row["trait"] == "immersive_audio"
                )
                self.assertEqual(aggregate["status"], "owned")
                self.assertEqual(aggregate["local_present_count"], 1)
                self.assertEqual(aggregate["local_copy_count"], 2)
                missing_item = next(item for item in report.movies if item.path == str(missing))
                self.assertTrue(
                    any(
                        finding.code == "immersive_audio_upgrade_available"
                        for finding in missing_item.profile.diagnostics
                    )
                )
                stored = load_store(trait_store, legacy_path=legacy_store)
                self.assertEqual(len(stored["evidence"]), 1)


if __name__ == "__main__":
    unittest.main()
