# Pamphlet Workbench UI & UX Specification

## Purpose

This is the governing UI and UX specification for the next-generation movie web UI.

It exists to preserve the design logic before project code is treated as real product direction. It should feed stripped-down wireframe generation, comparison, and iteration. It is internal-only and intentionally implementation-light.

## Core premise

The current UI over-values chrome and under-values the review surface.

The new UI must reverse that hierarchy. It is a fixed-shape workbench with a left-to-right causal reading flow:

`global strip -> upstream sliver -> Primary Surface -> Secondary Surface -> audit ledger sliver`

The user should feel the directional logic physically and semantically:

- what library and workflow is this
- what scan result or proposal derives from that source
- what selection or proposal is being inspected
- what downstream consequence will occur
- what downstream consequence has already occurred

## Fixed spatial grammar

The product shape remains fixed across workflows.

### 1. Global strip

A shallow top strip for global environment and mode.

Owns:

- source path
- current workflow/page
- run / stop
- activity
- future contextual ribbons or sub-ribbons if needed

Does not own downstream mutation commitment by default.

### 2. Upstream sliver

A narrow permanent left sliver.

Owns:

- source-derived context
- flow-local orientation
- concise upstream metrics
- optional expandable file tree

The file tree is upstream context, not a competing inspection surface.

Small safe default:

- a bottom-tucked control reveals a collapsible tree view
- expanding it does not displace the main two-page spread

### 3. Primary Surface

The main left page of the spread.

Owns:

- inspection
- sorting
- filtering
- selection
- proposal review
- dense tables

This is where the user narrows and decides what is under consideration.

### 4. Secondary Surface

The main right page of the spread.

Owns:

- consequence
- preview
- diff
- full landed downstream shape
- mutation / commit controls

This is a true commit surface for mutation-capable flows.

Mutation controls should not collide with the table-oriented controls of the Primary Surface.

### 5. Audit ledger sliver

A narrow permanent far-right sliver.

Owns:

- recorded downstream state
- recent and durable audit cues
- a compact sense that action has history

It is visually present at all times but compressed.

When deliberately expanded, it can occupy the Secondary Surface.

This transformation is acceptable because the user is moving from:

- prospective downstream consequence

to:

- recorded downstream consequence

## Universal preview language

All mutation-capable workflows should use the same Secondary Surface mode language.

### Mode 1: Preview Selected Changes

Default mode.

Meaning:

- live render of the currently selected consequence set

### Mode 2: Diff View

Meaning:

- concrete before / after delta expression

Examples:

- renames show path or structure deltas
- junk deletion shows removals
- remux / defaults repair shows stream-default or mux-state deltas

### Mode 3: Full Preview

Meaning:

- full landed downstream shape after all relevant changes are applied

This is useful, but should not be the default burden on the user.

## Workflow families

### Mutation-capable flows

Examples:

- Normalize
- Delete Weak Encodes
- Repair Defaults
- Delete Junk

Shared rule:

- the left page inspects and selects
- the right page previews and commits

### Curatorial flows

Examples:

- Dashboard
- Canonical Lists

These keep the same spread shape but use slightly different child vocabulary.

Shared rule:

- left page chooses, narrows, or classifies
- right page expands, explains, interprets, or deepens

They should not collapse to a one-panel layout merely because they are less mutative.

The fixed product shape is more important than local convenience.

## Naming rules

Use stable parent labels with controlled local variation.

### Stable parent labels

- `Primary Surface`
- `Secondary Surface`

### Child labels

Derived from workflow role.

Examples:

- `Normalize Inspection & Proposal`
- `Normalize Output Preview`
- `Junk Inspection & Proposal`
- `Junk Output Preview`

Dashboard and Canonical Lists may use more curatorial child vocabulary where truthful.

## Control wording rules

Use concise shared language by default.

Examples:

- `Select All`
- `Diff View`
- `Full Preview`
- `Run`
- `Stop`

Spend more words where consequence clarity matters.

Examples:

- `Apply 12 Changes`
- `Delete 4 Files`
- `Repair 3 Selected Titles`

Do not pad low-risk controls with redundant workflow labels such as `Junk Select All`.

## Audit model

Audit is a first-class downstream concept, not preview residue.

Current repo behavior is inconsistent:

- replacement history lives in the secondary/detail area
- subtitle history lives there too
- junk history is only a session-local fragment

The target model is:

- audit remains visibly present in the far-right ledger sliver
- audit can expand into the Secondary Surface
- audit remains visually and semantically distinguishable from prospective preview

Deferred:

- whether default audit scope is source-scoped or global

## Wireframe constraints

All wireframe proposals derived from this spec must keep the following fixed:

- same five-part left-to-right grammar
- same ownership model of the Primary and Secondary surfaces
- same audit-ledger concept
- same universal preview modes for mutation-capable flows
- same presence of the optional collapsible file tree in the upstream sliver

Wireframe proposals may vary in:

- top strip density
- sliver temperament
- panel chrome severity
- header phrasing cadence
- how aggressively information is compressed

They may not vary in:

- fundamental shape
- surface ownership
- mutation-control placement
- preview-mode semantics

## Prompt-ready output guidance

When using this spec to generate interactive wireframes in an external tool:

- keep visuals stripped down and schematic
- avoid decorative branding or polished final styling
- preserve exact surface ownership and control placement logic
- prefer realistic table rows, toggles, and panel headers over vague placeholder boxes
- show at least these workflows:
  - Normalize
  - Delete Junk
  - Repair Defaults
  - Dashboard
- ensure all four proposal variants are identical in function and differ only in presentation and compression choices

## Open questions intentionally deferred

- exact contextual-command ownership between top strip and local ribbons
- exact audit default scope: source vs global
- final wording of all workflow child labels
- final file-tree depth and truncation policy
- final visual style system beyond wireframe phase
