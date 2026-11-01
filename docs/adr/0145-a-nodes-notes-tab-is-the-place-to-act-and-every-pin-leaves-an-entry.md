# ADR-0145 — A node's Notes tab is the place to act, and every pin leaves an entry that says how it ended

- **Status:** Accepted
- **Date:** 2026-11-01 (accepted 2026-10-31)
- **Related:** [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (the
  *Notes* tab, a pin's note, the Copy document's newest note and the retention —
  amended), [ADR-0047](0047-node-notes-and-their-retention.md) (the notes — decisions 5
  and 9 amended),
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (a permission per act — decision 4 amended),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
  (*seen*, which the tab's form offers — amended),
  [ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
  (*silenced*, which the tab's form offers — amended),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (the rows of a pin —
  decisions 1 and 3 amended), [ADR-0036](0036-addressable-reasons.md) (decision 11, a
  line's pin in the log — amended),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (decision 4, a pin changed
  where its block stands, which the tab keeps),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (decision 7, a branch's *why* card, which lists what is handled beneath a branch, as
  the tab does in every state),
  [ADR-0014](0014-maintenance-persistence.md) (the placeholder a pin without words
  holds), [ADR-0077](0077-authority-follows-the-lease.md) (a takeover, whose adoption
  writes no end),
  [ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
  (*done*, a kind of the form — decision 2 amended),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md) (the door, ◇, and the drawer that frames the tab — decision 1 amended),
  [ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
  (decision 18: the windows of a maintenance entry, which its note counts)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

On 2026-10-31 Lex asked to see a node's earlier notes as he sets a pin. On the wall, a
line's editor showed nothing of the two notes its node's Notes view held, both of pins
that had ended, and neither said which pin it had been, how long it had stood or why it
ended. A pin set without words left nothing at all (ADR-0140 decision 1), and one act on
many parts left the same note on each: on one deployment's wall a head's ringed check
had left one sentence on 24 lines of a node, whose Notes view listed it 24 times.

The round's design pass that followed made a node's Notes tab the place to act — the
form beside the history — and the wall's way into it, a door on every head and a drawer
over the wall, a slice of its own. Of that pass this record holds what makes the tab: a
pin's note records its pin; every pin leaves an entry; a note is a kind in the form,
beside the pins; and whoever may set nothing reads.

The tab's own pass settled what that left open. A branch, whose failures stand beneath
it, offers the head's act, which writes on the parts' own nodes: its tab keeps what was
done from it. A pin that stands is stated where it stands and joins the
history as it ends. The links a note carries are its tickets. The Copy document hands
over the newest note with words. And with the first answer Lex added to the slice what
the round's walk-through had settled for every kind and maintenance never had: every
pin's set, edit and end a row of its node, and every end saying why. A line's
maintenance pin wrote a row only where it changed what its node showed, and no
maintenance pin's end said why.

*Done* is a kind of the same form
([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)),
and the door, the drawer and *◇ details*, which frame the tab on the wall, are
[ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)'s.

## Decision

1. **A node's Notes tab is the place to act.** It holds, beside the history (decision
   6): what fails at and beneath the node — the parts the ringed check would mark, each
   linked; a line on what came before (decision 7); *what stands* — the blocks of the
   node, of its lines and of the pins above it, as *Handled* words them away from their
   lines, with *Edit* and *Clear* for whoever may, a pin being changed where its block
   stands (ADR-0104 decision 4), and what is handled beneath the node in every state, a
   branch in maintenance, idle or undefined too, from the one function that gives the
   node's door its number: every part at or beneath it that a pin, an acknowledgment or
   a configured rule handles now
   ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
   decision 2); and the form (decision 2). At a desk the form and what stands take one
   column and the history the other; on a phone one column, what fails first. The tab
   is read, not polled (ADR-0140 decision 2): a head's act whose parts changed since the
   tab was drawn is refused, and lists them anew. It has a panel mode, which the drawer
   ◇ opens over the wall frames, and a write from it, a refusal and a conflict page
   included, stays in the frame (ADR-0147 decision 3).

2. **One form, a kind chosen.** Its kinds are *Note*, *Done*, *Seen*, *Silence* and
   *Maintenance*: one form each under one choice, each posting to the route of its own
   act — a note to `/notes/<path>`, a pin to `/pins/<kind>` — the stylesheet showing the
   chosen one's, a browser that cannot tell showing each, and script carrying the words
   across a change of kind, so that the note is one field. A kind is an entry of a list
   — its route, its permission, its fields and its words — so a kind added is an entry
   added. Under *On* a note and maintenance are set on the node or on any of its lines —
   maintenance on a line its node's page lets a pin be set on, and on no part a pin of
   it stands on already, whose block changes it — *Seen* on what fails now: a failing
   line, or every failure at and beneath the node, the head's act with its parts listed
   and their digest compared (ADR-0142 decision 5) — and *Silence* on that act too and,
   beside it, on every part that could take one, failing or not: the node's own part
   where it reads by itself and each line it reports, but a part in maintenance or held
   already (ADR-0144 decisions 1 and 7). *Done* is set on each failing line of the node
   whose failure is an event, one with an occurrence of its own, and nothing else — not
   the node, and not the head's act — and its form carries the event each line read as
   the tab was drawn, so that a line that reads another since closes nothing and comes
   back refused, with why and the words kept
   ([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
   decision 2). The form sets only what is new: a line acknowledged already is made done
   where its block stands, under what stands, whose pencil offers *Done* beside *Seen*
   and *Silence* (ADR-0146 decision 3). The form opens on *Seen* where something the
   ringed check would mark fails at the part it opens on, on *Note* elsewhere —
   maintenance always a deliberate choice — and on the first kind the reader may set
   where they may not set that one; `?reason=<slug>` opens it on a line, the address a
   line's ◇ names (ADR-0140 decision 3), and `?kind=<kind>` on a kind, `?kind=done` on
   *Done*. A write from the form comes back to the tab, and one it refuses comes back
   with why above the form and the words in it, the kind and the part chosen as they
   were. Each kind's row ends, after the kind's own button, in what a package that files
   a ticket from the words puts there
   ([ADR-0148](0148-a-ticket-is-drafted-from-a-notes-words-by-the-package-that-fills-its-slot.md) decision 1).

3. **A note is an act with a permission of its own, `note`.** A note is written under
   `Identity.may("note")`, an admin's until roles map onto it, as every act's is
   (ADR-0141 decision 4). The form offers the kinds the reader may set, and whoever may
   set none reads the tab without it — but for a small form of its own where a package
   files tickets from the tab, *On* and that package's button, since filing writes
   nothing here ([ADR-0148](0148-a-ticket-is-drafted-from-a-notes-words-by-the-package-that-fills-its-slot.md) decision 2).

4. **Every pin leaves an entry, and its note records its pin.** A pin's note enters its
   node's notes as the pin is set, whatever its kind — one set without words a note
   with no text, a record, the placeholder a maintenance pin holds (ADR-0014) never its
   words — keeping what the node showed before it (ADR-0140 decision 8). Beside its
   words it keeps its pin's kind, a seen's status, the failure a done closed and a
   silence's level, following the pin's edits while it stands, and the pin's end: when;
   why, in the log's words — `hand`, `clock`, `recovery`, `worsening`, `occurrence`,
   `gone`, `made-seen`, `made-silenced`, `made-done`; and who, where a person ended it.
   The end is written by the write that ends the pin, wherever the tree ends one: a
   route's *Clear*, a kind made another, the tick's sweep, a start for a pin that ran
   out while the instance was down, a reading, a start's reap. An adoption at a
   takeover writes none: the notes it adopts are the holder's, which wrote their ends. A
   pin's note is frozen once its pin ends, but for that end (ADR-0047 decision 5), and
   names its pin by the pin's creation (ADR-0140 decision 1). A note of a pin set before
   this release says what it said; where its pin still stands, its kind and its end are
   written when the end comes.
   `notes.json` carries `kind`, `status`, `level`, `ended_at`, `ended`, `ended_by` and
   `at` (decision 5) only where a note has them. A maintenance entry's note says too
   what the entry was planned as and counts its windows, `planned` and `tally`
   ([ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
   decision 18).

5. **One act on many parts is one entry, and a branch keeps the acts made from it.** The
   pins one act sets share their creation, so their notes name one pin: on a node's tab
   they stand as one entry, which lists its parts and how many the act had in all.
   Where the act was made on another node — a branch's head marking failures beneath it
   — each part's note says where (`at`), and that node's tab lists the act beside its
   own entries, its parts beneath it listed; none of its children's own notes is listed
   there. A tab's count is of entries, and so is retention (ADR-0047 decision 9): an
   entry is kept and retired whole, by its first note's age.

6. **The history is what came before.** A pin that stands is stated in *what stands*,
   as its block; its entry joins the history when it ends, and an act's when the last
   of its pins ends, each part that ended before saying when. An entry says its kind by
   its mark and its word, what it was on — the node, a line by its text, or an act's
   parts — from when to when and how long, who, why it ended and by whom, its words,
   and, folded, what the node showed then; one of maintenance planned as a window or a
   schedule says what of it ran in place of how long, and what it was planned as (ADR-0150
   decision 18). A note of its own says what it is on, who
   wrote it and when, and keeps its *Edit* while it is the newest on its node. The tab's
   number counts every entry, standing or not.

7. **A line on what came before.** Above what stands, one line says how often the part
   was handled here — the entries of pins — and noted, since the oldest entry the tab
   keeps; the last time, the newest entry of a pin that has ended — its kind, what it
   was on, who, when, how long, or what ran of one planned as a window or a schedule,
   and why it ended; and the links its notes carry: every
   link a note's words carry, by its own words, newest first, each once, three at most.
   A key written without a link is none, and so is a link into the node's own handbook
   or to a section of the page.

8. **The Copy document hands over the newest note with words.** A node's document
   carries the newest note that has words, whole, its pin said as the tab's entry says
   it — maintenance planned as a window or a schedule *set* when, never *from* (ADR-0150
   decision 18) — and how many entries more its tab lists (ADR-0140 decision 4). A record without
   words adds only who handled the part and when, which the document's own lines say
   while its pin stands and History says once it has ended.

9. **Every pin's set, edit and end is a row of its node, and every end says why.** A
   maintenance pin's end row carries `ended` — `hand`, `clock` or `gone` — as an
   acknowledgment's does, and the Events page's chip says it after the act, *maintenance
   ended · at its end*; an adoption's end says none. A line's maintenance pin writes a
   row of its node for its set, its edit and its end, one row a pin, whatever it does to
   what the node shows — the edit's cause `line-pin-edited`, new, its chip *line's pin
   edited* — where it wrote one only where its node's status changed (ADR-0107
   decision 1, ADR-0036 decision 11).
   Each names the line by its text where its node reports it — a line it does not
   report now by nothing, its slug, often a hash, telling a reader nothing — and none
   is written where no node stands, the pin held against its path. A row that changes
   nothing its node shows begins no period, so no period's `cause` in the contract
   moves, and changes nothing of a wait under way (ADR-0108 decision 2); the Events
   page lists it as it lists a node's own seen.

## Consequences

- **ADR-0140** decisions 1, 2, 4 and 9 are amended — every pin's note, the tab's form,
  the Copy document's newest with words, retention by entries — and so are **ADR-0047**
  decisions 5 and 9; **ADR-0141** decision 4 has a fourth permission; **ADR-0142** and
  **ADR-0144** have their acts offered on the tab's form; **ADR-0107** decisions 1 and 3
  and **ADR-0036** decision 11 write a line's pin whole and say why maintenance ended.
  Each says so.
- A note of its own is changed while it is the newest on its node, and a pin set after
  it, with words or without, now leaves a newer entry: its *Edit* goes then.
- A run of a line's pins ending together writes a row each, where it wrote one for the
  node, and a branch's tab reads the notes beneath it for the acts made on it, in
  memory, on every view of it.
- The page of a path no node stands at lists entries too, an act's one (ADR-0116).
- The envelope and the macOS client are as they were, and the notes stay out of the
  envelope (ADR-0047 decision 15); the wall reaches the tab through the door and the
  drawer (ADR-0147).
- A note written before this release reads as it did, and the log's rows written before
  it are as they were.

## Alternatives considered

- **A branch's tab covering the node and its lines alone**, an act made on it standing
  on the tabs of the nodes it touched: a branch's history blank for the acts that cover
  the most. **Or its whole subtree**: every pull request beneath a branch in its
  history, and its count a number nobody reads.
- **A standing pin's entry in the history as well**, marked as standing: its note shown
  twice while it stands. **Or the history alone**, with no *what stands*: a configured
  rule, a pin above and what is handled beneath a branch have no entry there.
- **A ticket by a key's pattern**, guessing at every tracker's shape; **or by the hosts
  a deployment's actions file tickets at**, nothing where a deployment has none.
- **The Copy document's newest entry, whatever it is**, a record without words handing
  over only who handled the part and when.
- **The why on maintenance's rows as they were written**: a line's pin in the log only
  where its node happened to change.
- **A pin's history apart from the notes, or read from the event log as it is shown**: a
  second store and a second retention for a few fields beside a note kept anyway; and a
  log that a flapping wall fills in hours, so that a year-old incident would lose its
  kind and its time.
- **Words required on every pin**, which buy entries nobody meant; and **every act a
  note, a pin an option of it**, which makes marking a failure seen a second choice
  after writing.

