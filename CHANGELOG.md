# Changelog

## [Unreleased] — v1.1

### Added

- UI themes: light, dark, and system default
- New onboarding documentation
- **Canonical Lists** page — compares owned titles against live all-time movie lists via TMDb and a local cache; simple badge unlocks for first-pass coverage tracking
- **Fix Multi-Audio Packaging** — detects MKVs with the wrong default audio language or a weaker English fallback, then either flips the default flag in place, drops tagged foreign-language audio, or queues for replacement
- **Repair Subtitle Readiness** — non-destructive lossless remux that corrects embedded subtitle default flags for supported MKVs: clears defaults for English-audio files, sets forced English when available, sets English default for non-English audio
- **Repair Artwork for Plex** — movie poster scan with drag-and-drop apply; recognizes `poster.jpg`, `folder.jpg`, and stem-based sidecar names; writes `poster.jpg` to each movie folder; gallery loads from the same paths Plex reads
- Movie scan, web tables, CSV export, and XLSX register now show a normalized main-audio summary alongside bitrate: `AAC 2.0`, `Dolby Digital 5.1`, `Dolby Digital Plus 5.1 Atmos`, `Dolby TrueHD 7.1 Atmos`, `DTS-HD MA 5.1`, and similar
- Replacement queue history filters: `Deleted, Awaiting Replacement`, `Replaced`, `Deleted From Queue`, `All Items`
- Inline dismiss action for deleted queue rows that are not worth replacing — changes queue state only, does not touch media files
- Dashboard View standards cards: each card shows current rule summary, movie count, and an inline **Edit definition** control that writes back to `movie_standards.json`

### Changed

- Fix Multi-Audio Packaging locks selection and action buttons during an active remux to prevent a mixed in-flight batch; **Delete Selected Files** moved to the far right of the action row
- Movie replacement-queue state now persists across hard refresh for the same source
- Movie navigation places Canonical Lists last in the page button list
- Normalize result tables no longer render the Reason column

### Fixed

- Movie replacement-queue delete now treats already-missing media as already deleted instead of leaving the queue item stuck in a pending state
- Movie profile cancellation now reliably records `movie_profile_cancelled` warnings when traversal stops mid-run

### Performance

- Heavy movie-side recursive scans now walk incrementally with cancellation checks during traversal instead of pre-enumerating the whole file tree up front — main fix for CPU-spike reduction on large libraries and risky mounts

### Known issue

- Movie scan cancellation is still best-effort. Under some unknown fast-interaction pattern, a background `ffprobe` may survive cancellation and fail to appear in the Drive Activity indicator.

---

## [0.1.0] — 2026-04-30

Initial release.

### Music lane

- Scan FLAC libraries for tag, filename, and folder inconsistencies
- Generate reviewable change plans with `safe` / `review` confidence levels
- Apply plans to a new target directory or in-place (opt-in)
- Artist name deduplication across case and `&` / `and` variants
- Dashboard profile view: format mix, fidelity distribution, artwork readiness
- Repair artist artwork for Jellyfin: sidecar fetch, candidate preview, approve and write
- Jellyfin artist metadata sync to push library sidecars into Jellyfin cache
- CSV collection export

### Movie lane

- Normalize movie file and folder names using local title/year parsing
- Encode quality profiling against a resolution-gated quality ladder
- Weak encode triage with persistent replacement queue tracking
- Junk video detection: samples, featurettes, shorts under 5 minutes
- Promo document cleanup: sidecar `.txt` / `.html` / `.htm` files
- Dashboard view: quality tier distribution, bitrate histograms, resolution breakdown
- XLSX catalogue export

### Web UI

- Local-only HTTP server (stdlib only, no external framework)
- Library Switcher for Movies / Music lane selection
- Source path auto-detection from path segments
- Music: Dashboard, Normalize, Repair Artwork for Jellyfin
- Movies: Dashboard, Normalize, Delete Weak Encodes, Fix Multi-Audio Packaging, Delete Junk Videos, Delete Junk Sidecar & Spam Files, Export Catalogue
- Per-page ETA estimation persisted in localStorage
- Abort support: Stop button cancels in-flight scans
