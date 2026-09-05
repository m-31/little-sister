# ADR-0047 — A node keeps notes, and they outlive it

- **Status:** Accepted
- **Date:** 2026-08-08 (decided the same day, in the design round on what a
  maintenance pin leaves behind)
- **Related:** [ADR-0014](0014-maintenance-persistence.md) (the pin, its side-table,
  the two dates and the compare-and-set token this reuses; its `reason` field is
  renamed here),
  [ADR-0036](0036-addressable-reasons.md) (keyed entries — the address space this
  matches, and decision 6's suspend-not-delete, extended to a note),
  [ADR-0032](0032-status-contribution-boundary.md) (the contribution boundary this
  primitive is deliberately **outside** of),
  [ADR-0041](0041-maintenance-is-a-contribution-rule.md) (why a pin no longer
  destroys a reading — the same instinct, applied to what a pin *says*),
  [ADR-0018](0018-markdown-rendering.md) (the renderer a note's text goes through;
  the trust class is unchanged),
  [ADR-0031](0031-deployment-config-directory.md) (`config/` is operator input,
  `var/` is state the program owns — which side this lands on),
  [ADR-0012](0012-node-metadata.md) (`about` — what a node *is*; a note is what
  someone wants to say about it),
  [ADR-0008](0008-json-output-api.md) (the envelope, deliberately untouched here)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A maintenance pin carries a line of text saying why. Since Markdown arrived
([ADR-0018](0018-markdown-rendering.md)) that line has quietly become the place an
admin records everything a pin cannot express structurally — a ticket link, a
paragraph of what was found, who to ask. It is the right place. What is wrong is how
long it lasts.

**A pin's text has exactly the lifetime of the pin, and there are four ways it
goes.** The expiry sweep drops the entry and rewrites the file (there is a real
`MAINTENANCE -> UNDEFINED` transition and an event, but the event records the
transition, not the text). A manual clear does the same with no trace at all.
`reap_uncovered` discards pins at startup for paths no check root covers. And a
per-entry pin ([ADR-0036](0036-addressable-reasons.md)) is quieter still — expiry is
its whole lifecycle end, and the code says outright that it "writes no status and
emits no event". There is no history to fall back on: `var/maintenance.json` is a
current-state table, not a log, and the only historical thing in an entry is
`created_at` / `created_by`, described in its own docstring as "the one piece of
history kept without a history".

So the better the field got, the more expensive its disposal became. That is the
first half.

The second half is **recurrence**. The same GitHub Action fails the way it failed
last spring; the same certificate renewal breaks the same way every year. What is
valuable then is not the pin — the pin is long gone and should be — but the sentence
somebody wrote the last time, and it is worth precisely because it is old. That
requirement is stronger than "keep the text a while": the check itself may have left
the configuration and come back, so **the record has to survive the node**.

The extension-seams round's answer to the first half was a named ticket field on the
entry. It is retired here: with Markdown in the field, a schema for one deployment's
issue tracker buys nothing, and it would not have answered the second half at all.

## Decision

1. **`reason` becomes `note`.** `MaintenanceEntry.reason` is renamed on the model
   and on the persisted key. This finishes a rename the presentation layer already
   made — `app.py` has been building its view models as `note=entry.reason` and
   documenting `note` as "*why*, the admin's justification" for some time — and it
   frees `reason` to mean the one thing it means everywhere else in this system: a
   line a **check** reported. The persisted key is a **clean break**, not a
   migration, on [ADR-0036](0036-addressable-reasons.md)'s precedent: an entry
   carrying only the old key loses its text with a warning and the next save
   rewrites the file. This is runtime state the program owns, every pin in it is
   bounded by a finite expiry, and one compatibility branch in the read path would
   outlive the problem it solves.

2. **A note is not a contribution rule.** Every mechanism in the maintenance and
   aggregation work is a transformation at the node boundary —
   [ADR-0032](0032-status-contribution-boundary.md)'s frame, and the reason each of
   them must be visible and attributable. A note is the first node-attached
   primitive deliberately outside it: it contributes nothing, transforms no code,
   never enters the roll-up, and cannot be the reason a node is any color. Stating
   this first is what keeps it cheap; the next reader will otherwise ask whether a
   note should clamp something.

3. **A node keeps a note history** — append-only, time-ordered, addressed like a pin
   (a node path, or a `(path, slug)` entry key, so the entry case that motivated all
   of this is covered). A pin's note is an entry in that history.

4. **The note is appended when the pin is set, not when it ends.** It exists from
   the moment it is written; expiry then does nothing to it at all — the pin stops
   and the note simply stays. This removes the handoff as a mechanism: there is
   nothing to transfer, no second copy, and no node showing both a live note and a
   kept one.

5. **A note is editable while its owning pin is live, and frozen once that pin
   ends.** Editing a live pin's explanation is correcting a sentence; editing it a
   year later is rewriting history. The note records the owning pin's `created_at`
   as its owner token and is editable exactly while a pin with that token is in the
   table. A note written with no pin is editable while it is the newest note on its
   node. Dates follow [ADR-0014](0014-maintenance-persistence.md)
   exactly — `created_at` / `created_by` the first write, `set_at` / `set_by` the
   last — and writes carry the same compare-and-set token, for the same reason two
   admins on one node needed it there.

6. **A note captures its context at write time** — the node's code and its reason
   lines as they stood. Without it a note jogs the memory; with it, "the same
   problem as before" is a question that can be answered. This is also the
   deliberate stopping point: the captured context is a **snapshot on an authored
   note**, not a status history. The durable status history stays the persistence phase's.

7. **Notes outlive the tree.** They are exempt from `reap_uncovered`. Coverage says
   whether a check is configured *today*, which is exactly the wrong question — the
   Action that vanished and came back is the case worth serving. Notes are therefore
   the first state in this system that is an **archive rather than a projection** of
   the current check set, with two consequences that must be built, not discovered:
   the notes index is browsable and **searchable independently of the tree** (a note
   on a path that does not currently exist must still be findable, or it is worse
   than deleted), and a path rename orphans its notes silently — named, accepted,
   and not solved here.

8. **A note on an entry slug the current run does not report is shown on the node,
   marked as belonging to an unreported entry.** This extends
   [ADR-0036](0036-addressable-reasons.md) decision 6 — absence suspends, it does
   not delete — from a pin to a note, and it is the reason the notes index cannot be
   only a walk of the live tree.

9. **Retention is a count floor, a count cap, an age floor and an age ceiling.** A
   note is retired if and only if

   > it is **not among the last `notes_keep`** on its node, **and** either it is
   > older than `notes_max_age`, **or** the node holds more than `notes_cap` notes
   > and it is older than `notes_min_age`.

   Precedence, because the rules conflict: **the count floor wins over everything.**
   A node with ten three-year-old notes keeps all ten — otherwise the node that has
   been healthy longest loses precisely the history that would let anyone recognize
   the problem when it returns. The age ceiling then retires by age alone, and the
   cap does the routine trimming with the age floor as its guard: you may trim for
   volume, never below the floor.

10. **The defaults, and why these numbers.** `notes_keep: 10`, `notes_cap: 50`,
    `notes_min_age: 13mo`, `notes_max_age: 25mo`. **Thirteen months is "more than a
    year"**, so a yearly-recurring problem is always still recognizable when it
    recurs; **twenty-five months is "more than two years"**, one full repeat plus
    margin. Written down because they look arbitrary otherwise, and the first person
    to tidy them to 12 and 24 breaks the only case they exist for. One parser
    consequence: the existing duration vocabulary reads `m` as **minutes**
    (`retry_interval: 2m`), so months are spelled `mo`, and a bare `m` in these two
    keys is **refused at load** rather than silently accepted — a retention floor of
    thirteen minutes is not a value anyone meant to write.

11. **The four keys live in `settings.yaml`**, with the values above as library
    defaults, so an existing deployment upgrades into this behavior without
    authoring anything.

12. **Retention runs on the scheduler tick**, beside `sweep_expired`, not on write.
    A node that never receives another note must still trim, and the tick is where
    this project already puts periodic disposal.

13. **Notes are persisted in their own `var/notes.json`**, on
    [ADR-0014](0014-maintenance-persistence.md)'s discipline exactly: atomic temp
    file plus `os.replace`, a write failure logged rather than raised, the in-memory
    table authoritative for the session, no flush on shutdown. A third table inside
    `var/maintenance.json` was the alternative; the filename would then be a lie, and
    the two now have different lifecycles — one bounded by an expiry, one bounded by
    a retention policy.

14. **The trust class is unchanged.** A note is admin-authored, like the pin's text
    today, so it renders as full Markdown
    ([ADR-0018](0018-markdown-rendering.md)); check-supplied reasons remain the
    untrusted vector, handled at their source. It does put admin Markdown on more
    surfaces, which is one more argument for the Content-Security-Policy rather
    than a new exposure.

15. **The JSON envelope changes nothing here.** Notes reach clients in the client
    contract round's one `schema_version` decision, additively, and nothing ships
    piecemeal before it ([ADR-0008](0008-json-output-api.md)).

Whether history is kept forever, for a number of days, or as the last N changes was
an open question. Decision 9 is the answer — **the conjunction of all three, with a
floor** — and the durable event log inherits this design rather than re-deciding it.

## Consequences

- The extension-seams round's ticket bullet retires; the need it named is met by
  decisions 3–7, and the JSON half moves into the client contract round with
  everything else.
- A piece of the persistence phase is pulled forward on purpose. Notes are the safe
  first instance because they are **hand-authored** — a human types each one, so the
  volume ceiling is inherently low and a JSON file rewritten whole stays fine at
  hundreds. If it ever is not, the durable store subsumes it, as it already subsumes
  the maintenance file.
- The handoff could be automatic *because* retention exists. While notes were
  permanent, every "rebooting the box, back in ten minutes" pin left litter forever
  and the choice had to be the admin's; with a retention policy the litter disposes
  of itself, which is what makes decision 4 affordable.
- **A note is not an event.** Events are derived and bounded; notes are authored and
  retained. They answer different questions and are not merged, even where both
  appear on the same page.
- **Acknowledgment does not supersede this.** When it lands, an ack says *someone is
  on it* and is bound to a condition; a note says *here is
  what we know* and is bound to nothing. A ticket link may sit on either, and the
  note is what remains once the pin and the ack are both gone.
- Every maintenance surface gains a second thing to show and must keep them distinct:
  the live pin's note (editable, silencing something) and the node's history
  (frozen, silencing nothing). The `/maintenance` page, the card, the popover and the
  new index all have to say which they are showing.
- `set_maintenance(reason=…)`, the form field, and the templates rename together;
  this is one break rather than two, and it lands in the same slice as the primitive.
- Notes on paths no check covers accumulate invisibly unless the index is built as
  decision 7 requires. This is the failure mode to test for first.

## Alternatives considered

- **A named ticket field on the entry** (the extension-seams round's plan) — retired.
  With Markdown in the field it buys a schema for one deployment's tracker, and it
  answers nothing about the record surviving the pin, which was the actual problem.
- **Tags** — rejected by the node-tags design's own
  rule: *a tag is a static fact about the subject, never a fact about its status*,
  and tags come from `nodes.yaml`, inheritance or the check — operator-authored
  configuration, never an admin's in-the-moment action. A note is per-incident
  runtime state; putting it in the tag vocabulary makes selectors time-varying.
- **Calling them entries** — rejected on vocabulary alone. `MaintenanceEntry` is one
  meaning and [ADR-0036](0036-addressable-reasons.md)'s addressable reason entries
  are another; a third would make the docstrings unreadable. (The same objection
  retired `aspect` as a name for tags: check aspects and configuration aspects had
  it first.)
- **A single standing note per node** (the first shape this round considered) —
  superseded by the history. One note holds the current explanation and loses
  recurrence, which is the half of the problem that motivated survival past the pin.
- **Reaping notes by coverage, like pins** — rejected: it deletes exactly the record
  the recurring-Action case needs, and it deletes it at startup, silently.
- **An opt-in handoff, a checkbox on the form** — rejected once retention existed;
  see the third consequence. It also asks the admin a question at the moment they
  are thinking about something else.
- **Keep notes forever** — rejected. Unbounded invisible growth is the failure
  ADR-0014's reaper exists to prevent, and the open retention question wants an
  answer, not an omission.
- **Two retention parameters — retire past the ceiling unless among the last N** —
  rejected: with no count cap the age floor never fires, and a chatty node has no
  upper bound at all. The four-parameter form is the one where every rule does work.
- **Appending the note when the pin ends rather than when it is set** — rejected: it
  makes the note invisible for the whole time it is most relevant, and it puts a
  node in the position of showing a live note and a kept note that say the same
  thing.
