# Light Experimental UI

Internal, local-only note.

Restyle and workflow-merge note for **Parser Tester UI** (`/parser-tester-ui`).
This route now carries three internal workflows inside one shell:

- `Parser Testing UI`
- `Weak Encodes Testing UI`
- `Repair Defaults Testing UI`
- `Delete Junk & Spam Files`

Workflow is URL-stable:

- `/parser-tester-ui?workflow=normalize`
- `/parser-tester-ui?workflow=weak-encodes`
- `/parser-tester-ui?workflow=repair-defaults`
- `/parser-tester-ui?workflow=junk`

## Files (`normal/web_assets/`)

- `normalize_lab.html` — shared shell
- `normalize_lab.css` — the restyle
- `normalize_lab.js` — normalize, weak-encode, repair-defaults, and junk-delete workflow logic

Assets served at `/parser-tester-ui-assets/<file>`.

## Design

- Light/paper palette: ground `#f6f5f2`, panels `#fff`, ink `#1c1d1f`, hairline
  rules `#e6e4df`/`#dcdad3`, one accent (ink-blue `#3a5a8c`) for Run button,
  active tab/mode, focus, selected row.
- System sans for chrome, monospace for data/paths.
- Tighter spacing (`--pad 14`, `--gap 12`, `--radius 6`); flat panels, no
  shadows; chips → flat 4px tags; sticky header; quiet hover.

## Workflow contract

Shared shell:

- top title is the workflow switcher
- default visible mode stays two-column
- source input and run button stay in the header
- shell now owns named layout modes: `2-page-lopsided`, `3-page-book`,
  `4-page-ledger`
- page roles are semantic rather than positional: current parser UI uses `scan`
  and `preview`, leaving room for future `inspection` and `audit` pages without
  rewriting layout primitives
- row-like surfaces opt into one shared rhythm contract from shell scope rather
  than tuning table rows and preview tree rows independently
- collapse behavior is defined at shell scope:
  `anchored-slot` keeps a narrow visible stub, `reflow` disappears and frees the
  track
- this contract is intentionally invisible in the current parser UI pass; live
  default remains `2-page-lopsided`

Normalize:

- table shows source `File Name` rather than full source path
- right page is preview-first; detailed row debug copy is no longer part of the
  live shell
- confirm path still uses `/api/movies/normalize` and `/api/movies/apply`

Weak encodes:

- scan table owns inspection details
- table shows source `File Name` rather than full source path
- weak floor selector defaults to `Standard Definition`; this is product
  posture, not a temporary tester quirk
- issue labels should stay short and semantic rather than expose raw thresholds or
  diagnostic prose where avoidable
- audio bitrate can open a tiny anchored speech-bubble inspector for the full
  audio-track list when the row needs stream-level verification
- packaging-owned cases such as wrong default-language audio with a good English
  track already present should route out of strict weak delete ownership
- right column owns preview and destructive confirm only
- row source is `/api/movies/profile`
- preview source is `/api/movies/replacement-queue/delete-preview`
- confirm still reuses queue-add then queue-delete
- replacement history widgets are intentionally not part of this page

Repair defaults:

- reuses the same tester shell and table rhythm as weak encodes rather than inventing a separate route
- covers both audio-packaging and subtitle-readiness sub-tabs inside the tester shell
- row source is `/api/movies/profile`
- consequence preview stays local to the current payload rather than requiring a repair-specific preview API
- the point is inspection and workflow-shape verification, not a second independent mutation contract
- filter/search/select stays owned by the top strip; preview scope and file-touch actions belong in the preview header
- audio-packaging now uses a compact `Repair action` selector plus `Run Repair` button so delete can sit in the same local action cluster without overloading the header
- forward note: if defaults become first-class policy settings rather than per-action mutations, this header can likely collapse again around `enforce policy` semantics instead of enumerating separate repair verbs

Junk delete:

- reuses the weak table scaffold rather than inventing a separate junk table
- `File Name` is junk-only middle truncation so the identifying front and release tail stay visible
- row source is `/api/movies/junk`
- confirm source is `/api/movies/junk/delete`
- preview is local-only from current `relative_path` values; no junk-specific preview endpoint
- video junk rows can surface probe-backed resolution, bitrate, channels, and audio-stream inspection
- promo docs and other non-media spam leave media cells honestly blank

## CSS / JS hooks

Keep the names JS toggles/emits: `#runButton.is-running`,
`.lab-tab`, `tr.active`, `.chip`,
`.lab-preview-summary/.lab-preview-empty`, `.lab-tree/.lab-tree-line`
(`.is-mutated`, `.is-selected`, `.is-deleted`, `.is-cleanup`,
`.lab-indent-0..5`), `.sort`, workflow menu/button ids,
`.lab-audio-popover*`, `#previewScopeSelect`, `#repairActionSelect`,
`#repairActionButton`, and the weak preview confirm label
`Delete Selected Files (N)`.

Shell contract hooks:

- `.lab-shell[data-layout-mode]`
- `.lab-page[data-page-role][data-collapse-mode][data-panel-state]`
- `.lab-rhythm-surface[data-rhythm-surface="rows"]`
- shell rhythm tokens such as `--lab-track-*` and `--lab-rhythm-*`

## Run

```bash
source .venv/bin/activate
python3 -m normal web --host 127.0.0.1 --port 8765 --source /mnt/media_storage/Movies
# http://127.0.0.1:8765/parser-tester-ui?workflow=normalize
# http://127.0.0.1:8765/parser-tester-ui?workflow=weak-encodes
# http://127.0.0.1:8765/parser-tester-ui?workflow=repair-defaults
# http://127.0.0.1:8765/parser-tester-ui?workflow=junk
```
