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
├── movie_inspect.py             # Movie inspect: single-file diagnostic
├── movie_junk.py                # Movie junk: sample/featurette/short detection
├── movie_replacement_queue.py   # Replacement queue: persistent state for deleted weak encodes
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
- **Web layer**: `web.py` — all HTTP routes in one file; stdlib `http.server`, no external framework
- **Shared data contract**: `models.py` — `ProposedChange` is the core type crossing module boundaries
- **Persistent state**: `movie_replacement_queue.py` writes to `~/.local/share/normal/movie-replacement-queue.json`

## Entry points

```bash
# CLI
python3 -m normal <command> [flags]
normal <command> [flags]         # after pip install

# Tests
python3 -m pytest tests/

# Web server (local workstation note: use python3 -m normal, not python)
python3 -m normal web --host 127.0.0.1 --port 8765 --source /path/to/library
```

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

Replacement priority by decade:

| Year range | Multiplier |
|---|---|
| ≤ 1989 | 0.60 |
| 1990–1999 | 0.75 |
| 2000–2009 | 0.90 |
| 2010–2019 | 1.00 |
| 2020+ | 1.10 |

### Movie profile report (JSON)

Per-file classification against the quality ladder. See `docs/commands.md` for the full ladder table. Heuristic finding categories: `playback_risk`, `indexing_visibility_risk`.

Notable heuristic families: `dts_no_compat_track`, `anime_subtitle_attachment_risk`, `multi_audio_anime_mux_risk`, `high_complexity_hevc_tv_risk`, `episodic_naming_parse_risk`, `anime_absolute_numbering_risk`, `attachment_heavy_visibility_risk`.

### Replacement queue (JSON)

Path: `~/.local/share/normal/movie-replacement-queue.json`

Keyed by source directory. Each item: `path`, `title`, `year`, `status` (`pending` → `deleted` → `completed`), deletion metadata. Future profile scans auto-complete `deleted` items when a non-weak encode for the same title/year appears.

### Artwork provenance (JSON)

Path: `Album Artist/artist.normal-artwork.json`

Written alongside low-confidence artwork writes. Stores source label (`low confidence album`, `low confidence web`, `low confidence wikimedia`, `low confidence Bing`, `low confidence dropped image`). Rescans use it to restore labels. Deleting the file manually re-labels the image as a verified local sidecar on the next scan.

## Web API routes

All routes in `web.py`. Key families:

| Route | Method | Description |
|---|---|---|
| `/api/music/scan` | GET | Full music scan |
| `/api/music/apply` | POST | Apply selected music changes in-place |
| `/api/music/profile` | GET | Music dashboard profile |
| `/api/music/artwork` | GET | Artist artwork scan |
| `/api/music/artwork/save` | POST | Write approved artwork for one artist |
| `/api/music/artwork/write-selected` | POST | Bulk write selected Jellyfin-cache candidates |
| `/api/music/artwork/sync-jellyfin` | POST | Copy library sidecars into Jellyfin metadata cache |
| `/api/movies/scan` | GET | Movie quality scan |
| `/api/movies/apply` | POST | Apply selected movie renames in-place |
| `/api/movies/profile` | GET | Movie quality profile |
| `/api/movies/junk` | GET | Junk video scan |
| `/api/movies/junk/delete` | POST | Delete selected junk files |
| `/api/movies/misc-junk` | GET | Promo document scan |
| `/api/movies/misc-junk/delete` | POST | Delete selected promo documents |
| `/api/movies/replacement-queue` | GET | Queue state for current source |
| `/api/movies/delete-encodes` | POST | Delete selected weak encodes and update queue |
| `/api/movies/catalogue` | GET | Inline catalogue scan for XLSX download |

## Safety constraints

Hard rules — do not relax without explicit user instruction:

1. `scan`, `plan`, `movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `output`, `movie-output`, `movie-register` make **no file mutations**.
2. `apply` and `movie-apply` require an explicit plan file and never auto-apply from a scan.
3. `apply --target` writes to a new directory; the source is untouched.
4. `apply --in-place` is explicitly opt-in — never infer it from context.
5. Web UI delete routes validate each path against the current source root before unlinking; outside-root paths are rejected.
6. Junk deletion revalidates each candidate as junk immediately before deletion.
7. No remote metadata fetching — all data comes from local files only.

## Intentional design decisions

These are deliberate choices, not gaps:

- **Hardcoded preferences over UI controls (v1 posture).** Quality thresholds, replacement priority weights, normalization rules are in code. The adjustment path is repo/agent edits. This is the core v1 stance; v2 changes it.
- **`Movies > Plex Compatibility` is hidden in the v1 UI.** The heuristics live in `movie_profile.py`. The page is suppressed because the workflow isn't concrete enough. Do not re-expose it without a workflow design.
- **Music normalization is FLAC-only.** MP3 appears in dashboard profile views but is not a normalization target in v1.
- **No external web framework.** `web.py` uses stdlib `http.server`. Keep it that way unless there is a compelling reason to add a dependency.
- **Strict weak encode profiles.** Strict weak = `sd_low_quality`, `weak_1080p`, `weak_4k`, `unclassified`. `minimum_acceptable_1080p` and above are never shown as deletion candidates in the default view. Do not change this threshold without explicit instruction.
- **Replacement queue is append-only from the tool.** Items move forward through states but are never silently removed. Auto-completion (`completed`) happens on future scans when a replacement appears.
- **No cross-platform guarantees for v1.** Linux-first. Windows/macOS rough edges are known and deferred.
- **Adult video register is not implemented.** It is spec'd in detail but intentionally kept isolated from the general movie pipeline if built.
- **`--in-place` is always explicit.** Never infer in-place mutation from context; the flag must be present.
