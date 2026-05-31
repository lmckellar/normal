# Light Experimental UI

Internal, local-only note.

Restyle and workflow-merge note for **Parser Tester UI** (`/parser-tester-ui`).
This route now carries two internal workflows inside one shell:

- `Parser Testing UI`
- `Weak Encodes Testing UI`

Workflow is URL-stable:

- `/parser-tester-ui?workflow=normalize`
- `/parser-tester-ui?workflow=weak-encodes`

## Files (`normal/web_assets/`)

- `normalize_lab.html` — shared shell
- `normalize_lab.css` — the restyle
- `normalize_lab.js` — normalize plus weak-encode workflow logic

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
- layout stays two-column
- source input and run button stay in the header

Normalize:

- existing row/detail/preview split remains
- confirm path still uses `/api/movies/normalize` and `/api/movies/apply`

Weak encodes:

- scan table owns inspection details
- right column owns preview and destructive confirm only
- row source is `/api/movies/profile`
- preview source is `/api/movies/replacement-queue/delete-preview`
- confirm still reuses queue-add then queue-delete
- replacement history widgets are intentionally not part of this page

## CSS / JS hooks

Keep the names JS toggles/emits: `#runButton.is-running`,
`.lab-tab/.lab-mode-button.is-active`, `tr.active`, `.chip`,
`.lab-preview-summary/.lab-preview-empty`, `.lab-tree/.lab-tree-line`
(`.is-mutated`, `.is-selected`, `.is-deleted`, `.is-cleanup`,
`.lab-indent-0..5`), `.sort`, workflow menu/button ids, and the weak preview
confirm label `Delete Selected Files (N)`.

## Run

```bash
source .venv/bin/activate
python3 -m normal web --host 127.0.0.1 --port 8765 --source /mnt/media_storage/Movies
# http://127.0.0.1:8765/parser-tester-ui?workflow=normalize
# http://127.0.0.1:8765/parser-tester-ui?workflow=weak-encodes
```
