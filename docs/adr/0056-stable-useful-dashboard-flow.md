# ADR-0056 — Dashboard layout follows stable, useful flow

- **Status:** Accepted
- **Date:** 2026-10-18 (accepted 2026-08-15)
- **Supersedes:** [ADR-0024](0024-dashboard-layout.md)
- **Related:** [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (the `little-sister` heartbeat),
  [ADR-0014](0014-maintenance-persistence.md) (maintenance pins),
  [ADR-0019](0019-inspection-popover.md) (chip and maintenance popovers),
  [ADR-0012](0012-node-metadata.md) (chip and strip metadata),
  [ADR-0076](0076-the-instance-node-is-a-branch.md) (the branch the strip rolls up),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (the tree
  that replaces dense mode's switch, and the folds that replace `branch_cap`),
  [ADR-0128](0128-where-a-nodes-first-look-comes-from.md) (the first look this prices).
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The overview renders each top-level system as a card in a responsive grid. Cards
differ wildly in height, but operators rely on where each card is. A packer that
closes every hole also makes a card's position depend on other cards' live heights,
so an incident can rearrange the wall while somebody is reading it. The layout must
therefore remain a function of stable tree facts, not rendered pixels.

ADR-0024 bounded height with reason caps, chips and branch folds, and later let a
large root spend spare outer tracks. Its first column allocator used visible node
count, a 16-node entry price and one maximum branch factor. Live fixtures exposed
five places where that approximation and useful rendered width diverged:

- configured `reason_cap: 30` makes potential reason hosts much taller without
  changing the number of nodes;
- nesting quantizes usable width, so span two can buy no nested column while span
  three does;
- one maximum branch factor cannot express a branch that becomes usable only after
  several nested insets;
- a direct chip at a mixed level prevented its full boxes from using a grid; and
- the fragment shipped 32 complete plans, including 2,560 integers for 80 roots,
  while an arbitrary 16/17-node boundary decided who could compete for every spare.

The durable part of ADR-0024 is the stable-position constraint and its density
tools. The allocation approximation is replaced here; the rest is restated so this
record is complete on its own.

## Decision

### Stable position and bounded content — decided 2026-07-19

A card's position is a pure function of the filtered, depth-limited node set, its
declared sibling order, the first look its configuration gives each node
([ADR-0128](0128-where-a-nodes-first-look-comes-from.md)) and available ordinary grid
tracks. Live status, current reason count or text, measured element height, and a chip
or a box drawn by a status or by a click do not participate: a click makes a card
taller or shorter where it stands. A node-set, explicit filter/depth or viewport change
may reflow; a status-only poll may not.

Bound the remaining height variance:

1. Dashboard reason blocks use the configured line budget and a sparse card keeps
   the established minimum-height floor.
2. A node is a chip or a box, closed or open by a click
   ([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)), and
   how each starts is its configuration's. Where nobody speaks for a level, a quiet
   descendant leaf is a compact name-and-state chip and a warn/error leaf a full box
   with its reason — the density the page drew before the tree — until the built-in
   look is ADR-0128's. A failure's box is never folded: it opens its way
   within its card's budget of three, and past it is a red chip with its count; and
   within item 1's line budget a box shows its failing lines first, errors, then
   warnings, then the rest, each in its check's order (ADR-0127 decision 6). A chip's
   detail is one click away and its metadata remains inspectable.
3. The reserved `/little-sister` heartbeat leaves the card grid for a fit-content
   status-strip pill, and it is lifted **with its children**: the path is a branch,
   one child per contributor ([ADR-0076](0076-the-instance-node-is-a-branch.md)), and
   the strip is that branch's roll-up — it summarizes the subtree as any branch card
   does and links to `/status/little-sister`, where the children are the page, so
   lifting it hides nothing (`_split_heartbeat`). A heartbeat that is not on the root
   overview is not lifted. The loader rejects a user check that claims the reserved
   namespace.

The status snapshot and JSON envelope do not change.

### Status band and quiet branches — decided 2026-07-25

The heartbeat sits in a right-aligned band at the top of `#status-grid`, beneath
the view controls and inside the polled fragment. Its watching-eye mark distinguishes
self-monitoring from ordinary nodes, and a stale heartbeat stays vivid.

At a branch level nobody speaks for, `branch_cap` limits only quiet full child boxes:
surplus boxes remain in the DOM behind an in-place `+N more`, a warn/error box is
never folded, and the tab's map keeps an open fold across a poll swap. `branch_cap` and
its `+N more` leave when the built-in look becomes ADR-0128's, and chips and the healthy
fold are then the folds (ADR-0127 decision 6). The depth control and the
chips switch have left the band with their cookies (ADR-0127 decision 7).

### Maintenance visibility — decided 2026-07-25

Maintenance is computed from the unfiltered snapshot so shallow depth and hide
filters cannot erase it. A card whose subtree contains a pin carries an accessible
maintenance pip opening the scoped list. The global list is folded into a live count
pill beside the heartbeat; its capped popover links onward to the complete read-only
`/maintenance` page and the pill itself is the no-JavaScript link. Maintenance is
not idle and is not hidden by *hide idle*. These surfaces do not change the snapshot,
maintenance side-table or JSON envelope.

### Reason separators — decided 2026-07-25

Stacked reasons carry a tight `currentColor` hairline and gap between entries on
both dashboard and detail surfaces. The dashboard folds that boundary height into
the configured line clamp; the detail page remains uncapped.

### Stable useful column flow — decided 2026-08-15

For each top-level card, the server derives a **stable flow profile** from its
filtered, depth-limited topology, the first look its configuration gives each node and
its configured `reason_cap`:

- every visible open node is a potential reason host and costs at least its heading
  row, scaling by `ceil(reason_cap / 6)` at its own `reason_cap`, which a check may set
  for its nodes; this reads the stable configured budget, never current reasons;
- a node closed by the configuration, or by a `depth=` in the address, is a chip in its
  run, and each run is priced where it stands among its level's boxes, a line of chips
  as a heading row at its level's width, estimated from the names of all the level's
  children and never from a status
  ([ADR-0128](0128-where-a-nodes-first-look-comes-from.md) decision 6);
- for outer spans 1 through 32, the model applies the same 330 px ordinary nested
  track, gaps and per-level insets as the stylesheet, then sums sibling rows by the
  tallest branch in each row; and
- a span enters the profile only when, since the preceding useful span, it removes
  at least one stable flow row per additional outer track.

This is an intentionally discrete model, not pixel measurement. A profile may jump
from span one directly to span three when span two cannot open a nested track; a
linear chain has no wider step at all. Reason text may come and go without changing
the profile, while changing the configured reason budget deliberately changes it. So
chip-versus-box painting enters the profile as the configured first look, while a status
and a click never do.

Within each consecutive source-order row every root starts at its first one-track
step. The allocator's objective is min-max, not summed gain. A grid row is as tall
as its tallest card, so among cards whose next useful step fits, the currently
tallest one wins; equal heights fall to the better reduction per track, exact ties
to source order. A step can consume several tracks atomically. If no useful next
step fits, tracks remain empty rather than padding a card with width its tree cannot
use. The summed-gain rule measurably misallocated: two equal roots on a fourteen-track
grid went `[12, 2]`, because every one of the twelve tracks paid a row while the
starved neighbor owned the row height throughout. Under min-max they grow
alternately.

A descendant level containing at least two direct full boxes uses responsive nested
grid tracks. Consecutive quiet chips share a full-row `leaf-chip-run`: the chips wrap
inline inside it while full boxes at the same mixed level can still grid. A single
child wrapper and each node box remain intact, so a node and its reasons never split
between columns and document order stays unchanged.

The five stylesheet constants are pinned by a structural test. The model mirrors
`overview.css` (330 px track, 1 rem and 0.4 rem gaps, card and box insets) by hand;
a test reads the stylesheet and compares, so moving the CSS turns a silently wrong
layout into a red test. The per-node cost divisor written as `6` above is the
**default reason budget** (`DEFAULT_REASON_CAP`), not a sixth constant.

Pricing a span at the 330 px track **minimum** misprices it: `auto-fill` distributes
a real viewport's leftover across its tracks, so a resolved track is almost always
wider. A two-track card at the minimum offers ~656 px against the ~666 px two nested
columns need — ten pixels short — so a minimum-priced model called span two useless
everywhere, although it fits at nearly every real width. Two consequences were
measured: two equal ~30-node roots on a real four-track grid were allocated `[3, 1]`
— a 1,137 px card beside a 1,949 px tower — where `[2, 2]` paints 1,137/1,137; and a
root branching four wide at its second level missed a 1,763 → 918 px step because the
fourth nested column missed the minimum by a hair.

The server retains the 32 plans for deterministic diagnostics. Breakpoints are keyed
in grid width, not track counts. The server prices each candidate span at the content
width it actually has at that grid width (integer tenths, exact threshold enumeration
— every width at which any nested column count anywhere can flip, mapped back through
the same arithmetic the height model divides with) and publishes bands where the plan
changes. Bands publish **tenths of a pixel**, the model's own unit, and the client
scales its measurement by ten: publishing the ceiling in whole pixels instead left a
band up to 0.9px late — nine times the column tolerance — and browsers report
fractional widths, so across that gap a wall could carry a 105-row plan while a legal
count offered 75. The column tolerance is one tenth of a pixel, and a browser test
holds model and paint to within a pixel of each other.

`dashboard-layout.js` measures the grid's resolved width — a viewport fact it already
observed for the resize reflow — and selects the last applicable band; the resolved
track count remains only as the safety clamp on a span. It never derives product
semantics from the DOM. Grid width is not a status fact, so the stability rule is
untouched. The ordinary `auto-fill` grid remains the no-JavaScript and malformed-data
fallback.

The published band count is proportional to actual plan changes over width (roughly
sixty entries, under a kilobyte, for the two-root live shape; still one band for
eighty flat roots). A deployment that wants none of this sets `settings.yaml`
`dashboard_columns: plain`, which withholds the plan and leaves the auto-fill grid —
byte-for-byte the no-JavaScript page; `flow` is the default, anything else warns and
falls back. That key is deliberately an enum, not a switch: a per-viewer value and a
possible `packed` mode are later steps of the same control.

### Explicit track counts — decided 2026-08-15

Width pricing alone leaves one flaw standing: **at the exact width where `auto-fill`
adds a track, every track snaps back to the 330 px minimum**, so a span-two card
physically loses its second nested column and one more pixel of viewport paints a
dramatically taller page. Measured on the equal-root fixture: a 1,713 px grid painted
the 2 + 2 split at 1,137 px twice (1,582 px document); at 1,714 px the fifth track
snapped in and the same tree painted a 2,122 px tower (2,567 px document). The
lopsided fixture worsened the same way at 2,405 → 2,406 px. This is not an
enumeration bug — an integer number of minimum-width outer tracks simply cannot
express the half-and-half layout an odd count just destroyed.

A published band therefore names the **track count its plan was priced for**:
`(tenths, tracks, plan)`. The script sets the grid to exactly that many equal tracks
(`repeat(tracks, minmax(0, 1fr))`), so at 1,714 px the four wide tracks simply stay.
A count of `0` means "let auto-fill decide" and is only ever sent with an all-ones
plan, which is valid at any count — a flat eighty-root wall therefore still ships one
band and paints byte-identically to the fallback. Three rules keep the choice
disciplined:

- **Candidates are priced by modeled page height** — consecutive source-order rows,
  each as tall as its tallest card — with the summed card heights breaking ties
  (two candidates can hide the same tallest card while one leaves a second tower
  beside it), then more tracks, so an indifferent grid behaves like `auto-fill`.
- **A candidate never stretches a track wider than auto-fill itself can produce**
  (one track just before a second fits, ~676 px) — equivalently, the count never
  drops below about half the auto-fill count. Explicit counts exist so a plan can
  keep the tracks a boundary would snap away — never so the wall can stack into
  the page-wide banners this record has always rejected, although one enormous
  card is often the modeled-shortest page. The first formulation of this floor,
  `min(roots, auto-fill count)`, grew with the viewport and disqualified exactly
  the counts that were holding the page: twelve linear roots of mixed heights
  rode one auto-fill band and rose 15 → 16 modeled rows when the eighth track
  re-chunked them, the seven-track hold being below the floor; a randomized wall
  rose 47 → 48 the same way. Under the track-width floor the sweep pins an
  explicit band through a harmful region and returns to auto-fill when a larger
  count genuinely ties or wins.
- **The incumbent band never expires and a challenger must strictly beat it as
  repriced at the current width.** A track count stays feasible at every wider
  grid and its cards only widen, while a fresh greedy allocation at the same count
  can genuinely come out worse — the strict inequality is what makes a wider
  viewport unable to select a worse page, and it also quiets the band churn near
  boundaries. The floor above constrains **new** counts only, never the held one:
  a fixed plan is *not* guaranteed to get shorter as its cards widen, because a
  card's own nested column count can flip mid-band and re-chunk its children into
  worse rows (found by counterexample: nine roots, the ninth ending in five short
  children and two deep chains — at the width where its nested grid went five
  columns to six, the chains landed in separate rows and the held plan rose
  12 → 17 modeled rows). The dodge is a re-span at the incumbent's own count, so
  that count must stay challengeable even after the floor grows past it; the
  monotonicity test therefore evaluates the active band's fixed cost immediately
  before and at every model event, not merely at published band starts.

`_height_pieces` used to evaluate the whole subtree at every propagated threshold —
0.4 s at a thousand leaves, 6.7 s at ten thousand, per poll — and now merges its
**children's pieces bottom-up**, so each node's work is local (10,000 leaves:
~150 ms); `_flow_height` stays as the straight-line reference with a differential
test holding the two together. And the finished layout is **memoized on the
depth-limited tree shape** plus the reason budget — the only inputs it ever reads —
so a poll that changed nothing but statuses costs a dictionary lookup.

### What a wider viewport promises — decided 2026-08-15

A fifteen-plus-one fixture rules out a universal "wider never gets taller" claim:
fifteen leaf roots beside one root whose children are chains of heights
(3, 3, 3, 7, 5). Inside an unchanged three-track band, the mixed card's
**nested auto-fit** flips three columns to four, the 7-chain re-chunks beside the
5-chain instead of above it, and the card genuinely grows (modeled 16 → 18 rows;
painted ~1,141 → ~1,229 px) — while every alternative track count costs 28 or more.
The incumbent itself becomes taller and there is nothing to switch to. The rise is
the card's own: the planner controls outer tracks and spans, and this reflow
happens a level below both.

**Is a general guarantee possible at all?** In the model, yes, and provably: if
the plan also pinned **every level's column count**, a fixed complete layout's
modeled height would be width-independent, the feasible set only grows with
width, and the minimum is monotone by induction — a bottom-up min-over-columns
dynamic program whose argmins ship with the band. It is not built, deliberately:
bands would carry a per-card nested assignment the script applies level by
level, the payload and the client grow accordingly, every change to the card's
interior template becomes a layout-model liability — and the theorem still ends
at the model's edge, because text wrapping and live reason blocks were never
priced. The full construction is recorded in the backlog with its price; it is
worth that cost only if per-card reflow proves to annoy in practice.

**What is promised instead**, and held by tests:

- **No harmful outer snap.** At the width where auto-fill adds a track, the
  published band keeps its wide tracks; the boundary paints flat to the pixel
  (held by a Chromium test walking 1,713 → 1,714 px).
- **Never worse than the best available choice.** At every model event the
  sweep re-prices the incumbent and every legal count; the published page rises
  only when every candidate is at least as bad — held across the counterexample
  fixtures and a seeded randomized sweep, whose trial 9 contains exactly such an
  unavoidable rise.
- **Strict monotonicity where no undodgeable re-chunk exists** — the equal,
  deep-branch, nine-root and twelve-root fixtures — probed at integer pixels on
  both sides of every model event. Bands publish the exact tenth that earns
  them, so no window exists in which a superseded plan is still on screen: a
  band start *is* a model event, never a rounded-up one.

## Consequences

- Status and reason churn cannot move a root; topology, view controls, reason-cap
  configuration and viewport capacity can.
- Width is spent only in useful quanta. Some responsive rows intentionally retain
  an empty track because the next usable nested column needs two or more.
- A high reason budget gives a reason-capable topology more influence without the
  unstable alternative of counting live reasons.
- Mixed levels of chips and boxes gain nested columns without turning every chip into
  a grid cell.
- Poll payload is proportional to roots plus actual plan changes, rather than roots
  multiplied by 32.
- The `/little-sister` reservation still costs one namespace; a chip still trades
  at-a-glance quiet reason text for density; both keep their original fallbacks.
- The first look pays: measured on one deployment's tree at 1,280 pixels, the wall
  priced by its first look is 3.4 screens where pricing every node open makes it 4.1.
- Known and deliberate: a level nobody speaks for is priced as full box-and-reason
  hosts, though the density draws its quiet leaves as chips, so the model overestimates
  its height and can spend width the paint gains little from. That is the stability
  trade decided above — a chip drawn by a status must not move cards — and it is
  recorded rather than tuned.

## Alternatives considered

- **Equal-height uniform tiles** — maximal stability and balance, but wastes space
  in the interactive overview. It remains a possible fixed-geometry kiosk design.
- **CSS columns, masonry or dense packing** — closes holes but makes position depend
  on live height, violating the stable-position rule.
- **Live reason counts or browser-measured heights** — match one paint precisely and
  make a status poll move cards. Rejected at the input boundary.
- **Visible node count plus a 16-node entry price and maximum branch factor** —
  deterministic but discontinuous at 16/17, blind to reason-cap configuration, and
  unable to say which nesting widths are useful. This is the superseded ADR-0024
  allocation.
- **A `wide` or `weight` hint in `nodes.yaml`** — stable but couples deployment
  metadata to presentation and ages as a check's topology changes. The first look's
  keys cross that line on purpose: they are the web page's settings, not metadata on
  the node (ADR-0128 decision 5).
- **One grid item per chip** — opens mixed levels but destroys the compact wrapping
  run. The full-row chip-run wrapper preserves both properties.
