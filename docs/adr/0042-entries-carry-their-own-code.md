# ADR-0042 — A reason entry carries its own code

- **Status:** Accepted
- **Date:** 2026-08-08 (in the design round on information a status code cannot carry)
- **Related:** [ADR-0036](0036-addressable-reasons.md) (keyed entries — amended by
  this record: its decision 8's "an entry has no severity of its own" narrows to
  entries that declare none),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up this reuses one level
  down, virtual children included),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 4's closed vocabulary,
  upheld; rules 5–7, which any implementation must satisfy),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (the derived-not-written
  precedent, and why node pins are unaffected),
  [ADR-0040](0040-what-a-failing-check-becomes.md) (the failure path, which reports
  prose and keeps declaring `ERROR`),
  [ADR-0024](0024-dashboard-layout.md) (`reason_cap`, which makes entry ordering
  load-bearing; the non-color cue rule the italic must respect),
  [ADR-0028](0028-design-tokens-and-themes.md) (the measured ink roster per-line
  status color joins),
  [ADR-0008](0008-json-output-api.md) (the envelope, deliberately untouched here)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Several kinds of information arrive at one node and the status code cannot carry
them. A CI check watches fourteen workflows: this one failed, that one passed, a
third is red *and* already re-running — three different facts on three lines of one
node. A security check grades advisories critical to low and collapses them into one
node code, smuggling the per-line severity back in through an emoji. And nothing at
all can say "a run is in flight": while a nightly build reruns, *the last run failed*
and *a new run is going* are both true at once, and the one field can hold only one
of them.

The temptation each time is a new status code — `RUNNING`, generalized to an `INFO`
band. [ADR-0036](0036-addressable-reasons.md) had already made reasons keyed,
addressable entries; what they could not do was disagree with their node. Its
decision 8 said so outright: "an entry has no severity of its own — it carries the
node's." That held while entries were only findings, where every line on a node was
a problem sharing the node's severity. It breaks for a **mixed** set: under an
`ERROR` node a healthy workflow line renders as a failure, so there is no way to
show a green line under a red node — which is exactly what listing healthy jobs, and
showing a running one, both need.

## Decision

1. **No sixth status code.** The vocabulary stays `OK`, `WARN`, `ERROR`,
   `MAINTENANCE`, `UNDEFINED` ([ADR-0032](0032-status-contribution-boundary.md)
   decision 4 stands). **`INFO` collapses onto `WARN`**: something that is not `OK`
   and not an `ERROR` is a `WARN`. Since `WARN` is *counted*, the choice a check
   author makes is **seen and counted ⇒ `WARN`; available but not counted ⇒ `OK`
   with a reason** (the informational-note reading the product spec has always
   allowed). A permanent informational `WARN` holds the root amber for as long as it
   lasts — a legitimate choice, but a choice; the honest cost of the `OK` half is
   that a band graded `OK` is dimmed, indistinguishable at a glance from "nothing
   there".
2. **An entry may declare a `code`.** A reason entry — already a keyed
   `slug → text` ([ADR-0036](0036-addressable-reasons.md)) — gains an optional
   `StatusCode`. An entry that declares none keeps today's behavior and carries the
   node's; nothing moves until a check opts in, and there is a whole class of checks
   for which uncoded entries stay right permanently (a severity-banded leaf's lines
   are one severity *by construction* — the grouping already moved it onto the
   node).
3. **A node with coded entries declares no code of its own; its own status is
   derived** — the worst of its entries' codes, `UNDEFINED` ignored, suppressed
   entries contributing nothing, the silenced-versus-unreported tiebreak as in
   [ADR-0039](0039-status-rollup-semantics.md) rule 5. This is not a new mechanism:
   ADR-0036's decision 7 already calls entries *virtual children* and already says
   the node's own status is the worst of what is left. Coded entries make that
   sentence literally true rather than trivially true — `effective_code` unchanged,
   over virtual children. Every claim the node makes is attributable to a line
   ([ADR-0032](0032-status-contribution-boundary.md) rule 5); a check that wants to
   say something its entries do not cover says it *as a line*.
4. **An entry-bearing node with no entries this run reads `OK`.** The check ran,
   enumerated, and found nothing; "nothing to report" is not "nothing reported".
   Strict derivation over an empty set would give `UNDEFINED`, so the empty set is
   the one place the derivation carries a stated default, and this is it. A check
   that *could not* enumerate reports **prose** with a declared code — the split
   falls along the members/prose line ADR-0036 already drew: **members ⇒ derived,
   empty means `OK`; prose ⇒ the check declares.** The engine's failure path is
   therefore untouched: `check error:` is prose and stays a declared `ERROR`
   ([ADR-0040](0040-what-a-failing-check-becomes.md)).
5. **Declaring both is refused, loudly, at the `CheckResult` seam** — the repo's
   habit for a field that must not be set (a check YAML naming `name:` is rejected
   the same way). A silently ignored code would leave the author believing a status
   they are not getting.
6. **A per-entry `running` flag carries "work is in flight", as display.** It
   renders as a CSS class on the line (`is-running`, italic) — the pattern
   suppressed entries already use — never as Markdown emphasis in the check's text.
   It has **no severity and never touches the roll-up**: a running line's code is
   still the last completed run's verdict, so a red line whose job is re-running
   stays red, visibly rebuilding. The words still carry the meaning (`#4215 running
   2m`); the italic is the glance, not the channel — one sensory channel may not
   carry a fact alone ([ADR-0024](0024-dashboard-layout.md)'s cue rule). `running`
   and quiet compose; they are different channels.
7. **The check-facing shape is a named value object** — `Entry(slug, text,
   code=None, running=False)`, frozen, accepted wherever a `(slug, text)` pair is.
   The tolerant forms (`str`, `list[str]`, mapping, pairs, `entries=True`) stay
   exactly as they are, so no existing check moves. Two optional attributes is
   where positional pairs run out; a third field must argue for itself harder than
   the second — ADR-0036 deliberately kept an entry from becoming a node, and a
   value object makes creep cheap.
8. **Healthy entries are opt-in, per aspect, off by default** — an alarm surface
   stays an alarm surface unless a deployment asks otherwise, and one check's
   aspects do not all want the same answer. **A run in flight always produces a
   line in the default view**, even when healthy entries are off and even when the
   last run passed: seeing what is running is guaranteed, seeing what is idle and
   fine is opt-in. `hide_ok` may hide a healthy running line — an operator who
   asked to see only problems has asked not to see it.
9. **Ordering becomes load-bearing, and is the check's duty:** non-`OK` first, then
   in-flight, then healthy-and-idle — otherwise `reason_cap`
   ([ADR-0024](0024-dashboard-layout.md)) folds the failures below the chevron on
   exactly the crowded card where it matters.
10. **How a source severity maps to our codes stays deployment configuration** (a
    `severity_map`, grading a band or a line); whether lines carry codes at all is
    **not** configurable — it is the check's structural statement about its data,
    declared by the shape of what it hands over, like members and prose. A knob
    that let a deployment flatten real per-line severities would be a wrong
    statement, not a preference.
11. **The JSON envelope changes nothing here.** `reasons` stays `[str]`; the
    per-entry object — text, maintenance, `code`, `running` — is the client
    contract round's one `schema_version` decision, and nothing ships piecemeal
    before it ([ADR-0008](0008-json-output-api.md)).

## Consequences

- The severity-banded pattern and coded lines are complementary, and the rule of
  thumb is: **split the node when the group is what an operator acts on; code the
  line when the finding is** — especially when its state can move, because a
  severity in the *path* strands the pin each time it changes, while a coded line's
  slug holds still.
- Hand-computed node codes ("if errors and code is OK: code = WARN") retire from
  each check as it opts in.
- With always-present lines, a pin on an entry that has since gone green stays
  *applied* rather than suspended — quietly silencing an `OK` line, and the "N of M
  in maintenance" count reads oddly. Known and accepted; absence-suspends-a-pin
  (ADR-0036 decision 6) is unchanged.
- Per-line status ink lands on pale tints, on vivid fills and in every theme — the
  surface class that has already produced one AA regression. The implementing slice
  decides the line's surface treatment (the precedent: paint your own tint) and
  extends the gate's contrast test and the browser sweep **in the same change**.
- ADR-0036 decision 8's cap-not-`escapes` rule for entry pins stands for now; its
  premise is narrowed, not its effect, and the pin-policy design pass owns the
  re-examination.
- Per-entry appear/resolve events stay out of the bounded log, as before — coded
  entries will invite them, and a two-hundred-entry check would wrap the deque.

## Alternatives considered

- **A `RUNNING` status code** — rejected. The field is one-valued and the facts are
  two: showing the phase makes the failure disappear for the forty minutes somebody
  is most likely to be looking — the destroyed-reading mistake
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) just removed, re-created a
  release later. It has no defensible rank (ignored ⇒ the root goes green *because
  work is happening*; between `OK` and `WARN` ⇒ a CI-heavy tree is permanently
  amber; below `OK` ⇒ inert under worst-of). The one case where the phase is the
  whole truth — a job that has **never** completed — is already `UNDEFINED`. And
  the cost is mostly silent: beyond the loud `worst_of` / copy-icon /
  roster-assertion failures, an unknown code paints red in `_status_alert`'s
  fallback, draws the never-reported ring, collapses to a quiet chip, evades both
  hide filters, and matches no CSS fill — which the contrast gate would not catch.
  What would reopen it: primary consumers that can render only a color (a
  traffic-light wall); a marker reaches none of them, a code reaches all of them
  for free. That is not the case today.
- **An `INFO` band as a code** — the same objections, generalized; collapsed onto
  `WARN` by decision 1 instead.
- **Expressing "rerun in progress" as a maintenance pin** — rejected. A pin is
  admin-authored suppression ([ADR-0014](0014-maintenance-persistence.md)); a check
  that can pin itself can silence itself, the hole
  [ADR-0032](0032-status-contribution-boundary.md) rule 6 closes. A pin *hides*
  and a running run should be *shown* — and in the concrete form, the pin would
  suppress the failure so that a failed rerun alarms nobody until it expires.
- **Markdown emphasis (`*…*`) as the running channel** — rejected: a convention
  rather than a channel, and `shorten()` is link-aware but not emphasis-aware, so a
  clipped line renders a stray asterisk on exactly the crowded card where the
  budget bites.
- **A second entry for the in-flight run** — rejected: it churns the entry set on
  every push, and absence-suspends-a-pin leaves suspended pins behind each one. If
  ever wanted, its code is `UNDEFINED` — a run that has not concluded has not
  reported.
- **Making "may lines carry codes" a deployment knob** — rejected as a wrong
  statement about the data (decision 10); the wishes it would serve are already
  served by the `severity_map`, by the aggregation clamp, and by display.
