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

Parses title, year, and technical tokens from local paths only. Ambiguous parses are flagged as `review`. See [docs/commands.md](commands.md) for naming rules.

### Profile encode quality

```bash
normal movie-scan --source /path/to/movies --report movie-scan.json --progress
```

Profiles each file against the quality ladder using ffprobe metadata. No changes made. Use `--progress` to print live count, elapsed time, and ETA to stderr.

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

### Export a catalogue

```bash
normal movie-register --report movie-scan.json --xlsx catalogue.xlsx
```

Formatted XLSX: title, year, resolution, video codec, audio, container, file size.

---

## Web UI

```bash
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
- Normalize Movie Files & Folders — interactive rename plan review and apply
- Delete Weak Encodes — quality triage with replacement queue tracking
- Delete Junk Videos — checkbox select and confirm to delete
- Delete Junk Sidecar & Spam Files — sidecar and spam file cleanup

Scans can be stopped mid-run with the Stop button. Per-page ETA estimates are stored in localStorage and shown on subsequent runs.
