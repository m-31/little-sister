# ADR-0043 — The coverage backstop: an empty scope is never silently green

- **Status:** Accepted
- **Date:** 2026-08-08 (in the design round on information a status code cannot carry)
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (rules 6 and 7, the
  invariants this one stands beside),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the zero-checks
  heartbeat `WARN` — the same answer one scale up),
  [ADR-0013](0013-check-config-on-node.md) (the config block shows the scope's
  *intent*; this decision is about its outcome),
  [ADR-0044](0044-run-facts-on-the-node.md) (`report`, where the discovered roster
  goes),
  [ADR-0042](0042-entries-carry-their-own-code.md) (why a branch container still
  declares its code, which is what makes the `WARN` expressible)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check that **discovers its own subjects** — repositories from an org and team
filter, issues from a query, link groups from a file — has a failure mode its status
cannot show. A *broken* discovery is caught: the lookup raises, and the run becomes
`ERROR — discovery failed`. An **empty or over-narrow** one is not: discovery returns
nothing, every aspect loops over nothing, everything reports `OK`, and the tree is
green. A name-prefix typo, a team that lost its repositories, a filter that excludes
everything — all read exactly like a clean bill of health. Green means "nothing to
report" and "nothing is being watched" identically, and only one of those is good
news.

The information already exists — discovery logs its count, and the configured filter
is on the node ([ADR-0013](0013-check-config-on-node.md)) — but no surface shows the
**outcome** of applying that intent. This project has answered the same failure twice
already, at other scales: a configuration tree holding no checks turns the heartbeat
`WARN`, "an OK heartbeat would roll up to an all-green root while nothing whatsoever
is being watched" ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)); and
the tags design requires a selector that matches nothing to warn, "a rule that
applies to nothing is not a no-op — it is a lie about coverage". Both times the
answer was *amber, saying so*.

## Decision

1. **The invariant, stated project-wide:** a check that discovers its own scope
   **reports that scope, and an empty scope is never silently green.** It stands
   beside the liveness backstop and fail-toward-alarming
   ([ADR-0032](0032-status-contribution-boundary.md) rules 6–7) as the third
   standing rule any discovery-shaped check satisfies.
2. **Zero scope is a `WARN` on the check's own node**, with a reason naming the
   filter that produced it — *no repositories in scope (org acme, team platform,
   prefix "quality-")*. `WARN` and not `ERROR`, following the heartbeat precedent:
   the check is working; what is wrong is the world or the configuration. A branch
   check declares its container's code, so this is expressible without touching the
   derived-entries rule ([ADR-0042](0042-entries-carry-their-own-code.md) applies to
   entry-bearing nodes; a branch result with children is not one).
3. **The scope itself is information and goes where information goes:** the *count*
   rides as an `OK` reason on the container — no new mechanism — and the *roster*
   belongs in the node's `report` ([ADR-0044](0044-run-facts-on-the-node.md)),
   where forty names cost nothing. The roster is presence; an entry is a claim — a
   subject only acquires an entry when something is wrong *about* it.
4. **The expectation is the check's business, and zero is its degenerate case.** A
   deployment that knows the team has thirty repositories sets the check's own
   `expect_min` (e.g. `expect_min_repos: 20`) and the check reports `WARN` below
   it. Core provides nothing and needs to know nothing. Build the two as **one
   comparison whose default is 1** — two messages, one code path — and **the
   setting floors at 1**: a configurable zero would let a deployment silence the
   backstop by configuration, which is the fail-toward-alarming rule's whole point.
5. **The subject children still render when the scope is empty.** Emitting no
   children would make the aspect nodes vanish and lose, one level down, exactly
   the property this record protects: a leaf you can see is empty is a leaf you can
   see is being watched. Quiet children under an amber container that says *no
   subjects in scope* is the honest picture; the container carries the alarm.
6. **"Overdue" follows the same ownership rule.** *The job did not run when it
   should have* is a judgment only the check can make (freshness measures the
   check's poll, never the subject's cadence —
   [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)), so core provides
   nothing for it; a check that wants it carries its own expectation, exactly like
   `expect_min`. Recorded here so the next job-shaped check does not re-ask.

## Consequences

- Nothing in core changes now: the reading and the expectation are check-side, and
  the invariant is the contract new discovery-shaped checks are reviewed against.
  In-repo, the links page's empty group is the candidate case if one is ever
  wanted.
- A too-narrow filter becomes visible the day it is deployed instead of the day
  something it silently excluded breaks.
- The severity-band shape shares the instinct on another axis: a band leaf emitted
  even when empty makes absence readable — presence is what makes emptiness
  legible.

## Alternatives considered

- **`ERROR` at zero scope** — rejected: nothing is broken; the check ran and can
  say so. The heartbeat precedent grades the same situation `WARN`.
- **A core-enforced minimum** — rejected: only the check knows what "too few"
  means, and a core knob would be either meaningless or wrong per check type.
- **Leaving it in the log** — the hole itself; the log is where the information
  already was while every dashboard stayed green.
- **A node per discovered subject** — rejected: forty repositories times seven
  aspects is a tree nobody reads. Per-subject *identity* already exists in the
  entry slugs; what was missing was per-subject **presence**, which the roster
  gives without paths, histories and pins per subject.
