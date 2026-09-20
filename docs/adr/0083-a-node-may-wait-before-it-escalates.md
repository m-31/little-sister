# ADR-0083 — A node may wait before it escalates

- **Status:** Accepted
- **Date:** 2026-09-19
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (the contribution
  boundary this is the second rule at, and rules 5–7 which bind it),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up, unchanged),
  [ADR-0033](0033-budgeted-failure-retry.md) (the fast recheck, without which this
  trades false alarms for latency), [ADR-0041](0041-maintenance-is-a-contribution-rule.md)
  (the first rule at this boundary, and the derived-not-written precedent),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the freshness
  backstop this must not close), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (decision 2, which described this field before there was a rule that needed it),
  [ADR-0027](0027-observation-timestamp-semantics.md) (the reading, which is what
  the counter counts)
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — `Contribution`, from
  2.2.0.

## Context

**A single failed check is not proof.** Toggling the Wi-Fi on one machine took this
tree to `ERROR` and the client alarmed; every report was true and the attribution was
wrong. Two mechanisms answer that, and they answer different halves of it: a
dependency says *could we even have reached it*, and a counter says *has it failed
enough to believe*. This record is the second.

The objection to a counter is already written down: it pays for the quiet by delaying
every detection equally. That objection lands against damping **inside the check**,
where the leaf itself stays green and the operator reading its page is lied to.
Damping at the **boundary** is a different animal, and the difference is the whole of
why this is worth building: the leaf goes red at once and stays honest — its card, its
page and the event log all say so from the first failure — and what waits is only the
claim that everything above it is broken.

## Decision

### 1. The counter counts readings, and it counts what the check reported

A node publishes a worse code to its parent only after `escalate_after` **consecutive
readings** of it. A reading is a check's write, not a poll: the snapshot is recomputed
every few seconds whether or not anything was read, and a counter that advanced there
would escalate a node nobody had asked about again. So the counter lives beside the
pins, as a side-table keyed by path, and is advanced in the one place a reading
arrives — including a reading that changed nothing, because *three consecutive
readings of `ERROR`* is three readings and only the first of them is a transition.

What it counts is the code the check **reported**, not the node's derived own status.
Those two differ only where a pin is involved — with coded entries the derived value
is already what the tree is handed — and a pinned node contributes nothing anyway. So
counting the reported code costs nothing in fidelity and saves deriving the same value
twice, at two points, that must then agree.

### 2. What a held node publishes is what it published before

Not `OK`, and not nothing. A node that was already `WARN` and now reads `ERROR`
publishes `WARN` while it holds: publishing `OK` would invent a reading nobody made,
and publishing nothing would drop the node out of its parent's count entirely, which
is what [ADR-0039](0039-status-rollup-semantics.md) reserves for *silenced* and *not
yet reported*. Neither is true of a node that has read something and is waiting to be
believed.

This makes it the first rule at this boundary that **transforms** a contribution
rather than withholding one, which is the case
[ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 2 described in
advance: `contribution.code` is null for a rule that withholds and a real code here.
The snapshot now carries that value as a field rather than leaving the API to infer it
from the node's code — an inference that worked only as long as every rule withheld,
because a transformed contribution is by definition not derivable from the value that
was not counted.

### 3. Three ways out of the count, and only one of them is the count

**Recovery is immediate.** A reading equal to or better than what is published is
published at once and clears the counter. Asymmetry — slow to alarm, fast to recover —
is the convention, and the alternative makes a parent flap on the way down instead of
on the way up.

**A different worse code restarts the count.** Two readings that disagree are not two
votes for either; a node that reads `ERROR`, then `WARN`, is counting toward `WARN`
from one.

**An unranked move is not an escalation at all.** Only `OK` / `WARN` / `ERROR` are
ranked, so a move through `UNDEFINED` publishes at once, and so does a node's very
first reading — there is nothing to escalate *from*, and holding it back would delay
the only claim anybody has made.

### 4. Staleness goes past the counter

A check that stops running produces no new readings, so the count never advances and
the hold never ends: the node would age quietly behind a door the counter was holding
shut. Freshness escalates independently, as
[ADR-0032](0032-status-contribution-boundary.md) rule 6 requires of every suppression
here — and the shape it already had does the work, because a stale node gives its
parent its degraded **raw** code rather than anything derived.

That is invariant 1 of this boundary, met for the second time: the pin's own
exemption was removed for it, and the dependency shield will answer to it next.

### 5. It has to be visible or it reads as a bug

A red leaf under a green parent is exactly what a broken roll-up looks like. So the
node says how far the count has got — `1 of 3 to escalate` on its card, and on its own
page a sentence naming what it is showing, how many readings are in, and what the
level above is counting meanwhile. It takes the **same slot and the same ink** as the
maintenance suffix that already says *we are silencing an error*, because they are one
idea — this node is transforming what it publishes — and three features inventing three
treatments is the outcome that boundary exists to prevent.

The event log stays honest: the leaf's transition is recorded when it happens, marked
`damping` in `suppressed_by`, so the delay is visible in the history rather than hidden
by it.

**And the node's own history keeps it**, which needed saying in code as well as here.
The history filters out transitions that were *hidden*, so that a check going red
underneath a pin does not chop one maintenance window into phantom periods — and the
test for that was *was this suppressed at all*. A damped transition answers yes to that
question and is the opposite case: the node did change what it showed, immediately, and
only its parent's count waited. So the filter turns on which rules hide the **reading**,
not on whether a rule acted; today that is maintenance alone, and a dependency shield
will sit on this side too, since it keeps the node's own state and marks it.

### 6. The number is the deployment's, and `1` is today

`escalate_after` is a `settings.yaml` key with a per-check override, default **1** —
which is exactly the behavior every deployment had before there was a counter. It
arrives switched off, and a deployment turns it on where it has a flapping subject
rather than everywhere at once. Zero is refused at load: *never publish* is the one
direction [ADR-0032](0032-status-contribution-boundary.md) rule 7 rules out.

The engine resolves the two — the check's own value, or the deployment's default — and
hands the answer to the tree with the reading, because the tree reads no configuration
of its own and should not start.

### 7. What the counter cannot catch, the node says out loud

Consecutive counting never escalates a **flapping** subject — `red, green, red,
green` never reaches two reds in a row — and its own marker is no help there either,
because every recovery clears it: the card would flicker rather than report. So the
hole is not merely written down, it is answered on the surface. A node's page says how
many times its own status **changed in the last hour**, counting only moves between
`OK`, `WARN` and `ERROR`.

It is **derived, not stored**. Every transition is already in the event log; a second
record of them would be a second thing to keep true. One pass over the log per
snapshot serves the whole tree, because the log is bounded and the recursion is not.

Three details decide what the number means. A node's **first** reading is not a change
of mind, so `UNDEFINED` to anything is not counted — otherwise every node on the
dashboard would carry a 1 for an hour after a restart, and a number that is always 1
teaches its reader to skip it. A transition that a rule **kept from alarming does**
count, which is the opposite of what the node's history does with it: this number is
about the subject's behavior, and a check flapping underneath a pin is exactly the
thing worth seeing. And the window is an hour — the span the question *is this thing
flapping* has in mind, and short enough to stay inside a bounded log, so the number
does not quietly come to mean *what is still in the deque*.

It is on the node's **page and in the envelope, and deliberately not on a card**. A
card says what a node is now; churn is history, and the page is where this project's
history already lives, next to the link to the rest of it. Noticing churn across a
whole tree is the events page's job and it already does it.

## Consequences

- **The counter is memory and a restart re-arms it.** A node mid-escalation when the
  process restarts begins its count again. Accepted rather than solved: the value's
  whole purpose is to be forgotten within a few minutes, and a state file for it would
  outlive the thing it describes.
- **Flap is not caught, it is only shown.** `red, green, red, green` never reaches two
  consecutive reds, so a flapping subject escalates only through staleness or not at
  all — while a flapping service is broken. Consecutive is the rule that is easy to
  explain and easy to see on a card; decision 7 makes the hole visible rather than
  leaving it to be discovered, and a sliding window is the answer if the number shows
  that it matters.
- **Detection is slower by `escalate_after` readings** wherever it is turned on, which
  is why the fast recheck ([ADR-0033](0033-budgeted-failure-retry.md)) ships first: the
  delay is measured in retry intervals rather than in full periods.
- **The roll-up reads a new value.** A parent accumulates its children's
  *contributions* rather than their codes. For every rule that withholds, that is the
  same number as before — `MAINTENANCE` and `UNDEFINED` are skipped by the roll-up
  itself — so nothing about a tree without damping moves.
- **The envelope's minor moves to 2.3.0**, additively: `contribution.code` carries a
  real code for the first time (2.2.0) and a node carries `changes` (2.3.0). No field
  changes shape.
- **The golden envelope artifact is regenerated in this change**, which is the other
  half of ADR-0080 decision 1 and is the rule that artifact states about itself: a
  field added to the contract makes it stale in the same change, not in a follow-up.

## Alternatives considered

- **`N` of the last `M`.** Catches flap, which consecutive does not, at the cost of a
  rule that is harder to explain and a marker that cannot be a count. Deferred with
  its hole named above.
- **Damping inside the check**, so the leaf itself stays green until it is sure.
  Rejected: it lies to the one reader who came to look at that specific thing, and it
  is the formulation this project rejected when the question was first written down.
- **Symmetric recovery**, a hold in both directions. Defensible and rejected: it makes
  a parent lag on the way down as well, which is the half nobody is asking for.
- **Do it in a notifier.** The rolled-up code is what every client consumes, so
  suppressing only the notification suppresses nothing — and there is no notifier.
- **Leave the contribution derivable from the code**, as the API did. That works only
  while every rule withholds. A transformed contribution is precisely the value the
  node's own code is not, so it has to be carried.
