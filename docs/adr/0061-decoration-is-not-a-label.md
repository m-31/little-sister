# ADR-0061 — Decoration cannot substitute for the thing it decorates

- **Status:** Accepted
- **Date:** 2026-08-16
- **Related:** [ADR-0017](0017-node-title.md) (the title, and the rule that one which
  only repeats the name is not drawn; this is the second question that rule opened), [ADR-0019](0019-inspection-popover.md) (the hover card, one of the
  two surfaces here), [ADR-0018](0018-markdown-rendering.md) (raw HTML in a title is
  escaped, which is why a package cannot solve this from outside),
  [ADR-0016](0016-node-addressing.md) (`name`, the thing a title may or may not stand
  in for), [ADR-0055](0055-sibling-order.md) (the declared rank a glyph would render)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node's `title` is a nicety beside its `name` (ADR-0017), which also says that a
title which only repeats the name is not drawn at all. Both rules
live in one predicate, `titles.py`, and every surface calls it.

**Most surfaces draw both halves.** The leaf chip, the card head line, the heartbeat
strip, the page band beside the breadcrumb and the `/maintenance` pin table each put
the name (or the path, or the last crumb) down and then the title beside it. For those
the only question is whether the title adds anything.

**Two surfaces draw the title *instead of* the name**, and that is the case this
record is about:

* **`/copy`** (`copy_status._label`) labels an item with the title when there is one
  and the name otherwise.
* **The inspection popover** (`app._node_meta_map`) carries `title` and `about` and no
  name, for the same reason it drops a repeated title — hovering `critical` would
  otherwise pop a card whose entire content is the word *Critical*.

Both are right while a title is a **word**. A node titled *Cluster A* is better named
that way in a document pasted into a ticket, and *Cluster A* is a better card heading
than `web`.

**What made this a decision is a glyph.** little-sister-github and little-sister-wiz
both want a colored circle as a severity band's title — 🔴 for `critical`, 🟠 for
`high` — carrying the band's severity in one character where a word costs a chip's
width, and reading the rank those bands now declare (ADR-0055). On a chip that is a
clear improvement, because the band's `name` is right beside it: the emoji is not the
accessible channel, the name is, and nothing is lost.

On the two surfaces above, everything is lost. `/copy` would print a bare **🔴** — in
the surface defined as *read somewhere with no chips and no styling* — and the card
would contain nothing but a circle. A pasted document outlives the person who pasted
it, and a colour name is the one thing a reader cannot reconstruct from a colour.

**And a package cannot fix it.** Raw HTML is escaped in titles (ADR-0018,
`html=False`), so `aria-hidden` and a `title=` attribute are both unavailable to a
check. Whatever answer the two plugins reach, they reach it through this library or
not at all.

## Decision

### 1. A title with no letter and no digit in it cannot stand in for a name

Where a surface draws the title *instead of* the name, a **decorative** title is drawn
**with** the name rather than in place of it: `critical 🔴`, name first, in the same
order the chip uses. A title that carries a word is unchanged and still stands alone.

The rule is stated as a property of the title, not as a list of emoji. *Decoration* is
text with nothing in it that a reader could say out loud as the node's name — and
"nothing to say" is exactly "no letter and no digit".

### 2. The predicate is `isalnum`, per character, and that is a Unicode test

`not any(character.isalnum() for character in title)`. Deliberately not an ASCII or a
`[A-Za-z]` test: a Japanese, Cyrillic or Greek title is a word and keeps every right a
word has here, while an emoji, an arrow, a bullet and a box-drawing character are not.
A **digit** counts — a node titled `42` is labelled badly but labelled, and inventing a
rule that a number is not a name would be a second decision hiding inside this one.

One letter anywhere is enough. The test is not *is this mostly a glyph*: a title of
`🔴 Critical` already carries its word and needs no help.

### 3. The first rule runs first, and the two do not compose into a third case

`shown_title` is asked before `decorative`, so a title that only repeats the name folds
away and what is left is *a name with no title* — not a name with a decoration beside
it. The order matters for one real case: a check that titles a band `Critical` gets
today's behaviour exactly, and only a check that titles it `🔴` reaches the new rule.

### 4. It returns **parts**, and the drawing stays where it was

`label_parts(name, title)` hands back a `(name, title)` pair, either half of which may
be empty, to be drawn in that order with a space between. Not a joined string, because
the two halves are not the same kind of text: a title is authored Markdown and keeps
that contract, while a name is structural data that has to be escaped before it is
drawn as Markdown — and each surface escapes it its own way (`_MD_INLINE_ESCAPE` in the
copy document, `plain` on the way into the card). One decision, in one place; two
renderings, where they already were.

This is also what makes the change small at the call sites, which is the point: a rule
about *what a label is* should not become a rule about how two surfaces render.

### 5. A view rule, never a data one

As with ADR-0017's update. The **snapshot keeps the title**, and the **JSON API keeps
emitting it** — dropping or rewriting a field is a contract change (ADR-0008), and a
client drawing its own chips is entitled to its own decision about the glyph. What
changes is only what two surfaces draw.

## Consequences

* A check may title a node with a glyph without any surface losing the word. That
  unblocks the severity ramps in little-sister-github and little-sister-wiz, which are
  held on this record.
* **One behaviour changes for a node that exists today**: any node whose title is
  already wordless now shows its name too, on those two surfaces. That is the fix, and
  it is strictly additive — nothing that was drawn stops being drawn.
* The popover gains a heading that repeats the chip beneath it, for a node with a
  glyph title. Accepted: a heading that names what you hovered is what a heading is,
  and the alternative — dropping a wordless title from the card — would give one
  predicate two answers for the sake of a case that no shipped band is, since every
  band in both packages ships `about` text and would have a card regardless.
* **Not a rule about emoji.** Nothing here says a title should or should not be a
  glyph; whether "a title may be a glyph" is a good idea at all is still being tried
  in the two packages that want it. This record only says what has to be true of the
  library before that question can be answered honestly.
