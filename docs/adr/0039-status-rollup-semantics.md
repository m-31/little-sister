# ADR-0039 — Status roll-up: how a parent derives its status

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-08-02; rules 1 to 4 and the explicit status
  decided 2026-06-20)
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (the boundary this
  derivation sits inside — *own*, *effective*, *contribution*),
  [ADR-0036](0036-addressable-reasons.md) (the same rule one level down, over an
  entry's virtual children), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (staleness, layered on top and never suppressed),
  [ADR-0124](0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)
  (whose `MAINTENANCE` cancels a subtree, and why a node's pinned lines do not),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (rule 4
  restated: a declared rule may transform what a part counts above),
  [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (decision 2: maintenance's own words, *silenced* left to the kind that holds a
  flapping thing)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A parent's status is derived from its own state and its children. The rules below were
first decided on 2026-06-20, to fix a first draft of `get_status_code()` that could
return the string `"warn"` and could downgrade an `ERROR`, and to settle what
`UNDEFINED` and `MAINTENANCE` do to the parent above them. Checks normally update
**leaves**, but some updaters — a satellite check — replace a whole **branch**, which is
what the explicit status below is for.

This is the pure derivation, over stored readings, with no policy in it:
[ADR-0032](0032-status-contribution-boundary.md) names the vocabulary it sits inside,
what a failing check becomes is [ADR-0040](0040-what-a-failing-check-becomes.md)'s, and
what an administrator's pin does is [ADR-0041](0041-maintenance-is-a-contribution-rule.md)'s.

## Decision

Effective status, computed bottom-up from a node's own code and its children's
contributions:

1. **Severity order** among *counted* statuses: `ERROR > WARN > OK`. A node is `OK`
   only if every counted child is `OK`.
2. **`UNDEFINED` means "not reported yet"** and is **ignored** when a parent
   accumulates — it never makes a parent `UNDEFINED`.
3. **`MAINTENANCE` contributes nothing** and cancels its subtree — a node's, by a pin
   on it or by its check's word for it. *Why* a node reads `MAINTENANCE` is
   [ADR-0041](0041-maintenance-is-a-contribution-rule.md)'s business; this rule only
   says what a parent does with one. A node whose lines are all pinned counts nothing
   for itself and cancels nothing: its lines are skipped as rule 5 skips a child in
   maintenance, and the nodes beneath it count as they would without them
   ([ADR-0124](0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)).
4. **Always a `StatusCode`, and the derived roll-up never downgrades.** An `ERROR`
   node with a `WARN` child stays `ERROR`. A rule **declared** at a node's boundary,
   over its children or on its lines may transform what a part counts above, visibly
   and attributably
   ([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)
   decision 9): the part keeps its true color under the rule's mark, and what a part
   shows is never transformed.
5. **When nothing is counted, the answer depends on why.** If any child was skipped
   *because it is in maintenance*, the parent reads `MAINTENANCE`; if the children
   merely have not reported, it stays `UNDEFINED`. A node all of whose parts a
   declared rule leaves out reads `UNDEFINED` too: it counts nothing, and nothing
   beneath it is in maintenance.

Rule 5 is what the rules of 2026-06-20 left open (their proposed default was
`UNDEFINED`), and it is answered against the model rather than by taste: the same
question already had an answer one level down, where a node whose **virtual** children —
its reason entries — are all pinned reads `MAINTENANCE` where nothing beneath it counts
either ([ADR-0036](0036-addressable-reasons.md) decision 7). Real and virtual children
may not read differently in one model. And the two facts are genuinely different:
*nothing under here is reporting because we put it in maintenance* is not *nothing
here has reported yet*, and only the first is something an operator did on purpose.

### An explicit (non-derived) node status

Normally a check updates a **leaf**. An updater that owns a whole **branch** may set
that branch node's status explicitly: on failure it sets `ERROR` and **drops its
children** (the subtree is no longer known), and it **must clear** that status —
replacing it with fresh data — once it can update the branch again. Whatever can stamp
an explicit branch status owns clearing it on recovery.

## Consequences

- `Status.get_status_code()` implements exactly this and nothing else. It is the *pure*
  derivation over stored readings, which [ADR-0032](0032-status-contribution-boundary.md)
  rule 3 requires of it; the contribution rules are applied in `StatusTree.snapshot`,
  and `StatusTree.effective()` reads the snapshot because *effective* is the snapshot's
  word.
- Rule 5 changes behavior: a container whose only children are pinned used to read
  `UNDEFINED` and now reads `MAINTENANCE`. Two tests moved with it.
- Staleness is layered **on top** and is never suppressed
  ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md),
  [ADR-0032](0032-status-contribution-boundary.md) rule 6): a node that stopped being
  observed contributes its reading degraded to at least `WARN`, whatever policy is
  holding it back.

## Alternatives considered

- **Treat `UNDEFINED` / `MAINTENANCE` as severities** in the worst-of comparison —
  rejected: "unknown" or "planned downtime" would mask or fake real problems.
- **Forbid an explicit inner-node status** (checks only ever touch leaves) — does not
  survive contact with satellite checks, whose branch can fail as a unit.
- **Keep rule 5 at `UNDEFINED`** — simpler, and it was the proposal of 2026-06-20. It
  loses the property that matters more: one model answering one question one way,
  whether the children are real or virtual.
