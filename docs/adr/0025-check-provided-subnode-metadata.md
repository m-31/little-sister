# ADR-0025 — Check-provided subnode metadata (`about` / `title` on `CheckResult`)

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-07-25)
- **Related:** [ADR-0007](0007-check-result-branches.md) (recursive `CheckResult` —
  the branch shape this extends), [ADR-0012](0012-node-metadata.md) (`about`, its
  sources and precedence), [ADR-0017](0017-node-title.md) (`title`, same sources),
  [ADR-0013](0013-check-config-on-node.md) (`config` — the display-metadata-on-result
  sibling, but write-through), [ADR-0019](0019-inspection-popover.md) (the popover that
  already renders these), [ADR-0008](0008-json-output-api.md) (JSON envelope, unchanged
  here), [ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)
  (a child that says a run names it takes its labels from its own result alone).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
A branch check ([ADR-0007](0007-check-result-branches.md)) emits `CheckResult.children`
and so **knows what its subnodes are** — a metrics check owns the meaning of its
`disk` / `memory` / `cpu` aspects, a repository check its per-aspect children. Today it
can hand each child a `description` (what the *check* does), but the subject label
`about` ([ADR-0012](0012-node-metadata.md)) and the short `title`
([ADR-0017](0017-node-title.md)) reach a child node **only** through a `nodes.yaml`
declaration keyed by that child's path, seeded once at startup. There is no inline
source for a subnode the way a check's *root* node has one (`about:` / `title:` in the
check's YAML, type-defaultable in code).

That fits host and container nodes, whose identity is **deployment-specific** — *this*
NUC in *that* cupboard — so their label belongs in *this* deployment's `nodes.yaml`.
But a check that emits **structured aspect subnodes** has **type-inherent** subnode
identity: what `disk` measures and how it grades is a property of the check *type*, the
same in every deployment and on every host it runs against. Leaving that label to
`nodes.yaml` means copy-pasting the same per-subnode `about` (and any legend) into every
deployment, for every host — the exact duplication [ADR-0012](0012-node-metadata.md)
removed for the *check's own* node but never closed for its children. The missing source
is the one the check already is: the **result value should carry the subnode labels**,
as a third feed beneath `nodes.yaml`.

## Decision
`CheckResult` carries the labels for the subnodes a branch check emits, and the tree
applies them with a **seed-once** rule that keeps `nodes.yaml` authoritative without the
engine or tree learning where a value came from.

1. **Two optional fields on the value.** `CheckResult` gains `about` and `title`
   (Markdown, empty by default), beside `description` / `config`. Like `name`, they are
   **ignored on the root result** — the engine places the root at `check.path`, and the
   root keeps its existing label sources (`nodes.yaml` > inline-on-check > empty). Only
   a **child** result's labels are read.

2. **Per-field precedence: `nodes.yaml` > check-provided > empty.** Each field resolves
   on its own — a `nodes.yaml` entry that sets only `about` still lets the check fill
   `title`.

3. **Mechanism — seed-once tree semantics.** Startup seeding (`set_about` / `set_title`)
   stays an **authoritative overwrite**; the engine's runtime write
   (`upsert(about=…, title=…)`, via `_store` for each child) **fills an empty field
   only**. Because `nodes.yaml` (and the root's inline value) is seeded *before the
   engine's first tick* — `_seed_node_metadata` runs before `engine.start()` — a declared
   label is already present when the first result arrives, so fill-empty leaves it
   untouched: `nodes.yaml` wins with no provenance state. `description` / `config` stay
   **write-through** (they are the check's to refresh every run); `about` / `title` are
   identity labels, so they freeze at the first fill.

4. **Nothing else moves.** The web surface needs no change — the inspection popover
   ([ADR-0019](0019-inspection-popover.md)) already walks the whole snapshot, so more
   nodes simply populate. The **JSON contract does not move**: `about` / `title` are
   already node fields in [`../api/openapi.yaml`](../api/openapi.yaml); they merely
   populate for more nodes. The per-leaf `descriptions:` map (ADR-0012) is untouched:
   a different field, with write-through semantics.

5. **Where a check sources the labels.** Point 1 is the *transport* (`CheckResult`);
   **the library reads, a check only declares.** A deployment states the labels in a
   **`subnodes:` block**, `name -> {title, about, show_when_quiet}`, in the same file
   the check's root inline `about` / `title` live in. The non-label key in that block
   sets the shape (`show_when_quiet`, ADR-0063): parsed by `Check._parse_common` for
   every type, applied by the engine per child name, so a deployment states it for any
   installed branch check with no check release. The labels follow: a type declares
   **`subnode_defaults`** (`name -> {title, about, show_when_quiet}` — the per-aspect
   maps, a declaration the library applies, and shaped like the `subnodes:` block
   itself, so the type's half mirrors the deployment's key for key: ADR-0063's flag
   rides the same entries, a roster aspect declared once beside its own label) and
   **`label_tokens`** (`token -> value`), both ordinary common-field constructor
   keywords. The library resolves each field once — for text, the configured value when
   present, else the declared default, `{default}` substituted and `{token}`s expanded
   by a plain replace; for the flag, the same merge without the layering — and the
   engine stores the result per child name. What is declared for a subnode's name
   reaches a child that says nothing
   ([ADR-0118](0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)), and
   for such a child a result-carried label or flag remains only the fallback for a name
   nothing declared or configured, so a deployment-authored check stamping a dynamic
   child keeps working. A child that says a run names it, `dynamic=True`, takes its
   labels from its own result alone, with a `nodes.yaml` entry for its path still above
   them. The config may **extend** rather than
   replace by writing `{default}` into its own text, which is substituted in place
   (before token expansion, so tokens inside the default still expand; an aspect with no
   default resolves it to nothing). So `host-metrics` ships defaults every deployment
   inherits yet lets one retune or annotate an aspect's `about` in its config, while a
   deployment-authored branch check can keep its labels wholly in config. The extension
   form earns its keep when one check *type* runs several times in a deployment — one
   per team — where config-only labels would put the same paragraphs in every instance's
   file. Per-field precedence is `nodes.yaml` > the deployment's block > the check >
   empty; seed-once / fill-empty is the mechanism; labels freeze at the first fill —
   which pins tokens to construction-time facts structurally.

## Consequences
- A reusable branch check ships its subnode legend **once, in code**, and every
  deployment's hover cards explain those leaves out of the box; a deployment still
  overrides any of them per field in its own `nodes.yaml`. `host-metrics` adopts this
  in-repo as the first proof — a per-aspect `about` for `ssh` / `disk` / `memory` /
  `cpu` / `load` (the numeric bounds stay in each child's `config`,
  [ADR-0013](0013-check-config-on-node.md), not duplicated in the prose).
- A check-provided label is **fixed at the node's first fill**, for the life of the
  process. These are **stable identity labels, not live status** — text that changes
  with each observation (a percentage, a failing path) belongs in `reason`, which *does*
  update every run. A label that legitimately needs to change is a restart, like any
  seed-time metadata.
- The tree and engine stay **provenance-free**: the fill-empty rule is the whole
  mechanism, two lines under the existing status-write lock. No `Status` grows a
  "source" field; no resolved-metadata map is plumbed into the engine.
- `parse_subnodes`, `resolve_text` and `expand_tokens` lose their external callers and
  retire from the authoring facade, ADR-0049's surface gate moving with them — a
  **breaking** change to the surface, taken deliberately while every consumer is
  family-owned and moves in lockstep; there is deliberately no compatibility window,
  and the release notes say it at the top.
- Two holes close: a `subnodes:` label on a type that never read the block was a silent
  no-op and now reaches every branch type; and substitution becomes one library
  contract — a plain `str.replace`, token values inserted as Markdown-active text with
  raw HTML escaped at render (ADR-0018), so a check exposes only values it would print
  as Markdown.

## Alternatives considered
- **A yaml-aware engine** — plumb the resolved `nodes.yaml` metadata map into
  `Engine._store` so it *skips* writing any field a declaration already owns. Rejected:
  it re-couples the engine to `nodes.yaml` (which [ADR-0012](0012-node-metadata.md) kept
  a startup-only, web-side concern) and buys **live** label updates — a running check
  overriding a label the instant its declaration is removed — that nothing needs, since
  labels are seed-time identity. Seed-once gets the same precedence with none of the
  wiring.
- **Per-field provenance on `Status`** — tag each label with its source (yaml / check /
  empty) and resolve on read. Cleanest *live* semantics (a source could change
  precedence at runtime), but the **most state**: every metadata field doubles, every
  writer sets provenance, and the snapshot carries it — all to support runtime
  re-resolution the product has no use case for.
- **Leave it to `nodes.yaml` (status quo).** Rejected: it is exactly the per-deployment,
  per-host copy-paste this closes; type-inherent identity has an obvious home on the
  type.
- **Prune children a shrinking result stops reporting.** Unrelated to where a label
  comes from, and still deferred ([ADR-0007](0007-check-result-branches.md)).
