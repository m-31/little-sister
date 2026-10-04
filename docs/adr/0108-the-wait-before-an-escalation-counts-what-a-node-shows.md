# ADR-0108 — The wait before an escalation counts what a node shows

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (the wait, whose
  decision 1 this amends),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (what a node shows, as
  the log records it, and an event's cause), [ADR-0036](0036-addressable-reasons.md)
  (decision 5, a line's pin; decision 7, what a node shows over its lines),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (a node's pin),
  [ADR-0042](0042-entries-carry-their-own-code.md) (a node's own status from its coded
  lines), [ADR-0032](0032-status-contribution-boundary.md) (rule 3, one derivation;
  rule 5, a transformed contribution is visible)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node may wait before it escalates (ADR-0083): it publishes a worse code to its parent
only after `escalate_after` consecutive readings of it. The counter counted the code
the check **reported**, and ADR-0083 decision 1 said why: the reported code and the
node's own status differ only where a pin is involved, and a pinned node contributes
nothing anyway. A node with one of its lines pinned does contribute, and what it shows
is not what its check reports (ADR-0036 decision 7). So with a line pinned the counter
counted readings the node did not show, and with `escalate_after: 3`:

- A pinned line that failed for three readings spent the wait beneath its pin. The
  node showed *ok* throughout, while its card said *1 of 3 to escalate* and its page
  *Showing error*; the first failure of an unpinned line then reached the parent at
  once.
- A pinned line that flapped kept a failure the node showed from its parent for as
  long as it flapped: the reported code was a different worse code at every reading,
  so the count started over each time. A node showed *warn* for eight readings and its
  parent counted *ok* throughout.
- At a pin's end the readings beneath it had counted: a failure older than the wait
  was published the moment its pin ended, and a fresher one waited out the rest.

## Decision

### 1. The counter counts what the node shows

Its own status, as the snapshot derives it and the log records it (ADR-0107 decision
1): one derivation for the three. A reading in which the node shows what it showed is
one more reading of it, whatever its pinned lines did; a different worse status
restarts the count; and a recovery, a first reading and a move through an unranked
status are published at once, as ADR-0083 decision 3 has them. Beneath a node's own
pin, or with every line pinned, the node shows `MAINTENANCE`, which is unranked: the
counter holds nothing there.

So the hold a node states — the count on its card, the sentence on its page, the
`damping` mark on its event — is always about the status the node shows.

### 2. A change that a pin made is published at once

Where a pin's set or its end — cleared, run out, reaped, or replaced where a kept file
is adopted — changes what a node shows, the counter takes the new status as published.
Only a reading starts a wait: a row that a pin caused (ADR-0107 decision 3) reached,
and is never marked `damping`. A pin's set can only take a failure away, which is a
recovery. A pin's end can uncover one, and that is no new reading to doubt: the check
has been reporting it beneath the pin.

A pin that changes nothing the node shows changes nothing of a wait under way. Where
one of two failing lines is un-pinned while the other's failure is still being counted,
the node goes on waiting.

## Consequences

- **ADR-0083 decision 1** is amended: its second paragraph, on what is counted.
- **A wait is spent by what the node shows.** The first failure of an unpinned line
  waits its `escalate_after` readings beside a failing pinned one, and a flapping
  pinned line no longer holds a failure the node shows back from its parent.
- **The readings beneath a pin no longer count toward a wait.** A failure that began
  fewer than `escalate_after` readings before its pin ended reaches the parent at once,
  where it waited out the rest; an older one is published at once, as it was.
- **The contract does not move.** `contribution` and `damping` keep their shape, and a
  node with a pinned line carries them for the status it shows.
- **The counter stays memory.** What a restart does to it is
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)'s: a node's
  first reading in a process is counted from what the node last showed.

## Alternatives considered

- **The wait starts at the pin's end**, the parent keeping what it counted until
  `escalate_after` readings have shown the failure: the rule without an exception, and
  a failure a week old waits again when its pin runs out. A node's own pin has nothing
  to hold, its parent having counted nothing of it, so the two grains would differ.
- **The readings beneath a pin keep counting**, exactly: the tree keeps each node's
  last readings by line and recounts when a pin changes. An old failure is published
  at once and a fresh one waits the remainder, at both grains. It is exact only for a
  pin that ends within a few readings of its line's change, at the price of readings
  kept per line where the counter is one number.
- **The marker alone corrected**, shown only where the node shows the pending status:
  the pages stop saying *Showing error* over a green node, and the parent still counts
  what a pinned line spent or held back.

