# ADR-0033 — A faster second look: the budgeted failure retry

- **Status:** Accepted
- **Date:** 2026-10-10 (accepted 2026-08-01)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (the scheduler and
  bounded worker pool this leans on),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (freshness, which
  deliberately keeps judging by the nominal frequency),
  [ADR-0004](0004-status-aggregation-semantics.md) (what a failing run means),
  [ADR-0023](0023-secret-references.md) (the pinned checks this never touches),
  [ADR-0031](0031-deployment-config-directory.md) (where the settings live),
  [ADR-0125](0125-the-failure-retry-reads-what-a-run-rolls-up-to.md) (what a run is
  read for: what it rolls up to, not its root's own code).
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A single failed check is not proof, but confirmation used to cost a full
frequency interval: three reds at a five-minute check are fifteen minutes
before anyone believes the failure. The open interval-resolution question
carried this as *failure backoff* — and asked about jitter and the `frequency`
unit in the same breath; the believing-a-failure design round worked out the
shapes, and this piece ships first because it is small, engine-local, and
useful before damping exists.

The scheduler arms a check's next slot at **submit** time (`now + frequency`,
plus the one-time stagger); the result is only known at **completion**. Any
retry decision therefore happens when the run finishes.

## Decision

**1. A non-OK completion pulls the armed slot earlier — never later.** When a run
completes rolling up to something other than `OK` — its root's code and every child it
returned, by [ADR-0039](0039-status-rollup-semantics.md)'s rules, so that a branch check
whose root declares nothing retries when a node beneath it fails
([ADR-0125](0125-the-failure-retry-reads-what-a-run-rolls-up-to.md)) — and a retry is
configured, the next slot becomes `min(armed slot, now + retry_interval)`. The
submit-time arming is untouched — the nominal slot stays the safe default if a worker
dies mid-run — and a retry interval longer than the frequency changes nothing at all
(the fast look that would not be fast does not count against the budget).

**2. The retry is budgeted per failure episode.** At most `retry_attempts` fast attempts
follow a failure; then the check falls back to its nominal frequency until what the run
rolls up to **changes**, which ends the episode and re-arms the budget
([ADR-0060](0060-a-line-makes-no-claim.md)) — a root that turns from `OK` to `WARN`
above a run still rolling up to the same `ERROR` brings nothing new to confirm, and a
disk that goes from `WARN` to `ERROR` beneath a root that declares nothing does.
Re-arming on any change and not only on an `OK` is what ADR-0042 makes necessary: it
made a chronically non-`OK` node ordinary, and under an `OK`-only rule such a check
spends its retries once and never gets them back, invisibly. A three-day outage costs
exactly `retry_attempts` fast runs, then normal cadence — the budget bounds the burst by
construction. A completed run that rolls up to `UNDEFINED` does **not** arm the retry, a
withheld claim being nothing to confirm. Any other non-`OK` result triggers, `WARN`
included: that is the same set a later escalation counter (damping, a coming slice of
the same phase) will count, so the two features cannot disagree about what a failure is
— and that counter should skip a chosen `UNDEFINED` too. A **secret-pinned** check
([ADR-0023](0023-secret-references.md)) never retries — it is pinned until restart, and
a fast retry would burn the pool confirming a result that cannot change.

**3. Staleness keeps judging by the nominal frequency.** The engine upserts
`frequency_seconds` unchanged, so [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)'s
math never sees the retry: a fast-retrying check cannot go stale mid-episode
(it is observed more often, not less), and the exhausted-budget case is
exactly the nominal schedule. The `/system` page marks a retry slot
(`· retry 1/2` beside the next run) — a slot that silently contradicts the
frequency column would look like a bug.

**4. Configuration: two settings keys, two per-check fields, off by default.**
`config/settings.yaml` gains `retry_interval` (a duration string or bare
seconds; absent or `0` = no retry — today's behavior) and `retry_attempts`
(default 2); a check config may override either, and a per-check
`retry_interval: 0` switches that one check off. A bad settings value logs and
leaves the retry off (the config-module convention); a bad per-check value
fails the load loudly, like `frequency` would. The interval is measured **from
completion**, so a check that fails by timeout cycles at
`timeout + retry_interval` — the retry can never outrun the timeout.

**5. No added jitter, and the interval-resolution question is settled.**
Retry slots get no jitter of their own: completions are already spread by run
durations, the shipped per-check stagger keeps the nominal schedules apart,
the budget bounds any burst, and the bounded worker pool turns a residual
coincidence into brief queueing rather than load. That answers the question's
jitter half (the stagger is the mechanism, and it shipped); this decision is
its failure-backoff half — a speed-up, not a slow-down; and `frequency`
**stays seconds** (`parse_duration`). A cron-like calendar expression, if it
ever comes, belongs to the recurring-windows work, where calendars actually
live — check frequency does not grow a second time vocabulary.

## Consequences

- Confirmation latency drops from `attempts × frequency` to roughly
  `attempts × (run time + retry_interval)` wherever a deployment opts in;
  nothing changes anywhere else — the defaults reproduce today's schedule
  exactly.
- The episode counter is in-memory scheduler state: a restart mid-episode
  re-arms the budget, like every other schedule detail (ADR-0001). Recorded,
  not fought — durable scheduler state would be persistence-phase work.
- Damping, when it lands, ties its escalation count to this budget — the
  fast looks are what feed `escalate_after` — which is why the trigger set is
  the same on both sides.
- Events and history are untouched: a retry run is an ordinary run.
- `CheckInfo` grows the retry state for `/system`; the JSON API is untouched.

## Alternatives considered

- **Retry until recovery, with backoff.** Unbounded fast polling through every
  long outage — against rate-limited subjects too; the budget exists precisely
  to cap that, and damping will want a bounded confirmation count anyway.
- **Jittered retry slots.** Solves a herd the pool and the budget already
  bound, at the cost of a second scheduling vocabulary beside the stagger.
- **ERROR-only triggering.** Keeps a chronic WARN from ever fast-cycling, but
  splits the definition of "failure" from the escalation counter that will sit
  on top of this — and a WARN worth showing is worth confirming.
- **Do nothing.** The status quo: first-failure alarming with slow
  confirmation — the fifteen-minute case above.
