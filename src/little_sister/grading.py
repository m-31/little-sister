"""What a check type grades, and how a deployment writes it (ADR-0131).

A type declares every value it grades — its **gradings** — beside the forms, the words
and the fields of its lines (ADR-0126), and hands them to ``Check.__init__`` as
``gradings``. A grading has a name, which is a stored key, one sentence, the field of
the record it reads by the dotted name a template addresses it by, and a kind:

* a **map** from a word of its source's vocabulary to a code — a band's severity, an
  alarm's state — written as a mapping under its key, each word matched with its case
  and the spaces around it folded; a word no key names grades WARN, so that a word the
  source began to send is seen (decision 4);
* a **pair** of levels over a number, ``<key>_warn`` and ``<key>_error``, beside
  ``<key>_reason`` and with ``<key>: null`` switching the judgment off, a level written
  with its unit: a ``max_…`` pair fails above its level and a ``min_…`` pair below it,
  so that a level is the last value that passes (decisions 2 and 3);
* a **set** of accepted values under its key — ``http``'s ``expected_status`` — any
  other value grading the code the type declares for it;
* a **judgment** the type makes in its own code, which a deployment gives a sentence,
  ``<key>_reason`` (decision 5);
* and a **window**, ``since``: a pair over how long ago the subject's kept readings
  last stood OK, which the library declares on every check as :data:`SINCE_OK` and
  applies over what the check keeps (decisions 7 and 8).

A grading lives in a **block** of the check's configuration — the check's own keys,
or a block of them a type reads, such as an aspect's — named in front of its key:
``ec2.max_age`` is the pair a deployment writes as ``max_age_warn`` in ``ec2:``. The
library reads what a deployment wrote — the check's own keys when the check is built,
a block wherever its type hands one over (:class:`GradingBlock`), and the keys a rule
of that block writes — refuses what does not fit, naming the key, and answers the code
of a value as a :class:`Verdict`: the code, the sentence written for the grading where
it fired, and the rule whose keys judged it.
"""
from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from little_sister.codes import StatusCode, worst_of
from little_sister.errors import CheckError
from little_sister.limits import format_weight
from little_sister.reasons import Entry, derived_slug, plain
from little_sister.spans import format_duration

#: The check-authoring surface of this module (architecture.md §11, ADR-0049): what a
#: type holds of the seam — everything else here is the library's to read with.
__all__ = ["Graded", "GradingBlock", "Verdict", "worst"]

logger = logging.getLogger(__name__)

#: The kinds of grading (decisions 2, 5 and 8).
MAP = "map"
PAIR = "pair"
SET = "set"
JUDGMENT = "judgment"
SINCE = "since"
KINDS = (MAP, PAIR, SET, JUDGMENT, SINCE)

#: What a pair's level is, which decides how it is written and read: a **count**, a
#: whole number of 0 or more; a **number**, any finite number — a load per core, a
#: temperature; a **duration** in the library's grammar (``26h``, ``2w``), at least a
#: second; a **size** in the library's grammar (``500 GB``, ``2 TiB``); an **amount**
#: of money, a number of 0 or more in the currency of what it is compared with; and a
#: **share**, a percentage written with its sign (``80%``), compared with a field that
#: holds one.
COUNT = "count"
NUMBER = "number"
DURATION = "duration"
SIZE = "size"
AMOUNT = "amount"
SHARE = "share"
UNITS = (COUNT, NUMBER, DURATION, SIZE, AMOUNT, SHARE)

#: The window grading every check takes (decision 8): how long before the reading
#: graded the newest kept reading of its subject was taken that stood OK, the reading
#: graded included — ``max_since_ok_error: 26h`` says *the last run succeeded within
#: 26 h*. A check that keeps no series cannot take it (decision 7).
SINCE_OK = "max_since_ok"

#: The word the library hands a line a grading decided (decision 5): the sentence the
#: deployment wrote for that grading, where it fired.
REASON_WORD = "reason"

#: The codes a map may give a word: a claim a line can make (ADR-0042), and never
#: ``UNDEFINED``, which would leave a finding counting for nothing.
_MAP_CODES = (StatusCode.OK, StatusCode.WARN, StatusCode.ERROR)

#: One part of a grading's name: its key, or a block's name.
_PART = r"[a-z][a-z0-9_]*"
_NAME = re.compile(rf"(?:{_PART}\.)*{_PART}")
_SHARE = re.compile(r"\s*(\d+(?:\.\d+)?)\s*%\s*")

#: What each kind's declaration holds — required, and allowed beside it.
_DECLARED: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    MAP: (frozenset({"sentence", "kind", "field", "words"}), frozenset({"rules"})),
    PAIR: (frozenset({"sentence", "kind", "field", "unit"}),
           frozenset({"warn", "error", "rules"})),
    SET: (frozenset({"sentence", "kind", "field", "accepted"}),
          frozenset({"code", "rules"})),
    JUDGMENT: (frozenset({"sentence", "kind", "field"}), frozenset({"rules"})),
    SINCE: (frozenset({"sentence", "kind"}), frozenset({"warn", "error", "rules"})),
}

#: How a refusal says what a level of each unit is.
_UNIT_SAYS = {
    COUNT: "a whole number of 0 or more",
    NUMBER: "a number",
    DURATION: "a duration of at least 1s, as 26h",
    SIZE: "a size, as 500 GB or 2 TiB",
    AMOUNT: "an amount of 0 or more",
    SHARE: "a share written with its percent sign, as 80%",
}


class GradingError(CheckError):
    """What a type declares, or what a deployment writes, cannot be read as a
    grading: a check configuration error, which stops the start naming the file
    wherever it is raised — as the check is built, or where its type reads a block."""


def fold(word: str) -> str:
    """A map's word as it is matched (decision 4): its case and the spaces around it
    folded, so that ``ALARM``, ``Alarm `` and ``alarm`` are one word."""
    return word.strip().casefold()


# --- what a type declares ---------------------------------------------------------


@dataclass(frozen=True)
class Grading:
    """One value a type grades, as it declares it (decision 1).

    ``name`` is its full name, ``[block.]key``: the key a deployment writes it under,
    behind the block it lives in — ``max_disk`` among the check's own keys,
    ``ec2.max_age`` in ``ec2:``. ``field`` is the record's field it reads, by its
    dotted name; a window reads no field. ``unit`` is a pair's, and a window's
    duration. ``warn`` and ``error`` are a pair's defaults, read as a deployment's
    levels are; ``words`` a map's vocabulary with each word's default code;
    ``accepted`` a set's default values and ``failing`` the code any other takes.
    ``rules`` says whether a rule of its block may write it (decision 6).
    """

    name: str
    sentence: str
    kind: str
    field: str = ""
    unit: str = ""
    warn: float | None = None
    error: float | None = None
    words: tuple[tuple[str, StatusCode], ...] = ()
    accepted: tuple[int | str, ...] = ()
    failing: StatusCode = StatusCode.ERROR
    rules: bool = False

    @property
    def block(self) -> str:
        """The block it lives in — empty for the check's own keys."""
        return self.name.rpartition(".")[0]

    @property
    def key(self) -> str:
        """The key a deployment writes it under, in its block."""
        return self.name.rpartition(".")[2]

    @property
    def most(self) -> bool:
        """Whether a pair, or a window, grades a maximum — fails above its levels —
        rather than a minimum."""
        return self.key.startswith("max_")

    @property
    def keys(self) -> tuple[str, ...]:
        """Every key a deployment writes it under, in its block."""
        key = self.key
        if self.kind in (PAIR, SINCE):
            return key, f"{key}_warn", f"{key}_error", f"{key}_reason"
        if self.kind == MAP:
            return (key,)
        if self.kind == SET:
            return key, f"{key}_reason"
        return (f"{key}_reason",)

    @property
    def default(self) -> Setting:
        """What it grades with where nothing is written."""
        if self.kind in (PAIR, SINCE):
            return Levels(self.warn, self.error)
        if self.kind == MAP:
            return Words(self.words)
        if self.kind == SET:
            return Accepted(self.accepted)
        return Sentence()

    def written(self, value: float) -> str:
        """One of a pair's levels as its unit writes it."""
        return _written(self.unit, value)


def declare(value: object) -> tuple[Grading, ...]:
    """A type's ``gradings``, read: a mapping of each grading's full name to its
    declaration — its sentence, its kind, the field it reads and what its kind
    takes, each default read as a deployment's value is — so that a mistake in one
    fails the type's own tests (decision 1)."""
    if value is None:
        return ()
    if not isinstance(value, Mapping):
        raise GradingError(
            f"gradings maps a grading's full name to its declaration, and is "
            f"{type(value).__name__}")
    declared: list[Grading] = []
    for name, entry in value.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise GradingError(
                f"gradings declares {name!r}, which is not a grading's name: a key "
                f"in lower case, behind the block it lives in, as ec2.max_age")
        declared.append(_declared(name, entry, f"gradings.{name}"))
    return tuple(declared)


def _declared(name: str, entry: object, where: str) -> Grading:
    if not isinstance(entry, Mapping):
        raise GradingError(f"{where} must be a mapping, not {entry!r}")
    held = {str(key): item for key, item in entry.items()}
    kind = held.get("kind")
    if kind not in _DECLARED:
        raise GradingError(f"{where}.kind is one of {', '.join(KINDS)}, not {kind!r}")
    required, allowed = _DECLARED[str(kind)]
    missing = sorted(required - set(held))
    if missing:
        raise GradingError(f"{where} needs {', '.join(repr(k) for k in missing)}")
    unknown = sorted(set(held) - required - allowed)
    if unknown:
        raise GradingError(
            f"{where} does not take {', '.join(repr(k) for k in unknown)} "
            f"(a {kind} takes {', '.join(sorted(required | allowed))})")
    sentence = held["sentence"]
    if not isinstance(sentence, str) or not sentence.strip():
        raise GradingError(f"{where}.sentence must be one sentence, not {sentence!r}")
    rules = held.get("rules", False)
    if not isinstance(rules, bool):
        raise GradingError(f"{where}.rules is true or false, not {rules!r}")
    key = name.rpartition(".")[2]
    grading = Grading(name, sentence.strip(), str(kind), rules=rules)
    if kind != SINCE:
        field = held["field"]
        if not isinstance(field, str) or not re.fullmatch(
                r"[A-Za-z0-9_*][A-Za-z0-9_*-]*(?:\.[A-Za-z0-9_*][A-Za-z0-9_*-]*)*",
                field):
            raise GradingError(
                f"{where}.field is the record's field it reads, by its dotted name, "
                f"not {field!r}")
        grading = replace(grading, field=field)
    if kind in (PAIR, SINCE):
        if not key.startswith(("max_", "min_")) or key in ("max_", "min_"):
            raise GradingError(
                f"{where}: a {kind}'s name says which way it grades — max_… fails "
                f"above its levels and min_… below them — and {key!r} does not")
        if kind == SINCE and not grading.most:
            raise GradingError(
                f"{where}: a window's time since is a maximum, and its name starts "
                f"with max_")
        unit = DURATION if kind == SINCE else held["unit"]
        if unit not in UNITS:
            raise GradingError(f"{where}.unit is one of {', '.join(UNITS)}, "
                               f"not {unit!r}")
        grading = replace(grading, unit=str(unit))
        warn = (None if held.get("warn") is None
                else _level(held["warn"], grading.unit, f"{where}.warn"))
        error = (None if held.get("error") is None
                 else _level(held["error"], grading.unit, f"{where}.error"))
        _ordered(grading, warn, error, f"{where}.error", f"{where}.warn")
        grading = replace(grading, warn=warn, error=error)
    elif kind == MAP:
        words = held["words"]
        if not isinstance(words, Mapping) or not words:
            raise GradingError(
                f"{where}.words maps each word of the source's vocabulary to its "
                f"default code, as critical: ERROR")
        grading = replace(grading, words=_words(words, f"{where}.words").codes)
    elif kind == SET:
        accepted = _accepted(held["accepted"], f"{where}.accepted", like=())
        if len({type(item) for item in accepted}) > 1:
            raise GradingError(f"{where}.accepted holds whole numbers or words, not "
                               f"both")
        failing = _code(held.get("code", "ERROR"), f"{where}.code")
        if failing == StatusCode.OK:
            raise GradingError(f"{where}.code is what a value outside the set grades, "
                               f"and OK would grade every value alike")
        grading = replace(grading, accepted=accepted, failing=failing)
    return grading


# --- what one block grades with ---------------------------------------------------


@dataclass(frozen=True)
class Levels:
    """What a pair, or a window, grades with: its two levels — ``None`` where one is
    not set, and so not compared — the sentence written for it, and whether
    ``<key>: null`` switched it off."""

    warn: float | None = None
    error: float | None = None
    reason: str = ""
    off: bool = False


@dataclass(frozen=True)
class Words:
    """What a map grades with: each word as it was written, and its code."""

    codes: tuple[tuple[str, StatusCode], ...] = ()

    def code_of(self, word: object) -> StatusCode | None:
        """The code ``word`` is mapped to, matched folded, or ``None`` where no word
        of this map is it."""
        if not isinstance(word, str):
            return None
        folded = fold(word)
        for written, code in self.codes:
            if fold(written) == folded:
                return code
        return None

    def over(self, beneath: Words) -> Words:
        """These words over ``beneath``, word by word: the code a word is given here,
        and ``beneath``'s for every word not named here (decision 6)."""
        named = {fold(word) for word, _ in self.codes}
        return Words(tuple((word, code) for word, code in beneath.codes
                           if fold(word) not in named) + self.codes)


@dataclass(frozen=True)
class Accepted:
    """What a set grades with: the values that pass, and the sentence written for
    it."""

    values: tuple[int | str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class Sentence:
    """What a judgment the type makes in its own code grades with: the sentence a
    deployment wrote for it."""

    reason: str = ""


#: What one grading grades with in one block.
Setting = Levels | Words | Accepted | Sentence


@dataclass(frozen=True)
class Graded:
    """What one block of a check's configuration grades with — the check's own keys,
    a block its type reads, or a rule of one: each grading's setting by its full
    name, and the gradings it wrote. A block holds a setting for every grading it
    declares, its default where nothing is written; a rule only what it wrote."""

    block: str
    settings: Mapping[str, Setting]
    written: frozenset[str] = frozenset()

    def summary(self, name: str, grading: Grading) -> str | None:
        """What this block says of one grading, as the check's configuration card
        writes it — *warn above 80%, error above 90%* — or ``None`` where it grades
        nothing: there is no honest way to write a comparison that never runs."""
        setting = self.settings.get(name)
        if isinstance(setting, Levels):
            if setting.off:
                return None
            way = "above" if grading.most else "below"
            parts = [f"{level} {way} {grading.written(value)}"
                     for level, value in (("warn", setting.warn),
                                          ("error", setting.error))
                     if value is not None]
            return ", ".join(parts) or None
        if isinstance(setting, Words):
            named = ", ".join(f"{word} → {code.name}" for word, code in setting.codes)
            return f"{named}; any other word → WARN"
        if isinstance(setting, Accepted):
            values = ", ".join(str(value) for value in setting.values)
            return f"{values}; any other → {grading.failing.name}"
        return None


class GradingBlock:
    """The gradings a type declares in one block of its configuration, and what reads
    them: a block, or a rule of it (decision 6).

    ``keys`` is every key the block's gradings are written under — what a type that
    refuses a key its block does not take adds to the keys it takes. ``said_by`` is
    the check's path, which the line in the log about a map's key that names no word
    begins with (decision 4).
    """

    def __init__(self, name: str, gradings: Iterable[Grading], *,
                 said_by: str = "") -> None:
        self.name = name
        self.gradings = tuple(gradings)
        self.said_by = said_by
        self.keys = frozenset(key for grading in self.gradings
                              for key in grading.keys)

    def defaults(self) -> Graded:
        """What the block grades with where nothing is written."""
        return Graded(self.name, {grading.name: grading.default
                                  for grading in self.gradings})

    def read(self, value: object, where: str = "") -> Graded:
        """What one instance of the block grades with, read out of ``value`` — the
        block as the configuration wrote it, absent being empty — each grading it
        does not write at its default. ``where`` names the block in a refusal:
        ``"ec2"``, or empty for the check's own keys."""
        if value is None:
            return self.defaults()
        if not isinstance(value, Mapping):
            raise GradingError(f"{where or 'the check'} must be a mapping of its keys, "
                               f"not {type(value).__name__}")
        settings: dict[str, Setting] = {}
        written: set[str] = set()
        for grading in self.gradings:
            setting = _read(grading, value, where, said_by=self.said_by)
            if setting is None:
                settings[grading.name] = grading.default
                continue
            if isinstance(setting, Words):
                setting = setting.over(Words(grading.words))
            settings[grading.name] = setting
            written.add(grading.name)
        return Graded(self.name, settings, frozenset(written))

    def read_rule(self, value: Mapping[str, Any], where: str) -> Graded:
        """What one rule of the block writes of its gradings, and nothing it does not:
        a pair, a set or a sentence whole, a map's words for the block's to be read
        under (decision 6). A grading no rule of the block may write is refused."""
        settings: dict[str, Setting] = {}
        for grading in self.gradings:
            setting = _read(grading, value, where, said_by=self.said_by)
            if setting is None:
                continue
            if not grading.rules:
                written = next(key for key in grading.keys if key in value)
                raise GradingError(
                    f"{where}: a rule does not write {written!r} — what it grades, "
                    f"{grading.name}, is the block's alone")
            settings[grading.name] = setting
        return Graded(self.name, settings, frozenset(settings))


def _read(grading: Grading, block: Mapping[str, Any], where: str, *,
          said_by: str) -> Setting | None:
    """What ``block`` writes of one grading, or ``None`` where it writes none of its
    keys."""
    if grading.kind in (PAIR, SINCE):
        return _read_levels(grading, block, where)
    if grading.kind == MAP:
        value = block.get(grading.key)
        if value is None:
            return None
        at = _at(where, grading.key)
        if not isinstance(value, Mapping):
            raise GradingError(
                f"{at} maps a word of its source to a code, as critical: ERROR — "
                f"not {type(value).__name__}")
        words = _words(value, at)
        declared = {fold(word) for word, _ in grading.words}
        unknown = [word for word, _ in words.codes if fold(word) not in declared]
        if unknown:
            # Said, never refused: the word may be one the source began to send after
            # the type's release (decision 4), and the map grades it as written.
            logger.info(
                "%s: %s names %s, which %s none of the words declared for it (%s); "
                "graded as written", said_by or "a check", at,
                ", ".join(repr(word) for word in unknown),
                "is" if len(unknown) == 1 else "are",
                ", ".join(word for word, _ in grading.words))
        return words
    if grading.kind == SET:
        key = grading.key
        if key not in block and f"{key}_reason" not in block:
            return None
        if block.get(key) is None:
            raise GradingError(
                f"{_at(where, key + '_reason')} is set but {key!r} is not: a set is "
                f"written whole, its values and its sentence")
        return Accepted(_accepted(block[key], _at(where, key), like=grading.accepted),
                        _reason(block, f"{key}_reason", where))
    key = f"{grading.key}_reason"
    if key not in block:
        return None
    return Sentence(_reason(block, key, where))


def _read_levels(grading: Grading, block: Mapping[str, Any],
                 where: str) -> Levels | None:
    """A pair's keys, or a window's, as ``block`` writes them (decision 2): absent
    where it writes none, switched off by ``<key>: null``, and otherwise whole — a
    level it leaves out is not compared, whatever the default."""
    key = grading.key
    keys = grading.keys
    if not any(name in block for name in keys):
        return None
    if key in block:
        if block[key] is not None:
            raise GradingError(
                f"{_at(where, key)} accepts only null, which switches the judgment "
                f"off — set a level with '{key}_warn' or '{key}_error'")
        beside = [name for name in keys[1:] if name in block]
        if beside:
            raise GradingError(
                f"{_at(where, key)}: null switches the judgment off, so it cannot be "
                f"written beside {', '.join(repr(name) for name in beside)}")
        return Levels(off=True)
    warn = _optional(block, f"{key}_warn", grading.unit, where)
    error = _optional(block, f"{key}_error", grading.unit, where)
    _ordered(grading, warn, error, _at(where, f"{key}_error"),
             _at(where, f"{key}_warn"))
    reason = _reason(block, f"{key}_reason", where)
    if reason and warn is None and error is None:
        raise GradingError(
            f"{_at(where, key + '_reason')} is set but neither '{key}_warn' nor "
            f"'{key}_error' is, so the sentence could never be said")
    return Levels(warn, error, reason)


def _optional(block: Mapping[str, Any], key: str, unit: str,
              where: str) -> float | None:
    value = block.get(key)
    return None if value is None else _level(value, unit, _at(where, key))


def _ordered(grading: Grading, warn: float | None, error: float | None,
             error_at: str, warn_at: str) -> None:
    """Refuse levels in which the warning could never be said (decision 3): an error
    level that is not beyond the warn level, equal ones included."""
    if warn is None or error is None:
        return
    if grading.most and error <= warn:
        raise GradingError(
            f"{error_at} ({grading.written(error)}) must be above {warn_at} "
            f"({grading.written(warn)}), or the warning could never be said")
    if not grading.most and error >= warn:
        raise GradingError(
            f"{error_at} ({grading.written(error)}) must be below {warn_at} "
            f"({grading.written(warn)}), or the warning could never be said")


def _level(value: object, unit: str, where: str) -> float:
    """One level as its unit writes it, or the refusal naming ``where``."""
    says = f"{where} must be {_UNIT_SAYS[unit]}, not {value!r}"
    if isinstance(value, bool):
        raise GradingError(says)
    if unit == COUNT:
        if not isinstance(value, int) or value < 0:
            raise GradingError(says)
        return float(value)
    if unit in (NUMBER, AMOUNT):
        if not isinstance(value, int | float) or not math.isfinite(value) or (
                unit == AMOUNT and value < 0):
            raise GradingError(says)
        return float(value)
    if unit == SHARE:
        found = _SHARE.fullmatch(value) if isinstance(value, str) else None
        if found is None:
            raise GradingError(says)
        return float(found.group(1))
    # The checks import this module, so their parsers are reached at the call: the
    # one grammar for a duration and for a size, and their own refusals.
    from little_sister.checks.base import parse_duration, parse_size
    try:
        if unit == DURATION:
            seconds = parse_duration(value, 0)
        else:
            return float(parse_size(value, 0))
    except GradingError:
        raise
    except CheckError as error:
        raise GradingError(f"{where}: {error}") from error
    if seconds < 1:
        raise GradingError(says)
    return float(seconds)


#: The units a configured size is written back in, largest first: the binary ones,
#: then the decimal ones, as the library's size grammar reads them.
_SIZE_WRITTEN = (("PiB", 1024 ** 5), ("TiB", 1024 ** 4), ("GiB", 1024 ** 3),
                 ("MiB", 1024 ** 2), ("KiB", 1024), ("PB", 10 ** 15),
                 ("TB", 10 ** 12), ("GB", 10 ** 9), ("MB", 10 ** 6), ("kB", 10 ** 3))


def _written(unit: str, value: float) -> str:
    """A level as its unit writes it back: a duration as it is configured, a size in
    the largest unit it divides exactly — as somebody would have typed it — a share
    with its sign."""
    if unit == DURATION:
        return format_duration(int(value))
    if unit == SIZE:
        size = int(value)
        for name, factor in _SIZE_WRITTEN:
            if size and size % factor == 0:
                return f"{size // factor} {name}"
        return format_weight(size) if size >= 1024 else f"{size} B"
    if unit == SHARE:
        return f"{value:g}%"
    if unit == AMOUNT:
        return f"{value:,.2f}"
    return f"{value:g}"


def _words(value: Mapping[Any, Any], where: str) -> Words:
    """A map as it is written: each word once, folded, and a code a line can carry."""
    codes: list[tuple[str, StatusCode]] = []
    seen: dict[str, str] = {}
    for word, code in value.items():
        if not isinstance(word, str) or not word.strip():
            raise GradingError(f"{where} names {word!r}, which is no word")
        earlier = seen.get(fold(word))
        if earlier is not None:
            raise GradingError(
                f"{where} names {earlier!r} and {word!r}, which are one word: a map "
                f"matches a word with its case and the spaces around it folded")
        seen[fold(word)] = word
        codes.append((word.strip(), _code(code, f"{where}.{word.strip()}")))
    return Words(tuple(codes))


def _code(value: object, where: str) -> StatusCode:
    """A code a map gives a word, or a set gives what it does not accept."""
    name = value.name if isinstance(value, StatusCode) else value
    if isinstance(name, str):
        for code in _MAP_CODES:
            if code.name == name.strip().upper():
                return code
    raise GradingError(f"{where} is OK, WARN or ERROR, not {value!r}")


def _accepted(value: object, where: str,
              like: tuple[int | str, ...]) -> tuple[int | str, ...]:
    """A set's values, one or a list of them, each of the kind its declared default
    holds: a whole number where those are, as a status a deployment may quote."""
    items = list(value) if isinstance(value, list | tuple) else [value]
    if not items:
        raise GradingError(f"{where} names no value, and an empty set passes nothing")
    numbers = bool(like) and all(isinstance(item, int) for item in like)
    values: list[int | str] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int | str):
            raise GradingError(f"{where} holds {item!r}, which is no value to accept")
        if numbers and not isinstance(item, int):
            if not item.strip().isdigit():
                raise GradingError(f"{where} holds {item!r}, and its values are "
                                   f"whole numbers")
            item = int(item)
        if not numbers and like and not isinstance(item, str):
            raise GradingError(f"{where} holds {item!r}, and its values are words")
        values.append(item)
    return tuple(values)


def _reason(block: Mapping[str, Any], key: str, where: str) -> str:
    value = block.get(key)
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise GradingError(f"{_at(where, key)} must be one sentence, not {value!r}")
    return value.strip()


def _at(where: str, key: str) -> str:
    """A key as a refusal names it: in its block, or alone among the check's own."""
    return f"{where} {key!r}" if where else repr(key)


# --- what a grading says of a value -----------------------------------------------


@dataclass(frozen=True)
class Verdict:
    """What one grading says of one value (decision 1): its full name — empty where
    it decided nothing, a pair that holds no level, switched off or never given one,
    so that the line names no grading — the code, the sentence the deployment wrote
    for it where the grading fired — a code WARN or ERROR — and the name of the rule
    whose keys judged the value, an ``OK`` included, where one did (ADR-0129
    decision 6). ``against`` is what a value that
    did not pass was held against, as the configuration writes it — the level a
    pair's value went beyond (``20m``, ``90%``), a set's accepted values
    (``200, 204``) — for a line that says it; empty where the value passed, and for a
    map, whose word says it."""

    grading: str
    code: StatusCode
    reason: str = ""
    rule: str = ""
    against: str = ""

    def entry(self, text: str, *, slug: str = "", coded: bool = False) -> Entry:
        """The line a type writes as a sentence of its own under this verdict:
        ``text``, followed by the grading's sentence where one fired — escaped, since
        a deployment wrote it — and named by the grading it came from. ``slug`` is
        derived from the text where none is given, as a line of prose's is; ``coded``
        makes the verdict's code the line's own."""
        said = f"{text} — {plain(self.reason)}" if self.reason else text
        return Entry(slug or derived_slug(said), said,
                     code=self.code if coded else None, grading=self.grading)


def held_against(grading: Grading, setting: Setting, code: StatusCode) -> str:
    """What a value ``setting`` gave ``code`` was held against, as the configuration
    writes it: the level a pair's value went beyond, or a set's accepted values —
    empty where it passed, and for a map or a judgment."""
    if code not in (StatusCode.WARN, StatusCode.ERROR):
        return ""
    if isinstance(setting, Levels):
        level = setting.error if code == StatusCode.ERROR else setting.warn
        return "" if level is None else grading.written(level)
    if isinstance(setting, Accepted):
        return ", ".join(str(value) for value in setting.values)
    return ""


def judge(grading: Grading, setting: Setting, value: object,
          code: StatusCode | None = None) -> StatusCode:
    """The code ``setting`` gives ``value`` under ``grading``: a maximum fails above
    its level and a minimum below it, a map gives the word its code and any word it
    does not name WARN, a set passes what it holds, and a judgment is the code its
    type handed over."""
    if isinstance(setting, Levels):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise GradingError(
                f"{grading.name} grades a number, and was handed {value!r}")
        # A pair switched off holds no level, so nothing below fires for it.
        if grading.most:
            if setting.error is not None and value > setting.error:
                return StatusCode.ERROR
            if setting.warn is not None and value > setting.warn:
                return StatusCode.WARN
            return StatusCode.OK
        if setting.error is not None and value < setting.error:
            return StatusCode.ERROR
        if setting.warn is not None and value < setting.warn:
            return StatusCode.WARN
        return StatusCode.OK
    if isinstance(setting, Words):
        found = setting.code_of(value)
        return StatusCode.WARN if found is None else found
    if isinstance(setting, Accepted):
        return StatusCode.OK if value in setting.values else grading.failing
    if code is None or code not in _MAP_CODES:
        raise GradingError(
            f"{grading.name} is a judgment its type makes, and is handed its code: "
            f"OK, WARN or ERROR, not {code!r}")
    return code


def since_ok(at: datetime, kept: Iterable[tuple[datetime, StatusCode | None]]
             ) -> tuple[float, bool]:
    """The window's value (decision 8): how long before ``at`` the newest reading in
    ``kept`` that stood OK was taken — or, where none did, the oldest the window holds,
    so that what it measures is the time the window shows no OK reading for — and
    whether one in it stood OK. ``kept`` is the subject's readings up to and including
    the one graded, each at its own time with the code it landed with; one taken after
    ``at`` is not that reading's window (decision 7)."""
    window = [(when, code) for when, code in kept if when <= at]
    if not window:
        return 0.0, False
    stood = [when for when, code in window if code == StatusCode.OK]
    start = max(stood) if stood else min(when for when, _ in window)
    return (at - start).total_seconds(), bool(stood)


def worst(*verdicts: Verdict) -> Verdict:
    """The verdict of a line two or more gradings judged: the worst code, named by the
    first grading that gave it and named itself — one that decided nothing gives a
    line no name while another that graded it is there; the sentences of every
    grading that fired, in the order given; and the rule whose keys judged any of
    them (ADR-0129 decision 6)."""
    if not verdicts:
        raise GradingError("worst() is handed the verdicts of a line, and was handed "
                           "none")
    graded = [verdict for verdict in verdicts if verdict.code in _MAP_CODES]
    code = (worst_of(verdict.code for verdict in graded) if graded
            else verdicts[0].code)
    at_code = [verdict for verdict in verdicts if verdict.code == code]
    deciding = next((verdict for verdict in at_code if verdict.grading), at_code[0])
    reasons = [verdict.reason for verdict in verdicts if verdict.reason]
    rule = next((verdict.rule for verdict in verdicts if verdict.rule), "")
    return Verdict(deciding.grading, code, " ".join(reasons), rule, deciding.against)
