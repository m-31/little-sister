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
│   ├── checks/          # check configs (*.yaml), plus examples/ and a README
│   ├── csp.yaml         # Content-Security-Policy sources (ADR-0048) — example, inert
│   ├── settings.yaml    # general options (timezone, time_format)
│   ├── links.yaml       # optional: curated links (or links/ with icon files)
│   ├── nodes.yaml       # optional: node metadata, keyed by node path
│   └── users.yaml       # login list, or users/{users.yaml, avatars/} (gitignored)
├── src/little_sister/
│   ├── app.py           # Flask app: routing, login, .env load, engine start
│   ├── api.py           # JSON serialization for backend mode (ADR-0080)
│   ├── status.py        # Status / StatusCode domain model + roll-up
│   ├── codes.py         # the status vocabulary, a leaf module nothing imports from
│   ├── reasons.py       # addressable reasons: a node's reason list as keyed entries (ADR-0036)
│   ├── tree.py          # the shared, thread-safe StatusTree, event log, history
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
│   ├── maintenance.py   # the maintenance side-table as a state file (its shape)
│   ├── state.py         # the state layer: var/state/, the writer, the two failure lines (ADR-0071)
│   ├── keeper.py        # the seam that carries var/state/ off the machine (ADR-0071 §5)
│   ├── self_report.py   # what the instance says about itself: contributors → /little-sister (ADR-0072)
│   ├── readiness.py     # has this instance come up, and what it can see (ADR-0073)
│   ├── links.py         # the `links` aspect: curated links, re-read on change
│   ├── link_probe.py    # reachability for that page: an open starts a pass
│   ├── users.py         # the `users` aspect: login list + avatar resolution
│   ├── identity.py      # who a request is from, and the one login gate (ADR-0068)
│   ├── local_login.py   # the built-in login list, as a provider like any other (ADR-0069)
│   ├── system_admin.py  # the one door the library ships, and it is not a provider's (ADR-0069)
│   ├── origins.py       # where an import package came from: distribution, version, file
│   ├── watch_lines.py   # what /about's hero says: the pools a render draws from
│   ├── icons.py         # icon names, the pack registry, where the bytes are
│   ├── icon_pack/       # the built-in marks (our own drawn glyphs) + manifest
│   ├── nodes.py         # the `nodes` aspect's metadata + startup consistency pass
│   ├── render.py        # safe server-side Markdown → HTML (markdown-it-py)
│   ├── titles.py        # a title that repeats the name, or has no word in it
│   ├── spans.py         # how a span of time is written, on every surface
│   ├── dashboard_layout.py  # stable, width-priced track allocation for the dashboard (ADR-0056)
│   ├── paths.py         # a loaded-from path, drawn against a root the reader has
│   ├── copy_status.py   # the canonical incident hand-off: the tree's outline,
│   │                    # one node's and one reason's, from one formatter
│   ├── copy_action.py   # the built-in copy chip, in the reason.actions slot
│   ├── slots.py         # template slots a dependent package fills (ADR-0034)
│   │                    # and the assets it ships for them (ADR-0037)
│   ├── actions.py       # the declarative action list, config/actions.yaml (ADR-0038)
│   ├── csp.py           # the assembled Content-Security-Policy (ADR-0048)
│   ├── logger.py        # root logging, if nobody else set it up (stderr + file)
│   ├── users.example.yaml  # sample login list — the real one is a config aspect
│   ├── templates/       # Jinja2 pages
│   └── static/          # CSS, the page JS (poll, popover, reason overflow, rail,
│                        #   submit-on-change), favicons, webmanifest
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
  through ([ADR-0014](adr/0014-maintenance-persistence.md)), and the event log,
  written at most once per interval and at the stop's one save — read back at
  startup. The directory has **one writer**, the process that holds its lease
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
- `timestamp: str | None` — the **observation time** (ISO-8601): `None` until the
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
- `about: str` — **subject** metadata: what the node *is* (location, kind, context),
  distinct from `description` (what its check does); Markdown, seeded at startup from
  `nodes.yaml` / the owning check ([ADR-0012](adr/0012-node-metadata.md)).
- `title: str` — a **short display label**, briefer than `about`; same sources and
  seeding ([ADR-0017](adr/0017-node-title.md)).
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
`(path, slug)` side table — its own **pin**, so one line of a node can be silenced
without silencing the node.

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
they are *silenced* leave the parent `MAINTENANCE`, children that merely have not
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

### 4.4 Status tree, event log & history — `tree.py`
The single in-memory state everything hangs off (ADR-0001/0002). `StatusTree`
holds one root `Status` and a bounded `deque` of `Event`s behind one `RLock`.

- `upsert(path, code, reason, *, description=None, frequency_seconds=None,
  stale_after=None, config=None)` — create-or-update a node by absolute path (intermediate nodes
  auto-created), store the inherited metadata, and append a transition `Event`
  **only when the node's own code changes**. `config` is static display metadata
  (the check's parameters, [ADR-0013](adr/0013-check-config-on-node.md)) — stored
  when given, never a transition. A node **in maintenance** is written like any
  other — the pin is derived at snapshot time, not stamped into the tree, so a
  silenced node can still say what it is silencing and clearing a pin restores the
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
- `set_run_facts(path, *, wall_seconds, next_run_at)` — record the owning check's
  **last-run facts** for a mount ([ADR-0044](adr/0044-run-facts-on-the-node.md)):
  the run's wall time, and the engine's **armed next slot** already projected onto
  the wall clock. A registry beside the mount counts, resolved by `snapshot()`
  onto `StatusSnapshot.run` under the same sole-check condition as the inherited
  stamp — the sole mount and the unwritten ancestors above it carry the facts, a
  mount two checks share and its ancestors carry none, and a leaf *below* a
  branch mount stays bare: its next update belongs to the node where the check is
  named. `next_run_at` must come from the schedule, never `timestamp +
  frequency` — the budgeted retry
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
  ([ADR-0036](adr/0036-addressable-reasons.md)). It writes no status and emits no
  event: the pin lives in the side-table under `(path, slug)` and the snapshot joins
  it, so the check's next run cannot destroy it and nothing derived is written into
  the tree ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 3). A slug the
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
  silenced node able to say *what* it is silencing, and clearing able to restore
  anything at all. Setting an **already-pinned** node is an *edit*: it keeps the entry's
  `created_at` / `created_by` and replaces the rest, so extending a window never
  passes through an unpinned state. Both record events — including the edit, which is
  `MAINTENANCE → MAINTENANCE` and so invisible to the code test; a re-submit changing
  neither reason nor expiry emits nothing. `expected_set_at` is the **compare-and-set
  token** (the `set_at` the caller believes it is replacing, `""` for *"nothing is
  pinned"*, `None` for unguarded): on a mismatch **nothing is written** and the returned
  `MaintenanceWrite` carries `refused` plus the entry that was actually there. The
  comparison is exact — one process, one lock. `MaintenanceEntry.reason` is the
  admin-authored raw Markdown source shown on every maintenance surface (§4.7).
  Maintenance is held in a **side-table**
  (`path → MaintenanceEntry`, i.e. `{reason, set_at, expires_at, set_by, created_at,
  created_by}`) kept in sync with each node's `maintenance` bool and
  **written through** to `var/state/maintenance.json` via an injected
  `MaintenanceStore`, which knows the file's shape and hands the write to the state
  layer (§4.8; [ADR-0014](adr/0014-maintenance-persistence.md),
  [ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)); an entry
  read without the two creation fields defaults them to the set values, so a file
  written before that amendment loads unchanged. `restore_maintenance` replays it
  post-fork at startup (dropping expired); `reap_uncovered` drops pins no check root
  covers (segment-wise — the `status.on_same_line` predicate shared with ADR-0015);
  and `sweep_expired`, run each scheduler tick, clears entries past their window as a
  real transition.
- **The event log is a state file too.** `events_payload()` copies the log under the
  lock and serializes it outside; `restore_events(events)` puts a file's log back at
  startup, before anything has written, keeping the bound. `Event.to_dict()` /
  `from_dict()` carry the codes by name, and `events_from_payload()` refuses a file
  of a shape it does not know whole rather than half-reading it — the layer then
  reports the file (§4.8). A restored log makes `/events` and every node's history
  start where the last process left off. **A restart is no transition**
  ([ADR-0094](adr/0094-a-restart-is-no-transition.md)): `restore_events` keeps what the
  log last recorded per path — the node's last reading, passing over an admin's pin
  set, and what it last showed — and a node's **first** write in this process is
  compared with that rather than with the `UNDEFINED` a restart leaves, so the same
  reading keeps its period and any other one, `UNDEFINED` included, changes from the
  old code; the pins' replay compares with what the log last showed, and a pin whose
  period the log holds writes nothing. The instance's own node records the gap
  instead, once: `close_unobserved(path, since, reason)` ends `/little-sister`'s
  restored period with an event to `UNDEFINED`, dated when the old process was last
  alive — `last_alive`, the later of the `stopped_at` the stop's one save writes beside
  the events (`note_stop`, §4.6; `stopped_at_of` reads it back) and the lease's
  `previous_beat` (§4.8) — so its first beat is a transition from there and its
  history reads the time nothing watched.
- **Events under a suppression are recorded and marked.** Because a pinned node keeps
  being written, its transitions still happen, and the log keeps all of them: an
  `Event` carries `suppressed_by`, the **name of the contribution rule** that kept
  that transition from reaching anybody, empty when nothing did. One sentence defines
  it — *an unmarked event is one that alarmed; a marked one is one that didn't* — and
  it is a name rather than a boolean because the aggregation clamp, the dependency
  shield and the damping counter each withhold a transition too, and four booleans
  would be four spellings of one property
  ([ADR-0032](adr/0032-status-contribution-boundary.md) rules 2 and 5). Today the
  vocabulary has one member, `tree.MAINTENANCE_RULE`, carried by both grains of the
  same rule: a pin on the node, and a pin on every one of its entries so that nothing
  is left reporting. A node whose *check* reported `MAINTENANCE` is not marked —
  nothing suppressed it, it said so itself — and neither is a partly pinned node,
  whose unpinned entries still alarm. An admin's own set / clear / edit is never
  marked either: that transition **is** the change, and it is what everyone sees.
  Before the keystone none of this could exist — a pinned node was not written, so
  there was no transition to mark — and recording them is what makes *did it break
  during the window?* answerable
  ([ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)).
- `history(path)` — the node's **status history** as `StatusPeriod`s (code, since,
  until, reason), derived from the event log; the current period's `until` is the
  last check time. **Marked transitions do not start a period**: history answers
  *what did this node show over time*, and a check that went red underneath a pin did
  not change what the node showed — it stayed in maintenance. Counting them would
  chop one window into a dozen phantom `ERROR` periods no surface ever displayed.
  They stay in the event log, which is where the other question is answered.
- **A node says how often it changed its mind lately** — `changes`, its own status
  transitions in the last hour between `OK`, `WARN` and `ERROR`, derived from the event
  log at snapshot time and stored nowhere
  ([ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md) decision 7). A first
  reading is not a change and is not counted; a transition a rule kept from alarming
  **is**, which is where this differs from the node's history — that answers *what did
  this node show*, this answers *how is the subject behaving*. It is the one number
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
  the envelope; what the parent then accumulates is `UNDEFINED`, which the roll-up skips.
  For a pin and an unreported node that is the node's own code and nothing had to be
  said — the roll-up reads the difference between those two — while a **shielded** node
  holds a ranked reading of its own and has to contribute `UNDEFINED` explicitly
  ([ADR-0084](adr/0084-a-check-may-be-reached-through-another.md) decision 3). A rule
  that *transforms* one puts a real code there
  instead, and today exactly one does: a **damping counter** holds a worse reading back
  until it has been read `escalate_after` times in a row, and the node publishes what it
  published before while it waits. The counter is advanced on the **reading**, in
  `upsert`, and kept in a side-table beside the pins; the snapshot reads it and renders
  the hold (`1 of 3 to escalate`). Staleness goes past it, because a stale node gives
  its parent its degraded **raw** code and never anything derived.
- The snapshot derives a node's **own status** rather than copying its stored code
  ([ADR-0036](adr/0036-addressable-reasons.md);
  [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md); the
  [ADR-0032](adr/0032-status-contribution-boundary.md)): a **pin** on the
  node presents `MAINTENANCE`, and a node's member entries are **virtual children** —
  each unsuppressed one contributes its **own code** where the check declared one
  ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) and the reported status
  where it did not, a suppressed one contributes nothing (`UNDEFINED` contributions
  are ignored, as everywhere), and a node with nothing counted presents
  `MAINTENANCE` when something was silenced and `UNDEFINED` when nothing has
  reported — so pinning the one red line of an otherwise healthy coded set turns
  the node `OK`. Prose and reason-less nodes stay outside the entry rule. What the check actually said survives beside the
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
  aggregated — no min or max — and `stale` / `age_seconds` deliberately keep measuring
  the node's **own** stamp, so an inherited time is a display value and not an
  observation of that node. Resolution is relative to the snapshot's own subtree, and
  nothing derived is stored on the nodes, so a topology change can never leave a stale
  roll-up behind.
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

`grade` returns a `CheckResult` — a **recursive value** (`code`, `reason`, and
optional `name` / `description` / `config` / `children`). `reason` is **keyed**
([ADR-0036](adr/0036-addressable-reasons.md)): a string, a list of strings, a
`{slug: text}` mapping, `(slug, text)` pairs or a list of `Entry` values,
normalized in `__post_init__` into `reason_entries`. A mapping or a pairs list
declares its entries **members** — an admin can silence one of them — and a list
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
then in-flight, then healthy-and-idle, or `reason_cap` folds the failures below
the chevron. **An entry may also carry what it is about and what was read.** `Entry.subject` is
the source's identifier for the entity the line stands for — a repository, a host —
which several lines commonly share and which no slug can be split back into, and
which is deliberately not an address: nothing is pinned by subject, because a pin
holds an identifier and only a line has one. `Entry.data` is the **record**, the
material a check read and used to throw away once it had written its sentence;
`text` is untouched, so nothing on any surface moves until something renders it,
and the node's own page shows it as a list of dotted names and values.

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
([ADR-0082](adr/0082-a-line-carries-what-it-is-about-and-what-it-read.md) and its
update).

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
`measures`, `reading_cap`; `parse_duration` accepts `15m` / `2h` / `1w` / seconds,
lowercase units only) and a `type`→class registry.
Config blocks are read with **`values.py`** ([ADR-0026](adr/0026-reading-values-from-decoded-bags.md)):
`values.text` / `number` / `real` / `flag` / `rows` take a decoded YAML (or JSON)
bag plus a path of keys and always return the declared type — absent yields the
default, `required=True` makes absence a `CheckError`, and a present-but-uncoercible
value always raises rather than falling back to a plausible number. `CheckError`
itself lives in `errors.py` so `values` stays importable from `config.py` /
`maintenance.py` without pulling in the check registry.
Built-ins:

- **`http`** — GET a URL; OK when the status is in `expected_status`. A `3xx` is
  followed or reported per `follow_redirects` (default: followed); the body is
  never read. Requests go through `little_sister.fetch` (ADR-0058), as every
  request in the library does.
- **`file`** — heartbeat: OK while a file's mtime is within `max_age` (default 20m),
  else `stale_code`. Relative `file` paths resolve under the executing user's `$HOME`.
- **`command`** — run a shell string or argv; OK on exit 0; reason = captured
  `stdout` / `stderr` / `both`, shortened to `max_chars` from `tail` / `head`
  (`little_sister.process`, per-check timeout).
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
`volume_name` — is the **public** API the parsing checks share (`little_sister.process`;
the external `ssh` binary). The five checks:

- **`ssh-connect`** — connectivity: connect and run a trivial remote `true`; OK if
  reachable, ERROR if not, **WARN** on the non-PQ advisory.
- **`ssh-command`** — run a remote command (the over-SSH twin of `command`): OK on
  exit 0, reason = the captured output (`capture` / `max_chars` / `keep`), **WARN**
  on the advisory.
- **`ssh-script`** — pipe a local `script` (via `interpreter`, default `bash`) to
  the host and report its output, like `ssh-command`; the base the two metrics
  checks specialize (they parse the output instead of returning it).
- **`host-metrics`** — read basic system parameters from a host over SSH and report a
  **branch** rooted at the **host node** (the check's `path` targets the
  host, e.g. `/system/alpha`). Because ssh is only the *helper* that fetches the
  data, it is a **peer leaf**, not the metrics' parent: the host gets an `ssh`
  child (OK, **WARN** on the non-PQ advisory, ERROR on a failed connection)
  alongside a `disk` / `memory` / `cpu` / `load` leaf — all siblings, each metric
  carrying its number (a percentage) even when OK, graded by configurable
  `thresholds`. The host node itself is a neutral container (its status rolls up
  from the leaves), so other checks (e.g. a `file` heartbeat) can sit beside them.
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
  exposed, and one `drive<bay>` per populated bay, in °C, graded by `warn`/`error`
  thresholds) and `smart` (one `drive<bay>` per bay: `GOOD`→OK, `Warning`→WARN,
  else ERROR). Empty bays and absent sensors are omitted. It carries no
  description, so it shares the host node without overwriting `host-metrics`'; the
  non-PQ warning it leaves to `host-metrics` / `ssh-connect` on that node.
- **`macos-memory`** — macOS memory health over SSH: pipes
  `scripts/memory-macos.sh` and reports the early-warning signals that RAM
  trouble is *building*, as leaves **on the host node, beside the
  `host-metrics` data** — `pressure` (the kernel's VM memory-pressure level:
  normal→OK, warning→WARN, critical→ERROR), `swap` (MB in use), `compressor`
  (memory occupied by the compressor as % of RAM — compressor exhaustion is
  the kernel-panic signature on a small-RAM Mac; `host-metrics` folds those
  pages into its one "used" number and can't see them specifically) and an
  optional `processes` branch (RSS per watched command-line pattern, summed
  over matches and graded per process, plus the oldest match's uptime — a
  slow leak shows as monotonic growth, a scheduled restart as uptime
  resetting).
  A watched process that isn't running is **OK**: the aspect watches memory,
  not liveness (that's a `file` heartbeat's / `ssh-command`'s job). Like the
  other macOS script it stays bash-3.2-clean, guards on Darwin, and only
  measures; the grading lives in the check. It carries no description, so it
  shares the host node without overwriting `host-metrics`'.

The family lives in the `checks/ssh/` package: `connection.py` (`SshConnection`),
`metrics.py` (the pure toolkit), `connect.py` / `command.py` / `script.py`, and the
domain checks `host_metrics.py` / `qnap_metrics.py` / `macos_memory.py` — over
`SshCheckBase` (the shared connection block) and `SshScriptCheck` (adds script
piping). Several checks can target the **same host node** (e.g. `nexus` runs both
`host-metrics` and `qnap-metrics`): the engine leaves a node's description
untouched when a contributing check has none, so they don't clobber each other.

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
remembered. `/system` shows both halves: `secret <scheme>://` on the registering
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
directory — `config/nodes.yaml` in each root of the path-list, where a later root
wins **per field** over an earlier one and the override is logged with both files
named ([ADR-0031](adr/0031-deployment-config-directory.md)). It carries both fields
per path (`path: {about: …, title: …}`; a bare string is `about`). For the **subnodes a
branch check emits** the lattice grows two rungs
([ADR-0025](adr/0025-check-provided-subnode-metadata.md)): `nodes.yaml` **>** the
deployment's `subnodes:` block in the check's own YAML — **read by the library**, like
the `show_when_quiet` beside it — **>** what the check *type* **declared**
(`subnode_defaults`, `name → {title, about}`) **>** the `about` / `title` on the child
`CheckResult` **>** empty. The middle two resolve **per field** in `Check.__init__`, once:
the configured text when it says something, the declared default otherwise, with
`{default}` substituted so a deployment can extend rather than replace and `{token}`s
(`label_tokens`) expanded by a plain replace that leaves Markdown intact; the engine
then writes the resolved text per subnode *name*, at any depth, exactly as it does the
flag. The result's own label is read only where that map is silent for the name — the
**dynamically named** child a run discovered (`host-metrics`' per-volume leaves), which
no declaration could have anticipated. Unlike the write-through
`description` / `config`, these **fill an empty field only**, and because the startup
seed runs before the engine's first tick a `nodes.yaml` label is already present and
wins; a filled label then freezes at first fill (stable identity — text that
changes each run belongs in `reason`), which is also what pins a `{token}` to a
construction-time fact. This carries **type-inherent** subnode identity —
`host-metrics` declares a per-aspect `about` for `ssh` / `disk` / `memory` / `cpu` /
`load` — so a reusable branch check explains its leaves in every deployment without
per-node `nodes.yaml` copy-paste, and a deployment retunes one of them, for **any**
installed branch type, without that type carrying a line of code for it. A
**branch** check gives each leaf its own `description` through a `descriptions:` map
keyed by leaf name, leaving the shared container's description empty. A startup
**consistency pass** warns for an `about` path no check covers (the ADR-0014
check-root coverage test) and info-logs a container that has checks but no `about`.
`about`, `title`, the leaf descriptions and the `reasons` are Markdown, rendered
server-side ([ADR-0018](adr/0018-markdown-rendering.md), §4.7). `title` follows the node name (ellipsed) on a card, and the
`status / …` breadcrumb in the **page header** of both a branch view and a leaf's
detail page (whose body still shows the name + description) ([ADR-0017](adr/0017-node-title.md)).
A node also carries an **`order`** — its declared rank among its siblings
([ADR-0055](adr/0055-sibling-order.md)), resolved by the same per-field precedence as
the labels: a `nodes.yaml` `order:` **>** an inline `order:` on the check **>** the
`order` on the `CheckResult` it returns **>** unstated. Unlike the labels it is read on
a result's **root** as well as its children, and unlike them a stated `0` is a real
declaration rather than silence — which is what lets a deployment overrule a check's
rank by naming the default value, so the node's field is nullable while the snapshot's
is a plain `int`. A zeroed node sorts **with the unranked**, ahead of every positive
rank; that is a rank, not a request for alphabetical, and returning a whole ranked set
to the alphabet takes an `order: 0` per sibling.

And a node may carry **`show_when_quiet`** — *this node's quiet lines are still
information* ([ADR-0063](adr/0063-declining-the-density-trade.md)) — for the
**inventory**-shaped aspect whose list is read precisely because everything is fine,
and which the dense view would otherwise show only while a sibling was failing. It
rides the labels' lattice **exactly**, which is what makes the `subnodes:` block one
story: a `nodes.yaml` `show_when_quiet:` **>** the deployment's `subnodes:` block in
the check's own YAML — **read by the library**, not by the check: `_parse_common`
parses it for every type, so a deployment can state it for any installed branch check
without that check changing — **>** the type's **declared default**, `show_when_quiet`
in the same `subnode_defaults` entry that declares that subnode's labels, so an aspect
that is a roster by construction is declared once in a package rather than once per
node path in every installation **>** the value on a child `CheckResult`, the
dynamic-child channel **>** unstated. `Check.__init__` merges the two declarations
into one per-name map — the same place and the same moment the labels resolve — and
the engine applies that map per subnode *name*, at any depth. The
result's copy is root-ignored like `about` / `title`, because the root's own source
is the inline `show_when_quiet:` key in the check's YAML. It is a **tri-state** for
the reason `order` is nullable, sharpened: a stated `false` is a deployment declining
a claim a check type ships for every installation, so it must occupy the field where
a check's `true` cannot fill over it, and it stays `bool | None` all the way onto the
snapshot. A non-boolean fails the load (`values.strict_flag`, so `"false"` in quotes
cannot read as *on*) — for the inline key and for the block alike, on every type,
since the block's shape is the library's to validate. What it does is painting and
nothing else — §4.4 — and it is deliberately **not** in the JSON envelope, which is
unchanged.

**A title that only repeats the name is not drawn** (`titles.py`). Where a check has
nothing better to say it hands back the name again with a capital letter, and a row of
severity-band chips then reads `critical Critical`, `medium Medium` — twice the width,
no second fact. One predicate answers for every surface: the grid's leaf chips, box and
card head lines and the heartbeat strip, the page band beside the breadcrumb, the
inspection popover, the `/maintenance` pin table and the `/copy` hand-off. It folds
**case**, `_` / `-` / a space, and runs of whitespace — so `pull_requests` and
*Pull requests* are one string, and so are `code_scanning_alerts` and
*Code-scanning alerts* — and nothing else: a title that adds anything at all survives.

**And a title with no word in it cannot stand in for the name**
([ADR-0061](adr/0061-decoration-is-not-a-label.md)). Most of those surfaces draw the
name and the title side by side, so the rule above is all they need. Two draw the
title *instead of* the name — the `/copy` hand-off and the inspection popover's card —
and that is right while a title is a **word**: a node titled *Cluster A* is better
named that way in a pasted document. It stops being right for a **glyph**: a severity
band titled 🔴 would paste into a ticket as a circle and nothing else. So a title with
no letter and no digit in it (`isalnum`, a Unicode test — 日本語 is a word, → is not) is
drawn **with** its name there, `critical 🔴`, in the chip's own order. `label_parts`
returns the two halves rather than a joined string, because a title is authored
Markdown and a name is structural data each surface escapes its own way.

Both are **view** rules: the snapshot stores the title and the JSON envelope emits it,
whatever a surface decides to draw.
The comparison is on the **raw** values, before the Markdown renderer (§4.7). This is
**display, never data**: the snapshot keeps the title and the JSON envelope keeps
emitting it ([ADR-0008](adr/0008-json-output-api.md)), because a client rendering its
own chips is entitled to its own decision about the word.

A leaf's `description` surfaces **only** on its detail page (the dashboard popover shows
`title` + `about`, [ADR-0019](adr/0019-inspection-popover.md)); a **branch node's
`description` is stored but deliberately not displayed** — a container's detail lives in
its leaves, and its own `about` carries the node-level "what is this box" (ADR-0012).

### 4.6 Monitoring engine — `engine.py`
`Engine` runs the configured checks against the shared tree.

- A **scheduler** thread wakes every `poll_interval` (1s) and submits every *due*
  check to a bounded `ThreadPoolExecutor`; each check is due at start (the first
  sweep populates the tree), then every `frequency_seconds` — phase-shifted
  **once**, at the first re-arm, by a stable per-check offset (a digest of
  path + type within `min(frequency, 60s)`), so equal-frequency checks don't
  fire in one tick forever and a host carrying two checks isn't hit by both at
  once. A check already running is not re-submitted. While a check's **last
  result is not OK**, a configured **failure retry**
  ([ADR-0033](adr/0033-budgeted-failure-retry.md)) pulls its next slot to
  `retry_interval` — measured from the run's completion, and never later than
  the nominal slot — at most `retry_attempts` times per failure episode, then
  nominal cadence until an OK re-arms it. A secret-pinned check never retries,
  and freshness keeps judging by the nominal frequency.
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
  `/little-sister/runtime` per check and reading and per check and line (§4.8), and
  `_largest_record` counts the refused records at their size, setting
  `record_refused` where the heaviest was refused for its weight.
- `_execute` runs `check.measure()` and then `check.grade(measurements, now)` with
  an aware UTC instant (ADR-0086), maps any exception or timeout from either to
  `ERROR`, records
  the run's **wall time** on the schedule entry (`elapsed_seconds` — a raising or
  timed-out run keeps its full wait), logs the
  result at **INFO** (`check <path>: <code> (<ms>) — <reason>`), and **stores** it
  via `_store`, which **upserts** the root at `check.path` and walks any
  `children` into nodes beneath it (`<parent path>/<child name>`), each inheriting the
  check's frequency (ADR-0007). Beside each result it writes the **run facts** —
  `set_run_facts(path, …)` (§4.4, [ADR-0044](adr/0044-run-facts-on-the-node.md)):
  the wall time, and the armed slot projected onto the wall clock once, at write
  time, **after** the retry decision below — so a watched failure's next update
  is the pulled-in slot, never `timestamp + frequency` arithmetic. A one-shot
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
  gathers from the result, root first and depth first, the first line not yet claimed
  winning; for one no line carried that names the object the check declared, what the
  placed one keeps (`_placed`), since it stood on the node too; for any other one no
  line carried, neither; for a refused one among several, the failure record beside
  the engine's line about it, at that line's code. A store that raises is a `runtime`
  line
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
  page — uptime, pool size, check counts, and per check its type, the in-flight
  run (start + elapsed so far), the armed next slot (projected onto the wall
  clock) and the last completed run (start + wall time); and, as the last tick
  measured them, what the series hold, their ceiling and the projection (§4.10),
  which the page shows as the third line beside the declared load and the entries
  held.
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
  the roll-up. Before any of it the tick **sweeps the series** (§4.10) —
  `MemoryStore.sweep`'s one production caller: every series held to its check's
  `series_keep` as it is now, a series whose check keeps none dropped, and whole series
  evicted past `series_limit` — and hands what went to `_observe`; a sweep that raises
  is the `runtime` line `series.sweep` (§4.8) and costs the tick nothing else. The
  tick also drives the state layer's writer (`state.tick()`), last, so a file written
  on the tick holds what the sweep left, and `stop()` flushes the kept files once more
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
  the engine does not record, the resident size (`/proc/self/statm` on Linux;
  elsewhere the high-water mark `getrusage` keeps, and the line says *peak*).
  The lines, each under a slug of its own on `/little-sister/engine` (ADR-0072
  decision 4, ADR-0076 decision 3 — the path carries the engine's name, not the slug):
  - `entries` — the entry count against `ENTRY_LIMIT` (100,000): WARN at 80 % of
    it, ERROR at it. A constant rather than a share of memory, because at the
    measured half kilobyte an entry the snapshot copied per poll binds long
    before memory does.
  - `memory` — the resident size against half of what the machine gives the
    process (physical memory, or the cgroup's limit where one is set and smaller —
    the number that kills the process), WARN at 80 %, ERROR at the limit, the
    machine's figure named beside it. No line where the machine cannot say.
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
    more than nothing — the two figures the `series` lines grade.
  The path in a line's slug is `slug(path)` (§4.3's declared slug, narrowed to
  `[A-Za-z0-9._-]`), so a line is pinnable per check like any entry. A run is measured on the engine's one
  clock — the `clock` it was constructed with — which is what lets the tick see a
  run's age while it is still in flight.
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
before anything else, and counts the rest, which went to stderr only); resolves
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
nothing. It abandons the links probe's pass, then stops the engine: the scheduler
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
The node text fields (`title`, `about`, leaf `description`, each `reason`) and an
admin-authored **maintenance explanation** are
authored in Markdown and rendered **server-side** to HTML, exposed to templates as
the `markdown` (block) and `markdown_inline` (one-line, no `<p>`) Jinja filters
([ADR-0018](adr/0018-markdown-rendering.md)).

- `render.py` wraps a single **markdown-it-py** instance configured *safe by
  default*: raw HTML is **escaped** (`html=False`), link schemes are validated (so
  `javascript:` / unsafe `data:` never become links), and every link gets
  `rel="noopener noreferrer"`. **Images** were initially disabled (beacons / mixed
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
  escapes inline Markdown so a string renders literally, and **`code()`** fences
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

### 4.8 The state layer and the self-report — `state.py`, `self_report.py`

What a restart keeps is a **directory of JSON files**, `var/state/`
([ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)): a fixed
path relative to the working directory, git-ignored, not env-overridable. Two write
disciplines, one atomic write, and a seam for what the instance says about itself.

- `StateLayer(directory, interval_seconds)` owns the directory. `read(name)` returns
  the parsed file, or `None` for a file that is not there (a first start) — and also
  for one that cannot be read, which is a **load failure** the layer records and
  logs; a reader that finds a shape it cannot use says so with
  `report_load_failure(name, detail)`. `write(name, payload)` is the
  **write-through** discipline — a temp file in the same directory and
  `os.replace`, never raised, the outcome recorded. `keep(name, producer)` registers
  a **kept** file: `tick()`, called by the engine every scheduler tick, writes every
  kept file at most once per `state_interval` (`settings.yaml`, default 60 s, §7)
  and only when its serialized state changed; `flush()` writes them once more at
  graceful shutdown. A producer copies under its own lock and returns — the layer
  is never inside the tree's lock for longer than the copy takes (ADR-0002).
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
- **The files today**: `maintenance.json` (written through by the tree's
  `MaintenanceStore`, §4.4; moved from `var/`, a clean break — the old path is not
  read, and a file still there is named once at startup) and `events.json` (kept:
  `status_tree.events_payload`, restored by `app._restore_state` before the pins
  are replayed, so this process's first transitions append to yesterday's) and
  `series.json` (kept: the engine's `MemoryStore.payload`, restored by
  `app._restore_series` once `_restore_state` has fetched what a keeper holds, and
  registered with the store's `restore` for an adoption or *take the backups* — §4.10,
  [ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md) decision 9). A series
  file of another shape is `load.series.json` and the series start empty; one older
  than the configuration is met by the first tick's sweep. Run facts stay ephemeral.
  The notes file joins when it is built.
- **A failure never refuses to start, and is never silent.** `lines()` is the
  layer's self-report: per file, `load.<file>` at ERROR for as long as the process
  runs (what the file held before the restart is not in force) and `save.<file>`
  at WARN until a write of that file succeeds (nothing is lost yet; the next
  restart is). The same two slugs carry what an adoption leaves standing, with
  *adopt* as the verb — ERROR for a copy the process could not take in, WARN for
  one written to disk with nothing registered to take it. The `.bak` files are the
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
  side-table's by `MaintenanceStore(state, tree=…)` at construction, and the series
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
  (`/little-sister/state` + `load.maintenance.json`), never the flat form. A
  contributor that raises, or answers with something that is not lines, is logged
  and stands as one WARN line `<name>.raised` — the beat still lands. A report
  **clears**: a line the contributor stops returning is gone, and the node's code
  follows. `/system` prints `report <name>` on the package's
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
    **followed by `state_layer.flush()`** where the handler returned: what the
    action changed reaches the store now, not at the next interval, and a keeper's
    take-over adopts and saves in the click (ADR-0076 decision 6).
  - **Two records, one call each** (ADR-0072 §7): `Standing` keeps lines for the
    life of the process — `note(slug, text, code=WARN)` records and logs at the
    line's severity (a `StatusCode`, never `None`: a fact is the report's), one line
    per slug, a second note on a slug replacing the first
    — and the library's own is `self_report.startup`, registered as `startup`
    beside `readiness`. `Held(hold_seconds)` keeps occurrences of what recurs —
    `see(slug, text, code=WARN, measure=None, now=None)` records and logs one — for
    the window after each; `lines()` writes the plain line per slug (the latest
    text, *n times in the last …* where there was more than one), and `worst()`,
    `latest()`, `count()` and `slugs()` are for a contributor that writes its own
    sentence, as the engine's `lag` line does from the worst measure inside the
    window. Every method takes `now` so a caller with the engine's clock in hand
    gives it; the clock is otherwise monotonic and injectable.
  - **The library's three, registered in `app.py`**: `startup` (a `Standing`) for
    what the process learned at startup — an unresolved `SECRET_KEY` or
    `LITTLE_SISTER_API_TOKENS` reference, no identity door or none the default
    (ERROR where nobody can sign in), the system-admin password unresolved, a
    `config/` file no aspect claims, an aspect declared in two roots or refused at
    registration, `instance:` refused, `retry_interval` unreadable, `nodes.yaml`
    metadata no check covers or the file not loaded, a links interval unreadable,
    an avatar not shown, the retired maintenance file, a slot template, asset, icon
    or action refused, the theme bootstrap's hash missing; `runtime` (a `Held`, ten
    minutes) for what recurs — a slot's provider or template raising, an identity
    door raising, a scheduler tick, an upsert, a series store or its sweep raising, a
    reachability pass failing, overrunning, stuck or giving up; and `security` (a
    `Held`, ten minutes, graded by `security_lines`) — failed logins as a rate, a
    fact below five in the window and WARN from five, and the system-admin account
    used.
    `plain()` lives in `little_sister.reasons` so these sites can fold a path or an
    error into a line; `little_sister.checks.plain` is the same function. Two sites
    stay log-only and say why in place: `LOG_LEVEL` unreadable (`logger.py`, beneath
    the seam) and an engine that did not start (no tick to read a line on).
- **The keeper** (`keeper.py`) — a file store that mirrors the whole directory to
  somewhere durable **without knowing what it carries**: `load(name)`,
  `save(name, data)`, `list()`, in bytes, so it moves `events.json` and a package's
  sqlite file with the same code. `register_keeper(name, keeper)` claims the seam in
  the import-before-app slot under ADR-0064's rules, and there is **one slot rather
  than one per name** — two keepers would each carry a copy of what the other wrote,
  and import order would decide which one a restart came back as. `/system` lists it
  on the registering package's row, which is the only place a working keeper is
  visible: it says nothing until it fails.
  - `restore_from_keeper()` runs **first** in `_restore_state`, before any file is
    read, so a fresh machine comes up as the instance that stopped on the old one.
    What the keeper holds wins over a local file of the same name — the point on a
    new machine, and reachable on an old one only where a save to the keeper had
    already failed and said so. A name that is not a plain file name is refused: it
    arrives from outside the library and is used as a path component.
  - `flush()` mirrors the directory **after** the writer, on the same interval and
    once more at shutdown, sending every file in it — including one no producer here
    registered — and skipping a file whose bytes the keeper already took.
  - **Three methods a keeper may answer**, looked for by name (`keeper.takes_saves`,
    `keeper.close_keeper`, `keeper.changed_since_sync`):
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
    what the layer then adopts ([ADR-0077](adr/0077-authority-follows-the-lease.md)).
    A keeper without them is called as before.
  - **A failure never refuses to start and is never silent**, exactly as for a local
    file: a keeper that cannot be reached leaves every local file as it is and is
    `keeper.load` at ERROR for the life of the process; a save it would not take is
    `keeper.save.<file>` at WARN until one of that file lands — *nothing is lost yet,
    the next machine is*; a `tick` that raises is `keeper.tick` at WARN, with no save
    behind it that interval, until one returns. Nothing a keeper raises reaches the
    tick.
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
- **One read more on the memory tier**: `placed(key)`, the window with each record's
  **place** — a `Placed(record, at)`, where `at` is the instant the series orders the
  record by (below): its own `at`, or when it was first observed, which a replacement
  does not move and which the record itself does not carry. It is what the node that
  stands for the subject draws and lists (§4.11), and the page reads this tier.
- **The memory tier** is `MemoryStore`, one per engine (`Engine.series`), holding one
  window per series under its own lock: the engine adds from its pool's workers and
  sweeps from the scheduler, and a reader copies under the same lock. Every kept
  reading is **weighed** as the file keeps it — the bytes of its `json.dumps`, the
  spelling `record_limit` weighs a record in — and the store keeps the sum as it adds,
  replaces, trims and evicts: `held()` is what the ceiling is measured against, and
  `usage()` answers per check, by type and mount, the series, the readings and the
  bytes a projection is made of.
- **The file.** `payload()` is the producer of `series.json` (§4.8): every series in
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

A series is drawn where its subject is: on the node that stands for it
([ADR-0092](adr/0092-a-check-declares-its-measures.md)).

- **A measure is declared.** A `Measure(field, unit, label)` is a projection over the
  record ([ADR-0085](adr/0085-a-measure-is-read-out-of-a-record.md)): the field's dotted
  name, spelled as the record list spells it (§4.5) — `Measure.read` walks the record
  with the same `reasons.record_leaves`, and a field the record does not have reads as
  null — its unit, and what its curve is titled, the field's own name where nothing
  was given. A type passes `measure_defaults` to `Check.__init__`, shaped like the YAML
  block; a deployment writes `measures:` in the check's YAML, read by `_parse_common`
  for every type. Both are `read_measures`' shape — a field name to a unit, or to
  `{unit, label}` — and `resolve_measures` merges them **per field** in the
  constructor, once: a field the configuration names takes its entry, `null` removes
  a default, every other field keeps it, and the defaults come first in the order the
  type declared them. `check.measures` is the answer; a block of another shape — a
  unit that is not text, a name that is not a field's, `null` in a type's declaration —
  is a `CheckError` that the loader prefixes with the file (§4.5). `http` declares
  `response_ms` in `ms`, labeled *Response time*.
- **A unit is free text** and is never refused. `Measure.write` prints a number with
  the unit beside it — whole numbers with separators, fractions at three significant
  figures — except for `ms` and `s`, which are written as a span through
  `spans.format_span` (1,850 ms reads `1.9 s`), a negative one keeping its sign; a
  span names its unit in every value, so `axis_unit` is empty for those two and the
  unit itself for every other. `B` reads as a plain label until a curve needs it
  formatted.
- **`reading_cap`** — how many readings the node shows — is the check's own where its
  YAML states one (`_parse_reading_cap`: a whole number, `0` allowed, junk refused at
  load) and `settings.yaml`'s otherwise (§7: 10 by default, a bad value logged and
  replaced). The page resolves the two.
- **The curve** is `curves.draw(measure, readings, tolerance=…)` — pure arithmetic
  over a series' placed window that a template writes as SVG, on the server, with no
  script. A reading sits at its place, to scale on a time axis spanning the whole kept
  window; its value to scale from a baseline at zero (below it where a value is),
  the axis stepping in about four clean steps — for a span unit, a span somebody would
  name (500 ms, 15m, 2h). A reading whose measure is not a number — a null, a field
  the record lacks, anything else — breaks the line and is a `Mark` in a lane beneath
  the baseline, never a zero; two neighbors further apart than `tolerance` — the
  node's own `stale_after_seconds`, the tolerance its freshness is judged by
  ([ADR-0079](adr/0079-freshness-is-a-stated-tolerance.md)) — are a **hole**, and the
  line breaks there with no mark. The line never crosses either: its `runs` are the
  unbroken stretches of two readings or more, a reading standing alone between two
  breaks is a dot, and `end` is the newest reading where it has a value. The
  `hover` strips cut the plot between neighbors' midpoints, each titled with a
  reading's time and value; the times read in the configured zone and format (§7).
- **Where it is shown.** `Engine.series_at(path, subject)` answers, for a node, every
  configured check mounted on it that keeps a series, each with that subject's placed
  readings (`SubjectSeries`); nothing for an empty subject, a node below a mount, or
  a check that keeps none. `app._series_views(node)` asks it for a node that carries
  a subject — a node the engine placed a reading on (§4.6) — and builds one view per
  series: a curve for each measure, and the newest `reading_cap` readings as rows,
  each through `record_fields` (§4.5) so a time reads in the configured zone and
  everything else as stored. `_node_facts.html` renders them as the **Readings** card
  on the leaf page and on a branch page, whose poll renders it again and so carries no
  more rows than the cap; `/history/<path>` renders every kept reading and no curve
  (`every=True`). A subject that rides only on a line has no node of its own and no
  curve yet.

---

## 5. Web layer — `app.py`

### 5.1 Routes

| Route | Methods | Behavior |
|-------|---------|-----------|
| `/` | GET | Redirect to `/status`. |
| `/login`, `/logout` | GET, POST / GET | The **default door's** login step — the built-in login list on an install that registered it (`local_login.use_local()`), which stores `username`, name and an `admin` flag — or, under `identity.choose_at_login()`, a page offering every **enterable** door as a link to its own route, which takes no credential itself (§5.2) / runs the session's door `end_session` step, if it has one, and clears the session ([ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)). |
| `/login/<door>`, `/auth/callback/<door>` | GET, POST / GET | **One named door's** own login step and the return leg of its redirect flow (§5.2, [ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)). Both dispatch on the name in the path to the provider registered under it — a provider never registers a route, so this costs no general route seam — and both answer `404` for a name nothing claims and for a hook the provider does not implement, since either is a way in this deployment does not have and a redirect there risks a loop. A door's own route matters mechanically rather than stylistically: under a provider that redirects, `/login` never renders a local form. |
| `/status`, `/status/<path:branch>` | GET | Renders the dashboard from a live snapshot (whole tree or a branch; the `path:` converter passes the slash-separated node path, ADR-0016). A **leaf** check renders its **detail** page. `hide_ok` / `hide_idle` filter the view; `depth` caps how deep the tree renders (clamped to `MAX_DEPTH`, remembered in a `depth` cookie); `fragment=1` returns just the grid (for the page's live polling). With `Accept: application/json` and a valid bearer token, the same routes return the subtree as JSON instead (ADR-0008). A **leaf** page also carries the node's own **hand-off** — the two clipboard buttons of `/copy` aimed at one node: the same document machinery (`copy_status.py`, one formatter for both) over what only this page knows — the path, the observation and the period it bounds, the next update, the run's wall time, the frequency, the report, the configuration and every reason line uncapped — each line with its own code cue and in-flight marker where it declared them, each instant naming its offset. A pin does not change it: the document keeps the **measurement** and says a pin is in force, rather than presenting the pinned code as the reading. Containers get no buttons — their hand-off is `/copy`. |
| `/history/<path>` | GET | A node's status history (Status / Since / Until / Reason) and, beneath it, **every reading** the node's subject kept, newest first, in the table its page shows the newest of (§4.11). Not polled. |
| `/little-sister/<contributor>/act/<slug>` | POST | **Admin only.** Runs an action a package offered on its self-report child ([ADR-0076](adr/0076-the-instance-node-is-a-branch.md)) — `self_report.register_action(contributor, slug, label, handler)` — logs who ran what, flushes the state layer (what the action changed reaches the store now), and redirects to `/status/little-sister/<contributor>` with the sentence the handler returned shown once (a flashed message, rendered by `_said.html` on the status and leaf pages); a handler that raises is caught and its label and error are the sentence. Unknown action: 404. The buttons are the library's built-in filler on `node.actions` (`_self_report_actions.html`), rendered only on a child of `/little-sister` and only for an admin, as POST forms. |
| `/maintenance` | GET, POST | **GET** — the full, uncapped maintenance overview as its own read-only page (the leaf-detail pattern), reached from the strip pill's "+N more": **one row per pin** — a node's own, or one of its reasons' ([ADR-0036](adr/0036-addressable-reasons.md)) — with the path, what the pin *silences* (the whole node, or one reason line), time left, rendered Markdown explaining *why* it is silenced, and authorship (*pinned by … , last changed by …*). *Silenced* and *Why* are two columns on purpose: both are called "reason" in the model and are not the same thing. An entry row links to its line as `/status/<branch>?reason=<slug>`; the slug is never rendered as text. **POST** — **admin only**: set/edit/clear a node's maintenance with a raw-Markdown reason and optional duration-or-expiry (blank uses the duration from `settings.yaml`), recording who set it. Unit-suffixed durations and full ISO date/times are accepted alongside `MM-DD`, a day-of-month, `HH:MM`, and weekday/time shortcuts; a bare weekday uses 12:00, and unzoned values use the configured timezone. The resolved expiry must be **at least one second and at most 365 days away**; invalid, past, ambiguous-DST or out-of-range input is refused with the admin's words returned, and a blank reason on an *edit* keeps the stored one ([ADR-0014](adr/0014-maintenance-persistence.md)). A `slug` field addresses **one reason** of the node instead of the node ([ADR-0036](adr/0036-addressable-reasons.md)) — never a path segment, since the natural slug for a discovered entry contains a `/`; redirects to the node — or back to the page the form was opened on, via a validated `next` (the card dialog's way home). Every form carries the entry's `set_at` as a hidden **compare-and-set token**, so a write against a pin someone else has since changed is **refused whole** and answered with the conflict page — both rendered stored text and the admin's raw source, who set the stored one and when, the admin's own words preserved and one click to take the stored ones instead ([ADR-0014](adr/0014-maintenance-persistence.md)). |
| `/events` | GET | The transition log, newest first (When / Status / Service / Reason). A transition that reached nobody is **shown and marked** with the contribution rule that held it back ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 5, [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)) — it keeps the status color it would have alarmed in, and the chip beside the code is what says it did not. Marked events are what makes *did it break during the window?* answerable, and they are excluded from `/history`, which answers the other question. |
| `/system` | GET | **Admin only** — engine uptime, pool size, check counts; the declared load, the entries held and the series held beside what each is measured against (the series with the projection, §4.10); per check its type and the in-flight / armed-next / last run, each a time of day plus interval. Carries the dashboard's freshness stamp and ~10s poll (`fragment=1` returns just the info block). Below it, outside the polled fragment because they are settled at startup: the **check-type roster** (§11) — the types this configuration runs first, each with the number of checks behind it, a count that opens into the node path of every one of them so it can be believed without reading a config file, the rest folded into a disclosure so a registered-but-unused type stays readable without filling the card — the **package inventory** (§11), one row per installation outside the library with its distribution, version, loaded path and everything it registered, because a version belongs to the *installation* and a package that registers no check type would otherwise have one nowhere on the page — both tables print that loaded path **against a root the reader has** (`paths.py`): `site-packages/…` or `./…` under the working directory, whichever root is the nearer, because the diagnostic it carries is *which root the module came from* rather than the absolute string, nine tenths of which is the same prefix on every row and starts with somebody's home directory (the origins and the hover `title` keep it whole; a path under neither root stays long, which is the signal) — the **extension seams** (which package fills which slot, which configuration aspects were registered, and who registered each one), the **identity card** — one row per registered door with its route, its provider, the package that registered it and which one is the default, and beneath it whether a system-admin account is configured, whether its credential resolved and which keyword configured it, because a way into an application must not be knowable only by reading the source (§5.2, [ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)) — and the **effective Content-Security-Policy**, directive by directive, with the contributor of every source — a request blocked inside somebody else's package is otherwise undebuggable from the running instance (§5.4, [ADR-0048](adr/0048-an-assembled-content-security-policy.md)). |
| `/about` | GET | The identity page — the gaze, the name and the reasoning behind it, the running instance's `__version__`, the repository link. Auth-gated like every other surface: it names the version of a live instance. |
| `/preferences` | POST | Records this browser's **theme** and **layout** (§5.3, [ADR-0029](adr/0029-per-user-presentation-preferences.md)) and redirects back to the posting page. A value outside the roster is dropped in favor of what the browser already had; the return path is validated by `_safe_next` (a single leading `/`, and none of the characters a browser rewrites into a second one), so the hidden field cannot become an open redirect. |
| `/copy`, `/copy/<path:branch>` | GET | Auth-gated incident hand-off, in three sizes from one route and one formatter: the **tree** (`/copy`), one **node** (`/copy/<branch>`) and one **reason line** (`/copy/<branch>?reason=<slug>` — the node a path, the entry a query value, [ADR-0036](adr/0036-addressable-reasons.md) decision 12, because a discovered entry's slug contains a `/`). A line's document is the line and just enough to locate it — the node's title, path and observation — and deliberately not the node's run facts, report or configuration, which the node's own document carries and which is where a secret reference would appear. An unmounted path and a slug this run does not report are both `404` with a page that says which: a suspended pin is not deleted, but a document made from its stored text would hand over a finding the check is no longer making. The tree document: one immutable root snapshot becomes one canonical Markdown document: every non-OK leaf (`WARN`, `ERROR`, `MAINTENANCE`, `UNDEFINED`) plus only the ancestors needed to locate it, in snapshot order; the synthetic root and wholly healthy branches are omitted. Leaves carry a non-color emoji cue, and so does a **reason line that declared a code of its own** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) — a healthy workflow under a failing node has to read as healthy in a pasted document too, and a line that declared none takes no cue because it carries its node's. A line whose subject is **running** says so in words: the page's italic is the glance, and a document has none. Authored check and maintenance explanations keep their Markdown, while node/per-reason maintenance also names who set it and its expiry. Every instant it writes — a pin's expiry here, and the whole node document's time facts — names its **UTC offset**: the pages render local time and stay silent about the zone, which is right for a screen somebody is standing in front of, and wrong for a document read in another office. The page renders the rich preview through the same hardened Markdown renderer as every other surface. **Copy Markdown** writes `text/plain`; **Copy Rich HTML** writes both `text/html` and the Markdown as `text/plain`, falling back honestly to plain/manual selection when clipboard access is unavailable — the buttons are one partial (`_copy_controls.html`) shared with the leaf detail page, so the pair is named and ordered the same in both places, and the label names the clipboard member rather than claiming RTF. An all-OK tree gets an empty state rather than an empty clipboard action. |
| `/links` | GET | The **shared toolbox**: this deployment's curated links (§7, [ADR-0030](adr/0030-curated-links.md)), one flat level of groups flowed into columns, each entry a mark and a title in the configured order. Icons resolve through the search path; a name nothing defines falls through to the entry's own origin favicon and then to a neutral glyph. Structural problems in the file are shown on the page — the person who maintains it is the one looking. A **client-side filter** sits above the columns and narrows by entry and group title. The configuration is re-read only when it changed, so an edit needs no restart. Opening the page is also what **triggers a reachability pass** (§7) when the newest answer is older than the configured interval — on a daemon thread, so the render never waits on the network. |
| `/links/check` | POST | **Check now**: probes the links page's targets and redirects back to it, the return path validated by `_safe_next`. Unlike an open this one **waits**, under a deadline, joining the pass already running rather than starting a second — whatever has not answered by then keeps its previous verdict and age while the pass finishes behind the response, and the page says a pass is still going. A forced pass has a minimum gap, which is the whole of the abuse story; open to every logged-in viewer, not only an admin, because whoever maintains the file is not necessarily one (§7, [ADR-0030](adr/0030-curated-links.md)). |
| `/links/icon/<variant>/<name>` | GET | One resolved icon, for the background `variant` names (`on-light` / `on-dark`). Serves every rung of the search path that holds bytes — the deployment's own file, a registered pack's package data, the built-in pack — so the page has one URL shape for all of them; a **remote** icon is 404 here and is emitted as its own URL rather than proxied. The name is a registry key and never builds a path. Auth-gated, `private` cache with an ETag (§7, [ADR-0030](adr/0030-curated-links.md)). |
| `/user/avatar` | GET | The signed-in user's configured avatar, if any. Takes no username or path: the session selects a startup-resolved bare name inside the winning users aspect's `avatars/` sandbox, so the route cannot enumerate accounts or construct a filesystem path. Auth-gated, private five-minute cache with an ETag; a removed file falls back to the packaged neutral avatar ([ADR-0045](adr/0045-user-avatars.md)). |
| `/ext/<package>/<member>` | GET | One registered **extension asset** — a `.css` or `.js` file a dependent package ships for the slot it fills (§6.1, [ADR-0037](adr/0037-extension-static-assets.md)). Read through `importlib.resources` and looked up in the registry, so neither argument ever builds a path; the URL carries a content hash and the response is immutable. Login-gated like every other surface, and the kiosk layout loads none of it. |
| `/csp-report` | POST | Where a browser posts a **Content-Security-Policy violation**. Each report is one `WARNING` log line — the violated directive, the document, the blocked URI, the source and line — and nothing is stored, which is what keeps the policy clear of the persistence decision. **No login gate**, necessarily: a violation on the login page has no session, and a report the browser cannot deliver measures nothing. One of three such routes, with `/health` and `/ready` below. It is bounded instead — an oversized body is refused unread and each reported field is truncated before it reaches the log, because a blocked URI is whatever the page tried to load (§5.4, [ADR-0048](adr/0048-an-assembled-content-security-policy.md)). |
| `/health` | GET | **Liveness for a machine**, and the second route with no login gate ([ADR-0066](adr/0066-health-answers-liveness-and-says-almost-nothing.md)). `200` while this process serves, *whatever the engine is doing* — a load balancer that pulled the instance out of service over a failed check config would remove the very page whose banner explains it. The engine is reported instead: `{"status": "ok", "engine": "running" | "disabled" | "failed"}`, a closed vocabulary in which a deliberate `LITTLE_SISTER_ENGINE=0` (`disabled`) is not the same word as a configuration this instance could not load (`failed`). It says nothing else, and that is the bound an ungated route pays for: not the failure reason (a `CheckError` names config files; the banner carries it behind the login), not the version (`/about` is auth-gated for that reason), not the configuration. Not part of the JSON API and not in `api/openapi.yaml`. `no-store`. |
| `/ready` | GET | **Readiness for a machine**, and the third route with no login gate ([ADR-0073](adr/0073-a-readiness-answer-beside-health.md)). `200 {"status": "ready"}` once an identity door is registered, the machine's trust store holds CA certificates and the engine has run every configured check once; `503 {"status": "not ready", "waiting_for": [...]}` until then, from the closed vocabulary `doors` / `trust` / `first-pass` and nothing else — three words that name no path, count, version or configuration and answer the one question the caller of an unready instance cannot answer itself, *wait or roll back*. It **latches**: the three are startup facts, so this route goes `503` to `200` once and never back, which is what keeps it from withdrawing a serving instance and removing the page whose banner explains the failure. An engine switched off with `LITTLE_SISTER_ENGINE=0` has no pass to wait for and is ready; one that could not load its configuration never is. Which of the two routes a load balancer aims at is the deployment's choice — `/ready` behind several instances, `/health` behind one. Not part of the JSON API and not in `api/openapi.yaml`. `no-store`. |
| `/favicon.ico` | GET | Redirect to the static favicon. |

Jinja filters back the views: `status_slug` (a CSS class suffix per code),
`status_alert` (a Bootstrap alert class), `shorten`, `duration` (a *configured*
interval in the units the config wrote it in: `15m`, `1h` — a name for
`little_sister.spans.format_duration`, which the copy document calls too),
`elapsed`
(a *measured* span — a run's wall time, a countdown, an uptime — as
`little_sister.spans.format_span` writes it: `412 ms` / `3.1 s` / `43 s` /
`1m 55s` / `2h 7m` / `1d 3h`; `—` for none), `localtime`
(renders a timestamp in the configured timezone, §7 — an optional argument
overrides the format, never the timezone), `record_fields` (a record as the rows of
its list, each with its kind, §4.5), `url_branch`,
`markdown` / `markdown_inline` (server-side Markdown → safe HTML, §4.7), and
`breadcrumbs` (a path → cumulative `(name, path)` crumbs for the clickable header
trail, rendered by `_breadcrumb.html`; the current node stays plain). The dashboard
filter logic is `_filter_snapshot` (drops nodes whose effective code is hidden).

### 5.2 Authentication
- Session-based, and **one gate**: a `before_request` hook refuses any request with no
  identity, unless its endpoint is named in `identity.py`
  ([ADR-0068](adr/0068-the-login-gate-refuses-by-default.md)). Two lists say which —
  `OPEN_ENDPOINTS`, which answer without an identity at all (`/login`,
  `/login/<door>`, `/auth/callback/<door>`, `/logout`, `static`, `/`,
  `/favicon.ico`, `/csp-report`, `/health`, `/ready`), and
  `SELF_AUTHENTICATING_ENDPOINTS`, which is `/status` alone because it negotiates
  between a session and a bearer token and a gate in front of it would redirect an API
  client to a login form. Everything else is gated, including a route added tomorrow.
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
  `/system`'s, and `/system` is behind an admin session, while this page is open to
  anybody — so it says *that* there is no way in and where the answer is. **Where is
  not `/system`**: reaching that page needs an administrator's session, and the third
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
  door (`404`) while the application keeps serving and `/system` says why; a malformed
  reference still fails startup. Nothing is ever generated. It is visible while in use
  — a distinct packaged avatar and `System admin` where the chrome prints a name, a
  `WARNING` on every login and every failed attempt, a row on `/system` — and
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
  admin-only actions (set/clear maintenance, the system page) are gated on it.
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
- **JSON backend mode** — `GET /status[/<path:branch>]` with `Accept: application/json`
  is gated by a **bearer token** (named per-client tokens from the
  `LITTLE_SISTER_API_TOKENS` setting — a literal, or itself a secret reference —
  compared with `secrets.compare_digest`); the session
  cookie isn't accepted there. Errors are **Problem JSON** (RFC 9457), and an inbound
  `X-Flow-Id` is echoed. Read-only; the contract is
  [`api/openapi.yaml`](api/openapi.yaml)
  ([ADR-0080](adr/0080-the-envelope-is-the-snapshot-published.md)), and what it
  publishes is the snapshot the dashboard renders — a field added to one is added to
  the other in the same change.

### 5.3 Presentation preferences
How a viewer sees the surface — the **theme** and the **layout** — is theirs to
choose, and the choice is **presentation only**: it lives in one long-lived cookie
per browser (`ls_prefs`, url-encoded `theme=…&layout=…`, a year, `SameSite=Lax`),
never in the server, so there is no per-user state to store or migrate
([ADR-0029](adr/0029-per-user-presentation-preferences.md)). The rosters are
`THEMES` (`auto`, `default`, `vivid`, `pastel`, `dark`, `cyberpunk`) and `LAYOUTS`
(`rail`, `topbar`, `kiosk`), with `default` / `rail` the defaults.

- `_presentation()` parses the cookie and resolves each key **independently** onto
  its default — a missing cookie, an unparsable one, a retired value or one typed
  by hand can only ever show the default. A preference is a look; a bad one must
  not be able to break a page.
- An `@app.context_processor` (`_inject_presentation`) hands every template the
  resolved `theme` / `layout`, the rosters (the settings menu builds itself from
  them), `default_layout` (the kiosk's exit is a write of that value) and
  `bs_theme` — `dark` for the dark-family themes, so Bootstrap's own chrome
  follows. `_header.html` renders them onto `<body>` as `data-ls-theme` /
  `data-ls-layout` / `data-bs-theme`, so the scheme is **server-rendered** and no
  page flashes the wrong one.
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
  rail or in the bar.
- This cookie and the **view** cookies of §5.1 (`depth` and the filter switches) carry
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
  line is. `img-src` is left strict, because Markdown images are on and unconstrained
  (§4.7) — that is the directive with something to measure.
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
- The assembled policy is a **value**, which is why what a browser would be told is
  asserted in unit tests without a browser, and printed on `/system` with the
  contributor of every source.


---

## 6. Templates & static

Jinja2 templates under `templates/`, with `StrictUndefined` (an undefined variable
raises rather than rendering blank):

- `_header.html` — the shared `<head>` tail (the tab title, the icon set and
  manifest, Bootstrap and `overview.css`) and everything above the page: the
  presentation attributes on `<body>` (§5.3), the **top bar** (the brand, which is
  the way home, and the settings menu), the **rail**, and — only while the engine
  failed to start — the persistent `engine_error` banner (§4.6). It also *opens*
  the shell (`.ls-shell` and `<main class="ls-page">`), which is why every page
  ends with `_page_end.html`; a page that forgets it renders unclosed. Under the
  `kiosk` layout the bar and the rail are omitted outright and `_kiosk_line.html`
  stands in their place. The tab **title** reads *page* · *brand* — the page first,
  because a narrow tab truncates from the right and `poll.js` prefixes "(stale) "
  to whatever it says. Two script tags are emitted here rather than per page, so no
  page can forget them: `_theme_bootstrap.html` (§5.3) and `static/js/prefs.js`.
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
- `_nav_items.html` — the sections (Status / Events / Maintenance / Links / Copy,
  plus **System** for admins), written once and rendered by `nav_style` into either
  the rail or the bar. `_about_entry.html` is the way into `/about` in whichever of
  the two is showing — deliberately apart from the sections (the rail's foot, below
  a spacer; the last, quietest entry in the bar), because it is not a place you go
  to work.
- `_settings_menu.html` — the current user's circular avatar and name open it: the
  configured picture or packaged neutral fallback, then **theme** and **layout**
  as radio circles that post to `/preferences` (§5.3) with the current page as the
  return path, a grayed "settings…" reserving the later per-user overrides of
  `settings.yaml`, and **Logout**, which moved in here (the bar lost its red button).
  Each radio carries `data-ls-submit`, so `static/js/prefs.js` submits on change and
  the `<noscript>` Apply button is what a JS-less browser uses instead.
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
  node's `about` beneath. `band_stamp` / `band_filters` say which parts a page has
  (the dashboard both, a detail page neither) and default to off, so under
  `StrictUndefined` a page must ask. The freshness line is styled as the ADR-0005
  measurement it is — tabular figures, so the digits don't dance on each poll — and
  nothing here may set a `color` on it: `poll.js` swaps `text-muted` for
  `text-danger`, and both Bootstrap utilities are `!important`, so a color of our
  own would lose and a stale line could read muted instead of red. The kiosk has no
  band; its line carries the stamp instead, so the page still has exactly one. The
  filter controls carry `data-ls-submit` and the same `<noscript>` fallback the
  settings menu has (§5.3).
- `_kiosk_line.html` — the wall-display header: the brand sentence, the same stamp
  element the dashboard uses (same id, same seeded `data-rendered-at`, so the poll,
  the outage banner and the "(stale)" prefix all behave identically — an unattended
  screen is precisely where a frozen one must announce itself), and **exit**, which
  is not a mode switch but a POST writing `default_layout` back to the presentation
  cookie.
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
- `_breadcrumb.html` — the clickable header path trail (`status` root + a link per
  ancestor segment, current node plain); included in the dashboard and detail headers.
- `status.html` / `_status_grid.html` — the **dashboard**: top-level systems as
  cards in a responsive grid. **Every system and subsystem is a filled rounded box
  colored by its own rolled-up status, nested inside its parent's box** (so a
  green branch shows clearly inside a red system), each carrying its reasons; a
  translucent edge keeps same-color boxes legible. To surface the **culprit**, a
  box is shown **vivid** only when it reports its own status; a box whose status is
  merely *derived* from a visible child — and any healthy (OK) box — is **dimmed**
  (pale fill, dark text), so the eye follows a faded trail down to the bold
  originating node. So status never rests on **color alone**, each card, node box and
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
  of its own. In a head row the title and the action chips share a zero-basis
  middle (`.status-head__middle`), so **name and state alone decide whether a row
  fits**: the title ellipses under pressure and the chips sit absolutely over its
  space — a chip is something to click, a title is a nicety. The rail **repaints the
  box's own fill** there (every card and node declares it as `--ls-surface`) for as
  long as its chips are showing, so a chip — transparent by design, inking in
  `currentColor` — never reads through to the title beneath it, and a card at rest,
  offering nothing to click, keeps its whole title. The state
  cluster never breaks between its parts; a state that truly cannot fit drops as
  one clean right-aligned line. Where a card's cluster *sits* is the deployment's
  choice (`card_status_line`, §7): `beside` keeps the compact one-line head,
  `below` makes the drop the rule — a standing second line on every card, the
  same shape everywhere. When the tree is collapsed by depth, the deepest *visible* node
  in a branch stays bold (it now carries the reason). A **depth** input in the
  filter bar sets how many levels below the viewed node render — the node itself is
  level 0, so depth 0 collapses to a single card carrying that node's rolled-up
  status (an overall traffic light), depth 1 shows its top-level systems, and so on.
  It is clamped to `MAX_DEPTH` and remembered in a `depth` cookie (resolved by
  `_resolve_depth`). From depth 1 the viewed node **heads** its page with its **own**
  status wherever it has something of its own to say, since the children right below
  say theirs — except a node that declares nothing: its `UNDEFINED` is a container's,
  which the roll-up skips ([ADR-0039](adr/0039-status-rollup-semantics.md)), so one
  that carries a sentence (an `aws` check's root states its scope) heads with what it
  rolls up to, pale as its card on the parent's page is, and that is the code a kept
  reading records for it too
  ([ADR-0087](adr/0087-a-check-keeps-its-subjects-readings.md) decision 8).
  Nodes drill down; a **hide-ok** switch drops OK nodes and a
  **hide-idle** switch drops never-reported (UNDEFINED) ones; a **chips** switch (leaf density, default on) toggles the quiet-leaf chip collapse below off for a viewer who wants every leaf as a full box, and these view switches — like `depth` — persist across visits in a `SameSite=Lax` cookie set on an explicit change; **stale** nodes get a
  badge; a node with an unambiguous **observation time** — its own last
  write, or the run time of the single check below it — states *when* beside *what*, as
  a muted time of day (`settings.yaml`'s timezone, ADR-0006) sitting just before the cue
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
  with the name unless it carries a word (§4.5); and a branch view shows the viewed
  node's `about` under its heading. Admin **maintenance**
  ([ADR-0014](adr/0014-maintenance-persistence.md)) is surfaced so a pin the roll-up and
  depth hide is still findable: a maintenance-tinted **pill** joins the status strip (a
  pause-bars glyph and a live count, shown only when something is pinned), and clicking
  it opens a popover (`static/js/maintenance.js`, reusing the inspection popover's Floating-UI positioning and poll-swap survival) of the pinned nodes (path, time left, reason, each linked) — **one row per node**, so a node with twenty pinned *reasons* contributes one row carrying a count (*3 of 20 reasons*, or *all 20* where nothing is left reporting) rather than twenty that would evict everything else; capped
  at `maintenance_cap` with a **"+N more"** to a dedicated read-only **`/maintenance`
  page** that lists the full, uncapped set; a maintenance-tinted **"contains
  maintenance" pip** still marks any ancestor card whose subtree holds a pin, opening the
  same popover scoped to that card. All are built from the *unfiltered* snapshot, so
  hide-idle and a shallow depth don't hide them. An **admin** additionally gets a
  hover-revealed **pin control** in each card head — an outline pause-bars link (to
  the node's own page when JavaScript is absent) that opens a small anchored dialog
  (`static/js/pin.js`, the maintenance popover's Floating-UI and poll-survival
  machinery plus form focus handling) naming exactly what a pin on that card
  silences — and every **branch page** carries the node's own **maintenance card**
  below the grid (`_maintenance_card.html`, shared with the leaf page), which is
  also where a pin on the viewed node itself is read. On an **already-pinned** node
  both surfaces open in read mode — the safe rendered explanation, expiry and
  authorship with explicit *Edit* and *Clear* actions. *Edit* reveals the prefilled raw
  Markdown textarea and *Save changes*; editing a window is not clearing and re-setting
  it. The **Duration or expiry** field stays unfilled, so blank means the configured
  duration exactly as it does on an unpinned node. It accepts the route's duration,
  ISO and next-occurrence shortcuts; each shared editor states the configured timezone
  and exposes the complete grammar in a closed, native *Which formats can I use?*
  disclosure. A member reason follows the same rule one level down: its stable
  end-rail *Set maintenance* / *Edit maintenance* control opens an anchored native
  disclosure only on activation, never on hover, and a pinned entry's guarded set form
  sits beside its clear action. The card is also where the pin's whole reading lives — *pinned by
  Anna …, last changed by Ben …* — while the popover, having room for one name, shows
  the last writer; the kiosk layout shows
  neither control, and the overview root deliberately carries no form — silencing
  everything stays a curl, not a click.
  To keep the everyday grid balanced **without moving cards**
  ([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)), a card's **quiet leaves** (OK or idle) collapse
  to compact name+color **chips** — an all-green host converges toward a wrapping
  chip row instead of a stack of boxes — while a **warn/error** leaf keeps its full
  box and reason so a problem stays legible; chips flow inline, so a run of quiet
  siblings packs and a problem box breaks the line, preserving sibling order (a
  chip's own reason is a click away on its leaf page — the popover still shows
  title/about). In that same dense view a branch also **caps the quiet sub-branch
  boxes** it shows to a configurable budget (`branch_cap`), folding the surplus behind
  an in-place **"+N more"** (`static/js/branches.js` keeps the reveal open across the ~10s poll swap) so a deeply-nested card can't tower over the grid — a
  warn/error box is never folded. **A node may decline both compactions**
  ([ADR-0063](adr/0063-declining-the-density-trade.md)): one carrying
  `show_when_quiet` is never painted as a chip and is never counted a surplus quiet
  box, so an inventory aspect keeps its list at a glance instead of showing it only
  while a sibling is red. Both together or the field lies — kept out of the chip and
  then folded, it would show less than the chip did. The declaration is per node and
  does not cascade; it is a fact about the node's content, so the viewer's own
  controls are untouched in both directions (density off already boxes everything,
  and *hide idle* / *hide ok* still answer to the person at the screen). Card heights are **bounded**: the reason caps from
  above, a `min-height` floor from below. When a responsive row has **spare
  ordinary-width tracks**, roots spend only widths their tree can use. The server
  builds a stable flow profile from the filtered, depth-limited topology and
  configured `reason_cap`: every visible node is a potential reason host and scales
  by `ceil(reason_cap / default budget)`, and the width model follows the
  stylesheet's 330 px nested tracks, gaps and per-level insets — five constants a
  structural test pins to `overview.css`. It never reads current status,
  reason count/text, measured height or chip/box painting. Every span is priced at
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
  paint, resize and each poll swap — an explicit count is what stops the width
  where auto-fill adds a track (and snaps every track to its 330 px minimum) from
  painting a taller page out of a wider viewport. A candidate count may not
  stretch a track wider than auto-fill itself ever could (one track just short of
  a second fitting, ~676 px), which forbids the page-wide banner a single enormous
  card would otherwise win while keeping the moderate counts a dodge needs — and
  the count a band already holds is exempt, so a widening viewport can never
  disqualify the plan that is holding the page. An incumbent yields only to a
  strictly better challenger, all-ones plans ride auto-fill unchanged, and the
  finished layout is memoized on the depth-limited tree shape. Choosing the best
  legal outer count is not the same as never growing taller: a card's own nested
  auto-fit can re-chunk at a column flip that no outer choice can dodge, which is
  the documented limit of the outer planner rather than a defect. `settings.yaml`
  `dashboard_columns: plain` withholds the plan, leaving the plain auto-fill grid. A wider card grids a branch containing at least two direct full
  boxes. Consecutive quiet chips share a full-row `leaf-chip-run`, preserving their
  compact inline wrap while full boxes at the same mixed level can grid; a
  single-child wrapper and every node/reason box remain intact. The original
  auto-fill grid is the no-JavaScript fallback, and a narrow viewport resolves to one
  track without horizontal overflow ([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)). The engine's own
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
  container to swap), and flags refresh failures (so it never silently shows old
  content); the
  poll stamp (`#status-updated`) shows the **server-formatted** render time — in
  `settings.yaml`'s timezone and `time_format` (ADR-0006), not the browser clock —
  **seeded into the page itself** at render (a `data-rendered-at` attribute; page
  JavaScript cannot read navigation-response headers), then refreshed from the
  fragment's `X-Rendered-At` header on each swap. So even a page whose polls all
  fail dates its data ("could not refresh — last ok …") from first paint. A
  response **without** that header is not a fragment at all — the login redirect
  after a session expiry — and counts as a failed poll, so the grid is never
  overwritten with a login form. A **sustained** outage escalates (ADR-0005):
  after six consecutive misses the line grows a legible age, a
  banner rises above the content, the frozen content dims (`.poll-stale`) and
  the tab title gains a "(stale) " prefix — one good poll resets everything;
  session expiry banners "reload to log in" instead of an age, and a
  `visibilitychange` re-poll lets a woken tab self-heal immediately.
- **Inspection popover** ([ADR-0019](adr/0019-inspection-popover.md)) — a node's static
  `title` / `about` (rendered Markdown) show in a custom **hover card**, not the native
  `title=` tooltip (the leaf `description` stays on its detail page). The page preloads a path-keyed map of the rendered
  HTML (`#node-meta`, a `script[type=application/json]` built by `_node_meta_map`,
  **page-only** so the ~10s poll doesn't re-send it); `static/js/inspect.js` binds once via
  event delegation on `#status-grid` (surviving the swaps), looks each node up by
  `data-path`, and renders + positions the card with **Floating UI** (CDN). Opens on
  hover / focus, stays open when the pointer moves into it, closes on leave / blur /
  Escape; the node stays a link to its detail page; a tap opens the card on touch.
- **Coded reason lines** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) —
  a line whose entry declares its own code carries a per-line state class and a
  small **labeled** shape cue (a line has no status word, so the cue is its
  accessible name — the `_status_cue.html` partial both surfaces import); every
  coded line paints its state's **own tint pair** at full opacity, ok included
  (the silenced-reason lesson: ink on whatever surface a line lands on is how a
  2.7:1 ships — and a mixed list sits on a *vivid* fill, where a surfaceless
  passed line would read as part of the problem; green under red is the point).
  The pale ok tint is itself the quiet treatment, and an all-healthy node
  collapses to a chip on the grid anyway. `is-running` renders work-in-flight as
  an italic; the words still say it. A **quiet** (pinned) line keeps the
  maintenance tint whatever its code, with only the cue saying what state is
  silenced; `test_contrast.py` measures all four line pairs and the full-opacity
  reset.
- **Reason overflow** — a card clamps its reasons to a **line budget**
  (`settings.yaml`'s `reason_cap`, default 6, carried as the block's `--reason-lines`):
  short reasons show that many, a reason that wraps to several lines uses more of the
  budget, so an erupting node cannot outgrow the grid. Every reason is server-rendered
  into the DOM and the surplus is clipped **by CSS, never mid-HTML**, so a reason's
  safe Markup ([ADR-0018](adr/0018-markdown-rendering.md)) is never cut, then faded at
  the edge. A single **chevron in the card header**, just after the status word
  (`static/js/reasons.js`), reveals the rest in place (▼ → show all) and folds it back
  (▲), with an empty same-width slot when nothing overflows so the status words stay
  aligned; a nested node, which has no status word, gets it at the top-right of its
  name row. Like the popover it binds once via event delegation on `#status-grid` and
  keeps a page-lifetime set of expanded paths, so an expanded card survives the ~10s
  fragment swap. The leaf detail page (`check.html`) always renders every reason and
  the JSON envelope ([ADR-0008](adr/0008-json-output-api.md)) is untouched.
- `check.html` — a leaf check's detail page (its `title` following the breadcrumb in
  the header ([ADR-0017](adr/0017-node-title.md)); the node name + `description`; its
  `about` when present
  ([ADR-0012](adr/0012-node-metadata.md)), status + reason, the **node-facts** block
  below, a per-reason
  admin pin on a node whose reasons are members ([ADR-0036](adr/0036-addressable-reasons.md)) —
  a silenced line stays visible in the maintenance tint, says who silenced it and
  until when, and the node states how many of its reasons are quiet — admin maintenance
  form).
- `_node_facts.html` — the node's own facts, the **one** block both detail surfaces
  render ([ADR-0044](adr/0044-run-facts-on-the-node.md) decision 8): a **Time**
  card, a **Measured** card where the run kept a record
  ([ADR-0085](adr/0085-a-measure-is-read-out-of-a-record.md); its list is §4.5's), a
  **Readings** card where the node stands for a subject whose check keeps a series
  ([ADR-0092](adr/0092-a-check-declares-its-measures.md), §4.11: the curves of its
  measures and its newest readings, from `_series.html`), a
  **Report** card and a **Configuration** card, in that order — when it ran, what it
  read, what it has read over time, what it found, what it ran with, outputs before
  inputs because the outputs are why the page was opened. The report and the configuration go through the
  hardened Markdown renderer ([ADR-0018](adr/0018-markdown-rendering.md)), which
  `config` had been missing since before that renderer landed. The **Time** card
  never invents an instant
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)): it reads *from … until …*
  across the current status period — the **own**-status period, since that is what the
  event log bounds — falls back to a single *Observed …* where the node
  has no transition of its own to bound one, or where it declares nothing above nodes
  that report, since a container's `UNDEFINED` is no status for a period to name,
  and says *Not yet observed* when no check
  has written it; it adds the **next update** and the run's **wall time** where the
  node carries run facts (this is where wall time surfaces at all), the check
  frequency, and the History button. The next update stays **absolute** here as on
  the grid: one partial serves a page that polls and a page that does not, and a
  relative *in 4m* left frozen on an unpolled tab is the lie the absolute form was
  chosen to survive.
  **The branch page renders it too** — below the child grid (the head says what this
  node is, the grid what is under it, the details last, so a long report cannot push
  the dashboard off the screen) and **inside `#status-grid`**, because `report` is an
  output of the run and would otherwise be the one part of a polling page going
  quietly stale. It renders only where the node has something of its own to say, so a
  container two checks share — its text and run facts withheld by §4.4's rule — shows
  none of it. The kiosk keeps none of it either. This is the container acquiring the
  detail page it never had, by reuse rather than as a second surface.
- `_series.html` — a subject's series, as two macros both detail surfaces and the
  History page import ([ADR-0092](adr/0092-a-check-declares-its-measures.md), §4.11):
  `curve`, which writes `curves.draw`'s geometry as SVG with no script — the value
  axis as hairlines and its words, the unbroken runs of line, the dots, a mark in the
  lane beneath the baseline for a reading without a value, the oldest and newest
  time, and a transparent strip per reading titled with its time and value, lit
  faintly under the pointer — with a caption that names the newest, the lowest and
  the highest value and counts the marks (its key the mark itself) and the holes; and
  `readings_table`, the readings newest first — the time on the series' clock, the
  code as a labeled cue, a column per field through `record_fields`, the sentence as
  it stood. Every ink is a token `test_contrast.py` measures on the card.
- `history.html` / `events.html` — the status-history and event-log tables, rows
  tinted by status (`row-*` classes in `overview.css`); the history carries every
  reading the node's subject kept beneath its periods (§4.11), and shows no row for the
  current period of a node that declares nothing above nodes that report — own code
  `UNDEFINED`, children present, the Time card's test — ending where it stopped
  declaring and saying so in a line
  ([ADR-0094](adr/0094-a-restart-is-no-transition.md)); a suppressed event carries the
  rule's name in an `event-suppressed` chip, which paints its own maintenance tint
  rather than inking onto the row color beneath it ([ADR-0028](adr/0028-design-tokens-and-themes.md)).
- `system.html` / `_system_info.html` — the admin engine status page (per
  check: type, the in-flight run, the armed next slot (marked `· retry k/N` when it is a failure-retry slot, ADR-0033) and the last completed
  run), with the same server-seeded stamp and ~10s poll as the dashboard — the
  info block is the `_system_info.html` partial, swapped by `poll.js`.
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
  fragment swap the day this page starts polling — the shape `reasons.js`,
  `branches.js` and `maintenance.js` already use.
- `static/css/overview.css` — every color the surface paints is a **design token**
  (`--ls-*`) declared once on `:root`, and a **theme** is an override block on
  `body[data-ls-theme=…]`, never a fork
  ([ADR-0028](adr/0028-design-tokens-and-themes.md)): the two-surface state model
  (a vivid fill and a pale tint per state, with the ink that belongs to each), the
  brand inks, the shell (bar, rail, page, band, kiosk line), the dashboard
  grid/card/panel styles, the leaf **chips** and the heartbeat **status strip**,
  the settings menu, `/about`, and the table row tints. Status text is held to
  WCAG **AA** in the default, vivid, pastel and dark themes — verified per theme by
  computed style and measured contrast, not by the presence of a class; cyberpunk
  is a declared fun theme and is measured but not gated. Bootstrap via CDN;
  favicons (`.svg` re-inking itself for a dark tab strip, `.ico`, the PNGs);
  `site.webmanifest`.

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
undeclared slot raises. `/system` lists what registered.

The roster holds **two** slots, and they differ in their **subject** — which is what
decides where a deployment's action belongs
([ADR-0036](adr/0036-addressable-reasons.md)):

- **`reason.actions`** — beside every rendered reason line, on the dashboard grid
  (`_status_grid.html`'s `reason_block`) and on the leaf detail page (`check.html`),
  with `node`, the **unshortened** `reason`, the whole `line` (its slug, its own
  code, its `running` flag and any pin), its `index` and the `surface`
  (`grid` / `check`). The place for an action about **one** finding, where a node's
  reasons are individually addressable members. A provider receives **the names it
  declares** — or all of them if it declares `**kwargs` — so a context that grows
  never costs a filler written against an earlier one its chip
  ([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)). The
  library's own **copy chip** fills this slot: a link to
  `/copy/<path>?reason=<slug>`, on member lines only, since prose has one thing to
  hand over and it is the node.
- **`node.actions`** — on every node the grid draws as a **box**: a card head and each
  nested box under it, plus beside the status on a leaf's own page, with `node` and
  `surface`. Boxes and not only cards because a card is the *top* of a subtree and is
  usually a container with no reading of its own, while the failing leaf an action is
  about sits in a nested box; a **quiet leaf** is drawn as a chip rather than a box and
  carries none. The
  place for an action about the **whole node**, which is where it belongs when the
  reasons are *prose*: a failure message and its stack trace are one condition in
  several paragraphs, and a per-line control there would offer to raise a ticket about
  a stack trace.

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

The common case for a slot is *a link with the node's details in the query string*,
and it needs no code: `config/actions.yaml` describes one
([ADR-0038](adr/0038-declarative-action-list.md)). An entry is `label`, `url`, `slot`
and optionally `icon` and `under`; roots are **layered like the checks**, so a site
root adds its actions to a base root's. `url` is a template over `{path}`, `{name}`,
`{code}`, `{reason}` and `{reasons}` — for a node action `{reason}` is the node's first
line and `{reasons}` all of them — and every substituted value is **percent-encoded**,
so only a URL is ever templated and an action can never carry markup onto a page. A
template naming anything else is **refused at load**, because a button that lies is
worse than no button. `under` limits an action to one subtree, compared segment-wise
(`/system/alpha` covers `/system/alpha/disk`, never `/system/alphaville`); `tag:` waits
for tags. It is registered as a **`builtin` filler of both slots**, through the same
loader an extension uses, so a configured chip and a coded one share one rail in one
order — and it is the one registration `slots.forget_fillers()` puts back, the way the
icon registry keeps its built-in pack. `/system` marks each filler *built-in* or
*extension*.

---

## 7. Configuration & data

- **Deployment actions** — an optional `config/actions.yaml` per root lists chips the
  dashboard and the detail page offer on a node or on one of its reason lines
  (`label`, `url`, `slot`, optional `icon` and `under`), layered across roots like the
  checks (§6.2, [ADR-0038](adr/0038-declarative-action-list.md)).
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
  `/system`.
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
  environment ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)).
  A check names its credentials in a `secrets:` block, each a **secret
  reference** — `env://NAME` for the environment, or another `scheme://address`
  resolved by a deployment-registered resolver — once at check construction
  (§4.5, [ADR-0023](adr/0023-secret-references.md)).
- **API tokens** — the `LITTLE_SISTER_API_TOKENS` setting holds named per-client
  bearer tokens (`name=token,name2=token2`) for the JSON backend (ADR-0008); its
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
  `title` and an ordered list of entries (`title`, `url`, an `icon` **name**, an
  optional one-line Markdown `note`, and `check: true` to opt that entry into
  reachability probing); an `icons:` map naming the deployment's own marks — one file,
  an `on_light` / `on_dark` pair named for the background it goes on, or `none` to
  suppress a mark; and a `check:` block (`icons`, `links`, `interval`, `alive`) of
  probe settings. Groups **merge by title** across the roots and concatenate base
  first — two files contributing to one group is not the ambiguity two checks claiming
  one node is — while `icons:` entries resolve **per name**, a later root replacing one
  whole, and the `check:` block merges per key. Entry order is curated and never
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
  checks, URLs that rot on a redesign, one `img-src` line in `config/csp.yaml` per
  host (§5.4), and nothing at all for a deployment without outbound access. Each name ships
  `<name>-on-light.svg` / `<name>-on-dark.svg`, named for the background the file goes
  on and differing only in ink (the two `--ls-ink` values, [ADR-0028](adr/0028-design-tokens-and-themes.md));
  the pack's `manifest.yaml` records what every glyph depicts and its terms
  ([ADR-0030](adr/0030-curated-links.md), `icons.py`).
- **Link reachability** — the `check:` block is acted on by `link_probe.py`, and
  **opening `/links` is what starts a pass**, only when the newest answer is older
  than `interval:` (default `6h`, so the key measures how stale an answer may be
  rather than how often a timer fires). The engine's tick is deliberately not the
  trigger: there is none wherever `LITTLE_SISTER_ENGINE=0` — which is exactly where
  the page still works — and structural validation already settles every icon that
  is not remote, so a timer would usually wake to probe an empty set. The open
  **never blocks**: the pass runs on a daemon thread and the page renders from
  module state, so the answers one open triggers land on the next. **One pass at a
  time**, however many readers arrive together; answers are keyed by URL, so a dozen
  entries for one tool and its icon cost one probe, and a URL the file no longer
  names is dropped at the end of a pass. Targets are the entries that said
  `check: true` (off by default: a corporate `403` says three different things) and
  the **remote** icon URLs the used names resolve to (`icons: true` by default,
  which is an empty set wherever the marks are built-in or local). `HEAD` first,
  again with `GET` when the server's answer is about the method (`405` / `501`);
  redirects are reported rather than followed, since `301` / `302` are agreed alive
  codes and the page at the end of a chain answers a different question. Only
  `404`, `410`, a name that does not resolve and a refused port are **dead**;
  everything else outside `alive:` — a `500`, a timeout, a TLS failure — is *no
  answer*, worded as this instance failing to find out rather than as a verdict on
  the entry. Per-request timeout, concurrency cap and the interval fallback are
  module constants (`REQUEST_TIMEOUT`, `CONCURRENCY`), not settings: a deployment
  that wants none of this switches both keys off, which empties the target list. The
  opener is otherwise urllib's default, so an outbound proxy named in the
  environment is used as it is everywhere else. **Check now** (`POST /links/check`,
  §5.1) is the one caller that waits — the time gate is exactly wrong for somebody
  who has just fixed a URL and is waiting on purpose — under `CHECK_NOW_DEADLINE`,
  joining a running pass and floored by `MIN_FORCED_GAP` so the page cannot become a
  way to spend the instance's bandwidth. A pass also has **a deadline of its own**,
  derived from the target count in rounds of `CONCURRENCY` and floored above the
  *check now* one (`PASS_DEADLINE_FLOOR`, `PASS_DEADLINE_SLACK`): `REQUEST_TIMEOUT`
  bounds a socket operation rather than a request, so a host that dribbles never
  times out and would otherwise hold the only pass slot for the life of the process.
  At the deadline the pass **abandons** what is still on the wire — answered keeps
  its verdict, started-and-unfinished becomes *no answer*, never-started keeps the
  verdict and age it already had — and releases the slot. Two passes can therefore
  overlap, so each carries a **generation**: a superseded one stops writing, stops
  pruning, and does not clear its successor's slot. Abandoned probes are counted
  until their sockets close, and past `MAX_STUCK_PASSES` no new pass starts — which
  the page says, rather than looking like a control that does nothing. Nothing here
  reaches the status tree — a moved wiki page must not turn the dashboard amber for
  everyone ([ADR-0030](adr/0030-curated-links.md) §9–10, `link_probe.py`).
- **General options** — `config/settings.yaml` (shallow-merged per key across the
  roots, later winning; override the whole thing with a single file via
  `LITTLE_SISTER_CONFIG`)
  holds display/runtime options: `timezone` (default `Europe/Berlin`), `time_format`,
  the dashboard budgets `reason_cap` (default 6), `branch_cap` (default 3) and `maintenance_cap` (default 5) — the reason-line, quiet-sub-branch and maintenance-pin caps ([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)) — `reading_cap` (default 10, the readings a node standing for a subject shows beneath its curves, `0` the curves alone; a check's own wins, §4.11, [ADR-0092](adr/0092-a-check-declares-its-measures.md)), `maintenance_default_expiry` (default `7d`, the window applied when an admin
  gives no explicit duration or expiry — ADR-0014), `stacktrace` (default **true** — a failing
  check's trace on its node, §4.6), `card_status_line` (default `beside` — the
  compact one-line card head; `below` gives every card a standing status line
  under its title row, a calmer grid that spends vertical space for it, rendered
  as a `data-ls-card-state` body attribute the stylesheet branches on; §6),
  `dashboard_columns` (default `flow` — large roots may spend a wide grid's
  spare columns per the stable width-priced plan,
  [ADR-0056](adr/0056-stable-useful-dashboard-flow.md); `plain` withholds the
  plan and keeps every card at one ordinary track, the no-JavaScript grid) and
  the **failure retry** — `retry_interval` /
  `retry_attempts` (default off / 2; [ADR-0033](adr/0033-budgeted-failure-retry.md),
  §4.6), both overridable per check — `state_interval` (default 60, the seconds
  between writes of the kept state files, §4.8), the engine's sizing numbers —
  `max_workers` (default 8, the worker ceiling and what declared costs are summed
  against), `entry_limit` (default 100,000), `memory_share` (default 0.5, a
  fraction in `(0, 1]`), `record_limit` (default 2,048 bytes, what one record may
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
  ([ADR-0006](adr/0006-config-file-and-timezones.md)). Displayed timestamps are
  stored as server-local and converted to that timezone by the `localtime` filter
  (`zoneinfo` + `tzdata`) — a record's own times, which the seam stores in UTC, by
  `record_fields` (§4.5); the same zone interprets maintenance expiry input that has
  no explicit offset (ADR-0006).
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
  `maintenance.json`, written through, and the event log in `events.json` and the
  series in `series.json`, written every `state_interval` and at graceful shutdown;
  all three restored at startup (§4.8,
  [ADR-0071](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)). The tree
  itself is rebuilt by the checks. Where a deployment registers a **keeper**, the
  whole directory is mirrored to it on the same interval and restored from it before
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
- **A reader for the series on the API.** A series survives a restart and all of them
  are bounded together (§4.10), and the node that stands for a subject draws its
  measures' curves and newest readings from it (§4.11); no `series` read on the JSON API
  exists yet, so a client sees a kept series nowhere.
- **A keeper to register.** The seam is built (§4.8) and the library ships no
  implementation of it, which is the design rather than a gap — a store is a
  package's business, and a local installation wants none. Out of the box, then,
  nothing carries `var/state/` off the machine it is on.
- **Filtering `/events`.** Every transition is now recorded, marked or not (§4.4), so
  a long maintenance window over a flapping check writes rows nobody wants first. The
  page shows all of them today. Hiding marked ones by default behind a toggle is a
  question about the log as a whole — the same one retention answers — and belongs
  there rather than as a special case for one rule.
- **Satellite federation** and **write actions** over the JSON API
  (`project.md` §2.9). The snapshot's `reported_code` and an `Event`'s
  `suppressed_by` stay server-side until then: they are new fields on a published
  contract and ship with the round that versions it
  ([ADR-0008](adr/0008-json-output-api.md)).
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

Test suites: `test_status.py` (the `Status` model + ADR-0039 roll-up),
`test_tree.py` (the tree, events, history, maintenance + its persistence),
`test_copy_status.py` (the canonical incident-copy documents — the tree's outline
and one node's — and the zoned instants both write),
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
`test_maintenance.py` (the maintenance side-table store and its file), `test_nodes.py` (nodes.yaml loading, `about` precedence, the consistency
pass), `test_metadata.py` (the shared subnode-metadata helpers),
`test_engine.py` (scheduling, concurrency, `info()`), `test_retry.py` (the budgeted
failure retry of ADR-0033), `test_config_dir.py` (the configuration roots, aspect
forms and the startup contract of ADR-0031), `test_values.py` (typed reads out of a
decoded bag, ADR-0026), `test_render.py` (Markdown rendering and the
reason-assembly helpers, ADR-0018), `test_titles.py` (what the fold treats as the
same string, and the two emphasis spellings it splits on), `test_paths.py` (which
root a loaded-from path is drawn against, and what stays long), `test_links.py` and `test_link_probe.py` (the
`links` aspect and its reachability pass, ADR-0030), `test_icons.py` (icon names,
the pack registry and resolution),
`test_web.py` (the routes via the Flask test client), `test_web_pins.py` (branch
pins: the card pin control and the subtree page's maintenance card), `test_api.py`
(the JSON backend: serialization, content negotiation, token auth),
`test_contrast.py` (the AA bar of ADR-0028, measured rather than eyeballed),
`test_ui_fixtures.py` and `test_demo_check.py` (gate coverage for the two UI
harnesses), and `test_docs_links.py`
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
  are each followed by a flush of the state layer, is.
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
  §4.8 here), and the three it may answer — `tick(interval_seconds) -> bool`,
  `close()`, `changed_since_sync() -> Sequence[str]`
  ([ADR-0077](adr/0077-authority-follows-the-lease.md)) — each looked for by name and
  done without. One per instance, registered in the same import-before-app slot. The
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
      CHECK_TYPES  Check  CheckError  CheckResult  Entry  Measurement  register
      API_VERSION  require_api
      code  coerce_code  config_markdown  parse_duration  parse_secret_refs  plain
      CHECKS_ASPECT  checks_dirs  load_checks
  little_sister.reasons
      Entry  MAX_SLUG_LENGTH  MAX_SUBJECT_LENGTH  RECORD_TIMESTAMP_KEYS
      ReasonError  clip  derived_slug  normalize  plain  slug
  little_sister.status
      StatusCode  join_path
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

  `little_sister.spans` is on the list because a check writes a duration into a
  reason line — *"the backup took 2h 7m"* — and one that formatted its own would
  drift from the page it renders onto. It is the writing half of a pair whose
  reading half, `parse_duration`, is already promised above; the two sit in
  different modules because one is config parsing and the other is display, and
  the display half is used by the library's own templates through the `elapsed`
  and `duration` filters, each a name for one of these functions and not a second
  implementation. `format_duration` is the third rendering and answers the
  question the other two do not — how a **configured** interval is written back,
  in the units somebody typed it in (`900` is `15m`) — which is why the copy
  document can state a check's frequency in the same words as the page.
  `local_time` is the one **instant** beside the three spans: a moment in the
  `timezone` and `time_format` of `settings.yaml`, the rendering every page uses
  (the application's own `_format_local` delegates to it), promised so that a
  plugin writing *when* into a line — *the lease lapsed at …* — says it in the
  page's words rather than in `GMT` beside the page's zone.

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
  buys it nothing — which is why **neither built-in caller passes one**: the `http` check
  makes a single request and reads no body, and the link prober bounds a hung probe by
  abandoning the pass. And the clock does not reach the **status line and headers**, which
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
  epoch 3 promises, and the gate requires the current block to still contain all of
  it — so a name cannot leave without the epoch moving, which is the hole a
  doc-and-code rename would otherwise slip through. **Epoch 2** opened by removing
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
  ([ADR-0051](adr/0051-what-startup-refuses.md)). `/system` lists every registered
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
- **Logging** — a *behavior*, not a name. little-sister logs through the standard
  hierarchy and never switches propagation off, and `little_sister.logger`
  configures the **root** logger only when the application has not — no handlers on
  it at import. So a deployment or a plugin that sets up its own logging **before**
  importing `little_sister.app` (the same import-before-app slot as everything else
  here) keeps its handlers *and its level*, and little-sister's own records arrive
  there too; one that sets up none gets the default: the console (stderr) plus a log
  file, whose path is `LOG_FILE` or `var/little-sister.log`, at the level `LOG_LEVEL`
  names or **INFO**. Both variables belong to that default and are consulted nowhere
  else — against an application that configured its own logging, `LOG_LEVEL` does
  nothing, because the level is then that application's to choose. An unrecognized
  name falls back to INFO and says so in the log it just opened. A plugin imports
  nothing
  from here — it calls `logging.getLogger(__name__)` like any Python library. The
  module and its
  `logger` object are **not** contract — what is promised is that the records reach
  whoever owns the root logger, which is the whole of what a dependent package needs.
  `tests/test_logger.py` holds it, because a library that quietly reconfigures
  logging is only noticed when somebody's log file is empty.
  - **INFO rather than DEBUG, because nothing here logs below it.** A DEBUG root
    collects no line the library writes and every line its dependencies write — the
    caps on `httpx` and `markdown_it` are two such dependencies noticed one at a
    time, and a deployment carrying an AWS check type was two thirds `botocore`
    request detail. A deployment that wants that detail asks for it with
    `LOG_LEVEL=DEBUG`; one that wants a *dependency* quiet caps that dependency's
    own logger by name, which adds no handler and so leaves this default intact.
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
whenever a plugin decides to reach past this list. `/system` lists every registered
package with the version answering for it, which is where a mismatch becomes
visible.
