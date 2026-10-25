# ADR-0133 — A node says what it is in a card, and at length in a handbook

- **Status:** Accepted
- **Date:** 2026-10-24
- **Related:** [ADR-0012](0012-node-metadata.md) (`about` and `description`, their
  sources and the startup pass — amended),
  [ADR-0025](0025-check-provided-subnode-metadata.md) (what a type declares and a
  deployment writes under `subnodes:`, `{default}` and a type's tokens — amended),
  [ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md) (a child a
  run names, and the volumes `host-metrics` names — amended),
  [ADR-0017](0017-node-title.md) (`title`, on the same sources),
  [ADR-0018](0018-markdown-rendering.md) (the renderer, which takes the links, the
  status signs and the anchors — amended), [ADR-0019](0019-inspection-popover.md) (the
  hover card — amended),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (decision 8:
  a node's page, its facts after its children and its `about` in the band — amended),
  [ADR-0044](0044-run-facts-on-the-node.md) (decision 8: the node's facts, which the
  card stands beside), [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (a
  node's tabs — amended),
  [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) (the Copy
  document, which gains a line and a block, and the address it says it was made from —
  amended), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope —
  amended), [ADR-0030](0030-curated-links.md) (the links page, and the runbooks it left
  to the nodes — amended), [ADR-0047](0047-node-notes-and-their-retention.md) (a node's
  notes, which a handbook is not),
  [ADR-0126](0126-a-line-is-a-template-over-its-record.md) and
  [ADR-0131](0131-a-type-declares-what-it-grades-and-the-library-grades-it.md) (a line's
  template and a level's `_reason`, which say what a reading holds),
  [ADR-0028](0028-design-tokens-and-themes.md) (the status tints a sign is drawn on),
  [ADR-0128](0128-where-a-nodes-first-look-comes-from.md) (the first look's keys, on the
  same addresses), [ADR-0076](0076-the-instance-node-is-a-branch.md) (the startup node
  the notes stand on), [ADR-0031](0031-deployment-config-directory.md) (the
  configuration directory a handbook's file is named in, whose table `handbook/` joins
  with its loader), [ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md)
  (a node's tags, which the card shows between its texts and its details)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node has two texts that say what it is. Its `description` says what its check does,
and its `about` has been, since [ADR-0012](0012-node-metadata.md), the note for its
location, kind and context, from `nodes.yaml` by path, the check's own file and what its
type declares ([ADR-0025](0025-check-provided-subnode-metadata.md)). In use the `about`
carries a short account and a long one at once. The hover card shows its first
paragraph; the longest in the family's deployments' files is 4,612 characters, a runbook
in all but name; and the packages' types ship theirs as references —
`little-sister-aws`'s `ec2` at 3,933 characters, `codepipeline` 3,804 and `lambda`
3,475, `little-sister-github`'s `actions` 1,654. Since
[ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision 8 the
`about` stands open beneath a node's name on every view of it, so on a phone a long one
is read before the node's status and takes most of the first screen; the startup pass
notes one past 400 characters, and every deployment's start names the packages'.

The two texts overlap where they should divide: `host-metrics`' `memory` says *Memory in
use* above *Percentage of RAM in use on the host*. And neither has room for what a team
asks of a node in an incident: whom to call and where its tickets go, its documentation,
the exact name of the object — an account, a region and a function; a server, the rack
it stands in and what it holds — what to do when it fails, and how to log in, a page
that many servers share. A place told level by level, a site, a room, an aisle, a rack,
a slot, has nowhere to go but every node's prose, and `host-metrics` copies `disk`'s
`about` onto every volume it names so that a volume says anything at all. A text that
says what to do when a node fails says it by colour — *Red:* — which a theme paints
otherwise and which a reader who cannot tell red from green cannot read. And a
deployment writes an aspect's `about` under `subnodes:` rather than in the aspect's own
block, because the library reads that block for every type alike (ADR-0025 decision 5),
and no record says whether what a deployment writes about an aspect belongs there or in
the aspect's block.

The design round with Lex of 2026-10-24 settled what follows, one question at a time, on
pictures drawn on the application's own pages from two deployments' nodes; what each
declined is under *Alternatives considered*.

## Decision

### 1. A node's short account stands in a card of its own, *About*

The card is headed *About*, as the facts' cards are. A node's `description` stands first
in it, muted, its `about` beneath, its tags as a line of chips
([ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 4), and
its details (decision 6) after a thin rule, as a table. It stands on the node's Status tab beside the node's facts
([ADR-0044](0044-run-facts-on-the-node.md) decision 8), after the node's children where
it has them, as the facts do: to the right of *Time* where the page is wide enough, the
facts keeping their measure, and at every width where it does not fit there among them,
before *Configuration*, which is there to look things up where the card answers what the
reader came with. A leaf's page widens from 820 pixels to about 1,300 to make the room;
a curve keeps its column and its width, the card beside *Time* reaching down beside it.
A node with nothing to show in it has no card, and its page stays as it is. The root is
a node as any other: its Status tab is the overview at `/status`, which has no facts,
and where the root says something of itself its card stands alone after its children, at
the wall's foot; where it says nothing — no deployment's root does today — the wall
stays as it is.

The `about` leaves the band, where it stood open on every view of the node, and the
`description` the head, where it stood beneath the row. The card is the Status tab's
alone: the node's other views — *Series*, *History*, *Handbook* and *Copy* — show none,
one click from *Status*. On a phone the node's status comes first.

### 2. The description says what is read, the about what to do

The two divide by what they say. The **description** says what the check reads or
checks, in a sentence, its type's or its check file's; the startup pass notes one past
about 160 characters, as it notes an `about` past 400, on the instance's startup node
([ADR-0076](0076-the-instance-node-is-a-branch.md)). The **about** says where the thing
stands, how to reach it and what to do — an instruction, in short. A type writes the
first steps that hold everywhere — a function's log group, GitHub's security overview, a
drive to replace — and a deployment replaces them, or extends them by writing
`{default}` where the type's text is to stand (ADR-0025 decision 5), as a team adds its
policy to a package's text. How to read a value is the description's or the handbook's
and never the about's, so that the two do not say one thing twice. What a reading holds
stays out of the about, which is fixed at its node's first fill: it is a line's, through
the line's template ([ADR-0126](0126-a-line-is-a-template-over-its-record.md)) and a
level's `_reason`
([ADR-0131](0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)), which
link into the handbook's section for what to do in that one condition. The hover card
shows the description where a node has no about.

The tokens a type offers its labels — `little-sister-github`'s `{owner}` and `{team}`
and its links into GitHub's security overview, `little-sister-aws`'s sentences on
pinning — are expanded in what is written of an aspect, by its type or by a deployment
under `subnodes:` ([ADR-0025](0025-check-provided-subnode-metadata.md)): its title, its
about and its handbook. What a type writes is also what its run hands a child — the
labels of a child no declaration can name, such as the band of a severity
`little-sister-wiz` finds and its map does not, a handbook file among them — and the
tokens expand there too, with the values the check was made with. A text `nodes.yaml`
writes by path, or a check's file for its own node, keeps a token as written.

### 3. At length, a node has a handbook, on a tab of its own

What a team writes at length about a node — its runbook, how to sign in, its policy, the
reference a package ships — is the node's `handbook`: text or a Markdown file, from the
`about`'s sources in the `about`'s precedence — `nodes.yaml` by path, over the check's
own file, its own node's `handbook:` and an aspect's under `subnodes:`, over what its
type declares and a run hands over. A deployment writes its runbooks as files, and a
package states its handbook as text in its type's declaration or as a file it ships. A
file is named where the handbook is stated — `handbook: handbook/ec2.md`, relative to
the configuration directory it is stated in
([ADR-0031](0031-deployment-config-directory.md)), a package's to the package — and
never found by a node's path: three accounts' `ec2` share one runbook, and a package
knows no deployment's paths. A single line ending in `.md` names a file, and anything
else is the text itself. The startup pass names a stated file that is missing and a file
in `handbook/` that nothing names; `handbook/` is an aspect of the configuration
directory, and joins ADR-0031's table of them when its loader lands, as that record has
it.

`{default}` works in a handbook as in an about: a deployment's handbook replaces its
type's, and where it writes `{default}` the type's stands there, so that a team puts its
own sign-in and policy before the package's reference or after it, and a deployment that
writes no handbook keeps the type's.

A handbook is read with the configuration, at a restart, as `nodes.yaml` is: an edited
runbook reaches a running instance with the deployment that restarts it — a commit and a
push on a cloud instance, an edit and a restart on a local one — and the startup pass's
note on a handbook goes with the fix and the restart.

It is read on a tab of its own, *Handbook*, at `/handbook/<path>`, after *Status*,
*Series* and *History* and before *Copy*, which stays last
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 3). The tab stands
only on a node that has a handbook, which the configuration says — and for a node a run
names, its first fill — so it never comes and goes with a reading. The tab and the hover
card say that a node has one, and nothing in the *About* card says it again. Its
headings are anchored as GitHub anchors them: `## Sign in` is `#sign-in`.

Elsewhere it is pointed to and never carried. A node's Copy document gains a line,
*Handbook*, with the tab's address, absolute as its *Dashboard* line is
([ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) decision 1),
so that whoever reads a ticket finds the runbook in one click; the API says of each node
whether it has one, by that address, and the macOS client opens it in the browser. Its
text is kept beside the tree, for its tab, and the node says only that it has one: the
envelope publishes what the snapshot holds
([ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1), and a client
that fetches the snapshot fetches no handbook. Nor is a handbook a node's notes
([ADR-0047](0047-node-notes-and-their-retention.md)), which an admin writes while the
instance runs and which outlive the node.

### 4. A text links its own node's handbook by a short form

A link written `handbook` leads to the top of the handbook of the node the text belongs
to, and `handbook#<section>` to a section of it: `/handbook/<path>#<section>`. A detail
belongs to the node it is given on, so a sign-in written once for every server beneath a
node leads into that node's handbook, a page every server beneath it shares. So a type's
description and a deployment's about under `subnodes:`, each said of every node of its
name, can link, and a path that moves takes its links along. The about and the
description link into the handbook's sections — how to sign in, what to do when a line
fails — so that the card holds the short version and the handbook the long one, some of
it said twice on purpose.

It is one rule in the Markdown renderer ([ADR-0018](0018-markdown-rendering.md)), which
is handed the node it renders for and rewrites the link where it already sets every
link's target: for every text of a node the page shows — the About card, a line, the
hover card — and for the handbook's own page, whose headings it anchors. The startup
pass names a link to a section its handbook does not have, or on a node that has none:
at the start for a check's own node and the nodes above it, whose handbooks and texts
the configuration alone gives; and for a node beneath a check's when a run first fills
it, its handbook and its texts — a type's description, its labels, what `nodes.yaml`
says of it — being known by then.

Where a node's text leaves the instance the short form is written out to its full
address, from the base each already links back with: the Copy document, which keeps a
line's Markdown as its check wrote it, from the address it says it was made from
(ADR-0115 decision 1), and `little-sister-jira`'s draft, which copies a node's lines
into an issue, as it writes its `dashboard:` line — the library offering the one
function both call, which the slot a draft is made in hands its filler bound to the
node, the address of its handbook written in
([ADR-0034](0034-template-slots-for-dependent-packages.md)). The API carries it raw, as
the envelope carries every text, and its
contract says what it means: the address of the node's handbook, which the envelope
carries, and the section. The macOS client resolves it as the page does.

### 5. A text names a status as `{error}`

A text names a status by the word the page shows it with, in a placeholder's braces:
`{ok}`, `{warn}`, `{error}`, `{maintenance}` and `{undefined}`, in either case, reserved
so that no type offers a token by those names. The renderer draws one as a small sign —
the status's cue and its word on the status's own tint, as a coded line paints its own
surface ([ADR-0028](0028-design-tokens-and-themes.md)) — readable on every theme and
glowing in cyberpunk's; so an about says `{error}:` where it said *Red:*. It holds in
every text the page shows — an about, a description, a detail, a handbook, a title, a
line, a maintenance note — one renderer drawing them all, GitHub's tables and
strikethrough among what it draws ([ADR-0018](0018-markdown-rendering.md) decision 14),
so that whoever writes a text never asks where it will stand. A line's own braces are
its template's ([ADR-0126](0126-a-line-is-a-template-over-its-record.md)), filled before
it is rendered. The Copy document and `little-sister-jira`'s draft write it out as the
Copy document writes a status, *error ⛔*, through the library's one function; the API
carries it raw, its contract saying what it means. A status word the page gains later —
an acknowledgment, a window — gives a text its placeholder with it.

### 6. A node's details are named values whose keys its team chooses

A node's `details` are named values, each a line of Markdown, whose keys the team
chooses; the card shows them as a table beneath the about, the key muted, and on a key
given down from above the node it comes from as its tooltip.

- **The type** gives each node it writes the details of its object — an account, a
  region, a function, a host, a bay — with each run, as it gives its description, the
  check's own node among them. They are their node's alone; on a node two checks share
  they are withheld, as what a run found is
  ([ADR-0044](0044-run-facts-on-the-node.md) decision 1).
- **The deployment** gives anything else — a contact, where tickets are filed, the
  documentation, a provider, a place, how to log in — in the check's file, an aspect's
  under its name in `subnodes:` (decision 7), and in `nodes.yaml` by path, which wins
  key by key.
- **A detail the deployment gives a node holds for every node beneath it**, key by key,
  the nearest winning. A place told level by level — a site, a room, an aisle, a rack, a
  slot — composes itself card by card; a contact holds for a subtree that one key
  overrides lower down; how to log in to a server is written once; and the details
  written under an aspect's name hold for every node a run names beneath it — a
  function, a bucket, a volume, a drive — which no deployment labels by path.
  `host-metrics` no longer copies `disk`'s `about` onto every volume it names. A key
  written with no value is a value too: it stands nowhere, there nor beneath where
  nothing nearer names it, so a subtree takes a key back.
- **In the card** the type's details stand first, in its order — the object — and then
  the deployment's, in the tree's order, the outermost first, those of one node in the
  order they are written, and the node's own last. A key stands once, where it is named
  highest, with its nearest value, the deployment's winning over the type's on the node
  itself: a team that names a contact at the top and another for its live account keeps
  the row where it was.

They travel. A node's Copy document gains a block, *Details*, its card's table as key
and value — the inherited ones among them, the links written out — and
`little-sister-jira`'s draft writes them above its `dashboard:` line, as the slot it is
made in hands its filler the card's rows written out, cut after the lines where a
draft is too long for its address: the object's name and whom to ask are what a
ticket needs, and a document pasted elsewhere is read where nobody opens the card. The
API carries each node's own details as the snapshot holds them, raw — the
type's and then the deployment's, each as given and each saying who gave it, since the
deployment's are given down and the type's stand first — and its contract says that what
the deployment gives holds for every node beneath its own, key by key, the nearest
winning, as it says what `handbook#` means: from them a client draws the card as the
page does.

### 7. What is shown of an aspect is written under `subnodes:`, what is checked in its type's blocks

A deployment writes what is shown of an aspect — its title, its about, its handbook, its
details and the keys of its first look
([ADR-0128](0128-where-a-nodes-first-look-comes-from.md)) — under `subnodes:`, which the
library reads for every type alike (ADR-0025 decision 5), and what is checked in the
type's own blocks, such as `little-sister-aws`'s `lambda:`: a split that mirrors the
description's and the about's. An aspect with no block of its own needs none, and the
details under an aspect's name are the one way besides `nodes.yaml`'s paths to reach the
nodes a run names beneath it.

## Consequences

- **A node's page shows its status first on a phone**, and its short account beside its
  facts at a desk. A leaf's page is wider; the facts keep their measure.
- **The library's types and the packages' rewrite their texts to the division**: an
  about becomes what to do, a sentence or a few; what it held at length moves into a
  handbook; and a description says what is read. The startup pass's note on an `about`
  past 400 characters stays and gains one on a `description` past 160.
- **`host-metrics`' volumes carry no copied `about`**: what holds for every volume of a
  host reaches them as the details given down to them (ADR-0118 decision 5 amended).
- **One renderer draws every text, and it knows the node it renders for**: it writes
  four things it did not — a short link resolved, a status's sign, GitHub's tables and
  strikethrough, and a handbook's anchored headings (ADR-0018 amended) — and a
  description renders as a block, as an about does. One function of the library writes
  the short form and the signs out where a text leaves the instance, the Copy document's
  lines, notes and titles among it.
- **A node gains `details` and says whether it has a handbook**, and the envelope
  carries both — the handbook as its tab's address, the details a node's own, raw, each
  saying who gave it — additively: the contract's minor version moves and
  `schema_version` stays 2 (ADR-0080 amended). The macOS client resolves the short form
  as the page does and opens a handbook in the browser.
- **The startup pass names more**: a handbook's file that is missing, a file in
  `handbook/` that nothing names, a link to a section a handbook lacks or on a node
  without one; a type's description is checked at its node's first fill.
- **Five token names are taken**: `ok`, `warn`, `error`, `maintenance` and `undefined`
  are no type's to offer.
- **The links page stays general helpers** (ADR-0030 amended): what concerns one node is
  its handbook and its details, and a node still grows no `links:` list.

## Alternatives considered

- **The handbook as text alone**, a runbook written and reviewed in YAML; **as a file
  alone**, every package shipping files for its shortest handbook; and **a file found by
  its node's path**, with or without a name that overrides it, which three accounts
  sharing one runbook cannot use, nor a package, which knows no deployment's paths.
- **A section folded beneath the lines of the node's status page**, which grows the page
  and puts the runbook beneath everything on a phone; and **a page of its own linked
  from the about alone**.
- **The handbook nowhere but on its tab**; and **its text in the Copy document and the
  API** — a runbook in a ticket's comment, and every handbook in every snapshot a client
  fetches.
- **A handbook's file read again while the instance runs**, as the links page's is
  ([ADR-0030](0030-curated-links.md) decision 7) — a stat each time its tab is opened,
  and a read when the file changed — which would move the checks a file's content can
  falsify off the startup record, whose lines stand until a restart, into lines of their
  own recomputed every tick; an edit reaches a running instance with its next deployment
  either way.
- **The card last on a narrow screen**, after the whole of a configuration — more than a
  phone's screen of it on an account's node; and **the about kept in the band**, the
  card carrying the description and the links alone, which leaves the about most of a
  phone's first screen.
- **The overview without a card**, which shows the root's `about` nowhere once it has
  left the band; and **the root's `about` kept in the overview's band**, the one
  exception to its leaving it.
- **The two texts divided by author** — the description the check's and the about the
  deployment's alone — which put a type's first steps into its description, a sentence
  then saying more than what is read, or a click away into its handbook; and **one of
  the two**, the about or else the description, which takes the check's sentence out of
  every card that has an about.
- **Both handbooks always**, the deployment's above the type's, which takes the order
  from the deployment and shows the type's reference where a team replaced it on
  purpose; and **replacing alone**, which copies the type's text to keep it and lets the
  copy age beside its source.
- **A token, `{handbook}`**, which the library resolves once per check where this needs
  a node, and which reads worse; **full addresses**, which break when a path moves and
  which neither a type nor an about said of every node of a name can write; and **the
  API writing the short form out**, which would make the envelope's text no longer the
  snapshot's — the first text the API changed — where a client has all it needs to
  resolve it.
- **Shortcodes, `:error:`**, which run into the colon that follows them; and **the words
  alone**, which leave the colour and the shape behind.
- **Signs and tables in a node's own texts alone**, a line, a title and a note kept
  CommonMark — which would have a writer ask where a text will stand, the same table
  drawn in an about and left as pipes in a line; **in a handbook alone**, a second
  renderer for one page; and **no tables**, a runbook's contacts written as a list.
- **A text of its own given down**, which a subtree cannot override and which carries no
  label; **free text alone**, the structure left to convention, which gives no table,
  nothing per key and nothing a ticket could take over; **fixed fields** — `contact:`,
  `docs:`, `access:` and the like — which put every team in one form; **the node's own
  details alone**, which leave the nodes a run names without a word; **the nearest about
  above**, which the tree picks rather than the deployment: a function would show its
  account's urgency and miss a sign-in one level higher, and every aspect of a node
  would repeat that node's overview; and **the about itself marked as meant for
  beneath**, which gives down an overview with the sign-in.
- **`properties`**, an inventory's word; **`annotations`**, a remark's, near the node's
  notes; and **`facts`**, which the cards of a node's page already are.
- **The nearest detail first throughout**, which reads a place as a postal address does
  and puts whom to call last.
- **A node's own details in one list that does not say who gave each**, from which a
  client would give a type's down and could not draw the card's order; **the type's
  and the deployment's under two keys**, the same under a second name; and **a type's
  given down too**, which leaves the card's order to need the marking all the same.
- **The details on the page alone**; and **in the Copy document without the draft**,
  which leaves a ticket to say what it is about by a path alone.
- **The about and the details in the aspect's own block**, which every type would have
  to take and hand on, the library knowing no type's blocks, and for which an aspect
  with nothing to set would need a block — `host-metrics` has none; and **both**, which
  would give one key two meanings in one block.

