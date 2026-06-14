# Changelog

This changelog was retroactively rebuilt from commit history and diff/change
logs. Real release history starts at `v0.7.0-alpha.1`, with a matching git tag
and GitHub prerelease. Earlier sections remain reconstructed history.

## [0.7.0-alpha.9] — 2026-06-15

### Changed

- **Deployment and runtime assumptions are explicit.** Native CI now covers
  Linux, macOS, and Windows, including an installed-wheel web-server smoke test,
  while Python support remains bounded to the tested 3.12–3.14 range.
- **User-owned state is centralized.** Credentials, policy, audit, cache,
  replacement, history, and corpus data resolve through the shared user-data
  path module instead of relying on working-directory or platform-specific
  assumptions.
- **Remote web access has one coherent trust model.** Non-loopback binding
  requires explicit unsafe-remote intent, trusted host/origin configuration,
  and an allowed peer network; host-local access remains the safe default.
- **Source and mount policy is shared across CLI and web workflows.** Heavy
  scans and mutations use the same approved-root, whole-drive, mount, network
  share, symlink, junction, and containment rules across supported platforms.

### Fixed

- Mutating web requests now reject malformed routes, oversized or invalid
  bodies, untrusted peers, hosts, and origins before dispatch; destructive
  operations are serialized server-side.
- Rename, move, merge, repair, and folder-cleanup paths are revalidated at
  mutation time so stale plans and path escapes cannot cross the approved
  source boundary.
- Safe-only apply behavior is enforced by the server-owned plan rather than
  trusted from client input, and persisted library roots must pass source
  approval before reuse.
- Installed wheels now exercise the packaged web server in CI, including its
  bundled assets and runtime path assumptions.

## [0.7.0-alpha.8] — 2026-06-14

### Added

- **Format Upgrade Candidates.** The Immersive Audio workflow received an unexpected injection of horse steroids. What started as a way to answer "is this title available in an object-based mix?" is now a reference and look up Matrix that ponder questions about *release traits* — **immersive audio** (Atmos / DTS:X), **UHD**, **Dolby Vision**, **Open Matte**, and **Hybrid** — answered against a local corpus and your own copies. Renamed to **Review Format Upgrade Candidates**. Each title gets one row per feature with three columns that read as a sentence: **Known Release** (what the corpus knows exists), **Corpus Verdict** (the resulting upgrade opportunity — found, partial, already covered, none known, conflicting, research needed), and **Your Copies** (local coverage). Want to know whether your copy of *The Matrix* secretly has a Dolby Vision release available now? It will tell you "yes" because it knows this from its knowledge corpus. Whether that 7.1 copy of *Top Gun: Maverick* is actually Atmos? It will tell you no by reading from the metadata of the file. Each trait stays gated on real evidence, so a lossy core can't masquerade as a tracked object.
- **Evidence-backed trait assessments.** Every claim now carries a basis (local probe, curated research, manual verification, imported or user report) and a reliability grade, and the verdict honours them. A filename that asserts a feature it can't substantiate reads as *needs corroboration* rather than being trusted, and Open Matte / Hybrid claims in particular require corroboration before they count.
- **Weak-encode badges + Fun Mode.** Review Low-Quality Encodes gains a badge column that names *why* a file is weak, with a global **Fun Mode** operator preference that toggles the playful voice on those badges across the workbench.
- **Known-moron encoder badges.** A file whose name still carries a known-bad release group or uploader (YIFY / YTS, MkvCage, and friends) earns a **Known moron** badge — or a softer **Suspect encoder** for hit-or-miss groups. This is an editorial track-record verdict layered over the existing diagnosis, never a detector of its own. Seeded from a versioned data file.
- **Lopsided encode detection.** A new weak-encode check flags files where one stream is fine and the other is starved — a reference-grade video welded to a 96 kbps down-mix, or lossless audio laid over a smeared transcode — with a configurable imbalance threshold in library policy.
- **Reclaimed-space chip** in the weak-encode and repair previews, so the space a delete or repair would free is visible before you confirm.

### Changed

- **Python support is explicit and bounded.** 3.12, 3.13, and 3.14 are tested targets; packaging rejects unvalidated 3.15+ installs until that runtime is added to CI.
- **XLSX export loads lazily.** `openpyxl` is imported only when catalogue export actually runs, so an incomplete environment leaves every other workflow available and reports the exact install command needed to restore it.
- **Trait/immersive seeds moved to a versioned data file** under `normal/data/` with provenance, instead of being inlined in code.
- Workbench typography and table palette restyled for a calmer local-first read; shared table spacing and the foundation column unified across lanes.
- Normalize's Projected Path column now delineates folder from file.
- Probe-cache writes are batched per scan instead of saved per file.

### Fixed

- Wheel packaging now ships the `normal.web` subpackage and its bundled assets, so a wheel install launches the web UI correctly.
- The low-audio weak badge no longer fires on codec-floor-only misses.
- Lopsided-encode review routing and cache invalidation corrected.

## [0.7.0-alpha.7] — 2026-06-12

### Added

- **Immersive Audio workflow.** `normal`'s most ambitious feature. Crowdsources whether a title is available in an object-based immersive mix (Dolby Atmos / DTS:X) — a fact no scanner can read off a library, nor can it be pulled or farmed from any poblically available API. This painful reality get solved in an interesting way, which draws inspiration from RateYourMusic and other user-driven approaches: `normal` pairs local-probe facts (carrier codec, channel layout) with a seeded, extendable corpus of titles known to have or lack an immersive release, framing each row as an upgrade candidate. A tri-state **Status** column (available / not available / unknown) backed by local-probe telemetry replaces manual per-title voting. Atmos/DTS:X crediting is gated on the actual carrier codec so a lossy core can't sneak in as a tracked object. Verdict surface split into Status, Audio, and Quality Profile columns. Sits ahead of Canonical Lists in the menu, flags non-normalized rows with normalization tooltips, and emits coloured Telemetry Vote audit events.
- **Crowdsource Of Truth.** Over time the "Crowdsource of Truth" grows as new users come online and scan their libraries. Each scan that hits a file with Atmos confirms or teaches the network a fact: this Title (Year) *does have Atmos available as a matter of scanned and confirmed fact*. It does not care for or ponder who the user is: but emits a "vote" (if allowed in settings) to the corpus body confirming that fact. Any 'fact' of a title having object Audio submitted to the corpus body will immediately overwrite a fact that claims otherwise to allow the body to grow and stay current to new releases. Even a relatively small number of users with reasonably large collections could in theory form a very strong (~99+%) detection net against the entire known release corpus of Object Based Audio UHD releases. A hard scraped seed list of roughly 140 'facts' is provided to bootstrap the corpus body and make the UI not feel stupid while knowledge levels are low and being built through opt-in telemetry.
- **Cold-start onboarding gate:** a first-run surface holds the workbench until library context is established instead of dropping the operator into an empty shell.
- **Weak-encode triage score:** low-quality encodes carry a composite score that highlights the offending axis (resolution, bitrate, codec), with a hover explainer on the Triage column header.

### Changed

- **Replacement queue** is back online and integrated with the unified audit ledger. Weak-encode and audio deletes flow into the queue and reconcile against it as "deleted, awaiting replacement" items under the same ledger as the rest of the workbench. Pre-merge replacement lists are migrated forward in place.
- Title-key canonicalization is stronger: key folding normalizes accents and `&`/`and` and bridges roman/arabic numerals, so a film matches across edition and numbering variants. (Seed match-safety round-trip verification still outstanding.)

### Fixed

- `N/A` language and digit-infix title morphs no longer short-circuit the audio-repair path causing a planner subtitle recommendation out of sync with user policy.
- ffprobe tag keys are read case-insensitively, so tags differing only in case are no longer missed.
- Weak-delete preview refreshes correctly; junk-preview destructive grammar unified with the other delete surfaces.

## [0.7.0-alpha.6] — 2026-06-09

### Added

- **API keys now live in the product.** A **Settings** surface manages the optional OMDb/TMDb enricher keys via a process-wide credential store rather than launch-time environment plumbing. The store is seeded from the environment at boot and read live on every request, so a pasted key takes effect without a restart, and it persists to `~/.local/share/normal/secrets.env` (`0600`, env-style) so the key has a durable home. The full key never round-trips to the browser — the read API (`/api/settings/read`, `/api/settings/keys`) exposes only presence, the last four characters, and the source. Covered by tests.
- **mkvpropedit fast lane for disposition-only repairs.** Subtitle/audio `default`/`forced` flags are MKV header metadata, so flipping them never needed a full remux. When a repair's only changes are disposition flips, `build_execution_plan` marks the work `metadata_only` and routes it through the new `mkvpropedit_fix` module, editing the header in place and verifying by re-probe — roughly 0.2 s on a 6.6 GB file instead of a full rewrite. The named-flag mechanism also preserves `forced` when setting `default`, avoiding the whole-disposition-replace footgun of the remux path. ffmpeg remains the path for structural repairs (foreign-audio prune); a missing `mkvpropedit` falls back to ffmpeg automatically.
- Forced-subtitle detection by disposition: `ffprobe` reads `stream_disposition=default,forced`, so a forced track carrying a plain `English` title with no "Forced" text is recognized by its disposition bit. (Bumps the probe cache to v3, forcing one cold rebuild.)
- Conservative detection of non-English default audio: without an enricher key, language resolution flags non-English defaults conservatively rather than asserting a wrong default it can't prove. The foreign-original-with-packaged-English case is a deferred design note.

### Changed

- Multi-file repair gate keys on real remux cost, not file count. Disposition-only flip batches — the common case — skip the heavy two-step warning and chain freely; dropping foreign audio is the sole trigger for a true remux, where the gate still fires.
- Setting a default no longer strips a track's forced flag. ffmpeg's `-disposition` replaces a stream's entire disposition set, which had been clearing the `forced` bit and causing files to flip-flop between "make forced default" and "clear default" on each scan. `subtitle_disposition_value()` now rebuilds the disposition preserving each stream's original `forced` bit while flipping only `default`, wired into the combined and subtitle-only paths with regression tests.
- Remux queue progress is tracked by file path, not card position. The backend doesn't walk the queue top-to-bottom, so DOM-position inference falsely marked cards complete; completion now follows the activity focus by path and stays truthful regardless of order.

### Fixed

- Repair progress reads as motion instead of a dead stop: a front-end fill paced from file size, eased to plateau at 88% so it can't false-complete, with an 88→96% "finalizing lossless mux" crawl on I/O troughs and the snap to 100% reserved for real completion. No backend changes.
- Canonical Lists no longer reports itself inactive when `IMDB_DATASET_DIR` is unset. The backend self-manages the dataset under `~/.local/share/normal/imdb-datasets/`; readiness now checks the managed files and honors the variable only as an override.
- The rail no longer clips its lower icons on an empty surface — it sizes to its own content in both modes, and the orphaned empty rail body and its CSS were removed.

## [0.7.0-alpha.5] — 2026-06-07

### Added

- Movie repair planning/execution seam now powers `Fix Audio and Subtitle Defaults`. Rows carry explicit audio, subtitle, and combined repair plans, and the backend can execute one combined remux pass when an audio-default change also alters the correct subtitle-default outcome.
- `/api/movies/repair-defaults/fix` unified repair-defaults mutation route, replacing the older per-family paths.
- Audit reads expose ledger revision metadata and the latest system-start context, plus an `/api/audit/stream` SSE route so the workbench reacts to ledger changes without polling.
- User-adjustable safety gating policy.

### Changed

- Root workbench is stricter about consequence ownership. Normalize Naming drops the `Preview Scope` toggle, and the preview pane no longer implies a distinct full-library preview mode when the real action is still row selection.
- Uniform downstream preview semantics across the shell: normalize, junk cleanup, weak-encode delete, and repair-default flows all use the same staged model — select rows, inspect the staged consequence, confirm.
- `Fix Audio and Subtitle Defaults` UI hardened: labels, selection, applicability reporting, row refresh, combined-action wording, and repair-lock behavior tightened so mixed audio/subtitle work reads as one lane, with clearer preview semantics for multi-file and multi-package changes.
- Audit Ledger UI gains richer events for remux jobs that chain multiple actions, better table spacing and labelling, and an inline cell dropdown for multi-stage inspection.
- Subtitle policy moved into explicit library policy controls for English-audio and non-English-audio cases; the editor treats language and subtitle defaults as their own playback-policy section.
- Library policy exposes a warning-gate safety level, separate from the core quality and delete defaults.
- Canonical lists refreshed: `Animation` and `Documentary` use 100-title shapes, `Drama / Romance` added, and IMDb genre matching is stricter for hybrid lists so multi-genre categories don't degrade into loose any-genre buckets.
- Delete and repair routes preserve richer downstream metrics: junk deletion tracks deleted-media size, repair flows summarize removed foreign-audio tracks and bytes, and updated profile items are rebuilt from post-fix facts so mutated rows refresh directly.
- Resolution breakdown uses a general display-shape taxonomy across HD and UHD buckets, giving cleaner letterbox/anamorphic distinctions.
- Release truth surfaces advanced to `alpha.5` across package metadata, workbench chrome, roadmap status, and the release docs set.

### Fixed

- Removed dead frontend wiring for the old preview-scope selector and its library-mode branches.
- Audit-store reads reuse cached ledger and follow-up state until the ledger changes, reducing repeat parsing.
- Library-improvement totals still count delete effects on older audit events that lack the newer `deleted_media` payload, keeping removal progress coherent across mixed history.

## [0.7.0-alpha.4] — 2026-06-05

### Added

- A persisted audit ledger now tracks system start, scans, normalize apply actions, media deletes, junk deletes, repair actions, exports, policy updates, and follow-up state changes through one source-scoped read surface in the main workbench.
- The workbench now exposes an Audit surface and library-improvement summary signals, including file removals, removed audio tracks, scan count, and Top 500 progress above the active weak-floor policy.

### Changed

- The root workbench is now the only active web shell. Old parser-tester routes and their packaged assets were removed, and workflow deep links now use `/?workflow=...`.
- Canonical Lists now defaults to a local IMDb-dataset provider with consensus-weighted ranking, per-provider caching, automatic dataset refresh support, and TMDb retained as an explicit fallback provider.
- Library policy now includes a canonical-list provider selector under `Library Defaults`, allowing the default IMDb path or explicit TMDb routing without adding a separate workflow.
- Canonical list coverage now includes `Top 500`, which also feeds the new library-improvement progress metric.
- Web scan surfaces now carry richer inspection context without reviving the older multi-shell UI split. Some scan performance was intentionally traded back to support the restored audit and inspection depth, while warm-cache maintenance scans remain fast.

### Fixed

- Junk deletion now writes durable audit events instead of remaining a session-only history gap.
- Legacy replacement-queue and subtitle-fix history can now be migrated into the unified audit ledger instead of remaining isolated state islands.

## [0.7.0-alpha.3] — 2026-06-04

### Changed

- The compact movie workbench now exposes a left-side `Policy` rail as the sole write owner for library policy and operator delete posture. Weak-floor and related policy edits are no longer separate ad hoc controls.
- Policy persistence is now split cleanly: repo-local library policy continues to live in `movie_standards.json`, while user-local operator preferences are stored separately under `~/.local/share/normal/operator-preferences.json`.
- `Repair Defaults` in the compact shell is now one unified repair lane rather than a tab switcher. Audio-default and subtitle-default issues can be staged through one shared table and combined repair actions.
- Delete-capable web routes now honor a shared delete posture resolver. Media, junk, safe sidecars, and empty folders can be recycled or hard-deleted according to the configured operator preference, including the two hybrid modes.
- The compact shell preview surface now yields to policy editing mode. Opening policy expands the left rail into the main work area, suppresses preview/action controls, and uses the right pane for reduced inspection instead.
- The deprecated alternate workbench route and its static assets were removed. The compact root-shell and parser-tester shell are now the only active web UI surfaces in this slice.
- Normalize cleanup now treats obvious no-video junk residue folders as safe delete candidates when they only contain disposable metadata or promo-document residue.
- Web asset serving now appends hash-based cache-buster query strings and returns `Cache-Control: no-store` headers for the HTML and packaged asset routes to reduce stale local UI loads during active iteration.

### Fixed

- Repair-lane actions no longer split ownership awkwardly between audio and subtitle sub-tabs. Shared rows now classify by issue family and refresh correctly after mixed repair actions.
- Destructive cleanup helpers no longer bypass the configured delete posture when removing safe sidecars or emptied folders after file deletion.

## [0.7.0-alpha.2] — 2026-06-02

### Changed

- `/` and `/index.html` now open the new compact movie workbench directly. The former parser testing shell is the default alpha.2 UI, while the old dashboard is no longer the active public entry surface.
- The promoted alpha.2 workbench no longer frames itself as an internal tester. Normalize, Weak Encodes, Repair Defaults, and Junk now read as the main movie workflows inside one compact shell.
- Alpha.2 publicly narrows the surfaced product while the interface consolidates. Some lanes and audit surfaces that existed in alpha.1 remain present in backend or partial internal form but are intentionally not exposed in the default UI yet.
- Movie quality profiling now has an explicit `Compact Grade` stance between the weak catch-all bucket and `Library Grade`, giving the dashboard and Weak Encodes testing UI a saner middle band for benign compact encodes.
- The former bottom stance is now framed as a true fallback bucket rather than a strict threshold profile. In the dashboard editor it only exposes card label and summary, removing the previous illusion that its numeric controls were authoritative while it still functioned as the unconditional catch-all.
- Quality profiles now support an `Allow original mono before year` control. When enabled for a stance, pre-cutoff mono titles can satisfy that stance without being penalized for missing stereo/surround channels, and the audio bitrate floor is relaxed to a mono-aware threshold for those exempt titles.
- Movie profile probing now keeps all `main audio` facts aligned to the same chosen playback-relevant stream instead of mixing first-stream codec/channel metadata with default-stream bitrate/summary data. This removes a misleading weak-encode edge case where multi-audio MKVs could look internally contradictory in scans and tables.
- `/parser-tester-ui?workflow=weak-encodes` now lets the audio bitrate cell open a small anchored track inspector showing every audio stream's language, bitrate, channel layout, and default flag without disturbing table shape.
- The promoted workbench exposes a fourth workflow, `Repair Defaults`, so audio-packaging and subtitle-default repair behavior can be inspected in the same focused shell as normalize, weak-encode, and junk triage.
- Weak-encode triage now has a clearer ownership boundary: files with a good in-container English track but wrong default-language packaging no longer count as strict weak delete candidates, and the weak-floor selector defaults to the weakest safe posture (`Standard Definition`) rather than inheriting a harsher library-grade floor.
- Resolution bucketing now uses display-class semantics when stream aspect metadata supports it. Cropped widescreen HD encodes like `1920x796` remain `1080p`, anamorphic HD encodes like `1440x1080` can classify as `1080p`, and malformed or missing aspect metadata still falls back to the old raster-based bucket.
- Web frontend extracted out of `normal/web.py` into package-managed assets under `normal/web_assets/`. The stdlib `http.server` backend remains in place, now serves `/assets/app.css` and `/assets/app.js`, and injects only a small runtime bootstrap into the HTML shell instead of carrying the full UI inline.
- Web packaging and tests updated to match the split frontend layout. `pyproject.toml` now includes the packaged web assets, and web-layer tests now assert against asset content and static-asset serving instead of a single embedded HTML constant.
- Movie normalize parser hardening is now framed around preserving the settled concise movie target shape rather than exploring alternate outputs. The current objective is explicit regression defense against the already-good `Title (Year)/Title (Year).ext` library state.
- Movie normalize parser hardening now strips leading site/uploader credit noise more reliably, keeps safe language and edition tokens like `PORTUGUESE` and `International Cut`, and promotes committed round-2 corpus regressions into tests.
- Shared title cleanup now safely normalizes obvious all-caps movie names, while the generic domain-credit stripper is more conservative at TLD word boundaries so real titles like `Bone Tomahawk` no longer lose leading text to false `.to` matches.
- Shared tracker/domain-credit stripping now also accepts bracketed tags with internal whitespace, so cases like `[ OxTorrent.com ] Apollo...` collapse to the same settled title shape as the already-supported compact bracket forms.
- Shared movie title punctuation hardening now also repairs compact leading `K19` forms into the existing settled `K-19: ...` family for normalize and OMDb lookup candidates, while leaving broader branded-hyphen recovery out of scope.
- Movie normalize tail-token confidence is now structure-aware rather than length-only. Long unknown edition-style words no longer force `review` when the same tail already contains enough recognized packaging evidence, and `DTS-HDMA` now normalizes as valid `DTS-HD MA` structure.
- Movie normalize collision handling now tries safe alternate concise targets before falling back to review. Existing-target clashes can be auto-split with technical differentiators or local package labels, while root-level duplicates without extra local evidence still stay in review.
- Normalize web payloads now build only the requested naming style, precompute parsed identities once per request, and serialize movie rows through indexed change/warning lookup instead of reparsing and rescanning per movie. On the reference mounted library this cut normalize from minute-scale behaviour back down to a few seconds.
- Web normalize surfaces now treat concise naming as the active product path. The main UI, workbench, and `/parser-tester-ui` no longer build or switch dual style payloads on every request, though verbose parsing support remains in the planner and test corpus for legacy artifact cleanup and regression coverage.
- `/parser-tester-ui` now exposes linked change reasons and warning messages in the detail pane, keeps staged and full-library downstream preview modes, and can confirm selected normalize changes directly through the same `/api/movies/apply` path as the main UI.
- `/parser-tester-ui` confirm selection now also carries safe wrapper `folder_delete` cleanup when every actionable row under a split package folder is selected, closing the gap where successful movie moves could still leave behind an empty collection wrapper.
- The old parser-tester selected-row export endpoint was removed. The promoted workbench now validates parser output by previewing and confirming the real normalize mutation contract instead of exporting rows to a side artifact.

---

## [0.7.0-alpha.1] — 2026-05-23

### Added

- Persistent file-level probe cache (`ProbeCache` in `probe_cache.py`). All ffprobe results are cached to `~/.local/share/normal/probe-cache.json`, keyed by `(path, mtime_ns, size_bytes)`. Shared across all scan workflows (profile, junk, catalogue export, inspect). After a cold first scan, subsequent scans re-read from disk instead of spawning ffprobe, reducing a ~330s full-library walk to ~5s on the next server start. Automatically invalidates per file when mtime changes (e.g. after an audio or subtitle fix).
- Server-side movie profile cache (`MovieProfileCache`) in `web.py`. Dashboard, Delete Weak Encodes, Fix Multi-Audio Packaging, and Repair Subtitle Readiness all draw from a single cached `MovieProfileReport` per source root. Subsequent navigations between these four pages return in under a second instead of re-running a full ffprobe sweep each time. The cache is explicitly invalidated after file-mutating operations: `handle_movies_apply` (renames), `handle_movies_audio_packaging_fix` (when files were fixed), and `handle_movies_subtitle_readiness_fix` (when files were fixed). No TTL — cache persists for the server session and is only cleared by explicit invalidation.
- `reclassify_report_with_standards(report, standards)` added to `movie_profile.py`. Rebuilds all `MovieProfileItem` objects from their cached `MediaFacts` against a new standards dict without running ffprobe. Not currently called from the web layer (standards saves are now instant and defer reclassification to the next scan), but available for future use.

### Changed

- Fix Multi-Audio Packaging and Repair Subtitle Readiness merged into a single **Repair Defaults** page with a shared scan and two sub-tabs. Previously required two separate scan cycles; one scan now feeds both tabs and the user switches between them without re-probing.
- Junk video detection and promo/sidecar document cleanup merged into a single combined scan (~12 s vs ~2 min previously). `POST /api/movies/junk` returns both video junk and document junk in one response; the UI presents them as two detail panels from the same scan result.
- Canonical lists swapped: `top_1000` and `suspense_horror` removed (poor fit for the reference library); `animation` (Animation, TMDb genre 16, 60%) and `documentary` (Documentary, TMDb genre 99, 60%) added.
- Quality profile definition saves are now instant and trigger no scan. `POST /api/movies/standards/update` writes `movie_standards.json` and returns the updated definitions; the browser patches `state.results.movies.profile` in-memory and re-renders immediately. Profile counts and classifications remain as of the last scan and update the next time the user initiates one. The previous behaviour — a full 300-second ffprobe rescan triggered by every save, including cosmetic edits like removing a full stop from a description — is removed.
- Movie profile scan activity indicator now correctly terminates when the last file is probed. Response serialisation (`asdict` on the full `MovieProfileReport`, histogram aggregation, replacement queue reconciliation) was moved outside the `ActivityTracker` context, eliminating the previous "stuck with no filename" appearance during the post-scan serialisation phase.
- `build_movie_plan` now accepts an optional `movie_files: list[Path] | None` keyword argument. When provided, internal `discover_video_files` call is skipped. `handle_movies_normalize` and `handle_movies_apply` pass a single pre-discovered file list to all per-style plan builds, reducing the previous three redundant directory walks to one. Observed normalize scan time dropped from ~2 minutes to ~42 seconds on the reference library.
- Server-side OMDb rating cache and lookup endpoint for movie replacement history.
- Repo-local agent guidance for the intended `unittest` test runner.
- Movie normalization naming-style controls: concise `Title (Year)` output is now the default, with verbose technical-token naming retained as an option in the web UI and CLI.
- Movie normalization can split locally-evidenced multi-movie package folders into individual movie folders.

### Changed

- Movie normalization now resolves concise same-title/year duplicates with the shortest parsed differentiator available, usually resolution, at both folder and file level.
- Movie normalization is now treated as product-complete for movie libraries; verbose naming is documented as temporary parser-hardening scaffolding scheduled for removal.
- Roadmap now tracks the two pre-refactor paths: remove verbose movie naming, then add a TV Show Normalization lane.
- Quality Profile card editing no longer exposes per-profile allowed audio codecs, and quality-profile matching no longer gates on those per-profile codec lists.
- Dashboard movie profile scans now show streamed forward progress in the activity bar: processed file count, current probe target, elapsed time, and ETA only when a bounded total is known.
- Movie replacement-history IMDb ratings now use local title cleanup and search fallback, and no longer expose the OMDb key to the browser.

### Fixed

- Formerly open movie-scan cancellation rough edge is no longer tracked as an active concern. The scan-control hardening around cancellation, incremental traversal, and probe lifecycle has been stable in real use, including the earlier path where a cancelled scan could occasionally leave a background `ffprobe` behind.
- `reconcile_replacement_queue` was calling `replacement_identities` (an O(library-size) walk with `path.resolve()` per file) once per replacement-queue item rather than once per issue family, due to Python's eager evaluation of `dict.setdefault` defaults. On a 973-movie library with a large queue this added ~194s to every profile response. Fixed by guarding with an explicit `if family not in` check.
- IMDb rating availability on fresh web UI load.
- Movie name normalization now handles mixed-script title prefixes, `Director's Cut`, compact `BluRayRemux` tokens, language tags like `3Rus Eng`, hyphenated release groups like `CME-v0`, technical tokens before trailing parenthesized years, and the `Blauray` typo.
- Movie name normalization now deletes empty package artifact folders, handles nonstandard resolution differentiators such as `1072p`, trims verbose uploader/language/audio noise, and preserves useful edition/video tokens such as `Open Matte`.
- Repair Subtitle Readiness table now shows movie title and year (e.g. `Alien (1979)`) instead of the raw file path.
- Downstream Plex client subtitle-default changes are verified working without cache invalidation issues.

## [0.6.3] — 2026-05-12

Hardening pass for movie dashboard state, profile persistence, and scan-derived
rendering.

### Added

- CLI module entrypoint guard.
- Environment-backed web UI launch contract documentation.
- Movie histogram architecture notes for future agents.

### Changed

- Movie replacement candidates now derive from the saved quality-profile cutoff.
- Movie bitrate histograms stay in sync after partial profile mutations.
- Movie junk workflow results are isolated between junk-video and promo-document lanes.
- Movie profile bars scale by total count.

### Fixed

- Movie standards saves use persistence hardening and stale-write protection.
- Dashboard refresh preserves in-progress movie profile drafts.

---

## [0.6.2] — 2026-05-11

Quality-profile editor refinement.

### Added

- Vintage audio exemption controls for pre-surround-era films.

### Changed

- Quality-profile editor inputs use clearer option controls.

### Fixed

- 1080p widescreen films no longer fall into the 720p resolution breakdown.

---

## [0.6.1] — 2026-05-11

Movie dashboard quality-profile reframing.

### Changed

- Dashboard separates action-oriented cards from quality-profile cards.
- Movie profile classification and dashboard rendering were aligned around the
  current standards model.

---

## [0.5.0] — 2026-05-11

Subtitle readiness repair lane.

### Added

- **Repair Subtitle Readiness** repairs embedded subtitle default flags for
  supported MKVs with a lossless remux.
- English-audio files clear subtitle defaults; non-English-audio files prefer
  forced English or English subtitles when available.

---

## [0.4.0] — 2026-05-11

Dashboard-owned movie standards.

### Added

- Dashboard View standards cards show rule summary, movie count, and inline
  editing controls.
- `movie_standards.json` persists quality-profile definitions and replacement
  candidate cutoff.

---

## [0.3.2] — 2026-05-11

Movie audio summaries across outputs.

### Added

- Movie scan, web tables, CSV export, and XLSX register show normalized
  main-audio summaries such as `AAC 2.0`, `Dolby Digital 5.1`, and
  `DTS-HD MA 5.1`.

---

## [0.3.1] — 2026-05-08

Movie web UI and documentation refinement.

### Changed

- Movie UI copy, layout, and docs were tightened after the first Canonical Lists
  pass.

---

## [0.3.0] — 2026-05-07

Canonical Lists coverage workflow.

### Added

- **Canonical Lists** compares owned titles against live all-time movie lists
  using TMDb and a local cache.
- First-pass coverage badges show basic ownership progress.

---

## [0.2.2] — 2026-05-07

Movie replacement queue hardening.

### Added

- Inline dismiss action for deleted queue rows that are not worth replacing.
- Replacement queue history filters: `Deleted, Awaiting Replacement`,
  `Replaced`, `Deleted From Queue`, and `All Items`.

### Changed

- Movie replacement-queue state persists across hard refresh for the same source.
- Fix Multi-Audio Packaging locks selection and action buttons during active
  remuxes.
- Destructive delete action moved away from repair actions.

### Fixed

- Movie replacement-queue delete treats already-missing media as already deleted.
- Movie replacement history grouping was corrected.

---

## [0.2.1] — 2026-05-06

Movie audio remux repair.

### Added

- Lossless MKV repair can make the best English audio track default.
- Optional stricter repair can drop tagged foreign-language audio while keeping
  English and untagged audio.

---

## [0.2.0] — 2026-05-06

Movie multi-audio packaging triage lane.

### Added

- **Fix Multi-Audio Packaging** detects wrong default audio language and weak
  English fallback cases.
- Multi-audio triage shares the movie profile scan and replacement queue
  substrate with weak-encode triage.

---

## [0.1.2] — 2026-05-05

Movie replacement queue rating context.

### Added

- IMDb rating column for deleted movie replacement queue history when an OMDb
  API key is configured.

---

## [0.1.1] — 2026-04-30

Early documentation and UI polish.

### Added

- Dashboard screenshots.
- Web UI themes.
- New onboarding and safety documentation polish.

---

## [0.1.0] — 2026-04-30

Initial release.

### Music lane

- Scan FLAC libraries for tag, filename, and folder inconsistencies.
- Generate reviewable change plans with `safe` / `review` confidence levels.
- Apply plans to a new target directory or in-place with explicit opt-in.
- Artist name deduplication across case and `&` / `and` variants.
- Dashboard profile view for format mix, fidelity distribution, and artwork readiness.
- Repair artist artwork for Jellyfin with candidate preview and approve/write flow.
- Jellyfin artist metadata sync to push library sidecars into Jellyfin cache.
- CSV collection export.

### Movie lane

- Normalize movie file and folder names using local title/year parsing.
- Encode quality profiling against a resolution-gated quality ladder.
- Weak encode triage with persistent replacement queue tracking.
- Junk video detection for samples, featurettes, and shorts under 5 minutes.
- Promo document cleanup for sidecar `.txt`, `.html`, and `.htm` files.
- Dashboard view for quality tier distribution, bitrate histograms, and resolution breakdown.
- XLSX catalogue export.

### Web UI

- Local-only HTTP server using the Python standard library.
- Library Switcher for Movies and Music lanes.
- Source path auto-detection from path segments.
- Music pages: Dashboard, Normalize, Repair Artwork for Jellyfin.
- Movie pages: Dashboard, Normalize, Delete Weak Encodes, Fix Multi-Audio
  Packaging, Delete Junk Videos, Delete Junk Sidecar & Spam Files, Export Catalogue.
- Per-page ETA estimation persisted in localStorage.
- Abort support for in-flight scans.

---

<sub>Authorship: **Agent-written** — see the [authorship policy](docs/writing.md).</sub>
