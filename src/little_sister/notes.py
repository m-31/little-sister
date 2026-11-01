"""A node's notes (ADR-0047, ADR-0140): what somebody knows about a node, kept beside
its status and never part of it.

A note is Markdown an admin writes — on a node or on one of its lines, by itself or
as a pin's note — with its authors and its times and the context it was written in:
what the node showed and its lines as they stood (ADR-0047 decision 6). A node keeps
its notes as a history, appended to and never rewritten but for an edit: a pin's note
while its pin stands, edited with the pin; a note of its own while it is the newest on
its node (decision 5). The history outlives the pin, the node and the configuration
that made the node (decision 7): nothing reaps it, and only retention retires a note
— the four settings keys of decision 9, on the scheduler tick (decision 12).

A note is no contribution rule (decision 2): it counts nothing, holds nothing back
and writes no row of the log. The book keeps the notes in memory by path and writes
them through as ``var/state/notes.json`` (ADR-0071), plain JSON an operator reads, and
an adopted copy replaces them at a takeover as the pins are replaced (ADR-0077).

**Every pin leaves an entry that records it** (ADR-0145 decision 4): a pin's note
enters as the pin is set, whatever its kind — one set without words a note with no
text, a *record* — and keeps its pin's kind, a seen's status and a silence's level, and
the pin's end: when, why in the log's words, and who, where a person ended it. **One
act on many parts is one entry** (decision 5): the pins one act sets share their
creation, so their notes name one pin, and a node's tab — and its retention — counts
them as one; where the act was made on another node, each note says where (``at``), and
that node's tab lists the act too.

**A maintenance entry's note counts its windows** (ADR-0150): what the entry was
planned as — one window set ahead, or a schedule — and every window of it that held,
each once, from what the tree tells as it opens and closes them
(:meth:`NoteBook.window_seen`): how many, how long those that closed held in all, the
one open now, and the last that closed — from when until when, and how. The note is
the only record that ties windows to their entry and outlives the log's pruning; a
note written before notes counted windows counts none, and says what it said.
"""
from __future__ import annotations

import calendar
import re
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from little_sister import instants, values
from little_sister.codes import StatusCode
from little_sister.pins import MAINTENANCE, NO_NOTE
from little_sister.state import NOTES_FILE, StateLayer
from little_sister.status import join_path

if TYPE_CHECKING:
    from little_sister.pins import Pin
    from little_sister.tree import StatusSnapshot, WindowSeen

#: How many of a node's lines a note's context keeps, the rest counted: a node of
#: 150 lines would otherwise put every one of them into every note written on it.
CONTEXT_LINES = 50

#: The retention a deployment that says nothing gets (ADR-0047 decision 10): the
#: last ten on a node always kept, fifty the routine bound, and thirteen and
#: twenty-five months the ages — more than a year, so that a yearly problem is still
#: recognizable when it comes back, and more than two years, one repeat and a margin.
DEFAULT_KEEP = 10
DEFAULT_CAP = 50
DEFAULT_MIN_AGE = "13mo"
DEFAULT_MAX_AGE = "25mo"

#: An age as the four keys write it: a number and a unit — ``mo`` months, ``w``
#: weeks, ``d`` days, ``h`` hours, ``s`` seconds.
_AGE = re.compile(r"(\d+)\s*(mo|w|d|h|s)")
_SECONDS = {"w": 604800, "d": 86400, "h": 3600, "s": 1}


@dataclass(frozen=True)
class Age:
    """How old a note may grow before a rule may retire it: whole months, which
    follow the calendar in the configured zone, or a number of seconds."""
    months: int = 0
    seconds: int = 0

    def cutoff(self, now: datetime, zone: ZoneInfo) -> datetime:
        """The instant a note written before is older than this age: ``now`` less
        the months, on the calendar of ``zone`` — the same day of the month, or its
        last where the month is shorter — less the seconds."""
        local = now.astimezone(zone)
        month = local.month - 1 - self.months
        year = local.year + month // 12
        month = month % 12 + 1
        day = min(local.day, calendar.monthrange(year, month)[1])
        moved = local.replace(year=year, month=month, day=day)
        return moved.astimezone(now.tzinfo) - timedelta(seconds=self.seconds)


def parse_age(text: object) -> Age:
    """An age as ``notes_min_age`` and ``notes_max_age`` write it (ADR-0047 decision
    10): ``13mo``, ``400d``, ``8w``. A bare ``m`` is refused: it is minutes
    everywhere else in the configuration, and a retention age of thirteen minutes is
    no value anyone meant to write.

    :raises ValueError: naming what is wrong."""
    written = str(text).strip()
    match = _AGE.fullmatch(written)
    if match is None:
        if re.fullmatch(r"\d+\s*m", written):
            raise ValueError(
                f"{written!r} reads as minutes, which no note's age is: write "
                f"months as mo (13mo)")
        raise ValueError(f"{written!r} is no age: a number and mo, w, d, h or s")
    number, unit = int(match.group(1)), match.group(2)
    if unit == "mo":
        return Age(months=number)
    return Age(seconds=number * _SECONDS[unit])


@dataclass(frozen=True)
class Retention:
    """When a note is retired (ADR-0047 decision 9): never while it is among the last
    ``keep`` on its node; past ``max_age`` by its age alone; and past ``min_age``
    while its node holds more than ``cap``, the oldest first and only as many as
    bring the node down to ``cap`` — trimmed for volume, never below the floor."""
    keep: int = DEFAULT_KEEP
    cap: int = DEFAULT_CAP
    min_age: Age = field(default_factory=lambda: parse_age(DEFAULT_MIN_AGE))
    max_age: Age = field(default_factory=lambda: parse_age(DEFAULT_MAX_AGE))


@dataclass(frozen=True)
class ContextLine:
    """One line of a node as a note found it: its address, its status word —
    ``error``, as the page names it, empty for a line that carries none — and its
    text, as the check wrote it."""
    slug: str
    code: str
    text: str


@dataclass(frozen=True)
class Context:
    """What a node showed when a note was written on it (ADR-0047 decision 6): its
    status word, empty where no node stood, and its lines — for a note on a line,
    that line — the first :data:`CONTEXT_LINES` of them, and how many more."""
    code: str = ""
    lines: tuple[ContextLine, ...] = ()
    more: int = 0

    def to_dict(self) -> dict[str, Any]:
        said: dict[str, Any] = {"code": self.code}
        if self.lines:
            said["lines"] = [{"slug": line.slug, "code": line.code,
                              "text": line.text} for line in self.lines]
        if self.more:
            said["more"] = self.more
        return said

    @classmethod
    def from_dict(cls, data: object) -> Context:
        if not isinstance(data, Mapping):
            return cls()
        lines = tuple(
            ContextLine(slug=values.text(raw, "slug"), code=values.text(raw, "code"),
                        text=values.text(raw, "text"))
            for raw in values.rows(data, "lines") if isinstance(raw, Mapping))
        return cls(code=values.text(data, "code"), lines=lines,
                   more=values.number(data, "more"))


def context_of(node: StatusSnapshot | None, slug: str = "") -> Context:
    """What ``node`` shows as a note is written on it (ADR-0047 decision 6): its
    status word and its lines as they stand — for a note on its line ``slug``, that
    line, where the run reports it — the first :data:`CONTEXT_LINES` of them, and
    how many more. Nothing where no node stands."""
    if node is None:
        return Context()
    lines = [line for line in node.reasons if not slug or line.slug == slug]
    return Context(
        code=node.code.name.lower(),
        lines=tuple(ContextLine(slug=line.slug,
                                code=line.code.name.lower() if line.code else "",
                                text=line.text)
                    for line in lines[:CONTEXT_LINES]),
        more=max(0, len(lines) - CONTEXT_LINES))


def _status(data: Mapping[str, Any], key: str) -> StatusCode | None:
    """The status a note's file says under ``key``, or ``None`` where it says none.

    :raises ValueError: it says one that is no status."""
    said = values.text(data, key)
    try:
        return StatusCode[said] if said else None
    except KeyError:
        raise ValueError(f"a note's {key} {said!r}, which is no status") from None


#: What a maintenance entry was planned as (ADR-0150), the nouns its history line and
#: the Copy document name it by — the ones *Handled*'s *Planned* counts in: one window
#: set ahead, and a schedule, every other entry with windows. One window set from now
#: is neither, and is said as a pin is.
WINDOW = "window"
SCHEDULE = "schedule"


def planned_of(entry: Pin, before: str = "") -> str:
    """What ``entry`` was planned as, its note having said ``before``: a series is a
    :data:`SCHEDULE`, and stays one where an edit makes it one window; one window is a
    :data:`WINDOW` where it starts after the entry was made, and nothing where it starts
    as it was made — set from now; and any other pin is nothing."""
    schedule = entry.schedule
    if entry.kind != MAINTENANCE or schedule is None:
        return ""
    if before == SCHEDULE or not schedule.is_one_off:
        return SCHEDULE
    return WINDOW if schedule.starts_at > entry.created_at else ""


@dataclass(frozen=True)
class Tally:
    """The windows of a maintenance entry that held (ADR-0150), as its note counts
    them from what the tree tells (:meth:`NoteBook.window_seen`): ``windows``, how many
    opened — each once: a window told again, at a restart inside it or an edit while it
    is open, counts no more — and ``held``, how long those that closed held in all, in
    seconds, each from when it began to hold; the one open now, from ``open_since``
    until ``open_until`` as it stands; and the last that closed, from ``last_start``
    until ``last_end``, ``last_closed`` how, in the log's words (``tree.ENDED_*``), and
    ``last_closed_by`` who, where a person closed it. The surfaces say how many ran,
    how long, and how the last closed; its start and end are kept beside how it closed
    and said nowhere yet."""
    windows: int = 0
    held: float = 0.0
    open_since: datetime | None = None
    open_until: datetime | None = None
    last_start: datetime | None = None
    last_end: datetime | None = None
    last_closed: str = ""
    last_closed_by: str = ""

    @property
    def ran(self) -> int:
        """How many of its windows closed — every one, once its entry has ended."""
        return self.windows - (1 if self.open_since is not None else 0)

    def closed(self, when: datetime, why: str, by: str = "") -> Tally:
        """The tally once the window open in it closed ``when`` — or at its own end,
        where that came first: the entry's last window, or one that closed while the
        instance was down — for ``why``, by ``by``. Itself where none is open."""
        if self.open_since is None:
            return self
        end = when if self.open_until is None else min(when, self.open_until)
        end = max(end, self.open_since)
        return replace(self, held=self.held + (end - self.open_since).total_seconds(),
                       open_since=None, open_until=None, last_start=self.open_since,
                       last_end=end, last_closed=why, last_closed_by=by)

    def holding(self, start: datetime, until: datetime) -> Tally:
        """The tally with the window that began to hold at ``start`` open, until
        ``until`` as it stands: counted where it is not the one open in it, and its end
        followed where it is — extended, or told again."""
        if self.open_since == start:
            return self if self.open_until == until else replace(self, open_until=until)
        return replace(self, windows=self.windows + 1, open_since=start,
                       open_until=until)

    def to_dict(self) -> dict[str, Any]:
        """The tally as a note's file carries it: its counts, each time in UTC, and how
        the last window closed, each only where it has it."""
        said: dict[str, Any] = {"windows": self.windows, "held": self.held}
        for name, moment in (("open_since", self.open_since),
                             ("open_until", self.open_until),
                             ("last_start", self.last_start),
                             ("last_end", self.last_end)):
            if moment is not None:
                said[name] = instants.stamp(moment)
        if self.last_closed:
            said["last_closed"] = self.last_closed
        if self.last_closed_by:
            said["last_closed_by"] = self.last_closed_by
        return said

    @classmethod
    def from_dict(cls, data: object) -> Tally:
        """A tally back from a note's file — :class:`ValueError` for one that is not a
        mapping, a count that is no whole number, a length that is no number, and a
        time that is no instant with an offset, which the store reports for the
        file."""
        if not isinstance(data, Mapping):
            raise ValueError("a note's tally is not a mapping")
        windows, held = data.get("windows", 0), data.get("held", 0.0)
        if isinstance(windows, bool) or not isinstance(windows, int) or windows < 0:
            raise ValueError(f"a note's tally counts {windows!r} windows")
        if isinstance(held, bool) or not isinstance(held, int | float) or held < 0:
            raise ValueError(f"a note's tally held its windows {held!r} seconds")

        def moment(name: str) -> datetime | None:
            value = data.get(name)
            return (None if value is None
                    else instants.instant(value, f"a note's tally's {name}"))

        return cls(windows=windows, held=float(held),
                   open_since=moment("open_since"), open_until=moment("open_until"),
                   last_start=moment("last_start"), last_end=moment("last_end"),
                   last_closed=values.text(data, "last_closed"),
                   last_closed_by=values.text(data, "last_closed_by"))


@dataclass(frozen=True)
class Note:
    """One note on the node at ``path``, or on its line ``slug``: its Markdown, who
    wrote it first and when, who changed it last and when — the two dates of a pin
    (ADR-0014) — the pin it is the note of, by that pin's creation, empty for a note
    of its own, and the context it was written in.

    A pin's note records its pin (ADR-0145 decision 4): its ``kind``, the ``status`` a
    *seen* was set at and the ``level`` a silence holds its part at — following the
    pin's edits while it stands — and its end: ``ended_at``, ``ended``, why in the
    log's words (``tree.ENDED_*``), and ``ended_by``, who, where a person ended it. A
    note of its own keeps none of them, and neither does a pin's note written before
    a note kept them, until its pin ends. ``at`` is the node the act that set its pin
    was made on, where that is not its own — a branch's head marking a failure beneath
    it (decision 5) — and empty everywhere else. A maintenance entry's note says what
    it was planned as, ``planned`` (:func:`planned_of`), following its edits, and counts
    its windows, ``tally`` (ADR-0150) — ``None`` on every other note, and on one written
    before notes counted windows.

    ``key`` names it among its node's notes, its creation as a file spells it;
    ``token`` is the compare-and-set an edit names (ADR-0047 decision 5)."""
    path: str
    slug: str
    text: str
    created_at: datetime
    created_by: str
    set_at: datetime
    set_by: str
    pin: str = ""
    context: Context = field(default_factory=Context)
    kind: str = ""
    status: StatusCode | None = None
    level: StatusCode | None = None
    ended_at: datetime | None = None
    ended: str = ""
    ended_by: str = ""
    at: str = ""
    planned: str = ""
    tally: Tally | None = None

    @property
    def key(self) -> str:
        return instants.stamp(self.created_at)

    @property
    def token(self) -> str:
        return instants.stamp(self.set_at)

    def to_dict(self) -> dict[str, Any]:
        """The note as its file carries it, under its path: each time in UTC, and what
        it records of its pin only where it has it."""
        said: dict[str, Any] = {
            "text": self.text,
            "created_at": instants.stamp(self.created_at),
            "created_by": self.created_by,
            "set_at": instants.stamp(self.set_at), "set_by": self.set_by,
            "context": self.context.to_dict()}
        if self.slug:
            said["slug"] = self.slug
        if self.pin:
            said["pin"] = self.pin
        if self.kind:
            said["kind"] = self.kind
        if self.status is not None:
            said["status"] = self.status.name
        if self.level is not None:
            said["level"] = self.level.name
        if self.ended_at is not None:
            said["ended_at"] = instants.stamp(self.ended_at)
        if self.ended:
            said["ended"] = self.ended
        if self.ended_by:
            said["ended_by"] = self.ended_by
        if self.at:
            said["at"] = self.at
        if self.planned:
            said["planned"] = self.planned
        if self.tally is not None:
            said["tally"] = self.tally.to_dict()
        return said

    @classmethod
    def from_dict(cls, path: str, data: Mapping[str, Any]) -> Note:
        """Read one note, its times strictly — :class:`ValueError` for one that is no
        instant with an offset, and for a status or a level that is none, which the
        store reports for the file."""
        created = instants.instant(data.get("created_at"), "a note's created_at")
        changed = data.get("set_at")
        ended = data.get("ended_at")
        made = values.text(data, "at")
        counted = data.get("tally")
        return cls(
            path=path, slug=values.text(data, "slug"),
            text=values.text(data, "text"),
            created_at=created, created_by=values.text(data, "created_by"),
            set_at=(created if changed is None
                    else instants.instant(changed, "a note's set_at")),
            set_by=values.text(data, "set_by"), pin=values.text(data, "pin"),
            context=Context.from_dict(data.get("context")),
            kind=values.text(data, "kind"), status=_status(data, "status"),
            level=_status(data, "level"),
            ended_at=(None if ended is None
                      else instants.instant(ended, "a note's ended_at")),
            ended=values.text(data, "ended"), ended_by=values.text(data, "ended_by"),
            at=join_path(made) if made else "", planned=values.text(data, "planned"),
            tally=None if counted is None else Tally.from_dict(counted))


def _words(entry: Pin) -> str:
    """What ``entry``'s note says: its words, and none where a maintenance pin was set
    without any — the placeholder it holds is nobody's words (ADR-0014)."""
    return "" if entry.kind == MAINTENANCE and entry.note == NO_NOTE else entry.note


@dataclass(frozen=True)
class Entry:
    """One entry of a node's history (ADR-0145 decisions 5 and 6): a note of its own,
    or the notes one act left at the node — on the node, on its lines, or, for an act
    made on it, on the nodes beneath it — which name one pin's creation, oldest first.
    Its time is its first note's creation, as a file keeps it."""
    notes: tuple[Note, ...]

    @property
    def first(self) -> Note:
        return self.notes[0]

    @property
    def created_at(self) -> datetime:
        return self.first.created_at

    @property
    def pin(self) -> str:
        return self.first.pin

    @property
    def text(self) -> str:
        """The words of the act — its first note's, which every note of one act shares
        as it was set, and which an edit of one pin changes for that one alone."""
        return self.first.text


def entries_of(notes: Iterable[Note]) -> tuple[Entry, ...]:
    """``notes`` as entries, newest first (ADR-0145 decision 5): every note of its own
    one entry, and the notes that name one pin's creation one entry, oldest first
    within it."""
    acts: dict[str, list[Note]] = {}
    own: list[Entry] = []
    for note in notes:
        if note.pin:
            acts.setdefault(note.pin, []).append(note)
        else:
            own.append(Entry((note,)))
    found = [*own, *(Entry(tuple(sorted(held, key=_age))) for held in acts.values())]
    return tuple(sorted(found, key=lambda entry: entry.created_at, reverse=True))


@dataclass(frozen=True)
class NoteWrite:
    """The outcome of a guarded edit: ``applied`` where the history changed,
    ``refused`` where the guard said no — another edit came first, or the note may
    no longer be edited — with ``current`` what the history holds now."""
    applied: bool
    current: Note | None = None
    refused: bool = False


class NoteBook:
    """Every node's notes, by path — the node's own and its lines' together, oldest
    first — in memory, written through by every change (ADR-0071). Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._notes: dict[str, list[Note]] = {}
        self._store: NoteStore | None = None
        # What the tree told of an entry's windows before its note entered — the set's
        # own window, told in the write that sets it — by path, line and the pin's
        # creation, for the note to take as it enters (:meth:`pinned`).
        self._unheard: dict[tuple[str, str, str], Tally] = {}

    def use_store(self, store: NoteStore) -> None:
        """Write every change through ``store`` from now on."""
        with self._lock:
            self._store = store

    def forget(self) -> None:
        """Hold no note and write through no store (tests)."""
        with self._lock:
            self._notes = {}
            self._store = None
            self._unheard = {}

    def restore(self, notes: Mapping[str, Sequence[Note]]) -> None:
        """Take ``notes`` as the history — the start's read, or an adopted copy at
        a takeover (ADR-0077) — in place of what the book held."""
        with self._lock:
            self._notes = {join_path(path): sorted(held, key=_age)
                           for path, held in notes.items() if held}
            self._unheard = {}

    # --- reading ---

    def of(self, path: str) -> tuple[Note, ...]:
        """The notes on the node at ``path`` and on its lines, newest first."""
        with self._lock:
            return tuple(reversed(self._notes.get(join_path(path), ())))

    def count(self, path: str) -> int:
        """How many entries the node's tab lists (ADR-0145 decision 5): an act on many
        parts one, and the acts made on the node from beneath it among them."""
        return len(self.entries(path))

    def entries(self, path: str) -> tuple[Entry, ...]:
        """The node's history as its tab lists it, newest first (ADR-0145 decision
        5): its notes and its lines', an act's notes one entry — and every act made on
        it whose parts stand beneath it, by the notes those parts keep, which say it
        was made here. None of the notes the nodes beneath it keep of their own."""
        held = join_path(path)
        prefix = held.rstrip("/") + "/"
        with self._lock:
            found = [*self._notes.get(held, ()),
                     *(note for at, notes in self._notes.items()
                       if at.startswith(prefix) for note in notes if note.at == held)]
        return entries_of(found)

    def act(self, pin: str) -> tuple[Note, ...]:
        """Every note one act left, wherever in the tree its parts stand: the notes
        that name the pin creation ``pin``, by their path and their line — how many
        parts the act had, and which (ADR-0145 decision 5)."""
        if not pin:
            return ()
        with self._lock:
            found = [note for notes in self._notes.values() for note in notes
                     if note.pin == pin]
        return tuple(sorted(found, key=lambda note: (note.path, note.created_at)))

    def beneath(self, path: str) -> tuple[Note, ...]:
        """The notes at ``path`` and at every path beneath it, newest first — what
        the page of a path no node stands at lists (ADR-0140)."""
        held = join_path(path)
        prefix = held.rstrip("/") + "/"
        with self._lock:
            found = [note for at, notes in self._notes.items()
                     if at == held or at.startswith(prefix) for note in notes]
        return tuple(sorted(found, key=_age, reverse=True))

    def find(self, path: str, key: str) -> Note | None:
        """The note on ``path`` whose creation ``key`` spells, or ``None``."""
        with self._lock:
            return next((note for note in self._notes.get(join_path(path), ())
                         if note.key == key), None)

    def tables(self) -> dict[str, list[Note]]:
        """A copy of the history, by path — what the file is written from."""
        with self._lock:
            return {path: list(notes) for path, notes in self._notes.items()}

    def editable(self, note: Note) -> bool:
        """Whether ``note`` may be edited on its own, here: a note of its own while
        it is the newest on its node (ADR-0047 decision 5). A pin's note is edited
        with its pin while the pin stands, and is frozen once it ends."""
        if note.pin:
            return False
        with self._lock:
            held = self._notes.get(note.path, [])
            return bool(held) and held[-1].key == note.key

    # --- writing ---

    def add(self, path: str, slug: str, text: str, *, by: str,
            context: Context, now: datetime | None = None) -> Note:
        """Append a note of its own — on the node at ``path``, or on its line
        ``slug`` — written by ``by`` now."""
        moment = now or instants.now()
        with self._lock:
            note = Note(path=join_path(path), slug=slug, text=text,
                        created_at=self._unique(join_path(path), moment),
                        created_by=by, set_at=moment, set_by=by, context=context)
            self._notes.setdefault(note.path, []).append(note)
            self._write()
        return note

    def edit(self, path: str, key: str, text: str, *, by: str, expected: str,
             now: datetime | None = None) -> NoteWrite:
        """Edit a note of its own — the newest on its node — when ``expected`` is
        the token of the note as it stands: a **compare-and-set**, so that two
        admins' edits never overwrite each other unseen. Saying what it says
        already changes nothing."""
        moment = now or instants.now()
        held = join_path(path)
        with self._lock:
            notes = self._notes.get(held, [])
            index = next((index for index, note in enumerate(notes)
                          if note.key == key), None)
            if index is None:
                return NoteWrite(False, None, refused=True)
            stored = notes[index]
            if (stored.pin or index != len(notes) - 1
                    or stored.token != expected):
                return NoteWrite(False, stored, refused=True)
            if stored.text == text:
                return NoteWrite(False, stored)
            notes[index] = replace(stored, text=text, set_at=moment, set_by=by)
            self._write()
            return NoteWrite(True, notes[index])

    def pinned(self, path: str, slug: str, entry: Pin, context: Context, *,
               at: str = "") -> Note:
        """A pin set or edited on the node at ``path``, or on its line ``slug``:
        its note enters the history when it is set (ADR-0047 decision 4), whatever
        its kind and with words or without — a pin set without words a record with no
        text (ADR-0145 decision 4) — and follows an edit while the pin stands, the
        note naming its pin by the pin's creation (decision 5) and keeping its kind, a
        seen's status and a silence's level — and a maintenance entry's what it was
        planned as, and its windows counted from the first (ADR-0150): the set's own,
        where one opened as it was set, told before the note entered. ``at`` is the
        node the act was made on, kept where that is not ``path`` (ADR-0145 decision
        5). The answer is the note as the history holds it."""
        owner = instants.stamp(entry.created_at)
        held = join_path(path)
        made = join_path(at) if at else ""
        words = _words(entry)
        with self._lock:
            notes = self._notes.setdefault(held, [])
            index = next((index for index, note in enumerate(notes)
                          if note.pin == owner and note.slug == slug), None)
            if index is not None:
                stored = notes[index]
                planned = (planned_of(entry, stored.planned)
                           if stored.tally is not None else stored.planned)
                if (stored.text, stored.kind, stored.status, stored.level,
                        stored.planned) == (words, entry.kind, entry.status,
                                            entry.level, planned):
                    return stored
                notes[index] = replace(stored, text=words, set_at=entry.set_at,
                                       set_by=entry.set_by, kind=entry.kind,
                                       status=entry.status, level=entry.level,
                                       planned=planned)
                self._write()
                return notes[index]
            heard = self._unheard.pop((held, slug, owner), Tally())
            note = Note(path=held, slug=slug, text=words,
                        created_at=self._unique(held, entry.set_at),
                        created_by=entry.set_by, set_at=entry.set_at,
                        set_by=entry.set_by, pin=owner, context=context,
                        kind=entry.kind, status=entry.status, level=entry.level,
                        at=made if made != held else "", planned=planned_of(entry),
                        tally=heard if entry.kind == MAINTENANCE else None)
            notes.append(note)
            self._write()
            return note

    def pin_ended(self, path: str, slug: str, entry: Pin, why: str, by: str,
                  when: datetime) -> Note | None:
        """The pin ``entry`` on the node at ``path``, or on its line ``slug``, ended
        ``when``, for ``why`` — the log's word — and by ``by`` where a person ended
        it: its note records the end (ADR-0145 decision 4), and the pin's kind where
        the note was written before a note kept it — and a window of a maintenance
        entry open as it ended closes with it, or at its own end where that came first
        (ADR-0150). The one write a pin's note takes once its pin has ended (ADR-0047
        decision 5). A pin that left no note — one set without words before notes
        recorded every pin — has none to record it in, and the answer is ``None``."""
        owner = instants.stamp(entry.created_at)
        held = join_path(path)
        moment = instants.utc(when, "a pin's end")
        with self._lock:
            self._unheard.pop((held, slug, owner), None)
            notes = self._notes.get(held, [])
            index = next((index for index, note in enumerate(notes)
                          if note.pin == owner and note.slug == slug), None)
            if index is None:
                return None
            stored = notes[index]
            notes[index] = replace(
                stored, kind=stored.kind or entry.kind,
                status=stored.status if stored.kind else entry.status,
                level=stored.level if stored.kind else entry.level,
                ended_at=moment, ended=why, ended_by=by,
                tally=(stored.tally.closed(moment, why, by)
                       if stored.tally is not None else None))
            self._write()
            return notes[index]

    def window_seen(self, seen: WindowSeen) -> Note | None:
        """What the tree saw of a maintenance entry's windows (ADR-0150): its note
        counts the window that holds — from ``seen.start`` until ``seen.until`` — once,
        and closes the one it held open where that is another or none holds, at
        ``seen.when``, for ``seen.why``, by ``seen.by``. What is told before the note
        enters — the set's own window, in the write that sets it — is kept for the note
        to take as it enters (:meth:`pinned`). A note written before notes counted
        windows counts none. The answer is the note as the history holds it, and
        ``None`` where it holds none yet or one that counts nothing."""
        owner = instants.stamp(seen.pin.created_at)
        held = join_path(seen.path)
        with self._lock:
            notes = self._notes.get(held, [])
            index = next((index for index, note in enumerate(notes)
                          if note.pin == owner and note.slug == seen.slug), None)
            if index is None:
                key = (held, seen.slug, owner)
                self._unheard[key] = _heard(self._unheard.get(key, Tally()), seen)
                return None
            stored = notes[index]
            if stored.tally is None:
                return None
            tally = _heard(stored.tally, seen)
            if tally != stored.tally:
                notes[index] = replace(stored, tally=tally)
                self._write()
            return notes[index]

    def retire(self, retention: Retention, *, now: datetime,
               zone: ZoneInfo) -> int:
        """Retire what ``retention`` says is past keeping, on every node, and say how
        many notes went (ADR-0047 decision 9): past the age ceiling by age alone, then
        past the floor while the node holds more than the cap, the oldest first —
        never one of the last ``keep`` on its node. What is counted, kept and retired
        is an **entry** (ADR-0145 decision 5): an act's notes on a node go together,
        by its first note's age."""
        oldest = retention.max_age.cutoff(now, zone)
        floor = retention.min_age.cutoff(now, zone)
        retired = 0
        with self._lock:
            for path in list(self._notes):
                notes = self._notes[path]
                held = sorted(entries_of(notes), key=lambda entry: entry.created_at)
                kept_from = max(0, len(held) - retention.keep)
                gone = {index for index in range(kept_from)
                        if held[index].created_at < oldest}
                standing = len(held) - len(gone)
                for index in range(kept_from):
                    if standing <= retention.cap:
                        break
                    if index not in gone and held[index].created_at < floor:
                        gone.add(index)
                        standing -= 1
                if gone:
                    going = {note.key for index in gone for note in held[index].notes}
                    retired += len(going)
                    left = [note for note in notes if note.key not in going]
                    if left:
                        self._notes[path] = left
                    else:
                        del self._notes[path]
            if retired:
                self._write()
        return retired

    def _unique(self, path: str, moment: datetime) -> datetime:
        """``moment``, or a microsecond after it for each note on ``path`` created
        at it already: a note's creation is its address among its node's."""
        taken = {note.created_at for note in self._notes.get(path, ())}
        while moment in taken:
            moment += timedelta(microseconds=1)
        return moment

    def _write(self) -> None:
        """Write the history through, under the lock, so that writes reach the file
        in the order they were made."""
        if self._store is not None:
            self._store.save(self._notes)


def _age(note: Note) -> datetime:
    return note.created_at


def _heard(tally: Tally, seen: WindowSeen) -> Tally:
    """``tally`` once it has heard ``seen`` (:meth:`NoteBook.window_seen`): the window
    open in it closed where it is not the one that holds, and the one that holds
    open."""
    if seen.start is None or tally.open_since != seen.start:
        tally = tally.closed(seen.when, seen.why, seen.by)
    if seen.start is not None:
        tally = tally.holding(seen.start, seen.until or seen.start)
    return tally


#: The process's notes, as :data:`~little_sister.tree.status_tree` is its tree: one
#: book, which the start fills from the file and writes through from then on.
notes_book = NoteBook()


def forget_notes() -> None:
    """Empty the process's book and let go of its store (tests)."""
    notes_book.forget()


class NoteStore:
    """The notes as a state file, written through: ``var/state/notes.json`` holds
    ``{"notes": {path: [note, …]}}``, each path's notes oldest first. Reading and
    writing — atomic, and never a refusal to start — are the state layer's
    (ADR-0071); a file it cannot read starts the history empty and stands as a line
    on the heartbeat, and a failed write leaves the book authoritative for the
    session."""

    def __init__(self, state: StateLayer, *, book: NoteBook | None = None) -> None:
        self._state = state
        self._book = book
        # The other direction (ADR-0077): an adopted copy — the store's at a
        # takeover, the backup's on the way back — replaces the history.
        if book is not None:
            state.restore_with(NOTES_FILE, self._adopt)

    def _adopt(self, payload: object) -> None:
        assert self._book is not None
        self._book.restore(self.tables(payload))

    def load(self) -> dict[str, list[Note]]:
        """The history as the start finds it: empty without a file, and empty for a
        file it cannot take — a shape it does not know, a time that is no instant —
        which is a load failure the layer reports."""
        data = self._state.read(NOTES_FILE)
        if data is None:
            return {}
        try:
            return self.tables(data)
        except ValueError as error:
            self._state.report_load_failure(NOTES_FILE, str(error))
            return {}

    @staticmethod
    def tables(payload: object) -> dict[str, list[Note]]:
        """The history out of a payload in the file's shape, or :class:`ValueError`
        naming what is wrong with it."""
        if not isinstance(payload, Mapping):
            raise ValueError("not a mapping")
        by_path = payload.get("notes", {})
        if not isinstance(by_path, Mapping):
            raise ValueError("its 'notes' is no mapping of paths")
        notes: dict[str, list[Note]] = {}
        for path, raws in by_path.items():
            if not isinstance(raws, list):
                raise ValueError(f"the notes of {path} are no list")
            notes[join_path(str(path))] = [
                Note.from_dict(join_path(str(path)), raw)
                for raw in raws if isinstance(raw, Mapping)]
        return notes

    def save(self, notes: Mapping[str, Sequence[Note]]) -> None:
        """Rewrite the whole history, atomically, through the layer."""
        self._state.write(NOTES_FILE, {"notes": {
            path: [note.to_dict() for note in held]
            for path, held in sorted(notes.items())}})
