# normal

*Authorship: Agent-written.*

`normal` is a local movie-library workbench for people who want a smaller, cleaner, more deliberate pirate library. It is no longer a broad media-organizing sandbox. It now assumes a strong downstream shape, pushes toward it aggressively, and keeps destructive actions visible and gated.

- Normalize movies into clear `Title (Year)` naming
- Profile library quality against a hardcoded standards posture
- Delete weak encodes into a replacement queue
- Repair default audio and subtitle behavior
- Delete junk videos and sidecar spam
- Compare the library against canonical movie lists

![normal movie dashboard](docs/assets/readme_dashboard.png)

## What It Is Now

`normal` is opinionated on purpose.

- A good movie library should default to the clearest possible naming: `Title (Year)`
- Quality should live inside a defined library policy, not drift title by title
- Large files carry a burden of proof under physical storage economics
- Scans should minimize unnecessary drive reads and writes
- Junk media ephemera should not quietly accumulate forever

The fuller product stance lives in [docs/statement.md](docs/statement.md).

## Safety

`normal` is aggressive in workflow shape, not reckless in execution.

- Scans and plans are read-only
- CLI commands do not delete media
- Web deletions require checkbox selection and a confirmation action
- The server revalidates selected paths against the active source root before deleting
- `normal` will not silently rename or destroy files behind your back

Before touching a live library, use a representative local test library first. The recommended sanity checks are in [docs/quickstart.md](docs/quickstart.md) and [docs/safety.md](docs/safety.md).

## Get Started

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
ffprobe -version
normal --help
normal web --host 127.0.0.1 --port 8765 --source /path/to/Test\ Movies
```

Then open `http://127.0.0.1:8765`.

## Docs

- [Statement](docs/statement.md)
- [Install](docs/install.md)
- [Quick start](docs/quickstart.md)
- [Movies](docs/movies.md)
- [Safety](docs/safety.md)
- [CLI reference](docs/commands.md)
- [Documentation authorship](docs/writing.md)
- [Roadmap](docs/roadmap.md)

Historical note: `normal` did not start as a movie-only tool. Current public docs describe what it is now. Project-history docs still note the path it took to get here, including the now-legacy music lane.

For contributors and AI agents working in the codebase: [docs/agent.md](docs/agent.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [CHANGELOG.md](CHANGELOG.md).

## License

MIT — see [LICENSE](LICENSE).
