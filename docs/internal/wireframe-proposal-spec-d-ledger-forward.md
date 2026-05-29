# Wireframe Proposal Spec D: Ledger-Forward

## Use

This is a prompt-ready wireframe specification for an external tool such as Google AI Studio. It must produce an interactive wireframe, not polished final UI art.

The proposal must follow the governing spec in `docs/internal/ui-ux-spec-pamphlet-workbench.md`.

## Intent

This variant explores a stronger sense of downstream consequence and recorded action.

Its personality is:

- procedural
- consequence-aware
- review-and-commit focused
- explicitly stateful

It should still preserve the same shape, but make the audit and consequence model feel most legible.

## Fixed shape

Keep the same fixed workbench:

- global strip
- upstream sliver
- Primary Surface
- Secondary Surface
- audit ledger sliver

No change in ownership or overall function.

## Surface behavior

### Top strip

Normal global strip treatment.

### Left upstream sliver

Normal upstream context treatment.

### Primary Surface

Clear inspection and selection treatment.

### Secondary Surface

Make consequence especially legible:

- preview mode toggle should be prominent
- mutation action buttons should feel obviously downstream
- selected consequence set should be easy to parse

### Audit ledger sliver

Make the compressed ledger slightly more informative than in the other proposals.

Show:

- stronger count cues
- clearer event grouping cues
- more obvious promise that it can expand into a full ledger view

When expanded, the Secondary Surface should clearly transform from prospective state to recorded state.

## Workflows to include

Same four workflows:

- Normalize
- Delete Junk
- Repair Defaults
- Dashboard

But include slightly richer audit examples for mutation-capable flows:

- deleted awaiting replacement
- replaced
- subtitle history
- junk deleted this session

## Visual treatment

Still stripped down and schematic:

- no polished color system
- no final branding
- no production-ready visuals

However, the wireframe should place slightly more emphasis on state transitions and ledger readability than the other variants.

## What should vary in this proposal

Compared to the other three proposals, this one should:

- make the audit concept most visible
- make the shift from preview to recorded history most explicit
- test whether stronger ledger presence improves trust and orientation without becoming distracting
