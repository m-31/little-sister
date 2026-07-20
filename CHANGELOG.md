# Changelog

All notable changes to little-sister, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/); releases are cut with the release
pipeline (see [`docs/create_a_release.md`](docs/create_a_release.md)), which rolls
the **[Unreleased]** notes below into the tagged version. The JSON API
contract versions **separately** — see `docs/api/openapi.yaml` `info.version`.

## [Unreleased]

## [0.2.2] - 2026-07-20

### Added

- **The dashboard holds its shape under stress**: a card's **quiet
  leaves** (OK or idle) collapse to compact name+colour **chips**, so an all-green
  host converges toward a wrapping chip row instead of a stack of boxes — a
  warn/error leaf keeps its full box and reason, and a chip's own reason is a click
  away on its leaf page. Card heights are bounded (the reason caps above, a
  `min-height` floor below), and the always-tiny `little-sister` heartbeat moves out
  of the grid into a compact **status-strip pill** under the "updated …" line —
  a side note, not a summary banner — whose hover card explains the heartbeat
  by default (a `nodes.yaml` `about` overrides it). Card
  **positions stay a function of the node set** (no packing layout), so the everyday
  grid stops looking ragged without anything jumping on a status change. The
  `/little-sister` line is **reserved** — a custom check owning nodes there is
  rejected at load: the one-line strip must never hide a subtree, and the engine
  keeps the namespace for children of its own (should it ever grow some, the
  heartbeat falls back into the grid as a card). A heartbeat `title`/`about` from
  `nodes.yaml` feeds the strip and its hover card like any node's, without the
  orphan warning. HTML/CSS plus that load-time guard; the snapshot and JSON
  envelope are unchanged.
- **Dashboard reason overflow is capped**: a card shows at most six reason entries
  and clamps a tall reason block (a long `code()` trace) to about eight lines, with
  a per-node **"show all (N)"** that expands it in place and survives the ~10s
  fragment swap; every entry stays in the DOM (trimmed by entry and by CSS, never
  mid-HTML), and the leaf detail page and the JSON envelope stay complete. Reins in
  the unbounded card growth that made the grid ragged.
- **Engine-start failures reach the dashboard**: when the checks configuration
  fails to load, every page carries a persistent red banner with the reason
  ("Engine not started — …") instead of a blank, quietly-empty overview with the
  explanation only in the log. Covers the failed-start (`CheckError`) path; a
  deliberate `LITTLE_SISTER_ENGINE=0` disable shows no banner, and the
  standalone login page never shows the reason.
- **A fuller `/system` check table**: a **Type** column (two checks sharing a
  root node stay distinguishable), and three schedule columns each shown as a
  time of day plus an interval — **Running** (the in-flight run's start and
  elapsed so far; "queued" while it waits for a worker), **Next run** (the
  armed slot, shown even while a run is in flight — it replaces the old
  "running" placeholder), and **Last run** (the last completed run's start and
  wall time; a check that raised or timed out shows its full wait; a
  secret-pinned check, which never runs, shows "—").
- A guide to previewing the web UI against synthetic extremes,
  [`docs/testing-the-gui.md`](docs/testing-the-gui.md): a static fixture sheet
  rendered through the real templates (extreme trees, side by side) and a live
  demo tree replaying scripted scenarios — both dev-only, under `tests/`;
  nothing enters the package.

- **`/system` refreshes itself**: the system page carries the same server-seeded
  "updated …" stamp as the dashboard (so it always says from when its
  information is) and re-fetches its info block every ~10 s through the shared
  poll (`static/js/poll.js`), flagging failures the same way.
- **A sustained outage escalates**: the freshness line no longer treats a
  10-second blip and an hour-long outage alike. After ~1 minute of failed polls
  the dashboard and system pages show the outage age ("could not refresh for
  14 min — last ok …"), raise a red banner naming when the frozen data is from,
  dim that content, and prefix the tab title with "(stale) " — all reset by the
  first successful poll. A re-focused or woken tab re-polls immediately instead
  of waiting out the interval, and an expired session gets its own
  "Session expired — reload to log in" banner right away.

### Changed

- **Check schedules spread out**: after the immediate first sweep, each check
  settles onto a stable personal phase (within `min(frequency, 60 s)`, derived
  from its path and type) instead of every equal-frequency check firing in the
  same second forever — no more synchronized SSH bursts onto the worker pool
  and the monitored hosts, and a host carrying two checks is no longer hit by
  both at once. Visible on `/system`'s next-run column.
- The dashboard's freshness stamp is **server-seeded**: the page renders its own
  generation time into the "updated …" line (previously a "live" placeholder
  until the first successful poll), so a dashboard that never reaches the server
  again reports *"could not refresh — last ok \<page render time\>"* instead of
  *"last ok never"*.

### Fixed

- An expired session can no longer let the poll inject the login page into the
  dashboard grid: a fragment response without the `X-Rendered-At` header counts
  as a failed poll (shown red) instead of being swapped in.
- The freshness line's failure state now actually renders **red**: the stamp
  kept its muted styling class alongside the danger class and Bootstrap's
  cascade let muted win, so a dead server showed a grey "could not refresh —
  last ok …" line. The poll now swaps the classes instead of stacking them.

## [0.2.1] - 2026-07-19

### Added

- **Secret references** ([ADR-0023](docs/adr/0023-secret-references.md)): a check
  credential in YAML names its source — a bare environment-variable name (the
  unchanged default, fed by `.env`) or a `scheme://address` reference resolved by
  a resolver the deployment registers in code
  (`little_sister.secrets.register_resolver`). Secrets resolve **once, at check
  construction**, never during runs; a reference that cannot be resolved pins
  just that check to a visible ERROR ("secret unresolvable: …") instead of
  stopping the engine.
- The application settings `SECRET_KEY` and `LITTLE_SISTER_API_TOKENS` may now
  themselves be **secret references** (`scheme://address`), resolved once at
  startup through the deployment's registered resolvers — one step closer to
  running without any `.env` file. An unresolvable reference degrades safely
  (random session key / no API tokens, loudly logged); a malformed one fails
  startup.
- A developer guide for building custom check types,
  [`docs/implementing-checks.md`](docs/implementing-checks.md) — the `Check`
  contract, branch results, registration and startup wiring, secret references,
  testing.

### Fixed

- The dashboard's live-refresh line ("updated …" / "could not refresh — last
  ok …") now renders its timestamp with the configured `time_format` and
  timezone (`config.yaml`), matching every other displayed time. It previously
  used the browser's locale, so a 24-hour deployment saw a 12-hour "AM/PM"
  clock in that one spot.
- Distribute a `py.typed` marker (PEP 561) so downstream projects can
  type-check against little-sister. Without it, type checkers treated the
  installed package as untyped and reported missing type information for
  `little_sister` imports.

### Security

- Without `SECRET_KEY`, little-sister now generates a **random session key at
  each start** instead of falling back to a fixed, insecure development key.
  Sessions (logins) reset on a restart unless an explicit key is configured.

## [0.2.0] - 2026-07-15

First release. little-sister is a small, self-hosted status dashboard:
configurable **checks** run on background threads in a single process, their
results aggregate into one **status tree**, and the tree is served as a web
dashboard and a read-only **JSON API**.

- **Checks:** `http`, `file`, `command`, and an SSH family — `ssh-connect`,
  `ssh-command`, `ssh-script`, `host-metrics`, `qnap-metrics` — with
  per-userland metrics scripts (Linux, macOS, busybox) shipped as package
  data; example configs in `checks/examples/`.
- **Status semantics:** worst-of roll-up with `MAINTENANCE` and `UNDEFINED`
  handling, freshness (an unobserved node degrades to WARN), engine
  self-monitoring, node metadata (`about`, `title`, `config` — Markdown),
  an event log and per-node history.
- **Web UI:** dashboard with drill-down and breadcrumbs, node detail pages,
  admin **maintenance** windows (always with an expiry), and a system page;
  session login with viewer/admin roles.
- **JSON API:** content negotiation on `GET /status[/<path>]`, named
  per-client bearer tokens, Problem-JSON errors; the normative contract is
  `docs/api/openapi.yaml` (OpenAPI 3.1) — this release serves **contract
  version 1.1.0** (envelope `schema_version: 1`).
- **Packaged as a library**, consumed by a separate deployment repository
  that holds the real checks, users and secrets; configuration and secrets
  come from the working directory and a git-ignored `.env`.

A native macOS menu-bar client lives in its own repository,
[little-sister-app](https://github.com/m-31/little-sister-app), and consumes
the JSON API.
