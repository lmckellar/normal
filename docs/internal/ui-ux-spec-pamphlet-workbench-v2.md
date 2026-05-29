# Pamphlet Workbench UI & UX Specification v2

## Purpose

This is the revised governing UI and UX specification for the next-generation movie workbench.

It supersedes the earlier pamphlet spec in direction, but does not overwrite it.

This version absorbs later thinking from:

- audit ledger semantics
- policy forecast / library shape planner
- community / prestige artefact modeling

It remains internal-only and intentionally implementation-light.

## Why v2 exists

The earlier pamphlet captured an important spatial idea, but it predates several stronger product conclusions.

In particular:

- audit is not a side detail, it is a first-class product surface
- policy and forecast are not side features, they are natural workbench citizens
- durable downstream artefacts matter because future exports and community interpretation depend on them
- the current UI's visibility/status treatment is too scattered and too eager to expose machinery

So this v2 spec keeps the good fixed-shape logic and rewrites the product meaning around it.

## Product stance

`normal` remains a local-first movie workbench.

Its core job is still:

- scan
- classify
- plan
- mutate deliberately
- record consequence

It is not:

- a social product
- a badge garden
- a flag-heavy control cockpit
- a spreadsheet hobby app

The UI should feel like a serious local workbench with a calm but legible record of consequence.

## Core premise

The current UI over-values chrome, under-values review, and fragments consequence across too many mini-surfaces.

The new UI must reverse that hierarchy.

It is a fixed-shape workbench with a left-to-right causal reading flow:

`global strip -> upstream sliver -> Primary Surface -> Secondary Surface -> audit ledger sliver`

The user should feel this chain physically and semantically:

- what library and workflow is this
- what upstream state or policy context produced this view
- what set of titles or rules is under inspection
- what downstream consequence is proposed or projected
- what downstream consequence is already recorded

## Governing principles

### 1. Fixed product shape matters more than local convenience

The workbench should preserve one stable grammar across workflows.

The user should not have to relearn where inspection, consequence, and recorded history live.

### 2. Consequence must be readable

The interface should favor review surfaces over chrome and dashboards over ornament.

When the system proposes or records change, the user should be able to read that consequence plainly.

### 3. Audit is a first-class downstream concept

Audit is not preview residue.

It is the durable record of what the system did, what still needs attention, and what the user later chose to do about it.

### 4. Backend richness must not leak into the UI as flag salad

The backend may track many internal distinctions.

The UI should expose only the small user-facing vocabulary needed to understand and act.

### 5. Policy deserves equal structural seriousness

Library taste, quality floors, and storage constraints are not settings fluff.

They are part of the same downstream consequence model as mutation workflows.

### 6. Future exportability matters now

Even though external prestige/community surfaces are out of scope for core product work, current UI and state-shape decisions should stay friendly to durable snapshots, audit objects, and export bundles.

## Fixed spatial grammar

The product shape remains fixed across workflows.

### 1. Global strip

A shallow top strip for global environment and mode.

Owns:

- source path
- active workflow
- run / stop
- current activity
- concise global context

It does not own primary mutation commitment by default.

### 2. Upstream sliver

A narrow permanent left sliver.

Owns:

- source-derived context
- workflow-local orientation
- concise upstream metrics
- optional expandable file tree
- compact policy or cohort context where relevant

The file tree is upstream context, not a competing inspection surface.

Small safe default:

- a tucked control reveals a collapsible tree view
- expanding it does not displace the main spread

### 3. Primary Surface

The main left page of the spread.

Owns:

- inspection
- sorting
- filtering
- selection
- narrowing
- rule definition where the workflow is policy-oriented
- dense tables and list views

This is where the user decides what is under consideration.

### 4. Secondary Surface

The main right page of the spread.

Owns:

- proposed consequence
- projected consequence
- diff
- full landed shape
- commit controls for mutation workflows
- forecast controls and result framing for policy workflows

This is the consequence surface.

It should feel downstream of the Primary Surface, not like a second unrelated dashboard.

### 5. Audit ledger sliver

A narrow permanent far-right sliver.

Owns:

- recorded downstream state
- latest consequential events
- active follow-up counts
- a compact sense that action has history

It is always present but compressed.

When deliberately expanded, it may occupy the Secondary Surface.

That transformation is acceptable because the user is moving from:

- prospective or projected consequence

to:

- recorded consequence and unresolved follow-up

## The three visible questions

The workbench should always answer only three visible questions:

1. what is under consideration
2. what will happen or is projected to happen
3. what happened and what still needs attention

This should replace the current feeling of many jostling status ideas.

The mapping is stable:

- Primary Surface answers question 1
- Secondary Surface answers question 2
- audit ledger answers question 3

## Workflow families

The workbench supports three product families.

### Mutation workflows

Examples:

- Normalize
- Delete Weak Encodes
- Delete Junk
- Repair Defaults

Shared rule:

- the left page inspects and selects
- the right page previews and commits
- the ledger records what actually happened

### Curatorial workflows

Examples:

- Dashboard
- Canonical Lists

Shared rule:

- the left page narrows, groups, or classifies
- the right page expands, explains, or interprets
- the ledger remains present as the record of relevant downstream state

These should not collapse to one-panel layouts merely because they are less mutative.

### Policy workflows

Examples:

- Library Shape Planner
- future policy editor / forecast surfaces

Shared rule:

- the left page defines intent and constraints
- the right page shows forecasted downstream consequence
- the ledger records saved policy snapshots and prior forecast moments

## Secondary Surface modes

Mutation-capable workflows should share a stable consequence language.

### Mode 1: Preview Selected Changes

Default mode.

Meaning:

- live render of the currently selected consequence set

### Mode 2: Diff View

Meaning:

- concrete before / after expression

Examples:

- renames show path deltas
- junk deletion shows removals
- repairs show stream-default or mux-state deltas

### Mode 3: Full Preview

Meaning:

- full landed downstream shape after all relevant changes are applied

This is useful but should not be the default burden on the user.

### Policy mode variation

Policy workflows may use equivalent consequence language without pretending they are mutation previews.

Examples:

- `Current vs Projected`
- `Cohort Impact`
- `Storage Forecast`

The important part is not label uniformity at all costs.

The important part is preserving the same structural meaning:

- left defines
- right shows downstream consequence

## Naming rules

Use stable parent labels and restrained child variation.

### Stable parent labels

- `Primary Surface`
- `Secondary Surface`
- `Audit Ledger`

### Child labels

Derived from truthful workflow role.

Examples:

- `Normalize Inspection`
- `Normalize Output Preview`
- `Junk Inspection`
- `Junk Output Preview`
- `Policy Definition`
- `Library Shape Forecast`

Avoid inflated or overly computery phrasing.

## Control wording rules

Use concise shared language by default.

Examples:

- `Select All`
- `Diff View`
- `Full Preview`
- `Run`
- `Stop`
- `View Details`

Spend more words where consequence clarity matters.

Examples:

- `Apply 12 Changes`
- `Delete 4 Files`
- `Repair 3 Selected Titles`
- `Save Policy`

Do not pad low-risk controls with redundant workflow labels.

## Ledger and visibility model

The far-right ledger replaces the idea of a scattered visibility monitor.

It should not behave like multiple unrelated status widgets.

### Compressed ledger

Compressed state should show only:

- latest meaningful events
- unresolved follow-up counts
- plain language cues that history exists

Examples:

- `Deleted 4 weak encodes.`
- `2 titles are awaiting replacement.`
- `Repaired subtitle defaults for 3 titles.`
- `1 review item remains.`

### Expanded ledger

Expanded state should show:

- chronological ledger entries
- active follow-up lists
- simple filters where useful
- event details on demand

It should read like a calm record of consequence, not a warning farm.

### Sentence-first language

The ledger should use concise factual sentences rather than backend status labels.

Avoid:

- code-like chips
- many tiny flag buttons
- exposing internal state names

Prefer:

- plain statements
- one or two obvious verbs
- simple grouping

### Small user action vocabulary

Visible verbs should stay narrow and concrete.

Good examples:

- `Hide`
- `Restore`
- `Return to List`
- `Mark Handled`
- `View Details`

The UI should not force users to parse abstract audit terminology.

## One deletion ledger

There should be one deletion history, not separate deletion worlds.

This includes:

- weak encode deletions
- junk video deletions
- junk sidecar/spam deletions
- audio-packaging deletions if retained
- future deletion-capable flows

The current split is stale and product-odd because the user experiences all of these as deletion actions while the product stores and presents them as separate histories.

### Replacement is a follow-up view

`Deleted awaiting replacement` remains meaningful, but it is not a separate ledger.

The cleaner model is:

- one deletion ledger
- one active replacement follow-up list derived from it
- filters such as `all deletions`, `replacement`, `junk`

This is both more intuitive in the UI and cleaner in the backend.

### Active lists versus history

The system should distinguish between:

- durable ledger history
- active follow-up lists derived from that history plus current state

Examples of active follow-up:

- awaiting replacement
- subtitle review items
- Normalize review leftovers

Users may remove something from an active list without erasing its history.

That later user choice should itself become a ledger event.

## Proposal versus record

Proposal semantics should not flood the recorded side of the workbench.

Proposal belongs to preview.
Record belongs to consequence.

Selections, confidence signals, and review reasons may exist in the proposal surface, but they should enter the ledger only when they become:

- applied results
- unresolved follow-up
- explicit later user decisions

This keeps the ledger calm and useful.

## Policy workflow stance

Policy should now be treated as a first-class workbench citizen rather than an optional afterthought.

### Primary Surface for policy

Should own:

- cohort rules
- preferred quality ladders
- minimum floors
- drive capacity and reserved-space constraints
- concise explanation text

### Secondary Surface for policy

Should own:

- current vs projected library shape
- projected storage delta
- projected quality distribution
- cohort impact breakdown
- fit or overflow against practical capacity

### Ledger for policy

Should own:

- saved policy revisions
- prior forecast snapshots
- later record of policy shifts over time

This keeps policy inside the same accountability model as mutation workflows without pretending both are identical.

## Dashboard and canonical stance

Curatorial flows still belong in the same workbench grammar.

The dashboard should not try to impersonate a separate product.

Canonical lists should not feel bolted on.

They should behave like adjacent reading modes over the same library truth:

- the left page narrows or groups
- the right page expands or interprets
- the ledger quietly retains the downstream record context

## Artefact awareness

The workbench should stay friendly to a future durable artefact model.

That means UI decisions should not assume history is browser-local or workflow-fragmented.

Relevant underlying object families are expected to include:

- library snapshots
- mutation events
- mutation items
- policy snapshots
- forecast snapshots
- export bundles

The UI does not need to expose these terms directly.

But it should be shaped so those objects can support it cleanly.

## Local-first and privacy stance

The core workbench remains local-first.

External prestige or community interpretation is out of scope for the core UI.

However, the UI should not block future reviewed export by assuming:

- raw title disclosure is always acceptable
- browser caches are authoritative
- workflow histories can stay ad hoc forever

Small safe default:

- local truth first
- reviewed export later
- aggregate-first external posture if ever pursued

## Visual posture

The interface should feel:

- calm
- structured
- serious
- legible
- consequence-aware

It should not feel like:

- an enterprise dashboard
- a gamified badge field
- a flag-heavy admin console
- a generic media library shell

The main review surfaces should do the expressive work, not chrome density.

## Non-goals

- do not surface backend codes as user vocabulary
- do not create separate mini-ledgers per workflow
- do not scatter visibility/status logic across multiple unrelated panels
- do not treat browser-local convenience fragments as authoritative audit
- do not collapse the workbench shape for individual workflows
- do not let future community ideas bloat the core local UI

## Open questions intentionally deferred

- exact default audit scope: source-scoped, cross-source, or switchable
- exact policy save/revision interaction wording
- exact compact ledger density before readability degrades
- whether some curatorial workflows need lighter Secondary Surface headers than mutation workflows
- how much of forecast uncertainty should be shown inline versus on demand

## Immediate design consequences

This v2 pamphlet implies the next major implementation direction should favor:

1. one common ledger event model
2. one unified deletion history
3. one stable fixed workbench grammar across mutation, curatorial, and policy flows
4. sentence-first consequence language
5. durable snapshot and forecast-friendly state underneath the UI
