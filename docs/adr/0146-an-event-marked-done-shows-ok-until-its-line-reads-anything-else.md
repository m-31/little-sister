# ADR-0146 — An event marked done shows OK until its line reads anything else

- **Status:** Accepted
- **Date:** 2026-11-01 (accepted 2026-10-31)
- **Related:**
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (the pin, of which *done* is the fourth kind, its file, its permission and the
  envelope's list — amended),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
  (*seen*, whose occurrence a done is bound to and whose pencil makes it done —
  amended),
  [ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
  (*silenced*, and the one write that changes a kind — amended),
  [ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
  (the *Notes* tab, whose form sets a new done — amended),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (the true color, which a done does not keep, and the healthy fold, which takes it —
  amended),
  [ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)
  (a handled line's mark and rail — amended),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (a
  configured rule on a node's lines, over which a done counts its line — amended),
  [ADR-0032](0032-status-contribution-boundary.md) (rules 6 and 7: staleness escalates
  under every rule, and a rule that cannot be read does not apply),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (the block, in a fourth
  kind's words, and decision 4, a pin changed where its block stands — amended),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (a row's cause —
  amended), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope —
  amended), [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (its note,
  which enters the notes), [ADR-0014](0014-maintenance-persistence.md) (the
  compare-and-set write), [ADR-0036](0036-addressable-reasons.md) (a line's address),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md) (the door, which replaces ✓'s editor for a new act — decision 3 amended)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A failed run that somebody has looked into still alarms: its line stays red until the
next run reads it, and a workflow that failed a year ago and never runs again stays red
for good. *Seen* does not fit: it keeps the failure's color, so the branch above reads
OK while the line still reads red, and it is a state accepted until it changes rather
than an event closed. Maintenance does not fit either.

When the maintenance-and-aggregation round was walked through, Lex settled *done* as the
kind for an event that is over
([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)'s
context): closed, counting as OK where it stands with the failure it closed beside it,
never ending by itself, a new event being new, offered where a failure is an event. The
round brought it before the door on the wall's heads, so that it is a kind of the
*Notes* tab's form from the start. Its design pass, with Lex on 2026-10-31, settled
four questions one at a time: what ends a done, what the healthy fold does with one, how
a part already acknowledged becomes done, and whether `little-sister-aws`'s function
lines name their held error as their event with it.

## Decision

1. **An event looked into and over is closed: a pin of the kind `done`, on a line.** One
   person's acknowledgment on a line at a time, a seen, a silence or a done, beside any
   maintenance, in `pins.json` with the others. Besides what every pin has it keeps the
   failure it closed, `status`, a warning or an error, and the event, `occurrence`,
   which it must have; it has no end and no level, and the file refuses a done without
   an occurrence or with an end. It is set, changed and ended at `POST /pins/done`,
   under the permission `done`
   ([ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
   decision 4), a compare-and-set write as a pin's is (ADR-0014 decision 8), whose
   refusals keep the person's words.

2. **It is set on a failing line whose failure is an event, and nowhere else.** A
   member line that reads a warning or an error now and carries an occurrence of its
   own — the field its type names, or the identity of the reading it was written from
   (ADR-0142 decision 3) — holding no maintenance, on a node in no maintenance. Never a
   node's own failure, which is its failing stretch and no event, and never a head's
   act: a done closes one line's event. A new one is set on the node's *Notes* tab,
   *Done* between *Note* and *Seen*
   ([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
   decision 2), *On* each failing line of the node that names its event;
   `?kind=done` opens the form on it. **It closes the event that was looked at**: the
   tab is read and not polled, so the form carries the event each line read as the tab
   was drawn, and a line that reads another since closes nothing — refused, saying
   that its line now reads a different event, the words kept.

3. **A block's editor makes an acknowledgment any kind its part takes.** The pencil on a
   block — on a node's page, under what stands on its *Notes* tab and on *Handled* —
   offers *Done* beside *Seen* and *Silence* wherever its part takes a done, and a
   done's pencil offers *Seen* and *Silence*: the one standing ends, *made done*, *made
   seen* or *made a silence*, and the other is set in its place in one write
   ([ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
   decision 7), the route asking both kinds' permissions (decision 8). The tab's form
   sets only what is new: a part acknowledged already is changed where its block stands
   (ADR-0104 decision 4). Every new act — a done, a seen, a silence — is set on the
   tab's form in the drawer ◇ opens over the wall, and the block's editor stands in the
   drawer a block opens
   ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
   decision 3).

4. **Its line shows OK, with the failure it closed beside it, and counts as OK.** Its
   tint and its cue are OK's, with the failure it closed beside the cue and set off from
   its words by the same separator, *· error ·*, and its words are the failure's own;
   its mark is the ringed check in OK's green, with no rail, *Done by ada, closing an
   error · counts as ok*
   ([ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)).
   It counts as OK in its node's own status, over a configured rule on the node's lines,
   as a seen does, and a node whose one failure is done reads OK. **A rule with a count
   counts it as the OK it shows**, on Lex's word of 2026-10-31 — a done line among the
   lines it counts, and a node whose one failure is done among the children: a seen or
   a silence holds a state that is still true, and is counted as it reads (ADR-0144
   decision 3), but a done's event is over, and every other surface takes it as OK — its
   node's status, the fold, a chip's ✓, the budget. It is the one acknowledgment that
   does not keep its part's true color
   ([ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
   decision 1), and where a box's lines are ordered it stands among those that show OK.
   It spends no failure budget. Staleness is not closed: a node whose reading goes stale
   counts what its check reported, a warning at least, as it does under every rule
   (ADR-0032 rule 6).

5. **It ends when it no longer covers anything, and never by the clock.** It is judged
   on what its line reads, not on the OK it makes the line show: a different event —
   the next run, whether that fails or passes — ends it, *a new occurrence*; the same
   event read OK, *recovered*; the same event worse, *worse*; no line at all, *no longer
   reported*; and a person's hand. Through the same event read the same or milder it
   holds, a year if need be. *Never ends by itself* says that a done needs no end for
   the next event to alarm, not that it stands once it covers nothing: standing, it
   would sit under *Accepted* and in ◇'s count doing nothing, and hold the line's one
   acknowledgment against the next one. The event is compared first, so the next run
   that passes ends it as a new occurrence, where a seen's next run that passes ends it
   recovered (ADR-0142 decision 4). **The next event alarms as new**: where it fails,
   the row that moves its node is its reading's, as any failure's is, and the done's
   end is a row beside it that changes nothing more. A check's error, which stands in
   for its node's lines, leaves a done suspended; it holds through every restart, and
   one no configured check covers is reaped at a start.

6. **The healthy fold takes a done as the OK it shows.** Its line folds with its node's
   healthy lines, and its node and the nodes above it into their parents' folds, where
   nothing else stands on them or beneath them. It is the fold's one exception to *a
   person's rule on a part or beneath it is never folded* (ADR-0135 decision 9), for
   the reason a done is the one acknowledgment that does not keep its color: it is a
   red a person declared over, which shows OK and counts as ✓ already. Kept out, one
   done would hold its node and every node above it open for as long as it stands — for
   good, for the workflow that never runs again. Folded, it hides nothing: it ends the
   moment its line reads anything other than the failure it closed, so the next failure
   unfolds and spends the budget as if there had been no done, and staleness unfolds it
   as it does anything; ◇ still counts it, and *Handled* lists it. A seen, a silence,
   maintenance and a configured rule stay out of the fold.

7. **Its block and its words.** Its block, beneath its line on its node's page, under
   what stands on the *Notes* tab and on *Handled*, says *This line is marked done by
   ada, closing* {error} *· until it reads anything else*, its record *Marked done by
   ada* and when. *Handled* lists every done under *Accepted*, beside the seens — *1
   done and 2 seen on 3 nodes, the longest standing first* — ◇ and the band's pill say
   *1 done*, before *seen*, a card's list *done, closing error*, and a branch's *why*
   card lists it under *Accepted*. The Copy document writes ✅ before the line and
   beneath it *☑️ Done — by ada, closing error ⛔, until it reads anything else*, and a
   node's *Shown as* says how many of its lines are done. A refusal is *Not marked
   done*, with why.

8. **Every set, edit and end is a row of its node.** The causes are `line-done-set`,
   `line-done-edited` — its note changed, which changes nothing its node shows — and
   `line-done-ended`; an end's `ended` is `occurrence`, `recovery`, `worsening`, `gone`
   or `hand`, or `made-seen` or `made-silenced`, and a seen or a silence made done ends
   `made-done`. The Events page's chips say *line done*, *line's done changed* and
   *line's done ended* with why — *a new occurrence*, *recovered*, *worse*, *no longer
   reported*, *by hand*, *made seen*, *made a silence* — and *made done* after the kind
   it replaced; History's *what moved it* says *a line marked done*, *a line's done
   changed* and *a line's done ended*, and the Time card *when a line was marked done*
   and *when a line's done ended*. A reading of a done line that its node did not show
   is marked done on its row, as damping's rows are marked. A done's note enters its
   node's notes as it is set (ADR-0140), and records the failure it closed and how it
   ended (ADR-0145 decision 4).

9. **The envelope lists it.** A done is an item of its line's `handled`: kind `done`,
   source `person`, `counts_as` `{"WARN": "OK", "ERROR": "OK"}`, `expires_at` null,
   `status` the failure it closed, and `occurrence` the event, never null. The entry's
   `contribution` says `done`, with the OK counted and the done's id as `rule`, and its
   `code` stays what its check declared. A further kind is a compatible change
   ([ADR-0080](0080-the-envelope-is-the-snapshot-published.md)): it is part of the
   contract's 3.1.0, and `schema_version` stays 3.

10. **An older release skips it.** A release that does not know the kind reads a done in
    `pins.json` as none and names it once in its log, as it does any kind it does not
    know (ADR-0032 rule 7), and reads a done's note as a note.

## Consequences

- **ADR-0141** has a fourth kind and a fourth permission; **ADR-0142**'s seen is made
  done from its pencil, and its word on `little-sister-aws`'s function lines is
  corrected; **ADR-0144**'s one write makes a done and is made from one; **ADR-0145**'s
  form has *Done*; **ADR-0135**'s accepted job has its second kind and its fold its
  first exception; **ADR-0143**'s ringed check stands on a line that shows OK;
  **ADR-0104**'s block a fourth kind's words; **ADR-0107** three causes more and
  `made-done`; **ADR-0080**'s `handled` a fourth kind of pin; and **ADR-0137**'s rules
  meet a done line as they meet a seen one in its node, and count it as the OK it shows.
  Each says so.
- **`little-sister-aws` names `occurrence="error.at"`** on the `aws` type in its next
  release, its ADR-0012 updated: a function's line names its held error as its event,
  so a done on it holds through the hold, ends *recovered* once the hold runs out and
  *a new occurrence* at the next error, which alarms; a seen there ends at a newer error
  where it held through one. A function that errs at nearly every run moves its error
  at nearly every poll, so neither holds it: a failure that flaps is a silence's case.
- **A done on a fast line lives for one run** — a job that runs every minute closes for
  a minute — which is why the form compares the event it drew; a workflow that never
  runs again keeps its done for good, and *Handled* lists it among the oldest.
- **The demo's job names carry their run as their event**, so `/ci/jobs/<name>` is where
  a done is shown (`testing-the-gui.md`, Mode 2).
- **The macOS client** alarms off `code`: a node whose one failure is done reads OK and
  is quiet, and the line's next failure alarms as new. Its copy of the contract is
  3.1.0.

## Alternatives considered

- **Bound to its event until a hand clears it**: once its line reads another event the
  done covers nothing, yet would stand under *Accepted*, in ◇'s count and in the line's
  one place for an acknowledgment, and the next acknowledgment would have to replace
  it.
- **Ending only when its line reads another event**, holding through a recovery and a
  worsening of the same event: a done judged by the OK it makes its line show rather
  than by what the line reads, on the one line an end of the same event would ever meet
  — a function's held error once its hold runs out.
- **Kept from the fold as every handled part is**, by the failure its line still reads:
  a line of its box and an open path for as long as it stands, which for a workflow
  that never runs again is for good; and **kept out for a day after it is set**, a
  refinement for the quiet wall, before that wall has been lived with.
- **Counted as it reads by a rule with a count**, as a seen or a silenced part is: one
  done and one real failure would escalate under *one of five may fail*, and a workflow
  that never runs again would use up the allowance for good, for an event that is over.
- **A part already acknowledged made done from the *Notes* tab's form** rather than from
  its block: the block's editor built a second time, and a seen line standing twice on
  the tab; and **no change of kind to or from a done**, a seen cleared and a done set in
  two writes, the line red between them long enough for the macOS client to sound.
- **`little-sister-aws`'s `error.at` later, in a release of its own, or not at all**:
  *Done* offered on no function line, which is the case the round was opened with, and
  a seen there holding through a new error inside its failing stretch.

