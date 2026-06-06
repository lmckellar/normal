# Menu Action Bar Audio / Subtitle Chain Notes

Internal scoping note for the `Repair Defaults` action bar and its audio/subtitle sequencing semantics.

Update: this note described the earlier staged-two-remux implementation. Current code has been re-oriented so combined audio + subtitle repair computes the post-audio subtitle intent up front and executes a single mux per file. The scan-economics concern described here won that argument.

## Why this note exists

Recent policy-editor work made subtitle and language preferences more editable, which exposed a seam that was already present:

- the action bar presents broad combined actions
- the underlying audio and subtitle logic is policy-sensitive
- combined repair execution is chained
- subtitle targeting depends on default-audio state

That means the same selected file can have different subtitle intent depending on whether we evaluate:

- the file as currently scanned
- the file after an audio-default remux

This matters most in combined audio + subtitle actions.

## Current implementation shape

Relevant ownership is split across these files:

- `normal/web_assets/normalize_lab.js`
- `normal/movie_audio_fix.py`
- `normal/movie_subtitle_fix.py`
- `normal/movie_profile.py`
- `normal/web/routes_cleanup.py`

Current repair action bar options:

- `Make Best English Audio Default`
- `Normalize Subtitle Defaults`
- `Make Best English Audio Default + Normalize Subtitle Defaults`
- `Make Best English Audio Default + Remove Foreign Audio`
- `Make Best English Audio Default + Remove Foreign Audio + Normalize Subtitle Defaults`

The action bar is contextual to the selected rows, but the context is built from the current scanned file shape, not from a forward simulation of the chained result.

## What the code does today

### 1. Subtitle intent is keyed off current default audio

Both UI and backend subtitle targeting use the current default audio language as the branch point.

If default audio is non-English:

- `foreign_audio_subtitles = forced_english` prefers forced English if present, else full English
- `foreign_audio_subtitles = english` prefers full English
- `foreign_audio_subtitles = off` targets no default subtitle

If default audio is English:

- `english_audio_subtitles = forced_english` prefers forced English
- `english_audio_subtitles = english` or `primary_language` prefers full English
- `english_audio_subtitles = off` targets no default subtitle

This logic exists in both places:

- UI helper: `movieSubtitleReadinessRepairTarget()`
- backend fix planner: `choose_target_subtitle_ordinal()`

## 2. Combined execution is staged, not snapshot-based

Combined repair does not compute one frozen plan up front.

It runs in stages:

1. run audio repair first when the selected action includes audio
2. merge freshly probed updated items back into the repair payload
3. re-evaluate subtitle repairability from the updated file state
4. run subtitle repair second

So the subtitle step responds to the result of the audio step, not to the original scan alone.

This is the important current truth.

## 3. Preview and labeling are still mostly snapshot-based

The repair rows, issue summaries, repair targets, and preview tree are built from the file as currently scanned.

They do not simulate:

- the post-audio default track
- the post-audio subtitle policy branch
- new subtitle issues that may appear only after audio becomes English
- subtitle issues that may disappear after the audio step

So execution is staged, but preview is mostly pre-stage.

That is the core mismatch.

## Practical consequences

### Preview can under-describe or mis-describe the subtitle step

A combined action may show a subtitle target based on non-English default audio, while the actual subtitle remux later runs against an English-default file.

### A row can start as audio-only but still get a subtitle step later

This is possible because the second stage re-reads updated items by selected path after audio repair.

So a file that was initially only an audio issue can become subtitle-repairable mid-chain.

### A row can start as audio + subtitle, but the subtitle target can change

If the subtitle policy differs between non-English-audio and English-audio branches, the second-stage subtitle target can differ from what the initial row preview implied.

### Some subtitle cases are intentionally non-repairable

UI repairability currently refuses some missing-subtitle-default cases:

- `missing_default_english_subtitle`
- `english_audio_missing_default_english_subtitle`

So a combined chain will not fix every theoretically desirable subtitle state. It only fixes the subset the current UI/backend consider safely remuxable.

### The UI sends `issue_codes` to subtitle fix, but the backend does not use them

That suggests earlier intent toward a tighter plan contract, but today the server simply re-probes the file and decides again.

## Reading the hypothetical

Hypothetical file:

- default audio is non-English
- high-quality English audio exists
- English subtitle exists
- forced English subtitle exists

Hypothetical policy:

- primary language: English
- when default audio is non-English: prefer forced English subtitles
- when default audio is English: keep forced English subtitle where present

Under current logic, the file likely surfaces:

- audio issue: wrong default audio language
- subtitle issue: forced English exists but is not default

If the user runs the combined action:

1. audio step makes English audio default
2. subtitle step re-evaluates from the updated file
3. because the English-audio policy also prefers forced English, the subtitle target remains forced English

So in this exact hypothetical, pre-audio and post-audio subtitle intent happen to align.

But that alignment is contingent, not structural.

If English-audio policy were instead:

- `off`
- or `english`

then the post-audio subtitle target could diverge from the initial non-English-audio interpretation.

## What this means for the action bar

The current action labels are broader than the actual planned semantics.

`Normalize Subtitle Defaults` is not one operation. It is a policy-driven family of operations:

- clear subtitle defaults
- set forced English default
- set full English default

In a combined action, which one lands can depend on an earlier audio mutation in the same chain.

So the label is stable, but the concrete meaning is not stable unless we also define the evaluation model.

## Recommended direction

Small safe default:

- document and treat combined repair as a staged workflow whose later steps evaluate the file after earlier mutations

That matches current execution already.

Then choose one of these models explicitly:

### Option A: snapshot plan

Compute everything from the initial file shape and lock it before execution.

Pros:

- simpler mental model
- preview and execution can match exactly

Cons:

- can produce stale or wrong second-step intent after the first mutation lands

### Option B: staged plan

Treat each chain link as responding to the new file state created by the prior link.

Pros:

- matches media reality better
- more robust when policy branches depend on default-audio state

Cons:

- preview must simulate intermediate state or it will mislead

Current code is already much closer to Option B.

## Recommended next implementation posture

Before changing UI behavior, it would be cleaner to define one backend-owned repair planner that can answer:

- what issues apply now
- what actions would run in what order
- what the intermediate file state is expected to become
- what the final target state is expected to be

That would remove the current JS/Python duplication around subtitle targeting and reduce drift risk.

## Upstream considerations

- Policy editability increases the number of branch combinations, so action-bar ambiguity becomes more visible.
- Subtitle targeting logic currently exists in both JS and Python. That is a drift risk.
- The current combined action model is more powerful than the labels imply, because it can create second-order subtitle work after audio mutation.
- Any top-down rethink should decide whether the workbench is promising:
  - a single action label
  - a concrete staged plan
  - or an explicit final intended media shape

## Questions worth answering next

- Should combined repair preview simulate intermediate state?
- Should rows advertise possible second-order subtitle consequences before execution?
- Should `Normalize Subtitle Defaults` be split into explicit target labels in preview text?
- Should the backend own the full combined repair plan so the UI only renders it?
- Should some currently non-repairable subtitle cases become repairable once the chained final state is known?
