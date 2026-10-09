#!/usr/bin/env bash
#
# Read the read-only JSON API of a running instance: GET a path with a bearer token
# and print the JSON. Without an argument that is GET /status, the smoke test this
# script began as. The one argument that is not a flag is the path to ask instead,
# with its query, quoted so that the shell leaves `?` and `&` alone:
#
#   ./test_api.sh                                     # /status, the whole tree
#   ./test_api.sh '/series/hosts/alpha?from=now-1h'   # a node's series, one hour
#
# A refusal -- a status of 400 and above -- is printed as the instance said it, since
# what it says is the sentence written for whoever asked: which token, which node,
# which forms a window is read in. Then the path and the status are named, and the
# script ends with 22, curl's own status for a refusal.
#
# The token comes from LITTLE_SISTER_API_TOKENS
# ("name=token,name2=token2", in the environment or .env — the first is used);
# the scheme, HOST and PORT come from lib.sh, matching what the app binds to. The
# script reads the token itself and prints it nowhere, so whoever runs it reads an
# instance without reading its credential.
#
# `--tls` talks to the HTTPS instance, on its own port. The certificate is never
# verified, minted or supplied: this is a process on this machine that the same
# scripts started, so who the far end is was never the question, and a probe that
# failed on trust would report a serving instance as dead (`tls_curl_args` in
# lib.sh). `start.sh` is where a supplied certificate the
# machine does not trust is *reported*.

set -euo pipefail
cd "$(dirname "$0")"
# shellcheck source=lib.sh
. ./lib.sh

# The path is the argument that starts with `/`, and one is asked at a time. A flag
# is lib.sh's to know. What is neither is refused here, where the refusal can say
# what a path looks like: the slip is a path without its first slash.
ask="/status"
asked=0
passed=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h|--help)
      echo "usage: $0 [/path] [--tls]" >&2
      echo "  /path   the path to ask, with its query, quoted for the shell;" \
           "/status without one" >&2
      echo "  --tls   talk to the HTTPS instance (port ${TLS_PORT:-8443})" >&2
      exit 0 ;;
    -*) passed+=("$1") ;;
    /*)
      if [ "$asked" = 1 ]; then
        echo "ERROR: one path at a time, not '${ask}' and '$1'" >&2
        exit 2
      fi
      ask="$1"
      asked=1 ;;
    *)
      echo "ERROR: a path starts with '/', not '$1' (usage: $0 [/path] [--tls])" >&2
      exit 2 ;;
  esac
  shift
done
parse_flags "${passed[@]+"${passed[@]}"}"
resolve_bind
require curl

# Bearer token: from the environment, else parsed out of .env (parsed, not
# sourced, so a stray line in .env can't run).
tokens="${LITTLE_SISTER_API_TOKENS:-}"
if [ -z "$tokens" ] && [ -f .env ]; then
  tokens="$(sed -n 's/^LITTLE_SISTER_API_TOKENS=//p' .env | tail -n1)"
  tokens="${tokens%\"}"; tokens="${tokens#\"}"     # strip optional quotes
  tokens="${tokens%\'}"; tokens="${tokens#\'}"
fi
token="${tokens%%,*}"   # first "name=token" pair
token="${token#*=}"     # -> the token value
if [ -z "$token" ]; then
  echo "ERROR: no API token found — set LITTLE_SISTER_API_TOKENS in .env." >&2
  exit 1
fi

# A 0.0.0.0 bind is reached locally via 127.0.0.1.
connect="$HOST"
[ "$connect" = "0.0.0.0" ] && connect="127.0.0.1"

# Read into an array: `tls_curl_args` echoes words, and a bare string would splice a
# future second flag in as one argument (lib.sh).
declare -a insecure
read -ra insecure <<< "$(tls_curl_args)"
# `--globoff`, so the path is asked as it was written: curl reads brackets and braces
# in a URL as a pattern of its own, and would ask another path or refuse this one.
#
# No `--fail`: it ends on a refusal without printing what the instance said, and the
# flag that prints it too is one an older curl does not have. So curl writes the status
# on a line of its own behind the body, and it is taken off again here. Where the
# instance does not answer at all, curl says so and the script ends with curl's status.
answer="$(curl -sS --max-time 10 --globoff \
  ${insecure[@]+"${insecure[@]}"} \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${token}" \
  --write-out '\n%{http_code}' \
  "${SCHEME}://${connect}:${PORT}${ask}")"
line_end=$'\n'
code="${answer##*"$line_end"}"
printf '%s\n' "${answer%"$line_end"*}"
case "$code" in
  [1-3][0-9][0-9]) ;;
  *)
    echo "ERROR: ${ask} answered ${code}" >&2
    exit 22 ;;
esac
