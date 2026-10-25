# ADR-0135 — A handled part keeps its true color, and every surface says by what

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-10-24)
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (the contribution
  boundary; rule 5, a transformed contribution visible and attributable),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (a pin is one block, its
  kind data — decisions 1, 2, 6, 7 and 8 amended),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (decision 2,
  a chip's counts and its bare ‖ — amended), [ADR-0019](0019-inspection-popover.md) (the
  inspection card, whose look and machinery the note's card takes — amended),
  [ADR-0056](0056-stable-useful-dashboard-flow.md) (*Maintenance visibility*, the band's
  pill and a card's pip — amended), [ADR-0036](0036-addressable-reasons.md) (decisions 10
  and 12, the Maintenance page and the way back to it — amended),
  [ADR-0124](0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)
  (a node whose lines are all pinned — its words amended),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (decision 3, the words a
  cause is said in — amended), [ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  (decision 6, *a pin ended*), [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md)
  (the Copy document, which writes the same words and the same list),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (a pin is a rule in the snapshot),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (decision 2,
  `contribution`, whose `by` names a rule's kind), [ADR-0018](0018-markdown-rendering.md) (decision 7,
  compact means clamped HTML), [ADR-0029](0029-per-user-presentation-preferences.md)
  (`inspection_card`, the look that says whether a card opens on a pause, and
  `failures`, whether the failure budget runs),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up — unchanged here),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (the
  configured rules, which take this record as it stands — decisions 5, 6, 8 and 10),
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (the envelope's list of what handles a part, by decision 9's predicate, and a route
  per act),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (*seen*,
  the first kind of accepted, and its ringed check)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A pin does several jobs that are about to get rules of their own — a failure accepted,
a flapping thing silenced for a while, a part that never reddens the whole — and every
one of them but maintenance keeps its node's true color. ADR-0104 made a pin one block on
what it silences, its kind data — its mark, its tint and its buttons — and left the rest
of what such a rule owes the page for later. What the page says of a rule today was
built for maintenance alone:

- A closed node's chip shows a bare ‖ wherever a rule stands beneath it, a node's pin or
  a line's, and says nothing of what or how many.
- A branch says why it has its color in one line of its Time card — *from pull_requests
  beneath it, and 2 more* — and nowhere says what beneath it is pinned.
- The Maintenance page lists pins, the one kind there is.
- Maintenance says *silenced* — *Silenced by*, *a line silenced*, *It silences everything
  beneath it* — the word the walk-through gives the kind that holds a flapping thing.
- On the wall a block states its note whole: on Lex's wall a long note on `ec2` stood at
  full length in its card, the heaviest thing on it.

The design was settled with Lex by 2026-10-24, one question at a time, each drawn on
the real wall in every theme where it was a matter of looks. This record is
what every rule owes the page, built on the rules there are today — a node's pin and a
line's, damping and the shield — with nothing counted differently. The rules still to
come, the configured ones and the kinds a person sets beside maintenance, take it as it
stands here.

## Decision

### 1. Every part keeps its true color, and a mark per job says what acts on it

There are four jobs: down on purpose, maintenance, ‖; accepted, *done* and *seen*, a
ringed check; silenced, a bell struck through; and a configured rule, §. Each mark is
drawn in `currentColor` at the status cues' height, § as a path and not a font's glyph,
so that it holds on every surface in every theme; and none stands alone — its word
stands beside it in a head, a block and a line, and on a chip in the tooltip and the
accessible name (ADR-0056), so that a job leans on neither color nor shape and a screen
reader says it.

Every part keeps its true color and carries the mark of the rule acting on it, and what
it counts as shows one level up: a line's in its node, a node's in its parent. A rule
never changes the color of what it acts on — only how that counts above. Two exceptions
stand: maintenance paints blue, there being nothing to read on a node down on purpose,
which says its reading beside *maintenance*; and *done* shows OK with the failure it
closed beside it. Damping's count and the shield's mark at the check's mount stay as
built. Maintenance's mark, the ringed check — *seen*'s
([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)) — and
§, the configured rules'
([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) decision
10), are drawn; the bell struck through comes with its kind.

### 2. Maintenance takes its own words, and *silenced* is left to its kind

The status is *maintenance*, a chip says *in maintenance*, the macOS client *Maintenance
ended*, and History's first table and the Copy document *a pin ended* and *a line's pin
ended* (ADR-0132 decision 6). So the block says *This node is in maintenance from
/nexus/qnap by …*, a card's *In maintenance by …* and a line's *This line is in
maintenance by …*, *also in maintenance on its own* under a pin above; *a line's pin
set* stands wherever *a line silenced* stood — the Events page's chip, History, the Time
card's *when a line's pin was set*, the Copy document; and the editors' sentences say
what a pin puts in maintenance where they said what it silences. No surface says
*silence* of maintenance: *silenced* is the word of the kind that holds a flapping thing
until a deadline, Alertmanager's for the same. The code keeps its names
(`lines_silenced`, `CAUSE_LINE_PIN_SET`), and the records that say *silenced* of
maintenance take the new words in their titles, headers and decisions, ADR-0124's title
among them.

### 3. A block on the wall says its sentence, and its note opens from a mark

On the wall a rule's block says its mark and its sentence — who, until when, and what
is left — and where it has a note, a note mark after them: a speech bubble, drawn as the
marks are, its word *Note* in its tooltip and its accessible name. The mark opens the
note in a card in the inspection card's look and place (ADR-0019): on a click, a tap,
Enter or Space, for every viewer, and after a pause where the viewer's look opens cards
on a pause (`inspection_card`, ADR-0029). It closes with Escape, a click elsewhere or the
mark again, and holds through the refresh, as the inspection card does. The card names
the node, says the block's sentence, its note whole — rendered, scrolling past a height,
clamped HTML and never shortened Markdown (ADR-0018 decision 7) — who set it and when,
and links to the node's page. It carries no buttons, so that a pin keeps its one editor
(ADR-0104 decision 3), and it stands above the block, so that the sentence pressed stays
in view. Without script the mark is a link to the node's page. Each note rides in the
grid's fragment inside its block, in a template the browser keeps out of the page until
the card reads it, so that nothing is fetched to open it and the fragment carries no
more than when the note stood in the box.

Where a node is stated on its own a block keeps its note whole, and *Edit* and *Clear*
in words: a node's page, in the blocks of the node itself and of its lines, and
*Handled*, in every block — what is too heavy for a wall is what a page is for. The
boxes a node's page shows beneath it are a wall of their own, and their blocks the
wall's.

### 4. On the wall an admin edits with a pencil, and clears in the editor

For an admin, *Edit* on the wall is a pencil mark after the note mark, its word *Edit*
in its tooltip and its accessible name, shown as *Edit* and *Clear* were — on hover or
keyboard focus, always on a touch screen — its room kept so that nothing moves when it
shows. It opens the block's editor as before (ADR-0104 decision 4), and *Clear* stands
there, in words beside *Save changes* and *Cancel*. *Clear* is the one control on a block
that acts at once, without a confirmation — the rule ends and the node may alarm — and
a small mark is where a mis-click lands; so every mark on the wall opens something, and
every act with an effect is said in words inside what a mark opened. Ending a rule from
the wall takes one click more. A node's page, whose head shows *Edit* and *Clear*
always, keeps them in words, as *Handled* does.

### 5. Every block has a dashed edge, and a fill only where its rule paints

Every node and chip on the wall is a box with a solid edge, filled with its state, and
nothing else on the page has a dashed or dotted edge; so a block's edge is dashed — 1.5
pixels of its ink — and says one thing: not a node, but something laid on one.
Maintenance's block keeps its blue fill, its rule painting its node blue, and its dashes
are its ink at 65 %, which clears the non-text bar on that tint in every theme. The
block of a rule that keeps its node's color has no fill, the node's color running
through it and its words in the node's own ink, which every theme already makes
readable on its fill; standing on whatever fill its node's status gives it, its dashes
are its ink at 75 %, as a head's squares' edges are, and its marks wash at 8 % under
the pointer, a ring saying which one is open, since at maintenance's 65 % and 12 % a
block on an amber or a green node falls under the bars in four themes
(`tests/sweep_contrast.py`). With a solid edge a neutral block was an idle child box to
the eye — the idle tint as it is is a pale idle box's fill and an idle chip's — and with
the dashes a fill would only lend the idle tint's meaning, *reports nothing*, to what
has no status, and cover the true color this record leaves alone. It is the same in
every theme, and no color pair is added.

A person's rule's block stands on the wall while the rule stands — maintenance, *seen*,
which ends by itself, and with its kind *silenced*, whose block stays between the
recoveries of what flaps. A configured rule's block, §'s, stands on the wall only while
the rule changes what its part counts, so that a block and ◇ follow one predicate, open
and closed alike; on a node's page and *Handled* it stands always, *changes nothing now*
beside it where it does not act.

### 6. A closed chip says what is handled beneath it in one short form

A chip counts each part by what it counts as above, so that its counts explain its color
(ADR-0127 decision 2). Beside the counts, where a bare ‖ stood, stand a ringed diamond
and the number of parts beneath that a rule handles and the counts do not show as such.
That is a pinned branch — the chip's own node among them — whose leaves count for
themselves, a line's pin wherever its node is not ‖ among the counts, a part marked
seen, and a part whose count a configured rule changes; with its kind a part silenced.
A pinned leaf is ‖ among the counts already, its lines with it, and is not handled
twice. The diamond's words, in the tooltip and the accessible name and at the end of
the chip's own, say what each job handles — *3 handled: 1 node in maintenance, 2 lines
in maintenance*, *4 handled: 1 line in maintenance, 2 seen, 1 by a rule* — the words
*by a rule* the same for one part and for many. It is one mark and a number whatever
the mix, so that a chip grows by the same whatever is handled beneath it, and the marks
by job show once the node is opened. The band's pill takes the same form — the diamond,
a number and the same words — counting every pin that stands and, beside them, the
parts a configured rule changes now rather than the rules configured, which stand for
good; it leads to *Handled*, and a card's pip takes the diamond and opens the card's own
list.

### 7. A branch says why it has its color, in a card of its own

On a node's Status tab, right after Time, a card titled by its question — *Why error*,
*Why warn*, or *Why ok* where something beneath is handled — stands wherever a branch
fails or holds something handled, and nowhere else: not on a leaf, whose lines are its
page, nor on a node in maintenance, whose block says why. First what counts: each part
beneath that fails and passes its failure up, with the status it counts as and since
when — not what a pin, a shield or a damping counter holds back, nor anything beneath
it. Then what is handled, under ◇ and its total, grouped by job under each mark, each
with its rule, who or what set it and until when, what its part reads where that is a
failure, linked to where it stands. Each list shows its first five rows and folds the
rest beneath *N more*, as History folds its earlier periods, so that an outage does not
grow its branch's page by a screen. Time keeps its one line —
*from pull_requests beneath it, and 2 more* — its *and 2 more* linking to the card; a
node with rules of its own keeps them as the blocks at the head of its frame (ADR-0104
decision 8). A branch's Copy document writes what is handled the same way, after
*Beneath it*, whose outline is what needs attention.

### 8. One index of what is handled: *Handled*, at `/handled`

The Maintenance page becomes *Handled*, at `/handled`: every rule that stands, grouped
by job, oldest first, each as its block (ADR-0104 decision 6). Its sections read as the
jobs do — *In maintenance*; *Accepted*, *seen*'s (ADR-0142 decision 6); *By a rule*,
every configured rule the longest standing first, with its file, its root, its note and
its date; and *Silenced* with its kind. It takes the word the chip and the pill say, so
that *◇ 12 handled* lands on a page of that name, and the rail's entry takes the ringed
diamond. `GET /maintenance` redirects there with its query, so that a bookmark and the
way back from an edit hold; a pin's writes go to a route per act, a maintenance pin's
to `POST /pins/maintenance` (ADR-0141 decision 4).

### 9. One predicate behind the fold, the counts and the budget, and no switch

A handled failure spends no failure budget, counts where it counts above, ◇ and its total
beside the counts, and the healthy fold folds only what is truly OK.
On today's rules that is how they behave already — a pinned node counts as maintenance
and spends no budget, and a node with a pin on it or beneath it is never folded — so
nothing is counted differently; the later kinds are built to the same functions
(`counts_as`, `own_failure` and `healthy` in `tree.py`). Whether the budget runs at all
is a browser's look, `failures` (ADR-0029), which asks the same `own_failure` and
has no test of a failure of its own. Since every part keeps its true
color, nothing on the wall is painted over and no switch shows it: the Events page's
*held back* stays the one switch, every rule's rows marked as damping's are.

### 10. The envelope names a rule by its kind, and lists what handles a part

`contribution.by` keeps its values and names the kind of the rule that decided:
`maintenance` for a maintenance pin, `seen` for a failure marked seen (ADR-0142
decision 8), and `aggregation` for a configured rule (ADR-0137 decision 12). Every
entry carries a `contribution` object too, saying what its node counted of it —
`maintenance` where the line is pinned, `seen` where its failure is marked seen,
`aggregation` where a rule on its node's lines changes how it counts — the contract's
2.11.0. Each later kind adds
its own name when it lands — a client shows a name it does not know, so each is a
compatible change (ADR-0080 decision 2). What a block states, the envelope lists:
a node and an entry carry `handled`, every rule that handles them now by decision 9's
predicate, where `maintenance` said a pin alone, and `contribution` names the rule
beside its kind — a break, `schema_version` 3 (ADR-0141 decision 3).

## Consequences

- **ADR-0104 is amended**: decision 1, the note whole wherever the block stands — on the
  wall behind the note mark, whole where a node is stated on its own — and *Edit* and
  *Clear*, on the wall a pencil and *Clear* in the editor; decision 2, a closed node's ‖ —
  the diamond and a total; decision 6, the Maintenance page — *Handled*; decision 7,
  *Edit* and *Clear* shown on hover — the pencil; decision 8, *the block paints its own
  tint* — only where its rule paints, every block's edge dashed.
- **So is ADR-0127 decision 2**: the bare ‖ and its words give way to the diamond and the
  number handled.
- **ADR-0019** gains a second card on its machinery, the note's, opened by the mark and,
  under the look, by a pause; **ADR-0056**'s pill and pip take the short form and lead to
  *Handled*; **ADR-0036** decisions 10 and 12 name `/handled`; **ADR-0107** decision 3,
  **ADR-0132** decision 6 and **ADR-0124** take maintenance's words, and the Copy
  document (**ADR-0115**) its words and a branch's list of what is handled.
- **Every record that said *silenced* of maintenance** says maintenance's words in its
  title, its header and its decisions — ADR-0014, 0036, 0039, 0042, 0072, 0082, 0083,
  0085, 0104, 0107, 0110, 0115, 0123, 0124, 0127 and 0132 — its context, consequences
  and alternatives keeping the words they were written in, and every file its name; the
  living documents take them throughout. The code keeps its names.
- **The contrast sweep reads the wall's block as it now stands** — its words, the note
  mark, the pencil under the pointer and the editor's *Clear* — and its dashed edge
  against the non-text bar, in every theme (`tests/sweep_contrast.py`).
- **The demo deployment** gets a recipe: a node's pin with a long note, a line's pin, a
  branch with the *Why* card (`testing-the-gui.md`, Mode 2).
- **Nothing changes for the macOS client.**

## Alternatives considered

- **The marks**: a flag for *accepted*, which most tools give to what needs attention,
  and an eye, little-sister's own sign; an hourglass for *silenced*, which says *until*
  and not *quiet*, and a speaker struck through; a file or sliders for a configured rule —
  sliders kept for a value set on the page, later.
- **A chip's short form**: the mark most of them share, which misstates a mix; every
  job's mark, with or without its count, which grows with the mix; an umbrella, which
  reads less cleanly than the diamond at a chip's size.
- **The *why***: inside the Time card, whose time facts a big branch's list would bury;
  a tab of its own, a click from the page the chip's words promise the answer on; a
  panel on the wall, which a click that opens or closes a node competes with.
- **The index**: *Rules* at `/rules`, a word a deployment already writes for its
  packages' rule lists; *Maintenance* kept, one job's name over all four.
- **The words**: renaming the kind *muted* or *quieted* and leaving maintenance
  *silenced*, two words for maintenance and one nobody used for the kind.
- **The block on the wall**: the note's first line, a gist that still costs every block a
  line; the note whole, as built; *Note* in words, which costs a narrow card a line of its
  sentence; the card on a pause alone, which a viewer who never chose cards, a touch
  screen and a wall nobody touches never open; the note in the inspection card, which
  says what a node is, not what is done to it now; a panel of the whole node; the note
  opened in place, which moves the cards beneath and closes at the next refresh; the
  sentence as the button, which holds a link where a pin above stands.
- **The edge and fill**: a fill per theme — the idle tint in cyberpunk and dark, with 6 %
  of its ink in the light ones — a color pair to tune in every theme that says nothing
  the dashes do not; a fill with a solid edge, an idle box; a wash of the node's own ink,
  which makes the block part of the alarm; the page's card surface or the canvas, a
  stark hole in a node; frosted, illegible on the dark theme's vivid fills.
- **Edit and Clear**: both as marks, which puts the one act that cannot wait for a second
  look behind a glyph; both in words, which keeps words on a wall otherwise drawn in
  marks.
- **A configured rule's block** while it changes nothing: on every node it picks, for
  good, saying nothing of now; every block only while it acts, under which a silence
  blinks with the flapping it was set for.
- **A switch on the wall**: *hide handled* beside *hide ok* and *hide idle*, a candidate
  for later if a wall asks; *show as reported*, which gives every color two meanings.

