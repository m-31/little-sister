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
``{unit, label}`` where a label is wanted. Anything else is refused, and the
refusal names the place — the library turns it into a load failure naming the file.

**A unit is free text**, printed beside a value and as the axis label, and nothing
is ever refused for its unit, because a wrong one costs a label and never a poisoned
series. Two strings mean more, because the family already writes them: ``ms`` and
``s`` are written as a span — through :func:`~little_sister.spans.format_span`, so
1,850 ms reads ``1.9 s`` — and name their unit in every value, so an axis in either
needs no label of its own. ``B`` reads as a plain label until a curve needs it
formatted; nothing that configures it changes meaning when it is.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from little_sister.reasons import record_leaves
from little_sister.spans import format_span

#: The units the page writes as a span, and what one of each is in seconds.
SPAN_UNITS = {"ms": 0.001, "s": 1.0}

#: The keys the mapping form takes. `unit` is required: a measure is a number *in*
#: something, and a relabeled default restates its unit rather than inheriting it,
#: because an entry the configuration names is taken whole.
_ENTRY_KEYS = frozenset({"unit", "label"})


class MeasureError(ValueError):
    """A ``measures:`` block, or a type's ``measure_defaults``, of another shape.
    The message names the place; the library refuses the load with it."""


@dataclass(frozen=True)
class Measure:
    """One declared measure: the field it reads, its unit, and what its curve is
    titled — the field's own name where the declaration gave no label."""

    field: str
    unit: str
    label: str

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
        """The unit an axis prints once as its label — none for a span unit, whose
        every tick names its own (``1.9 s`` under an axis labeled ``ms`` would
        contradict it)."""
        return "" if self.unit in SPAN_UNITS else self.unit

    def write(self, value: float, *, bare: bool = False) -> str:
        """``value`` as a reader reads it: a span unit as a span, any other number
        at about three significant figures with the unit beside it — or, ``bare``,
        without it, for an axis that prints it once."""
        if self.unit in SPAN_UNITS:
            if value < 0:
                return "-" + format_span(-value * SPAN_UNITS[self.unit])
            return format_span(value * SPAN_UNITS[self.unit])
        number = _number(value)
        return number if bare or not self.unit else f"{number} {self.unit}"


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
                f"timing.total_ms)")
        measures[name] = _entry(name, entry, where=f"{where}.{name}",
                                removals=removals)
    return measures


def _is_field_name(name: object) -> bool:
    return (isinstance(name, str) and name == name.strip()
            and all(part.strip() for part in name.split(".")))


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
                f"{where!r} takes 'unit' and 'label', not {', '.join(unknown)}")
        unit = entry.get("unit")
        if not isinstance(unit, str):
            raise MeasureError(
                f"{where!r} must give its 'unit' as text, not {unit!r}")
        label = entry.get("label")
        if label is not None and not isinstance(label, str):
            raise MeasureError(f"'{where}.label' must be text, not {label!r}")
        return Measure(name, unit, label or name)
    raise MeasureError(
        f"{where!r} must be a unit (text) or {{unit, label}}, not {entry!r}")


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
