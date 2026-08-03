"""Addressable reasons: a node's reason list as keyed entries (ADR-0036).

A check that discovers **dynamic entries** — security findings under a severity
band, waiting pull requests under an aspect — puts many of them into one node's
reasons. An operator picks one, opens a ticket and works on it, and the next
engineer has to be able to see that. Maintenance is per node, so pinning the one
finding somebody is on silences the other nineteen. What is needed is narrower
than a node per entry: an entry must be **addressable**, so a pin can name one.

So a reason is a keyed entry, ``slug -> text``, in the check's order — insertion
order, never sorted by key, because the order a check emits its entries in is
information (severity, API order) that an opaque slug would scramble.

**Prose is the default; members are declared.** Not every reason list is a list of
independent things: a failing check's ``check error:`` line and its stack trace,
or stdout beside stderr, are *one condition in several paragraphs*. Silencing the
trace while the message keeps alarming is meaningless. Both kinds are keyed — the
key is how anything addresses a line at all — but only **members** are
individually suppressible; prose keeps the node pin as its unit. A check declares
members by handing over a **mapping** (the shape says so) or by setting
``entries=True`` beside a sequence of strings it knows to be stable.

Two properties follow, and both are why the default sits on this side: the
engine's failure path needs no change at all, and no existing surface moves until
some check opts in.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# A declared slug is opaque and never rendered as text — it lives in `data-`
# attributes, form fields, query values and log lines — so it stays bounded and
# free of whitespace and control characters (ADR-0036 consequences).
MAX_SLUG_LENGTH = 200

#: The prefix marking a **derived** slug. It is there so a human reading a URL or
#: a log line can tell the two promises apart: a declared slug is an identity
#: claim that survives a re-wording, a derived slug *is* the wording.
DERIVED_PREFIX = "h-"


class ReasonError(ValueError):
    """A reason list the core cannot key — a mixed sequence, or a declared slug
    that is empty, over-long or carries whitespace. Raised where the outside world
    enters (ADR-0026), so a check author sees it at construction."""


@dataclass(frozen=True)
class ReasonEntry:
    """One keyed reason: an opaque ``slug`` and the ``text`` that is displayed.

    ``text`` is what every existing surface already shows — events, history and
    the JSON envelope carry the values and never the slug (ADR-0036 decision 11):
    a slug in a historical event means nothing once the entry is gone.
    """
    slug: str
    text: str

    @property
    def derived(self) -> bool:
        """Whether this slug was computed from the text rather than declared. A
        derived slug invalidates itself on a re-wording, which is exactly why no
        separate validator field is needed."""
        return self.slug.startswith(DERIVED_PREFIX)


#: Everything a check (or a direct `upsert` caller) may hand over as a reason.
#: Four input forms, one internal one — the normalization below is the only place
#: that knows the difference.
ReasonInput = (
    str
    | Mapping[str, str]
    | Sequence[str]
    | Sequence[tuple[str, str]]
    | Sequence[ReasonEntry]
    | None
)


def derived_slug(text: str) -> str:
    """The content-hash slug for ``text`` — ``h-`` plus ten hex digits of its SHA-1.

    Deliberately **not** an index: an index moves when an entry is inserted above
    it, so a pin would slide silently onto a *different* finding, with nothing to
    notice it by. A hash makes "return a stable string" sufficient — a check that
    emits ``f"{issue_id} {text}"`` gets durable pins without a line of slug logic.
    """
    digest = hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()
    return DERIVED_PREFIX + digest[:10]


def _check_declared(slug: str) -> str:
    """Validate a check-supplied slug, or raise. A declared slug is an identity
    claim and travels in URLs and form fields, so it has to be usable as one."""
    if not slug or slug != slug.strip() or any(ch.isspace() for ch in slug):
        raise ReasonError(f"reason slug must be non-empty and free of whitespace: "
                          f"{slug!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in slug):
        raise ReasonError(f"reason slug carries a control character: {slug!r}")
    if len(slug) > MAX_SLUG_LENGTH:
        raise ReasonError(f"reason slug longer than {MAX_SLUG_LENGTH} characters: "
                          f"{slug[:40]!r}…")
    return slug


def _keyed(pairs: Sequence[tuple[str, str]]) -> tuple[ReasonEntry, ...]:
    """Build the entries, resolving a slug already taken within this node to
    ``-2``, ``-3``, in the check's order.

    The suffix covers both an honestly repeated text — a real list can carry the
    same sentence three times, for three different findings — and an
    astronomically unlikely hash collision.
    """
    entries: list[ReasonEntry] = []
    seen: set[str] = set()
    for slug, text in pairs:
        candidate, bump = slug, 1
        while candidate in seen:
            bump += 1
            candidate = f"{slug}-{bump}"
        seen.add(candidate)
        entries.append(ReasonEntry(candidate, text))
    return tuple(entries)


def normalize(reason: ReasonInput,
              entries: bool = False) -> tuple[tuple[ReasonEntry, ...], bool]:
    """Normalize any accepted reason form into ``(entries, members)``.

    ``members`` says the entries are **individually suppressible**. A mapping or a
    pairs sequence says so by its shape; a sequence of plain strings needs the
    ``entries`` flag; a bare ``str`` is one condition and the flag is meaningless
    beside it. A sequence of :class:`ReasonEntry` is already normalized and carries
    the flag through unchanged.
    """
    if reason is None:
        return (), False
    if isinstance(reason, str):
        return _keyed([(derived_slug(reason), reason)]), False
    if isinstance(reason, Mapping):
        # An empty mapping declares nothing: a node with no reasons is outside the
        # virtual-child rule either way, so it should not claim to have members.
        lines = _keyed([(_check_declared(str(slug)), str(text))
                        for slug, text in reason.items()])
        return lines, bool(lines)
    items = list(reason)
    if not items:
        return (), False
    if all(isinstance(item, ReasonEntry) for item in items):
        return tuple(item for item in items if isinstance(item, ReasonEntry)), entries
    if all(isinstance(item, str) for item in items):
        texts = [item for item in items if isinstance(item, str)]
        return _keyed([(derived_slug(text), text) for text in texts]), entries
    if all(isinstance(item, tuple) and len(item) == 2 for item in items):
        pairs = [item for item in items if isinstance(item, tuple)]
        return _keyed([(_check_declared(str(slug)), str(text))
                       for slug, text in pairs]), True
    raise ReasonError(
        "a reason sequence must be all strings, all (slug, text) pairs or all "
        "ReasonEntry — not a mixture")
