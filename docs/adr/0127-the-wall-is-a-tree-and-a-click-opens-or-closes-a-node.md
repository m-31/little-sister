# ADR-0127 — The wall is a tree: a node is closed or open, and a click changes which

- **Status:** Accepted
- **Date:** 2026-10-11
- **Related:** [ADR-0056](0056-stable-useful-dashboard-flow.md) (dense mode, its
  `branch_cap` and the band's depth and chips controls, which this retires; the flow
  model, which prices the first look),
  [ADR-0128](0128-where-a-nodes-first-look-comes-from.md) (how each node starts, which
  this record leaves to it), [ADR-0063](0063-declining-the-density-trade.md) (the one
  exception a single child claims), [ADR-0019](0019-inspection-popover.md) (the
  inspection card: when it opens, what it says, and that a refresh keeps it),
  [ADR-0029](0029-per-user-presentation-preferences.md) (the presentation cookie, which
  gains the chip runs' look; what a viewer opens stays out of it),
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (decision 11, a node's
  actions, now in the head's row), [ADR-0038](0038-declarative-action-list.md) and
  [ADR-0076](0076-the-instance-node-is-a-branch.md) (the actions a head draws, with an
  icon and without), [ADR-0044](0044-run-facts-on-the-node.md) (decision 8, a page's own
  facts, which stand after its children as it decided),
  [ADR-0012](0012-node-metadata.md) (a node's `about`, shown open on its page, and
  decision 4's startup pass), [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md)
  (a pin's block and its setter), [ADR-0041](0041-maintenance-is-a-contribution-rule.md)
  (a pin silences and keeps the colors beneath it), [ADR-0017](0017-node-title.md) and
  [ADR-0061](0061-decoration-is-not-a-label.md) (where a title is drawn; a chip no
  longer draws one), [ADR-0055](0055-sibling-order.md) (a level's declared order),
  [ADR-0114](0114-a-curve-seen-small-and-the-series-tabs-count.md) (decision 3, the
  curves a node's page draws, in full as before),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the ten-second refresh),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope, untouched)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The wall's density was one switch for the page (ADR-0056). With *chips* on, the
default, a quiet descendant leaf was painted as a chip, its name and its state; a warn
or error leaf stayed a box with its reason; and at every level `branch_cap` folded the
quiet boxes past its count behind *+N more*. The band also carried a depth control,
and both lived in year-long cookies beside *hide ok* and *hide idle*. What a viewer
could unfold for one node was that *+N more* and a box's reason chevron, each held in a
set for the page's life and gone with a reload. The deployment had one word per node,
`show_when_quiet` (ADR-0063), and that record refused the viewer one on purpose.

What was asked was the viewer's own word, per node. Chips should be toggled per node in
the GUI, not for the whole page; a viewer should unfold a node, expand it or fold it to
a chip by a click on that node; a branch should open with or without its children that
are ok; whatever a viewer opened must survive the ten-second refresh, or the page turns
under the hand; and a node or a branch should say how it starts. The last is
[ADR-0128](0128-where-a-nodes-first-look-comes-from.md)'s. The need grows with the
tree: a subject given a node of its own adds, on one deployment, 158 nodes, nearly all
quiet.

A per-node density switch would have kept two vocabularies, a chip and a box for what
density does and a fold for what the viewer does. The round turned the question around
instead: one element, everywhere, which is either small or not. It was tried on one
deployment's own tree of 265 nodes, anonymized, in a prototype that runs ADR-0056's
flow model, in screens of 900 pixels: as configured, the two failures of that day
opening their way, its wall is 3.4 screens on a desk where today's is 4.0, and with
every leaf failing 3.5 where today's is 12.0.

## Decision

### 1. Every node is closed or open, and a click on it changes which

A closed node is a **chip**; an open node is a **box**, a card at the top of the wall:
its head, its pin's block where one stands, its lines, and its children, each closed or
open in turn. A click on a chip opens it in place, and a click on an open node's head
closes it again. It holds at every level, down to a leaf, whose lines are what opening
it shows, and an open node is a box at every level, its border and its tint saying where
it begins.

A closed node at the top of the wall stays a card in its place, closed to one line, its
head and its counts, so a click never moves another card sideways, and closing every
card turns the wall into a one-line overview laid out as the open one. A box keeps
today's colors: a failing leaf is vivid, and a branch takes the pale tint of what rolls
up into it. A closed node that fails is a vivid chip, red for an error and yellow for a
warning, a branch's as a leaf's, so it stands out on the pale tint of the box it sits
in; a maintenance or an idle chip keeps its tint. Closing never turns red into green; it
only makes it small.

A level keeps its order (ADR-0055) whichever of its children are open: consecutive
closed children form a run of chips (decision 12), and an open child stands in its
place between runs, as dense mode drew a quiet leaf's chip among boxes. A click opens a
chip where it stands, splitting its run, and closing it puts the chip back, so nothing
changes its place because its status changed, and the failures a budget opens stand
where their names put them.

### 2. A chip says its state, its name and what it counts

A chip is the cue of its state, its name, and what is beneath it counted: each leaf by
what it counts for itself, a stale leaf as warn, a pinned one as ‖, an idle one as ○,
and each branch that fails for itself, the chip's own node among them, by what it counts
for itself. A branch whose own reading failed above healthy leaves so reads ● 1 beside
their ✓, where counting the leaves alone drew it red over nothing red. Where everything
a chip counts shares one state, it shows one total and no glyph, muted unless the chip
fails; where states mix, each state's glyph and count — *● 2 ▲ 1 ‖ 1 ✓ 119*. The counts
explain the chip's color and add up the same way at every level. A leaf's chip counts
its lines the same way, and a leaf of one line shows no count: its chip is that line. A
‖ stands on a chip where a rule stands beneath it. A stale leaf's own chip is drawn as
the warning it counts as. The counts are said in words as the chip's tooltip and in its
accessible name — *2 errors, 1 warning, 119 ok* — a damped count with how near it is to
escalating and a running line among them, and a bare ‖ says that a rule stands beneath;
there is no legend, and every open head pairs its cue with its word. A chip counts what
is beneath it before *hide ok* and *hide idle* drop what they hide, so a filter changes
what the page shows and never what a chip says.

A chip carries no title. Measured on one deployment's own tree, 162 of the 255 chips in
its runs had one, and 70 said something the name does not — a workflow's display name
beside its file, a GitHub aspect's beside its key; the rest repeated the name or were a
severity glyph. In an aligned run (decision 12) the long titles would have been cut, and
in the compact view they made the runs 13 to 25 % taller. A node's title is in its head
once it is open, and in the inspection card (ADR-0019).

### 3. An open node's head carries its page, its two folds and its rule, in its own row

In this order: ↗, the node's page; its healthy fold (decision 4), a funnel, pressed
while the node's healthy ones are folded — pressed is the compact look for both buttons
— with its count in its tooltip and accessible name, and not ✓, which stays the cue of
an ok state and the ok count; ▤, its children as chips (decision 5); for an admin, ‖,
which opens a pin's editor in the node's box (ADR-0104) — the page's one editor, kept
outside the grid the refresh swaps and cloned where it is asked for, never one drawn
into every head; and before them all, the node's actions, which a deployment's
`node.actions` slot fills (ADR-0034). The head's own are small square icons that hold
its upper right corner and look the same on every head, after its state word where the
state shares their row, on every open head but the kiosk's and always shown, drawn from
the ink of the surface they stand on, as the rule buttons and action chips are, so that
they hold in every theme (ADR-0028): at rest an edge of the ink at 75 % around a glyph
in the full ink, the glyph what says *button* and the edge its square; pressed, the full
ink as the edge and a wash of it; ▤ half washed while some of the node's children are
open and some closed; and a dot of the ink on a button the viewer set differently from
the configured look. A glyph is drawn at 16 of its square's 24 pixels, so that the eye
finds the symbol, not the margin. Under a coarse pointer the squares stand 8 pixels
apart, where a mouse keeps 3, each one's tap area reaching to the middle of the gap, 32
pixels wide and never over the state word; the row loses no height. The fold stands wherever the node
has a healthy child or line, whether others stand beside them or not, ▤ where it has
children, and ↗ on every open head but that of a page's own node. The row never wraps:
the title gives way first, then the node's actions fold behind ⋯ (below), and only then
the name. The kiosk draws none of them, as it draws no pin control and no slot: ↗ would
take it to a node's page, a leaf's not refreshed and a branch's holding the kiosk there,
and the folds have nobody to set them.

A node's actions stand before the head's own, and before its state where the state
shares the row, shown always. An action that names an icon (ADR-0038) is a square of the
same shape, the icon alone, its label its tooltip and accessible name; one that names
none, as the self-report buttons do not (ADR-0076), keeps its label as a small chip,
since a letter in a square would be a guess on a touch screen. The title gives way to
them, and actions that do not fit even with the title gone fold, from the last, behind
a ⋯ at the end of their rail, before the state and the icons, whose menu lists them by
their labels, so that no action cuts the name and none moves to a line beneath; nothing
is laid over the title, so on a phone nothing covers the name. ⋯ never holds one action
alone where the state's own line beneath keeps it in the row: a menu of one item puts
the action behind an unlabeled button and a second click. Under `card_status_line:
below` the icons and actions stay on the first line with the name and the state alone
takes the standing line; in the default the state drops to a line of its own only where
the name would otherwise be cut or a lone action fold. A name breaks where its words meet,
after an underscore, a dot or a hyphen, and inside a word only where one is longer than
its line. Where the name breaks onto a second line
anyway, the state stands on that line, beneath the icons, rather than on a third of its
own — unless it would touch the name's words or the icons there. A chip carries none of
them; it is opened first.

### 4. The healthy fold folds what counts ok for itself

On an open node, the healthy fold shows or folds its **healthy** children and lines.
Folded, they are one count after the rest — *✓ +116 ok* — which opens them again. A node
is healthy when its code is `OK`, nothing beneath it is stale and no pin is on it or
beneath it; a line when its own code is `OK`, or, having none, when the code its node
rolls up to is, and no pin covers it, so a branch's own line stays while anything
beneath the branch fails, as the branch itself does. So the fold folds exactly what the
roll-up counts as ok, and *+N ok* means what it says. Everything else always stays —
warn, error, idle, maintenance, and a stale node, which counts at least warn for itself,
so a check that stopped running is never folded out of sight. It is per node and does
not cascade. A node that claims `show_when_quiet`, and its quiet lines, stay out of a
fold the configuration sets and fold with one the viewer presses (decision 5).

### 5. ▤ sets the children, and two kinds of child open regardless

On an open node with children, ▤ is one state button: pressed, its children are chips;
released, they are all open; mixed while some are open and some closed, by a click, the
failure budget or `show_when_quiet`. A click on it pressed opens every child, and
released or mixed folds every child to a chip, the likely wish where one child stands
open among a hundred. Pressing it sets every child, and a click on one child afterwards
changes that child alone.

A child that claims `show_when_quiet` (ADR-0063) starts open whatever its parent's ▤
says, and no fold the configuration sets, its parent's or its own, hides it or its quiet
lines. A press is the viewer's word over the claim: ▤ pressed closes it with its
siblings, a funnel the viewer presses on its parent folds it with the other healthy
children, open or closed, and its own funnel, pressed, folds its quiet lines.

A failure has a budget. A failure is a node that fails for itself, a branch whose own
reading failed as well as a failing leaf, each by what it counts for itself; a node a
damping counter still holds back from its parent is none until it escalates, since a
first glance shows why a card has its colour and a damped node is not why. In each
top-level card the first three failures that chips hide, errors before warnings and in
the card's order, open their way: the failing node and every node on its path, so its
reason shows without a click, while its healthy siblings stay chips. Every other failing
node stays a red chip with its count. The budget holds the wall's shape in an outage — a
card grows by at most three paths, each ending in a reason block the line budget clamps
— and a viewer's click wins over it both ways, as over every default, a close holding
for its node's incident (decision 9).

### 6. The folds replace `branch_cap`; `reason_cap` stays

Chips and the healthy fold are the folds. `branch_cap` and its *+N more* go with dense
mode, whose rule they were: a level a type expects to be big starts as chips, its
healthy ones folded, and a click that asks to open everything opens everything.
`reason_cap` stays the line budget of an open box, and within it a box shows its failing
lines first — errors, then warnings, then the rest, each in its check's order — so the
reason for its colour is never what the budget clips; a pinned line stays among the
rest. Beneath the lines, while they overflow the budget, *⌄ all N* shows them all, N
their total, and *⌃ less* folds them again; the head keeps no seat for it. The budget
clamps every box below a page's own node, the
cards of a node's page as the wall's, and each shows its failing lines first; only the
page's own node — its own lines in its head, a leaf's own page — and the Copy documents
are never clamped, the healthy fold theirs, and they keep the check's order.

### 7. The band keeps its filters and loses depth and the chips switch

*hide ok* and *hide idle* stay filters: the server drops what they hide, the address and
the cookie carry them, and every fold works inside what they leave. The depth control
goes — opening a node is its depth — and so does the chips switch, since a closed node
is the chip; their cookies are no longer read. The band gains three buttons that set
every node at once: *Close all*, *As configured* and *Open all*, the last also showing
the healthy. *Close all* closes everything the configuration and the failure budget
opened, and keeps every node the viewer opened with the nodes above it; under it nothing
opens by itself, so a wall that changes under the hand goes still on the viewer's own
path in one click, and *As configured* then *Close all* closes everything. A `depth=` in
a kept address or a kiosk's bookmark closes every node at that level as the tab starts,
the viewer's word like the three buttons, so a failure past it is still a red chip and
still opens within its card's budget; *As configured* clears it. `depth=0` closes the
page's node itself, which on the wall is the one card that rolls the whole tree up, as
before. The three are drawn as the head's buttons are (decision 3), from the band's ink:
at rest an edge of it at 75 % around a label in the full ink, and the button in force
pressed, the full ink as its edge and a wash of it, since under *Close all* nothing
opens by itself and an operator has to see why a new failure stayed a chip. On it stands
the count of what the viewer set in the tab, the nodes its map holds and a `depth=`, and
a click on it drops what it counts: *As configured · 3* resets, and *Close all · 2*
closes everything in one click.

### 8. A node's page is the same tree, framed, its facts after it

↗ opens `/status/<path>`: the same tree, rooted at that node. The node is always open
and framed with everything that is part of it — its head as the frame's top, the pins
above it stated (ADR-0104 decision 2), its children inside. It opens its node's
children as it arrives and leaves everything deeper as configured; that is the page's
default and nothing remembers it, so a page fills in only what the viewer has not said.
One state serves the wall and every page of the tab (decision 9): a click on a page
carries to the wall and back.

The node's own facts (ADR-0044 decision 8) stand where that record put them, after the
children: Time, Measured, the curve, Report and Configuration, one above another, every
card open, as before. The page is read from the top — the head says what the node shows,
the children why — and the detail follows whole, where a long report above the children
would push away what the reader came for, and folded it was a click on every page.

The node's `about` (ADR-0012) is shown open in the band, beneath its name and title, on
every view of the node, where it was folded behind a line, so that what a node is needs
no click. It is the short account of the node, and the startup consistency pass notes
one past about 400 characters. What a team writes at length about a node — where it
stands, who answers for it, its runbook, its dashboards — is to be a field of its own on
a tab of the page, a decision of its own.

### 9. What a viewer opens holds for the tab, and only where it differs

What a viewer opened, closed, folded, pressed and expanded is a map by node path in the
tab's `sessionStorage`. It survives a reload — the one the refresh makes by itself when
a release changes the page's files among them — and every move between the wall and a
node's page. It ends with the tab: a link opened in a new tab starts as configured,
nothing is written to a cookie or the server, and *As configured* empties it.

It holds only what differs. A click that brings a node back to how the view would show
it on its own — its first look on the wall, the page's rule on a page, a failure its
budget opens, and what *Close all* or *Open all* draws while it is in force — removes
the node's entry, so a page's rule and a configuration changed under an open tab reach
that node again. Pressing ▤ removes the children's entries, and a child that would not
follow the button on its own — one that claims `show_when_quiet`, or a failure its
budget opens — gets one, so that it follows too. A funnel the viewer presses stays its
node's entry wherever it folds more than the configured fold, as it does where a claim
stands beneath it or on its node. An entry outlives its node until the tab ends, so a
child a run names gets its look back when it returns. What the map holds is of the view
and not of the node. *Close all* and *Open all* are the tab's, for the wall and every
page of it, a page that regroups a branch among them; and a view kept by name, if one is
wanted, would be such a map saved whole, the button in force with it.

A close holds for its node's incident. Once the tab has seen the node out of failure —
drawn neither as an error nor as a warning, whatever pins stand beneath it — for six
hundred seconds by the server's clock, a render at their end still drawing it so — the
hold the engine's own lines use against a flicker — its next failure gives the close
way, and the node opens as its look and the failure budget say; a failure sooner is a
flicker, the close holds and the count starts again. The time is the one each render
carries, never the browser's clock or a count of refreshes, since a hidden tab is
throttled, and a tab that saw no render out of failure keeps the close. An open never
gives way to a status change.

On the kiosk the map lives in the page's memory and never in `sessionStorage`: the kiosk
has no band and so no *As configured*, and its tab stays open for months. Five minutes
without input empty it, so the kiosk returns to its first look by itself; one nobody
touches never notices.

### 10. The browser puts the map back after every refresh

The server renders the first look for every load and every refresh, so the refresh stays
a plain request for the page's own address and its answer one rendering for every
viewer. One script owns the map. It applies it after each swap of the grid, before
anything paints, and on a load before the first paint. It puts the keyboard's focus back
on the same control of the same node, and keeps an open inspection card on its node's
new element (ADR-0019). The card's text rides in each refresh, so a node that arrives
after the load has its card and a changed `about` is current; and a table's or a curve's
scroll is put back once the map is applied, since a box the map opens has no layout
before it. A pin's editor still holds the swap back (ADR-0104 decision 7). A text
selection still goes with a swap; merging the answer node by node would keep it, and is
the step to take if that bothers.

### 11. A chip and a head stay links, and a click on them toggles

In the markup a chip and an open node's head are links to the node's page, as a chip and
a name were. The script makes each a disclosure button — `role="button"`,
`aria-expanded`, Enter and Space — and takes a plain click to open or close it in place;
on an open node a plain click anywhere on its head row but its icons and actions closes
it, and the row says so itself, no caret before its cue: under the pointer a wash of its
surface's own ink at 10 %, the library's look — or, where a browser or a deployment
chooses `toggle_hover: outline` (ADR-0029), an outline of it, 3 pixels out, in the
wash's place, which forced colors draw either way — and pressed a wash of it, neither on
a control of its own, and on a touch screen the press alone; a chip the same, its wash
over its tint and its outline a pixel out where chips stand close, and neither its name
nor a head's underlined. A chip a click opens below the fold is
brought into view, as far as its box needs. A click with a modifier, a middle click and
a long press keep the link's own meaning, and without JavaScript the wall is the
server's first look with every node a link to its page. The keyboard reaches chips and
heads with Tab, and a head's controls — its actions, ⋯ and its icons — are one toolbar,
a single stop walked with the arrow keys, Home and End; a toggle moves the focus to the
other face, since the face that held it is hidden; and Escape closes the inspection
card. The wall is a grid of cards, not a tree to walk with the arrow keys, which move
only inside a toolbar. On touch a tap opens or closes, and the card is not offered
(ADR-0019). A closed node's box is hidden until found, so the browser's find still
reaches a name or a line beneath a chip, and a match opens its node and every closed
node above it as a click would, writing their entries. That reveal is provisional for
two seconds: one that a later reveal outside it follows within them is undone, its nodes
closed again and their entries put back as they were, but for the nodes above the newer
match, so a query typed letter by letter keeps the node the find rests on and not those
its shorter forms passed; a click or a key in the page keeps it at once. What the
healthy fold hides stays beyond a find, as dense mode's surplus boxes were, and a
browser without the attribute finds what is open.

### 12. A run of chips lines up in columns, or wraps where a browser says so

As decision 1 has it, a run is a node's closed children standing next to each other in
its order. A level's runs share one column width, taken from what never changes with
status — the widest of the names of all its children, open or closed, measured in the
chip's own font whatever face a child shows, but never more than one and a half times
their 90th percentile, and room for the largest count of leaves among its branches,
which changes with the tree and not with status (decision 2), and none for a leaf's
total, the count of its lines, which each reading writes — so the runs on either side of
an open child line up, and neither a status nor a reading moves a chip sideways: only a
name wider than its box, or past that bound, wraps inside its column, where its words
meet as a head's name does, and the glyphs and counts of states that mix wrap under the
name, as does a leaf's total past what its column leaves it, so a chip only grows taller
where it stands. Each run fills its row with as many columns as fit, each chip stretched
to its column with its counts at the right, and no name is cut; where two columns do not
fit side by side, as in most narrow boxes on a phone, there is nothing to line up, and
the run wraps as it comes, each chip at its own width, sharing lines. What decides is the
column as the browser draws it, the server's estimate before the script — its
characters counted in the face the browser's theme draws them in — and what the script
measured after, so a run near the line goes from one to the other when the script
measures its level, as its columns do. Wrapped as they come everywhere, each chip at its
own width, is the compact view. Which a page shows is a look, a key of the presentation
cookie (ADR-0029), with the deployment's default in `settings.yaml`,
`chip_runs: aligned | wrapped`, and the library's own `aligned`. Like a click, it is
painting: the planner prices a run's lines at its level's width from the server's
estimate — in columns from two on, each chip at its own width below — however a run is
drawn.

## Consequences

- **The wall gets shorter where it was long** once the first look is configured: as
  configured, 3.4 screens on a desk against today's 4.0, and with every leaf failing
  3.5 against 12.0. A viewer who opens far more than configured gets a taller card in
  the span the first look earned.
- **No click moves a card.** The planner prices the first look and never the viewer's
  (ADR-0128), so a click makes a card taller or shorter where it stands.
- **A viewer's look is the tab's.** Two tabs can hold two looks of one wall; a second
  machine, or a link sent to a colleague, starts as configured. The looks a browser
  keeps are the presentation cookie's: the theme, the layout, the chip runs, the
  inspection card's switch, and whether a row and a chip answer the pointer with an
  outline or a wash.
- **One script owns every toggle**, so the grid's state is one map read in one place;
  the two scripts that kept *+N more* and the chevron for the page's life fold into it.
- **Costs.** A failure under a chip past its card's budget is two clicks from its
  reason, where it was a red box in place. Aligned runs cost height on a phone: drawn as
  wide as their widest chip, they made the real wall 9.9 screens, 9.0 wrapped, where
  today's is 8.6; and a card with a hundred repositories as chips is 3.7 screens where
  three boxes and *+97 more* were 3.6, 2.6 with the healthy folded. A level's columns
  are as wide as its widest name, up to one and a half times its 90th-percentile name,
  so a long name takes columns from all its chips until it passes that and wraps
  instead: on one deployment's card at 700 pixels a run of twenty repositories takes
  three columns where the 90th percentile of the names gave four, and on a phone one
  where it gave two, 246 pixels more. A node's page keeps its facts below its children,
  so a long roster is scrolled past to reach them, as today, its head carrying the time
  and the next update for the glance; and an *about* shown open is the band's height on
  every view of its node, which the startup note keeps to a few lines. Where a node
  claims `show_when_quiet`, a funnel pressed as configured and one the viewer pressed
  fold different things, and only the changed dot tells them apart; and every roster
  with a quiet line carries a funnel, eight heads more on one deployment's tree, whose
  press on a calm roster folds what closing it would. A close made in one incident gives
  way at the next after ten calm minutes, so a node closed to keep it out of the way is
  closed again when it fails anew. On a wall that hides what is ok, a failing node's
  healthy siblings come back through the page's filter, not a click on that branch: a
  filter decides what is on the page, and a fold works only inside what it leaves. And
  every node's box is drawn into each fragment, a closed node's hidden until found, so
  that opening it needs no request and a find reaches it: what that adds to a fragment's
  bytes, the server's render and a phone's parse is measured before the first look lets
  a wall grow. A head's button at rest is an edge at 75 % of its surface's ink, 3.0 to
  4.2:1 on the light themes' tints, a little firmer than the 60 % first settled, and the
  step from rest to pressed is narrower, pressed resting more on its wash; its glyph,
  which is what WCAG 2.2's 1.4.11 asks 3:1 of, a pressed button's edge and the changed
  dot are the full ink. A closed node's name matches a find twice, on its chip and in
  its hidden head, and the second step opens it; and what the healthy fold hides is
  beyond a find, as the surplus behind dense mode's *+N more* was. A find's reveal
  stands only after two seconds: stepping quickly through matches closes each box behind
  it, which stepping back opens again; and a find that moves on to what is already shown
  tells the page nothing, so a box it passed stays open. A clipped box is one short line
  taller, its *⌄ all N* standing beneath the cut. Every fragment carries the inspection
  card's text for the nodes it draws, each `about`'s first paragraph, which the same
  measure prices; a keyboard reaches a head's controls past its first by the arrow keys,
  not Tab; and under a coarse pointer the head's corner is wider by its gaps, which its
  title gives way to.
- **Unchanged:** the snapshot and the envelope, and the macOS client, which draws no
  tree; the filters; a level's order (ADR-0055), whichever of its children are open; a
  pin's block and its editor, though one editor now serves a page; the refresh's
  cadence and what holds it back.
- **Amended:** ADR-0012, ADR-0017, ADR-0019, ADR-0029, ADR-0034, ADR-0056, ADR-0061,
  ADR-0063 and ADR-0104, each by an update under its header.

## Alternatives considered

- **A density switch per node**, the ask taken literally: a chip or a box per node, the
  page's switch kept. Two vocabularies for one gesture, and the viewer still could not
  fold an open branch's healthy children.
- **Keeping what a viewer opens past the tab**, in a cookie or on the server: set aside
  for now, not refused. A cookie would carry node paths, and the server has no per-user
  store (ADR-0029); a view kept by name, or carried by an address for a wall nobody
  clicks, is a later step if one is wanted, and reopens ADR-0029 when it comes.
- **Rendering the viewer's look on the server.** A load cannot send the tab's storage,
  so the browser would apply the map anyway.
- **Every failure opens its way**, today's rule: with every leaf failing the real wall
  is 12.6 screens; the first three under each node, 6.6; the first three a card, 3.5.
  **A chip holds its failures**, opening none, is the most compact, 3.2 screens and 8.5
  on a phone, and leaves every failure two clicks from its reason.
- **A page that shows its node as the wall does**, no deeper on the click that opened
  it; **a state of its own for each page**, so nothing carries between them; a page
  that opens **everything beneath**, nearly eight screens for a team; and **one level
  more than the wall**, four.
- **A page's facts first, the long ones folded**, as first decided: Time at the top of
  the frame and the others a line each that opened in place, held in the tab's map,
  which put github's Time card at the top where it stands 1.1 screens down; but a reader
  comes to a page for its children, and a folded report was a click on every page. Side
  by side the folded facts cut a long report into a column and left white beneath the
  short ones; in one row of lines with an opened one at the frame's full width beneath,
  or one above another, each was still a click.
- **The `about` in a tab or a popup of its own**, a click for what a node is: the short
  account belongs beneath its name, and a long one gets a tab of its own.
- **The head's buttons in a row of their own**, or shown on hover: a row of their own
  makes the phone's wall 10.0 screens where the head's row keeps it at 9.0, its runs
  wrapped, and hover hides them on a phone.
- **A branch wearing its colour on its head and frame**, or **healthy chips drawn
  white**, against the ragged edge of wrapped chips on a branch that is not green: the
  colour, not the geometry, made it show; aligned runs answer it, and the compact view
  stays the viewer's.
- **A chip with its title**, muted after its name as the dense chips had it, or only
  where the title says more than the name: in an aligned run the long titles are cut,
  in a wrapped one they cost height, and the card carries them a pause away.
- **A level's chips gathered in one run before its open children**, as the prototype
  first drew them: a click sent the opened box below the run — on a level of 100
  repositories 1,047 pixels below its chip, on a phone 365 — the failures a budget
  opened waited below the healthy chips, and a node moved because its status changed,
  which ADR-0055 refuses.
- **A node's action as a square with its label's first letter**, a guess on a touch
  screen; **every action as a labelled chip**, too wide for a head that has an icon to
  show; and **one ⋯ for a node's actions**, a second click on every one.
- **A *Close all* that drops what the viewer opened**, as first designed: in a hazard
  whose statuses change at every refresh it held the wall still, but the viewer's path
  had to be opened again by hand, four clicks on one deployment's tree. Set aside with
  it: **a switch per browser that stops the failure budget**, set once and forgotten
  until the one failure a first glance should show stays shut; **a hold** in the band,
  or one a viewer's first click takes, which freezes a look that goes stale in an
  outage; and **a budget that keeps the longest-failing open**, which shows the old
  failures rather than the new.
- **A chip that counts the leaves beneath it alone**, and a failure budget that takes
  failing leaves alone: a branch whose own reading failed above healthy leaves was a red
  chip counting nothing red, and the budget passed it by.
- **▤ in two states**: once a click opened one child of a hundred, ▤ still read as
  pressed, and a click on it opened the other ninety-nine.
- **A pin's editor drawn into every head**, as a card's setter was: 3.2 KB and 72
  elements a node, some 850 KB in every swap of an admin's tab on one deployment's tree.
- **The head's name alone as its toggle**: the head is the first thing a viewer clicks,
  and its title, state word and space did nothing.
- **`depth=0` read as 1**, which retired the one card that rolls a tree up without
  saying so.
- **A run as wide as its widest chip**, counts included, or as a high percentile of its
  chips with their counts: a count that a failure brought could halve a level's columns
  and move every chip after it, and the percentile still moved a level in an outage.
- **Every chip its counts by state**, as first decided: on a healthy chip *✓ 2* repeats
  the chip's own cue, 157 of the real tree's 203 leaves have one line and read *✓ 1*,
  and the room a glyph needs made the phone's wall up to 484 pixels taller.
- **A leaf's line count hidden wherever its lines agree with it**, so that a number
  always means leaves: a closed warning with two lines read as one with forty, and a
  band folding 15 findings as an empty one. **A leaf keeping its total for one line**: a
  muted 1 on 157 chips that are that line.
- **Pressed drawn as a fill**, as first decided: 69 dark or half-dark squares in the
  configured wall's 63 heads, every one saying *as configured*, and in the dark themes a
  fill of the ink is a bright block. **A light look in fixed greys**, as first drawn,
  vanished on the dark themes' surfaces; **an edge at 45 %**, as the rule buttons have
  it, measured about 2:1 on the light themes' tints, too faint to draw a button's square
  on a touch screen; and **at 60 %**, as first settled, 2.3 to 3.0:1 on them, conformant
  since the glyph says *button*, but faintest where the pastel theme's tints are
  lightest.
- **The healthy fold as a pill after a node's children**, no mark in its head: 17 pills
  on the configured wall, 243 pixels more on a desk and 459 on a phone, and a handle up
  to a thousand pixels below its head.
- **An eye for the fold**, struck through while folded: the most legible pair, but
  little-sister's own mark, the brand's and the strip's self-monitor; and **its count as
  the mark**, *19 ok*, a word that cut titles and names on a phone and changes width
  with its count.
- **The fold's count on its button**, behind the funnel, as a badge in its corner or
  beside it: too much for a mark that keeps one size.
- **The fold only where healthy ones stand beside others**, its seat kept: 5 funnels of
  36 on a calm day and 17 of 39 on the configured wall, but it had to stand while
  pressed and while a click had changed it too, or a fold whose trouble cleared would
  lose its button; its seat was a gap in every green head; and on a green box the fold
  does what closing does not, keeping the box open with its count, where a child that
  fails appears in its place.
- **A child that claims `show_when_quiet` never folded**, open or closed, as first
  decided: under a funnel the viewer had pressed, two rosters closed to chips stood
  green beside its count and kept nothing in view, a chip showing no quiet lines; and
  **folded only once it is a chip**, which still left an open roster under a pressed
  funnel; and **folded as a child but never its own quiet lines**, which left a failing
  roster's healthy names standing around the one that fails, and the claim an exception
  to the press.
- **A kiosk where a click does nothing**, read-only: its touch screen could show no
  reason beyond those its failure budget opens.
- **The head's icons and actions on `below`'s standing line**, after the state: the
  first line the name's alone, but a deployment's actions in the corner, where the
  head's own are looked for; **the actions at the start of that line**, the title kept
  longer, but the actions moved down and their place differing between the modes; and
  **the actions after the icons, going to a line beneath the name** on a narrow head, as
  first decided: the corner differed from card to card, and a head grew a line for them.
- **A close that holds for the tab both ways**, as first decided: a node closed in one
  incident stayed a red chip in the next, one the failure budget no longer opened; and
  **a damped node spending the budget**: up to three red boxes in a green card for what
  the card says is not yet a failure.
- **A box's lines in their check's order under the budget**, as before: a failing name
  late in a roster sat past the budget, the box yellow and every line in view green; **a
  budget that never clips a failing line**, which lets a box of thirty failing lines
  grow thirty lines tall in an outage; and **a count of the failing lines below**, as
  pinned lines have, still a click from the reason.
- **The band with no button shown in force**, as first drawn: under *Close all* an
  operator could not tell why a new failure stayed a chip; and **the viewer's count on
  *As configured* always**, which under *Close all* read as a change from a look the
  wall was not in.
- **The band's button in force filled dark**, as the prototype first drew it: the fill
  set aside for the head's buttons, above, a bright block in the dark themes; and **the
  band's buttons drawn as the Events page's switches**, the one segmented control the
  GUI has: built for filters, it strikes through a switch that is off, which reads wrong
  for a mode, and its wash of 8 % is faint for the button an operator has to see under
  *Close all*.
- **A find that sees only what is open**, as first designed: it said nothing was there
  for a failure beneath a chip, and under *Close all* reached little more than the
  cards' names; and **the healthy fold hidden until found as well**: an element so
  hidden keeps its place in a grid, so a folded chip left a hole in its run.
- **The chevron in the head's state cluster**, where it stood: a triangle in a row that
  opens and closes its node by a click anywhere on it; a seat more in a row that never
  wraps, and on a card an empty slot wherever the lines fit; and a control at the top of
  lines whose cut is at their foot.
- **A caret before the head's cue**, ▾ open and ▸ closed, as the sign that the row opens
  and closes its node: on an open box it said what the box shows, on a closed card what
  its counts show, and it took a column of every head. The row's outline under the
  pointer says it where it is wanted.
- **A wash under the pointer for everyone**, the head's quiet words lifted to full ink
  under it or not: 1.12 to 1.30:1 from the row at rest, where the outline stands 2.2 to
  5.1:1 away, faint on the pale tints most of a quiet wall stands on, and gone under
  forced colours, which repaint every fill. A viewer's choice of it in the outline's
  place joins the presentation cookie
  ([ADR-0029](0029-per-user-presentation-preferences.md)) beside the chip runs and the
  inspection card's switch, built with them.
- **No border and no fill from the third level down**, a rule in the state's colour at
  the left and the head alone: a card of the real tree 3.8 screens on a phone where
  boxes keep it at 4.2, but its innermost line only 12 pixels wider, since a rule still
  indents, and a healthy node beneath a failing one without its green; and **the same
  from the second level**, only the card a box, under which a healthy check read as part
  of a red team card.
- **The inspection card's text loaded once with the page**, as before: a node a run
  names after the load had no card, and a changed `about` stayed as loaded until a
  reload. A fetch on the first pause stays the way back should the text weigh too much
  in every fragment.
- **A line with no code of its own judged by its node's own reading**: under a pressed
  funnel a branch's own sentence, which explains a failure beneath it, folded with the
  healthy while that failure stood beneath.
- **Larger squares on touch**, 32 or 44 pixels: that card 4.5 and 4.9 screens on a phone
  where it is 4.2, and its names cut; **every control its own tab stop**, 327 on the
  configured wall where a toolbar to a head makes 240; and **letter keys on a focused
  head**, unseen and in the way of a screen reader's own.
- **A legend** for the cues and counts, in the settings menu, on About or at the wall's
  foot: the counts carry their words where they stand.
- **A *Close all* and *Open all* for each view**: whether they hold on a node's page
  would have been asked again, and the band's count would be a view's.
- **A run's width at the 90th percentile of its names**, as first settled: a column more
  where the box has room for it, but the one name past the percentile carried its count
  beneath it and stood its row taller.
- **Room for a leaf's lines** in a level's width: a band going from nine findings to ten
  widened its level's columns, and the planner, pricing a run at that width, would read
  a reading (ADR-0056); and **two digits of room on every level**: on one deployment's
  tree the desk wall 30 pixels taller and a phone's 119, runs of one-line leaves one
  chip to a row for counts none of them shows.
- **One chip to a row where two columns do not fit**, as first settled: on the recorded
  wall under the configured look, twenty runs on a phone drew 72 chips one to a row, 719
  pixels more than wrapping them as they come; **two columns at least**, names breaking
  inside them, which a stand-in read 384 pixels shorter than one to a row, a name on two
  lines stretching its neighbour to its row; and **the estimate deciding alone**, before
  the first paint and never after: nothing moves when the script arrives, but a run the
  estimate gives two columns where the font draws one stays one chip to a row, as one
  of a phone's did by a pixel. **One letter for every theme's face**: cyberpunk draws in
  a monospace face, every character a whole `0`, where the system's faces run at 0.6
  to 0.9 of one; counted at 0.85 the estimate stood 10 to 30 pixels short of what the
  script measures there and 11 of 194 runs changed at the script, against 4; and a
  whole `0` in every theme stands the system's faces wider than they draw again, as
  the estimate did before it counted 0.85 of one.
- **The outline under the pointer as the library's look**, as first settled: the wash
  took its place on Lex's word of 2026-10-18, the outline a browser's or a deployment's
  choice.
- **The widest name unbounded**, as first settled: one name of 64 characters among a
  hundred repositories put them all one to a row, a card at 700 pixels 4.6 screens where
  it was 2.5; and **a bound in characters**: at 40 it left them one to a row, it helped
  only at about 24, and a fixed count cannot tell one long name from a level whose names
  are all long.
- **Every reveal kept**, as first settled: a find searches as its query is typed,
  Chrome's from the first letter, and a query whose shorter forms first matched beneath
  other chips left those open too, counted on the band with what the viewer opened and
  dropped only with it.
