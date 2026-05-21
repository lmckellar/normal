# CLI reference

*Authorship: Agent-written.*

All current top-level commands are movie commands.

### movie-plan

Generate a movie rename plan from local path parsing.

```bash
normal movie-plan --source /path/to/movies --plan out/plan.json --summary out/plan.md
normal movie-plan --source /path/to/movies --plan out/plan.json --naming-style verbose
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--plan` | Yes | Output path for the JSON plan file |
| `--summary` | No | Output path for a human-readable summary |
| `--naming-style` | No | `concise` for intended `Title (Year)` output, or temporary `verbose` output with selected edition and video tokens. Defaults to `concise`. |

Default target naming shape: `Title (Year)/Title (Year).ext`

Verbose target naming shape: `Title (Year) [edition/video tokens]/Title (Year) [edition/video tokens].ext`

When concise naming would collapse multiple parsed copies of the same title/year, `movie-plan` adds the shortest available parsed differentiator, usually resolution, to both folder and file stem: `Title (Year) 2160p/Title (Year) 2160p.ext`. Differentiators can come from the file or the containing folder, which keeps duplicate copies actionable after a partial previous cleanup. If no differentiator is available, the collision remains a `review` item.

Movie plans can also include safe cleanup operations:

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

---

### movie-profile

Classify a movie library against the local movie standards with inline review findings.

```bash
normal movie-profile --source /path/to/movies --report out/profile.json --histogram out/histogram.json
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--report` | Yes | Output path for the JSON profile report |
| `--histogram` | No | Output path for an aggregate histogram payload |
| `--progress` | No | Print progress to stderr |

Dashboard groupings:

Action-based labels:

| Label | Meaning |
|---|---|
| `deleted, awaiting replacement` | Deleted through the replacement queue and still waiting for a better copy |
| `replacement_candidate` | Quality profile is at or below the configured replacement cutoff |
| `needs_review` | Inline review attention needed, often low-confidence subtitle or hygiene issues |

Quality-profile labels:

| Profile | Meaning |
|---|---|
| `Standard Definition` | Weak HD encodes and standard-definition material still worth keeping |
| `Library Grade` | Good enough for casual viewing and broad library selection |
| `Collector Grade` | Solid compact encodes that hold up better on difficult material |
| `Reference` | Mild to no visual compression with lossless-audio posture |

Config source:
- repo-local `movie_standards.json`

Dashboard notes:
- `Movies / Dashboard View` separates action cards from quality-profile cards.
- Inline definition controls write `movie_standards.json`.
- Browser cache is convenience state only; repo-local standards are authoritative.
- Dashboard scans report streamed progress in the activity bar.

The same `movie-profile` report also powers the main web triage lanes:

- `Delete Weak Encodes`
- `Repair Defaults`

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

Find likely sample, featurette, extra, and sidecar spam junk in a movie library pre-clean pass.

```bash
normal movie-junk --source /path/to/movies --report out/junk.json
```

| Flag | Required | Description |
|---|---|---|
| `--source` | Yes | Path to movie library root |
| `--report` | Yes | Output path for the JSON junk report |

CLI is report-only. Deletion is done through the web UI after selection and confirmation.

Detection criteria:
- junk markers in filenames or ancestor folders such as `sample`, `samples`, `extra`, `extras`, `featurette`, `featurettes`, and known typo variants
- marker-backed junk under 2 GB → high-confidence junk
- marker-backed junk between 2 GB and 4 GB needs stacked signals such as a file marker plus an ancestor marker, multiple ancestor markers, or a very small file
- marker-only video files at or above 4 GB are ignored
- size alone does not create junk candidates

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
| `--omdb-key` | No | OMDb API key for cached server-side IMDb ratings in the replacement queue (falls back to `OMDB_KEY` env var) |
| `--tmdb-key` | No | TMDb API key for the Canonical Lists page (falls back to `TMDB_KEY` env var) |

Movie pages currently exposed in the web UI:

- `Dashboard View`
- `Normalize Movie Files & Folders`
- `Delete Weak Encodes`
- `Repair Defaults`
- `Delete Junk & Spam Files`
- `Canonical Lists`

Heavy recursive web scans now show a confirmation warning for risky sources such as drive-root style paths and NTFS/FUSE mounts. The server also rejects overlapping heavy scans for the same source instead of running them concurrently.

Known issue: some cancelled movie scans can leave a background `ffprobe` running if another UI action starts immediately after cancellation. The exact trigger is still unknown, and the Drive Activity `ps` check may miss the leftover probe.
