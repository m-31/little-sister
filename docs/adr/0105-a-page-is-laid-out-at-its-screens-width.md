# ADR-0105 — A page is laid out at its screen's width, and is no wider

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md) (a
  readings table's own box), [ADR-0103](0103-the-series-index-says-where-each-link-leads.md)
  (the Series index's table, the first to scroll inside its card),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (the band, its trail and
  its tabs), [ADR-0029](0029-per-user-presentation-preferences.md) (the three layouts),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the poll),
  [ADR-0056](0056-stable-useful-dashboard-flow.md) (layout claims a browser has to hold)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

No document declared its viewport. A phone therefore laid every page out at its
980-pixel fallback and scaled that to its screen — the wall as a desk shows it, at two
fifths the size — and none of the narrow layouts was ever reached on one. The browser
tests that held a page to *a phone's width* set a narrow window, which a desktop browser
lays out at that width whatever the document says, so they never met the difference.

At a phone's width, once declared, pages were wider than the screen, and a page wider
than its screen scrolls sideways as a whole, its bar and its rail with it. The band's
four filters stood in a row that could not wrap. The tables of Events, of History and of
both System views were as wide as their rows. The trail in a node's band was kept on one
line, so every page of a node four levels down was as wide as its path. And a name or a
word with nowhere to break — `backup_of_the_primary_cluster`, a digest, a login name —
was as wide as itself on a card of the wall, in a pin's sentence and in the Copy page's
heading; on the wall that reached a desk too, where such a name ran out of its card. The
Series index had lost the same defect in ADR-0103's build, where its table scrolls
inside its card.

## Decision

### 1. Every document declares its viewport

`<meta name="viewport" content="width=device-width, initial-scale=1">`: the device's own
width, at its own scale. The shared head says it for every page that takes it, and the
two documents that stand before there is a session to build a head from say it
themselves. Nothing is said about zooming, which stays the reader's.

### 2. No page is wider than its screen

What can be wider than a screen keeps a box of its own that scrolls it sideways — a
table, a drawing, a block of code — and everything else gives way: it wraps, or it
breaks. The bar and the rail then stay where they are while a table is read to its last
column.

### 3. A table stands in a box

Every table of every template stands in a box that scrolls it: Bootstrap's
`.table-responsive`, or one of the two a table already had — a readings table's, which
scrolls both ways (ADR-0102), and the one around the formats an expiry field takes. A
`.table-responsive` box is `position-relative`, so that what is placed absolutely inside
it — a visually hidden heading — is placed in the box and cannot widen the page from
within; and it carries the outer margin its table had, since a box that scrolls is a
formatting context of its own and a margin kept inside it would no longer collapse with
what follows.

A table wider than its box gives every column its narrowest, and a reason's narrowest is
its longest word: a column of single words, in rows a screen tall. On a phone a reason
therefore keeps 16rem, a line's worth and most of the screen's. Not on a desk, where a
table shares its width out by what its columns hold and a floor under one of them would
move the others.

### 4. The band gives way before the page does

The filters take a second line beneath the stamp, which on a phone has nothing beside it
to be ruled off from. The trail keeps one line while the band has the room, and takes as
many as it needs where it has not: each ends in its slash — the space before a slash
does not break, the one after it does — and a name wider than a line breaks inside
itself. The node's title takes what the trail leaves of its line and is cut short there,
as it was; it takes the next line where the trail leaves nothing, and on a phone where
it leaves less room than a word needs, and has all of that line. Above the wall's cards,
the strip takes the line beneath the count of pins where the two do not fit one,
instead of pushing the count out of its column.

### 5. A word with nowhere to break breaks where it must

A card's name on the wall, at every depth; a pin's sentence and the record beneath it,
which carry a line's own words, a path and a login name; the path in the Copy page's
heading: each breaks inside a word that is wider than its line, and only there. Inside a
table nothing does: breaking a value anywhere folds a column into single characters
before its box ever scrolls (ADR-0102).

### 6. A box keeps its place over a poll

System's schedule is fetched again every ten seconds, box and all, and a new box stands
at its left edge. `poll.js` puts each `.table-responsive` box of the part it swaps where
the one before it stood, so that somebody reading the right-hand columns stays at them.

### 7. A phone is emulated, and every page is measured on it

`tests/test_phone_browser.py` reads each page off Chromium emulating a phone — a touch
device with a phone's user agent, which is what makes a browser treat the declaration as
a phone does — at 390 pixels and at 360, in the three layouts, over an estate that holds
a deep path, a name and a word with nowhere to break, long reasons, and a pin on each.
The page has to be laid out at the screen's width, at its own scale, and nothing in it
may reach past the screen outside a box of its own. `tests/test_phone_layout.py` holds
in the gate what a response can show: the declaration in every document, a box around
every table of every template, and that no rule keeps the band's parts on one line.

### 8. On a phone the rail gives way to the top bar

Below 576 pixels — the width the page's other phone layouts begin at — a viewer whose
layout is the rail gets the top bar's as it is at that width: no rail, the bar's
sections folded behind its toggler, the page at the screen's whole width. The rail's 52
pixels are a seventh of such a screen, kept for good. The preference is not touched:
the settings menu still says *left rail*, and the rail stands again from 576 pixels,
where it costs little and a section is one tap away. It is the stylesheet's doing
alone; the server emits one markup for both layouts, as before.

## Consequences

- **A desk reads as it did.** Over an estate without such words, nothing on a page moves
  at 1,024 pixels and wider. Where a page was wider than a desk's window it no longer
  is: a name that ran out of its card breaks inside it, the trail of a deep path wraps
  in a leaf's column, and a table of long reasons scrolls in its box.
- **A new table needs its box**, or the gate refuses the template.
- **A long reason on a phone is read by scrolling its table.** Its row is as tall as the
  reason set at 16rem, and the reason stands off to the right of the times beside it.
  A table that reflows on a phone is a layout of its own, and not decided here.
- **320 pixels is held**, in the rail layout too: on such a screen it is the top
  bar's (decision 8), which fits a card's state line — a time, a cue and a word, kept
  whole as one fact. The rail with its labels opened takes 192 pixels beside the page;
  from 576 pixels a viewer who opens it has what is left.
- **A title in the instance's pill has more room on a phone**: the page is 52 pixels
  wider there, so a title that stepped out at 375 pixels may stand.
- **Nothing moves on the API**, and no stored state changes.

## Alternatives considered

- **The rail kept on a phone**: a section is always one tap away, and every page pays
  52 pixels of 375 for it.
- **The rail opened over the page from a burger in the bar**: the page gets its width,
  and a second navigation for a phone stands beside the bar's folded one, which works
  and is tested there.
- **The rail gone wherever the bar folds, below 992 pixels, or below 768**: one line
  for both layouts, and a tablet and a half-width window lose a rail that fits them.
- **`overflow-x: hidden` on the page**: no page scrolls sideways, and what was wider is
  cut off out of reach.
- **Rows that reflow into blocks on a phone**, a reason beneath its times: the better
  reading of Events and History there, and a layout to design for each table; a box is
  what every table can have at once.
- **The trail cut short, or scrolling in a box of its own**: its end is the node's own
  name, which the page is about. **Its head folded** to *… / production /
  informational-findings*: needs a script to know how much fits.
- **Every word breaking wherever it must, set once on the page**: a table then folds its
  columns before it scrolls (decision 5), so the rule is said where a name is printed.
- **`maximum-scale=1` beside the declaration**: takes zooming from a reader who needs
  it.
- **A narrower window in the tests**: what they did, and how a page laid out 980 pixels
  wide on every phone passed them.

