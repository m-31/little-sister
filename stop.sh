#!/usr/bin/env bash
#
# Stop this instance (the gunicorn that start.sh launched). `instance.sh` beside
# this file says which instance that is; the lines below print its name.
#
# It looks at **both** ports, because a checkout serves one instance and the
# point of stopping is to stop whatever this checkout is running,
# not to be told which scheme it happened to be started under. `--tls` is therefore
# accepted and needed by nothing here; it only decides which port the messages call
# "this run's" and which port a stranger would be refused on.
#
# "Ours" means a gunicorn whose working directory is *this checkout* -- not the WSGI
# target, which two checkouts can share, and nothing in the command line, which `ps`
# truncates and gunicorn rewrites. `--any-instance` widens it to any gunicorn on the
# port, and every refusal a gunicorn caused says so.
#
#   * Our gunicorn on either port -> stop it, and wait for every process of it: the
#                                    grace and five seconds, then KILL what is left.
#   * Nothing of ours, port free  -> nothing to do (exit 0); clears a stale pidfile.
#   * Another checkout's instance -> refuse, and name `--any-instance`.
#   * Anything else on the port   -> refuse to touch it and exit non-zero.

set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
. ./lib.sh
parse_flags "$@"
resolve_bind
require lsof

target="$(our_port)"

if [ -z "$target" ]; then
  # Nothing of ours on either port. A stranger on the port we would have used is
  # still worth refusing over rather than reporting a clean "nothing to do" -- that
  # is the one case where saying "not running" would send somebody looking in the
  # wrong place.
  strangers="$(listeners)"
  if [ -n "$strangers" ]; then
    echo "ERROR: port ${PORT} is held by another process; refusing to stop it:" >&2
    hint=0
    for pid in $strangers; do
      echo "  PID ${pid}: $(cmd_of "$pid")" >&2
      if is_an_instance "$pid"; then hint=1; fi
    done
    if [ "$hint" = 1 ]; then any_instance_hint; fi
    exit 1
  fi
  echo "${NAME} is not running (looked at :${PORT}${OTHER_PORT:+ and :${OTHER_PORT}})."
  # Nothing of ours is listening on either port, so the pidfile is stale by
  # definition and clearing it cannot orphan an instance. It used to be cleared on
  # the strength of one port, which is how a `./stop.sh` that found nothing took the
  # pidfile of a TLS instance that was serving perfectly.
  rm -f "$PID_FILE"
  exit 0
fi

existing="$(listeners_on "$target")"

# Never stop something that isn't ours, even if it shares the port with us.
foreign=""
for pid in $existing; do
  is_ours "$pid" || foreign="${foreign} ${pid}"
done
if [ -n "$foreign" ]; then
  echo "ERROR: port ${target} is held by another process; refusing to stop it:" >&2
  hint=0
  for pid in $foreign; do
    echo "  PID ${pid}: $(cmd_of "$pid")" >&2
    if is_an_instance "$pid"; then hint=1; fi
  done
  if [ "$hint" = 1 ]; then any_instance_hint; fi
  exit 1
fi

master="$(master_of "$existing")"
if ! own_instance "$master"; then
  echo "Stopping an instance this checkout did not start (PID ${master} on" \
       ":${target}), because --any-instance was given."
elif [ "$target" != "$PORT" ]; then
  echo "${NAME} is serving on :${target}, not :${PORT}; stopping it anyway."
fi
stop_instance "$master"
if [ -n "$(listeners_on "$target")" ]; then
  echo "ERROR: something is still listening on :${target} after stop." >&2
  exit 1
fi
rm -f "$PID_FILE"
echo "${NAME} stopped."
