# ADR-0136 — How the wall is used is one file the package ships, read at `/help`

- **Status:** Accepted
- **Date:** 2026-10-24
- **Related:** [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
  (the wall the account describes, its band and its heads),
  [ADR-0029](0029-per-user-presentation-preferences.md) (the settings menu, whose foot
  links it, and the looks it names),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  (decision 3, a handbook drawn on its page, its headings anchored — how the account is
  drawn), [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (what is handled, which the account describes too),
  [ADR-0018](0018-markdown-rendering.md) (the renderer)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The repository had no account of using the wall. The README says how to install the
library and what `settings.yaml` defaults; `docs/project.md` §3, the specification,
still named a depth control the wall no longer has; and how the band, a head's buttons,
the looks, the kiosk and the failure budget behave was told to developers alone, in the
records and `architecture.md`. A viewer who wondered what a ringed diamond counts, what
*Close all* keeps or what *Failures: stay chips* does had nowhere to read it, and the
page said what its settings change in a line beneath each of them and no further.

The design was settled with Lex on 2026-10-24, one question at a time: the account is
one Markdown file the package ships, drawn at `/help` as a handbook is and linked from
the settings menu's foot, the README and the specification pointing to it.

## Decision

1. **One Markdown file says what a viewer sees and does**,
   `src/little_sister/help/using-the-wall.md`: the chips and the boxes and a click that
   opens and closes them, colors and counts, a box's lines, what opens by itself, the
   band and its buttons, a head's buttons, a node's page and its tabs, maintenance and
   what is handled, each group of the settings menu, the kiosk, a phone, and the other
   pages. It is written for a viewer: it names no record and no file of the code, and
   carries no date.
2. **The package ships it, and the page draws it at `/help`**, behind the sign-in as
   every page is, rendered as a handbook is — its tables drawn, its headings anchored as
   GitHub anchors them, so that `/help#the-band` opens at the band, beneath the sticky
   bar. It is read once from the package (`importlib.resources`), since it changes with
   a release and never at runtime, and it belongs to no node: it stands in no node's
   band and carries no tabs.
3. **The settings menu's foot links it**, *Using the wall*: the last thing in the
   groups' flow, whole in its column. At a desk it stands at the last column's foot, in
   the room the longer columns before it leave, so the menu is no taller for it and
   still fits a laptop's window; on a phone it ends the menu.
4. **The README and `docs/project.md` §3 point to it**, and the specification no longer
   names the depth control.
5. **The account keeps up with the menu by a test.** Every group of the settings menu,
   each of its values, the band's buttons, a head's buttons, a node's tabs and the
   navigation's pages are named in it, and `tests/test_help.py` fails where one is not —
   a look added or renamed among them.

Set aside: the file in the repository alone, which the viewers who need it never open;
a section of the README, the page that says how to install and configure, which it
would about double; and the link beneath the columns, a row of its own, which made the
menu some 45 pixels taller and scroll in a laptop's window.

## Consequences

- A change a viewer sees writes the account with it, where the test does not already
  ask: the flip of the built-in look, which takes `branch_cap` and *+N more* away, has a
  paragraph of it to rewrite.
- The account is in the release tree, on the keep list, and a reader of the repository
  reads it where the code is.
