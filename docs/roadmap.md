# Roadmap

`normal` is pre-1.0. The current version story was retroactively rebuilt from
commit history and diff/change logs; package metadata stays at `0.1.0` until a
real release is cut.

## Where we are now

The movie-lane build-out is complete and the architectural consolidation
originally planned for 1.0.x–1.x happened early. Live today:

- **Persistent probe cache** — cold full-library scan (~330 s) drops to ~5 s on
  every subsequent run; per-file invalidation on mtime change keeps it honest
  after repairs and renames.
- **Server-side profile cache** — Dashboard, Delete Weak Encodes, and Repair
  Defaults all share one cached `MovieProfileReport` per source; page switches
  return in under a second.
- **Unified scan workflows** — Repair Defaults (Multi-Audio + Subtitle) runs one
  shared scan feeding two sub-tabs; Junk (video + docs) runs one combined scan
  (~12 s vs ~2 min) feeding two detail panels.
- **Instant quality-profile saves** — no rescan triggered; browser patches
  in-memory state and rerenders immediately.

The remaining pre-TV work is trimming and hardening: fork and remove the Music
lane, drop Plex artwork, remove verbose naming, tighten UI consistency, and
finish outstanding parser edge cases.

### Product identity going forward

`normal` will be a dedicated tool for tagging, folder-quality management, and
library health for **movie and TV show collections** — a gap not well served by
free tools. Music library management will continue as a separate, focused
product (see below).

## Music lane — fork, not delete

The music features (FLAC tagging, normalization, artist deduplication, dashboard
profile, artwork repair, Jellyfin sync, CSV export, replacement queue) will be
extracted cleanly into a new git project with its own identity rather than
discarded. The intended scope of that product: a tagging, visualisation, and
intelligence dashboard for music collections that names, tags, and organises
files; recommends new listening; and surfaces upcoming live music activity.

Once the fork is made, all music code and traces are stripped from `normal`.

---

## 0.7.0 — Scan architecture and workflow consolidation *(done, not yet tagged)*

- **Persistent probe cache** (`ProbeCache` in `probe_cache.py`) — cold → warm
  scan across the full library; shared by profile, junk, export, and inspect.
- **Server-side movie profile cache** — single cached report serves Dashboard,
  Delete Weak Encodes, and Repair Defaults; explicit invalidation after
  file-mutating operations.
- **Unified Repair Defaults** — Fix Multi-Audio Packaging and Repair Subtitle
  Readiness share one scan and surface as two sub-tabs on one page.
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

- Fork Music lane to its own project; strip all music code and references from
  `normal`.
- Remove Plex movie artwork feature (added in 0.6.4; workflow duplicates
  what the Plex browser UI already provides).
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
  destructive defaults, review for ambiguity, source-root validation on every
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

- **Catalogue merge / swap report** — import another user's exported catalogue,
  compare shared movies, and suggest swaps where one library has a stronger
  encode.
- **Plex Compatibility workflow** — heuristic findings exist in
  `movie_profile.py`; the UI remains hidden until the workflow shape is clear.
