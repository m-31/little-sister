# ADR-0115 — A Copy document says where it is from, when it was made and since when

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0036](0036-addressable-reasons.md) (decision 12: a line is
  addressed by a query value, never by a path),
  [ADR-0099](0099-a-status-that-still-holds-says-since-when.md) (a status that still
  holds says since when), [ADR-0039](0039-status-rollup-semantics.md) (what a branch
  shows is what its nodes roll up to),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 5: a surface shows what a pin
  transforms), [ADR-0044](0044-run-facts-on-the-node.md) (decision 8: a branch's page
  states the node's own facts),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (a pin covers what is
  beneath it), [ADR-0027](0027-observation-timestamp-semantics.md) (no instant is
  invented), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (a reading
  past its tolerance counts degraded),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (decision 3: a node's
  views are tabs beneath its title)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A Copy document is what somebody pastes into a ticket, and whoever reads the ticket was
not standing in front of the page. Three things it needs were missing.

**It did not say where it was from or when.** The tree's document was an outline and
nothing else; a node's named its path and its observation. Neither said which
installation had seen this, at which address, or when the document was made — and the
instant a failure began was in a leaf's document only, so the tree's document listed
its findings and dated none.

**A branch's document was a leaf's.** The route answers for any node, and for a node
with nodes beneath it the formatter printed what a leaf has: the status its own check
reported. A host whose check grades its children and declares nothing itself read
*Reported: undefined*, with a full disk beneath it or with nothing wrong, and named
none of its children. A pinned container that no check writes read *Not yet observed*
and *the reported reading above is what the check measured*, of a node nothing
measures.

**The outline skipped what a branch has of its own.** It listed every leaf that is
not ok under the bare names of its ancestors. A pin on a container was not in it, so
what the pin silences read as alarming. A container with a status of its own above
healthy children — a gateway that itself answers 503, or one whose check has stopped,
which the tree shows as a warning — was not in it at all.

**And nothing led to a branch's document.** A leaf's page carried two buttons that
copied the leaf's. A branch's page carried none and no link, so its document was
reached by typing its address; and the Copy page, once reached, led nowhere: its
heading named a path.

And *Copy Rich HTML* copied Markdown wherever the instance is reached over plain
`http` by a host's name: the clipboard interface it writes through exists in a secure
context only, and a monitor inside a network is rarely served another way.

## Decision

### 1. Every document says where it is from and when it was made

Under its heading, a node's document and a line's carry two lines beneath the path,
and the tree's document opens with them:

- **Dashboard:** the address of the page the document was made from — the wall for
  the tree, the node's own page for a node, and that page with the line marked for a
  line. It is absolute, and it is the address the request came by, as a link back out
  of a ticket has to be: an instance opened through a tunnel names the tunnel.
- **As of:** the instant the document was made, in the document's clock with its
  offset. It is not the instant a button was pressed: a Copy page makes its document
  when it is opened, and the line says how old that is.

A caller with no request to take an address from — a fixture sheet, a test — passes
none, and the document claims none.

### 2. Every finding says since when

In an outline, a node that is listed says the status it shows and since when: *disk ⛔
— error since 2026-10-03 16:09:40 +02:00*. The instant is the beginning of the node's
period as its page states it
([ADR-0099](0099-a-status-that-still-holds-says-since-when.md)): *since before* where
the tree can only vouch for a bound, and with what began it where a pin did — *when its
maintenance ended*. A node the tree keeps no period of says nothing. A line carries no
instant: a line has no period of its own.

### 3. An outline says what a branch has of its own

A branch's line in an outline was its name. It now carries what the branch itself
holds, above everything beneath it: a pin on it, with who set it, until when and its
note; and a status of its own that is not ok, with its own lines. A reading of its own
that is past its tolerance is such a status — the tree counts it degraded
([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)) — and the line says
*stale*; a branch above a stale node leaves that word to the node. A branch that holds
any of these is listed whether or not anything beneath it is.

### 4. The tree's document has a head, and there is always one

*little-sister status*, with the cue of what the tree shows; the two lines of
decision 1; and a count — *Needs attention — 6 of 12 nodes: 2 error ⛔, 3 warn ⚠️, 1
maintenance 🛠️* — before the outline. A node is counted where it shows a status of its
own: a node with nothing beneath it, and a branch that declares a status or is pinned.
The count is the number of findings the outline lists. A tree with nothing to list
says *Nothing needs attention — all 12 nodes are ok.*, and that is a document too: a
state that is well is a state somebody documents.

A pin on the tree itself is not set from the wall, and one that stands is stated like
any other: in the head, above a count that says what it is silencing.

### 5. A branch's document hands over what is beneath it

For a node with nodes beneath it the document says, in this order:

- its path, and the two lines of decision 1;
- **Reported**, where the node declares a status of its own;
- **Shown as**, where it shows something else, with the reason: *error ⛔ — rolled up
  from the 3 nodes beneath it. It reports nothing of its own.*; under a pin, *a
  maintenance pin is in force on it and on the 2 nodes beneath it*, followed by the
  pin. The sentence names where the status comes from and claims nothing of each
  node: a pinned node, one that waits and one reached through a failing check count
  for nothing in what their branch shows
  ([ADR-0039](0039-status-rollup-semantics.md));
- its period and its observation, as far as it has them, and its run's facts. *Stale*
  is said of its own reading only;
- its own lines, if it has any;
- **Beneath it** — how many of the nodes beneath it need attention, and the outline of
  those, each with its lines and since when; or *nothing needs attention*; under a
  pin, what the pin is silencing;
- what its own run found and ran with.

Its heading carries the cue of what the node shows. A leaf's document is as it was,
with the two lines added.

### 6. A period is stated wherever there is one

A node that no check has written, and that is pinned, has a period: it has shown
*maintenance* since its pin. Its document states it, *Status maintenance since …*, and
so does its Time card, where both said *Not yet observed* and nothing else; and the
document says that no check has written the node, where it called the reading the pin
stands over a measurement. *Not yet observed* stays for a node with neither an
observation nor a period.

A branch's page draws its node's Time card where the node has a period, as it does
where the node has an observation, a report or a configuration. A pinned container
that nothing has written had no card: its page said who had silenced it and until
when, in the pin's block, and since when was said by its History and its document
alone. A container that nothing has written and that is not pinned declares nothing,
has no period, and has no card.

### 7. Copy is a view of its node

A node's views gain **Copy** beside Status, Series and History
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 3): a tab on
every view of every node, and on the root, whose Copy is the tree's document. The Copy
page stands in the node's band as the other views do: the breadcrumb says where, each
crumb opens the Copy page of that ancestor, and the Status tab is the way back to the
node's page. A line's page stands in its node's band. Beneath the band the page says
which of the four documents it holds: the tree's, a branch's, a node's or a line's.

The tab is the one way to a node's document. A leaf's page carried two buttons that
copied its document in place; it carries them no longer, and no Status page makes a
document. The second click buys what the buttons did not show: the document, before it
is copied.

A tab, because that is where a node's other views are. It is on a leaf and on a branch
alike, it needs no pointer over it to show, and it stands the same on a phone.

### 8. Copy Rich HTML has a second rung

Where the clipboard interface is missing, or refuses, the button copies through the
browser's copy event, which carries the rendered document and its Markdown as the two
members the interface would have written. Where the interface is missing nothing is
awaited before that copy: a browser lets a page copy only while it is answering the
click. Whether the two members were set is the event's to say — a browser that raises
none has copied the Markdown alone — and where this rung fails as well, the button
copies the Markdown and says so, as before.

## Consequences

- The tree's document reads the period of every node it lists, one read of the tree's
  history for each. It is made when its page is asked for and at no other time.
- An address the request came by is not a public one. An installation behind a proxy
  that does not forward its host writes the inner address into every document, as it
  does into a ticket's link back.
- A document for a tree that is well replaces the page's empty state.
- A leaf's document is made when its Copy page is asked for, as every other is; its
  page made one with every load. Copying a leaf takes a second click.
- The kiosk layout draws no band, and so no tab: a leaf's page there carried the two
  buttons, and now a document is reached by its address alone, as a branch's always
  was on that layout.
- A pinned container that nothing has written draws a Time card beneath its children:
  the pin's block above them says who silenced the node and until when, and the card
  says since when, where every other node's period is said.
- A snapshot says whether a node's own reading is the stale one (`own_stale`), beside
  `stale`, which says it of the node or of any node beneath it.
- The second rung rests on `document.execCommand`, which browsers keep and no longer
  recommend. It is the only way to the clipboard outside a secure context. The tests
  hold it in Chromium; that a copy is made while the click is answered is what
  Firefox and Safari ask as well, and neither is in the test set.

## Alternatives considered

- **A branch's document as the tree's outline from that node down.** One formatter and
  no new layout, and it drops the node's path, its times, its report and its
  configuration, which a host has; a healthy branch would have no document at all.
- **A branch's document with a count and no findings.** It says that something is
  wrong and sends the reader to each leaf for what.
- **The instant the button was pressed.** It reads as the more exact one and is the
  less true: what is copied was read when the page was made, and a stamp taken later
  would date old facts as new.
- **A configured public address.** The right address where the request's is not, and a
  setting no installation has today; the request's is what a ticket's link back
  already uses.
- **Removing *Copy Rich HTML*.** Every current browser writes HTML to the clipboard; the
  button failed for where it was served, not for what the browser could do.
- **A link in a branch's head**, in place of the tab. Smaller, and a way to a document
  that only a branch would have, beside the buttons only a leaf had.
- **The two buttons kept on a leaf's page**, beside its tab. One click from the page
  that shows the node; and the one page that offers its document twice, with the
  buttons standing between a status and the time and report that belong to it.
- **A pinned container's page left without a Time card.** Its pin's block says who and
  until when, and its History says since when; the node's own page would be the one
  surface of it that states no period where there is one.
