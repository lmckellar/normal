# Music

The music lane normalizes FLAC libraries: tags, filenames, folder structure, and Jellyfin artwork — without touching anything until you explicitly apply.

![Music dashboard](assets/music_dashboard_default.png)

## Dashboard

A library-wide profile by format and fidelity — FLAC vs lossy, bit depth and sample rate breakdown, and early quality signals. Useful for understanding what's already in good shape and where the rough edges are.

## Normalize files and folders

The normalization pipeline is scan → plan → review → apply.

**Scan** reads your FLAC library, groups tracks into albums, and reports tag inconsistencies and naming issues. Nothing is changed.

**Plan** turns scan findings into a concrete list of proposed changes — tag edits, file renames, folder moves — each labelled `safe` or `review`. Safe changes are deterministic. Review changes need a human call.

**Apply** executes the plan. The default writes to a new directory so your source is untouched. In-place is available but has to be explicitly opted in to.

You can run the full pipeline in the web UI with an interactive review step, or via CLI if you'd rather diff the plan file directly.

## Delete weak encodes

The music quality page profiles tracks and surfaces strict weak candidates for removal:

| Profile | Meaning |
|---|---|
| `mp3_trash` | MP3 below the current high-quality threshold |
| `unknown_unreadable` | Files that could not be read or classified |

Selected files go through the Music Replacement Queue before deletion. Deleted items stay visible as awaiting replacement, so a future scan can show what still needs a better copy.

## Repair artwork for Jellyfin

The **Repair Artwork for Jellyfin** page scans album artist folders for `artist.jpg` sidecars and shows them as a thumbnail gallery. The thumbnails are loaded from the same paths Jellyfin reads, so the gallery is a direct preview of what Jellyfin displays.

Missing artists are listed alongside the gallery. Low-quality images — under 30 KB or smaller than 300×300 px — are flagged with a red border and dimension badge.

### Finding and dragging artwork

The recommended workflow: open `normal` on one half of your screen and an image source — Google Images, a fan art site, or your file manager — on the other half. Drag images directly onto an artist tile or into the drop zone in the detail panel.

The image must be a real image resource that the browser has loaded, not an HTML-framed thumbnail. The practical distinction:

- **Works:** The large preview image in Google Images' right-side panel (after clicking a result). An image URL opened directly in its own browser tab. An image file dragged from your file manager.
- **May not work:** Small thumbnails in a search result grid. Images inside complex page layouts where the dragged element is a styled `div`, not an `<img>` tag.

A quick test: right-click the image → **Open Image in New Tab**. If the browser shows it as a standalone image with no surrounding page chrome, that image is draggable. Drag from that tab.

Accepted formats: JPEG and PNG. All sources are converted to JPEG on write.

### What gets written

`artist.jpg` in the album artist folder. Jellyfin reads this path directly. The preview in `normal` loads from the same location, so what you see in the gallery is what Jellyfin shows.

Low-confidence writes — anything sourced from a drag-drop or external fetch rather than a confirmed local sidecar — are tagged with a provenance file so future scans can distinguish what `normal` placed from what was already there.

## Recommendation engine

The Music Recommendation Engine is currently a placeholder page. It exists to reserve the workflow for future artist, album, and related-release discovery tools; it does not make recommendations yet.

## CSV export

Export an album-level CSV of your cleaned library: artist, album, year, genre, track count, path.

```bash
normal output --source /path/to/music --csv collection.csv
```

## Web UI pages

| Page | What it does |
|---|---|
| Dashboard | Format mix, fidelity profile, artwork readiness |
| Normalize | Interactive plan review and apply |
| Delete Weak Encodes | Triage weak tracks and track replacements |
| Repair Artwork for Jellyfin | Artist browser with drag-and-drop artwork and approve/write |
| Music Recommendation Engine | Placeholder for future discovery tools |
