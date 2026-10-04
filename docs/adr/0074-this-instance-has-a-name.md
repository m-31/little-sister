# ADR-0074 — This instance has a name, and the library owns it

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-09-05)
- **Related:** [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) §5
  (the keeper seam, whose first implementation had to invent one of these),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the self-report seam, where a
  package says what it knows about this process), [ADR-0035](0035-registering-a-config-aspect.md)
  (`settings` is the library's own aspect), `little-sister-aws` ADR-0004 (the S3
  keeper, and the mark it invented), [ADR-0095](0095-the-instance-states-its-memory.md)
  (decision 2, where the runtime figures stand)

## Context

Until this record there was **no notion of an instance** in this library. Nothing
named the running process; `/system` reported what was installed — check types,
packages, extensions, login doors, the assembled policy — and never said *which
installation this is*. That was consistent while an installation was a directory on a
machine somebody had ssh'd into: the answer was the shell prompt.

State leaving the machine ended it. The keeper seam of ADR-0071 hands `var/state/` to
a store somewhere else, and the first store written against it —
`little-sister-aws`'s S3 keeper — has to answer *did I write this?* about an object in
a bucket that another instance may also be writing. It had no library answer to that
question, so it invented one: `host:pid:started:random`, chosen for reasons that are
not specific to S3 at all. That mark now goes into somebody's bucket and onto a status
line, and the second keeper anybody writes would have invented a second one, differing
in exactly the ways two independent inventions differ.

The question is therefore not *should the library have an instance identity* — one
already exists, in the wrong place — but what it is and where a human reads it.

## Decision

1. **`little_sister.instance`, resolved once — on first use, not at import.** A
   frozen `Instance` with `name`, `pid`, `started` and `tag`, behind a memoising
   `this_instance()`. Once, because a mark that changed mid-process would break the
   only thing it is for.

   *On first use* rather than at import is load-bearing and was learned by getting it
   wrong: the name comes from the settings, reading the settings needs a
   configuration root, and a module constant would therefore make **importing** this
   module require that root to exist. `little-sister-aws` imports it in its own
   module body, so a plugin's import would have started failing wherever no root is
   configured yet — which includes its own test collection. So the configuration is
   reached inside `resolve()` and nowhere else, and a test asserts that no top-level
   import of this module names `little_sister.config`.

2. **The mark is `<name>:<pid>:<started>:<tag>`.** `pid` and `started` are for the
   human — together they are what turns a mark on a page into a process somebody can
   find. `started` is UTC in the **basic** ISO form, because the separator is a colon
   and the extended form carries three of its own.

3. **`tag` is eight random hex characters, and it is not decoration.** It is what
   makes an *equality test* on the mark sound. Two containers of one deployment share
   a configured name, run as pid 1, and start in the same second — so without it two
   live processes could hold one mark, and a reader comparing marks would take a
   second writer for itself. That failure is **silent**, which is the reason it is not
   left to the deployment to avoid.

4. **A deployment may name the instance, in `config/settings.yaml`.** `instance:`,
   defaulting to the hostname — which in a container is already the task or pod name,
   so the default is usually the name somebody would have chosen. `web-frontend` reads
   better than `ip-10-0-3-14` in a fleet of identical hosts, and the reason to withhold
   the knob is answered by decision 3: the library appends uniqueness the deployment
   cannot take away. `little-sister-aws` refused the same knob for want of that
   guarantee, and could not give it, because a plugin cannot promise anything about a
   name another plugin also reads.

   A bad name **falls back to the hostname with a warning** rather than refusing the
   start — the bargain every other setting in that file makes. Nothing about the name
   is load-bearing once the tag carries the uniqueness, and refusing to start over a
   cosmetic label would make having a mark more dangerous than not having one. What is
   refused: the separator, whitespace, and anything over 64 characters. The first two
   would make one mark read as several.

5. **The mark is never parsed.** It is compared for equality and printed. Nothing here
   promises the parts stay in this order, or stay four. What *is* promised is the pair
   that matters: two processes never share a mark, and one process's mark never
   changes while it runs.

6. **`/system` says which instance this is, in a section of its own, first.** Every
   other card on that page describes something about an instance, and until this one
   the page never said which. It sits **outside** the polled fragment on that block's
   own rule — settled at import, unchanged while the process runs.

   Two fields, not four: the **name**, which is the only part a deployment chooses,
   and the **mark**, because that is the string that ends up in somebody else's bucket
   and the reason to come to this page is to find out whether it is this instance's.
   The pid and the start are inside the mark, and the engine block below already shows
   the start again in local time — a card repeating either would say one fact three
   times.

## Consequences

- `little-sister-aws` deletes its own `_this_instance()` and takes the library's. The
  shape it had is the shape adopted here, so nothing it wrote into a bucket becomes
  unreadable — but a name is now a **deployment's** choice where it was a hostname,
  which is a change an operator will see on a status line.
- **The mark is on the promised surface** (`architecture.md` §11) from this release.
  A plugin writes it into storage that outlives the process, so changing what it is
  made of is a version and not an edit, and dropping the two promises in decision 5
  would be a break with no error message anywhere.
- **`/system` grows a section, and the argument about what else belongs in it starts
  here.** What this process is *doing* — the entry count, the memory share, the pool
  wait, the lag — is not in that section at all; those are the engine's own lines on
  `/little-sister` (ADR-0072). The division has been *what is installed* against *how
  it is running*, and an instance's name is neither. It is put on `/system` because
  that is where somebody goes to ask what this installation is, and whether the
  runtime figures move beside it is answered by
  [ADR-0095](0095-the-instance-states-its-memory.md) decision 2: they stand in
  `/system`'s polled engine block, and *This instance* keeps what is settled at import.
- A deployment that names two instances the same gets two distinguishable marks and
  two identical names on two dashboards. That is a legible mistake rather than a
  silent one, which is the whole point of decision 3.

## Alternatives considered

- **Leaving it in the plugin.** Rejected: the second keeper reinvents it, differently,
  and the two marks then mean the same thing in two shapes — in the same bucket, if a
  deployment ever runs both.
- **A name with no suffix, wholly the deployment's.** Rejected, and it is the sharpest
  version of the trade: it reads best and it silently breaks the equality test the
  mark exists for. A reader cannot tell a duplicated name from itself.
- **No name at all, derived only.** That is what the plugin does today, and it is
  defensible — but a fleet of identically-provisioned hosts is exactly where an
  instance identity earns its place, and it is exactly where the hostname says least.
- **Refusing to start on a bad `instance:`.** Rejected by decision 4's reasoning: the
  cost of a wrong label is a page that reads badly, and the cost of a refusal is an
  instance that does not run.
- **Putting the mark on `/little-sister` as well.** Rejected for now: the heartbeat
  carries conditions, the mark is a fact, and a package that needs it beside its own
  lines can say it there — `little-sister-aws` does. Revisit if a second package wants
  the same line.
