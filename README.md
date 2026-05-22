# normal

*Authorship: Human/AI-authored.*

Restoring order to your chaotic movie library

`normal` is an opinionated open source local workbench that fixes a cross section of common issues with messy movie libraries. It seeks to restore order where there was chaos and can be useful for organizing, maintaining, improving or expanding your collection.

Documentation authorship policy: [docs/writing.md](docs/writing.md).

![normal movie dashboard](docs/assets/readme_dashboard.png)

## What It Does

- Normalises movie files and parent folders into `Title (Year)/Title (Year)` naming convention
- Inspects the library and arranges it into a cross section of user editable quality profiles and surfaces what doesn't make the cut
- Deletes these weak movie encodes (looking at you, YIFY) from disk and then saves them in a text based replacement queue, freeing space immediately while recording what needs replacing
- Deletes Samples, Featurettes, Extras, Foreign Audio, promotional `.txt` spam and other junk ephemera
- Enforces logical subtitle and audio defaults across the board with `ffmpeg` remuxing
- Lets you compare your collection directly against canonical movie lists (TMDB Top 100, 250, etc.) and identify what's missing
- One Click Export your entire library as a cleanly organized spreadsheet

The fuller stance on why these choices are the right ones is in [docs/statement.md](docs/statement.md).

## The Opinionated Part

`normal` is built around two principles:

Physical storage economics. The bigger a file gets, the stronger the case it has to make for existing.

Scan economics. Reading and writing to a physical hard drive repeatedly is not free. `normal` tries to know what it wants the library to look like at the outset and take the minimum number of actions required to reach that goal.

The claim: A library of 1,000 orderly, relevant, well-encoded films beats a library of 5,000 weak, mediocre and chaotic ones.

## Before You Point It at Your Real Library

`normal` is aggressive by default. It renames, moves, deletes files and folders, uses recursive probe walks to gather metadata where needed, calls remuxing workloads via `ffmpeg`, and will seek to move "from A to B" as fast as you will let it.

While safety has not been an afterthought, any downstream user must exercise their own judgement on this matter.

Before it touches anything you care about, build a small test directory with a representative cross-section of your actual naming and folder conventions, a Noah's Ark of your current mess, and run everything there first.

Nothing is deleted without two explicit approval actions from you. All planned changes are shown before they run. But the recommended sanity-check process is in [docs/quickstart.md](docs/quickstart.md) and [docs/safety.md](docs/safety.md). Do it. Watching the tool purify a test library for the first time is a good experience. Watching it touch your real library before you're ready is not.

## Get Started

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
normal web --host 127.0.0.1 --port 8765 --source /path/to/Test\ Movies
```

Open <http://127.0.0.1:8765>.

## Docs

- [Statement](docs/statement.md)
- [Install](docs/install.md)
- [Quick start](docs/quickstart.md)
- [Movies](docs/movies.md)
- [Safety](docs/safety.md)
- [CLI reference](docs/commands.md)
- [Documentation authorship](docs/writing.md)
- [Roadmap](docs/roadmap.md)

For contributors and agents working in the codebase: [docs/agent.md](docs/agent.md), [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
