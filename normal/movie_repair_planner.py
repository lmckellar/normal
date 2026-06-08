from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from normal.movie_plan import parse_movie_name
from normal.movie_profile import (
    audio_stream_quality_key,
    canonical_audio_language,
    choose_best_english_subtitle_stream,
    choose_default_audio_stream,
    choose_default_subtitle_stream,
    english_stream_is_materially_weaker,
    is_english_subtitle,
    normalized_subtitle_preferences,
)
from normal.quality_review import AudioStreamFacts, MediaFacts, SubtitleStreamFacts


SUPPORTED_REPAIR_EXTENSIONS = {".mkv"}


def build_movie_repair_plan(
    facts: MediaFacts,
    *,
    path: str | None = None,
    subtitle_preferences: dict[str, Any] | None = None,
    resolve_language: Callable[[str, int | None], str | None] | None = None,
) -> dict[str, Any]:
    audio = build_audio_repair_plan(facts, path=path, resolve_language=resolve_language)
    subtitle = build_subtitle_repair_plan(
        facts,
        path=path,
        subtitle_preferences=subtitle_preferences,
    )
    combined = build_combined_repair_plan(
        facts,
        path=path,
        subtitle_preferences=subtitle_preferences,
        audio_plan=audio,
        subtitle_plan=subtitle,
        resolve_language=resolve_language,
    )
    families: list[str] = []
    if audio.get("repairable"):
        families.append("audio")
    if subtitle.get("repairable"):
        families.append("subtitle")
    return {
        "audio": audio,
        "subtitle": subtitle,
        "combined": combined,
        "issue_families": families,
    }


def build_audio_repair_plan(
    facts: MediaFacts,
    *,
    path: str | None = None,
    resolve_language: Callable[[str, int | None], str | None] | None = None,
) -> dict[str, Any]:
    streams = list(facts.audio_streams)
    default_stream = choose_default_audio_stream(streams)
    target_ordinal, target_stream = choose_best_english_audio_stream(streams)
    title: str | None = None
    year: int | None = None
    if resolve_language is not None and path:
        parsed = parse_movie_name(Path(path))
        title = parsed.title
        year = parsed.year
    issue_code = audio_repair_issue_code(facts, title=title, year=year, resolve_language=resolve_language)
    return {
        "issue_code": issue_code,
        "repairable": bool(issue_code and target_stream is not None and path_supports_repair(path) and len(streams) >= 2),
        "current_default_stream_index": default_stream.index if default_stream else None,
        "current_default_language": canonical_audio_language(default_stream.language) if default_stream else None,
        "target_ordinal": target_ordinal,
        "target_stream_index": target_stream.index if target_stream else None,
        "target_language": canonical_audio_language(target_stream.language) if target_stream else None,
    }


def build_subtitle_repair_plan(
    facts: MediaFacts,
    *,
    path: str | None = None,
    subtitle_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    streams = list(facts.subtitle_streams)
    default_stream = choose_default_subtitle_stream(streams)
    target_ordinal, target_stream = choose_target_subtitle_stream(
        facts,
        subtitle_preferences=subtitle_preferences,
    )
    issue_code = subtitle_repair_issue_code(
        facts,
        subtitle_preferences=subtitle_preferences,
        target_ordinal=target_ordinal,
    )
    repairable = subtitle_issue_is_repairable(
        facts,
        issue_code,
        target_ordinal=target_ordinal,
        path=path,
    )
    default_audio = choose_default_audio_stream(facts.audio_streams)
    default_audio_language = canonical_audio_language(default_audio.language) if default_audio else None
    preferences = normalized_subtitle_preferences(subtitle_preferences)
    policy_branch = "foreign_audio" if default_audio_language not in {None, "english"} else "english_audio"
    return {
        "issue_code": issue_code,
        "repairable": repairable,
        "mode": "clear" if target_ordinal is None else "target",
        "current_default_stream_index": default_stream.index if default_stream else None,
        "target_ordinal": target_ordinal,
        "target_stream_index": target_stream.index if target_stream else None,
        "target_forced": bool(target_stream.is_forced) if target_stream else False,
        "default_audio_language": default_audio_language,
        "policy_branch": policy_branch,
        "policy_preference": preferences["foreign_audio_subtitles"] if policy_branch == "foreign_audio" else preferences["english_audio_subtitles"],
    }


def build_combined_repair_plan(
    facts: MediaFacts,
    *,
    path: str | None = None,
    subtitle_preferences: dict[str, Any] | None = None,
    audio_plan: dict[str, Any] | None = None,
    subtitle_plan: dict[str, Any] | None = None,
    resolve_language: Callable[[str, int | None], str | None] | None = None,
) -> dict[str, Any]:
    audio = audio_plan or build_audio_repair_plan(facts, path=path, resolve_language=resolve_language)
    subtitle = subtitle_plan or build_subtitle_repair_plan(facts, path=path, subtitle_preferences=subtitle_preferences)
    if not audio.get("repairable"):
        return {
            "staged": False,
            "second_order_subtitle": False,
            "subtitle_changes_after_audio": False,
            "subtitle_after_audio": subtitle,
            "stages": [],
        }
    post_audio_facts = simulate_post_audio_default_facts(facts, target_ordinal=audio.get("target_ordinal"))
    subtitle_after_audio = build_subtitle_repair_plan(
        post_audio_facts,
        path=path,
        subtitle_preferences=subtitle_preferences,
    )
    subtitle_changes = subtitle_state_key(subtitle) != subtitle_state_key(subtitle_after_audio)
    second_order = subtitle_after_audio.get("repairable") and (
        not subtitle.get("repairable") or subtitle_changes
    )
    stages = [
        {
            "family": "audio",
            "action": "set_english_default",
            "target_stream_index": audio.get("target_stream_index"),
        }
    ]
    if subtitle_after_audio.get("repairable"):
        stages.append(
            {
                "family": "subtitle",
                "action": "normalize_subtitle_defaults",
                "evaluation_basis": "post_audio",
                "issue_code": subtitle_after_audio.get("issue_code"),
                "target_stream_index": subtitle_after_audio.get("target_stream_index"),
                "mode": subtitle_after_audio.get("mode"),
            }
        )
    return {
        "staged": True,
        "second_order_subtitle": second_order,
        "subtitle_changes_after_audio": subtitle_changes,
        "subtitle_after_audio": subtitle_after_audio,
        "stages": stages,
    }


def choose_best_english_audio_stream(streams: list[AudioStreamFacts]) -> tuple[int | None, AudioStreamFacts | None]:
    english_streams = [
        (index, stream)
        for index, stream in enumerate(streams)
        if canonical_audio_language(stream.language) == "english"
    ]
    if not english_streams:
        return None, None
    return max(english_streams, key=lambda item: audio_stream_quality_key(item[1]))


def choose_target_subtitle_stream(
    facts: MediaFacts,
    *,
    subtitle_preferences: dict[str, Any] | None = None,
) -> tuple[int | None, SubtitleStreamFacts | None]:
    subtitle_streams = list(facts.subtitle_streams)
    active_preferences = normalized_subtitle_preferences(subtitle_preferences)

    default_audio = choose_default_audio_stream(facts.audio_streams)
    default_audio_language = canonical_audio_language(default_audio.language) if default_audio else None
    if default_audio_language not in {None, "english"}:
        if active_preferences["foreign_audio_subtitles"] == "off":
            return None, None
        if active_preferences["foreign_audio_subtitles"] == "forced_english":
            forced_target = choose_best_english_subtitle_stream(subtitle_streams, forced_only=True)
            if forced_target is not None:
                return subtitle_streams.index(forced_target), forced_target
        english_target = choose_non_forced_english_subtitle_stream(subtitle_streams)
        if english_target is None:
            return None, None
        return subtitle_streams.index(english_target), english_target
    if active_preferences["english_audio_subtitles"] == "forced_english":
        forced_target = choose_best_english_subtitle_stream(subtitle_streams, forced_only=True)
        if forced_target is None:
            return None, None
        return subtitle_streams.index(forced_target), forced_target
    if active_preferences["english_audio_subtitles"] in {"english", "primary_language"}:
        english_target = choose_non_forced_english_subtitle_stream(subtitle_streams)
        if english_target is None:
            return None, None
        return subtitle_streams.index(english_target), english_target
    return None, None


def choose_non_forced_english_subtitle_stream(streams: list[SubtitleStreamFacts]) -> SubtitleStreamFacts | None:
    candidates = [stream for stream in streams if is_english_subtitle(stream) and not stream.is_forced]
    if not candidates:
        return None
    default_stream = choose_default_subtitle_stream(candidates)
    return default_stream or candidates[0]


def audio_repair_issue_code(
    facts: MediaFacts,
    *,
    title: str | None = None,
    year: int | None = None,
    resolve_language: Callable[[str, int | None], str | None] | None = None,
) -> str:
    default_stream = choose_default_audio_stream(facts.audio_streams)
    if default_stream is None:
        return ""
    default_language = canonical_audio_language(default_stream.language)
    if default_language in {None, "english"}:
        return ""
    english_streams = [stream for stream in facts.audio_streams if canonical_audio_language(stream.language) == "english"]
    if not english_streams:
        return ""
    if resolve_language is not None and title:
        original_language = resolve_language(title, year)
        if original_language is not None and original_language != "english":
            return ""
    best_english = max(english_streams, key=audio_stream_quality_key)
    if english_stream_is_materially_weaker(default_stream, best_english):
        return "default_non_english_audio_with_weak_english"
    return "default_non_english_audio"


def subtitle_repair_issue_code(
    facts: MediaFacts,
    *,
    subtitle_preferences: dict[str, Any] | None = None,
    target_ordinal: int | None = None,
) -> str:
    streams = list(facts.subtitle_streams)
    if not streams:
        return ""
    default_count = int(facts.default_subtitle_streams or 0)
    target_ordinal = target_ordinal if target_ordinal is not None else choose_target_subtitle_stream(
        facts,
        subtitle_preferences=subtitle_preferences,
    )[0]
    default_subtitle = choose_default_subtitle_stream(streams)
    default_audio = choose_default_audio_stream(facts.audio_streams)
    audio_language = canonical_audio_language(default_audio.language) if default_audio else None
    subtitle_policy = normalized_subtitle_preferences(subtitle_preferences)

    if default_count > 1:
        return "multiple_default_subtitles"
    if target_ordinal is None:
        if subtitle_policy["english_audio_subtitles"] in {"english", "primary_language"} and audio_language in {None, "english"}:
            return "" if (default_subtitle and is_english_subtitle(default_subtitle) and not default_subtitle.is_forced) else "english_audio_missing_default_english_subtitle"
        return "unnecessary_default_subtitle" if default_count > 0 else ""
    target = streams[target_ordinal]
    if default_subtitle and default_count == 1 and default_subtitle.index == target.index:
        return ""
    if target.is_forced:
        return "wrong_default_forced_subtitle" if default_count > 0 else "english_forced_not_default"
    if default_count == 0:
        return "missing_default_english_subtitle" if audio_language not in {None, "english"} else "english_audio_missing_default_english_subtitle"
    if audio_language not in {None, "english"}:
        return "wrong_default_subtitle_language"
    return "english_audio_missing_default_english_subtitle"


def subtitle_issue_is_repairable(
    facts: MediaFacts,
    issue_code: str,
    *,
    target_ordinal: int | None,
    path: str | None = None,
) -> bool:
    if not issue_code:
        return False
    if not path_supports_repair(path):
        return False
    if not facts.subtitle_streams:
        return False
    if issue_code in {"missing_default_english_subtitle", "english_audio_missing_default_english_subtitle"}:
        return False
    if issue_code == "multiple_default_subtitles":
        default_audio = choose_default_audio_stream(facts.audio_streams)
        default_audio_language = canonical_audio_language(default_audio.language) if default_audio else None
        return target_ordinal is not None or default_audio_language in {None, "english"}
    if issue_code in {"english_forced_not_default", "wrong_default_forced_subtitle", "wrong_default_subtitle_language"}:
        return target_ordinal is not None
    if issue_code == "unnecessary_default_subtitle":
        return True
    return False


def subtitle_disposition_value(*, is_default: bool, is_forced: bool) -> str:
    # ffmpeg's -disposition replaces a stream's whole disposition set, so flipping
    # `default` would otherwise wipe an existing `forced` bit. Preserve forced so a
    # re-probe still sees the forced English track the planner targeted.
    flags = []
    if is_default:
        flags.append("default")
    if is_forced:
        flags.append("forced")
    return "+".join(flags) if flags else "0"


def simulate_post_audio_default_facts(facts: MediaFacts, *, target_ordinal: int | None) -> MediaFacts:
    if target_ordinal is None:
        return facts
    simulated = deepcopy(facts)
    for ordinal, stream in enumerate(simulated.audio_streams):
        stream.is_default = ordinal == target_ordinal
    if simulated.audio_streams:
        simulated.default_audio_streams = 1
        simulated.default_audio_stream_index = simulated.audio_streams[target_ordinal].index
    return simulated


def subtitle_state_key(plan: dict[str, Any]) -> tuple[Any, ...]:
    return (
        plan.get("repairable"),
        plan.get("issue_code"),
        plan.get("mode"),
        plan.get("target_stream_index"),
    )


def path_supports_repair(path: str | None) -> bool:
    if not path:
        return True
    return any(str(path).casefold().endswith(ext) for ext in SUPPORTED_REPAIR_EXTENSIONS)
