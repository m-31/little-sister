# ADR-0076 — The instance's node is a branch: a child per contributor, an action per child

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-09-05)
- **Related:** [ADR-0072](0072-the-instance-reports-on-itself.md) (the self-report
  seam whose contributors become the children, and whose §7 records are what the
  children carry), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the
  heartbeat this branch is rooted on, and the stale beat that stays the root's own),
  [ADR-0056](0056-stable-useful-dashboard-flow.md) (the status strip, whose
  decision 3 this record amends), [ADR-0024](0024-dashboard-layout.md)
  (where the strip came from), [ADR-0036](0036-addressable-reasons.md) (a pin holds
  against `(path, slug)`, which is why this is a breaking change),
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (the slot seam the action buttons render
  through), [ADR-0039](0039-status-rollup-semantics.md) (the roll-up the strip shows)

## Context

ADR-0072 gave the instance one node to speak on, `/little-sister`, and one seam to
speak through: a contributor registers a name and answers with lines, and every
tick the heartbeat carries the engine's own lines and every contributor's, each
slug prefixed with the contributor's name so a pin can hold it. Two records grew on
the seam since (ADR-0072 §7) and the inventory of what the process used to say only
to the log moved onto them, and with it the node has eight speakers — the engine,
the state layer, readiness, startup, runtime, security, and whatever a package
brings, the S3 keeper first — and something between five and fifty lines on one
node, in one flat list, read as one card.

Three things stopped working at that size. A reader cannot tell the speakers apart
except by the prefix inside each slug. A pin silences one line or the whole node —
there is nothing between *this lease line* and *everything the instance says*. And
a package with something an operator can *do* about its lines — take a lease over,
give it up — had nowhere to put a button: the node was the library's, the lines
were the package's, and the seam carried lines and nothing else.

## Decision

1. **`/little-sister` is a branch.** The root carries the beat — the engine writes
   it every tick with the heartbeat's description and a stated freshness
   **tolerance**, OK, and no lines of its own — and one child per speaker:
   `/little-sister/engine` for the engine's own lines, `/little-sister/<name>` for
   every registered contributor. Each child is written every tick with that speaker's
   lines as member entries, its own code the worst of what they claim (ADR-0042) and
   OK when nothing does, its description saying what such a node is, and a tolerance
   of its own. Nothing on this branch carries a **frequency**: nothing here is read on
   a check's schedule, so it publishes no interval for a surface to report as one
   ([ADR-0081](0081-an-instance-node-states-a-tolerance-not-a-period.md)). The root's
   code is the roll-up (ADR-0039), and the stale beat stays the root's own (ADR-0005).

   **Every line on a child carries a code; what carries none is the child's
   `report`.** A line is a claim about this process — a lease held by somebody
   else, a save that failed, a burst of failed logins — and carries its code. What
   the speaker merely *knows* — who holds the lease, what was set aside as `.bak`,
   where the engine searched for checks, a configuration that *may* run late, a
   few failed logins below the rate — is a fact, and a fact is
   [ADR-0044](0044-run-facts-on-the-node.md) decision 6's `report`: Markdown, shown
   on the child's page and never on a card, never a status claim. A contributor
   answers it through a second callable (`register_contributor(…, report=)`), the
   engine writes it on the child every tick, empty included, so a fact the speaker
   no longer has does not outlive it. The reason is the roll-up: a child is a coded
   set, and on a coded set an uncoded entry carries the node's code (ADR-0042
   decision 2) — here the worst of the warnings beside it — so a fact written as a
   line counts as WARN while painted as nothing, and the child stays WARN after
   its one warning is pinned until every fact is pinned too. With the facts in the
   report, pinning the one warning quiets the child, and the per-line pin appears
   exactly where a claim is. A line that arrives without a code is a defect, and
   it shows as one: a WARN under its own slug saying the fact belongs in the report.

2. **A child exists whether or not it has something to say.** A registered
   contributor is a node from the first tick, OK and empty when it has no lines; a
   node that appeared only when something was wrong would be the absence a reader
   has to notice, which is the shape ADR-0072 §7 exists to end. `/system` still
   lists the contributors; the tree now shows them.

3. **The path carries the name, so a line's slug is the contributor's own.**
   `/little-sister/engine` + `lag`, not `/little-sister` + `engine.lag`. A pin holds
   against `(path, slug)` (ADR-0036), so **every pin set on `/little-sister` before
   this record holds nothing after it**: the path and the slug both moved. Said at
   the top of the release notes, and taken before the first release for exactly that
   reason. `self_report.current_lines()` keeps the prefixed flat view for a reader
   that wants the whole report in one sequence; the engine reads
   `current_reports()`, one report per contributor with its labels and its lines.

4. **A contributor declares its node's labels at registration**, the way a check
   type ships its subnode prose (C2): `register_contributor(name, lines, title=…,
   about=…)`. The engine writes them fill-only on the tick (`upsert(title=,
   about=)`), so a deployment's `nodes.yaml` declaration for the path, seeded at
   startup, still wins (ADR-0012). The library's own contributors — `engine`,
   `state`, `readiness`, `startup`, `runtime`, `security` — each say what they are.

5. **The status strip is the branch's roll-up.** ADR-0056 decision 3 lifted the
   heartbeat into the strip only while it was a leaf, on the argument that a
   one-line bar must never hide a subtree. It hides nothing: the strip summarizes
   the subtree the way any branch card does, wears the roll-up's code, and links to
   `/status/little-sister`, where the children are the page. `_split_heartbeat`
   lifts the heartbeat with its children; a heartbeat that is not on the root
   overview is still not lifted. ADR-0056 decision 3 states it.

6. **A package may offer an action on its child.** `self_report.register_action(
   contributor, slug, label, handler)`, claimed once under the same rules as a
   contributor name and from the same import-before-app block, in either order
   with the contributor's own registration. The library mounts one route,
   `POST /little-sister/<contributor>/act/<slug>`, gated like every route and
   **admin-only** like every write; it runs the handler, logs who ran what, and
   comes back to the child's page with the sentence the handler returned — or,
   where the handler raised, with the label and the error, because a button that
   answers with a traceback page has said nothing about the thing it was pressed
   for. **A handler that ran is followed by a flush of the state layer** (ADR-0071):
   an action is a write into this process, and what it changed reaches the store
   now rather than at the next interval — the keeper's *take over* adopts and saves
   in the click, and pressed on the instance that holds the lease already it is
   the save; a handler that raised is not followed by one. The flush is the
   scheduler's own, serialized with it, so the click waits at most one interval's
   flush; a handler's sentence may promise what the flush does. A button is offered
   in every state rather than disabled by a state read before the click — the page
   is a snapshot, and the lease can change hands between the render and the POST —
   and the handler's sentence says what actually happened. The buttons are a
   **built-in slot filler** on `node.actions` (ADR-0034),
   rendered only on a child of `/little-sister` and only for an admin, as POST forms
   because an action is a write. Nothing new is invented for the rail: a package's
   button lands beside the declarative chips (ADR-0038) in the one order the slot
   seam already keeps. The first package to register two is the S3 keeper — *take
   over* and *release* — in `little-sister-aws`.

## Consequences

- **Breaking, before the first release**: a pin on `/little-sister` with a
  `<name>.<slug>` slug holds nothing; the same pin is `/little-sister/<name>` with
  `<slug>`. No migration is written — there is no released instance to migrate.
- The JSON envelope does not change shape; the children appear as ordinary nodes
  under `/little-sister`, and a client that walks the tree sees them without
  learning anything new.
- The event log records a transition per child rather than one for the whole
  node, which is finer and more legible: *security went WARN* rather than
  *little-sister went WARN*.
- A pin lands on one speaker — *the keeper is in standby for the next three
  minutes* is one pin on `/little-sister/aws-keeper` — or on one line of it, and
  the rest of the instance's report keeps grading.
- `little_sister.self_report` promises, beside `register_contributor` and the two
  records, `register_action`, `actions_for`, `find_action` and the `Report` a
  contributor's tick becomes (architecture.md §11).
- The library's own contributors carry a title and an about; a deployment's
  `nodes.yaml` can rename any child by its path, as before.

## Alternatives considered

- **One node, the flat list, and a better rendering** — group the lines by prefix
  on the card. It keeps the pin key stable and changes nothing structural, and it
  answers none of the three problems: a pin still cannot take one speaker, a
  package still has nowhere to put a button, and the rendering would have been the
  one card on the dashboard laid out unlike every other.
- **A child per contributor only where it has lines.** Fewer nodes on a quiet
  instance, and the absence problem back: *security* appearing means something
  happened, and its not appearing means either nothing happened or nothing
  registered it, which nobody can tell apart from the tree.
- **Keeping the `<name>.<slug>` prefix under the child**, so only the path moves.
  It would keep half of every old pin key and break the other half all the same;
  a prefix that repeats the path is noise a reader pays for on every line.
- **Actions as ordinary routes a package mounts itself.** A package would need
  the app, the identity gate and the admin rule — three things the library owns —
  and each package would answer *who may press this* on its own. One route and one
  rule, in the library, is the smaller surface.
- **Declaring the actions in `config/actions.yaml`** (ADR-0038). Those are links
  to somewhere else, authored by the deployment; these are writes into this
  process, offered by the package that can perform them. Same rail, different
  kind, and the kind is what the seam distinguishes.
