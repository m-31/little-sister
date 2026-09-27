# Little Sister — Implementing a check type

How to implement a **new check _type_** — a Python class the engine can schedule.
This is the developer-side companion to [`checks/README.md`](../config/checks/README.md),
which covers the other half: how to _author_ a check (write the YAML for a type
that already exists).

Everything here applies to all three places a type can live: the **built-in** types
in this repo, the types a **deployment** adds through the public `CHECK_TYPES` seam
([`architecture.md`](architecture.md) §11), and the types an **installed package**
adds through the same seam. The class is identical in all three; only §4
(registration timing) differs, and §9 says which of the three a type belongs in.

A type that outgrows the deployment it was written in gets a repository of its own 
and arrives as an ordinary dependency —
`little-sister-github`, `little-sister-wiz` and `little-sister-aws` all did (and
`little-sister-jira` made the same move as a surface extension, with no check type of
its own), and that was the evolution of this seam it was always described as, not a
rewrite.

> Grounded in `src/little_sister/checks/` (`base.py`, `loader.py`, the built-in
> types), `transport.py`, `fetch.py` and `app.py`. If a name here drifts from the
> source, the source wins — update this doc.

---

## 1. The mental model

little-sister is **checks → engine → shared status tree → web + JSON API**. A *check*
is a small class that measures one thing and returns a value; the *engine* schedules
it at its `frequency`, and writes the result into the one shared status tree that the
web and JSON surfaces read. A check never touches identity, timestamps, maintenance or
event history — those belong to the tree
([ADR-0007](adr/0007-check-result-branches.md)).

This guide used to say a check is a *pure function of the world → a result*. That was
always **two** functions wearing one coat, and they are written separately now
([ADR-0086](adr/0086-a-check-measures-and-grades.md)): a **measurement**, world → a
record, and a **grading**, record → a result. Splitting them is what lets a verdict be
reached again later over a record this process did not take — which is what a history
of a subject is for — and the code had the shape already: a metrics check reads one
script and only then builds five children out of it.

One question shapes almost everything else, and it is worth answering before you write
a line: **is the thing you talk to the subject of your measurement, or the instrument
you measure something else with?** An `http` check's URL is its subject — failing to
answer *is* the reading. A check that reads an API to grade forty repositories has an
instrument, and grading those repositories for the API's bad minute is the bug the
transport vocabulary exists to prevent ([ADR-0058](adr/0058-transport-policy-vocabulary.md)).
§7 says what each answer costs you.

Two things that sound alike but aren't:

- **Authoring** a check — writing a `checks/*.yaml` that configures an existing type.
  That's [`checks/README.md`](../config/checks/README.md).
- **Implementing** a check type — writing the Python class behind a `type:`. That's
  this document.

---

## 2. The `Check` contract

The names a check may import are the **check-authoring surface** of the version
contract ([`architecture.md`](architecture.md) §11). Most of them live in the package
`little_sister.checks`, and the surface also promises `little_sister.status`
(`StatusCode`, `join_path`), `reasons`, `values`, `spans`, `transport` and `fetch` —
seven modules, listed in §11, and all but `spans` also pinned by an append-only
snapshot (§4). Nothing outside that block is part of the **check-authoring** surface —
though the contract is wider than this document: §11 also promises `CHECK_TYPES`,
`little_sister.app:app`, `little_sister.secrets`, the slot and CSP seams and the
`LITTLE_SISTER_*` variables (§4).

A check type is a subclass of `Check` decorated with `@register("<type>")`:

```python
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from little_sister.checks import (
    Check, CheckError, CheckResult, Measurement, config_markdown, plain,
    register,
)
from little_sister.status import StatusCode


@register("example")            # the YAML `type:` name; also sets cls.type_name
class ExampleCheck(Check):
    """One-line description of what this check measures."""

    def __init__(self, *, url: str, **kwargs: Any) -> None:
        # `subject` is the OBJECT you read, out of your own configuration — the
        # thing in the world, not the node's path and not the command you read
        # it with (§2's `subject`/`record` paragraph).
        super().__init__(subject=url, **kwargs)   # common fields (path, …)
        self.url = url                       # your own parsed fields

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        """Parse type-specific YAML into constructor kwargs. Raise CheckError
        on anything invalid — the loader prefixes it with the file name."""
        url = config.get("url")
        if not url:
            raise CheckError("example check requires a 'url'")
        return {"url": str(url)}

    def config_summary(self) -> str:
        """Optional: a curated, secret-free view of the params, shown on the
        node's detail page (ADR-0013)."""
        return config_markdown({"url": self.url})

    def measure(self) -> Measurement:
        """Read the world. No codes, no sentences — just what you read."""
        ...

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """Say what it means. A non-OK result MUST carry a reason."""
        ...
```

What the base class gives you and expects:

- **`measure(self) -> Measurement | Sequence[Measurement]`** — the half that touches
  the world, and **the engine does not bound it.** Python cannot kill a thread, so a
  hung `measure()` occupies a pool worker until it returns; `self.timeout_seconds` is
  a budget **you** enforce (§7). It hands back one `Measurement` per object the run
  read — one of them, or a sequence where you read several. One record is the common
  case and deliberately **not** the signature: you say which you have by what you hand
  back, and nothing downstream branches on shape.
- **`grade(self, measurements, now) -> CheckResult`** — the half that decides. It gets
  what you measured, normalized to a sequence, and returns the same tree a check has
  always returned. A non-OK result must carry a reason.

  **It must be pure over `(record, configuration, now)`**, and this is the rule the
  whole split exists for. Read the records, read the fields your type parsed at
  construction, read the `now` you are given — and nothing else: not an attribute
  `measure()` left on `self`, not the clock, not the world again. A later phase grades
  **old** records out of a subject's history, when the process that took them is long
  gone; a grading that leaned on anything else would not fail there, it would answer
  something quietly wrong.

  Two things follow that catch people out. **What the line says has to be in the
  record**, because the grading may read nothing else — so a check whose sentence *is*
  its captured output puts that output in the record (clipped; see below). And
  **mapping records to places is yours**: a record whose object has a node becomes
  that node's reading, one whose object has none becomes a line, and only you can say
  which, because a line is an `Entry` and no engine could place one for you.
- **Construction from YAML** — `Check.from_config(config, base_dir)` merges the common
  fields (`_parse_common`) with your `_extra_from_config(...)` and calls the
  constructor. You override only `_extra_from_config`; you never parse `path` /
  `frequency` / `timeout` yourself.
- **Common fields** (parsed for you, all keyword-only on `__init__`): `path`
  (**required**, absolute and slash-separated, e.g. `/hosts/example.org`,
  [ADR-0016](adr/0016-node-addressing.md)), `description`, `about`, `title`,
  `order` ([ADR-0055](adr/0055-sibling-order.md)), `frequency_seconds`,
  `timeout_seconds`, and `retry_interval_seconds` / `retry_attempts`
  ([ADR-0033](adr/0033-budgeted-failure-retry.md) — `None` inherits the deployment
  default, `0` switches the fast retry off for this check), `escalate_after`
  ([ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md) — consecutive readings
  of a worse code before the level above counts it; `None` inherits the deployment
  default, `1` publishes at once, `0` is refused), `depends_on`
  ([ADR-0084](adr/0084-a-check-may-be-reached-through-another.md) — the **path** of
  one other check this one is reached *through*; while that check reports `ERROR`
  this node keeps its own reading and contributes nothing upward. An unknown target
  and any cycle are refused at load, and a `tag:` value is refused by name rather
  than read as a path) and `series_keep`
  ([ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md) — how many readings of
  each subject the check keeps as its series, the oldest out; `0`, the default, is no
  series, and there is no deployment default to inherit, because where a history is
  wanted is the deployment's choice per check — so a type passes it on and never sets
  it), and beside it `measures` and `reading_cap`
  ([ADR-0092](adr/0092-a-check-declares-its-measures.md) — which fields of the record the
  series is drawn by, merged over your type's `measure_defaults` as *Declare what your
  record's numbers are* below says, and how many readings the node shows, `None`
  leaving `settings.yaml`'s in force; a type passes both on). Durations accept `30s` /
  `15m` / `2h` / `1d` / `1w` or a bare number, the units lowercase. **`name:` in YAML
  is rejected** — it was merged into `path` (ADR-0016).
- **Take `**kwargs` and forward them**, as the sketch above does — do not spell the
  common fields out in your own `__init__`. That list **grows**: `order` joined it in
  one minor release and the two retry fields in another, and a constructor naming the
  fields one by one stops binding the day the next one lands, even though every name
  it imports still resolves ([ADR-0049](adr/0049-the-check-authoring-surface.md)
  decision 6). If yours does refuse a keyword, the loader says so with the file, the
  type and every refused keyword named, rather than raising a bare `TypeError` from
  inside itself.
- **`subject` on the check, `record` on the measurement** — **the object you read, and
  what you read about it** ([ADR-0085](adr/0085-a-measure-is-read-out-of-a-record.md),
  [ADR-0086](adr/0086-a-check-measures-and-grades.md)). A run reads one object and
  produces one record; the node, the children and the lines you write are *derived*
  from that reading. `CheckResult` carries neither — one field, one writer, nothing to
  forget.

  **Declare your object in the constructor**, out of your own configuration:
  `super().__init__(subject=url, **kwargs)`. It is the identifier **you reached** —
  `web01.example`, `http://web01.example`, an account id — and deliberately not the
  node's path: the path is the deployment's label for where your node hangs and may be
  renamed or moved, while the history is about the thing in the world. At construction
  rather than per run, for two reasons: a subject that moved between runs would
  silently split one history in two, and the engine needs a name for your object on the
  run where your check **raises** and there is no measurement at all.

  Ask which of the two things you are holding, because it is the same question §1 asks
  about subjects and instruments: **the object is what you measure, the command is how
  you measure it**. An `http` check's object is its URL, not `GET`; an `ssh-command`'s
  is the host, not the command it runs there. Where your object is knowable only from
  an **answer** — a rate-limit check asking the API whose token it holds, because the
  rate-limit endpoint never says — leave the constructor's `subject` empty and put it
  on the `Measurement` instead. Make it as fine as what has a history: that check names
  one account's budget *per resource*, since each resource has its own limit and reset.
  And when your run hands back **several** measurements, the constructor's subject
  names none of them — a measurement without a subject of its own has no series, which
  is right for a reading nobody needs the history of.

  **Where your object has no node at all** — a repository, a job run, a finding — it is
  a line, and the line carries its own: `Entry(slug, text, subject=…, data=…)`.

  A `record` is validated at the seam like a line's: JSON-serializable, bounded by
  `record_limit`, and `at` / `started` / `ended` at any depth must be times with an
  offset — and one it refuses costs what a line's does (below): a raise in your
  tests, and in a run that reading and never the run, the engine saying on your node
  which subject's record it was and why. It is **data and never a claim** — anything
  that should alarm is a reason.
  It is also **not your working state**: the raw answer — a 150-finding page, an
  unshortened log — stays inside your check, and what crosses into the record is what
  is worth keeping, because 2 KB is the default bound on one of them.
  A run that **failed** to read its object should still record the attempt — the reason
  beside the values it could not get, as nulls — because a history of failures answers
  *how often did this answer at all*, and a history with holes in it cannot: a hole
  looks the same as a restart or a poll that never happened. Keep **one shape**: a value
  you could not read is `None`, never a missing key, so a curve draws a real gap instead
  of inferring one. A *reason* is the exception and rides along only where there was
  one. A run that records nothing at all — an empty sequence from `measure()` — clears
  what the last run recorded, since the node's observation time moves with every run and
  a kept reading would be wrongly dated, not merely old.

  **Free text in a record is clipped once, and in bytes.** A record is weighed as
  `json.dumps` writes it, which escapes to ASCII: 1000 characters cost 1014 bytes in
  ASCII, 2014 in newlines, 6014 in umlauts and 12014 in emoji, which JSON writes as
  surrogate pairs. So `clip(text, chars=…, budget=…, keep=…)` bounds both at once, off
  the same end, and you use the **one** result as your record value *and* in your
  sentence — clip twice, to two lengths, and the sentence can no longer be written from
  the reading stored beside it. Doing it this way is what lets `expected_record()` below
  be a ceiling that cannot be exceeded, so a configuration that will not fit is refused
  at startup by name instead of at the seam on every run.

  **Two rules give a reading a history: the subject gives it one, and the identity
  keeps each event in it once — or the state each spell**
  ([ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md)). Where a deployment
  sets `series_keep` on your check, the engine keeps that many readings of each subject
  as its *series*, the oldest out, keyed by your check — its type and its mount — and
  the subject. So a reading has a history only where it names an object: the one you
  declared in the constructor, for a run that hands back a single measurement, or its
  own `subject` among several. A reading with none is your grading's input and nothing
  more, and a slug, declared or derived, plays no part in it. Whether a reading is a
  new record in its series is `Measurement(…, identity=…)`: leave it empty where every
  reading really is a new one — a response time, a load average — and name the event
  where the source keeps the history — the run you read, a job's id — so that the same
  finished run, read again on the next poll, replaces its record wherever it stands in
  the kept window instead of becoming a second point. Where your object's source keeps
  no event for it at all — a thing that is switched off, a state that simply stands —
  name as its identity what that source calls *last changed*, where it has such a field
  and the field moves whenever the state does. Where that field is a time, the identity
  is the instant as your record keeps it and never the source's text: put the time under
  a timed name (`at`, `started` or `ended`, at any depth), build the measurement, and
  hand back one naming as its identity the time that `record` holds — one instant
  written with another offset would otherwise be another event. Where there is no such
  field, pass `Measurement(…, state=…)`, the **state itself**, spelled from the few
  fields that constitute it and never from the whole record. A state is compared with
  the newest record of its series alone — the same state replaces it, a different one
  appends — so a return to an earlier state is a new record, where an identity would
  have found the old one and rewritten it in place.
  A measurement names an identity or a state, never both, and a reading of a frozen
  state with neither writes the same record into its series on every poll. A series
  orders by a record's own
  time, its top-level `at`, where it has one — so a run's record puts when it finished
  there — and otherwise by when it was first read, readings of one run in the order you
  handed them back. A kept reading also keeps what **stood** where it landed, because
  the thresholds that graded it may have changed by the time its window is read. The
  one reading the engine places keeps your node's code and its texts; where your root
  grades nothing, as a branch check's `UNDEFINED` container does whether or not it
  also says what it watches, it keeps what your result rolls up to — your children's
  codes, never another check's on the same node — beside whatever that root says. One
  of several keeps the code and the text of the line your grading
  carried it onto, and that line is found by the record it carries as its `data` and
  the subject it names — so hand the measurement's record over unchanged and give the
  line the reading's subject, or the reading is kept with neither. The exception is a
  reading among several that names the object you declared: where no line carries
  it, it stood on your node, and it keeps what the one placed reading would.
- **`config_summary(self) -> str`** *(optional)* — Markdown display metadata for the
  detail page ([ADR-0013](adr/0013-check-config-on-node.md)). Build it with
  `config_markdown({"label": value, ...})`; **never** put a secret in here. Default
  is empty.
- **`resolve_secret(self, reference)`** — resolve a credential **in the
  constructor** and keep the value; see §6
  ([ADR-0023](adr/0023-secret-references.md)).
- **`owned_nodes(self) -> set[str]`** *(optional)* — override only when your check
  **shares** its container node with a peer: return your child subtrees, built with
  `join_path(self.path, name)` so the container stays unowned and the peers coexist
  ([ADR-0015](adr/0015-check-discovery-union.md)). A branch check that owns its
  container outright — most of them — keeps the default `{self.path}`. Build the paths
  with `join_path` rather than by hand, or every plugin re-derives ADR-0016's
  normalization by guesswork.

- **`expected_cost(self) -> float | None`**,
  **`expected_entries(self) -> int | None`** and
  **`expected_record(self) -> int | None`** *(optional)* — what one run of *this*
  configuration is expected to occupy in worker seconds, how many reason entries it
  expects to hold, and how many bytes one of its records is expected to need
  ([ADR-0075](adr/0075-a-check-declares-what-it-costs.md)). Compute them from your own
  parsed fields, in the constructor's arithmetic rather than from a measurement: fifty
  repositories at two requests each is a different answer from one, and only your type
  knows which it has. Startup **sums** the first two over every declaring check — each
  cost over its own `frequency_seconds` against the deployment's `max_workers`, the
  entries against its `entry_limit` — and **compares the third per check** against
  `record_limit`, which bounds one record rather than a ceiling every check shares —
  raised, where you declared less, to the most the failure record the engine writes
  for a check that raised can weigh, which therefore sets a floor under any record
  size you declare ([ADR-0086](adr/0086-a-check-measures-and-grades.md) decision 5). It
  **refuses** a configuration whose declared part alone cannot fit, naming the checks;
  at 80 % of a limit it is a warning in the log and a fact in the `report` of
  `/little-sister/engine`.

  Declare an **estimate of a normal run**, never a bound: `timeout_seconds` is the
  bound, and a type that declares it refuses deployments that work. Declare nothing —
  the default — when the honest answer is *small and roughly constant*; the mechanism
  is for types that read an estate. A declaration that raises or answers something
  that is not a non-negative number is logged against your check's path and treated as
  absent, so a broken estimate never stops a deployment starting. What you declare
  shows on `/system` beside what was measured — the wall time of the last run, and the
  largest record it carried — which is where an estimate that has drifted becomes
  visible.

Raise **`CheckError`** for any bad configuration; the loader names the offending file.

---

## 3. `CheckResult`: a leaf or a whole tree

`CheckResult` is a frozen dataclass:

```python
CheckResult(
    code:        StatusCode | None = None, # declare one, OR code your entries — never both
    reason:      ReasonInput = [],         # five accepted shapes, below; rendered as Markdown
    name:        str = "",                 # a child's id under its parent; ignored on the root
    description: str = "",                 # child-only; the root's comes from the check's YAML
    children:    tuple[CheckResult, ...] = (),
    config:      str = "",                 # per-child config markdown (branch checks)
    report:      str = "",                 # what this run FOUND, markdown; root and children (ADR-0044)
    about:       str = "",                 # subnode subject label; child-only, fills empty (ADR-0025)
    title:       str = "",                 # subnode short label; child-only, fills empty (ADR-0025)
    order:       int = 0,                  # sibling rank; root AND children, fills unset (ADR-0055)
    entries:     bool = False,             # declare plain strings to be members (ADR-0036)
)
```

`reason` takes five shapes: a `str`, a `Sequence[str]`, a `Mapping[str, str]` of
slug → text, a sequence of `(slug, text)` pairs, or a sequence of `Entry`. The last
mapping and the pairs list declare **members** — individually addressable,
individually pinnable lines ([ADR-0036](adr/0036-addressable-reasons.md)); a sequence
of `Entry` does so by shape, when an entry carries a `code` or `running`. Otherwise
`entries=True` declares them, which is how a plain string sequence becomes members and
one of the two ways to hand over an *entry-bearing empty set* — an empty mapping is the
other. A non-OK result carrying no reason is not refused by the
constructor, but it is wrong: say why.

- **Leaf** — the common case: `CheckResult(StatusCode.OK)` or
  `CheckResult(StatusCode.ERROR, ["what went wrong"])`.
- **Branch (a dynamic subtree)** — return a root whose `children` are named
  `CheckResult`s; each child may itself have children. The engine upserts the root at
  `check.path` and each child beneath it
  ([ADR-0007](adr/0007-check-result-branches.md)). **Every child must set `name`**
  (enforced in `__post_init__`). This is exactly how one check can own a
  discovered-at-runtime tree — e.g. a repository check → one child per **aspect**
  (pull requests, security findings, …), each listing the repositories it flags. A
  check shaped this way should let a deployment switch an aspect off; that is §10.
- **Roll-up** — a container's displayed status is the **worst-of** its subtree; the
  tree computes that on read. What a branch root carries follows §2's question: a
  check that **shares** its container returns `UNDEFINED` there and owns only its
  child subtrees, so the container belongs to nobody and simply rolls up (ADR-0015 —
  all three built-in metrics checks do this); a check that **owns** its container
  grades it, and child problems still surface through the roll-up.
- **When discovery itself fails**, the answer depends on who failed
  ([ADR-0060](adr/0060-a-line-makes-no-claim.md) decision 3). A failure the service
  **answered** — an owner or team that is not there, a credential that may not look —
  is a defect somebody must fix, and stays
  `CheckResult(StatusCode.ERROR, ["discovery failed: …"])`.
  A **transient** failure — a 5xx, a dropped connection, a throttle — is *we could not
  ask*, and grading the whole tree for it is the thing that rule exists to stop:
  return `WARN` naming the coverage gap. Either way return **no children**, and note
  what that does and does not do: omitted children are **not pruned** (ADR-0007), so
  the subtree keeps the last good run's readings and their timestamps, and freshness
  ([ADR-0005](adr/0005-dashboard-freshness-and-self-monitoring.md)) is left to say
  honestly that they are old. In the `ERROR` case the root's own code dominates the
  roll-up anyway; in the `WARN` case the last reading is the best knowledge anyone
  has, which is the point.
- **Status codes** — a check declares `StatusCode.OK`, `WARN`, or `ERROR` on a node.
  `MAINTENANCE` is the tree's alone. An **entry** may additionally carry `UNDEFINED`,
  and since [ADR-0060](adr/0060-a-line-makes-no-claim.md) that means one specific
  thing: *this line makes no claim about its subject* — a claim you withheld, almost
  always because you could not ask. (*Never reported yet* is the **node**-level
  meaning of the same code, and not yours to write.) `coerce_code(...)` turns a config
  string (e.g. `stale_code: WARN`) into a `StatusCode`.
- **If you withhold claims, grade the node you own.** `UNDEFINED` lines are skipped by
  the derivation, so a node whose lines are *all* withheld derives `UNDEFINED` — and
  an `UNDEFINED` own code is skipped again in favor of children, which is how an
  aspect that read nothing at all comes to render green. So a check that could not
  look owes its own node a **`WARN`** saying so (ADR-0060 decisions 1–2). Where your
  other lines carry codes you cannot declare a node code beside them, so say it
  **through a line of its own**; count only the *could-not-ask* kind, and name
  coverage rather than any one subject.
- **Coded entries** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) — where
  one node's lines have verdicts of their own (this workflow failed, that one
  passed), hand over `Entry` values and **omit `code`**; the node's stored code is
  then derived: worst-of the entries' own codes, an entry declaring none contributing
  nothing, `UNDEFINED` skipped — with two stated defaults at the ends, an **empty**
  entry-bearing set reading `OK` ("nothing to report" is not "nothing reported") and
  an **all-`UNDEFINED`** set reading `UNDEFINED`, which is the case the bullet above
  is about:

  ```python
  from little_sister.checks import Entry

  return CheckResult(reason=[
      Entry("web-build", "web (main) / build: failed after 8m14s · #4216 running 2m",
            StatusCode.ERROR, running=True),
      Entry("api-tests", "api (main) / tests: passed in 2m01s", StatusCode.OK),
  ])
  ```

  Declaring **both** a result code and entry codes is refused at construction — a
  silently ignored code would be believed. `running` marks a line whose subject
  has work in flight; it is display (an italic and a class), never severity, so
  the line's **text must still say it** in words. An entry carrying a code or
  `running` declares members by shape, like a mapping. Three author rules come
  with the power: **order the list non-OK first, then in-flight, then healthy**
  (`reason_cap` clamps the card, and healthy lines above the fold would bury the
  failures); **seen and counted ⇒ `WARN`, available but not counted ⇒ `OK` with a
  reason** (a permanent informational `WARN` holds the root amber — a legitimate
  choice, but a choice); and **split the node when the *group* is what an operator
  acts on, code the line when the *finding* is** — a severity band is a real node
  with a pin that silences the whole band, while a coded line keeps its pin when
  its state moves. Emitting healthy lines is a per-aspect choice, off by default;
  a run in flight should always produce a line.
- **A slug is an identifier, never a position** ([ADR-0050](adr/0050-slugs-from-provider-identifiers.md)).
  Build a member's key with `slug(*parts)` from what the provider minted — the issue
  number, the alert id, the workflow and branch — and never from the rendered text or
  the line's index, because a pin holds that key and a re-ordered list would move it.
  `derived_slug(text)` is the fallback where you have nothing better than your own
  wording. Name the **subject first** by convention (`slug(repository, "pr", 42)`);
  see `architecture.md` §4.3 for what a subject is and why it is not a child.
- **A line may carry what it is about, and what you read**
  ([ADR-0082](adr/0082-a-line-carries-what-it-is-about-and-what-it-read.md)). Two
  more optional attributes on `Entry`, both invisible until something renders them:

  ```python
  Entry(slug(repo.id, "workflow", workflow_id, branch),
        f"{plain(repo.name)} ({plain(branch)}) / {plain(workflow)}: failed (#41)",
        StatusCode.ERROR,
        subject=str(repo.id),                       # what this line is ABOUT
        data={"repository": repo.full_name,         # what you READ about it
              "workflow": workflow, "branch": branch,
              "run_number": 41,
              "completed": {"at": "2026-09-19T09:12:00Z"}})
  ```

  `subject` is the **source's own identifier** — the one a rename cannot change, the
  same value the slug's first part is built from — because a view that groups
  ("everything about this repository") cannot recover it from the slug. Put what a
  human reads in the record, not here. Nothing is ever pinned by subject.

  `data` is the **record**: the material you would otherwise throw away once the
  sentence is written. Keep what a reader, a template or a curve would want — not the
  API response. Three names are typed and read at **any depth** — `at`, `started`,
  `ended` — and each must be an ISO-8601 string **with an offset** (or null), which
  the seam converts to UTC and the node's page shows in the deployment's configured
  timezone. Everything else is yours and renders as a name and the value as you
  stored it — a time under any other name included, so put a time you want read as
  one under a timed name, nested where it belongs (`created.at`). The page shows no
  age beside a time: where your grading reads one, your sentence says it. Neither
  attribute declares members, so prose carrying a record stays prose.

  The seam refuses a record that is not a JSON mapping, carries a non-time under a
  timed name, or weighs more than `record_limit` bytes of JSON (2 KB by default), and
  what a refusal costs depends on where the record is built
  ([ADR-0093](adr/0093-a-record-the-seam-refuses-costs-its-line.md)). **In your
  tests, and anywhere else a result or a measurement is built, it raises** a
  `CheckError` naming the field or the bytes, so you meet it where you built the
  record. **In a run the engine drives it costs that line or that reading, never the
  run**: a line keeps your text and code, its `data` null and `refused` saying why; a
  reading is kept out of your grading, and the engine says on your node which
  subject's record was refused and why; the instance says both on
  `/little-sister/runtime`. Build your readings on the run's own thread: the run is
  lenient through a context variable, and a thread you start yourself begins with a
  context of its own, where a refused record still costs the whole run. Aim at the
  default rather than at a deployment's setting: your package cannot see which one it
  is installed into. Values are escaped when they are rendered, so a record field needs
  no `plain()`.
- **Reasons are Markdown** — fold untrusted text in safely: `plain(text)` escapes an
  inline value (a path, an error, an API message); `code(text)` fences multi-line /
  log output as a verbatim block ([ADR-0018](adr/0018-markdown-rendering.md)). Never
  interpolate raw external bytes straight into a reason.
- **A time in a sentence reads the way the page reads it.** Write an instant with
  `little_sister.spans.local_time`, which uses the deployment's configured `timezone`
  and `time_format` ([ADR-0006](adr/0006-config-file-and-timezones.md)) — never a zone
  of your own, and never the UTC your source handed you — and a span with
  `format_span`, `coarse_span` or `format_duration`, whichever reading it is (their
  docstrings say which). A sentence that says *the lease lapsed at …* in `GMT`, beside a
  page whose every other time is in the configured zone, reads as a different moment.
- **Declare what your record's numbers are: `measure_defaults`**
  ([ADR-0092](adr/0092-a-check-declares-its-measures.md)). Where a deployment keeps
  your check's series, the node that stands for its subject draws a curve for each of
  the check's **measures** — fields of your record, by the dotted name its record list
  spells them with, each in a unit. What a field means and in which unit is your
  type's knowledge, so declare it once in the constructor, shaped like the YAML block:
  `super().__init__(subject=url, measure_defaults={"response_ms": {"unit": "ms",
  "label": "Response time"}}, **kwargs)`, or `{"field": "unit"}` where the field's name
  is label enough. Whether it is drawn is the deployment's: its `measures:` block is
  read by the library and merged over yours **per field** — naming a field takes it
  whole, `null` removes one, and every field it does not name keeps your default — so
  do not read `measures:` yourself. A unit is free text and is never refused; `ms` and
  `s` are written as spans (`1.9 s`), so prefer them for a time. Keep the record's
  shape the same on every path, with a null where a reading failed: a null is drawn as
  a marked break, and a field that is simply missing reads as one too — never as a
  zero. A declaration of another shape refuses the load like any configuration
  error.
- **`report` — what the run found** ([ADR-0044](adr/0044-run-facts-on-the-node.md)) —
  the outputs field beside `config`'s inputs: the repositories in scope, the volumes
  enumerated, the queues discovered. Markdown, shown on the node's own page — never
  on a card, because volume is exactly what `reason_cap` exists to keep off the grid
  — and **written through on every run**: hand over an empty one and the last is
  cleared, which is the point, since a roster that outlives the run that found it is
  a lie by the next tick.

  Two author rules. **It is never a status claim**: anything that should alarm is a
  reason, and this field must not become a second, quieter reason channel. What
  separates them is **status, not volume** — a list whose items each carry a verdict
  belongs in the reasons as coded entries (and the card clamps them); a list whose
  items carry none is scope and belongs here. *The roster is presence; an entry is a
  claim.* So the **count** of what was found is an `OK` reason, where it is seen
  without opening anything, and the forty **names** go in `report`, where they cost
  nothing. **And it belongs to whoever owns the node alone**: put a whole-check
  statement on the root of a container your check owns outright; on a container
  **shared** with another check, tag the owned children instead — a shared node
  publishes neither `config` nor `report`, by the same rule that withholds its
  timestamp. A check with whole-check information to publish should own its own node.
- **If you discover your own scope, you owe a coverage backstop**
  ([ADR-0043](adr/0043-coverage-backstop.md)). A filter that selects nothing must not
  read as a clean bill of health: report the scope, and grade the check's own node
  **`WARN`** when it is empty, naming the filter that produced it. Carry your own
  `expect_min`-shaped knob for "too few" — core provides none and needs to know none —
  built as one comparison whose default is `1` and which **floors at `1`**, so a
  deployment cannot switch the backstop off by configuration. The subject children
  still render when the scope is empty: a leaf you can see is empty is a leaf you can
  see is being watched.
- **Subnode labels — `about` / `title`** — a branch check can caption the subnodes it
  emits by setting a child's `about` (subject: what the aspect *is* and how it grades)
  and, rarely, `title` (a short label) ([ADR-0025](adr/0025-check-provided-subnode-metadata.md)).
  Set these only for **type-inherent** identity — a label the same in every deployment
  (a metrics type's `disk` / `memory` aspects) — and leave **deployment-specific**
  identity (this host's location, this box's role) to the deployment's `nodes.yaml`.
  They are **ignored on the root** (like `name` and `description`) and **fill an empty
  node field only**, so a `nodes.yaml` declaration always wins and the label freezes at
  its first fill; text that changes with each run belongs in `reason`, not here.

---

## 4. Registration & startup wiring

The loader resolves each YAML `type:` through the **`CHECK_TYPES`** registry
(`little_sister.checks`), and the engine loads checks **at process start**
(`app.py` calls `_start_engine_once()` → `create_engine()` → `load_checks()` at
import). So a type must be in `CHECK_TYPES` **before `little_sister.app` is imported**.
`@register(...)` populates the registry as a side effect of importing the module that
defines the class — the whole game is making that import happen first. A **type name
is claimed once**: a second class registering a name already taken refuses at startup
naming both ([ADR-0051](adr/0051-what-startup-refuses.md)).

**In a deployment** — add a thin WSGI wrapper that imports its checks, then the app:

```python
# wsgi.py — register the deployment's check types, then expose the app.
# The order is load-bearing and deliberately not sorted: importing
# little_sister.app builds the engine and loads the check configs at import time,
# so everything this deployment registers must already be in place. An import
# sorter puts `little_sister` first and silently inverts exactly that.
# isort: off
import my_deployment.checks          # noqa: F401  registration side effects
from little_sister.app import app    # builds the engine, loads the checks
# isort: on

__all__ = ["app"]
```

and point the runner at it (gunicorn → `wsgi:app` instead of
`little_sister.app:app`). The check package must be importable — run from the
directory where it resolves on `sys.path`. The same wrapper (and the same import
slot) also registers **secret resolvers** (§6), **template slot fillers**
([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)) and **configuration
aspects** ([ADR-0035](adr/0035-registering-a-config-aspect.md)).

The `# isort: off` fence is not decoration. Note that this file needs **no**
`# noqa: E402`: nothing sits between the two imports, and with this repo's ruff
selection an unused `noqa` is itself an error.

**In an installed package** — same seam, plus one thing a deployment wrapper does not
have. The package's `__init__.py` declares the **API epoch** it was built for, and
that declaration is what sits between the imports:

```python
# little_sister_example/__init__.py
from little_sister.checks import require_api

require_api(3)                       # refuses at startup on a mismatch, naming both

from little_sister_example import (  # noqa: E402  registers the type
    example,
)

__all__ = ["example"]                # or `# noqa: F401` — an unused import is an error
```

`API_VERSION` is the library's current epoch and `require_api(version, *, by="")` is
how a package pins the one it was written against ([ADR-0051](adr/0051-what-startup-refuses.md)).
A version **floor** in `pyproject.toml` cannot express this — a floor has no ceiling,
so it cannot see a library that has moved *past* your epoch. The surface itself is
pinned from the other side by an append-only snapshot,
`tests/fixtures/check_api_v2.txt`: a name may join the surface within an epoch, but no
name leaves it without the epoch moving. The deployment still writes
`import little_sister_example` in the same slot as any other registration; what a
package changes is who maintains the type and on what version line, not how it
arrives. Discovery without an import — an entry point that would let a deployment
install a type and write no line at all — does not exist yet; when it does, that
import is what it replaces.

**In the library** — the built-ins do the same thing via a side-effect import in
`little_sister/checks/__init__.py` (it imports `http`, `file`, `command`, `ssh`).

`CHECK_TYPES`, `little_sister.app:app`, `little_sister.secrets`, the
`LITTLE_SISTER_*` environment variables and every name in §2 above are part of
little-sister's **published version contract** ([`architecture.md`](architecture.md)
§11), so a tag won't move them under a deployment. Logging is on that contract as a
*behavior* rather than a name: call `logging.getLogger(__name__)` and your records
reach whatever the application configured — including your own setup, if you install
it before importing `little_sister.app`.

---

## 5. Configuration (YAML → your check)

- One `config/checks/*.yaml` = one check; `type:` selects your class, the rest are
  your fields plus the common ones. Configs are read **once at startup** across the
  path-list union of `checks/` directories under `LITTLE_SISTER_CONFIG_DIR` (default
  `config`); sub-directories are ignored, and nothing is skipped by name because
  `config/checks/` holds checks and nothing else
  ([ADR-0015](adr/0015-check-discovery-union.md),
  [ADR-0031](adr/0031-deployment-config-directory.md)). A restart re-reads them.
- **Read values with `little_sister.values`, not by hand**
  ([ADR-0026](adr/0026-reading-values-from-decoded-bags.md)). `text`, `number`, `real`
  and `rows` narrow a YAML value at the seam and take one line on what goes wrong: an
  **absent** key takes your default (`text`, `number` and `real` also take
  `required=True`, which raises instead); a key that is **present but uncoercible
  always raises** `CheckError`, and never quietly falls back — a threshold that reads
  `"twenty"` is a mistake somebody must see, not a reason to grade on `0`. All four
  take `where=`, which names the block the value came from so the message sends a
  reader to the right line of the right file. `flag` is the deliberate exception: a
  truthiness read, no `required=`, no `where=`, and it never raises.
  `parse_duration` reads the duration grammar, `coerce_code` a status name, and
  `parse_secret_refs` the `secrets:` block (§6).
- **`base_dir` is the config file's own directory**, handed to `_extra_from_config`,
  and resolving your relative paths against it is the **convention** — `command`'s
  `working_dir:`, the ssh `script:` — not a rule the library enforces. Two built-ins
  deviate on purpose: the `file` check resolves a relative path under `$HOME`, and a
  built-in's *default* script is looked up through
  [ADR-0021](adr/0021-script-resolution.md)'s search order, with `base_dir` in the
  middle of it. Say which you do in `config_summary()`.
- **Sibling order — `order`** — siblings render alphabetically, which is right until
  the set has an order of its own: a severity band row reads
  `critical high informational low medium`, filing *nothing to do* third. Set
  `order` and the snapshot sorts by `(order, name)` — a negative value pulls a node
  up, a positive one pushes it down, ties break by name, and the default `0` is
  exactly the alphabetical behavior, so a check that says nothing changes nothing
  ([ADR-0055](adr/0055-sibling-order.md)). Unlike `about` / `title` it is read on the
  **root** as well as on children, so a leaf check can rank the node it owns — which
  also means a root rank competes with **other checks'** nodes on the same wall; rank a
  root only where your check genuinely knows where it belongs, and expect a deployment
  to overrule you from its own config. It is a rank, not a status: set it from what the
  node is *about*, never from what it is reporting this minute — a row that re-sorts on
  every poll cannot be read.
- **Node metadata** (`title`, `about`) resolves **per field** by precedence:
  `nodes.yaml` keyed by node path **>** the check **>** empty
  ([ADR-0012](adr/0012-node-metadata.md) / [ADR-0017](adr/0017-node-title.md)). For a
  check's **root** node the check source is an inline `about:` / `title:` in its YAML;
  for the **subnodes a branch check emits** it is the `subnodes:` block in
  the check's config resolved over what the type declared, and the child
  `CheckResult`'s `about` / `title` beneath that — all of them filling an empty field
  only ([ADR-0025](adr/0025-check-provided-subnode-metadata.md); see the two bullets
  below and §3). A container node no
  single check owns can still be labeled via `nodes.yaml`. **`order` follows the same
  precedence** — `nodes.yaml` **>** an inline `order:` on the check **>** the
  `CheckResult`'s — with one difference: a stated `order: 0` in either file is a real
  declaration, whereas a check's `0` means it said nothing. Stating it is how a
  deployment overrules a rank a check set; it is *not* a request for alphabetical
  order, because `0` is the rank the unranked carry, so a zeroed node sorts ahead of
  every positively-ranked sibling. Putting a whole ranked set back to the alphabet
  takes an `order: 0` on each of them ([ADR-0055](adr/0055-sibling-order.md)).
- **Subnode labels: declare, don't mediate.** The per-aspect `title` / `about` a branch
  check ships are **declared**, in the two common constructor keywords
  `subnode_defaults` (`name → {title, about}`) and `label_tokens` (`token → value`),
  handed to `super().__init__()` from your own `__init__`. The library does the rest:
  it reads the deployment's `subnodes:` block out of your config, resolves each field —
  the configured text when present, your default otherwise, with `{default}` letting a
  deployment **extend** rather than replace and `{token}`s expanded by a plain replace
  (never `str.format`, so backticks and stray braces in the Markdown survive) — and the
  engine writes the result per subnode *name*, at any depth. So **do not parse
  `subnodes:`**, and do not layer a default yourself: the readers you would be
  duplicating have already run, and they are no longer on this surface to call
  ([ADR-0025](adr/0025-check-provided-subnode-metadata.md) — the
  same shape `show_when_quiet` uses, and the epoch bump that retired
  `parse_subnodes` / `resolve_text` / `expand_tokens`). Declare anything true of the
  check *type*: a deployment then retunes or annotates one aspect without touching code
  or `nodes.yaml`, and a type that runs several times in one deployment (one check per
  team) carries its prose once instead of once per config file. Tokens are resolved at
  **construction**, so a token value must be a construction-time fact — a label freezes
  at the node's first fill, and text that changes with an observation belongs in
  `reason`.
- **A label for a child only the run can name.** `CheckResult.about` / `title` stay for
  the child whose name no declaration could have anticipated — a volume, a repository,
  a tenant the run discovered. They are read **per field**, and only where the resolved
  map says nothing for that name. A check that wants such a child to inherit an
  aspect's text reads the resolved map, `self.subnode_labels[name][field]`, rather than
  its own constant: that is what carries a deployment's override down to it
  (`host-metrics`' per-volume leaves under `disk`).
- **Declaring that a node's quiet lines are the reading.** Most reason text is
  diagnostic — while the node is quiet there is nothing to read — but some checks'
  lines are an **inventory**: one line per instance, per volume, per account, read
  *because* everything is fine. A check whose quiet lines are noise already drops
  them itself; the opposite claim is `show_when_quiet`
  ([ADR-0063](adr/0063-declining-the-density-trade.md)), and the dense dashboard then
  keeps that node's full box and never folds it away. A check type's only part in it
  is the **declaration**, and it goes where the labels go: `show_when_quiet: True`
  in that subnode's `subnode_defaults` entry, beside its `title` and `about`, for an
  aspect that is an inventory *by construction*. The type's map is then shaped like
  the deployment's block, key for key, and one line in the package replaces an entry
  per aspect per node path in every installation's `nodes.yaml`. Declare it as a
  real boolean: a string is refused at load, naming the subnode, because
  `bool("false")` is `True` and a quoted one would switch a node on while the source
  says off.
  Say nothing at all for a node the check has no opinion about — an entry that
  omits the key leaves the field for somebody else, while `False` is a *statement*
  and would shut out a declaration a deployment wanted to make. The deployment's
  half needs nothing from you either: the library reads
  `subnodes: {name: {show_when_quiet: …}}` out of the check's config, for **every**
  type, and merges it over your declaration per name — so do not parse the key in a
  check, and do not layer it yourself; both readers have already run. Ship a
  declaration only for the aspect whose *content* is a list, not for one you would
  like to be more visible — a wall of declared nodes is a configuration smell, and
  dense mode's benefit shrinks by exactly as much as somebody declares.
  `CheckResult.show_when_quiet` stays for the child a run *names* — a volume, an
  instance — which is the same dynamic-child channel the labels keep; the root's own
  source is the `show_when_quiet:` key in its YAML, which no result may overrule.
- **Ownership** — two checks may not own overlapping nodes; the loader rejects the
  whole load with a named conflict. A branch check that shares a container overrides
  `owned_nodes()` to own its child subtrees only (§2), so peers can coexist (ADR-0015).

---

## 6. Secrets & credentials

A check names its credentials in a **`secrets:` block**, each value a **secret
reference** ([ADR-0023](adr/0023-secret-references.md)):

```yaml
secrets:
  token: env://GITHUB_TOKEN        # or aws-sm://myteam/github-token
```

**`env://NAME`** reads that environment variable — fed by the git-ignored `.env`,
which little-sister loads into `os.environ` at import with `setdefault`, so a real
environment variable overrides the file
([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). Any other
**`scheme://address`** reference (`aws-sm://team/github-token`) goes through the
resolver the application registered for that scheme
(`little_sister.secrets.register_resolver`) — registered in the same
import-before-app slot as the check types (§4); the library ships no store client.
A scheme is claimed **once**, and a second claim from a different package refuses at
startup naming both, because a scheme says where a credential is read from
([ADR-0064](adr/0064-the-resolver-is-a-registration.md)).

- **Resolve at construction, never while measuring.** Call
  `self.resolve_secret(reference)` from the constructor and keep the value — cloud
  stores bill per read, and rotation is a restart, like any other config change.
- **The failure split is handled for you.** A **malformed** reference raises
  `CheckError` and the load fails loudly like any config typo — that covers an empty
  value, a scheme with no address, a scheme no resolver is registered for, and, the
  one that matters most, a value carrying **no `scheme://` at all**. That last case is
  why the grammar is strict: a credential pasted where its reference belongs fails to
  parse instead of being looked up, and the message never quotes what it rejected. A
  **well-formed** reference that cannot be resolved (store unreachable, secret absent)
  is recorded on the check instead, and the engine **pins** it: the node shows `ERROR`
  with *"secret unresolvable: …"*, neither half of the check is ever called, and there
  is no retry until restart. Nothing is recorded either: the check did not fail to
  reach its object, it never went.
- **Don't validate the resolved value yourself.** `resolve_secret` returns `""` on a
  failed resolution and records the failure; a constructor that answers with
  `raise CheckError("token is empty")` converts one pinned, visible, explained node
  into a **whole-load failure**, which is exactly the outcome ADR-0023 chose the pin to
  avoid — one unreachable store must not take down all monitoring and leave an empty,
  unexplained tree.
- **Parse the block with `parse_secret_refs(config, "token", …)`** in
  `_extra_from_config`, and resolve what it returns in the constructor. Every name
  you list is required — deliberately: a default reference baked into the check type
  ties every instance of it to the same credential, which is what stops a deployment
  running the type twice, once per team, with a token each. A deployment then moves
  that one secret to a store by editing one YAML line — no code change.
- Secrets **never** reach the repo, `config_summary()` or a reason. `.env` stays
  git-ignored; only the *address* of a secret may appear in YAML.

---

## 7. External I/O: the run's budget, and what a failure means

Two questions. The library gives you the vocabulary for the first and refuses to
answer the second at all. Everything here is promised by name (`little_sister.transport`,
`little_sister.fetch`, `little_sister.process`; [`architecture.md`](architecture.md)
§11), and [ADR-0058](adr/0058-transport-policy-vocabulary.md) is the record, with
[ADR-0089](adr/0089-a-process-a-check-starts-ends-with-it.md) for a process.

### The budget is the run's, not the request's

**`timeout:` bounds the whole run**, one request at a time inside it. Build a
`Deadline` from `self.timeout_seconds` at the top of `measure()` and pass it down:

```python
from little_sister.fetch import fetch
from little_sister.transport import Deadline, DeadlineExceeded, Fault, RemoteError

deadline = Deadline(self.timeout_seconds)
# `request_timeout` is a field this check parsed itself — the common fields
# carry the run's budget, not a per-request one (§2).
response = fetch(url, timeout=self.request_timeout,
                 follow_redirects=False, deadline=deadline)
```

`deadline.budget(t)` clamps each request to what the run has left, `expired()` says
whether to start one at all, and `affords(wait)` vetoes a backoff that would outlive
the run. **Spending `timeout_seconds` directly as a socket timeout is the anti-pattern
this replaced**: a check that asks fifty times then has fifty budgets and no bound —
which is how a slow provider once wedged a run indefinitely. The single-request case
is the exception, and the built-in `http` check is it: with one request the clamp is
`min(t, t)`, so it passes no deadline and says so in a comment.

One honest residual: a deadline does not reach the **status line and headers**, which
urllib reads inside `opener.open` before `fetch` has a stream. A server trickling
those is bounded only by the socket timeout per read. It is stated rather than
implied.

### `fetch` makes the request; `ask` retries it

`fetch(url, *, timeout, follow_redirects, …)` is the one place the library opens a
socket. Both keywords are **required** — a request with no timeout is the defect this
project keeps rediscovering, and a redirect policy assumed rather than chosen is the
one above it. It returns a `Response` for **every** status, `500` included: a status
is an answer, not an exception. Two things still raise: a failure that never reached a
status, as a `RemoteError` with `Fault.TRANSIENT`; and a body over `max_bytes`, as
`Fault.MALFORMED` — it arrived and cannot be used.

`ask(operation, *, deadline, backoff=…)` wraps one bounded retry around a call,
spending a service's own `Retry-After` in place of its backoff when there is one and
the deadline affords it.

**`ask` is not the ADR-0033 retry, and the two are worth keeping apart in your head.**
`ask` re-tries a *request*, inside one run and inside the run's own budget,
invisible to the scheduler — one second by default, or whatever the service asked for
when it said so. `retry_interval_seconds` / `retry_attempts` (§2) re-schedule a *check*
between runs. Different mechanism, different budget, same English word.

### A `Fault` says what happened; only you can say what it means

`Fault` has three members, set **by status and never by message text**: `TRANSIENT`
(we could not ask — a 5xx, a timeout, a transport failure; the only member `ask`
retries), `ANSWERED` (a 4xx — absent, or not visible to this credential), and
`MALFORMED` (it arrived and cannot be used — no status at all). `fault_for(status)`
gives this family's reading of a status you consider a failure. `RemoteError` takes
`fault` **required, with no default** — the classification is the decision this
vocabulary exists to make consistent, and a default would be that decision taken by
whoever forgot to pass it. **Subclass `RemoteError`** and keep your own error class,
your own message prefixes and every `except` clause you already have.

There is deliberately **no mapping from a `Fault` to a `StatusCode`**, because that
mapping depends on the question from §1:

- **The endpoint is your subject.** Failing to answer *is* the reading. Map it
  straight to `ERROR` on your node. `checks/http.py` is the example, and it is the
  short case.
- **The endpoint is your instrument.** Then a failure is not a finding about the
  thing you were grading ([ADR-0060](adr/0060-a-line-makes-no-claim.md)). For each
  subject you could not read, emit a line coded `UNDEFINED` — *this line makes no
  claim* — so its subject is not painted amber for somebody else's outage. Grade your
  **own** node `WARN` for the coverage gap (§3). And **do not overwrite a last-known
  reading**: if you read nothing, omit the node rather than replacing its lines, and
  ADR-0007's no-prune rule keeps the last good reading with its own timestamp until
  freshness calls it old.

`DeadlineExceeded` is deliberately **not** a `RemoteError`. Catch `RemoteError` per
item, so one subject's failure becomes one line; let `DeadlineExceeded` reach a single
run-level handler, keep the children that finished, and say **once** that the run was
cut short. If it arrived as a `RemoteError`, one run-level fact would be spelled as
forty item-level ones.

### Throttles, and what stays yours

A service answering *not now* is `TRANSIENT` and carries a number, not a fourth fault.
`fetch.retry_after(headers)` reads the standard `Retry-After` in both forms RFC 9110
allows; attach it as `RemoteError(..., fault=Fault.TRANSIENT, retry_after=…)` and
`ask` will spend it inside your deadline. What stays in your package is the **vendor's
dialect**: no status identifies a throttle — a service may answer `403` or `429` for
it, and a bare `403` may equally mean *not visible to this credential* — so
`fault_for` classifies `429` as `ANSWERED`, and a throttle is only retried if you say
so. Beyond that: batch where you can, keep `frequency` sane, and prefer few calls per
run.

### A process goes through `run`

A check that starts a process calls `little_sister.process.run` rather than
`subprocess`. It is `fetch`'s counterpart and settles the same kind of questions once:
it takes an argument vector — a shell command is `["/bin/sh", "-c", command]`, said by
you — runs it in a process group of its own with `/dev/null` for stdin, reads both
streams under a cap, and ends the whole group at the bound, when the instance stops,
and at a normal end for whatever the command left behind, so an abandoned run never
leaves a process behind. The answer is a `Finished` whatever the status; `NotStarted`
is what it raises for a command that could not start, and `DeadlineExceeded` for a run
already out of budget.

```python
from little_sister.process import Ended, NotStarted, run

try:
    done = run(["df", "-P", "/"], timeout=10, deadline=deadline)
except NotStarted as error:
    ...  # the command could not start: a reading that says so
if done.ended is Ended.BOUND:
    ...  # it outran its bound, and its group has been ended
text = done.stdout.decode("utf-8", "replace")
```

What a status *means* stays yours, as with `fetch`: a non-zero exit is a fact about the
command, and only your check can say whether it is a failure of its subject.

### Never raise out of `measure()`

Not because the engine cannot cope — it can, and turns any escaping exception into an
`ERROR` node carrying `check error: …` plus a short traceback
([ADR-0040](adr/0040-what-a-failing-check-becomes.md)), and writes a failure record
naming your object so the attempt is still in the history
([ADR-0086](adr/0086-a-check-measures-and-grades.md)). Because that node is ugly, it
says nothing an operator can act on, and it replaces every line your check had
published. Catch what you expect, record it as a reading with its values standing as
`None`, and say it properly in the grading.

The same goes for `grade()`, and there it is worse: a grading has no I/O to blame, so
an exception out of it is a bug in your own arithmetic — and the engine keeps the
reading it already had rather than replacing it with the failure, precisely because
that reading is still true.

**Keep dependencies light.** The extracted check-type packages reach their provider
through `little_sister.fetch` and `little_sister.transport`, and all but one ship
with little-sister as their only dependency (the AWS type argued for boto3 in its own
record). That is measured, not hoped for, and it is what keeps an extraction cheap.

---

## 8. Testing & the gate

- **Type-check and test against the floor you promise, not only against the
  interpreter you develop on.** Whatever `requires-python` says is a promise to
  everybody who installs you, and a promise nobody exercises is a claim that decays —
  a stdlib name that arrived two versions later type-checks perfectly on your machine
  and fails on theirs. Running `mypy --python-version <floor>` costs about a second
  and catches exactly that class
  ([ADR-0054](adr/0054-python-floor-and-development-version.md) sets out the
  reasoning). **Your floor is yours to choose**: little-sister promises 3.11, and a
  plugin that needs 3.15 for something real is welcome to say 3.15 — it simply means
  the deployments that can install it are the ones already on 3.15.
- **`mypy` runs over `src` only** — tests are not type-checked. Where a test double
  has to model a real object's shape, nothing mechanical will tell you it drifted;
  say so in the double.
- **Unit-test both halves against recorded fixtures / a fake transport — no live
  network in tests.** Patch the opener rather than the check: that keeps the seam at
  the boundary the code is about. Test `measure()` on the **record** — every key you
  promised, present and null where the world did not answer — and `grade()` on the
  `code`, the `reason` and (for a branch) the child tree shape and names. Test the
  grading by **handing it a record you wrote yourself**, not one you just measured:
  that is the one test that proves it is pure, because a record you typed is exactly
  what a series will hand it a year from now. For a check with a credential,
  substitute a fake resolver / environment and cover both the resolved and the pinned
  path (see `tests/test_secrets.py` for the patterns).
- **A test double is a claim about the real thing, and it can be wrong.** One that
  modeled a blocking `read` where the code needs `read1` hid a real overrun for a
  release: the double answered instantly and the socket did not. Where the shape
  matters, make the double **refuse** the method your code must not call.
- **Test the sentence, not the mechanism**, and prove each test by a mutation that
  breaks it. A correct mechanism has carried a false sentence through a fully covered,
  fully green gate.
- **Coverage: point it at your own package.** The library's
  `--cov=little_sister` is the one setting a plugin must **adapt rather than copy** —
  copied, it measures somebody else's code from your repository. There is no
  `--cov-fail-under` anywhere, deliberately: coverage is a report, and it is not
  evidence that a decision is tested.
- **Smoke-test config loading** without starting the server:

  ```bash
  uv run python -c "import my_deployment.checks; \
      from little_sister.checks import load_checks; \
      print(len(load_checks()), 'checks OK')"
  ```

  (Import the module first so the types are registered; for the built-ins alone the
  import line is unnecessary.)

---

## 9. Extraction to a plugin

Build a deployment check type so it lifts out cleanly: a **self-contained module**
(class + tests + an example YAML + a short doc), **minimal dependencies**, and
credentials behind **secret references** (§6). This section is the *design* advice —
what makes a type liftable when it turns out to have a second user.

The table below is no longer a prediction. Four extractions have run against it and
every row that applied held — what could not move turned out to be configuration
already, which is the same line arriving from the other direction. The check-type
packages exercised the whole table; the surface extension has no credential and no
subnode prose, so it tested the knob row alone.

The line to build against is **type vs deployment**: what is true of the check *type*
travels inside the package, what is true of one installation stays in that
deployment's YAML — and being explicit there is a feature, not duplication, because a
plugin user should be able to read their own choices without knowing the type's
defaults.

| Travels with the plugin | Stays in the deployment's config |
|-------------------------|----------------------------------|
| subnode `title` / `about` prose, its `{token}` grammar, severity legends (§3) | which org / team / host, and every threshold, ignore list and tuning knob |
| the default for each optional knob | the value this installation actually chose |
| the code that reads a credential | the **reference** naming where that credential lives (§6) |

Two consequences are worth designing for before the plugin exists. A credential
reference is **required, never defaulted**: a type that bakes in `GITHUB_TOKEN` ties
every instance to one secret, so a deployment cannot run it twice with different
credentials — one check per team. And the type's prose stops being a file the
deployment can edit, so a label must be **extendable**, not only replaceable: that is
what `{default}` in a `subnodes:` value buys (§3), letting a deployment append its own
note to shipped text and still inherit the next version of it.

### What to call it on PyPI

There is no namespace enforcement on an index, so the convention has to do the work.
**Please name a third-party plugin `<you>-little-sister-<plugin>`** — your own name or
your organization's first, then the library, then what the plugin does:
`acme-little-sister-jenkins`, `rnd-little-sister-grafana`.

That leaves the bare **`little-sister-<plugin>`** form meaning *maintained alongside
little-sister itself*, which is worth something to the person choosing between two
packages that both claim to check the same product: they can tell at a glance whose
release line they are taking on. It is a courtesy rather than a rule — nothing stops
you, and nothing breaks if you do not — but it keeps the index legible, and it means
your package's name says who stands behind it rather than only what it talks to.

The import package follows the distribution name, with the hyphens as underscores:
`acme_little_sister_jenkins`. That is what `wsgi.py` imports, so it is the name a
deployment's operator actually types.

---

## 10. Aspects, and letting a deployment switch one off

If your check emits **one child per aspect** (§3) — a container node with a named
leaf per thing it measures — give every aspect an `enabled:` switch. Two check
types in this family arrived at the same shape independently, which is the usual
sign that it belongs in the how-to rather than in each of them.

**Why a deployment needs one.** A type is installed for *some* of what it does.
The aspects a given installation does not want are not merely noise on a wall:
they are calls against a rate budget, and they are usually permissions somebody
has to grant. A read the credential is not allowed to make reports a failure that
is perfectly true and completely useless — nobody will fix it, because nothing is
broken. Without a switch the options are a permanently red node, a maintenance pin
nobody ever lifts, or a fork of the type.

**The switch goes in the aspect's own block**, beside the knobs that shape it:

```yaml
security_advisories:
  enabled: false              # this account has no Advanced Security
  severities: [critical, high]
```

— not a check-level `aspects: [a, b, c]` roster. In its own block it is read where
somebody configuring that aspect is already looking, and the block usually exists
anyway. A roster has to be maintained against a list it does not own: when the type
gains an aspect, every existing config either silently loses it or has to be edited,
and neither is what the deployment asked for.

**An aspect that says nothing is on.** The default is `True`, so every config
written before the key existed still means what it meant. Adding the switch to a
shipped type is therefore not a breaking change — where *removing* an aspect is,
because its node path is what maintenance pins are held against.

**Off means the node is not there** — not a node carrying "this aspect is switched
off". That node is the thing somebody turned off in order to stop seeing — and on a
check that repeats its aspects per account, a handful of them is a wall of cards
saying nothing. **Skip the work, not only the node:** the paragraph about a
permission nobody will grant only holds if the call is never made.

**Then name what is off, on the check's card.** This is the obligation the previous
rule creates, and the easiest one to skip. A node absent because its aspect is off
looks exactly like a node absent because the check broke before reaching it, and
`config_summary()` is the page an operator opens to find out which. Name the
disabled aspects there — and *only* when there are some, or every card carries a
row about a feature the check is not using.

**Refuse a config that switches off every aspect.** It is not literally nothing —
the root still reports what it discovered — but such a check makes no finding about
any of it, while looking, from the dashboard, exactly like one that does. Deleting
the check says that out loud; a config of `enabled: false` whispers it. Raise
`CheckError` and name what to do instead.

**Read the boolean strictly.** `bool("false")` is `True`, so a quoted YAML boolean
would switch an aspect **on** while its config says off, and nothing downstream
could notice — the aspect would simply report. A switch is worth less than nothing
if it can silently mean its opposite:

```python
def _flag(value: object, where: str) -> bool:
    if not isinstance(value, bool):
        raise CheckError(f"{where} must be true or false")
    return value
```

The same applies to every other boolean knob beside it: a quoted `show_healthy`
listing a hundred healthy lines is the identical failure with a friendlier face.

**The shape, in code.** A class-level roster the key is read against, and one
accessor the tree is built from:

```python
class MyCheck(Check):
    #: Every aspect this type can run, whether or not this check runs it.
    ASPECTS = ("pull_requests", "security_advisories", "actions")

    def active_aspects(self) -> tuple[str, ...]:
        """The aspects this check runs, in ASPECTS order."""
        return tuple(name for name in self.ASPECTS
                     if self._block(name).enabled)

    def run(self) -> CheckResult:
        build = {"pull_requests": self._pull_requests,
                 "security_advisories": self._security_advisories,
                 "actions": self._actions}
        return CheckResult(StatusCode.OK, [self._scope_reason()],
                           children=tuple(build[name]()
                                          for name in self.active_aspects()))
```

`_block(name)` is whatever holds that aspect's parsed settings — a per-aspect frozen
dataclass, or a slice of one config object. Spell the mapping out rather than
reaching for `getattr`: the attribute names are already written in the constructor,
and `getattr` hands a type checker an `Any` at the one seam worth checking.

Keeping `ASPECTS` complete — every aspect the *type* can run, not every aspect
*this* check runs — matters twice: it is the roster `enabled:` is read against, so
an unknown aspect name in a config can be refused, and it is what a rate or cost
estimate has to be computed from before any of it is switched off.

**A maintenance pin against a switched-off aspect survives.** Startup reaps pins no
check root covers (ADR-0014 / ADR-0015), and a disabled aspect's path is still under
its check's root, so the pin is left alone rather than reaped — it covers nothing
while the aspect is off and applies again the moment it comes back. Expiry remains
its backstop. That is the behavior you want for "off for the migration", and it is
worth knowing before somebody reports the pin as a leak.

**Where this may end up.** Two implementations of a rule are two implementations, and
plumbing solved once should not be solved again — so a third check type needing `_flag`
and this roster is the point at which they stop being a pattern in a how-to and become
something the check-authoring surface offers (`architecture.md` §11). Offering it is a
version-contract commitment, so it waits for the third, not for the second.
