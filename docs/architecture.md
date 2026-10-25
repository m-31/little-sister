# Little Sister — Architecture

How the codebase is built **today**. For the product (what and why) see
[`project.md`](project.md); for the rationale behind the choices here see
[`decisions.md`](decisions.md) and [`adr/`](adr/).

---

## 1. Technology stack

| Concern | Choice |
|---------|--------|
| Language | Python ≥ 3.11 — the floor a package promises ([ADR-0054](adr/0054-python-floor-and-development-version.md)); developed and gated on the exact 3.14 patch level `.python-version` pins |
| Web framework | Flask + Jinja2 (`StrictUndefined`) |
| WSGI server | gunicorn (single worker, threaded) |
| Config | YAML (PyYAML); secrets from a `.env` file |
| Build / tooling | uv (`uv_build`, `uv.lock`); ruff, mypy, pytest |
| Frontend | Bootstrap 5 + Floating UI via CDN; one local stylesheet + a little vanilla JS |
| Markdown | markdown-it-py — server-side rendering of node text ([ADR-0018](adr/0018-markdown-rendering.md)) |
| Dependencies | Flask, gunicorn, PyYAML, `markdown-it-py[linkify]` (the extra backs autolinking, ADR-0018) and tzdata — that is all of them; checks use the standard library (the SSH checks shell out to the external `ssh` binary) |
| License | MIT |

A deployment host is anything that runs the floor: a Mac on the network it
watches, or a Linux container behind a load balancer. The SSH checks shell out to
the host's `ssh`, so what a host can reach is what its checks can read.

---

## 2. Repository layout

```
little-sister/
├── README.md            # install / run instructions
├── pyproject.toml       # metadata, deps, tool config (mypy targets src/)
├── uv.lock
├── hooks/pre-commit     # the gate (§10), opt-in via core.hooksPath
├── docs/                # the documentation set
├── config/              # the deployment's configuration, by aspect (ADR-0031)
│   ├── actions.yaml     # deployment action chips (ADR-0038) — example, inert
│   ├── aggregation.yaml # configured rules: how a part counts above it (ADR-0137) — example, inert
│   ├── checks/          # check configs (*.yaml), plus examples/ and a README
│   ├── csp.yaml         # Content-Security-Policy sources (ADR-0048) — example, inert
│   ├── settings.yaml    # general options (timezone, time_format)
│   ├── links.yaml       # optional: curated links (or links/ with icon files)
│   ├── nodes.yaml       # optional: node metadata, keyed by node path
│   └── users.yaml       # login list, or users/{users.yaml, avatars/} (gitignored)
├── src/little_sister/
│   ├── app.py           # Flask app: routing, login, .env load, engine start
│   ├── api.py           # JSON serialization for backend mode: the status read and the series read (ADR-0080, ADR-0122)
│   ├── status.py        # Status / StatusCode domain model + roll-up
│   ├── codes.py         # the status vocabulary, a leaf module nothing imports from
│   ├── reasons.py       # addressable reasons: a node's reason list as keyed entries (ADR-0036)
│   ├── line_template.py # a line as a template over its record: the notation, the rendering, the declarations (ADR-0126)
│   ├── grading.py       # what a type grades and how a deployment writes it: the declarations, the readers, the verdict (ADR-0131)
│   ├── tree.py          # the shared, thread-safe StatusTree, event log, history
│   ├── aggregation.py   # the configured rules, config/aggregation.yaml: what a rule is, where it acts (ADR-0137)
│   ├── rule_words.py    # what a configured rule says where it stands, in one sentence (ADR-0137)
│   ├── checks/          # Check base + http/file/command + ssh/ family + loader
│   ├── transport.py     # transport policy: what a check does about a request that may not answer (ADR-0058)
│   ├── fetch.py         # one HTTP request with that policy applied
│   ├── engine.py        # scheduler + thread pool: runs checks → upserts the tree
│   ├── limits.py        # the engine's limits, what it measures against them, its own lines (ADR-0072)
│   ├── series.py        # a subject's readings over time, and the memory tier that keeps them (ADR-0087)
│   ├── measures.py      # what a measure is, where it is declared, how its value is written (ADR-0092)
│   ├── curves.py        # a measure's curve over its series: the geometry a page draws (ADR-0092)
│   ├── config.py        # general config (config/settings.yaml) → Config
│   ├── config_dir.py    # the config path-list and its aspects (ADR-0031)
│   ├── values.py        # typed reads out of decoded YAML/JSON bags (ADR-0026)
│   ├── errors.py        # CheckError + ConfigError (shared; see below)
│   ├── secrets.py       # secret references → values; resolver registry (ADR-0023)
│   ├── pins.py          # a pin with a kind, and the pins as a state file (ADR-0141)
│   ├── notes.py         # a node's notes: the book, its file, the retention (ADR-0140)
│   ├── state.py         # the state layer: var/state/, the writer, the two failure lines (ADR-0071)
│   ├── keeper.py        # the seam that carries var/state/ off the machine (ADR-0071 §5)
│   ├── self_report.py   # what the instance says about itself: contributors → /little-sister (ADR-0072)
│   ├── readiness.py     # has this instance come up, and what it can see (ADR-0073)
│   ├── links.py         # the `links` aspect: curated links, re-read on change
│   ├── users.py         # the `users` aspect: login list + avatar resolution
│   ├── identity.py      # who a request is from, and the one login gate (ADR-0068)
│   ├── local_login.py   # the built-in login list, as a provider like any other (ADR-0069)
│   ├── system_admin.py  # the one door the library ships, and it is not a provider's (ADR-0069)
│   ├── origins.py       # where an import package came from: distribution, version, file
│   ├── watch_lines.py   # what /about's hero says: the pools a render draws from
│   ├── icons.py         # icon names, the pack registry, where the bytes are
│   ├── icon_pack/       # the built-in marks (our own drawn glyphs) + manifest
│   ├── nodes.py         # the `nodes` aspect's metadata + startup consistency pass
│   ├── handbooks.py     # a node's handbook: text, or a file it names (ADR-0133)
│   ├── details.py       # a node's details: named values, given down key by key (ADR-0133)
│   ├── tags.py          # a node's tags: words given down as a union; tags.yaml (ADR-0139)
│   ├── render.py        # safe server-side Markdown → HTML (markdown-it-py)
│   ├── titles.py        # a title that repeats the name, or has no word in it
│   ├── first_look.py    # a node's first look: which file speaks first, what the page draws
│   ├── spans.py         # how a span of time is written, on every surface
│   ├── instants.py      # an instant: the clock, what holds one, its spelling, its reading
│   ├── dashboard_layout.py  # stable, width-priced track allocation for the dashboard (ADR-0056)
│   ├── paths.py         # a loaded-from path, drawn against a root the reader has
│   ├── copy_status.py   # the canonical incident hand-off: the tree's document, a
│   │                    # branch's, a leaf's and one reason's, from one formatter
│   ├── copy_action.py   # the built-in copy chip, in the reason.actions slot
│   ├── slots.py         # template slots a dependent package fills (ADR-0034)
│   │                    # and the assets it ships for them (ADR-0037)
│   ├── actions.py       # the declarative action list, config/actions.yaml (ADR-0038)
│   ├── csp.py           # the assembled Content-Security-Policy (ADR-0048)
│   ├── logger.py        # root logging, if nobody else set it up (stderr + file),
│   │                    # and LOG_LEVEL, a list that names loggers (ADR-0121)
│   ├── noise.py         # noise caps a package declares for what it brings (ADR-0121)
│   ├── users.example.yaml  # sample login list — the real one is a config aspect
│   ├── templates/       # Jinja2 pages
│   ├── brand/           # the eye, the family's drawing — every icon is drawn from it
│   └── static/          # CSS, the page JS (poll, popover, reason overflow, rail,
│                        #   submit-on-change), the icons, webmanifest
└── tests/               # test_*.py, one per area (§10), plus the UI harness
```

Only the aspects this repository itself uses are tracked under `config/`; the
optional ones above are what a deployment adds beside them
([ADR-0031](adr/0031-deployment-config-directory.md), [ADR-0035](adr/0035-registering-a-config-aspect.md)).

Everything a deployment authors lives under `config/`, and everything the process
writes lives under `var/` ([ADR-0031](adr/0031-deployment-config-directory.md)); the
one exception either way is `.env`, which is secrets read before anything else
([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). The file-form
`config/users.yaml` and directory-form `config/users/` are git-ignored and supplied
per deployment; the package ships only a sample.

### The family, and which way it points

This repository is one of several, and the arrows between them only ever run one
way — **toward the library**. Nothing here imports a deployment, and nothing here
knows a plugin exists.

| | | |
|---|---|---|
| **the library** | this repository | the engine, the built-in types, the web and JSON surfaces, and the seams below |
| **a plugin** | `little-sister-<x>` | one check type, one surface extension, or another registration such as a secret resolver — occasionally more than one of them — in a repository of its own. Depends on the library with a **floor** (`little-sister >= x`), never a pin |
| **a deployment** | private | the checks, node metadata, users and secrets of one installation. **Pins** the library, installs the plugins it wants, and writes the `wsgi.py` that imports them |

Four plugins exist today — **`little-sister-github`**, **`little-sister-wiz`** and
**`little-sister-aws`** (check types), and **`little-sister-jira`** (a surface
extension: two template slots and a configuration aspect, no check type).
`little-sister-aws` is the one that carries more than a type: an `aws` check type, the
`aws-sm://` and `aws-ssm://` secret resolvers (§7) and the identity seam beneath both,
which is what one vendor, one client and one credential look like when they arrive
together. Each releases on its own version line —
same shape as this one, a generated branch and an annotated tag
([ADR-0022](adr/0022-generated-release-branch.md)) — and each registers into the seams
§11 promises.

Giving a type a repository of its own is a decision about whether the type would ever
have a second user, not a step every type takes.

The direction is what keeps the seams honest: a plugin may only write against §11,
so the library can move anything else; and a deployment may install a plugin the
library has never heard of, because the registry is the only thing they share.

---

## 3. Process & runtime model

little-sister runs as **one process**: `gunicorn --workers 1 --threads N` (the
`gthread` worker) with the library's hooks module, `--config
python:little_sister.gunicorn_hooks`, or `python -m little_sister.app` for local dev.

- The **engine** runs checks on a **bounded thread pool**, scheduling each at its
  `frequency`. Checks are I/O-bound and the GIL is released during I/O, so threads
  give real concurrency.
- All threads share **one in-memory status tree** plus a bounded in-memory **event
  log**, guarded by a single `threading.RLock`. Reads take an immutable snapshot
  under the lock and render it outside (ADR-0002).
- The tree lives in memory only. What a restart keeps is the **state layer**
  (§4.8, [ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)):
  JSON files under `var/state/` — the admins' maintenance side-table, written
  through ([ADR-0014](adr/0014-maintenance-persistence.md)), and the event log and
  the series, compressed and written at most once per interval and at the stop's one
  save — read back at startup. The directory has **one writer**, the process that holds its lease
  ([ADR-0090](adr/0090-one-state-directory-one-writer.md)). Nothing that is a service
  is in the core.
- **An import is not an instance**
  ([ADR-0091](adr/0091-an-import-is-not-an-instance.md)): importing the application
  builds it and writes nothing. The engine starts **once, at the server's start** —
  gunicorn's `post_worker_init` in the worker, right after its import, through the
  hooks module, or the development server's `__main__` — and runs its checks on
  **daemon threads the interpreter does not join**. It **stops when the worker
  leaves**, at `worker_exit`, with `atexit` as the backstop: the runs in flight are
  abandoned, what they started is ended, and one final save is the last write
  ([ADR-0088](adr/0088-a-stop-ends-at-its-save.md)).

A **single worker is a hard constraint**: a second worker would be a separate
process with its own tree. This follows from keeping all state in memory
([ADR-0001](adr/0001-in-process-threaded-engine.md)).

---

## 4. Domain model & state — `status.py`, `tree.py`

### 4.1 `StatusCode`
```python
class StatusCode(Enum):
    MAINTENANCE = auto()
    OK = auto()
    WARN = auto()
    ERROR = auto()
    UNDEFINED = auto()
```
Plus `is_valid_status_code(value)`, a case-insensitive membership check.

### 4.2 `Status`
A node in the tree. Fields:

- `path` — the node's full, **absolute, slash-separated** location (`/system/alpha`);
  `name` is a derived property, the last segment (ADR-0016).
- `code: StatusCode` — accepts a `StatusCode` or a valid (case-insensitive) string.
- `reason: list[str]` — the reason **texts**, a read-only view of `reason_entries`
  (`ReasonEntry(slug, text)`), which is the one internal form
  ([ADR-0036](adr/0036-addressable-reasons.md)). A bare string is one entry;
  `members: bool` says the entries are individually suppressible rather than one
  condition in several paragraphs. An entry may also carry a `subject` — what the
  line is *about*, as the source's own identifier — and `data`, the **record** the
  check read about it, or, where the seam refused that record in a run, `refused`,
  why ([ADR-0093](adr/0093-a-record-the-seam-refuses-costs-its-line.md)); none of
  them declares members, because data about a claim is not a claim. A **measure** is not a third field: it is a *projection over the record*,
  chosen when it is drawn, which is the footing grading and rendering already have
  ([ADR-0085](adr/0085-a-measure-is-read-out-of-a-record.md)). The unit belongs to
  that projection, so a record's key names its unit for the reader (`response_ms`)
  and a curve's axis is labelled where the curve is declared.
- `subject: str`, `record: dict | None` — **what this node's check measured, and the
  object it measured** ([ADR-0085](adr/0085-a-measure-is-read-out-of-a-record.md)). A
  check run reads one object and the result is **one record**; the node's code, its
  lines and its children are *derived* from that reading, so the reading belongs to a
  `Measurement` ([ADR-0086](adr/0086-a-check-measures-and-grades.md)) and the engine
  puts it on the node that stands for the object — the mount, for the one-object case
  every check in this repository is. Where a run reads **several** objects the engine
  places none of them, because which node, child or line each stands for is what the
  grading said in the tree it returned. Only an object with **no node** carries its
  record on a line instead (`Entry.data`), which is the
  case a repository or a job run is. `subject` is the identifier the check actually
  reached and deliberately **not** the path: a path is the deployment's label for where
  a node hangs and may be renamed, while the reading is about a thing in the world, and
  an identity not written down at the reading cannot be added afterwards. Written
  through on every run like `report`, so a run that read nothing clears the last
  reading; withheld by the snapshot on a mount two checks share, where no single writer
  can be believed (ADR-0015, ADR-0044 decision 1).
- `timestamp: datetime | None` — the **observation time**, an instant the one clock
  answered ([ADR-0120](adr/0120-every-stored-time-is-an-instant.md)): `None` until the
  node's first `update()` / `touch()`, so *having* one means a check has written this
  node ([ADR-0027](adr/0027-observation-timestamp-semantics.md)). Construction never
  stamps; a node the tree created on the way down to a check carries none.
- `description: str`, `frequency_seconds: int | None`, `config: str` — metadata
  inherited from the check and set by the tree; `config` is the curated parameters
  the check ran with, as Markdown ([ADR-0013](adr/0013-check-config-on-node.md)).
- `stale_after: float | None` — how old this node's reading may get before it is
  stale, where somebody **stated** the tolerance rather than a period implying it
  ([ADR-0079](adr/0079-freshness-is-a-stated-tolerance.md),
  [ADR-0081](adr/0081-an-instance-node-states-a-tolerance-not-a-period.md)). `None`
  means nobody stated one and the tolerance is derived from `frequency_seconds`,
  which is every check that has a period; the instance's own branch states one and
  carries no period at all, because it is read on no check's schedule.
- `report: str` — what the run **found**, beside `config`'s what it ran **with**
  ([ADR-0044](adr/0044-run-facts-on-the-node.md)): Markdown, written through on
  every run — an empty one **clears** the last, so a roster cannot outlive the run
  that found it — shown on the node's own page and **never** on a card. Never a
  status claim: anything that should alarm is a reason, and what separates the two
  is status rather than volume (a list whose items each carry a verdict is entries;
  a list whose items carry none is scope).
- `about: str` — the node's **short account**: where the thing stands, how to reach it
  and what to do, distinct from `description` (what its check reads or checks, in a
  sentence); Markdown, seeded at startup from `nodes.yaml` / the owning check
  ([ADR-0012](adr/0012-node-metadata.md),
  [ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)).
- `title: str` — a **short display label**, briefer than `about`; same sources and
  seeding ([ADR-0017](adr/0017-node-title.md)).
- `handbook: str` — what a team writes **at length** about the node, read on its own
  *Handbook* tab; a label on the same sources, filled once (§4.5,
  [ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 3).
- `type_details`, `named_details`, `declared_details` — the node's **details** in three
  parts by who gives them (§4.5, ADR-0133 decision 6), each key and its line of Markdown
  in order: what the type gave its object with the last run, written through like
  `description`; what the deployment gives the node's name under its check's
  `subnodes:` block, written by the engine as it writes the node; and what the
  deployment declares for its path, seeded at startup. The deployment's two hold for
  every node beneath; the snapshot and `StatusTree.details` put the three together.
- `named_tags` — the tags the deployment gives the node's name under its check's
  `subnodes:` block (§4.5, ADR-0139 decision 2), written by the engine as it writes the
  node, as its named details are; those written for its path are the tree's, by path
  (`StatusTree.use_tags`), and both hold for every node beneath, added up.
- `maintenance: bool` — the **marker** that an admin pin is on this node
  ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 4;
  [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)). It does not change
  what is stored: the pin is a contribution rule the snapshot applies (rule 3), so the
  check keeps writing and the node keeps its real reading underneath.
- `__children: OrderedDict[str, Status]` — keyed by child `name`.

Methods: `update(code, reason)` (record an observation), `touch()` (re-stamp only),
`add_child(child)` (enforces `parent_path(child.path) == self.path`),
`get_children()`, and `get_status_code()` (§4.3). Code/reason coercion is factored
into `_coerce_code` / `_coerce_reason`.

### 4.3 Aggregation (roll-up)

**A node has two kinds of child, and they grade by one rule.** The real ones are in
`__children`. The **virtual** ones are its own member reasons: a node whose `members`
is true is not carrying one condition in several paragraphs, it is carrying a set of
reasons, and each of those is a child the tree does not hold
([ADR-0036](adr/0036-addressable-reasons.md) decision 7; the
[ADR-0032](adr/0032-status-contribution-boundary.md)). A virtual child has
the two things grading needs and the one thing a person needs: an **identifier** (its
slug — declared via `slug(*parts)`, or content-hashed to `h-` plus ten hex digits of
its SHA-1 when the check has nothing better than its own wording), a **code of its
own** where the check declared one
([ADR-0042](adr/0042-entries-carry-their-own-code.md)), and — through the
`(path, slug)` side table — its own **pin**, so one line of a node can be put in
maintenance without the node.

**A pin holds an identifier, and only a reason has one.** That is why maintenance is
per line and never per anything coarser, and it is worth saying before the next
paragraph introduces something coarser.

**What a reason is *about* is a subject, and a subject is not a child.** Several
reasons commonly share one — a repository with a failed build *and* a run awaiting
approval has two coded lines under one `actions` aspect — and reading *how is that
repository doing* means taking the worst of their codes.

Grouping is free, but only under one rule. The **ranking** is associative: `worst_of`
answers the same however it is bracketed. `derive_code`'s **fallbacks** are not — it
answers `OK` when nothing was counted, so a subject that folded its reasons with
`derive_code` and handed the result up would turn a node's `UNDEFINED` into a green
one. So: **a subject with no coded reason contributes nothing**, exactly as an uncoded
reason does; with that, a node grades identically whether its reasons are folded
directly or through their subjects. (`worst_of` ranks three codes and raises on the
rest, so any subject reading filters before it folds, as `derive_code` already does.)
Where the check declared no codes at all and the node carries one — a severity band —
there is nothing to fold, and every subject under it reads the band's code.

A subject is a **lens**: no slug, so nothing pins it; no storage, so nothing holds it;
no contribution of its own, since its reasons already contribute. It is not even
recoverable from the data. A declared slug is built from identifiers the provider
minted rather than from rendered text
([ADR-0050](adr/0050-slugs-from-provider-identifiers.md)) and by convention names the
subject first — `slug(repository, "pr", 42)` — but the parts are joined with `-` and
`-` is legal *inside* a part, so a subject cannot be parsed back out of a slug.
Grouping by subject would need a check to carry it explicitly; nothing does today, and
grading never has to.

The construction exists because a check whose subjects are discovered at run time —
every open pull request across forty repositories, every alert a scanner reports —
would otherwise have to choose between a node per subject, which is a tree nobody reads
([ADR-0043](adr/0043-coverage-backstop.md) rejected exactly that), and a paragraph per
subject, which nothing can address, grade or pin. The virtual child is the third
answer: an identifier per line without a path per line. A check that has subjects hands
over reasons and lets its node's code be **derived**; a check with one condition to
describe hands over prose and declares its code. Declaring a code *and* handing over
coded reasons is refused (`CheckError`), because then two things would grade the same
node.

**Presence is the check's choice, not a signal.** A reason set may report every subject
it looked at — `github-rate-limit` gives one line per API budget, healthy ones
included — or only the ones worth acting on, which is the habit of `github`'s aspects
and is a habit rather than a rule (its `actions` aspect carries a `show_healthy` switch
for the opposite). What no reader may do is take an absent line for good news: that an
unwatched scope must not look like a clean one is the coverage backstop's whole job
([ADR-0043](adr/0043-coverage-backstop.md)).

The folding happens **twice**, and the two folds are not the same function.
`derive_code` (`reasons.py`) runs at the check boundary, over the entries' own codes
alone: an entry that declares none contributes nothing, and pins never reach it.
`_own_code` (`tree.py`) runs at snapshot time with the contribution rules joined in,
so there an uncoded entry contributes the node's reported code and a pinned one is
skipped as `MAINTENANCE` (§4.4). What both do alike — and it is the part that matters
here — is **ignore `UNDEFINED`**, exactly as the roll-up over real children does.

What a virtual child does **not** have is a clock or a history of its own: freshness,
staleness (§4.4) and the event log are all node-grained, and an entry inherits its
node's `timestamp`. So a node written every run looks equally fresh in every line,
whatever each line's reading is actually based on — the standing constraint on any
check that would report some subjects from this run and others from an earlier one.

`get_status_code()` rolls a node's effective status up from itself and its children
per [ADR-0039](adr/0039-status-rollup-semantics.md), which is `status.effective_code`
applied recursively:

```python
if own == StatusCode.MAINTENANCE:
    return StatusCode.MAINTENANCE          # subtree canceled; parent ignores it
counted, silenced = [], False
if own != StatusCode.UNDEFINED:
    counted.append(own)
for c in child_codes:
    if c == StatusCode.MAINTENANCE:
        silenced = True                    # skipped, but remembered
        continue
    if c == StatusCode.UNDEFINED:
        continue                           # ignored when accumulating
    counted.append(c)
if counted:
    return worst_of(counted)
return StatusCode.MAINTENANCE if silenced else StatusCode.UNDEFINED
```

Severity is `ERROR > WARN > OK`; it always returns a `StatusCode`; `UNDEFINED`
(a not-yet-reported leaf) is ignored; `MAINTENANCE` cancels its subtree and is
ignored by its parent. **With nothing counted, the answer depends on why**
([ADR-0039](adr/0039-status-rollup-semantics.md) rule 5): children skipped because
they are *in maintenance* leave the parent `MAINTENANCE`, children that merely have not
reported leave it `UNDEFINED`. That is the edge case
[ADR-0032](adr/0032-status-contribution-boundary.md) left open, answered
the way the same model already answers it one level down — a node whose *virtual*
children are all pinned reads `MAINTENANCE`
([ADR-0036](adr/0036-addressable-reasons.md)) — because real and virtual children
must not read differently in one model.

This walk reads **stored** readings only. What a node *shows*, with pins and every
other contribution rule applied, is `StatusTree.effective` / the snapshot's `code`
([ADR-0032](adr/0032-status-contribution-boundary.md) rule 3; §4.4). Two other
records split off with this one: what a **failing check** becomes is
[ADR-0040](adr/0040-what-a-failing-check-becomes.md) (§4.6), and what an admin pin
does is [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md).

**Whose a status is, the snapshot says**
([ADR-0123](adr/0123-a-node-says-one-status-wherever-it-is-read.md) decision 2). What
a node counts for itself in what it rolls up to is its own status — or, where its own
reading is stale, what its check reported, degraded (§4.4): `_counts_for_itself` in
`tree.py`, the expression the snapshot rolls every node up with, which
`StatusSnapshot.own_counted` reads again off the snapshot's own fields. `derived` says
that what the node shows is not that, and so comes from beneath it; `counts_beneath`
says that the node counts nodes beneath it at all — it has some, and what it counts for
itself does not cancel them. A pin on the node and its check's word for it do; lines
that are all in maintenance do not: they count nothing and cancel nothing, so the node
shows what the nodes beneath it roll up to, and reads `MAINTENANCE` whole only where
nothing beneath it counts either
([ADR-0124](adr/0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)).
`_cancels_beneath` says which, once, for the roll-up (`_rolls_up`) and for the
snapshot, whose `lines_silenced` names the case for a surface that says where what a
node shows comes from. A surface that draws a node pale, or names a period as the
node's own, reads these and compares no two codes itself: `own_code` beside `code`
reads a stale reading of the node's own as a color from beneath it.

### 4.4 Status tree, event log & history — `tree.py`
The single in-memory state everything hangs off (ADR-0001/0002). `StatusTree`
holds one root `Status` and a bounded `deque` of `Event`s behind one `RLock`.

- **Every time the tree stores is an instant**
  ([ADR-0120](adr/0120-every-stored-time-is-an-instant.md)): a node's `timestamp`, an
  event's, a `Beginning`'s `at`, a pin's `set_at`, `created_at` and `expires_at`, and
  what is derived from them — a period's two ends, the stamp a snapshot publishes, a
  run's `next_run_at`, the stop's stamp. Each is a `datetime` that knows its zone, held
  in UTC. What holds one takes it through `instants.utc` where it is built, which
  refuses a time without a zone; a node is stamped by the clock, `instants.now`, alone;
  and the moment a method takes as `now=` is an instant, refused without a zone. Every
  comparison — a pin's expiry, a node's age, which period began first — is made on
  instants, so it is the same on every machine and through a change of its clock.
  `events.json.gz` and `pins.json` spell a time through `instants.stamp`, in UTC
  with a `Z`, and read it back through `instants.instant`: a file in which one time has
  no zone is refused whole, which is a load failure the layer reports (§4.8) — every
  file the versions before that record wrote, which nothing migrates.
- `upsert(path, code, reason, *, description=None, frequency_seconds=None,
  stale_after=None, config=None)` — create-or-update a node by absolute path (intermediate nodes
  auto-created), store the inherited metadata, and append a transition `Event`
  **only when the node's own code changes**. `config` is static display metadata
  (the check's parameters, [ADR-0013](adr/0013-check-config-on-node.md)) — stored
  when given, never a transition. A node **in maintenance** is written like any
  other — the pin is derived at snapshot time, not stamped into the tree, so a
  node in maintenance can still say what it holds and clearing a pin restores the
  last known state at once rather than at the next run. It is also the one path
  that writes entries, so it keeps **`entry_count`** — how many reason entries the
  nodes hold between them — as a counter, and the engine's tick reads a number
  rather than walking the tree (§4.6).
- `set_check_mount(path)` — register a **check mount**: the node a check writes its
  result root to, and so re-stamps on every run. A registry only — it creates no
  node, so the tree's visible shape still grows only with results — read solely by
  the timestamp roll-up in `snapshot()` below. The engine seeds it at construction
  from its checks (§4.6), which keeps the tree itself check-agnostic. It **counts
  checks per path** ([ADR-0027](adr/0027-observation-timestamp-semantics.md) as
  amended by [ADR-0044](adr/0044-run-facts-on-the-node.md)): two checks sharing one
  mount count as two, so an unwritten ancestor above them inherits **no** stamp —
  the shared node's own last write answers for itself, but attributed upward it
  would present one check's run time as both checks' data.
- `note_named_by_run(path, named)` / `named_by_run(path)` — whether the run that wrote a
  node named it, `dynamic`
  ([ADR-0118](adr/0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)),
  kept as the engine writes each node, since such a node takes nothing declared for its
  name and only its parent's `children:`
  ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)): the claim and the first
  look read it. A registry like the mounts, off the nodes, so the snapshot stays
  provenance-free and the envelope does not grow
  ([ADR-0025](adr/0025-check-provided-subnode-metadata.md),
  [ADR-0080](adr/0080-the-envelope-is-the-snapshot-published.md)); it starts empty after
  a restart, so no node is read as named before its run has said, and a node a run
  removes leaves it.
- `set_run_facts(path, *, wall_seconds, next_run_at)` — record the owning check's
  **last-run facts** for a mount ([ADR-0044](adr/0044-run-facts-on-the-node.md)):
  the run's wall time, and the engine's **armed next slot** already projected onto
  the wall clock. A registry beside the mount counts, resolved by `snapshot()`
  onto `StatusSnapshot.run` under the same sole-check condition as the inherited
  stamp — the sole mount and the unwritten ancestors above it carry the facts, a
  mount two checks share and its ancestors carry none, and a leaf *below* a
  branch mount stays bare: its next update belongs to the node where the check is
  named — unless a **unit** of the check answers for it
  ([ADR-0130](adr/0130-a-unit-has-a-period-of-its-own.md) decision 5): the engine
  sets facts for the unit's own node and for every container between it and the
  mount, and a node with facts of its own publishes them, whatever its subtree
  counts, except a mount two checks share. `next_run_at` must come from the
  schedule, never `timestamp + frequency` — the budgeted retry
  ([ADR-0033](adr/0033-budgeted-failure-retry.md)) pulls the slot in exactly when
  someone is watching a failure. Web-only until the client contract round, like
  `reported_code` before it.
- **The owning check's own text answers to the same rule** — one rule over four
  facts ([ADR-0044](adr/0044-run-facts-on-the-node.md) decision 1). `snapshot()`
  publishes `config` and `report` as `""` on a node **two or more checks mount**:
  two writers give the field no single answer, and a value flipping between them
  is worse than none. The condition is the node's **own** mount count, so a child
  *below* a shared container keeps its own per-child text — which is exactly where
  that shape's checks are told to put it. Withheld, not destroyed: the tree keeps
  what was written, and dropping back to one owner makes it answer again.
- `set_entry_maintenance(path, slug, reason, *, expires_at, set_by,
  expected_set_at)` / `clear_entry_maintenance(path, slug, *, expected_set_at)` —
  the same pin one key deeper, on **one reason** of a node
  ([ADR-0036](adr/0036-addressable-reasons.md)). It writes no status: the pin lives
  in the side-table under `(path, slug)` and the snapshot joins
  it, so the check's next run cannot destroy it and nothing derived is written into
  the tree ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 3). **It is an
  event where it changes what the node shows**, set, cleared or expired — the one
  failing line pinned turns the node green — and none where the node shows what it
  showed ([ADR-0107](adr/0107-an-event-is-a-change-of-what-a-node-shows.md) decision
  1). A slug the
  current run did not report is **suspended, not deleted** — a failed check replaces
  its whole reason map, so delete-on-absence would discard every pin on a bad
  minute; only expiry disposes of one.
- `set_maintenance(path, reason, *, expires_at, set_by, expected_set_at)` /
  `clear_maintenance(path, *, expected_set_at)`
  — the admin override: set records a pin until `expires_at`, noting who set it, and
  the node reads `MAINTENANCE` from then on; clear drops the record and the node is
  back to whatever its check last said, at once. The pin is **recorded, never
  written** ([ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md);
  [ADR-0032](adr/0032-status-contribution-boundary.md) rule 3) — the check keeps
  writing underneath it and the snapshot derives the status — which is what makes a
  node in maintenance able to say *what* it holds, and clearing able to restore
  anything at all. Setting an **already-pinned** node is an *edit*: it keeps the entry's
  `created_at` / `created_by` and replaces the rest, so extending a window never
  passes through an unpinned state. Both record events — including the edit, which is
  `MAINTENANCE → MAINTENANCE` and so invisible to the code test — written from and to
  **what the node shows**, which with a line pinned is not what its check reports
  (ADR-0107 decision 1). A set that says what
  the stored pin says — the same reason, the same expiry — **changes nothing and writes
  nothing** ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md)): no event,
  no file, and the entry keeps its `set_at` and `set_by`, which so mean the last write
  that changed it. `expected_set_at` is the **compare-and-set
  token** (the `set_at` the caller believes it is replacing, as it is spelled —
  `Pin.token` — `""` for *"nothing is pinned"*, `None` for unguarded): on
  a mismatch **nothing is written** and the returned
  `PinWrite` carries `refused` plus the entry that was actually there; it is
  asked before anything is compared, so a stale token is refused whatever the set says.
  The comparison is exact — one process, one lock. `Pin.note` is the
  admin-authored raw Markdown source shown on every maintenance surface (§4.7).
  Maintenance is held in a **side-table**
  (`path → Pin`, a pin of kind `maintenance`: `{note, set_at, expires_at, set_by,
  created_at, created_by, id}`) kept in sync with each node's `maintenance` bool and
  **written through** to `var/state/pins.json` via an injected `PinStore`, which knows
  the file's shape — one list of every pin, each beside its path and, for a line's, its
  slug — and hands the write to the state layer (§4.8;
  [ADR-0014](adr/0014-maintenance-persistence.md),
  [ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md),
  [ADR-0141](adr/0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)); an entry that names no creation was created when it was set, by
  whoever set it, and its `id`, made when it is first set, an edit keeps.
  `restore_maintenance` replays it
  post-fork at startup (dropping expired); `reap_uncovered` drops pins that neither a
  check root nor the instance's own covers (segment-wise — the `status.on_same_line`
  predicate shared with ADR-0015);
  and `sweep_expired`, run each scheduler tick, clears entries past their window as a
  real transition — every pin it finds run out, a node's and a line's alike, in one
  write (below).
- `set_acknowledgment(path, slug, kind, note, *, expires_at, set_by,
  expected_set_at)` / `set_acknowledgments(parts, kind, note, *, expires_at, set_by)`
  / `clear_acknowledgment(path, slug, *, expected_set_at)` — **a failure a person
  accepted as it stands**, *seen* ([ADR-0142](adr/0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)): a pin of an
  acknowledgment's kind on a node's own failure or on one of its lines, held in two
  side-tables of its own beside the pins' (`_acknowledged`, `_entry_acknowledged`) and
  written through with them, its compare-and-set token the pins'. A new one is taken
  only where its part fails now (`acknowledgeable`), bound to the status it read and, a
  line's, to its occurrence (`Entry.occurrence`). It writes no status either: the
  snapshot counts a line it stands on as OK in its node's own status, through
  `ACCEPTED`, and a node's own part as OK in what the node passes up, `contribution.by`
  `seen`, its true color kept. `upsert` asks each reading whether it ends what stands on
  its node (`_ended_by`) — a recovery, a worsening, another occurrence, a part no longer
  reported — each end a row naming why (`Event.ended`); `sweep_expired`,
  `reap_uncovered` and `prune` end theirs too, and `restore_acknowledgments` and
  `adopt_acknowledgments` replay and adopt them as the pins are.
  `acknowledgeable_parts(snapshot)` lists what a head's ringed check marks, each part
  its own, and `parts_digest` the digest its editor carries back.
- **A pin is held against a path, and makes no node**
  ([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md) decision 4).
  `set_maintenance`, the replay at a start and an adopted table record the entry and pin
  the node the tree holds at the path; where it holds none, none is made. `_furnish`
  gives every node the tree makes what is held against its path — the pin, and the
  labels the configuration declared for it, which `set_about` and its siblings keep in
  `_seeded` — so a node a check writes for the first time, or again after it was
  removed, is pinned and labeled from its first reading. A pin without a node holds
  nothing, and its rows are written all the same, as a node's pin always is (ADR-0107
  decision 1), against what is kept of the path (`_shows_at`, `_emit_at`). A node not
  written yet since the start shows what the kept table says it last showed, so its pin
  is set and ended there as on the node. A path whose node was removed shows nothing,
  and a pin on it is **suspended**: its set, its edit and its end are rows from nothing
  to nothing, a replay writes none, and it dates no period. `pins()` hands out both
  tables whole, the pins no node stands for among them, which *Handled* lists
  (§5.1).
- `prune(path, keep, *, protect=())` — **what a run no longer reports is removed**
  ([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md)). Every direct child of
  the node at `path` that `keep` does not name leaves the tree with its subtree, unless
  it lies on the line of a path in `protect` — the nodes the other checks own, which the
  engine hands in (§4.6) — and nothing beneath a child that is kept is looked at. The
  node goes, and nothing kept about it does: its lines leave `entry_count` and its wait
  is forgotten, while a pin against it, or against one of its lines, stays in the side
  table, and its readings are its check's (§4.10). **Each node removed writes a row**
  (decision 5): from what it showed to `UNDEFINED`, by the cause `removed`, its reason
  *no longer reported by its check*, every row of one call at one instant and a node's
  children before it. A node a check wrote that showed nothing has its row too; one no
  check ever wrote — a label its deployment declared, a container made on the way to
  another node — leaves without one. **The first run after a restart writes the same
  rows**: the tree starts empty, so a path the kept table says showed something, beneath
  the node through a child that is not kept, is ended by its row as if its node had
  stood there, and an entry that says its node showed nothing is dropped without one.
  **What is kept of a removed node says that it shows nothing since its removal** — its
  entry in the table, the removal as the beginning of that period — so its return is a
  change the tree saw, across a restart too, and a replayed pin reads from it that it is
  suspended. `_forget_removed`, at each save, drops the entry once the log no longer
  holds the removal's row, unless a pin is held against the path: a deployment whose
  subjects come and go carries none of them for good, and a node that returns after that
  is seen for the first time.
- **The event log is a state file too.** `events_payload()` copies the log under the
  lock and serializes it outside; `restore_events(events)` puts a file's log back at
  startup, before anything has written, keeping the bound. `Event.to_dict()` /
  `from_dict()` carry the codes by name — an event's `cause` and what its check
  `reported` as keys only where the event says them, so one read from a log written
  before them is written back as it was (ADR-0107 decision 6) — and
  `events_from_payload()` refuses a file
  of a shape it does not know whole rather than half-reading it — the layer then
  reports the file (§4.8). A restored log makes `/events` and every node's history
  start where the last process left off. **Beside its rows the file says what every
  node last showed**
  ([ADR-0110](adr/0110-what-every-node-last-showed-is-kept-beside-the-log.md)): a
  `nodes` table, per path what the node `shows` and what its check last `reported`, by
  name, and when the period it is in began (decision 5): `since`, with `was` and
  `cause` as the row that began it said them, or `since` and `before` where the instant
  is a bound — a `LastShown` with its `Beginning`. An entry of a node that waits
  before it escalates says also what the node `publishes` meanwhile
  ([ADR-0119](adr/0119-a-wait-that-ends-by-its-count-writes-a-row.md) decision 4).
  **A branch's entry keeps the period of what it shows** under `period`
  ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)):
  `code`, then `since` and either `before` or `was` and `cause`, then `by` — a
  `Period`, written by `Period.to_dict` and read by `_period_of`. The root's entry and a
  container's hold it alone beside their two codes, `UNDEFINED`, since a release before
  requires both of every entry and reads only the keys it knows: a rollback restores
  the file, which `tests/test_branch_period_kept.py` proves in every run with the
  release before's own code, taken from its tag (`tests/release_before_reader.py`).
  `events_payload()` takes it from `_last_shown()` under the lock that copies the rows —
  the tree's own derivation for a node a check has written in this process, what was
  restored for one it has not, and no entry where both codes are `UNDEFINED` and the
  tree did not see that begin, but for a branch's period — and the codes, a beginning
  and what a waiting node publishes change only with a row, so the table costs no
  write of its own; the exceptions are a wait that ends behind a shield, which writes
  no row, and a branch's period, which a reading gone stale moves.
  `nodes_from_payload()` reads it back, refusing one it cannot read whole, and
  answers `None` for a file written before it. **A restart is no transition**
  ([ADR-0094](adr/0094-a-restart-is-no-transition.md)): `restore_events(events, nodes)`
  keeps per path what the node last showed and what its check last reported — from the
  table, which names every node however long ago it last moved; or, for a file without
  one, from each node's last row (`_last_readings`), where what a check reported is
  worked out from the codes of a log written before an event could say it, and a node
  without a row has nothing kept — and a node's **first** write in this process is
  compared with both rather than with the `UNDEFINED` a restart leaves (ADR-0107
  decision 5). The same reading keeps its period, and whatever differs is written
  then: the node's change, and the reading's where the node does not show it. A pin
  that ran out while the instance was down ends at that reading, as its cause where
  the node would still show what it showed had the pin held; a branch's, which no
  reading will end, is written by `restore_maintenance` at the pin's own expiry. The
  pins' replay compares with what the node last showed, and a pin whose
  period the log holds writes nothing. What was restored of a node that no configured
  check covers is dropped at startup, as such a pin is reaped: `forget_uncovered(roots)`
  keeps the entries on a root's line, a branch's period going with its entry, and
  `_restore_state` hands it the checks' roots and the instance's own (ADR-0110
  decision 4). The instance's own node records the gap
  instead, once: `close_unobserved(path, since, reason)` ends `/little-sister`'s
  restored period with an event to `UNDEFINED`, dated when the old process was last
  alive — `last_alive`, the later of the `stopped_at` the stop's one save writes beside
  the events (`note_stop`, §4.6; `stopped_at_of` reads it back) and the lease's
  `previous_beat` (§4.8) — so its first beat is a transition from there and its
  history reads the time nothing watched.
- **The tree keeps when each node's period began**, in `_beginnings`, a `Beginning` per
  path (ADR-0110 decision 5): the log is bounded, and a period's first row leaves it.
  `_log`, the one place a row is appended, keeps the beginning of the period the row
  begins — a row that changes what its node shows, and neither an edit of a pin nor a
  row a pin hid. `_settle_period`, at a node's first write in a process, makes a first
  sight a **bound** at that reading, since the node was already what it shows
  ([ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md) decision 9) —
  except beneath a branch the engine named with `set_process_branch`, the instance's
  own, which begins with its process; a node that shows nothing has no status to bound.
  `restore_events` puts the beginnings back (`_restore_beginnings`): an entry's keys at
  their word; for a file written before them, the first row of the node's last period
  (`_beginning_of_run`, which reads a first reading's row and an edit's as bounds); and
  where neither says, the log's oldest event — the node's first write, where the log is
  empty — taken once and kept until the node changes. **A pin the tree did not see set
  begins at its creation** (decision 6), which the store keeps: `_date_pin`, for a pin
  that `restore_maintenance` replays or `adopt_maintenance` brings, dates the node's
  period by the entry's `created_at`, whatever instant the row written then carries, and
  a kept beginning later than that gives way to it; `set_maintenance` hands its write's
  one instant to the row, so a pin the tree sees set is dated as the store dates it. An
  adopted file's beginning is taken for a node no check has written yet, and for a
  written one where the file says it shows what it shows; `forget_uncovered` drops a
  beginning with the two codes.
- **A branch keeps the period of what it shows**, in `_periods`, a `Period` per node
  above others — the root included, and a node that declares nothing of its own
  ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)):
  `code`, what it rolls up to, staleness included; `began`, a `Beginning` in the words
  of a node's own; and `by`, the node whose change began it. `period(path)` reads it; a
  leaf has none, its one period being its own, and no row is written for it (decision
  1). **It is compared at every write and on every tick.** A write is `_one_write`: the
  instant it took and what every node was then (`_Write`), and at its end every branch
  above a node whose **own part** it moved — what the node counts for itself, the shield
  on it, what a wait publishes for it (`_own_part`) — is weighed, and keeps a new period
  where it rolls up to another code (`_compare`, `_weigh`). What every node is comes
  from `_parts`, the snapshot's own derivation (`_derive`, `_shields_over`) over the
  tree and the nodes a restart carries. **A run's store is one write** (decision 2,
  [ADR-0002](adr/0002-rlock-snapshot-synchronization.md)): `storing(answers_for)` holds
  the lock from the run's first write to its last, each upsert and prune re-entering
  it, so every node and row the run writes takes its one instant and no reader sees half
  of it (§4.6). Outside a run each writer is one write — a reading written alone, a pin
  set, edited or ended, a node `forget_uncovered` drops — and the pins `sweep_expired`
  finds run out, a node's and a line's alike, are one write together, so a branch whose
  pinned children both end at 18:00 never reads what one of them shows alone. **Time
  moves a branch too**: `_catch_up`, as a write begins and at the tick's
  `compare_periods`, compares each moment a node written in this process went stale
  since the last comparison — its last observation and its tolerance after it — as one
  change by the cause *stale*, so a branch orange from a silent leaf says *warn since
  10:45*, and a shield that ended with its dependency's silence is dated there.
  `compare_periods` then sets every branch against its kept period (`_settle`): a
  difference no change explains begins a period at the tick with no cause and no `by` —
  after an adopted file (ADR-0077) what its entries moved, and anywhere else a change
  the bookkeeping missed, which the log says at WARN. **`by`** (decision 4, `_by`) is
  the first node in the order the tree draws, of those the change moved at or beneath
  the branch, that answers for the new period: where the branch shows a worse failure —
  warn or error after ok, maintenance or undefined, or error after warn — one that now
  counts the new code for itself (`_makers`); where it shows less, one that counted the
  old code for itself; otherwise the first whose own part moved; and a node only a
  shield moved stands for its dependency, which need not stand beneath the branch. The
  `cause` is that node's row's (`_cause_in`), *reading* where it moved without one. A
  branch first seen showing a status is a bound there, except the instance's own, which
  begins with its process (`_first_period`); a node that comes to stand above others
  takes its own period (`_inherited`); and a branch its check removed keeps *undefined*
  since its removal, by itself, so that its return is a change the tree saw. **A restart
  carries the entries** (decision 3): a node no check has written in this process counts
  at its kept entry, not weighed stale, until a stored run has answered for it or a node
  above it (`_ran`, `_carries`, `_carried`), and each branch's period comes back with
  its entry (`_restore_periods`) and goes on from it until the units beneath it have
  run. The tick passes over a branch above a node still carried (`_Part.carrying`), a
  write that leaves such a branch's roll-up as it was leaves its period, and a node's
  carry ending is a move of it (`_carry_ended`): so a period a reading gone stale made,
  which the entries cannot say, ends at that node's first reading, by it. On the first
  start on a file written before the key, `restore_events` seeds every branch's period
  from the log instead (`_seed_periods`) — the rows replayed through the roll-up, one
  instant's rows as one change (`_replayed`), and a bound at the log's oldest row where
  they say nothing. An adopted file's periods are merged in (ADR-0077): the holder's
  replaces this process's where the file keeps one, and this process's stays where it
  keeps none, which is every branch of a file written before the key. **History
  derives the periods that ended** (decision 6, `shown_history`): the rows at and
  beneath the branch, and of each dependency a shield there is reached through
  (`_scope_of`), replayed as the seed replays them with the branch watched, the oldest
  a bound at the log's oldest row; one the rows say began after the period that holds
  began is none of the branch's — staleness writes no row — and the last before it
  ends where that one began. What it reads — the rows, the entries, the beginnings and
  the dependencies — is copied under the lock and replayed outside it, as
  `events_payload` copies the log and serializes it outside
  ([ADR-0002](adr/0002-rlock-snapshot-synchronization.md)).
  **What it costs**: the tree rolled up twice at every write, under the lock — about
  1.2 ms on a tree of 165 nodes, about 5 ms at 550 — and nothing left for the cycle
  collector, since no closure of the tree calls itself: a closure that reaches itself
  is a reference cycle, which would hold each roll-up's parts until the collector ran,
  about once a tick. On one deployment's kept log (162 entries, 1,000 rows), beside
  0.3.21 taken from its tag: a tick 1.8 ms; 0.4 MiB more at rest, a bare interpreter
  holding the tree settling at 25.9 MiB beside 25.5 with 0.3.21's; the first start on
  the release, whose seed replays the log, 0.4 s with a peak of 0.3 MiB; a later
  start, which reads the kept periods, no time to measure; a History view of a branch,
  22 to 47 ms, of which the lock is held 0.1 ms.
- **An event is a change of what a node shows**
  ([ADR-0107](adr/0107-an-event-is-a-change-of-what-a-node-shows.md)): its `old` and
  `new` are the node's own status before and after, as `_own_code` derives it from
  the reading, the node's pin and its lines' pins — one derivation for the snapshot,
  the log and the counter below (`StatusTree._own`). Every writer goes through it: a
  reading (`_record_reading`), a node's pin, set, edited or ended, and a line's pin
  set, cleared, expired, reaped or adopted, which is an event only where the node
  shows something else for it. A node that leaves the tree is the one writer beside
  them: `prune` writes its row, from what it showed to nothing. And one row is no
  change of what its node shows: **the reading that ends a wait by its count writes
  that the status reached**
  ([ADR-0119](adr/0119-a-wait-that-ends-by-its-count-writes-a-row.md)) — the status as
  both its codes, unmarked, by `CAUSE_REACHED`, beginning no period and counted as no
  change. An event carries its `cause`, one of the `CAUSE_` words, and what its check
  `reported` at that moment. **A change of the reading that the node does not show is a
  row of its own**, with the reading's codes and the mark below; one run writes both
  rows where it changes what the node shows and, differently, what its check reports.
- **Events under a suppression are recorded and marked.** Because a pinned node keeps
  being written, its transitions still happen, and the log keeps all of them: an `Event`
  carries `suppressed_by`, the **name of the contribution rule** that kept that
  transition from reaching anybody, empty when nothing did. One sentence defines it —
  *an unmarked event is one that alarmed; a marked one is one that didn't* — and it is a
  name rather than a boolean because the aggregation clamp, the dependency shield and
  the damping counter each withhold a transition too, and four booleans would be four
  spellings of one property ([ADR-0032](adr/0032-status-contribution-boundary.md)
  rules 2 and 5). Two rules **hide a reading**: `tree.MAINTENANCE_RULE`, at both grains
  of the same rule — a pin on the node, and a pin on a line — and
  `tree.AGGREGATION_RULE`, a configured rule on a node's lines that counts a line
  otherwise
  ([ADR-0137](adr/0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)). A
  row carries one for what it did — a change of the reading that the node did not show —
  whether one line is pinned or every one (ADR-0107 decision 2); where a pin and a
  configured rule both stand on the node, the rule's only where the pins alone would
  show the reading (`_hiding_rule`). A node whose *check* reported `MAINTENANCE` is not
  marked — nothing suppressed it, it said so itself. A pin's own set / clear / edit is
  never marked either, a line's as a node's: that transition **is** the change, and it
  is what everyone sees. A row the node showed carries a rule's name only where one
  keeps the change from the node's parent: a shield, an escalation that is still
  waiting, or a configured rule, which marks the rows of a write once the write is whole
  (`_mark_held`), since a rule on a node reads the roll-up and a count reads the node's
  siblings. Because `aggregation` names both kinds of row, an `Event` says which it is
  in `shown`, written into the kept log only where it differs from what the mark
  implies. Before the keystone none of this could exist — a pinned node was not written,
  so there was no transition to mark — and recording them is what makes *did it break
  during the window?* answerable
  ([ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)).
- `history(path)` — the node's **status history** as `StatusPeriod`s (code, since,
  until, reason, `previous`, what the node showed before it, and `before`, whether
  `since` is a bound), derived from the event log, with the beginning of the period that
  holds as the tree kept it (`_beginnings`): a node the log holds no row of still has
  its current period, and only one nothing is kept of has none. The period before it
  ends where that beginning says, and the current period's `until` is the last check
  time. **A period is a run of events that show the same status**
  ([ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md) decision
  6): an edit of a pin is an event and no period, so an edited pin is one period from
  its set. **A period's reason is what it said last** (decision 7): an ended one's is
  its last event's, and the one that holds says the stored pin's note under a pin — on a
  branch nothing writes too — and the node's own lines otherwise. `previous` is what a
  surface reads a beginning off: after `MAINTENANCE`, the period began where the node's
  maintenance ended. `before` says the instant is a bound and no beginning — a first
  reading, an edit whose set was lost, the log's oldest event (decisions 1 and 9) — and
  an earlier period whose first row is such a one says it too. **Marked transitions do
  not start a period**: history answers *what did this node show over time*, and a check
  that went red underneath a pin did not change what the node showed — it stayed in
  maintenance. Counting them would chop one window into a dozen phantom `ERROR` periods
  no surface ever displayed. They stay in the event log, which is where the other
  question is answered. **It answers for a node the tree holds.** A removed node has
  no history of its own until it returns; then its periods are there as far back as
  the log reaches, and the time it was away is a period of nothing between them, whose
  reason is the removal's (ADR-0109 decisions 3 and 5).
- **A node says how often it changed its mind lately** — `changes`, its own status
  transitions in the last hour between `OK`, `WARN` and `ERROR`, derived from the event
  log at snapshot time and stored nowhere
  ([ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md) decision 7). A first
  reading is not a change and is not counted; a transition a rule kept from alarming
  **is**, which is where this differs from the node's history — that answers *what did
  this node show*, this answers *how is the subject behaving*. So it counts the
  changes of what each event says the check reported: a row a pin caused is none, and
  a run that wrote two rows is one (ADR-0107 decision 4). It is the one number
  that says a subject is flapping, which the escalation counter deliberately cannot:
  every recovery clears that counter. On the node's page and in the envelope, never on
  a card.
- **A check may be reached *through* another**
  ([ADR-0084](adr/0084-a-check-may-be-reached-through-another.md)): `depends_on` names
  one check's path, the loader refuses an unknown target and any cycle, and the tree is
  told the graph as a registry — `set_dependency` and `dependents` —
  exactly as it is told a mount. Whether a shield is **in force** is derived per
  snapshot: while the dependency reports `ERROR`, the node keeps its own code and
  contributes nothing at all, its `OK` as much as its `ERROR`, because a reading taken
  through a broken path is no evidence either way. The mark sits at the check's mount;
  a never-reported or stale dependency does not shield, a stale dependent is not
  shielded (rule 6 again), and a dependency that is itself shielded does not shield on.
  Resolved once for the whole tree before the recursion, since a dependency may sit
  outside the subtree being rendered. The node's page names it and links it, the
  dependency's page counts what is reached through it, `/system` carries the graph, and
  the envelope publishes `shielded_by`.
- **A parent accumulates its children's `contribution`, not their `code`**
  ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 5,
  [ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md)). For a rule that
  *withholds* a node the contribution says so with a null code and the rule's name, for
  the envelope; what the parent then accumulates is `UNDEFINED`, which the roll-up
  skips. For a pin and an unreported node that is the node's own code and nothing had to
  be said — the roll-up reads the difference between those two — while a **shielded**
  node holds a ranked reading of its own and has to contribute `UNDEFINED` explicitly
  ([ADR-0084](adr/0084-a-check-may-be-reached-through-another.md) decision 3). A rule
  that *transforms* one puts a real code there instead, and two do — a configured rule,
  in the next item, and a **damping counter**, which holds a worse status back until the
  node has shown it for `escalate_after` readings in a row, and the node publishes what
  it published before while it waits. **It counts what the node shows** — its own
  status, and not the code its check reported, which with a line pinned is something
  else ([ADR-0108](adr/0108-the-wait-before-an-escalation-counts-what-a-node-shows.md))
  — so a pinned line's readings neither spend a wait nor restart one, and the hold a
  node states is about the status it shows. The counter is advanced on the **reading**,
  in `upsert`, and kept in a side-table beside the pins; the snapshot reads it and
  renders the hold (`1 of 3 to escalate`). The reading that completes the count writes
  the row that says the status reached, unless a shield holds the node back still
  (ADR-0119 decisions 1 and 2). The side-table is memory, and **a restart does not
  re-arm it**
  ([ADR-0110](adr/0110-what-every-node-last-showed-is-kept-beside-the-log.md)
  decision 1): a node's first write in a process seeds its counter with what the node
  last showed, as restored, so a failure a restart finds waits like any other and one
  that stood stays published. **A wait a stop interrupted goes on** (ADR-0119
  decision 5): the kept entry says what the waiting node published, and the count
  resumes with the reading its held row records as the first — the readings between that
  row and the stop are not kept, and a file written before the key reads every row held
  by the wait as an escalation made. A node nothing is kept of is published at once. **A
  change that a pin made is published at once**: `_emit` hands the counter the node's
  new status with every row whose cause is not a reading, so only a reading starts a
  wait, and a pin's end over a failure starts none. Staleness goes past it, because a
  stale node gives its parent its degraded **raw** code and never anything derived.
- **A configured rule is a table at one of three places**
  ([ADR-0137](adr/0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)).
  `aggregation.py` reads `config/aggregation.yaml` from every root at the start, the
  root named last first, refuses what cannot apply onto the startup record, and hands
  the tree a `RuleSet` (`StatusTree.use_aggregation`, before the state is restored),
  which answers per path, remembered, which rule decides a node's boundary (`boundary`),
  its children (`counting_children`) and its lines (`on_lines`), the first written
  deciding. A rule picks by `under:`, `tag:` or both
  ([ADR-0139](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision
  7): the set the tree takes is bound to what a path carries there (`RuleSet.bound`,
  `StatusTree._carried_tags`) and starts its answers over where that changes — the tags
  handed over, an aspect's written by a run or leaving with its node (`RuleSet.forget`),
  an answer worked out across a change given and not remembered — and a rule by a tag
  tops where the tag begins (`AggregationRule.tops`). The snapshot applies them in the
  order they compose: a rule on lines in the node's own status, a table beside each line
  (`_lines_ruled` → `_own_code`), so the node shows what its lines count as and each
  line keeps its code; then, after damping, a count over the children (`_counting`) and
  the node's boundary (`_through`), each mapping what its part would otherwise pass up,
  never below `WARN` for a part gone stale, and naming in `contribution.by` the first
  rule whose change the parent sees. Where each stands is a `RuleAt` — on the node
  (`rule`), over its children (`children_rule`), on it as one of its parent's children
  (`parent_rule`) and on each line (`ReasonLine.rule`) — what it reads, what it counts
  and whether that is a change, which every surface reads: the block, ◇'s *by a rule*,
  the budget and the healthy fold (`_acts`, `_lowers`, `ruled_beneath`), the *why* card
  and *Handled* (`rules_beneath`). The bookkeeping (`_evaluate`, `_replayed`) applies
  the same rules, so a branch's period is of what it counted, and a replay of the past —
  History's, a restart's — reads each rule from where it began: the start that brought
  it while a kept period says so (`_rule_starts`), and else the start of the day its
  `since:` names (`RuleSet.standing`, `day_begins`). A start that brings a rule begins
  the period of each branch it moves at that start (`_rules_began`, what the rules make
  of the kept entries against what the entries count without them), and the replay one
  it finds beginning inside the log: cause `rule` (`CAUSE_RULE`), `by` the node whose
  count the rule changed (`_rule_moved`), and its name (`Period.rule`,
  `_deciding_rule`), which History, the Copy document and the envelope say. A row a rule
  kept from a parent is marked `aggregation` where the rule makes the change count for
  less (`_mark_held`, `_counts_for_less`), and a reading a rule on lines kept from its
  node where the node shows less than either end of it (`_hiding_rule`, `_held_below`):
  a floor holds nothing back, and the reading it raised is a row of no rule's, which the
  Events page does not list (`_events_view`). A page that snapshots a node a count
  stands over takes it from its parent's snapshot, since the count reads its siblings.
- The snapshot derives a node's **own status** rather than copying its stored code
  ([ADR-0036](adr/0036-addressable-reasons.md);
  [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md); the
  [ADR-0032](adr/0032-status-contribution-boundary.md)): a **pin** on the
  node presents `MAINTENANCE`, and a node's member entries are **virtual children** —
  each unsuppressed one contributes its **own code** where the check declared one
  ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) and the reported status
  where it did not, a suppressed one contributes nothing (`UNDEFINED` contributions
  are ignored, as everywhere), and a node with nothing counted presents
  `MAINTENANCE` when something was in maintenance and `UNDEFINED` when nothing has
  reported — so pinning the one red line of an otherwise healthy coded set turns
  the node `OK`, and pinning every line turns its own status `MAINTENANCE`, which
  cancels nothing beneath it (§4.3). Prose and reason-less nodes stay outside the entry rule. What the check actually said survives beside the
  derivation as the snapshot's `reported_code`, so a card can say `maintenance ·
  error` and show the failure text under the pin's banner
  ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 5: a transformed
  contribution stays visible and attributable). Staleness judges the **raw** reading
  and is never suppressed, so a check that stopped running escalates whichever policy
  is holding its result back (rule 6) — a pin quiets a known state, it does not cover
  a dead check. This is the one transform that turns a stored reading into an own
  status, and both grains of maintenance now live inside it rather than beside it.
- `snapshot(path="", now=None)` — an immutable `StatusSnapshot` copied under the
  lock. It **orders siblings** by `(declared rank, name)` — the name half natural and
  case-insensitive, so `node2` precedes `node10` (`_sibling_key` over `_sort_key`) —
  at every level, so the dashboard and the JSON
  envelope read a deterministic order while the live tree keeps insertion order
  ([ADR-0055](adr/0055-sibling-order.md)). A rank nobody declared reads `0`, so an
  unranked set is plain alphabetical; a check states one on a `CheckResult` and a
  deployment overrules it from its own config, where a stated `0` is a declaration of
  the default rank rather than a request for alphabetical (§4.5).
  Ordering by the live grade is deliberately not offered — it would re-sort on every
  poll. It also computes **freshness** (ADR-0005):
  a node not observed within its **tolerance** is flagged `stale` and its `code` is
  degraded to at least `WARN` (worse-of, rolled up) — including a **pinned** node,
  whose reading is what staleness judges. `node_stale_after` resolves that tolerance
  in one place, for both the verdict and the number the snapshot publishes: the
  node's **stated** `stale_after` where there is one, and otherwise ~2× its
  `frequency` ([ADR-0079](adr/0079-freshness-is-a-stated-tolerance.md),
  [ADR-0081](adr/0081-an-instance-node-states-a-tolerance-not-a-period.md)). A node
  with neither can never be stale by its own stamp. The aggregation rule itself is the reusable
  `status.effective_code`. The same recursion resolves each node's published **`timestamp`**
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)), which exists only where
  *"when did the check behind this node run?"* has exactly one answer: a written node
  shows its own last write; an unwritten node above exactly **one** check mount shows
  that mount's; above two or more it is `None`, because any single value would
  attribute one check's run time to another check's data. Observation times are never
  aggregated — no min or max — and `age_seconds` deliberately keeps measuring the
  node's **own** stamp, so an inherited time is a display value and not an observation
  of that node. `stale` says that a reading is past its tolerance at the node **or
  beneath it**: a branch is stale while one of its nodes is, a node its check stopped
  returning among them for as long as it stays in the tree — which is until the node
  above it says that its children are complete (`prune`, above). `own_stale` says it of
  the node's own reading alone: `stale` is the alarm a card carries, and a surface that
  states a fact about this node's reading — a Copy document's *Stale* line, a branch's
  own line in its outline — reads the other. Resolution is relative to the snapshot's
  own subtree, and nothing derived is stored on the nodes, so a topology change can
  never leave a stale roll-up behind. **A node's two periods are on it**
  ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  decisions 3 and 7): `own_period`, the `Beginning` of the period of its own status —
  none on a node that declares nothing above nodes beneath it, its own code `UNDEFINED`,
  whether it never declared or has stopped, since it has no status of its own for a
  period to name — and `period`, the period of what it shows where it stands above
  others — only where that is of the snapshot's `code`. After a restart, until the units
  beneath it have run, and for the moment between a reading gone stale and the tick that
  dates it, the period the tree keeps is of another code; the snapshot carries none
  then, so no surface says it, decided here once. The envelope publishes both beside the
  codes they are of, `own_period` beside `own` and `period` beside `code` with no code
  of its own, each absent where there is none (2.9.0, `api._period`).
- `effective(path)` is **what the node shows** — it reads the snapshot's `code`, so
  every contribution rule applies ([ADR-0032](adr/0032-status-contribution-boundary.md)
  names that field for exactly this). `Status.get_status_code` (§4.3) is the pure
  roll-up over stored readings beneath it; before the keystone the two agreed by
  construction, and the distinction only became a real one when a pin stopped being
  written. `recent_events(limit)` reads the log, marks and all.

A module-level singleton `status_tree` is the one shared instance: the engine
writes to it, the web layer reads snapshots from it. `StatusSnapshot`, `Event` and
`StatusPeriod` are frozen dataclasses.

### 4.5 Checks — `checks/` package
A check run is **two steps** ([ADR-0086](adr/0086-a-check-measures-and-grades.md)).
`measure()` reads the world and hands back a `Measurement` — a `record`, the
`subject` it was taken on and either the `identity` of the event it is of, where the
source keeps a history, or the `state` the object is in (§4.10) — or a sequence of
them where the run reads several
objects; `grade(measurements, now)` turns those records into the codes and the
texts. What a check may reach for in the second half is the record, the fields its
type parsed at construction, and the `now` it is **given**: a later phase grades
old records out of a series when the process that took them is gone, so a grading
that leaned on anything else would answer something quietly wrong rather than
fail. The `record` is validated exactly as a line's is (below), and it is not the
check's working state — the raw answer stays inside the check.

The **object** is declared by the check, at construction, out of its own
configuration (a `url`, a `host`); a measurement names one only where the check
learned it from the answer. The engine places a single measurement on the check's
own node and leaves several to the grading, which has already said in its tree
where each belongs. Where the **measurement** raises, the engine writes the
failure record itself, against that declared object (ADR-0040).

A check that reads several things on tempos of their own declares them as
**units** ([ADR-0130](adr/0130-a-unit-has-a-period-of-its-own.md)): `units()`
answers one `Unit` each — a `key`, a `period_seconds`, the `node` it answers for
relative to the mount, and what one run of it costs — and `measure_unit(key)` reads
one of them, as `measure()` reads the whole. A check that declares none is the
**one-unit check**: the base answers one anonymous unit with the check's `frequency`,
answering for the mount and measured through `measure()`, which is every check that
existed before. A declared unit's period is written `frequency:` in the block that
configures it — an aspect's — read with `parse_duration`, else a cadence the type
declares for a source that has one, else the check's; a period written shorter than
a declared cadence is a line in the log at load, never a refusal. The engine refuses
at startup a declaration it could not honor (§4.6): a unit without a key, a check
that declares units and no `measure_unit`, two units of one key or of one node, and a
unit answering beneath another's node. A `Unit` validates itself — a period of at
least a second, a node with no `.` or `..` and no leading slash.

`grade` returns a `CheckResult` — a **recursive value** (`code`, `reason`, and
optional `name` / `description` / `config` / `children`). `reason` is **keyed**
([ADR-0036](adr/0036-addressable-reasons.md)): a string, a list of strings, a
`{slug: text}` mapping, `(slug, text)` pairs or a list of `Entry` values,
normalized in `__post_init__` into `reason_entries`. A mapping or a pairs list
declares its entries **members** — an admin can pin one of them — and a list
of strings needs `entries=True` to say the same; everything else is **prose**,
keyed like all reasons but suppressible only as a whole node. **An entry may carry
its own code** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)):
`Entry(slug, text, code=…, running=…)` — exported as `little_sister.checks.Entry`
— declares members by shape, and a check handing over coded entries **omits
`code`**: the seam refuses declaring both, and `CheckResult.stored_code` (what the
engine upserts) is then derived — worst-of the entries' own codes, `UNDEFINED`
ignored, an empty entry-bearing set (an empty mapping, or `entries=True` beside an
empty list) reading `OK`, because "nothing to report" is not "nothing reported".
`running` marks a line whose subject has work in flight — display only, never
severity — and the entry codes exclude `MAINTENANCE`, which is never a check's
claim. A check that emits healthy lines owes the **ordering rule**: non-OK first,
then in-flight, then healthy-and-idle, or `reason_cap` folds the failures behind
*⌄ all N*. **An entry may also carry what it is about and what was read.** `Entry.subject` is
the source's identifier for the entity the line stands for — a repository, a host —
which several lines commonly share and which no slug can be split back into, and
which is deliberately not an address: nothing is pinned by subject, because a pin
holds an identifier and only a line has one. `Entry.data` is the **record**, the
material a check read and used to throw away once it had written its sentence;
`text` is untouched, so nothing on any surface moves until something renders it,
and the node's own page shows it as a list of dotted names and values.

**A result may also carry lines no node shows.** `for_record` is a sequence of `Entry` a
grading writes **for the record alone**
([ADR-0111](adr/0111-a-runs-mark-says-how-the-run-stood.md) decisions 2 and 7): what it
says of a reading it read and does not put on a line — a run that is no longer its
subject's newest. `reasons.for_the_record` takes them in `__post_init__`: each is an
`Entry` that carries its own `code`, having no node's to take, and the record of the
reading it is said of as its `data`, by which the engine finds that reading (§4.6); a
line without either refuses the result with a `CheckError`. Its record goes through the
seam below. Its slug is neither checked nor deduplicated, since a slug is what a pin
holds and nothing pins a line no node shows. The lines are no part of `reason_entries`,
so nothing that reads a node's lines sees them — not `stored_code`, not a cap, not the
envelope, not a pin — and nothing holds them once the run's readings are kept.

**A node of a result may say that its children are complete.** `children_complete=True`
([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md) decisions 1 and 2) says
that the `children` of that node are all of them: the run read every one, so a child an
earlier run wrote there and this one does not return is gone, and the engine removes it
(§4.6). It is said of the node's direct children alone and of nothing beneath them, each
node of a result for itself, and anything but `True` or `False` refuses the result with
a `CheckError`. A result that says nothing — the default — removes nothing: a child it
leaves out stays, as a run that could not read it wants
([ADR-0060](adr/0060-a-line-makes-no-claim.md) decision 3). The keyword is additive, and
the epoch of §11 does not move.

**A child of a result may say that a run names it.** `dynamic=True`
([ADR-0118](adr/0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)) says
that the node is named by its source, or by what a deployment's configuration calls a
thing, and not by the type's own code: a volume, a function, an account. Nothing
declared for a name then reaches it. The engine reads its `title`, `about` and
`show_when_quiet` from its own result and asks neither the type's `subnode_defaults` nor
the deployment's `subnodes:` block for its name, so a function called `batch` is not
labeled as a `batch` aspect, though its parent's `children:` still claims
`show_when_quiet` for it ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md));
`nodes.yaml`, seeded by path, still beats what the result carries, and the status tree
keeps that a run named it (`named_by_run`, §4.4). It is said of that node alone — a
child beneath it that says nothing is read by its name — a root ignores it, and anything
but `True` or `False` refuses the result with a `CheckError`. The keyword is additive,
and the epoch of §11 does not move.

**The measuring half may read what its check kept.** `Check.kept(subject)`
([ADR-0113](adr/0113-a-measurement-reads-what-its-check-kept.md)) answers the window of
one of the check's own series as the store holds it (§4.10) — every kept `SeriesRecord`,
oldest first, each handed with a `data` of its own — and with no argument that of the
object the check declares. It is for deciding what to ask a source that keeps a history,
and a record stays a fact about the world. Whoever runs a check binds the read,
`Check.bind_kept(reader)`: the engine (§4.6), or a type's own test, which binds what the
type is to find. A check nothing bound is answered `()`. The method is additive, and the
epoch of §11 does not move.

**A line that carries a record is a template over it**
([ADR-0126](adr/0126-a-line-is-a-template-over-its-record.md)). A type declares the
sentences its grading may say of one reading as **forms** — each a full name, one
sentence saying when the grading says it, and a default text — and the **words** and the
record's **fields** a template may name, each with one sentence and an example:
`line_forms`, `line_words` and `line_fields`, passed to `Check.__init__` beside
`measure_defaults`. The constructor reads them (`line_template.declare`) and resolves
them once with the deployment's `display:` block (`line_template.resolve`), which
`_parse_common` reads for every type as it reads `measures:`: keyed flat by a form's full
name, a template over the type's default, which `{line.default}` names. A key that names
no form, a template that names a field or a word the type does not declare or that the
notation cannot read, and a default that names `{line.default}` raise `CheckError` at
construction, so a deployment's mistake refuses the load naming the file and a type's
fails its own tests. `Check.line(form, reading, *, slug, code, running, words)` renders
the form over the reading's record and the words handed to the call
(`line_template.render`) and answers the `Entry` with that text, the record as its
`data`, the reading's subject, its `form` and its `occurrence` — the record field the
type names as `occurrence=`, else the reading's `identity` (ADR-0142 decision 3); a
word lives for the call alone, so a
series graded again says the same line, and a line for the record alone is asked for
the same way. The notation is `line_template`'s: a field by its dotted name and a word
under `line.`; a segment `{? …}`, shown only when the values it prints are there — a
link's target not among them — and `{?name: …}`, shown when `name` is as well, a value
being absent where it is null, missing, empty or false; a link, Markdown's own, with one
value for its target, which leaves its words plain where the target is absent or no
http(s) URL; and `{{`, or outside a segment `}}`, for a brace. Every value is escaped
as `plain()` escapes one, a target as a URL — a backslash, a parenthesis without its
partner and an `&` that would begin a character reference, nothing else, so an address
reads as it reads anywhere — a time under one of the three timed names is written in
the configured zone through `spans.local_time`, and a value absent outside every
segment prints `—`. The form reaches the node's own page through `ReasonLine.form`,
which shows it beside the line (`_own_lines.html`), and the engine hands each check's
declarations to `/system/installed` (`CheckInfo.line_declarations`), which lists them
for every type the configuration runs, and the JSON envelope carries it as an entry's
`form` (2.8.0), null on a line its check wrote as a sentence of its own, and the
grading that decided it as its `grading`.

**What a check grades is declared, and the library grades it**
([ADR-0131](adr/0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)). A
type declares every value its grading judges — its **gradings**, passed to
`Check.__init__` as `gradings` — each a full name, the key a deployment writes it under
behind the block it lives in (`ec2.max_age`), one sentence, the record field it reads
and its kind: a **map** from a word of its source's vocabulary to a code, a **pair** of
levels over a number in one unit, `max_…` failing above its levels and `min_…` below
them, a **set** of accepted values, or a **judgment** the type makes in its own code;
the library adds the window `max_since_ok` to every check. `grading.declare` reads the
declarations at construction, so a type's mistake fails its own tests, and the check
reads the gradings of its own keys out of the file as `_parse_common` hands it over
(`configured`), through a `GradingBlock` — the one spelling per kind: `<key>_warn`,
`<key>_error` and `<key>_reason`, `<key>: null` switching a pair off, a level written
with its unit and passing at itself, a map merged over the type's words word by word
and matched with case and the spaces around a word folded, a key that names no
declared word said once at `INFO` and graded as written, a word no key names WARN. A
block a type reads elsewhere is read the same way where the type hands it over
(`Check.grading_block(name).read`), and a `RuleList` handed the block reads what each
rule writes of it into `Rule.graded`. `Check.verdict(name, reading, …)` answers the
`Verdict` a grading gives a value — its declared field of the reading, or the value the
type derived — under the block's setting, or a rule's where the rule wrote it: the
code, the sentence written for the grading where it fired, the rule whose keys judged
it and what a value that did not pass was held against; `grading.worst` joins the
verdicts of a line two gradings judged. `Check.line(…, verdict=…)` takes the line's
code from it and hands its forms the words `reason` and `rule`, which the library
declares for a type that grades through the seam, and `Verdict.entry(text)` is a line
written as the type's own sentence; either way the line's `Entry.grading` names the
grading that decided it. The library's `file`, `http`, `host-metrics`, `macos-memory`
and `qnap-metrics` grade this way, their old keys — `thresholds:`, `warn_mb`,
`max_age` with a level and `stale_code` — refused at start, naming what replaces them.

**The window is the library's** (decisions 7 and 8): `grading.since_ok` is the time
from the newest reading kept of a subject that stood OK to the reading graded, a pure
function of the times and codes handed to it, and `Check.window_line(at, kept)` judges
it under `max_since_ok` and writes the line, coded, from one of the library's two
forms, `since_ok.last` and `since_ok.none` (`checks.base.WINDOW_FORMS`), which a
check's `display:` block re-words beside its type's own. The engine calls it once a run
is graded and before it is stored (`Engine._with_window`), for a check whose
configuration writes a level of it (`Check.grades_a_window`): over the subject's kept
records and the run's reading at the code it stands at, each at its own time, the line
placed where `_keep_series` keeps the reading as standing — so that the node's code,
its roll-up, the log line and the retry read the window's code, and the reading is kept
as its node then stood. A line's grading reaches the tree as `ReasonLine.grading`, the
node's page and the envelope's `grading`; `/system/installed` lists each type's
gradings (`CheckInfo.gradings`, `app.GradingRow`) after the library's own.

The record is validated at this seam: it is a mapping, it serializes to JSON, its
JSON weighs no more than `record_limit` bytes (`settings.yaml`, default
`limits.RECORD_LIMIT`), and a value under one of `reasons.RECORD_TIMESTAMP_KEYS`
(`at`, `started`, `ended`, at **any** depth) is an ISO-8601 string carrying an
offset — converted to UTC here and never re-stamped — or null. **What a refusal
costs depends on where the record is built**
([ADR-0093](adr/0093-a-record-the-seam-refuses-costs-its-line.md)). Everywhere but
inside a run the engine drives it raises `reasons.RecordRefused`, a `CheckError` at
`CheckResult` and `Measurement`, naming the field or the bytes, as a
declared-and-derived code does — so a check's own tests meet it where the record is
built. Inside one (`reasons.lenient_records`, a context variable `_execute` sets
around `measure()` and around `grade()`, §4.6) the seam **marks** it instead and
collects a `reasons.Refusal` — why, the refused record's weight, and whether the
weight is why: a line keeps its text and code with `data` null and `Entry.refused`
saying why, and a reading keeps `Measurement.refused` and, as its record, the failure
record naming the refusal. A subject, an identity or a state it refuses still raises
there. What is stored is the JSON read back, so the tree holds plain types nobody
outside owns, which is what keeps a record safe to read outside the lock
([ADR-0002](adr/0002-rlock-snapshot-synchronization.md)). Those three names are the
whole typed vocabulary: a name earns a type when a surface does something with it
that it could not do without one. A measurement — a number with a unit — is not one of
them: which fields are measured, and in which unit, is **declared** in the check's
configuration (§4.11), because a key's name cannot carry the unit an axis needs.

The node's own page is that surface, and one list serves it for a line's record and
for the node's measured one (`_record_list.html`). Its rows are the record's fields by
their dotted names, from `reasons.record_leaves` — the one walk a measure reads a field
through too (§4.11), so what the list shows is what `measures:` names. The
`record_fields` filter decides
what kind each row is — the one place a field's kind is decided — by the field's own
name, never its value, reading the seam's set rather than a copy of it: a value under
one of the three names reads in the configured `timezone` and `time_format` (§7), and
everything else is shown as it was stored — a null, a time the zone cannot hold, a
time-shaped value under any other name. No age stands beside a time
([ADR-0082](adr/0082-a-line-carries-what-it-is-about-and-what-it-read.md)
decision 5).

`reasons.py` owns the normalization, the content-hash slug
(`h-` + ten hex digits) an undeclared entry gets, the record's validation, and the
`derive_code` rule. Most checks return a
single leaf; one that reports several aspects returns `children`, a small tree the
engine writes as a branch beneath the check's node ([ADR-0007](adr/0007-check-result-branches.md)).
A check also exposes a curated allow-list of the parameters it ran with via
`Check.config_summary()` (Markdown) — display metadata the engine carries onto the
node like `description` and the detail page renders
([ADR-0013](adr/0013-check-config-on-node.md)); a **branch** check leaves its shared
container bare and tags each child's `config` instead.
`checks/base.py` holds the `Check` ABC, the `CheckResult` / `CheckError` types,
common config parsing (`path`, `description`, `frequency`, `timeout`, `series_keep`,
`measures`, `reading_cap`, `display`; `parse_duration` accepts `15m` / `2h` / `1w` / seconds,
lowercase units only; `parse_size` accepts `500 GB` / `2 TiB` / `64 KiB` / bytes, the
decimal prefixes and the binary ones both, case as written) and a `type`→class registry.
Config blocks are read with **`values.py`** ([ADR-0026](adr/0026-reading-values-from-decoded-bags.md)):
`values.text` / `number` / `real` / `flag` / `rows` take a decoded YAML (or JSON)
bag plus a path of keys and always return the declared type — absent yields the
default, `required=True` makes absence a `CheckError`, and a present-but-uncoercible
value always raises rather than falling back to a plausible number. `CheckError`
itself lives in `errors.py` so `values` stays importable from `config.py` /
`pins.py` without pulling in the check registry.
Built-ins:

- **`http`** — GET a URL; OK when the status is in `expected_status`, a set of
  accepted values graded through the seam of §11 (default `200`, any other an error,
  [ADR-0131](adr/0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)). A `3xx` is
  followed or reported per `follow_redirects` (default: followed); the body is
  never read. Requests go through `little_sister.fetch` (ADR-0058), as every
  request in the library does.
- **`file`** — heartbeat: OK while a file's mtime is within `max_age`, a pair whose
  levels are the last ages that pass (default: an error above 20m, ADR-0131), else WARN
  or ERROR as the level it went beyond says — saying how long ago the file changed as
  `format_span` writes a span — `82d 19h` past a day — and that level as it was
  configured, through `format_duration`
  ([ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md)).
  Relative `file` paths resolve under the executing user's `$HOME`.
- **`command`** — run a shell string or argv; OK on exit 0; reason = captured
  `stdout` / `stderr` / `both`, shortened to `max_chars` from `tail` / `head` and then
  in bytes, so that its record weighs 2,048 at most, `OUTPUT_RECORD` in
  `checks/output.py` (`little_sister.process`, per-check timeout).
The **SSH family** runs over one connection, `SshConnection`
(`checks/ssh/connection.py`): a value object that carries the connection block (`host` /
`user` / `port` / `identity_file` / `options` / `sudo` / `timeout`), builds the `ssh`
argv (`BatchMode` forced; the legacy SHA-1 `ssh-rsa` algorithm **off by default**,
applied after the user's `options` so a host can re-enable it), and runs a remote
command or pipes a local script — through `little_sister.process` and a remote wrapper
that ends the remote command with its connection, the script on stdin ahead of the
hang-up line ([ADR-0089](adr/0089-a-process-a-check-starts-ends-with-it.md) decision 4)
— returning a `RemoteResult` (stdout, stderr, exit code, a failure `error`, and any ssh
advisory `notice`). It flags a **non-post-quantum key exchange**, which every connecting
check surfaces as **WARN**; a legacy host silences it with
`options: ["-o", "WarnWeakCrypto=no-pq-kex"]`. A pure, I/O-free toolkit, `ssh_metrics`
(`checks/ssh/metrics.py`) — `parse_metrics`, `grade`, the formatters, `unavailable`,
`volume_name`, `code_span` — is the **public** API the parsing checks share
(`little_sister.process`; the external `ssh` binary). The five checks:

- **`ssh-connect`** — connectivity: connect and run a trivial remote `true`; OK if
  reachable, ERROR if not, **WARN** on the non-PQ advisory.
- **`ssh-command`** — run a remote command (the over-SSH twin of `command`): OK on
  exit 0, reason = the captured output (`capture` / `max_chars` / `keep`), **WARN**
  on the advisory; its transport half and its output share one record of 2,048 bytes
  at most.
- **`ssh-script`** — pipe a local `script` (via `interpreter`, default `bash`) to
  the host and report its output, like `ssh-command`; the base the two metrics
  checks specialize (they parse the output instead of returning it).
- **`host-metrics`** — read basic system parameters from a host over SSH and report a
  **branch** rooted at the **host node** (the check's `path` targets the
  host, e.g. `/system/alpha`). Because ssh is only the *helper* that fetches the
  data, it is a **peer leaf**, not the metrics' parent: the host gets an `ssh`
  child (OK, **WARN** on the non-PQ advisory, ERROR on a failed connection)
  alongside a `disk` / `memory` / `cpu` / `load` leaf — all siblings, each metric
  carrying its number (a percentage) even when OK, each graded by a pair of the check's
  own keys — `max_disk`, `max_memory`, `max_cpu`, `max_load` (ADR-0131). The host node
  itself is a neutral container (its status rolls up
  from the leaves), so other checks (e.g. a `file` heartbeat) can sit beside them.
  It proposes a host's leaves as chips, by `node_defaults`, and a disk's
  filesystems where it fans out, by its `disk` entry
  ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)).
  One connection per run pipes a **per-profile** metrics script (measures only) to
  the host's shell: a
  host's `profile` (`linux` | `macos` | `busybox`, default `linux`) selects both
  the script — `scripts/host-metrics-{linux,macos,busybox}.sh` — and the
  interpreter it's piped to, `bash` for linux/macos and `sh` for busybox (whose
  `/bin/bash`, on an ASUS/ash router, is often just a symlink to busybox). Each
  script self-guards on `uname` and emits `profile_error=` on an OS-family
  mismatch — the check renders that as a **WARN** `ssh` leaf (a config defect, not
  an outage); the linux script applies the same hard guard to a **busybox**
  userland (busybox `df` self-identifies in `--help`, reliable where an old
  router's `readlink -f` isn't), so a busybox host wrongly on the linux profile is
  caught rather than left to a crashing `awk` (ADR-0009). `sudo` runs the script
  under `sudo -n` (not needed for these
  metrics); `disk_path` picks the filesystem to measure — `all`, or a **list** of
  paths, makes `disk` a branch with one graded child per filesystem (named by its
  volume; a list reports just those volumes); `debug: true` adds the raw
  (unstripped) ssh stderr, exit code and the script's `debug_*` lines to the `ssh`
  leaf's reason for diagnosis (`little_sister.process`, per-check timeout, the external
  `ssh` binary). All three scripts parse `df` by anchoring on the capacity column,
  so a space in the filesystem name (macOS autofs `map auto_home`) can't shift it,
  skip 0-block stubs so a real volume is found, and pick the disk row by the
  longest matching mount point. They split by **what userland each can rely on**:
  linux and macos trust `awk` and `df -P`, while the **busybox** script (QNAP /
  ASUS) keeps the paranoid handling for the weakest hosts — `df` retried with **no
  path argument** (old busybox rejects one) through `-Pk` → `-k` → bare, a
  **pure-shell `df` fallback** (`_df_sh`) for a busybox `awk` that *crashes*, an
  integer `sleep`, the CPU read from `/proc/stat` **twice into one awk** (so the
  huge cumulative counters never go through `awk -v …`, which Bus-errors that
  host's awk, nor the shell's 32-bit `$(( … ))`, which overflows), and the CPU
  count falling back to counting `/proc/stat` `cpuN` lines. That fallback parser
  lives in its **own function**, never as a `case` written literally inside
  `$( … )` — bash 3.2 (macOS) mis-parses the `)` of a case pattern there as the end
  of the command substitution, a parse error that would down a script on *every*
  host. The busybox script is strict **POSIX `sh`** (no `<<<` / `$'…'` / arrays),
  so it parses under busybox `ash`.
- **`qnap-metrics`** — QNAP hardware health over SSH: pipes `scripts/qnap-health.sh`
  (which calls QTS's `getsysinfo`) and reports two branches **on the host node,
  beside the `host-metrics` data** — `temperature` (`system`, `cpu` where
  exposed, and one `drive<bay>` per populated bay, in °C, graded by the pair
  `max_temperature`) and `smart` (one `drive<bay>` per bay: `GOOD`→OK, `Warning`→WARN,
  else ERROR — a judgment the type makes, to which `smart_reason` gives a sentence).
  Empty bays and absent sensors are omitted. It carries no description, so it shares
  the host node without overwriting `host-metrics`'; the non-PQ warning it leaves to
  `host-metrics` / `ssh-connect` on that node. It proposes its drives and its sensors
  as chips, the two branches open
  ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)).
- **`macos-memory`** — macOS memory health over SSH: pipes
  `scripts/memory-macos.sh` and reports the early-warning signals that RAM
  trouble is *building*, as leaves **on the host node, beside the
  `host-metrics` data** — `pressure` (the kernel's VM memory-pressure level, graded by
  `max_pressure`: normal→OK, warning→WARN, critical→ERROR by default), `swap` (in use,
  `max_swap`), `compressor`
  (memory occupied by the compressor as % of RAM — compressor exhaustion is
  the kernel-panic signature on a small-RAM Mac; `host-metrics` folds those
  pages into its one "used" number and can't see them specifically) and an
  optional `processes` branch (RSS per watched command-line pattern, summed
  over matches and graded per process by `max_rss` in its own entry, plus the oldest
  match's uptime — a
  slow leak shows as monotonic growth, a scheduled restart as uptime
  resetting).
  A watched process that isn't running is **OK**: the aspect watches memory,
  not liveness (that's a `file` heartbeat's / `ssh-command`'s job). Like the
  other macOS script it stays bash-3.2-clean, guards on Darwin, and only
  measures; the grading lives in the check. It carries no description, so it
  shares the host node without overwriting `host-metrics`'. It proposes its leaves as
  chips and the watched processes beneath them too (ADR-0128).

The family lives in the `checks/ssh/` package: `connection.py` (`SshConnection`),
`metrics.py` (the pure toolkit), `connect.py` / `command.py` / `script.py`, and the
domain checks `host_metrics.py` / `qnap_metrics.py` / `macos_memory.py` — over
`SshCheckBase` (the shared connection block) and `SshScriptCheck` (adds script
piping). Several checks can target the **same host node** (e.g. `nexus` runs both
`host-metrics` and `qnap-metrics`): the engine leaves a node's description
untouched when a contributing check has none, so they don't clobber each other. A
node they share is neither's, so its own first look is `nodes.yaml`'s, while each of its
leaves starts as the check that writes it says of the leaves of its own node, and
beneath them each speaks for its own subtrees (ADR-0128 decision 5, as amended).

**What the three domain checks say of their nodes** is ADR-0133's division: a node's
description says what is read, in a sentence; an aspect's `about` says what to do, by
the status it is done on, and links the aspect's handbook — a Markdown file the package
ships in `checks/ssh/handbook/<type>/`, one an aspect, which says how to read the value,
its levels and what to do at length — and a deployment's `{default}` places either in
its own. A node a run names beneath an aspect — a volume, a drive, a watched process —
takes neither: it carries the details of its object, its mount point, its bay or its
pattern, and what holds for every one of them a deployment gives as the details under
the aspect's name, which reach every node beneath it. A check's own node carries the
host it reaches, withheld where two checks share it.

`load_checks(spec)` reads every `*.yaml` / `*.yml` across the **`checks` aspect of
each configuration root** and instantiates the matching check; sub-folders like
`scripts/` and `examples/` are ignored and a config's relative paths (e.g. a
`script`) resolve against its own directory. `LITTLE_SISTER_CONFIG_DIR` (default
`config`) is a **path-list** — one root, or several joined by the OS path separator
(`base:sites/alpha`) — whose `checks/` directories load as a **union**: a shared base
plus site-specific additions, no copy-paste
([ADR-0015](adr/0015-check-discovery-union.md),
[ADR-0031](adr/0031-deployment-config-directory.md)). Each listed root must exist and
**at least one** must provide `checks/`, or the process refuses to start (§7); the
set is fixed for the process — a restart re-reads it. Because `config/checks/` holds
checks and nothing else, the loader skips nothing by name. The on-disk
`config/checks/` ships `examples/` and a `README`; the generic metrics scripts are
package data, not deployment configuration
([ADR-0021](adr/0021-script-resolution.md)).

Each check declares the nodes it owns — `owned_nodes()`, the subtrees it gives a
definite status to (a leaf its own node; a **branch** check its child subtrees, not
the shared container it merely rolls up). The loader **rejects** a union in which
two checks own **overlapping** nodes — equal, or one a segment-wise ancestor of the
other — naming the path and files, so a duplicated or shadowing check fails loudly.
Disjoint owners share a host node freely: `host-metrics` + `qnap-metrics`,
`host-metrics` + `macos-memory`, or a `file` heartbeat as a sibling child (e.g.
`/macmini/findmy` beside the metric leaves), but **not** a leaf placed on the
container itself ([ADR-0015](adr/0015-check-discovery-union.md)). The
`/little-sister` line is **reserved** for the engine's own heartbeat
([ADR-0005](adr/0005-dashboard-freshness-and-self-monitoring.md)): a check owning
nodes on it is rejected at load — the dashboard lifts that node into the status
strip, which must never hide a subtree.

**Secret references** (`secrets.py`, [ADR-0023](adr/0023-secret-references.md)): a
check config field that carries a credential is a **reference**, resolved through
`little_sister.secrets` **once, in the check's constructor**
(`Check.resolve_secret`) and held for the process lifetime — never re-read during
runs. Every reference is `scheme://address`: `env://GITHUB_TOKEN` is the
environment-variable lookup (fed by `.env`, ADR-0003, and registered like any other
scheme), while `aws-sm://…` and friends are resolved by the resolver the
**application registered** via `register_resolver(scheme, …)` before importing
`little_sister.app` — the same import slot that registers deployment check types;
the library ships no store client. Those two schemes are carried by
`little-sister-aws` (§2), which is where a resolver goes once it would have a second
user; a deployment may equally write one in its own code. There is no bare-name form: a string without a
scheme is a *pasted secret* far more often than a name, so it is rejected at load
without being quoted back (ADR-0023). A malformed reference
raises `CheckError`, so the load fails loudly like any config typo; a well-formed
reference that fails to
resolve (store unreachable, secret absent) is recorded on the check's
`secret_errors`, and the engine **pins** such a check (§4.6). None of the built-in
check types takes a credential; the seam serves deployment checks (and later
satellites).

Registering is a **claim**, held to the rules of the other registration seams
([ADR-0064](adr/0064-the-resolver-is-a-registration.md)): the registry records the
package that made it — inferred from the call site, as a configuration aspect's
registrant is — and a second claim on one scheme from a **different** package
**refuses at startup** naming both, for the reason a duplicate `type:` name does
(ADR-0051): a scheme says where a credential is read from, so import order must not
be what decides it. The same package registering again replaces silently, which is a
reloading server re-running its own registrations; replacing *another* package's
scheme is available to whoever means it and says so — `replace=True` — which is how
a deployment substitutes its own `env` implementation, and what it replaced is
remembered. `/system/installed` shows both halves: `secret <scheme>://` on the registering
package's inventory row, and a table of every scheme with its owner — built-in `env`
included, because the schemes are additive and the whole list is what a config field
may say.

**Node metadata** (`nodes.py`, [ADR-0012](adr/0012-node-metadata.md) /
[ADR-0017](adr/0017-node-title.md)): a node's `about` (subject metadata, what it *is*)
and `title` (a short display label) are seeded onto the tree **once at startup** via
`set_about` / `set_title`, resolved **per field** by precedence — a `nodes.yaml`
declaration keyed by path (so it reaches container / host nodes no single check owns)
**>** the inline value on the owning check **>** empty (`resolve_metadata` → a
`NodeMeta`). The file is **optional** and is the `nodes` aspect of the configuration
directory — `config/nodes.yaml` in each root of the path-list, where a later root wins
**per field** over an earlier one and the override is logged with both files named
([ADR-0031](adr/0031-deployment-config-directory.md)); a key no entry knows is named in
one startup line for the file. An entry may also say how the node first looks — `chips`,
`fold_ok`, `reason_cap` — and, under `children:`, the same and the claim for each child
of the node ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)): none of that
is seeded, and the file as loaded is kept for the process's life, handed to the engine,
which reads a path's `children:` claim as it writes each child. It carries both fields
per path (`path: {about: …, title: …}`; a bare string is `about`). For the **subnodes a
branch check emits** the lattice grows two rungs
([ADR-0025](adr/0025-check-provided-subnode-metadata.md)): `nodes.yaml` **>** the
deployment's `subnodes:` block in the check's own YAML — **read by the library**, like
the `show_when_quiet` beside it — **>** what the check *type* **declared**
(`subnode_defaults`, `name → {title, about}`) **>** the `about` / `title` on the child
`CheckResult` **>** empty. The middle two resolve **per field** in `Check.__init__`,
once: the configured text when it says something, the declared default otherwise, with
`{default}` substituted so a deployment can extend rather than replace and `{token}`s
(`label_tokens`) expanded by a plain replace that leaves Markdown intact — a token named
`default`, which `{default}` takes first, refuses the type, and so does one by a
status's name, `{error}` and the other four, in either case, being how a node's text
names a status
([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 5, §4.7); the engine then writes the resolved text per subnode *name*, at any
depth, exactly as it does the flag. The result's own label is read where that map is
silent for the name, and it is the only one read for a child whose result says `dynamic`
([ADR-0118](adr/0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)) — the
**dynamically named** child a run discovered (`host-metrics`' per-volume leaves), which
no declaration is about, whatever a host calls it. The type's `{token}`s expand in it as
in what the type declares, a handbook file it names among them (ADR-0133 decision 2);
the check keeps them as `label_tokens` for that. Unlike the write-through
`description` / `config`, these **fill an empty field only**, and because the startup
seed runs before the engine's first tick a `nodes.yaml` label is already present and
wins; a filled label then freezes at first fill (stable identity — text that changes
each run belongs in `reason`), which is also what pins a `{token}` to a
construction-time fact. This carries **type-inherent** subnode identity — `host-metrics`
declares for `ssh` / `disk` / `memory` / `cpu` / `load` an `about` that says what to do
and a handbook it ships — so a reusable branch check says what to do with its leaves in
every deployment without per-node `nodes.yaml` copy-paste, and a deployment retunes one
of them, for **any** installed branch type, without that type carrying a line of code
for it. A **branch** check gives
each leaf its own `description` through a `descriptions:` map keyed by leaf name,
leaving the shared container's description empty. A startup **consistency pass** warns
for an `about` path no check covers (the ADR-0014 check-root coverage test), notes an
`about` past about 400 characters and a check's own `description` past about 160
(`note_long_about`, `note_long_description` — the engine notes the ones a run hands a
node beneath its check, once), and info-logs a container that has checks but no
`about`. `about`, `title`, the leaf
descriptions and the `reasons` are Markdown, rendered server-side
([ADR-0018](adr/0018-markdown-rendering.md), §4.7). `title` follows the node name
(ellipsed) on a card, and the `status / …` breadcrumb in the **page header** of both a
branch view and a leaf's detail page
([ADR-0017](adr/0017-node-title.md)). A node also carries an **`order`** — its declared
rank among its siblings ([ADR-0055](adr/0055-sibling-order.md)), resolved by the same
per-field precedence as the labels: a `nodes.yaml` `order:` **>** an inline `order:` on
the check **>** the `order` on the `CheckResult` it returns **>** unstated. Unlike the
labels it is read on a result's **root** as well as its children, and unlike them a
stated `0` is a real declaration rather than silence — which is what lets a deployment
overrule a check's rank by naming the default value, so the node's field is nullable
while the snapshot's is a plain `int`. A zeroed node sorts **with the unranked**, ahead
of every positive rank; that is a rank, not a request for alphabetical, and returning a
whole ranked set to the alphabet takes an `order: 0` per sibling.

And a node may carry **`show_when_quiet`** — *this node's quiet lines are still
information* ([ADR-0063](adr/0063-declining-the-density-trade.md)) — for the
**inventory**-shaped aspect whose list is read precisely because everything is fine, and
which the wall would otherwise close to a chip while it is quiet. It rides the first
look's addresses ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)), which
are the labels' lattice with `children:` at each rung — `children:` saying it for each
child of a node, whatever its name — and that is what makes the `subnodes:` block one
story: a `nodes.yaml` `show_when_quiet:`, the node's own path and then its parent's
`children:` **>** the deployment's `subnodes:` block in the check's own YAML — **read by
the library**, not by the check: `_parse_common` parses it for every type, so a
deployment can state it for any installed branch check without that check changing — the
node's name entry and then its parent's name entry's `children:`, the top level's for a
child of the check's own node, **>** the type's **declared default**, `show_when_quiet`
in the same `subnode_defaults` entry that declares that subnode's labels, so an aspect
that is a roster by construction is declared once in a package rather than once per node
path in every installation, then its `children:`, and `node_defaults`' for the children
of the type's own node **>** the value on a child `CheckResult`, the dynamic-child
channel **>** unstated. `Check.__init__` keeps the file's statements and the type's
apart — the same place and the same moment the labels resolve — and the engine asks them
in that order as it writes each node (`first_look.statement`), a name entry per subnode
*name*, at any depth, and for no child that says `dynamic`, which takes its parent's
`children:` and then its own result. A node's own `nodes.yaml` entry is seeded at
startup; a parent's `children:` names no path, so the engine is handed the file as
loaded and reads it as it writes. The result's copy is root-ignored like `about` /
`title`, because the root's own source is the inline `show_when_quiet:` key in the
check's YAML. It is a **tri-state** for the reason `order` is nullable, sharpened: a
stated `false` is a deployment declining a claim a check type ships for every
installation, so it must occupy the field where a check's `true` cannot fill over it,
and it stays `bool | None` all the way onto the snapshot. A non-boolean fails the load
(`values.strict_flag`, so `"false"` in quotes cannot read as *on*) — for the inline key
and for the block alike, on every type, since the block's shape is the library's to
validate. What it does is painting and nothing else — §4.4 — and it rides the JSON
envelope as every field of the snapshot does
([ADR-0080](adr/0080-the-envelope-is-the-snapshot-published.md)), the one statement
about display in the contract: the first look's keys beside it are the web page's
settings and never on the snapshot (ADR-0128).

**A title that only repeats the name is not drawn** (`titles.py`). Where a check has
nothing better to say it hands back the name again with a capital letter, and a row of
severity-band chips then reads `critical Critical`, `medium Medium` — twice the width,
no second fact. One predicate answers for every surface: the grid's leaf chips, box and
card head lines and the heartbeat strip, the page band beside the breadcrumb, the
inspection popover, which heads with what the node's own head draws, *Handled*'s
headings and the `/copy` hand-off. It folds
**case**, `_` / `-` / a space, and runs of whitespace — so `pull_requests` and
*Pull requests* are one string, and so are `code_scanning_alerts` and
*Code-scanning alerts* — and nothing else: a title that adds anything at all survives.

**And a title with no word in it cannot stand in for the name**
([ADR-0061](adr/0061-decoration-is-not-a-label.md)). Every one of those surfaces but
one draws the name and the title side by side, so the rule above is all it needs. The
`/copy` hand-off draws the title *instead of* the name, and that is right while a
title is a **word**: a node titled *Cluster A* is better named that way in a pasted
document. It stops being right for a **glyph**: a severity
band titled 🔴 would paste into a ticket as a circle and nothing else. So a title with
no letter and no digit in it (`isalnum`, a Unicode test — 日本語 is a word, → is not) is
drawn **with** its name there, `critical 🔴`, in the chip's own order. `label_parts`
returns the two halves rather than a joined string, because a title is authored
Markdown and a name is structural data each surface escapes its own way.

Both are **view** rules: the snapshot stores the title and the JSON envelope emits it,
whatever a surface decides to draw.
The comparison is on the **raw** values, before the Markdown renderer (§4.7). This is
**display, never data**: the snapshot keeps the title and the JSON envelope keeps
emitting it ([ADR-0080](adr/0080-the-envelope-is-the-snapshot-published.md) decision 1),
because a client rendering its own chips is entitled to its own decision about the word.

A node's `description` and `about` stand in its **About card**, on its Status tab alone
([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 1; `_about_card.html`): headed *About* as the facts' cards are, the description
first, muted, the about beneath. `_node_facts.html` places it beside the node's facts —
a leaf's and a branch's alike, after a branch's children — in a block that is the
container its columns ask (`.node-facts--about`, `overview.css`): where the block holds
the facts at their 820 pixels, a gap and 18rem, the facts stand in a column at that
measure and the card in a second one from the top, beside *Time*, taking up to 28rem;
where it does not, the facts' own column gives its cards to the block
(`display: contents`) and the card is ordered in before *Configuration*, the block at
the facts' measure. A leaf's page widens from 820 to 1,300 pixels for the card
(`check.html`); a node with neither text has no card, and a branch with nothing else to
say has the card alone. The root is a node as any other: its card stands alone after its
children, at the overview's foot, where it says something of itself. `about_card`
(`app.py`) is the one answer to whether there is a card, which the leaf's width, the
block's columns and the branch's block ask. The band and the head say neither any more,
so the node's other views — Series, History, Handbook, Copy — show neither, one click
from Status. The dashboard popover shows the name and `title` as the head draws them,
and the first block of the `about` — the description where there is no `about`
([ADR-0019](adr/0019-inspection-popover.md)). Both render as every text does, the
description as a block as the about is: a table either writes is drawn, and a status
either names — `{error}:` — is drawn as its sign (§4.7).

Beneath the two texts, after a thin rule, the card shows the node's **details** as a
table (`details.py`,
[ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 6): named values whose keys its team chose, each a line of Markdown, the key
muted. The type gives each node it writes the details of its object on
`CheckResult.details` with every run, the root's too, written through as `description`
is; the deployment gives anything else in the check's file for its own node, under an
aspect's name in its `subnodes:` block, and in `nodes.yaml` by path — `details.read`
keeps each value as written, and one YAML read as anything but text refuses the file,
naming the key — which wins key by key (`details.merged`, as a later root does over an
earlier one, and the second of two checks sharing a node over the first's file). None
of it is a label: the type's are written through and the subnode's are written by the
engine per child name as each child is written — nothing for a child a run names, as
for the labels — and the path's are seeded (`StatusTree.set_details`) and kept apart, so
a run never touches them. **What the deployment gives a node holds for every node
beneath it**, key by key, the nearest winning, and the type's are the node's alone. The
snapshot holds a node's own (`StatusSnapshot.details`: each `Detail` with its key, its
text and `by`, the type's first and then the deployment's, each as given, a key both
name standing once for each; the type's withheld on a mount two checks share, as
`report` is), which the API carries as they are (§5.2), and
`StatusTree.details(path)` resolves the card's rows down the live tree on demand
(`details.rows`), since only a node's own page and its Copy document show them: the
type's first, then what comes down from above, the outermost first, then the node's own
deployment's last, a key standing once where it is named first with its nearest value,
and a nearest value that is empty standing nowhere — so a subtree can take a key back.
Each row says the node it is given on (`Row.at`): the card names it as the key's tooltip
where it is a node above, and renders the value for it, so that a link a detail writes
in the short form leads into the handbook of the node it is given on, a page every node
beneath it shares. `about_card` counts a node's rows too, so a node with nothing of its
own but what is given down has its card; the template global `card_details` keeps them
for the request. The Copy document carries the same rows as a block, *Details*, after
the node's facts (§5.1). The startup record names a link in a detail that leads nowhere
as it does one in the other texts: a path's at the start, a subnode's and a type's when
a run first fills the node, a check's own node's type's included.

Between the texts and the details' rule the card shows the node's **tags** as a line of
chips (`tags.py`,
[ADR-0139](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md)): words
that say what the node is — `production`, `rack-4` — which the deployment writes where
it writes details, `tags:` in a check's file for its own node, under an aspect's name in
its `subnodes:` block and in `nodes.yaml` by path, and which no type gives. `tags.read`
reads a list or one word, capitals as lower case, and names a word that is no tag on the
startup record rather than refusing the file. **A node carries every tag written for it
or for a node above it**, and everything adds up — a check's file and `nodes.yaml`
(`resolve_metadata`, `tags.union`), every root's entry for a path (`NodeMeta.merged_over`)
— so nothing takes a tag back and no parent carries its children's. The start hands the
tree the tags written for each path before the rules are read (`_seed_tags`,
`StatusTree.use_tags`), a path no node stands at keeping them for the node a run makes
there; the engine writes an aspect's on the child of its name (`named_tags`), never on a
child a run names. The snapshot carries each node's whole set (`StatusSnapshot.tags`),
those handed down to it from above and its own, in the order of the known tags —
`config/tags.yaml`, every root's added up, each tag with a line of what it means
(`tags.load_vocabulary`) — the rest after them by name; a subtree read by its path starts
from what is written above its root (`_tags_above`), so a node's tags are the same
wherever it is read. `StatusTree.tags_given` names, for the card's tooltips, the node each
is written on, the nearest; `tags_of` the tags a path carries — where no node stands,
what is written for its path and above it, with what an aspect's name gives the nodes
above it the tree holds (`_carried_tags`). A tag the configuration writes that no
`tags.yaml` names is a line on the startup record once, with where it is written
(`tags.note_unknown`, from `nodes.tag_places`). The hover card names a node's tags in
one line, the Copy document lists them with their lines after *Details*, and the API
carries them as `tags` (§5.2).

**A tag selects** (ADR-0139 decisions 5 and 7). A wall filtered by one, `?tag=` on
`/status` and on a node's page, draws each topmost node beneath the page's node that
carries it as a card of its own, the names between the two before its name, and nothing
above it (`_tagged_parts`, `status-card__context`); a node that carries it keeps every
child. A line inside the grid names the tag with its line, the parts the filter hides
that fail — a subtree no node of which carries it, where it fails, and a node on the way
to a tagged part whose own lines fail — and leads back to every node but on the kiosk
(`ls-tag-line`); the band offers the tags one at a time (`StatusTree.offered_tags`: the
known ones in their order, then any other written), each with its line as the option's
tooltip. The filter applies before hide ok and hide idle, after the strip has taken the
instance's heartbeat, and the chips' counts, the pins and the band's pill read the
unfiltered snapshot. It is the address alone: no cookie, and the refresh asks for the
page's own address. A chip on the *About* card leads to the wall filtered by it. The
Events page takes `?tag=` (`EventFilter.tag`, matched by `tags_of`), and a configured
rule and an action write `tag:` beside `under:` or instead of it (§4.4, §6.2), both
holding where both are written. Everything that selects is held to the tags the
configuration writes (`StatusTree.written_tags`): the start hands the tree its tags
before the rules are read and the actions their tags (`actions.use_tags`), so that a
`tag:` nobody writes is refused on the startup record.

What a team writes at length about a node — its runbook, how to sign in, its policy, the
reference a package ships — is its **handbook** (`handbooks.py`,
[ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 3), read on a tab of its own, *Handbook*, at `/handbook/<path>`
(`handbook.html`), after Status, Series and History and before Copy. It is a label as
the `about` is, on the same lattice: `nodes.yaml` by path **>** the check's own file —
its own node's `handbook:` and an aspect's under `subnodes:` — **>** what its type
declares in `subnode_defaults` **>** the `handbook` on a child `CheckResult`;
root-ignored, `{default}` placing the type's text in the deployment's, and filled once,
so the tab never comes and goes with a reading. A statement that is a single line ending
in `.md` names a Markdown file, and anything else is the text itself. A file is named
relative to the directory it is stated against — the configuration root a check's file
or a `nodes.yaml` is in, so `handbook: handbook/ec2.md` is `config/handbook/ec2.md`, and
a type's package for what the type declares or a run hands over — and never found by a
node's path: three accounts' `ec2` share one runbook. `handbooks.resolve` reads it where
it is stated — at startup for what the configuration and a type declare, at the node's
first fill for what a run hands over — so that `{default}`, the tokens and the fill work
on text alone; each root names files of its own, and `nodes.yaml`'s later root wins as
its other fields do. A file that is missing, cannot be read or lies outside its
directory gives no handbook and a line on the startup record, and the start names each
Markdown file in a root's `handbook/` that no statement read (`note_unnamed`):
`handbook` is an aspect of the configuration directory
([ADR-0031](adr/0031-deployment-config-directory.md)), always a directory, and one
stored as `handbook.yaml` is named there rather than refusing the start, a handbook
being a node's metadata. A handbook is read with the configuration, at a restart, as
`nodes.yaml` is. Its text stays on the node (`StatusTree.handbook`), and the snapshot
says only that there is one (`has_handbook`), so a client that fetches the snapshot
fetches no runbook. The tab stands on every view of a node that has one — the template
global `has_handbook(branch)` asks the tree, for the tabs and for the crumbs — and on no
view of one that has none, whose address answers `404` with a line that says where one
is written. The page renders the text as every text is rendered, its tables drawn and
its statuses as their signs, and anchors its headings as GitHub anchors them (§4.7);
its crumbs open each ancestor's handbook where it has one and its Status view where it
has none. The popover's map carries the Handbook view's address of a node that has one,
and the card links it.

**A text links its own node's handbook by a short form** (ADR-0133 decision 4): a link
written `handbook` leads to its top and `handbook#<section>` to a section,
`/handbook/<path>#<section>`, in every text of a node the page shows — the renderer is
handed the node a text belongs to (§4.7). Where a text leaves the instance the short
form is written out to the handbook's absolute address: the Copy document names a
node's handbook beside its *Dashboard* line and writes every link its texts write so
out (§5.1, `/copy`), and the API's node says where its handbook is, `handbook`,
leaving every text raw (§5.2). The startup record names a link that leads nowhere — to
a section the handbook does not have, its anchors as its page gives them
(`render.anchors_of`), or on a node that has none (`handbooks.note_links`): at the
start for a check's own node, the engine's heartbeat and the nodes above them, whose
handbooks and texts the configuration alone gives (`nodes._note_links`), and for a node
beneath a check's own when a run first fills it, once, since its handbook and texts come
from the check's labels and its run as well as from `nodes.yaml`
(`StatusTree.texts`).

### 4.6 Monitoring engine — `engine.py`
`Engine` runs the configured checks against the shared tree.

- A **scheduler** thread wakes every `poll_interval` (1s) and submits every *due*
  check to a bounded `ThreadPoolExecutor`; each check is due at start (the first
  sweep populates the tree), then every `frequency_seconds` — phase-shifted
  **once**, at the first re-arm, by a stable per-check offset (a digest of
  path + type within `min(frequency, 60s)`), so equal-frequency checks don't
  fire in one tick forever and a host carrying two checks isn't hit by both at
  once. A check already running is not re-submitted. While what a check's **last
  run rolls up to is not OK** — its root's code and every child it returned, by
  the roll-up's rules
  ([ADR-0125](adr/0125-the-failure-retry-reads-what-a-run-rolls-up-to.md)) — a
  configured **failure retry** ([ADR-0033](adr/0033-budgeted-failure-retry.md))
  pulls its next slot to `retry_interval` — measured from the run's completion,
  and never later than the nominal slot — at most `retry_attempts` times per
  failure episode, then nominal cadence until what the run rolls up to changes
  ([ADR-0060](adr/0060-a-line-makes-no-claim.md) decision 4); a run that rolls up
  to `UNDEFINED` arms nothing. It reads the result and not the node, so a pin
  cannot reach it. A secret-pinned check never retries, and freshness keeps
  judging by the nominal frequency.
- **What the scheduler releases is a unit**
  ([ADR-0078](adr/0078-the-unit-is-what-the-engine-releases.md),
  [ADR-0130](adr/0130-a-unit-has-a-period-of-its-own.md)): one `_Scheduled` entry
  per unit a check declares (`_units_of`, which is where a declaration the schedule
  could not honor refuses the start, naming the check), each armed on its own
  `period_seconds` and staggered on its own key, each holding the **newest reading**
  its unit handed back (`latest`). A check that declares none is one anonymous unit
  answering for the mount, and every sentence of this section that says *check*
  held before units and holds of that unit now. A check's units run **one at a
  time** (`_busy`): a unit due while another of its check is in flight keeps its
  slot and waits for the next tick, so a type's measuring half is never in two
  threads at once. `_execute` measures the one unit through `measure_unit(key)`,
  replaces its newest reading, and grades the **whole check** over the newest
  reading of every unit — this unit's first, then the others in the order the check
  declared them (`_newest`, `_grade`) — with this run's clock, so the tree is always
  whole and the grading stays the one pure function ADR-0086 made it; a unit that
  measured nothing contributes nothing until it measures again. **What it then
  writes is the unit's own path** (`_store_path`): the mount and every container
  down to the node the unit answers for, each with its own lines as the whole
  grading says them and with the shortest period among the units beneath it, then
  that node and its subtree whole, with the unit's period and the one reading the
  unit handed back alone placed on it — and **nothing beside it**: a sibling
  subtree keeps what its own unit wrote, its content, its stamp and its damping
  count, and writes no event. What a container says of its children — that they
  are complete — is applied after the path beneath it is written (`_prune_returned`),
  so a sibling the run returned and did not write stays and one it no longer
  returns goes. Where the grading returned no node on the path, the containers above
  the gap are written and the walk ends there. The anonymous unit's path is the
  whole tree, written through `_store` as before. Run facts are set on the unit's
  node and on every container between it and the mount (`_set_run_facts`): the
  unit's own armed slot on its node, the earliest slot armed beneath a container on
  the container. The log line, the retry (ADR-0125) and the readiness read what the
  unit's own subtree rolls up to — `_subtree` of the whole result — never a
  sibling's; `late.<path>` and the pool's wait name the unit's node; and the
  limits' arithmetic reads a check with units as one view per unit (`_UnitView`),
  each unit's cost over its own period, the check's entries and record once. A unit
  whose **measurement raises** is an `ERROR` on its own node alone
  ([ADR-0078](adr/0078-the-unit-is-what-the-engine-releases.md) decision 4): it
  keeps its last reading, the check is graded over the newest readings it has, and
  the failure — `check error: …`, the failure record placed on the node — is written
  over the unit's node last, its children left where they are; a grading that raises
  is the check's own error, at its root, as it always was. `info()` lists one row per
  unit, each with the path of the node it answers for and its key, so a check's units
  read beneath it on `/system`; `units()` answers every unit with its check and that
  path, for the pin's floor (§5). A unit runs at start as a check does, inside the
  stagger window, and is never armed from the series.
- A **raising check** becomes `ERROR` with `check error: <message>` as its reason —
  **escaped** with `plain()`, since an exception message routinely carries a captured
  line, a path or an API error body ([ADR-0018](adr/0018-markdown-rendering.md)).
  Unless `settings.yaml` sets `stacktrace: false`, a **second reason** carries the
  innermost `TRACEBACK_FRAMES` (5) of the trace as a `code()` block — chained causes
  included, so a `raise X from Y` shows both. The full trace is always in the log
  (`logger.exception`); putting it on the node too means an operator reading the
  dashboard of a cloud deployment does not have to go find the log.
- A **refused record** costs its line or its reading, never the run
  ([ADR-0093](adr/0093-a-record-the-seam-refuses-costs-its-line.md)). `_execute`
  opens `reasons.lenient_records` around `measure()` and around `grade()` — a context
  variable, so the seam is lenient on the run's own thread and strict everywhere
  else, the engine's own records included — and keeps what it marked there. A
  reading marked `refused` is kept out of the grading, keeps the failure record
  naming the refusal, and gets a line from `_refused_lines` naming its subject and
  why, which `_with_lines` adds to the root in the node's own form — a coded `WARN`
  line under `refused-<subject>` where the node's lines carry codes, an uncoded one
  and the node's code raised to `WARN` where it declares one — after the grading's
  leading `ERROR` and `WARN` lines, so the card's budget does not fold away the
  reason for the color. Where no reading passed there is nothing to grade, and the
  run stands as a check that raised: `ERROR`, those lines its reason, no trace. A
  line whose record was refused stands as graded. `_say_refused` holds a `WARN` on
  `/little-sister/runtime` per check and reading and per check and line (§4.8) — a
  line written for the record alone among them, which nothing else would show — and
  `_largest_record` counts the refused records at their size, setting
  `record_refused` where the heaviest was refused for its weight.
- **A check reads its own series, and only while it measures**
  ([ADR-0113](adr/0113-a-measurement-reads-what-its-check-kept.md)). The constructor
  hands every check `partial(self._kept, check)` through `bind_kept`: the window of
  `SeriesKey(check.type_name, check.path, subject)`, each record with a `data` of its
  own, and `()` where the check keeps no series, whatever a state file left behind.
  `_execute` opens `_measuring(check)` — a context variable, as the lenient seam's is —
  around `measure_unit()` and closes it before `grade()`; `_kept` refuses with a `CheckError`
  wherever that mark is not its own check's, so a grading's read stands as a check that
  raised, and so does one from a thread the check started.
- `_execute` runs `check.measure_unit(key)` — `check.measure()`, for the one-unit
  check — and then `check.grade(measurements, now)` over the newest readings with
  an aware UTC instant (ADR-0086), maps any exception or timeout from either to
  `ERROR`, records
  the run's **wall time** on the schedule entry (`elapsed_seconds` — a raising or
  timed-out run keeps its full wait), logs the
  result at **INFO** (`check <path>: <code>[, rolls up to <code>] (<ms>[; <what rose>])
  — <reason>`: the node's own code, and what the result rolls up to beside it wherever
  the two differ — `_rolled_up`, the code a kept reading records for a root that declares
  nothing, [ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md) decision 5;
  what rose while the run was in flight in the parentheses where it rose by 1 MiB or
  more — *What the process holds, in the log* below), and **stores** it
  via `_store` — `_store_path`, for a declared unit, which writes the unit's own
  path and hands the subtree the unit answers for to `_store` — which **upserts**
  the root at `check.path` (`_store_one`, one node) and walks any
  `children` into nodes beneath it (`<parent path>/<child name>`), each inheriting the
  check's frequency, or the unit's period where this is a unit's subtree
  (ADR-0007, ADR-0130). **Where a node of the result says that its children
  are complete, `_store` then removes what that node no longer returns** (ADR-0109):
  `tree.prune` with the names the run returned there — the first segment of a name
  that has several — and, as what it may not touch, the nodes every *other* check owns
  (`owned_nodes()`, [ADR-0015](adr/0015-check-discovery-union.md)) and the instance's
  own branch, read once at construction (`_not_its_own`). It runs after the children
  are written, level by level, and logs one line for each child that went, with how
  many nodes went beneath it. A result that says nothing leaves every child where it
  is. **All of it is one write**
  ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  decision 2): `_execute` holds `tree.storing(answers_for)` around the store, the
  unit's failure over its node included — the tree's lock from the run's first write
  to its last — so every node and row the run writes takes the run's one instant, no
  page, API call or tick sees half a run, and the tree compares the branches above what
  it moved once, when the store ends (§4.4). `answers_for` is the declared unit's own
  node or the check's mount, which the store's end says has run in this process.
  Beside each result it writes the **run facts** —
  `set_run_facts(path, …)` (§4.4, [ADR-0044](adr/0044-run-facts-on-the-node.md)):
  the wall time, and the armed slot projected onto the wall clock once, at write
  time, **after** the retry decision below — so a watched failure's next update
  is the pulled-in slot, never `timestamp + frequency` arithmetic. That clock is the
  engine's `wall`, which answers an instant
  ([ADR-0120](adr/0120-every-stored-time-is-an-instant.md)) and dates the engine's
  start and a run's start as well; one that answers a time without a zone is refused
  where it is read. A one-shot
  `run_once` writes no next slot (no live schedule to project). `_store` carries
  `report` from the **result** at every level, root included — unlike `config`,
  whose root value comes from the check object, what a run found can only come
  from the run — and passes it on every upsert, so a run that finds nothing
  clears what the last one found. It carries the run's **measurement** the same
  way and on the root alone — one where the run read one object, nothing where it
  read several — so a run that measured nothing clears the last reading rather
  than leaving it to be read as today's. Where `measure()` **raised**, what it
  writes is the engine's own failure record, `{"error": …}` against the object the
  check declared, the message clipped once in bytes to at most
  `FAILURE_RECORD_BYTES`; where the *grading* raised over a reading that succeeded, that
  reading stands. Last, `_keep_series` hands each of the run's readings that names a
  subject — its own, or the check's declared object for the one measurement a run
  handed back alone — to the engine's series store (§4.10), where the check's
  `series_keep` is at least one, stamped with the instant the grading was handed and
  with what **stood** where it landed: for the one reading placed on the node, the
  root's code and texts as the result wrote them, or — where the root is a branch
  check's `UNDEFINED` container, silent or saying what it watches — what the result
  rolls up to, beside the root's texts (`_rolled_up`: §4.3's `effective_code` over the
  root and every child the run returned), never read back from the tree, which also
  holds another check's children
  on a shared mount and a child an earlier run left there (ADR-0007), and a pin;
  for one of several, the code and the text of the line whose `data` is its record and
  whose `subject` is its subject, found by `_line_of` among the lines `_lines_of`
  gathers from the result — the shown ones root first and depth first, and behind
  them those a grading wrote for the record alone (`for_record`, ADR-0111 decision
  2), so that a reading both carry keeps what stood on its node — the first line not
  yet claimed winning; for one no line carried that names the object the check
  declared, what the placed one keeps (`_placed`), since it stood on the node too; for
  any other one no line carried, neither; for a refused one among several, the failure
  record beside the engine's line about it, at that line's code. A store that raises is
  a `runtime` line
  (§4.8) and never costs the stored result. A check with
  recorded `secret_errors` (§4.5) is
  **pinned**: `_execute` stores that `ERROR` ("secret unresolvable: …") without
  measuring — no retry until restart, no runtime recorded and no record, since it
  never went ([ADR-0023](adr/0023-secret-references.md)), so its run facts carry a
  real next slot and no wall time.
- `start()` / `stop()` are idempotent; threads are daemons. `run_once()` runs every
  check synchronously (for tests). `create_engine(config_dir)` loads checks into a
  new engine bound to `status_tree`; when the checks aspect resolves but is **empty**
  it still returns an engine, one whose every heartbeat carries a WARN naming the
  directories it searched (§7). `info()` returns runtime state for the `/system`
  page — uptime, pool size, check and unit counts, and per unit its check's type,
  the node it answers for and its key, its period, the in-flight
  run (start + elapsed so far), the armed next slot (projected onto the wall
  clock) and the last completed run (start + wall time); and, as the last tick
  measured them, what the series hold, their ceiling and the projection (§4.10),
  which the page shows as the third line beside the declared load and the entries
  held — and the fourth, what the process held at that tick: the size now, the peak,
  the memory limit and what the machine gives the process
  ([ADR-0095](adr/0095-the-instance-states-its-memory.md)) — and the fifth, what the
  machine had left, with how long it stalled on memory and how often the kernel has
  ended a process of the cgroup, worded as the report words them (decision 7).
- At **construction** the engine tells the tree where each of its checks writes —
  `set_check_mount(check.path)` for every check (§4.4) — so a container above a single
  check can publish that check's run time as its own observation
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)) — registration only, so a
  node still appears when its first result does. The heartbeat below is deliberately
  **not** a mount: it is the engine's own liveness rather than a check, so it neither
  blocks nor feeds that roll-up.
- The scheduler loop is **hardened** (a transient tick error logs and continues),
  and the engine **heartbeats a top-level `little-sister` node** every tick — if the
  scheduler stalls, that node goes stale and red (ADR-0005). Whole-process death is
  left to an external supervisor (launchd / systemd / gunicorn restart). What the
  beat writes is a **stated tolerance** and no `frequency_seconds`
  ([ADR-0081](adr/0081-an-instance-node-states-a-tolerance-not-a-period.md)): nothing
  on this branch is read on a check's schedule, so it publishes no interval, and the
  dead-scheduler window is the same number said as the promise it always was.
- **The beat is a branch that carries the instance's report of itself** (§4.8,
  [ADR-0072](adr/0072-the-instance-reports-on-itself.md),
  [ADR-0076](adr/0076-the-instance-node-is-a-branch.md)): the root
  `/little-sister` is written every tick with the beat and no lines of its own;
  `/little-sister/engine` with the engine's own lines (`no-checks` when the checks
  aspect is empty, the paths it searched as the child's `report`; then the lines
  below); and `/little-sister/<name>` with each registered contributor's, from
  `self_report.current_reports()`. Every child is written every tick — present and
  OK when it has nothing to say — as member entries under the contributor's own
  slugs, **every line carrying a code** and the contributor's facts as the child's
  `report` (ADR-0044 §6, ADR-0076 decision 1: a fact written as a line would carry
  the child's worst code into the roll-up, and arrives instead as a WARN saying it
  belongs in the report), its code derived from its lines, its `title` and `about`
  filled from the registration where `nodes.yaml` said nothing; the root's code is
  the roll-up. The beat is **one write**, as a run is (ADR-0132 decision 2): its
  nodes stored in one `tree.storing(HEARTBEAT_PATH)`, the reports read before it takes
  the lock, so the instance's branch is never compared between two of them, and its
  end stops the carry of an instance node a restart no longer has (§4.4). After the
  expired pins are swept the tick asks `tree.compare_periods()`: what time alone moved
  since the last comparison, and every branch against its kept period. Before any of it
  the tick **sweeps the series** (§4.10) —
  `MemoryStore.sweep`'s one production caller: every series held to its check's
  `series_keep` as it is now, a series whose check keeps none dropped, and whole series
  evicted past `series_limit` — and hands what went to `_observe`; a sweep that raises
  is the `runtime` line `series.sweep` (§4.8) and costs the tick nothing else. The
  tick also drives the state layer's writer (`state.tick()`), last, so a file written
  on the tick holds what the sweep left — and hears whether it ran the interval save,
  which the tick's own memory line says (below) — and `stop()` flushes the kept files once more
  after the scheduler thread is gone — first telling the tree the stop has come
  (`note_stop`), so the log that save writes carries the moment of the stop, which the
  next process dates the instance's gap by (§4.4,
  [ADR-0094](adr/0094-a-restart-is-no-transition.md)).
- **The engine's own lines** — `limits.py`: what the engine measures against its
  limits as it runs, **recorded on its side and read on the tick, never probed**.
  The rule is that a limit the engine enforces is a line it can show, and a limit
  it cannot compute is one it cannot observe either; every line clears when its
  condition does. `Limits` holds the numbers — the constants in `limits.py`, or what
  `settings.yaml` states for the ones a deployment sets (§7) — and `EngineReport` the
  record: the tick's `_observe` hands it the tree's entry count (`entry_count`, a
  counter the tree keeps on its write path, §4.4), the checks waiting for a worker,
  the runs that outgrew their period and what the series hold after the tick's sweep
  (`SeriesHeld`: the weight held, what the sweep evicted, and the projection with
  each check's part in it), and the report measures the one thing
  the engine does not record, the resident size (`limits.resident_size`,
  [ADR-0095](adr/0095-the-instance-states-its-memory.md)): the size now where the
  kernel keeps one (`/proc/self/statm`, Linux) and the peak, the high-water mark
  `getrusage` keeps, raised to the size now where the two disagree — the peak alone
  on macOS, and every surface says *peak* there. It reads what the machine has left
  as well (`limits.machine_left`, ADR-0095 decision 7): `MemAvailable`, and under a
  memory limit what the limit leaves — the limit less the usage with the two lists
  of file pages counted back, `inactive_file` and `active_file` in `memory.stat` (v1's
  `total_` ones) — the smaller of the two; the `total` of the `some` line of
  `/proc/pressure/memory`, of which it keeps ten minutes of readings
  (`STALL_SECONDS`) to say the share in which the machine stalled; and under a limit
  `oom_kill` in the process's own cgroup's `memory.events` (v1's
  `memory.oom_control`). The cgroups are the process's own, as `/proc/self/cgroup`
  names it beneath the mount, and each above it to the root of the mount — a
  container's own at the root, a service's and the slice's above it on a bare host —
  and a limit counts on any of them where it is smaller than the physical memory:
  what is left is the least any leaves, and the smallest limit is what the machine
  gives the process. macOS has neither file, and says none of it.
  The lines, each under a slug of its own on `/little-sister/engine` (ADR-0072
  decision 4, ADR-0076 decision 3 — the path carries the engine's name, not the slug):
  - `entries` — the entry count against `ENTRY_LIMIT` (100,000): WARN at 80 % of
    it, ERROR at it. A constant rather than a share of memory, because at the
    measured half kilobyte an entry the snapshot copied per poll binds long
    before memory does.
  - `memory` — the resident size against half of what the machine gives the
    process (physical memory, or the smallest limit set on the cgroups the process
    runs under, above, where it is smaller — the number that kills the process),
    WARN at 80 %, ERROR at the limit, the machine's figure named beside it. What it
    grades is the size now where the platform keeps one and the peak where that is
    all there is: a line that graded a high-water mark could never clear once it had
    stood. No line where the machine cannot say. **It holds what it saw, as `lag`
    does**
    ([ADR-0095](adr/0095-the-instance-states-its-memory.md)): `observe` puts every
    tick's reading that stands at or past the amber share into a held record (§4.8's
    `Held`) for ten minutes (`MEMORY_HOLD_SECONDS`, the `lag` line's window), with no
    log line of its own, and the line is written from the worst reading inside that
    window — its code, what it was, when it was read (the engine's `wall`, written by
    `spans.local_time`) and, beside it, the size now: *resident size 514 MiB at 09:12,
    past the limit of 504 MiB (now 481 MiB of the 917 MiB the machine gives the
    process)*. So it steps down, ERROR to WARN to nothing, only when the whole window
    stood below, and a process that sits on its limit — past it on one tick, below it
    on the next — changes the node once and not once a tick. A peak is said without a
    time and without a size now, which a high-water mark does not have; and where the
    platform keeps a size now, a tick that could not read it records nothing, since
    the high-water mark is all it has. The size is compared with the limit in bytes,
    and where the sentence would read as though the size were the limit — the two
    figures written as one, or a size below the limit that comes to 100 % of it — it
    says how far apart they are: *97.0 KiB past the limit of 504 MiB*, *1.0 MiB below
    the limit of 504 MiB*. So a size past its limit never reads as equal to it, nor
    one below it.
  - `series` — what every series weighs together (§4.10) against `series_limit`
    (`SERIES_LIMIT`, 8 MiB): WARN at 80 % of it, with what is held; ERROR while a
    sweep in the last ten minutes (`EVICTION_MEMORY_SECONDS`) evicted a series to stay
    under it — curves are being shortened now — naming what went, the series written
    to longest ago first, five and a count, and how many sweeps did it inside the
    window. A held record (§4.8's `Held`), for the `lag` line's reason: an eviction
    shortens a curve for good, and a line gone on the next tick would say so for a
    second.
  - `series.projection` — WARN when what this configuration would need at today's
    estate is past the ceiling: per check that keeps a series, its `series_keep` × the
    series it holds × the mean weight of its kept readings, summed, with the largest
    parts named. Every factor is measured, so the line is there on the first tick
    after the checks' first runs, hours before a slowly filling series reaches the
    ceiling, and it moves with an estate that grows.
  - `pool` — WARN once a check has waited for a worker longer than 10 s, with how
    many are waiting and the longest wait. A check that has never completed a
    run does not count: the first sweep submits every check at once by design,
    and a wait there is the start, not saturation.
  - `lag` — WARN when a tick came more than 5 s late beyond the poll interval,
    standing for ten minutes after the worst late tick inside that window; a
    tick's own work is inside the measurement, so a slow sweep, a lock held by a
    large snapshot, a state flush and a starved process all read the same way.
  - `late.<path>` — WARN per check whose run in flight, measured so far, or whose
    last completed run exceeded its `frequency`; it clears with the next run that
    fits. A run longer than its period is a late run, not a broken one.
  - **The engine's report** (`EngineReport.report()`, the child's `report` field,
    ADR-0076 decision 1) carries what the engine *knows* and does not claim, for the
    life of the process, each beside one warning in the log at load: a check whose
    `timeout` is longer than its `frequency` *may* run late — a shipped example runs
    at 60 s with a 120 s timeout, and it is not refused — and a limit whose
    *declared* sum (below) is at or above 80 % of it and inside it. Neither is a
    line: a declaration claims something about what will happen, and the coded
    line for what did is `late.<path>` or `entries` above, so the node stays OK
    until a run actually does. Beside them stands what the series hold of their
    ceiling and what this configuration would need at today's estate, once either is
    more than nothing — the two figures the `series` lines grade — and the process's
    own, from the first tick on, in the `memory` line's words
    (`limits.resident_text`): *resident size 312 MiB, peak 369 MiB, of a limit of
    8.0 GiB (of the 16.0 GiB the machine gives the process)*, or *peak resident size
    …* where the peak is all there is (ADR-0095 decision 2) — and after it what the
    machine has left, in the words `/system` and the log say it too
    (`limits.machine_text`, decision 7): *the machine has 41 MiB left; it stalled on
    memory for 1.7 % of the last 10m, and the kernel has ended no process of this
    cgroup* — the share of what a process younger than ten minutes has read, named
    as long as it is, none at its first tick, and the count, under a limit only,
    said at none too.
  The path in a line's slug is `slug(path)` (§4.3's declared slug, narrowed to
  `[A-Za-z0-9._-]`), so a line is pinnable per check like any entry. A run is measured on the engine's one
  clock — the `clock` it was constructed with — which is what lets the tick see a
  run's age while it is still in flight.
- **What the process holds, in the log**
  ([ADR-0095](adr/0095-the-instance-states-its-memory.md)). On the first tick past
  each `MEMORY_LINE_MINUTES` (ten) mark of the clock the log is stamped in, the
  configured zone's (§11, *Logging*) — the engine's `wall` read in `config.tzinfo`: an
  instant, and the library's one clock (`instants.now`) unless a caller composed its
  own — the engine
  logs the figures at INFO, as the tick's report recorded them: `engine: memory —
  resident size 312 MiB, peak 369 MiB, of a limit of 8.0 GiB; the series hold 3.1
  MiB, the tree 12,345 entries`, on macOS beginning `peak resident size`, and where
  the platform says what the machine has left, that after the process's figures —
  `…, of a limit of 461 MiB; the machine has 41 MiB left, stalled on memory for 1.7 %
  of the last 10m, and the kernel has ended no process of this cgroup; the series
  hold …`. Once more
  `at the start`, on the first tick, as the baseline, and `at the stop`, read fresh
  after the stop's save — at `stop()`, or at the halt a lost lease forces. A run
  reads the figures (the engine's `resident`, `resident_size` unless a caller
  composed its own) when it starts and when it ends, and its log line carries what
  rose inside the parentheses beside the elapsed time — `resident +38.2 MiB, peak
  +12.1 MiB while it ran, beside /a and /b` — the size's rise where the platform has
  a size now, the peak's everywhere, each from `RISE_LOGGED` (1 MiB) and a fall
  never (`limits.rise_text`). The rises are the process's, so `beside` names every
  other run in flight at any point of it, five and a count: each run's start adds
  itself to the runs already going and them to itself (`_Scheduled.beside`, under
  the engine lock), and a check sharing its mount with another is named with its
  type. **After a run that rose, a collection**
  ([ADR-0095](adr/0095-the-instance-states-its-memory.md) decision 8): where the run
  rose by `RISE_LOGGED` — the size's rise where both reads have a size now, the
  peak's where neither has, as on macOS — the engine calls the cycle collector (its
  `collect`, `gc.collect` unless a caller composed its own), never sooner after the
  end of the last than `COLLECTION_SPACING` (100) times what that one took, and never
  two at once (`_collect_from`, under the engine lock); and the run's line, written
  once it is done, says it after the rise — `; collected after it in 18 ms, resident
  −31.0 MiB` (`limits.collection_text`), the fall from `RISE_LOGGED`, on macOS the
  time alone. A collector that raises is logged and leaves the run as it was. The
  tick is measured the same way, and a tick that raised either figure by
  1 MiB or more logs `engine: resident +12.3 MiB, peak +3.0 MiB during the tick,
  including a state save, beside /web` — *including a state save* where
  `StateLayer.tick()` answered that it ran the interval save. Web requests are not
  measured; a step only a request made shows in the ten-minute line alone.
- **What each check last stored** (§4.9,
  [ADR-0073](adr/0073-a-readiness-answer-beside-health.md)) — one `StatusCode` per
  scheduled check, `None` until its first result lands, written on **every**
  completion. Deliberately not the `last_code` the retry block keeps, which moves
  only when a failure episode ends and stays `UNDEFINED` for a check with no retry
  configured. `Engine.outcomes` reads it under the lock into three counts —
  configured, completed, erroring — which are what the readiness answer's first-pass
  condition and the instance's `all-erroring` line are both made of. Nothing new runs
  on the tick for it.

- **What the configuration declares it costs**, summed at **construction**
  ([ADR-0075](adr/0075-a-check-declares-what-it-costs.md)) — the one thing here that
  is arithmetic before the first tick rather than a measurement after a run. A check
  type may answer `expected_cost()` (worker seconds one run is expected to occupy)
  and `expected_entries()` (reason entries it expects to hold) from its own
  configuration; both default to `None`, and only the library's *dependents* have
  numbers worth declaring — a built-in `http` check costs a fraction of a second, and
  a sum of such estimates would be noise. `limits.capacity()` sums **what is
  declared**: each cost over that check's own period against `max_workers` — the pool
  the engine will actually run, which is the roster's size when that is smaller — and
  the entries against `entry_limit`. Past either, the engine raises `CheckError`
  naming the largest contributors worst-first (five, then a count), which is the
  content failure below: the pages stay up with the banner and no engine runs. At or
  above `amber_share` of a limit it is a log warning and the uncoded line above.
  Because a silent check contributes nothing, the sums are a **lower bound** — enough
  to refuse what cannot fit, and deliberately no promise about what passes. A
  declaration that raises or is not a non-negative number is logged with the check's
  path and treated as absent. The refusal runs **before** the check mounts and the
  heartbeat's metadata are registered, so a refused configuration leaves no half-built
  tree; and `info()` carries the sums, the entries the tree holds now and each check's
  declared figures, so `/system` shows the estimate beside the measurement.

**The start** ([ADR-0091](adr/0091-an-import-is-not-an-instance.md)). Importing
`little_sister.app` builds the application — its configuration, routes and doors —
and writes nothing: no lease, no log file, no engine. `app.start()` does the rest,
once, in the process that serves: it takes the state directory's lease (§4.8) first,
so a process the lease refuses has touched nothing there; opens the log file with what
the import logged (`logger.open_log_file()` writes the first 1,000 buffered records
before anything else, each stamped as it is written there, and counts the rest, which
went to stderr only; then it says once, in that log, where the machine's clock does not
show the time the log is stamped in — §11, *Logging*); resolves
`SECRET_KEY` and `LITTLE_SISTER_API_TOKENS` where they are references — a literal is
read at the import, and a malformed reference still refuses there; and builds,
restores and starts the engine, with `atexit` as the backstop of its stop. gunicorn
reaches it through `little_sister.gunicorn_hooks`'s `post_worker_init`, right after
the worker's import and before it serves; `python -m little_sister.app` calls it
before `app.run` (with `use_reloader=False`, so it starts exactly once). The hooks
module never imports the application — gunicorn loads it in the master — and finds it
in `sys.modules`. A start the lease refuses logs the holder to stderr and raises,
which gunicorn turns into its worker boot error and a halted server.
`LITTLE_SISTER_ENGINE=0` is a server that runs no engine: the start takes no lease
and builds none.

**The stop** ([ADR-0088](adr/0088-a-stop-ends-at-its-save.md)) is
`app.stop(trigger=…)`, reached by the hooks module's `worker_exit` once the worker
has left its loop, with `atexit` as the backstop; a second call does nothing and says
nothing. It stops the engine: the scheduler
ends, the runs in flight are abandoned — a result one delivers later is dropped —
every process group a run started is ended (`process.end_all()`), one INFO line names
the runs it abandoned and what reached the stop, and the state layer makes its one
final save and releases the lease. The checks run on a `DaemonPool` (`pool.py`) whose
threads the interpreter does not join: the standard pool's exit hook joins every
thread it started, whatever its daemon flag, which is what held an exit for the check
in flight.

**A lease taken from this instance halts the engine**
([ADR-0090](adr/0090-one-state-directory-one-writer.md) decision 7). The scheduler
reads `StateLayer.lost` before every tick, and once it names a holder the engine stops
as at a stop but without the save — the directory is the new holder's — logs one
ERROR line, and publishes the `/little-sister` branch a last time, so that the
readiness line says why. The instance goes on serving the last view it had.

Two failures are told apart deliberately. An unusable configuration **tree** — no
configuration directory, a named root that does not exist, an aspect stored in a form
it does not have, or no `checks/` in any root — raises `ConfigError`, which **nothing
catches**: the process refuses to start, and the resolved path it looked at is named
both in the exception and in the log. There is no useful degraded mode when the
instance cannot be right about anything, and a reassuring green page would be the
worst answer ([ADR-0031](adr/0031-deployment-config-directory.md)). `ConfigError` and
`CheckError` are deliberately **unrelated** classes (`errors.py`) rather than a
hierarchy, because one `except` clause is all it would take to lose that distinction.

A start that **fails on content** (`create_engine()` raising `CheckError` — a typo in
one check config) does not stop the web app, but it must not hide in the log either: the
reason is kept in a module-level `engine_error`, injected into every template by a
context processor, and the shared header partial renders it as a persistent red
banner — *"Engine not started — …"* — on every page (the standalone login page
excluded, so nothing leaks pre-login). Until the start has run it says the
application was never started and names the hooks flag, which is all a gunicorn line
without the hooks module ever says (`NOT_STARTED`). It is `None` with a running
engine and on the deliberate `LITTLE_SISTER_ENGINE=0` disable, and clears only with a
restart against a fixed config. The JSON API carries no engine-health signal.

A hung check still occupies a pool worker (Python can't kill threads); the built-in
checks honor their own timeouts, and custom checks must too.

### 4.7 Markdown rendering — `render.py`
Every text the page shows is authored in Markdown and rendered **server-side** to HTML
by **one** configuration of one renderer ([ADR-0018](adr/0018-markdown-rendering.md)
decision 14): a node's `title`, `about`, leaf `description` and `handbook`, each line
(`reason`), what a check ran with (`config`) and what its run found (`report`), and an
admin-authored **maintenance explanation** — so that whoever writes a text never asks
where it will stand. Templates reach it through the `markdown` (block) and
`markdown_inline` (one line, no `<p>`) Jinja filters: a text renders as a block where it
is read whole, and inline where it stands on one line — a title, and a line or a note
summed up in a row of the events, the history, the series or the maintenance popover —
where a table, a list or a heading stays its text.

- `render.py` wraps a single **markdown-it-py** instance configured *safe by
  default*: raw HTML is **escaped** (`html=False`), link schemes are validated (so
  `javascript:` / unsafe `data:` never become links), and every link gets
  `rel="noopener noreferrer"`. Besides CommonMark it draws GitHub's **tables** and
  **strikethrough**, markdown-it-py's own rules enabled, and a table wider than what
  holds it scrolls sideways inside itself (`.md-body table`), in a card, a line and a
  phone's page alike, its cells breaking between words as GitHub's do — the `anywhere`
  of a card or a line, which keeps a long word from widening a phone's page, would
  narrow every column to a letter. **Images** were initially disabled (beacons / mixed
  content) but are **currently enabled** (ADR-0018); untrusted reasons
  stay safe because `plain()` / `code()` escape `[` / `]`, so the exposure is the
  operator-authored fields. The declared `markdown-it-py[linkify]` extra also turns
  fully qualified bare `http://` and `https://` URLs into the same hardened link tokens;
  schemaless domains, email, FTP, protocol-relative text, code spans and `plain()`
  output stay literal. No second sanitizer — the renderer itself is the trust
  boundary. The Content-Security-Policy of §5.4 does not change that: it currently
  reports and blocks nothing, and `img-src` is the directive that would eventually
  bound where an image may come from. Templates
  wrap rendered output in `.md-body`, whose CSS collapses
  the outer block margins so a one-line reason stays as compact as plain text.
- `reasons` can carry **externally-influenced** bytes (a captured command's output,
  an `ssh` error, a remote `df` line). Per ADR-0007 a check owns its reasons, so the
  check base offers two helpers (`little_sister.checks.plain` / `.code`): **`plain()`**
  escapes inline Markdown so a string renders literally — each tilde of a run of two or
  more among it, so that captured text cannot strike itself through, where a lone one,
  a home directory's `~/`, stays clean; a pipe stays as it is, because a table needs a
  delimiter row on a line of its own — and **`code()`** fences
  multi-line / log output as an inert code block (the fence grows past any backtick
  run inside). The built-in capturing checks use them — `command` and
  `ssh-command` / `ssh-script` `code()` their output; the `file` / `http` errors and
  the host-metrics / `qnap` remote strings (mount paths, OS, hostname, SMART status,
  the failure detail) are `plain()`-escaped — so a hostile monitored host can't inject
  formatting or a link through a reason. The raw Markdown (not the HTML) is what the
  JSON envelope carries. Maintenance explanations use the same trust boundary: full
  read surfaces use block rendering, compact banners/popovers use inline rendering and
  CSS clamping, and the editor always receives the untouched source. The literal
  `maintenance` sentinel is not displayed. `maintenance_details.reason` likewise
  remains raw Markdown in JSON; neither persistence nor the API shape changes.
- **A status a text names is drawn as its sign**
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 5): `{ok}`, `{warn}`, `{error}`, `{maintenance}` and `{undefined}`, in either
  case, become the status's cue and its word on the status's own tint (`render.sign`,
  `.ls-sign` and its five modifiers in `overview.css`, measured by
  `tests/test_contrast.py`), in every text the page shows — an about, a description, a
  handbook, a title, a line, a maintenance note. A line's own braces are its template's
  ([ADR-0126](adr/0126-a-line-is-a-template-over-its-record.md)), filled before the line
  is rendered, so what is left of one in the line is the text's. It is an inline rule at
  `{`, after the code span's and the escape's, so `` `{error}` `` and `\{error}` stay
  text, a link's destination and a bare URL keep their braces, and an image's
  alternative text says the status's word (`render._image`); ASCII's case alone, so a
  Kelvin sign is no `k`. The cue refers to the shape the page holds once
  (`cue_sprite`), as the wall's cues do, because the popover's map carries the first
  block of every `about` in every refresh; `_page_end.html` draws the shape on every
  page, so no page that shows a text can be without it. `plain()` escapes a
  placeholder's brace alone, so that a captured `{error}` stays the text it was. Where
  a text leaves the instance it is written out by one function of the library,
  `copy_status.written_out` — *error ⛔*, as the Copy document writes a status — over
  `render.write_out`, which reads the text with the renderer's own parse and rule, a
  block or `inline` as the page renders it, so a placeholder the page shows as written
  stays as written, and so do a reference link's label that names a status, whose
  definition would no longer answer to it, and an image's words; `tests/test_render.py`
  holds it against the page by spoiling one placeholder at a time. The Copy document
  writes out every text it carries so — a line, a maintenance note, a title, what a run
  found and what it ran with — and the function joins §11 when a package outside the
  library first calls it. The JSON envelope carries the placeholder raw, and its
  contract says what it means (2.10.0).
- **A link written in the short form leads into the handbook of the node the text
  belongs to**
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 4): `handbook` to its top, `handbook#sign-in` to a section. The two filters
  take `node`, the path of the node a text belongs to, which every template that shows
  a node's text passes — the card, a line on the wall and on its page, a title, a
  maintenance note, a row of the events and of a node's history — and the popover's map
  passes to `first_block`; the app hands the renderer what says that node's handbook's
  address (`_handbook_of`), which it asks only where it meets such a link. The rule that
  sets every link's target rewrites its `href` (`render._harden_links`), so the link
  opens a tab of its own as every other does; on the handbook's own page, rendered with
  `anchors`, it is a section of the page itself and stays in it; and in a text that
  belongs to no node — a note on the links page, a reading's sentences in its table,
  where a row does not say which node it was placed on — it leads nowhere: its words
  stand, and no link (`render._close_link`). markdown-it's own link rule is wrapped
  (`render._link`) so that a link also says where its destination stands in its text, and
  `render.write_out` writes a short form out to an address — in the link, or in the
  definition of its reference (`render._defined`) — as it writes a sign out, with the
  same parse, so a link in code or escaped stays as written; the address's parentheses
  are written as the URL's own escapes. `render.short_links` says where each link a text
  writes so leads and `render.anchors_of` which sections a handbook's page anchors, which
  is what the startup record compares (§4.5).
- **A handbook's headings are anchored as GitHub anchors them**
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 3), where the caller passes `anchors=True` (`render_markdown` and the
  `markdown` filter's `anchors` argument), which the Handbook view alone does: a core
  rule after every rule that makes a heading's words gives each heading the `id` of
  `render.anchor` — its words as a reader sees them, a code span's, a link's and a
  sign's word among them, in lower case, each space a hyphen, every character but a
  letter, a mark, a digit, `-` and `_` dropped — and a heading whose anchor an earlier
  one took that anchor with `-1`, `-2` after it, so `## Sign in` is `#sign-in` as on
  GitHub. A heading of no anchor has none. A link to a section of the page itself,
  `#sign-in`, navigates nowhere and stays in the page, where every other link opens a
  tab of its own. An anchored heading stops beneath the sticky bar when a link opens it
  (`scroll-margin-top`, `.ls-handbook`).

### 4.8 The state layer and the self-report — `state.py`, `self_report.py`

What a restart keeps is a **directory of JSON files**, `var/state/`
([ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)): a fixed
path relative to the working directory, git-ignored, not env-overridable. Two write
disciplines, one atomic write, and a seam for what the instance says about itself.
**The name says the encoding**
([ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md)): the event log and the
series are compact JSON with sorted keys under gzip at level 1 and `mtime=0` —
`events.json.gz` and `series.json.gz`, which `gzip -dc` reads — so the same state
gives the same bytes, and `pins.json` stays plain.

- `StateLayer(directory, interval_seconds, keeper_interval_seconds)` owns the
  directory. `read(name)` returns the parsed file, decoded as its name says and
  without its generation, or `None` for a file that is not there (a first start) —
  and also for one that cannot be read or does not decode — not JSON, or for a
  compressed one not gzip, cut short or damaged — which is a **load failure** the
  layer records and logs; a reader that finds a shape it cannot use says so with
  `report_load_failure(name, detail)`. `write(name, payload)` is the
  **write-through** discipline — a temp file in the same directory and
  `os.replace`, never raised, the outcome recorded, the keeper handed it at the next
  scheduler tick. `keep(name, producer)` registers
  a **kept** file: `tick()`, called by the engine every scheduler tick, writes every
  kept file at most once per `state_interval` (`settings.yaml`, default 60 s, §7)
  and only when its content changed — which it tells by a digest of the content
  without its generation, as it last wrote it or as an adoption put it in place, so
  the process holds no copy of any file's text between saves — and answers whether
  it ran that save (ADR-0095 decision 5); `flush()` writes them once more at graceful
  shutdown, and before and after an action. A producer copies under its own lock and returns — the layer
  is never inside the tree's lock for longer than the copy takes (ADR-0002).
  **Every file the layer writes carries its generation**
  ([ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md) decision 4), a
  top-level `generation` beside the file's tables: `writer`, this instance's mark
  (ADR-0074); `count`, that writer's writes of that file, from 1; and `held`, whether
  the keeper took its saves the interval before — false at a start's first write,
  true where no keeper is registered. The count moves with the content and never
  alone, every reader is handed the tables without it, and a release before passes
  over it, since its readers take a file's tables by name.
  **Every file may have the other direction too**
  ([ADR-0077](adr/0077-authority-follows-the-lease.md)): `keep(name, producer,
  restore=…)` or, for a file written through, `restore_with(name, restore)` — a
  callable that takes the parsed payload of a copy adopted at runtime and replaces
  what the process holds, under the process's own lock and no longer than the swap.
  `take_stock()` reads the directory once at startup — which files are there, when
  each was written, which `.bak` an earlier process set aside — so the report never
  has to.
- **One writer** ([ADR-0090](adr/0090-one-state-directory-one-writer.md)).
  `var/state.lease`, beside the directory, names the process that writes it — its mark,
  host, pid and kernel — and that process rewrites it every 10 s from a thread of its
  own; it lapses at 30 s. How the holder came by it (`taken`) and whether it still holds
  it (`state`, `held` or `released`) are two fields, and only `state` decides: a
  graceful restart takes a released lease and holds it. `var/state.lock` is an exclusive
  `flock` the holder keeps for its life. Under one kernel the lock decides; across
  kernels — the device VM's mount of a Mac's checkout — the heartbeat does, a lapsed
  lease being watched for one more beat. `Lease` (`lease.py`) is taken by the server's
  start before anything reads the directory, refusing with `LeaseRefused` rather than
  standing by, and `hold(lease)` makes every write ask it first: a layer whose lease was
  taken writes nothing more and says who holds the directory (`lost`), the engine halts
  (§4.6), and the readiness node says so (§4.9). `shutdown()`, the stop's one save,
  closes the layer, so nothing writes after it, and releases the lease. `take()` first
  reads when the lease file was last written — `previous_beat`, the previous holder's
  last beat or its release, whether it stopped or crashed — which dates the gap a
  restart leaves on the instance's own node (§4.4,
  [ADR-0094](adr/0094-a-restart-is-no-transition.md)).
- **The files today**: `pins.json` (written through by the tree's `PinStore`, §4.4;
  in place of `maintenance.json`, a clean break — the old name is retired, as the plain
  `events.json` and `series.json` are, and named once at startup;
  [ADR-0141](adr/0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md) decision 1) and `events.json.gz` (kept:
  `status_tree.events_payload`, restored by `app._restore_state` before the pins
  are replayed, so this process's first transitions append to yesterday's; beside the
  rows it carries what every node last showed, §4.4) and
  `series.json.gz` (kept: the engine's `MemoryStore.payload`, restored by
  `app._restore_series` once `_restore_state` has fetched what a keeper holds, and
  registered with the store's `restore` for an adoption or *take the backups* — §4.10,
  [ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md) decision 9). A series
  file of another shape is `load.series.json.gz` and the series start empty; one older
  than the configuration is met by the first tick's sweep. Run facts stay ephemeral.
  `notes.json` is written through, as the pins' file is: `notes.notes_book` holds every
  node's notes by path and writes the file on every change through `NoteStore`, which
  `app._restore_notes` reads after the series, for every path the file holds, and
  registers for an adoption
  ([ADR-0140](adr/0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) decision 7).
  **`events.json` and `series.json` are
  retired names** ([ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md)
  decision 2), never read: `take_stock()` names one it finds without its successor
  in the log at WARN and as a WARN `load.<name>` line for the life of the process,
  and a takeover that adopts one from a holder of a release before writes it in
  place under the same line. The plain copies stay beside the compressed ones,
  mirrored like any file, for a rollback.
- **A failure never refuses to start, and is never silent.** `lines()` is the
  layer's self-report: per file, `load.<file>` at ERROR for as long as the process
  runs (what the file held before the restart is not in force) and `save.<file>`
  at WARN until a write of that file succeeds (nothing is lost yet; the next
  restart is). The same two slugs carry what an adoption leaves standing, with
  *adopt* as the verb — ERROR for a copy the process could not take in, WARN for
  one written to disk with nothing registered to take it — and a retired name's
  line, at WARN. The `.bak` files are the
  child's **report** (`StateLayer.report()`, ADR-0076 decision 1), one item each:
  when it was last written beside when the live copy was, both local files on one
  clock. Recorded state, read — neither touches the disk.
- **Authority follows the lease** ([ADR-0077](adr/0077-authority-follows-the-lease.md)).
  When the keeper's `tick` turns from *not taking saves* to *taking them* — a
  standby became the holder, a demoted holder took the lease back, or the first
  interval a keeper takes at all — `flush()` asks the keeper's optional
  `changed_since_sync()` and adopts every file it names before this interval's
  first save: parsed and handed to its `restore`, then the live file set aside as
  `<file>.bak` (an older one overwritten) and the store's copy written in its
  place — the temporary file written first, so a disk that refuses moves nothing —
  and the mirror's digest seeded so it is not sent back until it changes. A file
  whose adoption failed is **held out of the mirror** until one lands, since its
  local copy is the shadow the rule forbids saving over the store, and is adopted
  again by name every interval the keeper takes saves. A keeper that names nothing,
  or has no such method, makes it a silent takeover with the instance's own state.
  A `.bak` is this machine's own: never mirrored, and refused from a keeper's
  listing like a walk upwards. The `restore` callables live in one registry, filled
  by their owners — the tree's `adopt_events` beside the log's producer, the
  side-table's by `PinStore(state, tree=…)` at construction, and the series
  store's `restore` beside its producer.
  **`take_backups()`** is the way back and the layer's one action on its child —
  *take the backups*, admin-only, `POST /little-sister/state/act/take-backups`: for
  every `.bak` beside a file the layer keeps or restores, the live file is set aside
  as `.bak` in turn and the backup adopted through the same path, so the mirror then
  takes what came back; a `.bak` matching no registered file is listed and left
  alone. The flush and the button are serialized on a lock of their own, and a pin
  written through never waits on it.
- **The self-report seam** ([ADR-0072](adr/0072-the-instance-reports-on-itself.md)):
  `self_report.register_contributor(name, callable)` claims a name under
  ADR-0064's rules (the calling package inferred and recorded, the same package
  replaces silently, another package refuses unless `replace=True`, the replacement
  remembered); `current_lines()` asks each contributor for its current entries and
  prefixes every slug with the name, which is a reader's flat view of what the
  children carry — a pin holds against the child and the bare slug
  (`/little-sister/state` + `load.pins.json`), never the flat form. A
  contributor that raises, or answers with something that is not lines, is logged
  and stands as one WARN line `<name>.raised` — the beat still lands. A report
  **clears**: a line the contributor stops returning is gone, and the node's code
  follows. `/system/installed` prints `report <name>` on the package's
  inventory row. The application registers the state layer as `state` in
  `_restore_state`; a package or a deployment registers its own in the
  import-before-app block, beside its resolvers.
  - **Each contributor is a child of `/little-sister`**
    ([ADR-0076](adr/0076-the-instance-node-is-a-branch.md)): `current_reports()`
    answers one `Report` per contributor — `name`, `title`, `about`, and its lines
    under the contributor's **own** slugs — which the engine writes onto
    `/little-sister/<name>` every tick; `current_lines()` is the flat view with the
    `<name>.<slug>` prefix. `register_contributor(name, lines, title=…, about=…,
    report=…)` declares the child's labels, filled where `nodes.yaml` said nothing,
    and the contributor's **report** — a callable answering Markdown, the child's
    `report` field (ADR-0044 §6), for what the contributor knows and does not claim:
    `state.report` lists the `.bak` files, `security_report` the failed logins
    below the rate, `EngineReport.report` the configurations that may run late and
    the declared load near a limit. A report that raises is the `raised` stand-in
    beside the lines. **Every line carries a code**; one without is refused into a
    WARN under its own slug that says so (ADR-0076 decision 1).
  - **An action per child**: `register_action(contributor, slug, label, handler)`
    claims one under the contributor's rules; `actions_for()` and `find_action()`
    are what the filler and the route read; the handler takes nothing and answers
    the sentence the page shows, or raises and the label and error are the sentence.
    Run by `POST /little-sister/<contributor>/act/<slug>` (§5), admin-only, and
    **between two `state_layer.flush()`es** (ADR-0076 decision 6,
    [ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md) decision 6): the one
    before the handler sends the keeper what the process holds while the lease is
    still its own — a keeper's *release* gives it up in its handler — and the one
    after, where the handler returned, what the action changed, now and not at the
    next interval, so a keeper's take-over adopts and saves in the click. Each sends
    everything, whatever `keeper_interval` says.
  - **Two records, one call each** (ADR-0072 §7): `Standing` keeps lines for the
    life of the process — `note(slug, text, code=WARN)` records and logs at the
    line's severity (a `StatusCode`, never `None`: a fact is the report's), one line
    per slug, a second note on a slug replacing the first
    — and the library's own is `self_report.startup`, registered as `startup`
    beside `readiness`. `Held(hold_seconds)` keeps occurrences of what recurs —
    `see(slug, text, code=WARN, measure=None, now=None)` records and logs one — for
    the window after each, and with `log=False` records it alone, where the call site
    has logged already or the occurrence comes every tick; `lines()` writes the plain
    line per slug (the latest text, *n times in the last …* where there was more than
    one), and `worst()`, `latest()`, `count()` and `slugs()` are for a contributor that
    writes its own sentence, as the engine's `lag` and `memory` lines do from the worst
    measure inside the window. Every method takes `now` so a caller with the engine's
    clock in hand gives it; the clock is otherwise monotonic and injectable.
  - **The library's three, registered in `app.py`**: `startup` (a `Standing`) for
    what the process learned at startup — an unresolved `SECRET_KEY` or
    `LITTLE_SISTER_API_TOKENS` reference, no identity door or none the default
    (ERROR where nobody can sign in), the system-admin password unresolved, a
    `config/` file no aspect claims, an aspect declared in two roots or refused at
    registration, `instance:` refused, `retry_interval` unreadable, `nodes.yaml`
    metadata no check covers or the file not loaded,
    an avatar not shown, the retired maintenance file, a slot template, asset, icon
    or action refused, a noise cap refused, the theme bootstrap's hash missing;
    `runtime` (a `Held`, ten
    minutes) for what recurs — a slot's provider or template raising, an identity
    door raising, a scheduler tick, an upsert, a series store or its sweep raising;
    and `security` (a
    `Held`, ten minutes, graded by `security_lines`) — failed logins as a rate, a
    fact below five in the window and WARN from five, and the system-admin account
    used.
    `plain()` lives in `little_sister.reasons` so these sites can fold a path or an
    error into a line; `little_sister.checks.plain` is the same function. Three sites
    stay log-only and say why in place: an entry of `LOG_LEVEL` that cannot be read
    (`logger.py`, beneath the seam; §11 says where it is listed), a machine whose
    clock is not the one the log is stamped in (`logger.py`:
    a note would stand for the life of the process on a machine whose zone is another
    on purpose) and an engine that did not start (no tick to read a line on).
- **The keeper** (`keeper.py`) — a file store that mirrors the whole directory to
  somewhere durable **without knowing what it carries**: `load(name)`,
  `save(name, data)`, `list()`, in bytes, so it moves `events.json.gz` and a package's
  sqlite file with the same code. `register_keeper(name, keeper)` claims the seam in
  the import-before-app slot under ADR-0064's rules, and there is **one slot rather
  than one per name** — two keepers would each carry a copy of what the other wrote,
  and import order would decide which one a restart came back as. `/system/installed` lists it
  on the registering package's row, which is the only place a working keeper is
  visible: it says nothing until it fails.
  - `restore_from_keeper()` runs **first** in `_restore_state`, before any file is
    read, so a fresh machine comes up as the instance that stopped on the old one.
    What the keeper holds wins over a local file of the same name — the point on a
    new machine — but for one case
    ([ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md) decision 5): a local
    copy whose generation names the same writer as the store's, a higher count and
    `held` is the dead worker's newer state when the next starts on the same disk,
    and stays. Every copy is loaded all the same, so the keeper notes the store's
    token and the flip that follows names nothing for it and sends it up. A name that
    is not a plain file name is refused: it
    arrives from outside the library and is used as a path component.
  - The mirror runs **after** the writer, on the same interval and once more at
    shutdown, sending every file in the directory — including one no producer here
    registered — and skipping a file whose bytes the keeper already took, **in two
    cadences** ([ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md) decision
    6). A file written through — the pins — goes at the next scheduler tick after it
    changes, through the keeper's `push` where it has one and the keeper took the last
    interval's saves, and with the interval's saves otherwise. A kept file — the event
    log and the series — goes every interval while the keeper's `standing_by()` says
    another instance stands by, and while nobody does once `keeper_interval`
    (`settings.yaml`, default 900 s, §7) has passed since its last send. The flip's
    save, the stop's and the two flushes an action runs between send everything at
    once; the keeper's `tick` and the local files stay on `state_interval`.
  - **Five methods a keeper may answer**, looked for by name (`keeper.takes_saves`,
    `keeper.close_keeper`, `keeper.changed_since_sync`, `keeper.push`,
    `keeper.standing_by`):
    `tick(interval_seconds) -> bool`, called by `flush()` every interval *before*
    any save, whether or not a file changed — where a store
    that holds a lease on its prefix renews it, and one that is not the holder reads
    who is — whose answer says whether this interval's saves are wanted at all
    (`False` sends nothing and leaves every file marked not yet taken, so the next
    `True` sends what changed meanwhile; not a failure, and no line of the layer's —
    the keeper says why through its own contributor); and `close()`, from
    `shutdown()` after the last flush, the one signal that the process is ending on
    purpose, so a lease can be given up rather than left to lapse; and
    `changed_since_sync() -> Sequence[str]`, asked once at the moment `tick` turns
    from declining to taking, naming the files whose copy in the store differs from
    what this instance last restored or saved, by a token the library never sees —
    what the layer then adopts ([ADR-0077](adr/0077-authority-follows-the-lease.md));
    `push(name, data)`, a save between two ticks, which a keeper lands only while it
    holds its store; and `standing_by() -> bool`, asked after the tick, whether another
    instance stands by ([ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md)).
    A keeper without them is called as before: without `push` it is handed the pins
    with the interval's saves, and without `standing_by()` it counts as always watched.
  - **A failure never refuses to start and is never silent**, exactly as for a local
    file: a keeper that cannot be reached leaves every local file as it is and is
    `keeper.load` at ERROR for the life of the process; a save it would not take is
    `keeper.save.<file>` at WARN until one of that file lands — *nothing is lost yet,
    the next machine is*; a `tick` that raises is `keeper.tick` at WARN, with no save
    behind it that interval, until one returns. A `push` that raises is the file's
    `keeper.save.<file>`, and the interval's saves send it again; a `standing_by()`
    that raises counts as watched and is `keeper.standing_by` at WARN until it
    answers. Nothing a keeper raises reaches the tick.
  - Two obligations the seam cannot enforce, stated in `keeper.py` for whoever writes
    one: **bound the client in seconds**, because saving and `tick` run on the
    scheduler tick, and **say it rather than merging it away** — two instances against
    one store is not resolved by merging files; whatever the keeper does instead (the
    S3 keeper holds a lease and puts the other instance in standby, little-sister-aws
    ADR-0004), the operator is told through the self-report seam. The library ships
    no keeper; a local installation registers none and loses nothing by it.

### 4.9 Readiness, and what the instance can see — `readiness.py`

`/health` answers *is this process serving* and deliberately nothing else
([ADR-0066](adr/0066-health-answers-liveness-and-says-almost-nothing.md)). This module
answers the other half — *has this instance finished coming up* — and holds, beside it,
the two lines the instance says about its own ability to observe anything at all
([ADR-0073](adr/0073-a-readiness-answer-beside-health.md)).

- **`Readiness`** takes the three conditions as callables, because two of them are only
  settled after the application has finished importing, and answers an `Answer`:
  `ready`, or the words it is waiting for. `app.py` composes it once and the route in
  §5.1 renders it.
  - **`doors`** — `identity.registered_doors()` is not empty (§5.2).
  - **`trust`** — `measure_trust_store()` found a usable trust source among the
    default TLS verification paths: a `cafile` that exists and is not empty, or a
    `capath` holding at least one hashed entry that resolves to a file. Asked of the
    paths and never of a context, because OpenSSL consults a hash directory by subject
    hash when it verifies a chain and never loads it, so a count of what a context had
    loaded read a populated `/etc/ssl/certs` as empty (ADR-0073).
    Measured **once**, at startup, and it is the only thing here that touches the
    machine; a measurement that raised answers `TrustStore(None)`, which is *unknown*
    and never reported as empty.
  - **`first-pass`** — `Engine.outcomes.first_pass` (§4.6): every configured check has
    stored a result. An engine switched off with `LITTLE_SISTER_ENGINE=0` has no pass
    to wait for and is ready; one that could not load its configuration, or was never
    started, never is, and `app.py`'s `_first_pass_done` is where the two stop being
    one answer.
- **The answer latches.** All three are startup facts; once they hold the conditions
  are not asked again and no later failure takes the answer back. That is what stops a
  readiness route from withdrawing a *serving* instance and removing the very page
  whose banner explains what broke, which is the thing ADR-0066 refused to build.
- **`Outcomes`** is what the engine records for both: `configured`, `completed` and
  `erroring`, from the code each check **last stored** — a field per scheduled check,
  set on every completion and read under the engine's lock. The counts satisfy
  `erroring <= completed <= configured`, which is why `all_erroring` needs no separate
  first-pass guard.
- **Three lines on the seam** (§4.8), registered as `readiness`, recorded state read on
  the tick. `readiness.saves` at ERROR (*this instance runs no more checks and saves
  nothing*, naming who holds the state directory now) stands from the moment the lease
  was taken from this instance for the life of the process
  ([ADR-0090](adr/0090-one-state-directory-one-writer.md)). The other two clear when
  their condition does: `readiness.trust` at ERROR (*the
  machine's trust store holds no CA certificates*, so every check reading an `https`
  address fails on the certificate rather than on the subject) and
  `readiness.all-erroring` at WARN (*every check this instance runs is erroring, all N
  of them*, where N is more than one — a reading of the **pattern**, not a second red
  for failures their own nodes already report). Neither is the readiness answer: why an
  instance did not become ready is the startup log and `/system`, where the reader has
  said who they are.

### 4.10 The series — `series.py`

A reading that names its subject is kept in that subject's **series** — its records
over time — by the check that took it
([ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md)). Memory is the tier this
module holds, and the only one there is; the state layer keeps it in a file of its own
(§4.8), and a ceiling bounds everything it holds together (§4.6's `series` lines).

- **The key** is `SeriesKey(type_name, mount, subject)`: the check by its type and its
  mount, because one mount carries two checks of different shape by design (§4.5,
  [ADR-0015](adr/0015-check-discovery-union.md)), and the subject the reading names. A
  reading with no subject has no series; the engine decides the subject exactly as it
  places a measurement on a node (§4.6).
- **The unit** is a `SeriesRecord`: the record as the measurement's seam normalized it
  (`data`, never written to again), when the engine took the reading (`observed_at`,
  an aware instant held in UTC — the one the grading was handed), the measurement's
  `identity` or its `state`, at most one of them set and both empty for a reading that
  is always a new one, and what **stood** where
  the reading landed — `code`, a `StatusCode` or `None`, and `texts`, the line's text
  or the node's — as the engine found them (§4.6, ADR-0087 decision 8): `None` and
  empty for a reading no line carried that names another object than its check's.
- **The seam** is the `SeriesStore` protocol, three operations. `add(key, record,
  keep=n)` replaces the record of the same identity wherever the kept window holds one,
  or the newest record where the record names a state and that one is in the same state,
  and appends otherwise, then holds the series to *n*, the oldest out; a count below one
  is refused, since a check that keeps none has no series and the engine never asks.
  `window(key)` answers the kept records oldest first, empty for a series that does not
  exist. `sweep(keep, ceiling=…)` holds every series to the count a callable answers
  for it now and drops each series whose check keeps none — for what is held when a
  retention changed under it, since `add` already holds its own series to its count —
  and then, given a ceiling in bytes, **evicts whole series** until what is held fits:
  the one written to longest ago first, by the newest `observed_at` a reading brought
  it, a tie broken by the key so a sweep is repeatable. It answers a `Swept` — how many
  records it trimmed, which series it dropped, which it evicted in the order they went
  and what those weighed. The counts are asked outside the store's lock. The engine
  sweeps on every tick (§4.6).
- **A check's own read is the engine's**, not a fourth operation: `Engine._kept` copies
  what `window(key)` answers for the check's own key (§4.6,
  [ADR-0113](adr/0113-a-measurement-reads-what-its-check-kept.md)), so a type never
  holds what the store holds.
- **One read more on the memory tier**: `placed(key)`, the window with each record's
  **place** — a `Placed(record, at)`, where `at` is the instant the series orders the
  record by (below): its own `at`, or when it was first observed, which a replacement
  does not move and which the record itself does not carry. It is what the curves
  are drawn from and the readings listed (§4.11), and the pages read this tier.
  `subjects(type_name, mount)` names every subject a check's series are kept for.
- **The memory tier** is `MemoryStore`, one per engine (`Engine.series`), holding one
  window per series under its own lock: the engine adds from its pool's workers and
  sweeps from the scheduler, and a reader copies under the same lock. Every kept
  reading is **weighed** as the file keeps it — the bytes of its `json.dumps`, the
  spelling `record_limit` weighs a record in — and the store keeps the sum as it adds,
  replaces, trims and evicts: `held()` is what the ceiling is measured against, and
  `usage()` answers per check, by type and mount, the series, the readings and the
  bytes a projection is made of.
- **The file.** `payload()` is the producer of `series.json.gz` (§4.8): every series in
  key order, each reading as `data`, `observed_at` in UTC with a `Z`, `identity`, the
  `code` by name or `null`, `texts`, `state` only where the reading names one, and
  `first_observed_at` only where a replacement moved `observed_at` past it.
  `restore(payload)` replaces everything held with a
  payload read whole first — a shape it does not know is a `ValueError` naming what is
  wrong, and the store keeps what it held — and leaves this configuration's retention
  to the next sweep, since the file may be older than the configuration reading it.
- **Order.** A window is sorted by the record's own time — its top-level `at`, which the
  seam has already converted to UTC — and, where it has none, by when the record was
  first observed, ties in arrival order. A record replaced by its identity or its state
  keeps its place unless its own time moves it, and one older than every record of a
  full window is not
  kept at all. A time nested deeper (`modified.at`, a run block's `started`) is a value
  the record carries and orders nothing.
- **Retention** is the check's `series_keep`, read by `_parse_common` for every type
  (§4.5) — a whole number, `0` when absent, junk and negatives refused at load — with
  no settings key: where a history is wanted is a choice per check. It bounds each
  series; `series_limit` (§7) bounds all of them together, and the projection says on
  the first tick when this configuration will not fit it (§4.6).

### 4.11 Measures and curves — `measures.py`, `curves.py`

A series is drawn on the nodes its measures name, and all of it on the Series view of
the node above them
([ADR-0092](adr/0092-a-check-declares-its-measures.md),
[ADR-0096](adr/0096-a-measure-names-its-node-and-its-things.md),
[ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md)).

- **A measure is declared.** A `Measure(field, unit, label, node, axis_to)` is a projection over
  the record ([ADR-0085](adr/0085-a-measure-is-read-out-of-a-record.md)): the field's
  dotted name, spelled as the record list spells it (§4.5) — `Measure.read` walks the
  record with the same `reasons.record_leaves`, and a field the record does not have
  reads as null — its unit, what its curve is titled, the field's own name where
  nothing was given, and the **node** the curve stands on: a path from the check's own
  node (`memory`, `disk/root`), and that node itself where it names none — and, where
  it declares one, **where its value axis reaches** (`axis_to`, 100 for a percent of a
  whole): the axis of its curve and its sparkline ends there whatever the readings are
  below it, so two of one kind compare, and a reading above it grows the axis as one
  without the key does ([ADR-0117](adr/0117-a-measure-says-where-its-axis-reaches.md)).
  A type passes
  `measure_defaults` to `Check.__init__`, shaped like the YAML block; a deployment
  writes `measures:` in the check's YAML, read by `_parse_common` for every type. Both
  are `read_measures`' shape — a field name to a unit, or to `{unit, label, node, axis_to}` —
  and `resolve_measures` merges them **per field** in the constructor, once: a field
  the configuration names takes its entry, `null` removes a default, every other
  field keeps it, and the defaults come first in the order the type declared them.
  `check.measures` is the answer; a block of another shape — a unit that is not text,
  a name that is not a field's, a node that is not a path down (an empty segment,
  `.`, `..`), `null` in a type's declaration — is a `CheckError` that the loader
  prefixes with the file (§4.5). `http` declares `response_ms` in `ms`, labeled
  *Response time*; `host-metrics`, `qnap-metrics` and `macos-memory` declare the
  numbers they grade, each on the aspect that grades it (ADR-0096 decision 6).
- **A `*` picks a key.** A record keys the things it counts by the names of the nodes
  they become — `host-metrics`' `volumes: {root: {path, pct, avail_kb, total_kb}}`,
  `qnap-metrics`' `drives: {drive3: {bay, temp_c, smart}}`, `macos-memory`'s
  `processes: {mail: {count, rss_kb, elapsed_seconds}}` — never by where a thing stood
  in one run's output, which would move a curve to another thing the day the order
  did. A field may carry one whole `*` segment (`volumes.*.pct`), and its node and its
  label may write it too (`disk/*`, `Used on *`); `Measure.expand(records)` answers
  the plain measures a declaration stands for — itself without a `*`, and otherwise
  one for every key the mapping at the `*` holds in any of the records, in the order
  the keys first appear, the key standing in for the `*` in the field, the node and
  the label. A `*` in the node or the label of a field without one is refused. It
  picks and never computes.
- **A unit is free text** and is never refused. `Measure.write` prints a number with
  the unit beside it — whole numbers with separators, fractions at three significant
  figures — except for the family's units: `ms` and `s` are written as a span through
  `spans.format_span` (1,850 ms reads `1.9 s`), and `B`, `KiB`, `MiB`, `GiB` and `TiB`
  (`SIZE_UNITS`) as a size through `limits.format_weight` (19,169,728 KiB reads
  `18.3 GiB`), a negative one keeping its sign. They name their unit in every value, so
  `axis_unit` is empty for them and the unit itself for every other; a size written
  for an axis tick drops the tenth a whole unit does not need (`512 MiB`). `kB`, `MB`
  and `GB` are not among them: whether `MB` is 10⁶ or 2²⁰ is the guess a family unit is
  there to remove.
- **`reading_cap`** — how many readings of each series the Series view lists beneath
  its curves — is the check's own where its YAML states one (`_parse_reading_cap`: a
  whole number, `0` allowed, junk refused at load) and `settings.yaml`'s otherwise
  (§7: 10 by default, a bad value logged and replaced). The page resolves the two.
- **The curve** is `curves.draw(measure, readings, tolerance=…, span=…, times=…)` — pure
  arithmetic over a series' placed window that a template writes as SVG, on the
  server, with no script. A reading sits at its place, to scale on a time axis
  spanning the window — or `span`, where a page draws several curves on one axis —
  and its value to scale from a baseline at zero (below it where a value is), the
  axis stepping in about four clean steps: a span somebody would name for a span unit
  (500 ms, 15m, 2h), a power of two of a byte for a size unit (256 MiB, 512 MiB,
  1 GiB). A reading that **failed** — its record carries an `error` that is not null:
  the engine's for a check that raised, the seam's for a record it refused, and each
  metrics type's for a reading that did not answer (`SshCheckBase._say_it_failed`) —
  breaks the line and is a `Mark` in a lane beneath the baseline, never a zero; a
  reading that answered without a number for this measure breaks it with no mark. Two
  neighbors further apart than `tolerance` — the tolerance the check's own period
  implies (`tree.stale_after_seconds`,
  [ADR-0079](adr/0079-freshness-is-a-stated-tolerance.md)), which is its node's where
  the check alone writes that node — are a **hole**, and the line breaks there with no
  mark. A node two checks share carries the period of whichever wrote it last, which
  is why the page asks the check. The line never crosses a break: its `runs` are the
  unbroken stretches of two readings or more, a reading standing alone between two
  breaks is a dot, and `end` is the newest reading where it has a value. `failed`,
  `unvalued` and `valued` count the three kinds of reading, and a measure with nothing
  valued has no curve to draw. The `hover` strips cut the plot between neighbors'
  midpoints, each titled with a reading's time and its value — or `failed`, or
  `no value`; the times read in the configured zone and format (§7). Every instant a
  curve writes, those titles and the axis ends, it writes through `times`,
  `spans.local_time` unless the caller hands another. A page hands its curves
  `app._times()`, one writing that remembers each instant for as long as the page is
  rendered, since the curves of one series are drawn over the same readings and
  formatting an instant costs more on macOS than the rest of a curve: a reading's time
  is formatted once however many curves are drawn over it, and a Series view's range
  and its tables of readings share the same writing.
- **The time axis** is labeled by `curves.time_labels(first, last)` at round times in
  the configured timezone ([ADR-0098](adr/0098-a-series-view-is-drawn-over-a-window.md)
  decision 4): the smallest step of the ladder 1m, 2m, 5m, 15m, 30m, 1h, 3h, 6h, 12h, 1d,
  2d, 1w, a month, a quarter, 1y, 2y and 5y that puts no more than six labels strictly
  between the ends, walked on the local clock from the round time before `first` — a
  time the clock skipped is not labeled, and one it read twice is labeled the first
  time — and each label as short as its step allows: `14:00`, the date `09-30` at a
  midnight and for days and weeks, `2026-09`, `2026`. Everything is compared and
  subtracted in UTC, because two instants of one zone subtract as their clocks read.
  A curve carries its `time_ticks`, a faint line across the plot for each, and its
  `stretches`, the spans between two labels and from an end to the label nearest it;
  the template draws the time axis as a drawing of its own beneath the plot
  (`AXIS_HEIGHT`), so that on a Series view each stretch can be a link into the window
  it spans — drawn as a segment of a track that parts at the labels, a zoom under the
  pointer — while the plot stays one picture (`role="img"`), with nothing drawn where
  the pointer is. Where no round time falls between the ends, the axis names the two
  ends.
- **Drawn by column.** A window with more readings than the plot's `COLUMNS` (336, two
  units each) is drawn by `_by_column` (ADR-0098 decision 5): each column's first,
  last, lowest and highest reading, so the line is the one every reading would draw and
  no spike is lost. A hole breaks the line where it is at least a column wide, and so
  does a column none of whose readings has a value; a column holding a reading that
  failed carries one mark; its strip under the pointer names the range, the count and
  the times. The summary — newest, lowest, highest, failed, holes — is counted over
  every reading, at any width. Fewer readings are drawn one by one (`_by_reading`).
- **Runs are marks.** A series' **runs** are its records with an identity
  (`curves.runs_of`), and `curves.draw_runs(measure, runs, span=…, times=…)` draws each
  at its own instant on the axis a curve has (`_time_axis`), as a
  `Stem(x, y, at, verdict, head)`, with no line between two and no hole
  ([ADR-0106](adr/0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 5,
  [ADR-0111](adr/0111-a-runs-mark-says-how-the-run-stood.md)). Under a measure a stem
  runs from the baseline to the run's value, on the scale a curve of those values would
  have. Without one — `measure=None` — the plot is titled `RUNS_LABEL`, has no value
  axis and is `TICKS_HEIGHT` tall, and a stem is a tick whose height says how the run
  stood. `verdict_of` reads that from the code the reading kept (§4.10): `passed`,
  `warned`, `failed`, or `unjudged` where it kept none, or one that makes no claim. A
  run that warned or failed has a head, one without a verdict has none, and a passing
  run has one under a measure alone — which `_with_room` leaves out where another head's
  middle is nearer than `HEAD`, the newest run keeping its own. No run is merged with
  another, at any width (ADR-0111 decision 4). The lane, which a plot with a value axis
  has, carries one `Mark` for each column that holds a run that failed, by its code or
  by its record's `error`. `_runs_hover` cuts the strips between the columns that hold a
  run, and a strip says a run alone — its time, its value, how it stood — or a column's
  range, count and times and how many of its runs failed or warned. `readings`,
  `failed`, `warned` and `unjudged` count the runs handed in, and the newest, lowest and
  highest value are taken over every one of them that has a value, a run that failed
  among them (decision 6). `runs_drawable(measure, runs)` says whether runs have a plot:
  under a measure where a run gives it a number, and without one wherever there is a
  run. A record with a state is no run and has no mark (decision 5).
- **Which series are near a node.** `Engine.series_near(path)` answers every
  configured check that keeps a series mounted at the node, beneath it or above it,
  with each subject's placed readings (`SubjectSeries(check, readings, subject)`) —
  found through the checks and `MemoryStore.subjects`, not the tree, so a mount two
  checks share shows both although its node withholds the one subject a last writer
  would claim ([ADR-0044](adr/0044-run-facts-on-the-node.md)). `curves_may_stand(path)`
  answers from the configuration alone whether a curve can stand at or beneath a node —
  a check keeps a series there or beneath it, or above it with a measure naming a node
  there, a `*` naming any — so a view's tab does not come and go with the readings.
  `app._series_tab` asks the tree besides: the tab also stands where a series is shown
  at or beneath the node on a subject's own node, or a curve of that series stands
  there ([ADR-0106](adr/0106-a-subject-with-a-history-has-a-node-of-its-own.md)
  decision 4).
- **Where it is shown.** A series is shown on one node, which `app._stood_on(kept)`
  answers: the node at or beneath its check's mount whose lines name its subject and no
  other — `_subject_nodes`, the first in the tree's order where two do — and the
  check's own node where none does, and always for the object the check declares
  (ADR-0106 decisions 2 and 4); `app._shown(kept)` answers that beside the series a
  node stands for — a subject's on its own node, and the object a check declares on
  the check's. `app._standing(kept, where=…)` expands each measure over its series'
  readings and names the node each would stand on, from the node the series is shown
  on, at or beneath `where` — or, `on=True`, on that node itself.
  `curves.drawable(measure, readings)` says whether a
  measure has a curve by `draw`'s own two rules — a reading that did not fail gives it
  a finite number — without drawing it, and stops at the first reading that does.
  `app._plots(kept, where=…, on=…)` names everything that is drawn there, none of it
  drawn yet: a curve for each measure a reading gives a number, and for a series of
  runs its marks — stems under each measure a run gives a number and, where none of
  its measures draws, ticks under no measure on the node that stands for its subject.
  A series of runs no node stands for draws no ticks; its readings are on its check's
  History page (ADR-0109 decision 6, ADR-0111 decision 5).
  `app._drawn(kept, where=…, on=…, span=…)` draws what `_plots` names, keyed by
  the node each stands on; `app._drawable(kept, where=…)` answers the same without
  drawing — each curve's label and series, in `_drawn`'s order — for a page that only
  lists curves or asks which series have one, since a curve costs a formatted time and
  a hover strip for every reading it is drawn over. No page draws a curve it does not
  show. A node's **Status** page, leaf or branch, carries the curves
  that stand on that node (`_node_curves`), as the *Series* card of `_node_facts.html`,
  naming the node their series is shown on — the check's own, or the one that stands
  for the subject — and linking that node's Series view, at this node's group, and
  its History page, with no readings. The **Series view**,
  `/series/<path>` (`_series_view`, `series.html`), carries every curve at or beneath
  the node, grouped by the node each stands on in the tree's order, each group headed
  by that node's status and sentence and opening its Status page, all on one time axis
  spanning the series the curves are drawn from — which `_drawable` finds, so a check
  above that draws nothing there does not stretch it — or the window its URL names
  (ADR-0098). `_window(request.args)` reads `from` and `to`: `now`, `now-` and a
  duration in the family's units, or an ISO 8601 instant, one without an offset read in
  the configured zone; `to` is now where only `from` is given, and neither is
  everything kept. What it cannot read, or a `from` not before its `to`, is a `400`
  naming the parameter. It reads the clock once, through `_now()`, and the page's
  controls measure against that reading. The window's open ends are filled from what is
  kept, the axis is the window as written, and every curve is drawn over the readings
  inside it (`within`), while which curves stand is still decided by everything
  kept — one with no reading inside keeps its place and says so, and one whose
  readings there carry no value says that. `_window_bar` is the bar above the curves,
  sticky beneath the page's own from the md breakpoint up: it names the window —
  *Last 6 hours* for one written back from now, *Everything kept* without one — and
  its ends to the minute in the configured zone, with the zone's name (`_window_ends`);
  the presets up to the first that reaches back past the oldest reading kept, and *all
  kept*, the one of a live window's length marked; and *earlier*, *zoom out*, *later*
  and *now*, always in their places, each disabled where it does not apply (ADR-0098
  decision 3). The bar is drawn by `_window_bar.html`, and `_window_bar` takes the
  writer of the page's own URL, so the Events page draws it too, over its log, each
  link keeping that page's filters (ADR-0101). A move that leaves the window ending
  now or after writes it back from now (`_ago`: `now-` and the length to the minute,
  in the largest family unit); every other window, a stretch chosen on the time axis
  included, is two instants in UTC with a `Z`. A stretch's link carries its group's
  anchor, so the view opens at the curve it was chosen on; the first curve's time
  axis is the keyboard's, and every other one is
  `aria-hidden` with its links out of the tab order. Over the links runs the view's
  one script, `static/js/series.js` (ADR-0098 decision 6), which reads what the page
  hands it — the grid's `data-start`, `data-end` and `data-zone`, each plot's
  `data-left` to `data-right` and `data-top` to `data-bottom` — and nothing else: a
  mouse or pen drag across a plot or its axis marks the stretch on every plot, writes
  its ends beneath the curve dragged, and opens the view over it, rounded to the minute
  over a window of an hour or more and to the second under one, at the curve's group;
  the pointer at rest draws one line across every plot and puts each strip's title in
  its curve's summary (`.is-enhanced` takes the pointer from the strips, whose tooltips
  would say it twice); and a preset or a move from the bar carries the anchor of the
  group scrolled to. Touch is left to the page's scroll and its links. The drawings
  are `user-select: none`, and a stretch's link `-webkit-user-drag: none`, so a drag
  selects and carries off nothing without the script either. The Series crumbs carry
  the window as written (`window_args`); the tabs, the index and a node's page take
  none.
  Beneath the curves come the newest `reading_cap` readings — inside the window, where
  one is named — of each of those series, folded, each through `record_fields` (§4.5)
  so a time reads in the configured zone and everything else as stored; and a line for
  each node at or beneath it that series are shown on while none of them draws
  anything, naming what it keeps and its History page.
  Without a usable time axis, the introduction says “No curves to display.” rather
  than printing an empty range; retained-reading counts and History links remain.
  `/series` (`_series_index`, `series_index.html`) is the index: every node a series
  is shown on — a check's own, and each that stands for one of its subjects — grouped
  under its root node, with its status, the checks keeping it, a
  count of the curves its own series draw — their labels, from `_drawable`, folded
  behind it — the readings it holds and the newest one's time
  ([ADR-0103](adr/0103-the-series-index-says-where-each-link-leads.md)). A node's name
  opens its Status page, and its row ends with *curves*, its Series view, where a curve
  stands at or beneath it, and *readings*, its History page. A root appears once: its
  heading is its own row, its cells empty where it keeps nothing itself, and the nodes
  beneath it follow, indented. `/history/<path>` renders
  every kept reading of each series shown on the node (`every=True`) and no curve: the
  series of the subject the node stands for, and on a check's own node what the check
  keeps of its own object and of every subject no node stands for.
  Neither view is polled.

---

## 5. Web layer — `app.py`

### 5.1 Routes

| Route | Methods | Behavior |
|-------|---------|-----------|
| `/` | GET | Redirect to `/status`. |
| `/login`, `/logout` | GET, POST / GET | The **default door's** login step — the built-in login list on an install that registered it (`local_login.use_local()`), which stores `username`, name and an `admin` flag — or, under `identity.choose_at_login()`, a page offering every **enterable** door as a link to its own route, which takes no credential itself (§5.2) / runs the session's door `end_session` step, if it has one, and clears the session ([ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)). |
| `/login/<door>`, `/auth/callback/<door>` | GET, POST / GET | **One named door's** own login step and the return leg of its redirect flow (§5.2, [ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)). Both dispatch on the name in the path to the provider registered under it — a provider never registers a route, so this costs no general route seam — and both answer `404` for a name nothing claims and for a hook the provider does not implement, since either is a way in this deployment does not have and a redirect there risks a loop. A door's own route matters mechanically rather than stylistically: under a provider that redirects, `/login` never renders a local form. |
| `/status`, `/status/<path:branch>` | GET | Renders the dashboard from a live snapshot (whole tree or a branch; the `path:` converter passes the slash-separated node path, ADR-0016). A **leaf** check renders its **detail** page. `?reason=<slug>` names one line of the node, a leaf's or a branch's, which the page marks, or says is no longer reported where only its pin is left (ADR-0036 decision 12). `hide_ok` / `hide_idle` filter the view, and `tag` draws only what carries one tag, each topmost part that does a card of its own ([ADR-0139](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 5, never a cookie); `depth=N` closes every node N levels below the page's node for that load, the wall's cards being level 1, and `depth=0` closes the page's node itself to one card (clamped to `MAX_DEPTH`, never a cookie — [ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision 7); `fragment=1` returns just the grid (for the page's live polling). With `Accept: application/json` and a valid bearer token, the same routes return the subtree as JSON instead (ADR-0080). No Status page carries a document, or the buttons that copy one: a node's hand-off is its Copy view, `/copy/<branch>`, which the **Copy** tab of every node's views leads to ([ADR-0115](adr/0115-a-copy-document-says-where-it-is-from-and-since-when.md) decision 7). A path **no node stands at** is `404` with one page, the same at each of a node's addresses — Status, Series, History, Handbook and Copy ([ADR-0116](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)): its removal with when and why, where the event log holds it, and a link to its rows on Events; every pin held against the path or beneath it, edited there by an admin; and the nearest node above that stands, on whose History the readings kept of a removed subject are listed. `fragment=1` at such a path is still `200` and says the same, so a node that leaves under an open page is not a failed refresh. |
| `/series`, `/series/<path>` | GET | A node's **Series view**: every curve that stands at or beneath the node, grouped by the node each stands on, on one time axis, with the newest `reading_cap` readings of each series they were drawn from beneath them, folded — and the index at the root, every node a series is kept on, a name opening the node's Status page, *curves* and *readings* beside it its Series view and its History, and the count of its curves unfolding to each one's label, sparkline and newest, lowest and highest value, each on a line of its own, so a fold is no wider than a strip; on a phone each row is laid out as a block of its own and nothing is scrolled sideways — the curve's own plot on its own scale, from zero, drawn over sixty columns with no instant written ([ADR-0114](adr/0114-a-curve-seen-small-and-the-series-tabs-count.md)), which is also where a node's Series tab gets the number of curves its view draws (§4.11, [ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md), [ADR-0103](adr/0103-the-series-index-says-where-each-link-leads.md)). `?from=…&to=…` draws the view over a window, Grafana-style — `now`, `now-6h` or an instant — named in a bar above the curves that holds the presets and the moves, with the time axis's stretches as links ([ADR-0098](adr/0098-a-series-view-is-drawn-over-a-window.md)); a window the server cannot read is `400`, naming the parameter. A node where no curve can stand is `404`, and a path no node stands at is `404` with the page that says what is known of it ([ADR-0116](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)). Not polled. With `Accept: application/json` and a valid bearer token both routes answer the **series read** instead ([ADR-0106](adr/0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 6, [ADR-0122](adr/0122-a-series-is-read-over-the-api-as-it-stands.md); `_series_json`): every series that stands at or beneath the node — at the root, every series the instance keeps — over the same `from` and `to`, each with the node it is shown on, the key it is kept under, the measures that stand at or beneath the node asked — one for every key the kept readings hold, each with the path of the node its curve stands on — and its readings in the window whole, oldest first (`_series_standing`, which asks the helpers the view asks; `api.series_envelope` spells it). A series shown above the node asked is in the answer where one of its measures names a node at or beneath it. The answer says the node asked and the two instants the window was read as, and orders its series by the node each stands on: one above the node asked first, then the tree's own order, then the key. There a node that stands answers `200` and a list, empty where no series stands at or beneath it — a node no check keeps a series of, and every node of an instance that runs no engine — `404` is a path no node stands at and nothing else, and a window the server cannot read is `400`, as Problem JSON with the page's sentence. |
| `/history/<path>` | GET | A node's status history: on a node above others first the periods of what it shows (Status / Since / Until / From / What), newest first, the newest fifty open and the rest in one fold ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md) decision 6); then the periods of its **own** status (Status / Since / Until / Reason), which the page says of a node above others ([ADR-0123](adr/0123-a-node-says-one-status-wherever-it-is-read.md) decision 3) — and, beneath them, **every reading** each check mounted on the node kept, newest first (§4.11), in a box as wide as the page that holds its heading row and its Time column while it scrolls ([ADR-0102](adr/0102-a-readings-table-keeps-time-and-names-in-view.md)). Where the log holds no change of the node, a node that declares nothing of its own says so, and one a check has written shows the period that holds, begun when the kept table says or *before* its bound. A path the tree holds no node at — one its check no longer reports among them — is answered `404` with the page that says what is known of the path, as its Status address is ([ADR-0116](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)). Not polled. A node's views — Status, Series where a curve can stand, History on every node but the root, Handbook on a node that has one, Copy on every node — are tabs beneath its title, and the breadcrumb, `nodes` and a crumb per segment, opens the same view of each ancestor. |
| `/handbook`, `/handbook/<path>` | GET | A node's **Handbook view** ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) decision 3): what its team writes at length about it, rendered as every text is — its tables drawn, a status it names drawn as its sign — at the Copy page's measure, its headings anchored as GitHub anchors them, so `#sign-in` opens at `## Sign in` (§4.5, §4.7). It stands in the node's band, its crumbs opening each ancestor's handbook where it has one and its Status view where it has none; `/handbook` is the root's. A node that has none is `404` with a line that says where one is written, and a path no node stands at is `404` with the page that says what is known of it ([ADR-0116](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)). Not polled: a handbook is read with the configuration, at a restart. |
| `/notes/<path>` | GET, POST | A node's **Notes view** ([ADR-0140](adr/0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) decisions 2 and 3): the notes on the node and on its lines, newest first — what each is on, a line marked where the run does not report it, who wrote it and when, whether it is a pin's and its pin still stands, its words, and folded what the node showed then. **POST** — **admin only**: adds a note (`action=add`, `slug` naming a line, `text`), with what the node shows now, or changes the newest note of its own (`action=edit`, `key`, `set_at`, the compare-and-set token, `text`); a write that is refused saves nothing and comes back `200` with the admin's words in the form. `?reason=<slug>` chooses the line a note is added on, as a line's editor links here. A path no node stands at is answered as its other addresses are ([ADR-0116](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)), with the notes written for it and beneath it. |
| `/little-sister/<contributor>/act/<slug>` | POST | **Admin only.** Runs an action a package offered on its self-report child ([ADR-0076](adr/0076-the-instance-node-is-a-branch.md)) — `self_report.register_action(contributor, slug, label, handler)` — logs who ran what, flushes the state layer (what the action changed reaches the store now), and redirects to `/status/little-sister/<contributor>` with the sentence the handler returned shown once (a flashed message, rendered by `_said.html` on the status and leaf pages); a handler that raises is caught and its label and error are the sentence. Unknown action: 404. The buttons are the library's built-in filler on `node.actions` (`_self_report_actions.html`), rendered only on a child of `/little-sister` and only for an admin, as POST forms. |
| `/handled` | GET | ***Handled***, the full, uncapped index of every rule that stands, as its own page ([ADR-0135](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md) decision 8; the leaf-detail pattern), reached from the navigation, the strip's pill and its popover's "+N more": its sections the jobs, today *In maintenance* alone, and in it **every pin as the block a node's own page states it with** ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md)), grouped under its node's path, the node whose pins have stood longest first — the node's own pin first, then its reasons' ([ADR-0036](adr/0036-addressable-reasons.md)) in the check's order. A block opens with what the pin holds — *The whole node*, or the reason line itself — and says who put it in maintenance, until when and what is left, then the note that explains *why*, rendered Markdown in full, and authorship for everyone (*pinned by … , last changed by …*). What is held and why are two texts in two places on purpose: both are called "reason" in the model and are not the same thing. A line's block links to its line as `/status/<branch>?reason=<slug>#pinned-reason`; the slug is never rendered as text. An **admin's** block carries *Edit* and *Clear*, and a write made here comes back here with its node named — `?node=<path>#pinned-node`, which marks that node's section and no other; a viewer reads the same page without them. **A pin whose node is not reported** — its check no longer returns the node, or has not written it yet since the start — stands under its path as well ([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md) decision 4), read against the snapshot the page lists the others from (`_suspended_pins`, over `StatusTree.pins()`): the path is no link, a sentence says that the node is not reported at present and that its pins hold nothing until it returns, and each block says what it holds *when it is reported* — the whole node, or one of its lines, whose text went with the node. It is edited and cleared there like any other, and neither makes a node; the wall's pill counts what is in maintenance now, so not this. |
| `/maintenance` | GET | Answers with `/handled` and its query (ADR-0135 decision 8), so that a bookmark and a way back drawn before hold. |
| `/pins/maintenance` | POST | **Admin only**, asked as the act's own permission, `maintenance` ([ADR-0141](adr/0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md) decision 4), each act on a pin having a route of its own: set/edit/clear a node's maintenance with a raw-Markdown note (`note`) and optional duration-or-expiry (blank uses the duration from `settings.yaml`), recording who set it. Unit-suffixed durations and full ISO date/times are accepted alongside `MM-DD`, a day-of-month, `HH:MM`, and weekday/time shortcuts; a bare weekday uses 12:00, and unzoned values use the configured timezone. The resolved expiry must be **at least one second and at most 365 days away**; invalid, past, ambiguous-DST or out-of-range input is refused with the admin's words returned, and a blank note on an *edit* keeps the stored one ([ADR-0014](adr/0014-maintenance-persistence.md)); a set's words enter the node's notes, and follow its edits while the pin stands ([ADR-0140](adr/0140-a-nodes-notes-stand-on-a-tab-of-their-own.md) decision 1). An edit's form also carries what its expiry field was filled with (`expiry_was`, the stored expiry as the field reads one): a field that still reads that **keeps the stored instant exactly** and is not read again, and anything else — a blank included — is read as above ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md)). A `slug` field addresses **one reason** of the node instead of the node ([ADR-0036](adr/0036-addressable-reasons.md)) — never a path segment, since the natural slug for a discovered entry contains a `/`; redirects to the node — for one of its reasons to that line, `?reason=<slug>#pinned-reason`, where the node's page marks it — or back to the page the form was opened on, via a validated `next` (a card's and a branch's head's way home, and *Handled*'s). A set that says what the stored pin says writes nothing and is answered as a save is. Every form carries the entry's `set_at` as a hidden **compare-and-set token**, so a write against a pin someone else has since changed is **refused whole** and answered with the conflict page — both rendered stored text and the admin's raw source, who set the stored one and when, the admin's own words preserved and one click to take the stored ones instead ([ADR-0014](adr/0014-maintenance-persistence.md)); the page is headed by the node's path as every page writes one, however the form spelled it, and each way off it leads where the write would have. |
| `/pins/seen` | POST | **Admin only**, asked as the act's own permission, `seen` ([ADR-0142](adr/0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) decisions 1 and 5): marks a failure seen, edits a seen or ends one by hand. One part — a node's own failure, or one of its lines by `slug` — is the guarded write `/pins/maintenance` makes, its note entering the node's notes; a new one only where its part fails now, refused with why where it does not. Its *Until* is optional — blank for none, the seen ending as what it accepted changes — and otherwise read as a pin's expiry is, within the same bounds, an edit's unchanged field keeping its end. A head's form names its node and carries `parts`, the digest of the failing parts at and beneath it that its editor listed: each is marked seen, its own seen sharing the note; where the parts failing there now are others, nothing is written and the refusal lists them as they stand, with a form that marks those. Comes back where its block stands, as a pin's write does. |
| `/events` | GET | The transition log, newest first (When / Status / Service / Reason) — every row its node showed and every one a rule held back, not a reading a floor on its node's lines raised ([ADR-0137](adr/0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) decision 11) — narrowed by what its URL names ([ADR-0101](adr/0101-the-events-page-is-filtered-by-its-url.md), `event_filter.py`, `_events_view`): `under`, a node and everything beneath it, compared segment by segment; `tag`, a tag its node carries ([ADR-0139](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 7) — one gone, by what is written for its path and above it; `words`, each found in the reason, in any order and ignoring case; `status`, the switches that are on of *error*, *warn*, *ok*, *maintenance* and *undefined*, by the status an event moved to; `held`, `no` for what reached anybody and `yes` for what a rule held back; `cause`, the switches that are on of `reading`, `pin` and `removed`, by what wrote the row — a row that says no cause being a reading's ([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md) decision 5); and `from` and `to`, read as the Series view reads them (`_window`), an event inside when its time is, ends included. A group with every switch on, or none, filters nothing and no link writes it; a switch the page does not offer, like a window it cannot read, is a `400` naming the parameter. The filter row, the Series view's bar (`_window_bar`, `_window_bar.html`) over the log's own oldest and newest event, and a line counting the window and what matches in it stay in view while the table scrolls; the line adds how far back the log reaches where the window starts before it, *reset* leads to `/events`, the form carries the window and every link the bar draws the filters, and nothing remembers a filter. An empty table says which empty it is. A Service path opens the node's current Status page when the node still exists; a removed node's path remains plain text. A node its check no longer reports writes a row for itself and for each node beneath it, to *undefined*, with the chip *removed*, and the *removals* switch hides them. A transition that reached nobody is **shown and marked** with the contribution rule that held it back ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 5, [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)) — it keeps the status color it would have alarmed in, and the chip beside the code is what says it did not. A status that a wait held back and that then reached has a second row, at the reading that completed the count, with the chip *reached* ([ADR-0119](adr/0119-a-wait-that-ends-by-its-count-writes-a-row.md)): a reading's row and unmarked, so with *held back* off the page lists what alarmed, and when. Marked events are what makes *did it break during the window?* answerable. One that maintenance held back is left out of `/history`, which answers the other question; one that damping or a dependency shield held back stays there, since the node showed it ([ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md), `HIDES_THE_READING`). |
| `/system` | GET | **Admin only** — the System page's *Running* view ([ADR-0100](adr/0100-system-is-two-views.md)): which instance this is, and engine uptime, pool size, check counts; the declared load, the entries held and the series held beside what each is measured against (the series with the projection, §4.10), and the process's resident size and peak against the memory limit and what the machine gives it, and what the machine has left beside it ([ADR-0095](adr/0095-the-instance-states-its-memory.md)); per check its type and the in-flight / armed-next / last run, each a time of day plus interval. Carries the dashboard's freshness stamp and ~10s poll (`fragment=1` returns just the info block). |
| `/system/installed` | GET | **Admin only** — the System page's *Installed* view ([ADR-0100](adr/0100-system-is-two-views.md)), settled at startup and not polled, every section open under an index: the **check-type roster** (§11) — the types this configuration runs first, each with the number of checks behind it, a count that opens into the node path of every one of them so it can be believed without reading a config file, the rest folded into a disclosure so a registered-but-unused type stays readable without filling the card — **what their lines say** (§4.5, [ADR-0126](adr/0126-a-line-is-a-template-over-its-record.md)), for every type the configuration runs whose lines are forms: each form with the sentence that says when its grading says it and its default text, and each word and field a template may name with its sentence and an example, folded per type, the page a deployment writes a `display:` block against — the **package inventory** (§11), one row per installation outside the library with its distribution, version, loaded path and everything it registered, because a version belongs to the *installation* and a package that registers no check type would otherwise have one nowhere on the page — both tables print that loaded path **against a root the reader has** (`paths.py`): `site-packages/…` or `./…` under the working directory, whichever root is the nearer, because the diagnostic it carries is *which root the module came from* rather than the absolute string, nine tenths of which is the same prefix on every row and starts with somebody's home directory (the origins and the hover `title` keep it whole; a path under neither root stays long, which is the signal) — the **extension seams** (which package fills which slot, which configuration aspects were registered, and who registered each one), the **identity card** — one row per registered door with its route, its provider, the package that registered it and which one is the default, and beneath it whether a system-admin account is configured, whether its credential resolved and which keyword configured it, because a way into an application must not be knowable only by reading the source (§5.2, [ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)) — and the **effective Content-Security-Policy**, directive by directive, with the contributor of every source — a request blocked inside somebody else's package is otherwise undebuggable from the running instance (§5.4, [ADR-0048](adr/0048-an-assembled-content-security-policy.md)). Last, **what the log leaves out** (§11, [ADR-0121](adr/0121-a-noise-cap-is-declared-and-log-level-has-the-last-word.md)): whether the library's logging default is in charge, the root's level, every logger that carries a level of its own with where the level comes from — a noise cap a package declared, an entry of `LOG_LEVEL`, or neither — and every declared cap that was not set, with the reason; read off the loggers at the request rather than kept from startup, since what code sets after the import, it sets. |
| `/help` | GET | **How the wall is used** ([ADR-0136](adr/0136-how-the-wall-is-used-is-one-file-the-package-ships.md)): the account the package ships, `help/using-the-wall.md`, read once from the package (`importlib.resources`, `help_account()`) and drawn as a handbook is — its tables drawn, its headings anchored as GitHub anchors them, so `/help#the-band` opens at the band beneath the sticky bar — at the handbook's measure, in no node's band (`help.html`). The settings menu's foot links it. Auth-gated like every page; not polled. `tests/test_help.py` holds the account to the menu it describes: every look and its values, the band's and a head's buttons, a node's tabs and the navigation's pages. |
| `/about` | GET | The identity page — the gaze, the name and the reasoning behind it, the running instance's `__version__`, the repository link. Auth-gated like every other surface: it names the version of a live instance. |
| `/preferences` | POST | Records this browser's **theme** and **layout** (§5.3, [ADR-0029](adr/0029-per-user-presentation-preferences.md)) and redirects back to the posting page. A value outside the roster is dropped in favor of what the browser already had; the return path is validated by `_safe_next` (a single leading `/`, and none of the characters a browser rewrites into a second one), so the hidden field cannot become an open redirect. |
| `/copy`, `/copy/<path:branch>` | GET | Auth-gated incident hand-off, four documents from one route and one formatter ([ADR-0115](adr/0115-a-copy-document-says-where-it-is-from-and-since-when.md)): the **tree** (`/copy`), a **branch** or a **leaf** (`/copy/<branch>`) and one **reason line** (`/copy/<branch>?reason=<slug>` — the node a path, the entry a query value, [ADR-0036](adr/0036-addressable-reasons.md) decision 12, because a discovered entry's slug contains a `/`). **Copy is a view of its node** ([ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md) decision 3): the page stands in the node's band, under the tabs the node's other views carry with *Copy* the current one, its crumbs opening the Copy page of each ancestor — the tree's page in the root's band, a line's in its node's — and beneath the band it says which of the four it holds. **Every document says where it is from and when it was made**: *Dashboard*, the address of the page it describes as the request reached it — the wall, the node's page, that page with the line marked — and *As of*, the instant the document was made, which is when its page was opened and not when a button was pressed. Where its node has a handbook, *Handbook* stands between them, the handbook's address from the same base, and a link any text of the document writes in the short form, `handbook#<section>`, is written out to the handbook of the node the text belongs to ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) decisions 3 and 4; `Origin.handbooks`, `copy_status.written_out`). A node's document carries its **details** after its facts, as a block, *Details*: its *About* card's table as key and value, in the card's order, those given down to it among them, each value written out as every text is, a link in the short form to the handbook of the node it is given on (ADR-0133 decision 6; `StatusTree.details`, `copy_status._details_block`). A line's document is the line and just enough to locate it — the node's title, path and observation — and deliberately not the node's run facts, report or configuration, which the node's own document carries and which is where a secret reference would appear. A slug this run does not report is `404` with a page that says so: a suspended pin is not deleted, but a document made from its stored text would hand over a finding the check is no longer making. A path no node stands at is `404` with the page that says what is known of the path, as its other addresses are, and so is a line asked of it ([ADR-0116](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)). **The tree's document**: one immutable root snapshot becomes one canonical Markdown document — a head (*little-sister status* with the cue of what the tree shows, the two lines, and a count, *Needs attention — 6 of 12 nodes: 2 error ⛔, …*) over an outline: every non-OK leaf (`WARN`, `ERROR`, `MAINTENANCE`, `UNDEFINED`) plus only the ancestors needed to locate it, in snapshot order; the synthetic root and wholly healthy branches are omitted. A node is counted where it shows a status of its own — a node with nothing beneath it, and a branch that declares a status or is pinned — and the count is the number of findings the outline lists. **A listed node says since when** it has shown its status, from the period its own page states (`_period_of`, which is the Time card's `_since_of`): *since before* where that is a bound, and with what began it where a pin did. **A branch's line says what the branch itself holds**, above what is beneath it: a pin on it, and a status of its own that is not ok with its own lines — a reading of its own gone stale among them, which the tree counts degraded and the snapshot names (`own_stale`, §4.4). A tree with nothing to list is a document too — *Nothing needs attention — all 12 nodes are ok.* — and a pin that stands on the tree itself is stated in the head. **A branch's document** hands over what is beneath it: *Reported* where the node declares a status, *Shown as* where it shows something else and where that comes from (the nodes beneath it alone where every line of its own is in maintenance, [ADR-0124](adr/0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)), the period of what it shows where that is of what it shows — *Status error since …, begun by a reading of load-fixtures beneath it*, what began it in one clause after the instant in History's words, a dependency outside the branch by its full path and *which a node beneath it is reached through*, and nothing after the instant of a bound or of a difference no change explains (`_shown_period`, `_begun_by`; [ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md) decision 6) — the period of its own status, named so ([ADR-0123](adr/0123-a-node-says-one-status-wherever-it-is-read.md) decision 3), and its observation — *Not yet observed* only where it has neither an observation nor a period — its own lines, then *Beneath it* — how many of the nodes beneath it need attention, and the outline of those — then *Handled beneath it* where its page's *why* card stands: every rule beneath it under its job, as the card lists them (`_handled_block`, [ADR-0135](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md) decision 7) — and what its own run found and ran with. **A leaf's document** carries what only its page knows and the tree's has no room for — the path, the observation and the period it bounds, the next update, the run's wall time, the frequency, the report, the configuration and every reason line uncapped. A pin does not change it: the document keeps the **measurement** and says a pin is in force, rather than presenting the pinned code as the reading. Leaves carry a non-color emoji cue, and so does a **reason line that declared a code of its own** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) — a healthy workflow under a failing node has to read as healthy in a pasted document too, and a line that declared none takes no cue because it carries its node's. A line whose subject is **running** says so in words: the page's italic is the glance, and a document has none. Authored check and maintenance explanations keep their Markdown, while node/per-reason maintenance also names who set it and its expiry. Every instant a document writes names its **UTC offset**: the pages render local time and stay silent about the zone, which is right for a screen somebody is standing in front of, and wrong for a document read in another office. The page renders the rich preview through the same hardened Markdown renderer as every other surface. **Copy Markdown** writes `text/plain`; **Copy Rich HTML** writes both `text/html` and the Markdown as `text/plain` — through the clipboard interface where the page has one, and through the browser's copy event where it has none or is refused, which is every instance reached over plain `http` by a host's name: the interface exists in a secure context only. Where neither carries the rendered document it falls back honestly to plain/manual selection. The two buttons stand on this page alone (`_copy_controls.html`), and the label names the clipboard member rather than claiming RTF. |
| `/links` | GET | The **shared toolbox**: this deployment's curated links (§7, [ADR-0030](adr/0030-curated-links.md)), one flat level of groups flowed into columns, each entry a mark and a title in the configured order. Icons resolve through the search path; a name nothing defines falls through to the entry's own origin favicon and then to a neutral glyph. Structural problems in the file are shown on the page — the person who maintains it is the one looking. A **client-side filter** sits above the columns and narrows by entry and group title. The configuration is re-read only when it changed, so an edit needs no restart. A page with **no links** says so in one sentence and holds its setup guide in two folds, the browser's own disclosures and closed: *Add links* — the file's shape and where it goes — and *Icon names*, the registry's roster with both drawings of each mark and how a deployment adds one of its own. A page that has links keeps *Icon names* at its foot, outside what the filter narrows. Every reader gets the same page. |
| `/links/icon/<variant>/<name>` | GET | One resolved icon, for the background `variant` names (`on-light` / `on-dark`). Serves every rung of the search path that holds bytes — the deployment's own file, a registered pack's package data, the built-in pack — so the page has one URL shape for all of them; a **remote** icon is 404 here and is emitted as its own URL rather than proxied. The name is a registry key and never builds a path. Auth-gated, `private` cache with an ETag (§7, [ADR-0030](adr/0030-curated-links.md)). |
| `/user/avatar` | GET | The signed-in user's configured avatar, if any. Takes no username or path: the session selects a startup-resolved bare name inside the winning users aspect's `avatars/` sandbox, so the route cannot enumerate accounts or construct a filesystem path. Auth-gated, private five-minute cache with an ETag; a removed file falls back to the packaged neutral avatar ([ADR-0045](adr/0045-user-avatars.md)). |
| `/ext/<package>/<member>` | GET | One registered **extension asset** — a `.css` or `.js` file a dependent package ships for the slot it fills (§6.1, [ADR-0037](adr/0037-extension-static-assets.md)). Read through `importlib.resources` and looked up in the registry, so neither argument ever builds a path; the URL carries a content hash and the response is immutable. Login-gated like every other surface, and the kiosk layout loads none of it. |
| `/csp-report` | POST | Where a browser posts a **Content-Security-Policy violation**. Each report is one `WARNING` log line — the violated directive, the document, the blocked URI, the source and line — and nothing is stored, which is what keeps the policy clear of the persistence decision. **No login gate**, necessarily: a violation on the login page has no session, and a report the browser cannot deliver measures nothing. One of three such routes, with `/health` and `/ready` below. It is bounded instead — an oversized body is refused unread and each reported field is truncated before it reaches the log, because a blocked URI is whatever the page tried to load (§5.4, [ADR-0048](adr/0048-an-assembled-content-security-policy.md)). |
| `/health` | GET | **Liveness for a machine**, and the second route with no login gate ([ADR-0066](adr/0066-health-answers-liveness-and-says-almost-nothing.md)). `200` while this process serves, *whatever the engine is doing* — a load balancer that pulled the instance out of service over a failed check config would remove the very page whose banner explains it. The engine is reported instead: `{"status": "ok", "engine": "running" | "disabled" | "failed"}`, a closed vocabulary in which a deliberate `LITTLE_SISTER_ENGINE=0` (`disabled`) is not the same word as a configuration this instance could not load (`failed`). It says nothing else, and that is the bound an ungated route pays for: not the failure reason (a `CheckError` names config files; the banner carries it behind the login), not the version (`/about` is auth-gated for that reason), not the configuration. Not part of the JSON API and not in `api/openapi.yaml`. `no-store`. |
| `/ready` | GET | **Readiness for a machine**, and the third route with no login gate ([ADR-0073](adr/0073-a-readiness-answer-beside-health.md)). `200 {"status": "ready"}` once an identity door is registered, the machine's trust store holds CA certificates and the engine has run every configured check once; `503 {"status": "not ready", "waiting_for": [...]}` until then, from the closed vocabulary `doors` / `trust` / `first-pass` and nothing else — three words that name no path, count, version or configuration and answer the one question the caller of an unready instance cannot answer itself, *wait or roll back*. It **latches**: the three are startup facts, so this route goes `503` to `200` once and never back, which is what keeps it from withdrawing a serving instance and removing the page whose banner explains the failure. An engine switched off with `LITTLE_SISTER_ENGINE=0` has no pass to wait for and is ready; one that could not load its configuration never is. Which of the two routes a load balancer aims at is the deployment's choice — `/ready` behind several instances, `/health` behind one. Not part of the JSON API and not in `api/openapi.yaml`. `no-store`. |
| `/favicon.ico` | GET | Redirect to the static favicon. |

Jinja filters back the views: `status_slug` (a CSS class suffix per code),
`shorten`, `duration` (a *configured*
interval in the units the config wrote it in: `15m`, `1h` — a name for
`little_sister.spans.format_duration`, which the copy document calls too),
`elapsed`
(a *measured* span — a run's wall time, a countdown, an uptime — as
`little_sister.spans.format_span` writes it: `412 ms` / `3.1 s` / `43 s` /
`1m 55s` / `2h 7m` / `1d 3h`; `—` for none), `localtime`
(renders an instant in the configured timezone, §7 — an optional argument
overrides the format, never the timezone), `record_fields` (a record as the rows of
its list, each with its kind, §4.5), `url_branch`,
`markdown` / `markdown_inline` (server-side Markdown → safe HTML, §4.7), and
`breadcrumbs` (a path → cumulative `(name, path)` crumbs for the clickable header
trail, rendered by `_breadcrumb.html` after a first crumb, `nodes`, each opening the
view the page is in; the current node stays plain). The dashboard
filter logic is `_filter_snapshot` (drops nodes whose effective code is hidden).

### 5.2 Authentication
- Session-based, and **one gate**: a `before_request` hook refuses any request with no
  identity, unless its endpoint is named in `identity.py`
  ([ADR-0068](adr/0068-the-login-gate-refuses-by-default.md)). Two lists say which —
  `OPEN_ENDPOINTS`, which answer without an identity at all (`/login`,
  `/login/<door>`, `/auth/callback/<door>`, `/logout`, `static`, `/`,
  `/favicon.ico`, `/csp-report`, `/health`, `/ready`), and
  `SELF_AUTHENTICATING_ENDPOINTS`, which are the routes the JSON API reads —
  `/status`, and `/series` with `/series/<path>`
  ([ADR-0122](adr/0122-a-series-is-read-over-the-api-as-it-stands.md) decision 8) —
  because each negotiates between a session and a bearer token and a gate in front of
  it would redirect an API client to a login form; each refuses both ways.
  Everything else is gated, including a route added tomorrow.
- **`identity.current_user()` is the one answer to *who is this request***, returning an
  `Identity` (`name`, `firstname`, `lastname`, `admin`) or `None`; `signed_in()` is the
  same for a view already behind the gate, and answers `401` rather than redirecting,
  because nobody there means a misclassified route rather than a visitor who has not
  logged in. Every template gets `is_admin` from that same call, through a context
  processor, so the shared header's admin-only nav entry follows the **identity** and
  not the session it happens to be kept in today — a view that passes `is_admin`
  itself still wins, and passes the same value from the same place.
- **Who somebody is comes from outside, through doors that are never a chain**
  ([ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)).
  `identity.use(name, provider, default=…)` registers an implementation as a named
  **door** from the import-before-app slot; the registering package is inferred from
  the call site, a name is claimed once and exactly one door is the default, and a
  second claim on either refuses at startup naming both. A provider answers
  `identify()` and `challenge()`; `login_page()`, `submit_login()`,
  `complete_login()` and `end_session()` are optional, because a provider verifying a
  header performs no login at all. **Several ways in are allowed, an ordered list of
  them to try is not**: `sign_in()` records which door produced the session and
  `current_user()` asks that provider and no other — a session naming a door that is
  no longer registered is nobody — so registration order cannot decide a `name` that
  pins and event authorship are stored against. `identify()` is answered once per
  request, and a provider that raises is **no identity**, logged, never a way
  through — the same containment covers `enterable()` (raising ⇒ not enterable,
  so one probe of an unreachable directory cannot take the chooser down for
  every other door) and `end_session()` (raising ⇒ logged, and the local session
  is cleared anyway, because logging out has to work *whatever* the provider
  does, including fails).
  A door carries an optional **`label`** — what a page calls it out loud, defaulting to
  the name, which is a path segment — and answers **`enterable`**: it has a
  `login_page` *and* its provider's optional `enterable()` does not say otherwise.
  **A contradiction refuses, an omission logs**: a second claim on a name or on the
  default stops the process where it happens, while *no door at all* and *doors with
  none of them the default* are a startup `WARNING` from `identity.announce_doors()`
  naming the line to add, on an instance that serves `/health` and answers `401`
  everywhere gated — refusing to start would take a monitoring application down for a
  mistake it can describe, and would refuse the more usable of the two, since doors
  without a default still admit anybody who knows `/login/<door>`. **No door at all is
  also the one of the two that `/ready` answers for** (§4.9,
  [ADR-0073](adr/0073-a-readiness-answer-beside-health.md)): an instance nobody can
  sign in to never becomes ready, while doors without a default are an instance anybody
  who knows the address can enter and readiness stays silent about them. **A default door can
  also stop being there**, which is nobody's omission — a credential that fails to
  resolve closes its own door — so `challenge()` sends an unidentified request to
  `/login` where the installation asked for the chooser and any door is registered
  (decided off the registry, never by asking `enterable()`, which a provider may answer
  by probing); without the chooser that address is the default door's own step and
  answers `404`, so `401` remains the answer and its message says which of the two
  states it is in.
- **The built-in login list is a provider like any other**
  (`little_sister.local_login.LocalUsers`, on the `local` door), including in how it
  gets there: `local_login.use_local()`, written in the installation's own
  import-before-app block like everything else it registers
  (ADR-0069 §3). The library adds no door on a deployment's behalf, so the ways into an
  instance are exactly the lines one file names. It stays the fallback for the install
  that needs no implementation at all, not the shape everyone else fits.
- **`/login` may offer the doors instead of going to the default one.**
  `identity.choose_at_login()`, written in the same import-before-app block, makes that
  address render `identity.door_chooser()` — one link per **enterable** door, the
  default first, labeled. **With nothing enterable it says so**, in one of three
  sentences, because the three states need three different actions: no door registered
  at all (somebody has to add a line); a door that signs people in without a
  `login_page` of its own — the header-verifying provider, the redirect flow that
  renders nothing here — which is not a fault at all and means the reader is on the
  wrong address; or every door registered with a page and none of them able to take a
  credential (something has to resolve). It names no door and no reason — that is
  `/system/installed`'s, and the System views are behind an admin session, while this
  page is open to anybody — so it says *that* there is no way in and where the answer
  is. **Where is not `/system/installed`**: reaching that page needs an administrator's
  session, and the third
  state is exactly the state in which no door can issue one, the system-admin door
  included. It points at the instance's startup output, which is where
  `announce_doors()` and the system-admin registration already wrote the door and the
  reason. Without any of it the page was a heading over an empty list, which is the
  state a deployment reaches whenever its doors resolve their credentials from
  somewhere a given machine cannot see. While there is a door to ask, `challenge()` is
  untouched, and
  that is the point: an unidentified request still goes wherever the provider sends it,
  so a live SSO session still arrives logged in having seen no page, while the address
  somebody *types* becomes a page **we** serve and therefore one that still answers when
  the identity provider does not. The exception is the case where there is no provider
  to ask — a default door that closed — and this page is then where an unidentified
  request goes, being the only address of ours left. Under it `/login` is not a door — it renders on `GET` and answers
  `404` to a `POST` — while `/login/<door>` is unchanged, which is what keeps the page
  from linking back to itself. A redirecting provider adds a `login_page()` returning
  its own redirect to appear there at all; a header-verifying one has no login step and
  is not listed, which is how that deployment gets a login page for the first time
  (§5.1, [ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)).
- **One door the library ships is not a provider's: the system admin**
  (`little_sister.system_admin`, on the `system-admin` door), because the provider can
  stop answering and that is exactly when somebody needs to get in. Configured with
  `identity.use_system_admin(reference=…)` — a secret reference resolved **once, at
  registration** — or the discouraged `password=…`; exactly one keyword, and each
  refuses the other's shape. Login name `admin`, hard-coded, compared with
  `compare_digest`; the door is never the default and always renders a local form, so
  it stays usable under a provider that redirects. A **failed** resolution shuts that
  door (`404`) while the application keeps serving and `/system/installed` says why; a malformed
  reference still fails startup. Nothing is ever generated. It is visible while in use
  — a distinct packaged avatar and `System admin` where the chrome prints a name, a
  `WARNING` on every login and every failed attempt, a row on `/system/installed` — and
  deliberately without a page banner. The built-in login page links to it below the
  form while `system_admin.usable_route()` answers one, i.e. while the account is
  configured *and* its credential resolved: a convenience for the install whose
  `/login` is a local form, since under a provider that redirects that template is
  never rendered. `identity.is_system_admin_session()` answers
  *which door*, so `Identity` keeps its four fields and `set_by` keeps recording the
  name alone.
- Users come from a flat `config/users.yaml`, or `config/users/users.yaml` beside
  `config/users/avatars/` (a map of `username → {firstname, lastname, password,
  admin?, avatar?}`), read **by `use_local()` and by nothing else** — so an
  installation that does not register that door carries no user list at all and never
  looks for one, while one that does still fails at startup if the list is broken
  rather than at the first login. `avatar` is a bare file name or stem; invalid,
  missing and ambiguous references warn and use the packaged neutral image without
  affecting login ([ADR-0045](adr/0045-user-avatars.md)). The avatars belong to the
  aspect, so under another provider there are none and every viewer gets the packaged
  image.
- **viewer / admin roles** — the built-in list stores an `admin` flag on the session
  it opens, and another provider decides `Identity.admin` however its directory says;
  admin-only actions are gated on it — the system page, and every act on a pin, which
  a route asks for by its name, `Identity.may(<act>)` — `maintenance` and `seen` — every
  one an admin's until roles map onto them ([ADR-0141](adr/0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md) decision 4).
- **Passwords in the built-in list are plaintext** (compared directly) — what another
  provider does is its own business. The credentials that are *not* that list — the
  system-admin password and the JSON API's bearer tokens — go through
  `secrets.same_secret`, one constant-time comparison over **bytes**: the standard
  library's own takes `str` only while both sides are ASCII and raises otherwise, so
  the obvious spelling answers a `500` to the first umlaut anybody types.
- **The session cookie is `Secure` when the connection was** — decided per request from
  `request.is_secure`, never from configuration or a host name, so the flag is right on
  a plain-HTTP install and on a TLS one without either being told which it is. A
  configured `SESSION_COOKIE_SECURE` can only add the flag, never remove it, and no
  `Strict-Transport-Security` header is sent
  ([ADR-0065](adr/0065-the-connection-decides-what-is-secure.md)). It also says
  **`SameSite=Lax`** outright rather than leaving the one cookie that carries a login
  to a browser default, which is what withholds it from a cross-site form post on an
  application whose state-changing POSTs carry no CSRF token; `Lax` rather than
  `Strict` because a door's callback is a top-level navigation back from an identity
  provider and `Strict` would arrive there with no cookie
  ([ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md) §4).
- `secret_key` comes from **`SECRET_KEY`** — a literal value, or itself a secret
  reference resolved once at startup; **unset means a random per-start key**
  (sessions reset on restart)
  ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md),
  [ADR-0023](adr/0023-secret-references.md)). `.env` feeds the
  environment via a dependency-free loader.
- **JSON backend mode** — `GET /status[/<path:branch>]` and `GET /series[/<path>]`
  with `Accept: application/json`
  are gated by a **bearer token** (named per-client tokens from the
  `LITTLE_SISTER_API_TOKENS` setting — a literal, or itself a secret reference —
  compared with `secrets.compare_digest`); the session
  cookie isn't accepted there. Errors are **Problem JSON** (RFC 9457), and an inbound
  `X-Flow-Id` is echoed. Read-only; the contract is
  [`api/openapi.yaml`](api/openapi.yaml)
  ([ADR-0080](adr/0080-the-envelope-is-the-snapshot-published.md)), and what the
  status read publishes is the snapshot the dashboard renders — a field added to one
  is added to the other in the same change. A node that has a handbook says where it
  is, `handbook`, the absolute address of its Handbook view as the request reached
  the server, which the web layer hands `api.status_envelope` (`handbooks`); its text
  rides in no envelope, and a link a text writes in the short form stays raw, the
  contract saying what it means
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decisions 3 and 4). A node that has details carries its own, `details`, as the
  snapshot holds them — each `{key, text, by}`, the type's first and then the
  deployment's, each as given — and never the rows its card resolves: the contract says
  that the deployment's hold for every node beneath, key by key, the nearest winning,
  and the type's stand first on their own node, so a client draws the card from the
  nodes above as the page does (decision 6). A node that carries tags carries every one,
  `tags`, those written for it and above it, in its card's order — its whole set, so
  that a subtree read by its path says them of its root too
  ([ADR-0139](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md)
  decision 6). A node and an entry list what handles them, `handled` — a person's pin
  while it stands, a configured rule while it changes what counts — and a
  `contribution` names the rule that decided, `rule`: `schema_version` 3
  ([ADR-0141](adr/0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md) decision 3). The series read publishes what the
  memory tier keeps (§4.10) where the Series view shows it (§5.1,
  [ADR-0122](adr/0122-a-series-is-read-over-the-api-as-it-stands.md)). Each read has
  one answer written down in `little_sister.contract` — `envelope-3.json` and
  `series-3.json` — generated from this API and held to it by
  `test_contract_fixture.py`.

### 5.3 Presentation preferences
How a viewer sees the surface — the **theme**, the **layout** and the other looks —
is theirs to choose, and the choice is **presentation only**: it lives in one
long-lived cookie per browser (`ls_prefs`, url-encoded `theme=…&layout=…`, a year,
`SameSite=Lax`), never in the server, so there is no per-user state to store or
migrate ([ADR-0029](adr/0029-per-user-presentation-preferences.md)). The layouts are
`LAYOUTS` (`rail`, `topbar`, `kiosk`), `rail` the default, a constant.

The theme is one of the **looks**, how the page draws what it says: one roster,
`LOOKS` in `looks.py`, each entry a key of the cookie and of `settings.yaml`, its
values, the library's default, its group's heading, the line beneath it that says
what the group changes and its values' words in the settings menu, and its attribute
on `<body>`, `data-ls-` and the key with hyphens. Seven: `theme` (`auto`, `plain`,
`vivid`, `pastel`, `dark`, `cyberpunk`, the library's
cyberpunk; `plain` was called `default` until 2026-10-18, and a cookie that still
says so follows the deployment's default), which the settings menu leads with, the
layout after it ([ADR-0028](adr/0028-design-tokens-and-themes.md)); `chip_runs`
(`aligned`, `wrapped`), how a run of chips is drawn (§6); `boxes` (`rows`, `packed`, the
library's `rows`), how a level's boxes fill its columns (§6,
[ADR-0138](adr/0138-a-viewer-may-pack-a-levels-boxes.md)); `inspection_card` (`pause`,
`off`, the library's `off`), whether a pause on a name opens the inspection card
(§6); `toggle_hover` (`outline`, `wash`, the library's `wash`), how a head's row
and a chip answer the pointer (§6); `head_buttons` (`pointer`, `pointer-name`,
`line`, `name`, the library's `pointer`), where an open head keeps its buttons (§6);
and `failures` (`open`, `chips`, the library's `open`), whether the failure budget
opens a failure's way or every failure stays the chip its look drew (§6), its line
saying that the default is the one to keep, a kiosk's too. The layout's line is the
menu's own, `LAYOUT_LINE`, since the layout is no look; every line describes its
group's radios (`aria-describedby`), so a screen reader reads it with the choice.
A look's default is the **deployment's**, `config.looks` from `settings.yaml`, which
reads YAML's `off` — a boolean when unquoted — as the word, and falls back to the
library's own with a warning naming the choices. So the cookie carries a look only
once a browser has chosen it: `/preferences` writes a posted value that differs from
the deployment's default, or one that replaces a value the cookie already had, and a
browser that never chose follows the default when a deployment changes it.

- `_presentation()` parses the cookie and resolves each key **independently** onto
  its default — a missing cookie, an unparsable one, a retired value or one typed
  by hand can only ever show the default, a look's the deployment's. A preference is
  a look; a bad one must not be able to break a page.
- An `@app.context_processor` (`_inject_presentation`) hands every template the
  resolved `theme` / `layout`, the layouts' roster, `looks` and the `look_values` in
  force (the settings menu builds itself from them: the theme's group, the layout's,
  then a group for each other look, each a radio group its heading names and its line
  describes, the groups in two columns where the window is at least 36rem wide and in
  three where it is at least 72rem),
  `layout_line`, `default_layout` (the kiosk's exit is a write
  of that value) and `bs_theme` — `dark` for the dark-family themes, so Bootstrap's
  own chrome follows. `_header.html` renders them onto `<body>` as one attribute a
  look, `data-ls-theme` first, and `data-ls-layout` / `data-bs-theme`, so the scheme
  and the looks are **server-rendered** and no page flashes the wrong one.
- `auto` is the one theme a server cannot resolve — only the browser knows what the
  OS asks for. The stylesheet follows it through `prefers-color-scheme`, and three
  inline lines at the top of `<body>` set `data-bs-theme` for Bootstrap's part,
  before anything paints. Every other theme needs no script at all. Those lines are
  `_theme_bootstrap.html`, included by the header **and** by the login page, which
  has no header: **one** inline script, so the policy of §5.4 spends one hash on it
  rather than two. They stay inline on purpose — a `defer`red file runs after the
  document is parsed, far too late, and a blocking one would put a request in front
  of every cold load's first paint.
- Both preference forms **submit on change** rather than offering an Apply button:
  each control carries `data-ls-submit` and `static/js/prefs.js` submits its form,
  delegated on the document so a control that arrived with a poll fragment still
  works. It is a script and not an `onchange` attribute because an inline handler
  takes neither a hash nor a nonce (§5.4). Each form keeps a `<noscript>` submit, so
  a choice can still be applied without JavaScript.
- The **kiosk** is the one layout the server branches on (`_header.html` omits the
  bar and the rail outright, and emits `_kiosk_line.html` instead); `rail` and
  `topbar` are the same markup, with CSS deciding whether the sections show in the
  rail or in the bar — and below 576 pixels in the bar for both, folded behind its
  toggler: on a phone the rail gives way, the preference untouched
  ([ADR-0105](adr/0105-a-page-is-laid-out-at-its-screens-width.md) decision 8).
- This cookie and the **view** cookies of §5.1 (the two filter switches) carry
  `Secure` under the same rule as the session cookie — the connection the request
  arrived on decides ([ADR-0065](adr/0065-the-connection-decides-what-is-secure.md)).
  Nothing here is worth stealing; the flag is uniform because a rule with an exception
  is one somebody has to remember.

### 5.4 Content-Security-Policy — `csp.py`

Every HTML response carries a **`Content-Security-Policy-Report-Only`** header, set
by the application's one `after_request` hook. Report-Only means exactly what it
says: a violation is reported and **nothing is blocked**, so shipping it changed no
page's behavior. JSON API responses and static files do not carry it — the policy
governs how a *document* may be built, and on those it is a header no browser
consults.

The header value has **no constant**. `csp.py` holds the library's `DEFAULTS`, the
contributions dependent packages make, and the deployment's own last word, and
composes the value **at application creation** — after every registration has run and
the configuration is loaded, never at module import, because import is when
contributions are still arriving
([ADR-0048](adr/0048-an-assembled-content-security-policy.md)). The reason is the
packaging phase: `script-src` names **origins, not files**, so `'self'` already covers
every extension's *code* (ADR-0037 serves it from our own origin on purpose), but not
the origins that code **reaches** — an issue tracker a filler calls, a vendor's images
a check embeds, an identity provider a plugin redirects to. Those differ per
deployment and cannot be known here, and a header shape deployments already depend on
is a compatibility break to revise.

- **The library's floor** is what our own pages need: `default-src 'self'`, the CDN
  that serves Bootstrap and Floating UI in `script-src` / `style-src`, `'self'`
  elsewhere, `object-src 'none'`, and the `report-uri`. Two asymmetries are
  deliberate. `style-src` keeps `'unsafe-inline'`, because several `style=` attributes
  carry *computed* values (a card's reason-line cap, `/about`'s ring geometry) which
  cannot be hashed even in principle, and an inline style is not the vector a reason
  line is. `img-src` names no host, because Markdown images are on and unconstrained
  (§4.7) — that is the directive with something to measure. It takes `data:`:
  Bootstrap draws a switch's knob and the bar's burger as `data:` images, and a
  `data:` image calls no host, so our own controls report nothing.
- **The one inline script is named, not reported.** The theme bootstrap (§5.3) enters
  `script-src` as a `'sha256-…'` taken from the **rendered partial** at assembly, so
  the hash is the bytes the document actually carries and cannot drift from a second
  copy in Python.
- **A package contributes** with `csp.allow(directive, source, by=…)` from the same
  import-before-app block it uses for check types, fillers, assets, icon packs,
  aspects and secret resolvers. It may name an **origin, never a keyword**:
  `'unsafe-inline'` and friends are refused, because one dependency able to relax the
  policy would make it decorative for every other package in the process. A source
  carrying a path, userinfo, a bare scheme, any `*`, a scheme a browser does not fetch
  over, an unknown directive or one the library keeps to itself (`default-src` above
  all — widening it widens everything that falls back to it) is a **warning and a
  skip**, like every other registration seam here. What is accepted is stored as the
  origin the *parse* yields, not as written, so one host named in two cases is one
  entry.
- **A source is one token, and that is enforced, not assumed.** The assembled value
  separates sources by whitespace and directives by `;`, so a "source" containing
  either is not one source — it is several, and the last could be a directive of its
  own placed *ahead* of the library's, which is the occurrence a browser honors. Both
  contribution paths therefore refuse any source carrying whitespace, `;`, `,` or a
  control character before looking at anything else. The control characters matter
  twice over: a header value holding one cannot be assigned, so a single stray newline
  in `config/csp.yaml` would otherwise have taken every page down at request time
  rather than failing at startup.
- **A deployment-specific host is declared, not written.**
  `csp.origin_of("<aspect>.<field>")` points at a field in the package's own
  configuration aspect (§7, [ADR-0035](adr/0035-registering-a-config-aspect.md));
  it is read at assembly, the last configuration root wins, and the value is reduced
  to `scheme://host[:port]`. So the host stays written once and cannot drift out of
  the file an operator edits.
- **The deployment has the last word** in `config/csp.yaml` (§7): sources it adds, and
  the only place a keyword, a bare scheme or a wildcard host is taken at all. So a
  source nobody anticipated is a configuration line rather than a fork. It adds and
  never subtracts, which is why a configured `'none'` is **refused** rather than
  quietly reverted: it reads as locking a directive down and cannot do that, since
  `'none'` means something only when it is a directive's only source. (Where a
  contribution lands on a directive the library set to `'none'`, that keyword is
  dropped — it is invalid beside anything else — and the drop is a `WARNING`, because
  the directive is then *wider* than the default.)
- **A page adds what its own configuration names**, on its own response and no other
  page's. `/links` adds to `img-src` the hosts its icons load from — the site of an
  entry whose mark falls back to its favicon, the host of a remote mark — taken from
  `links.yaml` as the page renders: `LinksConfig.mark_for` decides which images an
  entry is drawn with and where each comes from, and the page's policy is read off the
  same answer, so the two cannot drift. The viewer's browser fetches those icons,
  never the instance: a browser that can open a link can fetch its icon
  ([ADR-0030](adr/0030-curated-links.md)). A favicon that redirects to a host the file
  does not name is still reported.
- The assembled policy is a **value**, which is why what a browser would be told is
  asserted in unit tests without a browser, and printed on `/system/installed` with the
  contributor of every source — and, on its last row, what `/links` adds, answerable to
  the file that names it.


---

## 6. Templates & static

Jinja2 templates under `templates/`, with `StrictUndefined` (an undefined variable
raises rather than rendering blank).

No page is wider than the screen it is read on
([ADR-0105](adr/0105-a-page-is-laid-out-at-its-screens-width.md)). Every document
declares its viewport, so a phone lays a page out at its own width; every table of
every template stands in a box that scrolls it sideways — Bootstrap's
`.table-responsive`, made `position-relative` so that what is placed absolutely inside
it cannot widen the page, and carrying the outer margin its table had; a readings
table's own box; or the one around the formats an expiry field takes — and what is not
a table gives way: the band's filters, its trail and the node's title take another
line, as the wall's strip does; a node's name breaks after an underscore, a dot or a
hyphen on a card, a box, a node's page and in the trail, and a name or a word with
nowhere to break breaks inside itself, there and in a pin's sentence.
`tests/test_phone_layout.py` holds the declaration and the boxes in the gate, and
`tests/test_phone_browser.py` measures every page on an emulated phone
(`docs/testing-the-gui.md`, Mode 5).

- `_header.html` — the shared `<head>` tail (the viewport declaration, the tab title,
  the icon set and manifest, Bootstrap and `overview.css`) and everything above the
  page: the
  presentation attributes on `<body>` (§5.3), the **top bar** (the brand, which is
  the way home, and the settings menu), the **rail**, and — only while the engine
  failed to start — the persistent `engine_error` banner (§4.6). It also *opens*
  the shell (`.ls-shell` and `<main class="ls-page">`), which is why every page
  ends with `_page_end.html`; a page that forgets it renders unclosed. Under the
  `kiosk` layout the bar and the rail are omitted outright and `_kiosk_line.html`
  stands in their place. The tab **title** reads *page* · *brand* — the page first,
  because a narrow tab truncates from the right and `poll.js` prefixes "(stale) "
  to whatever it says. Two script tags are emitted here rather than per page, so no
  page can forget them: `_theme_bootstrap.html` (§5.3) and `static/js/prefs.js`. The
  viewport declaration is the device's width at its own scale and says nothing about
  zooming; `login.html` and `choose_door.html`, which take no header, carry it
  themselves.
- `_theme_bootstrap.html` — the three inline lines that resolve the `auto` theme
  before first paint (§5.3). Its own partial because the login page carries no header
  and needs the same behavior: one inline script means the policy of §5.4 spends one
  hash, where two copies would have cost two forever.
- `_brand.html` — the brand sentence in **one place**: the figure, the lowercase
  wordmark and the tagline, «little sister *is watching for you.*». `brand_figure`
  picks the figure — the one-eyed **mark**, which winks on hover, for the bar and
  the kiosk line; the two-eyed **gaze** (`_gaze.html`), which blinks on its own,
  for the login page and `/about`. Both are inline SVG inked from the brand tokens,
  so a theme re-inks them without forking the geometry, and both hold still under
  `prefers-reduced-motion`. `brand_name` is the seam the web-customization phase
  makes deployment-settable.
- `_nav_items.html` — the sections (Status / Series / Events / Handled / Links /
  Copy, plus **System** for admins; Series lit on every Series view as Status is on
  every status page), written once and rendered by `nav_style` into either
  the rail or the bar. `_about_entry.html` is the way into `/about` in whichever of
  the two is showing — deliberately apart from the sections (the rail's foot, below
  a spacer; the last, quietest entry in the bar), because it is not a place you go
  to work.
- `_settings_menu.html` — the current user's circular avatar and name open it: the
  configured picture or packaged neutral fallback. Its first row is the session's:
  whom this browser is signed in as, the identity's `name` (`signed_in_as`, a context
  processor of its own), and **Log out**, a button drawn from the danger ink — it
  moved in here when the bar lost its red button, and to the top, above the looks and
  outside their form, on Lex's word of 2026-10-24, so that it is in reach as the menu
  opens however short the window. Beneath it the headline *Display* and its line,
  *Saved in this browser, not in your account.*, which name and describe the form,
  then **theme**, **layout** and the other looks as radio circles that post to
  `/preferences` (§5.3) with the current page as the return path. The grayed
  "settings…" that reserved a row for the later per-user overrides of `settings.yaml`
  went the same day: it comes back when there is something to draw. Its foot,
  *Using the wall*, leads to `/help` (ADR-0136): the last thing in the groups' flow, so
  that in the columns it stands at the last one's foot and the menu is no taller for
  it. Each radio carries `data-ls-submit`, so `static/js/prefs.js` submits on change and
  the `<noscript>` Apply button is what a JS-less browser uses instead. The menu stays
  open while a viewer chooses: the trigger's `data-bs-auto-close="outside"` keeps a click
  inside it from closing it, and `prefs.js` writes a choice made in it to the tab's
  session storage before the form goes and, on the page that comes back, opens the menu
  with the focus on that choice, the entry read once; a filter switch of the band writes
  nothing, and a refused storage leaves the menu shut.
  `static/js/rail.js` is the rail's counterpart — its burger swaps the collapsed
  icon rail for icons + labels, deliberately *not* remembered: collapsed is the
  layout's default and the burger is a peek, while presentation that is remembered
  belongs to the one cookie. Per [ADR-0062](adr/0062-navigation-chrome-is-layout-behavior.md),
  pinning is behavior of both interactive layouts, not another preference. The bar
  and rail are sticky while the **window remains the scroll container**, preserving
  the viewport coordinate system used by the inspection and maintenance popovers.
  CSS supplies safe scriptless geometry; the script observes the rendered border box
  and publishes both its exact height and the non-section footprint of the first row.
  It recognizes a wrapped section list from its position below the settings row,
  without copying Bootstrap's breakpoint into JavaScript.
  A short rail scrolls internally. Below the top bar's collapse breakpoint, the first
  row stays visible while an over-tall section list scrolls beneath it; the settings
  dropdown takes the same measured budget, not the expanded bar's height.
  Content-anchored reason editors pass
  behind the chrome, while viewport-positioned popovers stay above it. The kiosk
  renders neither element, so none of this behavior reaches it.
- `_page_band.html` — one aligned band per page, replacing what used to be a title
  row, a loose `about` paragraph and a freshness caption stacked down the page:
  breadcrumb/title on the left, the updated-line and the filters on the right, the
  node's `about` beneath, and — on a page that is one of a node's views (`view`) —
  the tabs closing it, Status, Series where `series_tab` says a curve can stand,
  History on every node but the root, and Copy on every node and on the root, whose
  Copy is the tree's document, the current one underlined on the band's own rule
  ([ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md),
  [ADR-0115](adr/0115-a-copy-document-says-where-it-is-from-and-since-when.md)
  decision 7). The trail's crumbs open the same view of each ancestor
  (`_breadcrumb.html`).
  `band_stamp` / `band_filters` say which parts a page has
  (the dashboard both, a detail page neither) and default to off, so under
  `StrictUndefined` a page must ask. The freshness line is styled as the ADR-0005
  measurement it is — tabular figures, so the digits don't dance on each poll — and
  nothing here may set a `color` on it: `poll.js` swaps `text-muted` for
  `text-danger`, and both Bootstrap utilities are `!important`, so a color of our
  own would lose and a stale line could read muted instead of red. The kiosk has no
  band; its line carries the stamp instead, so the page still has exactly one. The
  filter controls carry `data-ls-submit` and the same `<noscript>` fallback the
  settings menu has (§5.3). Where the band is narrower than the four of them they
  take a second line, beneath the stamp, which on a phone loses the rule that marks
  it off from them (ADR-0105 decision 4).
- `_kiosk_line.html` — the wall-display header: the brand sentence, the same stamp
  element the dashboard uses (same id, same seeded `data-rendered-at`, so the poll,
  the outage banner and the "(stale)" prefix all behave identically — an unattended
  screen is precisely where a frozen one must announce itself), and **exit**, which
  is not a mode switch but a POST writing `default_layout` back to the presentation
  cookie.
- `help.html` — how the wall is used
  ([ADR-0136](adr/0136-how-the-wall-is-used-is-one-file-the-package-ships.md)): the
  account the package ships in `help/using-the-wall.md`, drawn as `handbook.html` draws a
  handbook, its headings anchored, at the same measure and in no node's band.
- `about.html` — the identity page, built as **one hero** and centered in the
  window: the gaze, the wordmark and the version, with the terms she watches in
  orbit **behind the eyes** on two faint rings wider than the reading column, and a line at a time underneath — a couple of clauses, an
  observation, then the nine-line ending, after which it stops. The identity is
  told once here rather than three times (the bar, a block, and an animation with
  an eye of its own). Color carries one meaning each: **green is seen** — spent
  only on the term the eyes are on and on the phrase in the story that term names
  (`data-topic`, paired by `static/js/watch.js`) — **pink is her**, and everything
  at rest is muted. Monospace is for the orbiting **signals** only; a sentence is
  hers and keeps the page's face. The lines and the outer ring are **drawn per
  render** from `watch_lines.py`, so a second visit differs. It is the one place
  motion is allowed — the dashboard stays still because anything moving there
  competes with the one signal that should — and all of it stops for
  `prefers-reduced-motion`, where the rings hold still, nothing is drawn as seen,
  and the ending shows its last line alone.
- `_breadcrumb.html` — the clickable header path trail: `nodes`, the tree's root, then
  a link per ancestor segment, the current node plain; each crumb opens the view the
  page is in — `nodes` that view's root, which for History is the overview — and the
  trail is the same on every view (ADR-0097 decision 3). It keeps one line while the
  band has the room and takes as many as it needs where it has not, each ending in its
  slash: the space before a slash does not break and the one after it does. The
  node's title beside it takes what the trail leaves of the line and is cut short
  there; it takes the next line where the trail leaves nothing, and on a phone where
  it leaves less room than a word needs (ADR-0105 decision 4).
- `status.html` / `_status_grid.html` — the **dashboard**: top-level systems as
  cards in a responsive grid. **Every system and subsystem is a filled rounded box
  colored by its own rolled-up status, nested inside its parent's box** (so a
  green branch shows clearly inside a red system), each carrying its reasons; a
  translucent edge keeps same-color boxes legible. To surface the **culprit**, a
  box is shown **vivid** only when it reports its own status; a box whose status is
  merely *derived* from a visible child — and any healthy (OK) box — is **dimmed**
  (pale fill, dark text), so the eye follows a faded trail down to the bold
  originating node. Whether a status is derived is the snapshot's one answer for a
  card, a box and a page's head (`StatusSnapshot.derived`, §4.3), and no template
  compares a node's two statuses for it. So status never rests on **color alone**, each card, node box and
  the strip also carries a small **per-state shape cue** — a check (OK), triangle
  (warn), filled disc (error), pause bars (maintenance), a hollow ring (idle) — beside
  the fill, and the warn/error status word is lifted out of the muted state text, so a
  red/green color-blind viewer can still separate error from OK. A **node box ends
  its head line like a card head does**: a right-aligned state cluster
  (`.status-node__state`) of staleness, the topmost-visible check time, and the
  status word — a box used to lack the word, which left its time dangling after the
  title and made the state read incomplete beside the cards. The box keeps its
  single leading cue for the shape channel; the cluster repeats no glyph. With the
  word visible on every surface, **every** card, box and strip glyph is decorative
  (`aria-hidden`) — the word beside it speaks, and a named cue would
  double-announce; the one cue still named for a screen reader (`role="img"` + an
  `aria-label`, WCAG 1.1.1) is a **coded reason line's**, which has no status word
  of its own. **A head's row never wraps**
  ([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  decision 3): the cue and the name; the title in a zero-basis middle
  (`.status-head__middle`), which gives way first, with an ellipsis; the state
  cluster, no control; and the head's buttons, **one toolbar**
  (`.node-controls[role="toolbar"]`, named *<node> controls*): the head's own icons
  first (`.node-icons`), ↗ the first of them, so that on every head the button that
  opens the node's page is the first after its name, then the funnel, ▤ and ‖; then
  the node's actions (`.node-actions`, the `node.actions` slot of §6.1 — an action
  that names an icon a square like the head's own buttons, its label its tooltip and
  accessible name, one that names none a small chip wearing its label); then ⋯
  (`button[data-control="actions-more"]`, `hidden` until `tree.js` folds behind it the
  actions the row has no room for, whose menu lists them by their labels). An empty
  `.node-icons` — a leaf's own page, the leaf with a pin of its own — keeps no room,
  and under a coarse pointer the taps of the toolbar's first and last squares reach
  no further than their edges. Where the toolbar stands is the look
  `head_buttons` (§5.3), which `node_controls` draws in its order and the stylesheet
  answers on `<body>`: under `pointer`, the library's, right after the name, the title
  and the state after it, and seen only while the pointer is on the head, the keyboard's
  focus — not a click's — is in it or its menu is open, by its `opacity`, so that the
  keyboard and a screen reader find it as ever; where `(hover: hover)` holds it takes no
  room in the row, the title standing right after the name and the toolbar, shown, lying
  over it on the box's own fill (`--ls-surface`), so that nothing moves when it shows,
  but in a row `tree.js` marks `.is-crowded`, where the name gives way even with every
  action folded and the state beneath, which keeps its room for the name to break
  beside; and always shown, in its room, where `(hover: hover)` does not hold, on a
  touch screen; under `pointer-name` there too, with the name the link to the node's
  page as under `name`, below; under `line`, on a line of its own beneath the row, from
  under the name, the row wrapping there and wrapping its state beneath, at the right,
  where it has no room for it, so that `tree.js` reads no row under that look — and
  under `card_status_line: below` a card's state stands at the right of the toolbar's
  line; and under `name`, at the row's end, the state before it, as ADR-0127 first drew
  it, where the pointer's click on an open head's name follows its link to the node's
  page: `tree.js` lets a click with a pointer (`detail` not 0) on an open node's name
  through, the keyboard's Enter (a click with `detail` 0) and Space still open and close
  the node, and ↗ is hidden but for a screen reader until it has the keyboard's focus.
  Nothing else is laid over the title: the toolbar alone, while it shows, on the box's
  own fill. `tree.js` reads each shown row — as a box opens, when the grid's
  width changes, when the pointer turns coarse or fine and once the fonts have
  settled, and after a swap only a row the server drew otherwise, or that stands at
  another width, than one it read before, the others drawn from what was read of them
  — always once `dashboard-layout.js` has laid its plan, so at the width the row's
  card is drawn at; it reads a row as it would be with the
  title gone, every action and ⋯ shown and the state in the row, and from how far it
  overflows folds actions from the last behind ⋯ — nothing where ⋯'s own square and
  gap would give the overflow back, ⋯ standing only where something folds; where not
  even every action folded leaves the name whole, or where one action would fold
  alone and the state's line keeps it in the row
  ([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  decision 3), the state takes a line of its own beneath (`.is-state-below`: the
  cluster placed at the head's foot, the head padded by one line, or by the lines it
  breaks into, below), and the actions get its room back;
  the name gives way last and wraps where its words meet — after each `_`,
  `.` and `-`, which the `breakable` filter marks `<wbr>`, no character, so a copied
  name and the accessible name are the name itself; inside a word only where one is
  longer than its line — and where it has broken
  onto a second line anyway, the state stands on that line, at the row's end, instead
  (`.is-state-beside`: no padding, the toolbar at the row's top), which `tree.js` tries
  on every head whose state is beneath and keeps only where the name did break and the
  cluster, the toolbar's gap before it, touches neither the name's lines nor the
  toolbar's items. A title
  left less than 2.5em is hidden (a container query on the middle) rather than shown
  as a clipped glyph. The state cluster keeps its whole width in the row; on a line of
  its own narrower than it is it breaks between its parts — the stale mark, the pin's
  pip, the time, a card's cue and word (`.status-word`), the reading beside them
  (`.status-reported`) — right-aligned, each part whole where the line has room for it
  and broken at its own spaces only where it alone is wider than the line (the time, a
  card's word and the reading inline blocks, the stale mark leading the cluster), and
  `tree.js` pads the head by the lines it takes (`--ls-state-room`, read after the row
  and kept for the refresh with it), so that nothing of it runs out of its box; a closed
  card's state takes its line in the head's flow, under `below` too, and the flow makes
  that room. Where a card's cluster *sits* is the deployment's choice
  (`card_status_line`, §7): `beside` keeps the compact one-line head, the state
  beneath only where the name would be cut; `below` makes the line the rule — a
  standing second line on every card, the same shape everywhere, the actions and the
  icons on the first line with the name but under `head_buttons: line`. One control of
  the toolbar is its tab stop
  and the rest are `tabindex="-1"`: Tab goes from a head's name to its toolbar and
  on to the next node, ← and →, Home and End walk the controls, and which control
  holds the stop is kept by node in memory for the page's life and given back after a
  swap, as the focus is. A square is 1.5rem, 24 pixels at the browser's own size and
  the touch target, and its glyph 1rem, two thirds of it at any font size. On touch
  (`pointer: coarse`) the squares stand 8 pixels apart and each one's tap area grows
  to the middle of the gap, none over the state word. The whole row but its controls
  opens and closes its node (decision 11), and **the row says so itself**, no caret
  before it: under the pointer, where `(hover: hover)` holds, an outline of its
  surface's own ink, 3 pixels out, and pressed a wash of that ink reaching 4 pixels
  past it — neither while the pointer is on a control of its own, the ones `tree.js`
  lets a click keep (`OWN_CONTROLS`), which `:has()` reads. Both looks are drawn from
  tokens on `:root` (`--ls-toggle-hover-line`, `--ls-toggle-hover-wash`,
  `--ls-toggle-press-wash`: the outline's share of the ink, a wash under the pointer
  and the press's, 60 %, 0 and 12 %), so the look `toggle_hover: wash` (§5.3), a wash
  in the outline's place, sets tokens and no rule — `body[data-ls-toggle-hover="wash"]`
  sets the outline's share to 0 and the wash to 10 %, and under forced colors puts
  both back, so the outline stands there either way. A chip answers the pointer the
  same way from the same tokens, its outline a pixel out where chips stand close and
  never over the ring the keyboard's focus draws, its press a wash laid over its tint
  as a `background-image`. A box's links underline under the pointer, a head's name
  and a chip do not — but an open head's name under `head_buttons: name` and
  `pointer-name`, where it opens the node's page and the row's own answer keeps off it
  while the pointer is on the name; a head's row and a chip show the pointer's cursor,
  and a name
  whose pause brings the inspection card — a chip, the name in a head — the help
  cursor; a node's page's own head, which is no toggle, shows the arrow. **The wall is a tree**
  ([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)):
  every node the filters leave is drawn, closed — a **chip**, its cue, its name and
  what is beneath it counted — or open — a **box**, today's card or nested box with
  its head, its lines and its children — and a click on it changes which, where it
  stands (§6, the tab's map). A `depth=N` in the address closes every node N levels
  below the viewed node for that one load, the wall's cards being level 1 — the
  viewer's word, like the band's three buttons, never a cookie (`_resolve_depth`
  reads the address alone, and the `depth` and `dense` cookies the band once wrote
  are expired by the first answer that finds one) — and `depth=0` closes the viewed
  node itself to a single card carrying its rolled-up status (an overall traffic
  light), its head and its counts. From depth 1 the viewed node **heads** its page, wherever it has
  something of its own to say or its reader may pin it, with **what it rolls up to**:
  the status its card says on the page above, so a node is one status wherever it is
  read ([ADR-0123](adr/0123-a-node-says-one-status-wherever-it-is-read.md) decision
  1). The head is pale where that status is **derived** — not what the node counts for
  itself, so from beneath it, where the node that makes it so stands — and vivid where
  it is the node's own, its own reading gone stale included (decision 2). A node that
  declares nothing is the plain case of a derived one: its `UNDEFINED` is a
  container's, which the roll-up skips
  ([ADR-0039](adr/0039-status-rollup-semantics.md)), so one that carries a sentence
  (an `aws` check's root states its scope) heads with what it rolls up to, which is
  the code a kept reading records for it too
  ([ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md) decision 8).
  Nodes drill down; a **hide-ok** switch drops OK nodes and a
  **hide-idle** switch drops never-reported (UNDEFINED) ones — beneath the viewed node,
  never the node itself: where they drop every child, the grid says what they hid in
  the switches' own words (`_nothing_left`) — *All 14 nodes are ok.*, *The only node
  beneath aws is idle.*, *11 nodes are ok and 3 are idle.* — and the node keeps its
  head, its card at depth 0 and its own facts below. On the overview that is what a
  problems-only wall says on a good day, where *No checks reporting yet.* is left to an
  empty tree; the two switches persist across visits in a `SameSite=Lax` cookie set on an explicit change (the chips switch and the depth control went with dense mode: a closed node is the chip, and opening a node is its depth); **stale** nodes get a
  badge; a node with an unambiguous **observation time** — its own last
  write, or the run time of the single check below it — states *when* beside *what*, as
  a muted time of day (`settings.yaml`'s timezone, ADR-0120) sitting just before the cue
  and status word, and shows **nothing at all** where the question has no single answer
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)) — the absence is the
  signal, and the freshness *alarm* stays the stale badge, normalized per node
  against the tolerance the server applied — a check's period implies one, and a node
  with no period may state one
  ([ADR-0081](adr/0081-an-instance-node-states-a-tolerance-not-a-period.md)). The time shows on the **topmost node visible in the current
  view** and is suppressed below, where it would be identical
  ([ADR-0044](adr/0044-run-facts-on-the-node.md)): the branch head carries it when
  it renders, a card carries it as before, and a **nested box** now carries its own
  where no visible ancestor already shows the same one — which is how a sole-check
  container sitting under a two-check card finally states when its check ran.
  Suppression compares the displayed rendering, and it is safe because an ancestor
  carries a stamp only where a single check owns everything beneath it. The **next
  update joins the check time** wherever that time shows and the node carries its
  check's run facts (`_next_update.html`, on the grid and the branch head — the
  detail pages state it in words in their Time card instead, and printing both
  would say it twice): **`22:25 → 22:30`** — absolute, the whole pair at
  minute precision (seconds carried no information worth the row width), and the
  arrow suppressed where it would repeat the value beside it, so a sub-minute
  schedule shows a bare time and the arrow appears exactly when it adds
  information. Absolute is freeze-safety: under a failed poll the
  staleness dim leaves the page on screen, where a frozen relative "in 4m" would
  keep looking live while a frozen `→ 22:30` stays true and recedes; a stalled
  check honestly shows a next update already gone by, and the stale badge beside
  it carries the alarm; a node's short `title` (ADR-0017) follows the name (ellipsed, `.node-title`) on
  a card and the breadcrumb in the page header — unless it only repeats that name,
  which no surface draws, and where a surface draws it *instead of* the name it comes
  with the name unless it carries a word (§4.5); and a node's Status tab says its
  `description` and its `about` once, in its *About* card beside its facts
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 1, §4.5), and no other view of it says either; since the `about` is the short
  account of the node, the startup consistency pass notes one past 400 characters
  (`nodes.note_long_about`), and the engine one a run hands over when it first fills
  its node.
  Admin **maintenance**
  ([ADR-0014](adr/0014-maintenance-persistence.md)) is surfaced so a pin the roll-up and
  depth hide is still findable: a maintenance-tinted **pill** joins the status strip (a
  ringed diamond and a live count of the pins that stand, *2 handled*, its words by job
  in its name — *2 handled: 1 node in maintenance, 1 line in maintenance*,
  [ADR-0135](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md) decision 6 — shown only when
  something is pinned), and clicking
  it opens a popover (`static/js/maintenance.js`, reusing the inspection popover's Floating-UI positioning and poll-swap survival) of the pinned nodes (path, time left, reason, each linked) — **one row per node**, so a node with twenty pinned *reasons* contributes one row carrying a count (*3 of 20 reasons*, or *all 20* where nothing is left reporting) rather than twenty that would evict everything else; capped
  at `maintenance_cap` with a **"+N more"** to ***Handled***, the page at **`/handled`**
  that states the full, uncapped set (decision 8), which the pill itself links to; a
  maintenance-tinted **pip**, the same diamond, still marks any ancestor card whose
  subtree holds a pin, opening the same popover scoped to that card. All are built from the *unfiltered* snapshot, so
  hide-idle and a shallow depth don't hide them.
  **On the wall a pin is stated and set in the card**
  ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md) decisions 2, 3 and
  7, `_status_grid.html`). A pinned card states its pin as the block described below,
  the first thing in the card's body — *In maintenance by lex until … · 1d 23h left*,
  the card's head naming the node — and a box inside a card states its own the same
  way, in the wall's lighter form ([ADR-0135](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  decisions 3 and 4, `wall` in `_rule_block.html`): its note waits behind a mark of its
  own, a speech bubble, which opens it in a card in the inspection card's look and
  place — on a click, a tap, Enter or Space, and on a pause where the look
  `inspection_card` opens cards on one — naming the node, saying the block's sentence,
  the note whole and who set it and when, with a link to the node's page and no
  buttons (`static/js/note-card.js`; the card, `#note-card`, stands outside
  `#status-grid`, and each note rides in its block in a `template.rule-note-src`, so
  nothing is fetched to open it and a refresh finds the card's block again by its
  pin's key). Without script the mark is a link to the node's page. An admin's *Edit*
  is a pencil after it, shown while the card is hovered or the keyboard is on it, and
  *Clear* stands in its editor, in words beside *Save changes* and *Cancel*. Every
  block's edge is dashed and only a rule that paints its node fills it (decision 5).
  Every open head of a node with no pin of its own — a
  card's and a nested box's — ends its icons, for an admin, in ‖
  (`a[data-control="pin"]`, ADR-0127 decision 3): a link to the node's page without
  script, and with it the control that clones the page's **one editor** of a pin
  still to be set — `template#pin-editor`, drawn outside `#status-grid`, so no
  fragment carries an editor where one in every head would weigh a megabyte in an
  admin's swap — into the node's box, where the pin's block will stand: a card's
  panel, a box after its head's row. `tree.js` fills in the node's path and the
  sentence that names what the pin covers — *hemulen and everything beneath it*,
  from `data-beneath` on ‖, which the server reads off the unfiltered snapshot, so a
  node whose children *hide ok* dropped says the same — and opens it; the clone is
  the disclosure every editor is, so the poll waits for it (below) and Cancel or
  Escape close it, which takes the clone away and gives ‖ the focus back. A
  **node's page**, a branch's or a leaf's, is framed, and the frame's head
  (`frame_head` in `_node_head.html`, one macro for both pages) is drawn on every
  node's page for every reader: the node's row as its box draws it, then the check's
  description, the node's pin and the pins above it as the rows heading the frame,
  the node's own lines and the damping counter in words. An admin sets the node's pin
  from there with the row's ‖, a button that opens the editor the head keeps beneath
  its row — without script that editor's own *Set maintenance*, the browser's
  disclosure. **The head lists the node's own lines** — in full rather than
  clamped to `reason_cap`, each with its record, the pause mark at its end and a
  pinned line's block beneath it — and so does a branch's one card at depth 0, from the
  block the two share (`_own_lines.html`,
  [ADR-0036](adr/0036-addressable-reasons.md) decision 12): a line of
  a node above others is put in maintenance there, without the node's pin that holds
  everything beneath it. Any line takes a pin, whatever it says, and the editor of
  the last of its lines still alarming says that the nodes beneath it still count
  (ADR-0124). Where a line's grading named its form
  ([ADR-0126](adr/0126-a-line-is-a-template-over-its-record.md)), the form stands
  beside it, above its record: the key a check's `display:` block re-words it under.
  There a line's record takes the line's ink rather than Bootstrap's
  muted one, since a status fill can be vivid. The kiosk layout and a viewer get the
  block without buttons, no ‖ and no editor. The overview's own card sets no pin —
  pinning everything stays a curl, not a click — though a pin that stands there is
  stated and changed like any other. A write from a card or from a head comes back
  to the page as it was asked for, its filters and its depth: the form's `next` is
  the page's own address, without the `fragment` the poll adds — and a line's, at the line
  (`at_line`: `?reason=<slug>#pinned-reason`, in place of any line the page was
  asked at).
  Who pinned a pin and who changed it last stand in the block's editor, and on
  *Handled* for everyone; the strip's popover, with room for one name, shows the last
  writer.
  **The poll waits for an open editor.** These editors stand inside what the ~10s
  poll swaps, so while a disclosure around a `form.maintenance-editor-form` is open
  in its container `poll.js` neither fetches nor swaps, and an answer that was on its
  way is dropped whole. The stamp says *updated … — paused while editing* at once,
  and after a minute everything but the card or the head that holds the editor dims
  (`.poll-waiting`), as a page that lost its server does. When the editor closes the
  stamp drops the words and the ticks go on, the next at most ten seconds away; a
  page that had dimmed is polled at once. A close does not poll by itself, because a
  swap takes the keyboard's focus with it and Cancel has just put that back on what
  opened the editor.
  A **node's own page states a pin as one block where it acts** — a leaf's, below,
  and a branch's head, above
  ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md), `_rule_block.html`):
  the node's at the head of the page's frame, which is the border that runs round every
  line the pin covers, and a line's beneath its line — *also in maintenance on its own*
  under the node's pin, because it stays quiet when that pin ends. A **pin set on a
  node above** holds this one in maintenance with everything beneath that node, and the
  page states it where it acts too: the same block without buttons, one row of the
  frame's list for each pin above, outermost first, its sentence naming and linking
  the node the pin stands on — *This node is in maintenance from /nexus/qnap* — and
  the node's own pin and a line's under one say *also in maintenance on its own*
  (`_pins_above` in `app.py`); the words are maintenance's own, *silenced* being left to
  the kind that holds a flapping thing ([ADR-0135](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md) decision 2). The block
  says who put it in maintenance, until when and what is left — *until 2026-10-03
  20:44:28 · 1d 23h left* — and its note in full; an admin's carries *Edit* and
  *Clear*, and a viewer reads the same block without them. The boxes a node's page
  shows beneath it are a wall of their own, and their blocks the wall's. A pin is
  **set where its block will stand**: *Set maintenance* is ‖ in the head's row, and
  each member line ends in a pause mark, on a seat
  in the rail its other actions share. Each opens its editor in place — a line's
  beneath its line, in the flow — and the editor's first sentence says what the pin
  covers: *all 6 lines and any that appear*, or *this line only, the other 5 keep
  alarming*. *Edit* opens in the block and turns the note into its Markdown source,
  with who pinned it at the top. Every editor is the browser's own disclosure and works
  without script; `static/js/maintenance-edit.js` adds Cancel and Escape, starts an
  opened editor at the end of its note, and selects an expiry that is still as it was
  filled when its field takes focus. A write **comes back to where its block stands**:
  the node's own pin to the top of the page, and a line's set, edit and clear to the
  line, by the address that names one (`?reason=<slug>#pinned-reason`), so that on a
  node of 150 lines the block just written is the one in view. The block's **kind is
  data** — `data-rule`, of which
  maintenance is the first — and the head of a node's frame is a list, so a second
  rule on a node is a second row there. Every block's edge is dashed — 1.5 pixels of its
  ink at 65 %, nothing else on the page having a dashed edge — and only a rule that
  paints its node fills its block, maintenance's with its own tint, the node's color
  running through any other; the frame is a border, so both stand on a status surface
  of any color (ADR-0135 decision 5).
  ***Handled* is the same blocks** (`maintenance.html`, decision 6 of that record, at
  `/handled` since ADR-0135 decision 8, its rail entry the ringed diamond): its sections
  the jobs, today *In maintenance* alone, and in it every pin in the tree,
  grouped under its node's path, the node whose pins have stood longest first
  (`_oldest_first`) — the path a link to the node, its title beside it — with the
  node's own pin first, as *The whole node*, and then its lines' in the check's order,
  each opening with the line it holds and a link to that line on its node's page. A
  count above them says how many pins stand on how many nodes. `GET /maintenance`
  answers with `/handled` and its query, so that a bookmark and a way back drawn before
  hold. Each block carries the pin's whole record — *pinned by Anna …,
  last changed by Ben …* — beneath its note, for everyone; a node's own page keeps
  that in the editor, and here an open editor stands in for it. An admin changes a pin
  there with the same *Edit* in the block and the same *Clear*, each named for its node
  (*Edit this line's maintenance, /ci/actions*) and described by the block's sentence,
  since a page of many blocks is a page of many *Edit*s. A save or a clear comes back
  to the page with its node named in the query, `?node=<path>#pinned-node`: that
  node's section alone takes the id and a ring, and the page scrolls to it. The node
  travels in the query and not in the fragment because a refused write is answered at
  `/pins/maintenance` itself, and a link from there that differed only by its fragment
  would load nothing. The page is not polled, so an open editor has nothing to wait
  for.
  **A node that is not reported has its section too** (`pin-node--suspended`, ADR-0109
  decision 4): its path plain, a sentence in the muted ink saying that its pins hold
  nothing until it returns, and its blocks opening *The whole node, when it is
  reported,* or *One of its lines, when it is reported,* — a line's naming no line, and
  never its slug.
  **An edit shows the expiry it keeps.** Every editor of a pin — on a node's page,
  on *Handled*, in a card and in a branch's head — fills the **Duration or
  expiry** field with the
  stored expiry, a date and time in the configured timezone, and its form carries what
  the field was filled with. A field that still reads that keeps the stored instant
  exactly: it is not read again, so neither the interval floor nor the hour a clock
  change repeats can refuse an edit that left the window alone. Emptied, it means the
  configured default from now, as on a new pin, whose field is empty; anything else is
  read as it is typed. A save that changes neither the note nor the expiry writes
  nothing, so *Save changes* on an editor nobody typed in leaves the pin its last
  author's and another open editor of it good. The field accepts the route's
  duration, ISO and next-occurrence shortcuts; each shared editor states the
  configured timezone and exposes the complete grammar in a closed, native *Which
  formats can I use?* disclosure.
  How each node **first looks** is the deployment's
  ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)): the route works it
  out once per render (`first_look.draw`, from the resolver the start builds,
  `app.first_looks`) and hands it to the template and the planner. The cards start
  open — the wall's root and a page's node take no `chips` — and beneath them a node
  starts closed where its parent's `chips` says so and it claims no
  `show_when_quiet`, open where it says otherwise — beneath a mount two checks share,
  where the check that writes it says so (`FirstLooks.children_chips`) — and closed at
  a `depth=` level;
  where nobody spoke, the built-in look draws it open, its healthy shown, unless its
  level is **big**: one that, opened, would draw more than `first_look.BIG_LEVEL`
  boxes (thirty), counted all the way down with each level beneath deciding first
  (`_drawn_beneath`), starts as chips, as `chips: true` would start it — the net for a
  level nobody expected to be big, a run that suddenly names a great many children. It
  reads the tree's shape and what is said, never a status, so it is priced and moves
  no card ([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)), and every statement
  wins over it. Then the **failure budget** opens, in each card — on a
  node's page, each of its children — unless the browser's look `failures` is
  `chips` (§5.3, `_failures_open()`), the first three failures the first look hides
  under a chip, each a node that fails for itself and that no damping counter holds
  back (`tree.own_failure`), errors before warnings in the card's order, with every
  node on their path, marked `data-budget`; the others stay red chips with their
  counts. `fold_ok` folds a node's healthy children and lines from the first paint:
  the server marks them `data-fold-drawn` and writes *✓ +N ok* as `tree.js` will, the
  stylesheet folds them under `ls-script` until `tree.js` has applied the tab's map
  and put `ls-tree-ready` on `<html>`, and without script nothing is folded. Each box
  clamps its lines at its own `reason_cap`. Both faces of every node
  are in the fragment: one `.tree-node[data-node]` holds the chip, `a.tree-chip` to
  the node's page with its cue, name and counts, and the box inside a bare
  `.tree-hold`, drawn `hidden="until-found"` while the node is closed, so a click
  opens it without a request and the browser's find reaches a name or a line beneath
  a chip (the stylesheet gives the wrapper its `display` back against Bootstrap's
  `[hidden]`; an open node's chip is plain `hidden`). A level keeps its declared
  order: consecutive closed children stand in a `.tree-run` that spans the row, an
  open child in its place between runs, and `tree.js` re-forms the level by
  `data-order` as a click opens or closes a node; a level stands 6 pixels below the
  lines of the node it belongs to, a card's as a box's. **A run lines up in columns**
  under the look `chip_runs: aligned` (§5.3, decision 12): a level's runs share one
  column width, `--chip-w` on its `.tree-kids` — the server's estimate
  (`app._chip_room`: the characters of the widest name of the level's children, open
  or closed, at most `CHIP_NAME_BOUND` times their 90th percentile, and of the
  largest count of leaves among its branches, `_leaves_map` on the unfiltered
  snapshot, each at the theme's `--ls-chip-letter` of the chip's `0` — 0.85 in the
  system's faces, a whole one in cyberpunk's monospace — and the chip's padding,
  border, cue and, where the level counts, the counts' margin at their size,
  `dashboard_layout.chip_estimate`, such as
  `calc(9 * var(--ls-chip-letter) * 1ch + 20px + 1.65em)`), which the run's font,
  the chip's, resolves, within a few pixels of what the script measures — and
  `data-leaves`, that count. The planner counts the same characters in the face the
  browser's theme draws them in (`dashboard_layout.chip_face`, a `0` of 0.55 em in
  the system's faces and 0.6 em in cyberpunk's). `tree.js` measures the names in the chip's own font with a canvas, takes the
  same bound, adds the chip's edge, padding and cue and the counts' margin and widest
  digits, and sets the width in pixels; it keeps a level's width by what it measured
  it from, so a click, a status and a refresh leave it alone and only another set of
  children, the fonts settling or the root's font size measure again. The run is a
  flex row and the container its chips ask, in their font: its line height is one
  column and the chips' gap, which no text of it is set by, so container queries on
  its own width — one for each count of columns from two up to `MAX_LAYOUT_TRACKS` —
  stand its chips in as many columns of that width as fit, each stretched to its
  column, a last line's too, as a grid's tracks hold them; a chip is stretched to its
  row, its name breaking where its words meet (`<wbr>`, `breakable`) and then
  anywhere, its counts floated right — beside the name's last line where they fit,
  beneath it where they do not, as a mixed chip's glyphs and a leaf's total past its
  column's room do. Where its level has room for one column only, the run **wraps as
  it comes**: each chip at its own width, drawn as a column's chip is, sharing
  lines. The column decides as the browser draws it,
  the estimate before the script and the measured width after, so a run near the line
  changes when the script measures its level, as its columns do. Under
  `chip_runs: wrapped` the server sizes nothing and a run is the chips inline, each at
  its own width. A chip's **counts** are what the
  node contributes (`tree.py`'s `chip_counts`, on the snapshot before the filters
  drop nodes): each leaf beneath by what it counts for itself — a stale leaf as warn,
  a pinned one as maintenance, an idle one as idle — and each branch that fails for
  itself, the chip's own node among them, by `own_counted`; one total where they
  share a state, each state's glyph and count where they mix, none on a leaf of one
  line; beside them a ringed diamond and the number of parts beneath that a rule
  handles and the counts do not show as such — a pinned branch, the chip's own node
  among them, and a line's pin where its node is not ‖ among the counts
  (`handled_beneath`, ADR-0135 decision 6); the words ride on the chip as its `title`
  and accessible name, *1 ok, 1 handled: 1 line in maintenance*. A failing chip is
  vivid, and so is a card closed while it fails. The **head's icons** (`.node-icons`, decision 3; none on the kiosk): ↗ to the
  node's page, the healthy fold's **funnel** where the node has a healthy child or
  line — healthy being `OK` with nothing stale beneath and no pin on or beneath,
  `tree.py`'s `healthy` and `line_healthy`, marked `data-healthy` on nodes and lines;
  a node that claims `show_when_quiet` (`data-swq`) and its quiet lines fold only
  under a press, which the two counts on the button, `data-n` and `data-n-pressed`,
  say — ▤ where it has children, `aria-pressed` `true` while all are closed,
  `false` while all are open and `mixed` between — and, last, an admin's ‖ where the
  node has no pin of its own (above). The icons' shapes and the status
  cues' are drawn once per page as sprites (`_rule_block.html`'s `icon_sprite`,
  `_status_cue.html`'s `cue_sprite`), so a fragment carries references, not paths.
  **A node may decline the chips** ([ADR-0063](adr/0063-declining-the-density-trade.md)):
  one carrying `show_when_quiet` starts open whatever its level starts as, and counts
  as the box it draws, so an inventory aspect keeps its list at a glance instead of
  showing it only while a sibling is red; the claim is per node and does not cascade, a fact about the
  node's content, so *hide idle* / *hide ok* still answer to the person at the screen,
  and a viewer's ▤ or funnel is their word over it. Card heights are **bounded**: the reason caps from
  above, a `min-height` floor from below. When a responsive row has **spare
  ordinary-width tracks**, roots spend only widths their tree can use. The server
  builds a stable flow profile from the filtered, depth-limited topology as the first
  look draws it by its configuration (`dashboard_layout.Priced`, ADR-0128 decision 6):
  every open node is a potential reason host and scales by `ceil(reason_cap / default
  budget)` at its own `reason_cap`; a closed node is a chip in its level's run, each
  run a heading row for each line of chips at the level's width — the level's
  `--chip-w` estimate in tenths of a pixel (`dashboard_layout.chip_width`, a `0` of
  the chip's font taken at about 0.55 em), for as many columns as fit, and where the
  level has room for one column only each chip at its own width (`app._chip_own`: its
  name, a branch's digits and the chip's chrome, estimated alike), as many to a line
  as fit with their gaps — with nothing beneath a chip priced; and a closed card is
  one row. The width model
  follows the stylesheet's 330 px nested tracks, gaps and per-level insets and the
  chips' column gap — six constants a structural test pins to `overview.css`, with the
  chip's padding, border, cue, counts' margin and font the estimate takes — and a
  level's boxes beside a run keep every track that fits, as the browser lays them out:
  the run spans them all, so none is empty for auto-fit to drop. It never reads
  current status, reason count/text, measured height or chip/box painting — not what
  the failure budget opens, so no status moves a card. Every span is priced at
  the width it actually has at a given grid width, not at the track minimum, and a
  span is useful only when it removes at least one modeled row per added outer
  track — so a profile can skip a span that opens no nested column, and a linear
  chain has no wider step. Within each source-order row the currently tallest root
  with a fitting step wins (a row is as tall as its tallest card; height ties fall
  to the better reduction per track); an unusable spare remains empty.
  The fragment carries only `(tenths, tracks, plan)` breakpoints where the band
  changes — the smallest grid width **in integer tenths of a pixel** at which the
  band applies, the model's own unit, so a band is never late against a browser
  that measures fractionally; `static/js/dashboard-layout.js` measures the grid's
  width, compares it scaled by ten, sets the named track count explicitly and
  selects the latest applicable band after first
  paint, resize and each poll swap — at once when `tree.js` asks before it reads the
  cards' rows (`window.lsLayout.apply()`), and a frame that finds the band's plan on
  the grid already writes nothing — an explicit count is what stops the width
  where auto-fill adds a track (and snaps every track to its 330 px minimum) from
  painting a taller page out of a wider viewport. A candidate count may not
  stretch a track wider than auto-fill itself ever could (one track just short of
  a second fitting, ~676 px), which forbids the page-wide banner a single enormous
  card would otherwise win while keeping the moderate counts a dodge needs — and
  the count a band already holds is exempt, so a widening viewport can never
  disqualify the plan that is holding the page. An incumbent yields only to a
  strictly better challenger, all-ones plans ride auto-fill unchanged, and the
  finished layout is memoized on the depth-limited tree shape, each node's cost and
  which children the first look closes among it. Choosing the best
  legal outer count is not the same as never growing taller: a card's own nested
  auto-fit can re-chunk at a column flip that no outer choice can dodge, which is
  the documented limit of the outer planner rather than a defect. `settings.yaml`
  `dashboard_columns: plain` withholds the plan, leaving the plain auto-fill grid. A wider card grids a branch containing at least two direct open
  nodes. Consecutive closed children share a full-row `tree-run`, in the level's columns
  or inline as the look says, while open nodes at the same mixed level can grid; a
  single-child wrapper and every node/reason box remain intact. The original
  auto-fill grid is the no-JavaScript fallback, and a narrow viewport resolves to one
  track without horizontal overflow ([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)).
  Under the look `boxes: packed`
  ([ADR-0138](adr/0138-a-viewer-may-pack-a-levels-boxes.md)) the server prices the plan
  as the page will be packed — `dashboard_layout(…, packed=True)`, which the template
  passes by the look in force: every level of a card priced packed, and at each count
  of tracks the spans that pack the page shortest, the rows' own plan where that packs
  no taller, by the bands, floor and held count above — and `dashboard-layout.js`
  stands every grid of open boxes — the cards, and a level of two or more open boxes in
  a card — in columns rather than rows: the grid keeps the plan's tracks and each card's
  span, a level of a card lays equal columns of its own, as many as fit and its boxes
  and runs fill, every box stands in its first row with a top margin as deep as the
  boxes above it in its column, so the row is as tall as the tallest column
  (`.is-packed`), and each box in the page's order goes beneath the shortest column, or
  run of columns for a span — the leftmost within 32 pixels, an empty column of the
  first row before any, a run of chips in one column as a box, a card's own levels
  before the card. It holds each level's columns, and by a node's path the column the
  node stands in as a box or as a chip, while the page is open: a load packs anew once
  `tree.js` has put the tab's map back (`window.lsLayout.draw()`), and so does a level
  whose columns a width changes; a refresh, a click and a box's growth, which a
  `ResizeObserver` on each box's border box reports before the frame is painted — the
  plan a new width selects laid first — restack the columns and move no box sideways:
  a box a click closes leaves its chip where it stood, a chip it opens stands its box
  where the chip stood, a run stands where the first of its nodes stood, and a column a
  click empties stays, empty, until the page is drawn again. `tree.js` has the boxes
  packed before it puts the window back or scrolls a box into view. Until a load is
  drawn `#status-grid` is hidden — `tree.js` puts `ls-boxes-drawn` on `<html>`, and
  `tree-pending.js`'s one-second timer puts it there whatever happens — so the first
  paint never stands the boxes in rows for the packing to move. The page's order is
  untouched, and a level of one column is drawn as rows. The engine's own
  **heartbeat** (`/little-sister`,
  ADR-0005) — a branch with a child per contributor
  ([ADR-0076](adr/0076-the-instance-node-is-a-branch.md)) — is lifted out of the
  grid with its children into a compact **status-strip pill** at the top
  (fit-content — a side note under the "updated …" line, not a page-wide
  banner) that wears the branch's roll-up and links to `/status/little-sister`,
  where the children are the page; it renders inside the polled fragment, so it
  refreshes with the grid and dims with it under a sustained outage — and a stalled
  scheduler shows it **vivid** (its self-alarm), not dimmed; the engine seeds a
  default `about` so the pill's hover card explains the heartbeat out of the
  box, and a `nodes.yaml` title/about overrides it like any node's. The grid
  is the
  `_status_grid.html` partial; the page **polls** it (`?fragment=1`) every ~10s
  via the shared `static/js/poll.js` (the script tag's `data-target` names the
  container to swap), flags refresh failures (so it never silently shows old
  content), and waits while an editor of a pin is open in what it would swap
  (ADR-0104 decision 7, above); the
  poll stamp (`#status-updated`) shows the **server-formatted** render time — in
  `settings.yaml`'s timezone and `time_format` (ADR-0120), not the browser clock —
  **seeded into the page itself** at render (a `data-rendered-at` attribute; page
  JavaScript cannot read navigation-response headers), then refreshed from the
  fragment's `X-Rendered-At` header on each swap. So even a page whose polls all
  fail dates its data ("could not refresh — last ok …") from first paint. A
  response **without** that header is not a fragment at all — the login redirect
  after a session expiry — and counts as a failed poll, so the grid is never
  overwritten with a login form; and a fragment is a fragment whatever the node has
  become, so a branch's page whose children a run stopped naming is answered with the
  grid for a node without any, not with the leaf's page. A **sustained** outage escalates (ADR-0005):
  after six consecutive misses the line grows a legible age, a
  banner rises above the content, the frozen content dims (`.poll-stale`) and
  the tab title gains a "(stale) " prefix — one good poll resets everything;
  session expiry banners "reload to log in" instead of an age, and a
  `visibilitychange` re-poll lets a woken tab self-heal immediately.
- **Our own stylesheet and scripts are addressed by their content**
  ([ADR-0112](adr/0112-our-own-assets-carry-their-content-hash.md)) — every
  `url_for('static', …)` for a `.css` or `.js` file carries `?v=` and eight hex digits
  of the file's SHA-256 (`little_sister.assets`, added where the URL is built, so a
  template writes none by hand), and that URL is answered `immutable`; another hash is
  answered `no-cache`, and pictures keep their plain names. A page that polls states one
  digest of the whole set, the registered packages' assets among them, on the poll's
  script tag (`data-assets`), and every fragment states the server's in `X-Assets`:
  where they differ `poll.js` reloads the page instead of swapping the answer in — after
  an open editor closes, and once for a digest, which it keeps in the session's storage.
  So a wall display takes an upgrade by itself.
- **What is sent compressed** — a page, a fragment and a JSON envelope go gzipped
  where the request takes gzip, which every browser's and `requests`' does
  (`_compressed_where_asked`, the last of the application's `after_request` hooks,
  so the body every other hook saw is the one compressed and the headers they set
  stand): the tree puts both faces of every node in the fragment, and what rides
  every ten seconds to every open tab is sent at a twentieth of its weight — a
  deployment's recorded wall 26 KB for 574 KB, in 4 ms at gzip's own level beside a
  render of 100 ms. Nothing under a kilobyte, no answer but a 200, nothing already
  encoded, and never a static file, which the browser keeps by its hash and
  `send_file` streams. Every answer of these kinds carries `Vary: Accept-Encoding`,
  compressed or not, so a cache between here and a browser never hands one to a
  browser that did not ask. The compression-oracle attacks on TLS need a secret in
  the body beside text an attacker can place there, and a page here carries none —
  the session rides in its cookie, and a pin's compare-and-set token is the pin's
  own time. `tests/test_wall_cost.py` holds the fragments' weight on the wire beside
  the bytes rendered.
- **The tab's map** ([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  decisions 9 and 10) — what a viewer opened on the wall stands through every refresh
  and a reload of the tab: one script, `static/js/tree.js`, owns one `sessionStorage`
  key, `ls-wall-map`, `{v, mode, nodes}` — `mode` the band's button in force
  (`null` for *As configured*, `closed`, `open`) and `nodes` a map by node path of
  what differs from how the view draws the node on its own: `open`, and beside a
  close `ok_since` and `ok_held`, the server's time (`data-rendered-s` on the
  grid, whole seconds) of the first render since the close that drew the node out of
  failure and whether a render six hundred seconds or more after it still did, after
  which the node's next failure opens it again (decision 9: a close holds for its
  incident, a shorter recovery is a flicker and the count starts again, a tab that
  saw no render out of failure keeps the close; an open never gives way to a status);
  `chips`, its ▤; `ok`, its healthy fold — an entry wherever a press folds more than
  the configuration, a claim beneath or on the node; and `lines`, a box's reason lines
  shown in full (by the block's `data-reason-node`) — a `more` entry, a level's
  *+N more* until the built-in look became ADR-0128's, is read by nothing. How a node
  looks is worked out from the server's markers and the map alone, in this order —
  its own `open` entry; under *Close all* an open entry beneath it, which keeps it
  open; in the configured look its claim, `data-swq`; its parent's ▤, the parent's
  `chips` entry, the mode, the page's rule for a page's own children, what the server
  drew (`data-state`) — and the rule that decided is written on the node as
  `data-why`. A page's own node is its frame (`data-page-root`), always open
  (`data-why` `page`), whatever its entry says, and a click on its head's row toggles
  nothing; its ▤ and its funnel set its entries as its box's do on the wall, so the
  wall follows, and a leaf's page, which has no grid, gives the script its
  `.node-page` instead. A click on a chip, on a head's
  name or anywhere on an open node's head row but its icons and actions toggles the
  node in place (Enter and Space on the chip and the name, which the script makes
  disclosure buttons; a click with a modifier, a middle click and a drag that
  selected the head's text keep the link); the focus moves to the other face's
  toggle, and a box opened below the fold is brought into view as far as it must.
  ▤ sets every child — the children's entries go, and one whose own look would not
  follow gets one of its own, as on a fold does every failing child (`data-failing`),
  which another of the tab's views may open by its own failure budget — and the
  funnel folds the healthy (`data-healthy` children and lines set `hidden`, *✓ +N ok*
  after the rest, `button.tree-ok`); a button set differently from the view's own
  drawing carries `.is-changed`. The band's three buttons set the `mode`: *Close all*
  keeps every `open: true` entry and drops the rest, *Open all* drops every `open`,
  `chips` and `ok` entry, *As configured* empties the map and loads the address
  without a `depth=`; the one in force is pressed and carries the count of the nodes
  the map holds, one more for a `depth=`, and a click on it drops what it counts. A
  **find** reaches what is beneath a chip: the browser fires `beforematch` at each
  closed `.tree-hold` above its match, the innermost first, and the script opens each
  as a click would, writing its entry and re-forming its level around the node and
  never the node itself (a node taken out of the DOM collapses the find's range; its
  run's wrapper stays and becomes `.tree-solo`, drawn without a box of its own) —
  and leaves the wrapper's `hidden` to the browser, which reveals no ancestor above
  a wrapper a script unhid during the event. The reveal is
  provisional for two seconds: a later reveal elsewhere within them closes what the
  earlier opened but the nodes above the new match, entries put back; a click or a
  key anywhere keeps it. It is read once on a load and written on every change;
  storage that is missing or refused leaves it in memory for the page's life.
  `poll.js` brackets each swap with the script's `before` and `apply`: the map goes
  back on the new markup before anything paints — the lines' overflow measured in
  one pass for every shown block, one layout for the wall — the keyboard's focus
  returns to the same control of the same node — every control carries
  `data-control`, a chip its node's toggle, and its `[data-path]` names the node —
  without scrolling, the window scrolls by
  what the node nearest its top moved, once the new markup is laid out, so that it
  shows what it showed (a window at the page's top stays there), and the open
  inspection card finds its node's new element by path (`inspect.js`); the scroll of
  a table or a curve is put back after that, since a box the map opens has no layout
  before. On a load `static/js/tree-pending.js`, linked first in the head without
  `defer`, puts `ls-script` on `<html>`, under which the band's three buttons and, on a
  node's page, the head's ‖ in the place of *Set maintenance* stand from the first
  paint as `tree.js` will draw them, so neither moves the page when it runs — a page
  without script has neither, its setter beneath the head — and puts `ls-tree-pending`
  on `<html>` while the map holds anything, under which the stylesheet hides
  `#status-grid`, or a leaf's `.node-page`, with `visibility: hidden` until the map is
  applied, so the first look never flashes under a viewer's folds; an external file
  rather than a second inline script, since the policy names one by its hash (§5.3). A
  new tab starts as configured, nothing is written to a cookie, and the system page,
  which has no map, is left alone. On the kiosk the map lives in memory and never in
  storage: five minutes after the last pointer, touch, key or wheel it is emptied and
  applied again, which brings the first look back with a bookmark's `depth=`; a tap
  toggles a node there as anywhere, and its heads carry no icons. On touch a tap
  toggles and the inspection card is not offered (`inspect.js` ignores the focus a tap
  gives a link, and the compatibility `mousemove` a tap sends comes once the touch is
  lifted, just after a click, when a movement starts no pause). The editor the refresh
  waits for is named by its own disclosure,
  `details.maintenance-editor-disclosure[open]` or a line's `details.reason-pin[open]`,
  in `poll.js`, `inspect.js`, `maintenance-edit.js` and the stylesheet's
  `.poll-waiting` rules, so nothing else the grid may hold matches it.
- **Inspection popover** ([ADR-0019](adr/0019-inspection-popover.md)) — a custom **hover
  card** for a node, not the native `title=` tooltip: its name and `title` as the
  node's own head draws them — every node's box carries its head, open or closed —
  then the first block of its `about` (rendered Markdown) and, where more follows, a
  line to its page that counts the blocks after it — or, where it has no `about`, its
  `description`, its first block as its *About* card renders it
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 2) — and a node with neither a title, an `about` nor a `description` has no
  card. The map of what each says and that count (`#node-meta`, a
  `script[type=application/json]` built by `_node_meta_map` with `render.first_block`)
  rides in the grid's fragment (`_status_grid.html`) and is read again after every
  swap, so a node a run names after the load has its card and a changed text is
  current. `static/js/inspect.js` binds once via event delegation on `#status-grid`
  (surviving the swaps) and renders + positions the card with **Floating UI** (CDN).
  It opens on a node's **name** alone — a chip, the name in an open node's head, the
  status strip's name — once the pointer has rested there about two thirds of a
  second (`REST_MS`, every movement starting the pause again, but for one while a
  click is under way or for `AFTER_CLICK_MS` after it, the hand that clicked still on
  the name it toggled), on the name a refresh drew again where one came during the
  pause; keyboard focus on a name opens it at once;
  it stays open while the pointer moves into it and closes on leave / blur / Escape;
  a refresh keeps it on its node, found again by path and kind. A node's page's own
  head has none — its *About* card stands on the page — and under the look
  `inspection_card: off` (§5.3) the script binds nothing. `markTriggers` marks the
  names that have a card with `inspect-trigger`, which the help cursor reads. The node
  stays a link to its detail page. Nothing else in a row raises a card, being no name
  — a pin's own controls (the pip, a line's pause mark, a head's ‖, the block, its note
  mark and its pencil, and an editor), the action chips that stand in it, the head's
  toolbar, its actions, ⋯ and
  its menu, and *⌄ all N* beneath the lines — so a tap on a chip is the tap on its
  link, on the first try. Nor does a name raise a card while an editor of its node's
  pin is open (`EDITOR`, the shape `poll.js` waits for): what opened the editor has
  given way to it, and the pointer is left on the row
  ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md) decision 3).
- **Coded reason lines** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) —
  a line whose entry declares its own code carries a per-line state class and a
  small **labeled** shape cue (a line has no status word, so the cue is its
  accessible name — the `_status_cue.html` partial both surfaces import); every
  coded line paints its state's **own tint pair** at full opacity, ok included
  (the pinned line's lesson: ink on whatever surface a line lands on is how a
  2.7:1 ships — and a mixed list sits on a *vivid* fill, where a surfaceless
  passed line would read as part of the problem; green under red is the point).
  The pale ok tint is itself the quiet treatment, and an all-healthy node
  collapses to a chip on the grid anyway. `is-running` renders work-in-flight as
  an italic; the words still say it. A **quiet** (pinned) line keeps the
  maintenance tint whatever its code, with only the cue saying what state is
  held; `test_contrast.py` measures all four line pairs and the full-opacity
  reset.
- **Reason overflow** — a card clamps its reasons to a **line budget**
  (`settings.yaml`'s `reason_cap`, default 6, carried as the block's `--reason-lines`):
  short reasons show that many, a reason that wraps to several lines uses more of the
  budget, so an erupting node cannot outgrow the grid. Within the budget a block shows
  its **failing lines first** — errors, then warnings, then the rest, each group in the
  check's order, a pinned line among the rest whatever its code
  ([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  decision 6) — so what the clamp cuts is healthy lines, and the reason for a box's
  color needs no click. The order is the server's
  (`tree.failing_first`, the template filter of the same name), so it stands through
  every swap; it holds wherever a `reason_block` is clamped, a card's and a box's on
  the wall and the cards of a node's page alike, and a node's own lines on its page
  (`_own_lines.html`), which nothing clamps, keep the check's order, as the Copy
  documents do. Every reason is server-rendered
  into the DOM and the surplus is clipped **by CSS, never mid-HTML**, so a reason's
  safe Markup ([ADR-0018](adr/0018-markdown-rendering.md)) is never cut, then faded at
  the edge. One **⌄ all N** beneath the lines (`button.reason-more`, ADR-0127
  decision 3), N the block's total, reveals the rest in place and reads *⌃ less* until
  it folds them back: the server draws it, hidden, where the lines are more than the
  budget, `tree.js` makes one where a shorter block wraps past the clamp, and it is
  shown while the block is clipped or open — the head carries no chevron and no empty
  seat for one. The lines it opens stand no taller than about half a window, or the
  budget where a deployment's is taller (`max()` of the two), and scroll inside the
  box beyond it; while they scroll, `tree.js` gives the block `role="region"`,
  `tabindex="0"` and *All N lines of* its node for a name, keeps where it stood by the
  node's path for the tab's life and puts it back after each swap, and *⌃ less*
  returns it to its first line (ADR-0127 decision 3). Like the popover it
  binds once via event delegation on `#status-grid`, and what it opened is an entry of
  the tab's map (below), so an expanded card survives the ~10s fragment swap and a
  reload. A node's own page always renders every reason of its own
  (`_own_lines.html`): a leaf's detail page (`check.html`), and a branch's head and
  its card at depth 0. The JSON envelope
  ([ADR-0080](adr/0080-the-envelope-is-the-snapshot-published.md)) is
  untouched.
- `check.html` — a leaf check's detail page (its `title` following the breadcrumb in
  the header ([ADR-0017](adr/0017-node-title.md)); its `about`
  ([ADR-0012](adr/0012-node-metadata.md)) stands in its *About* card, on its Status
  view alone
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 1)), framed as a branch's page is
  ([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  decision 8): the frame's head (`frame_head`, `_node_head.html`) — the leaf's row as
  its box draws it, its `description`, and the node's maintenance where it acts
  ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md)): the pin's block
  and the pins above as the rows heading the frame, and on a node whose reasons are
  members ([ADR-0036](adr/0036-addressable-reasons.md)) a block beneath each pinned
  line — a pinned line stays visible in the maintenance tint, its block says who put
  it in maintenance and until when, and the node states how many of its reasons are
  quiet —
  with an admin's controls to set, edit and clear either; then its reasons in the
  check's order and the damping counter in words — and the **node-facts** block, last
  in the frame. The page is not polled; `tree.js` keeps the funnel's fold of its
  healthy lines in the tab's map, the entry the leaf's box carries on the wall.
- `_rule_block.html` — a rule's block
  ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md)): `pin_block` states
  a pin — the node's or a line's — with its editor and its *Clear*, or, given the node
  a pin above stands on (`source`), without them and naming it; `pins_above_stated`
  states each pin above a node that way; `pin_new` is the
  editor of a pin still to be set, and `rule_mark` draws the kind's mark. `instant`
  writes an instant of the block with each of its words whole — the date, the time of
  day — so a sentence that wraps in a narrow card ends no line inside one. A page that
  states a block away from what it holds passes `pin_block` the rest: the words its
  sentence opens with, whether the pin's record (`pin_record`) stands beneath the
  note, the address a write returns to, and the node its controls are named for —
  which is all *Handled* adds. The wall passes `wall`, its lighter form: `note_mark`
  and the note in a template for `note-card.js`, `pencil_mark` for *Edit*, and *Clear*
  in the editor. The two
  authored fields of every maintenance form are `_maintenance_fields.html`'s.
- `_node_facts.html` — the node's own facts, the **one** block both detail surfaces
  render ([ADR-0044](adr/0044-run-facts-on-the-node.md) decision 8): a **Time**
  card, a **Measured** card where the run kept a record
  ([ADR-0085](adr/0085-a-measure-is-read-out-of-a-record.md); its list is §4.5's), a
  **Series** card where curves stand on the node
  ([ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md), §4.11: the curves
  drawn there, from `_series.html`, and the way to the Series view and the History
  page), a
  **Report** card and a **Configuration** card, in that order — when it ran, what it
  read, what it has read over time, what it found, what it ran with, outputs before
  inputs because the outputs are why the page was opened. The report and the configuration go through the
  hardened Markdown renderer ([ADR-0018](adr/0018-markdown-rendering.md)), which
  `config` had been missing since before that renderer landed. The **Time** card
  never invents an instant
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)): it states the current
  status period — the **own**-status period, since that is what the event log bounds —
  as *Status error since …* and, on a line of its own, *Last observed …*, also where the
  two are one instant: the latest reading is no end, and *until* belongs to a period
  that has ended ([ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md)).
  **A node above others states first the period of what it shows**
  ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  decision 5), which the tree keeps beside its log: *Status error
  since 10:00*, so a branch that turned red from one node and stays red from another
  says the first one's instant (`_shows` in `app.py`, a `_Shows`). Where what it shows
  comes from beneath it, the line names the node beneath it that makes it so, with a
  link to its page, and that node's own *since* only where it began after the
  branch's: *Status error since 10:00, from staging/codepipeline/load-fixtures beneath
  it, error since 10:42, and 2 more*, and *Status error since 10:00, from load-fixtures
  beneath it* where one node made the whole period. The node named counts the code for
  itself — never a branch on the way down that only passes it on — and of several it
  is the one that has counted the code the longest; one that counts it only because
  its own reading went stale is *stale, last observed …*, and is weighed from when it
  went stale, its last observation and its tolerance after it (`_made_by`, a
  `_MadeBy`, from the same unfiltered node as the period). A status no one node makes,
  *ok* or *maintenance*, is *from the nodes beneath it*, and a well branch says
  *Status ok since …*, true now of everything beneath it. Beneath that line the
  period is named the own status's — *Its own status ok since …*, and its changes *of
  its own status* — because what such a node shows counts the nodes beneath it. Where
  the snapshot carries no `period`, which is not of what the node shows (decision 3),
  the line says the status without a *since*, and the node beneath with its own. What
  began the period is History's and the Copy document's to say. Its *and 2 more* links
  to the card that says why ([ADR-0135](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  decision 7; `_why` in `app.py`, a `_Why`), which stands right after Time wherever a
  branch shows an error or a warning, or ok and something beneath it is handled — not on
  a leaf, whose lines are its page, nor on a node in maintenance, whose block says why.
  Titled by its question — *Why error*, *Why warn*, *Why ok* — it lists what counts,
  each part beneath that fails for itself and passes the failure up through every node
  between, with the status it counts as and since when, errors first and the longest
  first, so what a pin, a shield or a damping counter holds back is not there; then,
  under ◇ and its total and the job's mark, every rule beneath it
  (`tree.rules_beneath`), a node's pin and a line's, with the node it stands on, what
  its part reads where that is a failure, who set it and until when, each linked to
  where it stands.
  A node in maintenance keeps *Status maintenance since …*, since that cancels what
  is beneath it
  ([ADR-0123](adr/0123-a-node-says-one-status-wherever-it-is-read.md) decision 3) —
  by a pin on it or its check's word; one whose lines are all in maintenance cancels
  nothing, and says *Its own status maintenance since …*
  ([ADR-0124](adr/0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)).
  When the period began is the tree's to say, which keeps it beside the log
  (ADR-0110 decision 5), so the card reads *since* that instant however far the log
  has moved on. Where the tree did not see the period begin it is stated *since
  before* a bound — a first reading, which found the node as it was, or a beginning
  lost before the tree kept it — taken once and kept until the node changes. An edit
  of a pin begins no period, so a pinned node holds *since* its set, and a period that
  a pin's end began says so: *since …, when its maintenance ended*, the instant the
  node began to show its status and not the one its check began to read it (decisions
  6 and 8). One that a line's pin began says which it was — *when a line's pin was
  set*, *when a line's maintenance ended* — read off the cause of the event that
  began it (`_began`; ADR-0107 decision 3). It falls back to
  a single *Observed …* where the node declares nothing above nodes that report (beneath
  that first line, since all it shows comes from beneath it), since a
  container's `UNDEFINED` is no status for a period to name, or where the tree keeps
  nothing of the node — decided once, where the routes take the period's start
  (`_since_of` in `app.py`, a `_Since`, which also says which status the period names
  and whether it is named the node's own), from the node before a filter takes its
  children, so the node's Copy document and History's row for the period that holds
  state the period its page does, in the same words — and says *Not yet observed* when
  no check has written it and nothing gives it a period: a pinned node that nothing has
  written has shown *maintenance* since its pin, and states that
  ([ADR-0115](adr/0115-a-copy-document-says-where-it-is-from-and-since-when.md)
  decision 6); it adds the **next update** and the run's **wall time** where
  the node carries run facts (this is where wall time surfaces at all), and the check
  frequency. A stale leaf says when it was last *observed*, not checked, since a node
  the instance re-asserts goes stale too. The next update stays **absolute** here as on
  the grid: one partial serves a page that polls and a page that does not, and a
  relative *in 4m* left frozen on an unpolled tab is the lie the absolute form was
  chosen to survive.
  **The branch page renders it too** — below the child grid (the head says what this
  node is, the grid what is under it, the details last, so a long report cannot push
  the dashboard off the screen) and **inside `#status-grid`**, because `report` is an
  output of the run and would otherwise be the one part of a polling page going
  quietly stale. It renders only where the node has something of its own to say — an
  observation, a report, a configuration or a period — so a container two checks
  share, its text and run facts withheld by §4.4's rule, shows its Time card alone,
  with the period of what it shows, wherever that period is of what it shows
  ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  decision 5), and none of it while it is not, after a restart
  until the units beneath it have run; pinned, its period is its pin's
  ([ADR-0115](adr/0115-a-copy-document-says-where-it-is-from-and-since-when.md)
  decision 6). The kiosk keeps none of it either. This is the container acquiring the
  detail page it never had, by reuse rather than as a second surface.
- `_series.html` — a series, as two macros the detail surfaces, the Series view and
  the History page import ([ADR-0092](adr/0092-a-check-declares-its-measures.md),
  §4.11): `curve`, which writes `curves.draw`'s geometry as SVG with no script — the
  value axis as hairlines and its words, the unit label once at its head where the
  values do not name it, the unbroken runs of line, the dots, a mark in the lane
  beneath the baseline for a reading that failed, the oldest and newest time, and a
  transparent strip per reading titled with its time and value, lit faintly under the
  pointer — with a caption that names the newest, the lowest and the highest value and
  counts the failed readings (its key the mark itself) and the holes; for a plot of
  runs (`curves.draw_runs`, ADR-0111) the stems of each verdict as one path in the
  line's place — no verdict, passed, warned, failed, the worse painted over the
  better — then the heads, a dot for a run that passed, the warning's triangle and a
  hollow ring in the failure ink, a hairline at the baseline where the plot has no
  value axis, and a caption (`runs_summary`) that counts the runs, names the three
  values under a measure and counts what did not pass, by kind, keyed by its mark; and
  `readings_table`, the readings newest first — the time on the series' clock with
  the code as a labeled cue beside it, a column per field through `record_fields`,
  the sentence as it stood — in `.ls-readings-box`, a named region in the tab order
  that scrolls both ways and holds the heading row and the Time column still
  ([ADR-0102](adr/0102-a-readings-table-keeps-time-and-names-in-view.md)). `_columns`
  heads a field its measures declare by label and unit over its name, expanded over
  the records as the curves are, and puts those first in their declared order; every
  other field follows by its name in the record's order, read from the oldest record
  on. Every ink is a token `test_contrast.py` measures on the card.
- `series.html` / `series_index.html` — the Series view and its index (§4.11,
  [ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md)): a card per node the
  curves stand on, as many to a row as fit a curve at the width it is drawn at, each
  headed by the node's status cue, its name opening its Status page and its sentence;
  the readings folded in a `<details>` per series beneath; a line per node none of
  whose series draws anything; and the index's table grouped under root nodes, each
  root's heading its own row, a count of curves a `<details>` holding their labels, and
  *curves* and *readings* a column each beneath one visually hidden heading
  ([ADR-0103](adr/0103-the-series-index-says-where-each-link-leads.md)). The index's
  table scrolls inside its card where the page is narrower, in a `.table-responsive`
  box that is `position-relative`: its visually hidden headings are absolutely placed,
  and a box that is not their containing block lets them widen the page. Neither is
  polled.
- `history.html` / `events.html` — the status-history and event-log tables, rows
  tinted by status (`row-*` classes in `overview.css`); the history takes the node's
  band and tabs, carries every reading of each check mounted on the node beneath its
  periods (§4.11), writes *current* in the *Until* of the period that still holds —
  its `until` is the latest reading, which the Status tab states as the last
  observation ([ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md)) —
  shows a pin as one maintenance row from its set to its end, whatever was edited in
  between, with the pin's note as it last stood and *before* its start where the set
  has left the log (decisions 6 and 7), and
  shows no row for the
  current period of a node that declares nothing above nodes that report — own code
  `UNDEFINED`, children present, the Time card's test — ending where it stopped
  declaring and saying so in a line
  ([ADR-0094](adr/0094-a-restart-is-no-transition.md)), in the table itself where no
  earlier period is left; says under the table of a node above others that its
  periods are those of its own status, since its page heads with what it rolls up to
  ([ADR-0123](adr/0123-a-node-says-one-status-wherever-it-is-read.md) decision 3);
  lists above that table the periods of what such a node shows
  ([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  decision 6) — *Status*, *Since*, *Until*, *From* and *What*, newest first: *From*
  the node whose change began the period, its path beneath the node, *itself*, or a
  dependency's full path where a shield did, linked to that node's History while the
  tree holds it, as the Events page links a node; *What* what moved it, *a reading*,
  *a pin set*, *a pin ended*, *a line's pin set*, *a line's pin ended*, *a removal* or
  *gone stale*; both empty on a bound and on a difference a tick found that no change
  explains — the period that holds first, from the snapshot's `period`, so only where
  it is of what the node shows, then those `shown_history` derives, the newest fifty
  open (`SHOWN_OPEN`) and the rest in one `<details>` beneath them, which needs no
  script (`_shown_rows`, a `_ShownRow`, in `app.py`);
  where the log holds no change of a node, one that declares
  nothing says so, one a check has written shows the period that holds, begun when
  the kept table says or *before* its bound, and only one nothing is kept of says *No
  status changes recorded*
  ([ADR-0102](adr/0102-a-readings-table-keeps-time-and-names-in-view.md)).
  The periods keep their measure (`.ls-history__periods`) and the readings take the
  page's width. Both tables scroll sideways in their boxes where their rows are wider
  than the page, and there, on a phone, a reason keeps a line's worth of width
  (ADR-0105 decision 3). A suppressed event carries the
  rule's name in an `event-suppressed` chip, which paints its own maintenance tint
  rather than inking onto the row color beneath it ([ADR-0028](adr/0028-design-tokens-and-themes.md)).
  A row that a pin caused says so in an `event-cause` chip on the same tint, ruled in
  its ink — *set*, *edited*, *maintenance ended*, *line's pin set*, *line's maintenance
  ended* — since such a row reached, and a pinned line's is no recovery (ADR-0107
  decision 3). A removal's row carries *removed* in the same chip
  (`event-cause--removed`), in the pair of the nothing it moved to, since no pin did
  it; the row that ends a wait carries *reached* (`event-cause--reached`), in the pair
  of the status its row shows (ADR-0119 decision 3); and the filter row has a third
  switch group, *readings*, *pins* and *removals*, in neutral ink like *reached* and
  *held back* (ADR-0109 decision 5).
- `system.html` / `system_installed.html` / `_system_band.html` / `_system_info.html` —
  the System views ([ADR-0100](adr/0100-system-is-two-views.md)), tabs beneath one
  band. *Running* (`system.html`) is which instance this is and the engine block — the
  `_system_info.html` partial, swapped by `poll.js` on the same server-seeded stamp
  and ~10s poll as the dashboard — whose schedule has a row per check: its type, and
  what it is reached through where it is, beneath its path; *Every*; the in-flight run,
  the armed next slot (marked `· retry k/N` when it is a failure-retry slot,
  ADR-0033) and the last completed run, each a time and its interval on one line; and
  *Declared*, the type's estimate, beside *Seen*, the heaviest record the last run
  carried, a legend saying which compares with which. *Installed*
  (`system_installed.html`) is what startup settled — check types, packages,
  extensions, identity, the policy — every section open under an index, and not
  polled. The schedule's box comes with every poll, and `poll.js` puts it where the
  one before it stood, so a reader at its right-hand columns stays at them (ADR-0105
  decision 6).
- `login.html` — the full brand moment (the gaze, wordmark and tagline) above the
  form; `text.html` — the remaining stub.
- `links.html` — the shared toolbox (§7, [ADR-0030](adr/0030-curated-links.md)).
  Groups flow into CSS columns, each block unbreakable so a heading is never
  stranded at the foot of one; a row is a flex pair of mark and text, which is what
  gives a wrapped title its **hanging indent** — the reference implementation ran
  wrapped titles back under the icon. An icon that declared a light/dark pair emits
  **both** files with one hidden by `body[data-bs-theme="dark"]`, because under the
  `auto` theme the server cannot know what the OS will resolve to; anything else —
  one file, a favicon — rides a **theme-invariant chip**, the one background such a
  file is guaranteed to be legible on. `static/js/links.js` swaps a failed image for
  the neutral glyph, attached as a listener rather than an `onerror` attribute so
  the page never becomes the reason a Content-Security-Policy cannot be turned on —
  which is part of why one could ship at all (§5.4).
  The same script owns the **filter**: a match against the one field the server puts
  in `data-ls-match` (the entry's title and its group's, lower-cased server-side),
  every token required and in any order, hiding entries and then any group left with
  none — never sorting, because the configured order is the operator's. It is
  delegated and re-applied through a `MutationObserver`, so both behaviors survive a
  fragment swap the day this page starts polling — the shape `tree.js` and
  `maintenance.js` already use.
- `static/css/overview.css` — every color the surface paints is a **design token**
  (`--ls-*`) declared once on `:root`, and a **theme** is an override block on
  `body[data-ls-theme=…]`, never a fork
  ([ADR-0028](adr/0028-design-tokens-and-themes.md)): the two-surface state model
  (a vivid fill and a pale tint per state, with the ink that belongs to each — the pale
  fill stepped toward its ink on every other level of node, its box's and its quiet
  chip's alike, the template's `is-stepped` on the node, by the theme's
  `--ls-tint-step`, and its words toward the page's ink, so a box or a chip stands apart
  from the box around it), the brand inks, the shell (bar, rail, page, band, kiosk line), the dashboard
  grid/card/panel styles, the leaf **chips** and the heartbeat **status strip**,
  the settings menu, `/about`, and the table row tints, which a theme may restate on
  the logs alone — cyberpunk does, on the Events page and a node's History tab, each a
  `.ls-log`, weighing a row's tint by its status and lighting its status word in its
  state's ink; and cyberpunk draws its culprit as a neon tube, every vivid surface
  lit dark glass under white-hot words, with an edge, a glow and a halo on its name
  and state word in its state's neon, the ink that state's words wear in the theme.
  Status text is held to WCAG **AA** in every theme — plain, vivid, pastel, dark and
  cyberpunk, the library's default and gated since 2026-10-18, where it had been a
  declared fun theme, measured but not gated — a pale pair's state word at its quiet
  80 % among it, but a healthy one's (ADR-0028's quiet OK) — verified per theme by
  computed style and measured contrast, not by the presence of a class. Bootstrap via CDN;
  `site.webmanifest`.
- the icons under `static/` — every one rendered by `tests/render_brand.py`, through
  Chromium, from the drawing in `brand/`: little-sister's eye with raspberry eyeshadow
  on its lid, in a full form, `eye.svg`, and a small one for 32 px and below,
  `eye-small.svg`, with heavier lines and no lashes, the eyeshadow a layer of its own
  that a renderer may leave out. The tab icons are the small form — `favicon.svg`, whose
  ink turns light on a dark tab strip, the PNGs and the `.ico` — and the home-screen
  icons the full form on rose paper, edge to edge, since the phone rounds the corners.
  Each image carries the digest of the SVG it was rendered from, which
  `tests/test_brand.py` holds to the drawing as it is now; `tests/test_brand_browser.py`
  holds the pixels.

### 6.1 Template slots — `slots.py`

The declared places a **dependent package** may put HTML of its own
([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)). `slots.SLOTS` is a
closed roster: a slot name, the exact context handed over there, and where it sits. A
dependent package calls `slots.register(slot, package, template, context=…)` in the
same import-before-app slot check types and icon packs use; the template comes from
that package's own `templates/` directory and is rendered by **our** Jinja environment
— autoescaping on, our filters and `url_for` available. The optional context provider
is deployment code that turns the slot's context into the values its template wants,
and returning `None` means *nothing here*, which is how a filler declines a node or a
surface. So **data is computed in Python and HTML is authored in Jinja**: a deployment
never assembles markup, and the untrusted halves of the context (a reason line, ADR-0018)
are escaped by the machinery that escapes them everywhere else.

Extension templates resolve only as `ext/<package>/<name>`, through an `ExtensionLoader`
mounted **behind** the app's own — so filling is additive and no registration can
shadow a core template. Several packages may fill one slot; all render, in registration
order. A provider that raises or a template that will not render is logged with slot,
package and template named and contributes nothing; a core template naming an
undeclared slot raises. `/system/installed` lists what registered.

The roster holds **two** slots, and they differ in their **subject** — which is what
decides where a deployment's action belongs
([ADR-0036](adr/0036-addressable-reasons.md)):

- **`reason.actions`** — beside every rendered reason line, on the dashboard grid
  (`_status_grid.html`'s `reason_block`) and on a node's own page (`_own_lines.html`:
  a leaf's `check.html`, a branch's head and its card at depth 0), with `node`, the
  **unshortened** `reason`, the whole `line` (its slug, its own code, its `running`
  flag and any pin), its `index` and the `surface` (`check` on a leaf's page, which is
  not polled, `grid` wherever the poll draws), and what a draft is written with
  (below). The place for an action about **one** finding, where a node's
  reasons are individually addressable members. A provider receives **the names it
  declares** — or all of them if it declares `**kwargs` — so a context that grows
  never costs a filler written against an earlier one its chip
  ([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)). The
  library's own **copy chip** fills this slot: a link to
  `/copy/<path>?reason=<slug>`, on member lines only, since prose has one thing to
  hand over and it is the node.
- **`node.actions`** — on every node the grid draws as a **box**: a card head and each
  nested box under it, and the viewed node's own head on its page — a branch's from
  depth 1, and a leaf's — with `node`, `surface`, what a draft is written with (below)
  and the `place` — `card`, `box` or `frame` — so a filler that wants to be on cards
  alone, or everywhere but a page's head, can decline by name instead of guessing from
  the node's depth. In a head's row the
  actions open the toolbar (§6), an action with an icon as a square, one without as its
  label chip. Boxes and not only cards because a card is the *top* of a subtree and is
  usually a container with no reading of its own, while the failing leaf an action is
  about sits in a nested box; a node closed to a **chip** draws no box and carries
  none. The
  place for an action about the **whole node**, which is where it belongs when the
  reasons are *prose*: a failure message and its stack trace are one condition in
  several paragraphs, and a per-line control there would offer to raise a ticket about
  a stack trace.

**What a draft is written with.** Both hand a filler, beside the node, two functions
for what it makes from the node that leaves the instance — a ticket, as
`little-sister-jira`'s chip drafts one
([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decisions 4 to 6): `written_out(text, inline=False)`, a text of the node written out
as the Copy document writes one (`copy_status.written_out`, the address of the node's
handbook written in), and `details()`, the rows of its *About* card as `(key, value)`,
those given down to it among them, each value written out the same way, a link in the
short form to the handbook of the node it is given on (`copy_status.written_details`,
which the Copy document's *Details* block is made with). Functions and not values,
since a slot is filled for every node at every render and the card is resolved down
the live tree: `slot()` (`_drafting`) binds them to the node, and only the draft that
calls one pays for it. Outside a request there is no base to write an address from,
and a short form stays as written.

Both are offered on **every** node; a provider returning `None` is how a filler
declines one, so placement policy stays with the extension rather than being baked into
our templates. Core emits the `.reason-actions` / `.node-actions` rail and styles the
`.reason-action` / `.node-action` chip, so two extensions look like one product; a rail
collapses when nothing filled it. On a member's detail page, core's own stable
maintenance disclosure shares the visual end rail without changing the slot's name,
context or filler order. The `slot()` template global lives in `app.py` rather
than in `slots.py` because it carries the one presentation rule the seam must not know:
**the kiosk renders no slot**.

**Assets** ([ADR-0037](adr/0037-extension-static-assets.md)). A package declares what
it ships with `slots.register_assets(package, *members)`: **bare member names** inside
its own `static/` directory (no separators, no `..` — the icon sandbox verbatim), and
**`.css` / `.js` only**. The **library** emits the tags — a `<link>` or a deferred
`<script>` in `_header.html`, once per page, in registration order, after our own
stylesheet — so an extension never writes a tag into a page it does not own, and never
re-derives load order or caching. They are served from **our own origin** by
`GET /ext/<package>/<member>`, read through `importlib.resources` and looked up in the
registry rather than built into a path; the URL carries an eight-hex **content hash**,
so a changed file is a changed URL and the response is immutable. Same-origin is the
security half: it is what keeps a future `script-src 'self'` able to cover an
extension's code without a nonce for something the library never saw. Login-gated, and
the kiosk loads none of it.

### 6.2 The declarative action list — `actions.py`

The common case for a slot is *a link with the node's details in the query string*, and
it needs no code: `config/actions.yaml` describes one
([ADR-0038](adr/0038-declarative-action-list.md)). An entry is `label`, `url`, `slot`
and optionally `icon` and `under`; roots are **layered like the checks**, so a site root
adds its actions to a base root's. `url` is a template over `{path}`, `{name}`,
`{code}`, `{reason}` and `{reasons}` — for a node action `{reason}` is the node's first
line and `{reasons}` all of them — and every substituted value is **percent-encoded**,
so only a URL is ever templated and an action can never carry markup onto a page. A
template naming anything else is **refused at load**, because a button that lies is
worse than no button. `under` limits an action to one subtree, compared segment-wise
(`/system/alpha` covers `/system/alpha/disk`, never `/system/alphaville`), and `tag` to
what carries one tag
([ADR-0139](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision
7), both holding where both are written; a `tag` that is no tag, or one the
configuration writes for no node (`use_tags`), drops the action onto the startup record.
It is registered as a **`builtin` filler of both slots**, through the same loader an
extension uses, so a configured chip and a coded one share one rail in one order — and
it is the one registration `slots.forget_fillers()` puts back, the way the icon registry
keeps its built-in pack. `/system/installed` marks each filler *built-in* or
*extension*.

---

## 7. Configuration & data

- **Deployment actions** — an optional `config/actions.yaml` per root lists chips the
  dashboard and the detail page offer on a node or on one of its reason lines
  (`label`, `url`, `slot`, optional `icon`, `under` and `tag`), layered across roots
  like the checks (§6.2, [ADR-0038](adr/0038-declarative-action-list.md)).
- **Content-Security-Policy sources** — an optional `config/csp.yaml` per root, a
  mapping of directive to a list of sources, layered across roots like the actions and
  **unioned**: a site root adds to a base root's, because a policy is a union and
  there is nothing to overwrite. It is the deployment's last word on the assembled
  policy (§5.4) and the only place a policy *keyword* is taken at all — a package may
  contribute an origin and never one of those
  ([ADR-0048](adr/0048-an-assembled-content-security-policy.md)).
- **Aspects a dependent package added** — `config_dir.register_aspect(name, …)` lets
  an extension declare a `config/<name>.yaml` of its own
  ([ADR-0035](adr/0035-registering-a-config-aspect.md)), so its operator-editable
  parameters sit in the same tree and layer through the same path-list. The library's
  own aspects are the floor and cannot be redefined; the document's schema and
  validation belong entirely to the package that registered it, and the name shows on
  `/system/installed`.
- **Users** — either `config/users.yaml`, or `config/users/users.yaml` beside
  `config/users/avatars/`, a flat map keyed by username with `firstname`, `lastname`,
  `password`, optional `admin: true` and optional `avatar`. The avatar is a bare name
  inside that one directory, with or without its allowlisted image extension; an
  extensionless name must resolve uniquely. Git-ignored, and the one aspect that does
  **not** merge across roots: the first root declaring either form wins whole, a second
  is a warning — which is also how a deployment pins one exact file, by giving it a
  root of its own and naming that root first
  ([ADR-0046](adr/0046-user-list-from-the-configuration-roots.md),
  [ADR-0031](adr/0031-deployment-config-directory.md),
  [ADR-0045](adr/0045-user-avatars.md)).
- **Secrets** — a git-ignored `.env` file may supply `SECRET_KEY` (optional —
  unset means a random per-start key) and any check credentials via the
  environment ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). It feeds
  the two variables of the logging default as well, `LOG_LEVEL` and `LOG_FILE`,
  which are read after it whatever a process imports first (§11).
  A check names its credentials in a `secrets:` block, each a **secret
  reference** — `env://NAME` for the environment, or another `scheme://address`
  resolved by a deployment-registered resolver — once at check construction
  (§4.5, [ADR-0023](adr/0023-secret-references.md)).
- **API tokens** — the `LITTLE_SISTER_API_TOKENS` setting holds named per-client
  bearer tokens (`name=token,name2=token2`) for the JSON backend (ADR-0080 decision 8); its
  value may itself be a `scheme://` secret reference, resolved once at startup
  ([ADR-0023](adr/0023-secret-references.md)).
- **What to monitor** — YAML files across the `config/checks/` directories, a
  path-list union selected by `LITTLE_SISTER_CONFIG_DIR` (§4.5).
- **Node metadata** — an optional `config/nodes.yaml` per root declares each node's
  `about` and `title` keyed by path (`path: {about: …, title: …}`); layered across
  the path-list per field and seeded at startup (§4.5,
  [ADR-0012](adr/0012-node-metadata.md) / [ADR-0017](adr/0017-node-title.md)).
- **Curated links** — an optional `links` aspect holds the shared toolbox `/links`
  shows: `config/links.yaml`, or `config/links/links.yaml` once a deployment ships
  icon files of its own (both forms are legal, and growing from one into the other is
  a move rather than a rename). It carries one flat level of `groups:`, each with a
  `title` and an ordered list of entries (`title`, `url`, an `icon` **name** and an
  optional one-line Markdown `note`), and an `icons:` map naming the deployment's own
  marks — one file, an `on_light` / `on_dark` pair named for the background it goes
  on, or `none` to suppress a mark. Groups **merge by title** across the roots and
  concatenate base
  first — two files contributing to one group is not the ambiguity two checks claiming
  one node is — while `icons:` entries resolve **per name**, a later root replacing one
  whole. Entry order is curated and never
  sorted. Relative paths resolve against the document's own directory and may not
  leave it. Structural problems — a bad scheme, an unknown key, a missing icon file, a
  duplicate title — **warn and continue**, so a typo in this file can never take the
  monitor down; the file is re-read when its size or mtime changes rather than loaded
  once, because editing a link must not cost a restart while history is in memory
  ([ADR-0030](adr/0030-curated-links.md), `links.py`).
- **Link icons** — an entry names a mark, never a URL, and the name resolves through a
  search path, first match wins, in the shape script resolution already uses
  ([ADR-0021](adr/0021-script-resolution.md)): the deployment's own `icons:` map → the
  files it dropped in **`config/links/icons/`**, discovered by file name → packs
  registered by dependent packages, later registration winning → little-sister's
  **built-in pack** → the link origin's `/favicon.ico` → a neutral glyph.
  **A discovered file needs no declaration**: `firewall.png` in that directory *is*
  the mark named `firewall`, and `<name>-on-light.*` / `<name>-on-dark.*` pair up the
  way the built-in pack's own files are named. One flat directory, no recursion, and
  anything that is not an icon file (a README, a `.DS_Store`) passes in silence. The
  `icons:` map stays for what a file cannot say — a remote URL, or `none` — and
  outranks a discovered file of the same name; only the **directory** form of the
  aspect has an `icons/`, which is what that form is for. Resolution is
  **per name, never per pack**, so a house pack defining one name leaves the rest of
  the built-ins standing, and an entry replaces a name **whole** rather than filling in
  half of a pair. A dependent package registers with
  `icons.register_pack(package, {name: file})` in the same import-before-app slot it
  already uses for check types — order-sensitive, so a shadowing is logged with winner
  and loser named — and a pack member is a **bare file name inside its own package
  data**, which is the whole sandbox: a pack cannot name a path, so it cannot reach out
  of what it ships. The built-in pack (`icon_pack/`, registered through that same door)
  carries **glyphs drawn for little-sister** — a cloud for `aws`, a git graph for
  `github` — rather than vendor marks: redistributing a logo inside a wheel is a
  question each vendor answers differently, while drawing our own asks nobody, works
  with no outbound access, and themes as a proper pair. Where a deployment wants the
  real mark, its **own local file** is the next rung and an **external URL** the last
  — deliberately in that order. Hotlinking settles only redistribution: displaying a
  mark is displaying it whichever server the bytes came from (nominative use is what
  makes either arrangement fine), it *adds* a terms-of-service question since asset
  hosts commonly forbid it, and it is the least reliable of the three — referrer
  checks, URLs that rot on a redesign, and nothing at all for a viewer whose network
  cannot reach the host. Its host is one the page's own policy allows, taken from the
  file (§5.4), so `config/csp.yaml` needs no line for it. Each name ships
  `<name>-on-light.svg` / `<name>-on-dark.svg`, named for the background the file goes
  on and differing only in ink (the two `--ls-ink` values, [ADR-0028](adr/0028-design-tokens-and-themes.md));
  the pack's `manifest.yaml` records what every glyph depicts and its terms
  ([ADR-0030](adr/0030-curated-links.md), `icons.py`).
- **General options** — `config/settings.yaml` (shallow-merged per key across the
  roots, later winning; override the whole thing with a single file via
  `LITTLE_SISTER_CONFIG`)
  holds display/runtime options: `timezone` (default `Europe/Berlin`), `time_format`,
  the dashboard budgets `reason_cap` (default 6) and `maintenance_cap` (default 5) — the reason-line and maintenance-pin caps ([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)), a `branch_cap` left beside them named at the start as no longer read — `reading_cap` (default 10, the readings of each series a Series view lists beneath its curves, `0` the curves alone; a check's own wins, §4.11, [ADR-0092](adr/0092-a-check-declares-its-measures.md), [ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md)), `maintenance_default_expiry` (default `7d`, the window applied when an admin
  gives no explicit duration or expiry — ADR-0014), `stacktrace` (default **true** — a failing
  check's trace on its node, §4.6), `card_status_line` (default `beside` — the
  compact one-line card head; `below` gives every card a standing status line
  under its title row, a calmer grid that spends vertical space for it, rendered
  as a `data-ls-card-state` body attribute the stylesheet branches on; §6),
  `dashboard_columns` (default `flow` — large roots may spend a wide grid's
  spare columns per the stable width-priced plan,
  [ADR-0056](adr/0056-stable-useful-dashboard-flow.md); `plain` withholds the
  plan and keeps every card at one ordinary track, the no-JavaScript grid), the
  **looks' defaults** — `theme` (default `cyberpunk`), `chip_runs` (default
  `aligned`), `boxes` (default `rows`), `inspection_card` (default `off`),
  `toggle_hover` (default `wash`), `head_buttons` (default `pointer`) and `failures`
  (default `open`), what a browser that never chose a look draws
  (§5.3, [ADR-0029](adr/0029-per-user-presentation-preferences.md)) — and
  the **failure retry** — `retry_interval` /
  `retry_attempts` (default off / 2; [ADR-0033](adr/0033-budgeted-failure-retry.md),
  §4.6), both overridable per check — `state_interval` (default 60, the seconds
  between writes of the kept state files, §4.8), `keeper_interval` (default 900, the
  seconds between sends of the event log and the series to a keeper while no other
  instance stands by, §4.8,
  [ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md)), the engine's sizing numbers —
  `max_workers` (default 8, the worker ceiling and what declared costs are summed
  against), `entry_limit` (default 100,000), `memory_share` (default 0.5, a
  fraction in `(0, 1]`), `record_limit` (default 3,072 bytes, what one record may
  weigh, §4.5) and `series_limit` (default 8,388,608 bytes, what every
  series together may weigh before the one written to longest ago is evicted, §4.10,
  [ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md)), whose defaults are the
  constants in `limits.py` beside the measurements that read them
  ([ADR-0075](adr/0075-a-check-declares-what-it-costs.md), §4.6) — `escalate_after`
  (default 1, how many consecutive readings of a worse code a
  node needs before the level above counts it; overridable per check, and `1` is
  publish-at-once, [ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md)) — and
  `instance` (default the
  hostname: what this instance is called, on `/system` and in whatever a package
  writes down about the process — [ADR-0074](adr/0074-this-instance-has-a-name.md);
  validated in `instance.py`, which appends the parts that make the mark unique, so
  a name here is safe to choose and a bad one falls back with a warning) — loaded
  once into `config.py`'s `Config`
  ([ADR-0120](adr/0120-every-stored-time-is-an-instant.md) decision 7). A key that
  nothing reads, in any layer, is said in the log at start with the keys that are
  (`SETTINGS_KEYS`), as `links.yaml`'s loader says its own: a misspelled cap or look
  would otherwise change nothing and say nothing. A time is
  stored as an instant in UTC and written in that timezone where it is shown, by the
  `localtime` filter (`zoneinfo` + `tzdata`) — a record's own times, which the seam
  stores in UTC, by `record_fields` (§4.5); the same zone interprets maintenance expiry
  input that has no explicit offset, and what comes out of that is an instant too. And
  the same zone stamps the lines of the default log, each with its offset (§11,
  *Logging*): `config.py` hands it to the logger the moment it has read it, before any
  other setting is looked at.
**Startup contract** ([ADR-0031](adr/0031-deployment-config-directory.md)): strict
about the tree, tolerant about its contents. The process **refuses to start** — naming
the resolved path in the exception and in the log — when there is no configuration
directory (the message names the moves if the pre-`config/` layout is still lying
around), when a named root does not exist, when an aspect is stored in a form it does
not have, or when **no** root provides `checks/`. A `config/checks/` that exists but
holds **no checks** is the one survivable case and is loud rather than silent: the
engine runs, a warning names the directories it searched, and the **heartbeat carries
that same sentence at WARN** (§4.6, [ADR-0005](adr/0005-dashboard-freshness-and-self-monitoring.md))
— with zero checks the tree is only the heartbeat, so an OK there would roll up to an
all-green root while nothing at all is watched.

- **State** — `var/state/` (git-ignored runtime state, a fixed path) holds what a
  restart keeps: the admin maintenance pins (per node and per reason) in
  `pins.json`, written through, and the event log, with what every node last
  showed, in `events.json.gz` and the
  series in `series.json.gz`, compact JSON under gzip, written every `state_interval`
  and at graceful shutdown; all three restored at startup (§4.8,
  [ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md),
  [ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md)). The tree
  itself is rebuilt by the checks. Where a deployment registers a **keeper**, the
  whole directory is mirrored to it — the pins as they change, the event log and the
  series every `keeper_interval` while no other instance stands by and every
  `state_interval` while one does — and restored from it before
  anything reads — which is what carries this state across a redeployment onto a
  fresh machine (§4.8).

---

## 8. Not implemented yet

Current gaps.

- **A queryable store** — a history longer than the bounded event log, searched
  rather than read whole, and retention as a decision rather than a deque. The log
  itself survives a restart now (§4.8); what a store would add is a package's seam,
  never a database in the core
  ([ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)).
- **A drawing for a state.** A record with a state has no mark (§4.11,
  [ADR-0111](adr/0111-a-runs-mark-says-how-the-run-stood.md) decision 5): it is a row of
  its readings table, and how long each state lasted is drawn nowhere.
- **What was not observed, and a removed node's own pages.** A child a run leaves out
  without its node saying that its children are complete stays and goes stale, and
  nothing says why it was not read: a branch that says it *could not observe*, and
  staleness that obeys a pin, are not built
  ([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md) decision 7). And a node
  its check no longer reports has no page of its own: its readings are on its check's
  History page, its rows on the Events page, and its own Status and History pages say
  that there is no such node until it returns.
- **A keeper to register.** The seam is built (§4.8) and the library ships no
  implementation of it, which is the design rather than a gap — a store is a
  package's business, and a local installation wants none. Out of the box, then,
  nothing carries `var/state/` off the machine it is on.
- **What the log keeps of what was held back.** Every transition is recorded, marked
  or not (§4.4), so a long maintenance window over a flapping check writes rows nobody
  wants first, and they take their places in the bounded log. `/events` leaves them out
  when its *held back* switch is off, and shows them by default
  ([ADR-0101](adr/0101-the-events-page-is-filtered-by-its-url.md)); whether the log
  keeps them at all, or apart, is the question retention answers.
- **A row when a shield's end lets a change reach.** A change held back while its node
  is reached through a failing check
  ([ADR-0084](adr/0084-a-check-may-be-reached-through-another.md)) reaches when that
  check recovers, or goes stale, and the log does not say when; a wait that ends by
  its count writes its row (ADR-0119).
- **Satellite federation** and **write actions** over the JSON API
  (`project.md` §2.9). An `Event`'s `suppressed_by` stays server-side until then; the
  snapshot's `reported_code` is published, as a node's `reported`
  ([ADR-0080](adr/0080-the-envelope-is-the-snapshot-published.md)).
- **An enforced Content-Security-Policy.** The header ships as Report-Only (§5.4), so
  it measures and blocks nothing. Enforcing it costs naming or vendoring the CDN as a
  script source, deciding what to do about the computed `style=` attributes, and one
  rule an extension's filler would have to follow — none of which is worth committing
  to before the reports say what a strict policy would actually have caught.

---

## 9. Known limitations

- A **hung check** ties up a pool worker until it returns (Python can't kill
  threads); built-in checks enforce their own timeouts. The beat says so once the
  run has outlived its period (`engine.late.<path>`, §4.6), and names the checks
  queued behind it when the pool is saturated (`engine.pool`).

---

## 10. Quality gates

`hooks/pre-commit` runs `uv run ruff check`, `shellcheck` over every tracked shell
script, `uv run mypy` twice — on the pinned interpreter and with
`--python-version 3.11`, the floor — and `uv run pytest`, and blocks a commit on any
failure (enable per clone with `git config core.hooksPath hooks`). mypy targets
`src/`.

ruff's selection is the family's one, which the release check holds six projects to;
the comment fenced beside it in `pyproject.toml` is its argument. Its `DTZ` rules
refuse a clock read and a time built without a zone
([ADR-0120](adr/0120-every-stored-time-is-an-instant.md) decision 10). The three wall
times the library builds on purpose — `_wall` in `app.py` and the two round times of
`curves.py` — carry `noqa: DTZ001` under a comment that says why.

Test suites: `test_status.py` (the `Status` model + ADR-0039 roll-up),
`test_tree.py` (the tree, events, history, maintenance + its persistence),
`test_instants.py` (the clock, what holds an instant, its spelling and its strict
reading) and `test_stored_instants.py` (a state read on a machine in another zone, the
hour a clock repeats and the hour it skips, and a file whose times carry no zone),
`test_copy_status.py` (the canonical incident-copy documents — the tree's outline
and one node's — and the zoned instants both write), `test_copy_documents.py` (where
each says it is from, when it was made and since when, the tree's head and its count, a
branch's document and what a stale reading says), `test_copy_tab.py` (Copy as a view
of its node: the tab on every view, the page in the node's band, and no Status page
that carries a document) and
`test_copy_browser.py` (the two buttons in Chromium, on the machine's own address and
over plain http by a name: what a paste then receives),
`test_checks.py` (the http/file/command checks + loader), the SSH family —
`test_ssh.py` (transport, connect/command/script), `test_host_metrics.py`,
`test_qnap_metrics.py`, `test_macos_memory.py` and `test_metrics_scripts.py` (the
bundled shell scripts),
`test_config.py` (general config), `test_secrets.py` (secret references: resolution,
the resolver registry, the engine's pinned-ERROR path), `test_reasons.py` (keyed
entries: prose vs members, slug stability, the check-facing forms, coded entries
and `derive_code`),
`test_slots.py` (the slot roster, the loader's sandbox, containment, and the asset
seam of ADR-0037), `test_actions.py` (the declarative list: loading, templating,
percent-encoding and the `under:` filter),
`test_pins.py` (a pin with a kind, and the pins' store and its file), `test_nodes.py` (nodes.yaml loading, `about` precedence, the consistency
pass and its note of a long `about`), `test_metadata.py` (the shared subnode-metadata helpers),
`test_engine.py` (scheduling, concurrency, `info()`, the long `about` a run hands
over), `test_retry.py` (the budgeted
failure retry of ADR-0033), `test_config_dir.py` (the configuration roots, aspect
forms and the startup contract of ADR-0031), `test_values.py` (typed reads out of a
decoded bag, ADR-0026), `test_render.py` (Markdown rendering and the
reason-assembly helpers, ADR-0018), `test_titles.py` (what the fold treats as the
same string, and the two emphasis spellings it splits on), `test_paths.py` (which
root a loaded-from path is drawn against, and what stays long), `test_links.py` (the
`links` aspect, ADR-0030), `test_icons.py` (icon names,
the pack registry and resolution),
`test_web.py` (the routes via the Flask test client), `test_web_pins.py` (branch
pins: a head's ‖ and a branch's head, and a branch's own lines on its page),
`test_pin_block.py` (a pin's block on a leaf's page, the controls that set one, and
the expiry an edit shows and keeps), `test_wall_pins.py` (the block in a card and in
a branch's head, the editors that open there, and what the poll that waits for them
goes by), `test_maintenance_page.py` (the same blocks on
*Handled*: how they are grouped, what each says, and a change made there
coming back to its node; `page_tree.py` is the parser these read a response through,
as elements by class, tag and id and the text a reader gets), `test_handled.py` (what
ADR-0135 adds on the pages: a closed chip's diamond and its words, the pill, a
branch's *why* card and what its Copy document writes of it, and the note's card on
the wall's page), `test_pin_write.py`
(where a pin's write returns to, and the save that changes nothing) with
`test_pin_browser.py` (the same in Chromium: a line far down a long page back in
view, the cursor in an opened editor, an editor opening in its card and the poll
holding off while it is open, a node page's ‖ opening the editor its head keeps, and
a branch's own line pinned in its head), `test_seen.py` with `test_seen_pages.py` and
`test_seen_browser.py` (a failure marked seen: what the tree counts and what ends it,
what the pages, the Copy document and the envelope say of it, and the ringed check's
editors in Chromium),
`test_api.py`
(the JSON backend: serialization, content negotiation, token auth, and both reads
held to the spec in both directions) with `test_series_read.py` (the series read,
against its record's sentences),
`test_contrast.py` (the AA bar of ADR-0028, measured rather than eyeballed),
`test_ui_fixtures.py` and `test_demo_check.py` (gate coverage for the two UI
harnesses), `test_wall_cost.py` (what the wall costs the server on a deployment's own
tree, its names replaced — the refresh's fragment in bytes and elements, the render's
time and peak memory — the baseline the interactive wall's stages are held to, with
`test_wall_cost_browser.py` for what a browser pays), and `test_docs_links.py`
(every relative Markdown link resolves). The suite passes on the pinned 3.14 with
ruff and mypy clean, and once per release on a real 3.11.

---

## 11. Public API surface — the version contract

Two kinds of dependent read this section, and they read it differently. A
**deployment** pins little-sister to a semver tag
([ADR-0022](adr/0022-generated-release-branch.md)), so a library upgrade is a
deliberate version bump rather than silent drift. A **plugin** declares a
**floor** and never a pin (`little-sister >= x`) — because a deployment installs
several, and two plugins that each pinned an exact version could not be installed
together at all. A floor is a statement about *this section*: "I need at least the
release that promised the names I write against." Neither works unless the surface
is explicit. A tag promises to keep these stable:

- **WSGI application** — `little_sister.app:app` (the Flask app of §5), the object
  a deployment runs under `gunicorn`, and the **hooks module** gunicorn loads beside it,
  `--config python:little_sister.gunicorn_hooks`: importing the application starts
  nothing, and the hooks start it after the worker's import and stop it when the worker
  leaves ([ADR-0091](adr/0091-an-import-is-not-an-instance.md),
  [ADR-0088](adr/0088-a-stop-ends-at-its-save.md)). A gunicorn line without the flag
  serves an application with no engine, which says so on every page and as `failed` on
  `/health`.
- **Template slots** — `little_sister.slots`: `register(slot, package, template,
  context=…)`, the declared slot roster `SLOTS` and, per slot, the **context keys** it
  passes and the CSS classes of the frame around it (`.reason-actions` /
  `.reason-action` for `reason.actions`, `.node-actions` / `.node-action` for
  `node.actions`). This is a deliberate carve-out from the
  "exact HTML may move" rule below: a slot's *name*, *context* and *frame* are the
  contract, while the markup around it stays free to change. Adding a context key is
  compatible; removing or renaming one, or retiring a slot, is a version bump and a new
  ADR ([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)).
- **Extension assets** — `little_sister.slots`: `register_assets(package, *members)`,
  the `static/` directory convention, the `.css` / `.js` allowlist and the
  `/ext/<package>/<member>` URL shape
  ([ADR-0037](adr/0037-extension-static-assets.md)).
- **Content-Security-Policy contributions** — `little_sister.csp`:
  `allow(directive, source, by=…)`, `origin_of("<aspect>.<field>")`, the set of
  directives a package may add to and the origin-never-a-keyword rule
  ([ADR-0048](adr/0048-an-assembled-content-security-policy.md)). Registered in the
  same import-before-app slot as the rest. The policy's *contents* are not part of
  the contract — the defaults are the library describing its own pages, and they move
  when the pages do.
- **Configuration aspects** — `little_sister.config_dir`: `register_aspect(name, …)`
  plus the reading helpers a registered aspect then uses, `aspect_files(name)` and
  `sole_aspect_file(name)` ([ADR-0035](adr/0035-registering-a-config-aspect.md)).
  Registered in the same import-before-app slot as the rest — and the **report on
  configuration files no aspect claims** sits at the far *end* of that slot rather than
  at the first read: `announce_aspects()`, called once from the app import, over every
  configured root, naming the known aspects with the packages that read them
  ([ADR-0070](adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)).
  Resolving a root is silent, because in this family the first resolution *is* somebody's
  registration reading the aspect it has just declared.
- **The self-report seam** — `little_sister.self_report`:
  `register_contributor(name, callable)`, the callable answering a sequence of
  `little_sister.reasons.Entry` lines, and the `<name>.<slug>` shape those lines are
  addressed by in the flat view ([ADR-0072](adr/0072-the-instance-reports-on-itself.md)),
  the `title`, `about` and `report` a registration may declare for its child of
  `/little-sister`, the two records a contributor may keep its lines in, `Standing`
  and `Held`, each writing the line and the log entry in one call (§4.8), and
  `register_action(contributor, slug, label, handler)` for a button on that child
  ([ADR-0076](adr/0076-the-instance-node-is-a-branch.md)). Registered in the same
  import-before-app slot as the rest. What the *library's own* lines say is not part
  of the contract; that a registered contributor's lines reach
  `/little-sister/<name>` every tick under their own slugs, clear when it stops
  returning them, and that its actions run admin-only from its child's page and
  each between two flushes of the state layer, is.
- **This instance's identity** — `little_sister.instance`: `this_instance()` and the
  `Instance` it answers with, carrying `name`, `pid`, `started`, `tag` and the joined
  `mark` ([ADR-0074](adr/0074-this-instance-has-a-name.md)). Resolved on the first
  call and memoised, so a package may import this module before a configuration root
  exists and still get one mark for the life of the process. Two things are
  promised and they are the two a store depends on: **no two processes share a mark**,
  and **one process's mark does not change while it runs**. What is *not* promised is
  the shape — the mark is compared for equality and printed, never parsed, and the
  parts may gain a sibling. A package that writes it into storage outliving the
  process is why this is a contract at all.
- **The keeper seam** — `little_sister.keeper`: `register_keeper(name, keeper,
  replace=…)` and the three methods a keeper answers — `load(name) -> bytes | None`,
  `save(name, data)`, `list()` — the file store that mirrors `var/state/` somewhere
  durable ([ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md) §5,
  §4.8 here), and the five it may answer — `tick(interval_seconds) -> bool`,
  `close()`, `changed_since_sync() -> Sequence[str]`
  ([ADR-0077](adr/0077-authority-follows-the-lease.md)), `push(name, data)` and
  `standing_by() -> bool`
  ([ADR-0134](adr/0134-the-state-is-compressed-and-stamped.md)) — each looked for by
  name and done without. One per instance, registered in the same import-before-app slot. The
  *names and contents* of the files it carries are deliberately **not** promised: a
  keeper moves bytes and never reads them, which is what lets the directory grow a
  file without a keeper release.
- **Check-type registry** — `CHECK_TYPES` in `little_sister.checks` (§4.5). A
  deployment adds its own check *types* by importing them before
  `little_sister.app:app` — whether they are modules in its own tree or **installed
  packages**, which is the same seam and was always described as an evolution of it
  rather than a rewrite. That evolution has run: `little-sister-github`,
  `little-sister-wiz`, `little-sister-aws` and `little-sister-jira` register here from
  packages of their own (§2). Discovery *without* that import — an entry point — does not exist yet.
  The developer how-to is [`implementing-checks.md`](implementing-checks.md).
- **Check-authoring surface** — the names a check type written *outside* this
  repository may import ([ADR-0049](adr/0049-the-check-authoring-surface.md)). A
  registered type is code the library does not own, and once it lives behind a tag of
  its own it upgrades on its own schedule — so every name it writes against is
  promised, or the promise covers only the registry it registers *into*. The import
  point is the **package** `little_sister.checks`, never a module beneath it:
  `checks.base` is where most of these live today, which is not what they are.

  ```
  little_sister.checks
      CHECK_TYPES  Check  CheckError  CheckResult  Entry  Measurement  Unit  register
      API_VERSION  require_api
      code  coerce_code  config_markdown  parse_duration  parse_secret_refs  parse_size
      plain
      CHECKS_ASPECT  checks_dirs  load_checks
  little_sister.reasons
      Entry  MAX_SLUG_LENGTH  MAX_SUBJECT_LENGTH  RECORD_TIMESTAMP_KEYS
      ReasonError  clip  derived_slug  normalize  plain  slug
  little_sister.status
      StatusCode  join_path
  little_sister.series
      SeriesRecord
  little_sister.values
      flag  number  real  rows  strict_flag  text
  little_sister.spans
      coarse_span  format_duration  format_span  local_time
  little_sister.transport
      Deadline  DeadlineExceeded  Fault  RemoteError  ask
  little_sister.fetch
      Response  fault_for  fetch  retry_after
  little_sister.process
      Ended  Finished  NotStarted  run
  little_sister.rules
      RULE_WORD  Axis  Matcher  Rule  RuleList
  little_sister.grading
      Graded  GradingBlock  Verdict  worst
  ```

  Three **optional declarations** on `Check` join that surface additively
  ([ADR-0075](adr/0075-a-check-declares-what-it-costs.md)): `expected_cost()` and
  `expected_entries()`, what one run is expected to occupy in worker seconds and what
  the check expects to hold in reason entries; and `expected_record()`, the bytes one
  of its records is expected to need
  ([ADR-0082](adr/0082-a-line-carries-what-it-is-about-and-what-it-read.md)'s limit).
  Each is computed by the type from its own configuration and each is `None` by
  default. What is promised is that a type that overrides one is measured at startup —
  the first two **summed** against the worker ceiling and the entry limit, the third
  **compared**, per check, against `record_limit`, because that limit bounds one record
  rather than a shared ceiling, and raised first to `FAILURE_RECORD_BYTES`, the
  engine's own failure record, where it declared less
  ([ADR-0086](adr/0086-a-check-measures-and-grades.md) decision 5) — and that a type
  that does not is unaffected; never
  that a particular number refuses. The measured counterpart of each stands beside it
  on `/system` — for a record, the heaviest one the last run produced, one the seam
  refused included and marked *refused* where its weight was why
  ([ADR-0093](adr/0093-a-record-the-seam-refuses-costs-its-line.md) decision 6).

  `Check.kept(subject)` joins it the same way
  ([ADR-0113](adr/0113-a-measurement-reads-what-its-check-kept.md)): the measuring
  half's read of what its check kept, with `Check.bind_kept(reader)` for whoever runs
  the check — the engine, and a type's own test. `little_sister.series` is on the list
  for the one name that read hands a type, `SeriesRecord`: what `kept()` answers, and
  what a test builds to bind. Promised of it are what a check reads — `data`,
  `observed_at`, `identity`, `state`, `code`, `texts`, and its `at` — and how it is
  built from them. The store beside it is the engine's, and no part of this surface.

  `Check.units()` and `Check.measure_unit(key)` join it the same way, with `Unit`
  on the list for what the first answers
  ([ADR-0130](adr/0130-a-unit-has-a-period-of-its-own.md), the names
  [ADR-0078](adr/0078-the-unit-is-what-the-engine-releases.md) decision 2 said would
  join additively): a type that reads several things on tempos of their own declares
  them, each with its key, its period, the node it answers for and its cost, and
  reads one at a time; one that declares none is the one-unit check, unchanged.
  Promised are that the engine releases each unit on its own period, grades the
  whole check over the newest reading of every unit after each, writes the unit's
  own path and nothing beside it, and carries the unit's run facts, tolerance,
  retry and cost on the node it answers for (§4.6) — and that a unit's key is a
  stored key, which a plugin may not rename without saying so at the top of its
  release notes.

  `Check.line(form, reading, …)` joins it the same way
  ([ADR-0126](adr/0126-a-line-is-a-template-over-its-record.md) decision 7), with the
  three declarations a type passes to `Check.__init__` beside `measure_defaults` —
  `line_forms`, `line_words`, `line_fields` — `display`, the common field that arrives
  as a constructor keyword, and `Entry.form`. Promised are the notation a template is
  written in (§4.5), that a type's defaults are checked against its declarations when a
  check is built, and that `Check.line` answers the `Entry` the form was rendered into;
  `little_sister.line_template` is not on the list, since a type hands it nothing but
  the mappings it declares. The names a type declares — its forms', its words' and its
  record fields' — are that type's own contract with the deployments that write
  templates against them, and renaming one is a breaking change of its release.

  `Check.verdict(name, reading, …)` and `Check.grading_block(name)` join it the same
  way ([ADR-0131](adr/0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)
  decision 1), with `gradings`, the declaration a type passes to `Check.__init__` beside
  its forms, words and fields; `configured`, the common field the check's own keys
  arrive in; `Entry.grading`; a `RuleList`'s `grading` and a `Rule`'s `graded`; and
  `little_sister.grading` for the four names a type holds of the seam — what one block
  grades with (`Graded`), the block and what reads it (`GradingBlock`), what a grading
  says of a value (`Verdict`, whose `entry()` writes a line of the type's own sentence
  under it) and `worst()`, the verdict of a line two gradings judged. Promised are the
  one spelling of each kind a deployment writes — a map's words folded, a pair passing
  at its level with `<key>_reason` beside it and `<key>: null` switching it off, a set
  of accepted values — that a type's declarations are checked when a check is built and
  a deployment's keys as they are read, and that `Check.line` takes a line's code, its
  grading and the words `reason` and `rule` from the verdict it is handed. A grading's
  name, the keys it is written under and a map's words are that type's stored keys,
  and renaming one is a breaking change of its release.

  `node_defaults` joins it the same way
  ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)), a declaration a type
  passes to `Check.__init__` beside `subnode_defaults`, whose entries take the same keys
  beside their labels and their claim: what a type proposes of the first look of its own
  node and of each name — `chips`, `fold_ok` and `reason_cap`, and under `children:` the
  same and `show_when_quiet` for each child of that node, whatever its name, a level its
  runs name among them. `look` and `subnode_looks` are the common fields a check's file
  arrives in. Promised are those keys, that a value of the wrong kind refuses the
  check's construction naming its entry, and that a key the library does not read is
  named at startup; what each key does is ADR-0128's, a deployment's file and
  `nodes.yaml` taking back what a type proposes.

  `little_sister.spans` is on the list because a check writes a duration into a
  reason line — *"the backup took 2h 7m"* — and one that formatted its own would
  drift from the page it renders onto. It is the writing half of a pair whose
  reading half, `parse_duration`, is already promised above; the two sit in
  different modules because one is config parsing and the other is display, and
  the display half is used by the library's own templates through the `elapsed`
  and `duration` filters, each a name for one of these functions and not a second
  implementation. `parse_size` is the reading half of the other quantity a config
  carries with a unit — a size, `500 GB` or `2 TiB`, parsed into whole bytes, the
  decimal prefixes and the binary ones both and a unit read as written, so that a
  plugin's ceiling on a bucket is typed the way the console shows the bucket and no
  two types read `GB` differently (the plan's *A size with a unit, parsed once*). `format_duration` is the third rendering and answers the
  question the other two do not — how a **configured** interval is written back,
  in the units somebody typed it in (`900` is `15m`) — which is why the copy
  document can state a check's frequency in the same words as the page.
  `local_time` is the one **instant** beside the three spans: a moment in the
  `timezone` and `time_format` of `settings.yaml`, the rendering every page uses
  (the application's own `_format_local` delegates to it), promised so that a
  plugin writing *when* into a line — *the lease lapsed at …* — says it in the
  page's words rather than in `GMT` beside the page's zone. It takes an instant —
  a time with its zone, whichever zone — and refuses a time without one
  ([ADR-0120](adr/0120-every-stored-time-is-an-instant.md) decision 8): a type
  writes no time of its own into a line or a log message, and hands this one what
  its source said with the offset it said it in.

  `little_sister.transport` is on the list because a check that reads a remote service
  has to answer four things before it can report anything — how long one request may
  take, what bounds a run that asks fifty times, what is worth asking again, and what
  a failure *means* — and nothing on this surface used to say a word about any of them,
  so every such check answered all four for itself
  ([ADR-0058](adr/0058-transport-policy-vocabulary.md)). It promises the **policy** and
  no client: `Deadline` (whose `budget(timeout)` clamps a per-request timeout to what
  the run has left, which is what makes `timeout:` a bound — the engine does not bound
  `measure()`, §4.6), `DeadlineExceeded` (outside `RemoteError` on purpose, so a per-item
  handler cannot spell one run-level fact as forty item-level ones), `Fault`
  (*transient* / *answered* / *malformed*, set by status and never by message text),
  `RemoteError` (status plus fault, `fault` required with no default, meant to be
  subclassed) and `ask` (one bounded retry whose backoff the deadline can veto). It has
  **no I/O and no HTTP in it**, which is what lets a check whose transport is a vendor
  SDK wear the same policy; and it deliberately promises **no** mapping from a `Fault`
  to a `StatusCode`, because for an `http` check the endpoint *is* the subject of the
  measurement while for a check reading an API to grade something else it is the
  *instrument*.

  `little_sister.fetch` is the request itself, and it is on the list because the
  vocabulary above is deliberately transport-free: something still has to open the
  socket, and four call sites answering the same HTTP questions differently is what
  this pair replaced. `fetch(url, *, timeout, follow_redirects, …)` makes **one**
  request and returns a `Response` — a fact, for **every** status, `500` included.
  A failure that never reached a status raises instead — a `RemoteError` with
  `Fault.TRANSIENT` and the originating exception attached as `__cause__` — and so
  does a body over the size cap, below. A caller
  that wants this project's reading of a status it considers a failure asks
  `fault_for(status)`: a 5xx is transient, anything else is answered.

  Five things that used to differ per call site are settled there, and each is a
  promise a dependent may rely on:

  - **`timeout` and `follow_redirects` are required.** A request with no timeout is
    the defect this project keeps rediscovering; a redirect policy assumed rather than
    chosen is the one above it — following silently is how a login wall answering `200`
    at the end of a chain reads as health, and refusing to follow is how a `301` reads
    as *alive and moved*. Both are right somewhere, so neither is the default.
  - **One `User-Agent`**, `little-sister/<version>`, because the default
    `Python-urllib` is the string an outbound filter is most likely to answer with a
    `403` nobody can interpret. A caller-supplied header wins, which is how a
    subsystem adds which part of the process is knocking.
  - **Proxies and TLS trust are the environment's**: a default opener otherwise, so
    `http_proxy` / `https_proxy` and the system trust store apply (`SSL_CERT_FILE` /
    `SSL_CERT_DIR` for an internal CA). There is deliberately **no way to switch
    certificate verification off**.
  - **A body is read in bounded chunks**, against `max_bytes` (16 MiB by default) and,
    when a `deadline` is given, against the run's clock. Over the cap is
    `Fault.MALFORMED` — it arrived and cannot be used.
  - **A `deadline` clamps the socket timeout** to what the run has left, and a caller
    with a spent budget gets `DeadlineExceeded` instead of a request issued with a
    non-blocking socket.

  - **A service that answers *not now* is read, not guessed at.** `retry_after(headers)`
    returns the seconds the standard `Retry-After` header asks for — both forms RFC 9110
    allows, delta-seconds and an HTTP-date, with a past date reading as `0.0` and an
    unreadable value as `None`. What to *do* with the number is the caller's:
    `RemoteError` carries it as `retry_after`, and `ask` spends it in place of its own
    backoff **only** while the deadline affords it. Deliberately no `Fault` member for a
    throttle — a throttle is already `TRANSIENT`, and no status identifies one, since a
    service may answer `403` or `429` for it while a bare `403` may equally mean *not
    visible to this credential*. Only a caller that speaks the service's dialect can
    classify it, and a vendor's own reset header is that dialect, not this.

  That last pair is what bounds a **dribbling server**, which `urlopen(timeout=…)` never
  could: its timeout bounds one socket operation, so a byte every four seconds arrives
  forever. The clock is read between chunks, with **`read1`** rather than `read` — a
  `read(n)` blocks until it has all *n* bytes, so the first call would not return until
  the trickle finished and the clock would be consulted only after the overrun it was
  there to prevent. That is not a detail: it is the difference between the bound working
  and merely being described (ADR-0058).

  Three limits of it, stated rather than implied. The clock bites **only when a deadline
  is given**. A caller passing `read_body=False` has no body read to bound, so a deadline
  buys it nothing — which is why **the built-in caller passes none**: the `http` check
  makes a single request and reads no body. And the clock does not reach the **status line and headers**, which
  urllib reads inside its own opener before this module is handed a stream; a server
  trickling *those* is bounded only by the socket timeout per read, which is the residual
  for every caller.

  `little_sister.process` is the process a check starts, `fetch`'s counterpart
  ([ADR-0089](adr/0089-a-process-a-check-starts-ends-with-it.md)). `run(argv, *,
  timeout, deadline=None, max_bytes=…, env=None, cwd=None, send=b"", hang_up=False)`
  runs an **argument vector** — never a command string; a shell command is
  `["/bin/sh", "-c", command]`, said by the caller — in a **session and process group of
  its own** with `/dev/null` for stdin, bounded by `timeout`, which a run's `Deadline`
  clamps to what it has left. It reads **both streams** itself, each kept up to
  `max_bytes` (1 MiB) and the rest read and dropped, and ends **the whole group** —
  TERM, a grace, KILL — at the bound, at the instance's stop, and at a normal end for
  whatever the command left behind. It answers a `Finished`, a fact whatever the status:
  `status`, `stdout`, `stderr`, `ended` (`Ended.EXITED`, `BOUND` or `STOP`), whether
  each stream was cut, and how long it ran. It raises only where the command could not
  start — `NotStarted`, with the `OSError` as its `__cause__`, or with none while the
  instance is stopping — and `DeadlineExceeded` where the run's budget was already
  spent. `send` puts bytes on stdin instead, written while both streams are read and
  followed by the end of stdin; `hang_up=True` holds stdin open for the run, after
  whatever was sent, which an `ssh` client carries to the remote side as the connection
  closing. The library's `command` and `ssh` types start their processes through it, so
  an abandoned run never leaves a process behind, here or on a remote host.

  `little_sister.rules` is what a configuration says about part of what one aspect lists
  — a workflow left out, a fleet judged by limits of its own — read once for every
  package ([ADR-0129](adr/0129-a-rule-list-is-the-librarys-and-a-value-matches-it-exactly.md)).
  A package declares the `Axis`es its rules match along — each a key on a rule, or the
  one axis of an aspect written on the rule itself, `absent` where a value can be
  missing — and, where its rules say more than `ignore:`, the keys that are its own and
  a reader for them. `RuleList` reads the list once, refusing what no rule could mean: a
  rule without a name, or with nothing to match, a key that neither it nor the package
  takes, `unnamed:` on an axis whose values are never absent, `ignore: true` beside a
  key of the package's own. Each `Rule` carries what the package's reader returned. A
  `Matcher` compares a value as the source returned it — a name equal to it, a prefix
  it begins with, a regex matching it whole — and never folds case. `first(**values)`
  is the grading's lookup, the first rule that matches deciding whole; `see(**values)`
  answers the same for the measuring half and keeps the run's tally for
  `report(path, whole=…)`, which writes one `INFO` line per check and rule list naming
  the rules that matched nothing — when that set changes, beside each the rule above it
  that decided a value it matches or else a near miss in case, and never after a run
  that read only part of its scope. `RULE_WORD`, `rule`, is the word a line carries
  where a key of a rule's own judged it: a type whose rules judge declares it in
  `line_words` and hands over the rule's name on those lines alone — or, where it
  grades through the seam, hands the list its block (`grading=`), and the library
  reads what each rule grades and hands the word with the verdict (ADR-0131).

  The subnode-metadata helpers are on that first list rather than under
  `checks.metadata` for exactly the reason above — the module they live in is not the
  promise. `join_path` is there because a **branch** check's `owned_nodes` override
  has to build absolute child paths, and hand-assembling them would make every plugin
  re-derive [ADR-0016](adr/0016-node-addressing.md)'s normalization by guesswork.

  What the surface promises is **names**, not a frozen constructor signature. The
  **common config fields grow** (`order` joined them with
  [ADR-0055](adr/0055-sibling-order.md)), and each becomes a keyword argument
  `from_config` passes on — so a check type must take `**kwargs` and forward them to
  `super().__init__()`. One that spells the fields out stops binding when a field is
  added, and is told so by a `CheckError` naming the file, the type and the keyword.

  **This surface is versioned as an epoch of its own** — `API_VERSION`, currently
  **3**. It bumps when a name above is removed or renamed, or a documented behavior
  changes; adding a name does not bump it, and neither does anything else in a
  release. A package declares the epoch it was built for with `require_api(3)` beside
  its registrations, and a mismatch refuses at startup naming both numbers
  ([ADR-0051](adr/0051-what-startup-refuses.md)). The install-time floor a package
  declares (`little-sister >= x`) keeps a *too old* library out; the epoch catches the
  upgrade the floor cannot see. `tests/fixtures/check_api_v3.txt` snapshots what
  epoch 3 promises, a name joining it in the change that adds the name to the block,
  and the gate requires both: the snapshot to hold every name of the block, and the
  block to still contain all of the snapshot — so a name cannot leave without the epoch
  moving, which is the hole a doc-and-code rename would otherwise slip through. **Epoch 2** opened by removing
  `parse_subnodes`, `resolve_text` and `expand_tokens`: a branch check used to read and
  layer its own `subnodes:` block, and the library reads the whole block now while a
  type only declares (§4.5's node metadata paragraph, ADR-0025). **Epoch 3** opened
  on a *behavior* rather than a name: `run()` became `measure()` and `grade()`
  ([ADR-0086](adr/0086-a-check-measures-and-grades.md)), `Measurement` joined the
  surface and `CheckResult` lost `subject` and `record`, which a measurement now
  carries alone. A type written for v2 cannot be adapted at runtime — it would still
  decide a code from a world it re-reads inside the grading — so it refuses at
  import, which is the supported shape of *the others follow later*.

  A **type name is claimed once**, and stays bare (`type: github`): two packages
  registering one name refuse at startup naming both classes, rather than letting
  import order decide whose code answers for somebody else's configuration
  ([ADR-0051](adr/0051-what-startup-refuses.md)). `/system/installed` lists every registered
  type with the package and version that answers for it, and beside it every
  registering package once — a check type is only one of the seams a package can
  arrive through (a slot filler, an asset, a configuration aspect, a secret
  resolver, an identity provider are the others), and the release that answers for
  it belongs to the installation rather than to the seam. `origins.py` is the single lookup both read, and `paths.py` the single
  rule both print a loaded-from path through (§5.1).

  What each name *does* is documented where it is designed — `CheckResult`'s fields
  and `Check`'s keyword-only common fields in §4.5 and
  [`implementing-checks.md`](implementing-checks.md), the slug vocabulary in
  [ADR-0036](adr/0036-addressable-reasons.md) /
  [ADR-0050](adr/0050-slugs-from-provider-identifiers.md), the typed readers in
  [ADR-0026](adr/0026-reading-values-from-decoded-bags.md), the transport policy and
  the request that wears it in
  [ADR-0058](adr/0058-transport-policy-vocabulary.md) — and that documented
  behavior travels with the name. Adding a name is compatible; removing or renaming
  one is a version bump and a new ADR, the slot rule above for the same reason.
  Deliberately **not** on the list: the engine, the tree, `app`, the templates, and
  every module path below `little_sister.checks`. The block above is
  **machine-read**: `tests/test_public_surface.py` imports every name in it, and for
  the modules that declare `__all__` (`little_sister.checks` and, through it,
  `values`) requires the two lists to be identical. That catches **drift** — a name
  renamed or dropped in a refactor, or exported without being promised. A rename that
  edits the code *and* this block in one commit is caught by the epoch snapshot
  below, which is the one thing a same-commit edit cannot quietly satisfy.
- **Logging** — a *behavior*, and one call beside it. little-sister logs through the
  standard hierarchy and never switches propagation off, and `little_sister.logger`
  configures the **root** logger only when the application has not — no handlers on
  it at import. So a deployment or a plugin that sets up its own logging **before**
  importing `little_sister.app` (the same import-before-app slot as everything else
  here) keeps its handlers *and its level*, and little-sister's own records arrive
  there too; one that sets up none gets the default: the console (stderr) plus a log
  file, whose path is `LOG_FILE` or `var/little-sister.log`, at the levels `LOG_LEVEL`
  names, the root at **INFO** where it names none. Both variables belong to that
  default and are consulted nowhere else — against an application that configured its
  own logging, `LOG_LEVEL` does nothing, because the levels are then that
  application's to choose — and both are read **after `.env`**, whatever a process
  imports first: `logger.py` imports the module that reads the file into the
  environment before it reads either, and a value in the process's own environment
  stands over the file's, as for every variable. A plugin imports nothing from
  `little_sister.logger` — it calls `logging.getLogger(__name__)` like any Python
  library. That module and its `logger` object are **not** contract — what is
  promised is that the records reach whoever owns the root logger, the list
  `LOG_LEVEL` takes, and the call a package declares a noise cap with, both below
  ([ADR-0049](adr/0049-the-check-authoring-surface.md) decision 4,
  [ADR-0121](adr/0121-a-noise-cap-is-declared-and-log-level-has-the-last-word.md)).
  `tests/test_logger.py` and `tests/test_noise.py` hold it, because a library that
  quietly reconfigures logging is only noticed when somebody's log file is empty.
  - **The default's lines are stamped in the configured `timezone`, each with the
    offset in force** — `2026-10-04 13:02:35,893 +0200`, on stderr and in the file
    ([ADR-0120](adr/0120-every-stored-time-is-an-instant.md) decision 9) — so a line
    of the log and a time on a page are one clock, and the offset says which. The
    shape is the log's own, not `time_format` (§7). `config.py` hands the zone to
    `logger.stamp_in` the moment it has read it, and the stamp is taken where a line
    is written (`_Stamped.formatTime`), not where it was logged: the file is in that
    zone from its first line, what the import logged included. On stderr a line
    written before the zone was read — about a settings file that is absent or cannot
    be read, or about `LOG_LEVEL` — carries the machine's clock, with its offset like
    every line. The stamp is the default's, as the handlers are: an application that
    configured logging keeps its own, and gunicorn's lines keep the machine's clock.
    So `open_log_file()` compares the two clocks by what they show, hour by hour
    through the year ahead (`_HOURS_AHEAD`), and logs one WARNING where they part —
    naming both offsets where they differ at the start, and otherwise the day from
    which they do — and nothing where they agree throughout. It is a line in the log
    and no note on `/little-sister`, which would stand at WARN for the life of the
    process on a machine whose zone is another on purpose.
  - **INFO rather than DEBUG, because nothing here logs below it.** A DEBUG root
    collects no line the library writes and every line its dependencies write — a
    deployment carrying an AWS check type was two thirds `botocore` request detail.
    A deployment that wants that detail asks for it with `LOG_LEVEL=DEBUG`, which
    lowers the root and lifts no cap: the declared caps are what keeps such a
    session readable, and a capped logger is asked for by name.
  - **`LOG_LEVEL` is a list, and names loggers beside the level** —
    `LOG_LEVEL=INFO,botocore.credentials=DEBUG`, separated by commas
    ([ADR-0121](adr/0121-a-noise-cap-is-declared-and-log-level-has-the-last-word.md)
    decision 5). The entry with no `=` is the root's level, which is all the variable
    was. An entry `name=LEVEL` is that logger's level — any logger and any level, the
    library's own loggers and `ERROR` included, since the log is the deployment's —
    and it speaks for its name **and for every name beneath it**, down to the next
    name the variable has an entry for: a level that stands on a logger there is
    taken off, whoever set it, so that the nearest entry at or above a logger's name
    is that logger's level. A named entry is set twice with that reach: with the
    default, so that it holds from the first line, and again where the application
    is imported and the caps are set, after the code of the slot, over which it then
    stands; between the two the later `setLevel` stands, as it does anywhere. The
    bare level is set once, with the default. A level is written by its name in
    `logging`, in either case, and `NOTSET` names none; a logger's name is taken as
    it is written; spaces around an entry and around its `=` are dropped, an empty
    entry is nothing, and what follows the first `=` is the level; a later entry for
    a name replaces an earlier one, the bare level too; and the root has no name in
    the variable, so `root=DEBUG` is an entry that cannot be read. Such an entry is
    skipped and said in the log, a line for each — written before the variable's
    levels are set, so that no entry takes out the line about another — and the rest
    of the variable stands.
  - **A package declares the noise caps of the dependencies it brings, and sets no
    level** — `little_sister.noise.cap(logger, level, hides=…)`, in the
    import-before-app slot beside its other registrations
    ([ADR-0121](adr/0121-a-noise-cap-is-declared-and-log-level-has-the-last-word.md)
    decisions 1 to 4). The call records a **row** — the logger's name, the level, the
    package, inferred from the call site as a resolver's is, and what the cap hides —
    and touches no logger. What a package may declare is bounded: a dependency's
    logger, never the root and never `little_sister` or a logger beneath it;
    `logging.INFO` or `logging.WARNING`, so that a package takes a dependency's
    `DEBUG` and `INFO` lines out of a log and nothing above them; `hides`, which
    finishes the sentence *it hides …* for a reader deciding whether to ask for the
    lines back; and in the slot — after the application was imported a declaration
    is refused, unless it repeats a row as it stands. One outside these is a warning,
    a skip and a line on `/little-sister/startup`, and never an exception. The
    library's own rows are those for its own dependencies, and that is one:
    `markdown_it` at `INFO`.

    **The rows are set once, where the application is imported** — `noise.settle()`,
    called there beside `announce_aspects()` — and a row is set on its logger unless
    one of four things holds, asked in this order: the application configured
    logging itself; `LOG_LEVEL` names the logger or one above it; a level stands on
    the logger, or on one above it short of the root, that no row set — the code of
    the slot set it, or the dependency itself; or the row would take no line away,
    the logger being at its level already or above it without it. So nothing is set
    where a row is declared, and the order of a deployment's imports decides nothing;
    a cap takes lines away and adds none; where two rows reach one logger the higher
    level stands, whichever was declared first; and what code sets after the
    application was imported, it sets, and no row follows it.

    **A deployment that wants a dependency quiet which no package declared** sets
    that logger's level by name in the slot, as it always could —
    `logging.getLogger("urllib3").setLevel(logging.WARNING)` adds no handler, so it
    leaves the default intact, and it stands against every row — or declares a row
    with the same call, which puts what the cap hides on the page. It has any capped
    logger's lines back by name: `LOG_LEVEL=INFO,botocore.credentials=DEBUG`, in
    `.env` or in the environment, and a restart.
  - **The instance says what its log leaves out**
    ([ADR-0121](adr/0121-a-noise-cap-is-declared-and-log-level-has-the-last-word.md)
    decision 7). `/system/installed` has a *Logging* section: whether the default is
    in charge, the root's level with where it comes from, and every logger that
    carries a level of its own with where *that* comes from — a row, with each
    package that declared one and what it hides; an entry of `LOG_LEVEL`; or
    neither, which is the application's code or the dependency itself. Then every
    row that was not set, with the first of the four reasons that held; every level
    an entry took off, with the logger it stood on; and every entry of the variable
    that could not be read. The levels are read off the loggers at the request
    (`noise.report()`), so the page says what stands and not what startup left. The
    package inventory names a package's caps beside its other registrations. And
    the log says it where it begins: setting the rows writes an `INFO` line for each
    row that was set, which names the entry that shows its lines — a log that
    leaves lines out says which. The entry is the logger at the level it is at
    without the row, `botocore.credentials=INFO` under the default's root: what the
    row hid comes back and nothing below it, where `DEBUG` would be more than was
    hidden, and on a wide logger a wire trace. The page prints the same entry as a
    line to copy, after the variable as it was read (`Entries.written()`), so that
    pasting it changes one thing. A row that was not set leaves nothing out, so the
    log says nothing of it — not at a start with nothing to cap, and not in the log
    of an application that configured logging itself — and the page says why it was
    not. A deployment that took the library's own lines out with the variable reads
    the set rows on the page as well.
- **Secret references** — `little_sister.secrets`: `resolve(reference)` /
  `register_resolver(scheme, resolver, *, replace=False)` / `resolve_setting(value)`
  (an app setting
  whose value may be a reference), the reference syntax itself (`scheme://address`,
  with no bare-name form), and `Check.resolve_secret` (resolve at construction,
  pin on failure — [ADR-0023](adr/0023-secret-references.md)). A deployment registers
  its resolvers in the same import-before-app slot as its check types. A scheme is
  claimed **once**: a second claim from a different package raises
  `SchemeConflictError` at startup naming both, and `replace=True` is how a caller
  that means to displace another package's scheme says so
  ([ADR-0064](adr/0064-the-resolver-is-a-registration.md)).
- **Identity** — `little_sister.identity`: `use(name, provider, default=…)`,
  `use_system_admin(reference=… | password=…)`, `choose_at_login()` /
  `door_chooser()` and `little_sister.local_login.use_local()` for the built-in
  list, the provider protocol (`identify` /
  `challenge` required, `login_page` / `submit_login` / `complete_login` /
  `end_session` optional), the `Identity` type, `current_user()` / `signed_in()`,
  `sign_in(Identity)` / `sign_out()` / `session_door()` and the route shape a door
  gets (`/login/<door>`, `/auth/callback/<door>`) —
  [ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md).
  Registered in the same import-before-app slot as the rest. It is on this list and
  **not** inside the check-authoring block above, and the difference is the reason
  the epoch does not move for it: a check type is third-party and numerous and
  upgrades on its own schedule behind an epoch, while a provider lives in a
  deployment's own code or in a package that pins this library, so ordinary semver
  carries it — the same footing `register_resolver` is on.
- **Environment contract** — how a deployment points the library at its own config
  in the working directory: `LITTLE_SISTER_CONFIG_DIR` (the configuration path-list —
  checks, node metadata, settings and users,
  [ADR-0031](adr/0031-deployment-config-directory.md); a user list kept outside that
  tree gets a configuration root of its own, named first, which is the only way to pin
  one exact file — [ADR-0046](adr/0046-user-list-from-the-configuration-roots.md)),
  `LITTLE_SISTER_SCRIPTS_DIR` (metrics-script overrides,
  [ADR-0021](adr/0021-script-resolution.md)), `LITTLE_SISTER_CONFIG` (a single
  settings file, bypassing layering — not redundant the way the user-list override
  was, because settings merge per key),
  `LITTLE_SISTER_API_TOKENS` (JSON-API bearer tokens), and `LITTLE_SISTER_ENGINE`
  (a server that runs no engine; an import never starts one, so tests need nothing). The retired `LITTLE_SISTER_USERS` is part of the
  contract too, in the negative: it is never honored, and a startup that finds it set
  **refuses**, naming the move. Defaults and formats are in §7.

A version bump is *for* changes to these; everything else — internal modules,
template markup, exact HTML — may move between releases.

**What is not on this list, a plugin may not import.** That is the whole force of
the section for a package released on its own line: it upgrades on its own schedule,
so every name it writes against is promised or it is borrowing something that can be
renamed under it without a word in any changelog. Two the extractions actually
tripped on: `little_sister.logger`'s `logger` object is **not** here (a plugin calls
`logging.getLogger(__name__)`; what is promised is that the records still arrive),
and neither is any module path beneath `little_sister.checks`. One dependency on a
name that is *not* here is known and deliberate: little-sister-jira builds its link
back to a node with `url_for("status", …)`, so it assumes the **endpoint name** of a
view this section explicitly does not promise. It is left that way because the
alternative is a plugin assembling our URLs by hand, and it is pinned by a test in
that repository rather than by a promise here — which is the shape of the bargain
whenever a plugin decides to reach past this list. `/system/installed` lists every registered
package with the version answering for it, which is where a mismatch becomes
visible.
