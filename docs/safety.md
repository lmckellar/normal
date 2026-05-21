# Safety model

*Authorship: Agent-written.*

`normal` is no longer conservative in product opinion, but it is still explicit in execution. Scans and plans are read-only. Mutations require an intentional user action. Destructive web actions re-check the selected paths immediately before touching disk.

## Read-only operations

These commands do not mutate the library:

| Scope | Commands |
|---|---|
| Movies | `movie-plan`, `movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `movie-output`, `movie-register` |

Read-only commands may write reports, plans, CSV files, or XLSX catalogues to the explicit output paths you provide. They do not rename, delete, overwrite, or rewrite media files.

## Apply operations

`movie-apply` uses the following safety posture:

- Requires an explicit plan file. There is no auto-apply from scan output.
- `--target` and `--in-place` are mutually exclusive; exactly one must be specified.
- `--target` writes to a new directory and leaves the source untouched.
- `--in-place` mutates the source and must be explicitly requested.
- Existing destination files are not overwritten; colliding changes are skipped and reported.
- If the library has drifted from the plan, affected changes are skipped and reported.
- Apply reports are written to the destination/source root after execution.

## Web UI deletion rules

All destructive web UI actions follow the same pattern:

1. User selects files via checkboxes. Selection alone does nothing.
2. User clicks a destructive action button.
3. The browser confirmation step must pass.
4. The server revalidates every selected path against the current source root.
5. Paths outside the active source root are rejected.
6. Each file is reclassified immediately before deletion where a detector exists.

Those first two steps are the minimum two approval gates the product promises before deletion: explicit selection and explicit confirmation.

**Delete Junk & Spam Files**: selected files are revalidated as current junk candidates before unlink. A file that no longer meets the junk criteria is skipped.

**Delete Weak Encodes / Repair Defaults (Audio Packaging)**: selected files are added to the movie Replacement Queue and then deleted after confirmation. Deleted items remain visible as `deleted, awaiting replacement` and can be auto-completed by a future scan when a replacement copy appears that no longer matches the queued issue family. Deleted queue items can also be manually marked `deleted from queue` when they are no longer worth replacing. That action is queue-only and does not delete media.

The CLI does not delete media. Deletion workflows are web-only and require checkbox selection plus confirmation.

## Replacement queue

The movie replacement queue is source-scoped and stored under `~/.local/share/normal/`:

| Queue | File |
|---|---|
| Movies | `movie-replacement-queue.json` |

Queue items move forward through states such as `pending`, `deleted`, `dismissed`, and `completed`. The tool does not silently remove queue history.

Subtitle repair also keeps a separate source-scoped subtitle history. Junk deletion has useful UI history today, but not yet the same durable coherent audit posture.

## Scan control

The web UI uses a Stop/Run toggle for in-flight scans:

- While a scan is running, the Run button becomes Stop.
- Clicking Stop aborts the browser request.
- Movie profile scans also check for client disconnects between files and report `movie_profile_cancelled` when cancellation is observed.
- Cancellation is cooperative. A currently running media probe may finish or time out before the request fully unwinds.

The web UI also applies two guards around heavy recursive scans:

- risky sources such as drive-root style paths and NTFS/FUSE mounts trigger an explicit confirmation warning
- only one heavy scan per source is allowed at a time; overlapping requests are rejected instead of running concurrently

There is also an execution-model guard behind the movie-side heavy scans: recursive discovery is no longer fully enumerated before probes begin. The scan walks the tree incrementally and checks for cancellation as it goes. That was the main change that reduced the earlier CPU spike on large or risky sources.

This is also worth treating as a candidate pattern for broader platform hardening, not just a Linux-local fix. Different filesystems, launch paths, indexers, sync agents, antivirus, thumbnailers, and shell or service managers can amplify up-front directory walks and incidental writes differently. Current read/write hygiene looks directionally safer, but cross-platform effects are not yet characterized and should be validated rather than assumed.

Movie metadata probes run through `ffprobe` with a 30 second timeout per file. A timed-out probe becomes a reported warning or error for that file rather than hanging the whole scan indefinitely.

Known open issue:

- Under some not-yet-isolated UI interaction pattern, likely involving cancellation and quickly launching another movie workflow, a background `ffprobe` can survive after the web request is gone.
- In that state the leftover probe is not guaranteed to appear in the Drive Activity indicator, even though activity discovery also uses `ps`.
- Treat Stop as best-effort cancellation, not a strict guarantee that every in-flight probe has already exited.

## Observability

The web UI includes a Drive Activity indicator so users can see whether work is active before assuming the app is frozen.

It reports three kinds of activity:

- `normal` jobs tracked inside the current server process
- active `ffprobe` media probes launched by `normal`
- external Linux processes that appear related to the selected source

External process visibility is implemented with a Linux `ps` query scoped by source path and command names such as `ffprobe`, `ffmpeg`, `normal`, `python`, and `python3`. This gives useful system-level visibility into local media/probe activity, but it is observational only:

- it does not grant remote access
- it does not terminate external processes
- it does not inspect file contents
- it may miss processes whose command line does not include the selected source path
- it may miss leftover probes from the open cancellation/visibility issue above

If the OS process check is unavailable or times out, the UI reports that process activity is unknown and continues operating.

## Remote access and metadata

Core scan, profile, normalize, and delete workflows are local-first. They do not require cloud services and do not fetch remote metadata.

## What normal will never do without explicit instruction

- Apply changes from a `scan` or `plan` run automatically
- Overwrite an existing destination file during apply
- Delete anything from the CLI
- Mutate files outside the specified source root
- Delete web-selected files without confirmation and server-side revalidation
- Terminate unrelated system processes
