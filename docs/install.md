# Install

## Requirements

- **Python 3.12 or later**
- **ffprobe** — required for all movie lane commands that probe media files (`movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `movie-register`, `web`)

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

## Verify

```bash
normal --help
```

Expected output: top-level command list including `scan`, `plan`, `apply`, `movie-scan`, `web`, etc.

```bash
ffprobe -version
```

Both must succeed before running any movie lane command.

## Platform notes

`normal` is developed and tested on Linux. macOS and Windows are not explicitly supported for v1 — rough edges are expected, particularly around:

- file path handling on Windows
- `ffprobe` PATH resolution
- `~/.local/share/normal/` replacement queue storage location
