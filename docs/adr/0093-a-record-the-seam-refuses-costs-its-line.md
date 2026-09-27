# ADR-0093 — A record the seam refuses costs its line, not the run

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)
  (decision 3, which this reverses, and the four refusals it keeps),
  [ADR-0086](0086-a-check-measures-and-grades.md) (the reading, the grading that may
  read only records, and the failure record the engine writes),
  [ADR-0040](0040-what-a-failing-check-becomes.md) (what a run in which no reading
  passed becomes), [ADR-0042](0042-entries-carry-their-own-code.md) (the coded line
  and the prose node the engine's own line leaves as they are),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the held line the instance says
  it with), [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (what a kept
  reading keeps beside its record), [ADR-0092](0092-a-check-declares-its-measures.md)
  (the marked break a failed reading draws),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (decision 1, the
  compatible change), [ADR-0075](0075-a-check-declares-what-it-costs.md) (decision 8,
  the record `/system` puts beside a declaration),
  [ADR-0051](0051-what-startup-refuses.md) (the epoch this does not move)
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — `Entry.refused`, from
  2.6.0.

## Context

A record is validated where it enters — a line's in `CheckResult`, a reading's in
`Measurement` — and four things are checked: it is a mapping, it serializes to JSON, it
weighs no more than `record_limit`, and a value under a timed name is a time
([ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md) decisions 2 to
4). Decision 3 of that record made a violation refuse the **whole result**, for two
reasons: a record dropped quietly would be believed missing, and a check author meets
the refusal loudly, on the first run.

Both reasons were argued with a check that reads one object in front of them, and the
cost shows from the other side once a check reads many. little-sister-github's `github`
type reads eight aspects over every repository in scope in one run, and one subject's
record takes every aspect's reading with it — on every poll, for as long as that subject
stays as it is. And the refusal is triggered by **data**, not by the check's code: a
disabled workflow's record carries its link, which the package cannot clip without
breaking it, and the link carries two names GitHub bounds only at 255 bytes, which in a
non-ASCII script take the record past the default 2,048. One bad instant from a
provider — a time without its offset — would do the same to any check that keeps one.

So what decision 3 guarded has to stay guarded — a refused record must never be believed
missing, and its author must still meet it — and the price it paid cannot stay the run.
What follows answers which refusals this covers, what becomes of a line whose record is
refused and of a reading whose record is, what the envelope says, how an author still
meets the refusal, and what `/system` counts beside a declared record.

## Decision

### 1. A refused record costs itself, never the run

The four refusals are alike here — a record that is not a mapping, one that does not
serialize, one heavier than `record_limit`, and one carrying something that is not a
time under a timed name — because each can come from data the check did not write: a
provider's answer that is a list, a float that is not a number, a name longer in bytes
than anybody expected, a time without its offset. The refusals themselves do not move:
the same four checks, the same limit, the same messages, and what is stored of a record
that passes is still the JSON read back.

What moves is the price. A refused record costs **the line or the reading it belongs
to**, which says so, and the rest of the run lands.

### 2. A line whose record is refused stands, and says that it lost it

The line keeps the text and the code the grading wrote. The grading wrote them over
readings that passed the seam — its claim about its subject was made on good material —
and what failed is the record the line carries for the surfaces after it. Replacing the
line, or setting it to `ERROR`, would say something false about the subject: that the
repository is broken, when it is the check's record that is.

The record is **gone, and says so**. `data` is null, and the entry carries
**`refused`**: why, in a sentence — the size against the limit, or the field whose time
had no offset. It stands **beside** the record and never as a key inside it, for the
reason a measurement's identity does
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md)): the record is the check's own
vocabulary, and a reserved name would take one from it. The node's own page says, where
the record would be listed, that it was refused and why.

And the instance says it, because a line that stands looks as healthy as it did and the
refusal is the author's to fix: a held `WARN` on `/little-sister/runtime`, naming the
check and the line, which stands while the refusal recurs and clears ten minutes after
it stops ([ADR-0072](0072-the-instance-reports-on-itself.md)).

This is the alternative ADR-0082 considered and refused — dropping the record and
keeping the line, *quieter and wrong: a reader would believe the check carried no
record, and nothing would say otherwise*. The objection is answered rather than
overruled: something now says otherwise, in three places.

### 3. A reading whose record is refused is kept out of the grading

A grading may read only the records it is handed
([ADR-0086](0086-a-check-measures-and-grades.md) decision 6), and a refused reading has
none it may read: handing over the refused mapping would let an unchecked value reach a
line, and handing over a stand-in would have the grading grade the engine's words. So
`grade()` receives the readings that passed, and the refused one is the engine's to
report — as ADR-0086 decision 5 has the engine report a measurement that raised,
which is what a refused reading was under the strict seam: `measure()` raised the
refusal.

**Its series keeps the failure record**, `{"error": "record refused: …"}`, clipped by
the helper every failure record goes through, so the reading is a marked break on its
subject's curve ([ADR-0092](0092-a-check-declares-its-measures.md) decision 5) — not a
hole, and not a gap the next reading papers over.

**The check's node carries one line per refused reading**, written by the engine, naming
the subject and why, at `WARN`. The node's verdict is incomplete — something it reads
was not read — and green over a subject nobody could read would be a false all-clear;
it is not `ERROR`, because the readings that passed were graded and their verdict
stands. The line takes the node's form rather than changing it
([ADR-0042](0042-entries-carry-their-own-code.md)): on a node whose lines carry their
own codes it is a coded `WARN` line under `refused-` and the subject, pinnable like any
other; on a node that declares its code it is an uncoded line, and the code is raised to
`WARN` where it was better, so a prose node stays prose. It stands after the grading's
own failing lines and ahead of the rest: a card shows a node's lines in order under a
line budget, and the reason for a node's color must not be what the budget folds away.
The instance says it as for a line. The kept reading keeps the code and the sentence of
that line beside its record, which is what stood
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md)).

**Where no reading passed there is nothing to grade**, and the run stands as a check
that raised ([ADR-0040](0040-what-a-failing-check-becomes.md)): `ERROR`, the refusal
its reason, and the failure record where the reading would have been — on the node,
where the run handed back one. Every check that reads a single object is in this case,
and sees the run it saw before, with a sentence that names the refusal where a check
error and its trace stood.

### 4. The envelope carries the refusal beside the record

Each line in the envelope gains **`refused`** beside `data`: the sentence the page
shows, or `null`. It is always present, as `subject` and `data` are — a client should
not have to discover an absent field. It is the compatible change
[ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1 describes:
`schema_version` stays 2, the spec's minor moves to **2.6.0**, the golden envelope
carries a refused line, and a client needs no release. A node's own reading needs no
field: a run whose one reading was refused stood as a check that raised, and its record
is the failure record, which says so.

### 5. The seam is strict by default, and lenient only inside the engine's runs

A refusal raises exactly as it did — a `CheckError` naming the field or the bytes —
wherever a record is built: a check's own tests, a fixture, a script, anything that
constructs a `CheckResult` or a `Measurement`. So a check author still meets it in the
tests, where the record is built, which is the half of decision 3 that was right.

Only inside a run the engine drives — around `measure()` and around `grade()`, and
nowhere else — does the seam mark a refused record instead of raising, and collect what
it marked. The engine says so through a context variable it sets for those two calls.
Only the engine can carry what a mark costs — the node's line, the instance's `WARN`,
`refused` in the envelope — so only the engine turns it on: there is no switch in
`settings.yaml`, nothing a test suite has to remember, and nothing a check can set.

The cost is stated rather than hidden. A new thread starts with a context of its own, so
a reading built on a thread a check starts itself is judged strictly, and its refusal
costs the run as before — unless the interpreter starts a thread from its starter's
context, which a free-threaded build does by default from Python 3.14. No check type in
the family builds a reading off its run's own thread, and `implementing-checks.md` says
so where it describes the seam.

### 6. The record `/system` puts beside a declaration counts the refused ones

[ADR-0075](0075-a-check-declares-what-it-costs.md) decision 8 puts the largest record a
run carried beside what its type declared, so that an estimate which stopped being true
is seen. A record refused for its weight is that estimate failing — and when a refusal
took the run, `/system` showed the engine's failure record in its place. So the figure
is the heaviest record the run **produced**, refused ones included, marked *refused*
where that heaviest one was refused for its weight. A record refused for a bad time
counts at its size, since its time was wrong and not its weight; one that does not
serialize has no size and does not count. Startup's comparison of a declaration against
`record_limit` does not change.

## Consequences

- **ADR-0082 decision 3 is reversed**, and that record now says so. What it decided
  about a record that passes — the JSON read back — stands, and so do its four
  refusals; ADR-0075's decision 8 says what its figure now counts.
- **The check API epoch does not move** ([ADR-0051](0051-what-startup-refuses.md)).
  Outside the engine's runs nothing behaves differently; `Entry.refused` and
  `Measurement.refused` are additive and the seam's to set; and no type in the family
  catches the refusal itself. One that did, around a `Measurement` it built, would see
  no exception inside a run, and would find the mark instead.
- **A single-object check sees the run it saw before**, `ERROR` with the failure record,
  except that its sentence names the refusal and carries no trace: a refusal is a
  verdict on data, not a fault in the check's code.
- **The instance's runtime node can carry many lines at once**, where one run refuses
  many records — one per check and line, or per check and subject, each counted over its
  window rather than repeated. That is the size of the problem, stated.
- **What this does not reach**: a subject, an identity or a state the seam refuses —
  over-long, or carrying a control character — still refuses the run. Each names a
  reading rather than carrying one, and a type bounds its own where its data could pass
  the bound, as the `github` type writes an over-long subject as a digest of itself; a
  case one could not bound is its own decision.
- **The contract's copies in little-sister-app follow in the same change**, since the
  release check compares them.

## Alternatives considered

- **Replacing a line whose record is refused** by one naming the refusal — the shape
  the question was first asked in. It loses what the grading said about the subject,
  which was said over readings that passed, and trades a line about the subject for one
  about the check.
- **The line, or the refused reading's own line, going `ERROR`.** A subject whose record
  the check could not keep has not failed; the code would be a claim about the wrong
  party. The node's `WARN` says its verdict is incomplete, which is the true claim.
- **A note on the node and no change of code.** The node would stay green over a
  subject nobody could read, a false all-clear.
- **Handing the grading the failure record in the refused reading's place.** The grading
  would grade the engine's words as if they were the subject's, and every type would
  have to know them.
- **A switch between strict and lenient** — in `settings.yaml`, the environment, or a
  test suite's configuration. A deployment's switch lets an author's mistake choose a
  deployment's outage; a test suite's has to be remembered by every plugin's suite, and
  one that forgot would meet the refusal in production and nowhere else.
- **Lenient everywhere, the refusal only logged.** The author would meet it on a
  dashboard rather than in the tests — giving up the one thing decision 3 got right.
