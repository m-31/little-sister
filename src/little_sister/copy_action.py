"""The built-in **copy** chip: one reason line, handed over on its own.

`/copy` hands over the tree and a node's Copy view the node; the finding an
operator is actually opening a ticket about is one line of one node,
and until this chip existed that was the one thing they had to retype.

**Why it is a slot filler and not a control of its own.** The place a per-line
interaction belongs is already declared — `reason.actions`
([ADR-0034](../docs/adr/0034-template-slots-for-dependent-packages.md)) — and a
deployment's "raise a ticket" chip is already in it. Registering through the same
seam is what puts both chips in one rail, in one order, wearing one chip class,
and lists this one on `/system` beside them. The declarative action list
([ADR-0038](../docs/adr/0038-declarative-action-list.md)) took the same route for
the same reason; `builtin=True` marks both as the library's own.

**Why it is a link.** Every filler in that rail has been one, and this one stays
one: it points at `/copy/<path>?reason=<slug>`, the page that builds the document.
Nothing is embedded in the page it sits on — which is the point. The detail page
lists every reason uncapped and the grid's rail rides the ~10s poll, so a document
carried per line would be paid for on every render of the two-hundred-finding node
this feature exists for, and paid twice (the Markdown and the rendered HTML). A
link costs the length of a URL.

**Where it does not appear.** Where a node's reasons are **prose** — a failure
message and its stack trace are one condition in several paragraphs
([ADR-0036](../docs/adr/0036-addressable-reasons.md)) — there is exactly one thing
to hand over and it is the node, which its Copy tab hands over. A per-line copy
there would offer somebody half of one condition. Prose reasons also have no
stable slug to address, so the URL could not be written even if the offer were
right.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from little_sister import slots

#: The template this filler renders, beside the other core templates and reached
#: through exactly the loader an extension uses (`ext/little_sister/…`).
FILLER_TEMPLATE = "_copy_action.html"

#: The package the filler resolves against — the library itself.
FILLER_PACKAGE = "little_sister"


def copy_context(*, node: Any, reason: str, line: Any, index: int,
                 surface: str) -> Mapping[str, object] | None:
    """Provider for `reason.actions`: the URL of this line's own document.

    Declines — returns ``None``, the way any filler declines — for a node whose
    reasons are prose, and for a line with no slug to name. ``line`` is the slot's
    promise of the whole entry; the **slug is taken from it and never from
    ``index``**, which is [ADR-0036](../docs/adr/0036-addressable-reasons.md)
    decision 3's rule about identity: an index moves when an entry is inserted
    above it, and a chip built on one would quietly address a different finding.
    """
    from flask import url_for

    del reason, index, surface
    if not getattr(node, "members", False):
        return None
    slug = getattr(line, "slug", "")
    path = getattr(node, "path", "")
    if not slug or not path:
        return None
    return {
        "href": url_for("copy", branch=path.lstrip("/"), reason=slug),
        "chip": "reason-action",
    }


def register_copy_filler() -> None:
    """Register the library's copy chip for `reason.actions`. Idempotent."""
    slots.register("reason.actions", FILLER_PACKAGE, FILLER_TEMPLATE,
                   copy_context, builtin=True)
