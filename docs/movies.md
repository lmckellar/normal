# Movies

The movie workflow *is* the product. It is not a generic media organizer — it is a deliberate local system for forcing a pirate movie library toward a cleaner downstream shape with as little ambiguity, scan waste, and junk tolerance as possible.

## Dashboard

A library-wide view of encode quality, resolution mix, standards posture, and replacement pressure. This is the first stop when you want to understand what kind of library you actually have rather than what you imagine you have.

**Resolution** here is display-class oriented, not just stored raster size. Cropped widescreen encodes such as `1920x796` still count as `1080p`, and anamorphic HD encodes such as `1440x1080` can count as `1080p` when the stream carries usable aspect metadata. If that metadata is missing or malformed, the bucket falls back to the stored raster dimensions.

To export a formatted XLSX catalogue, use the **Export** button on the Movies library card in the Library Switcher.

## Compare Against Canonical Lists

**Compare Against Canonical Lists** measures owned titles against IMDb-derived all-time lists using a local dataset plus a local cache. The lists are consensus-weighted locally rather than sorted by raw average alone, so broadly validated films outrank niche high-average outliers. It is title-coverage focused — bitrate, quality tiers, and warning telemetry don't affect the result.

Set `IMDB_DATASET_DIR` to a directory containing `title.basics.tsv.gz` and `title.ratings.tsv.gz` before launch. TMDb stays available as an explicit secondary provider when `TMDB_KEY` is set. The coverage badges are intentionally simple and good enough for first-pass tracking; badge refinement is deferred. For the broader local-first versus outbound-API posture, see [Safety](safety.md#networking-behaviour).

![Compare Against Canonical Lists](assets/canonical_lists.png)

## Normalize names

Uploader naming is usually sloppy. `normal` parses each path locally — no remote metadata — and proposes a clean target:

```
Title (Year)/Title (Year).mkv
```

The production normalizer is concise-first and treated as the intended movie shape. **All Results** includes already-normalized items as no-change rows, so the preview shows the full downstream structure, not just the diffs. The main workbench renders the projected library shape inline as a compact directory tree, stages preview through row selection, and confirms the same apply action it previewed — useful both for checking whether a proposal is merely parsable and whether the selected downstream shape is coherent before applying.

Deep links: `/?workflow=normalize`, `/?workflow=weak-encodes`, `/?workflow=repair-defaults`, `/?workflow=junk`, `/?workflow=immersive-audio`.

Verbose naming still exists temporarily in the CLI as parser-hardening scaffolding, but it is not the public end state:

```
Title (Year) [technical tokens]/Title (Year) [technical tokens].mkv
```

Ambiguous parses and unsafe target collisions are flagged `review`; everything else is `safe`. You review the plan before anything moves. That boundary now also covers **composed** target collisions: if a file rename plus folder rename would land on the same final path as another proposal, the planner downgrades it to `review` rather than letting two `safe` actions converge silently on one file.

Concise duplicate handling is subtractive but not lossy. When two local copies would otherwise collide and the scan can distinguish them from parsed path or folder tokens, it adds the shortest useful suffix to both folder and file stem — `Title (Year) 1080p` and `Title (Year) 2160p`. With no local differentiator, the collision stays in review rather than inventing `(2)` names. That same path covers stale post-split residue: if an older partial cleanup left a concise file inside a still-garbled multi-movie folder, normalize can strip repeated package-title tail junk and reuse a concise package token such as `1080p` for both folder and file.

Normalize also handles common library-chaos cleanup when the evidence is local and high-confidence:

- loose root movie files move into `Title (Year)/Title (Year).ext`, including cases where a sibling `.nfo` provides the title/year
- no-video movie-shaped artifact folders can be renamed, merged into an existing concise folder, deleted when they are duplicate metadata-only remnants, or flagged for review when merge safety is unclear
- metadata-only collection/series/trilogy artifact folders and root AppleDouble `._*` files can be deleted as safe cleanup proposals
- multi-part movie folders such as CD1/CD2 normalize to one folder with part labels preserved in filenames
- multi-movie package folders can split into individual movie folders when each video file, or a same-stem NFO, locally parses to its own title/year; package marker words such as `trilogy` are not treated as titles

The parser stays local and heuristic. It prefers a clear ASCII title segment when a filename mixes non-Latin and English title text before the year, and it can split technical-token runs that appear before a trailing parenthesized year. Tail-token confidence is weighted by structured evidence rather than token length alone, so harmless edition prose no longer sinks otherwise well-supported renames while genuinely weak tail evidence still stays in review. Parser hardening is intentionally narrow:

- it reconstructs a small settled punctuation set when local evidence is already present: ordinals (`25th`), abbreviations/initialisms (`Mr.`, `Dr.`, `L.A.`), and the compact `K19` / spaced `K 19` family into `K-19: ...`
- already-normalized titles that only need one of those deterministic upgrades are treated as `safe`, not forced into review
- a small explicit canonical-title exception table covers settled edge cases that don't generalize from local rules alone — `K-Pax`, `TRON: Legacy`, `WALL-E`
- it keeps the punctuation-light stance elsewhere instead of broad apostrophe/colon recovery across arbitrary titles
- it strips stacked tracker or domain credit noise only at the path edges (`www...`, split-domain forms such as `Oxtorrent Com`, bracketed domain tags), never mid-title words

![Normalize Movie Library Naming](assets/normalize_movies.png)

## Quality triage

A full profile scan separates **Action Based** cards from **Quality Profile** cards.

Action cards:

| Card | Meaning |
|---|---|
| `deleted, awaiting replacement` | Deleted through the replacement queue, still waiting for a better copy |
| `replacement_candidate` | Quality profile at or below the configured replacement cutoff, eligible for delete/replace triage |
| `needs_review` | Inline review attention needed, often from subtitle/default/hygiene checks |

Quality profile cards:

| Profile | Meaning |
|---|---|
| `Standard Definition` | Catch-all fallback for weak HD, SD titles, and outliers that miss every stricter stance |
| `Compact Grade` | Benign compact encodes that clear a modest floor but not full library-grade posture |
| `Library Grade` | Good enough for casual viewing and broad library selection |
| `Collector Grade` | Solid compact encodes that hold up on difficult material |
| `Reference` | Mild to no visual compression with lossless-audio posture |

The standards definition lives inside the broader repo-local library policy in `movie_standards.json`. In the compact shell, policy writes are owned by the left-side **Policy** rail rather than scattered inline controls — quality profiles, Replacement Candidate, library defaults, and junk-floor behavior all share that one editor. The bottom `Standard Definition` card stays the fallback bucket below `Compact Grade`; only its label and summary are editable.

The video-floor presets are trimmed to plausible movie-library ranges rather than ultra-weak encodes. The 1080p dropdown starts at `4,500 kbps — compact encode` and steps through `5,500 library grade`, `7,500 strong library`, `10,000 collector grade`, `12,500 strong collector`, and `15,000 reference grade` before the higher near-lossless/remux tiers. The 4K dropdown starts at `10,000 kbps — compact encode`, then `15,000 library grade`, `20,000 strong library`, `25,000 reference grade`, followed by `30,000`, `40,000`, and `50,000`.

Dashboard scans stream progress without pre-counting the whole tree. The drive activity bar shows processed file count, elapsed time, current `ffprobe` target when visible, and ETA only when a bounded total is known — avoiding false precision on large rebuilds while still showing forward movement.

Persistence posture:

- `movie_standards.json` is the repo-local source of truth for library policy across restarts and localhost port changes
- `~/.local/share/normal/operator-preferences.json` stores user-local operator defaults such as delete posture
- browser cache is only a per-origin dashboard snapshot; `127.0.0.1:8765` and `127.0.0.1:8766` don't share localStorage
- policy and operator-preference saves use revision checks, so an older tab or stale view is rejected instead of silently overwriting newer state
- writes use an atomic temp-file replace, so an interrupted write never leaves a partial JSON file

The audio channel minimum has a companion **Exempt pre-surround era films** setting. Set a release-year cutoff (Pre-1970 through Pre-1990) and films released before it bypass the channel floor — useful when Library Grade or higher requires 5.1 but classic titles with mono or stereo-only audio have no higher-channel release to replace them with. Profiles also expose **Allow original mono before year**, narrower than the general vintage exemption: it preserves legitimate mono presentations on older films without weakening the surround expectation for later material, and when it applies the engine also relaxes the audio bitrate floor to a mono-aware threshold.

Quality results include a normalized main-audio summary for the playback-relevant stream alongside audio bitrate — `AAC 2.0`, `Dolby Digital 5.1`, `Dolby Digital Plus 5.1 Atmos`, `Dolby TrueHD 7.1 Atmos`, `DTS-HD MA 5.1`, and similar. In the workbench at `/?workflow=weak-encodes` the audio bitrate value is clickable, opening a compact track inspector that shows each audio stream's language, bitrate, channel layout, and which stream is default — primarily there to expose multi-audio packaging mistakes without bloating the table.

That shell routes weak-floor editing through the shared **Policy** rail. The default stays intentionally conservative — `Standard Definition`, not `Library Grade` — because the point of the delete workflow is to identify the weakest safe replacement candidates first, not to drag stronger titles into an aggressive destructive lane by default. Weak-encode ownership is also narrower than general review: if a file already has good English audio and the real defect is wrong default-language packaging, that belongs to **Fix Audio and Subtitle Defaults**, not **Review Low-Quality Encodes**.

**Review Low-Quality Encodes** lets you select weak files for deletion. Each deleted file enters a replacement queue, and when a better encode for the same title shows up in a future scan it is automatically marked complete. Queue history has four hard filters — `Deleted, Awaiting Replacement`, `Replaced`, `Deleted From Queue`, and `All Items`. Deleted rows can be dismissed from history inline when the release is no longer worth replacing; that only changes queue state and touches no media.

The queue-history table sorts by title, year, and IMDb rating. Ratings are fetched server-side from [OMDb](https://www.omdbapi.com/) and require a free key via `--omdb-key` or `OMDB_KEY`. Lookups use local title cleanup plus a small cache, so repeated loads don't keep spending the quota. Without a key the column is hidden; when OMDb is rate-limited, new cells show `limit` and cached ratings still display. This is one of the few optional outbound paths — see [Safety](safety.md#networking-behaviour).

![Review Low-Quality Encodes](assets/delete_weak_encodes.png)

## Fix Audio and Subtitle Defaults

**Fix Audio and Subtitle Defaults** stages audio-packaging and subtitle-readiness issues together in one compact shell, also reachable at `/?workflow=repair-defaults` when you want to jump straight into repair consequences.

### Audio Packaging

Some MKVs are muxed with the wrong main audio track — Italian marked default, a weaker English track left as fallback. The **Audio Packaging** tab uses the same shared profile scan as weak-encode triage, with different issue rules:

- detect non-English default audio when English is present
- flag the stronger case where the English fallback is materially weaker than the default track
- show the main-audio summary plus default-vs-English stream summaries so direct repair or deletion is explainable before action

For MKVs, the page can do an in-place lossless repair that flips the default audio flag to the best English track, plus a stricter variant that drops streams explicitly tagged non-English while keeping English and untagged audio. Unsupported containers stay review-only. While a remux runs, the page locks checkbox selection and disables conflicting bulk actions; the lane is intentionally non-destructive, so direct delete is not surfaced here.

Safety note: **Make Best English Audio Default** has been exercised against real files. **Make Best English Audio Default + Remove Foreign Audio** is implemented but currently untested on real libraries and should still be treated cautiously.

### Subtitle Readiness

The **Subtitle Readiness** tab is the sibling repair lane on the same scan, following the subtitle hygiene stance from the standards engine:

- default to no subtitle when main audio is already English
- default to forced English when a forced English subtitle exists
- default to English subtitles when the default audio track is non-English

Non-destructive: it deletes no media or subtitle files. For supported MKVs it does a lossless in-place remux that only updates embedded subtitle default flags. If the needed English or forced-English subtitle doesn't exist, the item stays review-only.

When you run a combined audio + subtitle repair, `normal` computes the final intended subtitle target before execution and performs **one** lossless remux per file — it no longer accepts a second subtitle pass after the audio remux for the same combined repair. Scope is embedded subtitle streams only; external `.srt` / `.ass` sidecars are not modified. Subtitle fixes return immediate results only: review-only items stay visible from current diagnostics and disappear after a fresh scan once the issue is gone. No durable subtitle history is recorded in this flow.

![Fix Audio and Subtitle Defaults](assets/repair_defaults.png)

## Immersive Audio

**Review Immersive Audio Candidates** (`/?workflow=immersive-audio`) tackles a fact no scanner can read off a library: whether a film is even *available* in an object-based immersive mix (Dolby Atmos / DTS:X). The upstream catalogues don't expose it, so the workflow crowdsources it.

Each row pairs what the local container actually probes — carrier codec and channel layout — with a seeded, expandable corpus of titles known to have, or to lack, an immersive release. That lets the workbench frame a row as a concrete upgrade candidate rather than a guess. A tri-state **Status** column (immersive available / not available / unknown) replaced the older manual per-title voting, and the verdict surface is split into **Status**, a separate **Audio** explainer, and a **Quality Profile** column.

Atmos/DTS:X crediting is gated on the actual carrier codec, so a lossy core can't masquerade as the object track. The workflow is non-destructive: it records distinctly-coloured Telemetry Vote events into the audit ledger and flags non-normalized rows with normalization tooltips. The "not available" corpus ships seeded with researched titles and can be extended and shared internally.

<placeholder awaiting screenshot>

## Junk cleanup

**Remove Junk Files** is one combined scan with two result panels:

- junk-marker videos such as samples, extras, and featurettes — detected from filenames, ancestor folders, and conservative size thresholds with a hard 4 GB suppression ceiling
- promo PDFs, NFOs, HTML, and other non-video sidecar spam

Both are preview-first. Nothing is deleted until you select rows and confirm. Junk deletion now writes durable events to the unified audit ledger alongside scans, weak-encode/audio deletes, repairs, exports, and policy updates, so it is no longer the session-only history gap it once was.

![Remove Junk Files](assets/delete_junk_spam.png)

## Catalogue export

Export a formatted XLSX of your full library — title, year, resolution, video codec, audio, container, file size — sorted alphabetically:

```bash
normal movie-register --report scan.json --xlsx catalogue.xlsx
```

The **Audio** column uses the same normalized main-audio summary as the scan and web UI.

## Web UI pages

| Page | What it does |
|---|---|
| Dashboard View | Quality overview, replacement pressure, histograms, standards editing |
| Normalize Movie Library Naming | Review and apply rename plans |
| Remove Junk Files | Remove junk videos and sidecar spam after preview and confirmation |
| Review Low-Quality Encodes | Triage low-floor encodes and queue replacements |
| Fix Audio and Subtitle Defaults | Fix default audio/subtitle behavior where supported, or keep review cases visible |
| Review Immersive Audio Candidates | Flag titles that have or lack an object-based immersive mix and vote into a shared availability dataset |
| Compare Against Canonical Lists | Compare owned titles against curated movie lists and unlock simple coverage badges |

Scan cancellation is cooperative rather than instantaneous: scans check between files, while a running `ffprobe` may still finish or hit its timeout before unwind completes.

Low-priority parsing edge case: some low-quality multi-movie pack names can leak genre-style tokens such as `Sci Fi` into the parsed title when they appear before the year. Treat those as local repair cases rather than broadening the parser heuristics.

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
