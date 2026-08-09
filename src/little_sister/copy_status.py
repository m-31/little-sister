"""Clipboard-friendly Markdown for the status tree.

The copy page is an incident hand-off, not another dashboard.  It keeps every
non-OK leaf and only the ancestors needed to locate those leaves, then emits one
canonical Markdown document.  The web layer renders rich HTML from that same
document so the two clipboard formats cannot drift.
"""
from __future__ import annotations

from little_sister.status import StatusCode
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


def status_icon(code: StatusCode) -> str:
    """The portable, non-colour status cue used by the copy document."""
    return _STATUS_ICON[code]


def format_copy_markdown(root: StatusSnapshot | None) -> str:
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
        lines.extend(_format_node(child, 0))
    return "\n".join(lines)


def _format_node(node: StatusSnapshot, depth: int) -> list[str]:
    if node.children:
        descendants: list[str] = []
        for child in node.children:
            descendants.extend(_format_node(child, depth + 1))
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
        ))
    for reason in node.reasons:
        lines.extend(_format_reason(reason, depth + 1))
    return lines


def _label(node: StatusSnapshot) -> str:
    # Titles are defined as short inline Markdown.  Collapse an accidental newline
    # so even malformed metadata cannot escape the list item it labels.
    if node.title:
        return " ".join(node.title.splitlines())
    return node.name.translate(_MD_INLINE_ESCAPE)


def _format_reason(reason: ReasonLine, depth: int) -> list[str]:
    lines = _markdown_item(depth, reason.text)
    if reason.maintenance is not None:
        lines.extend(_maintenance_lines(depth + 1,
            reason.maintenance.reason,
            reason.maintenance.set_by,
            reason.maintenance.expires_at,
        ))
    return lines


def _maintenance_lines(depth: int, reason: str, set_by: str,
                       expires_at: str) -> list[str]:
    """One maintenance reading plus its authored Markdown explanation.

    Authorship and expiry are structural text; the explanation is source content and
    stays Markdown, nested below that reading exactly like a check reason.  Keeping
    them as separate items means a multiline list or fenced block cannot swallow the
    attribution line or be flattened into literal punctuation.
    """
    actor = set_by or "an admin"
    attribution = f"🛠️ Maintenance — by {actor}, until {expires_at}".translate(
        _MD_INLINE_ESCAPE)
    lines = [_item(depth, attribution)]
    if reason and reason != "maintenance":
        lines.extend(_markdown_item(depth + 1, reason))
    return lines


def _item(depth: int, text: str) -> str:
    return f"{'  ' * depth}- {text}"


def _markdown_item(depth: int, markdown: str) -> list[str]:
    """Nest one authored Markdown block inside a list item.

    Prefixing the first line with the bullet and every continuation with the
    item's content indent preserves links, paragraphs and fenced code blocks at
    arbitrary tree depth.
    """
    raw_lines = markdown.splitlines() or [""]
    prefix = "  " * depth
    continuation = "  " * (depth + 1)
    return [f"{prefix}- {raw_lines[0]}"] + [
        f"{continuation}{line}" for line in raw_lines[1:]
    ]
