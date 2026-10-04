# ADR-0081 — An instance's own node states a freshness tolerance, never a period

- **Status:** Accepted
- **Date:** 2026-09-19
- **Related:** [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the
  freshness rule, and the stale heartbeat that makes a dead scheduler visible —
  the constraint any answer here had to meet),
  [ADR-0079](0079-freshness-is-a-stated-tolerance.md) (the record this applies: a
  tolerance is stated, and `stale_after_seconds` is already the field it is
  published in), [ADR-0072](0072-the-instance-reports-on-itself.md) (a report is
  recorded state, **read** — the sentence the label contradicted),
  [ADR-0076](0076-the-instance-node-is-a-branch.md) (the children that inherited
  the stamp), [ADR-0044](0044-run-facts-on-the-node.md) (the run facts, and why
  they are not the answer), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (the envelope, which does not move for this)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`/little-sister` and every child of it rendered **"Checked every 1s"**, beside real
checks whose identical line means a subject was read on that period. Nothing on that
branch is checked at all: the lines are recorded state read on the tick
([ADR-0072](0072-the-instance-reports-on-itself.md) decision 2), and readiness
measured its trust store exactly once, at startup. The engine stamped
`frequency_seconds = max(1, round(poll_interval))` — the scheduler tick — where a
check gets its configured period, and two renderers said the same wrong sentence
about it.

The number was not free to remove, and that is the constraint every candidate answer
had to meet. `_is_stale` derived its tolerance from `frequency_seconds` and returned
`False` where there was none, so an unstamped node could never be stale — and a stale
heartbeat is how a dead scheduler becomes visible
([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) decision 3). At a 1s beat
the branch goes stale 31 seconds after the last tick. That detection window is the
thing not to lose.

What made the answer cheap is that the field's two jobs had **already** been
separated, by [ADR-0079](0079-freshness-is-a-stated-tolerance.md), when a paced check
forced the question from the other side. That record says freshness is judged against a tolerance somebody **stated**, publishes
it as `run.stale_after_seconds`, and establishes a node kind that carries the tolerance
and no period at all — a paced unit, whose `run` has neither `frequency_seconds` nor
`next_at`. So the envelope already distinguishes *how fresh this is meant to be* from
*what interval a check reads it on*, and the second is simply not a fact about a node
the engine re-asserts on its own tick. What was missing was on our side of it: the
tolerance had one source, arithmetic over a period, so a node without a period could
not have one.

## Decision

1. **A node may state its freshness tolerance, and a stated one is what freshness
   measures.** `Status` carries `stale_after`, `upsert` takes it, and one resolution —
   `tree.node_stale_after` — answers both callers: `_is_stale` decides with it and the
   snapshot publishes the number it used, so what the tolerance *is* and what a client
   is *told* it is cannot disagree. Stated wins over derived; where nobody stated one
   it is `frequency + max(frequency, 30s)` as before, which is every check that exists.
   This is [ADR-0079](0079-freshness-is-a-stated-tolerance.md) decision 1's second
   branch arriving in the tree; the cycle ceiling a paced check declares lands on the
   same field.

2. **The instance's own branch states the tick's tolerance and carries no period.**
   The engine writes `/little-sister`, `/little-sister/engine` and every contributor's
   child with `stale_after` and no `frequency_seconds`. The detection window is
   identical — the stated number is the one the arithmetic produced — and there is no
   longer a period for any surface to report as a check's. A node read on no check's
   schedule publishes no interval, which is the honest reading of a field whose whole
   meaning is *a subject was read on this*.

3. **A surface shows the period where there is one and the promise where there is
   not.** One rule, both kinds, and **no discriminator**: a node with
   `frequency_seconds` reads "Checked every 5m", a node without reads "Goes stale
   after 31s". Written once in prose and once in the clipboard document
   (`_node_facts.html`, `copy_status.py`), from `spans.format_tolerance`, which is
   `format_duration` over a rounded float — a derived tolerance arrives as one and
   would otherwise be spelled `31.0s`. A paced unit gets the same sentence for free,
   which is the second reason the rule is a rule rather than a case.

4. **The envelope does not move.** No new field, no new word, `schema_version` 2 and
   the spec's `info.version` unchanged: the two fields were already separate, and what
   changes is only which of them these nodes emit — `run` present with `observed_at`
   and `stale_after_seconds`, `frequency_seconds` absent, exactly the shape a paced
   unit will have. The macOS client decodes both as optional, has a contract test for
   the absent case, and renders `frequency_seconds` nowhere, so it needs no release.
   The spec's wording for that field is corrected to say what it now means.

5. **No word for *reported, not probed*, and no run facts on these nodes.** Both were
   weighed and both are refused below. What the branch does not say about itself in a
   label it says in its `description` and its `about`, which every surface already
   renders; what the tick costs belongs on `/little-sister/engine` as the engine's own
   lines, where the rest of the engine's self-measurement lives
   ([ADR-0072](0072-the-instance-reports-on-itself.md)), and is a separate slice.

## Consequences

- The instance's own nodes stop claiming a period they never had, and keep the
  freshness alarm that made the stamp worth having. Same 31 seconds, said in a
  sentence that is true.
- Freshness now has one resolution point rather than one formula, which is what the
  scheduler round needs for `stale_after:` on a paced check
  ([ADR-0079](0079-freshness-is-a-stated-tolerance.md) decision 2): that work brings
  the configuration field and the refusal at startup, and finds the tree side built.
- A deployment may state a tolerance on a node that also has a period, and the stated
  one wins. That is deliberate — a stated tolerance is somebody's claim and arithmetic
  is not — and it is not yet reachable from configuration; the field is written by the
  engine alone until `stale_after:` lands.
- `run` on such a node is present, carrying the two facts that are true of it: when it
  was last written, and how fresh it is promised to be. Its `wall_seconds` and
  `next_at` stay null, as they always were.
- Nothing about the dashboard grid, the status strip or the roll-up changes; this
  record moves no node and no code.
- Two records are amended rather than being quietly corrected:
  [ADR-0076](0076-the-instance-node-is-a-branch.md) decision 1, which said the root is
  written with the heartbeat's description and **frequency**, and
  [ADR-0079](0079-freshness-is-a-stated-tolerance.md) decision 1, whose second branch
  was a paced check's ceiling alone and is now a stated tolerance from whatever states
  one.

## Alternatives considered

- **Give the self-report nodes run facts**, so "checked every" becomes true. Rejected
  on the evidence rather than on taste. `RunFacts` is documented as the last-run facts
  of *the check that owns a node alone* ([ADR-0044](0044-run-facts-on-the-node.md)),
  and its presence encodes exactly that — present where the subtree holds one check,
  absent on a shared mount — so putting it where no check owns anything destroys an
  invariant a client relies on today. The values have no honest content either: one
  tick re-asserts every contributor in a single pass, so `wall_seconds` would charge
  that pass to each child separately, and `next_at` is the engine's **armed slot**,
  deliberately never `observed_at + frequency`, which a loop has none of.
- **A word in the envelope for *reported, not probed*** — `run.source`, or a node
  kind — which every surface switches its wording on. Rejected: it spends a contract
  field, and a new word has to be defined for every node that will ever exist rather
  than for the two kinds in front of us. It buys the ability to say something
  *positive* about these nodes, and the honest positive thing is the tick's own cost
  on `/little-sister/engine`, which is a different line in a different place and needs
  no word here. The option stays available; nothing in this record forecloses it.
- **Relabel or drop the line in the two renderers**, and leave the stamp alone.
  Cheapest, and it fixes the sentence rather than the cause: the tree would still hold
  a period for something with none, the next surface would still find it, and the
  scheduler round would still have to build the stated tolerance.
- **Drop the stamp entirely** and accept that the instance's branch cannot go stale.
  This is the green tile with no promise behind it that
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) was written against, on
  the one node whose staleness is the whole self-monitor.
- **Keep the period and add the tolerance beside it**, both rendered. Two numbers on
  every node to fix a sentence on a few, and the wrong one of them is still wrong.
