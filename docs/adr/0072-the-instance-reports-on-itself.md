# ADR-0072 — The instance reports on itself through one seam, in lines that clear

- **Status:** Accepted
- **Date:** 2026-09-05
- **Related:** [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the
  heartbeat and staleness, untouched), [ADR-0024](0024-dashboard-layout.md)
  (the strip that draws the heartbeat), [ADR-0031](0031-deployment-config-directory.md)
  (§7, the one line the beat used to carry), [ADR-0036](0036-addressable-reasons.md)
  / [ADR-0042](0042-entries-carry-their-own-code.md) (entries with slugs and codes,
  which the lines are), [ADR-0064](0064-the-resolver-is-a-registration.md) (the
  registration rules), [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)
  (the first contributor)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`/little-sister` is the engine's own node: it beats every scheduler tick, so a
stalled scheduler shows as staleness (ADR-0005), and the dashboard draws it as the
status strip (ADR-0024). Beyond liveness it could say exactly one thing, fixed at
construction — that no checks are configured (ADR-0031 §7). Everything else the
process knows about its own state went to the log: a maintenance file that could
not be written, a pool with every worker busy, a run that outgrew its period. A
deployment reading the dashboard from a phone learned none of it, and the state
layer (ADR-0071) was about to add two more facts of exactly this kind — a load that
failed, a save that failed — that must not be silent.

The risk is where this runs. The beat is written on the scheduler thread, and
anything that thread waits on is a tick the checks do not get. A self-report that
*measured* — opened a socket, listed a bucket, stat'ed a file — would make the
heartbeat wait on the thing it reports about, and a contributor that raised would
take the scheduler down with it.

## Decision

1. **One seam, contributors, lines.** Anything with something to say about the
   instance registers a **contributor**: a name and a callable that returns its
   current lines. Every tick the engine asks each one and writes what it answered
   onto the contributor's own child of `/little-sister` — `/little-sister/<name>`,
   the engine's own lines on `/little-sister/engine` — as **member entries**
   (ADR-0036) whose codes derive that child's own (ADR-0042), OK when nothing
   claims anything; the root's code is the roll-up (ADR-0076, which gives the
   branch its shape).

2. **A report is recorded state, read — never a probe.** A contributor returns what
   it already knows. Measuring belongs to whatever produced the state, on its own
   thread and its own budget; the seam only reads it.

3. **A contributor that raises is caught and named.** The beat still lands, and the
   report it could not read stands as one WARN line naming the contributor — a
   report that could not be read is not a report that said nothing. The same for a
   contributor that answers with something that is not lines.

4. **Every line carries a stable slug** — the contributor's own, on the
   contributor's own node, so `(path, slug)` is what a pin holds against and
   re-wording a line does not move the pin. A contributor's name is one slug
   segment, claimed once: re-registering from the same package replaces silently
   (a reloading server), a claim from another package refuses at startup naming
   both, `replace=True` says the replacement is the point and is recorded —
   ADR-0064's rules, for ADR-0064's reason: the name is the path a pin is written
   against, and import order must not decide what a pin silences. The flat view
   `current_lines()` still prefixes each slug with the name, for a reader that
   wants the whole report in one sequence.

5. **A report clears.** A line is a condition that holds now; a contributor that
   stops returning it has said so, and the node follows its lines. Nothing is
   remembered on behalf of a contributor, and both movements are transitions the
   event log records. A condition that should stand until a restart — a load that
   failed — is the contributor's to keep returning.

6. **The engine's own lines** live on `/little-sister/engine`, and the no-checks
   warning is the first of them: the sentence at WARN, the searched paths beside it
   as a line with no claim of its own (ADR-0042). `/system` prints each package's
   contributors beside its other seams, and the tree shows each as a child of the
   heartbeat whether or not it has something to say (ADR-0076).

7. **Two records, so the log and the node cannot drift apart.** A warning about
   the state of this process takes one of two shapes, and the seam offers a record
   for each that writes the line and the log entry in **one call** — so a call site
   that has the one has the other, and nobody has to read a log to learn there is
   something to read. `Standing` is for what the process learned at startup and
   cannot undo — a setting it could not honor, a credential reference that did not
   resolve, a door nobody can enter — one line per slug, for the life of the
   process; the library keeps one as `self_report.startup`, registered under the
   name `startup`. `Held` is for what recurs — a renderer that raised, a probe that
   timed out, a login that failed — each occurrence kept for a window after it was
   seen, so the line stands while the condition does and clears when it stops, with
   a count rather than a repetition and, where the occurrence has a size, the worst
   inside the window as the one reported. The engine's late-tick line is the first
   on that shape. Both are plumbing (F28): a package with the same two shapes uses
   them rather than writing its own. **Both write claims**: a note or an occurrence
   carries a code, WARN unless said otherwise. A fact — what the process knows and
   does not grade — is not a line on either record but the contributor's *report*
   ([ADR-0076](0076-the-instance-node-is-a-branch.md) decision 1), answered beside
   its lines and shown on its child's page.

## Consequences

- The heartbeat's reasons become entries with declared slugs on the contributor's
  child; the surfaces render them as they render any member entry, pin rail
  included. Each child's status moves — WARN or ERROR while a line stands, OK again
  when it clears — the root rolls them up, and those transitions are in the event
  log, which is the point: the dashboard says what the log used to.
- A deployment or a package can say something about the instance without a check
  and without a template: register a contributor in the same import-before-app
  block as its resolvers.
- The first contributor is the state layer's two lines (ADR-0071). The engine's own
  followed, on the same seam and under these rules, each under its slug on
  `/little-sister/engine` ([ADR-0076](0076-the-instance-node-is-a-branch.md)):
  `entries` (the tree's entry count against a limit of 100,000, WARN at 80 % of it
  and ERROR at it), `memory` (the resident size against half of what the machine
  gives the process — physical memory, or a cgroup's smaller limit — the same shape,
  and no line at all where the machine cannot say), `pool` (a check that has waited
  for a worker longer than 10 s, the first sweep excepted), `lag` (a tick more than
  5 s late, standing for ten minutes) and `late.<path>` (a run in flight, or a last
  run longer than the check's `frequency`, at WARN — a late run, not a broken one).
  A `timeout` above a `frequency` is a warning at load rather than a refusal, and
  what the engine knows about it afterwards is a paragraph of its report rather than
  a line: a configuration that only *may* run late claims nothing, and the shipped
  example that runs at 60 s with a 120 s timeout would otherwise stand amber for its
  whole life. Every number is recorded by the engine as it runs and read on the tick
  — the resident size is the process asking the kernel about itself, local and
  bounded, which is not the probe decision 2 forbids — and the numbers are constants
  in `limits.py` until the declared costs make them settings.
- What the process still says to the log alone — the startup degradations, the
  recurring failures, the security events — moves onto the two records one call
  site at a time, and the rule that goes with it (a warning about the state of
  this process is a line, or its call site says why not) is the roadmap's, not
  this record's.
- Pinning a line silences the instance's own warning, as pinning any entry does.
  That is an operator's call, and it is visible on `/maintenance` like every pin.

## Alternatives considered

- **Each fact its own node under `/little-sister`.** Rejected: a node per fact
  would put the engine's internals in the tree the dashboard lays out, and the
  strip exists to keep the self-monitor out of the grid (ADR-0024).
- **A probing report** — let a contributor measure when asked. Rejected for the
  thread it runs on; the one rule that keeps the tick a tick is that reading a
  report costs nothing.
- **Remember a line until somebody clears it.** Rejected: that is acknowledgment,
  a separate primitive with its own record to come; a report that had to be
  cleared by hand would be a report nobody trusts after the first stale one.
- **Prose reasons, as the no-checks warning was.** Rejected: prose has no slug, so
  nothing on it can be pinned, and a re-wording would move a pin that existed.
