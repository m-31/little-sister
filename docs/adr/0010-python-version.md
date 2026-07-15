# ADR-0010 — Target Python 3.14

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (single-host threaded
  engine), [ADR-0002](0002-rlock-snapshot-synchronization.md) (locking is
  GIL-independent).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
`requires-python` sat at `>=3.14` with no recorded rationale, and the open
question was whether to keep it or loosen to
3.12+. The code forces nothing that new: the only feature above 3.10 is
`typing.Self` in `status.py` (3.11) — no `match`, no PEP 695 generics, nothing
3.14-only. So the pin is a choice, not a constraint.

The runtime context makes a high floor cheap. The deployment is a single macOS
host we control (ADR-0001), installed and run with **uv**, which manages the
interpreter per environment — we are not bound to whatever Python a distro or
system ships. Development currently runs on **3.14.2**.

## Decision
Target **Python 3.14** as the floor (`requires-python = ">=3.14"`), chosen
deliberately rather than left by inertia.

- **One modern target** keeps the toolchain simple: a single version to lint,
  type-check and test against, with no compatibility shims, and current language
  and standard-library features available by default.
- It keeps the door open to **free-threaded (no-GIL) CPython**, directly relevant
  to an engine of threads sharing one tree. Correctness does **not** depend on it —
  ADR-0002 locks explicitly regardless of the GIL — but the option is there.

uv pins the exact interpreter; the lockfile and the quality gate resolve against
3.14.

## Consequences
- The app won't run on a stock 3.10–3.13 interpreter; deployment provisions Python
  via uv. Supporting arbitrary system Pythons is a non-goal.
- No external contract is affected: federation peers and the planned Swift client
  speak JSON/HTTP, so the runtime version is invisible to clients.
- We can modernize to newer idioms (built-in generics, `X | Y`, PEP 695 type
  parameters, `match`) — a possible later cleanup, not required
  here.
- If an interpreter-version constraint ever appears (e.g. a satellite host stuck
  below 3.14), this decision is revisited in a superseding ADR.

## Alternatives considered
- **Loosen to `>=3.12`** (or `>=3.11`, the true floor). Maximizes portability at no
  code cost today, but buys nothing concrete on a uv-managed host and forgoes newer
  features and the free-threading path.
- **Always track the newest (`>=3.15` when it ships).** Needless churn; bump the
  floor when a feature or fix actually warrants it.
