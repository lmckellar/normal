# normal

Local workbench for taming pirated music and movie libraries.

Two lanes:

- **Music** — normalize FLAC tags, filenames, and folder structure; repair artist artwork for Jellyfin
- **Movies** — normalize file and folder names; profile encode quality; surface weak encodes and junk for cleanup

No cloud. No transcoding. No destructive defaults.

## Install

```bash
pip install .
```

Requires Python 3.12+ and `ffprobe` (for movie commands). See [docs/install.md](docs/install.md).

## Quick start

```bash
# Music: scan → plan → apply
normal scan --source /path/to/music --report scan.json
normal plan --source /path/to/music --plan plan.json
normal apply --source /path/to/music --plan plan.json --target /path/to/output

# Movies: scan for quality issues, normalize names
normal movie-scan --source /path/to/movies --report scan.json --progress
normal movie-plan --source /path/to/movies --plan plan.json
normal movie-apply --source /path/to/movies --plan plan.json --target /path/to/output

# Web UI
normal web --host 127.0.0.1 --port 8765 --source /path/to/library
```

See [docs/quickstart.md](docs/quickstart.md) for a full walkthrough of both lanes.

## Docs

- [Install](docs/install.md)
- [Quick start](docs/quickstart.md)
- [CLI reference](docs/commands.md)
- [Safety model](docs/safety.md)
- [Roadmap](docs/roadmap.md)

For contributors and AI agents working in the codebase: [docs/agent.md](docs/agent.md).

## Design posture

`normal` is a single-user local utility. Some preferences are intentionally hardcoded rather than surfaced as UI controls — the expected adjustment path is direct repo or agent edits. This is a deliberate v1 stance; see the roadmap for how this evolves toward v2.

## License

MIT — see [LICENSE](LICENSE).
