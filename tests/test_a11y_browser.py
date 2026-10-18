"""The wall, a node's page and the kiosk under axe-core's WCAG 2.2 A and AA rules.

The other browser files each hold one claim about one thing; this one lets a scanner
look at whole pages. `axe-core` runs in the page over the rules tagged for WCAG 2.2 A
and AA and says what fails them — a name without a label, a control too small to tap,
an ink too faint on its fill. The demo's wall, a branch's page and the kiosk are
scanned at a desk's width and on an emulated phone, in the library's theme, cyberpunk,
and in the plain one the baseline was first taken in, and **every finding is held to a
baseline**: what the scan found on the wall before the interactive wall was built
(backlog #91, its note's §7.1 step 8), each entry a rule and the component it stands
on, with the reason it stands. A finding outside the baseline fails the scan, so a
change to the templates or the sheet that adds one is seen the day it is made; an entry
that no scan finds any more fails it too, so the baseline shrinks as findings are mended
and never carries one that is gone.

The scanner is `axe-playwright-python` (MIT, needing only Playwright), which carries
axe-core itself (MPL-2.0, with no dependencies of its own) and injects it into the page.
It is in the browser group, never in `dev`: the ordinary gate grows no browser.

The demo runs in a child interpreter — its import registers a door, a check type and
slot fillers and moves the process into the demo's directory, and its engine takes a
lease there, none of which may reach this suite's process (`test_demo_check.py`) — and
serves on a port of its own, its scenarios started 36 seconds in so the wall is not all
green. Bootstrap comes from the copy Mode 4 vendors where there is one and from the CDN
otherwise; with neither the scan reads an unstyled page, and fails. Skipped wherever
Playwright, the scanner or a Chromium binary is unavailable
(``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from itertools import product
from pathlib import Path
from typing import Any, ClassVar

from little_sister.looks import LOOKS_BY_KEY
from tests.browser_looks import looks
from tests.running import subprocess_env

try:  # pragma: no cover - environment probe
    from axe_playwright_python.sync_playwright import Axe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]
    Axe = None  # type: ignore[assignment,misc]

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

#: Bootstrap as ``tests/sweep_contrast.py`` vendors it (``docs/testing-the-gui.md``,
#: Mode 4), where there is a copy; the CDN otherwise.
_BOOTSTRAP = _REPO_ROOT / "var" / "bootstrap" / "node_modules" / "bootstrap" / "dist"

#: The two widths the design was measured at: a desk, and the phone
#: ``tests/test_phone_browser.py`` reads its pages on.
_DESK = {"viewport": {"width": 1280, "height": 900}}
_PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"),
}
_WIDTHS = {1280: _DESK, 390: _PHONE}

#: axe-core's rules for WCAG 2.2 at levels A and AA, by their tags: 2.0's, 2.1's and
#: what 2.2 added at AA (the target-size rule among them).
_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]

#: The demo's wall has six cards, a branch's page five; the engine's first readings
#: arrive a moment after the start.
_CARDS = {"/status": 6, "/status/ci": 5}

#: The themes a scan reads each page in: the library's, which a browser that never
#: chose draws (since 2026-10-18), and the plain one, the light palette the others
#: are drawn from, which the baseline was first taken in.
_THEMES = ("cyberpunk", "plain")

#: **The baseline**: what axe-core 4.12 found on the demo before the interactive wall
#: was built — on 2026-10-16, at both widths, in the sidebar layout and the kiosk, in
#: the plain theme, the library's then; cyberpunk, the library's since 2026-10-18,
#: has none of :data:`PLAIN_ONLY` — as
#: the rule that fired and the component it fired on, the innermost part of the
#: scanner's selector with the nodes' own attributes taken out (:func:`component`), and
#: the reason the finding stands for now. A scan that finds a rule on a component not
#: listed here fails; so does a baseline entry that no scan finds any more, which is
#: how an entry leaves with the change that mends it. What is said of the stages is the
#: plan of backlog #91; the brand's inks are the brand's own decision.
BASELINE: dict[tuple[str, str], str] = {
    ("html-has-lang", "html"):
        "the pages declare no language on <html>; one attribute in _header.html, to be "
        "fixed on its own",
    ("color-contrast", ".ls-brand__wordmark"):
        "the brand's pink on the bar's surface measures 4.3:1 at 19 px where 4.5 is "
        "asked; the brand's inks are the brand's",
    ("color-contrast", ".ls-brand__tagline"):
        "the muted tagline on the bar's surface measures 4.4:1 at 14.5 px",
    ("color-contrast", ".ls-accent"):
        "the viewer's name in the brand's pink on the bar's surface, 4.3:1 at 16 px",
    ("color-contrast", ".node-title"):
        "the muted title ink on a head's state tint, 3.4:1 on the pale error tint — "
        "the title's own look, which the head's row kept",
    ("color-contrast", ".status-card__state"):
        "the state cluster's small words at 80 % on a pale error tint, 3.9:1 — the "
        "cluster's own look, kept in the head's row; a vivid card's words are lifted "
        "to the full ink",
    ("color-contrast", ".status-node__state"):
        "a nested box's state cluster on a vivid fill, as the card's",
    ("color-contrast", ".status-card__time"):
        "the observation time in the state cluster, small, on a vivid fill",
    ("color-contrast", "code"):
        "Bootstrap's code ink on a vivid line's fill, 1.4:1 on error: a code span in a "
        "reason takes no tint of its own",
    ("color-contrast", ".reason-action"):
        "a line's chip inks in currentColor at 60 % to 75 % opacity until hovered, "
        "which the scanner reads as its resting color",
    ("color-contrast", ".branch-more__show"):
        "a level's \"+N more\" is a subtle text button in currentColor at 80 % "
        "opacity until hovered, 3.8:1 on a card's tint; on the demo since stage 2's "
        "fleet, the fold the tab's map keeps — stage 3 redraws the level's controls",
}

#: The entries that stand in the plain theme alone: a light canvas's pale tints and
#: its bar's surface, which cyberpunk's dark canvas and its own inks do not have.
PLAIN_ONLY = frozenset({
    ("color-contrast", ".ls-brand__tagline"),
    ("color-contrast", ".ls-accent"),
    ("color-contrast", ".status-card__state"),
    ("color-contrast", ".status-node__state"),
    ("color-contrast", "code"),
    ("color-contrast", ".branch-more__show"),
})


def baseline(theme: str) -> set[tuple[str, str]]:
    """The entries that stand in ``theme``."""
    return {key for key in BASELINE if theme == "plain" or key not in PLAIN_ONLY}

#: The demo, served from a child interpreter: the port it chose on its first line, and
#: then nothing until it is ended.
_DEMO = textwrap.dedent("""
    import logging
    import tests.demo_wsgi  # noqa: F401 - the demo's type, door and fillers register
    from werkzeug.serving import make_server
    from little_sister.app import app, start
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    start()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    print(server.server_port, flush=True)
    server.serve_forever()
""")


def component(target: str) -> str:
    """The component a finding stands on: the innermost part of the scanner's selector,
    with the attributes and positions that name one node taken out — so that a finding
    on every head's title is one entry, not one per node."""
    last = target.split(" > ")[-1]
    last = re.sub(r"\[[^\]]*\]", "", last)
    last = re.sub(r":nth-[a-z-]+\([^)]*\)", "", last)
    return last


def _demo_environment(home: str) -> dict[str, str]:
    env = subprocess_env()
    env.pop("LITTLE_SISTER_CONFIG_DIR", None)     # the demo names its own roots
    env.pop("LITTLE_SISTER_ENGINE", None)
    env["LITTLE_SISTER_DEMO_DIR"] = home
    env.setdefault("LITTLE_SISTER_DEMO_OFFSET", "36s")
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(_REPO_ROOT), env.get("PYTHONPATH"))))
    return env


class AccessibilityScanTests(unittest.TestCase):
    """axe-core over the demo's pages, every finding held to the baseline."""

    playwright: Any = None
    browser: Any = None
    demo: subprocess.Popen[str] | None = None
    home: tempfile.TemporaryDirectory[str] | None = None
    started: tempfile.TemporaryDirectory[str] | None = None
    base = ""
    #: Every scan's findings, taken once for the class: (route, layout, width,
    #: theme) → the scanner's answer.
    scans: ClassVar[dict[tuple[str, str, int, str], dict[str, Any]]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None or Axe is None:
            raise unittest.SkipTest(
                "playwright or axe-playwright-python is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(
                executable_path=(str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file()
                                 else None))
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(f"no chromium available: {error}") from error
        cls.home = tempfile.TemporaryDirectory(prefix="ls-a11y-demo-")
        cls.started = tempfile.TemporaryDirectory(prefix="ls-a11y-cwd-")
        cls.demo = subprocess.Popen(
            [sys.executable, "-c", _DEMO], cwd=cls.started.name,
            env=_demo_environment(cls.home.name), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        cls.base = f"http://127.0.0.1:{cls._port()}"
        try:
            cls.scans = cls._scan_everything()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.demo is not None:
            cls.demo.terminate()
            try:
                cls.demo.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover
                cls.demo.kill()
            cls.demo = None
        for directory in (cls.home, cls.started):
            if directory is not None:
                directory.cleanup()
        cls.home = cls.started = None
        if cls.browser is not None:
            cls.browser.close()
            cls.browser = None
        if cls.playwright is not None:
            cls.playwright.stop()
            cls.playwright = None

    @classmethod
    def _port(cls) -> int:
        """The port the demo chose, read from its first line within a bound: a child
        that never binds is a failure with the words of the child, not a hang."""
        assert cls.demo is not None and cls.demo.stdout is not None
        line: list[str] = []
        reader = threading.Thread(
            target=lambda: line.append(cls.demo.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout=60)
        if not line or not line[0].strip().isdigit():
            raise AssertionError(f"the demo did not say its port: {line!r}")
        return int(line[0])

    @staticmethod
    def _vendored(route: Any) -> None:
        """Bootstrap from the vendored copy where there is one, the CDN otherwise."""
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    @classmethod
    def _scan_everything(cls) -> dict[tuple[str, str, int, str], dict[str, Any]]:
        """Twelve scans: the wall and a branch's page in the sidebar layout, and the
        kiosk's wall, each at a desk's width and on the phone, in each theme."""
        scans: dict[tuple[str, str, int, str], dict[str, Any]] = {}
        for (width, drawn_in), theme in product(_WIDTHS.items(), _THEMES):
            for layout, routes in (("sidebar", ("/status", "/status/ci")),
                                   ("kiosk", ("/status",))):
                context = cls.browser.new_context(**drawn_in)
                try:
                    context.route("https://cdn.jsdelivr.net/**", cls._vendored)
                    page = context.new_page()
                    page.goto(f"{cls.base}/login")
                    page.fill("#username", "pan")
                    page.fill("#password", "12345678")
                    with page.expect_navigation():
                        page.click("button[type=submit]")
                    chosen = {"theme": theme}
                    if layout == "kiosk":
                        chosen["layout"] = "kiosk"
                    context.add_cookies([looks(cls.base, **chosen)])
                    for route in routes:
                        page.goto(f"{cls.base}{route}")
                        page.wait_for_function(
                            "n => document.querySelectorAll('.status-card').length"
                            " >= n", arg=_CARDS[route], timeout=30_000)
                        page.wait_for_timeout(300)        # the first paint settles
                        scans[(route, layout, width, theme)] = Axe().run(
                            page, options={"runOnly": {"type": "tag", "values": _TAGS},
                                           "resultTypes": ["violations", "incomplete"]},
                        ).response
                finally:
                    context.close()
        return scans

    # --- what a scan says -------------------------------------------------------------

    @staticmethod
    def _findings(response: dict[str, Any]
                  ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        """The violations of one scan by rule and component, each with its nodes."""
        found: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for violation in response["violations"]:
            for node in violation["nodes"]:
                key = (violation["id"], component(node["target"][0]))
                found.setdefault(key, []).append(node)
        return found

    @staticmethod
    def _said(rule: str, nodes: list[dict[str, Any]]) -> str:
        """A finding in the scanner's words, for the one who has to mend it."""
        lines = [f"{rule}: {len(nodes)} node(s)"]
        for node in nodes[:3]:
            lines.append(f"    target: {', '.join(node['target'])}")
            lines.append(f"    html:   {node['html'][:160]}")
            checks = node.get("any") or node.get("all") or node.get("none") or []
            for check in checks[:1]:
                lines.append(f"    says:   {check['message'][:200]}")
        return "\n".join(lines)

    def assert_nothing_past_the_baseline(self, route: str, layout: str) -> None:
        for width, theme in product(_WIDTHS, _THEMES):
            with self.subTest(width=width, theme=theme):
                response = self.scans[(route, layout, width, theme)]
                beyond = {key: nodes for key, nodes in self._findings(response).items()
                          if key not in baseline(theme)}
                if beyond:
                    self.fail(f"{route} in the {layout} layout at {width} px in "
                              f"{theme} adds to the baseline:\n" + "\n".join(
                                  f"{rule} on {part} — " + self._said(rule, nodes)
                                  for (rule, part), nodes in sorted(beyond.items())))

    # --- the pages --------------------------------------------------------------------

    def test_the_wall_adds_nothing_to_the_baseline(self):
        self.assert_nothing_past_the_baseline("/status", "sidebar")

    def test_a_nodes_page_adds_nothing_to_the_baseline(self):
        self.assert_nothing_past_the_baseline("/status/ci", "sidebar")

    def test_the_kiosk_adds_nothing_to_the_baseline(self):
        self.assert_nothing_past_the_baseline("/status", "kiosk")

    def test_every_entry_of_the_baseline_is_still_found(self):
        # an entry that no scan finds any more has been mended, and leaves with the
        # change that mended it: the baseline carries what stands, never what stood —
        # in each theme what stands there
        for theme in _THEMES:
            with self.subTest(theme=theme):
                seen = {key for (*_, scanned), response in self.scans.items()
                        if scanned == theme for key in self._findings(response)}
                self.assertEqual(sorted(baseline(theme) - seen), [])

    def test_the_scans_covered_every_page_at_every_width(self):
        self.assertEqual(sorted(self.scans),
                         sorted((route, layout, width, theme)
                                for width in _WIDTHS
                                for theme in _THEMES
                                for layout, routes in (("sidebar", ("/status",
                                                                    "/status/ci")),
                                                       ("kiosk", ("/status",)))
                                for route in routes))
        # the library's theme among the ones read, which a browser that never chose
        # draws
        self.assertIn(LOOKS_BY_KEY["theme"].default, _THEMES)
        # the rules the scans ran were WCAG 2.2's at A and AA, and nothing else
        for response in self.scans.values():
            for violation in response["violations"]:
                self.assertTrue(set(violation["tags"]) & set(_TAGS), violation["id"])
