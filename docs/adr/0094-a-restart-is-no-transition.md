# ADR-0094 — A restart is no transition, and the instance's own node records the gap

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the
  restored log, and the consequence this reverses),
  [ADR-0001](0001-in-process-threaded-engine.md) (the bound on the log a restart
  spends), [ADR-0014](0014-maintenance-persistence.md) (the pins replayed at startup),
  [ADR-0077](0077-authority-follows-the-lease.md) (a log adopted in a running process),
  [ADR-0088](0088-a-stop-ends-at-its-save.md) (the stop's one save, which now stamps the
  stop), [ADR-0090](0090-one-state-directory-one-writer.md) (the lease whose last beat
  dates a crash), [ADR-0072](0072-the-instance-reports-on-itself.md) and
  [ADR-0076](0076-the-instance-node-is-a-branch.md) (the instance's own node),
  [ADR-0032](0032-status-contribution-boundary.md) (the one marker an event carries),
  [ADR-0027](0027-observation-timestamp-semantics.md) and
  [ADR-0039](0039-status-rollup-semantics.md) (the Time card's rule for a container,
  which the history page now follows),
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (decision 7, the changes a
  node counts)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A restart restores the event log and not the nodes
([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)): every node starts
`UNDEFINED`, and its first reading is compared with that. A first reading of anything
else is therefore a transition — `UNDEFINED → OK` for every node on every restart, which
ADR-0071 kept on purpose: *the node was unobserved, and a restart is visible in a
history for that reason*. A first reading of `UNDEFINED` makes none, and then the last
period the log restored for the node runs on to the present with the present reason. The
case that showed it is an `aws` check's root across that package's conversion: it
declared `OK` before and declares nothing now, and its `/history` says *ok, from before
the restart until now*.

The visibility ADR-0071 bought was thinner than it read. The period before a restart
already ran over the downtime, up to the first reading after it; what the restart added
was a split between two periods of one code, and an event per node. That event costs:
the log holds 1,000 events for the whole tree (ADR-0001), so a few deploys push the real
transitions out of it.

What stays true is that for one node a restart *is* something that happened — the
instance's own, `/little-sister`, which beats `OK` every tick. That the instance was not
running is its fact, and a subject's history is the wrong place to say it.

## Decision

### 1. The first reading after a restart is compared with what the log last recorded

The tree keeps, from the restored log, each node's last **reading**: the `new` of its
last event, passing over an admin's pin set — an unmarked event to `MAINTENANCE`, which
moves what the node shows and not what it read. A node's **first write in this process**
is compared with that rather than with the `UNDEFINED` a restart leaves. A reading that
is what it was keeps its period across the restart; any other — `UNDEFINED` included,
the case that showed it — is a transition from the old code, dated by the reading that
saw it, as every reading's change is. Where the log holds nothing for a node, its first
reading is a first reading, as before.

Only a node's first write reads it. A log adopted in a running process (ADR-0077)
arrives where the nodes are written, and changes nothing about how they compare.

### 2. A pin in force before the restart writes nothing at its replay

The pins' replay at startup compares with what the restored log last *showed* for the
node — the code of its current period, as the history reads it. A pin whose
`MAINTENANCE` period the log holds continues it; one whose set the log no longer holds —
evicted by the bound, or a log that was lost — records its set, as today.

### 3. A change seen across a restart is not marked

An event is dated by the reading that saw it: a check's period already makes that up to
one period late, and a restart's gap differs from it in size only. `Event` does not
change, and the one sentence that defines its one marker — *an unmarked event is one
that alarmed* (ADR-0032) — is not bent to carry a second meaning. Where a reader needs
to know whether the instance was watching, it asks the instance's own node (decision 4).

### 4. The instance's own node records the gap

On restore, `/little-sister`'s last period is closed by an event to `UNDEFINED`, dated
when the old process was **last alive**, whose reason says the instance was not running;
its first beat after the start is then a transition from there. So its history reads *OK
until the stop, `UNDEFINED` over the downtime, OK since*, and a change a subject shows
at 10:05 can be read against it. Two events per restart, where there was one per node.
The node's children are not closed: the gap is said once.

*Last alive* is the later of two stamps. **The stop's one save** writes the moment of
the stop into the log, beside the events, as `stopped_at` — that save and no other, so
the interval writes still skip an unchanged log (ADR-0071 decision 3), and a keeper
carries it with the file. **The lease's last beat**: its holder rewrites the lease file
every 10 s and once more when it lets go (ADR-0090), so the file's last write before
this process takes it is when the old process was last alive, whether it stopped or
crashed. The later of the two wins, which also covers a process that crashed before its
first save and left an older stop's stamp behind.

The log's own last save is **not** one of them: a kept file is written only when it
changed, so on a quiet night its last save can be hours before the stop. And the lease
lives beside the state directory, where no keeper carries it: a crash on a fresh disk,
or a log saved before this change, records no gap, and `/little-sister` then keeps its
period across the restart like every other node.

### 5. A container's current `UNDEFINED` is no row on its history

The Time card names no period for a node that declares nothing above nodes that report —
its `UNDEFINED` is a container's, which the roll-up skips (ADR-0039), and its page heads
with what its children roll up to. `/history` follows the same rule with the same test,
own code `UNDEFINED` and children present: the current period is not a row. The table
ends with the last period that named a status, whose *until* is when the node stopped
declaring, and one line beneath it says so. A leaf's `UNDEFINED` is its own reading and
keeps its row; an `UNDEFINED` period in the past stays a row, since nothing records
whether the node had children reporting then. The log is untouched: this is how the page
reads it.

## Consequences

- **ADR-0071's consequence is reversed** — *the first run after a restart still records
  `UNDEFINED → OK`* — and that record now says so.
- **A restart writes fewer events**: one per node whose reading changed across it, two
  on `/little-sister`, and one per pin whose set the log lost — where it wrote one per
  node.
- **A node's Time card reaches back across a restart**: a node reading what it read
  before says *from* the moment its period began, before the restart.
- **A change across a restart counts as the change it is**: `changes`, which counts
  transitions between `OK`, `WARN` and `ERROR` (ADR-0083 decision 7), counts an `OK →
  ERROR` seen by the first reading after a restart, which it could not while that
  reading read `UNDEFINED → ERROR`.
- **The events file may carry `stopped_at`**, a key an older reader passes over; no file
  changes shape, and the envelope and `Event` do not move.
- **The lease says when its previous holder last wrote it**, read before this process
  takes it over.

## Alternatives considered

- **Keep `UNDEFINED` as the baseline and close every node's period at the restart**, so
  every history shows the downtime literally. The most faithful picture, and the most
  expensive: two events per node per restart spend the log twice as fast, and every
  node's page carries an `UNDEFINED` stretch for every deploy.
- **Compare only a first reading of `UNDEFINED` with the restored code.** Mends the case
  that showed it and nothing else: one case follows a rule the others do not, and
  restarts go on spending the log.
- **Mark a change seen across a restart on its event.** Precise per event, and a second
  marker beside `suppressed_by` that no rule reads — history and the change count treat
  the event the same.
- **Date the gap by the log's last save.** Wrong on a quiet night, where it claims hours
  of downtime that never happened.
- **Stamp the log at every interval write**, so a crash leaves a stamp one interval old
  everywhere. It writes the log, and sends it to a keeper, every interval whether it
  changed or not — the skip ADR-0071 made, gone for this file.
- **Show a container's `UNDEFINED` period as any other, or rename it *declares
  nothing*.** The first contradicts the page's own head and Time card; the second puts a
  non-status in the Status column.
