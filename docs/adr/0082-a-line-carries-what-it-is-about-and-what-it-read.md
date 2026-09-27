# ADR-0082 — A line carries what it is about and what it read

- **Status:** Accepted
- **Date:** 2026-09-27 (accepted 2026-09-19)
- **Related:** [ADR-0036](0036-addressable-reasons.md) (the entry, and the rule that
  it is not a node), [ADR-0042](0042-entries-carry-their-own-code.md) (the entry's
  own claim, and the value object this extends),
  [ADR-0050](0050-slugs-from-provider-identifiers.md) (the slug the subject cannot
  be recovered from), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (decision 1, which this is the first exercise of),
  [ADR-0002](0002-rlock-snapshot-synchronization.md) (why the stored record is a
  copy), [ADR-0018](0018-markdown-rendering.md) (escaping moves from the check's
  sentence to the renderer's field), [ADR-0006](0006-config-file-and-timezones.md)
  (why a record's time carries an offset and the node's need not),
  [ADR-0075](0075-a-check-declares-what-it-costs.md) (declare-and-measure, the shape
  a later limit negotiation would take),
  [ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md) (a refused record costs
  its line or its reading, never the run), [ADR-0085](0085-a-measure-is-read-out-of-a-record.md)
  (the node's measured record, shown beside the line's)
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — `Entry`, from 2.1.0.

## Context

A check gathers data about one thing, decides a status from it, and writes a
sentence. The sentence is what the model keeps; the data it came from is gone by
the time anything renders. The GitHub `actions` line is the worked example — it
knows the repository, the workflow, the branch, the run number, the verdict, both
run URLs and both times, and it publishes one string with all of it folded in.

Three things that ought to be separable are welded together by that. **Grading** is
extraction from what was read, and the family already has the two idioms for it — a
map from a state word to a code, a pair of thresholds over a number — but neither
can say which field it reads. **Rendering** is a choice about the data and not a
fact about the entity, so the deployment that wants the line worded differently
needs a plugin release. And **links** are baked into the text by the check, which
is both a class of escaping mistakes and the reason a surface cannot decide what is
clickable.

Two further things need something that does not exist. A view that **groups** —
everything about this repository — needs to know what a line is about, and it
cannot recover that from the slug: a declared slug is built subject-first, but the
parts are joined with `-` and `-` is legal inside a part, so `little-sister-pr-42`
cannot be split back apart by anything that did not build it. And a **series** — a
subject's readings over time, drawn as curves — has nothing to keep, because a
sentence is not a measurement.

[ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1 anticipated
this one by name: `subject`, `observed_at` and `data` "join it in the change that
adds them to the snapshot", and declined to publish them earlier, because a field
the schema promises and no run can fill is a promise no test can check. This is
that change, for two of the three.

## Decision

### 1. The record rides on the entry, beside the subject it is about

`Entry` gains two optional attributes. **`subject`** is the source's own identifier
for the entity the line stands for — a repository, a host — which several lines
commonly share; it is empty where the check did not say. **`data`** is the
**record**: a mapping of what the check read about that subject, absent by default.

`text` is untouched, and it stays what every surface shows and what events and
history carry. That is the whole reason this is additive rather than a redesign: a
check opts in, nothing on any card moves, and the check's own wording stays
reachable. Deriving `text` from the record everywhere at once was the alternative
and is rejected — every surface and the history read `text`, and a derived line
makes the sentence the check actually wrote unreachable.

Neither field declares **members**. A `code` or a `running` does, because each is a
per-line claim and a claim on an indivisible condition is meaningless
([ADR-0042](0042-entries-carry-their-own-code.md)); a subject and a record are data
*about* a claim, so prose that carries one stays prose and keeps the node pin as
its unit of suppression.

**The subject is not an address.** Nothing may be pinned by it, now or later. A pin
holds an identifier and only a line has one, and a subject pin would silence
everything about a repository — including the nineteen findings nobody has looked
at. A per-repository *node*, which is a different thing and a breaking one, is how
that wish is granted honestly, and it is not granted here.

This is the answer [ADR-0036](0036-addressable-reasons.md) asked for when it said a
third field must argue for itself harder than the second: a record needs no path,
no pin of its own beyond the entry's, no children, and no place in the roll-up. It
does not make an entry a node.

### 2. The typed vocabulary is three names, and all three are times

The surfaces can only do something special with a field whose meaning they know.
So a small set of key names carries a type, and everything else is free-form and
renders as a name and a value. The set is `at`, `started` and `ended`, each an
ISO-8601 string **carrying an offset**, or null — converted to UTC at this seam and
never re-stamped afterwards.

They are recognized at **any depth**. A record is a tree, and a time nested under
the run it belongs to is as much a time as one at the top; the first emitter's own
times are nested exactly so.

**An offset is required**, unlike the node's own stamp, which may be naive-local
because one process owns it ([ADR-0006](0006-config-file-and-timezones.md)). A
record's time comes from somebody else's clock and is read by a viewer in a third
zone, so a naive value is an instant only to whoever wrote it. A null is kept
rather than refused: *this run has not ended* is a fact, and refusing it would push
a check into omitting the key, which loses the difference between a time that is
absent and one that was never asked for.

**Nothing else is typed, and the omissions are deliberate.** The test a name has to
pass is that some surface does something with it that it could not do without the
type. A *link* fails it: `text` is Markdown and has carried links all along, and
letting the surface decide what is clickable is the point of the line *template*,
two slices away, which is where a link's shape should be settled with a template in
front of it. An *actor* and a *state word* fail it too — nothing renders either
differently today, and a state's reader is the grading seam. A **measurement** — a
number with a unit — is the interesting omission and is covered by decision 4.

The vocabulary is enforced here rather than merely documented. A documented type
nothing checks is the worst of both: every renderer still has to defend itself, so
the defense is written repeatedly, and the check author learns of the mistake from
a dashboard rather than from the construction that made it. Enforcing it later is
also the expensive order — once records exist, turning the check on converts
working checks into failing ones.

### 3. The seam refuses, and a refusal costs the line, not the run

The record is validated where the outside world enters, in `CheckResult`, and a
violation is a `CheckError` — which is to say a red node naming the check
([ADR-0040](0040-what-a-failing-check-becomes.md)), loud and on the first run.
Four things are checked: it is a mapping, it serializes to JSON, it is not too
heavy, and a timed name carries a time.

**A refused record costs the line or the reading it belongs to, never the run**
([ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md)). The first check to read
many subjects in one run showed why the whole result cannot fall: one subject's
record, heavy with names a provider bounds only at 255 bytes, took every aspect's
reading with it on every poll, and a refusal comes from data as readily as from a
check's code. What a whole-result refusal guarded stays guarded — a reader must never
believe a check carried no record when it did. So a line whose record is refused
stands and carries, beside the record, that it was refused and why; the node's page
and the instance say it too; and a check author still meets the refusal where the
record is built, because the seam raises everywhere but inside the engine's own runs.
Shaping a record to fit is the check's job, and the refusal says which field and how
many bytes.

**What is stored is the JSON read back**, not the mapping that was handed over. A
snapshot is read outside the lock ([ADR-0002](0002-rlock-snapshot-synchronization.md)),
so a check that kept a reference to its own mapping could otherwise change a value
while a page renders it. Reading it back also makes what is stored exactly what a
client receives — a tuple arrives as a list, a non-string key as a string — rather
than something that merely serializes to that.

### 4. How heavy is counted in JSON bytes, and a deployment may say

The limit is the byte length of the record's JSON, because that is the form a
record costs in: the envelope sent to every client, and a series file later. The
same serialization proves the JSON-serializable promise and measures it, so one
step does both jobs.

**The default is 2 KB.** The line is drawn where a composed record ends and a
payload dump begins, which is what the limit exists to stop: the first records
assembled by hand come to a few hundred bytes, while a single raw row from a
provider's API is already several kilobytes. A more generous number would let an
unexamined API row through, and then the limit no longer guards the thing it was
drawn for.

**`record_limit` in `settings.yaml` overrides it**, like the engine's other
numbers. The deployment owns the memory, the poll and the clients, so it is the
party entitled to decide; the check is the party the limit exists against, and a
limit its subject can raise is not one. Two consequences follow and both are meant.
A plugin is written against the **default**, never against a deployment's value —
a type whose records need more works where somebody raised the limit and fails
where nobody did, and the type cannot see which it is in. And the seam reads the
configuration **late**, at the first result rather than at import, because this
module is imported by every check type including a plugin's, and binding a
deployment's settings at plugin-import time would bind them at a moment that has
nothing to do with the deployment being ready.

That late read can **fail, and the failure is an answer rather than an error**.
Importing the configuration resolves a configuration directory and refuses when
there is none ([ADR-0031](0031-deployment-config-directory.md)), and a
`CheckResult` is built in plenty of places where there is none and should be — a
plugin's own test suite is the ordinary one, and a type that could not construct a
result without a deployment beside it would be a type nobody can unit-test. So a
missing configuration reads as *nobody has an opinion here* and the default stands.
A deployment cannot reach that branch: the application resolves its configuration at
import and refuses to come up without it, long before any check runs. This is
written down because the first build of this decision did not do it, and the cost
was every plugin's test suite at once.

There is deliberately **no total**. One record is bounded; the sum over a tree is
not, and at the entry limit the arithmetic reaches further than the memory line
does. That is left to the machinery that already exists: the engine measures its
own resident size and says so on its own node, which is that module's stated rule —
a limit it enforces is a line it can show, and a limit it cannot compute is one it
cannot observe either. A second, predicted bound would be a number nobody can watch.

### 5. What a record is not

It is not a second, quieter reason channel, and it is not a payload. It carries no
status: a node's code still comes from its own reading and its entries' claims, and
**a record never aggregates** — a parent's code rolls up from its children, and a
parent's record does not exist. It is not carried by the event log or the history,
which keep the texts, because a record in the transition deque would cost a great
deal to answer a question nobody asked of it. And it is not rendered on a card: the
node's own page shows it, as a plain list of dotted names and values, which is the
surface a reader reaches when the line is not enough.

That list reads decision 2's names. A value under `at`, `started` or `ended`, at any
depth, is shown in the configured `timezone` and `time_format`, as every other time is
([ADR-0006](0006-config-file-and-timezones.md)); everything else as it was stored — a
null, a time the zone cannot hold (the seam accepts any instant UTC can, and the last
half hour of the year 9999 in UTC is the year 10000 in Berlin), and a time-shaped value
under a name decision 2 does not type, since the type is the name's and never the
value's. One filter decides a field's kind, reading decision 2's set rather than a copy
of it, and both records the page shows go through it: a line's, and the one its node
measured ([ADR-0085](0085-a-measure-is-read-out-of-a-record.md)). **No age stands
beside a time.** The curves the series draws need none, a check that grades on an age
says so in its own sentence, as [ADR-0060](0060-a-line-makes-no-claim.md) decision 5
has a carried reading do, and an age written by a page that is not polled would be
wrong a minute later. The envelope carries a record's times in UTC, and a client
renders them as it chooses.

## Consequences

- **The envelope gains two fields and stays at `schema_version` 2.** The spec's
  minor moves to 2.1.0, which is exactly the compatible change
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1 describes.
  A client that reads neither is unaffected, and the macOS client needs no release
  to keep working.
- **Both fields are always present in the envelope**, as `""` and `null`, rather
  than omitted where unset. An absent field is something a client has to discover;
  *the check did not say* is an answer.
- **`observed_at` is not here.** It is the third field ADR-0080 named, it reverses
  [ADR-0036](0036-addressable-reasons.md)'s explicit *no ownership stamp*, and
  nothing in the library carries a line from an earlier run today — so it would
  ship null in every response of every release until something does. It belongs to
  the change that first carries a reading forward, which is where the reversal can
  be argued with a caller in hand.
- **A measurement is not here either**, and this is the omission most likely to be
  read as an oversight. A number with a unit has exactly one consumer — the series
  that will draw it — and that consumer is not built. Its shape is also not obvious:
  a series draws curves of a subject's *measures*, plural, and the single
  `number`/`unit` pair the original sketch proposed cannot hold two. Deciding it
  with the first curve in front of us is cheaper than deciding it now and living
  with the answer. Nothing is reserved against it, for the reason ADR-0080 gave
  about tags: a name is claimed when it exists.
- **A check that adopts the record can stop welding data into its sentence** — but
  none is obliged to, and a type's sentences are rewritten when that type adopts
  the record, never before.
- **The escaping moves.** A record field is data escaped at render
  ([ADR-0018](0018-markdown-rendering.md)) rather than text a check interpolated,
  which retires a class of mistakes that only ever showed up in somebody's
  repository name.

## Alternatives considered

- **A `Subject` value object carrying an identifier and a display name.** Both
  halves are genuinely needed — a rename changes the name and not the id — but the
  entry already has one open-ended structure, and a second one beside it is one too
  many. The display name is a field of the record. It is also the safer order:
  promoting a string to an object later would be a breaking change, while adding a
  name to the record is additive, so the cheaper option today is the one that never
  forces the change the object shape exists to avoid.
- **The subject as a pinnable key**, so an operator could silence a repository in
  one act. Refused above, and the honest version of the wish is a per-repository
  node, which costs every path and every pin under that check.
- **A per-check `record_limit:` in the check's YAML**, so a deployment could raise
  it for the one type that needs it. Mechanically awkward — a `CheckResult` does not
  know which check built it — and the declare-and-measure shape of
  [ADR-0075](0075-a-check-declares-what-it-costs.md) is the better answer if the
  runtime refusal ever proves too blunt: a type states what one record needs, and
  startup refuses against the deployment's number instead of the first run doing it
  fifteen minutes later.
- **Dropping the over-heavy record and keeping the line, silently.** Quieter and
  wrong: a reader would believe the check carried no record, and nothing would say
  otherwise. Decision 3 keeps the line too, and differs in exactly that — the line, the
  node's page and the instance say the record was refused and why.
- **The whole result falls**, not the offending line. Chosen at first, for the reason
  above, and reversed by [ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md)
  once one subject's record was seen taking a many-subject check down on every poll.
- **Counting the limit in fields, or in depth.** Neither is what a record costs.
  Depth is left unbounded on purpose: deeply nested and small is ugly to render and
  harmless, and a second limit needs a second justification.
