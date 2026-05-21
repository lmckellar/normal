# Product Statement

*Authorship: Gently user-edited.*

Human authored update: This document was transcribed from my insane, hurried scrawlings by the ever patient GPT5.4 that has accompanied me so well throughout this journey. He has, sadly, collpased far too much information for my liking or for this to coherently fit with what i consider to be my states positions regarding authorship for this project, nascent thoough they may be. Time is short right now, so consider this to be a purely AI summarized document for now - that is marked as intended for complete re-writing into human output. The original transcript of the conversation and notes that produced this artefact have been preserved in internal/docs.

`normal` has evolved from a safety-first, probe-heavy file renaming tool with less clearly separated functions into a highly opinionated movie-library workflow that now asserts the following.

## A Good Pirate Movie Library Should

- have the most obvious, clear, and consistent naming convention of `Title (Year)` unless a duplicate or alternate version needs differentiation
- define an intended quality stance and library policy, then apply it unanimously while still giving the user visibility into the shape and contents of the library
- be clear of Samples, Features, Extras, and other high-load, low-payoff media ephemera
- improve the files at their source before worrying about downstream client quirks like Plex versus Jellyfin behavior

For `normal`, the quality stance is anchored between a minimum of respectable web-streaming-service level material and a maximum of 4K UHD remux, with logical gradations in between.

## Physical Storage Economics

`normal` adheres to a principle of physical storage economics. The larger a media object becomes, the greater the burden of proof becomes on it to justify its existence.

`normal` does not consider maximum bitrate the holy grail. It does not automatically permit large packaged metadata payloads to exist without reason, including audio layouts bloated with unnecessary language options.

## Scan Economics

`normal` also adheres to scan economics. It respects the fact that it is often reading and writing to a physical drive. As such, it should aim to perform the breadth of its functions with the absolute minimum of read and write.

This is not just a scanning detail. It crosses into script shape, workflow structure, function boundaries, maintenance scanning, caching, local storage, and most importantly the assertion of an opinionated downstream object shape. `normal` should decide what the target state is, what the required steps are to get there, and then pursue that state as confidently as the hardening evidence allows.

## Opinionated, Yet Merciful

`normal` is opinionated, yet merciful. It understands that mistakes happen and tastes change. It also understands that migrating the centre-mass of quality of a library upward can be painful when the original library shape was anchored on the wrong encode profile.

Its answer is aligned with both scan economics and physical storage economics:

- define a minimum floor of garbage via quality profiles
- scan to identify which movies are garbage by that policy
- shift-delete those weak encodes in a single pass
- record them as deleted and awaiting replacement

This instantly frees drive space, reduces future scan overhead, and centralizes replacing weak encodes into a clean list that updates itself. When a deleted candidate is replaced by a better copy, `normal` should recognize that and move it off into replacement history automatically.

## Naming, Defaults, and Downstream Shape

`normal` asserts that hands should be devoted to popcorn at the start of a movie, not fiddling with subtitle controls. Its default posture is:

- forced subtitles by default if they exist
- English-audio primary should default to no subtitle
- foreign-audio primary should default to English subtitle

It also asserts that a library of 5,000 poor films is weaker than a library of 1,000 excellent and canonically significant ones. Canonical list comparison exists to orient the user against curated movie buckets, not just to inflate counts.

The planned regional estimate matrix belongs in that same orientation layer: a lightweight externally updated research table that compares a user library against the rough canonical depth of a known platform in a region. It is intended as a directional reference, not a guarantee of actual streaming-catalog shape.

## Internal Confidence and Compression

In its journey, `normal` did not discard its internal review, proposal, and triaging architecture. It simply became confident enough in that architecture to compress it together with higher confidence, becoming more sensitive to genuine edge cases and less wasteful everywhere else.

## What Must Be Crystal Clear

`normal` is now aggressive by default and, out of respect, strongly implores the user to perform several simple sanity and safety checks against test files on bare metal before allowing any real scan to touch a precious live library.

The minimum recommended checks are:

1. Goal: ascertain whether `normal` is set up correctly, whether it ingests your media desirably in its current structure, and whether it scans without issue.
   Suggested test: make an `Example Movies` directory on your local drive with a representative cross-section of your library. Think of this like a Noah's Ark of naming and foldering conventions. You do not need to hit anything yet. This is a ground-level sanity check that the Python scripts, UI, dependencies, and probes are all actually working together.
2. Goal: ascertain whether drive pathing, scanning, and probing are fine on the external hard drive if you store media on a mechanical drive.
   Suggested test: copy the same `Example Movies` folder to the external drive and repeat the experiment there.

From there, validate as far as you need before trusting live execution. It obviously makes sense to run the example library through the full range of motion and test each feature in turn.

`normal` accommodates that well: the test library simply becomes another selectable library with its own storage and audit trail, alongside the main library and any other roots you use. Stay in the test environment until you are comfortable running live.

## Safety and Visibility Promises

- `normal` will never delete a file on your system without you explicitly performing two approval-gating actions: selection and confirmation
- `normal` seeks to maximize visibility of what is being changed, why it is being changed, and what it is being changed to while minimizing friction
- `normal` will not silently destroy or rename something; the intended downstream actions are visible before they run

## Audit Logging: Useful, Not Yet Coherent

`normal` seeks to keep an audit log of actions, but this arrived late and remains half-baked.

The honest current description is:

- already useful
- not yet a clean and coherent management of state and storage
- with a notable gap around long-term permanence and accountability for junk-deleted items

The newer aggression in junk deletion has not yet been paired with equally mature destructive-action logging. That gap should be treated as real, visible, and scheduled to be addressed rather than hand-waved away.
