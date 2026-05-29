# Roadmap

*Authorship: Agent-written.*

## Where we are now

### Headline

`normal` is now in a semi-stable alpha state with main lanes built and
materially useful: normalize, quality triage, junk cleanup, repair defaults,
canonical list coverage, and export. The recent scan/cache work means the
product shape feels coherent rather than exploratory, but it is still pre-1.0
and the remaining work will need to focus heavily on UI and UX improvements.
Present v0.7.0-alpha.1 release is only recommended for Linux users who are 
comfortable working with alpha software.

### Concerns

- **UI/UX maturity** — functionally strong, but still uneven in consistency,
  colour logic, and overall polish between pages. does not respect screen realestate
  nor yet have a concise, Universal Principle of interaction perceivable across workflows
- **Main workflow maturity** — movie lanes are credible for real use; TV does
  not exist yet, so the product is still intentionally movie only in practice.
- **Documentation coherence** — mostly aligned with the movie-first reality. Current key
  user docs Readme and Statement are suitabily human written.
- **Safety / mutation confidence** — rename, delete, and remux lanes are
  meaningfully bounded and preview-driven, but they still deserve active
  caution to retain clear boundaries in the face of TV parsing logic.
- **Auditability / receipts** — replacement and subtitle history are useful with
  a noted gap around junk deletion. Authorial policy is clear yet not evenly applied to doc base. 
- **Performance / scan economics** — recent cache and shared-scan work improved
  the runtime reality materially. retain strength and defend against boundary regressions.
- **Architecture health** — structural refactor of web.py has deconstructed monolithic 
  web backend into assets packages. frontend/editor ergonomics remain less mature than the
  backend workflows which feel suitably scoped to the tool. 
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

## 0.7.x — Library trim and polish

- Remove remaining legacy public identity references from the repo and docs.
- Keep verbose naming removed from the product path; retain only the parser
  hardening and concise collision logic that the old regression corpus forced.
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

## Disclaimer
  `normal` is pre-1.0. The current version story was retroactively rebuilt from commit history and diff/change logs. The first real release is `v0.7.0-alpha.1`, with a matching git tag and GitHub prerelease; earlier sections in `CHANGELOG.md` remain reconstructed history rather than tagged releases.
