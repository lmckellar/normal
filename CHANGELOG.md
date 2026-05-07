# Changelog

## [Unreleased] — v1.1

### Both lanes
- UI themes (light, dark, system default)
- New onboarding documentation

### Movie lane
- Shared movie triage substrate with family-aware replacement queue state
- New `Fix Multi-Audio Packaging` workflow for MKVs with wrong default language or weak English fallback tracks
- Replacement queue history filters for `Deleted, Awaiting Replacement`, `Replaced`, `Deleted From Queue`, and `All Items`
- Inline dismiss action for deleted queue rows that are not worth replacing
- Movie replacement-queue delete now treats already-missing media as already deleted instead of leaving the queue item stuck
- `Fix Multi-Audio Packaging` now locks selection and action buttons during active remux, and separates `Delete Selected Files` to the far right to reduce accidental clicks
- Movie replacement-queue state now persists across hard refresh for the same source, including audio-packaging `Deleted, Awaiting Replacement` history

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
