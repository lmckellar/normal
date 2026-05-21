# Install

## Requirements

- **Python 3.12 or later**
- **ffprobe** — required for movie lane commands that probe media files (`movie-scan`, `movie-profile`, `movie-inspect`, `movie-register`, `web`)

### Installing ffprobe

ffprobe ships with ffmpeg:

| Platform | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install ffmpeg` |
| macOS | `brew install ffmpeg` |
| Windows | Download from ffmpeg.org and add to PATH |

Verify: `ffprobe -version`

## Install normal

Clone and install:

```bash
git clone <repo>
cd normal
pip install -e .
```

Or non-editable:

```bash
pip install .
```

A virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Local API keys should be stored in a durable shell env source such as `~/.bashrc`, `~/.zshrc`, or a separate local env file that is sourced before launch. Do not store project API keys in `.venv/bin/activate`; recreating the venv can wipe them.

Example:

```bash
export TMDB_KEY=your_tmdb_key
export OMDB_KEY=your_omdb_key
```

## Verify

```bash
normal --help
```

Expected output: top-level command list including `scan`, `plan`, `apply`, `movie-scan`, `web`, etc.

```bash
ffprobe -version
```

Both must succeed before running any movie lane command.

If you plan to use Movies / Canonical Lists, also verify:

```bash
printf '%s\n' "${TMDB_KEY:+TMDB_KEY loaded}"
```

## Platform notes

`normal` is developed and tested on Linux. macOS and Windows are not explicitly supported before 1.0 — rough edges are expected, particularly around:

- file path handling on Windows
- `ffprobe` PATH resolution
- `~/.local/share/normal/` replacement queue storage location
