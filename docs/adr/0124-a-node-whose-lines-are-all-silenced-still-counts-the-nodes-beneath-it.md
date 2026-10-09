# ADR-0124 — A node whose lines are all silenced still counts the nodes beneath it

- **Status:** Accepted
- **Date:** 2026-10-10
- **Related:** [ADR-0036](0036-addressable-reasons.md) (decision 7, a node's lines
  are its virtual children, which this amends for a node above others; decision 10,
  quiet is visible; decision 12, a line is pinned on a leaf's page),
  [ADR-0039](0039-status-rollup-semantics.md) (rule 3, what `MAINTENANCE` cancels,
  and rule 5 with the sentence beside it — real and virtual children may not read
  differently), [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (decision 5,
  staleness under a pin), [ADR-0042](0042-entries-carry-their-own-code.md) (a line
  never declares `MAINTENANCE`),
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (an aspect's
  line above a node for every subject),
  [ADR-0123](0123-a-node-says-one-status-wherever-it-is-read.md) (decisions 1 to 3,
  what a node says and whose it is),
  [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) (decision
  5, a branch's document, which this amends),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 5, a transform stays visible)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node's lines are its children too: each line that is not silenced contributes, a
pinned one contributes nothing, and a node whose lines are all pinned presents
`MAINTENANCE` (ADR-0036 decision 7). A node that presents `MAINTENANCE` cancels what is
beneath it (ADR-0039 rule 3), and the roll-up took the node's own `MAINTENANCE` as that,
whatever made it so: a pin on the node, its check's word, or its lines all pinned.

The first of the two was written when a node with lines had nothing beneath it. Since
ADR-0106 an aspect's node carries a line of its own — its scope, or a region that
cannot be read — above a node for every subject, and it is often its one line. A line
is pinned on a leaf's page only (ADR-0036 decision 12), so the case comes about where a
node was a leaf when its line was pinned and has nodes beneath it now: a subject list
that was empty and has filled, or a package release that gives an aspect nodes for its
subjects. The pin's form said *Maintenance for this line only. No other line is left to
alarm.*, and from then on the tree silenced every node beneath that node, while the
node's page said *maintenance* and named no pin on it.

ADR-0039 had stated the model the roll-up departed from, beside rule 5: real and
virtual children may not read differently in one model. A child in maintenance counts
nothing and leaves its siblings counted; a node's lines in maintenance did not. It was
seen while the family plan's slice 55 was built, where a test held the tree's answer as
it stood; none of the deployments' saved states held such a pin when they were read.

## Decision

### 1. A node's silenced lines silence its own part, and nothing beneath it

A node whose lines are all silenced has an own status of `MAINTENANCE`, as ADR-0036
decision 7 has it, and that counts nothing and cancels nothing: its lines are skipped as
a silenced child is, the nodes beneath it count as they would without them, and the
node shows what they roll up to. It shows `MAINTENANCE` whole only where nothing
beneath it counts either — ADR-0039 rule 5, which is also what a node with every line
pinned and nothing beneath it reads, as it did.

What cancels what is beneath a node is a pin on the node, or its check's word for the
node: a reported `MAINTENANCE`, the lines that declare no code of their own and carry it
included. A line cannot say `MAINTENANCE` of itself (ADR-0042), so a line is silenced by
its pin alone — and a pin on a line is for that line, wherever its node stands in the
tree when the pin applies.

### 2. Whether a node cancels what is beneath it is said once

One expression decides whether what a node counts for itself cancels what is beneath
it, and the roll-up reads it. The snapshot reads it again of the fields it was given:
for whether the node counts the nodes beneath it (ADR-0123 decision 3), and for whether
its lines are all silenced, which a surface asks before it says where what the node
shows comes from. So no surface can say that a node counts what is beneath it where the
roll-up did not.

That holds of the one other node whose own status is `MAINTENANCE` while it counts
something else: a node pinned whose own reading has gone stale counts that reading
degraded (ADR-0041 decision 5), which cancels nothing, and the nodes beneath it have
counted since that record. Its Time card names its period its own too.

### 3. The surfaces say what it shows, and that its lines are silenced

Its head, its card and its box say what it rolls up to, pale where that is derived
(ADR-0123 decisions 1 and 2). The reading a *maintenance* stands over — *· ok* beside
the word — is added only where the node shows *maintenance*. Its Time card says where
what it shows comes from — *Status error, from load-fixtures beneath it, error since …*
— and *Its own status maintenance since …* (ADR-0123 decision 3). Its Copy document
says where what it shows comes from: *Shown as: error ⛔
— rolled up from the 3 nodes beneath it. Every line of its own is silenced.* Its lines
keep their maintenance tint and their count (ADR-0036 decision 10), and an outline
lists its own part as *maintenance*, as it did.

## Consequences

- **A line's pin no longer silences the nodes beneath its node.** On an instance
  upgraded from 0.3.19, what such a pin silenced alarms again. A pin on the node is the
  way to silence what is beneath it, and its form says *and everything beneath it*. The
  release notes say so.
- **The API's `code` of such a node is what the nodes beneath it roll up to.** `own`
  stays `MAINTENANCE` and `reported` the reading — the three fields of ADR-0080
  decision 2, unchanged.
- **The events do not move.** Pinning a node's last line is a row of that node, its
  own status, and nothing above it writes one (ADR-0123 decision 4).
- **A pinned node whose own reading went stale** reads *Its own status maintenance
  since …* where it read *Status maintenance since …*, and its head no longer adds the
  reported reading beside the degraded one it shows.
- **ADR-0036 decision 7, ADR-0039 rule 3 and ADR-0115 decision 5 carry an update**,
  and ADR-0123, which has not shipped, says it in place.
- **One test file reads the node on every surface** with its one line pinned above a
  node that fails, and the tree's tests hold what still cancels.

## Alternatives considered

- **Today's rule, said on the form.** The form stands on a leaf's page, where nothing
  is beneath yet to warn of; the case comes about later, when the pin applies to a node
  that has grown.
- **A line's pin suspended once its node has nodes beneath it.** It drops the silence
  the operator set on the line at the moment the node grows, and makes what a pin does
  depend on the shape of the tree at a later run.
- **The node read as one that declares nothing.** Its `UNDEFINED` would be skipped as
  well, and lose what ADR-0032 rule 5 keeps visible: that a line is silenced.
- **Each surface deciding whether a node in maintenance cancels.** Three of them read
  the node's own status for it already; one expression is what ADR-0123 decision 2 made
  of the same kind of question.
