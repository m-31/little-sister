# shellcheck shell=bash
# shellcheck disable=SC2034  # config values below are used by the sourcing scripts
#
# Shared helpers for start.sh / stop.sh.
#
# Source this *after* `cd`-ing to the repo root (both scripts do `cd
# "$(dirname "$0")"` first). It defines the bind target, the way we recognise
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
