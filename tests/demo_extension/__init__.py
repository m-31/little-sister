"""A stand-in for a dependent package that fills a template slot (ADR-0034).

The seam's whole point is that the filler lives *outside* the library, so testing it
needs a package that is not :mod:`little_sister`: its own importable name, its own
``templates/`` directory, its own context provider. This is the smallest thing with
that shape, and it is deliberately a package rather than a fixture built at runtime —
:class:`~little_sister.slots.ExtensionLoader` resolves through
:class:`jinja2.PackageLoader`, so a real importable package is what it must be
pointed at.

The provider mirrors what a real deployment does: decline anything that is not a leaf
(placement policy belongs to the filler, not to our template), and otherwise hand its
template the values it needs — computed here, in Python, so the template never
assembles markup.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from urllib.parse import urlencode

from little_sister.slots import DraftPart


def action(*, node: object, reason: str, index: int,
           surface: str) -> Mapping[str, object] | None:
    """A context provider: a label and a URL for one reason line of one leaf."""
    if getattr(node, "children", ()):
        return None
    return {
        "label": "raise",
        "url": f"https://tracker.example.org/new?path={getattr(node, 'path', '')}",
        "summary": f"{surface}#{index}: {reason}",
    }


def node_action(*, node: object, surface: str) -> Mapping[str, object] | None:
    """A context provider for the **node** slot (ADR-0034's second slot).

    It declines a node whose reasons are individually addressable ``members``,
    because there the right control is the per-line one (ADR-0036) — which is the
    placement rule the second slot exists for, expressed where it belongs: in the
    filler, not in our template. Its summary is built from the whole reason set,
    first line first, exactly as a real one would build an issue title.
    """
    if getattr(node, "members", False):
        return None
    reasons = list(getattr(node, "reason", ()))
    if not reasons:
        return None
    return {
        "label": "file",
        "url": f"https://tracker.example.org/new?node={getattr(node, 'path', '')}",
        "summary": f"{surface}: {reasons[0]}",
    }


#: Past this many reason lines a per-line chip stops being a control and becomes
#: wallpaper — the node action is the right unit there. A judgment about *this*
#: deployment's pages, which is why it lives in the filler and not in the library.
REASON_BUDGET = 20

#: The demo review queue's lines say who they are waiting on; only the ones waiting
#: on a **reviewer** can be nudged. A filler reads the reason text it was handed —
#: it has no other way to tell one line of a node from another.
_NUDGEABLE_TAIL = "h for a reviewer"


def review_action(*, node: object, reason: str, index: int,
                  surface: str) -> Mapping[str, object] | None:
    """The **live demo's** reason-level provider (``demo_wsgi.py``, ADR-0034).

    Separate from :func:`action` above rather than a reuse of it: that one is the
    test suite's stand-in, and a rule edited for a test case would silently change
    what the demo shows. Same package, though — a real deployment has one extension,
    and so should the demo.

    It exists to show the one thing a configured action cannot: **declining**, on
    four different grounds, three of which are about the node and one about the
    line. On ``/ci/reviews`` the last of them is visible side by side — the review
    that is waiting on its *author* gets no chip while its neighbors do, and the
    configured "Nudge" entry, which has no way to express that, sits on all of them.
    """
    del index, surface
    if getattr(node, "children", ()):
        return None                    # a container has no reasons of its own
    if not getattr(node, "members", False):
        return None                    # prose: the node is the unit (ADR-0036)
    if len(list(getattr(node, "reason", ()))) > REASON_BUDGET:
        return None                    # a wall of chips is not a control
    if not reason.endswith(_NUDGEABLE_TAIL):
        return None                    # this line is not waiting on a reviewer
    return {
        "label": "nudge",
        "url": f"https://chat.example.org/compose?to=reviewers"
               f"&path={getattr(node, 'path', '')}",
        "summary": f"ask for a review: {reason}",
    }


def echoes(**context: object) -> Mapping[str, object] | None:
    """A provider that hands its whole context back through the template.

    For the escaping cases: a provider returning a **constant** proves nothing
    about escaping, because the payload never reaches the template — the test then
    passes on somebody else's escaping and would keep passing with `| safe` in the
    filler. This one puts the untrusted value where it is actually rendered.
    """
    reasons = list(getattr(context.get("node"), "reason", ()))
    text = str(context.get("reason") or (reasons[0] if reasons else ""))
    return {"label": text or "echo", "url": "https://tracker.example.org/new",
            "summary": text}


def recorder(seen: list[Mapping[str, object]]):
    """A provider that records the keyword arguments a slot handed it.

    The slot's declared ``context`` is a contract with every filler, and nothing
    else checks that the core templates actually pass it: dropping a name would
    fail silently inside each provider instead of here.
    """
    def provider(**context: object) -> Mapping[str, object] | None:
        seen.append(dict(context))
        return {"label": "seen", "url": "https://tracker.example.org/new",
                "summary": "seen"}
    return provider


def always(**_context: object) -> Mapping[str, object] | None:
    """A provider that never declines — for the ordering and escaping cases."""
    return {"label": "always", "url": "https://tracker.example.org/new",
            "summary": "always"}


def declines(**_context: object) -> Mapping[str, object] | None:
    """A provider that always declines."""
    return None


def explodes(**_context: object) -> Mapping[str, object] | None:
    """A provider that raises — the page must still render without it."""
    raise RuntimeError("the tracker client is not configured")


#: Where the suite's draft function files: the reserved example domain, never a real
#: tracker.
TRACKER = "https://tracker.example.org/new"

#: How long a drafted title may run, as a tracker's board would cut it.
TITLE_LIMIT = 200


def draft_issue(*, path: str, parts: Sequence[DraftPart], words: str,
                notes_url: Callable[[], str]) -> str | None:
    """The suite's draft function for a node's *Notes* tab (ADR-0148), drafting with
    the promise alone — what the library hands a draft function, and nothing read off
    the node it hands beside it.

    A tracker's new-issue address: its title the node's path and the words' first
    line, or where there are none what the part reads — one part, its own path and
    its first line; several, how many and then the first — and its body the words,
    then what each part reads, then the address of the node's *Notes* tab, where the
    note the words become will stand. Every line came written out, so the body is
    what the tracker shows; the title is flattened to one line and cut where a board
    would cut it."""
    first = next((line.strip() for line in words.splitlines() if line.strip()), "")
    if first:
        title = f"{path}: {first}"
    elif len(parts) == 1:
        part = parts[0]
        title = f"{part.path}: {part.lines[0]}" if part.lines else part.path
    else:
        lead = parts[0]
        title = (f"{path}: {len(parts)} failures — {lead.path}: "
                 f"{lead.lines[0] if lead.lines else ''}")
    title = " ".join(title.split())
    if len(title) > TITLE_LIMIT:
        title = title[:TITLE_LIMIT - 1] + "…"
    read = "\n".join(f"{part.path}: {line}" if part.path != path else line
                     for part in parts for line in part.lines)
    body = "\n\n".join(text for text in (words.strip(), read, notes_url()) if text)
    return f"{TRACKER}?{urlencode({'title': title, 'body': body})}"
