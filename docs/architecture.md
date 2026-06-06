# Architecture

*Authorship: Agent-written.*

`normal` is a local-first movie library workbench. The core shape is simple: scan or plan first, then mutate only through an explicit apply, delete, or repair action. Most workflows share the same small set of internals so the library is not re-read more often than necessary.

## Core pipelines

### Normalize pipeline

The normalize flow is a proposal pipeline first:

`movie_plan.py` -> proposed changes -> `movie_apply.py`

- `movie-plan` and the web normalize page parse local paths and build a rename or cleanup plan.
- The plan can include file renames, file moves, folder renames, safe folder merges, and a narrow set of safe cleanup deletes.
- Existing-target collisions are not all treated the same. The planner first tries to resolve them into safe alternate concise targets when local evidence is strong enough, then leaves only the unresolved cases in review.
- Collision checks now use the composed final movie target, not just raw per-change target fragments. This matters for cases where a `file_rename` and `folder_rename` together would land on the same downstream file as another move or rename.
- Nothing is changed during planning. Mutation only happens when the user applies selected changes.

Current normalize contract is intentionally evidence-driven:

- parser evidence and local folder context can promote a collision from `review` to `safe`
- shared display-title and token cleanup now lives in `movie_naming.py`, with `movie_identity.py` and downstream lookup/matching surfaces reusing that seam
- normalize web payloads now carry linked change detail plus warning detail for each movie row
- the main workbench is the only web shell for that richer backend reasoning; it reuses the same normalize confirm/apply endpoint rather than introducing a separate mutation contract
- the same workbench also acts as a downstream-shape harness: selected rows can be staged into an inline tree preview, the filtered library view can be rendered as a compact projected directory shape, and safe wrapper-folder deletes implied by a fully selected package split can be confirmed alongside the row-linked movie moves
- parser cleanup is still local-only and intentionally narrow: edge tracker/domain credit stripping, compact token cleanup, a small settled punctuation family, and a tiny explicit canonical-title exception seam for non-generalizable settled cases; no remote canonical-title recovery

### Quality and triage pipeline

The quality workflow starts with local media facts, then classifies them into action and quality layers:

`probe_cache.py` -> `movie_scan.py` / `movie_profile.py` -> dashboard, weak-encode triage, repair pages

- `ffprobe` gathers per-file media facts.
- Probe facts now include stream aspect metadata, so `resolution_bucket` can represent effective display class rather than raw stored raster when the container exposes usable SAR/DAR data.
- `movie_profile.py` classifies those facts against repo-local movie standards.
- The same profile result feeds the Dashboard, Review Low-Quality Encodes, Audio Packaging, and Subtitle Readiness flows.
- This shared-scan model is deliberate. It avoids separate full-library rescans for each page.

The scan economics matter here:

- recursive discovery is streamed rather than fully enumerated up front
- probe results are persisted by path, mtime, and size
- web profile consumers reuse one cached report per source root

In practice this means cold scans against very large or accidentally broad roots are now much less punitive than earlier revisions. That is an execution-model property, not a product promise that every source choice is equally safe or equally cheap.

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

Two provider-backed support surfaces sit beside the local pipelines:

- Canonical Lists defaults to local IMDb datasets plus a local cache for title coverage comparisons, with local consensus-weighted IMDb ranking and optional TMDb fallback when explicitly selected.
- Replacement-history IMDb ratings use OMDb plus a local cache.

These do not drive mutation decisions. They are support surfaces around the local library state.

## Persistent state

`normal` keeps a small number of durable state files outside the media library itself.

### Repo-local state

- `movie_standards.json` in the repo root is the source of truth for library
  policy: quality-profile definitions, replacement-candidate cutoff, primary
  language, subtitle defaults, and junk-floor defaults.

This file survives browser refreshes, server restarts, and localhost port changes because it is not browser state.

### User-local state

Under `~/.local/share/normal/`:

- `operator-preferences.json` stores user-local operator preferences such as
  delete posture.
- `probe-cache.json` stores per-file probe results keyed by resolved path, mtime, and size.
- `library-roots.json` stores the last active movie root and a short recent-roots list.
- `audit-ledger.jsonl` stores the unified audit/event ledger for scans, deletes, repairs, exports, policy updates, and follow-up state changes.

### User-local caches

- `~/.local/share/normal/canonical_lists/<schema-version>/<provider>/` stores canonical-list cache files per provider.
- `~/.cache/normal/omdb_ratings/<schema-version>/` stores cached OMDb rating lookups.

### Browser-local convenience state

The web UI also keeps convenience caches in `localStorage`, including:

- recent scan durations
- selected library roots and recent libraries
- cached dashboard payloads
- cached canonical-list payloads
- theme selection

These browser caches are convenience snapshots only. They are not authoritative
and do not replace repo-local or user-local state.

## Cache invalidation and freshness

There are four main freshness models in the current architecture.

### Probe cache

- Probe cache entries are keyed by resolved path, file mtime, and file size.
- If any of those change, the old entry no longer matches and the file is reprobed.
- This is the main reason warm scans are much faster than cold scans.
- Cache schema changes can still force a one-time warm-cache reset when the stored `MediaFacts` contract changes materially, such as adding new ffprobe fields needed for resolution classification.
- The current execution model also reduces the cold-scan penalty because discovery and probe work are interleaved instead of paying a large up-front enumeration cost first.

### Server-side movie profile cache

- The web server keeps one in-memory `MovieProfileReport` per resolved source path.
- Dashboard, Review Low-Quality Encodes, Audio Packaging, and Subtitle Readiness all reuse it.
- This cache is explicitly invalidated after normalize apply, after successful audio repairs, and after successful subtitle repairs.

This cache is process-local. Restarting the web server clears it.

### Movie standards freshness

- Saving dashboard profile definitions writes `movie_standards.json` directly.
- The save path includes a revision token derived from the current standards file.
- If another tab or process changed the file first, the stale write is rejected instead of silently overwriting newer rules.

Current behavior is intentionally narrow: saving standards updates the definitions immediately, but it does not trigger a full reclassification scan. Counts and file classifications update on the next explicit scan.

### Canonical-list and OMDb caches

- Canonical-list data is cached per provider on disk and may be returned as fresh, live, or stale cached data depending on fetch state.
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
- Backend row serializers are expected to work from indexed or precomputed scan/plan state rather than re-walking or reparsing per row on hot paths.
- Most product decisions are local-file-first. Remote metadata is limited to optional TMDb and OMDb calls; the default canonical-list path uses local IMDb datasets.

For user-facing operation and safety guidance, see [Movies](movies.md) and [Safety](safety.md). For agent/developer operational detail, see [Agent reference](agent.md).
