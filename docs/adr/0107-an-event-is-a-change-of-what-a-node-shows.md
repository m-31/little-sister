# ADR-0107 — An event is a change of what a node shows

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-10-03)
- **Related:** [ADR-0036](0036-addressable-reasons.md) (decision 5, a line's pin;
  decision 7, what a node shows over its lines; decision 11, which this amends),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (decisions 6 to 8, the mark
  and a pin's own transitions, taken one level down),
  [ADR-0042](0042-entries-carry-their-own-code.md) (a node's own status from its coded
  lines), [ADR-0094](0094-a-restart-is-no-transition.md) (the restart, whose decisions
  1 to 3 this amends), [ADR-0099](0099-a-status-that-still-holds-says-since-when.md)
  (decisions 6 to 8, a period and what it says of its beginning),
  [ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md) (decision 3, a
  bound that rests on the log holding every change of what a node shows),
  [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md) (the Events page and its
  switches), [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (decision 7, the
  count of a node's changes),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the kept event
  log), [ADR-0014](0014-maintenance-persistence.md) (the pins),
  [ADR-0119](0119-a-wait-that-ends-by-its-count-writes-a-row.md) (the row that ends a
  wait, and its cause), [ADR-0109](0109-a-node-says-its-children-are-complete.md) (a
  node's removal, and its cause),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (the table
  beside the log, which decision 5's comparisons read),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md) (decision 2, maintenance's own
  words, which decision 3's take),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (the rows
  a configured rule marks, and `shown`),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (the
  rows of a failure marked seen, and why one ended)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The event log followed the code a check reports. What a node shows is worked out from
its lines and their pins (ADR-0036 decision 7, ADR-0042), and where a node's own pin
wrote its set, its edits and its end as events (ADR-0041 decision 8), a line's pin wrote
none (ADR-0036 decision 11). So wherever a line's pin made a node show something other
than what was reported, the log, History and the Time card said what the wall did not
show:

- Pinning a node's one failing line turned it ok, and the pin's end turned it red
  again; neither was in the log. With every line pinned the node showed maintenance
  while History's row said *error*, *current*.
- A new failing line beside a pinned one turned the node red and wrote nothing, the
  reported code having been *error* all along.
- A pinned line that failed again wrote *ok → error* with no mark on it, though the
  node stayed green: a change beneath pins was marked only where every line was pinned.
- Across a restart the first reading was compared with what the log last reported and
  not with what it last showed. A node's pin that ran out while the instance was down,
  over a reading that was what it had been, wrote nothing, and History said
  *maintenance*, *current*, over a node that showed *warn*.

ADR-0102 decision 3 and ADR-0099 decision 1 bound a period by the log's oldest event on
the ground that the log records every change of what a node shows. It did not.

## Decision

### 1. An event is written for every change of what a node shows

Whatever caused it: a reading; the node's pin; a line's pin — set, cleared, expired, or
replaced where a kept file is adopted; or a line that comes or goes on a run beside a
pinned one. Its `old` and `new` are what the node showed before and after, its own
status as the snapshot derives it (ADR-0032 rule 3). A node's pin is set from what the
node showed and ends on what it shows then, which with a line pinned is not what its
check reports.

A node's pin is written whenever it is set, edited or ended, also where the node shows
the same before and after — an edit, or a pin over lines that are all pinned — since its
note is to leave a trace (ADR-0014 decision 9); such a row begins no period (ADR-0099
decision 6). The reading that ends a node's wait by its count writes a row as well,
which says that the status the node shows reached the level above
([ADR-0119](0119-a-wait-that-ends-by-its-count-writes-a-row.md)): the one row of a
reading that changes nothing its node shows, and it begins no period either. Nothing is
written for a line by itself. A line's pin that does not change what its node shows —
one of two failing lines pinned, a note or an expiry edited — is no event, so the log
does not fill with lines, which is what ADR-0036 decision 11 kept out of it.

A failure a person marks seen writes rows of its node
([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
decision 7): its set, its edit and its end, the node's own and a line's alike. A node's
own seen changes nothing its node shows, so its rows go from what the node shows to the
same; a line's go from what its node showed to what it shows.

### 2. A change of the reading that the node does not show is a row of its own, held back

As beneath a node's pin (ADR-0041 decision 6), and now also where only some of the
node's lines are pinned: the row carries the reading's codes and the mark `maintenance`,
the same rule at a line's grain. The Events page lists it as *held back*, and History
and *since* leave it out. A row is marked by what it did — it changed nothing the node
showed — and no longer by whether every line was pinned.

Where one run changes what the node shows and, differently, what its check reports — a
pinned line fails while an unpinned one turns slow — the log writes two rows at that
instant: the node's change, which reached, and the reading's, held back. A row keeps
saying one thing, a status that either reached or was held back, so the page's status
switches and *reached* off answer what a pin hid, that run included. A change only the
reading made is one held-back row, and one only the node made is one that reached.

A rule a deployment configures marks rows too
([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)
decision 11). A change of what a node shows that the rule kept from its parent — one it
makes count for less, a floor holding nothing back — is marked `aggregation` once the
write is whole, as damping's are; a change of the reading the node does not show,
because a rule on its lines counts it for less, is a row of its own, marked
`aggregation` where a pin's is `maintenance`, and one a floor on the lines raised is a
row of no rule's, which the Events page does not list. A reading's row that a seen kept
from its node's parent is marked `seen`, as damping's are. Since a mark does not say by
itself whether the node showed the change, a row carries `shown`, kept in the log only
where it differs from what its mark implies.

### 3. An event carries its cause

A field of its own, beside its reason: a reading; the node's pin, set, edited or ended;
a line's pin, set or ended; a seen, set, edited or ended, on the node or on a line —
`seen-set`, `seen-edited` and `seen-ended`, and `line-seen-set`, `line-seen-edited` and
`line-seen-ended`, the act and the kind; the end of a wait by its count (ADR-0119); and
*removed*, for a node its check has stopped reporting
([ADR-0109](0109-a-node-says-its-children-are-complete.md)). A seen's end carries
`ended` besides, why it ended: a recovery, a worsening, a new occurrence, a part no
longer reported, its end, or by hand. The reason is what it was — the node's lines for
a reading, for the end of a pin and for the end of a wait, the pin's note for a node's
pin — and where a line's pin was set it is that line and the pin's note: the line by
its text, since a slug means nothing once the line is gone. A removal's row is written
for each node removed, and at the first run after a restart for a path the log last
showed a status for (decision 5).

Each surface says the cause in its own words. On the Events page a row that a pin caused
carries a chip beside its status: *set*, *edited*, *maintenance ended*, *line's pin set*,
*line's maintenance ended*. A seen's carries *seen*, *seen changed* and *seen ended*
with why — *seen ended · worse* — and a line's *line seen*, *line's seen changed* and
*line's seen ended*. The row that ends a wait carries *reached*. On the Time card and in
the Copy document a period says what kind of beginning it had, ADR-0099 decision 8 one
level down: *Status ok since 16:24:04, when a line's pin was set* and *Status error
since 18:00:00, when a line's maintenance ended*. A period of maintenance says nothing
more, however it began.

### 4. An event carries what the check reported

At that moment, beside what the node showed. Two things read it, and no page shows it.
The restart reads what each node last reported (decision 5). And the count of a node's
changes in the last hour (ADR-0083 decision 7) counts the changes of what was reported,
which is what it counted before a row could be anything else: a pin's row is none, and
a run that wrote two rows is one.

### 5. A restart replays nothing, and the first reading settles it

Pins come back from their file and write nothing, a line's as a node's; a node's pin
whose period the log no longer holds still records its set (ADR-0094 decision 2). A
node's first reading in the new process is compared twice: what the node shows with
what the log last showed, and what its check reports with what the log says it last
reported. What a node last showed and last reported is kept in a table beside the log
([ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)), and the two
comparisons read the node's entry in it: the rows only where the kept file was written
before the table. Whatever differs is written then, dated by that reading (ADR-0094
decision 3): the node's change as a row that reached, the reading's as one held back.

A pin that ran out while the instance was down ends there. The row's cause is the
pin's end where the node would still show what it showed had the pin held, and the
reading otherwise.

A node that nothing reports to — a branch pinned whole — has no reading to come. The
restart writes the end of its pin itself, at the pin's own expiry, to the `UNDEFINED`
such a node shows: a row that claims nothing but that the pin ended.

### 6. A log written before this is read as it was

The two fields are new keys of an event in the kept log (ADR-0071). An event without
them reads as it did: its cause unsaid, and what its check last reported worked out
from its codes, as ADR-0094 decision 1 described. Nothing is migrated, and the rows
already in a log are not rewritten.

## Consequences

- **ADR-0036 decision 11, ADR-0041 decisions 6 to 8, ADR-0094 decisions 1 to 3 and
  ADR-0083 decision 7** are amended.
- **The log records every change of what a node shows**, which ADR-0102 decision 3 and
  ADR-0099 decisions 1 and 6 rest on: one rule bounds every period a surface states,
  for a node whose lines are pinned too. Its History says what it showed, for the rows
  written from now on.
- **A line's pin costs the log two rows at most**, one when it is set and one when it
  ends, and none where its node's status does not move. A held-back row beneath lines'
  pins replaces a row that was written unmarked: the log grows by the rows of what a
  node showed and its check did not report, which it lacked.
- **The contract does not move.** The JSON envelope carries no events; the kept log
  gains two keys an older reader passes over.
- **A pin set or cleared before a node's first reading after a restart** is written
  from what the log last showed, where it was written from `UNDEFINED`.
- **The counter that makes a node wait before it escalates** counts what the node
  shows too ([ADR-0108](0108-the-wait-before-an-escalation-counts-what-a-node-shows.md)):
  the snapshot, the log and the wait read one derivation.

## Alternatives considered

- **The Time card alone corrected**, naming the reading's status with its period and
  what is shown beside it: one surface says two things, and the log and History go on
  saying what the wall did not show. **Left to the policy round on pins**: the defect
  is in what an event is, and stands whatever a pin's policy becomes.
- **An event for every line**, its pin or its coming and going: the flood ADR-0036
  decision 11 declined, for a question a node's own row answers.
- **The cause in the reason's text only**: the fact is kept, as prose in two tables,
  and the Time card cannot say it. **No cause**: a silenced line reads as a recovery,
  and the pin is found nowhere once it has ended.
- **One row that says both**, what the node showed and what its check reported: tidier
  for a run, and a row is then two statements, of which the status switches and *held
  back* can filter one. **The node's row alone where the node itself changed**: the
  reading's later recovery is then a held-back *ok* from an error the log never
  recorded.
- **What a check last reported, worked out from the rows**, as before: nothing more is
  stored, and it is wrong in one shape — a run in which a pinned line takes over the
  status an unpinned line drops — where the first reading after a restart writes a
  held-back row for a change that did not happen then.
- **A pin's end written at its own instant** where it ran out during downtime: the log
  then says what the node showed while nothing was watching it, which ADR-0094 decision
  3 dates by the reading that saw it.

