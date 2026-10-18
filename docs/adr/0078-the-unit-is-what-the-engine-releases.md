# ADR-0078 — The unit is what the engine releases, and a check declares its own

- **Status:** Accepted
- **Date:** 2026-10-18 (accepted 2026-09-06)
- **Related:** [ADR-0049](0049-the-check-authoring-surface.md) (the surface this
  joins, and its add-is-compatible rule),
  [ADR-0051](0051-what-startup-refuses.md) (the epoch, its snapshot, and the shape
  of a startup refusal), [ADR-0075](0075-a-check-declares-what-it-costs.md) (the two
  declarations a type already makes about itself, and the arithmetic that reads
  them), [ADR-0044](0044-run-facts-on-the-node.md) (the run facts and the ownership
  rule this generalizes), [ADR-0027](0027-observation-timestamp-semantics.md)
  (stamped where written), [ADR-0040](0040-what-a-failing-check-becomes.md) (a
  failing check is all-or-nothing — the scope this narrows),
  [ADR-0043](0043-coverage-backstop.md) (the backstop, which attaches to whatever was
  short), [ADR-0008](0008-json-output-api.md) (the envelope this reaches),
  [ADR-0086](0086-a-check-measures-and-grades.md) (a run measures and grades — a unit
  is a unit of measuring), [ADR-0130](0130-a-unit-has-a-period-of-its-own.md) (a
  unit's own period and the node it answers for, the periodic half decision 6 leaves
  open)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The engine releases **checks**: one schedule per check, one run per period, one
worker held for the length of it. That is the right shape for a check that reads one
thing, and the wrong one for a check that reads forty. A type with more than one
subject to read has three bad options today — read them all in one run and hold a
worker for minutes, read a fixed slice and starve the rest, or be configured several
times over and lose the one node that answers for the whole scope. The GitHub type
has taken the second, and it starved the tail of its aspect roster until that
repository's own record was amended to rotate the order.

The engine cannot help, because it cannot see inside a run. It knows a check's
period, its timeout and — since [ADR-0075](0075-a-check-declares-what-it-costs.md) —
what the type says one run costs. It does not know that the run is forty independent
reads, which is exactly the fact that would let it order them by age, price them
against a budget, or stop after twenty without losing the twenty it had.

So the question is not whether the engine should schedule at a finer grain — it
plainly should — but whether that grain is **part of what a check type promises**, or
an engine-internal shape hidden behind a run. The difference is not academic: a
promise is pinned by the check API epoch and cannot be taken back
([ADR-0049](0049-the-check-authoring-surface.md) decision 5), and it is what a client
reading the envelope can be told about.

## Decision

1. **The unit is the check-authoring surface's primitive, and a check is the
   one-unit case.** A type declares what it reads — `units()` answering a unit for
   each thing (a repository, an account, a log group), its key, its own period and the
   node it answers for, and `measure_unit(key)` reading exactly that one and handing
   back its measurements, the measuring half of a run
   ([ADR-0086](0086-a-check-measures-and-grades.md)). The check is graded over the
   newest reading of every unit, and a unit's run writes the path it answers for and
   nothing beside it ([ADR-0130](0130-a-unit-has-a-period-of-its-own.md)). The engine
   releases units, never checks; a periodic check is a check with exactly one unit,
   released once per period, which is a check's behavior unchanged and is the
   degenerate case rather than a special case in the code.

2. **It is additive, so the check API epoch does not move.** The base class answers
   `units()` with a single anonymous unit at the check's own frequency, answering for
   its mount, and `measure_unit()` by calling `measure()`, so every check type keeps
   working without an edit and without a release. Adding a name to the surface is
   compatible by [ADR-0049](0049-the-check-authoring-surface.md) decision 5, and
   [ADR-0051](0051-what-startup-refuses.md) decision 4's snapshot is append-only
   within an epoch — the gate requires the current §11 block to still *contain* every
   promised line, not to equal it. This is the same argument
   [ADR-0075](0075-a-check-declares-what-it-costs.md) decision 1 made for
   `expected_cost()`, and it is the reason this decision costs the four packages
   nothing at all until one of them wants it.

3. **A unit answers for the nodes it writes, and the run facts follow it there.**
   [ADR-0044](0044-run-facts-on-the-node.md)'s ownership rule counts *checks* per
   path — one check owns this subtree ⇒ it carries that check's run facts, two or
   more ⇒ none. The rule is unchanged in shape and generalized in scope: **one unit
   answers for this subtree ⇒ it carries that unit's run facts.** A one-unit check is
   the same statement it makes today, which is why nothing moves for the checks that
   exist. What this buys is the fact a forty-repository check cannot state now — that
   *this* repository was read four minutes ago and *that* one an hour ago — where
   today one stamp on the mount speaks for all forty and is true of none of them.
   [ADR-0027](0027-observation-timestamp-semantics.md) is untouched: a unit stamps
   what it writes, and nothing is synthesized from below.

4. **Failure, retry and coverage are per unit.** A transient failure keeps that
   unit's last reading and requeues it with backoff
   ([ADR-0033](0033-budgeted-failure-retry.md) applied to a unit rather than a
   check); an answered refusal is that unit's reading; a `units()` or `measure_unit()`
   that raises is [ADR-0040](0040-what-a-failing-check-becomes.md)'s `ERROR` for that
   unit alone, so one repository GitHub answers with a 500 no longer empties a whole
   check. The coverage backstop
   ([ADR-0043](0043-coverage-backstop.md)) attaches to the unit that was short. This
   is the decision's real cost and its real payoff: all-or-nothing was a *simplifying*
   rule, and it is now all-or-nothing per unit.

5. **The envelope names the unit that answered, and nothing else about it.** The
   published snapshot carries `run` wherever a unit answered for the node — decision
   3's rule, said in the contract's words — and an optional `unit` key beside it
   naming which. That is the whole of what this decision owes the contract round, and
   it is why it is taken before that round freezes the envelope rather than after: a
   `run` block that may appear below a check's mount is a different contract from one
   that may not, and no additive field can fix that later.

6. **What is deliberately not decided here.** The scheduler's queue and its ordering,
   the pacer and its reserve, and the fields a *paced* declaration carries. Those are
   the scheduler round's, and they are decisions about the engine rather than about
   the surface; its periodic half — a unit's own period, the node it answers for and
   what a run of it costs — is [ADR-0130](0130-a-unit-has-a-period-of-its-own.md)'s.
   What this record fixes is only that the engine has a unit to release and a type
   may say what its units are.

## Consequences

- The four packages need not change, need not release, and need not raise a floor: a
  check type that says nothing about units is a one-unit check and always was.
- A type that *does* declare units publishes the keys, which makes a key a stored
  identifier like a slug or a `type:` name — renaming one moves node paths and breaks
  maintenance pins. The plugin rulebook's *a slug shape, a `type:` name and a
  configuration key are stored keys* covers it; a unit key joins that list.
- The engine gains the fact it needs to order work by age, which is what makes the
  fixed-roster starvation in `little-sister-github` an interim rather than a design.
- `expected_cost()` ([ADR-0075](0075-a-check-declares-what-it-costs.md)) is a
  per-check number today and becomes a per-unit one where units are declared; the sum
  startup adds up does not change shape, only its terms.
- Two things the envelope must carry from the day the contract round lands, whether
  or not any type declares units: `run` below a mount, and `unit`. A client written
  against a `run` that appears only at a mount would be wrong on the first paced
  check.

## Alternatives considered

- **Keep it engine-internal, behind a run.** The engine would slice a run by
  something it invents — a scope in the configuration, a count. It cannot: the only
  code that knows what a subject *is* is the type, so the engine would be ordering
  and pricing a thing it cannot name. It was the other half of the open question this
  record closes, and its real cost is that every plugin that wants pacing then builds
  its own, which the family's *plumbing solved once is not solved again* rule
  refuses.
- **A new check API epoch for it.** The obvious reading, and wrong twice: nothing is
  removed or renamed, and an epoch bump obliges every plugin to release
  ([ADR-0051](0051-what-startup-refuses.md)'s stated cost) for names none of them
  has to use.
- **A separate `MultiCheck` base class.** Two surfaces to document, two paths through
  the engine, and a type that grows a second subject has to change its base class.
  The one-unit default is the same thing with one surface.
