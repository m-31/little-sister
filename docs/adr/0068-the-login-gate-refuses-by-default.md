# ADR-0068 — The login gate refuses by default, and every route is classified

- **Status:** Accepted
- **Date:** 2026-10-10 (accepted 2026-08-29)
- **Related:** [ADR-0020](0020-user-list-location.md) /
  [ADR-0046](0046-user-list-from-the-configuration-roots.md) (where the login list comes
  from), [ADR-0008](0008-json-output-api.md) (the bearer token `/status` also accepts),
  [ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md) (the route that
  made this necessary rather than tidy),
  [ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md) (the series read, whose
  two routes choose their own credential as `/status` does)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

*Who is this request* was answered by `session['username']`, read directly in fourteen
views. Thirteen of them opened with the same two lines; the fourteenth wrote its own
variation. The admin gate was two more copies, and every page's template arguments read
the session again.

Two things follow from that, and only one of them is the obvious one.

The obvious one is duplication: fourteen copies of a rule are fourteen chances to write
the fifteenth view without it, and nothing fails when somebody does. **The other is
worse and is about the set rather than the copies** — there was no way to ask the
application which routes answer without an identity. The answer was *whichever views
happened to check*, discoverable only by reading all of them, and true only until the
next one was written.

That was survivable while every route was written in this repository by somebody who
would notice. It stops being survivable twice over. `/health` deliberately answers a
load balancer holding no credential
([ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)), so "ungated" is
now a design position rather than an oversight and deserves to be written down. And an
identity provider supplied from outside will be able to send an unidentified request
wherever it likes — to Keycloak, say — which means it would send the health check there
too, the load balancer would see a redirect, and it would kill a target that is serving
perfectly.

## Decision

### 1. One gate, in `before_request`, refusing by default

A single hook asks two questions — does this endpoint need an identity, and is there
one — and refuses if the answers are yes and no. It replaced fourteen copies.

**The polarity is the decision, not the deduplication.** A decorator each view opts into
reads identically on the page and fails the other way: forget it and the route is open,
silently, and nothing in the application says so. The hook is the reverse — a route
added tomorrow is closed until somebody puts its endpoint on a list, and that edit is
where the question *should this be open?* gets asked. The failure mode of forgetting
becomes a locked door rather than an open one, and a locked door reports itself the
first time somebody tries it.

### 2. Two named lists, and the second one exists so nobody misreads the first

- **`OPEN_ENDPOINTS`** answer with no identity at all, each for a stated reason: the
  login form and the stylesheet it is drawn with; logout, which has to work when the
  session is already gone; the violation-report endpoint, which receives from pages that
  may have had no session ([ADR-0048](0048-an-assembled-content-security-policy.md) §6);
  `/health`; and the two redirects, for two different reasons — `/` lands on
  `/status`, which refuses on its own account, and `/favicon.ico` lands on the
  packaged icon, which is `static` and therefore already open.
- **`SELF_AUTHENTICATING_ENDPOINTS`** contains three routes, each serving a page to a
  session *and* a read of the JSON API to a bearer token, choosing by content
  negotiation ([ADR-0008](0008-json-output-api.md)): `/status` serves the dashboard and
  the status read, and `/series` and `/series/<path>` serve the Series index and a
  node's Series view, and the series read
  ([ADR-0122](0122-a-series-is-read-over-the-api-as-it-stands.md) decision 8). A gate in
  front of one would redirect an API client to a login page. Each refuses both ways, in
  its own view, after the negotiation that decides which credential applies.

Two lists rather than one because the routes on the second are **not open**, and a
single list called "the ungated ones" would say that they are — to a reader, and
eventually to somebody deciding it is safe to add a route beside them.

### 3. `current_user()` answers, `signed_in()` insists

`current_user()` returns an `Identity` or `None`, and `None` outside a request context
is not an error — a context processor may run without one.

`signed_in()` is for a view already behind the gate, and answers **401 rather than
redirecting** when there is nobody. Reaching it without an identity means the route is
on the wrong list, not that a person needs to log in, and sending them to a form that
will not fix it turns a misconfiguration into a loop.

### 4. `Identity` carries a name and one role

`name` is the stable identifier a pin, an event and an authorship line are recorded
against, so it is never a display choice. `admin` is the only role, because two is what
the routes actually gate — anything finer would be this library guessing at a
deployment's own vocabulary, which is the guess the identity work exists to stop making.

## Consequences

- **Nothing about what a visitor sees changes.** The same routes redirect, the same two
  answer `403` to a viewer, and the existing suite passes unchanged — which is the
  strongest available statement about a refactor of a gate.
- **A new route is closed until it is classified**, and the test that enforces this
  compares the two lists against `app.url_map` rather than against paths typed into a
  test, so it fails on the day a route is added rather than on the day somebody notices.
- **The seam this is groundwork for has one function to replace.** What an unidentified
  request gets is `challenge()`, called from one place — a redirect to the login form
  today, and the whole of what a provider would substitute to send somebody elsewhere.
- **`little_sister.identity` is not on the promised surface** (§11) and the check-type
  API epoch does not move. It is internal until there is a provider contract to publish,
  and publishing a shape before it has a second caller is what costs a release.

## Alternatives considered

**A `@requires_login` decorator on each view.** Fewer moving parts and the wrong
polarity: it deduplicates the copies while leaving the set of open routes exactly as
undiscoverable as it was, and it fails open.

**Keeping the inline checks and adding a test that greps for them.** Enforces a shape
rather than a property, and passes the day somebody writes the check slightly
differently.

**One list, with `/status` on it.** One fewer name and a standing invitation to read
`/status` as open, which it is not.

**Deriving the gated set in the test from the two lists.** Would make the test pass
automatically for a new route — which is exactly the failure it exists to prevent. The
gated set is written out so that adding a route breaks it.
