# ADR-0017 — Node title: a short display label

- **Status:** Accepted
- **Date:** 2026-06-26
- **Related:** [ADR-0012](0012-node-metadata.md) (node metadata — `about`; `title`
  shares its sources and `nodes.yaml` shape), [ADR-0016](0016-node-addressing.md)
  (`name` is the derived last path segment `title` sits beside),
  [ADR-0008](0008-json-output-api.md) (JSON envelope, unchanged here). The
  Markdown-rendering item renders `title` too.
- **Register:** [`../decisions.md`](../decisions.md)

## Context
A node is identified by its `name` — the last segment of its absolute path
([ADR-0016](0016-node-addressing.md)) — which is often terse on purpose: `disk`,
`alpha`, `example.org`, `nas1`. The node already carries `description` (what its
*check* does) and `about` (rich **subject** metadata — location, kind, context;
[ADR-0012](0012-node-metadata.md)), but **nothing gives the node a short, friendly
label**. An operator scanning the dashboard wants a one-line caption (“Living-room
NUC”, “RAID-5 data volume”) without renaming the node — the name/path is the stable
identifier and addressing key, and must not change for display.

## Decision
Add an optional **`title`** — a short display label for the node.

1. **A brief label, not prose.** `title` is a short, one-line caption — less detailed
   than `about` or `description`. It is **Markdown**, shown as plain text until the
   renderer item lands, like `about` and the leaf `description`s.
2. **Same sources and precedence as `about`.** A `nodes.yaml` declaration keyed by
   path **>** an inline `title` on the owning check **>** empty. `nodes.yaml`'s
   per-path mapping carries it beside `about` — `path: {about: …, title: …}` — the
   extensible shape [ADR-0012](0012-node-metadata.md) chose for exactly this. Seeded
   onto the tree once at startup, like `about`; the startup consistency pass already
   warns for any declared `nodes.yaml` path no check covers, `title`-only entries
   included.
3. **Display.** The title **follows** the node name (or breadcrumb), ellipsed, never
   replacing it: on a **dashboard card** (and nested grid nodes) after the node name,
   and in the **page header** beside the `status / …` breadcrumb — on both a branch
   view and a **leaf's** detail page. The leaf's body still shows its `name` heading
   and `description`. The name/path identity is unchanged underneath.
4. **Web-only this slice.** It surfaces in the snapshot and renders in the web UI;
   it is **not** added to the JSON envelope ([ADR-0008](0008-json-output-api.md)) here
   — that is the Phase-2 `status_envelope` item.

## Consequences
- Friendly labels without touching identity: the path/name stays the stable address
  ([ADR-0016](0016-node-addressing.md)); `title` is pure display.
- **Low marginal cost.** It mirrors `about`'s plumbing exactly — a `Status` field, a
  `StatusSnapshot` field, a `set_title` seed, the same `nodes.yaml` + inline-check
  sources, the same consistency pass — so it is largely a parallel of an existing
  path.
- `nodes.yaml`'s nested `{about, title}` mapping is now the norm; the bare-string
  shorthand (`path: "text"`) stays sugar for `about` alone.
- It joins `about`, the leaf `description`s and `reasons` in the Markdown-rendering
  item — one renderer, several consumers.

## Alternatives considered
- **Overload `name` (rename the node).** Rejected: `name` is the last path segment and
  the addressing key ([ADR-0016](0016-node-addressing.md)); a human label must not
  change where the node lives or how it is reached.
- **Fold the label into `about` / `description`.** Rejected: those are longer-form and
  semantically different (subject vs check behaviour); a card needs a terse caption and
  a leaf a short heading, neither of which a paragraph serves.
- **A separate `nodes.yaml`-only field (no inline source).** Rejected: a leaf check
  often wants to name its own node inline, exactly as it can set `about`; reusing the
  `about` precedence keeps one model.
- **Title on checks only (no `nodes.yaml`).** Rejected for the same reason as `about`:
  container / host nodes have no owning check to carry it ([ADR-0012](0012-node-metadata.md)).
