# ADR-0106 — A subject with a history has a node of its own, and a run is a mark at its own time

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0092](0092-a-check-declares-its-measures.md) (decisions 5 and 6,
  which left both halves of this open and which this amends),
  [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) (decision 1, where a
  measure's node is read from, and decision 4, the lane — both amended),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (the views a node's series
  are shown in; decision 1 amended),
  [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) (the window every curve of a
  view shares), [ADR-0086](0086-a-check-measures-and-grades.md) (decision 2: a grading
  carries a reading onto the line it produced),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (decision 1, what a series is
  keyed by, and decision 8, what stood where a reading landed),
  [ADR-0043](0043-coverage-backstop.md) (decision 7, which this amends, and the
  alternative it rejected), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (decision 8: one URL, the representation chosen by `Accept`),
  [ADR-0050](0050-slugs-from-provider-identifiers.md) (a line's slug, built from what a
  rename cannot move), [ADR-0025](0025-check-provided-subnode-metadata.md) (a child's
  labels), [ADR-0007](0007-check-result-branches.md) (a child an earlier run wrote stays
  in the tree), [ADR-0039](0039-status-rollup-semantics.md) (the roll-up),
  [ADR-0024](0024-dashboard-layout.md) (a status is never said by color alone),
  [ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) (the marks of a run that warned
  and of one without a verdict, a crowd of runs, the summary, and the records a mark is
  drawn for; decision 2, a line written for the record alone)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0092](0092-a-check-declares-its-measures.md) showed a subject's series on the node
that stands for it and left two things to the change that first draws one: a subject
that rides only on a line, which has no node (decision 6), and how a series of events is
drawn, which has no cadence for a tolerance to measure (decision 5). They are one
question, because every series of events the family keeps rides on a line: a workflow's
runs, a Batch job name's runs, a pipeline's executions, a load test's runs. A check that
reads many objects hands back a measurement for each, its grading carries each onto a
line of an aspect's node ([ADR-0086](0086-a-check-measures-and-grades.md) decision 2),
and the series is kept and shown nowhere. Most such subjects have no line at a given
moment either: in one deployment's run, 4 of 96 workflows did.

Two answers were weighed over that deployment's kept readings. A **page of its own**,
addressed by the series' key, moves no path — and gives the tree a second way to address
what it addresses already, the route per subject that
[ADR-0092](0092-a-check-declares-its-measures.md) and
[ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) had each refused. A **node**
for the subject moves paths and pins in every type that takes it. What decided it: no
deployment needs a migration, since each can start from scratch; and the one reason left
against nodes, memory, did not hold when it was measured. The series weigh the same
wherever they are shown. A node costs about 2.4 KiB of tree and 1.4 KiB of envelope: 137
subjects — sixteen of them functions, counted as if each named one — and the nodes they
hang on took that deployment's tree from 99 nodes and 0.21 MiB to 282 and 0.54 MiB, and
a root snapshot from 0.55 ms to 1.5 ms; a thousand subjects hold 2.6 MiB, and a snapshot
of them costs 7.6 ms.

Two records argue against a node per subject, and this one is narrower than what they
refused. [ADR-0043](0043-coverage-backstop.md) rejected *a node per discovered subject*
— forty repositories times seven aspects is a tree nobody reads — and its decision 7
made a subject a grouping of the lines about it, read and never acted on. What has a
node here is a subject that has a **history**: a workflow on its branch, a job name, a
pipeline — and not every repository under every aspect.

How a run is drawn was settled over three drawings of the same two series in the Series
view's own frame, their axes the library's: marks on the time axis, dots, and one slot
per run.

## Decision

### 1. A subject that has a history has a node of its own

A subject that one of several measurements names
([ADR-0086](0086-a-check-measures-and-grades.md) decision 4,
[ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 2) — what rode on a
line — has a node: a status and a path, a pin as every node has one, and the views a
node has. It has it whether or not its newest reading is a problem, so a subject that is
well stands in the tree and says so; and whether or not the deployment keeps a series of
it, since `series_keep` says what is kept and never what shape the tree has. A line that
names no subject — a finding, a pull request, an alert — has no history and stays a
line, and [ADR-0043](0043-coverage-backstop.md) decision 7 holds for it as written. This
amends that decision for a subject with a history: it is no longer only read, it is a
place.

### 2. A node stands for the subject its line names

A grading already carries each reading onto the line it produced — the record as the
line's `data`, the subject as the line's
([ADR-0086](0086-a-check-measures-and-grades.md) decision 2). It now writes that line on
the subject's own node, a child of its result as an aspect is
([ADR-0007](0007-check-result-branches.md)). **A node whose lines name one subject and
no other stands for that subject.** Nothing is added to the check API and its epoch does
not move: the engine finds a reading's line by its record and its subject wherever in
the result the line stands, so what stood where the reading landed
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 8) is the line on the
subject's node, and the series is kept as it was.

A node that carries the lines of several subjects stands for none of them, and their
readings are shown where they are today, on their check's History page. So a type that
has not moved its lines keeps working as it did.

**A line may name its node's subject without carrying one of that subject's readings.**
Where a type shows a subject through a reading it keeps no history of — a function's
newest bucket, asked on every poll — and writes the subject's runs for the record
([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) decision 2), that line names the
subject all the same. A node stands for a subject by what its lines name, so it stands
for this one in a run that read one of its events and in one that read none, and the
line's own reading, which names no subject, is kept nowhere. This amends
[ADR-0086](0086-a-check-measures-and-grades.md) decision 2, which had a line's subject
be its reading's: it is, wherever the reading names one.

A measure that names a node ([ADR-0096](0096-a-measure-names-its-node-and-its-things.md)
decision 1) names it from the node its reading stands on: the subject's, as it is the
check's own for the one reading the engine places. This amends that decision.

A place the measurement declares was the other way, and stays refused as
[ADR-0086](0086-a-check-measures-and-grades.md) decision 2 refused it for a line: the
place would be said twice, by the measurement and by the child the grading returns, and
the two could disagree.

### 3. Where the node hangs and what names it are its type's to say

The library prescribes no shape: a subject's node is wherever beneath its check's mount
the grading wrote its line. The family's types hang it **beneath the node whose line it
rode on, under what it belongs to where there is such a thing** — a workflow under its
repository inside its aspect, a job name under its queue — and their trees stay
aspect-first. A level of that kind is a container: it grades nothing of its own and
rolls up what is beneath it ([ADR-0039](0039-status-rollup-semantics.md)).

A node is named by **what its provider calls the thing**, as every node the family has
is: a path is read where no title shows — a URL, `nodes.yaml`, a log line, a client's
watched paths — and its title comes as a child's labels do
([ADR-0025](0025-check-provided-subnode-metadata.md)). A rename at the source is
therefore a new node. The series carries over, keyed as it is by its check and its
subject's identifiers and not by a path
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 1); a pin on the node,
its `nodes.yaml` entry, its periods and its events stay on the old path. The provider's
identifier as the name, with the name as a title, was the alternative: nothing would
move, as nothing moves for a line's slug
([ADR-0050](0050-slugs-from-provider-identifiers.md)), and every path would be
unreadable. A node named by what its provider calls the thing says that a run names it,
so that nothing declared for a name the provider happens to share reaches it
([ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)).

### 4. A subject's series is shown where a node's series is

The node that stands for a subject shows its series as
[ADR-0092](0092-a-check-declares-its-measures.md) decision 6 and
[ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) have a node show one: the
curves that stand on it on its page, every curve at or beneath it in its Series view
under the node it stands on, every reading on its History page, and a row in the Series
index. A check's series are found through the check, as before, and each is shown on the
node that stands for its subject where one does. This amends
[ADR-0092](0092-a-check-declares-its-measures.md) decision 6, which left such a subject
without a place, and [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md)
decision 1.

### 5. A run is a mark at its own time

A series of events — records with an identity
([ADR-0092](0092-a-check-declares-its-measures.md) decision 5) — is drawn on the time
axis every curve of a view shares
([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md)), each run a mark at its
record's own instant ([ADR-0092](0092-a-check-declares-its-measures.md) decision 4). So
the window, the way into a stretch and the line that reads every curve at one instant
hold for a run as they do for a gauge, and a night without a run is a gap that can be
seen. A mark is drawn for a record with an identity, and a record with a state has none
([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) decision 5).

- **Without a measure, a run is a tick**: short for a run whose reading stood `OK`, tall
  in the failure ink with a hollow head for one whose reading stood `ERROR`.
- **With a measure, a run is a stem** from the baseline to its value, with a head on it.
  A run that failed keeps its value, in the failure ink with a hollow head.
- **A failed run is marked in the lane beneath the baseline as well.** The lane marked a
  reading that failed ([ADR-0096](0096-a-measure-names-its-node-and-its-things.md)
  decision 4); for a series of events it also marks a run whose reading stood `ERROR`.
  This amends that decision. The lane stands beneath a plot that has a value axis
  ([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) decision 4).
- **No line joins two runs**, and no hole is drawn: between two runs nothing was read
  because nothing ran.
- **A failed run is told by its shape and its place as well as by its ink**
  ([ADR-0024](0024-dashboard-layout.md)).

What a run *failed* means is the code its reading stood with
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 8). A run that warned
and one that kept no verdict have marks of their own, in a crowd every run stands where
it ran and a passing run's head gives way —
[ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 5 is the gauges' rule
— and the summary beside the title counts the runs and what did not pass, by kind
([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) decisions 1, 3, 4 and 6). This
amends [ADR-0092](0092-a-check-declares-its-measures.md) decision 5.

### 6. The API reads a series at the Series view's own URL

`GET /series/<node_path>` with `Accept: application/json` answers what the page at that
URL shows: every series that stands at or beneath the node, over the window its `from`
and `to` name ([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 1) —
one URL and the representation chosen by `Accept`, behind the bearer token, in one
response, as the status read is
([ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 8). Each series
says the node it stands on, the key it is kept under — its check's type and mount, and
its subject — the measures its check declares, and its readings in the window: the time
on the series' clock, when it was observed, the code and the sentence as they stood, the
identity or the state, and the record. It is additive under `schema_version` 2. Nothing
reads a series yet, and the read is built when something does.

## Consequences

- **Each type moves at its own release**, and that release moves paths and pins: a
  grading hands back a node where it handed back a line. Until then nothing changes for
  it.
- **Pruning becomes a prerequisite.** A line a grading no longer writes is gone with the
  next run; a node it no longer writes stays
  ([ADR-0007](0007-check-result-branches.md)), goes stale and degrades every ancestor
  until the process restarts. A type whose subjects come and go hands back nodes only
  once a run can remove what it no longer reports.
- **A subject that is well has a status**, so the wall holds a node for every subject:
  158 more in one deployment, nearly all of them quiet. What keeps that readable is the
  wall's own work: a viewer folding a branch, and a branch saying how it starts.
- **A rename leaves a node behind**, and a pin with it. A node that follows its subject
  would carry both over, and is not built.
- **The view of one thing across the aspects it stands under is not a tree shape.** A
  repository still stands once under each aspect; a page that regroups a branch by a
  second key would show it, and is not built.
- **[ADR-0092](0092-a-check-declares-its-measures.md) decisions 5 and 6,
  [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) decisions 1 and 4,
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 1,
  [ADR-0043](0043-coverage-backstop.md) decision 7 and
  [ADR-0086](0086-a-check-measures-and-grades.md) decision 2 are amended.**
- **`implementing-checks.md` says the rule** when the first commission is built: a
  subject with a history is handed back as a node, its line on it.
- **The envelope moves only by what it carries already**: more nodes, each with its
  line's `subject`.

## Alternatives considered

- **A page of its own for a subject**, addressed by its series' key — no path moves, the
  tree gains a second address for what it addresses already, and a subject without a
  line has neither a status nor a pin. It is the route per subject two records refused.
- **Every subject directly beneath its aspect** — fifty-eight children on one node, each
  name repeating what it belongs to.
- **What a subject belongs to first** — `check → repository → aspect`: every aspect
  under every repository, the tree [ADR-0043](0043-coverage-backstop.md) refused, and
  aspects moved that gain no series by it.
- **A node named by its provider's identifier** — proof against a rename, and unreadable
  (decision 3).
- **A place the measurement names** — said twice, and free to disagree (decision 2).
- **Dots without stems** — a value floats loose of its instant where runs are sparse,
  and a short failed run near the baseline reads as a lane mark.
- **One slot per run in the order they ran**, as a CI page draws it — the night without
  a run disappears, seventy minutes between a failed run and its second attempt look
  like a day, and the series leaves the axis the view's other curves share.
- **The API answering a node's own series alone, a route by the series' key, or readings
  in the status envelope** — the first breaks with the page and with the status read,
  which both answer a branch whole; the second makes a provider's identifiers the
  address and needs a second read to find them; the third makes every poll carry
  history, and [ADR-0092](0092-a-check-declares-its-measures.md) had said the envelope
  does not move.
