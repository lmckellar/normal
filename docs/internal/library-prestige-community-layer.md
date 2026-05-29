# Library Prestige / Community Layer

## Purpose

This note records a serious downstream product idea that should remain out of core `normal` for now, but should still influence backend thinking today.

The idea is an external prestige and community layer built from `normal` snapshots and audit objects.

This should be treated as:

- real
- external to the core local workbench
- not an immediate implementation target
- relevant to current backend and state-shape decisions

## Core framing

`normal` should remain a local-first movie workbench.

The community concept does not require `normal` itself to become a social product.

The cleaner model is:

- `normal` scans, plans, mutates, and records
- an optional external site consumes exported snapshots
- that site turns downstream library objects into prestige, comparison, and shared ritual

This separation matters because it preserves the product core while still allowing a wider cultural layer to form around it.

## Why this matters

This is not merely a gimmick.

If done well, it could become a differentiating layer between:

- a useful local tool that silently replaces paid labor

and:

- a useful local tool that also turns curation, improvement, and discipline into something communal, legible, and fun

That makes it more than utility software.

It becomes a system with identity, status objects, and stories.

## Product logic

The reason this works is simple:

`normal` already trends toward producing readable downstream objects such as:

- canonical-list coverage
- quality-tier distribution
- replacement pressure
- mutation counts
- normalization outcomes
- audit history
- before/after library state

Those are already meaningful locally.

The external layer simply reinterprets them as community-facing prestige signals.

## Strong principle

Prestige should be derived from curation, coherence, uplift, and taste.

It should not collapse into a dumb competition around raw library size.

If “biggest hoard wins” becomes the main story, the community layer will drift away from `normal`'s stated philosophy.

The better orientation is:

- who curated most sharply
- who improved most dramatically
- who achieved the strongest result within constraints
- who demonstrated the cleanest one-shot confidence

## Example board families

These are not final categories, but they show the shape of the idea.

### Canonical boards

Examples:

- highest IMDB Top 100 coverage
- strongest Top 50 Animation coverage
- strongest Action or other genre-bucket coverage

### Weight divisions

These exist to stop giant libraries from dominating every board by default.

Examples:

- by title-count bands
- by total-storage bands
- by cohort-specific divisions

This allows smaller libraries to compete within a truthful bracket.

### One-shot boards

This is especially native to `normal`.

Examples:

- biggest safe one-pass normalization rewrite
- largest single apply event
- strongest one-shot cleanup against a heavily mangled library

This celebrates preparation, confidence, and clean downstream consequence.

### Most improved boards

Examples:

- strongest improvement from first snapshot to later snapshot
- largest increase in canonical coverage
- largest drop in junk burden
- largest upward shift in quality floor

This rewards transformation, not just incumbency.

### Purity / discipline boards

Examples:

- strongest normalized naming adherence
- lowest junk burden
- strongest profile-floor compliance
- best subtitle/default-audio hygiene

### Recurring ritual boards

Examples:

- `Employee of the Month`

This can be funny without being empty if it resets monthly and is awarded for strongest compliance against the user's own declared internal policies.

That gives the external layer a recurring ceremonial object that rewards discipline and consistency rather than raw library scale alone.

### Constraint-aware boards

Examples:

- best canonical outcome under a storage cap
- strongest quality uplift within a small-library bracket
- best storage-economics result

This is where the community concept can intersect very naturally with the policy forecast / library shape planner idea.

## Tone and identity

This layer should feel playful, proud, and slightly ceremonial.

It should not feel like:

- enterprise analytics
- sterile stats dashboards
- generic gamification sludge

The product voice can support:

- prestige
- nicknames
- trials
- boards
- badges
- category rituals

The earlier “one-shot Sally” style instinct is useful here. It points toward a distinctive vocabulary rather than generic leaderboard language.

## Why this belongs outside core `normal`

Keeping this external is important for several reasons:

- the local workbench should stay focused on scanning, planning, mutation, and safety
- many users will not want any community layer at all
- privacy expectations around personal libraries are sensitive
- the web UI should not be bloated with social surfaces that do not help local mutation decisions

So the intended product split is:

- local `normal`: authoritative library workbench
- external site: optional prestige and community interpretation layer

## Privacy and consent posture

This idea only works if users retain strong control over what leaves their machine.

Small safe default:

- export is opt-in
- upload is user-reviewed
- pseudonymous identity first
- aggregate stats first
- raw title disclosure optional, not assumed

The system should be able to support prestige without forcing people to publish their full library contents.

## Backend relevance right now

This note matters now because it changes how backend state should be thought about.

At present, `normal` state is fragmented across:

- repo-local standards
- user-local queue and history files
- process-local caches
- browser convenience caches

See the current split in [docs/architecture.md](../architecture.md): repo-local `movie_standards.json`, user-local `movie-replacement-queue.json` and `subtitle-fix-history.json`, process-local movie profile cache, and browser-local convenience snapshots.

This is workable for the current app, but it is not yet a coherent downstream object model.

That matters because a community layer wants stable, legible exported objects rather than ad hoc per-lane state fragments.

## Auditability pressure

This idea strengthens an already-existing pressure in the repo:

- replacement queue has durable state
- subtitle history has separate durable state
- junk deletion still lacks equivalent durable coherent audit posture

This mismatch is already called out in [docs/safety.md](../safety.md) and elsewhere.

If the product eventually wants to express:

- first snapshot
- later snapshot
- most improved library
- biggest safe one-shot rewrite
- strongest quality uplift

then the current fragmented and lane-specific audit posture becomes more obviously insufficient.

In simple terms:

community prestige is only as trustworthy as the audit and snapshot model underneath it

## Desired downstream objects

If this concept is pursued later, `normal` will likely want a stable exportable object model for at least:

- library snapshot
- policy snapshot
- canonical coverage snapshot
- quality-profile distribution snapshot
- mutation event summary
- audit timeline
- before/after comparison
- derived achievement metrics

The key is not that all of these must exist now.

The key is that future state work should avoid making them harder to derive cleanly.

## Snapshot concept

A likely future direction is a formal snapshot object that can represent a library at a given moment.

That snapshot could eventually support:

- local comparison inside `normal`
- external export to a prestige site
- most-improved and one-shot derivations
- policy-forecast comparison against actual downstream results

This may become the cleaner unifying object than today’s scattered per-workflow state artifacts.

## Architectural implication

There is already a large rewrite being implied by current state-management inconsistency.

This concept does not create that rewrite pressure from nothing.

It simply makes the need easier to see and easier to justify.

The likely architectural direction is toward:

- cleaner durable state objects
- more explicit snapshot and audit boundaries
- less ad hoc per-lane history handling
- exportable downstream object shapes

That would serve both:

- core local product coherence
- future external prestige/community use

## Smallest safe backend posture now

Without implementing any community feature yet, the backend can still stay friendly to this future by:

1. treating snapshot shape as a real future concern
2. treating audit consistency as core product work, not optional cleanup
3. avoiding lane-specific state models where a shared downstream object should exist
4. keeping browser cache clearly secondary to durable local state
5. designing new derived objects so they can be exported later without heroic translation work

## What not to do

Do not:

- bolt leaderboard concepts directly into the current workbench
- design backend objects around public web display first
- leak raw library contents by default
- let giant-library dominance become the main prestige logic
- assume all users want social participation

The future value of this idea depends on restraint.

## Current conclusion

This concept should be remembered as a serious downstream product layer, not a joke idea.

It is ahead of its implementation time, but it is relevant now because it sharpens the requirements around:

- state coherence
- auditability
- snapshot design
- exportable downstream objects

The right move for now is not to build it.

The right move is to let it influence how the backend rewrite and downstream object model are conceived from this point onward.
