# ADR-0044 — The run on the node: the container stamp, run facts, and `report`

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-08-08 in the design round on information a
  status code cannot carry)
- **Related:** [ADR-0027](0027-observation-timestamp-semantics.md) (amended by this
  record: the mount registry counts checks per path, and the stamp a sole-check
  container always carried is finally drawn),
  [ADR-0013](0013-check-config-on-node.md) (`config` is inputs; `report` is the
  outputs field beside it),
  [ADR-0012](0012-node-metadata.md) (`about` stays seed-once subject metadata — the
  line a live count must not cross),
  [ADR-0033](0033-budgeted-failure-retry.md) (why next-run must come from the
  engine, never from arithmetic),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (freshness; the
  container becomes subject to it, deliberately),
  [ADR-0019](0019-inspection-popover.md) (where a container's metadata surfaces
  today — the reason the branch head grows rather than a new page),
  [ADR-0008](0008-json-output-api.md) (the envelope, untouched until the contract
  round)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Three observations about one node, from the dashboard of a branch check (a CI/repo
check reporting seven aspects under one container). The container shows **no check
time**, though one check wrote all seven aspects in one run and the time has exactly
one honest answer. What `/system` knows — the last run, its wall time, when the next
is due — is exactly what an operator wants *while looking at `/status`*, and it sits
behind an admin page. And the check's own configuration, which both stress checks
publish via `config_summary()`, is **rendered nowhere**: the data lands on the
container (`is_root`), core renders `config` on the leaf detail page only, and a
container has no leaf page — the data is container-only and the rendering leaf-only,
and the two never meet.

Behind the first gap is display, not storage. The engine registers one mount per
check at the check's own path and stores the check's result at that path on every
run, exactly as [ADR-0027](0027-observation-timestamp-semantics.md)'s context always
said ("leaves, inner branch nodes, and the mount itself"), so the container carries a
true stamp and its staleness (decision 3) is already live. The bare container is
**display-only** — neither the overview's boxes nor the branch page's head renders a
time; only cards and the leaf page do — and decision 5 is the real fix for the
observation. Rule 4's refusal ("two or more mounts: no timestamp") does not apply to
the sole-check container: below it there is no other check, so the ambiguity the rule
guards against is absent.

There is also a latent collision, one step **above** the shared node: `_check_mounts`
is a **set**, so two checks legitimately sharing one host node collapse to one entry —
and if the sole-mount shape simply stamped "the" mount, the unwritten ancestors above
them would inherit a stamp that flips between the two checks' run times, which is
exactly rule 4's ambiguity. The shared node itself keeps answering with its own last
write (ADR-0027 rule 2, untouched).

## Decision

1. **The mount registry counts checks per path.** One check at a path ⇒ the
   container may carry that check's run facts; two or more ⇒ it carries none, for the
   reason ADR-0027 rule 4 states; and the ancestors above a shared mount inherit
   **none**. **One ownership rule covers four facts** — the run time, the wall time,
   the next run, and the check's own text (`config`, and `report` below): all belong
   to *the check that owns this node alone*, and all are withheld where two checks
   share it. `config_summary`'s branch-check guidance becomes conditional on that
   count: own the container alone ⇒ its whole-check text goes there; share it ⇒ tag
   the owned children instead. A check with whole-check information to publish should
   own its own node. [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
   generalizes that rule from *one check answers for this node* to *one **unit**
   answers* ([ADR-0078](0078-the-unit-is-what-the-engine-releases.md)) — the same
   statement for every check that exists today.
2. **The engine writes the run's facts onto the check's own node after each run.**
   The sole-check container carries the check's run time because that is literally
   what it is. Nothing is synthesized from below — `max(children)` stays rejected
   ([ADR-0027](0027-observation-timestamp-semantics.md) rule 5). The run's **facts** —
   wall time and next run, which no upsert carries — are written only where the count
   is one: the engine writes wall time and the armed next slot beside each result, and
   the tree resolves the facts onto exactly the nodes whose subtree holds **one**
   check, the condition that already governs the inherited stamp: ancestors above a
   sole mount inherit them, a shared mount and its ancestors get none, and a leaf
   *below* a branch mount keeps a bare time — its next update lives one level up,
   where the check is named. A one-shot `run_once` writes wall time with no next slot
   (no live schedule to project), and a secret-pinned check the reverse — a real slot,
   no wall time, since it never runs (ADR-0023).
3. **The container is thereby subject to staleness, deliberately.** A branch check
   that stops running degrades where it is named; its children degrade too and
   worst-of takes the worse, so nothing weakens. ADR-0027 rule 1's "having a
   timestamp means a check has written the node" widens for a branch container to
   *the check behind this node ran* — which is what a reader takes it for anyway.
4. **The node gains one small `run` object** — wall time and next run — beside
   `timestamp`, rather than flat fields, so the node grows one member and the
   "these are one fact under one rule" claim is structural. **Next-run comes from
   the engine, never from `timestamp + frequency`:** under the budgeted retry
   ([ADR-0033](0033-budgeted-failure-retry.md)) a failing check's next slot is
   pulled in, so the arithmetic answer is confidently wrong exactly when someone is
   watching a failure. The slot is projected onto the wall clock once, at write time,
   after the ADR-0033 retry decision, so a watched failure's next update is the
   pulled-in slot.
5. **Display: the time shows on the topmost node visible in the current view** and
   is suppressed below, where it would be identical — at the overview the container
   shows it and its boxes do not; on the branch page the head shows it and the
   cards do not; on the leaf page the leaf shows its own. Safe precisely because of
   decision 1: an ancestor carries a stamp only where a single check owns
   everything below, so an identical value below can only be the same run. The
   **next update joins the check time in the head line** wherever that time shows:
   `22:25 → 22:30` — absolute, and **the whole pair is minute-precision**, because
   seconds carried no information worth the row width. The arrow is **suppressed
   where it would render the very value beside it** (`22:25 → 22:25` says nothing),
   so a sub-minute schedule (the demo's fast checks, a pulled-in retry) shows a bare
   time and the arrow appears exactly when it adds information.
   Freeze-safety decides the format: when polling fails, the client-side staleness
   dims the content and leaves it on screen, and a frozen relative "in 4m" is a lie
   that still looks live, while a frozen `→ 22:30` stays true and recedes into the
   past. A stalled check shows a next-run in the past — honest, and the staleness
   `WARN` beside it already carries the alarm. The root stays blank: many checks,
   no single answer (rule 4), and "how current is this page" is the freshness
   stamp's question, answered a few pixels away. Wall time itself stays unrendered
   until decision 8's node header.
6. **A node gains `report` — what the run *found*,** distinct from `config`'s what
   it ran *with* ([ADR-0013](0013-check-config-on-node.md)). Write-through every
   run (like `config`, unlike the seed-once `about`); Markdown through the same
   hardened renderer; shown on the node's page and **never on the card** — volume
   is what `reason_cap` exists to keep off cards; and **never a status claim** —
   anything that should alarm is a reason, and `report` must not become a second,
   quieter reason channel. It is a field on `CheckResult` and on the node, written
   through every run **including empty** — a roster the current run no longer finds
   must not outlive it, which is the one place it parts company with `config`, whose
   root value comes from the check object rather than from the run (only a run can
   say what it found, so `report` rides the result at every level, root included).
   What separates the two is **status, not volume**: a list whose items each carry a
   verdict belongs in the reasons (entries, capped); a list whose items carry none is
   scope and belongs in `report` — the roster is presence, an entry is a claim.
7. **`report` lands on the node the check owns alone; on a shared container it goes
   on the owned child subtrees** — the rule `config` already follows, carried by
   the same per-child `CheckResult` mechanism, and unambiguous by construction
   (ownership is disjoint and enforced at load). A whole-check statement has no
   honest home on a shared container; in practice the shared-container checks are
   host-shaped and their natural report is per-child, while the checks with
   whole-run statements own their containers outright. This rule and decision 1 are
   **enforced rather than advised**: the snapshot publishes `config` and `report` as
   empty on a node **two or more checks mount**, so the "one ownership rule over four
   facts" claim is structural, like the withheld stamp beside it — withheld, not
   destroyed, and conditioned on the node's *own* mount count, so per-child text
   below a shared container survives, which is exactly where that shape is told to
   put it.
8. **The branch head becomes a real node header.** `/status/<branch>` today renders
   the node's children and gives the node itself only name, title, `about` and
   rolled-up status; it grows the run facts, the `config` block and `report` when
   present — the container acquiring the page it never had, not a new surface. The
   kiosk keeps none of it. Rather than growing the head field by field, the leaf
   page's Time and Configuration cards became **one shared partial**
   (`_node_facts.html`, plus the new Report card), and the branch page renders it —
   so the container gets that page by **reuse**, and the two pages cannot drift. The
   block sits **below** the child grid and **inside** the polled fragment: below,
   because a forty-line report above the grid pushes away the dashboard the reader
   came for; inside, because `report` is an output of the run and a frozen roster
   beside a live grid is the one part of the page quietly going wrong. `config`
   renders **as Markdown** — checks author it with `config_markdown()` and the leaf
   page had been showing `- **scope:** org` verbatim since before the renderer landed
   (ADR-0018).

## Consequences

- The "config is stored but rendered nowhere" gap closes for containers, and the
  scope answer of [ADR-0043](0043-coverage-backstop.md) gets its two homes: the
  count as a reason, the roster in `report`.
- `Status` grows two members (`run`, `report`). That is real creep of the kind
  ADR-0027 and ADR-0036 both warn about; each future field argues for itself, and
  grouping the run facts as one object is part of holding that line.
- The JSON envelope is untouched until the client contract round; until then the
  new material is web-only, like `reported_code` and `suppressed_by` before it. At
  that round [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) publishes
  `run` and `report`, with the block **absent** where nothing answers rather than
  null.
- A topology change keeps its ADR-0027 property: adding a second check under a
  container clears the container's run facts because the question stopped having
  one answer — the value disappears rather than silently changing meaning.
- One defect older than this record surfaced in building it: `history()` asserted
  that a node with a transition is stamped, while `_emit` documents the opposite
  case — an admin pin lands on a container no check has written.
  `/history/<that container>` was a 500, and the branch page asking for its own
  period would have been another. `StatusPeriod.until` is now `str | None` and the
  surfaces render the absence as `—`.

## Alternatives considered

- **Synthesize the container's stamp from its children** (`max`) — rejected by
  ADR-0027 rule 5, and re-opening it here would re-open it everywhere.
- **A view-layer join against `engine.info()`** for the run facts — no model
  change, but the JSON API stays blind (the client cannot show what the page
  shows), and the view would duplicate a node→check lookup the engine already
  owns.
- **The roster in `config`** — rejected: the filter is an input and the fourteen
  matches are an output; filing outputs under inputs is how a field stops being
  trustworthy.
- **A live count in `about` via runtime tokens** — rejected:
  [ADR-0012](0012-node-metadata.md) makes `about` seed-once subject metadata, and a
  count written once is a lie by the second run. Config-derived tokens stay fine;
  run-derived values belong in `report`.
- **A relative "in 4m" next-run on the card** — rejected for freeze-safety
  (decision 5); the next update stays **absolute** in the header too, because the
  argument for a relative form there assumes a live page, and one partial serves a
  page that polls and a page that does not, where a frozen *in 4m* is precisely the
  lie the absolute form was chosen to survive.
