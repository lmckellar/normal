# Install

## Requirements

- **Python 3.12, 3.13, or 3.14**
- **ffprobe** — required by every command that probes media: `movie-scan`, `movie-profile`, `movie-inspect`, `movie-register`, and `web`

### Getting ffprobe

ffprobe ships with **ffmpeg**:

| Platform | Command |
|---|---|
| Debian / Ubuntu | `sudo apt install ffmpeg` |
| macOS | `brew install ffmpeg` |
| Windows | Download from ffmpeg.org and add it to `PATH` |

Confirm it resolves: `ffprobe -version`

## Install normal

Clone and install into a virtual environment — recommended, and the path everything else assumes:

```bash
git clone https://github.com/lmckellar/normal.git
cd normal
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

For a non-editable install from inside the cloned repo, use
`python -m pip install .` instead.
The install command resolves Python dependencies inside the virtual environment;
do not rely on packages installed for another global Python version.

**Keep API keys out of `.venv/bin/activate`.** Recreating the venv wipes them. Store them in a durable shell source — `~/.bashrc`, `~/.zshrc`, or a separate env file you source before launch:

```bash
export TMDB_KEY=your_tmdb_key
export OMDB_KEY=your_omdb_key
export IMDB_DATASET_DIR=/path/to/imdb-datasets
```

## Verify

```bash
normal --help
```

Expected: the movie commands (`movie-plan`, `movie-apply`, `movie-scan`, `movie-profile`, `movie-inspect`, `movie-junk`, `movie-output`, `movie-register`) plus `web`.

```bash
ffprobe -version
```

Both must succeed before you run `normal`.

If you plan to use **Compare Against Canonical Lists**, also confirm the dataset:

```bash
printf '%s\n' "${IMDB_DATASET_DIR:+IMDB_DATASET_DIR loaded}"
test -f "$IMDB_DATASET_DIR/title.basics.tsv.gz" && test -f "$IMDB_DATASET_DIR/title.ratings.tsv.gz" && printf 'IMDb dataset files found\n'
```

## Platform notes

`normal` is developed and tested on **Linux**. macOS and Windows are not explicitly supported before `1.0`, and rough edges are expected — particularly around:

- file path handling on Windows
- `ffprobe` resolution on `PATH`
- the `~/.local/share/normal/` state and replacement-queue location

---

<sub>Authorship: **Agent-written** — see the [authorship policy](writing.md).</sub>
