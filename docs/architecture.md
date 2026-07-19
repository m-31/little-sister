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
├── checks/              # check configs (*.yaml), scripts/, examples/, README
├── config.yaml          # general options (timezone, time_format)
├── src/little_sister/
│   ├── app.py           # Flask app: routing, login, .env load, engine start
│   ├── api.py           # JSON serialization for backend mode (ADR-0008)
│   ├── status.py        # Status / StatusCode domain model + roll-up
│   ├── tree.py          # the shared, thread-safe StatusTree, event log, history
│   ├── checks/          # Check base + http/file/command + ssh/ family + loader
│   ├── engine.py        # scheduler + thread pool: runs checks → upserts the tree
│   ├── config.py        # general config (config.yaml) → Config
│   ├── secrets.py       # secret references → values; resolver registry (ADR-0023)
│   ├── maintenance.py   # maintenance side-table persistence (var/maintenance.json)
│   ├── nodes.py         # nodes.yaml `about` metadata + startup consistency pass
│   ├── render.py        # safe server-side Markdown → HTML (markdown-it-py)
│   ├── logger.py        # root logging (stdout + log file)
│   ├── users.yaml       # local user list (gitignored; a sample is committed)
│   ├── templates/       # Jinja2 pages
│   └── static/          # CSS, the inspection-popover JS, favicons, webmanifest
└── tests/               # test_status, test_tree, test_checks, test_render, test_engine, test_web
```

`users.yaml` is git-ignored and supplied per deployment; the in-package copy is a
sample.

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
- `reason: list[str]` — a bare string is wrapped into a one-element list.
- `timestamp: str` — the **observation time** (ISO-8601), set at construction and
  re-stamped by `update()` / `touch()`.
- `description: str`, `frequency_seconds: int | None`, `config: str` — metadata
  inherited from the check and set by the tree; `config` is the curated parameters
  the check ran with, as Markdown ([ADR-0013](adr/0013-check-config-on-node.md)).
- `about: str` — **subject** metadata: what the node *is* (location, kind, context),
  distinct from `description` (what its check does); Markdown, seeded at startup from
  `nodes.yaml` / the owning check ([ADR-0012](adr/0012-node-metadata.md)).
- `title: str` — a **short display label**, briefer than `about`; same sources and
  seeding ([ADR-0017](adr/0017-node-title.md)).
- `maintenance: bool` — a sticky admin override; while `True` the tree refuses to
  overwrite the code.
- `__children: OrderedDict[str, Status]` — keyed by child `name`.

Methods: `update(code, reason)` (record an observation), `touch()` (re-stamp only),
`add_child(child)` (enforces `child.path == f"{self.path}.{self.name}"`),
`get_children()`, and `get_status_code()` (§4.3). Code/reason coercion is factored
into `_coerce_code` / `_coerce_reason`.

### 4.3 Aggregation (roll-up)
`get_status_code()` rolls a node's effective status up from itself and its children
per [ADR-0004](adr/0004-status-aggregation-semantics.md):

```python
if self.code == StatusCode.MAINTENANCE:
    return StatusCode.MAINTENANCE          # subtree cancelled; parent ignores it
counted = []
if self.code != StatusCode.UNDEFINED:
    counted.append(self.code)
for child in self.__children.values():
    c = child.get_status_code()
    if c in (StatusCode.MAINTENANCE, StatusCode.UNDEFINED):
        continue                           # ignored when accumulating
    counted.append(c)
return max(counted, key=severity) if counted else StatusCode.UNDEFINED
```

Severity is `ERROR > WARN > OK`; it always returns a `StatusCode`; `UNDEFINED`
(a not-yet-reported leaf) is ignored; `MAINTENANCE` cancels its subtree and is
ignored by its parent.

### 4.4 Status tree, event log & history — `tree.py`
The single in-memory state everything hangs off (ADR-0001/0002). `StatusTree`
holds one root `Status` and a bounded `deque` of `Event`s behind one `RLock`.

- `upsert(path, code, reason, *, description=None, frequency_seconds=None,
  config=None)` — create-or-update a node by absolute path (intermediate nodes
  auto-created), store the inherited metadata, and append a transition `Event`
  **only when the node's own code changes**. `config` is static display metadata
  (the check's parameters, [ADR-0013](adr/0013-check-config-on-node.md)) — stored
  when given, never a transition. A node **in maintenance** keeps its code (only its
  check time refreshes).
- `set_maintenance(path, reason, *, expires_at, set_by)` / `clear_maintenance(path)`
  — the admin override: set pins the node to `MAINTENANCE` (sticky) until
  `expires_at`, recording who set it; clear reverts to `UNDEFINED` until the next
  check. Both record events. Maintenance is held in a **side-table**
  (`path → MaintenanceEntry`) kept in sync with each node's `maintenance` bool and
  **written through** to `var/maintenance.json` via an injected `MaintenanceStore`
  ([ADR-0014](adr/0014-maintenance-persistence.md)). `restore_maintenance` replays it
  post-fork at startup (dropping expired); `reap_uncovered` drops pins no check root
  covers (segment-wise — the `status.on_same_line` predicate shared with ADR-0015);
  and `sweep_expired`, run each scheduler tick, clears entries past their window as a
  real transition.
- `history(path)` — the node's **status history** as `StatusPeriod`s (code, since,
  until, reason), derived from the event log; the current period's `until` is the
  last check time.
- `snapshot(path="", now=None)` — an immutable `StatusSnapshot` copied under the
  lock. It **orders siblings** by name — natural and case-insensitive, so `node2`
  precedes `node10` (`_sort_key`) — at every level, so the dashboard and the JSON
  envelope read a deterministic order while the live tree keeps insertion order
  (decisions.md, "Node sibling ordering"). It also computes **freshness** (ADR-0005):
  a node not observed within ~2× its `frequency` is flagged `stale` and its `code` is
  degraded to at least `WARN` (worse-of, rolled up). `effective()` and the event log
  stay raw — the aggregation rule itself is the reusable `status.effective_code`.
- `effective(path)` rolls up; `recent_events(limit)` reads the log.

A module-level singleton `status_tree` is the one shared instance: the engine
writes to it, the web layer reads snapshots from it. `StatusSnapshot`, `Event` and
`StatusPeriod` are frozen dataclasses.

### 4.5 Checks — `checks/` package
A check returns a `CheckResult` — a **recursive value** (`code`, `reason`, and
optional `name` / `description` / `config` / `children`). Most checks return a
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
  checks specialise (they parse the output instead of returning it).
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

`load_checks(spec)` reads every `*.yaml` / `*.yml` across **one or more**
directories and instantiates the matching check; sub-folders like `scripts/` are
ignored and a config's relative paths (e.g. a `script`) resolve against its own
directory. `LITTLE_SISTER_CHECKS_DIR` (default `checks/`) is a **path-list** — one
directory, or several joined by the OS path separator (`base:hosts/alpha`) —
loaded as a **union**: a shared base plus host-specific additions, no copy-paste.
Each listed directory must exist, and the set is fixed for the process — a restart
re-reads it ([ADR-0015](adr/0015-check-discovery-union.md)). The on-disk `checks/`
ships `examples/`, `scripts/` and a `README`.

Each check declares the nodes it owns — `owned_nodes()`, the subtrees it gives a
definite status to (a leaf its own node; a **branch** check its child subtrees, not
the shared container it merely rolls up). The loader **rejects** a union in which
two checks own **overlapping** nodes — equal, or one a segment-wise ancestor of the
other — naming the path and files, so a duplicated or shadowing check fails loudly.
Disjoint owners share a host node freely: `host-metrics` + `qnap-metrics`,
`host-metrics` + `macos-memory`, or a `file` heartbeat as a sibling child (e.g.
`/macmini/findmy` beside the metric leaves), but **not** a leaf placed on the
container itself ([ADR-0015](adr/0015-check-discovery-union.md)).

**Secret references** (`secrets.py`, [ADR-0023](adr/0023-secret-references.md)): a
check config field that carries a credential is a **reference**, resolved through
`little_sister.secrets` **once, in the check's constructor**
(`Check.resolve_secret`) and held for the process lifetime — never re-read during
runs. A bare name (`GITHUB_TOKEN`) is an environment-variable lookup (fed by
`.env`, ADR-0003); a `scheme://address` reference is resolved by the resolver the
**application registered** via `register_resolver(scheme, …)` before importing
`little_sister.app` — the same import slot that registers deployment check types;
the library ships no store client. An unknown scheme raises `CheckError`, so the
load fails loudly like any config typo; a well-formed reference that fails to
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
`NodeMeta`). `nodes.yaml` is **optional**, lives in the checks directory (unioned
across the path-list, a duplicate path an error), carries both fields per path
(`path: {about: …, title: …}`; a bare string is `about`), and is skipped by
`load_checks`. A
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
  check to a bounded `ThreadPoolExecutor`; each check is due at start, then every
  `frequency_seconds`. A check already running is not re-submitted.
- `_execute` runs `check.run()`, maps any exception or timeout to `ERROR`, logs the
  result at **INFO** (`check <path>: <code> (<ms>) — <reason>`), and **stores** it
  via `_store`, which **upserts** the root at `check.path` and walks any
  `children` into nodes beneath it (`<parent path>/<child name>`), each inheriting the
  check's frequency (ADR-0007). A check with recorded `secret_errors` (§4.5) is
  **pinned**: `_execute` stores that `ERROR` ("secret unresolvable: …") without
  calling `run()` — no retry until restart ([ADR-0023](adr/0023-secret-references.md)).
- `start()` / `stop()` are idempotent; threads are daemons. `run_once()` runs every
  check synchronously (for tests). `create_engine(dir)` loads checks into a new
  engine bound to `status_tree`. `info()` returns runtime state (uptime, pool size,
  check counts, per-check next-run) for the `/system` page.
- The scheduler loop is **hardened** (a transient tick error logs and continues),
  and the engine **heartbeats a top-level `little-sister` node** every tick — if the
  scheduler stalls, that node goes stale and red (ADR-0005). Whole-process death is
  left to an external supervisor (launchd / systemd / gunicorn restart).

`app.py` starts the engine once at import (post-fork worker), guarded by
`LITTLE_SISTER_ENGINE` (set `0` to disable) and tolerant of a missing checks
directory; the dev server uses `use_reloader=False` so it starts exactly once.

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

| Route | Methods | Behaviour |
|-------|---------|-----------|
| `/` | GET | Redirect to `/status`. |
| `/login`, `/logout` | GET, POST / GET | Session login (stores `username`, name, and an `admin` flag) / clears the session. |
| `/status`, `/status/<path:branch>` | GET | Renders the dashboard from a live snapshot (whole tree or a branch; the `path:` converter passes the slash-separated node path, ADR-0016). A **leaf** check renders its **detail** page. `hide_ok` / `hide_idle` filter the view; `depth` caps how deep the tree renders (clamped to `MAX_DEPTH`, remembered in a `depth` cookie); `fragment=1` returns just the grid (for the page's live polling). With `Accept: application/json` and a valid bearer token, the same routes return the subtree as JSON instead (ADR-0008). |
| `/history/<path>` | GET | A node's status history (Status / Since / Until / Reason). |
| `/maintenance` | POST | **Admin only** — set/clear a node's maintenance with a reason and optional duration (default from `config.yaml`), recording who set it; redirects to the check. |
| `/events` | GET | The transition log, newest first (When / Status / Service / Reason). |
| `/system` | GET | **Admin only** — engine uptime, pool size, check counts, per-check next-run. |
| `/text`, `/links` | GET | Auth-gated stubs (not built). |
| `/favicon.ico` | GET | Redirect to the static favicon. |

Jinja filters back the views: `status_slug` (a CSS class suffix per code),
`status_alert` (a Bootstrap alert class), `shorten`, `duration`, `localtime`
(renders a timestamp in the configured timezone, §7), `url_branch`,
`markdown` / `markdown_inline` (server-side Markdown → safe HTML, §4.7), and
`breadcrumbs` (a path → cumulative `(name, path)` crumbs for the clickable header
trail, rendered by `_breadcrumb.html`; the current node stays plain). The dashboard
filter logic is `_filter_snapshot` (drops nodes whose effective code is hidden).

### 5.2 Authentication
- Session-based; the gate is `username` in `session`, checked per route.
- Users come from `users.yaml` (a flat map of `username → {firstname, lastname,
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

---

## 6. Templates & static

Jinja2 templates under `templates/`, with `StrictUndefined` (an undefined variable
raises rather than rendering blank):

- `_header.html` — shared `<head>` tail + navbar (Status / Events / Text / Links,
  plus **System** for admins, current user, Logout).
- `_breadcrumb.html` — the clickable header path trail (`status` root + a link per
  ancestor segment, current node plain); included in the dashboard and detail headers.
- `status.html` / `_status_grid.html` — the **dashboard**: top-level systems as
  cards in a responsive grid. **Every system and subsystem is a filled rounded box
  coloured by its own rolled-up status, nested inside its parent's box** (so a
  green branch shows clearly inside a red system), each carrying its reasons; a
  translucent edge keeps same-colour boxes legible. To surface the **culprit**, a
  box is shown **vivid** only when it reports its own status; a box whose status is
  merely *derived* from a visible child — and any healthy (OK) box — is **dimmed**
  (pale fill, dark text), so the eye follows a faded trail down to the bold
  originating node. When the tree is collapsed by depth, the deepest *visible* node
  in a branch stays bold (it now carries the reason). A **depth** input in the
  filter bar sets how many levels below the viewed node render — the node itself is
  level 0, so depth 0 collapses to a single card carrying that node's rolled-up
  status (an overall traffic light), depth 1 shows its top-level systems, and so on.
  It is clamped to `MAX_DEPTH` and remembered in a `depth` cookie (resolved by
  `_resolve_depth`). Nodes drill down; hide-ok / hide-idle switches;
  **stale** nodes get a badge; a node's short `title` (ADR-0017) follows the name
  (ellipsed, `.node-title`) on a card and the breadcrumb in the page header; and a
  branch view shows the viewed node's `about` under its heading. The grid is the
  `_status_grid.html` partial; the page **polls** it (`?fragment=1`) every ~10s, swaps
  it in, and flags refresh failures (so it never silently shows old content); the
  poll stamp shows the **server-formatted** render time — the fragment's
  `X-Rendered-At` header, in `config.yaml`'s timezone and `time_format` (ADR-0006) —
  not the browser clock.
- **Inspection popover** ([ADR-0019](adr/0019-inspection-popover.md)) — a node's static
  `title` / `about` (rendered Markdown) show in a custom **hover card**, not the native
  `title=` tooltip (the leaf `description` stays on its detail page). The page preloads a path-keyed map of the rendered
  HTML (`#node-meta`, a `script[type=application/json]` built by `_node_meta_map`,
  **page-only** so the ~10s poll doesn't re-send it); `static/js/inspect.js` binds once via
  event delegation on `#status-grid` (surviving the swaps), looks each node up by
  `data-path`, and renders + positions the card with **Floating UI** (CDN). Opens on
  hover / focus, stays open when the pointer moves into it, closes on leave / blur /
  Escape; the node stays a link to its detail page; a tap opens the card on touch.
- `check.html` — a leaf check's detail page (its `title` following the breadcrumb in
  the header ([ADR-0017](adr/0017-node-title.md)); the node name + `description`; its
  `about` when present
  ([ADR-0012](adr/0012-node-metadata.md)), status + reason, time interval, heartbeat,
  a **Configuration** card of the parameters the check ran with when present
  ([ADR-0013](adr/0013-check-config-on-node.md)), History button, admin maintenance
  form).
- `history.html` / `events.html` — the status-history and event-log tables, rows
  tinted by status (`row-*` classes in `overview.css`).
- `system.html` — the admin engine status page.
- `login.html`, `text.html`, `links.html` — login, and the two stubs.
- `static/css/overview.css` — the brand accent, dashboard grid/card/panel styles,
  and table row tints; Bootstrap via CDN; favicons; `site.webmanifest`.

---

## 7. Configuration & data

- **Users** — `users.yaml` inside the package, a flat map keyed by username with
  `firstname`, `lastname`, `password` and an optional `admin: true`. Git-ignored.
- **Secrets** — a git-ignored `.env` file may supply `SECRET_KEY` (optional —
  unset means a random per-start key) and any check credentials via the
  environment ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)).
  A check's credential field is a **secret reference** — a bare env-var name (the
  default), or `scheme://address` resolved by a deployment-registered resolver,
  once at check construction (§4.5, [ADR-0023](adr/0023-secret-references.md)).
- **API tokens** — the `LITTLE_SISTER_API_TOKENS` setting holds named per-client
  bearer tokens (`name=token,name2=token2`) for the JSON backend (ADR-0008); its
  value may itself be a `scheme://` secret reference, resolved once at startup
  ([ADR-0023](adr/0023-secret-references.md) update note).
- **What to monitor** — YAML files across one or more `checks/` directories, a
  path-list union selected by `LITTLE_SISTER_CHECKS_DIR` (§4.5).
- **Node metadata** — an optional `nodes.yaml` per checks directory declares each
  node's `about` and `title` keyed by path (`path: {about: …, title: …}`); unioned
  across the path-list and seeded at startup (§4.5,
  [ADR-0012](adr/0012-node-metadata.md) / [ADR-0017](adr/0017-node-title.md)).
- **General options** — `config.yaml` (working dir; override `LITTLE_SISTER_CONFIG`)
  holds display/runtime options: `timezone` (default `Europe/Berlin`), `time_format`,
  and `maintenance_default_expiry` (default `7d`, the window applied when an admin
  gives no explicit duration — ADR-0014), loaded once into `config.py`'s `Config`
  ([ADR-0006](adr/0006-config-file-and-timezones.md)). Displayed timestamps are
  stored as server-local and converted to that timezone by the `localtime` filter
  (`zoneinfo` + `tzdata`).
- **Maintenance** — admin maintenance pins persist to `var/maintenance.json`
  (git-ignored runtime state, a fixed path), restored at startup; durable storage of
  the rest of the tree is still deferred (§8, [ADR-0014](adr/0014-maintenance-persistence.md)).

---

## 8. Not implemented yet

Current gaps.

- **Persistence** — durable storage/retention of the **tree and history** (the
  in-memory log is bounded and lost on restart); only admin **maintenance** persists
  so far, to a file (§7, [ADR-0014](adr/0014-maintenance-persistence.md)).
- **Satellite federation** and **write actions** over the JSON API
  (`project.md` §2.9).
- The `/text` and `/links` pages.
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

Test suites: `test_status.py` (the `Status` model + ADR-0004 roll-up),
`test_tree.py` (the tree, events, history, maintenance + its persistence),
`test_checks.py` (the http/file/command checks + loader), the SSH family —
`test_ssh.py` (transport, connect/command/script), `test_host_metrics.py`,
`test_qnap_metrics.py` and `test_metrics_scripts.py` (the bundled shell scripts),
`test_config.py` (general config), `test_secrets.py` (secret references: resolution,
the resolver registry, the engine's pinned-ERROR path), `test_maintenance.py` (the
maintenance side-table store), `test_nodes.py` (nodes.yaml loading, `about` precedence, the consistency
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
  in the working directory: `LITTLE_SISTER_CHECKS_DIR` (checks + `nodes.yaml`),
  `LITTLE_SISTER_USERS` (the user list, [ADR-0020](adr/0020-user-list-location.md)),
  `LITTLE_SISTER_SCRIPTS_DIR` (metrics-script overrides,
  [ADR-0021](adr/0021-script-resolution.md)), `LITTLE_SISTER_CONFIG` (`config.yaml`),
  `LITTLE_SISTER_API_TOKENS` (JSON-API bearer tokens), and `LITTLE_SISTER_ENGINE`
  (disable the engine, e.g. in tests). Defaults and formats are in §7.

A version bump is *for* changes to these; everything else — internal modules,
template markup, exact HTML — may move between releases.
