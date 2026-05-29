# Policy Forecast / Library Shape Planner

## Purpose

This note defines a likely next product surface for `normal`.

It extends the current quality-profile editing model into a cleaner and more literal policy workflow:

- define policy intent
- project downstream library shape
- estimate storage consequence
- decide whether the policy is desirable and practical before acting

This is internal-only and exploratory, but it is intended to be concrete enough to guide future implementation.

## Why this exists

The current repo already exposes editable quality-profile definitions and replacement-candidate thresholds via repo-local `movie_standards.json`.

That is useful, but it is still mostly a stance-threshold editor.

The missing object is a higher-order policy layer:

- which kinds of films should aim for which quality tier
- what the preferred fallback order is when the ideal is unavailable
- what minimum floor is acceptable for each cohort
- what this policy would do to the actual physical shape of the library

This matters because a policy without projected consequence is only half a policy.

For `normal`, the more truthful product question is not only:

- what do I prefer

It is also:

- what library shape does that preference imply
- what will it cost in storage
- can my drive afford it

This aligns directly with the existing product principles around physical storage economics and visible downstream shape.

## Core product move

The key move is to treat policy as a first-class object rather than a loose cluster of quality-profile cutoffs.

Quality profiles remain important, but they become supporting tiers inside a broader policy system.

In simple terms:

- quality profiles classify what a file currently is
- policy rules express what a title should ideally be
- forecast compares current shape to desired shape

This is the conceptual bridge between the current dashboard and a truer planning surface.

## Example policy logic

The intended policy model should be able to express ideas such as:

- IMDB Top 100 or similarly canonical material should prefer `reference`
- visually rich action films should lean upward by default
- less demanding or less rewatchable films can start at `library_grade`
- animation may tolerate lower bitrate floors or softer target tiers because it compresses more gracefully

The important part is that these are not just stricter thresholds.

They are conditional preference rules applied to cohorts.

## Smallest safe product model

Do not begin with a giant questionnaire about bitrate philosophy.

The smallest safe default is a compact rule model that uses metadata `normal` already knows or already intends to know cheaply.

### Rule inputs

First pass should be limited to:

- canonical-list membership
- genre or genre bucket
- animation flag
- year band
- resolution bucket

Avoid introducing broad free-form rule builders too early.

### Rule outputs

Each rule should produce:

- preferred quality ladder
- minimum acceptable floor
- short explanation text

Example:

- `Top 100`: prefer `reference`, floor `collector_grade`
- `Animation`: prefer `collector_grade`, floor `library_grade`
- `Comedy`: prefer `library_grade`, floor `library_grade`

The ladder matters because it expresses practical fallback, not just an ideal target.

## Forecast is the real acknowledgement

The more useful product acknowledgement is not merely that a policy exists.

It is that `normal` can tell the user what the policy would likely do to the library before the user commits to it as a governing taste.

Given a library such as:

- `1000` movies
- `5 TB` current total size
- `10 TB` drive capacity
- most files currently `library_grade` at best

The planner should answer:

- what would the projected total library size be under this policy
- how much additional storage would be required
- how the quality-tier distribution would shift
- which cohorts are driving the mass increase
- whether the policy fits within the available storage budget

That is the point where policy becomes operational rather than rhetorical.

## Three connected layers

This concept likely wants three connected layers, not one.

### 1. Policy intent

Defines desired target shape.

Examples:

- `Top 100 -> prefer reference, floor collector_grade`
- `Animation -> prefer collector_grade, floor library_grade`
- `General catalog -> prefer library_grade, floor library_grade`

### 2. Forecast model

Projects what the policy implies.

Examples:

- current library shape
- target library shape
- estimated uplift by cohort
- projected storage delta
- projected fill percentage

### 3. Constraint layer

Lets the user state a practical boundary.

Examples:

- drive capacity
- reserved free space
- maximum acceptable projected total

This unlocks two different product questions:

- if I apply this policy, what will it cost
- given this storage cap, what is the best achievable shape

The second question is especially strong because it turns the system from an editor into a planner.

## Relationship to the workbench

This concept already has a natural home in the pamphlet workbench grammar.

The existing left-to-right flow answers the placement question without much debate.

### Primary Surface

Should own:

- policy definitions
- cohort rules
- preference ladders
- practical storage constraints

This is where the user defines intended library taste and boundaries.

### Secondary Surface

Should own:

- projected downstream library shape
- forecast totals and deltas
- cohort impact breakdown
- current vs projected comparison

This is where the user sees the consequence of the declared policy.

### Audit ledger sliver

Should own:

- saved policy revisions
- prior forecast snapshots
- eventual record of policy changes over time

This keeps policy history distinct from file-mutation history while still belonging to the same downstream accountability model.

## Histogram stance

The histogram should not be treated as the hero object of this concept.

It was useful because it surfaced library shape.

But if policy definition and forecast become clean and legible, the histogram may be demoted from primary surface to optional supporting instrument.

That is not a rejection of the histogram.

It is a clearer assignment of responsibility:

- policy editor explains intended shape
- forecast explains projected shape
- histogram, if retained, helps visualize one aspect of that shape

If the core policy flow lands cleanly, the product may no longer need to lean on the histogram for meaning.

## UI posture

This should not feel like:

- a 100-step questionnaire
- a spreadsheet for bitrate hobbyists
- an expert-only rules engine

It should feel like:

- a concise declaration of taste
- a practical forecast of consequence
- a readable answer to whether the policy is worth adopting

That means:

- very few first-pass rule inputs
- strong defaults
- visible explanations
- immediate consequence preview

## Forecast honesty

Forecasting must declare its basis and avoid fake precision.

Small safe default:

- estimate target size from runtime, resolution, and target bitrate floors
- clearly label the result as a forecast
- allow low / mid / high estimate bands if confidence needs breathing room

The purpose is not to promise exact future library size.

The purpose is to make policy practical enough to reason about before re-curating the collection around it.

## Upstream implications

If this concept is pursued, it will likely have consequences beyond dashboard wording.

Relevant implications:

- `movie_standards.json` may no longer be the whole governing model; policy rules may need a new persisted object or a clean extension of the current one
- canonical-list and genre membership become more central to quality planning, not just dashboard ornament
- forecast calculations should remain scan-economical and should avoid turning every policy edit into a full expensive library recomputation where possible
- replacement-candidate logic may eventually want to reference policy intent, not only a flat quality-profile floor

These implications should be considered before implementation so the repo does not grow two competing policy systems by accident.

## Smallest safe implementation slice

If this moves into code, the first coherent slice should likely be:

1. add a repo-local persisted policy definition object
2. support a very small rule vocabulary
3. compute projected target tiers for scanned titles
4. estimate current vs projected storage totals
5. render this as a dashboard-adjacent planning surface

Do not begin with:

- arbitrary nested boolean rule builders
- per-codec ideology editing
- heavy forecast visual complexity

The main job of v1 is to prove that policy definition plus forecast feels cleaner and more cohesive than histogram-first dashboarding.
