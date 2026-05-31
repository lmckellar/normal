# Changelog

This changelog was retroactively rebuilt from commit history and diff/change
logs. Real release history starts at `v0.7.0-alpha.1`, with a matching git tag
and GitHub prerelease. Earlier sections remain reconstructed history.

## [Unreleased]

### Changed

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
- The old parser-tester selected-row export endpoint was removed. The internal testing surface now validates parser output by previewing and confirming the real normalize mutation contract instead of exporting rows to a side artifact.

---

## [0.7.0-alpha.1] — 2026-05-23

### Added

- Persistent file-level probe cache (`ProbeCache` in `probe_cache.py`). All ffprobe results are cached to `~/.local/share/normal/probe-cache.json`, keyed by `(path, mtime_ns, size_bytes)`. Shared across all scan workflows (profile, junk, catalogue export, inspect). After a cold first scan, subsequent scans re-read from disk instead of spawning ffprobe, reducing a ~330s full-library walk to ~5s on the next server start. Automatically invalidates per file when mtime changes (e.g. after an audio or subtitle fix).
- Server-side movie profile cache (`MovieProfileCache`) in `web.py`. Dashboard, Delete Weak Encodes, Fix Multi-Audio Packaging, and Repair Subtitle Readiness all draw from a single cached `MovieProfileReport` per source root. Subsequent navigations between these four pages return in under a second instead of re-running a full ffprobe sweep each time. The cache is explicitly invalidated after file-mutating operations: `handle_movies_apply` (renames), `handle_movies_audio_packaging_fix` (when files were fixed), and `handle_movies_subtitle_readiness_fix` (when files were fixed). No TTL — cache persists for the server session and is only cleared by explicit invalidation.
- `reclassify_report_with_standards(report, standards)` added to `movie_profile.py`. Rebuilds all `MovieProfileItem` objects from their cached `MediaFacts` against a new standards dict without running ffprobe. Not currently called from the web layer (standards saves are now instant and defer reclassification to the next scan), but available for future use.

### Changed

- Fix Multi-Audio Packaging and Repair Subtitle Readiness merged into a single **Repair Defaults** page with a shared scan and two sub-tabs. Previously required two separate scan cycles; one scan now feeds both tabs and the user switches between them without re-probing.
- Junk video detection and promo/sidecar document cleanup merged into a single combined scan (~12 s vs ~2 min previously). `POST /api/movies/junk` returns both video junk and document junk in one response; the UI presents them as two detail panels from the same scan result.
- Canonical lists swapped: `top_1000` and `suspense_horror` removed (poor fit for the reference library); `animation` (Top 50 Animation, TMDb genre 16, 60%) and `documentary` (Top 50 Documentary, TMDb genre 99, 60%) added.
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
