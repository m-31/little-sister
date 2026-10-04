# ADR-0120 — Every stored time is an instant

- **Status:** Accepted
- **Date:** 2026-10-04
- **Supersedes:** [ADR-0006](0006-config-file-and-timezones.md) wholly (accepted
  2026-06-20, rewritten 2026-08-23). What that record decided and this one keeps is
  restated in decision 7 with its reasoning, so nothing has to be read out of a
  superseded record: the settings file, the display zone and format, and how an expiry
  an admin types is read. What changes is the one thing it left as it found it: how a
  time is stored.
- **Related:** [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (a reading's
  `observed_at`, the instant the tree's times now are),
  [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md) (a record's own
  times, in UTC at the seam),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the state files, and
  what a file the process cannot use costs),
  [ADR-0077](0077-authority-follows-the-lease.md) (a takeover, which adopts them),
  [ADR-0014](0014-maintenance-persistence.md) (the pins' file; decision 8, the token;
  decision 22, a typed expiry), [ADR-0027](0027-observation-timestamp-semantics.md) (a
  node's observation time), [ADR-0094](0094-a-restart-is-no-transition.md) (decision 4,
  the stop's stamp and the gap),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (decision 5,
  a period's beginning; decision 6, a pin's creation),
  [ADR-0044](0044-run-facts-on-the-node.md) (a run's next slot),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope, which does
  not move), [ADR-0030](0030-curated-links.md) (the reachability probe's times),
  [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) (an axis's round times),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (decision 5, the expiry an
  edit keeps), [ADR-0031](0031-deployment-config-directory.md) (where the settings file
  lives), [ADR-0003](0003-config-and-secrets-via-env-file.md) (secrets in `.env`),
  [ADR-0049](0049-the-check-authoring-surface.md) (the promised names, none of which
  carries one of these times, and the logging an application may configure itself),
  [ADR-0091](0091-an-import-is-not-an-instance.md) (the log file the start opens, with
  what the import logged), [ADR-0095](0095-the-instance-states-its-memory.md) (the
  memory line's ten-minute marks), [ADR-0076](0076-the-instance-node-is-a-branch.md)
  (a note, which stands for the life of the process)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

ADR-0006 gave the pages a time zone and left storage as it found it. A node's
observation time, an event's time and a pin's three times were the machine's wall clock,
written without a zone, and every surface converted on the way out: a time without a
zone was read as the machine's own. That reading is right on the machine that wrote the
time, for as long as its clock has not changed. It stops being right in three ways, and
each was run through the library's own functions.

**A state that travels.** A keeper carries the state files to another machine
(ADR-0071), and a takeover adopts them (ADR-0077). On an instance that stood by six
hours from the one holding the lease, everything the holder wrote read six hours early:
a node it wrote at 12:51:48 of the standby's time said *since before 06:51:48*. A pin
set for two hours was expired when it arrived; written the other way round it would have
held six hours too long. One restored log held two machines' clocks, in the order the
events arrived. It needs no second machine either: a laptop whose zone follows its
location, or a process started with another `TZ` than the last.

**The hour a clock repeats.** A node observed at 01:59:50 has an age of 0 seconds twenty
seconds later, when the clock reads 01:00:10, and for the hour after: a check that
stopped reporting just before that hour is noticed an hour late. An event of the second
pass is read an hour early. A pin set at 01:50 for thirty minutes ends at 01:20, before
the clock that set it.

**The hour a clock skips.** Observed at 01:59:50, a node's age is 3,620 seconds twenty
seconds later. Every node read more often than about every half hour is stale at once,
until its next reading.

Everything newer than the tree held instants already: a reading's `observed_at`
(ADR-0087), a record's own times (ADR-0082), the instance's mark and the JSON the API
serves. The series read their file strictly — a time without an offset is a damaged
file, not a dialect — and the pins' file had taken a change of shape as a clean break
(ADR-0014).

**The log** was the last surface on the machine's clock. The default handler stamped a
line with it and wrote no zone — `2026-10-04 13:02:35,893` — on stderr and in
`var/little-sister.log`, beside pages that write every time in the configured zone. On
a machine in another zone a line and a page were hours apart, with nothing in the line
to say so, and in the hour a clock repeats a stamp named two moments.

## Decision

### 1. A time the tree stores is an instant

A node's observation time, an event's time, the beginning of a period and a pin's
`set_at`, `created_at` and `expires_at` are **instants**: times that know their zone,
held in UTC, as a reading's `observed_at` is (ADR-0087). So is what is derived from
them or kept beside them in memory: a period's two ends, the time a snapshot publishes,
the moment the engine started, a run's start and the slot its next run is armed for
(ADR-0044), the stop's stamp (ADR-0094), and the times the reachability probe keeps of
an answer and of a pass (ADR-0030).

### 2. An instant without a zone cannot be built

What holds an instant refuses a time without a zone where it is built — an event, a
period's beginning, a pin, a run's facts, a probe's answer — and keeps the instant in
UTC whatever zone it was built in. A node is stamped by the clock alone. The moment a
method of the tree is asked at is an instant as well, and a time without a zone is
refused there; so is a clock handed to the engine that answers one.

### 3. One clock, one spelling, one reading

**The clock is one function**, which answers an instant in UTC, and nothing else in the
application asks the system what time it is. A constructor that takes a clock, as the
engine's does, defaults to it, so a test holds time still by handing one in. The
schedule and a run's duration stay on the monotonic clock, where they were.

**One function spells an instant**: UTC, with a `Z`. Both state files, the API and the
token a pin's form sends back are spelled by it. **One function reads a time back**,
and strictly: text that is no time, and a time without an offset, are refused, in words
that name where the time stood.

### 4. A file that carries a time without a zone is refused whole

`events.json` and `maintenance.json` carry every time in UTC. A file in which one time
has no zone — an event's, a node's `since`, the stop's stamp, any of a pin's three — is
a load failure: nothing of it is taken, that state starts empty, the start is not
refused, and the file is an ERROR line on `/little-sister/state` until the process ends
(ADR-0071). A copy adopted at a takeover is refused the same way, and what the process
holds stands (ADR-0077).

**Nothing is migrated.** Every time in a file the versions before this record wrote is
without a zone, and nothing in the file says whose clock it was. The one reading that
can be right is the reading of the machine that wrote it, of a time its clock has not
changed since, and a reader cannot know that it is that machine. So such a file is
refused like any other, and the versions before do not read what this one writes: an
upgrade may break the code before it.

### 5. Every comparison is made on instants

A pin's expiry, a node's age, which checks shield a node, the gap an instance was not
running, which of two periods began first, the soonest of several pins and how long ago
a link answered: each compares or subtracts two instants, so the answer is the same on
every machine and through every change of a clock. The compare-and-set token of a pin
(ADR-0014 decision 8) stays text — the pin's `set_at` as it is spelled — and is the
same text before a restart and after it.

### 6. A surface spells an instant at its edge

A page writes an instant in the configured zone and format (decision 7), a copied
document adds the offset in force at it, and the API spells it in UTC. Where the
library names an instant in a sentence of its own — the line that says a reachability
pass overran, the log's line that says since when nothing watched — it writes it as a
page does. The envelope serves the same text for the same instant: `schema_version` and
the spec do not move (ADR-0080).

### 7. What ADR-0006 decided and this record keeps

Restated so the superseded record never has to be read.

**General options live in a settings file.** Options that are no secret — the display
timezone was the first — are not hard-coded and have a home of their own: a YAML file,
the `settings` aspect of a configuration root, `config/settings.yaml` (ADR-0031), or
the one file `LITTLE_SISTER_CONFIG` names instead. It is read once at startup into a
frozen `Config`. A missing file or key falls back to its default, and an invalid value
is logged and defaulted. Adding an option is a field and a default. Secrets stay in
`.env` (ADR-0003) and what to monitor in `checks/`: three small, separate surfaces. A
YAML file reads better than environment variables for a growing set of options, and
matches the rest of the configuration.

**A page writes a time in the configured zone and format.** `timezone` is an IANA name,
default `Europe/Berlin`, and `time_format` a `strftime` string. Every time a page shows
— a check's detail, history, events, the system page — is converted where it is shown,
by the `localtime` filter; `zoneinfo` does the conversion, with the `tzdata` package for
portability. What it converts is an instant now, so a page reads the same wherever the
process runs.

**The configured zone reads what an admin types.** A maintenance expiry written without
a zone — a full date and time, a date, a time of day, a weekday and a time — is a wall
time in the configured zone; one that carries `Z` or a numeric offset keeps it. A wall
time that does not exist, or happens twice, at a clock change is refused instead of
silently choosing an instant. What comes out is an instant in UTC, and the tree stores
it as it is: it is no longer turned back into the machine's clock.

**A wall time stays one where it is meant as one.** What a person types — an expiry,
an end of a window (ADR-0098) — and the round times an axis is labeled at are wall
times: without a zone on purpose, and given the configured one. They are the only times
in the application without one.

### 8. A check type hands the library a time with its zone

A time crosses from a check type to the library in two ways, and in both it carries its
zone — whichever zone, since an instant is converted. Under a record's `at`, `started`
or `ended` it is text with its offset (ADR-0082). In a sentence, and in a message a type
logs, it is written by `spans.local_time`, which takes an instant and writes it in the
configured zone and format: the function **refuses a time without a zone**, where it
read one as the machine's clock. A type formats no time of its own — not on the
machine's clock, and not in the UTC its source handed it — so every time a page or the
log shows is in one zone, and the library never guesses whose clock a time was.

The check API's epoch does not move for it (ADR-0049). The surface promised *an instant*
for that name wherever a kept document describes it, and only the function's docstring
said what it did with anything else. A type that handed it an instant is untouched; one
that handed it a time without a zone has its run become an ERROR that names the
refusal, which is the mistake said where it was made.

### 9. The log's lines are stamped in the configured zone, with its offset

The default handler stamps a line in the configured zone and writes the offset in force
beside it — `2026-10-04 13:02:35,893 +0200` — on stderr and in `var/little-sister.log`.
A log is read by people, who compare its times with a page's, and a page's are in the
configured zone (decision 7); the offset is what lets a machine compare a stamp with
UTC, and what tells the two passes of a repeated hour apart. The stamp keeps the shape
it had and gains the offset, as gunicorn's own lines beside it carry one. The shape is
the log's own and not `time_format`, which is a page's.

**The configuration hands the logger the zone the moment it has read it**, before it
says anything of a setting; the configuration imports the logger, never the reverse. A
line is stamped where it is written and not where it was logged, so **the log file is
in the configured zone from its first line**: what the import logged is kept and
written when the start opens the file (ADR-0091 decision 4), and it is stamped then. On
stderr a line carries the machine's clock only where it was written before the zone was
read — one about a settings file that is absent or cannot be read, and the logger's own
about `LOG_LEVEL` — and it carries its offset like every line.

**It stays the default's.** An application that configured logging before the import
keeps its handlers, its level and its own stamp (ADR-0049). gunicorn's own lines keep
the machine's clock — `[2026-10-04 12:56:59 +0200]` — so on a machine whose zone is
another, stderr holds two clocks, each with its offset.

**The engine's memory line follows the log.** Its ten-minute marks are those of the
clock the log is stamped in (ADR-0095 decision 3), which is the configured zone's.

**A start says once, in the log, where the machine's clock is another.** A process has
no portable way to ask its machine for the name of its zone, so the two clocks are
compared by what they show, hour by hour from the start through the year ahead. Where
they differ at the start, the line names both offsets. Where they agree then and part
later, it names the day from which they do: a machine on UTC under a configured
`Europe/London`, started in December, is told of the day in spring. Two zones that show
the same time throughout, `Europe/Paris` under a configured `Europe/Berlin`, are told
nothing. It is a line in the log and no line on `/little-sister`: a note stands at WARN
for the life of the process (ADR-0076), and a machine whose zone is another on purpose
would show its own node yellow for as long as it runs.

### 10. The gate refuses a time built without a zone

ruff's `DTZ` rules are in the family's one selection, `tool.ruff.lint.select`, which the
release check holds six projects to. What holds an instant refuses a time without a
zone where it is stored or compared (decisions 2 and 5). The rules refuse a clock read
and a time built without one at the gate, in the source and in the tests of every
project, and so where the answer is only shown as well.

**A time that is meant as a wall time says so.** The three this library builds on
purpose (decision 7) — the parts of an expiry an admin typed, and an axis's round
times — carry `noqa: DTZ001` under a comment that says why, and so does a test that
builds a time without a zone to see it refused.

**The rules see where a time is built, and not where one is parsed or written**: a
date read from text, a `time.localtime` and a `strftime` pass them. Those are decision
8's.

## Consequences

- **An upgrade starts the event log and the pins empty.** At the first start on this
  version both files of the version before are load failures. `maintenance.json` is
  rewritten at that start and `events.json` at the first save, so the old log and the
  old pins are gone from the directory, and from a keeper's store once the instance
  holds its lease. A pin still wanted is set again.
- **Every instance on one keeper's prefix is stopped before the first one starts on
  this version.** An instance of this version that takes over from a holder still on
  the version before can take neither file that holder wrote: each is an ERROR line,
  fetched and refused again every interval, and what the new holder writes meanwhile is
  not carried to the store.
- **The version before is not started on that state again.** It takes no event log this
  version wrote, and where `maintenance.json` holds a pin it does not start. The way
  back removes that file first.
- **The API's contract does not move.** The values become right where the state came
  from another machine or lived through a clock change, and are what they were
  everywhere else.
- **A clock read or a time built without a zone fails the gate of the six projects the
  selection binds**: the library, the four packages and the deployment that shares it.
  Nothing of what they do changes with it.
- **The log's stamp carries an offset behind the milliseconds**, on stderr and in the
  log file, so whatever parses a line's stamp reads one field more. On a machine whose
  zone is the configured one the time of day is what it was; on any other the log's
  times move to the configured zone's at the upgrade, and the start says so.
- **No promised name carries one of these times** (ADR-0049), and one promised name
  takes less than it did: `spans.local_time` refuses a time without a zone (decision
  8). Nothing in the library hands it one. A source that names no zone is the type's to
  settle where it parses: an HTTP date that says `-0000` names a time in UTC, and Python
  answers it without one.
- **The three cases of the context are tests**, each seen failing on the code before:
  a state written on a machine in one zone and read on a machine in another, the hour a
  clock repeats and the hour it skips.
- **A duration the probe measures no longer jumps with a clock.** It is still the
  difference of two instants; measuring it on the monotonic clock is a change of its
  own.
- **ADR-0014 decisions 8, 11 and 22, ADR-0080 decision 8, ADR-0082 decision 2 and
  ADR-0110 decision 6 are amended.**

## Alternatives considered

- **Read an old file once, on the reading machine's clock, and write it back.** It is
  right only on the machine that wrote the file, of times its clock has not changed
  since — and a keeper's store exists to be read by another machine. A conversion that
  is wrong cannot be told from one that is right afterwards.
- **A zone the deployment declares for its old files.** A setting for one start, and
  wrong for a log that already held two machines' clocks.
- **Times kept as text, in one spelling.** The smaller change. A time stays
  indistinguishable from any other text, and two of them compared as text are compared
  wrongly at a whole second: `2026-10-04T10:51:48Z` sorts after
  `2026-10-04T10:51:48.500000Z`.
- **Every process started with `TZ=UTC`, and the code as it was.** It removes all three
  cases where every machine of a deployment is started so. It is a setting of whatever
  starts the process, which the library cannot hold, and a file written under it still
  says nothing of its zone.
- **Every time in UTC, and none of them with a zone.** The arithmetic is as right, since
  UTC has no clock change. But that a time is UTC then stands in a convention and not in
  the value. Python reads a time without a zone as the machine's own, in `astimezone()`
  and in `timestamp()`, so every edge would attach the zone first, and one that forgot
  would be this record's mistake again, without an error. The type would no longer tell
  an instant from the wall times decision 7 keeps, which a subtraction refuses to mix
  today. And a time a check type handed over without a zone would be taken as UTC
  whether it was or not.
- **The log in UTC with a `Z`, on the machine's clock with its offset, or as it was.**
  The three other answers to decision 9. A log is read beside a page, and only the
  configured zone makes the two one clock; the offset gives a machine what UTC would
  have, and the line a start writes says where gunicorn's clock is another.
- **Storage as it was**, which ADR-0006 chose when it weighed UTC and found no benefit
  for the display. That held for one process on one machine whose clock never changes.
