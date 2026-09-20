# ADR-0036 — Addressable reasons: keyed entries, and maintenance on one of them

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-08-01)
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (the contribution
  boundary, amended by this decision to reach one level below a node),
  [ADR-0004](0004-status-aggregation-semantics.md) (the roll-up these entries reuse,
  and an open edge case this answers one level down),
  [ADR-0007](0007-check-result-branches.md) (`CheckResult`, and the tree-level prune it
  deferred — which this decision makes unnecessary *for entries*),
  [ADR-0014](0014-maintenance-persistence.md) (the pin and its side-table, whose key
  space this widens), [ADR-0018](0018-markdown-rendering.md) (an alternative it
  declined once, on other grounds — see *Alternatives*),
  [ADR-0024](0024-dashboard-layout.md) (`reason_cap`, the display budget these render
  inside), [ADR-0008](0008-json-output-api.md) (the envelope, extended additively),
  [ADR-0025](0025-check-provided-subnode-metadata.md) (the other route — real
  subnodes — and why it is not this one)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check that discovers **dynamic entries** puts many of them into one node's reasons:
security findings under a severity band, waiting pull requests under an aspect, jobs
under a build server. The list changes run by run — entries appear when the condition
appears and vanish when someone fixes it.

An operator picks *one* of them, opens a ticket and starts working. The next engineer
has to be able to see that. Today they cannot: the only suppression is
[maintenance](0014-maintenance-persistence.md) and it is **per node**, so pinning the
one finding somebody is working on silences the other nineteen — and a node with
twenty findings is exactly the node where that is worst.

The obvious answer is to make each entry a node. It was designed out loud and
rejected on cost, not on principle:

- **The event log.** A first sync of two hundred findings is two hundred
  `UNDEFINED → WARN` transitions into a 1000-entry deque. Two such checks wrap it and
  erase every real status transition the operator had.
- **The envelope and the client.** Hundreds of extra leaves per check land in the JSON
  and in the menu-bar app's tree.
- **The dashboard.** The density rules of [ADR-0024](0024-dashboard-layout.md) — chips,
  the branch cap — were tuned for a dozen siblings, not two hundred.
- **It demands the prune.** [ADR-0007](0007-check-result-branches.md) deferred a
  tree-level delete *"until a check needs it"*; entries-as-nodes would need it
  immediately, together with an ownership stamp (a `nodes.yaml` entry can create a node
  under a check's mount that the check never wrote) and a **declared completeness**
  signal, because a truncated or failed run must never delete what it did not see.

All of that buys per-entry history — which this pass deliberately does **not** take,
for the event-log reason above. So the cost is paid for a feature we are not taking.

What is actually needed is narrower: an entry must be **addressable**, so a pin can
name one. Everything else about a node — a path, a page, a history, a freshness
clock — is not.

## Decision

**1. A reason is a keyed entry: `slug -> text`, in the check's order.**
Insertion order, not sorted by key: the order a check emits its entries in is
information (severity, API order), and sorting by an opaque slug would scramble it.

**2. The check signature stays tolerant, and a plain list is prose.**
`CheckResult.reason` accepts `str`, `list[str]`, `dict[str, str]` or a list of pairs,
and `__post_init__` normalizes to the one internal form. A disk check keeps writing
`CheckResult(WARN, ["disk at 86%"])`.

But **not every reason list is a list of independent things**, and the difference
decides what may be suppressed. A failing check's node carries two reasons —
`check error: …` and the stack trace
([ADR-0004](0004-status-aggregation-semantics.md), *A check that fails*) — and a
captured-output check carries stdout beside stderr. Those are **one condition in
several paragraphs**: silencing the trace while the message keeps alarming is
meaningless, and so is a per-line ticket button on either half.

So **prose is the default and members are declared**, in either of two ways: the check
hands over a **mapping**, which says so by its shape, or it sets **`entries=True`**
beside a sequence of strings it knows to be stable. The second form exists so a check
whose strings already carry identity — `f"{issue_id} {text}"` — gets per-entry pins
without restructuring its return; a mapping implies the flag and need not set it, and
the flag is meaningless beside a bare `str`.

Two properties follow, and both are why the default sits on this side: the engine's
failure path needs **no change at all** (it returns a sequence, so it is prose), and
this decision changes **no existing surface** until some check opts in.

**3. An undeclared entry is keyed by a content hash**, `h-` plus the first ten hex
digits of the text's SHA-1; a slug already taken within that node takes `-2`, `-3`, in
the check's order. Not an index: an index moves when an entry is inserted above it, so
a pin would slide silently onto a **different** finding. The hash makes *"return a
stable string"* sufficient — a check that emits `f"{id} {text}"` gets durable pins
without a line of slug logic — and the `-N` suffix covers both repeated texts (a real
list can carry the same sentence three times, for three different findings) and an
astronomically unlikely hash collision.

**4. Declared and derived slugs differ in what they promise, not in mechanism.** A
check-supplied slug is an **identity claim**: the text may be re-worded and the pin
holds. A derived slug **is** the wording: re-word the entry and the slug is gone. Both
are plain strings and both obey one rule — *a pin whose slug is not present does not
apply* ([ADR-0032](0032-status-contribution-boundary.md) rule 7). The `h-` prefix is
there so a human reading a URL or a log line can tell which promise they are looking
at.

**5. The pin lives outside the check's output.** The check emits `slug -> text` and
nothing else; the maintenance side-table's key widens from `path` to `(path, slug)`;
the snapshot joins the two. Where the widened side-table is persisted is
[ADR-0014](0014-maintenance-persistence.md); the file's shape is a clean break, not a
migration. Storing the entry *in* the reason map would destroy it on the check's next
run, and writing it into the tree is what
[ADR-0032](0032-status-contribution-boundary.md) rule 3 forbids. This is the first
maintenance-shaped mechanism built rule-3-correct from the start.

**6. Absence suspends a pin; only expiry disposes of it.** A slug missing from this
run's map means the pin *does not apply right now* — it is **not** deleted. A failed
check replaces its whole reason map with `check error: …`, so a delete-on-absence rule
would throw away every pin on the node the moment the check has a bad minute. The
node says a pinned entry is no longer reported;
[ADR-0014](0014-maintenance-persistence.md)'s expiry stays the backstop that keeps a
forgotten pin from lasting forever.

**7. The entries are virtual children.** Each unsuppressed entry contributes the
node's reported status; a suppressed one contributes nothing; the node's **own**
status is the worst of what is left. That holds literally over entries that declare a
code of their own ([ADR-0042](0042-entries-carry-their-own-code.md)): same derivation,
same exclusions, same silenced-versus-unreported tiebreak, with one stated default —
an entry-bearing node whose run reports **no** entries reads `OK`, because "nothing to
report" is not "nothing reported". A node that reported entries and has none
unsuppressed left presents `MAINTENANCE`. Two nodes are outside this rule entirely: one
that reported **no** reasons (a check with a code and nothing to say), and one whose
reasons are **prose** (decision 2) — prose has no individually suppressible parts, and
its unit of suppression stays the node pin.

This is [ADR-0004](0004-status-aggregation-semantics.md)'s roll-up applied one level
below a node, and it is what the
[ADR-0032](0032-status-contribution-boundary.md) decision 8 records:
the contribution boundary reaches under a node, and rules 2–7 hold there unchanged.

**8. A per-entry pin takes the cap, not the threshold.** An entry may declare a **code
of its own** ([ADR-0042](0042-entries-carry-their-own-code.md)), so an entry has no
severity of its own only where it declares none — which remains the default, and
remains permanently right for a severity-banded leaf, whose lines are one severity by
construction. When the pin policy grows an `escapes` setting, the threshold form
(`escapes: error`) is meaningless for such an entry, because it carries the node's. The
**cap** form does work: a capped entry contributes `WARN` where it would have
contributed `ERROR`. Whether a pin on a *coded* entry may take `escapes` is re-examined
by the pin policy when it is designed.

**9. Liveness is not switched off.** `_is_stale`'s exemption for a pinned node is
**not** extended to a node whose entries are all pinned. Staleness keeps judging the
raw reading, which the tree still holds — otherwise a dead check hides behind twenty
quiet findings ([ADR-0032](0032-status-contribution-boundary.md) rule 6).

**10. Quiet is visible.** A suppressed entry renders in the maintenance surface color,
and the node states how many of its entries are quiet — a card clamps its reasons to
`reason_cap` ([ADR-0024](0024-dashboard-layout.md)), so the pinned line may sit below
the fold and the count is the only thing that always shows
([ADR-0032](0032-status-contribution-boundary.md) rule 5). An entry pin **reports**
everywhere a node pin does — the strip pill, the "contains maintenance" pip and
`/maintenance`. Setting one stays the leaf page's job (decision 12).

The **capped popover summarizes per node** — one row with a count (*3 of 20 reasons*,
or *all 20 reasons* where every member is pinned) — while `/maintenance` lists one row
per pin. Twenty rows from one node would otherwise evict every other node from a capped
list. The count is also what keeps the pip honest: without it a row would read as a
node pin, which it is not.

**11. Events and history keep plain strings.** They carry the map's *values*. A slug
in a historical event means nothing once the entry is gone, and per-entry events are
what would flood the log. Whether an entry's appearance is ever recorded is left open.

**12. An entry is addressed in a query parameter or a form field — never in a path
segment.** The surface is the **existing leaf detail page**, which already lists every
reason uncapped; it grows an admin control per line, and the write posts `path` plus
**`slug`**, not `reason`: this form's `reason` is already the pin's explanation text,
and overloading it would have made the two indistinguishable in one request — the
*addressing* shape this decision fixes is the query parameter (`?reason=<slug>`), a
different namespace, and it is unaffected.

The **query parameter is built** on the node page rather than as a second route:
`/status/<branch>?reason=<slug>` — the node stays a path, the slug stays a query value.
The index names a line, so its link lands on that line; the page marks the one it was
asked for with a single fixed `pinned-reason` anchor. A slug in a *fragment* was
considered and rejected — a declared slug may legally contain `#` or `%`, which a
fragment silently mis-parses; it would need an id on all 150 lines; and it can only
fail to scroll. The parameter lets the server say what nothing else could: a pin whose
slug the current run does not report is **suspended, not deleted** (decision 6), and
the page says so in words.

Two reasons, both hard: a percent-encoded `/` does **not** survive a path segment (WSGI
hands over an already-decoded `PATH_INFO`, so `%2F` and a real separator are
indistinguishable by the time routing runs, and Apache answers `404` for encoded
slashes by default), and the natural slug for a discovered entry contains one —
`acme/api-pr-412`. Keeping the slug out of the path also removes the ambiguity of
`/maintenance/a/b/c`: with the parameter absent, the target is the node itself.

The **slug is never rendered as text.** It appears only as that link's value. What
names an entry in a list is its *line*, and the two texts get two columns: *Silenced*
(the line) and *Why* (the pin's own explanation). They are both called "reason" in the
model and are not the same kind of thing.

**13. The JSON envelope grows additively.** The existing `reasons` array of strings
stays, unchanged for every existing client; a new array — `entries`, the working name
— carries an object per entry, `{"text": …, "code": …, "running": …,
"maintenance": … | null}` — objects rather than positional pairs, per the API
guidelines. It rides the one `schema_version` decision of the client contract round
rather than arriving on its own.

That round is [ADR-0080](0080-the-envelope-is-the-snapshot-published.md), and it took
the name rather than the addition: `entries` is an object that **replaces** the string
`reasons`, its `addressable` flag is this record's `members`, and its items carry
`slug`, `text`, `code`, `running` and `maintenance`. The name this record could not
spend twice was spent there.

## Consequences

- The operator can pin the one finding they are working on. The other nineteen keep
  alarming, which is the entire point.
- **No prune, no ownership stamp, no completeness signal.** An entry that disappears
  is simply absent from the next map. [ADR-0007](0007-check-result-branches.md)'s
  deferred tree-level prune stays deferred — it is still owed for genuinely
  node-shaped dynamic subjects and for its original case (aspect nodes left behind by
  an unreachable host), but it is no longer on this feature's path.
- **`own_code` stops meaning "what the check reported".** For a node with suppressed
  entries it is a derived value, and the tree's stored code is the raw one. The
  maintenance keystone refactor makes the same move for node pins, so the two should
  share one transform in `StatusTree.snapshot` rather than build it twice — which is
  why this lands **with or after** that refactor, not before it.
- **[ADR-0004](0004-status-aggregation-semantics.md) has an open edge case that must
  now be answered the same way.** *"A node whose children are all ignored and that has
  no explicit code — proposed default: `UNDEFINED`."* Decision 7 answers the identical
  question for virtual children with `MAINTENANCE`, and real children reading
  `UNDEFINED` while virtual ones read `MAINTENANCE` would be a contradiction in one
  model. The ADR-0004 split owes the same answer: a container whose every child is
  pinned is in maintenance, not idle.
- **A write client cannot yet address an entry.** Decision 13 publishes no slug, so a
  token-authed mutation (the JSON API's write actions) has nothing to name. Adding
  the slug later is additive but costs a second `schema_version` bump; that is the
  accepted trade for a smaller envelope now, and the bump the contract round spends is
  the one that carries it.
- **Two shapes at one seam.** `CheckResult.reason` accepts four input forms and the
  core sees one. The normalization is the only place that knows the difference, which
  is the same rule the value readers follow
  ([ADR-0026](0026-reading-values-from-decoded-bags.md)): narrow where the outside
  world enters.
- A slug is opaque and is never rendered as text; it appears in `data-` attributes,
  form fields, query values and log lines, so it stays bounded in length and free of
  whitespace and control characters.
- Deployment extensions benefit for free: the `reason.actions` slot
  ([ADR-0034](0034-template-slots-for-dependent-packages.md)) already passes the whole
  reason line, and an entry is what a ticket should be filed against.
- **A deployment action needs two placements, not one.** Where a node's reasons are
  members, an action belongs on the **entry** — the `reason.actions` slot, one per
  line. Where they are prose, there is exactly one thing to act on and it is the
  **node**: one control, built from the whole reason set (its first line the summary,
  the rest the body). A per-line control there would offer to raise a ticket about a
  stack trace. That second placement is the `node.actions` slot — the card header
  and the detail page, where "this check is unhappy" is the subject — which this
  record was the first concrete need for and
  [ADR-0038](0038-declarative-action-list.md) gave the roster.

## Alternatives considered

- **A node per entry.** The honest general model, and the one the tree already knows
  how to address, pin and page. Rejected on the four costs in *Context* — the event
  log above all — for a feature (per-entry history) this pass is not taking. It stays
  the right answer for a subject that is **independently monitored over time** — a job
  that goes red and green has a history and deserves a node; a finding that exists
  until someone fixes it does not.
- **An index as the slug.** Simpler and readable, and adequate for the static handful
  of member entries a discovering check emits. Rejected as the *default* because it
  fails silently in exactly the case this ADR exists for: insert an entry above a
  pinned one and the pin moves to a different finding, with nothing to notice it by.
- **A separate validator field** — store the pinned text beside the entry and refuse
  the pin when it no longer matches. Correct, and unnecessary: a derived slug already
  *is* the text, so it invalidates itself, and a declared slug is meant to survive a
  re-wording. The field would only have re-implemented decision 4.
- **A typed reason.** [ADR-0018](0018-markdown-rendering.md) considered one — carrying
  a `markdown` / `plain` flag — and rejected it as *"a wide, invasive change"* across
  `CheckResult`, `Status`, the event log, history and the envelope. That reasoning was
  about **rendering**, and it still holds: nothing here changes how a reason is
  rendered, and the strings survive as strings at every one of those seams. What
  changes is that a reason gains an **address**, which the earlier decision was not
  asked about.
- **`%2F` in a path segment.** Would have let the slug be a path component and kept
  one route shape. Rejected on decision 12's two failure modes; the query parameter
  costs nothing and is unambiguous.
- **A dict as the only accepted form.** One shape end to end, no normalization. Rejected:
  it would make every check author think about identity, including the ones with a
  single fixed reason, to serve the few that have dynamic entries.
