# ADR-0015 — Check discovery: a union of config directories

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (one process),
  [ADR-0014](0014-maintenance-persistence.md) (the immutable check set the reaper
  relies on). Satellite federation (`project.md` §2.9) is the multi-site mechanism
  this defers layering to.
- **Register:** [`../decisions.md`](../decisions.md)

## Context
`load_checks` reads **one** directory of YAML (default `checks/`, env
`LITTLE_SISTER_CHECKS_DIR`); each deployment points the env at its own directory, so
the package is already separate from a host's check set. Two
things were open: **confirm** the single-directory layout, and whether configs should
**reload without a restart**. The pain with one flat directory is **duplication**
when several hosts share a common base of checks.

## Decision
Keep per-deployment directories, selected **explicitly** by env; extend the env to a
**list** and load the **union**; apply config at **startup** only.

1. **Union of directories.** `LITTLE_SISTER_CHECKS_DIR` accepts a path-list (e.g.
   `base:hosts/alpha`); every `*.yaml` / `*.yml` across all of them loads. A
   **shared base plus host-specific additions** without copy-paste.
2. **Overlapping ownership is a hard error.** A check is **asked which nodes it
   writes** — `owned_nodes()`, the set of node paths it gives a definite status to,
   each read as the subtree it owns. A leaf check owns `{full_path}`; a **branch**
   check owns its **child** subtrees and **not** the shared container — `host-metrics`
   → `{<host>.ssh, <host>.disk, <host>.memory, <host>.cpu, <host>.load}`,
   `qnap-metrics` → `{<host>.temperature, <host>.smart}` — so the two coexist on one
   host node (`architecture.md` §4.5). At load the union's owned sets are checked for
   **overlap** (segment-wise: equal, or one an ancestor of the other) and the load is
   **rejected loudly**, naming the path and the offending files. Disjoint owners share
   freely (the metrics pair; a `file` heartbeat as a sibling child); no last-wins, no
   merge.
3. **Explicit selection, no magic.** Which directories a deployment loads is set by
   its env; there is **no hostname auto-detection**.
4. **Startup-only.** The check set is **immutable for the process**; a **restart**
   re-reads config. No live reload.

## Consequences
- DRY across hosts that share checks, while the union stays trivial to reason about
  (no override semantics to trace).
- Asking each check for its `owned_nodes()` rests on a tree invariant: a **branch**
  check returns an `UNDEFINED` root and owns only its child subtrees, so the shared
  container is owned by no one and rolls up — `host-metrics` + `qnap-metrics` don't
  clobber, while two of the same branch (identical child sets), or a leaf placed on
  the container (an ancestor of its children), overlap and are caught. The subtree
  comparison even encodes §4.5's "sit beside" rule: a heartbeat must be a **sibling
  child** (`<host>.backup`), not the container's own status. A future **satellite**
  owns its whole graft subtree (it stamps `ERROR` on failure), so two satellites — or
  a satellite and any check beneath it — correctly error.
- `owned_nodes()` must match what `run()` actually writes. `qnap-metrics` declares
  `{temperature, smart}` and **no `ssh`** leaf — it leaves the transport leaf and the
  non-PQ warning to `host-metrics` / `ssh-connect` — so the metrics pair stays
  disjoint, but a check pointed at a node host-metrics owns (e.g. a second writer of
  `<host>.ssh`) correctly errors. A test that runs each check against a captured
  fixture and asserts its produced nodes fall within its declared set guards the
  declaration from drifting.
- The immutable-per-process set keeps the engine simple and lets the maintenance
  reaper ([ADR-0014](0014-maintenance-persistence.md)) reconcile **once at startup**
  against a fixed set of check roots.
- A restart loses the in-memory event log / history until Phase 7 durability;
  acceptable for an internal, single-process app, and config edits are
  deliberate.
- Resolves the open check-layout question.
- **Deferred (see alternatives):** override-layering and live reload. The genuine
  multi-site story is **satellite federation** (`project.md` §2.9, Phase 6), not
  config layering.

## Alternatives considered
- **Forbid any two checks at the same `full_path`.** Simpler to state but wrong — it
  breaks the documented `host-metrics` + `qnap-metrics`-on-one-host pattern
  (`architecture.md` §4.5). The conflict is shared **ownership** of a node's status
  (or two same-type branches), not a shared path.
- **One directory only (status quo).** Rejected as the *sole* option: forces
  copy-paste of shared checks across deployments. Still valid — a single directory is
  a union of one.
- **Override layering** (base + per-host overlay that replaces / merges same-path
  checks). Rejected for now: needs merge rules, precedence, a **tombstone** to
  *disable* a base check on one host, and harder "why is this running like this"
  debugging — clever over boring, for a need that satellites and the union already
  cover.
- **Live reload** (admin-triggered or file-watched). Rejected for now: reconciling
  add / remove / replace against a running scheduler and thread pool — and pruning
  orphaned nodes — is churn in the threading core ([ADR-0001](0001-in-process-threaded-engine.md))
  for a convenience a fast restart already provides; it pairs better with later
  live-ops work.
