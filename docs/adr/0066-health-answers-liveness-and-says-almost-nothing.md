# ADR-0066 — `/health` answers liveness, and says almost nothing

- **Status:** Accepted
- **Date:** 2026-08-29
- **Related:** [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (what this
  application already says about itself, and where a dead engine is loud),
  [ADR-0008](0008-json-output-api.md) (the token-authed JSON API this is **not** part
  of), [ADR-0048](0048-an-assembled-content-security-policy.md) §6 (the other route
  with no login gate)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Nothing here answers *is this process serving* in a form a machine can read. The run
scripts' readiness probe therefore aims at `/login` — a login page standing in for a
liveness statement, chosen because it is the one route that answers without a session.
It works, and it has always been a stand-in.

The first caller who is not a person is now real: a deployment is being containerized to
run behind a load balancer, which will health-check the instance on a schedule, from a
configuration written by somebody who cannot see our routes and holds no credential of
ours. That caller changes what the question is worth answering *for*, and two different
questions have to stop being one.

**A load balancer asks "should traffic go here", not "is everything well".** They come
apart in exactly the case that matters. When the check configuration fails to load, this
application deliberately keeps serving: the engine does not start, `engine_error` is
recorded, and every page carries a red banner naming the reason. That is the design
([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)) and it is right — an
operator needs the dashboard most on the morning it is broken. A health check that
answered "not well" there would have the balancer take the instance out of service and
remove the one page explaining why, turning a legible failure into an unreachable one.

**And this route has no login gate**, because a load balancer has no session and no
bearer token, so everything it says is said to whoever can reach the port. That is a
constraint on the design rather than a footnote: every field here is published.

## Decision

### 1. Liveness. `200` while the process serves, whatever the engine is doing

The status code answers the routing question and only that. The engine's condition is
**reported in the body**, so a probe that wants to alarm on it can, and a probe that
only decides where to send traffic is not made to care.

The loud channels for a dead engine already exist and are better ones: the banner on
every page, and `/little-sister` when the heartbeat can carry a self-report. This route
adds a third reader, not a third opinion.

### 2. Two fields, and the second is a closed vocabulary

`{"status": "ok", "engine": "running" | "disabled" | "failed"}`.

`status` is constant today, and deliberately still present: the code is the answer, the
field is the same answer for a caller that reads bodies, and a body with only a
secondary fact in it invites the wrong reading.

**`disabled` and `failed` are both "no engine" and are deliberately not one word.** The
first is a deployment that said `LITTLE_SISTER_ENGINE=0` and got exactly what it asked
for; the second is a configuration this instance could not load. Reporting them the same
would make a deliberate quiet indistinguishable from a broken one, which is the
confusion this whole application exists to remove.

### 3. What it does not say, and why each one is a decision

- **Not the reason the engine failed.** It is a `CheckError` message, and those name
  config files and check identifiers. The banner carries it, behind the login, to a
  reader who has said who they are.
- **Not the version.** `/about` names the running version and is auth-gated for exactly
  that reason: it names the version of a *live* instance. An unauthenticated endpoint
  publishing it hands anyone who can reach the port the release to look up.
- **Not the configuration, the check count, or anything about what is monitored.**

The bound on an ungated route is that it says almost nothing. A field added here later
is a field published, and that is the question to ask before adding one.

### 4. It is not part of the JSON API

No bearer token, no envelope, no `schema_version`, and it is not in `api/openapi.yaml`
([ADR-0008](0008-json-output-api.md)). The JSON API is a read-only *status* contract for
clients that authenticate; this is one line for an infrastructure probe that cannot. Two
contracts with different audiences and different lifetimes should not be one because
both happen to return JSON.

It is also **not the system-info endpoint**. Reporting engine state and version to an
authenticated client is a separate, still-open question, and this route deliberately
does not answer half of it.

### 5. `no-store`

A cached health answer is a lie with a delay on it.

## Consequences

- **The readiness probe in the run scripts can stop pretending.** `PROBE_PATH` may point
  here instead of at `/login`, which is both cheaper to render and honest about what is
  being asked.
- **One more route answers a caller that is not working through the login flow.**
  `/csp-report` was the only other one; the login form, logout, the two redirects and
  the static assets have always answered without a session as well, which is exactly
  the point of the bullet below — the set was never written down anywhere, so "how
  many are there" had no answer to check this against.
  Which paths never require an identity has been an *accident* of each route checking
  for itself — survivable while the gate is a line repeated in every view, and not
  survivable once an identity provider can redirect an unidentified request wherever it
  likes, because it would redirect this one too and the balancer would kill a target
  that is serving perfectly. That roster becomes explicit and closed when the identity
  seam lands; this route is its first member and part of the reason it must exist.
- **A deployment that wants alerting on the engine has something to read**, without a
  credential and without scraping HTML.

## Alternatives considered

**`503` when the engine did not start.** The intuitive answer, and it removes the page
that explains the failure. It also mislabels `LITTLE_SISTER_ENGINE=0`, where nothing is
wrong at all. Rejected: the status code answers the routing question, and routing is
fine.

**Reporting the failure reason in the body.** Genuinely useful, and it is a `CheckError`
message on a route with no login gate. Rejected — it goes where the banner already puts
it.

**Adding it to the JSON API, behind a bearer token.** Would fit the existing envelope
and machinery, and a load balancer has no token to present, so it would answer the wrong
audience.

**A `HEAD`-only or empty-bodied route.** Cheapest possible, and gives the caller nothing
to alarm on. The body is two fields; that is not a cost worth saving.
