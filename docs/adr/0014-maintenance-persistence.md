# ADR-0014 — Persist maintenance to a file, with auto-expiry

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (one process, in
  memory), [ADR-0002](0002-rlock-snapshot-synchronization.md) (the tree owns state),
  [ADR-0003](0003-config-and-secrets-via-env-file.md) (config / secrets in files),
  [ADR-0006](0006-config-file-and-timezones.md) (`config.yaml`),
  [ADR-0015](0015-check-discovery-union.md) (the static check set the reaper keys
  off), [ADR-0008](0008-json-output-api.md) (JSON envelope, unchanged here).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Maintenance (`project.md` §2.6) is a sticky admin override held **only in memory**
(`Status.maintenance` plus the tree's state). A restart loses it — the node reverts
to `UNDEFINED` and the next check can redden a system that is still intentionally
down. And maintenance currently **never ends**, so a forgotten or orphaned pin
lingers. Full durable persistence is deferred to Phase 7; maintenance needs a
restart-survival answer **sooner**, without pulling that decision forward.

## Decision
Persist maintenance to a small JSON file and restore it on startup; bound every
entry with an expiry.

1. **A maintenance side-table in the tree.** `StatusTree` owns
   `dict[path → entry]`, where an entry is `{reason, set_at, expires_at, set_by}`;
   `Status.maintenance` stays the in-tree bool that drives roll-up
   ([ADR-0004](0004-status-aggregation-semantics.md)) and the `upsert` guard.
   `set_maintenance` / `clear_maintenance` are the single choke points that keep the
   two in sync.
2. **Write-through JSON at `var/maintenance.json`.** Every set / clear / expiry /
   reap rewrites the whole file **atomically** (temp + `os.replace`); the file is
   exactly the side-table serialized. It is runtime state the app writes (not
   hand-authored config), so the path is **fixed** (not env-overridable) and
   git-ignored. A failed write logs and keeps the in-memory state for the session —
   there is **no flush-on-shutdown**, so a crash right after a set never loses it.
3. **Restore post-fork, before the engine starts** (single worker,
   [ADR-0001](0001-in-process-threaded-engine.md), so once). Replay each non-expired
   entry via `set_maintenance` — which auto-creates the node, so replay before any
   check has run is safe (`upsert` respects the flag). Already-expired entries are
   dropped and the file rewritten once.
4. **Auto-expiry.** Setting maintenance applies a **default duration** — one week,
   configurable in `config.yaml` ([ADR-0006](0006-config-file-and-timezones.md)) —
   unless an explicit duration is given (`parse_duration`: `2h`, `3d`, …). **No
   indefinite.** The scheduler ([ADR-0001](0001-in-process-threaded-engine.md))
   sweeps each tick and clears entries past `expires_at` via `clear_maintenance` — a
   real `MAINTENANCE → UNDEFINED` transition and event — and the next check refills
   the node.
5. **Orphan reaping at startup, by static check-root coverage.** After loading the
   checks and restoring the file, drop any maintenance entry whose path **no
   configured check covers.** A check at `full_path` *Q* **covers** path *P* when the
   two lie on the same root-to-leaf line, compared **segment-wise**: `P == Q`, *P* is
   an ancestor of *Q*, or *Q* is an ancestor of *P*. This keys off the **statically
   known check roots**, not the nodes a run happens to produce — so it is decidable
   immediately and is unaffected by a branch check that emitted only its root this
   run. The check set is fixed for the process (no live reload,
   [ADR-0015](0015-check-discovery-union.md)), so once at startup suffices; expiry is
   the guaranteed backstop.

## Consequences
- Maintenance survives restarts; an intentionally-down system stays blue across a
  deploy.
- Nothing pins forever: expiry bounds forgotten and orphaned entries, and the sweep
  emits proper events so history stays honest.
- **Coverage keeps the legitimate cases.** A container / subsystem pin (use-case #3,
  `payments`) is covered because a check root sits *beneath* it; a branch-leaf pin
  (`system.alpha.disk`) is covered because the `host-metrics` root sits *above* it —
  even when the host is unreachable and that run wrote no `disk` leaf. Only a path
  with no check anywhere on its line (a removed check) is reaped.
- `set_maintenance` gains `expires_at` / `set_by`; the maintenance form gains an
  optional duration; the detail page shows "set by X, expires …".
- Crash-safe: write-through at mutation time means a `kill -9` never loses a just-set
  pin.
- The persisted record is a small contract; Phase 7's durable store subsumes this
  file — the side-table is the seam.
- The JSON envelope ([ADR-0008](0008-json-output-api.md)) is **not** changed here;
  whether `maintenance_expires_at` joins it is the Phase 2 API item.

## Alternatives considered
- **Wait for the Phase 7 store.** Rejected: restart-survival and an expiry are wanted
  now and don't need the store's open choices settled.
- **Expire at render / snapshot time** (compute "expired" like staleness). Rejected:
  it desyncs the in-memory flag from the file and emits no transition event; a read
  shouldn't mutate.
- **Reap by observed nodes after a full cycle.** Rejected: a branch check that is
  unreachable on that cycle writes only its root, so its leaves don't exist yet — a
  legitimate pin on such a leaf would be wrongly reaped, and node existence isn't
  decidable on any single cycle. Static check-root coverage sidesteps the timing
  entirely.
- **Reap by exact check-path equality.** Rejected: a container / subsystem path is
  never a check `full_path`, so equality wrongly reaps legitimate subsystem
  maintenance (use-case #3).
- **No reaping; rely on expiry alone.** A valid simplification (≤ one-week bound);
  startup coverage is kept because it clears a removed check's pin promptly instead
  of waiting out the week.
- **Default to no expiry / allow indefinite.** Rejected for now: indefinite
  reintroduces the "stays forever" orphan; a generous default (one week) bounds it
  without cutting real windows short, and an admin can extend explicitly.
