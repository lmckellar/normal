# Roadmap

## v1 — current release

Music lane: scan, plan, apply, artist deduplication, dashboard profile, artwork repair for Jellyfin, CSV export.

Movie lane: normalize names, encode quality profiling, canonical-list coverage dashboard, weak encode triage, multi-audio packaging triage, shared replacement queue workflow, junk video and sidecar & spam file cleanup, dashboard, XLSX catalogue export.

Both lanes: local web UI, full CLI surface.

## vNext — backlog

Features in no particular order. Priority will be shaped by usage patterns after v1.

**Movies**
- **Canonical Lists badge refinement** — keep the TMDb-backed coverage scan, but improve badge weighting, thresholds, and presentation once real usage shows what is noisy or misleading
- **Plex Compatibility workflow** — heuristic findings for playback risk and indexing risk are implemented in `movie_profile.py`; the UI page is hidden pending a clearer workflow design
- **Catalogue merge / swap report** — import another user's exported catalogue, compare shared movies, suggest swaps where one library has a stronger encode

**Music**
- **Music Recommendation Engine** — placeholder UI page; vision to be defined

**Both lanes**
- **Onboarding copy** — improve in-app onboarding text to better orient new users
- **Configurable preference defaults** — quality thresholds, replacement priority weights, normalization rules are currently hardcoded; surface as documented config before adding UI controls
- **Broader platform testing** — Linux-first for v1; Windows and macOS rough edges are known and deferred
- **Cross-environment scan hygiene validation** — measure whether incremental traversal, temp-file strategy, cancellation, and process visibility behave cleanly under Windows/macOS and common Linux desktop setups with indexers, AV, cloud-sync clients, automounters, and alternate shell/service launch paths
- **Replacement queue performance and state boundaries** — reduce full-table recompute/repaint cost when switching movie queue history filters, especially `Replaced` to `All Items`; tighten state ownership and backend domain boundaries before broader cleanup
- **Replacement queue restore action** — add an inline `restore to queue` action for `Deleted From Queue` items so dismissed titles can re-enter the replacement workflow without re-scanning first
- **Probe lifecycle hardening** — isolate and fix the open issue where cancelled movie scans can leave background `ffprobe` processes that are not always visible through the current activity indicator

## v2 — standalone

v2 ships the vNext backlog and moves user-adjustable behaviour into the UI, so that changing how `normal` works doesn't require editing code or asking an agent.

In v1, things like naming output schema, table column layouts, and quality profile definitions are hardcoded. Adjusting them is straightforward with an agent or a direct repo edit, but that's not a reasonable expectation for everyone. v2 surfaces these as proper UI controls — the tool should be fully configurable without touching the codebase.
