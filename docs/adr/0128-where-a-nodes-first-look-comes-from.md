# ADR-0128 — Where a node's first look comes from: `chips`, `fold_ok` and `reason_cap`

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-10-11)
- **Related:** [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  (the tree whose first look this decides), [ADR-0012](0012-node-metadata.md) and
  [ADR-0017](0017-node-title.md) (`nodes.yaml`, by path, above everything a check
  says), [ADR-0025](0025-check-provided-subnode-metadata.md) (a check's `subnodes:`
  block and its type's `subnode_defaults`, by name; the snapshot that stays
  provenance-free),
  [ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)
  (a child a run names takes nothing declared for its name),
  [ADR-0063](0063-declining-the-density-trade.md) (`show_when_quiet`, which stays a key
  of its own; decisions 2 to 4, amended),
  [ADR-0056](0056-stable-useful-dashboard-flow.md) (the flow model, which prices the
  first look; its line against a `wide:` hint),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope, which does
  not carry these keys), [ADR-0061](0061-decoration-is-not-a-label.md) (a client draws
  its own chips), [ADR-0049](0049-the-check-authoring-surface.md) (decision 5: adding a
  name is compatible) and [ADR-0051](0051-what-startup-refuses.md) (decision 2: an
  addition does not move the epoch),
  [ADR-0029](0029-per-user-presentation-preferences.md) (the looks that are the
  viewer's), [ADR-0015](0015-check-discovery-union.md) (the subtree a check owns beneath
  a mount it shares)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

In the tree of [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
every node starts closed or open, its healthy children and lines shown or folded, and
its box with a budget of lines. Something has to say which, per node, before anyone
clicks.

Dense mode said it for the whole wall, with no key a deployment could set; the line
budget and `branch_cap` were the deployment's, for every check alike; and the one
statement a deployment could make per node was `show_when_quiet` (ADR-0063), on the
lattice the labels follow — `nodes.yaml` by path, then the check's `subnodes:` block by
name, then the type's declared default, then what a run stamps.

Who knows which levels are big differs by level. A type knows its own: a GitHub type
that its workflow runs and repositories come in dozens, a cloud type that an account's
services are many and that four of them are rosters worth reading when all is well, a
security type that its severity bands are a ladder. A deployment knows its exceptions,
for one check or one path. And a container no check owns — a team, a site — has only
`nodes.yaml` to speak for it, as it has for its title.

Measured on one deployment's own tree, anonymized: as configured — a plausible first
set in which an account shows its services as chips, workflow runs and a repository
their children, the security bands are chips and an informational band's lines folded
— its wall is 3.1 screens of 900 pixels on a desk, that day's two failures left in
their chips, where the same tree opened everywhere is 11.2.

## Decision

### 1. Three keys say how a node starts

- **`chips`** — whether the node's children start as chips;
- **`fold_ok`** — whether its healthy children and lines start folded behind *✓ +N ok*;
- **`reason_cap`** — the line budget of its box.

For the first two `true` is the more compact look. They are flat, beside `title:`,
`show_when_quiet:` and `reading_cap:` in a check's file and beside `reason_cap` in
`settings.yaml`, where they read `chips: false` and `fold_ok: false`; `reason_cap` per
check takes `reading_cap`'s shape. They name what the page does with a node: the fold is
`fold_ok`, not `show_ok`, which would read as a second `show_when_quiet`.

### 2. The most specific statement wins, and a type ranks above `settings.yaml`

For each key of each node, the first statement found:

1. the viewer, for the tab (ADR-0127 decision 9);
2. `nodes.yaml`, the node's path: the only place a container no check speaks for gets
   a look of its own;
3. the check's own file: its subnodes by name, then the check's own node at the
   file's top level;
4. the type's declaration: `subnode_defaults` by name, and `node_defaults`, a new
   constructor keyword, for the type's own node, which no name reaches — a proposal,
   which the deployment takes back in the check's file;
5. `settings.yaml`, for everything nobody spoke for;
6. built in: open, its healthy shown, and the line budget's default — but a level that,
   opened, would draw more than thirty boxes starts as chips (decision 8).

Between the viewer's word and the files stand two defaults of a view: a node's page
opens its node's children as it arrives, and a `depth=` in the address closes a level
as the tab starts
([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decisions 7
and 8). Neither is remembered.

The type ranks above `settings.yaml` on purpose. `settings.yaml` has to state the
containers' look anyway, so ranked above the type it would decide every check whose
file is silent, and no type's proposal would ever reach the wall: on the real tree,
11.2 screens instead of 3.1. A deployment that wants to overrule every type at once
would get a key of its own, if one ever asks; the order does not flip for it.

### 3. On the labels' addresses, and `children:` under any of them

A key is said at an address the labels already have: a path in `nodes.yaml`, a subnode's
name — reaching every node of that name at any depth — and the check's own node at its
file's top level. Under any of them **`children:`** says the same keys for each child of
that node, whatever its name; within one file a child's own name entry beats its
parent's `children:`, and across the files the layers' order decides, so a `children:`
in `nodes.yaml` beats a name in a check's file. A child a run names takes nothing
declared for its name (ADR-0118) and does take its parent's `children:`, which is how
the look reaches a level a run names — an account, a queue, a repository. A GitHub type
would declare `actions: {chips: true, children: {chips: true}}`, its repositories and
each one's workflows as chips, and a deployment opens every repository's workflows with
`subnodes: {actions: {children: {chips: false}}}`. `children:` sits inside a name entry
or at a file's top level, never directly under `subnodes:`, where it would read as a
subnode called *children*.

The wall's root takes no key: its cards start open, and `chips: true` in
`settings.yaml` closes every level beneath them that nothing more specific speaks for.

### 4. `show_when_quiet` stays a key of its own, on the same addresses

Named for its claim (ADR-0063): a node that carries it starts open whatever its parent's
`chips` says, and no ✓ fold the configuration sets hides it or its quiet lines, though a
funnel the viewer presses folds them (ADR-0127 decision 5). It rides the same addresses,
`children:` included, so a type declares it for a level runs name —
`batch: {children: {show_when_quiet: true}}` for every queue — where it would stamp
each result; a deployment's `false` still takes it back. Where a child's own result
stamps it and its parent's `children:` declares it, the declaration wins, as a
declaration wins over what a run stamps (ADR-0063 decision 3) — for a child a run names
too, whose own result was its one source (ADR-0118 decision 3).

It stays what it is, a statement on the snapshot frozen at the node's first fill, so it
is resolved where the engine stores each child: from the check's file and the type, and
from `nodes.yaml`'s `children:`. Those name no path, so they cannot be seeded at startup
as `nodes.yaml`'s entries are: the engine is handed them when the files load and applies
them as it fills a node, and reads no file itself.

### 5. The keys are the web page's settings, never the snapshot's

They are read when the files load, as the caps are, and resolved for each render by
`little_sister.first_look`, which answers a `FirstLook` per node; they are never put on
the snapshot, so the envelope, which publishes it (ADR-0080), does not carry them.
`show_when_quiet` stays the one statement about display in the contract, and the macOS
client, which draws no tree, keeps its own look.

So they may name what the page does. ADR-0063 refused a name for the widget on a field
riding in the tree, and ADR-0056 a `wide:` hint as presentation in a deployment's
metadata; these keys are presentation on purpose, the web page's settings, and in no
tree.

The check whose file and type speak for a node is the one that writes it: the check
whose path the node is, or lies beneath, and beneath a mount two checks share, the one
whose own subtree the node is in — `owned_nodes()`, which the loader keeps apart
([ADR-0015](0015-check-discovery-union.md)) — so a host's two metrics checks each speak
for their own leaves. The mount's own look takes nothing from either check's file or
type: `nodes.yaml` speaks for it as for any container. Each of its children starts as
the check that writes it says of the children of its own node — `nodes.yaml`'s word for
the mount first, for every child alike, then that check's file and its type, then
`settings.yaml`. So a Mac's leaves are chips, `host-metrics`' and `macos-memory`'s each
by its own check's proposal, and a NAS's `smart` and `temperature` stand open beside
`host-metrics`' chips, `qnap-metrics` proposing nothing for the node. Whether a run
named a child is remembered beside the tree, never on the snapshot, so the snapshot
stays provenance-free (ADR-0025), and it is forgotten with a node a run removes; after a
restart it is known again as each run writes, and until then no child is matched by its
name. `nodes.yaml` is kept for the process's life.

### 6. The planner prices the first look

The flow model (ADR-0056) reads what layers 2 to 6 give each node, and a `depth=` in the
address, which arrives with the request: a closed node is a chip in its run, and each
run, where it stands among its level's boxes, a line of chips priced as the heading row
every node costs, at the level's width, the server's estimate from the names of all its
children (ADR-0127 decision 12); an open node is the box it always was. A level's boxes
beside a run of chips are priced at every track that fits, as a browser lays them out:
the run spans the tracks, so none is empty for auto-fit to drop. It never reads a status
— what the failure budget opens, what ✓ folds — and never a click, so no click moves a
card. Pricing every node open would give the width to the card with the most nodes,
whatever is open; pricing the viewer's look would plan the grid again on a click, for a
wall no shorter.

### 7. A bad value fails where that file's keys fail

In a check's file the booleans are strict flags and `reason_cap` is read as
`reading_cap` is: a bad value refuses the start and names the file. In `settings.yaml` a
bad value warns and gives way to the library's own. In `nodes.yaml` it keeps what a bad
entry does there today, a note at startup and the file unread. A type's declaration is
code, held by its tests, and one of the wrong kind refuses the check's construction,
naming its entry, as its `show_when_quiet` does. In each of them a key the loader does
not know warns at startup, naming the key and its file — for a type's declaration, the
type — where it was ignored in silence.

### 8. A level nobody spoke for starts as chips once it is big

The built-in look of decision 2 is open, its healthy shown — but a level that, opened,
would draw more than thirty boxes starts as chips, as `chips: true` would start it, its
failures the budget's to open
([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision 5)
and a node that claims `show_when_quiet` open (Lex's words of 2026-10-24). Its boxes are
counted all the way down, the deeper levels deciding first, so that a child counts what
it draws once it has decided: sixty pods stand as chips, and so do thirty repositories
with two workflows each and ten hosts of ten leaves, where seven repositories with their
build and deploy, twenty-one boxes, stand open. It reads the tree's shape alone, never a
status, the same on every screen, so the planner prices what it closes as it prices the
configured look (decision 6); every statement wins over it, `chips: false` in
`settings.yaml` among them, and the cards are never its.

Thirty is the library's (`first_look.BIG_LEVEL`): on both deployments' walls the
family's declarations leave it nothing to close at thirty, forty or fifty, where twenty
would close a team's checks on the tree mounted under its teams, and with nothing
declared it closes a run of twenty repositories, 83 boxes opened. `branch_cap` and
*+N more* go with the density whose rule they were, and a `branch_cap:` left in
`settings.yaml` is named at the start as no longer read.

## Consequences

- **A type proposes, a deployment overrides.** A family package declares its big levels
  once; every deployment of it inherits them and takes any back in the check's file, by
  name or for the check's own node, or per path in `nodes.yaml`. The library's own types
  that write a host's levels propose theirs: `host-metrics` a host's leaves as chips, by
  `node_defaults`, and a disk's filesystems where it fans out, by its `disk` entry;
  `qnap-metrics` its drives and its temperature sensors, its two branches open;
  `macos-memory` its leaves and its watched processes. Measured on a household's wall of
  nine hosts with the family's declarations, the wall reads 1,414, 1,195, 1,415 and
  3,427 pixels at 2,560, 1,920 and 1,280 pixels wide and on a phone, where with nothing
  declared for the hosts, and no level closed for being big, it reads 2,544, 3,585,
  4,674 and 7,550.
- **A deployment that says nothing sees more.** Built in, a node nobody speaks for
  starts open with its healthy shown, where dense mode closed its quiet leaves, and only
  a level of more than thirty boxes starts as chips, so a deployment's big levels are
  closed by its types or in its own files. The built-in look was drawn before the
  family's packages released their declarations, on Lex's word of 2026-10-25, so the
  release that brings it brings theirs on the same day, never after it, and says at the
  top of its notes that a deployment updates them with it and states its big levels.
- **The check-authoring surface grows by additions** — `node_defaults` for a type's own
  node, and the new keys and `children:` in `subnode_defaults` — so its epoch does not
  move (ADR-0049 decision 5, ADR-0051 decision 2); a package that uses them raises its
  floor.
- **The engine is handed one more thing**: the `children:` statements of
  `show_when_quiet` in `nodes.yaml`, loaded once. ADR-0025 declined coupling the engine
  to `nodes.yaml`, because seeding at startup gave the same precedence with none of the
  wiring; for a child no path names there is nothing to seed, and the coupling is
  accepted for that one statement.
- **What stays the deployment's alone:** `maintenance_cap`, since the strip it caps
  belongs to no check.
- **Amended:** ADR-0012, ADR-0025, ADR-0056, ADR-0063 and ADR-0118, each where it
  decided otherwise.

## Alternatives considered

- **`settings.yaml` above the types**: the general default would win wherever a
  check's file is silent, which is everywhere a type's proposal matters.
- **One `dense:` per node**, the deployment's switch moved down a level: one boolean
  cannot say *open, its healthy folded*, and it names a mode the tree no longer has.
- **A nested `display:` block**: one more level to write, for keys that otherwise sit
  where every key of a check's file sits.
- **The keys on the snapshot and in the envelope**: they are the web page's settings,
  and the contract would carry one surface's painting where `show_when_quiet` is its one
  statement about display; the macOS client draws no tree to apply them to.
- **Names only, without `children:`**: nothing would reach a level a run names, and a
  deployment would write one `nodes.yaml` path per repository, the copy-paste ADR-0025
  closed for labels.
- **A key that overrules every type at once**: later, if a deployment asks.
- **A host's healthy leaves folded** rather than chips: on the household's wall as tall
  at 2,560, 418 to 500 pixels taller at a desk below it and 308 on a phone, and naming
  no healthy leaf.
