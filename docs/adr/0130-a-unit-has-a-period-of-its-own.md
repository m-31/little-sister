# ADR-0130 — A unit has a period of its own, and a run stamps only what it answered for

- **Status:** Accepted
- **Date:** 2026-10-17
- **Related:** [ADR-0078](0078-the-unit-is-what-the-engine-releases.md) (the unit as the
  surface's primitive, whose decision 6 left the scheduler round open — this record
  takes its periodic half), [ADR-0079](0079-freshness-is-a-stated-tolerance.md)
  (freshness per unit, against a stated tolerance),
  [ADR-0086](0086-a-check-measures-and-grades.md) (measuring and grading as two halves —
  a unit is a unit of measuring), [ADR-0027](0027-observation-timestamp-semantics.md)
  (a stamp is set where a node is written, never synthesized),
  [ADR-0044](0044-run-facts-on-the-node.md) (the run facts and the ownership rule),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the tolerance a period
  implies), [ADR-0033](0033-budgeted-failure-retry.md) and
  [ADR-0125](0125-the-failure-retry-reads-what-a-run-rolls-up-to.md) (the retry, per
  unit now), [ADR-0075](0075-a-check-declares-what-it-costs.md) (the startup sum, per
  unit now), [ADR-0094](0094-a-restart-is-no-transition.md) and
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (what a
  restart keeps, and what it does not show), [ADR-0113](0113-a-measurement-reads-what-its-check-kept.md)
  (what `kept()` is for), [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md)
  (what writes an event), [architecture.md](../architecture.md) §11 (the surface the
  names join)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The engine releases **checks**: one schedule per check, one `measure()` per period, the
whole tree graded and written from it, and every node it writes stamped with that run.
A check that reads several things of one provider — the `aws` type's aspects, the
`github` type's — therefore reads them all at one tempo, and the tempo is the one its
most demanding reading can afford. Alarms want a minute. A bucket's storage metrics
are published once a day and read the same number every minute in between; a month's
cost is a request that is billed, fourteen hundred times a day at the check's minute.

A deployment has one way to say *once a day* today, and it is the wrong shape: a second
check of the same type on a second mount, the daily aspects switched on and the rest
off. Two checks cannot share a mount without withholding `config`, `report` and the run
facts ([ADR-0044](0044-run-facts-on-the-node.md)), so the account — the level the `aws`
type put first precisely so that one maintenance pin silences a migration — splits in
two, the account list and its roles are maintained twice, the estate's credential
reading is kept twice, and the day the paths move back under the account, every pin
set against them in between breaks. The other way, a type that skips the read inside
its own run while its kept record is young and hands the old record back, is refused by
the records it would have to break: the node would carry a stamp for a look nobody took
([ADR-0027](0027-observation-timestamp-semantics.md)), `kept()` exists for deciding what
to ask and what a run hands back is what the source said in that run
([ADR-0113](0113-a-measurement-reads-what-its-check-kept.md)), and it is plumbing the
next type rebuilds.

[ADR-0078](0078-the-unit-is-what-the-engine-releases.md) already decided the shape the
answer takes: the unit is what the engine releases, a type declares its own, and a check
is the one-unit case. What it left to the scheduler round — its decision 6 — was
everything about releasing them: the queue, the pacer, the paced declaration, the cost
per unit. That round was planned as one stage, the periodic unit and the paced kind
together, and the paced kind is the large half: a check without a frequency, a token
bucket per secret reference, a queue per resource, progress as scheduler state. A
daily aspect needs none of it. It needs a unit with a period of its own, released on
its own slot, answering for its own node.

## Decision

1. **A type declares its units with a period each, and measures one at a time.**
   `units()` answers the check's units — each a **key**, a **period** in seconds, and
   the **node** it answers for, a path relative to the mount, or none; `measure_unit(key)`
   reads exactly one of them and hands back its measurements, as `measure()` does for the
   whole. The base class answers one anonymous unit with the check's `frequency`,
   answering for the mount and measured through `measure()`: the one-unit check,
   unchanged, the degenerate case and not a special one. Both names join the surface
   additively, within the epoch, as [ADR-0078](0078-the-unit-is-what-the-engine-releases.md)
   decision 2 said they would; its `run_unit` is `measure_unit` once
   [ADR-0086](0086-a-check-measures-and-grades.md) split a run, named for the half it is.
   A unit's key is a stored key, with a slug and a `type:` name.

2. **A unit's period is written `frequency:` in the block that configures the unit,
   and defaults to the check's.** The library owns the word, the duration syntax and the
   default; a type places the key in its own block — an aspect's — and reads it with the
   library's parser. A type may declare a default period for a unit whose source has a
   cadence of its own, and the deployment's key overrides it; so a unit's period is the
   block's key, else the type's declared default, else the check's `frequency:`. A block
   that replaces another whole — an account's own block of an aspect — carries its own
   key or falls back the same way, never to the block it replaced. A period written
   shorter than a cadence the type declares is a line in the log when the check loads,
   never a refusal: it spends requests and tells no lie, and the family refuses a
   configuration that would lie, not one that spends.

3. **The engine releases units, and grades the whole check after each.** One schedule
   entry per unit, armed on its period. A unit's run measures its unit, replaces the
   newest reading the engine holds for it, and then grades the whole check over the
   newest reading of every unit with this run's clock — so the tree is always whole, and
   the grading stays the one pure function of the records, the configuration and the
   clock that [ADR-0086](0086-a-check-measures-and-grades.md) decision 6 made it. A unit
   that measured nothing clears what the engine held of it, as a run does today.

4. **A stamp belongs to whoever took the look, so a unit's run writes its own path
   and nothing beside it.** Out of the whole graded tree, the run writes the mount, every
   container down to the node the unit answers for — each with its own lines as the
   grading says them, since every unit refreshes what the containers say — and that node
   with its subtree, and moves the observation stamp on exactly those nodes. A sibling
   subtree is not written: its content, its stamp and its damping count stay what its own
   unit's run left, and no event is written for it. The grading is still whole, so a
   sibling's lines are graded again with every run and written when its own unit next
   runs — an age on a daily line moves once a day, which is what *checked every 1d* says.
   The alternative, writing a sibling with its stamp held still, was the shape first
   taken and is refused for a reason the stamp alone does not show: a write is a
   **reading** of the node — it advances the wait before an escalation
   ([ADR-0108](0108-the-wait-before-an-escalation-counts-what-a-node-shows.md),
   [ADR-0119](0119-a-wait-that-ends-by-its-count-writes-a-row.md)) — and a neighbor's
   minute would then count as the daily node's readings, three of them in three minutes.
   The anonymous unit's path is the whole tree, which is the one-unit check as it writes
   today. What a container says of its children — that they are complete
   ([ADR-0109](0109-a-node-says-its-children-are-complete.md)) — is applied after
   the path beneath it is written, so a sibling the grading returned and the run did not
   write stays, and one the grading no longer returns goes.

5. **Run facts, tolerance, retry and cost are per unit.** The node a unit answers for
   says its unit's period, its last write and its armed slot — `frequency_seconds`,
   `observed_at`, `next_at` — and goes stale by [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)'s
   rule over its own period ([ADR-0079](0079-freshness-is-a-stated-tolerance.md)
   decision 4). A container between the mount and a unit's node, and the mount itself,
   says the newest write beneath it as its own — it was written then — the shortest
   period among the units beneath it, and the earliest armed slot, which for a check
   whose units all keep its `frequency` is what it says today. The failure retry
   ([ADR-0033](0033-budgeted-failure-retry.md), [ADR-0125](0125-the-failure-retry-reads-what-a-run-rolls-up-to.md))
   runs its episode per unit, `late.<path>` ([ADR-0072](0072-the-instance-reports-on-itself.md))
   names the unit that outgrew its period, [ADR-0075](0075-a-check-declares-what-it-costs.md)'s
   startup sum takes each unit's cost over its own period, and the floor a pin takes at a
   node is the period of the unit that answers there. The envelope needs no new field:
   `run` may stand beneath a mount, and `frequency_seconds` and `stale_after_seconds` are
   per node already. `/system` lists a check's units beneath it, each with its period and
   its last run.

6. **A unit runs at start, as a check does**, inside the stagger window, and then on
   its period. The schedule stays in memory and is not armed from the series: arming a
   daily unit from its newest kept record would save one read a restart and leave its
   node `UNDEFINED` until its slot — the kept table is for comparing a first write, not
   for display ([ADR-0094](0094-a-restart-is-no-transition.md),
   [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)) — unless the
   kept record were graded at start without measuring, which is the replay
   [ADR-0086](0086-a-check-measures-and-grades.md) was built for and the series' own
   later stage, not this record's.

## Consequences

- The four packages need not change and need not release: a check that declares no
  units is the one-unit check and always was. A type that declares units publishes
  their keys, and a key joins the stored keys a plugin may not rename
  ([ADR-0078](0078-the-unit-is-what-the-engine-releases.md)'s consequence).
- A reader meets a `run` block on a node beneath a mount, where today it stands on the
  mount alone; the contract's words allow it, and a client that decodes only what it
  shows is untouched.
- The `aws` type is the first adopter, its unit the pair of an account and an aspect,
  once an account may carry its own block of an aspect — the period is read off that
  resolved block. Two things it settles in its own record: how an account's units share
  the session a run opens once today, which `little-sister-aws` ADR-0011 decision 4 left
  to the day an aspect has a period of its own, and which of them refreshes the
  account's and the estate's readings.
- The paced kind, the pacer, the per-resource queue and progress as scheduler state
  stay the scheduler round's, smaller by this: a unit, its slot, its stamp and its
  facts exist when their turn comes. The `github` type's `actions` aspect stays that
  half's first case, and the fixed-roster starvation ADR-0078 named is retired there,
  not here.

## Alternatives considered

- **Two checks on two mounts** — the shape a deployment has today, and what it costs is
  in the context: the account split, the configuration twice, the pins broken twice.
- **The type skipping its read while the kept record is young** — refused in the
  context; three records and a family rule stand against it.
- **The loader seam** sketched before the unit was decided, `from_config_many`: one
  file, several checks. Two checks on one container withhold `config`, `report` and the run facts
  ([ADR-0044](0044-run-facts-on-the-node.md)), which for the `aws` type is the root and
  every account node — a real loss, where the unit under one mount loses nothing.
- **Stamping every node a run writes**, the path as it is. Simplest, and a daily node
  would carry a stamp that moves every minute; [ADR-0079](0079-freshness-is-a-stated-tolerance.md)'s
  per-unit staleness could never bite.
- **Writing every node and holding a sibling's stamp still** — the shape the round
  took first, so that an age on a sibling's line moves with the clock. Refused in
  decision 4: a write is a reading, and a neighbor's runs would count as the node's
  own toward an escalation.
- **Grading and writing the unit's subtree alone.** `grade()` returns a check's tree
  and would need a second contract, the root's roster and a node's completeness
  ([ADR-0109](0109-a-node-says-its-children-are-complete.md)) would be written by
  whichever unit ran last, and the `aws` grading needs the account's reading beside the
  aspect's in any case: more change for less.
- **Arming a unit from its newest kept record** — decision 6.
- **The `subnodes:` block as the key's home**, which the library parses for every type.
  It applies per name under every account and cannot carry a period one account sets
  for itself; and the aspect's own block already carries `enabled:`.
- **Waiting for the third stage whole.** The daily aspects would wait for the pacer,
  which they do not need.
