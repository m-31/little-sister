# ADR-0002 — Synchronize shared state with one RLock and copy-on-read snapshots

- **Status:** Accepted
- **Date:** 2026-10-24 (accepted 2026-06-20)
- **Related:** [ADR-0001 — In-process threaded engine](0001-in-process-threaded-engine.md),
  [ADR-0071 — what a restart keeps is a directory of files](0071-what-a-restart-keeps-is-a-directory-of-files.md),
  [ADR-0132 — a branch keeps the period of what it shows beside the log](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
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
- **A run's store is one mutation.** The engine holds the lock from the first node a
  run writes to the last — the run's node, the nodes beneath it, what it no longer
  returns, a unit's failure over its node — each of those writes re-entering it, so no
  reader, and no comparison of what a branch rolls up to, sees half a run
  ([ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)).
- **Reads for rendering** take the lock only long enough to build a lightweight
  **snapshot** (a copy of the branch being shown / a slice of events), then
  release the lock and render the snapshot **outside** it.
- **A write to disk reads the same way.** The producer of a kept state file
  ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) §3) copies the
  event log under the lock and serializes outside it, so no write holds the lock for
  longer than the copy takes.

## Rationale
- One lock for all shared state is the simplest thing that is correct; `RLock`
  lets a locked method call another locked method without self-deadlock, which is also
  what lets a run's store hold it across writes that each take it.
- Copy-on-read keeps request latency **independent of check activity** and avoids
  holding the lock across template rendering.

## Consequences
- Snapshot cost is O(size of the shown branch) — fine for expected tree sizes.
- **A reader waits out a store**, which is in memory and takes milliseconds.
- **Change detection** (old code vs new code, to emit an event) must happen
  **under the lock**, so two threads can't interleave and miss or duplicate a
  transition.
- If trees grow large or lock contention bites, revisit with finer-grained locks
  or an immutable copy-on-write tree (atomic root swap) — see Alternatives.

## Alternatives considered
- **Rely on the GIL alone** — incorrect for compound operations; rejected.
- **Per-node locks** — more concurrency, but more complexity and deadlock risk;
  premature for the initial build.
- **Immutable copy-on-write tree with an atomic reference swap** — elegant,
  lock-free reads, but more machinery than the initial build warrants. A
  candidate for later if needed.
