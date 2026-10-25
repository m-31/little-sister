# ADR-0140 — A node's notes stand on a tab of their own, and its hand-off carries the newest

- **Status:** Accepted
- **Date:** 2026-10-25
- **Related:** [ADR-0047](0047-node-notes-and-their-retention.md) (the notes — the
  history, a pin's note, the context a note keeps, the retention — built here in part),
  [ADR-0014](0014-maintenance-persistence.md) (the pin and its file, whose key is
  renamed — amended), [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)
  (the directory the notes' file joins — amended),
  [ADR-0077](0077-authority-follows-the-lease.md) (the takeover, which adopts it),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (a node's views —
  amended), [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md)
  (the Copy document — amended),
  [ADR-0116](0116-a-path-with-no-node-says-what-is-known-of-it.md) (the page of a path
  no node stands at — amended), [ADR-0036](0036-addressable-reasons.md) (a line's
  address, which a note on a line takes),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (a line's editor, beside
  which its note is offered), [ADR-0072](0072-the-instance-reports-on-itself.md) (the
  lines the start and the tick say what went wrong in),
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (the pins' file, which keeps a pin's note under `note`)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

ADR-0047 decided that a node keeps notes: a history on each node, a pin's note entered
as the pin is set and kept once it ends, what the node showed when a note was written,
a retention of four keys, and a file of their own. It left open what a reader sees of
them, whether an admin writes one without a pin, and where they are found once their
node is gone, and it named the rename of a pin's text, `reason` to `note`, as the break
to land with them. Since it was accepted the state layer gave its file a directory
(ADR-0071) and a takeover its other direction (ADR-0077).

A finding is usually written after the failure is over, its pin run out or never set.
Were a pin's note the only note, an admin would pin a healthy node to write a sentence
about it. And what is known of a node is wanted where somebody works on it and where
it is handed over — not on the wall, whose heads are full, and not in the envelope,
whose next version is the client contract round's to decide (ADR-0047 decision 15).

## Decision

1. **A note of its own, on a node and on each of its lines.** An admin writes a note
   bound to nothing — *here is what we know* — on the node, or on one of its lines by
   the line's slug (ADR-0036). It is changed while it is the newest note on its node, as
   ADR-0047 decision 5 says, by a compare-and-set on its last write, as a pin is. A
   pin's note enters the same history as the pin is set, names its pin by the pin's
   creation, follows the pin's edits while the pin stands and is kept as it was once
   the pin ends. A pin set without words writes no note: `maintenance`, which such a
   pin holds as its text, is nobody's note.

2. **A tab of their own, *Notes*, after *History*.** It stands on every node but the
   root, as History does, and carries the number of notes as Series carries its curves
   ([ADR-0114](0114-a-curve-seen-small-and-the-series-tabs-count.md) decision 3). Its
   view, `/notes/<path>`, lists the notes on the node and on its lines, newest first.
   Each says what it is on — the node, or a line as it reads now, linked to it on the
   node's page, and marked where the run does not report it (ADR-0047 decision 8) — who
   wrote it and when, who changed it last, and whether it is a pin's note and its pin
   still stands; then its words, rendered as a pin's note is (ADR-0047 decision 14);
   and, folded beneath them, what the node showed when they were written. An admin adds
   a note at the top, on the node or on a line, and changes the newest note of its own
   in place. A write that is refused — the note changed since, no longer the newest, a
   pin's, or no words at all — saves nothing and brings the admin's words back in the
   form. The view is read, not polled, as History is.

3. **A line's note is written from the line too.** A line's editor
   ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) decisions 3 and 4)
   offers beside the pin it sets *Write a note on this line*: the node's Notes view,
   the line chosen (`?reason=<slug>`, ADR-0036 decision 12).

4. **The hand-off carries the newest.** A node's Copy document has a block, *Notes*,
   after its reasons: the newest note whole — who wrote it and when, who changed it
   last, whether it is a pin's, the line it is on as the line read then — and how many
   more its Notes view lists, at that view's address. The tree's document and a line's
   are as they were, so is the wall, and so is the envelope.

5. **A path no node stands at lists its notes.** The page every address of such a path
   answers with (ADR-0116) lists the notes written for the path and for the paths
   beneath it, newest first, each beneath the page's own at its path, as written:
   nothing links to a line there, and nothing is changed. When the check comes back,
   its node's Notes view has them again. The index ADR-0047 decision 7 asks for —
   every note, found and searched without the tree — is still to build.

6. **`reason` becomes `note` in the model, the form and the file at once** (ADR-0047
   decision 1). A pin's text is `Pin.note`, the field a pin's form posts is `note`, and
   a pin in `pins.json` keeps its text under `note` (ADR-0141 decision 1). No file
   carries the old key: `pins.json` is new in the same release, and `maintenance.json`,
   which carried it, is not read.

7. **`var/state/notes.json`.** The notes are a file of the state layer (ADR-0071):
   plain JSON, `{"notes": {path: [note, …]}}`, each path's notes oldest first, written
   through on every change, read at the start, and adopted at a takeover and on *take
   the backups* (ADR-0077). A file it cannot take is a load failure on
   `/little-sister/state`, and the history starts empty. Nothing reaps a note (ADR-0047
   decision 7): the start takes every path the file holds, covered by a check or not.

8. **What a note keeps of its node.** The status the node showed, and its lines, each
   with its own status where it declares one — for a note on a line, that line: the
   first fifty, and how many more. A pin's note keeps what the node showed before the
   pin.

9. **Retention on the tick.** The four keys of ADR-0047 decision 9, in `settings.yaml`
   with its defaults: a whole number for `notes_keep` and `notes_cap`, and an age for
   `notes_min_age` and `notes_max_age` — `13mo`, `400d`, `8w` — whose months are the
   calendar's in the configured zone. A value it cannot use, a bare `m` among them, is
   warned of at the load and gives way to the default. The engine retires on every
   tick, beside the pins' expiry; a sweep that raises is a line on
   `/little-sister/runtime`, and the tick goes on.

## Consequences

- A pin that stands at the upgrade is dropped with `maintenance.json`, its text with it
  (ADR-0141), and enters no node's notes: the notes begin with the pins set after the
  upgrade and the notes written then.
- The pin surfaces show the pin's note as they did; the Notes view is where the history
  is read and the one place a note of its own is changed, and it says which notes are
  pins' and whether their pins stand, as ADR-0047's consequences ask of every surface
  that shows both.
- Until the index, a gone path's notes are found at its own address only, and a path
  renamed orphans its notes there — named, and not solved, as ADR-0047 decision 7 says.
- A note is not an event: nothing here writes a row of the log, colors a node or counts
  in a roll-up (ADR-0047 decision 2).

## Alternatives considered

- **A pin's note alone, a note of its own coming with acknowledgment's *done*.** *Done*
  is bound to an occurrence and counts as OK; a note is bound to nothing and counts for
  nothing, and a finding written after the failure has no occurrence to be bound to.
- **A note on the node only.** A line is where a line pin's note lands and where a
  recurring failure often is.
- **The notes on the History tab, above the periods, or as a card on the Status tab.**
  History's periods and readings would be pushed below the fold, and the Status tab is
  the busiest page, where the newest note is often not the one that matters.
- **The node's page alone, without the Copy document; or the Copy document and a mark
  on the wall's head of a node that fails and has notes.** The first leaves *what we
  know* out of the hand-off; the second crowds heads that are full, and is a later
  slice's once deployments have notes.
- **Nothing for a gone path until the index; or the nearest node above listing the
  notes of the paths gone beneath it.** Under the first nobody finds them; under the
  second a node's view mixes its own notes with strangers'.
- **The model renamed now and the file's key with `pins.json`** — recommended at the
  design pass, to spare a pin's text at this upgrade. It leaves `reason` meaning two
  things in the file until then, and Lex chose the break ADR-0047 decision 1 names.

