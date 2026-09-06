# ADR-0032 — The contribution boundary: what a node shows and what it publishes

- **Status:** Accepted
- **Date:** 2026-08-23 (accepted 2026-08-01)
- **Related:** [ADR-0004](0004-status-aggregation-semantics.md) (the roll-up this
  names a second half of), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (staleness — the first and, today, only transform),
  [ADR-0002](0002-rlock-snapshot-synchronization.md) (the snapshot this happens in),
  [ADR-0008](0008-json-output-api.md) (the envelope that already carries both codes),
  [ADR-0014](0014-maintenance-persistence.md) (the one implementation that once
  breaks the rule below), [ADR-0027](0027-observation-timestamp-semantics.md) (the
  other per-node value resolved in the same snapshot pass).
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-09-06):** the field the consequences hold back arrived:
> [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) publishes `reported`,
> `own` and `code` under their own names and adds `contribution` — what the parent
> counted, null where that was simply `code`, and otherwise naming the rule. Rule 5
> reaches the API with it.

## Context

[ADR-0004](0004-status-aggregation-semantics.md) says how a status is **derived**:
severity order, `UNDEFINED` ignored, `MAINTENANCE` cancels its subtree, never
downgrade. What it does not describe is that the snapshot already **transforms** a
node's status on the way up, and that the code has carried the vocabulary for it
since [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md):

```python
own = worst_of((node.code, STALE_DEGRADE)) if stale_self else node.code
code = effective_code(own, (child.code for child in children))
```

`StatusSnapshot` holds **`own_code`** (what the node reported) beside **`code`**
(what it effectively is), the JSON envelope publishes both, and the dashboard dims
a card precisely when they differ. ADR-0005 states the principle in a consequence
bullet — *"staleness is a view concern: `StatusTree.snapshot` degrades and flags
it; `Status.get_status_code` / `effective` stay raw"* — but only for staleness.

The same idea is present a second time, in a different disguise. ADR-0004 §2 and
§3 — an `UNDEFINED` leaf is ignored when a parent accumulates, a `MAINTENANCE`
node is ignored by its parent — are **not** statements about what those nodes are.
They are statements about what those nodes *give their parent*, written from the
parent's side. So the concept exists twice already: as parent-side skip rules and
as a pre-roll-up degrade. It has no name, so nothing can cite it, and each new
feature that needs it re-derives it.

That is not hypothetical. Four separate designs — an admin pin that silences
warnings but not errors, a configured clamp so a lab machine cannot redden the
root, a dependency that shields the checks behind it, and a counter that holds a
failure back until it repeats — arrived independently at the same operation. Each
also asked, independently, whether it needed a new status code, and there was no
record to answer from.

## Decision

**1. A node has three statuses, and the third is now named.**

| | meaning | today |
| --- | --- | --- |
| **reported status** | what the node itself reported — a check's result, or an explicit branch status | `StatusSnapshot.reported_code` |
| **own status** | the first derived value — the worst of what its unsuppressed entries leave (decision 8) | `StatusSnapshot.own_code` |
| **effective status** | what the node *is*, given its own status and its subtree | `StatusSnapshot.code` |
| **contribution** | what its parent accumulates | implicit — equal to the effective status, except where ADR-0004 §2/§3 skip it |

The first three exist as fields. The last is promoted from an implicit parent-side
rule to the value a policy acts on.

**2. The contribution is where policy applies.** A node's contribution defaults to
its effective status. `UNDEFINED` and `MAINTENANCE` contribute nothing — ADR-0004
§2 and §3 restated from the node's side, with no change in behavior. Any future
rule that suppresses, caps, delays or promotes what a subtree reports upward is a
**contribution rule**, and it composes with the others at this one point:

> given a node — its own reported status, its children's contributions, the clock
> and the configuration — what does it **show**, and what does it **contribute**?

**3. One evaluation point, and it is the snapshot.** Transforms happen in
`StatusTree.snapshot`, where the clock and the configuration are available and
where staleness already happens. The tree's stored `Status.code` stays the raw
report and `Status.get_status_code()` stays the pure ADR-0004 derivation. **A
policy is never implemented by writing a different value into the tree**, because
a tree that has forgotten what a check said cannot apply a policy that depends on
it, cannot record an honest history, and cannot compose two policies.

**4. The status vocabulary is closed.** `OK`, `WARN`, `ERROR`, `MAINTENANCE`,
`UNDEFINED` — and no more. A new reason for a node not to count is expressed as a
contribution rule **plus a marker on the node**, never as a new code. Every
consumer switches on the code — the templates, the envelope's enum, the macOS
client — so a sixth code is a breaking contract change and a re-render of every
surface, in exchange for something the model already expresses: *do not count
this, and say why*.

**5. A transformed contribution is visible and attributable.** When a node
contributes something other than its effective status, the surfaces say so and
name the rule that did it. A tree whose roll-up cannot be checked by eye is a tree
that stops being trusted, and the transform is invisible precisely where it
matters most — on a quiet dashboard.

**6. Every suppression keeps a liveness backstop.** A rule that decides not to
report something must not also disable the freshness path
([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)). A check that
stops running altogether has to escalate regardless of which policy is holding its
result back — otherwise the suppression that was meant to quiet a known state
silently covers a dead check.

**7. An unusable rule does not apply.** When the input a policy depends on is
missing or unparseable, the policy is skipped and the status is reported normally.
Suppression is the failure direction that hides outages, and it is the one a naive
implementation reaches by default.

**8. The boundary reaches one level below a node.** A node's **reasons** are
addressable keyed entries ([ADR-0036](0036-addressable-reasons.md)), and an entry
may carry a suppression of its own. The entries are then **virtual children**: each
unsuppressed entry contributes the node's reported status, a suppressed one
contributes nothing, and the node's **own** status is the worst of what is left —
`MAINTENANCE` when a node that reported entries has none unsuppressed remaining. A
node that reported **no** entries is outside the rule, so a check with a code and no
reason is unaffected.

*Own status* is not simply *what the node itself reported*: the value the tree
stores is the **reported** status, and `own` is the first derived one — the same
move the maintenance keystone refactor makes for node pins, which is why the two
share one transform in `StatusTree.snapshot`. Decisions 2–7 apply at this level
**unchanged**: the evaluation point is still the snapshot (3), no new code is
introduced (4), a quiet entry is shown and counted (5), staleness still judges the
raw reading (6), and a suppression whose entry is not present simply does not apply
(7). Nothing about the boundary itself changes; only its reach is stated.

## Consequences

- **No behavior changes today.** Both fields already exist, staleness is already
  the one transform, and the contribution is currently identical to the effective
  status for every counted node. This ADR names what is built.
- **Rules 4–7 bind future work**, which is the point of writing it before the first
  policy rather than after the fourth.
- **`MAINTENANCE` as implemented no longer breaks rule 3.** `_apply_maintenance`
  records the entry and writes nothing; `_own_code` derives `MAINTENANCE` from the
  side table, the arm beside the one ADR-0036 added
  ([ADR-0014](0014-maintenance-persistence.md); `tree.py` `_apply_maintenance` /
  `upsert`). Three things fall out that were not obvious from here: clearing a pin
  restores the last known state because nothing was ever destroyed (it used to blank
  the node for a full check interval — a live bug); a silenced node can finally *say
  what it is silencing*, which rule 5 required and the old implementation made
  impossible; and `StatusSnapshot` grows the **`reported_code`** field this ADR's own
  table implies, because once `own_code` is derived the check's answer has nowhere
  else to live.
- **There was a second deviation, and it was propping this one up.** `_is_stale`
  exempted any pinned node, so a pinned check that died never escalated — rule 6
  exactly. It could not be removed on its own: the stale degrade takes
  `worst_of(reading, WARN)`, `worst_of` knows only OK/WARN/ERROR, and a node
  holding a written-in `MAINTENANCE` reached it and raised. Correcting rule 3 is
  what made rule 6 a two-word deletion. The guard that replaced it is on the
  **code**, which also closes the same latent crash for a check that reports
  `MAINTENANCE` itself.
- Still open, and named below: the split of ADR-0004, the maintenance-policy record
  this now implements, and the marked events for transitions that happen under a
  pin.
- **ADR-0004 was split when that landed.** Its derived-roll-up rules are
  [ADR-0039](0039-status-rollup-semantics.md) and its separate *failing check*
  decision [ADR-0040](0040-what-a-failing-check-becomes.md), with this one as the
  third piece; the skip rules are restated above and the `MAINTENANCE` half is what
  a policy replaced ([ADR-0041](0041-maintenance-is-a-contribution-rule.md)). One
  obligation came with it:
  its open edge case — a node whose children are **all** ignored — must be answered
  the way decision 8 answers it for virtual children (`MAINTENANCE`, not
  `UNDEFINED`), or real and virtual children would read differently in one model.
- **The envelope already carries `own_code` and `code`.** A contribution that
  differs from the effective status will need a field of its own and a
  `schema_version` decision; that rides the client-facing contract round rather
  than arriving piecemeal.
- `Status.get_status_code()` keeps its ADR-0004 unit tests unchanged, because the
  boundary deliberately sits outside it.

## Alternatives considered

- **Let each feature write its result into the tree** — what maintenance does
  today. Rejected: it destroys the reading the next policy needs, leaves the event
  log silent for the duration, and two such features cannot compose because
  whichever writes last wins.
- **A status code per reason** (`SUPPRESSED`, `SHIELDED`, `PENDING`). Rejected by
  rule 4: none of them is a severity, each breaks every consumer's exhaustive
  switch and the published enum, and the thing actually wanted is a marker beside
  an existing code.
- **Let consumers decide what to ignore.** Rejected: the rolled-up code is the
  contract every client reads, so a policy that leaves it untouched suppresses
  nothing — and N clients would each need the rules and would disagree.
- **Put the transform in `get_status_code()`.** Rejected: it has neither the clock
  nor the configuration, it is the pure derivation the tests pin, and a policy
  there would change what the tree itself believes rather than what it reports.
- **Wait for the first policy and write this then.** Rejected: the boundary is
  already built, already has one tenant and already has no name, which is why four
  designs re-derived it separately. Naming it is what stops the fifth.
