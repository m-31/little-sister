# Little Sister — Architecture

How the codebase is built **today**. For the product (what and why) see
[`project.md`](project.md); for the rationale behind the choices here see
[`decisions.md`](decisions.md) and [`adr/`](adr/).

---

## 1. Technology stack

| Concern | Choice |
|---------|--------|
| Language | Python ≥ 3.14 |
| Web framework | Flask + Jinja2 (`StrictUndefined`) |
| WSGI server | gunicorn (single worker, threaded) |
| Config | YAML (PyYAML); secrets from a `.env` file |
| Build / tooling | uv (`uv_build`, `uv.lock`); ruff, mypy, pytest |
| Frontend | Bootstrap 5 + Floating UI via CDN; one local stylesheet + a little vanilla JS |
| Markdown | markdown-it-py — server-side rendering of node text ([ADR-0018](adr/0018-markdown-rendering.md)) |
| Dependencies | Flask, gunicorn, PyYAML, `markdown-it-py[linkify]` (the extra backs autolinking, ADR-0018) and tzdata — that is all of them; checks use the standard library (the SSH checks shell out to the external `ssh` binary) |
| License | MIT |

The expected deployment host is **macOS** (so checks can reach the Apple
ecosystem plus Linux hosts on the network and remote servers).

---

## 2. Repository layout

```
little-sister/
├── README.md            # install / run instructions
├── pyproject.toml       # metadata, deps, tool config (mypy targets src/)
├── uv.lock
├── hooks/pre-commit     # ruff + mypy + pytest gate (opt-in via core.hooksPath)
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
│   ├── api.py           # JSON serialization for backend mode (ADR-0008)
│   ├── status.py        # Status / StatusCode domain model + roll-up
│   ├── tree.py          # the shared, thread-safe StatusTree, event log, history
│   ├── checks/          # Check base + http/file/command + ssh/ family + loader
│   ├── engine.py        # scheduler + thread pool: runs checks → upserts the tree
│   ├── config.py        # general config (config/settings.yaml) → Config
│   ├── config_dir.py    # the config path-list and its aspects (ADR-0031)
│   ├── values.py        # typed reads out of decoded YAML/JSON bags (ADR-0026)
│   ├── errors.py        # CheckError + ConfigError (shared; see below)
│   ├── secrets.py       # secret references → values; resolver registry (ADR-0023)
│   ├── maintenance.py   # maintenance side-table persistence (var/maintenance.json)
│   ├── links.py         # the `links` aspect: curated links, re-read on change
│   ├── link_probe.py    # reachability for that page: an open starts a pass
│   ├── users.py         # the `users` aspect: login list + avatar resolution
│   ├── watch_lines.py   # what /about's hero says: the pools a render draws from
│   ├── icons.py         # icon names, the pack registry, where the bytes are
│   ├── icon_pack/       # the built-in marks (our own drawn glyphs) + manifest
│   ├── nodes.py         # the `nodes` aspect's metadata + startup consistency pass
│   ├── render.py        # safe server-side Markdown → HTML (markdown-it-py)
│   ├── titles.py        # a title that repeats the name, or has no word in it
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
| **a plugin** | `little-sister-<x>` | one check type, or one surface extension, in a repository of its own. Depends on the library with a **floor** (`little-sister >= x`), never a pin |
| **a deployment** | private | the checks, node metadata, users and secrets of one installation. **Pins** the library, installs the plugins it wants, and writes the `wsgi.py` that imports them |

Three plugins exist today — **`little-sister-github`** and **`little-sister-wiz`**
(check types), and **`little-sister-jira`** (a surface extension: two template slots
and a configuration aspect, no check type). Each releases on its own version line —
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
`gthread` worker), or `app.run()` for local dev.

- The **engine** runs checks on a **bounded thread pool**, scheduling each at its
  `frequency`. Checks are I/O-bound and the GIL is released during I/O, so threads
  give real concurrency.
- All threads share **one in-memory status tree** plus a bounded in-memory **event
  log**, guarded by a single `threading.RLock`. Reads take an immutable snapshot
  under the lock and render it outside (ADR-0002).
- There is **no persistence** — state lives in memory only.
- The engine starts **once, after the fork** (in the worker), with **daemon
  threads**.

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
  condition in several paragraphs.
- `timestamp: str | None` — the **observation time** (ISO-8601): `None` until the
  node's first `update()` / `touch()`, so *having* one means a check has written this
  node ([ADR-0027](adr/0027-observation-timestamp-semantics.md)). Construction never
  stamps; a node the tree created on the way down to a check carries none.
- `description: str`, `frequency_seconds: int | None`, `config: str` — metadata
  inherited from the check and set by the tree; `config` is the curated parameters
  the check ran with, as Markdown ([ADR-0013](adr/0013-check-config-on-node.md)).
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
`add_child(child)` (enforces `child.path == f"{self.path}.{self.name}"`),
`get_children()`, and `get_status_code()` (§4.3). Code/reason coercion is factored
into `_coerce_code` / `_coerce_reason`.

### 4.3 Aggregation (roll-up)

**A node has two kinds of child, and they grade by one rule.** The real ones are in
`__children`. The **virtual** ones are its own member reasons: a node whose `members`
is true is not carrying one condition in several paragraphs, it is carrying a set of
reasons, and each of those is a child the tree does not hold
([ADR-0036](adr/0036-addressable-reasons.md) decision 7; the
[ADR-0032](adr/0032-status-contribution-boundary.md) amendment). A virtual child has
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
[ADR-0032](adr/0032-status-contribution-boundary.md)'s amendment left open, answered
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
  config=None)` — create-or-update a node by absolute path (intermediate nodes
  auto-created), store the inherited metadata, and append a transition `Event`
  **only when the node's own code changes**. `config` is static display metadata
  (the check's parameters, [ADR-0013](adr/0013-check-config-on-node.md)) — stored
  when given, never a transition. A node **in maintenance** is written like any
  other — the pin is derived at snapshot time, not stamped into the tree, so a
  silenced node can still say what it is silencing and clearing a pin restores the
  last known state at once rather than at the next run.
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
  **written through** to `var/maintenance.json` via an injected `MaintenanceStore`
  ([ADR-0014](adr/0014-maintenance-persistence.md)); an entry read without the two
  creation fields defaults them to the set values, so a file written before that
  amendment loads unchanged. `restore_maintenance` replays it
  post-fork at startup (dropping expired); `reap_uncovered` drops pins no check root
  covers (segment-wise — the `status.on_same_line` predicate shared with ADR-0015);
  and `sweep_expired`, run each scheduler tick, clears entries past their window as a
  real transition.
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
- The snapshot derives a node's **own status** rather than copying its stored code
  ([ADR-0036](adr/0036-addressable-reasons.md);
  [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md); the
  [ADR-0032](adr/0032-status-contribution-boundary.md) amendment): a **pin** on the
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
  a node not observed within ~2× its `frequency` is flagged `stale` and its `code` is
  degraded to at least `WARN` (worse-of, rolled up) — including a **pinned** node,
  whose reading is what staleness judges. The aggregation rule itself is the reusable
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
A check returns a `CheckResult` — a **recursive value** (`code`, `reason`, and
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
the chevron. `reasons.py` owns the normalization, the content-hash slug
(`h-` + ten hex digits) an undeclared entry gets, and the `derive_code` rule. Most checks return a
single leaf; one that reports several aspects returns `children`, a small tree the
engine writes as a branch beneath the check's node ([ADR-0007](adr/0007-check-result-branches.md)).
A check also exposes a curated allow-list of the parameters it ran with via
`Check.config_summary()` (Markdown) — display metadata the engine carries onto the
node like `description` and the detail page renders
([ADR-0013](adr/0013-check-config-on-node.md)); a **branch** check leaves its shared
container bare and tags each child's `config` instead.
`checks/base.py` holds the `Check` ABC, the `CheckResult` / `CheckError` types,
common config parsing (`path`, `description`, `frequency`, `timeout`;
`parse_duration` accepts `15m` / `2h` / seconds) and a `type`→class registry.
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
  (stdlib `subprocess`, per-check timeout).
The **SSH family** runs over one connection, `SshConnection` (`checks/ssh/connection.py`):
a value object that carries the connection block (`host` / `user` / `port` /
`identity_file` / `options` / `sudo` / `timeout`), builds the `ssh` argv (`BatchMode`
forced; the legacy SHA-1 `ssh-rsa` algorithm **off by default**, applied after the
user's `options` so a host can re-enable it), and runs a remote command or pipes a
local script — returning a `RemoteResult` (stdout, stderr, exit code, a failure
`error`, and any ssh advisory `notice`). It flags a **non-post-quantum key
exchange**, which every connecting check surfaces as **WARN**;
a legacy host silences it with `options: ["-o", "WarnWeakCrypto=no-pq-kex"]`. A pure,
I/O-free toolkit, `ssh_metrics` (`checks/ssh/metrics.py`) — `parse_metrics`, `grade`,
the formatters, `unavailable`, `volume_name` — is the **public** API the parsing
checks share (stdlib `subprocess`; the external `ssh` binary). The five checks:

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
  leaf's reason for diagnosis (stdlib `subprocess`, per-check timeout, the external
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
the library ships no store client. There is no bare-name form: a string without a
scheme is a *pasted secret* far more often than a name, so it is rejected at load
without being quoted back (ADR-0023's 2026-07-27 update). A malformed reference
raises `CheckError`, so the load fails loudly like any config typo; a well-formed
reference that fails to
resolve (store unreachable, secret absent) is recorded on the check's
`secret_errors`, and the engine **pins** such a check (§4.6). None of the built-in
check types takes a credential; the seam serves deployment checks (and later
satellites).

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
per path (`path: {about: …, title: …}`; a bare string is `about`). For the **subnodes a branch check emits**, a child `CheckResult` may
carry its own `about` / `title` — a third feed the engine applies at runtime
([ADR-0025](adr/0025-check-provided-subnode-metadata.md)), so the per-field precedence
there is `nodes.yaml` **>** check-provided **>** empty. Unlike the write-through
`description` / `config`, these **fill an empty field only**, and because the startup
seed runs before the engine's first tick a `nodes.yaml` label is already present and
wins; a check-provided label then freezes at first fill (stable identity — text that
changes each run belongs in `reason`). This carries **type-inherent** subnode identity —
`host-metrics` ships a per-aspect `about` for `ssh` / `disk` / `memory` / `cpu` / `load`
— so a reusable branch check explains its leaves in every deployment without per-node
`nodes.yaml` copy-paste. A
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
- `_execute` runs `check.run()`, maps any exception or timeout to `ERROR`, records
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
  clears what the last one found. A check with
  recorded `secret_errors` (§4.5) is
  **pinned**: `_execute` stores that `ERROR` ("secret unresolvable: …") without
  calling `run()` — no retry until restart, and no runtime recorded
  ([ADR-0023](adr/0023-secret-references.md)), so its run facts carry a real next
  slot and no wall time.
- `start()` / `stop()` are idempotent; threads are daemons. `run_once()` runs every
  check synchronously (for tests). `create_engine(config_dir)` loads checks into a
  new engine bound to `status_tree`; when the checks aspect resolves but is **empty**
  it still returns an engine, one whose every heartbeat carries a WARN naming the
  directories it searched (§7). `info()` returns runtime state for the `/system`
  page — uptime, pool size, check counts, and per check its type, the in-flight
  run (start + elapsed so far), the armed next slot (projected onto the wall
  clock) and the last completed run (start + wall time).
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
  left to an external supervisor (launchd / systemd / gunicorn restart).

`app.py` starts the engine once at import (post-fork worker), guarded by
`LITTLE_SISTER_ENGINE` (set `0` to disable); the dev server uses
`use_reloader=False` so it starts exactly once.

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
excluded, so nothing leaks pre-login). It is `None` on success and on the
deliberate `LITTLE_SISTER_ENGINE=0` disable, and clears only with a restart
against a fixed config. The JSON API carries no engine-health signal.

A hung check still occupies a pool worker (Python can't kill threads); the built-in
checks honour their own timeouts, and custom checks must too.

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
  content) but are **currently enabled** (ADR-0018 Update note); untrusted reasons
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

---

## 5. Web layer — `app.py`

### 5.1 Routes

| Route | Methods | Behavior |
|-------|---------|-----------|
| `/` | GET | Redirect to `/status`. |
| `/login`, `/logout` | GET, POST / GET | Session login (stores `username`, name, and an `admin` flag) / clears the session. |
| `/status`, `/status/<path:branch>` | GET | Renders the dashboard from a live snapshot (whole tree or a branch; the `path:` converter passes the slash-separated node path, ADR-0016). A **leaf** check renders its **detail** page. `hide_ok` / `hide_idle` filter the view; `depth` caps how deep the tree renders (clamped to `MAX_DEPTH`, remembered in a `depth` cookie); `fragment=1` returns just the grid (for the page's live polling). With `Accept: application/json` and a valid bearer token, the same routes return the subtree as JSON instead (ADR-0008). A **leaf** page also carries the node's own **hand-off** — the two clipboard buttons of `/copy` aimed at one node: the same document machinery (`copy_status.py`, one formatter for both) over what only this page knows — the path, the observation and the period it bounds, the next update, the run's wall time, the frequency, the report, the configuration and every reason line uncapped — each line with its own code cue and in-flight marker where it declared them, each instant naming its offset. A pin does not change it: the document keeps the **measurement** and says a pin is in force, rather than presenting the pinned code as the reading. Containers get no buttons — their hand-off is `/copy`. |
| `/history/<path>` | GET | A node's status history (Status / Since / Until / Reason). |
| `/maintenance` | GET, POST | **GET** — the full, uncapped maintenance overview as its own read-only page (the leaf-detail pattern), reached from the strip pill's "+N more": **one row per pin** — a node's own, or one of its reasons' ([ADR-0036](adr/0036-addressable-reasons.md)) — with the path, what the pin *silences* (the whole node, or one reason line), time left, rendered Markdown explaining *why* it is silenced, and authorship (*pinned by … , last changed by …*). *Silenced* and *Why* are two columns on purpose: both are called "reason" in the model and are not the same thing. An entry row links to its line as `/status/<branch>?reason=<slug>`; the slug is never rendered as text. **POST** — **admin only**: set/edit/clear a node's maintenance with a raw-Markdown reason and optional duration-or-expiry (blank uses the duration from `settings.yaml`), recording who set it. Unit-suffixed durations and full ISO date/times are accepted alongside `MM-DD`, a day-of-month, `HH:MM`, and weekday/time shortcuts; a bare weekday uses 12:00, and unzoned values use the configured timezone. The resolved expiry must be **at least one second and at most 365 days away**; invalid, past, ambiguous-DST or out-of-range input is refused with the admin's words returned, and a blank reason on an *edit* keeps the stored one ([ADR-0014](adr/0014-maintenance-persistence.md)). A `slug` field addresses **one reason** of the node instead of the node ([ADR-0036](adr/0036-addressable-reasons.md)) — never a path segment, since the natural slug for a discovered entry contains a `/`; redirects to the node — or back to the page the form was opened on, via a validated `next` (the card dialog's way home). Every form carries the entry's `set_at` as a hidden **compare-and-set token**, so a write against a pin someone else has since changed is **refused whole** and answered with the conflict page — both rendered stored text and the admin's raw source, who set the stored one and when, the admin's own words preserved and one click to take the stored ones instead ([ADR-0014](adr/0014-maintenance-persistence.md)). |
| `/events` | GET | The transition log, newest first (When / Status / Service / Reason). A transition that reached nobody is **shown and marked** with the contribution rule that held it back ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 5, [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)) — it keeps the status color it would have alarmed in, and the chip beside the code is what says it did not. Marked events are what makes *did it break during the window?* answerable, and they are excluded from `/history`, which answers the other question. |
| `/system` | GET | **Admin only** — engine uptime, pool size, check counts; per check its type and the in-flight / armed-next / last run, each a time of day plus interval. Carries the dashboard's freshness stamp and ~10s poll (`fragment=1` returns just the info block). Below it, outside the polled fragment because they are settled at startup: the **check-type roster** (§11) — the types this configuration runs first, each with the number of checks behind it, a count that opens into the node path of every one of them so it can be believed without reading a config file, the rest folded into a disclosure so a registered-but-unused type stays readable without filling the card — the **package inventory** (§11), one row per installation outside the library with its distribution, version, loaded path and everything it registered, because a version belongs to the *installation* and a package that registers no check type would otherwise have one nowhere on the page — both tables print that loaded path **against a root the reader has** (`paths.py`): `site-packages/…` or `./…` under the working directory, whichever root is the nearer, because the diagnostic it carries is *which root the module came from* rather than the absolute string, nine tenths of which is the same prefix on every row and starts with somebody's home directory (the origins and the hover `title` keep it whole; a path under neither root stays long, which is the signal) — the **extension seams** (which package fills which slot, which configuration aspects were registered, and who registered each one) and the **effective Content-Security-Policy**, directive by directive, with the contributor of every source — a request blocked inside somebody else's package is otherwise undebuggable from the running instance (§5.4, [ADR-0048](adr/0048-an-assembled-content-security-policy.md)). |
| `/about` | GET | The identity page — the gaze, the name and the reasoning behind it, the running instance's `__version__`, the repository link. Auth-gated like every other surface: it names the version of a live instance. |
| `/preferences` | POST | Records this browser's **theme** and **layout** (§5.3, [ADR-0029](adr/0029-per-user-presentation-preferences.md)) and redirects back to the posting page. A value outside the roster is dropped in favor of what the browser already had; the return path is validated by `_safe_next` (a single leading `/`, and none of the characters a browser rewrites into a second one), so the hidden field cannot become an open redirect. |
| `/copy`, `/copy/<path:branch>` | GET | Auth-gated incident hand-off, in three sizes from one route and one formatter: the **tree** (`/copy`), one **node** (`/copy/<branch>`) and one **reason line** (`/copy/<branch>?reason=<slug>` — the node a path, the entry a query value, [ADR-0036](adr/0036-addressable-reasons.md) decision 12, because a discovered entry's slug contains a `/`). A line's document is the line and just enough to locate it — the node's title, path and observation — and deliberately not the node's run facts, report or configuration, which the node's own document carries and which is where a secret reference would appear. An unmounted path and a slug this run does not report are both `404` with a page that says which: a suspended pin is not deleted, but a document made from its stored text would hand over a finding the check is no longer making. The tree document: one immutable root snapshot becomes one canonical Markdown document: every non-OK leaf (`WARN`, `ERROR`, `MAINTENANCE`, `UNDEFINED`) plus only the ancestors needed to locate it, in snapshot order; the synthetic root and wholly healthy branches are omitted. Leaves carry a non-colour emoji cue, and so does a **reason line that declared a code of its own** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) — a healthy workflow under a failing node has to read as healthy in a pasted document too, and a line that declared none takes no cue because it carries its node's. A line whose subject is **running** says so in words: the page's italic is the glance, and a document has none. Authored check and maintenance explanations keep their Markdown, while node/per-reason maintenance also names who set it and its expiry. Every instant it writes — a pin's expiry here, and the whole node document's time facts — names its **UTC offset**: the pages render local time and stay silent about the zone, which is right for a screen somebody is standing in front of, and wrong for a document read in another office. The page renders the rich preview through the same hardened Markdown renderer as every other surface. **Copy Markdown** writes `text/plain`; **Copy Rich HTML** writes both `text/html` and the Markdown as `text/plain`, falling back honestly to plain/manual selection when clipboard access is unavailable — the buttons are one partial (`_copy_controls.html`) shared with the leaf detail page, so the pair is named and ordered the same in both places, and the label names the clipboard member rather than claiming RTF. An all-OK tree gets an empty state rather than an empty clipboard action. |
| `/links` | GET | The **shared toolbox**: this deployment's curated links (§7, [ADR-0030](adr/0030-curated-links.md)), one flat level of groups flowed into columns, each entry a mark and a title in the configured order. Icons resolve through the search path; a name nothing defines falls through to the entry's own origin favicon and then to a neutral glyph. Structural problems in the file are shown on the page — the person who maintains it is the one looking. A **client-side filter** sits above the columns and narrows by entry and group title. The configuration is re-read only when it changed, so an edit needs no restart. Opening the page is also what **triggers a reachability pass** (§7) when the newest answer is older than the configured interval — on a daemon thread, so the render never waits on the network. |
| `/links/check` | POST | **Check now**: probes the links page's targets and redirects back to it, the return path validated by `_safe_next`. Unlike an open this one **waits**, under a deadline, joining the pass already running rather than starting a second — whatever has not answered by then keeps its previous verdict and age while the pass finishes behind the response, and the page says a pass is still going. A forced pass has a minimum gap, which is the whole of the abuse story; open to every logged-in viewer, not only an admin, because whoever maintains the file is not necessarily one (§7, [ADR-0030](adr/0030-curated-links.md)). |
| `/links/icon/<variant>/<name>` | GET | One resolved icon, for the background `variant` names (`on-light` / `on-dark`). Serves every rung of the search path that holds bytes — the deployment's own file, a registered pack's package data, the built-in pack — so the page has one URL shape for all of them; a **remote** icon is 404 here and is emitted as its own URL rather than proxied. The name is a registry key and never builds a path. Auth-gated, `private` cache with an ETag (§7, [ADR-0030](adr/0030-curated-links.md)). |
| `/user/avatar` | GET | The signed-in user's configured avatar, if any. Takes no username or path: the session selects a startup-resolved bare name inside the winning users aspect's `avatars/` sandbox, so the route cannot enumerate accounts or construct a filesystem path. Auth-gated, private five-minute cache with an ETag; a removed file falls back to the packaged neutral avatar ([ADR-0045](adr/0045-user-avatars.md)). |
| `/ext/<package>/<member>` | GET | One registered **extension asset** — a `.css` or `.js` file a dependent package ships for the slot it fills (§6.1, [ADR-0037](adr/0037-extension-static-assets.md)). Read through `importlib.resources` and looked up in the registry, so neither argument ever builds a path; the URL carries a content hash and the response is immutable. Login-gated like every other surface, and the kiosk layout loads none of it. |
| `/csp-report` | POST | Where a browser posts a **Content-Security-Policy violation**. Each report is one `WARNING` log line — the violated directive, the document, the blocked URI, the source and line — and nothing is stored, which is what keeps the policy clear of the persistence decision. The **one route with no login gate**, necessarily: a violation on the login page has no session, and a report the browser cannot deliver measures nothing. It is bounded instead — an oversized body is refused unread and each reported field is truncated before it reaches the log, because a blocked URI is whatever the page tried to load (§5.4, [ADR-0048](adr/0048-an-assembled-content-security-policy.md)). |
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
overrides the format, never the timezone), `url_branch`,
`markdown` / `markdown_inline` (server-side Markdown → safe HTML, §4.7), and
`breadcrumbs` (a path → cumulative `(name, path)` crumbs for the clickable header
trail, rendered by `_breadcrumb.html`; the current node stays plain). The dashboard
filter logic is `_filter_snapshot` (drops nodes whose effective code is hidden).

### 5.2 Authentication
- Session-based; the gate is `username` in `session`, checked per route.
- Users come from a flat `config/users.yaml`, or `config/users/users.yaml` beside
  `config/users/avatars/` (a map of `username → {firstname, lastname, password,
  admin?, avatar?}`), loaded once at import. `avatar` is a bare file name or stem;
  invalid, missing and ambiguous references warn and use the packaged neutral image
  without affecting login ([ADR-0045](adr/0045-user-avatars.md)).
- **viewer / admin roles** — `login` stores an `admin` flag; admin-only actions
  (set/clear maintenance, the system page) are gated on it.
- **Passwords are plaintext** (compared directly); hashing is planned.
- `secret_key` comes from **`SECRET_KEY`** — a literal value, or itself a secret
  reference resolved once at startup; **unset means a random per-start key**
  (sessions reset on restart)
  ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md),
  [ADR-0023](adr/0023-secret-references.md) update note). `.env` feeds the
  environment via a dependency-free loader.
- **JSON backend mode** — `GET /status[/<path:branch>]` with `Accept: application/json`
  is gated by a **bearer token** (named per-client tokens from the
  `LITTLE_SISTER_API_TOKENS` setting — a literal, or itself a secret reference —
  compared with `secrets.compare_digest`); the session
  cookie isn't accepted there. Errors are **Problem JSON** (RFC 9457), and an inbound
  `X-Flow-Id` is echoed. Read-only; the contract is
  [`api/openapi.yaml`](api/openapi.yaml) ([ADR-0008](adr/0008-json-output-api.md)).

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
  belongs to the one cookie.
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
- `about.html` — the identity page, built as **one hero** and centred in the
  window: the gaze, the wordmark and the version, with the terms she watches in
  orbit **behind the eyes** on two faint rings wider than the reading column, and a line at a time underneath — a couple of clauses, an
  observation, then the nine-line ending, after which it stops. The identity is
  told once here rather than three times (the bar, a block, and an animation with
  an eye of its own). Colour carries one meaning each: **green is seen** — spent
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
  space — a chip is something to click, a title is a nicety — while the state
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
  `_resolve_depth`). Nodes drill down; a **hide-ok** switch drops OK nodes and a
  **hide-idle** switch drops never-reported (UNDEFINED) ones; a **chips** switch (leaf density, default on) toggles the quiet-leaf chip collapse below off for a viewer who wants every leaf as a full box, and these view switches — like `depth` — persist across visits in a `SameSite=Lax` cookie set on an explicit change; **stale** nodes get a
  badge; a node with an unambiguous **observation time** — its own last
  write, or the run time of the single check below it — states *when* beside *what*, as
  a muted time of day (`settings.yaml`'s timezone, ADR-0006) sitting just before the cue
  and status word, and shows **nothing at all** where the question has no single answer
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)) — the absence is the
  signal, and the freshness *alarm* stays the stale badge, which is normalized per
  check frequency. The time shows on the **topmost node visible in the current
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
  warn/error box is never folded. Card heights are **bounded**: the reason caps from
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
  ADR-0005) is lifted out of the grid into a compact **status-strip pill** at the top
  (fit-content — a side note under the "updated …" line, not a page-wide
  banner); it renders inside the polled fragment, so it
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
  overwritten with a login form. A **sustained** outage escalates (ADR-0005
  update note): after six consecutive misses the line grows a legible age, a
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
  card, a **Report** card and a **Configuration**
  card, in that order — when it ran, what it found, what it ran with, outputs before
  inputs because the outputs are why the page was opened. Both texts go through the
  hardened Markdown renderer ([ADR-0018](adr/0018-markdown-rendering.md)), which
  `config` had been missing since before that renderer landed. The **Time** card
  never invents an instant
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)): it reads *from … until …*
  across the current status period — the **own**-status period, since that is what the
  event log bounds — falls back to a single *Observed …* where the node
  has no transition of its own to bound one, and says *Not yet observed* when no check
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
- `history.html` / `events.html` — the status-history and event-log tables, rows
  tinted by status (`row-*` classes in `overview.css`); a suppressed event carries the
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
  ([ADR-0034](adr/0034-template-slots-for-dependent-packages.md), amended). The
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
  ([ADR-0023](adr/0023-secret-references.md) update note).
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
  trigger: it is skipped wherever `LITTLE_SISTER_ENGINE=0` — which is exactly where
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
  the dashboard budgets `reason_cap` (default 6), `branch_cap` (default 3) and `maintenance_cap` (default 5) — the reason-line, quiet-sub-branch and maintenance-pin caps ([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)) — `maintenance_default_expiry` (default `7d`, the window applied when an admin
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
  §4.6), both overridable per check — loaded once into `config.py`'s `Config`
  ([ADR-0006](adr/0006-config-file-and-timezones.md)). Displayed timestamps are
  stored as server-local and converted to that timezone by the `localtime` filter
  (`zoneinfo` + `tzdata`); the same zone interprets maintenance expiry input that has
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

- **Maintenance** — admin maintenance pins (per node and per reason) persist to `var/maintenance.json`
  (git-ignored runtime state, a fixed path), restored at startup; durable storage of
  the rest of the tree is still deferred (§8, [ADR-0014](adr/0014-maintenance-persistence.md)).

---

## 8. Not implemented yet

Current gaps.

- **Persistence** — durable storage/retention of the **tree and history** (the
  in-memory log is bounded and lost on restart); only admin **maintenance** persists
  so far, to a file (§7, [ADR-0014](adr/0014-maintenance-persistence.md)).
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
- **Hashed passwords** (plaintext today) and a machine-readable health endpoint.

---

## 9. Known limitations

- A **hung check** ties up a pool worker until it returns (Python can't kill
  threads); built-in checks enforce their own timeouts.

---

## 10. Quality gates

`hooks/pre-commit` runs `uv run ruff check`, `uv run mypy`, `uv run pytest -q` and
blocks a commit on any failure (enable per clone with
`git config core.hooksPath hooks`). mypy targets `src/`.

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
(every relative Markdown link resolves). The suite passes under
Python 3.14 with ruff and mypy clean.

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
  a deployment runs under `gunicorn`.
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
  Registered in the same import-before-app slot as the rest.
- **Check-type registry** — `CHECK_TYPES` in `little_sister.checks` (§4.5). A
  deployment adds its own check *types* by importing them before
  `little_sister.app:app` — whether they are modules in its own tree or **installed
  packages**, which is the same seam and was always described as an evolution of it
  rather than a rewrite. That evolution has run: `little-sister-github`,
  `little-sister-wiz` and `little-sister-jira` register here from packages of their
  own (§2). Discovery *without* that import — an entry point — does not exist yet.
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
      CHECK_TYPES  Check  CheckError  CheckResult  Entry  register
      API_VERSION  require_api
      code  coerce_code  config_markdown  parse_duration  parse_secret_refs  plain
      expand_tokens  parse_subnodes  resolve_text
      CHECKS_ASPECT  checks_dirs  load_checks
  little_sister.reasons
      Entry  MAX_SLUG_LENGTH  ReasonError  derived_slug  normalize  slug
  little_sister.status
      StatusCode  join_path
  little_sister.values
      flag  number  real  rows  text
  little_sister.spans
      coarse_span  format_duration  format_span
  little_sister.transport
      Deadline  DeadlineExceeded  Fault  RemoteError  ask
  little_sister.fetch
      Response  fault_for  fetch  retry_after
  ```

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

  `little_sister.transport` is on the list because a check that reads a remote service
  has to answer four things before it can report anything — how long one request may
  take, what bounds a run that asks fifty times, what is worth asking again, and what
  a failure *means* — and nothing on this surface used to say a word about any of them,
  so every such check answered all four for itself
  ([ADR-0058](adr/0058-transport-policy-vocabulary.md)). It promises the **policy** and
  no client: `Deadline` (whose `budget(timeout)` clamps a per-request timeout to what
  the run has left, which is what makes `timeout:` a bound — the engine does not bound
  `run()`, §4.6), `DeadlineExceeded` (outside `RemoteError` on purpose, so a per-item
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
  and merely being described (ADR-0058, amended 2026-08-16).

  Three limits of it, stated rather than implied. The clock bites **only when a deadline
  is given**. A caller passing `read_body=False` has no body read to bound, so a deadline
  buys it nothing — which is why **neither built-in caller passes one**: the `http` check
  makes a single request and reads no body, and the link prober bounds a hung probe by
  abandoning the pass. And the clock does not reach the **status line and headers**, which
  urllib reads inside its own opener before this module is handed a stream; a server
  trickling *those* is bounded only by the socket timeout per read, which is the residual
  for every caller.

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
  **1**. It bumps when a name above is removed or renamed, or a documented behavior
  changes; adding a name does not bump it, and neither does anything else in a
  release. A package declares the epoch it was built for with `require_api(1)` beside
  its registrations, and a mismatch refuses at startup naming both numbers
  ([ADR-0051](adr/0051-what-startup-refuses.md)). The install-time floor a package
  declares (`little-sister >= x`) keeps a *too old* library out; the epoch catches the
  upgrade the floor cannot see. `tests/fixtures/check_api_v1.txt` snapshots what
  epoch 1 promises, and the gate requires the current block to still contain all of
  it — so a name cannot leave without the epoch moving, which is the hole a
  doc-and-code rename would otherwise slip through.

  A **type name is claimed once**, and stays bare (`type: github`): two packages
  registering one name refuse at startup naming both classes, rather than letting
  import order decide whose code answers for somebody else's configuration
  ([ADR-0051](adr/0051-what-startup-refuses.md)). `/system` lists every registered
  type with the package and version that answers for it, and beside it every
  registering package once — a check type is only one of four seams a package can
  arrive through (a slot filler, an asset, a configuration aspect are the others),
  and the release that answers for it belongs to the installation rather than to
  the seam. `origins.py` is the single lookup both read, and `paths.py` the single
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
  `register_resolver(scheme, resolver)` / `resolve_setting(value)` (an app setting
  whose value may be a reference), the reference syntax itself (`scheme://address`,
  with no bare-name form), and `Check.resolve_secret` (resolve at construction,
  pin on failure — [ADR-0023](adr/0023-secret-references.md)). A deployment registers
  its resolvers in the same import-before-app slot as its check types.
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
  (disable the engine, e.g. in tests). The retired `LITTLE_SISTER_USERS` is part of the
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
