# ADR-0103 — The Series index says where each link leads, and names each node once

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (decision 4,
  the index; decision 1, a Series view holds every curve at or beneath its node),
  [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md) (a path that opens the
  node's Status page, on Events), [ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md)
  (the History page a node's readings are on)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The Series index lists every node a series is kept on, grouped under its root node
(ADR-0097 decision 4). A node's name opened its Series view where its series drew
curves and its History page where they drew none, and a root's heading opened the root's
Series view. A root with a check mounted on itself — nearly every host — appeared twice,
as the heading and as its own row, and for a root without curves the two identical names
led to different pages, one of them a Series view saying *No curves to display*. A row
listed the label of every curve it draws, which made some rows several lines tall, and a
row without curves repeated *none — its readings are on its History page*. A reader could
not tell where a name would lead without trying it.

## Decision

### 1. A name opens its node; a row says in words where else it leads

A node's name opens its Status page, as a path does everywhere else — on Events, on the
Series view's group headings. Each row ends with *curves*, which opens the node's Series
view, where a curve stands at or beneath the node, and *readings*, which opens its
History page, where its own series are kept.

### 2. The Curves column counts, and the labels fold behind the count

*5 curves* — *1 curve* — opens to the labels of the curves the node's own series draw; a
node whose series draw none shows *—*. Every row stays one line. A browser's find opens a
closed fold where it lands — Chrome, Firefox from 139 and Safari from 26.2 — so a named
measure is still found, and the index has no search box of its own.

### 3. A root appears once: its heading is its own row

A root's heading line carries what the root keeps itself — the checks keeping it, its
curves, its readings, the newest one's time, and its *curves* and *readings* — and those
cells stay empty where it keeps nothing. The nodes beneath it follow, indented. Its
*curves* opens its Series view, which holds every curve at or beneath it (ADR-0097
decision 1), so the total that stood beside its name goes: every line counts the curves
its own node's series draw.

## Consequences

- **ADR-0097 decision 4 is rewritten in place**, since the record has not shipped: its
  sentence on where a name leads is this record's.
- **A bookmark of a row's old destination** still opens it; only which link on the index
  leads there has changed.
- **Nothing moves on the API**, which carries no index.

## Alternatives considered

- **The same two words with the name as plain text**: fewer links, and the one path in
  the application that leads nowhere. **The name's link kept, only the duplicate
  folded**: the name still leads to different pages on different rows.
- **The count and the first three labels**: the commonest measures in sight, and the rest
  behind a fold or on the Series view all the same. **The full list in small type**: the
  long rows of the finding, smaller. **A search box**: what a browser's find does already.
- **The heading kept as the group, the root's own row saying *itself***: plain, and a
  host still two lines. **Both lines left**: harmless once both names open the Status
  page, and a line per root that keeps a series itself.

