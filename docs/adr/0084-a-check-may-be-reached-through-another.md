# ADR-0084 — A check may be reached through another

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-09-19)
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (the contribution
  boundary this is the third rule at, and rules 3, 5 and 6 which bind it),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up, and its closed
  vocabulary), [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (the other
  half of the pair: *has it failed enough to believe*, where this asks *could we
  have reached it at all*), [ADR-0041](0041-maintenance-is-a-contribution-rule.md)
  (the derived-not-written precedent this follows),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (decision 1: a field
  added to the snapshot is added to the envelope in the same change),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the freshness
  backstop this must not close), [ADR-0100](0100-system-is-two-views.md) (the
  schedule of `/system`'s *Running* view, which carries the graph)
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — `shielded_by`, from
  2.4.0.

## Context

The incident is the one [ADR-0083](0083-a-node-may-wait-before-it-escalates.md)
opens with: a laptop's Wi-Fi went off and a dozen checks went red at once. Every
one of those readings was true and every one of them was about the same thing —
the network — and none of them said so. The counter answers the half that asks
*has this failed enough to believe*. This record answers the other half: **a
reading taken through a path that is down is not a reading about its subject.**

The shape is a unit that cannot be reached. A service inside a VPN, an estate
behind one API gateway, every check that speaks to one host. When the thing in
between is failing, the checks behind it report what they honestly found, and what
they found is that they could not get there.

## Decision

### 1. A check names one check it is reached through

`depends_on` in a check's configuration: the **path** of another check, resolved at
load. Not a selector, not a tag, not a list. One name is the shape the incident
has — everything behind the gateway is behind *the* gateway — and it is the shape
that can be read off a node's page in one line. A `tag:` value is refused by name
rather than silently treated as a path, so the day that shape is wanted it is a
decision and not a surprise.

The loader refuses what it cannot make sense of: a target no check mounts, and any
cycle, a check depending on itself included. Both are configuration errors that
would otherwise become a silence nobody could account for, and the load is the one
place where the whole set is in view.

The tree is told the graph the way it is told a check's mount — **registry only**,
no node created and nothing written onto one. Whether a shield is in force is
derived per snapshot, because it depends on what the dependency is reporting right
now; that is [ADR-0032](0032-status-contribution-boundary.md) rule 3, and the same
rule the pin was corrected to follow.

### 2. A dependency shields only when it is failing

`ERROR`, and nothing less. The shape this exists for is *a unit that cannot be
reached*, and a gateway reporting `WARN` has not stopped anybody reaching anything.
Shielding on it would quiet a subtree because something was amber, which is the
direction *fail toward alarming* refuses.

### 3. The shield is a statement about evidence, not a filter on bad news

While it is in force, **nothing** of the shielded node reaches its parent — its
`OK` exactly as much as its `ERROR`. Letting a good reading through because it
alarms nobody would put green on a dashboard for a unit nobody could reach, on the
strength of a reading taken through a broken path; *nothing here is reporting* is
the true sentence, and the dependency's own `ERROR` is what the operator is meant
to be looking at.

The node's own `code` does not move. It is red on its own page, in its own history
and in the event log, exactly as a damped node is — for the same reason, which is
that the reader who opened that page came to look at that specific thing.

This is the first rule at this boundary that withholds a node **still holding a
ranked reading of its own**, and that cost one line of the roll-up. A pin and an
unreported node are already `MAINTENANCE` and `UNDEFINED`, which the roll-up skips
by itself, so those two could leave the contribution's code null and let the node's
own value through. A shielded node's value is `ERROR`; it has to contribute
`UNDEFINED` explicitly, because *nothing was counted* has no other spelling in a
closed vocabulary ([ADR-0032](0032-status-contribution-boundary.md) decision 4) and
inventing one was ruled out before this rule existed.

### 4. The marker sits at the check's mount

A check that emits a subtree declares one dependency, and it belongs where the
declaration was made. The children are withheld because their mount is, which is
the roll-up doing its ordinary job — not a mark repeated on every node the check
happened to write.

### 5. Three ways a shield does not apply, and each is one invariant

**A dependency that has never reported, or is stale, does not shield.** Silence is
precisely the state a naive implementation reads as permission, and a gateway whose
check stopped running may be holding an `ERROR` an hour old.

**A stale dependent is not shielded.** A check that stopped running escalates
whatever else is true of it
([ADR-0032](0032-status-contribution-boundary.md) rule 6) — the invariant the pin's
own exemption was removed for and the counter answered to before this. A permanent
shield over a dead check is the failure this whole boundary is built to avoid.

**A dependency that is itself shielded does not shield on.** One red root would
otherwise quiet half a tree through two hops, with the middle node saying nothing
about it. A node that is already withholding is not evidence.

### 6. One rule names each node, in the order of specificity

A node may be pinned, unreported, shielded and counting all at once, and exactly
one rule is named in its contribution. An admin's pin is the most specific thing
anybody said about this node, so it is named first even where something else would
also have withheld it. A node that has never reported has nothing to believe or
disbelieve. Then the two rules that are about a *reading*: the shield, which
withholds it, before the counter, which only delays it — and that order is not
cosmetic, because the counter puts a real code on the contribution and a shielded
node evaluated counter-first would reach its parent after all, with the value it
published before the outage.

Being shielded is still a **fact** about a pinned node, and the node says so; what
it does not do is claim to be the rule that spoke.

### 7. One declaration can quiet dozens, so both ends are visible

That is the risk this feature carries, and the only thing standing between it and a
silence nobody can account for is that the graph can be seen without reading a
configuration file:

- the shielded node's page says it is reached through the failing dependency, and
  links to it — an operator who does not know why a parent went quiet is the reader
  this is for;
- the dependency's page says how many checks are reached through it, which is the
  question to ask *before* declaring one rather than after a quiet morning;
- the schedule of `/system`'s *Running* view
  ([ADR-0100](0100-system-is-two-views.md)) carries the whole graph, on a line
  beneath each check's path;
- the envelope carries `shielded_by` on every node — the path, not merely the fact,
  because `contribution.by` already says a dependency withheld the node and only
  this says which one.

## Consequences

- **A subtree behind a failed dependency reads `UNDEFINED`, not `OK`.** A container
  whose only children are shielded has nothing to say and says so. That is the
  intent — and the dependency's own `ERROR` is on the same dashboard, which is the
  alarm this trades a dozen alarms for.
- **Nothing shields until something declares it.** The default is no dependency at
  all, so a deployment that adds none behaves exactly as before.
- **A check has one dependency, not many.** An estate reached through two gateways
  is not expressible; the day it is wanted, a list is compatible with everything
  here and with the loader's refusals.
- **A shield does not chain.** Declaring `a → b → c` does not shield `a` when only
  `c` is down. Deliberate (decision 5), and the price is that a deep graph must be
  declared against the node that actually fails.
- **The graph is forgotten on restart**, like every other registration: it is read
  from the check files at load, so there is nothing to keep true across a restart.
- **The envelope's minor moves to 2.4.0**, additively: a node carries
  `shielded_by`. No field changes shape, and the golden envelope artifact is
  regenerated in this change ([ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  decision 1).

## Alternatives considered

- **`WARN` shields too.** Rejected in decision 2: a degraded gateway has not
  stopped anybody reaching anything, and the rule that quiets a subtree on amber is
  the one that quiets it wrongly.
- **Shield only a dependent that is itself failing**, letting an `OK` through.
  Rejected in decision 3: it turns a statement about evidence into a filter on bad
  news, and the reading it lets through is the one nobody should trust.
- **Shield transitively**, following the chain. Rejected in decision 5: two hops
  quiet a tree with nothing on any page saying why, and the failure mode is silence.
- **Infer the graph from the tree's shape**, taking a parent as a dependency.
  Rejected: the tree is how an operator wants to *read* the estate and the
  dependency graph is how it is *reached*, and the two are not the same picture —
  the gateway is rarely the parent of what is behind it.
- **Mark every node a check emitted.** Rejected in decision 4: the declaration was
  made once, and repeating it per node makes the marker look like a property of the
  subject rather than of the path to it.
- **Do it in a notifier.** As with the counter: the rolled-up code is what every
  client consumes, so suppressing only the notification suppresses nothing.
