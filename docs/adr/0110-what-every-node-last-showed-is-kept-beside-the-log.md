# ADR-0110 — What every node last showed is kept beside the log, and a wait counts from it

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-10-03)
- **Related:** [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (the wait, whose
  consequence on restarts this corrects),
  [ADR-0094](0094-a-restart-is-no-transition.md) (a restart is no transition, which this
  completes for a node the log holds no row of),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (decision 5, a node's
  first reading after a restart; decisions 1 and 2, what writes a row),
  [ADR-0108](0108-the-wait-before-an-escalation-counts-what-a-node-shows.md) (the
  counter counts what a node shows; decision 2, what a pin publishes),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the kept files, of
  which `events.json.gz` gains a key),
  [ADR-0001](0001-in-process-threaded-engine.md) (the log's bound), [ADR-0014](0014-maintenance-persistence.md) (reaping what no check
  covers, and a pin's creation, which the store keeps),
  [ADR-0077](0077-authority-follows-the-lease.md) (a file adopted in a running
  process), [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 5, a
  node its check no longer returns), [ADR-0032](0032-status-contribution-boundary.md)
  (rule 3, one derivation), [ADR-0099](0099-a-status-that-still-holds-says-since-when.md)
  (what a period's beginning says, which decision 5 keeps),
  [ADR-0119](0119-a-wait-that-ends-by-its-count-writes-a-row.md) (the row that says a
  wait had ended, and the key decision 1 reads),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (a pin's creation and an entry's
  `since` are instants),
  [ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md) (the
  second period an entry of a node above others keeps),
  [ADR-0134](0134-the-state-is-compressed-and-stamped.md) (the event log kept compressed),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (decision 2, maintenance's own words, in which a pin's period is said)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node may wait before it escalates (ADR-0083): it publishes a worse status to its
parent only after `escalate_after` consecutive readings of it. The counter is memory,
and ADR-0083 said what a restart does to it: a node in the middle of an escalation
*begins its count again*. It did not. A node's first reading in a new process met no
counter and was published at once, so with `escalate_after: 3`:

- A node that read *ok* before the stop and failed at its first reading after it
  reached its parent at that reading, where without a restart the parent counts *ok*
  for two readings more.
- So did a node one *error* reading into its wait when the instance stopped.
- Every failure a restart found skipped its wait.

A restart is no transition (ADR-0094): a node's first reading is compared with what the
restored log last recorded for it. The same comparison can start the count, and two
things the log does not say stood in the way.

*Whether a wait had ended.* The reading that completes a count changes nothing the node
shows, and it wrote no row. A node one reading into its wait and one whose failure
reached its parent a week ago left the same last row, *ok → error* marked `damping`.

*What a node showed, where the log holds no row of it.* The log is bounded for the whole
tree (ADR-0001), and a restart writes nothing for a node that reads what it read. A node
whose last change is older than the log reaches has no row, so its first reading after
a restart was a first reading: published at once, and written as *undefined → …*, the
transition ADR-0094 meant a restart not to be. In a kept log of 1,000 rows reaching back
six days, 61 of 88 nodes had as their last row such a first reading, a day or two from
the log's old end.

## Decision

### 1. The count starts from what the node last showed

A node's first reading in a process is counted from what the node last showed (decision
2), as its events are measured from it: the counter takes that status as published. A
worse first reading then waits like any other, its parent counting what the node showed
before the stop (ADR-0083 decision 2); a reading that is what the node showed, or
better, is published at once.

**A wait that had ended stays published, and one under way goes on.** The reading that
completes a count writes a row
([ADR-0119](0119-a-wait-that-ends-by-its-count-writes-a-row.md)), and an entry of the
table says what a waiting node publishes (decision 2), so the kept file tells the two
apart. Where a node's wait had ended, the status it shows is taken as published: a
failure that stood stays published through a restart, and no restart takes an alarm
back. A node that was in its wait when the instance stopped goes on waiting: it
publishes what it published before, and its count resumes with the reading its held row
records as the first. A file written before the key says of no node that it waits, and
there a row held by the wait is read as an escalation made.

A node nothing is kept of has nothing to count from, and its first reading is published
at once, as ADR-0083 decision 3 has it. So is the end of a pin that ran out while the
instance was down, which that reading writes (ADR-0108 decision 2).

### 2. The kept log says what every node last showed, beside its rows

`events.json.gz` carries a table beside the events, `nodes`: for each node, what it
`shows` and what its check last `reported`, by name — the two things a first reading is
compared with (ADR-0107 decision 5). It is the tree's own derivation at the moment of
the save (ADR-0032 rule 3): for a node a check has written in this process, its own
status and its reading; for one not written yet, what was restored. A node that shows
nothing and whose check reported nothing has no entry, unless the tree saw it begin to
show nothing (decision 5).

Either code changes only with a row (ADR-0107 decisions 1 and 2), and so does what an
entry says of its period, so the table changes only when the log does and costs no
write of its own (ADR-0071 decision 3). The log keeps its bound and its meaning: 1,000
rows, complete since the oldest.

An entry of a node that waits before it escalates says also what the node `publishes`
meanwhile, from the row the wait held back to the row that ends the wait (ADR-0119
decision 4).

### 3. A restart reads the table

Where the kept file carries the table, a node's first reading is compared with its
entry, whether or not the log still holds a row of the node. The same reading writes
nothing, so a quiet node writes no *undefined → …* at a start; a change is written from
what the entry says; and the count starts from what it shows (decision 1). The pins'
replay and the instance's own gap read it the same way (ADR-0094 decisions 2 and 4).

A file written before the table is read as it was: what each node last showed and last
reported is worked out from its rows (ADR-0094 decision 1, ADR-0107 decision 6), and a
node without a row has a first reading. The next save writes the table.

A file adopted in a running process (ADR-0077) brings its table with it, for the nodes
no check has written yet; a node written already goes on comparing with itself.

### 4. An entry goes when no configured check covers its node

At startup, as a pin is reaped (ADR-0014): an entry on no configured check's line, and
not on the instance's own, is dropped. Every other entry is kept until a reading
replaces it — also that of a node that vanished beneath a check that still runs, a few
bytes, until its check says its children are complete and no longer returns it
([ADR-0109](0109-a-node-says-its-children-are-complete.md) decision 5).

The removal does not drop the entry at once: it rewrites it as a period of nothing that
began at the removal, by the cause *removed* — decision 5's rule for a node that begins
to show nothing — so the node's return is a change the tree saw, across a restart too,
and a replayed pin reads from the entry that its node is gone. The entry goes when the
removal's row has left the log, unless a pin is held against the path; and an entry that
says its node showed nothing is dropped at the removal, there being no period to end.

### 5. An entry says when its node's period began

Beside the two codes an entry carries `since`, the instant the period the node is in
began, and how it began: `was`, what the node showed before, and `cause`, what moved it
(ADR-0107 decision 3) — the three things a period is read off its first row (ADR-0099
decisions 6 and 8). Where the beginning is a bound (ADR-0099 decisions 1 and 9) the
entry says `since` and `before`, and neither of the other two. So a period's beginning
outlives its row: the Time card, History and the Copy document read it from the entry
where the log no longer holds the row that began the period.

The entry of a node above others keeps a second period, of what it shows, in a key of
its own beside these: since when — or since and before, where the beginning is a bound —
what it showed before, what moved it, and `by`, the node whose change it was
([ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)). It is
written at every change of what the node rolls up to, staleness included, carried across
a restart until each node's unit has run, and seeded at the first start on its release
from the log that start restores. A release before it reads the keys it knows and passes
over the new one.

The tree keeps it as it writes. A row that changes what a node shows begins its period;
an edit of a pin, and a row of a reading the node did not show, begin none; and a node's
first reading with nothing kept of it is a bound at that reading, except on the
instance's own branch, which the engine names to the tree as the one that begins with
its process. A first reading that shows nothing bounds nothing, and neither does one
beneath a pin set before it: the pin is something kept of the node, its period stands,
and what the node shows once the pin has gone is a change the tree saw. A node that
begins to show nothing has a period like any other, and its entry is kept for it: what
it shows next is then a change the tree saw, across a restart too.

A file written before these keys is read by its rows, as one written before the table
is (decision 3): the last period the rows hold for a node gives its beginning, and where
they hold none the entry takes a bound — the node's oldest row of the period; the log's
oldest event, where the log has no row of the node; or, where the log is empty, the
node's first reading in the process that reads the file. It is taken once, where the
tree first meets the node without a beginning, only for a node that shows something,
and the next save writes it. A restart and the forgetting at startup carry these keys
as they carry the two codes (decisions 3 and 4). An adopted file's beginning is taken
for every node no check has written yet, and for one written already where the file
says the node shows what it shows; otherwise that node keeps what this process saw of
it.

### 6. A pin the tree did not see set begins at its creation

A pin's period begins where the pin was set (ADR-0099 decision 6), and a pin set or
edited while the instance runs writes its row at the store's own instant for that
write. Where the tree only learns of a pin — a start replays it over a log that does
not hold its period (ADR-0094 decision 2), or it arrives with an adopted store
(ADR-0077) — the row is written then and dated then, and says nothing of when the pin
began. The store does: it keeps every pin's creation (ADR-0014). So the period begins
at the pin's creation, what the node showed until then ends there, and the entry
carries that instant with the cause of a pin's set.

An entry that says a pinned node's `MAINTENANCE` began later than its pin was created —
the date of an earlier replay, or a bound — takes the creation as well when the pin is
replayed. One that began no later stands: the node showed `MAINTENANCE` before it was
pinned. Where the log's rows say the node began to show something else after the pin
was created, they stand as they are, and the period begins at the row the tree wrote. A
line's pin dates nothing: what a node shows with a line pinned is its reading's to
say, and its first reading is a bound like any other.

A pin's creation is an instant wherever a pin exists
([ADR-0120](0120-every-stored-time-is-an-instant.md)): the store's file is read
strictly, and a pin cannot be built with a time without a zone. An entry's `since` is an
instant in UTC as well, and one without a zone refuses the file whole, as any entry of
another shape does.

## Consequences

- **ADR-0083's consequence on restarts is corrected.** The counter is memory still,
  and a restart no longer re-arms it: it counts from what each node last showed.
- **ADR-0094 holds for every node**, and its decisions 1 and 2 say so: a restart
  writes no row for a node that reads what it read, also one the log holds no row of.
- **A failure a restart finds waits**, wherever its node waits; one that stood before it
  is published at the first reading; and a wait under way at a stop goes on.
- **The kept log gains its keys**, which an older reader passes over, and ADR-0071
  decision 2 says what it holds. `Event` does not move; the envelope carries the two
  periods since ADR-0132 (decision 7).
- **A quiet node keeps its *since*.** Once its row has left the log, its Time card,
  History and Copy document read the entry (decision 5), and no restart gives it a row
  again, whose date was the restart's. A period whose beginning was lost before the
  table kept it reads *since before* a bound that no longer moves (ADR-0099 decision 1).
- **An entry keeps one beginning, the current period's.** History lists the periods the
  log holds and the one that holds: once a node changes, the period it left is a row
  only while the log holds the row that began it.
- **The first start on a file written before the keys is where its bounds are taken.**
  A node the log holds no row of is bounded by the log's oldest event; one that a file
  without the table does not name is first read at that start, and bounded by that
  reading (ADR-0099 decision 9). Each keeps its bound until the node changes.
- **A pinned node says *since* what its pin's block says.** After a start on a log
  that had lost the pin's set, the Time card read *since* that start, days after the
  instant the block above it stated; it reads *since* the pin's creation, and an entry
  that already carries a start's date is corrected at the next replay.
- **The Events page still lists a replayed pin as set at the start.** The row says when
  this log learned of the pin, and is the only row the log has of it; when the pin was
  set is said by the node's period and by the pin's block.
- **ADR-0109's removal reads the same entry**: the path it writes *removed* for at the
  first run after a restart is one the table names, and the removal rewrites the entry
  as a period of nothing that began at the removal (decision 4).
- **A restart can lengthen a wait.** The count itself is not kept, so a node that waits
  three readings or more reaches later for a restart in the middle of its wait, by the
  readings between its held row and the stop (ADR-0119 decision 5).

## Alternatives considered

- **Every row held by the wait read as a wait under way**, where a file does not say
  which it was: the count begins again from what the node showed before the row, as
  ADR-0083 first had it. Every standing failure of a node that waits is then
  held again at the restart, its parent counting *ok* meanwhile: an alarm taken back and
  raised again.
- **A node without a row keeps its first reading**, published at once: nothing to
  build, and the rule reaches only the nodes that changed within the log's reach — under
  a third of them in the log above.
- **A failing first reading waits too**, its parent counting nothing of the node
  meanwhile: it reaches every node, and holds again every failure older than the log
  reaches.
- **A log that never drops a node's last row**: one kind of record, and the oldest row
  is then no longer where the log begins to be complete, on every surface that states
  that bound (ADR-0099 decision 1, ADR-0102 decision 3).
- **The counter kept in a file**, which ADR-0083 declined: a value whose purpose is to
  be forgotten within minutes.
- **A replayed pin as a bound**, *since before* the start: true, and less than the
  pin's block on the same page states. **The replay's row dated the pin's creation**:
  the log would hold a row older than the rows before it, and the Events page a pin set
  at an instant the instance did not write it.

