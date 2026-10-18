"""Our own pages send no Content-Security-Policy report (ADR-0048, ADR-0030) — held
against a real browser.

The policy ships Report-Only, so a report is all it does, and a report our own pages
send on every view buries the ones it is there to collect. Two kinds did. Bootstrap
draws a switch's knob and the bar's burger as ``data:`` images, which ``img-src``
takes because a ``data:`` image calls no host. And ``/links`` sends the viewer's
browser to the sites it links to for their icons — the favicon of an entry with no
mark, a remote mark's own URL — which the page's own policy allows, taken from
``links.yaml`` as the page renders.

What would be reported is decided by the browser, so it is the browser that is asked:
every ``securitypolicyviolation`` a page raises is counted, on the wall and a node's
page, whose switches carry the knob, and on ``/links``, whose two icons from elsewhere
are on hosts reserved never to resolve (RFC 2606) — so each is asked for, fails, and
becomes the neutral glyph, which is how the test knows it was asked for — at a desk's
width and at a phone's, where the bar shows its burger. Served by a real server to
headless Chromium. Skipped wherever Playwright or a Chromium binary is unavailable, so
the ordinary gate does not grow a browser dependency (``docs/testing-the-gui.md``,
Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister import links
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

#: Bootstrap as ``tests/sweep_contrast.py`` vendors it (``docs/testing-the-gui.md``,
#: Mode 4), where there is a copy; the CDN otherwise.
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: A desk, and a phone: below Bootstrap's ``lg`` the bar folds its sections behind
#: the burger.
_SCREENS = (
    ("a desk", {"viewport": {"width": 1280, "height": 800}}),
    ("a phone", {"viewport": {"width": 390, "height": 844}, "is_mobile": True,
                 "has_touch": True}),
)

#: The two icons ``/links`` sends a browser elsewhere for, on reserved names.
_FAVICON_SITE = "https://chef.test/tool"
_REMOTE_MARK = "https://marks.test/phoenix.svg"

#: An entry of the list — the roster of icon names at the page's foot holds images
#: too, in a fold that is closed.
_ENTRY = ".ls-links__entry"

#: Every violation a page raises, as the browser reports it to the page itself.
_COUNT_VIOLATIONS = """
window.__violations = [];
document.addEventListener('securitypolicyviolation', (event) => {
  window.__violations.push(event.effectiveDirective + ' ' + event.blockedURI);
});
"""


def _estate() -> StatusTree:
    """A branch over two leaves, one of them failing, so the wall has cards and a
    node's page has a band with its switches."""
    tree = StatusTree()
    tree.upsert("/nexus/disk", StatusCode.ERROR, "97 % used on /volume1")
    tree.upsert("/nexus/memory", StatusCode.OK, "41 % used")
    return tree


def _links() -> links.LinksConfig:
    """An entry with no mark, one with a remote mark, and one with a mark of ours."""
    remote = links.Icon(name="phoenix", on_light=links.IconFile(url=_REMOTE_MARK),
                        on_dark=links.IconFile(url=_REMOTE_MARK))
    return links.LinksConfig(
        icons={"phoenix": remote},
        sources=(Path("config/links/links.yaml"),),
        groups=(links.Group(title="Toolbox", links=(
            links.Link(title="Cyber Chef", url=_FAVICON_SITE),
            links.Link(title="Phoenix", url="https://phoenix.test/", icon="phoenix"),
            links.Link(title="Grafana", url="https://grafana.test/", icon="grafana"),
        )),))


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class OwnPagesReportNothingTests(unittest.TestCase):
    """A real server and headless Chromium; for each page and screen a context of
    its own, signed in, counting what the page reports."""

    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(
                executable_path=(str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file()
                                 else None))
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(f"no chromium available: {error}") from error
        cls.saved = app_module.status_tree
        app_module.status_tree = _estate()
        # The page reads its file and starts a probe pass when it opens; both are
        # held out here, the pass being the instance's and not the browser's.
        cls.patches = [
            mock.patch.object(app_module, "current_links", return_value=_links()),
            mock.patch.object(app_module.link_probe, "refresh_if_due"),
        ]
        for patch in cls.patches:
            patch.start()
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        for patch in reversed(cls.patches):
            patch.stop()
        app_module.status_tree = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    @staticmethod
    def _vendored(route: Any) -> None:
        """Bootstrap from the vendored copy where there is one, the CDN otherwise."""
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _open(self, path: str, screen: dict[str, Any]) -> Any:
        """``path`` on ``screen``, signed in, with the page's violations counted from
        its first byte."""
        context = self.browser.new_context(**screen)
        self.addCleanup(context.close)
        context.add_init_script(_COUNT_VIOLATIONS)
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}{path}")
        page.wait_for_load_state("load")
        return page

    @staticmethod
    def _wait_for(page: Any, condition: str, *, seconds: float = 5.0) -> None:
        """Wait until ``condition`` holds in the page.

        Asked from here rather than with ``wait_for_function``, which evaluates its
        condition with ``eval`` inside the page — a ``script-src`` report of the
        test's own, on the one page whose reports are the point.
        """
        for _ in range(int(seconds / 0.05)):
            if page.evaluate(condition):
                return
            page.wait_for_timeout(50)
        raise AssertionError(f"never held: {condition}")

    @staticmethod
    def _settled(page: Any) -> list[str]:
        """What the page reported, once a report has had time to be raised."""
        page.wait_for_timeout(300)
        return page.evaluate("window.__violations")

    def test_the_wall_and_a_node_page_report_nothing_of_their_own_controls(self):
        for name, screen in _SCREENS:
            for path in ("/status", "/status/nexus"):
                with self.subTest(screen=name, path=path):
                    page = self._open(path, screen)
                    # Bootstrap's stylesheet is what draws the knob as a data: image;
                    # a page it did not reach would report nothing and prove nothing
                    knob = page.evaluate(
                        "getComputedStyle(document.querySelector("
                        "'.form-switch .form-check-input')).backgroundImage")
                    self.assertTrue(knob.startswith('url("data:'), knob)
                    self.assertEqual(self._settled(page), [])

    def test_links_reports_none_of_the_icons_it_sends_a_browser_elsewhere_for(self):
        for name, screen in _SCREENS:
            with self.subTest(screen=name):
                page = self._open("/links", screen)
                # each icon from elsewhere was asked for and failed, and the page
                # drew the glyph in its place; the mark of ours that the theme shows
                # loaded from our own origin — the one for a dark canvas, in the
                # library's theme, cyberpunk
                self._wait_for(page, f"document.querySelectorAll("
                                     f"'{_ENTRY} svg.ls-links__icon').length === 2")
                ours = page.evaluate(
                    f"[...document.querySelectorAll('{_ENTRY} img.ls-links__icon')]"
                    ".filter(image => getComputedStyle(image).display !== 'none')"
                    ".map(image => [new URL(image.src).pathname, image.naturalWidth])")
                self.assertEqual([(path, width > 0) for path, width in ours],
                                 [("/links/icon/on-dark/grafana", True)])
                self.assertEqual(self._settled(page), [])


if __name__ == "__main__":
    unittest.main()
