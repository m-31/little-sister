# ADR-0001 — In-process threaded engine with a single shared in-memory status tree

- **Status:** Accepted
- **Date:** 2026-09-27 (accepted 2026-06-20)
- **Related:** [ADR-0002 — RLock + snapshot synchronization](0002-rlock-snapshot-synchronization.md),
  [ADR-0071 — what a restart keeps is a directory of files](0071-what-a-restart-keeps-is-a-directory-of-files.md),
  [ADR-0088 — a stop ends at its save](0088-a-stop-ends-at-its-save.md),
  [ADR-0089 — a process a check starts ends with it](0089-a-process-a-check-starts-ends-with-it.md),
  [ADR-0091 — an import is not an instance](0091-an-import-is-not-an-instance.md)
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Little Sister runs many **checks** on per-check intervals and serves a web view
of **one overall status tree** ([`../project.md`](../project.md) §2.8). The
initial build deliberately needs **no persistence** (`../project.md` §5). Checks
are **I/O-bound** — they call APIs, ping hosts, run shell commands. We want the
simplest correct model in which the checks and the web view look at the same
live state.

## Decision
- Run as a **single OS process**: gunicorn with **one worker and several
  threads** — the `gthread` worker, i.e. `gunicorn --workers 1 --threads N
  --config python:little_sister.gunicorn_hooks --keep-alive 0`: the hooks module is
  what starts and stops the application in the worker, and keep-alive is off so that a
  stop is not held open by an idle connection
  ([ADR-0088](0088-a-stop-ends-at-its-save.md) decisions 5 and 7).
- The **monitoring engine** runs its own **background threads** inside that same
  process, scheduling each check at its `frequency` on a **bounded thread pool**
  (not one thread per check).
- The **overall status tree** and an **event log** (status switches) are
  **module-level, in-memory** objects shared by all threads — engine threads
  writing, web threads reading. The **event log is also a file** of the state layer
  ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)), written at most
  once per interval and at graceful shutdown and read back at startup, so a restart
  no longer empties it.
- Because all state is in-process memory, deployment is **pinned to exactly one
  worker process**.

## Rationale
- One process ⇒ one shared memory ⇒ web threads and check threads see the same
  tree with no broker or store. This is what makes "no persistence" work.
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
- **Engine lifecycle:** start the engine **once, and after the fork**, at the
  server's start and never at the import — gunicorn's `post_worker_init` through the
  hooks module the library ships, and the development server's `__main__`
  ([ADR-0091](0091-an-import-is-not-an-instance.md)). Threads are not inherited across
  `fork`; Flask's debug reloader and gunicorn `--preload` are double-start / no-start
  traps.
- **Robustness:** the engine runs its checks on a pool of its own, whose threads the
  interpreter does not join, and a stop **abandons a run in flight** rather than
  waiting for it, ending whatever the run started
  ([ADR-0088](0088-a-stop-ends-at-its-save.md),
  [ADR-0089](0089-a-process-a-check-starts-ends-with-it.md)) — the standard pool's exit
  hook joins every thread it started, whatever its daemon flag, so a daemon thread
  alone does not give a clean shutdown. **Every check honors a timeout of its own** —
  the engine cannot kill a thread, so a check that never returns pins a pool worker
  (`architecture.md` §9), and the bounded pool is what keeps one slow check from
  starving the others. A check that **fails or times out sets its node to `ERROR`**
  (see [ADR-0040](0040-what-a-failing-check-becomes.md)).
- The **event log must be bounded** (e.g. `collections.deque(maxlen=N)`), and the
  bound holds in the file it is written to as well. Durable history stays out of
  scope: a history *longer than the bound*, or one searched rather than read whole,
  is a store behind a seam
  ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) §1) — never a
  database in the core.
- **Traded away by design:** horizontal scaling, and the restart durability of the
  live tree — what the state layer keeps comes back at startup
  ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)), and a node's
  current reading waits for its next run. Horizontal scaling is the seam below.

## Alternatives considered
- **Multiple gunicorn workers + shared state in Redis/DB** — needed only if we
  ever require more than one web process; reintroduces a store, which this
  decision explicitly avoids. Deferred to the seam below.
- **`asyncio` event loop instead of threads** — also gives I/O concurrency, but
  forces checks into async APIs (shell and many third-party libs are sync) and is
  less boring. Threads chosen for simplicity.
- **Separate engine process writing to a store now** — cleaner decoupling, but
  needs persistence/IPC immediately; that is exactly the seam below and is
  premature today.

## The seam it leaves
Move the engine into its **own process** and put the shared tree + event table in
**Redis (or a DB)**. Web workers become stateless and can scale; the single-worker
constraint above is the thing that lifts.
