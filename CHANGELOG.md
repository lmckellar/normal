# Changelog

## [Unreleased] — v1.1

### Both lanes
- UI themes (light, dark, system default)
- New onboarding documentation

### Movie lane
- Canonical Lists page backed by TMDb plus a local cache for owned-title coverage against live all-time movie lists
- Simple Canonical Lists badge unlocks for quick coverage feedback; deeper badge refinement is deferred
- Shared movie triage substrate with family-aware replacement queue state
- Heavy movie-side recursive scans now walk incrementally instead of prebuilding the whole recursive path set first; that execution-model shift, plus cancellation checks during traversal, was the key fix behind the CPU-spike reduction on large or risky sources
- New `Fix Multi-Audio Packaging` workflow for MKVs with wrong default language or weak English fallback tracks
- Movie scan, web tables, CSV export, and XLSX register now expose a normalized main-audio summary beside bitrate, covering common labels such as `AAC 2.0`, `Dolby Digital 5.1`, `Dolby Digital Plus 5.1 Atmos`, `Dolby TrueHD 7.1 Atmos`, and `DTS-HD MA 5.1`
- Replacement queue history filters for `Deleted, Awaiting Replacement`, `Replaced`, `Deleted From Queue`, and `All Items`
- Inline dismiss action for deleted queue rows that are not worth replacing
- Movie replacement-queue delete now treats already-missing media as already deleted instead of leaving the queue item stuck
- `Fix Multi-Audio Packaging` now locks selection and action buttons during active remux, and separates `Delete Selected Files` to the far right to reduce accidental clicks
- Movie replacement-queue state now persists across hard refresh for the same source, including audio-packaging `Deleted, Awaiting Replacement` history
- Movie profile cancellation now reliably records `movie_profile_cancelled` warnings when traversal stops mid-run
- Early local validation showed Canonical Lists and Weak Encodes scans complete with only moderate transient temperature rise that recedes after scan completion once the scan stopped doing an up-front full-tree walk
- Movie navigation now places `Canonical Lists` last in the page button list, and Normalize result tables no longer render the `Reason` column

### Known issue
- Movie scan cancellation is still best-effort. Under some unknown fast UI interaction pattern, a background `ffprobe` may survive cancellation and fail to appear in the Drive Activity indicator.

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
