"""The configured rules: ``config/aggregation.yaml`` (ADR-0137).

A deployment says here how a part of its tree counts above it — a fact about how
the estate is built, which stands for good: staging passes at most a warning to the
root, every account's EC2 warnings heal, a band of findings counts as a warning
until it holds ten. Each rule is one small table at the contribution boundary
(ADR-0032), and what this module settles is what a rule *is* and *where it acts*;
what a table does to a count is the tree's (:mod:`little_sister.tree`), so that the
snapshot and the bookkeeping read one derivation.

**A rule** writes five keys and may write three more::

    rules:
      - name: develop is no production
        under: /aws/develop
        counts_as: {ERROR: WARN}
        note: The develop account is no production; it advises.
        since: 2026-10-24

- ``counts_as`` is the table: what a part reporting ``WARN`` or ``ERROR`` counts as
  above — the cap ``{ERROR: WARN}``, healing ``{WARN: OK}``, the floor
  ``{WARN: ERROR}`` and their combinations — or ``nothing``, the part left out
  whatever it reports. A status the table does not name counts as itself, so ``{}``
  is every status as itself, the exception written above the rule it excepts. A
  table that would count a worse status for less than a milder one is refused.
- ``under`` picks a part of the tree: the node it names and everything beneath it,
  ``*`` standing for one segment, so ``/aws/*/ec2`` names every account's ec2.
  ``tag`` picks every node that carries a tag (ADR-0139 decision 7) — the nodes a tag
  is written for and everything beneath them — and beside ``under`` both must hold;
  a rule writes one of them at least.
- Without ``lines:`` or ``children:`` a rule acts on what the **top** of each part
  it picks passes to its parent — the node it picks whose parent it does not. With
  ``lines:`` — ``"*"`` or a list of line addresses — it acts on how the lines of
  every node it picks count in that node's own status. ``children:`` stands only
  beside a count.
- ``while_fewer_than: N`` makes the table apply only while fewer than N of the
  part's lines, or of the top's children, report a status the table names; from N
  on they count as they are.
- ``note`` (Markdown, as a pin's note is) and ``since`` (the day the rule began to
  stand) are required: the index lists the rules by age, and a rule nobody dated is
  the likeliest to be stale.

**Where two rules pick one place the first decides, whole** — a node's boundary, its
lines one by one, and its children are three places — in the order the rules are
read: every configuration root's file, the root named **last** first, as a later
root wins everywhere else in the chain (ADR-0031), and within a file its order.

**Nothing here stops the monitor.** A rule that cannot apply — a key it does not
know, a table that reorders, a part no check's mount can reach, the instance's own
branch, a name another rule has — does not apply, and the startup record says why
(``self_report.startup``): it fails toward alarming by itself, the alarm it was to
quiet staying (ADR-0032 rule 7). A rule that picks nothing *now* is no mistake —
what it names comes and goes — and the index says so beside it.

The instance's own branch, ``/little-sister``, is out of every rule's reach: a rule
naming it is refused, and a broader one leaves it out in silence (decision 4). A
deployment must not be able to quiet its own monitor by configuration.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, TypeVar, cast

import yaml

from little_sister import instants, self_report
from little_sister.codes import StatusCode
from little_sister.config_dir import aspect_files, config_roots
from little_sister.logger import logger
from little_sister.reasons import DERIVED_PREFIX, plain, slug
from little_sister.status import HEARTBEAT_PATH, join_path, split_path
from little_sister.tags import spelled

#: The configuration aspect the rules are read from.
ASPECT = "aggregation"

#: What a rule's ``lines:`` and ``children:`` write for every one.
ALL = "*"

#: The one word a table may be instead of a mapping: the part left out.
NOTHING = "nothing"

#: Every key a rule may write, in the order a rule is read (and its index row says it).
RULE_KEYS: tuple[str, ...] = ("name", "under", "tag", "lines", "children",
                              "counts_as", "while_fewer_than", "note", "since")

#: How bad a ranked status is, for the table's one invariant: it never reorders.
_RANK: Mapping[StatusCode, int] = {StatusCode.OK: 0, StatusCode.WARN: 1,
                                   StatusCode.ERROR: 2}

#: The statuses a table names: an ``OK`` part counts ``OK``, since raising it would
#: report a failure nothing measured, and ``MAINTENANCE`` and ``UNDEFINED`` count
#: nothing already (ADR-0039 rules 2 and 3).
_TABLE_KEYS: tuple[StatusCode, ...] = (StatusCode.WARN, StatusCode.ERROR)

#: The segment of the instance's own branch, which no rule reaches.
_OWN_BRANCH = split_path(HEARTBEAT_PATH)[0]

_T = TypeVar("_T")

#: How many paths a rule set remembers its answers for before it starts over. The
#: tree asks once per node per snapshot, and a deployment whose subjects come and go
#: would otherwise grow the memo with every path it ever saw.
_MEMO_LIMIT = 50_000


@dataclass(frozen=True)
class Table:
    """What a rule makes a part count as above, by the status it reports.

    ``entries`` maps ``WARN`` and ``ERROR`` to what each counts as, a status it does
    not name counting as itself; ``left_out`` is ``counts_as: nothing``, the part
    counting nothing whatever it reports. ``MAINTENANCE`` and ``UNDEFINED`` pass
    through every table: they count nothing already."""

    entries: tuple[tuple[StatusCode, StatusCode], ...] = ()
    left_out: bool = False

    def counts(self, code: StatusCode) -> StatusCode | None:
        """What a part reporting ``code`` counts as above: a status, or ``None``
        where it counts nothing."""
        if code not in _RANK:
            return code
        if self.left_out:
            return None
        return dict(self.entries).get(code, code)

    def names(self, code: StatusCode) -> bool:
        """Whether this table names ``code`` — what a count counts (decision 7):
        a part reporting a status the table maps."""
        if self.left_out:
            return code in _RANK
        return any(key is code for key, _ in self.entries)

    @property
    def spelled(self) -> str:
        """The table as a rule writes it: ``{ERROR: WARN}``, ``{}`` or
        ``nothing``."""
        if self.left_out:
            return NOTHING
        return "{" + ", ".join(f"{key.name}: {value.name}"
                               for key, value in self.entries) + "}"


@dataclass(frozen=True)
class AggregationRule:
    """One configured rule as it was read and accepted (ADR-0137): what it is
    called, the part it picks, the table, where it acts, its count, its note and
    its day — and the file and root it is written in, which is who set it. ``order``
    is its place among every root's rules, the one the first-decides rule reads."""

    name: str
    under: str
    segments: tuple[str, ...]
    table: Table
    note: str
    since: date
    file: Path
    root: Path
    order: int = 0
    #: The lines it acts on — ``("*",)`` for every one — or ``None`` for a rule that
    #: acts on what a node passes up or on its children.
    lines: tuple[str, ...] | None = None
    #: The children it counts — ``("*",)`` for every one — beside a count, or
    #: ``None``.
    children: tuple[str, ...] | None = None
    #: ``while_fewer_than``, or ``None`` for a rule that always applies.
    count: int | None = None
    #: The tag it picks by (ADR-0139 decision 7), or ``""`` for a rule that picks by
    #: ``under`` alone; a rule that writes no ``under`` has ``under`` empty.
    tag: str = ""

    @property
    def selector(self) -> str:
        """What the rule picks, as the index names it: its ``under`` path, *what
        carries dev*, or both — *what carries dev under /aws*."""
        if not self.tag:
            return self.under
        carried = f"what carries {self.tag}"
        return f"{carried} under {self.under}" if self.under else carried

    @property
    def level(self) -> str:
        """Where it acts: ``node``, ``lines`` or ``children``."""
        if self.lines is not None:
            return "lines"
        if self.children is not None:
            return "children"
        return "node"

    @property
    def key(self) -> str:
        """What the surfaces address the rule by: its name, case folded — unique
        across every root's rules (decision 2)."""
        return self.name.casefold()

    def picks(self, segments: Sequence[str],
              tags: Collection[str] = ()) -> bool:
        """Whether the node with these path ``segments``, carrying ``tags``, is in a
        part this rule picks: it is the node ``under`` names, or beneath it, ``*``
        matching any one segment, and it carries the rule's ``tag`` where it writes
        one. The instance's own branch never is."""
        if segments and segments[0] == _OWN_BRANCH:
            return False
        if self.tag and self.tag not in tags:
            return False
        if len(segments) < len(self.segments):
            return False
        return all(want == ALL or want == got
                   for want, got in zip(self.segments, segments, strict=False))

    def tops(self, segments: Sequence[str], tags: Collection[str] = (),
             parent_tags: Collection[str] = ()) -> bool:
        """Whether the node with these ``segments``, carrying ``tags`` beneath a
        parent carrying ``parent_tags``, is the **top** of a part this rule picks —
        picked, and its parent not (decision 4): where a rule on a node and a count
        over children act. Beneath the node ``under`` names, that is where the tag
        begins: a node that carries it whose parent does not (ADR-0139 decision 7)."""
        if not self.picks(segments, tags):
            return False
        if len(segments) == len(self.segments):
            return True
        return bool(self.tag) and self.tag not in parent_tags

    def names_line(self, line: str) -> bool:
        assert self.lines is not None
        return self.lines == (ALL,) or line in self.lines

    def names_child(self, child: str) -> bool:
        assert self.children is not None
        return self.children == (ALL,) or child in self.children

    def would_pick_folded(self, segments: Sequence[str]) -> bool:
        """Whether the node with these ``segments`` is one this rule would pick
        with case folded and does not — what the index names beside a rule that
        picks nothing now, as a package's rule list names it (ADR-0129 decision 5)."""
        if not self.under or self.picks(segments, (self.tag,)) or len(segments) < len(
                self.segments):
            return False
        if segments and segments[0] == _OWN_BRANCH:
            return False
        return all(want == ALL or want.casefold() == got.casefold()
                   for want, got in zip(self.segments, segments, strict=False))


class RuleSet:
    """The rules a start accepted, in the order the first-decides rule reads them,
    and the answers to *which rule decides here* (decision 3).

    Static for the life of the process — a rule changes with a deploy and a restart
    (#31's reload in place is not built) — so each answer is remembered per path:
    the tree asks for every node it rolls up, at every snapshot. Safe to share
    between threads: an answer computed twice is the same answer."""

    def __init__(self, rules: Iterable[AggregationRule] = (),
                 tags_of: Callable[[str], Collection[str]] | None = None) -> None:
        self.rules: tuple[AggregationRule, ...] = tuple(rules)
        self._node = tuple(rule for rule in self.rules if rule.level == "node")
        self._lines = tuple(rule for rule in self.rules if rule.level == "lines")
        self._children = tuple(rule for rule in self.rules
                               if rule.level == "children")
        self._by_key = {rule.key: rule for rule in self.rules}
        self._memo: dict[tuple[str, str], Any] = {}
        # how many times the remembered answers were started over: an answer worked
        # out across a `forget` is given, and not remembered
        self._forgotten = 0
        self._standing: dict[frozenset[str], RuleSet] = {}
        self._lock = threading.Lock()
        # What a node at a path carries (ADR-0139), which a rule with `tag:` picks
        # by: the tree's, handed over where it takes the rules (`bound`), and asked
        # only where a rule writes a tag.
        self._tags_of = tags_of
        self._tagged = any(rule.tag for rule in self.rules)

    def bound(self, tags_of: Callable[[str], Collection[str]]) -> RuleSet:
        """These rules, answering by what ``tags_of`` says a node at a path carries:
        the set one tree reads, with answers of its own, so that a set handed to two
        trees answers each by its own tags."""
        return RuleSet(self.rules, tags_of)

    def forget(self) -> None:
        """Start the remembered answers over — where what a node carries has
        changed, a run having written the tags an aspect's name is given."""
        with self._lock:
            self._memo.clear()
            self._forgotten += 1
            standing = tuple(self._standing.values())
        for found in standing:
            found.forget()

    def __bool__(self) -> bool:
        return bool(self.rules)

    def standing(self, keys: Iterable[str]) -> RuleSet:
        """The rules named by ``keys``, in their order: those that stood at one
        moment of a replay of the past (decision 11), each from where it began to
        count. The set itself where every rule stood already."""
        wanted = frozenset(keys)
        if all(rule.key in wanted for rule in self.rules):
            return self
        with self._lock:
            found = self._standing.get(wanted)
            if found is None:
                found = RuleSet((rule for rule in self.rules if rule.key in wanted),
                                self._tags_of)
                self._standing[wanted] = found
        return found

    def __len__(self) -> int:
        return len(self.rules)

    def named(self, key: str) -> AggregationRule | None:
        """The rule called ``key``, case folded, or ``None``."""
        return self._by_key.get(key.casefold())

    def boundary(self, path: str) -> AggregationRule | None:
        """The rule that decides what the node at ``path`` passes to its parent:
        the first node rule whose part begins there, or ``None``."""
        return self._remembered("node", path, lambda at: next(
            (rule for rule in self._node if rule.tops(*at)), None))

    def counting_children(self, path: str) -> AggregationRule | None:
        """The rule that decides how the children of the node at ``path`` count in
        it: the first children rule whose part begins there, or ``None``."""
        return self._remembered("children", path, lambda at: next(
            (rule for rule in self._children if rule.tops(*at)), None))

    def on_lines(self, path: str) -> tuple[AggregationRule, ...]:
        """The lines rules that pick the node at ``path``, in order: a line is
        decided by the first of them whose ``lines:`` names it."""
        return self._remembered("lines", path, lambda at: tuple(
            rule for rule in self._lines if rule.picks(at[0], at[1])))

    def picking(self, path: str) -> tuple[AggregationRule, ...]:
        """Every rule that picks a place at the node at ``path`` — its boundary, its
        children or its lines — in order: what the explain view names beside the
        rule that decided (decision 3)."""
        def found(at: _At) -> tuple[AggregationRule, ...]:
            return tuple(rule for rule in self.rules if (
                rule.picks(at[0], at[1]) if rule.level == "lines"
                else rule.tops(*at)))
        return self._remembered("picking", path, found)

    def _remembered(self, kind: str, path: str,
                    answer: Callable[[_At], _T]) -> _T:
        key = (kind, path)
        try:
            return cast(_T, self._memo[key])
        except KeyError:
            pass
        forgotten = self._forgotten
        segments = split_path(path)
        if self._tagged and self._tags_of is not None:
            tags = self._tags_of(path)
            above = self._tags_of(join_path(*segments[:-1])) if segments else ()
            found = answer((segments, tags, above))
        else:
            found = answer((segments, (), ()))
        with self._lock:
            if self._forgotten != forgotten:
                return found
            if len(self._memo) >= _MEMO_LIMIT:
                self._memo.clear()
            self._memo[key] = found
        return found


#: Where a rule set is asked: a node's path segments, the tags it carries and the
#: tags its parent carries.
_At = tuple[Sequence[str], Collection[str], Collection[str]]


#: The rule set of a deployment that configures none.
NO_RULES = RuleSet()


@dataclass
class _Read:
    """One rule as a file wrote it, before every root's are compared by name."""
    raw: Mapping[str, Any]
    file: Path
    root: Path
    index: int
    rule: AggregationRule | None = None
    problems: list[str] = field(default_factory=list)


def load_rules(spec: str | Path | None = None, *, check_roots: Sequence[str] = (),
               tags: Collection[str] | None = None,
               today: date | None = None) -> RuleSet:
    """Every configuration root's rules (ADR-0137), the root named last first and
    each file in its order, with what cannot apply named on the startup record.
    ``check_roots`` are the mounts of the configured checks, against which a rule
    whose part no check can reach is named; ``tags`` are those the configuration
    writes for a node (ADR-0139), against which a rule whose ``tag:`` none is given
    is named; ``today`` is the day in the configured zone, after which no ``since:``
    may fall."""
    files: list[tuple[Path, Path]] = []
    for root in config_roots(spec):
        found = aspect_files(ASPECT, root)
        if found:
            files.append((found[0], root))
    return read_rules(files, check_roots=check_roots, tags=tags, today=today)


def read_rules(files: Sequence[tuple[Path, Path]], *,
               check_roots: Sequence[str] = (),
               tags: Collection[str] | None = None,
               today: date | None = None) -> RuleSet:
    """The rules of ``files`` — each an aspect file and the root it is in, in
    path-list order — accepted and ordered, what cannot apply named on the startup
    record, one line a rule. The function :func:`load_rules` reads them through; a
    test hands its own."""
    when = today if today is not None else _today()
    read: list[_Read] = []
    for file, root in reversed(files):
        read.extend(_read_file(file, root))
    for item in read:
        item.rule = _accepted(item, when)
    _refuse_duplicates(read)
    for item in read:
        if item.rule is not None and check_roots and not _reachable(
                item.rule.segments, check_roots):
            item.problems.append(
                f"picks {item.rule.under}, which no configured check's mount "
                f"reaches — a typo in the path, or a check removed")
            item.rule = None
        # a tag nothing is tagged with picks nothing for good: a lie about coverage,
        # not a no-op (ADR-0139 decision 7)
        if item.rule is not None and item.rule.tag and tags is not None \
                and item.rule.tag not in tags:
            item.problems.append(
                f"picks what carries {item.rule.tag}, a tag the configuration writes "
                f"for no node — a typo in the tag, or a tag no longer written")
            item.rule = None
    rules: list[AggregationRule] = []
    for item in read:
        if item.problems:
            _note(item)
        elif item.rule is not None:
            rules.append(replace(item.rule, order=len(rules)))
    if rules:
        logger.info("aggregation: %d configured rule(s) apply: %s", len(rules),
                    ", ".join(repr(rule.name) for rule in rules))
    return RuleSet(rules)


def _today() -> date:
    """Today in the configured zone, where a rule's ``since:`` is compared, by the
    one clock (:func:`little_sister.instants.now`)."""
    return day_of(instants.now())


def day_of(at: datetime) -> date:
    """The day ``at`` falls on in the configured zone, where a rule's ``since:`` is
    read."""
    from little_sister.config import config as settings
    return at.astimezone(settings.tzinfo).date()


def day_begins(day: date) -> datetime:
    """The instant ``day`` begins in the configured zone, in UTC as the tree stamps
    its rows: where a rule that began to stand on it starts to count in a replay of
    the past (decision 11)."""
    from little_sister.config import config as settings
    return instants.utc(datetime.combine(day, time(), tzinfo=settings.tzinfo),
                        "the day a rule began to stand")


def _read_file(file: Path, root: Path) -> list[_Read]:
    """The rules one file writes, each as written. A file that is no YAML, or whose
    ``rules:`` is no list, applies nothing, and the startup record says so."""
    try:
        with open(file, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as error:
        _note_file(file, f"could not be read ({error}); none of its rules apply")
        return []
    if data is None:
        return []
    if not isinstance(data, dict):
        _note_file(file, "is no mapping — it holds a `rules:` list; none of its "
                         "rules apply")
        return []
    unknown = sorted(str(key) for key in data if key != "rules")
    if unknown:
        _note_file(file, f"has the key(s) {', '.join(unknown)}, which it does not "
                         f"know and are not read — a file holds `rules:` alone")
    rules = data.get("rules", [])
    if rules is None:
        return []
    if not isinstance(rules, list):
        _note_file(file, "has a `rules:` that is no list; none of its rules apply")
        return []
    read: list[_Read] = []
    for index, raw in enumerate(rules):
        if not isinstance(raw, dict):
            _note_file(file, f"has a rule at position {index + 1} that is no "
                             f"mapping; it does not apply", index=index)
            continue
        read.append(_Read(raw, file, root, index))
    return read


def _accepted(item: _Read, today: date) -> AggregationRule | None:
    """The rule ``item`` writes, or ``None`` where it cannot apply — each reason
    named on the startup record."""
    raw = item.raw
    problems: list[str] = []
    unknown = [str(key) for key in raw if key not in RULE_KEYS]
    if unknown:
        problems.append(f"writes {', '.join(sorted(unknown))}, which a rule does "
                        f"not know (a rule writes {', '.join(RULE_KEYS)})")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("has no `name:`")
    tag = _tag(raw.get("tag"), problems)
    under, segments = _under(raw.get("under"), problems,
                             required=raw.get("tag") is None)
    lines = _parts_named(raw, "lines", problems)
    children = _parts_named(raw, "children", problems)
    if lines is not None and children is not None:
        problems.append("writes both `lines:` and `children:`; one rule acts at one "
                        "level")
    table = _table(raw, problems)
    count = _count(raw, problems)
    if count is not None:
        if lines is None and children is None:
            problems.append("counts with `while_fewer_than:` but writes neither "
                            "`lines:` nor `children:` — a node's own boundary has "
                            "nothing to count")
        if table is not None and table.left_out:
            problems.append("counts with `counts_as: nothing`, which would leave a "
                            "healthy part's parts out too; "
                            "`{WARN: OK, ERROR: OK}` says what is meant")
    elif children is not None and under is not None and not under and tag:
        problems.append("writes `children:` without `while_fewer_than:`; without a "
                        "count a rule acts on what each part it picks passes up, "
                        "and writes no `children:`")
    elif children is not None:
        each = f"`under: {under.rstrip('/')}/*`" if under else "`under: /*`"
        problems.append(f"writes `children:` without `while_fewer_than:`; a rule on "
                        f"each child is {each}")
    note = raw.get("note")
    if not isinstance(note, str) or not note.strip():
        problems.append("has no `note:`")
    since = _since(raw.get("since"), today, problems)
    if under:
        if segments and segments[0] == _OWN_BRANCH:
            problems.append(f"picks {under}, the instance's own branch, which no rule "
                            f"reaches")
        elif not segments and not tag and lines is None and children is None:
            problems.append("acts on what the root passes up, and the root passes "
                            "nothing up — a rule on the whole tree writes `lines:`, "
                            "or picks `/*`")
    item.problems = problems
    if problems:
        return None
    assert isinstance(name, str) and under is not None and table is not None
    assert isinstance(note, str) and since is not None
    return AggregationRule(
        name=name.strip(), under=under, segments=segments, table=table,
        note=note.strip(), since=since, file=item.file, root=item.root,
        lines=lines, children=children, count=count, tag=tag or "")


def _tag(value: object, problems: list[str]) -> str | None:
    """The tag ``tag:`` picks by (ADR-0139 decision 7), as a tag is read —
    capitals as lower case — or ``None`` where the rule writes none or one that is
    no tag, which is named."""
    if value is None:
        return None
    if not isinstance(value, str) or not spelled(value):
        problems.append(f"writes `tag: {value}`, which is no tag: one tag, lowercase "
                        f"letters and digits with hyphens between them")
        return None
    return spelled(value)


def _under(value: object, problems: list[str], *,
           required: bool = True) -> tuple[str | None, tuple[str, ...]]:
    """The part ``under:`` picks, as a path and its segments: ``*`` a whole segment
    and nothing else with it. A rule that picks by ``tag:`` need not write one, and
    picks then wherever the tag is carried: an empty path and no segments."""
    if value is None and not required:
        return "", ()
    if not isinstance(value, str) or not value.strip():
        problems.append("has no `under:` and no `tag:`, so it picks nothing"
                        if value is None
                        else "writes an `under:` that names no node")
        return None, ()
    segments = tuple(split_path(value.strip()))
    for segment in segments:
        if ALL in segment and segment != ALL:
            problems.append(f"picks {value.strip()}, whose segment {segment!r} is "
                            f"part of a name and part `*`; `*` stands for one whole "
                            f"segment")
            return None, ()
    return join_path(*segments), segments


def _parts_named(raw: Mapping[str, Any], key: str,
                 problems: list[str]) -> tuple[str, ...] | None:
    """``lines:`` or ``children:`` as a rule wrote it: ``"*"``, or a list of
    addresses or names. A line's address is what a line pin names (ADR-0036
    decision 12); a derived one, ``h-…``, is the line's wording and no address for a
    rule that stands for good, and one with a ``*`` in it reads as a pattern and
    would match nothing — both refused, so a later meaning changes nothing a
    configuration meant."""
    if key not in raw:
        return None
    value = raw[key]
    if value == ALL:
        return (ALL,)
    if isinstance(value, str) or not isinstance(value, list) or not value:
        problems.append(f"writes `{key}:` as {value!r}; it is \"*\" or a list of "
                        f"{'addresses' if key == 'lines' else 'names'}")
        return None
    named: list[str] = []
    for entry in value:
        if not isinstance(entry, str | int) or isinstance(entry, bool) or not str(
                entry).strip():
            problems.append(f"names {entry!r} in `{key}:`, which is no "
                            f"{'address' if key == 'lines' else 'name'}")
            return None
        text = str(entry).strip()
        if ALL in text:
            problems.append(f"names {text!r} in `{key}:`, which reads as a pattern; "
                            f"every one is \"*\" alone")
            return None
        if key == "lines" and text.startswith(DERIVED_PREFIX):
            problems.append(f"names {text!r} in `lines:`, an address made from the "
                            f"line's own words, which changes when they do — a "
                            f"configured rule names a line its check gives an "
                            f"address")
            return None
        named.append(text)
    return tuple(dict.fromkeys(named))


def _code(value: object) -> StatusCode | None:
    """A status a table writes, in either case: ``OK``, ``WARN`` or ``ERROR``."""
    if not isinstance(value, str):
        return None
    try:
        code = StatusCode[value.strip().upper()]
    except KeyError:
        return None
    return code if code in _RANK else None


def _table(raw: Mapping[str, Any], problems: list[str]) -> Table | None:
    """``counts_as:`` as a :class:`Table`: ``nothing``, or a mapping from ``WARN``
    and ``ERROR`` to ``OK``, ``WARN`` or ``ERROR`` that never makes a worse status
    count for less than a milder one."""
    if "counts_as" not in raw:
        problems.append("has no `counts_as:`")
        return None
    value = raw["counts_as"]
    if isinstance(value, str) and value.strip().casefold() == NOTHING:
        return Table(left_out=True)
    if not isinstance(value, dict):
        problems.append(f"writes `counts_as:` as {value!r}; it is a table such as "
                        f"{{ERROR: WARN}}, or `nothing`")
        return None
    entries: dict[StatusCode, StatusCode] = {}
    for key, mapped in value.items():
        status = _code(key)
        if status not in _TABLE_KEYS:
            problems.append(f"maps {key!r} in `counts_as:`; a table maps WARN and "
                            f"ERROR — an OK part counts OK, and maintenance and a "
                            f"part not yet reported count nothing already")
            return None
        counted = _code(mapped)
        if counted is None:
            problems.append(f"maps {key} to {mapped!r} in `counts_as:`; a status "
                            f"counts as OK, WARN or ERROR, and a part left out is "
                            f"`counts_as: nothing`")
            return None
        assert status is not None
        if status in entries:
            problems.append(f"maps {status.name} twice in `counts_as:`")
            return None
        entries[status] = counted
    table = Table(tuple(sorted(entries.items(), key=lambda item: _RANK[item[0]])))
    ranks = [_RANK[table.counts(code) or StatusCode.OK] for code in
             (StatusCode.OK, StatusCode.WARN, StatusCode.ERROR)]
    if ranks != sorted(ranks):
        problems.append(f"writes `counts_as: {table.spelled}`, under which a worse "
                        f"status counts for less than a milder one")
        return None
    return table


def _count(raw: Mapping[str, Any], problems: list[str]) -> int | None:
    """``while_fewer_than:``: a whole number of at least two, below which the table
    would never apply."""
    if "while_fewer_than" not in raw:
        return None
    value = raw["while_fewer_than"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        problems.append(f"writes `while_fewer_than:` as {value!r}; it is a whole "
                        f"number of at least 2, below which the table would never "
                        f"apply")
        return None
    return value


def _since(value: object, today: date, problems: list[str]) -> date | None:
    """``since:``, the day the rule began to stand: a date, and none after today in
    the configured zone — a rule applies from the start it is read at, and a day to
    come would only misplace it in the index."""
    if value is None:
        problems.append("has no `since:`")
        return None
    if isinstance(value, datetime):
        problems.append(f"writes `since:` as {value.isoformat()}, a moment; it is "
                        f"the day the rule began to stand, YYYY-MM-DD")
        return None
    if isinstance(value, date):
        day = value
    elif isinstance(value, str):
        try:
            day = date.fromisoformat(value.strip())
        except ValueError:
            problems.append(f"writes `since:` as {value!r}, which is no date "
                            f"(YYYY-MM-DD)")
            return None
    else:
        problems.append(f"writes `since:` as {value!r}, which is no date "
                        f"(YYYY-MM-DD)")
        return None
    if day > today:
        problems.append(f"writes `since: {day.isoformat()}`, a day still to come")
        return None
    return day


def _refuse_duplicates(read: Sequence[_Read]) -> None:
    """A name two rules have, in one root or across two, compared with case folded,
    applies for neither — a duplicate cannot say which was meant — and the startup
    record names both files (decision 2)."""
    by_name: dict[str, list[_Read]] = {}
    for item in read:
        name = item.raw.get("name")
        if isinstance(name, str) and name.strip():
            by_name.setdefault(name.strip().casefold(), []).append(item)
    for items in by_name.values():
        if len(items) < 2:
            continue
        where = " and ".join(sorted({str(item.file) for item in items}))
        for item in items:
            item.problems.append(f"shares its name with another rule in {where}, "
                                 f"so neither applies")
            item.rule = None


def _reachable(segments: Sequence[str], check_roots: Sequence[str]) -> bool:
    """Whether a part beginning at ``segments`` lies on one line with some check's
    mount — at it, beneath it, or above it — ``*`` matching any segment."""
    for root in check_roots:
        mount = split_path(root)
        shared = min(len(mount), len(segments))
        if all(want == ALL or want == got
               for want, got in zip(segments[:shared], mount[:shared], strict=True)):
            return True
    return False


def _note(item: _Read) -> None:
    """Why a rule does not apply, on the startup record: one line a rule, every
    reason in it."""
    name = item.raw.get("name")
    called = (f"the rule {name.strip()!r}" if isinstance(name, str) and name.strip()
              else f"the rule at position {item.index + 1}")
    reasons = "; it ".join(item.problems)
    self_report.startup.note(
        slug("aggregation", str(item.file), item.index),
        plain(f"{item.file}: {called} does not apply (ADR-0137): it {reasons}"))


def _note_file(file: Path, problem: str, *, index: int | None = None) -> None:
    """What is wrong with a rule file as a whole, on the startup record."""
    self_report.startup.note(
        slug("aggregation", str(file), "" if index is None else index),
        plain(f"{file} {problem} (ADR-0137)"))
