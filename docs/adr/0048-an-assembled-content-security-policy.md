# ADR-0048 — The Content-Security-Policy is assembled, never a constant

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-08-08, decided in the design round on what a
  Content-Security-Policy would actually cost)
- **Related:** [ADR-0037](0037-extension-static-assets.md) (same-origin extension
  assets — why `'self'` already covers a dependent package's *scripts*, and the
  unbounded trust this starts to bound),
  [ADR-0035](0035-registering-a-config-aspect.md) (a registered config aspect — where
  a package's own parameters live, and the shape a contribution follows),
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (the filler whose script
  reaches an origin in the first place),
  [ADR-0018](0018-markdown-rendering.md) (the renderer whose images an `img-src` would
  bound),
  [ADR-0029](0029-per-user-presentation-preferences.md) (the preferences form whose
  inline handlers this displaces),
  [ADR-0031](0031-deployment-config-directory.md) (`config/` is operator input — where
  a deployment's own sources are written),
  [ADR-0100](0100-system-is-two-views.md) (the *Installed* view of `/system`, which
  shows the effective policy)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A Content-Security-Policy is one response header, and setting it is one line. That is
the whole trap: the header is a *promise about how the pages are built*, and a policy
strict enough to be worth having is one today's pages do not keep. A lenient one —
`'unsafe-inline'` — permits exactly the injected script it exists to block, so it is
free to adopt and worth nothing. The value is in the strictness, and the strictness is
what has a price.

The half that would have been hard is already paid. A dependent package's stylesheets
and scripts are served from our own origin
([ADR-0037](0037-extension-static-assets.md)) — `register_assets` refuses a
third-party URL on purpose — and `script-src` names **origins, not files**. So `'self'`
covers every filler's code, present and future, including code this library will never
see. That was the design's intent, stated in the registration docstring.

What `'self'` does not cover is where that code **reaches**. A filler that raises a
ticket calls an issue tracker; a check package may embed images from its service in the
text it reports. Those origins differ per deployment and cannot be known here. The
packaging phase, which turns check types and provider backends into separately
installable packages, only widens the set: a plugin may need `connect-src` for its own
API, `img-src` for a vendor's avatars, `form-action` for an identity provider's
redirect.

That is the decision this record exists to force. A policy hardcoded in this library
would leave such a package unbuildable or force a fork — and worse, a header shape
deployments already depend on is a breaking change to revise afterwards. The cost of
getting this right is roughly twenty lines and no user-facing surface; the cost of
retrofitting it is a compatibility break. So it is settled before the first header
ships, not after.

## Decision

1. **The policy is assembled, and assembled late.** There is no policy constant. A
   `csp` module holds the library's defaults and the contributions made to it, and
   composes the header value **at application creation** — after every registration has
   run and after the configuration is loaded. Nothing is computed at module import,
   because import is when contributions are still arriving.

2. **A dependent package contributes through a module-level registry**, called from the
   same import-before-app slot it already uses to register check types, fillers, assets,
   icon packs, aspects and secret resolvers:

   ```python
   # a package that ships a slot filler, in its import-before-app block
   from little_sister import csp
   csp.allow("connect-src", "https://api.example-tracker.com", by="ls_tickets")
   ```

   `by` names the contributor, for the readout in decision 7. A refused contribution is
   a warning and a skip, like every other registration here — a malformed source never
   prevents startup, and never silently widens the policy either.

3. **A contribution names an origin, never a keyword.** `'unsafe-inline'`,
   `'unsafe-eval'`, `'unsafe-hashes'`, `*` and a bare scheme are refused from a package.
   A package able to switch the policy off would make it decorative for every other
   package in the process, and the deployment — not a dependency — is who may decide to
   accept that cost.

4. **A deployment-specific origin is declared, not written.** A hosted tracker has a
   fixed origin, but a self-hosted one is the deployment's, and it already lives in the
   filler package's own configuration aspect. The package points at that field rather
   than repeating its value:

   ```python
   csp.allow("connect-src", csp.origin_of("tickets.base_url"), by="ls_tickets")
   ```

   resolved at assembly time and reduced to `scheme://host[:port]` — any path, query or
   fragment is dropped. A host written in two places drifts the first time a deployment
   repoints it, and the drift shows up as a blocked request nobody connects to the edit.

5. **The deployment has the last word.** A `csp` block in the deployment's own
   configuration may add sources, and is the only place a keyword from decision 3 may be
   taken at all. A source nobody anticipated is therefore a configuration line, never a
   fork — which is what makes it safe to ship a policy before we know what plugins will
   need.

6. **The first policy shipped is `Content-Security-Policy-Report-Only`.** Violations are
   logged at `WARNING`; there is no report store, so nothing here waits on the
   persistence decision. Report-Only breaks nothing by construction, which is the point:
   it reports what a strict policy *would* have caught before anyone commits to one.
   Enforcement — including which directives graduate first — is a separate, later
   decision.

7. **`/system`'s *Installed* view shows the effective policy and who contributed each
   source**, at `/system/installed` ([ADR-0100](0100-system-is-two-views.md)). The view
   already lists what registered. Without this, a request blocked inside someone else's
   package is undebuggable from here.

## Consequences

- **A check type contributes at most `img-src`, and usually nothing.** The policy
  governs the browser, so everything a check does over the network — the API call that
  is most of its work — is invisible to it: a check that talks to a hosting provider all
  day needs no `connect-src`, because no browser ever makes that request. What a check
  can reach the browser with is what it puts *in the page*. Reason lines go through the
  Markdown renderer ([ADR-0018](0018-markdown-rendering.md)) and a check author's own
  text is trusted there, so a check that embeds an image from its own service needs that
  host in `img-src` — and a disk-space or HTTP-probe check never mentions the policy at
  all. `connect-src`, `script-src` and the rest belong to packages that ship a
  **filler**: code that runs in the page.
- **The packaging phase inherits this unchanged.** Discovery through entry points
  changes *when* registration happens, not what it does, and assembly already runs
  after registration. No plugin-specific machinery is needed, and none is added here.
- **A dependency can widen the policy for the whole application.** That is not a new
  trust boundary — [ADR-0037](0037-extension-static-assets.md) says plainly that an
  extension already runs with the page's full authority — but it becomes *visible*, on
  `/system/installed`, rather than implicit. This is the first written bound on what an
  extension may do to a page.
- **The header is a value, so it is testable without a browser.** The assembled policy
  can be asserted in a unit test: defaults present, a contributed origin accepted, a
  contributed keyword refused, a configured source added.
- **Nothing is enforced by this record.** No page changes behavior when it ships.

## Alternatives considered

- **A constant header string.** The cheapest thing to write, and wrong on first
  contact: a dependency needing an origin has no way to express it, and revising the
  shape of a header deployments already rely on is a compatibility break. The saving is
  about twenty lines; the retrofit is a version boundary.
- **Configuration only — the deployment writes the entire policy.** Moves the burden
  onto the operator, who would have to know what every dependency needs. A package
  knows its own requirements and nobody else does. Kept as decision 5's escape hatch,
  where it is a supplement rather than the mechanism.
- **A package writes literal origins for deployment-specific hosts.** Simpler than
  decision 4, and duplicates a value that already lives in the package's configuration
  aspect. Decision 4 exists precisely to keep the host written once.
- **A nonce, rather than an origin allowlist, as the general answer.** Nonces do not
  apply to HTML attributes at all, so they solve none of the inline surface that
  actually blocks a strict policy; and threading a per-request nonce into filler
  templates would make it part of the slot's context contract, which is a heavier
  commitment than same-origin serving already is.
