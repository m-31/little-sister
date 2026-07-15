# ADR-0002 — Synchronize shared state with one RLock and copy-on-read snapshots

- **Status:** Accepted
- **Date:** 2026-06-17
- **Related:** [ADR-0001 — In-process threaded engine](0001-in-process-threaded-engine.md)
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Under [ADR-0001](0001-in-process-threaded-engine.md), multiple check threads
mutate the status tree and append events while web threads read the tree to
render. Compound operations — updating a subtree, walking the tree — are **not
atomic** under the GIL. Concurrent mutation during a read can cause torn reads or
`RuntimeError: dictionary changed size during iteration`.

## Decision
- Guard the shared **status tree** and the **event log** with a single
  `threading.RLock`.
- **Mutations** (a check writing its node; appending an event; change detection)
  take the lock.
- **Reads for rendering** take the lock only long enough to build a lightweight
  **snapshot** (a copy of the branch being shown / a slice of events), then
  release the lock and render the snapshot **outside** it.

## Rationale
- One lock for all shared state is the simplest thing that is correct; `RLock`
  lets a locked method call another locked method without self-deadlock.
- Copy-on-read keeps request latency **independent of check activity** and avoids
  holding the lock across template rendering.

## Consequences
- Snapshot cost is O(size of the shown branch) — fine for expected tree sizes.
- **Change detection** (old code vs new code, to emit an event) must happen
  **under the lock**, so two threads can't interleave and miss or duplicate a
  transition.
- If trees grow large or lock contention bites, revisit with finer-grained locks
  or an immutable copy-on-write tree (atomic root swap) — see Alternatives.

## Alternatives considered
- **Rely on the GIL alone** — incorrect for compound operations; rejected.
- **Per-node locks** — more concurrency, but more complexity and deadlock risk;
  premature for phase 1.
- **Immutable copy-on-write tree with an atomic reference swap** — elegant,
  lock-free reads, but more machinery than phase 1 warrants. A candidate for
  later if needed.
