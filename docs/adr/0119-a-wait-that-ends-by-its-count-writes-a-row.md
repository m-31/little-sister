# ADR-0119 — A wait that ends by its count writes a row

- **Status:** Accepted
- **Date:** 2026-10-04
- **Related:** [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (the wait, and
  decision 5, what the log says of it),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (what writes a row,
  and an event's cause),
  [ADR-0108](0108-the-wait-before-an-escalation-counts-what-a-node-shows.md) (what the
  counter counts, and what a pin publishes),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (decision 1,
  what a restart counts from; decision 2, the table whose entries gain a key),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 5, a transformed contribution
  names its rule), [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (decision 6,
  the mark, and the one sentence that defines it),
  [ADR-0084](0084-a-check-may-be-reached-through-another.md) (the shield, whose end
  writes no row), [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md) (the
  Events page's switches),
  [ADR-0099](0099-a-status-that-still-holds-says-since-when.md) (decision 6, a row that
  begins no period), [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)
  (the kept event log), [ADR-0001](0001-in-process-threaded-engine.md) (the log's bound)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node that waits before it escalates (ADR-0083) shows a worse status at once and
publishes it to the level above only after `escalate_after` consecutive readings of
it. The row of that change is written when the node shows it, marked `damping`: held
back. The reading that completes the count changed nothing the node showed, so it wrote
nothing, and nothing else said that the failure had reached.

So the log held the same one row for a failure that turned the wall red as for one
that was gone a reading later. The Events page listed both as *held back*; and with
that switch off, among what *reached*, a failure that reached after its wait was not on
the page — the newest row of such a node there was its last recovery, while the wall
showed it red. ADR-0041's sentence for the mark, *an unmarked event is one that
alarmed; a marked one is one that didn't*, held of a row at its moment and said nothing
of the readings after it.

A restart could not tell the two apart either. ADR-0110 decision 1 read every row held
by the wait as an escalation made, and paid for it with one case: a wait under way at a
stop was cut short by it.

In a kept log of 1,000 rows reaching back six days, 335 were held back by the wait, on
fourteen nodes. Going by how long each stood before its node's next row, about a third
of them, 108, were read often enough to reach; no row said so.

## Decision

### 1. The reading that completes a count writes a row

When a node's wait ends by its count — at the reading that shows the held status for
the `escalate_after`-th time in a row — the log gets a row of that node: the status it
shows, as what it showed before and as what it shows, unmarked, dated by that reading,
with the node's lines as they stand then. Its cause is a word of its own, `reached`
(ADR-0107 decision 3). It is the one row a reading writes that is no change of what its
node shows: the node has shown the status since the held row, and what changed is what
the level above counts.

The row reached, so it carries no mark, and the held row before it keeps its own: that
change did not alarm when it was written. Each row says one thing of one moment, and
ADR-0041's sentence holds of both.

It begins no period, as an edit of a pin begins none (ADR-0099 decision 6): History,
the Time card and a Copy document go on saying *since* the row the node began to show
its status with. And it is no change of what the check reported, so the count of a
node's changes leaves it out (ADR-0083 decision 7).

### 2. Only a wait that ends by its count writes it

A wait ends in other ways, and each writes its own row or has none to write:

- a recovery, or another status, is a change of what the node shows and writes that
  row, as before;
- a pin, on the node or on its lines, publishes what the node shows then (ADR-0108
  decision 2), with the pin's own row;
- a node that does not wait, and a node's first reading, are published at once and
  were never held: their row is unmarked already;
- a node that goes stale reaches its parent without a reading (ADR-0083 decision 4),
  so there is no reading to date a row by;
- and a count that completes while the node is reached through a failing check
  (ADR-0084) writes nothing, because nothing reached: the shield holds the node back
  still.

### 3. On the Events page the row says *reached*

In a chip beside its status, as a pin's row says *set* or *maintenance ended*: the row
of a node that shows *error* reads *error*, *reached*. No pin wrote the row, so the
chip does not wear a pin's tint: it wears the pair of the status its row shows, on a
surface of its own and ruled in its ink.

The row is a reading's, and it reached: the *readings* switch lists it, and *reached*
lists it where *held back* lists the row before it. With *held back* off, the page
lists what alarmed, and when.

### 4. The kept file says which nodes are waiting

An entry of the table beside the log (ADR-0110 decision 2) says what its node
`publishes` while the node waits: the status the level above counts meanwhile. The key
stands from the held row to the row that ends the wait — this record's, a recovery,
another status, a pin's — so it changes with a row and costs no write of its own. The
one wait that ends without a row is one behind a shield (decision 2), and there the
table changes by itself.

### 5. A wait under way at a stop goes on

A restart reads the entry. A node that was waiting when the instance stopped goes on
waiting in the next process: it publishes what it published before, and its count
resumes with the reading its held row records as the first. So a wait of two readings
ends at the first reading afterwards that still shows the status, one reading on each
side of the restart, and writes its row there; a longer one counts on. The readings
between the held row and the stop are not kept — the counter is memory still
(ADR-0083) — so a restart can lengthen a wait by them, by `escalate_after` less two
readings at most.

A node whose wait had ended has no such key. The status it shows is taken as
published: a failure that stood stays published through a restart, and no restart
takes an alarm back (ADR-0110 decision 1). A file written before the key says of no
node that it waits, and is read as it was, every row held by the wait as an escalation
made.

## Consequences

- **The log holds one row more for each wait that completes.** In the log above that is
  about one row in ten, and its six days would be nearer five and a half.
- **ADR-0110 decision 1 states the restart's rule as decision 5 has it**: a wait under
  way at a stop is no longer cut short. A restart no longer hastens an escalation, and
  where a node waits three readings or more it can delay one.
- **ADR-0083 decision 5 is amended, and ADR-0107 decisions 1 and 3 name the row and
  its cause.**
- **The kept log gains a cause word and its table a key.** An older reader passes over
  the key, and lists the row without a chip, among its *pins*.
- **The end of a shield still writes no row.** A change held back while its node is
  reached through a failing check reaches when that check recovers, or goes stale, and
  the log does not say when.
- **The envelope does not move.** An event is not part of it, and `contribution` and
  `damping` keep their shape.

## Alternatives considered

- **The held row amended with the instant it reached.** No row more. A row would change
  after it was written, and it stays dated at the failure's beginning: a window on the
  Events page that begins later misses the reach.
- **The restart cutting a wait short, as ADR-0110 had it**, with the row written at the
  first reading afterwards. An escalation a restart hastens is the alarm the wait is
  configured against, and it comes with every restart made while a subject is
  failing briefly.
- **The count kept in the entry.** Exact across a restart; it changes with every
  reading of a wait, so the kept file would be written at each, which ADR-0110 decision
  2 avoids and ADR-0083 declined.
- **The shield's end in the same change.** Its end is another node's reading, or none
  at all where staleness lifts it, and what reached is a comparison with what the level
  above last saw of the node, which the tree does not keep. It is a round of its own.
- **Nothing.** The log keeps its reach, and goes on listing a failure that turned the
  wall red as held back.
