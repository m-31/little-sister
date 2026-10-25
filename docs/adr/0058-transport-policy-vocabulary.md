# ADR-0058 — `little_sister.transport`: a vocabulary for asking something that might not answer

- **Status:** Accepted
- **Date:** 2026-10-24 (accepted 2026-08-15)
- **Related:** [ADR-0049](0049-the-check-authoring-surface.md) (the surface this adds
  five names to, and its add-is-compatible rule),
  [ADR-0051](0051-what-startup-refuses.md) (the epoch those names sit in),
  [ADR-0033](0033-budgeted-failure-retry.md) (the *other* retry — the engine's,
  between runs; this one is inside a single run and they must not be confused),
  [ADR-0042](0042-entries-carry-their-own-code.md) (the entry vocabulary a
  classification is eventually read into),
  [ADR-0039](0039-status-rollup-semantics.md) (why the mapping to a status code is
  *not* in this record),
  [ADR-0011](0011-ssh-check-family.md) (the module renamed here, to free the word
  `transport` for what it is about),
  [ADR-0054](0054-python-floor-and-development-version.md) (the floor this module
  stays well below)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check type may live in a package of its own and upgrade on its own schedule, so
everything it writes against is promised by name
([ADR-0049](0049-the-check-authoring-surface.md)). **Nothing on that surface says
anything about a request that fails** — and a check that reads a remote API has four
questions to answer before it can report anything at all:

- how long may **one request** take;
- what bounds **the whole run**, when one `run()` asks fifty times;
- what is worth **asking again**;
- and what a failure **means** — whether the reading is wrong, or merely absent.

With nothing promised, every such check answers all four for itself. Two checks in one
status tree then disagree about what a `500` is, an author reading one of them learns a
rule the other does not follow, and none of it is visible in the tree. The library is
the only place a single answer can live.

**A client is not that answer.** The call shapes genuinely differ — one check reads a
single URL, another posts GraphQL, another walks a paginated `Link` header — and a
`Client` class fitting all of them would fit none of them well. More decisively, a check whose transport is a **vendor
SDK** (boto3 for a CloudWatch reading, an OIDC client, anything with its own connection
pool and retry mode) cannot reach a shared client at all, while still needing all four
answers above.

**Nor is a general-purpose HTTP library.** `requests` spends its read timeout "between
bytes sent from the server"; `httpx` spends its as "the maximum duration to wait for a
chunk of data to be received"; neither ships a total-request timeout. A server dribbling
bytes defeats both exactly as it defeats `urlopen(timeout=…)`, whose bound is one socket
operation. Whatever client a check holds, **the wall clock is the check's own to keep** —
so the deadline is the expensive part of this and the transport is the cheap part. (What
a real client buys is connection reuse, redirect, proxy and TLS handling. That is an
argument for a particular check-type package taking a particular dependency, and it
stays open to one. It is not an argument for this library taking one: a deployment
installs several packages that each declare a floor here, so a dependency added here is
added to all of them.)

**And what a failure means cannot be shared, even though its classification can.** A
`http` check reports `ERROR` when a URL will not answer, and it is right to: the endpoint
**is the subject of its measurement**. A check that reads an API to grade something else
must *not* grade that thing when the API is unreachable: there the endpoint is the
**instrument**. Same failure, opposite consequence, decided by what was being measured —
so anything mapping a failure straight onto a `StatusCode` would be wrong in one of those
two places by construction. The library already states this distinction, one layer down:
the SSH transport "reports **facts**, not verdicts … leaving a completed run — whatever
its exit code — for the *check* to interpret."

## Decision

**One module holds the policy vocabulary; every client wears it; no client is shared.**

1. **`little_sister/transport.py` is the vocabulary, and holds nothing else.** It is
   stdlib-only, performs **no I/O**, and imports nothing from `little_sister` — for the
   reason `errors.py` gives for its own existence: importing the `checks` package
   registers every built-in check type as a side effect, which a module used by a
   built-in check and by an installed package has no business triggering. Five names, and the smallness is deliberate: a promised name is
   permanent, so this is the whole of it.

   The word is claimed here because *transport policy* is what this is, and therefore
   where a reader will look for it. **The SSH package's `transport.py` is renamed
   `connection.py`** ([ADR-0011](0011-ssh-check-family.md)) — the better name for what
   it holds anyway: `SshConnection`, a value object carrying one host's parameters and
   turning them into an `ssh` argv. Two modules called `transport` in one distribution,
   meaning different things, is how divergence starts.

2. **`Deadline` — when this run must stop, and how much of it is left.** A duration and
   an **injectable clock** defaulting to `time.monotonic`, so a test can drive a budget
   without spending one and the whole run reads *one* clock (mixing wall and monotonic
   time makes the budget jump when the machine's clock is corrected). It offers
   `elapsed()`, `remaining()`, `expired()`, and the two methods that carry the knowledge
   rather than leaving it at the call site:

   - **`budget(timeout)` → `min(timeout, max(0.0, remaining()))`** — the socket timeout
     for the next request: its own, *clamped to what is left of the run*. Without the
     clamp a 15-second request may start with two seconds of budget left and overrun the
     run by thirteen, which makes a deadline a suggestion rather than a bound.
   - **`affords(wait)`** — whether a pause of `wait` leaves the run able to do anything
     afterward. A retry certain to be cut off spends the backoff to learn nothing.

   A check builds one from its own common `timeout_seconds` at the top of `run()`. The
   engine does not bound `run()` and never claimed to — `architecture.md` §4.6 says
   only that "the built-in checks honor their own timeouts, and custom checks must
   too" — and *what* a
   check's `timeout:` bounds was never actually stated. It is stated here: **the whole
   run**, one request at a time inside it. A check that spends it as a socket timeout
   instead has hundreds of budgets and no bound.

3. **`DeadlineExceeded` is not a `RemoteError`, deliberately.** The run-level fact must
   not be catchable by the per-item handler. A check reporting one child per repository
   catches its own error per repository and turns it into a line; if the deadline
   arrived as that same class, one run-level fact would be spelled as forty item-level
   ones. It propagates past those handlers, so a run keeps what finished and says
   **once** that it was cut short.

4. **`Fault` — a three-state reading of what went wrong, set by status and never by
   message text.**

   | member | means | asking again |
   |---|---|---|
   | `TRANSIENT` | we could not ask — a 5xx, a timeout, a transport failure | could change the answer |
   | `ANSWERED` | they answered, and the answer was no — a 4xx: absent, or not visible to this credential | cannot |
   | `MALFORMED` | they answered, and the answer was unusable — a payload of the wrong shape | cannot; the shape will be the same |

   **Three states, not a boolean.** A boolean spells a malformed payload — no status,
   not transient — identically to a `404`, and those grade differently: a `404` is a
   fact about the thing being measured, while a list arriving where an object was
   promised is a fact about the reading, or about the API. A check cannot report a
   difference its error type cannot carry.

5. **`RemoteError(message, *, status=None, fault=…)`** carries the status when there is
   one and the `Fault` always. **`fault` is required and has no default**: the
   classification is the decision this vocabulary exists to make consistent, and a
   default is that decision taken by whoever forgets to pass it — in one direction
   spurious retries, in the other grading a node for someone else's outage. It is
   designed to be **subclassed**, so a check-type package keeps its own error class, its
   own message prefixes, and every `except` clause it already has.

   **`RemoteError` also carries `retry_after: float | None = None`.** The `Fault` stays
   `TRANSIENT`, because *asking again could change the answer* is exactly what a
   throttle means; what is new is not a kind of failure but **a number the service
   supplied**. A defaulted keyword-only argument, so every existing subclass and call
   site is untouched.

6. **`ask(operation, *, deadline=None, retries=1, backoff=1.0, sleep=time.sleep)`** is
   the one bounded retry. It calls `operation()`; before each attempt it raises
   `DeadlineExceeded` if the deadline has expired; on a `RemoteError` it re-raises unless
   the fault is `TRANSIENT`, attempts remain, **and** the deadline affords the backoff.
   `retries` counts attempts *after* the first, so the default `1` is one extra try —
   enough to separate a hiccup from a bad ten minutes, where a second would only buy a
   sharper line at the cost of the run's remaining time. `sleep` and the clock are
   injected for the same reason: the policy is testable without spending real seconds.

   **`ask` spends `error.retry_after` in place of its own `backoff`** when the error
   carries one, and the veto is the same: the wait happens only if
   `deadline.affords(...)` it. So a two-second secondary limit is absorbed inside the
   run, and a twenty-minute primary limit is refused and re-raised — because a wait that
   outlives the budget the check granted is not this module's to take.

   `operation` is an arbitrary callable, which is what makes this reachable from a check
   whose transport is an SDK. Such a check keeps its SDK's retry mode and still gets the
   two things the SDK has no opinion about: what bounds a run that asks forty times, and
   what an exhausted retry means to a status tree.

7. **The five names join the check-authoring surface** ([ADR-0049](0049-the-check-authoring-surface.md)),
   listed in architecture.md §11 as `little_sister.transport` and appended to
   `tests/fixtures/check_api_v1.txt`. Adding a name is a compatible change:
   `API_VERSION` does **not** move, and no installed package is affected until it raises
   its floor on purpose. `retry_after` joins the surface in §11 with the code; adding a
   name does not move the epoch.

8. **What this record deliberately does not decide.** There is **no mapping from a
   `Fault` to a `StatusCode`**, and no helper producing an `Entry`. That mapping is one
   line at the call site, where the check knows whether the endpoint is its subject or
   its instrument; and it also depends on a question this project has not answered —
   whether *unknown on purpose* is the same state as *not yet reported*
   ([ADR-0039](0039-status-rollup-semantics.md)) — so a vocabulary shipping a mapping
   would pin that answer by accident. Nor does this record specify a client, a request
   function, an exception tuple, or a header, redirect, proxy or response-size policy:
   those are HTTP's, and this module is not about HTTP.

9. **A service may answer *not now, ask again in N seconds*.** That is one field, one
   behavior and one helper — and, deliberately, **no fourth `Fault` member**.

   **The principle it turns on: a check and an HTTP request are different realms.** This
   module serves the second one. Its job is to make a request comfortably and bounded;
   it is not a scheduler and knows nothing about when a check runs again, what its
   frequency is, or how a failed reading is re-tried between runs — those belong to the
   check and to the engine, and [ADR-0033](0033-budgeted-failure-retry.md) governs them.
   `Deadline` is the one place the two realms touch: the check hands its budget in, and
   everything here stays inside it.

   **`fetch` offers `retry_after(headers)`**, which reads the **standard** `Retry-After`
   header and returns seconds. It accepts both forms RFC 9110 allows — delta-seconds
   *and* an HTTP-date — because that parsing is identical for every service and is easy
   to get wrong. It reads nothing else: a vendor's own headers, and the precedence
   between them, stay with the package that knows that vendor.

   **Why not a `Fault.THROTTLED`.** Two reasons, and the second settles it. A throttle
   is already `TRANSIENT` by this record's own definition. And **the status cannot
   classify it**: GitHub, for one, documents *both* `403` and `429` for both its primary
   and its secondary limit, while a bare `403` also means *this credential may not see
   it* — so the discriminator is a set of vendor headers, and only the package that
   speaks that vendor's dialect can read them. A member the library could never itself
   set is a strange thing to promise, and unlike adding a *name*, adding an enum
   **member** breaks every exhaustive match on `Fault` that already exists, here and in
   code we do not own.

   **`fault_for` classifies `429` as `ANSWERED`.** A `429` with no `Retry-After` may be
   crawler protection with no stated end, and the safe default for something running
   unattended forever is not to press a service that is already complaining about
   volume — GitHub warns that continuing while limited may get an integration banned. A
   package that knows better classifies it itself, which is the whole shape of this
   record.

10. **The bounded chunked read closes the hole `urlopen(timeout=…)` leaves open**, so
    that a server dribbling a byte at a time no longer escapes it — and it is `read1`,
    not `read`, that makes that true. A loop that consults the deadline between chunks
    is not enough on its own: **`read(n)` blocks until it has all *n* bytes or reaches
    the end** — so against a trickle the first call does not return until the whole body
    has arrived, and the clock is then consulted once, after the overrun it was there to
    prevent. Measured against a real socket dribbling one byte every 200 ms, a
    **1.5-second budget raised `DeadlineExceeded` after 7.8 seconds**. What that bounds
    is a *large* body, which is a different promise.

    `read1(n)` hands back what has actually arrived. The same measurement stops at 1.6
    seconds. `_CHUNK` is, with `read1`, a ceiling on one read rather than a target, so a
    fast large body still costs one iteration per 64 KiB.

    **A test double is what hid it, and that is the part worth remembering.** That test
    answered `read` with one byte immediately, where a socket blocks; the loop turned
    freely, so the test proved the clock was *consulted* and nothing about *when*. The
    double refuses `read` outright, and a real localhost server that dribbles stands
    beside it as ground truth — asserting on how many bytes the server got to send
    rather than on elapsed time, so no machine is too slow to pass it. That is the
    suite's only socket test, because this is the one claim a double could not settle.

    **Two limits are stated rather than implied.** A caller passing `read_body=False` is
    not exposed to a slow body at all, so a deadline buys it nothing here — which is why
    **the one built-in caller was not given one**, against the expectation the roadmap
    carried: the `http` check makes a single request, so the clamp is `min(t, t)` and
    the entry check looks at a full budget, and it reads no body. A bound that does
    nothing is worse than no bound, because the next reader believes it.

    And the clock does not reach the **status line and headers**, which urllib reads
    inside `opener.open` before this module is handed a stream. A server trickling those
    is bounded only by the socket timeout per read and by urllib's own header limits,
    which together are not a bound worth the name. Closing it would mean owning the
    header parse or running the request on a thread; that is not taken on here, and it
    is the honest residual for every caller — including the two packages that do read
    bodies.

## Consequences

- **A rename lands with it.** `SshConnection` and `RemoteResult` move to
  `checks/ssh/connection.py` and the modules importing them follow. The package's public
  face does not move: both names stay re-exported from `little_sister.checks.ssh`, which
  is what the built-in checks import.
- **A check-type package may still bring its own client.** Nothing here forbids `httpx`
  or an SDK in a package that wants one; the vocabulary is what it wears, not what it
  calls.
- **No dependency change and no floor risk.** `dataclasses`, `enum`, `time.monotonic`
  and `logging` are all far below 3.11
  ([ADR-0054](0054-python-floor-and-development-version.md)).
- **The engine is untouched.** ADR-0033's budgeted failure retry re-schedules a *check*
  between runs; `ask` re-tries a *request* inside one run, in under a second, invisible
  to the scheduler. Nothing here reads or writes the scheduler, and a network backoff
  must never end up in it.
- **What the tests prove are the sentences above**, not the mechanism: that `budget()`
  clamps (a 15-second timeout with 2 seconds left yields 2), that the backoff is refused
  when unaffordable, that `ANSWERED` and `MALFORMED` are not retried, that
  `DeadlineExceeded` escapes an `except RemoteError`, and that a missing `fault` is a
  `TypeError` at construction — each proved by a mutation that makes it fail
  ([ADR-0043](0043-coverage-backstop.md) is the same instinct one level up).

## Alternatives considered

- **A shared `Client` class** — rejected. It fits none of the call shapes well, and an
  SDK-backed check could not reach it at all. The split between a shared *policy* and a
  private *client* is the whole content of this record.
- **`requests` or `httpx` as a dependency of this library** — rejected twice over: it is
  added to every deployment installing any package built on this one, and it does not buy
  the bound this work exists to provide (see Context).
- **A boolean `transient` instead of `Fault`** — rejected. It cannot express *answered
  with garbage*, which it spells the same way as a `404`.
- **Leave `SshConnection` in a module called `transport.py` and name this one something
  else** — rejected, and it was the first draft. It avoids a rename at the cost of the
  word: a reader looking for transport policy would find an `ssh` argv builder, and the
  name of the thing this record is *about* would be permanently unavailable to it. The
  rename is three imports and two doc references.
- **Put the names in `errors.py`** — rejected: that module states as its reason that it
  holds two deliberately *unrelated* classes, and a vocabulary belongs beside the
  vocabulary it is part of.
- **Bundle the retry knobs into a `RetryPolicy` dataclass** — rejected. It buys tidiness
  in a four-keyword signature and costs a sixth permanently promised name.
- **Extend ADR-0033 rather than add anything** — rejected, and it is the confusion most
  worth naming: that record is the engine re-scheduling a failing check between runs,
  driven by `retry_interval_seconds` and `retry_attempts` from a deployment's
  configuration. This is one run asking a service again inside itself. Two mechanisms,
  one word.
