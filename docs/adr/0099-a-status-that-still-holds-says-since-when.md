# ADR-0099 — A status that still holds says since when

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0027](0027-observation-timestamp-semantics.md) (the observation a
  node's time is), [ADR-0094](0094-a-restart-is-no-transition.md) (a period that reaches
  back across a restart, and a container's `UNDEFINED`, which names no period),
  [ADR-0081](0081-an-instance-node-states-a-tolerance-not-a-period.md) (*checked
  every*, a claim only a check makes),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (decision 8, what a result
  rolls up to), [ADR-0039](0039-status-rollup-semantics.md) (the roll-up),
  [ADR-0006](0006-config-file-and-timezones.md) (the configured timezone the instants
  are written in), [ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md)
  (decision 3, History's row for a period the log holds no start of),
  [ADR-0014](0014-maintenance-persistence.md) (decision 9, the event an edit of a pin
  writes), [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (a pin edited in
  place), [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)
  (decision 5, the kept entry that says when a period began),
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (decision 7, a first reading
  is no change), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) and
  [ADR-0040](0040-what-a-failing-check-becomes.md) (what a measurement not taken does,
  and one that fails),
  [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) (decision
  6, the period of a pinned node nothing has written)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node's Time card stated its current status as *Status error from 09:12 until 17:45*.
The first instant began the period; the second was the latest reading, not an end, and
the status still held. An active failure read as one that had stopped, a maintained node
read *from … until* a time in the past beneath a banner naming the pin's expiry
tomorrow, and wherever the latest reading was the one that began the period the card
read *from 19:32:39 until 19:32:39* — after a restart, every node whose reading changed
across it. The node's Copy document wrote the same sentence, and History's current row
the same *until*.

Two more places said a time or a code as something it was not. The `file` check wrote an
age past an hour in hours and minutes — more than eighty days as *1987h14m* — and the
maximum it was configured with as it had computed it rather than as it was written, a
week as *168h00m*. And the engine logged a run by its node's own code: a check whose
root declares nothing above children that grade — host metrics' is one — logged
*UNDEFINED* on every run, whether a disk was full or not, although what the run rolls up
to is what a reader of the log wants, and the engine already works it out for the
reading it keeps.

And a pin did three things to its node's periods. Every event of a node began a
period, and an edit of a pin is an event, deliberately (ADR-0014 decision 9): a node
silenced at 11:19 whose note was corrected at 11:20 read *maintenance since 11:20*,
and History listed two maintenance periods. A pin is edited in place and keeps its
expiry (ADR-0104), so a corrected word in a note is the common edit. The row that held
showed the node's own lines beneath the pin, and nothing on a branch, where an ended
one showed the note the pin was set with. And the end of a pin read as the moment the
status beneath it began: a node ok for days read *ok since 11:29* after ten minutes
under a pin, though its check had read nothing else in between.

The bound a period was stated by moved. A node whose one transition had left the
bounded log read *since before* the log's oldest event, which is a later instant every
time the log drops a row: on a busy instance always about as far back as the log
reaches, for a node that had not changed in a year. And a node's first reading began
its period, *undefined → ok* and *ok since* that instant. That is fair to a check added
today, and false of the same row where a restart wrote it for a node whose history had
left the log: in a kept log of 88 nodes, 61 had such a row as their last and read
*since* a restart, as if they had changed then.

## Decision

### 1. A status that still holds is stated since when, and when it was last observed

The Time card says *Status error since 09:12* and, on a line of its own, *Last observed
17:45* — also where the two are one instant. *Until* belongs to a period that has ended.
When a period began does not leave with the log's rows: the kept table beside the log
says it for every node (ADR-0110 decision 5), so a node whose one transition has left
the bounded log still reads *since 09:12*. Where no beginning is known the period is
stated by a **bound**, *Status ok since before 18:51*: the furthest back the tree can
vouch that nothing changed. That is the node's first reading, where it was first seen
showing its status (decision 9); the node's oldest event of the period, where the
period's first row had left the log before the table kept it (decision 6); and the
log's oldest event, where the log held no row of the node. A bound is taken once and
kept until the node changes: it does not move forward as the log drops rows. History's
row for the period states the same (ADR-0102 decision 3). A node that declares nothing
above nodes that report has no period of its own and says *Observed …*, and one nothing
has written *Not yet observed*, as before (ADR-0027, ADR-0094 decision 5) — unless it
is pinned: it has shown *maintenance* since its pin, and states that period
([ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) decision 6).
The node's Copy document says the same in its own labels: ***Status error** since …*,
***Status ok** since before …* and ***Last observed:** …*. What a period is, what one
says that a pin's end began, and what a first reading begins are decisions 6, 8 and 9.

### 2. History calls the period that still holds *current*

Its row's *Until* reads *current*; a period that has ended keeps its end. In the
history the tree derives, a current period's `until` is still the latest observation,
and the Status page is where that instant is stated.

### 3. A node is observed, not checked

The instant a node was last written is when it was *observed*: the word ADR-0027 and
[`project.md`](../project.md) give it, and the one the envelope's `observed_at` carries.
A stale node says *Stale — last observed 12m ago*, on its page and in its Copy document,
where it said *checked*: a node the instance re-asserts on its own tick goes stale too,
and nothing checks it — ADR-0081's reason for leaving *checked every* to a check.

### 4. A check writes a measured span and a configured interval in the library's words

The `file` check writes how long ago its file changed as a span — past a day in days and
the hour beside them, *82d 19h* — and its maximum as it was configured, *20m* or *1w*,
in its reason and in its configuration: `format_span` and `format_duration`, the
library's two answers to the two questions. The sentence stays the check's own.

### 5. A run's log line says what it rolls up to beside its own code

`check /host: UNDEFINED, rolls up to ERROR (1234 ms)`, and `check /repos: OK, rolls up
to ERROR (…)` for a root that declares a code above a failing child. What a run rolls up
to is taken from its result, as the code of a reading it keeps is (ADR-0087 decision 8),
so neither another check on the same mount nor a pin reaches it. A leaf's line, and any
run whose own code is its roll-up, is as it was: the first code on every line is the
node's own.

### 6. A period is a run of events that show the same status

An edit of a pin is an event and no period. It stays in the log, where a rewritten
note or a longer window leaves its trace (ADR-0014 decision 9), and the Events page
lists it with the note it wrote. The node showed `MAINTENANCE` before it and after it,
so its period began where the pin was set: the Time card and the Copy document state
*since* the set, and History shows one maintenance row, from the set to the pin's end.
The kept table holds the set's instant, so the period reads *since* the set also once
the set has left the bounded log. Where the tree did not see the pin set — a start
replays it over a log that no longer holds it, or a store is adopted — the period
begins at the pin's creation, which the store keeps: the instant the pin's own block
states (ADR-0110 decision 6). Only a maintenance period that has ended, and whose set
had left the log, begins before the oldest edit the log keeps of the node — *before* in
History's row: decision 1's bound, from the node's own oldest event.

### 7. A maintenance row shows the pin's note as it last stood

An ended row shows the wording the pin had when its period ended. The row that holds
shows the stored pin's note as it stands, on a pinned branch too, which nothing writes
and whose row was empty. Earlier wordings stay on the Events page, each with the edit
that wrote it, and what the check says beneath the pin stays on the Status page. A
check that reports `MAINTENANCE` itself has no pin and keeps its own words.

### 8. A period that a pin's end began says so

A clear — and an expiry, which is one — goes on beginning a period: the node began to
show its status then. The Time card and the Copy document say what kind of beginning
it was: *Status error since 18:00:00, when its maintenance ended* — a pin's, or one
its check reported. A period a reading began says nothing more, and neither does the
pin's own. History's rows are as they were: the maintenance row ends at that instant
and the next begins there. How long the check has read what it reads is not stated
there; the transitions held back beneath the pin are on the Events page, marked *held
back*.

### 9. A first reading is a bound

A node's first reading with nothing kept of it is no beginning the tree saw: the node
was already what it shows when it was first seen. Its period is stated *since before*
that reading — for a check added to the configuration, for a child a check reports for
the first time, and for the row a restart wrote, into a log kept before ADR-0110, for a
node whose history had left it. A first reading that shows nothing bounds nothing:
there is no status to state, and the node says when it was observed (decision 1). What
a node counts as its changes reads a first reading the same way: it is no change
(ADR-0083 decision 7).

A beginning is stated exactly where the tree saw it happen: a change from one status a
node showed to another, a pin set or ended, and a first reading on the instance's own
branch, which begins with its process (ADR-0094 decision 4). A log written before this
decision does not always tell the two apart. A period there is read as a bound where
its first row is the node's oldest in the log, comes from `UNDEFINED` and was written
by a reading. A real change out of an `UNDEFINED` the node showed, whose earlier rows
the log no longer holds, then reads *since before* too, which is less sharp and not
false: a change is always seen by the reading after it.

### 10. No gap ends a period

A period ends where the node shows something else, and nowhere else. A measurement that
is not taken — the instance not running, a run that hangs, a child its check leaves out
of a result — ends nothing, however long it is missing. While the process runs the node
goes stale after its tolerance (ADR-0005, ADR-0079), which is said where the node is
drawn and written nowhere; and when readings return with the same status the period
goes on as one, across a restart too (ADR-0094). A measurement that is taken and fails
is a reading (ADR-0040): a check that cannot reach its object reports that, the node
shows it, and the period ends there like any other.

## Consequences

- **ADR-0094's consequence** that a node reading what it read before says *from* the
  moment its period began now says *since* it, and that record says so.
- **One rule bounds every period a surface states** — the Time card on a node's page,
  on a branch's and in its poll, the Copy document and History's row for the period
  that holds — so none of them can bound a period another does not.
- **The contract does not move**: the envelope carries no period, and `timestamp` and
  `observed_at` keep their meaning.
- **ADR-0014 decision 9 stands**, and says what its event is not: the edit is in the
  log and on the Events page, and begins no period.
- **A pin edited before this reads as one row from now on**: periods are derived from
  the log on every read, so nothing stored changes and no event is lost.
- **A period says what the node showed before it, and whether its beginning is a
  bound**: one that follows `MAINTENANCE` began where the node's maintenance ended, and
  a bound says nothing of how the period began.
- **A new check's node reads *since before* its first reading** — on its Time card, in
  its Copy document and in History's first row — where it read *since* it.
- **A bound no longer moves**: a quiet node keeps the *since before* it was first given,
  across restarts, until it changes; and one whose beginning the table kept reads
  *since* that instant however far the log has moved on.
- **Where the measuring stopped is said by the node's *Last observed* and its stale
  mark, and by nothing in its periods**; the time the instance was not running is on
  the instance's own node (ADR-0094 decision 4).
- **A line's pin is an event where it changes what its node shows**
  ([ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md)), so these rules bound
  the periods of a node whose lines are pinned too, and a period that a line's pin
  began says so as decision 8's does: *when a line was silenced*.
- **A `file` check's reason reads differently**, and so does its configuration's *max
  age*. Neither is a stored key, and the reason's text changed with every run already.
- **A healthy container's log line is longer** — `UNDEFINED, rolls up to OK` on every
  run — and a search of the log for `ERROR` finds a run whose children failed.
- **Where a pin's expiry is shown does not change**: the banner and the Maintenance card
  keep it, and their order is the maintenance pages' question.

## Alternatives considered

- **Since only where the two instants are one** leaves an active failure read twice
  reading as one that has ended.
- **Labeled facts on the page, as the Copy document writes them**, turn the card's
  sentences into a form, with this decision underneath.
- **Last verified or last checked**: a node the instance re-asserts is observed, and
  *verified* claims more than a reading does.
- **A bound that follows the log's oldest event**, as it was: nothing to keep, and a
  statement that weakens with every row the log drops. **The first start on the kept
  table as the bound's date**: an onset the tree guesses.
- **A first reading as a beginning**, as it was: fair to a new check, and every row a
  restart wrote goes on reading as a change. **A first reading told from a restart's row
  in an old log**: only by how close the row stands to a start of the instance, which is
  a guess. **A word on the event for a first reading**: the log would say it, and
  `Event` and every reader of a cause move for something the tree needs to know only of
  the period that holds.
- **A gap past a limit ends the period**, with `UNDEFINED` between: two rows for every
  node at every long outage, the flood ADR-0094 ended, and the last reading's time kept
  for every node across a restart. **The gap noted on the period where it is read**,
  from the instance's own periods: that is only what the instance missed, where a node's
  not knowing is also its transport's and its dependency's, a view of its own to design.
- **Since reaching back to the set while History keeps a row for each edit** has two
  surfaces bound one period two ways; **every event a period, as it was**, dates a
  silence by its last correction.
- **The note the pin was set with** shows a wording its author corrected; **every
  wording in order** makes a row a log, which the Events page is; **the node's own
  lines in the row that holds** says under *maintenance* what the Status page says
  beneath the pin, and nothing on a branch.
- **The bare instant** for a period a pin's end began reads as the moment the node
  broke or recovered. **The reading's own start beside it**, taken from the transitions
  held back beneath the pin, and ***since* as the reading's, with a pin's window a row
  laid over the reading's periods**, each state two timelines at once, which is a view
  of its own to design.
- **Days in the check's own ladder** is a second ladder for the same kind of number;
  **the file's modification time in the sentence** is on the node's page already, in its
  Measured card.
- **The kept reading's code in the code's place** changes what the first code on some
  lines means, and a root that declares OK above a failing child still says OK; **the
  roll-up first** changes it on every container's line.

