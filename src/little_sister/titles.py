"""When a node's ``title`` says nothing its ``name`` did not.

A node's title is a nicety beside its name (ADR-0017), and a check with nothing
better to say hands back the name again with a capital letter — so a row of
severity-band chips reads ``critical Critical``, ``medium Medium``, ``none
None``: twice the width, twice the reading, no second fact. On a card whose chips
already compete for one line (ADR-0028) that is the cheapest width in the
application to give back.

**This is a view rule, not a data one**, and the distinction is the whole reason
this module exists rather than a ``title = None`` somewhere upstream. The check
said something and the tree stored it; a surface may decline to *draw* it, but
nothing may make it stop being true:

* the **snapshot keeps the title** — :class:`~little_sister.tree.StatusSnapshot`
  is read by everything and must stay the record of what the check said;
* the **JSON API keeps emitting it** — dropping a field is a contract change
  (ADR-0008), and a client rendering its own chips is entitled to its own
  decision about the word.

What *is* a surface, and therefore folds: the grid's leaf chips, box and card
head lines and the heartbeat strip, the page band beside the breadcrumb (so the
detail page too), the inspection popover (ADR-0019) and the Maintenance
page's headings — plus the ``/copy`` hand-off, which is read somewhere with no chips
and no styling, where ``critical`` alone is a fine name and the title adds
nothing either. They all call :func:`shown_title`; none of them re-implements it.

**What "the same thing" folds.** Case, ``_`` versus ``-`` versus a space, and
runs of whitespace — so ``pull_requests`` and *Pull requests* are one string, and
so are ``code_scanning_alerts`` and *Code-scanning alerts*: that is the same
duplication wearing better typography. Nothing else. Two different words stay two
different words, and a title that adds anything at all — a unit, a hostname, an
emphasis the raw text spells out — survives.

The comparison is on the **raw** values, before the inline Markdown renderer sees
them (ADR-0018), so it is one string comparison and not a question about rendered
HTML — and that boundary has one asymmetry worth stating out loud rather than
discovering: ``_`` is a separator to this rule *and* an emphasis marker to
Markdown, so a title of ``_critical_`` folds to the name and goes, while
``**Critical**`` does not and stays.

That is left alone on purpose. Closing it means normalizing Markdown emphasis
before comparing — a parse, in the one place that was meant to be a string
comparison — to buy the suppression of a title nobody writes. The asymmetry is
also in the safe direction: the failure it can produce is *keeping* a redundant
title, never dropping one that said something.

**A second question, for the two surfaces that draw the title instead of the name**
(ADR-0061). Most of the list above draws both — the chip, the card head, the strip,
the band and the Maintenance page all put the name down and the title beside it — and
for those the only question is the one above. ``/copy`` and the inspection popover carry
the title *alone*, which is right while a title is a **word**: a node titled
*Cluster A* is better named that way in a document pasted into a ticket.

It stops being right when the title is a **glyph**. A severity band titled 🔴 is an
improvement on a chip, where its name sits next to it — and a disaster in a pasted
document, which would read 🔴 and nothing else, in the one surface defined as having
no chips and no styling. So :func:`label_parts` answers *what to draw where the
title stands alone*, and the rule is that **decoration cannot substitute for the
thing it decorates**: a title with no letter and no digit in it comes with its name
rather than instead of it.

Both are **view** rules. The snapshot and the JSON keep emitting exactly what the
check said; what changes is only what a surface draws.
"""
from __future__ import annotations

import re
from typing import Protocol


class Labeled(Protocol):
    """Anything that carries both halves of the comparison — a
    :class:`~little_sister.tree.StatusSnapshot`, a maintenance pin. Read-only
    members, so a plain dataclass field and a computed property both answer."""

    @property
    def name(self) -> str: ...

    @property
    def title(self) -> str: ...


#: Everything that separates the words of an identifier or of a sentence. A title
#: and a name spell this differently on purpose, and the difference is never the
#: second fact a title is there to add.
_SEPARATORS = re.compile(r"[\s_-]+")


def _fold(text: str) -> str:
    """``text`` reduced to the words it is made of, lower-cased and space-joined."""
    return _SEPARATORS.sub(" ", text).strip().casefold()


def decorative(title: str) -> bool:
    """A title with no letter and no digit in it — a glyph, an arrow, an ellipsis.

    ``str.isalnum`` rather than an ASCII test, so a Japanese, Cyrillic or Greek title
    is a word and keeps every right a word has here; an emoji, an arrow and a
    box-drawing character are not. A digit counts: a node titled ``42`` is labeled,
    badly, but labeled.

    An empty title is vacuously decorative and never reaches a caller that cares —
    :func:`label_parts` asks :func:`shown_title` first, and an empty answer there
    means *there is no title*, which is a different question with the same shape.
    """
    return not any(character.isalnum() for character in title)


def label_parts(name: str, title: str | None) -> tuple[str, str]:
    """What to draw where a surface draws the title **instead of** the name.

    Returns a ``(name, title)`` pair, either half of which may be empty, to be drawn
    in that order with a space between them:

    * *(empty, title)* — the title is a word and stands in for the name, which is
      what ``/copy`` and the popover have always done;
    * *(name, title)* — the title is decoration, so it comes **with** the name
      (ADR-0061): ``critical 🔴``, in the chip's own order, name first;
    * *(name, empty)* — there is no title, or it only repeated the name.

    **Parts and not a joined string**, because the two halves are not the same kind
    of text and no single join is right for both callers. A title is authored
    Markdown and keeps that contract; a name is structural data that has to be
    escaped before it is drawn as Markdown, and each surface escapes it its own way.
    The decision lives here; the drawing stays where it was.
    """
    shown = shown_title(name, title)
    if shown and not decorative(shown):
        return "", shown
    return name, shown


def shown_title(name: str, title: str | None) -> str:
    """The title worth drawing beside ``name`` — ``""`` when it only repeats it.

    Returning the empty string rather than ``None`` keeps the Jinja side a plain
    truth test, the same shape the templates already had around ``node.title``.
    """
    if not title:
        return ""
    return "" if _fold(title) == _fold(name) else title
