# ADR-0109 — A node says its children are complete, and one it no longer returns is removed

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0007](0007-check-result-branches.md) (children are not pruned: the
  deferral this ends, and which this amends), [ADR-0060](0060-a-line-makes-no-claim.md)
  (decision 3: a child left out could not be read, which holds where nothing is said),
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (a subject has a
  node, which made this a prerequisite; decision 4, where its series is shown),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (decisions 1 and 5, an
  event and the first reading after a restart; decision 3, the cause, which this
  amends), [ADR-0036](0036-addressable-reasons.md) (decision 6: absence suspends a
  line's pin), [ADR-0014](0014-maintenance-persistence.md) (a pin and its expiry),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (decision 1, what a series is
  keyed by; decision 8, what stood where a reading landed; decision 10, the ceiling),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (the views a node's series
  are shown in), [ADR-0015](0015-check-discovery-union.md) (a mount two checks share),
  [ADR-0051](0051-what-startup-refuses.md) (decision 2, the epoch),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (freshness, and the event
  it declined), [ADR-0032](0032-status-contribution-boundary.md) (rule 6, the backstop
  beneath a pin), [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md) (the Events
  page's switches), [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (decision
  6, the Maintenance page),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (what is kept
  of a node beside the log),
  [ADR-0116](0116-a-path-with-no-node-says-what-is-known-of-it.md) (what a removed
  node's own pages say of its path)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The tree removes no node. [ADR-0007](0007-check-result-branches.md) let a check hand
back a branch and deferred pruning *until a check needs it*: a child a later run no
longer returns stays, and freshness says that it is old.
[ADR-0060](0060-a-line-makes-no-claim.md) decision 3 then gave that a meaning — a check
that could not read a node leaves it out, so its last reading survives — and it is what
keeps a wall from going blank when a role cannot be assumed or a service has a bad hour.
A line needs none of this: a node's write replaces its lines, so a finding that is gone
is gone with the next run.

[ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) made a node of what
had been a line — a subject that has a history: a workflow, a job name, a pipeline — and
such subjects come and go. A workflow is deleted, a job name stops running, a repository
is archived. Its node then stays, goes stale once its tolerance has passed, and degrades
every node above it until the process restarts. That record named pruning the
prerequisite of every type whose subjects come and go, so a check needs it now.

Leaving a child out therefore has to be able to say two things — *I could not read it*,
and *it is gone* — and the engine has to know which.

## Decision

### 1. Silence keeps, a statement removes

A node in a result may say that its children are complete:
`CheckResult(children=…, children_complete=True)`. **Only then is a child that node no
longer returns removed**, with the first run that says so. A result that says nothing
changes nothing — a child it leaves out stays, as
[ADR-0060](0060-a-line-makes-no-claim.md) decision 3 has it — so the keyword is
additive, the check API's epoch does not move ([ADR-0051](0051-what-startup-refuses.md)
decision 2), and a type adds the statement in the release where it hands back a node for
a subject ([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md)). This
amends [ADR-0007](0007-check-result-branches.md): children are pruned, where their
parent says that they are complete.

The keyword states a fact about the result and leaves what follows to the engine, as
every other field of a result does, and it says which part of the result it is about.

### 2. The statement stands on a node, for its direct children

It covers the direct children of the node that makes it, as far as that node's own check
writes them — two checks may share a mount ([ADR-0015](0015-check-discovery-union.md)),
and a run removes nothing another check wrote — and nothing beneath them. What its own
check writes is read from what the other checks own
([ADR-0015](0015-check-discovery-union.md)): a child on the line of a node another check
owns stays, and so does the instance's own branch. A node that leaves out a child it
knows of does not make the statement in that run, so nothing is removed at that level
until every child is read again.

Where what could not be read has a level of its own, nothing is lost by that. A
repository that did not answer is returned as a node that says nothing about its
children: its workflows stay as they were, and the node above still says that its
repositories are complete. A node whose children are a type's fixed aspects never makes
the statement, there being nothing a run could find gone.

### 3. A removal takes the node, and nothing that was kept about it

The node leaves the tree. What was kept about it stays, each under the rule it has:

- **Its readings.** A series is keyed by the check and the subject
  ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 1) and never by a
  node, so a subject's kept readings outlive its node, and a subject that returns — a
  repository archived and made active again, its identifiers unchanged — finds them, its
  new readings landing behind the old. Forgetting is the ceiling's
  ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 10): past it the
  series written to longest ago goes first, and that is a subject nobody reports any
  more.
- **Its status history.** The event log is keyed by path and bounded by its size, so the
  periods of a node that returns at its path are there, as far back as the log reaches.
- **Its pins**, as decision 4 has it.
- **What the configuration declared for it**, its labels and its rank, which are the
  node's again when it returns.

So a statement need not be exact. A wrong one costs a node that returns at the next good
run, with everything it had.

### 4. Absence suspends a pin, and only its expiry disposes of it

A pin on a removed node stays, and so does one on any of its lines and on the nodes
beneath it. The Maintenance page lists it as a pin whose node is *not reported at
present*; it holds again the moment a node returns at its path; and it ends by its own
expiry, as every pin does ([ADR-0014](0014-maintenance-persistence.md)). This is the
rule a line's pin has ([ADR-0036](0036-addressable-reasons.md) decision 6), one level
up, and a pin set for a migration survives its subject leaving and returning during it.

**A pin makes no node.** It is held against its path, whether it is set, replayed at a
start or adopted, and a node the tree makes at that path takes it. The rule is one for
every pin and not for a removed node's alone, and it amends
[ADR-0014](0014-maintenance-persistence.md) decision 3. A pin whose node was removed
writes its set, its edit and its end as rows that change nothing. *Not reported at
present* is also true of a pinned node no check has written yet since a start, which the
Maintenance page lists the same way until its first reading.

### 5. A removal is an event, one for each node removed

From what the node showed to nothing, with a cause of its own beside those
[ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) decision 3 names:
*removed*. The row's reason is *no longer reported by its check*. The node's last period
ends there; when the node returns, its first reading begins a new period, and the
absence is the gap between the two. It is
[ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) decision 1 — an event for
every change of what a node shows — said of a node that shows nothing any more, and it
amends that record's decision 3 by one cause. A removal has a definite moment, which is
what *went stale* lacked when
[ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) declined an event for it.

The event is written for each node a check wrote, one that showed nothing among them. A
node no check ever wrote — a label its deployment declared, a container the tree made on
the way to another node — leaves without one.

**The first run after a restart writes the same event.** The tree starts empty, so there
is no node to remove; for a path the log last showed a status for, and which the first
run that says its children are complete does not return, the event is written at that
run ([ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) decision 5). Nothing
is removed that was never there, and a node that went away while the process was down
still ends its period.

The Events page lists these rows with the chip *removed* and can hide them by their
cause: a third switch group, *readings*, *pins* and *removals*
([ADR-0101](0101-the-events-page-is-filtered-by-its-url.md)).

What is kept of a removed node
([ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)) says that it
shows nothing since its removal, so its return is a change the tree saw, and goes when
the removal's row has left the log, unless a pin is held against the path.

### 6. A series no node stands for is listed on its check's History page

[ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 4 shows a
subject's series on the node that stands for it. A series no node stands for — its
subject rides on a line of a node that carries several, or its node was removed — is
listed on its check's History page, a table for each, beneath the check's own readings:
what the check still keeps of things it no longer reports. A table is captioned by the
sentence of the line its newest reading stood on
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 8), since a subject
may be a provider's identifiers and nothing a reader knows.

### 7. What this does not decide

A branch that says it *could not observe*, the reason it gives, how that shows on the
nodes beneath it, and whether staleness then obeys a pin: the other half of what leaving
a child out can mean, and not needed to remove what is gone. Nor a node that names the
children it could not read, which would let it remove among siblings while one of them
is unread; decision 2 can gain that without changing.

## Consequences

- **Each type adds the statement at its own release**, the one where it hands back a
  node for a subject. Until then nothing changes for it, and a type that forgets the
  statement leaves a stale node, as today.
- **[ADR-0007](0007-check-result-branches.md) is amended**: its consequence that
  children are not pruned holds where a result says nothing.
  **[ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) decision 3 gains a
  cause.** [ADR-0060](0060-a-line-makes-no-claim.md) decision 3 holds as written, and a
  node that leaves a child out because it could not read it does not say that its
  children are complete.
- **The wall changes at once.** A node is gone with the first run that says so and back
  with the first that returns it; nothing waits a number of runs, since decision 3 makes
  a wrong removal cheap.
- **The event log grows by what is removed**: a repository archived with ten workflows
  writes eleven rows at one instant.
- **The ceiling forgets what is gone first**
  ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 10): a deployment
  near it loses the readings of an archived repository before those of any that still
  reports.
- **A pin without a node** is a state the Maintenance page shows and the store keeps,
  and a restart that brings the pins back no longer brings back a node for each.
- **`implementing-checks.md` says the rule** when this is built: say that the children
  are complete where the run read all of them, and leave it unsaid where it could not.

## Alternatives considered

- **Silence removes, and a check that could not look says so** — a node the run writes
  replaces its children as it replaces its lines. The cleaner end state. It reverses
  what leaving a child out means for every check that exists — a fourth epoch, and a
  round through every package — and a silence misread deletes a branch on a bad minute,
  where a statement forgotten leaves a stale node.
- **The statement once, for a whole result** — the simplest to write; one account that
  cannot be opened then stops removal everywhere in its check.
- **A node that names the children it could not read**, which are kept as they are —
  exact, and it needs a way to hand back a child without rewriting it (decision 7).
- **A pinned node that is not removed while its pin holds** — no new state; the node
  stays on the wall, stale, for as long as the pin lasts, degrading what stands above it
  through the pin ([ADR-0032](0032-status-contribution-boundary.md) rule 6).
- **A pin that goes with its node** — a subject missing for one run comes back unpinned
  and alarms through the maintenance it was pinned for.
- **No event** — a removed node's last period has no end: *current*, of something that
  is not there, or ended at a time nobody knows.
- **One event, for the topmost node removed** — fewer rows; every reader of a node's
  history then looks up its ancestors' removals.
- **The series dropped with its node** — bounded; a subject that returns finds nothing,
  and a flag turned by mistake costs every kept reading.
- **A removed node's own pages, by its path** — the tree reads a history for a node it
  holds, so a removed node's own pages say that there is no such node until it returns,
  and its rows are on the Events page.
  [ADR-0116](0116-a-path-with-no-node-says-what-is-known-of-it.md) gives those pages
  what the log and the pins know of the path: one page, and a `404`. Its series would
  show there if each kept reading remembered the path it stood on: a new stored key, and
  pages for nodes the tree does not hold. It can follow.
- **A series shown nowhere until its node returns** — kept, counted against the ceiling,
  and invisible.
- **`exhaustive` or `prune` as the keyword** — the first does not say what is
  exhaustive, a node's lines being so already; the second is an instruction among
  statements of fact, and reads as if the check removed the node.
