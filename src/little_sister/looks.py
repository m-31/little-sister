"""The looks a deployment defaults and a browser chooses (ADR-0029, ADR-0127).

A *look* is how the page draws what it says, never what it says: its theme (ADR-0028),
how a run of chips is drawn, whether the inspection card opens on a pause (ADR-0019),
how a head's row and a chip answer the pointer, where a head keeps its buttons, and
whether a failure the first look hides opens its way. Each is chosen per browser in
the settings menu and kept in the presentation cookie beside the layout, and the
server renders it onto ``<body>``, so the stylesheet and the scripts branch on one
attribute and nothing flashes. Unlike the layout, whose default
is a constant, a look's default is the deployment's, a key of ``settings.yaml`` named
as the look is, so a browser that never chose one follows the deployment when its
default changes.

**One roster**, :data:`LOOKS`: each look is its key, its values, the library's own
default and the words the settings menu says it in, and everything that touches a look
reads that list — ``config.py`` reading and checking the deployment's default, the
cookie in ``app.py``, the menu's groups (``_settings_menu.html``) and the attribute on
``<body>`` (``_header.html``) — so that a look joins as an entry and not as code. The
menu leads with the theme, the layout after it, and the other looks in this order,
each group's heading followed by its line: what the group changes, in a few words —
the page's help on its settings, beside the choice (backlog #91). The layout's line is
the menu's own, since the layout is no look.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Look:
    """One look: its key — ``settings.yaml``'s and the cookie's — its values in the
    order the settings menu offers them, the library's own default among them, and
    the menu's words for the group, for each value and, in ``line``, for what the
    group changes, the line beneath its heading."""

    key: str
    values: tuple[str, ...]
    default: str
    heading: str
    labels: tuple[str, ...]
    line: str

    def __post_init__(self) -> None:
        if self.default not in self.values:
            raise ValueError(f"look {self.key!r}: default {self.default!r} is not "
                             f"one of {self.values}")
        if len(self.labels) != len(self.values):
            raise ValueError(f"look {self.key!r}: one label per value")
        if not self.line.strip():
            raise ValueError(f"look {self.key!r}: a line for beneath its heading")

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
    # and the library's cyberpunk.
    Look("theme", ("auto", "plain", "vivid", "pastel", "dark", "cyberpunk"),
         "cyberpunk", "Theme",
         ("auto (follow the OS)", "plain", "vivid", "pastel", "dark", "cyberpunk"),
         "The page's colors."),
    # How a run of chips is drawn (ADR-0127 decision 12): in the columns its level
    # shares, where two fit, or wrapped as they come, each chip at its own width.
    Look("chip_runs", ("aligned", "wrapped"), "aligned",
         "Chips", ("aligned", "wrapped"),
         "How a level's chips line up."),
    # How a level's open boxes share its columns (ADR-0138): in rows, each as tall as
    # its tallest box and every box in its place whatever its lines, the library's
    # (ADR-0056); or packed, each box beneath the shortest column, so that a tall box
    # leaves no gap beside it — a box taking its column when the page is drawn and when
    # its width changes, and keeping it through a refresh and a click.
    Look("boxes", ("rows", "packed"), "rows",
         "Boxes", ("in rows", "packed"),
         "How a level's boxes fill its columns."),
    # Whether a pause on a node's name opens its inspection card (ADR-0019): `off`,
    # the library's since 2026-10-18, keeps it closed for the pointer and the
    # keyboard alike.
    Look("inspection_card", ("pause", "off"), "off",
         "Hover card", ("on a pause", "off"),
         "Whether a pause on a name opens its card."),
    # How a head's row and a chip say that a click opens or closes the node, under
    # the pointer (ADR-0127 decision 11): an outline of their ink, or a wash of it in
    # the outline's place, the library's since 2026-10-18. Under forced colors the
    # outline stands either way.
    Look("toggle_hover", ("outline", "wash"), "wash",
         "Under the pointer", ("outline", "wash"),
         "How a row shows that a click opens it."),
    # Where an open node's head keeps its buttons — its page, its folds, its pin and
    # the node's actions, in that order — so that the pointer need not travel to the
    # row's far end for them (ADR-0127 decision 3): right after the name, shown while
    # the pointer is on the head or the keyboard's focus is in it, the library's; there
    # too, where a click on the name opens the node's page and ↗ is the keyboard's
    # alone; on a line of their own beneath the row; or at the row's end, as they stood,
    # the name opening the page as in the second.
    Look("head_buttons", ("pointer", "pointer-name", "line", "name"), "pointer",
         "Head's buttons",
         ("after the name, under the pointer",
          "after the name, the name opens the page",
          "on a line beneath", "at the end, the name opens the page"),
         "Where an open head keeps its buttons."),
    # What the failure budget does with a failure the first look hides (backlog #91
    # §3.3): `open`, the library's, opens its way, the first three in each card with the
    # nodes on their paths, so that a first glance finds it; or `chips`, where it stays
    # the chip it was, red, and the wall keeps its size — a kiosk's wish (ADR-0127
    # decision 5). A switch set once is forgotten until the one failure a glance
    # should show stays shut, and the line beneath its heading is what answers that:
    # the default is the one to keep.
    Look("failures", ("open", "chips"), "open",
         "Failures", ("open their way", "stay chips"),
         "Keep them open, on a kiosk too: a new failure shows at a glance."),
)

#: The line beneath the layout's heading in the settings menu, which the menu writes
#: itself since the layout is no look.
LAYOUT_LINE = "Where the navigation stands; a kiosk has none."

#: The looks by key.
LOOKS_BY_KEY: dict[str, Look] = {look.key: look for look in LOOKS}
