"""The look a browser file chooses where it tests one (ADR-0029, ``testing-the-gui.md``,
Mode 5).

Since 2026-10-18 the library's look is cyberpunk, the inspection card off and a wash
under the pointer (`little_sister.looks`). A browser file that tests the card on a
pause, the outline under the pointer, or a premise of the plain theme's face — a name
that breaks at a width, an ink measured on a light canvas — chooses that look as a
viewer does in the settings menu, through the presentation cookie; the rest read the
library's, as a browser that never chose does.

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

from urllib.parse import urlencode


def looks(base: str, **chosen: str) -> dict[str, str]:
    """The presentation cookie of ``base``'s pages, choosing the ``chosen`` looks —
    the whole cookie, so a test that chooses a second look names the first again."""
    return {"name": "ls_prefs", "url": base, "value": urlencode(chosen)}
