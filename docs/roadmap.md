# Roadmap

## v1 — current release

Music lane: scan, plan, apply, artist deduplication, dashboard profile, artwork repair for Jellyfin, CSV export.

Movie lane: normalize names, encode quality profiling, weak encode triage with replacement queue, junk video and sidecar & spam file cleanup, dashboard, XLSX catalogue export.

Both lanes: local web UI, full CLI surface.

## vNext — backlog

Features in no particular order. Priority will be shaped by usage patterns after v1.

**Movies**
- **Plex Compatibility workflow** — heuristic findings for playback risk and indexing risk are implemented in `movie_profile.py`; the UI page is hidden pending a clearer workflow design
- **Catalogue merge / swap report** — import another user's exported catalogue, compare shared movies, suggest swaps where one library has a stronger encode

**Music**
- **Music Recommendation Engine** — placeholder UI page; vision to be defined

**Both lanes**
- **Onboarding copy** — improve in-app onboarding text to better orient new users
- **Configurable preference defaults** — quality thresholds, replacement priority weights, normalization rules are currently hardcoded; surface as documented config before adding UI controls
- **Broader platform testing** — Linux-first for v1; Windows and macOS rough edges are known and deferred

## v2 — standalone

v2 ships the vNext backlog and moves user-adjustable behaviour into the UI, so that changing how `normal` works doesn't require editing code or asking an agent.

In v1, things like naming output schema, table column layouts, and quality profile definitions are hardcoded. Adjusting them is straightforward with an agent or a direct repo edit, but that's not a reasonable expectation for everyone. v2 surfaces these as proper UI controls — the tool should be fully configurable without touching the codebase.
