# CLI reference

All commands share `--source` for the library root unless otherwise noted.

## Music lane

### scan

Analyze a FLAC library for tag, filename, and folder issues.

```bash
normal scan --source /path/to/music --report out/scan.json
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to music library root |
| `--report` | Yes | Output path for the JSON scan report |

No changes made.

---

### plan

Generate a reviewable change plan.

```bash
normal plan --source /path/to/music --plan out/plan.json --summary out/plan.md
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to music library root |
| `--plan` | Yes | Output path for the JSON plan file |
| `--summary` | No | Output path for a human-readable plan summary |

No changes made.

---

### apply

Execute an existing plan.

```bash
# Write to a new directory (recommended)
normal apply --source /path/to/music --plan out/plan.json --target /path/to/output

# Mutate in place (explicit opt-in)
normal apply --source /path/to/music --plan out/plan.json --in-place
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to the source music library |
| `--plan` | Yes | Path to an existing JSON plan file |
| `--target` | One of | Output directory for the cleaned copy |
| `--in-place` | One of | Mutate the source library directly |

Writes `normal-apply-report.json` to the destination root.

---

### output

Export a cleaned library as an album-level CSV.

```bash
normal output --source /path/to/cleaned-music --csv out/collection.csv
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to the cleaned music library |
| `--csv` | Yes | Output path for the CSV |

---

## Movie lane

### movie-plan

Generate a movie rename plan from local path parsing.

```bash
normal movie-plan --source /path/to/movies --plan out/plan.json --summary out/plan.md
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--plan` | Yes | Output path for the JSON plan file |
| `--summary` | No | Output path for a human-readable summary |

Target naming shape: `Title (Year) [technical tokens]/Title (Year) [technical tokens].ext`

---

### movie-apply

Apply a movie rename plan.

```bash
normal movie-apply --source /path/to/movies --plan out/plan.json --target /path/to/output
normal movie-apply --source /path/to/movies --plan out/plan.json --in-place
```

Same flag semantics as `apply`. Writes `normal-movie-apply-report.json`.

---

### movie-scan

Profile a movie library for encode quality using local media metadata.

```bash
normal movie-scan --source /path/to/movies --report out/scan.json --progress
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--report` | Yes | Output path for the JSON quality report |
| `--progress` | No | Print live count, elapsed time, ETA, and current file to stderr |

Requires `ffprobe`. No changes made.

---

### movie-profile

Classify a movie library against the quality ladder with heuristic findings.

```bash
normal movie-profile --source /path/to/movies --report out/profile.json --histogram out/histogram.json
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--report` | Yes | Output path for the JSON profile report |
| `--histogram` | No | Output path for an aggregate histogram payload |
| `--progress` | No | Print progress to stderr |

Quality ladder (video bitrate, resolution-gated):

| Profile | Resolution | Video kbps |
|---|---|---|
| `sd_low_quality` | 720p or SD | any |
| `weak_1080p` | 1080p | 1 – 4,499 |
| `minimum_acceptable_1080p` | 1080p | 4,500 – 5,999 |
| `compressed_1080p` | 1080p | 6,000 – 15,999 |
| `1080p_uhd` | 1080p | ≥ 16,000 |
| `weak_4k` | 2160p | 1 – 5,999 |
| `compressed_4k` | 2160p | 6,000 – 11,999 |
| `4k_uhd` | 2160p | 12,000 – 23,999 |
| `4k_remux` | 2160p | ≥ 24,000 |
| `unclassified` | any | unknown resolution or missing bitrate |

---

### movie-inspect

Detailed diagnostic for a single movie file.

```bash
normal movie-inspect --path /path/to/file.mkv --report out/inspect.json
```

| Flag | Required | Description |
|---|---|---|
| `--path` | Yes | Path to the video file |
| `--report` | Yes | Output path for the JSON inspect report |

---

### movie-junk

Find likely sample, featurette, and short junk videos.

```bash
normal movie-junk --source /path/to/movies --report out/junk.json
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--report` | Yes | Output path for the JSON junk report |

CLI is report-only. Deletion is done through the web UI.

Detection criteria:
- path tokens: `sample`, `featurette`, `featurettes`, and known typo variants
- duration under 5 minutes → high-confidence junk
- size under 100 MB → flagged for review

---

### movie-output

Export a quality report as a triage CSV.

```bash
normal movie-output --report out/scan.json --csv out/triage.csv
normal movie-output --report out/scan.json --csv out/severe.csv --minimum-status severe
```

| Flag | Required | Description |
|---|---|---|
| `--report` | Yes | Path to an existing `movie-scan` JSON report |
| `--csv` | Yes | Output path for the CSV |
| `--minimum-status` | No | Filter by minimum review status (e.g. `severe`) |

Sorted worst-first by `triage_score`. No changes made.

---

### movie-register

Export a formatted movie catalogue spreadsheet.

```bash
normal movie-register --report out/scan.json --xlsx out/catalogue.xlsx
```

| Flag | Required | Description |
|---|---|---|
| `--report` | Yes | Path to an existing `movie-scan` JSON report |
| `--xlsx` | Yes | Output path for the XLSX file |

Columns: Title, Year, Resolution, Video, Audio, Container, Size. Sorted A–Z by title.

---

## Web UI

```bash
normal web --host 127.0.0.1 --port 8765 --source /path/to/library
```

| Flag | Required | Description |
|---|---|---|
| `--host` | No | Bind address (default: `127.0.0.1`) |
| `--port` | No | Port (default: `8765`) |
| `--source` | No | Default source path pre-filled in the UI |
| `--omdb-key` | No | OMDb API key for IMDb ratings in the replacement queue (falls back to `OMDB_KEY` env var) |
