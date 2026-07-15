# ADR-0013 — Surface check config as node display metadata

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0007](0007-check-result-branches.md) (recursive `CheckResult` —
  refined here), [ADR-0002](0002-rlock-snapshot-synchronization.md) (the tree owns
  state), [ADR-0008](0008-json-output-api.md) (JSON envelope, unchanged here).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
The check detail page renders from a `StatusSnapshot`, which carries no
configuration; a check's parameters (an `http` url, `host-metrics` thresholds) live
on the `Check` object in the engine. An operator triaging a node wants to see what
it was configured with.

[ADR-0007](0007-check-result-branches.md) drew a boundary — `CheckResult` is "a pure
value", and config is "the check's concern" — but it **already** lets the result
carry `description` as inherited display metadata. The sharp question is how config
reaches the page for **branch checks**: `host-metrics` targets a *container* host
node (which renders the grid, not a detail page), and its leaves (`disk`, `memory`)
are auto-created with **no `Check` object** — so a "web pulls config from the check"
approach can't reach them.

## Decision
Treat a check's displayable config the way `description` is already treated:
**inherited display metadata that rides on the `CheckResult` onto the node** —
refining ADR-0007's boundary (the result may now carry config; identity, observation
time, maintenance and event-on-change stay the tree's).

1. **Curated, not reflected.** Each check exposes a small **allow-list** of safe
   fields formatted to strings (`http` → `url`, `expected_status`) — not a generic
   dump of attributes (the `SshConnection` block and sets render as leaky junk and
   throw away the curation that keeps sensitive fields off the page).
2. **Pushed per node.** `CheckResult` gains a `config` field; a leaf check tags its
   result, and a **branch check tags each child with the slice that produced it**
   (`disk` ← its thresholds). `Engine._store` writes it onto the `Status` node like
   `description`, so config lands exactly on the node it configured and the web layer
   just reads the snapshot.
3. **Static metadata, not status.** Config is stable between runs: storing it emits
   **no event**, re-setting the same value is a no-op, and it never enters
   aggregation ([ADR-0004](0004-status-aggregation-semantics.md)) or freshness
   ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)).
4. **Web-only this slice.** It surfaces in the snapshot and renders on leaf detail
   pages **to all viewers** (config is operator-authored; secrets live in `.env`,
   [ADR-0003](0003-config-and-secrets-via-env-file.md)). It is **not** added to the
   JSON envelope ([ADR-0008](0008-json-output-api.md)) here — that is the Phase 2 API
   item.

## Consequences
- Branch-check leaves show their own config — the case a pull-from-engine design
  couldn't reach — and the web layer keeps reading only the snapshot (no new
  web→engine coupling for rendering).
- A node shows config only **after its first run**; a never-run (`UNDEFINED`) or
  maintenance-pinned-before-first-run node has none yet. Checks are all due at
  startup, so the gap is brief.
- Adding a check means declaring its allow-list (a few fields); the base formats
  them.
- ADR-0007 stands; this refines its "config is the check's concern" line to "config
  may travel as display metadata, still not status".

## Alternatives considered
- **Web pulls from the engine** (`engine.check_for(path)` → `config_summary()`).
  Rejected: can't reach branch-check leaves (no `Check` at those paths), and couples
  the web layer to the engine for rendering.
- **Stamp config onto the tree as first-class state.** Rejected: it isn't status —
  keeping it out of events / aggregation / freshness matters; it is metadata
  alongside `description`, nothing more.
- **Generic reflection of check attributes.** Rejected: unsafe and ugly (nested value
  objects, sets), and removes the curation that withholds sensitive fields.
- **Admin-only card.** Considered (consistent with `/system`); not needed — the app
  is internal-only and the fields are operator-authored — but the allow-list is where
  a field would be withheld if that ever changed.
