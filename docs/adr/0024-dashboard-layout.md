# ADR-0024 — Dashboard layout: bounded heights, positional stability

- **Status:** Superseded by ADR-0056
- **Date:** 2026-08-23 (accepted 2026-07-19)
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
reflows its neighbors mid-incident. The `depth` control already lets a viewer
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
   idle render as compact name+color **chips** instead of stacked boxes, so an
   all-green host converges toward a wrapping chip row of near-uniform height. A
   warn/error leaf keeps its full box and reason, so a problem stays legible; a
   chip's own detail is one click away on its leaf page, and its `title`/`about`
   still open in the hover card ([ADR-0019](0019-inspection-popover.md)). Chips are
   inline and boxes are block, so a run of quiet siblings packs onto a line and a
   problem box breaks it — preserving alphabetical order by document flow, with no
   partitioning. Chipping the quiet *leaves* alone would leave a quiet sub-*branch*
   rendering as a full box, so a card with many sub-branches — a NAS whose `disk` /
   `smart` / `system` / `temperature` each box a chip-row — would grow into a
   skyscraper. The collapse therefore extends one level: in the dense view a branch
   caps the quiet (non-warn/error) child **boxes** it shows to a `config.yaml` budget
   (`branch_cap`, default 3, the count-cap sibling of `reason_cap`). The surplus boxes
   are marked `is-extra` — kept in the DOM but hidden — and the level grows a **"+N
   more"** control that reveals them in place; `branches.js` holds the open state
   across the ~10s poll swap (the reason-chevron pattern), keyed by branch path. The
   cap is an exact server-side count, so unlike the reason chevron it needs no browser
   measurement, and it is applied at **every** branch level. A **warn/error box is
   never capped**, so nothing urgent is hidden; with the density switch off,
   `branch_cap` does nothing and every node renders as a full box. Positions are
   untouched — folding only shortens a card — so the grid keeps its alphabetical,
   size-independent layout.
3. **Lift the outlier out of the grid.** The always-tiny `little-sister` heartbeat
   ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)) leaves the grid for
   a slim **status strip** — a fit-content caption pill in a **right-aligned band at
   the top of `#status-grid`, beneath the hide/depth controls**, so it reads as its
   own element rather than the grid's first row. It stays **inside the poll
   fragment** — both regions (the strip band and the card grid) swap and dim as one
   unit, `poll.js` unchanged — while the "updated …" freshness line stays *outside*
   the fragment so it survives a failed fetch. The pill is not a page-wide banner,
   and carries a small **watching-eye glyph** as a self-monitor identity, setting it
   apart from the node pills. A negative-margin pull-up onto the caption row is
   rejected: `poll.js` inserts the sustained-outage banner exactly there
   (`insertBefore(banner, #status-grid)`). A stale heartbeat shows **vivid** (its
   self-alarm), not dimmed.

The heartbeat's `/little-sister` path is **reserved**: the loader rejects a custom
check owning nodes on it. The strip is a one-line bar and must never hide a subtree,
and the engine keeps the namespace for future children of its own — should it ever
grow some, the heartbeat falls back to a grid card rather than lifting. A
`nodes.yaml` `title`/`about` feeds the strip and its hover card like any node's, and
the engine seeds a default `about` so the pill explains itself
([ADR-0012](0012-node-metadata.md)).

### Surfacing maintenance

Admin **maintenance** (a sticky override, [ADR-0014](0014-maintenance-persistence.md))
was easy to lose: a pin deep in the tree rolls up out of sight at a shallow `depth`,
and *hide idle* hid it outright (maintenance was bundled with `UNDEFINED` in the
filter). The dashboard surfaces the persisted set two ways, both computed from the
**unfiltered** snapshot in the route so they survive the hide filters and any depth: a
**global list** of every pinned node (path, time left, reason), each linking to its
node, and a **"contains maintenance" pip** on any card whose subtree holds a pin but
which is not itself pinned, so a glance at any depth shows where to drill. The pip is
maintenance-tinted (legible on any card fill, since the card's own status is a
different color) and is a **button**: clicking it opens a small popover listing just
that card's pins as links — a deliberate, less-obtrusive alternative to a hover —
reusing the inspection popover's Floating-UI positioning and poll-swap survival
([ADR-0019](0019-inspection-popover.md)). The button is keyboard-reachable and carries
an accessible name plus `aria-haspopup` / `aria-expanded`, so assistive tech announces
it as a popup control. And *hide idle* hides only never-reported (`UNDEFINED`) nodes:
maintenance is an intentional admin state, not idle, and stays visible.

An always-on global list suits a handful of pins but becomes a wall once they pile up,
dwarfing the grid it would sit over, so it **folds away**: a compact,
maintenance-tinted **pill** joins the status strip just left of the `little-sister`
heartbeat — the pause-bars glyph and a live count (`12 in maintenance`), shown only
when something is pinned and refreshed inside the polled fragment like the strip
around it. Clicking it opens the maintenance popover (`maintenance.js`, Floating UI,
[ADR-0019](0019-inspection-popover.md)) over the **whole** set rather than one card's,
**capped like a node**: a `maintenance_cap` in `config.yaml` (the count-cap sibling of
`reason_cap` / `branch_cap`, plumbed to the full page and the `?fragment` swap) shows
the first N pins, then a **"+N more"** to a dedicated **`/maintenance` route** — a
read-only page (the leaf-detail pattern) that renders the full, uncapped overview,
viewer-visible and bookmarkable. The pill is itself an `<a>` to that route, so the full
list stays reachable with no JavaScript (or when Floating UI fails to load); JS
upgrades a plain click to the popover and leaves a modified click to open a new tab.
The strip band that right-aligns the heartbeat holds both, so the pill and heartbeat
sit together under the view controls. The per-card **pips** serve as the at-a-glance
"which card" and open the same popover scoped to their subtree; the *global* list is a
count plus one click rather than an always-visible block. That is a deliberate step
back from an always-on index (the pips keep the glance honest), so the trade is named,
not slid into. Still view-only: the snapshot, the maintenance side-table and the JSON
envelope are unchanged; this adds HTML/CSS/JS, one read-only route and one config knob.

### Reason separators

Within a card, stacked reasons blurred together: each reason is a block whose wrapped
lines share the body leading (ADR-0018 keeps them compact), and nothing separated one
reason from the next, so a several-reason block read as a single paragraph. Reasons
carry a **tight hairline between entries** (never above the first) plus a small gap —
the "tight rows + rule" of the options weighed — on the dashboard and the leaf detail
page's alert alike. The rule is drawn from `currentColor` at low alpha, so it takes
each surface's readable text color and reads on a vivid fill (white text), a dim tint
and the pale alert (dark text) without a per-status rule — the same
non-color-dependent posture as the status cues. The divider **adds height per
reason**, nominally lifting a reason block's share of the bounded-height cap
(decision 1); on the dashboard that per-boundary height is folded into the
`reason_cap` clamp (`--reason-lines × (line + gap)`), so the budget still shows about
`reason_cap` entries and the reasons.js overflow chevron is unaffected. The detail
page shows every reason uncapped, so it only gains the rules. CSS plus one template
class; the snapshot, the JSON envelope and the reason data are unchanged.

### Track spans for large roots

The positional-stability rule admits one topology-only case. A card may span several
ordinary grid tracks when the current row has spare tracks, but its span remains a
pure function of the **filtered, depth-limited node set**, source order and available
track count — never of live status, reasons, rendered height or whether dense mode
paints a leaf as a chip. The server counts each visible card/box/chip node once,
including nodes folded behind `+N more`, and precomputes deterministic plans: every
card starts at one track; within each consecutive source-order row, each spare goes to
the greatest `weight / span` among the cards still eligible for one. A card is
eligible while **both** hold — its weight is above the internal budget of 16 nodes per
track, and its span is below its own **branch limit**, the widest sibling set anywhere
in its visible subtree. Thus weights 30 and 66 split a four-track row 1:3; a calm
leaf, a three-node root and a single-child chain stay narrow, the chain because it
branches one wide however heavy it grows. A wider card spends the width only at a
descendant level containing multiple direct full node boxes; single-child wrappers
stay full-width and any level containing leaf chips keeps its inline chip flow.
`dashboard-layout.js` selects the server plan after initial render, a resize and the
poll's fragment swap. The original auto-fill CSS remains the no-JavaScript or
malformed-data fallback. The snapshot and JSON envelope are unchanged.

The budget is the **entry price** for widening a root, not a ceiling on how far it
widens. A ceiling of `weight / budget` tracks is right only while the roots differ
enough for one of them to stay hungry. Two roots of roughly equal, genuine size — the
shape of a live overview whose two teams watch the same aspects — would both stop at
two tracks and leave every further column empty however wide the viewport grew. The
branch limit refuses width a card could only paint as whitespace, and it is a topology
fact, so it is as stable as the weight. A spare track with no eligible taker stays
empty — that remains the right answer for a row of small or linear roots.

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
