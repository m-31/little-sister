"""What a measure is, where it is declared, and how its value is written
(ADR-0092).

A **measure** is a projection over a record, chosen when it is drawn rather than
typed when it is written (ADR-0085): a field of what a check read, named by the
dotted path its node's record list spells it with, and the unit its numbers are in.
Which fields a check's readings are drawn by is declared in two places, merged per
field:

* the **type** passes ``measure_defaults`` to its constructor — what a field of its
  record means, and in which unit, is its knowledge;
* the **deployment** writes ``measures:`` in the check's YAML — whether a field is
  drawn is its choice. A field it names takes its entry, every other keeps the
  type's, ``field: null`` removes one, and an absent or empty block leaves the
  defaults standing: the resolution a deployment already knows from ``subnodes:``
  (ADR-0025).

Both are the same shape: a mapping of a field's name to its **unit**, or to
``{unit, label, node}`` where a label or a node is wanted. Anything else is refused,
and the refusal names the place — the library turns it into a load failure naming
the file.

**A measure names the node its curve stands on** (ADR-0096 decision 1): ``node``, a
path relative to the check's own node — ``memory``, ``disk/root`` — and the check's
own node where it names none. **A ``*`` picks a key** (decision 2): a record keys the
things it counts by the names of the nodes they become — ``volumes: {root: …}`` — and
``volumes.*.pct`` with ``node: disk/*`` is a curve for every key the kept readings
hold, each on its own node, the key standing in for the ``*`` in the node and the
label too. It picks and never computes: :meth:`Measure.expand` turns one declaration
into the measures it stands for, each a plain projection again.

**A unit is free text**, printed beside a value and as the axis label, and nothing
is ever refused for its unit, because a wrong one costs a label and never a poisoned
series. Seven strings mean more, because the family already writes them: ``ms`` and
``s`` are written as a span — through :func:`~little_sister.spans.format_span`, so
1,850 ms reads ``1.9 s`` — and ``B``, ``KiB``, ``MiB``, ``GiB`` and ``TiB`` as a size,
through :func:`~little_sister.limits.format_weight`, so 19,169,728 KiB reads
``18.3 GiB`` (decision 3). Each names its unit in every value, so an axis in any of
them needs no label of its own. ``kB``, ``MB`` and ``GB`` are not among them: whether
``MB`` is 10⁶ or 2²⁰ is the guess a family unit is there to remove.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from little_sister.limits import format_weight
from little_sister.reasons import record_leaves
from little_sister.spans import format_span

#: The units the page writes as a span, and what one of each is in seconds.
SPAN_UNITS = {"ms": 0.001, "s": 1.0}

#: The units the page writes as a size, and how many bytes one of each is: the
#: binary multiples, as the family writes them (ADR-0096 decision 3).
SIZE_UNITS = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3,
              "TiB": 1024 ** 4}

#: The segment a declaration writes for the key a record counts a thing by
#: (ADR-0096 decision 2).
PICK = "*"

#: The keys the mapping form takes. `unit` is required: a measure is a number *in*
#: something, and a relabeled default restates its unit rather than inheriting it,
#: because an entry the configuration names is taken whole.
_ENTRY_KEYS = frozenset({"unit", "label", "node", "axis_to"})


class MeasureError(ValueError):
    """A ``measures:`` block, or a type's ``measure_defaults``, of another shape.
    The message names the place; the library refuses the load with it."""


@dataclass(frozen=True)
class Measure:
    """One declared measure: the field it reads, its unit, what its curve is
    titled — the field's own name where the declaration gave no label — and the
    node its curve stands on, relative to the check's own node: empty for that node
    itself (ADR-0096 decision 1). ``axis_to`` is where its value axis reaches
    whatever its readings are (ADR-0117) — 100 for a percent of a whole, so that two
    curves of one kind compare — or ``None`` for an axis that ends past its own
    highest reading. It is no limit: a reading above it is drawn, on a longer axis."""

    field: str
    unit: str
    label: str
    node: str = ""
    axis_to: float | None = None

    def read(self, record: object) -> object:
        """The value this measure projects out of ``record``: the field of that
        dotted name, or ``None`` where the record has no such field — a projection
        reads a missing key as an empty one (ADR-0085 decision 3). A name that
        stops at a mapping is not a field, and reads as ``None`` too."""
        for name, _key, value in record_leaves(record):
            if name == self.field:
                return value
        return None

    @property
    def axis_unit(self) -> str:
        """The unit an axis prints once as its label — none for a span or a size
        unit, whose every tick names its own (``1.9 s`` under an axis labeled ``ms``
        would contradict it)."""
        named = self.unit in SPAN_UNITS or self.unit in SIZE_UNITS
        return "" if named else self.unit

    def write(self, value: float, *, bare: bool = False) -> str:
        """``value`` as a reader reads it: a span unit as a span, a size unit as a
        size, any other number at about three significant figures with the unit
        beside it — or, ``bare``, without it, for an axis that prints it once.

        A size ``bare`` is an axis tick, and a tick lands on a whole unit (ADR-0096
        decision 3): it says ``512 MiB``, not the tenth of nothing a reading's
        ``512.0 MiB`` carries."""
        if self.unit in SPAN_UNITS:
            if value < 0:
                return "-" + format_span(-value * SPAN_UNITS[self.unit])
            return format_span(value * SPAN_UNITS[self.unit])
        if self.unit in SIZE_UNITS:
            if value < 0:
                return "-" + self.write(-value, bare=bare)
            size = format_weight(round(value * SIZE_UNITS[self.unit]))
            return size.replace(".0 ", " ") if bare else size
        number = _number(value)
        return number if bare or not self.unit else f"{number} {self.unit}"

    def expand(self, records: Iterable[object]) -> list[Measure]:
        """The measures this declaration stands for over ``records``: itself, where
        its field has no ``*``; and otherwise one for every key the mapping at the
        ``*`` holds in any of them, in the order the keys first appear, the key
        standing in for the ``*`` in the field, the node and the label (ADR-0096
        decision 2). A record without that mapping holds no key."""
        parts = self.field.split(".")
        if PICK not in parts:
            return [self]
        above = parts[:parts.index(PICK)]
        keys: dict[str, None] = {}
        for record in records:
            found = _mapping_at(record, above)
            if found is not None:
                keys.update(dict.fromkeys(str(key) for key in found))
        return [self._picked(key) for key in keys]

    def _picked(self, key: str) -> Measure:
        """This measure with ``key`` for its ``*``."""
        field = ".".join(key if part == PICK else part
                         for part in self.field.split("."))
        node = "/".join(key if part == PICK else part
                        for part in self.node.split("/")) if self.node else ""
        return Measure(field, self.unit, self.label.replace(PICK, key), node,
                       self.axis_to)


def _mapping_at(record: object, path: list[str]) -> Mapping[object, object] | None:
    """The mapping ``record`` holds at ``path``, a key at a time, or ``None``."""
    found: object = record
    for key in path:
        if not isinstance(found, Mapping):
            return None
        found = found.get(key)
    return found if isinstance(found, Mapping) else None


def _number(value: float) -> str:
    """A number as the page writes one that has no unit of its own to be written
    in: whole numbers in full with thousands separators, fractions at three
    significant figures and never in exponent form."""
    if float(value).is_integer():
        return f"{int(value):,}"
    places = max(0, 2 - math.floor(math.log10(abs(value))))
    text = f"{value:,.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def read_measures(block: object, *, where: str,
                  removals: bool = True) -> dict[str, Measure | None]:
    """A ``measures:`` block — or a type's ``measure_defaults`` — as field name to
    :class:`Measure`, with ``None`` for a field the block removes.

    ``where`` is how the refusal names the place (``measures``,
    ``measure_defaults``). ``removals`` is whether ``null`` is allowed: it is in a
    deployment's block, where it takes a default back, and it is not in a type's
    declaration, which has nothing beneath it to remove. A :class:`Measure` already
    read is taken as it stands, so a block read once can be handed on.
    """
    if block is None:
        return {}
    if not isinstance(block, Mapping):
        raise MeasureError(
            f"{where!r} must map a record field's dotted name to its unit, or to "
            f"{{unit, label}} — not {type(block).__name__}")
    measures: dict[str, Measure | None] = {}
    for name, entry in block.items():
        if not _is_field_name(name):
            raise MeasureError(
                f"{where!r} names {name!r}, which is not a record field's dotted "
                f"name (as the node's record list spells it, e.g. response_ms or "
                f"timing.total_ms — or with one {PICK} for the key a thing is "
                f"counted by, e.g. volumes.{PICK}.pct)")
        measures[name] = _entry(name, entry, where=f"{where}.{name}",
                                removals=removals)
    return measures


def _is_field_name(name: object) -> bool:
    """A dotted name, each segment non-empty, and at most one segment ``*`` —
    a whole one, never a ``*`` inside a segment (ADR-0096 decision 2)."""
    if not isinstance(name, str) or name != name.strip():
        return False
    parts = name.split(".")
    return (all(part.strip() for part in parts)
            and all(PICK not in part or part == PICK for part in parts)
            and parts.count(PICK) <= 1)


def _is_node_path(node: str) -> bool:
    """A path from the check's own node: segments joined by ``/``, none of them
    empty, ``.`` or ``..``, and a ``*`` only as a whole segment, once."""
    segments = node.split("/")
    return (all(segment.strip() and segment not in (".", "..")
                for segment in segments)
            and all(PICK not in segment or segment == PICK for segment in segments)
            and segments.count(PICK) <= 1)


def _is_axis_end(value: object) -> bool:
    """A positive, finite number — and not a boolean, which Python counts as one."""
    return (isinstance(value, int | float) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _entry(name: str, entry: object, *, where: str,
           removals: bool) -> Measure | None:
    if isinstance(entry, Measure):
        return entry
    if entry is None:
        if removals:
            return None
        raise MeasureError(
            f"{where!r} declares nothing: a default is a unit, or {{unit, label}}")
    if isinstance(entry, str):
        return Measure(name, entry, name)
    if isinstance(entry, Mapping):
        unknown = sorted(str(key) for key in entry if key not in _ENTRY_KEYS)
        if unknown:
            raise MeasureError(
                f"{where!r} takes 'unit', 'label', 'node' and 'axis_to', not "
                f"{', '.join(unknown)}")
        unit = entry.get("unit")
        if not isinstance(unit, str):
            raise MeasureError(
                f"{where!r} must give its 'unit' as text, not {unit!r}")
        label = entry.get("label")
        if label is not None and not isinstance(label, str):
            raise MeasureError(f"'{where}.label' must be text, not {label!r}")
        node = entry.get("node", "")
        if "node" in entry and not (isinstance(node, str) and _is_node_path(node)):
            raise MeasureError(
                f"'{where}.node' must be a path from the check's own node — "
                f"memory, disk/root — not {node!r}")
        picks = PICK in name.split(".")
        if not picks and (PICK in node or PICK in (label or "")):
            raise MeasureError(
                f"{where!r} writes {PICK} in its node or its label, and its field "
                f"has no {PICK} to stand for")
        axis_to = entry.get("axis_to")
        if "axis_to" in entry and not _is_axis_end(axis_to):
            raise MeasureError(
                f"'{where}.axis_to' must be a number above zero — where the value "
                f"axis reaches, 100 for a percent of a whole — not {axis_to!r}")
        return Measure(name, unit, label or name, node,
                       None if axis_to is None else float(axis_to))
    raise MeasureError(
        f"{where!r} must be a unit (text) or {{unit, label, node}}, not {entry!r}")


def resolve_measures(configured: Mapping[str, Measure | None],
                     declared: Mapping[str, Measure | None]) -> dict[str, Measure]:
    """What a check draws: the type's ``declared`` defaults, with the deployment's
    ``configured`` block merged over them **per field** — a field it names takes its
    entry, ``None`` removes it, every other field keeps the default. The defaults
    come first in the order the type declared them, and a field only the
    configuration names follows in its own order."""
    merged: dict[str, Measure] = {name: measure for name, measure in declared.items()
                                  if measure is not None}
    for name, measure in configured.items():
        if measure is None:
            merged.pop(name, None)
        else:
            merged[name] = measure
    return merged
