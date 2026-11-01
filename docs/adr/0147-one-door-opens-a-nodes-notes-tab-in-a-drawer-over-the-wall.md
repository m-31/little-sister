# ADR-0147 — One door, ◇, opens a node's Notes tab in a drawer over the waiting wall

- **Status:** Accepted
- **Date:** 2026-10-31
- **Related:**
  [ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
  (the *Notes* tab, the place to act, which the drawer frames — decision 1 amended),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (the block, where a pin is
  set and where it is changed — decisions 1, 3, 4 and 7 amended),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (an open
  head's own buttons and the band — decisions 3 and 7 amended — and decision 11, a chip
  the button that opens its node),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (the block on the wall, its note's card, its pencil and its standing, and a card's pip
  — decisions 3, 4, 5 and 6 amended),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (✓,
  which the door replaces — decision 5 amended),
  [ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)
  (a handled part's mark, which becomes a door — decisions 2, 4 and 7 amended),
  [ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
  (✓'s one editor — decision 7 amended),
  [ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
  (✓ kept until the door — decision 3 amended),
  [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (*Write a note on this
  line* — decision 3 amended),
  [ADR-0056](0056-stable-useful-dashboard-flow.md) (*Maintenance visibility*, the card's
  pip — amended), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (decision
  2, the poll that waits — amended), [ADR-0019](0019-inspection-popover.md) (decision 6,
  the note's card on its machinery — amended),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (a pin above holds what is
  beneath it), [ADR-0048](0048-an-assembled-content-security-policy.md) (the policy, which lets a page
  frame its own origin),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) (a
  node's details, a name the switch leaves to them),
  [ADR-0036](0036-addressable-reasons.md) (decision 6, a line not reported now, which
  the one function holds), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (decision 1, the snapshot it reads, and the envelope that says what it says),
  [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 4, a pin held
  against its path and making no node, which the one function holds wherever that
  node is)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

On the wall a person acted through ‖ and ✓, on a head and on a node's lines, and through
their editors in the box — a pin's, and the ringed check's — which showed none of what a
node's *Notes* tab holds: what fails, what came before, what stands, and the form of
every kind
([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)).
The tab was made the place to act, and *done* was built as a kind of its form
([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)),
each keeping ✓ and the pencil until a door came. And a handled part said itself on the
wall at full length: a maintenance standing three months said who set it, until when and
why every day the wall was read, and on the demo the blocks took 226 pixels of the wall.

The round's design pass on history before a pin settled the door with Lex on 2026-10-31:
one control, ◇, in place of ‖ and ✓ wherever a person sets something — ◇ already said
*handled*, so the door and the count become one mark — plain where nothing is handled
and lit with its number where something is; on the wall it opens a drawer showing the
tab's panel over the wall, which waits while it is open, a link to the tab without
script and a sheet on a phone; a switch, *◇ details*, off by default, under which the
wall says only a handled part's color and mark; a block, and a mark, the button that
opens the drawer at its pin; and ◇ for everyone, whoever may set nothing reading. The
slice's own pass, with him the same day, one question at a time, settled what that left
open: how the drawer gets the panel and what a write in it does, how it holds the wall
and words not yet sent, what ◇'s number counts, a handled line's door, and what the
block is.

## Decision

1. **One door, ◇, in place of ‖ and ✓.** On every open head — a card's and a box's on
   the wall, the head of a node's page and its card at `depth=0` — the ringed diamond
   stands among the head's own buttons where ‖ and ✓ stood
   ([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision
   3), for everyone: whoever may set nothing reads what it opens. **Under the looks whose
   toolbar shows only under the pointer** — `pointer`, the library's, and `pointer-name`
   ([ADR-0029](0029-per-user-presentation-preferences.md)) — a lit ◇ stands instead at the
   start of the head's state, where a card's pip stood, at rest and under the pointer
   alike, a door there as whatever says handled is (decision 7), and the toolbar carries
   no second while it is lit; a plain ◇, which says nothing at rest, stays among the
   buttons and shows with them. So nothing shows twice, nothing moves as the pointer
   reaches it, and the toolbar shows all of itself or nothing. The kiosk, which draws
   no controls, shows ◇ as a mark, lit with its number, no button; the root, which has no
   *Notes* tab, has none. **A closed chip has no door**: it is itself the button that
   opens and closes its node (ADR-0127 decision 11), and a door inside it would be a button in a
   button, so its ◇ stays a count beside its counts. On a node's page each line has one
   seat at its end: a plain ◇ where nothing handles the line, for whoever may set
   something on it — a member line, as ‖ stood — and where something does, the mark of
   what handles it, which is its door (decision 7), as the mark stood where the button
   that set it stood
   ([ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)
   decision 7). The wall's lines carry no ◇: their marks are their doors. What stood
   behind ‖ and ✓ goes — the page's one editor of each, cloned into a box; the head's own
   *Set maintenance* and *Mark seen or silence*; a line's two disclosures, and with the
   line's ‖ its *Write a note on this line*
   ([ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) decision 3). A new act
   is set on the tab's form, and a standing one is changed where its block stands
   ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) decision 4).

2. **◇ is lit with the number of parts behind it.** Its number is the number of parts
   its drawer lists under *what stands* for its node — the node itself, its lines, a
   line it does not report now among them, and everything beneath it, a node not
   reported now among it — each part once, whatever handles it: a pin, an
   acknowledgment, or a configured rule while it changes what the part counts as.
   **Time decides what stands, and whether its part is reported now does not**: a pin
   stands from the start of its window to its end, an acknowledgment from its set until
   it ends, holding what of its part is reported and nothing while none is. The
   pins set above the node are not its number: they stand in its drawer, so that a
   reader sees why the node is blue, and are counted on the door of the node they stand
   on. **A maintenance entry planned is no part behind ◇**: a window set ahead, or a
   series between two of its windows, holds nothing, and the tab lists it in a section
   of its own beneath *what stands*, *Planned*, with its own count
   ([ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
   decision 9). Where nothing stands at or beneath, ◇ is plain. One function gives the drawer its
   list and the door its number, in every state, read before a filter takes anything
   away, as the band's pill is: *what stands* answers what is handled here, which a
   branch in maintenance, idle or undefined has as much as any other, so the tab lists
   what stands beneath such a branch too (ADR-0145 decision 1). It reads the snapshot
   alone, which carries a line its node does not report now beside the node's lines and
   never among them — a finding that comes and goes, its pin or a silence holding nothing
   until it is back (ADR-0036 decision 6) — and a node not reported now beside the
   nearest node above it that stands and never among that node's children — its check
   no longer returns it, or has not written it since the start, and what stands on it
   is held against its path (ADR-0109 decision 4) — so that the door, the drawer,
   *Handled* and the band's pill count and list what stands from one place, at one
   moment. *Not reported now* holds for a node removed and for one not yet written
   alike. Its words
   are its tooltip and its accessible name, each job's count in them, in a chip's form — *3
   handled: 1 line in maintenance, 2 seen* — and the tab says the same number over what
   stands, *3 handled*, the node's own parts and its lines' with what is beneath, what
   stands' own grouping saying where each part is. **Three
   counts of what is handled stand on the wall, and differ on purpose**: a closed chip's
   ◇ counts what its counts do not show as such, standing beside them
   ([ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
   decision 6); the pill counts every rule that stands, whether or not its part is
   reported now, an index of the whole; the door
   counts the parts behind it, what opening it shows. A card's pip goes: the door on its
   head is its count and its way in.

3. **◇ opens the drawer: the node's *Notes* tab, framed over the wall.** The tab has a
   panel mode — the same page and template without the site's header, the band and the
   poll, its links leaving the frame and its forms staying in it — and the drawer is a
   frame of it in a dialog whose head the wall draws: the node's name and its state as
   the box clicked says them, ✕, and links to the node's page and to its tab. The node's
   actions stay on its head. One load per opening; the content security policy lets a
   page frame its own origin already
   ([ADR-0048](0048-an-assembled-content-security-policy.md)). Opened from a head, the panel opens at
   its top; from a line, its form on that line; from a block or a mark, at that pin, its
   block's editor open for whoever may change it. **A write from the drawer is a write
   from the tab** — its refusals and its kind's conflict page included, the words kept,
   framed — and nothing is parsed or posted by script, so the wall beneath never
   reloads: its scroll, its open nodes and the box clicked are where they were. A write
   that goes through closes the drawer and brings the wall up to date at once; a refused
   one stays in the drawer with why and the words; and a set that plans a window, which
   the wall shows nothing of, is answered at the tab, at its new block, which the
   drawer shows and focuses, its sentence read at once with *Edit* beside it
   ([ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
   decision 11). The drawer closes on a write — the
   frame landing at the address its form's `next` named, after a submit from it — and
   never on an opening; a submit whose button opens another tab, a package's draft of
   a ticket, writes nothing in the frame and names nothing
   ([ADR-0148](0148-a-ticket-is-drafted-from-a-notes-words-by-the-package-that-fills-its-slot.md) decision 7),
   nor does a maintenance editor's own button — *Preview*, *Add an interval*, an ×,
   *weekend*, *working week* — whose answer is the editor back, drawn as a refusal is,
   while *Extend* and *End now* are writes as any other
   ([ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
   decisions 13 and 15). Without script ◇, a block and a mark are links to the tab — a
   line's with `?reason=<slug>`, a pin's at that pin — where every act works without
   script. ◇ opens the drawer on a node's page as on the wall, the boxes beneath its head
   being a wall of their own (ADR-0135 decision 3); a leaf's page, which is not
   refreshed, has nothing to hold.

4. **The drawer holds the wall.** It is modal: the wall inert behind a backdrop light
   enough to read it, the box clicked lit in it. The wall waits while the drawer is
   open, as it waits for an editor open in the grid — one test in the refresh, its
   dimming after a minute as it is
   ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) decision 2, ADR-0104
   decision 7). **The pause is said where its cause is, and the stamp keeps its
   width**, for the drawer and for an editor alike: the stamp says *updated …* as it
   does at rest, and what holds the page says *updates paused*, muted, in its own head
   — the drawer under the node's name, an editor at the top of its form — while it
   holds it, on a page the refresh pauses; a leaf's page, which nothing refreshes,
   says it nowhere. The drawer is the reason, and in front of the reader; what the
   reader cannot see is that the page behind has stopped. Words added to the stamp
   wrapped the band at a laptop's width and moved the wall beneath the shade, and an
   editor just opened with it, and where the drawer stands at the left it covers the
   stamp. At a desk the drawer stands at the right, 480 pixels wide, and nothing
   reflows beneath it; where the box clicked would sit under it, it stands at the left.
   On a phone it is a sheet from the foot, and the wall scrolls the box clicked into the
   strip above it. ✕, Escape and a click on the wall — on a phone a tap on the strip —
   close it, each through decision 5's question. The focus goes into the frame as it
   opens, to the note of the form or of the block's editor it opens at, and back to what
   opened it as it closes; Escape is read in the frame.

5. **A close asks before it drops what was written.** Where a field of the frame's form
   differs from how it opened — words typed, an end, a level or a deadline changed, a
   repeat's day ticked — or the frame holds words a refused write or a preview gave
   back, or a maintenance editor's windows added by hand changed in place, a close
   asks in the drawer, *Discard what you wrote?*, with *Discard* and *Keep
   writing*, *Keep writing* focused; Escape on the question keeps writing, and a link
   from the drawer that would leave the page asks the same. Nothing is asked where the
   form is as it opened or after a write has gone through, and nothing is kept in the
   browser.

6. ***◇ details*, off by default.** A switch in the band beside *hide ok* and *hide idle*
   (ADR-0127 decision 7), its tooltip *Show who handles a part, until when and why, on
   the wall*, which a browser keeps in a cookie as it keeps them, and whose default the
   deployment gives in `settings.yaml`, off in the library; the kiosk, which has no
   band, follows the default. One name serves the default, the cookie and the query
   parameter, `handled_details`: `details` alone names a node's details
   ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)).
   Off, no block stands on the wall — a person's or a
   configured rule's — and the server leaves them out of what it draws: a handled part
   says its color and its mark, a head's mark, a line's mark and rail, ◇ and its number,
   a closed chip's ◇ and count and the band's pill. On, every block stands where it
   stands (ADR-0135 decision 5). A node's own head, its card at `depth=0` and *Handled*
   state their blocks whole either way, with *Edit* and *Clear* for whoever may: the
   overview's card at `depth=0` is the root's own head, and the one place a pin on the
   root is changed. The boxes a node's page draws beneath its head follow the switch.
   It hides nothing that counts — a handled part's color and mark stay — and no node
   has a switch of its own: ◇ is the local one.

7. **Whatever says handled opens the drawer at it.** A block on the wall is one link to
   the *Notes* tab of the node its pin stands on, opened at that pin — the drawer with
   script, the tab without — its sentence its name, so that what a screen reader hears
   is what the block says and what a click opens is what it describes; it ends in a
   chevron, and takes the focus ring every link takes. The source of a pin set above is
   named in it and not linked: the drawer it opens is that node's, whose head names it
   and links to its page. A configured rule's block opens at its block under *what
   stands*. A line's mark — on the wall, and on a node's page in its line's seat or, for
   a reader without one, at its top right — and a head's mark beside its state open the
   drawer at what they mark, whichever way *◇ details* is set. The block's note mark and
   its pencil go: a note is read in the drawer, where the block's editor and *Clear*
   stand, and the note's card goes with the mark (ADR-0135 decisions 3 and 4,
   [ADR-0019](0019-inspection-popover.md) decision 6). On the kiosk blocks and marks stay
   plain.

## Consequences

- **ADR-0104** decisions 1, 3, 4 and 7 are amended — a block on the wall is a link
  without buttons, a new pin is set on the tab, a standing one changed in its block's
  editor in the drawer, and the refresh waits for the drawer as for an editor; so are
  **ADR-0127** decisions 3 and 7, ◇ among a head's buttons and *◇ details* in the band;
  **ADR-0135** decisions 3 to 6, the block's note and pencil, its standing on the wall
  and the card's pip; **ADR-0142** decision 5, **ADR-0144** decision 7 and **ADR-0146**
  decision 3, ✓ and its editor; **ADR-0143** decisions 2, 4 and 7, a mark that opens the
  drawer, a line's in its one seat; **ADR-0140** decision 3, a line's *Write a note on
  this line*; **ADR-0145** decision 1, *what stands* beneath in every state; **ADR-0056**'s
  *Maintenance visibility*, the pip; **ADR-0005** decision 2, the wait, and where it is
  said — no longer in the stamp, for an editor either; and **ADR-0019** decision 6, the
  note's card. Each says so.
- **Nothing counts differently**: the healthy fold, a chip's counts and the failure
  budget read what they read, and *◇ details* off takes blocks off the wall, never a
  color or a mark, a line not reported now is never among a node's lines, and a node
  not reported now never among its parent's children. The envelope lists such a line
  beside its node's entries, `entries.not_reported`, and such a node beside the
  nearest node above it that stands, `nodes_not_reported`, since the snapshot carries
  them
  ([ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  decision 3, [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1):
  a field of 3.1.0, which the macOS client does not read.
- **A pin set from the wall is a click further than ‖ was**: the door, then the kind —
  maintenance never the kind the form opens on — which is the point, ‖ having been the
  quickest way to paint a red box blue.
- **Every head carries ◇ for every reader**, and a fragment a door per head; with *◇
  details* off it carries no block. A drawer is one page load, the tab's, when it opens.
- **The demo deployment gets a recipe** (`testing-the-gui.md`, Mode 2): the door on a
  head and on a line, the drawer at a desk and on a phone, a write and a refusal in it,
  the question before a close, the switch, and the block as the button.

## Alternatives considered

- **◇ on the wall alone**, a node's page keeping ‖ and ✓ on its lines — two ways in —
  **or ‖ and ✓ as they were**, ‖ on every head the quickest way to paint a red box blue,
  the habit the acknowledgments were made to replace.
- **The *Notes* tab alone**, every act on the wall a page load away; **or a new browser
  tab**, one left behind for every act.
- **The panel injected as a fragment and its forms posted by script**, which rebuilds the
  tab's navigation — every refusal, the conflict page, the scripts its form needs on new
  content — to show what a frame shows for nothing; **or the page fetched and its writes
  posted as the tab posts them**, the wall reloaded at its top after every act.
- **A drawer beside a wall that can still be clicked**: the paused wall's own buttons
  changing what is drawn while nothing refreshes, another box's ◇ replacing the drawer
  under the words being written, and focus, Escape and what a screen reader is told built
  by hand.
- **Words not yet sent kept as a draft**, a sentence written for one failure turning up
  days later in a form opened on another; **or dropped without a word**, a note written
  at three in the morning lost to a stray Escape.
- **The door counting as a closed chip does**, what its counts do not show — an open head
  has no counts, so a branch whose one handled part is a pinned leaf would show a plain
  door over a drawer that lists the pin; **or as the pip did**, without the node's own
  blocks, which *◇ details* off takes off the wall.
- **A lit ◇ beside a handled line's mark**, its number always one, two glyphs for one
  fact; **or ◇ beside the mark on every line one may act on**, two glyphs on every handled
  line and a ◇ on a page's lines that the wall's do not have.
- **A link stretched over a block from its mark**, two targets and the mark's words for a
  name; **the mark alone a link**, the small target; **or the pencil kept**, shown only
  while the pointer is over its card.
- **No switch**, the blocks never on the wall, which takes away what somebody who has not
  seen a pin wants to read; **or the switch on by default**, today's wall until somebody
  turns it off.
- **The stamp saying the pause** — *paused while the notes are open* for the drawer, as
  *paused while editing* said it for an editor — which wrapped the band below 1600
  pixels and dropped the wall by as much as 67 under the shade as the drawer opened, an
  editor just opened moving with it, and stood under the drawer where it opens at the
  left; **or the time in the drawer's head**, which the stamp keeps.

