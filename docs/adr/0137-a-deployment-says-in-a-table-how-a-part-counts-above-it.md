# ADR-0137 — A deployment says in a table how a part of its tree counts above it

- **Status:** Accepted
- **Date:** 2026-10-24
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (the contribution
  boundary these rules act at — rules 5 to 8),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up — rule 4 restated),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (what every rule owes the page, which these take as it stands — decisions 5, 6, 8 and
  10 completed), [ADR-0031](0031-deployment-config-directory.md) (the aspect, and
  `config/` the operator's read-only input),
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (damping, whose count the table
  maps), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (staleness, and the
  instance's own branch), [ADR-0036](0036-addressable-reasons.md) (a line's address, and
  lines as virtual children), [ADR-0129](0129-a-rule-list-is-the-librarys-and-a-value-matches-it-exactly.md)
  (a rule list read in order, the first deciding — the form of decisions 2, 3 and 8),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (decision 8, a rule the
  configuration declares carries no buttons),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (the rows a rule marks),
  [ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md) (the
  periods a branch keeps, read with the rules), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (`contribution`, and the contract's 2.11.0), [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  (decision 5, a status a text names drawn as its sign),
  [ADR-0029](0029-per-user-presentation-preferences.md) (`failures`, the budget a
  lowered part does not spend),
  [ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) (decision 7,
  `tag:`, the selector's other half)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Every count in the tree is worst-of, everywhere, without exception (ADR-0039), which is
right for a house and wrong for an estate: one red leaf on a test account turns the root
red, the root stays red, and the one bit everything else reads — the band, the macOS
client's alarm — stops meaning anything. ADR-0032 named the place where a rule may act,
what a node contributes to its parent apart from what it is, and the pin, damping
(ADR-0083) and the shield have acted there since. A deployment still had no way to say
how a part of its estate counts for good: that the develop account only advises, that
an account's EC2 warnings are the day's weather, that a band of findings counts as a
warning until it holds ten, that one replica of three may be down.

Those are the four cases a deployment of the family named, and they set the scope. The
first is a cap on what a part passes up; the second healing, the opposite mapping, on a
node's lines rather than on a node, since the ec2 aspect writes one line per instance;
the third a count over a node's lines; the fourth a count over a node's children,
quorum. None of them is a status of its own (ADR-0032 rule 4), and each is a judgment
about how the estate is built rather than about one part for now — a fact for the
deployment's reviewed and versioned configuration, where a person's judgment for a while
is a rule with an author and an end, set on the page with the kinds that come beside
maintenance.

ADR-0135 settled what every rule owes the page — every part keeping its true color under
its rule's mark, what it counts as shown one level up — on the rules there were, and
left the configured rules' half of it here: their block on the wall only while they act,
`aggregation` in the envelope and a line's `contribution`. The design was settled with
Lex by 2026-10-24, one question at a time. This record is that design as built; where
the build had to decide something the questions had not, it says so — *built so* — and
those were put to Lex with the landing. He took them by 2026-10-25, changing three: the
past is read with each rule from its `since:`, a floor holds nothing back, and a count's
tally says how many fail (decisions 10 and 11); and on his word a period a rule's
beginning began names the rule (decision 11). The selector's other half, `tag:`, came
with the tags (ADR-0139 decision 7).

## Decision

### 1. A rule is a table per status, and the table never reorders

A rule writes `counts_as:`, what a part reporting a status counts as above:
`{ERROR: WARN}` the cap, `{WARN: OK}` healing, `{WARN: ERROR}` the floor,
`{ERROR: WARN, WARN: OK}` one step down, `{WARN: OK, ERROR: OK}` everything as OK. The
codes are written in capitals and read in either case, in the spelling the family's maps
give a code. WARN and ERROR are its only keys: an OK part counts OK, since raising it
would report a failure nothing measured, and MAINTENANCE and UNDEFINED count nothing
already (ADR-0039 rules 2 and 3). A status the table does not name counts as itself, so
`counts_as: {}` counts every status as it reads — an exception, written above the rule
it excepts (decision 3). `counts_as: nothing` leaves the part out whatever it reports,
the one place `nothing` stands. A table under which a worse status would count for less
than a milder one is refused where the configuration loads (decision 8): `{ERROR: OK}`
alone counts a dead replica for less than a degraded one, and the quorum where one
failure is expected is `{WARN: OK, ERROR: OK}`.

### 2. The rules are the deployment's, in `aggregation.yaml`, every root's read, the last-named first

The rules are a configuration aspect of their own, `aggregation.yaml` in a root, a file
and never a directory (ADR-0031) — kept apart from `nodes.yaml`, which says how a node
looks and never what its status means. Every root's file is read, the root named last
first: a site's root named after a shared base decides wherever both pick one place, as
a later root wins everywhere else in the chain; within a file its order holds.

A rule writes `name:`, `counts_as:`, `note:` and `since:`, and what it picks — `under:`,
`tag:` or both (decision 4); it may write `lines:`, `children:` and `while_fewer_than:`,
and a key it does not know is refused. Its **name** is any text, unique across every
root's rules compared with case folded, as a package's rule list compares them (ADR-0129
decision 1): the startup record, a node's page, *Handled* and the Copy document call the
rule by it, and a name two rules share applies for neither, the startup record naming
both files — a duplicate cannot say which was meant. Its **note**, Markdown as a pin's
is, says why it stands. **`since:`** is the day it began to stand: a date, not a moment,
and none after today in the configured zone, since a rule applies from the start that
reads it and a day to come would only misplace it in the index; writing a new date is
how a rule is confirmed again. There is no `author:`: who set a configured rule is its
file in its root, and its history is the repository's.

The page never writes `config/`. A configured rule is changed in the configuration and
read at the next start, as every aspect is until a reload in place is built. A pin set
beside it acts first and leaves its table nothing to map (decision 5).

### 3. Where two rules pick one place, the first written decides, whole

The rules are read in order, and the first that picks a place decides there with its
table and its count, as a package's rule list does (ADR-0129 decision 1). A node's
boundary, its lines one by one and its children are three places, so a rule on a node
and a rule on its lines both act; two rules compete only at one part's top or on one
line. An exception is written above what it excepts — `/aws/sandbox` left out above a cap
on `/aws/*` — and may carry `{}`. A node's page names the rule that decided each place
and every other rule written for it, with its file.

### 4. A rule picks a part of the tree, and acts where the part begins, on its lines, or over its children

`under:` keeps the meaning it has in `config/actions.yaml`: the node it names and
everything beneath it, `*` standing for one whole segment, so that `/aws/*/ec2` names
every account's ec2 node. `tag:` picks every node that carries a tag, written for it or
for a node above it (ADR-0139 decision 2), and a rule that writes both picks a node both
pick — no other way to put two together, so that why a rule picked a node stays
answerable on the page. A rule writes one of them at least. Without `lines:` or
`children:` a rule acts on what the **top** of each part it picks passes to its parent —
the node it picks whose parent it does not: the node `under:` names, and beneath it, for
a rule with `tag:`, each node where the tag begins. Under the cap on `/aws/develop` a
red function stays red, its `lambda` and the account red under the rule's mark, and only
`/aws` counts amber; `under: /web/*` picks each child as a part of its own, and
`tag: develop` each part the tag is written for.

With `lines:` — `"*"`, quoted because YAML reads a bare `*` as an alias, or a list of
addresses — a rule acts on how the lines of every node it picks count in that node's own
status. An address is what a line's pin names (ADR-0036 decision 12), read off a line's
link or the envelope's `entries`. A derived one, `h-…`, is the line's wording, which
changes when the words do, and one with a `*` in it reads as a pattern and would match
nothing: both are refused, so that a meaning given later changes nothing a configuration
meant. A line a run does not report is no mistake — the rule waits for it, as a pin does
— and a node whose lines are prose has none a rule can name, its check giving them no
address. `children:` stands only beside a count (decision 7), since without one it is
`under: <node>/*` written another way.

A rule on a node at the root is refused, the root passing nothing up. The instance's
own branch, `/little-sister`, is out of every rule's reach: a rule naming it or a path
beneath it is refused, and a broader one — `under: /`, `/*`, a count over the root's
children — leaves it out in silence, so that no configuration can quiet the monitor's
report on itself (ADR-0005).

### 5. The table comes last at a node's boundary, and never beneath staleness

A rule on a node maps what the node would otherwise pass up: after damping, which holds
a worse code back until it repeats (ADR-0083), and after the pin, the shield and a node
not yet reported, which count nothing and leave the table nothing to map. A part whose
check stopped running never counts less than WARN above, whatever its table says
(ADR-0032 rule 6): healing or leaving out a part over a dead check still escalates.

`contribution.by` says `aggregation` — one word for every configured rule, the aspect's
name and the one the boundary has held for the rule since ADR-0032 named it — and names
the first rule whose change still reaches the parent: an ERROR held at WARN counts OK
under `{WARN: OK}` by damping, since without the hold it would count ERROR, and WARN
under `{ERROR: WARN}` by the table, which would count WARN without the hold. The
contract's *one per node, the first of these that applies* holds, read as the first
whose change the parent sees. A rule's name, table and note are the page's to say,
never a field a client switches on.

### 6. Every part keeps its true color, and a rule on lines changes what their node shows

A rule never changes the color of what it acts on (ADR-0135 decision 1): a capped node
stays red and a healed line amber, each under §. A rule on a node changes what its
parent counts of it. A rule on lines changes what their node shows, as a line's pin
does, each line keeping its color and the node showing what they count as: a line is a
child of its node (ADR-0032 decision 8), and what a part shows is never transformed,
one level down. A pinned line is the pin's — no rule's mark stands on it, and it counts
toward no count.

A node all of whose parts are left out — its every line by a rule on its lines, or its
every child by `under: <node>/*` — counts nothing and reads UNDEFINED, *nothing
counted*, as one whose parts have not reported does, real and virtual children alike
(ADR-0039 rule 5); MAINTENANCE stays the word for what a person put in maintenance.
*Built so.*

### 7. A rule may count: its table applies while fewer than N parts fail

`while_fewer_than: N` beside `lines:` counts the node's lines, and beside `children:`
the top's children, `"*"` or a list of names. The table applies only while fewer than N
of the parts the rule decides report a status the table names — ERROR for the cap, WARN
or ERROR for `{WARN: OK, ERROR: OK}` — and from N on every part counts as it is. The
rule reads as its sentence — every line's ERROR counts as WARN while fewer than ten fail
— and its block says how many do, *7 do*. A count needs `lines:` or `children:`, a
node's own boundary having nothing to count; an N of at least 2, below which the table
would never apply; and a table, since `counts_as: nothing` with a count would leave a
healthy node's parts out too, where `{WARN: OK, ERROR: OK}` says what is meant. A pinned
line counts toward no count, and the instance's own branch is no child of the root's
that a rule counts.

### 8. What cannot apply is said at the start, and what changes nothing now beside the rule

Nothing in the file stops the monitor. A rule that cannot apply — a key it does not
know, a table that reorders, a name missing or another rule's, no note, no date or one
to come, neither `under:` nor `tag:`, a part no configured check's mount reaches, a tag
that is none or one the configuration writes for no node, the instance's own branch, a
rule on a node at the root — does not apply, and the startup record says why: one line a
rule, every reason in it, on the instance's own node until the next start (ADR-0032
rule 7). A rule that does not apply fails toward alarming by itself, the alarm it was to
quiet staying. A file that is no mapping, or whose `rules:` is no list, applies nothing,
and the record says so.

At runtime a rule that picks nothing now, or decides nowhere because a rule written
before it decides, is no mistake — what it names comes and goes — and *Handled* says so
beside it with what it missed: the rule written before it that decides, or a path it
would pick with case folded, as ADR-0129 decision 5 says it of a package's rule list.
Nothing reaps a configured rule: `config/` is the operator's input, not the program's
state.

### 9. The derived roll-up never downgrades; a declared rule may, and says so

ADR-0039 rule 4, *always a `StatusCode`, never a downgrade*, is restated. The **derived**
roll-up never downgrades: an ERROR node with a WARN child stays ERROR. A rule
**declared** at a node's boundary, over its children or on its lines may transform what
a part counts above, visibly and attributably (ADR-0032 rules 5 and 7): the part keeps
its true color and its rule's mark, and every surface that shows what it counts as says
by what. What a part shows is never transformed.

### 10. On the page a configured rule is §, its block where it acts, and *By a rule*

A configured rule's mark is §, drawn as a path at the cues' height (ADR-0135
decision 1). Its block says one sentence — what it makes of its part, where, while fewer
than its count fail and how many do, and by which rule — each status drawn as its sign
(ADR-0133 decision 5): *{error} counts as {warn} above, by the rule develop advises*;
*On its lines, {warn} counts as {ok}*; *Of its children, {error} counts as {warn} while
fewer than 2 fail — 1 does*; on a child counted, *Among /web's children, …*. The tally
says how many fail — *7 do*, *none does*, and *12 do* on the page of a count reached —
never *of* its number, which reads as a share of the parts. Its edge is
dashed and it has no fill (ADR-0135 decision 5), and it has no buttons: it says where it
is configured — *Configured in config/aggregation.yaml since 2026-09-05* — since that is
where it is changed.

Standing on whatever fill its node's status gives it, where maintenance's block stands
on its own tint, its dashes are its ink at 75 %, as a head's squares' edges are, and its
note mark washes at 8 % under the pointer, a ring saying which is open: at maintenance's
65 % and 12 % a block on an amber or a green node fell under the non-text bar and AA in
four themes (`tests/sweep_contrast.py`). *Built so.*

- **On the wall** a block stands only while its rule changes a count, so that a block
  and ◇ follow one predicate (ADR-0135 decision 5), its note behind the note mark. A
  line it changes carries § before its words, its tooltip and its hidden text saying
  what the line counts as and by which rule.
- **On a node's page** every rule that picks a place at the node stands at the head
  whether it acts now or not, *changes nothing now* beside it where it does not, with
  the rules it decides over.
- **A closed chip** counts each part by its true color and ◇ counts each part a rule
  changes the count of — *4 handled: 1 line in maintenance, 3 by a rule* — the words
  *by a rule* the same for one part and for many. **The band's pill** counts the same
  beneath the page's root, the parts a rule changes now rather than the rules
  configured, which stand for good; its popover leads to *Handled*'s *By a rule*.
  *Built so.*
- **A branch's *why*** lists what a rule handles under *By a rule*, after *In
  maintenance*: each part, what it reads, what it counts and by which rule, since when.
- **Handled** gains *By a rule*: every configured rule, the longest standing first, its
  block with the part it picks named by its path, or as *what carries develop* — *what
  carries develop under /aws* where it writes both — and what it changes the count of
  now, each part linked — or *changes nothing now*, and why.
- **The Copy document** writes what is handled beneath a branch the same way, under
  *§ By a rule*.

A part a rule makes count for less spends no failure budget — a floor, which makes it
count for more, does — and the healthy fold folds nothing on which or beneath which a
rule changes a count (ADR-0135 decision 9).

### 11. A change a rule keeps from a parent is marked `aggregation`, and the past reads each rule from its day

`Event.suppressed_by` carries `aggregation` on a change of what a node shows that a
configured rule kept from its parent — one the node's contribution, named by the rule,
counts for less than the node shows: a cap, healing, the part left out, a count while it
holds — as damping's rows are marked, so that History and the Events page say it as they
say damping, and *held back* hides it. A floor holds nothing back: what it raised
reached the parent, as more. The mark is written once the write is whole, since a rule
on a node reads the roll-up and a count reads the node's siblings. A change of a reading
its node does not show, because a rule on its lines counts it for less, is a row of its
own, as one under a line's pin is (ADR-0107 decision 2), marked `aggregation`, and so is
its end where its start was. Where a floor on the lines raised what the node shows to at
least the reading, that row is no rule's: kept for what the check said, which a replay
reads and a shield on a dependency with it, and left off the Events page, which lists a
row its node showed or one a rule held back. Since a mark no longer says by itself
whether the node showed the change, a row carries `shown`, kept in the log only where it
differs from what its mark implies. *Built so*, the floor's rows on Lex's word.

A start that brings a rule — a new one, or a table edited — begins the period of each
branch it moves at that start, where what the rules make of the kept entries differs
from what the entries count without them: its cause `rule`, its `by` the node whose
count the rule changed, and the rule named (`Period.rule`), rather than a period begun
at the run that ends the entries' count and named by whichever unit ran last (ADR-0132
decision 3). A difference the rules do not make is left to the units' runs, as before.

The periods a branch keeps (ADR-0132) are read with each rule from where it began, the
past a restart replays included: from the start that brought it, while a period the tree
keeps says so, and else from the start of the day its `since:` names, in the configured
zone — so that History says what the wall showed. Where a rule begins inside the log, a
branch it moves begins a period there, named as a start names it. A rule removed, or its
table edited, is read as the file has it now, nothing keeping what it was, and a rule a
start brought counts from its day once no period keeps that start. *Built so*; that the
two say the rule, on Lex's word of 2026-10-25.

### 12. The envelope says it: 2.11.0

`contribution.by` gains `aggregation`, its code what the parent counts or null where it
counts nothing. Every entry gains `contribution`, the same object, saying what its node
counted of it — `maintenance` with a null code where it is pinned, `aggregation` where a
rule on its node's lines changes how it counts, and null on the rest, which count as
they read — so that the virtual children read as the real ones do. A node's and an
entry's own `code` stay what they read. A branch's `period` may say `rule` as its
`cause`, a rule's beginning (decision 11), and name the rule in `rule`, beside the `by`
of the node whose count it changed. The change is additive (ADR-0080 decision 2), the
contract's 2.11.0, and moves no major of its own: the contract that carries it is
`schema_version` 3, whose break is
[ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)'s
(decision 3). The macOS client reads a contribution's code and not its name, so the word
changes nothing there until it learns it.

## Consequences

- **ADR-0039 rule 4 is restated** (decision 9), and **ADR-0032** gains its declared
  rules: the cap, healing, the floor, a part left out and a count, at the boundary its
  decision 2 reserved, unusable ones refused by its rule 7.
- **ADR-0031** gains an aspect, `aggregation`, a file in each root, every root's rules
  read, the last-named first.
- **ADR-0139**'s tags select for the rules: a rule picks by `under:`, `tag:` or both, and
  the start hands the tree the tags before the rules, so that a `tag:` nothing is tagged
  with is refused.
- **ADR-0083**'s damping is mapped by the table, and a held change keeps its name where
  the hold is what the parent sees.
- **ADR-0104** decision 8's block without buttons, for a rule the configuration declares,
  is built; **ADR-0135** decisions 5, 6, 8 and 10 are completed — the configured block
  while it acts, ◇'s *by a rule*, *Handled*'s *By a rule*, and the envelope's word.
- **ADR-0107** gains the rows marked `aggregation` and the `shown` flag; **ADR-0080** the
  contract's 2.11.0, re-synced to the macOS client's copy.
- **ADR-0036 decision 8 and ADR-0042** waited for a pin with a threshold, `escapes`,
  which will not come: a pin holds its part whole, and the threshold returned as a
  configured rule's table, healing on a node's lines.
- **`config/aggregation.yaml` ships as an example** that applies nothing, every key
  shown in a comment, and the demo deployment gets rules and a recipe
  (`testing-the-gui.md`, Mode 2).
- **A rule changes with a restart.** The rules are read once, at the start, before the
  state is restored; a change to the file waits for the next start.

## Alternatives considered

- **The spelling**: a verb per job — `cap:`, `heal:`, `floor:`, `leave_out:` — which has
  no settled word for healing, leaves `floor:` without a direction and needs a rule for
  each pair, while the page would still explain each as the table; and the verbs as a
  shorthand for the table, two spellings of one thing to document, test and show.
- **Any mapping**, a table that may reorder, and **the cap alone**: the first counts a
  worse status for less than a milder one, the second leaves three of the four cases
  without a rule.
- **Where a rule is set**: in the configuration only, under which every judgment about
  one part for now is a deploy and stands for good; on the page only, under which a fact
  about the estate expires within a year. A rule the page sets is the kinds beside
  maintenance, later.
- **What the page does with a configured rule**: a suspension until a required end, or
  editing and deleting it there, which means the program writing `config/` or a record
  in `var/` that contradicts the file for good.
- **The order at a boundary**: the table before damping, the same counts worked out as a
  node is written, which has to read the configuration there; and a stale part mapped
  like any WARN, the order a naive build reaches by default, under which a check that
  stopped running counts nothing above.
- **Across the roots**: path-list order, as `actions.yaml` reads, under which the base
  wins, the opposite of every other override in the chain; the first root that has the
  file winning whole, which makes a site copy the base's file to add one rule.
- **What cannot apply**: a line on the instance's own node for a rule that picks nothing
  once every check has run, which turns it amber whenever an account goes, until
  somebody edits the file; and refusing to start, which takes the monitor down for a
  typo in a file where every other refusal drops the rule.
- **The name in `contribution.by`**: the mapping's kind, which a table that caps and
  heals at once does not have; the rule's own name, free text no client can switch on,
  which a rename changes.
- **The note and the date**: both optional, which fails quietly, a startup line standing
  at every start reading as background; the date taken from the file, whose change time
  is the deploy's, which would make every old rule look new.
- **Two rules at one place**: the most specific deciding, which needs an order between
  an exact path, a path with `*` and a tag that none of them has, and falls back to the
  file's order at a tie; the more alarming, status by status, which never lets a narrower
  rule quiet more than a broad one and cancels two rules that each quiet one status.
- **The lines' level**: a key naming the level, `on: node` or `on: lines`, two keys for
  one job and a default to write; the level in the table's key, `lines_count_as:`, which
  still has to say which lines and lets one rule carry two tables and two marks; `all`
  beside `"*"`, two spellings.
- **The count**: `count: {lines: 10}`, which says *lines* twice beside named lines and
  takes over the level's job; a word per case, `quorum:` and a threshold, two spellings
  of one rule.
- **The selector**: acting at every node picked, which caps a part's inner nodes too —
  `lambda` and the account amber over a red function, a red one has to dig for; a path
  naming nodes exactly, `path:`, which forks the vocabulary `actions.yaml` shares.
- **The name**: none, a rule called by its file, root and place, though under the first
  rule deciding a rule moves and one `under:` may carry two rules; an optional one, which
  leaves some rules without a handle and every surface needing a fallback.
- **A node all of whose parts are left out**: MAINTENANCE, the word for what a person put
  in maintenance on purpose, which a configured rule is not; OK, as a node healed whole
  reads, which would make `nothing` count as `{WARN: OK, ERROR: OK}` does everywhere and
  draw a node green over red parts nothing measured.
- **The pill**: the number of rules configured, which stands for good and says nothing
  of now; the rules acting now, which would add pins in parts and rules in rules and
  stand still while a rule that counts takes on more.
- **What is held back**: every change a rule touched, a floor's included, which holds
  back what it raised; only a change nothing of which reached the parent, which needs a
  mark of its own for what a capped change counted as and puts one rule's rows under
  both of the Events page's switches by status.
- **The past**: today's rules over the whole log, which tell a story nobody saw and
  count a rule before the day it says it began; the rules as they stood, each start
  writing the set it read into the log and the replay switching sets where the log does,
  right through an edit and a removal, for a new kind of row the Events page shows or
  hides and a replay that changes rules partway through the log — not decided against,
  but left to be decided, whether and when.
- **The tally**: *7 of 10*, which on a node of eight lines reads as a share of them, and
  says *12 of 10* where the count was reached.

