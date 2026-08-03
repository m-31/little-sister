# ADR-0039 — Status roll-up: how a parent derives its status

- **Status:** Accepted
- **Date:** 2026-08-02
- **Supersedes:** [ADR-0004](0004-status-aggregation-semantics.md) (its roll-up half;
  the *failing check* half is [ADR-0040](0040-what-a-failing-check-becomes.md) and the
  `MAINTENANCE` half is [ADR-0041](0041-maintenance-is-a-contribution-rule.md))
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (the boundary this
  derivation sits inside — *own*, *effective*, *contribution*),
  [ADR-0036](0036-addressable-reasons.md) (the same rule one level down, over an
  entry's virtual children), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (staleness, the one transform applied on top)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

ADR-0004 was written to fix a buggy `get_status_code()` and ended up carrying three
unrelated decisions: how a parent accumulates, what a failing check becomes, and what
an administrator's `MAINTENANCE` does. [ADR-0032](0032-status-contribution-boundary.md)
named the vocabulary those three were talking past each other in, and promised the
split once maintenance became a real contribution rule. It has, so this is the first
of the three pieces: the pure derivation, over stored readings, with no policy in it.

## Decision

Effective status, computed bottom-up from a node's own code and its children's
contributions:

1. **Severity order** among *counted* statuses: `ERROR > WARN > OK`. A node is `OK`
   only if every counted child is `OK`.
2. **`UNDEFINED` means "not reported yet"** and is **ignored** when a parent
   accumulates — it never makes a parent `UNDEFINED`.
3. **`MAINTENANCE` contributes nothing** and cancels its subtree. *Why* a node reads
   `MAINTENANCE` is [ADR-0041](0041-maintenance-is-a-contribution-rule.md)'s business;
   this rule only says what a parent does with one.
4. **Always a `StatusCode`, never a downgrade.** An `ERROR` node with a `WARN` child
   stays `ERROR`.
5. **When nothing is counted, the answer depends on why.** If any child was skipped
   *because it is silenced*, the parent reads `MAINTENANCE`; if the children merely
   have not reported, it stays `UNDEFINED`.

Rule 5 is what ADR-0004 left open ("*Edge case to confirm … proposed default:
`UNDEFINED`"), and it is answered against the model rather than by taste: the same
question already had an answer one level down, where a node whose **virtual** children
— its reason entries — are all pinned reads `MAINTENANCE`
([ADR-0036](0036-addressable-reasons.md) decision 7). Real and virtual children may
not read differently in one model. And the two facts are genuinely different: *nothing
under here is reporting because we silenced it* is not *nothing here has reported yet*,
and only the first is something an operator did on purpose.

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
- **Keep rule 5 at `UNDEFINED`** — simpler, and it was ADR-0004's own proposal. It
  loses the property that matters more: one model answering one question one way,
  whether the children are real or virtual.
