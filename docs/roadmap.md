# Roadmap

## v1 — current release

Music lane: scan, plan, apply, artist deduplication, dashboard profile, artwork repair for Jellyfin, CSV export.

Movie lane: normalize names, encode quality profiling, weak encode triage with replacement queue, junk video and promo document cleanup, dashboard, XLSX catalogue export.

Both lanes: local web UI, full CLI surface.

## vNext — backlog

Features in no particular order. Priority will be shaped by usage patterns after v1.

**Movies**
- **Plex Compatibility workflow** — heuristic findings for playback risk and indexing risk are implemented in `movie_profile.py`; the UI page is hidden pending a clearer workflow design
- **Catalogue merge / swap report** — import another user's exported catalogue, compare shared movies, suggest swaps where one library has a stronger encode

**Music**
- **Music Recommendation Engine** — placeholder UI page; vision to be defined

**Both lanes**
- **Configurable preference defaults** — quality thresholds, replacement priority weights, normalization rules are currently hardcoded; surface as documented config before adding UI controls
- **Broader platform testing** — Linux-first for v1; Windows and macOS rough edges are known and deferred

**Opt-in / separate**
- **Adult video metadata register** — scan a local directory, derive search terms from filenames, look up performer names, write a local register file; strictly separate from general movie scan/plan/apply

## v2 — posture shift

v2 is a milestone, not a release date.

The defining change is a shift from the current **agent-assisted** stance to a **standalone application** stance.

In v1, some preferences and defaults are intentionally hardcoded rather than surfaced as UI controls. The expected way to adjust them is through direct repo edits or by working with an AI agent. This is a deliberate choice: it keeps the product lean while real usage patterns are unclear, and avoids designing configuration UI for preferences that may not need to be configurable at all.

v2 means:
- all vNext features stable
- the controls needed for a user to configure the tool without agent help are in the UI
- the product no longer assumes an agent-assisted workflow as the adjustment path
