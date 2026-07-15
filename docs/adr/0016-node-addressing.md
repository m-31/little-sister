# ADR-0016 — Node addressing: a single absolute slash path

- **Status:** Accepted
- **Date:** 2026-06-26
- **Related:** [ADR-0004](0004-status-aggregation-semantics.md) /
  [ADR-0007](0007-check-result-branches.md) (the tree these paths address),
  [ADR-0008](0008-json-output-api.md) (the JSON `path` field — schema-visible),
  [ADR-0015](0015-check-discovery-union.md) (check `owned_nodes` paths + coverage),
  [ADR-0012](0012-node-metadata.md) / [ADR-0014](0014-maintenance-persistence.md)
  (`nodes.yaml` keys / persisted maintenance paths).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
A node's location in the status tree is a **dotted path** — `system.alpha.disk` —
and a node is authored as **two fields**: a parent `path` plus its own `name`, joined
into `full_path` (`checks/base.py`, `status.py`). Two problems:

- **A name cannot contain the separator.** `.` delimits segments, so a host whose
  name is an FQDN — `example.org`, `example.net` — cannot be a node name; the checks
  work around it by underscoring (`name: example_org` for `host: example.org`), which
  reads poorly and discards the real name.
- **`path` + `name` is redundant.** A node already has one full location; splitting
  it across two fields (with an `rpartition` fallback when `name` is omitted) is two
  ways to say one thing, and that seam is where the separator ambiguity bites.

## Decision
Address a node by **one absolute, slash-separated path**.

1. **Separator is `/`, not `.`** — `system/alpha/disk`. A segment may now contain
   `.`, so a node can be named for its FQDN (`/hosts/example.org`). Slashes are rare
   in host / service names, so they delimit cleanly.
2. **Leading slash; paths are absolute.** Every path starts at the root `/` —
   `/alpha`, `/system/alpha/disk`. `split_path` ignores the leading (empty)
   segment; `join_path` always prepends `/`; the root node is `/`.
3. **One `path` attribute; `name` is derived.** A check / node is given a single full
   `path`; its **`name` is the last segment** — a computed property used for display
   and as the child key, no longer authored. The old `path` (parent) + `name` fields
   merge into this one `path`, and `Check.full_path` collapses into it. This changes
   the **`Status`** and **`Check`** constructors from `(path, name)` to `(path)`.
4. **The separator lives in one place.** A `PATH_SEP` constant plus `join_path` /
   `split_path` helpers (in `status.py`) replace every inline `.` join and
   `split(".")`. The segment-wise predicates (`on_same_line`, the ADR-0014 coverage
   test, `owned_nodes`) keep their logic — they already operate on segments, not on
   the raw string.

## Consequences
- **FQDN-capable names.** `name: example_org` becomes `example.org`; the underscore
  workaround retires.
- **Simpler authoring.** A check declares one `path: /system/alpha` — no `name:`, no
  parent/child split. The "must define a name and/or path" guard becomes "a path must
  have at least one segment."
- **URLs carry slash paths.** `/status/<branch>` and `/history/<path>` move to Flask's
  `<path:…>` converter (the default converter stops at `/`); link-building
  (`url_for('status', branch=…)`) must not double the leading slash. The root stays
  bare `/status`; breadcrumbs render the absolute path.
- **The JSON `path` field changes shape** ([ADR-0008](0008-json-output-api.md)) —
  `/system/alpha`, leading slash. This is **schema-visible**, but the Phase-3 Swift
  client and satellite federation do not exist yet, so it is a **free change now** and
  an expensive one once a consumer ships — doing it first is deliberate. The
  `status_envelope` question inherits the new shape.

- **Persisted paths migrate.** `var/maintenance.json` keys are paths; a file written
  before the change carries dotted keys that no longer match — the startup reaper /
  one-week expiry clears them, or a one-time rewrite converts them. Internal,
  low-stakes.
- **Wide but shallow.** The core is the ~12 join/split sites behind the helpers; the
  bulk is mechanical — every shipped check config (to one `path:`), the `nodes.yaml`
  keys, and the test / doc sweep.

## Alternatives considered
- **Keep `.`, quote / escape a dotted name.** Rejected: names commonly contain dots
  (every FQDN), so the escape becomes the common case, not the exception — uglier than
  changing the delimiter.
- **Slash separator, but relative (no leading `/`).** Rejected: a leading slash makes
  every path uniform and gives the root an honest name (`/`); the URL converter needs
  the same handling either way.
- **Keep separate `path` + `name`.** Rejected: the full path already determines both;
  one field removes the redundant seam — and the `rpartition` fallback the separator
  ambiguity exploited.
- **A different rare separator** (`:`, `|`). Rejected: `/` is the conventional path
  delimiter, reads naturally in URLs and configs, and only costs the `<path:…>`
  converter.
