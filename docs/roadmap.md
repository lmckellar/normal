# Roadmap

`normal` is pre-1.0. The current version story was retroactively rebuilt from
commit history and diff/change logs; package metadata stays at `0.1.0` until a
real release is cut.

## Where we are now — movie normalization product-complete

The app has grown from a local music/movie cleanup tool into a feature-rich
workbench with several movie repair and triage lanes.

Music lane: scan, plan, apply, artist deduplication, dashboard profile, weak
encode triage, artwork repair for Jellyfin, CSV export, and replacement queue
tracking.

Movie lane: product-complete concise name normalization, encode quality
profiling, dashboard standards controls, canonical-list coverage, weak encode
triage, multi-audio packaging triage and repair, subtitle readiness repair,
poster artwork repair for Plex, junk cleanup, shared replacement queue workflow,
OMDb-backed replacement-history rating context, and XLSX catalogue export.

Current pressure: movie normalization now does the important job end to end. It
scans a movie directory, proposes a full local restructure, handles duplicate
concise targets with parsed differentiators, splits locally-evidenced
multi-movie packages, deletes high-confidence package artifacts, and applies the
result from the web UI. The remaining pre-refactor work is product trimming and
lane expansion: remove verbose naming as a production option, then build a TV
Show Normalization lane from the movie-normalization structure. The broader
scan/state split remains after those moves.

## 0.7.0 — normalization controls landed

Focus: make movie normalization output easier to steer without waiting for the
larger UI overhaul.

- **Movie normalization defaults** — default movie filepath output is now
  concise: `Title (Year)/Title (Year).ext`.
- **Normalization UI controls** — Movies / Normalize exposes `Concise Naming`
  and `Verbose Naming - Include Extra Information`; the CLI mirrors this with
  `--naming-style concise|verbose`.
- **Duplicate concise output** — same-title/year copies are differentiated from
  parsed local tokens or folder context, usually resolution, at both folder and
  file level; truly indistinguishable collisions stay in review.
- **One-shot cleanup behavior** — normalization can now safely include loose
  root moves, artifact-folder renames/merges, metadata-only artifact deletes,
  root AppleDouble junk deletes, and CD1/CD2-style multi-part normalization.
- **Parser hardening** — trailing-year technical-token shapes, `BluRayRemux`,
  mixed-script title prefixes, language tags, hyphenated release groups, and
  common typo tokens are covered by focused tests.

## 0.7.x — normalize product completion

Focus: lock movie normalization as a product-complete workflow, then remove the
temporary verbose naming path before broader refactor work.

- **Movie Normalization complete** — concise `Title (Year)/Title (Year).ext`
  output is the production path. Duplicate copies receive local differentiators
  when possible; truly unresolved collisions stay in review.
- **One-shot cleanup complete** — normalization covers loose root movies,
  no-video artifact renames/merges/deletes, metadata-only package artifacts,
  root AppleDouble junk, CD-style multi-part movies, and locally-evidenced
  multi-movie package splits.
- **Remove verbose naming** — drop `--naming-style verbose`, the web naming
  selector, and verbose-only preview payloads. Keep the parser hardening earned
  from verbose-mode tests, but make concise the only normalization output.
- **Keep docs local-first** — document the production workflow and the removal
  of verbose naming internally before the next public push.

## 0.8.x — TV show normalization lane

Focus: port the movie-normalization concept to TV show libraries while
respecting TV-specific folder and episode naming conventions.

- **TV Show Normalize page** — add a dedicated lane/page that scans a TV source
  and proposes a complete restructure before apply.
- **Series and season structure** — target a stable local shape such as
  `Show Name (Year)/Season NN/Show Name - SNNENN - Episode Title.ext` when the
  evidence is local enough; use the smallest safe default when episode titles
  are unavailable.
- **Episode parsing** — handle common `S01E02`, `1x02`, season-folder, absolute
  anime-style, specials, multi-episode, and messy release-token inputs without
  remote metadata as a hard dependency.
- **Package cleanup** — adapt movie artifact cleanup for TV extras, samples,
  empty packaging folders, duplicate wrappers, and season-pack folders.
- **Apply safety** — reuse the movie normalizer’s preview/apply discipline:
  no destructive defaults, review for ambiguity, and source-root validation for
  every moved or deleted path.

## 0.9.x — music collection intelligence

Focus: carry the Canonical Lists pattern into Music and turn the Music
Recommendation lane into a complete useful workflow.

- **Music Canonical Lists** — port the movie Canonical Lists workflow shape to
  music collection coverage.
- **List and API assets** — scaffold the list/source/API inputs needed for a
  stronger music recommendation pass.
- **Music Recommendation lane** — keep the useful existing function and bring
  the other three main functions into working state.
- **Workflow refinement** — tune the recommendation implementation once the
  lane is functionally complete.

Movie recommendations are out of scope. IMDb already handles that use case well.

## 1.0.0 — collection intelligence complete

Focus: mark the point where Canonical Lists and the Music Recommendation lane
passes are complete enough to stop expanding collection-intelligence scope.

- Canonical Lists are actionable for movie and music use cases.
- Music Recommendation has its main functions working against the chosen list
  and API assets.
- Remaining recommendation work is limited to minor tuning before refactor
  slices begin.

## 1.0.x — recommendation tuning and refactor slices

Focus: make minor Recommendation Engine tweaks, then begin the scan/domain
refactor in coherent slices.

- Keep recommendation tuning narrow after the 0.9.0 line.
- Replace fractured lane scans with a singular source scan architecture where it
  is actually safe and useful.
- Separate source inventory, domain findings, workflow actions, persistent queue
  state, and UI projection state.
- Streamline downstream object rendering around the primary scan output.
- Harden probe lifecycle, cancellation, scan observability, and risky-source
  behavior.
- Tighten replacement queue state boundaries and performance.
- Keep existing destructive workflow safety constraints intact.

## 1.1.0 — final refactor slice

Focus: land the final refactor slice and make the architecture stable enough
for 1.x product work.

- Finish the unified scan and domain boundary refactor.
- Refine report shapes, cache ownership, and UI projection ownership after the
  unified scan lands.
- Keep the current UI usable while architecture settles.

## 1.x — refactor stabilization and dashboard-led UI overhaul

Focus: stabilize the refactor first, then turn the app from a set of workflow
pages into one coherent product.

- Stabilize regressions, performance, and risky-source behavior after 1.0.0.
- Make Dashboard the source-of-truth hub and workflow selector.
- Invoke workflows from Action Cards rather than treating top-level page
  navigation as permanent workflow state.
- Reduce navigational chrome prominence without losing navigability.
- Give information-rich surfaces more room.
- Enforce horizontal and vertical symmetry through reasonable viewport sizes.
- Keep Dashboard, diagnostic surfaces, repair flows, and queue state visually and
  conceptually aligned.

## Later candidates

- **Packaging and onboarding** — move beyond agent-assisted setup with a
  lightweight launcher/installer and local API-key onboarding after the refactor
  and UI direction are stable.
- **Interactive histogram drilldowns** — allow curve sections such as p10 to 0
  to reveal the files in that range, first as a compact overview and then as a
  detailed list.
- **Catalogue merge / swap report** — import another user's exported catalogue,
  compare shared movies, and suggest swaps where one library has a stronger
  encode.
- **Plex Compatibility workflow** — heuristic findings exist in
  `movie_profile.py`, but the UI remains hidden until the workflow shape is
  clear.
