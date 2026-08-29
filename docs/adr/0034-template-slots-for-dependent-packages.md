# ADR-0034 — Template slots for dependent packages

- **Status:** Accepted
- **Date:** 2026-08-23 (accepted 2026-08-01)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (the import-before-app
  registration slot this reuses), [ADR-0018](0018-markdown-rendering.md) (what a
  reason is made of, and why raw HTML is escaped there),
  [ADR-0030](0030-curated-links.md) §3 / `icons.py` (the other extension registry, and
  the precedence rule this one deliberately inverts),
  [ADR-0024](0024-dashboard-layout.md) (the surfaces a slot appears on),
  [ADR-0035](0035-registering-a-config-aspect.md) (where an extension's *configuration*
  goes — the sibling seam taken in the same pass),
  [ADR-0008](0008-json-output-api.md) (untouched: a slot is presentation only)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

little-sister is a library; the real deployment lives in a private repository that
consumes it one-way and already brings its own **check types** (registered before the
app is imported) and may bring its own **icon pack**. What it cannot bring today is
**anything on the page**.

The concrete need is small and entirely local: on a failing leaf, one click that opens
the house issue tracker with a new issue pre-filled from *that* node and *that* reason
line. The parameters are a Jira project id, an issue type id and a custom field number
— facts that are true for one company and meaningless to every other reader of this
repository, so the feature cannot live here. It also cannot live outside the server:
the surface is server-rendered Jinja that swaps under a ~10s poll, so anything bolted
on by client-side script has to re-attach itself after every refresh, and anything
placed by a browser extension is not part of the product at all.

So the question is what shape the seam takes. Three properties are in tension:

- **Generality.** The deployment wants *an interaction*, not *a link*. A seam that only
  emits `<a href>` will be the wrong seam the first time somebody wants a form.
- **Safety.** A reason line is check-authored and often assembled from captured output
  (ADR-0018 escapes raw HTML for exactly that reason). Any seam that lets a deployment
  interpolate that text into HTML it builds itself re-opens what ADR-0018 closed, in
  the one place where it was hardest to close.
- **Upgradability.** The library ships and the deployment upgrades. A seam whose
  contract is "reach into our templates" makes every internal rename a breaking change,
  and makes a broken extension look like a broken monitor.

## Decision

Declare **named template slots**. The library owns the roster and the context; a
dependent package fills a slot with **a template of its own** plus an optional
**context provider**.

1. **A slot is a declared name with a declared context.** `slots.SLOTS` is a closed
   roster: a name, the exact context keys handed over there, and where it sits.
   Registering for a name that is not on the roster is refused, with the known names
   logged. A slot is a promise the library keeps, so it must be possible to enumerate
   the promises; adding a context key later is compatible, removing or renaming one is
   a new ADR.

2. **A filler is `(package, template, context provider?)` — data in Python, HTML in
   Jinja.** The template lives in the dependent package's own `templates/` directory
   and is rendered by **little-sister's Jinja environment**: autoescaping on, the
   library's filters (`markdown`, `localtime`, `status_slug`, …) and `url_for`
   available. The optional provider is deployment code that receives the slot's context
   as keyword arguments and returns the extra names its template wants. This split is
   the answer to the safety/generality tension: the deployment computes *values* —
   a URL, a label — and never assembles markup, so every untrusted byte in the context
   is escaped by the same machinery that escapes it everywhere else.

   **A provider is handed exactly what it asks for.** A context that grows would
   otherwise break every provider that spelled its keywords out — a `TypeError`,
   a logged failure, and a deployment quietly losing its chips on an upgrade of
   *ours*. So the renderer reads the provider's signature and passes the names it
   declares, or everything when it declares `**kwargs`. This is
   [ADR-0049](0049-the-check-authoring-surface.md)'s growing-fields problem reached
   from the other side: a check type must take `**kwargs` because the loader cannot
   see what a constructor wants, and here the caller *can* look — so the burden is
   ours rather than the extension author's, which is the right way round for a seam
   somebody else's code depends on. Adding a name to a slot's context stays a
   compatible change; it is compatible in fact and not only on paper.

3. **A provider returning `None` means "nothing here".** That is how a filler declines
   a node, a surface or a reason it has no action for — placement *policy* belongs to
   the filler, not to the core template. The library offers `reason.actions` on every
   reason of every node; the deployment's provider is what says "leaves only".

4. **Filling is additive and can never shadow.** Extension templates are reachable
   only as `ext/<package>/<name>`, resolved by a loader mounted **behind** the app's
   own, so no registration can replace a core template. Several packages may fill one
   slot: every filler renders, in registration order. This deliberately inverts the
   icon-pack rule (ADR-0030 §3), where later registration *wins* per name — an icon is
   one mark and only one can be drawn; a slot is a place things go.

5. **A broken filler is contained, a broken slot name is not.** A provider that raises
   or a template that will not render is logged with slot, package and template named,
   and contributes nothing; the page still renders. Monitoring must not go dark because
   a button broke. A core template naming an *undeclared* slot raises instead — that is
   our own bug and the roster exists so a test catches it.

6. **The frame is ours, the contents are theirs.** Core emits the `.reason-actions`
   rail and styles a `.reason-action` chip; a filler puts chips in it. Two extensions
   installed side by side look like one product. The rail collapses when nothing filled
   it, so a deployment with no extension pays one empty `<span>` per reason line.

7. **The first slot is `reason.actions`** — context `node` (the `StatusSnapshot`),
   `reason` (that one line, **unshortened**: the 400-character grid clamp is a display
   budget and an action wants the whole text), `index`, and `surface` (`grid` on the
   polled dashboard, `check` on the leaf detail page). It renders in both places
   because the reason does.

   The context carries one more name, `line` — the whole
   [`ReasonLine`](../architecture.md), carrying the entry's **slug**, its own `code`,
   its `running` flag and whatever is pinned on it. `reason` stays the line's
   unshortened text, and every filler written against it is untouched. The library's
   own **copy chip** is the first filler to need it: it links one line to a document
   of its own (`/copy/<path>?reason=<slug>`), and a URL needs the slug.

   Recovering the entry from `index` was possible — the surfaces pass `loop.index0`
   over the very list the slug lives in — and is precisely what
   [ADR-0036](0036-addressable-reasons.md) decision 3 refuses: an index moves when an
   entry is inserted above it, so an action built on one would silently address a
   different finding the next time the check reports, with nothing to notice it by.

8. **The kiosk renders no slot.** Decided in `app.py`, not in `slots.py`: a wall display
   is read from across a room and has nobody at its keyboard — the same reason the pin
   control is hidden there — but that is a *presentation* rule, and the seam stays free
   of presentation. Every other viewer sees the slot: filing a ticket is not an
   administrative act on the monitor, and the person who spots the failure is often not
   the admin.

9. **Registration is visible.** `/system` lists slot, package, template and whether a
   provider is attached. Registration is import-order sensitive and all its failures
   are log warnings; a seam nobody can see from the running instance is
   indistinguishable from one that silently did not take.

10. **No new URL surface, no extension static assets, this decision.** A slot's output
    is HTML rendered into a page that already loads the library's own CSS and JS.
    Serving an extension's own `.js` / `.css` needs a route, a cache-busting story and
    a Content-Security-Policy answer, so it is a *separate* decision — see Consequences
    for what it costs today.

11. **The second slot is `node.actions`** — context `(node, surface)`, on the dashboard
    grid and beside the status on a leaf's own page. It is offered on **every box the
    grid draws**, not only on card heads — each nested box under a card carries it too.
    A card is the *top* of a subtree and is usually a container with no reading of its
    own, so a filler that declines a node with nothing to say declines exactly the
    nodes that have card heads, while the failing **leaf** — the node an action is
    nearly always about — sits in a nested box that carried no slot at all. The two
    rules were individually defensible and together they put the chip nowhere the eye
    already was, leaving it reachable only by drilling into the leaf's own page. A
    **quiet leaf** is drawn as a chip rather than a box and carries no slot, which is
    the right line: nothing quiet is worth acting on. A slot's `where` is part of the
    version contract (§11 of `architecture.md`), so it is recorded here rather than
    left to the template.

    [ADR-0036](0036-addressable-reasons.md) split a node's reasons into **members**
    and **prose**, and that split decides where a deployment's action belongs. On
    members an action is about one finding and goes on the line. On prose — a failure
    message and its stack trace are one condition in several paragraphs — there is
    exactly one thing to act on and it is the **node**; a per-line control there would
    offer to raise a ticket about a stack trace.

    Both slots are offered on **every** node, and the filler declines what it does not
    want by returning `None`, so this adds a *place*, not a policy. Additive: the
    mechanism, the loader, the containment and the closed-roster rule are untouched,
    and `reason.actions` is unchanged. Core gains the `.node-actions` rail and the
    `.node-action` chip, deliberately the same chip shape as `.reason-action`: an
    action is an action, and a second visual language for one gesture would be the
    extension seam leaking into the design. The rail collapses when nobody fills it —
    a deployment with no extension pays one empty `<span>` per box.

    The `node.actions` rail in a card head **veils what it overlays**. It is
    positioned over the title's space deliberately — a chip is something to click, a
    title is a nicety — and a chip is deliberately transparent, inking in
    `currentColor` so it reads on every status fill. Two right decisions drew both
    sets of glyphs into the same pixels: a deployment's `+ Jira` landed in the middle
    of the word *analysis* and neither could be read. So every card and node box
    declares its fill as `--ls-surface` and paints from that token, and the rail
    repaints that exact fill beneath its chips — the title dissolving into it across a
    short gradient rather than being sliced mid-letter. Only while the chips are
    showing, by the same conditions that show them: a card at rest offers nothing to
    click and keeps every pixel of its title.

    Presentation only: the `reason.actions` rail — which floats beside its line and
    overlaps nothing — is untouched. Because the fill under a chip is the fill the chip
    was already sitting on, no ink meets a new background: every pair
    `test_contrast.py` measures is unchanged. The claim is about paint, so it is
    checked in paint (`tests/test_dashboard_browser.py`): the pixels inside a shown
    chip are the same image with the title there and with it hidden, and — the
    counterpart that keeps the first honest — a *different* image on a card at rest.

## Consequences

- A deployment can put a local interaction on the dashboard without a fork, and
  little-sister keeps shipping no company-specific code. The first consumer — an
  issue-tracker button on a failing leaf — is one template, one provider and one
  registered configuration aspect in the deployment repository; nothing about it is
  visible here.
- The JSON envelope (ADR-0008) is **unchanged**. A slot is presentation; a native
  client sees nothing new, and nothing about the status model moves.
- **An extension can only render link-shaped and inline-styled interactions today.**
  A filler's template may contain a `<form>` posting to the deployment's own endpoint,
  or inline `style=`, but it cannot ship a `.js` file — the seam has no way to serve
  one. This is a real limit, recorded rather than left to be rediscovered; the first
  consumer does not need it, because a pre-filled issue-creation URL is a link.
- **Escaping stays the library's.** A provider that returns a string containing markup
  gets it escaped, which is the intended failure direction: an extension that really
  wants markup has to say so in *its own template*, where the reviewer can see it.
- Slot rendering is one template render per reason line per filler. With no
  registrations it is a dict lookup and an empty `Markup`, which is what the dashboard
  pays.
- The roster is a compatibility surface now. Slots will accumulate — a card header, a
  node page section, a links-page entry — and each one added is a promise about a
  place in the templates that the next refactor has to keep.

## Alternatives considered

- **A Python callable returning `Markup`.** The obvious seam, and rejected on the one
  point that matters here: it hands the deployment the job of escaping a reason line
  assembled from captured command output. That is precisely the job ADR-0018 decided
  the library should own, and "the deployment author is responsible" is a much weaker
  promise for markup than it is for a check's own reason text. It also invites
  string-built HTML, which no reviewer reads as HTML.
- **A template search path the deployment prepends** (shadow `_reason_actions.html`
  by name). Zero new API and full Jinja power, but *any* template becomes shadowable,
  so every internal template rename turns into a silent breaking change for a
  downstream repository, and there is no roster of what is being extended. The
  `ext/<package>/` prefix keeps the power and drops the shadowing.
- **Declarative actions in `config/actions.yaml`** — label, icon, URL template with
  `{path}` / `{reason}` placeholders, rendered and escaped entirely by the library.
  Safest of all, needs no deployment code, and would have covered the Jira case
  exactly. Rejected as the *only* seam because it can never be anything but a link,
  and the ask was a frame for custom interactions. It remains an attractive thing to
  build **on top of** this seam later — as a filler the library itself ships.
- **Client-side injection** (a deployment-served script that decorates reason lines).
  Must re-attach after every ~10s fragment swap, cannot see the unshortened reason,
  and puts the deployment's markup outside every server-side safety rule; rejected.
- **A slot that renders a string returned by the provider, with no template at all.**
  Simpler by one concept, but it makes the common case (a chip with an icon and a
  label) unwritable without markup, which lands back at the callable alternative.
