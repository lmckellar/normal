# Changelog

This changelog was retroactively rebuilt from commit history and diff/change
logs. Package metadata is still `0.1.0` until a real release is cut.

## [Unreleased]

### Added

- Server-side OMDb rating cache and lookup endpoint for movie replacement history.
- Repo-local agent guidance for the intended `unittest` test runner.

### Changed

- Quality Profile card editing no longer exposes per-profile allowed audio codecs, and quality-profile matching no longer gates on those per-profile codec lists.
- Dashboard movie profile scans now show streamed forward progress in the activity bar: processed file count, current probe target, elapsed time, and ETA only when a bounded total is known.
- Movie replacement-history IMDb ratings now use local title cleanup and search fallback, and no longer expose the OMDb key to the browser.

### Fixed

- IMDb rating availability on fresh web UI load.
- Repair Subtitle Readiness table now shows movie title and year (e.g. `Alien (1979)`) instead of the raw file path.
- Downstream Plex client subtitle-default changes are verified working without cache invalidation issues.

---

## [0.6.4] — 2026-05-12

Plex-synced movie artwork repair.

### Added

- Plex API integration for movie artwork repair: scan now queries the local Plex
  server (`localhost:32400`) and maps each movie folder to its Plex artwork via
  `fetch_plex_movie_index`.
- `--plex-token` and `--plex-url` CLI flags for `normal web`; both fall back to
  `PLEX_TOKEN` / `PLEX_URL` environment variables.
- Server-side Plex image proxy route (`GET /api/movies/artwork/plex-image`) keeps
  the Plex token out of the browser and caches responses for 1 hour.
- `display_name` field on poster items: clean "Title (Year)" derived via
  `parse_movie_identity`, shown in tiles and detail panel instead of raw folder
  names.
- `plex_title_sort` field on poster items: Plex's own sort key used for grid
  ordering, replicating Plex's article-dropping and numeric-aware alphabetisation.

### Changed

- Artwork grid status is now Plex-driven when a token is configured: "present"
  means Plex has a thumb, "missing" means Plex knows the movie but has no art.
  Falls back to local sidecar detection when Plex is unconfigured or the movie is
  not indexed.
- Grid sort order uses Plex `titleSort` when available, otherwise falls back to
  article-stripped display name with numeric-aware comparison.
- Tagline updates to reflect whether Plex sync is active.

### Fixed

- Resolution tokens (e.g. `1920x820`) in filenames no longer cause the year
  parser to misidentify the resolution width as the release year. Fixed in both
  `movie_identity.py` (shared `YEAR_PATTERN`) and the artwork-lane display-name
  fallback.
- Year-leading filenames (e.g. `1979.Mad.Max.…`) now parse to clean titles via a
  dedicated fallback in `_parse_display_name`.
- Apostrophe-free secondary index keys prevent lookup misses for titles like
  "A Bug's Life" whose filesystem names drop the apostrophe.

---

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

## [0.6.0] — 2026-05-11

Movie artwork repair lane.

### Added

- **Repair Artwork for Plex** scans movie folders for poster sidecars.
- Drag-and-drop poster apply writes `poster.jpg` to each movie folder.
- Poster gallery previews the same paths Plex reads.

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
