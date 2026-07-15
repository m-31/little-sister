# ADR-0003 — Configuration & secrets via a `.env` file (phase 1)

- **Status:** Accepted
- **Date:** 2026-06-17
- **Related:** [ADR-0001 — In-process threaded engine](0001-in-process-threaded-engine.md)
- **Register:** [`../decisions.md`](../decisions.md)

## Context
little-sister needs a Flask **`secret_key`** (today hardcoded as `"TODO"` — see
[`../architecture.md`](../architecture.md) §5.2) and, increasingly, **credentials
and tokens** for checks (APIs, remote hosts) and for the planned JSON API
(`../project.md` §2.9). Phase 1 keeps operations simple and has **no secret
store**. `app.py` already carries a placeholder comment about loading a `.env`
file; `.env` is already git-ignored.

## Decision
For phase 1, load configuration **secrets from a single `.env` file** via the
process environment:
- `secret_key` and any check/API credentials come from the environment, not from
  source or version control.
- The `.env` file is provisioned **per host** and never committed (it stays in
  `.gitignore`).
- Required keys are documented (e.g. in the README) so a deployment fails fast if
  one is missing.
- A check or satellite config **references a secret by its environment-variable
  name** (in the check's YAML), and the value is resolved from `.env` at runtime —
  the secret itself never appears in YAML or version control.

## Consequences
- No secrets in code or git; the existing `"TODO"` secret-key smell is removed.
- A missing required secret should **fail fast** at startup (an explicit dev
  fallback is acceptable only under debug).
- Loading mechanism is a small open choice: **`python-dotenv`** (a tiny
  dependency — adding it needs the usual "no framework soup" nod) vs.
  **shell-exported** environment variables. Either is fine;
  `python-dotenv` is the lower-friction default.
- This covers **secrets/config only**. Hashing the user-list passwords and any
  role model are separate and still open.

## Alternatives considered
- **Hardcoded secrets** (today's `"TODO"`) — rejected; insecure and unshippable.
- **A secret manager / OS keychain** (e.g. macOS Keychain) — heavier than phase 1
  warrants; revisit in phase 2 if the deployment grows.
- **Committed config file** — rejected; secrets must not enter version control.

## Phase-2 note
If the deployment grows (multiple hosts, the JSON API, satellite tokens), revisit
with a proper secret manager. The `.env` approach is intended as the simple
phase-1 baseline, consistent with ADR-0001's "no extra services yet".
