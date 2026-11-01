"""The Chromium a browser file launches (``docs/testing-the-gui.md``, Mode 5).

Playwright looks for the revision of Chromium its own version pins, and an environment
that brings its own browsers need not hold that one: the cloud container's image brings
whichever revision it was built with, under ``PLAYWRIGHT_BROWSERS_PATH``, and says so
with ``PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`` beside it. A file that named a revision ran
only while the image held it, and skipped — *no chromium available* — once an image
brought another. So no file names a revision: every browser file and every tool that
drives a browser asks here.

The answer, in this order: ``$PLAYWRIGHT_BROWSERS_PATH/chromium`` where that is a file —
the stable link an image keeps to the browser it brings; else the newest revision's
``chromium-*/chrome-linux*/chrome`` beneath it; else ``None``, the revision Playwright
finds itself, as on a Mac, where the release's run installs the one the lock's
Playwright asks for.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

#: Where an environment that brings its own browsers keeps them.
BROWSERS_PATH = "PLAYWRIGHT_BROWSERS_PATH"

#: A revision's directory beneath it, by the revision's number.
_REVISION = re.compile(r"chromium-(\d+)")


def chromium() -> str | None:
    """The Chromium to pass as ``executable_path``, or ``None`` for the one Playwright
    finds itself."""
    root = os.environ.get(BROWSERS_PATH)
    if not root:
        return None
    link = Path(root) / "chromium"
    if link.is_file():
        return str(link)
    revisions = [(int(match.group(1)), browser)
                 for browser in Path(root).glob("chromium-*/chrome-linux*/chrome")
                 if (match := _REVISION.fullmatch(browser.parent.parent.name))
                 and browser.is_file()]
    if not revisions:
        return None
    return str(max(revisions)[1])
