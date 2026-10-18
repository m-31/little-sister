# ADR-0126 — A line is a template over its record, and a deployment may re-word it

- **Status:** Accepted
- **Date:** 2026-10-11
- **Related:** [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)
  (the record a line carries, and the link's shape it left to this record),
  [ADR-0086](0086-a-check-measures-and-grades.md) (the grading, pure over its record,
  its configuration and the clock), [ADR-0120](0120-every-stored-time-is-an-instant.md)
  (the configured zone, and `spans.local_time`), [ADR-0018](0018-markdown-rendering.md)
  (the Markdown a line is, and what the renderer drops),
  [ADR-0025](0025-check-provided-subnode-metadata.md) (the `subnodes:` block whose
  shape `display:` takes), [ADR-0092](0092-a-check-declares-its-measures.md) (the
  declaration a type's forms, words and fields are shaped like),
  [ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md) and
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (what stands beside a record
  rather than inside it), [ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) (a
  line written for the record alone), [ADR-0049](0049-the-check-authoring-surface.md)
  (the surface this adds to), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (the envelope, which carries an entry's form), [ADR-0051](0051-what-startup-refuses.md)
  (what startup refuses), [ADR-0031](0031-deployment-config-directory.md) (the aspect a
  deployment-wide layer would be), [ADR-0029](0029-per-user-presentation-preferences.md)
  (the presentation preferences, which do not move)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check type writes the sentence of each of its lines in code. `little-sister-github`'s
`actions` line is the worked example: the type knows the repository, the branch, the
workflow, the run's number, its verdict, both runs' links and when the run started, and
it writes one Markdown string with two links baked in, every name escaped by hand, and
the start left out. Since [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)
the line carries the record it was written from beside the sentence, but the wording is
still the type's code. A deployment that wants a line to say more — the routine its
team follows for a kind of node, or when a run started — needs a release of the type;
and a type that says a time writes it itself, through `spans.local_time`, into a
sentence nothing can write again.

The family's types write three kinds of line, and this record is held against all of
them. `little-sister-github` makes its lines from one reading each, in all of its
aspects, and a line's shape follows from data the reading may lack: no completed run, a
run number GitHub did not send, a run in flight or none. `little-sister-aws` joins a
description of what was read — a region where an account reads several, a label after a
rule shortened a name, a console link wrapped in the account's template, a status — to
the grading's judgment, `Succeeded, but that run started 2d ago —` followed by a rule's
own sentence, and says a time as an age. `little-sister-wiz` shapes its issue line by
flags and a word derived in code, and a control line it makes from several issues
carries no record at all. None of the library's own types carries a record on a line.

## Decision

### 1. A line is rendered once, where the grading hands it back

A template is rendered when the grading hands its line back, into the line's `text`, and
every surface reads that text: the card, the node's page, the events and the history,
the Copy document, the envelope and the clients. A time it says is written in the
configured `timezone` and `time_format`, as every other time a page shows
([ADR-0120](0120-every-stored-time-is-an-instant.md) decision 7), through
`spans.local_time` and never a path of its own. A viewer's own zone — one the viewer
picks, every time on a page following it, and a line's time kept an instant inside
`text` until a surface writes it — is no part of this record; it would be one change,
made in that one function.

### 2. A template is rendered over the record and the line's words

The record is a fact about the world: stored, kept in the series, published and weighed
against `record_limit`. A line is what the grading says of that fact, under this
deployment's configuration, at this moment, and a template re-words only that; so it is
rendered over what the grading had in hand when it spoke — the record, and the **words**
the grading hands over with the line. A word lives for the rendering alone and is never
stored, published or weighed, and it is as reproducible as the rest of the grading
([ADR-0086](0086-a-check-measures-and-grades.md) decision 6).

**Each has a namespace of its own, by construction.** A record's field is named plainly,
by its dotted name — `{completed.run_number}` — and a word under `line.` —
`{line.why}` — so that no field can shadow a word and the record's vocabulary stays the
check's own, as `refused` stands beside a line's record rather than inside it
([ADR-0093](0093-a-record-the-seam-refuses-costs-its-line.md)) and an identity beside a
reading's ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md)).

**What goes where.** A fact about the subject is the record's, whether it was read or
derived from what was read — the word a type chose for a run's outcome among them, beside
the source's own. What a type adds from its configuration, from the clock or as its own
wording is a word: a link wrapped in a template the configuration holds, a label after a
rule shortened a name, a region shown only where several are read, an age, a rule's own
sentence. A line made from several readings carries no record, and its facts may not be
words, so it stays its type's sentence. A line written from one of several readings —
the one its verdict is about — is that reading's line: it carries that record, and what
the others add is words, as the executions in flight beside a pipeline's verdict are
(decision 3).

### 3. The grading names the form, and a segment leaves out what is not there

A **form** is the sentence the grading chooses to say — a verdict, no completed run, a
disabled workflow, a stale success — and the type ships its default text. A deployment
re-words a form and adds none, since only the grading chooses one. Inside a form a
**segment** is shown only when the values it names are there; a value is absent when it
is null, missing, empty or false — a word the grading did not hand over among them, which
is how a region is shown only where several are read. A segment may name a value it does
not print, so that a flag works. That is the one construct beyond substitution: no else,
no not, no comparison, no loop and no filter.

**The type decides what is true and what it judged — the record, the form and the words —
and the deployment decides what a line says of them.** A fact a deployment wants on its
lines is one segment in the forms that should say it, and where a type hands over both a
record's own time and an age, which of the two a line says is the deployment's.

**What lives where.** The sentence the grading chooses is a form's text, where a
deployment can re-word it, and the values inside it stay words. A phrase that only spells
a state word is a word, since a form per state would copy the whole line once per state;
a phrase table beside `state_map`, shipped by a type and overridden by a deployment, is
the shape a deployment's own phrase for a state would take. A list — one phrase per
status of the executions in flight — is a word too, the one thing a form cannot write.

### 4. A link is Markdown in the template

A template is Markdown, as `text` is, and a link is Markdown's own construct; its target
is a URL the record holds or a word. The record holds the URLs the source sent, and one
a type builds while measuring out of what its record keeps only in part, such as a name
it clips; a link a type builds out of what the record holds whole is a word, so that no
record stores a fact twice. The library escapes what it substitutes: a value as text as
`plain()` does, a value in a link's target as a URL. A target that is absent, or is not
an http(s) URL, leaves the link's words as plain text, so that a missing link never
hides what it labels, and the renderer keeps dropping unsafe schemes
([ADR-0018](0018-markdown-rendering.md)).

This answers what [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)
decision 2 left to this record. What each surface does with the Markdown it is handed is
the surface's; which words link where is the template's. A line may carry two links, and
a deployment may write one of its own.

### 5. A deployment writes a template in the check's own file, over what its type declares

A deployment usually needs no template, because a type's default is good; it writes one
where its team's own routine for a kind of node should be added to what its lines show.
A template is a deployment's handling, never a translation: lines stay in American
English.

- **The block.** `display:` stands in a check's YAML beside `subnodes:` and `measures:`,
  keyed flat by a form's full name, and a key that names no form of the type stops the
  start. `{line.default}` is the text of the layer beneath — the type's default — so that
  a layer per type for the whole deployment, an aspect of its own
  ([ADR-0031](0031-deployment-config-directory.md)), can come beneath the check's block
  without changing what any template means, should a deployment that runs one type many
  times need it.
- **The declarations.** A type declares its forms — each a name, one sentence and its
  default text — and the words and the fields a template may name — each a name, one
  sentence and an example — as it declares its measures
  ([ADR-0092](0092-a-check-declares-its-measures.md)). A template that names a form, a
  field or a word its type does not declare stops the start, as every other
  configuration error does; a type's own defaults are checked against the same
  declarations when a check of the type is built, so that a typo in a default fails the
  type's own tests.
- **The notation.** `{field.path}`, `{line.word}` and `{line.default}` — not
  `subnodes:`'s bare `{default}`, since a plain name is the record's, and no type
  declares a word called `default`. A segment is `{? …}`, shown when every value it
  prints is there, or `{?name: …}`, shown when a value it need not print is there as
  well; a link's target is not among the values a segment waits for, since a missing
  link never hides what it labels (decision 4). Segments nest, `{{` writes a brace and
  `}}` writes one outside a segment — inside one a `}` ends it, so that two segments
  ending together read `}}` — and everything else is Markdown, in which a brace means
  nothing.
- **What prints.** A time under `at`, `started` or `ended` in the configured zone and
  format (decision 1); a value absent outside every segment as `—`, the library's spelling
  of *none*, which is visible and never an error that costs the run.

### 6. A line is one text

A line has no compact and verbose forms for a viewer to choose between. Its fuller form
is the node's own page, which lists the line's record
([ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md) decision 5), and how
much of a node a viewer sees is the wall's to give. A viewer's choice of a line's length
would come with a viewer's own zone, where rendering for one viewer is built once for
both.

### 7. The grading asks the library for the line

A check asks for a line with `Check.line(form, reading, …)`, handing over the form, the
reading, the line's slug, its code and `running`, and its words. The library renders the
form's text — the deployment's `display:` over the type's default, as resolved when the
check was built — over the reading's record and the words, escapes what it substitutes,
and returns the `Entry` with its text, the record as its `data`, the reading's subject,
and the form it was written from. The grading stays pure, a series graded again renders
the same way, a type's own tests see the finished line, and the words live for the call
alone. A line written for the record alone
([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md)) is asked for the same way.

What a type stops writing is the sentence of every line that carries a record, the
Markdown links in it, `plain()` around a name, and `local_time` and ages inside it; a line
without a record keeps its sentence. What the library adds to the check-authoring surface
([ADR-0049](0049-the-check-authoring-surface.md)) is additive, so the check API's epoch
does not move: the three declarations, passed to `Check.__init__` beside
`measure_defaults`; `display:`, a common field that arrives as a constructor keyword;
`Check.line`; an entry's `form`, which the envelope carries with the rest of the entry
([ADR-0080](0080-the-envelope-is-the-snapshot-published.md)); and `/system/installed`,
which lists each type's forms, words and fields with their sentences and examples — the
page a deployment writes against.

## Consequences

- **A type adopts in a release of its own**, raising its floor to the library's release
  that brings this, and it adopts whole, so that no line of it is decided in two places.
  Until it does, it writes its sentences as before, and nothing on any surface moves.
- **A record's field names, a type's words and its forms' names are stored keys**: a
  deployment's template names them, so renaming one is a breaking change, said at the
  top of the type's release notes.
- **The node's page shows the form a line came from**, beside the line: the key a
  deployment writes to make that line say more.
- **`text` stays the contract.** Events, history, the Copy document and the envelope
  carry the rendered line, and a client reads what it read before; the envelope gains an
  entry's `form`, additively.
- **A judgment is the type's to make and the deployment's to place.** The clause that
  says why a line is red is a form's text with its values as words, so a deployment can
  move it, re-word it or leave it out of its own template, and the grading still decides
  when it is said.
- **A startup that refuses names the file**, as a bad check configuration's does; a
  value a template expected and the record lacks costs a `—` on the page and nothing else.

## Alternatives considered

- **The viewer's own zone**, every time on a page in it — chosen by the viewer, or the
  browser's taken without asking. The second would show a kiosk on a machine set to UTC
  in UTC and part a page from its log; both would need a line's time kept as an instant
  inside `text`, since events and history keep no record. Neither is needed while a
  deployment's viewers read it in its zone.
- **The record alone**, every word a line needs put into the record. Configured values
  would go stale in the series the day the configuration changed, and the judgment,
  which needs the clock, could not go in at all.
- **Filters in the template.** The start of a language, and still no way to say the
  judgment.
- **Flat forms alone**, every shape a form of its own: they multiply with every optional
  part — eight for the `actions` line, twelve for a Wiz issue line — and push the parts
  into words a deployment cannot re-word. **Segments alone** cannot say what the grading
  decided without an else and a not.
- **A typed link**, which puts the type's wording inside a value; and **a line's link
  beside its text**, a field on the entry and in the envelope, with one link per line
  where `actions` needs two.
- **A deployment-wide block before a deployment needs one**, and **undeclared fields
  read as absent**, which would put a typo on the wall instead of stopping the start.
- **Two texts per line**, compact and verbose, which doubles every form a type writes and
  every template a deployment writes for a preference nobody asked for; and **a text per
  surface**, which is the wall's to raise if a card ever shows a line too long.
- **The engine rendering after the grading**, which would have an entry carry words it
  must never keep and leave every other path that grades to render on its own; and **a
  function each type calls** over templates it resolves itself, which writes the same
  plumbing once per type.
