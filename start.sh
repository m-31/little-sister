#!/usr/bin/env bash
#
# Start little-sister under gunicorn, in the background, safely.
#
# Behaviour around the bind port:
#   * Port free                       -> start gunicorn.
#   * Port held by *our* gunicorn     -> stop it, then restart cleanly.
#   * Port held by an *other* process -> refuse to start and exit non-zero.
#
# The awkward part is the `nohup ... &` launch. A backgrounded process returns
# success to the shell the instant it forks, so `set -e` never sees gunicorn die
# when it fails to bind the port -- the script would "succeed" while nothing is
# listening. We therefore (a) check the port *before* launching and (b) verify
# gunicorn is actually alive *and* listening *after* launching, turning a silent
# bind failure into a real, visible script failure.

set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
. ./lib.sh
require lsof

# --- Config preflight: the files the app reads from this directory -----------
# users.yaml is required (the login list); .env is recommended (session key + API
# tokens). Point at ./setup.sh rather than failing deep inside gunicorn.
users_file="${LITTLE_SISTER_USERS:-users.yaml}"
if [ ! -f "$users_file" ]; then
  echo "ERROR: user list '$users_file' not found — it is required to log in." >&2
  echo "Run ./setup.sh to create users.yaml and .env, then edit the values." >&2
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
  echo "little-sister already running on :${PORT} (PID ${restart_master}); will restart it."
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
echo "Starting little-sister on ${HOST}:${PORT}..."
mkdir -p var          # runtime artifacts (gunicorn log + pidfile) live under var/
nohup gunicorn --workers 1 --threads 8 --bind "${HOST}:${PORT}" \
      --pid "$PID_FILE" "$APP" > "$LOG" 2>&1 &
app_pid=$!

# Verify it really came up. Because the launch is backgrounded, this is the only
# place a bind failure (or an import-time crash) becomes visible to the script.
for _ in $(seq 1 "$START_TIMEOUT"); do
  if ! kill -0 "$app_pid" 2>/dev/null; then
    echo "ERROR: gunicorn exited during startup. Recent log:" >&2
    tail -n 20 "$LOG" >&2
    exit 1
  fi
  if listeners | grep -qx "$app_pid"; then
    echo "little-sister is up (PID ${app_pid}); logging to ${LOG}."
    exit 0
  fi
  sleep 0.2
done

echo "ERROR: gunicorn (PID ${app_pid}) is not listening on :${PORT} after startup." >&2
tail -n 20 "$LOG" >&2
exit 1
