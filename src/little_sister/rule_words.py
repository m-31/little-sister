"""What a configured rule says where it stands (ADR-0137): one sentence, in the
page's words, for its block on the wall, on a node's page, in *Handled*, in a
branch's *why* card and in the Copy document.

Each sentence is Markdown that names a status by its placeholder, ``{error}`` —
the page draws it as the status's sign and the Copy document writes it out as it
writes a status, *error ⛔* (ADR-0133 decision 5) — so that the table reads the
same wherever it is shown. A configured rule gives the page no status word of its
own, so it gives a text no placeholder: what it changes is said in the words the
statuses already have.

The shape is the maintenance block's, a mark and then the sentence: what the rule
makes of its part, where — above, on the node's lines, among its children — while
fewer than its count fail and how many do, and by which rule. A node's page names
its node, and says since when the rule stands; the wall's box names its node in its
head already.
"""
from __future__ import annotations

from collections.abc import Sequence

from little_sister.aggregation import ALL, AggregationRule, Table
from little_sister.codes import StatusCode
from little_sister.reasons import plain

#: The order a table's entries are said in: the worse status first.
_SAID_FIRST = (StatusCode.ERROR, StatusCode.WARN)


def sign(code: StatusCode) -> str:
    """A status as a text names it: its placeholder, ``{error}``."""
    return "{" + code.name.lower() + "}"


def table_said(table: Table, *, many: bool = False) -> str:
    """What a table makes of a part, in the page's words: *{error} counts as {warn}*,
    *{warn} and {error} count as {ok}*, *{error} counts as {warn}, {warn} as {ok}*,
    *counts nothing*, or *counts as it reads* — and with ``many`` said of several
    parts, a node's lines, *count nothing* and *count as they read*."""
    if table.left_out:
        return "count nothing" if many else "counts nothing"
    entries = sorted(table.entries, key=lambda item: _SAID_FIRST.index(item[0]))
    if not entries:
        return "count as they read" if many else "counts as it reads"
    groups: list[tuple[list[StatusCode], StatusCode]] = []
    for key, value in entries:
        if groups and groups[-1][1] is value:
            groups[-1][0].append(key)
        else:
            groups.append(([key], value))
    said: list[str] = []
    for index, (keys, value) in enumerate(groups):
        named = " and ".join(sign(key) for key in reversed(keys))
        if index:
            said.append(f"{named} as {sign(value)}")
        else:
            verb = "count" if len(keys) > 1 else "counts"
            said.append(f"{named} {verb} as {sign(value)}")
    return ", ".join(said)


def condition_said(rule: AggregationRule, failing: int | None) -> str:
    """A count, in words: *while fewer than 10 fail — 7 do*, *— 1 does*, *— none
    does*, and *— 12 do* where the count is reached and the rule changes nothing —
    how many fail, never *of* the number, which reads as a share of the parts; or
    without how many do where ``failing`` is ``None``, a rule said of no one part;
    empty for a rule that counts nothing."""
    if rule.count is None:
        return ""
    said = f" while fewer than {rule.count:,} fail"
    if failing is None:
        return said
    if failing == 0:
        return f"{said} — none does"
    return f"{said} — {failing:,} {'does' if failing == 1 else 'do'}"


def _parts_said(named: Sequence[str] | None, noun: str, whose: str) -> str:
    """*its lines*, or *2 of its lines* where a rule names them — and where
    ``whose`` is no owner but a selector's words, *the lines of what carries dev*."""
    parts = f"{whose} {noun}" if whose.endswith("'s") or whose == "its" else (
        f"the {noun} of {whose}")
    if named is None or tuple(named) == (ALL,):
        return parts
    return f"{len(named):,} of {parts}"


def _first_up(text: str) -> str:
    """``text`` with its first letter in capitals, past any Markdown before it — and
    as it is where a status's sign leads it, ``{error}``, or a path, ``/aws``."""
    for index, char in enumerate(text):
        if char in "{/":
            return text
        if char.isalpha():
            return text[:index] + char.upper() + text[index + 1:]
    return text


def rule_said(rule: AggregationRule, place: str, *, failing: int | None = 0,
              this: str = "", path: str = "", parent: str = "") -> str:
    """The sentence of a rule's block, without its mark: what it makes of its part
    at ``place`` — ``node``, what the node passes up; ``lines``, how its lines count
    in it; ``children``, how its children count in it; ``counted``, how its parent
    counts it among its children — and by which rule.

    ``this`` names the node where the block stands away from its head — *this
    node* on the node's own page — and ``path`` names what it picks, as *Handled*
    does: its path, or what carries its tag (ADR-0139 decision 7); the wall leaves
    both out, its box's head naming the node. ``parent`` is
    the path of the node whose children are counted, for ``counted``.
    ``failing`` is how many of the parts it counts fail, ``None`` where the
    sentence is of no one part."""
    if path:
        this = f"**{plain(path)}**"
    table = rule.table
    condition = condition_said(rule, failing)
    # a selector's words own nothing: *the lines of what carries dev*
    whose = (this if path and not path.startswith("/")
             else f"{this}'s" if this else "its")
    if place == "lines":
        if table.left_out or not table.entries:
            said = (f"{_parts_said(rule.lines, 'lines', whose)} "
                    f"{table_said(table, many=True)}")
        else:
            said = (f"On {_parts_said(rule.lines, 'lines', whose)}, "
                    f"{table_said(table)}{condition}")
    elif place == "children":
        said = (f"Of {_parts_said(rule.children, 'children', whose)}, "
                f"{table_said(table)}{condition}")
    elif place == "counted":
        among = (f"**{plain(parent)}**'s children" if parent
                 else "its parent's children")
        said = f"Among {among}, {table_said(table)}{condition}"
    else:
        said = (f"{this}: {table_said(table)} above" if this
                else f"{table_said(table)} above")
    return f"{_first_up(said)}, by the rule **{plain(rule.name)}**"


def since_said(rule: AggregationRule) -> str:
    """Where a rule is written and since when it stands: *config/aggregation.yaml,
    since 2026-10-24* — who set a configured rule being its file, in its root."""
    return f"{plain(str(rule.file))}, since {rule.since.isoformat()}"
