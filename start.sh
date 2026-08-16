#!/usr/bin/env bash
#
# Start this instance under gunicorn, in the background, safely. `instance.sh`
# beside this file says which instance that is, and what gunicorn serves.
#
# Behavior around the bind port:
#   * Port free                       -> start gunicorn.
#   * Port held by *our* gunicorn     -> stop it, then restart cleanly.
#   * Port held by an *other* process -> refuse to start and exit non-zero.
#
# The awkward part is the `nohup ... &` launch. A backgrounded process returns
# success to the shell the instant it forks, so `set -e` never sees gunicorn die
# when it fails to start -- the script would "succeed" while nothing is serving.
# We therefore (a) check the port *before* launching and (b) wait for the app to
# answer a real HTTP request *after* launching, turning a silent bind failure or
# an import-time crash into a real, visible script failure. A listening port is
# not enough on its own: the master listens before it forks the worker that
# imports the app, so a worker that dies on import still leaves the port open
# for a moment (see `responds` in lib.sh).

set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
. ./lib.sh
require lsof
require curl   # the readiness probe (see `responds` in lib.sh)

# --- Config preflight: the files the app reads from this directory -----------
# The users aspect is required (the login list), in either legal form; .env is
# recommended (session key + API tokens). Point at ./setup.sh rather than failing
# deep inside gunicorn.
if ! resolve_users_document >/dev/null; then
  echo "Run ./setup.sh to create config/users/users.yaml and .env, then edit the values." >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "WARNING: no .env — using an insecure dev session key and no API tokens." >&2
  echo "Run ./setup.sh to create one (or set SECRET_KEY / LITTLE_SISTER_API_TOKENS)." >&2
fi

START_TIMEOUT="${START_TIMEOUT:-50}"   # wait for "up", in 0.2s steps (~10s)

# --- Pre-flight: decide what to do about anything already on the port --------
# Done first (before the slow `uv sync`) so an occupied port fails fast, and so
# a failing sync never takes down an already-running instance.
restart_master=""
existing="$(listeners)"
if [ -n "$existing" ]; then
  foreign=""
  for pid in $existing; do
    is_ours "$pid" || foreign="${foreign} ${pid}"
  done
  if [ -n "$foreign" ]; then
    echo "ERROR: port ${PORT} is already in use by another process:" >&2
    for pid in $foreign; do
      echo "  PID ${pid}: $(cmd_of "$pid")" >&2
    done
    echo "Refusing to start. Stop that process, or set LITTLE_SISTER_PORT." >&2
    exit 1
  fi
  restart_master="$(master_of "$existing")"
  echo "${NAME} already running on :${PORT} (PID ${restart_master}); will restart it."
fi

# --- Dependencies & environment ---------------------------------------------
uv sync
# shellcheck disable=SC1091
. .venv/bin/activate

# --- Stop the old instance (if any), then make sure the port is free ---------
if [ -n "$restart_master" ]; then
  stop_master "$restart_master"
fi
if [ -n "$(listeners)" ]; then
  echo "ERROR: port ${PORT} is still occupied; aborting." >&2
  exit 1
fi

# --- Launch (the nohup part) -------------------------------------------------
echo "Starting ${NAME} on ${HOST}:${PORT}..."
mkdir -p var          # runtime artifacts (gunicorn log + pidfile) live under var/
nohup gunicorn --workers 1 --threads 8 --bind "${HOST}:${PORT}" \
      --pid "$PID_FILE" "$APP" > "$LOG" 2>&1 &
app_pid=$!

# Verify it really came up. Because the launch is backgrounded, this is the only
# place a bind failure (or an import-time crash) becomes visible to the script.
# "Came up" means the app answered a request -- not that the port is open; see
# `responds` in lib.sh for why the two differ.
for _ in $(seq 1 "$START_TIMEOUT"); do
  if ! kill -0 "$app_pid" 2>/dev/null; then
    echo "ERROR: gunicorn exited during startup. Recent log:" >&2
    tail -n 20 "$LOG" >&2
    exit 1
  fi
  if fatal_in_log; then
    echo "ERROR: gunicorn could not boot a worker. Recent log:" >&2
    tail -n 20 "$LOG" >&2
    exit 1
  fi
  if status="$(responds)"; then
    engine_error="$(engine_error_in_log)"
    if [ -n "$engine_error" ]; then
      echo "ERROR: serving on :${PORT}, but the engine did not start — nothing is" >&2
      echo "being monitored: ${engine_error}" >&2
      echo "Fix the check config and run $0 again. The process (PID ${app_pid}) is" >&2
      echo "left running: the dashboard shows the same message. ./stop.sh ends it." >&2
      exit 1
    fi
    echo "${NAME} is up (PID ${app_pid}); logging to ${LOG}."
    if [ "$status" -ge 500 ]; then
      echo "WARNING: ${PROBE_PATH} answered HTTP ${status}: it is serving, but" >&2
      echo "erroring -- check ${LOG}." >&2
    fi
    exit 0
  fi
  sleep 0.2
done

echo "ERROR: gunicorn (PID ${app_pid}) did not answer on :${PORT} after startup." >&2
tail -n 20 "$LOG" >&2
exit 1
