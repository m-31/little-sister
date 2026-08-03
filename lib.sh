# shellcheck shell=bash
# shellcheck disable=SC2034  # config values below are used by the sourcing scripts
#
# Shared helpers for start.sh / stop.sh.
#
# Source this *after* `cd`-ing to the repo root (both scripts do `cd
# "$(dirname "$0")"` first). It defines the bind target, the way we recognize
# our own gunicorn, and the graceful-stop routine -- so start and stop always
# agree on what "our process" means and never touch an unrelated service.

HOST="${LITTLE_SISTER_HOST:-0.0.0.0}"
PORT="${LITTLE_SISTER_PORT:-8000}"
APP="little_sister.app:app"
LOG="var/gunicorn.log"
PID_FILE="var/gunicorn.pid"
STOP_TIMEOUT="${STOP_TIMEOUT:-50}"   # graceful-stop wait, in 0.2s steps (~10s)

require() {
  command -v "$1" >/dev/null 2>&1 ||
    { echo "ERROR: required command '$1' not found." >&2; exit 1; }
}

# PIDs currently LISTENing on the port (a gunicorn master and its workers all
# share the one listening socket, so this may return more than one PID).
listeners() { lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null | sort -u || true; }

# --- Readiness ---------------------------------------------------------------
# A listening port does *not* mean the app is up. The gunicorn master binds and
# listens *before* it forks the worker that imports the WSGI app, so a worker
# that dies on an import error still leaves a listening socket behind for the
# second or two the master needs to give up. "Up" therefore means the app
# *answered an HTTP request*, which only a booted worker can do.

PROBE_PATH="${LITTLE_SISTER_PROBE_PATH:-/login}"   # the one route served without a session
PROBE_TIMEOUT="${PROBE_TIMEOUT:-2}"                # seconds to wait for one probe

# Where to send that probe: the bind host may be a wildcard, which is not a
# usable destination address, so probe the loopback in that case.
probe_host() {
  case "$HOST" in
    0.0.0.0|"")  echo "127.0.0.1" ;;
    ::|"[::]")   echo "[::1]" ;;
    *)           echo "$HOST" ;;
  esac
}

# One readiness probe. Echoes the HTTP status and returns 0 if the app answered
# at all: *any* status proves a worker imported the app and served a request, so
# we deliberately do not require 2xx here (the caller warns about a 5xx). It
# fails when the connection is refused, and when the master accepts it but no
# worker is alive to answer.
responds() {
  local code
  code="$(curl -s -o /dev/null -m "$PROBE_TIMEOUT" -w '%{http_code}' \
            "http://$(probe_host):${PORT}${PROBE_PATH}" 2>/dev/null)" || return 1
  if [ "$code" = "000" ]; then return 1; fi   # curl reached nothing
  echo "$code"
}

# The fatal startup markers gunicorn writes to its log. Matching one is an
# *accelerator*, not the readiness test: it turns a full start timeout into an
# immediate, explained failure when no worker can boot -- an import error, or a
# worker that crashes and is respawned in a loop while the master stays alive.
# start.sh truncates the log at every launch, so an older failure cannot match.
fatal_in_log() {
  grep -Eq 'Worker failed to boot|Shutting down: Master|Exception in worker process' \
    "$LOG" 2>/dev/null
}

# Serving is not the same as monitoring. A bad check config does not stop the app:
# `little_sister.app` logs this line, leaves the engine unstarted and serves anyway,
# so the dashboard can show an "Engine not started" banner rather than an
# unexplained empty tree. For a start *script* that is a failed start -- nothing is
# being monitored -- so start.sh reports it and exits non-zero, leaving the process
# up so the banner stays readable (./stop.sh ends it).
#
# The line is written while the WSGI app is imported, i.e. strictly before any
# worker can answer a request: checking after a successful probe cannot race it. A
# deliberate LITTLE_SISTER_ENGINE=0 logs "engine disabled via …" instead, so it does
# not match here.
ENGINE_ERROR_MARK="engine not started:"
engine_error_in_log() {
  # `|| true` because no match is the healthy case, and `set -o pipefail` in the
  # caller would otherwise turn grep's "found nothing" into a failed assignment.
  grep -h "$ENGINE_ERROR_MARK" "$LOG" 2>/dev/null |
    tail -n 1 | sed "s/.*${ENGINE_ERROR_MARK} *//" || true
}

# Full command line of a PID (empty if the process is already gone).
cmd_of() { ps -p "$1" -o command= 2>/dev/null || true; }

# Is this PID one of *our* gunicorn processes, as opposed to some unrelated
# service that merely happens to sit on the same port? We match the gunicorn
# invocation together with our app target, which also survives gunicorn's
# "gunicorn: master [little_sister.app:app]" process-title rewrite.
is_ours() {
  case "$(cmd_of "$1")" in
    *gunicorn*"$APP"*) return 0 ;;
    *) return 1 ;;
  esac
}

# Given a set of related gunicorn PIDs, the master is the one whose parent is
# *not* itself in the set (workers are children of the master).
master_of() {
  local pids="$*" pid ppid other
  for pid in $pids; do
    ppid="$(ps -p "$pid" -o ppid= 2>/dev/null | tr -d ' ')"
    for other in $pids; do
      [ "$other" = "${ppid:-0}" ] && continue 2   # parent in set -> a worker
    done
    echo "$pid"; return 0                          # parent not in set -> master
  done
  echo "${pids%% *}"   # fallback: first PID
}

# Gracefully stop a gunicorn master: TERM, wait, then KILL as a last resort.
stop_master() {
  local pid="$1" i
  echo "Stopping running little-sister (PID ${pid})..."
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 "$STOP_TIMEOUT"); do
    kill -0 "$pid" 2>/dev/null || { echo "Stopped."; return 0; }
    sleep 0.2
  done
  echo "Did not exit in time; sending KILL." >&2
  kill -KILL "$pid" 2>/dev/null || true
  sleep 0.5
}
