# ADR-0012 — Node metadata: an `about` note, separate from check descriptions

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0007](0007-check-result-branches.md) (recursive `CheckResult` —
  descriptions on branch leaves), [ADR-0013](0013-check-config-on-node.md) (check
  config on the node), [ADR-0014](0014-maintenance-persistence.md) (the check-root
  coverage test the consistency pass shares), [ADR-0008](0008-json-output-api.md)
  (JSON envelope, unchanged here).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
A node carries `description` + `frequency` inherited from its check (`project.md`
§2.1). Two gaps:

- **Nowhere to say what a node *is*** — a host's location, what kind of box, the
  context whoever is triaging would want.
- **`description` is overloaded.** A branch check like `host-metrics` would have to
  describe several leaves at once on the shared host node, and two checks targeting
  one host node (`nexus` runs `host-metrics` + `qnap-metrics`) would clobber it.

The awkward part is *where metadata comes from*: a leaf check owns exactly one node,
but **container / host nodes are often owned by no single check** — `system` is
auto-created by the tree, a host node is a neutral container its leaves roll up into.
"Put it on the check" cannot reach those. We also weighed describing the whole
system topology in one declarative YAML, but that recouples topology with check
config and can never be complete once a **satellite** grafts a remote branch at
runtime (`project.md` §2.9).

## Decision
Make node metadata a **property fed by several sources**, and split the two
concerns.

1. **`about` — subject metadata.** A Markdown note describing the node itself
   (location, kind, context), distinct from `description` (what the *check* does).
2. **Sources, in precedence order:** a **`nodes.yaml`** declaration keyed by path
   (reaches container nodes no check owns, and satellite graft-points) **>** inline
   on the owning check **>** empty. A grafted satellite branch brings its own nodes'
   metadata in its JSON — the same node property, a third source.
3. **Per-leaf descriptions for branch checks.** A branch check declares each leaf's
   `description` through a `descriptions:` map keyed by leaf name (`disk`, `memory`,
   …); the shared host / container node's own `description` stays empty — which also
   stops two checks on one host node clobbering each other.
4. **Startup consistency pass.** After loading checks + `nodes.yaml`, **warn** for an
   `about` path that no configured check **covers** (an orphan — by the same
   static **check-root coverage** test the maintenance reaper uses, segment-wise on
   the same root-to-leaf line, [ADR-0014](0014-maintenance-persistence.md)), and
   info-log a host / container that has checks but no `about`. A config defect
   surfaces visibly, not as silent emptiness.
5. **Markdown, rendered later.** `about` and the leaf descriptions are Markdown; they
   show as plain text until the Phase 2 rendering item adds a renderer.

## Consequences
- Host and container nodes (and satellite graft-points) get human context, while
  leaves get their own check description; the two fields live at different depths and
  stop colliding.
- `about` reaches nodes no single check owns — the case per-check-only can't.
- A declared-but-unfed `about` is caught at startup, not left as a silent dead node;
  it simply shows `UNDEFINED` meanwhile.
- `nodes.yaml` is **optional** — the inline-on-check shortcut covers the
  one-check-per-node case with no extra file.
- Curated **links** are deliberately **deferred**; when built
  they'll be **structured** (not buried in `about`) so the `/links` page and clients
  can use them.
- The JSON envelope ([ADR-0008](0008-json-output-api.md)) is unchanged here; whether
  `about` joins it is the Phase 2 API item.

- **Where each field surfaces** (with the later popover, [ADR-0019](0019-inspection-popover.md)):
  a leaf's `description` shows on its **detail page**; `about` (and `title`) show on the
  dashboard **inspection popover**, and a branch's `about` under its heading. A **branch
  node's `description` is stored on the node but intentionally not displayed** — a
  container's detail lives in its leaves, and its own `about` already answers "what is
  this box"; so a branch `description` is simply latent (harmless), while a leaf's — and a
  single-node check's — `description` is exactly the detail-page "what this check does".

## Alternatives considered
- **Per-check metadata only.** Lightest, but can't label container / system nodes
  (no owning check) and is ambiguous when two checks share a host node. Kept as the
  inline source, not the whole answer.
- **One declarative whole-system tree YAML** (topology + checks together). Rejected:
  recouples topology with check config, fights the per-deployment dir model
  ([ADR-0015](0015-check-discovery-union.md)) with big-file merge pain, and can never
  be complete once satellites graft branches at runtime.
- **Fold links into the `about` Markdown.** Deferred and, when built, to be rejected
  in favour of structured links — a free-text blob isn't machine-usable for the
  `/links` page or the Swift client.
