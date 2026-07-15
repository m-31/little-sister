# ADR-0004 — Status aggregation (roll-up) semantics

- **Status:** Accepted
- **Date:** 2026-06-17
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (engine),
  [ADR-0002](0002-rlock-snapshot-synchronization.md) (synchronization). Fixes the
  bug in [`../architecture.md`](../architecture.md) §4.3.
- **Register:** [`../decisions.md`](../decisions.md)

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

**Implemented (`tree.py`):** a node carries a sticky `maintenance` flag. While
set, `StatusTree.upsert` keeps the admin-set `MAINTENANCE` code (only the check
time is refreshed) — so the engine cannot override it. `set_maintenance(path,
reason)` / `clear_maintenance(path)` (admin-only, via `POST /maintenance`) flip
the flag and record events; clearing reverts to `UNDEFINED` until the next check.

## Consequences
- Replaces the buggy guard/return in `get_status_code()`; expand the unit tests
  (including *MAINTENANCE cancels subtree* and *UNDEFINED ignored*). A phase-1
  task.
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
