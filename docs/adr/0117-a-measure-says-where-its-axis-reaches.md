# ADR-0117 — A measure says where its axis reaches

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0092](0092-a-check-declares-its-measures.md) (decision 1: the
  `measures:` block and a type's `measure_defaults`; decision 2: merged per field;
  decision 3: a unit is free text and nothing is refused for it),
  [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) (the entry's `node`,
  and one `*` for the key a thing is counted by),
  [ADR-0114](0114-a-curve-seen-small-and-the-series-tabs-count.md) (a sparkline is
  the curve's own plot on the curve's scale, from zero),
  [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) (decision 5: no spike is
  lost in a drawing)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A curve's value axis starts at zero and ends a step past its own highest reading. One
host's memory at 17 to 18 % is drawn near the top of an axis that ends at 20; another's
at 72 to 81 % near the top of one that ends at 100. As two curves a page apart nobody
compared them. As two sparklines in one list (ADR-0114) they look alike, and a reader
who takes a strip near its top for a full memory is wrong about the first host.

The drawing cannot know that a number is a percent of a whole. A unit is free text
(ADR-0092 decision 3), `%` is also what a growth rate and a load over several cores
are written in, and a temperature or a quota has an end the unit does not name at all.

## Decision

1. **A measure may declare where its axis reaches: `axis_to`.** It is a key of a
   measure's entry — `mem_pct: {unit: "%", axis_to: 100}` — in a check's `measures:`
   and in a type's `measure_defaults`, beside `unit`, `label` and `node`, and merged
   as they are: an entry the configuration names is taken whole, so a relabeled
   default restates its `axis_to` as it restates its unit, and `null` removes the
   measure. A measure written with one `*` hands it to every key the `*` stands for.
   It is a stored key.
2. **The axis reaches the declared end whatever the readings are below it** — the
   curve's and its sparkline's, which is the same plot. The axis ends on the whole
   step that reaches it: at 100 for `axis_to: 100`, and at 100 for `axis_to: 90`
   too, a tick landing on a round number as before.
3. **A reading above it grows the axis.** The axis then ends a step past that
   reading, exactly as one without the key does; nothing is cut off, marked or
   refused. The key says where the axis reaches at least, which is why it is not
   named for a limit.
4. **No lower end is declarable.** The axis starts at zero, and below it where a
   reading is, as ADR-0114 argued for.
5. **A value that is not a positive, finite number refuses the load**, naming the
   file and the key, as a `measures:` block of another shape does.
6. **The library's own measures that are a percent of a whole declare 100**, by
   their type's default: `host-metrics`' `mem_pct`, `cpu_pct` (100 % less idle, over
   all cores), `disk_pct` and `volumes.*.pct`, and `macos-memory`'s `compressor_pct`
   (of physical memory). None of its other measures declares an end: a load per
   core passes 1, a temperature's rated maximum is its device's, and a size, a span
   and a level have none.

## Consequences

- On upgrade the five curves above are drawn to 100 on every deployment that did not
  replace their entry: a memory at 18 % sits low on its plot where it sat near the
  top. A deployment that wants the old picture names the field without the key.
- A deployment that relabeled one of these defaults keeps the axis it had, its entry
  being taken whole, until it adds the key.
- A wrong declaration costs the comparison it was written for and nothing else.
- `Measure` gains `axis_to`, `None` where none is declared. The numbers beside a
  curve — newest, lowest, highest — are its readings', as before.
- A package's type declares the key for its own percents the same way; one built
  against an older library that passes it is refused there, as any key the entry
  does not take.

## Alternatives considered

- **The unit implies it: `%` ends at 100.** No key, and a unit would decide more than
  how a number is written; a percent that passes 100 by right would be drawn against
  an end it does not have.
- **Curves of one kind share a scale on the page.** No key, and a curve's scale would
  depend on what else the page lists: the same memory drawn two ways on the index and
  on its own node.
- **The curve clipped at the declared end, with a mark.** Always comparable, and the
  drawing hides how far over a reading went — the one thing a reader of a spike wants.
- **A reading above the end refused.** A hint for a drawing turned into a rule about
  the record, which no other part of a measure's declaration is.
- **A lower end, or one at or below zero only.** Nothing asked for it; a raised floor
  is the lively strip ADR-0114 refused, and a key that is not stored can be added
  when a signed measure wants a symmetric axis.
- **Bounds for every measure a type knows one for.** A drive's rated temperature and
  a quota's limit vary by device, and each would be a claim to keep right.
