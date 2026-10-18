# ADR-0019 — Inspection popover (hover card)

- **Status:** Accepted
- **Date:** 2026-10-18 (accepted 2026-06-27)
- **Related:** [ADR-0017](0017-node-title.md) (`title`) and
  [ADR-0012](0012-node-metadata.md) (`about`) — the fields the card shows;
  [ADR-0018](0018-markdown-rendering.md) (the card injects server-rendered Markdown);
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the ~10s grid-fragment
  poll the card rides in);
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (the tree: a
  click opens or closes a node, decision 11, and a node's page shows its `about` open,
  decision 8); [ADR-0029](0029-per-user-presentation-preferences.md) (`inspection_card`,
  the look that says whether the card opens).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
On the dashboard a node surfaced its `description` + `about` only through the native
browser **`title=` tooltip**: one line of **raw** text (no Markdown — you see the `**`),
no interaction (can't select or copy), and it vanishes as the pointer moves. Now that
node text is Markdown ([ADR-0018](0018-markdown-rendering.md)) and `title` / `about` /
`description` are all authored fields, we want a richer **inspection popover** — a small
HTML hover card that shows the node's rendered metadata beside the trigger and that you
can move into to read or copy, without leaving the dashboard.

The card's content is the node's **metadata, not its state**: `title` / `about` are
seeded at startup (`nodes.yaml` > inline check) or stated by the run that names a node,
and do not change as its status does. The live status / reasons already sit on the chip
or the head and on the detail page. So the popover needs no live data — which shapes the
delivery decision below.

The wall is a tree
([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)): a plain
click on a node opens or closes it in place, so a card that opened wherever the pointer
rested opened on the way to every click. And an `about` can be long: on one deployment a
type's documentation made a card 1,920 pixels tall, 387 with its first paragraph.

## Decision
A **custom, client-side hover card fed by a map that rides in the polled fragment** — no
new endpoint.

1. **Content — the node's name and title, and the first block of its `about`.** The card
   says the node's name and **`title`** as its head shows them, and the first block of
   its **`about`**, whatever that block is (`render.first_block`), as server-rendered
   Markdown ([ADR-0018](0018-markdown-rendering.md)), with a line beneath counting the
   blocks after it and a link to the node's page, where the whole `about` stands open
   (ADR-0127 decision 8). It does **not** repeat the live code / reasons — the chip or
   head under the pointer shows the node's state, and the detail view its reasons — nor
   the leaf `description` (that stays on the detail page). A node with neither field
   gets **no** card, and a node's page's own head has none: its `about` stands open in
   the band above it.

2. **Delivery — a map in the polled fragment, rendered client-side.** The wall's
   fragment carries a **path-keyed map** of each node's first `about` block, already
   rendered, and the count of the blocks after it; the name and title come from the
   node's own head, which every node's box carries, open or closed. A small script reads
   the map again after every ~10s `#status-grid` swap, so a node a run names after the
   load has its card and an `about` changed in the configuration is current. **No
   per-hover request, no new route**: the script binds once via **event delegation** on
   the stable `#status-grid` parent, and every node element carries a **`data-path`** so
   the handler can resolve its metadata after any swap. On the recorded wall the map
   weighs 2,450 bytes of the fragment, 800 on the wire, measured with the rest of it.

3. **Behavior.** The card opens only on a **pause on a node's name** — a chip, the name
   in an open node's head or the status strip's — after about two thirds of a second,
   and never over a head's icons, a box's lines or a line's actions, nor during a click
   or in the 600 milliseconds after one, the hand that clicked being on the name it
   toggled. **Keyboard focus** on a name opens it at once. It **stays open** while the
   pointer crosses from the name into the card (read / copy values), and closes on
   leaving both, on blur, or on **Escape**. Positioned with **Floating UI** (CDN) beside
   the name — it **flips / shifts at viewport edges** and is not clipped by scroll
   containers. The node itself **stays a link** to its page, which a click with a
   modifier follows, while a plain click opens or closes it in place (ADR-0127 decision
   11). On **touch** a tap opens or closes the node and the card is not offered: a tap's
   compatibility events move the mouse onto the name it tapped only once the touch is
   lifted, in that moment, so touch never brings the card. A refresh keeps an open card
   on its node, and one that draws the name again during the pause opens the card on the
   name it drew. The help cursor marks the names that have a card — a chip, a head's
   name — and no other part of a head's row, which wears the pointer's, a click there
   opening or closing the node; a name whose node's pin is being written has none.
   **Accessible:** the name is focusable, the card is associated for assistive tech, and
   Escape dismisses.

4. **Replaces the `title=` tooltips.** The raw `title=` attributes carrying
   `description` + `about` on grid cards and nested nodes are **removed** (no double
   tooltip).

5. **Whether it opens at all is a look.** The presentation cookie's `inspection_card`,
   *on a pause* or *off* ([ADR-0029](0029-per-user-presentation-preferences.md)), its
   default the deployment's `settings.yaml`, and where that names none the library's,
   *off*: a browser that never chose draws no card, and no name wears the help cursor.
   *On a pause* is a viewer's choice in the settings menu, or a deployment's, and opens
   the card as above.

## Consequences
- One CDN dependency (Floating UI) + one small static JS file and CSS. **No server route
  and no API change**; the added payload is the metadata map, in the polled fragment,
  measured with the rest of it before the wall grows — a fetch on the first pause is the
  way back should it weigh too much.
- The card is **current**: the map rides in every refresh, so a node that first appears,
  or whose `about` changes, has its card from the next swap, not the next full load.
- A long `about` costs the card no height: its first block and a count stand in for it,
  and the node's page shows the whole.
- Consistent rich hover content (links, emphasis, lists, images) instead of a one-line
  raw tooltip; values can be selected and copied.

## Alternatives considered
- **Fetch a fragment per hover** (a `/inspect/<path>` endpoint). Cleaner for very large
  trees and always fresh — but adds a route and per-hover latency for data that changes
  only with the configuration or a run. Kept as the way back should the map weigh too
  much.
- **Each card's content inside its node in the fragment** (hidden, per node). It would
  re-render with every node and bloat each box; one map beside the tree carries only the
  first blocks.
- **The map once, with the page.** As first built: it survived the swaps, but a node a
  run named after the load had no card and a changed `about` stayed stale until a
  reload.
- **The card anywhere on a node's row**, which opened on the way to a click; **a card
  only on request**; **no card on the wall**; and **the node's state in the card**,
  which the chip or head under the pointer already shows.
- **Keep the native `title=` tooltip.** Zero code — but no Markdown, no interaction /
  copy, no styling: the exact limitation this record removes.
- **Bootstrap popovers** (Bootstrap JS is already loaded). Easy to stand up, but awkward
  to keep open on pointer-into-card and weaker at edge-flip / scroll-clip handling, with
  fussy HTML-content escaping. Floating UI fits an interactive card better; Bootstrap
  stays for the rest of the UI.