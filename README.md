# normal

*Authorship: Human authored.*

Restoring order to your chaotic movie library

`normal` is a throroughly weird and opinionated open source local workbench that fixes a cross section of common issues with messy movie libraries. It seeks to restore calm where there was dissaray and can be useful for organizing, maintaining, improving or expanding your digital film collection.

Documentation authorship policy: [docs/writing.md](docs/writing.md).

## What It Does

- Normalises movie files and parent folders into `Title (Year)/Title (Year)` naming convention
- Inspects the library and arranges it into a cross section of user editable quality profiles and shortlists what doesn't make the cut
- Deletes the shortlisted weak movie encodes (looking at you, YIFY) from disk and then saves them in a text based replacement queue, freeing space immediately while recording what needs replacing
- Deletes Samples, Featurettes, Extras, Foreign Audio, promotional `.txt` spam and other junk ephemera
- Enforces logical subtitle and audio defaults across the board with `ffmpeg` remuxing
- Lets you compare your collection directly against canonical movie lists (TMDB Top 100, 250, etc.) and identify what's missing
- One Click Export your entire library as a cleanly organized spreadsheet

All packaged with a focused local Web workbench, minimal dependencies and all core features are local only. 

The fuller stance on why these choices are adopted is in [docs/statement.md](docs/statement.md).

## The Opinionated Part

`normal` is built around the following principles that lead to some loud claims:

**Physical Storage Economics**

The bigger a file gets, the stronger the case it has to make for existing.

Conversely, beneath a certain perceptual threshold even small files are objectively not worth existing. 

**Physical Scan Economics** 

Reading and writing to a physical hard drive repeatedly is not free. `normal` tries to know what it wants the library to look like at the outset and take the minimum number of actions required to reach that goal.

**Universal Naming Convention**

While preference on the specifics of naming and organisation may vary occasionally in response to obscure user preference, the expectations of downstream clients such as Plex and Jellyfin are explicit and should be targeted with a Universal Naming Convention that translates as freely between media API databases like IMDB/TMBD as it does into other clients like Emby, etc. 

**The Holy Trinity Of Snobby Claims**

1. A library of 1,000 orderly, relevant, well-encoded films beats a library of 5,000 weak, mediocre and chaotic ones. 

2. A maintenance process of 1,000 concise, respectful drive read/write events is preferable to one of 5,000 less consise ones if it acheives the same downstream shape.

3. Title (Year)/Title (Year).mkv is The Way.

## Before You Point It at Your Real Library

`normal` has become confident and efficient enough in flagging to take an aggressive by default stance. It renames, moves, deletes files and folders, uses recursive probe walks to gather metadata where unable to derive useful information via cheaper heuristic methods, calls remuxing workloads via `ffmpeg`, and will seek to move "from A to B" as fast as you let it. It does this by combining workflows while still providing visibility into what is being modified and what its output shape will be, but the net effect is that the tool can feel a little "in a hurry to clean your room" compared to more traditional and stage based implementations of this concept. This accumulates to big savings in terms of drive read/write and time spent tending to the process of maintenance yet does require the user to excercise adequate dilligence. 

While safety has been given primary consideration throughout development, any downstream user must exercise their own judgement on this matter.

Before it touches anything you care about, copy + paste a small test directory with a representative cross-section of your actual naming and folder conventions, a Noah's Ark of your current mess, and run everything there first.

Nothing is deleted without two explicit approval actions from you. All planned changes are shown before they run. 

`Human/AI-authored`
Recommended testing process is in [docs/quickstart.md](docs/quickstart.md) and [docs/safety.md](docs/safety.md). 

Watching the tool purify a test library for the first time is a good experience. Watching it touch your real library before you're ready is not.

## Alpha.2 UI note

`v0.7.0-alpha.2` promotes the newer workbench at `http://127.0.0.1:8765/` to the default UI.

Some lanes and audit surfaces that were previously exposed in `alpha.1` remain present in backend or partial internal form but are intentionally not surfaced in this default alpha.2 UI while they undergo deeper revision. The main release touch points in this repo reflect current reality; broader docs may still describe older public surfaces for a while.

## Optional API Keys

  `normal` works without external API keys for its core local workflows: movie normalize, profile scans, junk detection, repair defaults, inspect, and exports all run against local files.

  Two web features related to pulling Ratings use optional third-party APIs:

  - `TMDB_KEY` enables `Movies / Canonical Lists`, which compares your library against TMDb-backed movie lists.
  - `OMDB_KEY` enables IMDb ratings in movie list views that still surface ratings.

  If you do not provide these keys:

  - the app still launches and the main movie workflows still work as you would expect
  - `Canonical Lists` cannot fetch TMDb coverage data so this 'non core' feature will simply not return a list
  - movie pages that can show IMDb ratings simply omit them when no key is present.

  API Keys can be obtained from the respective websites and are free with basic usage plans and can be passed either by environment variable or via `normal web --tmdb-key ... --omdb-key ...`.

  `normal` thoughtfully provides internal caching that minimises repeated API calls after the first scan. This keeps the optional provider-backed views within free-tier limits and avoids wasteful re-queries for values that are already known.

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
