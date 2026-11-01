# ADR-0142 — A failure marked seen counts as OK above until it changes

- **Status:** Accepted
- **Date:** 2026-11-01 (accepted 2026-10-25)
- **Related:**
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (the pin, of which *seen* is a kind, its file, its permission and the envelope's
  list),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (the true color, the ringed check, ◇ and *Handled* — amended),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (the block and where its
  control stands — amended), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (the envelope — amended),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (a row's cause —
  amended), [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md) (what a
  line carries — amended), [ADR-0126](0126-a-line-is-a-template-over-its-record.md)
  (`Check.line`, which carries the occurrence),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (a reading's identity),
  [ADR-0014](0014-maintenance-persistence.md) (the compare-and-set write, an end's
  bounds), [ADR-0036](0036-addressable-reasons.md) (a line's pin, and its address),
  [ADR-0032](0032-status-contribution-boundary.md) (the contribution boundary),
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (damping, which a seen counts
  over), [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (a
  configured rule, which counts after it),
  [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (its note, which enters
  the notes), [ADR-0077](0077-authority-follows-the-lease.md) (a takeover, which adopts
  it), [ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)
  (how a handled part looks — decisions 5 and 6 amended),
  [ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
  (*silenced*, which shares ✓'s editor — decisions 2, 4 and 5 amended),
  [ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
  (*seen* offered on the *Notes* tab —
  amended),
  [ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
  (*done*, which a seen's pencil makes it — amended),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md) (the door, ◇, which takes the ringed check's place as the control — decision 5 amended)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A failing part a person has looked into still alarms: its branch stays red until the
part recovers, so a disk at 92 % whose replacement is on order reddens the wall for a
week, and every other failure under that branch comes to nobody's notice. Maintenance
does not fit — the disk is not down on purpose, and a blue node reads nothing — and a
pin that ends by the clock either ends before the disk is swapped or holds through a
worsening nobody would have accepted.

When the maintenance-and-aggregation round was walked through, Lex settled what an
acknowledgment is: four kinds a person sets — *done* for an event that is over, *seen*
for a state accepted until it changes, *silenced* for a thing that flaps, and
maintenance — each a pin with a kind
([ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)).
*Seen* keeps its part's true color under a ringed check and counts as OK above; it ends
by itself at a recovery, at a worsening, at an optional time and when what it is on is
no longer reported, and holds through an improvement and a restart. What tells one
occurrence from the next is the library's failing stretch, the identity a reading
carries, or a field the type names. A seen is set only where a failure is, and a
branch's is expanded as it is set — one acknowledgment per failing part, sharing a note,
each ending by itself — so that a failure that arrives later is new and alarms. Every
set, edit and end is a row of its node, an end saying why.

This record is *seen*, end to end; *silenced* and *done* come as kinds of the same pin
in records of their own. Whether a branch's seen came in the first build was left to the
split; it comes here, because most failures stand on lines — without it a head could
mark seen only a node that fails for itself.

## Decision

1. **A failure accepted as it stands is a pin of the kind `seen`.** It stands on a
   node's own failure or on one of its lines, in `pins.json` beside the maintenance
   pins: one person's acceptance on a part at a time, beside any maintenance. Besides
   what every pin has — its note, who set it and when, who first did, its id — it keeps
   the status its part read when it was set and the occurrence it is bound to, and an
   end only where one was given; the file leaves out what it does not have. Two on one
   place refuse the file, as two maintenance pins do. It is set, changed and ended at
   `POST /pins/seen`, under the permission `seen` (ADR-0141 decision 4), a
   compare-and-set write as a pin's is (ADR-0014 decision 8), whose refusals keep the
   person's words.

2. **A part marked seen keeps its true color and counts as OK above it.** A line marked
   seen shows what it reads and counts as OK in its node's own status — over what a
   configured rule on the node's lines makes of it, while a pinned line stays its pin's
   — so a node whose failing lines are all seen reads OK. A node's own failure marked
   seen keeps the node's color, and its own part counts as OK in what it passes up, its
   children counted as ever: the node's `contribution` says `seen`, its `rule` the seen.
   A seen counts over damping's held status, and never over maintenance, a shield or a
   node not yet reported; a configured rule at the node's top counts after it, from what
   it passes, and one that counts how many of a node's children fail counts a seen child
   toward that count as it reads, the child itself still counting as OK. Staleness is
   not accepted: a node marked seen whose reading goes stale counts as a warning above,
   as staleness escalates under every rule. It hides no reading, so History counts the
   true color its node showed, and a reading's row it kept from climbing names it, as
   damping's rows name theirs. It spends no failure budget unless its reading went
   stale, the healthy fold folds no node it stands on or beneath, and a chip counts its
   part by its true color, ◇ counting it besides as *2 seen*.

3. **It is bound to the failure it accepted: the status it was set at and the
   occurrence.** A line's occurrence is what tells its failure from the next: the record
   field its type names as `occurrence=` on `Check.__init__` — one the type declares in
   `line_fields`, which a name it does not declare refuses with `CheckError` when the
   check is built — and otherwise the identity of the reading the line was written from,
   which `Check.line` carries onto the line where only the series read it before
   (ADR-0087); where neither is there, the failing stretch the line stands in. A value
   that is no text is kept as its JSON, and one too long for a line as its digest. A
   node's own failure is bound to its failing stretch.

4. **It ends by itself as what it accepted changes, and every end says why.** It holds
   through an improvement and through every restart. It ends at a **recovery**, its part
   reading OK or its check saying it is in maintenance; at a **worsening**, a failure
   worse than the one it was set at; at a **new occurrence** of a line's failure; when
   its part is **no longer reported** — a line gone from a reading of member lines, a
   node reading no status, removed or reaped; at **its end**, where it was given one —
   read as a pin's expiry is and within the same bounds, refused rather than bent
   (ADR-0014 decisions 13 and 14); and **by hand**. A reading whose lines are no members
   — a check's error, prose — says nothing of its lines and leaves their seens
   suspended, as it leaves their pins (ADR-0036 decision 6). One whose end passed while
   the instance was down ends at that time. Where a line's next run passes, a seen on it
   ends *recovered*, where a done ends at *a new occurrence*
   ([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)).

5. ***Seen* is offered where something fails now, and a head's act marks each failure
   at and beneath it.** A new seen is set on the node's *Notes* tab, in the drawer the
   door, ◇, opens over the wall
   ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
   decision 1), *Seen* a kind of the tab's form
   ([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
   decision 2). It is offered on a part that fails now and nowhere else: not on a green
   part, nor one in maintenance — its own, a pin above, its check's word — nor one
   failing only because its reading went stale, nor one marked seen already. Its *On*
   offers a failing line, or the head's act, which marks every part that fails at and
   beneath the node as it stands — each failing line of a node whose lines are members,
   and each node failing for itself that has none — one seen each, sharing the note and
   the end, each bound to its own failure and ending by itself. The form lists those
   parts and carries their digest: a set that finds others failing there writes nothing
   and lists them as they stand, to be marked from there, and a set refused for its
   words carries the digest back, so that what is sent again marks what was shown.

6. **Its block says who accepted what, and what ends it.** The block is ADR-0104's, in
   its kind's words: *This node is marked seen by ada at* {error} *· until it changes*,
   or *This line …*, with *or* its end *· 2 d left* where it was given one, and on the
   wall *Seen by ada at …*; its record *Marked seen by ada* and when, its note, *Edit*
   and *Clear*. A standing seen is changed in its block's editor — on a node's page, on
   *Handled*, and from the wall in the drawer, opened at it — which offers the other
   kinds its part takes: *Silence*, and *Done* where its part takes one, a line whose
   failure has an occurrence of its own and fails now. Saving one ends the seen, *made
   a silence* or *made done*, as the other is set in its place, in one write
   ([ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
   decision 7,
   [ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
   decision 3), and a done's editor makes it seen. Its mark is the ringed check
   ([ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)
   decisions 2, 3, 4 and 7). A line marked seen carries it at its top right — on a
   node's page in its line's seat at its end, for the reader who has one — in OK's
   green, beside a green rail down its right edge. A node marked seen carries it beside
   its head's state, on its own tint, and its box the rail where the node counts as OK
   — none where a failure beneath it still climbs. Wherever it stands the mark opens the
   drawer at the seen (ADR-0147 decision 7). *Handled* lists them under *Accepted* —
   *2 seen on 2 nodes, the longest standing first* — each with the failure it accepted;
   the Copy document writes *☑️ Seen — by ada at error ⛔, until it changes*, and its
   list of what is handled *☑️ Accepted*.

7. **Every set, edit and end is a row of its node, and an end's row says why.** The
   causes are `seen-set`, `seen-edited` and `seen-ended`, and for a line
   `line-seen-set`, `line-seen-edited` and `line-seen-ended`; an end's row carries
   `ended`, one of `recovery`, `worsening`, `occurrence`, `gone`, `clock` and `hand`. A
   node's own seen changes nothing its node shows, so its rows go from what the node
   shows to the same; a line's go from what its node showed to what it shows. The Events
   page's chips say *seen*, *seen changed* and *seen ended* with why — *recovered*,
   *worse*, *a new occurrence*, *no longer reported*, *at its end*, *by hand* — and
   *line seen*, *line's seen changed* and *line's seen ended*; History's *what moved it*
   says *marked seen*, *a seen changed*, *no longer seen* and their lines' forms, and
   the Time card *when a line was marked seen*. The Events page's *pins* switch takes
   them, a seen being a pin. A seen's note enters its node's notes as it is set
   (ADR-0140), and records the status it was set at, and when, why and by whom it ended
   ([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
   decision 4).

8. **The envelope lists it.** A seen is an item of its part's `handled` (ADR-0141
   decision 3): kind `seen`, source `person`, `counts_as`
   `{"WARN": "OK", "ERROR": "OK"}`, `expires_at` null where it has no end, and besides
   `status`, the status it was set at, and `occurrence`, null where it is bound to the
   failing stretch. A node's `contribution` and an entry's say `seen`, with the OK
   counted and the seen's id as `rule`. It is part of 3.0.0, so nothing moves its
   version.

## Consequences

- **ADR-0135** draws its second job's mark, the ringed check; **ADR-0104**'s block
  states a second kind; **ADR-0107** has six causes more and a row's `ended`;
  **ADR-0082**'s line carries its occurrence; **ADR-0080**'s `handled` has a second
  kind of pin. Each says so.
- The wall carries no control of a seen's own: a seen is set through the door every
  head carries for every reader, whose cost `tests/test_wall_cost.py` says
  ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)).
- `little-sister-aws` writes its function line from the function's own reading, which
  carries no identity, so a seen there is bound to its failing stretch — holding through
  a new error inside it and ending at a recovery or a worsening. The package names
  `occurrence="error.at"` in a release of its own, and a seen there then ends when a
  newer error takes the line. GitHub's run lines are told apart by their readings'
  identity, which they carry already.
- A branch whose failures are all seen reads OK, and the macOS client, which alarms off
  what its polled node shows, is quiet about it; a ✓ it does not draw is what ◇ and
  *Handled* say on the page.
- The head's act on a wide outage marks many parts at once, each its own: they end one
  by one as their failures change, and *Handled* lists every one.

## Alternatives considered

- **The head's act in a later build**, as the split had left it: a head could have
  marked seen only a node that fails for itself, most failures being lines.
- **One seen on a node whose lines fail, covering them**: one acknowledgment for several
  failures, ending only when every one changed, or at the first — the walk-through took
  each part its own.
- **Marking what still fails where the parts changed** since the form listed them:
  something nobody was shown would be accepted, or something they were shown left out; a
  refusal that lists the parts as they stand costs one click more.
