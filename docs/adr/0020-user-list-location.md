# ADR-0020 — Deployment-supplied user list

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** [ADR-0003 — Configuration & secrets via a `.env` file](0003-config-and-secrets-via-env-file.md)
  (same cwd convention).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
The allowed users are read from **inside the package** today: `app.py` loads the user
list via `importlib.resources.files("little_sister").joinpath("users.yaml")`, and the
file ships as git-ignored package data at `src/little_sister/users.yaml`.

The repo split turns little-sister into a **library** consumed by a
separate **deployment repository**. A deployment must define **its own** users, and the
library must carry **none**. While the file lives inside the package a deployment cannot
supply its user list without editing installed package files. This is the long-standing
goal of moving `users.yaml` out of the package (and dropping its `.gitignore` entry).

## Decision
Read the user list from a **deployment-controlled location**, not from the package.

- **Path resolution:** `LITTLE_SISTER_USERS` (an explicit path) if set; otherwise
  `users.yaml` in the **current working directory**. This mirrors how the process already
  finds `.env` and `config.yaml` (cwd, or `LITTLE_SISTER_CONFIG`) — a deployment's runtime
  files sit together in its working directory ([ADR-0003](0003-config-and-secrets-via-env-file.md)).
- **The package ships `users.example.yaml`** as a template only; it **no longer bundles a
  real `users.yaml`**, and the `src/little_sister/users.yaml` `.gitignore` entry is
  dropped.
- **Fail fast:** a missing resolved file raises at startup, as today.
- The file **format is unchanged** (`username: {firstname, lastname, password, admin}`).

## Consequences
- The deployment repo owns and git-ignores its `users.yaml`; the library carries no real
  users.
- The **library repo's own** runs and tests now supply a `users.yaml` in the working
  directory (git-ignored) or point `LITTLE_SISTER_USERS` at a fixture — the same way they
  already rely on a cwd `.env` / `config.yaml`.
- This changes **only the file's location**, not the auth mechanism. Plaintext passwords
  and the viewer/admin role model are untouched: password hashing stays a Phase 7 item, and
  a **pluggable auth provider** (Keycloak / SSO) is Phase 5 — which would make this static
  file merely the *default* provider.
- One env var and one file-shipping change; no API or template change.

## Alternatives considered
- **Keep it packaged** (status quo) — rejected: a deployment can't own its users without
  editing installed files; it blocks the split.
- **`LITTLE_SISTER_USERS` only, no cwd default** — more explicit but less ergonomic; the
  cwd default matches `.env` / `config.yaml`, so a plain deployment needs no extra env var.
- **Fold users into `.env` or `config.yaml`** — rejected: the user list is structured
  (names, role) and belongs in its own YAML; secrets stay in `.env`
  ([ADR-0003](0003-config-and-secrets-via-env-file.md)).
