# ADR-0038 — The declarative action list: `config/actions.yaml`

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-08-02)
- **Related:** [ADR-0034](0034-template-slots-for-dependent-packages.md) (the slot
  seam this is built **on top of**, and which rejected a config-only list as the
  *sole* answer), [ADR-0036](0036-addressable-reasons.md) (the members/prose split
  that gives the two slots their meaning, so this needs no placement rule of its own),
  [ADR-0031](0031-deployment-config-directory.md) (the `config/` tree this aspect
  joins), [ADR-0030](0030-curated-links.md) §3 (the icon registry an entry's `icon`
  resolves through — reused, not duplicated),
  [ADR-0037](0037-extension-static-assets.md) (what a filler needs when a link is not
  enough — the case this one deliberately does not serve),
  [ADR-0008](0008-json-output-api.md) (untouched: an action is presentation),
  [ADR-0100](0100-system-is-two-views.md) (the *Installed* view of `/system`, which
  lists both kinds of filler)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0034](0034-template-slots-for-dependent-packages.md) considered a config-only
action list and rejected it — **as the sole seam**:

> A configured list of `(label, icon, url-template)` can never be more than a link.
> The first consumer wants a pre-filled URL, but the second wants a dialog, and a
> config schema has no answer.

That reasoning is intact. What it does not say is that the *first* consumer should
have to write a Python package. Today a deployment that wants "open this node in our
issue tracker" must ship an importable package with a `templates/` directory and a
context provider, to express a URL with a query string. That is a tax on the ordinary
case, paid so the rare case stays possible.

## Decision

The library ships a **filler of its own**, driven by configuration.

1. **A new built-in aspect, `config/actions.yaml`**, beside `checks`, `nodes`,
   `settings`, `users` and `links` ([ADR-0031](0031-deployment-config-directory.md)).
   **Layered like the checks, not merged like the settings**: a site root *adds* its
   actions to a base root's, because an action is a whole thing and a site should not
   have to restate the base's to add one.
2. **An entry is `label`, `url`, `slot`, and optionally `icon` and `under`.**
   `slot` is one of the library's two ([ADR-0034](0034-template-slots-for-dependent-packages.md)),
   so this invents **no placement rule of its own** — `reason.actions` already means
   *about one reason* and `node.actions` *about the whole node*, which
   [ADR-0036](0036-addressable-reasons.md) settled.
3. **`url` is a template**, interpolating `{path}`, `{name}`, `{code}`, `{reason}`
   and `{reasons}`. For a per-reason action `{reason}` is that line; for a node
   action it is the node's **first** line — its summary — and `{reasons}` is all of
   them, so "file a ticket about this node" can carry the whole condition as a body.
4. **Every substituted value is percent-encoded.** A reason full of ampersands and
   quotes lands in a query string intact, and an action can never become a way to get
   markup onto a page. Only a URL is ever templated — never a label, never markup.
5. **An unknown placeholder is refused at load**, with the file, the entry and the
   accepted names in the warning. A URL still carrying `{summary}` would render as a
   button that silently sends the operator somewhere useless, and a monitoring tool
   should not have buttons that lie.
6. **`under` is a node path, compared segment-wise** — `/system/alpha` covers
   `/system/alpha/disk` and never `/system/alphaville`. It is the half of the selector
   vocabulary that is already settled; a `tag:` selector waits for node tags to exist,
   and an action written today keeps working when it arrives.
7. **It registers through the slot seam**, as a `builtin` filler, rather than being
   rendered beside it. So a configured chip and a deployment's coded one land in one
   rail in one order, `/system`'s *Installed* view at `/system/installed`
   ([ADR-0100](0100-system-is-two-views.md)) lists both (marked *built-in* or
   *extension*), and there is one render path to reason about. It is the one
   registration `slots.forget_fillers()` puts back — the posture the icon registry
   already takes with its built-in pack.
8. **`icon` resolves through the existing icon registry**
   ([ADR-0030](0030-curated-links.md) §3), so a mark a deployment dropped in
   `config/links/icons/` is usable here by name. An unknown name is an ordinary
   answer, not an error: the chip goes without one, exactly as the links page does.
9. **A malformed entry is dropped with a warning, never an exception.** One bad
   action costs its own chip and not the others, and never the monitoring.

## Consequences

- The common case needs **no deployment code at all**: an operator adds four lines of
  YAML and gets a chip on every card, or on one subtree.
- **The slot seam stays the general answer.** This is the shorthand, and it is honest
  about its ceiling: a configured action is a link. The moment one needs to compose
  something before it posts, the answer is a package filler
  ([ADR-0034](0034-template-slots-for-dependent-packages.md)) with its own script
  ([ADR-0037](0037-extension-static-assets.md)) — and both kinds share the rail, so
  a deployment can move one action across without moving the others.
- **The library now registers itself as an extension**, through the loader an
  extension uses (`ext/little_sister/…`). That is deliberate — it proves the seam on
  the library's own code, so a change that breaks fillers breaks ours first.
- The action set is read once and held for the process, like the check set. There is
  no reload; a changed `actions.yaml` needs a restart, which is what every other
  aspect asks for.
- `{reason}` on a node action being the *first* line is a judgment, logged at info
  when an action uses it without `{reasons}`. It is the summary/body split an issue
  form wants, and the alternative — all lines joined into a title — is worse.
- Nothing enters the JSON envelope. An action is presentation, and a native client
  sees nothing new.

## Alternatives considered

- **No filter at all in the first version.** Simplest, and honestly scoped. Rejected
  because a deployment's first question after seeing a chip on every card is "only for
  these nodes", and adding the filter later means a second config shape for entries
  written against the first.
- **Wait for node tags and use `tag:`.** The eventual right selector.
  Rejected as a blocker: `under:` is already frozen vocabulary, covers the case, and
  composes with `tag:` when it lands.
- **Fold it into `config/links.yaml`.** An action is a labeled URL with an icon, and
  that loader already resolves icons. Rejected: a link is navigation the *viewer*
  chose and an action is something done *to a node*. Conflating them would make the
  links page answer for both and would put node-templated URLs in a list that has no
  node.
- **Render it beside the slot seam rather than through it.** Fewer moving parts — no
  self-registration, no `builtin` flag. Rejected: two render paths for one rail means
  two orderings, two failure modes and two places for `/system/installed` to look, to
  save one boolean.
- **Template more than the URL** — a label with `{name}` in it, say. Rejected for now:
  every templated field is a new escaping question, and the label is written by the
  operator, who already knows which node they aimed the action at.
