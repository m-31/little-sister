# ADR-0142 — A failure marked seen counts as OK above until it changes

- **Status:** Accepted
- **Date:** 2026-10-25
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
  it)
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
carries, or a field the type names. ✓ is set only where a failure is, and a branch's is
expanded as it is set — one acknowledgment per failing part, sharing a note, each ending
by itself — so that a failure that arrives later is new and alarms. Every set, edit and
end is a row of its node, an end saying why. At the round's design pass, on 2026-10-25,
he settled that ✓ stands beside ‖ as a control of its own.

This record is *seen*, end to end; *silenced* and *done* come as kinds of the same pin
in records of their own. Whether a branch's ✓ came in the first build was left to the
split; it comes here, because most failures stand on lines — without it ✓ would stand
only on the few nodes that fail for themselves.

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
   it passes. Staleness is not accepted: a node marked seen whose reading goes stale
   counts as a warning above, as staleness escalates under every rule. It hides no
   reading, so History counts the true color its node showed, and a reading's row it
   kept from climbing names it, as damping's rows name theirs. It spends no failure
   budget unless its reading went stale, the healthy fold folds no node it stands on or
   beneath, and a chip counts its part by its true color, ◇ counting it besides as
   *2 seen*.

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
   through an improvement and through a restart. It ends at a **recovery**, its part
   reading OK or its check saying it is in maintenance; at a **worsening**, a failure
   worse than the one it was set at; at a **new occurrence** of a line's failure; when
   its part is **no longer reported** — a line gone from a reading of member lines, a
   node reading no status, removed or reaped; at **its end**, where it was given one —
   read as a pin's expiry is and within the same bounds, refused rather than bent
   (ADR-0014 decisions 13 and 14); and **by hand**. A reading whose lines are no members
   — a check's error, prose — says nothing of its lines and leaves their seens
   suspended, as it leaves their pins (ADR-0036 decision 6). One whose end passed while
   the instance was down ends at that time.

5. **✓ stands where something fails now, and a head's marks each failure at and beneath
   it.** The ringed check is offered on a part that fails now and nowhere else: not on a
   green part, nor one in maintenance — its own, a pin above, its check's word — nor one
   failing only because its reading went stale, nor one marked seen already. A line's
   stands in its rail just before its ‖, which keeps the line's end (ADR-0104 decision
   3); a node's after ‖ among its head's icons, the last of them — so that ‖ never moves
   as its part starts failing. On a head it marks every part that fails at and beneath
   the node as it stands — each failing line of a node whose lines are members, and each
   node failing for itself that has none — one seen each, sharing the note and the end,
   each bound to its own failure and ending by itself. Its editor carries the digest of
   the parts it named: a set that finds others failing there writes nothing and lists
   them as they stand, to be marked from there. On the wall ✓ is a link to the node's
   page carrying that digest and how many, which the script turns into the page's one
   editor cloned into the box, as ‖'s is (ADR-0104 decision 3); on a node's page the
   head keeps an editor of its own that lists the parts, which ✓ opens and which stands
   without script.

6. **Its block says who accepted what, and what ends it.** The block is ADR-0104's, in
   its kind's words: *This node is marked seen by ada at* {error} *· until it changes*,
   or *This line …*, with *or* its end *· 2 d left* where it was given one, and on the
   wall *Seen by ada at …*; its record *Marked seen by ada* and when, its note, *Edit*
   and *Clear*. A line marked seen carries the ringed check before its words. The
   editor's first sentence says what it marks — *Mark seen this line.*, *this node's own
   failure*, *the 3 failures here, each its own* — and then what the mark does.
   *Handled* lists them under *Accepted* — *2 seen on 2 nodes, the longest standing
   first* — each with the failure it accepted; the Copy document writes *☑️ Seen — by
   ada at error ⛔, until it changes*, and its list of what is handled *☑️ Accepted*.

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
   (ADR-0140).

8. **The envelope lists it.** A seen is an item of its part's `handled` (ADR-0141
   decision 3): kind `seen`, source `person`, `counts_as`
   `{"WARN": "OK", "ERROR": "OK"}`, `expires_at` null where it has no end, and besides
   `status`, the status it was set at, and `occurrence`, null where it is bound to the
   failing stretch. A node's `contribution` and an entry's say `seen`, with the OK
   counted and the seen's id as `rule`. It is part of 3.0.0, which has not shipped, so
   nothing moves its version.

## Consequences

- **ADR-0135** draws its second job's mark, the ringed check; **ADR-0104**'s block
  states a second kind, its control standing after ‖; **ADR-0107** has six causes more
  and a row's `ended`; **ADR-0082**'s line carries its occurrence; **ADR-0080**'s
  `handled` has a second kind of pin. Each says so.
- An admin's wall carries ✓ on every head where something fails: some 320 bytes and
  three elements a head on the recorded trees, whose paths are long — 1 % of an admin's
  fragment on the recorded wall, 14 % in a blackout — and on a phone a failing card's
  name has one square less beside it (`tests/test_wall_cost.py` says each).
- `little-sister-aws` names `occurrence="error.at"` on its function lines in a release
  of its own; until then their seens end at their next run. GitHub's run lines are told
  apart by their readings' identity, which they carry already.
- A branch whose failures are all seen reads OK, and the macOS client, which alarms off
  what its polled node shows, is quiet about it; a ✓ it does not draw is what ◇ and
  *Handled* say on the page.
- A head's ✓ on a wide outage marks many parts at once, each its own: they end one by
  one as their failures change, and *Handled* lists every one.

## Alternatives considered

- **A head's ✓ in a later build**, as the split had left it: ✓ would have stood on the
  few nodes that fail for themselves, most failures being lines.
- **One seen on a node whose lines fail, covering them**: one acknowledgment for several
  failures, ending only when every one changed, or at the first — the walk-through took
  each part its own.
- **Marking what still fails where the parts changed** since the editor listed them:
  something nobody was shown would be accepted, or something they were shown left out; a
  refusal that lists the parts as they stand costs one click more.
- **✓ before ‖**: ‖ would move each time its node started or stopped failing.
- **The parts listed in the wall's editor**: a list per failing head in every fragment
  the wall refreshes, where a digest and a count are a few bytes; the node's page lists
  them.
