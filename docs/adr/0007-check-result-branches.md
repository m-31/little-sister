# ADR-0007 — Checks may report a branch (recursive `CheckResult`)

- **Status:** Accepted
- **Date:** 2026-06-24
- **Related:** [ADR-0002](0002-rlock-snapshot-synchronization.md) (the tree owns
  state), [ADR-0004](0004-status-aggregation-semantics.md) (roll-up),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (freshness).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
`project.md` §2.5 says a check normally produces one leaf node but **may produce a
whole branch** — a host with `disk` / `memory` / `cpu` children, or a satellite
grafting a remote subtree (§2.9). The first concrete need is the `ssh` system
check. Until now a run produced a flat `CheckResult` (code + reason) and the
engine did a single `upsert(check.full_path, …)`, so a branch had no way through.

The obvious shortcut — let `run()` return a `Status` (it already has `children`
and roll-up) — conflates two different things. `Status` is the **live, mutable,
lock-guarded entity** in the one shared tree: it owns identity (`path`/`name`,
enforced by `add_child`), the observation `timestamp`, the sticky `maintenance`
override, inherited metadata, and event-on-change. A worker thread handing back a
detached `Status` would carry fields it has no business setting and would have to
be reconciled into the real node under the lock anyway (ADR-0002).

## Decision
A check returns a **value**, not the entity — and that value is allowed to be a
small **tree**.

1. **`CheckResult` becomes recursive.** It gains `name`, `description` and
   `children: tuple[CheckResult, …]`. Most checks still return a single leaf
   (`CheckResult(code, reason)`, unchanged). A child must have a `name`
   (validated at construction); the root's `name` is ignored — the engine places
   the root at `check.full_path`.
2. **The engine walks the tree.** `Engine._store` upserts the root at
   `check.full_path` (inheriting the check's `description`), then recurses,
   writing each child at `parent.full_path.<name>` with the child's own
   `description`. Every node inherits the check's `frequency`, so freshness
   (ADR-0005) applies uniformly. The host node is OK once reachable; the worst
   aspect rolls up to it (ADR-0004).
3. **The boundary holds.** Identity, observation time, maintenance and
   event-on-change stay the **tree's** concern, set under the lock — exactly as
   for a leaf. The result remains a pure, immutable description of "what I
   observed", mirroring the status tree's shape without being one.

## Consequences
- A single check (one SSH connection) can report several aspects, each its own
  colour-coded node with its own reason — and roll-up/staleness/maintenance work
  on them for free.
- `CheckResult` stays backward compatible: `code`/`reason` are still the first two
  fields and every existing call site is untouched.
- The same shape is what a future satellite check will produce by parsing remote
  JSON into a result tree (§2.9) — no second mechanism needed.
- **Children are not pruned.** If a later run reports fewer children (e.g. the
  host is unreachable, so the `host-metrics` check returns just an `ERROR` root), the
  previously written aspect nodes remain until they go stale (ADR-0005); the root
  `ERROR` dominates the roll-up meanwhile. A tree-level prune/delete is deferred
  until a check needs it.

## Alternatives considered
- **Return a `Status` subtree** — reuse the entity. Rejected: it drags
  identity/time/maintenance/mutability into a return value and still needs a
  graft-into-tree merge under the lock.
- **A separate `ChildResult` type** — a parallel "Status-lite". Rejected as
  duplication; one recursive value is simpler and matches the tree's shape.
- **One node, multi-line reason** (percentages crammed into one leaf's text) —
  smallest change, but the aspects aren't separate nodes, so they can't be
  coloured, rolled up, or put into maintenance individually.
