# ADR-0079 — Freshness is judged against a stated tolerance, never a derived one

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-09-06)
- **Related:** [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the
  freshness rule this extends, and whose decision 1 points here),
  [ADR-0078](0078-the-unit-is-what-the-engine-releases.md) (the unit this measures,
  and the paced kind that made the question necessary),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the engine's own lines, and
  `late.<path>` — the same sentence asked of a periodic check),
  [ADR-0051](0051-what-startup-refuses.md) /
  [ADR-0075](0075-a-check-declares-what-it-costs.md) (what startup refuses, and the
  shape of a refusal that names the checks),
  [ADR-0044](0044-run-facts-on-the-node.md) (the `run` object this adds one field
  to), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope that
  publishes the verdict)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) decision 1 is the rule
that makes green mean *freshly verified*: a node not observed within `frequency +
max(frequency, 30s)` is stale, degraded to at least `WARN` by worse-of, computed at
render time. Every word of it measures against the check's **period**.

A paced check has no period. Its units are released at whatever rate the resource it
spends allows ([ADR-0078](0078-the-unit-is-what-the-engine-releases.md)), which is the
point of it — a check that does not know its own length cannot be given a `frequency`
without inventing one. So the freshness rule has nothing to measure against, and the
choice of what to put there is the whole of this decision.

The shape first proposed was an **expected cycle**, derived from the units' declared
costs over the pace the resource sustains, with a grace, capped by a ceiling the
deployment states. It is an attractive number: it adapts to the estate, it is exactly
what a capacity question wants, and the engine can compute it.

It is the wrong number to hang a status code on, for three reasons that only became
clear when the rule was written out as a sentence somebody has to be able to test.
**It moves under the reader.** Add forty repositories, or let GitHub tighten a budget,
and the tolerance grows with the estate — so a dashboard silently buys itself a longer
excuse exactly when it is doing worse, which is the reading ADR-0005 exists to refuse.
**It cannot be tested against a claim**, because it is an estimate refined by
measurement: there is no sentence with values in it to write a test from, only an
arithmetic that agrees with itself. And **nobody stated it**, so a deployment that
disagrees with a stale flag has nothing to argue with and nothing to change.

The same question is already asked of a periodic check whose run outgrew its period,
and it was already answered the other way:
[ADR-0072](0072-the-instance-reports-on-itself.md) puts `late.<path>` on the engine's
own branch at `WARN` rather than on the check's node. A run that takes longer than it
should is a fact about the *engine*, not about the subject.

## Decision

1. **Freshness is judged against a tolerance the deployment stated.** Where one was
   **stated** — a paced check's declared **cycle ceiling**, the longest a unit may go
   unobserved before its reading is stale whatever the pace, or the tolerance the
   engine states on its own branch
   ([ADR-0081](0081-an-instance-node-states-a-tolerance-not-a-period.md)) — that is
   the tolerance, and it wins over the one a period would imply. Where nothing was
   stated and there is a `frequency`, the tolerance is `frequency +
   max(frequency, 30s)` — ADR-0005 decision 1, unchanged and still the rule for every
   check that exists. Everything else about ADR-0005 decision 1 stands: worse-of
   degradation to at least `WARN`, computed at render time, maintenance and
   never-reported nodes exempt, no event recorded. The rule has one home,
   `tree.node_stale_after`, read by the stale verdict and by the number the envelope
   publishes (decision 5) alike, so the two cannot disagree.

2. **The ceiling is a common configuration field, `stale_after:`, and it is required
   of a paced check.** A paced check that declares no ceiling is refused at startup,
   in the shape [ADR-0075](0075-a-check-declares-what-it-costs.md) decision 2
   established — the engine refuses and the sentence names the checks — because a
   check the dashboard cannot ever call stale is a green tile with no promise behind
   it, and that is worse than a refusal somebody fixes in one line. It is **not**
   spelled `max_age:`, which is the same idea and already taken: the built-in `file`
   check grades a file by its own `max_age`, and one key meaning both the subject's
   age and the reading's age on one check is the kind of collision a stored key
   cannot recover from.

3. **The derived expected cycle is never a status input.** It stays worth computing
   and is reported where the engine reports on itself — a line on `/little-sister`
   beside `late.<path>` ([ADR-0072](0072-the-instance-reports-on-itself.md)), amber as
   a cycle stretches past what the budget should sustain. This is the whole of what
   the rejected shape offered, kept, and moved to the node that answers for the
   engine rather than the node that answers for somebody's repository.

4. **Freshness is per unit**, with [ADR-0078](0078-the-unit-is-what-the-engine-releases.md)
   decision 3: a unit's own last write is what its subtree's tolerance is measured
   against, and the roll-up carries the worst of them upward as it does today. A
   one-unit check is unchanged.

5. **The envelope publishes the verdict and the tolerance, and never the rule.**
   `stale` stays what it is — a boolean the server computed, which a client shows and
   never recomputes — and `run` gains `stale_after_seconds`, the tolerance actually
   applied, whichever branch of decision 1 produced it. A paced unit's `run` carries
   no `frequency_seconds` and no `next_at`: there is no period and no armed slot, and
   the fields are absent rather than null, per
   [ADR-0044](0044-run-facts-on-the-node.md)'s reading of an absent fact. That is one
   field for the contract round to carry, and it is why the round can freeze the
   envelope without waiting for the scheduler: the rule may change again inside this
   record without the contract moving at all.

## Consequences

- A deployment states one number per paced check and can be held to it. A ceiling set
  too generously is a slow alarm, and it is an auditable choice somebody made rather
  than an arithmetic nobody can see.
- A pace that collapses — forty minutes to five hours — is **not** visible on the
  check's own tile until the ceiling bites. It is visible on `/little-sister` from the
  first cycle, which is where the engine's own health lives, and that split is the
  decision: the subject's node says whether we know its state, the engine's node says
  whether we are keeping up.
- ADR-0005 decision 1 is amended rather than superseded: its rule is intact and its
  scope is now *where there is a frequency*. That record points here.
- One number in the envelope means a client renders freshness identically for both
  kinds, and a paced check needs no client change beyond tolerating two absent fields.

## Alternatives considered

- **The derived expected cycle with a grace, capped by the ceiling**, which is the
  shape first proposed. Rejected for the three reasons in the context: the tolerance grows
  with the estate, it cannot be tested against a claim, and nobody stated it. Keeping
  the ceiling *as well* would have made the derived number load-bearing only in the
  cases where it is most wrong — a collapsed pace excusing a late reading right up to
  the ceiling.
- **No staleness at all for a paced check**, on the grounds that the pace is the
  point. This is the green tile with no promise behind it, and it is exactly what
  ADR-0005 was written against.
- **A deployment-wide default ceiling** instead of a per-check one, so nothing is
  refused at startup. It hides the decision in a settings file at the moment somebody
  is adding a check, and the number depends entirely on which resource the check
  spends. A default may still be added later; refusing first is the reversible order.
- **A second status code for *not looked at recently enough***. Refused with every
  sixth code: the vocabulary is closed ([ADR-0032](0032-status-contribution-boundary.md)),
  and *stale* is a transformation of a code, not a code.
