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
caller hands in, since a formatter has no request to read either off — and, where its
node has a handbook, the handbook's address (ADR-0133 decision 3). The origin says
the address of any node's handbook, from the base the document was made from, so a
link a text writes in the short form leaves the instance written out to it, in every
text the document carries (:func:`written_out`). And every node an outline lists
says since when it has shown its status, which the caller answers too
(:data:`Periods`): the tree keeps that, and this module reads no tree.

Every instant either document writes names its **offset** (:class:`TimeStyle`).
The pages render local time and stay silent about the zone, which is right for a
screen somebody is standing in front of; a pasted incident is read in another
office, where `14:32` alone is a guess.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import TYPE_CHECKING, Protocol

from little_sister.config import DEFAULT_TIME_FORMAT
from little_sister.details import Row
from little_sister.pins import MAINTENANCE, NO_NOTE, Pin
from little_sister.render import write_out
from little_sister.spans import format_duration, format_span, format_tolerance
from little_sister.status import StatusCode
from little_sister.titles import label_parts
from little_sister.tree import (
    AGGREGATION_RULE,
    CAUSE_LINE_PIN_ENDED,
    CAUSE_LINE_PIN_SET,
    CAUSE_LINE_SEEN_EDITED,
    CAUSE_LINE_SEEN_ENDED,
    CAUSE_LINE_SEEN_SET,
    CAUSE_PIN_EDITED,
    CAUSE_PIN_ENDED,
    CAUSE_PIN_SET,
    CAUSE_REMOVED,
    CAUSE_RULE,
    CAUSE_SEEN_EDITED,
    CAUSE_SEEN_ENDED,
    CAUSE_SEEN_SET,
    CAUSE_STALE,
    MAINTENANCE_RULE,
    SEEN_RULE,
    HandledRule,
    Period,
    ReasonLine,
    StatusSnapshot,
    rules_beneath,
)

if TYPE_CHECKING:
    from little_sister.notes import Note

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

# What began a period of what a node above others shows, as its document says it in
# one clause after the instant (ADR-0132 decision 6): History's words, the node named
# where `{}` stands — *load-fixtures beneath it*, or a dependency's full path. Every
# other cause is a reading's, as History counts it: a check's run, the end of a wait,
# which the reading that completed its count wrote, a row of a log written before a
# row said its cause, and a node that moved without a row of its own.
_BEGUN_BY = {
    CAUSE_PIN_SET: "a pin set on {}",
    CAUSE_PIN_EDITED: "a pin edited on {}",
    CAUSE_PIN_ENDED: "a pin ended on {}",
    CAUSE_LINE_PIN_SET: "a line's pin set on {}",
    CAUSE_LINE_PIN_ENDED: "a line's pin ended on {}",
    CAUSE_REMOVED: "the removal of {}",
    CAUSE_STALE: "{} going stale",
    CAUSE_RULE: "a rule beginning to count {}",
    CAUSE_SEEN_SET: "{} marked seen",
    CAUSE_SEEN_EDITED: "the seen on {} changed",
    CAUSE_SEEN_ENDED: "{} no longer seen",
    CAUSE_LINE_SEEN_SET: "a line of {} marked seen",
    CAUSE_LINE_SEEN_EDITED: "the seen on a line of {} changed",
    CAUSE_LINE_SEEN_ENDED: "a line of {} no longer seen",
}
_A_READING = "a reading of {}"
# The same where the node's own change began it: *of its own*, *on it*.
_BEGUN_BY_ITS_OWN = {
    CAUSE_PIN_SET: "a pin set on it",
    CAUSE_PIN_EDITED: "a pin edited on it",
    CAUSE_PIN_ENDED: "a pin ended on it",
    CAUSE_LINE_PIN_SET: "a line's pin set on it",
    CAUSE_LINE_PIN_ENDED: "a line's pin ended on it",
    CAUSE_REMOVED: "its own removal",
    CAUSE_STALE: "its own reading going stale",
    CAUSE_RULE: "a rule beginning to count it",
    CAUSE_SEEN_SET: "its own failure marked seen",
    CAUSE_SEEN_EDITED: "the seen on it changed",
    CAUSE_SEEN_ENDED: "its own failure no longer seen",
    CAUSE_LINE_SEEN_SET: "a line of its own marked seen",
    CAUSE_LINE_SEEN_EDITED: "the seen on a line of its own changed",
    CAUSE_LINE_SEEN_ENDED: "a line of its own no longer seen",
}
_A_READING_OF_ITS_OWN = "a reading of its own"

# A CommonMark fence opener: up to three spaces of indent, then three or more
# backticks or tildes.  The one block construct that must own its line
# (:func:`_markdown_item`).
_OPENS_A_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")


def status_icon(code: StatusCode) -> str:
    """The portable, non-color status cue used by the copy document."""
    return _STATUS_ICON[code]


def written_out(text: str, *, inline: bool = False, handbook: str = "") -> str:
    """A text as a document carries it out of the instance (ADR-0133 decisions 4 and
    5): each status it names in a placeholder's braces, ``{error}``, written as this
    document writes a status, *error ⛔*, wherever the page draws one as its sign;
    given ``handbook`` — the full address of the handbook of the node the text belongs
    to — each link it writes in the short form, ``handbook#sign-in``, written out to
    that address, wherever the page leads one into it; and the rest as written.
    ``inline`` for a text the page renders on one line — a title — and not for one it
    renders as a block, which is every other.

    The one function the library offers for it, so that the Copy document — its
    lines, its notes, its titles, what a run found and ran with — and a ticket a
    package drafts from a node — ``little-sister-jira``'s — write a status and a link
    into a handbook the one way. What the page draws and where it leads is the
    renderer's to say (:func:`~little_sister.render.write_out`), so what the page shows
    as written — in code, escaped — stays as written here."""
    return write_out(text, _code_word, handbook=handbook, inline=inline)


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
    ``handbooks`` says the absolute address of a node's handbook by its path, from
    the base ``dashboard`` came by (ADR-0133 decisions 3 and 4): the *Handbook* line
    of a node that has one, and where a link written in the short form leads.

    Handed in, since a formatter has no request. A caller that has none either —
    a fixture sheet, a test — passes no origin, and the document claims none; one
    that passes no ``handbooks`` writes no *Handbook* line, and leaves the short
    form as written.
    """

    dashboard: str
    made: datetime
    handbooks: Callable[[str], str] | None = None

    def handbook(self, path: str) -> str:
        """The absolute address of the handbook of the node at ``path``, or ``""``
        where this origin cannot say it."""
        return self.handbooks(path) if self.handbooks is not None else ""


def _handbook_of(origin: Origin | None, path: str) -> str:
    """Where a link a text of the node at ``path`` writes in the short form leads,
    written out (ADR-0133 decision 4), or ``""`` where the document cannot say."""
    return origin.handbook(path) if origin is not None else ""


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


@dataclass(frozen=True)
class NotesSaid:
    """What a node's document says of its notes (ADR-0140): the newest, whole, and
    how many more its Notes view lists — at ``view``, that view's absolute address,
    where the caller can say it. Handed in, as the origin is: this module reads no
    notes."""
    newest: Note
    more: int = 0
    view: str = ""


def format_copy_markdown(root: StatusSnapshot | None, style: TimeStyle, *,
                         periods: Periods | None = None,
                         origin: Origin | None = None) -> str:
    """Return the outline of what needs attention below ``root`` as deterministic
    Markdown.

    The synthetic root is omitted.  A healthy leaf contributes nothing; a group
    contributes where a descendant does, or where it holds something of its own
    (:func:`_speaks`).  Snapshot sibling order is preserved (the tree has already
    made it deterministic), and all reasons remain in their check-provided order.
    With ``periods``, each node the outline lists says since when it has shown its
    status (ADR-0115 decision 2), and with ``origin`` the links its texts write in
    the short form lead to their nodes' handbooks (ADR-0133 decision 4).
    """
    if root is None:
        return ""
    lines: list[str] = []
    for child in root.children:
        lines.extend(_format_node(child, 0, style, periods, origin))
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
    stated like any other: in the head, above a count that says what it holds.
    """
    code = root.code if root is not None else StatusCode.UNDEFINED
    pin = root.maintenance_entry if root is not None else None
    document = [f"## little-sister status {status_icon(code)}", "",
                *_origin_lines(origin, style, root)]
    if pin is not None and root is not None:
        document.extend(_maintenance_lines(0, pin.note, pin.set_by,
                                           pin.expires_at, style,
                                           _handbook_of(origin, root.path)))
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
            (f"**Under the pin** — {len(wrong)} of {_nodes(len(counted))} "
             f"would need attention: {_tally(wrong)}" if pin is not None else
             f"**Needs attention** — {len(wrong)} of {_nodes(len(counted))}: "
             f"{_tally(wrong)}"),
            "", format_copy_markdown(root, style, periods=periods, origin=origin)])
    return "\n".join(document)


def format_node_markdown(node: StatusSnapshot, style: TimeStyle,
                         since: datetime | None = None, *, before: bool = False,
                         began: str = "", origin: Origin | None = None,
                         periods: Periods | None = None,
                         details: Sequence[Row] = (),
                         tags: Sequence[tuple[str, str]] = (),
                         notes: NotesSaid | None = None) -> str:
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
    its maintenance ended*, *when a line's pin was set* — in the Time card's own
    words (decision 8, ADR-0107 decision 3).

    **A node with nodes beneath it hands over what is beneath it**
    (:func:`_format_branch`, ADR-0115 decision 5): what a leaf has, its check's
    reading, is the one thing such a node may not have, and what is wrong with a
    host is on its children. ``periods`` dates what that outline lists.

    **Its details follow its facts** (:func:`_details_block`, ADR-0133 decision 6):
    ``details`` are the rows of its *About* card, those given down to it among them,
    which the caller resolves — the object's name and whom to ask are what a ticket
    needs, and a document pasted elsewhere is read where nobody opens the card. Its
    **tags** follow them (:func:`_tags_block`, ADR-0139 decision 4): ``tags`` are
    every tag it carries, each with what its ``tags.yaml`` says it means. Its
    **notes** follow its reasons (:func:`_notes_block`, ADR-0140): the newest whole,
    and how many more its Notes view lists.

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
        return _format_branch(node, style, since, before, began, origin, periods,
                              details, tags, notes)
    handbook = _handbook_of(origin, node.path)
    document = [f"## {_label(node, handbook)} {status_icon(node.reported_code)}", ""]
    document.extend(_node_facts(node, style, since, before, began, origin))
    document.extend(_details_block(details, origin))
    document.extend(_tags_block(tags))
    if node.reasons:
        document.extend(["", "**Reasons**", ""])
        for reason in node.reasons:
            document.extend(_format_reason(reason, 0, style, handbook))
    document.extend(_notes_block(notes, style, handbook))
    document.extend(_run_blocks(node, handbook))
    return "\n".join(document)


def _notes_block(notes: NotesSaid | None, style: TimeStyle,
                 handbook: str = "") -> list[str]:
    """The node's **Notes**, after its reasons (ADR-0140): the newest note whole — who
    wrote it and when, who changed it last where somebody did, whether it is a pin's,
    the line it is on as it read then, and its words — and how many more its Notes
    view lists. Nothing where no note is written on the node.

    A note is not a reading, so it is a block of its own and says whose words it is:
    what somebody knew, handed over beside what the check measured. Its words are
    an admin's Markdown, nested below the attribution as a pin's note is
    (:func:`_maintenance_lines`), and the line's are the check's, written as the
    line was written then."""
    if notes is None:
        return []
    note = notes.newest
    said = f"By {note.created_by or 'an admin'}, {style.at(note.created_at)}"
    if note.set_at != note.created_at:
        said += (f"; last changed by {note.set_by or 'an admin'}, "
                 f"{style.at(note.set_at)}")
    if note.pin:
        said += " — the note of a pin"
    said = said.translate(_MD_INLINE_ESCAPE)
    if note.slug:
        line = next((" ".join(seen.text.split()) for seen in note.context.lines
                     if seen.slug == note.slug), "")
        said += (f" — on its line: {written_out(line, inline=True, handbook=handbook)}"
                 if line else " — on one of its lines")
    block = ["", "**Notes**", "", _item(0, said),
             *_markdown_item(1, written_out(note.text, handbook=handbook))]
    if notes.more:
        block.append(_item(0, f"{notes.more} more on its Notes view"
                              + (f": {notes.view}" if notes.view else "")))
    return block


def _run_blocks(node: StatusSnapshot, handbook: str = "") -> list[str]:
    """What the node's run found and what it ran with, each under its heading.

    `report` before `config` — what the run found is why the page was opened,
    what it ran with is the reference beside it (`_node_facts.html` orders the
    cards the same way).  Both are the check's own authored Markdown and land
    at the margin, where a list or a fence renders as itself.
    """
    blocks: list[str] = []
    if node.report:
        blocks.extend(["", "**Report**", "",
                       written_out(node.report, handbook=handbook)])
    if node.config:
        blocks.extend(["", "**Configuration**", "",
                       written_out(node.config, handbook=handbook)])
    return blocks


def _format_branch(node: StatusSnapshot, style: TimeStyle,
                   since: datetime | None,
                   before: bool, began: str, origin: Origin | None,
                   periods: Periods | None, details: Sequence[Row] = (),
                   tags: Sequence[tuple[str, str]] = (),
                   notes: NotesSaid | None = None) -> str:
    """A node with nodes beneath it, handed over (ADR-0115 decision 5).

    Its heading carries the cue of what the node **shows**: a host whose check
    grades its children declares nothing itself, and the cue of what it reported
    would be *undefined* over a full disk and over nothing wrong alike.
    **Reported** stands where the node declares a status of its own, **Shown as**
    where it shows something else, with where that comes from — the nodes beneath
    it alone where every line of its own is pinned, which then counts for
    nothing and cancels nothing (ADR-0124) — and no claim about
    each node beneath it: one that is pinned, one that waits and one reached
    through a failing check count for nothing in what their branch shows
    (ADR-0039).

    Then the period of what it shows, with what began it, where that period is of
    what it shows (ADR-0132 decision 6); the period of its own status, named as that
    (ADR-0123 decision 3), and its observation, as far as it has them, its details
    (ADR-0133 decision 6), its tags (ADR-0139 decision 4), its own lines, its notes
    (ADR-0140), and **Beneath it**: how many of the nodes beneath it need attention
    and the outline of those, which is the tree document's own outline begun here —
    or that nothing does. Under a pin the count says what the pin is holding.

    Then **what is handled beneath it** (:func:`_handled_block`, ADR-0135 decision
    7): every rule that stands beneath the node, as its page's *why* card lists
    them, where that card stands.
    """
    beneath = _counted(node)
    declares = node.reported_code is not StatusCode.UNDEFINED
    handbook = _handbook_of(origin, node.path)
    document = [f"## {_label(node, handbook)} {status_icon(node.code)}", "",
                _item(0, f"**Path:** {node.path.translate(_MD_INLINE_ESCAPE)}"),
                *_origin_lines(origin, style, node)]
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
            node.maintenance_entry.note,
            node.maintenance_entry.set_by,
            node.maintenance_entry.expires_at,
            style, handbook,
        ))
    elif node.acknowledgment is not None:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — its own failure is seen, "
            f"and the level above counts it as {_code_word(StatusCode.OK)}."))
        document.extend(_acknowledgment_lines(0, node.acknowledgment, style,
                                              handbook))
    elif node.lines_silenced:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — rolled up from {under} "
            f"beneath it. Every line of its own is in maintenance."))
    elif not declares:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — rolled up from {under} "
            f"beneath it. It reports nothing of its own."))
    elif node.code != node.reported_code:
        document.append(_item(0,
            f"**Shown as:** {_code_word(node.code)} — rolled up from its own "
            f"reading and {under} beneath it."))
    document.extend(_time_facts(node, style, since, before, began))
    document.extend(_details_block(details, origin))
    document.extend(_tags_block(tags))
    if node.reasons:
        document.extend(["", "**Reasons**", ""])
        for reason in node.reasons:
            document.extend(_format_reason(reason, 0, style, handbook))
    document.extend(_notes_block(notes, style, handbook))
    listed: list[str] = []
    for child in node.children:
        listed.extend(_format_node(child, 0, style, periods, origin))
    wrong = sum(1 for found in beneath if _shown(found) is not StatusCode.OK)
    if not listed:
        document.extend(["", "**Beneath it** — nothing needs attention."])
    elif node.maintenance_entry is not None:
        document.extend([
            "", f"**Beneath it**, under the pin — {wrong} of "
                f"{_nodes(len(beneath))} would need attention", "", *listed])
    else:
        document.extend([
            "", f"**Beneath it** — {wrong} of {_nodes(len(beneath))} "
                f"{'needs' if wrong == 1 else 'need'} attention", "", *listed])
    document.extend(_handled_block(node, style, origin))
    document.extend(_run_blocks(node, handbook))
    return "\n".join(document)


def _handled_block(node: StatusSnapshot, style: TimeStyle,
                   origin: Origin | None) -> list[str]:
    """What is handled beneath a branch, as its page's *why* card says it (ADR-0135
    decision 7): under its total, by job — in maintenance, accepted (ADR-0142) and by
    a rule (ADR-0137) — each rule with the node it stands on, beneath the branch, a
    line's with that line, and what its part reads under it where that is a failure,
    who set it and until when. Written where the card stands, a branch that shows an
    error, a warning or ok; a branch in maintenance says why in its own pin, and
    *Beneath it, under the pin* lists what it holds."""
    if node.code not in (StatusCode.ERROR, StatusCode.WARN, StatusCode.OK):
        return []
    rules = rules_beneath(node)
    if not rules:
        return []
    lines = ["", f"**Handled beneath it** — {len(rules)}", ""]
    for jobs, title in (((MAINTENANCE_RULE,),
                         f"{status_icon(StatusCode.MAINTENANCE)} In maintenance"),
                        ((SEEN_RULE,), f"{_ACCEPTED_SIGN} Accepted"),
                        ((AGGREGATION_RULE,), "§ By a rule")):
        rows = [rule for rule in rules if rule.job in jobs]
        if not rows:
            continue
        lines.append(_item(0, title))
        for rule in rows:
            lines.extend(_handled_rule(rule, 1, style,
                                       _handbook_of(origin, rule.path)))
    return lines


def _handled_rule(rule: HandledRule, depth: int, style: TimeStyle,
                  handbook: str = "") -> list[str]:
    """One rule a branch's *why* lists: *db/pool, reads error ⛔ — by ada, until …*,
    or *a line of db/pool* with the line's text nested beneath it, its own Markdown
    as an outline writes a line's."""
    name = rule.name.translate(_MD_INLINE_ESCAPE)
    said = f"a line of {name}" if rule.slug else name
    if rule.reads is not None:
        said += f", reads {_code_word(rule.reads)}"
    if rule.rule is not None:
        # A configured rule (ADR-0137): what the part counts as, by which rule and
        # since when — it stands for good, its file saying who set it.
        at = rule.rule
        counts = "nothing" if at.counts is None else _code_word(at.counts)
        lines = [_item(depth, f"{said}, counts {counts} — by the rule "
                              f"{at.rule.name.translate(_MD_INLINE_ESCAPE)}, since "
                              f"{at.rule.since.isoformat()}")]
    elif rule.entry is not None and rule.entry.kind != MAINTENANCE:
        # A person's acknowledgment (ADR-0142): its kind, who, and what ends it.
        entry = rule.entry
        actor = (entry.set_by or "an admin").translate(_MD_INLINE_ESCAPE)
        until = ("" if entry.expires_at is None
                 else f", or until {style.at(entry.expires_at)} at the latest")
        lines = [_item(depth, f"{said} — {entry.kind} by {actor}, until it "
                              f"changes{until}")]
    else:
        assert rule.entry is not None and rule.entry.expires_at is not None
        actor = (rule.entry.set_by or "an admin").translate(_MD_INLINE_ESCAPE)
        lines = [_item(depth, f"{said} — by {actor}, until "
                              f"{style.at(rule.entry.expires_at)}")]
    if rule.slug:
        lines.extend(_markdown_item(depth + 1,
                                    written_out(rule.line, handbook=handbook)))
    return lines


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
    handbook = _handbook_of(origin, node.path)
    document = [f"## {_label(node, handbook)} {status_icon(node.reported_code)}", ""]
    document.append(_item(0, f"**Path:** {node.path.translate(_MD_INLINE_ESCAPE)}"))
    document.extend(_origin_lines(origin, style, node))
    if node.timestamp is not None:
        document.append(_item(0, f"**Observed:** {style.at(node.timestamp)}"))
    document.extend(["", "**Finding**", ""])
    document.extend(_format_reason(line, 0, style, handbook))
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
        *_origin_lines(origin, style, node),
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
            node.maintenance_entry.note,
            node.maintenance_entry.set_by,
            node.maintenance_entry.expires_at,
            style, _handbook_of(origin, node.path),
        ))
    if node.acknowledgment is not None:
        facts.extend(_acknowledgment_lines(0, node.acknowledgment, style,
                                           _handbook_of(origin, node.path)))
    facts.extend(_time_facts(node, style, since, before, began))
    return facts


def _origin_lines(origin: Origin | None, style: TimeStyle,
                  node: StatusSnapshot | None = None) -> list[str]:
    """Where a document is from and when it was made (ADR-0115 decision 1), or
    nothing for a caller that has neither to state — and, where the document's
    ``node`` has a handbook, the handbook's address beside the page's (ADR-0133
    decision 3), so that whoever reads a ticket finds the runbook in one click. An
    address stands bare: the renderer links it, and a reader of the Markdown reads
    it as it is."""
    if origin is None:
        return []
    lines = [_item(0, f"**Dashboard:** {origin.dashboard}")]
    if node is not None and node.has_handbook:
        if handbook := origin.handbook(node.path):
            lines.append(_item(0, f"**Handbook:** {handbook}"))
    lines.append(_item(0, f"**As of:** {style.at(origin.made)}"))
    return lines


def written_details(rows: Sequence[Row],
                    handbooks: Callable[[str], str] | None = None,
                    ) -> tuple[tuple[str, str], ...]:
    """A node's details as a text that leaves the instance carries them (ADR-0133
    decision 6): its *About* card's rows, key and value, in the card's order, those
    given down to it among them, each value written out as every text is
    (:func:`written_out`) — a link in the short form to the handbook of the node the
    value is given on, whose absolute address ``handbooks`` says by its path, and as
    written where nothing says it. The key is the team's name for the value, as
    written. The Copy document's *Details* block and a draft a package makes from a
    node — ``little-sister-jira``'s, through its slot — write them the one way."""
    return tuple(
        (row.key, written_out(row.text, inline=True,
                              handbook=handbooks(row.at) if handbooks is not None
                              else ""))
        for row in rows)


def _details_block(details: Sequence[Row], origin: Origin | None) -> list[str]:
    """A node's details under their heading (ADR-0133 decision 6): its *About* card's
    table as key and value, in the card's order, those given down to it among them —
    or nothing where it has none. A key is the team's name for a value and is written
    as a name is, its Markdown neutralised; a value is a line of Markdown, written out
    as every text the document carries is (:func:`written_details`)."""
    if not details:
        return []
    lines = ["", "**Details**", ""]
    for key, value in written_details(
            details, origin.handbooks if origin is not None else None):
        lines.append(_item(0, f"**{key.translate(_MD_INLINE_ESCAPE)}:** {value}"))
    return lines


def _tags_block(tags: Sequence[tuple[str, str]]) -> list[str]:
    """A node's tags under their heading (ADR-0139 decision 4): every tag it
    carries, in its *About* card's order, each with the line its ``tags.yaml`` gives
    it — or nothing where it carries none. A tag is a word and a line plain text, so
    each is written as a name is, its Markdown neutralised."""
    if not tags:
        return []
    lines = ["", "**Tags**", ""]
    for tag, line in tags:
        meaning = f" — {line.translate(_MD_INLINE_ESCAPE)}" if line else ""
        lines.append(_item(0, f"**{tag}**{meaning}"))
    return lines


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

    **Above it, the period of what such a node shows** (ADR-0132 decision 6,
    :func:`_shown_period`), where that period is of what it shows: ***Status
    error** since …, begun by a reading of load-fixtures beneath it*. A node that
    declares nothing has that line above its observation, and *Not yet observed*
    only where it has neither.
    """
    facts: list[str] = []
    shown = _shown_period(node, style)
    if shown is not None:
        facts.append(shown)
    if since is not None:
        named = "Its own status" if node.counts_beneath else "Status"
        facts.append(_item(0,
            f"**{named} {node.own_code.name.lower()}** since "
            f"{'before ' if before else ''}{style.at(since)}"
            f"{', ' + began if began else ''}"))
        if node.timestamp is not None:
            facts.append(_item(0, f"**Last observed:** {style.at(node.timestamp)}"))
    elif node.timestamp is None:
        if shown is None:
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


def _shown_period(node: StatusSnapshot, style: TimeStyle) -> str | None:
    """The period of what ``node`` shows, as its document states it first among its
    time facts (ADR-0132 decision 6, ADR-0115 decision 5): ***Status error** since …,
    begun by a reading of load-fixtures beneath it* — on a node whose status counts
    the nodes beneath it, and only where the period is of what it shows, which the
    snapshot has decided (:attr:`StatusSnapshot.period`). ``None`` elsewhere: on a
    leaf, whose one period is its own; on a node whose own status cancels what is
    beneath it, a pin or its check's word, whose own period is what it shows; and
    where the period is not of what the node shows — after a restart, until the
    units beneath it have run, and for the moment between a reading gone stale and
    the tick that dates it — the document says ***Its own status*** alone."""
    period = node.period
    if period is None or not node.counts_beneath:
        return None
    began = period.began
    clause = _begun_by(node, period)
    return _item(0,
        f"**Status {period.code.name.lower()}** since "
        f"{'before ' if began.before else ''}{style.at(began.at)}"
        f"{', begun by ' + clause if clause else ''}")


def _named_rule(said: str, period: Period) -> str:
    """``said``, a clause with ``{}`` where its node goes, with the rule the
    deployment configures named where one's beginning began the period (ADR-0137
    decision 11): *the rule develop advises beginning to count …*. The name is
    escaped for the document, and for the clause's own placeholder."""
    if period.began.cause != CAUSE_RULE or not period.rule:
        return said
    name = (period.rule.translate(_MD_INLINE_ESCAPE)
            .replace("{", "{{").replace("}", "}}"))
    return said.replace("a rule", f"the rule {name}", 1)


def _begun_by(node: StatusSnapshot, period: Period) -> str:
    """What began ``period``, the period of what ``node`` shows, as the clause after
    its instant says it in History's words (ADR-0132 decision 6) — or nothing where
    nothing says: a bound, and a difference a tick found that no change explains,
    which name no node. The node named is the one whose change began the period:
    the node itself, *of its own* or *on it*; one beneath it, by its path beneath
    it; or a dependency a shield is reached through, which stands outside it, by its
    full path and why it is named, whatever moved it. Where a rule the deployment
    configures began it, the clause names the rule and the node whose count it
    changed: *the rule develop advises beginning to count develop beneath it*."""
    by = period.by
    if not by:
        return ""
    cause = period.began.cause
    if by == node.path:
        said = _BEGUN_BY_ITS_OWN.get(cause, _A_READING_OF_ITS_OWN)
        return _named_rule(said, period).format()
    said = _named_rule(_BEGUN_BY.get(cause, _A_READING), period)
    beneath = node.path.rstrip("/") + "/"
    if by.startswith(beneath):
        return said.format(
            f"{by[len(beneath):].translate(_MD_INLINE_ESCAPE)} beneath it")
    return (f"{said.format(by.translate(_MD_INLINE_ESCAPE))}, "
            "which a node beneath it is reached through")


def _code_word(code: StatusCode) -> str:
    """A status as this document says it: the word and the portable cue."""
    return f"{code.name.lower()} {status_icon(code)}"


def _format_node(node: StatusSnapshot, depth: int, style: TimeStyle,
                 periods: Periods | None = None,
                 origin: Origin | None = None) -> list[str]:
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
            beneath.extend(_format_node(child, depth + 1, style, periods, origin))
        if _speaks(node):
            return [*_finding(node, _shown(node), depth, style, periods, origin),
                    *beneath]
        if not beneath:
            return []
        return [_item(depth, _label(node, _handbook_of(origin, node.path))), *beneath]
    if node.code == StatusCode.OK:
        return []
    return _finding(node, node.code, depth, style, periods, origin)


def _speaks(node: StatusSnapshot) -> bool:
    """Whether a branch holds something of its own for an outline to say: what it
    shows of its own is not ok — a status it declares, a pin on it, which it shows
    as *maintenance*, or a reading of its own gone stale. `UNDEFINED` is a branch
    that declares nothing, which is a name and no finding."""
    return _shown(node) not in (StatusCode.OK, StatusCode.UNDEFINED)


def _finding(node: StatusSnapshot, code: StatusCode, depth: int, style: TimeStyle,
             periods: Periods | None, origin: Origin | None = None) -> list[str]:
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

    handbook = _handbook_of(origin, node.path)
    lines = [_item(depth, f"{_label(node, handbook)} {state}"
                          f"{_stood(node, style, periods)}")]
    if node.maintenance_entry is not None:
        lines.extend(_maintenance_lines(depth + 1,
            node.maintenance_entry.note,
            node.maintenance_entry.set_by,
            node.maintenance_entry.expires_at,
            style, handbook,
        ))
    if node.acknowledgment is not None:
        lines.extend(_acknowledgment_lines(depth + 1, node.acknowledgment, style,
                                           handbook))
    for reason in node.reasons:
        lines.extend(_format_reason(reason, depth + 1, style, handbook))
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


def _label(node: StatusSnapshot, handbook: str = "") -> str:
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
        # newline so even malformed metadata cannot escape the item it labels, and
        # write a status it names out as the page draws it (ADR-0133 decision 5).
        parts.append(written_out(" ".join(title.splitlines()), inline=True,
                                 handbook=handbook))
    return " ".join(parts)


def _format_reason(reason: ReasonLine, depth: int, style: TimeStyle,
                   handbook: str = "") -> list[str]:
    """A line, and its pin where it has one, as an outline lists it: its text written
    out (:func:`written_out`), ``handbook`` the address of its node's handbook."""
    lines = _markdown_item(depth, written_out(reason.text, handbook=handbook),
                           _reason_cues(reason))
    if reason.maintenance is not None:
        lines.extend(_maintenance_lines(depth + 1,
            reason.maintenance.note,
            reason.maintenance.set_by,
            reason.maintenance.expires_at,
            style, handbook,
        ))
    if reason.acknowledgment is not None:
        lines.extend(_acknowledgment_lines(depth + 1, reason.acknowledgment, style,
                                           handbook))
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


def _maintenance_lines(depth: int, note: str, set_by: str,
                       expires_at: datetime | None, style: TimeStyle,
                       handbook: str = "") -> list[str]:
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
    until = "" if expires_at is None else f", until {style.at(expires_at)}"
    attribution = (f"🛠️ Maintenance — by {actor}{until}"
                   ).translate(_MD_INLINE_ESCAPE)
    lines = [_item(depth, attribution)]
    if note and note != NO_NOTE:
        lines.extend(_markdown_item(depth + 1,
                                    written_out(note, handbook=handbook)))
    return lines


#: The sign a pasted document gives an acknowledgment (ADR-0142), where the page
#: draws a ringed check: a checked box, which is no status's sign.
_ACCEPTED_SIGN = "☑️"


def _acknowledgment_lines(depth: int, pin: Pin, style: TimeStyle,
                          handbook: str = "") -> list[str]:
    """An acknowledgment as an outline states it (ADR-0142), as a pin is stated: *☑️
    Seen — by ada at error ⛔, until it changes* — and *or until …* where it was
    given an end — with its note nested beneath it as its own Markdown."""
    actor = pin.set_by or "an admin"
    at = "" if pin.status is None else f" at {_code_word(pin.status)}"
    until = ("" if pin.expires_at is None
             else f", or until {style.at(pin.expires_at)} at the latest")
    attribution = (f"{_ACCEPTED_SIGN} {pin.kind.capitalize()} — by {actor}{at}, "
                   f"until it changes{until}").translate(_MD_INLINE_ESCAPE)
    lines = [_item(depth, attribution)]
    if pin.note:
        lines.extend(_markdown_item(depth + 1,
                                    written_out(pin.note, handbook=handbook)))
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
