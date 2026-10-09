# ADR-0121 — A noise cap is declared by the package that brings the noise, and `LOG_LEVEL` has the last word by name

- **Status:** Accepted
- **Date:** 2026-10-04
- **Related:** [ADR-0049](0049-the-check-authoring-surface.md) (decision 4: logging is
  promised as a behavior, with the default's level, `LOG_LEVEL` and the two caps beside
  it — which this amends; decision 5: what a name on the surface costs),
  [ADR-0064](0064-the-resolver-is-a-registration.md) (a registration records the
  package that made it, and the order of imports decides nothing),
  [ADR-0048](0048-an-assembled-content-security-policy.md) (the same shape for a
  header: packages contribute, what they may contribute is bounded, and the deployment
  has the last word),
  [ADR-0070](0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md) (the
  end of the registration window, in the application's import),
  [ADR-0091](0091-an-import-is-not-an-instance.md) (what an import may do, where the
  lines it logs are kept, and a door that reaches out while it registers),
  [ADR-0100](0100-system-is-two-views.md) (decision 3: the *Installed* view, which
  gains a section), [ADR-0076](0076-the-instance-node-is-a-branch.md) (the startup
  node, where a refused declaration is a line),
  [ADR-0051](0051-what-startup-refuses.md) (decision 2, the epoch),
  [ADR-0003](0003-config-and-secrets-via-env-file.md) (`.env` feeds the environment)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Logging here is promised as a behavior
([ADR-0049](0049-the-check-authoring-surface.md) decision 4): the library logs through
the standard hierarchy and configures the root logger only where the application has
not, *a default, never a seizure* in the module's own words. That default is at `INFO`
unless `LOG_LEVEL` names another level, and beside that level it caps two loggers that
are not its own: `httpx` at `WARNING` and `markdown_it` at `INFO`. ADR-0049 calls the
two *dependencies noticed one at a time, each after somebody read a log*. Of every
other one it says that *a chatty dependency is still quieted by capping its own
logger*, and `architecture.md` §11 leaves that to the deployment.

**That leaves the decision with whoever cannot know.** What a dependency writes is
known to the package that brings it. `little-sister-aws` builds the session it reads
through at every run, and the SDK says each time, at `INFO` under
`botocore.credentials`, where it found the credentials: 192 of the 6,987 lines one
instance wrote in sixteen hours, one sentence 192 times. The library is the wrong
place to cap that logger: it does not depend on the SDK, and a list in the library of
what its packages bring is the dependency turned around. So each deployment finds the
line by reading its log. One capped the SDK's loggers in its startup file; another,
set up later with the same package, has the line at every run.

**The package cannot do it for itself either.** A `setLevel` where a package is
imported is a level for somebody else's log, set by code the deployment did not
write, and set whether or not the application configured logging itself, which is
what ADR-0049 decision 4 keeps the library from doing. Whether it holds is decided by
the order of the deployment's imports: a level the deployment set before that import
is overwritten, and one it sets later stands.

**A row nobody owns stays.** No Python project of the family installs `httpx`: not the
library, not one of its four packages, not a deployment, and no lock file names it.
The library caps it wherever its default runs.

**A cap can add lines.** A level on a logger is that logger's level, whatever stands
above it. With `LOG_LEVEL=ERROR` the root is at `ERROR`, `httpx` still at `WARNING`
and `markdown_it` at `INFO`: those two go on writing from their caps up, and nothing
else writes below `ERROR`.

**And without code a deployment can say one word.** `LOG_LEVEL=DEBUG` lowers the root.
That adds none of the library's lines, since nothing in it logs below `INFO`, and
every line of every dependency but the two capped ones: the deployment that tried it
had a log two thirds SDK request detail. Between that and an edit to its startup file
there is nothing. To see how the SDK looked for its credentials, for a login that
fails on one machine, a deployment takes everything or changes code. And no page says
what is held back: `/system/installed` lists check types, packages, extensions, doors
and the policy, and no logger.

The shape of an answer is common where one program hosts other people's code. The
standard library's advice ends at handlers: a library adds none but `NullHandler`,
their configuration being *the prerogative of the application developer*. It says
nothing of a dependency two levels down that is loud at the level the application
chose. Hosts answer that with a table of levels by logger name, filled from three
sides. oslo.log ships `default_log_levels`, *logger=LEVEL pairs* for what an OpenStack
service is known to bring; a service adds its own to that default; and the operator's
configuration replaces the list. A Home Assistant integration names in its manifest
the loggers its requirements write under. And `RUST_LOG=error,hello=warn`, as Rust's
`env_logger` reads it, is the operator's side in one variable: a level, and names
beside it.

One thing was found on the way, by running it: **whether a `LOG_LEVEL` written in
`.env` is read depends on what a process imports first, and in the order a deployment
starts in, it is not read.** `little_sister.logger` reads the variable when it is
imported, and the module that reads `.env` into the environment is imported after it
where a process imports a check package first, and where it imports the application
first. `LOG_FILE` is read the same way. Both work from the process's own environment,
and `architecture.md` calls `.env` *secrets read before anything else*.

## Decision

### 1. The caps are rows, and every row has an owner

A noise cap of the default is a row: a logger's name, the level it is capped at, the
package that declared it, and a sentence that says what the cap hides. The library's
rows are those for its own dependencies, and that is one: `markdown_it` at `INFO`,
which hides a `DEBUG` line for each block rule of every render. The cap on `httpx`
leaves: nothing the library depends on logs under that name.

### 2. A package declares a cap, and sets no level

A package that brings the AWS SDK, say, in the import-before-app slot beside its other
registrations:

```python
import logging

from little_sister import noise

noise.cap("botocore.credentials", logging.WARNING,
          hides="where each new session found its credentials, a line a run")
```

The call records a row and touches no logger. The package is inferred from the call
site, as a resolver's is ([ADR-0064](0064-the-resolver-is-a-registration.md) decision
1), a caller that cannot be identified included. A deployment's own code declares a
row the same way where it wants one on the page: a deployment is a package like the
others (decision 4 of that record).

### 3. What a package may declare is bounded

- **A dependency's logger.** Never the root, and never `little_sister` or a logger
  beneath it: the library's own lines are what the log is for.
- **`INFO` or `WARNING`**, by `logging`'s constant. A package may take a dependency's
  `DEBUG` and `INFO` lines out of a deployment's log. A warning or an error is taken
  out by the deployment alone (decision 5).
- **With what it hides**, in a sentence a reader of the page can decide by.
- **In the slot.** Every package registers before the application is imported, and
  the rows are set once (decision 4). What arrives later is refused, unless it repeats
  a row as it stands: a module may be imported twice.

A declaration outside these, or one that cannot be read at all, is a warning and a
skip, as on the neighboring seams
([ADR-0048](0048-an-assembled-content-security-policy.md) decision 2), and a line on
the instance's startup node ([ADR-0076](0076-the-instance-node-is-a-branch.md)): a
mistake in a default never costs a deployment its monitoring.

Two packages may bring one dependency, and every cap holds. Where two rows reach one
logger, on its own name or one of them on a name above it, the higher level stands
there, whichever was declared first, and the page names both. A row hides nothing
above `INFO`, so what one package loses to another is a dependency's `INFO` lines at
most, and a deployment has them back by name. The same package declaring a logger
again in the slot replaces its row.

### 4. The library sets the rows once, where the application is imported

In the position `announce_doors()` and `announce_aspects()` hold
([ADR-0070](0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)):
every package has registered by then, and the code of the slot has set the levels it
sets. Setting a level writes nothing an instance keeps, so an import may do it
([ADR-0091](0091-an-import-is-not-an-instance.md) decision 1).

A row is set on its logger unless one of four things holds. They are asked in this
order, and the first that holds is the reason the page gives (decision 7).

1. **The application configured logging itself.** The root had handlers where the
   library's logger module was first imported, which the import of a check package
   does. It is the guard of ADR-0049 decision 4, and no level is the library's to set
   then.
2. **`LOG_LEVEL` names the logger, or one above it** (decision 5).
3. **A level stands on the logger, or on one above it short of the root, that no row
   set.** The code of the slot set it, or the dependency itself. The library cannot
   tell which, and a row overrules neither.
4. **The row would take no line away.** Without it the logger is at the row's level
   already or above it, through the root or through a row above. A cap takes lines
   away and adds none.

A logger above counts in the third because a level on a name speaks for the names
beneath it that carry none: a deployment that set `botocore` to `DEBUG` in the slot
asked for the credential lines as well. The rows are judged from the top of the names
down, so that the fourth sees the rows above.

Nothing is set where a row is declared, and so the order of a deployment's imports
decides nothing. What code sets after the application was imported, it sets, and no
row follows it: on a row's own logger that is the later word, and on a logger above a
row it does not reach the row, lower or higher.

### 5. `LOG_LEVEL` names loggers beside the level

`LOG_LEVEL` is a list, separated by commas. An entry with no `=` is the level of the
default's root, which is all the variable was. An entry `name=LEVEL` is the level of
that logger:

```
LOG_LEVEL=INFO,botocore.credentials=DEBUG
```

- **A named entry may name any logger and carry any level**, the library's own
  loggers and `ERROR` included. The log is the deployment's.
- **An entry speaks for its name and for every name beneath it, down to the next name
  the variable has an entry for.** No row is set there, and a level that stands on a
  logger there is taken off, whoever set it. Of the variable's entries, the nearest
  at or above a logger's name is then that logger's level.
- **A named entry is set twice, each time with that reach**: with the default, and
  again where the rows are set, after the code of the slot. Where that code and the
  variable name one logger, the variable stands from there on. Between the two the
  later `setLevel` stands, as it does anywhere. The bare level is set once, with the
  default.
- **A bare `DEBUG` lowers the root and lifts no cap.** The caps are what keeps such a
  session readable, and a capped logger is asked for by name. The root has no name in
  the variable: an entry for `root` is one that cannot be read.
- **A level is written by its name in `logging`, in either case**, and `NOTSET` names
  none. A logger's name is taken as it is written. Spaces around an entry and around
  its `=` are dropped, an empty entry is nothing, and what follows the first `=` is
  the level.
- **A later entry for a name replaces an earlier one**, the bare level too.
- **An entry that cannot be read is skipped and said**, in the log, a line for each,
  and the rest of the variable stands. With no bare level that can be read the root is
  at `INFO`, as before.
- **All of it belongs to the default.** Against an application that configured
  logging the variable does nothing, as before.

### 6. `.env` feeds both of the default's variables

`LOG_LEVEL` and `LOG_FILE` are read after `.env` has been read into the environment
([ADR-0003](0003-config-and-secrets-via-env-file.md)), whatever a process imports
first. A value in the process's own environment stands over the file's, as for every
variable.

### 7. The instance says what its log leaves out

*Installed* ([ADR-0100](0100-system-is-two-views.md) decision 3) gains a section,
*Logging*. It says whether the default is in charge, and the root's level with where
it comes from. Then every logger that carries a level of its own, with where the level
comes from: a row, with the package that declared it and what it hides; an entry of
`LOG_LEVEL`; or neither, which is the application's code or the dependency itself.
Then every row that was not set, with the reason (decision 4); every level an entry
took off, with the logger it stood on; and every entry of the variable that could not
be read. The package inventory names a package's caps beside its other registrations.

The log says it where it begins. Setting the rows writes an `INFO` line for each row
that was set, which names the entry of `LOG_LEVEL` that shows its lines: a log that
leaves lines out says which. The entry names the logger at the level it is at without
the row — `botocore.credentials=INFO` under the default's root — so that what the row
hid comes back and nothing below it. The page prints that entry as a line to copy,
after the variable as it was read, so that pasting it changes one thing. A row that
was not set leaves nothing out, and the page says why it was not. A deployment that
takes the library's own lines out with the variable has the page for the rows that
were set as well.

### 8. One name joins what a release promises

`architecture.md` §11's entry for logging promises one call beside the behavior,
`little_sister.noise.cap(logger, level, hides=…)`, and states the list `LOG_LEVEL`
takes. The call stands where the other registration seams stand: it is no part of the
block that the check API's epoch versions, so the epoch does not move
([ADR-0051](0051-what-startup-refuses.md) decision 2), and no check sees a difference.
`little_sister.logger` stays what it was, no module a plugin imports. Adding a name is
compatible (ADR-0049 decision 5). A package that declares a cap needs the release that
first carries the call, and its floor says so.

### 9. What is not decided here

A filter that says a line once and holds its repeats back: it hides by content, and
would need an override as a level does. A switch that changes a level while the
process runs. A way to hand the rows to an application that configured logging itself:
it reads them on the page and sets what it wants, and no deployment of the family
configures logging itself. And a call that sets the rows in a process that never
imports the application.

## Consequences

- **ADR-0049 decision 4 is amended.** The caps beside the default's level are rows
  with owners (decisions 1 to 4), `LOG_LEVEL` is a list (decision 5), and one name is
  promised beside the behavior (decision 8). What that decision says of an application
  that configured logging stands: the variable does nothing against it. Under the
  default an entry that names a logger stands over a level the deployment's code set
  on it or beneath it, which that decision had no cause to say.
- **A deployment that installs a package has that package's dependencies quiet at
  every run without knowing their names**, once the package declares them.
  `little-sister-aws` declares what its SDK writes in a release of its own. A
  deployment that capped the SDK in the slot keeps its levels (decision 4). Whether it
  still needs them is a comparison with the package's rows, and the page lays the two
  side by side.
- **The slot is written under no row.** A door that reaches its store while it
  registers ([ADR-0091](0091-an-import-is-not-an-instance.md) decision 8) has the
  SDK's line once at a start. What the variable names holds there from the first line,
  except on a logger the startup file itself sets before that door registers: there
  the file's level stands until the application is imported.
- **A process that never imports the application sets no row** and says the variable
  once. Where the default is in charge in it, a tool logs under the levels the default
  first set.
- **A login that fails on one machine is one variable and a restart**:
  `LOG_LEVEL=INFO,botocore.credentials=DEBUG`, in `.env` or in the environment, and
  the page says what stands. A dependency at `DEBUG` may write what a log should not
  hold: the AWS SDK's documentation warns that *the full wire trace* is in what
  `botocore` logs. That is a reason to name the narrowest logger that answers the
  question, which a bare `DEBUG` cannot.
- **A level set in the slot stands against every row, also for a logger the library
  caps.** One set on `markdown_it` before the library's first import was overwritten
  by the default, and no longer is. Only the variable stands over it.
- **No row adds a line where the rows are set.** Under a root at `WARNING` or above,
  `markdown_it` is no longer set to `INFO`. A level that code moves above a row later
  is not followed.
- **`httpx` is no longer capped** after an upgrade. A package or a deployment that
  brings it declares it, and the release notes carry the line.
- **A dependency that sets a level on its own logger reads as a choice.** The row is
  not set, the page says so, and `LOG_LEVEL` names the logger all the same. One that
  sets its level only when it is first used, after the application was imported, has
  the later word over both.
- **A `DEBUG` session is as readable as the packages make it**: each declares at
  `INFO` what its dependencies write below it, as the library does for `markdown_it`.

## Alternatives considered

- **As it was: each deployment caps what it reads in its log.** It keeps the library
  out of it, and each installation of a package learns again what the package knew.
  The argument for it was that how loud a log is belongs to the installation and not
  to a check type. It still does: a declared cap is a default, and every deployment
  overrides it by name.
- **The package sets the level where it is imported.** One line, in the package that
  knows. It is what ADR-0049 decision 4 keeps the library from, done by a dependency;
  the order of imports decides whether a deployment's own level survives it; and
  nothing shows that it happened.
- **The library's list grows.** It is where the two caps stand. The library would name
  what its packages depend on, and the cap on `httpx` shows how long such a row
  outlives its reason.
- **Setting a row where it is declared**, and letting whatever the deployment sets
  later win. It would cap the lines of the slot as well. But a level set before the
  import is then overruled and one set after it stands, and a level a deployment sets
  on `botocore` never reaches a row already standing on `botocore.credentials`: the
  order of two lines in a startup file would decide what a log holds.
- **Taking a row that arrives after the application was imported**, and judging it
  then. A package imported late would have its cap. But a late row above a lower one
  leaves that one bringing lines back unless every row is judged again with it, and
  judging again moves loggers the late row does not name, each time one arrives.
- **Of two rows that reach one logger, the lower standing.** It hides less. A
  package's cap would then stop holding the day another package is installed beside
  it, and a row beneath a higher one would bring lines back, which a cap never does.
- **Refusing at startup where two packages declare one logger**, as two claims on a
  secret scheme are refused (ADR-0064 decision 3). A scheme says where a credential is
  read from. A cap is a default about a log, and two packages that bring the same SDK
  could then not be installed together.
- **A named entry that stops at a level standing beneath it.** It is how `logging`
  reads a level, and it overrules less. An operator who writes `botocore=DEBUG` for a
  login that fails would then get everything the SDK writes but the credential lines,
  wherever the slot or a dependency holds a level on that logger.
- **The override in `config/settings.yaml`.** A file the deployment already authors,
  and a level there could be validated like any setting. A debugging session would
  then be an edit to a file the deployment tracks, and the default's level would be
  said in two places. And the variable is there where the default is installed,
  before the first line, while a settings file is read later: what a door writes while
  it registers, the lines of a login that fails at a start, would be written before
  the override is known.
- **A second variable for the names**, or a variable for each logger. Two places that
  say one table, or dotted names spelled into the names of variables. A list in the
  variable that exists keeps `LOG_LEVEL=DEBUG` meaning what it meant.
- **A bare `DEBUG` lifts every cap.** Nothing is then hidden from somebody who asked
  for everything. It brings back the log that was two thirds SDK request detail, in
  which the lines of the code under study are not found, and what a package capped
  returns without anybody having named it.
- **A logging configuration file**, handed to `dictConfig`. Everything can be said in
  one. An application that wants that much configures logging itself, before it
  imports anything of the library, as it always could; the default would grow a second
  language for a few rows.
- **A filter that says a line once.** The first line that says where the credentials
  were found is worth reading and the rest are not, and a level cannot tell them
  apart. A filter hides by content, so a log then differs from what was written with
  nothing to say where, and it needs an override as well. Decision 9 leaves it open.
