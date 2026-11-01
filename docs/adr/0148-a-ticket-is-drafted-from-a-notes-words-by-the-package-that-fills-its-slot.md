# ADR-0148 — A ticket is drafted from a note's words by the package that fills the Notes tab's slot

- **Status:** Accepted
- **Date:** 2026-10-31
- **Related:**
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (template slots — a third
  slot, a draft function beside it, and the Notes tab's address on every slot),
  [ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
  (the *Notes* tab, the place to act — decisions 2 and 3 amended),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md) (the
  drawer, and what closes it — decision 3 amended),
  [ADR-0048](0048-an-assembled-content-security-policy.md) (the policy a package adds
  its tracker's origin to), [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  (decisions 4 to 6: what a draft is written with),
  [ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md) (the gate
  the route stands behind), `little-sister-jira` ADR-0001 (the package that files Jira
  issues, and the reason a draft is a link)

## Context

A package files a ticket from a node by filling a slot: `little-sister-jira` draws a
chip on a failing line, and one in a node's head, each a link to its tracker's own form
pre-filled from the node and the line — nothing created until a person presses Create
there, no credential held here. The ticket and the note never met. The draft knew
nothing of what the person wrote about the failure, and nothing brought the ticket's
link back; whoever wanted it beside the note pasted it into one, where the Notes tab
lists it among the part's tickets
([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
decision 7). The note says what the ticket says, and the place a part's tickets are
read is the place a person writes the note: the tab, which the drawer brings over the
wall ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)).

So filing moves into the tab's form, with Lex on 2026-10-31: the words written, the
button pressed, the ticket created in the tracker's tab, its link pasted into the words,
the act saved, the drawer open throughout — the words written once, the link back where
a part's tickets are read, and the earlier tickets in front of whoever files. A slot
draws when the page is drawn and cannot post, and the words exist only once they are
typed: a button that drafts from them has to send the form somewhere that makes the
tracker's address of it. The package keeps filing by a link: creating the ticket
through the tracker's API, its link written into the note by the act, would cost a
credential that writes, tickets filed under the instance's account and a permission of
their own, and waits for a deployment that wants one.

## Decision

1. **The Notes tab's form declares a slot, `notes.actions`.** It stands in the row of
   every kind's form, after the kind's own button: the kind's own stays the form's first
   submit button, its default, so that Enter in a field — *Seen*'s end, *Silence*'s
   deadline, maintenance's duration — still does the act and never opens a draft. Where
   something fills it, a line beneath the row says what the button does: a draft in a
   new tab, its summary the words' first line, and the issue's link pasted into the
   words before saving, which is what brings it back. The frame is ours, as on a line
   and in a head
   ([ADR-0034](0034-template-slots-for-dependent-packages.md) decision 6): core emits
   `.notes-actions` after the kind's own button and styles the `.notes-action` a filler
   puts in it, secondary beside it, in the text's own ink. Its context is `node`, `kind`
   — the form's, empty in the reader's — `draft_action`, the address the button posts
   to, and what every slot is handed (decision 5).

2. **Whoever may set no kind files from a small form of the panel's own.** Where a
   package fills the slot, the tab gives a reader who may set none of its kinds, and so
   no form, a form of its own in the form's place: *On* — the node and each of its lines
   — and the slot's button, drafting from the part chosen without words. It posts to the
   route in a new tab, as the button does, so in the drawer it leaves the frame. Filing
   writes nothing here, and the tracker decides who files, so no permission of ours
   gates it: filing a ticket is not an administrative act on the monitor
   ([ADR-0034](0034-template-slots-for-dependent-packages.md) decision 8). Where nothing
   fills the slot there is nothing to file with, and no form.

3. **A filler registers a draft function beside its template, and a route of the
   library's calls it.** `slots.register("notes.actions", package, template, …,
   draft=function)`: a slot that drafts takes no filler without one, and no other slot
   takes one, each a line at startup and nothing shown. The button submits its form to
   `draft_action` — `POST /draft/<path>`, the form's kind in its query — in a new tab,
   `formtarget="_blank"`, naming its package as `draft`. The route reads the part chosen
   (`slug`) and the words, a note's `text` or a pin's `note`; works out what the draft
   is about, each a `slots.DraftPart` — where it is, its line, and what it reads, every
   line written out for its own node as the Copy document writes a text: the line
   chosen; else what fails at and beneath the node as the tab lists it, a line by its
   text and a node failing by its own reading by every line it reports; else, where
   nothing fails, the node and its lines. It calls the function with the names it
   declares, as a provider is called (ADR-0034 decision 2): `node`, `path`, `kind`,
   `slug`, `parts`, `words` written out with every line break a newline whatever the
   browser sent, and what every slot is handed. It answers with a 303 to the address
   the function returns, which must be an absolute http(s) one, and never with an
   address the request carries. Where it cannot, a page of its own says why in the new
   tab, leading back to the node's tab: no node stands at the path (404), the button
   names no package or one nothing registered for (400, 404), the form names a kind
   the tab does not have (400), the line chosen is reported no longer (409), the
   function declines (200), raises — contained as a provider is, held on the
   instance's own node while it recurs — or answers with what is no such address
   (502). Whoever is signed in may: the gate stands in front of it as in front of
   every route.

4. **What a draft says is the package's.** Its summary, the markup its tracker reads
   and the bound its transport sets are the filler's, as they were the chip's; the line
   beneath the row states the convention a filler follows — the words' first line the
   summary, the words then what the part reads in the body, the Notes tab where it links
   back — and the library hands every line written out, so that a draft says what the
   page says.

5. **Every slot is handed the address of the node's *Notes* tab**, `notes_url()`,
   beside `written_out` and `details`
   ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
   decisions 4 to 6): absolute, since a draft is read outside the instance, and empty
   outside a request, as a short form stays, and on the root, which has no tab. A filler
   names no endpoint of ours to link back with.

6. **The tracker's origin is the package's to add to `form-action`.** The policy's
   `'self'` holds a redirect after a form's post — in Chrome, where it is enforced, and
   it reports one where it is not — so a package that fills the slot contributes its
   tracker's origin, `csp.allow("form-action", csp.origin_of("<aspect>.<field>"),
   by=…)` ([ADR-0048](0048-an-assembled-content-security-policy.md) §4): the policy
   names the tracker the deployment configured, and nothing else.

7. **A submit that opens another tab is no write in the drawer.** The drawer takes the
   frame's landing at the address a submit's form names for the write gone through, and
   closes
   ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
   decision 3). A submit whose button, or form, targets another tab names nothing: the
   words stay, the question still asks before a close drops them, and the frame's next
   landing — a reload, say — is not taken for a write.

## Consequences

- Additive to the seam: one slot more on the roster and one name more in the two
  others' context, which ADR-0034 decision 1 makes compatible; one keyword more on
  `slots.register`, and `slots.DraftPart`, both promised beside it. A package filling
  the tab's slot needs the release that carries it.
- One route more, `POST /draft/<path>`, behind the gate like every route, writing
  nothing. Its address is handed to the slot, not promised.
- The chip slots stay: the library's own actions and any package fill them as before. A
  package that moves its ticket into the form stops filling them in a release of its own.
- `/system/installed` says a filler's draft function beside its provider.
- The JSON envelope is unchanged: what is filed lives in the tracker, and its link in
  the note.

## Alternatives considered

- **Each package mounting a route of its own.** A surface the library would have to
  gate, protect and keep stable for code it never sees, every filler reading the form
  and the tree again.
- **Script building the tracker's address in the page.** The tab's forms work without
  script, and a package's markup and its budget would be written a second time, in the
  browser.
- **The route answering with a page that links on**, rather than a package adding its
  origin to the policy: a second click, in a tab that exists only to be clicked
  through.
- **Filing the form's alone.** A link that writes nothing would be gated by the form's
  permissions, a reader who files today would lose it, and roles would have filing to
  decide.
- **The button before the kind's own, under the words, in the order a person moves.**
  It would be the form's default, and Enter in an end field would open a draft instead
  of doing the act.
- **The Notes tab's address for the new slot alone, or a filler calling
  `url_for("notes")`**: a chip's filler without it, or a second endpoint name nothing
  promises.

