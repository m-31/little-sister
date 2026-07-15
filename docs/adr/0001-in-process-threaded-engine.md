# ADR-0001 — In-process threaded engine with a single shared in-memory status tree (phase 1)

- **Status:** Accepted
- **Date:** 2026-06-17
- **Related:** [ADR-0002 — RLock + snapshot synchronization](0002-rlock-snapshot-synchronization.md)
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Little Sister runs many **checks** on per-check intervals and serves a web view
of **one overall status tree** ([`../project.md`](../project.md) §2.8). Phase 1
deliberately needs **no persistence** (`../project.md` §5). Checks are
**I/O-bound** — they call APIs, ping hosts, run shell commands. We want the
simplest correct model in which the checks and the web view look at the same
live state.

## Decision
- Run as a **single OS process**: gunicorn with **one worker and several
  threads** — the `gthread` worker, i.e. `gunicorn --workers 1 --threads N`.
- The **monitoring engine** runs its own **background threads** inside that same
  process, scheduling each check at its `frequency` on a **bounded thread pool**
  (not one thread per check).
- The **overall status tree** and an **event log** (status switches) are
  **module-level, in-memory** objects shared by all threads — engine threads
  writing, web threads reading.
- Because all state is in-process memory, deployment is **pinned to exactly one
  worker process**.

## Rationale
- One process ⇒ one shared memory ⇒ web threads and check threads see the same
  tree with no broker or store. This is what makes phase-1 "no persistence" work.
- CPython's **GIL** serializes Python bytecode, but it is **released during
  blocking I/O**. Because checks are I/O-bound, multiple checks (and request
  handlers) make real progress concurrently. Threads are the right fit here, not
  a workaround.
- Boring and standard; introduces **no new frameworks**.

## Consequences
- **Hard constraint: a single worker.** `--workers 2+` would create independent
  interpreters, each with its own tree and engine → inconsistent state. Enforce
  in the run command/config and document it.
- The GIL does **not** make the tree thread-safe at the logical level; explicit
  synchronization is required — see [ADR-0002](0002-rlock-snapshot-synchronization.md).
- **Engine lifecycle:** start the engine **once, and after the fork** (in the
  worker — e.g. a gunicorn `post_fork` hook, or guarded app-init). Threads are
  not inherited across `fork`; Flask's debug reloader and gunicorn `--preload`
  are double-start / no-start traps.
- **Robustness:** check threads should be **daemon** threads (or have a stop
  signal) for clean shutdown, and **every check needs a timeout** so a hung check
  can't pin a thread or block shutdown. The bounded pool keeps one slow check from
  starving others. A check that **fails or times out sets its node to `ERROR`**
  (see ADR-0004).
- The in-memory **event log must be bounded** (e.g. `collections.deque(maxlen=N)`);
  durable history is out of scope for phase 1.
- **Traded away by design:** horizontal scaling and restart durability — both
  recovered in phase 2 (see Seam).

## Alternatives considered
- **Multiple gunicorn workers + shared state in Redis/DB** — needed only if we
  ever require more than one web process; reintroduces a store, which phase 1
  explicitly avoids. Deferred to phase 2.
- **`asyncio` event loop instead of threads** — also gives I/O concurrency, but
  forces checks into async APIs (shell and many third-party libs are sync) and is
  less boring. Threads chosen for simplicity.
- **Separate engine process writing to a store now** — cleaner decoupling, but
  needs persistence/IPC immediately; that is exactly the phase-2 seam and is
  premature today.

## Phase-2 seam
Move the engine into its **own process** and put the shared tree + event table in
**Redis (or a DB)**. Web workers become stateless and can scale; the single-worker
constraint above is the thing that lifts.
