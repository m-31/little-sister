# ADR-0096 — A measure names its node and its things, and a curve marks only a reading that failed

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** [ADR-0092](0092-a-check-declares-its-measures.md) (the declaration this
  extends, and decisions 3 and 5, which this amends),
  [ADR-0085](0085-a-measure-is-read-out-of-a-record.md) (a measure is a projection over
  the record, and a failed reading is a reading),
  [ADR-0086](0086-a-check-measures-and-grades.md) (one reading a run, and the nodes the
  grading derives from it),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (where the curves this
  declares are shown), [ADR-0075](0075-a-check-declares-what-it-costs.md) (the weight a
  record declares), [ADR-0049](0049-the-check-authoring-surface.md) (the surface
  `measure_defaults` arrives on),
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (the node a
  subject's measure names its node from, and the run the lane marks),
  [ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) (what the lane is for a series
  of runs)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0092](0092-a-check-declares-its-measures.md) drew one curve: an `http` check's
response time, a record of two fields on a node that is also its subject's. The
library's own metric types keep series too — `host-metrics`, `qnap-metrics` and
`macos-memory` place one reading a run on the node that stands for the machine they
read — and none of them declares a measure. Drawing them asks what the first curve did
not:

- **Where an aspect's curve stands.** One reading renders as several nodes
  ([ADR-0085](0085-a-measure-is-read-out-of-a-record.md) decision 2): a host's memory,
  CPU, load and disks are children of the host's node, and each grades one number of
  the reading.
- **How a size is written.** No source reports bytes: `host-metrics` keeps KiB
  (`mem_used_kb`, `disk_avail_kb`), `macos-memory` KiB and MiB. Declared as `KiB`, a
  free-text unit, a reading prints as a bare eight-digit number and the axis label runs
  off the plot; and a NAS volume holds terabytes, which `format_weight`, stopping at
  GiB, writes in thousands of GiB.
- **What the load curve draws.** The load node grades the one-minute load per CPU
  against 0.8 and 1.0, and the record holds `load1` and `ncpu`: on a twelve-core host
  `load1` reads up to 19 while its node reports at most 1.6 per core. A measure is a
  field and its unit, and nothing divides when a curve is drawn.
- **How a thing is named across readings.** A `disk_path: all` run writes `disk1_pct` …
  `disk4_pct`, a NAS `drive1_temp_c` with `drive1_bay` beside it, a Mac its watched
  processes as `proc1_rss_kb` in the order of its configuration. The index is where a
  thing stood in one run's output; the node it becomes is named by what it is.
- **What a mark means.** ADR-0092 decision 5 marks every reading whose measure is null,
  and reads a missing field as null. A field a release adds is missing from every
  reading kept before it; a sensor a model does not have is null in every reading, as
  the one-shape rule asks ([ADR-0085](0085-a-measure-is-read-out-of-a-record.md)
  decision 3); a host that reports its volumes has no `disk_pct` at all. Each would be a
  row of failure marks — a gap taken for a measurement problem.
- **What a type declares.** A curve for every field would repeat itself: a percentage
  and the size it is a percentage of draw one shape.

## Decision

### 1. A measure names the node its curve stands on

The mapping form takes `node` beside `unit` and `label`: a path relative to the node
its reading stands on — `memory`, `disk/root`. That node is the check's own for the one
reading the engine places, and for a subject with a node of its own it is that node
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 2). A
curve stands on the node its measure names, and a measure that names none stands on the
node its reading stands on, as the `http` check's response time does. Where that node
is not in the tree — an aspect the grading did not write — the curve has no page of its
own, and the Series view still carries it
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md)). A `node` that is not
text, that is absolute, or that has an empty, `.` or `..` segment is refused at
startup, naming the file, as every other shape `read_measures` refuses.

### 2. A thing a record counts is keyed by its node's name, and `*` picks it

A type that reports several things of one kind keys each by the name of the node it
becomes, in one mapping, its identity kept inside: `host-metrics` writes
`volumes: {root: {path, pct, avail_kb, total_kb}}`, `qnap-metrics`
`drives: {drive3: {bay, temp_c, smart}}`, `macos-memory`
`processes: {<name>: {count, rss_kb, elapsed_seconds}}`. The positional index leaves
the record, and with it a curve that swaps one thing for another when a run reports
them in another order.

A declaration may write `*` for that key — one whole segment of the field,
`volumes.*.pct` — and the same `*` in its `node` and its `label`:
`volumes.*.pct: {unit: "%", node: disk/*, label: Space used on *}`. One declaration
draws a curve for every key the kept readings hold, each on its own node. `*` picks a
key and computes nothing, so a measure stays a projection
([ADR-0085](0085-a-measure-is-read-out-of-a-record.md) decision 1). A field with two
`*`, a `*` inside a segment, and a `*` in a `node` or a `label` whose field has none are
refused at startup.

### 3. The binary sizes are family units

`B`, `KiB`, `MiB`, `GiB` and `TiB` say what a field's number is in; the page scales it
to bytes and writes it through `format_weight`, which gains TiB. Like a span, every
value and every tick names its unit, so a size axis carries no label; and it steps in
powers of two of a unit — 256 MiB, 512 MiB, 1 GiB — so that a tick lands on a whole
unit. The records keep the numbers their sources report. The decimal spellings — `kB`,
`MB`, `GB` — stay free text: the family writes IEC units, and whether `MB` means 10⁶ or
2²⁰ is the guess a family unit exists to remove. This amends
[ADR-0092](0092-a-check-declares-its-measures.md) decision 3, whose three strings
become seven.

### 4. A curve marks a reading that failed, and only that

A reading failed where its record carries an `error` that is not null — the key the
engine writes for a check that raised, the seam for a record it refused, and every
library type for a reading that did not answer. A failed reading is marked on every
curve of its series, in the lane beneath the baseline. A reading that answered but gives
a measure no number — a field its source does not have, a thing absent from that
reading, a field a release added after the reading was kept — breaks the line with no
mark, as a hole does. A measure with no number anywhere in the kept window draws no
curve.

`error` is therefore a named key of every record: a type writes it wherever a reading
did not measure. The SSH types, which recorded a script that failed by its exit code and
an answer they could not read by its output, write it for those too. This amends
[ADR-0092](0092-a-check-declares-its-measures.md) decision 5, and says what
[ADR-0085](0085-a-measure-is-read-out-of-a-record.md) decision 3's nulls were for: one
shape for every reading, with the failure said beside them.

For a series of runs the lane also marks a run whose reading stood `ERROR`
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 5), and no
other — a run that warned or kept no verdict has a mark of its own in the plot — once
for each column, beneath a plot that has a value axis
([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) decisions 1, 3 and 4).

### 5. `host-metrics` writes the load it grades

The record gains `load1_per_core` — `load1` over the CPUs the host had at that reading,
at least one, as the grading has always divided it — and the load node grades that
field. `load1` and `ncpu` stay. The curve, the sentence and the thresholds read one
number, and a host that grows from four cores to eight keeps a true history, each
reading divided by the cores it had.

### 6. The library's types declare the numbers they grade

A type's defaults are the fields its nodes are graded on, each standing on the node it
grades:

| Type | Field | Unit | Node |
|------|-------|------|------|
| `host-metrics` | `mem_pct` | `%` | `memory` |
| | `cpu_pct` | `%` | `cpu` |
| | `load1_per_core` | `per core` | `load` |
| | `disk_pct` | `%` | `disk` |
| | `volumes.*.pct` | `%` | `disk/*` |
| `qnap-metrics` | `sys_temp_c` | `°C` | `temperature/system` |
| | `cpu_temp_c` | `°C` | `temperature/cpu` |
| | `drives.*.temp_c` | `°C` | `temperature/*` |
| `macos-memory` | `pressure_level` | none | `pressure` |
| | `compressor_pct` | `%` | `compressor` |
| | `swap_used_mb` | `MiB` | `swap` |
| | `processes.*.rss_kb` | `KiB` | `processes/*` |

`file` declares none: its one value is a time, and an age is a fact about now, which its
measuring half never writes. The sizes behind the percentages — `mem_used_kb`,
`disk_avail_kb` — are a deployment's to add: by default they would draw their
percentage's shape again, against a total that hardly moves. The swap and process
sentences write their sizes through `format_weight`, so that a node and its curve write
one figure one way.

## Consequences

- **Three record shapes change.** `host-metrics`' `disk_count` and `disk{i}_*`,
  `qnap-metrics`' `drive_count` and `drive{i}_*` and `macos-memory`'s `proc{i}_*` become
  the mappings of decision 2, and `host-metrics` gains `load1_per_core`. The API's
  `record` is free-form in the check's own keys, so the contract does not move; a
  consumer that read an indexed key reads the mapping. Readings kept before the release
  keep their shape: the new curves start at the release, and the readings before it
  break no line with a mark (decision 4).
- **A record's key is a stored key once a `measures:` block names it**, as a slug or a
  configuration key is: renaming it breaks every deployment that draws it.
- **`node` and `*` join the declaration** additively: the check-authoring surface grows
  ([ADR-0049](0049-the-check-authoring-surface.md)) and the check API epoch does not
  move.
- **A check that failed across its whole window draws no curve**; its status and the
  failures in its readings say so.
- **The weights move** ([ADR-0075](0075-a-check-declares-what-it-costs.md)): each of the
  three types re-measures what a reading declares.

## Alternatives considered

- **Every curve on the check's own node** — the aspect a curve grades is where its
  thresholds and its sentence are, and on a host that has five of them, one node would
  carry every curve.
- **The types writing bytes** — a changed field splits every kept history at the
  release, and a new one doubles every size in every record.
- **Sizes left to the deployments** — the formatting stays deferred, and the first size
  curve anybody declares has an axis that runs off its plot.
- **The absolute load, or a divisor in the declaration** — the first disagrees with the
  node it is drawn on; the second makes a measure a formula and computes the graded
  number twice.
- **Positional fields, or a template matched per reading** — the first swaps things
  silently when an order changes; the second joins fields when a curve is drawn and
  repeats the grading's naming of nodes in the page.
- **Every null and every absence marked, as ADR-0092 had it** — a field a release adds,
  a sensor a model lacks and a host's other disk shape each become a row of failure
  marks.
- **An absence plain and a null marked** — the engine's failure record has every field
  absent, so a check that raised would draw no mark at all.
- **The sizes behind the percentages by default, or one curve a type** — the first draws
  shapes twice; the second leaves graded aspects without a history.
