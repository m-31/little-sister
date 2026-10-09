#!/usr/bin/env bash
#
# Start this instance under gunicorn, in the background, safely. `instance.sh`
# beside this file says which instance that is, and what gunicorn serves.
#
# Behavior around the bind port:
# `--any-instance` lets this run replace a gunicorn this checkout did not start; without
# it, one on this port is a refusal that names the flag.
#
# `--tls` serves HTTPS with a certificate this installation supplied, or one
# minted for this run and kept by nobody, on the TLS port rather than the plain
# one (`lib.sh`). Without it nothing about a plain-HTTP run changes.
#
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
parse_flags "$@"
resolve_bind
require lsof
require curl   # the readiness probe (see `responds` in lib.sh)

# --- Config preflight: the files the app reads from this directory -----------
# The users aspect, in either legal form, **where this installation is one that has
# one**; `.env` is recommended everywhere (session key + API tokens). Point at
# ./setup.sh rather than failing deep inside gunicorn.
#
# **Why that condition exists.** The check used to be unconditional, and it was
# right while the built-in login list was the only way in. It stopped being right
# when a deployment could register a provider of its own: an installation whose
# doors are an identity provider and the system-admin account has no `users` aspect
# to find, is entirely correct, and was refused by a script that never asked which
# doors it had — a rule stated for every installation from the shape of one.
#
# It is a variable rather than a discovery because this script cannot discover it:
# which doors exist is decided while the app is imported, which is after this script
# has forked gunicorn. `announce_doors()` is what answers *who can sign in here*,
# at startup, knowing about every door rather than about one file — so an
# installation that opts out here is not unwatched, it is watched by the thing that
# can see the answer.
#
# And it stays a **refusal** where it applies, rather than becoming a warning
# everywhere: an installation whose way in is that file has a missing file as a
# hard fault, and a warning that means "this may be fine" on every start is how a
# log stops being read.
REQUIRE_USERS_ASPECT="${REQUIRE_USERS_ASPECT:-1}"
if [ "$REQUIRE_USERS_ASPECT" != 0 ] && ! resolve_users_document >/dev/null; then
  echo "Run ./setup.sh to create config/users/users.yaml and .env, then edit the values." >&2
  echo "(An installation that registers its own identity doors and no built-in login" >&2
  echo "list sets REQUIRE_USERS_ASPECT=0 in instance.sh.)" >&2
  exit 1
fi
if [ ! -f .env ]; then
  echo "WARNING: no .env — a random session key per start (so every restart logs" >&2
  echo "everyone out), no system-admin password, and no API tokens." >&2
  echo "Run ./setup.sh to create one (or set SECRET_KEY / LITTLE_SISTER_API_TOKENS)." >&2
fi

START_TIMEOUT="${START_TIMEOUT:-50}"   # wait for "up", in 0.2s steps (~10s)

# How long gunicorn lets a worker go without a heartbeat before it kills and
# restarts it -- which covers the worker's **import**, not only its requests.
# The default is gunicorn's own, so this changes nothing by itself; an instance
# whose import can legitimately take longer raises it in `instance.sh`, together
# with START_TIMEOUT above. Both matter for the same reason and neither alone is
# enough: this one decides whether the worker survives, that one decides whether
# this script waits long enough to see it.
WORKER_TIMEOUT="${WORKER_TIMEOUT:-30}"

# --- Pre-flight: decide what to do about anything already running ------------
# Done first (before the slow `uv sync`) so an occupied port fails fast, and so
# a failing sync never takes down an already-running instance.
#
# Two different questions, and they are asked of two different sets of ports.
# **Is the port we are about to bind held by somebody else** is asked of this run's
# port alone -- a stranger on the other scheme's port is none of our business,
# because we are not going to bind it. **Is this checkout already serving** is asked
# of both, because a checkout serves one instance and a start
# replaces it wherever it is listening.
restart_master=""
restart_port=""
existing="$(listeners)"
if [ -n "$existing" ]; then
  foreign=""
  for pid in $existing; do
    is_ours "$pid" || foreign="${foreign} ${pid}"
  done
  if [ -n "$foreign" ]; then
    echo "ERROR: port ${PORT} is already in use by another process:" >&2
    hint=0
    for pid in $foreign; do
      echo "  PID ${pid}: $(cmd_of "$pid")" >&2
      if is_an_instance "$pid"; then hint=1; fi
    done
    if [ "$hint" = 1 ]; then any_instance_hint; fi
    echo "Refusing to start. Stop that process, or set LITTLE_SISTER_PORT." >&2
    exit 1
  fi
fi

restart_port="$(our_port)"
if [ -n "$restart_port" ]; then
  restart_master="$(master_of "$(listeners_on "$restart_port")")"
  if ! own_instance "$restart_master"; then
    # Only reachable with --any-instance, and it says so rather than calling somebody
    # else's process ours.
    echo "Replacing an instance this checkout did not start (PID ${restart_master}" \
         "on :${restart_port}), because --any-instance was given."
  elif [ "$restart_port" = "$PORT" ]; then
    echo "${NAME} already running on :${PORT} (PID ${restart_master}); will restart it."
  else
    # The case that used to slip through: a start under one scheme while the other
    # was serving left two instances sharing one pidfile, and this launch would
    # truncate the log the older one is still writing to and still being read from.
    echo "${NAME} is running on :${restart_port} (PID ${restart_master}); a checkout" \
         "serves one instance, so this start replaces it."
  fi
fi

# --- Dependencies & environment ---------------------------------------------
uv sync
# shellcheck disable=SC1091
. .venv/bin/activate

# --- Stop the old instance (if any), then make sure the port is free ---------
if [ -n "$restart_master" ]; then
  stop_instance "$restart_master"
fi
# Only this run's port has to be free -- the old instance's, whichever it was, is
# gone by now, and nothing else is about to bind the other one.
if [ -n "$(listeners)" ]; then
  echo "ERROR: port ${PORT} is still occupied; aborting." >&2
  exit 1
fi

# --- The certificate, if this is a TLS run -----------------------------------
# Minted (or resolved) *after* the port is free and the old instance is gone, so
# a refused start leaves no new files behind, and before the launch, because
# gunicorn reads both paths on every accepted connection.
tls_args=()
if [ "$TLS" = 1 ]; then
  # A plain assignment, so `set -e` stops here when the mint or the supplied pair
  # was refused; reading straight into `read` would swallow the failure and hand
  # gunicorn two empty paths.
  tls_paths="$(mint_certificate)"
  # One path per line, and `IFS=` so a path that contains a space -- which a
  # supplied certificate's may -- arrives whole rather than split across the two.
  { IFS= read -r cert_path; IFS= read -r key_path; } <<< "$tls_paths"
  tls_args=(--certfile "$cert_path" --keyfile "$key_path")
fi

# --- Launch (the nohup part) -------------------------------------------------
echo "Starting ${NAME} on ${SCHEME}://${HOST}:${PORT}..."
mkdir -p var          # runtime artifacts (gunicorn log + pidfile) live under var/
# `--workers 1` is load-bearing and not a default worth tuning: every worker is a
# separate interpreter with its own status tree and its own engine, and
# process-wide state -- an `aws sso login` in flight, for one --
# would be held once per worker. Threads are how this serves more than one reader.
#
# The last three flags are the stop and the start. The grace is one value (lib.sh).
# Keep-alive is off because an idle keep-alive connection -- a page open between two
# polls -- holds the worker's exit to the end of the grace. And the hooks module starts
# the engine right after the worker's import and stops it when the worker leaves:
# without it the application serves with no engine, and says so on every page.
nohup gunicorn --workers 1 --threads 8 --timeout "${WORKER_TIMEOUT}" \
      --graceful-timeout "${GRACEFUL_TIMEOUT}" --keep-alive 0 \
      --config python:little_sister.gunicorn_hooks \
      --bind "${HOST}:${PORT}" ${tls_args[@]+"${tls_args[@]}"} \
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
    echo "${NAME} is up on ${SCHEME}://${HOST}:${PORT} (PID ${app_pid});" \
         "logging to ${LOG}."
    if ! certificate_verifies; then
      echo "WARNING: nothing on this machine trusts the certificate in" >&2
      echo "  ${TLS_CERT} -- it is serving, but a browser will warn and any" >&2
      echo "  client that verifies will refuse it." >&2
    fi
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
