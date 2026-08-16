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
repository to a package index. The core itself has finished that arc — it installs from
**PyPI** — and each extension travels it when it would have a second user. The core stays simple — every extension is opt-in, and a
plain internal install needs none of it.

**The name** is the inversion it sounds like. Big Brother watches *you*; little
sister watches *for* you — her eyes stay on the things her operators asked her to
watch, and she speaks up when one of them needs attention. That is the product
stance in one line, too: the surface is quiet by default, because silence is the
normal report. She tells it herself at the top of [`README.md`](../README.md),
and on a running instance's about page.

---

## 2. Domain concepts

### 2.1 Status
The central object. A `Status` represents the condition of one component or
system. It carries:

- `path` — its position in the tree as one **absolute, slash-separated** address
  (e.g. `/system/db`); `name` is not carried separately, it is the last segment
  of that path (`db`) ([ADR-0016](adr/0016-node-addressing.md)).
- `code` — a `StatusCode` (§2.2).
- `reason` — zero or more human-readable strings explaining the code (§2.7).
- `timestamp` — when the status was last **observed** (set by the check on each run).
  A node no check writes has **none** — unless exactly one check sits below it, whose
  run time it then reports; where two or more do, no single value could answer for
  them all, so there is no timestamp.
- `description` and `frequency` — inherited from the check that owns the node.
- `maintenance` — whether an admin has pinned the node (§2.6).
- `children` — child `Status` objects.

A status therefore forms a **tree**: a node may have children, each itself a full
status with its own children. A node grows no structured `links:` list of its own:
`about` and `description` are Markdown and carry their own links, and a check ships
its runbook through its own config ([ADR-0013](adr/0013-check-config-on-node.md),
[ADR-0025](adr/0025-check-provided-subnode-metadata.md)); curated *general* links
live on their own page ([ADR-0030](adr/0030-curated-links.md)), separate from the
tree.

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
rules are recorded in [ADR-0039](adr/0039-status-rollup-semantics.md):

- **Worst wins**: `ERROR > WARN > OK`; a node is `OK` only if every counted child
  is `OK`.
- **`UNDEFINED`** (a not-yet-reported leaf) is ignored when a parent accumulates.
- **`MAINTENANCE`** cancels its whole subtree and is ignored by its parent — so
  planned downtime never reddens the top. *Why* a node reads `MAINTENANCE` is a
  separate rule ([ADR-0041](adr/0041-maintenance-is-a-contribution-rule.md), §2.6);
  the roll-up only says what a parent does with one.
- **When nothing is counted, *why* decides**: a parent whose children were all
  silenced reads `MAINTENANCE`; one whose children have merely never reported
  stays `UNDEFINED`.
- A branch owner (e.g. a satellite check, §2.9) may stamp a node `ERROR` and drop
  its children, and must clear that when it can update the branch again.

There is exactly **one overall status** for the whole application, because the
status is a single tree: every check updates its own node, and the web UI reads
from that one tree.

### 2.4 System / subsystem
"System" and "subsystem" are not separate types — they are just `Status` nodes at
different depths. A "system" is a node; its "subsystems" are its children.
Aggregation lets a high-level system summarize everything beneath it.

### 2.5 Check
A **check** determines the status of one thing and writes the result into the
tree. A check **can do anything** — call an API, run a shell command, ping a
server — and reports a `StatusCode` plus, when not `OK`, a **reason**. A
failed or timed-out check becomes `ERROR` — the **engine** decides that, not the
check ([ADR-0040](adr/0040-what-a-failing-check-becomes.md)).

Each check is configured by a **YAML file** declaring `path`, `description` and
`frequency` — `name` is never declared, it is the last segment of the path (§2.1).
The built-in types are `http`, `file` (freshness / heartbeat), `command` (a script,
OK on exit 0) and an **SSH family** that reaches a host over the external `ssh`
binary ([ADR-0011](adr/0011-ssh-check-family.md)): `ssh-connect`, `ssh-command` and
`ssh-script` run something on the host, while `host-metrics` (basic system
parameters — disk, memory, CPU, load), `qnap-metrics` (QNAP hardware health —
temperatures and per-drive SMART) and `macos-memory` read one specific readout from
it. The current roster, with each type's options, is
[`architecture.md` §4.5](architecture.md). A check normally produces
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
  sticky override: it pins the node to `MAINTENANCE` (canceling its subtree) until
  an admin clears it, and it can be edited in place — extending a window keeps the
  explanation and never lets the node alarm in a gap. The explanation is authored
  Markdown: viewers see it rendered, and an explicit Edit action reveals its source.
  Its expiry can be entered as a relative duration or as a full/shortened future
  timestamp in the configured timezone; the form exposes the accepted formats beside
  the field.
- An admin can also silence **one reason** of a node instead of the whole node. A
  check that discovers many findings puts many of them under one node; an operator
  works on one at a time, and the other findings must keep alarming while they do.
  A silenced reason stays visible, says who silenced it, and the node says how many
  of its reasons are quiet. Its pin is editable in place under the same rule as a
  whole-node pin.

Durable storage and retention of this history is a later concern.

### 2.7 Reason
Free-text explanation(s) attached to a status (e.g. "HTTP 503 from /health"). A
status that is **not `OK` must carry a reason**; an `OK` status may also carry one,
read there as an informational note rather than a problem.

A reason is **addressable**, so an admin can act on one of them (§2.6). Where a
check's reasons are independent things it discovered — findings, waiting pull
requests, jobs — it says so, and each becomes separately suppressible. Where they
are one condition told in several paragraphs — a failure message and its stack
trace — they are not: the unit of suppression stays the node.

### 2.8 The monitoring engine
The **engine** is the background runner that drives the checks: it discovers them,
schedules each to run at its own `frequency` on background threads, and writes each
result into the single shared status tree in a thread-safe way (many checks run
concurrently against one tree). Each run is logged. *(How this is realized —
process model, thread pool, locking — is in `architecture.md` and ADR-0001/0002.)*

### 2.9 JSON output & satellite instances (federation)
Two related capabilities — the first shipped, the second still planned:

- **JSON output (backend mode) — shipped.** The web app serves the status tree (or
  a branch by `path`) as **JSON** via content negotiation, so other apps can use
  little-sister as a backend — the motivating client is a native **macOS Swift**
  app querying an instance on another machine, and it consumes it today. Access
  uses a **bearer token**, and the surface is **read-only**: it is a published,
  versioned contract ([ADR-0008](adr/0008-json-output-api.md); the OpenAPI
  document is [`api/openapi.yaml`](api/openapi.yaml)). Write **actions** over the
  API remain future work.
- **Satellites (federation) — planned.** An instance can act as a **satellite** that
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
  grid of system cards. Each system and subsystem is a box color-coded by its
  rolled-up status and nested inside its parent, with reasons. To make the
  **culprit** obvious, healthy branches and boxes that are merely colored by a
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
- **About** (`/about`) — who this is, why it is called that, and the version of the
  instance in front of you.
- **System** (`/system`, admin) — engine uptime, worker-pool size, check counts,
  and per-check next-run.
- **Copy** — a compact non-OK outline with the minimum ancestor chain, copied as
  Markdown for chat or rich text for a ticket.
- **Links** — a curated set of runbook/dashboard links.
- **JSON / backend mode** (§2.9) — the same status routes answer with JSON to a
  token-bearing client, read-only; **satellite federation** on top of it is planned.

Visual style is Bootstrap 5; status colors are green/ok, amber/warn, red/error,
blue/maintenance, gray/undefined. Displayed timestamps use a configurable timezone
(`config/settings.yaml`, default `Europe/Berlin`). **How** a viewer sees all this is theirs
to choose: a **theme** (including one that follows the operating system) and a
**layout** — a left rail, the older top bar, or a **kiosk** line for an unattended
wall display. The choice is presentation only and is remembered per browser.

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
