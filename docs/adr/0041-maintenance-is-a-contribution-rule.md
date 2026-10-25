# ADR-0041 — Maintenance is a contribution rule, not a value

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-08-02)
- **Related:** [ADR-0039](0039-status-rollup-semantics.md) (rule 3: what a parent
  does with a node in `MAINTENANCE`),
  [ADR-0032](0032-status-contribution-boundary.md) (the boundary this is
  the first real instance of — it named this implementation as its one deviation),
  [ADR-0036](0036-addressable-reasons.md) (the same move one level down, which landed
  first and left the transform in place), [ADR-0014](0014-maintenance-persistence.md)
  (the side-table this reads and the write path that fills it),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the liveness backstop
  this may not switch off), [ADR-0101](0101-the-events-page-is-filtered-by-its-url.md)
  (the `/events` filter, whose *held back* switch reads the marker),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (decisions 6 to 8 taken
  one level down, to a line's pin)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Pinning a node **wrote** `MAINTENANCE` into it and discarded the check's next reading:
`_apply_maintenance` called `node.update(MAINTENANCE, entry.reason)` and `upsert`
returned early while the flag was set.
[ADR-0032](0032-status-contribution-boundary.md) rule 3 says a policy is never
implemented by writing a different value into the tree — *a tree that has forgotten
what a check said cannot apply a policy that depends on it, cannot record an honest
history, and cannot compose two policies* — and named this as the one deviation in the
codebase.

It was not an abstract complaint. Three things followed from the write, and the third
was a live bug:

- While pinned, nobody could tell whether the thing being silenced was healthy or on
  fire. The dashboard showed the pin's own text where the reading used to be.
- The event log had nothing to say about a maintenance window, because `upsert`
  returned before emitting.
- **Clearing a pin left the node blank** — `_clear_node` dropped it to `UNDEFINED`
  with an empty reason list, because there was nothing left to restore — until the
  check next ran, which on the un-polled leaf page meant "until you reload".

There was also a **second deviation, and it was propping up the first**: `_is_stale`
exempted any pinned node, so a pinned check that died never escalated
([ADR-0032](0032-status-contribution-boundary.md) rule 6). It could not be removed on
its own — the stale degrade takes `worst_of(reading, WARN)`, `worst_of` knows only
`OK`/`WARN`/`ERROR`, and a node holding a written-in `MAINTENANCE` reached it and
raised.

## Decision

1. **A pin is recorded, never written.** `_apply_maintenance` stores the side-table
   entry and marks the node; the tree keeps the check's reading, and the check keeps
   writing it. `upsert` has no maintenance branch at all.
2. **`MAINTENANCE` is derived at the snapshot**, in `_own_code` — the same transform
   ADR-0036 put there for entry pins, with the node pin as its first arm. One
   evaluation point, two grains of the same rule.
3. **The snapshot carries the reading beside the derived value.** `own_code` is what
   the node shows; **`reported_code`** is what the check said. Once `own_code` became
   derived, the raw answer had nowhere to live, and rule 5 — a transformed contribution
   is visible and attributable — needs it: a card says `maintenance · error`, not just
   blue. The JSON field rides the client-contract round, where
   [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) publishes it as
   `reported`, so a client can say the same thing the card does.
4. **Clearing restores nothing, because nothing was destroyed.** Releasing a pin lets
   the node show what it has been holding all along, immediately.
5. **The freshness backstop applies under a pin.** The `_is_stale` exemption is gone,
   replaced by a guard on the *code* (`UNDEFINED` or `MAINTENANCE` have no severity to
   degrade) — which also closes the same latent crash for a check that reports
   `MAINTENANCE` itself. A pinned check that stops running escalates exactly as any
   other does, taking the worst of its reading and `WARN`, so a known `ERROR` is never
   softened because we stopped watching.
6. **Transitions under a pin are recorded and marked.** `Event.suppressed_by` names
   the rule that kept a transition from reaching anybody — `maintenance` here — and is
   empty otherwise. One sentence defines it, and it is worth holding the field to:
   *an unmarked event is one that alarmed; a marked one is one that didn't.* It is a
   **name, not a boolean**: the aggregation clamp, the dependency shield and the
   damping counter each withhold transitions too, and four booleans would be four
   spellings of one property. Under a pin, a transition is marked where the node did
   not show it, also where only some of its lines are pinned
   ([ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) decision 2), and one
   run may write the node's own change beside it.
7. **History counts only what the node showed.** A marked transition does not start a
   period, so a maintenance window stays one period rather than being chopped into
   `ERROR` stretches no surface ever displayed. The marked events remain in the log,
   which is where *did it break during the window?* is answered — a question that had
   no answer at all before.
8. **Setting and clearing a pin stay transitions** of what the node shows (`old` = what
   it was contributing, `new` = `MAINTENANCE`, and the reverse on release), and are
   never marked: they are what everybody saw. A line's pin is a transition of what the
   node shows, as a node's is, where it changes that (ADR-0107 decision 1), and a pin's
   `old` and `new` are what the node showed, which with a line pinned is not what its
   check reported.

Default behavior is unchanged where it was correct: a pinned node still contributes
nothing to its parent, this record changes nothing in the file the pins are kept in, and
every value of `own_code` and `code` the API published before is the value it publishes
now.

## Consequences

- The two deviations ADR-0032 recorded are closed, and its text is corrected in place.
- A pinned node's `reasons` in the JSON envelope now carry the check's reading instead
  of a copy of the pin's text, which has always also been in `maintenance_details`.
  No schema change, and no code value moved.
- **Event volume under a long pin is real and is not this record's problem.** A
  flapping check under a week-long pin can wrap the bounded event deque. An *unpinned*
  flapper does exactly the same thing today; pins merely used to mask it. It belongs to
  **retention and event filtering**, which this makes more urgent — and with the marker
  present, defaulting `/events` to hide suppressed transitions is nearly free. `/events`
  is filtered ([ADR-0101](0101-the-events-page-is-filtered-by-its-url.md) decision 3):
  its *held back* switch leaves out the transitions a rule held back, this marker's
  among them. They stay shown by default — hiding them would not keep them from filling
  the bounded log — so the default that hides them is left to retention.
- The marker is the first member of a vocabulary the remaining policies will join.

## Alternatives considered

- **Stash the pre-pin reading and restore it on clear.** Fixes the visible bug in five
  lines and nothing else: the node still could not say what it was silencing, the
  event log would still be silent, and the stash would be deleted by this change.
- **`Event.maintenance: bool`.** Smaller today, wrong by the third policy.
- **A separate administrative event kind**, so pin and clear are not status
  transitions. Cleaner in the abstract, and it forces `history()` to decide whether a
  pinned span exists at all — a question not worth opening inside the risky change.
