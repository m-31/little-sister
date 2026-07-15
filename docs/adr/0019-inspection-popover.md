# ADR-0019 — Inspection popover (hover card)

- **Status:** Accepted
- **Date:** 2026-06-26
- **Related:** [ADR-0017](0017-node-title.md) (`title`) and [ADR-0012](0012-node-metadata.md)
  (`about`) — the fields the card shows;
  [ADR-0018](0018-markdown-rendering.md) (the card injects server-rendered Markdown);
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the ~10s grid-fragment
  poll the card must coexist with).
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-06-26):** the card shows **`title` + `about` only**. A leaf's
> `description` was dropped from it — it stays on the leaf detail page — so a node gets a
> card when it has a `title` or an `about`. The decision text below reads `title` / `about`
> accordingly.

## Context
On the dashboard a node surfaces its `description` + `about` only through the native
browser **`title=` tooltip**: one line of **raw** text (no Markdown — you see the `**`),
no interaction (can't select or copy), and it vanishes as the pointer moves. Now that
node text is Markdown ([ADR-0018](0018-markdown-rendering.md)) and `title` / `about` /
`description` are all authored fields, we want a richer **inspection popover** — a small
HTML hover card that shows the node's rendered metadata beside the trigger and that you
can move into to read or copy, without leaving the dashboard.

The card's content is **static**: `title` / `about` are seeded at startup
(`nodes.yaml` > inline check) and don't change as checks run. The live status / reasons
already sit on the card face and the detail page. So the popover needs no live data —
which shapes the delivery decision below.

## Decision
A **custom, client-side hover card fed by preloaded static metadata** — no new endpoint.

1. **Content — the static metadata only.** The card shows a node's **`title`** and
   **`about`**, each as server-rendered Markdown ([ADR-0018](0018-markdown-rendering.md)).
   It does **not** repeat the live code / reasons (those are on the card and the detail
   view), nor the leaf `description` (that stays on the detail page). A node with neither
   field gets **no** card.

2. **Delivery — preloaded, rendered client-side.** The dashboard page embeds a
   **path-keyed map of the already-rendered HTML** for these fields (a
   `<script type="application/json">` block), built once at page render from the snapshot
   for every in-view node that has metadata. A small script reads the map by node path and
   injects the matching HTML into the card. **No per-hover request, no new route.** Because
   the map ships with the **initial page** (not the polled grid fragment), it **survives the
   ~10s `#status-grid` `innerHTML` swaps**; the script binds once via **event delegation** on
   the stable `#status-grid` parent, and every node element carries a **`data-path`** so the
   handler can resolve its metadata after any swap.

3. **Behavior (the agreed spec).** Opens on **hover or keyboard focus** after a short delay;
   **stays open** while the pointer crosses from trigger into the card (read / copy values);
   closes on mouse-leave of both, blur, or **Escape**. Positioned with **Floating UI** (CDN)
   beside the trigger — **flips / shifts at viewport edges** and is not clipped by scroll
   containers. The node itself **stays a link** to its detail view. On **touch**, a tap opens
   the card (a second tap on the node follows the link). **Accessible:** the trigger is
   focusable, the card is associated for assistive tech, and Escape dismisses.

4. **Replaces the `title=` tooltips.** The raw `title=` attributes carrying
   `description` + `about` on grid cards and nested nodes are **removed** (no double tooltip).

## Consequences
- One CDN dependency (Floating UI) + one small static JS file and CSS. **No server route
  and no API change**; the only added payload is the metadata map, and only on the full page
  (not the 10s poll).
- The card is **static**: a node that first appears — or whose `title` / `about`
  changes — *after* page load won't show (updated) card content until the next
  full load. Acceptable for seeded metadata. If it ever needs to live-update, the poll
  fragment could carry a refreshed map (noted, not done).
- Slightly larger initial HTML (rendered metadata for nodes that have it); trivial at
  homelab scale, and absent from the polled fragment.
- Consistent rich hover content (links, emphasis, lists, images) instead of a one-line raw
  tooltip; values can be selected and copied.

## Alternatives considered
- **Fetch a fragment per hover** (a `/inspect/<path>` endpoint). Cleaner for very large trees
  and always fresh — but adds a route and per-hover latency for data that is **static**.
  Rejected: preloading is simpler and the content doesn't change.
- **Embed each card's content inside the grid fragment** (hidden, per node). Then it
  re-renders every 10s and the card must survive each swap, and it bloats the **polled**
  payload. Rejected: delivering the static map **once, outside** the polled grid is leaner
  and more robust.
- **Keep the native `title=` tooltip.** Zero code — but no Markdown, no interaction / copy,
  no styling: the exact limitation this slice removes.
- **Bootstrap popovers** (Bootstrap JS is already loaded). Easy to stand up, but awkward to
  keep open on pointer-into-card and weaker at edge-flip / scroll-clip handling, with fussy
  HTML-content escaping. Floating UI fits an interactive card better; Bootstrap stays for the
  rest of the UI.
