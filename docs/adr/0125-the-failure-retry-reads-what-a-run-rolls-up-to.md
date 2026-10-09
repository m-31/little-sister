# ADR-0125 — The failure retry reads what a run rolls up to

- **Status:** Accepted
- **Date:** 2026-10-10
- **Related:** [ADR-0033](0033-budgeted-failure-retry.md) (decision 2, what arms the
  retry and what ends an episode, which this amends),
  [ADR-0060](0060-a-line-makes-no-claim.md) (decision 4, an episode ends on any change
  and a withheld claim arms nothing, which this amends),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up's rules),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (decision 8) and
  [ADR-0099](0099-a-status-that-still-holds-says-since-when.md) (decision 5), where the
  engine reads what a result rolls up to already,
  [ADR-0123](0123-a-node-says-one-status-wherever-it-is-read.md) (a branch shows what
  it rolls up to), [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (a node
  that waits before it escalates, whose readings this brings sooner),
  [ADR-0007](0007-check-result-branches.md) and
  [ADR-0015](0015-check-discovery-union.md) (why the result is read and not the node),
  [ADR-0078](0078-the-unit-is-what-the-engine-releases.md) and
  [ADR-0086](0086-a-check-measures-and-grades.md) (what one run is)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The retry that follows a failed run (ADR-0033, ADR-0060 decision 4) was armed by
`result.stored_code`, the code of the result's root: where that was neither `OK` nor
`UNDEFINED`, the completion pulled the armed slot to the retry interval, and an episode
ended when that code changed. A check that hands back a branch says its failures on
the nodes beneath its root. `host-metrics` and `aws` declare nothing on theirs, which
store `UNDEFINED`, and `github`'s own node says its coverage, `OK` while it could read
what it was asked to. So a failing disk, alarm or workflow never pulled the next run
in, and a node beneath that waits before it escalates (ADR-0083) waited for readings
that came at the check's frequency — while the run's log line said *UNDEFINED, rolls up
to ERROR*.

The engine reads what a result rolls up to where that matters elsewhere: `_rolled_up`,
ADR-0039's `effective_code` applied to what this run wrote, in `_placed`, where the
root declares nothing (ADR-0087 decision 8), and in the run's log line (ADR-0099
decision 5). Since ADR-0123 a branch shows what it rolls up to on every surface. The
retry was the one reader left on the root's own code. No deployment of the family turns
it on: the library's own `config/settings.yaml` says `retry_interval: 0`, and none of
the deployments sets one.

## Decision

### 1. The retry reads what the run rolls up to

What arms the retry is what the run rolls up to: its root's code and every child it
returned, by ADR-0039's rules — `_rolled_up(result)`, the reading the log line and
`_placed` take already. Where that is neither `OK` nor `UNDEFINED`, a completion pulls
the armed slot to the retry interval as ADR-0033 decision 1 has it, wherever the root
stands: a root that declares nothing above a failing child arms it, a root that
declares `OK` above one does, and a failure several levels down does. A branch whose
nodes are all well arms nothing, and neither does a run that rolls up to `UNDEFINED` —
ADR-0060 decision 4(b), a withheld claim, read of the whole run. The codes that arm are
the ones they were; what is read for them is the run, not its root.

### 2. An episode is what the run rolls up to

An episode ends, and the budget re-arms, when what the run rolls up to changes
(ADR-0060 decision 4(a)), not when the root's own code does. A root that turns from
`OK` to `WARN` above a run that goes on rolling up to the same `ERROR` brings nothing
new to confirm, and the budget stays spent; a disk that goes from `WARN` to `ERROR`
beneath a root that declares nothing is news, and arms it again.

### 3. The result is read, not the node

The roll-up is taken of what this run returned. The node would answer with what does
not belong to this reading: the children another check on the same mount wrote
(ADR-0015), and a child an earlier run wrote and this one did not, which the tree does
not prune (ADR-0007). A pin cannot reach the result either: the retry confirms what the
check reads, as it always did for a pinned leaf, whose `ERROR` armed it. A
secret-pinned check still never retries (ADR-0033 decision 2).

### 4. One check's switch stays its own

A branch check is now read whole again for one failing node, which is what one run is
(ADR-0078, ADR-0086), at most `retry_attempts` times an episode. `retry_interval: 0` on
one check stays the switch for an estate too expensive to read twice, which a
rate-limited provider may make it.

## Consequences

- **Nothing moves until a deployment turns the retry on.** Where one does, a branch
  check whose nodes fail is read again at the retry interval, and a node beneath it that
  waits before it escalates gets its readings at that interval instead of the check's
  frequency.
- **`/system` marks it**, `· retry 1/2` beside the next run of a branch check whose run
  rolls up to a failure: the mark reads the engine's own state (ADR-0033 decision 3).
  The demo turns the retry on, so its branch checks take fast looks while a node beneath
  them fails.
- **The log line and the retry agree.** A run logged as *UNDEFINED, rolls up to ERROR*
  pulls its slot in where the retry is on.
- **ADR-0033 decision 2 and ADR-0060 decision 4 carry an update.** The engine's change
  is the one code the retry block reads, which the log line computed already.

## Alternatives considered

- **The root's own code, as it was.** A branch check whose root declares nothing never
  retried, and one whose root says its coverage retried only when the coverage failed:
  the check's failures are beneath its root.
- **The node's roll-up in the tree, after the store.** It answers with children another
  check wrote and children this run did not return, and with what pins do to them; the
  retry would confirm what the tree shows rather than what the check read.
- **Reading again only the node that failed.** A check reads what it watches in one run,
  and the engine schedules checks, not nodes: there is no run of one child.
- **A switch of its own for branch checks.** `retry_interval` on a check already says
  whether it is worth reading twice; a second setting would ask the same question of the
  same check.
