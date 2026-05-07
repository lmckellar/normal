# normal

Local workbench for taming pirated music and movie libraries.

Two lanes:

- **Music** — normalize FLAC tags, filenames, and folder structure; repair artist artwork for Jellyfin
- **Movies** — normalize file and folder names; profile encode quality; compare owned titles against canonical movie lists; triage weak encodes, repair or replace multi-audio packaging mistakes, and clean up junk

No cloud. No transcoding. No destructive defaults.

<img width="1440" height="900" alt="movies_dashboard_default" src="https://github.com/user-attachments/assets/fb2abd09-7704-4748-acb7-f3dd4c1b7ade" />


## Get started

Paste this into Claude Code CLI, Codex CLI, Gemini CLI, or any agent that can run shell commands:

```
Clone https://github.com/lmckellar/normal, install it with pip install -e . (Python 3.12+), install ffprobe via your system package manager if not present, verify with `normal --help`, then start the web UI pointed at my library.
```

The agent will handle dependencies and get you to a running web UI.

**No agent?** See [docs/install.md](docs/install.md) for manual steps, then [docs/quickstart.md](docs/quickstart.md) for a full walkthrough.

## CLI quick reference

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

## Docs

- [Movies](docs/movies.md)
- [Music](docs/music.md)
- [Install](docs/install.md)
- [Quick start](docs/quickstart.md)
- [CLI reference](docs/commands.md)
- [Safety model](docs/safety.md)
- [Roadmap](docs/roadmap.md)

For contributors and AI agents working in the codebase: [docs/agent.md](docs/agent.md).

## Design posture

`normal` is a single-user local utility. Some preferences are intentionally hardcoded rather than surfaced as UI controls — the expected adjustment path is direct repo or agent edits. This is a deliberate v1 stance; see the roadmap for how this evolves toward v2.

Movie replacement queue history now supports four hard filters in the web UI: `Deleted, Awaiting Replacement`, `Replaced`, `Deleted From Queue`, and `All Items`. Items judged not worth replacing can be dismissed from queue history without deleting any media.

## Canonical lists

The movie `Canonical Lists` page compares owned titles against live all-time movie lists using TMDb and a local cache. It ignores bitrate, quality tiers, and warning telemetry. Pass `--tmdb-key` to `normal web` or set `TMDB_KEY` before launching the UI.

Heavy recursive web scans now warn before running against risky sources such as drive-root style paths and NTFS/FUSE mounts. The web server also rejects overlapping heavy scans for the same source instead of stacking them.

## Known issue

There is an open movie-scan / web UI issue around probe cancellation and observability. Under some currently unknown interaction pattern — likely involving scan cancellation, quick page changes, and rapidly starting another scan — an `ffprobe` process can keep running in the background after the UI thinks the scan is gone. In that state the leftover probe may also fail to appear in the Drive Activity indicator because the current `ps`-based visibility check does not catch every case.

The movie audio-packaging page now supports in-place MKV remux actions for `Make English Default` and `Make English Default + Delete Foreign Audio`. The stricter delete-foreign-audio variant is currently untested on real libraries and should still be treated as a review path before first public push.

## License

MIT — see [LICENSE](LICENSE).
