# Using the wall

The wall is everything this instance watches, as one tree: a card for each system, and
inside it the parts it is made of. This page says what you see on it and what a click
does. How the wall first looks is the deployment's — it says which levels start closed
and what each node is called. What you open and close yourself is yours, and it is kept
for the browser tab you did it in.

## The wall

### Chips and boxes

Every node on the wall is either **closed**, a small *chip*, or **open**, a *box* with
its head and its lines. A click on a chip opens it in its place, the chips around it
standing where they were; a click anywhere on an open box's head — its name, its title,
its state, the space between — closes it to a chip again. A click on a card's head
closes the whole card to one line, its name and its counts, and a second click opens it.
Nothing else on the wall moves when you do.

A click on one of a head's buttons or actions is that button's, and dragging across a
head to select its text opens and closes nothing. To open a node's own page instead,
Ctrl-click (⌘-click on a Mac) its chip or its name, or use ↗ among its buttons.

From the keyboard, Tab reaches each chip and each name; Enter or Space opens and closes
the node.

### Colors and counts

A node's color is its status: green **ok**, amber **warn**, red **error**, blue
**maintenance**, gray **undefined** for what has not reported yet. A reading that is not
renewed in time counts as a problem, so green always means freshly checked. A box that
is only colored by something beneath it is dimmed, and so is a healthy one; the node
that actually reports the problem stands out. The engine reports on itself as a node
too, so a monitor that has stopped shows.

A chip says what is beneath it: a cue, its name, and its counts of the nodes beneath it,
or of a leaf's lines — one number where they all share a state, each state's mark and
number where they mix, none for a leaf of one line. Rest the pointer on a chip and its
tooltip says the counts in words. Among the counts, **‖** and a number count what is in
maintenance: the leaves beneath it, or a leaf's lines. A **ringed diamond** and a number
count what else a rule handles — a branch in maintenance, the chip's own node among
them, a line in maintenance on a node that is not, a failure somebody marked seen, and a
part a rule of the deployment's makes count otherwise (below) — and the tooltip ends
with how many of each, *2 seen, 1 by a rule*. Such a part keeps its own color among the
counts: a red node a rule lets count as a warning is counted red, and its parent is
amber.

### A box's lines

A box's lines are what its check says, its failing lines first: errors, then warnings,
then the rest. A box shows as many as its budget holds — a long line takes more of it —
and where there are more, **⌄ all N** beneath them shows the lot. Where the lot is
taller than about half the window, it scrolls inside the box, and it stays where you
scrolled it as the wall refreshes; **⌃ less** folds the lines to their first ones again.
A node's own page always lists every line.

### What opens by itself

How each node starts is the deployment's to say, and each check type proposes its own: a
level known to be big — a host's many readings, an account's services, a repository's
workflows — starts as chips, and the rest open, the healthy ones shown. A level nobody
configured starts open too, unless it is big: one
that, opened, would draw more than thirty boxes, counting everything beneath it, starts
as chips, so a check that suddenly names a great many children does not stretch the
wall. On top of that, the wall opens its failures: in each card, up to three failures
hidden under chips open their way, errors before warnings, with every node on their
path, so a new failure shows at a glance.
Whether this happens is the look *Failures* in the settings menu
([below](#the-settings-menu)).

Close a failing node yourself and it stays closed until its trouble is over: it opens
again only for a failure that comes after it has been well for ten minutes, not for one
that flickers.

### Staying up to date

The wall refreshes itself about every ten seconds, and *updated* in the band says the
time of what you see. What you opened stands through each refresh. If the server cannot
be reached, that line turns red, a banner says since when, and the page's title starts
with *(stale)*; nothing on the wall pretends to be live meanwhile.

### Finding a word

The browser's find (Ctrl-F, ⌘-F) reaches into closed nodes: a match beneath a chip opens
that node and every closed node above it, as a click would. Typing on, a later match
within two seconds closes again what the earlier one opened. What a funnel folds (below)
stays out of the find.

## The band

Above the wall stands the band: where you are, *updated* and the time, and two switches:
**hide ok** leaves out the healthy nodes, so that the wall becomes the list of what
needs you, and **hide idle** those that have never reported.

Where the deployment tags its nodes, a list beside them shows only what carries one tag
— *production*, say: each part that carries it is a card of its own, the path above it
before its name, and a line above the cards says what the tag means, names the parts
the filter hides that fail, and leads back to every node. On a node's page it shows
what carries the tag beneath the node. The address keeps the tag, `?tag=production`,
and nothing else remembers it: the next visit shows every node.

Its three buttons open and close everything at once:

- **Close all** closes everything the configuration and the failures opened, and keeps
  what you opened yourself, with the nodes above it; a second click closes those too.
- **Open all** opens every node, the healthy ones shown.
- **As configured** brings the first look back and forgets what you opened in the tab.

The button in force is pressed, and its number says how many nodes you set yourself in
this tab. Where something is handled, a pill reads the ringed diamond and how many parts
are — each pin, each failure marked seen, and each part a rule of the deployment's
changes now — and leads to *Handled*.

What you open is kept for this browser tab: a refresh and a reload keep it, and a new
tab starts as configured. An address may carry `depth=`: `depth=2` starts the wall with
the cards' children closed, for that one visit, and `depth=0` shows one card for
everything.

## A head's buttons

An open head carries its buttons right after its name, shown while the pointer is on the
head or the keyboard is in it:

- **↗** opens the node's page.
- **The funnel** folds the node's healthy children and lines behind *✓ +N ok* at the
  end; pressed while they are folded. A click on *✓ +N ok* shows them.
- **▤** closes every child to a chip; a click on one child afterwards changes that one
  alone.
- **‖**, for an admin, sets maintenance on the node
  ([below](#maintenance-and-what-is-handled)).
- **The ringed check**, for an admin, where something fails at or beneath the node,
  marks each of those failures seen ([below](#maintenance-and-what-is-handled)).

A dot on a button says you set it differently from the configured look. Before the state
stand the node's own actions — a runbook, a ticket to file — and those the row has no
room for fold behind **⋯**. The buttons are one stop for Tab; the arrow keys, Home and
End walk them. Where the buttons stand is the look *Head's buttons*.

## A node's page

A node's page shows the same tree, framed: the node's own head at the top, its lines
beneath it, and its children as the wall's cards. Its tabs:

- **Status** — the node now: since when it has shown what it shows (*Time*), how it is
  configured and checked, and its *About* card, which says what its check reads, what
  the node is and what to do about it, and lists its tags — each leads to the wall that
  shows what carries it. On a branch, a card right after *Time* says why
  it has its color — *Why error*, *Why warn* or *Why ok* — and what beneath it counts.
- **Series** — the curves of what is measured at or beneath the node, with the number of
  curves on the tab.
- **History** — the node's periods and every reading kept of it.
- **Notes** — what was written about the node and its lines, newest first, with the
  number of notes on the tab and, folded beneath each, what the node showed then. A
  pin's note is kept here when the pin ends; an admin writes one of their own at the
  top, or on a line from the mark at the line's end.
- **Handbook** — what its team wrote at length about it, where it has one.
- **Copy** — the node as a document, to paste into a chat or a ticket.

## Maintenance, and what is handled

An admin can put a node, or one of its lines, **in maintenance** for a while: it stops
alarming and shows blue, the reason written as a note. On the wall the pin stands as a
block with a dashed edge: one sentence saying who put it there, until when and how long
is left, and a speech bubble that opens the note. An admin sets one with **‖** in a
head's buttons, or on a node's page with the mark at the end of a line, and on the wall
changes or clears it with the pencil after the bubble. On the node's page the block
shows the note whole, with *Edit* and *Clear*, and the note stays on the node's
*Notes* tab when the pin ends.

A failure you have looked into can be marked **seen**: it keeps its color, and counts as
ok one level up until it changes, so the branch above stops alarming for it and alarms
again for anything new. It ends by itself when its part recovers, gets worse, fails anew
or is no longer reported — or at a time you give it — and by hand. An admin marks a
line seen with the **ringed check** at its end, beside ‖, and a node with the ringed
check in its head's buttons, which marks every failure at and beneath the node, each on
its own and with one note. Its block, under the ringed check, says who marked it, at
which status and what ends it; a line marked seen carries the ringed check before its
words. The Events page says each end and why — *seen ended · worse*.

The deployment's configuration may also say, for good, how a part counts one level up:
that a test account turns its parent amber at most, that a waiting gate is no failure,
that one host of five may be down. Such a rule is marked **§**. The part keeps its own
color — red stays red — and a block with a dashed edge says what it counts as above and
by which rule: on the wall while the rule changes something, and on the node's page
always, with *changes nothing now* where it does not. A line the rule counts otherwise
carries § before its words. Nobody changes such a rule on the page: it is changed in the
configuration, which the block names.

**Handled**, in the navigation and behind the band's pill, lists every rule that stands:
the pins by node, what was marked seen under *Accepted*, and the deployment's rules
under *By a rule*, each with what it changes now.

## The settings menu

Your name, at the top right, opens the settings menu. Its first row says whom this
browser is signed in as, and **Log out**. Beneath it, under *Display*, are the choices
of how the page looks — saved in this browser, not in your account. The deployment sets
each one's default, and a choice you make wins in this browser. A choice applies at once:
the page draws itself again with it, and the menu stands open on your choice, so you can
try the next; *Escape* or a click beside the menu closes it.

- **Theme** — the page's colors: *auto* follows the operating system's light or dark;
  *plain*, *vivid* and *pastel* are light, *dark* and *cyberpunk* dark.
- **Layout** — where the navigation stands: a *left rail*, a *top bar*, or none on a
  *kiosk* ([below](#the-kiosk)).
- **Chips** — how a level's chips line up: *aligned* in columns, or *wrapped* as they
  come.
- **Boxes** — how a level's boxes fill its columns: *in rows*, each row as tall as its
  tallest box and every box in its place; or *packed*, each box beneath the shortest
  column, so that a tall box leaves no gap beside it. A packed box keeps its column
  while the page is open at its width, and takes one anew when the page is drawn again
  or its width changes.
- **Hover card** — whether a pause on a name opens its card, with its title and what it
  is: *on a pause*, or *off*.
- **Under the pointer** — how a row shows that a click opens it: a *wash* of its color,
  or an *outline*.
- **Head's buttons** — where an open head keeps its buttons: *after the name, under the
  pointer*; *after the name, the name opens the page*; *on a line beneath*; or *at the
  end, the name opens the page*.
- **Failures** — whether failures beneath chips *open their way* or *stay chips*, the
  wall keeping its size. Keep them open, on a kiosk too: a new failure shows at a
  glance.

## The kiosk

The *kiosk* layout is for a screen nobody stands at: one line with the time of what is
shown and the way out, and the wall beneath it, without navigation, filters or a head's
buttons. A tap still opens and closes a node. What somebody opened is kept only while
they are there: five minutes without a pointer, a touch, a key or the wheel, and the
wall goes back to its first look. **Exit** returns this browser to the default layout.

## On a phone

The wall is laid out for the screen's width, and no page scrolls sideways. A head's
buttons always show, a tap on a name opens and closes the node, and the actions a row
has no room for fold behind **⋯**.

## The other pages

- **Series** — every node a curve is kept on.
- **Events** — every change of what a node shows, newest first, narrowed by a node, by a
  tag, by words, by the status it moved to and by time; the address keeps the filters.
- **Handled** — every rule that stands ([above](#maintenance-and-what-is-handled)).
- **Links** — the dashboards and tools this deployment keeps at hand.
- **Copy** — the whole wall as a document: what is not ok, with the nodes above it.
- **System** — for an admin: the instance, its engine and its checks.
- **About** — who this is, and the version in front of you.
