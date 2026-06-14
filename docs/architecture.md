# Architecture

`normal` is a local-first movie library workbench. The core shape is simple: **scan or plan first, then mutate only through an explicit apply, delete, or repair action.** Most workflows share a small set of internals, so the library is never re-read more than necessary.

## Core pipelines

### Normalize pipeline

Normalize is a proposal pipeline first:

`movie_plan.py` → proposed changes → `movie_apply.py`

- `movie-plan` and the web normalize page parse local paths and build a rename or cleanup plan.
- The plan can include file renames, file moves, folder renames, safe folder merges, and a narrow set of safe cleanup deletes.
- Collisions aren't all treated the same. The planner first tries to resolve them into safe alternate concise targets when local evidence is strong, then leaves only the unresolved cases in review.
- Collision checks use the **composed** final movie target, not raw per-change fragments — important when a `file_rename` and `folder_rename` together would land on the same downstream file as another move.
- Nothing changes during planning. Mutation happens only when the user applies selected changes.

The contract is evidence-driven:

- parser evidence and local folder context can promote a collision from `review` to `safe`
- shared display-title and token cleanup lives in `movie_naming.py`, reused by `movie_identity.py` and downstream lookup/matching surfaces
- normalize web payloads carry linked change detail plus warning detail per movie row
- the main workbench is the only web shell for that richer reasoning; it reuses the same normalize confirm/apply endpoint rather than a separate mutation contract
- the workbench also acts as a downstream-shape harness — selected rows stage into an inline tree preview, and safe wrapper-folder deletes implied by a fully selected package split can be confirmed alongside the row-linked moves
- parser cleanup is local-only and narrow: edge tracker/domain stripping, compact token cleanup, a small settled punctuation family, and a tiny explicit canonical-title exception seam; no remote canonical-title recovery

### Quality and triage pipeline

Quality starts with local media facts, then classifies them into action and quality layers:

`probe_cache.py` → `movie_scan.py` / `movie_profile.py` → dashboard, weak-encode triage, repair pages

- `ffprobe` gathers per-file media facts, now including stream aspect metadata, so `resolution_bucket` can represent effective display class rather than raw stored raster when the container exposes usable SAR/DAR data.
- `movie_profile.py` classifies those facts against repo-local movie standards.
- The same profile result feeds the Dashboard, Review Low-Quality Encodes, Audio Packaging, and Subtitle Readiness flows.
- The probed facts (carrier codec, channel layout, resolution, HDR signalling) also back the **Format Upgrade Candidates** workflow, which pairs them with a local trait corpus — immersive audio, UHD, Dolby Vision, Open Matte, Hybrid — to judge what better release exists and whether local copies already carry it, a fact the source metadata never carries.
- This shared-scan model is deliberate — it avoids separate full-library rescans per page.

Scan economics matter here:

- recursive discovery is streamed rather than fully enumerated up front
- probe results persist by path, mtime, and size
- web profile consumers reuse one cached report per source root

In practice, cold scans against very large or accidentally broad roots are far less punitive than earlier revisions. That is an execution-model property, not a promise that every source choice is equally safe or cheap.

### Repair pipelines

Two repair flows sit on top of the shared profile result:

- `movie_audio_fix.py` remuxes supported MKVs to correct English-default audio behavior.
- `movie_subtitle_fix.py` remuxes supported MKVs to correct embedded subtitle default flags.

These are mutation workflows, but narrower than normalize or delete: they rewrite container metadata and stream layout without renaming library structure.

Execution is split by cost. `build_execution_plan` decides whether a repair is **metadata-only** — a pure `default`/`forced` disposition flip with no track drop and no transcode. Metadata-only repairs route through `mkvpropedit_fix.py`, which edits the MKV header in place in milliseconds (verified by re-probe) rather than rewriting the container. Dropping foreign audio is the only change that forces a structural rewrite, so it is the sole trigger for the full ffmpeg remux path; ffmpeg is also the fallback when `mkvpropedit` is unavailable. This split is load-bearing for the UI: the multi-file repair confirmation gate keys on whether the work will actually remux, not on file count, so large disposition-only batches stay friction-free.

### Junk pipeline

`movie_junk.py` runs a separate cleanup scan for junk videos and sidecar spam:

- junk-marker videos such as samples or extras
- sidecar documents such as `.nfo`, promo HTML, and similar clutter

The scan is read-only. Deletion happens only after explicit selection and confirmation in the web UI.

### Canonical lists and ratings

Two provider-backed support surfaces sit beside the local pipelines:

- **Canonical Lists** defaults to local IMDb datasets plus a local cache for title-coverage comparisons, with local consensus-weighted ranking and optional TMDb fallback when explicitly selected.
- **Replacement-history IMDb ratings** use OMDb plus a local cache.

Neither drives mutation decisions — they are support surfaces around local library state. The optional keys they use are owned by a process-wide credential store (`normal/web/credentials.py`), seeded from the environment at boot and read live per request, so a key pasted into the Settings rail takes effect without a restart. The store persists to `secrets.env`, and the read API (`/api/settings/read`, `/api/settings/keys`) never returns a full key to the browser — only presence, last-4, and source. Key absence is the normal baseline, not a degraded state.

## Persistent state

`normal` keeps a small set of durable state files outside the media library.

### Repo-local

- `movie_standards.json` (repo root) — the source of truth for library policy: quality-profile definitions, replacement-candidate cutoff, primary language, subtitle defaults, junk-floor defaults. It survives browser refreshes, server restarts, and localhost port changes because it isn't browser state.

### User-local — under `~/.local/share/normal/`

- `operator-preferences.json` — user-local operator preferences such as delete posture
- `probe-cache.json` — per-file probe results keyed by resolved path, mtime, and size
- `library-roots.json` — last active movie root and a short recent-roots list
- `audit-ledger.jsonl` — the unified audit/event ledger for scans, deletes, repairs, exports, policy updates, and follow-up changes
- `secrets.env` — optional OMDb/TMDb keys written through the Settings rail, env-style with `0600` permissions

### User-local caches

- `~/.local/share/normal/canonical_lists/<schema-version>/<provider>/` — canonical-list cache per provider
- `~/.cache/normal/omdb_ratings/<schema-version>/` — cached OMDb rating lookups

### Browser-local convenience state

`localStorage` holds convenience caches only — recent scan durations, selected/recent library roots, cached dashboard payloads, cached canonical-list payloads, theme. These are snapshots, not authoritative, and never replace repo-local or user-local state.

## Cache invalidation and freshness

Four freshness models exist.

**Probe cache** — entries are keyed by resolved path, mtime, and size; if any change, the file is reprobed. This is the main reason warm scans beat cold ones. Schema changes can still force a one-time warm-cache reset when the stored `MediaFacts` contract changes materially (e.g. new ffprobe fields for resolution classification). Interleaving discovery and probe work also lowers the cold-scan penalty.

**Server-side movie profile cache** — one in-memory `MovieProfileReport` per resolved source path, reused by Dashboard, Review Low-Quality Encodes, Audio Packaging, and Subtitle Readiness. Explicitly invalidated after normalize apply and after successful audio/subtitle repairs. Process-local — restarting the server clears it.

**Movie standards freshness** — saving dashboard definitions writes `movie_standards.json` directly, with a revision token derived from the current file; a stale write (another tab/process changed it first) is rejected rather than silently overwriting. Saving standards updates the definitions immediately but does **not** trigger a reclassification scan — counts update on the next explicit scan.

**Canonical-list and OMDb caches** — canonical data is cached per provider on disk and may return fresh, live, or stale depending on fetch state; OMDb ratings are cached per lookup key so repeated history loads don't keep spending quota.

## Mutation model

Explicit and split by workflow.

### Read-only by default

`movie-plan`, `movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `movie-register`, and the dashboard/list views inspect, profile, or plan without touching media. They may write reports or caches but never rename, delete, or remux library media.

### Planned structure changes

Normalize uses a proposal-and-apply model: planning builds `ProposedChange` items; apply executes only the selected changes; `--target` writes to a new directory; `--in-place` mutates the source and must be explicit. This is the main structural path for renames, moves, merges, and safe artifact cleanup.

### Destructive deletion flows

Deletion is web-first and confirmation-gated: junk deletion removes files only after selection, confirmation, path validation, and detector revalidation; weak-encode and audio-packaging deletion records queue state first, then deletes. Replacement-queue history is durable — items are never silently dropped when the media disappears.

### Repair flows

Audio Packaging and Subtitle Readiness are in-place repairs for supported MKVs: audio repair changes default-audio behavior (with an optional stricter mode that drops foreign audio); subtitle repair changes embedded subtitle default flags; a combined repair plans the final post-audio subtitle intent up front and executes one lossless remux per file rather than chaining two passes. Explicit mutations, but repair operations rather than file-structure operations.

## Design boundaries

- The web server is stdlib `http.server`, not an external framework.
- The frontend shell, styles, and client logic are package-managed assets under `normal/web_assets/`, served by the stdlib web package under `normal/web/`.
- Web tests are split: facade and handler behavior in `tests/test_web.py`, while `normal/web/activity.py`, `scan_guard.py`, and `serializers.py` carry direct unit coverage.
- Heavy recursive scans are single-flight per source.
- Recursive discovery is streamed, not fully enumerated up front, in the heavy movie workflows.
- Backend row serializers work from indexed or precomputed scan/plan state rather than re-walking or reparsing per row on hot paths.
- Most decisions are local-file-first; remote metadata is limited to optional TMDb and OMDb calls, with the default canonical-list path on local IMDb datasets.

For user-facing operation and safety, see [Movies](movies.md) and [Safety](safety.md). For agent/developer detail, see [Agent reference](agent.md).

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
