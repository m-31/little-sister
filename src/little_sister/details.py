"""A node's details: named values whose keys its team chooses (ADR-0133 decision 6).

Each is a line of Markdown under a key — whom to ask, where tickets go, the
documentation, a place, how to log in, the exact name of the object — and a node's
*About* card shows them as a table beneath its ``about``, the key muted.

**Two givers, and one of them gives down.** The **type** gives each node it writes the
details of its object with each run, as it gives its description — an account, a
region, a function, a host, a bay — on ``CheckResult.details``, written through: what
the last run said is what the node holds. The **deployment** gives anything else, in
the check's file for its own node, under an aspect's name in its ``subnodes:`` block,
and in ``nodes.yaml`` by path, which wins key by key. **What the deployment gives a
node holds for every node beneath it**, key by key, the nearest winning: a place told
level by level composes itself card by card, a contact holds for a subtree that one
key overrides lower down, and the details written under an aspect's name reach every
node a run names beneath it, which nothing declared for a name reaches (ADR-0118). A
type's details are its own node's object and are given down to none.

**The card's order** (:func:`rows`): the type's first, in its order — the object —
then the deployment's, in the tree's order, the outermost first, those of one node in
the order they are written, and the node's own last. A key stands once, where it is
named highest, with its nearest value, the deployment's winning over the type's on
the node itself: a team that names a contact at the top and another for its live
account keeps the row where it was. An empty value is a statement like any other — the
key has no value there, nor beneath where nothing nearer names it — so the nearest
value being empty is the row not standing.

A detail belongs to the node it is given on, so a link it writes in the short form,
``handbook#sign-in``, leads into that node's handbook — a page every node beneath it
shares (ADR-0133 decision 4) — and a row names that node, ``at``, for the renderer and
for the card's tooltip.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from little_sister.errors import CheckError

#: A node's details as one giver states them: each key and its value, in the order
#: they are written.
Details = tuple[tuple[str, str], ...]

#: Who gave a detail: the type, through its run — its node's alone — or the
#: deployment, through its configuration — given down to every node beneath.
TYPE = "type"
DEPLOYMENT = "deployment"


@dataclass(frozen=True)
class Detail:
    """One of a node's own details as its snapshot holds it and the API carries it:
    the key, its text, raw Markdown, and who gave it — :data:`TYPE` or
    :data:`DEPLOYMENT` — since the deployment's are given down and the type's stand
    first."""
    key: str
    text: str
    by: str


@dataclass(frozen=True)
class Row:
    """One row of a node's *About* card: a key, the value that stands for it, and
    ``at``, the path of the node that value is given on — the node itself, or the one
    above it it comes down from, which the card's tooltip names and whose handbook a
    link in the value leads into."""
    key: str
    text: str
    at: str


def read(raw: object, where: str) -> Details:
    """The ``details`` one place of the configuration states — a check's file for its
    own node, a ``subnodes:`` entry for an aspect, a ``nodes.yaml`` entry for its path:
    a mapping of the keys its team chose to their values, in the order written. Absent
    or empty, it states none.

    **Each value is kept as written**, so it is text: a value YAML reads as anything
    else is refused, naming the key, since what it would show is not what the file
    says — ``0123`` reads as the number 83, ``12:30`` as 750, ``3.10`` as 3.1 and
    ``no`` as false. Quoting it keeps it. An empty value — ``contact:`` — is a
    statement: the key has no value here, nor beneath where nothing nearer names it.
    A value written over several lines is one line, its lines joined by a space, since
    the card and the Copy document show it on one; and a list or a mapping, which a
    line is not, is refused, as is a key that is not text or is empty.
    """
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise CheckError(f"{where} must be a mapping of a key to its value, each a "
                         f"line of Markdown, not {type(raw).__name__}")
    stated: dict[str, str] = {}
    for key, value in raw.items():
        name = _key(key, where)
        if value is None:
            stated[name] = ""
        elif isinstance(value, str):
            stated[name] = _one_line(value)
        elif isinstance(value, Mapping | list | tuple | set):
            raise CheckError(f"{where}.{name}: a detail is one line of Markdown, not "
                             f"a {type(value).__name__}")
        else:
            raise CheckError(
                f"{where}.{name}: YAML read {value!r} as a "
                f"{type(value).__name__}, and a detail is shown as written — put "
                f"the value in quotes ({name}: \"…\") so it stays what the file says")
    return tuple(stated.items())


def given(raw: Mapping[str, str] | Iterable[tuple[str, str]] | None,
          where: str) -> Details:
    """Details handed over in code — a type's on ``CheckResult.details``, a check
    built with them — as a mapping or as pairs, each value text. A value that is not
    text is the author's error and is refused naming the key, as are an empty key and
    two of the same; an empty value says nothing and is left out, and a value over
    several lines is one line."""
    if raw is None:
        return ()
    pairs = raw.items() if isinstance(raw, Mapping) else raw
    found: dict[str, str] = {}
    for pair in pairs:
        try:
            key, value = pair
        except (TypeError, ValueError) as error:
            raise CheckError(f"{where}: details are a mapping of a key to its text, "
                             f"or (key, text) pairs, not {pair!r}") from error
        name = _key(key, where)
        if name in found:
            raise CheckError(f"{where}: the detail {name!r} is given twice")
        if not isinstance(value, str):
            raise CheckError(f"{where}.{name}: a detail's value is text, a line of "
                             f"Markdown, not {type(value).__name__}")
        if text := _one_line(value):
            found[name] = text
    return tuple(found.items())


def merged(under: Details, over: Details) -> Details:
    """``over``'s details, falling back to ``under``'s key by key: a key ``under``
    names keeps its place with ``over``'s value where ``over`` names it too, and the
    keys only ``over`` names follow in its order. How ``nodes.yaml`` wins over a check's
    file on one node, a later configuration root over an earlier one, and the
    deployment's details over the type's on the node itself."""
    if not under:
        return over
    if not over:
        return under
    found = dict(under)
    found.update(over)
    return tuple(found.items())


def own(by_type: Details, by_deployment: Details) -> tuple[Detail, ...]:
    """A node's own details, as its snapshot holds them: the type's first, in its
    order, then the deployment's in theirs, each as it was given and saying so — a key
    both name standing twice, once for each, which the card resolves to the type's
    place and the deployment's value (:func:`rows`). Raw, as the API carries every
    text, so that a client resolves the card as the page does: from the givers, and
    not from a merge that would hide which place a key took."""
    return (tuple(Detail(key, text, TYPE) for key, text in by_type)
            + tuple(Detail(key, text, DEPLOYMENT) for key, text in by_deployment))


def rows(path: str, by_type: Details, by_deployment: Details,
         above: Sequence[tuple[str, Details]]) -> tuple[Row, ...]:
    """The rows of the *About* card of the node at ``path``: ``by_type`` and
    ``by_deployment`` are its own, and ``above`` what the deployment gives each node
    above it, the outermost first, by the node's path. In the card's order — the
    type's, then what comes down, then the deployment's own — a key standing once,
    where it is named first, with its nearest value; a nearest value that is empty
    stands nowhere."""
    found: dict[str, tuple[str, str]] = {key: (text, path) for key, text in by_type}
    for at, details in above:
        for key, text in details:
            # a value on the node itself is nearer than any from above; one from
            # above gives way to one from nearer, keeping its place
            if found.get(key, ("", ""))[1] != path:
                found[key] = (text, at)
    for key, text in by_deployment:
        found[key] = (text, path)
    return tuple(Row(key, text, at) for key, (text, at) in found.items() if text)


def _key(key: object, where: str) -> str:
    """A detail's key as its team wrote it, or :class:`CheckError` where it is not
    text — YAML reads ``12:`` as a number and ``yes:`` as true — or is empty."""
    if not isinstance(key, str):
        raise CheckError(f"{where}: the key {key!r} is read as a "
                         f"{type(key).__name__}; a detail's key is a name its team "
                         f"chooses — put it in quotes")
    name = key.strip()
    if not name:
        raise CheckError(f"{where}: a detail's key is a name, and one is empty")
    return name


def _one_line(text: str) -> str:
    """``text`` on one line: its lines stripped and joined by a space."""
    return " ".join(line.strip() for line in text.strip().splitlines() if line.strip())
