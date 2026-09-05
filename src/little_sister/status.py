from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime
from typing import Self

# The vocabulary lives in the leaf module `codes` (it must be importable from
# `reasons.py`, which this module imports — ADR-0042); these re-exports keep the
# published spelling, `from little_sister.status import StatusCode`, working
# unchanged (architecture.md §11).
from little_sister.codes import StatusCode as StatusCode
from little_sister.codes import is_valid_status_code as is_valid_status_code
from little_sister.codes import worst_of as worst_of
from little_sister.reasons import ReasonInput, normalize


def effective_code(own: StatusCode, child_codes: Iterable[StatusCode]) -> StatusCode:
    """Roll a node's effective status up from its own code and its children's:
    `MAINTENANCE` cancels the subtree; `UNDEFINED` is ignored; otherwise the worst of
    `ERROR > WARN > OK`.

    **When nothing is counted, the answer depends on why.** A node whose children
    were all skipped because they are *pinned* reads `MAINTENANCE`, not `UNDEFINED` —
    the open edge case ADR-0032 left for this split, answered the way the
    same model already answers it one level down: a node whose *virtual* children
    (its reason entries) are all pinned reads `MAINTENANCE`. Real and virtual children
    must not read differently in one model, and "nothing under here is reporting
    because we silenced it" is a different fact from "nothing here has reported yet",
    which stays `UNDEFINED`.
    """
    if own == StatusCode.MAINTENANCE:
        return StatusCode.MAINTENANCE
    counted: list[StatusCode] = []
    silenced = False
    if own != StatusCode.UNDEFINED:
        counted.append(own)
    for code in child_codes:
        if code == StatusCode.MAINTENANCE:
            silenced = True
            continue
        if code == StatusCode.UNDEFINED:
            continue
        counted.append(code)
    if counted:
        return worst_of(counted)
    return StatusCode.MAINTENANCE if silenced else StatusCode.UNDEFINED


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


# The engine's self-heartbeat node (ADR-0005). The whole line is *reserved*: the
# loader rejects a custom check owning nodes on it, so the subtree stays
# engine-owned (leaving room for future engine children, e.g. connected
# satellites) and the dashboard can lift the node out of the card grid into the
# status strip (ADR-0024) knowing nothing user-configured hides behind it.
HEARTBEAT_PATH = "/little-sister"


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


class Status:
    """Status of a component or system. Nodes form a tree; see ADR-0039 for the
    roll-up semantics implemented by :meth:`get_status_code`."""

    def __init__(self, path: str, name: str | None = None,
                 code: StatusCode | str = StatusCode.UNDEFINED,
                 reason: ReasonInput = None, members: bool = False):
        # `path` is the node's full, absolute location (ADR-0016); `name` is its last
        # segment, derived unless given explicitly (the root carries one).
        self.path = join_path(path)
        self._name = name if name is not None else leaf_name(self.path)
        self.code = _coerce_code(code)
        # Reasons are keyed entries (ADR-0036). `reason_entries` is the one internal
        # form; `reason` stays the list of texts every existing surface reads, now
        # as a view onto it — so nothing moved when the key arrived.
        self.reason_entries, self.members = normalize(reason, members)
        # The observation time — when the check behind this node ran. ``None`` until
        # the first :meth:`update` / :meth:`touch`, so *having* a timestamp means a
        # check has written the node; construction never stamps (ADR-0027).
        self.timestamp: str | None = None
        # Metadata inherited from the check (questions §3.6); set by the tree.
        self.description: str = ""
        self.frequency_seconds: int | None = None
        # Curated config the check ran with — display metadata, not status
        # (ADR-0013); Markdown, shown on the detail page.
        self.config: str = ""
        # What the run *found*, as against what it ran *with* (ADR-0044): the
        # outputs field beside `config`, written through on every run, Markdown,
        # shown on the node's own page and never on a card. Never a status claim —
        # anything that should alarm is a reason.
        self.report: str = ""
        # Subject metadata: what this node *is* (location, kind, context), distinct
        # from `description` (what its check does). Markdown; seeded at startup from
        # nodes.yaml / the owning check (ADR-0012).
        self.about: str = ""
        # A short display label, briefer than `about` (ADR-0017); same sources. The
        # path/name identity stays the addressing key.
        self.title: str = ""
        # A declared rank among this node's siblings (ADR-0055); the snapshot sorts
        # by `(order, name)`, and an undeclared rank reads 0. `None` means **nobody
        # said**, which is what keeps a configured `order: 0` distinguishable from
        # silence — a deployment overruling a rank the check declared has to be able
        # to name the default value like any other.
        self.order: int | None = None
        # "This node's quiet lines are still information" (ADR-0063) — display
        # metadata like the three above, seeded from the same sources, and never
        # status: it says a density mechanism must not trade the node's reason
        # lines away for being quiet. `None` means **nobody said**, which is what
        # keeps a `nodes.yaml` `show_when_quiet: false` — a deployment taking back
        # what a check declared — distinguishable from silence.
        self.show_when_quiet: bool | None = None
        # The marker that an admin pin is on this node (ADR-0032 rule 4, ADR-0041).
        # It is *not* sticky and holds no value: the check keeps writing underneath
        # it and the snapshot derives MAINTENANCE from it, so the node never forgets
        # what it is silencing (rule 3 — a policy is not implemented by writing a
        # different value into the tree).
        self.maintenance: bool = False
        self.__children: OrderedDict[str, Status] = OrderedDict()

    @property
    def name(self) -> str:
        """The node's own name — its last path segment (ADR-0016)."""
        return self._name

    @property
    def reason(self) -> list[str]:
        """The reason texts, in the check's order — what events, history and every
        rendered surface carry. The slugs live on :attr:`reason_entries`."""
        return [entry.text for entry in self.reason_entries]

    def touch(self) -> None:
        """Record a fresh observation without changing code or reason — stamps
        ``timestamp`` to now (ADR-0027)."""
        self.timestamp = datetime.now().isoformat()

    def __str__(self) -> str:
        suffix = ' - ' + ', '.join(self.reason) if self.reason else ''
        return f"{self.path}: {self.code.name.lower()}{suffix}"

    def update(self, code: StatusCode | str, reason: ReasonInput = None,
               members: bool = False) -> None:
        """Record a fresh observation of this node.

        Updates the code and reason and re-stamps ``timestamp`` to now — the
        timestamp is the *observation* time, set by the check on each run
        (project.md §2.1). ``members`` marks the reasons as individually
        suppressible entries rather than prose (ADR-0036).
        """
        self.code = _coerce_code(code)
        self.reason_entries, self.members = normalize(reason, members)
        self.timestamp = datetime.now().isoformat()

    def get_status_code(self) -> StatusCode:
        """Effective status of this node, rolled up per ADR-0039:

        - severity order ``ERROR > WARN > OK``;
        - ``UNDEFINED`` (a not-yet-reported leaf) is ignored when accumulating;
        - ``MAINTENANCE`` cancels this node's whole subtree, and the node itself
          is ignored by its parent;
        - always returns a ``StatusCode`` and never downgrades;
        - with nothing left to count, *silenced* children read ``MAINTENANCE`` and
          merely unreported ones read ``UNDEFINED``.

        This walks the **stored** readings, which is the pure derivation ADR-0032
        rule 3 requires of it. What a node *shows* — pins and every other
        contribution rule applied — is :meth:`StatusTree.effective`.
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
