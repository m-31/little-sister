# ADR-0075 — A check declares what it costs, and startup adds it up

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-09-05)
- **Related:** [ADR-0072](0072-the-instance-reports-on-itself.md) (the lines the
  engine already carries about itself, and the limits they measure against — this
  record turns two of those limits into settings and gives them a second reader),
  [ADR-0049](0049-the-check-authoring-surface.md) (the check-authoring surface these
  two declarations join, additively),
  [ADR-0051](0051-what-startup-refuses.md) (what startup already refuses, and the
  argument these refusals reuse),
  [ADR-0031](0031-deployment-config-directory.md) (the two start-up failures told
  apart: an unusable configuration *tree* stops the process, a failure of *content*
  stops the engine and leaves the pages up),
  [ADR-0033](0033-budgeted-failure-retry.md) (the other place a check's period is
  spent faster than its `frequency` says, and the reason the sums are a lower bound
  rather than a schedule)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The engine measures itself as it runs: the entries the tree holds against a limit, the
resident size against a share of the machine, the pool's saturation, a tick that came
late, a run that outgrew its period
([ADR-0072](0072-the-instance-reports-on-itself.md)). Every one of those is a
measurement *after the fact*. A configuration that cannot possibly be served is
therefore discovered by being served badly: the pool saturates, checks queue, and the
dashboard is late for everybody rather than wrong for one check.

Some of that is knowable before the first tick. What a check costs is not a property of
the world it reads — it is a property of the check's own configuration, and only the
**type** can compute it. A type that reads fifty repositories at two requests each
knows it will hold a worker for minutes and write thousands of entries; the same type
configured with one repository knows it will not. The library cannot derive either
number: `timeout_seconds` is the bound a run may not exceed, not what it is expected to
take, and the two differ by an order of magnitude for every check that finishes
normally.

Three numbers such arithmetic would need are constants today —
the worker ceiling, the entry limit, and the share of the machine's memory the process
may occupy — which is the other half of the problem: a deployment that disagrees with a
refusal must be able to answer it, and one that cannot state its own limits can only
disagree by editing the library.

## Decision

1. **A check type may declare three numbers, from its own configuration.**
   `Check.expected_cost()` answers the worker time one run is expected to occupy, in
   seconds; `Check.expected_entries()` answers the reason entries it expects to hold
   over the nodes it owns; `Check.expected_record()` answers the bytes one of the
   type's records is expected to need. All three default to `None` — *this type will
   not estimate* — and all three are additive to the check-authoring surface, so the
   check API epoch does not move. They are **estimates and not bounds**, which is why
   the default is silence rather than the timeout: a type that declared its timeout
   here would refuse configurations that work.

2. **Startup sums what is declared, and refuses what cannot fit, naming the checks.**
   The worker sum is the utilization of a set of periodic tasks — each check's declared
   cost over its own period — measured against the pool the engine will actually run
   (which is the roster's size when that is smaller than the ceiling). The entry sum is
   measured against the entry limit. The record declaration is **compared per check**
   rather than summed: `record_limit`
   ([ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)) bounds
   **one** record rather than being a ceiling every check shares, so adding two types'
   declarations together would answer a question nobody asked and refuse deployments
   that work. Past any of the three, the engine refuses; the sentence names the
   largest contributors worst-first, five of them and a count for the rest, each with
   the numbers it declared — and for the record limit, the types whose every record
   would be refused at the seam on its first run.

3. **Only what is declared is summed, so the sums are a lower bound.** A silent check
   contributes nothing. This is exactly enough for a refusal — a configuration whose
   declared part alone does not fit cannot fit at all — and deliberately not enough for
   the opposite claim: nothing here says that a configuration which passes will be
   served comfortably. Counting a silent check as costing something would be a number
   the library invented, and it would refuse deployments that work today.

4. **A declaration the library cannot read is a warning and a silence.** A type's
   estimate is code the library does not own ([ADR-0049](0049-the-check-authoring-surface.md));
   a declaration that raises, or answers something that is not a non-negative number,
   is logged with the check's path and treated as undeclared. What is declared and does
   not fit is refused; what could not be read was never a declaration.

5. **Near a limit is a fact, past it is a refusal.** At or above the same 80 % the
   engine's own lines use, and inside the limit, a declared sum is a warning in the
   log at load and a **fact on the engine's own node** for the life of the process —
   a bullet in `/little-sister/engine`'s `report`, rewritten every tick beside the
   *may run late* facts it keeps company with. A declared record at or above the same
   share of `record_limit`, and inside it, stands there too. A limit already refused
   says nothing here: the refusal is the louder half of the same sentence.

   It is a fact and not an entry for the reason that kept it **uncoded** when it was
   one: a declaration is a claim about what will happen, the coded line for what did
   happen is the entry count itself, and a configuration that fits must not leave the
   node amber for the life of the process. On a coded set an uncoded entry carries the
   node's code ([ADR-0042](0042-entries-carry-their-own-code.md) decision 2), so once
   the instance's node became a branch the only place that reasoning survived was the
   `report` ([ADR-0076](0076-the-instance-node-is-a-branch.md) decision 1), and that
   is where these went.

6. **The refusal is a failure of content, not of the tree.** It raises `CheckError`
   before the engine registers anything on the status tree, so the web application
   stays up with its *engine not started* banner naming the reason
   ([ADR-0031](0031-deployment-config-directory.md)) and no half-built engine is left
   behind. The argument for refusing rather than warning is
   [ADR-0051](0051-what-startup-refuses.md)'s: checks that cannot be run on schedule
   still *report*, confidently, without measuring what the operator believes they
   measure, and a monitoring tool that is wrong is worse than one that is down.

7. **The three numbers become settings**, in `settings.yaml`: `max_workers` (the
   worker ceiling, a positive integer, default 8), `entry_limit` (positive, default
   100,000) and `memory_share` (a fraction in `(0, 1]`, default 0.5). The constants
   stay where the measurements that read them live and become the defaults; a bad value
   falls back to the default with a warning rather than refusing the start, like every
   other setting. Raising `max_workers` is how a deployment answers a refusal it
   disagrees with, and that is the point of the pairing: a refusal a deployment cannot
   answer is a refusal it will patch around.

8. **The declared figures stand beside the measured ones on `/system`** — the sums
   against the limits, and per check the declared cost and entry count beside the wall
   time of its last run, the declared record beside the largest one that run actually
   carried. An estimate decays as an estate grows, and an estimate nobody can compare
   against a measurement decays invisibly.

## Consequences

- **The library's own built-in types declare nothing**, and that is the honest state:
  an `http` or `file` check costs a fraction of a second and holds a handful of
  entries, and a sum built from such estimates would be noise. The mechanism is for
  the types that read an estate — where the number is large, computable from the
  configuration, and worth refusing on.
- **A deployment can be refused by a package it upgraded.** A plugin that starts
  declaring, or an estate that grew, can turn a working configuration into a refused
  one. The refusal names the checks and their numbers, and the answer — more workers,
  a longer period, fewer subjects — is in the operator's hands. A refusal that arrives
  at the release of a plugin rather than at 3 a.m. is the trade this record makes.
- **The worker sum is loose on purpose.** These checks are I/O-bound and overlap, so
  utilization against the worker count is an approximation, not a schedulability
  proof. It is used only to refuse the clearly impossible and to say *close* at 80 %;
  nothing here tries to predict latency.
- **A check with no period contributes no worker time**, because a cost divided by no
  period is not a rate. Its declared entries still count.
- **The engine now reads three settings it did not read before**, which makes
  `settings.yaml` load-bearing for whether the engine starts at all. A typo cannot
  cause that: every one of the three falls back with a warning.

## Alternatives considered

- **Derive the cost from `timeout_seconds`.** No new surface, and every check would
  contribute. It is also wrong in the direction that matters: the timeout is a bound
  chosen for the worst case, so the sum would refuse deployments that have been
  running for months. A bound is not an estimate, and pretending otherwise would have
  made the first refusal a false one — the fastest way to teach an operator to raise
  the ceiling until the arithmetic stops talking.
- **Let the deployment declare the cost in the check's YAML.** It is the deployment
  that owns the frequency, after all. But the cost is a fact about what the type does
  with its configuration, not a preference: an operator asked for it would guess, and a
  guess in a configuration file is indistinguishable from a measurement. The knob a
  deployment *does* get is the ceiling the sums are measured against, which is a
  statement about its own machine and one it can make truthfully.
- **Warn instead of refusing.** Consistent with how the neighboring seams treat a
  registration that fails, and rejected for
  [ADR-0051](0051-what-startup-refuses.md)'s reason: a warning in a log is not where an
  operator learns that half their checks cannot be run on the schedule they were given.
- **Measure the cost and remember it across restarts** instead of asking the type.
  A measurement is the better number, and it exists — the wall time of every run. What
  it cannot do is answer *before the first tick*, which is when a refusal has to
  happen; and a remembered measurement would refuse a configuration on the strength of
  what a different configuration did. The measurement's job here is to stand beside the
  estimate and show it drifting.
