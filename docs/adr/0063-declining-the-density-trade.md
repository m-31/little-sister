# ADR-0063 — A node may decline the density trade (`show_when_quiet`)

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-08-22)
- **Related:** [ADR-0056](0056-stable-useful-dashboard-flow.md) (the density's
  chip and quiet-box fold, and the stability rule this must not disturb),
  [ADR-0012](0012-node-metadata.md) / [ADR-0017](0017-node-title.md) /
  [ADR-0055](0055-sibling-order.md) (the metadata lattice, and its non-prose
  precedent), [ADR-0025](0025-check-provided-subnode-metadata.md) (check-provided
  child metadata, fill-empty — and the text-layering reason its labels stay with the
  check), [ADR-0013](0013-check-config-on-node.md) (display metadata is not status),
  [ADR-0049](0049-the-check-authoring-surface.md) (what a name on the surface
  costs), [ADR-0029](0029-per-user-presentation-preferences.md) and
  [ADR-0062](0062-navigation-chrome-is-layout-behavior.md) (what stays the viewer's,
  and what was never a preference), [ADR-0019](0019-inspection-popover.md) (what a
  chip still offers), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (JSON
  envelope, unchanged here), [ADR-0061](0061-decoration-is-not-a-label.md) (a client draws its own chips),
  [ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md) (a
  child that says a run names it takes nothing declared for its name),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (the wall as
  a tree: a click, ▤ and the folds a declared node starts outside of),
  [ADR-0128](0128-where-a-nodes-first-look-comes-from.md) (the first look's addresses,
  `children:` among them, which the flag rides, and decision 8's big level, which starts
  as chips).
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The wall buys height by drawing quiet nodes small. The dense view did it with two
compactions (ADR-0056): a quiet leaf is painted as a name-and-state **chip** rather than
a box — "a chip trades at-a-glance quiet reason text for density" — and quiet full boxes
past `branch_cap` fold behind an in-place *+N more*. The tree that replaces it
([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)) does it by a
node's first look ([ADR-0128](0128-where-a-nodes-first-look-comes-from.md)): its
children start as chips where `chips` says so, or where nobody spoke for a level and it
is big, and its healthy ones folded where `fold_ok` does. Neither hides a failure: the
density exempts a warn/error node from both compactions, and in the tree a failing node
is a red chip where it does not open its way.

That prices every quiet node the same, and quiet nodes differ in what their lines
*are*. Most reason text is diagnostic: it explains a problem, so while the node is
quiet there is nothing to read and the chip costs nothing. But some checks' lines are
an **inventory** — the reading is the list itself. The `aws` check's `ec2` aspect is
the sharpest case: one line per instance name, how many carry it, how old the oldest
is. Those lines are read *because* everything is fine, and in dense view they are
visible only while something is wrong — beside an errored line the box shows the whole
inventory, while the quiet sibling account is a chip with its inventory hidden.
Visibility by accident of an error is exactly backwards for this content.

The check side already knows the distinction, in one direction. The same check's
`cloudwatch` aspect ships `show_healthy: false` — an OK line per alarm is a hundred
lines saying nothing — a check declaring its quiet lines *noise* and dropping them
itself. The opposite claim has nowhere to go: a check whose quiet lines are the
payload has no way to tell the surface not to trade them away.

Where such a fact would live is settled in general. What a node's content *means*
travels with the node as display metadata — `title`, `about`, the declared `order` —
fed by `nodes.yaml` over the check over unstated (ADR-0012 / ADR-0017 / ADR-0055,
ADR-0025 for a branch's children). What does **not** decide it is the viewer: the
preferences cookie changes nothing about what the surface *says*, only how it looks
(ADR-0029), and two viewers of one deployment do not disagree about whether an
inventory's quiet lines carry information. Two constraints bound the answer. It must
stay inside painting: chip-versus-box does not participate in card position, and the
flow model already prices every visible node as a full box (ADR-0056). And the half of
it a **deployment** writes must not need the check's cooperation to be read — which
subnode is an inventory in *this* estate is the deployment's statement, and a
statement a deployment could only make through a check release would put the type in
the deployment's lane.

## Decision

### 1. A node metadata field, named for the claim

A node grows optional boolean display metadata, **`show_when_quiet`**: *this node's
quiet lines are still information — a density mechanism must not hide them for being
quiet.* The name deliberately does not mention the chip. The chip is one surface's
current painting, a client rendering the tree draws its own (ADR-0061), and a field
whose value can only be explained by pointing at one template's condition would be
GUI configuration riding in the tree. This one is explained by pointing at the node's
lines. The keys that say how a node starts, `chips` among them (ADR-0128), may name
what the page does, because they are the web page's settings and ride in no tree; this
field rides in the snapshot, and so names its claim.

### 2. Sources and precedence — the labels' lattice, exactly

Per field, resolved exactly as `title` / `about` are — one chain for every key the
`subnodes:` block carries. For a check's **root** node: a `nodes.yaml` declaration
keyed by path **>** the inline `show_when_quiet:` key in the check's YAML **>**
unstated (the result's copy is root-ignored, like the labels — the root's declaration
is the inline key, and a result overruling it would put a check's code ahead of the
file the deployment edits). For a **child** node: `nodes.yaml` **>** the deployment's
`subnodes:` block in the check's YAML (`subnodes: {name: {show_when_quiet: …}}`)
**>** the type's **declared default** — an entry of the same `subnode_defaults` map
that declares the labels carries `show_when_quiet` beside `title` and `about`, so
the declaration mirrors the configuration key for key, and an aspect that is a
roster *by construction* (an `ec2` inventory, one line per instance) is declared
once in the type and inherited by every account of every installation — **>** the
value on the child `CheckResult`, the **dynamic-child channel**, stamped by the run
for a name no declaration could have anticipated **>** unstated. Each place also speaks
for every child of a node at once, by a `children:` block under the node's own entry —
in `nodes.yaml` under its path, in the deployment's block and the type's map under its
name, and for the children of the check's own node at the file's top level and in the
type's `node_defaults` — the addresses of the first look's keys
([ADR-0128](0128-where-a-nodes-first-look-comes-from.md) decision 3), where a child's
own name entry beats its parent's `children:` within one place and the places keep
their order. The deployment's block and the type's declared default reach a child by
its name where the child says nothing
([ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)); a child
that says a run names it, `dynamic=True`, takes nothing declared for its name and takes
its parent's `children:`, so a type declares the flag for a level runs name —
`batch: {children: {show_when_quiet: true}}` for every queue — where it would stamp
each result. With no `children:` above it, it takes the flag its own result carries, or
none, a `nodes.yaml` entry for its path still above it.

The mechanism is the seed-once / fill-empty write the lattice already uses, and the
field is a **tri-state** for the reason `order` is `None` rather than `0` when
unstated: `false` is a value an author may state on purpose, so a deployment's
`show_when_quiet: false` — in the block or in `nodes.yaml` — must occupy the field
where a `true` the type declared or stamped cannot fill over it. Unstated resolves to
today's behavior. A
value that is not a boolean refuses the load (`values.strict_flag` — `bool("false")`
is `True`, so a quoted YAML boolean would switch the node on while the file says
off); an entry stating only this field is still a declaration, so the startup
consistency pass warns for it when no check covers its path. A value freezes at the
node's first fill, and a changed declaration is a restart — the seed-time rule
ADR-0025 states.

### 3. The deployment's half is read by the library, not by the check

The `subnodes:` key for this field is a **common configuration field**:
`Check._parse_common` parses it for every type — the reader lives beside
`parse_subnodes` but is **not** on the check-authoring surface, because a check has
nothing to call it for — and hands the `{name: value}` map to the base constructor
through the same growing-common-fields contract every type already honors
(ADR-0049's `**kwargs` rule). `Check.__init__` merges the block's stated values over
the type's declared ones into one per-name map — exactly as it resolves the labels,
and in the same place, so a token of behavior and a line of text ride one
declaration — and the engine applies that map where it stores each child that says
nothing, by subnode **name at any depth**: one `disk: {show_when_quiet: true}` reaches
every host's `disk` leaf, which is the per-account copy-paste ADR-0025 closed for
labels. The map's value beats the one the child result carries, for the same reason
the root ignores its result copy: a declaration — the deployment's file first, the
type's map beneath it — beats what a run stamps. A `children:` statement names no path,
so the engine is handed the statements when the files load and applies them as it
stores each child, `nodes.yaml`'s among them (ADR-0128 decision 4); a parent's
`children:` beats what the child's own result stamps, a declaration over a stamp, for a
child a run names too.

Two consequences are the point, and one is the price. A deployment can state the
field for **any installed branch check** by editing its own YAML — a library upgrade
suffices, no plugin release; a check type's only part is declaring a default for an
aspect that is an inventory *by construction*, or stamping the one child only the
run can name. A reusable type therefore cannot
half-support the key: were the reader a per-type call, the first type that skipped it
would falsify the configuration reference silently — the key would parse, sit inert,
and read as "declared" to everyone who wrote it. The price is that the block's
*shape* is now the library's to validate on every type: a malformed `subnodes:` fails
the load even for a check that never reads the block itself, which is the fail-fast
side configuration errors are already on. The **labels** in the same block needed one
more step: layering them requires the type's default text and tokens
(`resolve_text`'s `{default}` extension and `{token}` expansion), which at first only
the check held — so the flag, which has no layering, moved first, and the labels
follow by declaring that text as data (ADR-0025). The
declaration then closes the loop in the other direction: once `subnode_defaults`
exists for the labels, the flag rides its entries too, and the type's half of the
block is one map, shaped like the block itself.

### 4. What it does: every fold the configuration sets, or the field lies

A declared node **starts open** whatever its parent's `chips` says, and **no healthy
fold the configuration sets** — its parent's or its own — hides it or its quiet lines
([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision 5).
The exemption holds against every level that starts as chips, a big one nobody spoke for
among them ([ADR-0128](0128-where-a-nodes-first-look-comes-from.md) decision 8): a
declared node starts open and counts as the box it draws.

The exemption is from every fold or from none: a node kept out of the chip and then
folded shows *less* than the chip did — exemption from one compaction and not the other
would make the field hide exactly what it promised to show. The declaration is per node
and does not cascade: a declared container keeps its own box, and its quiet children
start as their own first look says unless declared themselves.

A viewer's word is over the claim, for the tab: ▤ pressed on its parent closes it with
its siblings, a funnel pressed on its parent folds it with the other healthy children,
and its own funnel folds its quiet lines. And it moves cards: the planner prices the
first look ([ADR-0128](0128-where-a-nodes-first-look-comes-from.md) decision 6), and a
declared node is priced open, the box it starts as.

### 5. What it is not

- **Not status.** Storing it emits no event; it never enters aggregation or
  freshness (ADR-0013's grammar for display metadata).
- **Not an exemption from *hide idle*.** That filter is the viewer explicitly asking
  for problems only, and a declared node is still `OK`. The field re-weights
  density; it does not redefine idle. (Maintenance is different — not idle — and
  stays so.)
- **Not a preference, and no cookie key.** What a viewer closes or folds holds for the
  tab and no longer, in the tab's own map (ADR-0127 decision 9), and no per-node
  override joins the settings menu (the ADR-0029 / ADR-0062 line).
- **Not in the JSON envelope here.** The snapshot carries it and the web renders it;
  the envelope (ADR-0080) is unchanged, and a client drawing its own chips is
  entitled to its own decision (ADR-0061) until the field joins the contract as its
  own deliberate change. That change is
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md), where `show_when_quiet`
  ships as the tri-state it is — null where nobody said — so the client reads the
  declaration instead of guessing at it.

## Consequences

- A roster-shaped aspect is declared once — by the type, in the `subnode_defaults`
  entry that already labels it, or by a deployment in the `subnodes:` block of any
  installed type — and every account of every installation inherits it; a deployment
  takes any declaration back per name in the block or per path in `nodes.yaml`. No
  per-account copy-paste in either file: the case ADR-0025 closed for labels stays
  closed for this field, and a `nodes.yaml` that once carried the same `true` per
  account-path is left saying nothing.
- A behavior a deployment wants is a library upgrade plus its own YAML, never a
  plugin release. The check-authoring surface gains no reader for the key — one name
  (`values.strict_flag`) joins it instead, useful beyond this field.
- Chips remain the compact look a type, a deployment or a big level asks for. The
  field is for nodes whose quiet text is the reading; a wall of declared nodes is a
  configuration smell, not a mechanism failure, and the chips' height benefit shrinks by
  exactly as much as somebody declares.
- The planner gains nothing new to mispredict: a declared node is priced as the open
  box it always starts as.
- The tests that hold the whole are the open start under a parent's `chips`, the fold
  exemption, the per-field precedence across every place and its `children:`, the
  tri-state — an explicit `false` beating a declared or stamped `true` — a declared
  value beating a stamped one while a stamped value survives for an undeclared name,
  and a type that never heard of the key receiving a deployment's declaration anyway.

## Alternatives considered

- **`no_chip` / `chip: false`.** Names the widget, not the claim: false the day a
  surface compacts differently, meaningless to a client with its own painting — and
  on the wrong side of the line ADR-0056 drew when it rejected a `wide:` hint in
  `nodes.yaml`. That hint commanded one renderer's geometry, and so would this name.
- **A reader on the check-authoring surface**, for each check type to call and relay
  onto its child results. Rejected: it prices a deployment's statement at a plugin
  release, and it makes support invisible — the first type that skips the call
  leaves the key parsing cleanly and doing nothing, a silent no for every deployment
  that wrote it. A §11 name is epoch-priced contract (ADR-0049), and this one would
  buy a job the library can do once, for every type, in the seam that already has
  the check in hand.
- **The result stamp as the type's only channel.** It works — the engine reads a
  stamped `true` where nothing else speaks — but it states a static, type-inherent
  fact by re-shipping it on every run, from inside `run()`, where a reader of the
  type's declarations cannot see it; and it left the block's one asymmetry: labels
  declared, the flag stamped, so a deployment that wanted the type's claim without
  code ended up writing the same `true` per account-path into `nodes.yaml`.
  Declared beside the labels, a roster aspect is visible where its title is, and
  the stamp keeps the one job only it can do — the dynamically named child.
- **A per-node viewer pin** (a cookie key, or a chip clicked open persistently).
  Rejected by ADR-0029's own boundary: the cookie is presentation only, and this
  changes what is visible; a cookie would have to carry node paths; and it answers
  per browser a question that is about the node — the second machine, and every
  other viewer, would be wrong again.
- **A category (`nature: inventory`).** A taxonomy is a second decision hiding
  inside this one (ADR-0061's caution). The behavior is the whole claim, so declare
  the behavior.
- **Grading the inventory `WARN` so it stays a box.** The workaround available
  today, and the worst answer: it lies in the data to win a painting argument, it
  pollutes roll-up, events and the envelope, and a permanent yellow is a light
  people stop reading — the argument the `aws` check's `batch` grading already
  records against alarm fatigue.
- **Do nothing** — the detail is one click away, and the wall can be opened whole.
  True and beside the point: a click serves drill-down and the dashboard's job is the
  glance. An inventory read through one click per node per look is not glanceable, and
  opening everything spends the whole wall to un-hide two nodes.
- **Exempt declared nodes from *hide idle* too.** Rejected above: that filter
  answers to the viewer, and overriding an explicit "problems only" would make the
  field louder than the person at the screen.
