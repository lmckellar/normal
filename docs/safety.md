# Safety model

`normal` is conservative by design. Scans and plans never touch your library. Mutations require explicit opt-in at every step.

## Music lane

| Command | Mutates library? |
|---|---|
| `scan` | No |
| `plan` | No — writes a plan file only |
| `apply --target` | Writes to a new directory; source untouched |
| `apply --in-place` | Yes — explicit opt-in required |
| `output` | No |

### apply rules

- Requires an explicit plan file — no auto-apply from scan output
- `--target` and `--in-place` are mutually exclusive; exactly one must be specified
- No destructive overwrite: if a rename target already exists, the change is skipped and reported
- If the library has drifted from the plan (files moved or renamed since plan was generated), affected changes are skipped and reported
- Apply report written to `normal-apply-report.json` in the destination root

## Movie lane

| Command | Mutates library? |
|---|---|
| `movie-plan` | No |
| `movie-apply` | Yes, same rules as music `apply` |
| `movie-scan` | No |
| `movie-profile` | No |
| `movie-inspect` | No |
| `movie-junk` | No |
| `movie-output` | No |
| `movie-register` | No |

## Web UI deletions

All destructive web UI actions follow the same pattern:

1. User selects files via checkboxes — no action happens on selection alone
2. User clicks a delete button — a confirmation step fires
3. Each selected path is revalidated against the current source root before any unlink
4. Only paths under the active source root are accepted; outside-root paths are rejected

**Delete Junk Videos / Delete Junk Misc**: each file is revalidated as a junk candidate immediately before deletion. A file that no longer meets the junk criteria is skipped.

**Delete Weak Encodes**: selected files are queued in the Replacement Queue and immediately deleted in one confirmed step. Deleted items appear in the queue as `deleted, awaiting replacement` and are auto-completed when a better encode for the same title/year appears in a future scan.

## Replacement queue

The queue is stored at `~/.local/share/normal/movie-replacement-queue.json` and is keyed by source directory, so separate movie roots maintain separate queues. It is append-only from the tool's perspective — items move from `pending` → `deleted` → `completed` but are never silently removed.

## What normal will never do without explicit instruction

- Apply changes from a `scan` or `plan` run automatically
- Overwrite a file that already exists at the rename target
- Delete anything from the CLI (CLI commands are always report-only for deletions)
- Mutate files outside the specified source root
- Fetch or write metadata from remote sources
