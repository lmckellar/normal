# Community Layer Artefacts And Boards

## Purpose

This note turns the existing prestige/community idea into a more operational shape.

The immediate question is not "what should the leaderboard look like".

It is:

- what durable artefacts should `normal` produce
- which of those artefacts belong to core local product work
- which downstream board families those artefacts would unlock later

This stays internal-only and local-first.

## Core conclusion

If the future external layer is serious, then the first priority inside `normal` is a coherent audit and snapshot model.

That matters more than repairing current Normalize Preview/Selector behavior in isolation because:

- the current UI is already queued for major rework
- the current audit posture is uneven across workflows
- downstream prestige only works if exported objects are durable and legible

Small safe default:

- treat community as a future export consumer
- treat audit and snapshots as present-day core backend work

## Current state

The repo already has the beginnings of this model, but not yet a unified one.

Durable today:

- replacement queue history
- subtitle fix history
- repo-local standards

Weak or fragmented today:

- junk deletion history is effectively UI-local/session-local
- Normalize outcomes are proposal/apply oriented but not yet expressed as stable downstream mutation records
- audit concepts are split by workflow rather than shaped as one library event model

This means the product can show some historical consequence, but cannot yet export a clean library story.

## Target artefact families

The community layer should not ingest raw UI state.

It should ingest a small set of durable artefact families.

### 1. Library snapshot

Point-in-time description of the library.

Smallest safe contents:

- `snapshot_id`
- `source_root_id` or equivalent local library identity
- `captured_at`
- title count
- total storage bytes
- quality-tier distribution
- resolution distribution
- canonical-list coverage counts
- junk burden counts
- policy profile summary if present

This is the base object for before/after comparison, improvement boards, and cohort boards.

### 2. Mutation event

Single applied action with durable consequence.

Smallest safe contents:

- `event_id`
- `source_root_id`
- `workflow`
- `recorded_at`
- `item_count`
- `bytes_delta` where meaningful
- `before_snapshot_id` optional
- `after_snapshot_id` optional
- per-item consequence summaries

Examples:

- Normalize apply
- weak-encode delete
- audio/default repair
- subtitle/default repair
- junk delete

This should be the common audit object, not five unrelated history shapes.

### 3. Mutation item

Stable child record inside a mutation event.

Examples:

- renamed path A -> B
- deleted file path
- repaired MKV defaults for path
- merged artifact folder into target folder

This matters because many board categories care about what kind of improvement occurred, not only that an event happened.

### 4. Policy snapshot

Recorded policy intent at a point in time.

Smallest safe contents:

- `policy_id`
- `captured_at`
- rule summaries
- storage constraint summary
- preferred ladders and floors by cohort

This connects the policy planner to future constraint-aware boards.

### 5. Forecast snapshot

Projected downstream library shape under a policy.

Smallest safe contents:

- `forecast_id`
- `policy_id`
- `captured_at`
- projected total size
- projected delta bytes
- projected quality-tier distribution
- projected cohort uplift breakdown
- fit / overflow against storage cap

This unlocks "best outcome under constraints" boards later without needing the external layer to compute policy math itself.

### 6. Export bundle

Reviewed user-approved package for external upload.

Smallest safe contents:

- pseudonymous identity
- one or more library snapshots
- selected mutation events
- selected policy/forecast objects
- explicit disclosure level

The export bundle is the privacy boundary.

## Minimum audit schema direction

Across workflows, the backend should converge on one audit/event vocabulary.

Useful common fields:

- `event_type`
- `workflow`
- `source_root_id`
- `recorded_at`
- `status`
- `selection_basis`
- `confidence`
- `review_only_count`
- `applied_count`
- `skipped_count`
- `error_count`

Useful common item fields:

- `item_id`
- `title`
- `year`
- `path_before`
- `path_after`
- `profile_before`
- `profile_after`
- `reason_codes`
- `bytes_before`
- `bytes_after`

Not every workflow will populate every field. That is acceptable.

The important part is shared shape and shared meaning.

## Board families and required artefacts

Below is the practical mapping from prestige ideas to required local artefacts.

### Coverage boards

Examples:

- highest Top 100 coverage
- strongest animation canon coverage
- strongest noir or action canon coverage

Required artefacts:

- library snapshots
- canonical cohort tagging inside snapshots

### Quality-floor boards

Examples:

- strongest collector-grade floor
- lowest weak-encode burden
- highest share above declared floor

Required artefacts:

- library snapshots
- quality-tier distribution
- policy snapshot if board is policy-relative rather than absolute

### Uplift boards

Examples:

- biggest quality-floor rise from first snapshot
- largest drop in junk burden
- strongest increase in canonical coverage
- biggest storage reclaimed then reinvested into quality

Required artefacts:

- at least two library snapshots
- mutation events between them

### One-shot boards

Examples:

- biggest safe Normalize apply
- cleanest one-pass uplift
- strongest single-event cleanup
- largest high-confidence artifact consolidation

Required artefacts:

- mutation events
- mutation items
- optional before/after snapshots

These are especially native to `normal` and should remain a distinct prestige family.

### Discipline boards

Examples:

- longest streak without review-only leftovers in chosen workflow
- best subtitle/default hygiene
- best audio-default hygiene
- lowest persistent junk recurrence
- strongest normalized naming adherence

Required artefacts:

- repeated mutation events over time
- workflow-specific issue counts inside snapshots

### Constraint boards

Examples:

- best canonical result under 4 TB
- strongest uplift within small-library division
- best projected policy fit under storage cap
- most efficient quality gain per added TB

Required artefacts:

- library snapshots
- policy snapshots
- forecast snapshots

### Taste and curation boards

Examples:

- strongest classic-film shelf
- strongest animation shelf
- strongest decade curation
- strongest "small but sharp" catalog

Required artefacts:

- snapshots with cohort and canonical membership breakdowns
- title-count or storage-based weight divisions

These must be carefully framed so they reward curation rather than merely owning more files.

### Ritual boards

Examples:

- `Employee of the Month`
- `One-Shot Sally`
- `Floor Keeper`
- `The Merciless Janitor`

Required artefacts:

- recurring event summaries
- period windows
- explicit ceremony logic

These are tone objects more than analytical ones, but they still need trustworthy underlying event data.

## Candidate derived metrics

These are likely useful downstream summary fields to compute from the artefacts above.

- canonical coverage percentage by list
- storage per covered canonical title
- share of library at or above floor
- share of library in review-only or ambiguous state
- junk burden by count and bytes
- mutation confidence ratio
- one-shot event size by item count and bytes affected
- quality uplift score between snapshots
- discipline streak count by workflow
- storage efficiency score

These should be treated as derived metrics, not primary stored truth, where practical.

## Weight divisions

Weight divisions should be first-class in the downstream model.

Otherwise giant libraries will flatten the entire prestige layer.

Small safe default divisions:

- title-count bands
- total-storage bands
- optional age-of-library bands once snapshots exist over time

This is a product rule, not merely a display preference.

## Privacy boundary

The export boundary should support prestige without requiring full title disclosure.

Small safe default:

- aggregate-first export
- pseudonymous identity
- explicit opt-in for raw title lists
- reviewed export bundle rather than silent sync

This implies the local artefact model should separate:

- full local truth
- export-safe summary

from the start.

## Local storage envelope

The backend should have an explicit expectation for how much local artefact data a typical library may accumulate.

This does not require a pruning policy yet.

It does require a rough target so the storage model stays disciplined.

### Small safe assumptions

Use a typical steady user shape for first-pass sizing:

- library size: `1000` movies
- mutation activity: `2` meaningful mutation sessions per week
- snapshot cadence: one baseline snapshot plus snapshots around meaningful applied events
- retention posture: keep durable local history unless a later policy says otherwise

These are not product promises.

They are sizing assumptions.

### Rough object sizes

Small safe default estimates for compact JSON-like local records:

- library snapshot summary: `8 KB` to `25 KB`
- mutation event summary: `2 KB` to `6 KB`
- mutation item: `0.25 KB` to `1 KB`
- policy snapshot: `2 KB` to `8 KB`
- forecast snapshot: `4 KB` to `12 KB`

The upper bound mostly comes from:

- repeated path strings
- per-cohort counters
- human-readable reason labels
- duplicated before/after fields

That means path normalization, shared codes, and avoiding repeated verbose labels will matter if event history grows.

### Typical annual footprint

Under the assumptions above, a normal active library should stay small.

Example envelope:

- `150` library snapshots at `15 KB` average: about `2.25 MB`
- `100` mutation events at `4 KB` average: about `0.4 MB`
- `4000` mutation items at `0.5 KB` average: about `2 MB`
- `24` policy snapshots at `4 KB` average: about `0.1 MB`
- `24` forecast snapshots at `8 KB` average: about `0.2 MB`

Total:

- roughly `5 MB` per active library per year

Even if reality lands at `2x` to `4x` this estimate, the local artefact layer is still modest.

### Large but still reasonable envelope

For a heavier user:

- `3000` movies
- frequent iterative normalization and cleanup
- `300` snapshots
- `250` mutation events
- `15000` mutation items

The artefact layer likely lands around:

- `15 MB` to `40 MB` per library-year

That is still acceptable for local-first product state.

### Design target

Small safe default target:

- aim for typical active-library artefact storage to remain under `10 MB` per year
- aim for heavy usage to remain comfortably under `50 MB` per year

If the model starts trending beyond that without clear user value, it is a signal that:

- records are too verbose
- snapshots are too frequent
- item payloads are carrying duplicated derived detail that should be recomputed

### Practical implications

To stay inside that envelope:

- store summary snapshots, not full table dumps, by default
- record reason codes and counters, not repeated prose blobs
- keep event items concise and schema-shaped
- separate durable local artefacts from browser convenience caches
- treat export bundles as generated derivatives, not the canonical local store

### Upstream implication

This sizing stance affects backend schema choices now.

If Normalize, junk deletion, subtitle repair, and future policy forecast all emit different verbose history shapes, the storage cost stays manageable but the model becomes harder to reason about and harder to export cleanly.

So the storage target reinforces the same architectural move:

- one coherent audit model
- one coherent snapshot model
- lean summary objects by default
- richer derived views computed at read time where practical

## Sequencing recommendation

If this becomes the first priority, the order should be:

1. define shared audit event schema and snapshot schema
2. make junk deletion durable in the same model
3. record Normalize apply outcomes into the same model
4. map workbench Secondary Surface and audit ledger to those objects
5. only then design export bundles and external prestige surfaces

This sequence protects both backend and UI work from rework drift.

## What not to do yet

- do not build a social surface in core `normal`
- do not bolt leaderboard language into the current UI
- do not treat browser-local history fragments as real audit
- do not optimize for giant-library dominance
- do not rely on ad hoc per-workflow JSON forever

## Immediate implication for the Normalize issue

The current Preview/Selector bug may still warrant tactical containment if it blocks normal use.

But it should not define the next major slice by itself.

The larger safe slice is:

- formalize downstream artefacts
- unify audit posture
- let the forthcoming UI rework bind to those durable objects

That is the slice least likely to get sandblasted away.
