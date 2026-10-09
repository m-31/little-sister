"""Copy Markdown and Copy Rich HTML, held against a real browser (ADR-0115 decision 8).

What reaches a clipboard is nothing a response can show, and it depends on where the
page is served from. The interface a page writes a clipboard through exists in a secure
context only — https, or the machine's own loopback address — and a monitor inside a
network is mostly reached over plain http by a host's name. So both buttons are pressed
on both: on ``127.0.0.1``, and on a name the browser is told to resolve to the same
server, where the interface is missing and the copy event is the only way there is.

What a press left on the clipboard is read as its reader gets it, by pasting: a paste
hands over its members by type, on either origin and with nothing to permit. A sentence
copied by hand stands on the clipboard before every press, so a button that says it
copied and did not is seen.

Served by a real server to headless Chromium, which clicks, copies and pastes as a hand
does. Skipped wherever Playwright or a Chromium binary is unavailable, so the ordinary
gate does not grow a browser dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import parse

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

#: The loopback address, which a browser takes for a secure context, and a host's
#: name, which over plain http it does not. ``.test`` is reserved for exactly this
#: (RFC 2606), and the browser is told where the name leads, so nothing is looked up.
_LOOPBACK = "127.0.0.1"
_NAME = "sister.test"

#: Every page that offers the pair of buttons, by the document it hands over.
_PAGES = (
    ("the tree", "/copy"),
    ("a branch", "/copy/nexus"),
    ("a leaf", "/copy/nexus/disk"),
    ("a line", "/copy/nexus/disk?reason=volume1"),
)
#: The one a test presses on where one page says it all.
_LEAF = "/copy/nexus/disk"

#: What stands on the clipboard before a press, and what a hand copies after one.
_BEFORE = "copied by hand before the press"
_AFTER = "and a sentence copied by hand afterwards"

#: What the page says of a press.
_RICH_COPIED = "Rich HTML copied."
_MARKDOWN_COPIED = "Markdown copied."
_MARKDOWN_INSTEAD = "Rich HTML is unavailable; Markdown copied instead."
_BY_HAND = "Clipboard access failed. The Markdown is selected for manual copying."

#: A field a hand can paste into, which keeps what the paste handed over. The test
#: adds it to the page; it is no part of one.
_FIELD = """
() => {
  const field = document.createElement('div');
  field.id = 'pasted';
  field.contentEditable = 'true';
  field.style.minHeight = '2em';
  document.body.appendChild(field);
  window.pasted = null;
  field.addEventListener('paste', (event) => {
    window.pasted = {
      types: Array.from(event.clipboardData.types),
      html: event.clipboardData.getData('text/html'),
      plain: event.clipboardData.getData('text/plain'),
    };
    event.preventDefault();
  });
}
"""

#: The page's document: its Markdown, and the same as the server rendered it.
_DOCUMENT = """
() => [document.getElementById('ls-copy-source').value,
       JSON.parse(document.getElementById('ls-copy-html').textContent)]
"""

#: Where the Markdown stands once the page has given up on the clipboard.
_SOURCE = """
() => {
  const source = document.getElementById('ls-copy-source');
  return {
    open: document.getElementById('ls-copy-source-details').open,
    focused: document.activeElement === source,
    selected: source.value.substring(source.selectionStart, source.selectionEnd),
  };
}
"""

#: What kind of origin a page was served from: whether the browser takes it for a
#: secure context, and whether a page has a clipboard interface there.
_ORIGIN = "[window.isSecureContext, navigator.clipboard !== undefined]"

#: What a clipboard wraps a fragment in on its way, which is no part of the document.
_WRAPPING = frozenset({"html", "head", "body", "meta"})


def _shape(html: str) -> list[tuple[str, str, str]]:
    """A rendered document as its reader gets it: every element in order, with where
    it leads and the text it holds — whatever it was wrapped in on the way."""
    return [(element.tag, element.attrs.get("href", ""), element.text())
            for element in parse(html).walk() if element.tag not in _WRAPPING]


def _estate() -> StatusTree:
    """A branch over a failing leaf and a warning one. One line carries a link, so
    the rendered document holds something its Markdown does not look like."""
    tree = StatusTree()
    tree.upsert("/nexus/disk", StatusCode.ERROR,
                {"volume1": "97 % used on /volume1 — 12 GiB left"})
    tree.upsert("/nexus/memory", StatusCode.WARN,
                "88 % used, see [the runbook](https://runbooks.example.org/memory)")
    return tree


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class _CopyCase(unittest.TestCase):
    """A real server and headless Chromium for a class of tests, reached by the
    address the class names; for each test a page of its own, signed in."""

    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""
    #: The host the pages are opened by, and whether a browser takes a page served
    #: from there for a secure context. Every page a test opens is held to it: on
    #: the other kind of origin each test here would be testing something else.
    host: ClassVar[str]
    secure: ClassVar[bool]

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(
                executable_path=(str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file()
                                 else None),
                args=[f"--host-resolver-rules=MAP {_NAME} {_LOOPBACK}"])
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(f"no chromium available: {error}") from error
        cls.saved = app_module.status_tree
        cls.server = make_server(_LOOPBACK, 0, app_module.app, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://{cls.host}:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        app_module.status_tree = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        app_module.status_tree = _estate()
        # A browser lets a page its reader has just clicked write to the clipboard,
        # and the loopback class is about that interface. Headless Chromium 153,
        # the one Playwright 1.63 installs, refuses it unless it is granted, where
        # 141 did not: without the grant every press below is the copy command's
        # alone. So the context grants it, as the reader's click does.
        context = self.browser.new_context(permissions=["clipboard-write"])
        self.addCleanup(context.close)
        self.page = context.new_page()
        self.page.route("https://cdn.jsdelivr.net/**", self._vendored)
        self.page.goto(f"{self.base}/login")
        self.page.fill("#username", "pan")
        self.page.fill("#password", "12345678")
        with self.page.expect_navigation():
            self.page.click("button[type=submit]")

    @staticmethod
    def _vendored(route: Any) -> None:
        """Bootstrap from the vendored copy where there is one, the CDN otherwise."""
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    # --- the hand ---------------------------------------------------------------------

    def _open(self, url: str) -> None:
        """Open a page that offers the buttons and give it a field to paste into."""
        page = self.page
        page.goto(f"{self.base}{url}")
        self.assertEqual(page.evaluate(_ORIGIN), [self.secure, self.secure])
        page.evaluate(_FIELD)

    def _document(self) -> tuple[str, str]:
        markdown, rendered = self.page.evaluate(_DOCUMENT)
        return str(markdown), str(rendered)

    def _copy_by_hand(self, text: str) -> None:
        """Put ``text`` on the clipboard as a reader would: select it and copy it."""
        page = self.page
        page.evaluate(
            "(text) => { document.getElementById('pasted').textContent = text; }", text)
        page.click("#pasted")
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.press("ControlOrMeta+C")
        page.evaluate("() => { document.getElementById('pasted').textContent = ''; }")

    def _paste(self) -> dict[str, Any]:
        """What a paste hands over now."""
        page = self.page
        page.evaluate("() => { window.pasted = null; }")
        page.click("#pasted")
        page.keyboard.press("ControlOrMeta+V")
        page.wait_for_function("window.pasted !== null")
        pasted: dict[str, Any] = page.evaluate("window.pasted")
        return pasted

    def _press(self, which: str) -> str:
        """Press a button while the clipboard holds something else; what the page
        says once it has finished."""
        self._copy_by_hand(_BEFORE)
        self.assertEqual(self._paste()["plain"], _BEFORE)
        page = self.page
        button = f"[data-copy-format={which}]"
        page.click(button)
        page.wait_for_function(
            "(button) => !document.querySelector(button).disabled"
            " && document.getElementById('ls-copy-status').textContent !== ''",
            arg=button)
        return str(page.inner_text("#ls-copy-status"))

    # --- what arrived -----------------------------------------------------------------

    def assert_rich_arrived(self, said: str) -> None:
        """The page said it copied Rich HTML, and a paste gets the two members: the
        document as rendered, and its Markdown."""
        markdown, rendered = self._document()
        self.assertEqual(said, _RICH_COPIED)
        pasted = self._paste()
        self.assertEqual(sorted(pasted["types"]), ["text/html", "text/plain"])
        self.assertEqual(pasted["plain"], markdown)
        self.assertEqual(_shape(pasted["html"]), _shape(rendered))
        # and that is a document: a heading, and more than a heading
        self.assertEqual(_shape(rendered)[0][0], "h2")
        self.assertGreater(len(_shape(rendered)), 3)

    def assert_markdown_arrived(self, said: str, *,
                                saying: str = _MARKDOWN_COPIED) -> None:
        """The page said so, and a paste gets the Markdown and nothing beside it."""
        markdown, _rendered = self._document()
        self.assertEqual(said, saying)
        pasted = self._paste()
        self.assertEqual(pasted["types"], ["text/plain"])
        self.assertEqual(pasted["plain"], markdown)
        self.assertTrue(markdown.startswith("## "), markdown[:40])

    def assert_on_every_page(self, which: str, arrived: Callable[[str], None]) -> None:
        for name, url in _PAGES:
            with self.subTest(name):
                self._open(url)
                arrived(self._press(which))


class OnTheLoopbackAddressTests(_CopyCase):
    """Where the clipboard interface exists: the machine's own address."""

    host, secure = _LOOPBACK, True

    def test_rich_puts_the_rendered_document_beside_its_markdown(self):
        self.assert_on_every_page("rich", self.assert_rich_arrived)

    def test_markdown_puts_the_markdown_alone(self):
        self.assert_on_every_page("markdown", self.assert_markdown_arrived)

    def test_an_interface_that_refuses_is_not_the_last_word(self):
        """A browser can have the interface and deny it to this page. The copy event
        is tried then as well."""
        self._open(_LEAF)
        self.page.evaluate("""() => {
            window.refused = 0;
            navigator.clipboard.write = () => {
              window.refused += 1;
              return Promise.reject(new Error('denied'));
            };
        }""")
        self.assert_rich_arrived(self._press("rich"))
        self.assertEqual(self.page.evaluate("window.refused"), 1)

    def test_where_only_text_can_be_written_the_markdown_is_and_the_page_says_so(self):
        """Neither rung carries the rendered document — the interface refuses it and
        the command copies nothing — and plain text can still be written."""
        self._open(_LEAF)
        self.page.evaluate("""() => {
            navigator.clipboard.write = () => Promise.reject(new Error('denied'));
            document.execCommand = () => false;
        }""")
        self.assert_markdown_arrived(self._press("rich"), saying=_MARKDOWN_INSTEAD)


class OverPlainHttpByNameTests(_CopyCase):
    """Where it does not: plain http on a host's name, as an instance inside a
    network is mostly reached. The copy event is the only way to a clipboard there."""

    host, secure = _NAME, False

    def test_rich_puts_the_rendered_document_beside_its_markdown(self):
        self.assert_on_every_page("rich", self.assert_rich_arrived)

    def test_markdown_puts_the_markdown_alone(self):
        self.assert_on_every_page("markdown", self.assert_markdown_arrived)

    def test_the_copy_is_made_while_the_click_is_being_answered(self):
        """A browser lets a page copy only while it is answering the click, so nothing
        is awaited before this rung. An observer of what the page says is told at the
        first moment the page's script lets anything else run — after *Copying…* was
        said, and by then the copy is made and said too."""
        self._open(_LEAF)
        self.page.evaluate("""() => {
            const said = document.getElementById('ls-copy-status');
            window.saidAtFirst = null;
            new MutationObserver(() => {
              window.saidAtFirst ??= said.textContent;
            }).observe(said, {childList: true, characterData: true, subtree: true});
        }""")
        self.assert_rich_arrived(self._press("rich"))
        self.assertEqual(self.page.evaluate("window.saidAtFirst"), _RICH_COPIED)

    def test_a_copy_event_that_never_arrives_leaves_the_markdown_and_says_so(self):
        """The command answers yes whenever the selection was copied, and the
        selection is the Markdown. Whether the two members were set is the event's
        to say, and where it never reaches the page they were not."""
        self._open(_LEAF)
        self.page.evaluate("""() => {
            window.addEventListener(
                'copy', (event) => event.stopImmediatePropagation(), true);
        }""")
        self.assert_markdown_arrived(self._press("rich"), saying=_MARKDOWN_INSTEAD)

    def test_where_nothing_copies_the_markdown_is_selected_for_the_hand(self):
        for which in ("rich", "markdown"):
            with self.subTest(which):
                self._open(_LEAF)
                self.page.evaluate("() => { document.execCommand = () => false; }")
                markdown, _rendered = self._document()
                self.assertEqual(self._press(which), _BY_HAND)
                self.assertEqual(self.page.evaluate(_SOURCE),
                                 {"open": True, "focused": True, "selected": markdown})
                # and the clipboard is as it was
                self.assertEqual(self._paste()["plain"], _BEFORE)

    def test_a_copy_by_hand_afterwards_is_the_hands_own(self):
        """The rung listens for one copy event, its own, and leaves nothing on the
        page: what a reader copies next is what the reader selected."""
        self._open(_LEAF)
        fields = "document.querySelectorAll('textarea').length"
        before = self.page.evaluate(fields)
        self.assert_rich_arrived(self._press("rich"))
        self.assertEqual(self.page.evaluate(fields), before)
        self._copy_by_hand(_AFTER)
        pasted = self._paste()
        self.assertEqual(pasted["plain"], _AFTER)
        self.assertNotIn("<h2", pasted["html"])
