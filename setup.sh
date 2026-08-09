#!/usr/bin/env bash
#
# First-time setup: create the git-ignored config the app needs to run —
# config/users/users.yaml (the login list) and .env (a session signing key + JSON-API
# tokens). The user list is an aspect of the configuration directory (ADR-0031);
# .env stays beside it, deliberately outside — it is secrets, not authored config.
# Existing files are kept unless you confirm overwriting. Edit the values after.

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
# Login list (git-ignored). `admin: true` grants the admin-only actions.
# Passwords are plaintext for now — change these before real use.
# Add `avatar: admin` and put admin.svg/png/webp in avatars/ for a custom picture.
admin:
  firstname: "Admin"
  lastname: "User"
  password: "change-me"
  admin: true
EOF
    echo "  wrote $users_path (default login: admin / change-me)"
  fi
fi

if confirm_write .env; then
  # A random session key so it is secure out of the box; the token is a placeholder.
  secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))' 2>/dev/null || echo change-me)"
  cat > .env <<EOF
# Secrets (git-ignored). SECRET_KEY signs sessions; LITTLE_SISTER_API_TOKENS are
# "name=token" pairs the read-only JSON API accepts as bearer tokens.
SECRET_KEY="${secret}"
LITTLE_SISTER_API_TOKENS="client=change-me-token"
EOF
  echo "  wrote .env (random SECRET_KEY; edit LITTLE_SISTER_API_TOKENS)"
fi

echo "Done — review $users_path and .env, then run ./start.sh"
