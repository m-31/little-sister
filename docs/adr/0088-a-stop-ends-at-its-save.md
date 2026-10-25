# ADR-0088 — A stop ends at its save: the engine stops when the worker leaves, and abandons what is in flight

- **Status:** Accepted
- **Date:** 2026-10-24 (accepted 2026-09-26)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (the daemon check threads
  and the stop signal this makes true), [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)
  (the graceful-shutdown write, which becomes the stop's one save),
  [ADR-0030](0030-curated-links.md) (the links page, which probes nothing, so
  nothing of it holds the exit), [ADR-0067](0067-the-run-scripts-can-serve-tls.md) (the
  run scripts),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the runtime line a failed tick
  wrote), [ADR-0089](0089-a-process-a-check-starts-ends-with-it.md) (what a run started
  ends with the stop), [ADR-0090](0090-one-state-directory-one-writer.md) (the lease the
  save releases), [ADR-0091](0091-an-import-is-not-an-instance.md) (the start the same
  hooks module makes)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A deployment that ran this library on a Mac for three weeks showed what a stop was. Its
logs carried `engine: scheduler tick failed` — a traceback ending in *cannot schedule new
futures after shutdown* — once a poll from every stop with a check in flight until the
process ended, and its event log kept the consequence: at five stops, the runtime node
and the engine's node went to WARN, the stop's own last save wrote them, and the next
start restored them as the instance's history. Twice in one day a start came up beside a
worker that was still running: the old worker's check read the same service on the same
token for up to fifty seconds beside the new instance, and its last save went over the
files the new instance had restored.

Read in the sources of CPython 3.14.6 and gunicorn 26.2.0, and reproduced without the
application, the mechanism is four facts.

- **The standard thread pool holds the exit.** `concurrent.futures` registers its exit
  hook with `threading._register_atexit`, which runs before `atexit`; the hook wakes every
  pool thread and **joins every thread a `ThreadPoolExecutor` started, whatever its daemon
  flag**, draining the work already queued — thirty queued one-second tasks on six threads
  all ran, and the exit waited five seconds. The engine registered its stop with `atexit`,
  so the process waited for the check in flight while the scheduler, a daemon never told
  to stop, ticked into the closed pool: a refused submit skipped that tick's sweep,
  observation and state tick, and left the refused check marked running — *the pool is
  saturated*. A tick with nothing due ran whole, its interval save included.
  [ADR-0001](0001-in-process-threaded-engine.md)'s "check threads should be daemon threads
  (or have a stop signal) for clean shutdown" described a shutdown the standard pool does
  not give.
- **`stop.sh` orphaned the worker.** It sent TERM to the master and KILLed it after about
  ten seconds; the master's own graceful stop waits `graceful_timeout`, 30 s by default,
  before it KILLs its workers. Killing the master first is what left a worker waiting on a
  check with nothing to end it but the check.
- **The orphan did not hold the port.** gunicorn's `gthread` worker closes its listening
  sockets when it leaves its loop, so the port check passed and a new gunicorn bound the
  port beside it, and a script that looks for listeners cannot find it.
- **An idle keep-alive connection holds the worker to the end of the grace.** The worker
  counts it among its open connections and does not close it at the TERM: it waits for
  the client's next request, answers it with `Connection: close`, or waits the grace out.
  Measured with a stand-in application: a connection whose response had ended 0.27 s
  before the TERM, from a client that sent nothing more, held the worker's exit for the
  whole grace — `worker_exit` came 30.02 s after the TERM, the moment the master's own
  KILL is due, and with a 5 s grace at 5.0 s. Closed by its client, or idle past
  gunicorn's 2 s keep-alive, the same connection let `worker_exit` run 3 ms after the
  TERM, and so did `--keep-alive 0` with a client that closes when an answer says
  `Connection: close`, as a browser does. A client that keeps its end open anyway holds
  the worker for gunicorn's graceful close of the connection — up to 2 s after the
  answer in 26.2.0 — and never for the grace. The dashboard polls every 10 s over one
  such connection, so a stop with a page open waited for the next poll about one time
  in five.

What a stop has to be follows from those: it ends when its save is made, the save is the
last write, and nothing a check started — here or on a remote host — outlives it.

## Decision

1. **A stop abandons what is in flight.** The engine runs its checks on a pool of its
   own, of daemon threads the interpreter does not join, and a stop does not wait for a
   run: the scheduler stops first, the runs in flight are abandoned, and a result one of
   them delivers later is dropped rather than recorded or saved. The next start runs
   every check at once, as every start does. The engine does not own a check's deadline —
   `timeout_seconds` is a budget the type enforces — so reaching a run through a deadline
   the engine could pull in is a surface every type would adopt, and it is not attempted
   here.
2. **Whatever a run started ends with the stop.** Every process a check starts goes
   through the library's process function, which ends its group at the stop — TERM, a
   grace, KILL — and an `ssh` run's remote command ends with its connection
   ([ADR-0089](0089-a-process-a-check-starts-ends-with-it.md)). Abandoning a run never
   leaves a process behind, on this machine or on the remote host.
3. **One final save, after the scheduler has stopped, and nothing writes the state
   directory after it.** The save is [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)'s
   graceful-shutdown write, made once, after the scheduler and the process groups have
   ended; then the lease is released ([ADR-0090](0090-one-state-directory-one-writer.md)).
   A write that arrives after it — a late result, a flush — is refused by the state layer
   and dropped.
4. **The stop logs one INFO line**, naming the checks whose runs it abandoned and which
   of the two triggers below reached it, so a missing result has a reason in the log.
5. **The stop reaches the engine at gunicorn's `worker_exit`, with `atexit` as the
   backstop.** `worker_exit` runs in the worker once it has left its loop and before the
   interpreter finalizes — before anything closes a pool. It lives in a hooks module the
   library ships, `little_sister.gunicorn_hooks`, which gunicorn loads with
   `--config python:little_sister.gunicorn_hooks` on every gunicorn line the family runs;
   `atexit` covers every other way of serving. Four rules hold for it:
   - **The hooks module never imports the application**, not even inside a hook. It
     finds a running engine through `sys.modules`, so a worker whose import failed does
     not start an engine on its way out. It is loaded in the master, where an import of
     the application would be an instance.
   - **The flag, not a `gunicorn.conf.py`.** gunicorn reads `./gunicorn.conf.py` only
     when neither `--config` nor `GUNICORN_CMD_ARGS` names a file, so any explicit
     configuration turns it off without a word, and nothing on a command line shows that
     it is there. A missing flag is loud instead: the same module is where the server
     starts the engine, so a server without it has none, and says so on every page and
     on `/health` ([ADR-0091](0091-an-import-is-not-an-instance.md)).
   - **The stop is safe to reach twice**, and the second call says nothing.
   - **A deployment that runs gunicorn itself takes the flag**; the release notes say
     so, and name the flag.
6. **Nothing but the engine holds the exit.** The links page probes nothing
   ([ADR-0030](0030-curated-links.md)), so the stop is the engine's alone: no pass of a
   probe is in flight to abandon, and no pool of one to join.
7. **Keep-alive is off.** Every gunicorn line the family runs passes `--keep-alive 0`,
   so gunicorn answers each request with `Connection: close` and only a request that is
   still running holds the save. It costs a connection per request — a TLS handshake each
   where the instance serves HTTPS — which is nothing at a page's poll every 10 s and one
   per icon on a first load of the links page. A test holds it: a TERM with a browser's
   client connected, and the worker has exited within a second. **Keep-alive can come
   back once gunicorn closes idle connections at the TERM**, and the measurement above is
   what to repeat — a second test repeats it on every run, and fails the day gunicorn
   does.
8. **The grace is one value**: `GRACEFUL_TIMEOUT`, 30 s — gunicorn's own default, now
   written down — defined once in `lib.sh` and overridable per installation in
   `instance.sh` or the environment, the way `WORKER_TIMEOUT` is. `start.sh`, and a
   container's entrypoint that runs gunicorn itself, pass it as `--graceful-timeout`. It
   is what a request still running at the TERM may take before the master's KILL, and
   the routes that wait on somebody else are bounded below it: an action a package
   offers makes calls its client bounds, and a login door's callback waits on its
   identity provider — one deployment's for up to 25 s, and 35 s when its discovery has
   not worked yet, the one route that can outlast the grace.
9. **`stop.sh` waits for every process it read before the TERM.** It reads the master
   and its workers while they still listen, sends TERM to the master, and waits on those
   pids for the grace and 5 s — the margin the master needs to reap its worker and exit
   after its own KILL — and at that bound it KILLs what is left and names each pid and
   what it was. `start.sh` stops an old instance through the same routine, so a start
   never comes up beside a process of the old instance.
10. **A container's stop has a bound of its own, and the save comes before it.** A
    container runtime sends its KILL at its stop timeout — Docker's default is 10 s,
    ECS's 30 s — and the worker saves only once gunicorn has finished its open requests.
    A deployment that runs the instance in a container names its stop timeout beside the
    grace — **40 s**, the grace and 10 s for the save — on every line that starts the
    container, and stops it with `docker stop` rather than `docker rm -f`, which is a
    KILL: no TERM, so no save.

## Consequences

- A stop with no request running ends about a second after the TERM; with one running,
  when that request ends, and never later than the grace. A stop logs no failed tick and
  writes nothing into the instance's history but its one save.
- [ADR-0001](0001-in-process-threaded-engine.md)'s daemon check threads and its stop
  signal are true, and [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)'s
  graceful-shutdown write is a single, last write; both are updated.
- What a stop loses is the runs in flight. Their checks run again at the next start, at
  once, and a node's history shows the gap between the two runs as what it was.
- Every gunicorn line the family runs carries two flags it did not: the hooks module and
  `--keep-alive 0`. The run scripts carry them for the library and both deployments; a
  deployment's container entrypoint carries them itself, with the grace, and the one
  deployment that runs in a container takes `--stop-timeout 40` on both of its
  `docker run` lines — its infrastructure's and its local script's.
- A request that outlasts the grace is cut by the master's KILL, and the worker never
  reaches its save: the stop loses what changed since the last interval save. One
  deployment's login door can outlast it while its identity provider's discovery is
  failing, and the grace stays at 30 s all the same — that loss is bounded by the
  interval, and a longer grace would slow every stop that hangs. A route that has to
  finish is bounded under the grace rather than the grace raised over it; an
  installation that raises the grace raises its container's stop timeout with it.

## Alternatives considered

- **Wait for the check in flight.** As long as the slowest run, up to its `timeout:` —
  five minutes for one check on that deployment — with the grace raised to match, or the
  master kills the worker mid-check. A stop that takes minutes is a restart nobody makes.
- **Reach the run through a deadline the engine owns.** Correct, and a new surface every
  check type would adopt to honor it.
- **Stop on the worker's TERM.** gunicorn installs its own handler before it imports the
  application, so an application's handler replaces it; one that chained to it would save
  at the TERM, while requests still run, so every route that writes would have to refuse
  after the stop. It is the way to keep keep-alive, if keep-alive is ever worth that.
- **Register after the pool's exit hook** with `threading._register_atexit`, which runs
  first. CPython-internal.
- **A `gunicorn.conf.py` among the run files.** Reaches a manual run from the checkout's
  root too, and is turned off silently by any explicit configuration (decision 5).
- **`stop.sh` returns once the state is saved.** A quick restart, and a start that comes
  up beside a process of the old instance, which is what this record ends.
- **As it was**: ten seconds and a KILL of the master — the orphan.

