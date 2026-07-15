from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime
from enum import Enum, auto
from typing import Self


class StatusCode(Enum):
    """These are the possible status codes."""
    MAINTENANCE = auto()
    OK = auto()
    WARN = auto()
    ERROR = auto()
    UNDEFINED = auto()


# Severity used when accumulating a parent's status (ADR-0004). Only OK/WARN/ERROR
# are ranked; MAINTENANCE and UNDEFINED are excluded *before* this map is used.
_SEVERITY: dict[StatusCode, int] = {
    StatusCode.OK: 0,
    StatusCode.WARN: 1,
    StatusCode.ERROR: 2,
}


def worst_of(codes: Iterable[StatusCode]) -> StatusCode:
    """The most severe of `OK` / `WARN` / `ERROR` codes (others must be excluded)."""
    return max(codes, key=lambda code: _SEVERITY[code])


def effective_code(own: StatusCode, child_codes: Iterable[StatusCode]) -> StatusCode:
    """Roll a node's effective status up from its own code and its children's, per
    ADR-0004: `MAINTENANCE` cancels the subtree; `UNDEFINED` is ignored; otherwise
    the worst of `ERROR > WARN > OK`; nothing counted is `UNDEFINED`.
    """
    if own == StatusCode.MAINTENANCE:
        return StatusCode.MAINTENANCE
    counted: list[StatusCode] = []
    if own != StatusCode.UNDEFINED:
        counted.append(own)
    for code in child_codes:
        if code in (StatusCode.MAINTENANCE, StatusCode.UNDEFINED):
            continue
        counted.append(code)
    return worst_of(counted) if counted else StatusCode.UNDEFINED


def is_valid_status_code(value: str) -> bool:
    return value.upper() in StatusCode.__members__


# --- Node paths (ADR-0016): absolute, '/'-separated; a segment may contain '.'. ---

PATH_SEP = "/"


def split_path(path: str) -> list[str]:
    """The non-empty segments of a path (leading / trailing separators ignored)."""
    return [segment for segment in path.split(PATH_SEP) if segment]


def join_path(*parts: str) -> str:
    """Join segments / sub-paths into one **absolute** path (always a leading
    ``/``); ``join_path()`` is the root ``/``."""
    segments: list[str] = []
    for part in parts:
        segments.extend(split_path(part))
    return PATH_SEP + PATH_SEP.join(segments)


def leaf_name(path: str) -> str:
    """A node's own name — its last segment; ``""`` for the root."""
    segments = split_path(path)
    return segments[-1] if segments else ""


def parent_path(path: str) -> str:
    """The absolute path of ``path``'s parent (the root's parent is the root)."""
    return join_path(*split_path(path)[:-1])


def on_same_line(a: str, b: str) -> bool:
    """True when paths ``a`` and ``b`` lie on one root-to-leaf line — equal, or one a
    **segment-wise** ancestor of the other (so ``/x/disk`` relates to ``/x/disk/root``
    but not to ``/x/diskfoo``). Shared by check-discovery overlap (ADR-0015) and
    maintenance-coverage reaping (ADR-0014)."""
    sa, sb = split_path(a), split_path(b)
    shared = min(len(sa), len(sb))
    return sa[:shared] == sb[:shared]


def _coerce_code(code: StatusCode | str) -> StatusCode:
    """Accept a StatusCode or a valid (case-insensitive) status-code string."""
    if isinstance(code, StatusCode):
        return code
    if isinstance(code, str):
        if not is_valid_status_code(code):
            raise ValueError(f"Invalid status code: '{code}'")
        return StatusCode[code.upper()]
    raise TypeError(
        f"Status code must be a StatusCode instance or a valid status code "
        f"string, got {type(code).__name__} instead")


def _coerce_reason(reason: list[str] | str | None) -> list[str]:
    """Normalise a reason into a list of strings."""
    if reason is None:
        return []
    if isinstance(reason, str):
        return [reason]
    return list(reason)


class Status:
    """Status of a component or system. Nodes form a tree; see ADR-0004 for the
    roll-up semantics implemented by :meth:`get_status_code`."""

    def __init__(self, path: str, name: str | None = None,
                 code: StatusCode | str = StatusCode.UNDEFINED,
                 reason: list[str] | str | None = None):
        # `path` is the node's full, absolute location (ADR-0016); `name` is its last
        # segment, derived unless given explicitly (the root carries one).
        self.path = join_path(path)
        self._name = name if name is not None else leaf_name(self.path)
        self.code = _coerce_code(code)
        self.reason = _coerce_reason(reason)
        self.timestamp = datetime.now().isoformat()
        # Metadata inherited from the check (questions §3.6); set by the tree.
        self.description: str = ""
        self.frequency_seconds: int | None = None
        # Curated config the check ran with — display metadata, not status
        # (ADR-0013); Markdown, shown on the detail page.
        self.config: str = ""
        # Subject metadata: what this node *is* (location, kind, context), distinct
        # from `description` (what its check does). Markdown; seeded at startup from
        # nodes.yaml / the owning check (ADR-0012).
        self.about: str = ""
        # A short display label, briefer than `about` (ADR-0017); same sources. The
        # path/name identity stays the addressing key.
        self.title: str = ""
        # Sticky admin override: while True the engine must not overwrite the code.
        self.maintenance: bool = False
        self.__children: OrderedDict[str, Status] = OrderedDict()

    @property
    def name(self) -> str:
        """The node's own name — its last path segment (ADR-0016)."""
        return self._name

    def touch(self) -> None:
        """Update the observation timestamp without changing code or reason."""
        self.timestamp = datetime.now().isoformat()

    def __str__(self) -> str:
        suffix = ' - ' + ', '.join(self.reason) if self.reason else ''
        return f"{self.path}: {self.code.name.lower()}{suffix}"

    def update(self, code: StatusCode | str,
               reason: list[str] | str | None = None) -> None:
        """Record a fresh observation of this node.

        Updates the code and reason and re-stamps ``timestamp`` to now — the
        timestamp is the *observation* time, set by the check on each run
        (project.md §2.1).
        """
        self.code = _coerce_code(code)
        self.reason = _coerce_reason(reason)
        self.timestamp = datetime.now().isoformat()

    def get_status_code(self) -> StatusCode:
        """Effective status of this node, rolled up per ADR-0004:

        - severity order ``ERROR > WARN > OK``;
        - ``UNDEFINED`` (a not-yet-reported leaf) is ignored when accumulating;
        - ``MAINTENANCE`` cancels this node's whole subtree, and the node itself
          is ignored by its parent;
        - always returns a ``StatusCode`` and never downgrades.
        """
        return effective_code(
            self.code, (child.get_status_code() for child in self.__children.values()))

    def add_child(self, child: Self) -> None:
        """Add a child status to this status."""
        if not isinstance(child, Status):
            raise TypeError(
                f"Child must be an instance of Status, got "
                f"{type(child).__name__} instead")

        if parent_path(child.path) != self.path:
            raise ValueError(
                f"Child's path must sit directly under '{self.path}', got "
                f"'{child.path}' instead")

        self.__children[child.name] = child

    def get_children(self) -> list[Status]:
        return list(self.__children.values())
