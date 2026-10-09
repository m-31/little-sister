"""Logging setup — a **default**, never a seizure.

little-sister logs through the standard hierarchy and nothing else: its records
propagate to the **root** logger, so whoever configures that owns where they go.
This module configures root itself only when the application has **not** — no
handlers on it by the time we import — which is the ordinary case for
``./start.sh`` and gives the console (a ``StreamHandler``, so **stderr**) plus,
once the server's start calls :func:`open_log_file`, ``var/little-sister.log``
(``LOG_FILE`` overrides the path).

**An import opens no log file** (ADR-0091): importing the application is not an
instance, and a file in the working directory is the instance's. What the import
logs goes to stderr and into a bounded buffer — the first :data:`START_BUFFER`
records — which :func:`open_log_file` writes into the file before anything else, so
a run's log still begins with its configuration; past the bound it writes one line
counting what went to stderr only. A plain import leaves its lines on stderr.

A deployment or a plugin that wants its own logging therefore just sets it up
**before** importing ``little_sister.app``, in the same import-before-app block it
registers check types in: its handlers stay, its level stays, and little-sister's
own records arrive there too. That is the promise (architecture.md §11,
ADR-0049) — not this module's name. A plugin never imports ``logger`` from here;
it calls ``logging.getLogger(__name__)`` like any Python library, and the records
land wherever the application decided.

The level and everything ``LOG_LEVEL`` asks for sit **inside** the guard for the
same reason: a `setLevel` outside it would override the level an application had
already chosen, which is the one thing a library must not do to logging. So
``LOG_LEVEL`` speaks for *this* default and for nothing else — set it against an
application that configured its own logging and it does nothing, because the
levels are then that application's to choose. :data:`in_charge` says which of the
two holds, and the noise caps a package declares (:mod:`little_sister.noise`,
ADR-0121) ask it before a level is set for them: they are no longer set here.

The default is **INFO**, and what makes it the right one is that no module here
calls ``logger.debug``: little-sister's own records start at INFO, so a DEBUG
root adds none of our lines and every dependency's. One deployment's log ran two
thirds ``botocore`` request detail nobody had asked for. ``LOG_LEVEL=DEBUG`` asks
for that on purpose — which is also when the declared caps earn their place, since
they are what keeps a deliberate DEBUG session readable: a bare ``DEBUG`` lowers
the root and lifts no cap.

**``LOG_LEVEL`` is a list, and names loggers beside the level** (ADR-0121 decision
5): ``INFO,botocore.credentials=DEBUG``. The entry without an ``=`` is the level
of this default's root, which is all the variable was. An entry ``name=LEVEL``
speaks for that logger and for every name beneath it, down to the next name the
variable has an entry for: a level that stands there is taken off, whoever set it,
so that the nearest entry at or above a logger's name is that logger's level. The
named entries are said twice (:meth:`Entries.say`) — here, with the default, and
again where the application is imported and the caps are set, after the
deployment's own code has run; between the two a later `setLevel` stands, as it
does anywhere. An entry that cannot be read is skipped and said in the log, a line
for each, and the rest of the variable stands.

**Both of the default's variables are read after ``.env``** (ADR-0121 decision 6).
This module imports :mod:`little_sister.secrets`, whose import reads the file into
the environment (ADR-0003), before it reads ``LOG_LEVEL`` and ``LOG_FILE`` — so
the order in which a process imports the library decides nothing. A value in the
process's own environment stands over the file's, as for every variable.

**The default's lines are stamped in the configured timezone, with its offset**
(ADR-0120 decision 9) — ``2026-10-04 13:02:35,893 +0200`` — so that a line of the
log and a time on a page are the same clock, and the offset says which. The
configuration hands the zone over the moment it has read it (:func:`stamp_in`); a
line written before that carries the machine's own clock, with its offset as well.
The stamp is taken where a line is written, so what the import logged stands in the
log file in the configured zone from its first line. And where the machine's clock
does not show that zone's time, now or within the year ahead, the start says so
once, in the log: gunicorn's own lines are stamped on the machine's clock.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo

# Before either variable below is read (ADR-0121 decision 6): importing the module
# that owns `.env` is what reads the file into the environment (ADR-0003), so a
# `LOG_LEVEL` or a `LOG_FILE` written there counts whatever a process imports
# first — a check package, the application, or this module itself. Nothing of that
# module is used here, and it must go on importing nothing that reaches this one:
# a cycle between the two would be an import error at every start.
import little_sister.secrets  # noqa: F401
from little_sister import instants

_LOG_FILE = os.environ.get("LOG_FILE", "var/little-sister.log")
#: The level of the default's root where ``LOG_LEVEL`` names none that can be read.
DEFAULT_LEVEL = logging.INFO
_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

#: The zone the default's lines are stamped in, once the configuration has read
#: one and handed it over (:func:`stamp_in`); the machine's own clock until then.
_zone: tzinfo | None = None

#: How far ahead the start looks for the hour from which the machine's clock and
#: the zone the log is stamped in show different times: a year, and a day of slack.
_HOURS_AHEAD = 366 * 24


class _Stamped(logging.Formatter):
    """The default's lines: the stamp in the zone the log is stamped in, with the
    offset in force at it — ``2026-10-04 13:02:35,893 +0200`` (ADR-0120 decision
    9). The zone is read when a line is written, not when it was logged, which is
    what puts the lines of the import into the log file in the configured zone."""

    def formatTime(self, record: logging.LogRecord,
                   datefmt: str | None = None) -> str:
        moment = datetime.fromtimestamp(record.created, UTC).astimezone(_zone)
        return f"{moment:%Y-%m-%d %H:%M:%S},{int(record.msecs):03d} {moment:%z}"


_formatter = _Stamped(_FORMAT)

#: How many records an import may log before the start writes them into the log
#: file it opens (ADR-0091 decision 4); the rest reach stderr only, and are counted.
START_BUFFER = 1000


class _StartBuffer(logging.Handler):
    """What the import logs, kept for the log file the server's start opens."""

    def __init__(self, capacity: int) -> None:
        super().__init__()
        self.capacity = capacity
        self.records: list[logging.LogRecord] = []
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        if len(self.records) < self.capacity:
            self.records.append(record)
        else:
            self.dropped += 1


#: The buffer, while the default is in charge and no file is open yet.
_buffer: _StartBuffer | None = None
#: The log file's handler, once the start has opened it.
_file_handler: logging.FileHandler | None = None

#: What the root logger is called where a name is asked for: ``logging.getLogger``
#: answers the root for it, so no other logger can carry it.
ROOT = "root"


def above(name: str) -> list[str]:
    """The logger names above ``name``, nearest first and the root left out —
    ``["botocore"]`` for ``botocore.credentials``. A name that only begins alike is
    not above: ``botocore`` is nothing to ``botocorex.y``."""
    parts = name.split(".")
    return [".".join(parts[:count]) for count in range(len(parts) - 1, 0, -1)]


def level_on(name: str) -> int:
    """The level that stands on the logger ``name`` — ``NOTSET`` where none does,
    and where there is no such logger. Read from the registry, so that asking
    makes no logger."""
    standing = logging.Logger.manager.loggerDict.get(name)
    return standing.level if isinstance(standing, logging.Logger) else logging.NOTSET


def level_name(level: int) -> str:
    """``level`` as `logging` names it — ``WARNING`` for 30."""
    return str(logging.getLevelName(level))


def _level_named(word: str) -> int | None:
    """The level ``word`` names in ``logging``, in either case, or ``None``.
    ``NOTSET`` names none: it is what a logger without a level carries."""
    return logging.getLevelNamesMapping().get(word.upper()) or None


def _no_level(word: str) -> str:
    """Why ``word`` is no level, as the log and the page say it."""
    if not word:
        return "it names no level"
    if word.upper() == "NOTSET":
        return "NOTSET names no level"
    return f"{word!r} is not a level name"


@dataclass(frozen=True)
class Unreadable:
    """An entry of ``LOG_LEVEL`` that could not be read: as it was written, and why."""
    entry: str
    why: str


@dataclass(frozen=True)
class TakenOff:
    """A level that stood on a logger beneath a named entry, and was taken off."""
    logger: str
    level: int
    #: The name of the entry that speaks for the logger.
    entry: str

    @property
    def level_name(self) -> str:
        return level_name(self.level)


@dataclass
class Entries:
    """What ``LOG_LEVEL`` says, entry by entry (ADR-0121 decision 5).

    ``bare`` is the level of the default's root — the entry with no ``=`` — or
    ``None`` where the variable names none that can be read; ``named`` is the level
    of each logger an entry ``name=LEVEL`` names, a logger's name taken as it is
    written; ``unreadable`` is every entry that was skipped, in the order written.
    ``taken_off`` is what :meth:`say` did beyond setting the named levels.
    """
    bare: int | None = None
    named: dict[str, int] = field(default_factory=dict)
    unreadable: list[Unreadable] = field(default_factory=list)
    taken_off: list[TakenOff] = field(default_factory=list)

    @classmethod
    def read(cls, value: str) -> Entries:
        """The variable's value taken apart at its commas. Spaces around an entry
        and around its ``=`` are dropped, an empty entry is nothing, what follows
        the first ``=`` is the level, and a later entry for a name replaces an
        earlier one — the bare level too. An entry that cannot be read is kept
        with the reason, and reading goes on."""
        said = cls()
        for raw in value.split(","):
            entry = raw.strip()
            if not entry:
                continue
            if "=" not in entry:
                level = _level_named(entry)
                if level is None:
                    said.unreadable.append(Unreadable(entry, _no_level(entry)))
                else:
                    said.bare = level
                continue
            name, _, word = entry.partition("=")
            name, word = name.strip(), word.strip()
            level = _level_named(word)
            if not name:
                why = "it names no logger"
            elif name == ROOT:
                why = ("the root has no name in the variable: its level is the "
                       "entry without a name")
            elif level is None:
                why = _no_level(word)
            else:
                said.named[name] = level
                continue
            said.unreadable.append(Unreadable(entry, why))
        return said

    def speaks_for(self, name: str) -> str | None:
        """The entry that speaks for the logger ``name``: its own, or the nearest
        above it — and ``None`` where the variable says nothing of it."""
        return next((at for at in (name, *above(name)) if at in self.named), None)

    def written(self) -> str:
        """What was read, as the variable takes it: the bare level — the default's
        where the variable names none — and after it every named entry, in the
        order it was first written. An entry that could not be read is not in it,
        since it set nothing: reading the answer again says what this says, and
        ``/system/installed`` prints it in front of the entry it suggests, so that
        pasting the line changes one thing (ADR-0121 decision 7)."""
        bare = DEFAULT_LEVEL if self.bare is None else self.bare
        return ",".join([level_name(bare),
                         *(f"{name}={level_name(level)}"
                           for name, level in self.named.items())])

    def say(self) -> None:
        """Set every named entry on its logger, with its reach: a level that
        stands on a logger beneath an entry, where the variable has no entry for
        that logger itself, is taken off — whoever set it — and noted in
        ``taken_off``. The nearest entry at or above a logger's name is then that
        logger's level, which is what an operator who wrote ``botocore=DEBUG``
        for a login that fails asked for.

        Called twice where the default is in charge: with the default, below, and
        again where the caps are set (:func:`little_sister.noise.settle`), after
        the code of the import-before-app slot. The bare level is not this
        method's: it is set once, with the default."""
        for name, level in self.named.items():
            logging.getLogger(name).setLevel(level)
        for name, standing in list(logging.Logger.manager.loggerDict.items()):
            if not isinstance(standing, logging.Logger):
                continue
            if standing.level == logging.NOTSET or name in self.named:
                continue
            entry = self.speaks_for(name)
            if entry is not None:
                self.taken_off.append(TakenOff(name, standing.level, entry))
                standing.setLevel(logging.NOTSET)


root_logger = logging.getLogger()
logger = logging.getLogger(__name__)

#: What ``LOG_LEVEL`` says. Read before the guard because it is only *read* here:
#: nothing of it is said until the guard is taken, and against an application
#: that configured logging itself none of it ever is.
entries = Entries.read(os.environ.get("LOG_LEVEL", ""))

#: Whether this default is in charge of the process's log: no handler stood on the
#: root where this module was imported, so the handlers and the levels below are
#: ours. ``False`` is ADR-0049 decision 4's guard holding — the application
#: configured logging itself, and no level is the library's to set, here or where
#: the noise caps are set (ADR-0121 decision 4). It is also the guard against
#: duplicate handlers where this module is imported more than once.
in_charge = not root_logger.handlers


def _set_levels(said: Entries) -> None:
    """The levels of the default, set where it is installed (ADR-0121 decision 5):
    the root's — the bare level, or ``INFO`` where the variable names none that can
    be read — once, and the named entries for the first time, so that what the
    variable names holds from the first line, a door that reaches its store while
    it registers included."""
    root_logger.setLevel(said.bare if said.bare is not None else DEFAULT_LEVEL)
    said.say()


if in_charge:
    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_formatter)
    root_logger.addHandler(_stream_handler)

    # No file yet, and not even its directory: that is the start's (ADR-0091).
    _buffer = _StartBuffer(START_BUFFER)
    root_logger.addHandler(_buffer)

    for _skipped in entries.unreadable:
        # Log only, and on purpose: this runs while the logger is being built,
        # beneath every module that could record a self-report line — and a note
        # about the variable belongs where it was read, which is here. A typo in
        # an environment is no reason to refuse to log: the entry is skipped, the
        # rest of the variable stands, and `/system/installed` lists it.
        #
        # Said **before** the variable's levels are set, while the root is where
        # the process left it — at WARNING, as `logging` starts it — so that no
        # entry can take out the line about another: `LOG_LEVEL=ERROR,dep=DEBG`
        # still says which entry it could not read.
        logger.warning(
            "logger: LOG_LEVEL entry %r is skipped: %s%s", _skipped.entry,
            _skipped.why,
            "" if "=" in _skipped.entry else "; the root is at " + level_name(
                entries.bare if entries.bare is not None else DEFAULT_LEVEL))

    # No noise cap is set here any more (ADR-0121 decision 1): a cap is a row a
    # package declares, the library's own among them, and `little_sister.noise`
    # sets the rows once, where the application is imported.
    _set_levels(entries)


def stamp_in(zone: tzinfo) -> None:
    """The configuration's call, the moment it has read the time zone (ADR-0120
    decision 9): the default's lines are stamped in ``zone`` from here on, each
    with its offset. Where the application configured logging itself the stamp is
    that application's, and nothing it can see changes."""
    global _zone
    _zone = zone


def _say_where_the_clocks_part(zone: tzinfo) -> None:
    """Said once, by the start, in the log it has just opened (ADR-0120 decision
    9): that the machine's clock does not show the time this log is stamped in —
    now, or from a day within the year ahead. A process cannot ask its machine for
    the name of its zone, so the two are compared by what they show, hour by hour.
    Log only: a note on ``/little-sister`` would stand for the life of the process
    on a machine whose zone is another on purpose."""
    start = instants.now()
    for hour in range(_HOURS_AHEAD + 1):
        moment = start + timedelta(hours=hour)
        stamped, machine = moment.astimezone(zone), moment.astimezone()
        if stamped.utcoffset() == machine.utcoffset():
            continue
        if hour == 0:
            logger.warning(
                "logger: this log is stamped in %s, the configured timezone, at %s "
                "now; the machine's clock is at %s, so a line stamped on it, as "
                "gunicorn's own are, shows another time for the same moment",
                zone, f"{stamped:%z}", f"{machine:%z}")
        else:
            logger.warning(
                "logger: this log is stamped in %s, the configured timezone, which "
                "shows the machine's time now and not from %s on, at %s against the "
                "machine's %s; a line stamped on the machine's clock, as gunicorn's "
                "own are, shows another time from then on",
                zone, f"{stamped:%Y-%m-%d}", f"{stamped:%z}", f"{machine:%z}")
        return


def open_log_file() -> None:
    """The server's start (ADR-0091 decision 4): open the log file — ``LOG_FILE``, or
    ``var/little-sister.log`` of the working directory — and write into it first what
    the import logged, so that a run's log begins with its configuration. Every
    line of it is stamped as it is written here: in the configured zone, where the
    configuration handed one over, and the start then says once where the
    machine's clock is another (ADR-0120 decision 9).

    Where the application configured logging itself this does nothing: the file is
    the default's, and the default did not run. A second call does nothing either.
    """
    global _buffer, _file_handler
    buffer = _buffer
    if buffer is None or _file_handler is not None:
        return
    directory = os.path.dirname(_LOG_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handler = logging.FileHandler(_LOG_FILE)
    handler.setFormatter(_formatter)
    for record in buffer.records:
        handler.handle(record)
    root_logger.removeHandler(buffer)
    root_logger.addHandler(handler)
    _file_handler, _buffer = handler, None
    if buffer.dropped:
        logger.info("logger: %d more lines were logged before the start opened this "
                    "file, and went to stderr only", buffer.dropped)
    if _zone is not None:
        _say_where_the_clocks_part(_zone)
