# TV normalization lane — architectural seam (pre-implementation brief)

*Authorship: Agent-written. Purpose: orient the implementing agent before the 0.8.x TV slice. Read this, then `docs/roadmap.md` §0.8.x, then `docs/agent.md`.*

This is a "where does the knife go" document, not an implementation plan. It exists because the TV lane needs a **wide glance to place the seam correctly**, followed by a **narrow focus to write it**. Get the seam wrong and TV becomes a nested-if tumour inside the movie planner. Get it right and ~half the work is already done.

## TL;DR

- The whole movie system is spined on a single identity: `(Title, Year)` → one flat `Title (Year)/Title (Year).ext`.
- TV inverts the load-bearing invariant: identity is two-level (`Series (Year)` + episode `S01E02`), the target is three-deep, and **many files correctly land in one folder** — the exact condition the movie planner treats as a collision/danger.
- **The seam is the `ParsedIdentity → ChangePlan` boundary.** Everything below it is shared and lane-agnostic today. Everything at/above it is lane-specific and should be *duplicated deliberately*, not generalized.
- Do **not** try to make TV ride through `build_movie_plan`. That is the matryoshka trap.

## The spine: `(Title, Year)`

Every load-bearing structure reduces to one identity:

- `ParsedMovieIdentity` (title, year, tech_tokens, release_group, confidence) — `movie_identity.py:158`
- `MovieIdentityKey` / `canonical_identity_key` — `movie_identity.py:174,338`
- output serialization is one line: `concise_movie_base()` → `f"{title} ({year})"` — `movie_plan.py:784`
- replacement queue, canonical lists, OMDb lookups — all keyed on `(title, year)`

TV's identity is **two-level and many-to-one**: the series carries `(Title, Year)`; the file is an episode; the target is `Show (Year)/Season NN/Show - S01E02 - Episode Title.ext` (roadmap §0.8.x). Many files correctly share one folder. That is precisely the condition `build_movie_plan` is built to prevent.

## The seam

Draw one line: **`ParsedIdentity → ChangePlan`.**

```
  filename/folder string
        │
        ▼
  ┌───────────────┐   LANE-SPECIFIC  (fork here)
  │ identity parse│   what is the unit? how do files group? what is the target string?
  │   + planner   │
  └───────┬───────┘
          ▼
     ChangePlan / ProposedChange   ◄── the contract. lane-neutral.
          │
          ▼
  ┌───────────────┐   SHARED  (do not fork)
  │   executor    │   dispatches purely on change_type
  └───────────────┘
          ▼
      filesystem
```

- **Below the line** (`ChangePlan → filesystem`): shared. The executor doesn't know or care whether a move came from a movie or an episode.
- **At/above the line** (unit, grouping, target string): lane-specific by nature. TV diverges here for real reasons, not incidental ones.

## Shared substrate — reuse, do not fork (~50–60% of the value)

Lane-agnostic today or trivially extractable:

| Asset | Where | Note |
|---|---|---|
| Change contract | `models.py` | `ProposedChange`/`ChangePlan` have zero movie concepts. `change_type` is a free string: `file_rename`, `file_move`, `folder_rename`, `folder_merge`, `folder_delete`, `file_delete`. |
| Executor | `movie_apply.py` (`apply_change` :177) | Dispatches purely on `change_type`. Safe/review gate, drift detection (`current_value` must still match on disk), depth-ordered folder ops, target-exists guards, `prune_empty_parents`, target-root copy — all generic. **Only** movie-specific bit: `MOVIE_SIDECAR_EXTENSIONS` + sidecar stem matching (:289–327). Effectively this is `apply.py`. |
| Token/crud hygiene | `movie_naming.py` + shared calls from `movie_identity.py` | `canonicalize_token_sequence`, `split_compact_technical_token`, `normalize_token`, `strip_leading_site_credit`, `cleanup_title_text`, `CANONICAL_TOKEN_MAP`, year-finding. Edge tracker/domain credit stripping (`www.tracker.com`, split domains, bracketed domain tags), `x265`, `BluRay`, a `sample` file — identical for TV. |
| Junk/artifact cleanup | `movie_junk.py`, `plan_*_artifact_folder_cleanup` | Same crud (samples, nfo, posters, AppleDouble `._*`). |
| Media analysis | `movie_scan.py` → `movie_profile.py`, `probe_cache.py` | ffprobe/MediaFacts/quality scoring are identical for an episode file. Probe cache is keyed by path+mtime — lane-neutral. |
| Web plumbing | `normal/web/` | activity tracker, scan guard, single-flight, the workbench row-shaping pattern in `serializers.py`. |

## Lane-specific — fork deliberately

`build_movie_plan` (`movie_plan.py:146`) is built around one invariant: **one folder → one movie → one flat `Title (Year)`**. Almost all of its hard code exists to *defend* that invariant:

- `plan_multi_part_movie_folder` / `plan_multi_movie_package_folder` (:365, :420)
- `movie_bases_for_planned_files` + `concise_collision_differentiators` (:788, :806)
- `mark_movie_target_collisions` / `mark_existing_movie_target_collisions` (:898, :926)
- the `movie_folder_multiple_videos` "skip for safety" warning (:206)

TV violates every one of these *by design*. 24 files in a folder is the correct case for TV and the skip-for-safety case for movies. If you thread TV exceptions through these functions you get the nested-if nightmare. **Leave them in the movie module. Write `tv_plan.py` parallel to them.**

## Recommended shape

1. **Pre-work status:** the movie parser/display cleanup seam has already been extracted into `movie_naming.py`, and `movie_identity.py` / `movie_plan.py` now reuse it. TV should build on that seam rather than recreating parser hygiene locally.
2. **Parallel, not nested:** new `tv_identity.py` + `tv_plan.py` that emit the *same* `ChangePlan`/`ProposedChange`. The executor consumes them unchanged — that is the entire payoff of the clean contract. No new `change_type` values should be needed; `file_move` + `folder_rename`/`folder_delete` already cover the restructure.
3. **Serializer sibling, not branch:** `build_tv_normalize_results` reusing the change-indexing pattern from `serializers.py:22` but yielding a hierarchical series→season→episode payload. The richer-row contract the workbench already expects (linked changes, warning messages) generalizes cleanly.
4. **Lane is user-chosen.** Separate TV page/source (roadmap already frames it this way). **Do not build a mixed-tree "is this TV or movies" auto-classifier for 0.8** — that classifier is a brand-new cross-lane bug source. Separate sources sidesteps it.

## Existing TV hooks worth knowing

`movie_profile.py` already detects episodic media as a *quality risk* (not yet as a normalize target). Reuse these signals — don't reinvent the regexes:

- `is_episode_like_path` (:1373), `looks_like_plex_friendly_episode_name` (:1380), `looks_like_absolute_numbering` (:1385)
- `SEASON_EPISODE_PATTERN`, `ANIME_EPISODE_PATTERN`
- heuristic codes already emitted: `episodic_naming_parse_risk`, `anime_absolute_numbering_risk`, `high_complexity_hevc_tv_risk`, `multi_audio_anime_mux_risk`

These are evidence the codebase already "sees" TV; the 0.8 work is turning recognition into a planning lane.

## Honest risks that survive a clean seam

These do not go away no matter how clean the boundary — but with the seam at identity they are **quarantined in `tv_identity.py`/`tv_plan.py` and touch movies not at all.**

1. **Episode parsing is irreducibly harder than title/year.** `S01E01E02` (multi-episode), `S00` specials, date-based dailies, absolute anime numbering → season mapping, and episode *titles* you usually cannot derive from local files. The roadmap's "smallest safe default when titles unavailable" is the correct posture — do not let title-unavailability block the season/episode-number rename.
2. **Collision semantics invert.** Keep all uniqueness assumptions (`mark_movie_target_collisions` and friends) strictly inside the movie module. Audit that no *shared* helper assumes one-target-per-folder before relying on it from TV.
3. **Apply granularity matters more.** A series restructure is ~200 files. Emit **per-episode** `ProposedChange`s, not a per-series blob, so one unparseable episode goes to `review` without blocking the rest of the season. The existing per-change safe/review gate then does the right thing for free.
4. **Portability + safety rules still bind.** Per `docs/agent.md` safety constraints: source-root validation on every moved/deleted path, no up-front full-tree enumeration in heavy scans (streamed traversal + cancellation), no remote metadata as a hard dependency. TV's bigger move-sets make the streamed-scan discipline *more* important, not less.

## Onboarding checklist for the implementing agent

Before writing TV code, confirm you can answer:

- [ ] Can you state the seam in one sentence? (*Shared below `ChangePlan`; forked at/above identity.*)
- [ ] Have you done the parser de-duplication pre-work, or consciously deferred it with a reason?
- [ ] Is your `tv_plan.py` emitting the existing `ProposedChange` contract with **no new `change_type`**? If you reached for a new one, re-examine — you probably don't need it.
- [ ] Are TV changes **per-episode**, so partial failure degrades to per-episode `review`?
- [ ] Have you left `build_movie_plan` and its collision/multi-video machinery **untouched**?
- [ ] Is the lane user-selected (separate source), with **no mixed-tree classifier**?

## Bottom line

The instinct "TV shares logic with movies" is right about the substrate and wrong about the planner — and the planner is where that instinct would lead you to dig if unguarded. Duplicate the identity-to-target planner deliberately; reuse the executor, contract, hygiene, junk, ffprobe, and web plumbing. Name the boundary precisely as `ParsedIdentity → ChangePlan` and the feature stays sane.
