# Quick start

*Authorship: Agent-written.*

This quick start is intentionally biased toward a safe first run on a test movie library rather than a live one.

## 1. Build a representative test library

Make a small `Example Movies` directory on a local drive.

- include a cross-section of your real naming conventions
- include a few strong encodes, a few weak ones, and a few junky package leftovers
- if you use an external mechanical drive for the real library, copy the same test set there later and repeat the checks

The point is not volume. The point is to confirm that `normal` ingests your actual mess correctly before you let it near the real library.

## 2. Start with read-only workflows

### Normalize naming preview

```bash
normal movie-plan --source /path/to/movies --plan movie-plan.json --summary movie-plan.md
normal movie-apply --source /path/to/movies --plan movie-plan.json --target /path/to/normalized-movies
```

`movie-plan` is read-only. Review the summary before applying anything. For a first run, keep `movie-apply` pointed at a separate target directory rather than mutating in place.

### Profile library quality

```bash
normal movie-scan --source /path/to/movies --report movie-scan.json --progress
```

Profiles each file against the current quality posture using `ffprobe`. No changes are made.

```bash
normal movie-profile --source /path/to/movies --report movie-profile.json
```

Classifies the same library against the repo-local standards and surfaces review findings.

### Inspect one problematic file

```bash
normal movie-inspect --path /path/to/file.mkv --report inspect.json
```

Useful when one title behaves badly in Plex or looks misclassified.

### Find junk candidates

```bash
normal movie-junk --source /path/to/movies --report junk.json
```

CLI is report-only. Deletion is done through the web UI after selection and confirmation.

## 3. Use the web UI on the test library

```bash
source .venv/bin/activate
normal web --host 127.0.0.1 --port 8765 --source /path/to/Example\ Movies
```

Open `http://127.0.0.1:8765` in a browser.

For the internal focused tester shell, use:

- `http://127.0.0.1:8765/parser-tester-ui?workflow=normalize`
- `http://127.0.0.1:8765/parser-tester-ui?workflow=weak-encodes`
- `http://127.0.0.1:8765/parser-tester-ui?workflow=repair-defaults`

Use the test library to exercise the full workflow in order:

1. `Dashboard View` to understand current library shape
2. `Normalize Movie Files & Folders` to confirm the downstream naming shape matches your taste
3. `Delete Weak Encodes` to see whether the replacement-candidate policy feels sane
4. `Repair Defaults` to review audio-packaging and subtitle-default logic
5. `Delete Junk & Spam Files` to confirm junk detection is neither too timid nor too reckless

## 4. Only then consider live use

When the test library behaves the way you want, repeat the same process on a copy of that test set stored on the real external drive if one is involved. Once both local-drive and real-drive behavior look sane, move to the live library.

Watching `normal` purify the test library is useful. Rushing straight to the live library is not.
