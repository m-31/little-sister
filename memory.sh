#!/usr/bin/env bash
#
# What this checkout's instance holds in memory: the resident size of the gunicorn
# master and of each worker it forked, and their sum -- one line on the terminal, and
# one row appended to `var/memory.csv` beside the log and the pidfile, so that a run
# measured at its start, an hour in and a day in can be read back as a column.
# `instance.sh` beside this file says which instance that is.
#
# It finds the instance the way `stop.sh` does -- on **both** ports, a gunicorn whose
# working directory is *this checkout*, `--any-instance` to widen that -- and never out
# of `var/gunicorn.pid`, for `lib.sh`'s reason: a pid in that file is a number that
# may since have been reused. The workers are the master's children, which is where an
# instance's memory is: the engine, the tree and the series live in the worker.
#
# The resident size is `ps`'s RSS: what each process has in physical memory now,
# shared pages included. It is neither Activity Monitor's "Memory", which is macOS's
# physical footprint, nor the figure the engine reads for itself on
# `/little-sister/engine`, which on macOS is the process's high-water mark. Compare a
# row with the rows above it, not with those.
#
#   * Our gunicorn on either port -> one line, one row (exit 0).
#   * Nothing of ours, port free  -> nothing to measure (exit 1), no row.
#   * Another checkout's instance -> refuse, and name `--any-instance`.
#   * Anything else on the port   -> refuse to measure it and exit non-zero.
#
# **Over a night.** `--every SECONDS` measures again every SECONDS until it is stopped,
# and `--background` does that detached from the terminal -- every ten minutes unless
# `--every` says otherwise -- with its pid in `var/memory.pid` and what it says in
# `var/memory.log`; `--stop` ends it. It checks for the instance before it detaches,
# so a refusal is said here rather than into the log. A measurement that finds nothing
# is a line in the log and the next one is taken all the same: an instance restarted
# in the night is measured again as soon as it is back.
#
#   ./memory.sh --background     # tonight
#   ./memory.sh --stop           # tomorrow, after reading var/memory.csv

set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
. ./lib.sh

SELF="./$(basename "$0")"
SAMPLER_PID="var/memory.pid"
SAMPLER_LOG="var/memory.log"
DEFAULT_EVERY=600

every=""
background=0
stop=0
passed=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --every)
      if [ "$#" -lt 2 ]; then
        echo "ERROR: --every needs a number of seconds" >&2
        exit 2
      fi
      every="$2"
      shift ;;
    --every=*) every="${1#--every=}" ;;
    --background) background=1 ;;
    --stop) stop=1 ;;
    -h|--help)
      echo "usage: $0 [--every SECONDS] [--background] [--stop]" \
           "[--tls] [--any-instance]" >&2
      echo "  --every SECONDS  measure again every SECONDS, until stopped" >&2
      echo "  --background     do that detached, every ${DEFAULT_EVERY}s" \
           "unless --every says" >&2
      echo "  --stop           stop measuring in the background" >&2
      echo "  --tls, --any-instance  as for ./stop.sh" >&2
      exit 0 ;;
    *) passed+=("$1") ;;
  esac
  shift
done
case "$every" in
  "") ;;
  *[!0-9]*|0) echo "ERROR: --every takes whole seconds above zero, not '${every}'" >&2
              exit 2 ;;
esac
parse_flags "${passed[@]+"${passed[@]}"}"
resolve_bind
require lsof

# The pid in `var/memory.pid` when it is this checkout's sampler, and nothing when it
# is not: a stale file names a number somebody else may have since, and that process
# is never signalled.
sampler() {
  local pid
  pid="$(cat "$SAMPLER_PID" 2>/dev/null || true)"
  case "$pid" in ''|*[!0-9]*) return 1 ;; esac
  kill -0 "$pid" 2>/dev/null || return 1
  case "$(cmd_of "$pid")" in *memory.sh*) ;; *) return 1 ;; esac
  [ "$(cwd_of "$pid")" = "$PWD" ] || return 1
  echo "$pid"
}

if [ "$stop" = 1 ]; then
  if pid="$(sampler)"; then
    kill -TERM "$pid" 2>/dev/null || true
    rm -f "$SAMPLER_PID"
    echo "Stopped measuring in the background (PID ${pid})."
  else
    rm -f "$SAMPLER_PID"
    echo "Nothing is measuring in the background."
  fi
  exit 0
fi

# Name every process in the way, and the flag where a gunicorn is one of them.
refuse() {
  local port="$1" hint=0 pid
  shift
  echo "ERROR: port ${port} is held by another process; refusing to measure it:" >&2
  for pid in "$@"; do
    echo "  $(named_pid "$pid")" >&2
    if is_an_instance "$pid"; then hint=1; fi
  done
  if [ "$hint" = 1 ]; then any_instance_hint; fi
  exit 1
}

# Set `target` and `master` to this checkout's instance, or say why not and exit 1.
find_instance() {
  local strangers existing foreign pid
  target="$(our_port)"
  if [ -z "$target" ]; then
    strangers="$(listeners)"
    if [ -n "$strangers" ]; then
      # shellcheck disable=SC2086  # one word per PID
      refuse "$PORT" $strangers
    fi
    echo "${NAME} is not running" \
         "(looked at :${PORT}${OTHER_PORT:+ and :${OTHER_PORT}});" \
         "nothing to measure." >&2
    exit 1
  fi
  existing="$(listeners_on "$target")"
  foreign=""
  for pid in $existing; do
    if is_a_stranger "$pid"; then foreign="${foreign} ${pid}"; fi
  done
  if [ -n "$foreign" ]; then
    # shellcheck disable=SC2086  # one word per PID
    refuse "$target" $foreign
  fi
  master="$(master_of "$existing")"
}

# Kibibytes resident, empty for a process that is gone -- a worker gunicorn replaced
# between listing it and reading it is not an error, it is simply not there.
rss_of() { ps -o rss= -p "$1" 2>/dev/null | tr -d ' ' || true; }
mib() { awk -v kib="$1" 'BEGIN { printf "%.1f MiB", kib / 1024 }'; }

# One line on the terminal and one row in `var/memory.csv`, for `target` and `master`.
measure() {
  local master_kib workers total_kib parts worker_pids worker_kib pid kib up now row
  local rows="var/memory.csv"
  if ! own_instance "$master"; then
    echo "Measuring an instance this checkout did not start (PID ${master} on" \
         ":${target}), because --any-instance was given."
  fi
  master_kib="$(rss_of "$master")"
  if [ -z "$master_kib" ]; then
    echo "ERROR: PID ${master} on :${target} was gone before it could be measured." >&2
    exit 1
  fi
  workers="$(ps -A -o pid= -o ppid= \
    | awk -v master="$master" '$2 == master { print $1 }')"
  total_kib="$master_kib"
  parts="master ${master} $(mib "$master_kib")"
  worker_pids=""
  worker_kib=""
  for pid in $workers; do
    kib="$(rss_of "$pid")"
    [ -n "$kib" ] || continue
    total_kib=$((total_kib + kib))
    parts="${parts}, worker ${pid} $(mib "$kib")"
    worker_pids="${worker_pids:+${worker_pids} }${pid}"
    worker_kib="${worker_kib:+${worker_kib} }${kib}"
  done
  up="$(ps -o etime= -p "$master" 2>/dev/null | tr -d ' ' || true)"
  now="$(date '+%Y-%m-%d %H:%M:%S')"

  echo "${now} ${NAME} on :${target} — ${parts} — $(mib "$total_kib") resident," \
       "up ${up:-?}"

  mkdir -p var
  if [ ! -s "$rows" ]; then
    echo "time,port,master_pid,master_kib,worker_pids,worker_kib,total_kib,master_up" \
      > "$rows"
  fi
  row="${now},${target},${master},${master_kib},${worker_pids},${worker_kib}"
  echo "${row},${total_kib},${up}" >> "$rows"
}

if [ "$background" = 1 ]; then
  if pid="$(sampler)"; then
    echo "ERROR: already measuring in the background (PID ${pid});" \
         "${SELF} --stop ends it." >&2
    exit 1
  fi
  find_instance
  mkdir -p var
  nohup "$SELF" --every "${every:-$DEFAULT_EVERY}" "${passed[@]+"${passed[@]}"}" \
    < /dev/null >> "$SAMPLER_LOG" 2>&1 &
  echo "$!" > "$SAMPLER_PID"
  echo "Measuring ${NAME} every ${every:-$DEFAULT_EVERY}s in the background (PID $!):" \
       "rows in var/memory.csv, what it says in ${SAMPLER_LOG}; ${SELF} --stop ends it."
  exit 0
fi

if [ -n "$every" ]; then
  while true; do
    ( find_instance; measure ) || true
    sleep "$every"
  done
fi

find_instance
measure
