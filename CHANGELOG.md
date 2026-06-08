# Changelog

This changelog was retroactively rebuilt from commit history and diff/change
logs. Real release history starts at `v0.7.0-alpha.1`, with a matching git tag
and GitHub prerelease. Earlier sections remain reconstructed history.

## [Unreleased]

## [0.7.0-alpha.6] — 2026-06-09

### Added

- **API keys now live inside the product.** A new **Settings** surface on the workbench rail manages the optional OMDb/TMDb enricher keys, backed by a process-wide credential store rather than launch-time environment plumbing. The store is seeded from the environment at boot and read live on every request, so a pasted key takes effect immediately without a restart, and it persists to `~/.local/share/normal/secrets.env` (`0600`, env-style) so the key has a durable home instead of vanishing with the shell session — ending the "where did the key go" problem. The full key never round-trips to the browser: the read API (`/api/settings/read`, `/api/settings/keys`) exposes only key presence, the last four characters, and the source, and the no-leak guarantee plus the `0600` permissions are covered by tests.
- **An mkvpropedit fast lane for disposition-only repairs.** Subtitle and audio `default`/`forced` flags are MKV header metadata, so flipping them never actually needed a full container remux. When a repair's only changes are disposition flips — no track drop, no transcode — `build_execution_plan` now marks the work `metadata_only` and routes it through a new `mkvpropedit_fix` module that edits the header in place and verifies the result by re-probe. The practical difference is large: a flag flip on a 6.6 GB file completes in roughly 0.2 s in place instead of rewriting the whole file. The named-flag mechanism is also structurally safer than the ffmpeg path — it sets specific flags, so it preserves `forced` when setting `default` and cannot commit the whole-disposition-replace footgun the remux path has to guard against. ffmpeg remains the path for structural repairs (foreign-audio prune), and a missing `mkvpropedit` falls back to ffmpeg automatically.
- **Forced-subtitle detection by disposition, not just title text.** `ffprobe` now reads `stream_disposition=default,forced`, so a forced English track that carries a plain `English` title with no "Forced" text is recognized via its disposition bit rather than slipping past a title-regex match. (This bumps the probe cache to v3, forcing one cold rebuild.)
- **Conservative detection of non-English default audio.** Language resolution now feeds default-audio correctness; without an enricher key it falls back to flagging non-English defaults conservatively rather than asserting a wrong-default it cannot prove. The harder false-positive case — foreign-original films that ship a packaged English track — is captured as a deferred design note, deliberately not yet implemented.

### Changed

- **The multi-file repair confirmation gate now keys on real remux cost, not file count.** The gate previously warned of "ffmpeg remux workloads, 1–10 min per movie" on any multi-file batch, including disposition-only flips that the fast lane resolves in milliseconds. It now branches on whether the selected action will actually rewrite containers: dropping foreign audio is the sole trigger for a true remux, so all-flip batches — the common case — skip the heavy two-step warning entirely and chain freely, while the gate still fires for genuine remux work.
- **Setting a default no longer strips a track's forced flag.** ffmpeg's `-disposition` replaces a stream's entire disposition set, so the repair that set a forced English subtitle as default was silently clearing its `forced` bit. Combined with the new forced-by-disposition probing, the post-fix re-probe then saw `forced=0`, found no forced track to target, and reclassified the file — leaving it to flip-flop between "make forced default" and "clear default" on every scan. A new `subtitle_disposition_value()` rebuilds the disposition preserving each stream's original `forced` bit while flipping only `default` (a forced target emits `default+forced`), wired into both the combined and subtitle-only repair paths with regression tests as the guard.
- **Remux queue progress is tracked by file path, not card position.** `syncRemuxCardStates` used to infer "done" from a card's DOM position relative to the active one, but the backend doesn't walk the queue top-to-bottom, so unprocessed cards were falsely marked complete and once-active cards reset to plain. Completion is now tracked by path as the activity focus advances, so the queue stays truthful regardless of order.

### Fixed

- **Repair progress reads as motion instead of a dead stop.** The in-flight mux now shows as a vertical fill creeping down the active card — a pure front-end facade paced from file size over a slow-biased throughput estimate, eased to plateau at 88% so it can never false-complete. When an I/O trough would otherwise stall the bar, a "finalizing lossless mux" crawl advances it 88→96% over a long tail, with the snap to 100% reserved for the real remux completing. Reassurance without lying, and no backend changes.
- **Canonical Lists no longer reports itself inactive when `IMDB_DATASET_DIR` is unset.** The backend self-manages the IMDb dataset under `~/.local/share/normal/imdb-datasets/` and only falls back to that environment variable as an override, but the readiness check (and the launch contract) treated the unset variable as the gate. Readiness now checks the managed files, honoring the override, so the default local path is correctly recognized as active.
- **The rail no longer clips its lower icons on an empty surface.** The sliver rail height was pinned to the active primary surface and clipped with `overflow:hidden`, so a cold or empty surface collapsed it to its 220px floor and cut off the bottom icons. The rail now sizes to its own content in both modes, and a permanently-empty rail body that was causing asymmetric bottom padding (plus its orphaned CSS) was removed.

## [0.7.0-alpha.5] — 2026-06-07

### Added

- A new movie repair planning and execution seam now powers `Fix Audio and Subtitle Defaults`. Repair rows carry explicit audio, subtitle, and combined repair plans, and the backend can execute one combined remux pass when audio-default changes also alter the correct subtitle-default outcome.
- The web server now exposes `/api/movies/repair-defaults/fix` as a unified repair-defaults mutation route instead of forcing the UI to split ownership awkwardly across older per-family paths.
- Audit reads now expose ledger revision metadata and the latest system-start context, and the web layer now includes an `/api/audit/stream` SSE route so the workbench can react to ledger changes without polling blindly.
- User adjustable safety gating policy

### Changed

- The root workbench is now stricter about consequence ownership. Normalize Naming no longer exposes a `Preview Scope` toggle, and the preview pane no longer implies a distinct full-library preview mode when the meaningful operator action is still row selection.
- Downstream preview semantics are now more uniform across the shell. Normalize, junk cleanup, weak-encode delete preview, and repair-default flows all lean on the same staged model: select rows, inspect the staged consequence surface, then confirm.
- `Fix Audio and Subtitle Defaults` was hardened substantially in the UI. Repair action labels, selection handling, applicability reporting, row refresh, combined-action preview wording, and repair-lock behavior were all tightened so mixed audio/subtitle work reads as one coherent lane rather than loosely connected subcases. Preview window semantics were given more clarity and articulation to tracks complex multi-file and multi-package changes. 
- `Audit Ledger` UI introduced more detailed and articulated ledger events in particular for remuxxing jobs which chain multiple jobs or multiple actions into a single event. UI feel was improved with better table spacing, more communicative labelling, minor visual grammar for cards and an inline cell drop down for multi-stage inspection
- Subtitle policy moved from the older one-field conservative mode into explicit library policy controls for English-audio and non-English-audio cases. The policy/editor surface now treats language and subtitle defaults as their own playback-policy section.
- Library policy also now exposes a warning-gate safety level, separating how aggressively the UI should gate user-facing warnings from the core quality and delete defaults.
- Canonical movie lists were refreshed again: `Animation` and `Documentary` now use 100-title shapes, `Drama / Romance` was added, and IMDb genre matching is stricter for hybrid lists so multi-genre categories do not degrade into loose any-genre buckets.
- Delete and repair routes now preserve richer downstream metrics. Junk deletion tracks deleted-media size data, repair flows summarize removed foreign-audio tracks and bytes, and updated profile items are rebuilt from the post-fix facts so the shell can refresh mutated rows directly.
- Resolution breakdown classification now uses a more general display-shape taxonomy across HD and UHD buckets, not just SD-era labels, which gives histogram and profile surfaces cleaner letterbox/anamorphic distinctions.
- Release truth surfaces were advanced to `alpha.5`, including package metadata, workbench chrome, roadmap status, and the lean release docs set used for prerelease cuts.

### Fixed

- Removed dead frontend wiring for the old preview-scope selector and its library-mode branches, eliminating one more path where the shell could imply behavior that did not materially change the backend mutation contract.
- Audit-store reads now reuse cached ledger and follow-up state until the ledger changes, reducing unnecessary repeat parsing during repeated workbench reads.
- Library-improvement totals now continue to count delete effects even when older audit events do not carry the newer `deleted_media` metadata payload, which keeps removal progress coherent across mixed ledger history.

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
