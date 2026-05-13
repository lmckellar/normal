# Roadmap

`normal` is pre-1.0. The current version story was retroactively rebuilt from
commit history and diff/change logs; package metadata stays at `0.1.0` until a
real release is cut.

## Where we are now — local current state after 0.7.0 candidate

The app has grown from a local music/movie cleanup tool into a feature-rich
workbench with several movie repair and triage lanes.

Music lane: scan, plan, apply, artist deduplication, dashboard profile, weak
encode triage, artwork repair for Jellyfin, CSV export, and replacement queue
tracking.

Movie lane: concise-first name normalization with verbose compatibility mode,
encode quality profiling, dashboard standards controls, canonical-list coverage,
weak encode triage, multi-audio packaging triage and repair, subtitle readiness
repair, poster artwork repair for Plex, junk cleanup, shared replacement queue
workflow, OMDb-backed replacement-history rating context, and XLSX catalogue
export.

Current pressure: the lane set is useful, but scanning and UI state are
fragmented. Movie profile already acts as a shared scan for Dashboard, weak
encode, audio packaging, and subtitle readiness workflows; other areas still
run separate scans and produce separate UI projections. Movie normalization has
crossed the planned 0.7 threshold: the default is now concise `Title (Year)`,
verbose naming remains available, duplicate concise targets get parsed
differentiators when possible, and several real-world parser misses have been
hardened. The broader scan/state split remains.

## 0.7.0 — normalization controls landed

Focus: make movie normalization output easier to steer without waiting for the
larger UI overhaul.

- **Movie normalization defaults** — default movie filepath output is now
  concise: `Title (Year)/Title (Year).ext`.
- **Normalization UI controls** — Movies / Normalize exposes `Concise Naming`
  and `Verbose Naming - Include Extra Information`; the CLI mirrors this with
  `--naming-style concise|verbose`.
- **Duplicate concise output** — same-title/year copies are differentiated from
  parsed local tokens, usually resolution, at both folder and file level; truly
  indistinguishable collisions stay in review.
- **Parser hardening** — trailing-year technical-token shapes, `BluRayRemux`,
  mixed-script title prefixes, language tags, hyphenated release groups, and
  common typo tokens are covered by focused tests.

## 0.7.x — canonical-list actionability and normalization polish

Focus: finish the remaining collection-decision work while polishing the new
normalization defaults against real-library scans.

- **Plex Artwork Repair testing** — Plex-synced poster previews, title parsing,
  and sort order landed in 0.6.4. Known remaining gap: numerical sort order has
  a minor residual mismatch vs Plex for some multi-digit numeric titles (e.g.
  48 Hrs. / 88 Minutes / 1917 ordering). Investigate and resolve.
- **Subtitle Readiness validation** — confirm downstream Plex behavior and
  document any required Plex refresh/cache steps after repair.
- **Canonical Lists calculation** — fix incomplete, noisy, or misleading
  coverage logic.
- **Canonical Lists actionability** — show owned, missing, and
  owned-below-selected-quality titles as distinct states.
- **Normalization scan review** — keep feeding real edge cases into the local
  parser, especially duplicate-copy handling and trailing-year release naming,
  without adding heavier scan requirements.
- **Minor UI polish** — fix twitchy button hover behavior, accidental
  double-height buttons, theme contrast issues, typeface leaks, and rogue CSS
  paths that do not fit the active theme.
- **Movie dashboard hardening** — keep profile persistence, scan-derived
  rendering, and replacement-history rating lookup stable while 0.7.x settles.

## 0.8.x — music collection intelligence

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

## 0.9.0 — collection intelligence complete

Focus: mark the point where Canonical Lists and the Music Recommendation lane
passes are complete enough to stop expanding collection-intelligence scope.

- Canonical Lists are actionable for movie and music use cases.
- Music Recommendation has its main functions working against the chosen list
  and API assets.
- Remaining recommendation work is limited to minor tuning before refactor
  slices begin.

## 0.9.x — recommendation tuning and refactor slices

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

## 1.0.0 — final refactor slice

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
