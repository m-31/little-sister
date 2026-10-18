# ADR-0118 — A child a run names says so, and takes nothing declared for its name

- **Status:** Accepted
- **Date:** 2026-10-18 (accepted 2026-10-04)
- **Related:** [ADR-0025](0025-check-provided-subnode-metadata.md) (decision 5: a label
  is declared for a subnode's name, and a result's own is the fallback — which this
  amends), [ADR-0063](0063-declining-the-density-trade.md) (decisions 2 and 3:
  `show_when_quiet` on the same lattice, applied by name at any depth — amended the same
  way), [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (decision 3:
  a subject's node is named by what its provider calls the thing),
  [ADR-0012](0012-node-metadata.md) and [ADR-0017](0017-node-title.md) (`nodes.yaml`,
  keyed by path, which stays above everything a check says),
  [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 1: a keyword that
  states a fact about a result and leaves what follows to the engine),
  [ADR-0049](0049-the-check-authoring-surface.md) (what a name on the surface costs),
  [ADR-0051](0051-what-startup-refuses.md) (decision 2, the epoch),
  [ADR-0128](0128-where-a-nodes-first-look-comes-from.md) (the first look's keys, on the
  same addresses, and `children:`)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check type declares the labels of the children it always emits — `title`, `about` and
`show_when_quiet`, in `subnode_defaults` — and a deployment retunes them in the
`subnodes:` block of the check's own file. Both are keyed by a subnode's **name**, and
the engine applies them to every node of that name, at any depth
([ADR-0025](0025-check-provided-subnode-metadata.md) decision 5,
[ADR-0063](0063-declining-the-density-trade.md) decision 3). That is what they are for:
one `disk:` entry reaches every host's `disk` leaf, one `ec2:` every account's. And what
is declared for a name beats what the node's own result carries, a declaration being
what a name *is* and a stamped value what one run said.

Both records knew the other kind of child — a volume, a repository, a tenant the run
discovered — and left it the result's own fields, *the dynamic-child channel*, read
where the map is silent for the child's name. They took for granted that the map is
silent there: that a name a run comes up with is never one a type declares.

It can be. A node is named by what its provider calls the thing
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 3), and a
provider calls a thing what somebody chose. A Lambda function called `batch`, a node
beneath `little-sister-aws`'s `lambda`, is shown under the `batch` aspect's title, with
that aspect's `about` and its `show_when_quiet`; the title its own result carries is not
read. An account called `ec2` wears that aspect's label wherever a check names several
accounts. `host-metrics` names a filesystem's node by its mount, so one mounted at
`/mnt/memory` wears the `memory` aspect's `about`.

The engine cannot tell the two kinds of child apart: it sees a name. The type can: it
writes the one name from a constant and the other from what it read.

## Decision

### 1. A child of a result says that a run names it

`CheckResult(name=…, dynamic=True)`: this node is named by its source, or by what a
deployment's configuration calls a thing — an account, a region — and not by the type's
own code. The word is the one both amended records already have for such a child. It is
`True` or `False`, and anything else refuses the result with a `CheckError`, as a quoted
flag is refused elsewhere: `"false"` reads as true. A result that says nothing is read
as before. The keyword is therefore additive, the check API's epoch does not move
([ADR-0051](0051-what-startup-refuses.md) decision 2), and a type says it in the release
where it hands back such a node, or in its next. It says it on every result it hands
back for the node, the one of a run that could not read it among them: what a run writes
fills an empty field and stays, so one result that leaves the word out lets what is
declared for the name in until the instance restarts.

### 2. Nothing declared for its name reaches it

Neither map is asked for the name of a child that says so: not the label and the flag
its type declares in `subnode_defaults`, and not the deployment's `subnodes:` block.
Both mean the child the type always emits under that name, and a function called `batch`
is not that child. This amends [ADR-0025](0025-check-provided-subnode-metadata.md)
decision 5 and [ADR-0063](0063-declining-the-density-trade.md) decisions 2 and 3: *by
name, at any depth* holds for a child that says nothing.

The keys of a node's first look ride the same addresses
([ADR-0128](0128-where-a-nodes-first-look-comes-from.md)), and a child that says so takes
nothing declared for its name there either. What its parent says under `children:` —
those keys and `show_when_quiet`, for each child of that node whatever its name — does
reach it: that is how a type or a deployment speaks for a level a run names. Whether a
run named a node is remembered beside the tree, for the page, and never on the
snapshot.

### 3. Its labels are the ones its result carries

`title`, `about` and `show_when_quiet` on its own `CheckResult`, each field for itself,
and nothing where the result carries none — but for `show_when_quiet` where its
parent's `children:` says it, which beats what its own result stamps, a declaration over
a stamp (decision 2). What those two records kept as a fallback is the one source a
type has for such a child's labels. A `nodes.yaml` entry for the node's path
beats it as it beats everything a check says, by being seeded before the first run, and
what a run writes still fills an empty field only.

### 4. It is said of one node

Of that node, and of none beneath it: a child of a dynamic node that says nothing is
read by its name. An account called `ec2` says so and shows its own title; the `ec2`
aspect beneath it says nothing and takes what is declared for it. On a result's root the
word is ignored, as the root's `name` and its labels are: a root is named by its check's
`path:` and labeled by its check's file.

### 5. `host-metrics` says it of a volume

Where `disk_path` is `all` or a list, each filesystem's node says that the host names
it, the leaf of a volume whose numbers did not arrive among them. It carries the `disk`
aspect's resolved `about`, as it did. `host-metrics` is the library's one type that
declares labels by name and hands back nodes its source names. A package's type says it
in a release of its own.

**`macos-memory` and `qnap-metrics` say nothing, and stay so.** The one names a leaf by
a process its deployment configured, the other by a drive's bay. Neither type declares a
label by name, so nothing a type declares can reach such a leaf. What can is an entry of
the deployment's own `subnodes:` block under that very name, written in a file that
knows the name, and the word would take that entry away.

## Consequences

- **ADR-0025 decision 5 and ADR-0063 decisions 2 and 3 are amended**, as decision 2 has
  it.
- **A type that says nothing behaves as before**, and so does every deployment of it.
- **A deployment labels a node a run names by its path**, in `nodes.yaml`, and no longer
  through `subnodes:` by the node's name, once the node's type says so. The block is the
  type's own vocabulary, retuned. No deployment of the family labeled such a node there.
- **A type has one more thing to say** where it names a node from what it read, and a
  type that forgets it has what it had: a wrong label only where a source calls a thing
  by a name the type declares.

## Alternatives considered

- **The same word, with the deployment's `subnodes:` block still reaching the node by
  its name.** It keeps one way to label a single function without writing a path. A
  deployment that retunes `batch:` and runs a function called `batch` then has the
  collision back, out of its own file.
- **The parent says it of all its children**, as it says that they are complete. Fewer
  places to say it. But it is a fact about the child, a parent with both kinds of child
  could not say it, and the channel it completes — a result's own labels — is the
  child's.
- **No word, and the engine infers it.** Each rule tried fails a case the family has.
  *A declared label does not nest* gives an account called `ec2` the aspect's label and
  takes it from the aspect beneath. *A node that stands for a subject is dynamic* takes
  the label from an aspect whose only line names one subject, and misses an account, a
  region and a volume, which stand for none.
- **A declaration keyed by a path** from the check's own node, as a measure's `node` is
  ([ADR-0096](0096-a-measure-names-its-node-and-its-things.md)). The `subnodes:` block's
  keys are names in every deployment's file, and a type whose aspects hang beneath a
  level its configuration names would declare one entry for every path.
- **Left as it was, with `nodes.yaml` as the way out.** An entry for the path wins
  today. It asks every deployment to notice a wrong label first.
