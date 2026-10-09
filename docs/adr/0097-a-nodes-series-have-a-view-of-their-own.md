# ADR-0097 — A node's series have a view of their own, beside its status and its history

- **Status:** Accepted
- **Date:** 2026-10-10 (accepted 2026-09-27)
- **Related:** [ADR-0092](0092-a-check-declares-its-measures.md) (decisions 6 and 7,
  which this amends), [ADR-0096](0096-a-measure-names-its-node-and-its-things.md) (the
  curves, and the node each stands on),
  [ADR-0044](0044-run-facts-on-the-node.md) (the measurement a shared mount withholds),
  [ADR-0016](0016-node-addressing.md) (the path every view is addressed by),
  [ADR-0008](0008-json-output-api.md) (the status routes' JSON),
  [ADR-0094](0094-a-restart-is-no-transition.md) decision 5 (a node that declares
  nothing of its own has no periods),
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (the node that
  stands for a subject and shows its series, and the `series` read on the API),
  [ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md) (that read, built at
  this view's URL, and the credential its two routes choose)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0092](0092-a-check-declares-its-measures.md) decision 6 put a subject's series on
the node that stands for it: every curve, and the newest readings as a table, in the
node's facts. Once the library's metric types declare what they grade
([ADR-0096](0096-a-measure-names-its-node-and-its-things.md)), a Mac watching three
processes would carry ten curves and two tables beneath its grid — its host metrics and
its memory check share the host's node — on a page some four thousand pixels tall, with
each curve far from the aspect it grades. It would in fact carry none: two checks on one
mount withhold the node's subject and record
([ADR-0044](0044-run-facts-on-the-node.md) decision 1), and decision 6 reads the
subject off the node. And the things worth seeing side by side are often not on one
node: a NAS whose host metrics and whose hardware check are sibling mounts, a host with
its website mounted beneath it.

Mocked with the real templates over a deployment's kept readings, three placements were
compared: every curve on the node's page, a view of its own beside the node's status and
its history, and that view with a sparkline of every curve on the node's page. The view
of its own read best. A curve seen small, and the number on the Series tab, are
[ADR-0114](0114-a-curve-seen-small-and-the-series-tabs-count.md)'s.

## Decision

### 1. `/series/<path>` shows every curve at or beneath a node

A node's **Series** view is a route of its own, addressed by the node's path as
`/history/<path>` is. It carries every curve that stands at or beneath the node — kept
by a check mounted there or beneath, or above it with a measure naming a node there —
each under the node it stands on
([ADR-0096](0096-a-measure-names-its-node-and-its-things.md) decision 1), in the tree's
order, each group headed by that node's status and sentence as they are now and
opening its Status view. All of it stands on one time axis — the window the view's URL
names, where it names one ([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md)),
and otherwise from the
oldest reading the series its curves are drawn from keep to the newest, so that curves
read by different checks at different moments stand one above the other; a check above
the node that draws nothing there does not stretch it. Each curve breaks where its own
check's readings stand further apart than that check's period allows
([ADR-0092](0092-a-check-declares-its-measures.md) decision 5's tolerance), not its
node's: a node two checks share carries the period of whichever wrote it last. Beneath
the curves come the
newest `reading_cap` readings of each series they were drawn from, folded, with the
History page for the rest. A series that
declares no measure — a file's modification times — is named with a link to its History
page, where its readings are. The view is not polled: it is read, as History is.

A check's series are found through the check, not through the node: every check mounted
at or beneath the path that keeps a series, with the subject it placed its reading
against. So a shared mount shows both checks' series, and what ADR-0044 withholds — the
one subject and record a last writer would claim for both — stays withheld. Each
series is shown on the node that stands for its subject where one does
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 4), a
subject that rides on a line among them.

The `series` read on the API is this view's URL answered as JSON where `Accept` asks
for it ([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 6,
built by [ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md)).

### 2. A node's page shows the curves that stand on it

A node's Status view carries the curves drawn on that node — an aspect's own, or a
check's own node's for a measure that names no other — beside its status, its reasons
and its configuration, and no readings table. `reading_cap` counts the rows the Series
view shows. History keeps every reading, as before.

### 3. The breadcrumb says where, the tabs say which view, the rail says which section

- The breadcrumb names the tree and the node's place in it — **`nodes`**, then a crumb
  for every segment — and is the same on every view. *Node* is the word the pages
  already use for what a path addresses, and it names the kind of thing rather than any
  deployment's: what the first level holds — hosts, teams, systems — is the deployment's
  to choose. Each crumb opens the same view of that ancestor, and `nodes` opens that
  view's root — from History, the overview; from Copy, the tree's document.
- A node's views are tabs beneath its title: **Status**; **Series** where a curve can
  stand at or beneath the node — a check keeps a series there or beneath it, or above
  it with a measure naming a node there — as the configuration says, so a tab does not
  come and go with the readings, and also on a node at or beneath which a series is
  shown on a subject's own node, or a curve of that series stands
  ([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 4): the
  tree says that, the configuration not knowing where a grading writes a subject's
  line, and it is never read from a reading's numbers; **History** on every node but
  the root; and **Copy** on every node, the root included, which hands the node over
  ([ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) decision
  7). The History page and the Copy page take the same title and tabs.
- The rail gains **Series** beside Status, lit on every Series view as Status is on
  every status page.
- The routes do not move: `/status/<path>`, `/series/<path>`, `/history/<path>`,
  `/copy/<path>`.
  `/status` is the JSON API's ([ADR-0008](0008-json-output-api.md)) and the client's,
  and a view named after the node's path would collide with a node named `series`.

### 4. The roots

- `/status` is the overview it is: every root node's card. Its title is `nodes`, and it
  has three tabs: Status, Series and Copy, which is the tree's document at `/copy`.
- `/series` is an index, not a page of curves: every node a series is kept on, grouped
  under its root node, with its status, the checks keeping it, what it draws, how many
  readings it holds and when the newest was taken. A node's name opens its Status page,
  and its row says in words where else it leads — its Series view where a curve stands
  at or beneath it, its History page — and a root appears once, its heading its own row
  ([ADR-0103](0103-the-series-index-says-where-each-link-leads.md)). Asked for JSON, the
  same URL answers the series read for the root
  ([ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md) decision 2), and its
  page stays this index.
- There is no `/history` root: the root declares nothing of its own and has no periods
  ([ADR-0094](0094-a-restart-is-no-transition.md) decision 5), and the instance's
  changes are the Events page.

## Consequences

- **ADR-0092 decisions 6 and 7 are amended**: the curves leave the subject's node for
  their own nodes and the Series view, and the readings table goes with them.
- **One route, two pages**: `/series` and `/series/<path>`. Each chooses its own
  credential, as `/status` does, and refuses both ways
  ([ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md) decision 8). The
  node's Time card loses its History button; the tab replaces it.
- **A subject that rides only on a line, and how a series of events is drawn**, are
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md)'s — and have a
  view to be shown in.
- **The Series view answers JSON as well as HTML.** The `series` read on the API is this
  view's URL where `Accept` asks for JSON, and `/series` answers the same way (decisions
  1 and 4).
- **A curve seen small on the index, and a count on the Series tab**, are
  [ADR-0114](0114-a-curve-seen-small-and-the-series-tabs-count.md)'s.

## Alternatives considered

- **Every curve on the node's page**, as decision 6 had it — a long page, curves far from
  their aspects, and nothing at all on a shared mount or across sibling mounts.
- **Sparklines on the node's page** — a glance at every curve, and a scale question of
  their own: from zero a flat line stays flat, from the lowest reading a tenth of a GiB of
  jitter reads as a swing.
- **A route per subject**, ADR-0092's rejected alternative — still rejected: a subject's
  identifier in the URL, outside the breadcrumb, the pins and maintenance. A view
  addressed by a node's path has none of that, and it joins what a subject cannot, a host
  and the website mounted beneath it.
- **`status` as the first crumb** — the section, the crumb and a tab would be one word for
  three things.
- **The instance's name as the first crumb** — telling where a deployment sets it, a
  hostname where it does not; a deployment's own name belongs to its brand.
- **Node-first routes** (`/nodes/<path>/series`) — every link, bookmark and API caller of
  `/status` would move.
- **A `/history` root** — it would restate the Events page.
