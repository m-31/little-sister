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
| Dependencies | Flask, gunicorn, PyYAML, markdown-it-py only — checks use the standard library (the SSH checks shell out to the external `ssh` binary) |
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
│   ├── checks/          # check configs (*.yaml), scripts/, examples/, README
│   ├── links.yaml       # curated links (or links/ once it ships icon files)
│   ├── nodes.yaml       # node metadata, keyed by node path
│   ├── settings.yaml    # general options (timezone, time_format)
│   └── users.yaml       # the login list (gitignored)
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
│   ├── watch_lines.py   # what /about's hero says: the pools a render draws from
│   ├── icons.py         # icon names, the pack registry, where the bytes are
│   ├── icon_pack/       # the built-in marks (our own drawn glyphs) + manifest
│   ├── nodes.py         # the `nodes` aspect's metadata + startup consistency pass
│   ├── render.py        # safe server-side Markdown → HTML (markdown-it-py)
│   ├── slots.py         # template slots a dependent package fills (ADR-0034)
│   │                    # and the assets it ships for them (ADR-0037)
│   ├── actions.py       # the declarative action list, config/actions.yaml (ADR-0038)
│   ├── logger.py        # root logging (stdout + log file)
│   ├── users.example.yaml  # sample login list — the real one is a config aspect
│   ├── templates/       # Jinja2 pages
│   └── static/          # CSS, the page JS (poll, popover, reason overflow, rail), favicons, webmanifest
└── tests/               # test_status, test_tree, test_checks, test_render, test_values, test_engine, test_web
```

Everything a deployment authors lives under `config/`, and everything the process
writes lives under `var/` ([ADR-0031](adr/0031-deployment-config-directory.md)); the
one exception either way is `.env`, which is secrets read before anything else
([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). `config/users.yaml` is
git-ignored and supplied per deployment; the package ships only a sample.

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
children (its member reason entries) are all pinned reads `MAINTENANCE`
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
  result root to, and so re-stamps on every run. A registry only (a `set[str]`) — it
  creates no node, so the tree's visible shape still grows only with results — read
  solely by the timestamp roll-up in `snapshot()` below. The engine seeds it at
  construction from its checks (§4.6), which keeps the tree itself check-agnostic; two
  checks sharing one mount register one entry, since the roll-up counts mounts rather
  than checks ([ADR-0027](adr/0027-observation-timestamp-semantics.md)).
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
  comparison is exact — one process, one lock. Maintenance is held in a **side-table**
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
  each unsuppressed one contributes the reported status, a suppressed one contributes
  nothing, and a node with none left presents `MAINTENANCE` too. Prose and reason-less
  nodes stay outside the entry rule. What the check actually said survives beside the
  derivation as the snapshot's `reported_code`, so a card can say `maintenance ·
  error` and show the failure text under the pin's banner
  ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 5: a transformed
  contribution stays visible and attributable). Staleness judges the **raw** reading
  and is never suppressed, so a check that stopped running escalates whichever policy
  is holding its result back (rule 6) — a pin quiets a known state, it does not cover
  a dead check. This is the one transform that turns a stored reading into an own
  status, and both grains of maintenance now live inside it rather than beside it.
- `snapshot(path="", now=None)` — an immutable `StatusSnapshot` copied under the
  lock. It **orders siblings** by name — natural and case-insensitive, so `node2`
  precedes `node10` (`_sort_key`) — at every level, so the dashboard and the JSON
  envelope read a deterministic order while the live tree keeps insertion order
  (decisions.md, "Node sibling ordering"). It also computes **freshness** (ADR-0005):
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
`{slug: text}` mapping or `(slug, text)` pairs, normalized in `__post_init__` into
`reason_entries`. A mapping or a pairs list declares its entries **members** — an
admin can silence one of them — and a list of strings needs `entries=True` to say
the same; everything else is **prose**, keyed like all reasons but suppressible only
as a whole node. `reasons.py` owns the normalization and the content-hash slug
(`h-` + ten hex digits) an undeclared entry gets. Most checks return a
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

- **`http`** — GET a URL; OK when the status is in `expected_status` (stdlib `urllib`).
- **`file`** — heartbeat: OK while a file's mtime is within `max_age` (default 20m),
  else `stale_code`. Relative `file` paths resolve under the executing user's `$HOME`.
- **`command`** — run a shell string or argv; OK on exit 0; reason = captured
  `stdout` / `stderr` / `both`, shortened to `max_chars` from `tail` / `head`
  (stdlib `subprocess`, per-check timeout).
The **SSH family** runs over one transport, `SshConnection` (`checks/ssh/transport.py`):
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

The family lives in the `checks/ssh/` package: `transport.py` (`SshConnection`),
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
`config/checks/` ships `examples/`, `scripts/` and a `README`.

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
  check's frequency (ADR-0007). A check with recorded `secret_errors` (§4.5) is
  **pinned**: `_execute` stores that `ERROR` ("secret unresolvable: …") without
  calling `run()` — no retry until restart, and no runtime recorded
  ([ADR-0023](adr/0023-secret-references.md)).
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
The node text fields (`title`, `about`, leaf `description`, each `reason`) are
authored in Markdown and rendered **server-side** to HTML, exposed to templates as
the `markdown` (block) and `markdown_inline` (one-line, no `<p>`) Jinja filters
([ADR-0018](adr/0018-markdown-rendering.md)).

- `render.py` wraps a single **markdown-it-py** instance configured *safe by
  default*: raw HTML is **escaped** (`html=False`), link schemes are validated (so
  `javascript:` / unsafe `data:` never become links), and every link gets
  `rel="noopener noreferrer"`. **Images** were initially disabled (beacons / mixed
  content) but are **currently enabled** (ADR-0018 Update note); untrusted reasons
  stay safe because `plain()` / `code()` escape `[` / `]`, so the exposure is the
  operator-authored fields. No CSP or second sanitizer — the renderer itself is the
  trust boundary. Templates wrap rendered output in `.md-body`, whose CSS collapses
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
  JSON envelope carries.

---

## 5. Web layer — `app.py`

### 5.1 Routes

| Route | Methods | Behavior |
|-------|---------|-----------|
| `/` | GET | Redirect to `/status`. |
| `/login`, `/logout` | GET, POST / GET | Session login (stores `username`, name, and an `admin` flag) / clears the session. |
| `/status`, `/status/<path:branch>` | GET | Renders the dashboard from a live snapshot (whole tree or a branch; the `path:` converter passes the slash-separated node path, ADR-0016). A **leaf** check renders its **detail** page. `hide_ok` / `hide_idle` filter the view; `depth` caps how deep the tree renders (clamped to `MAX_DEPTH`, remembered in a `depth` cookie); `fragment=1` returns just the grid (for the page's live polling). With `Accept: application/json` and a valid bearer token, the same routes return the subtree as JSON instead (ADR-0008). |
| `/history/<path>` | GET | A node's status history (Status / Since / Until / Reason). |
| `/maintenance` | GET, POST | **GET** — the full, uncapped maintenance overview as its own read-only page (the leaf-detail pattern), reached from the strip pill's "+N more": **one row per pin** — a node's own, or one of its reasons' ([ADR-0036](adr/0036-addressable-reasons.md)) — with the path, what the pin *silences* (the whole node, or one reason line), time left, *why* it is silenced, and authorship (*pinned by … , last changed by …*). *Silenced* and *Why* are two columns on purpose: both are called "reason" in the model and are not the same thing. An entry row links to its line as `/status/<branch>?reason=<slug>`; the slug is never rendered as text. **POST** — **admin only**: set/edit/clear a node's maintenance with a reason and optional duration (default from `settings.yaml`), recording who set it. A duration must be **positive and at most a year**; anything else is refused with the admin's words returned, and a blank reason on an *edit* keeps the stored one ([ADR-0014](adr/0014-maintenance-persistence.md)). A `slug` field addresses **one reason** of the node instead of the node ([ADR-0036](adr/0036-addressable-reasons.md)) — never a path segment, since the natural slug for a discovered entry contains a `/`; redirects to the node — or back to the page the form was opened on, via a validated `next` (the card dialog's way home). Every form carries the entry's `set_at` as a hidden **compare-and-set token**, so a write against a pin someone else has since changed is **refused whole** and answered with the conflict page — both texts, who set the stored one and when, the admin's own words preserved and one click to take the stored ones instead ([ADR-0014](adr/0014-maintenance-persistence.md)). |
| `/events` | GET | The transition log, newest first (When / Status / Service / Reason). A transition that reached nobody is **shown and marked** with the contribution rule that held it back ([ADR-0032](adr/0032-status-contribution-boundary.md) rule 5, [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)) — it keeps the status color it would have alarmed in, and the chip beside the code is what says it did not. Marked events are what makes *did it break during the window?* answerable, and they are excluded from `/history`, which answers the other question. |
| `/system` | GET | **Admin only** — engine uptime, pool size, check counts; per check its type and the in-flight / armed-next / last run, each a time of day plus interval. Carries the dashboard's freshness stamp and ~10s poll (`fragment=1` returns just the info block). |
| `/about` | GET | The identity page — the gaze, the name and the reasoning behind it, the running instance's `__version__`, the repository link. Auth-gated like every other surface: it names the version of a live instance. |
| `/preferences` | POST | Records this browser's **theme** and **layout** (§5.3, [ADR-0029](adr/0029-per-user-presentation-preferences.md)) and redirects back to the posting page. A value outside the roster is dropped in favor of what the browser already had; the return path is validated by `_safe_next` (a single leading `/`, and none of the characters a browser rewrites into a second one), so the hidden field cannot become an open redirect. |
| `/copy` | GET | Auth-gated stub (not built). |
| `/links` | GET | The **shared toolbox**: this deployment's curated links (§7, [ADR-0030](adr/0030-curated-links.md)), one flat level of groups flowed into columns, each entry a mark and a title in the configured order. Icons resolve through the search path; a name nothing defines falls through to the entry's own origin favicon and then to a neutral glyph. Structural problems in the file are shown on the page — the person who maintains it is the one looking. A **client-side filter** sits above the columns and narrows by entry and group title. The configuration is re-read only when it changed, so an edit needs no restart. Opening the page is also what **triggers a reachability pass** (§7) when the newest answer is older than the configured interval — on a daemon thread, so the render never waits on the network. |
| `/links/check` | POST | **Check now**: probes the links page's targets and redirects back to it, the return path validated by `_safe_next`. Unlike an open this one **waits**, under a deadline, joining the pass already running rather than starting a second — whatever has not answered by then keeps its previous verdict and age while the pass finishes behind the response, and the page says a pass is still going. A forced pass has a minimum gap, which is the whole of the abuse story; open to every logged-in viewer, not only an admin, because whoever maintains the file is not necessarily one (§7, [ADR-0030](adr/0030-curated-links.md)). |
| `/links/icon/<variant>/<name>` | GET | One resolved icon, for the background `variant` names (`on-light` / `on-dark`). Serves every rung of the search path that holds bytes — the deployment's own file, a registered pack's package data, the built-in pack — so the page has one URL shape for all of them; a **remote** icon is 404 here and is emitted as its own URL rather than proxied. The name is a registry key and never builds a path. Auth-gated, `private` cache with an ETag (§7, [ADR-0030](adr/0030-curated-links.md)). |
| `/favicon.ico` | GET | Redirect to the static favicon. |

Jinja filters back the views: `status_slug` (a CSS class suffix per code),
`status_alert` (a Bootstrap alert class), `shorten`, `duration`, `elapsed`
(a run's wall time: `412 ms` / `3.1 s` / `43 s`; `—` for none), `localtime`
(renders a timestamp in the configured timezone, §7 — an optional argument
overrides the format, never the timezone), `url_branch`,
`markdown` / `markdown_inline` (server-side Markdown → safe HTML, §4.7), and
`breadcrumbs` (a path → cumulative `(name, path)` crumbs for the clickable header
trail, rendered by `_breadcrumb.html`; the current node stays plain). The dashboard
filter logic is `_filter_snapshot` (drops nodes whose effective code is hidden).

### 5.2 Authentication
- Session-based; the gate is `username` in `session`, checked per route.
- Users come from `config/users.yaml` (a flat map of `username → {firstname, lastname,
  password, admin?}`), loaded once at import.
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
  before anything paints. Every other theme needs no script at all.
- The **kiosk** is the one layout the server branches on (`_header.html` omits the
  bar and the rail outright, and emits `_kiosk_line.html` instead); `rail` and
  `topbar` are the same markup, with CSS deciding whether the sections show in the
  rail or in the bar.

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
  to whatever it says.
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
- `_settings_menu.html` — the current user's name opens it: **theme** and **layout**
  as radio circles that post to `/preferences` (§5.3) with the current page as the
  return path, a grayed "settings…" reserving the later per-user overrides of
  `settings.yaml`, and **Logout**, which moved in here (the bar lost its red button).
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
  band; its line carries the stamp instead, so the page still has exactly one.
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
  red/green color-blind viewer can still separate error from OK. The card and strip
  glyphs are decorative (`aria-hidden`) — their status word already speaks — but a
  **warn/error node box** has no word, so its cue is named for a screen reader
  (`role="img"` + an `aria-label` of the state, WCAG 1.1.1). When the tree is
  collapsed by depth, the deepest *visible* node
  in a branch stays bold (it now carries the reason). A **depth** input in the
  filter bar sets how many levels below the viewed node render — the node itself is
  level 0, so depth 0 collapses to a single card carrying that node's rolled-up
  status (an overall traffic light), depth 1 shows its top-level systems, and so on.
  It is clamped to `MAX_DEPTH` and remembered in a `depth` cookie (resolved by
  `_resolve_depth`). Nodes drill down; a **hide-ok** switch drops OK nodes and a
  **hide-idle** switch drops never-reported (UNDEFINED) ones; a **chips** switch (leaf density, default on) toggles the quiet-leaf chip collapse below off for a viewer who wants every leaf as a full box, and these view switches — like `depth` — persist across visits in a `SameSite=Lax` cookie set on an explicit change; **stale** nodes get a
  badge; a card whose node has an unambiguous **observation time** — its own last
  write, or the run time of the single check below it — states *when* beside *what*, as
  a muted time of day (`settings.yaml`'s timezone, ADR-0006) sitting just before the cue
  and status word, and shows **nothing at all** where the question has no single answer
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)) — the absence is the
  signal, and the freshness *alarm* stays the stale badge, which is normalized per
  check frequency; a node's short `title` (ADR-0017) follows the name (ellipsed, `.node-title`) on
  a card and the breadcrumb in the page header; and a branch view shows the viewed
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
  both surfaces offer the set form too, prefilled with the stored reason and labeled
  *Save changes*, beside *Clear* — editing a window is not clearing and re-setting it;
  duration stays unfilled, so blank means the configured default exactly as it does on
  an unpinned node. The card is also where the pin's whole reading lives — *pinned by
  Anna …, last changed by Ben …* — while the popover, having room for one name, shows
  the last writer; the kiosk layout shows
  neither control, and the overview root deliberately carries no form — silencing
  everything stays a curl, not a click.
  To keep the everyday grid balanced **without moving cards**
  ([ADR-0024](adr/0024-dashboard-layout.md)), a card's **quiet leaves** (OK or idle) collapse
  to compact name+color **chips** — an all-green host converges toward a wrapping
  chip row instead of a stack of boxes — while a **warn/error** leaf keeps its full
  box and reason so a problem stays legible; chips flow inline, so a run of quiet
  siblings packs and a problem box breaks the line, preserving sibling order (a
  chip's own reason is a click away on its leaf page — the popover still shows
  title/about). In that same dense view a branch also **caps the quiet sub-branch
  boxes** it shows to a configurable budget (`branch_cap`), folding the surplus behind
  an in-place **"+N more"** (`static/js/branches.js` keeps the reveal open across the ~10s poll swap) so a deeply-nested card can't tower over the grid — a
  warn/error box is never folded. Card heights are **bounded**: the reason caps from above, a
  `min-height` floor from below. The engine's own **heartbeat** (`/little-sister`,
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
  ([ADR-0012](adr/0012-node-metadata.md)), status + reason, a **Time** block, the check
  frequency, a **Configuration** card of the parameters the check ran with when present
  ([ADR-0013](adr/0013-check-config-on-node.md)), History button, a per-reason
  admin pin on a node whose reasons are members ([ADR-0036](adr/0036-addressable-reasons.md)) —
  a silenced line stays visible in the maintenance tint, says who silenced it and
  until when, and the node states how many of its reasons are quiet — admin maintenance
  form). The **Time** block never invents an instant
  ([ADR-0027](adr/0027-observation-timestamp-semantics.md)): it reads *from … until …*
  across the current status period, falls back to a single *Observed …* where the node
  has no transition of its own to bound one, and says *Not yet observed* when no check
  has written it.
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
  the page never becomes the reason a Content-Security-Policy cannot be turned on.
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
  with `node`, the **unshortened** `reason`, its `index` and the `surface`
  (`grid` / `check`). The place for an action about **one** finding, where a node's
  reasons are individually addressable members.
- **`node.actions`** — in a card head on the dashboard grid (cards only, like the pin
  control) and beside the status on a leaf's own page, with `node` and `surface`. The
  place for an action about the **whole node**, which is where it belongs when the
  reasons are *prose*: a failure message and its stack trace are one condition in
  several paragraphs, and a per-line control there would offer to raise a ticket about
  a stack trace.

Both are offered on **every** node; a provider returning `None` is how a filler
declines one, so placement policy stays with the extension rather than being baked into
our templates. Core emits the `.reason-actions` / `.node-actions` rail and styles the
`.reason-action` / `.node-action` chip, so two extensions look like one product; a rail
collapses when nothing filled it. The `slot()` template global lives in `app.py` rather
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
- **Aspects a dependent package added** — `config_dir.register_aspect(name, …)` lets
  an extension declare a `config/<name>.yaml` of its own
  ([ADR-0035](adr/0035-registering-a-config-aspect.md)), so its operator-editable
  parameters sit in the same tree and layer through the same path-list. The library's
  own aspects are the floor and cannot be redefined; the document's schema and
  validation belong entirely to the package that registered it, and the name shows on
  `/system`.
- **Users** — `config/users.yaml`, a flat map keyed by username with `firstname`,
  `lastname`, `password` and an optional `admin: true`. Git-ignored, and the one
  aspect that does **not** merge across roots: the first root declaring it wins
  whole, a second is a warning ([ADR-0020](adr/0020-user-list-location.md),
  [ADR-0031](adr/0031-deployment-config-directory.md)).
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
  checks, URLs that rot on a redesign, one CSP entry per host, and nothing at all for
  a deployment without outbound access. Each name ships
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
  the dashboard budgets `reason_cap` (default 6), `branch_cap` (default 3) and `maintenance_cap` (default 5) — the reason-line, quiet-sub-branch and maintenance-pin caps ([ADR-0024](adr/0024-dashboard-layout.md)) — `maintenance_default_expiry` (default `7d`, the window applied when an admin
  gives no explicit duration — ADR-0014), `stacktrace` (default **true** — a failing
  check's trace on its node, §4.6) and the **failure retry** — `retry_interval` /
  `retry_attempts` (default off / 2; [ADR-0033](adr/0033-budgeted-failure-retry.md),
  §4.6), both overridable per check — loaded once into `config.py`'s `Config`
  ([ADR-0006](adr/0006-config-file-and-timezones.md)). Displayed timestamps are
  stored as server-local and converted to that timezone by the `localtime` filter
  (`zoneinfo` + `tzdata`).
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
- The `/copy` page.
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
`test_checks.py` (the http/file/command checks + loader), the SSH family —
`test_ssh.py` (transport, connect/command/script), `test_host_metrics.py`,
`test_qnap_metrics.py` and `test_metrics_scripts.py` (the bundled shell scripts),
`test_config.py` (general config), `test_secrets.py` (secret references: resolution,
the resolver registry, the engine's pinned-ERROR path), `test_reasons.py` (keyed
entries: prose vs members, slug stability, the check-facing forms),
`test_slots.py` (the slot roster, the loader's sandbox, containment, and the asset
seam of ADR-0037), `test_actions.py` (the declarative list: loading, templating,
percent-encoding and the `under:` filter),
`test_maintenance.py` (the maintenance side-table store and its file), `test_nodes.py` (nodes.yaml loading, `about` precedence, the consistency
pass), `test_engine.py` (scheduling, concurrency, `info()`),
`test_web.py` (the routes via the Flask test client), `test_api.py` (the JSON
backend: serialization, content negotiation, token auth), and `test_docs_links.py`
(every relative Markdown link resolves). The suite passes under
Python 3.14 with ruff and mypy clean.

---

## 11. Public API surface — the version contract

A deployment pins little-sister to a semver tag
([ADR-0022](adr/0022-generated-release-branch.md)), so a library upgrade is a
deliberate version bump rather than silent drift — which only works if the
surface it depends on is explicit. A tag promises to keep these stable:

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
- **Configuration aspects** — `little_sister.config_dir`: `register_aspect(name, …)`
  plus the reading helpers a registered aspect then uses, `aspect_files(name)` and
  `sole_aspect_file(name)` ([ADR-0035](adr/0035-registering-a-config-aspect.md)).
  Registered in the same import-before-app slot as the rest.
- **Check-type registry** — `CHECK_TYPES` in `little_sister.checks` (§4.5). A
  deployment adds its own check *types* in-source by importing them before
  `little_sister.app:app`; packaging them as installable plugins later is an
  evolution of this, not a rewrite. The developer how-to is
  [`implementing-checks.md`](implementing-checks.md).
- **Secret references** — `little_sister.secrets`: `resolve(reference)` /
  `register_resolver(scheme, resolver)` / `resolve_setting(value)` (an app setting
  whose value may be a reference), the reference syntax itself (a bare env-var
  name, or `scheme://address`), and `Check.resolve_secret` (resolve at construction,
  pin on failure — [ADR-0023](adr/0023-secret-references.md)). A deployment registers
  its resolvers in the same import-before-app slot as its check types.
- **Environment contract** — how a deployment points the library at its own config
  in the working directory: `LITTLE_SISTER_CONFIG_DIR` (the configuration path-list —
  checks, node metadata, settings and users,
  [ADR-0031](adr/0031-deployment-config-directory.md)),
  `LITTLE_SISTER_USERS` (a single user-list file, bypassing layering,
  [ADR-0020](adr/0020-user-list-location.md)),
  `LITTLE_SISTER_SCRIPTS_DIR` (metrics-script overrides,
  [ADR-0021](adr/0021-script-resolution.md)), `LITTLE_SISTER_CONFIG` (a single
  settings file, bypassing layering),
  `LITTLE_SISTER_API_TOKENS` (JSON-API bearer tokens), and `LITTLE_SISTER_ENGINE`
  (disable the engine, e.g. in tests). Defaults and formats are in §7.

A version bump is *for* changes to these; everything else — internal modules,
template markup, exact HTML — may move between releases.
