# ADR-0034 — Template slots for dependent packages

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-08-01)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (the import-before-app
  registration slot this reuses), [ADR-0018](0018-markdown-rendering.md) (what a reason
  is made of, and why raw HTML is escaped there), [ADR-0030](0030-curated-links.md) §3 /
  `icons.py` (the other extension registry, and the precedence rule this one
  deliberately inverts), [ADR-0056](0056-stable-useful-dashboard-flow.md) (the surfaces
  a slot appears on), [ADR-0035](0035-registering-a-config-aspect.md) (where an
  extension's *configuration* goes — the sibling seam taken in the same pass),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (untouched: a slot is
  presentation only), [ADR-0100](0100-system-is-two-views.md) (the *Installed* view of
  `/system`, which lists what registered),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (the tree,
  whose head's toolbar holds a node's actions where decision 3's `head_buttons` look
  stands it, and the frame a node's page stands in),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  (decisions 4 to 6: what a draft made from a node is written with, which both slots
  hand a filler)
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

9. **Registration is visible.** `/system`'s *Installed* view, `/system/installed`
   ([ADR-0100](0100-system-is-two-views.md)), lists slot, package, template and whether
   a provider is attached. Registration is import-order sensitive and all its failures
   are log warnings; a seam nobody can see from the running instance is
   indistinguishable from one that silently did not take.

10. **No new URL surface, no extension static assets, this decision.** A slot's output
    is HTML rendered into a page that already loads the library's own CSS and JS.
    Serving an extension's own `.js` / `.css` needs a route, a cache-busting story and
    a Content-Security-Policy answer, so it is a *separate* decision — see Consequences
    for what it costs today.

11. **The second slot is `node.actions`** — context `(node, surface, place)`, in the
    head of **every node's box** the tree draws
    ([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)), not
    only a card's — each nested box under a card carries it too — and in the frame head
    of a node's page, a leaf's framed as a branch's is. A card is the *top* of a subtree
    and is usually a container with no reading of its own, so a filler that declines a
    node with nothing to say declines exactly the nodes that have card heads, while the
    failing **leaf** — the node an action is nearly always about — sits in a nested box.
    Offered on card heads alone, the two rules, each defensible, put the chip nowhere
    the eye already was, leaving it reachable only by drilling into the leaf's own page.
    `place` — `card`, `box` or `frame` — tells a card's head from a nested box's and
    from a page's frame, and `surface` (`check` on a leaf's page, `grid` on a branch's)
    the two pages apart. The slot is rendered into every node's box, open or closed, and
    shown while it is open, so a filler is called for each node at every render; a
    **closed node** is a chip and carries none, which is the right line for a quiet
    leaf: nothing quiet is worth acting on. A slot's `where` is part of the version
    contract (§11 of `architecture.md`), so it is recorded here rather than left to the
    template.

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

    The actions stand **in the head's toolbar**, after the head's own icons — ↗, the
    folds and ‖ — with ⋯ after them, and where the toolbar stands is a look,
    `head_buttons`
    ([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision
    3): `pointer`, the library's, right after the name, the title and the state after
    it, and shown while the pointer is on the head or the keyboard's focus is in it —
    always on a touch screen; `pointer-name`, there too, with the name a link to the
    node's page in ↗'s stead; `line`, on a line of its own beneath the row; or `name`,
    at the row's end, after the state. Under the last two the actions are shown always,
    as the icons are. Where a pointer can rest on a head, the toolbar of the first two
    takes no room in the row, the title standing right after the name, and, shown, lies
    over the title on the box's own fill, covering what it covers: an action lies over
    the title again, as the rail this record set aside did, but only while the pointer
    or the keyboard is on the head, and never on a touch screen, which keeps the
    toolbar's room. An action that names an icon
    ([ADR-0038](0038-declarative-action-list.md)) is a square of the icons' shape, the
    icon alone, its label its tooltip and accessible name; one that names none keeps its
    label as a small chip, as the self-report buttons do
    ([ADR-0076](0076-the-instance-node-is-a-branch.md)); the stylesheet offers the
    square beside the chip, for a package's filler to use. The title gives way to them,
    and what does not fit even then folds behind ⋯ at the toolbar's end, so that no
    action cuts the name and none moves to a line beneath it. With ⋯ and the head's own
    icons they are one toolbar, a single tab stop the arrow keys walk, so the script,
    not a filler, sets their `tabindex`.

12. **Both slots hand a filler what a draft is written with**, beside the node
    ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
    decisions 4 to 6): `written_out(text, inline=False)`, a text of the node written out
    as the Copy document writes one — a status its braces name as its word and cue, a
    link in the short form to the absolute address of the node's handbook — and
    `details()`, the rows of the node's *About* card as `(key, value)`, those given down
    to it among them, each value written out the same way. They are functions, called by
    a filler for a draft it makes and costing nothing otherwise, since a slot is filled
    for every node at every render; `reason.actions`' context is
    `(node, reason, line, index, surface, written_out, details)` and `node.actions`'
    `(node, surface, place, written_out, details)`, grown additively (decision 1).

## Consequences

- A deployment can put a local interaction on the dashboard without a fork, and
  little-sister keeps shipping no company-specific code. The first consumer — an
  issue-tracker button on a failing leaf — is one template, one provider and one
  registered configuration aspect in the deployment repository; nothing about it is
  visible here.
- The JSON envelope (ADR-0080) is **unchanged**. A slot is presentation; a native
  client sees nothing new, and nothing about the status model moves.
- **An extension renders link-shaped and inline-styled interactions, and may ship its
  own assets.** A filler's template may contain a `<form>` posting to the deployment's
  own endpoint, or inline `style=`. It could not ship a `.js` file — the seam had no
  way to serve one — until [ADR-0037](0037-extension-static-assets.md) gave it
  `register_assets`, which serves a filler's own `.js` and `.css` content-hashed from
  the library. The link-shaped default stands, and the first consumer needs nothing
  more, because a pre-filled issue-creation URL is a link.
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

- **The rail laid over the title, veiling what it covered.** As first built: the chips
  sat in the title's space on purpose, a chip being something to click and a title a
  nicety, and the rail repainted the box's fill beneath them, quiet until the card was
  hovered — after a deployment's `+ Jira` had landed in the middle of the word
  *analysis*. In the tree's head the toolbar has a place for them, and lies over the
  title only while the pointer or the keyboard is on the head (decision 11).
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
