# Little Sister — Product Specification

This is the product specification: the domain concepts, principles, and
non-goals. It describes *what* little-sister is, not how the code is built
(`architecture.md`). Significant design choices are recorded in
[`decisions.md`](decisions.md).

---

## 1. What Little Sister is

Little Sister is a small **monitoring application**. It periodically runs a set
of **checks** against a number of systems, aggregates their results into a single
**status tree**, and presents that tree — the current state and its changes over
time — through a web interface.

The shape of it is three steps:

1. **Collect** — run **checks** on configurable, per-check intervals using
   background threads.
2. **Aggregate** — every check writes its result into **one shared status tree**;
   a parent's status rolls up from its children.
3. **Present** — a **web interface** shows that tree (the whole thing, its top
   branches, or a selected branch) plus the history of changes.

It is a plain **Python application** — in principle it runs anywhere Python does, not
only macOS — though for now it is still run only on macOS. A check reaches whatever the
host and its network allow: Linux machines, remote servers, and the Apple ecosystem (for
example a Mac over SSH).

little-sister is deliberately a small **core** that a **deployment extends**, not a
monolith. The core ships the engine, the built-in check types and the web / JSON
surfaces; a deployment adds its own **checks** and — where it must meet its own
environment — swaps the pieces that touch it (**authorization**, **secret storage**, and
where **maintenance settings** are kept) through narrow seams, leaving the core
untouched. A deployment's private checks live in their **own repository** that consumes
the core as a library, and such extensions (e.g. AWS, Keycloak or GitHub integrations)
can grow into **installable packages**; distribution follows the same arc, from a git
repository toward **PyPI**. The core stays simple — every extension is opt-in, and a
plain internal install needs none of it.

---

## 2. Domain concepts

### 2.1 Status
The central object. A `Status` represents the condition of one component or
system. It carries:

- `path` + `name` — its position in a dotted hierarchy (e.g. `system.db`).
- `code` — a `StatusCode` (§2.2).
- `reason` — zero or more human-readable strings explaining the code (§2.7).
- `timestamp` — when the status was last **observed** (set by the check on each run).
- `description` and `frequency` — inherited from the check that owns the node.
- `maintenance` — whether an admin has pinned the node (§2.6).
- `children` — child `Status` objects.

A status therefore forms a **tree**: a node may have children, each itself a full
status with its own children. (Which further attributes a node carries — e.g.
curated links — is open.)

### 2.2 StatusCode

| Code | Meaning |
|------|---------|
| `OK` | Healthy / nominal ("green"). |
| `WARN` | Degraded but functioning; needs attention. |
| `ERROR` | Failing. |
| `MAINTENANCE` | Intentionally offline / under maintenance. |
| `UNDEFINED` | Not yet known / not reported (the default). |

### 2.3 Aggregation (roll-up)
A parent's effective status is derived from its own code and its children's. The
rules are recorded in [ADR-0004](adr/0004-status-aggregation-semantics.md):

- **Worst wins**: `ERROR > WARN > OK`; a node is `OK` only if every counted child
  is `OK`.
- **`UNDEFINED`** (a not-yet-reported leaf) is ignored when a parent accumulates.
- **`MAINTENANCE`** cancels its whole subtree and is ignored by its parent — so
  planned downtime never reddens the top.
- A branch owner (e.g. a satellite check, §2.9) may stamp a node `ERROR` and drop
  its children, and must clear that when it can update the branch again.

There is exactly **one overall status** for the whole application, because the
status is a single tree: every check updates its own node, and the web UI reads
from that one tree.

### 2.4 System / subsystem
"System" and "subsystem" are not separate types — they are just `Status` nodes at
different depths. A "system" is a node; its "subsystems" are its children.
Aggregation lets a high-level system summarise everything beneath it.

### 2.5 Check
A **check** determines the status of one thing and writes the result into the
tree. A check **can do anything** — call an API, run a shell command, ping a
server — and reports a `StatusCode` plus, when not `OK`, a **reason**. A
failed or timed-out check becomes `ERROR`.

Each check is configured by a **YAML file** declaring `path`, `name`,
`description` and `frequency`; the built-in types are `http`, `file` (freshness /
heartbeat), `command` (a script, OK on exit 0), `ssh` (basic system parameters —
disk, memory, CPU, load — read from a host over SSH) and `qnap` (QNAP hardware
health — temperatures and per-drive SMART — over SSH). A check normally produces
one leaf node, but may produce a whole **branch** (a node with children — the
`host-metrics` check reports one per host, and satellite checks graft a remote subtree,
§2.9). A deployment composes its checks from one or
more directories — a shared base plus host-specific additions
([ADR-0015](adr/0015-check-discovery-union.md)).

### 2.6 Events, status history & maintenance
Besides the current status, little-sister records **status changes**:

- An **event** is recorded whenever a node's code transitions (e.g. `OK → ERROR`),
  forming an **event log** across all checks.
- A node's **status history** is the sequence of status periods it has held
  (status, since, until, reason).
- An **admin** can put a node into **maintenance** with a reason. Maintenance is a
  sticky override: it pins the node to `MAINTENANCE` (cancelling its subtree) until
  an admin clears it.

Durable storage and retention of this history is a later concern.

### 2.7 Reason
Free-text explanation(s) attached to a status (e.g. "HTTP 503 from /health"). A
status that is **not `OK` must carry a reason**; an `OK` status may also carry one,
read there as an informational note rather than a problem.

### 2.8 The monitoring engine
The **engine** is the background runner that drives the checks: it discovers them,
schedules each to run at its own `frequency` on background threads, and writes each
result into the single shared status tree in a thread-safe way (many checks run
concurrently against one tree). Each run is logged. *(How this is realised —
process model, thread pool, locking — is in `architecture.md` and ADR-0001/0002.)*

### 2.9 JSON output & satellite instances (federation)
Two related capabilities (planned):

- **JSON output (backend mode).** The web app serves the status tree (or a branch
  by `path`) as **JSON** via content negotiation, so other apps can use
  little-sister as a backend — the motivating client is a native **macOS Swift**
  app querying an instance on another machine. API access uses a **token / API
  key** and may include actions, not just reads.
- **Satellites (federation).** An instance can act as a **satellite** that
  publishes its status as JSON; a central instance runs a **satellite check** that
  fetches that JSON and **grafts the returned branch** into its own tree. Because
  status is already a tree, the **JSON output format *is* the federation
  protocol**. The remote is configured by URL + token (referenced from `.env` by
  name); an unreachable satellite's branch becomes `ERROR`; cycles are forbidden
  by configuration but not checked.

---

## 3. Product surfaces (web interface)

The app is gated behind a small user list (login/logout) and offers:

- **Status dashboard** (`/status`, `/status/<branch>`) — the live status tree as a
  grid of system cards. Each system and subsystem is a box colour-coded by its
  rolled-up status and nested inside its parent, with reasons. To make the
  **culprit** obvious, healthy branches and boxes that are merely coloured by a
  child (a *derived* status) are **dimmed**, leaving the node that actually reports
  the problem bold. Nodes drill down to a branch or a single check; **hide-ok /
  hide-idle** filters narrow the view and an adjustable **depth** controls how much
  of the tree expands — from a single overall light down to the full tree
  (remembered per viewer). The dashboard
  keeps itself current (it refreshes periodically and flags when it can't), and
  shows a **stale** status — one not verified within its expected interval — as
  degraded, so green always means freshly checked. The engine even reports its own
  liveness as a node, so a dead monitor is visible too.
- **Check detail** (a leaf) — its description, current status and reason, the time
  interval the current status has held, the heartbeat interval, and a link to its
  history. An admin can set/clear **maintenance** here.
- **Status history** (`/history/<path>`) — a node's status periods over time.
- **Events** (`/events`) — the transition log across all checks, newest first.
- **System** (`/system`, admin) — engine uptime, worker-pool size, check counts,
  and per-check next-run.
- **Text** and **Links** — a clipboard-friendly plain-text rendering, and a
  curated set of runbook/dashboard links. *(Planned.)*
- **JSON / backend mode** and **satellite federation** (§2.9) — planned.

Visual style is Bootstrap 5; status colours are green/ok, amber/warn, red/error,
blue/maintenance, grey/undefined. Displayed timestamps use a configurable timezone
(`config.yaml`, default `Europe/Berlin`).

**Roles:** there are **viewer** and **admin** roles; some actions (notably setting
maintenance) are admin-only.

---

## 4. Principles

The engineering principles the code follows — boring over clever, small reviewable
diffs, phase discipline, stable public APIs, and a green `ruff` + `mypy` + `pytest`
gate — are held to throughout the codebase. The
*product* principles are embodied in this spec: a single overall status (§2.3),
**status, not telemetry**, and **internal-only** deployment (§5).

---

## 5. Scope & non-goals

The **core stays small and simple** — that principle is unchanged. What were once flat
non-goals now read better as the line between the core and its opt-in extensions (§1):
the core carries only what every install needs; anything heavier is added by a
deployment, never baked in.

- **Status, not telemetry.** The core surfaces **status** — it is not a metrics / APM
  platform, and a default install shows status and nothing more. (A deployment may of
  course add checks that read from anywhere.)
- **A small core, extended — not a monolith.** Extensibility is now a goal, but the
  *core* stays lean: few dependencies, boring code. Heavier machinery (cloud SDKs,
  Keycloak, S3) rides in **extensions / plugin packages**, so it never weighs down a
  simple install.
- **Local-first, not internal-only by rule.** The default deployment runs **locally on
  an internal network** and needs no reverse proxy, TLS or SSO — and that stays the
  simple path. These are no longer hard exclusions, though: the auth and secret seams
  (§1) are meant to open the door to **SSO (Keycloak)** and cloud **secret stores**, and
  later to wider hosting — as extensions, not core changes.
- **Not a heavy alerting pipeline** (routing, escalation, on-call schedules) — *simple*
  notification on a transition stays a possible future direction, just not a
  current focus.
