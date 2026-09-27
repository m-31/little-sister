# ADR-0091 — An import is not an instance: the server's start takes the lease, opens the log and starts the engine

- **Status:** Accepted
- **Date:** 2026-09-26
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (the engine lifecycle this
  moves), [ADR-0088](0088-a-stop-ends-at-its-save.md) (the hooks module whose other half
  is the stop), [ADR-0090](0090-one-state-directory-one-writer.md) (the lease the start
  takes), [ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) and
  [ADR-0073](0073-a-readiness-answer-beside-health.md) (the two routes a machine asks),
  [ADR-0023](0023-secret-references.md) (the settings that may be references),
  [ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md) (the doors),
  [ADR-0051](0051-what-startup-refuses.md) (the epoch)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Importing `little_sister.app` has been an instance. At module level it builds the engine
from the checks' configuration, restores the event log and the series, starts the
scheduler and with it every check, and registers the stop with `atexit`; and before any
of that, importing the logger gives the root logger a file handler on
`var/little-sister.log` of the working directory, creating `var/` if it is missing.
`LITTLE_SISTER_ENGINE=0` is what keeps an import from being one, and everything that
imports the application on purpose sets it — the library's test configuration, each
package's and deployment's tests that import it, and the tools that render its pages —
while the device VM's gate points `LOG_FILE` outside the checkout for every command run
there by hand.

What that costs was seen once: a process that was not the instance started an engine in
a deployment's checkout and wrote ten errors into that instance's history
([ADR-0090](0090-one-state-directory-one-writer.md)). The lease keeps two writers apart,
and it lets a stray process take a free directory: with the instance stopped, an import
on the device VM would take the lease and write its errors into the history. Only the
import can close that.

Where else the engine could start is already there. gunicorn's worker runs
`init_signals`, `load_wsgi` — the import — then the `post_worker_init` server hook, then
`run` (26.2.0's `init_process`), so that hook runs right after the import and before the
worker serves anything, in the module that already stops the engine
([ADR-0088](0088-a-stop-ends-at-its-save.md) decision 5).

## Decision

1. **Importing the application builds it and writes nothing.** Its configuration, its
   routes and its doors are built at the import as they always were; no lease is taken,
   nothing is restored, no check runs, nothing is saved, and no log file — not even
   `var/` — is created.
2. **The server's start does the rest, once, in the process that serves.** Under
   gunicorn it is the hooks module's `post_worker_init`, which finds the application in
   `sys.modules` and never imports it; the development server,
   `python -m little_sister.app`, makes the same call before `app.run`. In order, the
   start takes the state directory's lease
   ([ADR-0090](0090-one-state-directory-one-writer.md)) — first, so that a process the
   lease refuses has touched nothing in the directory, its log file included — then
   opens the log file with what the import logged (decision 4), resolves the settings
   that are references (decision 8), builds the engine from the checks' configuration,
   restores the kept files and the series, and starts the engine, with `atexit` as the
   backstop of its stop. A server started with `LITTLE_SISTER_ENGINE=0` takes no lease
   and builds no engine (decision 7). It is safe to reach twice, and the second call
   does nothing.
3. **A start the lease refuses halts the server, with the holder named.** It logs an
   ERROR line naming the holder — its mark, its host, its pid and its last beat — to
   stderr, since the log file in a directory it does not hold is not its to open, and
   raises, which gunicorn turns into its worker boot error: the master stops with
   *Worker failed to boot*, and `start.sh`, which already reports a gunicorn that exits
   during startup, prints the recent log with the line in it. It is the one start
   failure that halts. A refused process is a duplicate beside a live holder, and
   serving pages there would put a second dashboard over another instance's directory. A
   configuration the start cannot load still serves, with its banner
   ([ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)): that instance
   is the only one, and its banner is what explains what broke.
4. **What an import logs before the start is kept.** It goes to stderr, as it always did
   — `start.sh` keeps that in `var/gunicorn.log`, and a container in its log — and into
   a bounded buffer of the first 1,000 records, which the start writes into the log file
   when it opens it, so that a run's log still begins with its configuration; past the
   bound, the start writes one line counting what went to stderr only. A plain import
   leaves its lines on stderr only, and the buffer ends with the process.
5. **A process that serves without the start says so.** A gunicorn line without the hooks
   module imports the application, serves it, and never starts it. Its engine is
   `failed`, with an error that names the missing flag — on the banner of every page, on
   `/health` and on `/ready` (decision 6) — and the flag is the whole fix.
6. **`/health` and `/ready` with no engine.** `/health` answers `200` whatever the engine
   is doing ([ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)):
   `failed` where the start could not load the configuration or never ran, `disabled`
   where a server was started with `LITTLE_SISTER_ENGINE=0`. `/ready` answers `503`,
   waiting for a first pass that never comes, where the engine failed or never started,
   and `200` at once where it is disabled ([ADR-0073](0073-a-readiness-answer-beside-health.md)).
   A liveness probe that restarts on failure therefore never meets a missing flag as a
   failure: a load balancer that asks `/health`, and a group that replaces what it
   condemns — which is how the one deployment behind a load balancer runs — see a live
   instance with a failed engine, never a target to replace. Nothing there asks
   `/ready`.
7. **`LITTLE_SISTER_ENGINE=0` is kept, for a server that deliberately runs no engine.**
   The start honors it — no lease, no engine, `/health` saying `disabled` and `/ready`
   ready at once — for a server that serves its pages, the links page among them, and
   watches nothing. An import no longer needs it, so the library's tests, its tools and
   the packages' tests stop setting it.
8. **What an import still reaches outside the process**, named, and the part that moves:
   - **The settings `SECRET_KEY` and `LITTLE_SISTER_API_TOKENS`, where they are
     references** ([ADR-0023](0023-secret-references.md)), resolve at the start: a
     reference reaches a store, and the start is where an instance begins. A literal
     value is still read at the import, since reading it reaches nothing, and that is how
     a test or a tool sets one.
   - **The checks' constructor secrets** resolve when the start builds the engine.
   - **The doors an installation registers before the import stay where they are**, and
     a door may reach out: one deployment's reads its client id and secret from Parameter
     Store and fetches its identity provider's discovery document when it is registered.
     A door is the installation's own code, run in the slot before the application
     exists; the door table is what the import checks and announces
     ([ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md)) and what
     `/login` and `/ready` read; and moving a door's resolution to the start would take a
     start-time registration seam that every installation adopts — a change to the
     identity contract, for a reach that writes nothing an instance keeps. A door whose
     credentials cannot be read already closes and lets the application serve, and a
     deployment that wants its door not to reach out at the import can defer inside its
     own door: discovery already happens at first use where it has not worked, and a
     secret can be read at the first login.
   - **The machine's trust store** is read once at the import
     ([ADR-0073](0073-a-readiness-answer-beside-health.md)): a file on this machine.
9. **The epoch does not move.** `API_VERSION` versions the surface a check type is
   written against, which a package declares with `require_api`
   ([ADR-0051](0051-what-startup-refuses.md)), and no check type, no promised name and no
   behavior a check can observe changes here. What changes is how a server starts the
   WSGI application — a flag on its command line — which no package declares and which
   the epoch could not catch: a bump would refuse every package built for epoch 3 until
   it said 4, and not one of them sees a difference. The missing flag is caught where it
   happens instead, by the engine's error on the first page and on `/health`.
   `architecture.md` §11's entry for `little_sister.app:app` says what running it takes,
   and the release notes lead with the change and name the flag.

## Consequences

- A test, a tool, an import check, or a command an agent runs on the device VM is no
  longer an instance, and none of them can take a free state directory.
- Every way of serving starts the application explicitly: gunicorn through the hooks
  module it loads for the stop anyway, the development server through its `__main__`. A
  deployment that runs gunicorn itself without the flag has a failed engine that names
  it.
- `architecture.md` §3 says where the engine starts. [ADR-0001](0001-in-process-threaded-engine.md)'s
  engine lifecycle, [ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)'s
  `failed`, [ADR-0023](0023-secret-references.md)'s settings references and
  [ADR-0073](0073-a-readiness-answer-beside-health.md)'s conditions are updated. The
  packages' usage examples, which say that the import "builds the engine", are corrected
  in their own repositories.

## Alternatives considered

- **An import starts an engine only in a server**, recognized at the import — gunicorn
  in `sys.modules`, a server's environment. A guess the library makes about its caller: a
  test that imports gunicorn to test the hooks is a server by that rule, and a server the
  rule does not know serves with no engine and no reason.
- **An engine only when asked**, `LITTLE_SISTER_ENGINE=1` set by the run scripts and the
  entrypoint. Cheap, and it makes being an instance a property of an environment: a
  variable exported in a shell, or read from a deployment's `.env` by whatever sources
  it, makes every import an instance again, and every subprocess a check starts inherits
  it.
- **A start at the first request.** A test's first request would start an instance.
- **As it was**, with the lease refusing a second engine: a stray import still takes a
  free directory and writes into the history.

