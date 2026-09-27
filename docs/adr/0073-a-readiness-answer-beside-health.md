# ADR-0073 — A readiness answer beside `/health`, and it latches

- **Status:** Accepted
- **Date:** 2026-09-27 (accepted 2026-09-05)
- **Related:** [ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)
  (the liveness route this one stands beside, and whose bound on an ungated route it
  inherits), [ADR-0067](0067-the-run-scripts-can-serve-tls.md) §6 (the probe path,
  which does not move), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (the heartbeat, and the zero-checks `WARN` this follows twice),
  [ADR-0043](0043-coverage-backstop.md) (an empty scope is never silently green —
  the same argument one scale up),
  [ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md) (the
  doors, and the instance that registered none),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the seam the lines ride),
  [ADR-0091](0091-an-import-is-not-an-instance.md) (the server's start, which starts the
  engine), [ADR-0090](0090-one-state-directory-one-writer.md) (the lease whose loss is
  the third line)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) answered *is this
process serving* and deliberately stopped there. It also said which question it was
declining: a load balancer's *should traffic go here* is not *is everything well*, and
the two come apart in the case that matters — a check configuration that will not load
leaves this application serving on purpose, because the operator needs the dashboard
most on the morning it is broken.

That left the other half unanswered, and a deployment then went to production and
found it. Two failures came out of the stress deployment's first container rollout,
and both were **silent in exactly the same way**: the instance was serving, `/health`
said `200` with a `running` engine, and nothing anywhere said the instance was not
fit to be observed through.

- The image was built without its distribution's CA certificates. The default TLS
  context therefore loaded an **empty trust store**, and every check that reads an
  `https` address failed on the certificate — as did the identity provider's
  discovery document. Twelve checks reported twelve unreachable subjects. The one
  thing none of them said is that the fault was here.
- The engine came up `running` with a configuration whose **every check errored**.
  Each node was correctly red about its own subject, and the pattern — twelve
  failures with one cause — existed nowhere on any page, because no surface answers
  for the set.

Both are the failure [ADR-0043](0043-coverage-backstop.md) named at the scale of one
check — *an empty scope is never silently green* — and
[ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) named at the scale of a
configuration. This record answers it at the scale of the instance.

There is a second thing an instance can be unfit for and not say. An installation
registers its own identity doors ([ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md)),
and one that registers **none** starts, warns once into the log, and serves an
application nobody can sign in to. That warning is the only place it is said, and a
log line is not something a rollout can route on.

## Decision

### 1. `/ready`, beside `/health` and not instead of it

`GET /ready`. `200 {"status": "ready"}` once all three conditions in §3 hold; until
then `503 {"status": "not ready", "waiting_for": [...]}`.

`/health` is unchanged, and the run scripts' `PROBE_PATH` still aims at it
([ADR-0067](0067-the-run-scripts-can-serve-tls.md) §6): *did this checkout come up
and serve* is still the right question for a start script, and it is the question
`/health` answers.

**Which of the two a load balancer routes on is the deployment's choice**, and the
honest advice is not the same in both cases. Behind several instances, `/ready`:
a new instance that cannot observe anything should not be sent traffic while the
working ones are still there. Behind **one** instance, `/health`: draining your only
target takes away the page that explains why, which is
[ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)'s whole argument
and it does not stop being true here.

### 2. Readiness latches, and that is what makes it safe to route on

All three conditions are **startup facts**. Once they hold, this instance is ready
for the life of the process; the conditions are not asked again and no later failure
takes the answer back.

This is the design, not an optimization. A readiness route that could withdraw a
*serving* instance would remove the very dashboard whose banner explains what broke —
the thing
[ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) refused to build
— and a latch cannot do it. What `/ready` answers is *has this instance finished
coming up*. Whether it is still well is what the dashboard, the heartbeat and the
lines in §5 answer, to a reader who has said who they are.

So the failure mode this route has is the one worth having: an instance that never
becomes ready is never sent traffic, a rolling deployment stops on it rather than
rolling onto it, and the instances already serving go on serving.

### 3. The three conditions

- **`doors`** — at least one identity door is registered. An instance nobody can
  sign in to is not one to send readers to. Doors registered with *no default* are
  deliberately **not** a condition: that instance is usable by anybody who knows the
  address of a door ([ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md)),
  and `announce_doors()`'s warning stays the only word on it.
- **`trust`** — the machine holds a usable trust source, asked **once**, at startup,
  of the default verification paths. Asked of the paths, never of a context:
  `cert_store_stats()` counts what a context has **loaded**, and OpenSSL never loads a
  hash directory — a `capath` is consulted by subject hash when a chain is verified —
  so a populated `/etc/ssl/certs` beside a `cafile` the distribution does not create
  counts zero on an instance that verifies every connection, and the latch would keep
  it there. A source is usable when OpenSSL would read something from it: a `cafile`
  that exists and is not empty, or a `capath` holding at least one hashed entry that
  resolves to a file. What the condition asks is whether this instance can verify a
  certificate, not how many it has counted. A store that could not be measured at all
  is **not** reported as empty and does not hold readiness back: refusing to serve
  over a measurement that failed is a guess with a load balancer behind it.
- **`first-pass`** — the engine has started and run every configured check once. It
  starts at the server's start, not at the import
  ([ADR-0091](0091-an-import-is-not-an-instance.md)), so a server that never starts it —
  a gunicorn line without the library's hooks — never becomes ready. A secret-pinned
  check counts: it stores its `ERROR` without ever calling `run()`
  ([ADR-0023](0023-secret-references.md)), and a pass that waited for it would never
  end. A configuration holding no checks has completed its empty pass and is ready —
  the heartbeat already carries the `WARN` that nothing is watched
  ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)), and keeping traffic
  away as well would answer a configuration mistake by hiding the page describing it.

**An engine that is off and an engine that broke are not one answer**, exactly as on
`/health`. `LITTLE_SISTER_ENGINE=0` has no pass to wait for and is ready at once — a
deliberate quiet is not a thing to keep traffic away from. An engine that could not
load its configuration will never run a pass, and that instance never becomes ready.

### 4. What it publishes is a closed vocabulary of three words

`/ready` has **no login gate** — a probe that has to authenticate measures nothing —
so everything it says is said to whoever can reach the port, and
[ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) §3's bound
applies unchanged: a field added here is a field published.

`waiting_for` is `doors`, `trust`, `first-pass` and nothing else, ever, in that
order. The three name no path, no count, no version, no configuration and nothing
about what is monitored. They earn their place by answering the one question the
caller of an unready instance cannot answer for itself: **wait, or roll back.**
`first-pass` will pass on its own; the other two will not, and no amount of waiting
changes that.

A ready answer carries **no** `waiting_for` key rather than an empty list: absent and
empty would be the same fact said two ways, and one of them invites a caller to test
the wrong thing.

`no-store`, for the reason `/health` has it. Not part of the JSON API, not in
`api/openapi.yaml`, no bearer token and no `schema_version`
([ADR-0008](0008-json-output-api.md)) — the same argument
[ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) §4 makes, for
the same audience.

### 5. The two rollout failures, and a lost lease, are lines on `/little-sister`

A route a machine reads is not where a person looks, so both failures from the
Context are also lines on the instance's own node, beside a third, through the seam
every contributor uses ([ADR-0072](0072-the-instance-reports-on-itself.md)) —
recorded state read on the tick, pinnable as `readiness.<slug>`, clearing when their
condition does, the third excepted.

- **`readiness.trust`, at `ERROR`** — *the machine's trust store holds no CA
  certificates*. A defect **here**, fixed by rebuilding the image, and the sentence
  says what it costs: every check that reads an `https` address fails on the
  certificate rather than on the subject.
- **`readiness.all-erroring`, at `WARN`** — *every check this instance runs is
  erroring, all N of them*. `WARN` and not `ERROR`, following
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)'s zero-checks beat and
  [ADR-0043](0043-coverage-backstop.md)'s empty scope: the failures are already
  `ERROR` on their own nodes, and what this line adds is a **reading of the
  pattern** — N errors are more likely one cause than N — not a second red for one
  fact. Escalating would also claim the instance is broken when the world may
  simply be down; where the cause really is the instance, `readiness.trust` stands
  beside it at `ERROR` and says so.

  It needs **more than one** check: with a single one, *every check is erroring* says
  nothing that check's own node does not, and a line that adds nothing is one
  somebody learns to skip.
- **`readiness.saves`, at `ERROR`** — *this instance runs no more checks and saves
  nothing*, from the moment the state directory's lease was taken from this instance
  and it stopped its engine and its writes
  ([ADR-0090](0090-one-state-directory-one-writer.md) decision 7). It is recorded
  state, read like the other two, but its condition lasts for the life of the process:
  a holder that lost the lease never runs a check again, and a restart is the way back.

Neither line is the readiness answer, and the reasons an instance did not become
ready are deliberately not lines: they are the startup log and `/system`, where a
reader has said who they are.

## Consequences

- **A rollout has something to route on that is not a login page or a liveness
  code.** The two failures that took a morning each are now a `503` naming a word.
- **A third route answers without an identity.** `identity.OPEN_ENDPOINTS` gains
  `ready`, which is the list
  [ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) said would have
  to become explicit doing its job: adding a route to it is an edit somebody has to
  justify.
- **The engine records what each check last stored.** One field per scheduled check,
  read under the engine's lock, and the counts derived from it — configured,
  completed, erroring — are what both the first-pass condition and the
  `all-erroring` line are made of. Nothing new runs on the tick.
- **A deployment behind one instance should not move its probe.** The advice in §1
  is the deployment's to take, and no check here reports whether it did.

## Alternatives considered

**A live readiness verdict rather than a latch** — re-asking the conditions on every
call, so an instance that stops being well is drained. It is what a reader expects
the word *readiness* to mean, and it is the design
[ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) already refused
under another name: the instance most worth draining is the one whose dashboard most
needs reading. Rejected, and the word is bounded by §2 instead of being redefined.

**`503` on `/health` when the engine failed, and no second route.** One route,
one answer, no new vocabulary — and it mislabels `LITTLE_SISTER_ENGINE=0`, removes
the explaining page, and still says nothing about a trust store or a first pass.
Rejected in ADR-0066 and rejected again here for the same reasons.

**Detail in the body — the failing condition's reason, the check count, the door
names.** Genuinely more useful to a person, and this route has no login gate, so it
would be useful to everybody else too. Rejected: the detail goes where the banner and
`/system` already put it, and the three words are what a machine needs.

**Making an empty trust store refuse to start.** It is a broken image and it will
never fix itself, so failing fast is defensible. Rejected: it takes down a monitoring
application over a fault it can describe perfectly — the rule
`announce_doors()` already applies, that a contradiction refuses and an omission
says so.

**`readiness.all-erroring` at `ERROR`.** Fail toward alarming, and the instance
really is observing nothing. Rejected: the root is already red from the checks
themselves, so the escalation adds a colour and no information, and it would claim
an instance fault in the case where the world is simply down.
