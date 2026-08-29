# Little Sister — Decisions

> One self-contained digest per decision — the question it settled, the answer, and
> a link to the full Architecture Decision Record in [`adr/`](adr/) for the context,
> alternatives, and date. Reading this page is enough to know **what** we decided and
> **why**; the ADR holds the history.
>
> A decision is in force unless its heading is marked **superseded**.

---

### ADR-0001 — Process & threading model (the in-memory baseline)
**Q:** How do the checks, the shared status tree, and the web server run together
when there is no persistence?

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
**Q:** Where do the Flask secret key and check/API credentials come from with
no secret store?

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
`localtime` Jinja filter (`zoneinfo` + `tzdata`). The same zone also **interprets**
what an admin writes: an unzoned maintenance expiry is read in it, an explicit `Z` or
numeric offset wins, and a DST hole or fold is refused rather than guessed. The
resolved instant returns to the naive server-local storage convention, so the
persistence and JSON timestamp contracts are unchanged.

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

### ADR-0010 — Target Python 3.14 *(superseded by ADR-0054)*
**Q:** Keep `requires-python` at 3.14, or loosen to 3.12+?

**A:** Keep **`>=3.14`** as a deliberate single modern target. The code needs only
3.11 today, but the host is provisioned via uv (the interpreter is managed, not a
distro's), so a high floor is cheap; it simplifies the toolchain and keeps the
free-threading door open (locking is GIL-independent — ADR-0002). No external
contract depends on the runtime version.

→ Full record: [`adr/0010-python-version.md`](adr/0010-python-version.md) — superseded
by [ADR-0054](adr/0054-python-floor-and-development-version.md), which restates what
still stands and lowers the floor to 3.11.

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
covers. Links stay deferred here — settled later by
[ADR-0030](adr/0030-curated-links.md) as a page of their own, so a node never grew a
structured `links:` field.

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
subsystem and unreachable-branch-leaf pins survive). A deliberate stopgap the
persistence phase subsumes.

A pin is **editable in place**, because offering only *Clear* meant that extending a
window was a clear and a re-set: the node alarmed in the gap, and a blank reason falling
back to the literal `maintenance` usually threw the explanation away. The set form is
**reachable while pinned and prefilled** with the stored reason, beside *Clear* —
duration deliberately **not** prefilled, so blank means the configured default here
exactly as it does on an unpinned node, while a **blank reason on an edit keeps the
stored text**, blank meaning *"I did not touch this field"*; on a new pin the literal
`maintenance` stays the placeholder. Reading comes first and editing is on intent: a
pinned item shows its rendered explanation, authorship and expiry, and only an explicit
*Edit* reveals the prefilled raw-Markdown textarea beside the blank new-window field. A
member reason's control occupies a stable end rail and opens only on activation — hover
never inserts a form into the pointer's path.

The entry carries **both dates** — `created_at` / `created_by` beside `set_at` /
`set_by`, which keep meaning *the last write*; absent from an older file they default to
the set values, so it loads unchanged. The write is a **compare-and-set** on `set_at`,
carried as a hidden token (empty = *"nothing is pinned"*) and **exact**, since one
process holds one lock ([ADR-0001](adr/0001-in-process-threaded-engine.md),
[ADR-0002](adr/0002-rlock-snapshot-synchronization.md)); on a mismatch nothing is
written and both texts come back, the admin's own preserved, with one click to take the
stored ones instead. `action=clear` carries the same token. Without the precondition two
admins a minute apart silently lost the first one's words. An **edit emits an event** —
`MAINTENANCE -> MAINTENANCE` is invisible to the code test — but a no-op re-submit does
not.

The key is **`(path, slug)` as well as `path`**, since a pin may name one reason of a
node ([ADR-0036](adr/0036-addressable-reasons.md)), and the file holds two tables,
`{"nodes": …, "entries": …}`. One mechanism at two depths: same entry shape, same token,
same replay, reap and sweep — only the effect differs, since an entry pin writes nothing
into the tree and is joined at snapshot time, which is what
[ADR-0032](adr/0032-status-contribution-boundary.md) rule 3 asks for. Its guarded set
carries `(path, slug, set_at)`, so rewording or extending an entry pin never clears it
or lets the finding alarm in the gap, and it emits **no event**, because it changes no
stored code. That file shape is a **clean break** with the bare node table: no reader
for the old one, no migration, an ignored file warned about and rewritten on the next
save — runtime state the program owns and bounds with a finite expiry, so a
compatibility branch in the read path forever is the worse trade, and a future shape
change follows the same hard-cut rule.

**Finite was not enough** for §4's expiry. A zero or negative duration parsed cleanly,
landed `expires_at` in the past, and the next sweep dropped the entry — reason and both
authorships gone within a tick, behind a redirect that looked like success, which is the
lost-explanation failure the compare-and-set guard exists to prevent, arriving through
the other door. At the far end an enormous duration overflowed the date arithmetic and
`inf` overflowed the parser, neither of them a `CheckError`, so a typo became a 500. A
window is **at least one second and at most a year**, and out of range is **refused, not
clamped** — the form returns with the admin's words and a sentence saying what was
wrong, the same page a refused compare-and-set uses, because the situation is the same.
Only the deployment's configured default still falls back.

The field **names the expiry directly**: unit-suffixed durations, or a small calendar
grammar — full ISO date/time, `MM-DD`, a day of month, `HH:MM`, or weekday plus time.
Blank still uses the configured duration; digits mean day-of-month, so seconds carry
`s`. A **bare weekday**, abbreviated or full and in any letter case, means its next
occurrence at 12:00 in the configured timezone, and when today carries that name it
always means the following week, independent of the current time — an explicitly
supplied time may still select today. Shortcuts choose their next future occurrence,
never clamp an impossible date, refuse DST holes and folds, and obey the same
one-second-to-365-day bound. A native click-opened help table beside every shared field
makes the exact grammar discoverable. All forms resolve to the existing `expires_at`; no
persistence or JSON shape changes.

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
are deferred; satellites (a later phase) are the real multi-site mechanism.

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
plus `rel="noopener noreferrer"` on links (images were disabled, since **enabled**).
One runtime dep
(+ tiny `mdurl`); no CSP or extra sanitizer this slice. `reasons` are the check author's
responsibility (operator-controlled, ADR-0007); the check base provides **`plain()`**
(escape Markdown) and **`code()`** (fence log output) so a check folds external bytes in
safely, and the built-in capturing checks use them. `title`/`description` render inline;
`about`/`reasons` as a block. The JSON envelope is unchanged (raw Markdown).

The admin-authored `MaintenanceEntry.reason` is one of the rendered fields: block
rendering on full read surfaces, inline rendering plus CSS clamping in compact
summaries, and the untouched source in every editor. Raw HTML stays escaped and unsafe
schemes stay rejected. The literal `maintenance` sentinel is not displayed; the
persisted string and `maintenance_details.reason` remain raw Markdown in the same
storage and API shapes.

Fully qualified **bare `http://` and `https://` URLs** render as links, through
markdown-it-py's linkification rule and with the same scheme validation, new-tab target
and `noopener noreferrer` relation as explicit Markdown links. Recognition is
deliberately limited to those two schemes: schemaless domains, email addresses, FTP,
protocol-relative text, code spans and `plain()`-wrapped captured output stay literal.
The runtime dependency takes the `markdown-it-py[linkify]` extra rather than an in-house
URL recognizer.

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
*Superseded 2026-08-08 by
[ADR-0046](adr/0046-user-list-from-the-configuration-roots.md), which restates
everything here except the path resolution: the `users` aspect of the configuration
roots is now the only input. Kept for the history.*

**Q:** For the repo split, how does a deployment supply its own users
when `users.yaml` is read from inside the package today?

**A:** Read the user list from a **deployment-controlled** path — `LITTLE_SISTER_USERS` if
set, else `users.yaml` in the **cwd** — mirroring how `.env` / `config.yaml` are already
found ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). The package ships
**`users.example.yaml`** only and no longer bundles a real `users.yaml`. Format
and fail-fast-on-missing are unchanged; this is a **location** change, not an auth-mechanism
one (password hashing and a pluggable auth provider are in later phases).

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

### Node sibling ordering — natural, case-insensitive (no ADR) — superseded by [ADR-0055](adr/0055-sibling-order.md)
> Superseded by [ADR-0055](adr/0055-sibling-order.md) (*Sibling order: alphabetical,
> unless somebody declares a rank*), which restates the name sort unchanged and puts a
> **declared rank** in front of it. What is no longer true below is the last sentence's
> flat refusal of a curated order: a rank a check or a `nodes.yaml` entry states **on
> purpose** is now honoured. Insertion order and live-grade order stay rejected.

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

### A title that only repeats the name is not drawn (no ADR)
**Q:** A node's `title` is a nicety beside its `name` (ADR-0017), and a check with
nothing better to say hands back the name again with a capital letter. Severity bands
are the visible case: every `github` / `wiz` band chip reads `critical Critical`,
`medium Medium`, `none None` — twice the width, twice the reading, no second fact, on a
card whose chips already compete for one line (ADR-0024/0028). Where does that get
fixed?

**A:** **In the view, in one place** — `titles.py`, whose single predicate every surface
calls: the grid's leaf chips, box and card head lines and the heartbeat strip, the page
band beside the breadcrumb, the inspection popover (ADR-0019), the `/maintenance` pin
table and the `/copy` hand-off. It folds **case**, `_` / `-` / a space, and runs of
whitespace, so `pull_requests` and *Pull requests* are one string and so are
`code_scanning_alerts` and *Code-scanning alerts* — the hyphen deliberately included,
because that is the same duplication wearing better typography. Nothing else folds: a
title that adds anything at all survives. The comparison is on the **raw** values,
before the Markdown renderer (ADR-0018), which leaves one asymmetry accepted on purpose
— `_critical_` folds to the name and goes, `**Critical**` does not — because closing it
means parsing Markdown in what was meant to be a string comparison, and the error it can
make is keeping a redundant title rather than dropping a meaningful one.

It is **display, never data**: the check said something and the tree stored it, so this
is not a `title = None` in the snapshot. The JSON envelope keeps emitting the field
(dropping one would be an ADR-0008 contract change) and a client rendering its own chips
keeps its own decision about the word. Small, low-risk display change — recorded here,
no ADR.

### ADR-0024 — Dashboard layout: bounded heights, positional stability — superseded by [ADR-0056](adr/0056-stable-useful-dashboard-flow.md)
> Superseded by [ADR-0056](adr/0056-stable-useful-dashboard-flow.md), which
> restates the density, heartbeat and maintenance rules while replacing the
> visible-node budget allocator.

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

The same rule now spends **spare grid tracks from stable topology**. The server
counts the card and every descendant the current depth/filter can render, independent
of status, reasons and chip presentation, and allocates each consecutive row from
those weights and the viewport's ordinary-track count. Every root starts at one
track; a spare goes to the greatest `weight / span` among the roots still eligible,
and a root is eligible while its weight exceeds the internal 16-nodes-per-track
budget — the entry price for widening, not a ceiling on it — and its span is below
its **branch limit**, the widest sibling set anywhere in its visible subtree. A
wider root grids only a genuine descendant branch of full boxes — never a
single-child wrapper or an inline chip run. Node-set, depth/filter and viewport
changes may reflow; a status-only poll may not. The old auto-fill grid remains the
no-JavaScript fallback.

→ Full record: [`adr/0024-dashboard-layout.md`](adr/0024-dashboard-layout.md)

### ADR-0025 — Check-provided subnode metadata (`about` / `title` on `CheckResult`)
**Q:** A branch check knows what its subnodes *are* (a metrics check's `disk` /
`memory`), yet the subject label `about` and short `title` reach a child node only
through a per-path `nodes.yaml` entry — so a **type-inherent** subnode identity has to
be copy-pasted into every deployment and host. Where should those labels come from?

**A:** From the **type**, and read by the **library**: a check only declares. A type
states `subnode_defaults` (`name → {title, about, show_when_quiet}` — the shipped
per-aspect maps, shaped like the `subnodes:` block itself) and `label_tokens`
(`token → value`) as common constructor keywords beside the block's flag map; the
library resolves each field once — configured text when present, else the declared
default, `{default}` substituted and `{token}`s expanded by the same plain replace — and
the engine stores the resolved text per child name, at any depth. Precedence per field
is **`nodes.yaml` > declared or check-provided > empty**, kept by **seed-once**
semantics: startup seeding (`set_about` / `set_title`) overwrites, the engine's runtime
write **fills an empty field only**, and since `nodes.yaml` is seeded before the first
tick it always wins, so neither tree nor engine needs provenance state. Labels **freeze
at first fill** (stable identity, not live status — changing text is `reason`), which
also pins tokens to construction-time facts structurally. A label carried on a
`CheckResult` **child** — `about` / `title`, ignored on the root like `name` — remains
the fallback for a name nothing declared or configured, so a check stamping a
dynamically discovered child keeps working.

The block was check-mediated at first, on the argument that layering the labels needs
the type's own default text and tokens. That argument is contingent rather than
principled: it held only while those defaults lived as *code the check applies*.
Declaring them as data closes two holes — a `subnodes:` label on a type that never read
the block was a silent no-op and now reaches every branch type, and substitution becomes
one library contract, plain `str.replace` with token values inserted as Markdown-active
text and raw HTML escaped at render
([ADR-0018](adr/0018-markdown-rendering.md)), so a check exposes only values it would
print as Markdown. `parse_subnodes`, `resolve_text` and `expand_tokens` lose their
external callers and retire from the authoring facade — a **breaking** surface change
taken deliberately, with every consumer family-owned and moving in lockstep, no
compatibility window, said at the top of the release notes. The per-leaf `descriptions:`
map is untouched (a different field, write-through); `description` / `config` stay
write-through, and the JSON contract and web surface are unchanged. A **yaml-aware
engine** and **per-field provenance on `Status`** were rejected as buying live label
updates nothing needs.

→ Full record: [`adr/0025-check-provided-subnode-metadata.md`](adr/0025-check-provided-subnode-metadata.md)

### Clickable breadcrumbs (no ADR)
**Q:** The header path trail (`status / system/alpha/disk`) was a single non-clickable
span — only `status` linked home. How do we let it navigate up the tree?

**A:** Each **ancestor** segment links to its level (its cumulative path), built by a
`breadcrumbs` Jinja filter and rendered by a shared `_breadcrumb.html` partial used in
both the dashboard and detail-page headers; the **current** node (last crumb) is plain
text. Small UI navigation change — recorded here, no ADR.

### Envelope fields — node metadata + maintenance details (additive to ADR-0008)
**Q:** Which node-metadata fields (check `config`, `about`, `title`, maintenance expiry)
should join the read-only JSON envelope ([ADR-0008](adr/0008-json-output-api.md))?

**A:** **All four**, as an **additive** change (`schema_version` stays **1**). The envelope
serves both a display client and a federating satellite, so it now carries the same
metadata the origin renders: **`about`**, **`title`**, **`config`** as **raw Markdown**
(the client renders, ADR-0018), and a new **`maintenance_details`** object
`{reason, set_by, set_at, expires_at}` (timestamps RFC 3339 UTC, **null** when not under
maintenance) beside the existing **`maintenance`** bool — the bool is left **unchanged**
(repurposing it to an object would be breaking). Contract:
[`api/openapi.yaml`](api/openapi.yaml). Recorded here, no ADR.

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
(`resolve_setting` — see the record), and `SECRET_KEY` unset now means
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
persistence phase's durable store can hold this same line — that belongs to the store
choice itself.

### ADR-0027 — Observation timestamps: stamped where written, rolled up while unambiguous
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

The mount registry **counts checks per path**
([ADR-0044](adr/0044-run-facts-on-the-node.md)), so an unwritten ancestor above one
mount **shared by two checks** inherits **no** stamp: a set collapsed the pair into one
"sole" mount, and rule 3 then attributed upward a value that flips between two checks'
run times — rule 4's ambiguity. The shared node itself keeps its own last write
(rule 2). A branch check's own mount needs no separate stamping — it is written every
run; its bare look was display-only, closed by ADR-0044's topmost-visible rule (both
records carry the correction). The engine writes the run's **facts** — wall time and
armed next slot — beside each result, and the snapshot resolves them exactly where the
count is one; nothing is synthesized from children.

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

The client-side filter matches **the entry's title and its group's** — still titles,
never prose. Measured on the first real page rather than reasoned about: with entry
titles alone, typing a category name matched nothing at all, which reads as a broken
page rather than as a narrow rule.

The search path has one more rung than the roster above: **`config/links/icons/` is the
deployment's own pack, discovered by file name**, so a file dropped there needs no
`icons:` entry. It sits above the packs a dependent package registers and below the map
(which stays the way to name a URL or say `none`); pairs follow the built-in pack's
`<name>-on-light.*` naming.

Reachability is probed **when somebody opens the page**, not on a timer, and only when
the newest answer is older than `interval:` — which keeps its name and its `6h` default
while meaning *how stale an answer may be* rather than *how often a timer fires*. The
pass never blocks the render: the page shows what is in memory with each verdict's age,
and one open's pass lands on the next. The audience was always the reader of this page;
structural validation already covers every icon that is not remote, so a timer would
mostly probe an empty set; and the engine's tick would have bought a scheduler seam that
is skipped exactly where the page still works. *Every n-th open* was rejected against it
— a count refreshes five times under a reloading reader and never under a twice-a-day
one. *Never blocks* governs the **open**, not the reader: a deliberate **check now**
control re-probes on demand and does wait, under a deadline, sharing the one pass.

Two things a first reading of that got wrong. An `interval:` the parser cannot read, or
a non-positive one, **falls back to the default** rather than raising — the loader keeps
the key as raw text and validates nothing, so `6 hours` took `GET /links` to a 500. And
a target whose server answers garbage costs its own verdict, not the pass:
`http.client.HTTPException` is neither an `OSError` nor a `ValueError`, escaped the
probe unwrapped, and left every remaining target unanswered — which the trigger read as
"never asked" and retried on every subsequent open.

**A pass carries its own deadline and abandons what has not answered.**
`REQUEST_TIMEOUT` bounds a socket *operation*, not a request, so a server
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
error**, and an unrecognized entry **warns and is ignored** — reported once at the end of
the registration window rather than when a root is resolved
([ADR-0070](adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)) — so an
operator's stray file can never stop the monitor. `config.yaml` becomes **`config/settings.yaml`** and
`users.yaml` becomes **`config/users.yaml`** in the same move — a deployment reorganizes
**once**, not once per aspect — while `LITTLE_SISTER_CONFIG` remains an explicit
single-file override that **bypasses layering entirely** (the matching user-list
override is retired by
[ADR-0046](adr/0046-user-list-from-the-configuration-roots.md), on the strength of
this record's own first-root-wins rule). **`.env` and
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

The boundary reaches **one level below a node**. A node's
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

`reason.actions` also hands over the context name **`line`**: the whole reason entry,
carrying the **slug** an action needs to address one finding, plus its own code, its
`running` flag and any pin. `reason` stays the line's text. Recovering the entry from
`index` was possible and is what [ADR-0036](adr/0036-addressable-reasons.md) decision 3
refuses — an index moves when an entry is inserted above it. With it comes the rule the
roster was missing: **a provider receives the names it declares**, or all of them when
it declares `**kwargs`, so a growing context can never cost a filler written against an
earlier one its chip. Adding a name was always called a compatible change; that is what
makes it one in fact.

The second slot is **`node.actions`**, context `(node, surface)`, in a card head, on
each **nested box** under a card, and beside the status on a leaf's own page. A slot is
added when something asks for one, and [ADR-0036](adr/0036-addressable-reasons.md) did:
its members/prose split decides where a deployment's action belongs — on a line where
the reasons are addressable members, on the **node** where they are prose, since a
per-line control there would offer to raise a ticket about a stack trace. The nested
boxes are in the roster because the first deployment to fill the slot found the gap by
rendering: a card is the top of a subtree and is usually a container with no reading of
its own, so a filler that declines a node with nothing to say declines exactly the nodes
that have card heads — while the failing **leaf**, which is what an action is nearly
always about, sat in a box that carried no slot at all. A quiet leaf stays a chip and
carries none. Both slots are offered on every node, with the filler declining by
returning `None`, so the roster names places and never policy; `where` is part of the
version contract, which is why it is recorded here rather than left to the template.

One presentation rule belongs with them. In a card head the `node.actions` rail is
positioned **over** the title's space — a chip is something to click, a title is a
nicety — and a chip is transparent so that it reads on every status fill; together those
drew both sets of glyphs into the same pixels. Every card and node box declares its fill
as **`--ls-surface`**, and the rail repaints that exact fill beneath its chips while
they are showing, the title fading into it; a card at rest keeps its whole title. No
ink meets a new background, so every measured contrast pair holds.

→ Full record: [`adr/0034-template-slots-for-dependent-packages.md`](adr/0034-template-slots-for-dependent-packages.md)

### ADR-0035 — A dependent package registers its own configuration aspect
**Q:** ADR-0031 closed the aspect table and warns about anything else in a
configuration root. An extension filling a template slot has parameters an
operator must edit. Where do they go — and how, without the library warning
about the file on every start?

**A:** `config_dir.register_aspect(name, as_file=…, as_directory=…)`, called in
the same import-before-app slot check types and icon packs use — a rule about the
**read**, not about the warning: `aspect_in` looks the name up in `ASPECTS`, so an
undeclared aspect is a `KeyError` rather than a diagnosis. The warning could not have
been the reason, because the registering call is **itself** the first resolution, which
made the rule as first written unfollowable; the scan is silent now and the report runs
at the end of the registration window
([ADR-0070](adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)). The library's
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
**virtual children** (ADR-0032 decision 8): the node's own
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

As built, the write's form field is **`slug`**, not `reason`: that name is already the
pin's explanation text on the same form. The widened key is persisted by
[ADR-0014](adr/0014-maintenance-persistence.md) — one side-table, one file, two tables
in it — and that file's shape is a **clean break**, not a migration.

**An entry pin reports wherever a node pin does.** Setting one without indexing it left
the maintenance index walking node pins only, so a silenced reason reached neither the
strip pill, nor the "contains maintenance" pip, nor `/maintenance` — and a node whose
members were **all** pinned read `MAINTENANCE` on the dashboard while the maintenance
page denied any pin was there, which is exactly the un-indexed suppression
[ADR-0032](adr/0032-status-contribution-boundary.md) rule 5 forbids. The two surfaces
answer different questions and so take different shapes: the **capped popover**
summarizes one row per *node* with a count (*3 of 20 reasons*; *all 20 reasons* where
nothing is left reporting), because twenty rows from one node would evict every other
node from it, and **`/maintenance`** lists one row per *pin*, with entries in the
check's order under their node's own pin. What names an entry in a list is its **line**
— never the slug, which stays opaque — and the line (*Silenced*) gets a different
column from the pin's justification (*Why*), because both are called "reason" in the
model and are not the same kind of thing. On the pip, only a **node** pin takes a node
out of the ancestor set: a node pin cancels its subtree, an entry pin cancels nothing
below it.

Decision 12's query parameter **is** built, as `/status/<branch>?reason=<slug>` rather
than a second route or the linkable `/maintenance/<path:branch>?reason=<slug>` page the
decision sketched: on a 150-finding node the right page is not the right line, so the
index links to the line and the leaf detail page — the surface the decision names —
marks it with one fixed anchor. A slug in a *fragment* was rejected: legal slugs contain
`#` and `%`, it would need an id per line, and it can only fail silently. The parameter
instead lets the server say the one thing nothing else could, that a pin whose slug the
run did not report is **suspended, not deleted**.

Decision 8's premise is narrower than it reads. An entry may declare a **code of its
own** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)), so "an entry has no
severity of its own" describes entries that declare none — the default, and permanently
right for a severity-banded leaf. The cap-not-`escapes` *effect* for entry pins stands
unchanged; whether a pin on a coded entry may take `escapes` belongs to the pin-policy
design pass. Decision 13's envelope carries `code` and `running` beside `text` and
`maintenance`, still whole in the client contract round.

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
reason** carries the innermost five frames — chained causes included — as an inert
`code()` block, on by default,
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

### ADR-0042 — A reason entry carries its own code
**Q:** One node, mixed lines: this workflow failed, that one passed, a third is red
*and* already re-running — and a severity-graded check collapses critical-to-low
findings into one node code, smuggling the per-line severity back through an emoji.
Is that a sixth status code (`RUNNING`, an `INFO` band), or something else?

**A:** **No sixth code** — the vocabulary stays closed (ADR-0032 decision 4), and
`INFO` collapses onto `WARN`: *seen and counted* ⇒ `WARN`, *available but not
counted* ⇒ `OK` with a reason. Instead **an entry may declare a code**: the node's
own status derives from its entries — worst-of over virtual children, `UNDEFINED`
ignored, suppressed entries contributing nothing, the ADR-0039 tiebreak one level
down, which makes ADR-0036 decision 7 literal — an entry-bearing node declares no
code of its own, an **empty entry set reads `OK`** ("nothing to report" is not
"nothing reported"; a check that could not enumerate reports prose and declares),
and declaring both is refused at the `CheckResult` seam. A per-entry **`running`**
flag shows work in flight as display (`is-running` class, italic; the words still
say it) without touching the roll-up, so a failed job's verdict stays red and
visible under its rerun. Check-facing shape: a frozen `Entry(slug, text, code,
running)` accepted beside the untouched tolerant forms; uncoded entries carry the
node's code forever, which severity-banded leaves keep permanently. Healthy entries
are **per-aspect opt-in, off by default**; a run in flight always yields a line in
the default view; ordering becomes the check's duty (non-OK, then in-flight, then
healthy). Severity *mapping* stays deployment config (`severity_map`); whether lines
carry codes is the check's structural statement about its data, never a knob. The
envelope changes nothing until the client contract round. Rejected: a `RUNNING`
code (one field, two facts — the destroyed-reading mistake ADR-0041 removed,
re-created; no defensible rank; `UNDEFINED` already covers never-completed; and a
sixth code fails silently in every fallback branch), a check-set pin (a check that
can pin itself can silence itself), Markdown emphasis as the running channel
(`shorten` is not emphasis-aware), a second entry for the in-flight run (churns the
set, strands pins).

→ Full record: [`adr/0042-entries-carry-their-own-code.md`](adr/0042-entries-carry-their-own-code.md)

### ADR-0043 — The coverage backstop: an empty scope is never silently green
**Q:** A check that discovers its own subjects returns an empty or over-narrow
scope — a filter typo, a team that lost its repositories — and every aspect loops
over nothing and reports `OK`. Green then means "nothing to report" and "nothing is
being watched" identically. What guards the difference?

**A:** A third standing invariant beside liveness and fail-toward-alarming
(ADR-0032 rules 6–7): **a check that discovers its own scope reports that scope,
and an empty scope is never silently green.** Zero scope is a **`WARN` on the
check's own node**, naming the filter that produced it — `WARN`, not `ERROR`,
following the zero-checks heartbeat precedent: the check works; the world or the
configuration is wrong. The scope **count** rides as an `OK` reason on the
container; the **roster** goes in `report`
([ADR-0044](adr/0044-run-facts-on-the-node.md)) — the roster is presence, an entry
is a claim. The expectation is the **check's business**: one `expect_min`
comparison whose default is 1, and the setting **floors at 1** — a configurable
zero would let a deployment silence the backstop. Subject children still render
when the scope is empty (a leaf you can see is empty is a leaf you can see is being
watched), and "overdue" follows the same ownership rule — core provides nothing for
either. Rejected: `ERROR` at zero, a core-enforced minimum, leaving it in the log
(the hole itself), a node per discovered subject.

→ Full record: [`adr/0043-coverage-backstop.md`](adr/0043-coverage-backstop.md)

### ADR-0044 — The run on the node: the container stamp, run facts, and `report`
**Q:** A branch check's container shows no check time although one check answers
for everything below it; the last run, wall time and next run hide behind the admin
`/system` page; and the checks that publish their configuration onto a container
node find it rendered nowhere. What may a node say about the check behind it?

**A:** The mount registry **counts checks per path**, and the engine **writes the
run's facts onto a sole-check container** after each run
([ADR-0027](adr/0027-observation-timestamp-semantics.md) amended: ancestors above a
mount shared by two checks inherit no stamp by count — a value flipping between two
run times is rule 4's ambiguity — while the mount itself, written every run, keeps
its own last write; nothing is synthesized from children; the container's stamp was
never missing, only unrendered — the display rule below is what closes the visible
gap). **One ownership rule for four facts** — run time, wall time, next
run, and the check's own text: all belong to the check that owns the node *alone*,
withheld where two checks share it. The node gains a small **`run`** object (wall
time + next run, **engine-sourced** — under ADR-0033's retry, `timestamp +
frequency` is wrong exactly when someone watches a failure) and a **`report`**
field: what the run *found*, write-through Markdown beside `config`'s what-it-ran-
*with* (ADR-0013), shown on the node's page and never on the card, and never a
status claim. On a shared container, `report` goes on the owned child subtrees —
the rule and mechanism `config` already uses. **Status, not volume,** separates
reasons from `report`: items with verdicts of their own are entries (capped by
`reason_cap`); a code-less list is scope. Display: the time shows on the **topmost
node visible in the current view** and is suppressed below where it would be
identical; the head line gains the next update beside the check time —
**`22:25 → 22:30`**, absolute because a frozen relative "in 4m" lies under a
failed poll while a frozen absolute recedes honestly (both at minute precision —
seconds carried no information worth the row width — and the arrow is suppressed
where it would render the very value beside it, so a sub-minute schedule shows a
bare time); a stalled check shows a next-run in the past and staleness carries
the alarm; the root stays blank. The
**branch head becomes a real node header** (run facts, `config`, `report`; the
kiosk keeps none). The envelope is untouched until the client contract round.
Rejected: `max(children)` stamps, a view-layer join against `engine.info()` (the
API stays blind), the roster in `config` (outputs filed under inputs), live counts
in `about` (seed-once would make them lies), a relative next-run on the card.

→ Full record: [`adr/0044-run-facts-on-the-node.md`](adr/0044-run-facts-on-the-node.md)

### ADR-0045 — User avatars live with the user-list aspect
**Q:** The top bar identifies the signed-in user by name, but `config/users.yaml` has
nowhere inside its aspect to carry a picture. Does the configuration framework infer a
directory whenever files appear, and how does one user name an avatar safely?

**A:** The shape stays **explicit per aspect**: `users` now declares both the flat
`config/users.yaml` form and a directory form containing `users.yaml` beside
`avatars/`; dependent packages continue declaring their own legal forms through
`register_aspect`. An optional per-user `avatar:` is a **bare name**, with or without an
allowed image extension, resolved only inside that `avatars/` directory — no top-level
registry because one user has one picture. A missing, invalid or ambiguous reference
warns and falls back to the packaged neutral avatar without affecting login. The
settings trigger shows it beside the first name. A login-gated `/user/avatar` route
serves only the session user's selected file, never takes a username or path, and uses a
private short cache plus an ETag. Avatars sit inside the aspect's directory form; the
single-file override they could also sit beside is retired by
[ADR-0046](adr/0046-user-list-from-the-configuration-roots.md).

→ Full record: [`adr/0045-user-avatars.md`](adr/0045-user-avatars.md)

### ADR-0046 — The user list comes from the configuration roots, and nowhere else
**Q:** `LITTLE_SISTER_USERS` names one user-list file and bypasses the configuration
roots. Two later records moved everything around it and kept the variable — is a
second path into *who may log in* still earning its place?

**A:** **No — it is retired, and startup refuses while it is set.** `users` is the one
aspect that does not layer ([ADR-0031](adr/0031-deployment-config-directory.md)): the
first root declaring it **wins whole**. So a users-only root named first in the
path-list already *is* a single-file override —
`LITTLE_SISTER_CONFIG_DIR=/etc/little-sister/identity:config` — and the variable bought
only a second resolution branch in the loader, a second one in the run scripts, and its
own avatars rule. The **hard cut** is deliberate: the name is never honored again. But
unlike `LITTLE_SISTER_CHECKS_DIR`, whose removal announced itself (no checks ⇒ no
start), a stale user-list variable would leave an instance looking healthy while
authenticating against **a different list** — so it is read in exactly one place, the
startup seam, in order to **refuse**, and the run-script preflight refuses identically.
Permanently: a sunset needs a deletion nobody is scheduled to make.
ADR-0020's other decisions are restated unchanged (deployment-controlled, no packaged
list, fail-fast, same format). `LITTLE_SISTER_CONFIG` **stays** — settings merge per
key, so a prepended root layers instead of replacing, and no path-list spelling
reproduces it; the symmetry of the two names was never the argument.

→ Full record: [`adr/0046-user-list-from-the-configuration-roots.md`](adr/0046-user-list-from-the-configuration-roots.md)

### ADR-0047 — A node keeps notes, and they outlive it
**Q:** A maintenance pin carries a line of Markdown saying why, and it is where an
admin records a ticket, a finding, who to ask. That line dies with the pin — four
ways, one of them silent. What should survive, and for how long?

**A:** The field is renamed **`note`** (freeing `reason` for what a *check* reports),
and a node keeps a **note history** rather than a current explanation. The note is
appended when the pin is set, not when it ends, so expiry does nothing to it; it is
editable while its owning pin is live and frozen afterwards, and it captures the node's
code and reason lines **as they stood**, which is what makes "the same problem as
before" answerable. Notes are deliberately **not a contribution rule**
([ADR-0032](adr/0032-status-contribution-boundary.md)): they transform no code and
never enter the roll-up. They are also **exempt from coverage reaping** — a check that
left the configuration and came back is exactly the case worth serving — which makes
them the first state here that is an *archive* rather than a projection of the live
check set, and obliges an index searchable independently of the tree. Retention is
four parameters: a note is retired iff it is **not among the last `notes_keep`** and
either older than `notes_max_age` or the node holds more than `notes_cap` and it is
older than `notes_min_age` — defaults 10 / 50 / 13mo / 25mo, **the count floor winning
over everything**, because the node that has been healthy longest would otherwise lose
precisely the history that lets anyone recognize the problem when it returns. Thirteen
months is *more than a year*, twenty-five *one full repeat plus margin*. The keys live
in `settings.yaml`, the sweep runs on the scheduler tick, and the table is its own
`var/notes.json` on [ADR-0014](adr/0014-maintenance-persistence.md)'s discipline.

→ Full record: [`adr/0047-node-notes-and-their-retention.md`](adr/0047-node-notes-and-their-retention.md)

### ADR-0048 — The Content-Security-Policy is assembled, never a constant
**Q:** A Content-Security-Policy is one response header, so setting it is one line. But
a dependent package — today an extension, later a separately installable check or
provider plugin — may need origins this library cannot know: a filler's script calling
an issue tracker, a vendor's avatars in a reason line, an identity provider's redirect.
(A check's own API traffic is server-side and invisible to the policy.) Who decides what
the policy contains?

**A:** Nobody, once. The policy has **no constant**: a `csp` module holds the library's
defaults plus contributions and composes the header **at application creation**, after
every registration has run and the configuration is loaded — never at import, because
import is when contributions are still arriving. A package contributes through a
module-level registry (`csp.allow(directive, source, by=...)`) from the same
import-before-app slot it already uses for check types, fillers, assets, icon packs,
aspects and secret resolvers, and a refusal is a warning and a skip like every other
registration here. A contribution may name an **origin, never a keyword** —
`'unsafe-inline'` and friends are the deployment's call, not a dependency's, or the
policy is decorative for everyone else in the process. Where the host is
deployment-specific it is **declared, not written** (`csp.origin_of("<aspect>.<field>")`,
resolved at assembly and reduced to `scheme://host[:port]`), so it is never duplicated
out of the package's own aspect and cannot drift. The deployment keeps the last word
through a `csp` block in its configuration, so an unanticipated source is a config line
rather than a fork. The first policy shipped is **Report-Only**, violations at
`WARNING`, no store — enforcement is a separate later decision — and `/system` shows
the effective policy with the contributor of each source. What made this tractable is
[ADR-0037](adr/0037-extension-static-assets.md): `script-src` names **origins, not
files**, so same-origin extension assets are already covered by `'self'` and the open
question was only ever what a package *reaches*.

→ Full record: [`adr/0048-an-assembled-content-security-policy.md`](adr/0048-an-assembled-content-security-policy.md)

### ADR-0049 — The check-authoring surface is contract, and the gate holds it
**Q:** §11 promises the check *registry* — but a check type is written against a base
class, a result type, the metadata helpers, the slug vocabulary and the typed config
readers, none of which were promised. Harmless while every check sits in a repository
we bump in one commit; a silent `ImportError` at somebody else's process start once a
check type lives behind its own tag. What may a check type outside this repository
import?

**A:** A named list, in `architecture.md` §11, and the gate holds it. The import point
is the **package** `little_sister.checks`, never a module beneath it — `checks.base`
is where most of those names live today, which is not what they are — so a refactor
inside the module stays free while the promise holds still, and the subnode-metadata
helpers are re-exported through the facade rather than promised at their module path.
`tests/test_public_surface.py` parses the list out of the doc and imports every name
(doc → code); for each module that declares `__all__` the two lists must be
**identical** (code → doc). That measures **drift** — a name renamed by a refactor
that looked local, or exported without being promised — not a coordinated rename,
which is a deliberate act the version-bump rule governs. Adding a name is compatible;
removing or renaming one is a version bump and a new ADR, exactly as for a template
slot. **Logging is promised as a behavior, not a name**: `little_sister.logger` is
*not* on the list — a plugin calls `logging.getLogger(__name__)` — and what is
promised instead is that the library logs through the standard hierarchy and
configures the **root** logger only when the application has not, so a dependent that
sets up its own logging keeps its handlers *and its level* and gets little-sister's
records in them. Writing that down fixed a real defect: the root `setLevel(DEBUG)` ran
outside that guard.

The level *inside* that guard is **INFO**, named by
`LOG_LEVEL` when a deployment wants another. `DEBUG` collected no record the library
writes — nothing in it logs below INFO — and every record its dependencies write; one
deployment's log was two thirds AWS SDK request detail. The variable is part of the
default and stops where the default does, so it cannot overrule an application that
chose its own level. A chatty dependency is still capped by its **own** logger name,
which adds no handler and so leaves the default running.

→ Full record: [`adr/0049-the-check-authoring-surface.md`](adr/0049-the-check-authoring-surface.md)

### ADR-0050 — A declared slug comes from the provider's identifiers
**Q:** [ADR-0036](adr/0036-addressable-reasons.md) made a reason line addressable but
left *where a slug comes from* to the check, with a content hash as the fallback. Two
check types answered it the same way through one shared helper in the deployment — and
that helper now has to serve check types in repositories of their own. Where does the
rule live?

**A:** Here, as `slug(*parts)` in `little_sister.reasons`, beside `derived_slug` and
`MAX_SLUG_LENGTH` and on the check-authoring surface. It is not a rule about a
provider or a deployment: it is a rule about little-sister's own slug contract. Build
identity from **identifiers the provider already owns** — never from the rendered
text, because a hash *is* the wording and improving a line would drop every pin on it,
and never from a position, because an index slides onto a different finding with
nothing looking wrong. The helper narrows harder than `normalize` validates
(`[A-Za-z0-9._-]`, everything else collapsed), so a token needs no escaping anywhere,
and an over-long slug keeps a readable prefix plus a hash of the whole value rather
than being truncated onto a neighbour. Which identifiers a given check uses stays with
that check type, in its own repository.

→ Full record: [`adr/0050-slugs-from-provider-identifiers.md`](adr/0050-slugs-from-provider-identifiers.md)

### ADR-0051 — What startup refuses at the plugin boundary
**Q:** Once a check type arrives as a separately released package, two things can go
wrong silently: two packages claiming one `type:` name (the registry overwrites, so
import order decides whose code answers for whose configuration), and a plugin
outliving the surface it was built against (the install-time floor has no ceiling).
What does the library do about each?

**A:** It refuses, at startup, with both parties named. **Type names stay bare**
(`type: github`) and a name is **claimed once**: a second registration raises,
naming both classes, rather than letting import order pick a winner — re-registering
the *same* class stays fine, since a reloading server re-runs its decorators. And the
check-authoring surface gets an **epoch of its own**, `API_VERSION` (currently 1),
which bumps only when a promised name is removed or renamed or a documented behavior
changes — never for anything else in a release, so a plugin follows its contract
rather than the library's cadence. A package declares its epoch with `require_api(n)`
beside its registrations; a mismatch refuses naming both numbers. The epoch is held
by a **snapshot** of what it promised (`tests/fixtures/check_api_v<n>.txt`), which the
gate requires the surface to still contain — closing the one hole
[ADR-0049](adr/0049-the-check-authoring-surface.md) left, since a rename that edits
the code and the doc together cannot touch a snapshot a released plugin was built
against. Both refusals are **hard**, unlike the warn-and-skip of the other
registration seams: a slot that fails to fill leaves a page missing a chip, while
these two leave a monitoring system reporting confidently about something it is not
measuring. `/system` lists every registered type with the package and version that
answers for it.

→ Full record: [`adr/0051-what-startup-refuses.md`](adr/0051-what-startup-refuses.md)

### ADR-0052 — Plugin names: one convention for a git dependency and a published one
**Q:** The first plugins were consumed as **git dependencies**, with an index to come.
A distribution name is the most expensive identifier in the system to change — a
rename is a new project for every consumer, and the old name stays on the index for
whoever asks next. Do the names chosen now survive publication unchanged?

**A:** Yes, by construction, and that is what makes publication a packaging change
rather than a migration. One word in three spellings: distribution
`little-sister-<x>`, import package `little_sister_<x>`, check type `<x>`. A
`[tool.uv.sources]` entry is a **source redirect, not a different package** — the
dependency name and every `import` are the same whether the wheel came from a tag or
an index — so publishing deletes a table from the consumers' configuration and changes
no code, on the one condition that the git era already used the published name. The
name is therefore **checked when the repository is cut and claimed by its own first
release** — every package has code and a version to cut, so nothing has to be invented
to hold a name early, and an empty placeholder release would not hold one anyway (PEP
541 calls that squatting). No `little_sister.` sub-namespace: the library is an ordinary package with
its own `__init__.py`, so a separate distribution cannot add submodules to it, and a
plugin importing as part of the library would read as *inside* the version contract it
is explicitly outside. The type name is the package's suffix, which makes a collision
refusal name two projects that say what they claim and gives entry-point discovery an
obvious key later.

→ Full record: [`adr/0052-plugin-names.md`](adr/0052-plugin-names.md)

### ADR-0056 — Dashboard layout follows stable, useful flow
*Supersedes ADR-0024 and restates its still-live dashboard decisions in full.*

**Q:** The stable-topology allocator kept roots from moving on status changes, but
visible node count, a 16-node entry price and one maximum branch factor did not say
which widths a nested tree could actually use. A two-track span could leave height
unchanged, `reason_cap: 30` was invisible to the weight, a chip at a mixed level
disabled its boxes' grid, and an 80-root poll repeated 32 complete plans. How can
the grid spend useful width without reading live pixels or reasons?

**A:** Keep ADR-0024's position rule and density surfaces, but derive a **stable flow
profile** for each root from the filtered, depth-limited topology, configured
`reason_cap`, the stylesheet's 330 px nested track and its per-level insets.
Every visible node is a potential reason host and its stable cost scales by
`ceil(reason_cap / 6)`. Current status, reasons, measured height
and chip/box painting never enter. Only a span that removes at least one modeled row
per added track becomes a useful step, so profiles may skip two or remain one for a
linear chain. Within each source-order row the currently tallest root with a
fitting next step wins — a row is as tall as its tallest card — with the better
reduction per track breaking height ties, atomically; a spare with no useful step
stays empty. Consecutive quiet chips share a full-row wrapper, retaining their
inline wrap while full boxes at the same mixed level can grid. Each span is priced
at the width it actually has, and a published band names the **track count** its
plan was priced for: the server publishes `(tenths, tracks, plan)` breakpoints in
integer tenths of a pixel — the model's own unit, so a band is never late against
a fractional measurement — and the browser sets the grid to exactly that many
equal tracks and selects the last applicable band from its measured width, scaled
by ten, after first paint, resize and poll swap — so the width where auto-fill
snaps every track back to its minimum no longer makes one more pixel of viewport
paint a taller page. No candidate may stretch a track wider than auto-fill itself
ever could (~676 px, one track just short of a second fitting), which rules out
the page-wide banner while leaving the moderate counts a dodge needs; the count a
band already holds is exempt from that floor, so a widening viewport never
disqualifies the plan holding the page. An incumbent band yields only to a
strictly better challenger, and `tracks 0` rides auto-fill for all-ones plans, so
a flat wall stays one band. The promise is the best **legal** outer choice at
every width, not a page that never grows: a card's own nested auto-fit can
re-chunk at a column flip no outer count can dodge. A structural test pins the model's five constants to
`overview.css`, the layout is memoized on the depth-limited tree shape, and
`settings.yaml` `dashboard_columns: plain` withholds the plan entirely. The
auto-fill CSS remains the fallback.

The full restatement also keeps bounded reason blocks and minimum heights, quiet
leaf chips, `branch_cap` folds that never hide warn/error boxes, the reserved
`/little-sister` status-band pill, maintenance pips plus the global pill and
`/maintenance` page, and reason-entry separators.

→ Full record: [`adr/0056-stable-useful-dashboard-flow.md`](adr/0056-stable-useful-dashboard-flow.md)

### ADR-0055 — Sibling order: alphabetical, unless somebody declares a rank
*Supersedes the* Node sibling ordering *entry above, restating its name sort in full.*

**Q:** Siblings sort by name at every level, which is right for the reason it was
chosen — order must be a property of the node set, never of registration order or of a
live status. But a **severity band set is inherently ordered**, and the name sort
destroys exactly that: `wiz` files `informational` between `high` and `low`, and
`github` puts `low` before `medium`, which is a wrong statement about severity. Can a
check say what its own children's order is without re-opening insertion order?

**A:** Sort by **`(order, name)`** — a declared rank first, then the same natural,
case-insensitive name order as before, once in the snapshot. `CheckResult` grows
`order: int = 0`, so **a check that says nothing gets exactly today's behaviour** and
cannot accidentally publish its loop: the rank is declared, never incidental. It is
read on the result **root** as well as its children, unlike `about` / `title`
(ADR-0025), because the check is what *knows* the order and a rank is not identity —
without that a leaf check could not rank the node it owns. `order:` is also readable
**inline on a check** and in `nodes.yaml`, both of which overrule the result, per field
and in that order. A stated **`0` is a real declaration** — the only way to overrule a
rank by naming the default value, which is why the node's field is nullable — but it is
**not** a request for alphabetical: `0` is the rank the unranked carry, so a zeroed node
sorts ahead of every positive rank, and putting a whole ranked set back to the alphabet
takes an `order: 0` per sibling. One consequence is named rather than left implicit: a
root rank is compared against **other checks'** cards, so an installed plugin can nudge
a wall's layout, and the deployment's answer is to state the order itself. Ordering by the live **grade** stays rejected (it
jumps on every poll), so ADR-0024's positional stability holds. The envelope's
`children` order moves with the snapshot and is accepted (ADR-0008); the rank as a
**field** waits for the client contract round rather than arriving piecemeal.

→ Full record: [`adr/0055-sibling-order.md`](adr/0055-sibling-order.md)

### ADR-0061 — Decoration cannot substitute for the thing it decorates
**Q:** ADR-0017 says a title that only repeats the node's name is not drawn. Most surfaces draw the name and the title side by side, so that is the whole
question there — but two draw the title **instead of** the name: `/copy`, which labels
an item with the title when there is one, and the inspection popover, whose card
carries `title` and `about` and no name at all. Both are right while a title is a word:
a node titled *Cluster A* is better named that way in a pasted document. Two plugins now
want a **glyph** as a severity band's title — 🔴 for `critical` — which is a clear win
on a chip, where the band's name sits beside it and carries the word. What should those
two surfaces do with it?

**A:** **A title with no letter and no digit in it cannot stand in for a name**, so it
is drawn **with** the name instead: `critical 🔴`, name first, in the chip's own order.
Otherwise `/copy` — the surface defined as *read somewhere with no chips and no
styling* — would paste a bare circle into a ticket that outlives the person who pasted
it, and a colour name is the one thing a reader cannot reconstruct from a colour. A
package cannot fix this from outside: raw HTML in a title is escaped (ADR-0018), so
`aria-hidden` and a `title=` attribute are both unavailable to a check. The predicate is
`isalnum` per character, which makes it a **Unicode** test on purpose — a Japanese,
Cyrillic or Greek title is a word and keeps every right a word has, while an emoji, an
arrow and a bullet are not; a digit counts, because deciding that `42` is not a name
would be a second decision hiding inside this one. The fold rule runs **first**, so a
title of `Critical` still simply disappears and only a wordless one reaches the new
case. `label_parts` returns the two halves rather than a joined string: a title is
authored Markdown and keeps that contract, a name is structural data that each surface
escapes its own way, so the decision is in one place and the drawing stays where it was.
Like ADR-0017's update this is **display only** — the snapshot keeps the title and the
JSON envelope keeps emitting it, because a client drawing its own chips is entitled to
its own decision about the glyph. Accepted with one wart: a card headed `critical 🔴`
repeats the chip beneath it, which is what a heading does, and the alternative would
have given one predicate two answers for a case no shipped band is.

→ Full record: [`adr/0061-decoration-is-not-a-label.md`](adr/0061-decoration-is-not-a-label.md)

### ADR-0062 — Navigation chrome is layout behavior, not a preference
**Q:** Keeping navigation reachable on a long page opens two choices that CSS cannot
make: does pinned chrome become another key in ADR-0029's presentation cookie, and
should a short window unpin it when the navigation is taller than the viewport?

**A:** **Pinning belongs to the interactive layouts and is not another preference.**
The viewer already chooses rail or top bar; keeping that chosen arrangement reachable
while its page scrolls is behavior of the layout, so the cookie and settings menu gain
no switch. A short window keeps the chrome pinned and scrolls only its constrained
child — rail, expanded section list, or settings dropdown — while the window remains
the document scroll container and kiosk stays untouched. CSS supplies safe no-script
geometry; `rail.js` refines both the rendered border box and the first row's viewport
budget. Content-anchored
reason editors slide behind the chrome; viewport-positioned maintenance and inspection
popovers stay above it.

→ Full record: [`adr/0062-navigation-chrome-is-layout-behavior.md`](adr/0062-navigation-chrome-is-layout-behavior.md)

### ADR-0060 — A line makes no claim; the node says it could not look
**Q:** `UNDEFINED` meant *nobody has reported this node yet*, and ADR-0042 then let a
check hand a line that same code **on purpose** — *this line makes no claim*. Two
different statements, one spelling, and the roll-up ignores both. So a check that read
one service to grade another could not tell the tree *I could not look* apart from *I
have nothing to report*: in the sharpest case a severity band rendered `OK` while
nothing at all had been read, because a watched band is `OK` when empty. Does the model
need a sixth code to tell chosen-unknown from not-yet-measured?

**A:** **No — two sentences on two different things.** The **line** keeps `UNDEFINED`
and makes no claim about its subject; the **node the check owns** says `WARN`, meaning
the instrument is degraded and this reading is incomplete. That is ADR-0058's
subject-versus-instrument split one layer up, and it costs no consumer, no envelope and
no client — where a sixth code would cost all of them, against a vocabulary closed on
purpose. `WARN` specifically, because an `UNDEFINED` **own** code is skipped in favor of
a node's children, which is exactly how a blind container came to defer to bands that
had nothing to say; a `WARN` is counted. This is ADR-0043's invariant reaching one case
further — an *unread* scope is not silently green either — and like it, a rule checks
are reviewed against rather than machinery core enforces. Two properties keep the line
from becoming noise: it counts the **could-not-ask** kind only (a refused subject
already grades on its own line), and it names coverage, never a subject. Alongside it,
**a read failure never replaces a last-known reading**: a node write rebinds the whole
entry set, so a check that could not read **omits** the node and ADR-0007's no-prune
rule leaves the previous entries and their timestamp together, with freshness left to
say honestly that they are old — which also settles a failed **discovery** (its own
coverage failure and nothing else; a failure the service *answered* stays `ERROR`).
Two narrow amendments to **ADR-0033** follow, each from a fact that record did not
have: the budget re-arms on **any change** of the stored code and not only on an `OK`,
because ADR-0042 made chronically non-`OK` ordinary and such a check spends its retries
once and never gets them back — invisibly, since `/system` marks only a pulled-in slot;
and a completed run reporting `UNDEFINED` **does not arm** the retry, a withheld claim
being nothing to confirm. Deliberately left: the age of a carried reading goes in the
line's own words, not into a per-reason stamp the envelope would have to carry.

→ Full record: [`adr/0060-a-line-makes-no-claim.md`](adr/0060-a-line-makes-no-claim.md)

### ADR-0058 — `little_sister.transport`: a vocabulary for asking something that might not answer
**Q:** Nothing on the check-authoring surface says what a check should do about a
request that fails, so every check that reads a remote API decides four things for
itself — how long one request may take, what bounds a run that asks fifty times, what
is worth asking again, and what a failure *means*. Offer a shared HTTP client? Take a
general HTTP library? Or something else?

**A:** Share the **policy**, never the client. `little_sister/transport.py` — stdlib
only, no I/O, importing nothing from `little_sister` — promises five names: `Deadline`
(with `budget(timeout)`, the clamp to what is left of the run that makes a deadline a
bound rather than a suggestion, and `affords(wait)`), `DeadlineExceeded` (deliberately
**not** a `RemoteError`, so a per-item handler cannot spell one run-level fact as forty
item-level lines), `Fault` (**three** states — *transient* / *answered* / *malformed* —
because a boolean spells a garbage payload identically to a `404`, and those grade
differently), `RemoteError` (status + fault, `fault` **required with no default**,
designed to be subclassed) and `ask` (one bounded retry whose backoff the deadline can
veto). A check builds the deadline from its own `timeout_seconds`, which also settles
what `timeout:` bounds — **the whole run**, one request at a time inside it. There is
deliberately **no** mapping from a `Fault` to a `StatusCode`: for an `http` check the
endpoint *is* the subject of the measurement, for a check reading an API to grade
something else it is the *instrument*, so the mapping is one line at the call site and
waits on the chosen-`UNDEFINED` question. A check whose transport is a vendor SDK
replaces the *implementation* and still wears the policy; a check-type package may take
`httpx` or `requests` where the library may not — and neither would help where it
counts, since neither has a total-request timeout. The SSH package's `transport.py`
becomes `connection.py` to free the name. For a service that answers *not now*,
`RemoteError` carries an optional `retry_after`, `ask` spends it in
place of its own backoff when the deadline affords it, and `fetch` parses the standard
`Retry-After` header — but there is **no fourth `Fault`**, because a throttle is already
transient and no status can identify one (both `403` and `429` are used for it, and a
bare `403` also means *not visible to this credential*), so only a package that speaks
the service's dialect can classify it. The principle underneath: **a check and an HTTP
request are different realms**, and this module serves the second — `Deadline` is the one
place they touch.

→ Full record: [`adr/0058-transport-policy-vocabulary.md`](adr/0058-transport-policy-vocabulary.md)

### ADR-0063 — A node may decline the density trade (`show_when_quiet`)
**Q:** The dense view compacts every quiet node the same way — a leaf to a chip, surplus
boxes behind *+N more* — and ADR-0056 names the cost honestly: a chip trades at-a-glance
quiet reason text for density. For most nodes quiet text is diagnostic and the trade is
free, but an inventory-shaped node (the `aws` check's `ec2` aspect: one line per instance
name, a count, the oldest age) is read *because* everything is fine — in dense view its
lines were visible only beside an error. A check can already say "my quiet lines are
noise" (`show_healthy: false` drops them at the source); where does the opposite claim —
*my quiet lines are the payload* — live: with the check, or with the viewer?

**A:** **With the node, as display metadata — the viewer keeps the mode, the node states
its nature, and the deployment's half is read by the library.** A new optional boolean,
`show_when_quiet`, rides the labels' lattice exactly: `nodes.yaml` per path
**>** the deployment's `subnodes:` block in the check's YAML **>** the type's declared
default — `show_when_quiet` beside `title` / `about` in the same `subnode_defaults`
entry, so a roster aspect is declared once where its label is — **>** the stamped value
on a child `CheckResult`, the dynamic-child channel, **>** unstated (inline on the root,
whose result copy is ignored), seed-once / fill-empty — and **tri-state**, so a stated
`false` occupies the field where a declared or stamped `true` cannot fill over it. The
`subnodes:` key is a **common
field**: `_parse_common` reads it for every type and the engine applies it per subnode
*name*, at any depth, so a deployment can declare it for **any installed branch check**
by editing its own YAML — no plugin release, and no reader on the check-authoring
surface, where a per-type call would have made support invisible (the first type to skip
it leaves the key parsing cleanly and doing nothing). The labels needed their defaults
declared as data first and follow by ADR-0025; the block's *shape*
is base-validated on every type, so a malformed one fails fast. In the dense view a
declared node is exempt the way warn/error already is: **never a chip, never a fold
candidate** — one exemption without the other would hide more than the chip did. It is
display metadata and nothing else: no event, no aggregation, no freshness; *hide idle*
still hides it, because that filter is the viewer explicitly asking for problems only; no
cookie key (ADR-0029's boundary — the cookie changes how the page looks, this changes what
a node shows); no envelope change (ADR-0008), a client drawing its own chips being
entitled to its own decision (ADR-0061). Position cannot move: chip-versus-box painting
was never a flow-profile input and the model already prices every node as a full box
(ADR-0056). Named for the claim, not the widget — `no_chip` would be one template's
condition riding in the tree, on the wrong side of the line that rejected a `wide:` hint
in `nodes.yaml`.

→ Full record: [`adr/0063-declining-the-density-trade.md`](adr/0063-declining-the-density-trade.md)

### ADR-0064 — A secret resolver is a registration like the others
**Q:** `secrets.register_resolver()` is one of the five seams a package reaches an
instance through, and is held to none of their rules: it records no registering
package, it is absent from `/system`, and a second claim on a scheme silently
replaces the first where a second `type:` claim refuses naming both. Which of those
is right, now that a package — not only a deployment — can claim a scheme?

**A:** **All three change; the seam becomes a registration in full.** A claim
records the package that made it, inferred from the call site as
`register_aspect`'s is, and the resolver travels *with* its provenance in one record
per scheme rather than beside it in a table that can disagree. A second claim from a
**different** package **refuses at startup** naming both and the scheme — ADR-0051's
rule for ADR-0051's reason, because a scheme says where a credential is read from
and import order must not decide it; the same package registering again replaces
silently, which is a reloading server re-running its own registrations. Replacing
somebody else's scheme stays available and is **said out loud** — `replace=True` —
which keeps ADR-0023's promise that a deployment may substitute its own `env`
implementation while stopping it from happening by accident; a deployment is not
structurally distinguishable from a package, so an inferred *"the deployment wins"*
would refuse the very case it exists to allow. What was replaced is remembered and
shown, being the one fact the outcome cannot reveal. `/system` prints the seam
twice: `secret <scheme>://` on each package's inventory row, and the **whole** scheme
list with its owners — built-in `env` included, unlike the aspects line — because the
schemes are additive and the full list is the only answer to what a config field may
say. `little_sister.secrets` is not on the check-authoring surface, so the epoch does
not move.

→ Full record: [`adr/0064-the-resolver-is-a-registration.md`](adr/0064-the-resolver-is-a-registration.md)

### ADR-0065 — The connection decides what is secure
**Q:** The session cookie carries a login and was never marked `Secure`, which was
right while every deployment served plain HTTP on a trusted network — a `Secure`
cookie there is set and never sent back, and the symptom is a login page that will
not stay logged in. A deployment now terminates TLS, and the next one will sit behind
a load balancer that opens its own TLS connection to the instance. Who decides whether
a request is secure?

**A:** **The transport, per request** — `request.is_secure`, which is
`wsgi.url_scheme`, which gunicorn sets from the socket it is holding. It is true
exactly when *this process* terminated a TLS connection, so one rule covers a laptop
and a load-balanced instance without knowing which it is in, and it cannot drift from
how the process was started because it is how the process was started. Not a
configuration value — Flask's `SESSION_COOKIE_SECURE` is a second copy of a fact the
process already has, and a deployment that sets it and starts without TLS locks the
operator out of its own login page with nothing in the log reading wrong. Not the host
name, which is `localhost` to one viewer and something else to the rest. Not a
forwarded header, which is a claim by a peer rather than a fact, and which gunicorn
already offers behind its own allowed-peer list for a deployment that really does have
a terminating proxy. **All three cookies** are marked by the one rule — the session,
the presentation preferences and the view switches — because a rule with an exception
is one somebody has to remember, and the next cookie added should inherit a flag rather
than an argument. A configured `True` still wins, so the transport can only ever *add*
the flag, and there is deliberately no switch that removes it from a TLS connection.
**No HSTS:** it is scoped to a host and ignores the port, so a header from
`localhost:8443` would make every other service on that machine unreachable in that
browser — a promise about a whole host name, which is a deployment's to make and not a
library's.

→ Full record: [`adr/0065-the-connection-decides-what-is-secure.md`](adr/0065-the-connection-decides-what-is-secure.md)

### ADR-0066 — `/health` answers liveness, and says almost nothing
**Q:** Nothing answers *is this process serving* in a form a machine can read — the
readiness probe aims at `/login`, a login page standing in for a liveness statement.
A load balancer is about to ask on a schedule, holding no credential of ours. What
should it be told?

**A:** **`200` while the process serves, whatever the engine is doing**, with the
engine's condition reported in the **body** and never in the status code. The two
questions come apart exactly where it matters: a check config that fails to load
deliberately leaves the application serving behind a red banner naming the reason
(ADR-0005), so a health check that answered "not well" there would have the balancer
remove the one page explaining why — a legible failure turned into an unreachable one.
The body is **two fields**: `status`, constant, the code restated for a caller that
reads bodies; and `engine`, from the closed vocabulary `running` / `disabled` /
`failed`. `disabled` and `failed` are both "no engine" and deliberately not one word —
a deployment that said `LITTLE_SISTER_ENGINE=0` got what it asked for, and reporting it
the same as a broken configuration is the confusion this application exists to remove.
**No login gate**, because a load balancer has no session and no token — and the bound
on an ungated route is that it says almost nothing: not the failure reason (a
`CheckError` names config files, and the banner carries it behind the login), not the
version (`/about` is auth-gated for exactly that reason), not the configuration. It is
**not part of the JSON API** — no token, no envelope, not in `openapi.yaml` — because
two contracts with different audiences should not be one merely because both return
JSON, and it is not the system-info endpoint either. `no-store`, since a cached health
answer is a lie with a delay on it. It also makes the set of routes that answer without
an identity **two**, where it has always been an accident of each route checking for
itself; that roster becomes explicit and closed when the identity seam lands.

→ Full record: [`adr/0066-health-answers-liveness-and-says-almost-nothing.md`](adr/0066-health-answers-liveness-and-says-almost-nothing.md)

### ADR-0067 — The run scripts can serve TLS, and never verify it
**Q:** `start.sh`, `stop.sh` and `test_api.sh` are how somebody who receives
little-sister runs it, and all three could only speak `http://`. How to change that had
been open for a long time: gunicorn or a proxy, self-signed or an internal authority,
where the pair comes from, and what a client does about trust.

**A:** **`--tls` on all three scripts** — per run rather than a committed setting,
which would make one person's choice everybody's default; `LITTLE_SISTER_TLS` beside it
for telling `stop.sh` or `test_api.sh` about an instance something else started. All
three take it, though for two reasons: `start.sh` and `test_api.sh` have to *speak* the
scheme, while `stop.sh` signals a pid and its flag is vestigial. **The port moves with the
scheme** — `TLS_PORT`, `8443`, beside `PORT` in `instance.sh` — because one number under
two schemes is an address wearing two costumes and a bookmark reaches for the wrong one.
**`TLS_CERT` / `TLS_KEY`, both or neither**, serve a certificate the installation
already has; with neither set `--tls` **mints a throwaway** — P-384, 200 days, into the
gitignored `var/tls/` under a `077` umask, **overwritten at the next start rather than
removed at boot**, because gunicorn rebuilds its SSL context per accepted connection and
reads both files each time. **The scripts never verify it**, and that is the decision
rather than a shortcut: each is talking to a process on this machine that it started
seconds ago and holds the pid of, so a certificate answers nothing that was in question,
while verification adds a way for a healthy instance to be reported as dead — measured,
with the same certificate trusted and untrusted. That is not an exception to
`little_sister.fetch`'s no-switch-off rule, which is about reading somebody else's
service. **Whether this machine trusts a supplied certificate is reported instead** —
one question after a successful start, and only for a supplied one, since a minted
certificate is unverifiable by construction. And `PROBE_PATH` now aims at `/health`
(ADR-0066) rather than at a login page standing in for one. **One checkout serves one
instance** — which the single pidfile and single log already asserted, and one-port
lookups quietly broke: the scripts now ask whether *somebody else* holds the port they
are about to bind of that port alone, and whether *this checkout is already serving* of
both, so a start replaces an instance on the other scheme's port instead of running
beside it and truncating its log, and a stop finds that instance instead of calling it
absent and deleting its pidfile. **Ours is a gunicorn whose working directory is this
checkout** — not the WSGI target two checkouts can share, and deliberately nothing in
the command line, which macOS `ps` truncates and which gunicorn rewrites outright under
`setproctitle`; nor the pidfile's contents, which these scripts delete themselves and
which name a pid that may since have been reused. `--any-instance` is the per-run way
past the resulting refusal, named in the refusal, and it reaches a gunicorn and nothing
else.

→ Full record: [`adr/0067-the-run-scripts-can-serve-tls.md`](adr/0067-the-run-scripts-can-serve-tls.md)

### ADR-0068 — The login gate refuses by default, and every route is classified
**Q:** *Who is this request* was `session['username']`, read in fourteen views —
thirteen opening with the same two lines and a fourteenth with its own variation. The
duplication is the obvious problem; the real one is that **nothing could say which
routes answer without an identity**, the answer being whichever views happened to
check. `/health` now answers a load balancer holding no credential on purpose, and an
identity provider supplied from outside will be able to send an unidentified request
anywhere — including that health check.

**A:** **One `before_request` hook, refusing by default.** The polarity is the decision
rather than the deduplication: a decorator each view opts into reads the same on the
page and fails the other way — forget it and the route is silently open. A route added
tomorrow is closed until its endpoint is put on a list, and that edit is where *should
this be open?* gets asked. **Two named lists, and the second exists so nobody misreads
the first**: `OPEN_ENDPOINTS` answer with no identity at all (the login form and its
stylesheet, logout, `/csp-report`, `/health`, and the two redirects that land somewhere
gated anyway), while `SELF_AUTHENTICATING_ENDPOINTS` holds `/status` alone — it
negotiates between a session and a bearer token (ADR-0008), so a gate in front would
redirect an API client to a login form. One list called "the ungated ones" would say
`/status` is open, and it is not. `identity.current_user()` returns an `Identity`
(`name`, `firstname`, `lastname`, `admin`) or `None`; `signed_in()` serves a view
already behind the gate and answers **401 rather than redirecting**, because nobody
there means a misclassified route, not a visitor who needs a form. `admin` is the only
role, because two is what the routes gate. Nothing a visitor sees changes, the existing
suite passes unchanged, and the seam this prepares has exactly one function to replace:
`challenge()`, called from one place. `little_sister.identity` is **not** on the
promised surface and the check API epoch does not move.

→ Full record: [`adr/0068-the-login-gate-refuses-by-default.md`](adr/0068-the-login-gate-refuses-by-default.md)

### ADR-0069 — Identity comes from outside, and never from a chain
**Q:** Behind the one gate and the one `current_user()` was still
`session['username']`, written by a form comparing a plaintext password against a
list in `config/users/users.yaml`. That list is right for the install this project
protects — one person, one machine, fifteen seconds, no services behind it — and it
is not a login system for a team. Two environments in front of us answer identity in
structurally different ways: an authorization-code redirect to Keycloak, where the
application performs a login; and a load balancer that has already completed the
whole exchange and injects a signed assertion into a header, where it performs none.
And whatever answers can stop answering, at the same moment everything else is going
wrong.

**A:** **Deciding who somebody is is not this library's job.** The primitive is *who
is this request* — `identify()` — with `challenge()` beside it and a login flow as
four **optional** hooks, so the header-verifying case implements two methods and
nothing else rather than being the awkward one. A deployment registers a provider in
the same import-before-app slot it already uses, and the built-in list is a provider
like any other — including in how it gets there: **an installation registers its own
doors, all of them**, `local_login.use_local()` for the built-in list like anything
else (§3). The library adds none on anybody's behalf, so
*can anybody log into this instance* is answered by reading one file rather than by
working out what the library would have inferred from what else was registered. That
call is the only reader of the `users` aspect, which is what lets a deployment with a
directory of its own carry no `users.yaml` at all.

**Several ways in are allowed; an ordered list of them to try is not.** Each provider
is a **door** with a name and a route of its own (`/login/<door>`,
`/auth/callback/<door>`, library-owned, so no general route seam is added and a
provider never brings a route). `sign_in()` records which door produced the session
and `current_user()` asks *that* provider and no other — the mechanism, not a
discouragement — so registration order can never decide who somebody is. That matters
more here than in most applications: a name is a **stored key** that maintenance pins
and event authorship are held against, and two directories that both know `michael`
cannot be told apart afterwards. Nobody who solved this made order load-bearing:
Kubernetes made it irrelevant, Grafana partitioned by credential kind, Keycloak moved
the choice in front of the application; Django, which did make order matter,
documents the ambiguity rather than solving it.

A door name is claimed once and exactly one door is the default — a second claim on
either **refuses at startup naming both**, as a duplicate `type:` name or secret
scheme does (ADR-0051, ADR-0064). Where a registration is merely *missing* the
application starts and says so instead: **a contradiction refuses, an omission
logs** (§2). No door at all, and doors with none of them the default,
are both a startup `WARNING` naming the line to add, on an instance that serves
`/health` and refuses every gated page with a `401` — refusing to start would take a
monitoring application down for a mistake it can describe, and would refuse the more
usable of the two, since doors without a default still admit anybody who knows
`/login/<door>`. **A default door can also stop being there and that is nobody's
omission** — §5 closes a door whose credential did not resolve — so `challenge()` sends
an unidentified request to `/login` where the installation asked for the chooser and any
door is registered, decided off the registry rather than by asking `enterable()`, which
a provider may answer by probing; without the chooser that address is the default door's
own step and answers `404`, so `401` remains honest and its message says which of the
two states it is in. A provider that raises is **no identity**: logged, never *let them through*, the
opposite of the contained slot filler next door (ADR-0034), because containment is
right for a decoration and wrong for a gate; a failing door takes down itself and no
other. `identify()` is answered once per request. `Identity` stays four fields with no
claims bag, and the JSON API's bearer tokens are untouched.

**One door the library ships and it is not a provider's:** a **system admin**, on a
door of its own that always renders a local form, so an operator can still get in on
the morning the identity provider is what broke. Its password is a *registration* —
`identity.use_system_admin(reference=…)` resolved once through ADR-0023, or the
discouraged `password=…`, each refusing the other's shape — never generated, compared
with `compare_digest`, and visible in use: a distinct avatar, a `WARNING` per login,
a row on `/system`. The built-in login page links to it while it can take a password
(§5) — which reaches the small install and, precisely, *not* the
redirecting one that mostly needs it, where `/login` renders nothing of ours. That half
is §1's other half: **`challenge()` and `login_page()` answer different
questions.** The challenge stays a straight redirect, because on an SSO install it is
*silent* and anything rendered there taxes every visit forever; `/login` may render a
**choice** of doors instead, costing nothing on the common path and — being served by
us — still answering when the identity provider does not. `identity.choose_at_login()`
is the installation's line and `/login/<door>` is untouched, which is what keeps the
page from linking back to itself; a redirecting provider adds a `login_page()`
returning its own redirect to appear on it. A door grows an optional `label=` for that
page to print, and an optional `enterable()` for *can this be entered right now* —
asked once, of the door, by both the chooser and the built-in page's link. A failed resolution closes that door and the application keeps
serving, because an unreachable parameter store must not take the dashboard down
during the kind of event it is watching. Every door is on `/system` — name, route,
provider, registering package, which is the default — since a way into an application
must not be knowable only by reading the source.

→ Full record: [`adr/0069-identity-comes-from-outside-and-one-account-does-not.md`](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)

### ADR-0070 — The report on unclaimed configuration files runs at the end of registration
**Q:** A deployment that registers a configuration aspect of its own is told at every
start that its own file is *not a known configuration aspect* — read correctly, working,
and reported as ignored. ADR-0035 §5 says to register before the app is imported, so why
does following that rule not help?

**A:** Because **the registering call is itself the first resolution**, and resolving a
root was what scanned it. Every registrar in this family declares its aspect and then
reads it immediately — so that a broken configuration file fails at startup rather than
at the first click — so whichever registration ran first performed the scan and every
aspect registered after it was named unknown for the life of the process. No ordering
fixes that, which makes the rule unfollowable rather than delicate; it is import order
deciding an observable, which ADR-0035 §4 already refuses for aspect shapes. So **the
scan stays and goes silent, and the complaint moves to the end of the registration
window**: `config_dir.announce_aspects()`, called once from the app import, the same
position and the same argument as `announce_doors()`
([ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)) — that
import is the moment the set of aspects is final. It is **public**, so a tool that never
builds an app can ask the same question; it covers **every configured root** rather than
only the resolved ones; and, being late, the message can name the known aspects **with
the packages that read them**, so a misspelled `identiy.yaml` points at the `identity` it
missed. ADR-0035 §5 stands on its true reason — the read, not the warning: `aspect_in`
looks the name up in `ASPECTS`, so an undeclared aspect is a `KeyError`. Reading the
aspects lazily in the plugins was the obvious move and fixes nothing: it removes one
trigger, leaves the mechanism, and trades away the startup failure the eager read exists
for.

→ Full record: [`adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md`](adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)
