# normal

*Authorship: Human/AI-authored.*

Restoring order to your chaotic movie library

`normal` is an opinionated open source local workbench that fixes a cross section of common issues with messy movie libraries. It seeks to restore order where there was chaos and can be useful for organizing, maintaining, improving or expanding your digital film collection.

Documentation authorship policy: [docs/writing.md](docs/writing.md).

![normal movie dashboard](docs/assets/readme_dashboard.png)

## What It Does

- Normalises movie files and parent folders into `Title (Year)/Title (Year)` naming convention
- Inspects the library and arranges it into a cross section of user editable quality profiles and shortlists what doesn't make the cut
- Deletes the shortlisted weak movie encodes (looking at you, YIFY) from disk and then saves them in a text based replacement queue, freeing space immediately while recording what needs replacing
- Deletes Samples, Featurettes, Extras, Foreign Audio, promotional `.txt` spam and other junk ephemera
- Enforces logical subtitle and audio defaults across the board with `ffmpeg` remuxing
- Lets you compare your collection directly against canonical movie lists (TMDB Top 100, 250, etc.) and identify what's missing
- One Click Export your entire library as a cleanly organized spreadsheet

The fuller stance on why these choices are adopted is in [docs/statement.md](docs/statement.md).

## The Opinionated Part

`normal` is built around two principles:

**Physical Storage Economics**

The bigger a file gets, the stronger the case it has to make for existing.

**Physical Scan Economics** 

Reading and writing to a physical hard drive repeatedly is not free. `normal` tries to know what it wants the library to look like at the outset and take the minimum number of actions required to reach that goal.

The claims: 

1. A library of 1,000 orderly, relevant, well-encoded films beats a library of 5,000 weak, mediocre and chaotic ones. 

2. A maintenance process of 1,000 concise, respectful drive read/write events is preferable to one of 5,000 less consise ones if it acheives the same downstream shape.

## Before You Point It at Your Real Library
`User-written`

`normal` has become confident and efficient enough in flagging to take an aggressive by default stance. It renames, moves, deletes files and folders, uses recursive probe walks to gather metadata where unable to derive useful information via cheaper heuristic methods, calls remuxing workloads via `ffmpeg`, and will seek to move "from A to B" as fast as you let it. It does this by combining workflows while still providing visibility into what is being modified and what its output shape will be, but the net effect is that the tool can feel a little "in a hurry to clean your room" compared to more traditional and stage based implementations of this concept. This accumulates to big savings in terms of drive read/write and time spent tending to the process of maintenance yet does require the user to excercise adequate dilligence. 

While safety has been given primary consideration throughout development, any downstream user must exercise their own judgement on this matter.

Before it touches anything you care about, copy + paste a small test directory with a representative cross-section of your actual naming and folder conventions, a Noah's Ark of your current mess, and run everything there first.

Nothing is deleted without two explicit approval actions from you. All planned changes are shown before they run. 

`Human/AI-authored`
Recommended testing process is in [docs/quickstart.md](docs/quickstart.md) and [docs/safety.md](docs/safety.md). 

Watching the tool purify a test library for the first time is a good experience. Watching it touch your real library before you're ready is not.

## Optional API Keys
`Agent-written`

  `normal` works without external API keys for its core local workflows: movie normalize, profile scans, junk detection, repair defaults, inspect, and exports all run against local files.

  Two web features use optional third-party APIs:

  - `TMDB_KEY` enables `Movies / Canonical Lists`, which compares your library against TMDb-backed movie lists.
  - `OMDB_KEY` enables IMDb ratings in replacement-queue history for quick sorting of 'most acclaimed movies I have deleted and need to replace'

  If you do not provide these keys:

  - the app still launches and the main movie workflows still work
  - `Canonical Lists` cannot fetch TMDb coverage data without `TMDB_KEY`
  - replacement-history IMDb ratings stay unavailable without `OMDB_KEY` and renders a '-' in the otherwise fully functioning output table

  Keys are free with basic usage plans and can be passed either by environment variable or via `normal web --tmdb-key ... --omdb-key ...`.

  `normal` thoughtfully provides an internal local caching feature that minimises progressive API calls after initial scan. This allows users to stay comfortably within free usage plan rate limits for the API service providers even if managing a very large replacement queue and avoids needlessly hammering the provider endpoints with wasteful API requests. In the event the user gets rate limited (liekly on initial scan of huge library if many weak encodes get nuked, unlikely otherwise) they can simply wait 24 hours for the TMBD rate limit to refresh and perform another scan in normal - it will rebuild whatever was not initially scanned, update anything that has gone stale, while deliberately avoiding any wasteful re-queries against the API endpoint for known values from prior scans. 

  See [docs/safety.md](docs/safety.md#networking-behaviour) for the networking posture and [docs/movies.md](docs/movies.md) for where these features appear in the UI.


## Get Started
`Agent-written`

```bash
git clone https://github.com/lmckellar/normal.git
cd normal
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
normal web --host 127.0.0.1 --port 8765 --source /path/to/Test\ Movies
```

Then open `http://127.0.0.1:8765` in your browser.

## Support
`Agent-written`

`normal` currently supports Python 3.12 and newer.

Platform support is Linux-first. The project is developed and tested on Linux. macOS and Windows may work, but they are not explicitly supported before `1.0`.

`ffprobe` is required for media-probing workflows such as `movie-scan`, `movie-profile`, `movie-inspect`, `movie-register`, and `web`.

## Docs

- [Statement](docs/statement.md)
- [Install](docs/install.md)
- [Quick start](docs/quickstart.md)
- [Movies](docs/movies.md)
- [Safety](docs/safety.md)
- [CLI reference](docs/commands.md)
- [Documentation authorship](docs/writing.md)
- [Roadmap](docs/roadmap.md)

Architecture overview (`Agent-written` support doc): [docs/architecture.md](docs/architecture.md).

For contributors and agents working in the codebase: [docs/agent.md](docs/agent.md), [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
