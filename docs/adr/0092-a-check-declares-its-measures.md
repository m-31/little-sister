# ADR-0092 — A check declares its measures, and the node that stands for a subject shows its series

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-09-27)
- **Related:** [ADR-0085](0085-a-measure-is-read-out-of-a-record.md) (a measure is a
  projection over the record, and its unit belongs to it — the declaration this adds),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (the series, its order and
  `series_keep`), [ADR-0086](0086-a-check-measures-and-grades.md) (the one placed
  reading, on the node that stands for its object),
  [ADR-0025](0025-check-provided-subnode-metadata.md) (the `subnodes:` merge this
  follows), [ADR-0056](0056-stable-useful-dashboard-flow.md) (the display caps
  `reading_cap` joins), [ADR-0079](0079-freshness-is-a-stated-tolerance.md) (the
  tolerance a hole is measured against),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision 7, the configured
  timezone), [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)
  (the record list a reading's fields are written through),
  [ADR-0049](0049-the-check-authoring-surface.md) (the surface a type's default
  arrives on), [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) (the binary
  sizes among the family's units, and the `error` a curve marks),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (the Series view, and the
  check's period a hole is measured by),
  [ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md) (the readings
  table's box and its headings),
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (the node of a
  subject whose reading rides on a line, and a run's mark),
  [ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) (the records a mark is drawn
  for), [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) (decisions 1, 2 and
  5: the window a Series view is drawn over, and a window drawn column by column),
  [ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md) (a series read over
  the API), [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (decision 8: *Handled*, which lists every pin)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check that sets `series_keep` keeps its subjects' readings across restarts
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md)), and nothing draws them.
[ADR-0085](0085-a-measure-is-read-out-of-a-record.md) settled what a measure is — a
projection over the record, chosen when it is drawn rather than typed when it is
written, its unit belonging to the projection so that a wrong one costs an axis label
and never a poisoned series — and said that a curve's axis is labeled where the curve
is declared. Where that is, it left open: nothing declares a record's measures.

The first case is the `http` check. Its record is `{status, response_ms}`, both null on
a request that failed, and a deployment keeps a day of it for one site. Drawing it asks
seven things the model does not yet answer: where a measure is declared and with what
unit; how a type's default and a deployment's choice combine; what a unit is; which
clock a point sits on; how a failed reading differs from a stretch in which nothing was
read; where a subject's series is shown; and how much of it a page carries.

## Decision

### 1. A check's configuration declares its measures, and its type may declare the default

`measures:` is a common field of every check's YAML, beside `series_keep`, read by the
library for every type. It maps a field's dotted name, spelled as the node's record list
spells it, to its unit — `response_ms: ms` — or, where a label is wanted, to
`{unit: ms, label: Response time}`. A type passes the same mapping to its constructor
as `measure_defaults`, shaped like the block the way `subnode_defaults` is shaped like
`subnodes:` ([ADR-0025](0025-check-provided-subnode-metadata.md) decision 5): what a
field of its record means and in which unit is the type's knowledge, and whether it is
drawn is the deployment's.

The name is the model's own. A measure is a projection over the record
([ADR-0085](0085-a-measure-is-read-out-of-a-record.md)); a curve is how a page draws
one, and grading over a window will read the same declaration rather than a second one
under a name that describes a picture.

### 2. The configuration merges over the default per field

A field the configuration names takes its entry; every other field keeps the type's
default; `field: null` removes a default; an absent or empty block leaves the defaults
standing — the resolution a deployment already knows from `subnodes:`. So adding a
measure restates nothing, and a default a later release of the type adds still reaches
every deployment that did not remove it. A block of another shape — a unit that is not a
string, a name that is not a field's — is refused at startup, naming the file, as a bad
`series_keep` is.

### 3. A unit is free text, and the family's own units are formatted

Any string is a unit: it is printed beside a value and once as the axis label, and
nothing is ever refused for its unit, because a wrong one costs a label
([ADR-0085](0085-a-measure-is-read-out-of-a-record.md) decision 1). Seven strings mean
more to the page, because the family already writes them: `ms` and `s` are written
through `format_span`, so 1,850 ms reads `1.9 s`, and `B`, `KiB`, `MiB`, `GiB` and
`TiB` through `format_weight`
([ADR-0096](0096-a-measure-names-its-node-and-its-things.md) decision 3). A value
written that way names its own unit, on every tick of its axis too, so that axis needs
no label of its own: `ms` above `1.9 s` would only contradict it. The unit decides how
a number is written; what a field is stays the declaration's.

### 4. A point sits on its series' own clock, drawn to scale, in the configured timezone

A reading's place on the time axis is the time its series orders it by: the record's
top-level `at` where it has one, and otherwise when it was first observed
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md)). So a run sits where it
finished, a response time where it was read, and the curve and the table below it read
the same readings in the same order. The axis is proportional to time, so a night
without readings is a night wide.

Its times read in `settings.yaml`'s `timezone` and `time_format`, or their defaults,
as every other time a page shows ([ADR-0120](0120-every-stored-time-is-an-instant.md)
decision 7): that
is what *the viewer's timezone* has meant on every server-rendered page. A zone per
browser or per user would be a preference of its own, and there is none.

### 5. A failure is marked, a hole is left plain

A curve spans what its series keeps, or the window its Series view is drawn over where
the view's URL names one
([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decisions 1 and 2). A reading
whose record carries an `error`
([ADR-0096](0096-a-measure-names-its-node-and-its-things.md) decision 4) — the request
that failed — breaks the line and is marked at its instant in the error ink, beneath
the baseline so that it is never read as a zero: a failure is a reading, and it says
the object did not answer. A reading that answered without a number — a field the
record does not have, which a projection reads as null
([ADR-0085](0085-a-measure-is-read-out-of-a-record.md)), or a value that is not a
number — breaks the line with no mark. Two neighboring readings further apart than the
freshness tolerance their check's own period implies
([ADR-0079](0079-freshness-is-a-stated-tolerance.md): the frequency and the larger of
the frequency and 30 s) have a hole between them — a restart, a pause, a machine
asleep — and the line breaks there without a mark. The period is the check's and not
the node's ([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 1),
since a node two checks share carries the period of whichever wrote it last. One missed
poll is not a hole, as it does not make the node stale either. The line never crosses a
hole, because across it there is nothing that was read. Drawn column by column, as a
window with more readings than the plot has columns is
([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 5), the line breaks
at a hole at least a column wide and at a column none of whose readings has a number,
and a column that holds a failed reading carries one mark.

A series of events — records with an identity or a state, whose source keeps the
history — has no cadence for a tolerance to measure. It is drawn as a mark for each run
at its own time — a tick, or a stem to its value where a measure is declared — with no
line between two runs
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 5). A mark
is drawn for a record with an identity, and a record with a state has none: it stays a
row of its readings table
([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) decision 5).

### 6. The node that stands for a subject shows its series

Where the engine places a reading on the node that stands for its object
([ADR-0086](0086-a-check-measures-and-grades.md)), that node shows the subject's
series. Its facts — `_node_facts.html`, on the node's own page and on a branch's — show
the curves that stand on it, and its Series view, `/series/<path>`, every curve at or
beneath it
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decisions 1 and 2), as
server-rendered SVG with no script of its own. Beneath its curves the Series view shows
the newest `reading_cap` readings of each series as a table — the time on the series'
clock with the code the reading stood with as a cue beside it, a column per field
written through the record list's `record_fields` (so a time reads in the configured
zone and everything else as it was stored), and the sentence as it stood. The table is
a box that holds its heading row and its Time column still; a field a measure declares
is headed by its label and unit over the field's name, and the declared columns come
first
([ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md) decisions 1 and 2).
Every kept reading is on the node's History page, `/history/<path>`, in the same table
beneath its status periods; that page is not polled.

A subject whose reading rides on a line has a node of its own
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decisions 1 and 4),
which shows its series.

### 7. How many readings the Series view shows is a cap: `reading_cap`

A non-negative integer in `settings.yaml`, beside the other display caps
([ADR-0056](0056-stable-useful-dashboard-flow.md)), 10 by default; and optionally in a
check's own YAML beside `series_keep`, where it wins for that check. It counts the rows
the Series view shows of each series
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 2): `0` shows the
curves alone and leaves every reading to the History page, as `maintenance_cap: 0`
sends every pin to *Handled*
([ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
decision 8). A bad value in `settings.yaml` is logged and
replaced, as every setting's is ([ADR-0120](0120-every-stored-time-is-an-instant.md)
decision 7): one
that is not a whole number by the default, a negative one by `0`. In a check's YAML it
is refused at startup, naming the file, as a bad `series_keep` is.

## Consequences

- **Three stored keys and a keyword.** `measures:`, and `reading_cap` in both places,
  are written into deployments' files and so are kept as named; `measure_defaults` is a
  keyword added to the check-authoring surface, which is compatible
  ([ADR-0049](0049-the-check-authoring-surface.md)) and does not move the check API
  epoch.
- **The `http` type declares `response_ms` in `ms`**, labeled *Response time*, as its
  default, so a deployment that keeps its series draws the curve with no key of its own.
- **A Series view carries at most `reading_cap` rows of each series**; the whole table
  is on the History page.
- **A subject's recent history is part of its status**, and the core's line stays
  *status, not telemetry*: a series is bounded per subject and read where the subject
  is.
- **The envelope does not move.** Reading a series over the API is a change of its own,
  [ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md)'s.

## Alternatives considered

- **`curves:`** — the drawing's name. Grading over a window would have read a key named
  for a picture or declared the same field and unit again.
- **The configuration replacing the type's defaults whole** — one file would say
  everything, but adding one measure means copying the defaults, the copy goes stale,
  and a default a later release adds never arrives.
- **A closed vocabulary of units** — refusing `req/s` at startup turns
  [ADR-0085](0085-a-measure-is-read-out-of-a-record.md)'s cheap failure, a wrong label,
  into a start that fails.
- **Our clock for every point, or points evenly spaced** — the first stacks a source's
  runs on the instant they were read and moves a run re-read on the next poll; the
  second makes a minute's pause and a night's look alike.
- **Every absence breaking the line alike, or the line crossing a hole** — the first
  reads a restart as an outage, the second draws values nobody read.
- **A route of its own for every subject** — the route gives one object two pages and
  puts a provider identifier in the URL, outside the node's breadcrumb, pins and
  maintenance.
- **Every reading on the node's page, folded** — on a polled branch page every row would
  travel with every poll.
- **`reading_cap` only per check, or only in `settings.yaml`** — the first puts a
  display number in every check's file; the second leaves a check whose readings matter
  more with no way to show more of them.
