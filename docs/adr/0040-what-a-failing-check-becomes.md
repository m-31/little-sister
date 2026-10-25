# ADR-0040 — What a failing check becomes

- **Status:** Accepted
- **Date:** 2026-09-27 (accepted 2026-08-02; decided 2026-08-01)
- **Related:** [ADR-0039](0039-status-rollup-semantics.md) (the roll-up this feeds),
  [ADR-0018](0018-markdown-rendering.md) (why the message is escaped),
  [ADR-0056](0056-stable-useful-dashboard-flow.md) (`reason_cap`, which clamps the
  trace), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope
  carries it with no schema change),
  [ADR-0023](0023-secret-references.md) (the one check that fails without running),
  [ADR-0086](0086-a-check-measures-and-grades.md) (the two methods a check runs as)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`engine.py` has turned any failure into an `ERROR` since the day it was written; the
rule was recorded on 2026-08-01, and it is a record of its own because what a *failure*
means is not the same kind of decision as how a parent accumulates
([ADR-0039](0039-status-rollup-semantics.md)).

## Decision

A check is not trusted to fail gracefully, so the **engine** decides what a failure
means in status terms.

1. **Any** exception out of either half of a run — `measure()` or `grade()`
   ([ADR-0086](0086-a-check-measures-and-grades.md)) — a timeout, or a grading returning
   something other than a `CheckResult` becomes **`ERROR`** on the check's own node —
   never a skipped
   update, and never a stale `OK` left in place. "Unknown" is not an option:
   `UNDEFINED` means *not reported yet*
   ([ADR-0039](0039-status-rollup-semantics.md) rule 2), and a check that raised
   **has** reported — it reported that it cannot tell us, which is an operational
   problem.
2. The reason is `check error: <message>`, folded in with `plain()`. An exception
   message routinely carries external text — a captured line, a path, an API error
   body — so it is escaped like any other untrusted string
   ([ADR-0018](0018-markdown-rendering.md)); unescaped, a message could render as
   formatting or a link on the dashboard.
3. Unless settings set **`stacktrace: false`**, a **second reason** carries the
   innermost frames (`engine.TRACEBACK_FRAMES`, 5) as a `code()` block — verbatim and
   inert, chained causes included, so a `raise X from Y` shows both. **On by default**:
   this is an operator dashboard, and a deployment whose log is awkward to reach should
   not have to go find the log for the one thing that explains the failure. The full
   traceback goes to the log either way.
4. The switch is **global rather than per-check**, deliberately: the check that raises
   unexpectedly is precisely the one nobody thought to flag in advance, so a per-check
   opt-in would be off exactly when it was needed.
5. The trace is an extra **reason**, not a new field on `Status` — so `reason_cap`
   clamps it on the dashboard, the detail page shows it whole, and the JSON envelope
   carries it with no schema change.

Where the **measurement** is what raised, the engine also writes the reading —
`{"error": …}` against the object the check declared — so a check that could not get
there leaves a record saying so instead of a hole. A grading that raised over a reading
that succeeded keeps that reading.

A check whose **secret references** failed to resolve at construction is a different
case, and records nothing, because it never went: it is pinned to `ERROR` without ever
running and is never retried until restart ([ADR-0023](0023-secret-references.md)).

## Consequences

- A failing check is loud by construction, and the reason that explains it is on the
  node rather than only in a log.
- Because the failure is a normal `ERROR` reading, everything that acts on readings
  acts on it: the budgeted retry ([ADR-0033](0033-budgeted-failure-retry.md)) gives it
  a faster second look, and a maintenance pin silences it like any other
  ([ADR-0041](0041-maintenance-is-a-contribution-rule.md)) — while still recording the
  transition, marked.
- `check error:` is engine-assigned rather than check-authored, which is what lets a
  later pin policy treat it differently from a check's own `ERROR`.

## Alternatives considered

- **Skip the update on failure**, leaving the previous reading — rejected: the
  dashboard would show a green node whose check has been throwing for an hour.
- **A sixth status code for "cannot tell"** — rejected by
  [ADR-0032](0032-status-contribution-boundary.md) rule 4: the vocabulary is closed,
  and every consumer switches on it.
