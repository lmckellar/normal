# Normalize Round 2 Status

Internal handoff note for resuming movie normalize hardening.

## Purpose

Round 2 is the parser-gate and residue-handling hardening pass for movie
normalize.

The goal is to keep normalize aggressive when the local library already
contains enough evidence, while shrinking review down to true unresolved
conflicts.

This round also adds an internal-only diagnostic surface for inspecting
normalize output at scale without exposing mutation controls.

## Why This Exists

Before this pass, several different problems were being collapsed into the same
review bucket:

- parser heuristics that were actually locally well-supported
- real duplicate-video target collisions
- no-video residue around an already-established winning movie folder
- subtitle leftovers that could often be merged safely

That made normalize noisier than necessary and made future hardening harder to
reason about.

## What Shipped

### Parser Evidence

`ParsedMovieIdentity` now carries structured local evidence instead of only
free-form warning strings:

- `reason_codes`
- `reason_messages`
- `title_source`
- `year_source`
- `parse_source_path`
- optional compact token traces

Confidence still resolves to `safe` or `review`.

### Parser Gate Changes

The parser now treats these as safe when local evidence is strong enough:

- year-leading collection members
- clean compact technical-token splits
- known safe noise/uploader tokens
- RYP or collection-member-style children where the child filename itself
  carries title/year evidence

Review remains for:

- weak title inference
- truly ambiguous compact title recovery
- unknown technical-token cases that still need human inspection

### Planner Separation

`movie_plan.py` now distinguishes between:

- unresolved duplicate-video collisions
- package splits
- existing-target artifact residue
- subtitle merge collisions

Behavior now expected:

- metadata/poster/NFO-only residue around an existing winner: auto-delete
- subtitle-only residue around an existing winner: move subtitles into the
  winner, then delete the residue folder
- subtitle path collisions during merge: keep as review
- mixed residue with substantive non-subtitle payload: keep as review

### Normalize Payload Enrichment

Normalize rows now expose row-level reasoning and provenance:

- `reason_codes`
- `reason_messages`
- `warning_codes`
- `linked_change_types`
- `title_source`
- `year_source`
- `projected_path`

The existing normalize endpoint shape remains compatible.

### Internal Testing UI

A separate internal read-only UI now exists at:

`/normalize-lab`

Its purpose is diagnostic inspection, not product workflow.

Current capabilities:

- source selection and normalize run
- search on current and projected paths
- filters for all, actionable, unchanged, safe, review
- filters for reason code and warning code
- package / collision / artifact / subtitle merge case filters
- sortable current path, projected path, confidence, reason bucket columns
- detail pane with parse evidence and exact review causes
- preview pane with projected path and linked changes
- selected-row export to local JSONL

### Local Corpus Export

The lab can export selected rows to git-ignored local analysis artifacts:

`/out/normalize-lab/*.jsonl`

This is read-only with respect to the movie library.

## Files Touched In This Round

Primary code:

- `normal/movie_identity.py`
- `normal/movie_plan.py`
- `normal/models.py`
- `normal/web/serializers.py`
- `normal/web/routes_normalize.py`
- `normal/web/server.py`

Internal UI assets:

- `normal/web_assets/normalize_lab.html`
- `normal/web_assets/normalize_lab.css`
- `normal/web_assets/normalize_lab.js`

Tests and regression data:

- `tests/test_movie_plan.py`
- `tests/test_movie_one_shot_normalize.py`
- `tests/test_movie_normalize_web.py`
- `tests/test_web_serializers.py`
- `tests/test_web.py`
- `tests/data/normalize_round2_cases.json`

## Current Validation State

Focused and full suite validation passed after implementation:

- `python -m unittest discover -s tests`

Observed result at implementation time:

- `226` tests passed

## How To Resume Tomorrow

Start by reopening:

- this file
- `docs/internal/one-shot-movie-normalization-logic.md`
- `normal/movie_identity.py`
- `normal/movie_plan.py`
- `normal/web_assets/normalize_lab.js`

Then use `/normalize-lab` against the local movie corpus and export selected
cases from rows that still feel noisy or under-explained.

## Likely Next Work

- tighten reason bucketing and phrasing if the lab shows noisy or redundant row
  explanations
- promote exported live-corpus cases into committed synthetic tests
- refine subtitle residue handling if real libraries expose nested or
  language-tag edge cases not covered yet
- decide whether any remaining planner warnings should be split further for UI
  clarity
- improve the lab only if it materially helps normalize hardening; do not let
  it become a second product UI

## Follow-On Performance Note

After the initial round-2 parser/lab work landed, normalize web performance
was later re-hardened around the new reality that verbose naming is legacy
support matter, not an active product mode.

That follow-on pass removed the expensive dual-style normalize web payload path:

- web normalize now builds one requested plan instead of both concise and
  verbose on every request
- parsed identities are precomputed once per request and reused by plan build
  and row serialization
- normalize row serialization now indexes linked changes and warnings instead of
  rescanning the full change/warning lists per movie
- web normalize surfaces default back to concise-only operation, while verbose
  planner behavior remains only as parser-hardening coverage for legacy input

Observed effect on the reference mounted library: normalize returned to
single-digit-second behaviour instead of the earlier minute-scale post-hardening
regression.

## Important Constraint

Do not expand normalize with invented business rules.

The operating rule remains:

- normalize aggressively when local evidence is strong
- preserve externally meaningful subtitle residue when merge-safe
- delete redundant metadata-only leftovers
- keep review only for true unresolved conflicts or weak local inference
