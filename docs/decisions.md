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
lingering forever — without pulling the Phase 7 store forward?

**A:** A maintenance **side-table** in the tree, written through to a small
**`var/maintenance.json`** (atomic, fixed path) and **restored on startup** before the
engine runs. Every entry has an **auto-expiry** — default **one week** (`config.yaml`),
overridable, no indefinite — swept by the scheduler; and a **startup reap** drops
entries no configured check **covers** (segment-wise on the same root-to-leaf line, so
subsystem and unreachable-branch-leaf pins survive). A deliberate stopgap Phase 7
subsumes.

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
are deferred; satellites (Phase 6) are the real multi-site mechanism.

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
one (password hashing is Phase 7, a pluggable auth provider Phase 5).

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

**A:** The **reference names its source**. A bare name stays an env-var lookup
([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)); a `scheme://address`
reference selects a **resolver the application registered in code**
(`little_sister.secrets`, the same import-before-app slot as check types). Only
addresses appear in config — never values. Secrets resolve **once, at check
instantiation**, never during runs (cloud reads cost money); rotation = restart. A
malformed reference (unknown scheme) fails loudly at load like any config error; a
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
Phase-7 durable store can hold this same line — that belongs to the store choice
itself.

