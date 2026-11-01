"""The deployment's holidays: ``config/holidays.yaml`` (ADR-0149).

A deployment writes here the days nobody works, as named lists — a region's public
holidays, a company's own days off — each meaning that one thing, so that every reader
uses a list the same way: maintenance's *not on holidays* first (#35), the watch
window's closed shop and quiet hours' nobody on duty when they come. Nothing reads the
lists yet; this module settles what a list *is* and what of it can be read.

**A list** is keyed by a name the deployment chooses — an ISO 3166-2 code by convention
for a region's public holidays, anything for a company's own — and writes three keys::

    lists:
      DE-BY:
        name: holidays in Bavaria
        complete: [2026, 2027]
        dates:
          2026-11-01: All Saints' Day
          2026-12-25: Christmas Day
    default: DE-BY

- The key is what a reader keeps — a maintenance entry's ``not_on: DE-BY`` — as an
  entry keeps its zone, so that nothing a later file says of its default moves it.
- ``name`` reads after *not on* in a sentence: *not on holidays in Bavaria*, *not on
  ACME's company holidays*.
- ``complete`` is the years the list is complete for, **stated, never inferred**: a
  company's list that rightly has no day in a year is complete for it, and a day
  written in a year the list does not state makes that year no more complete. A reader
  that needs a year the list does not state has it missing.
- ``dates`` maps each day, ``YYYY-MM-DD``, to its name, which a page marks it with.

``default`` names the list an editor offers first; it may be left out.

**What cannot be read does not apply** (ADR-0032 rule 7). Within a list, any mistake —
a day that is no date or carries a time, a day written twice, a day or a list with no
name, no year stated complete or one that is no year, a key a list does not know —
leaves that list unreadable whole, since a day missing from it would put a window on
that day; the others stand. Outside the lists, a mistake leaves the file unreadable,
and a file that cannot be read leaves every list unreadable, since any of them may be
written in it. Each is one line on the startup record (``self_report.startup``), a
warning on the instance's own node for the life of the process — never a refusal to
start. A ``default`` that names no list hides nothing, so it stops nothing: it is
named, and no list is offered first. A reader asks for a list by its key and gets it,
or why not (:meth:`Holidays.why_not`); what it does without one is the reader's, and
fails toward alarming.

**Every configuration root's file is read**, in path-list order (ADR-0031): a list
named in two roots is the later root's, whole, keeping the place it was first named in,
and so is ``default``. The start reads them once, as it reads all configuration until a
reload in place (#31).

**Not built, and kept open** (ADR-0149 decision 5): a list may one day be filled from
outside — an ICS file or feed, a Google or a Microsoft 365 calendar — through a seam,
and say where it came from. A list is a mapping of named keys so that such a key is an
addition, never a change of the file's shape.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import MAXYEAR, MINYEAR, date, datetime
from pathlib import Path
from typing import Any

import yaml

from little_sister import self_report
from little_sister.config_dir import aspect_files
from little_sister.reasons import plain, slug

#: The configuration aspect the holidays are read from.
ASPECT = "holidays"

#: The keys a file writes, and the keys a list writes.
_FILE_KEYS = ("lists", "default")
_LIST_KEYS = ("name", "complete", "dates")

#: A list's key as it is read: letters and digits, with hyphens, dots or underscores
#: between them — a word an entry keeps and a page may put in an address.
_KEY = re.compile(r"[A-Za-z0-9]+(?:[-._][A-Za-z0-9]+)*")

#: What every line about a file that cannot be read ends with.
_NO_LIST = ", so no holiday list can be read"


@dataclass(frozen=True)
class HolidayList:
    """One list of the days nobody works: its key, the ``name`` that reads after *not
    on*, the years it is ``complete`` for, its ``dates`` each with its name, and the
    ``file`` it was read from."""

    key: str
    name: str
    complete: frozenset[int]
    dates: Mapping[date, str]
    file: Path

    def covers(self, year: int) -> bool:
        """Whether the list states that it is complete for ``year``."""
        return year in self.complete

    def holiday(self, day: date) -> str:
        """The name of ``day`` where the list names it — empty where it does not."""
        return self.dates.get(day, "")


@dataclass(frozen=True)
class Holidays:
    """What the start read: the ``lists`` that can be read, in the order first named;
    the ``unreadable`` ones, each with why; ``broken``, why no list can be read where a
    file could not be; the ``default``; and the ``files`` read, in path-list order —
    none where no root has a ``holidays.yaml``."""

    lists: Mapping[str, HolidayList] = field(default_factory=dict)
    unreadable: Mapping[str, str] = field(default_factory=dict)
    broken: str = ""
    default: str = ""
    files: tuple[Path, ...] = ()

    def get(self, key: str) -> HolidayList | None:
        """The list ``key`` names, or ``None`` where it cannot be had —
        :meth:`why_not` says why."""
        return None if self.broken else self.lists.get(key)

    def why_not(self, key: str) -> str:
        """Why the list ``key`` cannot be had, in the words of the startup record —
        empty where it can."""
        if self.broken:
            return self.broken
        if key in self.lists:
            return ""
        if key in self.unreadable:
            return self.unreadable[key]
        if not self.files:
            return "no configuration root has a holidays.yaml"
        if len(self.files) == 1:
            return f"{self.files[0]} lists no {key}"
        return f"{', '.join(str(file) for file in self.files)} list no {key}"


#: The holidays of a deployment that writes none.
NO_HOLIDAYS = Holidays()


class _Mapping(dict[Any, Any]):
    """A mapping as the file writes it, with the keys it writes more than once."""

    twice: tuple[Any, ...] = ()


class _Loader(yaml.SafeLoader):
    """YAML as the safe loader reads it, but for two things: a mapping keeps the keys
    it writes twice rather than the last of them alone, since a day written twice is a
    mistake to name, never one to settle in silence; and a day that is no date — the
    thirteenth month — stays the text it was written as, for its list to be named,
    where the safe loader raises out of the whole file."""


def _mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> _Mapping:
    loader.flatten_mapping(node)
    read = _Mapping()
    twice: list[Any] = []
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        try:
            seen = key in read
        except TypeError as error:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"found a key that cannot be one ({error})",
                key_node.start_mark) from None
        if seen:
            twice.append(key)
        read[key] = loader.construct_object(value_node, deep=True)
    read.twice = tuple(dict.fromkeys(twice))
    return read


def _timestamp(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> object:
    try:
        return loader.construct_yaml_timestamp(node)
    except ValueError:
        return loader.construct_scalar(node)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
_Loader.add_constructor("tag:yaml.org,2002:timestamp", _timestamp)


def load_holidays(config_dir: str | Path | None = None) -> Holidays:
    """The holidays of every configuration root, in path-list order (ADR-0031): each
    root's ``holidays.yaml`` read, a list named in two of them the later root's, whole,
    in the place it was first named in, and ``default`` the later root's — what cannot
    be read named on the startup record, one line each."""
    lists: dict[str, HolidayList] = {}
    unreadable: dict[str, str] = {}
    files: list[Path] = []
    broken = ""
    default: tuple[str, Path] | None = None
    for file in aspect_files(ASPECT, config_dir):
        files.append(file)
        data, problem = _read_file(file)
        if problem:
            broken = broken or problem
            _note(slug("holidays", "unread", str(file)), problem)
            continue
        written = data.get("lists")
        if isinstance(written, _Mapping):
            for key, raw in written.items():
                read = _read_list(file, key, raw, twice=key in written.twice)
                if isinstance(read, HolidayList):
                    lists[read.key] = read
                    unreadable.pop(read.key, None)
                elif read is not None:
                    unreadable[key] = read
                    lists.pop(key, None)
        named = data.get("default")
        if isinstance(named, str) and named.strip():
            default = (named.strip(), file)
        elif named is not None and not isinstance(named, str):
            default = None
            _note(slug("holidays", "default", str(file)),
                  f"{file}: default is {_a(named)}, where it names a holiday list; no "
                  f"list is offered first")
    if broken:
        return Holidays(broken=broken, files=tuple(files))
    chosen = ""
    if default is not None:
        named, file = default
        if named in lists or named in unreadable:
            chosen = named
        else:
            _note(slug("holidays", "default", str(file)),
                  f"{file}: default names {named}, which no holiday list is; no list "
                  f"is offered first")
    return Holidays(lists=lists, unreadable=unreadable, default=chosen,
                    files=tuple(files))


def _read_file(file: Path) -> tuple[_Mapping, str]:
    """What ``file`` writes, or why it cannot be read — in which case no list can be."""
    try:
        with open(file, encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_Loader)
    except (OSError, yaml.YAMLError) as error:
        return _Mapping(), (f"{file} cannot be read ({' '.join(str(error).split())})"
                            f"{_NO_LIST}")
    if data is None:
        return _Mapping(), ""
    if not isinstance(data, _Mapping):
        return _Mapping(), (f"{file} is {_a(data)}, where it maps lists and default"
                            f"{_NO_LIST}")
    if data.twice:
        return _Mapping(), f"{file} writes {_names(data.twice)} twice{_NO_LIST}"
    unknown = [key for key in data if key not in _FILE_KEYS]
    if unknown:
        return _Mapping(), (f"{file} writes {_names(unknown)}, which it does not know"
                            f"{_NO_LIST}")
    written = data.get("lists")
    if written is not None and not isinstance(written, _Mapping):
        return _Mapping(), (f"{file}'s lists are {_a(written)}, where they map each "
                            f"list's key to the list{_NO_LIST}")
    return data, ""


def _read_list(file: Path, key: object, raw: object, *,
               twice: bool) -> HolidayList | str | None:
    """The list ``key`` names in ``file``, or why it cannot be read — named on the
    startup record — or ``None`` where its key is no text, which no reader can name."""
    if not isinstance(key, str):
        _note(slug("holidays", "unread", str(file), str(key)),
              f"{file} names the holiday list {key}, which YAML reads as {_a(key)}; a "
              f"list's key is text — put it in quotes")
        return None
    why = _list_problem(key, raw, twice=twice)
    if why or not isinstance(raw, _Mapping):
        said = f"{file}: the holiday list {key} cannot be read — {why}"
        _note(slug("holidays", "unread", str(file), key), said)
        return said
    complete = raw["complete"]
    years = complete if isinstance(complete, list) else [complete]
    dates = raw.get("dates") or {}
    return HolidayList(
        key=key, name=" ".join(raw["name"].split()), complete=frozenset(years),
        dates={day: " ".join(name.split()) for day, name in dates.items()}, file=file)


def _list_problem(key: str, raw: object, *, twice: bool) -> str:
    """What leaves the list ``key`` unreadable — empty where nothing does."""
    if not _KEY.fullmatch(key):
        return ("a list's key is letters and digits, with hyphens, dots or underscores "
                "between them")
    if twice:
        return "it is written twice in one file"
    if not isinstance(raw, _Mapping):
        return f"it is {_a(raw)}, where it maps name, complete and dates"
    if raw.twice:
        return f"it writes {_names(raw.twice)} twice"
    unknown = [each for each in raw if each not in _LIST_KEYS]
    if unknown:
        return f"it writes {_names(unknown)}, which a list does not know"
    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        return (f"its name is {name}, which YAML reads as {_a(name)} — put it in "
                f"quotes")
    if not (name or "").strip():
        return "it has no name, which reads after *not on*"
    complete = raw.get("complete")
    years = ([] if complete is None else
             complete if isinstance(complete, list) else [complete])
    if not years:
        return "it states no year it is complete for"
    for year in years:
        if not _is_year(year):
            return f"it states {year!r} complete, which is no year"
    dates = raw.get("dates")
    if dates is None:
        return ""
    if not isinstance(dates, _Mapping):
        return f"its dates are {_a(dates)}, where they map each day to its name"
    if dates.twice:
        return f"it writes {_names(dates.twice)} twice"
    for day, day_name in dates.items():
        if isinstance(day, datetime):
            return f"it names {day}, which carries a time: a day is written YYYY-MM-DD"
        if not isinstance(day, date):
            return f"it names {day}, which is no date: a day is written YYYY-MM-DD"
        if day_name is not None and not isinstance(day_name, str):
            return (f"it gives {day} the name {day_name}, which YAML reads as "
                    f"{_a(day_name)} — put it in quotes")
        if not (day_name or "").strip():
            return f"it gives {day} no name"
    return ""


def _is_year(value: object) -> bool:
    """Whether ``value`` is a year a date can be in: an integer, and no truth value
    YAML read from *yes* or *true*."""
    return (isinstance(value, int) and not isinstance(value, bool)
            and MINYEAR <= value <= MAXYEAR)


def _names(keys: Iterable[object]) -> str:
    """Keys as a line names them, in the order written."""
    return ", ".join(str(key) for key in keys)


def _a(value: object) -> str:
    """What YAML read ``value`` as, with its article where it takes one: *a list*, *an
    int*, *text*, *empty*."""
    if value is None:
        return "empty"
    if isinstance(value, str):
        return "text"
    kind = "mapping" if isinstance(value, dict) else type(value).__name__
    return f"{'an' if kind[0] in 'aeiou' else 'a'} {kind}"


def _note(key: str, text: str) -> None:
    """What cannot be read, on the startup record: a warning on the instance's node for
    the life of the process, so that whoever wrote it learns without reading the log."""
    self_report.startup.note(key, plain(text))
