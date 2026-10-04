# ADR-0102 — A readings table keeps time and names in view; a quiet log says what it means

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0092](0092-a-check-declares-its-measures.md) (decision 6, the
  readings table; the measures whose labels and units head it),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (decision 1, History
  carries every reading), [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md)
  (decision 2, a window is the Series view's and not History's),
  [ADR-0094](0094-a-restart-is-no-transition.md) (decision 5, a container's
  `UNDEFINED` is no row), [ADR-0099](0099-a-status-that-still-holds-says-since-when.md)
  (decision 2, the current row reads *current*; decisions 1 and 9, a bound),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (decision 5,
  the kept entry a quiet node's period is read from),
  [ADR-0027](0027-observation-timestamp-semantics.md) (an observed node carries a stamp)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

History lists every reading a node's checks keep, newest first, in one table. A host
keeps 720 of them, each with a dozen and a half fields named as the record names them —
`exit_code`, `mem_pct`, `mem_used_kb`, `uptime_seconds` — in the record's order, on a
page 980 pixels wide. The columns past its right edge are reached by a scrollbar at the
table's foot, 720 rows down; the column names and the times scroll away with the first
rows; and the measures the check declared, the fields it thinks worth reading, each with
a label and a unit, stand among the counters wherever the record put them.

Above the readings, the periods table said *No status changes recorded* in two cases
that have nothing in common: a container, which declares no status of its own, and a
leaf whose one transition the bounded log has dropped. Neither is what the sentence
says, and read beside hundreds of readings it looks like a contradiction.

## Decision

### 1. A readings table is a box that keeps its times and names in view

The table sits in a box as wide as the page and about as tall as the window, and
scrolls both ways inside it: its heading row and its Time column hold still, and the
box's own scrollbars stand at its edges, where they can be seen. Every reading stays on
the page (ADR-0097 decision 1), so a browser's search reaches each of them, and nothing
needs a script. The Time column carries the reading's cue beside its time, so that one
column holds still rather than two. The box is a region with a name and a place in the
tab order, so a keyboard can scroll it. History's readings take the page's width, while
its periods keep the measure they had; the Series view's tables, drawn by the same
macro, sit in the same box.

### 2. A column says what its check declares, and the declared ones lead

A field a measure declares (ADR-0092) is headed by the measure's label and unit —
*Memory in use · %* — with the field's name beneath it, small; a measure with a `*` heads
one column for each key it expands to, as its curves do. Where a measure's label is its
field's name, the name stands alone with the unit beside it. A field no measure declares
keeps its name alone, and a declared field no reading carries has no column. The
declared columns come first, in the order they are declared, and the rest follow in the
record's own order, read from the oldest record on, so a field the newest reading
lacks keeps its place. A cell holds the value as it was stored,
a field a reading lacks stays an empty cell, and nothing is inferred from a field's
name.

### 3. A quiet log says what it means

Where the log holds no change of a node's status, History says which quiet it is. A
node that declares nothing of its own above nodes that report (ADR-0094 decision 5)
says so in the sentence it uses once it has stopped declaring: *Declares nothing of its
own: its page heads with what its children roll up to.* A node a check has written and
that has a status of its own gets the row of the period that holds: its status, when
the period began as the kept table says it (ADR-0110 decision 5) — the instant, or
*before* a bound where no beginning is known (ADR-0099 decisions 1 and 9) — *current*,
and its reason. A bound is what the tree can prove and not an onset it guesses: the log
records every change of what a node shows, so a node it held no row of had shown the
same since at least its oldest event when the bound was taken. A node no check has
written yet, and nothing is kept of, has no period and keeps *No status changes
recorded*.

## Consequences

- **ADR-0092 decision 6's table is amended**: where its columns stand and what heads
  them; its rows and cells are as they were.
- **The Time card and the Copy document state the same beginning**: a node the log
  holds no change of holds its status *since* the instant the kept table says, or *since
  before* its bound, there too (ADR-0099 decision 1), from the one rule that bounds
  every period a surface states.
- **Nothing moves on a contract**: these are pages, and the JSON envelope carries no
  readings and no periods.

## Alternatives considered

- **The newest rows, the rest one click away**: a short page, and the same scrollbar
  and the same headings leaving view on the full list; a bounded list must also never
  read as data thrown away. **One fold per day**: a sticky heading per fold, and a
  reading near midnight apart from its neighbor.
- **The same headings in the record's order**: nothing moves, and a declared measure
  stands ninth among counters. **Field names with the label in a tooltip**: one-line
  headings, and a label out of reach on touch and keyboard.
- **A sticky cue column beside a sticky time column**: the second needs the first's
  width, which the configured time format decides.
- **Two sentences and no row**, or **one sentence for both quiets**: the first leaves a
  node with a status without the row every other node has; the second still cannot tell
  a container from a steady leaf.

