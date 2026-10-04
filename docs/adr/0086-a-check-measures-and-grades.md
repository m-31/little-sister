# ADR-0086 — A check measures, and then grades what it measured

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-09-27)
- **Related:** [ADR-0085](0085-a-measure-is-read-out-of-a-record.md) (the record
  this splits in two, and whose decision 2 moves here),
  [ADR-0040](0040-what-a-failing-check-becomes.md) (what a raising check becomes,
  which now also produces a reading),
  [ADR-0051](0051-what-startup-refuses.md) (the epoch a plugin refuses on),
  [ADR-0049](0049-the-check-authoring-surface.md) (the surface this changes),
  [ADR-0075](0075-a-check-declares-what-it-costs.md) (the declarations three
  types can now make exact), [ADR-0007](0007-check-result-branches.md) (the tree
  a grading still returns), [ADR-0058](0058-transport-policy-vocabulary.md) (the
  instrument-versus-subject question this makes structural),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (the series that narrows
  decision 8 again),
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (a subject's
  own node, where a line may name the subject its reading does not)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`implementing-checks.md` has said from its first version that a check is a **pure
function of the world → a result**. That sentence was always two functions wearing
one coat, and the code already had the shape and hid it: `host-metrics` reads one
script, parses it into numbers, and only then builds five children out of them.

What forces the split now is the series. A subject's records over time are graded
— *the last run succeeded, within 26 h, and the size did not shrink by half* — and
that grading runs over **old** records, when the process that produced them is
long gone. A `run()` that reads the world and decides a code in one body cannot be
asked that question at all: there is nothing to hand it but the world as it is
today.

The cost of noticing this late is the reason to take it as one change. Nine check
types in this repository are written against the old shape, and four sibling
packages are written against it too.

## Decision

### 1. Two halves, and the seam between them is a record

`run()` goes. A check type implements **`measure()`**, which reads the world and
hands back a `Measurement` — a record, and the object it was taken on — or a
sequence of them; and **`grade(measurements, now)`**, which answers one
`CheckResult`, the same tree a check has always returned.

The scheduler runs both, in that order, and writes what comes back.

**Records are plural in the signature and singular in practice.** A check that
reads several objects measures each one, and one record is the common case and
not the shape: a type that reads one object says so by handing back one value, so
nothing downstream branches on shape.

### 2. The grading maps records to nodes and lines, not the engine

A record whose object has a node becomes that node's reading; a record whose
object has none — a repository, a job run, a finding — becomes a **line**. A line
is an `Entry` beneath a node, and `CheckResult.children` cannot express one, so an
engine-side placement would need two return shapes to say one thing. The mapping
therefore stays inside the grading, written in the vocabulary every type already
uses.

The engine places exactly one thing: where a run handed back **one** measurement,
that measurement is the check's own node's reading. Where it handed back several,
the engine places none and the grading has already said where they go.

**The grading carries a reading through onto the `Entry` it produced**, as that
entry's `data`, and the line's `subject` is the measurement's wherever the measurement
names one; a `Measurement` does not declare a place. No type in this repository reads
more than one object, so the case that settled it is the first that does — the `actions`
aspect of little-sister-github's `github` type (little-sister-github ADR-0013). Its
mapping is one-to-one — one workflow on one branch is one measurement and one line — and
the grading is where the line's slug is minted anyway, so a declared place would have
been a second way of saying what the `Entry` already says, and an engine mechanism with
nothing to do.

The same case showed that decision 8 decides a subject's **grain**. The object of that
line had been the repository, and a repository with many workflow-branches would have
been one object many times over, so the object became the workflow on its branch and
the repository a field in the record that a projection groups by. One measurement per
repository was the other way out, and it was measured before it was refused: a
workflow-branch record weighs 291 bytes, so ten of them pass the 2 KB `record_limit`
before any other aspect is counted. The `github` type's pull requests, alerts and issues
are measured one measurement per line for the same reason; whether any of them is an
object with a history is a decision for later, against its own surface.

A line on a subject's own node may name that subject where its reading names none
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 2) — a
reading taken on every poll and kept nowhere, beside the subject's runs, which are
written for the record.

### 3. A measurement is the only place an object and its reading live

`CheckResult` loses `subject` and `record`. They were added one release ago
(ADR-0085 decision 2) for a `run()` that had nowhere else to put them; with a
measurement there is somewhere else, and keeping both would be two writers for one
field — which is what invites a check to write one and forget the other.

A **fallback** was considered and refused: the engine could have stamped the
measurement onto a result whose grading said nothing. It buys the same safety by
making the behavior implicit, which this project decides the other way round
elsewhere — `fetch` has no default redirect policy for exactly this reason. The
epoch makes the removal free.

### 4. A check declares its object at construction

Out of its **own** configuration: the `url`, the `host`, the file path. Not from
the node's path, which is the deployment's editorial label for where a node hangs,
and not per run, because a subject that moved between runs would silently split
one series in two.

A measurement may still name an object the check learned only from the **answer**,
and that one wins where it is given. A rate-limit check is the example, and it asks a
second question to learn it: GitHub's `GET /rate_limit` lists resources and never names
the account, so little-sister-github's `github-rate-limit` asks `GET /user` once per
process. Its object is finer than *whose*, too: each resource is its own budget, with
its own limit and reset, so each reading names one account's budget for one resource —
with the account alone, every resource's reading would land in one series as several
points at one instant (decision 8), and no budget would have a curve of its own. Where
GitHub will not name the account — an installation token, whose budget is the
installation's — there is no subject and no stand-in (little-sister-github ADR-0014
§6).

**A measurement may carry no subject**, and then it is the grading's input and nothing
more — no series, since nothing says which later reading continues it, and so nothing a
duplicate could confuse. The rule is [ADR-0085](0085-a-measure-is-read-out-of-a-record.md)
decision 2's: every measurement that is to have a history names its object. An empty
subject falls back to the check's own object only where the engine places a
measurement, which is the one a run handed back alone; among several it is no subject at
all. A subject-less reading is held no longer than its node, so it does not count
against the runtime ceiling on series.

The distinction this settles is the one the transport vocabulary already turns on
(ADR-0058): **the object is what is measured, the command is how**. An `http`
check's object is its URL and not `GET`; an `ssh-command`'s is the host and not
the command it ran there; and the local `command` check's is therefore the machine
little-sister itself runs on, which the library already names
([ADR-0074](0074-this-instance-has-a-name.md)).

### 5. The engine builds the failure record when the measurement raises

A check that raised has already reported something — that it could not get there —
and that is a reading. The engine writes it: `{"error": …}` against the object the
check declared, beside the `ERROR` it already assigns (ADR-0040). No author can
forget it, which is the weakness of doing it by hand: ADR-0085 decision 3 was
honoured by exactly one check, because somebody remembered.

**Only where the measurement raised.** A grading that threw over a reading that
succeeded has not made that reading untrue, and `{"error": …}` in its place would
discard the one thing that run did get right. A check pinned by an unresolvable
secret (ADR-0023) records nothing at all: it did not fail to reach its object, it
never went.

**The message is clipped in bytes, by the helper every type uses for its own
failures** — `failure_text`, at the budget `http`, `file` and `command` clip to
(decision 7) — after its whitespace is folded, since it is one value and not a
document. The node's reason line keeps the whole message; the record is what a
series would keep, and a clip in characters let a message of emoji weigh twelve
times its length and be refused by the seam, which would lose the one reading this
decision exists to keep. So the record has a known maximum, derived in code as
`FAILURE_RECORD_BYTES`.

**That maximum is a floor under every record size a type declares.** Any check can
raise, and the record the engine then writes for it is this one; a declaration
smaller than it would be a ceiling the engine itself could break. So where startup
compares a declaration against `record_limit`, and where `/system` shows it, a type
that declared less is taken at the floor, and the page shows the type's own number
beside it. Only a type that **declared** a size is raised: one that declared none
stays undeclared, because the library makes no claim a type did not make. The
type's `expected_record()` is untouched, and no type has to know the engine's
number.

### 6. Grading is pure over `(record, configuration, now)`

The grading reads the records it is handed, the fields its type parsed at
construction, and the clock it is **given**. Nothing else: not an attribute
`measure()` left behind, not the world again, not `datetime.now()` — a grading
that called the clock itself could not be replayed either.

Two consequences run through every type. **A record is not the check's working
state**: the raw answer — a 150-finding page, an unshortened log — stays inside
the check, and what crosses into the record is what is worth keeping, because
`record_limit` is 2 KB. And **what the line says has to be in the record**, since
the grading may read nothing else; for the three checks whose line *is* their
captured output, that is the whole of the design question in decision 7.

A value the check could not read stands as **`None`** in the record rather than
being left out (ADR-0085 decision 3): one shape per check, so a curve draws a real
gap from a null instead of inferring one from an absence. The exception is a
*reason*, which rides beside the values only where there was one — a null `error`
on every healthy reading would lengthen every record for nothing.

### 7. Free text entering a record is clipped once, and in bytes

`command`, `ssh-command` and `ssh-script` read no number; their line's whole text
is the captured output, so the output has to be in the record. That makes
`record_limit` the real ceiling on how much a deployment may keep, and `max_chars`
a request within it.

The bound is in **bytes**, and this is the part that is easy to get wrong. A
record is weighed as `json.dumps` writes it, which escapes to ASCII. Measured
against the 2 KB default, 1000 characters of output come to 1014 bytes in ASCII,
2014 when every one of them is a newline, 6014 in umlauts or CJK, and 12014 in
emoji, which JSON writes as surrogate pairs. A check clipping by characters alone
would declare a size it could exceed twelvefold and then be refused at the seam on
every run — the exact failure a declaration exists to prevent.

So the text is clipped **once**: to `max_chars` characters and then into whatever
byte budget is left, off the same end, and that one result is both the record and
the line. Clipping twice, to two lengths, would mean the sentence written today
could no longer be written from the reading stored beside it.

What it buys is exactness. `expected_record()` becomes a ceiling that cannot be
exceeded, so startup either passes a configuration or refuses it by name, and the
seam never refuses a reading at runtime. The visible cost is honest: with
non-ASCII output the line shows less than `max_chars` asked for, which beats a
check that goes red every run.

The same holds for every other piece of free text a record carries. A failed
reading's error — `http`'s request failure, `file`'s path and operating-system
message, a command that produced no exit code, and the engine's own failure record
(decision 5) — goes through one helper to one budget, 300 characters and 320 bytes,
so each of those types declares its failure record's worst case exactly.

### 8. One signature, one meaning — a window is not a run

`grade()`'s sequence is **always the readings of one run**: never one *record*
twice. The unit within a run is the subject **with its identity** (ADR-0087
decision 3), so one subject may recur where the identities differ — a poll that
read five runs of one environment is five readings of that subject, each naming
the run it is of. Two readings of one subject with the same identity are one record,
the second replacing the first, and so are two in the same state; two with neither
are two points at one instant (ADR-0087 decision 3). Grading over a *window of the
series* — the same type, asked what a subject's history means — is a different call,
and the series phase adds it rather than overloading this one.

The reason is not taste. With a single-object check, a window of length one and a
run of one object are the **same value**, so nothing in the argument could tell
them apart, and a grading written for one would be silently wrong for the other.
Two calls can each be written against a promise; one call carrying two promises
can only be guessed at.

### 9. This is a new epoch, and a v2 plugin refuses at import

The check API epoch moves to **3** (ADR-0051), and all nine types this library
registers convert in the same change — `command`, `file`, `http`, `ssh-command`,
`ssh-connect`, `ssh-script`, `host-metrics`, `macos-memory`, `qnap-metrics`.

Nine is not scope creep but the proof a single check cannot give, that the seam
fits every shape: one object with a node (`http`), one object rendered as five
nodes (`host-metrics`), two checks sharing a mount (`macos-memory`,
`qnap-metrics`), a reading that is only an exit code and a blob of text
(`command`), and a check whose whole measurement is whether it got there at all
(`ssh-connect`). And without `host-metrics` the deployment loses the readings
whose curves are the point.

The epoch is the unusual case of one that bumps on a **behavior** rather than a
name: no name left the surface, `Measurement` and `clip` joined it, and what
changed is the method every type implements. A v2 type cannot be adapted at
runtime — it would still decide a code from a world it re-reads inside the grading
— so it refuses at **import**, naming both numbers. That is the supported shape of
*the others follow later*: loud at startup, never quietly wrong. The four sibling
packages follow one by one, each with its own floor and release.

## Consequences

- **Every built-in type now carries a record**, where only `http` did. The metrics
  types parse their scripts into the record as **numbers** rather than into the
  grading as strings, which is what makes their curves drawable at all; an
  unparseable key stands as `None`.
- **Five types declare an exact `expected_record()`** — the command family, whose
  clip makes the declaration a ceiling, and `http` and `file`, whose one free-text
  field, a failed reading's error, is clipped by the same helper to the same byte
  budget, so their declaration is that record's worst case rather than a
  measurement of a good one. `host-metrics` declares one where its
  volume count is knowable and **nothing** where `disk_path: all` puts that in the
  estate's hands; `qnap-metrics` declares nothing, since a NAS decides how many
  bays it has. That is ADR-0075's lower-bound reading, applied honestly.
- **One place a record can still be refused at runtime**: an estate large enough
  that its own numbers exceed `record_limit` — a host with very many filesystems
  under `disk_path: all`. Clipping is not available there, because the answer is
  volumes and dropping some would be a lie; the runtime ceiling and the projection
  the series round designs are where that is answered.
- **A shared mount still publishes no measurement.** `host-metrics`,
  `macos-memory` and `qnap-metrics` each write a reading to the host node they
  share, and the snapshot withholds it, because no single writer can be believed
  there — the rule that already withholds that node's text and run facts.
- **The `http` record's error text is stored raw.** It was folded through `plain()`
  before, which double-escaped it: a record's values are escaped where they are
  rendered, so the escaping showed. The grading folds it into Markdown, which is
  the one place that has to happen.
- **A test that wants *the result of running this check* now runs both halves**,
  through one helper in `tests/running.py`. Deliberately not a method on `Check`:
  a convenience that ran the two together would be the thing every author reached
  for, and the seam would quietly stop being a seam.
- **The authoring guide documents the two halves as the one way a check is
  written** ([`../implementing-checks.md`](../implementing-checks.md) §2). Until
  the series arrives the grading only has to be *possible*, not used — which is
  precisely why it has to be built now, before a write path is built against a
  seam about to move.

## Alternatives considered

- **The engine calls `grade()` once per record and places each result.** Rejected
  in decision 2: it has no shape at all for a record that becomes a line, so it
  would need two return shapes to say one thing.
- **Keeping `subject` and `record` on `CheckResult` and letting the grading copy
  the measurement back.** Rejected in decision 3: ceremony an author can forget, in
  a change whose whole point is removing one of those.
- **Stamping the measurement onto a result that stated nothing.** Rejected in
  decision 3 for being implicit where this project is explicit; the analogy to the
  engine-built failure record does not hold, because that exists for a check that
  *cannot* act, not one that *might forget*.
- **The command string as the `command` check's object.** Rejected in decision 4:
  it confuses the instrument with the subject, makes that check a special case
  beside `ssh-command`, and would refuse a shell one-liner longer than the 200
  characters a subject may have.
- **Letting `command` declare no object at all.** Rejected with it: a raising check
  would then name nothing, and the machine is a perfectly good object that the
  library already names.
- **A second knob clipping the record shorter than the line.** Rejected in
  decision 7: the line would stop being rebuildable from the reading, for exactly
  the case the split exists for.
- **One `grade()` serving both a run and a window of the series.** Rejected in
  decision 8: for a single-object check the two arguments are indistinguishable.
- **Converting one type and letting the rest follow.** Rejected in decision 9: one
  check cannot show that a seam fits every shape, and a half-converted library
  would have to keep both methods alive across releases.
