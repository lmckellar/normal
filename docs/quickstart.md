# Quick start

This quick start is deliberately biased toward a safe first run on a **test** movie library rather than a live one.

## 1. Build a representative test library

Make a small `Example Movies` directory on a local drive — a Noah's Ark of your actual mess, not a big one:

- a cross-section of your real naming conventions
- a few strong encodes, a few weak ones, a few junky package leftovers
- if your real library lives on an external mechanical drive, copy the same test set there later and repeat the checks

The point isn't volume. It's confirming `normal` ingests your conventions correctly before it goes anywhere near the real library.

## 2. Start with the read-only workflows

### Preview a normalize plan

```bash
normal movie-plan --source /path/to/movies --plan movie-plan.json --summary movie-plan.md
normal movie-apply --source /path/to/movies --plan movie-plan.json --target /path/to/normalized-movies
```

`movie-plan` is read-only — review the summary before applying anything. For a first run, point `movie-apply` at a separate `--target` rather than mutating in place.

### Profile library quality

```bash
normal movie-scan --source /path/to/movies --report movie-scan.json --progress
```

Profiles each file against the current quality posture with `ffprobe`. No changes.

```bash
normal movie-profile --source /path/to/movies --report movie-profile.json
```

Classifies the same library against the repo-local standards and surfaces review findings.

### Inspect one problem file

```bash
normal movie-inspect --path /path/to/file.mkv --report inspect.json
```

Useful when a single title misbehaves in Plex or looks misclassified.

### Find junk candidates

```bash
normal movie-junk --source /path/to/movies --report junk.json
```

The CLI is report-only. Deletion happens in the web UI, after selection and confirmation.

## 3. Run the web UI against the test library

```bash
source .venv/bin/activate
normal web --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765` and point `normal` at your test library folder in the UI on first run — it's saved for next time. (Passing `--source /path/to/Example\ Movies` on launch still works if you'd rather.)

Workflow deep links use the main route:

- `http://127.0.0.1:8765/?workflow=normalize`
- `http://127.0.0.1:8765/?workflow=weak-encodes`
- `http://127.0.0.1:8765/?workflow=repair-defaults`
- `http://127.0.0.1:8765/?workflow=junk`
- `http://127.0.0.1:8765/?workflow=format-upgrades`

Exercise the lanes in order:

1. **Dashboard View** — understand the library's current shape
2. **Normalize Movie Library Naming** — confirm the downstream naming matches your taste
3. **Remove Junk Files** — check junk detection is neither too timid nor too reckless
4. **Review Low-Quality Encodes** — see whether the replacement-candidate policy feels sane
5. **Fix Audio and Subtitle Defaults** — review the audio-packaging and subtitle-default logic
6. **Review Format Upgrade Candidates** — see whether better releases (UHD, Dolby Vision, Atmos/DTS:X, Open Matte, Hybrid) exist for your titles and whether your copies already cover them
7. **Compare Against Canonical Lists** — the distinct coverage pass, once the core cleanup lanes look right

## 4. Only then consider live use

When the test library behaves the way you want, repeat the process on a copy of that test set stored on the real external drive, if one is involved. Once both local-drive and real-drive behavior look sane, move to the live library.

Watching `normal` purify the test library is useful. Rushing straight to the live one is not.

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
