"""Clipboard-friendly Markdown for the status tree, and for one node of it.

The copy page is an incident hand-off, not another dashboard.  It keeps every
node that needs attention and only the ancestors needed to locate those, then
emits one canonical Markdown document.  The web layer renders rich HTML from that
same document so the two clipboard formats cannot drift.

**Four documents, one formatter.**  :func:`format_tree_markdown` hands over the
whole tree, an outline under a head of its own; :func:`format_node_markdown` hands
over one node — a leaf with everything the tree document has no room for and only
the node's own page knows, its path, when it was observed and since when it has
held that status, the next update, how long the last run took, how often it runs,
what the run reported and what it ran with; a branch with what it shows and the
outline of what is beneath it — and :func:`format_reason_markdown` one line.
They share this module rather than a resemblance: the status cue, the label rule,
the pin attribution and the Markdown nesting are one implementation each, so a
node's own document cannot describe it differently from the same node inside the
tree hand-off.

**Every document says where it is from and when it was made** (ADR-0115): the
address of the page it was made from and the instant, an :class:`Origin` the
caller hands in, since a formatter has no request to read either off. And every
node an outline lists says since when it has shown its status, which the caller
answers too (:data:`Periods`): the tree keeps that, and this module reads no tree.

Every instant either document writes names its **offset** (:class:`TimeStyle`).
The pages render local time and stay silent about the zone, which is right for a
screen somebody is standing in front of; a pasted incident is read in another
office, where `14:32` alone is a guess.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Protocol

from little_sister.config import DEFAULT_TIME_FORMAT
from little_sister.spans import format_duration, format_span, format_tolerance
from little_sister.status import StatusCode
from little_sister.titles import label_parts
from little_sister.tree import ReasonLine, StatusSnapshot

_STATUS_ICON = {
    StatusCode.OK: "✅",
    StatusCode.WARN: "⚠️",
    StatusCode.ERROR: "⛔",
    StatusCode.MAINTENANCE: "🛠️",
    StatusCode.UNDEFINED: "❓",
}

# Node names are structural data, not authored Markdown.  Keep the punctuation
# people use in identifiers, but neutralise constructs that would turn a name into
# emphasis, code or a link.  Titles and reasons are authored Markdown elsewhere in
# the application and deliberately keep that contract here.
_MD_INLINE_ESCAPE = {ord(ch): f"\\{ch}" for ch in "\\`*[]"}

# A CommonMark fence opener: up to three spaces of indent, then three or more
# backticks or tildes.  The one block construct that must own its line
# (:func:`_markdown_item`).
_OPENS_A_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


def status_icon(code: StatusCode) -> str:
    """The portable, non-color status cue used by the copy document."""
    return _STATUS_ICON[code]


@dataclass(frozen=True)
class TimeStyle:
    """How a copy document writes an instant: the deployment's zone and format,
    and the **offset** that lets somebody elsewhere read it.

    Passed in rather than read from the configuration here, for two reasons.  One
    document is formatted with one clock — the caller resolves it once, so a long
    document cannot straddle a settings reload.  And this module stays a pure
    formatter, testable against a fixed zone without a config file.
    """

    zone: tzinfo
    time_format: str = DEFAULT_TIME_FORMAT

    def at(self, moment: datetime | None) -> str:
        """One instant, in the configured zone, naming its offset — and an em
        dash where there is none, which is what the ``localtime`` filter writes
        there too."""
        if moment is None:
            return "—"
        moment = moment.astimezone(self.zone)
        return f"{moment.strftime(self.time_format)} {_offset(moment)}".rstrip()


def _offset(moment: datetime) -> str:
    """A UTC offset as ``+02:00`` — ``%z``'s ``+0200`` with the colon ISO-8601
    uses, and the seconds an ancient local-mean-time zone can carry dropped."""
    raw = moment.strftime("%z")
    return f"{raw[:3]}:{raw[3:5]}" if len(raw) >= 5 else raw


@dataclass(frozen=True)
class Origin:
    """Where a document is from and when it was made (ADR-0115 decision 1).

    ``dashboard`` is the absolute address of the page the document was made from,
    as the request reached it — the wall for the tree, a node's own page for a
    node, that page with the line marked for a line. ``made`` is the instant the
    document was made, which it writes in its own clock (:class:`TimeStyle`): not
    the instant a button was pressed, because what is copied was read when the
    page was made, and a stamp taken later would date old facts as new.

    Handed in, since a formatter has no request. A caller that has none either —
    a fixture sheet, a test — passes no origin, and the document claims none.
    """

    dashboard: str
    made: datetime


class Standing(Protocol):
    """Since when a node has shown its status, as its page states it (ADR-0099):
    the instant, whether that is a bound the period began before, and what began
    the period where a pin did — in the words every surface writes after it."""

    @property
    def at(self) -> datetime: ...

    @property
    def before(self) -> bool: ...

    @property
    def began(self) -> str: ...


#: What the tree keeps of a node's period, or ``None`` where it keeps none: how an
#: outline learns since when each node it lists has stood (ADR-0115 decision 2).
Periods = Callable[[StatusSnapshot], Standing | None]


def format_copy_markdown(root: StatusSnapshot | None, style: TimeStyle, *,
                         periods: Periods | None = None) -> str:
    """Return the outline of what needs attention below ``root`` as deterministic
    Markdown.

    The synthetic root is omitted.  A healthy leaf contributes nothing; a group
    contributes where a descendant does, or where it holds something of its own
    (:func:`_speaks`).  Snapshot sibling order is preserved (the tree has already
    made it deterministic), and all reasons remain in their check-provided order.
    With ``periods``, each node the outline lists says since when it has shown its
    status (ADR-0115 decision 2).
    """
    if root is None:
        return ""
    lines: list[str] = []
    for child in root.children:
        lines.extend(_format_node(child, 0, style, periods))
    return "\n".join(lines)


def format_tree_markdown(root: StatusSnapshot | None, style: TimeStyle,
                         origin: Origin, periods: Periods | None = None) -> str:
    """Return the tree's document (ADR-0115 decision 4): what it is, where it is
    from and when it was made, how much needs attention, and the outline of that.

    There is always one. A tree with nothing to list says that nothing needs
    attention and how many nodes that is said of, which is a state somebody
    documents as much as a failure; one that nothing reports into says so.

    The count and the outline are a paragraph and a list of their own beneath the
    head's list: one list would space the outline's items like the head's.

    A pin on the tree itself is not set from the wall, and one that stands is
    stated like any other: in the head, above a count that says what it silences.
    """
    code = root.code if root is not None else StatusCode.UNDEFINED
    pin = root.maintenance_entry if root is not None else None
    document = [f"## little-sister status {status_icon(code)}", "",
                *_origin_lines(origin, style)]
    if pin is not None:
        document.extend(_maintenance_lines(0, pin.reason, pin.set_by,
                                           pin.expires_at, style))
    document.append("")
    counted = _counted(root) if root is not None else []
    wrong = [node for node in counted if _shown(node) is not StatusCode.OK]
    if not counted:
        document.append("**Nothing reports.**")
    elif not wrong:
        document.append("**Nothing needs attention** — "
                        + ("the one node is ok." if len(counted) == 1
                           else f"all {len(counted)} nodes are ok."))
    else:
        document.extend([
            (f"**Silenced by the pin** — {len(wrong)} of {_nodes(len(counted))} "
             f"would need attention: {_tally(wrong)}" if pin is not None else
             f"**Needs attention** — {len(wrong)} of {_nodes(len(counted))}: "
             f"{_tally(wrong)}"),
            "", format_copy_markdown(root, style, periods=periods)])
    return "\n".join(document)


def format_node_markdown(node: StatusSnapshot, style: TimeStyle,
                         since: datetime | None = None, *, before: bool = False,
                         began: str = "", origin: Origin | None = None,
                         periods: Periods | None = None) -> str:
    """Return one node as a hand-off document: what the tree outline says about
    it, plus everything only its own page knows.

    The tree document locates a finding; this one hands it to somebody.  So it
    keeps the identity and the facts an operator would otherwise retype — the
    path, where the document is from and when it was made (``origin``), the
    observation and the period it bounds, the next update, the last run's wall
    time, the frequency — then the reason lines **in full**, then what
    the run reported and what it ran with.  ``since`` is the start of the node's
    current own-status period (the same value its page renders), and ``None``
    where the node has no transition of its own to bound one (ADR-0027); ``before``
    says it is a bound, and the period began before it — a first reading, or a
    beginning lost before the tree kept it (ADR-0099 decisions 1 and 9);
    ``began`` is what the period says of its beginning where a pin did it — *when
    its maintenance ended*, *when a line was silenced* — in the Time card's own
    words (decision 8, ADR-0107 decision 3).

    **A node with nodes beneath it hands over what is beneath it**
    (:func:`_format_branch`, ADR-0115 decision 5): what a leaf has, its check's
    reading, is the one thing such a node may not have, and what is wrong with a
    host is on its children. ``periods`` dates what that outline lists.

    Headings and blocks rather than the tree's nested list: a document about one
    thing is read as one, and a fenced traceback or a bulleted configuration
    nested four levels deep is a worse paste than the same block at the margin.

    A pin does not change what is copied.  A pin changes what the tree *reports*;
    it does not change what the check *measured*, and a hand-off is about the
    measurement — so the reading stays, and the document says a pin is in force
    instead of quietly presenting the pinned code as the answer
    ([ADR-0032](../docs/adr/0032-status-contribution-boundary.md) rule 5, in a
    surface that has no color to say it with).
    """
    if node.children:
        return _format_branch(node, style, since, before, began, origin, periods)
    document = [f"## {_label(node)} {status_icon(node.reported_code)}", ""]
    document.extend(_node_facts(node, style, since, before, began, origin))
    if node.reasons:
        document.extend(["", "**Reasons**", ""])
        for reason in node.reasons:
            document.extend(_format_reason(reason, 0, style))
    document.extend(_run_blocks(node))
    return "\n".join(document)


def _run_blocks(node: StatusSnapshot) -> list[str]:
    """What the node's run found and what it ran with, each under its heading.

    `report` before `config` — what the run found is why the page was opened,
    what it ran with is the reference beside it (`_node_facts.html` orders the
    cards the same way).  Both are the check's own authored Markdown and land
    at the margin, where a list or a fence renders as itself.
    """
    blocks: list[str] = []
    if node.report:
        blocks.extend(["", "**Report**", "", node.report])
    if node.config:
        blocks.extend(["", "**Configuration**", "", node.config])
    return blocks


def _format_branch(node: StatusSnapshot, style: TimeStyle,
                   since: datetime | None,
                   before: bool, began: str, origin: Origin | None,
                   periods: Periods | None) -> str:
    """A node with nodes beneath it, handed over (ADR-0115 decision 5).

    Its heading carries the cue of what the node **shows**: a host whose check
    grades its children declares nothing itself, and the cue of what it reported
    would be *undefined* over a full disk and over nothing wrong alike.
    **Reported** stands where the node declares a status of its own, **Shown as**
    where it shows something else, with where that comes from — the nodes beneath
    it alone where every line of its own is silenced, which then counts for
    nothing and cancels nothing (ADR-0124) — and no claim about
    each node beneath it: one that is pinned, one that waits and one reached
    through a failing check count for nothing in what their branch shows
    (ADR-0039).

    Then the period of its own status, named as that (ADR-0123 decision 3), and
    its observation, as far as it has them, its own lines, and
    **Beneath it**: how many of the nodes beneath it need attention and the
    outline of those, which is the tree document's own outline begun here — or
    that nothing does. Under a pin the count says what the pin is silencing.
    """
    beneath = _counted(node)
    declares = node.reported_code is not StatusCode.UNDEFINED
    document = [f"## {_label(node)} {status_icon(node.code)}", "",
                _item(0, f"**Path:** {node.path.translate(_MD_INLINE_ESCAPE)}"),
                *_origin_lines(origin, style)]
    if declares:
        document.append(_item(0, f"**Reported:** {_code_word(node.reported_code)}"))
    under = ("the one node" if len(beneath) == 1 else f"the {len(beneath)} nodes")
    if node.maintenance_entry is not None:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — a maintenance pin is in force "
            f"on it and on {under} beneath it. "
            + ("The reported reading above is what its check measured." if declares
               else "It reports nothing of its own.")))
        document.extend(_maintenance_lines(0,
            node.maintenance_entry.reason,
            node.maintenance_entry.set_by,
            node.maintenance_entry.expires_at,
            style,
        ))
    elif node.lines_silenced:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — rolled up from {under} "
            f"beneath it. Every line of its own is silenced."))
    elif not declares:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — rolled up from {under} "
            f"beneath it. It reports nothing of its own."))
    elif node.code != node.reported_code:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — rolled up from its own "
            f"reading and {under} beneath it."))
    document.extend(_time_facts(node, style, since, before, began))
    if node.reasons:
        document.extend(["", "**Reasons**", ""])
        for reason in node.reasons:
            document.extend(_format_reason(reason, 0, style))
    listed: list[str] = []
    for child in node.children:
        listed.extend(_format_node(child, 0, style, periods))
    wrong = sum(1 for found in beneath if _shown(found) is not StatusCode.OK)
    if not listed:
        document.extend(["", "**Beneath it** — nothing needs attention."])
    elif node.maintenance_entry is not None:
        document.extend([
            "", f"**Beneath it**, silenced by the pin — {wrong} of "
                f"{_nodes(len(beneath))} would need attention", "", *listed])
    else:
        document.extend([
            "", f"**Beneath it** — {wrong} of {_nodes(len(beneath))} "
                f"{'needs' if wrong == 1 else 'need'} attention", "", *listed])
    document.extend(_run_blocks(node))
    return "\n".join(document)


def format_reason_markdown(node: StatusSnapshot, line: ReasonLine,
                           style: TimeStyle, *, origin: Origin | None = None) -> str:
    """Return **one reason line** as a hand-off document.

    The narrowest of the four, and the one the whole feature started from: an
    operator picks one finding out of twenty, opens a ticket and has to paste it
    somewhere.  What the tree document and the node document both carry is the
    other nineteen.

    So this is the line, and just enough to say **where it came from** — a pasted
    finding with no node behind it is a sentence nobody can act on, and the
    operator who could have supplied it is the one who has left.  Nothing else:
    the run's facts, the report and the configuration describe the *node*, they
    answer questions this document is not being asked, and the button that does
    carry them is one click away on the same page.

    That exclusion is also why the *secret* question does not arise here — a
    check's configuration is where a secret reference appears
    ([ADR-0023](../docs/adr/0023-secret-references.md)), and no configuration
    reaches this document at all.
    """
    document = [f"## {_label(node)} {status_icon(node.reported_code)}", ""]
    document.append(_item(0, f"**Path:** {node.path.translate(_MD_INLINE_ESCAPE)}"))
    document.extend(_origin_lines(origin, style))
    if node.timestamp is not None:
        document.append(_item(0, f"**Observed:** {style.at(node.timestamp)}"))
    document.extend(["", "**Finding**", ""])
    document.extend(_format_reason(line, 0, style))
    return "\n".join(document)


def _node_facts(node: StatusSnapshot, style: TimeStyle,
                since: datetime | None, before: bool = False,
                began: str = "", origin: Origin | None = None) -> list[str]:
    """The fact list under the heading, in the detail page's own order and words.

    Two statuses can appear, and the difference between them is the point.
    **Reported** is what the check measured.  **Shown as** appears only when the
    node presents something else — which is a pin, the one transform that makes
    them differ (`_own_code`) — and names it rather than letting the reader
    believe the tree measured `maintenance`.
    """
    facts = [
        _item(0, f"**Path:** {node.path.translate(_MD_INLINE_ESCAPE)}"),
        *_origin_lines(origin, style),
        _item(0, f"**Reported:** {_code_word(node.reported_code)}"),
    ]
    if node.own_code != node.reported_code:
        # a node no check has written has no reading for the pin to stand over
        # (ADR-0115 decision 6), and saying it was measured would invent one
        measured = ("no check has written this node." if node.timestamp is None
                    else "the reported reading above is what the check measured.")
        facts.append(_item(0,
            f"**Shown as:** {_code_word(node.own_code)} — a maintenance pin is "
            f"in force; {measured}"))
    # The pin itself directly under the line that says one is in force, rather
    # than at the foot of the list: the two are one statement, and five time
    # facts between them is where a reader stops connecting them.
    if node.maintenance_entry is not None:
        facts.extend(_maintenance_lines(0,
            node.maintenance_entry.reason,
            node.maintenance_entry.set_by,
            node.maintenance_entry.expires_at,
            style,
        ))
    facts.extend(_time_facts(node, style, since, before, began))
    return facts


def _origin_lines(origin: Origin | None, style: TimeStyle) -> list[str]:
    """Where a document is from and when it was made (ADR-0115 decision 1), or
    nothing for a caller that has neither to state. The address stands bare: the
    renderer links it, and a reader of the Markdown reads it as it is."""
    if origin is None:
        return []
    return [_item(0, f"**Dashboard:** {origin.dashboard}"),
            _item(0, f"**As of:** {style.at(origin.made)}")]


def _time_facts(node: StatusSnapshot, style: TimeStyle,
                since: datetime | None,
                before: bool = False, began: str = "") -> list[str]:
    """When: the period, the observation and the run, as the page's Time card
    states them.

    The observation, and the period it bounds (ADR-0027): no transition of the
    node's own means there is no period to bound. A status that still holds is
    stated since when, and when it was last observed — never *until* the latest
    reading, which is no end (ADR-0099 decision 1). A period that a pin began —
    its end, or a line's pin set or ended — says so: the node began to show its
    status then, which is not when its check began to read it.

    **A period is stated wherever there is one** (ADR-0115 decision 6): a pinned
    node that no check has written has shown *maintenance* since its pin, and
    *Not yet observed* alone would say nothing of that. The sentence is for a node
    with neither an observation nor a period.

    **The period is the own status's, and a node above others names it so**
    (ADR-0123 decision 3): ***Its own status ok** since …*, beneath a *Shown as*
    that says what the node rolls up to. What such a node shows counts the nodes
    beneath it (``counts_beneath``), and *Status ok since …* said that of the
    node. A node in maintenance, and one with nothing beneath it, show their own
    status and keep *Status*.
    """
    facts: list[str] = []
    if since is not None:
        named = "Its own status" if node.counts_beneath else "Status"
        facts.append(_item(0,
            f"**{named} {node.own_code.name.lower()}** since "
            f"{'before ' if before else ''}{style.at(since)}"
            f"{', ' + began if began else ''}"))
        if node.timestamp is not None:
            facts.append(_item(0, f"**Last observed:** {style.at(node.timestamp)}"))
    elif node.timestamp is None:
        facts.append(_item(0, "**Not yet observed.**"))
    else:
        facts.append(_item(0, f"**Observed:** {style.at(node.timestamp)}"))
    # the node's own reading: a branch is stale while a node beneath it is, and
    # that node's document says when *it* was last observed
    if node.own_stale:
        facts.append(_item(0,
            f"**Stale** — last observed {format_span(node.age_seconds)} ago"))
    if node.run is not None and node.run.next_run_at is not None:
        facts.append(_item(0, f"**Next update:** {style.at(node.run.next_run_at)}"))
    if node.run is not None and node.run.wall_seconds is not None:
        facts.append(_item(0,
            f"**Last run took:** {format_span(node.run.wall_seconds)}"))
    # The period where there is one and the freshness promise where there is not,
    # exactly as the page's Time card states them (ADR-0081): "checked every" is
    # true of a check and of nothing else, and the instance's own nodes are read on
    # no check's schedule.
    if node.frequency_seconds:
        facts.append(_item(0,
            f"**Checked every:** {format_duration(node.frequency_seconds)}"))
    elif node.stale_after_seconds:
        facts.append(_item(0,
            f"**Goes stale after:** {format_tolerance(node.stale_after_seconds)}"))
    return facts


def _code_word(code: StatusCode) -> str:
    """A status as this document says it: the word and the portable cue."""
    return f"{code.name.lower()} {status_icon(code)}"


def _format_node(node: StatusSnapshot, depth: int, style: TimeStyle,
                 periods: Periods | None = None) -> list[str]:
    """One node of an outline, and what is listed beneath it.

    A leaf is listed where it is not ok. A branch is a name above what is listed
    beneath it — and where it holds something of its own, it says that first
    (ADR-0115 decision 3): without its pin, what a pin on a container silences
    reads as alarming, and a container with a status of its own above healthy
    nodes would not be in the outline at all.
    """
    if node.children:
        beneath: list[str] = []
        for child in node.children:
            beneath.extend(_format_node(child, depth + 1, style, periods))
        if _speaks(node):
            return [*_finding(node, _shown(node), depth, style, periods), *beneath]
        return [_item(depth, _label(node)), *beneath] if beneath else []
    if node.code == StatusCode.OK:
        return []
    return _finding(node, node.code, depth, style, periods)


def _speaks(node: StatusSnapshot) -> bool:
    """Whether a branch holds something of its own for an outline to say: what it
    shows of its own is not ok — a status it declares, a pin on it, which it shows
    as *maintenance*, or a reading of its own gone stale. `UNDEFINED` is a branch
    that declares nothing, which is a name and no finding."""
    return _shown(node) not in (StatusCode.OK, StatusCode.UNDEFINED)


def _finding(node: StatusSnapshot, code: StatusCode, depth: int, style: TimeStyle,
             periods: Periods | None) -> list[str]:
    """A node an outline lists: its name, the cue of ``code`` — what a leaf shows,
    and a branch's own status — since when, its pin and its lines."""
    state = status_icon(code)
    qualifiers: list[str] = []
    # its own reading: a branch is stale while a node beneath it is, and that node
    # says so on its own line
    if node.own_stale:
        qualifiers.append("stale")
    if (code == StatusCode.MAINTENANCE
            and node.reported_code not in (
                StatusCode.MAINTENANCE, StatusCode.UNDEFINED)):
        qualifiers.append(f"reported {status_icon(node.reported_code)}")
    if qualifiers:
        state += f" ({'; '.join(qualifiers)})"

    lines = [_item(depth, f"{_label(node)} {state}{_stood(node, style, periods)}")]
    if node.maintenance_entry is not None:
        lines.extend(_maintenance_lines(depth + 1,
            node.maintenance_entry.reason,
            node.maintenance_entry.set_by,
            node.maintenance_entry.expires_at,
            style,
        ))
    for reason in node.reasons:
        lines.extend(_format_reason(reason, depth + 1, style))
    return lines


def _stood(node: StatusSnapshot, style: TimeStyle, periods: Periods | None) -> str:
    """*— error since …* for a node the tree keeps a period of (ADR-0115 decision
    2), in the words its page's Time card writes: the status the node itself
    shows, *before* where the instant is a bound, and what began the period where
    a pin did. Empty where nothing is kept, and for a caller that asks nothing."""
    standing = periods(node) if periods is not None else None
    if standing is None:
        return ""
    return (f" — {node.own_code.name.lower()} since "
            f"{'before ' if standing.before else ''}{style.at(standing.at)}"
            f"{', ' + standing.began if standing.began else ''}")


def _shown(node: StatusSnapshot) -> StatusCode:
    """What a node shows of its own. For a node with nothing beneath it that is its
    status. For a branch it is the part of its status that is its own, since what
    it rolls up to is said by the nodes beneath it: what the tree counts for the
    node itself (``own_counted``) — its own status, or, where its own reading is
    stale, that reading degraded (ADR-0005). Without that a gateway whose check
    stopped, above backends that are well, would be in no count and no outline of a
    tree that shows a warning.
    """
    if not node.children:
        return node.code
    return node.own_counted


def _counted(node: StatusSnapshot) -> list[StatusSnapshot]:
    """Every node beneath ``node`` that shows a status of its own (ADR-0115
    decision 4), in the document's order: a node with nothing beneath it, and a
    branch that declares a status or is pinned — a pinned one shows *maintenance*.
    A branch that declares nothing is a name, and counting it would count its
    nodes twice."""
    found: list[StatusSnapshot] = []
    for child in node.children:
        if not child.children or _shown(child) is not StatusCode.UNDEFINED:
            found.append(child)
        found.extend(_counted(child))
    return found


def _nodes(count: int) -> str:
    return f"{count} {'node' if count == 1 else 'nodes'}"


def _tally(nodes: list[StatusSnapshot]) -> str:
    """*2 error ⛔, 3 warn ⚠️* — how many of ``nodes`` show each status, the worst
    first."""
    parts = []
    for code in (StatusCode.ERROR, StatusCode.WARN, StatusCode.UNDEFINED,
                 StatusCode.MAINTENANCE):
        number = sum(1 for node in nodes if _shown(node) is code)
        if number:
            parts.append(f"{number} {_code_word(code)}")
    return ", ".join(parts)


def _label(node: StatusSnapshot) -> str:
    # Two rules, one predicate, both in `titles.py`.  A title that only repeats the
    # name is not a better label for it, here least of all: this document is read
    # with no chips and no styling, where `critical` alone says everything
    # *Critical* would.  And a title with no word in it cannot stand in for the name
    # at all (ADR-0061) — a band titled 🔴 would otherwise paste into a ticket as a
    # circle and nothing else, which is the failure this surface is least able to
    # survive: a pasted document outlives the person who pasted it.
    name, title = label_parts(node.name, node.title)
    parts = []
    if name:
        # A name is structural data, not authored Markdown (`_MD_INLINE_ESCAPE`).
        parts.append(name.translate(_MD_INLINE_ESCAPE))
    if title:
        # Titles are defined as short inline Markdown.  Collapse an accidental
        # newline so even malformed metadata cannot escape the item it labels.
        parts.append(" ".join(title.splitlines()))
    return " ".join(parts)


def _format_reason(reason: ReasonLine, depth: int,
                   style: TimeStyle) -> list[str]:
    lines = _markdown_item(depth, reason.text, _reason_cues(reason))
    if reason.maintenance is not None:
        lines.extend(_maintenance_lines(depth + 1,
            reason.maintenance.reason,
            reason.maintenance.set_by,
            reason.maintenance.expires_at,
            style,
        ))
    return lines


def _reason_cues(reason: ReasonLine) -> str:
    """What a line claims about itself before its text begins (ADR-0042).

    **Its own code**, where it declared one.  On the page that claim is a tinted
    surface plus a shape cue whose accessible name is the code word; a document
    has neither color nor tint, so it takes the same portable cue the nodes take
    — and a line that declared no code still takes none, which is the whole
    distinction: it carries its node's severity, and the node has already said so.

    **Work in flight**, as the word.  The page's italic is *the glance, not the
    channel* — the ADR is explicit that the text has to carry the fact — and a
    pasted document has no glance at all, so what is left is to write it.  A word
    in parentheses rather than emphasis, which the same decision turned down:
    `*…*` is a convention a reader has to know, and it does not survive being
    clipped.
    """
    cues = []
    if reason.code is not None:
        cues.append(status_icon(reason.code))
    if reason.running:
        cues.append("(running)")
    return " ".join(cues)


def _maintenance_lines(depth: int, reason: str, set_by: str,
                       expires_at: datetime, style: TimeStyle) -> list[str]:
    """One maintenance reading plus its authored Markdown explanation.

    Authorship and expiry are structural text; the explanation is source content and
    stays Markdown, nested below that reading exactly like a check reason.  Keeping
    them as separate items means a multiline list or fenced block cannot swallow the
    attribution line or be flattened into literal punctuation.

    The expiry is written through ``style``, offset and all: *until 10:00* in a
    pasted document is worth less than nothing if the reader's ten o'clock is an
    hour from the one the pin ends at.
    """
    actor = set_by or "an admin"
    attribution = (f"🛠️ Maintenance — by {actor}, until {style.at(expires_at)}"
                   ).translate(_MD_INLINE_ESCAPE)
    lines = [_item(depth, attribution)]
    if reason and reason != "maintenance":
        lines.extend(_markdown_item(depth + 1, reason))
    return lines


def _item(depth: int, text: str) -> str:
    return f"{'  ' * depth}- {text}"


def _markdown_item(depth: int, markdown: str, cues: str = "") -> list[str]:
    """Nest one authored Markdown block inside a list item, behind optional cues.

    Prefixing the first line with the bullet and every continuation with the
    item's content indent preserves links, paragraphs and fenced code blocks at
    arbitrary tree depth.

    ``cues`` join that first line — except where it **opens a fence**, which is
    the one construct that cannot share a line with anything: ```` ⛔ ``` ```` is
    an ordinary paragraph, the fence it should have opened never opens, and the
    closing one goes on to mean something else entirely.  A text that starts with
    one therefore takes its cues on the item's own line and begins on the next.
    Every other opener degrades to a paragraph and loses no content, so this stays
    narrow on purpose: it is a guard against corruption, not a style rule.
    """
    raw_lines = markdown.splitlines() or [""]
    prefix = "  " * depth
    continuation = "  " * (depth + 1)
    if cues and _OPENS_A_FENCE.match(raw_lines[0]):
        return [f"{prefix}- {cues}"] + [
            f"{continuation}{line}" for line in raw_lines
        ]
    head = f"{cues} {raw_lines[0]}" if cues else raw_lines[0]
    return [f"{prefix}- {head}"] + [
        f"{continuation}{line}" for line in raw_lines[1:]
    ]
