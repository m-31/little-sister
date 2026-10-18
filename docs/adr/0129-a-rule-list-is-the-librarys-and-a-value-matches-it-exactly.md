# ADR-0129 — A rule list is the library's, and a value matches it exactly

- **Status:** Accepted
- **Date:** 2026-10-11
- **Related:** little-sister-aws **ADR-0003** (the rule list this lifts, its decisions 4
  to 7), [ADR-0126](0126-a-line-is-a-template-over-its-record.md) (decision 2, the
  words a type hands over with a line, the `rule` word among them now),
  [ADR-0086](0086-a-check-measures-and-grades.md) (decision 6, a grading pure over
  its record, its configuration and the clock, which keeps no tally),
  [architecture.md](../architecture.md) §11 (the surface the rule list joins)

## Context

Two packages say something about a named part of what one aspect lists, and each said
it in its own way. `little-sister-aws` has a `rules:` list (its ADR-0003): consulted in
order, the first match deciding, a required `name:`, `names:`, `prefixes:` and
`regexes:` compared with case folded and a regex matched anywhere in a name,
`unnamed: true` for the instances with no `Name` tag, `ignore: true` as an action, and a
log line for a rule that matched nothing. `little-sister-github` had one flat list of
regexes for its `actions` aspect, searched with case folded in a workflow's display name
and applied alike in every repository; an entry that was not a string was turned into
one and compiled. A deployment that wrote a repository's name over a list of files —
the one workflow file of the one repository it wanted left out — loaded without a word
and left out nothing, and no title could have said it: two of its repositories carried
a workflow under the same title.

The folded case and the unanchored regex of the AWS rules were taken from that GitHub
key by imitation, not by sharing. A property travelled from one package to the other
without anybody deciding it a second time; one implementation would have carried one
decision.

## Decision

### 1. A rule list is the library's

A package that lets a configuration say something about some of what an aspect lists
reads it as the library's rule list. The list is consulted in order and the first rule
that matches decides, whole: an exception is a rule written above the rule it excepts.
Every rule carries a `name:`, unique in its list, which a refusal, the log line of
decision 5 and the `rule` word of decision 6 call it by. `ignore: true` drops what the
rule matches — no line, nothing read for it where the package can spare the read — and
is refused beside any key of the package's own, since a dropped value has no line to say
anything on. A rule that names nothing to match is refused at the start, and so is a
key that neither the library nor the package takes, the refusal naming the keys a rule
takes.

### 2. A package declares the axes its rules match

A value is addressed along the axes a package declares. A named axis is a key on the
rule, whose value is a list of names or a block of `names:`, `prefixes:` and `regexes:`;
an aspect with a single axis may write those keys on the rule itself, as
`little-sister-aws`'s rules do. A rule matches when every axis it writes matches; an axis
it leaves out matches any value; within an axis, any of its forms matching is enough.

An axis says whether its values can be absent. Where they can, `unnamed: true` matches
the absent value and nothing else does; where they cannot, the key is refused, since a
rule that can never match is configuration that looks like it works. Absence is the
library's because the order and the refusals that read a rule's matchers have to see it.
The word is `unnamed`: a missing `Name` tag is the only absent value any package has.

### 3. A value compares exactly

A name matches a value equal to it as the source returned it; a prefix, a value that
begins with it; a regex, a value it matches whole, as `re.fullmatch` does, so `^` and `$`
are never needed and a pattern that means less than the whole value says so with `.*`.
Nothing folds case: a pattern that wants case folded says so itself with `(?i)`. No flag
on a rule changes what its entries mean; the kind of match is the key an entry is
written under. A rule matches the value as the source returned it, never a name a
package shortened for display.

### 4. What a rule says beyond `ignore:` is the package's

A package hands the library the keys of a rule that are its own and a reader for them,
and the rule carries what the reader returned. `little-sister-aws`'s threshold pairs and
the overrides a rule writes are such keys. They are grading, which a later step of the
design takes through one seam, and nothing in this record decides them.

### 5. A rule that matched nothing is a log line

Never a node: a typo in a matcher is a fact about the configuration, not a finding, and
a rule that matches nothing is often right, since what it names may come and go — a load
test's instances exist while it runs. The line is written at `INFO` from the measuring
half, one per check and rule list, naming the rules, when that set changes and once more
when it empties; at `frequency: 60s` an unconditional line would be some fourteen
hundred identical records a day about a mistake that was true at breakfast. The set is
the run's, not one source's.

To each rule it names, the line adds what the rule missed, so a slip is pointed at
rather than forgiven. Where the rule's own matcher matches a value the run saw, a rule
above it decided that value, and the line names that rule: an exception written below
the rule it excepts is the slip a first match invites, and it shows otherwise only as a
level that never applies. Where it matches none, the line adds a value the run saw that
it would have matched with case folded — a slip in a name, a prefix or a regex. A value
is quoted as the source returned it, and an absent one is said as absent — *an absent
name* — since a configuration addresses it as `unnamed:` and never writes it as a value.
The rule list the check holds keeps the run's tally — the rules that matched and the
values seen — because the grading keeps none (ADR-0086 decision 6), and the package asks
for the report once a run. A run that could not read the whole of its scope leaves the
set as it was, so a source that did not answer does not pass its rules off as typos.

### 6. A line names the rule that judged it

A rule owns a line where a key of its own judged it — a level, a gate, a switch, whatever
the type grades by — an `OK` included: the question a line answers is which rule judged
it, not which rule matched its reading. A rule that only matches owns no line: one
written above another as its exception, keeping a value from a later `ignore:`, and one
that writes nothing beyond its matcher, whose values the block judges. Nor does a rule
own a line its keys did not reach — a line for the record alone about one run of
something the rule judged as a whole. The owning rule's name is the word `rule`: what a
type adds from its configuration is a word (ADR-0126 decision 2). A type whose rules can
judge declares it and hands it over on every line a rule owns; its default forms print
it, and a deployment's `display:` may leave it out. On a line no rule owns the word is
absent, and the segment that prints it leaves itself out; a type whose rules only drop
or keep values declares no such word. A rule's own sentence stays a word of its type's,
and the rule's name stands in for no sentence, a fired judgment's or any other, so a
line that names its rule never says the name twice.

### 7. The surface grows, the epoch stays

The rule list, its matcher and the `rule` word are added names of the check API
(architecture.md §11). Adding a name moves no epoch, so a package's floor rises to the
release that brings them and nothing else of it has to change.

## Consequences

- `little-sister-aws` takes its matcher from here. Its names, prefixes and regexes stop
  folding case and its regexes match whole names, so a configuration that leaned on
  either sees its rule match nothing, which the log line says with its hint; its
  ADR-0003 says so in an update. What its rules grade stays its own.
- `little-sister-github`'s `actions` aspect has rules of its own: two named axes, the
  repository's name and the workflow's file its node is named by, `ignore:` their one
  action, read before anything is spent on a workflow.
- Every line a rule judged carries one word more, on the wall and wherever the line is
  read again — the events, History, Copy. No slug moves, and a deployment that does not
  want the word leaves it out of its `display:` block.
- The log line about rules that matched nothing reads the same for every type, and the
  hint costs the tally of one run's values, dropped when the run is reported.

## Alternatives considered

- **Each package its own code, written to one rule.** Rejected: the folded case this
  record removes reached one package from the other by imitation, which is how two
  implementations of one rule drift.
- **One module carried verbatim by both packages and compared byte for byte.** Rejected:
  shared code belongs in the library, where what it exposes is promised surface, and a
  carried copy that drifts shows up in somebody else's commit.
- **Case folded by default, or a flag for it; a `regex: true` flag on the rule.**
  Rejected: folding is harmless only where the source's own names ignore case, and a
  workflow file is a path in git; a flag changes what every entry of a rule means from
  a line a reader may not be looking at.
- **A regex matched anywhere in the value.** Rejected: every pattern is loose until it
  is anchored, and a forgotten anchor fails the quiet way, by matching more.
- **Absence left to the package that has it.** Rejected: the refusal of a rule with
  nothing to match, and the log line, read a rule's matchers and could not see
  `unnamed:`; the package would answer both a second time for one group.
- **Every axis named, a one-axis aspect's included.** Rejected: every rule
  `little-sister-aws` reads would gain a key to say what it says without one today.
- **The library reading its own keys and handing the package the rest of each rule.**
  Rejected: the refusal of a key nobody takes, and of `ignore:` beside a key of the
  package's, would be made by the two together, and by neither alone.
- **A rule that matched nothing shown on the instance's own node.** Rejected: see
  decision 5.
- **A hint about case alone.** Rejected: an exception written below a rule that takes
  every value it matches would be named as matching nothing, its values in plain view,
  and nothing would say that the order is the slip.
- **The rule that owns a line named only on the check's configuration card.** Rejected:
  never on the wall, where the case that raised decision 6 was read.
- **A line owned by every rule that matched its reading and did not drop it.** Rejected:
  a rule that keeps a value from a later `ignore:` judged nothing, and every line for the
  record about one run would end in the name of a rule none of whose keys reached it.
