"""An instant: the clock that answers one, how one is spelled, and how one is read.

An **instant** here is a time that knows its zone, held in UTC. A time without a
zone is the wall clock of whichever machine wrote it — an instant only on that
machine, and only until its clock changes — which is why a reading's
``observed_at`` is an aware instant (ADR-0087), a record's own times cross the
seam in UTC (ADR-0082), and every time the tree stores is an instant (ADR-0120).
What the series, the seam and the API each wrote out for themselves is here once:

* :func:`now` — **the clock**, as an instant in UTC. A constructor that takes a
  clock, as the engine's ``wall`` does, defaults to this one, so a test holds time
  still by handing a clock in.
* :func:`utc` — **the holding**: an instant as what holds one keeps it, in UTC,
  and :class:`ValueError` for a time without a zone — called where an event, a pin
  or a period's beginning is built, so that none can be built with one.
* :func:`stamp` — **the spelling**: UTC, with a ``Z``. One function, so that an
  instant reads alike in a state file and in the API's JSON. A time without a zone
  is not spelled at all.
* :func:`instant` — **the reading**, and a strict one: :class:`ValueError` for a
  time that carries no offset, and for anything else that is no instant. A state
  file is written by this library and by nothing else, so a time its reader cannot
  take is a damaged file and not a dialect, and the :class:`ValueError` is what the
  state layer reports as a load failure (ADR-0071).

This module imports nothing of the library, so every module may import it.
"""
from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    """The clock: this moment, as an instant in UTC."""
    return datetime.now(UTC)


def utc(moment: datetime, where: str) -> datetime:
    """``moment`` as what holds an instant keeps it: the same instant, in UTC — or
    :class:`ValueError` naming ``where`` it was to stand, for a time without a zone.
    """
    if moment.utcoffset() is None:
        raise ValueError(
            f"{where} is a time without a zone, and no instant: "
            f"{moment.isoformat()!r}")
    return moment.astimezone(UTC)


def stamp(moment: datetime) -> str:
    """``moment`` as a state file and the API spell it: UTC, with a ``Z`` — the
    spelling the seam gives a record's own times (ADR-0082).

    :raises ValueError: ``moment`` carries no zone. Which instant it is depends on
        whose clock wrote it, and spelling it would be choosing one.
    :raises OverflowError: its offset carries it past the edge of the calendar. A
        caller that was handed such a time by somebody else says so in its own
        words, as the seam does.
    """
    if moment.utcoffset() is None:
        raise ValueError(
            f"a time without a zone is no instant, and is not spelled as one: "
            f"{moment.isoformat()!r}")
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def instant(value: object, where: str) -> datetime:
    """One time a file holds, as an instant in UTC — or :class:`ValueError` naming
    ``where`` it stood, which a state file's reader reports as a load failure.

    Refused: what is no text, text that is no time, and a time without an offset.
    And an instant its offset carries past the edge of the calendar — the first hour
    of the year 1 at ``+01:00`` is the year 0 in UTC — because the conversion raises
    :class:`OverflowError` there, which nothing that reads a file catches, so it
    would stop an instance where a state should start empty.
    """
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            moment = None
        if moment is not None and moment.utcoffset() is not None:
            try:
                return moment.astimezone(UTC)
            except OverflowError:
                raise ValueError(
                    f"{where} lies outside the years 1 to 9999 once it is read in "
                    f"UTC: {value!r}") from None
    raise ValueError(f"{where} is not an instant with an offset: {value!r}")
