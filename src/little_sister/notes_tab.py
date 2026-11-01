"""A node's Notes tab as the place to act (ADR-0145): the kinds its form offers, and
what came before as the tab lists it.

**The form** is one choice over one form per kind (decision 2), each posting to the
route of its own act: :data:`KINDS`, in the order the choice lists them — *Note*,
*Done*, *Seen*, *Silence*, *Maintenance*. A kind is an entry of that list: its route,
its permission, what it is set on, and its words; its fields are the template's, keyed
by its name. *Note* and *Maintenance* are set on the node or on any of its lines;
*Seen* on what fails now — a failing line, or every failure at and beneath the node,
the head's act (:class:`Target`); *Silence* on the head's act as well, and besides it
on any part that could take one later, failing or not — the node's own part where it
reads by itself, and each line it reports (ADR-0144 decision 1); and *Done* on a
failing line of the node whose failure is an event, one with an occurrence of its
own, and nowhere else (ADR-0146). The form opens on *Seen* where something the ringed
check would mark fails at the part it opens on, on *Note* elsewhere, and on the first
kind the reader may set where they may not set that one (:func:`opens_on`); the line
it opens on is the choice of every kind that may be set on it (:func:`opens_each_on`).

**What came before** is the tab's entries but the ones whose pin still stands, which
*what stands* states as their blocks (decision 6): each its kind, what it was on —
the node, a line by its text, or an act's parts — from when to when and how long,
who, why it ended and by whom, and its words (:class:`Shown`). Above what stands one
line sums it up (decision 7, :class:`Before`): how often the part was handled and
noted since the oldest entry, the last pin that ended, and the links the notes carry.
A maintenance entry planned as a window or a schedule is said by what of it ran, which
its note counts (ADR-0150): *planned as a schedule*, *3 windows ran, 2h 10m in all*,
ended *with its last window* (:func:`ran_said`, :func:`ended_word`) — and, while it
stands, its block's row says how many of its windows closed and how the last did
(:func:`ran_so_far`).

What the tab reads of the tree — what fails, what stands, which pin still stands, a
line's words now — the application hands in: this module reads notes and says them.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from little_sister.codes import StatusCode
from little_sister.notes import SCHEDULE, WINDOW, Entry, Note, Tally
from little_sister.pins import DONE, MAINTENANCE, SEEN, SILENCED
from little_sister.render import links_of
from little_sister.spans import format_span
from little_sister.tree import ENDED_CLOCK, ENDED_WORDS

#: The kind of the form that writes a note of its own (ADR-0145 decision 3), and the
#: permission it asks.
NOTE = "note"

#: How many links the line on what came before lists (ADR-0145 decision 7).
LINKS_SHOWN = 3

#: What *On* sends for a node's own part offered beside a head's act, which sends the
#: empty slug with its digest (:attr:`Target.value`): a silence on a node that reads
#: by itself while failures stand at or beneath it (ADR-0144 decision 1). No line's
#: slug carries whitespace (``reasons._check_declared``), so it is never one, and the
#: route reads it as the node's own part alone.
OWN_PART = "own part"


@dataclass(frozen=True)
class Kind:
    """One kind of the tab's form (ADR-0145 decision 2): its ``name`` — a pin's kind,
    or :data:`NOTE` — which is the permission its act asks as well
    (:data:`~little_sister.identity.PERMISSIONS`); the ``endpoint`` its form posts to;
    whether it is set on what fails now (``on_failures``) — a failing line, or every
    failure at and beneath the node, the head's act — rather than on the node or any of
    its lines; and its words: its choice's, the sentence above its fields of what it
    does, its button's, and the word an entry of it is headed by. ``on_events`` is a
    kind set on a failing line of the node whose failure is an event — an occurrence
    of its own — and nowhere else, *Done* (ADR-0146). ``on_parts`` is a kind set on
    the head's act and, beside it, on any part that could take it later, failing or
    not: the node's own part where it reads by itself and each line it reports,
    *Silence* (ADR-0144 decision 1)."""
    name: str
    word: str
    endpoint: str
    on_failures: bool
    does: str
    button: str
    entry_word: str
    on_events: bool = False
    on_parts: bool = False

    @property
    def permission(self) -> str:
        return self.name


#: The form's kinds, in the order its choice lists them (ADR-0145 decision 2), *Done*
#: between *Note* and *Seen* (ADR-0146).
KINDS: tuple[Kind, ...] = (
    Kind(NOTE, "Note", "notes", False,
         "It is kept beside the node's status and changes nothing it shows.",
         "Add the note", "Note"),
    Kind(DONE, "Done", "done", False,
         "The line shows ok with the failure it closed beside it, and counts as ok "
         "above, until it reads anything else: its next run ends it, and alarms as "
         "new if it fails.",
         "Mark done", "Done", on_events=True),
    Kind(SEEN, "Seen", "seen", True,
         "What it marks keeps its color and counts as ok above until it recovers, "
         "gets worse, fails anew or is no longer reported; a failure that comes "
         "later alarms.",
         "Mark seen", "Seen"),
    Kind(SILENCED, "Silence", "silenced", True,
         "What it silences keeps its color and counts above as chosen whenever it "
         "fails — on a part that reads ok now, from its next failure — through every "
         "recovery until its deadline; a failure that comes later alarms.",
         "Silence", "Silenced", on_parts=True),
    Kind(MAINTENANCE, "Maintenance", "maintenance", False,
         "Nothing it covers alarms while a window of it is open; its check keeps "
         "running, and counts again as each window closes.",
         "Set maintenance", "Maintenance"),
)
KINDS_BY_NAME: Mapping[str, Kind] = {kind.name: kind for kind in KINDS}


@dataclass(frozen=True)
class Target:
    """One choice of a kind's *On* (ADR-0145 decision 2): the node, ``slug`` empty;
    one of its lines, by its slug and its ``line`` as the run reports it; or, for a
    kind set on what fails, every failure at and beneath the node, each its own — the
    head's act (``act``, how many parts it marks), whose parts the tab lists above the
    form and whose digest the form carries. ``own`` says the act's one part is the
    node's own failure — and, without ``act``, that it is the node's own part offered
    beside a head's act over other parts, whose choice sends :data:`OWN_PART`.
    ``occurrence`` is a line's event as the tab drew it, which a *done* set on it
    closes and its form carries (ADR-0146)."""
    slug: str = ""
    line: str = ""
    act: int = 0
    own: bool = False
    occurrence: str = ""

    @property
    def value(self) -> str:
        """What *On* sends for it: its slug — empty for the node and for the head's
        act — and :data:`OWN_PART` for the node's own part beside a head's act."""
        return OWN_PART if self.own and not self.act else self.slug


def targets(kind: Kind, lines: Sequence[tuple[str, str]],
            fails: Sequence[tuple[str, str]], *, here: str,
            held: Iterable[str] = (), keep: str | None = None,
            events: Mapping[str, str] | None = None) -> tuple[Target, ...]:
    """What ``kind`` may be set on at the node at ``here``: for a kind set on what
    fails, the head's act over ``fails`` — each part as its path and its line's slug,
    as the ringed check finds them — and each failing line of the node; for a kind set
    on events, each failing line of the node that ``events`` gives an occurrence, by
    its slug, carrying it (ADR-0146); for any other, the node and every line it
    reports (``lines``, each its slug and its text) but the parts ``held`` names — the
    node, ``""``, and lines by slug — which a pin of the kind stands on already and
    whose block changes it (ADR-0104 decision 4). One failure that is a line of the
    node is that line alone.

    A kind set on parts (``on_parts``, *Silence*) takes the head's act over ``fails``
    and, beside it, every part that could take it later, failing or not (ADR-0144
    decision 1): the node's own part and each of ``lines`` — the lines of a node whose
    lines are members, which the caller hands in — but the parts ``held`` names,
    which cannot take one: a part in maintenance, one a person holds already, a node
    that reads by its lines. The node's own part is the head's act where that act is
    its own failure alone, and is offered beside any other act as :data:`OWN_PART`.

    ``keep`` is the part a refused write chose — a line's slug, ``""`` for the node or
    the head's act, or :data:`OWN_PART` — which stays a choice where it would
    otherwise be gone, a pin set on it since the tab was drawn or its failure over:
    the form comes back with the part chosen as it was, so that sending it again is
    refused again rather than setting the kind on another part than the one chosen."""
    said = dict(lines)
    known = events or {}
    offered: list[Target] = []
    if kind.on_events:
        offered.extend(Target(slug, said.get(slug, ""), occurrence=known[slug])
                       for path, slug in fails
                       if path == here and slug and known.get(slug))
        if keep and not any(choice.slug == keep for choice in offered):
            offered.append(Target(keep, said.get(keep, ""),
                                  occurrence=known.get(keep, "")))
        return tuple(offered)
    taken = set(held)
    if kind.on_failures:
        own_lines = [slug for path, slug in fails if path == here and slug]
        if fails and not (len(fails) == 1 and own_lines):
            offered.append(Target(act=len(fails),
                                  own=list(fails) == [(here, "")]))
        if kind.on_parts:
            if "" not in taken and not (offered and offered[0].own):
                offered.append(Target(own=bool(offered)))
            offered.extend(Target(slug, text) for slug, text in lines
                           if slug and slug not in taken)
        else:
            offered.extend(Target(slug, said.get(slug, "")) for slug in own_lines)
    else:
        if "" not in taken:
            offered.append(Target())
        offered.extend(Target(slug, text) for slug, text in lines
                       if slug and slug not in taken)
    if keep is not None and not any(choice.value == keep for choice in offered):
        if keep == OWN_PART:
            offered.append(Target(own=True))
        elif keep:
            offered.append(Target(keep, said.get(keep, "")))
        else:
            offered.insert(0, Target())
    return tuple(offered)


def opens_on(offered: Mapping[str, Sequence[Target]], *, asked: str = "",
             line: str = "", failing: bool = False) -> tuple[str, str]:
    """The kind the form opens on and the choice of its *On* (ADR-0145 decision 2):
    the one ``asked`` (``?kind=``), where it is offered; else *Seen* where something
    the ringed check would mark fails at the part the tab opens on (``failing``) —
    the line ``line`` (``?reason=``), or the node — and *Note* elsewhere; and the
    first kind offered where the one it would open on is not. ``offered`` are the
    kinds the reader may set, each with what it may be set on, in the form's order.
    The choice is ``line`` where the kind may be set on it, and its first otherwise.
    Nothing where nothing is offered."""
    if not offered:
        return "", ""
    wanted = asked if asked in offered else (SEEN if failing else NOTE)
    name = wanted if wanted in offered else next(iter(offered))
    return name, _choice(offered[name], line)


def opens_each_on(offered: Mapping[str, Sequence[Target]], *,
                  line: str = "") -> dict[str, str]:
    """Every kind's choice under *On* as the form opens, by the kind's name (ADR-0145
    decision 2): the line ``line`` (``?reason=``) wherever the kind may be set on it,
    and the kind's first choice elsewhere — so that the line the tab opens on stays
    chosen across a change of kind, as a part chosen under *On* does, the chosen kind's
    being :func:`opens_on`'s. ``offered`` as :func:`opens_on` takes it."""
    return {name: _choice(choices, line) for name, choices in offered.items()}


def _choice(choices: Sequence[Target], line: str) -> str:
    """``line`` where it is what one of ``choices`` sends, and the first otherwise —
    the head's act, like the node, sends no slug (:attr:`Target.value`)."""
    if line and any(choice.value == line for choice in choices):
        return line
    return choices[0].value if choices else ""


@dataclass(frozen=True)
class Part:
    """One part an entry is on, as the tab lists it (ADR-0145 decisions 5 and 6): its
    note, which says its node and its line and how its pin ended; its line by its
    text — as the run reports it now where it does, as the note found it where it does
    not — and whether the run reports it."""
    note: Note
    line: str = ""
    reported: bool = True

    @property
    def path(self) -> str:
        return self.note.path

    @property
    def slug(self) -> str:
        return self.note.slug


@dataclass(frozen=True)
class Shown:
    """One entry of a node's tab (ADR-0145 decision 6), as it is said: a note of its
    own, or the record of a pin — one act's, whose parts are its notes the tab holds,
    ``in_all`` how many it had wherever they stand. ``here`` is the tab's node,
    ``standing`` that a pin of it still stands, and ``editable`` that it is a note of
    its own the reader may edit (ADR-0047 decision 5)."""
    entry: Entry
    parts: tuple[Part, ...]
    here: str
    in_all: int = 1
    standing: bool = False
    editable: bool = False

    @property
    def first(self) -> Note:
        return self.entry.first

    @property
    def kind(self) -> str:
        """Its kind: :data:`NOTE` for a note of its own, the pin's kind for a record —
        empty for a pin's note written before a note kept its kind, which says what
        it said (ADR-0145 decision 4)."""
        return self.first.kind if self.first.pin else NOTE

    @property
    def word(self) -> str:
        known = KINDS_BY_NAME.get(self.kind)
        return known.entry_word if known is not None else "Note"

    @property
    def text(self) -> str:
        return self.entry.text

    @property
    def started(self) -> datetime:
        return self.entry.created_at

    @property
    def last(self) -> Note | None:
        """The part whose end was the act's — the last to end — or ``None`` while
        one has not ended, or ended before its note recorded ends."""
        ends = [part.note for part in self.parts]
        if not ends or any(note.ended_at is None for note in ends):
            return None
        return max(ends, key=lambda note: note.ended_at or self.started)

    @property
    def ended_at(self) -> datetime | None:
        last = self.last
        return last.ended_at if last is not None else None

    @property
    def ended(self) -> str:
        last = self.last
        return last.ended if last is not None else ""

    @property
    def ended_by(self) -> str:
        last = self.last
        return last.ended_by if last is not None else ""

    @property
    def lasted(self) -> str:
        """How long it stood, from its set to its end, as a measured span is written
        (``2h 28m``) — empty where its end is not known."""
        ended = self.ended_at
        if ended is None:
            return ""
        return format_span(max(0.0, (ended - self.started).total_seconds()))

    @property
    def status(self) -> StatusCode | None:
        return self.first.status

    @property
    def level(self) -> StatusCode | None:
        return self.first.level

    @property
    def made_at(self) -> str:
        """The node the act was made on, where that is another than the tab's: a
        branch's head, which marked failures beneath it."""
        made = self.first.at
        return made if made and made != self.here else ""

    @property
    def alone(self) -> Part | None:
        """Its one part, where the tab holds one, which the entry names inline;
        ``None`` where its parts are listed."""
        return self.parts[0] if len(self.parts) == 1 else None

    @property
    def planned(self) -> str:
        """What the maintenance entry it records was planned as (ADR-0150) — a window,
        a schedule — where its note counted its windows; empty for every other entry,
        one window set from now among them, which is said as a pin is."""
        first = self.first
        return first.planned if first.pin and first.tally is not None else ""

    @property
    def ran(self) -> str:
        """What ran of the entry it records, planned as a window or a schedule, once
        it has ended (:func:`ran_said`) — said in place of how long it stood, which
        reads as maintenance from its set to its end. Empty for every other entry."""
        tally = self.first.tally
        if not self.planned or tally is None or self.standing:
            return ""
        return ran_said(self.planned, tally)


#: How an entry planned as a window or a schedule that ended at its end says it
#: (ADR-0150): with the window that ended it, its last — never *at its end*, which
#: reads as maintenance that held until then.
_ENDED_WITH: Mapping[str, str] = {WINDOW: "with its window",
                                  SCHEDULE: "with its last window"}


def ended_word(ended: str, planned: str = "") -> str:
    """Why an entry ended, as every surface says it after the act (ADR-0145 decision
    6): the log's word, in its words (``tree.ENDED_WORDS``) — and, for an entry planned
    as a window or a schedule (``planned``), one that ended at its end *with its
    window*, *with its last window* (ADR-0150). Empty for a word nobody knows."""
    if ended == ENDED_CLOCK and planned in _ENDED_WITH:
        return _ENDED_WITH[planned]
    return ENDED_WORDS.get(ended, "")


def _windows(count: int) -> str:
    return f"{count} window{'' if count == 1 else 's'}"


def ran_said(planned: str, tally: Tally, *, standing: bool = False) -> str:
    """What ran of an entry planned as a window or a schedule (ADR-0150), as its
    history and the Copy document say it: once it has ended, its windows and how long
    they held — *3 windows ran, 2h 10m in all*, *1 window ran, 1m 11s*, *no window
    opened*, and a window's *it ran 1m 11s* or *it never opened* — and, while it
    stands, how many have opened — *3 windows have opened*, *no window has opened yet*,
    *it has opened*, *it has not opened yet*. Empty for an entry planned as
    neither."""
    if planned == WINDOW and tally.windows <= 1:
        if standing:
            return "it has opened" if tally.windows else "it has not opened yet"
        return (f"it ran {format_span(tally.held)}" if tally.windows
                else "it never opened")
    if planned not in (WINDOW, SCHEDULE):
        return ""
    if standing:
        if not tally.windows:
            return "no window has opened yet"
        return (f"{_windows(tally.windows)} "
                f"{'has' if tally.windows == 1 else 'have'} opened")
    if not tally.ran:
        return "no window opened"
    held = format_span(tally.held)
    return (f"1 window ran, {held}" if tally.ran == 1
            else f"{_windows(tally.ran)} ran, {held} in all")


@dataclass(frozen=True)
class Ran:
    """What has run of a schedule that stands, as its block's row on the tab says it
    (ADR-0150): how many of its windows closed — *3 windows* — and how the last closed,
    in the words an end is said in, and by whom where a person closed it: *3 windows
    ran, the last closed by hand, by pan*. Its entry's own end is said apart, once it
    has one (:func:`ended_word`)."""
    windows: str
    how: str
    by: str = ""


def ran_so_far(planned: str, tally: Tally | None) -> Ran | None:
    """What has run of an entry planned as a schedule while it stands (:class:`Ran`),
    and ``None`` where none of its windows has closed — and for one planned as one
    window, whose close is its end."""
    if planned != SCHEDULE or tally is None or not tally.ran:
        return None
    return Ran(_windows(tally.ran), ENDED_WORDS.get(tally.last_closed, ""),
               tally.last_closed_by)


def shown(entries: Iterable[Entry], *, here: str,
          line_now: Callable[[str, str], str | None],
          stands: Callable[[Note], bool],
          editable: Callable[[Note], bool],
          act_size: Callable[[str], int]) -> tuple[Shown, ...]:
    """``entries`` as the tab says them, newest first: each part's line by its text —
    ``line_now`` answers what the run reports at a path and a slug now, ``None`` where
    it does not report it, and the line says what its note found where that is empty —
    whether a pin of it still ``stands``, whether a note of its own is ``editable``,
    and how many parts its act had, ``act_size`` by its pin."""
    said: list[Shown] = []
    for entry in entries:
        parts = []
        for note in entry.notes:
            now = line_now(note.path, note.slug) if note.slug else ""
            found = next((line.text for line in note.context.lines
                          if line.slug == note.slug), "") if note.slug else ""
            parts.append(Part(note, line=now or found, reported=now is not None))
        first = entry.first
        said.append(Shown(
            entry, tuple(parts), here,
            in_all=max(len(parts), act_size(first.pin)) if first.pin else 1,
            standing=bool(first.pin) and any(stands(note) for note in entry.notes),
            editable=not first.pin and editable(first)))
    return tuple(said)


@dataclass(frozen=True)
class Before:
    """The line on what came before (ADR-0145 decision 7): how often the part was
    handled here — the entries of pins that ended — and noted, since the oldest entry
    the tab keeps; the last time, the newest of those pins; and the links its notes
    carry, each as where it leads and its own words, newest first, each once, at most
    :data:`LINKS_SHOWN`."""
    handled: int
    noted: int
    since: datetime | None
    last: Shown | None
    links: tuple[tuple[str, str], ...]


def before(history: Sequence[Shown], every: Sequence[Shown]) -> Before:
    """The line over ``history``, what came before, newest first; the links are read
    from ``every`` entry the tab keeps, a pin that stands among them, newest first."""
    pins = [entry for entry in history if entry.first.pin]
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in every:
        for href, words in links_of(entry.text):
            if href not in seen and len(links) < LINKS_SHOWN:
                seen.add(href)
                links.append((href, words))
    return Before(
        handled=len(pins), noted=len(history) - len(pins),
        since=min((entry.started for entry in history), default=None),
        last=pins[0] if pins else None, links=tuple(links))
