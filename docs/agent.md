# Agent reference

For AI agents and developers working in this codebase. Covers repo structure, module ownership, data models, API routes, safety constraints, and intentional design decisions.

## Repo map

```
normal/
├── cli.py                       # CLI entry point and command dispatch
├── commands.py                  # CLI command implementations (movie scan, plan, apply, output, web)
├── models.py                    # Shared data models — ProposedChange and core types
├── output.py                    # Movie XLSX register (movie-register) and quality CSV export
├── movie_apply.py               # Movie apply: executes an existing plan file
├── movie_scan.py                # Movie scan: ffprobe probing, quality scoring, triage
├── movie_plan.py                # Movie plan: title/year parsing, rename proposals
├── movie_profile.py             # Movie profile: quality ladder classification, heuristic findings
├── movie_audio_fix.py           # Movie audio packaging repair: lossless MKV remux helpers
├── movie_inspect.py             # Movie inspect: single-file diagnostic
├── movie_junk.py                # Movie junk: size-first video markers + sidecar spam detection
├── movie_omdb.py                # Server-side OMDb rating lookups and cache
├── movie_replacement_queue.py   # Replacement queue: persistent state for movie triage families
├── movie_subtitle_fix.py        # Subtitle repair: lossless MKV remux for subtitle default flags
├── movie_subtitle_history.py    # Subtitle fix audit log: persistent history for fixed and review-only items
├── movie_canonical_lists.py     # Canonical list coverage: TMDb list fetching and library matching
├── movie_identity.py            # Movie title/year parsing shared across scan and plan
├── probe_cache.py               # Persistent ffprobe result cache (keyed by path + mtime)
├── quality_review.py            # Quality review helpers
├── web/                         # Built-in HTTP server package: routes, state, activity, serializers, asset serving
├── web_assets/                  # Package-managed HTML, CSS, and JS for the local web UI
├── __init__.py
└── __main__.py                  # python -m normal entry point

tests/                           # Unit tests
docs/                            # User and agent documentation
```

## Module ownership

- **Movie normalization pipeline**: `movie_plan.py` → `movie_apply.py`
- **Movie quality pipeline**: `movie_scan.py` → `movie_profile.py` → `movie_inspect.py` → `movie_junk.py`
- **Movie audio packaging repair**: `movie_profile.py` → `movie_audio_fix.py`
- **Movie subtitle repair**: `movie_profile.py` → `movie_subtitle_fix.py` → `movie_subtitle_history.py`
- **Probe caching**: `probe_cache.py` — persistent per-file ffprobe cache; shared by profile, junk, export, and inspect
- **Web layer**: `web/` + `web_assets/` — stdlib `http.server`, package-managed frontend assets, no external framework
- **Shared data contract**: `models.py` — `ProposedChange` is the core type crossing module boundaries
- **Persistent state**: `movie_replacement_queue.py` writes to `~/.local/share/normal/movie-replacement-queue.json`; `movie_subtitle_history.py` writes to `~/.local/share/normal/subtitle-fix-history.json`

## Current backend posture

Two backend themes matter to current agent work:

- normalize is now more evidence-driven end to end
- scan economics are now a first-class architectural constraint

That means agents should treat planner evidence, serializer shape, and scan execution cost as linked concerns rather than separate cleanup tasks.

## Entry points

```bash
# CLI
python3 -m normal <command> [flags]
normal <command> [flags]         # after pip install

# Tests
python3 -m unittest discover -s tests
python3 -m unittest tests.internal.movie_one_shot_live_acceptance

# Web server
source .venv/bin/activate
python3 -m normal web --host 127.0.0.1 --port 8765 --source /path/to/library
```

## Launch contract

When the user asks to start the web UI, open the app, or provide the localhost link, treat that as a request for a clean launch, not a minimal process spawn.

If a change touches `normal/web/` or otherwise requires a server restart to go live, restart the local web UI as part of finishing the task and include the localhost link in the completion report so the user can test immediately.

A clean launch must:

1. use the repo virtual environment
2. load the canonical local env source before server start
3. preserve configured API-backed features
4. verify the localhost page responds before reporting success

Current local env posture:

- `OMDB_KEY` and `TMDB_KEY` are exported from `.venv/bin/activate`. Sourcing the venv is sufficient to load them.
- If the web UI is started by an agent, do not launch it via a bare venv interpreter path if that bypasses env loading.

Minimum preflight before reporting success:

- `python3` resolves inside the repo venv
- required binaries for the requested workflow are present (`ffprobe` for movie workflows)
- `TMDB_KEY` is loaded if the requested workflow includes Movies / Canonical Lists
- localhost responds on the chosen port

## Data models

### ProposedChange (models.py)

Core type used throughout the plan/apply pipeline:

| Field | Type | Description |
|---|---|---|
| `item_id` | str | Stable identifier for the change |
| `change_type` | str | `tag_edit`, `file_rename`, or `folder_rename` |
| `current_value` | str | Existing value |
| `proposed_value` | str | Proposed replacement value |
| `confidence` | str | `safe` or `review` |
| `reason` | str | Human-readable reason for the change |

### Movie scan report (JSON)

One entry per file. Key fields: `path`, `status`, `triage_score`, `quality_score`, `replacement_priority_score`, `replacement_priority_label`, `replacement_year_hint`, plus bitrate, runtime, codec, and reason columns.

`triage_score = quality_score × replacement_priority_score`

Movie `facts` now also carry normalized main-audio display fields for scan/export/UI reuse:

- `audio_display_stream_index`
- `audio_format_family`
- `audio_format_variant`
- `audio_channel_layout`
- `audio_immersive_extension`
- `audio_summary`

`audio_summary` is the user-facing label for the playback-relevant stream, usually the sole default audio stream or else the first audio stream. Typical values: `AAC 2.0`, `Dolby Digital 5.1`, `Dolby Digital Plus 5.1 Atmos`, `Dolby TrueHD 7.1 Atmos`, `DTS-HD MA 5.1`.

`audio_bitrate_kbps` is always sourced from the display stream (chosen by `choose_display_audio_stream`), not stream index 0. When the display stream has no per-stream bitrate in the container, `media_facts_from_ffprobe_payload` falls back in order: (1) container-level estimate (`total − video − other_audio`), valid only when video bitrate is per-stream; (2) `codec_bitrate_floor` — a conservative minimum for known lossless codecs (TrueHD, DTS-HD MA, DTS-HD HRA, FLAC, PCM). When the floor is used, `audio_bitrate_estimated = True` is set on `MediaFacts` and the UI renders the value as `3,000+ kbps est.` Lossy codecs (AAC, AC3, EAC3, plain DTS) return `None` from the floor and display `—` if no container bitrate is available. Do not regress to stream-index-0 selection; the display stream and the bitrate must remain aligned.

Replacement priority by decade:

| Year range | Multiplier |
|---|---|
| ≤ 1989 | 0.60 |
| 1990–1999 | 0.75 |
| 2000–2009 | 0.90 |
| 2010–2019 | 1.00 |
| 2020+ | 1.10 |

### Movie profile report (JSON)

Per-file classification against repo-local movie standards. The scan now carries two parallel layers:

- action labels: `replacement_candidate`, `needs_review`
- quality stances: `standard_definition`, `library_grade`, `collector_grade`, `reference`

`deleted, awaiting replacement` remains replacement-queue state rather than a per-file profile label. Heuristic finding categories: `playback_risk`, `indexing_visibility_risk`, `standards_review`, `standards_failure`.

Notable heuristic families: `dts_no_compat_track`, `anime_subtitle_attachment_risk`, `multi_audio_anime_mux_risk`, `high_complexity_hevc_tv_risk`, `episodic_naming_parse_risk`, `anime_absolute_numbering_risk`, `attachment_heavy_visibility_risk`, `default_non_english_audio`, `default_non_english_audio_with_weak_english`.

The dashboard payload also carries `movie_standards`, `movie_standards_revision`, `quality_profile_definitions`, and `replacement_candidate_definition`. The movie dashboard uses that payload to split **Action Based** cards from **Quality Profile** cards, summarize each rule shape, and expose inline definition controls on the quality-profile cards and Replacement Candidate card. Do not reintroduce per-profile allowed audio codec controls; audio codec arrays may exist in older standards files, but profile matching now relies on channel/bitrate floors, vintage channel exemptions, hygiene toggles, and `require_lossless_audio`.

Quality stance channel matching supports two graduated exemptions:

- `audio_channels_vintage_cutoff` — exempts films with year < cutoff from the channel minimum entirely (pre-surround era). Options: 1970, 1980, 1985, 1990, 1999.
- `audio_channels_atmos_cutoff` — exempts films with year < cutoff from an 8-channel requirement down to 6 channels (pre-Atmos era). Only fires when the stance requires > 6 channels and the film has ≥ 6. Options: 2005, 2010, 2015. Intended to cover films that received 5.1 lossless mixes and will never get an Atmos re-release.

Both cutoffs are persisted in `movie_standards.json` per stance and exposed as select controls in the inline quality-profile card editor.

Each profile card (both Action Based and Quality Profile) has a **View** button that swaps `mainContent` inline to a Quality Profile Inspector: a sortable table of titles in that tier with columns: Title, Year, Resolution, Codec, Ch, Raw Audio, Norm. Audio, Video Bitrate, File Size. Resolution is derived from `facts.resolution_bucket` and sorted by rank (SD < 720p < 1080p < 2160p). Title and year are parsed from the filename stem via `^(.+?)\s*\((\d{4})\)` — `MovieProfileItem` carries no separate title/year fields. The inspector is state-driven (`state.movieProfileInspectorLabel`, `state.movieProfileInspectorType`, `state.movieProfileInspectorSort`) and cleared on any `setPage` call. A "← Back to Dashboard" button restores the card view. The View button is suppressed when count is 0. If the payload has no `movies` (cached/snapshot-only), the inspector shows an empty-state prompt instead of a table.

**Norm. Audio** is a front-end-only perceptually normalized bitrate expressed as an AC3-equivalent figure. Multipliers by `audio_format_family`: AAC 1.30×, EAC3 1.12×, DTS (lossy) 0.95×, AC3 1.00× (baseline). Lossless families (TrueHD, DTS-HD, FLAC, PCM) display "Lossless" with no numeric value. The multiplier tapers linearly toward 1.0 between 75 kbps/channel and 110 kbps/channel (AC3-eq space), scaling with channel count — 450–660 kbps for 5.1, 600–880 kbps for 7.1. Above the upper threshold the cell shows `≥N kbps eq.` rather than a precise figure, since codec differences become perceptually negligible. The column sorts on the normalized value; Raw Audio sorts on the original `audio_bitrate_kbps`. All math lives in `normalizeAudioBitrate()` and `fmtNormAudioBitrate()` in `normal/web_assets/app.js` — no scan-side changes. Do not bake these multipliers into the scan infrastructure.

Dashboard movie profile scans stream file discovery and do not pre-count the whole tree. If you touch scan observability, preserve forward guidance that is true for streamed scans: processed file count, elapsed time, current probe target when available, and ETA/percent only when the backend has a real bounded total.

Movie bitrate histograms are derived aggregates, not durable state. Full dashboard scans build them from the `movie-profile` report. Partial web mutations that already have the current `movies` payload rebuild only the histogram aggregate through the lightweight dashboard histogram route, then refresh the browser dashboard cache.

### Replacement queue (JSON)

Path: `~/.local/share/normal/movie-replacement-queue.json`

Keyed by source directory. Each item also carries `issue_family`, `issue_code`, and `issue_label`.

- `weak_encode` items complete when a future scan finds the same title/year and it is no longer a strict weak encode.
- `audio_packaging` items complete when a future scan finds the same title/year and it no longer matches the queued audio-packaging issue family.

### Subtitle fix history (JSON)

Path: `~/.local/share/normal/subtitle-fix-history.json`

Keyed by source directory. Each item carries `item_id` (SHA256[:16] of `source_root + path + entry_type`), `source_root`, `path`, `title`, `year`, `issue_code`, `entry_type` (`fixed` or `review_only`), `recorded_at`, `updated_at`, and `dismissed_at` (null until dismissed).

- `review_only` items are upserted from the profile scan result each time the subtitle-readiness page loads; they represent files with subtitle issues that cannot be auto-repaired.
- `fixed` items are written when the subtitle repair action completes successfully.
- Dismissal sets `dismissed_at`; items are never deleted.

## Web API routes

Routes are registered from the `normal/web/` package. Key families:

| Route | Method | Description |
|---|---|---|
| `/api/activity?source=...` | GET | Current normal / ffprobe / ffmpeg activity for a source |
| `/api/library-roots` | GET / POST | Load or save main and recent library roots |
| `/api/source/scan-warning` | POST | Detect risky scan sources such as drive-root style paths and NTFS/FUSE mounts and return a confirmation warning payload |
| `/api/movies/apply` | POST | Apply selected movie renames in-place |
| `/api/movies/profile` | POST | Shared movie profile payload for dashboard, weak encode triage, audio packaging triage, and subtitle-readiness triage |
| `/api/movies/dashboard/histogram` | POST | Rebuild movie dashboard histogram aggregates from the current in-memory `movies` payload after partial web mutations |
| `/api/movies/standards/update` | POST | Persist repo-local movie-standards edits from dashboard quality-profile cards; rejects stale saves when the standards revision no longer matches |
| `/api/movies/canonical-lists` | POST | Canonical title coverage payload from TMDb plus local cache |
| `/api/movies/omdb/ratings` | POST | Batch IMDb rating lookup for replacement history using OMDb, local title cleanup, and cache |
| `/api/movies/register` | POST | Inline movie catalogue export as XLSX download |
| `/api/movies/inspect` | POST | One-file movie diagnostic payload |
| `/api/movies/normalize` | POST | Build movie normalize plan |
| `/api/movies/junk` | POST | Combined junk scan: marker-based videos + sidecar spam docs |
| `/api/movies/junk/delete` | POST | Delete selected junk files |
| `/api/movies/replacement-queue/list` | POST | Queue state for current source, optionally filtered by issue family |
| `/api/movies/replacement-queue/add` | POST | Add movie triage items to the queue |
| `/api/movies/replacement-queue/delete` | POST | Delete queued movie triage items and mark them deleted |
| `/api/movies/replacement-queue/dismiss` | POST | Mark deleted movie queue items as dismissed without touching media |
| `/api/movies/audio-packaging/fix` | POST | Lossless MKV remux to fix English-default audio packaging when possible |
| `/api/movies/subtitle-readiness/fix` | POST | Lossless MKV remux to repair embedded subtitle default flags without deleting files |
| `/api/movies/subtitle-readiness/history` | POST | Load subtitle fix history for current source |
| `/api/movies/subtitle-readiness/history/sync` | POST | Upsert review-only items into subtitle history (called after profile scan) |
| `/api/movies/subtitle-readiness/history/dismiss` | POST | Mark subtitle history items as dismissed |

For normalize specifically, the route contract now matters beyond a flat change list:

- movie rows can carry linked serialized changes
- movie rows can carry warning messages, not just warning codes
- this richer row payload is what powers `/normalize-lab` review inspection

## Test boundaries

Keep the web test split aligned with current ownership:

- `tests/test_web.py` covers facade behavior, HTTP routing, asset serving, and end-to-end handler responses.
- direct unit tests for `normal/web/activity.py`, `normal/web/scan_guard.py`, and `normal/web/serializers.py` cover internal behavior in place instead of through `normal.web` re-exports.
- patch internal module symbols at their owning path when needed; avoid patching through the `normal.web` facade unless the facade itself is under test.

If route testing needs to grow, prefer a tiny request/response harness around `RequestContext` or route callables before adding broader server bootstrap for each case.

Internal-only live-library hardening stays out of the default suite. Run it explicitly with:

```bash
NORMAL_TEST_MOVIE_SOURCE=/path/to/Movies \
NORMAL_TEST_MOVIE_PRECLEAN_LEDGER=/path/to/movie-preclean.jsonl \
python3 -m unittest tests.internal.movie_one_shot_live_acceptance
```

## Safety constraints

Hard rules — do not relax without explicit user instruction:

1. `movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `movie-output`, `movie-register` make **no file mutations**.
2. `movie-apply` requires an explicit plan file and never auto-applies from a scan.
3. `movie-apply --target` writes to a new directory; the source is untouched.
4. `movie-apply --in-place` is explicitly opt-in — never infer it from context.
5. Web UI delete routes validate each path against the current source root before unlinking; outside-root paths are rejected.
6. Junk deletion revalidates each candidate as junk immediately before deletion.
7. Movie junk is size-first: marker-backed videos can be high-confidence below 2 GB, 2-4 GB cases require stacked signals before promotion, and marker-only videos at or above 4 GB are ignored.
8. No remote metadata fetching — all data comes from local files only.
9. Heavy recursive web scans are single-flight per source; same-source overlaps are rejected.
10. Heavy movie-side recursive discovery is intentionally streamed rather than fully enumerated up front, because that change was central to reducing the earlier CPU spike and improving cancellation behavior.

Performance improvements do not weaken the source-choice rule. Accidentally scanning a drive root is less punitive than before, but it is still a risky source choice that should trigger warning and explicit confirmation paths in the web flow.

## Intentional design decisions

These are deliberate choices, not gaps:

- **Hardcoded preferences remain the pre-1.0 default.** Quality thresholds and replacement priority weights are mostly in code or repo-local config. Movie normalization now stays concise-only; parser token extraction remains an internal implementation detail for collision and review logic.
- **Movie triage uses a shared scan across all repair workflows.** `Delete Weak Encodes` and `Repair Defaults` (Audio Packaging + Subtitle Readiness sub-tabs) are all backed by the same `movie-profile` report and replacement queue substrate. Keep workflow and UI code shared where possible, but keep issue-family rules separate.
- **Movie profile results are server-side cached.** `MOVIE_PROFILE_CACHE` in `normal/web/state.py` stores the `MovieProfileReport` object keyed by resolved source path. Dashboard, Delete Weak Encodes, and Repair Defaults (both Audio Packaging and Subtitle Readiness tabs) all hit this cache on repeated navigation. The cache is explicitly invalidated after `handle_movies_apply`, `handle_movies_audio_packaging_fix` (when files were fixed), and `handle_movies_subtitle_readiness_fix` (when files were fixed). Response serialisation (`asdict`, histogram, queue reconciliation) happens outside the `ACTIVITY_TRACKER` context so the activity indicator correctly terminates when the last file is probed.
- **Quality profile definition saves do not trigger a rescan.** `POST /api/movies/standards/update` writes `movie_standards.json` and returns the updated definitions. The UI patches `state.results.movies.profile` in-memory and re-renders immediately; profile counts and classifications remain as of the last scan and update on the next user-initiated scan. Do not reintroduce a post-save rescan or reclassification call — even cache-based reclassification is expensive at library scale (~5,500 `build_movie_profile_item` calls).
- **Movie normalize scan walks the directory once.** `build_movie_plan` accepts an optional `movie_files: list[Path] | None` keyword argument. `handle_movies_normalize` and `handle_movies_apply` call `discover_video_files` once and pass the result to all per-style plan builds, eliminating the previous 3× redundant walk.
- **Normalize collision resolution is evidence-first.** Existing-target collisions should first attempt safe alternate concise targets derived from parsed differentiators or local folder context before being left in review. Preserve review for the cases that are still genuinely unresolved.
- **Normalize row serialization is part of the hot path.** Avoid reparsing names, rescanning warning lists, or rebuilding equivalent row detail per movie when indexed or precomputed data can be reused once per request.
- **Movie audio labels are centralized.** Main-audio display strings should come from the shared normalization path, not from per-surface ad hoc codec formatting. Keep scan JSON, CSV/XLSX export, and web tables aligned.
- **`Movies > Plex Compatibility` is hidden in the current UI.** The heuristics live in `movie_profile.py`. The page is suppressed because the workflow isn't concrete enough. Do not re-expose it without a workflow design.
- **No external web framework.** `normal/web/server.py` uses stdlib `http.server`. Keep it that way unless there is a compelling reason to add a dependency.
- **Replacement candidates are standards-driven.** Delete/replace eligibility is based on `profile.weak_candidate`, which is derived from the configured quality-profile cutoff in repo-local `movie_standards.json`.
- **Movie standards persistence is file-backed.** `movie_standards.json` is the authoritative store across server restarts and localhost port changes. Browser dashboard cache is origin-scoped convenience state only.
- **Movie histogram persistence is intentionally absent.** Bitrate histograms are rebuilt from the current movie profile payload. Cached dashboard snapshots may be shown for convenience, but cannot be incrementally trusted when they do not carry `movies`.
- **Movie bitrate charts use mean, not median.** Keep the chart marker aligned with the dashboard average and avoid adding median labels/tooltips back into the crowded SVG.
- **Do not trust stale dashboard state for writes.** The web save path now carries `movie_standards_revision` and rejects a save if another edit changed the file after that dashboard view loaded.
- **Movie standards are dashboard-owned.** The card for each movie standards class now owns its label, count, summary, and inline definition editor. Edit the rule definition there; do not add a separate parallel settings surface unless the dashboard ownership model clearly breaks down.
- **Replacement queue keeps audit history.** Items move forward through states and are never silently removed. Auto-completion (`completed`) happens on future scans when a replacement appears. Manual dismissal (`dismissed`) is explicit queue state, not media deletion.
- **IMDb ratings are server-side.** Replacement-history ratings go through `/api/movies/omdb/ratings`; do not reintroduce browser-side OMDb key exposure or direct `www.omdbapi.com` calls.
- **Probe cancellation is resolved.** Extended use has not reproduced any condition where a stray `ffprobe` escapes the cancellation safeguards or evades the activity indicator. The activity detector (`find_external_activity`) reliably picks up any lingering process via `ps`. Consider this closed.
- **Latent CPU accumulation after long sessions (open, browser-side).** After several hours of active use — running scans, remux operations, repeated UI interactions — CPU does not settle back to the normal idle range (1–5%) and instead hovers at 5–20% across cores until the normal tab or Firefox itself is closed, at which point it drops immediately. The server process alone does not reproduce this; it appears to be browser-side state accumulation (JS heap, event listeners, DOM churn from repeated re-renders) growing over a long session. Observed on an i5-2600KF; the load is not onerous but is reproducible after sustained work. No fix has been identified yet — do not prematurely attribute it to the Python server or ffprobe.
- **Ubuntu GNOME risk is treated as operationally real.** Large recursive scans on drive-root style paths and NTFS/FUSE mounts have caused desktop instability. Keep the warning and same-source heavy-scan gate in place unless the underlying failure mode is disproven.
- **Do not reintroduce up-front full-tree enumeration in heavy movie web scans.** Moving away from prebuilding the whole recursive path set was a key stability fix, not a cosmetic refactor. Preserve incremental traversal and cancellation checks unless there is a measured reason to change it.
- **Treat this as a portability question, not just a Linux quirk.** The same hygiene may matter differently under Windows Explorer, Finder, desktop search, AV, cloud-sync clients, automounters, and alternate launch/service paths. Avoid assuming current traversal, temp-file, and process-observability behavior carries cleanly across platforms without measurement.
- **No cross-platform guarantees before 1.0.** Linux-first. Windows/macOS rough edges are known and deferred.
- **`--in-place` is always explicit.** Never infer in-place mutation from context; the flag must be present.
- **Canonical list matching uses three-tier fallback.** `_find_inventory_match` in `movie_canonical_lists.py` tries: (1) exact normalized key — `canonical_identity_key(title, year)` strips non-alphanumeric and lowercases both sides; (2) TMDb subtitle fallback — when the TMDb title contains `": "`, also try matching just the part after the colon (handles files named without a franchise prefix where TMDb uses one, e.g. "The Fellowship of the Ring" matching "The Lord of the Rings: The Fellowship of the Ring"); (3) inventory suffix fallback — a pre-built index maps every word-boundary suffix of each inventory title to its key, so a file named with extra franchise words at the front (e.g. "Star Wars Episode V The Empire Strikes Back") matches a TMDb title that is a suffix of it ("The Empire Strikes Back"). Ambiguous suffix matches (two library files share the same suffix+year) are skipped.
- **Configured canonical lists (in order):** `top_100` (Top 100, top_rated, 75%), `top_250` (Top 250, top_rated, 65%), `animation` (Top 50 Animation, genre 16, 60%), `sci_fi` (Sci-Fi, genre 878, 60%), `fantasy` (Fantasy, genre 14, 60%), `action` (Action, genre 28, 60%), `thriller_mystery` (Thriller / Mystery, genres 53+9648, 60%), `documentary` (Top 50 Documentary, genre 99, 60%), `comedy` (Comedy, genre 35, 60%). Badge threshold is the unlock percentage. Do not reinstate `top_1000` or `suspense_horror` — both were removed as poor fits for this library.
- **Canonical list inspector View button is always shown**, including for 0/x lists. Clicking View on a 0/x list shows all N titles in the list as "Missing" — this is intentional so the user can see what to acquire. The profile inspector suppresses View at count 0; the canonical list inspector does not. If `all_entries` is absent (stale cache from before this field was added), the inspector shows a "Re-run to load N titles" prompt with a back button instead of a table. Browser localStorage cache key is `n_movie_canonical_lists_cache_v3`; old v2 caches (without `all_entries`) are discarded on first page load.
