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
- unknown technical-token cases where the tail still lacks enough recognized structure to trust the parse

Provisional current state on the reference scan:

- review-only flagged normalize cases have been driven to zero
- this should be treated as a hardening checkpoint, not a claim that parser review is globally finished

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

`/parser-tester-ui`

Its purpose is diagnostic inspection, not product workflow.

Current capabilities:

- source selection and normalize run
- search on current and projected paths
- filters for all, actionable, unchanged, safe, review
- filters for reason code and warning code
- package / collision / artifact / subtitle merge case filters
- select all / deselect all against the current filtered result set
- sortable current path, projected path, confidence, reason bucket columns
- detail pane with parse evidence and exact review causes
- inline detail / preview toggle in one container instead of stacked panels
- preview pane with staged selected preview and full filtered-library preview
- compact projected directory-tree render for downstream shape inspection
- selected-row export to local JSONL

### Local Corpus Export

The lab can export selected rows to git-ignored local analysis artifacts:

`/out/parser-tester-ui/*.jsonl`

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

Then use `/parser-tester-ui` against the local movie corpus and export selected
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

## 2026-05-30 Follow-On Slice

This follow-on slice tightened three connected gaps that still showed up in
real normalize review output:

- parser/planner collision handling
- normalize row visibility in `/parser-tester-ui`
- review boundary coverage for existing-target cases

Later on 2026-05-30, one additional live-library hardening issue was confirmed
through `/parser-tester-ui` itself:

- composed downstream file collisions could still slip through as `safe` when a
  `file_rename` plus `folder_rename` landed on the same final movie file as a
  separate `file_move`

The Ace Ventura Pet Detective live-library case exposed this clearly in the
Preview tree even while the proposal table still showed zero review flags. That
was a genuine planner defect, not a preview artifact.

### What Changed

- existing-target collisions now attempt a safe alternate concise target before
  staying in review
- differentiators can come from parsed technical tokens such as `BDRip` or
  `1080p`
- when technical tokens are not enough, the planner can now reuse local package
  labels from parent folders below the source root
- repeated parent package-title residue is now stripped back out of child tail
  text before token classification, so stale post-split filenames do not drag
  `Grindhouse Planet Terror & Death Proof ...` style junk forward as fake
  differentiators
- package-folder context no longer falls back to the whole multi-movie folder
  label when a shorter tail token such as `1080p` is available
- once a package-style folder has effectively collapsed to one surviving movie
  payload, the planner now allows the folder itself to normalize into the same
  concise differentiated target instead of protecting the stale package shell
- normalize row payloads now include serialized linked changes plus warning
  messages, not just flattened code lists
- `/parser-tester-ui` now shows those linked reasons and warning messages directly
  in the row detail pane, and row checkbox selection updates the active detail
  view immediately
- `/parser-tester-ui` preview is now an inline staged tree view rather than a
  second verbose debug card stack, which makes downstream shape inspection
  materially useful against the real library
- collision marking now uses the composed final movie path for `file_rename`
  rows after any paired `folder_rename`, so the planner catches downstream
  file collisions that were previously missed
- the Ace Ventura composed-collision shape is covered by a committed planner
  regression test
- the Grindhouse / Death Proof post-split residue shape is now covered both for
  child-tail cleanup and for concise differentiated folder recovery

### Validation Run

Focused validation for this slice:

- `python -m unittest tests.test_movie_plan tests.test_web tests.test_web_serializers tests.test_movie_normalize_web tests.test_movie_one_shot_normalize`

### Remaining Legit Review Limits

These still correctly stay in review after this slice:

- root-level duplicate titles that collide with an existing canonical target
  but have no extra local context to safely differentiate
- cases where title/year parsing still fails or stays weak
- subtitle merge collisions or mixed-residue folders where auto-cleanup would
  risk dropping substantive payload

## Important Constraint

Do not expand normalize with invented business rules.

The operating rule remains:

- normalize aggressively when local evidence is strong
- preserve externally meaningful subtitle residue when merge-safe
- delete redundant metadata-only leftovers
- keep review only for true unresolved conflicts or weak local inference
