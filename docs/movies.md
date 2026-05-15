# Movies

The movie lane handles five practical problems in a pirated library: inconsistent naming, uneven encode quality, bad multi-audio packaging, messy subtitle defaults, and missing poster artwork.

![Movies dashboard](assets/movies_dashboard_default.png)

## Dashboard

A library-wide view of encode quality — resolution breakdown, quality tier distribution, and bitrate histograms. A good first stop to understand the shape of your collection before deciding what to clean up.

To export a formatted XLSX catalogue of the current library, use the **Export** button on the Movies library card in the Library Switcher (top-left). The button is visible whenever a Movies library path is configured.

Theme examples:

![Movies dashboard, Win95 theme](assets/movies_dashboard_win95.png)

![Movies dashboard, dark theme](assets/movies_dashboard_dark.png)

![Movies dashboard, matrix theme](assets/movies_dashboard_matrix.png)

![Movies dashboard, sand theme](assets/movies_dashboard_sand.png)

## Canonical Lists

The **Canonical Lists** page compares owned titles against live all-time movie lists using TMDb and a local cache. It is title-coverage focused: bitrate, quality tiers, and warning telemetry do not affect the result.

Pass `--tmdb-key` to `normal web` or set `TMDB_KEY` before launch. Current badges are intentionally simple and good enough for first-pass coverage tracking; badge-system refinement is deferred.

## Normalize names

Files named by whoever uploaded them tend to have inconsistent formatting — varying year placement, leftover technical tokens, mismatched folder names. `normal` parses each path locally (no network lookups) and proposes a clean, consistent target shape:

```
Title (Year)/Title (Year).mkv
```

The production normalizer is concise-first and now considered product-complete for movie libraries. Its default **All Results** review shows every scanned video file, including already-normalized items as no-change rows, so the proposed structure preview can show the full selected downstream library shape. Use the **Safe** and **Flagged for review** list filters with **Select All / Deselect All** to narrow or bulk-select the actionable rows.

Verbose naming still exists temporarily in the web UI and CLI as a parser-hardening leftover, but it is scheduled for removal before the broader refactor. The CLI currently supports `--naming-style verbose` for this older technical-token shape:

```
Title (Year) [technical tokens]/Title (Year) [technical tokens].mkv
```

Ambiguous parses and unsafe target collisions are flagged as `review`. Everything else is `safe`. You review the plan before anything moves.

Concise duplicate handling is subtractive but not lossy when two local copies would otherwise collide. If the scan can distinguish them from parsed path or folder-context tokens, it adds the shortest useful suffix to both folder and file stem, such as `Title (Year) 1080p` and `Title (Year) 2160p`. If no local differentiator is available, the collision stays in review rather than inventing `(2)` names.

Normalize also handles common library-chaos cleanup when the evidence is local and high confidence:

- loose root movie files move into `Title (Year)/Title (Year).ext`, including cases where a sibling `.nfo` provides the title/year
- no-video movie-shaped artifact folders can be renamed, merged into an existing concise folder, deleted when they are duplicate metadata-only remnants, or flagged for review when merge safety is unclear
- metadata-only collection/series/trilogy package artifact folders and root AppleDouble `._*` files can be deleted as safe cleanup proposals
- multi-part movie folders such as CD1/CD2 normalize to one movie folder with part labels preserved in filenames
- multi-movie package folders can be split into individual movie folders when each video file, or a same-stem NFO, locally parses to its own title/year; package marker words such as `trilogy` are not treated as movie titles

The parser stays local and heuristic. It prefers a clear ASCII title segment when a filename includes both non-Latin and English title text before the year, and it can split technical-token runs that appear before a trailing parenthesized year. In verbose mode, it keeps selected edition/video details such as `Director's Cut`, `BluRay Remux`, codec, resolution, and HDR tokens while dropping uploader, language, and audio-packaging noise.

## Quality triage

A full movie profile scan now separates **Action Based** cards from **Quality Profile** cards.

Action cards:

| Card | What it means |
|---|---|
| `deleted, awaiting replacement` | File was deleted through the replacement queue and is still waiting for a better copy |
| `replacement_candidate` | Quality profile is at or below the configured replacement cutoff and is eligible for delete/replace triage |
| `needs_review` | Inline review attention needed, often from subtitle/default/hygiene checks |

Quality profile cards:

| Profile | What it means |
|---|---|
| `Standard Definition` | Edge cases and legacy files that are still worth keeping |
| `Library Grade` | Good enough for casual viewing, including compact encodes like Tigole |
| `Collector Grade` | Solid compact encodes that hold up better on difficult material |
| `Reference` | Mild to no visual compression with lossless audio |

The standards definition lives in repo-local `movie_standards.json`. Dashboard View quality-profile cards own the inline **Edit definition** controls. Replacement Candidate uses a simpler inline **Edit** control: choose the quality-profile cutoff, then save to refresh the dashboard. Quality-profile editing no longer exposes per-profile allowed audio codec lists; audio posture is controlled through channel floor, bitrate floor, vintage channel exemption, and **Require lossless audio**.

Dashboard movie profile scans stream progress without pre-counting the whole tree. During a scan, the drive activity bar shows processed file count, elapsed time, current `ffprobe` target when visible, and ETA only when a bounded total is known. This avoids false precision on large rebuilds while still showing forward movement.

Persistence posture:

- `movie_standards.json` is the source of truth across server restarts and localhost port changes
- browser cache is only a per-origin dashboard snapshot; `127.0.0.1:8765` and `127.0.0.1:8766` do not share localStorage
- standards saves now use a revision check, so an older tab or stale cached dashboard is rejected instead of silently overwriting a newer standards file
- writes are done with an atomic temp-file replace so interrupted writes do not leave a partial JSON file behind

The audio channel minimum has a companion **Exempt pre-surround era films** setting. Set it to a release-year cutoff (Pre-1970 through Pre-1990) and films released before that year bypass the channel floor check — useful when Library Grade or higher requires 5.1 but classic titles with mono or stereo-only audio have no higher-channel release to replace them with.

Quality scan results include a normalized main-audio summary for the playback-relevant stream alongside audio bitrate — `AAC 2.0`, `Dolby Digital 5.1`, `Dolby Digital Plus 5.1 Atmos`, `Dolby TrueHD 7.1 Atmos`, `DTS-HD MA 5.1`, and similar labels.

The **Delete Weak Encodes** page lets you select weak files for deletion. Each deleted file goes into a replacement queue — when a better encode for the same title shows up in a future scan, it is automatically marked complete.

Queue history has four hard filters: `Deleted, Awaiting Replacement`, `Replaced`, `Deleted From Queue`, and `All Items`. Deleted rows can be dismissed from queue history inline when the release is no longer worth replacing. That action only changes queue state; it does not touch media files.

The queue-history table is sortable by title, year, and IMDb rating. IMDb ratings are fetched server-side from [OMDb](https://www.omdbapi.com/) and require a free API key passed via `--omdb-key` or the `OMDB_KEY` environment variable. Lookups use local title cleanup plus a small cache, so repeated page loads do not keep spending the OMDb quota. Without a key the column is hidden; when OMDb is rate-limited, new cells show `limit` and cached ratings still display.

## Multi-audio packaging triage

Some MKVs are muxed with the wrong main audio track: for example, Italian marked as default and a weaker English track left as the fallback. The **Fix Multi-Audio Packaging** page uses the same replacement-queue workflow as weak encode triage, but with different scan rules:

- detect non-English default audio when English is present
- flag the stronger case where the English fallback is materially weaker than the default track
- show the main audio summary plus default-vs-English stream summaries so the queue is explainable before deletion

For MKVs, the page can do an in-place lossless repair that flips the default audio flag to the best English track. It also supports a stricter variant that drops audio streams explicitly tagged as non-English while keeping English and untagged audio. Unsupported containers are left as review-only items. Replacement queue delete/replace is still available for genuinely bad releases.

While a remux is running, the page locks checkbox selection and disables conflicting bulk actions. The destructive **Delete Selected Files** button is separated to the far right of the action row so it is visually distinct from the two repair actions.

Current safety note: **Make English Default** has been exercised against real files. **Make English Default + Delete Foreign Audio** is implemented but currently untested on real libraries and should be treated as a cautious review-only workflow before first public push.

## Subtitle readiness repair

The **Repair Subtitle Readiness** page is a sibling repair lane built on the same movie-profile scan. It follows the current subtitle hygiene stance from the standards engine:

- default to no subtitle when main audio is already English
- default to forced English when a forced English subtitle exists
- default to English subtitles when the default audio track is non-English

This workflow is non-destructive: it does not delete media files or subtitle files, and it does not use the replacement queue. For supported MKVs it can do a lossless in-place remux that only updates embedded subtitle default flags. If the needed English or forced-English subtitle does not exist, the item stays review-only.

Current scope is embedded subtitle streams already inside the container. External `.srt` / `.ass` sidecars are not modified.

## Repair artwork for Plex

The **Repair Artwork for Plex** page scans each movie folder and queries your local Plex server to show exactly what Plex has — or is missing — for each title. The gallery is a direct preview of what Plex displays, using Plex's own artwork via a server-side proxy.

Without a Plex token the lane falls back to scanning local sidecar files only (`poster.jpg` etc.), which does not reflect Plex's actual artwork state.

### Plex token setup

The lane requires a `PLEX_TOKEN` to query your Plex server. Add it to `.venv/bin/activate` alongside the other API keys:

```bash
export PLEX_TOKEN="your_token_here"
```

**How to find your token:**

1. In the Plex web UI, go to **Settings → Troubleshooting → Download logs**.
2. Unzip the downloaded archive — it extracts to a folder named something like `Plex Media Server Logs_YYYY-MM-DD_HH-MM-SS`.
3. Run this command against the extracted folder (substituting the actual folder name):

```bash
grep -rho 'X-Plex-Token=[A-Za-z0-9_-]\{10,\}' ~/Downloads/"Plex Media Server Logs_YYYY-MM-DD_HH-MM-SS"/ | head -1
```

Note: the token will display as `xxxxxxxxxxxxxxxxxxxx` in terminal output — this is Claude Code masking sensitive values. Copy the raw value directly from a text editor instead: open any `Plex Media Server.log` file from the extracted folder and search for `X-Plex-Token=`. The token is the alphanumeric string immediately after the `=`.

Alternatively, if you have `sudo` access on the server machine, read it directly from Plex's preferences file:

```bash
sudo grep -o 'PlexOnlineToken="[^"]*"' "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Preferences.xml"
```

After adding the token, restart the `normal` web server for it to take effect.

### How it works with a token

- **Present (blue chip):** Plex has artwork for this title.
- **Missing (red chip):** Plex knows the title but has no poster — this is the actionable case. Drop a poster image onto the tile to write `poster.jpg` to the folder; Plex will pick it up on its next scan.
- Titles not yet indexed by Plex fall back to local sidecar detection.
- Grid sort order mirrors Plex's own alphabetisation (articles dropped, numeric-aware).

### Local sidecar detection (no token)

Recognized poster filenames: `poster.jpg`, `poster.png`, `folder.jpg`, `folder.png`, and `{movie-filename}-poster.jpg` for flat libraries. Missing posters and low-quality images — under 30 KB or smaller than 400×600 px — are flagged.

The write target is always `poster.jpg` in the movie folder.

### Finding and dragging poster art

The recommended workflow: open `normal` on one half of your screen and an image source — Google Images, a movie database site, or your file manager — on the other half. Drag poster images directly onto a movie tile or into the drop zone in the detail panel.

The image must be a real image resource that the browser has loaded, not an HTML-framed thumbnail. The practical distinction:

- **Works:** The large preview image in Google Images' right-side panel (after clicking a result). An image URL opened directly in its own browser tab. An image file dragged from your file manager.
- **May not work:** Small thumbnails in a search result grid. Images inside complex page layouts where the dragged element is a styled `div`, not an `<img>` tag.

A quick test: right-click the image → **Open Image in New Tab**. If the browser shows it as a standalone image with no surrounding page chrome, that image is draggable. Drag from that tab.

Accepted formats: JPEG and PNG. All sources are converted to JPEG on write.

### What gets written

`poster.jpg` in the movie folder. Plex reads this path directly. The preview in `normal` loads from the same location, so what you see in the gallery is what Plex shows.

## Junk cleanup

Two pages handle library noise:

- **Delete Junk Videos** — samples, featurettes, and shorts, detected by path tokens and duration
- **Delete Junk Sidecar & Spam Files** — promo PDFs, NFO files, and other non-video sidecars

Both show a preview list before anything is deleted.

## Catalogue export

Export a formatted XLSX of your full library: title, year, resolution, video codec, audio, container, file size — sorted alphabetically.

```bash
normal movie-register --report scan.json --xlsx catalogue.xlsx
```

The `Audio` column uses the same normalized main-audio summary as the scan and web UI.

## Web UI pages

| Page | What it does |
|---|---|
| Dashboard | Quality overview — tiers, histograms, resolution breakdown. Export XLSX catalogue via Library Switcher. |
| Normalize | Review and apply rename plans |
| Delete Weak Encodes | Triage and queue replacements |
| Fix Multi-Audio Packaging | Detect wrong-language defaults, remux MKVs to prefer English, optionally drop tagged foreign-language audio, or queue replacements |
| Repair Subtitle Readiness | Repair embedded subtitle defaults for supported MKVs without deleting files |
| Repair Artwork for Plex | Movie poster gallery with drag-and-drop apply; writes poster.jpg to each movie folder |
| Delete Junk Videos | Remove samples and featurettes |
| Delete Junk Sidecar & Spam Files | Remove sidecar and spam files |
| Canonical Lists | Compare owned titles against live all-time movie lists and unlock simple coverage badges |

## Known issue

There is an open issue around movie probes not always unwinding cleanly when a scan is cancelled and another UI action starts immediately after. Exact reproduction conditions are still unknown. In some cases a background `ffprobe` keeps running and is not visible through the current Drive Activity `ps` check.

Low priority parsing edge case: some low-quality multi-movie pack names can leak genre-style tokens such as `Sci Fi` into the parsed title when those tokens appear before the year. Current guidance is to treat those as local repair cases rather than broaden the parser heuristics.
