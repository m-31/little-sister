"""What of the walk needs no browser (``tests/walk_gui.py``, Mode 6 of
``docs/testing-the-gui.md``): what a vendored URL resolves to, how a report reads,
that the gallery leads with what was marked, that the walk leaves the demo it ran
before the demo's directory goes, and the looks its browser chooses. Every run that
collects ``tests/`` runs it. The facts themselves, each held against a page in
Chromium, are ``tests/test_walk_gui_browser.py``, a browser file, which runs where it
is named.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from tests import walk_gui
from tests.running import subprocess_env
from tests.walk_gui import FACTS, Step


class WithoutABrowserTests(unittest.TestCase):
    def test_a_vendored_url_is_the_file_beneath_the_vendored_root(self) -> None:
        with tempfile.TemporaryDirectory() as holder:
            root = Path(holder).resolve() / "node_modules"
            css = root / "bootstrap" / "dist" / "css" / "bootstrap.min.css"
            core = root / "@floating-ui" / "core" / "dist" / "core.umd.min.js"
            for path in (css, core):
                path.parent.mkdir(parents=True)
                path.write_text("")
            (root.parent / "outside.js").write_text("")
            cdn = "https://cdn.jsdelivr.net/npm"
            self.assertEqual(walk_gui.vendored(
                f"{cdn}/bootstrap@5.3.2/dist/css/bootstrap.min.css", root), css)
            self.assertEqual(walk_gui.vendored(
                f"{cdn}/@floating-ui/core@1.6.8/dist/core.umd.min.js", root), core)
            # not vendored, not a CDN URL, and a path that leaves the root
            self.assertIsNone(walk_gui.vendored(
                f"{cdn}/bootstrap@5.3.2/dist/js/missing.js", root))
            self.assertIsNone(walk_gui.vendored(
                "https://example.org/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css",
                root))
            self.assertIsNone(walk_gui.vendored(
                f"{cdn}/bootstrap@5.3.2/../../outside.js", root))

    def test_a_report_reads_as_its_directive_and_what_it_blocked(self) -> None:
        self.assertEqual(
            walk_gui.csp_said(json.dumps({"csp-report": {
                "effective-directive": "img-src", "blocked-uri": "data"}})),
            "img-src blocked data")
        self.assertEqual(walk_gui.csp_said("not json"),
                         "a report that could not be read")

    def test_the_gallery_leads_with_what_was_marked_and_counts_by_fact(self) -> None:
        steps = [
            Step("desk-1440", "wall", "http://x/status"),
            Step("desk-1440", "about", "http://x/about",
                 findings={"page-width": ["the page is 48px wider than its screen"]}),
            Step("phone-390", "about", "http://x/about",
                 findings={"page-width": ["the page is 3px wider than its screen"],
                           "csp": ["img-src blocked data"]})]
        self.assertEqual(walk_gui.facts_counted(steps), {"page-width": 2, "csp": 1})
        page = walk_gui.gallery(steps)
        self.assertIn("3 steps, 2 marked.", page)
        marked, every = page.split("<h2>Every step</h2>")
        self.assertEqual(marked.count("<article"), 2)
        self.assertNotIn("<h3>wall</h3>", marked)
        self.assertEqual(every.count("<article"), 3)
        self.assertIn("48px wider", marked)
        # every fact is named with what it holds a step to, marked or not
        for name in (*FACTS, "layout-shift", "console", "csp"):
            self.assertIn(f"<td>{name}</td>", page)

    def test_what_a_page_says_is_escaped_into_the_gallery(self) -> None:
        page = walk_gui.gallery([Step("desk-1440", "<b>wall</b>", "http://x/?a=1&b=2",
                                      findings={"console": ["<script>x</script>"]})])
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;b&gt;wall&lt;/b&gt;", page)

    def test_a_walk_with_nothing_marked_says_so(self) -> None:
        self.assertIn("<h2>Marked</h2><p>None.</p>",
                      walk_gui.gallery([Step("desk-1440", "wall", "http://x/")]))


#: The walk's demo, started and left as the walk does, in a child interpreter: the
#: application starts once a process and stops once, and this suite's never starts.
_DEMO_CHILD = """
    import json, os, urllib.request
    from tests import walk_gui
    here = os.getcwd()
    with walk_gui.demo() as base:
        ran_in = os.getcwd()
        served = urllib.request.urlopen(base + "/health", timeout=10).status
    try:
        urllib.request.urlopen(base + "/health", timeout=2)
        after = "answered"
    except OSError as error:
        refused = isinstance(getattr(error, "reason", error), ConnectionRefusedError)
        after = "refused" if refused else "unanswered"
    print(json.dumps({"served": served, "after": after,
                      "where": "back" if os.getcwd() == here else os.getcwd(),
                      "directory": "kept" if os.path.exists(ran_in) else "gone"}))
"""


class TheDemoTests(unittest.TestCase):
    def test_the_walk_leaves_the_demo_before_its_directory_goes(self) -> None:
        # The demo runs in a directory of its own, and its instance keeps its state
        # and its lease there: the server stops, then the instance — its one save,
        # its lease let go — and the process goes back where it was, all while the
        # directory is still there. The stop at exit came after the directory had
        # gone, found no lease, and logged that the instance no longer saved.
        directory = self.enterContext(tempfile.TemporaryDirectory())
        environment = subprocess_env()
        # the demo's own configuration roots and log, as a walk has them
        for name in ("LITTLE_SISTER_CONFIG_DIR", "LITTLE_SISTER_ENGINE", "LOG_FILE",
                     "LITTLE_SISTER_DEMO_DIR"):
            environment.pop(name, None)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        environment["LOG_LEVEL"] = "INFO"  # the engine's stop says what reached it
        done = subprocess.run([sys.executable, "-c", textwrap.dedent(_DEMO_CHILD)],
                              cwd=directory, env=environment, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]),
                         {"served": 200, "after": "refused", "where": "back",
                          "directory": "gone"})
        self.assertIn("engine: stopped, reached by the walk's end", done.stderr)
        self.assertNotIn("no longer saves", done.stderr)


class _Stopped(Exception):
    """Where the fake browser's page ends a walk: at its first use."""


class TheWalksLooksTests(unittest.TestCase):
    def test_the_walks_browser_chooses_the_card_it_raises(self) -> None:
        # The walk rests on every card head's name, which raises the inspection
        # card; the library's look keeps the card off since 2026-10-18, so the
        # walk's browser chooses it on a pause, as a viewer does in the settings
        # menu, and every other look stays the library's
        cookies: list[dict[str, str]] = []

        class Page:
            def add_init_script(self, _script: str) -> None:
                raise _Stopped

        class Context:
            def add_cookies(self, added: list[dict[str, str]]) -> None:
                cookies.extend(added)

            def new_page(self) -> Page:
                return Page()

        class Browser:
            def new_context(self, **_drawn_in: Any) -> Context:
                return Context()

        base = "http://127.0.0.1:5123"
        out = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with self.assertRaises(_Stopped):
            walk_gui.walk_demo(Browser(), base, out, [])
        self.assertEqual([(cookie["name"], cookie["url"]) for cookie in cookies],
                         [("ls_prefs", base)])
        from little_sister import app as app_module
        from little_sister.looks import LOOKS
        with app_module.app.test_request_context():
            never_chose = app_module._presentation()
        with app_module.app.test_request_context(
                headers={"Cookie": f"ls_prefs={cookies[0]['value']}"}):
            drawn = app_module._presentation()
        self.assertEqual(drawn["inspection_card"], "pause")
        for look in LOOKS:
            if look.key != "inspection_card":
                with self.subTest(look=look.key):
                    self.assertEqual(drawn[look.key], never_chose[look.key])


class AnotherLookTests(unittest.TestCase):
    def test_look_adds_a_look_of_the_settings_menus_to_the_walks_own(self) -> None:
        # `--look boxes=packed` walks the demo packed (ADR-0138), the card still on a
        # pause; a look or a value the menu does not have stops the walk before it
        # starts, naming the looks
        self.assertEqual(walk_gui.chosen_looks(["boxes=packed"]),
                         {**walk_gui.CHOSEN_LOOKS, "boxes": "packed"})
        self.assertEqual(walk_gui.chosen_looks([]), walk_gui.CHOSEN_LOOKS)
        for asked in ("boxes=masonry", "packing=packed", "boxes"):
            with self.subTest(asked=asked), self.assertRaises(SystemExit) as stop:
                walk_gui.chosen_looks([asked])
            self.assertIn("boxes", str(stop.exception))
