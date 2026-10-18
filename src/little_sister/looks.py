"""The looks a deployment defaults and a browser chooses (ADR-0029, ADR-0127).

A *look* is how the page draws what it says, never what it says: its theme (ADR-0028),
how a run of chips is drawn, whether the inspection card opens on a pause (ADR-0019),
how a head's row and a chip answer the pointer. Each is chosen per browser in the
settings menu and kept in the presentation cookie beside the layout, and the server
renders it onto ``<body>``, so the stylesheet and the scripts branch on one attribute
and nothing flashes. Unlike the layout, whose default is a constant, a look's default
is the deployment's, a key of ``settings.yaml`` named as the look is, so a browser that
never chose one follows the deployment when its default changes.

**One roster**, :data:`LOOKS`: each look is its key, its values, the library's own
default and the words the settings menu says it in, and everything that touches a look
reads that list — ``config.py`` reading and checking the deployment's default, the
cookie in ``app.py``, the menu's groups (``_settings_menu.html``) and the attribute on
``<body>`` (``_header.html``) — so that a look joins as an entry and not as code. The
menu leads with the theme, the layout after it, and the other looks in this order.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Look:
    """One look: its key — ``settings.yaml``'s and the cookie's — its values in the
    order the settings menu offers them, the library's own default among them, and
    the menu's words for the group and for each value."""

    key: str
    values: tuple[str, ...]
    default: str
    heading: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.default not in self.values:
            raise ValueError(f"look {self.key!r}: default {self.default!r} is not "
                             f"one of {self.values}")
        if len(self.labels) != len(self.values):
            raise ValueError(f"look {self.key!r}: one label per value")

    @property
    def attribute(self) -> str:
        """The attribute on ``<body>`` that carries the look: ``data-ls-`` and the
        key, its underscores hyphens."""
        return "data-ls-" + self.key.replace("_", "-")

    def label(self, value: str) -> str:
        """What the settings menu says for ``value``."""
        return self.labels[self.values.index(value)]


#: Every look, in the order the settings menu lists them after the theme and the
#: layout.
LOOKS: tuple[Look, ...] = (
    # The theme (ADR-0028): the palette the page is painted in — `auto` the plain
    # theme or the dark one as the operating system asks, resolved in the browser —
    # and the library's cyberpunk, on Lex's word of 2026-10-18.
    Look("theme", ("auto", "plain", "vivid", "pastel", "dark", "cyberpunk"),
         "cyberpunk", "Theme",
         ("auto (follow the OS)", "plain", "vivid", "pastel", "dark", "cyberpunk")),
    # How a run of chips is drawn (ADR-0127 decision 12): in the columns its level
    # shares, where two fit, or wrapped as they come, each chip at its own width.
    Look("chip_runs", ("aligned", "wrapped"), "aligned",
         "Chips", ("aligned", "wrapped")),
    # Whether a pause on a node's name opens its inspection card (ADR-0019): `off`,
    # the library's since 2026-10-18, keeps it closed for the pointer and the
    # keyboard alike.
    Look("inspection_card", ("pause", "off"), "off",
         "Hover card", ("on a pause", "off")),
    # How a head's row and a chip say that a click opens or closes the node, under
    # the pointer (ADR-0127 decision 11): an outline of their ink, or a wash of it in
    # the outline's place, the library's since 2026-10-18. Under forced colors the
    # outline stands either way.
    Look("toggle_hover", ("outline", "wash"), "wash",
         "Under the pointer", ("outline", "wash")),
)

#: The looks by key.
LOOKS_BY_KEY: dict[str, Look] = {look.key: look for look in LOOKS}
