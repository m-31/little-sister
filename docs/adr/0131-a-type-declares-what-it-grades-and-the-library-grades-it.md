# ADR-0131 — A type declares what it grades, and the library grades it

- **Status:** Accepted
- **Date:** 2026-10-17
- **Related:** [ADR-0086](0086-a-check-measures-and-grades.md) (a grading, pure over its
  records, its configuration and the clock — decision 6 — and a window graded by a call
  of its own — decision 8), [ADR-0126](0126-a-line-is-a-template-over-its-record.md)
  (the declarations this one is shaped like, the words a line is handed, and the field
  names a grading reads),
  [ADR-0129](0129-a-rule-list-is-the-librarys-and-a-value-matches-it-exactly.md) (the
  rule list whose grading keys this takes — decision 4 — its log line — decision 5 — and
  the word `rule` — decision 6), [ADR-0087](0087-a-check-keeps-its-subjects-readings.md)
  and [ADR-0113](0113-a-measurement-reads-what-its-check-kept.md) (the kept records a
  window is made of, and why a grading never reads the store),
  [ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md) (the code a kept record landed
  with), [ADR-0042](0042-entries-carry-their-own-code.md) (an entry's own code),
  [ADR-0051](0051-what-startup-refuses.md) (what startup refuses),
  [ADR-0049](0049-the-check-authoring-surface.md) (the surface this adds to),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope, which
  carries an entry's grading), little-sister-aws ADR-0003 (the pair, its spelling and
  its comparison, which this makes the family's)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check turns what it read into OK, WARN or ERROR in one of five ways, and each type
parses and applies its own. **A map** from a word to a code: `little-sister-github` has
four — a Dependabot advisory's severity, a code-scanning alert's on either scale, and a
disabled workflow's state — `little-sister-wiz` one, a band's severity, and
`little-sister-aws` two, an alarm's state and a pipeline execution's status. **A pair**
of levels over a number: `little-sister-aws` writes `max_age_warn` and `max_age_error`
flat in an aspect's block, compared strictly above, with `max_age_reason` as the
judgment's sentence and `max_age: null` switching it off, and its rules write the same
keys for the names they match; this library's host metrics write `thresholds: {disk:
{warn: 90, error: 95}}`, nested and compared at or above, and `macos-memory` a
process's `warn_mb`. **One level and its code**: the `file` check's `max_age` and
`stale_code`. **A set of accepted values**: the `http` check's `expected_status`. And
**a grading in code alone**, which no key reaches.

So the family has as many seams as it has checks. A pair has three spellings and two
meanings at its boundary, and one of the spellings cannot switch a judgment off — a
deployment writes `{warn: 101, error: 101}`, a level never reached, to do it. Each map
folds case its own way, and a misspelled key is accepted and grades nothing, silently.
Nothing lists what a type grades, or which key a deployment writes to change it. Two
records left their part of this open on purpose: ADR-0129 decision 4 left the grading
keys a rule writes to *a later step of the design*, and ADR-0086 decision 8 left the
grading of a window to *a different call*, which the series phase adds — so no check can
say *the last run succeeded within 26 h* from what it keeps, though every kept record
carries the code it landed with.

The design round with Lex of 2026-10-17 settled what follows, one question at a time;
what each declined is under *Alternatives considered*.

## Decision

### 1. A type declares what it grades, and the library grades it

A type declares every value it grades: a name, which is a stored key, one sentence, the
record field it reads by its dotted name — the names a template addresses
([ADR-0126](0126-a-line-is-a-template-over-its-record.md) decision 5) — its kind, and
for a pair which way it grades, its default, and the key a deployment writes it under in
the block of what it grades. The declarations pass to `Check.__init__` beside the forms,
words and fields, and are checked when a check is built.

The grading asks the library for a verdict, `Check.verdict(name, reading, …)`: the
code the named grading gives the reading under this check's configuration and the rule
that matched its name, with the sentence written for it. It hands the verdict on to
`Check.line`, which takes the line's code from it and hands the line the words `reason`
and `rule` (decision 5). The library reads a deployment's keys when the check is built
and refuses one that does not fit, naming the file
([ADR-0051](0051-what-startup-refuses.md)); `/system/installed` lists each type's
gradings beside its forms, with their sentences, defaults and keys; and an entry names
the grading that decided its code, as it names its form, on the node's page and in the
envelope — none where a pair holds no level, switched off or never given one, since it
then decided nothing. A judgment with more than one input — `little-sister-aws`'s
stale success, an age and a run time — keeps its logic in the type's code and asks the
library for each comparison.

### 2. One spelling per kind

A **map** is a mapping from a word to a code under the key its type declares, the shape
every map has. A **pair** is little-sister-aws ADR-0003's spelling: `<name>_warn` and
`<name>_error` in the block of what they grade, `<name>_reason` beside them, `<name>:
null` switching the judgment off, and a level written with its unit — a count, a
number, a duration, a size, an amount or a share, as the type declares. A **set of
accepted values** is a kind of its own, `http`'s `expected_status`. A rule writes the
same spelling (decision 6).

The others retire. This library's `thresholds:` blocks of `host-metrics`, `macos-memory`
and `qnap-metrics`, `macos-memory`'s `warn_mb` and `error_mb`, and the `file` check's
`max_age` with `stale_code`, which become a pair with one level, are refused at start,
naming the file and the key that replaces each; a package's own spellings retire when it
adopts. The release notes say each at the top (PL10).

### 3. A pair passes at its level: a maximum fails above it, a minimum below

A level is the last value that passes. A pair grades one way, which its type declares
and its name says — `max_…` fails above its levels, `min_…` below them — so a number in
a configuration reads the same everywhere: `max_per_name_warn: 1` allows one, and
`min_repos_warn: 20` asks for twenty. Equal levels, and an error level that is not
beyond the warn level, are refused at start. The family's two minimums mean what they
did as `min_` pairs, and the `file` check passed at its level already; the host metrics
move by one step at the boundary, and `null` replaces a level written never to be
reached.

### 4. A map folds its words, and says a key that names none

A map's key is a word of its source's vocabulary, not a name: every map matches with
case and the spaces around a word folded, so `ALARM:`, `InProgress:` and `critical:`
load as deployments write them. A key that matches none of the words its type declares
for that map is said once in the log at start, as a rule that matched nothing is
([ADR-0129](0129-a-rule-list-is-the-librarys-and-a-value-matches-it-exactly.md)
decision 5), and grades as written, since it may be a word the source began to send
after the type's release. A word no key names grades WARN, so that a new word is seen.
A name still compares exactly (ADR-0129 decision 3).

### 5. A grading's sentence is written beside it, and the library hands it to the line

`<name>_reason` stands beside any grading a type declares by name: a pair's, and a
judgment's that is neither a pair nor a map, as `little-sister-aws`'s `lambda` aspect
has `error_reason` and `silent_reason`, and `qnap-metrics` a drive's `smart_reason`.
Where a grading decided a line's code, the library hands its sentence to the line as
the word `reason` on every type, as it hands `rule` (ADR-0129 decision 6), so that no
type passes one along on its own. A map carries none: a line under a map says the word
that colored it, and a deployment's policy for a band is the band's `about`.

### 6. A rule writes what its block grades

A rule may write any grading its block declares, in the block's keys and spelling, and
the library reads it: a pair it writes replaces the block's whole, a map it writes
changes the block's word by word, and a grading it does not write is the block's.
`/system/installed` says of each grading that a rule may write it, and a rule's key is
refused at start as the block's is. ADR-0129 decision 4 narrows to the keys that are
not grading, such as what a run reads, which stay the package's through its reader.

### 7. A window is handed to the seam, cut at the reading it grades

Once a run is graded, the library applies each declared window grading over the
subject's kept records up to and including that run's reading — what `kept()` answers
and the reading at the code it stands at, each at its own time, the record's `at` where
it gives one, cut at the reading's — so that a reading graded again later sees the
window it had, as far as the store still holds it. It is a call of its own
([ADR-0086](0086-a-check-measures-and-grades.md) decision 8), pure over what it is
handed (decision 6), and never a read of the store
([ADR-0113](0113-a-measurement-reads-what-its-check-kept.md)); a type's `grade()` stays
one run's readings. It is applied before the run is stored, so that the node's code is
the window's too, and the reading is kept as its node then stood. A window grading is
declared, written, ruled, refused and listed as any other. One on a check that keeps no
series is refused at start, and a window reaches no further back than the check keeps:
a level beyond that is said once in the log at start. A window that fails is a line of
its own on the node where the reading stands, from a form the library declares, so a
deployment re-words it as it re-words any other.

### 8. A window says `since` first, and `change` after

Each kind is a pair over a number the window yields. **`since`** is the time from the
newest kept record that stood OK — the code it landed with
([ADR-0111](0111-a-runs-mark-says-how-the-run-stood.md)) — to the reading graded, each
at its own time: a maximum, so `max_since_ok_error: 26h` says *the last run succeeded
within 26 h*. It reads codes and times and no field of the type's, so any check that
keeps a series can take it. **`change`** is a declared number's newest value against the
record before it, as a ratio: a minimum, so `min_size_change_warn: 50%` says *it did not
shrink by half*. It needs a type to declare the number, and comes once one does.

## Consequences

- **The library's own checks adopt first**, and their keys move: a deployment that wrote
  `thresholds:`, `warn_mb` or `max_age` with `stale_code` edits its file before the
  release starts, as the refusal says; one that wrote none edits nothing. What warned at
  a level warns beyond it.
- **A package adopts in a release of its own**, raising its floor to the library release
  that brings this, and until it does it grades as before. Its maps load unchanged; its
  minimums, its pairs and its rules' grading keys move to the one spelling.
- **The check API grows and its epoch stays**: the declarations, `Check.verdict`, an
  entry's grading and the window call are additive
  ([ADR-0049](0049-the-check-authoring-surface.md)). A grading's name, its key and its
  words are stored keys, so renaming one is a breaking change, said at the top of the
  type's release notes.
- **What a type grades is listed**, and a line's page names the grading that judged it:
  the key a deployment writes to grade that line differently, beside the form it writes
  to say it differently.
- **A misspelled key is said**, at start, where today a map takes it and grades nothing.
- **A window costs a series**: a check whose window grading needs records keeps them
  (`series_keep`), and a short `series_keep` at a short frequency sees a short window.

## Alternatives considered

- **Shared parsers each type calls** from its own code — the smallest change, which
  nothing lists or refuses alike, and the plumbing per type that ADR-0126 declined for
  lines. **A `grading:` block** a deployment writes for any value, as it writes
  `display:` — two ways to say one thing while the types' keys stand; it can come on top
  of this if a deployment needs to grade a value its type does not.
- **Every type keeping its keys**, a pair read in three spellings for good; and **both
  spellings for a release** with a note at startup, which the family has not done — a
  retired key has been refused outright with a message naming its replacement.
- **Strictly above for maximums alone**, which leaves the minimums keys of their own
  types; and **at or above**, under which `max_per_name_warn: 1` warns at one instance
  and every `max_` name allows one less than it says.
- **The source's own spelling, exactly**, for a map's key, which moves every `wiz` map
  and spells a band one way and its key another; and **refusing a key no declared word
  matches**, which leaves a deployment unable to map a word its source has begun to send
  until its type releases.
- **A sentence for each word of a map**, a second shape for an entry nobody has asked
  for; and **no sentence keys**, the wording left to `display:`, under which two rules
  could no longer say two sentences.
- **Rules writing pairs alone**, which leaves maps and the `lambda` aspect's judgments
  outside the seam; and **rules left as the package's**, a reader per package.
- **A grading that reads the store when it runs**, which judges a past reading against
  a window it never had; and **windows graded by the engine outside the seam**, a second
  mechanism in which the deployment names the field and the words that mean success.
- **`since` and `change` together**, `change` with no type asking for it yet; and **a
  wider vocabulary now** — a count of codes in a window, runs in a span — which can come
  as kinds of the same pattern when a deployment asks.
