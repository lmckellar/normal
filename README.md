# normal

![Status](https://img.shields.io/badge/status-alpha-orange)
![Version](https://img.shields.io/badge/version-0.7.0--alpha.7-blue)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Platform](https://img.shields.io/badge/platform-Linux--first-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

User consensus is unanimous:

> "Better than Filebot... probably?"
> — You

`normal` is a thoroughly weird and opinionated open source local workbench that fixes a cross section of common issues with messy movie libraries. It seeks to restore calm where there was disarray and can be useful for organizing, maintaining, improving or expanding your digital film collection.

<placeholder awaiting gif>

## 🎯 What It Does

- 🎬 Normalises movie files and parent folders into `Title (Year)/Title (Year)` naming convention
- 🔍 Inspects the library and arranges it into a cross section of user editable quality profiles and shortlists what doesn't make the cut
- 🗑️ Deletes the shortlisted weak movie encodes (looking at you, YIFY) from disk and then saves them in a text based replacement queue, freeing space immediately while recording what needs replacing
- 🧹 Deletes Samples, Featurettes, Extras, Foreign Audio, promotional `.txt` spam and other junk ephemera
- 🔊 Enforces logical subtitle and audio defaults across the board with `ffmpeg` remuxing
- 📊 Lets you compare your collection directly against canonical movie lists (TMDB Top 100, 250, etc.) and identify what's missing
- 📤 One Click Export your entire library as a cleanly organized spreadsheet
- 🤝 Removes downstream frustrations with clients like Plex, Emby and Jellyfin and their oddly conflicting naming requirements

All packaged with a focused local Web workbench, minimal dependencies and all core features are local only.

<placeholder awaiting screenshot>

## 📦 Supported Formats

`normal` recognises the common video containers — **MKV, MP4, M4V, AVI, MOV, WMV, MPG/MPEG, TS, M2TS, and WebM**. Normalize, quality profiling, weak-encode and junk triage, inspect, and export all work across every one of them.

Audio- and subtitle-default repair (the lossless `mkvpropedit` / `ffmpeg` remux lane) is **MKV only** — other containers are still scanned and reported, just not remuxed.

Disc images (`.iso`) and raw disc rips are **not supported**. Remux them to MKV first (e.g. with MakeMKV) and `normal` will pick them up.

## 🚀 Get Started [1]

```bash
git clone https://github.com/lmckellar/normal.git
cd normal
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
normal web --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765` in your browser. On first run, point `normal` at your library folder in the UI — it's saved for next time, so you only do it once. (You *can* still pass `--source /path/to/Movies` on launch if you prefer, but you don't need to.)

<placeholder awaiting gif>

## 🤓 Safety

`normal` is aggressive by default. It renames, moves, deletes and remuxes files, and it tries to get from mess to clean in as few drive read/write passes as possible. That's the whole point — but it also means you should not aim it at your real library cold.

Before it touches anything you care about, copy a small test directory with a representative cross-section of your actual naming and folder conventions — a Noah's Ark of your current mess — and run everything there first. Watching the tool purify a test library for the first time is a good experience. Watching it touch your real library before you're ready is not.

The full safety posture, the approval gates, and networking behaviour live in [docs/safety.md](docs/safety.md). Recommended first-run process is in [docs/quickstart.md](docs/quickstart.md).

## 🔑 Optional API Keys

All core workflows — normalize, profile scans, weak-encode and junk triage, repair defaults, inspect, export, and Compare Against Canonical Lists — run entirely on local files with **no API key required**.

An optional `OMDB_KEY` adds IMDb ratings to the movie list and canonical-list views. Paste it into the workbench **Settings** rail or pass it on launch (`normal web --omdb-key ...` or the environment); either way it is stored locally under `~/.local/share/normal/secrets.env` and takes effect live without a restart. A free key is available at <https://www.omdbapi.com/apikey.aspx>.

(`TMDB_KEY` is only offered as alternative if you switch Compare Against Canonical Lists back to the TMDb provider. See [docs/movies.md](docs/movies.md) for where these surface in the UI.)

## 🔥 The Opinionated Part

`normal` is built around the following principles that lead to some loud claims:

**🪙 Physical Storage Economics**

The bigger a file gets, the stronger the case it has to make for existing.

Conversely, beneath a certain perceptual threshold even small files are objectively not worth existing.

**💽 Physical Scan Economics**

Reading and writing to a physical hard drive repeatedly is not free. `normal` tries to know what it wants the library to look like at the outset and take the minimum number of actions required to reach that goal.

**🧭 Universal Naming Convention**

While preference on the specifics of naming and organisation may vary occasionally in response to obscure user preference, the expectations of downstream clients such as Plex and Jellyfin are explicit and should be targeted with a Universal Naming Convention that translates as freely between media API databases like IMDB/TMDB as it does into other clients like Emby, etc.

**😤 The Holy Trinity Of Snobby Claims**

1. A library of 1,000 orderly, relevant, well-encoded films beats a library of 5,000 weak, mediocre and chaotic ones.

2. A maintenance process of 1,000 concise, respectful drive read/write events is preferable to one of 5,000 less concise ones if it achieves the same downstream shape.

3. Title (Year)/Title (Year).mkv is **The Way**.

The fuller stance on why these choices are adopted is in [docs/statement.md](docs/statement.md).

## 🧰 Support [1]

`normal` runs on Python 3.12+ and is Linux-first — developed and daily-driven on Ubuntu, where it has been dead stable: no crashes, no hangs, no garbled or botched muxes. That stability isn't really ours to take credit for. Under the hood `normal` leans on a small set of bulletproof, battle-tested open-source libraries (`ffmpeg`, `ffprobe`, `mkvtoolnix`, `openpyxl`) and works hard to stay out of their way.

macOS and Windows aren't hardened yet. They may already work, but they haven't been validated, and other mount and filesystem types are similarly untested. Treat them as "help wanted," not "you're on your own."

**Requirements:** `ffprobe` for media-probing workflows (`movie-scan`, `movie-profile`, `movie-inspect`, `movie-register`, `web`); `ffmpeg` for remux repairs; and `mkvpropedit` (from `mkvtoolnix`) for the fast disposition-only repair lane, falling back to `ffmpeg` when absent. These are external binaries — install them from your distro's packages. The sole Python dependency, `openpyxl`, installs automatically with `pip install -e .` and powers the XLSX export.

## 🙌 Get Involved

The project is genuinely open to participation now, and a few kinds of help are worth their weight in gold:

- **You speak a language other than English.** This is the big one. `normal`'s subtitle and audio-default logic has a heavy English bias baked deep into it, and I honestly don't know how a multilingual viewer actually wants their films configured — which audio track should win, which subtitles, and when. If you watch films across several languages and have a view on what "correct" defaults look like, please tell me. It is the single most valuable feedback this tool can get.
- **You have a filthy library.** Huge, ugly, inconsistently-named collections are perfect material for corpus regression study and edge-case hardening. Real mess beats synthetic test data every time.
- **You're on macOS or Windows.** Theoretical deployment hardening for both as real targets is being set up — the boring machinery around packaging, paths, mounts, and bundled binaries. Validation from people actually running those platforms would move it along far faster.
- **You found an edge case, hit a wall, or have feedback.** Open an issue. Anything that wants to test, poke at, or break the tool is welcome.

## 📚 Docs

- 📜 [Statement](docs/statement.md)
- 🔧 [Install](docs/install.md)
- ⚡ [Quick start](docs/quickstart.md)
- 🎬 [Movies](docs/movies.md)
- 🛡️ [Safety](docs/safety.md)
- ⌨️ [CLI reference](docs/commands.md)
- ✍️ [Documentation authorship](docs/writing.md)
- 🗺️ [Roadmap](docs/roadmap.md)
- 🏗️ [Architecture overview](docs/architecture.md)

For contributors and agents working in the codebase: [docs/agent.md](docs/agent.md), [CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md).

## 📄 License

MIT — see [LICENSE](LICENSE).

---

<sub>Authorship: **Human/AI-authored** — see the [authorship policy](docs/writing.md).</sub>
<sub>[1] *Get Started* and *Support*: **Agent-written**.</sub>
