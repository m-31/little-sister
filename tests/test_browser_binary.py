"""The Chromium a browser file launches, found rather than named
(``tests/browser_binary.py``): the link an environment keeps to the browser it brings,
else its newest revision, else Playwright's own."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from tests.browser_binary import BROWSERS_PATH, chromium


class ChromiumTests(TestCase):

    def setUp(self) -> None:
        held = tempfile.TemporaryDirectory(prefix="ls-browsers-")
        self.addCleanup(held.cleanup)
        self.root = Path(held.name).resolve()
        patched = mock.patch.dict(os.environ, {BROWSERS_PATH: str(self.root)})
        patched.start()
        self.addCleanup(patched.stop)

    def browser(self, revision: str, platform: str = "chrome-linux64") -> Path:
        """A revision's browser beneath the root, as an image unpacks it."""
        path = self.root / revision / platform / "chrome"
        path.parent.mkdir(parents=True)
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        return path

    def test_the_link_an_environment_keeps_is_what_runs(self):
        target = self.browser("chromium-800")
        self.browser("chromium-900")
        (self.root / "chromium").symlink_to(target)
        self.assertEqual(chromium(), str(self.root / "chromium"))

    def test_without_one_the_newest_revision_runs(self):
        self.browser("chromium-700", "chrome-linux")
        newest = self.browser("chromium-800")
        # neither the headless shell nor a revision whose name is no number
        self.browser("chromium_headless_shell-900", "chrome-headless-shell-linux64")
        self.browser("chromium-tip", "chrome-linux64")
        self.assertEqual(chromium(), str(newest))

    def test_by_its_number_not_its_spelling(self):
        self.browser("chromium-999", "chrome-linux")
        newest = self.browser("chromium-1000", "chrome-linux")
        self.assertEqual(chromium(), str(newest))

    def test_a_link_to_nothing_is_passed_over(self):
        gone = self.root / "chromium-1" / "chrome-linux" / "chrome"
        (self.root / "chromium").symlink_to(gone)
        newest = self.browser("chromium-800")
        self.assertEqual(chromium(), str(newest))

    def test_nothing_beneath_it_is_playwright_s_own(self):
        self.assertIsNone(chromium())

    def test_no_such_environment_is_playwright_s_own(self):
        with mock.patch.dict(os.environ, clear=True):
            self.assertIsNone(chromium())
