# Roadmap

*Authorship: Agent-written.*

`normal` is pre-1.0. The current version story was retroactively rebuilt from commit history and diff/change logs. The first real release tag is `v0.7.0-alpha.1`; earlier sections in `CHANGELOG.md` remain reconstructed history rather than tags.

## Where we are now

The movie workflow build-out is the product now. Live today:

- **Persistent probe cache** — cold full-library scan (~330 s) drops to ~5 s on
  every subsequent run; per-file invalidation on mtime change keeps it honest
  after repairs and renames.
- **Server-side profile cache** — Dashboard, Delete Weak Encodes, and Repair
  Defaults all share one cached `MovieProfileReport` per source; page switches
  return in under a second.
- **Unified scan workflows** — Repair Defaults (Audio Packaging + Subtitle Readiness) runs one
  shared scan feeding two sub-tabs; Junk (video + docs) runs one combined scan
  (~12 s vs ~2 min) feeding two detail panels.
- **Instant quality-profile saves** — no rescan triggered; browser patches
  in-memory state and rerenders immediately.
- **Cancellation rough-edge closure** — the earlier cancelled-scan / leftover-`ffprobe`
  issue is no longer treated as active after the current scan-control hardening
  and has been stable in real use.

The remaining pre-TV work is trimming and hardening: remove remaining legacy public traces, remove verbose naming, tighten UI consistency, and finish parser edge cases.

### Product identity going forward

`normal` is now a dedicated tool for naming, quality management, repair, and library health for movie collections first, with TV as the next major expansion. The public docs should reflect that current state directly rather than preserving parallel-story clutter from earlier phases.

---

## 0.7.0-alpha.1 — Scan architecture and workflow consolidation *(first real prerelease)*

- **Persistent probe cache** (`ProbeCache` in `probe_cache.py`) — cold → warm
  scan across the full library; shared by profile, export, and inspect.
- **Server-side movie profile cache** — single cached report serves Dashboard,
  Delete Weak Encodes, and Repair Defaults; explicit invalidation after
  file-mutating operations.
- **Unified Repair Defaults** — Audio Packaging and Subtitle Readiness share one
  scan and surface as two sub-tabs on one page.
- **Unified junk scan** — video junk and document/sidecar junk merged into one
  combined scan; ~12 s vs ~2 min previously.
- **Single-walk normalization** — `build_movie_plan` accepts a pre-discovered
  file list; `handle_movies_normalize` and `handle_movies_apply` call
  `discover_video_files` once and share it, eliminating the previous 3×
  redundant walk.
- **Instant quality-profile saves** — `POST /api/movies/standards/update`
  writes and returns; no scan is triggered.
- **Canonical list swap** — `top_1000` and `suspense_horror` removed;
  `animation` (Top 50 Animation, genre 16, 60%) and `documentary` (Top 50
  Documentary, genre 99, 60%) added.
- **Fixed O(n²) reconcile regression** — `reconcile_replacement_queue` now
  calls `replacement_identities` once per issue family, not once per queue item.

## 0.7.x — Library trim and polish

- Remove remaining legacy public identity references from the repo and docs.
- Remove verbose naming option — drop `--naming-style verbose`, the web naming
  selector, and verbose-only preview payloads; retain the parser hardening the
  verbose-mode tests produced.
- Themes — remove at least two; full removal decision pending.
- Canonical list: surface "deleted, awaiting replacement" as a distinct token
  separate from "missing".
- UI consistency pass — button colours, global action bar, colour logic.
- Parser hardening carry-overs — `:` / `-` normalisation, sequel naming
  conventions, omega-dump and rodneyyouplonker collection edge cases.

## 0.8.x — TV Shows normalization lane

- **TV Show Normalize page** — dedicated lane that scans a TV source and
  proposes a complete restructure before apply.
- **Series and season structure** — target shape:
  `Show Name (Year)/Season NN/Show Name - SNNENN - Episode Title.ext`; fall
  back to the smallest safe default when episode titles are unavailable.
- **Episode parsing** — `S01E02`, `1x02`, season-folder, absolute anime-style,
  specials, multi-episode, and messy release-token inputs handled without
  remote metadata as a hard dependency.
- **Package cleanup** — adapt movie artifact cleanup for TV extras, samples,
  empty season folders, duplicate wrappers, and season-pack folders.
- **Apply safety** — reuse movie normalizer's preview/apply discipline: no
  silent destructive execution, review for ambiguity, source-root validation on every
  moved or deleted path.

## 0.9.x — Hardening and feature refinement

No new lanes. Maturing what's already built:

- Histogram improvements — interactive drilldowns to reveal files in a selected
  curve segment, first as compact overview then as a detailed list.
- Canonical list badge and inspector refinements.
- UI consistency and colour logic pass (carry-overs from 0.7.x if not landed).
- Remaining parser edge cases and normalization ambiguities across both lanes.
- Minor underdeveloped-feature polish.

## 1.0 — Release readiness

Both lanes stable. The tool has a clear, distinctive identity: folder and
tagging quality management for movies and TV shows, with no adequate free
analogue.

- All lane workflows stable and hardened.
- Packaging and onboarding — lightweight launcher, local API-key onboarding
  flow.
- Version metadata cut to 1.0.0.

---

## Later candidates

- **Extract inline JS from web.py** — move the ~5000-line inline `<script>` block into a proper `.js` file (or a few). No architectural overhaul; the goal is editor tooling: symbol search, go-to-definition, linting. The current blob is workable but makes wiring bugs slow to diagnose.
- **Catalogue merge / swap report** — import another user's exported catalogue,
  compare shared movies, and suggest swaps where one library has a stronger
  encode.
- **Plex Compatibility workflow** — heuristic findings exist in
  `movie_profile.py`; the UI remains hidden until the workflow shape is clear.
