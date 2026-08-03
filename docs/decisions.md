# Little Sister — Decisions

> One self-contained digest per decision — the question it settled, the answer, and
> a link to the full Architecture Decision Record in [`adr/`](adr/) for the context,
> alternatives, and date. Reading this page is enough to know **what** we decided and
> **why**; the ADR holds the history.
>
> A decision is in force unless its heading is marked **superseded**.

---

### ADR-0001 — Process & threading model (phase 1)
**Q:** How do the checks, the shared status tree, and the web server run together
when phase 1 has no persistence?

**A:** In **one process** — `gunicorn --workers 1 --threads N` (`gthread`) — with
the engine running checks on **background threads** that share a single
**in-memory** status tree and event log. A single worker is a hard constraint;
the engine starts once, after the fork, with daemon threads and per-check
timeouts.

→ Full record: [`adr/0001-in-process-threaded-engine.md`](adr/0001-in-process-threaded-engine.md)

### ADR-0002 — Synchronizing the shared state
**Q:** How do we keep the shared tree and event log thread-safe, given the GIL
does **not** make compound operations atomic?

**A:** Guard them with a single **`threading.RLock`**. Writers (and change
detection) hold the lock; readers copy a **snapshot** under the lock and render
it **outside** the lock.

→ Full record: [`adr/0002-rlock-snapshot-synchronization.md`](adr/0002-rlock-snapshot-synchronization.md)

### ADR-0003 — Configuration & secrets via a `.env` file
**Q:** Where do the Flask secret key and check/API credentials come from in
phase 1, with no secret store?

**A:** From a single **`.env`** file (already git-ignored), read via the process
environment — no secrets in code or version control. Hashing the user passwords
is separate and still open.

→ Full record: [`adr/0003-config-and-secrets-via-env-file.md`](adr/0003-config-and-secrets-via-env-file.md)

### ADR-0004 — Status aggregation (roll-up) semantics
*Superseded 2026-08-02 by [ADR-0039](adr/0039-status-rollup-semantics.md) (roll-up),
[ADR-0040](adr/0040-what-a-failing-check-becomes.md) (a failing check) and
[ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md) (maintenance). Three
unrelated decisions had grown under one title — which is how its `MAINTENANCE` half
came to contradict its own roll-up half unnoticed. Kept for the history.*

**Q:** How does a parent's status combine its children, and how do `MAINTENANCE`
and `UNDEFINED` behave?

**A:** Worst-of `ERROR > WARN > OK`. `UNDEFINED` (leaf-only) is ignored.
`MAINTENANCE` (admin, any node) cancels its whole subtree and is ignored by its
parent. `get_status_code()` must always return a `StatusCode` and never downgrade.
A branch owner (e.g. a satellite) may stamp a node `ERROR` and drop its children,
and must clear that on recovery.

→ Full record: [`adr/0004-status-aggregation-semantics.md`](adr/0004-status-aggregation-semantics.md)

### ADR-0005 — Dashboard freshness & engine self-monitoring
**Q:** How do we avoid showing a stale state (an old page, a check that stopped, or
a dead engine)?

**A:** A node not observed within ~2× its interval is **stale** and degrades to at
least `WARN` (worse-of, computed at render time). The dashboard **polls a fragment**
every ~10s and flags refresh failures. The engine **heartbeats a `little-sister`
tile** each tick, so a stalled scheduler goes red via staleness; the loop is
hardened, and an external supervisor handles whole-process death.

→ Full record: [`adr/0005-dashboard-freshness-and-self-monitoring.md`](adr/0005-dashboard-freshness-and-self-monitoring.md)

### ADR-0006 — General config file & display timezones
**Q:** Where do general options like the display timezone live, and how are
timestamps shown in it?

**A:** In a YAML **`config.yaml`** (read once; defaults on missing keys). Options so
far: `timezone` (default `Europe/Berlin`) and `time_format`. Timestamps are stored
as server-local and **converted at display** to the configured zone via a
`localtime` Jinja filter (`zoneinfo` + `tzdata`).

→ Full record: [`adr/0006-config-file-and-timezones.md`](adr/0006-config-file-and-timezones.md)

### ADR-0007 — Checks may report a branch (recursive `CheckResult`)
**Q:** How does a check report several aspects (e.g. an `ssh` host's disk /
memory / cpu) as separate nodes, without returning the live `Status` entity?

**A:** `CheckResult` becomes a small **recursive value**: it gains `name`,
`description` and `children`. The engine walks it, upserting the root at
`check.full_path` and each child beneath it; identity, observation time,
maintenance and event-on-change stay the tree's concern. A leaf result is
unchanged, so existing checks and call sites are untouched.

→ Full record: [`adr/0007-check-result-branches.md`](adr/0007-check-result-branches.md)

### ADR-0008 — JSON output (backend mode)
**Q:** How does the web app serve the status tree as JSON for external clients and
satellite federation — endpoint, schema, and auth?

**A:** Serve JSON by **content negotiation** on the existing unversioned
`GET /status[/<node_path>]` (`Accept: application/json`) — no URL versioning (Zalando
#115). A top-level envelope (`schema_version`, `generated_at`, `status`) wraps a
recursive snapshot: `snake_case` properties, `UPPER_SNAKE` string codes, plural
`reasons`, UTC `date-time`, both `own_code` and rolled-up `code`. Errors are **Problem
JSON** (RFC 9457). Auth is a **named per-client bearer token** from `.env`. Read-only
this slice; the normative contract is `api/openapi.yaml` (OpenAPI 3.1).

→ Full record: [`adr/0008-json-output-api.md`](adr/0008-json-output-api.md)

### ADR-0009 — Per-profile remote metrics scripts
**Q:** How does the `host-metrics` check's metrics script cope with userlands as different
as macOS, mainstream Linux, CentOS 6 and busybox (a QNAP / an ASUS router) without
one script taxing every host?

**A:** Split it into **three** scripts by userland capability —
`host-metrics-{linux,macos,busybox}.sh` — chosen by a host's **`profile`**
(`linux` | `macos` | `busybox`, default `linux`), which also picks the interpreter
(`bash`, or `sh` for busybox). Each script self-guards on `uname` and emits
`profile_error=` on a mismatch (the check shows a WARN), so a mis-set profile is a
visible config error, not garbage.

→ Full record: [`adr/0009-per-profile-metrics-scripts.md`](adr/0009-per-profile-metrics-scripts.md)

### ADR-0010 — Target Python 3.14
**Q:** Keep `requires-python` at 3.14, or loosen to 3.12+?

**A:** Keep **`>=3.14`** as a deliberate single modern target. The code needs only
3.11 today, but the host is provisioned via uv (the interpreter is managed, not a
distro's), so a high floor is cheap; it simplifies the toolchain and keeps the
free-threading door open (locking is GIL-independent — ADR-0002). No external
contract depends on the runtime version.

→ Full record: [`adr/0010-python-version.md`](adr/0010-python-version.md)

### ADR-0011 — SSH check family
**Q:** How should the SSH checks be structured and named — `ssh.py` has become the
de-facto shared SSH library (qnap imports its privates) and `type: ssh` misleadingly
means "host metrics"?

**A:** One transport (`SshConnection`) plus an `ssh-` family by intent —
`ssh-connect`, `ssh-command`, `ssh-script`, `host-metrics` (today's `ssh` metrics,
renamed) and `qnap-metrics` — over a shared, pure `ssh_metrics` toolkit; the
connection surfaces a non-PQ key exchange as `WARN` on every connecting check. Clean YAML
migration, a `checks/ssh/` subpackage, full family built now.

→ Full record: [`adr/0011-ssh-check-family.md`](adr/0011-ssh-check-family.md)

### ADR-0012 — Node metadata: an `about` note, separate from check descriptions
**Q:** Where do a node's human metadata (what it *is* — location, kind, context) and
a branch check's per-leaf descriptions come from, given container/host nodes are
often owned by no single check?

**A:** Node metadata is a **property fed by several sources**: an **`about`** Markdown
note, fed in precedence order by a **`nodes.yaml`** declaration (keyed by path, so it
reaches container nodes and satellite graft-points) **>** inline on the owning check
**>** empty — kept **separate** from `description` (what the check does). Branch checks
give each leaf its own `description` via a `descriptions:` map, leaving the shared
host node's empty. A **startup consistency pass** warns about an `about` path no check
covers. Links stay deferred.

→ Full record: [`adr/0012-node-metadata.md`](adr/0012-node-metadata.md)

### ADR-0013 — Surface check config as node display metadata
**Q:** How does the check detail page show the parameters a check ran with —
including for branch checks, whose leaves have no `Check` object?

**A:** The check **pushes** a curated allow-list of its config onto the
`CheckResult`, which the engine stores on the node like `description` — so a branch
check tags each leaf with the slice that produced it, and the web layer just reads the
snapshot. It's **static display metadata**: no event, out of aggregation, shown on
leaf detail pages to all viewers, and **not** added to the JSON envelope here. Refines
[ADR-0007](adr/0007-check-result-branches.md).

→ Full record: [`adr/0013-check-config-on-node.md`](adr/0013-check-config-on-node.md)

### ADR-0014 — Persist maintenance to a file, with auto-expiry
**Q:** How does admin maintenance survive a restart, and how do we stop a pin
lingering forever — without pulling the general store question forward?

**A:** A maintenance **side-table** in the tree, written through to a small
**`var/maintenance.json`** (atomic, fixed path) and **restored on startup** before the
engine runs. Every entry has an **auto-expiry** — default **one week** (`config.yaml`),
overridable, no indefinite — swept by the scheduler; and a **startup reap** drops
entries no configured check **covers** (segment-wise on the same root-to-leaf line, so
subsystem and unreachable-branch-leaf pins survive). A deliberate stopgap in a later
Phase subsumes.

*Amended 2026-08-02 — editing a pin, and two admins writing it.* A pinned node offered
only *Clear*, so extending a window meant clearing and re-setting: the node alarmed in
the gap, and a blank reason falling back to the literal `maintenance` usually threw the
explanation away. And the write had no precondition, so two admins a minute apart
silently lost the first one's words. Now: the set form is **reachable while pinned and
prefilled** with the stored reason, beside *Clear* — duration deliberately **not**
prefilled, so blank means the configured default here exactly as it does on an unpinned
node. The entry carries **both dates** — `created_at` / `created_by` beside `set_at` /
`set_by`, which keep meaning *the last write*; absent from an older file they default to
the set values, so it loads unchanged. The write becomes a **compare-and-set** on
`set_at`, carried as a hidden token (empty = *"nothing is pinned"*) and **exact**, since
one process holds one lock ([ADR-0001](adr/0001-in-process-threaded-engine.md),
[ADR-0002](adr/0002-rlock-snapshot-synchronization.md)); on a mismatch nothing is
written and both texts come back, the admin's own preserved, with one click to take the
stored ones instead. `action=clear` carries the same token. An **edit emits an event** —
`MAINTENANCE -> MAINTENANCE` is invisible to the code test — but a no-op re-submit does
not. Lands **before** per-entry pins ([ADR-0036](adr/0036-addressable-reasons.md)),
because the same guard has to cover `(path, slug)` and a token designed once is a token
not built twice.

*Amended again the same day — the key widens.* A pin may name **one reason** of a node
([ADR-0036](adr/0036-addressable-reasons.md)), so the side-table is keyed `(path, slug)`
as well as `path` and the file holds two tables, `{"nodes": …, "entries": …}`. One
mechanism at two depths: same entry shape, same token, same replay, reap and sweep —
only the effect differs, since an entry pin writes nothing into the tree and is joined
at snapshot time, which is what [ADR-0032](adr/0032-status-contribution-boundary.md)
rule 3 asks for. The file's new shape is a **clean break** with the bare node table:
no reader for the old one, no migration, an ignored file warned about and rewritten on
the next save — runtime state the program owns and bounds with a finite expiry, so a
compatibility branch in the read path forever is the worse trade. An entry pin emits
**no event**, because it changes no stored code.

*Amended again 2026-08-02 (after review) — a positive, bounded window, and a blank
field that changes nothing.* §4 promised a **finite** expiry; finite was not enough.
A zero or negative duration parsed cleanly, landed `expires_at` in the past, and the
next sweep dropped the entry — reason and both authorships gone within a tick, behind
a redirect that looked like success, which is the lost-explanation failure the
compare-and-set guard exists to prevent arriving through the other door. At the far
end, an enormous duration overflowed the date arithmetic and `inf` overflowed the
parser, neither of them a `CheckError`, so a typo became a 500. A window is now **at
least one second and at most a year**, and out of range is **refused, not clamped** —
the form returns with the admin's words and a sentence saying what was wrong, the same
page a refused compare-and-set uses, because the situation is the same. Only the
deployment's configured default still falls back. And a **blank reason on an edit keeps
the stored text**: blank means *"I did not touch this field"*, so an edit that only
moves the window keeps the explanation; on a new pin the literal `maintenance` stays
the placeholder.

→ Full record: [`adr/0014-maintenance-persistence.md`](adr/0014-maintenance-persistence.md)

### ADR-0015 — Check discovery: a union of config directories
**Q:** Confirm the check-config layout: one directory per
deployment, or shared / layered profiles — and do configs reload without a restart?

**A:** Keep **explicit per-deployment selection** but let `LITTLE_SISTER_CHECKS_DIR`
be a **list of directories loaded as a union** (shared base + host-specific adds;
checks are **asked which nodes they own** (`owned_nodes()`) and **overlapping
ownership is a hard error** — branch checks like `host-metrics` + `qnap-metrics` own
disjoint child subtrees, so they still share a host node; no override / merge). Config
applies at
**startup**; a restart re-reads it — **no live reload**. Override-layering and reload
are deferred; satellites (later Phase) are the real multi-site mechanism.

→ Full record: [`adr/0015-check-discovery-union.md`](adr/0015-check-discovery-union.md)

### ADR-0016 — Node addressing: a single absolute slash path
**Q:** How is a node addressed — can a node name be an FQDN (with dots), and why
carry both a parent `path` and a `name`?

**A:** Address a node by **one absolute, slash-separated path** (`/system/alpha/disk`).
The separator is **`/`** (not `.`), so a segment may contain dots — a node can be named
for its FQDN (`/hosts/example.org`), retiring the `example_org` underscore workaround.
Paths are **absolute** (leading `/`, root `/`). The old parent `path` + `name` merge
into **one `path`**; `name` is the **derived** last segment, no longer authored. The
separator lives in `status.py` helpers (`join_path` / `split_path`); URLs use Flask's
`<path:…>` converter. The JSON `path` field changes shape — a free change while no
client/satellite consumes it yet.

→ Full record: [`adr/0016-node-addressing.md`](adr/0016-node-addressing.md)

### ADR-0017 — Node title: a short display label
**Q:** How does a node get a short, friendly label distinct from its terse `name`
(the path segment), its check `description`, and its richer `about`?

**A:** Add an optional **`title`** — a short, one-line Markdown label. It rides the
same machinery as `about` (ADR-0012): fed by precedence **`nodes.yaml` > inline on
the owning check > empty**, carried in `nodes.yaml`'s per-path mapping beside `about`
(`path: {about: …, title: …}`), seeded at startup, and covered by the consistency
pass. Display: the title **follows** the node name (or breadcrumb), ellipsed, never
replacing it — after the node name on a dashboard card, and beside the `status / …`
breadcrumb in the **page header** of both a branch view and a leaf's detail page (whose
body still shows the name + description). Markdown (rendered later); not in the JSON envelope
yet. The path/name identity (ADR-0016) is untouched.

→ Full record: [`adr/0017-node-title.md`](adr/0017-node-title.md)

### ADR-0018 — Markdown rendering for node text
**Q:** How do we render the Markdown fields (`title`, `about`, leaf `description`,
`reasons`) shown as plain text today — which library, and how do we stay safe given
`reasons` can carry captured (externally-influenced) output?

**A:** Render **server-side** via Jinja `markdown` (block) / `markdown_inline` filters,
using **markdown-it-py** with safe defaults — raw HTML escaped, link schemes validated —
plus `rel="noopener noreferrer"` on links (images were disabled, since **enabled** — see
the ADR Update note). One runtime dep
(+ tiny `mdurl`); no CSP or extra sanitizer this slice. `reasons` are the check author's
responsibility (operator-controlled, ADR-0007); the check base provides **`plain()`**
(escape Markdown) and **`code()`** (fence log output) so a check folds external bytes in
safely, and the built-in capturing checks use them. `title`/`description` render inline;
`about`/`reasons` as a block. The JSON envelope is unchanged (raw Markdown).

→ Full record: [`adr/0018-markdown-rendering.md`](adr/0018-markdown-rendering.md)

### ADR-0019 — Inspection popover (hover card)
**Q:** The dashboard shows a node's `description` + `about` only through the native
`title=` tooltip — raw, non-interactive, one line. With node text now Markdown, how do
we show a richer hover card, and where does its data come from?

**A:** A **custom client-side hover card**. It shows the **static** metadata only —
`title` / `about`, as server-rendered Markdown (the leaf `description` stays on the
detail page) — so it needs no live data. The dashboard **preloads** a path-keyed map of
the already-rendered HTML (a
`script[type=application/json]`, page-only, not the polled fragment), and a small script
renders the card from it by `data-path`, surviving the ~10s grid swaps via event
delegation. **Floating UI** positions it (flip/shift at edges); opens on hover/focus with
a delay, stays open into the card, closes on Escape/blur; the node stays clickable; mobile
taps open it. No new route or API change. Replaces the `title=` tooltips. A node with no
metadata gets no card.

→ Full record: [`adr/0019-inspection-popover.md`](adr/0019-inspection-popover.md)

### ADR-0020 — Deployment-supplied user list
**Q:** For the repo split, how does a deployment supply its own users
when `users.yaml` is read from inside the package today?

**A:** Read the user list from a **deployment-controlled** path — `LITTLE_SISTER_USERS` if
set, else `users.yaml` in the **cwd** — mirroring how `.env` / `config.yaml` are already
found ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). The package ships
**`users.example.yaml`** only and no longer bundles a real `users.yaml`. Format
and fail-fast-on-missing are unchanged; this is a **location** change, not an auth-mechanism
one (password hashing and a pluggable auth provider are in later Phases).

→ Full record: [`adr/0020-user-list-location.md`](adr/0020-user-list-location.md)

### ADR-0021 — Script resolution: packaged defaults with an override
**Q:** After the split moves the private configs to their own repo, how do checks find the
generic (safety-sensitive) measurement scripts they call, without vendoring divergent copies?

**A:** **Single-source** the generic scripts as **package data** in `little_sister`. An
explicit `script:` is unchanged (relative → the config's own dir); a built-in check's
**default** script resolves against a search path, first match wins:
**`LITTLE_SISTER_SCRIPTS_DIR`** → the **config's own dir** (shadowing) → the **packaged**
scripts. The `command` check is unaffected. Deployments get built-in scripts for free and
the sensitive scripts never drift.

→ Full record: [`adr/0021-script-resolution.md`](adr/0021-script-resolution.md)

### Node sibling ordering — natural, case-insensitive (no ADR)
**Q:** Sibling nodes render in **insertion order** (check / discovery order), which is
undetermined and not a useful order. How should they be ordered?

**A:** Sort siblings by **name**, **case-insensitive** and **natural** (digit runs
compared numerically, so `node2` precedes `node10`), at **every level**. The sort happens
once in the **snapshot** (`tree._snapshot`, key `_sort_key`) — the single point both the
dashboard and the JSON envelope read — so order is consistent everywhere and computed
once; the live tree keeps insertion order untouched. Pure name order (no severity-first,
which would jump on each poll); a branch check's curated leaf order (e.g. host-metrics'
disk/memory/cpu/load) is **not** preserved — uniform alphabetical wins on predictability.
Small, low-risk display change — recorded here, no ADR.

### ADR-0024 — Dashboard layout: bounded heights, positional stability
**Q:** Top-level cards differ wildly in height (a fifteen-disk host beside the
one-line `little-sister` heartbeat), so the grid looks ragged and an erupting node
reflows its neighbors. But whoever knows the wall relies on **where** a card is, so
a packing layout that moves cards on any size change is out. How is the overview
balanced without moving anything?

**A:** Keep a card's **position a function of the node set alone** (alphabetical at
every level, per *Node sibling ordering* above) and **bound the size variance**
instead: the reason caps and a `min-height` hold height in a fixed band; a card's
**quiet leaves** collapse to compact name+color **chips** while a warn/error leaf
keeps its full box and reason; and the always-tiny `little-sister` heartbeat
(ADR-0005) lifts out of the grid into a slim **status strip** under the "updated …"
line. Its `/little-sister` path is **reserved** at load so nothing user-configured
can hide behind the one-line bar. Packing layouts and `nodes.yaml` size hints are
rejected — both move cards on a state change, against the position rule.

→ Full record: [`adr/0024-dashboard-layout.md`](adr/0024-dashboard-layout.md)

### ADR-0025 — Check-provided subnode metadata (`about` / `title` on `CheckResult`)
**Q:** A branch check knows what its subnodes *are* (a metrics check's `disk` /
`memory`), yet the subject label `about` and short `title` reach a child node only
through a per-path `nodes.yaml` entry — so a **type-inherent** subnode identity has to
be copy-pasted into every deployment and host. Where should those labels come from?

**A:** From the **result value**: `CheckResult` gains `about` / `title`, read only on a
**child** (ignored on the root, like `name`, which keeps its `nodes.yaml` / inline-check
sources). Precedence per field is **`nodes.yaml` > check-provided > empty**, kept by
**seed-once** semantics — startup seeding (`set_about` / `set_title`) overwrites, the
engine's runtime write **fills an empty field only**; since `nodes.yaml` is seeded before
the first tick it always wins, so neither tree nor engine needs provenance state. Labels
**freeze at first fill** (stable identity, not live status — changing text is `reason`).
`description` / `config` stay write-through; the JSON contract and web surface are
unchanged. A **yaml-aware engine** and **per-field provenance on `Status`** were rejected
as buying live label updates nothing needs.

→ Full record: [`adr/0025-check-provided-subnode-metadata.md`](adr/0025-check-provided-subnode-metadata.md)

### Clickable breadcrumbs (no ADR)
**Q:** The header path trail (`status / system/alpha/disk`) was a single non-clickable
span — only `status` linked home. How do we let it navigate up the tree?

**A:** Each **ancestor** segment links to its level (its cumulative path), built by a
`breadcrumbs` Jinja filter and rendered by a shared `_breadcrumb.html` partial used in
both the dashboard and detail-page headers; the **current** node (last crumb) is plain
text. Small UI navigation change — recorded here, no ADR.

### Envelope fields — node metadata + maintenance details (additive to ADR-0008)
**Q:** Which Phase-2 node fields (check `config`, `about`, `title`, maintenance expiry)
should join the read-only JSON envelope ([ADR-0008](adr/0008-json-output-api.md))?

**A:** **All four**, as an **additive** change (`schema_version` stays **1**). The envelope
serves both a display client and a federating satellite, so it now carries the same
metadata the origin renders: **`about`**, **`title`**, **`config`** as **raw Markdown**
(the client renders, ADR-0018), and a new **`maintenance_details`** object
`{reason, set_by, set_at, expires_at}` (timestamps RFC 3339 UTC, **null** when not under
maintenance) beside the existing **`maintenance`** bool — the bool is left **unchanged**
(repurposing it to an object would be breaking). Contract:
[`api/openapi.yaml`](api/openapi.yaml). Recorded here, no ADR.

### ADR-0004 (2026-07-29 update) — A failing check shows its stack trace
**Q:** When a check raises, the node shows only `check error: <message>` while the
trace goes to the log. On a deployment whose log is awkward to reach — a container,
someone else's cloud — that is the one piece of information the operator needs and
cannot get from the dashboard. Should the trace go on the node?

**A:** **Yes, by default.** A second reason carries the innermost 5 frames as a
`code()` block (verbatim and inert, ADR-0018), chained causes included; `config.yaml`'s
**`stacktrace: false`** turns it off where the dashboard has a wider audience than its
logs. Global rather than per-check: a check that raises unexpectedly is exactly the one
nobody thought to flag in advance, so an opt-in switch would be off when it mattered.
Folded into `reason` rather than given its own `Status` field — `reason_cap` then clamps
it on the dashboard, the detail page shows it in full, and the JSON envelope carries it
with no schema change. The exception **message** is now escaped with `plain()` in the
same pass, which it never was.

Recorded as an update to [ADR-0004](adr/0004-status-aggregation-semantics.md), which
gains *A check that fails* — stating that any exception, timeout or non-`CheckResult`
return becomes `ERROR` (never a skipped update, never a stale OK), and why that is
`ERROR` rather than `UNDEFINED`. `engine.py` had cited ADR-0004 for exactly this since
it was written, with nothing in the ADR to point at.

→ Full record: [`adr/0004-status-aggregation-semantics.md`](adr/0004-status-aggregation-semantics.md)

### ADR-0026 — Reading values from decoded bags (`values.py`)
**Q:** Config blocks and API payloads decode to bags of `Any`, and `Any` is assignable
to anything — so `mypy --strict` cannot flag `plain(payload["number"])` and the wrong
type only shows up at runtime. The standing answer was a `str(...)`-at-every-read
convention held at ~50 sites, which failed exactly where it was forgotten. Where should
the narrowing actually live?

**A:** At the seam where `Any` enters, in a top-level **`little_sister.values`**:
`text` / `number` / `real` / `flag` / `rows` take the bag plus a `*path` of keys
(collapsing the `(x or {}).get(y)` idiom) and **always return the declared type**;
parameters are `object`, not `Any`, so `--strict` still checks the body. Policy:
**absent → default**, **`required=True` → `CheckError`** for structural fields, and
**present-but-uncoercible always raises** — a silently wrong *green* is the worst
outcome for a monitor. Escaping stays at the render (`plain`, ADR-0018): a stored
escaped value can no longer go in a URL. `CheckError` moves to a new `errors.py` so
`values` is raisable from `config.py` / `maintenance.py` without importing the check
registry. Per-payload dataclasses were rejected as the general answer (their value
scales with the number of consumers); deployment repos still model what recurs.

→ Full record: [`adr/0026-reading-values-from-decoded-bags.md`](adr/0026-reading-values-from-decoded-bags.md)

### ADR-0022 — Public releases from a generated, condensed `main`
**Q:** How does a private working branch publish to a public `main` without
leaking working notes, private strings, or development history?

**A:** `main` is **generated** per release: the working branch's committed tree is
snapshotted onto a dedicated worktree, condensed, human-reviewed, and landed as
**one squash commit** with an annotated `v<x.y.z>` tag carrying the CHANGELOG
notes. The condense enforces a three-way doc classification (keep / drop /
error), strips the release markup (`Rationale:`/`Dev:` trailers, dev-only
blocks), validates links and names, and scans the whole surviving tree against
a private-strings denylist. Version + CHANGELOG roll on the working branch;
`main` only gates and tags; humans review and push. Repos version
independently; contact runs through GitHub issues, no personal email in
metadata.

→ Full record: [`adr/0022-generated-release-branch.md`](adr/0022-generated-release-branch.md)

### ADR-0023 — Secret references with deployment-registered resolvers
**Q:** How does a check get a credential from somewhere other than `.env` — AWS Secrets
Manager, Parameter Store, possibly both in one deployment — without the core growing
cloud dependencies or a global "secret provider" switch?

**A:** The **reference names its source**. Every reference is `scheme://address`:
`env://NAME` is the env-var lookup ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md))
and any other scheme selects a **resolver the application registered in code**
(`little_sister.secrets`, the same import-before-app slot as check types). Only
addresses appear in config — never values. Secrets resolve **once, at check
instantiation**, never during runs (cloud reads cost money); rotation = restart. A
malformed reference — no scheme (a pasted secret, typically) or an unknown one —
fails loudly at load like any config error, without quoting what it rejected; a
failed **resolution** pins the check to a visible ERROR instead of aborting the
engine. `SECRET_KEY` and the API-token setting may themselves be references
(`resolve_setting` — see the ADR's update note), and `SECRET_KEY` unset now means
a **random per-start key**.

→ Full record: [`adr/0023-secret-references.md`](adr/0023-secret-references.md)

### The core stays service-free; deployments extend through the seams (no ADR)
**Q:** Must little-sister stay pure-Python/Flask, add no extra services, and remain
deployable as one `gunicorn` command — with Keycloak and cloud secret stores on the
horizon?

**A:** **Confirmed for the core.** External services — an IdP, a secret store, cloud
storage — enter only **deployment-side**, wired by the application through the
provider seams ([ADR-0023](adr/0023-secret-references.md); the auth seam follows the
same philosophy): the core gains no SDK, no service, no extra deploy step, and a plain
local install keeps working with none of it. Deliberately still open is whether the
later Phase durable store can hold this same line — that belongs to the store choice
itself.

### ADR-0027 — Observation timestamps: only where a check has written
**Q:** `Status.__init__` stamped every node at construction, so a node no check ever
writes — a container above the check mounts, the root above all — served the process
start time as its "observation" time, and a client polling the root read boot time as
data age. What should `timestamp` mean, and what do aggregate nodes report?

**A:** A timestamp appears only where **"when did the check behind this node run?"**
has exactly one answer. No stamp at construction (`None` until the first
`update()`/`touch()`); a written node carries its own last write; an unwritten ancestor
with exactly **one** check mount in its subtree inherits that mount's stamp (derived at
snapshot time; the engine heartbeat never counts); with two or more mounts below, a
node has **no** timestamp. **No aggregation statistics:** min/max of raw ages across
heterogeneous check frequencies carries no signal (a healthy 90-day check would make a
min-rolled root look ancient) — the frequency-normalized freshness signal remains
`stale` (ADR-0005). A deliberate asymmetry with ADR-0004: codes roll up worst-of;
observation times do not aggregate. Cards show the time when present; the JSON
`timestamp` becomes nullable with the same semantics.

→ Full record: [`adr/0027-observation-timestamp-semantics.md`](adr/0027-observation-timestamp-semantics.md)

### ADR-0028 — Design tokens: one named palette, and a theme is an override of it
**Q:** Every color the web surface painted was a literal in `overview.css`, so a second
scheme — a dark mode, a theme roster, a deployment's own branding — meant copying rules
and editing the copies, which drift apart one fix at a time. What is a theme, and what
stops a scheme from quietly making a status unreadable?

**A:** The stylesheet names its palette **once**, on `:root`, and paints only from it;
no rule below that block carries a literal color. The vocabulary mirrors the shipped
dim/vivid model (ADR-0024) rather than the design sheets' sketch of it: per status a
**vivid** fill with its ink and a **pale tint** with its ink, `ok` pale at every depth,
and status **borders mixed from the matching ink** so a scheme that moves an ink moves
its edges too. A **theme is an override block** keyed on `body[data-ls-theme]`, never a
fork; dark-canvas themes also set Bootstrap's `data-bs-theme`, and a deployment theme
(the web-customization phase) uses the same seam. **The accessibility bar outranks any
picked swatch:** status text holds AA in default/vivid/pastel/dark — light themes render
status words in their dark state inks, yellow lives on surfaces and never as words
there, dark themes may use bright words; cyberpunk is a declared fun theme, measured but
not gated. When a pick and the bar collide the bar wins and **the pick finds a different
vehicle**, flagged, never silently both. Two deliberate exceptions are recorded: the
**quiet OK** (a healthy word recedes at 0.8 opacity; the shape cue is its non-color
channel) and the **wordmark** (brand, not status, and large text). Verified by computed
style and rendered pixels per theme, never by class presence.

→ Full record: [`adr/0028-design-tokens-and-themes.md`](adr/0028-design-tokens-and-themes.md)

### ADR-0029 — Presentation preferences live in a cookie, not in the server
**Q:** Theme and layout became the viewer's choice, but little-sister keeps no durable
store on purpose (ADR-0001/0002) and a preference resolved after load would flash the
wrong scheme on every navigation. Where does the choice live, and what applies it?

**A:** **One long-lived cookie per browser** (`ls_prefs`, urlencoded, a year,
`SameSite=Lax`, beside the view cookies it resembles), read **server-side** into
`body[data-ls-theme][data-ls-layout]` so the page renders in the chosen scheme rather
than switching into it. Presentation only — nothing in it changes what the surface
*says*. **Every failure mode lands on the defaults, independently per key** (absent,
unparsable, retired value, hand-typed), because a look must never be able to break a
page. The settings menu **posts** to `/preferences`, so validation lives in one place
and the return path is accepted only as a same-site path (no open redirect). `auto` is
the one exception to server-rendering — three inline lines set Bootstrap's theme from
`prefers-color-scheme` before first paint, since only the browser knows. The look
belongs to the **browser, not the session**: it survives logout, the login page wears
it, a kiosk browser keeps its own, and a value the menu no longer offers is still
honored. **Logout moves into the menu.** Per-user *functional* settings (overrides of
`config.yaml`) are explicitly **not** covered — they need a real store and wait for the
persistence phase; the menu reserves a grayed entry for them.

→ Full record: [`adr/0029-per-user-presentation-preferences.md`](adr/0029-per-user-presentation-preferences.md)

### ADR-0030 — Curated links come from a deployment-supplied file
**Q:** `/links` has been a placeholder since the route existed, and the content belongs
to the deployment, not the library. What fills it, in what form, and how does a curated
list avoid rotting into dead weight?

**A:** A structured **`links.yaml`**, an **aspect of the `config/` directory**
([ADR-0031](adr/0031-deployment-config-directory.md)), so it layers base-plus-site like
everything else. **One flat level of groups**, merged by title across roots, with **file
order preserved and never sorted** — an operator who puts *EMERGENCY STOP* first means
it. Deliberately not a Markdown page: the library keeps ownership of the presentation
(themes, rail, band, kiosk), and records can be filtered where prose cannot. **Runbooks
are not here** — a subject's runbook lives on the check that watches it
([ADR-0012](adr/0012-node-metadata.md), [ADR-0013](adr/0013-check-config-on-node.md),
[ADR-0025](adr/0025-check-provided-subnode-metadata.md)); this page is general helpers.
**Icons are referenced by name and the names aggregate** — the deployment's map, then
packs registered by dependent packages, then little-sister's **built-in DevOps pack**,
then the link origin's favicon, then a neutral SVG — so a dozen Grafana links cost one
icon, and a page built from built-in and local marks makes **no outbound request**. The
pack carries **only marks we may redistribute** — a name whose file we may not ship still
exists and falls through. Filling it, in preference order: **draw our own generic glyph**,
then **the deployment's own local file**, then **an external URL** — hotlinking settles
redistribution but leaves trademark untouched, adds a terms-of-service question, and is the
least reliable of the three. Overrides resolve **per name, not per pack**, an entry
**replaces whole** (no merging of `on_light` / `on_dark` across layers), `none` is a legal
value meaning *do not display this mark*, and a shadowed name is **logged**. A
brand mark does not theme, so an icon may declare an `on_light` / `on_dark` pair chosen
**in CSS**, since the server cannot know what `auto` resolves to; a single-file icon
renders on a theme-invariant chip, a paired one bare. The file is **re-read on mtime
change**, never load-once, because a restart still costs the in-memory event log.
**Structural validation runs at load and never touches the network** — this application
must come up while the network is broken — while **reachability is probed on a slow
schedule and reported on the page, not on the status tree**: the audience is whoever
maintains the file, and the first engine-owned child under `/little-sister` would cost
the status strip a redesign ([ADR-0024](adr/0024-dashboard-layout.md)). Icons are probed
by default, links **opt in per entry**, and `401` / `403` count as alive. No JSON API
surface, and no caching of remote icons. **Node metadata does not move**: a node's `about`
and `description` are already Markdown and carry their own links, and a check ships its
runbook through its own config ([ADR-0025](adr/0025-check-provided-subnode-metadata.md)),
so no structured per-node `links:` field is added — the page is general helpers, the node
knows its own subject.

**Update (2026-07-31):** the client-side filter matches **the entry's title and its
group's** — still titles, never prose. Measured on the first real page rather than
reasoned about: with entry titles alone, typing a category name matched nothing at all,
which reads as a broken page rather than as a narrow rule.

**Update (2026-08-01):** the search path gains a rung — **`config/links/icons/` is the
deployment's own pack, discovered by file name**, so a file dropped there needs no
`icons:` entry. Above the packs a dependent package registers, below the map (which
stays the way to name a URL or say `none`); pairs follow the built-in pack's
`<name>-on-light.*` naming.

**Update (2026-08-02):** reachability is probed **when somebody opens the page**, not on
a timer, and only when the newest answer is older than `interval:` — which keeps its name
and its `6h` default while changing meaning from *how often a timer fires* to *how stale
an answer may be*. The pass never blocks the render: the page shows what is in memory
with each verdict's age, and one open's pass lands on the next. The audience was always
the reader of this page; structural validation already covers every icon that is not
remote, so a timer would mostly probe an empty set; and the engine's tick would have
bought a scheduler seam that is skipped exactly where the page still works. *Every n-th
open* was rejected against it — a count refreshes five times under a reloading reader and
never under a twice-a-day one. *Never blocks* governs the **open**, not the reader: a
deliberate **check now** control re-probes on demand and does wait, under a deadline,
sharing the one pass.

*Amended again 2026-08-02 (after review).* An `interval:` the parser cannot read, or a
non-positive one, **falls back to the default** rather than raising — the loader keeps
the key as raw text and validates nothing, so `6 hours` took `GET /links` to a 500. And
a target whose server answers garbage costs its own verdict, not the pass:
`http.client.HTTPException` is neither an `OSError` nor a `ValueError` and escaped the
probe unwrapped, leaving every remaining target unanswered — which the trigger read as
"never asked" and retried on every subsequent open.

*Amended once more 2026-08-02.* **A pass carries its own deadline and abandons what has
not answered.** `REQUEST_TIMEOUT` bounds a socket *operation*, not a request, so a server
that dribbles a byte every four seconds never times out — and since the executor was
entered as a context manager and the single pass slot released only on the way out, that
one host froze reachability for the life of the process. It cannot be cancellation: a
request already on the wire cannot be recalled. So the pass keeps what came back, marks
what started and did not finish as *no answer*, leaves a target it never reached with the
verdict and age it already had, and gets out of the way. The deadline is derived from the
target count in rounds of `CONCURRENCY`, with a floor above the *check now* deadline. Two
passes may now be alive at once, so each carries a **generation**: a superseded one stops
writing, stops pruning, and does not free its successor's slot. Abandonment leaks threads
a host will not release, so past three outstanding no new pass starts — and the page says
so, because that is the one condition under which the ages stop meaning what they say.
Underneath all of it, verdicts were said to be stored *as they arrive* and were collected
with `Executor.map`, which yields in **submission** order: harmless while a pass always
completes, load-bearing the moment one may not.

→ Full record: [`adr/0030-curated-links.md`](adr/0030-curated-links.md)

### ADR-0031 — One deployment config directory, split by aspect
**Q:** `checks/` had grown three unrelated tenants — check configs, `nodes.yaml`, and now
`links.yaml` — while **only checks were layerable**, so every new aspect either squats in
a directory named for something else or grows its own environment variable. Where does a
deployment's configuration live?

**A:** **One layered configuration directory, `config/`, whose entries are aspects.**
`LITTLE_SISTER_CONFIG_DIR` is a path-list replacing `LITTLE_SISTER_CHECKS_DIR`, and **the
list says where to look while each aspect says how its layers combine**: checks union with
a hard error on overlapping ownership (unchanged,
[ADR-0015](adr/0015-check-discovery-union.md)), `nodes.yaml` later-root-wins **per field** (the grain ADR-0012 already uses, and an override is logged),
links merge by title, `settings.yaml` shallow-merges per key, and `users.yaml` is taken
**whole from the first root that declares it** — merging identities across layers is a
security question wearing a convenience costume. An aspect is `config/<aspect>.yaml` when
it is only data and `config/<aspect>/` when it also carries files beside it (checks and
their scripts, links and their icons, a brand and its assets); **both forms present is an
error**, and an unrecognized entry **warns and is ignored**, so an operator's stray file
can never stop the monitor. `config.yaml` becomes **`config/settings.yaml`** and
`users.yaml` becomes **`config/users.yaml`** in the same move — a deployment reorganizes
**once**, not once per aspect — while `LITTLE_SISTER_CONFIG` and `LITTLE_SISTER_USERS`
remain explicit single-file overrides that **bypass layering entirely**. **`.env` and
`var/` stay out**: `config/` is read-only input the operator authors,
`var/` is state the program owns ([ADR-0014](adr/0014-maintenance-persistence.md)). One
**clean break** — `LITTLE_SISTER_CHECKS_DIR` is gone and `checks/` is never consulted,
since every consumer pins a tag and a shim would be dead code the day it shipped. Startup is
**strict about the tree, tolerant about its contents**: it **refuses to start** — naming the
resolved path — when there is no config directory, when a named root does not exist, when no
root provides the `checks` aspect, or when the tree is absent while a legacy marker is still
present (the old layout is detected *only in order to refuse*, naming the moves). A checks
aspect holding **no checks** is allowed but loud: the engine runs, a warning names the
reason, and the heartbeat node goes **WARN** ([ADR-0005](adr/0005-dashboard-freshness-and-self-monitoring.md)) —
with zero checks the tree is only the heartbeat, so an OK heartbeat would show an all-green
root while nothing is watched. A **candidate aspect** is a
`*.yaml` file or a directory, so a `README.md` or a dotfile in `config/` passes in silence.
[ADR-0020](adr/0020-user-list-location.md)'s decision — deployment-controlled, never
packaged — stands; only its default path moves. The ADR also names the **override ladder**
as the house pattern for anything the library ships a default of — **packaged default →
package-registered override → deployment file**, winning **per named item, never
wholesale** — so scripts ([ADR-0021](adr/0021-script-resolution.md)), icons
([ADR-0030](adr/0030-curated-links.md)) and a later brand share one arrangement instead of
three; whatever resolves by import order logs when order decided the winner.

→ Full record: [`adr/0031-deployment-config-directory.md`](adr/0031-deployment-config-directory.md)

### ADR-0032 — The contribution boundary: what a node shows and what it publishes
**Q:** Several planned rules — an admin override that silences warnings but not
errors, a configured cap so a lab machine cannot redden the root, a dependency that
shields the checks behind it, a counter that holds a failure back until it repeats —
all need to change what a node reports **upward** without changing what it *is*.
Where does that happen, and does each one need a new status code?

**A:** At **one boundary, in the snapshot**, which already does exactly this for
staleness. A node has three statuses: its **own** (what it reported, `own_code`), its
**effective** status (what it is, given its subtree, `code`), and its **contribution**
(what its parent accumulates) — the third promoted from the implicit parent-side skip
rules in [ADR-0004](adr/0004-status-aggregation-semantics.md) §2/§3 to the value a
policy acts on. The tree's stored code stays the raw report and `get_status_code()`
stays the pure derivation: **a policy is never implemented by writing a different
value into the tree.** The status vocabulary is **closed** — a new reason not to count
is a contribution rule plus a marker, never a sixth code, since every consumer
switches on the code. Three rules bind any such policy: a transformed contribution is
**visible and attributable**; every suppression keeps a **liveness backstop**
([ADR-0005](adr/0005-dashboard-freshness-and-self-monitoring.md) §1) so a check that
stops running still escalates; and an **unusable rule does not apply**, because
silence is the failure direction that hides outages. Nothing changes in behavior
today — both fields already exist and staleness is the one transform; maintenance
([ADR-0014](adr/0014-maintenance-persistence.md)) is the single implementation that
breaks the rule and is what a policy decision would correct.

**Update (2026-08-01):** the boundary reaches **one level below a node**. A node's
reasons are addressable keyed entries ([ADR-0036](adr/0036-addressable-reasons.md))
and an entry may carry its own suppression; the entries are then **virtual children**
— each unsuppressed one contributes the node's reported status, a suppressed one
contributes nothing, and the node's **own** status is the worst of what is left,
`MAINTENANCE` when a node that reported entries has none unsuppressed remaining (a
node that reported no entries is outside the rule). So *own* is no longer simply
*what the node reported*: the stored value is the **reported** status and `own` is the
first derived one — the same move the maintenance keystone makes for node pins.
Decisions 2–7 hold at that level unchanged. The ADR-0004 split now owes the same
answer to its open all-children-ignored edge case (`MAINTENANCE`, not `UNDEFINED`).

→ Full record: [`adr/0032-status-contribution-boundary.md`](adr/0032-status-contribution-boundary.md)

### ADR-0033 — A faster second look: the budgeted failure retry
**Q:** A failed check is only confirmed a full frequency interval later —
fifteen minutes at a five-minute check before three reds exist. Recheck faster
after a failure without creating a retry herd, without touching freshness, and
without a second time vocabulary?

**A:** At **completion** (the result does not exist at submit time), a non-OK
run pulls the armed next slot to `min(armed, now + retry_interval)` — earlier,
never later — at most **`retry_attempts` times per failure episode**; an OK
ends the episode and re-arms the budget. Any non-OK triggers (`WARN` included:
the same set a later escalation counter will count); a secret-pinned check
never retries. Staleness keeps judging by the **nominal** frequency (the
upsert is unchanged), and `/system` marks a retry slot (`· retry 1/2`) so the
schedule stays explicable. Config: `settings.yaml` `retry_interval` (off by
default — today's behavior) and `retry_attempts` (default 2), both overridable
per check; a bad settings value logs and stays off, a bad check value fails
the load. No added jitter — completions spread, the stagger holds, the budget
and the bounded pool cap the rest. This settles the open interval-resolution
question: `frequency` stays seconds, the shipped stagger is the jitter answer,
failure backoff is this speed-up; calendar expressions belong to the
recurring-windows work, not to check frequency.

→ Full record: [`adr/0033-budgeted-failure-retry.md`](adr/0033-budgeted-failure-retry.md)

### ADR-0034 — Template slots for dependent packages
**Q:** A deployment needs one local interaction on the dashboard — a click on a
failing leaf's reason line that opens the house issue tracker, pre-filled from
that node and that reason. The parameters mean nothing outside one company, so
the feature cannot live in the library; the surface is server-rendered Jinja
that swaps under a ~10s poll, so it cannot live outside the server either. What
seam lets a dependent package put HTML on our page without owning our templates
and without re-opening what ADR-0018 closed?

**A:** **Named template slots.** The library declares a closed roster
(`slots.SLOTS`) of places and the exact context each hands over; a dependent
package registers **a template of its own** for a slot, plus an optional
**context provider** — deployment code that turns the slot context into the
values its template wants. Data is computed in Python, HTML is authored in
Jinja and rendered by *our* environment, so autoescaping still owns the
untrusted halves of the context. Extension templates are reachable only as
`ext/<package>/<name>`, behind our loader, so filling is **additive and can
never shadow** a core template, and several packages may fill one slot (every
filler renders, in registration order — deliberately inverting the icon-pack
rule, where later registration wins per name). A provider returning `None`
means *nothing here*, which is how placement policy stays with the filler. A
broken provider or template is logged and contributes nothing — the page still
renders; an undeclared slot name in one of *our* templates raises. Core owns
the affordance frame (`.reason-actions` / `.reason-action`), the kiosk renders
no slot, and `/system` lists what registered. First slot: `reason.actions`
(`node`, the unshortened `reason`, `index`, `surface`), on the grid and the
leaf page. Extension **static assets** are explicitly not in this decision; the
JSON envelope is untouched.

*Amended 2026-08-02 — the second slot.* The roster gains **`node.actions`**, context
`(node, surface)`, in a card head and beside the status on a leaf's own page. A slot is
added when something asks for one, and [ADR-0036](adr/0036-addressable-reasons.md) did:
its members/prose split decides where a deployment's action belongs — on a line where
the reasons are addressable members, on the **node** where they are prose, since a
per-line control there would offer to raise a ticket about a stack trace. Additive; the
mechanism and `reason.actions` are unchanged, and both slots are offered on every node
with the filler declining by returning `None`, so this adds a place and not a policy.

→ Full record: [`adr/0034-template-slots-for-dependent-packages.md`](adr/0034-template-slots-for-dependent-packages.md)

### ADR-0035 — A dependent package registers its own configuration aspect
**Q:** ADR-0031 closed the aspect table and warns about anything else in a
configuration root. An extension filling a template slot has parameters an
operator must edit. Where do they go — and how, without the library warning
about the file on every start?

**A:** `config_dir.register_aspect(name, as_file=…, as_directory=…)`, called in
the same import-before-app slot check types and icon packs use. The library's
`BUILTIN_ASPECTS` is the floor: a registration naming one of them is refused
with both shapes logged. A registered aspect is then an **ordinary** aspect —
same shape enforcement, same path-list layering (`aspect_files`), same
first-root-wins helper (`sole_aspect_file`) — while the document's schema and
validation stay entirely with the package that registered it. Names are bare
lower-case stems; every refusal is a warning and a skip, and the first
registration of a name wins. Registered aspects show on `/system`. This is the
seam ADR-0031's own table note predicted.

→ Full record: [`adr/0035-registering-a-config-aspect.md`](adr/0035-registering-a-config-aspect.md)

### ADR-0036 — Addressable reasons: keyed entries, and maintenance on one of them
**Q:** A check that discovers dynamic entries — security findings, waiting pull
requests, jobs — puts twenty of them in one node's reasons. An engineer works on
**one** and the next engineer must see that. The only suppression we have is
per node, so pinning that one finding silences the other nineteen. Do the
entries become nodes?

**A:** No — they become **addressable**, which is all a pin needs. A reason is a
keyed entry, `slug -> text`, in the check's order (insertion order, not sorted:
the order a check emits in is information). `CheckResult.reason` stays tolerant —
`str`, `list[str]`, `dict` or pairs, normalized at construction — so a disk check
changes nothing. But **prose is the default and members are declared**: a failing
check's `check error:` line and its stack trace, or stdout beside stderr, are one
condition in several paragraphs, and silencing the trace while the message alarms
is meaningless. A check says *members* by handing over a **mapping** (its shape
says so) or by setting **`entries=True`** beside a sequence of strings it knows to
be stable — so a check whose strings already carry identity needs no
restructuring. Prose is keyed like everything else but is **not** individually
suppressible; its unit stays the node pin. The engine's failure path therefore
needs no change, and nothing on any surface moves until a check opts in. An
undeclared entry is keyed by a **content hash** (`h-` + 10 hex, `-2`/`-3` on a
taken slug), not an index: an index slides onto a *different* finding when an
entry is inserted above it, while the hash makes "return a stable string"
sufficient. A declared slug is an **identity claim** (the text may be re-worded);
a derived slug **is** the wording. Both obey one rule — *a pin whose slug is not
present does not apply* — so no validator field and no origin flag. The pin lives
in the maintenance side-table, whose key widens from `path` to `(path, slug)`, and
the snapshot joins them ([ADR-0032](adr/0032-status-contribution-boundary.md)
rule 3, honoured from the start for once). **Absence suspends a pin; only expiry
disposes of it** — a failed check replaces its whole reason map, so
delete-on-absence would discard every pin on a bad minute. The entries are
**virtual children** (the ADR-0032 amendment of the same date): the node's own
status is the worst of the unsuppressed set, `MAINTENANCE` when none is left.
A per-entry pin takes the **cap**, not the `escapes` threshold — an entry has no
severity of its own. Staleness still judges the raw reading, quiet entries are
shown and counted, events and history keep plain strings (whether an entry's
appearance is ever recorded is left open). An entry is addressed in a **query parameter
or a form field, never a path segment** — `%2F` does not survive `PATH_INFO`, and
the natural slug (`acme/api-pr-412`) contains a slash; the surface is the existing
leaf detail page. The envelope grows additively: `reason` unchanged, a new
`reasons: [{text, maintenance}]` in the contract round's one `schema_version`.
Rejected: a node per entry (the event log alone — 200 findings is a fifth of the
deque — plus the envelope, the density budget and a tree-level prune, all to buy a
history we are not taking).

*Amended 2026-08-02 — built.* The write's form field is **`slug`**, not `reason`: that
name is already the pin's explanation text on the same form. The optional linkable
`/maintenance/<path:branch>?reason=<slug>` page is not built; the leaf detail page the
decision names as the surface carries the control. The widened key is persisted by
[ADR-0014](adr/0014-maintenance-persistence.md)'s amendment of the same date — one
side-table, one file, two tables in it — and that file's shape is a **clean break**,
not a migration.

*Amended again 2026-08-02 — an entry pin reports where a node pin does.* The first
pass built setting one and forgot indexing it: the maintenance index walked node pins
only, so a silenced reason reached neither the strip pill, nor the "contains
maintenance" pip, nor `/maintenance` — and a node whose members were **all** pinned
read `MAINTENANCE` on the dashboard while the maintenance page denied any pin was
there, which is exactly the un-indexed suppression
[ADR-0032](adr/0032-status-contribution-boundary.md) rule 5 forbids. The two surfaces
answer different questions and so take different shapes: the **capped popover**
summarizes one row per *node* with a count (*3 of 20 reasons*; *all 20 reasons* where
nothing is left reporting), because twenty rows from one node would evict every other
node from it, and **`/maintenance`** lists one row per *pin*, with entries in the
check's order under their node's own pin. What names an entry in a list is its **line**
— never the slug, which stays opaque — and the line (*Silenced*) gets a different
column from the pin's justification (*Why*), because both are called "reason" in the
model and are not the same kind of thing. The **query parameter of decision 12 is
built after all**, as `/status/<branch>?reason=<slug>` rather than a second route: on
a 150-finding node the right page is not the right line, so the index links to the
line and the page marks it with one fixed anchor. A slug in a *fragment* was rejected
— legal slugs contain `#` and `%`, it would need an id per line, and it can only fail
silently; the parameter instead lets the server say the one thing nothing else could,
that a pin whose slug the run did not report is **suspended, not deleted**. On the
pip, only a **node** pin still takes a node out of the ancestor set: a node pin cancels
its subtree, an entry pin cancels nothing below it.

→ Full record: [`adr/0036-addressable-reasons.md`](adr/0036-addressable-reasons.md)

### ADR-0037 — Extension static assets: a filler may ship CSS and JS
**Q:** A slot filler can render a link or a form but cannot ship a `.js`, so any
interaction more elaborate than a link is out of reach. How does an extension serve
its own code — and who puts the tag on the page?

**A:** `slots.register_assets(package, *members)`: a **bare member name** inside the
package's `static/` directory (the icon pack's sandbox verbatim — no separators, no
`..`), **`.css` and `.js` only**, read through `importlib.resources`. **The library
emits the tag, never the extension** — a `<link>` or a deferred `<script>` in our own
header, once per page, in registration order, after our stylesheet and after
Bootstrap; an extension writing its own would decide load order and caching for a
document it cannot see. Served from **our own origin** at `/ext/<package>/<member>`,
never a third-party URL: same origin is what keeps a future `script-src 'self'` able
to cover code the library never saw, which makes the eventual
Content-Security-Policy question easier rather than harder. The URL carries an **eight-hex content hash**, which answers
"the extension's version, not ours" more precisely than a release version can.
Login-gated; the kiosk loads none of it, for the same reason it renders no slot.
Every refusal is a warning and a skip. Rejected: CSS only (leaves the dialog out of
reach, which is the thing being unblocked), letting the filler emit its own tag
(exactly the shape the backlog flagged), a third-party URL (makes the CSP an
allowlist of other people's origins), and distribution-metadata versioning (a hash is
the actual question). Note plainly: **an extension's script runs with the page's full
authority** — installing one is trusting it.

→ Full record: [`adr/0037-extension-static-assets.md`](adr/0037-extension-static-assets.md)

### ADR-0038 — The declarative action list: `config/actions.yaml`
**Q:** A deployment that wants "open this node in our issue tracker" must ship an
importable package with a template and a provider, to express a URL with a query
string. Can the common case need no code?

**A:** The library ships a **filler of its own**, driven by a new built-in aspect
`config/actions.yaml` — **layered like the checks**, so a site root adds its actions
to a base root's. An entry is `label`, `url`, `slot` and optionally `icon` and
`under`. It invents **no placement rule**: `slot` is one of the library's two, whose
meanings [ADR-0036](adr/0036-addressable-reasons.md) already settled. `url` is a
template over `{path}`, `{name}`, `{code}`, `{reason}` and `{reasons}` (for a node
action `{reason}` is the first line — the summary — and `{reasons}` all of them);
every value is **percent-encoded**, and only a URL is ever templated, so an action can
never carry markup onto a page. An **unknown placeholder is refused at load** rather
than rendered as a button that lies. `under` is a node path compared **segment-wise**
— the half of the selector vocabulary already frozen, with a `tag:` selector waiting
for node tags. It registers **through the slot seam** as a `builtin` filler, so a configured
chip and a coded one share one rail and one order and `/system` lists both. `icon`
resolves through the existing registry ([ADR-0030](adr/0030-curated-links.md) §3).
This does not reverse [ADR-0034](adr/0034-template-slots-for-dependent-packages.md)'s
rejection of a config-only list as the *sole* seam — it is the shorthand built on top
of it, honest about its ceiling: a configured action is a link, and anything more is a
package filler with its own script ([ADR-0037](adr/0037-extension-static-assets.md)).
Rejected: no filter at all, waiting for tags, folding it into `links.yaml` (a link is
navigation the viewer chose; an action is done to a node), and rendering it beside the
seam rather than through it.

→ Full record: [`adr/0038-declarative-action-list.md`](adr/0038-declarative-action-list.md)

### ADR-0039 — Status roll-up: how a parent derives its status
**Q:** [ADR-0004](adr/0004-status-aggregation-semantics.md) carried three unrelated
decisions under one title. What is left when the other two are lifted out — and what
is the answer to the edge case it left open?

**A:** The **pure derivation**, over stored readings, with no policy in it: worst-of
`ERROR > WARN > OK` among counted statuses; `UNDEFINED` means *not reported yet* and is
ignored; `MAINTENANCE` contributes nothing and cancels its subtree (*why* a node reads
it belongs to [ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md)); always a
`StatusCode`, never a downgrade; and an updater owning a whole branch may set it
explicitly, dropping its children, and owns clearing it. The open edge case — a node
whose children are **all** ignored — is answered **`MAINTENANCE` when any of them was
silenced, `UNDEFINED` when they merely have not reported**. Not taste: the same
question already had an answer one level down, where a node whose *virtual* children
(its reason entries) are all pinned reads `MAINTENANCE`
([ADR-0036](adr/0036-addressable-reasons.md) decision 7), and real and virtual children
may not read differently in one model. *Nothing under here is reporting because we
silenced it* is a different fact from *nothing here has reported yet*, and only the
first is something somebody did on purpose. `Status.get_status_code()` implements this
and nothing else — [ADR-0032](adr/0032-status-contribution-boundary.md) rule 3 requires
that of it — while `StatusTree.effective()` reads the snapshot, because *effective* is
the snapshot's word. Rejected: treating `UNDEFINED`/`MAINTENANCE` as severities;
forbidding explicit inner-node status; keeping the edge case at `UNDEFINED`.

→ Full record: [`adr/0039-status-rollup-semantics.md`](adr/0039-status-rollup-semantics.md)

### ADR-0040 — What a failing check becomes
**Q:** A check raises, times out, or returns something that is not a `CheckResult`.
What does the node say?

**A:** **`ERROR`**, decided by the engine rather than trusted to the check — never a
skipped update, never a stale `OK` left in place. "Unknown" is not available:
`UNDEFINED` means *not reported yet*, and a check that raised **has** reported, namely
that it cannot tell us. The reason is `check error: <message>`, escaped like any
untrusted string ([ADR-0018](adr/0018-markdown-rendering.md)) because an exception
message routinely carries external text. Unless settings say otherwise a **second
reason** carries the innermost five frames as an inert `code()` block — on by default,
because a deployment whose log is awkward to reach should not have to go find the one
thing that explains the failure, and **global rather than per-check**, because the
check that raises unexpectedly is exactly the one nobody thought to flag. The trace is
a *reason*, not a new field, so the cap clamps it, the detail page shows it whole and
the envelope carries it unchanged. A check whose secret references failed to resolve is
the one that is `ERROR` without ever running
([ADR-0023](adr/0023-secret-references.md)). Rejected: skipping the update on failure;
a sixth status code for "cannot tell".

→ Full record: [`adr/0040-what-a-failing-check-becomes.md`](adr/0040-what-a-failing-check-becomes.md)

### ADR-0041 — Maintenance is a contribution rule, not a value
**Q:** Pinning a node wrote `MAINTENANCE` into it and discarded the check's next
reading — the one deviation
[ADR-0032](adr/0032-status-contribution-boundary.md) named. What replaces it?

**A:** A pin is **recorded, never written**. The side-table entry is stored, the check
keeps reporting, and `MAINTENANCE` is **derived in the snapshot** by the same transform
[ADR-0036](adr/0036-addressable-reasons.md) already put there for entry pins — one
evaluation point, two grains of one rule. The snapshot grows **`reported_code`** beside
the derived `own_code`, because once the latter is derived the check's real answer has
nowhere to live, and rule 5 needs it: a card says `maintenance · error`, not just blue.
Clearing restores nothing **because nothing was destroyed** — which fixes a live bug
where a cleared node sat blank until the next check run. The staleness exemption goes
too: a pinned check that dies escalates like any other, taking the worst of its reading
and `WARN`. That was a **second deviation propping up the first** — removing it alone
crashed, because `worst_of` knows only `OK`/`WARN`/`ERROR` and a written-in
`MAINTENANCE` reached it. Transitions under a pin are recorded and marked:
`Event.suppressed_by` names the **rule**, not a boolean, since the clamp, the shield
and the damping counter will each want one — *an unmarked event is one that alarmed; a
marked one is one that didn't.* History counts only unmarked events, so a window stays
one period instead of phantom `ERROR` stretches, while the log finally answers *did it
break during the window?* Pin and clear stay transitions of what the node shows and are
never marked. Behavior is otherwise unchanged: every `own_code` and `code` the API
published before it publishes now, and an existing `var/maintenance.json` loads
untouched. Rejected: stashing the reading and restoring it on clear (fixes the symptom,
nothing else, and this change deletes it); a `maintenance` boolean; a separate
administrative event kind.

→ Full record: [`adr/0041-maintenance-is-a-contribution-rule.md`](adr/0041-maintenance-is-a-contribution-rule.md)
