# CLI reference

Every top-level command is a movie command (plus `web`).

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

Default target shape: `Title (Year)/Title (Year).ext`

When concise naming would collapse multiple parsed copies of the same title/year, `movie-plan` adds the shortest available parsed differentiator — usually resolution — to both folder and file stem: `Title (Year) 2160p/Title (Year) 2160p.ext`. Differentiators can come from the file or the containing folder, which keeps duplicate copies actionable after a partial earlier cleanup. With no differentiator available, the collision stays a `review` item.

Plans can also include safe cleanup operations:

| Change type | Meaning |
|---|---|
| `file_move` | Move a loose root movie into its concise folder |
| `file_rename` | Rename a movie file in place |
| `folder_rename` | Rename a movie or artifact folder |
| `folder_merge` | Move non-conflicting artifact-folder contents into an existing concise movie folder |
| `file_delete` | Delete high-confidence root junk such as AppleDouble `._*` files |
| `folder_delete` | Delete high-confidence metadata-only collection artifact folders |

---

### movie-apply

Apply a movie normalize plan.

```bash
normal movie-apply --source /path/to/movies --plan out/plan.json --target /path/to/output
normal movie-apply --source /path/to/movies --plan out/plan.json --in-place
```

Writes `normal-movie-apply-report.json`.

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to the source movie library |
| `--plan` | Yes | Path to an existing JSON plan file |
| `--target` | One of | Output directory for the cleaned copy |
| `--in-place` | One of | Mutate the source library directly |

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

`resolution_bucket` is display-class oriented when usable aspect metadata is present: cropped `1920x796` films stay `1080p`, and anamorphic `1440x1080` HD masters classify as `1080p` when the stream exposes valid aspect data.

---

### movie-profile

Classify a movie library against the local standards, with inline review findings.

```bash
normal movie-profile --source /path/to/movies --report out/profile.json --histogram out/histogram.json
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--report` | Yes | Output path for the JSON profile report |
| `--histogram` | No | Output path for an aggregate histogram payload |
| `--progress` | No | Print progress to stderr |

Dashboard groupings split into action-based and quality-profile labels.

Action-based:

| Label | Meaning |
|---|---|
| `deleted, awaiting replacement` | Deleted through the replacement queue, still waiting for a better copy |
| `replacement_candidate` | Quality profile at or below the configured replacement cutoff |
| `needs_review` | Inline review attention needed, often low-confidence subtitle or hygiene issues |

Quality-profile:

| Profile | Meaning |
|---|---|
| `Standard Definition` | Catch-all fallback for weak HD, SD titles, and outliers that miss every stricter stance |
| `Compact Grade` | Benign compact encodes that clear a modest floor but not full library-grade posture |
| `Library Grade` | Good enough for casual viewing and broad library selection |
| `Collector Grade` | Solid compact encodes that hold up on difficult material |
| `Reference` | Mild to no visual compression with lossless-audio posture |

The bottom stance is a fallback bucket, not a strict authored threshold — its dashboard editor only exposes label and summary.

Config source: repo-local `movie_standards.json`. Dashboard scans report streamed progress in the activity bar; browser cache is convenience state only, with the repo-local standards authoritative. The same `movie-profile` report powers the web triage lanes **Review Low-Quality Encodes** and **Fix Audio and Subtitle Defaults**.

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

Find likely sample, featurette, extra, and sidecar spam in a movie library pre-clean pass.

```bash
normal movie-junk --source /path/to/movies --report out/junk.json
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--report` | Yes | Output path for the JSON junk report |

Report-only — deletion happens in the web UI after selection and confirmation. Detection is size-first:

- junk markers in filenames or ancestor folders such as `sample`, `extra`, `featurette`, and known typo variants
- marker-backed junk under 2 GB → high-confidence junk
- marker-backed junk between 2 GB and 4 GB needs stacked signals (file marker plus ancestor marker, multiple ancestor markers, or a very small file)
- marker-only video files at or above 4 GB are ignored
- size alone never creates a candidate

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
| `--host` | No | Bind address (default `127.0.0.1`) |
| `--port` | No | Port (default `8765`) |
| `--source` | No | Default source path pre-filled in the UI |
| `--omdb-key` | No | OMDb key for cached server-side IMDb ratings in the replacement queue (falls back to `OMDB_KEY`) |
| `--tmdb-key` | No | TMDb key for Compare Against Canonical Lists, only when the provider is explicitly TMDb (falls back to `TMDB_KEY`) |

Compare Against Canonical Lists defaults to the IMDb provider; for that default, set `IMDB_DATASET_DIR` to a directory containing `title.basics.tsv.gz` and `title.ratings.tsv.gz`.

Movie pages currently exposed:

- `Dashboard View`
- `Normalize Movie Library Naming`
- `Remove Junk Files`
- `Review Low-Quality Encodes`
- `Fix Audio and Subtitle Defaults`
- `Review Immersive Audio Candidates`
- `Compare Against Canonical Lists`

Workflow deep links:

- `/?workflow=normalize`
- `/?workflow=weak-encodes`
- `/?workflow=repair-defaults`
- `/?workflow=junk`
- `/?workflow=immersive-audio`

Heavy recursive web scans show a confirmation warning for risky sources (drive-root style paths, NTFS/FUSE mounts), and the server rejects overlapping heavy scans for the same source rather than running them concurrently. Scan cancellation is cooperative: profile scans check between files, and a running `ffprobe` may finish or time out before the request fully unwinds.

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
