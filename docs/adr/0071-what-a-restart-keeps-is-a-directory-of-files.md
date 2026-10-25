# ADR-0071 — What a restart keeps is a directory of files, and a keeper carries it

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-09-05)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (one process, in
  memory — the event log this record gives a life across restarts),
  [ADR-0002](0002-rlock-snapshot-synchronization.md) (the lock the writer stays
  out of), [ADR-0014](0014-maintenance-persistence.md) (the maintenance file, whose
  path moves and whose discipline becomes every state file's),
  [ADR-0047](0047-node-notes-and-their-retention.md) (a node's notes, whose file joins
  the directory), [ADR-0064](0064-the-resolver-is-a-registration.md)
  (the registration rules the keeper follows),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the seam that carries this
  layer's two lines), [ADR-0031](0031-deployment-config-directory.md) (`var/` is
  what the process writes), [ADR-0088](0088-a-stop-ends-at-its-save.md) (the stop's
  one save), [ADR-0090](0090-one-state-directory-one-writer.md) (the directory's one
  writer), [ADR-0094](0094-a-restart-is-no-transition.md) (what the first reading after
  a restart records),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (the table
  `events.json.gz` carries beside the log),
  [ADR-0134](0134-the-state-is-compressed-and-stamped.md) (the kept files compressed and
  stamped, the newer local copy a start keeps, and the keeper's two cadences),
  [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (decision 7, the
  notes file, `notes.json`),
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (decision 1, the pins' file, `pins.json`, which takes `maintenance.json`'s place)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

One process keeps its state in memory (ADR-0001), and a restart has always cost most
of it: the event log emptied, every node's history with it, and only the
maintenance pins came back, from one file written through under `var/`
(ADR-0014). That record deferred everything else to "the persistence phase" and
assumed a database would arrive to subsume the file. Two things changed the
assumption. The family now runs the library on the smallest cloud instance and on a
laptop alike, and nothing in either wants a service in the core: a database is a
package's business. And the series — a subject's records over time, kept and drawn
— needs somewhere to live across a restart *before* any store exists, or a local
instance loses its history with every deploy.

Meanwhile the one file that did persist failed quietly: a write that could not land
was a log line, and an unreadable file at startup restored as an empty table, so a
maintenance window ended the moment somebody restarted the process — with nothing
on the dashboard to say so. A layer that keeps more state must not keep more
silence.

## Decision

Three layers hold what this process wants to survive a restart.

1. **Memory is where the application works**, as before. **The state layer** is
   memory serialized to JSON files under `var/state/`, read at startup so an instance
   initializes with what it had. **Packages** sit behind two seams outside the core:
   a *store* that speaks to a service per record (the series stores), and a
   **keeper** (§5). Nothing that is a service enters the core; `var/state/` is the
   whole of what the core persists.

2. **The files.** `pins.json` (every pin a person sets, of every kind, in one list —
   [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
   decision 1; the pins ADR-0014 kept under `var/` **move** here, and that path is not
   read); `events.json.gz` (the bounded event log of ADR-0001, from which node history
   is derived, so one file covers both and a restart no longer empties the log);
   `notes.json` (a node's notes, ADR-0047: plain JSON, written through by the notes as
   `pins.json` is by the pins, adopted at a takeover, and read at the start for every
   path it holds — [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md)
   decision 7); `series.json.gz` (the series' memory tier). `events.json.gz` carries,
   beside the log, what every node last showed and what its check last reported
   ([ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)): a table
   written with the log, which a restart reads for the nodes the bounded log has no row
   of. Run facts stay ephemeral — a wall time and an armed slot belong to the process
   that measured them. JSON because these files are machine-written and machine-read;
   YAML stays for what a person authors. The two kept files are compact JSON under gzip,
   as their names say ([ADR-0134](0134-the-state-is-compressed-and-stamped.md) decision
   1). `events.json`, `series.json` and `maintenance.json`, where the maintenance pins
   were kept, are retired names: no release from then on reads one, and a start that
   finds one without its successor says so once — clean breaks (ADR-0134 decision 2,
   ADR-0141 decision 1). Nothing else loose in `var/` is state: logs, pids and TLS
   material stay where they are. The directory is a fixed path relative to the working
   directory (ADR-0031), git-ignored and not env-overridable, exactly as the maintenance
   file was. **The directory has one writer**: a process takes a lease on it before it
   restores anything and keeps it for its life — a file beside the directory with a
   heartbeat, and a kernel lock for the machine the kernel sees — and a process that
   cannot take it restores, runs and saves nothing
   ([ADR-0090](0090-one-state-directory-one-writer.md)).

3. **Two write disciplines, one atomic write.** The pins and the notes are
   **written through**: a pin is written when it changes, so a crash a minute later
   loses nothing. Events and the series are **kept**: written
   coalesced, at most once per `state_interval` (`settings.yaml`, default 60 s) on
   the scheduler tick beside the sweeps, and once more at the stop — the stop's one
   save, made after the scheduler has stopped, with nothing written to the directory
   after it ([ADR-0088](0088-a-stop-ends-at-its-save.md) decision 3); an unclean
   shutdown loses at most the interval. A kept file whose state did not
   change is not rewritten. Every write is a temporary file in the same directory
   and `os.replace`, the discipline the pins' file always had; the producer of a
   kept file copies under its own lock and serializes outside it, so the writer is
   never inside the tree's lock for longer than the copy takes (ADR-0002). A file of
   an older shape is reported and rewritten by the next save, never migrated
   (ADR-0014 decision 11). Every file the layer writes carries its generation — the
   writer's mark, its count of that file's writes, and whether it held the keeper's
   lease as it wrote ([ADR-0134](0134-the-state-is-compressed-and-stamped.md)
   decision 4).

4. **A failure never refuses to start, and is never silent.** A file that cannot be
   read — unreadable, not JSON, a shape the reader does not know — starts that state
   empty; a write that fails keeps the state in memory. Both are lines on
   `/little-sister` through the self-report seam (ADR-0072), with stable slugs so
   either can be pinned: *the state in `<file>` could not be loaded at startup* at
   **ERROR** for as long as the process runs, because what somebody set before the
   restart is not in force and a restart is the one thing that could change that;
   *the last save of `<file>` failed* at **WARN** until a write of that file
   succeeds, because nothing is lost yet — the next restart is. The layer is the
   first contributor the application registers, which is why that seam and this
   layer are one phase.

5. **The keeper.** One seam, one keeper per instance — `little_sister.keeper`, whose
   `register_keeper(name, keeper)` claims **the** slot rather than one name among many,
   because two keepers would each carry a copy of what the other wrote and import order
   would decide which one a restart came back as. It is registered in the
   import-before-app slot like a resolver (ADR-0064's rules: a name claimed once, the
   package recorded, `/system` lists it), and answers in **bytes**: `load(name)`,
   `save(name, data)`, `list()`, and some a keeper may answer —
   `tick(interval_seconds) -> bool`, called every interval before any save whether or
   not a file changed, whose answer says whether this interval's saves are wanted;
   `close()`, once at graceful shutdown after the last save; and `push(name, data)` and
   `standing_by()`, for the two cadences below. It mirrors the whole of `var/state/` —
   every file, a package's sqlite file among them if a store keeps one there — **every
   file in the directory, not only the ones this process writes** — and never knows what
   a file means. It loads before the tree restores from the files and saves copies after
   the writer, at two cadences ([ADR-0134](0134-the-state-is-compressed-and-stamped.md)
   decision 6): what an operator sets — the files written through, the pins and the
   notes — at the scheduler tick after it changes, through `push`, a save between two
   of the keeper's ticks; and what is observed — the event log and the series — every
   `keeper_interval` (`settings.yaml`, default 900 s) while nobody stands by and every
   `state_interval` while anyone does, as `standing_by()` says; everything at a
   takeover, at the stop and at an action. A
   keeper that answers neither is sent everything every interval. What the keeper holds
   **wins** over a local file of the same name, which is the point on a fresh machine,
   but for one case: a local copy whose generation names the same writer as the store's,
   a higher count, and the lease held — the dead worker's newer state when the next one
   starts on the same disk ([ADR-0134](0134-the-state-is-compressed-and-stamped.md)
   decision 5). A name it lists is refused unless it is a plain file name: it arrives
   from outside the library and is used as a path component. A keeper that cannot load
   leaves the local files as they are; its failures are the same two lines with the
   keeper's name — `keeper.load` at ERROR, `keeper.save.<file>` at WARN, through this
   layer's own contributor — a `tick` that raises a third, and a `standing_by()` that
   raises a fourth. A tick that *declines* is not a failure: the layer sends nothing and
   says nothing, and the keeper says why through the self-report seam. The first keeper
   is S3, in `little-sister-aws`: one lease per prefix, renewed in `tick` by a heartbeat
   and read there by an instance that does not hold it, taken with S3's own
   compare-and-swap, given up in `close`; a client bounded in seconds so neither a save
   nor a tick can hold the scheduler. `tick` exists because that keeper needed a call on
   the interval that a directory with nothing to save never made, and `close` because a
   lease left to lapse is a failover that waits for nothing. A local instance keeps no
   keeper and loses nothing by it. The seam ships with that keeper; this record fixes
   its shape so the layer is built for it. What the lease does not settle on its own —
   that whoever holds it wrote the truth, so an instance that takes it over adopts what
   the store changed while it stood by — is
   [ADR-0077](0077-authority-follows-the-lease.md): the `restore` direction of a state
   file, the keeper's optional `changed_since_sync()`, the adoption at the moment `tick`
   turns from declining to taking, and the `.bak` it leaves behind.

6. **What this retires.** The plan's *maintenance store supplied by the deployment*:
   a deployment supplies a keeper, not a store, and the file it keeps is the one the
   core writes. ADR-0014's "the durable store subsumes this file": the file is the
   durable state, and what a database was going to add is a store per record behind
   its own seam. And the open question whether a durable store could hold the
   service-free line: memory and files in the core, every service a package, the
   keystone of one process untouched (ADR-0001).

## Consequences

- A restarted instance shows yesterday's events, its pins and its notes, and every
  node's history starts where it left off. The first reading after a restart is compared
  with what the restored log last recorded for its node
  ([ADR-0094](0094-a-restart-is-no-transition.md)): a node reading what it read
  before keeps its period, and one reading anything else — `UNDEFINED` included,
  whose restored period had run on to the present — changes from the old code; the
  pins' replay writes nothing where the log already holds the pin. The restart is
  recorded once, where it happened: on `/little-sister`, whose last period closes when
  the old process was last alive — a `stopped_at` the stop's one save writes into
  `events.json.gz`, or the lease's last beat.
- No maintenance file is read: neither `var/maintenance.json`, where ADR-0014 kept
  the pins, nor `var/state/maintenance.json`, whose place `pins.json` takes (ADR-0141
  decision 1). A deployment that upgrades sets again the pins it still wants, and the
  release notes say so; nothing outside the family reads either file, which is what
  makes the clean break cheap.
- The event log costs one more write per interval: a few hundred kilobytes at most
  at the ADR-0001 bound, skipped when nothing changed.
- `settings.yaml` gains `state_interval`. What is written through never waits on it.
- The two failure lines are pinnable like any entry (ADR-0036), so an operator who
  has re-pinned by hand can silence the load line for the rest of the process.
- The keeper, its registration and the lines it adds are decision 5's, its S3
  implementation `little-sister-aws`'s; the notes and the series are files of the
  directory, as decision 2 lists them. A second process never writes into the
  directory — the lease refuses it
  ([ADR-0090](0090-one-state-directory-one-writer.md)); two instances sharing one
  keeper is the 412 the design reports, not a case it serves — and two instances
  sharing one *keeper's* lease is [ADR-0077](0077-authority-follows-the-lease.md)'s.

## Alternatives considered

- **A database in the core** (sqlite first, then whatever the cloud offers).
  Rejected: sqlite is a file a keeper can carry but a poor fit for the cloud
  instance, a hosted database is a service, and either puts a store in the process
  that every deployment pays for; the seams give both to the deployments that want
  them.
- **Migrate `var/maintenance.json` to the new path** on first start. Rejected: a
  migrator in the read path forever, for one upgrade of state the program owns and
  bounds with a finite expiry — the same reasoning as ADR-0014 decision 11. A
  clean break is the honest cost.
- **Write the event log through**, like the pins. Rejected: a transition storm
  during an outage would write the whole log per event under load; the interval
  bounds the cost, and what an unclean shutdown loses is stated.
- **Keep the event log's failure in the log only**, as the maintenance file's was.
  Rejected: that is the silence this record exists to end.
- **One file for everything.** Rejected: a write-through pin would rewrite the
  event log each time, and a keeper that mirrors a directory carries any number of
  files at no extra design.
