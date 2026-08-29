#!/usr/bin/env bash
#
# Smoke-test the read-only JSON API of a running instance: GET /status with a
# bearer token and print the JSON. The token comes from LITTLE_SISTER_API_TOKENS
# ("name=token,name2=token2", in the environment or .env — the first is used);
# the scheme, HOST and PORT come from lib.sh, matching what the app binds to.
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
parse_flags "$@"
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
curl -fsS --max-time 10 \
  ${insecure[@]+"${insecure[@]}"} \
  -H "Accept: application/json" \
  -H "Authorization: Bearer ${token}" \
  "${SCHEME}://${connect}:${PORT}/status"
echo
