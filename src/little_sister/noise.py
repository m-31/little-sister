"""Noise caps: a package declares what its dependencies write (ADR-0121).

What a dependency logs is known to the package that brings it. A package that reads
AWS builds a session at every run, and the SDK says each time, at ``INFO`` under
``botocore.credentials``, where it found the credentials: one sentence, a line a
run, in the log of every deployment that installs the package. The library cannot
cap that logger, since it does not depend on the SDK. The package cannot set the
level itself either: a `setLevel` where a package is imported is a level for
somebody else's log, set whether or not the application configured logging, and
whether it holds would be decided by the order of the deployment's imports.

So a package **declares**, in the import-before-app slot beside its other
registrations, and sets no level::

    import logging

    from little_sister import noise

    noise.cap("botocore.credentials", logging.WARNING,
              hides="where each new session found its credentials, a line a run")

The call records a **row** — the logger's name, the level it is capped at, the
package, which is inferred from the call site as a resolver's is (ADR-0064), and
what the cap hides — and touches no logger. The library declares its own the same
way, and that is one row: ``markdown_it`` at ``INFO``.

**What a package may declare is bounded** (decision 3). A dependency's logger:
never the root, and never ``little_sister`` or a logger beneath it, whose lines
are what the log is for. ``INFO`` or ``WARNING``, by `logging`'s constant: a
package may take a dependency's ``DEBUG`` and ``INFO`` lines out of a log, and a
warning or an error is taken out by the deployment alone, with ``LOG_LEVEL``. With
what it hides. And in the slot: what arrives after the application was imported is
refused, unless it repeats a row as it stands. A declaration outside these is a
warning and a skip, as on the neighboring seams, and a line on the instance's
startup node — a mistake in a default never costs a deployment its monitoring.

**The library sets the rows once, where the application is imported**
(:func:`settle`, decision 4): every package has registered by then, and the code of
the slot has set the levels it sets. A row is set on its logger unless one of four
things holds, asked in this order, and the first that holds is the reason
``/system/installed`` gives — the application configured logging itself;
``LOG_LEVEL`` names the logger or one above it; a level stands on the logger, or on
one above it short of the root, that no row set; or the row would take no line
away. So nothing is set where a row is declared and the order of a deployment's
imports decides nothing; a cap takes lines away and adds none; and what the
deployment said, in its code or in the variable, stands over every row.

Two packages may bring one dependency, and every cap holds: where two rows reach
one logger, on its own name or one of them on a name above it, the higher level
stands there, whichever was declared first. What code sets after the application
was imported, it sets, and no row follows it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from little_sister import logger as default
from little_sister import self_report
from little_sister.logger import (
    ROOT,
    Entries,
    TakenOff,
    Unreadable,
    above,
    level_name,
    level_on,
    logger,
)
from little_sister.origins import calling_package
from little_sister.reasons import plain, slug
from little_sister.secrets import UNIDENTIFIED

#: The levels a package may cap a dependency's logger at (decision 3), by
#: `logging`'s constant: at ``INFO`` its ``DEBUG`` lines go, at ``WARNING`` its
#: ``INFO`` lines with them. Nothing above: a warning or an error is taken out by
#: the deployment alone, by name in ``LOG_LEVEL``.
LEVELS = (logging.INFO, logging.WARNING)

#: The library's own logger. No row names it or a logger beneath it — its lines
#: are what the log is for — and it is the package of the library's own rows.
OWN = "little_sister"


def _named_at_or_below(level: int) -> int:
    """The highest level `logging` has a name for at or below ``level`` — an entry
    of ``LOG_LEVEL`` is written by name — and ``DEBUG`` where there is none, which
    is a root at ``NOTSET``: every line passes it."""
    named = [value for value in logging.getLevelNamesMapping().values()
             if logging.NOTSET < value <= level]
    return max(named, default=logging.DEBUG)


@dataclass(frozen=True)
class Row:
    """One declared cap (decision 1): a logger's name, the level it is capped at,
    the package that declared it, and what the cap hides."""
    logger: str
    level: int
    #: The package that declared it, inferred from the call site — ``""`` where
    #: the caller could not be identified.
    package: str
    #: What the cap hides, in words that finish the sentence *it hides …*.
    hides: str

    @property
    def owner(self) -> str:
        """The declaring package as a page or a message should say it."""
        return self.package or UNIDENTIFIED

    @property
    def level_name(self) -> str:
        return level_name(self.level)


@dataclass(frozen=True)
class Verdict:
    """What became of the rows that name one logger, where the rows were set."""
    logger: str
    #: The level the rows ask for: the highest any package declared for the logger.
    level: int
    #: Every package's row for the logger, by package.
    rows: tuple[Row, ...]
    #: Why no level was set — the first of decision 4's four reasons that held —
    #: or ``""`` where the logger was set to ``level``.
    reason: str = ""
    #: The level the logger is at without the rows, where they were set: what
    #: stands on the nearest logger above it that carries a level, or on the root.
    #: It lies below ``level`` then, and the lines between the two are what the
    #: cap hides.
    without: int = logging.NOTSET

    @property
    def capped(self) -> bool:
        """Whether the rows were set on the logger."""
        return not self.reason

    @property
    def shown_by(self) -> str:
        """The entry of ``LOG_LEVEL`` that shows the lines a cap hides (decision
        7): the logger at the level it is at without the cap, so that what the cap
        hid comes back and nothing below it — ``DEBUG`` would be more than was
        hidden, and on a wide logger a wire trace. An entry is written by name, so
        a level `logging` has no name for is the nearest named one beneath it."""
        return f"{self.logger}={level_name(_named_at_or_below(self.without))}"

    @property
    def level_name(self) -> str:
        return level_name(self.level)


class Caps:
    """The rows, and what became of them (decisions 2 to 4).

    The rules live here, apart from the module's one table, so that each can be
    run against real loggers with the two things the process decides — whether
    the default is in charge, and what ``LOG_LEVEL`` says — handed in.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], Row] = {}
        self._set: dict[str, int] = {}
        self._verdicts: tuple[Verdict, ...] = ()
        #: Whether the rows have been set: the application was imported.
        self.settled = False

    def declare(self, logger: object, level: object, *, hides: object,
                package: str) -> str | None:
        """Record a row for ``package``, or answer why not, in a sentence — the
        declaration is then skipped, and whatever row stood before it stands.
        Nothing here raises and no logger is touched.

        The same package declaring a logger again replaces its row. After
        :meth:`settle` every declaration is refused but one that repeats a row as
        it stands, which is nothing: a module may be imported twice. Spaces around
        the name are dropped, and a run of white space in ``hides`` is one space,
        so a sentence wrapped in its source is one line on the page.
        """
        who = package or UNIDENTIFIED
        name = logger.strip() if isinstance(logger, str) else ""
        says = " ".join(hides.split()) if isinstance(hides, str) else ""
        if self.settled:
            standing = self._rows.get((name, package))
            if (standing is not None and isinstance(level, int)
                    and not isinstance(level, bool)
                    and (standing.level, standing.hides) == (level, says)):
                return None
            return (f"{who} declares a noise cap on {name or repr(logger)} after "
                    f"the application was imported — the caps are set once, at "
                    f"that import, so a declaration goes before it (ADR-0121); it "
                    f"is ignored")
        if not name or any(not part for part in name.split(".")):
            return (f"{who} declares a noise cap on {logger!r}, which names no "
                    f"logger (ADR-0121); it is ignored")
        if name == ROOT:
            return (f"{who} declares a noise cap on the root logger — a cap names "
                    f"a dependency's logger, and the root's level is LOG_LEVEL's "
                    f"to say (ADR-0121); it is ignored")
        if name == OWN or name.startswith(OWN + "."):
            return (f"{who} declares a noise cap on {name}, the library's own "
                    f"logger — its lines are what the log is for, and only "
                    f"LOG_LEVEL takes them out (ADR-0121); it is ignored")
        if not isinstance(level, int) or level not in LEVELS:
            shown = (level_name(level)
                     if isinstance(level, int) and not isinstance(level, bool)
                     else repr(level))
            return (f"{who} declares a noise cap on {name} at {shown} — a "
                    f"package caps at logging.INFO or logging.WARNING, by the "
                    f"constant, and a warning or an error is taken out by the "
                    f"deployment alone, with LOG_LEVEL (ADR-0121); it is ignored")
        if not says:
            return (f"{who} declares a noise cap on {name} and does not say what "
                    f"it hides — hides= is what /system/installed prints beside "
                    f"the cap (ADR-0121); it is ignored")
        self._rows[(name, package)] = Row(name, level, package, says)
        return None

    def rows(self) -> tuple[Row, ...]:
        """Every row, by logger and then by package."""
        return tuple(sorted(self._rows.values(),
                            key=lambda row: (row.logger, row.package)))

    def verdicts(self) -> tuple[Verdict, ...]:
        """What became of the rows, a verdict for each logger a row names, by
        logger — nothing until :meth:`settle` has run."""
        return self._verdicts

    def levels_set(self) -> dict[str, int]:
        """The level the rows set, for each logger they were set on."""
        return dict(self._set)

    def settle(self, *, in_charge: bool, entries: Entries) -> None:
        """Set the rows, once (decision 4) — where the application is imported,
        after the code of the slot. Where the default is in charge the named
        entries of ``LOG_LEVEL`` are said a second time first (decision 5), so
        that the variable stands over what that code set. Then every logger a row
        names is judged, **from the top of the names down**, so that a row sees
        what the rows above it came to. A second call does nothing.
        """
        if self.settled:
            return
        if in_charge:
            entries.say()
        declared: dict[str, list[Row]] = {}
        for row in self.rows():
            declared.setdefault(row.logger, []).append(row)
        verdicts = []
        for name in sorted(declared, key=lambda at: (at.count("."), at)):
            level = max(row.level for row in declared[name])
            reason, without = self._why_not(name, level, in_charge=in_charge,
                                            entries=entries)
            if not reason:
                logging.getLogger(name).setLevel(level)
                self._set[name] = level
            verdicts.append(Verdict(name, level, tuple(declared[name]), reason,
                                    without))
        self._verdicts = tuple(sorted(verdicts, key=lambda verdict: verdict.logger))
        self.settled = True

    def _why_not(self, name: str, level: int, *, in_charge: bool,
                 entries: Entries) -> tuple[str, int]:
        """The first of the four reasons that holds for not setting ``level`` on
        the logger ``name``, as a sentence — or ``""``: nothing holds, and the row
        is set. With it the level the logger is at without the row, which the
        fourth reason is about and a row that is set is undone by; ``NOTSET``
        where one of the first three held, which do not ask for it."""
        if not in_charge:
            return "the application configured logging itself", logging.NOTSET
        named = entries.speaks_for(name)
        if named is not None:
            return f"LOG_LEVEL names {named}", logging.NOTSET
        through = "the root"
        without = logging.getLogger().level
        # Nearest first, so the first level found above is the one the logger
        # is at without its row.
        for at in (name, *above(name)):
            standing = level_on(at)
            if standing == logging.NOTSET:
                continue
            if self._set.get(at) != standing:
                # A level on a name speaks for the names beneath it that carry
                # none: a deployment that set `botocore` to DEBUG in the slot
                # asked for the credential lines as well.
                return (f"{at} is at {level_name(standing)}, set by the "
                        f"application's code or by the dependency itself",
                        logging.NOTSET)
            if through == "the root":
                through, without = f"the cap on {at}", standing
        if without >= level:
            return (f"it would take no line away — without it the logger is at "
                    f"{level_name(without)} already, through {through}", without)
        return "", without


def _own() -> Caps:
    """A table that holds the library's own rows and no other (decision 1): the
    rows for its own dependencies, and that is one."""
    caps = Caps()
    caps.declare("markdown_it", logging.INFO, package=OWN,
                 hides="a DEBUG line for each block rule of every render")
    return caps


#: The process's table: the library's own rows, and what the packages declared.
_caps = _own()


def cap(logger: str, level: int, *, hides: str = "") -> None:
    """Declare a noise cap for a dependency this package brings (ADR-0121
    decision 2) — a row, and no level::

        noise.cap("botocore.credentials", logging.WARNING,
                  hides="where each new session found its credentials, a line a run")

    Called in the import-before-app slot, beside a package's other
    registrations. ``logger`` is a dependency's logger, by name; ``level`` is
    ``logging.INFO`` or ``logging.WARNING``; ``hides`` finishes the sentence *it
    hides …* for a reader of ``/system/installed`` who is deciding whether to ask
    for the lines back. The declaring **package** is inferred from the call site.

    Whether the cap is set is decided where the application is imported
    (:func:`settle`), and a deployment has the lines back by name:
    ``LOG_LEVEL=INFO,botocore.credentials=DEBUG``.

    A declaration outside the bounds is a warning and a skip — it never raises —
    and a line on ``/little-sister/startup``, which is why ``hides`` has a default
    it may not keep: a call that left it out is refused like any other, where a
    missing argument would have stopped the import.
    """
    given: object = logger
    package = calling_package()
    refused = _caps.declare(given, level, hides=hides, package=package)
    if refused is None:
        return
    name = given.strip() if isinstance(given, str) and given.strip() else repr(given)
    self_report.startup.note(slug("noise", package, name), plain(refused))


def settle() -> None:
    """Set the rows, once: the application's import calls it, in the position
    ``announce_doors()`` and ``announce_aspects()`` hold (ADR-0121 decision 4,
    ADR-0070) — every package has declared by then. Setting a level writes
    nothing an instance keeps, so an import may do it (ADR-0091 decision 1).

    The log says it where it begins (decision 7): an ``INFO`` line for each row
    that was set, which names the entry of ``LOG_LEVEL`` that shows its lines. A
    log that leaves lines out says which. A row that was not set leaves nothing
    out, so the log says nothing of it — not at a start with nothing to cap, not
    for a level the deployment chose itself, and not in the log of an application
    that configured logging — and ``/system/installed`` says why it was not
    (:func:`report`).
    """
    if _caps.settled:
        return
    _caps.settle(in_charge=default.in_charge, entries=default.entries)
    for verdict in _caps.verdicts():
        if verdict.capped:
            for row in verdict.rows:
                logger.info("noise: %s", _said(verdict, row))


def _said(verdict: Verdict, row: Row) -> str:
    """The line the log carries for one row of a logger that was capped."""
    standing = (f"capped at {verdict.level_name} for {row.owner}"
                if row.level == verdict.level else
                f"capped at {verdict.level_name}, above the {row.level_name} "
                f"{row.owner} declared")
    return (f"{row.logger} is {standing} — it hides {row.hides}; "
            f"{verdict.shown_by} in LOG_LEVEL shows its lines")


def rows() -> tuple[Row, ...]:
    """Every declared row, the library's own included, by logger and package."""
    return _caps.rows()


def forget_caps() -> None:
    """Back to the library's own rows, not yet set (tests). The levels an earlier
    table set on loggers are not taken back: a test that sets one restores it."""
    global _caps
    _caps = _own()


@dataclass(frozen=True)
class OwnLevel:
    """One logger that carries a level of its own, and where the level comes from
    (decision 7): ``"cap"``, a row, with the rows that name the logger;
    ``"variable"``, an entry of ``LOG_LEVEL``; or ``"code"``, which is neither —
    the application's code, or the dependency itself."""
    logger: str
    level_name: str
    source: str
    rows: tuple[Row, ...] = ()
    #: For a cap, the entry of ``LOG_LEVEL`` that shows its lines
    #: (:attr:`Verdict.shown_by`); ``""`` for the other two.
    shown_by: str = ""


@dataclass(frozen=True)
class Report:
    """What ``/system/installed`` says of the log (decision 7)."""
    #: Whether the library's default is in charge of the log.
    in_charge: bool
    #: The root's level, and where it comes from: ``"variable"``, the bare entry
    #: of ``LOG_LEVEL``; ``"default"``, where the variable names none;
    #: ``"code"``, set after the default was installed; or ``"application"``,
    #: where the application configured logging itself.
    root: str
    root_source: str
    #: What ``LOG_LEVEL`` says as it was read, in the form the variable takes
    #: (:meth:`~little_sister.logger.Entries.written`): the page's example is this
    #: and one entry more. ``""`` where the application configured logging itself.
    variable: str
    #: Every logger that carries a level of its own, by name.
    levels: tuple[OwnLevel, ...]
    #: The rows that were not set, with the reason.
    not_set: tuple[Verdict, ...]
    #: Every level an entry of ``LOG_LEVEL`` took off, with the logger it stood on
    #: — once, also where it was taken off at both moments the entries are said.
    taken_off: tuple[TakenOff, ...]
    #: Every entry of ``LOG_LEVEL`` that could not be read.
    unreadable: tuple[Unreadable, ...]


def report() -> Report:
    """The *Logging* section's facts, read off the loggers as they stand **now**:
    what code set after the application was imported, it set, and the page says
    what stands. A level is a row's where the rows set it and it still stands,
    an entry's where the variable names the logger at that level, and otherwise
    neither."""
    in_charge, entries = default.in_charge, default.entries
    root = logging.getLogger().level
    if not in_charge:
        root_source = "application"
    elif entries.bare is not None and root == entries.bare:
        root_source = "variable"
    elif entries.bare is None and root == default.DEFAULT_LEVEL:
        root_source = "default"
    else:
        root_source = "code"
    set_by_rows = _caps.levels_set()
    declared = {verdict.logger: verdict for verdict in _caps.verdicts()}
    levels = []
    for name, standing in sorted(logging.Logger.manager.loggerDict.items()):
        if not isinstance(standing, logging.Logger):
            continue
        if standing.level == logging.NOTSET:
            continue
        if in_charge and set_by_rows.get(name) == standing.level:
            levels.append(OwnLevel(name, level_name(standing.level), "cap",
                                   declared[name].rows, declared[name].shown_by))
        elif in_charge and entries.named.get(name) == standing.level:
            levels.append(OwnLevel(name, level_name(standing.level), "variable"))
        else:
            levels.append(OwnLevel(name, level_name(standing.level), "code"))
    return Report(
        in_charge=in_charge, root=level_name(root), root_source=root_source,
        variable=entries.written() if in_charge else "",
        levels=tuple(levels),
        not_set=tuple(verdict for verdict in _caps.verdicts()
                      if not verdict.capped),
        # The entries are said twice, so a level set again between the two is
        # taken off twice: the page lists what was taken off, and that is once.
        taken_off=tuple(dict.fromkeys(entries.taken_off)) if in_charge else (),
        unreadable=tuple(entries.unreadable) if in_charge else ())
