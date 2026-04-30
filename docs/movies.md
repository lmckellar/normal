# Movies

The movie lane handles the two main problems with a pirated library: inconsistent naming and uneven encode quality.

![Movies dashboard](assets/movies_dashboard_default.png)

## Dashboard

A library-wide view of encode quality — resolution breakdown, quality tier distribution, and bitrate histograms. A good first stop to understand the shape of your collection before deciding what to clean up.

Theme examples:

![Movies dashboard, Win95 theme](assets/movies_dashboard_win95.png)

![Movies dashboard, dark theme](assets/movies_dashboard_dark.png)

![Movies dashboard, matrix theme](assets/movies_dashboard_matrix.png)

![Movies dashboard, sand theme](assets/movies_dashboard_sand.png)

## Normalize names

Files named by whoever uploaded them tend to have inconsistent formatting — varying year placement, leftover technical tokens, mismatched folder names. `normal` parses each path locally (no network lookups) and proposes a clean, consistent target shape:

```
Title (Year) [technical tokens]/Title (Year) [technical tokens].mkv
```

Ambiguous parses are flagged as `review`. Everything else is `safe`. You review the plan before anything moves.

## Quality triage

A full quality scan profiles every file against a bitrate/resolution ladder:

| Tier | What it means |
|---|---|
| `4k_remux` / `4k_uhd` | Reference quality |
| `compressed_4k` | Acceptable 4K |
| `1080p_uhd` / `compressed_1080p` | Good 1080p |
| `minimum_acceptable_1080p` | Watchable |
| `weak_1080p` / `weak_4k` / `sd_low_quality` | Candidates for replacement |

The **Delete Weak Encodes** page lets you select weak files for deletion. Each deleted file goes into a replacement queue — when a better encode for the same title shows up in a future scan, it's automatically marked complete.

## Junk cleanup

Two pages handle library noise:

- **Delete Junk Videos** — samples, featurettes, and shorts, detected by path tokens and duration
- **Delete Junk Sidecar & Spam Files** — promo PDFs, NFO files, and other non-video sidecars

Both show a preview list before anything is deleted.

## Catalogue export

Export a formatted XLSX of your full library: title, year, resolution, video codec, audio, container, file size — sorted alphabetically.

```bash
normal movie-register --report scan.json --xlsx catalogue.xlsx
```

## Web UI pages

| Page | What it does |
|---|---|
| Dashboard | Quality overview — tiers, histograms, resolution breakdown |
| Normalize | Review and apply rename plans |
| Delete Weak Encodes | Triage and queue replacements |
| Delete Junk Videos | Remove samples and featurettes |
| Delete Junk Sidecar & Spam Files | Remove sidecar and spam files |
