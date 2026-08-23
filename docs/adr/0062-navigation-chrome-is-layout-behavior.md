# ADR-0062 — Navigation chrome is layout behavior, not a preference

- **Status:** Accepted
- **Date:** 2026-08-16
- **Related:** [ADR-0029](0029-per-user-presentation-preferences.md) (the theme and
  layout cookie), [ADR-0019](0019-inspection-popover.md) (viewport-positioned
  overlays), [ADR-0036](0036-addressable-reasons.md) (in-page reason anchors)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The rail and top-bar layouts put the same navigation in two arrangements. On a long
dashboard both used to leave the viewport with the document, so reaching another
section meant returning to the top of the tree. Keeping the navigation in view opens
two product questions that CSS alone cannot answer:

1. Is pinned chrome another viewer choice in ADR-0029's presentation cookie?
2. Should a short window abandon pinning when the navigation itself is taller than
   the viewport?

There are also two implementation boundaries. The pages retain useful server-rendered
behavior without JavaScript, including native maintenance disclosures and explicit
form submission paths. And the window is deliberately the document scroll container:
the maintenance and inspection popovers are positioned in viewport coordinates, while
reason links use ordinary document anchors.

## Decision

### Pinning belongs to each interactive layout

The bar is sticky in both interactive layouts, and the rail is sticky immediately
beneath it in the rail layout. Kiosk continues to render neither one.

This is **not** a new presentation preference. ADR-0029's `layout` choice already says
which navigation arrangement the viewer wants; whether that arrangement remains
reachable while its page scrolls is behavior of the arrangement, like its breakpoint
or keyboard order. The presentation cookie therefore gains no `pinned_chrome` key and
the settings menu gains no switch.

### A short window keeps the chrome pinned and scrolls the bounded child

Pinning does not turn off at a height breakpoint. That would make navigation disappear
on exactly the windows where returning through a long page is hardest, and would make
the same layout change behavior at a boundary unrelated to the viewer's choice.

Instead, the constrained part becomes its own vertical scrollport:

- a tall rail scrolls below the bar;
- an expanded narrow top bar keeps its first row fixed and scrolls its section list;
  and
- the settings dropdown scrolls within the viewport budget below that first row.

The window remains the document scroll container. The page is not translated into a
second application scrollport, and kiosk remains untouched.

### JavaScript refines geometry; it does not make the clearance exist

CSS seeds the bar-height and first-row-budget tokens with safe estimates. That keeps
the rail's first control and in-page anchors clear when scripts are unavailable or
have not run yet. `rail.js` observes the rendered border box and replaces the
estimates with the exact bar height and the non-section footprint of its first row,
including changes caused by padding, fonts, or an expanded top bar. Whether the
section list has wrapped is determined from its position below the settings row, not
from a JavaScript copy of the stylesheet's breakpoint.

### Viewport chrome sits above page panels and below viewport overlays

Content-anchored reason editors slide behind the pinned bar as their document content
scrolls. Viewport-positioned maintenance and inspection popovers remain above it. The
stacking order therefore follows ownership rather than assigning every open panel a
higher rung than navigation.

## Consequences

- No cookie, server state, route, JSON contract, or kiosk markup changes.
- The scriptless path uses a conservative offset rather than exact measurement, but
  its controls and anchors remain reachable; enhancement removes the small estimate.
- Short interactive windows can have two scrollable areas — the document and the one
  open navigation surface — but each has a visible boundary and only the constrained
  child scrolls.
- Browser boundary tests must cover the scriptless fallback, the expanded top-bar
  settings menu, and the stacking boundary. Each chrome test skips only when its
  exact Bootstrap CDN prerequisite is directly unavailable; an unrelated page
  resource cannot stand in for that probe. The stable-flow boundary tests have no
  Bootstrap prerequisite: they abort every jsDelivr request themselves and compare
  a consistently unstyled render rather than racing the remote stylesheet.

## Alternatives considered

- **A `pinned_chrome` presentation-cookie key.** Rejected: it makes basic navigation
  reachability optional, adds a setting whose value must be explained per layout, and
  gives kiosk a meaningless fourth combination.
- **Unpin below a height breakpoint.** Rejected: a short window would lose the benefit
  precisely when the document is hardest to traverse, and font or browser chrome
  changes could silently cross the behavior boundary.
- **Measure everything in JavaScript.** Rejected: the server-rendered surface would
  regress to an overlapping rail and obscured anchors whenever scripts are disabled or
  fail before the measurement runs.
- **Make the page, rather than the window, the scroll container.** Rejected: it changes
  the coordinate system under ADR-0019's viewport-positioned overlays and turns a
  navigation correction into a page-shell rewrite.
