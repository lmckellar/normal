# Movie Comparison Card Spec

Status: working note  
Last reviewed: 2026-05-07

## Goal

Define the card model and dataset plan for `Movies > Streaming Service Comparison Dashboard`.

This replaces the current quality-shaped comparison cards. Comparison here is about catalogue/menu shape, not encode quality.

## Core stance

- Compare one selected `service` dataset at a time.
- Treat the selected service snapshot as the active menu.
- Use local library overlap plus curated list overlap to describe that menu.
- Do not use bitrate, format, resolution, or encode-strength cards on this page.
- Do not infer genre strength from local media metadata. Genre/classic cards are list-driven.

## Card groups

### Menu breadth

These cards answer: how big is the menu, how much do I already have, what is distinct, and what am I missing?

| Card ID | Label | Meaning |
|---|---|---|
| `library_capture` | Library Capture | How many titles from the selected service snapshot already exist in the local library |
| `exclusive_titles` | Exclusive Titles | Titles in the selected service snapshot that do not appear in any other installed service snapshot |
| `gap_opportunity` | Gap Opportunity | Titles in the selected service snapshot that intersect with our installed prestige/recent lists but are missing locally |

### classics

These cards answer: does this service menu carry canon depth?

| Card ID | Label | Backing dataset |
|---|---|---|
| `imdb_top_250_coverage` | IMDb Top 250 Coverage | `imdb_top_250` |
| `imdb_top_1000_coverage` | IMDb Top 1000 Coverage | `imdb_top_1000` |

### genre classics

These cards answer: where does this service menu go deep in the genres we care about?

| Card ID | Label | Backing dataset |
|---|---|---|
| `top_100_scifi_coverage` | Top 100 Sci-Fi Coverage | curated sci-fi top 100 list |
| `top_100_fantasy_coverage` | Top 100 Fantasy Coverage | curated fantasy top 100 list |
| `top_100_action_coverage` | Top 100 Action Coverage | curated action top 100 list |
| `top_100_thriller_coverage` | Top 100 Thriller Coverage | curated thriller top 100 list |
| `top_100_horror_coverage` | Top 100 Horror Coverage | curated horror top 100 list |
| `top_100_comedy_coverage` | Top 100 Comedy Coverage | curated comedy top 100 list |
| `top_100_animation_coverage` | Top 100 Animation Coverage | curated animation top 100 list |

## Current UI direction

Primary cards on the left should come from the groups above.

Recommended first visible order:

1. `Library Capture`
2. `Exclusive Titles`
3. `Gap Opportunity`
4. `IMDb Top 250 Coverage`
5. `IMDb Top 1000 Coverage`
6. the installed genre-classics cards

The right panel remains the `Service Comparison Library` switcher and active loaded object detail.

## Card definitions

### Library Capture

Question:
How much of this service menu do I already have?

Numerator:
- local normalized titles matching the selected service snapshot

Denominator:
- total titles in the selected service snapshot

Display:
- matched count
- percent of selected service snapshot
- optional secondary count: matched count as percent of normalized local library

### Exclusive Titles

Question:
What does this service have that the other installed services do not?

Numerator:
- titles in selected service snapshot whose normalized title/year key appears in no other installed `service` dataset

Denominator:
- total titles in selected service snapshot

Display:
- exclusive title count
- percent of selected service snapshot

Notes:
- if only one `service` dataset is installed, this card is still valid but should be labeled as provisional in detail text
- we should not hide it, because the count is still mechanically correct inside the currently installed service set

### Gap Opportunity

Question:
What high-value titles on this service do I still not have?

Numerator:
- titles that satisfy all of:
  - exist in the selected service snapshot
  - exist in at least one installed `prestige` or `recent` dataset
  - do not exist in the normalized local library

Denominator:
- all titles in selected service snapshot that intersect installed `prestige` or `recent` datasets

Display:
- missing count
- optional percent of the selected service's prestige/recent intersection

Notes:
- this starts as a comparison card
- later it can feed a dedicated acquisition / queue lane

### Coverage cards for IMDb and genre lists

Question:
How much of this list is present on the selected service?

Primary numerator:
- titles that exist in both the selected service snapshot and the selected list dataset

Primary denominator:
- total titles in the list dataset

Secondary numerator:
- titles that exist in selected service snapshot, in the list dataset, and in the local library

Display:
- service coverage count and percent for the list
- optional local-owned count within that service-covered slice

Example:
- `IMDb Top 250 Coverage`
  - service coverage: `58 / 250`
  - owned locally: `34 / 58`

This is the right shape because it separates:
- what the service menu offers
- what you personally already have from that offering

## Dataset plan

## Supported runtime dataset kinds

Keep the current runtime kinds for now:

- `service`
- `prestige`
- `recent`

Do not introduce a new runtime `dataset_kind` yet.

Reason:
- the current loader and report model already support these three kinds
- genre-classics lists can live under `prestige` without blocking the current rollout

## Dataset classification inside `prestige`

Use naming and metadata conventions inside `prestige`:

| Family | Example dataset ID |
|---|---|
| general prestige | `imdb_top_250` |
| general prestige | `imdb_top_1000` |
| genre prestige | `top_100_scifi` |
| genre prestige | `top_100_fantasy` |
| genre prestige | `top_100_action` |
| genre prestige | `top_100_thriller` |
| genre prestige | `top_100_horror` |
| genre prestige | `top_100_comedy` |
| genre prestige | `top_100_animation` |

Recommended display names:

- `IMDb Top 250`
- `IMDb Top 1000`
- `Top 100 Sci-Fi`
- `Top 100 Fantasy`
- `Top 100 Action`
- `Top 100 Thriller`
- `Top 100 Horror`
- `Top 100 Comedy`
- `Top 100 Animation`

## Dataset source stance

- `service` datasets are service catalogue snapshots
- `prestige` datasets are curated fixed lists
- `recent` datasets are recency slices with release dates
- genre cards must be powered by curated fixed lists, not inferred tags

## Desired payload additions

The current comparison payload is close, but it is not card-first yet.

Desired additions for the comparison response:

- `active_service_dataset_id`
- `active_service_dataset`
- `cards`

Recommended `cards` shape:

```json
{
  "cards": [
    {
      "card_id": "library_capture",
      "label": "Library Capture",
      "group": "menu_breadth",
      "primary_count": 42,
      "primary_total": 180,
      "primary_pct": 23.3,
      "secondary_count": 42,
      "secondary_total": 880,
      "secondary_pct": 4.8,
      "detail": "42 Apple TV+ titles already owned locally."
    }
  ]
}
```

Recommended coverage-card shape:

```json
{
  "card_id": "imdb_top_250_coverage",
  "label": "IMDb Top 250 Coverage",
  "group": "classics",
  "dataset_id": "imdb_top_250",
  "primary_count": 58,
  "primary_total": 250,
  "primary_pct": 23.2,
  "secondary_count": 34,
  "secondary_total": 58,
  "secondary_pct": 58.6,
  "detail": "58 IMDb Top 250 titles are on this service. 34 of those are already owned locally."
}
```

## Upstream implications

- The comparison page should stop leaning on `aggregates` built for union-style service summaries.
- Card computation needs selected-service-first logic, not selected-service-union logic.
- `Exclusive Titles` requires awareness of all installed service datasets, even though only one service is active in the UI.
- `Gap Opportunity` requires cross-joining selected service titles against installed `prestige` and `recent` datasets before subtracting local ownership.
- Genre-classics cards should appear only when the corresponding list dataset is installed.
- Missing list datasets should not create warnings; they should simply suppress those cards.

## Out of scope for this slice

- acquisition queue automation
- ranking titles inside `Gap Opportunity`
- fuzzy matching
- genre inference from local tags or service metadata
- replacing the current separate comparison scan with a shared scan substrate
