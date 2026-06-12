# Safety model

`normal` is no longer conservative in **opinion**, but it is still explicit in **execution**. Scans and plans are read-only. Mutations require an intentional action. Destructive web actions re-check the selected paths immediately before touching disk.

## Read-only operations

These commands never mutate the library:

| Scope | Commands |
|---|---|
| Movies | `movie-plan`, `movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `movie-output`, `movie-register` |

They may write reports, plans, CSVs, or XLSX catalogues to the output paths you provide. They do not rename, delete, overwrite, or rewrite media.

## Apply operations

`movie-apply` carries the structural-mutation safety posture:

- Requires an explicit plan file — there is no auto-apply from scan output.
- `--target` and `--in-place` are mutually exclusive; exactly one is required.
- `--target` writes to a new directory and leaves the source untouched.
- `--in-place` mutates the source and must be requested explicitly.
- Existing destination files are never overwritten — colliding changes are skipped and reported.
- If the library has drifted from the plan, the affected changes are skipped and reported.
- An apply report is written to the destination (or source) root afterward.

## Web UI deletion rules

Every destructive web action follows the same pattern:

1. You select files via checkboxes. Selection alone does nothing.
2. You click a destructive action button.
3. The browser confirmation must pass.
4. The server revalidates every selected path against the current source root.
5. Paths outside the active source root are rejected.
6. Each file is reclassified immediately before deletion, where a detector exists.

Steps 1 and 2 are the two approval gates the product promises before any deletion: explicit selection, explicit confirmation.

- **Remove Junk Files** — selected files are revalidated as current junk candidates before unlink. Anything that no longer meets the criteria is skipped.
- **Review Low-Quality Encodes / Fix Audio and Subtitle Defaults (Audio Packaging)** — selected files are added to the movie **Replacement Queue**, then deleted after confirmation. Deleted items stay visible as `deleted, awaiting replacement` and auto-complete on a future scan when a replacement copy appears that no longer matches the queued issue family. They can also be marked `deleted from queue` manually when no longer worth replacing — a queue-only action that touches no media.

The CLI never deletes media. Deletion is web-only, behind selection plus confirmation.

Delete execution honors user-local policy: the current operator preference can recycle or hard-delete everything, or use one of two hybrid modes that treat media and junk differently. Safe sidecar and empty-folder cleanup follows the same delete posture rather than bypassing it.

## Replacement queue

The movie replacement queue is source-scoped, stored under `~/.local/share/normal/`:

| Queue | File |
|---|---|
| Movies | `movie-replacement-queue.json` |

Items move forward through states such as `pending`, `deleted`, `dismissed`, and `completed`. Queue history is never silently dropped.

Subtitle repair keeps its legacy source-scoped history file, but the main audit posture is the **unified ledger**: scans, deletes, repairs, exports, policy updates, and junk deletion all write durable audit events.

## Scan control

The web UI uses a Stop/Run toggle for in-flight scans:

- While a scan runs, **Run** becomes **Stop**.
- Stop aborts the browser request.
- Movie profile scans also check for client disconnects between files and report `movie_profile_cancelled` when cancellation is observed.
- Cancellation is cooperative — a probe already running may finish or time out before the request fully unwinds.

Two guards sit around heavy recursive scans:

- risky sources (drive-root style paths, NTFS/FUSE mounts) trigger an explicit confirmation warning
- only one heavy scan per source runs at a time; overlapping requests are rejected rather than run concurrently

There is also an execution-model guard: recursive discovery is no longer fully enumerated before probing begins. The scan walks the tree incrementally and checks for cancellation as it goes — the main change that reduced the earlier CPU spike on large or risky sources. Different filesystems, indexers, sync agents, antivirus, and thumbnailers amplify up-front directory walks differently, so the current read/write hygiene looks directionally safer but is not yet characterized cross-platform. Validate rather than assume.

Each `ffprobe` runs with a 30-second timeout. A timed-out probe becomes a reported warning or error for that file rather than hanging the whole scan.

## Observability

The **Drive Activity** indicator lets you see whether work is active before assuming the app is frozen. It reports three kinds:

- `normal` jobs tracked inside the server process
- active `ffprobe` probes launched by `normal`
- external Linux processes that appear related to the selected source

External visibility is a Linux `ps` query scoped by source path and command names (`ffprobe`, `ffmpeg`, `normal`, `python`, `python3`). It is observational only:

- it does not grant remote access
- it does not terminate external processes
- it does not inspect file contents
- it may miss a process whose command line omits the selected source path

If the OS process check is unavailable or times out, the UI reports process activity as unknown and keeps running.

## Remote access and metadata

Core scan, profile, normalize, and delete workflows are local-first. They require no cloud services and fetch no remote metadata.

## What normal will never do without explicit instruction

- Apply changes from a `scan` or `plan` automatically
- Overwrite an existing destination file during apply
- Delete anything from the CLI
- Mutate files outside the specified source root
- Delete web-selected files without confirmation and server-side revalidation

## If You Deleted Something You Wanted

If you accidentally approve a deletion, the first rule is simple: stop writing to the affected drive and seek help immediately. Do not keep scanning, moving files, downloading replacements, or running cleanup passes against that same storage until you understand your recovery options. Recovery is time-sensitive and depends heavily on the filesystem, whether snapshots or backups exist, whether the file was hard-deleted or only moved to Trash, and whether the storage has already reused the space.

If you have a capable command-line coding agent available (GPT, Sonnet, Opus, Gemini, or an equivalent frontier-class open-weight system such as Deepseek, Qwen, Kimi, etc.), use it immediately. The agent is not "recovering files from cache by magic"; it is a fast way to triage the system and guide you to the best available recovery path while time still matters. In practice that means quickly checking whether the file is still in Trash, whether the disk or NAS has snapshots, whether a backup exists, whether another process still holds the deleted file open, and which filesystem-aware recovery options are safest before further writes occur.

If you are "Agentless in Seattle", Plan B is to open ChatGPT (www.chatgpt.com) immediately and paste a short, factual description of what happened. Keep it plain and specific. A useful seed:

`I accidentally deleted a video file I wanted to keep while using a local media cleanup tool. I need urgent triage advice to maximise recovery chances. Please do not assume you have access to my machine. First, ask me only the minimum questions you need to determine the safest next steps, such as: what operating system I am using, whether the file was deleted to Trash or permanently deleted, whether the drive is SSD/HDD/external/NAS, whether I know the filesystem, and whether I have backups or snapshots. Then give me the safest immediate actions in priority order, with emphasis on avoiding further writes to the affected storage.`

[1]

Stay calm! While I can't promise you get those files back, you are not alone and casually working through the steps is your best move right now. 

Here is a meme to lift your spirits. We've all been there. Image credit to NanoBanana as served via Gemini 3.5 Flash.

normal -------------------------------------------------------------------------------you------------------------------------------------------------------------------ ChatGPT.com
<img width="1408" height="768" alt="agentless-in-seattle-1993" src="https://github.com/user-attachments/assets/339e6836-f07b-4bcc-b906-a94b089bc4ae" />

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
<sub>[1] From the reassurance onward, **User-written**.</sub>
