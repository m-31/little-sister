# ADR-0111 — A run's mark says how the run stood, and a grading may say it for the record alone

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md)
  (decision 5, a run is a mark: what it left to the commission that draws one, which
  this settles, and its wording, which this narrows; decisions 2 and 4, where a
  subject's series is shown), [ADR-0087](0087-a-check-keeps-its-subjects-readings.md)
  (decision 3, an identity and a state; decision 8, what stood where a reading landed,
  which this amends), [ADR-0086](0086-a-check-measures-and-grades.md) (decision 2: a
  grading carries a reading onto a line),
  [ADR-0042](0042-entries-carry-their-own-code.md) (a node's code is the worst of its
  lines'), [ADR-0060](0060-a-line-makes-no-claim.md) (decision 1: a line that makes no
  claim), [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) (decision 3, the way
  into a stretch; decision 5, the gauges' rule for a window that holds more than a plot
  has columns), [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) (decision 4,
  the lane), [ADR-0092](0092-a-check-declares-its-measures.md) (decision 5, where *an
  identity or a state* came from),
  [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 6: a series no
  node stands for), [ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md) (a
  record the seam refuses), [`../architecture.md`](../architecture.md) §6 (a status is
  never said by color alone), [ADR-0028](0028-design-tokens-and-themes.md) (the inks are tokens
  every theme has), [ADR-0036](0036-addressable-reasons.md) (a pin holds a slug),
  [ADR-0051](0051-what-startup-refuses.md) (decision 2, the epoch)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 5 draws a
run as a mark at its own time — a tick, or a stem to its value — and said what a run
that passed and one that failed look like. It left three things to the commission that
builds the marks: the mark of a run that stood `WARN` or without a verdict, a window
that holds more runs than a plot has columns, and what the summary beside the title
counts.

The mark it had put off is the common one. How a run stood is the code its reading kept,
and a reading keeps the code of the line that carried its record
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 8). Most runs have no
such line. In one checkout's kept readings 92 of 96 workflow runs carry no code, every
one of them a run that passed, since their type writes no line for a passing run unless
a deployment asks for one. A job name's line is written from every run of the name and
carries the record of none, so each of its runs is kept without a code, a failed one
included. And a load test's complete run has no line at all.

A code that was kept does not last either. A record with an identity is replaced,
wherever it stands in the kept window, by what a later poll reads of the same event
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 3), with what stands
then: a failed run that had a line loses its code at the first poll after a newer run
took the line.

And decision 5 drew *a series of events — records with an identity or a state*, a phrase
it took over from [ADR-0092](0092-a-check-declares-its-measures.md) decision 5. The
round that settled the marks was about runs, and a state is not an instant.

## Decision

### 1. A run without a verdict has a mark of its own, which claims nothing

A run whose reading kept no code — or the code of a line that makes no claim
([ADR-0060](0060-a-line-makes-no-claim.md) decision 1) — is drawn, and as what it is.
**Without a measure it is a tick half as tall as a passing run's, in the muted ink; with
a measure a stem to its value in the muted ink, with no head.** It is not marked in the
lane, and the summary counts such runs, with the mark as its key (decision 6). The mark
says that a run happened, when, and its value where there is a measure, and nothing
about how it stood.

### 2. A grading may say how a run stood for the record alone

A grading may write a line that no node shows: **a line for the record alone**. The
reading whose record the line carries keeps the line's code and its sentence, as it
keeps a shown line's. This amends
[ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 8, whose first case
becomes *a line, shown or written for the record*. No node carries such a line: it
reaches neither a node's code nor its line cap, the envelope or a pin.

A grading then says how each run stood on every poll that reads the run — the newest on
the line it shows, every other for the record — so the replacement of
[ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 3 writes the verdict
again where it erased it. The mark has what it draws, and the readings table the
sentence, which is empty for such a run today. Where a shown line and a line for the
record carry the same reading, the shown one is what stood, and the reading keeps that.

It is additive: a result that writes no such line is what it was, and the check API's
epoch does not move ([ADR-0051](0051-what-startup-refuses.md) decision 2).

### 3. A run that warned has a mark of its own

A run whose reading stood `WARN` — a job past the time its configuration allows, a run
its type's severity map grades as a warning — is drawn with **the status cue's triangle
as its head, filled in the warning color and outlined in the body ink, on a stem in the
body ink**: between a pass and a failure in height where there is no measure, at the
run's value where there is one. It is not marked in the lane, which stays the failures'
row, and the summary counts the runs that warned, with the triangle as its key. The
warning's yellow cannot be an ink on a card's surface, so the outline carries the
contrast; both are tokens every theme has
([ADR-0028](0028-design-tokens-and-themes.md)).

The marks are then four, each told by its shape and its place as well as by its ink
([`../architecture.md`](../architecture.md) §6):

- **A run that passed** — without a measure a short tick in the body ink; with one a
  stem to its value with a filled head.
- **A run that warned** — the triangle on a stem in the body ink.
- **A run that failed** — a hollow ring in the failure ink on a stem in that ink: the
  tallest tick, or a stem to the run's value and a mark in the lane
  ([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 5).
- **A run without a verdict** — the bare mark in the muted ink.

### 4. In a crowd every run stands where it ran, and a passing run's head gives way

Runs stand closer than their marks are wide long before a window holds more of them than
a plot has columns. Over thirty days a column is two hours wide and a head covers eight,
so a release day's runs share a few columns and a job that runs every two hours fills
every one.

**Every run is drawn at its own instant and its own value, and a passing run's head is
drawn only where it does not run into another head** — one whose middle is nearer than a
head is wide. A run that warned or failed always keeps its head, the worse painted over
the better, and the newest run keeps its own, as a curve's newest reading keeps its dot.
A crowd then reads as the outline of its values with what went wrong standing out; a
passing run much shorter than its neighbors keeps its head, having room; and the way
into a stretch ([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 3)
separates what a window crowds. Nothing is merged, so a window with more runs than
columns needs no second way of drawing.

Three things hold as [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 5
has them for a gauge. A column's strip under the pointer names what the column holds: a
run alone its time, its value and how it stood, and several their range, their count,
their times and how many of them failed or warned. The lane marks a column once, however
many failures it holds. And the summary counts every run in the window, at any zoom.

The lane stands beneath a plot that has a value axis, where a failed run's stem may be
the shortest on the plot. A plot of ticks has none: a failed run is its tallest mark.

### 5. A mark is for a record with an identity, and a state has no mark

**A mark is drawn for a record with an identity, and for no other.** A record with a
state ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 3) is no event
at an instant: it says that the object stood so from then until the next record — which
accounts could be read, a workflow that is switched off, a pipeline that never ran — and
a state read unchanged stays one record. It has no mark. It stays a row of its series'
readings table, under the time the state began, with the code and the sentence it stood
with, and a measure its check declares over such records draws its curve as it did. This
narrows [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 5,
whose *records with an identity or a state* now reads *records with an identity*.

A series' runs are drawn where the series is shown
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 4): as
stems under each measure its check declares that a run gives a number, where that
measure's curve would stand; and, where no measure of it draws, as ticks on the node
that stands for its subject, in a plot titled *Runs*. A series no node stands for draws
no ticks — its readings are listed on its check's History page
([ADR-0109](0109-a-node-says-its-children-are-complete.md) decision 6) — so a type that
has not moved its lines shows what it showed
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 2).

### 6. The summary counts the runs, and what did not pass by kind

Beside its title a plot of runs says **how many runs the window holds, the measure's
newest, lowest and highest value where there is a measure, and then what did not pass,
by kind, each kind with its mark as the key**: *30 runs · newest 1h 4m · lowest 6m ·
highest 1h 4m · 1 failed · 3 warned · 12 without a verdict*, the ring, the triangle and
the bare tick each before its count. A kind that no run in the window is of is left out,
and a window without runs says *no runs in this window*. Without a measure the summary
is the count and the kinds.

The three values are taken over every run that has one, a failed run among them, so they
are what the plot draws: the lowest may be a run that crashed after six minutes. The
word is *runs* for every type, and no stretch without readings is counted, a series of
runs having no holes ([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md)
decision 5).

### 7. A line for the record alone is written in `for_record`

`CheckResult(reason=[…], for_record=[Entry(…), …])`: **a list of its own on the result,
named for where its lines go.** Its lines are ordinary entries — a text, a code, a
subject, a record — and each carries its own code and its record: it has no node's code
to take, and a reading is found by the record its line carries
([ADR-0086](0086-a-check-measures-and-grades.md) decision 2). A line without either is
refused where the result is built. The list may stand on any node of a result, and a
line's slug is no key there: a slug is what a pin holds
([ADR-0036](0036-addressable-reasons.md)), and nothing pins a line no node shows.

One thing decides the spelling. A node's own code is the worst of the codes of the lines
in its `reason` ([ADR-0042](0042-entries-carry-their-own-code.md)), and a line about a
run that failed last week must never reach that. `reason` and everything that reads a
node's lines are untouched, so a line written in `for_record` cannot.

## Consequences

- **[ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 5 is
  settled and narrowed, and [ADR-0087](0087-a-check-keeps-its-subjects-readings.md)
  decision 8 is amended.** [ADR-0092](0092-a-check-declares-its-measures.md) decision 5,
  [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) decision 4 and
  [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 5 hold as written,
  and what they are for a run is said here: a record with a state has no mark, the lane
  stays the failures' row, and nothing is merged into a column.
- **Each type says how its runs stood at its own release.** Until it does, a run it
  writes no line for is drawn without a verdict, which is true: nothing was said of it.
  A type that reads several runs of one subject on a poll shows the newest and writes
  the others for the record.
- **A verdict is written when a run is read.** A run kept before its type said how it
  stood gets its verdict at the next poll that reads it, and one no poll reads again
  keeps none.
- **The readings table says what the mark says**: a run written for the record has its
  code's cue and its sentence there.
- **A line for the record costs its run and nothing after it.** No node holds it, so it
  counts against no entry limit and no line cap. Its record goes through the seam a
  shown line's goes through; one the seam refuses leaves the line said of no reading,
  and the instance says so on its runtime node
  ([ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md)).
- **A plot of ticks is as tall as its tallest mark**, less than half a curve's plot, so
  a branch whose subjects have no measure stays short in its Series view.
- **`implementing-checks.md` says the rule**: a grading says how every run it read stood
  — on the line it shows, or for the record.

## Alternatives considered

- **A run without a verdict drawn as one that passed** — the guess the kept code exists
  to avoid: right for a type whose failures always have a line, and a failed job run
  drawn as a pass.
- **A run without a verdict counted and not drawn** — a plot reads as if nothing ran,
  and a gap on the time axis no longer means that nothing did.
- **A verdict from a shown line alone** — a line for each run does not fit a job name's
  node, and the library would need a rule of its own for the re-read that stands on no
  line.
- **An uncoded record graded again when a window is read** — with whatever thresholds
  stand then, which is what [ADR-0087](0087-a-check-keeps-its-subjects-readings.md)
  decision 8 keeps a code to avoid.
- **Every healthy line written always** — paid in entries, in the envelope and in a
  box's line cap, for the sake of a code.
- **A run that warned drawn as a failure** — two states, a summary that has to say
  *failed or warned*, and a run that took too long standing like one that crashed.
- **A run that warned drawn as a pass** — the plot hides a run time creeping past its
  limit, and only the table says so.
- **Every run keeping its whole mark** — a crowd's heads pile up along the top of the
  plot.
- **One mark for a column**, the worst verdict at the highest value among its runs — it
  moves a verdict onto another run's value: a run that failed after six minutes beside a
  second attempt that ran an hour stands as a failure at an hour.
- **A lane beneath a plot of ticks** — every failure said twice, the second time beneath
  the tallest mark the plot has.
- **A mark for each change of a state**, as a run has one — a state that lasts reads as
  a moment: ten days in which not every account could be read stand as one failure on
  the first day and one pass on the last, and the gap between them means the opposite of
  what it means between two runs.
- **A state drawn as the spell it lasted** — a line while it stood well and a box in the
  failure ink while it did not. The truthful drawing, and a design of its own: what ends
  the newest spell, what a spell that warned or kept no verdict looks like, what the
  summary and the pointer say. Not taken now.
- **Ticks for a series no node stands for**, on its check's own node — as many plots
  titled *Runs* as the check has such subjects, on a node that showed none of them.
- **A gauge's summary** — the three values and the failed count alone: a run that warned
  and one without a verdict have marks nobody counts, and a series without a measure
  says only how many failed.
- **A share in place of the counts**, *13 of 17 passed* — wrong as soon as the window
  holds a run without a verdict, which neither passed nor failed.
- **`unshown` as the keyword** — it says what the lines are not and leaves what they are
  for to the documentation.
- **A flag on the line**, `Entry(…, shown=False)` among the node's own — the smallest
  change to the surface, and one where every reader of a node's lines has to leave such
  a line out, so that one that forgets shows an old failure on the wall.
