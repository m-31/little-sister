# ADR-0060 — A line makes no claim; the node says it could not look

- **Status:** Accepted
- **Date:** 2026-08-15
- **Related:** [ADR-0042](0042-entries-carry-their-own-code.md) (the decision that
  put `UNDEFINED` in the entry vocabulary, and so created the collision),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up that ignores it, and the
  explicit branch status decision 3 distinguishes itself from),
  [ADR-0032](0032-status-contribution-boundary.md) (the closed vocabulary),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (freshness, which is
  what says an unrefreshed reading is old),
  [ADR-0043](0043-coverage-backstop.md) (the coverage invariant this extends, and
  decision 7's reason/subject vocabulary),
  [ADR-0033](0033-budgeted-failure-retry.md) (the retry budget, amended in decision 4),
  [ADR-0058](0058-transport-policy-vocabulary.md) (subject versus instrument, one
  layer down), [ADR-0007](0007-check-result-branches.md) (children are not pruned,
  which is what makes decision 3 free),
  [ADR-0036](0036-addressable-reasons.md) (the entry model, and the stamp decision 5
  declines to add)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`UNDEFINED` has always meant *nobody has reported this node yet* — the code a node
carries between startup and its first run, ignored by the roll-up at every grain
because a node that has not been measured must not drag a tree down.

[ADR-0042](0042-entries-carry-their-own-code.md) then let a check hand a line a code
of its own, and put `UNDEFINED` in the entry vocabulary. A check can now say *this
line makes no claim* on purpose. That is a genuinely different statement from *not
measured yet*, and both are spelled the same way.

The collision surfaces wherever a check reads one service in order to grade another
thing. `little-sister-github` ADR-0002 turns a transient read failure into an
`UNDEFINED` line precisely so a repository is not painted amber for GitHub's outage —
which is right, and which left the tree unable to tell *I could not look* from *I
have nothing to report*. Read against the code, the mechanism is uniform and
uniformly against us here: `derive_code` returns `UNDEFINED` only when no line
declares anything else; `effective_code` skips an `UNDEFINED` **own** code in favor
of a node's children; and a parent ignores an `UNDEFINED` child. Every one of those
is correct for *not yet measured*. Together, for *asked, and cannot say*, they are a
silence the operator did not choose — and in the sharpest case a severity band read
`OK` while nothing at all had been read, because a watched band is `OK` when empty.

Two further facts were found while settling this, and they are why decision 4 exists
rather than being inherited.

## Decision

### 1. No sixth code. Two sentences, on two different things

A claim withheld and a coverage failure are different statements about different
subjects, and the model already has a channel for each.

- The **line** says `UNDEFINED`: *this line makes no claim about its subject.* It is
  displayed, keyed and pinnable, and the derivation skips it, so nobody's repository
  is graded for somebody else's bad minute.
- The **node the check owns** says `WARN`: *the instrument is degraded and this
  reading is incomplete.*

That is the subject-versus-instrument split
[ADR-0058](0058-transport-policy-vocabulary.md) turns on, applied one layer up. A
sixth status code is the expensive answer — every consumer, the JSON contract, every
client and every icon — to express something two existing channels already say, and
the vocabulary is closed on purpose
([ADR-0032](0032-status-contribution-boundary.md) decision 4).

It follows that a check should not want to put a chosen `UNDEFINED` on a node it
owns. `WARN` is the truer thing to say there, and the only thing the roll-up will
carry.

How a node comes to say it depends on what else it is carrying, and
[ADR-0042](0042-entries-carry-their-own-code.md) already drew the line: declaring a
node code *and* handing over coded lines is refused at the seam (decision 5), so a
node whose lines carry codes says `WARN` **through a line of its own** and lets the
derivation do the rest, while a node reporting prose declares it directly — which is
the shape decision 4 of that record already prescribes for a check that could not
enumerate.

### 2. A node that could not look grades itself, and `WARN` is why

`WARN` and not a quieter unknown, because the quieter unknown is what fails: an
`UNDEFINED` own code is skipped in favor of a node's children, so a container that
could not look defers to children that have nothing to say. A `WARN` is counted.

This is [ADR-0043](0043-coverage-backstop.md)'s invariant reaching one case further.
That record says an **empty** scope is never silently green; this one says an
**unread** scope is not either, and both are claims about coverage, which is a thing
a node may honestly grade itself for. Like ADR-0043 this is a rule that
discovery-shaped checks are reviewed against rather than machinery the library
enforces: core cannot know what a check failed to ask.

Two properties keep it from becoming noise, and a check that adds the line should
carry both. The count is the **could-not-ask** kind only — a subject the service
*refused* already grades on its own line, and counting it twice would make the number
mean two things. And the sentence names coverage, never a subject: no repository is
named on a line that is about the instrument.

### 3. A read failure never replaces a last-known reading

The last measurement is the last truth we have. Discarding it because the next run
could not be made is a worse answer than showing it, and it is the difference between
a dashboard that degrades and one that goes blank.

This is a rule about **checks**, not a new tree operation, and the tree is why: a node
write rebinds the whole entry set, so there is no merge to reach for. What a check
does instead is **omit** the node — and [ADR-0007](0007-check-result-branches.md) does
not prune omitted children, so the previous entries and their timestamp survive
together and freshness ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md))
is left to say honestly that the reading is old.

The same rule decides what a failed **discovery** means: a check that cannot find out
what its subjects are has read nothing, so it reports its own coverage failure and
nothing else. A failure the service *answered* is not this case — a scope that is not
there, or a credential that may not look, is a defect somebody must fix and stays
`ERROR`.

This is **not** the explicit branch status of
[ADR-0039](0039-status-rollup-semantics.md), which has an updater that owns a branch
set it to `ERROR` and *drop its children* on failure, "the subtree is no longer
known". That rule is right where the branch is the **subject** of the measurement:
if the thing being reported on cannot be reached, what was under it genuinely is no
longer known. Here the branch is the **instrument** — the service that was asked, not
the thing being graded — and the subtree's last reading is still the best knowledge
anyone has about subjects that have not changed. Same distinction as decision 1, one
level up: which of the two a check is holding decides whether stale data is a lie or
the only truth available.

Re-publishing a **partial** scope — some subjects from this run, the rest carried
forward — is a different question with a real cost, and is not decided here.

### 4. The retry budget arms on news, and a withheld claim is not news

[ADR-0033](0033-budgeted-failure-retry.md) decision 2 triggers the fast retry on any
non-`OK` completion and re-arms the budget when an `OK` completes. Both halves were
reasoned, and two facts that were not available then change one of them each.

**(a) The budget re-arms on any change of the stored code, not only on `OK`.**
ADR-0033 accepted that a long outage costs `retry_attempts` fast runs and then normal
cadence. What it did not foresee is a check that is non-`OK` *as its ordinary state*:
ADR-0042 made a node's code derive from its lines, and `github-rate-limit` is a flat
node whose budget sits below a threshold for weeks at a time. Such a check spends its
retries in its first few cycles and never gets them back, so the fast second look is
gone at the moment a genuinely new failure needs it — and nothing says so, because
`/system` prints `retry n/m` only while the slot is a pulled-in one, which a spent
budget never sets again. A **change** of the stored code ends one episode and begins
another; an `OK` still does, and everything ADR-0033 says about bounding a burst
holds within an episode.

**(b) A completed run that reports `UNDEFINED` does not arm the retry.** A claim
withheld is not a failure to confirm. The live case is structural rather than
transient — `github-rate-limit` reports `UNDEFINED` for a resource the installation
gives no limit for, and asking again in ten seconds cannot change that. An
`UNDEFINED` from a run that never completed is untouched, because there is no
completion to arm anything.

This is the only narrowing of ADR-0033's trigger set, and it is deliberately one code
wide. That record chose "any non-`OK`" so the escalation counter that will sit on top
of the budget could not disagree with it about what a failure is; when that counter
lands it should skip a chosen `UNDEFINED` for the reason above, and the two still
agree.

### 5. A carried reading states its age in its own text

Where a check does show a reading older than this run, the age belongs in the line's
words. That is honest to a person and costs nothing.

Making the **tree** honest about it is a different thing and is not done here: it
would mean a timestamp per reason and a merge mode on the node write, which reverses
[ADR-0036](0036-addressable-reasons.md)'s explicit *no prune, no ownership stamp, no
completeness signal* and changes a JSON envelope other people's clients read. It is a
step toward a reason being a node, and it is recorded as a wanted thing rather than
taken.

## Consequences

- **A dashboard gets louder in exactly one case**, and it is the case that was
  lying: an aspect that read nothing renders amber instead of green.
  `little-sister-github` has deleted the paragraph in its own ADR-0002 decision 5
  that carried the defect as known.
- **Decisions 1–3 need no core change.** They are rules a check is reviewed against,
  and the two shipped checks that needed them already carry them.
- **Decision 4 is the only part that takes engine code**, and it touches two lines of
  the completion block: what arms the fast retry, and what re-arms its budget. The
  defect it removes is the one it names — a chronically non-`OK` check with no fast
  look left for the day its reading changes, and a chosen `UNDEFINED` arming one it
  cannot use.
- **The JSON envelope is untouched**, so no client needs a release. That was the
  point of refusing the sixth code.
- **`UNDEFINED` keeps its old meaning everywhere it is read.** Nothing had to learn a
  new state; what changed is what a check is expected to *say* beside it.
- Freshness still measures the check's poll and not the subject's cadence, so a node
  answering *I could not look* every minute is not stale, and is not healthy either.
  Those are now two different sentences on the node rather than one silence.

## Alternatives considered

- **A sixth status code** for *unknown on purpose* — rejected: every consumer, the
  JSON contract, every client and every icon, to say what two channels already say,
  against a vocabulary closed on purpose. The cheapest answer is not automatically
  right, but here it is also the truer one: the line and the node are making
  different claims, and one code could not hold both.
- **A flag beside the code**, or the rule *a node that has run at least once and is
  `UNDEFINED` chose it* — rejected together: both keep the coverage failure inside
  the `UNDEFINED` channel, which the roll-up ignores. The whole defect is that
  ignoring it was correct.
- **`ERROR` for a check that could not look** — rejected, following the heartbeat and
  ADR-0043 precedent: the check is working. What is wrong is the world, and the
  reading is incomplete rather than bad.
- **Grading the subject on a read failure** — rejected in `little-sister-github`
  ADR-0002 before this record existed, and this one keeps it: a repository nobody
  could ask about has done nothing wrong.
- **A per-reason `observed_at` now** — rejected for this round as too much
  complication for what it buys, and kept as a wanted thing (decision 5).
- **Doing nothing until the partial-scope question is settled** — rejected: the
  green-when-blind case is shipped and visible, and it turned out to need none of
  that machinery.
