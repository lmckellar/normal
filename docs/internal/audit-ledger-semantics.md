# Audit Ledger Semantics

## Purpose

This note defines the intended meaning and behavior of the audit ledger and the fixed visibility area in the next workbench.

It exists to prevent two bad outcomes:

- backend event/state richness leaking into the UI as flag salad
- workflow-specific history fragments drifting into separate mini-systems

This is a product semantics note, not a storage schema spec.

## Core stance

The system should record actions immutably underneath.

The interface should present consequences simply above that.

The ledger is not a status garden.
It is a readable record of what the system did, what still needs attention, and what the user later chose to do about it.

## Primary rule

Every consequential system action should become a ledger event.

Examples:

- Normalize applied
- junk deleted
- weak encode deleted
- audio defaults repaired
- subtitle defaults repaired
- item removed from replacement plan without replacement

If the user takes a later action that changes the meaning of an earlier active item, that later action should also become a ledger event.

Examples:

- replacement item removed from active follow-up
- review item re-opened
- restored from trash

The system should not silently drop accountable items from history.

## UI rule

The UI should not expose backend state names directly unless they are truly user-meaningful.

Avoid:

- code-like labels
- dense status chips
- many tiny action buttons
- separate panels each inventing their own mini-language

Prefer:

- sentence-based entries
- one fixed place for recorded consequence
- a very small action vocabulary
- filters and grouping only where they improve reading

## The three visible questions

The fixed visibility area should always answer only three questions:

1. what is proposed
2. what happened
3. what still needs attention

These should not be treated as three unrelated widgets.

They are one causal stack:

- proposal belongs to the preview side
- recorded consequence belongs to the ledger side
- active follow-up is the bridge between them

## One fixed visibility area

The current visibility monitor feeling of "seven jostled ideas" should be removed.

Small safe default:

- one fixed ledger/visibility area on the far right
- compressed by default
- expandable into the Secondary Surface

Compressed state should show only:

- latest meaningful events
- unresolved follow-up counts
- plain language cues that history exists

Expanded state should show:

- chronological ledger entries
- active follow-up list
- simple filtering

## Sentence-first ledger language

Ledger entries should read like concise factual sentences.

Examples:

- `Deleted 4 weak encodes.`
- `2 titles are now awaiting replacement.`
- `Removed 1 title from the replacement plan without replacement.`
- `Repaired subtitle defaults for 3 titles.`
- `Applied Normalize changes to 12 titles.`
- `1 title remains for review.`

The UI should look like a record of consequence, not a control board full of badges.

## Small user action vocabulary

The visible user verbs should stay narrow and concrete.

Good examples:

- `Hide`
- `Restore`
- `Return to list`
- `Mark handled`
- `View details`

Avoid exposing abstract audit terms like:

- `compensate`
- `dispute`
- `reopen`

Those ideas may still exist in backend semantics, but the interface should prefer plain operational wording.

## One deletion ledger

There should not be two separate deletion histories.

All deletion events should belong to one unified deletion ledger.

This includes:

- weak encode deletions
- audio-packaging deletions if still modeled that way
- junk video deletions
- junk sidecar/spam deletions
- future deletion-capable workflows

The current split is product-odd because:

- one deletion family is treated as durable replacement history
- another deletion family is treated as session-local junk history
- the user experiences both as "I deleted something"

The ledger should reflect the user truth first.

## Replacement as a filter, not a separate world

`Deleted awaiting replacement` should remain a meaningful concept, but not a separate deletion history.

The cleaner model is:

- one deletion ledger
- one optional active replacement follow-up list derived from it
- filters such as `replacement`, `junk`, `all deletions`

That means a deletion event can carry additional consequence tags such as:

- created replacement follow-up
- no replacement expected
- restored later

But the base history is still one deletion history.

## Active lists versus history

The system should distinguish between:

- ledger history
- active follow-up lists

History is durable and chronological.

Active follow-up lists are operational views derived from the history plus current state.

Examples:

- awaiting replacement
- subtitle review items
- Normalize review leftovers

This distinction matters because users often want to remove something from an active list without pretending it never happened.

## Handling "take this out of the audit trail"

The honest product move is usually:

- remove it from the active list
- keep the history
- record the later user action

Example:

`Deleted awaiting replacement` item is manually removed by the user.

Do not silently erase it.

Instead record:

- original deletion event
- later event: `Removed from replacement plan without replacement.`

Then:

- it no longer appears in the active replacement list
- it still exists in deletion history

This closes the current accountability blind spot.

## Normalize and proposal semantics

Do not let proposal semantics flood the ledger.

Proposal belongs to preview.
Ledger belongs to applied consequence.

So:

- selections
- confidence buckets
- review signals
- proposal reasons

may exist in preview presentation, but should enter the ledger only once they become:

- applied result
- unresolved follow-up
- explicit user decision

This keeps the recorded side calmer than the proposal side.

## Backend implications

The backend may need richer internal event typing than the UI shows.

That is acceptable.

But the backend should still converge on a common event family so the UI can stay simple.

Minimum useful shared concepts:

- event kind
- event time
- workflow
- consequence count
- follow-up effect
- optional linkage to prior event

The UI should translate those into plain ledger sentences and a small number of derived lists.

## Workbench implications

In the pamphlet workbench grammar:

- Primary Surface owns inspection and selection
- Secondary Surface owns preview and commit
- audit ledger sliver owns recorded consequence and active follow-up

When the ledger expands into the Secondary Surface, the user is changing mode from:

- what will happen

to:

- what happened and what still needs attention

That transition should be explicit and calm.

## Non-goals

- do not expose internal state words everywhere
- do not create separate mini-ledgers per workflow
- do not silently erase accountable deletion actions
- do not turn the ledger into a warning badge farm
- do not treat browser-local convenience fragments as real audit

## Immediate design consequences

For the upcoming backend and UI rework, this implies:

1. define one common ledger event model
2. define one unified deletion history
3. derive replacement and other follow-up lists from ledger events plus current state
4. present the ledger in sentence-first language
5. keep proposal/status machinery out of the recorded surface unless it becomes an actual consequence
