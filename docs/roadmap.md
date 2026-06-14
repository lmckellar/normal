# Roadmap

## Where we are now

### Headline

`normal` is in a semi-stable alpha with a default movie **workbench** at the root route and a narrower, more coherent product shape. Normalize, weak-encode triage, junk cleanup, repair defaults, canonical-list coverage, and export are all materially useful. Recent scan/cache work and the shell pivot make the product feel deliberate rather than exploratory, while deployment and source safety now have native CI coverage across Linux, macOS, and Windows. It remains pre-`1.0`, and real-library validation outside Linux is still limited.

`v0.7.0-alpha.9` is the current tagged cut: a hardening checkpoint after the `alpha.8` feature wave. It intentionally changes little in the visible product surface and consolidates native CI and installed-wheel checks, centralized user-data paths, cross-platform mount and source policy, mutation-time path validation, heavy-scan safety, and the remote web trust model. The result is a cleaner baseline before the next product-facing push.

### Concerns

- **UI/UX maturity** — the default shell is much stronger than the old dashboard. The next test is resurfacing withheld lanes without reintroducing fuzzy ownership or weak preview semantics.
- **Main workflow maturity** — movie lanes are credible for real use; TV does not exist yet, so the product is still intentionally movie-only in practice.
- **Documentation coherence** — `README`, `CHANGELOG`, and this roadmap are the release-truth set. Broader docs are allowed to lag while the compact-shell surface is still settling.
- **Safety / mutation confidence** — rename, delete, and remux lanes are meaningfully bounded and preview-driven, but still deserve active caution as TV parsing logic arrives.
- **Auditability / receipts** — the unified ledger exists and is useful. The next need is UI polish, breadth validation, and coherent follow-up semantics as more workflows return.
- **Performance / scan economics** — recent cache and shared-scan work improved the runtime reality materially. The task now is holding that gain while defending against boundary regressions.
- **Architecture health** — backend workflows and parser hardening run ahead of the narrowed UI surface. The next step is resurfacing that backend strength without growing another incoherent dashboard.
- **Release / versioning coherence** — coherent from `v0.7.0-alpha.1` forward; earlier reconstructed history is useful context, not true release history.

### Product identity going forward

`normal` is crossing the wobbly terrain from a personal tool parked in public to a plausibly useful indie OSS project — one with a clearly articulated use case currently served only by paid tools. A more mature body of principles is being crystallized and injected inline into the runtime of the project itself.

---

## 0.7.0-alpha.1 — Scan architecture and workflow consolidation *(first real prerelease)*

- **Persistent probe cache** (`ProbeCache` in `probe_cache.py`) — cold → warm scan across the full library; shared by profile, export, and inspect.
- **Server-side movie profile cache** — one cached report serves Dashboard, Delete Weak Encodes, and Repair Defaults; explicit invalidation after file-mutating operations.
- **Unified Repair Defaults** — Audio Packaging and Subtitle Readiness share one scan, surfaced as two sub-tabs.
- **Unified junk scan** — video junk and document/sidecar junk merged into one scan (~12 s vs ~2 min previously).
- **Single-walk normalization** — `build_movie_plan` accepts a pre-discovered file list; `handle_movies_normalize` and `handle_movies_apply` walk once and share it, killing the previous 3× redundant walk.
- **Instant quality-profile saves** — `POST /api/movies/standards/update` writes and returns with no triggered scan.
- **Canonical list swap** — `top_1000` and `suspense_horror` removed; `animation` and `documentary` added.
- **Fixed O(n²) reconcile regression** — `reconcile_replacement_queue` now calls `replacement_identities` once per issue family, not once per queue item.

## 0.7.x — Default workbench consolidation

- Promote the compact shell to the root route and remove the old dashboard from the active product path.
- Keep public release truth honest without rewriting the whole doc set.
- Defend concise-only movie normalization and its parser-hardening gains.
- Finish the movie-lane stabilization that directly affects the default surface.
- Land the left **Policy** rail as the sole write owner for library policy and operator delete posture.
- Keep repo-local library policy and user-local operator preferences separate so release-facing defaults and user-machine behavior do not blur.
- Stabilize the unified Repair Defaults lane and the shell reflow that suppresses downstream preview while policy editing is active.
- Remove deprecated alternate UI routes rather than carrying multiple active shells through one prerelease band.

## 0.8.x — Resurfacing, TV, and audit maturation

- Resurface withheld backend-backed movie lanes into the new workbench shape once stable.
- Harden the audit / receipt system across resurfaced workflows and keep its storage, follow-up semantics, and reading model coherent.
- Add the **TV Show Normalize** lane as the next major product family inside the same workbench grammar.
- Keep apply safety, source-root validation, and preview discipline consistent across movie and TV mutation paths.

- **Series and season structure** — target shape `Show Name (Year)/Season NN/Show Name - SNNENN - Episode Title.ext`; fall back to the smallest safe default when episode titles are unavailable.
- **Episode parsing** — `S01E02`, `1x02`, season-folder, absolute anime-style, specials, multi-episode, and messy release-token inputs handled without remote metadata as a hard dependency.
- **Package cleanup** — adapt movie artifact cleanup for TV extras, samples, empty season folders, duplicate wrappers, and season-pack folders.
- **Apply safety** — reuse the movie normalizer's preview/apply discipline: no silent destructive execution, review for ambiguity, source-root validation on every moved or deleted path.

## 0.9.x — Post-resurfacing polish and stabilization

- Histogram improvements — interactive drilldowns into a selected curve segment, first as a compact overview, then a detailed list.
- Canonical-list badge and inspector refinements.
- A UI consistency and colour-logic pass once the resurfaced lanes and TV shape are settled.
- Remaining parser edge cases and normalization ambiguities across both lanes.
- Minor underdeveloped-feature polish after the new audit system and resurfaced workflows land.

## 1.0 — Release readiness

Both lanes stable, with a clear, distinctive identity: folder and tagging quality management for movies and TV, with no adequate free analogue.

- All lane workflows stable and hardened.
- Packaging and onboarding — lightweight launcher, local API-key onboarding flow.
- Version metadata cut to `1.0.0`.

---

## Later candidates

- **Rust core feasibility pass** — once `normal` reaches a stable alpha/beta shape, evaluate whether a small set of pure-core subsystems should move into Rust behind a narrow Python boundary. Current likely seams are streamed path walking and media discovery (`movie_scan.py`), scan-result and plan modelling (`models.py`, shared scan/profile payloads), cache invalidation and probe-cache mechanics (`probe_cache.py`), parser/token logic (`movie_identity.py`, `movie_naming.py`), and selected plan-generation hot paths (`movie_plan.py`). This is explicitly **not** a full application rewrite: Python remains the orchestration and UI layer unless a later spike proves a broader port is worth the added build, packaging, and contributor-complexity cost.
- **Feasibility bar** — run this as a bounded evaluation: identify which pure-core seams can plausibly move to Rust, measure whether doing so yields meaningful benefits in performance, scan economics, or implementation clarity, and proceed only where those benefits justify the added build, packaging, and parity-maintenance cost. This still depends on the product shape having settled enough for a stable boundary and on the Python implementation being covered well enough to verify behavioral parity.
- **Extract inline JS from web.py** — move the ~5000-line inline `<script>` block into a proper `.js` file (or a few). No architectural overhaul; the goal is editor tooling — symbol search, go-to-definition, linting. The current blob is workable but makes wiring bugs slow to diagnose.
- **Catalogue merge / swap report** — import another user's exported catalogue, compare shared movies, and suggest swaps where one library has a stronger encode.
- **Plex Compatibility workflow** — heuristic findings already exist in `movie_profile.py`; the UI stays hidden until the workflow shape is clear.

## Disclaimer

`normal` is pre-`1.0`. The current version story was reconstructed from commit history and diff/change logs. The first real release is `v0.7.0-alpha.1` and the current release is `v0.7.0-alpha.9`; both carry matching prerelease intent. Earlier `CHANGELOG.md` sections remain reconstructed history rather than tagged releases.

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
