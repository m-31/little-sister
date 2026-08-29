#!/usr/bin/env bash
#
# First-time setup: create the git-ignored config the app needs to run —
# config/users/users.yaml (the login list) and .env (a session signing key, the
# system-admin password and JSON-API tokens). The user list is an aspect of the
# configuration directory; .env stays beside it, deliberately outside — it
# is secrets, not authored config. Existing files are kept unless you confirm
# overwriting. Edit the values after.
#
# **The two credentials it writes are opposites, and that is the point.** The login
# in the user list is `viewer` with the placeholder password
# `change-me`: it is meant to be *edited*, so entropy there would only make it harder
# to replace, and it is deliberately **not** an admin. The system-admin password in
# .env is generated: that one is meant to be *read* — it is the account for when the
# identity provider cannot answer, it is registered by `wsgi.py` as a reference to
# this variable, and nobody types it twice a day. After a fresh setup the powerful
# account is the one with real entropy and the everyday one is the weak editable
# placeholder, which is the right way round.

set -euo pipefail
cd "$(dirname "$0")"

# Ask before clobbering an existing file. 0 = (over)write, 1 = keep existing.
confirm_write() {
  local path="$1" reply
  [ -e "$path" ] || return 0
  printf '%s exists — overwrite? [y/N] ' "$path"
  read -r reply || reply="n"
  case "$reply" in
    [yY] | [yY][eE][sS]) return 0 ;;
    *) echo "  kept existing $path"; return 1 ;;
  esac
}

users_path="config/users/users.yaml"
if [ -e config/users.yaml ]; then
  users_path="config/users.yaml"
  echo "  kept existing config/users.yaml (move it to config/users/users.yaml before adding avatars)"
else
  mkdir -p config/users/avatars
  if confirm_write "$users_path"; then
    cat > "$users_path" <<'EOF'
# Login list (git-ignored). `admin: true` grants the admin-only actions, and this
# generated login deliberately does not have it: the admin of a fresh install is the
# system-admin account in .env, behind its own door. Add
# `admin: true` here for an everyday admin once you have edited the password.
# Passwords are plaintext for now — change these before real use.
# Add `avatar: viewer` and put viewer.svg/png/webp in avatars/ for a custom picture.
viewer:
  firstname: "Viewer"
  lastname: "User"
  password: "change-me"
EOF
    echo "  wrote $users_path (default login: viewer / change-me — not an admin)"
  fi
fi

# Random values so the install is secure out of the box. A generator is **required**
# rather than best-effort: this mints the password of the most powerful account there
# is, and the old silent fallback to a constant handed that account a well-known
# password while the line below still called it random. python3 first because the app
# needs it anyway; openssl second because lib.sh already requires it to mint a
# certificate; and a refusal rather than a third guess.
generated() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
  elif command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr -d '=+/' | cut -c1-43
  else
    echo "setup.sh: need python3 or openssl to generate a password — install one" >&2
    return 1
  fi
}

# Overwriting .env is not the cheap answer it looks like, so say what it costs before
# asking. The append below is why answering no is now the better path.
if [ -e .env ]; then
  echo "  .env exists — overwriting mints a new SECRET_KEY (ending every open session)"
  echo "  and replaces LITTLE_SISTER_API_TOKENS; keeping it adds only what is missing."
fi
if confirm_write .env; then
  secret="$(generated)"
  admin_password="$(generated)"
  cat > .env <<EOF
# Secrets (git-ignored). SECRET_KEY signs sessions;
# LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD is the system-admin account's password, which
# wsgi.py registers by *reference* to this name rather than by value;
# LITTLE_SISTER_API_TOKENS are "name=token" pairs the read-only JSON API accepts as
# bearer tokens.
SECRET_KEY="${secret}"
LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD="${admin_password}"
LITTLE_SISTER_API_TOKENS="client=change-me-token"
EOF
  echo "  wrote .env (random SECRET_KEY and system-admin password; edit"
  echo "  LITTLE_SISTER_API_TOKENS)"
  echo "  the admin of this install is 'admin' at /login/system-admin —"
  echo "  its password is LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD in .env"
elif ! grep -q '^LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD=' .env; then
  # The upgrade path, and the only one every existing installation takes: an .env
  # written before the system-admin account existed has no line for it, so that door
  # is registered and shut — a state discovered on the morning it is needed. Appending
  # the one missing key is additive and reversible, where rewriting the file would end
  # every open session and take the deployment's own API tokens with it.
  admin_password="$(generated)"
  {
    echo ""
    echo "# Added by setup.sh: the system-admin account's password, which wsgi.py"
    echo "# registers by *reference* to this name rather than by value."
    echo "LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD=\"${admin_password}\""
  } >> .env
  echo "  added LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD to the existing .env"
  echo "  the admin of this install is 'admin' at /login/system-admin"
fi

echo "Done — review $users_path and .env, then run ./start.sh"
