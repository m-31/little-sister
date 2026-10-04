"""What the Events page shows of the log (ADR-0101): the filters its URL names, read
into one filter that says whether a transition matches and how a link writes the
filter back.

Five parameters, each empty where it filters nothing. ``under`` is a node path compared
segment by segment, as an action's is (ADR-0038 decision 6); ``words`` are each found
in the reason, in any order and ignoring case; ``status`` names the status switches
that are on, by the word a row shows for the code an event moved to; ``held`` names
which of *reached* and *held back* is on; ``cause`` names the kinds of cause that are
on — a reading, a pin, a removal (ADR-0109 decision 5). A switch group with every
switch on, or with none, filters nothing and is written into no link. The window,
``from`` and ``to``, is not read here: the route reads it as the Series view does
(ADR-0098 decision 1).
"""
from __future__ import annotations

from dataclasses import dataclass

from markupsafe import Markup
from werkzeug.datastructures import MultiDict

from little_sister.status import join_path
from little_sister.tree import CAUSE_REACHED, CAUSE_READING, CAUSE_REMOVED, Event

#: The status switches in the order the page offers them.
STATUS_WORDS = ("error", "warn", "ok", "maintenance", "undefined")

#: The held-back switches: ``held=no`` is *reached*, ``held=yes`` is *held back*.
HELD_WORDS = ("no", "yes")

#: The cause switches, one for each kind of thing that writes a row: a check's
#: ``reading``; an admin's ``pin`` — set, edited or ended, a node's or a line's
#: (ADR-0107 decision 3); and a node ``removed`` from the tree (ADR-0109 decision 5).
CAUSE_WORDS = ("reading", "pin", "removed")


class FilterRefused(ValueError):
    """A filter the page cannot read: answered ``400``, naming the parameter and what
    it takes."""

    def __init__(self, name: str, said: Markup) -> None:
        super().__init__(name)
        self.name = name
        self.said = said


def cause_kind(event: Event) -> str:
    """Which of :data:`CAUSE_WORDS` wrote ``event``. A row from a log written before
    a row said its cause is a reading's, as it is drawn: without a chip. The row that
    ends a wait is a reading's too: the reading that completed the count wrote it
    (ADR-0119 decision 3)."""
    if event.cause == CAUSE_REMOVED:
        return "removed"
    if event.cause in ("", CAUSE_READING, CAUSE_REACHED):
        return "reading"
    return "pin"


def covers(under: str, path: str) -> bool:
    """Whether the node at ``path`` is the node ``under`` or beneath it, segment by
    segment: ``/hosts/nas`` covers ``/hosts/nas/disk`` and never ``/hosts/nas2``."""
    return path == under or path.startswith(under.rstrip("/") + "/")


@dataclass(frozen=True)
class EventFilter:
    """The filters an Events URL names: ``under``, the node, absolute and without a
    trailing slash, empty for every node; ``words`` as they were written; the
    ``statuses`` that are on where one is off, empty where all are; the one of
    ``no`` and ``yes`` that ``held`` has on, empty where both are; and the
    ``causes`` that are on where one is off, empty where all are."""

    under: str = ""
    words: str = ""
    statuses: tuple[str, ...] = ()
    held: str = ""
    causes: tuple[str, ...] = ()

    @property
    def folded(self) -> tuple[str, ...]:
        """The words as they are compared: each on its own, its case folded."""
        return tuple(word.casefold() for word in self.words.split())

    @property
    def narrows(self) -> bool:
        """Whether anything is set that can leave an event out."""
        return bool(self.under or self.folded or self.statuses or self.held
                    or self.causes)

    def matches(self, event: Event) -> bool:
        """Whether ``event`` is one the filter keeps: under the node, moved to a
        status that is on, reached or held back as the switches say, written by a
        cause that is on, and saying every word — its reason read whole, its lines
        together."""
        if self.under and not covers(self.under, event.path):
            return False
        if self.statuses and event.new.name.lower() not in self.statuses:
            return False
        if self.held and (self.held == "yes") != bool(event.suppressed_by):
            return False
        if self.causes and cause_kind(event) not in self.causes:
            return False
        said = "\n".join(event.reason).casefold()
        return all(word in said for word in self.folded)

    def written(self) -> dict[str, str | list[str]]:
        """The filter as a link writes it: what narrows, and nothing else."""
        written: dict[str, str | list[str]] = {}
        if self.under:
            written["under"] = self.under
        if self.folded:
            written["words"] = " ".join(self.words.split())
        if self.statuses:
            written["status"] = list(self.statuses)
        if self.held:
            written["held"] = self.held
        if self.causes:
            written["cause"] = list(self.causes)
        return written


def read_filter(args: MultiDict[str, str]) -> EventFilter:
    """The filter a request's parameters name. An empty field filters nothing, and so
    does the root; a switch the page does not offer raises :class:`FilterRefused`."""
    node = join_path(args.get("under", "").strip())
    statuses = _switches(args, "status", STATUS_WORDS, Markup(
        "The <code>status</code> filter takes <code>error</code>, <code>warn</code>, "
        "<code>ok</code>, <code>maintenance</code> or <code>undefined</code>"))
    held = _switches(args, "held", HELD_WORDS, Markup(
        "The <code>held</code> filter takes <code>no</code>, for what reached anybody, "
        "or <code>yes</code>, for what a rule held back"))
    causes = _switches(args, "cause", CAUSE_WORDS, Markup(
        "The <code>cause</code> filter takes <code>reading</code>, <code>pin</code> "
        "or <code>removed</code>"))
    return EventFilter(under="" if node == "/" else node, words=args.get("words", ""),
                       statuses=statuses, held=held[0] if held else "", causes=causes)


def _switches(args: MultiDict[str, str], name: str, offered: tuple[str, ...],
              takes: Markup) -> tuple[str, ...]:
    """The switches of one group that are on, in the order the page offers them —
    none where every one is on, or none is, since either filters nothing."""
    on: set[str] = set()
    for value in args.getlist(name):
        if not value:
            continue
        if value not in offered:
            raise FilterRefused(name, Markup("{}, not <code>{}</code>.").format(
                takes, value))
        on.add(value)
    if len(on) in (0, len(offered)):
        return ()
    return tuple(word for word in offered if word in on)
