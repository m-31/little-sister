"""Reading values out of a **decoded bag** — a YAML config block or a JSON API
payload, anything ``yaml.safe_load`` / ``json.loads`` hands back as nested
``dict``/``list``/scalars.

Every value in such a bag is typed ``Any``, and ``Any`` is assignable to anything, so
``mypy --strict`` cannot help at the point of use: ``plain(payload["number"])``
type-checks cleanly and then fails at runtime when GitHub answers with an int. The
fix is to narrow **where ``Any`` enters** rather than at the last helper before
rendering, and these readers are that seam — each one takes the bag and always
returns the declared type (see ADR-0026).

``*path`` walks nested mappings, so the ``(x.get("a") or {}).get("b")`` idiom
collapses to one call::

    values.text(alert, "security_advisory", "severity", default="unknown")
    values.real(spec, "warn", default=80.0, where="thresholds.disk")
    values.number(issue, "number", required=True)

**Policy** (ADR-0026), chosen for a monitoring tool where a silently wrong *green*
is the worst outcome:

* An **absent** value (missing key, a non-mapping on the way, or an explicit
  ``null``) yields ``default`` — a field the payload stopped sending is usually
  cosmetic, and a missing label should not take out the whole check.
* ``required=True`` turns absence into a :class:`CheckError` instead. Use it for
  **structural** fields whose absence means the shape changed under you.
* A value that is **present but uncoercible** always raises :class:`CheckError`,
  never falls back — a ``warn: "abc"`` in a config is a typo, and defaulting it
  would hide the mistake behind a plausible number. This matches
  :func:`little_sister.checks.base.parse_duration`.

``where`` prefixes the path in error messages, so a caller that has already walked
part of the way (or knows the block's name) still produces
``thresholds.disk.warn: …`` rather than a bare ``warn: …``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from little_sister.errors import CheckError

#: The check-authoring surface of this module (architecture.md §11, ADR-0049) —
#: everything public here is promised, so the two cannot drift apart.
__all__ = ["flag", "number", "real", "rows", "text"]

#: Sentinel for "not in the bag at all" — distinct from a present ``None``, which is
#: treated the same way but must not be confused with a legitimate falsy value.
_MISSING: Final = object()

#: What a scalar reader will coerce from. Deliberately narrow: a ``dict`` or ``list``
#: where a number was expected is a shape error, not something to stringify.
_SCALARS: Final = (int, float, str)


def _walk(bag: object, path: tuple[str, ...]) -> object:
    """Follow ``path`` through nested mappings, or ``_MISSING`` as soon as a step is
    absent or lands on something that is not a mapping."""
    current: object = bag
    for key in path:
        if not isinstance(current, Mapping):
            return _MISSING
        if key not in current:
            return _MISSING
        current = current[key]
    return current


def _label(path: tuple[str, ...], where: str) -> str:
    """The dotted name of the value, for an error message."""
    return ".".join(part for part in (where, *path) if part) or "value"


def _read(bag: object, path: tuple[str, ...], where: str, required: bool) -> object:
    """The raw value, or ``_MISSING`` when absent (``required`` makes that fatal).
    A present ``None`` counts as absent — YAML and JSON both use it for 'unset'."""
    value = _walk(bag, path)
    if value is _MISSING or value is None:
        if required:
            raise CheckError(f"{_label(path, where)}: required value is missing")
        return _MISSING
    return value


def text(bag: object, *path: str, default: str = "", required: bool = False,
         where: str = "") -> str:
    """A display string. Anything present is stringified — the *escaping* for
    Markdown is a separate step at the point of rendering
    (:func:`little_sister.checks.base.plain`), never stored here: a value that has
    been escaped can no longer be put in a URL."""
    value = _read(bag, path, where, required)
    return default if value is _MISSING else str(value)


def number(bag: object, *path: str, default: int = 0, required: bool = False,
           where: str = "") -> int:
    """A whole number — an identifier, a count, a cap. Returns a real ``int``, so
    the value can go into a URL or a comparison without a stringify-and-hope."""
    value = _read(bag, path, where, required)
    if value is _MISSING:
        return default
    if not isinstance(value, _SCALARS):
        raise CheckError(f"{_label(path, where)}: expected a whole number, got "
                         f"{type(value).__name__}")
    try:
        return int(value)
    except ValueError as error:
        raise CheckError(f"{_label(path, where)}: expected a whole number, got "
                         f"{value!r}") from error


def real(bag: object, *path: str, default: float = 0.0, required: bool = False,
         where: str = "") -> float:
    """A number that may have a fraction — a threshold, a percentage, a duration."""
    value = _read(bag, path, where, required)
    if value is _MISSING:
        return default
    if not isinstance(value, _SCALARS):
        raise CheckError(f"{_label(path, where)}: expected a number, got "
                         f"{type(value).__name__}")
    try:
        return float(value)
    except ValueError as error:
        raise CheckError(f"{_label(path, where)}: expected a number, got "
                         f"{value!r}") from error


def flag(bag: object, *path: str, default: bool = False) -> bool:
    """A boolean. YAML and JSON both decode ``true`` / ``false`` to real ``bool``,
    so this is a plain truthiness read — note that the *string* ``"false"`` is
    therefore true, exactly as it would be in the ``if bag.get(key):`` it replaces.
    """
    value = _read(bag, path, where="", required=False)
    return default if value is _MISSING else bool(value)


def rows(bag: object, *path: str, where: str = "") -> list[Any]:
    """A list of sub-bags — the rows of an API response or a config sequence.
    Absent yields ``[]``; something present that is **not** a list raises, since a
    scalar where a collection belongs means the shape is not what the caller thinks.

    The elements stay ``Any``: they are bags in their own right, to be read with
    these same functions. This is the one place ``Any`` legitimately leaves this
    module."""
    value = _read(bag, path, where, required=False)
    if value is _MISSING:
        return []
    if not isinstance(value, list):
        raise CheckError(f"{_label(path, where)}: expected a list, got "
                         f"{type(value).__name__}")
    return value
