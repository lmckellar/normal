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

There is also an execution-model guard behind the movie-side heavy scans: recursive discovery is no longer fully enumerated before probes begin. The scan walks the tree incrementally and checks for cancellation as it goes. That was the main change that reduced the earlier CPU spike on large or risky sources.Different filesystems, launch paths, indexers, sync agents, antivirus, thumbnailers, and shell or service managers can amplify up-front directory walks and incidental writes differently. Current read/write hygiene looks directionally safer, but cross-platform effects are not yet characterized and should be validated rather than assumed.

Movie metadata probes run through `ffprobe` with a 30 second timeout per file. A timed-out probe becomes a reported warning or error for that file rather than hanging the whole scan indefinitely.

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

If the OS process check is unavailable or times out, the UI reports that process activity is unknown and continues operating.

## Remote access and metadata

Core scan, profile, normalize, and delete workflows are local-first. They do not require cloud services and do not fetch remote metadata.

## What normal will never do without explicit instruction

- Apply changes from a `scan` or `plan` run automatically
- Overwrite an existing destination file during apply
- Delete anything from the CLI
- Mutate files outside the specified source root
- Delete web-selected files without confirmation and server-side revalidation

## If You Deleted Something You Wanted
  
If you accidentally approve a deletion, the first rule is simple: stop writing to the affected drive and seek help immediately. Do not keep scanning, moving files, downloading replacements, or running cleanup passes against that same storage until you understand your recovery options. Recovery is time-sensitive and depends heavily on the filesystem, whether snapshots or backups exist, whether the file was hard-deleted or only moved to Trash, and whether the storage has already reused the space.
  
If you have a suitably capable command line coding agent available (GPT, Sonnet, Opus, Gemini or equivalent frontier-class open weight model derived system such as Deepseek, Gwen, Kimi, etc), use it immediately. The agent is not “recovering files from cache by magic”; it is a fast way to triage the system and guide you to the best available recovery path while time still matters. In practice that usually means quickly checking whether the file is still in Trash, whether the disk or NAS has snapshots, whether a backup exists, whether another process still has the deleted file open, and what filesystem-aware recovery options are safest before further writes occur.
  
If you are "Agentless in Seattle", Plan B is to open ChatGPT (www.chatgpt.com) immediately and paste a short factual description of what happened. Keep it plain and specific. A useful seed is:
  
`I accidentally deleted a video file I wanted to keep while using a local media cleanup tool. I need urgent triage advice to maximise recovery chances. Please do not assume you have access to my machine. First, ask me only the minimum questions you need to determine the safest next steps, such as: what operating system I am using, whether the file was deleted to Trash or permanently deleted, whether the drive is SSD/HDD/external/NAS, whether I know the filesystem, and whether I have backups or snapshots. Then give me the safest immediate actions in priority order, with emphasis on avoiding further writes to the affected storage.`

`human authored`

Stay calm! While I can't promise you get those files back, you are not alone and casually working through the steps is your best move right now. 

Here is a meme to lift your spirits. We've all been there. Image credit to NanoBanana as served via Gemini 3.5 Flash.

Me --------------------------------------------------------------------------------------------------------------------------------------------------------------------- ChatGPT.com
<img width="1408" height="768" alt="agentless-in-seattle-1993" src="https://github.com/user-attachments/assets/339e6836-f07b-4bcc-b906-a94b089bc4ae" />


