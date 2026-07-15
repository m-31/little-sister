#!/usr/bin/env bash
#
# Stop the running little-sister (the gunicorn that start.sh launched).
#
#   * Our gunicorn on the port -> stop it gracefully (TERM, then KILL).
#   * Nothing on the port      -> nothing to do (exit 0); clears a stale pidfile.
#   * Another process on port  -> refuse to touch it and exit non-zero.

set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
. ./lib.sh
require lsof

existing="$(listeners)"
if [ -z "$existing" ]; then
  echo "little-sister is not running on :${PORT}."
  rm -f "$PID_FILE"
  exit 0
fi

# Never stop something that isn't ours, even if it sits on our port.
foreign=""
for pid in $existing; do
  is_ours "$pid" || foreign="${foreign} ${pid}"
done
if [ -n "$foreign" ]; then
  echo "ERROR: port ${PORT} is held by another process; refusing to stop it:" >&2
  for pid in $foreign; do
    echo "  PID ${pid}: $(cmd_of "$pid")" >&2
  done
  exit 1
fi

stop_master "$(master_of "$existing")"
if [ -n "$(listeners)" ]; then
  echo "ERROR: something is still listening on :${PORT} after stop." >&2
  exit 1
fi
rm -f "$PID_FILE"
echo "little-sister stopped."
