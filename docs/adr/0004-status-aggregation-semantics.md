# ADR-0004 — Status aggregation (roll-up) semantics

> **Superseded 2026-08-02 by three records**, as
> [ADR-0032](0032-status-contribution-boundary.md) promised when maintenance became a
> real contribution rule. This one had grown three unrelated decisions under one
> title, which is why its `MAINTENANCE` half could sit in contradiction with its own
> roll-up half for months without anyone noticing:
>
> - [ADR-0039](0039-status-rollup-semantics.md) — the roll-up (§1–4 and *Explicit
>   node status*), **plus an answer** to the edge case this record left open below: a
>   node whose children are all *silenced* reads `MAINTENANCE`, one whose children
>   merely have not reported stays `UNDEFINED`.
> - [ADR-0040](0040-what-a-failing-check-becomes.md) — *A check that fails*, verbatim
>   in substance.
> - [ADR-0041](0041-maintenance-is-a-contribution-rule.md) — §3's `MAINTENANCE` and
>   the *Implemented (`tree.py`)* note below, both **replaced**: a pin is no longer
>   written into the node and no longer sticky against `upsert`, and clearing no
>   longer reverts to `UNDEFINED`.
>
> Kept for the history. Everything below describes the design as it stood; where it
> disagrees with the three records, they win.

- **Status:** Superseded by [ADR-0039](0039-status-rollup-semantics.md),
  [ADR-0040](0040-what-a-failing-check-becomes.md) and
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md)
- **Date:** 2026-06-17
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (engine),
  [ADR-0002](0002-rlock-snapshot-synchronization.md) (synchronization). Fixes the
  bug in [`../architecture.md`](../architecture.md) §4.3.
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-07-29):** the decision now states what a **failing check** becomes —
> see *A check that fails* below. `engine.py` has cited this ADR for "any failure
> becomes an ERROR" since it was written, but the ADR only covered roll-up; the
> citation now has something to point at. The same section records the stack trace on
> the node (`config.yaml`'s `stacktrace`).

## Context
A parent's status is derived from its own state and its children
([`../project.md`](../project.md) §2.3). The first-draft `get_status_code()` is
buggy — it can return the string `"warn"` and can downgrade an `ERROR`
(`../architecture.md` §4.3) — and the treatment of `MAINTENANCE` and `UNDEFINED`
was undecided. Checks normally update **leaves**, but some updaters (notably
satellite checks, `../project.md` §2.9) replace a whole **branch**.

## Decision
Effective status of a node, computed bottom-up:

1. **Severity order** among *counted* statuses: `ERROR > WARN > OK`. A node is
   `OK` only if every counted child is `OK`.
2. **`UNDEFINED`** means "not reported yet" and occurs only at a **leaf**. It is
   **ignored** when a parent accumulates — it never makes a parent `UNDEFINED`.
3. **`MAINTENANCE`** may be set by an **administrator on any node**. It **cancels
   its whole subtree** (warnings/errors beneath it do not propagate) and the
   maintenance node itself is **ignored** by its parent's accumulation.
4. `get_status_code()` must **always return a `StatusCode`** (never a string) and
   must **never downgrade** — e.g. an `ERROR` node with a `WARN` child stays
   `ERROR`.

### Explicit (non-derived) node status
Normally a check updates a **leaf**. An updater that owns a whole **branch** (e.g.
a satellite check) may set that branch node's status explicitly:

- On failure it sets the node to **`ERROR`** and **drops its children** (the
  subtree is no longer known).
- It **must clear** that explicit status — replacing it with fresh data — once it
  can update the branch again. Whatever can stamp an explicit branch status owns
  clearing it on recovery.

(An administrator's `MAINTENANCE` is the other explicit, non-derived status; same
principle.)

### A check that fails
A check is not trusted to fail gracefully, so the engine decides what a failure *means*
in status terms. **Any** exception out of `run()`, a timeout, or a `run()` that returns
something other than a `CheckResult` becomes **`ERROR`** on the check's own node — never
a skipped update, and never a stale OK left in place. "Unknown" is not an option here:
`UNDEFINED` means *not reported yet* (§2), and a check that raised **has** reported —
it reported that it cannot tell us, which is an operational problem.

The reason is `check error: <message>`, folded in with `plain()`. An exception message
routinely carries external text — a captured line, a path, an API error body — so it is
escaped like any other untrusted string
([ADR-0018](0018-markdown-rendering.md)); unescaped, a message could render as
formatting or a link on the dashboard.

Unless `config.yaml` sets **`stacktrace: false`**, a **second reason** carries the
innermost frames of the traceback (`engine.TRACEBACK_FRAMES`, 5) as a `code()` block —
verbatim and inert, chained causes included, so a `raise X from Y` shows both. **On by
default**: this is an operator dashboard, and a deployment whose log is awkward to
reach — a container, a managed cloud runtime — should not have to go find the log for
the one thing that explains the failure. The full traceback goes to the log either way
(`logger.exception`). The switch is **global rather than per-check** on purpose: the
check that raises unexpectedly is precisely the one nobody thought to flag in advance,
so a per-check opt-in would be off exactly when it was needed.

The trace is an extra **reason**, not a new field on `Status`: `reason_cap`
([ADR-0024](0024-dashboard-layout.md)) then clamps it on the dashboard, the detail page
shows it in full, and the JSON envelope ([ADR-0008](0008-json-output-api.md)) carries it
with no schema change.

A check whose **secret references** failed to resolve at construction is a different
case: it is pinned to `ERROR` without ever running, and never retried until restart
([ADR-0023](0023-secret-references.md)).

**Implemented (`tree.py`):** a node carries a sticky `maintenance` flag. While
set, `StatusTree.upsert` keeps the admin-set `MAINTENANCE` code (only the check
time is refreshed) — so the engine cannot override it. `set_maintenance(path,
reason)` / `clear_maintenance(path)` (admin-only, via `POST /maintenance`) flip
the flag and record events; clearing reverts to `UNDEFINED` until the next check.

## Consequences
- Replaces the buggy guard/return in `get_status_code()`; expand the unit tests
  (including *MAINTENANCE cancels subtree* and *UNDEFINED ignored*). A task for
  the initial build.
- A maintenance node makes its whole subtree **invisible to ancestors** — intended,
  so planned downtime doesn't redden the top.
- **Edge case to confirm:** a node whose children are *all* ignored
  (`MAINTENANCE`/`UNDEFINED`) and that has no explicit code — proposed default: it
  reports its own explicit code, defaulting to `UNDEFINED`.

## Alternatives considered
- **Treat `UNDEFINED`/`MAINTENANCE` as severities** in the worst-of comparison —
  rejected; "unknown" or "planned downtime" would mask or fake real problems.
- **Forbid explicit inner-node status** (checks only ever touch leaves) — doesn't
  survive contact with satellites, whose branch can fail as a unit.
