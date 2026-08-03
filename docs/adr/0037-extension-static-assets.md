# ADR-0037 — Extension static assets: a filler may ship CSS and JS

- **Status:** Accepted
- **Date:** 2026-08-02
- **Related:** [ADR-0034](0034-template-slots-for-dependent-packages.md) (the slot
  seam this lifts a stated limit from),
  [ADR-0030](0030-curated-links.md) §3 (the icon route's sandbox and package-data
  serving, copied here on purpose),
  [ADR-0035](0035-registering-a-config-aspect.md) (the sibling seam — where an
  extension's *configuration* goes),
  [ADR-0038](0038-declarative-action-list.md) (the library's own filler, which needs
  none of this and is the reason the limit was survivable so long),
  [ADR-0029](0029-per-user-presentation-preferences.md) (the kiosk, which loads none
  of it), [ADR-0008](0008-json-output-api.md) (untouched: assets are presentation)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0034](0034-template-slots-for-dependent-packages.md) recorded a limit rather
than solving it:

> **An extension can only render link-shaped and inline-styled interactions today.**
> A filler's template may contain a `<form>` posting to the deployment's own
> endpoint, or inline `style=`, but it cannot ship a `.js` file — the seam has no way
> to serve one.

That was right at the time: the first consumer was a pre-filled issue-creation URL,
which is a link. It stopped being right when the roster gained
[`node.actions`](0034-template-slots-for-dependent-packages.md) — an action whose
subject is a whole node is the one that wants a dialog, because "file a ticket about
this node" has a title and a body to compose before it posts, and composing them is
code.

The note that scoped this seam set out what it needs: a route serving a registered
package's own data, a cache-busting answer that tracks the *extension* rather than
little-sister, a decision about whether an extension may add a `<script>` to a page
it does not own, and the Content-Security-Policy question, which such a seam makes
materially harder — because a nonce or an allowlist would then have to cover code the
library never saw.

## Decision

A registered package may declare stylesheets and scripts; little-sister serves them
and puts the tags on the page.

1. **`slots.register_assets(package, *members)`**, beside `register`. Assets belong
   to the **package**, not to one filler: a package that fills both slots with one
   stylesheet says so once.
2. **A bare member name inside the package's `static/` directory.** No separators,
   no `..` — the icon pack's sandbox verbatim ([ADR-0030](0030-curated-links.md) §3).
   An extension cannot name a path, so it cannot reach outside what it ships, and
   the route looks a request up in the registry rather than building a path from it.
3. **`.css` and `.js` only.** A short allowlist: these two are what a filler needs to
   look like part of the product and to run a dialog, and every addition widens what
   an extension can put into a page it does not own. **No images** — an icon already
   has a home ([ADR-0030](0030-curated-links.md) §3), and one seam per job.
4. **The library emits the tag, never the extension.** A registered asset becomes a
   `<link>` or a deferred `<script>` in *our* header, once per page, in registration
   order — after our own stylesheet, so a filler builds on the design tokens rather
   than fighting them, and `defer` so a script runs after the document is parsed and
   after Bootstrap's end-of-body bundle. This answers the one question the scoping
   note left explicitly open: an extension writing its own tag would be deciding load
   order and caching for a document it cannot see, and would have to re-derive the URL
   and the cache-busting in every filler.
5. **Served from our own origin**, at `/ext/<package>/<member>`, read through
   `importlib.resources`. Never a third-party URL, and never proxied from one. This
   is a **security decision, not a convenience**: same-origin is what keeps a future
   `script-src 'self'` able to cover an extension's code without a nonce for
   something the library never saw. A seam that let a filler point at a CDN would
   make the CSP question strictly harder, which is exactly the risk the scoping note
   named.
6. **The URL carries a content hash** — eight hex digits of the asset's SHA-256,
   taken at registration — and the response is cached hard and immutable. This is the
   *"the extension's version, not little-sister's"* the scoping note asked for,
   answered more precisely than a release version can: little-sister's version says
   nothing about whether this file changed, and the extension's release version says
   it only coarsely.
7. **Login-gated, like every other surface.** An extension's script is written for
   the deployment's own operators and its source can name their internals.
8. **The kiosk loads none of it.** It renders no slot
   ([ADR-0034](0034-template-slots-for-dependent-packages.md)), so there is nothing
   for the code to drive; the same rule, in the same place, decides both.
9. **Every refusal is a warning and a skip.** A mistyped member, a type we do not
   serve, a file that did not ship — each costs the deployment its asset and not its
   monitoring, exactly as a bad filler registration does.

## Consequences

- A slot filler can now be an interaction rather than only a link — a dialog that
  composes an issue title before posting, a chip that reveals detail in place.
- **The CSP question is not answered here, and is now easier.** There is still no
  `Content-Security-Policy` header at all, so this slice makes nothing worse.
  Decision 5 is what it buys the future: because every extension asset is same-origin,
  a `script-src 'self'` covers them, and the remaining work is little-sister's own —
  the inline theme-bootstrap script in `_header.html` needs a hash or a nonce, and
  the CDN that serves Bootstrap needs naming.
- **An extension's code runs with the page's full authority.** There is no sandbox
  beyond the origin rule: a registered script can read the DOM and the session's
  cookies. That is the same trust a deployment already places in its own check types,
  which run in-process — but it is a wider door, and it is worth saying plainly that
  installing an extension is trusting it.
- Registration hashes the file, so it is read once at startup. A file edited under a
  running process keeps its old digest until a restart, like every other registration.
- `/system` lists what registered, and now says whether a filler is a dependent
  package's or the library's own.
- The page pays nothing when nothing registered: an empty loop emits no tags.

## Alternatives considered

- **CSS only.** Serve stylesheets and nothing executable — the smallest, safest
  answer, and it would have let a filler look like part of the product. Rejected
  because it leaves the dialog out of reach, which is the thing the limit was blocking;
  the next consumer would have reopened this immediately.
- **Serve the bytes, let the filler emit its own `<script>`.** Less machinery in the
  library. Rejected: it is precisely the "an extension adds a script to a page it does
  not own" shape the scoping note flagged, and it would scatter the cache-busting and
  the load-order decisions across every extension.
- **Let a filler name a third-party URL** (a CDN build of its dependency). Rejected on
  decision 5: it would make the eventual CSP an allowlist of other people's origins,
  and it quietly makes the deployment's browsers fetch whatever a config file names —
  the same reason a remote icon is emitted, never proxied.
- **Version the URL from the extension's distribution metadata.** What the scoping
  note literally asked for. Rejected in favor of a content hash: the hash is exactly the
  question ("did this file change?"), needs no installed distribution to resolve, and
  cannot go stale between releases.
- **Serve from Flask's own `static` folder** by copying assets in at startup.
  Rejected: it writes into the install tree, and a read-only or zipped install has no
  such folder to write to. `importlib.resources` answers for both.
