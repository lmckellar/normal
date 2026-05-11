# Roadmap

`normal` is pre-1.0. The current version story is reconstructed from commit
history; package metadata stays at `0.1.0` until a real release is cut.

## Where we are now — reconstructed 0.6.3

The app has grown from a local music/movie cleanup tool into a feature-rich
workbench with several movie repair and triage lanes.

Music lane: scan, plan, apply, artist deduplication, dashboard profile, weak
encode triage, artwork repair for Jellyfin, CSV export, and replacement queue
tracking.

Movie lane: normalize names, encode quality profiling, dashboard standards
controls, canonical-list coverage, weak encode triage, multi-audio packaging
triage and repair, subtitle readiness repair, poster artwork repair for Plex,
junk cleanup, shared replacement queue workflow, and XLSX catalogue export.

Current pressure: the lane set is useful, but scanning and UI state are
fragmented. Movie profile already acts as a shared scan for Dashboard, weak
encode, audio packaging, and subtitle readiness workflows; other areas still
run separate scans and produce separate UI projections.

## 0.7.x — prove and polish existing lanes

Focus: make the current workflows trustworthy before adding another large
architecture change.

- **Plex Artwork Repair testing** — test against real libraries and refine poster
  previews.
- **Subtitle Readiness validation** — confirm downstream Plex behavior and
  document any required Plex refresh/cache steps after repair.
- **Minor UI polish** — fix twitchy button hover behavior, accidental
  double-height buttons, theme contrast issues, typeface leaks, and rogue CSS
  paths that do not fit the active theme.
- **Movie normalization defaults** — make default movie filepath normalization
  less verbose.
- **Basic normalization controls** — expose simple movie filepath output options
  in the UI before the larger UI overhaul.

## 0.8.x — make discovery and collection intelligence useful

Focus: turn coverage and recommendation surfaces into practical decision tools.

- **Canonical Lists calculation** — review and fix the current coverage logic
  where it is incomplete, noisy, or misleading.
- **Canonical Lists actionability** — show the actual list with owned titles,
  missing titles, and owned-but-below-selected-quality titles as distinct states.
- **Canonical Lists badge rethink** — keep badges only if they become compact
  secondary status; otherwise fold or remove them.
- **Music Recommendation Engine** — replace the placeholder with a useful
  music-only recommendation workflow after choosing credible list/source/API
  inputs.

Movie recommendations are out of scope. IMDb already handles that use case well.

## 0.9.0 — unified scan and domain refactor

Focus: make scanning and state architecture coherent enough to support 1.0.

- Replace fractured lane scans with a singular source scan architecture where it
  is actually safe and useful.
- Separate source inventory, domain findings, workflow actions, persistent queue
  state, and UI projection state.
- Streamline downstream object rendering around the primary scan output.
- Review DDD and state-management boundaries as part of the refactor, not as a
  separate abstract exercise.

## 0.9.x — refactor stabilization

Focus: refine the large 0.9 lift in slices.

- Harden probe lifecycle, cancellation, scan observability, and risky-source
  behavior.
- Tighten replacement queue state boundaries and performance.
- Refine report shapes, cache ownership, and UI projection ownership after the
  unified scan lands.
- Keep existing destructive workflow safety constraints intact.

## 1.0.0 — dashboard-led UI overhaul

Focus: turn the app from a set of workflow pages into one coherent product.

- Make Dashboard the source-of-truth hub and workflow selector.
- Invoke workflows from Action Cards rather than treating top-level page
  navigation as permanent workflow state.
- Reduce navigational chrome prominence without losing navigability.
- Give information-rich surfaces more room.
- Enforce horizontal and vertical symmetry through reasonable viewport sizes.
- Keep Dashboard, diagnostic surfaces, repair flows, and queue state visually and
  conceptually aligned.

## 1.1.0 candidate — packaging and onboarding

Focus: move beyond agent-assisted setup.

- Add a basic runtime package or installer so `normal` can launch like a normal
  desktop program.
- Keep the first packaging pass lightweight; do not rewrite the app as a native
  desktop application.
- Add onboarding for required API keys with local validation and local secret
  storage.
- Keep secrets out of repo files and generated support artifacts.

## Later candidates

- **Interactive histogram drilldowns** — allow curve sections such as p10 to 0
  to reveal the files in that range, first as a compact overview and then as a
  detailed list.
- **Catalogue merge / swap report** — import another user's exported catalogue,
  compare shared movies, and suggest swaps where one library has a stronger
  encode.
- **Plex Compatibility workflow** — heuristic findings exist in
  `movie_profile.py`, but the UI remains hidden until the workflow shape is
  clear.
