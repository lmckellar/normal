# Table Principle and Specification

Internal, local-only note.

## Purpose

Define one governing rule for tables so they stop behaving like loose column piles and start behaving like deliberate screen objects.

Tables are now a primary product surface. They should preserve scan speed, row integrity, and page width discipline before they preserve raw field exposure.

## Governing principle

**A table is a single-row reading instrument, not a bucket for fields.**

Each row should read as one horizontal object with a controlled shape.

That means:

- the table must respect the browser width
- columns must earn width based on decision value, not convenience
- rows should resist accidental height growth
- overflow should be managed intentionally, not tolerated
- detail that breaks table shape should move to an adjacent inspection surface, not stay in-cell by default

## Core rules

### 1. Preserve row shape first

Default target:

- one-line rows in standard desktop views
- tightly bounded two-line rows only when the workflow truly requires it

Do not allow uncontrolled multi-line wrapping across the table body.

If text cannot fit, prefer this order:

1. shorten the visible label
2. truncate with ellipsis
3. move full detail to hover, title, expansion, or side-panel inspection
4. hide the column at smaller widths if it is non-critical

### 2. Width is allocated by role

Do not size columns by guesswork or equal distribution.

Each column should be classified before implementation:

- `anchor`: the primary identifying field for the row; gets the largest stable share
- `signal`: compact status, quality, type, state, or counts; should stay narrow
- `decision`: fields directly needed to choose or compare; gets moderate width
- `supporting`: useful but not required for first-pass scanning; collapses earlier
- `overflow`: verbose explanation, paths, diagnostics, prose; not a default table column unless heavily compressed

Small safe default:

- keep one anchor column
- keep supporting columns few
- treat verbose reasoning/path text as overflow unless proven otherwise

Fixed-width exception:

- only the untitled checkbox/select column may use fixed width
- that lane should keep one stable width across related table views so the anchor column does not drift horizontally between dense and sparse tables
- define fixed internal padding for that lane and reuse it rather than letting extra space bloat the control cell
- outside that lane, surplus width should resolve into the anchor column first, not into utility columns

### 3. Padding must serve density and alignment

Padding is not the main width control.

Use padding to keep columns readable, but solve fit with column strategy first.

Default stance:

- compact horizontal padding
- consistent cell rhythm across the table
- extra width belongs to the anchor column, not to repeated padding inflation
- the checkbox/select lane should use one sane fixed padding contract and keep it unchanged across sibling workflows

### 4. Tables must degrade by priority

Responsive behavior should be ordered, not accidental.

When width tightens:

1. remove or hide supporting columns
2. compress signal columns to icon/tag/short label form
3. reduce anchor width only after lower-priority columns have collapsed
4. move overflow content to row detail or adjacent surface

Do not let the table simply wrap downward and call that responsive.

### 5. Long strings are hostile by default

Paths, diagnostic prose, compound titles, and identifiers will sprawl unless constrained.

Default handling:

- single-line clipping in the grid
- full value available on deliberate inspection
- monospace only where comparison accuracy matters
- path columns should show the most decision-relevant segment, not always the full raw string

### 6. The table is not the whole workflow

A table should answer first-pass comparison questions.

It should not also carry:

- full reasoning
- full preview
- full audit history
- large control clusters
- verbose instructions

Those belong in the surrounding workbench surfaces.

## Practical specification

### Column budgeting

For each table, define before implementation:

- the row's anchor field
- which columns are required for first-pass decisions
- which columns collapse first
- what content is delegated out of the table

If this cannot be stated in a few lines, the table is carrying too much.

### Row height policy

- default row height should be stable across the body
- selected state should not materially change row height
- badges, chips, and status labels must be height-disciplined
- expanded rows should be explicit, rare, and visually separate from standard scan rows

### Text overflow policy

- default body cells: no free multi-line wrap
- headers: may wrap only if needed, but should stay concise
- truncation should be visually obvious
- full text reveal must require deliberate user action

### Alignment policy

- text fields align for fast vertical scanning
- numeric and count fields align consistently
- status fields should read as a narrow visual lane, not a drifting paragraph

### Responsive policy

Every important table should have an explicit narrow-width behavior, not just a desktop layout that later breaks.

Minimum expectation:

- desktop: full priority set visible
- medium width: supporting columns collapsed
- narrow width: anchor plus essential signals only, with detail moved elsewhere

## Review checklist

Before calling a table done, ask:

1. Does each row still read as one horizontal object?
2. Which column is the anchor, and is that visible in the shape?
3. Which columns collapse first when width tightens?
4. Which cells can currently grow row height without control?
5. What content is in the table that belongs in the side-panel or preview surface instead?

If those answers are vague, the table is not specified well enough.

## Product implication

This principle affects more than CSS.

It should influence:

- serializer field choice
- API payload shaping for table views
- UI component contracts
- preview/inspection panel responsibilities
- responsive design decisions at the page level

The upstream rule is simple: do not send table surfaces more semantic weight than a row can carry cleanly.
