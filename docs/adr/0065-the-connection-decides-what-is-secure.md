# ADR-0065 — The connection decides what is secure

- **Status:** Accepted
- **Date:** 2026-08-29
- **Related:** [ADR-0003](0003-config-and-secrets-via-env-file.md) (the session and
  its signing key), [ADR-0029](0029-per-user-presentation-preferences.md) (the
  presentation cookie and the view switches)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Three cookies leave this application. The **session** cookie carries a login. The
**presentation** cookie carries a viewer's theme and layout, and the **view** cookies
their render depth and filter switches. None of them was marked `Secure`, because until
now there was no connection it could have been true of: the default deployment serves
plain HTTP on a network somebody trusts, and a `Secure` cookie there is one the browser
sets and never sends back — a login page that will not stay logged in, with nothing on
the screen explaining why.

That has stopped being the only case. A deployment now terminates TLS in gunicorn, and
the same deployment will shortly run behind a load balancer that terminates the public
certificate and opens a **second** TLS connection to the instance. So a running instance
may be serving over TLS or not, and it changes without the code changing.

**The question is therefore not whether to mark the cookies but who gets asked.** There
are three candidates and two of them are worse than they look. A **configuration value**
— Flask's own `SESSION_COOKIE_SECURE` — is a second copy of a fact the process already
has, and the copy is the one that goes wrong: set it, start without TLS, and the
application locks the operator out of its own login page while every log line reads
normal. The **host name** is not an answer either: the same instance is `localhost` to
the person who started it and something else to everybody else, and a rule keyed on a
name would have to be told which names count. A **forwarded header** is the answer for a
proxy that terminates TLS itself, and it is the one that has to be *believed* — a claim
by a peer, correct only while the peer list is.

## Decision

### 1. The transport is asked, per request

`request.is_secure` — which is `wsgi.url_scheme`, which gunicorn sets from the socket it
is holding. It is true exactly when **this process** terminated a TLS connection.

That one rule covers both places this runs without knowing which one it is in: locally
the TLS socket is the browser's, behind a load balancer it is the balancer's second
connection, and in both cases the answer is arrived at the same way with nothing trusted
in between. It cannot drift from how the process was actually started, because it *is*
how the process was actually started.

### 2. Every cookie, not only the one that matters

The session cookie is the one carrying a login, so it is the one this is about. The
presentation and view cookies are marked by the same rule in the same breath — not
because a stolen theme preference costs anybody anything, but because a rule with an
exception is a rule somebody has to remember, and the next cookie added here should
inherit the flag rather than a decision.

### 3. A configured `True` still wins, and there is no way to force it off

`SESSION_COOKIE_SECURE` is Flask's setting and a deployment that turned it on meant it,
so it is honored — the transport can only ever *add* the flag. There is deliberately no
switch that removes it from a TLS connection. The cookie carries a login, and a library
that can be told to hand one out in the clear eventually is.

### 4. No `Strict-Transport-Security`

`HSTS` is scoped to a **host** and ignores the port, so a header sent from
`localhost:8443` tells the browser that every service on `localhost` is HTTPS-only for
the lifetime of the policy — the plain-HTTP instance beside it included, and every other
development server on that machine, all unreachable in that browser until somebody finds
the setting that clears it.

A library must not make a promise on behalf of a whole host name it does not own. A
deployment behind a real name and a certificate somebody trusts is in a position to make
that promise, and can set the header in front of us; that is its decision and it has the
standing to take it.

## Consequences

- **A deployment gets the flag by serving over TLS**, with nothing to configure and
  nothing to keep in step, and with **no session interface of its own on the app
  object**. That is the point of the rule living here rather than in each deployment:
  the alternative is every one of them subclassing a Flask internal and keeping it in
  step by hand, and getting the flag right is not a thing a deployment should have to
  do twice.
- **A plain-HTTP deployment is unchanged**, which is the promise this project keeps on
  every seam: whoever says nothing sees nothing.
- **An instance that served both schemes would split its preferences** — a cookie set
  over TLS is not sent over the plain connection, so the viewer's theme would appear to
  reset. There is one listener, so there is no such instance; if there ever is, this is
  the sentence to come back to.
- **Logging out clears the cookie under the same rule**, because Flask's deletion path
  asks the same question. A session opened over TLS and closed over plain HTTP would
  leave the cookie in place — an edge with no path to it while there is one listener,
  and named here rather than discovered.

## Alternatives considered

**A configuration flag, set by the deployment.** Rejected in *Context*: it is a copy of
what the transport knows, and its failure mode is silent and locks the operator out.

**Trusting a forwarded header** (`X-Forwarded-Proto`), so a proxy that terminates TLS
could say so. Not needed by either deployment in front of us — both terminate TLS in the
process itself — and it turns a fact into a claim that is only as good as the list of
peers allowed to make it. gunicorn already offers this, guarded by its own allowed-peer
list, for a deployment that genuinely has a terminating proxy in front; taking the
decision away from it and into here would buy nothing.

**Marking only the session cookie.** Cheaper by two lines and worse: it makes the flag a
per-cookie judgment call, and the next cookie inherits an argument instead of a rule.
