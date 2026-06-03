# Policy Editor Ownership and Rail Reflow Plan

## Summary

Ship the policy editor as the single write owner for library policy and related operator preferences.

The editor lives behind the left sliver and, when expanded, takes the primary `2/3` work area. The current inspection surface is temporarily demoted into the right `1/3` pane. The current downstream preview/action surface is suppressed while policy editing is active, because policy editing is upstream intent work rather than mutation commitment work. On collapse, the normal spread returns.

Persistence is split:

- repo-local policy for library-governing rules
- user-local preference state for operator behavior defaults

The current dashboard inline standards editors and the standalone weak/junk floor control stop being independent editors. They become read-only summaries or entry points into the new policy editor.

## Key Changes

### Policy domain and persistence

Add a first-class policy model with revisioned saves and explicit ownership boundaries.

Repo-local policy should absorb and formalize:

- quality profile definitions currently stored in `movie_standards.json`
- replacement candidate / weak floor logic
- junk floor definition so the current dedicated UI button/control can be removed
- primary language
- subtitle preferences
- other library-governing media policy fields that are already implicit in scan/repair logic

User-local preference state should own:

- delete posture default
- the four supported delete modes:
  - `recycle_all`
  - `hard_delete_all`
  - `hybrid_media_to_bin_junk_hard_delete`
  - `hybrid_junk_to_bin_media_hard_delete`

Use revision tokens on both stores. Do not allow parallel write paths after this lands.

### Backend contract

Refactor current standards handling into a policy service layer rather than adding another ad hoc settings object.

Public/backend-facing changes:

- replace the narrow standards payload with a broader policy payload in the profile/workbench bootstrap response
- add policy read/update endpoints with optimistic revision checks
- keep the existing movie classification code reading through one normalized policy object
- route weak-candidate and junk-floor evaluation through policy-owned helpers
- route delete execution through a policy-aware delete strategy resolver instead of direct `unlink()` calls in handlers

Small safe default:
- continue storing repo-local library policy in `movie_standards.json` for v1, but extend its schema into a broader policy object rather than introducing a second repo-local file
- add one new user-local JSON file for operator preferences and delete posture

### UI rail behavior

Implement policy expansion as a structural workbench mode, not a floating drawer.

Behavior:

- left sliver remains visible in collapsed form
- opening policy switches the frame into `policy_editing` mode
- policy editor occupies the main `2/3` area
- inspection/output table is compressed into the right `1/3` pane as a secondary, reduced-reading surface
- preview/action controls are hidden or disabled during policy editing
- audit sliver remains present on the far right
- if audit is expanded while policy is open, audit expansion wins and policy collapses first; avoid competing full-surface takeovers

UI ownership changes:

- dashboard inline standards editing controls become entry points into the policy editor
- the current junk/weak floor button is removed in its current form because policy owns that state
- page summaries can still show current policy values, but no page other than policy editor writes them

### Delete behavior integration

Introduce a delete execution abstraction that all delete-capable routes use.

Apply it to:

- movie deletion flows
- junk deletion flows
- safe sidecar cleanup that follows deletion

Policy-aware behavior should determine whether each deleted item is:

- sent to recycle/trash
- permanently deleted

This needs path-safe validation to remain unchanged. Sidecar/folder cleanup must follow the same posture rules where relevant, not bypass them with direct hard delete unless policy explicitly says so.

## Test Plan

Add focused `unittest` coverage for:

- policy load/merge defaults and revision hashing
- policy update conflict handling with stale revisions
- migration/normalization from current standards-only files into the broader policy shape
- split persistence boundaries: repo-local policy vs user-local operator prefs
- weak/replacement floor evaluation now reading from policy
- junk-floor evaluation now reading from policy
- delete strategy resolution for all four modes
- cleanup routes honoring recycle vs hard-delete decisions without allowing outside-root paths
- workbench payload serialization including policy data and revision tokens
- workbench UI tests updated for:
  - policy editor as sole write path
  - removed standalone junk/weak floor control
  - policy-expanded rail mode
  - preview/action suppression during policy editing
  - dashboard cards acting as policy entry points rather than inline editors

## Assumptions and defaults

- The policy editor is a global left-side workbench surface, not a dashboard-only page.
- The editor becomes the sole policy write owner in v1.
- Existing repo-local `movie_standards.json` is extended rather than replaced by a new repo-local file.
- A new user-local preferences file is introduced for operator defaults such as delete posture.
- `Primary Language` and `Subtitle Preferences` are treated as library policy, not per-operator taste.
- The two hybrid delete modes are explicit first-class options in v1 rather than hidden sub-flags.
- Forecast/planner depth stays out of this slice except where the rail/state model should remain compatible with a later forecast surface.
