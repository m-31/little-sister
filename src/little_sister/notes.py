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
"""
from __future__ import annotations

import calendar
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from little_sister import instants, values
from little_sister.pins import NO_NOTE
from little_sister.state import NOTES_FILE, StateLayer
from little_sister.status import join_path

if TYPE_CHECKING:
    from little_sister.pins import Pin
    from little_sister.tree import StatusSnapshot

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


@dataclass(frozen=True)
class Note:
    """One note on the node at ``path``, or on its line ``slug``: its Markdown, who
    wrote it first and when, who changed it last and when — the two dates of a pin
    (ADR-0014) — the pin it is the note of, by that pin's creation, empty for a note
    of its own, and the context it was written in.

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

    @property
    def key(self) -> str:
        return instants.stamp(self.created_at)

    @property
    def token(self) -> str:
        return instants.stamp(self.set_at)

    def to_dict(self) -> dict[str, Any]:
        """The note as its file carries it, under its path: each time in UTC."""
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
        return said

    @classmethod
    def from_dict(cls, path: str, data: Mapping[str, Any]) -> Note:
        """Read one note, its times strictly — :class:`ValueError` for one that is no
        instant with an offset, which the store reports for the file."""
        created = instants.instant(data.get("created_at"), "a note's created_at")
        changed = data.get("set_at")
        return cls(
            path=path, slug=values.text(data, "slug"),
            text=values.text(data, "text"),
            created_at=created, created_by=values.text(data, "created_by"),
            set_at=(created if changed is None
                    else instants.instant(changed, "a note's set_at")),
            set_by=values.text(data, "set_by"), pin=values.text(data, "pin"),
            context=Context.from_dict(data.get("context")))


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

    def use_store(self, store: NoteStore) -> None:
        """Write every change through ``store`` from now on."""
        with self._lock:
            self._store = store

    def forget(self) -> None:
        """Hold no note and write through no store (tests)."""
        with self._lock:
            self._notes = {}
            self._store = None

    def restore(self, notes: Mapping[str, Sequence[Note]]) -> None:
        """Take ``notes`` as the history — the start's read, or an adopted copy at
        a takeover (ADR-0077) — in place of what the book held."""
        with self._lock:
            self._notes = {join_path(path): sorted(held, key=_age)
                           for path, held in notes.items() if held}

    # --- reading ---

    def of(self, path: str) -> tuple[Note, ...]:
        """The notes on the node at ``path`` and on its lines, newest first."""
        with self._lock:
            return tuple(reversed(self._notes.get(join_path(path), ())))

    def count(self, path: str) -> int:
        with self._lock:
            return len(self._notes.get(join_path(path), ()))

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

    def pinned(self, path: str, slug: str, entry: Pin,
               context: Context) -> Note | None:
        """A pin set or edited on the node at ``path``, or on its line ``slug``:
        its note enters the history when it is set (ADR-0047 decision 4) and
        follows an edit while the pin stands, the note naming its pin by the pin's
        creation (decision 5). A pin without a note writes none; the answer is the
        note as the history holds it, or ``None``."""
        if not entry.note or entry.note == NO_NOTE:
            return None
        owner = instants.stamp(entry.created_at)
        held = join_path(path)
        with self._lock:
            notes = self._notes.setdefault(held, [])
            index = next((index for index, note in enumerate(notes)
                          if note.pin == owner and note.slug == slug), None)
            if index is not None:
                stored = notes[index]
                if stored.text == entry.note:
                    return stored
                notes[index] = replace(stored, text=entry.note,
                                       set_at=entry.set_at, set_by=entry.set_by)
                self._write()
                return notes[index]
            note = Note(path=held, slug=slug, text=entry.note,
                        created_at=self._unique(held, entry.set_at),
                        created_by=entry.set_by, set_at=entry.set_at,
                        set_by=entry.set_by, pin=owner, context=context)
            notes.append(note)
            self._write()
            return note

    def retire(self, retention: Retention, *, now: datetime,
               zone: ZoneInfo) -> int:
        """Retire what ``retention`` says is past keeping, on every node, and say how
        many went (ADR-0047 decision 9): past the age ceiling by age alone, then past
        the floor while the node holds more than the cap, the oldest first — never
        one of the last ``keep`` on its node."""
        oldest = retention.max_age.cutoff(now, zone)
        floor = retention.min_age.cutoff(now, zone)
        retired = 0
        with self._lock:
            for path in list(self._notes):
                notes = self._notes[path]
                kept_from = max(0, len(notes) - retention.keep)
                gone = {index for index in range(kept_from)
                        if notes[index].created_at < oldest}
                standing = len(notes) - len(gone)
                for index in range(kept_from):
                    if standing <= retention.cap:
                        break
                    if index not in gone and notes[index].created_at < floor:
                        gone.add(index)
                        standing -= 1
                if gone:
                    retired += len(gone)
                    left = [note for index, note in enumerate(notes)
                            if index not in gone]
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
