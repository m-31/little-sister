# ADR-0134 — The state is compressed and stamped, and a keeper takes it in two cadences

- **Status:** Accepted
- **Date:** 2026-10-24
- **Related:** [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the
  files, their two disciplines and the keeper — its §2, §3 and §5 are what this record
  changes), [ADR-0077](0077-authority-follows-the-lease.md) (authority follows the
  lease: the adoption a takeover makes, which stands, and the line for a name nothing
  takes in, which a retired name no longer gets),
  [ADR-0014](0014-maintenance-persistence.md) (the pins' file, which gains its
  generation; decision 11, the clean break this one follows),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision 4, the clean break of
  the event log before this one), [ADR-0074](0074-this-instance-has-a-name.md) (the
  mark a generation names its writer by), [ADR-0088](0088-a-stop-ends-at-its-save.md)
  (the stop's one save), [ADR-0076](0076-the-instance-node-is-a-branch.md) (an action
  on the instance's node, which runs between two flushes from this record on),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (the
  series, whose file this compresses and whose retention a takeover brings),
  [ADR-0094](0094-a-restart-is-no-transition.md) and
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (what an empty
  start costs), [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (the pins' file, `pins.json`, whose old name joins the retired ones)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The state layer writes the event log and the series every `state_interval` in which they
changed, and a keeper mirrors every file it writes (ADR-0071). With the series kept, the
mirror carries megabytes where little-sister-aws ADR-0004 decision 12 put the prefix at
a few hundred kilobytes, its cost the requests. One deployment's bucket held a
`series.json` of 1.57 MB — 103 series, 1,916 records — rewritten nearly every interval,
and an `events.json` of 460 KB; a sync every minute carried between 0.75 and 2.3 GB a
day of whole series files, some eight times that at the default `series_limit`, each a
serialization peak in a container of 512 MiB. The requests stayed under a dollar a
month. The bytes were the cost, and where a NAT gateway carries them they are paid.

Lex asked whether the keeper could sync less often than the lease beats — monitoring
data may be lost, and need not be kept like production data — and named the two places
it would bite: a pin the holder changed after a standby copied the store, and a holder
that dies with nobody standing by before its last changes reached the bucket. Another
database, or a service such as Redis, was out of scope: the places it runs are a machine
in a homelab, an EC2 instance with its bucket, and a container, in Kubernetes among
others.

Two findings shaped the answer. A longer cadence turns ADR-0071 §5's *the keeper wins
over a local file* from harmless into a loss: it discards the newer local file in the
unclean end a container under a memory bound meets, where the kernel ends the worker and
gunicorn starts the next in the same container, on the same disk — on that deployment,
nine of the 28 workers that ended without giving the lease up, in the three days before
its memory fix, were followed so. And SQLite, measured for the state as it is, answers a
different question, history longer than memory, and not the bytes a mirror carries,
which compression answers with far less change: compact JSON under gzip at level 1
carried that series in 77 KB and that log in 33 KB, for a few milliseconds more a save.

## Decision

1. **The kept files are compressed, under names of their own.** The event log and the
   series are written as `events.json.gz` and `series.json.gz`: compact JSON with
   sorted keys under gzip at level 1 and `mtime=0`, so the same state gives the same
   bytes. That is fixed, with no setting — one that turned it off would write the plain
   names decision 2 retires. The pins stay plain JSON, in `pins.json` (ADR-0141) —
   written through, small, and the file an operator reads — and every file this record
   does not name stays as it is. The encoding is the state layer's: a keeper is still
   handed bytes and knows nothing of what they mean (ADR-0071 §5). A kept file is still
   rewritten only when its state changed, judged by a digest of its content before
   compression and without its generation (decision 4) — never the keeper's digest of
   the bytes it holds — and still written as a temporary file and `os.replace`. The
   name says the encoding, on a disk and in a bucket alike; reading one is `gzip -dc`.

2. **A clean break: no release from this one reads `events.json` or `series.json`.**
   They are retired names, as ADR-0014 decision 11 had no reader for the pins' old
   shape and ADR-0120 decision 4 none for an event log whose times carry no zone. At
   the upgrade the event log and the series start empty, once per deployment, and the
   release notes say so. That start is a first reading for every node — a row
   *undefined → …* each, and a failure found then published without its wait, the
   restart ADR-0094 and ADR-0110 otherwise prevent — and the series lose their history,
   a series of identities refilled at its next read and an append series begun again.
   In a rollout the new instance is the one that starts empty, and at its takeover it
   keeps what it observed while it stood by. `maintenance.json` joins them in the same
   release, when every pin a person sets is kept in `pins.json` (ADR-0141 decision 1):
   a pin that stands at the upgrade holds nothing until it is set again, and the start
   says so as it says the others.

   The start that finds a plain copy and no compressed one says so twice: once in the
   log, at WARN, as ADR-0071 §2 named a maintenance file left at its old path, and as a
   WARN line on `/little-sister/state` under the file's `load.` slug (ADR-0072), so that
   whoever looks at the instance and not at its log sees why its history begins at the
   upgrade. The line stands for the life of the process that met the file, can be pinned
   like any other, and does not come back, since by the next start the compressed copy
   is there. It is WARN where a load failure is ERROR (ADR-0071 §4): the history went on
   purpose, the release notes said so, and nothing an operator does brings it back. A
   takeover that adopts a plain copy from a holder of a release before writes it in
   place, as it writes any name nothing in the process takes in, and stands the same
   line — not the one ADR-0077 gives such a name, whose *until a restart* no restart
   makes true for a retired one.

   The plain copies stay: a keeper's seam has no delete, and the layer mirrors and
   restores every file (ADR-0071 §5), so they sit beside the compressed ones in the
   directory and in the bucket until an operator deletes them, which is safe once the
   compressed ones exist. Only a rollback reads them: a release from before this one
   reads the plain copies as it last wrote them, a roll-forward after it the compressed
   copies from before the rollback — what the older release observed in between is lost
   — and the pins likewise: a rollback finds `maintenance.json` as the release before
   last wrote it, a pin set or cleared since not among them. Taking whichever copy is newer is no rule: a plain
   copy carries no generation, so the comparison would be of two clocks.

3. **A compressed copy that does not decode is a file that cannot be read**, wherever
   it is read — not gzip, cut short, or not JSON inside. At a start that state starts
   empty with ADR-0071 §4's ERROR line; at a takeover and at *Take the backups* the
   adoption is refused and what the process holds stands, held out of the mirror where
   the copy came from the store (ADR-0077 decision 5). gzip's trailer carries the length
   and a CRC, so a file cut short is refused, never read short — though not by an error
   today's reading catches: Python raises `EOFError` for a stream cut short and
   `zlib.error` for damaged data, neither an `OSError` nor a `ValueError`. Every error
   of the decoding is that one failure, and none leaves the start, which never refuses
   (ADR-0071 §4).

4. **Every file the layer writes carries its generation**, a top-level key beside the
   file's own tables — in `pins.json`:

   ```json
   {"generation": {"writer": "web-1:4711:20261022T081500Z:2b7de044",
                   "count": 412, "held": true},
    "pins": […]}
   ```

   `writer` is the writer's mark (ADR-0074); `count` is that writer's writes of that
   file, from 1; `held` is what the layer knew as it wrote — whether the keeper took its
   saves the interval before, since the files are written before the keeper's tick — so
   a start's first write says false, and where no keeper is registered it is true. The
   count moves with the content and never alone (decision 1's digest). Readers take a
   file's tables by name and pass over a key they do not know — `PinStore.tables`,
   `events_from_payload`, `series._parsed` — so a release that does not know the key
   still reads a stamped file, where a stamp wrapped around the tables would cost it
   the file at a rollback. A file the layer does not write — a package's — carries
   none.

5. **At a start the newest copy wins.** The store's copy still wins over a local one —
   authority follows the lease (ADR-0077) — but for one case: a local copy whose
   generation names the same writer as the store's, a higher count, and `held`. That is
   the dead worker's newer state when the next starts on the same disk, which a longer
   cadence would otherwise throw away, and the rule compares no two clocks. A standby's
   writes never take it — written without the lease, they are the shadow ADR-0077 makes
   them, and a holder that demotes itself writes as a standby from that moment — and
   neither does a copy without a generation, as every release before this one wrote.
   The keeper notes the store's token when it loads a copy, whether the layer puts that
   copy in place or not, so the flip that follows names nothing for it — ADR-0077
   decision 4's silent takeover — and the flip's save sends the newer copy up (decision
   6). It keeps one end's newer state, not two close together: the successor stands by
   until the dead holder's lease lapses — `lapse_after` intervals, three minutes at the
   defaults (little-sister-aws ADR-0004 decision 8) — and writes as a standby meanwhile,
   so a second end in that window falls back to the store's copy. A file the layer does
   not write keeps ADR-0071 §5's rule.

6. **Two cadences to the keeper.** *What an operator sets* — the pins, and the notes
   once they are built — goes to the store at the next scheduler tick after it changes,
   as it goes to the disk the moment it does. *What is observed* — the event log and the
   series — goes every **`keeper_interval`** (`settings.yaml`, default 900 s) while
   nobody stands by, and every `state_interval` while anyone does. The heartbeat stays
   on `state_interval`, so a failover still takes `lapse_after` intervals, and the disk
   keeps it too: the local files are written as often as before. **The flip's save
   sends the observed state at once**, whatever `keeper_interval` says, so the store
   holds the new holder's copies from its first interval as holder, and the interval
   counts from each send. **A stop sends everything first** — the stop's one save
   (ADR-0088 decision 3) — **and so does an operator's release**, which gives the lease
   up in its handler: **an action runs between two flushes** of the state layer, the one
   before its handler sending what the process holds while the lease is still its own
   and the one after it what the action changed (ADR-0076 decision 6), and each sends
   everything, whatever `keeper_interval` says. A keeper's release needs nothing of its
   own.

   The seam gains two optional answers for it. `push(name, data)` is a save between two
   of the keeper's ticks, which the keeper puts behind a heartbeat of its own so that it
   lands only while the lease is held — for the S3 keeper, which writes a state file
   unconditionally only behind a heartbeat that landed (little-sister-aws ADR-0004
   decision 3), one more conditional `PUT` per change, a few a day. `standing_by()`
   says whether another instance stands by, as the keeper last saw. A keeper without
   `push` is handed the pins with the interval's saves, and one without
   `standing_by()` counts as always watched and is sent the observed state every
   interval — both as now.

   Every graceful handover then loses nothing at any cadence. An unclean end loses
   observed state only where the disk goes with the instance and nobody stands by — an
   EC2 instance replaced, a pod on an `emptyDir` — and there at most `keeper_interval`
   of it and a pin set in its last tick: a restart on the same disk keeps the newer
   local copy (decision 5) — short of a second end before the successor holds the lease
   — and a takeover finds the store at most an interval behind. Without a keeper the
   setting does nothing.

7. **A takeover adopts the store's observed state, as now, and a smaller
   configuration's takeover is accepted.** ADR-0077 stands. An instance that keeps fewer
   series, or keeps them shorter, cuts the store to its own retention from its takeover
   — the engine answers no keep for a check it does not configure, and its sweep trims
   to its own keeps and evicts by its own `series_limit` (ADR-0087). Pointing a
   differently configured instance at a live prefix is a deliberate act, and its cost is
   written where the act is: here, and in the architecture of a deployment that starts
   such an instance on purpose.

## Consequences

- **A sync carries about a twentieth of what it did**, and while nobody stands by the
  observed state is sent a fifteenth as often: the state the context measured
  compresses to 77 KB of series and 33 KB of events from 1.57 MB and 460 KB. The live
  log and the readings in memory do not shrink, and nothing here raises the series'
  budget.
- **Every deployment loses its event log and its series once**, at the upgrade
  (decision 2); the release notes say so, the instance says so on `/little-sister/state`
  for as long as the upgraded process runs, and the plain copies wait beside the new
  ones for a rollback or an operator.
- **`settings.yaml` gains `keeper_interval`**, a positive integer of seconds, default
  900, met at the first flush after it falls due — never shorter, in effect, than
  `state_interval`. Maintenance never waits on it.
- **The keeper seam gains `push` and `standing_by()`**, both optional. The S3 keeper
  has what `standing_by()` needs from its listing (little-sister-aws ADR-0004 decision
  13); its half — the two answers — is that repository's next slice, and until it
  ships it is sent everything every interval, as now. Its *release* sends everything
  first without it, through the flush before an action.
- **An action costs one more flush**, the one before its handler, and with it one more
  tick of the keeper — a heartbeat, for the S3 keeper — whatever the action does; a
  handler that raised is still followed by none.
- **ADR-0071 §5's *the keeper wins over a local file*** holds for a package's file and
  for every copy decision 5 does not prefer, and its §2 and §3 read with decisions 1, 2
  and 6. ADR-0014's file carries a third key beside its two tables. ADR-0077's adoption
  is unchanged but for the line a retired name gets. ADR-0076's action runs between two
  flushes. Each of the four says so and points here.
- **Reading a kept file by hand gains a step**, `gzip -dc events.json.gz`, which the
  operating documentation says where it shows the directory.
- **A smaller configuration's takeover shrinks the store**, as it did before this
  record; the cost is now written down rather than found.

## Alternatives considered

- **The state in SQLite.** Rows, each change written as it happens, a restore that is a
  query, the generation in a table of its own. Rejected for now: a keeper carries a file
  whole — the measured state's three files were 1.84 MB as one SQLite file, 0.23 MB
  compressed, against 0.11 MB of compressed JSON — a live database copied in the middle
  of a transaction is torn, and the bytes are what compression answers with far less
  change. Its gain, history longer than memory, comes later, when a deployment's series
  are to hold more than memory, on the standard library's `sqlite3`.
- **Sync less often and leave the keeper winning at a start.** Rejected: it throws away
  the newer local file at every worker restart on the same disk.
- **The newest copy by its times.** Rejected: two machines' clocks; the generation
  compares none.
- **At a takeover, keep the standby's own events and series and adopt only the
  holder's pins.** With the pins always fresh in the store it no longer loses a pin, but
  the standby's history is the holder's only where the standby is the holder's setup,
  and nothing says it is.
- **The same names, the encoding told by the content, the reader shipped a release
  before the writer** — the round's recommendation. Rejected for names that say what a
  file is on a disk and in a bucket, at the price of decision 2.
- **Read a plain copy where no compressed one exists.** The upgrade would be a restart
  like any other. Rejected: it is the reader for an old file that ADR-0014 decision 11
  and ADR-0120 decision 4 refused, in the read and adoption paths until a release took
  it out.
- **The upgrade's loss named in the log alone**, as ADR-0071 §2 named a moved file — the
  record's draft. Rejected on Lex's word: whoever looks at the instance and not at its
  log would find its history empty and no reason given.
- **Compression as a setting, or another level or codec.** On another deployment's
  series of 4.25 MB, level 6 saved another 42 KB for 6.7 ms more a save; Zstandard
  reaches the standard library at Python 3.14, above the floor. Rejected without an
  operational need.
- **`keeper_interval` defaulting to `state_interval`, or to an hour.** The first leaves
  the decision off until a deployment turns it on — affordable, well under a dollar a
  month at the measured size once compressed; the second makes the bucket an hourly
  copy and an hour the loss. A quarter of an hour was Lex's answer.
- **A release that gives the lease up at the keeper's next tick**, after the flush that
  follows the click has sent everything. Nothing here would change; but the lease
  leaves up to an interval late, and what changes meanwhile stays behind. Rejected on
  Lex's word, with the next.
- **A third optional answer on the seam**, called after a flush's saves, where a keeper
  gives its lease up. Exact, but the seam widened for one action, where a flush before
  every action serves every keeper's.
