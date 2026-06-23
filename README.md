# normal movie renamer

![Status](https://img.shields.io/badge/status-alpha-orange)
![Version](https://img.shields.io/badge/version-0.7.0--alpha.9-blue)
![Python](https://img.shields.io/badge/python-3.12%E2%80%933.14-blue)
![Platform](https://img.shields.io/badge/platform-Linux--first-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

User consensus is unanimous:

> "Better than Filebot... probably?"
> — You

`normal` is a thoroughly weird and opinionated open source local workbench that fixes a cross section of common issues with messy movie libraries. It seeks to restore calm where there was disarray and can be useful for organizing, maintaining, improving or expanding your digital film collection.

<placeholder awaiting gif>

## 🧹 What It Does

- 🎬 Normalizes movie files and parent folders into `Title (Year)/Title (Year)` naming convention
- 🔍 Inspects the library and arranges it into a cross section of user editable quality profiles
- 🗑️ Bulk Deletes shortlisted weak encodes, Samples, Featurettes, Extras, `.txt` spam and other junk ephemera freeing space immediately 
- 📑 Creates and manages a local Universal Ledger & Replacement Queue that centralizes all deleted items and checks for a replacement 
- 🎯 Surgically removes Foreign Audio files(s) from within .mkv packages
- 📽️ Enforces logical subtitle and audio defaults across the board with `ffmpeg` remuxing and `mkvpropedit` subtitle swapping
- 📤 One Click Export your entire library as a cleanly organized spreadsheet for a quick 💪
- 🤝 Removes downstream frustrations with clients like Plex, Emby and Jellyfin and their oddly conflicting naming requirements
- 🗣️ Tells you whether a *better release* of a film even exists — UHD, Dolby Vision, object-based immersive audio (Atmos / DTS:X), Open Matte, or Hybrid — and whether your own copies already have it. A fact no scanner can read off a library and no public API will sell you
- 🦀 Conceals its deep shame and embarrassment for being agent-coded in 2026 but not written in Rust. It prays to 🧇 for guidance
- 📊 Lets you compare your collection directly against canonical movie lists and identify what's missing:
  - IMDb Top 100 / 250 / 500 All Time Greatest Movies
  - Genre lists: Animation, Sci-Fi, Fantasy, Action, Thriller/Mystery, Drama/Romance, Documentary, Comedy
- 🚨 It even does other stuff too 🔥

All presented with a generic slop GUI, minimal dependencies and all core features are local only (except the ones that aren't). 

`normal` packages only the bare minimum of CCP spyware required to phone home and fetch media information that cannot be attained locally.  

<placeholder awaiting screenshot>

## 📦 Supported Formats

`normal` recognises all common video containers — **MKV, MP4, M4V, AVI, MOV, WMV, MPG/MPEG, TS, M2TS, and WebM**. Normalize, quality profiling, weak-encode and junk triage, inspect, and export all work across every one of them.

Audio- and subtitle-default repair (the lossless `mkvpropedit` / `ffmpeg` remux feature) is **MKV only** — other containers are still scanned and reported, just not remuxed.

Disc images (`.iso`) and raw disc rips are **not supported** at this stage.

## 🚀 Get Started [1]

```bash
git clone https://github.com/lmckellar/normal.git
cd normal
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
normal web --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765` in your browser. On first run, point `normal` at your library folder in the UI — it's saved for next time, so you only do it once. (You *can* still pass `--source /path/to/Movies` on launch if you prefer, but you don't need to.)

<placeholder awaiting gif>

## 🤓 Safety

`normal` is aggressive by default but does seek to provide for user safety when scanning and performing actions. 

It renames, moves, deletes and remuxes files, and it tries to get from mess to clean in as few drive read/write passes as possible. That's the whole point — but it also means you should not aim it at your real library cold.

Before it touches anything you care about, copy a small test directory with a representative cross-section of your actual naming and folder conventions — a Noah's Ark of your current mess — and run everything there first. 

The full safety posture, the approval gates, and networking behaviour live in [docs/safety.md](docs/safety.md). Recommended first-run process is in [docs/quickstart.md](docs/quickstart.md).

## 🔑 Optional API Keys

All core workflows — normalize, profile scans, weak-encode and junk triage, repair defaults, inspect, export, and Compare Against Canonical Lists — run entirely on local files with **no API key required**.

An optional `OMDB_KEY` adds IMDb ratings to the movie list and canonical-list views. Paste it into the workbench **Settings** rail or pass it on launch (`normal web --omdb-key ...` or the environment); either way it is stored locally under `~/.local/share/normal/secrets.env` and takes effect live without a restart. A free key is available at <https://www.omdbapi.com/apikey.aspx>.

(`TMDB_KEY` is only offered as alternative if you switch Compare Against Canonical Lists back to the TMDb provider. See [docs/movies.md](docs/movies.md) for where these surface in the UI.)

## 🙋 User F.A.Q's

❓ Q: How do you get internet access from the Asylum, and why did you make this application?

✅ A: Those are both fair questions.

🤷‍♂️

## 😤 The Opinionated Part

The core thesis of normal is this:

**🏦 Replicate Paid Software for the OSS Community**

Agentic Coding tools means the age of easily deployable, local, easily modifiable open source software has arrived.

**💽 Flattery Is Not Enough**

Cloning a tool like Filebot could be done in several afternoon with Claude & Codex. It is not enough. The OSS serpent must consume the paid tail in such a way that it becomes greater, grander, and better in every way.

**🧾 Create An Unsearchable, Unmarketable Name as a Joke Thereby Ensuring the Product Remains a "Hidden Gem" and Utterly Shoots Itself in the Foot Regardless of How Useful It Becomes**

A name like normal is a digital camouflage suit. The most patient hunter often waits in plain sight. It doesn't even get the honour of a capital letter. Ouch. 

## 👑 The Holy Trinity Of Snobby Claims

1. A library of 1,000 orderly, relevant, well-encoded films beats a library of 5,000 shit ones.

2. A maintenance process of 1,000 concise and respectful drive read/write events is preferable to one of 5,000 less concise ones *if it achieves the same downstream shape.*

3. Title (Year)/Title (Year).mkv is **The Way** 🧭.

The fuller stance on why these choices are adopted is in [docs/statement.md](docs/statement.md).

## 🧰 Support [1]

`normal` runs on Python 3.12 through 3.14 and is Linux-first — developed and daily-driven on Ubuntu, where it has been perfectly stable through 400+ scans (hard drive status: thoroughly fondled). Under the hood `normal` leans on a small set of bulletproof, battle-tested open-source libraries (`ffmpeg`, `ffprobe`, `mkvtoolnix`, `openpyxl`) and mostly just does python stuff around them.

macOS and Windows run in CI alongside Linux. Source safety uses native mount and volume detection on each platform, including macOS APFS/removable/network volumes and Windows drive roots, UNC shares, and junctions. Broader real-library validation remains welcome.

**Requirements:** `ffprobe` for media-probing workflows (`movie-scan`, `movie-profile`, `movie-inspect`, `movie-register`, `web`); `ffmpeg` for remux repairs; and `mkvpropedit` (from `mkvtoolnix`) for the light touch subtitle swaps, falling back to `ffmpeg` when absent. These are external binaries — install them from your distro's packages. The sole Python dependency, `openpyxl`, installs into the active interpreter with `python -m pip install -e .` and powers the XLSX export; it loads lazily, so a missing or broken `openpyxl` only affects catalogue export — every other workflow keeps running and the export tells you the exact command to restore it.

## 🙌 Get Involved

The project is genuinely open to participation now, and a few kinds of help are worth their weight in gold:

- **You speak a language other than English.** This is the big one. `normal`'s subtitle and audio-default logic has a heavy English bias baked deep into it, and I honestly don't know how a multilingual viewer actually wants their films configured — which audio track should win, which subtitles, and when. If you watch films across several languages and have a view on what "correct" defaults look like, please tell me. It is the single most valuable feedback this tool can get.
- **You have a filthy library.** Huge, ugly, inconsistently-named collections are perfect material for corpus regression study and edge-case hardening. My library is now as pure as the driven snow so I lack new crud to harden the parser against. 
- **You're on macOS or Windows.** Both platforms run in CI and have native mount safety checks; validation against real libraries, filesystems, and external media remains valuable.
- **You found an edge case, hit a wall, or have feedback.** Open an issue. Anyone who wants to test, poke at, or break the tool is welcome.

## 1 ⭐ on Github that I definitely did not pay for

Find out what all the critics are **raving** about:

> "WTF is this colostomy bag of vibe coded filth?"
> — People, who hurt my feelings deeply :(

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
