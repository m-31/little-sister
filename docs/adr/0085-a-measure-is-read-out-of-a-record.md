# ADR-0085 — A measure is read out of a record, not declared into it

- **Status:** Accepted
- **Date:** 2026-09-19
- **Related:** [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)
  (the record this reads from, and the `subject` this finally uses),
  [ADR-0042](0042-entries-carry-their-own-code.md) (why the line carries no code),
  [ADR-0036](0036-addressable-reasons.md) (the slug a pin holds),
  [ADR-0044](0044-run-facts-on-the-node.md) (the run's own time, which this is not),
  [ADR-0024](0024-dashboard-layout.md) (the density rule that made a healthy line
  free), [ADR-0063](0063-declining-the-density-trade.md) (the lever a deployment has
  where it is not), [ADR-0075](0075-a-check-declares-what-it-costs.md) (the cost this
  declares), [ADR-0058](0058-transport-policy-vocabulary.md) (this check's readings)
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — a node's `subject` and
  `record`, from 2.5.0.

## Context

`HttpCheck.run` asked for a status and stopped. So the family's most common check — a
URL, every few minutes, in every deployment — produced **no number at all**, while a
response time is the most natural measurement in the estate: no vendor, no fixture, and
it lives in the library where nothing has to be coordinated.

The timing is two lines around `fetch`. What made this worth a record is that the
series is the next round, and a round about *records over time* designed with no real
measurement in hand would be designed against an abstraction.

## Decision

### 1. A measure is a projection over the record, chosen when it is drawn

Not a typed field declared at the seam. The record already carries what the check read;
a *measure* is what somebody later decides to read out of it — the same footing this
project already gives the two neighbouring operations, where **grading is extraction
from a field** and **rendering is a choice about the record**. Typing a measure at
write time would make measurement the one thing settled when we know least:
before there is a curve, before there is a second check to compare it against, and
before anybody has asked the question the number is meant to answer.

It also survives a check that changes what it reads. A record with a field missing
gives a curve a **gap**; a schema declared a year earlier gives it nothing, because
what was never declared was never kept.

**The unit belongs to the projection**, not to the record. A curve's axis is labelled
where the curve is declared. What the record holds is a number, and the key names its
unit — `response_ms` — because a record renders as its keys (ADR-0082's untyped
rendering), so the name is what a reader sees. The difference matters in the failure
case: under a typed measure a check writing seconds where another wrote milliseconds
would silently poison a stored series, while here it costs a wrong axis label, which is
a thing somebody fixes.

### 2. A measurement belongs to the run, and names the object it was taken on

A check run reads **one object**, and the result is **one record**. What the check then
writes — a node, a subtree of children, a line — is *derived* from that reading. So the
record belongs to the `CheckResult`, and a line carries one only where the object has no
node of its own.

The case that decides it is a host-metrics check: one SSH call, one script, one flat
reading, out of which the check builds `ssh`, `disk`, `memory`, `cpu` and `load`. There
is no line for the record to ride on, and those five nodes are renderings of one
measurement, not five measurements. Putting the record on a line would either invent a
line to carry it or split one reading into five at write time — the same premature
extraction decision 1 refuses, one level up.

Where the object has **no node** — a repository, a load-test run, a security finding —
it is a line, and `Entry.data` carries its record there. That is the special case, and
it is the one a check has to name itself in: a line's `subject` says which thing in the
world it is about.

**Every measurement names its object**, node or no node, because the node's path does
not: the path is the deployment's label for where a node hangs, and it is editorial.
`/hosts/web01` measures `web01.example`, `/hosts/nas/system` measures `nas01`, and a
rate-limit check learns its object only from the answer. An identity that is not written
down at the reading cannot be added to the history afterwards.

### 3. What is measured is the subject, and only when it answered

The timer wraps the call and nothing else. It measures the endpoint — how long the
world took — and not our run, which the engine already times as `run.wall_seconds`
(ADR-0044). One says how the world is, the other how we are, and a monitor that
confuses them reports its own slowness as an outage.

A status nobody expected *is* a measurement: a `503` answered, and how fast it answered
is a reading about the object.

**And a failed reading is a reading.** A request that never answered still taught the
check something — that it could not get there, and why — so it is recorded, with
`status` and `response_ms` standing as **null** rather than being left out. Two reasons,
and the second is the load-bearing one. One shape per check means a curve draws a real
gap from a null instead of inferring one from an absence. And a series without failures
carries a *hole*, which cannot be told apart from a restart, a pause, or a poll that
never happened — whereas a recorded failure puts availability in the data itself: how
many readings answered, over how many there were. Without it the denominator has to come
from outside the series, from the check's cadence, which nothing stores beside it.

What the nulls must **not** hold is how long we waited before giving up. That is the
timeout's number, not the endpoint's, and under `response_ms` it would seed a series
with values that are not the thing it measures. The reason for the failure rides beside
them, and only where there was one: carrying it as a null on every successful reading
would lengthen every record for nothing, since a projection treats a missing key as an
empty one.

### 4. One line, no code of its own, one slug

The line carries no `code`: with a single line the node's own reading is already the
verdict, and a coded entry beside a declared result code is the shape `CheckResult`
refuses (ADR-0042) — which is what lets this check go on declaring `OK` and `ERROR`
itself.

Its slug is a constant. Addressing exists to tell sibling lines apart (ADR-0036) and
there are no siblings here; what a slug must be is **the same across readings**, because
a pin holds one and the line an operator silenced has to be the line the next run
reports. A *derived* slug is SHA-1 of the sentence, so it would mint a new one every
poll as the number in it moves.

### 5. The healthy line costs what it was feared to cost, which is nearly nothing

This was held back for a year on the grounds that a line on the healthy path is a
visible change to every dashboard running it. Measured against the grid rendered
with and without one: **byte-identical** in the default dashboard and under hide-ok,
because a quiet `OK` leaf already collapses to a chip (ADR-0024) and its lines live on
its own page. It differs in one layout — chips off — where the line joins the card, and
there `show_when_quiet` (ADR-0063) is the lever a deployment already has, without the
check's cooperation.

What it holds is one entry and one record per check, declared to the startup sum
(ADR-0075) so a deployment can see the cost before it pays it.

## Consequences

- **The most common check in the family now holds one entry and one record per run.**
  Small per check, real across an estate, and priced by the declarations rather than
  discovered.
- **An `http` node's page gains a record**, rendered untyped like every other, and an
  operator can pin the line rather than only the node.
- **A node's measurement is written through on every run**, so what stands there is the
  current reading. A run that measured nothing clears the last one rather than leaving
  it dated by a newer timestamp — the node's `timestamp` moves with every run, so a kept
  record would not be undated but **wrongly dated**. A caller that says nothing about a
  measurement leaves it alone, so a direct `upsert` does not wipe a check's reading.
- **The envelope's minor moves to 2.5.0**, additively: a node carries `subject` and
  `record`, which is where a measurement now lives (ADR-0080 decision 1, and the golden
  envelope artifact is regenerated in the same change). A node no check measures carries
  an empty subject and a null record, as does a mount two checks share, where the last
  writer cannot be believed — the same rule the node's text and run facts already
  follow.
- **The series inherits a decision it did not have to make.** It keeps **whole
  records** with a count ceiling, in memory for now (a store sits behind #65's seam
  later), because mapping-when-drawn is only possible if what was read is what is kept.
- **A curve is still not drawn.** That is the series' half, and it now has one real
  case to be designed against.

## Alternatives considered

- **A typed measure at the seam** — `{"value": 412, "unit": "ms"}`, recognised by shape
  at any depth or under a reserved `measures` key. Rejected in decision 1: it settles at
  write time what is only knowable at read time, and its failure mode is a poisoned
  series rather than a wrong label.
- **A record only on a line**, as this record first had it, with a single-object check
  growing a line to carry one. Rejected in decision 2 once every check in two
  deployments was walked through: a host-metrics run has no line to hang it on, and the
  ceremony was a transport problem dressed as a model.
- **Timing the failure too**, under the same name. Rejected in decision 3: it is the
  timeout's number, not the endpoint's — though the failure itself is recorded, which is
  a different thing.
- **Leaving a failed reading out of the record entirely**, as this record first had it,
  on the grounds that nothing was read. Reversed in decision 3: something *was* learned,
  and a series of gaps cannot answer the one question a series of failures answers for
  free.
- **A unit vocabulary** — a closed set of physical units plus an escape for counts,
  where 12 deployments have the counted thing as their unit. Not needed once the unit
  belongs to the projection; the question returns when a curve is declared, which is
  where it can be answered against a real axis.
- **Waiting for the series.** Rejected once the density cost was measured rather than
  assumed: nothing about this needs a store, and the series is better designed with a
  measurement in hand.
