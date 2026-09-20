# ADR-0055 — Sibling order: alphabetical, unless somebody declares a rank

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-08-09)
- **Supersedes:** the *Node sibling ordering* entry in
  [`../decisions.md`](../decisions.md) (2026-06, no ADR of its own), whose decision
  is restated in full below
- **Related:** [ADR-0016](0016-node-addressing.md) (`name` is the derived last path
  segment being sorted), [ADR-0012](0012-node-metadata.md) (node metadata — where a
  deployment overrules what a check declared), [ADR-0024](0024-dashboard-layout.md)
  (positional stability, which rests on this order),
  [ADR-0008](0008-json-output-api.md) (the JSON envelope reads the same snapshot),
  [ADR-0036](0036-addressable-reasons.md) (a node's entries are **virtual** children
  and keep the check's own order — untouched here)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Sibling nodes arrive in **insertion order** — check and discovery order — which is
undetermined and not a useful order, so the tree has sorted them by name since 2026-06.
That decision is still right for the reason it was taken: the order must be a property
of the node set, not of whichever check happened to register first, and it must not
move when a status does.

But a **severity band set is inherently ordered**, and a name sort destroys exactly
that order. `wiz` renders `critical high informational low medium` — `informational`,
the band that means *nothing to do*, sits third, between `high` and `low`. `github`
renders `critical high low medium`: **`low` before `medium`**, which is not a cosmetic
complaint but a wrong statement about severity. The same loss shows wherever a check
emits a set with a natural sequence of its own: a host's `disk / memory / cpu / load`
is a narrative, and alphabetical files `load` in the middle of it. The bands know their
order; the display throws it away.

The original decision considered a check's curated leaf order and rejected preserving
it — "uniform alphabetical wins on predictability" — because the alternative on the
table was *insertion* order, which a check produces by accident. A rank a check states
**on purpose** is a different proposal, and it is the one this record accepts.

## Decision

### 1. Siblings sort by `(order, name)` — the original name order, with a rank in front

*(the name half restated from the superseded entry, 2026-06; the rank is new, 2026-08-09)*

Sort siblings by their **declared rank** first and then by **name**,
**case-insensitive** and **natural** — digit runs compared numerically, so `node2`
precedes `node10` — at **every level**. The sort happens once in the **snapshot**
(`tree._snapshot_subtree`, key `_sibling_key`) — the single point both the dashboard
and the JSON envelope read — so order is consistent everywhere and computed once; the
live tree keeps insertion order untouched.

**Ordering by the live grade stays rejected**, as it was in 2026-06: a row that
re-sorts on every poll cannot be read, and a card that moves when a status changes
breaks [ADR-0024](0024-dashboard-layout.md)'s positional rule. A rank is not a status.
It says what a node is *about* — the severity it collects when something turns up in
it — and a band's subject never moves, so neither does its rank.

### 2. The default is `0`, so saying nothing is exactly today's behavior

`CheckResult` grows `order: int = 0`, carried onto the node. A check that says nothing
gets `0` for every child and therefore precisely the order it had before this record
existed; a check that knows better pushes a band down (`order=1`) or pulls one up (a
negative value); ties break by name, so two checks under one container both default to
`0` and interleave alphabetically as they always did.

This is what keeps the 2026-06 concern answered: the rank is **declared, never
incidental**, so a check that never thought about order cannot accidentally publish its
loop. The declaration is the whole mechanism — one small field, set on purpose, absent
until it is. And alphabetical remains the default a reader can predict without reading
any check's source.

### 3. A rank is read on a result's **root** as well as its children

Deliberately unlike `name`, `about` and `title`, which
[ADR-0025](0025-check-provided-subnode-metadata.md) ignores on the result root. Those
are root-ignored because the root's labels are **authored**, not measured: they come
from the deployment's own files, and a check overwriting them would be code overruling
configuration. A rank is different in the one way that matters — the check is the thing
that *knows* the order, because the order is a property of what it reports (a severity
scale, a hardware narrative), and ignoring it on the root would leave a plain **leaf**
check unable to rank the node it owns. A rank is also not identity: it moves a node
within a row without changing where it lives or how it is addressed
([ADR-0016](0016-node-addressing.md)).

Configuration still wins, as it does for the labels: `order:` is readable **inline on
the check** as well as in `nodes.yaml` (decision 4), both are seeded at startup, and a
result's rank **fills an unset field only** — so a deployment overrules a check's rank
in the same file where it already overrules its title, and a later tick never rewrites
what it filled.

### 4. Configuration may override the rank, and a stated `0` is a real declaration

Node metadata is already where a deployment overrules what a check declared
([ADR-0012](0012-node-metadata.md)), and there is no reason ordering should be the one
thing it cannot reach. `order:` joins `about` and `title` in **both** places those
already live — the `nodes.yaml` per-path mapping, and inline on the check itself — with
the same per-field precedence, `nodes.yaml` **>** inline on the check **>** what a
`CheckResult` carries **>** unstated. The first two are seeded onto the tree at startup
before the first tick, which is what puts them ahead of the third. An inline key
reaches only the check's own root, which is the node that file is about; a branch's
subnodes are ranked from the result, where their names exist.

The node's field is therefore **nullable**: `None` means nobody said, and `0` is a rank
somebody stated. Without that distinction a deployment could push a node around but
never *lower* it back to the baseline, which is half an override. A **check** declaring
`0` is saying nothing, because `0` is what saying nothing means — so the engine passes
it as "unstated" and leaves the configuration free to speak. A non-numeric `order:` is
refused with the rest of the file's parse errors: a silently ignored rank would leave
the row in an order nobody chose.

**What `0` is not** is a request for alphabetical order, and it is worth saying plainly
because the shorthand is tempting. `0` is the rank the *unranked* carry, so a node
given it sorts **with** them — after every negative rank and before every positive one.
In a set a check ranked `1..5`, stating `order: 0` on one child moves that child to the
**front** of the row, not back to its alphabetical place. Handing a whole ranked set
back to the alphabet means stating `order: 0` on **every** sibling. The mechanism is
the plain one — a rank is a number and the sort is `(order, name)` — and the escape
hatch is real; it is just per node, not per set.

### 5. The JSON envelope's `children` order moves; the rank follows in the contract round

The envelope reads the same snapshot, so a ranked node's `children` order moves there
too. Order is not usually part of a contract
([ADR-0008](0008-json-output-api.md)) and the change is **accepted**: a client that
renders in received order will see it move, and what it sees is better.

This one is not left implicit, because the spec had actually promised it: `openapi.yaml`
said *children are returned in natural, case-insensitive name order*, and that sentence
is now `(rank, name)`. It is therefore a real, if small, incompatible change, handled
exactly as the nullable `timestamp` of [ADR-0027](0027-observation-timestamp-semantics.md)
was — `info.version` to **1.3.0**, `schema_version` staying **1**, and the formal bump
consolidated into the client-facing revision. The client repository re-syncs its copy of
`docs/api/`, which is the standing one-way obligation whenever that directory moves.

The rank as a **field** stays server-side at this point, with `reported_code`,
`report` and the run facts, and ships with them in the client contract round's single
`schema_version` decision. A client must not be shown a field one release and a rename
the next, and this one has no reason to be the exception that arrives piecemeal. That
round is [ADR-0080](0080-the-envelope-is-the-snapshot-published.md), and `order` is
published there beside them.

## Consequences

- The severity bands read in severity order — the defect that prompted this — and a
  host's aspects read as the narrative the check meant.
- **Every existing deployment is unchanged on upgrade.** Nothing declares a rank until
  somebody writes one, and the default reproduces the old sort exactly.
- [ADR-0024](0024-dashboard-layout.md)'s positional stability survives: a card's
  position stays a function of **the node set** — now the node set plus what its
  checks and its configuration declare, all of which are static — and never of a live
  status. That ADR's citation of *Node sibling ordering* in the register still
  resolves; the register entry points forward to this record.
- **A root rank reaches past nodes another check owns, and that is accepted.** Ranks
  are compared across the whole sibling set, so a plugin setting `order=-1` on its own
  root moves its card ahead of every unranked card on the wall — cards belonging to
  checks that said nothing and to types the deployment never chose. The plan's promise
  that ordering stays "check-independent" therefore holds for **children**, where a
  container's set is normally one check's to arrange, and no longer for **roots**,
  where the set is shared. This is the price of decision 3 and is worth naming: an
  installed package can nudge a deployment's layout. It cannot do worse than nudge —
  the rank moves a card within the wall and changes no status, no path and no
  identity — and the deployment's answer is the same one it has for a title it
  dislikes: state `order:` for that node, in `nodes.yaml` or beside the check, and
  configuration wins. A deployment that wants the whole wall alphabetical states
  `order: 0` on each top-level node.
- A node's entries are **virtual** children ([ADR-0036](0036-addressable-reasons.md))
  and keep the check's own order; nothing here touches them.
- The rank is on `StatusSnapshot`, so a surface can see the order it was handed rather
  than infer it — but reading it is not required to render, because the snapshot
  arrives already sorted.

## Alternatives considered

- **Name the bands `1-critical`, `2-high`.** Rejected: the name is the path, the slug
  and the pin key ([ADR-0016](0016-node-addressing.md)), so a rename is a breaking
  change for every deployment that has pinned or linked one — a display problem paid
  for with an identity change.
- **Sort by the live status grade.** Rejected in 2026-06 and rejected again: it jumps
  on every poll and moves cards under the reader.
- **Preserve the check's insertion order for children.** Rejected in 2026-06 and still
  rejected — it is undetermined, it is not a decision anybody made, and a check would
  publish its loop without meaning to. A declared rank is the same wish with the
  accident removed.
- **A per-node `sort:` in `settings.yaml`.** Rejected: ordering belongs beside the node
  it orders, which is where its labels already are, and a third location for node facts
  would need its own precedence rule.
- **`order:` only in `nodes.yaml`, ignored inline on a check.** Rejected, and it is
  what the first cut did. Unknown keys in a check file are ignored generally, so an
  `order: 2` written beside that check's own `title:` and `about:` vanished without a
  word — in the one file where a deployment states the other two facts about the very
  same node. It is the same objection decision 4 makes against a silently ignored
  non-numeric rank, and it costs about ten lines to answer, because the per-field merge
  and the startup seed already exist for the labels.
- **Warn instead, and keep the single source.** Rejected as the answer, though it would
  have closed the silence: it tells a deployment *no* to something the two keys beside
  it allow, and the reason for the asymmetry would have to be explained wherever the
  three are documented together.
- **Emit `order` in the JSON now.** Rejected — see decision 5.
