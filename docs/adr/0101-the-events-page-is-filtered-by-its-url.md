# ADR-0101 — The Events page is filtered by its URL

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) (the window
  as a URL writes it, and the bar that names and moves it, which this page shares),
  [ADR-0038](0038-declarative-action-list.md) (decision 6, `under` compared
  segment-wise), [ADR-0032](0032-status-contribution-boundary.md) (rule 5, a
  transition held back names the rule that held it),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (the marker, and whether to
  hide what it marks), [ADR-0083](0083-a-node-may-wait-before-it-escalates.md)
  (damping marks a transition too), [ADR-0039](0039-status-rollup-semantics.md) (the
  codes that carry a rank), [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)
  (the log survives a restart), [ADR-0029](0029-per-user-presentation-preferences.md)
  (the status page's switches, remembered per browser),
  [ADR-0048](0048-an-assembled-content-security-policy.md) (a switch submits its form
  without an inline handler), [ADR-0109](0109-a-node-says-its-children-are-complete.md)
  (decision 5, a removal's row, which the third switch group hides)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`/events` is the transition log, newest first: every change of a node's own status the
bounded log keeps, a thousand by default, as one long colored table, and nothing to
narrow it with. An outage among hundreds of unrelated transitions is found by scrolling
and reading paths; the aspects of one host failing together repeat one line down the
page; and nothing says whether the log still reaches back to the evening one asks about,
so a quiet stretch and a lost one look alike.

Transitions a rule held back — maintenance, a dependency shield, damping — are shown and
marked with the rule, because they are what makes *did it break during the window?*
answerable (ADR-0032 rule 5). They share the bounded log with everything else, and a
long pin over a flapping check fills it (ADR-0041).

The Series view already writes a window into its URL and has a bar that names and moves
it (ADR-0098). The log is a sequence in time as well.

## Decision

### 1. The filters are the page's URL, and nothing remembers them

`/events?under=/hosts/nas&words=disk+full&status=error&status=warn&held=no&from=now-6h`
is a link that can be bookmarked and handed on, and the server draws the page it names.
The switches submit their form when they change, as the status page's do (ADR-0048); the
two fields submit on Enter, which presses a default button kept out of sight and out of
the tab order, and a browser without script has an Apply button. Nothing is remembered,
unlike the status page's switches (ADR-0029): `/events` without parameters is always the
whole log, because a filter that outlived its question would make the next visit look
emptier than the log is. A value the page cannot read is answered `400`, naming the
parameter and what it takes: a `status`, `held` or `cause` that is not one of its words,
or a window ADR-0098 decision 1 refuses.

### 2. `under` is a node and everything beneath it; `words` are found in the reason

`under` is a node path compared segment-wise, as an action's is (ADR-0038 decision 6):
`/hosts/nas` holds `/hosts/nas` and `/hosts/nas/disk` and never `/hosts/nas2`; its
leading `/` may be left out, and `/` is every node. It is matched against the path an
event was recorded under, so a node removed since is found as well; `/` filters nothing.
`words` holds where each of its words is found somewhere in the event's reason, in any
order and ignoring case: `disk full` finds *Disk nearly full* and *full: /dev/disk2*.
They are two fields because they are two questions — one box would find `nas` in every
reason that mentions the NAS, and a reason's words in the paths.

### 3. A switch per status, one each for reached and held back, and three by cause

Five switches filter by the status an event moved to, the word and the color its row
shows: *error*, *warn*, *ok*, *maintenance* and *undefined*, all on by default, and
`status=` names the ones that are on. After a divider, in neutral ink, two more filter
by whether a rule held the transition back: *reached* (`held=no`) and *held back*
(`held=yes`), both on by default. With *held back* off the page shows what reached
anybody; with *reached* off, only what a rule withheld — in a maintenance window, the
answer to *did it break?* The divider is there because *maintenance* is two things on
this page, a status an event moved to and a rule a chip names, and turning off the one
does not hide the other. A group with every switch on, or with none, filters nothing,
is drawn with every switch on and is written into no link the page draws: a filter that
excludes every event is not a question anybody asks.

Held-back rows are shown by default. Whether the log should keep them at all, or keep
them apart, is the question retention answers, and hiding them here would not stop them
from pushing the rows one wants out of the bounded log.

A third group, `cause`, stands in neutral ink beside *reached* and *held back* and
filters by what wrote a row ([ADR-0109](0109-a-node-says-its-children-are-complete.md)
decision 5): *readings*, *pins* and *removals* — a check's reading; an admin's pin, set,
edited or ended, a node's or a line's; or a node that left the tree. A row that says no
cause, from a log written before a row did, is a reading's, as it is drawn.
`cause=reading&cause=pin` hides the removals, and the group follows the rule for every
switch on or none.

### 4. The window and its bar are the Series view's

`from` and `to` are read as ADR-0098 decision 1 reads them, and the bar above the table
is the Series view's (decision 3): the window named — *Last 6 hours · 14:45 – 20:45
CEST*, or *Everything kept* and the log's two ends — the presets up to the first that
reaches back past the oldest event kept, *all kept*, and the four moves, *earlier* and
*later* paging through the log half a window at a time. An event is in the window when
its time is, ends included. Every link the bar draws keeps the other filters, and the
filter form keeps the window. One builder and one partial draw the bar on both pages,
and the filters stand in view with it while the table scrolls.

### 5. A line says how many match, and an empty table says which empty it is

Beneath the bar, one line: *12 of 340 events match* where anything besides the window is
set, *340 events* where nothing is, its words agreeing with its numbers — *1 event*, *1
of 3 events matches*. The counts are exact — every event the log keeps is counted, and
every match is listed. Where the window starts before the oldest event kept, the line
adds *the log reaches back to 2026-09-26 17:00*, so a quiet stretch is not taken for a
lost one. An empty table says which empty it is: *No events yet* for an empty log, which
has neither filters nor a bar; *No events in this window* where the log holds none
there, the line counting *0 events*; and, where the filters left none, *None of the 340
events in this window match* — or *The only event in this window does not match*, for
one. A *reset* link to `/events` stands beside the line whenever anything is set.

## Consequences

- **ADR-0098 decisions 2 and 3 are rewritten in place**, since the record has not
  shipped: the window and its bar belong to the Series view and to this page.
- **The parameters are a contract**, as the Series view's are: `under`, `words`,
  `status`, `held`, `cause`, `from` and `to` are read as written here, by a bookmark as
  by a link the page drew.
- **Retention stays open, and now alone**: what the log keeps, for how long, and whether
  held-back transitions share its bound.
- **Nothing moves on the JSON API**, which reads no events.

## Alternatives considered

- **One field for the path and the reason**: fewer controls, and matches across the two.
  **The node alone**: the words of an error stay unsearchable.
- **The status page's *hide ok* and *hide idle***: familiar words, and no way to single
  out one status. **A severity floor** — all, warn and worse, error only: maintenance
  and undefined carry no rank (ADR-0039), so the floor drops them or has to place them.
- **One *hide held back* switch**: the only switch in the row where on hides, and *held
  back only* out of reach. **Held back hidden by default**, which ADR-0041 found nearly
  free once the page could filter: it takes the decision retention owns, the hidden rows
  still fill the log, and a window where everything was held back opens empty.
- **Presets alone**: a second, poorer control for one idea, and a stretch in the past
  only by typing a URL. **Two fields for `from` and `to`**: precise, clumsy to explore
  with (ADR-0098), and a typo answered with a bare `400`.
- **Filters remembered per browser**, as the status page's are: the trap an empty result
  sets. **A bare count and one empty sentence**: it cannot tell *the filters hid
  everything* from *nothing happened*.
- **Rows that share a moment, grouped**: a shared moment is not a shared cause, and
  `under` already gathers a host's rows; every row stays its own.

