# ADR-0144 — A failure silenced counts at its level above until its deadline

- **Status:** Accepted
- **Date:** 2026-11-01 (accepted 2026-10-31)
- **Related:**
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (the pin, of which *silenced* is the third kind, its file, its permission and the
  envelope's list — amended),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
  (*seen*, whose editor this one shares and whose count over children it changes —
  amended),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (a
  configured rule, which a silence meets by the stricter cap, and a rule's count —
  amended),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (the true color, the jobs, ◇ and *Handled* — amended),
  [ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)
  (a handled part's mark and rail — amended),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (the block — amended),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (a row's cause —
  amended), [ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) (the notes,
  which an extension writes to — amended),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope —
  amended), [ADR-0014](0014-maintenance-persistence.md) (the expiry's grammar and
  bounds, and the default a blank one takes — amended),
  [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 4, a pin held
  against its path), [ADR-0032](0032-status-contribution-boundary.md) (the contribution
  boundary, and rule 6: staleness escalates under every rule),
  [ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
  (*silenced* offered on the *Notes* tab —
  amended),
  [ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
  (*done*, which a block's pencil makes a part and is made from — decisions 7 and 8
  amended),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md) (the door, ◇, and the drawer where a silence is set and changed — decision 7 amended)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A failure that flaps — red, then green, then red again — alarms at every return, and
*seen* does not hold it: a seen ends at the first recovery
([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)), so the
part is red again at its next failure and has to be marked again. Maintenance does not
fit either: the part is not down on purpose, and a blue node reads nothing.

When the maintenance-and-aggregation round was walked through, Lex settled *silenced* as
the kind for a thing that flaps: it holds across recoveries and ends only at its
deadline or by hand; the deadline is required and bounded, the technical pressure, since
the alarm comes back at it; its note says what is being done, and an extension says what
changed, the organizational pressure. A silence carries a level — counting as OK above,
or at most amber, the busy function's — which makes it the page's form of a clamp for
now, beside the configuration's for good; where both stand on one part, the stricter
cap counts. The round's design pass settled, on 2026-10-25, that ✓ opens one editor of
the kinds a part takes, that a silence's deadline is a week by default and thirty days
at most, and that an extension's sentence is required and kept as a note of its own.

It was built in three slices: the model, the pages, and these records. The review of
the first two, on 2026-10-31, found that a rule counting a node's children counted a
silenced child as it was held, so that silencing one replica
of five let a second fail unseen — Lex took (b), the count reading a held part as it
reads, for *seen* as well — and that a start lost every acknowledgment at the restart
after the next.

A silence was first offered only where its part failed, so a flaky part had to fail
again — and alarm once more — before anybody could silence it. On 2026-11-01 Lex had it
offered on a part that reads ok as well: a silence is bound to no failure, so nothing
asks it to wait for one.

## Decision

1. **A part that flaps is silenced: a pin of the kind `silenced`, with a level and a
   deadline, bound to no failure.** It stands on a node's own part where the node reads
   by itself, or on one of its lines, whether the part fails now or not, in `pins.json`
   beside the others: one person's acknowledgment on a part at a time, a seen or a
   silence, beside any maintenance. Besides what every pin has, it keeps its level —
   `OK` or `WARN` — and its deadline, both required; it is bound to no failure, so it
   keeps neither a status nor an occurrence, and one set on a part that reads ok
   changes nothing until the part fails, and from then counts at its level until its
   deadline (decision 2). It is refused on a part in maintenance — under a pin on it or
   above it, or under its own check's word for maintenance, over which no silence
   counts — on one a person holds already, whose block changes it, and on a node whose
   lines are members, which take one each. It is set, changed and ended at
   `POST /pins/silenced`, under the permission `silenced`
   ([ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
   decision 4), a compare-and-set write as a pin's is (ADR-0014 decision 8), whose
   refusals keep the note, the level, the deadline and what changed.

2. **Its part keeps its true color and counts above at its level, through every
   recovery.** At `OK` every failure of it counts as OK, `{"WARN": "OK", "ERROR":
   "OK"}`; at most a warning, an error counts as a warning and a warning as it is,
   `{"ERROR": "WARN"}` — a line's in its node's own status, a node's own part in what
   it passes up, its children counted as ever. It holds through a recovery, a
   worsening and a new occurrence: a silenced line that recovered counts as it reads,
   and when it fails again it is silenced still. Staleness is not silenced — a stale
   reading counts at least as a warning above, as it does under every rule (ADR-0032
   rule 6) — and a silence never counts over maintenance, a shield or a node not yet
   reported. It hides no reading, and spends no failure budget unless its reading went
   stale.

3. **Beside a configured rule the stricter cap counts, and a rule's count reads a held
   part as it reads.** Where a silence and a configured rule stand on one part — at the
   node's boundary, over its parent's children, or on its lines — the one that counts
   the part for less counts, the rule where both count it the same, and
   `contribution.by` names the one that decided; a floor never lifts a silenced part
   above its level. A rule with a count — *one host of five may be down* — counts a
   part a person holds, silenced or seen, toward its count as it reads, on Lex's word of
   2026-10-31: the part itself still counts as it is held, and a second failure beside
   it is not hidden behind its silence. A node's lines were counted so already.

4. **Its deadline is required: a week by default, thirty days at most, refused rather
   than bent.** A blank deadline takes `silence_default_expiry`, a week unless
   `settings.yaml` says otherwise; any other is read in a pin's expiry's grammar, at
   most thirty days away — the library's bound — and at least the period of the
   slowest check the silence covers, as a window's (ADR-0014 decision 13); one out of
   range is refused, never clamped (decision 14). A check slower than thirty days sets
   no floor, since no deadline could cover a run of it. A default that reads as no
   duration, or one past thirty days, is not honored: a blank deadline runs for a
   week, every form names the week, and the log says so at start.

5. **It ends at its deadline, by hand, or made the other kind, and no reading ends
   it.** A part no longer reported — a line gone from its node's reading, a node
   removed — leaves its silence against its path, suspended, as a pin is held (ADR-0109
   decision 4), until its deadline; one no configured check covers is reaped at a
   start. One whose deadline passed while the instance was down ends there. It holds
   through every restart: a start replays the whole pins file — the maintenance and
   every acknowledgment — and writes it back once, after both.

6. **An extension says what changed, in a note of its own.** An edit that moves the
   deadline later is refused without a sentence under *What changed*, and the sentence
   enters the part's notes as a note of its own that names the deadline it moved the
   silence to — *Silence extended until 2026-11-07 10:00:00. The vendor moved the patch
   to Friday.* — beside the silence's own note, which keeps saying what is being done
   ([ADR-0140](0140-a-nodes-notes-stand-on-a-tab-of-their-own.md)). Any other edit that
   says what changed keeps its sentence the same way, naming what the silence holds
   now — *Silence changed: until …, counting as a warning at most.* — since words a
   person wrote are not dropped.

7. **A node's *Notes* tab offers *Silence* on any part a person could later silence,
   and a block's pencil changes the kind.** A new silence is set on the node's *Notes*
   tab, in the drawer ◇ opens over the wall
   ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)), *Silence*
   one of its form's kinds beside *Seen*, each the form of its own act on its own route
   ([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
   decision 2). Its *On* offers every part that could take one — the node's own part
   where it reads by itself, and each line the node reports, failing or not — beside
   the head's act over what fails at and beneath the node, which silences each failing
   part, one silence each, sharing the note, the level and the deadline, its form
   carrying the parts' digest as a seen's does; a set refused for its words comes back
   with the digest, so that what is sent again acts on the parts that were shown. A
   part in maintenance, or one a person holds already, is not offered. The head's act
   sends the form's empty choice, as the node does where nothing fails; where both
   stand, the node's own part is sent as `own part`, which no line's slug can be.
   *Seen* and *Done* stay on what fails now. A standing silence is changed in its
   block's editor — on a node's page, on *Handled*, and from the wall in the drawer —
   which opens with the standing kind chosen beside the others its part takes: its
   form saves changes, and another's makes the part that kind — the one ended and the
   other set in its place, in one write, the end's row saying *made a silence*, *made
   seen* or *made done*. *Seen* is offered there only where the part fails now, *Done*
   where it takes one — a line whose failure has an occurrence of its own and fails now
   ([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
   decision 7) — and a done's pencil offers *Seen* and *Silence*; a silence on a part
   that reads ok, set so or held through a recovery, is edited or cleared.

8. **Ending an acknowledgment asks the permission of its kind.** Clearing one, or making
   it the other kind, is an act on the one that stands, so the route asks the
   permission of that one's kind besides its own: the `seen` permission alone ends no
   silence, nor `silenced` a seen, and neither ends a done, whose route asks `done`
   besides ([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)).
   Every permission is an admin's until roles map onto them.

9. **Its mark, its block and its words.** Its mark is a bell struck through, drawn in
   the color its part counts as
   ([ADR-0143](0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)):
   a line's at its top right, a node's beside its head's state — a warning wherever its
   reading went stale, recovered or not — and the rail green or amber as the silence
   counts its part. Its block says *This node is silenced by ada, counting as* {ok}
   *until* its deadline *· 6d 23h left*, *at most* after {warn}, and on the wall
   *Silenced by ada, …*; its record *Silenced by ada* and when. *Handled* lists every
   silence under *Silenced* — *2 silenced on 2 nodes, the longest standing first*, *Its
   own part* — ◇ says *1 silenced*, a card's list *counts as ok* or *at most warn* and
   what is left, and a branch's *why* card *Silenced*. The Copy document writes *🔕
   Silenced — by ada, counting as ok ✅, until …*, and *🔕 Silenced* among what is
   handled. A refusal is *Not silenced*, with why.

10. **Every set, edit and end is a row of its node, with its level.** The causes are
    `silenced-set`, `silenced-edited` and `silenced-ended`, and for a line
    `line-silenced-set`, `line-silenced-edited` and `line-silenced-ended`, each row
    carrying `level`; an end's `ended` is `clock`, `hand` or `gone`, and `made-seen` or
    `made-silenced` where a person made it the other kind. The Events page's chips say
    *silenced*, *silence changed* and *silence ended* with why — *at its end*, *by hand*,
    *no longer reported*, *made seen*, *made a silence* — and *line silenced*, *line's
    silence changed* and *line's silence ended*; History's *what moved it* says
    *silenced*, *a silence changed*, *no longer silenced* and their lines' forms, and
    the Time card *when a line was silenced*. A replay reads each period's level from
    its rows. A silence's note enters its node's notes as it is set (ADR-0140), and
    records its level, and when, why and by whom it ended
    ([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
    decisions 2 and 4).

11. **The envelope lists it.** A silence is an item of its part's `handled`: kind
    `silenced`, source `person`, `counts_as` its level's table, `expires_at` its
    deadline, never null. A node's and an entry's `contribution` say `silenced`, with
    what was counted and the silence's id as `rule`. A further kind is a compatible
    change ([ADR-0080](0080-the-envelope-is-the-snapshot-published.md)): the contract
    is 3.1.0, and `schema_version` stays 3.

## Consequences

- **ADR-0141** has a third kind and a third permission; **ADR-0142**'s seen is made a
  silence from its pencil, and counts toward a rule's count as it reads; **ADR-0137**'s
  rules meet a silence by the stricter cap and count a held part as it reads;
  **ADR-0135** has a third job, *Silenced*; **ADR-0143** a third mark; **ADR-0104**'s
  block a third kind's words; **ADR-0107** six causes more and a row's `level`;
  **ADR-0140** an edit's note of what changed; **ADR-0080**'s `handled` a third kind of
  pin; and **ADR-0014**'s default is said at start where a blank field does not run
  for it. Each says so.
- A seen set before this release was written back without it at every start, and stood
  until the start after the next; one lost so is set again. The fix keeps every kind
  through every restart (decision 5).
- A flaky part is silenced in the quiet between two failures, so its next failure
  counts at the silence's level and alarms nobody. The *Silence* form's *On* lists every
  line the node reports, as *Note*'s does, so a tab grows by one choice a line.
- A deployment whose `silence_default_expiry` lies past thirty days runs its blank
  deadlines for a week, and its log says so at every start.

## Alternatives considered

- **A silence without a deadline, or one standing up to a year**: a configured clamp in
  all but name, without the configuration's review (the design pass's decision 2).
- **The silence's note rewritten at each extension, or a sentence asked for and not
  required**: the first loses what was said before, the second is left out at three in
  the morning (decision 3).
- **A count over children reading a held part as it is held**, as the build first had
  it: one replica silenced while it flapped turned *one may be down* into *two may be
  down* while it stood.
- ***What changed* dropped where the save is no extension**: words a person wrote, lost
  without a sign.
- **A silence offered only where its part fails**, as it was built first: the part had
  to fail again, and alarm, before it could be silenced.
- **Every kind's *On* sending a choice of its own** — the head's act, the node, a line —
  in place of the empty choice the head's act and the node share: every form and route
  changed for the one choice in which the two stand side by side.
- **A default past thirty days counted as thirty days**: a bound the deployment cannot
  raise, raised in silence.

