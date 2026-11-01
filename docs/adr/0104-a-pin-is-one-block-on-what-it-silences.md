# ADR-0104 — A pin is one block on what it holds, and it is edited there

- **Status:** Accepted
- **Date:** 2026-11-01 (accepted 2026-10-03)
- **Related:** [ADR-0014](0014-maintenance-persistence.md) (the pin, its expiry, its
  compare-and-set token and its editor — decisions 6, 7, 9, 13 and 16 to 18, which
  this amends), [ADR-0036](0036-addressable-reasons.md) (a pin on one line, and how
  *Handled* lists pins — decisions 10 and 12, which this amends),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 5: a transformed contribution is
  visible and attributable), [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (a
  pin is a rule in the snapshot, and one on a node holds everything beneath it),
  [ADR-0047](0047-node-notes-and-their-retention.md) (a pin's text is its note),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the refresh and the stamp
  that dates the page), [ADR-0056](0056-stable-useful-dashboard-flow.md) (the wall's
  cards), [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision 7, the configured
  timezone),
  [ADR-0019](0019-inspection-popover.md) (the inspection card a node's row answers to),
  [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 4: a pin whose
  node is not reported),
  [ADR-0124](0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)
  (a pin on a line of a node above holds that line alone),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (the wall as
  a tree: an open node's head and its icons, a chip, and a node's page framed),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md) (the block on the wall, its
  words, its edge and its fill, a closed node's mark and the page that lists every pin —
  decisions 1, 2, 6, 7 and 8, which it amends),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (the first
  block the configuration declares — decision 8),
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (the pin's route and its place in the envelope),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (a
  second kind's block, and the ringed check that sets it),
  [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (decision 3: a line's
  note, written from its editor),
  [ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
  (*silenced*, the block in a third kind's words — amended),
  [ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
  (*done*, the block in a fourth kind's words — amended),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md) (the door, ◇, and the drawer it opens over the wall, where a pin is set and changed — decisions 1, 3, 4 and 7 amended),
  [ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
  (a maintenance entry as its schedule: a planned one's block, its editor's fields, and
  a series' window open in two rows)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A pin was shown and changed in three different ways. On a node's own page the status
card stated it in a strip cut off after two lines, and a card at the foot of the page,
an admin's only, stated it again in full beside *Edit maintenance* and *Clear
maintenance*; a node without a pin had its *Set maintenance* in that card too. On a
node whose lines can be pinned one by one, every line ended in *Set maintenance*,
whose editor floated over the lines beneath it, so the node's control and its lines'
said the same words in two places. On the wall a card's pause mark opened a dialog.
The Maintenance page listed every pin in a table to read, and changing one meant
following its link.

One expiry read three ways: *Time left 1d 23h* on the Maintenance page, *until
2026-10-03 20:44:28* in the status card and *Expires 2026-10-03 20:44:28* in the card
at the foot. And an edit that left the expiry field as it found it — blank — renewed
the pin for the configured default from now, so correcting a word in the explanation
moved a pin that had two days left to seven.

And a node silenced by a pin on a node above it said nothing of that pin on its own
page: *Status: error* and *Set maintenance*, on a node that would not alarm.

## Decision

### 1. One block states a pin, wherever a pin shows

Who pinned it, until when and how long is left, and its note; for an admin, *Edit* and
*Clear*. The same block stands on a node's page, under a line, on *Handled*, on a node's
*Notes* tab and in a box on the wall. Where a node is stated on its own — a node's page,
for the node and its lines, its *Notes* tab and *Handled* — the block is stated whole:
its note in full, *Edit* and *Clear* in words. On the wall it is lighter, and stands
only while a browser's *◇ details* is on
([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
decisions 6 and 7): its mark and its sentence — who, until when and what is left — as
one link, its sentence its name, which opens its node's *Notes* tab in the drawer over
the wall at that pin, where its note is read and its editor stands open for whoever may
change it; the block carries no note mark and no pencil. The expiry reads one way in
all of them, the instant and what is left: *until 2026-10-03 20:44:28 · 1d 23h left*.
Where the sentence wraps, as it does in a narrow card, no line ends inside a word of an
instant: the date and the time of day each stay whole. A viewer sees the block without
its buttons, and, where a node is stated on its own, with the note whole, which the
strip cut off.

### 2. Where the block stands says what it covers

A node's page is framed, a leaf's as a branch's
([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision 8),
and a node's block stands at the head of the frame, beneath the head's row, above the
lines and the children it covers. A line's block hangs beneath that line; where the
node is pinned too, it says *also in maintenance on its own*, because the line stays
quiet when the node's pin ends. On the wall the block stands in its node's open box:
under a card's head and above its lines and the boxes it covers, its sentence opening
*In maintenance by*, since the head names the node, and a box inside a card states its
own pin the same way. A closed node shows no block; its chip shows a ringed diamond and
the number of what a rule handles beneath it that its counts do not show (ADR-0135
decision 6).

A pin set on a node above this one holds it with everything else beneath that node
([ADR-0041](0041-maintenance-is-a-contribution-rule.md)), so this node's page states it
where it acts as well as where it was set: the same block, its note whole and **without
buttons**, since a pin is edited where it stands, its sentence naming the node it stands
on, linked to that node's page — *This node is in maintenance from /nexus/qnap by anna
until …*. Each such pin is a row of decision 8's list at the head of the page's frame,
outermost first. The node's own pin under one says *also in maintenance on its own*, as
a line's does under its node's, and a line's pin says the same under a pin above; the
editors that set either say that it is for the day the pin above ends. A pin on a
**line** of a node above holds that line alone
([ADR-0124](0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md))
and is stated on its own node's page only.

### 3. A new pin is set on its node's *Notes* tab, which one door opens

One door, ◇, stands among the own buttons of every open head — a card's and a box's on
the wall, and the head of a node's page — and, on a node's page, in each line's one
seat at its end
([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
decision 1). It opens the node's *Notes* tab — on the wall in a drawer, the wall waiting
beneath it — and a new pin is set on the tab's form, maintenance one of its kinds, the
form's *On* saying what the pin will cover: the node and everything beneath it, or one
line. Without script ◇ is a link to the tab. The head's own *Set maintenance*, the
page's one editor cloned into a box and a line's pause mark go, and with the line's its
*Write a note on this line*; no fragment carries an editor. The overview's own card
sets no pin, because putting everything in maintenance is not done from a form; a pin
that stands there is stated and changed like any other. The card at the foot of a
node's page goes.

An acknowledgment is a pin too, set on the same form under its own kind
([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) decision
5), and the ringed check is a seen's mark, which opens the drawer at it (ADR-0147
decision 7).

A node's row on the wall and a page's head also answer to the inspection card
(ADR-0019), and a pin's own controls in them are not that card's to answer: the mark,
the block and an editor. A row with an editor open in it raises no card at all. The
control that opened the editor has given way to it, so the pointer that clicked is left
on the row, and the row's card would stand over the one above while the note is typed.

### 4. Edit opens the block where it stands

A pin is changed where its block stands: on a node's page and on *Handled*, its *Edit*
and *Clear* in words, and from the wall in the drawer, opened at its block with its
editor open (ADR-0147 decision 3). *Edit* turns the note into its Markdown source in a
field, with the expiry, *Save changes* and *Cancel*; who pinned it and when stands at
the top of the editor. A line's editor opens beneath its line, where it floated over the
lines. The disclosure is the browser's own, so every editor works without script, and
pinned stays a read state (ADR-0014 decision 16). Where script runs, the editor opens in
its note, at the note's end.

A pin's writes go to `POST /pins/maintenance`, asking the permission `maintenance`
([ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
decision 4), and a write comes back to where its block stands; one made in the drawer
closes it and brings the wall up to date at once (ADR-0147 decision 3). From a node's
own page that is the top of the page for the node's pin, and for a line's the line
itself: its edit and its clear return to the address that names a line,
`?reason=<slug>#pinned-reason` (ADR-0036 decision 12), because on a node of 150 lines
the top of the page is a long way from the line that was just pinned.

### 5. An edit shows the expiry it would keep

On an edit the expiry field holds the stored expiry, a date and time in the configured
timezone as the field reads one. The form carries what the field was filled with, and a
field that still says it keeps the stored instant exactly: it is not read again, so the
floor a typed expiry is held to (ADR-0014 decision 13) and the hour a clock change
repeats cannot refuse an edit that left the window alone. A field emptied means the
configured default from now, as on a new pin. Where script runs, the field's text is
selected when the field takes focus while it is untouched, so one keystroke replaces
it. A maintenance entry's editor fills every field of its schedule the same way —
*Starts* above the end, a series' repeat, *Until*, *Not on* and its zone — and keeps
each exactly while it still reads what it was filled with
([ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
decisions 11 and 13). This holds for every editor of a pin, a node's and a line's,
wherever it opens.

A save that changes neither the note nor the expiry writes nothing. The pin keeps its
token and its authors: nobody is recorded as having changed it, and another editor of
it that is open elsewhere stays good. The token is asked first, so a form drawn from a
pin that has been written over since is refused whatever it says.

### 6. *Handled* is the same blocks

On *Handled*, at `/handled`, the page that lists what is handled (ADR-0135 decision 8),
the pins are grouped under each node's path, the whole node first and then its lines in
the check's order, each read and changed there. A block there stands away from what it
holds, so its sentence opens with that: *The whole node*, or the line itself, with a
link to the line on its node's page. Who pinned it and who last changed it stand
beneath the note for everyone, which a node's own page keeps in its editor. A change
comes back to the page with its node marked, and the node is named in the address's
query: a refused write is answered at the page's own address, where a way back that
differed only by its fragment would load nothing. The page is not refreshed, so nothing
waits.

A pin whose node is not reported
([ADR-0109](0109-a-node-says-its-children-are-complete.md) decision 4) — its check no
longer returns the node, or has not written it yet since a start — stands on the page
under its path, which is no link there. Its section says that the node is not reported
at present and that its pins hold nothing until it returns, and its block opens *The
whole node, when it is reported,* or *One of its lines, when it is reported,* since a
line's text went with the node. It is edited and cleared there as every pin is, and
neither makes a node.

### 7. A page that refreshes itself waits for an open editor

On a node's page an editor opens where its block stands, and on the wall a pin is
changed in the drawer over it (decision 4); the ten-second refresh skips while an editor
or the drawer is open
([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
decision 4): nothing is asked for, and an answer that was on its way is dropped. The
stamp keeps saying *updated …* as at rest, and keeps its width; what holds the page
says *updates paused*, muted, in its own head while the page waits for it — an editor
at the top of its form, the drawer under the node's name — so the pause is said where
its cause is. After a minute the page dims as one that lost its server does, all of it
but what is being edited, so a wall left with an editor open never reads as live.

When the editor closes, *updates paused* goes with it and the next refresh, at most ten
seconds on, brings the page up to date; a page that had dimmed is refreshed at once.
A close does not refresh the page by itself: a refresh takes the keyboard's focus with
it, and Cancel has just put that back on what opened the editor. A write that goes
through in the drawer brings the wall up to date at once as the drawer closes.

On the wall a block carries no pencil: it is the link that opens the drawer at it,
where its editor and *Clear* stand (decision 1); the head of a node's page shows *Edit*
and *Clear* always, in words. A write from a node's page comes back to the page as it
was asked for, with its filters and its depth, and one from the drawer leaves the wall
beneath where it was — its scroll, its open nodes and the box clicked (ADR-0147
decision 3). The pin dialog goes.

### 8. The block is a rule's, and maintenance is its first kind

Every rule at the contribution boundary (ADR-0032) owes the same thing a pin does: to
be visible where it acts and to name who or what set it. So the block's kind is data —
its mark, its tint and its buttons — and the head of a node's frame is a list, in which
a second rule on the same node is a second row: the rules stand as its rows beneath the
head's row, the pins above first, and the node's lines stand inside the frame with no
second border round them. A rule an admin set carries its buttons; one the
configuration declares carries none. Every block's edge is dashed, and only a rule that
paints its node fills its block, maintenance's with its tint (ADR-0135 decision 5); the
frame is a border, so both stand on a node of any color. The editor's text is called
the pin's *note* (ADR-0047 decision 1), which a check's reason lines are not.

*Seen*, a failure a person accepted as it stands, is a second kind of pin (ADR-0142
decision 6): the same block in its kind's words — *This node is marked seen by …*,
*Marked seen by …* — under the ringed check, with no fill, its *Edit* and *Clear*
posting to `POST /pins/seen`. *Silenced*, a failure that flaps, held until a deadline,
is a third
([ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
decision 9): *This node is silenced by ada, counting as* {ok} *until …*, its record
*Silenced by ada*, under a bell struck through. *Done*, an event looked into and over,
is a fourth, on a line alone
([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
decision 7): *This line is marked done by ada, closing* {error} *· until it reads
anything else*, its record *Marked done by ada*, under the ringed check. An
acknowledgment's *Edit* opens its block's editor with its kind chosen beside the others
its part takes — *Seen* where its part fails now, *Silence*, and *Done* wherever its
part takes one, a done's offering *Seen* and *Silence* — and saving another kind makes
the part that kind in one write (ADR-0144 decision 7, ADR-0146 decision 3). A rule the
configuration declares has its block too
([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) decision
10): its mark, §; its sentence — what it makes of its part, where, while fewer than its
count fail and how many do, by which rule; and, where it is stated whole, its note and
where it is configured — *Configured in config/aggregation.yaml since 2026-09-05* — and
no buttons, since it is changed in the configuration. On the wall it stands only while
it changes a count, its note behind the note mark; at the head of a node's frame and in
*Handled* it stands always, *changes nothing now* beside it where it does not act. What
a block states, the envelope lists: a pin is an item of its part's `handled`, beside
every configured rule its part's block states (ADR-0141 decision 3).

### 9. A maintenance entry's block says what holds now and what is planned

A maintenance entry is its schedule — one window, set ahead or now, or a series
([ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md))
— and its block says it so. A pin that holds says its window open's end in decision 1's
*until … · … left*. A series' window open is two rows: the window, with *Extend* and
*End now*, and its schedule, with *Edit* and *Clear*, each the browser's own disclosure
whose name says how far it reaches (ADR-0150 decision 15). An entry planned — a window
set ahead, or a series between two of its windows — holds nothing, and is a block of its
own under *Planned*, drawn without maintenance's tint: its sentence and when it starts,
and its *Edit* this record's editor with every field of its schedule filled (decision 5;
ADR-0150 decisions 9, 11 and 13). A one-off's *Clear* asks nothing, and a series' asks
first, in the browser's own disclosure, *Clear the schedule* and *Keep it*.

## Consequences

- **ADR-0014 decisions 6, 7, 9 and 16 are amended**: the expiry is filled in on an
  edit, the surfaces a pin is edited on are the block's, and a set that says what the
  stored pin says is no write, where every set rebuilt the entry.
- **So are ADR-0036 decisions 10 and 12**: *Handled* states a pin as a block under its
  node's path, and the line it silences and the pin's explanation stand in two places
  of that block, where they stood in two columns of a table.
- **And ADR-0005 decision 2**: the poll that keeps the dashboard current waits while
  an editor of a pin is open in what it would swap.
- **Three editors become one.** The card at the foot of a node's page, the panel over a
  line and the wall's dialog give way to the block's editor.
- **A wall with an editor or the drawer open does not refresh**, which is why decision
  7 says the pause where its cause is and dims a page held for a minute.
- **A pin's write keeps its fields**: `POST /pins/maintenance` takes those
  `POST /maintenance` took, with a schedule's beside them (ADR-0150 decision 13), and
  the form adds the one that says what the expiry field was filled with.
- **A refused write keeps the rule.** A form whose pin somebody changed meanwhile, and
  whose expiry field was left as filled, comes back filled from the pin as it now
  stands, so saving the admin's words from there keeps that expiry; where the pin is
  gone the field is a new pin's, empty. An expiry the admin typed stays theirs.
- **The explain view starts here.** The rows at the head of a node's frame are the
  rules acting on it, in one place.

## Alternatives considered

- **A blank expiry keeps the stored one on an edit**, as a blank note does: one rule
  for both fields, and a field that shows nothing of what it keeps. **Today's rule with
  a sentence beside the field**: the trap, labeled.
- **The expiry selected when Edit opens**: the first keystroke meant for the note
  replaces the expiry.
- **Every save rebuilding the pin**, as before an edit kept its expiry: *Save changes*
  on an editor nobody typed in names the saver as the pin's last author and refuses
  whoever else has it open.
- **The wall's dialog kept, or the dialog on every page**: the wall stays live while an
  editor is open, and a pin is edited in two ways, or in none of them in place. **The
  wall's mark as a link to the node's page**: no editor on the wall, and a page to load
  to silence a node for two hours.
- **The refresh going on around the card that is being edited**: a live wall, and a
  reconciliation of the page in script where a pause is a line.
- **A refresh the moment an editor closes**: a page up to date as soon as it can be,
  and the cursor taken from the mark that Cancel has just returned it to.
- **The expiry in one wording and nothing else**: the arithmetic gone, and the pin
  still stated twice with its buttons at the foot.
- **Set maintenance in words on every line**: a label on each control, and a column of
  the same two words down a node with 150 lines.
- **The stamp saying the pause**, *paused while editing*: words added to the stamp wrap
  the band at a laptop's width and move the editor just opened.

