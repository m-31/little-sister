# ADR-0098 — A Series view is drawn over the window its URL names

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-10-03)
- **Related:** [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (the Series
  view; decision 1 amended), [ADR-0092](0092-a-check-declares-its-measures.md) (a curve
  drawn on the server, with no script of its own; decision 5, its breaks),
  [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) (decision 4, a failed
  reading's mark), [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision 7,
  the configured timezone and time format), [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md)
  (the Events page, which reads the same window with the same bar),
  [ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) (decision 4, decision 5's
  counterpart for a series of runs)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A Series view draws everything a series keeps on one time axis, labeled at its two ends.
A day of readings at two minutes is 720 of them across a plot 672 units wide: a moment
in the middle of the day is estimated rather than read, the strip a reading owns under
the pointer is narrower than a pixel, and the page carries every reading. Nothing on the
page moves, so it reads as static. Longer series are coming — readings reduced into
buckets from a day to years — and there, drawing every reading is not an option at all.

The view is drawn on the server, as every curve is, and a way into a stretch of it has
to be too: a link somebody can bookmark or hand on, which a page without its script
still follows.

Walked once it was built, the view hid how it moved. A band followed the pointer across
every plot, the look of a crosshair one drags out, and a drag selected the value axis's
labels as text instead, while the way into a stretch — the time axis between two labels
— showed nothing until hovered and repeated on every curve. The presets and the moves
were a line of small links that came and went with the window, the window was named only
in a sentence above them, and a move that reached now froze the window where it was.

## Decision

### 1. The window is written as `from` and `to`, as Grafana writes it

`/series/<path>?from=…&to=…`. Each is `now`; `now-` and a duration in the family's
units — `15m`, `6h`, `1d`, `1w`; or an ISO 8601 instant, one without an offset read in
the configured timezone. `to` is `now` where it is left out, and a view without `from`
shows everything kept, as it did. `now` is the server's clock when the page is drawn, so
a bookmark of `?from=now-6h` is always the last six hours, while a stretch in the past
is two instants. A value the server cannot read, or a `from` not before its `to`, is
answered `400`, naming the parameter and what it takes. An instant the page writes into
a link is in UTC, with a `Z`.

### 2. The window is the Series view's, and the Events page's

Every curve on the view is drawn over the window, and which curves stand there is decided
by everything kept: a curve with no reading inside the window keeps its place and says
so, and the page holds still as it is zoomed and moved. The axis is the window as
written, not trimmed to the readings inside it, so a series that stopped reporting ends
before the right edge and two windows of one length compare. The bar that names the
window and the tables of readings follow it — a table holds the newest `reading_cap`
readings inside the window. The breadcrumb's Series crumbs carry the window;
the Status and History tabs, the index and a node's page do not take one. The Events
page reads the same `from` and `to` over its log (ADR-0101 decision 4).

### 3. One bar names the window and moves it; the time axis is the way into a stretch

A bar above the curves, in view while the page scrolls, names the window to the minute
in the configured timezone, with the zone as its clock names it: `Last 6 hours ·
2026-10-03 14:45 – 20:45 CEST` for a window back from now, *Everything kept* and its
ends for a view without one, and the two ends alone otherwise — each with its zone
where the clock changed between them. Beside it are one group of presets — 1h, 6h,
12h, 1d, 1w, 30d, 1y and 7y, offered up to the first that reaches back past the oldest
reading the view's series keep, and *all kept* — with the current one marked, and the
four moves, each in its place whether or not it applies. *Earlier* and *later* move the
window by half its length, *zoom out* doubles it around its middle, and *now* moves it
to end now, its length kept. A move that does not apply is shown disabled: *earlier*
once the window starts at or before the oldest reading kept, *zoom out* once it holds
every reading kept, *later* and *now* once it ends now or after, and all four over
everything kept. The Events page draws the same bar above its log, measured against the
oldest and newest event kept, and each of its links keeps the page's filters (ADR-0101
decision 4).

A window that ends now stays live: a preset writes it as `now-` and a duration, and so
do *now* and a zoom out or a *later* that reaches now, the length to the minute; the
preset of that length is marked. Every other window is written as two instants, a
stretch chosen on the time axis included, the newest one too: what one chose to look at
holds still, and *later* or *now* go back to live. The clock the page read the window
by is the one every control measures against.

Every stretch of a curve's time axis between two of its labels, and from an end to the
label nearest it, is a link to the view over that stretch, which returns to the curve it
was chosen on. The axis is drawn as a track divided at its labels, and the pointer over
a stretch is a zoom. Each curve's stretches are the same links, so the first curve's are
in the tab order and the others are for the pointer alone. Without the view's script
nothing follows the pointer across a plot; with it, a drag chooses a stretch and one
line reads every curve at one instant (decision 6). Every control that applies is a
link the server draws.

### 4. Time labels fall on round times in the configured timezone

The step is the smallest of 1m, 2m, 5m, 15m, 30m, 1h, 3h, 6h, 12h, 1d, 2d, 1w, a month, a
quarter, a year, two years and five years that puts at most six labels on the axis. They
fall on round local times — the hour, midnight, a Monday, the first of a month, New Year
— stepped in local time, so a day with 23 or 25 hours is labeled as the clock read it.
A label is written in the ISO style of the family's time format and as short as its step
allows: `14:00` within a day, the date — `09-30` — at a midnight and for days, `2026-09`
for months and `2026` for years. The window's ends are named in the bar above the
curves and, to the second, in each curve's accessible name; where no round time falls
between them, the axis names the two ends, as it did. The time axis is a drawing of
its own beneath the plot, so that its stretches can be links while the plot stays one
picture.

### 5. A window with more readings than a plot has columns is drawn column by column

A curve's plot is 336 columns, two units each. Where a window holds more readings than
that, each column draws its first, last, lowest and highest reading, so the line looks
as the line drawn through every reading would and no spike is lost; a column's strip
under the pointer names the range, the count and the times — *38–47 % over 6 readings,
14:02–14:12*. A stretch without readings breaks the line where it is at least a column
wide, and a column holding a reading that failed carries its mark. What a curve's summary
counts — the newest, lowest and highest value, the readings that failed, the stretches
without readings — is counted over every reading in the window, at any zoom. A window
with no more readings than columns is drawn reading by reading, as before. This is the
rule for gauges read at a steady rate.

The rule's counterpart for a series of runs is
[ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) decision 4: every run is drawn at
its own instant and its own value and nothing is merged into a column, a passing run's
head giving way where heads would run into each other. A column's strip, the lane's one
mark for a column and a summary counted over every run hold as they do for a gauge.

### 6. A drag chooses a stretch, and one line reads every curve at one instant

The view carries a script over its links, and every link works without it. With a
mouse or a pen, a drag across a curve's plot or its time axis marks the stretch on
every curve of the view, its two ends written beneath the curve dragged — to the
minute over a window of an hour or more, to the second under one — and, let go, opens
the view over it: two instants rounded the same way, the link a stretch of the axis
would be, returning to that curve. A drag shorter than a few pixels is a click, and
Escape lets a drag go. Where the pointer rests on a plot, one line crosses every curve
at the same instant, and each curve's summary says what its strip there says — a
reading's time and value, or a column's range, count and times — until the pointer
leaves; the strips' own tooltips give way to it. A preset or a move from the bar
returns the reader to the group the view was scrolled to. Touch keeps the page
scrolling and its links as they are. Nothing on a plot or its axis is selected as
text or picked up as a link, with the script or without it.

## Consequences

- **ADR-0097 decision 1 is amended**: its one time axis is the window where the URL names
  one.
- **A bucket keeps what this drawing needs.** A store that reduces readings into buckets
  keeps each bucket's first, last, lowest and highest value and its count — and a sum
  beside them, for a mean — so a window drawn from buckets keeps every spike. An average
  alone would smooth them away.
- **A measure's kind is open** — a gauge drawn by column, a latency-like measure drawn as
  percentiles, which merge only through a histogram kept with each bucket, and an event
  drawn as a mark per reading — with what each kind's buckets keep. They are decided
  with the stores that reduce readings into buckets, before any reading is dropped.
- **The view's URL is a contract**: `from` and `to` are read as written here, by a
  bookmark as by a link the page made.
- **Today's day-long views are drawn by column** — 720 readings at two minutes are more
  than 336 columns — which makes the heaviest of them, a Mac host's eleven curves, a
  third lighter; a single reading is reached by zooming in. A view without a window
  shows everything kept, as it did.
- **A script, over links that work without it**: a drag writes the `from` and `to` a
  link does, so a page without the script loses the gesture, not the way. The family's
  durations have no `y`, so a year is written `365d`: the presets *1y* and *7y* are
  `now-365d` and `now-2555d`.

## Alternatives considered

- **`?last=6h` alone** could not write a stretch in the past, so neither moving nor
  zooming into one; **absolute instants only** would freeze a bookmarked preset into a
  fixed past window; **the window in the path** collides with node names, as ADR-0097
  found for a view's name.
- **The window reaching the History page, or a node's page** — History is about
  everything, and a node's page is about now and polled; both link to the view.
- **Presets alone** leave a stretch in the past to a typed URL; **a link per reading** is
  precise but some half a megabyte and thousands of tab stops on a host's view; **a form
  of two instants** is precise and clumsy to explore with, and can come beside the links.
- **A stretch chosen at the newest end that stays live** — growing from where it starts,
  or sliding as `now-` and its length — was weighed with Lex: the first is a third kind
  of window every move would need a rule for, the second drifts off the stretch chosen.
  A chosen stretch holds still, as a drag does in Grafana. **Moves that come and go**
  shifted the bar under the pointer, and a *later* offered seconds before now moved the
  window by those seconds; **the window named only in a sentence** was not where its
  controls were.
- **A charting library drawing in the browser** would ship the readings as data and
  keep a second drawing true beside the server's; **a tooltip beside the pointer**
  covers what it reads and reads one curve at a time; **the stretch marked on the curve
  dragged alone** hides what it holds on the others; **a drag by touch** takes the
  page's scroll away on a phone, where the links do the same.
- **Evenly spaced labels** land on times nobody reads, like `13:47:12`; **short formats
  derived from `time_format`** would guess at an arbitrary format string.
- **A column per plot unit** doubles the weight for a plot rarely drawn that wide;
  **aggregating only from three readings a column** keeps strips too narrow to use;
  **LTTB** may drop an extreme; **a mean line in a min/max band** is heavier to draw and
  to read; **averages** smooth the spikes away; **a sample of readings** misses the
  extremes unless it keeps them on purpose, and estimates a tail badly.
