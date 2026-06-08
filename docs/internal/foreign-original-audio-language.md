# Foreign-Original Audio: Suppressing the Wrong-Default Finding

_Deferred design note. Captures the reasoning, the candidate implementations, and
why each one carries a rough edge — so the trade-off is chosen deliberately rather
than rediscovered. normal does **not** currently have this; this note is the map._

## The bug, concretely

Seven Samurai (1954): main audio is **Japanese** (correct), plus two packaged
**English commentary** tracks. The scanner flagged "Wrong Default Audio Language"
and proposed promoting the English commentary to default.

The chain:

1. **Detection** — `detect_audio_language_selection_risks` (`movie_profile.py:1596`):
   default audio is non-English → an English track exists → emit
   `default_non_english_audio`. Nothing consults the track *title*; a commentary
   track is just "English audio."
2. **Surfacing** — the code maps to "Wrong Default Audio Language" in
   `normalize_lab.js:981`, action "Make Best English Audio Default."
3. **Fix** — `choose_best_english_audio_stream` (`movie_audio_fix.py:163`) picks the
   highest-quality English stream (the commentary) and sets it default.

Two independent gaps:

- **No original-language awareness.** The detector encodes "non-English default + any
  English track ⇒ packaging mistake." That premise is simply false for a
  foreign-language film, whose non-English default is correct.
- **No commentary classification.** "Best English audio" can resolve to a commentary
  track in both detection and fix. The `title` field is captured
  (`movie_scan.py:402`) but only used for immersive-codec and `\bforced\b` subtitle
  detection — never for commentary.

This note is primarily about the first gap (the foreign-film false positive). The
second is tracked under "Scope" below.

## Why this wasn't done originally

At build time the answer to "what is the film's original language?" was a flat *no* —
no cheap local source. That justified the crude language-only heuristic.

That premise has shifted:

- **OMDB** detail payloads (the `i=imdbID` call already made at `movie_omdb.py:116`)
  carry `Language` and `Country`. `result_from_omdb_payload` (`movie_omdb.py:146`)
  currently **discards** them — it keeps only rating/title/year/imdbID. For Seven
  Samurai the payload says `"Language": "Japanese"`. The data already flows through
  the pipeline and is thrown away.
- **IMDB bulk dataset** — still no. We fetch only `title.basics` + `title.ratings`
  (`movie_canonical_lists.py:41`); basics has no language column (`originalTitle` is
  unpacked then discarded at `movie_canonical_lists.py:749`). Language lives in
  `title.akas.tsv.gz` (not downloaded, large, per-aka, mostly empty). The only free
  crumb is `originalTitle != primaryTitle` — a weak, unnamed "maybe foreign" hint.
- **NFO** — mostly no. Parsed today only for title/year (`movie_plan.py:331`). Kodi's
  movie schema has no reliable original-language element; `<streamdetails>` just
  mirrors the container, and `<country>` is a weak proxy that isn't always written.
- **TMDB** — plumbed through the profile routes (`ctx.tmdb_key`) and carries a clean
  single-ISO `original_language`, but current use is canonical-list/top-500 discovery
  only (`TMDbCanonicalProvider`), not per-title lookup.

**Conclusion:** OMDB `Language` is the cheap, correct source. Step zero, independent
of everything below: capture `Language`/`Country` in `OmdbRatingResult` and its cache.

## The plumbing problem

The two pipelines are deliberately disjoint:

| | Scan / profile | OMDB |
|---|---|---|
| Trigger | scan time, server-side | client / on-demand, batched |
| Source | `MediaFacts` (ffprobe) | network |
| Cache key | `path \| st_mtime_ns \| st_size` (`probe_cache.py:48`) | `sha1(key+title+year)` (`movie_omdb.py:262`) |
| Invalidation | on file change | none — permanent |

The audio finding is born at scan time from `MediaFacts`, with **no OMDB in scope**.
OMDB arrives later, client-side, joined to rows in the browser.

Two facts make this sharper than it first looks:

- **The OMDB cache is cold in practice.** The `/api/movies/omdb/ratings` endpoint
  exists and is tested, but **no current frontend calls it** (`grep` for `omdb` /
  `/ratings` across `web_assets` is empty). So a naïve "best-effort cache-only read at
  profile time" would near-always miss. *Something must actively resolve language* for
  any server-side seam to deliver.
- **The OMDB cache is keyed by `title+year`, not file.** Original language never
  changes, so once warm an entry is permanent and survives remuxes/renames (which
  invalidate the *probe* cache and re-run the diagnostic). Steady-state reads are free;
  only a brand-new title pays network.

## The seam: where the fix lives changes everything

Ordered earliest → latest in the pipeline.

- **A — probe time (bake into `MediaFacts`/`ProbeCache`).** Rejected. Pollutes a
  content-addressed file cache with title-level network metadata whose invalidation key
  doesn't match, and forces OMDB into every scan.
- **B — diagnostic build (`detect_audio_language_selection_risks`).** Semantically
  cleanest: the bad finding is never emitted. Cost: pulls original-language resolution
  into the scan path. **This is the chosen seam** (see the sensitive gate, below, which
  is what makes it affordable).
- **C — post-profile server-side join.** Diagnostics computed locally at scan, a second
  pass suppresses/annotates when language is known. Decouples scan cost but creates a
  server-side join that doesn't exist today, and re-implements the suppression outside
  the detector that owns the rule.
- **D — client render (`normalize_lab.js`).** Rides the join that already exists (OMDB
  is merged into rows in the browser). Cheapest, zero scan-economics impact — **but
  fixes display only.**

### The pivot that rules out D

`default_non_english_audio` is **not display-only**. `is_audio_packaging_owned_movie`
(`movie_profile.py:1641`) keys on it, and at `movie_profile.py:325` that *gates
replacement candidacy*:

```python
weak_candidate = is_replacement_candidate_quality(...) and not is_audio_packaging_owned_movie(diagnostics)
```

`movie_replacement_queue.py:21-22,407` also branch on the code. A client-only seam
leaves Seven Samurai still tagged "audio-packaging-owned" and wrongly excluded from
replacement logic — precisely the foreign-film population we're trying to protect. The
correction must live server-side (B), where the diagnostic itself is fixed.

## The sensitive gate (the idea that makes B affordable)

The objection to B is "network in the hot scan path / rate-limit risk on a cold scan."
But the API only needs to be consulted for movies the detector would *otherwise flag* —
and that predicate is already the detector's own early-return:

> default audio is **non-English** AND at least one **English** audio track is present.

For a typical predominantly-English library this is a tiny minority of titles. So:

- gate the OMDB call behind that condition — 99% of the library never touches the API;
- the rate-limit exposure shrinks from "whole library on cold scan" to "the handful of
  foreign-default-with-English-track files";
- combined with the permanent `title+year` cache, even those are paid **once, ever**.

This turns "network in the hot path" from a library-wide cost into a rare conditional,
which is the difference between a real economics problem and a non-issue.

Residual rough edges to accept or design around:

- **Cold-title latency.** The first scan that hits a gated title blocks on one OMDB
  call (or chooses best-effort: emit as today, correct next pass — a one-time flicker).
- **No key / offline / OMDB miss.** Must fail *open* to current behaviour (emit the
  finding) — never fail closed and silently hide a real wrong-default.
- **OMDB `Language` is comma-joined** (`"Japanese, English"`), order usually but not
  guaranteed primary-first. Predicate must be defined precisely (see below).

## Open decisions (each a genuine fork)

### 1. Population strategy

- **Eager + sensitive gate (recommended).** Resolve during profile build, but only for
  gated titles. Cold gated title pays one call; everything else free. Network enters the
  hot path only on the rare relevant minority.
- **Background warm pass.** Scan stays fully local; a background task resolves languages
  and re-profiles. Correctness is eventual, with a flicker; more moving parts.
- **Lazy at workflow open.** Cheapest, but leaves server-side replacement gating wrong —
  rejected for the same reason as seam D.

### 2. Finding semantics when original language is non-English

- **Reframe to a distinct code** (e.g. `foreign_original_audio_ok`, informational). UI
  can show "foreign film, default correct"; replacement logic decides explicitly how to
  treat it. Keeps intent visible and auditable.
- **Suppress entirely.** Cleaner UI, but because `is_audio_packaging_owned_movie` keys
  on the *bad* code to *exclude* the film from weak-replacement candidacy, silent
  suppression flips a correctly-defaulted foreign film back into replacement eligibility.
  That may be desirable — but it's a decision, not a side effect to stumble into.

### 3. Scope

- **Detector only.** Fix the false positive; Seven Samurai stops being flagged. Leaves
  `choose_best_english_audio_stream` still able to pick a commentary track when the
  finding legitimately fires (e.g. a genuinely mis-flagged English film).
- **Detector + fix hardening.** Also make `choose_best_english_audio_stream`
  commentary-aware via track title, so the remux never promotes a commentary track —
  covers the general case (including English-original films with commentary tracks) but
  requires building the commentary classifier too.

### 4. The English-eligibility predicate

When does a film count as "English is an original language" (so the finding should
*stand*)? Define against OMDB `Language`:

- **Any English** in the list → treat as English-eligible (conservative: fewer
  suppressions, risks leaving a real foreign film flagged if OMDB lists an English dub).
- **Primary (first) language only** → stricter suppression; better for Seven Samurai but
  leans on OMDB's unguaranteed ordering.

Note this predicate cannot by itself distinguish a legitimate English *dub* from
commentary — that distinction needs Scope option "detector + fix hardening."

## Step zero, regardless of the above

Capture `Language`/`Country` in `OmdbRatingResult` + cache (`movie_omdb.py:146`,
`movie_omdb.py:285`). Pure additive, benefits every seam, and is the prerequisite for
all of it.
