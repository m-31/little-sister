# ADR-0114 — A curve is seen small beside its name, from zero, and the Series tab counts its curves

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (decision 3,
  the tabs; decision 4, the index, which this draws on),
  [ADR-0103](0103-the-series-index-says-where-each-link-leads.md) (decision 2: a row
  counts its curves and folds their labels behind the count),
  [ADR-0092](0092-a-check-declares-its-measures.md) (decision 5) and
  [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) (decision 4): what
  breaks a curve's line,
  [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) (decision 5: a window with
  more readings than a plot has columns is drawn column by column, and no spike is
  lost), [ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) (a run is a mark),
  [ADR-0105](0105-a-page-is-laid-out-at-its-screens-width.md) (a table wider than a
  screen scrolls in its box)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The Series index named every curve a node's series draw, and drew none. To know
whether a curve was worth opening a reader opened its node's Series view. And a node's
Series tab said that a view was there, never how much was on it: a branch high in the
tree and a leaf with one measure had the same tab.

A curve drawn small has one question to settle, and the mock that first drew one
raised it: its scale. From the lowest reading to the highest, every sparkline fills its
height, so a tenth of a GiB of jitter reads as a swing, two of them side by side cannot
be compared, and each contradicts the curve it leads to, whose value axis starts at
zero — below it where a value is. From zero, a
disk that stands at ninety percent is a flat line near the top: true, and telling
nothing.

## Decision

### 1. A curve seen small is the curve's own plot, from zero

A sparkline is the plot of the curve it stands for with nothing around it — from the
top of the curve's scale down to its baseline, which is its zero — squeezed into a strip
120 pixels wide and the height of a line of text. So it is on the curve's own scale,
and a glance and a click never disagree. It breaks where the curve breaks: at a reading
that failed, at one that answered without a number, and at a stretch without readings
longer than the node's tolerance. A reading that stands alone is a dot; a run is its
stem, in the ink of how it stood.

Where a series holds more readings than the strip has columns — sixty, two pixels each
— it is drawn column by column as a curve is over a long window
([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 5): each column's
first, last, lowest and highest reading, so no spike is lost.

It has no axis, no step and nothing under a pointer, and no instant is written to draw
it: a formatted time for every reading is what made drawing every curve of an instance
slow.

### 2. Beside it stand the newest, the lowest and the highest value

In the words the curve's own summary has them, with the readings that failed counted
after them. The line gives the shape and the numbers carry what a flat line hides. The
sparkline says nothing to a reader that hears the page; the words do.

### 3. The index draws one beside each label, in the row's fold

A row of the Series index still counts its curves, and the count still unfolds
([ADR-0103](0103-the-series-index-says-where-each-link-leads.md) decision 2): for
each curve to its label, its sparkline and its three values, each on a line of its
own, the values wrapping. So the strips stand in a column and a fold asks for no more
width than a strip: opening one does not widen the table past its box. The closed row
is as it was.

On a phone the index is no table to the eye. Eight columns are wider than that screen
whatever a fold does, and the column the folds stand in was out of sight; so below a
phone's width each row is a block of its own — its status and its node, and beneath the
node what keeps it, its fold, what it holds, its newest reading and where it leads,
each on a line that says what it is, since the headings are kept for a reader that
hears the page and are out of sight. Nothing is scrolled sideways.

A row has no one sparkline of
its own: a node's series draw several curves, and nothing a check declares says which
of them is the node's.

A node's own page has no sparkline. It draws in full every curve that stands on it
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 2), and the
curves beneath it are one click away, on the tab that counts them.

### 4. The Series tab carries the number of curves its view draws

Every curve that stands at or beneath the node — for the root, whose Series tab is the
index, every curve the instance has. No number where the view draws none. It is counted
by a curve's own rules and nothing is drawn for it, and it moves with what is declared
and what the tree holds, not with a reading's value, so a page that refreshes itself
does not show it flicker. History's tab has no number: the page itself says how many
readings it lists, and that number moves every minute.

## Consequences

- The index draws every curve of the instance when it is opened: on the device a day of
  seventeen series and sixty-eight curves costs about a fifth of a second and 174 KiB,
  nearly all of it reading each record for each measure. The page is not polled.
- [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 4 says what the
  index shows; this adds the drawing to it.
- `little_sister.curves.draw` takes `small`; it is not part of the surface a package
  may import.

## Alternatives considered

- **From the lowest reading to the highest.** Every strip is lively and none can be
  believed: in a tool whose reader is trained to take a line that moves for an alarm, a
  sparkline that exaggerates is worse than one that is dull.
- **From zero, and nothing beside it.** Honest, and a full disk that does not move
  tells a reader nothing; three numbers the drawing has anyway answer that.
- **One sparkline on the closed row.** It needs a main curve for each node, which no
  declaration names; picking the first would be a rule a reader has to learn.
- **A list of the curves beneath a node on its page, each seen small.** The index's
  fold again, a click from the view it copies, and drawn at every refresh of a page
  that refreshes itself.
- **A sparkline in each card of the wall.** A card is priced by the layout, so every
  card with a curve grows and the wall rearranges: a change to how the wall reads, to
  be weighed with the wall and not beside it.
- **The readings kept, on the Series tab or on both tabs.** A number that changes every
  minute in the head of every node's page, and one History's own page already says.
- **No number.** The quietest, and it loses what a count on a tab is for: knowing
  before the click whether anything is there.
