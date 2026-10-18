"""What a configuration says about some of what an aspect lists: a rule list
(ADR-0129).

A package that lets a deployment single out part of what one of its aspects lists —
leave one workflow of one repository out, grade a fleet of instances by limits of
its own — reads the deployment's ``rules:`` list here, so that what a rule matches,
and which rule decides, is answered once for every package. What is settled here:

- **The list is consulted in order, and the first rule that matches decides,
  whole** — not the first rule that sets each key, which would be a merge asking one
  question once per key. An exception is a rule written *above* the rule it
  excepts, and there is no negation.
- **A value is addressed along the axes its package declares** (:class:`Axis`): a
  workflow by its repository and its file, an instance by its ``Name`` tag. A named
  axis is a key on the rule, a list of names or a block of ``names:``, ``prefixes:``
  and ``regexes:``; the one axis of an aspect that has one may be written on the rule
  itself. A rule matches where every axis it writes matches, an axis it leaves out
  matching any value, and within an axis any of its forms matching is enough.
- **A value compares exactly** (:class:`Matcher`), as the source returned it: a name
  a value equal to it, a prefix a value that begins with it, a regex a value it
  matches whole. Nothing folds case — a pattern that wants it folded says ``(?i)`` —
  and no flag on a rule changes what its entries mean.
- **An absent value is matched by ``unnamed: true`` and by nothing else**, on an axis
  whose values can be absent; on any other axis the key is refused, since a rule
  that can never match is configuration that looks like it works.
- **What a rule grades is the library's, and what else it says its package's.** A
  list handed its block's gradings (ADR-0131 decision 6) reads the keys a rule writes
  of them — a pair, a set or a sentence whole, a map word by word — into
  :attr:`Rule.graded`; the package names the keys that are not grading — what a run
  reads — and hands over a reader for them, and the rule carries what the reader
  returned. ``ignore: true`` is refused beside either, since what a rule drops has no
  line for them to say anything on.
- **A rule that matched nothing is a log line, never a node**
  (:meth:`RuleList.report`): a typo in a matcher is a fact about the configuration,
  not a finding, and a rule that matches nothing is often right, since what it names
  may come and go.

Everything a rule list refuses it refuses while the configuration is read, as a
:class:`~little_sister.errors.CheckError` naming the rule, so that a mistake stops
the check's start rather than leaving a filter that filters nothing.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from little_sister.errors import CheckError
from little_sister.grading import Graded, GradingBlock

#: The check-authoring surface of this module (architecture.md §11, ADR-0049) —
#: everything public here is promised, so the two cannot drift apart.
__all__ = ["RULE_WORD", "Axis", "Matcher", "Rule", "RuleList"]

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: The word a line carries where a rule owns it (decision 6): the name of the rule
#: that judged the line by a key of its own — a level, a gate, a switch, an ``OK``
#: included — which a template names as ``{line.rule}``. A type whose rules can judge
#: declares it in its ``line_words`` and hands it over,
#: ``words={RULE_WORD: rule.name}``, on every line a rule owns; on a line no rule owns
#: it hands nothing, and the segment that prints the word leaves itself out. A type
#: whose rules only drop or keep values declares no such word, and a rule's name
#: stands in for no sentence.
RULE_WORD = "rule"

#: What every rule writes, whatever its package: its name, and whether it drops what
#: it matches.
_RULE_KEYS = ("name", "ignore")
#: The forms of a matcher, as a rule or an axis's block writes them.
_FORMS = ("names", "prefixes", "regexes")
_UNNAMED = "unnamed"
#: Every word the library reads on a rule: no named axis, and no key of a package's
#: own, may be called by one of them.
_LIBRARY_KEYS = frozenset((*_RULE_KEYS, *_FORMS, _UNNAMED))


@dataclass(frozen=True)
class Axis:
    """One way a package addresses what an aspect lists (decision 2).

    ``name`` is what a value along the axis is: the key a rule writes the axis under
    — ``repositories:`` — and the keyword :meth:`RuleList.first` and
    :meth:`RuleList.see` take its value under. ``absent`` says whether a value along
    it can be missing, as an instance's ``Name`` tag can, which is what lets a rule
    write ``unnamed: true``. ``on_rule`` writes the axis's forms on the rule itself
    rather than under its name, which the one axis of an aspect may do: ``prefixes:``
    beside a rule's limits rather than ``name: {prefixes: …}``.
    """

    name: str
    absent: bool = False
    on_rule: bool = False


@dataclass(frozen=True)
class Matcher:
    """What one rule matches along one axis (decision 3): names, prefixes and regexes,
    and — where the axis allows it — the value that is absent.

    Each compares the value as the source returned it, never a name a package
    shortened for display: a name matches a value equal to it, a prefix a value that
    begins with it, and a regex a value it matches **whole**, as :func:`re.fullmatch`
    does — so ``^`` and ``$`` are never needed, and a pattern that means less than the
    whole value says so with ``.*``. Nothing folds case: ``(?i)`` in a pattern is how
    one asks for it.
    """

    names: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    regexes: tuple[re.Pattern[str], ...] = ()
    unnamed: bool = False

    def matches(self, value: str | None) -> bool:
        """Whether ``value`` matches — ``None`` standing for the absent value, which
        ``unnamed`` matches and nothing else does."""
        if value is None:
            return self.unnamed
        return (value in self.names
                or any(value.startswith(prefix) for prefix in self.prefixes)
                or any(pattern.fullmatch(value) for pattern in self.regexes))


def _folded(matcher: Matcher, value: str | None) -> bool:
    """Whether ``value`` would match ``matcher`` with case folded: the hint of the log
    line about rules that matched nothing (decision 5), and nothing else."""
    if value is None:
        return matcher.unnamed
    folded = value.casefold()
    return (any(folded == name.casefold() for name in matcher.names)
            or any(folded.startswith(prefix.casefold())
                   for prefix in matcher.prefixes)
            or any(re.fullmatch(pattern.pattern, value,
                                pattern.flags | re.IGNORECASE)
                   for pattern in matcher.regexes))


@dataclass(frozen=True)
class Rule(Generic[_T]):
    """One rule as its list read it (decision 1): its name, what it matches along each
    axis it writes, whether it drops what it matches, what its package's reader
    returned for the keys of the package's own it writes (decision 4), or ``None``
    where it writes none of them, and what it grades with where it writes a grading
    of its block (ADR-0131 decision 6), or ``None`` where it writes none — which
    ``Check.verdict`` reads in place of the block's.

    ``name`` is the one the configuration wrote, without the spaces around it.
    ``matchers`` pairs each axis the rule writes with its matcher, in the order the
    package declared its axes. An axis the rule leaves out is not there, and matches
    any value.
    """

    name: str
    matchers: tuple[tuple[str, Matcher], ...]
    ignore: bool = False
    own: _T | None = None
    graded: Graded | None = None


def _matches(rule: Rule[Any], values: Mapping[str, str | None]) -> bool:
    return all(matcher.matches(values[axis]) for axis, matcher in rule.matchers)


def _near(rule: Rule[Any], values: Mapping[str, str | None]) -> bool:
    return all(_folded(matcher, values[axis]) for axis, matcher in rule.matchers)


class RuleList(Generic[_T]):
    """An aspect's ``rules:``, read, and the tally of the run in progress.

    Built once, from the configuration, with what the package declares: the ``axes``
    its rules match along, and, where its rules say something beyond ``ignore:``,
    ``own_keys`` — the keys that are the package's own — and ``read_own``, which is
    handed the ones a rule writes, and where the rule stands for a refusal, and
    returns what the rule carries as :attr:`Rule.own`. ``grading`` is the block of
    gradings its rules may write (``Check.grading_block``), read into
    :attr:`Rule.graded`. ``where`` names the list in a refusal and in the log line:
    ``"ec2"``. Every refusal is made here, naming the
    rule, and the package's own declarations are held to the same, so that its own
    tests meet a mistake in them first. A list whose rules write no key of the
    package's own is a ``RuleList[None]``.

    The grading asks :meth:`first` which rule decides a value. The measuring half asks
    :meth:`see`, which answers the same and keeps the run's tally — the rules that
    decided something and the values seen — and calls :meth:`report` once a run,
    which writes the log line and drops the tally. The tally is the list's because a
    grading keeps none (ADR-0086 decision 6); it is one run's at a time, which is how
    the engine runs a check.
    """

    def __init__(self, value: object, where: str, axes: Sequence[Axis], *,
                 own_keys: Collection[str] = (),
                 read_own: Callable[[Mapping[str, Any], str], _T] | None = None,
                 grading: GradingBlock | None = None) -> None:
        self.where = where
        self.axes = tuple(axes)
        _declared(where, self.axes, own_keys, read_own)
        self.own_keys = frozenset(own_keys)
        self._read_own = read_own
        self.grading = grading
        graded_keys = frozenset() if grading is None else grading.keys
        _graded_keys(where, self.axes, self.own_keys, graded_keys)
        self._axis_names = frozenset(axis.name for axis in self.axes)
        on_rule = self.axes[0] if self.axes[0].on_rule else None
        known = set(_RULE_KEYS) | self.own_keys | graded_keys
        if on_rule is None:
            known |= self._axis_names
        else:
            known |= set(_FORMS) | ({_UNNAMED} if on_rule.absent else set())
        self._known = frozenset(known)
        self.rules: tuple[Rule[_T], ...] = self._read(value)
        self._decided: set[str] = set()
        self._seen: dict[tuple[str | None, ...], None] = {}
        self._reported: frozenset[str] | None = None

    def __iter__(self) -> Iterator[Rule[_T]]:
        return iter(self.rules)

    def __len__(self) -> int:
        return len(self.rules)

    def first(self, **values: str | None) -> Rule[_T] | None:
        """The rule that decides ``values`` — the first, in the order the
        configuration wrote them, whose every axis matches — or ``None`` where no
        rule does. ``values`` holds a value for each axis, by its name, ``None``
        standing for one that is absent.

        A lookup and nothing more, which is what a grading asks: a value looked up
        here counts for nothing in the log line.
        """
        if set(values) != self._axis_names:
            along = ", ".join(axis.name for axis in self.axes)
            handed = ", ".join(sorted(values)) or "nothing"
            raise CheckError(
                f"{self.where} rules match along {along}, and were handed {handed}")
        for rule in self.rules:
            if _matches(rule, values):
                return rule
        return None

    def see(self, **values: str | None) -> Rule[_T] | None:
        """:meth:`first`, for the measuring half: the rule that decides ``values``,
        with the run's tally of it — which rule decided something, and the values
        seen — that :meth:`report` writes the log line from."""
        rule = self.first(**values)
        if self.rules:
            self._seen.setdefault(tuple(values[axis.name] for axis in self.axes))
            if rule is not None:
                self._decided.add(rule.name)
        return rule

    def report(self, path: str, *, whole: bool) -> None:
        """Say which rules decided nothing in the run that just measured, and drop its
        tally (decision 5) — once a run, from the measuring half.

        One line at ``INFO``, beginning with ``path``, the check's: written when the
        set of those rules changes, the first run's included, and once more when it
        empties — at ``frequency: 60s`` a line every run would be some fourteen
        hundred identical records a day about a mistake that was true at breakfast.
        To each rule it names it adds what the rule missed, so that a slip is pointed
        at rather than forgiven: the rule above it that decided a value it matches —
        an exception written below the rule it excepts — or else a value it would
        have matched with case folded.

        ``whole`` says whether the run read the whole of its scope. One that did not
        leaves the set as it was: a source that did not answer does not pass its
        rules off as mistakes.
        """
        decided, seen = self._decided, self._seen
        self._decided, self._seen = set(), {}
        if not self.rules or not whole:
            return
        unmatched = [rule for rule in self.rules if rule.name not in decided]
        names = frozenset(rule.name for rule in unmatched)
        if names == self._reported:
            return
        if unmatched:
            logger.info("%s: %d %s rule(s) matched nothing: %s", path,
                        len(unmatched), self.where,
                        ", ".join(self._hinted(rule, seen) for rule in unmatched))
        elif self._reported:
            logger.info("%s: every %s rule now matches something", path, self.where)
        self._reported = names

    def _hinted(self, rule: Rule[_T],
                seen: Iterable[tuple[str | None, ...]]) -> str:
        """The rule's name, and what it missed. A value seen that it matches comes
        first: since the rule decided nothing, a rule above it decided that value, and
        the hint names that rule. Else the first value seen that it would have matched
        with case folded."""
        axes = [axis.name for axis in self.axes]
        folded = ""
        for along in seen:
            values = dict(zip(axes, along, strict=True))
            if _matches(rule, values):
                above = next(other for other in self.rules
                             if _matches(other, values))
                return (f"{rule.name} (matches {self._shown(rule, values)}, decided "
                        f"by {above.name!r} above it)")
            if not folded and _near(rule, values):
                folded = (f"{rule.name} (would match {self._shown(rule, values)} "
                          f"with case folded)")
        return folded or rule.name

    def _shown(self, rule: Rule[_T], values: Mapping[str, str | None]) -> str:
        """A value as a hint names it: alone where the axis is written on the rule,
        and otherwise as each axis the rule writes, with its value — quoted as the
        source returned it, and an absent one said as absent, since ``None`` is
        nothing a configuration writes: ``unnamed:`` is how it addresses one."""
        axis = self.axes[0]
        if axis.on_rule:
            value = values[axis.name]
            return f"an absent {axis.name}" if value is None else repr(value)
        return ", ".join(f"{name} absent" if values[name] is None
                         else f"{name} {values[name]!r}"
                         for name, _ in rule.matchers)

    def _read(self, value: object) -> tuple[Rule[_T], ...]:
        if value is None:
            return ()
        if not isinstance(value, list):
            raise CheckError(f"{self.where} 'rules' must be a list of mappings")
        rules: list[Rule[_T]] = []
        called: dict[str, str] = {}
        for index, item in enumerate(value, 1):
            if not isinstance(item, Mapping):
                raise CheckError(f"{self.where} rules[{index}] must be a mapping")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise CheckError(
                    f"{self.where} rules[{index}] needs a 'name', which a refusal "
                    f"and the log line about rules that matched nothing call it by")
            name = name.strip()
            at = f"{self.where} rules[{index}] ({name!r})"
            earlier = called.get(name.casefold())
            if earlier is not None:
                raise CheckError(
                    f"{at}: another rule is already called that" if earlier == name
                    else f"{at}: another rule is already called {earlier!r}, and a "
                         f"name differing only in case reads as the same one")
            called[name.casefold()] = name
            rules.append(self._rule(item, name, at))
        return tuple(rules)

    def _rule(self, item: Mapping[Any, Any], name: str, at: str) -> Rule[_T]:
        on_rule = self.axes[0] if self.axes[0].on_rule else None
        if on_rule is not None and not on_rule.absent and _UNNAMED in item:
            raise CheckError(
                f"{at}: 'unnamed' matches only an absent value, and no "
                f"{on_rule.name} is absent here: the rule could never match")
        unknown = sorted(str(key) for key in item if key not in self._known)
        if unknown:
            raise CheckError(
                f"unknown key(s) in {at}: {', '.join(unknown)} "
                f"(a rule takes: {', '.join(sorted(self._known))})")
        ignore = item.get("ignore", False)
        if not isinstance(ignore, bool):
            raise CheckError(f"{at}: 'ignore' must be true or false")
        written = [key for key in item if key in self.own_keys]
        grades = ([] if self.grading is None
                  else [key for key in item if key in self.grading.keys])
        if ignore and (written or grades):
            said = ", ".join(repr(key) for key in (*written, *grades))
            raise CheckError(
                f"{at}: 'ignore' drops what the rule matches, which then has no line "
                f"for {said} to say anything on")
        if on_rule is not None:
            matcher = _matcher(item, at, "")
            if matcher == Matcher():
                forms = ", ".join(repr(form) for form in _FORMS)
                if on_rule.absent:
                    forms += f" or {_UNNAMED!r}"
                raise CheckError(
                    f"{at}: a rule needs at least one of {forms} — a rule that means "
                    f"to match everything says so with regexes: ['.*']")
            matchers: tuple[tuple[str, Matcher], ...] = ((on_rule.name, matcher),)
        else:
            matchers = tuple((axis.name, _axis(item[axis.name], at, axis))
                             for axis in self.axes if axis.name in item)
            if not matchers:
                axes = " or ".join(repr(axis.name) for axis in self.axes)
                raise CheckError(
                    f"{at}: a rule needs at least one of {axes} — a rule that means "
                    f"to match everything says so with a regex, as "
                    f"{self.axes[0].name}: {{regexes: ['.*']}}")
        own: _T | None = None
        if written and self._read_own is not None:
            own = self._read_own({key: item[key] for key in written}, at)
        graded: Graded | None = None
        if grades and self.grading is not None:
            graded = self.grading.read_rule({key: item[key] for key in grades}, at)
        return Rule(name, matchers, ignore, own, graded)


def _declared(where: str, axes: tuple[Axis, ...], own_keys: Collection[str],
              read_own: object) -> None:
    """Refuse a declaration no configuration could be read against — a package's own
    mistake, which its tests meet before any deployment does."""
    if isinstance(own_keys, str):
        raise CheckError(
            f"{where}: own_keys is a collection of keys, not the string {own_keys!r}")
    if not axes:
        raise CheckError(f"{where}: a rule list matches along one axis at least")
    names = [axis.name for axis in axes]
    if len(set(names)) != len(names):
        raise CheckError(f"{where}: two axes are called the same: {', '.join(names)}")
    if len(axes) > 1 and any(axis.on_rule for axis in axes):
        raise CheckError(
            f"{where}: an axis written on the rule itself is its list's only axis")
    named = {axis.name for axis in axes if not axis.on_rule}
    taken = sorted((named | set(own_keys)) & _LIBRARY_KEYS)
    if taken:
        raise CheckError(
            f"{where}: {', '.join(taken)} is a word the library reads on every rule, "
            f"so neither an axis nor a key of a package's own can be called that")
    both = sorted(named & set(own_keys))
    if both:
        raise CheckError(
            f"{where}: {', '.join(both)} is an axis and a key of the package's own")
    if bool(own_keys) != (read_own is not None):
        raise CheckError(
            f"{where}: a package's own keys and the reader that reads them come "
            f"together")


def _graded_keys(where: str, axes: tuple[Axis, ...], own_keys: frozenset[str],
                 graded_keys: frozenset[str]) -> None:
    """Refuse a block of gradings whose keys a rule could not tell from the library's
    own words, an axis or a key of the package's — its declaration's mistake."""
    named = {axis.name for axis in axes if not axis.on_rule}
    taken = sorted(graded_keys & (_LIBRARY_KEYS | named | own_keys))
    if taken:
        raise CheckError(
            f"{where}: {', '.join(taken)} is written by a grading of the block and is "
            f"a word a rule says otherwise too — the library's, an axis or the "
            f"package's own")


def _axis(value: object, at: str, axis: Axis) -> Matcher:
    """A named axis as a rule writes it: a list of names, or a block of forms."""
    if isinstance(value, list):
        matcher = Matcher(names=_entries(value, at, axis.name))
    elif isinstance(value, Mapping):
        if _UNNAMED in value and not axis.absent:
            raise CheckError(
                f"{at}: '{axis.name}.{_UNNAMED}' matches only an absent value, and no "
                f"value of '{axis.name}' is absent here: the rule could never match")
        takes = (*_FORMS, *((_UNNAMED,) if axis.absent else ()))
        unknown = sorted(str(key) for key in value if key not in takes)
        if unknown:
            raise CheckError(
                f"unknown key(s) in {at} '{axis.name}': {', '.join(unknown)} "
                f"('{axis.name}' takes: {', '.join(takes)})")
        matcher = _matcher(value, at, f"{axis.name}.")
    else:
        raise CheckError(
            f"{at}: '{axis.name}' must be a list of names or a block of 'names', "
            f"'prefixes' and 'regexes'")
    if matcher == Matcher():
        raise CheckError(f"{at}: '{axis.name}' names nothing to match")
    return matcher


def _matcher(block: Mapping[Any, Any], at: str, prefix: str) -> Matcher:
    """The forms ``block`` writes — the rule itself for an axis written on it, an
    axis's block otherwise — each label in a refusal after ``prefix``. An
    ``unnamed:`` has been refused before this where its axis is never absent."""
    regexes = tuple(_compiled(pattern, at, f"{prefix}regexes")
                    for pattern in _entries(block.get("regexes"), at,
                                            f"{prefix}regexes"))
    unnamed = block.get(_UNNAMED, False)
    if not isinstance(unnamed, bool):
        raise CheckError(f"{at}: '{prefix}{_UNNAMED}' must be true or false")
    return Matcher(names=_entries(block.get("names"), at, f"{prefix}names"),
                   prefixes=_entries(block.get("prefixes"), at, f"{prefix}prefixes"),
                   regexes=regexes, unnamed=unnamed)


def _entries(value: object, at: str, label: str) -> tuple[str, ...]:
    """A form's entries, each kept as written: an exact comparison compares what the
    configuration says, its spaces included."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise CheckError(f"{at}: '{label}' must be a list")
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            # An empty prefix matches every value: the accidental spelling of a rule
            # that swallows the whole aspect.
            raise CheckError(f"{at}: every '{label}' entry must be a non-empty string")
    return tuple(value)


def _compiled(pattern: str, at: str, label: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as error:
        raise CheckError(
            f"{at}: '{label}' entry {pattern!r} is not a regular expression: "
            f"{error}") from error
