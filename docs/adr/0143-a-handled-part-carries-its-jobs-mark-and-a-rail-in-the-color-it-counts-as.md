# ADR-0143 — A handled part carries its job's mark, and a rail in the color it counts as

- **Status:** Accepted
- **Date:** 2026-11-01 (accepted 2026-10-25)
- **Related:**
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (a handled part keeps its true color, a mark per job — decision 1 amended),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (*seen*,
  its ringed check and where it stands — decisions 5 and 6 amended),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (§ on a
  line — decision 10 amended), [ADR-0084](0084-a-check-may-be-reached-through-another.md)
  (the shield's marker at the check's mount — decision 4 amended),
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (damping, whose count stands
  beside its rail), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (decision 2, `contribution`, which the rail draws),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 5, a transformed contribution
  visible and attributable),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  (decision 5, the status sign, whose look a mark on a fill takes),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (decision 3, the seat of a
  line's control), [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  (decision 6, the order a box shows its lines in),
  [ADR-0042](0042-entries-carry-their-own-code.md) (a coded line's tint),
  [ADR-0028](0028-design-tokens-and-themes.md) (contrast measured, not eyeballed),
  [ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
  (*silenced*, whose mark is a bell struck through),
  [ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
  (*done*, whose ringed check stands on a line that shows OK),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md) (the door, ◇: a handled part's mark opens the drawer at what handles it — decisions 2, 4 and 7 amended)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A line marked seen differed from one nobody had seen in one thing: a 12-pixel ringed
check between its status cue and its words, in the line's own ink, the size and the ink
of the cue beside it, so that `▲ ☑` read as one double glyph. Its tint, its ink and its
box were the unseen line's, and the word *seen* stood only in the mark's tooltip. That is
what ADR-0135 decision 1 and ADR-0142 decision 6 asked for, and on a card of pull
requests, where seen and unseen lines stand side by side, it was hard to tell which were
seen. § on a line a configured rule counts otherwise stood the same way (ADR-0137
decision 10), a pinned line carried no mark at all, and a node seen for itself said so
only in its block.

The look was settled with Lex on 2026-10-25, each option drawn on the live card in every
theme where it was a matter of looks.

## Decision

### 1. A handled part keeps its true color, its tint and its place

Nothing is dimmed and nothing moves: a box keeps its lines in the order its line budget
shows them (ADR-0127 decision 6), and a part keeps the color and the tint of what it
reads (ADR-0135 decision 1). What changes is what it carries.

### 2. A handled line carries its job's mark at its top right, in the color it counts as

A line a rule acts on carries the mark of the rule's job at its top right, in room the
line keeps for it, drawn in the color of what its node counts it as rather than in the
line's own ink: seen's ringed check in OK's; § in the color its table gives — amber for
a cap, red for a floor, the undefined ink where the line counts as nothing; ‖ in
maintenance's ink, on a line that keeps its maintenance tint, a pinned line carrying a
mark too. A line has one rule deciding how it counts, and so one mark: a pinned line's is
the pin's, and a line a person accepted carries no configured rule's mark. A line with no
tint of its own stands on its box's fill, which a box's vivid status paints, and its mark
on its own tint, as a status sign is drawn (ADR-0133 decision 5). A silence's mark is a
bell struck through
([ADR-0144](0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md)
decision 9), drawn as the others in the color its part counts as — OK's green, or a
warning's amber where the silence holds it at a warning at most or its reading went
stale. A line marked done shows OK — its tint and its cue OK's, the failure it closed
beside the cue and set off from its words, *· error ·* — and carries the ringed check in
OK's green on that tint
([ADR-0146](0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)
decision 4).

The mark's words are its tooltip and its accessible name, as a chip's are: who, until
when, and what the line counts as — *Seen by ada, until it changes · counts as ok*,
*Done by ada, closing an error · counts as ok*, *Counts as warn by the rule develop
advises*, *In maintenance by ada until* its end. No word stands beside it: it would cost
every handled line some three characters, repeated down a card full of them. On the wall
the mark is a door: it opens its node's *Notes* tab in a drawer at what handles the line
([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
decision 7), where the block says it in words — so that a touch screen, which shows no
tooltip, reaches them, and so that the mark opens something, as every mark on the wall
does (ADR-0135 decision 4). Its own box is its target, 24 pixels square with the glyph in
its middle, as WCAG 2.2 asks at AA (2.5.8), and a marked line shorter than its target
stands as tall, so that the marks of two lines one above the other never overlap.

### 3. Wherever a part counts as something other than it shows, a rail on its right edge says what

A part draws a rail down its right edge, in the color of the status it counts as one
level up, wherever that differs from what it shows: the envelope's `contribution` drawn
— what a node's parent counts of it (ADR-0080 decision 2) and what a node counts of each
of its lines (ADR-0135 decision 10). The color is the ink of that status's tint, and the
undefined ink where the part counts as nothing. The mark says which job, the rail what
the part counts as instead, and the right edge of a card reads as one column of what is
taken care of.

So a seen line always has one, being a failure that counts as OK; a silence's where it
changes what its part counts as, green or amber as it counts it; a configured rule's
only while it changes a count, as its § does; and maintenance has none, a pinned part
counting nothing, which is what maintenance counts — nor has a done line, which shows OK
and counts as what it shows. A line nobody has handled has none. One derivation serves
the envelope's entry and a line's rail, `tree.line_contribution`; a node's rail reads
`StatusSnapshot.counted`.

### 4. A node with a rule on its own part carries its mark beside its head's state

A node whose own part a rule acts on carries the job's mark beside its head's state — on
a card, a box and the head of its own page — where a head is always drawn, its buttons
showing only under the pointer in the library's look. It stands on its own tint, as a
status sign is drawn, a head standing on its box's fill: seen's ringed check in OK's, or
in amber where the node's reading went stale, which escalates under every rule (ADR-0142
decision 2); a silence's bell struck through in green or amber as it counts the node,
amber wherever its reading went stale (ADR-0144 decision 9); § in the color its table
makes of the node, where it changes what the node passes up or what its parent counts of
it among its children. Its words are its tooltip and its accessible name, and it is a
door as a line's mark is, opening the drawer at what handles the node whichever way
*◇ details* is set, since with the switch off the node's block is off the wall (ADR-0147
decisions 6 and 7). By decision 3 its box draws the rail wherever the node counts as
something other than it shows — green where a node seen for itself has nothing failing
beneath it, none where a failure beneath still climbs, the node then counting as that
failure. A node in maintenance carries neither, its state saying *maintenance* already.

### 5. Damping and the shield draw the rail too

Every contribution is drawn, which is ADR-0032 rule 5's *a transformed contribution is
visible and attributable*. A damped node shows the reading it holds, and its rail the one
its parent still counts, beside its *· 2 of 3 to escalate* (ADR-0083). A shielded node
counts nothing above, its rail in the undefined ink, and says why beside its state in the
ink of damping's count: *· reached through vpn*, the dependency's name, with its path and
the rest of the sentence in the tooltip — *Reached through /network/vpn, which is failing
— nothing from here reaches the level above until it answers* — at the check's mount
alone, where ADR-0084 decision 4 puts the shield's marker.

### 6. On a box's fill the rail stands on a strip of the page

A box that counts its failure for itself is filled vivid, and the tints' inks, made for
the pale tints, fall under the 3:1 a non-text mark needs on the vivid red and, in dark,
on the vivid amber. So a box's rail is drawn inside its edge on a strip of the page two
pixels wide, against the page's color, and so is the rail of a line with no tint of its
own; a mark on a fill stands on its own tint (decisions 2 and 4). A line's mark and rail
stand on the line's own tint. In cyberpunk a failing box is a tube of shadows (ADR-0028),
and a railed one draws the rail and its strip over its glass.

### 7. On a node's own page the mark stands in its line's one seat, and the rail runs down the row

A line on a node's page has one seat at its end: a plain ◇ where nothing handles the
line, for whoever may set something on it, and where something does, the mark of what
handles it, which is its door, opening the drawer at what handles it
([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
decisions 1 and 7). For a reader who may set nothing there the line has no seat, and its
mark stands at its top right, a door all the same. The rail runs down the row's whole
right edge — the sentence, the record and the block — so that a row with a long record
still reads as handled.

### 8. A closed chip, and what a handled part counts as, stay as they are

A closed chip's counts explain its color and its ◇ says what is handled, by which job in
its words (ADR-0135 decision 6). What seen, silenced and done count as above stays as
recorded: OK, silenced at most amber where it holds at amber.

## Consequences

- **ADR-0135 decision 1 is amended**: a line's mark and a head's are drawn in the color
  of what their part counts as rather than in `currentColor`, a line's at its top right
  with its words in its tooltip and its accessible name, and damping's count and the
  shield's marker gain the rail, the shield its words.
- **ADR-0137 decision 10 is amended**: § stands at a line's top right in the color its
  table gives, a door on the wall as every mark is, and beside the head's state of a
  node it counts otherwise.
- **ADR-0142 decisions 5 and 6 are amended**: a line marked seen carries the ringed check
  at its top right, on a node's page in its line's seat, and a node marked seen beside
  its head's state, each with the rail where its part counts as OK.
- **ADR-0084 decision 4 is amended**: the mount says *· reached through* its dependency
  beside its state, and draws the rail.
- **The JSON contract does not move**: the rail draws `contribution`, which the envelope
  carries for nodes and lines already, and the macOS client alarms off `code` as before.
- **The contrast is measured in every theme**, from the tokens in
  `tests/test_contrast.py` and in the page in `tests/sweep_contrast.py`: a line's mark
  and rail on its tint at 4.9:1 at the least (pastel's green on a red line), a rail on
  the page's strip at 6.1:1, a head's mark on its own tint at 5.4:1, and the shield's
  words at 5.8:1.
- **A link in a line keeps Bootstrap's link ink**, under AA on a light theme's pale tints
  and on a pale card's fill: it is mended on its own, and the accessibility scan's
  baseline lists it until then (`tests/test_a11y_browser.py`).

## Alternatives considered

- **A handled failure counting nothing above, or a status of its own.** Counting nothing
  says something false where every part a node counts is handled: a card whose every
  pull request is seen would turn blue or idle gray, and its parent with it. A sixth
  status would break the contract's `code`, every client and every theme's palette, and
  would rank above OK or vanish one level up; nor would it cover a table that turns an
  error into a warning, so *counts as* stays a mapping either way.
- **Handled lines grouped below a divider, with a tag**: the order stops being the
  check's, and a line jumps when it is marked.
- **A handled line toned down by opacity**: the faded ink `tests/test_contrast.py`
  refuses; in a light theme a see-through line lets the card's color through and reads
  louder.
- **The background alone dimmed toward the card**: invisible in cyberpunk, backwards in
  the light themes, where the pale tint is the quiet part, and a link falls from 4.1:1 to
  3.1:1.
- **A green edge, a green left rail, a tag, a green tint, or gray**: a tag costs a narrow
  card its width, a green tint is an OK line's, and gray is an idle part's.
- **Hatching, thin stripes, a raster behind the words**: the stripes vanish on
  cyberpunk's red line, take the words under AA, or are too faint to read.
- **The mark before the cue, between the cue and the words as it stood, or a dog-ear**:
  the cues stop forming a column, the mark reads as one glyph with the cue, or the check
  is too small to read.
- **A pattern or a second stripe per job**: the angles and the tints too close to tell
  apart; one look serves every job.

