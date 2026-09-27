# ADR-0087 — A check keeps its subjects' readings, and an identity keeps each event once

- **Status:** Accepted
- **Date:** 2026-09-20
- **Related:** [ADR-0086](0086-a-check-measures-and-grades.md) (the measurement a
  series keeps, and the subject that picks its series),
  [ADR-0085](0085-a-measure-is-read-out-of-a-record.md) (whole records under a count,
  which this builds), [ADR-0015](0015-check-discovery-union.md) (two checks on one
  mount), [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md) (the
  typed times, in UTC from the seam on),
  [ADR-0047](0047-node-notes-and-their-retention.md) (the retention shape this does not
  take), [ADR-0050](0050-slugs-from-provider-identifiers.md) (the slug, which has
  nothing to do with a history), [ADR-0042](0042-entries-carry-their-own-code.md) and
  [ADR-0039](0039-status-rollup-semantics.md) (the code a kept reading carries: its
  line's, or what its check's result rolls up to),
  [ADR-0007](0007-check-result-branches.md) (the children a tree keeps after a run
  stops writing them, which that code leaves out),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (the pin it does not carry),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the writer
  `series.json` joins, and the keeper that carries it),
  [ADR-0077](0077-authority-follows-the-lease.md) (the `restore` a takeover adopts it
  through), [ADR-0075](0075-a-check-declares-what-it-costs.md) (what a sum at startup
  can and cannot promise, and the page the projection stands on beside it),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the engine's own node, where the
  ceiling speaks)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check reads its object and hands back a record of what it read, and since a check
measures and grades in two halves ([ADR-0086](0086-a-check-measures-and-grades.md)) a
verdict can be reached again over a record the process that took it no longer holds.
What nothing did was keep one: every run writes its reading onto its node, and the next
run writes over it. A subject — a backup job, a web page's response time, a host's load
— has a history an engineer reads and wants drawn as a curve, and that history is a
**series**: the subject's records over time, ordered by time and bounded by retention.

Five things have to be settled before the first record is kept, because each is written
into every record from the first one on and none can be added to a history afterwards:
which series a reading joins, whether it is a new record there or one the series
already holds, how many are kept and who says so, which clock orders them, and what the
reading meant where it was graded. This record settles them for **memory**, the first
tier, and for the seam every other tier is written through — and then the two things
memory alone cannot promise: that a series outlives the process that kept it, and that
all of them together fit inside it. A history is kept in a file a restart reads back,
and bounded by a ceiling on everything held, with a projection beside it that sees the
ceiling coming.

## Decision

### 1. A series belongs to the check and its subject

The key is the check — its **type and its mount** — and the **subject** the reading is
of. Not the node path: a path is the deployment's label for where a node hangs, and one
mount carries two checks by design, a `host-metrics` and a `macos-memory` on one host
node with the container belonging to neither
([ADR-0015](0015-check-discovery-union.md)). Keyed by path, two measurements of a
different shape would land in one series. Two methods on one host are therefore two
series, as two mounts already are. The key needs no configuration of its own; its cost,
accepted, is that moving a check to another mount starts a new history.

### 2. The subject says which series, and a reading without one has none

A reading joins the series of the subject it names — its own, or, for the one
measurement a run hands back alone, the object its check declared at construction
([ADR-0086](0086-a-check-measures-and-grades.md) decision 4). Among
several measurements an empty subject is no subject, and a reading that names no object
has no history, since nothing says which later reading continues it.

That leaves the slug out of it. A line's slug is what a pin holds
([ADR-0050](0050-slugs-from-provider-identifiers.md)); a line whose slug is derived from
its sentence has no series because it names no subject, which is this rule and not a
second one.

### 3. The identity or the state says whether it is a new record

`Measurement` gains an optional **identity** beside its subject. Empty — the common
case — **appends**: every reading of a response time or a load average really is a new
one. Set, it names the **event** the reading is of — the completed run of a workflow, a
load-test run, a batch job's id — and a record of that identity already in the kept
window is **replaced**, updated in place, never a second point. Replacement is by
identity **anywhere** in the window and not only against the newest record, so a poll
that sees an older run again does not duplicate it.

**A run may read one subject several times, where the identities differ.** A
load-test check reads every run of an environment inside its window on each poll, so
it hands back one reading per run, all of one subject, each naming the run it is of;
the older ones replace the records they already wrote and the new one appends. That is
what narrows [ADR-0086](0086-a-check-measures-and-grades.md) decision 8 a second time,
to *never one record twice*. The other two cases stay unrefused, and neither costs the
run: two readings of one subject with the same identity are one record, the later —
the second replaces the first, as it would on the next poll — and two with neither an
identity nor a state are two points at one instant, an author's mistake that costs a
duplicate point.

**A reading of a frozen state names when it last changed, or the state it is in.** Not
every object's source keeps events for it: a workflow that is switched off names no run,
a queue has no execution, a finding the scanner keeps reporting names nothing that
happened. Such a reading has a subject and would append the same record on every poll,
and a history of *no change* is a history of nothing. So it says what changed in one of
two ways, in this order. Where the source itself keeps a **last-changed** field that
moves whenever the state does — an `updated_at`, a `lastUpdatedAt` — that field is the
identity, whatever else moves it too, and the check's own record says which field it is
and what that source's documentation says moves it; vendor documentation is the showing,
because a check that cannot be run against the estate cannot demonstrate more, and a
field that turns out not to move with the state is an amendment to that record rather
than a defect in this one. A field that is a time is named as the instant the record
keeps, never as the source's text for it: the check puts it under a timed name, which
the seam converts to UTC, and takes the identity back out of the measurement, because
one instant written with another offset would otherwise be another event.
little-sister-github's disabled workflow is the case — GitHub wrote its `updated_at` at
`+01:00` and at `+02:00` (little-sister-github ADR-0013 §5). Where the source keeps no
such field, the reading names its **state** instead — `Measurement`'s second optional
field, spelled from the few fields that *constitute* the state, the switch or the
status, and never from the whole record, whose counts and timestamps would change on
every poll.

**A state is compared with the newest record alone.** The same state replaces the
series' newest record, and any other appends, so an unchanged state is one record, every
change appends the next — a return to an earlier state included — and the newest record
is always the state the object is in. That is where a state parts from an identity. An
identity is found **anywhere** in the window because an event recurs only as a re-read;
a state recurs as a new spell, and found anywhere, a return would rewrite that state's
older record where it stood: the spell between would vanish, and with no time of its own
the newest record would name a state the object had left. A reading names an identity or
a state, never both, and two readings of one subject in one run in the same state are
one record, the later. Only where neither is possible does a reading name nothing, and
the cost is a series as long as its retention, saying the same thing in every record.

That is not [ADR-0050](0050-slugs-from-provider-identifiers.md) being worked around.
That record forbids inventing an **object's** identity out of text the provider did not
mint; this names the **event inside** an object the provider did name, or the **state**
it stands in, which for a frozen state is what happened.

Both are fields on the measurement and not reserved keys in the record, for the reason
the subject is one: the record is the check's own vocabulary, and a reserved name would
take one away from it. The three read as one rule for a check author — *the subject
gives a reading a history, the identity keeps one event in it once, and the state one
spell*.

### 4. Retention is a count, per check, in the check's own YAML

`series_keep` is a common field beside `frequency` and `timeout`, parsed for every type,
and nowhere else: there is no `settings.yaml` key. `record_limit`, `escalate_after` and
the retry pair are policy, one rule meant to hold everywhere, and a deployment default
is right for them. Where a history is wanted is an **editorial** choice per check — a
curve here, two hundred batch runs there, nothing elsewhere — and any global number
would be the wrong one almost everywhere. The default is **0**, which is **no series**:
a non-zero default would be a choice somebody made for the deployment, and zero keeps
what the series hold at nothing until a deployment says otherwise. An override per
subject waits until somebody misses one; it is additive.

A count and only a count. [ADR-0047](0047-node-notes-and-their-retention.md)'s four
parameters are shaped for notes, which are rare and meant to outlive years; a reading
arrives every few minutes, and in memory *older than x* and *not among the last n* then
say the same thing, so two age parameters could only contradict the counts. Age earns
its place with a store that serves longer windows than memory, and going from one
number to four is additive where the reverse is not.

### 5. Memory is the first tier: the last *n* records, oldest out

A series holds **whole records**, as the measurement's seam normalized them — the
decision [ADR-0085](0085-a-measure-is-read-out-of-a-record.md) made so that a measure
can be read out of a record when it is drawn — each with its identity or its state, both
clocks and what stood where it landed (decision 8) beside it. Memory keeps the last *n*
of each series and drops the oldest when a new one would pass the count.

### 6. Two clocks, and both are kept

`observed_at` is **ours**: when the engine took the reading — the instant it hands the
grading, so a verdict reached again over a kept record is reached at the time it was
first reached. A record's **own** times are the **source's**: converted to UTC at the
check's seam ([ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)) and
never re-stamped with ours. A series orders by the record's own time when it has one
and by when we looked when it has not — a curve of run durations sits on when each run
finished, one of response times on when it was measured — and keeps both, so *the last
backup finished 31 hours ago* is a sentence it can say. A node's staleness is untouched:
it is the age of a reading, and the age of a record is a different fact.

The record's own time is its **top-level `at`**, the instant the record is of. A time
nested deeper is a value the record carries — a file's modification, a run block's
start — and orders nothing, since a record may carry several and only the check knows
which one it is about; a check that wants its record placed by the source's clock puts
that instant at the top. Where there is none the record stands where it was **first**
observed, so one replaced by its identity or its state keeps its place instead of moving
to the end, and readings that tie stand in the order they were handed back.

### 7. The seam is three operations

A store **adds** a record — appending it, replacing the one of its identity, or
replacing the newest where both are in one state — reads the **window** of one series,
and **sweeps**: by retention, and, given a ceiling (decision 10), by evicting whole
series until what it holds fits. The engine sweeps on every tick, before it reads its
own lines. Memory is the first tier to speak it and stays the front of any tier behind
it; a store whose retention is its own business may leave the ceiling to the memory in
front of it. None of it is on the check-authoring surface: a check hands back
measurements and never sees a store, and a type never sets `series_keep`.

### 8. A kept reading keeps what stood where it landed

A record says what was read; what it **meant** is a grading, and the thresholds that
produced it may have changed by the time a window is read, so a week's availability
would otherwise have to guess what *OK* meant on the Tuesday. Beside the record and its
identity a kept reading therefore carries the **code** and the **sentence** of the
place it stood, as they stood there:

- **A line.** A reading among several that the grading carried onto a line keeps that
  line's text and its code — the line's own, or its node's where it declared none
  ([ADR-0042](0042-entries-carry-their-own-code.md)). The line is found by what the
  grading already writes on it: the reading's record as the line's `data`, and its
  subject as the line's ([ADR-0086](0086-a-check-measures-and-grades.md) decision 2).
  Two readings carrying the same record pair with two such lines in the order both
  were written.
- **The node.** The one reading the engine placed keeps its node's code and the root's
  texts as the result wrote them, and so does a reading **among several that names the
  object its check declared** at construction, where no line carried it: it is the
  reading the engine would have placed had the run handed back nothing else, and a
  grading that says it on the root rather than on a line — little-sister-github's
  estate reading is one — has it stand where the placed one stands. A line that
  carried it still wins, as it does for every reading among several. A branch check's
  root is `UNDEFINED` — a container, which grades nothing whether it is silent or says
  what it watches — so what stood there for this reading is what the check's own
  result **rolls up to**: the roll-up of
  [ADR-0039](0039-status-rollup-semantics.md) over the root and every child this run
  returned, beside whatever sentence the root carries. Not the node as the tree holds
  it: on a mount two checks
  share (decision 1) the node counts the other check's readings, and a child an
  earlier run wrote and this one did not stays in the tree
  ([ADR-0007](0007-check-result-branches.md)). Neither is anything this reading says,
  and grading its record again reproduces neither; the roll-up of the result it
  reproduces exactly. A pin is not a reading either: what an admin let the node show
  ([ADR-0041](0041-maintenance-is-a-contribution-rule.md)) is not kept.
- **Nowhere.** Any other reading no line carried keeps neither.

What the children said is not kept: they are derived from the same record, and a page
rebuilds them by grading it again. A record kept without the two could never be given
them afterwards, which is why the rule came with the file: every record a restart reads
back carries what stood.

### 9. The series are a state file

`series.json` joins the state layer's writer as a **kept** file
([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) decision 3):
written at most once per `state_interval` on the scheduler tick and once more at
graceful shutdown, not rewritten while nothing changed, and carried by a keeper with
the rest of the directory without the keeper knowing what it holds. It is the layer's
file discipline, not a second writer: the memory tier is the producer, copying under
its lock and serializing outside it. The file holds every series in key order and each
reading as it is kept — the record, `observed_at`, the identity, the code by name, the
texts, and the state where there is one — with `first_observed_at` where a replacement
moved `observed_at` past it, since that is what keeps a replaced record in its place
across a restart.

It is read back at startup, after a keeper has fetched what it holds, so an instance on
a fresh machine comes up with the series the old one wrote; whole or not at all, so a
file of another shape is the layer's `load.series.json` line at ERROR and the series
start empty, never a refusal to start. The same `restore` adopts a keeper's copy at a
takeover and swaps a backup back
([ADR-0077](0077-authority-follows-the-lease.md) decision 2). The file may be older than
the configuration reading it, so it is read as written and **this** configuration's
retention is met by the first tick's sweep: a series whose check is gone or keeps none
is dropped, and one past its new count is trimmed, the oldest out.

### 10. A ceiling on what all of them weigh

A count bounds one series; how many series there are is the estate's, and a check that
discovers its subjects grows them for as long as the process runs. The sum at startup
([ADR-0075](0075-a-check-declares-what-it-costs.md)) is only a lower bound here, since
it sums what is declared and a check that cannot know its estate correctly declares
nothing. So the process bounds what it holds at runtime, in the shape `entry_limit`
has.

- **In bytes, weighed as `record_limit` weighs a record** — the JSON of each kept
  reading as the file keeps it — so what is held is what the file costs, in the unit
  the projection multiplies. `series_limit` in `settings.yaml` — a policy, one bound
  meant to hold everywhere, where the count is an editorial choice (decision 4) —
  default **8 MiB**, and not a share of memory, for the reason the entry limit is not
  one: something else binds first. Here it is the file, which the layer rewrites whole
  every interval a series changed — with any check keeping one, every interval — and
  which a keeper carries each time: eight mebibytes of kept readings are a file of
  about thirteen, written in hundredths of a second on the tick.
- **Past it, whole series go, the one written to longest ago first** — by the newest
  reading each was given — until what is held fits. A subject that stopped being
  observed, a deleted branch or a job nobody runs, goes before any that still reports,
  and a tie is broken by the key, so a sweep is repeatable.
- **Said by the process on its own node**, `/little-sister/engine`
  ([ADR-0072](0072-the-instance-reports-on-itself.md) decision 6), as the `series`
  line: WARN from the amber share of the ceiling, 80 %, with what is held; ERROR while
  a sweep in the last ten minutes evicted — curves are being shortened now — naming
  what went, and counting the sweeps where it recurred. Held for the late-tick line's
  window and for its reason: an eviction shortens a curve for good, and a line that
  vanished on the next tick would say so for one second.

### 11. The projection, beside the ceiling

A series fills slowly — at `series_keep: 60` and a two-minute period it is full after
two hours, after days for batch runs — so the ceiling fires long after a configuration
was settled. The estate is known at runtime, though, so every tick computes what this
configuration would need **at today's estate**: for each check that keeps a series, its
`series_keep` times the series it holds times what one of its kept readings weighs on
average. Every factor is measured and none declared, so the number exists from the
first tick after a check's first run and moves with an estate that grows — which, for a
check that discovers its subjects, is the warning. Past the ceiling it is the
`series.projection` line at **WARN**, naming the largest needs: *this configuration
cannot be honored at this estate*. Nothing is broken yet, which is why it does not
share the ceiling's ERROR: the two grade differently or the node cries wolf, and the
hours between them are the time to lower a `series_keep`. `/system` carries both
figures as the third line of the card where the declared load and the entries held
already stand beside what the process measured
([ADR-0075](0075-a-check-declares-what-it-costs.md) decision 8).

## Consequences

- **Nothing changes for a deployment that says nothing**, but a file. The default keeps
  no series, so no reading is held beyond its node and nothing weighs more than it did;
  `var/state/` gains a `series.json` that holds an empty list.
- **A check with `series_keep` set holds up to that many records per subject, and a
  restart keeps them.** Nothing reads them back yet: a subject's page and its curve are
  what they are for, and until those exist a kept series is visible in its file and
  nowhere else.
- **A kept reading weighs more than its record** — its code, its texts, both clocks and
  its identity or state stand beside it — and all of it counts against the ceiling.
- **The total is bounded, and a curve can be shortened.** Past the ceiling the series
  written to longest ago goes and the engine's node is red for ten minutes; a
  configuration that cannot fit says so first, on the first tick after its checks ran.
  Lowering a `series_keep` takes effect on the next tick's sweep. Raising
  `series_limit` costs the file, which a keeper carries every interval a series changed
  — at the default, up to about thirteen mebibytes a copy.
- **Where two checks share a mount** (decision 1), each keeps only what its own
  readings say. What the host node showed with both together is the node's history,
  which the event log keeps.
- **A line that does not carry its reading's record keeps nothing for it.** A grading
  that reshapes the record on the way to its line, or puts none there, leaves its
  readings kept with neither code nor sentence; the authoring guide says to carry the
  record through unchanged.
- **Nor does a reading that its grading shows on no line, unless it names the
  check's own object.** little-sister-github's `actions` aspect writes no line for a
  passing run unless `show_healthy` is set, so with its default that check's series
  keep every passing run without its code, and only the failures with theirs. Taking
  an absence for *OK* is what no reader may do, so a window over such a series grades
  those records again. The same check's estate reading, graded into the root's
  sentence rather than onto a line, stood on the node and keeps what it said there.
- **`Measurement` gains two fields, additively.** A type that names neither an identity
  nor a state is unchanged, and the check API epoch does not move: the surface gains no
  name, and nothing a type already does behaves differently.
- **The authoring guide says what gives a reading a history** — the subject, the
  identity that keeps one event in it once or the state that keeps one spell, and the
  line that says what stood — where a check author reads it
  ([`../implementing-checks.md`](../implementing-checks.md) §2), and every template
  carries `series_keep` commented out, with what it does.

## Alternatives considered

- **The node path as the key**, as the vision first had it. Rejected in decision 1: a
  shared mount would merge two shapes into one series and write records onto a node no
  check owns.
- **The slug as the identity** — append or merge decided by whether a line's slug
  returns. Rejected once the measurement took the object to its subject: a workflow on
  its branch is both a line's slug and its subject, so merging by slug would have left
  that series exactly one record, overwritten every poll — no history of the runs, which
  is the thing that series exists for.
- **A reserved key in the record** for the identity. Rejected in decision 3: it takes a
  name from the check's vocabulary.
- **A state as an identity**, found anywhere in the window as an event is — the rule
  first written for a frozen state. Rejected in decision 3: a state recurs where an
  event does not, so a return to an earlier state rewrote that state's older record
  where it stood; the spell between vanished, and with no time of its own the newest
  record named a state the object had left.
- **A deployment-wide default** in `settings.yaml`. Rejected in decision 4: this is an
  editorial choice per check, not a policy.
- **A non-zero default.** Rejected in decision 4: a history nobody asked for is a cost
  somebody pays.
- **ADR-0047's four retention parameters.** Deferred in decision 4, to a store that
  serves windows longer than memory.
- **Only a silent root rolled up**, as decision 8 first read: a root that grades nothing
  but says what it watches — `little-sister-aws` names the accounts and regions in scope
  on its root — kept `UNDEFINED`, a code none of its readings had, where the same root
  without its sentence kept the roll-up. Rejected: a sentence is not a code, so the two
  roots claim the same, and what stood on both is what the result rolls up to.
- **The node's code after aggregation** for a reading placed on a silent root — what
  the node held once the run's result was stored, the rule first settled for this
  case. Rejected in decision 8: on a shared mount it writes the other check's verdict
  into this check's series, so both series carry one outage; it counts children the
  tree kept from earlier runs; and it changes with which check stored last. With pins
  applied it would also keep an admin's statement about the node instead of a
  reading.
- **A count of readings as the ceiling**, as `entry_limit` counts entries. Rejected in
  decision 10: kept readings differ in weight several times over — a response time
  against a workflow run — the file pays in bytes, and the projection multiplies a
  weight.
- **Trimming the oldest readings of every series** instead of evicting whole ones.
  Rejected in decision 10: it shortens every live curve to spare a dead one, where the
  series written to longest ago is most often a subject nobody observes any more.
- **A projection from what the checks declare**
  ([ADR-0075](0075-a-check-declares-what-it-costs.md)). Rejected in decision 11: a
  check that cannot know its estate declares nothing, which is the case the projection
  is for.
