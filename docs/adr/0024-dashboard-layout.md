# ADR-0024 — Dashboard layout: bounded heights, positional stability

- **Status:** Accepted
- **Date:** 2026-07-20
- **Related:** [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the
  `little-sister` heartbeat this strips out of the grid),
  [ADR-0019](0019-inspection-popover.md) (the hover card a collapsed chip keeps),
  [ADR-0012](0012-node-metadata.md) (the `title`/`about` the chips and strip carry).
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The overview renders each top-level system as a card in a responsive grid. Cards
differ wildly in height — a host with a dozen metric leaves beside the one-line
`little-sister` heartbeat — so a row is as tall as its tallest card, the everyday
all-green view looks ragged with holes, and when a node erupts its card grows and
reflows its neighbours mid-incident. The `depth` control already lets a viewer
flatten the tree, but the *default* view should look balanced on its own.

One constraint rules the design: operators rely on **where** a card is — whoever
knows the wall knows which corner a system lives in. So a card's **position** must
depend only on the **node set** (its names — order is already fixed alphabetical at
every level, per *Node sibling ordering* in the register), never on sizes. Balance,
though, is inherently about sizes, and no packing layout serves both at once: any
packer that closes holes must move cards when a size changes. The question is
therefore not "which packing algorithm" but "how to look balanced without a packing
layout at all."

## Decision

Keep every card's position a pure function of the node set, and **bound the size
variance** three ways rather than relaxing the position rule:

1. **Bound card heights.** The reason-overflow caps (a card shows at most a few
   reason entries and clamps a tall reason block) bound growth from above; a
   `min-height` floors sparse cards from below. Height then lives in a fixed
   `[min, cap]` band, so holes stay shallow and an erupting card shifts its row by a
   bounded amount.
2. **Collapse quiet leaves to chips.** A card's descendant leaves that are OK or
   idle render as compact name+colour **chips** instead of stacked boxes, so an
   all-green host converges toward a wrapping chip row of near-uniform height. A
   warn/error leaf keeps its full box and reason, so a problem stays legible; a
   chip's own detail is one click away on its leaf page, and its `title`/`about`
   still open in the hover card ([ADR-0019](0019-inspection-popover.md)). Chips are
   inline and boxes are block, so a run of quiet siblings packs onto a line and a
   problem box breaks it — preserving alphabetical order by document flow, with no
   partitioning.
3. **Lift the outlier out of the grid.** The always-tiny `little-sister` heartbeat
   ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)) leaves the grid for
   a slim **status strip** — a fit-content caption pill under the "updated …"
   freshness line it conceptually belongs with, refreshing inside the poll fragment.
   A stale heartbeat shows **vivid** (its self-alarm), not dimmed.

The heartbeat's `/little-sister` path is **reserved**: the loader rejects a custom
check owning nodes on it. The strip is a one-line bar and must never hide a subtree,
and the engine keeps the namespace for future children of its own — should it ever
grow some, the heartbeat falls back to a grid card rather than lifting. A
`nodes.yaml` `title`/`about` feeds the strip and its hover card like any node's, and
the engine seeds a default `about` so the pill explains itself
([ADR-0012](0012-node-metadata.md)).

## Consequences

- The everyday grid stops looking ragged and nothing jumps on a status change:
  positions are stable, heights are bounded, and density is up.
- Pure HTML/CSS plus one load-time guard (the reserved path) and the seeded default
  `about`. The status snapshot and the JSON envelope
  ([ADR-0008](0008-json-output-api.md)) keep their shape — the heartbeat's `about`
  field simply now has a value.
- A chip trades at-a-glance reason text for density; the reason stays one click away
  on the leaf page and in the hover card, and any warn/error leaf keeps its box, so
  nothing urgent is hidden.
- The `/little-sister` reservation costs deployments a name they could otherwise
  have used; in return the strip can never be spoofed or buried by a custom check.

## Alternatives considered

- **Equal-height uniform tiles** (every card one height, content trimmed or scrolled
  inside) — maximal stability *and* balance, but wasted space in sparse cards. The
  right answer for a later fixed-geometry **kiosk / wall display**, not for the
  interactive overview.
- **Packing layouts** — CSS `columns`, masonry, `grid-auto-flow: dense`: balanced,
  but a card's position becomes a function of *other* cards' heights, so anything can
  move on any state change. Rejected by the position rule itself; the objection is
  inherent, not a browser-support question.
- **Size hints in `nodes.yaml`** (a `weight` / `wide` flag) — static, no constant
  user arranging, but it couples node metadata to presentation and ages as checks
  change. A last resort; the automatic layout should be elegant without it.

Judged by rendering the real grid template against the fixture extremes (all-green →
a node erupting with a dozen reasons) as side-by-side static pages and comparing
screenshots — layout judged in the abstract fails; forty rendered extremes side by
side works.
