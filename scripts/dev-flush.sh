#!/usr/bin/env bash
#
# dev-flush — warm/cold/nuke the local normal web stack in one shot.
#
# The staleness you hit after a deep change lives in exactly three layers:
#   1. server in-memory caches  (MOVIE_PROFILE_CACHE / MOVIE_CANONICAL_CACHE)
#        -> die whenever the server process restarts. Every tier below restarts.
#   2. browser in-page `state`  (normalize_lab.js; no localStorage at all)
#        -> this script can't touch it: hard-reload the tab after a flip.
#   3. disk: probe-cache.json   (holds derived classifications)
#        -> only `cold` and `nuke` clear it.
#
# Tiers:
#   warm  (default)  stop server -> restart.            Keeps all disk caches;
#                                                        probe cache intact, so
#                                                        no re-ffprobe. 90% case.
#   cold             stop -> rm probe-cache.json -> restart.
#                                                        Re-ffprobes on next scan.
#                                                        Use when you changed how
#                                                        facts/classifications are
#                                                        derived without bumping
#                                                        ProbeCache._VERSION.
#   nuke             cold + wipe omdb ratings + canonical lists. Explicit only.
#
# Hard invariants:
#   * NEVER deletes audit-ledger.jsonl (immutable history).
#   * NEVER redownloads the IMDb dataset unless --include-dataset is passed.
#   * NEVER touches user config (library-roots / operator-preferences).
#
# Usage:
#   scripts/dev-flush.sh [warm|cold|nuke] [--source PATH] [--host H] [--port N]
#                        [--include-dataset] [--no-start]

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/.venv"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/normal"
CACHE_DIR="$HOME/.cache/normal"
LOG="/tmp/normal-dev-web.log"

MODE="warm"
HOST="127.0.0.1"
PORT="8765"
SOURCE="${NORMAL_DEV_SOURCE:-/mnt/media_storage/Movies}"
INCLUDE_DATASET=0
START=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    warm|cold|nuke) MODE="$1"; shift ;;
    --source) SOURCE="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --include-dataset) INCLUDE_DATASET=1; shift ;;
    --no-start) START=0; shift ;;
    -h|--help) awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "dev-flush: unknown argument: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;36m[dev-flush]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[dev-flush]\033[0m %s\n' "$*" >&2; }

stop_server() {
  local pids=""
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  fi
  if [[ -z "$pids" ]]; then
    pids="$(pgrep -f "normal web .*--port $PORT" 2>/dev/null || true)"
  fi
  if [[ -z "$pids" ]]; then
    say "no server listening on $PORT"
    return 0
  fi
  say "stopping server (pids: $(echo "$pids" | tr '\n' ' '))"
  kill $pids 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if ! kill -0 $pids 2>/dev/null; then return 0; fi
    sleep 0.3
  done
  warn "server did not exit on SIGTERM; sending SIGKILL"
  kill -9 $pids 2>/dev/null || true
}

flush_disk() {
  case "$MODE" in
    warm)
      say "warm: in-memory caches only (cleared by restart); disk untouched"
      ;;
    cold)
      if [[ -f "$DATA_DIR/probe-cache.json" ]]; then
        rm -f "$DATA_DIR/probe-cache.json"
        say "cold: removed probe-cache.json (next scan re-ffprobes)"
      else
        say "cold: no probe-cache.json present"
      fi
      ;;
    nuke)
      rm -f "$DATA_DIR/probe-cache.json"
      rm -rf "$CACHE_DIR/omdb_ratings"
      rm -rf "$DATA_DIR/canonical_lists"
      say "nuke: removed probe cache + omdb ratings + canonical lists"
      if [[ "$INCLUDE_DATASET" == 1 ]]; then
        rm -rf "$DATA_DIR/imdb-datasets"
        warn "nuke: removed imdb-datasets (1-2 GB redownload on next use)"
      else
        say "nuke: imdb dataset preserved (pass --include-dataset to wipe)"
      fi
      ;;
  esac
  # Invariant guard: this script must never have removed these.
  [[ -e "$DATA_DIR/audit-ledger.jsonl" || ! -e "$DATA_DIR" ]] || true
}

preflight() {
  [[ -d "$VENV" ]] || { warn "no venv at $VENV (see docs/install.md)"; exit 1; }
  command -v ffprobe >/dev/null 2>&1 || warn "ffprobe not on PATH; movie workflows will fail"
  # Two-tier env stance: absence is the baseline, not a fault.
  #   * OMDB_KEY / TMDB_KEY are legacy/plan-B remote enrichers. Ingested if
  #     present, silent if not. Never warned about.
  #   * Canonical lists run off a self-managed IMDb dataset in
  #     $DATA_DIR/imdb-datasets (the app downloads it on its own). IMDB_DATASET_DIR
  #     is only an override to point at a custom dataset location, not the gate.
  #     Lists are active when the managed files are present OR the override is set.
  local managed_dataset="$DATA_DIR/imdb-datasets"
  if [[ -z "${IMDB_DATASET_DIR:-}" \
        && ! ( -e "$managed_dataset/title.basics.tsv.gz" && -e "$managed_dataset/title.ratings.tsv.gz" ) ]]; then
    say "IMDb dataset not present in $managed_dataset; canonical lists inactive until it downloads or IMDB_DATASET_DIR is set (other workflows unaffected)"
  fi
}

start_server() {
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  # Ingest saved plan-B enricher keys (OMDB_KEY / TMDB_KEY) from the UI-managed
  # secrets file into the environment so the cli picks them up at boot. Absence
  # stays silent; presence is reported so the key has a visible, durable home.
  local secrets="$DATA_DIR/secrets.env"
  if [[ -f "$secrets" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$secrets"
    set +a
    say "ingested saved keys from $secrets"
  fi
  say "starting: normal web --host $HOST --port $PORT --source $SOURCE"
  ( cd "$REPO" && exec python3 -m normal web --host "$HOST" --port "$PORT" --source "$SOURCE" ) \
    >"$LOG" 2>&1 &
  disown || true
  for _ in $(seq 1 40); do
    if curl -fsS "http://$HOST:$PORT/" >/dev/null 2>&1; then
      say "up: http://$HOST:$PORT/  (logs: $LOG)"
      warn "browser tab still holds the old in-page state — hard-reload it (Ctrl+Shift+R)"
      return 0
    fi
    sleep 0.25
  done
  warn "server did not respond on $HOST:$PORT within timeout; see $LOG"
  return 1
}

say "mode: $MODE"
preflight
stop_server
flush_disk
if [[ "$START" == 1 ]]; then
  start_server
else
  say "--no-start: server left down"
fi
