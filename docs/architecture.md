# Architecture

*Authorship: Agent-written.*

`normal` is a local-first movie library workbench. The core shape is simple: scan or plan first, then mutate only through an explicit apply, delete, or repair action. Most workflows share the same small set of internals so the library is not re-read more often than necessary.

## Core pipelines

### Normalize pipeline

The normalize flow is a proposal pipeline first:

`movie_plan.py` -> proposed changes -> `movie_apply.py`

- `movie-plan` and the web normalize page parse local paths and build a rename or cleanup plan.
- The plan can include file renames, file moves, folder renames, safe folder merges, and a narrow set of safe cleanup deletes.
- Nothing is changed during planning. Mutation only happens when the user applies selected changes.

### Quality and triage pipeline

The quality workflow starts with local media facts, then classifies them into action and quality layers:

`probe_cache.py` -> `movie_scan.py` / `movie_profile.py` -> dashboard, weak-encode triage, repair pages

- `ffprobe` gathers per-file media facts.
- `movie_profile.py` classifies those facts against repo-local movie standards.
- The same profile result feeds the Dashboard, Delete Weak Encodes, Audio Packaging, and Subtitle Readiness flows.
- This shared-scan model is deliberate. It avoids separate full-library rescans for each page.

### Repair pipelines

Two repair flows sit on top of the shared movie profile result:

- `movie_audio_fix.py` remuxes supported MKVs to correct English-default audio behavior.
- `movie_subtitle_fix.py` remuxes supported MKVs to correct embedded subtitle default flags.

These are mutation workflows, but they are narrower than normalize or delete flows: they rewrite container metadata and stream layout without renaming the library structure.

### Junk pipeline

`movie_junk.py` runs a separate cleanup scan for junk videos and sidecar spam:

- junk-marker videos such as samples or extras
- sidecar documents such as `.nfo`, promo HTML, and similar clutter

The scan is read-only. Deletion happens only after explicit selection and confirmation in the web UI.

### Canonical lists and ratings

Two optional network-backed surfaces sit beside the local pipelines:

- Canonical Lists uses TMDb plus a local cache for title coverage comparisons.
- Replacement-history IMDb ratings use OMDb plus a local cache.

These do not drive mutation decisions. They are support surfaces around the local library state.

## Persistent state

`normal` keeps a small number of durable state files outside the media library itself.

### Repo-local state

- `movie_standards.json` in the repo root is the source of truth for quality-profile definitions and the replacement-candidate cutoff.

This file survives browser refreshes, server restarts, and localhost port changes because it is not browser state.

### User-local state

Under `~/.local/share/normal/`:

- `probe-cache.json` stores per-file probe results keyed by resolved path, mtime, and size.
- `movie-replacement-queue.json` stores weak-encode and audio-packaging queue history.
- `subtitle-fix-history.json` stores subtitle repair history and review-only subtitle items.
- `library-roots.json` stores the last active movie root and a short recent-roots list.

### User-local caches

- `~/.local/share/normal/canonical_lists/<schema-version>/` stores TMDb canonical-list cache files.
- `~/.cache/normal/omdb_ratings/<schema-version>/` stores cached OMDb rating lookups.

### Browser-local convenience state

The web UI also keeps convenience caches in `localStorage`, including:

- recent scan durations
- selected library roots and recent libraries
- cached dashboard payloads
- cached canonical-list payloads
- cached replacement-queue payloads
- theme selection

These browser caches are convenience snapshots only. They are not authoritative and do not replace repo-local or user-local state.

## Cache invalidation and freshness

There are four main freshness models in the current architecture.

### Probe cache

- Probe cache entries are keyed by resolved path, file mtime, and file size.
- If any of those change, the old entry no longer matches and the file is reprobed.
- This is the main reason warm scans are much faster than cold scans.

### Server-side movie profile cache

- The web server keeps one in-memory `MovieProfileReport` per resolved source path.
- Dashboard, Delete Weak Encodes, Audio Packaging, and Subtitle Readiness all reuse it.
- This cache is explicitly invalidated after normalize apply, after successful audio repairs, and after successful subtitle repairs.

This cache is process-local. Restarting the web server clears it.

### Movie standards freshness

- Saving dashboard profile definitions writes `movie_standards.json` directly.
- The save path includes a revision token derived from the current standards file.
- If another tab or process changed the file first, the stale write is rejected instead of silently overwriting newer rules.

Current behavior is intentionally narrow: saving standards updates the definitions immediately, but it does not trigger a full reclassification scan. Counts and file classifications update on the next explicit scan.

### Canonical-list and OMDb caches

- TMDb canonical-list data is cached on disk and may be returned as fresh, live, or stale cached data depending on fetch state.
- OMDb ratings are cached per lookup key so repeated replacement-history loads do not keep spending quota.

## Mutation model

The mutation model is explicit and split by workflow.

### Read-only by default

These workflows inspect, profile, or plan without touching media files:

- `movie-plan`
- `movie-scan`
- `movie-profile`
- `movie-inspect`
- `movie-junk`
- `movie-register`
- dashboard and list views in the web UI

They may write reports or cache files, but they do not rename, delete, or remux library media.

### Planned structure changes

Normalize uses a proposal-and-apply model:

- planning builds `ProposedChange` items
- apply executes only the selected changes
- `--target` writes to a new directory
- `--in-place` mutates the source library and must be explicit

This is the main structural mutation path for renames, moves, merges, and safe artifact cleanup.

### Destructive deletion flows

Deletion is web-first and confirmation-gated:

- Junk deletion removes files only after selection, confirmation, path validation, and detector revalidation.
- Weak-encode and audio-packaging deletion first records queue state, then deletes the selected media.

Replacement-queue history is durable. Items are not silently dropped when the media disappears.

### Repair flows

Audio Packaging and Subtitle Readiness are in-place repair workflows for supported MKVs:

- audio repair changes default-audio behavior, with an optional stricter mode that drops foreign audio
- subtitle repair changes embedded subtitle default flags

These are still explicit mutations, but they are repair operations rather than file-structure operations.

## Design boundaries

- The web server is stdlib `http.server`, not an external framework.
- The frontend shell, styles, and client logic are package-managed assets under `normal/web_assets/`, loaded and served by the stdlib web package under `normal/web/`.
- Web tests are intentionally split: facade and handler behavior stays in `tests/test_web.py`, while `normal/web/activity.py`, `scan_guard.py`, and `serializers.py` carry direct unit coverage.
- Heavy recursive scans are single-flight per source in the web UI.
- Recursive discovery is streamed rather than fully enumerated up front in the heavy movie workflows.
- Most product decisions are local-file-first. Remote metadata is limited to the optional TMDb and OMDb surfaces.

For user-facing operation and safety guidance, see [Movies](movies.md) and [Safety](safety.md). For agent/developer operational detail, see [Agent reference](agent.md).
