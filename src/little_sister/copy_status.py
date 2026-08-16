"""Clipboard-friendly Markdown for the status tree, and for one node of it.

The copy page is an incident hand-off, not another dashboard.  It keeps every
non-OK leaf and only the ancestors needed to locate those leaves, then emits one
canonical Markdown document.  The web layer renders rich HTML from that same
document so the two clipboard formats cannot drift.

**Two documents, one formatter.**  :func:`format_copy_markdown` hands over the
whole tree; :func:`format_node_markdown` hands over one leaf, with everything the
tree document has no room for and only the node's own page knows — its path, when
it was observed and since when it has held that status, the next update, how long
the last run took, how often it runs, what the run reported and what it ran with.
They share this module rather than a resemblance: the status cue, the label rule,
the pin attribution and the Markdown nesting are one implementation each, so the
node a reader copies off the detail page cannot describe itself differently from
the same node inside the tree hand-off.

Every instant either document writes names its **offset** (:class:`TimeStyle`).
The pages render local time and stay silent about the zone, which is right for a
screen somebody is standing in front of; a pasted incident is read in another
office, where `14:32` alone is a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, tzinfo

from little_sister.config import DEFAULT_TIME_FORMAT
from little_sister.spans import format_duration, format_span
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
    """The portable, non-colour status cue used by the copy document."""
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

    def at(self, value: str | None) -> str:
        """One stored timestamp, in the configured zone, naming its offset.

        The tree's timestamps are naive server-local strings (ADR-0006), so a
        value without a zone is read as the server's — the same reading the
        ``localtime`` filter makes, and the reason this cannot simply be
        ``fromisoformat`` plus ``strftime``.

        Absent is an em dash and unparsable is returned unchanged, which are the
        two answers that filter gives as well: a hand-off is not the place to
        discover that a timestamp is malformed, and raising here would turn a
        display detail into a 500 on a page that was working a moment ago.
        """
        if not value:
            return "—"
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
        if moment.tzinfo is None:
            moment = moment.astimezone()
        moment = moment.astimezone(self.zone)
        return f"{moment.strftime(self.time_format)} {_offset(moment)}".rstrip()


def _offset(moment: datetime) -> str:
    """A UTC offset as ``+02:00`` — ``%z``'s ``+0200`` with the colon ISO-8601
    uses, and the seconds an ancient local-mean-time zone can carry dropped."""
    raw = moment.strftime("%z")
    return f"{raw[:3]}:{raw[3:5]}" if len(raw) >= 5 else raw


def format_copy_markdown(root: StatusSnapshot | None, style: TimeStyle) -> str:
    """Return the non-OK outline below ``root`` as deterministic Markdown.

    The synthetic root is omitted.  A healthy leaf contributes nothing; a group
    contributes only when at least one descendant does.  Snapshot sibling order is
    preserved (the tree has already made it deterministic), and all reasons remain
    in their check-provided order.
    """
    if root is None:
        return ""
    lines: list[str] = []
    for child in root.children:
        lines.extend(_format_node(child, 0, style))
    return "\n".join(lines)


def format_node_markdown(node: StatusSnapshot, style: TimeStyle,
                         since: str | None = None) -> str:
    """Return one **leaf** as a hand-off document: what the tree outline says
    about it, plus everything only its detail page knows.

    The tree document locates a finding; this one hands it to somebody.  So it
    keeps the identity and the facts an operator would otherwise retype — the
    path, the observation and the period it bounds, the next update, the last
    run's wall time, the frequency — then the reason lines **in full**, then what
    the run reported and what it ran with.  ``since`` is the start of the node's
    current own-status period (the same value its page renders), and ``None``
    where the node has no transition of its own to bound one (ADR-0027).

    Headings and blocks rather than the tree's nested list: a document about one
    thing is read as one, and a fenced traceback or a bulleted configuration
    nested four levels deep is a worse paste than the same block at the margin.

    A pin does not change what is copied.  A pin changes what the tree *reports*;
    it does not change what the check *measured*, and a hand-off is about the
    measurement — so the reading stays, and the document says a pin is in force
    instead of quietly presenting the pinned code as the answer
    ([ADR-0032](../docs/adr/0032-status-contribution-boundary.md) rule 5, in a
    surface that has no colour to say it with).
    """
    document = [f"## {_label(node)} {status_icon(node.reported_code)}", ""]
    document.extend(_node_facts(node, style, since))
    if node.reasons:
        document.extend(["", "**Reasons**", ""])
        for reason in node.reasons:
            document.extend(_format_reason(reason, 0, style))
    # `report` before `config` — what the run found is why the page was opened,
    # what it ran with is the reference beside it (`_node_facts.html` orders the
    # cards the same way).  Both are the check's own authored Markdown and land
    # at the margin, where a list or a fence renders as itself.
    if node.report:
        document.extend(["", "**Report**", "", node.report])
    if node.config:
        document.extend(["", "**Configuration**", "", node.config])
    return "\n".join(document)


def format_reason_markdown(node: StatusSnapshot, line: ReasonLine,
                           style: TimeStyle) -> str:
    """Return **one reason line** as a hand-off document.

    The narrowest of the three, and the one the whole feature started from: an
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
    if node.timestamp is not None:
        document.append(_item(0, f"**Observed:** {style.at(node.timestamp)}"))
    document.extend(["", "**Finding**", ""])
    document.extend(_format_reason(line, 0, style))
    return "\n".join(document)


def _node_facts(node: StatusSnapshot, style: TimeStyle,
                since: str | None) -> list[str]:
    """The fact list under the heading, in the detail page's own order and words.

    Two statuses can appear, and the difference between them is the point.
    **Reported** is what the check measured.  **Shown as** appears only when the
    node presents something else — which is a pin, the one transform that makes
    them differ (`_own_code`) — and names it rather than letting the reader
    believe the tree measured `maintenance`.
    """
    facts = [
        _item(0, f"**Path:** {node.path.translate(_MD_INLINE_ESCAPE)}"),
        _item(0, f"**Reported:** {_code_word(node.reported_code)}"),
    ]
    if node.own_code != node.reported_code:
        facts.append(_item(0,
            f"**Shown as:** {_code_word(node.own_code)} — a maintenance pin is "
            f"in force; the reported reading above is what the check measured."))
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
    # The observation, and the period it bounds, exactly as the page's Time card
    # states them (ADR-0027): no timestamp means no check has ever written this
    # node, and no transition of its own means there is no period to bound.
    if node.timestamp is None:
        facts.append(_item(0, "**Not yet observed.**"))
    elif since:
        facts.append(_item(0,
            f"**Status {node.own_code.name.lower()}** from {style.at(since)} "
            f"until {style.at(node.timestamp)}"))
    else:
        facts.append(_item(0, f"**Observed:** {style.at(node.timestamp)}"))
    if node.stale:
        facts.append(_item(0,
            f"**Stale** — last checked {format_span(node.age_seconds)} ago"))
    if node.run is not None and node.run.next_run_at:
        facts.append(_item(0, f"**Next update:** {style.at(node.run.next_run_at)}"))
    if node.run is not None and node.run.wall_seconds is not None:
        facts.append(_item(0,
            f"**Last run took:** {format_span(node.run.wall_seconds)}"))
    if node.frequency_seconds:
        facts.append(_item(0,
            f"**Checked every:** {format_duration(node.frequency_seconds)}"))
    return facts


def _code_word(code: StatusCode) -> str:
    """A status as this document says it: the word and the portable cue."""
    return f"{code.name.lower()} {status_icon(code)}"


def _format_node(node: StatusSnapshot, depth: int,
                 style: TimeStyle) -> list[str]:
    if node.children:
        descendants: list[str] = []
        for child in node.children:
            descendants.extend(_format_node(child, depth + 1, style))
        if not descendants:
            return []
        return [_item(depth, _label(node)), *descendants]

    if node.code == StatusCode.OK:
        return []

    state = status_icon(node.code)
    qualifiers: list[str] = []
    if node.stale:
        qualifiers.append("stale")
    if (node.code == StatusCode.MAINTENANCE
            and node.reported_code not in (
                StatusCode.MAINTENANCE, StatusCode.UNDEFINED)):
        qualifiers.append(f"reported {status_icon(node.reported_code)}")
    if qualifiers:
        state += f" ({'; '.join(qualifiers)})"

    lines = [_item(depth, f"{_label(node)} {state}")]
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
    has neither colour nor tint, so it takes the same portable cue the nodes take
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
                       expires_at: str, style: TimeStyle) -> list[str]:
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
