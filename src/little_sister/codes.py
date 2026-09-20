"""The status vocabulary — a leaf module with no imports of its own.

`StatusCode` began life in `status.py`, which imports `reasons.py` for the keyed
reason entries (ADR-0036). When an entry grew a code of its own (ADR-0042),
`reasons.py` needed the vocabulary too — and importing it back from `status.py`
would be a cycle. So the vocabulary lives here, below both; `status.py` re-exports
it, so `from little_sister.status import StatusCode` — the published spelling
(architecture.md §11, `implementing-checks.md`) — keeps working unchanged.

The vocabulary is **closed** (ADR-0032 decision 4): a new reason not to count a
node is a contribution rule plus a marker, never a sixth code, because every
consumer switches on these five.
"""
from __future__ import annotations

from collections.abc import Iterable
from enum import Enum, auto


class StatusCode(Enum):
    """These are the possible status codes."""
    MAINTENANCE = auto()
    OK = auto()
    WARN = auto()
    ERROR = auto()
    UNDEFINED = auto()


# Severity used when accumulating a parent's status (ADR-0039). Only OK/WARN/ERROR
# are ranked; MAINTENANCE and UNDEFINED are excluded *before* this map is used.
_SEVERITY: dict[StatusCode, int] = {
    StatusCode.OK: 0,
    StatusCode.WARN: 1,
    StatusCode.ERROR: 2,
}


#: The codes that carry a severity, and the only ones a change between is a change of
#: mind. `MAINTENANCE` is an admin's act and `UNDEFINED` is *nothing has reported*, so
#: a move touching either is not a node changing what it thinks.
RANKED = frozenset(_SEVERITY)


def worst_of(codes: Iterable[StatusCode]) -> StatusCode:
    """The most severe of `OK` / `WARN` / `ERROR` codes (others must be excluded)."""
    return max(codes, key=lambda code: _SEVERITY[code])


def escalates(old: StatusCode, new: StatusCode) -> bool:
    """Whether moving from ``old`` to ``new`` is a **worsening** of a ranked code.

    The one question the damping counter asks, given a name so that the rule is in
    one place rather than spelled out at the call site. Only `OK` / `WARN` / `ERROR`
    are ranked, so a move that touches `UNDEFINED` or `MAINTENANCE` is not an
    escalation and is never delayed: *nothing has reported* and *an admin silenced
    this* are not claims a confidence counter has anything to say about, and holding
    one back would delay a node's very first reading.
    """
    if old not in _SEVERITY or new not in _SEVERITY:
        return False
    return _SEVERITY[new] > _SEVERITY[old]


def is_valid_status_code(value: str) -> bool:
    return value.upper() in StatusCode.__members__
