# shellcheck shell=bash
# shellcheck disable=SC2034  # config values below are used by the sourcing scripts
#
# Shared helpers for start.sh / stop.sh / test_api.sh.
#
# Source this *after* `cd`-ing to the repo root (every script does `cd
# "$(dirname "$0")"` first). It defines the bind target, the way we recognize
# our own gunicorn, and the graceful-stop routine -- so start and stop always
# agree on what "our process" means and never touch an unrelated service.
#
# Sourcing does not decide the bind target, because a flag can still change it:
# each script does `. ./lib.sh`, then `parse_flags "$@"`, then `resolve_bind`.
#
# **This file is byte-identical in every installation** — the library and both
# deployments — and is compared on every commit (little-sister `release/family.toml`).
# What is true of one installation and not the others is in `instance.sh` beside it,
# which is the only one of these scripts that differs.

# shellcheck source=instance.sh
. ./instance.sh

HOST="${LITTLE_SISTER_HOST:-0.0.0.0}"
LOG="var/gunicorn.log"
# Absolute, so that the checkout an instance belongs to is legible in `ps` output and
# in the refusals below. It is **not** how ownership is decided -- see `own_instance`,
# which asks the process rather than its arguments -- and it is deliberately not read
# out of the file either: these scripts delete that file themselves, and a pid in a
# stale one is a number that may since have been reused (macOS wraps at 99999).
PID_FILE="$PWD/var/gunicorn.pid"

# Whether this run may act on an instance this checkout did not start.
#
# A per-run flag with **no environment variable beside it**, unlike `LITTLE_SISTER_TLS`:
# the value of the refusal is that a person read it and answered, and a variable
# exported three days ago answers nothing. Assigned rather than defaulted, so an
# exported one cannot decide it either.
ANY_INSTANCE=0

# The grace: how long gunicorn gives a request still running at the TERM before its
# master KILLs the worker. gunicorn's own default, written down once here because three
# things are bounded by it: `start.sh` hands it to gunicorn as `--graceful-timeout`,
# `stop_instance` below waits it out, and a container that runs the instance names its
# stop timeout beside it. An installation raises it in `instance.sh` or in the
# environment, the way it raises WORKER_TIMEOUT.
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-30}"
# What the master needs after its own KILL to reap its worker and exit: `stop_instance`
# waits the grace and this, and then KILLs whatever is left.
STOP_MARGIN=5

# --- TLS, and the bind target it decides ------------------------------------
#
# `--tls` serves HTTPS instead of HTTP, and the port moves with the scheme: the
# same number under two schemes is one address wearing two costumes, and a
# bookmark, a `curl` in somebody's notes or a browser that already knows that
# port reaches for the wrong one. Two numbers make that mistake impossible
# instead of merely recoverable.
#
# The flag is how you ask for it once; the environment variable is how a script
# somebody else started the instance from is told about it, and how `stop.sh`
# and `test_api.sh` find an instance they did not start.
TLS_REQUESTED="${LITTLE_SISTER_TLS:-${TLS:-0}}"

# A certificate this installation supplies -- an internal CA's, or one from a
# public authority. Both halves or neither: half a pair is a misconfiguration
# and is refused rather than silently minting something else. Left unset,
# `--tls` mints a throwaway (see `mint_certificate`).
TLS_CERT="${LITTLE_SISTER_TLS_CERT:-${TLS_CERT:-}}"
TLS_KEY="${LITTLE_SISTER_TLS_KEY:-${TLS_KEY:-}}"

# Where a minted pair lives: beside the log and the pidfile, in the gitignored
# runtime directory, overwritten at every start and kept by nobody.
TLS_DIR="var/tls"
TLS_MINTED_CERT="${TLS_DIR}/cert.pem"
TLS_MINTED_KEY="${TLS_DIR}/key.pem"

# Read the flags every one of these scripts accepts. Called *before*
# `resolve_bind`, because `--tls` is what it resolves against.
parse_flags() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --tls) TLS_REQUESTED=1 ;;
      --any-instance) ANY_INSTANCE=1 ;;
      -h|--help)
        echo "usage: $0 [--tls] [--any-instance]" >&2
        echo "  --tls            talk to the HTTPS instance (port ${TLS_PORT:-8443})" >&2
        echo "  --any-instance   act on a gunicorn this checkout did not start" >&2
        exit 0 ;;
      *)
        echo "ERROR: unknown option '$1' (usage: $0 [--tls] [--any-instance])" >&2
        exit 2 ;;
    esac
    shift
  done
}

# Fix TLS / SCHEME / PORT for this run. Split out of sourcing so a flag can
# still change the answer; every script calls it once, straight after
# `parse_flags`.
#
# The port comes from `instance.sh`, because which port is free is exactly the
# kind of thing that is true of one installation and not the others — a machine
# already serving something on the number you wanted needs another one, and a
# local edit *here* would be a difference no comparison could see. The literal
# fallbacks keep an installation whose `instance.sh` predates either line
# working unchanged. An explicit LITTLE_SISTER_PORT wins under either scheme:
# somebody naming a port has already answered the question.
resolve_bind() {
  # Snapshot the plain default *before* PORT is overwritten with this run's answer,
  # and only once: `PORT` is both the input from `instance.sh` and the output, so a
  # second call would otherwise read a TLS run's 8443 back as the plain port and
  # report the two schemes as one. Every script calls this once; being idempotent is
  # cheaper than relying on that.
  PLAIN_PORT="${PLAIN_PORT:-${PORT:-8888}}"
  TLS_PORT="${TLS_PORT:-8443}"
  case "$TLS_REQUESTED" in
    1|y|yes|true|on|Y|YES|TRUE|ON) TLS=1 ;;
    *) TLS=0 ;;
  esac
  if [ "$TLS" = 1 ]; then
    SCHEME="https"; PORT="$TLS_PORT";   OTHER_PORT="$PLAIN_PORT"
  else
    SCHEME="http";  PORT="$PLAIN_PORT"; OTHER_PORT="$TLS_PORT"
  fi
  # An explicit port answers the question for this run under either scheme, so
  # there is then only one number in play and no second place to look.
  if [ -n "${LITTLE_SISTER_PORT:-}" ]; then
    PORT="$LITTLE_SISTER_PORT"
    OTHER_PORT=""
  fi
}

# What `curl` needs to talk to this instance, as words to splice into a command.
#
# **These scripts do not verify the certificate, and that is a decision rather
# than a shortcut**. Every one of them is talking to a process on this
# machine, over the loopback interface, that this script started seconds ago and
# holds the pid of; who the far end is was never in question, and a certificate
# cannot answer anything that is. What verification *would* add is a way for a
# perfectly healthy instance to be reported as dead because the certificate it
# serves is not in this machine's trust store — which is a fact worth knowing and
# is said out loud instead, by `certificate_verifies` below.
#
# This is not the rule `little_sister.fetch` keeps, which has no way to switch
# verification off. That one is about reading **somebody else's** service, where
# the certificate is the only thing saying whose it is.
#
# It echoes **words**, and every caller reads them into an array with `read -ra`
# before splicing them into a command. Passing the string itself through
# `${x:+"$x"}` works only while there is exactly one word in it: a second flag added
# here would arrive as a single argument with a space inside it, and `curl` would
# reject an option nobody typed.
tls_curl_args() {
  if [ "$TLS" = 1 ]; then
    printf '%s' "--insecure"
  fi
}

# Whether this machine can verify the certificate the instance is serving.
#
# Asked once, after a successful start, and only about a certificate the
# installation supplied: a minted one is unverifiable by construction, so asking
# would be theatre. A `no` costs nothing today and is exactly what a browser is
# about to complain about, which is why it is worth a line.
certificate_verifies() {
  [ "$TLS" = 1 ] && [ -n "$TLS_CERT" ] || return 0
  curl -s -o /dev/null -m "$PROBE_TIMEOUT" \
       "${SCHEME}://$(probe_host):${PORT}${PROBE_PATH}" >/dev/null 2>&1
}

# Put a certificate and key where gunicorn can read them, and echo the two paths,
# **one per line** -- a certificate path is a path somebody chose, and a space in one
# is ordinary where a newline is pathological, so the separator has to be the
# character that cannot appear by accident. Splitting one space-separated line on
# `$IFS` put the tail of such a path into the key instead, and gunicorn then reported
# a missing file for a pair that was on disk all along.
#
# A supplied pair is used as it is. Otherwise a fresh self-signed certificate is
# minted for this run and overwritten by the next one: it is never installed
# anywhere, never trusted by anything, and outlives nothing -- so it has no name
# worth choosing and no lifetime worth managing. It is *overwritten* rather than
# removed at boot because gunicorn builds its SSL context per accepted
# connection and reads both files each time, so they have to stay readable for
# as long as the process serves.
mint_certificate() {
  if [ -n "$TLS_CERT" ] || [ -n "$TLS_KEY" ]; then
    if [ -z "$TLS_CERT" ] || [ -z "$TLS_KEY" ]; then
      echo "ERROR: set both TLS_CERT and TLS_KEY, or neither." >&2
      return 1
    fi
    local path
    for path in "$TLS_CERT" "$TLS_KEY"; do
      [ -r "$path" ] || { echo "ERROR: cannot read '$path'." >&2; return 1; }
    done
    printf '%s\n%s\n' "$TLS_CERT" "$TLS_KEY"
    return 0
  fi

  require openssl
  # `openssl` writes the private key `0600` itself, whatever the umask -- measured,
  # not assumed. The umask is here for the rest of what the command drops: the
  # *certificate*, which would otherwise be `0644`, and the directory holding them,
  # which is why `mkdir` is inside the subshell and not above it. So it is a floor
  # under the whole directory rather than the thing protecting the key.
  #
  # **openssl's own stderr is kept and printed on failure.** The one failure this was
  # expected to have -- the LibreSSL macOS ships refusing `-newkey ec -pkeyopt
  # ec_paramgen_curve:P-384` -- is exactly the one where openssl's message *is* the
  # diagnosis, and a bare "could not mint a certificate" would throw it away.
  local reason
  reason="$(
    ( umask 077
      mkdir -p "$TLS_DIR" &&
      openssl req -x509 -nodes -newkey ec -pkeyopt ec_paramgen_curve:P-384 \
              -keyout "$TLS_MINTED_KEY" -out "$TLS_MINTED_CERT" \
              -days 200 -subj "/CN=${NAME}"
    ) 2>&1 >/dev/null
  )" || {
    echo "ERROR: could not mint a certificate with openssl." >&2
    [ -n "$reason" ] && printf '  %s\n' "$reason" >&2
    return 1
  }
  printf '%s\n%s\n' "$TLS_MINTED_CERT" "$TLS_MINTED_KEY"
}

require() {
  command -v "$1" >/dev/null 2>&1 ||
    { echo "ERROR: required command '$1' not found." >&2; exit 1; }
}

# Resolve the user-list document exactly as the built-in `users` aspect does.
# LITTLE_SISTER_CONFIG_DIR is a path-list: the first root declaring
# the aspect wins, and that aspect may be a flat users.yaml/users.yml file or a
# users/ directory containing exactly one users.yaml/users.yml document. One rule,
# the same one the library applies — a deployment pinning one exact file names a
# root that carries only that file, first.
resolve_users_document() {
  # The retired override. Refused, not ignored, and refused
  # here so ./start.sh stops before it forks a worker onto a different user list.
  if [ -n "${LITTLE_SISTER_USERS:-}" ]; then
    echo "ERROR: LITTLE_SISTER_USERS is set, but it is no longer read — move that file into a configuration root, name the root first in LITTLE_SISTER_CONFIG_DIR, then unset it." >&2
    return 1
  fi

  local spec="${LITTLE_SISTER_CONFIG_DIR:-config}"
  local raw_root root
  local -a raw_roots=() roots=() forms=() documents=()
  local IFS=:
  read -r -a raw_roots <<< "$spec"
  for raw_root in "${raw_roots[@]}"; do
    root="${raw_root#"${raw_root%%[![:space:]]*}"}"
    root="${root%"${root##*[![:space:]]}"}"
    [ -n "$root" ] && roots+=("$root")
  done
  [ "${#roots[@]}" -gt 0 ] || roots=(config)

  for root in "${roots[@]}"; do
    if [ ! -d "$root" ]; then
      echo "ERROR: configuration root '$root' not found." >&2
      return 1
    fi

    forms=()
    [ -f "$root/users.yaml" ] && forms+=("$root/users.yaml")
    [ -f "$root/users.yml" ] && forms+=("$root/users.yml")
    [ -d "$root/users" ] && forms+=("$root/users")
    if [ "${#forms[@]}" -gt 1 ]; then
      echo "ERROR: the users aspect occurs more than once in '$root' — keep only users.yaml, users.yml, or users/." >&2
      return 1
    fi
    [ "${#forms[@]}" -eq 1 ] || continue

    if [ -f "${forms[0]}" ]; then
      printf '%s\n' "${forms[0]}"
      return 0
    fi

    documents=()
    [ -f "${forms[0]}/users.yaml" ] && documents+=("${forms[0]}/users.yaml")
    [ -f "${forms[0]}/users.yml" ] && documents+=("${forms[0]}/users.yml")
    if [ "${#documents[@]}" -eq 1 ]; then
      printf '%s\n' "${documents[0]}"
      return 0
    fi
    if [ "${#documents[@]}" -eq 0 ]; then
      echo "ERROR: users directory '${forms[0]}' needs users.yaml or users.yml." >&2
    else
      echo "ERROR: users directory '${forms[0]}' contains both users.yaml and users.yml — keep one." >&2
    fi
    return 1
  done

  echo "ERROR: no users aspect found in the configured root(s)." >&2
  return 1
}

# PIDs currently LISTENing on a port (a gunicorn master and its workers all
# share the one listening socket, so this may return more than one PID).
listeners_on() { lsof -ti "tcp:$1" -sTCP:LISTEN 2>/dev/null | sort -u || true; }

# The same, for the port this run resolved to.
listeners() { listeners_on "$PORT"; }

# Which port *this checkout's* instance is serving on -- this run's, or the one the
# other scheme would have used. Empty when nothing of ours is listening on either.
#
# **A checkout serves one instance**. It has one pidfile and one
# log, which is a statement about how many instances there are, and the second port
# exists so the two schemes cannot be confused for one address -- not so that a
# checkout can serve twice. Looking at one port only made that statement quietly
# false: `./start.sh --tls` beside a running plain instance left both alive, sharing
# the pidfile and truncating each other's log, and `./stop.sh` reported a running
# instance as absent and then cleared its pidfile.
#
# Always returns 0, echoing nothing when there is nothing: the callers assign this in
# a `$(...)` under `set -e`, where a non-zero return would abort the script instead.
our_port() {
  local port pid
  for port in "$PORT" ${OTHER_PORT:+"$OTHER_PORT"}; do
    for pid in $(listeners_on "$port"); do
      if is_ours "$pid"; then echo "$port"; return 0; fi
    done
  done
  return 0
}

# --- Readiness ---------------------------------------------------------------
# A listening port does *not* mean the app is up. The gunicorn master binds and
# listens *before* it forks the worker that imports the WSGI app, so a worker
# that dies on an import error still leaves a listening socket behind for the
# second or two the master needs to give up. "Up" therefore means the app
# *answered an HTTP request*, which only a booted worker can do.

# `/health` is the machine-readable liveness answer and needs no
# session. It replaced `/login`, which was a login page standing in for one.
PROBE_PATH="${LITTLE_SISTER_PROBE_PATH:-/health}"
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
  local -a insecure
  read -ra insecure <<< "$(tls_curl_args)"
  code="$(curl -s -o /dev/null -m "$PROBE_TIMEOUT" -w '%{http_code}' \
            ${insecure[@]+"${insecure[@]}"} \
            "${SCHEME}://$(probe_host):${PORT}${PROBE_PATH}" 2>/dev/null)" || return 1
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
# The line is written by the server's start -- gunicorn's `post_worker_init`, right
# after the worker's import and before it serves anything -- so checking after a
# successful probe cannot race it. A deliberate LITTLE_SISTER_ENGINE=0 logs "engine
# disabled via …" instead, so it does not match here.
ENGINE_ERROR_MARK="engine not started:"
engine_error_in_log() {
  # `|| true` because no match is the healthy case, and `set -o pipefail` in the
  # caller would otherwise turn grep's "found nothing" into a failed assignment.
  grep -h "$ENGINE_ERROR_MARK" "$LOG" 2>/dev/null |
    tail -n 1 | sed "s/.*${ENGINE_ERROR_MARK} *//" || true
}

# Full command line of a PID (empty if the process is already gone).
#
# `-ww` because BSD `ps` -- macOS's -- truncates to the terminal width, and to 80
# columns when its output is a pipe, which every use here is. A gunicorn command line
# is longer than that, so without it the tail is silently missing: this is printed in
# the refusals, and an error message that cuts off mid-path helps nobody.
cmd_of() { ps -ww -p "$1" -o command= 2>/dev/null || true; }

# The working directory of a PID, empty when it cannot be read.
cwd_of() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1 || true
}

# Is this PID the instance **this checkout** started?
#
# A gunicorn whose **working directory is this checkout**. It used to be matched on
# `$APP`, which is precise only while every installation serves a different WSGI
# target -- and a deployment and the library can both serve `wsgi:app`, leaving two
# checkouts on one port indistinguishable, each ready to stop the other's instance.
#
# The working directory rather than anything in the command line, because a command
# line is not a property of the process so much as a string that can stop being true
# of it. `ps` truncates it (see `cmd_of`), and gunicorn *rewrites* it to
# "gunicorn: master [$APP]" when `setproctitle` is installed -- which no version of
# this repository installs today, and any deployment may. Either one turns an argv
# match into a silent "not running" for an instance that is serving perfectly. A cwd
# survives both, is read from the live process, and identifies an instance started
# from this checkout by any means rather than only by these scripts.
#
# An unreadable cwd answers empty, which is not `$PWD`, so a process we cannot see
# into is not ours -- the safe direction.
own_instance() {
  if ! is_an_instance "$1"; then
    return 1
  fi
  [ "$(cwd_of "$1")" = "$PWD" ]
}

# Is this PID a gunicorn at all -- i.e. something `--any-instance` would let us act
# on? Used to decide whether a refusal should mention that the flag exists.
is_an_instance() {
  case "$(cmd_of "$1")" in
    *gunicorn*) return 0 ;;
    *) return 1 ;;
  esac
}

# The one sentence that says the escape hatch exists. Printed only when the process in
# the way is a gunicorn: for anything else the flag would not help, and naming it there
# would only tempt somebody into trying it on a database.
any_instance_hint() {
  echo "  (that is a gunicorn this checkout did not start — re-run with" >&2
  echo "   --any-instance to act on it anyway)" >&2
}

# May this run act on this PID? This checkout's own instance always; any gunicorn
# when `--any-instance` says so. Never anything else: a refusal naming a database or
# somebody's dev server is a refusal worth keeping, and no flag relaxes it.
is_ours() {
  if own_instance "$1"; then
    return 0
  fi
  if [ "$ANY_INSTANCE" = 1 ] && is_an_instance "$1"; then
    return 0
  fi
  return 1
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

# The processes of an instance: its master, and every process the master forked -- its
# workers.
instance_pids() {
  echo "$1"
  ps -A -o pid= -o ppid= 2>/dev/null | awk -v master="$1" '$2 == master { print $1 }'
}

# Stop an instance, and wait for **every process of it**.
#
# The processes are read *before* the TERM, while the worker still listens: a worker
# leaves its loop at the TERM and closes its sockets, and from then on nothing on the
# port says it is there -- which is how a worker waiting on a check outlived a stop that
# watched its master alone, and a start came up beside it. The TERM goes to the master,
# whose own graceful stop gives a request still running the grace and then KILLs the
# worker; this waits on all of them for the grace and STOP_MARGIN, and at that bound
# KILLs what is left and names each one.
stop_instance() {
  local master="$1" pids pid left steps
  steps=$(( (GRACEFUL_TIMEOUT + STOP_MARGIN) * 5 ))   # 0.2 s each
  pids="$(instance_pids "$master" | tr '\n' ' ')"
  echo "Stopping running little-sister (PID ${master})..."
  kill -TERM "$master" 2>/dev/null || true
  while :; do
    left=""
    for pid in $pids; do
      if kill -0 "$pid" 2>/dev/null; then left="${left} ${pid}"; fi
    done
    if [ -z "$left" ]; then echo "Stopped."; return 0; fi
    if [ "$steps" -le 0 ]; then break; fi
    steps=$(( steps - 1 ))
    sleep 0.2
  done
  echo "Still running ${GRACEFUL_TIMEOUT}s and ${STOP_MARGIN}s after the TERM;" \
       "sending KILL to:" >&2
  for pid in $left; do
    echo "  PID ${pid}: $(cmd_of "$pid")" >&2
    kill -KILL "$pid" 2>/dev/null || true
  done
  sleep 0.5
}
