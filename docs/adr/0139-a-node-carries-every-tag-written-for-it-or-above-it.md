# ADR-0139 — A node carries every tag written for it or above it

- **Status:** Accepted
- **Date:** 2026-10-25
- **Related:** [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  (decision 6, a node's details: the places a deployment writes them and how they come
  down — the same places, the other rule — and the *About* card the tags join),
  [ADR-0012](0012-node-metadata.md) (`nodes.yaml` — amended),
  [ADR-0025](0025-check-provided-subnode-metadata.md) (a check's file and its
  `subnodes:` block — amended),
  [ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md) (a child a
  run names, which nothing declared for its name reaches),
  [ADR-0031](0031-deployment-config-directory.md) (the `tags` aspect — amended),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (the
  rules' selector, which `tag:` joins), [ADR-0038](0038-declarative-action-list.md)
  (an action's `under` — amended), [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md)
  (the Events page's address — amended),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (the wall a
  tree, and its filters — amended), [ADR-0019](0019-inspection-popover.md) (the hover
  card — amended), [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md)
  (the Copy document — amended), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (the contract's 2.12.0 — amended), [ADR-0027](0027-observation-timestamp-semantics.md)
  (an aggregate synthesized upward, taken out once — why a tag never goes up)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The status tree is organized by what is monitored, and it is a strict hierarchy: a node
has one parent. An operator keeps wanting to slice it by things that are not that
hierarchy — which environment a node is, who owns it, where it sits, whether it faces
customers. Each is a fact about a node that does not follow the tree, and at least five
things want one answer to *which nodes do I mean?*: the configured rules (ADR-0137),
whose known limit is that an environment is a label rather than a subtree; a dashboard
composed of readouts; a notifier, which tells someone of a production failure and not of
a dev one; maintenance, for a rack that is no subtree; and a dependency stated once for
everything behind a VPN. Were each to grow its own answer, a deployment would learn five
ways to say *production*.

Asking *is production OK?* is a status over a set that is not a subtree — a roll-up
whose root is no node, with an address, a history and pins of its own still to decide.
That is not decided here. What is: tags exist, come down the tree, filter what the wall
already shows, and select for the rules, the actions and the Events page, in one
vocabulary. An earlier design round settled that a tag is no file of its own, comes down
the tree as a union, never goes up, warns where nobody named it, and that the vocabulary
stays small; the rules' walk-through added `*` for one segment. The rest was settled with
Lex on 2026-10-25, one question at a time — where a tag is written, the known tags, the
card, the filter, the envelope and what takes `tag:` — and he widened the first: a tag
is written wherever a detail is.

## Decision

### 1. A tag is a word a deployment writes for a node, a fact about its subject

A tag says what the node is — `production`, `database`, `berlin`, `customer-facing`,
`rack-4`, `behind-vpn` — stable, and true whether or not anything is broken. What a node
is doing — stale, pinned, failing — is never one: a selector over it would cover other
nodes from one minute to the next, and why a rule applied would stop being answerable.
Policy stays in what selects by tags: whether a production failure wakes somebody is a
rule over `tag: production`, never a tag `page`, so that a change of policy edits no
node's file. Only the deployment writes a tag; a check type gives none.

### 2. A tag is written wherever a detail is, and holds for every node beneath, added up

A deployment writes `tags:` — a list of words, or one word — in a check's file for the
check's own node, in its `subnodes:` block under an aspect's name, for every node of that
aspect at any depth as the aspect's labels reach (ADR-0025), a child a run names
excepted (ADR-0118), and in `nodes.yaml` by path: the three places it writes a node's
details (ADR-0133 decision 6). A node carries every tag written for it in any of them
and every tag written for a node above it. Everything adds up: no place wins, and none
can take a tag back — a subtree that needs other tags says that the tree is organized
against the grain, which is worth knowing — so a later configuration root adds to an
earlier one's tags rather than replacing them. A detail comes down key by key, the
nearest winning; a tag comes down as a union.

**A parent never acquires its children's tags.** `/system` with a production child and
a dev child is tagged neither; what wants *the tags under here* is asking for a status
computed over a selector. A tag written for a path no node stands at yet is the node's
when a run makes it, and the tags are read at the start, as every aspect is.

### 3. The known tags are `tags.yaml`, each with what it means, and a tag is a word

`tags` is a configuration aspect of its own, a file in a root (ADR-0031): a mapping of
each tag to one line that says what it means — `production: Serves customers; a failure
here is somebody's outage.` Every root's file is read and they add up, the later root's
line winning for a tag two of them name, each tag keeping the place it was first named
in. The file gives no node a tag. Its order is the one the wall's filter offers the tags
in and a node lists them in, the tags no file names after them by name.

A tag is lowercase letters and digits, with hyphens between them. Capitals are read as
lower case, so `Production` is `production`; a tag with any other character is not read,
and the startup record names where it is written, as it names one YAML reads as anything
but text — `yes` reads as true. A tag no file names still applies, and is named on the
startup record once, with where it is written — every tag, where no root has a file. The
line is what keeps a second word for one thing out: whoever reaches for `prod` finds
`production` defined as what they meant, which a list of names cannot say. Nothing about
a tag stops the monitor.

### 4. A node's *About* card shows its tags as one line of chips

Between the `about` and the details' rule (ADR-0133 decisions 1 and 6), every tag the
node carries, in its order, each chip's tooltip its line and, for a tag that comes down
from above, the node it is written on, the nearest, as a detail given down names the
node it is given on. A node with tags and nothing else has the card. A chip leads to the
wall filtered by its tag (decision 5). The wall's hover card names the tags in one line
(ADR-0019), and a node's Copy document lists them with their lines after its details
(ADR-0115).

One place on the page, beside the details designed with them: a detail and a tag that
say one thing stand side by side, where whoever wrote them sees it. On a node's page the
tags are reference — why a filter shows the node, why a rule picks it — and *what is
production* is the wall's question, so the card's place, the Status tab alone and low on
a phone, costs little.

### 5. A wall filtered by a tag draws the tagged parts as its cards

The nodes that carry a tag are whole subtrees, each topped by a node that carries it and
whose parent does not. Filtered — `?tag=production` — the wall draws each such top as a
card of its own, in the tree's order, with the path above it before its name
(`aws › live`), and nothing above it, so that every color on it is explained by what it
shows; a tag written on a top-level node gives exactly the card the unfiltered wall has.
A node's page filters what is beneath it: `/status/aws?tag=production` is production
under `/aws`, the page being the selector's `under:`, and the node itself stays in its
frame with its true status.

The filter is in the address and never in a cookie, as the Events page's are (ADR-0101
decision 1): unlike hide ok it hides failures, and a wall that came back filtered the
next morning would hide them from whoever forgot. A bookmark keeps it, and a kiosk's
address. The band offers one tag at a time beside hide ok and hide idle — the known tags
in their order, each with its line, then any other the configuration writes. A line
above the cards names the one chosen with its line, says which parts the filter hides
that fail — a filter changes what the page shows, never what is true — and leads back
to every node; it stands inside what the refresh redraws, so that what it hides stays
current, and on the kiosk too, which has no band to say so. *Built so.* Hide ok and hide
idle apply within it, and a chip counts what is beneath it unfiltered, as it does under
them (ADR-0127 decision 2). This is where a rule with `tag:` acts, at the top of each
part (decision 7), so a filtered wall shows the parts such a rule picks.

### 6. The envelope carries every tag a node carries: 2.12.0

`tags` joins a node's entry: the tags it carries, as text, those written for it and for
every node above it, in its card's order, and absent where it carries none. It is the
node's whole set rather than its own, unlike `details`, so that whether a node carries a
tag is asked of the node in hand — the root of a subtree fetched by its path among them,
whose nodes above are not in the response. The reason `details` are carried as given,
that a resolved row would hide which place a key took, has no counterpart in a union,
where a tag counts the same wherever it is written. The known tags' lines stay out of the
envelope until a client offers a filter. The change is additive: the contract's minor
version moves to 2.12.0 and `schema_version` stays 2 (ADR-0080 decision 2).

### 7. `tag:` picks for the rules, the actions and the Events page

What every consumer of a selection shares is small and frozen: `under:`, a node and
everything beneath it, `*` standing for one whole segment; `tag:`, one tag, every node
that carries it; and the two written together, both holding — an AND, with no OR, no
negation and no precedence, so that why a selector picked a node stays answerable on the
page. A configured rule writes `under:`, `tag:` or both (ADR-0137 decision 4), and acts
as before at the top of each part it picks, a node it picks whose parent it does not —
for a tag, where the tag begins — on its lines or over its children. An action writes
the same (ADR-0038). A `tag:` that the configuration writes for no node is refused at
the start, as an `under:` no check's mount reaches is: a selector that matches nothing
is a lie about coverage, not a no-op. One the configuration writes, on nothing the tree
holds now, picks nothing now, and *Handled* says so beside the rule.

The Events page takes `?tag=` beside its `?under=` (ADR-0101 decision 2) and lists the
changes of the nodes that carry it — what happened in production overnight. An event
whose node the tree no longer holds is matched by the tags written for its path and
above it, with those an aspect's name gives the nodes above it that the tree holds,
every one of which the node carried too: the one approximation — a tag an aspect's name
gave the node gone, or one gone above it, is not known — matches less where it errs and
never claims a tag a node did not carry.

## Consequences

- **ADR-0031** gains an aspect, `tags`, a file in each root, every root's read and added
  up; and a `nodes.yaml` entry's `tags` add up across the roots where its other fields
  follow the later root.
- **ADR-0012** and **ADR-0025**: `nodes.yaml`, a check's file and its `subnodes:` block
  gain `tags:`; a type declares none.
- **ADR-0133**'s *About* card gains its chips, **ADR-0019**'s hover card and
  **ADR-0115**'s Copy document a node's tags, and **ADR-0127**'s wall its filter.
- **ADR-0137**'s selector gains `tag:`; **ADR-0038**'s actions and **ADR-0101**'s Events
  page the same.
- **ADR-0080**: the contract's 2.12.0, re-synced to the macOS client's copy.
- **`config/tags.yaml` ships as an example** that names no tag, its shape shown in a
  comment, and the demo deployment gets tags on its nodes and their file
  (`testing-the-gui.md`, Mode 2).
- **What stays for later**: a status computed over a selector — *is production OK?* —
  and its identity, an address, a history, a pin; tags a check type seeds, which would
  fill what is empty as ADR-0025's labels do; a query by tag, a new resource shape; a pin
  on everything that carries a tag; and a dependency stated against one.
- **A tag changes with a restart**, as every aspect does until a reload in place is
  built.

## Alternatives considered

- **Where a tag is written**: `nodes.yaml` alone, one file per root to read for why a
  node carries a tag — a question the card's tooltip answers — under which tags would be
  the one thing a deployment writes away from the check, where the family's deployments
  keep their metadata; and the check's file without `subnodes:`, since tagging by an
  aspect's name is selection by type, beside the tags a check type would seed, and `*`
  reaches every account's ec2 in a rule. A `nodes.yaml` list replacing a check file's, by
  the labels' precedence, would have been a way to take a tag back.
- **Taking a tag back**: a negation, `-production`, which makes the order tags are
  resolved in load-bearing and why a node carries one unanswerable from the page.
- **Tags going up**: a parent acquiring its children's, under which `/system` would be
  production and dev at once and every selector would match nearly everything — the
  synthesized aggregate ADR-0027 took out once.
- **The known tags**: a list of names in `settings.yaml`, where a later root replaces an
  earlier one's whole list — the one place a later root would take a tag away — and which
  says nothing of what a tag means; no list, the startup record naming every tag written,
  which keeps the vocabulary in view and lets `prod` and `production` both stand; and a
  file keyed the other way, tag to selector, which makes a tag a rule rather than a fact.
- **The spelling**: any text compared with case folded, which lets a tag carry a space
  that an address and a selector must quote; and capitals refused rather than read as
  lower case, which would drop a node out of a selection for a letter's case.
- **On the page**: the band after the title, on every view of the node, which spends the
  room the `about` gave up there on what matters little once the page is open; and both
  the band and the card, which says every tag twice.
- **The filter**: the tree trimmed, the nodes above a tagged part drawn as the way to it,
  which are red over children that look green wherever the filter hid what fails — what
  a broken roll-up looks like; dimming the rest, under which nothing hides and a wall of
  four hundred nodes stays four hundred; and the filter kept in a cookie as hide ok is,
  which would bring a filtered wall back the next morning.
- **The envelope**: a node's own tags, as its details are, which a subtree fetched by its
  path cannot complete; and each tag with the node it is written on, several times the
  size, for what the card's tooltip says.
- **What takes `tag:`**: the rules alone, or the rules and the actions, the Events page
  waiting — which would split one vocabulary between the wall's address and the Events
  page's.

