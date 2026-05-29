# Wireframe Proposal Spec A: Balanced Ledger

## Use

This is a prompt-ready wireframe specification for an external tool such as Google AI Studio. It must produce an interactive wireframe, not polished final UI art.

The proposal must follow the governing spec in `docs/internal/ui-ux-spec-pamphlet-workbench.md`.

## Intent

This variant is the baseline and most balanced reading of the pamphlet workbench.

Its personality is:

- calm
- sober
- evenly weighted
- very legible

It should feel like an engineer's review instrument, not a dashboard showroom.

## Fixed shape

Render a fixed desktop-first workbench with:

- a shallow top global strip
- a narrow left upstream sliver
- a central two-page spread with equal left and right page authority
- a narrow far-right audit ledger sliver

Keep the spread shape fixed across all shown workflows.

## Surface behavior

### Top strip

Show:

- source path field
- current workflow tabs
- run / stop button
- activity status text

Keep it shallow and dense.

### Left upstream sliver

Show:

- source summary
- concise workflow stats
- bottom-tucked `Reveal File Tree` button
- collapsed file tree by default

### Primary Surface

Show:

- child title such as `Normalize Inspection & Proposal`
- dense inspection table
- selection checkboxes
- sorting / filter ribbon above the table

Do not place final mutation buttons here.

### Secondary Surface

Show:

- child title such as `Normalize Output Preview`
- mode toggle:
  - `Preview Selected Changes`
  - `Diff View`
  - `Full Preview`
- mutation buttons in this surface only

### Audit ledger sliver

Show:

- compressed audit counts or pips
- an `Expand` control

When expanded, the Secondary Surface transforms into audit content.

## Workflows to include

### Normalize

Show:

- selected rename rows on left
- selected downstream tree preview on right
- diff mode example
- full preview example
- `Apply N Changes` button on right

### Delete Junk

Show:

- junk candidates with checkboxes on left
- diff mode showing deletions on right
- `Delete N Files` button on right

### Repair Defaults

Show:

- audio or subtitle issue rows on left
- stream/default consequence preview on right
- repair button on right

### Dashboard

Show:

- profile or action cards on left
- expanded selected card interpretation on right

## Visual treatment

Keep it stripped down:

- grayscale or muted monochrome wireframe
- minimal fill
- simple borders
- no gradients
- no decorative illustrations

It should feel balanced and architectural.

## What should vary in this proposal

Compared to the other three proposals, this one should:

- feel most neutral
- preserve the clearest equal split between Primary and Secondary surfaces
- make the audit sliver present but restrained
