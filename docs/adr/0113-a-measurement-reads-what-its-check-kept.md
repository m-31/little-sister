# ADR-0113 — A measurement reads what its check kept, and a grading does not

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (decision 7, by
  which a check never sees a store, and which this amends; decision 1, what a series is
  keyed by; decision 3, an identity and a state; decision 8, what stood where a reading
  landed; decision 10, the ceiling), [ADR-0086](0086-a-check-measures-and-grades.md)
  (decision 6, a grading is pure; decision 8, a window is not a run; decision 4, the
  object a check declares), [ADR-0032](0032-status-contribution-boundary.md) (what a
  node shows is derived, in the snapshot),
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (the wait before an
  escalation, which counts readings),
  [ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md) (decision 5, the context
  the engine opens around a check's two halves),
  [ADR-0040](0040-what-a-failing-check-becomes.md) (a check that raises),
  [ADR-0015](0015-check-discovery-union.md) (two checks on one mount),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (what a restart
  keeps), [ADR-0051](0051-what-startup-refuses.md) (decision 2, the epoch)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check hands back measurements and never sees a store
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 7). That is enough for
a check that reads what its source says now. A check that reads a **history** from its
source — the runs of a job, the executions of a pipeline, the buckets of a metric — has
a second question on every poll: how much of that history to ask for. With no way to
know where its own history ends, it asks for a fixed window again on every poll and
leaves the rest to the series, which replaces a record of the same identity in its place
(decision 3 there). Every type of the family that reads a history does that. It is
correct, and it asks for far more than is new: one type asks a metric store for fifteen
days of one-minute buckets on every poll, to use the newest.

Where a poll resumes can be known in three places. Nowhere, which is the fixed window.
In the process, which remembers where it read to: a mark that is lost at every restart,
and that can run ahead of what was kept, since a read that succeeded moves it whether or
not its readings were kept. Or in the kept history itself.

The third needed one thing said first, because it sounds like what the split of a check
forbids. [ADR-0086](0086-a-check-measures-and-grades.md) decision 6 does not say that
history stays out of a grading. The order a reading goes through shows what it says.
`measure()` fetches. `grade()` reads what it is handed — the records, the configuration,
the clock — so that a kept reading can be graded again with no process behind it, as a
page does already. And what a node shows is derived after that by the library, in the
snapshot ([ADR-0032](0032-status-contribution-boundary.md)), where history acts on a
status already: the wait before an escalation counts readings
([ADR-0083](0083-a-node-may-wait-before-it-escalates.md)), a pin has an expiry, a period
has a beginning. That step keeps its own history and never changes what was reported. So
a grading may be handed a history, which is what grading over a window of the series is
([ADR-0086](0086-a-check-measures-and-grades.md) decision 8), and it may not fetch one.

## Decision

### 1. The measuring half reads the window of one of its own subjects

`self.kept(subject)` answers what this check kept of that subject: the window of the one
series the check and the subject name
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 1). With no argument
it reads the object the check declares ([ADR-0086](0086-a-check-measures-and-grades.md)
decision 4). The engine that runs a check binds the read to the check's own type and
mount, so a check reads its own series and no other check's, and of two checks on one
mount ([ADR-0015](0015-check-discovery-union.md)) each reads its own.

It answers nothing where the check keeps no series, where nothing of the subject is kept
yet, and outside an engine. A type therefore always has an answer to act on, and asks
for its whole window where the answer is empty. Nothing is added that a check has to
implement, and a check that never calls it is what it was, so the check API's epoch does
not move ([ADR-0051](0051-what-startup-refuses.md) decision 2). This amends
[ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 7: a type still never
sets `series_keep` and still writes to no store, and its measuring half may read what
the store holds of its own subjects.

### 2. A check is handed the window as the store holds it

Every kept record, oldest first, as the series orders them: the record, its own time,
the moment it was observed, its identity or its state, and the code and the texts that
stood where it landed ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision
8). It is what a node's pages read, so the read shows a check nothing the instance does
not show. The records are copies: writing to one changes nothing that is kept.

### 3. The read is for deciding what to ask

A type uses what it kept to decide what to ask its source for, and for nothing else. **A
record stays a fact about the world**: what a type derived from its history is not
written into a new record. Such a record would depend on what this instance happens to
hold — on its `series_keep`, on a restart, on the ceiling
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 10) — and two
instances would keep different records of one world. A judgment over a history has its
own places: the grading over a window of the series
([ADR-0086](0086-a-check-measures-and-grades.md) decision 8), and the rules by which a
node shows a status ([ADR-0032](0032-status-contribution-boundary.md)). Nothing enforces
this decision; `implementing-checks.md` states it.

### 4. It answers only while its own check is measuring

Called anywhere else — from `grade()`, from another check, outside a run — the read
raises and names the rule. The engine marks the measuring half the way it marks both
halves lenient for a record the seam refuses
([ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md) decision 5): a context
variable, set around `measure()` and closed before `grade()` is called. A refusal inside
a grading is an exception like any other there, and the node shows it as an `ERROR`
([ADR-0040](0040-what-a-failing-check-becomes.md)). It holds for a check that keeps no
series as well: what is refused is the fetch, whatever it would have found.

The mark stands on the thread the engine called `measure()` on. A thread a check starts
itself begins with a context of its own and is refused, so a type reads what it kept
before it fans out.

The guard is in what the engine binds, and whoever runs a check binds its read
(`bind_kept`). A type's own test stands in the engine's place: it binds what the type is
to find and calls the measuring half itself, and that read answers wherever the type
asks. A check nothing bound is answered nothing.

## Consequences

- **A type that reads a history asks from where its history ends.** It takes the newest
  record's time, or the moment the newest was observed, from what it kept, asks its
  source from there less whatever the source may still deliver late, and the series
  merges what it reads again ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md)
  decision 3).
- **The mark is the history, so it cannot run ahead of what was kept.** A poll whose
  readings were not kept leaves the window where it was, and the next poll asks again.
  After a restart the check reads what the state file restored
  ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)) and resumes.
- **What a forgetful process repaired for nothing is no longer repaired.** A restart
  does not ask for everything again, so a point a source delivers later than a type
  looks back for stays missing, unless the type asks for its whole window from time to
  time. Whether it does is the type's rule and not the library's.
- **`series_keep` decides whether a type can resume at all.** Where a deployment keeps
  no series of a check, the answer is empty on every poll and the type reads as it did.
- **[ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 7 is amended.**
  [ADR-0086](0086-a-check-measures-and-grades.md) decisions 6 and 8 hold as written, and
  what they are for a history is said here: a grading is handed one, or it does not see
  it.
- **The wait before an escalation counts readings, not runs.** A rule over a subject's
  runs — worse only after two failed runs — is not built. It would be a rule of what a
  node shows that reads the series, or the grading over a window, and in neither case a
  fetch inside `grade()`.
- **`implementing-checks.md` says the rule**: read what you kept in `measure()`, before
  you fan out, to decide what to ask; a record stays a fact about the world.

## Alternatives considered

- **The process remembers where it read to** — no change to the library. The mark is
  lost at every restart, it moves when a read succeeded even where its readings were not
  kept, and it serves one type where the read serves every type that reads a history.
- **Every poll asks for the whole window** — what the types do today: correct, without
  state, and an answer that grows with how busy a subject is.
- **Only what resuming needs**, the newest record's time and observation — the smallest
  surface, and a second method with the next need, such as telling whether a record read
  again differs from the one that is kept.
- **The window without what stood** — the measuring half never reads a verdict, and a
  check is kept from what its own pages show.
- **A record that carries what a type derived from its history** — it can be graded
  again like any other, and its content depends on the instance that wrote it (decision
  3).
- **Convention in place of the guard** — a grading that reads the store works in the
  running instance, grades differently when an old reading is graded again, and nothing
  says so.
- **The window passed into `measure()` as an argument** — the grading has no handle on
  it at all; it changes that method for every type, which moves the epoch, and a type
  can still keep what it was handed.
- **`window`, `series` or `history` as the name** — the store's own word does not say
  whose window it is and also names the stretch of time a Series view shows; a series is
  what the pages draw; and history is the page of a node's status changes.
