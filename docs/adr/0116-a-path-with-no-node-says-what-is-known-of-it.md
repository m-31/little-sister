# ADR-0116 — A path with no node has one page, and it says what is known of the path

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0109](0109-a-node-says-its-children-are-complete.md) (a node its
  check no longer returns is removed; decision 4, its pins stay; decision 5, its
  removal is an event), [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md)
  (decision 3: a node's views, each a route of its own),
  [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) (decision 7:
  Copy is one of them),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (a pin is one block,
  edited where it is stated),
  [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md) (the Events page narrowed
  to a path), [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md)
  (decision 4: the readings kept of a removed subject are listed on its check's
  History), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (a page refreshes a part of
  itself)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node that says its children are complete loses the ones it stops returning
(ADR-0109). What is left of a removed node is in three places: its removal is a row on
the Events page, a pin held against it is suspended on the Maintenance page, and the
readings its check keeps of it are on the History of the node the check is mounted on.
Its own address knew none of them. `/status/<path>` answered `200` with *No such
branch* beneath the Status and History tabs of a node that was not there, `/history/<path>`
said the same, `/series/<path>` was a bare `404`, `/copy/<path>` a `404` that said
*No such node* and nothing of the node, and a path nothing ever stood at was answered
exactly like one whose node left a minute ago. A reader who followed a
bookmark, a link in a ticket or a row of the log arrived at a page that could say only
that they were wrong to come.

ADR-0109 left this open: *a removed node's own pages, by its path* was among its
alternatives, set aside because the kept readings do not remember the path they stood
on, and such a page said that there is no such node.

## Decision

1. **An address no node stands at is a `404`, with one page.** `/status/<path>`,
   `/series/<path>`, `/history/<path>` and `/copy/<path>` answer it alike: the same
   page under the breadcrumb, which says where the path would stand and opens what
   stands above it, and no view tabs, there being no node to have views. A line asked
   of such a path, `/copy/<path>?reason=<slug>`, is answered the same: there is no
   node to have lines. The JSON read of `/status` is unchanged — it answered `404`
   already.
2. **The part an open Status page refreshes is still answered `200`**, and says what
   the page says. A page that was a node's when it loaded asks for that part every
   few seconds; a node that leaves and returns under it shows as gone and as back,
   and never as a refresh that failed.
3. **The page says what the event log and the pins know of the path, and no more.**
   - Where the last event the log holds at the path is its removal: *removed*, when,
     and the sentence the removal was logged with, with a link to the Events page
     narrowed to the path. Where the log holds other events of it — a node no check
     has written yet since the start — that it is not reported at present, and the
     same link. Where it holds none, that nothing is recorded of it.
   - Every pin held against the path or beneath it, as the Maintenance page states a
     suspended pin, each under the path it is held against, with *Edit* and *Clear*
     for an admin. A write from there comes back to the page.
   - The nearest path above it that a node stands at, with that node's Status, its
     History and, where it has one, its Series view — and, where the page says
     *removed*, that readings kept of a removed subject are listed on its History:
     of a path nothing is recorded of, the page promises no readings. Where no node
     stands above, the first level.
4. **Nothing is stored for it.** The kept readings are still not found by path: the
   page sends a reader to where they are listed and does not list them.
5. **Events and Maintenance write a path with no node as text**, as before: a link
   there would open this page, which says less than the row it was followed from.

## Consequences

- A link to a removed node is answered with a `404` where it was a `200`. A monitor
  that watched such an address for a `200` now sees the removal; the page it gets is
  a whole page, with the navigation.
- The page is not polled: an editor of a pin may be open in it. A node that returns
  is a reload away, and a Status page that was open when the node left shows the
  return by itself (decision 2).
- A sentence a refused write flashes is shown on the page, as on any node's.
- The Maintenance page's wording for a suspended pin is one macro
  (`_pin_sections.html`), used by both pages.
- What the page says of a removal lasts as long as the log holds the row; after that
  a removed node's path reads as one nothing is recorded of, unless a pin is held
  against it.

## Alternatives considered

- **`200`, as it was.** Nothing breaks, and an address that names nothing goes on
  answering like one that does: a link checker and a reader's own bookmarks cannot
  tell.
- **`410 Gone` for a removed node, `404` for the rest.** The log is bounded, so a
  removed node's address would turn from `410` to `404` on a day nothing happened,
  and a node that returns from `410` to `200`: *gone* promises more than is known.
- **A `404` for the refreshed part too.** The open page's script would count it as a
  failed refresh and say that the page is stale, of a tree that answered.
- **The tabs kept, each view saying what it can.** Four pages with one thing to say,
  and tabs that lead from one to the next of them.
- **The Copy address keeping a page of its own**: *No such node*, in the band of the
  node with its tabs. It was the one address of the four that knew nothing of the
  path, and two of its tabs led to the page that does.
- **The kept readings listed on the page.** Each reading would need the path it stood
  on: a stored key (ADR-0109's alternative), for a list its check's History has.
- **Links from Events and Maintenance to the page.** Every removed row would lead to a
  page that repeats it.
