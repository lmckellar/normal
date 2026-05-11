# Agent reference

For AI agents and developers working in this codebase. Covers repo structure, module ownership, data models, API routes, safety constraints, and intentional design decisions.

## Repo map

```
normal/
├── cli.py                       # CLI entry point and command dispatch
├── commands.py                  # Music command implementations (scan, plan, apply, output)
├── models.py                    # Shared data models — ProposedChange and core types
├── scan.py                      # Music scan: reads FLAC tags, groups into albums, emits issues
├── plan.py                      # Music plan: proposes tag edits, renames, folder moves
├── apply.py                     # Music apply: executes an existing plan file
├── output.py                    # Music CSV export + movie XLSX register (movie-register)
├── movie_scan.py                # Movie scan: ffprobe probing, quality scoring, triage
├── movie_plan.py                # Movie plan: title/year parsing, rename proposals
├── movie_profile.py             # Movie profile: quality ladder classification, heuristic findings
├── movie_audio_fix.py           # Movie audio packaging repair: lossless MKV remux helpers
├── movie_inspect.py             # Movie inspect: single-file diagnostic
├── movie_junk.py                # Movie junk: sample/featurette/short detection
├── movie_replacement_queue.py   # Replacement queue: persistent state for movie triage families
├── music_profile.py             # Music profile: format/fidelity classification for dashboard
├── music_replacement_queue.py   # Music replacement queue (parallel structure to movie queue)
├── quality_review.py            # Quality review helpers
├── artwork.py                   # Artist artwork: Jellyfin sidecar fetch, candidate approval, write
├── web.py                       # Built-in HTTP server + all web API route handlers
├── __init__.py
└── __main__.py                  # python -m normal entry point

tests/                           # Unit and fixture-based tests
fixtures/                        # Sample FLAC albums for scan/plan/apply/output tests
docs/                            # User and agent documentation
```

## Module ownership

- **Music normalization pipeline**: `scan.py` → `plan.py` → `apply.py` → `output.py`
- **Movie normalization pipeline**: `movie_plan.py` → `movie_apply` (in `commands.py`)
- **Movie quality pipeline**: `movie_scan.py` → `movie_profile.py` → `movie_inspect.py` → `movie_junk.py`
- **Movie audio packaging repair**: `movie_profile.py` → `movie_audio_fix.py`
- **Web layer**: `web.py` — all HTTP routes in one file; stdlib `http.server`, no external framework
- **Shared data contract**: `models.py` — `ProposedChange` is the core type crossing module boundaries
- **Persistent state**: `movie_replacement_queue.py` writes to `~/.local/share/normal/movie-replacement-queue.json`

## Entry points

```bash
# CLI
python3 -m normal <command> [flags]
normal <command> [flags]         # after pip install

# Tests
python3 -m unittest discover -s tests

# Web server
source .venv/bin/activate
python3 -m normal web --host 127.0.0.1 --port 8765 --source /path/to/library
```

## Launch contract

When the user asks to start the web UI, open the app, or provide the localhost link, treat that as a request for a clean launch, not a minimal process spawn.

If a change touches `web.py` or otherwise requires a server restart to go live, restart the local web UI as part of finishing the task and include the localhost link in the completion report so the user can test immediately.

A clean launch must:

1. use the repo virtual environment
2. load the canonical local env source before server start
3. preserve configured API-backed features
4. verify the localhost page responds before reporting success

Current local env posture:

- Keep durable local API config outside `.venv/bin/activate`.
- Do not store or rely on secrets embedded in venv activation scripts; venv recreation can wipe them.
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

### Music scan / plan report (JSON)

Top-level keys: `source_root`, `generated_at`, `ruleset_version`, `tracks`, `albums`, `proposed_changes`, `warnings`

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

The dashboard payload also carries `movie_standards`, `movie_standards_revision`, `quality_profile_definitions`, and `replacement_candidate_definition`. The movie dashboard uses that payload to split **Action Based** cards from **Quality Profile** cards, summarize each rule shape, and expose inline definition controls on the quality-profile cards and Replacement Candidate card.

Movie bitrate histograms are derived aggregates, not durable state. Full dashboard scans build them from the `movie-profile` report. Partial web mutations that already have the current `movies` payload rebuild only the histogram aggregate through the lightweight dashboard histogram route, then refresh the browser dashboard cache.

### Replacement queue (JSON)

Path: `~/.local/share/normal/movie-replacement-queue.json`

Keyed by source directory. Each item also carries `issue_family`, `issue_code`, and `issue_label`.

- `weak_encode` items complete when a future scan finds the same title/year and it is no longer a strict weak encode.
- `audio_packaging` items complete when a future scan finds the same title/year and it no longer matches the queued audio-packaging issue family.

### Artwork provenance (JSON)

Path: `Album Artist/artist.normal-artwork.json`

Written alongside low-confidence artwork writes. Stores source label (`low confidence album`, `low confidence web`, `low confidence wikimedia`, `low confidence Bing`, `low confidence dropped image`). Rescans use it to restore labels. Deleting the file manually re-labels the image as a verified local sidecar on the next scan.

## Web API routes

All routes in `web.py`. Key families:

| Route | Method | Description |
|---|---|---|
| `/api/activity?source=...` | GET | Current normal / ffprobe / ffmpeg activity for a source |
| `/api/library-roots` | GET / POST | Load or save main and recent library roots |
| `/api/source/scan-warning` | POST | Detect risky scan sources such as drive-root style paths and NTFS/FUSE mounts and return a confirmation warning payload |
| `/api/music/apply` | POST | Apply selected music changes in-place |
| `/api/music/profile` | POST | Music dashboard profile / weak encode triage payload |
| `/api/music/normalize` | POST | Build music normalize plan |
| `/api/music/replacement-queue/list` | POST | Music replacement queue for current source |
| `/api/music/replacement-queue/add` | POST | Add music profile items to queue |
| `/api/music/replacement-queue/delete` | POST | Delete queued music items and mark them deleted |
| `/api/music/artwork/scan` | POST | Artist artwork scan |
| `/api/music/artwork/candidates` | POST | Candidate discovery for one artist |
| `/api/music/artwork/image-search` | POST | Paginated image-search candidates for one artist |
| `/api/music/artwork/apply` | POST | Apply approved artwork candidates |
| `/api/music/artwork/backfill-jellyfin` | POST | Copy local artist sidecars into Jellyfin metadata cache |
| `/api/music/artwork/promote` | POST | Promote a cached/approved artwork candidate |
| `/api/music/artwork/image?...` | GET | Serve artwork preview image bytes |
| `/api/movies/apply` | POST | Apply selected movie renames in-place |
| `/api/movies/profile` | POST | Shared movie profile payload for dashboard, weak encode triage, audio packaging triage, and subtitle-readiness triage |
| `/api/movies/dashboard/histogram` | POST | Rebuild movie dashboard histogram aggregates from the current in-memory `movies` payload after partial web mutations |
| `/api/movies/standards/update` | POST | Persist repo-local movie-standards edits from dashboard quality-profile cards; rejects stale saves when the standards revision no longer matches |
| `/api/movies/canonical-lists` | POST | Canonical title coverage payload from TMDb plus local cache |
| `/api/movies/register` | POST | Inline movie catalogue export as XLSX download |
| `/api/movies/inspect` | POST | One-file movie diagnostic payload |
| `/api/movies/normalize` | POST | Build movie normalize plan |
| `/api/movies/junk` | POST | Junk video scan |
| `/api/movies/promo-docs` | POST | Sidecar and spam-file scan |
| `/api/movies/junk/delete` | POST | Delete selected junk files |
| `/api/movies/replacement-queue/list` | POST | Queue state for current source, optionally filtered by issue family |
| `/api/movies/replacement-queue/add` | POST | Add movie triage items to the queue |
| `/api/movies/replacement-queue/delete` | POST | Delete queued movie triage items and mark them deleted |
| `/api/movies/replacement-queue/dismiss` | POST | Mark deleted movie queue items as dismissed without touching media |
| `/api/movies/audio-packaging/fix` | POST | Lossless MKV remux to fix English-default audio packaging when possible |
| `/api/movies/subtitle-readiness/fix` | POST | Lossless MKV remux to repair embedded subtitle default flags without deleting files |

## Safety constraints

Hard rules — do not relax without explicit user instruction:

1. `scan`, `plan`, `movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `output`, `movie-output`, `movie-register` make **no file mutations**.
2. `apply` and `movie-apply` require an explicit plan file and never auto-apply from a scan.
3. `apply --target` writes to a new directory; the source is untouched.
4. `apply --in-place` is explicitly opt-in — never infer it from context.
5. Web UI delete routes validate each path against the current source root before unlinking; outside-root paths are rejected.
6. Junk deletion revalidates each candidate as junk immediately before deletion.
7. No remote metadata fetching — all data comes from local files only.
8. Heavy recursive web scans are single-flight per source; same-source overlaps are rejected.
9. Heavy movie-side recursive discovery is intentionally streamed rather than fully enumerated up front, because that change was central to reducing the earlier CPU spike and improving cancellation behavior.

## Intentional design decisions

These are deliberate choices, not gaps:

- **Hardcoded preferences over UI controls (pre-1.0 posture).** Quality thresholds, replacement priority weights, normalization rules are mostly in code. The adjustment path is repo/agent edits until the roadmap's normalization controls and 1.0 UI work land.
- **Movie triage now has separate lanes on one shared scan.** `Delete Weak Encodes` and `Fix Multi-Audio Packaging` are sibling workflows backed by the same `movie-profile` report and the same replacement queue substrate. Keep workflow/UI code shared where possible, but keep issue-family rules separate.
- **Movie audio labels are centralized.** Main-audio display strings should come from the shared normalization path, not from per-surface ad hoc codec formatting. Keep scan JSON, CSV/XLSX export, and web tables aligned.
- **`Movies > Plex Compatibility` is hidden in the current UI.** The heuristics live in `movie_profile.py`. The page is suppressed because the workflow isn't concrete enough. Do not re-expose it without a workflow design.
- **Music normalization is FLAC-only.** MP3 appears in dashboard profile views but is not a normalization target before 1.0.
- **No external web framework.** `web.py` uses stdlib `http.server`. Keep it that way unless there is a compelling reason to add a dependency.
- **Replacement candidates are standards-driven.** Delete/replace eligibility is based on `profile.weak_candidate`, which is derived from the configured quality-profile cutoff in repo-local `movie_standards.json`.
- **Movie standards persistence is file-backed.** `movie_standards.json` is the authoritative store across server restarts and localhost port changes. Browser dashboard cache is origin-scoped convenience state only.
- **Movie histogram persistence is intentionally absent.** Bitrate histograms are rebuilt from the current movie profile payload. Cached dashboard snapshots may be shown for convenience, but cannot be incrementally trusted when they do not carry `movies`.
- **Movie bitrate charts use mean, not median.** Keep the chart marker aligned with the dashboard average and avoid adding median labels/tooltips back into the crowded SVG.
- **Do not trust stale dashboard state for writes.** The web save path now carries `movie_standards_revision` and rejects a save if another edit changed the file after that dashboard view loaded.
- **Movie standards are dashboard-owned.** The card for each movie standards class now owns its label, count, summary, and inline definition editor. Edit the rule definition there; do not add a separate parallel settings surface unless the dashboard ownership model clearly breaks down.
- **Replacement queue keeps audit history.** Items move forward through states and are never silently removed. Auto-completion (`completed`) happens on future scans when a replacement appears. Manual dismissal (`dismissed`) is explicit queue state, not media deletion.
- **Probe cancellation is not fully hardened yet.** There is a known open issue where cancelling a movie scan and quickly starting another UI action can leave a background `ffprobe` running, and the activity indicator may miss it. Do not document cancellation as stronger than best-effort until that is fixed.
- **Ubuntu GNOME risk is treated as operationally real.** Large recursive scans on drive-root style paths and NTFS/FUSE mounts have caused desktop instability. Keep the warning and same-source heavy-scan gate in place unless the underlying failure mode is disproven.
- **Do not reintroduce up-front full-tree enumeration in heavy movie web scans.** Moving away from prebuilding the whole recursive path set was a key stability fix, not a cosmetic refactor. Preserve incremental traversal and cancellation checks unless there is a measured reason to change it.
- **Treat this as a portability question, not just a Linux quirk.** The same hygiene may matter differently under Windows Explorer, Finder, desktop search, AV, cloud-sync clients, automounters, and alternate launch/service paths. Avoid assuming current traversal, temp-file, and process-observability behavior carries cleanly across platforms without measurement.
- **No cross-platform guarantees before 1.0.** Linux-first. Windows/macOS rough edges are known and deferred.
- **`--in-place` is always explicit.** Never infer in-place mutation from context; the flag must be present.
