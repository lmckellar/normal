# Quick start

## Music lane

The music pipeline is: scan → plan → review → apply.

### 1. Scan your library

```bash
normal scan --source /path/to/music --report scan.json
```

Reads your FLAC library, groups tracks into albums, and reports tag inconsistencies, naming issues, and likely fixes. Nothing is changed.

### 2. Generate a change plan

```bash
normal plan --source /path/to/music --plan plan.json --summary plan.md
```

Produces a JSON plan with proposed tag edits, file renames, and folder renames. Each change is labelled `safe` or `review`. The optional `--summary` writes a human-readable version alongside it.

### 3. Review

Open `plan.md` (or `plan.json`) and check the `review`-confidence changes. Safe changes are deterministic and low-risk. Review changes need a human decision.

### 4. Apply

Copy to a new directory (recommended for a first run):

```bash
normal apply --source /path/to/music --plan plan.json --target /path/to/cleaned-music
```

Or apply in-place:

```bash
normal apply --source /path/to/music --plan plan.json --in-place
```

An apply report is written to `normal-apply-report.json` in the destination root.

### 5. Export a collection list

```bash
normal output --source /path/to/cleaned-music --csv collection.csv
```

Writes an album-level CSV: artist, album, year, genre, track count, path.

---

## Movie lane

### Normalize file and folder names

```bash
normal movie-plan --source /path/to/movies --plan movie-plan.json --summary movie-plan.md
normal movie-apply --source /path/to/movies --plan movie-plan.json --target /path/to/normalized-movies
```

Parses title, year, and technical tokens from local paths only. Concise `Title (Year)` naming is the default; verbose technical-token naming remains available with `--naming-style verbose`. Ambiguous parses and unresolved concise collisions are flagged as `review`. See [docs/commands.md](commands.md) for naming rules.

### Profile encode quality

```bash
normal movie-scan --source /path/to/movies --report movie-scan.json --progress
```

Profiles each file against the quality ladder using ffprobe metadata. No changes made. Use `--progress` to print live count, elapsed time, and ETA to stderr.

Scan outputs and web tables now include a main-audio summary in addition to bitrate. Typical labels include `AAC 2.0`, `Dolby Digital 5.1`, `Dolby Digital Plus 5.1 Atmos`, `Dolby TrueHD 7.1 Atmos`, and `DTS-HD MA 5.1`.

```bash
normal movie-profile --source /path/to/movies --report movie-profile.json
```

Classifies files into quality tiers and attaches heuristic findings for playback risk and indexing risk.

### Inspect a single file

```bash
normal movie-inspect --path /path/to/file.mkv --report inspect.json
```

Detailed one-file diagnostic view.

### Find junk

```bash
normal movie-junk --source /path/to/movies --report junk.json
```

CLI is report-only. To delete, use the web UI: `Movies > Delete Junk Videos`.
Video junk detection is size-first and path-heuristic-only: marker-backed files under 4 GB are surfaced for review or direct deletion; marker-only files at or above 4 GB are ignored.

### Export a catalogue

```bash
normal movie-register --report movie-scan.json --xlsx catalogue.xlsx
```

Formatted XLSX: title, year, resolution, video codec, audio, container, file size.

---

## Web UI

If you use API-backed web features, load your local env first. Keep durable API keys outside `.venv/bin/activate`; venv recreation can wipe them.

```bash
source .venv/bin/activate
normal web --host 127.0.0.1 --port 8765 --source /path/to/library
```

Open `http://127.0.0.1:8765` in a browser.

The Library Switcher in the top right selects the active lane. The source path input auto-detects Music vs Movies from the path (last segment containing `music` or `movies` wins).

**Music pages**
- Dashboard View — format mix, fidelity profile, artwork readiness
- Normalize Music Files & Folders — interactive plan review and apply
- Delete Weak Encodes — weak track triage with replacement queue tracking
- Repair Artwork for Jellyfin — album artist browser with candidate preview and approve/write
- Music Recommendation Engine — placeholder for future discovery tools

**Movie pages**
- Dashboard View — quality tier distribution, bitrate histograms, resolution breakdown
- Normalize Movie Files & Folders — interactive rename plan review and apply; All Results includes already-normalized videos as no-change rows for full selected-output preview
- Delete Weak Encodes — quality triage with replacement queue tracking; deleted queue items can be dismissed later if they are not worth replacing; tables now show a separate main-audio column alongside audio bitrate
- Fix Multi-Audio Packaging — triage MKVs where default audio language/track choice is likely wrong, then either flip English to default in place, drop tagged foreign-language audio, or queue the file for replacement. The delete-foreign-audio variant is currently untested on real libraries.
- Delete Junk Videos — checkbox select and confirm to delete
- Delete Junk Sidecar & Spam Files — sidecar and spam file cleanup
- Canonical Lists — strict title/year overlap against live all-time movie lists with simple badge unlocks

Canonical Lists uses TMDb plus a local cache. Start the web UI with `--tmdb-key` or load `TMDB_KEY` before launch. If an agent starts the server for you, the expected behavior is a clean launch with configured API integrations available, not a degraded launch that only serves the page shell.

Scans can be stopped mid-run with the Stop button. Per-page ETA estimates are stored in localStorage and shown on subsequent runs.

Heavy recursive web scans now show a confirmation warning for risky sources such as drive-root style paths and NTFS/FUSE mounts. The web server also allows only one heavy scan per source at a time.

Separately, the heavy movie scan path now discovers files as it walks instead of prebuilding the entire recursive result first. That change matters because it lowers the up-front traversal burst and lets cancellation bite during the directory walk rather than only after enumeration finishes.

Known issue: under some not-yet-isolated UI interaction pattern, cancelling a movie scan and quickly starting another workflow can leave an `ffprobe` probe running in the background. The Drive Activity indicator may not show that leftover probe in every case.
