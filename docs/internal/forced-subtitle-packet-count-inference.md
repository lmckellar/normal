# Forced Subtitle Inference by Packet Count

_Deferred design note. Captured so the idea can be reconsidered deliberately, not rediscovered by accident. This describes a system normal does **not** currently have and may never need._

## Why this note exists

normal enforces a subtitle stance: **forced English subtitles default when they exist.** To act on that, the planner must be able to *find* the forced track. Today it relies on `SubtitleStreamFacts.is_forced`, which is now populated from two cheap signals:

1. the container **forced disposition bit** (`disposition.forced`), and
2. a **title regex** (`subtitle_title_looks_forced`) for tracks named "… Forced".

Those two cover the cases worth covering. This note is about the *third* case, which they cannot reach, and the expensive machinery that would.

## The three shapes of a forced track

| Case | forced flag | title says "forced" | How normal sees it today |
|---|---|---|---|
| A | set | any | **Detected** (disposition bit) |
| B | set | no / plain "English" | **Detected** (disposition bit — fixed when the probe began requesting `stream_disposition=default,forced`) |
| C | **not set** | no | **Invisible** — no header evidence at all |

Case C is the subject here. The motivating example was a Game of Thrones collection: two English PGS tracks, both `forced=0`, both untitled. The only thing separating them was the *amount of content*.

## The signal

A forced/foreign-only track carries only the lines spoken in another language (Valyrian, Dothraki). A full track carries the entire dialogue. The gap is enormous and unambiguous:

```
S04E10 — English PGS subtitle streams
  stream 2: 1386 cues   (full / SDH)
  stream 3:   30 cues   (forced, foreign-only)
```

`ffprobe -select_streams s -count_packets -show_entries stream=nb_read_packets` returns the per-stream cue count. The forced track is the English subtitle stream with a cue count that is a small fraction of its siblings and below an absolute ceiling.

## Why it is deferred, not built

This is the expensive cure to the edge case of an edge case:

- **Cost.** `-count_packets` requires a **full demux read of the file** — the same order of cost as a scan pass, per file. That directly antagonises normal's **scan economics** stance. It is categorically more expensive than every other probe normal does.
- **Rarity.** Across a 1000+ file library this pattern appeared **once**. The cheap signals (cases A and B) already nail everything else.
- **Principle.** Cheap signals first; pay for the expensive signal only when the cheap ones are exhausted *and* the payoff justifies it. Here the payoff is one collection.

So the bar for ever turning this on is: the case C population grows enough that the one-time demux cost is worth the libraries it rescues.

## How it would be designed

### Gate (cheap, evaluated from facts — no IO)

Only consider the demux when **all** hold:

- active subtitle policy on the relevant branch is `forced_english`;
- there are **≥ 2 English subtitle candidates**;
- **none** of them is already forced (cases A/B did not fire);
- the file supports repair (`.mkv`, `path_supports_repair`).

This gate is pure and lives exactly where the forced lookup already fails: in `choose_target_subtitle_stream` (`movie_repair_planner.py`), both `forced_english` branches, at the point `choose_best_english_subtitle_stream(..., forced_only=True)` returns `None`.

### Evidence (expensive, IO — injected, not imported)

A new helper in `movie_scan.py`, e.g. `count_subtitle_cue_counts(path) -> dict[int, int]`, runs one `-count_packets` pass and maps subtitle stream index → cue count. The planner must **not** import this directly — keep the planner pure over facts and inject the counter as a callable (mirrors how the web layer already injects `tracked_probe`). Tests pass a stub; production passes the cached, activity-tracked real thing.

### Inference (pure, unit-testable)

`infer_forced_english_subtitle(streams, cue_counts) -> SubtitleStreamFacts | None`:

- among English candidates with counts, take the smallest;
- accept it as forced only if it is **both** below a ratio of the largest English count (e.g. ≤ 0.25×) **and** below an absolute ceiling (e.g. ≤ ~300 cues);
- otherwise return `None` (two genuine full tracks — SDH + dialogue — must not be misread as forced; a short film's small full track must not trip the ceiling).

Both guards are required. Tunable constants; the GoT gap (30 vs 1386 → 0.02×) sits far inside any sane threshold.

### Threading the result

When inference succeeds the target stream is forced *in intent* but `is_forced == False` at the container level. Two honest options:

- carry an explicit `forced_inferred: bool` (and `forced_cue_count: int`) on the subtitle plan, and teach `subtitle_repair_issue_code` / `subtitle_issue_is_repairable` to treat an inferred-forced target like a real forced one; or
- normalise earlier by setting a derived `is_forced_effective` on the candidate before the existing planner logic runs.

The first is more explicit and lets the UI preview say something true: _"default → forced English (foreign-only, 30 cues)."_ The second touches less planner code but hides the provenance.

### Repair-time correction (companion decision)

If we are confident enough to default an inferred-forced track, we should consider **stamping the forced disposition bit** during the remux (`-disposition:s:<n> forced`), so the file is corrected at the source and downstream players (Plex, Jellyfin) finally read it as forced too — in keeping with normal's "improve the file before pondering client quirks" stance. This converts a case C file permanently into a case A file.

### Caching and observability (mandatory, not optional)

- **Cache the cue counts** keyed by `path|mtime|size`, same shape as `ProbeCache._key`. Either a sibling cache file or a new optional `MediaFacts` field with a `ProbeCache` version bump. Without this the demux re-runs on every repair-payload build and every rescan — unacceptable.
- **Wrap the demux in the activity tracker.** Repair-plan serialisation (`serializers.py: attach_repair_plans_to_payload_movies`) currently runs *outside* the `ACTIVITY_TRACKER` context (see the note in `agent.md` about serialisation terminating the indicator). A multi-second demux there would make the UI look hung. The counter must register its own tracked activity ("counting subtitle cues") so the indicator behaves.

## Risks and open questions

- **False positives** are the real danger: defaulting a partial/commentary/SDH-fragment track that merely happens to be short. The ratio+ceiling pair is the guard; it should fail closed (leave non-repairable) when ambiguous.
- **Non-mkv / non-PGS** containers and text vs image subs may count differently; scope to the same `SUPPORTED_REPAIR_EXTENSIONS` the rest of repair uses.
- **Where the cost lands.** Repair-plan build happens at serialisation, per movie in the payload — so a library-wide repair scan could trigger many demuxes at once even with the gate. Consider counting **lazily on selection/preview** rather than during the bulk payload build, so the cost follows user intent.
- **Is the gate ever worth it?** Revisit only if case C stops being a curiosity. Until then this stays a note.

## Anchors (if implemented)

- Gate / target selection: `normal/movie_repair_planner.py` — `choose_target_subtitle_stream`, `build_subtitle_repair_plan`, `subtitle_repair_issue_code`, `subtitle_issue_is_repairable`.
- Forced lookup it backstops: `normal/movie_profile.py` — `choose_best_english_subtitle_stream(forced_only=True)`.
- Evidence probe + cache: `normal/movie_scan.py`, `normal/probe_cache.py`.
- Injection / activity / serialisation seam: `normal/web/serializers.py`, `normal/web/activity.py`.
- Repair remux (forced stamping): `normal/movie_subtitle_fix.py`.
