# Changelog

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
- Movies: Dashboard, Normalize, Delete Weak Encodes, Delete Junk Videos, Delete Junk Misc, Export Catalogue
- Per-page ETA estimation persisted in localStorage
- Abort support: Stop button cancels in-flight scans
