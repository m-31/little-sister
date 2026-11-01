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
Nothing else on the wall moves when you do — not even at the foot of the page, where
what you close or fold stays where it was and the page keeps the space it freed until
you scroll back up.

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
them, a line in maintenance on a node that is not, a line somebody marked done, a
failure somebody marked seen or silenced, and a part a rule of the deployment's makes
count otherwise (below) — and the tooltip ends with how many of each, *2 seen, 1
silenced, 1 by a rule*. Such a part keeps its own color among the counts: a red node a
rule lets count as a warning is counted red, and its parent is amber.

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
time of what you see. What you opened stands through each refresh. While the drawer is
open, or an editor on the page, the wall waits for it, and what holds it says so in its
own head, *updates paused*; after a minute the rest of the wall dims. If the server
cannot be reached, that line turns red, a banner says since when, and the page's title
starts with *(stale)*; nothing on the wall pretends to be live meanwhile.

### Finding a word

The browser's find (Ctrl-F, ⌘-F) reaches into closed nodes: a match beneath a chip opens
that node and every closed node above it, as a click would. Typing on, a later match
within two seconds closes again what the earlier one opened. What a funnel folds (below)
stays out of the find.

## The band

Above the wall stands the band: where you are, *updated* and the time, and three
switches: **hide ok** leaves out the healthy nodes, so that the wall becomes the list of
what needs you, **hide idle** those that have never reported, and **◇ details** puts the
blocks of what handles a part on the wall — off unless your deployment says otherwise, a
handled part saying so by its color and its mark, and ◇ by its number
([below](#maintenance-and-what-is-handled)). This browser keeps the three as you set
them.

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
are — each pin, each line marked done, each failure marked seen or silenced, and each
part a rule of the deployment's changes now — and leads to *Handled*. On a card, its
**◇** says how many parts are handled at and beneath it
([below](#a-heads-buttons)).

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
- **◇**, the node's door, opens its *Notes* tab in a drawer over the wall: what fails
  there, what stands, what came before, and — for whoever may — the form that writes a
  note, marks a failure done or seen, silences a part, failing or not, or puts the node
  or a line in maintenance ([below](#maintenance-and-what-is-handled)). Where something is handled at
  or beneath the node it is lit with how many parts are, its tooltip saying how many of
  each, *3 handled: 1 line in maintenance, 2 seen*. While it is lit it stands at the
  start of the head's state, in sight when the pointer is elsewhere, and the buttons
  carry none; a plain one comes with them. Every reader has it; the overview's own card,
  which is every node there is, has none.

A dot on a button says you set it differently from the configured look. Before the state
stand the node's own actions — a runbook, a ticket to file — and those the row has no
room for fold behind **⋯**. The buttons are one stop for Tab; the arrow keys, Home and
End walk them, and a lit ◇ beside the state is a stop of its own. Where the buttons
stand is the look *Head's buttons*: where they always show, a lit ◇ stays among them.

## The drawer

**◇**, a line's **◇**, every mark of what handles a part and, with *◇ details* on, every
block on the wall open the node's *Notes* tab in a drawer over the wall — at a desk at
the side that leaves the box you clicked in sight, on a phone as a sheet from the bottom,
the box above it. The tab is whole in it, opened at its top from a head, at its form on
the line from a line, and at the block a mark marks or a block states, its editor open.
The wall waits while the drawer is open, the drawer saying *updates paused* under the
node's name, the box you clicked lit. What you write there is written as on
the tab: once it goes through the drawer closes and the wall is up to date at once; a
refusal stays in the drawer with why and your words. **✕**, Escape, or a click on the
wall closes it — and where you wrote something not sent, it asks first, *Discard what
you wrote?*, *Keep writing* chosen unless you choose otherwise. The drawer's head links
to the node's page and to its tab; a click on a door with Ctrl or ⌘ opens the tab in a
new browser tab.

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
- **Notes** — the place to act on the node. What fails at and beneath it; a line on what
  came before — how often it was handled and noted, the last time and how that ended,
  and the links its notes carry; what stands on it now, each with *Edit* and *Clear*;
  and a form that writes a note, or closes a line's failure as done, marks a failure
  seen, silences a part, failing or not, or puts the node or a line in maintenance —
  whichever you may — on
  the node, a line, or every failure listed. Where the instance files tickets, a button
  after the act's own opens a draft of your words in the tracker, in a new tab, their
  first line its summary: paste the issue's link into the words before you save, and it
  stands with the part's other tickets. Whoever may set nothing has that button too,
  with *On*. Beside them, what came before, newest
  first: every note, and every pin that has ended, each saying what it was on, from when
  to when, who, why it ended and its words, with what the node showed then folded
  beneath it — one act on many lines once. The number on the tab counts them, a pin that
  stands among them.
- **Handbook** — what its team wrote at length about it, where it has one.
- **Copy** — the node as a document, to paste into a chat or a ticket.

## Maintenance, and what is handled

Everything below is set in one place, a node's *Notes* tab, which **◇** on its head
opens; on a node's page a line's own **◇**, at its end for whoever may set something
there, opens the tab with its form on that line. Whatever handles a part says so with a
mark, and the mark opens the tab at what it marks, where it is changed. The tab heads
what stands with how many parts are handled, *3 handled*, the number ◇ says.

An admin can put a node, or one of its lines, **in maintenance** for a while: it stops
alarming and shows blue, the reason written as a note. The pin stands as a block with a
dashed edge, saying who put it there, until when and how long is left. An admin sets one
on the node's *Notes* tab, *Maintenance* chosen in its form. On the node's page and its
*Notes* tab the block shows the note whole, with *Edit* and *Clear*; on the wall, with
*◇ details* on, it is its sentence alone, which opens the drawer at it, where the note
is read and the pin changed or cleared. When the pin ends the *Notes* tab keeps it —
with words or without — saying how long it stood and why it ended. The Events page says each
end and why — *maintenance ended · at its end*.

A window can be set **ahead**: *Starts*, above the end on the form, says when it opens —
blank is now, and it takes what the end field takes, *Sat 22:00*, *3d* or a date — and a
duration in the end field then counts from the start; a window set on the page ends
within a year of being set. Until it opens it holds nothing, and is listed apart, under
**Planned**: on the node's *Notes* tab beneath what stands, beneath the blocks on the
node's page, and on *Handled*, counted on no ◇. Its block, without the blue, says it in
one sentence and when it starts — *Once, from 2026-11-07 22:00:00 until 2026-11-08
06:00:00 · starts in 6d* — with *Edit* and *Clear*; setting one from the drawer keeps
the drawer open on it. At its start it opens by itself, and the Events page says *window
opened*.

A **schedule** of windows — every Saturday night, say — is set on the same form:
*Repeats* every so many days, weeks on the days you tick — *weekend* and *working week*
tick theirs — or months on a day or a weekday, and the rest opens in place: *Until*, its
last date, at most a year away; *Not on*, which leaves out a holiday list's days;
*Times in*, the zone its times are read in; and *Add an interval*, a window of its own
beside the rule's. With a repeat the end field is *Length*, how long each window is —
*8h*, or *1d* for whole days. Beneath the fields the next five windows and the
schedule's sentence say what it sets before you set it, the first window on the first
day on or after *Starts* that the rule picks, and a night the clocks change marked with
how long its window really lasts. A window set where a schedule stands joins it, unless
you choose that it replaces it.

Before them stands the **month**: each day's hours — on a phone a bar across the day —
a night the clocks change marked, a day the holiday list leaves out by its name, and a
date left out with its time struck; ‹ and › page it by month and « and » by year, as far
as a year away. A click on a day leaves its window out, or puts back one left out; on a
day the holiday list leaves out it adds the window back; and on a day without a window
it adds one at the schedule's time, as long as its others. Each is listed beneath with
its ×, and nothing is set until you set it. From the keyboard the month is one stop: the
arrow keys move a day or a week, Home and End to the week's ends, Page Up and Page Down
a month — with Shift a year — and Enter clicks the day.

While a window of a schedule is open its block has two rows. The first is the window,
its own end and the time left, with *Extend* — by 30 minutes or 1, 2 or 4 hours from its
end, or until a time you write, never shorter — and *End now*, which closes this window
and leaves those to come, or on the schedule's last window ends it. The second is the
schedule, its sentence and its next start, with *Edit*, which changes the windows to
come and leaves the one open as it is, and *Clear*, which asks first, since it ends the
windows to come as well. Where a schedule's holiday list cannot be read, or from 1
December is not complete for the coming year, the instance's own *Holidays* says so,
and how many schedules it stops.

The *Notes* tab counts a schedule's windows as they open, each once: while it stands its
block ends in how many ran and how the last closed — *· 3 windows ran, the last closed
by hand, by pan* — and once it has ended what came before says what of it ran in place
of how long it stood — *Planned as a schedule by pan*, *3 windows ran, 2h 10m in all*,
or *no window opened* — and that it ended *with its last window*, or by whose hand. A
window set ahead says *it ran 2h* or *it never opened*. On the Events page a row of a
branch's maintenance, which reads nothing of its own, says *nothing of its own* where it
ends; the *undefined* switch finds it.

A pin, or a silence, stays on a part that is **not reported now** — a line its node no
longer reports, or a node its check no longer returns or has not written since the
instance started — holding nothing until the part is back, and ending as it would. It
still stands, and is counted where it stands: on the ◇ of its node or, for a node not
reported now, of the nearest node above it, whose *Notes* tab lists it as *not reported
now*; on the band's pill; and on *Handled*, where it is changed or cleared.

A failure you have looked into can be marked **seen**: it keeps its color, and counts as
ok one level up until it changes, so the branch above stops alarming for it and alarms
again for anything new. It ends by itself when its part recovers, gets worse, fails anew
or is no longer reported — or at a time you give it — and by hand. An admin marks a
failure seen on the node's *Notes* tab, *Seen* chosen in its form: a line, the node's own
failure, or every failure at and beneath the node, each on its own and with one note.
Its block, under the **ringed check**, says who marked it, at which status and what ends
it; a line marked seen carries the ringed check at its top right, and a node beside its
state. The Events page says each end and why — *seen ended · worse*.

A failure that flaps — red, then green, then red again — can be **silenced** until a
deadline instead: it keeps its color, and counts one level up as ok, or as a warning at
most, through every recovery, so the branch above stops alarming for it while the
silence lasts. A silence always has a deadline — the deployment's default, a week unless
it says otherwise, and thirty days at most — and ends there or by hand; moving the
deadline later asks what changed, which is kept as a note of its own on the *Notes* tab,
as it is whenever a change says it. It is set as a seen is, with *Silence* chosen
instead — and on a part that reads ok as well, a line or a node that reads by itself,
so that a part that flaps is silenced between two failures: nothing changes until it
fails, and from then it counts as the silence holds it. A part in maintenance, or one
somebody holds already, takes none. Its block, under a bell struck through, says who
silenced it, what it counts as and until when; a silenced line carries the bell at its
top right, and a node beside its state. *Edit* on a seen's block makes it a silence, and on a
silence's makes it seen while its part fails, the one ending as the other is set.

An event looked into and over — a failed run, a function's held error — can be marked
**done** where its line says which event it is: the line shows ok, with the failure it
closed beside its cue and in its own words, and counts as ok one level up, so the branch
above stops alarming for it, and it folds with the healthy lines. It holds while the
line reads that failure, a year if need be, and ends when the line reads anything else —
its next run, whether it fails or passes, the same failure recovered or worse, or no
line at all — and by hand, never by the clock; the next failure alarms as new. A done is
set on the node's *Notes* tab, *Done* chosen in its form, on a line whose failure is an
event; *Edit* on a seen's or a silence's block makes it done there too, and on a done's
block makes it seen or a silence. Its block, under the ringed check,
says who marked it done and the failure it closed. The Events page says each end and why
— *line's done ended · a new occurrence*.

The deployment's configuration may also say, for good, how a part counts one level up:
that a test account turns its parent amber at most, that a waiting gate is no failure,
that one host of five may be down. Such a rule is marked **§**. The part keeps its own
color — red stays red — and a block with a dashed edge says what it counts as above and
by which rule: on the wall while the rule changes something and *◇ details* is on, and
on the node's page always, with *changes nothing now* where it does not. A line the rule counts otherwise
carries § at its top right, and a node beside its state. Nobody changes such a rule on
the page: it is changed in the configuration, which the block names. A rule that counts
how many fail — one host of five — counts a host seen or silenced as it reads, so a
second host down still alarms; the silenced one itself counts as its silence holds it.

Whatever handles a part, the part keeps its own color — but a line marked done, which
shows ok — and its mark says what it counts as one level up: the ringed check, the
struck bell and § are drawn in that color, ‖ in maintenance's blue. Rest the pointer on
a mark for who, until when and what it counts as; a click on it opens the node's *Notes*
tab at what it marks. Wherever a part counts as something other than it shows, a
stripe of that color runs down its right edge — green on a line marked seen, and on a
box whose own failure is marked seen while nothing beneath it fails; green or amber on a
failure silenced, as its silence counts it; amber or red where a rule counts a part as a
warning or an error; gray where it counts as nothing. A node that waits before it
escalates draws one too, in the color the level above still counts, beside *· 2 of 3 to
escalate*, and so does a node reached through a check that is failing, gray, beside *·
reached through vpn*: nothing of it counts above until that check answers.

**Handled**, in the navigation and behind the band's pill, lists every rule that stands:
the pins by node, with what is planned under *Planned*, the soonest first, what was
marked done or seen under *Accepted*, what was silenced under *Silenced*, and the
deployment's rules under *By a rule*, each with what it changes now.

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
