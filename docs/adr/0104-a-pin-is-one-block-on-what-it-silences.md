# ADR-0104 — A pin is one block on what it silences, and it is edited there

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0014](0014-maintenance-persistence.md) (the pin, its expiry, its
  compare-and-set token and its editor — decisions 6, 7, 9, 13 and 16 to 18, which
  this amends), [ADR-0036](0036-addressable-reasons.md) (a pin on one line, and how
  `/maintenance` lists pins — decisions 10 and 12, which this amends),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 5: a transformed contribution is
  visible and attributable), [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (a
  pin is a rule in the snapshot), [ADR-0047](0047-node-notes-and-their-retention.md)
  (a pin's text is its note), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (the refresh and the stamp that dates the page),
  [ADR-0056](0056-stable-useful-dashboard-flow.md) (the wall's cards),
  [ADR-0006](0006-config-file-and-timezones.md) (the configured timezone),
  [ADR-0019](0019-inspection-popover.md) (the inspection card a node's row answers to),
  [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 4: a pin whose
  node is not reported)
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

## Decision

### 1. One block states a pin, wherever a pin shows

Who silenced it, until when and how long is left, and its note in full; for an admin,
*Edit* and *Clear*. The same block stands on a node's page, under a line, on the
Maintenance page and in a card. The expiry reads one way in all of them, the instant and
what is left: *until 2026-10-03 20:44:28 · 1d 23h left*. Where the sentence wraps, as it
does in a narrow card, no line ends inside a word of an instant: the date and the time
of day each stay whole. A viewer sees the block without its buttons, and with the note
whole, which the strip cut off.

### 2. Where the block stands says what it covers

A node's block stands at the top of its status card and frames every line beneath it.
A line's block hangs beneath that line; where the node is pinned too, it says *also
silenced on its own*, because the line stays quiet when the node's pin ends. On a
branch's page the block stands in the node's head, above the children it covers, and
on the wall in the card: under the card's head and above its lines and the boxes it
covers, its sentence opening *Silenced by*, since the card's head names the node. A
box inside a card states its own pin the same way.

### 3. A pin is set where its block will stand

A node's control is one labeled button on its status line, *Set maintenance*. A line's
is a pause mark at the line's end, in the rail it shares with the line's other actions.
Each opens its editor where the block will stand, and the editor's first sentence says
what it covers: *this node, all 6 lines and any that appear*, or *this line only, the
other 5 keep alarming*.

On the wall an unpinned card's head carries an admin's pause mark, which opens the
editor in the card: *Maintenance for hemulen and everything beneath it*, said of the
tree as it is and not of what a filter left on the page. A pinned card has no mark,
and a box inside a card has none either: it is pinned from its own page. On a branch's
page the control is *Set maintenance* in the head, so an admin's page of a branch has
a head even where the node has nothing of its own to say. The overview's own card
sets no pin, because silencing everything is not done from a form; a pin that stands
there is stated and changed like any other. The card at the foot of a node's page
goes.

A node's row on the wall and a branch's head also answer to the inspection card
(ADR-0019), and a pin's own controls in them are not that card's to answer: the mark,
the block and an editor. A row with an editor open in it raises no card at all. The
control that opened the editor has given way to it, so the pointer that clicked is left
on the row, and the row's card would stand over the one above while the note is typed.

### 4. Edit opens the block where it stands

*Edit* turns the note into its Markdown source in a field, with the expiry, *Save
changes* and *Cancel*; who pinned it and when stands at the top of the editor. A line's
editor opens beneath its line, where it floated over the lines. The disclosure is the
browser's own, so every editor works without script, and pinned stays a read state
(ADR-0014 decision 16). Where script runs, the editor opens in its note, at the note's
end.

A write comes back to where its block stands. From a node's own page that is the top
of the page for the node's pin, and for a line's the line itself: its set, its edit and
its clear return to the address that names a line, `?reason=<slug>#pinned-reason`
(ADR-0036 decision 12), because on a node of 150 lines the top of the page is a long
way from the line that was just pinned.

### 5. An edit shows the expiry it would keep

On an edit the expiry field holds the stored expiry, a date and time in the configured
timezone as the field reads one. The form carries what the field was filled with, and a
field that still says it keeps the stored instant exactly: it is not read again, so the
floor a typed expiry is held to (ADR-0014 decision 13) and the hour a clock change
repeats cannot refuse an edit that left the window alone. A field emptied means the
configured default from now, as on a new pin. Where script runs, the field's text is
selected when the field takes focus while it is untouched, so one keystroke replaces
it. This holds for every editor of a pin: a node's, a line's and a card's.

A save that changes neither the note nor the expiry writes nothing. The pin keeps its
token and its authors: nobody is recorded as having changed it, and another editor of
it that is open elsewhere stays good. The token is asked first, so a form drawn from a
pin that has been written over since is refused whatever it says.

### 6. The Maintenance page is the same blocks

Grouped under each node's path, the whole node first and then its lines in the check's
order, each read and changed there. A block there stands away from what it silences, so
its sentence opens with that: *The whole node*, or the line itself, with a link to the
line on its node's page. Who pinned it and who last changed it stand beneath the note
for everyone, which a node's own page keeps in its editor. A change comes back to the
page with its node marked, and the node is named in the address's query: a refused
write is answered at the page's own address, where a way back that differed only by
its fragment would load nothing. The page is not refreshed, so nothing waits.

A pin whose node is not reported
([ADR-0109](0109-a-node-says-its-children-are-complete.md) decision 4) — its check no
longer returns the node, or has not written it yet since a start — stands on the page
under its path, which is no link there. Its section says that the node is not reported
at present and that its pins silence nothing until it returns, and its block opens *The
whole node, when it is reported,* or *One of its lines, when it is reported,* since a
line's text went with the node. It is edited and cleared there as every pin is, and
neither makes a node.

### 7. A page that refreshes itself waits for an open editor

On the wall and on a branch's page the editor opens in the card or in the head, and
the ten-second refresh skips while one is open: nothing is asked for, and an answer
that was on its way is dropped. The stamp says *paused while editing* at once, and
after a minute the page dims as one that lost its server does, all of it but the card
or the head being edited, so a wall left with an editor open never reads as live.

When the editor closes, the stamp drops the words and the next refresh, at most ten
seconds on, brings the page up to date; a page that had dimmed is refreshed at once.
A close does not refresh the page by itself: a refresh takes the keyboard's focus with
it, and Cancel has just put that back on what opened the editor.

On a card, *Edit* and *Clear* show on hover or keyboard focus, as the pause mark
does; a branch's head shows them always. A write from either comes back to the page
as it was asked for, with its filters and its depth. The pin dialog goes.

### 8. The block is a rule's, and maintenance is its first kind

Every rule at the contribution boundary (ADR-0032) owes the same thing a pin does: to
be visible where it acts and to name who or what set it. So the block's kind is data —
its mark, its tint and its buttons — and the head of a node's frame is a list, in which
a second rule on the same node is a second row. A rule an admin set carries its
buttons; one the configuration declares carries none. The block paints its own tint and
the frame is a border, so both stand on a node of any color. The editor's text is
called the pin's *note* (ADR-0047 decision 1), which a check's reason lines are not.

## Consequences

- **ADR-0014 decisions 6, 7, 9 and 16 are amended**: the expiry is filled in on an
  edit, the surfaces a pin is edited on are the block's, and a set that says what the
  stored pin says is no write, where every set rebuilt the entry.
- **So are ADR-0036 decisions 10 and 12**: `/maintenance` states a pin as a block
  under its node's path, and the line it silences and the pin's explanation stand in
  two places of that block, where they stood in two columns of a table.
- **And ADR-0005 decision 2**: the poll that keeps the dashboard current waits while
  an editor of a pin is open in what it would swap.
- **Three editors become one.** The card at the foot of a node's page, the panel over a
  line and the wall's dialog give way to the block's editor.
- **A wall with an editor open does not refresh**, which is why decision 7 makes the
  pause loud rather than quiet.
- **Nothing moves on the envelope**, and `POST /maintenance` keeps its fields; the form
  adds the one that says what the expiry field was filled with.
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

