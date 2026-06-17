from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from normal.movie_profile import (
    DEFAULT_MOVIE_STANDARDS,
    build_delete_mode_definition,
    build_movie_profile_definitions,
    build_policy_definitions,
    build_replacement_candidate_definition,
    build_histogram_payload,
    build_histogram_payload_from_items,
    build_movie_profile_item,
    choose_best_english_subtitle_stream,
    classify_profile_label,
    classify_quality_stance,
    classify_standard_label,
    detect_audio_language_selection_risks,
    detect_immersive_audio_candidate,
    detect_plex_diagnostics,
    evaluate_lopsided_encode,
    is_audio_packaging_owned_movie,
    looks_like_absolute_numbering,
    total_risk_score,
    evaluate_movie_standards,
    load_movie_standards,
    library_policy_revision,
    MovieStandardsConflictError,
    movie_standards_revision,
    operator_preferences_revision,
    normalize_weak_encode_floor,
    OPERATOR_PREFERENCES_PATH,
    path_matches_normalized_shape,
    scan_movie_profiles,
    update_policy_definition,
    update_movie_profile_definition,
    is_replacement_candidate_quality,
)
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts, build_audio_summary


class MovieProfileTests(unittest.TestCase):
    def test_build_audio_summary_formats_common_home_theater_variants(self) -> None:
        self.assertEqual(build_audio_summary("aac", 2)[-1], "AAC 2.0")
        self.assertEqual(build_audio_summary("ac3", 6)[-1], "Dolby Digital 5.1")
        self.assertEqual(build_audio_summary("eac3", 6, "Dolby Digital Plus + Dolby Atmos")[-1], "Dolby Digital Plus 5.1 Atmos")
        self.assertEqual(build_audio_summary("truehd", 8, "Dolby Atmos")[-1], "Dolby TrueHD 7.1 Atmos")
        self.assertEqual(build_audio_summary("dts", 6, "DTS-HD Master Audio")[-1], "DTS-HD MA 5.1")
        self.assertEqual(build_audio_summary("pcm_s16le", 2)[-1], "PCM 2.0")

    def test_build_audio_summary_ignores_atmos_title_on_non_carrier_codec(self) -> None:
        family, _variant, _layout, immersive, summary = build_audio_summary(
            "opus",
            8,
            None,
            "Dolby Atmos/TrueHD Audio / 5631 kbps / 7.1-Atmos / 48 kHz / 24-bit",
        )
        self.assertEqual(family, "opus")
        self.assertIsNone(immersive)
        self.assertEqual(summary, "Opus 7.1")

    def test_classify_profile_label_keeps_legacy_bitrate_label_for_compatibility(self) -> None:
        label = classify_profile_label(
            MediaFacts(
                runtime_seconds=90 * 60,
                file_size_bytes=int(4.5 * 1024 * 1024 * 1024),
                width=1920,
                height=1080,
                video_bitrate_kbps=5000,
                audio_bitrate_kbps=192,
            )
        )

        self.assertEqual(label, "minimum_acceptable_1080p")

    def test_path_matches_normalized_shape_accepts_concise_movie_names(self) -> None:
        self.assertTrue(path_matches_normalized_shape(Path("/movies/The Matrix (1999)/The Matrix (1999).mkv")))

    def test_path_matches_normalized_shape_rejects_verbose_tokenized_movie_names(self) -> None:
        self.assertFalse(
            path_matches_normalized_shape(
                Path("/movies/The Matrix (1999) [1080p BluRay x264 GRP]/The Matrix (1999) [1080p BluRay x264 GRP].mkv")
            )
        )

    def test_path_matches_normalized_shape_accepts_legacy_concise_punctuation_light_names(self) -> None:
        self.assertTrue(
            path_matches_normalized_shape(Path("/movies/K 19 The Widowmaker (2002)/K 19 The Widowmaker (2002).mkv"))
        )

    def test_reference_profile_ignores_folder_hygiene_for_quality_classification(self) -> None:
        facts = MediaFacts(
            width=1920,
            height=1080,
            video_bitrate_kbps=18000,
            audio_codec="truehd",
            audio_channels=6,
            audio_bitrate_kbps=4000,
            audio_streams=[AudioStreamFacts(index=1, codec="truehd", bitrate_kbps=4000, channels=6, language="eng", is_default=True)],
            default_audio_streams=1,
            default_audio_stream_index=1,
        )

        item = build_movie_profile_item(
            Path("/movies"),
            Path("/movies/The Matrix (1999) [1080p BluRay x264 GRP]/The Matrix (1999) [1080p BluRay x264 GRP].mkv"),
            facts,
            standards=DEFAULT_MOVIE_STANDARDS,
        )

        self.assertEqual(item.profile.quality_label, "reference")
        self.assertEqual(item.profile.label, "reference")
        self.assertEqual([result["domain"] for result in item.profile.domain_results], ["video_minimum", "audio_minimum"])

    def test_classify_profile_label_uses_kind_floor_for_compressed_tiers(self) -> None:
        compressed_1080p = classify_profile_label(
            MediaFacts(width=1920, height=1080, video_bitrate_kbps=6000)
        )
        compressed_4k = classify_profile_label(
            MediaFacts(width=3840, height=2160, video_bitrate_kbps=6000)
        )

        self.assertEqual(compressed_1080p, "compressed_1080p")
        self.assertEqual(compressed_4k, "compressed_4k")

    def test_classify_profile_label_names_high_bitrate_1080p_as_uhd(self) -> None:
        label = classify_profile_label(
            MediaFacts(width=1920, height=1080, video_bitrate_kbps=16000)
        )

        self.assertEqual(label, "1080p_uhd")

    def test_classify_profile_label_names_weak_resolution_tiers(self) -> None:
        weak_1080p = classify_profile_label(
            MediaFacts(width=1916, height=952, video_bitrate_kbps=1962)
        )
        weak_4k = classify_profile_label(
            MediaFacts(width=3840, height=2160, video_bitrate_kbps=5500)
        )

        self.assertEqual(weak_1080p, "weak_1080p")
        self.assertEqual(weak_4k, "weak_4k")

    def test_detect_plex_diagnostics_flags_image_subtitles_and_multiple_defaults(self) -> None:
        findings = detect_plex_diagnostics(
            "Show - s01e01.mkv",
            MediaFacts(
                container="matroska",
                subtitle_codecs=["hdmv_pgs_subtitle"],
                default_audio_streams=2,
                default_subtitle_streams=1,
            )
        )

        codes = {finding.code for finding in findings}
        self.assertIn("image_subtitle_transcode_risk", codes)
        self.assertIn("multiple_default_streams", codes)

    def test_evaluate_movie_standards_only_reports_core_video_and_audio_domains(self) -> None:
        results = evaluate_movie_standards(
            Path("Movie (2001)/Movie (2001).mkv"),
            MediaFacts(
                container="matroska",
                width=1920,
                height=1080,
                video_bitrate_kbps=6000,
                audio_codec="ac3",
                audio_bitrate_kbps=640,
                audio_channels=6,
                audio_streams=[AudioStreamFacts(index=1, codec="ac3", bitrate_kbps=640, channels=6, language="eng", is_default=True)],
                subtitle_streams=[
                    SubtitleStreamFacts(index=2, codec="subrip", language="eng", title="English Forced", is_default=False, is_forced=True),
                ],
                default_audio_streams=1,
                default_audio_stream_index=1,
            ),
            {},
        )

        self.assertEqual([result["domain"] for result in results], ["video_minimum", "audio_minimum"])

    def test_choose_best_english_subtitle_stream_prefers_current_default(self) -> None:
        streams = [
            SubtitleStreamFacts(index=2, codec="subrip", language="eng", title="English Forced", is_default=False, is_forced=True),
            SubtitleStreamFacts(index=3, codec="subrip", language="eng", title="English", is_default=True, is_forced=False),
        ]

        chosen = choose_best_english_subtitle_stream(streams)

        self.assertIs(chosen, streams[1])

    def test_classify_standard_label_keeps_failed_core_standard_in_review_without_cutoff_match(self) -> None:
        label = classify_standard_label(
            [
                {"domain": "video_minimum", "status": "fail", "code": "video_below_minimum", "summary": "", "confidence": "high"},
                {"domain": "audio_minimum", "status": "pass", "code": "audio_meets_minimum", "summary": "", "confidence": "high"},
            ],
            {"replacement_candidate_rules": {"quality_profile_floor": "standard_definition"}},
        )

        self.assertEqual(label, "needs_review")

    def test_classify_standard_label_marks_cutoff_match_as_replacement_candidate(self) -> None:
        label = classify_standard_label([], {}, weak_candidate=True)

        self.assertEqual(label, "replacement_candidate")

    def test_replacement_candidate_quality_cutoff_is_inclusive(self) -> None:
        standards = {"replacement_candidate_rules": {"quality_profile_floor": "library_grade"}}

        self.assertTrue(is_replacement_candidate_quality("standard_definition", standards))
        self.assertTrue(is_replacement_candidate_quality("compact_grade", standards))
        self.assertTrue(is_replacement_candidate_quality("library_grade", standards))
        self.assertFalse(is_replacement_candidate_quality("collector_grade", standards))
        self.assertFalse(is_replacement_candidate_quality("reference", standards))

    def test_normalize_weak_encode_floor_clamps_to_safe_options(self) -> None:
        standards = {"replacement_candidate_rules": {"quality_profile_floor": "reference"}}

        self.assertEqual(normalize_weak_encode_floor("collector_grade", standards), "standard_definition")
        self.assertEqual(normalize_weak_encode_floor("compact_grade", standards), "compact_grade")
        self.assertEqual(normalize_weak_encode_floor("standard_definition", standards), "standard_definition")

    def test_build_movie_profile_item_routes_good_english_packaging_issue_out_of_weak_candidate(self) -> None:
        facts = MediaFacts(
            width=1920,
            height=1080,
            video_bitrate_kbps=15000,
            audio_codec="ac3",
            audio_channels=2,
            audio_bitrate_kbps=192,
            audio_streams=[
                AudioStreamFacts(index=1, codec="ac3", bitrate_kbps=192, channels=2, language="ukr", is_default=True),
                AudioStreamFacts(index=2, codec="truehd", bitrate_kbps=4000, channels=8, language="eng", is_default=False),
            ],
            default_audio_streams=1,
            default_audio_stream_index=1,
        )

        item = build_movie_profile_item(
            Path("/movies"),
            Path("/movies/American Psycho (2000)/American Psycho (2000).mkv"),
            facts,
            standards=DEFAULT_MOVIE_STANDARDS,
        )

        self.assertFalse(item.profile.weak_candidate)
        self.assertEqual(item.profile.label, "meets_minimum")
        self.assertIn("default_non_english_audio", [finding.code for finding in item.profile.diagnostics])

    def _foreign_default_facts(self) -> MediaFacts:
        return MediaFacts(
            audio_streams=[
                AudioStreamFacts(index=1, codec="dts", channels=6, bitrate_kbps=1500, language="jpn", is_default=True),
                AudioStreamFacts(index=2, codec="ac3", channels=6, bitrate_kbps=640, language="eng", is_default=False),
            ],
        )

    def test_detect_audio_language_relabels_foreign_original_and_protects_replacement(self) -> None:
        findings = detect_audio_language_selection_risks(
            self._foreign_default_facts(),
            title="Seven Samurai",
            year=1954,
            resolve_language=lambda title, year: "japanese",
        )

        self.assertEqual([finding.code for finding in findings], ["foreign_original_audio_ok"])
        self.assertEqual(findings[0].severity, "info")
        self.assertTrue(is_audio_packaging_owned_movie(findings))
        self.assertEqual(total_risk_score(findings), 0)

    def test_detect_audio_language_fails_open_to_finding_when_not_confirmed_foreign(self) -> None:
        facts = self._foreign_default_facts()
        for resolver in (None, lambda title, year: None, lambda title, year: "english"):
            findings = detect_audio_language_selection_risks(
                facts, title="Some Title", year=2000, resolve_language=resolver
            )
            codes = [finding.code for finding in findings]
            self.assertNotIn("foreign_original_audio_ok", codes)
            self.assertIn(
                codes[0], {"default_non_english_audio", "default_non_english_audio_with_weak_english"}
            )

    def test_build_movie_profile_item_threads_resolver_to_relabel_foreign_original(self) -> None:
        facts = MediaFacts(
            width=1920,
            height=1080,
            video_bitrate_kbps=15000,
            audio_codec="dts",
            audio_channels=6,
            audio_bitrate_kbps=1500,
            audio_streams=[
                AudioStreamFacts(index=1, codec="dts", channels=6, bitrate_kbps=1500, language="jpn", is_default=True),
                AudioStreamFacts(index=2, codec="ac3", channels=6, bitrate_kbps=640, language="eng", is_default=False),
            ],
            default_audio_streams=1,
            default_audio_stream_index=1,
        )

        item = build_movie_profile_item(
            Path("/movies"),
            Path("/movies/Seven Samurai (1954)/Seven Samurai (1954).mkv"),
            facts,
            standards=DEFAULT_MOVIE_STANDARDS,
            resolve_language=lambda title, year: "japanese",
        )

        codes = [finding.code for finding in item.profile.diagnostics]
        self.assertIn("foreign_original_audio_ok", codes)
        self.assertNotIn("default_non_english_audio", codes)
        self.assertFalse(item.profile.weak_candidate)

    def test_build_movie_profile_definitions_exposes_dashboard_owned_controls(self) -> None:
        definitions = build_movie_profile_definitions()
        compact_definition = next(definition for definition in definitions if definition["label"] == "compact_grade")
        video_1080p_options = compact_definition["fields"][2]["options"]
        video_2160p_options = compact_definition["fields"][3]["options"]

        self.assertEqual(
            [definition["label"] for definition in definitions],
            ["standard_definition", "compact_grade", "library_grade", "collector_grade", "reference"],
        )
        self.assertEqual(definitions[0]["fields"][0]["key"], "display_name")
        self.assertEqual(definitions[0]["fields"][1]["key"], "summary")
        self.assertEqual(len(definitions[0]["fields"]), 2)
        self.assertIn("audio_channels_mono_cutoff", [field["key"] for field in compact_definition["fields"]])
        self.assertEqual(definitions[-1]["fields"][2]["key"], "video_1080p_kbps")
        self.assertEqual(
            video_1080p_options,
            [
                {"value": 4500, "label": "4,500 kbps — compact encode"},
                {"value": 5500, "label": "5,500 kbps — library grade"},
                {"value": 7500, "label": "7,500 kbps — strong library"},
                {"value": 10000, "label": "10,000 kbps — collector grade"},
                {"value": 12500, "label": "12,500 kbps — strong collector"},
                {"value": 15000, "label": "15,000 kbps — reference grade"},
                {"value": 20000, "label": "20,000 kbps — near-lossless"},
                {"value": 25000, "label": "25,000 kbps — remux tier"},
            ],
        )
        self.assertNotIn({"value": 1200, "label": "1,200 kbps — SD minimum"}, video_1080p_options)
        self.assertNotIn({"value": 1800, "label": "1,800 kbps — 720p minimum"}, video_1080p_options)
        self.assertNotIn({"value": 3000, "label": "3,000 kbps — compact encode"}, video_1080p_options)
        self.assertEqual(
            video_2160p_options,
            [
                {"value": 10000, "label": "10,000 kbps — compact encode"},
                {"value": 15000, "label": "15,000 kbps — library grade"},
                {"value": 20000, "label": "20,000 kbps — strong library"},
                {"value": 25000, "label": "25,000 kbps — reference grade"},
                {"value": 30000, "label": "30,000 kbps — near-lossless"},
                {"value": 40000, "label": "40,000 kbps — remux tier"},
                {"value": 50000, "label": "50,000 kbps — full remux"},
            ],
        )
        self.assertNotIn({"value": 5000, "label": "5,000 kbps — compact 4K"}, video_2160p_options)
        self.assertNotIn({"value": 8000, "label": "8,000 kbps — efficient encode"}, video_2160p_options)
        self.assertNotIn({"value": 12000, "label": "12,000 kbps — solid 4K"}, video_2160p_options)
        for definition in definitions:
            self.assertNotIn("audio_codecs", [field["key"] for field in definition["fields"]])
            self.assertNotIn("codecs:", definition["rule_summary"])

    def test_build_replacement_candidate_definition_exposes_quality_profile_cutoff(self) -> None:
        definition = build_replacement_candidate_definition(
            {
                "replacement_candidate_rules": {"quality_profile_floor": "library_grade"},
                "quality_stances": {
                    "standard_definition": {"display_name": "Weak Encodes & Standard Definition"},
                    "compact_grade": {"display_name": "Compact Grade"},
                    "library_grade": {"display_name": "Library Grade"},
                    "collector_grade": {"display_name": "Collector Grade"},
                    "reference": {"display_name": "Reference"},
                },
            }
        )

        self.assertEqual(definition["label"], "replacement_candidate")
        self.assertEqual(definition["fields"][0]["key"], "quality_profile_floor")
        self.assertEqual(definition["fields"][0]["value"], "library_grade")
        self.assertIn("Library Grade and lower", definition["rule_summary"])

    def test_update_movie_profile_definition_strips_removed_quality_stance_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "movie_standards.json"
            path.write_text(
                json.dumps(
                    {
                        "quality_stances": {
                            "reference": {
                                "audio_codecs": ["legacy"],
                                "require_audio_language_hygiene": True,
                                "require_subtitle_setup": True,
                                "require_folder_hygiene": True,
                                "require_lossless_audio": True,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", path):
                standards = update_movie_profile_definition(
                    "reference",
                    {
                        "display_name": "Reference",
                        "summary": "Lossless audio and near-transparent video.",
                        "video_1080p_kbps": "18000",
                        "video_2160p_kbps": "26000",
                        "audio_channels": "6",
                        "audio_bitrate_kbps": "512",
                        "audio_codecs": "opus",
                    },
                )

            reference = standards["quality_stances"]["reference"]
            self.assertEqual(reference["video_custom"]["1080p"], 18000)
            self.assertEqual(reference["video_custom"]["2160p"], 26000)
            self.assertEqual(reference["audio_codecs"], ["legacy"])
            self.assertNotIn("require_lossless_audio", reference)
            self.assertNotIn("require_folder_hygiene", reference)
            saved = path.read_text(encoding="utf-8")
            self.assertIn('"video_custom"', saved)
            self.assertNotIn("require_lossless_audio", saved)
            self.assertNotIn("require_folder_hygiene", saved)

    def test_quality_stance_matching_ignores_profile_audio_codec_allowlists(self) -> None:
        standards = {
            "quality_stances": {
                "compact_grade": {
                    "video_custom": {"1080p": 4500, "2160p": 12000},
                    "audio_channels": 2,
                    "audio_bitrate_kbps": 320,
                    "audio_channels_mono_cutoff": 1970,
                },
                "collector_grade": {
                    "video_custom": {"1080p": 8000, "2160p": 18000},
                    "audio_channels": 6,
                    "audio_bitrate_kbps": 384,
                    "audio_codecs": ["ac3"],
                    "require_audio_language_hygiene": True,
                    "require_subtitle_setup": True,
                },
                "reference": {
                    "video_custom": {"1080p": 16000, "2160p": 24000},
                    "audio_channels": 6,
                    "audio_bitrate_kbps": 640,
                    "audio_codecs": ["truehd"],
                    "require_lossless_audio": True,
                },
            }
        }

        label = classify_quality_stance(
            Path("Movie (2001)/Movie (2001).mkv"),
            MediaFacts(
                width=1920,
                height=1080,
                video_bitrate_kbps=9000,
                audio_codec="opus",
                audio_channels=6,
                audio_bitrate_kbps=640,
            ),
            [],
            standards,
        )

        self.assertEqual(label, "collector_grade")

    def test_old_mono_audio_can_meet_compact_grade_with_mono_cutoff(self) -> None:
        standards = {
            "quality_stances": {
                "compact_grade": {
                    "video_custom": {"1080p": 4500, "2160p": 12000},
                    "audio_channels": 2,
                    "audio_channels_mono_cutoff": 1970,
                    "audio_bitrate_kbps": 320,
                }
            }
        }

        label = classify_quality_stance(
            Path("Movie (1954)/Movie (1954).mkv"),
            MediaFacts(
                width=1920,
                height=1080,
                video_bitrate_kbps=5000,
                audio_codec="aac",
                audio_channels=1,
                audio_bitrate_kbps=192,
            ),
            [],
            standards,
        )

        self.assertEqual(label, "compact_grade")

    def test_recent_mono_audio_still_misses_compact_grade_when_cutoff_does_not_apply(self) -> None:
        standards = {
            "quality_stances": {
                "compact_grade": {
                    "video_custom": {"1080p": 4500, "2160p": 12000},
                    "audio_channels": 2,
                    "audio_channels_mono_cutoff": 1970,
                    "audio_bitrate_kbps": 320,
                }
            }
        }

        label = classify_quality_stance(
            Path("Movie (1984)/Movie (1984).mkv"),
            MediaFacts(
                width=1920,
                height=1080,
                video_bitrate_kbps=5000,
                audio_codec="aac",
                audio_channels=1,
                audio_bitrate_kbps=192,
            ),
            [],
            standards,
        )

        self.assertEqual(label, "standard_definition")

    def test_build_movie_profile_item_does_not_emit_weak_audio_failure_for_exempt_legacy_surround(self) -> None:
        standards = {
            "audio": {
                "minimum_channels": 6,
                "minimum_bitrate_kbps": 384,
                "minimum_codecs": ["dts", "ac3", "eac3", "dtshd", "truehd", "flac", "pcm"],
                "reference_codecs": ["dtshd", "truehd", "flac", "pcm"],
            },
            "replacement_candidate_rules": {"quality_profile_floor": "compact_grade"},
            "quality_stances": {
                "compact_grade": {
                    "video_custom": {"1080p": 4500, "2160p": 12000},
                    "audio_channels": 2,
                    "audio_bitrate_kbps": 320,
                },
                "library_grade": {
                    "video_custom": {"1080p": 5500, "2160p": 15000},
                    "audio_channels": 6,
                    "audio_bitrate_kbps": 448,
                    "audio_channels_vintage_cutoff": 1999,
                },
            },
        }

        item = build_movie_profile_item(
            Path("/movies"),
            Path("/movies/Ran (1985)/Ran (1985).mkv"),
            MediaFacts(
                width=1920,
                height=1080,
                video_bitrate_kbps=9000,
                audio_codec="dts",
                audio_channels=4,
                audio_bitrate_kbps=512,
            ),
            standards=standards,
        )

        self.assertEqual(item.profile.quality_label, "library_grade")
        self.assertEqual(item.profile.label, "meets_minimum")
        self.assertFalse(item.profile.weak_candidate)
        codes = {diag.code for diag in item.profile.diagnostics}
        self.assertNotIn("audio_channels_below_minimum", codes)
        self.assertNotIn("audio_bitrate_below_minimum", codes)

    def test_build_movie_profile_item_emits_weak_audio_failure_when_floor_itself_is_missed(self) -> None:
        standards = {
            "replacement_candidate_rules": {"quality_profile_floor": "compact_grade"},
            "quality_stances": {
                "compact_grade": {
                    "video_custom": {"1080p": 4500, "2160p": 12000},
                    "audio_channels": 2,
                    "audio_bitrate_kbps": 320,
                },
            },
        }

        item = build_movie_profile_item(
            Path("/movies"),
            Path("/movies/Movie (1984)/Movie (1984).mkv"),
            MediaFacts(
                width=1920,
                height=1080,
                video_bitrate_kbps=5000,
                audio_codec="aac",
                audio_channels=1,
                audio_bitrate_kbps=192,
            ),
            standards=standards,
        )

        self.assertEqual(item.profile.quality_label, "standard_definition")
        self.assertTrue(item.profile.weak_candidate)
        codes = {diag.code for diag in item.profile.diagnostics}
        self.assertIn("audio_channels_below_minimum", codes)

    def test_legacy_quality_stance_levers_no_longer_gate_reference_profile(self) -> None:
        standards = {
            "quality_stances": {
                "reference": {
                    "video_custom": {"1080p": 16000, "2160p": 24000},
                    "audio_channels": 6,
                    "audio_bitrate_kbps": 640,
                    "audio_codecs": ["opus"],
                    "require_audio_language_hygiene": True,
                    "require_subtitle_setup": True,
                    "require_folder_hygiene": True,
                    "require_lossless_audio": True,
                }
            }
        }

        reference_label = classify_quality_stance(
            Path("Movie (2001)/Movie (2001).mkv"),
            MediaFacts(
                width=1920,
                height=1080,
                video_bitrate_kbps=18000,
                audio_codec="opus",
                audio_channels=6,
                audio_bitrate_kbps=640,
            ),
            [],
            standards,
        )

        self.assertEqual(reference_label, "reference")

    def test_update_movie_profile_definition_persists_replacement_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", path):
                standards = update_movie_profile_definition(
                    "replacement_candidate",
                    {"quality_profile_floor": "compact_grade"},
                )

            self.assertEqual(standards["replacement_candidate_rules"]["quality_profile_floor"], "compact_grade")
            self.assertIn('"replacement_candidate_rules"', path.read_text(encoding="utf-8"))

    def test_update_movie_profile_definition_rejects_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", path):
                stale_revision = movie_standards_revision(load_movie_standards())
                path.write_text(
                    json.dumps(
                        {
                            "quality_stances": {
                                "library_grade": {
                                    "video_custom": {"1080p": 6000, "2160p": 12000},
                                }
                            }
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )

                with self.assertRaises(MovieStandardsConflictError):
                    update_movie_profile_definition(
                        "library_grade",
                        {"display_name": "Library Grade", "video_1080p_kbps": "8000"},
                        expected_revision=stale_revision,
                    )

    def test_policy_definitions_extend_quality_controls_with_library_and_operator_sections(self) -> None:
        definitions = build_policy_definitions(
            standards={},
            preferences={"default_source": "", "delete_mode": "recycle_all"},
        )

        labels = [definition["label"] for definition in definitions]
        self.assertNotIn("replacement_candidate", labels)
        self.assertIn("default_source", labels)
        self.assertIn("library_defaults", labels)
        self.assertIn("language_subtitle_defaults", labels)
        self.assertIn("delete_mode", labels)
        default_source = next(definition for definition in definitions if definition["label"] == "default_source")
        self.assertEqual(default_source["scope"], "operator_preferences")
        self.assertEqual(default_source["fields"][0]["value"], "")
        library_defaults = next(definition for definition in definitions if definition["label"] == "library_defaults")
        self.assertEqual(library_defaults["fields"][0]["key"], "canonical_list_provider")
        self.assertEqual(library_defaults["fields"][0]["value"], "imdb")
        self.assertEqual(library_defaults["fields"][1]["key"], "quality_profile_floor")
        self.assertEqual(library_defaults["fields"][3]["key"], "warning_gate_safety_level")
        self.assertEqual(library_defaults["fields"][3]["value"], "safe")
        language_defaults = next(definition for definition in definitions if definition["label"] == "language_subtitle_defaults")
        self.assertEqual(language_defaults["fields"][0]["key"], "primary_language")
        self.assertEqual(language_defaults["fields"][1]["key"], "english_audio_subtitles")
        self.assertEqual(language_defaults["fields"][1]["value"], "forced_english")
        self.assertEqual(
            [option["value"] for option in language_defaults["fields"][1]["options"]],
            ["forced_english", "english", "primary_language", "off"],
        )
        self.assertEqual(
            [option["value"] for option in language_defaults["fields"][2]["options"]],
            ["forced_english", "english", "off"],
        )
        delete_mode = next(definition for definition in definitions if definition["label"] == "delete_mode")
        self.assertEqual(delete_mode["scope"], "operator_preferences")
        self.assertEqual(delete_mode["fields"][0]["value"], "recycle_all")

    def test_update_policy_definition_persists_library_defaults_and_weak_floor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", policy_path):
                policy, preferences = update_policy_definition(
                    "library_defaults",
                    {
                        "canonical_list_provider": "imdb",
                        "quality_profile_floor": "compact_grade",
                        "junk_delete_confidence_floor": "review",
                        "warning_gate_safety_level": "yolo",
                    },
                    expected_policy_revision=library_policy_revision(load_movie_standards()),
                )
                saved = policy_path.read_text(encoding="utf-8")

        self.assertEqual(policy["canonical_list_provider"], "imdb")
        self.assertEqual(policy["replacement_candidate_rules"]["quality_profile_floor"], "compact_grade")
        self.assertEqual(policy["junk_rules"]["delete_confidence_floor"], "review")
        self.assertEqual(policy["warning_gate_safety_level"], "yolo")
        self.assertEqual(preferences["delete_mode"], "recycle_all")
        self.assertIn('"replacement_candidate_rules"', saved)
        self.assertIn('"canonical_list_provider": "imdb"', saved)
        self.assertIn('"warning_gate_safety_level": "yolo"', saved)

    def test_update_policy_definition_persists_language_and_subtitle_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", policy_path):
                policy, _preferences = update_policy_definition(
                    "language_subtitle_defaults",
                    {
                        "primary_language": "english",
                        "english_audio_subtitles": "forced_english",
                        "foreign_audio_subtitles": "off",
                    },
                    expected_policy_revision=library_policy_revision(load_movie_standards()),
                )
                saved = policy_path.read_text(encoding="utf-8")

        self.assertEqual(policy["primary_language"], "english")
        self.assertEqual(policy["subtitle_preferences"]["english_audio_subtitles"], "forced_english")
        self.assertEqual(policy["subtitle_preferences"]["foreign_audio_subtitles"], "off")
        self.assertIn('"english_audio_subtitles": "forced_english"', saved)
        self.assertIn('"foreign_audio_subtitles": "off"', saved)

    def test_update_policy_definition_persists_lopsided_encode_with_clamps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", policy_path):
                policy, _preferences = update_policy_definition(
                    "lopsided_encode",
                    {
                        "audio_kbps_per_channel": 200,
                        "audio_efficient_kbps_per_channel": 999,
                        "starved_ratio": 0.05,
                        "min_spread": 99,
                    },
                    expected_policy_revision=library_policy_revision(load_movie_standards()),
                )
                saved = policy_path.read_text(encoding="utf-8")

        block = policy["lopsided_encode"]
        self.assertEqual(block["audio_kbps_per_channel"], 160.0)
        self.assertEqual(block["audio_efficient_kbps_per_channel"], 160.0)
        self.assertEqual(block["starved_ratio"], 0.2)
        self.assertEqual(block["min_spread"], 5.0)
        self.assertIn('"audio_kbps_per_channel": 160', saved)

    def test_update_policy_definition_lopsided_encode_round_trips_and_caps_efficient(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", policy_path):
                policy, _preferences = update_policy_definition(
                    "lopsided_encode",
                    {
                        "audio_kbps_per_channel": 96,
                        "audio_efficient_kbps_per_channel": 120,
                        "starved_ratio": 0.45,
                        "min_spread": 3.0,
                    },
                    expected_policy_revision=library_policy_revision(load_movie_standards()),
                )

        block = policy["lopsided_encode"]
        self.assertEqual(block["audio_kbps_per_channel"], 96.0)
        self.assertEqual(block["audio_efficient_kbps_per_channel"], 96.0)
        self.assertEqual(block["starved_ratio"], 0.45)
        self.assertEqual(block["min_spread"], 3.0)

    def test_update_policy_definition_lopsided_encode_rejects_stale_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "movie_standards.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", policy_path):
                with self.assertRaises(MovieStandardsConflictError):
                    update_policy_definition(
                        "lopsided_encode",
                        {"audio_efficient_kbps_per_channel": 90},
                        expected_policy_revision="stale-revision",
                    )

    def test_update_policy_definition_persists_operator_preferences_with_revision_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "movie_standards.json"
            preferences_path = Path(tmpdir) / "operator-preferences.json"
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", policy_path):
                with patch("normal.movie_profile.OPERATOR_PREFERENCES_PATH", preferences_path):
                    stale_revision = operator_preferences_revision()
                    preferences_path.write_text(json.dumps({"delete_mode": "hard_delete_all"}) + "\n", encoding="utf-8")
                    with self.assertRaises(MovieStandardsConflictError):
                        update_policy_definition(
                            "delete_mode",
                            {"delete_mode": "recycle_all"},
                            expected_preferences_revision=stale_revision,
                        )
                    policy, preferences = update_policy_definition(
                        "delete_mode",
                        {"delete_mode": "hybrid_media_to_bin_junk_hard_delete"},
                        expected_preferences_revision=operator_preferences_revision(),
                    )
                    saved = preferences_path.read_text(encoding="utf-8")

        self.assertEqual(preferences["delete_mode"], "hybrid_media_to_bin_junk_hard_delete")
        self.assertEqual(policy["junk_rules"]["delete_confidence_floor"], "high")
        self.assertIn('"delete_mode": "hybrid_media_to_bin_junk_hard_delete"', saved)

    def test_update_policy_definition_persists_default_source_operator_preference(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            preferences_path = Path(tmpdir) / "operator-preferences.json"
            with patch("normal.movie_profile.OPERATOR_PREFERENCES_PATH", preferences_path):
                policy, preferences = update_policy_definition(
                    "default_source",
                    {"default_source": "~/Movies"},
                    expected_preferences_revision=operator_preferences_revision(),
                )
                saved = preferences_path.read_text(encoding="utf-8")

        self.assertEqual(preferences["default_source"], "~/Movies")
        self.assertEqual(policy["canonical_list_provider"], "imdb")
        self.assertIn('"default_source": "~/Movies"', saved)

    def test_legacy_standards_file_loads_with_policy_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "movie_standards.json"
            path.write_text(
                json.dumps(
                    {
                        "replacement_candidate_rules": {"quality_profile_floor": "compact_grade"},
                        "quality_stances": {"reference": {"require_lossless_audio": True}},
                    }
                ),
                encoding="utf-8",
            )
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", path):
                policy = load_movie_standards()

        self.assertEqual(policy["replacement_candidate_rules"]["quality_profile_floor"], "compact_grade")
        self.assertEqual(policy["canonical_list_provider"], "imdb")
        self.assertEqual(policy["warning_gate_safety_level"], "safe")
        self.assertEqual(policy["primary_language"], "english")
        self.assertEqual(policy["subtitle_preferences"]["english_audio_subtitles"], "forced_english")
        self.assertEqual(policy["subtitle_preferences"]["foreign_audio_subtitles"], "forced_english")
        self.assertEqual(policy["junk_rules"]["delete_confidence_floor"], "high")
        self.assertNotIn("require_lossless_audio", policy["quality_stances"]["reference"])

    def test_legacy_subtitle_mode_is_removed_when_loading_standards(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "movie_standards.json"
            path.write_text(
                json.dumps(
                    {
                        "subtitle_preferences": {
                            "mode": "conservative",
                            "english_audio_subtitles": "english",
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", path):
                policy = load_movie_standards()

        self.assertNotIn("mode", policy["subtitle_preferences"])
        self.assertEqual(policy["subtitle_preferences"]["english_audio_subtitles"], "english")
        self.assertEqual(policy["subtitle_preferences"]["foreign_audio_subtitles"], "forced_english")

    def test_unknown_canonical_list_provider_normalizes_to_imdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "movie_standards.json"
            path.write_text(json.dumps({"canonical_list_provider": "bogus"}) + "\n", encoding="utf-8")
            with patch("normal.movie_profile.MOVIE_STANDARDS_PATH", path):
                policy = load_movie_standards()

        self.assertEqual(policy["canonical_list_provider"], "imdb")

    def test_detect_plex_diagnostics_flags_dts_and_anime_visibility_risks(self) -> None:
        findings = detect_plex_diagnostics(
            "Berserk 01.mkv",
            MediaFacts(
                container="matroska",
                audio_codecs=["dts"],
                audio_stream_count=3,
                subtitle_codecs=["ass"],
                attachment_stream_count=5,
            ),
        )

        codes = {finding.code for finding in findings}
        self.assertIn("dts_no_compat_track", codes)
        self.assertIn("anime_subtitle_attachment_risk", codes)
        self.assertIn("anime_absolute_numbering_risk", codes)
        self.assertIn("attachment_heavy_visibility_risk", codes)

    def test_detect_plex_diagnostics_flags_default_non_english_audio_with_weak_english(self) -> None:
        findings = detect_plex_diagnostics(
            "Movie.mkv",
            MediaFacts(
                container="matroska",
                audio_stream_count=2,
                default_audio_streams=1,
                audio_streams=[
                    AudioStreamFacts(index=1, codec="ac3", bitrate_kbps=640, channels=6, language="ita", is_default=True),
                    AudioStreamFacts(index=2, codec="aac", bitrate_kbps=128, channels=2, language="eng", is_default=False),
                ],
            ),
        )

        codes = {finding.code for finding in findings}
        self.assertIn("default_non_english_audio_with_weak_english", codes)

    def test_detect_plex_diagnostics_flags_default_non_english_audio_even_when_english_is_not_weaker(self) -> None:
        findings = detect_plex_diagnostics(
            "Movie.mkv",
            MediaFacts(
                container="matroska",
                audio_stream_count=2,
                default_audio_streams=1,
                audio_streams=[
                    AudioStreamFacts(index=1, codec="ac3", bitrate_kbps=640, channels=6, language="ita", is_default=True),
                    AudioStreamFacts(index=2, codec="ac3", bitrate_kbps=640, channels=6, language="eng", is_default=False),
                ],
            ),
        )

        codes = {finding.code for finding in findings}
        self.assertIn("default_non_english_audio", codes)

    def test_looks_like_absolute_numbering_accepts_plain_anime_episode_names(self) -> None:
        self.assertTrue(looks_like_absolute_numbering("Berserk 01.mkv"))
        self.assertFalse(looks_like_absolute_numbering("Show.S01E01.mkv"))

    def test_scan_movie_profiles_assigns_profile_and_percentile(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "First.1999.1080p.mkv"
            second = source / "Second.1999.1080p.mkv"
            first.write_text("video", encoding="utf-8")
            second.write_text("video", encoding="utf-8")

            fake_facts = {
                first: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=3_000 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    video_bitrate_kbps=3500,
                    audio_bitrate_kbps=128,
                ),
                second: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=25_000 * 1024 * 1024,
                    width=3840,
                    height=2160,
                    video_bitrate_kbps=46000,
                    audio_bitrate_kbps=4000,
                ),
            }

            report = scan_movie_profiles(source, probe_media=lambda path: fake_facts[path])

            self.assertEqual(len(report.movies), 2)
            first_item = next(item for item in report.movies if item.path == str(first))
            second_item = next(item for item in report.movies if item.path == str(second))
            self.assertEqual(first_item.profile.label, "replacement_candidate")
            self.assertEqual(second_item.profile.label, "replacement_candidate")
            self.assertEqual(first_item.profile.quality_label, "standard_definition")
            self.assertTrue(second_item.profile.weak_candidate)
            self.assertTrue(first_item.profile.weak_candidate)
            self.assertEqual(first_item.profile.percentile, 100.0)
            self.assertIn("playback_risk", first_item.profile.risk_counts)

    def test_scan_movie_profiles_emits_streamed_progress_without_fake_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "First.1999.1080p.mkv"
            second = source / "Second.1999.1080p.mkv"
            first.write_text("video", encoding="utf-8")
            second.write_text("video", encoding="utf-8")
            events = []

            scan_movie_profiles(
                source,
                probe_media=lambda _: MediaFacts(width=1920, height=1080, video_bitrate_kbps=3500),
                progress_callback=events.append,
            )

            self.assertEqual(events[0].status, "starting")
            self.assertEqual(events[0].processed, 0)
            self.assertEqual(events[0].total, 0)
            self.assertEqual(events[1].processed, 1)
            self.assertEqual(events[1].total, 0)
            self.assertEqual(events[-1].status, "complete")
            self.assertEqual(events[-1].processed, 2)
            self.assertEqual(events[-1].total, 2)

    def test_build_histogram_payload_summarizes_bitrates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            movie = source / "Only.1999.1080p.mkv"
            movie.write_text("video", encoding="utf-8")
            report = scan_movie_profiles(
                source,
                probe_media=lambda _: MediaFacts(
                    runtime_seconds=7200,
                    file_size_bytes=3_000 * 1024 * 1024,
                    width=1920,
                    height=1080,
                    video_bitrate_kbps=3500,
                    audio_bitrate_kbps=128,
                ),
            )

            payload = build_histogram_payload(report)

            self.assertEqual(payload["movie_count"], 1)
            self.assertEqual(payload["profile_counts"]["replacement_candidate"], 1)
            self.assertEqual(payload["quality_profile_counts"]["standard_definition"], 1)
            self.assertEqual(sum(payload["quality_profile_counts"].values()), payload["movie_count"])
            self.assertEqual(payload["video_bitrate_kbps"]["median"], 3500.0)
            self.assertIn("risk_counts", payload)

    def test_build_histogram_payload_from_items_uses_payload_dicts(self) -> None:
        payload = build_histogram_payload_from_items(
            "/movies",
            "2026-05-12T00:00:00Z",
            [
                {
                    "runtime_minutes": 100,
                    "facts": {
                        "video_bitrate_kbps": 7000,
                        "audio_bitrate_kbps": 640,
                        "file_size_bytes": 1_000,
                        "width": 1920,
                        "height": 800,
                        "resolution_bucket": "1080p",
                        "audio_channels": 6,
                    },
                    "profile": {
                        "label": "meets_minimum",
                        "quality_label": "library_grade",
                        "risk_counts": {"playback_risk": 1},
                    },
                },
                {
                    "runtime_minutes": 90,
                    "facts": {
                        "video_bitrate_kbps": 30000,
                        "audio_bitrate_kbps": 4000,
                        "file_size_bytes": 2_000,
                        "width": 3840,
                        "height": 2160,
                        "resolution_bucket": "2160p",
                        "audio_channels": 8,
                        "audio_immersive_extension": "atmos",
                    },
                    "profile": {
                        "label": "reference",
                        "quality_label": "reference",
                        "risk_counts": {},
                    },
                },
            ],
        )

        self.assertEqual(payload["movie_count"], 2)
        self.assertEqual(payload["total_runtime_minutes"], 190)
        self.assertEqual(payload["total_size_bytes"], 3_000)
        self.assertEqual(payload["video_bitrate_kbps"]["mean"], 18500.0)
        self.assertEqual(payload["profile_counts"]["reference"], 1)
        self.assertEqual(payload["resolution_breakdown_counts"]["1080p_letterbox"], 1)
        self.assertEqual(payload["resolution_breakdown_counts"]["2160p_letterbox"], 1)
        self.assertEqual(payload["surround_sound_breakdown_counts"]["five_one_surround"], 1)
        self.assertEqual(payload["surround_sound_breakdown_counts"]["seven_one_atmos"], 1)
        self.assertEqual(payload["risk_counts"]["playback_risk"], 1)

    def test_scan_movie_profiles_can_cancel_between_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir)
            first = source / "First.1999.1080p.mkv"
            second = source / "Second.1999.1080p.mkv"
            first.write_text("video", encoding="utf-8")
            second.write_text("video", encoding="utf-8")
            calls = 0

            def probe(_: Path) -> MediaFacts:
                nonlocal calls
                calls += 1
                return MediaFacts(width=1920, height=1080, video_bitrate_kbps=3500)

            report = scan_movie_profiles(source, probe_media=probe, should_cancel=lambda: calls >= 1)

            self.assertEqual(calls, 1)
            self.assertEqual(len(report.movies), 1)
            self.assertEqual(report.warnings[0].code, "movie_profile_cancelled")


class ImmersiveAudioCandidateTests(unittest.TestCase):
    STANDARDS = {"immersive_audio": {"availability_year_prior": 2012}}

    def _facts(self, immersive: str | None = None) -> MediaFacts:
        return MediaFacts(
            container="matroska",
            width=3840,
            height=2160,
            video_bitrate_kbps=20000,
            audio_codec="eac3",
            audio_channels=6,
            audio_immersive_extension=immersive,
        )

    def test_disabled_by_default_emits_nothing(self) -> None:
        findings = detect_immersive_audio_candidate("Dune (2021)/Dune (2021).mkv", self._facts(), {})
        self.assertEqual(findings, [])

    def test_enabled_recent_non_immersive_flags_candidate(self) -> None:
        findings = detect_immersive_audio_candidate(
            "Dune (2021)/Dune (2021).mkv", self._facts(), self.STANDARDS, enabled=True
        )
        self.assertEqual([f.code for f in findings], ["immersive_audio_candidate"])
        self.assertEqual(findings[0].severity, "candidate")

    def test_already_immersive_file_not_flagged(self) -> None:
        findings = detect_immersive_audio_candidate(
            "Dune (2021)/Dune (2021).mkv", self._facts(immersive="atmos"), self.STANDARDS, enabled=True
        )
        self.assertEqual(findings, [])

    def test_title_below_year_prior_not_flagged(self) -> None:
        findings = detect_immersive_audio_candidate(
            "Heat (1995)/Heat (1995).mkv", self._facts(), self.STANDARDS, enabled=True
        )
        self.assertEqual(findings, [])

    def test_candidate_severity_excluded_from_risk_score(self) -> None:
        findings = detect_immersive_audio_candidate(
            "Dune (2021)/Dune (2021).mkv", self._facts(), self.STANDARDS, enabled=True
        )
        self.assertEqual(total_risk_score(findings), 0)

    def test_available_verdict_fires_even_when_disabled_and_old(self) -> None:
        findings = detect_immersive_audio_candidate(
            "Heat (1995)/Heat (1995).mkv", self._facts(), {}, verdict="available"
        )
        self.assertEqual([f.code for f in findings], ["immersive_audio_candidate"])
        self.assertIn("confirmed available", findings[0].summary)

    def test_available_verdict_ignored_when_file_already_immersive(self) -> None:
        findings = detect_immersive_audio_candidate(
            "Dune (2021)/Dune (2021).mkv", self._facts(immersive="atmos"), {}, verdict="available"
        )
        self.assertEqual(findings, [])

    def test_final_below_target_verdict_surfaces_as_not_available(self) -> None:
        # A hard-won "no object-audio release exists" fact is pinned visibly,
        # regardless of the candidate toggle or year prior — not suppressed.
        findings = detect_immersive_audio_candidate(
            "Heat (1995)/Heat (1995).mkv", self._facts(), {}, verdict="final_below_target"
        )
        self.assertEqual([f.code for f in findings], ["immersive_audio_candidate"])
        self.assertIn("confirmed unavailable", findings[0].summary.lower())


class LopsidedEncodeTests(unittest.TestCase):
    def _facts(self, **overrides) -> MediaFacts:
        base = dict(
            resolution_bucket="1080p",
            width=1920,
            height=1080,
            video_bitrate_kbps=16000,
            audio_codec="eac3",
            audio_channels=6,
            audio_bitrate_kbps=4000,
        )
        base.update(overrides)
        return MediaFacts(**base)

    def test_reference_video_with_starved_audio_flags_audio_starved(self) -> None:
        facts = self._facts(audio_bitrate_kbps=96)
        result = evaluate_lopsided_encode(facts, DEFAULT_MOVIE_STANDARDS)
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "encode_lopsided_audio_starved")
        self.assertEqual(result["status"], "fail")

    def test_reference_audio_with_starved_video_flags_video_starved(self) -> None:
        facts = self._facts(video_bitrate_kbps=4000, audio_codec="truehd")
        result = evaluate_lopsided_encode(facts, DEFAULT_MOVIE_STANDARDS)
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "encode_lopsided_video_starved")
        self.assertEqual(result["status"], "fail")

    def test_uniformly_weak_is_not_lopsided(self) -> None:
        facts = self._facts(video_bitrate_kbps=2000, audio_bitrate_kbps=96)
        self.assertIsNone(evaluate_lopsided_encode(facts, DEFAULT_MOVIE_STANDARDS))

    def test_uniformly_strong_is_not_lopsided(self) -> None:
        facts = self._facts(audio_codec="truehd", audio_bitrate_kbps=4000)
        self.assertIsNone(evaluate_lopsided_encode(facts, DEFAULT_MOVIE_STANDARDS))

    def test_estimated_starved_axis_drops_to_review(self) -> None:
        facts = self._facts(audio_bitrate_kbps=96, audio_bitrate_estimated=True)
        result = evaluate_lopsided_encode(facts, DEFAULT_MOVIE_STANDARDS)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "review_low_confidence")
        self.assertEqual(result["confidence"], "low")

    def test_missing_axis_yields_no_verdict(self) -> None:
        self.assertIsNone(evaluate_lopsided_encode(self._facts(audio_bitrate_kbps=0), DEFAULT_MOVIE_STANDARDS))
        self.assertIsNone(evaluate_lopsided_encode(self._facts(video_bitrate_kbps=0), DEFAULT_MOVIE_STANDARDS))

    def test_efficient_codec_gets_grace_baseline(self) -> None:
        # Strong video (1.5x reference) drags the spread past the gate. At the flat
        # baseline an AC3 6ch @ 320 reads as starved audio; the efficient EAC3
        # baseline spares the identical bitrate.
        ac3 = self._facts(video_bitrate_kbps=24000, audio_codec="ac3", audio_bitrate_kbps=320)
        result = evaluate_lopsided_encode(ac3, DEFAULT_MOVIE_STANDARDS)
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "encode_lopsided_audio_starved")
        eac3 = self._facts(video_bitrate_kbps=24000, audio_codec="eac3", audio_bitrate_kbps=320)
        self.assertIsNone(evaluate_lopsided_encode(eac3, DEFAULT_MOVIE_STANDARDS))

    def test_lossless_audio_never_flagged_starved(self) -> None:
        # A thin/estimated lossless read must never count as the starved axis.
        facts = self._facts(video_bitrate_kbps=24000, audio_codec="truehd", audio_bitrate_kbps=200)
        self.assertIsNone(evaluate_lopsided_encode(facts, DEFAULT_MOVIE_STANDARDS))

    def test_efficiency_baseline_is_config_driven(self) -> None:
        facts = self._facts(video_bitrate_kbps=24000, audio_codec="eac3", audio_bitrate_kbps=320)
        self.assertIsNone(evaluate_lopsided_encode(facts, DEFAULT_MOVIE_STANDARDS))
        tightened = json.loads(json.dumps(DEFAULT_MOVIE_STANDARDS))
        tightened["lopsided_encode"]["audio_efficient_kbps_per_channel"] = 107
        result = evaluate_lopsided_encode(facts, tightened)
        self.assertIsNotNone(result)
        self.assertEqual(result["code"], "encode_lopsided_audio_starved")

    def test_lopsided_marks_item_weak_candidate(self) -> None:
        facts = self._facts(audio_bitrate_kbps=96)
        item = build_movie_profile_item(
            Path("/movies"),
            Path("/movies/The Matrix (1999)/The Matrix (1999).mkv"),
            facts,
            standards=DEFAULT_MOVIE_STANDARDS,
        )
        self.assertTrue(item.profile.weak_candidate)
        codes = {diag.code for diag in item.profile.diagnostics}
        self.assertIn("encode_lopsided_audio_starved", codes)

    def test_low_confidence_lopsided_stays_review_only(self) -> None:
        facts = self._facts(
            video_bitrate_kbps=24000,
            audio_codec="ac3",
            audio_bitrate_kbps=320,
            audio_bitrate_estimated=True,
        )
        item = build_movie_profile_item(
            Path("/movies"),
            Path("/movies/The Matrix (1999)/The Matrix (1999).mkv"),
            facts,
            standards=DEFAULT_MOVIE_STANDARDS,
        )
        self.assertFalse(item.profile.weak_candidate)
        self.assertEqual(item.profile.label, "needs_review")
        codes = {diag.code for diag in item.profile.diagnostics}
        self.assertIn("encode_lopsided_audio_starved", codes)

if __name__ == "__main__":
    unittest.main()
