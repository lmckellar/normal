# Roadmap

*Authorship: Agent-written.*

## Where we are now

### Headline

`normal` is now in a semi-stable alpha state with a new default movie
workbench at the root route and a narrower but more coherent surfaced product
shape. Normalize, weak-encode triage, junk cleanup, repair defaults, canonical
list coverage, and export are materially useful. Recent scan/cache work and the
new shell pivot mean the product now feels more deliberate than exploratory,
but it is still pre-1.0 and still best suited to Linux users comfortable with
alpha software. Present `v0.7.0-alpha.4` is the current tagged cut of that new
default surface and focuses on restoring auditability, richer inspection, and
IMDb-first canonical coverage inside the same shell rather than widening the
release surface again.

### Concerns

- **UI/UX maturity** — the new default shell is much stronger than the old
  dashboard, but resurfacing withheld lanes into it without losing coherence is
  the next real test.
- **Main workflow maturity** — movie lanes are credible for real use; TV does
  not exist yet, so the product is still intentionally movie only in practice.
- **Documentation coherence** — `README`, `CHANGELOG`, and this roadmap are the
  release truth set. Broader docs are intentionally allowed to lag for now to
  avoid churn while the current compact-shell surface is likely still short-lived.
- **Safety / mutation confidence** — rename, delete, and remux lanes are
  meaningfully bounded and preview-driven, but they still deserve active
  caution to retain clear boundaries in the face of TV parsing logic.
- **Auditability / receipts** — the unified ledger now exists and is useful.
  The next need is UI polish, breadth validation, and keeping follow-up
  semantics coherent as more workflows return.
- **Performance / scan economics** — recent cache and shared-scan work improved
  the runtime reality materially. The next task is to retain that strength
  while defending against boundary regressions.
- **Architecture health** — backend workflows and parser hardening are ahead of
  the newly narrowed UI surface. The next step is resurfacing that backend
  strength without growing another incoherent dashboard.
- **Release/versioning coherence** — now coherent from `v0.7.0-alpha.1`
  forward; earlier reconstructed history remains useful context, not true
  release history.

### Product identity going forward

`normal` is traversing the wobbly terrain from personal tool stored in the public space to conceivably useful indie dev OSS project with a clearly articulated pre-existing use case only currently addressed by paid tools. A more mature and articulated body of principles is currently being crystallized and injected inline into the runtime environment of the project itself. 

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

## 0.7.x — Default workbench consolidation

- Promote the new compact shell to the root route and remove the old dashboard
  from the active public product path.
- Keep public release truth honest without rewriting the whole doc set.
- Defend concise-only movie normalization and its parser hardening gains.
- Finish the immediate movie-lane stabilization work that directly affects the
  alpha.4 default surface.
- Keep UI cleanup focused on coherence inside this new shell, not on reviving
  the old dashboard structure.
- Land the left Policy rail as the sole write owner for library policy and
  operator delete posture.
- Keep repo-local library policy and user-local operator preferences separate so
  release-facing defaults and user-machine behavior do not blur together.
- Stabilize the unified Repair Defaults lane and the shell reflow that suppresses
  downstream preview while policy editing is active.
- Remove deprecated alternate UI routes rather than carrying multiple active
  shells through the same prerelease band.

## 0.8.x — Resurfacing, TV, and audit maturation

- Resurface withheld backend-backed movie lanes and support surfaces into the
  new workbench shape after they are stable enough to return.
- Harden the new audit / receipt system across resurfaced workflows and keep
  its storage, follow-up semantics, and UI reading model coherent.
- Add the **TV Show Normalize** lane as the next major product family inside
  the same workbench grammar.
- Keep apply safety, source-root validation, and preview discipline consistent
  across movie and TV mutation paths.

- **Series and season structure** — target shape:
  `Show Name (Year)/Season NN/Show Name - SNNENN - Episode Title.ext`; fall
  back to the smallest safe default when episode titles are unavailable.
- **Episode parsing** — `S01E02`, `1x02`, season-folder, absolute anime-style,
  specials, multi-episode, and messy release-token inputs handled without
  remote metadata as a hard dependency.
- **Package cleanup** — adapt movie artifact cleanup for TV extras, samples,
  empty season folders, duplicate wrappers, and season-pack folders.
- **Apply safety** — reuse movie normalizer's preview/apply discipline: no
  silent destructive execution, review for ambiguity, source-root validation on
  every moved or deleted path.

## 0.9.x — Post-resurfacing polish and stabilization

- Histogram improvements — interactive drilldowns to reveal files in a selected
  curve segment, first as compact overview then as a detailed list.
- Canonical list badge and inspector refinements.
- UI consistency and colour logic pass once the resurfaced lanes and TV shape
  are settled.
- Remaining parser edge cases and normalization ambiguities across both lanes.
- Minor underdeveloped-feature polish after the new audit system and resurfaced
  workflows are in place.

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

## Disclaimer
  `normal` is pre-1.0. The current version story was retroactively rebuilt from commit history and diff/change logs. The first real release is `v0.7.0-alpha.1`, and the current release is `v0.7.0-alpha.4`; both have matching prerelease intent. Earlier sections in `CHANGELOG.md` remain reconstructed history rather than tagged releases.
