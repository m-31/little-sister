# ADR-0138 — A viewer may pack a level's boxes into its columns

- **Status:** Accepted
- **Date:** 2026-10-25
- **Related:** [ADR-0056](0056-stable-useful-dashboard-flow.md) (the rows, the
  stable-position rule, and the plan that lays the columns and each card's span),
  [ADR-0029](0029-per-user-presentation-preferences.md) (a look, the cookie that keeps
  it and a deployment's default),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (the tree, a
  run of chips, the refresh that keeps a viewer's folds and the window where it stood)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

ADR-0056 lays every grid of boxes in rows — the cards of a wall and of a node's page,
and the open boxes of a level inside a card — each row as tall as its tallest box, so
that a box stands where it stood whatever its lines say, and a refresh never moves it.
It set aside packing the boxes into their columns because a box's place would then
depend on live heights.

Rows cost room where one box stands far taller than the boxes beside it: their columns
stand empty beneath them down to the tall one's foot. On one deployment's team page,
`/status/<team>`, a failing check with one short line stood beside its GitHub check,
which reaches over two thousand pixels; at 1,280 pixels the checks after them waited
beneath GitHub's foot, the failing check's column empty beside it nearly to the page's
end, and at 2,560 the GitHub check's eight aspects stood in three columns 2,209 pixels
tall, where by the heights they were drawn at they pack into 1,055. The deployment's
wall at 2,560 read 2,778 pixels where packed it reads 2,647.

On Lex's word of 2026-10-25 the rows stay the library's — a wall that never moves is
what a glance at it needs — and a viewer who wants the room packs.

Packing as it was first built that day kept two things of the rows. The plan was the
rows', whose spans are a row's spare tracks, so a tall card was never given the tracks
beside it that let the short cards pack around it: on the same team page at 1,920
pixels the packed page stood 2,224 pixels tall, its GitHub check one track wide, where
two tracks for the check pack the page into 1,084. And a run of chips spanned every
column, as it spans the row in rows, so a card a click closed stood its chip — and
every box after it — beneath the level's longest column, the column it had stood in
empty above them (Lex's report the same day).

## Decision

### 1. A look, `boxes`: `rows`, the library's, or `packed`

ADR-0029's roster gains a look, `boxes`, offered in the settings menu after how a run
of chips is drawn, kept in the presentation cookie, and defaulted by a deployment in
`settings.yaml` as the other looks are. Under `rows` the page is drawn as ADR-0056
draws it.

### 2. Packed, each box stands beneath the shortest column

Every grid of open boxes keeps the columns and each card's span its plan gives it —
packed, the plan priced for packing (decision 5) — and `dashboard-layout.js` places each
box in the page's order beneath the shortest column — for a card that spans several,
beneath the shortest run of adjacent columns — the leftmost of the columns within 32
pixels of the shortest, a line of a box's lines and a little, so that boxes of about one
height keep their reading order; while a level's first row has an empty column, the next
box takes it. Every box stands in the grid's first row, in its column, with a top margin
as deep as the boxes above it in that column and the level's gap beneath each of them,
so that the row is as tall as the tallest column, to the pixel; a packed level carries
`.is-packed`. A run of chips stands in one column as a box does, its chips wrapping to
the column's width as they do in a narrow card (Lex's (a) on the runs, 2026-10-25), and
a level of a card lays its columns itself, equal ones: as many as fit and its boxes and
runs fill, where the stylesheet's auto-fit keeps every track a run spans and drops one a
click empties. A level of nothing but chips is no grid and keeps its one run across it.
A card's own levels are packed before the card is, since they make its height.

### 3. A node keeps its column until the page is drawn or its columns change

A box takes its column when the page is drawn — loaded, reloaded or reached — and when
its level's columns change, as a width brings them: the plan's band laying another count
of tracks, a card's span changing with it, a level of a card fitting another count of
its own. Otherwise it keeps it: a refresh, a click, *⌄ all N* and a box's lines growing
or shrinking restack the columns and move no box sideways. A node keeps its column as a
box and as a chip (his (i) on a chip a click opens): a card a click closes leaves its
chip where its box stood, the boxes beneath it in its column moving up; a chip a click
opens stands its box where the chip stood, the chips before it in their run above it and
the ones after it beneath it; and a run stands where the first of its nodes that stood
anywhere did, so that a card closed beside a run gathers with it where the first of them
stood. A box new to its level — one a refresh brought — takes the shortest column at its
turn, and a column a click empties stays where it stood, empty, until the page is drawn
again. A width that keeps a level's columns, as a scrollbar's does, keeps every box in
its column.

The page is drawn once `tree.js` has put the tab's map back (ADR-0127 decision 10), and
the boxes are packed then by the heights the map leaves them, whatever a frame before it
packed them by. A long wall paints while the parser is still on its way to the scripts,
and a first paint in rows would have the packing move every box beside a tall one, so
under `packed` the wall is hidden until it is drawn — with `visibility: hidden`, as a
tab whose map holds a fold hides it — and `tree-pending.js`'s one-second timer shows it
whatever happens, for a script that never ran.

### 4. No box stands over another, and the page's order is the source's

The browser says when a box changes size (a `ResizeObserver`), and its columns restack
before the frame is painted, the plan a new width selects laid first, since a level's
columns are what it lays; after a refresh `tree.js` has the boxes packed before it
puts the window back where it stood, and after a click before it scrolls the opened
box into view. The packing places the boxes and moves none of them in the page:
the keyboard, a screen reader, a find on the page and the Copy document follow the
page's order, and the tab's map is untouched. A level of one column — on a phone, in a
narrow card — is drawn as in rows.

### 5. Packed, the plan is priced for packing

Under `packed` the server prices ADR-0056's plan as the page will be packed (Lex's (a)
on the plan, 2026-10-25): every level of a card priced packed — each box beneath the
shortest of its columns, each run of chips in one of them at that column's width, the
level as many columns as fit and its boxes and runs fill — and at each count of tracks
the spans that pack the page shortest. From every card at one track, the useful step
that packs the page lowest, or as low with its columns filled least, is taken while one
improves it, exact ties staying with the earlier card; and where the rows' own plan
packs no taller it is the plan, so that a packed wall is never planned worse than the
rows' plan would pack it. The bands, the track floor and the count a band holds are
ADR-0056's, each candidate priced packed; the browser selects its band as before, and
under `rows` the plan is ADR-0056's. A tall card thus takes the tracks that shorten the
packed page, where the rows' plan leaves it one wherever its row has none to spare.

## Consequences

- **The page is shorter where a box stands far taller than its row-mates**: on the wall
  cost's harness (`tests/test_wall_cost_browser.py`'s cases, read under each look) the
  recorded wall at 1,920 pixels reads 1,998 where 2,318 in rows, 2,142 where 2,390 with
  every leaf failing, and at 2,560 1,952 where 2,270; a team's page at 1,024 pixels
  2,309 where 2,422, at 1,280 1,886 where 2,143, at 1,920 1,421 where 2,105 and at
  2,560 one screen where 1,786; its github check's page at 1,024 1,889 where 2,174, and
  an outage's page of workflow runs 3,449 where 3,758; the deployed wall at 1,280
  pixels 1,467 where 1,741 and at 1,920 1,019 where 1,703, its github card at 2,560
  pixels 612 tall where 1,066, the plan giving it half as much width again; the hosts
  wall at 2,560 one screen where 1,367. The recorded wall at 1,280 reads as in rows,
  the page of a hundred repositories 8,149 where 8,203, and on a phone, one column
  wide, every page as before.
- **Packed, a page can read taller than in rows where the plan's model misjudges a
  narrow card**: the hosts wall at 1,920 pixels reads 1,367 where 1,195 in rows. The
  plan gives its larger card four tracks of five and the smaller the fifth, 351 pixels
  wide, which the model — counting a box's lines by its budget and never by how its text
  wraps (ADR-0056) — prices one row taller than at 596 pixels, a third of the wall, and
  the browser draws 200 pixels taller, above the larger card's foot. Lex took the trade
  the same day (his (a) on the hosts wall): the look is a viewer's choice, and it reads
  lower on nearly every other page.
- **Packed, two viewers — or one page before and after a reload — may see the boxes
  arranged otherwise**: a box's column comes from the heights the page was drawn with.
  ADR-0056's stable position is the library's look's; under `packed` it holds between
  draws, which is what a viewer reading the page sees.
- **Packed, the wall is blank until its scripts have run**, where in rows it paints while
  the page is still arriving: on the demo's wall, in headless Chromium beside its server,
  the page's first paint came some 300 milliseconds after it was asked for, the wall in
  it in rows, and packed the wall came about 170 milliseconds after that, once
  `tree.js` had drawn it (medians of six loads each). A long wall over a slow line waits
  the longer, for the whole of the page and its scripts.
- **Between draws a box's growth moves only the boxes beneath it in its own columns**,
  where in rows it moves every column beneath its row; and a hole can open again as
  heights change while a page stays open, until it is drawn again.
- **Packed, a tall card takes the tracks beside it**, and the short cards pack around
  it, beside it or beneath it: where one card dwarfs the rest the plan may give it every
  track and stand the others beneath it — the browser tests' card of six boxes, one of
  them twenty lines tall, beside a card of one line takes both tracks at 1,000 pixels —
  and a wall changes plan at other widths than in rows.
- **The packed plan costs the server more**: on the harness's walls a shape's first plan
  took some 40 to 200 milliseconds packed where 30 to 100 in rows, and the memo serves
  it after that until the shape, the look or what the first look closes changes
  (ADR-0056).
- **A run of chips grows tall in its column**: a long run wraps to a column's width,
  where in rows it stands across the level, and the columns beside it fill around it.
- **A column a click empties stays empty until the page is drawn again**: a card
  closed into a run in another column, its own column holding nothing else, leaves the
  column blank rather than give its width to the others, which would move every box in
  them sideways.
- **A packed level reads down its columns where the keyboard walks the page's order**:
  the two differ where boxes were placed beside a tall one.
- **The browser's own masonry is not used**: `display: grid-lanes` ships in Safari 26.4
  alone, behind a flag in Chrome and Edge and in an older syntax in Firefox, and it would
  repack at every change of height.

## Alternatives considered

- **Repacking whenever a height changes** (Lex's (i)): the tightest page, and the one
  ADR-0056 set aside — a refresh that opens a failure or adds a line sends the boxes
  around it sideways while somebody reads them.
- **Repacking after a viewer's click too** (his (iii)): denser after clicking around,
  but a click moves boxes the viewer was not looking at.
- **Columns the server lays from the first look's priced heights**: no refresh could move
  a box, and the stacks would hold only while the boxes of a level stayed as the first
  look draws them, so the first click that closed one would lay the level again. The
  server prices the plan packed (decision 5); each box's column stays the browser's.
- **The rows' plan, packed**, as packing was first built: a tall card was never given
  the tracks beside it, the rows' spans being a row's spare tracks.
- **A run across every column**, as packing was first built: a card a click closed
  emptied its column above it, and its chip and every box after it stood beneath the
  level's longest column.
- **A run across as many columns as its chips need for one line** (his (b) on the
  runs): one closed card takes one column, as here, but a run longer than a column's
  line bars the level again.
- **A chip a click opens taking the shortest column at its turn** (his (ii) on opening),
  as a box new to its level does: the box may open in a column other than the one
  clicked, and the chips after it start a run of their own elsewhere.
- **The stylesheet's columns for a packed level**: auto-fit keeps every track a run
  spans and drops one a click empties, so the columns beside it widen and every box in
  them moves sideways.
- **CSS columns**: the page's order flows down each column, and the browser balances the
  columns by live heights at every change.
- **Rows of four pixels, each box spanning as many as its height**, as the look was first
  built: every box's height and gap rounded up to the rows gathered down a column — on
  the recorded tree's page of a hundred repositories, whose boxes rows already stand
  well, 102 pixels taller than in rows — and a browser holds a grid to so many lines,
  Firefox to ten thousand.
- **The rows' plan wherever the packed one narrows a card** (his (b) on the hosts
  wall): the hosts wall at 1,920 pixels as in rows, but the wins at 2,560 — a team's
  page, the deployed wall and the hosts wall — narrow their small cards too, and
  would go with it.
- **A model that sees a box's text wrap** (his (c)): the one way to price a narrowed
  card truly, against ADR-0056's rule that only the tree's stable facts are priced,
  never rendered text.
- **Rows alone**, with this trade written into ADR-0056: kept as the library's look,
  and offered beside this one.
