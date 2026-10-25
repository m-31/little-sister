"""The tree in a browser (ADR-0127): a click opens and closes a node in its place,
the tab's map keeps what a viewer set through the refresh and a reload, the browser's
find opens what it finds, the head's icons and the band's three buttons set the
folds, and a close holds for its node's incident; and the head's row — its controls
one toolbar, the node's actions before the state and the icons, what the row has no
room for behind ⋯, the state beneath where the name would be cut, *⌄ all N* beneath a
box's lines, and an admin's ‖ cloning the page's editor into the box; and in cyberpunk,
the culprit a neon tube on every vivid surface.

Stage 3's first two slices of backlog #91 — the tree's mechanics with today's look,
and the head's row. Served
by a real server to headless Chromium on the page's own clock, as
``tests/test_tree_state_browser.py`` is; the server's clock is held where a test
reads the time a render carries. Skipped wherever Playwright or a Chromium binary is
unavailable (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import json
import re
import threading
import unittest
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import actions as actions_module
from little_sister import app as app_module
from little_sister import instants
from little_sister.actions import Action
from little_sister.checks.metadata import Stated
from little_sister.first_look import FirstLooks
from little_sister.nodes import NodeMeta
from little_sister.reasons import Entry
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusTree
from tests.browser_looks import looks
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

try:  # pragma: no cover - environment probe: the scanner is the browser group's
    from axe_playwright_python.sync_playwright import Axe
except ImportError:  # pragma: no cover
    Axe = None  # type: ignore[assignment,misc]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

_KEY = "ls-wall-map"
_MAP = f"window.sessionStorage.getItem({_KEY!r})"
_FRAGMENT = re.compile(r"[?&]fragment=1")
_NOON = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)

#: The estate: a card of five quiet aspects and one erupting, each aspect's probe a
#: chip; a card whose children mix — three quiet leaves as chips, a warning, a roster
#: that claims `show_when_quiet`, a leaf that fails and recovers under the hand —
#: and a deep chain for a find to reach beneath two closed nodes. Its deployment
#: says how those levels start (:data:`_ESTATE_LOOK`), since a level nobody speaks
#: for starts open.
_NAS = "/nas"
_WEB = "/web"
_API = "/web/api"
_CDN = "/web/cdn"
_DNS = "/web/dns"
_MAIL = "/web/mail"
_ROSTER = "/web/roster"
_FLAKY = "/web/flaky"
_DEEP = "/deep"
_DEEP_LEAF = "/deep/a/leaf"
_DEEP_LINE = "the line beneath two closed nodes"
_OTHER_LEAF = "/deep/b/leaf"
_OTHER_LINE = "another line beneath another closed node"
#: How the estate's deployment says its levels start, in its `nodes.yaml`
#: (ADR-0128): every aspect's probe and every leaf of the deep chain as chips, and
#: the web tier's children, its warning and its failure opening their way by the
#: failure budget, its roster by its claim.
_ESTATE_LOOK = {
    _NAS: NodeMeta(look=Stated(children=Stated(chips=True))),
    _WEB: NodeMeta(look=Stated(chips=True)),
    _DEEP: NodeMeta(look=Stated(children=Stated(chips=True))),
}
#: The estate's look without its word for the web tier, which the built-in look then
#: draws open, every box of it.
_WEB_BUILT_IN = {path: meta for path, meta in _ESTATE_LOOK.items() if path != _WEB}

#: Counts the MutationObserver callbacks of the page's scripts, by observer, from
#: before the scripts run (an init script).
_COUNT_OBSERVERS = """
    window.__observers = [];
    const Native = window.MutationObserver;
    window.MutationObserver = function (callback) {
      const entry = {calls: 0};
      window.__observers.push(entry);
      return new Native(function (records, observer) {
        entry.calls += 1;
        return callback(records, observer);
      });
    };
    window.MutationObserver.prototype = Native.prototype;
"""


def _estate() -> StatusTree:
    tree = StatusTree()
    for aspect in ("alpha", "beta", "gamma", "delta", "epsilon"):
        tree.upsert(f"{_NAS}/{aspect}/probe", StatusCode.OK)
    tree.upsert(f"{_NAS}/zeta/probe", StatusCode.ERROR, ["zeta is down"])
    tree.upsert(_API, StatusCode.OK, ["200 in 40 ms", "certificate fine"])
    tree.upsert(_CDN, StatusCode.OK)
    tree.upsert(_DNS, StatusCode.WARN, ["slow"])
    tree.upsert(_MAIL, StatusCode.OK)
    tree.upsert(_ROSTER, StatusCode.OK, [Entry("one", "host one fine", StatusCode.OK),
                                          Entry("two", "host two fine", StatusCode.OK)],
                members=True, show_when_quiet=True)
    tree.upsert(_FLAKY, StatusCode.ERROR, ["flaky is down"])
    tree.upsert(_DEEP_LEAF, StatusCode.OK, [_DEEP_LINE])
    tree.upsert(_OTHER_LEAF, StatusCode.OK, [_OTHER_LINE])
    tree.set_title(_WEB, "The web tier")
    return tree


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class _BrowserCase(unittest.TestCase):
    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""
    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1000, "height": 700}, "reduced_motion": "reduce"}
    #: How the deployment says the estate's levels start, a class's to widen for the
    #: levels it adds, or a test's to set before it draws the wall.
    estate_look: Mapping[str, NodeMeta] = _ESTATE_LOOK

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
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        app_module.status_tree = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.tree = _estate()
        app_module.status_tree = self.tree
        # the server's clock, held: what each render stamps on the grid
        self.server_now = _NOON
        clock = mock.patch.object(instants, "now", side_effect=lambda: self.server_now)
        clock.start()
        self.addCleanup(clock.stop)
        self.context = self.browser.new_context(**self.drawn_in)
        self.addCleanup(self.context.close)
        self.context.route("https://cdn.jsdelivr.net/**", self._vendored)
        self.page = self._signed_in(self.context)
        # the estate's look, read with the configuration a test may patch; a test that
        # says its own sets `app_module.first_looks`, which speaks instead
        looks = mock.patch.object(app_module, "_first_looks", self._estate_looks)
        looks.start()
        self.addCleanup(looks.stop)
        self.fragments: list[str] = []
        self.page.on("request", lambda request: (
            self.fragments.append(request.url)
            if _FRAGMENT.search(request.url) else None))
        self.errors: list[str] = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def tearDown(self) -> None:
        self.assertEqual(self.errors, [])

    def _estate_looks(self) -> FirstLooks:
        """The first look the page draws: a test's own, or the estate's."""
        if app_module.first_looks is not None:
            return app_module.first_looks
        return FirstLooks((), dict(self.estate_look), app_module.config,
                          app_module.status_tree.named_by_run)

    def _signed_in(self, context: Any) -> Any:
        page = context.new_page()
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        return page

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    # --- the hand ---------------------------------------------------------------------

    def _wall(self, url: str = "/status", page: Any | None = None) -> Any:
        page = page or self.page
        page.clock.install(time=_NOON)
        page.goto(f"{self.base}{url}")
        page.wait_for_selector("#status-grid .status-card")
        page.clock.pause_at(_NOON + timedelta(seconds=5))
        return page

    def _node(self, path: str, page: Any | None = None) -> Any:
        return (page or self.page).locator(f'.tree-node[data-node="{path}"]')

    def _chip(self, path: str, page: Any | None = None) -> Any:
        return self._node(path, page).locator(":scope > .tree-chip")

    def _hold(self, path: str, page: Any | None = None) -> Any:
        return self._node(path, page).locator(":scope > .tree-hold")

    def _head(self, path: str, page: Any | None = None) -> Any:
        node = self._node(path, page)
        return node.locator(
            ":scope > .status-card__head, "
            ":scope > .tree-hold > .tree-box > .status-node__self, "
            ":scope > .tree-hold > .tree-box > .viewed-head > .status-node__self")

    def _icon(self, path: str, kind: str, page: Any | None = None) -> Any:
        return self._head(path, page).locator(f'.node-icons > [data-control="{kind}"]')

    def _state(self, path: str, page: Any | None = None) -> str:
        return self._node(path, page).get_attribute("data-state-now") or ""

    def _why(self, path: str, page: Any | None = None) -> str:
        return self._node(path, page).get_attribute("data-why") or ""

    def _map(self, page: Any | None = None) -> dict[str, Any] | None:
        raw = (page or self.page).evaluate(_MAP)
        return None if raw is None else json.loads(raw)

    def _level_items(self, path: str, page: Any | None = None) -> list[str]:
        """A level's top-level items as the DOM has them: `run(a,b)` or `node(c)`."""
        return (page or self.page).evaluate("""path => {
            const level = document.querySelector(`.tree-kids[data-branch="${path}"]`);
            return Array.from(level.children).map(item => {
                const names = Array.from(item.classList.contains('tree-node')
                    ? [item] : item.querySelectorAll(':scope > .tree-node'))
                    .map(node => node.dataset.node.split('/').pop());
                const kind = item.classList.contains('tree-node') ? 'node'
                           : item.classList.contains('tree-solo') ? 'solo' : 'run';
                return kind + '(' + names.join(',') + ')';
            });
        }""", path)

    def _swap(self, page: Any | None = None) -> None:
        page = page or self.page
        page.evaluate("document.querySelector('#status-grid .status-card')"
                      ".dataset.drawn = 'before'")
        before = len(self.fragments)
        page.clock.run_for(10_000)
        page.wait_for_function(
            "document.querySelector('#status-grid [data-drawn]') === null",
            timeout=5000)
        self.assertGreater(len(self.fragments), before)

    def _reload(self, page: Any | None = None) -> None:
        page = page or self.page
        page.reload()
        page.wait_for_selector("#status-grid .status-card")

    def _band(self, page: Any | None = None) -> list[tuple[str, str, str]]:
        """The band's three buttons: mode, pressed, and the count shown."""
        return [tuple(button) for button in (page or self.page).evaluate("""() =>
            Array.from(document.querySelectorAll('.ls-band__mode')).map(button => [
                button.dataset.mode, button.getAttribute('aria-pressed'),
                button.querySelector('.ls-band__count').hidden ? ''
                    : button.querySelector('.ls-band__count').textContent])""")]


class ClickTests(_BrowserCase):
    """A click opens and closes a node in its place."""

    def test_a_click_opens_a_chip_where_it_stands_and_closes_it_again(self):
        self._wall()
        self.assertEqual(self._level_items(_WEB),
                         ["run(api,cdn)", "node(dns)", "node(flaky)", "run(mail)",
                          "node(roster)"])
        self.assertEqual(self._state(_CDN), "closed")
        self.assertEqual(self._why(_CDN), "drawn")
        self.assertEqual(self._hold(_CDN).get_attribute("hidden"), "until-found")
        cards = self.page.locator(".status-grid > .status-card")
        before = [card.bounding_box()["x"] for card in cards.all()]
        self._chip(_CDN).click()
        # open in its place: the run split around it, its box where the chip
        # stood, in the level's order; no card moved
        self.assertEqual(self._state(_CDN), "open")
        self.assertEqual(self._why(_CDN), "entry")
        self.assertEqual(self._level_items(_WEB),
                         ["run(api)", "node(cdn)", "node(dns)", "node(flaky)",
                          "run(mail)", "node(roster)"])
        self.assertIsNone(self._hold(_CDN).get_attribute("hidden"))
        self.assertEqual(self._chip(_CDN).get_attribute("hidden"), "")
        self.assertEqual(self._map(), {"v": 1, "mode": None,
                                       "nodes": {_CDN: {"open": True}}})
        self.assertEqual([card.bounding_box()["x"] for card in cards.all()], before)
        self.assertLess(self._node(_API).bounding_box()["y"],
                        self._hold(_CDN).bounding_box()["y"])
        self.assertLess(self._hold(_CDN).bounding_box()["y"],
                        self._node(_ROSTER).bounding_box()["y"])
        # the focus went to the other face's toggle, the head's name
        self.assertEqual(self.page.evaluate(
            "document.activeElement.getAttribute('data-control')"), "toggle")
        self.assertEqual(self.page.evaluate(
            "document.activeElement.closest('.tree-node').dataset.node"), _CDN)
        # a click on the head's state word closes it: the run whole again, the
        # entry gone, the focus on the chip
        self._head(_CDN).locator(".status-node__state").click()
        self.assertEqual(self._state(_CDN), "closed")
        self.assertEqual(self._level_items(_WEB),
                         ["run(api,cdn)", "node(dns)", "node(flaky)", "run(mail)",
                          "node(roster)"])
        self.assertIsNone(self._map())
        self.assertEqual(self.page.evaluate(
            "document.activeElement.className"), "tree-chip s-ok")
        self.assertEqual(self.page.evaluate(
            "document.activeElement.getAttribute('aria-expanded')"), "false")

    def test_a_card_closes_in_its_place_to_one_line(self):
        self._wall()
        cards = self.page.locator(".status-grid > .status-card")
        left = [box["x"] for box in [card.bounding_box() for card in cards.all()]]
        self._head(_NAS).locator(".status-card__name").click()
        self.assertEqual(self._state(_NAS), "closed")
        self.assertTrue(self._node(_NAS).evaluate(
            "card => card.classList.contains('is-closed')"))
        self.assertEqual(self._hold(_NAS).get_attribute("hidden"), "until-found")
        # its counts on the head's line, its icons gone, the other cards unmoved
        counts = self._head(_NAS).locator(".tree-counts")
        self.assertTrue(counts.is_visible())
        self.assertEqual(counts.text_content().replace(" ", ""), "15")
        self.assertFalse(self._head(_NAS).locator(".node-icons").is_visible())
        self.assertEqual([card.bounding_box()["x"] for card in cards.all()], left)
        self.assertLess(self._node(_NAS).bounding_box()["height"], 60)
        self.assertEqual(self._map()["nodes"], {_NAS: {"open": False}})
        self._head(_NAS).locator(".status-card__name").click()
        self.assertEqual(self._state(_NAS), "open")
        self.assertIsNone(self._map())

    def test_a_click_on_a_heads_title_closes_it_and_one_on_its_icons_does_not(self):
        self._wall()
        # on the title's room past the toolbar, which lies over the title's start
        # while the pointer is on the head
        middle = self._head(_WEB).locator(":scope > .status-head__middle")
        middle.scroll_into_view_if_needed()
        box = middle.bounding_box()
        self.page.mouse.click(box["x"] + box["width"] - 3,
                              box["y"] + box["height"] / 2)
        self.assertEqual(self._state(_WEB), "closed")
        self._head(_WEB).locator(".status-card__name").click()
        self.assertEqual(self._state(_WEB), "open")
        self._icon(_WEB, "chips").click()
        self.assertEqual(self._state(_WEB), "open")             # ▤ is its own control
        self._icon(_WEB, "chips").click()
        self.assertEqual(self._state(_WEB), "open")

    def test_a_drag_that_selects_the_heads_text_does_not_toggle(self):
        # on the state's words, which are no name, so no card comes up under the
        # pointer
        self._wall()
        state = self._head(_NAS).locator(".status-card__state")
        box = state.bounding_box()
        # across the state's words: the click that ends it lands on the head row
        self.page.mouse.move(box["x"] + 2, box["y"] + box["height"] / 2)
        self.page.mouse.down()
        self.page.mouse.move(box["x"] + box["width"] - 2, box["y"] + box["height"] / 2,
                             steps=6)
        self.page.mouse.up()
        self.assertEqual(self._state(_NAS), "open")
        self.assertTrue(self.page.evaluate(
            "window.getSelection().toString().length > 0"))
        # and a click where the pointer does not travel toggles
        state.click()
        self.assertEqual(self._state(_NAS), "closed")

    def test_a_modified_click_keeps_the_link(self):
        self._wall()
        # a click with a modifier, and a middle click, are left to the browser: the
        # page neither prevents them nor toggles. What the browser then does is the
        # platform's — Ctrl opens a tab on Linux and navigates in place on a Mac,
        # where Cmd opens one — so the test reads what the page did, after its own
        # handlers, and keeps the browser from following the link
        for init in ({"ctrlKey": True}, {"metaKey": True}, {"shiftKey": True},
                     {"altKey": True}, {"button": 1}):
            with self.subTest(click=init):
                left = self._chip(_CDN).evaluate("""(chip, init) => {
                    let left = null;
                    const after = e => {
                        left = !e.defaultPrevented;
                        e.preventDefault();
                    };
                    document.addEventListener('click', after);
                    chip.dispatchEvent(new MouseEvent('click',
                        Object.assign({bubbles: true, cancelable: true}, init)));
                    document.removeEventListener('click', after);
                    return left;
                }""", init)
                self.assertIs(left, True)
                self.assertEqual(self._state(_CDN), "closed")
        self.assertIsNone(self._map())
        # a plain one is taken
        prevented = self._chip(_CDN).evaluate("""chip => !chip.dispatchEvent(
            new MouseEvent('click', {bubbles: true, cancelable: true}))""")
        self.assertTrue(prevented)
        self.assertEqual(self._state(_CDN), "open")

    def test_enter_and_space_toggle_and_the_faces_are_buttons(self):
        self._wall()
        chip = self._chip(_CDN)
        self.assertEqual(chip.get_attribute("role"), "button")
        self.assertEqual(chip.get_attribute("aria-expanded"), "false")
        chip.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(self._state(_CDN), "open")
        toggle = self._head(_CDN).locator('[data-control="toggle"]')
        self.assertEqual(toggle.get_attribute("role"), "button")
        self.assertEqual(toggle.get_attribute("aria-expanded"), "true")
        self.assertTrue(toggle.evaluate("link => document.activeElement === link"))
        self.page.keyboard.press(" ")
        self.assertEqual(self._state(_CDN), "closed")
        self.assertTrue(chip.evaluate("chip => document.activeElement === chip"))
        self.page.keyboard.press(" ")
        self.assertEqual(self._state(_CDN), "open")

    def test_a_chip_opened_below_the_fold_comes_into_view_and_one_in_view_stays(self):
        self._wall()
        # in view, with room beneath for its box: nothing scrolls
        self._chip(_CDN).evaluate("chip => chip.scrollIntoView({block: 'start'})")
        self.page.evaluate("window.scrollBy(0, -100)")
        before = self.page.evaluate("window.scrollY")
        self.assertGreater(before, 0)
        self._chip(_CDN).evaluate("chip => chip.click()")
        self.assertEqual(self._state(_CDN), "open")
        self.assertEqual(self.page.evaluate("window.scrollY"), before)
        self._head(_CDN).locator(".status-node__state").evaluate(
            "state => state.click()")
        # at the foot of a short window, its box landing below the fold: the box
        # comes up as far as it must, and no further
        self.page.set_viewport_size({"width": 1000, "height": 330})
        chip = self._chip(_MAIL)
        chip.evaluate("chip => chip.scrollIntoView({block: 'end'})")
        self.assertGreater(chip.bounding_box()["y"], 250)
        chip.evaluate("chip => chip.click()")
        self.assertEqual(self._state(_MAIL), "open")
        box = self._hold(_MAIL).bounding_box()
        self.assertGreaterEqual(box["y"], 0)
        self.assertLessEqual(round(box["y"] + box["height"]), 330)


class FoldTests(_BrowserCase):
    """The head's icons: ▤ sets the children, the funnel folds the healthy."""

    def test_chips_folds_every_child_and_opens_them_all_again(self):
        self._wall()
        chips = self._icon(_WEB, "chips")
        self.assertEqual(chips.get_attribute("aria-pressed"), "mixed")
        chips.click()
        self.assertEqual(chips.get_attribute("aria-pressed"), "true")
        self.assertEqual(self._level_items(_WEB),
                         ["run(api,cdn,dns,flaky,mail,roster)"])
        # the children's entries went, and the roster, whose claim would keep it
        # open, and the warning and the failure, as every failing child a fold
        # closes, got their own
        self.assertEqual(self._map()["nodes"], {_WEB: {"chips": True},
                                                _DNS: {"open": False},
                                                _FLAKY: {"open": False},
                                                _ROSTER: {"open": False}})
        self.assertEqual(self._why(_API), "parent")
        self.assertEqual(self._why(_DNS), "entry")
        self.assertEqual(self._why(_ROSTER), "entry")
        self.assertTrue(chips.evaluate(
            "button => button.classList.contains('is-changed')"))
        # pressed: a click opens every child
        chips.click()
        self.assertEqual(chips.get_attribute("aria-pressed"), "false")
        self.assertEqual(self._level_items(_WEB),
                         ["node(api)", "node(cdn)", "node(dns)", "node(flaky)",
                          "node(mail)", "node(roster)"])
        self.assertEqual(self._map()["nodes"], {_WEB: {"chips": False}})
        # a click on one child afterwards changes that child alone, and ▤ is mixed
        self._head(_CDN).locator(".status-node__state").click()
        self.assertEqual(chips.get_attribute("aria-pressed"), "mixed")
        self.assertEqual(self._map()["nodes"], {_WEB: {"chips": False},
                                                _CDN: {"open": False}})
        # mixed: a click folds them all
        chips.click()
        self.assertEqual(chips.get_attribute("aria-pressed"), "true")
        self.assertEqual(self._map()["nodes"], {_WEB: {"chips": True},
                                                _DNS: {"open": False},
                                                _FLAKY: {"open": False},
                                                _ROSTER: {"open": False}})

    def test_the_funnel_folds_the_healthy_and_a_press_takes_the_claims_too(self):
        self._wall()
        funnel = self._icon(_WEB, "ok")
        self.assertEqual(funnel.get_attribute("aria-pressed"), "false")
        # api, cdn, mail and the roster are healthy; the configured fold would leave
        # the roster, a press takes it: both counts ride on the button
        self.assertEqual(funnel.get_attribute("data-n"), "3")
        self.assertEqual(funnel.get_attribute("data-n-pressed"), "4")
        self.assertEqual(funnel.get_attribute("title"), "Fold the 4 healthy ones")
        funnel.click()
        self.assertEqual(funnel.get_attribute("aria-pressed"), "true")
        self.assertEqual(funnel.get_attribute("title"), "Show the 4 healthy ones")
        self.assertTrue(funnel.evaluate(
            "button => button.classList.contains('is-changed')"))
        for path in (_API, _CDN, _MAIL, _ROSTER):
            self.assertFalse(self._node(path).is_visible(), path)
        for path in (_DNS, _FLAKY):
            self.assertTrue(self._node(path).is_visible(), path)
        mark = self._node(_WEB).locator(":scope > .tree-hold > .tree-ok")
        self.assertTrue(mark.is_visible())
        self.assertEqual(mark.text_content(), "✓ +4 ok")
        self.assertEqual(self._map()["nodes"], {_WEB: {"ok": True}})
        # the fold stands through a swap and a reload
        self._swap()
        self.assertFalse(self._node(_ROSTER).is_visible())
        self.assertEqual(mark.text_content(), "✓ +4 ok")
        self._reload()
        self.assertFalse(self._node(_ROSTER).is_visible())
        # *✓ +N ok* opens them again
        self._node(_WEB).locator(":scope > .tree-hold > .tree-ok").click()
        self.assertTrue(self._node(_ROSTER).is_visible())
        self.assertEqual(self._icon(_WEB, "ok").get_attribute("aria-pressed"), "false")
        self.assertIsNone(self._map())

    def test_a_claiming_nodes_own_quiet_lines_fold_under_its_own_press_alone(self):
        self._wall()
        # a box's lines stand after its head's row, in the box
        lines = self._node(_ROSTER).locator(
            ":scope > .tree-hold > .tree-box > .reason-block > .status-node__reason")
        self.assertEqual(lines.count(), 2)
        self.assertTrue(lines.first.is_visible())
        # the parent's press folds the roster whole, not its lines one by one
        self._icon(_WEB, "ok").click()
        self.assertFalse(self._node(_ROSTER).is_visible())
        self._icon(_WEB, "ok").click()
        # its own funnel, pressed, folds its quiet lines
        own = self._icon(_ROSTER, "ok")
        self.assertEqual(own.get_attribute("data-n"), "0")
        self.assertEqual(own.get_attribute("data-n-pressed"), "2")
        own.click()
        self.assertFalse(lines.first.is_visible())
        self.assertEqual(self._node(_ROSTER).locator(":scope > .tree-hold .tree-ok")
                         .first.text_content(), "✓ +2 ok")
        self.assertEqual(self._map()["nodes"], {_ROSTER: {"ok": True}})

    def test_a_configured_fold_leaves_the_claims_and_a_press_takes_them(self):
        # until stage 4 no configuration folds, so the server's fold is put on by
        # hand: `data-ok="true"` is what it will draw
        self._wall()
        self.page.evaluate(f"""() => {{
            document.querySelector('.tree-node[data-node="{_WEB}"]')
                .setAttribute('data-ok', 'true');
            window.lsTree.apply(document.getElementById('status-grid'));
        }}""")
        funnel = self._icon(_WEB, "ok")
        self.assertEqual(funnel.get_attribute("aria-pressed"), "true")
        self.assertEqual(funnel.get_attribute("title"), "Show the 3 healthy ones")
        for path in (_API, _CDN, _MAIL):
            self.assertFalse(self._node(path).is_visible(), path)
        self.assertTrue(self._node(_ROSTER).is_visible())      # the claim stands
        mark = self._node(_WEB).locator(":scope > .tree-hold > .tree-ok")
        self.assertEqual(mark.text_content(), "✓ +3 ok")
        self.assertIsNone(self._map())                      # nothing of the viewer's
        self.assertFalse(funnel.evaluate("b => b.classList.contains('is-changed')"))
        # a press shows them; a second press folds them, the roster too, and its
        # entry stays though the configuration folds as well
        funnel.click()
        self.assertTrue(self._node(_ROSTER).is_visible())
        self.assertTrue(self._node(_API).is_visible())
        self.assertEqual(self._map()["nodes"], {_WEB: {"ok": False}})
        funnel.click()
        self.assertFalse(self._node(_ROSTER).is_visible())
        self.assertEqual(self._map()["nodes"], {_WEB: {"ok": True}})
        self.assertEqual(funnel.get_attribute("title"), "Show the 4 healthy ones")

    def test_the_funnel_stands_on_a_green_node_as_on_a_failing_one(self):
        self._wall()
        self.assertEqual(self._icon(f"{_NAS}/alpha", "ok").count(), 1)   # green
        self.assertEqual(self._icon(_NAS, "ok").count(), 1)              # red
        self.assertEqual(self._icon(f"{_NAS}/zeta", "ok").count(), 0)  # nothing healthy
        self.assertEqual(self._icon(f"{_NAS}/zeta", "chips").count(), 1)
        self.assertEqual(self._icon(_DNS, "chips").count(), 0)           # a leaf


#: Every card in a track of 170 pixels, as a desk narrower than the planner's widest
#: gives the cards it plans one track each: what *Close all* leaves them, since a
#: click never moves a card (ADR-0128 decision 6).
_NARROW_TRACKS = """
.status-grid { grid-template-columns: repeat(auto-fill, 170px) !important; }
.status-grid > .status-card { grid-column: auto !important; }
"""
_LINES = """el => {
    const range = document.createRange();
    range.selectNodeContents(el);
    return new Set(Array.from(range.getClientRects(), r => Math.round(r.top))).size;
}"""


class BandTests(_BrowserCase):
    """The band's three buttons, and the count of what the viewer set."""

    def test_a_closed_card_in_a_narrow_track_keeps_its_name_whole(self):
        # Closed whole, a card in a narrow track squeezed its name to a letter a line
        # beside its counts and its state; its head wraps instead, the name whole on its
        # first line and the state beneath
        self._wall()
        self.page.click('.ls-band__mode[data-mode="closed"]')
        self.page.add_style_tag(content=_NARROW_TRACKS)
        beneath = []
        for path in (_NAS, _WEB, _DEEP):
            head = self.page.locator(
                f'.status-card.tree-node[data-node="{path}"] > .status-card__head')
            name = head.locator(".status-card__name").element_handle()
            seen = name.bounding_box()
            state = head.locator(".status-card__state").bounding_box()
            with self.subTest(card=path):
                self.assertEqual(self.page.evaluate(_LINES, name), 1)
                # the state beside the name where the line holds both, else beneath
                below = state["y"] + 0.5 >= seen["y"] + seen["height"]
                self.assertTrue(below or state["x"] >= seen["x"] + seen["width"])
                beneath.append(below)
                # two lines at most: the name's, and the state's, at the right — the
                # row's padding and the state's margin short of its edge
                row = head.bounding_box()
                self.assertLess(row["height"], 3 * seen["height"])
                self.assertAlmostEqual(state["x"] + state["width"],
                                       row["x"] + row["width"], delta=6)
        # the narrow tracks put some state beneath its name
        self.assertTrue(any(beneath))

    def test_a_closed_card_with_room_keeps_its_one_line(self):
        # where the track holds the whole head, wrapping changes nothing: one line,
        # the title taking what is left and the state clear of it, as open
        self._wall()
        self.page.click('.ls-band__mode[data-mode="closed"]')
        head = self.page.locator(
            f'.status-card.tree-node[data-node="{_WEB}"] > .status-card__head')
        name = head.locator(".status-card__name").bounding_box()
        title = head.locator(".status-head__middle > .node-title").bounding_box()
        middle = head.locator(".status-head__middle").bounding_box()
        state = head.locator(".status-card__state").bounding_box()
        self.assertTrue(title["width"] > 0)
        self.assertLess(head.bounding_box()["height"], 1.5 * name["height"])
        self.assertLess(abs(state["y"] - title["y"]), name["height"] / 2)
        # the counts their own margin from the name, and not a pixel more
        counts = head.locator(".tree-counts")
        margin = counts.evaluate("el => parseFloat(getComputedStyle(el).marginLeft)")
        self.assertAlmostEqual(counts.bounding_box()["x"] - (name["x"] + name["width"]),
                               margin, delta=1)
        # the controls' clearance, 0.4em, between the room the title may fill and
        # the state's words
        padding = head.locator(".status-card__state").evaluate(
            "el => parseFloat(getComputedStyle(el).paddingLeft)")
        self.assertGreaterEqual(
            state["x"] + padding - (middle["x"] + middle["width"]), 5)

    def test_the_three_buttons_and_the_count(self):
        self._wall()
        self.assertEqual(self._band(), [("closed", "false", ""),
                                        ("configured", "true", ""),
                                        ("open", "false", "")])
        self._chip(_CDN).click()
        self._icon(_NAS, "chips").click()
        # the chip, ▤, and the failure ▤ folded, which keeps a close of its own
        self.assertEqual(self._band()[1], ("configured", "true", "· 3"))
        # *Close all*: everything the configuration opened closes, what the viewer
        # opened stays with the nodes above it
        self.page.click('.ls-band__mode[data-mode="closed"]')
        self.assertEqual(self._band(), [("closed", "true", "· 1"),
                                        ("configured", "false", ""),
                                        ("open", "false", "")])
        self.assertEqual(self._map(), {"v": 1, "mode": "closed",
                                       "nodes": {_CDN: {"open": True}}})
        self.assertEqual(self._state(_CDN), "open")
        self.assertEqual(self._why(_CDN), "entry")
        self.assertEqual(self._state(_WEB), "open")
        self.assertEqual(self._why(_WEB), "kept")
        for path in (_NAS, _DEEP, _DNS, _FLAKY, _ROSTER):
            self.assertEqual(self._state(path), "closed", path)
            self.assertEqual(self._why(path), "mode", path)
        self.assertEqual(self._icon(_WEB, "chips").get_attribute("aria-pressed"),
                         "mixed")
        # the statuses beneath change under the hand, and the map stands
        self.tree.upsert(_CDN, StatusCode.ERROR, ["cdn is down"])
        self.tree.upsert(_DNS, StatusCode.OK)
        self._swap()
        self.assertEqual(self._state(_CDN), "open")
        self.assertEqual(self._state(_DNS), "closed")
        self.assertEqual(self._band()[0], ("closed", "true", "· 1"))
        # a click on the button in force drops what it counts: everything closes
        self.page.click('.ls-band__mode[data-mode="closed"]')
        self.assertEqual(self._map(), {"v": 1, "mode": "closed", "nodes": {}})
        self.assertEqual(self._state(_CDN), "closed")
        self.assertEqual(self._state(_WEB), "closed")
        self.assertEqual(self._band()[0], ("closed", "true", ""))
        # *Open all* opens everything, the healthy shown
        self.page.click('.ls-band__mode[data-mode="open"]')
        self.assertEqual(self._map(), {"v": 1, "mode": "open", "nodes": {}})
        for path in (_NAS, _WEB, _CDN, _MAIL, f"{_NAS}/epsilon"):
            self.assertEqual(self._state(path), "open", path)
            self.assertTrue(self._node(path).is_visible(), path)
        self.assertEqual(self._why(_CDN), "mode")
        # *As configured* empties the map: the first look again, cdn now failing
        # and opened by its card's failure budget, dns recovered and drawn as a chip
        self.page.click('.ls-band__mode[data-mode="configured"]')
        self.assertIsNone(self._map())
        self.assertEqual((self._state(_CDN), self._why(_CDN)), ("open", "budget"))
        self.assertEqual((self._state(_DNS), self._why(_DNS)), ("closed", "drawn"))
        self.assertEqual(self._why(_ROSTER), "swq")
        self.assertEqual(self._band()[1], ("configured", "true", ""))

    def test_a_depth_in_the_address_counts_and_as_configured_drops_it(self):
        alpha = f"{_NAS}/alpha"
        self._wall(url="/status?depth=2")
        self.assertEqual(self._state(alpha), "closed")      # level 2, the viewer's word
        self.assertEqual(self._why(alpha), "drawn")
        # a failure the level closed opens within its card's budget (ADR-0128)
        self.assertEqual((self._state(_DNS), self._why(_DNS)), ("open", "budget"))
        self.assertEqual(self._band()[1], ("configured", "true", "· 1"))
        self._chip(alpha).click()
        self.assertEqual(self._band()[1], ("configured", "true", "· 2"))
        with self.page.expect_navigation():
            self.page.click('.ls-band__mode[data-mode="configured"]')
        self.page.wait_for_selector("#status-grid .status-card")
        self.assertNotIn("depth=", self.page.url)
        self.assertEqual(self._state(alpha), "open")
        self.assertIsNone(self._map())

    def test_the_buttons_and_icons_are_drawn_from_the_ink(self):
        self._wall()
        drawn = ("b => [getComputedStyle(b).borderTopColor, "
                 "getComputedStyle(b).backgroundColor]")
        funnel = self._icon(_WEB, "ok")
        rest = funnel.evaluate(drawn)
        ink = funnel.evaluate("b => getComputedStyle(b).color")
        self.assertNotEqual(rest[0], ink)                       # the edge at 75 %
        self.assertIn("/ 0.75)", rest[0])                        # of the ink
        self.assertEqual(rest[1], "rgba(0, 0, 0, 0)")           # no wash at rest
        funnel.click()
        pressed = funnel.evaluate(drawn)
        self.assertEqual(pressed[0], ink)                   # the full ink as the edge
        self.assertNotEqual(pressed[1], "rgba(0, 0, 0, 0)")     # and a wash
        funnel.click()
        # ▤ mixed: the edge, and half the wash
        chips = self._icon(_WEB, "chips")
        self.assertEqual(chips.get_attribute("aria-pressed"), "mixed")
        mixed = chips.evaluate(drawn)
        self.assertEqual(mixed[0], ink)
        self.assertNotIn(mixed[1], ("rgba(0, 0, 0, 0)", pressed[1]))
        chips.click()
        self.assertEqual(chips.evaluate(drawn)[1], pressed[1])
        # the band's: at rest and in force
        buttons = self.page.locator(".ls-band__mode")
        band_ink = buttons.nth(1).evaluate("b => getComputedStyle(b).color")
        edge = "b => getComputedStyle(b).borderTopColor"
        self.assertEqual(buttons.nth(1).evaluate(edge), band_ink)
        self.assertNotEqual(buttons.nth(0).evaluate(edge), band_ink)
        # `.is-changed` where the map holds the button's entry, cleared by *As
        # configured*
        self.assertTrue(self._icon(_WEB, "chips").evaluate(
            "b => b.classList.contains('is-changed')"))
        self.page.click('.ls-band__mode[data-mode="configured"]')
        self.assertFalse(self._icon(_WEB, "chips").evaluate(
            "b => b.classList.contains('is-changed')"))


#: Where the window stands the moment `tree.js` has put the map back on a swap, before
#: anything paints: a scroll that glides has not moved yet.
_AFTER_APPLY = """() => {
    const tree = window.lsTree, apply = tree.apply;
    tree.apply = container => { apply(container); window.__scrolled = window.scrollY; };
}"""


#: Each node the window shows, by its path, and its top in the window.
_TOPS_SHOWN = """() => [...document.querySelectorAll('#status-grid .tree-node')]
    .map(node => [node.dataset.node, node.getBoundingClientRect()])
    .filter(([, box]) => box.height && box.bottom > 0 && box.top < innerHeight)
    .map(([path, box]) => [path, box.top])"""


class RefreshTests(_BrowserCase):
    """Everything stands through a swap and a reload, the focus with it, and through a
    swap what the window shows."""

    def test_what_a_viewer_set_stands_through_a_swap_and_a_reload(self):
        self._wall()
        self._chip(_CDN).click()
        self._head(_DNS).locator(".status-node__state").click()
        self._icon(_NAS, "chips").click()
        self._icon(_WEB, "ok").click()
        held = self._map()
        for again in (self._swap, self._reload):
            again()
            self.assertEqual(self._map(), held)
            self.assertEqual(self._state(_CDN), "open")
            self.assertEqual(self._state(_DNS), "closed")
            self.assertEqual(self._level_items(_WEB),
                             ["run(api)", "node(cdn)", "run(dns)", "node(flaky)",
                              "run(mail)", "node(roster)"])
            self.assertEqual(self._icon(_NAS, "chips").get_attribute("aria-pressed"),
                             "true")
            self.assertFalse(self._node(_MAIL).is_visible())     # folded
            self.assertFalse(self._node(_CDN).is_visible())      # healthy, open or not
            self.assertTrue(self._node(_DNS).is_visible())

    def test_the_focus_goes_back_to_its_face_without_a_scroll(self):
        self._wall()
        self._chip(_CDN).click()
        self.page.set_viewport_size({"width": 1000, "height": 330})
        self.page.evaluate("window.scrollTo(0, 150)")
        self._head(_CDN).locator('[data-control="toggle"]').focus()
        self.page.evaluate("window.scrollTo(0, 150)")
        self._swap()
        self.assertEqual(self.page.evaluate(
            "document.activeElement.closest('.tree-node').dataset.node"), _CDN)
        self.assertEqual(self.page.evaluate(
            "document.activeElement.getAttribute('data-control')"), "toggle")
        self.assertEqual(self.page.evaluate("window.scrollY"), 150)
        # and the chip's focus, on a closed node
        self._head(_CDN).locator(".status-node__state").click()
        self._swap()
        self.assertEqual(self.page.evaluate("document.activeElement.className"),
                         "tree-chip s-ok")

    def test_the_node_at_the_window_top_stands_through_a_swap(self):
        # A wall scrolled down used to move at the next refresh. On a phone's width the
        # cards stand in one column; the window scrolled until the last of them stands
        # at its top, a card above it grows by two lines, and the swap scrolls by what
        # it grew, so that the window shows what it showed — at once, where the page's
        # stylesheet has a scroll glide, as Bootstrap's does for a viewer who has not
        # asked for less motion
        self.page.set_viewport_size({"width": 375, "height": 300})
        self._wall()
        self.page.add_style_tag(content=":root { scroll-behavior: smooth; }")
        self.assertEqual(self._cards()[-1], _WEB)
        self.page.evaluate("by => window.scrollBy({top: by, behavior: 'instant'})",
                           self._top(_WEB))
        scrolled = self.page.evaluate("window.scrollY")
        self.assertGreater(scrolled, 0)
        stood = self._top(_WEB)
        self.page.evaluate(_AFTER_APPLY)
        self.tree.upsert(f"{_NAS}/zeta/probe", StatusCode.ERROR,
                         ["zeta is down", "zeta's disk is full", "zeta's fan stopped"])
        self._swap()
        self.assertAlmostEqual(self._top(_WEB), stood, delta=1)
        now = self.page.evaluate("window.scrollY")
        self.assertGreater(now, scrolled + 20)
        self.assertEqual(self.page.evaluate("window.__scrolled"), now)
        # and lines added beneath the node at the window's top, in the window, move
        # nothing: the nearest node holds the window, not one the lines pushed down
        self.assertLess(self._top(_DNS), 300)
        self.tree.upsert(_DNS, StatusCode.WARN, ["slow", "slower", "slowest"])
        self._swap()
        self.assertAlmostEqual(self._top(_WEB), stood, delta=1)
        self.assertEqual(self.page.evaluate("window.scrollY"), now)

    def test_a_node_folded_away_hands_the_window_to_the_next(self):
        # the node nearest the window's top recovers under its card's healthy fold, as a
        # card above grows: the window goes by the next nearest still shown, the card
        # it stood in
        self.page.set_viewport_size({"width": 375, "height": 300})
        self._wall()
        self._icon(_NAS, "ok").click()
        zeta = f"{_NAS}/zeta"
        self.page.evaluate("by => window.scrollBy({top: by, behavior: 'instant'})",
                           self._top(zeta) - 10)
        tops = sorted(self.page.evaluate(_TOPS_SHOWN), key=lambda it: abs(it[1]))
        self.assertEqual([path for path, _ in tops[:2]], [zeta, _NAS])
        stood = self._top(_NAS)
        self.tree.upsert(f"{zeta}/probe", StatusCode.OK)
        self.tree.upsert(_DEEP_LEAF, StatusCode.ERROR, [_DEEP_LINE, "and the next"])
        self._swap()
        self.assertFalse(self._node(zeta).is_visible())
        self.assertAlmostEqual(self._top(_NAS), stood, delta=1)

    def test_a_window_at_the_page_top_stays_there(self):
        # whatever comes to stand at the head of the wall: a card new before the first
        self.page.set_viewport_size({"width": 375, "height": 700})
        self._wall()
        first = self._cards()[0]
        self.assertLess(self._top(first), 700)
        self.tree.upsert("/alpha/probe", StatusCode.ERROR, ["alpha is down"])
        self._swap()
        self.assertEqual(self._cards()[0], "/alpha")
        self.assertEqual(self.page.evaluate("window.scrollY"), 0)

    def test_a_swap_and_a_click_wake_each_observer_once(self):
        # three scripts watch the grid where the card opens on a pause, a viewer's
        # choice: `inspection_card: off`, the library's look, binds no observer
        self.context.add_cookies([looks(self.base, inspection_card="pause")])
        self.page.add_init_script(_COUNT_OBSERVERS)
        self._wall()
        self.page.evaluate("window.__observers.forEach(o => { o.calls = 0; })")
        self._chip(_CDN).click()
        self.page.wait_for_timeout(50)
        calls = self.page.evaluate("window.__observers.map(o => o.calls)")
        # the three scripts' observers, once each; tree.js's own is disconnected
        # while it moves the nodes, and no other script's watches the grid
        self.assertEqual(sum(calls), 3, calls)
        self.assertTrue(all(count <= 1 for count in calls), calls)
        self.page.evaluate("window.__observers.forEach(o => { o.calls = 0; })")
        self._swap()
        self.page.wait_for_timeout(50)
        calls = self.page.evaluate("window.__observers.map(o => o.calls)")
        self.assertTrue(all(count <= 1 for count in calls), calls)

    def _cards(self) -> list[str]:
        """The wall's cards, by their paths, in the order they stand."""
        return self.page.evaluate(
            "[...document.querySelectorAll('#status-grid .status-card')]"
            ".map(card => card.dataset.node)")

    def _top(self, path: str) -> float:
        """Where the node of ``path`` begins in the window."""
        return self.page.evaluate(
            "path => document.querySelector(`.tree-node[data-node=\"${path}\"]`)"
            ".getBoundingClientRect().top", path)


class IncidentTests(_BrowserCase):
    """A close holds for its node's incident, by the server's clock."""

    def _closed_flaky(self) -> None:
        self._wall()
        self._head(_FLAKY).locator(".status-node__state").click()
        self.assertEqual(self._map()["nodes"], {_FLAKY: {"open": False}})

    def _tick(self, seconds: int) -> None:
        self.server_now += timedelta(seconds=seconds)
        self._swap()

    def test_a_close_gives_way_once_the_node_was_out_of_failure_for_the_hold(self):
        self._closed_flaky()
        self.tree.upsert(_FLAKY, StatusCode.OK)
        self._tick(10)
        held = self._map()["nodes"][_FLAKY]
        self.assertEqual(held, {"open": False,
                                "ok_since": int(self.server_now.timestamp())})
        self._tick(590)                                   # 590 s: not yet
        self.assertNotIn("ok_held", self._map()["nodes"][_FLAKY])
        self._tick(10)                                    # 600 s: held
        self.assertEqual(self._map()["nodes"][_FLAKY]["ok_held"], True)
        self.assertEqual(self._state(_FLAKY), "closed")
        # a new failure: the close gives way, and the node opens as its look and the
        # failure budget say — a chip its card's budget opens
        self.tree.upsert(_FLAKY, StatusCode.ERROR, ["flaky is down again"])
        self._tick(10)
        self.assertEqual(self._state(_FLAKY), "open")
        self.assertEqual(self._why(_FLAKY), "budget")
        self.assertIsNone(self._map())

    def test_a_pin_beneath_does_not_keep_the_node_in_failure(self):
        # out of failure means drawn neither as an error nor as a warning, whatever
        # pins stand beneath it — never *healthy*
        self._closed_flaky()
        self.tree.set_maintenance(_FLAKY, "planned", set_by="pan",
                                  expires_at=_NOON + timedelta(days=1))
        self._tick(10)
        self.assertIn("ok_since", self._map()["nodes"][_FLAKY])

    def test_a_shorter_recovery_is_a_flicker_and_the_count_starts_again(self):
        self._closed_flaky()
        self.tree.upsert(_FLAKY, StatusCode.OK)
        self._tick(10)
        self.tree.upsert(_FLAKY, StatusCode.ERROR, ["flaky is down"])
        self._tick(300)
        self.assertEqual(self._map()["nodes"][_FLAKY], {"open": False})
        self.assertEqual(self._state(_FLAKY), "closed")
        self.tree.upsert(_FLAKY, StatusCode.OK)
        self._tick(10)
        since = self._map()["nodes"][_FLAKY]["ok_since"]
        self.assertEqual(since, int(self.server_now.timestamp()))

    def test_renders_that_skip_the_holds_end_still_count(self):
        # a tab asleep across the hold's end: the next render is what counts
        self._closed_flaky()
        self.tree.upsert(_FLAKY, StatusCode.OK)
        self._tick(10)
        self._tick(3600)
        self.assertEqual(self._map()["nodes"][_FLAKY]["ok_held"], True)
        self.tree.upsert(_FLAKY, StatusCode.ERROR, ["flaky is down"])
        self._tick(10)
        self.assertEqual(self._state(_FLAKY), "open")

    def test_a_tab_that_saw_no_render_out_of_failure_keeps_the_close(self):
        self._closed_flaky()
        self._tick(3600)
        self.assertEqual(self._map()["nodes"][_FLAKY], {"open": False})
        self.assertEqual(self._state(_FLAKY), "closed")

    def test_an_open_never_gives_way_to_a_status(self):
        self._wall()
        self._chip(_CDN).click()
        for code, lines in ((StatusCode.ERROR, ["cdn is down"]), (StatusCode.OK, []),
                            (StatusCode.WARN, ["slow"])):
            self.tree.upsert(_CDN, code, lines)
            self._tick(700)
            self.assertEqual(self._state(_CDN), "open")
            self.assertEqual(self._map()["nodes"], {_CDN: {"open": True}})


class FindTests(_BrowserCase):
    """A find opens what it finds: a fragment that names a line beneath two closed
    nodes is revealed by the steps the browser's find takes."""

    def _deep(self) -> None:
        self._wall(url="/status?depth=2")
        self.assertEqual(self._state(f"{_DEEP}/a"), "closed")
        self.assertEqual(self._state(_DEEP_LEAF), "closed")
        # the lines get ids to be named by
        self.page.evaluate("""() => {
            document.querySelectorAll('.status-node__reason').forEach(line => {
                const text = line.textContent;
                if (text.includes('two closed nodes')) { line.id = 'deep-line'; }
                if (text.includes('another closed node')) { line.id = 'other-line'; }
            });
            window.__matched = [];
            document.getElementById('status-grid').addEventListener('beforematch',
                e => window.__matched.push(e.target.parentElement.dataset.node));
        }""")

    def test_a_fragment_beneath_two_closed_nodes_opens_both(self):
        self._deep()
        items_before = self._level_items(_DEEP)
        self.page.evaluate("location.hash = '#deep-line'")
        self.page.wait_for_function("window.__matched.length === 2")
        self.assertEqual(self.page.evaluate("window.__matched"),
                         [_DEEP_LEAF, f"{_DEEP}/a"])          # the innermost first
        for path in (f"{_DEEP}/a", _DEEP_LEAF):
            self.assertEqual(self._state(path), "open", path)
            self.assertEqual(self._why(path), "entry", path)
        self.assertEqual(self._map()["nodes"],
                         {f"{_DEEP}/a": {"open": True}, _DEEP_LEAF: {"open": True}})
        self.assertEqual(self._band()[1], ("configured", "true", "· 3"))
        self.assertTrue(self.page.locator("#deep-line").is_visible())
        # the level re-formed around the node, the node itself in place
        self.assertEqual(items_before, ["run(a,b)"])
        self.assertEqual(self._level_items(_DEEP), ["solo(a)", "run(b)"])
        # and kept through a swap, where the server's shape is put back
        self._swap()
        self.assertEqual(self._state(_DEEP_LEAF), "open")
        self.assertEqual(self._level_items(_DEEP), ["node(a)", "run(b)"])
        self.assertTrue(self.page.get_by_text(_DEEP_LINE).is_visible())

    def test_a_second_fragment_within_two_seconds_closes_the_first_reveal_again(self):
        self._deep()
        self.page.evaluate("location.hash = '#deep-line'")
        self.page.wait_for_function("window.__matched.length === 2")
        self.page.clock.run_for(500)
        self.page.evaluate("location.hash = '#other-line'")
        self.page.wait_for_function("window.__matched.length === 4")
        self.assertEqual(self._state(f"{_DEEP}/a"), "closed")
        self.assertEqual(self._state(_DEEP_LEAF), "closed")
        self.assertEqual(self._state(f"{_DEEP}/b"), "open")
        self.assertEqual(self._state(_OTHER_LEAF), "open")
        self.assertEqual(self._map()["nodes"],
                         {f"{_DEEP}/b": {"open": True}, _OTHER_LEAF: {"open": True}})
        self.assertEqual(self._band()[1], ("configured", "true", "· 3"))

    def test_two_seconds_apart_both_stand(self):
        self._deep()
        self.page.evaluate("location.hash = '#deep-line'")
        self.page.wait_for_function("window.__matched.length === 2")
        self.page.clock.run_for(2500)
        self.page.evaluate("location.hash = '#other-line'")
        self.page.wait_for_function("window.__matched.length === 4")
        for path in (f"{_DEEP}/a", _DEEP_LEAF, f"{_DEEP}/b", _OTHER_LEAF):
            self.assertEqual(self._state(path), "open", path)

    def test_a_click_between_them_keeps_the_first_at_once(self):
        self._deep()
        self.page.evaluate("location.hash = '#deep-line'")
        self.page.wait_for_function("window.__matched.length === 2")
        self.page.mouse.click(5, 5)
        self.page.evaluate("location.hash = '#other-line'")
        self.page.wait_for_function("window.__matched.length === 4")
        for path in (f"{_DEEP}/a", _DEEP_LEAF, f"{_DEEP}/b", _OTHER_LEAF):
            self.assertEqual(self._state(path), "open", path)

    def test_a_closed_wrapper_keeps_its_display_against_bootstraps_hidden(self):
        self._wall()
        hold = self._hold(_CDN)
        style = ("hold => [getComputedStyle(hold).display, "
                 "getComputedStyle(hold).contentVisibility]")
        self.assertEqual(hold.evaluate(style), ["block", "hidden"])
        self.assertEqual(hold.bounding_box()["height"], 0)
        # a closed node whose box a find could not reach would be out of the find:
        # the wrapper is in the page's layout, its box's name findable by the browser
        self.assertEqual(hold.get_attribute("hidden"), "until-found")


class WhyTests(_BrowserCase):
    """The rule that decided a node's look is written on it."""

    def test_each_rule_names_itself(self):
        self._wall()
        self.assertEqual(self._why(_API), "drawn")              # a chip, configured
        self.assertEqual(self._why(_DNS), "budget")             # a failure's way
        self.assertEqual(self._why(_ROSTER), "swq")             # the claim, configured
        self._chip(_API).click()
        self.assertEqual(self._why(_API), "entry")
        self.page.click('.ls-band__mode[data-mode="closed"]')
        self.assertEqual(self._why(_DNS), "mode")
        self.assertEqual(self._why(_API), "entry")
        self.assertEqual(self._why(_WEB), "kept")               # an open entry beneath
        self.assertEqual(self._why(_ROSTER), "mode")            # the claim gives way
        self.page.click('.ls-band__mode[data-mode="configured"]')
        self._icon(_WEB, "chips").click()
        self.assertEqual(self._why(_API), "parent")
        self.assertEqual(self._why(_DNS), "entry")              # a failure's own close
        self.assertEqual(self._why(_ROSTER), "entry")           # set with its siblings

    def test_a_pages_children_open_by_the_pages_rule(self):
        self._wall(url="/status/web")
        self.assertEqual(self._why(_DNS), "page")
        self.assertEqual(self._why(_ROSTER), "swq")             # a claim comes first
        self.page.click('.ls-band__mode[data-mode="closed"]')
        self.assertEqual(self._why(_DNS), "mode")               # the mode wins over it
        self.assertEqual(self._state(_DNS), "closed")


#: A node page's own lines, each one's text: inside the frame's head.
_PAGE_LINES = ".node-frame .viewed-head .own-lines > .check-reason .check-reason__body"


class PageFrameTests(_BrowserCase):
    """A node's page draws its node in a frame, always open (backlog #91 §3.5): its
    ▤ folds the page's cards and its funnel the healthy ones and its own healthy
    lines, by the node's own entries in the tab's map — the ones its box carries on
    the wall — and a leaf's page, which is not polled, keeps its fold the same way."""

    def _leaf(self, url: str) -> Any:
        """A leaf's own page, which has no grid: its frame is what the script finds."""
        self.page.clock.install(time=_NOON)
        self.page.goto(f"{self.base}{url}")
        self.page.wait_for_selector(".node-frame .viewed-head")
        self.page.clock.pause_at(_NOON + timedelta(seconds=5))
        return self.page

    def _cards_closed(self) -> list[bool]:
        return self.page.evaluate("""() => Array.from(document.querySelectorAll(
            '.node-frame .status-grid > .status-card')).map(card =>
                card.classList.contains('is-closed'))""")

    def _shown(self, selector: str) -> list[str]:
        """What `selector` finds that is not hidden, by its node or its text."""
        return self.page.evaluate("""selector => Array.from(
            document.querySelectorAll(selector)).filter(el => !el.hidden
                && !el.closest('[hidden]')).map(el =>
                    el.dataset.node || el.textContent.trim())""", selector)

    def test_the_pages_node_is_open_whatever_the_tabs_map_holds(self):
        self._wall()
        self._head(_WEB).locator(".status-card__state").click()     # closed on the wall
        self.assertEqual(self._map()["nodes"], {_WEB: {"open": False}})
        self._wall("/status/web")
        frame = self._node(_WEB)
        self.assertEqual((self._state(_WEB), self._why(_WEB)), ("open", "page"))
        # and a failing node's close keeps its incident: the frame says it fails
        self.assertEqual(self._map()["nodes"], {_WEB: {"open": False}})
        self.assertTrue(frame.evaluate("node => node.hasAttribute('data-page-root')"))
        # its head is no toggle: a click on its name or its state closes nothing
        self._head(_WEB).locator(".status-node__name").click()
        self._head(_WEB).locator(".status-node__state").click()
        self.assertEqual(self._state(_WEB), "open")
        self.assertEqual(self._map()["nodes"], {_WEB: {"open": False}})
        self.assertFalse(self._head(_WEB).locator(".status-node__name").evaluate(
            "name => name.hasAttribute('role') || name.matches('a')"))

    def test_a_click_on_the_pages_own_head_writes_nothing_for_the_wall(self):
        # with the tab's map empty: on any other head the click closes the node,
        # an entry the page's rule would outweigh here and the wall would obey
        self._wall("/status/web")
        self._head(_WEB).locator(".status-node__state").click()
        self._head(_WEB).locator(".status-node__name").click()
        self.assertEqual(self._state(_WEB), "open")
        self.assertIsNone(self._map())
        self._wall()
        self.assertEqual(self._state(_WEB), "open")

    def test_its_chips_fold_the_pages_cards_and_the_wall_follows(self):
        self._wall("/status/web")
        chips = self._icon(_WEB, "chips")
        self.assertEqual(chips.get_attribute("aria-pressed"), "false")
        self.assertEqual(self._cards_closed(), [False] * 6)
        self.assertEqual(self._why(_DNS), "page")
        chips.click()
        self.assertEqual(chips.get_attribute("aria-pressed"), "true")
        self.assertEqual(self._cards_closed(), [True] * 6)
        # the node's own entry; the roster's, whose claim would keep it open; and the
        # warning's and the failure's, which the wall's failure budget would open
        self.assertEqual(self._map()["nodes"], {_WEB: {"chips": True},
                                                _DNS: {"open": False},
                                                _FLAKY: {"open": False},
                                                _ROSTER: {"open": False}})
        self.assertEqual(self._why(_API), "parent")
        self.assertEqual(self._why(_DNS), "entry")
        # through a swap and a reload
        self._swap()
        self.assertEqual(self._cards_closed(), [True] * 6)
        self._reload()
        self.assertEqual(self._cards_closed(), [True] * 6)
        # one state for the tab: on the wall the same node's children are chips, the
        # warning and the failure among them
        self._wall()
        for path in (_DNS, _FLAKY):
            self.assertEqual((self._state(path), self._why(path)), ("closed", "entry"))
        self.assertEqual(self._icon(_WEB, "chips").get_attribute("aria-pressed"),
                         "true")
        # and back on the page, pressed: a click opens every card again
        self._wall("/status/web")
        self._icon(_WEB, "chips").click()
        self.assertEqual(self._cards_closed(), [False] * 6)
        self.assertIsNone(self._map())                       # nothing differs
        # one card closed by a click leaves ▤ half pressed
        self._head(_CDN).locator(".status-card__state").click()
        self.assertEqual(self._icon(_WEB, "chips").get_attribute("aria-pressed"),
                         "mixed")

    def test_its_funnel_folds_the_healthy_cards_and_its_own_healthy_lines(self):
        self.tree.upsert(_WEB, StatusCode.WARN, [
            Entry("tier", "the tier answers", StatusCode.OK),
            Entry("region", "one region is slow", StatusCode.WARN)], members=True)
        self._wall("/status/web")
        funnel = self._icon(_WEB, "ok")
        self.assertEqual(funnel.get_attribute("aria-pressed"), "false")
        # api, cdn and mail, the roster, which claims its quiet, and its own line
        self.assertEqual(funnel.get_attribute("data-n-pressed"), "5")
        cards = ".node-frame .status-grid > .status-card"
        lines = _PAGE_LINES
        self.assertEqual(len(self._shown(cards)), 6)
        funnel.click()
        self.assertEqual(funnel.get_attribute("aria-pressed"), "true")
        self.assertEqual(self._shown(cards), [_DNS, _FLAKY])
        self.assertEqual(self._shown(lines), ["one region is slow"])
        mark = self._node(_WEB).locator(":scope > .tree-hold > .tree-box > .tree-ok")
        self.assertEqual(mark.text_content(), "✓ +5 ok")
        self.assertFalse(mark.evaluate("mark => mark.hidden"))
        self.assertEqual(self._map()["nodes"], {_WEB: {"ok": True}})
        self.page.reload()                 # the first card is folded: no wait on it
        self.page.wait_for_selector(".node-frame .viewed-head")
        self.assertEqual(self._shown(cards), [_DNS, _FLAKY])
        self.assertEqual(self._shown(lines), ["one region is slow"])
        # the mark after the cards shows them all again
        mark.click()
        self.assertEqual(len(self._shown(cards)), 6)
        self.assertEqual(len(self._shown(lines)), 2)

    def test_a_leafs_page_keeps_its_fold_and_the_wall_follows(self):
        page = self._leaf("/status/web/api")
        self.assertEqual(page.locator("#status-grid").count(), 0)
        self.assertEqual((self._state(_API), self._why(_API)), ("open", "page"))
        funnel = self._icon(_API, "ok")
        lines = _PAGE_LINES
        self.assertEqual(self._shown(lines), ["200 in 40 ms", "certificate fine"])
        funnel.click()
        self.assertEqual(self._shown(lines), [])
        self.assertEqual(self._map()["nodes"], {_API: {"ok": True}})
        page.reload()
        page.wait_for_selector(".node-frame .viewed-head")
        self.assertEqual(self._shown(lines), [])
        self.assertFalse(page.evaluate(
            "document.documentElement.classList.contains('ls-tree-pending')"))
        # on the wall the leaf's box folds its lines by the same entry
        self._wall()
        self._chip(_API).click()
        self.assertEqual(self._shown(f'.tree-node[data-node="{_API}"] .reason-block > '
                                     '.status-node__reason'), [])

    def test_the_frames_head_is_one_toolbar_with_its_stop(self):
        self._wall("/status/web")
        stops = self._head(_WEB).evaluate("""row => Array.from(row.querySelectorAll(
            '.node-controls a, .node-controls button')).filter(c => !c.hidden)
            .map(c => [c.dataset.control || c.textContent.trim(), c.tabIndex])""")
        # ‖ and ✓ among them for an admin, once the script shows the buttons that
        # open the editors the head keeps — ✓ where something fails, as here
        self.assertEqual(stops, [["ok", 0], ["chips", -1], ["pin", -1], ["ack", -1]])


#: What a page draws of what `tree.js` shows: the band's meta and its three buttons,
#: and on a node's page the setter beneath its head, the head's ‖ and the head's box —
#: each its box in whole pixels, or None where it is not drawn.
_FIRST_PAINT = """() => {
    const box = el => {
      if (!el || !el.getClientRects().length) { return null; }
      const r = el.getBoundingClientRect();
      return [r.x, r.y, r.width, r.height].map(Math.round);
    };
    return {
      meta: box(document.querySelector('.ls-band__meta')),
      modes: box(document.querySelector('.ls-band__modes')),
      setter: box(document.querySelector('.viewed-head > .rule-setter')),
      pin: box(document.querySelector(
          '.viewed-head .node-icons > [data-control="pin"]')),
      head: box(document.querySelector('.viewed-head')),
    };
}"""


class FirstPaintTests(_BrowserCase):
    """What `tree.js` shows stands from the first paint, so the page does not move
    when it runs: `tree-pending.js`, in the head, puts `ls-script` on <html>, under
    which the band's three buttons take their room and a node's page carries ‖ in its
    head's row where *Set maintenance* would stand beneath it — read here with
    `tree.js` held back, as a page stands before it runs. Without script neither is
    drawn: no buttons, and the setter beneath the head."""

    def _drawn(self, url: str, held: bool = False,
               script: bool = True) -> dict[str, Any]:
        context = self.browser.new_context(**self.drawn_in,
                                           java_script_enabled=script)
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        page = self._signed_in(context)
        if held:
            context.route("**/static/js/tree.js*", lambda route: route.abort())
        page.goto(f"{self.base}{url}")
        page.wait_for_selector("#status-grid .status-card")
        drawn: dict[str, Any] = page.evaluate(_FIRST_PAINT)
        return drawn

    def test_the_bands_buttons_take_their_room_before_the_script_runs(self):
        held = self._drawn("/status", held=True)
        drawn = self._drawn("/status")
        self.assertIsNotNone(held["modes"])
        self.assertEqual(held["modes"], drawn["modes"])
        self.assertEqual(held["meta"], drawn["meta"])

    def test_a_pages_head_carries_its_pin_mark_before_the_script_runs(self):
        held = self._drawn("/status/web", held=True)
        drawn = self._drawn("/status/web")
        self.assertIsNone(held["setter"])
        self.assertIsNotNone(held["pin"])
        self.assertEqual(held["pin"], drawn["pin"])
        self.assertEqual(held["head"], drawn["head"])

    def test_without_script_neither_is_drawn(self):
        bare = self._drawn("/status/web", script=False)
        self.assertIsNone(bare["modes"])
        self.assertIsNone(bare["pin"])
        self.assertIsNotNone(bare["setter"])

    # --- a fold the configuration sets (ADR-0128) ---

    def _folded(self, held: bool = False, script: bool = True) -> dict[str, Any]:
        """The web card as the page stands: which of its children show, its *✓ +N
        ok* and where the card is, with `/web`'s fold configured on."""
        app_module.first_looks = FirstLooks(
            (), {_WEB: NodeMeta(look=Stated(chips=False, fold_ok=True))},
            app_module.config, self.tree.named_by_run)
        self.addCleanup(setattr, app_module, "first_looks", None)
        context = self.browser.new_context(**self.drawn_in, java_script_enabled=script)
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        page = self._signed_in(context)
        if held:
            context.route("**/static/js/tree.js*", lambda route: route.abort())
        page.goto(f"{self.base}/status")
        page.wait_for_selector("#status-grid .status-card")
        drawn: dict[str, Any] = page.evaluate("""() => {
            const box = el => {
              if (!el || !el.getClientRects().length) { return null; }
              const r = el.getBoundingClientRect();
              return [r.x, r.y, r.width, r.height].map(Math.round);
            };
            const web = document.querySelector('.tree-node[data-node="/web"]');
            const mark = web.querySelector(':scope > .tree-hold > .tree-ok');
            const shown = {};
            for (const kid of web.querySelectorAll('.tree-kids > .tree-node')) {
              shown[kid.dataset.node.split('/').pop()] = box(kid) !== null;
            }
            return {shown: shown, mark: box(mark),
                    words: mark && box(mark) ? mark.textContent : null,
                    card: box(web)};
        }""")
        return drawn

    def test_a_configured_fold_stands_before_the_script_runs(self):
        held = self._folded(held=True)
        drawn = self._folded()
        # the healthy ones folded, the roster's claim and the failures standing
        self.assertEqual(held["shown"], {"api": False, "cdn": False, "dns": True,
                                         "flaky": True, "mail": False, "roster": True})
        self.assertEqual(held["words"], "\u2713 +3 ok")
        # and the script draws it just so: nothing moves when it runs
        self.assertEqual(held, drawn)

    def test_once_the_script_runs_the_fold_is_the_viewers_to_press(self):
        self._folded()
        context = self.browser.new_context(**self.drawn_in)
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        page = self._wall(page=self._signed_in(context))
        funnel = self._icon(_WEB, "ok", page)
        self.assertEqual(funnel.get_attribute("aria-pressed"), "true")
        funnel.click()
        for name in ("api", "cdn", "mail"):
            self.assertTrue(self._node(f"{_WEB}/{name}", page).is_visible(), name)
        self.assertEqual(self._map(page)["nodes"], {_WEB: {"ok": False}})

    def test_without_script_a_configured_fold_folds_nothing(self):
        bare = self._folded(script=False)
        self.assertTrue(all(bare["shown"].values()), bare["shown"])
        self.assertIsNone(bare["mark"])


class PricedLookTests(_BrowserCase):
    """The planner prices the configured look (ADR-0128 decision 6): a level its node
    closes is a run of chips to the planner as to the page, so a click that opens one
    of them, and a failure the failure budget opens at a refresh, move no card."""

    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1400, "height": 800}, "reduced_motion": "reduce"}

    def setUp(self) -> None:
        super().setUp()
        app_module.first_looks = FirstLooks(
            (), {_NAS: NodeMeta(look=Stated(chips=True)),
                 _WEB: NodeMeta(look=Stated(chips=True))},
            app_module.config, self.tree.named_by_run)
        self.addCleanup(setattr, app_module, "first_looks", None)

    def _cards(self) -> list[tuple[float, float]]:
        return [(box["x"], box["width"]) for box in
                (card.bounding_box() for card in
                 self.page.locator(".status-grid > .status-card").all())]

    def _plan(self) -> str | None:
        return self.page.locator(".status-grid").get_attribute(
            "data-layout-breakpoints")

    def test_a_click_and_the_budget_move_no_card(self):
        self._wall()
        self.assertEqual(self._state(f"{_NAS}/alpha"), "closed")
        self.assertEqual(self._why(f"{_NAS}/zeta"), "budget")    # the failure's way
        self.assertEqual(self._why(_FLAKY), "budget")
        self.assertEqual(self._why(_MAIL), "drawn")
        plan, before = self._plan(), self._cards()
        self.assertGreater(len({x for x, _width in before}), 1)  # cards side by side
        self._chip(f"{_NAS}/alpha").click()
        self.assertEqual(self._state(f"{_NAS}/alpha"), "open")
        self.assertEqual(self._cards(), before)
        # a failure under a chip, which the next refresh opens: no card moves
        self.tree.upsert(_MAIL, StatusCode.ERROR, ["mail is down"])
        self._swap()
        self.assertEqual(self._why(_MAIL), "budget")
        self.assertEqual(self._plan(), plan)
        self.assertEqual(self._cards(), before)


#: A deployment's actions, as the head's row draws them (decision 3): three labels,
#: offered on every node. A box on a desk has room for all three, and a phone's card
#: for one; the tests narrow a card to the overflow they need, its row read first.
_ACTIONS = (
    Action("File", "https://tracker.example.org/new?n={path}", "node.actions"),
    Action("Mute", "https://tracker.example.org/mute?n={path}", "node.actions"),
    Action("Escalate", "https://tracker.example.org/up?n={path}", "node.actions"),
)
#: A name a card on a desk holds on one line, but not beside its state; and one a
#: phone's card holds so.
_LONG_NAME = "/backup_of_the_primary_cluster"
_PHONE_NAME = "/backup_of_cluster"
#: A box's name that breaks at its hyphen, its last line short.
_QUEUE = "/web/collect-queue"


class _HeadRowCase(_BrowserCase):
    """A wall where every node carries the three actions."""

    #: Where the heads keep their buttons, the look `head_buttons` (ADR-0029): right
    #: after the name, the library's, where the row's reading is tested; a line
    #: beneath and the row's end have classes of their own.
    look: ClassVar[str] = "pointer"

    def setUp(self) -> None:
        super().setUp()
        configured = mock.patch.object(actions_module, "_actions", _ACTIONS)
        configured.start()
        self.addCleanup(configured.stop)
        self._choose()

    def _choose(self, **chosen: str) -> None:
        """The presentation cookie, choosing this class's `head_buttons` and the
        ``chosen`` looks beside it."""
        self.context.add_cookies([looks(self.base, head_buttons=self.look, **chosen)])

    def _parts(self, path: str) -> dict[str, Any]:
        """The head's row of ``path`` as drawn: each part's box — ↗'s and the
        toolbar's among them — the actions folded, ⋯ shown, the state's line and the
        room the head was given for it."""
        return self._head(path).evaluate("""head => {
            const box = el => {
              if (!el) { return null; }
              const r = el.getBoundingClientRect();
              return {x: r.x, y: r.y, right: r.right, bottom: r.bottom,
                      width: r.width, height: r.height};
            };
            const name = head.querySelector('[data-control="toggle"]');
            const actions = Array.from(head.querySelectorAll('.node-actions > *'));
            const lineHeight = parseFloat(getComputedStyle(name).lineHeight) || 24;
            return {
              head: box(head), name: box(name),
              nameLines: Math.round(name.getBoundingClientRect().height / lineHeight),
              title: box(head.querySelector('.node-title')),
              titleCut: (() => { const t = head.querySelector('.node-title');
                                 return !!t && t.scrollWidth > t.clientWidth + 1; })(),
              actions: actions.map(box),
              shown: actions.filter(a => !a.classList.contains('is-folded')).length,
              folded: actions.filter(a => a.classList.contains('is-folded')).length,
              foldedWidth: actions.filter(a => a.classList.contains('is-folded'))
                  .reduce((sum, a) => sum + a.getBoundingClientRect().width, 0),
              more: box(head.querySelector('.node-more:not([hidden])')),
              state: box(head.querySelector(
                  ':scope > .status-card__state, :scope > .status-node__state')),
              icons: box(head.querySelector('.node-icons')),
              page: box(head.querySelector('.node-icons > [data-control="page"]')),
              toolbar: box(head.querySelector(':scope > .node-controls')),
              cue: box(head.querySelector(':scope > .status-cue')),
              below: head.classList.contains('is-state-below'),
              beside: head.classList.contains('is-state-beside'),
              room: head.style.getPropertyValue('--ls-state-room'),
              opacity: actions.length
                  ? getComputedStyle(actions[0]).opacity : null,
            };
        }""")

    def _as_read(self, path: str) -> dict[str, float]:
        """The row of ``path`` as `tree.js` reads it — the title gone, every action
        and ⋯ shown, the state in the row: what its parts need, what the row has
        inside its padding, the actions' widths and their sum, the toolbar's gap,
        and the widths of ⋯ and of the state."""
        return self._head(path).evaluate("""head => {
            head.classList.add('is-measuring');
            const below = head.classList.contains('is-state-below');
            head.classList.remove('is-state-below');
            let need = 0;
            for (const kid of head.children) {
              const style = getComputedStyle(kid);
              if (style.display === 'none' || style.position === 'absolute') {
                continue;
              }
              need += kid.getBoundingClientRect().width
                    + parseFloat(style.marginLeft) + parseFloat(style.marginRight);
            }
            const own = getComputedStyle(head);
            const inside = head.getBoundingClientRect().width
                - parseFloat(own.paddingLeft) - parseFloat(own.paddingRight);
            const widths = Array.from(head.querySelectorAll('.node-actions > *'),
                                      a => a.getBoundingClientRect().width);
            const gap = parseFloat(
                getComputedStyle(head.querySelector('.node-controls')).columnGap);
            const width = el => el ? el.getBoundingClientRect().width : 0;
            const more = width(head.querySelector('.node-controls > .node-more'));
            const state = width(head.querySelector(
                ':scope > .status-card__state, :scope > .status-node__state'));
            head.classList.remove('is-measuring');
            head.classList.toggle('is-state-below', below);
            return {need, inside, gap, actions: widths.reduce((a, b) => a + b, 0),
                    count: widths.length, widths, more, state};
        }""")

    def _overflowing(self, path: str, excess: float) -> dict[str, Any]:
        """Draw the card of ``path`` so that its row, read with every action and ⋯
        in it and the state in the row, overflows by ``excess`` pixels; what it
        was read as at 700 pixels."""
        self._narrow(path, 700)
        wide = self._as_read(path)
        self._narrow(path, 700 - wide["inside"] + wide["need"] - excess)
        return wide

    def _narrow(self, path: str, width: float) -> None:
        """Draw the card of ``path`` ``width`` pixels wide — the grid's width, which
        the page watches, stays — and have the page apply the map again, which
        measures every head as a swap does."""
        self._node(path).evaluate(
            "(card, width) => { card.style.width = width + 'px';"
            " card.style.minWidth = '0'; card.style.justifySelf = 'start'; }", width)
        self.page.evaluate(
            "window.lsTree.apply(document.getElementById('status-grid'))")

    @staticmethod
    def _on_one_line(parts: dict[str, Any], *names: str) -> bool:
        tops = [round(parts[name]["y"]) for name in names if parts[name]]
        return max(tops) - min(tops) <= 2

    def _focused(self) -> str:
        return self.page.evaluate("""() => {
            const el = document.activeElement;
            return el.getAttribute('data-control') || el.textContent.trim()
                || el.className;
        }""")

    def _resized_to(self, width: int) -> None:
        """The window ``width`` wide, and the frame drawn in which the grid's
        observer reports it. The page's clock is paused, and a busy machine can
        draw that frame only after the clock's next step, which then finds no
        timer of the page's to fire: an observer of the test's own, made after
        the page's and so told after it in the same frame, says when it is."""
        page = self.page
        page.evaluate("""() => new Promise(resolve => {
            window.__gridSeen = 0;
            new ResizeObserver(() => { window.__gridSeen += 1; resolve(); })
                .observe(document.getElementById('status-grid'));
        })""")
        seen = page.evaluate("window.__gridSeen")
        page.set_viewport_size({"width": width, "height": 700})
        for _ in range(250):
            if page.evaluate("window.__gridSeen") > seen:
                return
            page.wait_for_timeout(20)
        self.fail(f"the grid's observer never reported a width of {width}")

    def _look(self, path: str) -> dict[str, Any]:
        """The head of ``path`` as the stylesheet paints it now: its outline, its
        fill, the ring around the fill and the ring's colour, its ink and its
        cursor — each colour as ``[r, g, b, alpha]``, 0 to 255 and 0 to 1."""
        return self._head(path).evaluate("""head => {
            const rgba = value => {
              const n = (value.match(/-?[\\d.]+(e-?\\d+)?/g) || []).map(Number);
              const scale = value.startsWith('color(') ? 255 : 1;
              return [n[0] * scale, n[1] * scale, n[2] * scale,
                      n.length > 3 ? n[3] : 1];
            };
            const s = getComputedStyle(head);
            return {outline: s.outlineStyle, width: s.outlineWidth,
                    offset: s.outlineOffset, line: rgba(s.outlineColor),
                    fill: rgba(s.backgroundColor), ring: s.boxShadow,
                    ringInk: s.boxShadow === 'none' ? [0, 0, 0, 0]
                                                    : rgba(s.boxShadow),
                    ink: rgba(s.color), cursor: s.cursor};
        }""")

    def _point_at(self, part: Any, end: bool = False) -> None:
        """The pointer to the middle of ``part`` — to its far end where ``end``, for
        a title: under the pointer the toolbar lies over the title's start. A part in
        the window but under the page's sticky bar is brought clear of it first."""
        part.scroll_into_view_if_needed()
        part.evaluate("""part => {
            const bar = document.querySelector('.ls-bar');
            if (bar && part.getBoundingClientRect().top
                    < bar.getBoundingClientRect().bottom) {
                part.scrollIntoView({block: 'center'});
            }
        }""")
        box = part.bounding_box()
        x = box["x"] + box["width"] - 3 if end else box["x"] + box["width"] / 2
        self.page.mouse.move(x, box["y"] + box["height"] / 2)

    def _chip_look(self, path: str) -> dict[str, Any]:
        """The chip of ``path`` as the stylesheet paints it now: its outline, its
        tint, the wash laid over the tint (the first colour of its
        `background-image`), its ink, and whether it and its name underline."""
        return self._chip(path).evaluate("""chip => {
            const rgba = value => {
              const n = (value.match(/-?[\\d.]+(e-?\\d+)?/g) || []).map(Number);
              if (n.length < 3) { return [0, 0, 0, 0]; }
              const scale = value.indexOf('color(') >= 0 ? 255 : 1;
              return [n[0] * scale, n[1] * scale, n[2] * scale,
                      n.length > 3 ? n[3] : 1];
            };
            const s = getComputedStyle(chip);
            const name = chip.querySelector('.tree-chip__name');
            return {outline: s.outlineStyle, width: s.outlineWidth,
                    offset: s.outlineOffset, line: rgba(s.outlineColor),
                    fill: s.backgroundColor,
                    wash: s.backgroundImage === 'none' ? [0, 0, 0, 0]
                                                       : rgba(s.backgroundImage),
                    ink: rgba(s.color), decoration: s.textDecorationLine,
                    nameDecoration: getComputedStyle(name).textDecorationLine};
        }""")

    def _chip_pressed(self, path: str) -> dict[str, Any]:
        """The look of the chip of ``path`` while the button is held on it — let go
        away from the wall, so nothing opens."""
        self._point_at(self._chip(path))
        self.page.mouse.down()
        look = self._chip_look(path)
        self.page.mouse.move(2, 2)
        self.page.mouse.up()
        return look

    def _pressed(self, part: Any, end: bool = False) -> dict[str, Any]:
        """The look of the head ``part`` stands in while the button is held on it —
        let go away from the wall, so nothing toggles."""
        self._point_at(part, end)
        self.page.mouse.down()
        path = part.evaluate("p => p.closest('[data-path]').dataset.path")
        look = self._look(path)
        self.page.mouse.move(2, 2)
        self.page.mouse.up()
        return look

    def _breaking(self, path: str, card: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Narrow ``card`` until the head of ``path`` has its state beneath with its
        name on one line, and on until the name breaks in two: the head drawn at
        each of the two."""
        one_line = two_lines = None
        for width in range(440, 196, -4):
            self._narrow(card, width)
            parts = self._parts(path)
            if parts["below"] and parts["nameLines"] == 1 and one_line is None:
                one_line = parts
            if parts["below"] and parts["nameLines"] == 2:
                two_lines = parts
                break
        self.assertIsNotNone(one_line, "no width drops the state with the name whole")
        self.assertIsNotNone(two_lines, "no width breaks the name in two")
        assert one_line is not None and two_lines is not None
        return one_line, two_lines


class HeadRowTests(_HeadRowCase):
    """The head's row on a desk."""

    def test_the_buttons_follow_the_name_and_the_state_ends_the_row(self):
        # the look `head_buttons: pointer`, the library's (ADR-0029): right after the
        # name the head's icons, ↗ the first of them — on every head the button that
        # opens the node's page is the first after its name — then the node's actions,
        # the title after them, and the state at the row's end; a card's as a box's
        self._wall()
        self.page.mouse.move(2, 2)
        for path in (_DNS, _WEB):
            parts = self._parts(path)
            with self.subTest(path=path):
                self.assertAlmostEqual(parts["page"]["x"], parts["name"]["right"],
                                       delta=8)
                self.assertAlmostEqual(parts["page"]["x"], parts["toolbar"]["x"],
                                       delta=0.5)
                self.assertLess(parts["page"]["right"], parts["icons"]["right"])
                self.assertLess(parts["icons"]["right"], parts["actions"][0]["x"])
                self.assertTrue(self._on_one_line(parts, "name", "icons", "state"))
        parts = self._parts(_DNS)                  # a box with room for all three
        self.assertEqual((parts["shown"], parts["folded"], parts["more"]),
                         (3, 0, None))
        self.assertLess(parts["actions"][-1]["right"], parts["state"]["x"])
        self.assertAlmostEqual(parts["state"]["right"], parts["head"]["right"],
                               delta=3)
        self.assertFalse(parts["below"])
        self.assertEqual(parts["nameLines"], 1)
        # the toolbar takes no room in the row: the title stands right after the
        # name, under where the buttons show, and gives way first, with an
        # ellipsis, before the state
        web = self._parts(_WEB)
        self.assertTrue(web["title"])
        self.assertEqual(web["toolbar"]["width"], 0)
        self.assertLess(web["title"]["x"] - web["name"]["right"], 16)
        self.assertLessEqual(web["title"]["right"], web["state"]["x"] + 1)
        self.assertEqual(web["nameLines"], 1)
        # the state clear of the room the title may fill, by 0.4em
        middle = self._head(_WEB).locator(
            ":scope > .status-head__middle").bounding_box()
        self.assertGreaterEqual(
            web["state"]["x"] - (middle["x"] + middle["width"]), 5)

    def test_a_head_without_icons_starts_its_toolbar_with_its_first_action(self):
        # a leaf's own page has no ↗ in its head, being that page, and a leaf with a
        # pin of its own no ‖: with no funnel and no ▤ either, its toolbar keeps no
        # room for icons it has none of
        self.tree.set_maintenance(_FLAKY, "planned", set_by="pan",
                                  expires_at=_NOON + timedelta(days=1))
        self.page.goto(f"{self.base}/status{_FLAKY}")      # a leaf's page has no grid
        self.page.wait_for_selector(".node-frame .viewed-head")
        head = self.page.locator(".node-frame .viewed-head > .status-node__self")
        icons = head.locator(".node-icons")
        self.assertEqual(icons.evaluate("el => el.children.length"), 0)
        toolbar = head.locator(":scope > .node-controls").bounding_box()
        first = head.locator(".node-actions > *").first.bounding_box()
        self.assertAlmostEqual(first["x"], toolbar["x"], delta=0.5)

    def test_what_the_row_has_no_room_for_folds_behind_the_menu(self):
        self._wall()
        page = self.page
        # over by more than the last action gives back and less than the last two
        # do, the script's slack of two pixels among it
        self._narrow(_WEB, 700)
        wide = self._as_read(_WEB)
        last, before = wide["widths"][-1], wide["widths"][-2]
        self._overflowing(_WEB, last + wide["gap"] + (before + wide["gap"]) / 2 - 2)
        parts = self._parts(_WEB)
        self.assertEqual(parts["folded"], 2)
        # some actions behind ⋯, the name whole, ⋯ ending the toolbar
        self.assertGreater(parts["folded"], 0)
        self.assertGreater(parts["shown"], 0)
        self.assertEqual(parts["foldedWidth"], 0)        # folded takes no room
        self.assertIsNotNone(parts["more"])
        self.assertEqual(parts["nameLines"], 1)
        self.assertTrue(self._on_one_line(parts, "name", "more", "icons", "state"))
        self.assertAlmostEqual(parts["state"]["right"], parts["head"]["right"],
                               delta=3)
        self.assertFalse(parts["below"])
        self.assertLess(parts["actions"][0]["right"], parts["more"]["x"])
        # the menu lists the folded ones by their labels, beneath the row
        more = self._head(_WEB).locator(".node-more")
        self.assertEqual(more.get_attribute("aria-haspopup"), "menu")
        more.click()
        menu = self._head(_WEB).locator(".node-actions-menu")
        self.assertEqual(menu.get_attribute("role"), "menu")
        labels = [item.strip()
                  for item in menu.locator('[role="menuitem"]').all_inner_texts()]
        self.assertEqual(labels,
                         [action.label for action in _ACTIONS][-parts["folded"]:])
        self.assertEqual(more.get_attribute("aria-expanded"), "true")
        head = self._head(_WEB).bounding_box()
        self.assertGreaterEqual(menu.bounding_box()["y"],
                                head["y"] + head["height"] - 1)
        self.assertEqual(self._focused(), labels[0])
        page.keyboard.press("Escape")
        self.assertEqual(menu.count(), 0)
        self.assertEqual(self._focused(), "actions-more")
        self.assertEqual(more.get_attribute("aria-expanded"), "false")
        # a click elsewhere closes it too
        more.click()
        self.assertEqual(menu.count(), 1)
        self._head(_NAS).locator(".status-card__name").click()
        self.assertEqual(menu.count(), 0)

    def test_a_row_that_fits_once_the_menu_is_gone_folds_nothing(self):
        # the row is read with ⋯ in it, and ⋯ stands only where an action folds
        # behind it: a row whose overflow ⋯'s square and its gap would give back
        # keeps every action in it, and ⋯ is not shown
        self._wall()
        self._narrow(_WEB, 700)
        wide = self._as_read(_WEB)
        spare = wide["more"] + wide["gap"]
        self.assertGreater(spare, 20)
        self._narrow(_WEB, 700 - wide["inside"] + wide["need"] - spare / 2)
        read = self._as_read(_WEB)
        self.assertGreater(read["need"] - read["inside"], 0)      # with ⋯ it overflows
        self.assertLess(read["need"] - read["inside"], spare - 2)  # without, it fits
        parts = self._parts(_WEB)
        self.assertEqual(parts["folded"], 0)
        self.assertIsNone(parts["more"])
        self.assertFalse(parts["below"])
        self.assertEqual(parts["nameLines"], 1)
        self.assertTrue(self._on_one_line(parts, "name", "state", "icons"))
        self.assertLessEqual(parts["actions"][-1]["right"], parts["state"]["x"])
        # and so does one over by just short of ⋯'s square and its gap, the
        # script's slack among it
        self._overflowing(_WEB, spare - 3.5)
        parts = self._parts(_WEB)
        self.assertEqual(parts["folded"], 0)
        self.assertFalse(parts["below"])
        self.assertTrue(self._on_one_line(parts, "name", "state", "icons"))

    def test_a_lone_action_keeps_its_place_and_the_state_goes_beneath(self):
        # over by more than ⋯ gives back, so that the last action would fold
        # behind it alone: the state takes its line beneath instead, its room the
        # action's, and ⋯ holds nothing
        self._wall()
        self._narrow(_WEB, 700)
        wide = self._as_read(_WEB)
        spare = wide["more"] + wide["gap"]
        # one action's fold is enough, and so is the state's line without ⋯
        self.assertGreater(wide["widths"][-1] + wide["gap"], spare + 10)
        self.assertGreater(wide["state"] + wide["gap"], 10)
        self._overflowing(_WEB, spare + 6)
        parts = self._parts(_WEB)
        self.assertTrue(parts["below"])
        self.assertEqual(parts["folded"], 0)
        self.assertEqual(parts["shown"], 3)
        self.assertIsNone(parts["more"])
        self.assertEqual(parts["nameLines"], 1)
        self.assertTrue(self._on_one_line(parts, "name", "icons"))
        self.assertGreaterEqual(parts["state"]["y"], parts["icons"]["bottom"] - 1)
        self.assertAlmostEqual(parts["state"]["right"], parts["head"]["right"],
                               delta=3)
        # and two that would fold leave the state in the row, behind ⋯ together,
        # even where its line would make room for both: over by more than the last
        # action gives back and no more than the state's line and ⋯'s room do
        low = wide["widths"][-1] + wide["gap"]
        high = min(low + wide["widths"][-2] + wide["gap"], spare + wide["state"]
                   + wide["gap"])
        self.assertGreater(high - low, 4)
        self._overflowing(_WEB, (low + high) / 2 - 2)
        parts = self._parts(_WEB)
        self.assertFalse(parts["below"])
        self.assertEqual(parts["folded"], 2)
        self.assertIsNotNone(parts["more"])
        self.assertTrue(self._on_one_line(parts, "name", "more", "state", "icons"))

    def test_a_lone_action_the_states_line_makes_no_room_for_folds_alone(self):
        # a last action so wide that the state's line would not keep it in the row:
        # it folds behind ⋯ alone, and the state keeps its place in the row, the
        # head one line
        wide_last = (*_ACTIONS[:2], Action(
            "Escalate to the team on call this week",
            "https://tracker.example.org/up?n={path}", "node.actions"))
        configured = mock.patch.object(actions_module, "_actions", wide_last)
        configured.start()
        self.addCleanup(configured.stop)
        self._wall()
        self._narrow(_WEB, 700)
        wide = self._as_read(_WEB)
        spare = wide["more"] + wide["gap"]
        last = wide["widths"][-1] + wide["gap"]
        beneath = spare + wide["state"] + wide["gap"]
        self.assertGreater(last, beneath + 10)
        # over by more than the state's line gives back with ⋯'s room, and less
        # than the last action does
        self._overflowing(_WEB, (beneath + last) / 2 - 2)
        parts = self._parts(_WEB)
        self.assertFalse(parts["below"])
        self.assertEqual(parts["folded"], 1)
        self.assertIsNotNone(parts["more"])
        self.assertEqual(parts["nameLines"], 1)
        self.assertTrue(self._on_one_line(parts, "name", "more", "state", "icons"))

    def test_a_row_the_state_beneath_makes_room_in_keeps_its_lone_action(self):
        # not even its one action folded leaves the name whole, so the state goes
        # beneath and gives the row its room back; what the row then overflows by
        # with ⋯ in it ⋯'s square gives back, so the action stays and ⋯ is not shown
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        lone = mock.patch.object(actions_module, "_actions", _ACTIONS[:1])
        lone.start()
        self.addCleanup(lone.stop)
        self._wall()
        self._narrow(_LONG_NAME, 700)
        wide = self._as_read(_LONG_NAME)
        self.assertEqual(wide["count"], 1)
        spare = wide["more"] + wide["gap"]
        # over by the state, its gap and half ⋯'s room, less the script's slack of
        # two pixels: more than the action gives back
        excess = wide["state"] + wide["gap"] + spare / 2 - 2
        self.assertGreater(excess, wide["actions"] + 2)
        self._narrow(_LONG_NAME, 700 - wide["inside"] + wide["need"] - excess)
        parts = self._parts(_LONG_NAME)
        self.assertTrue(parts["below"])
        self.assertEqual(parts["folded"], 0)
        self.assertEqual(parts["shown"], 1)
        self.assertIsNone(parts["more"])
        self.assertEqual(parts["nameLines"], 1)
        self.assertTrue(self._on_one_line(parts, "name", "icons"))
        self.assertGreaterEqual(parts["state"]["y"], parts["icons"]["bottom"] - 1)

    def test_the_state_drops_beneath_where_the_name_would_be_cut(self):
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        page = self.page
        # with room, the state stays in the row while actions fold
        self._narrow(_WEB, 300)
        parts = self._parts(_WEB)
        self.assertLess(parts["shown"], 3)
        self.assertFalse(parts["below"])
        self.assertTrue(self._on_one_line(parts, "name", "state", "icons"))
        # a name the row cannot hold with the state, even with every action folded:
        # the state takes its own line beneath, right-aligned, and the actions get
        # its room back — the card as wide as leaves its row, as read, a few pixels
        # over with every action folded
        self._narrow(_LONG_NAME, 700)
        read = self._as_read(_LONG_NAME)
        self._overflowing(_LONG_NAME,
                          read["actions"] + read["count"] * read["gap"] + 6)
        long = self._parts(_LONG_NAME)
        self.assertTrue(long["below"])
        self.assertEqual(long["nameLines"], 1)
        self.assertGreaterEqual(long["state"]["y"], long["icons"]["bottom"] - 1)
        self.assertAlmostEqual(long["state"]["right"], long["head"]["right"],
                               delta=3)
        self.assertTrue(self._on_one_line(long, "name", "icons"))
        self.assertGreater(long["shown"], 0)
        # and the name gives way last: narrower still, it wraps inside itself
        self._narrow(_LONG_NAME, 220)
        last = self._parts(_LONG_NAME)
        self.assertTrue(last["below"])
        self.assertEqual(last["shown"], 0)
        self.assertGreater(last["nameLines"], 1)
        # under `card_status_line: below` every card's state is beneath, the actions
        # and the icons on the first line with the name
        page.evaluate("document.body.dataset.lsCardState = 'below'")
        page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        for path in (_NAS, _WEB):
            with self.subTest(path=path):
                drawn = self._parts(path)
                self.assertGreaterEqual(drawn["state"]["y"],
                                        drawn["icons"]["bottom"] - 1)
                self.assertTrue(self._on_one_line(drawn, "name", "icons"))
                self.assertGreater(drawn["shown"], 0)
                self.assertAlmostEqual(drawn["actions"][0]["y"], drawn["icons"]["y"],
                                       delta=6)
        # the state's line is the row's own there, not room the script gives back:
        # a name too long for the row by less than the state is wide, with every
        # action folded, keeps them folded and breaks
        self._narrow(_LONG_NAME, 700)
        read = self._as_read(_LONG_NAME)
        excess = read["actions"] + (read["count"] - 1) * read["gap"] + 20
        self._narrow(_LONG_NAME, 700 - read["inside"] + read["need"] - excess)
        last = self._parts(_LONG_NAME)
        self.assertEqual(last["shown"], 0)
        self.assertIsNotNone(last["more"])
        self.assertGreater(last["nameLines"], 1)

    def test_the_row_is_read_with_nothing_squeezed_so_what_stays_in_it_fits(self):
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        # at every width of a card with a long name, and of one holding a box with
        # a leading cue: while the state is in the row the name is whole, and a
        # whole name has the cue beside it at its own width — nothing in the row
        # absorbs an overflow the script failed to read
        for card, path in ((_LONG_NAME, _LONG_NAME), (_WEB, _DNS)):
            self._narrow(card, 700)
            rest = self._parts(path)                   # a row with room for all
            for width in range(440, 196, -4):
                with self.subTest(path=path, width=width):
                    self._narrow(card, width)
                    parts = self._parts(path)
                    if not parts["below"]:
                        self.assertEqual(parts["nameLines"], 1)
                    if parts["nameLines"] == 1:
                        if rest["cue"]:
                            self.assertAlmostEqual(parts["cue"]["width"],
                                                   rest["cue"]["width"], delta=0.5)
                        self.assertTrue(self._on_one_line(parts, "name", "icons"))
        # the exact window where folding every action gives back the actions and
        # the gaps between them — one fewer than the actions — and half a pixel is
        # still missing: the state drops beneath rather than the name breaking
        self._narrow(_LONG_NAME, 700)
        read = self._as_read(_LONG_NAME)
        excess = read["actions"] + read["count"] * read["gap"] - 2.5
        self._narrow(_LONG_NAME, 700 - read["inside"] + read["need"] - excess)
        parts = self._parts(_LONG_NAME)
        self.assertTrue(parts["below"])
        self.assertEqual(parts["nameLines"], 1)
        self.assertTrue(self._on_one_line(parts, "name", "icons"))
        self.assertGreaterEqual(parts["state"]["y"], parts["icons"]["bottom"] - 1)

    def test_a_broken_name_carries_the_state_on_its_second_line(self):
        # where the name breaks anyway, the state stands on its second line beneath
        # the icons, instead of on a third line of its own; a name of one line keeps the
        # state's own line beneath — the widths are the plain theme's face, where this
        # name breaks and has room
        self._choose(theme="plain")
        self.tree.upsert(_QUEUE, StatusCode.ERROR, ["the queue's last job failed"])
        self._wall()
        one, two = self._breaking(_QUEUE, _WEB)
        self.assertFalse(one["beside"])
        self.assertGreaterEqual(one["state"]["y"], one["icons"]["bottom"] - 1)
        self.assertGreater(one["head"]["height"], one["name"]["height"] + 10)
        self.assertTrue(two["beside"])
        self.assertGreaterEqual(two["state"]["y"], two["icons"]["bottom"] - 1)
        self.assertAlmostEqual(two["state"]["bottom"], two["name"]["bottom"], delta=4)
        # no taller than the name, and given no room for a line it does not take
        self.assertLessEqual(two["head"]["height"], two["name"]["height"] + 2)
        self.assertEqual(two["room"], "")
        self.assertAlmostEqual(two["state"]["right"], two["head"]["right"], delta=3)
        # the icons level with the name's first line, not between its two
        self.assertAlmostEqual(two["icons"]["y"], two["name"]["y"], delta=5)
        # and with room again, the row is one line and nothing of it is left
        self._narrow(_WEB, 1000)
        wide = self._parts(_QUEUE)
        self.assertEqual((wide["below"], wide["beside"]), (False, False))
        self.assertTrue(self._on_one_line(wide, "name", "state", "icons"))

    def test_a_state_that_would_touch_the_name_keeps_a_line_of_its_own(self):
        self.tree.upsert(_QUEUE, StatusCode.ERROR, ["the queue's last job failed"])
        self._wall()
        self._breaking(_QUEUE, _WEB)
        # a state as wide as the box: beside the name's last line it would lie on it
        self._head(_QUEUE).evaluate(
            "head => head.querySelector(':scope > .status-node__state')"
            ".insertAdjacentHTML('afterbegin',"
            " '<span style=\"display:inline-block;width:320px\"></span>')")
        self.page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        parts = self._parts(_QUEUE)
        self.assertTrue(parts["below"])
        self.assertEqual(parts["nameLines"], 2)
        self.assertFalse(parts["beside"])
        self.assertGreaterEqual(parts["state"]["y"], parts["name"]["bottom"] - 1)

    def test_the_state_beside_the_name_keeps_the_toolbars_gap_from_it(self):
        # beside the name's last line the state stands at least the toolbar's gap
        # from where the name ends, or it takes its own line
        self.tree.upsert(_QUEUE, StatusCode.ERROR, ["the queue's last job failed"])
        self._wall()
        self._breaking(_QUEUE, _WEB)
        for room, beside in ((1.0, True), (-1.0, False)):
            with self.subTest(room=room):
                self._head(_QUEUE).evaluate("""(head, room) => {
                    const state = head.querySelector(':scope > .status-node__state');
                    head.querySelectorAll('.probe').forEach(el => el.remove());
                    const name = head.querySelector('[data-control="toggle"]');
                    const range = document.createRange();
                    range.selectNodeContents(name);
                    const lines = Array.from(range.getClientRects())
                        .filter(r => r.width > 0);
                    // the end of the name's last line, the one the state shares
                    const end = lines
                        .reduce((a, b) => (b.bottom > a.bottom ? b : a)).right;
                    const gap = parseFloat(getComputedStyle(
                        head.querySelector(':scope > .node-controls')).columnGap);
                    const s = state.getBoundingClientRect();
                    // the state's left edge at the gap past the name's end, give
                    // or take a pixel
                    const spacer = s.left - (end + gap + room);
                    state.insertAdjacentHTML('afterbegin',
                        '<span class="probe" style="display:inline-block;width:'
                        + spacer + 'px"></span>');
                }""", room)
                self.page.evaluate(
                    "window.lsTree.apply(document.getElementById('status-grid'))")
                parts = self._parts(_QUEUE)
                self.assertEqual(parts["nameLines"], 2)
                self.assertEqual(parts["beside"], beside)

    def test_under_below_a_broken_cards_name_shares_its_line_with_the_state(self):
        # `card_status_line: below` gives every card a second line for its state;
        # where the name broke onto that line anyway, the state stands beside it
        self.tree.upsert("/night-shift/job", StatusCode.ERROR, ["the job failed"])
        self._wall()
        self.page.evaluate("document.body.dataset.lsCardState = 'below'")
        found = None
        for width in range(440, 196, -4):
            self._narrow("/night-shift", width)
            parts = self._parts("/night-shift")
            if parts["nameLines"] == 2:
                found = parts
                break
        self.assertIsNotNone(found, "no width breaks the card's name in two")
        assert found is not None
        self.assertTrue(found["beside"])
        self.assertLessEqual(found["head"]["height"], found["name"]["height"] + 2)
        self.assertEqual(found["room"], "")
        self.assertAlmostEqual(found["state"]["bottom"], found["name"]["bottom"],
                               delta=4)

    def test_the_glyphs_fill_their_squares(self):
        # sixteen of the square's twenty-four pixels, centred; the square stays the
        # touch target it is
        self._wall()
        squares = self._head(_WEB).evaluate("""head =>
            Array.from(head.querySelectorAll('.node-icons > .node-icon'), square => {
              const s = square.getBoundingClientRect();
              const g = square.querySelector('.icon-mark').getBoundingClientRect();
              return [square.dataset.control, s.width, s.height, g.width, g.height,
                      g.left - s.left, s.right - g.right, g.top - s.top,
                      s.bottom - g.bottom];
            })""")
        self.assertGreaterEqual(len(squares), 3)
        for kind, width, height, glyph_w, glyph_h, left, right, top, bottom in squares:
            with self.subTest(icon=kind):
                self.assertEqual((round(width), round(height)), (24, 24))
                self.assertEqual((round(glyph_w), round(glyph_h)), (16, 16))
                self.assertAlmostEqual(left, right, delta=1)
                self.assertAlmostEqual(top, bottom, delta=1)

    def test_a_cards_children_stand_six_pixels_below_its_lines(self):
        # as a nested box's always have: a run of chips straight under a card's
        # line read as part of it
        self.tree.upsert("/ops", StatusCode.OK, ["one line of the card's own"])
        self.tree.upsert("/ops/alpha", StatusCode.OK)
        self.tree.upsert("/ops/beta", StatusCode.OK)
        self._wall()
        gap = self._node("/ops").evaluate("""card => {
            const panel = card.querySelector(':scope > .tree-hold > .status-panel');
            const block = panel.querySelector(':scope > .reason-block');
            const kids = panel.querySelector(':scope > .node-children');
            return kids.getBoundingClientRect().top
                - block.getBoundingClientRect().bottom;
        }""")
        self.assertAlmostEqual(gap, 6, delta=0.5)

    def test_a_title_squeezed_below_two_letters_is_hidden_not_clipped(self):
        # a title with less room than two letters and its ellipsis would show a
        # clipped glyph — a `P` read as an `F` — so the middle shows nothing there
        self._wall()
        squeezed = shown = 0
        for width in range(560, 196, -2):
            self._narrow(_WEB, width)
            middle = self._head(_WEB).evaluate("""head => {
                const middle = head.querySelector(':scope > .status-head__middle');
                const title = middle.querySelector('.node-title');
                return {width: middle.getBoundingClientRect().width,
                        em: parseFloat(getComputedStyle(middle).fontSize),
                        visible: getComputedStyle(title).visibility === 'visible'};
            }""")
            limit = 2.5 * middle["em"]
            if 0.5 < middle["width"] < limit - 0.5:
                squeezed += 1
                self.assertFalse(middle["visible"], f"{width}: {middle}")
            elif middle["width"] > limit + 0.5:
                shown += 1
                self.assertTrue(middle["visible"], f"{width}: {middle}")
        self.assertGreater(squeezed, 0)
        self.assertGreater(shown, 0)

    # --- the row under the pointer ---

    def test_a_head_under_the_pointer_wears_an_outline_of_its_own_ink(self):
        # the whole row opens and closes its node, and with the caret gone it says
        # so where the pointer is: a line of its surface's ink at 60 %, 3 pixels
        # out, no fill — on a card's head, a box's on a warning and a box's on a
        # failure, from the title — past the toolbar lying over its start under the
        # pointer — the name, the cue and the state alike — under the look
        # `toggle_hover: outline`, a viewer's choice, with the card on a pause
        self._choose(toggle_hover="outline", inspection_card="pause")
        self.tree.set_title(_FLAKY, "the flaky one")        # a card on a pause
        self._wall()
        for path in (_WEB, _DNS, _FLAKY):
            head = self._head(path)
            self.page.mouse.move(2, 2)
            rest = self._look(path)
            self.assertEqual(rest["outline"], "none", path)
            # the pointer's own sign where a click is what the row offers, and the
            # help cursor on the name alone, where a pause also brings the node's
            # card (ADR-0019)
            self.assertEqual(rest["cursor"], "pointer", path)
            name = head.locator('[data-control="toggle"]')
            card = name.evaluate("n => n.classList.contains('inspect-trigger')")
            self.assertEqual(name.evaluate("n => getComputedStyle(n).cursor"),
                             "help" if card else "pointer", path)
            self.assertEqual(card, path != _DNS, path)     # a title, or none
            parts = [":scope > .status-head__middle", '[data-control="toggle"]',
                     ":scope > .status-card__state, :scope > .status-node__state"]
            if head.locator(":scope > .status-cue").count():
                parts.append(":scope > .status-cue")
            for part in parts:
                with self.subTest(path=path, part=part):
                    self._point_at(head.locator(part), end="middle" in part)
                    look = self._look(path)
                    self.assertEqual((look["outline"], look["width"], look["offset"]),
                                     ("solid", "1px", "3px"))
                    self.assertEqual([round(v) for v in look["line"][:3]],
                                     [round(v) for v in look["ink"][:3]])
                    self.assertAlmostEqual(look["line"][3], 0.6, delta=0.01)
                    self.assertEqual(look["fill"][3], 0)
        # and the outline is the row's alone: the box around it wears none
        self.assertEqual(self._node(_DNS).locator(":scope > .tree-hold > .tree-box")
                         .evaluate("box => getComputedStyle(box).outlineStyle"), "none")
        self.page.mouse.move(2, 2)
        self.assertEqual(self._look(_DNS)["cursor"], "pointer")

    def test_the_pointer_on_a_heads_own_controls_draws_no_outline(self):
        # a click on them toggles nothing, so the row does not offer itself there:
        # on an icon, in the gap between two, on an action, on a card's pip of the
        # maintenance beneath it, on ⋯ and in its menu
        self.tree.set_maintenance(_FLAKY, "planned", set_by="pan",
                                  expires_at=_NOON + timedelta(days=1))
        self._wall()
        self._point_at(self._head(_WEB).locator(".maintenance-pip"))
        self.assertEqual(self._look(_WEB)["outline"], "none", "the pip")
        for path in (_WEB, _DNS):                          # a card's head, a box's
            head = self._head(path)
            head.scroll_into_view_if_needed()
            squares = head.locator(".node-icons > .node-icon").all()
            left, right = squares[0].bounding_box(), squares[1].bounding_box()
            gap = ((left["x"] + left["width"] + right["x"]) / 2,
                   left["y"] + left["height"] / 2)
            self.assertEqual(self.page.evaluate(
                "([x, y]) => document.elementFromPoint(x, y).className", list(gap)),
                "node-icons")
            self.page.mouse.move(*gap)
            self.assertEqual(self._look(path)["outline"], "none", f"{path}: the gap")
            for name, part in (("an icon", squares[0]),
                               ("an action", head.locator(".node-actions > a").first)):
                self._point_at(part)
                self.assertEqual(self._look(path)["outline"], "none",
                                 f"{path}: {name}")
        # a card narrow enough that its head and its box's fold actions behind ⋯
        self._narrow(_WEB, 300)
        for path in (_WEB, _DNS):
            more = self._head(path).locator(".node-more")
            self.assertTrue(more.is_visible(), path)
            self._point_at(more)
            self.assertEqual(self._look(path)["outline"], "none", f"{path}: ⋯")
            more.click()
            self._point_at(self._head(path)
                           .locator('.node-actions-menu [role="menuitem"]').first)
            self.assertEqual(self._look(path)["outline"], "none", f"{path}: the menu")
            self.page.keyboard.press("Escape")
            # the pointer back on the row's own words: the outline again
            self._point_at(self._head(path).locator('[data-control="toggle"]'))
            self.assertEqual(self._look(path)["outline"], "solid", path)

    def test_a_pressed_head_wears_a_wash_of_its_ink_and_a_pressed_control_none(self):
        self._wall()
        for path in (_WEB, _DNS):                          # a card's head, a box's
            with self.subTest(path=path):
                head = self._head(path)
                look = self._pressed(head.locator(":scope > .status-head__middle"),
                                     end=True)
                self.assertEqual([round(v) for v in look["fill"][:3]],
                                 [round(v) for v in look["ink"][:3]])
                self.assertAlmostEqual(look["fill"][3], 0.12, delta=0.01)
                # the wash reaches 4 pixels past the row, in the same ink
                self.assertRegex(look["ring"], r" 0px 0px 0px 4px$")
                self.assertAlmostEqual(look["ringInk"][3], 0.12, delta=0.01)
                self.assertEqual(self._state(path), "open")  # let go away: no toggle
                look = self._pressed(head.locator(".node-icons > .node-icon").first)
                self.assertEqual((look["fill"][3], look["ringInk"][3]), (0, 0))

    def test_the_name_under_the_pointer_is_not_underlined(self):
        # the whole row answers the pointer; the link's underline said it of the
        # name alone — a card's name and a box's
        self._wall()
        for path in (_WEB, _DNS):
            with self.subTest(path=path):
                name = self._head(path).locator('[data-control="toggle"]')
                self._point_at(name)
                self.assertEqual(name.evaluate(
                    "n => getComputedStyle(n).textDecorationLine"), "none")
                self.assertEqual(self._look(path)["outline"], "solid")

    def test_the_wash_a_browser_chooses_stands_in_the_outlines_place(self):
        # the look `toggle_hover: wash` (ADR-0029), as the
        # settings menu writes it: under the pointer the outline's share of the ink
        # goes to nothing and a wash of 10 % takes its place, on a head's row and on
        # a chip, the press as it was
        self._choose(toggle_hover="wash")
        self._wall()
        middle = self._head(_DNS).locator(":scope > .status-head__middle")
        self._point_at(middle, end=True)
        look = self._look(_DNS)
        self.assertEqual(look["line"][3], 0)
        self.assertAlmostEqual(look["fill"][3], 0.10, delta=0.01)
        self.assertRegex(look["ring"], r" 0px 0px 0px 4px$")
        self.assertAlmostEqual(self._pressed(middle, end=True)["fill"][3], 0.12,
                               delta=0.01)
        self._point_at(self._chip(_CDN))
        look = self._chip_look(_CDN)
        self.assertEqual(look["line"][3], 0)
        self.assertAlmostEqual(look["wash"][3], 0.10, delta=0.01)
        # and under forced colors the row draws what a browser that chose the
        # outline draws there: the outline, in the system's color, and no wash,
        # which would be the system's background at a tenth
        self.page.emulate_media(forced_colors="active")
        self.page.mouse.move(2, 2)
        self._point_at(middle, end=True)
        forced = self._look(_DNS)
        self.assertEqual(forced["outline"], "solid")
        self.assertGreater(forced["line"][3], 0.5)
        self.assertEqual(forced["fill"][3], 0)

    def test_the_row_paints_from_its_tokens(self):
        # the line's share, the wash's under the pointer and the press's — the
        # rules read the tokens, not numbers of their own
        self._wall()
        self.page.add_style_tag(content=":root { --ls-toggle-hover-line: 0%;"
                                        " --ls-toggle-hover-wash: 10%;"
                                        " --ls-toggle-press-wash: 20%; }")
        middle = self._head(_DNS).locator(":scope > .status-head__middle")
        self._point_at(middle, end=True)
        look = self._look(_DNS)
        self.assertEqual(look["line"][3], 0)
        self.assertAlmostEqual(look["fill"][3], 0.10, delta=0.01)
        self.assertRegex(look["ring"], r" 0px 0px 0px 4px$")
        self.assertAlmostEqual(look["ringInk"][3], 0.10, delta=0.01)
        self.assertAlmostEqual(self._pressed(middle, end=True)["fill"][3], 0.20,
                               delta=0.01)
        # and a chip from the same tokens
        chip = self._chip(_CDN)
        self._point_at(chip)
        look = self._chip_look(_CDN)
        self.assertEqual(look["line"][3], 0)
        self.assertAlmostEqual(look["wash"][3], 0.10, delta=0.01)
        self.assertAlmostEqual(self._chip_pressed(_CDN)["wash"][3], 0.20, delta=0.01)

    def test_the_glyphs_grow_with_their_squares_under_a_larger_font(self):
        # a browser set to a larger font grows the squares, which are in rem, and
        # the glyphs with them — two thirds of the square at any size, where a
        # glyph in pixels sat in a wider and wider margin; an action's image too
        runbook = Action("Runbook", "https://wiki.example.org/{path}", "node.actions",
                         icon="jira")
        configured = mock.patch.object(actions_module, "_actions",
                                       (runbook, *_ACTIONS))
        configured.start()
        self.addCleanup(configured.stop)
        self._wall()
        self.page.add_style_tag(content="html { font-size: 20px; }")
        self.page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        squares = self._head(_WEB).evaluate("""head => Array.from(
            head.querySelectorAll('.node-icons > .node-icon, .node-actions > .is-icon'),
            square => {
              const s = square.getBoundingClientRect();
              const g = square.querySelector('.icon-mark, .action-icon')
                  .getBoundingClientRect();
              return [square.dataset.control || square.title, s.width, g.width,
                      g.height];
            })""")
        self.assertIn("Runbook", [square[0] for square in squares])
        for kind, square, glyph_w, glyph_h in squares:
            with self.subTest(square=kind):
                self.assertEqual(round(square), 30)
                self.assertEqual((round(glyph_w), round(glyph_h)), (20, 20))

    def test_a_chip_under_the_pointer_wears_the_rows_outline_a_pixel_out(self):
        # a chip opens its node as the row closes it, and says so as the row does: an
        # outline of its own ink at 60 %, a pixel out where chips stand close; its tint
        # stays, and neither it nor its name underlines — a quiet chip on a card and in
        # a box, and a failing one closed by a click; under the look
        # `toggle_hover: outline`, a viewer's choice
        self._choose(toggle_hover="outline")
        self._wall()
        self._head(_FLAKY).locator('[data-control="toggle"]').click()
        self.assertEqual(self._state(_FLAKY), "closed")
        in_a_box = f"{_NAS}/alpha/probe"
        self.assertEqual(self._chip(in_a_box).evaluate(
            "c => c.parentElement.closest('.tree-box') !== null"), True)
        for path in (_API, in_a_box, _FLAKY):
            with self.subTest(path=path):
                self.page.mouse.move(2, 2)
                rest = self._chip_look(path)
                self.assertEqual(rest["outline"], "none")
                self._point_at(self._chip(path))
                look = self._chip_look(path)
                self.assertEqual((look["outline"], look["width"], look["offset"]),
                                 ("solid", "1px", "1px"))
                self.assertEqual([round(v) for v in look["line"][:3]],
                                 [round(v) for v in look["ink"][:3]])
                self.assertAlmostEqual(look["line"][3], 0.6, delta=0.01)
                self.assertEqual(look["fill"], rest["fill"])
                self.assertEqual(look["wash"][3], 0)
                self.assertEqual((look["decoration"], look["nameDecoration"]),
                                 ("none", "none"))

    def test_a_chip_the_keyboard_is_on_keeps_its_focus_ring_under_the_pointer(self):
        self._wall()
        chip = self._chip(_API)
        for _ in range(80):
            if chip.evaluate("c => c === document.activeElement"):
                break
            self.page.keyboard.press("Tab")
        self.assertTrue(chip.evaluate("c => c.matches(':focus-visible')"))
        self._point_at(chip)
        self.assertNotEqual(self._chip_look(_API)["outline"], "solid")

    def test_a_pressed_chip_wears_a_wash_over_its_tint(self):
        self._wall()
        rest = self._chip_look(_API)
        look = self._chip_pressed(_API)
        self.assertEqual(look["fill"], rest["fill"])
        self.assertEqual([round(v) for v in look["wash"][:3]],
                         [round(v) for v in look["ink"][:3]])
        self.assertAlmostEqual(look["wash"][3], 0.12, delta=0.01)
        self.assertEqual(self._state(_API), "closed")    # let go away: nothing opened

    def test_a_long_name_breaks_where_its_words_meet_and_copies_whole(self):
        # `backup_of_the_primary_cluster` on a card too narrow for it breaks after
        # an underscore, never inside a word, and a copy of it carries no break of its
        # own
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        name = self._head(_LONG_NAME).locator('[data-control="toggle"]')
        ends: list[str] = []
        for width in range(400, 100, -6):
            self._narrow(_LONG_NAME, width)
            ends = name.evaluate("""name => {
                const chars = [];
                const walker = document.createTreeWalker(name, NodeFilter.SHOW_TEXT);
                for (let node = walker.nextNode(); node; node = walker.nextNode()) {
                  for (let i = 0; i < node.length; i++) {
                    const range = document.createRange();
                    range.setStart(node, i);
                    range.setEnd(node, i + 1);
                    const rect = range.getClientRects()[0];
                    if (rect) { chars.push([node.data[i], rect.top]); }
                  }
                }
                return chars.filter((c, i) => i === chars.length - 1
                    || chars[i + 1][1] > c[1] + 2).map(c => c[0]);
            }""")
            if len(ends) > 2:
                break
        self.assertGreater(len(ends), 2, "the name never broke")
        for end in ends[:-1]:
            self.assertEqual(end, "_", ends)
        copied = name.evaluate("""name => {
            const range = document.createRange();
            range.selectNodeContents(name);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            return selection.toString();
        }""")
        self.assertEqual(copied, "backup_of_the_primary_cluster")

    def test_a_box_a_click_or_the_map_opens_is_measured_at_once(self):
        # a window of one narrow column, so a box inside a card has no room for
        # three actions
        self.page.set_viewport_size({"width": 320, "height": 700})
        self._wall()
        self._chip(_CDN).click()
        parts = self._parts(_CDN)
        # shown with its actions behind ⋯ from the first paint, nothing cut
        self.assertGreater(parts["folded"], 0)
        self.assertIsNotNone(parts["more"])
        self.assertEqual(parts["nameLines"], 1)
        self._swap()
        self.assertGreater(self._parts(_CDN)["folded"], 0)
        # and after a reload, from the map
        self._reload()
        self.assertEqual(self._state(_CDN), "open")
        self.assertGreater(self._parts(_CDN)["folded"], 0)
        # the boxes beneath a card a click opens are measured with it: closed
        # through a swap, their heads had no width to be read at
        probe = f"{_NAS}/zeta/probe"
        self._head(_NAS).locator(".status-card__name").click()
        self._swap()
        self.assertEqual(self._state(_NAS), "closed")
        self._head(_NAS).locator(".status-card__name").click()
        self.assertGreater(self._parts(probe)["folded"], 0)
        # and a window that grows gives the row its room back: the grid's width is
        # watched, and the heads are read again shortly after it changes
        self._resized_to(1000)
        self.page.clock.run_for(200)
        self.assertEqual(self._parts(probe)["folded"], 0)
        self.assertEqual(self._parts(_CDN)["folded"], 0)

    def test_a_heads_controls_are_one_toolbar_walked_with_the_arrow_keys(self):
        self._wall()
        page = self.page
        toolbar = self._head(_WEB).locator(".node-controls")
        self.assertEqual(toolbar.get_attribute("role"), "toolbar")
        self.assertEqual(toolbar.get_attribute("aria-label"), "web controls")
        # one stop: Tab from the name reaches the first control, ↗, and Tab again
        # leaves the toolbar for the next node
        self._head(_WEB).locator(".status-card__name").focus()
        page.keyboard.press("Tab")
        self.assertEqual(self._focused(), "page")
        self.assertEqual(toolbar.locator('[tabindex="0"]').count(), 1)
        # the head's icons, then the node's actions
        for control in ("ok", "chips", "pin", "ack", "File", "Mute"):
            page.keyboard.press("ArrowRight")
            self.assertEqual(self._focused(), control)
        page.keyboard.press("End")
        self.assertEqual(self._focused(), "Escalate")
        page.keyboard.press("ArrowRight")
        self.assertEqual(self._focused(), "Escalate")      # the end stays the end
        page.keyboard.press("ArrowLeft")
        self.assertEqual(self._focused(), "Mute")
        page.keyboard.press("Home")
        self.assertEqual(self._focused(), "page")
        for _ in range(3):
            page.keyboard.press("ArrowRight")
        self.assertEqual(self._focused(), "pin")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate(
            "document.activeElement.closest('.tree-node').dataset.node"), _API)
        self.assertTrue(page.evaluate(
            "document.activeElement.classList.contains('tree-chip')"))
        # Shift+Tab comes back to the stop the arrows left, and the stop is kept
        # by node through a swap and given back with the focus
        page.keyboard.press("Shift+Tab")
        self.assertEqual(self._focused(), "pin")
        self._swap()
        self.assertEqual(self._focused(), "pin")
        self.assertEqual(toolbar.locator('[tabindex="0"]').get_attribute("data-control"),
                         "pin")
        self._head(_WEB).locator(".status-card__name").focus()
        page.keyboard.press("Tab")
        self.assertEqual(self._focused(), "pin")
        # a focus on a second action keeps that one through a swap
        self._head(_DNS).locator(".node-actions > a").nth(1).focus()
        self._swap()
        self.assertEqual(self._focused(), "Mute")
        # a click on a control moves the stop to it, so Tab comes back there
        self._icon(_WEB, "ok").click()
        self._head(_WEB).locator(".status-card__name").focus()
        page.keyboard.press("Tab")
        self.assertEqual(self._focused(), "ok")

    def test_all_n_stands_beneath_clipped_lines_and_folds_them_again(self):
        self.tree.upsert(f"{_NAS}/zeta/probe", StatusCode.ERROR,
                         [f"line {n} of zeta" for n in range(12)])
        self.tree.upsert(_MAIL, StatusCode.OK, [f"fine {n}" for n in range(12)])
        # two lines, each long enough to wrap past the budget at the width the
        # planner gives the web's boxes
        self.tree.upsert(_CDN, StatusCode.OK, [
            " ".join(f"edge {n} warm" for n in range(60)),
            " ".join(f"origin {n} cold" for n in range(60))])
        self._wall()
        page = self.page
        probe = f"{_NAS}/zeta/probe"
        block = page.locator(f'.reason-block[data-reason-node="{probe}"]')
        button = block.locator("xpath=following-sibling::*[1]")
        self.assertEqual(button.get_attribute("data-control"), "lines")
        self.assertTrue(button.is_visible())
        self.assertEqual(button.inner_text().strip(), "\u2304 all 12")
        self.assertEqual(button.get_attribute("aria-expanded"), "false")
        self.assertEqual(button.get_attribute("aria-controls"),
                         block.get_attribute("id"))
        self.assertTrue(block.evaluate("b => b.classList.contains('is-clipped')"))
        # beneath the lines, and no seat for it in any head
        lines = block.bounding_box()
        self.assertGreaterEqual(button.bounding_box()["y"],
                                lines["y"] + lines["height"] - 1)
        self.assertEqual(page.locator(".reason-chevron").count(), 0)
        self.assertEqual(page.locator(
            '.status-card__head [data-control="lines"], '
            '.status-node__self [data-control="lines"]').count(), 0)
        # after the lines in the tab order: Tab from the end of the head's toolbar
        # passes the lines, which carry no control here, and lands on it
        self._icon(probe, "pin").focus()
        page.keyboard.press("Tab")
        self.assertEqual(self._focused(), "lines")
        self.assertTrue(button.evaluate("b => b === document.activeElement"))
        # a click shows them all, and *⌃ less* folds them again; the map keeps it
        button.click()
        self.assertTrue(block.evaluate("b => b.classList.contains('is-open')"))
        self.assertEqual(button.inner_text().strip(), "\u2303 less")
        self.assertEqual(button.get_attribute("aria-expanded"), "true")
        self.assertEqual(self._map()["nodes"], {probe: {"lines": True}})
        self._swap()
        self.assertTrue(block.evaluate("b => b.classList.contains('is-open')"))
        button.click()
        self.assertFalse(block.evaluate("b => b.classList.contains('is-open')"))
        self.assertIsNone(self._map())
        # a block that fits has no button to show
        api = page.locator(f'.reason-block[data-reason-node="{_API}"]')
        self.assertFalse(api.locator("xpath=following-sibling::*[1]").is_visible())
        # measured when its box opens: a chip's lines overflow once it is shown
        self._chip(_MAIL).click()
        mail = page.locator(f'.reason-block[data-reason-node="{_MAIL}"]')
        self.assertTrue(mail.locator("xpath=following-sibling::*[1]").is_visible())
        # a block of fewer lines than the budget carries no button from the server;
        # where they wrap past it, the script draws one
        cdn = page.locator(f'.reason-block[data-reason-node="{_CDN}"]')
        drawn = page.locator(f'.reason-block[data-reason-node="{_CDN}"] + .reason-more')
        self.assertEqual(drawn.count(), 0)
        self._chip(_CDN).click()
        self.assertTrue(drawn.is_visible())
        self.assertEqual(drawn.inner_text().strip(), "\u2304 all 2")
        self.assertEqual(drawn.get_attribute("aria-controls"), cdn.get_attribute("id"))

    def test_the_lines_all_n_opens_scroll_inside_about_half_a_window(self):
        # The lines *⌄ all N* opens stand no taller than about half a window, the rest
        # scrolling inside the box — a region the keyboard reaches and a screen reader
        # names, standing where its viewer left it through the swap — and *⌃ less* folds
        # them to their first lines as before; a block whose lines fit opens to its
        # height and is no region
        probe = f"{_NAS}/zeta/probe"
        self.tree.upsert(probe, StatusCode.ERROR, [
            f"line {n} of zeta, long enough to wrap in a box of the wall's track"
            for n in range(120)])
        self.tree.upsert(_MAIL, StatusCode.OK, [f"fine {n}" for n in range(12)])
        self._wall()
        page = self.page
        block = page.locator(f'.reason-block[data-reason-node="{probe}"]')
        button = block.locator("xpath=following-sibling::*[1]")
        closed = block.evaluate("b => b.getBoundingClientRect().height")
        self.assertIsNone(block.get_attribute("role"))
        button.click()
        drawn = block.evaluate("""b => ({
            height: b.getBoundingClientRect().height, half: innerHeight / 2,
            scrolls: b.scrollHeight > b.clientHeight + 1,
            role: b.getAttribute('role'), tabindex: b.getAttribute('tabindex'),
            label: b.getAttribute('aria-label'),
            overscroll: getComputedStyle(b).overscrollBehaviorY})""")
        self.assertLessEqual(drawn["height"], drawn["half"] + 1, drawn)
        self.assertGreater(drawn["height"], closed + 1, drawn)
        self.assertTrue(drawn["scrolls"], drawn)
        self.assertEqual((drawn["role"], drawn["tabindex"]), ("region", "0"))
        self.assertEqual(drawn["label"], "All 120 lines of probe")
        # nothing holds the wheel at its ends: the page goes on past it
        self.assertEqual(drawn["overscroll"], "auto")
        # the keyboard reaches it and scrolls it
        block.focus()
        self.assertTrue(block.evaluate("b => b === document.activeElement"))
        page.keyboard.press("End")
        page.wait_for_function(
            "b => b.scrollTop > 0", arg=block.element_handle(), timeout=2000)
        page.keyboard.press("Home")
        # the key's scroll is animated: read it once it has stood still a few frames
        page.wait_for_function("""b => {
            const top = b.scrollTop;
            b.dataset.still = b.dataset.last === String(top)
                ? String(Number(b.dataset.still || 0) + 1) : "0";
            b.dataset.last = String(top);
            return top === 0 && Number(b.dataset.still) >= 5;
        }""", arg=block.element_handle(), timeout=3000)
        # where its viewer left it, through the swap: somewhere in the middle. Set there
        # directly, since a PageDown pressed as Home's scroll came to rest was seen to
        # scroll nothing at all, and the page hears a scroll alike however it was made;
        # what it heard is what the swap has to keep
        left = block.evaluate("""b => new Promise(heard => {
            b.addEventListener("scroll", () => heard(b.scrollTop), {once: true});
            b.scrollTop = Math.round((b.scrollHeight - b.clientHeight) / 2);
        })""")
        self.assertGreater(left, 0)
        self.assertLess(left, block.evaluate("b => b.scrollHeight - b.clientHeight"))
        self._swap()
        self.assertTrue(block.evaluate("b => b.classList.contains('is-open')"))
        self.assertAlmostEqual(block.evaluate("b => b.scrollTop"), left, delta=2)
        self.assertEqual(block.get_attribute("tabindex"), "0")
        # *⌃ less* folds them to their first lines, a region no more; opened again
        # they start at the first
        button.click()
        folded = block.evaluate("""b => ({top: b.scrollTop,
            role: b.getAttribute('role'), tabindex: b.getAttribute('tabindex'),
            height: b.getBoundingClientRect().height})""")
        self.assertEqual(folded["top"], 0)
        self.assertIsNone(folded["role"])
        self.assertIsNone(folded["tabindex"])
        self.assertAlmostEqual(folded["height"], closed, delta=1)
        button.click()
        self.assertEqual(block.evaluate("b => b.scrollTop"), 0)
        # a block whose lines fit opens to its height, and is no region
        self._chip(_MAIL).click()
        mail = page.locator(f'.reason-block[data-reason-node="{_MAIL}"]')
        mail.locator("xpath=following-sibling::*[1]").click()
        fits = mail.evaluate("""b => ({open: b.classList.contains('is-open'),
            scrolls: b.scrollHeight > b.clientHeight + 1,
            role: b.getAttribute('role'), tabindex: b.getAttribute('tabindex')})""")
        self.assertEqual(fits, {"open": True, "scrolls": False, "role": None,
                                "tabindex": None})

    def test_a_budget_taller_than_half_a_window_never_shrinks_as_it_opens(self):
        # where a deployment's line budget is taller than half the window, the lines
        # *⌄ all N* opens stand at least as tall as the budget did, and scroll beyond
        probe = f"{_NAS}/zeta/probe"
        self.tree.upsert(probe, StatusCode.ERROR,
                         [f"line {n} of zeta" for n in range(120)])
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, reason_cap=30)):
            self._wall()
            block = self.page.locator(f'.reason-block[data-reason-node="{probe}"]')
            closed = block.evaluate("b => b.getBoundingClientRect().height")
            self.assertGreater(closed, self.page.evaluate("innerHeight / 2"))
            block.locator("xpath=following-sibling::*[1]").click()
            opened = block.evaluate("""b => ({height: b.getBoundingClientRect().height,
                scrolls: b.scrollHeight > b.clientHeight + 1})""")
        self.assertGreaterEqual(opened["height"], closed - 1, opened)
        self.assertTrue(opened["scrolls"], opened)

    def test_an_opened_scrolling_block_passes_axe(self):
        # a scroll area the keyboard cannot reach, or a name on a block that is no
        # region, is what axe-core's WCAG 2 rules find: the opened block is scanned
        if Axe is None:
            self.skipTest("axe-playwright-python is not installed")
        probe = f"{_NAS}/zeta/probe"
        self.tree.upsert(probe, StatusCode.ERROR,
                         [f"line {n} of zeta" for n in range(120)])
        # the page's own clock, not the held one `_wall` installs: axe-core schedules
        # its work on the page's timers, which a held clock never runs
        self.page.goto(f"{self.base}/status")
        self.page.wait_for_selector("#status-grid .status-card")
        selector = f'.reason-block[data-reason-node="{probe}"]'
        block = self.page.locator(selector)
        block.locator("xpath=following-sibling::*[1]").click()
        self.assertEqual(block.get_attribute("role"), "region")
        found = Axe().run(self.page, context=selector, options={
            "runOnly": {"type": "tag", "values": [
                "wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]}}).response
        self.assertEqual([violation["id"] for violation in found["violations"]], [])

    def test_an_admins_pin_mark_clones_the_editor_into_the_box_and_holds_the_swap(self):
        self._wall()
        page = self.page
        mark = self._icon(_DNS, "pin")
        self.assertEqual(mark.get_attribute("href"), f"/status{_DNS}")
        mark.click()
        page.wait_for_function("document.activeElement.name === 'note'")
        box = self._node(_DNS).locator(":scope > .tree-hold > .tree-box")
        clone = box.locator(":scope > details.pin-setter")
        self.assertEqual(clone.count(), 1)
        self.assertEqual(clone.locator("input[name=path]").input_value(), _DNS)
        self.assertEqual(clone.locator(".rule-block__scope").inner_text().strip(),
                         "Maintenance for dns.")
        self.assertEqual(page.locator("template#pin-editor").count(), 1)
        # the refresh waits while it is open
        before = len(self.fragments)
        page.clock.run_for(10_000)
        page.wait_for_timeout(200)
        self.assertEqual(len(self.fragments), before)
        self.assertIn("paused while editing",
                      page.locator("#status-updated").inner_text())
        # Cancel takes the clone away and gives ‖ the focus; the refresh goes on
        clone.locator(".maintenance-editor-cancel").click()
        page.wait_for_function(
            "document.querySelector('#status-grid details.pin-setter') === null")
        self.assertEqual(self._focused(), "pin")
        self._swap()


#: The rows `tree.js` reads on a refresh, as it picks them: every head but those in a
#: closed node's box and a closed card's.
_ROWS = """Array.from(document.querySelectorAll(
        '#status-grid .status-node__self, #status-grid .status-card__head'))
    .filter(head => !head.closest('.tree-hold[hidden], .status-card.is-closed'))"""

#: Every such row as `tree.js` drew it, by its path: how many actions fold behind ⋯,
#: whether ⋯ is shown, and the state beneath the name or beside its last line.
_DRAWN_ROWS = """() => """ + _ROWS + """
    .map(head => [head.dataset.path,
                  head.querySelectorAll('.node-actions > .is-folded').length,
                  !!head.querySelector('.node-controls > .node-more:not([hidden])'),
                  head.classList.contains('is-state-below'),
                  head.classList.contains('is-state-beside'),
                  head.style.getPropertyValue('--ls-state-room')])"""

#: Which rows `tree.js` reads from here on: a head wears `is-measuring` while its row
#: is read, so a change of its class whose old value carried it names a row read.
_WATCH_READS = """() => {
    window.__read = new Set();
    window.__readsNote = records => records.forEach(record => {
      if ((record.oldValue || '').split(/\\s+/).indexOf('is-measuring') >= 0) {
        window.__read.add(record.target.dataset.path);
      }
    });
    window.__reads = new MutationObserver(window.__readsNote);
    window.__reads.observe(document.getElementById('status-grid'), {
      attributes: true, attributeFilter: ['class'], attributeOldValue: true,
      subtree: true});
}"""
_READS = """() => {
    window.__readsNote(window.__reads.takeRecords());
    window.__reads.disconnect();
    return Array.from(window.__read).sort();
}"""

#: What is written from here on to the grid's columns and its cards' spans — the plan
#: `dashboard-layout.js` lays on the grid.
_WATCH_PLAN = """() => {
    window.__planWrites = [];
    window.__planNote = records => records.forEach(record => {
      const target = record.target;
      if (target.classList.contains('status-grid')
          || (target.classList.contains('status-card')
              && target.parentElement.classList.contains('status-grid'))) {
        window.__planWrites.push(record.attributeName);
      }
    });
    window.__plan = new MutationObserver(window.__planNote);
    window.__plan.observe(document.getElementById('status-grid'), {
      attributes: true,
      attributeFilter: ['style', 'data-layout-span', 'data-layout-tracks'],
      subtree: true});
}"""
_PLAN_WRITES = """() => {
    window.__planNote(window.__plan.takeRecords());
    window.__plan.disconnect();
    return window.__planWrites;
}"""


class RefreshRowTests(_HeadRowCase):
    """The refresh reads a row only where it changed (backlog #91 §7.4): a row the
    server drew the same, at the same width, is drawn from what was read of it — and
    every row is read at the width the planner gives its card."""

    def _reads(self, change: Callable[[], None]) -> list[str]:
        """The rows `tree.js` reads while ``change`` runs, by their paths, sorted."""
        self.page.evaluate(_WATCH_READS)
        change()
        return self.page.evaluate(_READS)

    def _shown_rows(self) -> list[str]:
        return sorted(row[0] for row in self.page.evaluate(_DRAWN_ROWS))

    def _row_widths(self) -> dict[str, float]:
        return self.page.evaluate("() => Object.fromEntries(" + _ROWS + """
            .map(head => [head.dataset.path, head.getBoundingClientRect().width]))""")

    def _read_all_again(self) -> None:
        """Have the page read every row as it is drawn, as a resize does."""
        self.page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")

    def test_a_refresh_reads_again_only_the_rows_that_changed(self):
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self.tree.upsert(_QUEUE, StatusCode.ERROR, ["the queue's last job failed"])
        self._wall()
        # the web card as narrow as breaks the queue's name, by a stylesheet a
        # refresh keeps, so that one row draws its state beside the name's last line
        self._breaking(_QUEUE, _WEB)
        width = self._node(_WEB).evaluate("card => card.style.width")
        self.page.add_style_tag(content=(
            f'.status-card[data-node="{_WEB}"] {{ width: {width}; min-width: 0;'
            " justify-self: start; }"))
        # once a refresh has read the rows as the server drew them, the next draws a
        # row the server drew the same, at the same width, from what was read
        self._swap()
        drawn = self.page.evaluate(_DRAWN_ROWS)
        self.assertTrue(any(row[1] for row in drawn))            # actions folded
        self.assertTrue(any(row[2] for row in drawn))            # ⋯ shown
        self.assertTrue(any(row[3] for row in drawn))            # a state beneath
        self.assertTrue(any(row[4] for row in drawn))            # beside the name
        self.assertEqual(self._reads(self._swap), [])
        self.assertEqual(self.page.evaluate(_DRAWN_ROWS), drawn)
        # a row the server draws otherwise is read again, and it alone
        self.tree.set_title(_DNS, "the resolver, under a title it did not have")
        self.assertEqual(self._reads(self._swap), [_DNS])
        # what is drawn from a reading is what reading every row again draws
        drawn = self.page.evaluate(_DRAWN_ROWS)
        self._read_all_again()
        self.assertEqual(self.page.evaluate(_DRAWN_ROWS), drawn)

    def test_a_row_whose_width_changed_is_read_again(self):
        self._wall()
        self._swap()
        # a card drawn narrower by a stylesheet, which a refresh keeps: the grid's
        # width stays, so nothing reads the rows until the refresh — which reads
        # those of that card, and none other
        widths = self._row_widths()
        self.page.add_style_tag(content=(
            f'.status-card[data-node="{_NAS}"] {{ width: 300px; min-width: 0;'
            " justify-self: start; }"))
        now = self._row_widths()
        changed = sorted(path for path in now
                         if abs(now[path] - widths.get(path, -1.0)) > 0.05)
        self.assertTrue(changed)
        self.assertTrue(all(path == _NAS or path.startswith(_NAS + "/")
                            for path in changed), changed)
        self.assertEqual(self._reads(self._swap), changed)
        drawn = self.page.evaluate(_DRAWN_ROWS)
        self._read_all_again()
        self.assertEqual(self.page.evaluate(_DRAWN_ROWS), drawn)

    def test_a_row_drawn_already_is_read_again_when_it_is_asked_for(self):
        self._wall()
        self._swap()
        self._read_all_again()             # every row as this page has drawn it
        rows = self._shown_rows()
        # a stylesheet that pads every state cluster changes what each row needs, and
        # neither its markup nor its width: only a row as the server drew it is drawn
        # from a reading, and the rows this page drew are read again when asked for
        self.page.add_style_tag(content=(
            ":is(.status-card__head, .status-node__self) > .status-card__state,"
            " :is(.status-card__head, .status-node__self) > .status-node__state"
            " { padding-left: 40px; }"))
        self.assertEqual(self._reads(self._read_all_again), rows)

    def test_a_refresh_reads_each_row_at_the_width_its_card_is_planned_to(self):
        # at 1,280 pixels the planner spans the web card over two tracks, where the
        # grid's own columns would give it one: the refresh has the grid planned
        # before it reads a row, so the web's boxes are drawn after it as on the load
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self.page.set_viewport_size({"width": 1280, "height": 700})
        self._wall()
        web = self._node(_WEB)
        self.assertEqual(web.get_attribute("data-layout-span"), "2")
        loaded = self.page.evaluate(_DRAWN_ROWS)
        self._swap()
        # planned before the frame after the swap, which the page's clock holds back
        self.assertEqual(web.get_attribute("data-layout-span"), "2")
        self.assertEqual(self.page.evaluate(_DRAWN_ROWS), loaded)
        self.page.clock.run_for(100)
        self.assertEqual(self.page.evaluate(_DRAWN_ROWS), loaded)

    def test_the_frame_after_a_refresh_leaves_the_planned_grid_as_it_was(self):
        # the plan the refresh laid on the grid is the one its width selects, so the
        # planner's frame after the swap finds it there and writes nothing — at
        # 1,000 pixels, where the band leaves the count to the grid's own columns and
        # every card spans one, and at 1,280, where the web spans two of three
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        grid = self.page.locator("#status-grid .status-grid")
        for width, tracks, web in ((1000, None, "1"), (1280, "3", "2")):
            with self.subTest(width=width):
                if width != 1000:
                    self._resized_to(width)
                    self.page.clock.run_for(100)
                self._swap()
                self.page.evaluate(_WATCH_PLAN)
                self.page.clock.run_for(100)
                self.assertEqual(self.page.evaluate(_PLAN_WRITES), [])
                self.assertEqual(grid.get_attribute("data-layout-tracks"), tracks)
                span = self._node(_WEB).get_attribute("data-layout-span")
                self.assertEqual(span, web)

    def test_a_larger_root_font_reads_every_row_again(self):
        self._wall()
        self._swap()
        # the grid's width and gap held where they are, so the cards keep their
        # widths and no observer speaks: a larger font still changes what every row
        # needs, and the next refresh reads them all
        outer, inner = self.page.evaluate(
            "[document.getElementById('status-grid').getBoundingClientRect().width,"
            " document.querySelector('#status-grid .status-grid')"
            ".getBoundingClientRect().width]")
        self.page.add_style_tag(content=(
            f"#status-grid {{ width: {outer}px; }}"
            f" #status-grid .status-grid {{ width: {inner}px; gap: 16px; }}"))
        rows = self._shown_rows()
        self.page.evaluate("document.documentElement.style.fontSize = '20px'")
        self.assertEqual(self._reads(self._swap), rows)

    def _touch_taken_up(self) -> None:
        """The pointer turned coarse mid-page, as a touch screen taken up turns it,
        and the page told: a listener of the test's own, added after the page's,
        has heard the change."""
        page = self.page
        page.evaluate("""() => { window.__coarse = 0;
            matchMedia('(pointer: coarse)').addEventListener(
                'change', () => { window.__coarse += 1; }); }""")
        client = page.context.new_cdp_session(page)
        client.send("Emulation.setTouchEmulationEnabled",
                    {"enabled": True, "maxTouchPoints": 1})
        page.wait_for_function("window.__coarse > 0", timeout=5000)

    def test_a_coarse_pointer_reads_every_row_again_with_its_spacing(self):
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        self._swap()
        rows = self._shown_rows()
        # a touch screen taken up mid-page spaces the toolbars apart: every row is
        # read again at once, the toolbar's gap read anew
        self.assertEqual(self._reads(self._touch_taken_up), rows)
        self.assertTrue(self.page.evaluate("matchMedia('(pointer: coarse)').matches"))
        # and what the rows were read as under the mouse is forgotten: the next
        # refresh reads every row the server drew again
        self.assertEqual(self._reads(self._swap), rows)
        # at the window where folding every action gives the name its room only
        # with the touch screen's gaps credited, the state stays in the row
        self._narrow(_LONG_NAME, 700)
        read = self._as_read(_LONG_NAME)
        self.assertGreater(read["gap"], 3)
        excess = read["actions"] + (read["count"] - 1) * read["gap"] - 4
        self._narrow(_LONG_NAME, 700 - read["inside"] + read["need"] - excess)
        parts = self._parts(_LONG_NAME)
        self.assertEqual(parts["shown"], 0)
        self.assertFalse(parts["below"])


class HeadRowPhoneTests(_HeadRowCase):
    """The head's row on a phone of 375 pixels, under a coarse pointer."""

    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 375, "height": 667}, "device_scale_factor": 2,
        "is_mobile": True, "has_touch": True, "reduced_motion": "reduce"}

    def test_a_touch_screen_shows_the_buttons_always(self):
        # no pointer rests on a head there (`head_buttons: pointer`, ADR-0029)
        self._wall()
        for path in (_WEB, _DNS):
            with self.subTest(path=path):
                self.assertEqual(self._head(path).evaluate(_BAR), "1")

    def test_a_card_of_three_actions_keeps_its_name_whole(self):
        # names the plain theme's face holds on one line beside the row's controls
        self._choose(theme="plain")
        self.tree.upsert(_PHONE_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        page = self.page
        self.assertTrue(page.evaluate("matchMedia('(pointer: coarse)').matches"))
        for path in (_WEB, _PHONE_NAME):
            with self.subTest(path=path):
                parts = self._parts(path)
                # the icons, the actions and ⋯ after the name, the state ending the
                # row or on a line of its own beneath; the name whole; what does not
                # fit behind ⋯
                self.assertGreater(parts["folded"], 0)
                self.assertIsNotNone(parts["more"])
                self.assertEqual(parts["nameLines"], 1)
                self.assertTrue(self._on_one_line(parts, "name", "icons", "more"))
                for action in parts["actions"][:parts["shown"]]:
                    self.assertLess(parts["icons"]["right"], action["x"])
                    self.assertLess(action["right"], parts["more"]["x"] + 1)
                self.assertLess(parts["icons"]["right"], parts["more"]["x"])
                self.assertAlmostEqual(parts["state"]["right"], parts["head"]["right"],
                                       delta=3)
                if parts["below"]:
                    self.assertGreaterEqual(parts["state"]["y"],
                                            parts["icons"]["bottom"] - 1)
                else:
                    self.assertLess(parts["more"]["right"], parts["state"]["x"])
        # the long name has no room beside the state: its state is beneath; the
        # short one keeps it in the row
        self.assertTrue(self._parts(_PHONE_NAME)["below"])
        self.assertFalse(self._parts(_WEB)["below"])
        # under `card_status_line: below` the state alone takes the standing line,
        # and the actions get the room it had in the row
        before = self._parts(_WEB)["shown"]
        page.evaluate("document.body.dataset.lsCardState = 'below'")
        page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        parts = self._parts(_WEB)
        self.assertGreaterEqual(parts["state"]["y"], parts["icons"]["bottom"] - 1)
        self.assertTrue(self._on_one_line(parts, "name", "more", "icons"))
        self.assertGreater(parts["shown"], before)

    def test_the_squares_stand_apart_and_a_tap_in_a_gap_lands_on_one_of_them(self):
        self._wall()
        page = self.page
        head = self._head(_DNS)
        head.scroll_into_view_if_needed()
        squares = head.locator(".node-icons > .node-icon")
        boxes = [square.bounding_box() for square in squares.all()]
        self.assertGreaterEqual(len(boxes), 2)
        for left, right in pairwise(boxes):
            self.assertAlmostEqual(right["x"] - (left["x"] + left["width"]), 8,
                                   delta=0.5)
            # the taps meet in the middle of each gap
            middle = (left["x"] + left["width"] + right["x"]) / 2
            y = left["y"] + left["height"] / 2
            under = page.evaluate("([x, y]) => document.elementFromPoint(x, y)"
                                  ".closest('.node-icon') !== null", [middle, y])
            self.assertTrue(under, (middle, y))
        # and none reaches over the state word
        state = head.locator(".status-node__state").bounding_box()
        x = state["x"] + state["width"] - 2
        y = state["y"] + state["height"] / 2
        self.assertFalse(page.evaluate(
            "([x, y]) => document.elementFromPoint(x, y).closest('.node-icon')"
            " !== null", [x, y]))
        # the actions stand 8 apart too, their taps the same
        chips = [chip.bounding_box()
                 for chip in head.locator(".node-actions > a:not(.is-folded)").all()]
        for left, right in pairwise(chips):
            self.assertAlmostEqual(right["x"] - (left["x"] + left["width"]), 8,
                                   delta=0.5)

    def test_no_tap_reaches_past_the_toolbars_ends(self):
        # a tap at the toolbar's first square stops at its edge on the name's side,
        # and at its last on the title's — ⋯ where an action folds, the last action
        # where none does, the last icon where the node has no action — so that what
        # lies beside the toolbar stays the row's
        for actions in (_ACTIONS, ()):
            with self.subTest(actions=len(actions)), \
                    mock.patch.object(actions_module, "_actions", actions):
                self._wall()
                self._assert_taps_stop_at_the_ends(self._head(_DNS))
        # and where a head has no icon at all — a leaf's own page, the leaf with a pin
        # of its own — at its first action
        self.tree.set_maintenance(_FLAKY, "planned", set_by="pan",
                                  expires_at=_NOON + timedelta(days=1))
        self.page.goto(f"{self.base}/status{_FLAKY}")      # a leaf's page has no grid
        self.page.wait_for_selector(".node-frame .viewed-head")
        head = self.page.locator(".node-frame .viewed-head > .status-node__self")
        icons = head.locator(".node-icons")
        self.assertEqual(icons.evaluate("el => el.children.length"), 0)
        self._assert_taps_stop_at_the_ends(head)

    def _assert_taps_stop_at_the_ends(self, head: Any) -> None:
        """A tap two pixels past the first and the last square ``head``'s toolbar
        shows lands on none of its controls, and two pixels inside each on it."""
        head.scroll_into_view_if_needed()
        first, last = head.evaluate("""head => {
            const shown = Array.from(head.querySelectorAll(
                ':scope > .node-controls :is(.node-icon, .node-action)'))
                .filter(el => el.getBoundingClientRect().width > 1);
            const box = el => {
              const r = el.getBoundingClientRect();
              return {x: r.x, right: r.right, y: r.y + r.height / 2};
            };
            return [box(shown[0]), box(shown[shown.length - 1])];
        }""")
        on = ("([x, y]) => !!document.elementFromPoint(x, y)"
              ".closest('.node-icon, .node-action')")
        for x, y, inside in ((first["x"] - 2, first["y"], first["x"] + 2),
                             (last["right"] + 2, last["y"], last["right"] - 2)):
            self.assertFalse(self.page.evaluate(on, [x, y]), (x, y))
            self.assertTrue(self.page.evaluate(on, [inside, y]), (inside, y))

    def test_a_head_under_a_finger_wears_no_outline_and_a_press_its_wash(self):
        # a touch screen has no pointer to show the row first, and a finger lifted
        # leaves the hover behind on the row it tapped: no outline where
        # (hover: hover) does not match — the press still washes the row
        self._wall()
        self.assertFalse(self.page.evaluate("matchMedia('(hover: hover)').matches"))
        name = self._head(_DNS).locator('[data-control="toggle"]')
        self._point_at(name)
        self.assertTrue(self._head(_DNS).evaluate("h => h.matches(':hover')"))
        self.assertEqual(self._look(_DNS)["outline"], "none")
        self.assertAlmostEqual(self._pressed(name)["fill"][3], 0.12, delta=0.01)
        # and a chip the same
        self._point_at(self._chip(_API))
        self.assertTrue(self._chip(_API).evaluate("c => c.matches(':hover')"))
        self.assertEqual(self._chip_look(_API)["outline"], "none")
        self.assertAlmostEqual(self._chip_pressed(_API)["wash"][3], 0.12, delta=0.01)


#: A box whose state is long: a failure held back says how near it is to escalating,
#: beside its word.
_GATE = "/web/gateway"
#: A card whose state is long: its time says when it runs next.
_NEXT = "/nightly"

#: A head's state as drawn: its box and its parts', the lines its reading beside the
#: word stands on, the word's place where it is bare text — a box's — and the room the
#: head keeps for it.
_STATE_PARTS = """head => {
    const box = el => {
      if (!el) { return null; }
      const r = el.getBoundingClientRect();
      return {x: r.x, y: r.y, right: r.right, bottom: r.bottom, width: r.width,
              height: r.height};
    };
    const state = head.querySelector(
        ':scope > .status-card__state, :scope > .status-node__state');
    // the lines an element's contents stand on: a rect that starts below the line
    // before begins the next
    const lines = el => {
      if (!el) { return 0; }
      const range = document.createRange();
      range.selectNodeContents(el);
      const rects = Array.from(range.getClientRects())
          .filter(r => r.width > 0 && r.height > 0).sort((a, b) => a.top - b.top);
      let count = 0;
      let bottom = -Infinity;
      for (const r of rects) {
        if (r.top >= bottom - 1) { count += 1; bottom = r.bottom; }
        else { bottom = Math.max(bottom, r.bottom); }
      }
      return count;
    };
    const bare = Array.from(state.childNodes)
        .find(node => node.nodeType === 3 && node.textContent.trim());
    let word = box(state.querySelector('.status-word'));
    if (!word && bare) {
      const range = document.createRange();
      range.selectNodeContents(bare);
      word = box(range);
    }
    const next = head.nextElementSibling;
    return {head: box(head), state: box(state),
            name: box(head.querySelector('[data-control="toggle"]')),
            time: box(state.querySelector('.status-card__time')), word: word,
            wordLines: lines(state.querySelector('.status-word')),
            suffix: box(state.querySelector('.status-reported')),
            suffixLines: lines(state.querySelector('.status-reported')),
            next: next ? box(next) : null,
            room: head.style.getPropertyValue('--ls-state-room'),
            below: head.classList.contains('is-state-below'),
            beside: head.classList.contains('is-state-beside')};
}"""


class StateBreakTests(_HeadRowCase):
    """A state wider than the line it has to itself breaks between its parts, right-
    aligned, and inside one only where that part alone is wider than the line, and its
    head makes room for every line it takes: github's *01:08 → 01:23 error · 1 of 2 to
    escalate* ran out of its box at the left."""

    #: The web tier's boxes open, the gateway's among them: a failure its damping
    #: counter still holds back spends no failure budget, so beneath chips it would
    #: stay one (ADR-0128).
    estate_look = _WEB_BUILT_IN

    def setUp(self) -> None:
        super().setUp()
        for code in (StatusCode.OK, StatusCode.ERROR):
            self.tree.upsert(_GATE, code, f"it reads {code.name.lower()}",
                             escalate_after=2)

    def _state_of(self, path: str) -> dict[str, Any]:
        return self._head(path).evaluate(_STATE_PARTS)

    def _assert_inside(self, parts: dict[str, Any]) -> None:
        """The state within its head, at its right, beneath its row, and clear of
        what follows the head."""
        state, head = parts["state"], parts["head"]
        self.assertGreaterEqual(state["x"], head["x"] - 0.5)
        self.assertAlmostEqual(state["right"], head["right"], delta=2.5)
        self.assertLessEqual(state["bottom"], head["bottom"] + 0.5)
        self.assertGreaterEqual(state["y"], parts["name"]["bottom"] - 1)
        if parts["next"]:
            self.assertGreaterEqual(parts["next"]["y"], state["bottom"] - 0.5)

    def test_a_state_wider_than_its_line_breaks_between_its_parts(self):
        self._wall()
        self.page.mouse.move(2, 2)
        # with room enough: a line of its own, whole, and no more room asked
        self._narrow(_WEB, 360)
        whole = self._state_of(_GATE)
        self.assertTrue(whole["below"])
        self.assertEqual(whole["room"], "")
        self._assert_inside(whole)
        line = whole["state"]["height"]
        # narrower than the state: the reading beside the word takes a line of its
        # own, whole, beneath the time and the word, all at the right
        for width in (260, 220):
            self._narrow(_WEB, width)
            parts = self._state_of(_GATE)
            with self.subTest(width=width):
                self.assertGreater(parts["state"]["height"], 1.5 * line)
                self.assertNotEqual(parts["room"], "")
                self._assert_inside(parts)
                self.assertGreater(parts["suffix"]["y"], parts["time"]["y"] + line / 2)
                self.assertEqual(parts["suffixLines"], 1)
                self.assertAlmostEqual(parts["suffix"]["right"], parts["head"]["right"],
                                       delta=2.5)
                self.assertLess(abs(parts["word"]["y"] - parts["time"]["y"]), line / 2)
        # a part alone wider than the line breaks at its own spaces, within it
        self._narrow(_WEB, 170)
        narrowest = self._state_of(_GATE)
        self.assertGreater(narrowest["suffixLines"], 1)
        self._assert_inside(narrowest)
        self.assertGreaterEqual(narrowest["suffix"]["x"], narrowest["head"]["x"] - 0.5)
        # and with room again, one line once more
        self._narrow(_WEB, 360)
        self.assertEqual(self._state_of(_GATE), whole)

    def test_a_cards_time_and_word_part_where_even_they_do_not_fit(self):
        # a card's cue and word are one part, and its time another
        self.tree.upsert(_NEXT, StatusCode.ERROR, "the run failed")
        self.tree.set_run_facts(_NEXT, wall_seconds=12.0,
                                next_run_at=_NOON + timedelta(minutes=5))
        self._wall()
        self.page.mouse.move(2, 2)
        self._narrow(_NEXT, 700)
        whole = self._state_of(_NEXT)
        line = whole["state"]["height"]
        self.assertIn("\u2192", self._head(_NEXT).locator(
            ".status-card__time").inner_text())
        # on one line, the time its gap before the cue and the word, as ever
        self.assertAlmostEqual(whole["word"]["y"], whole["time"]["y"], delta=line / 2)
        self.assertGreaterEqual(whole["word"]["x"] - whole["time"]["right"], 5)
        # as narrow as the time and the word no longer share a line
        self._narrow(_NEXT, whole["time"]["width"] + whole["word"]["width"] / 2 + 40)
        parts = self._state_of(_NEXT)
        self.assertGreater(parts["word"]["y"], parts["time"]["y"] + line / 2)
        self.assertEqual(parts["wordLines"], 1)
        self._assert_inside(parts)
        for part in ("time", "word"):
            self.assertAlmostEqual(parts[part]["right"], parts["head"]["right"],
                                   delta=2.5)
        # and under `card_status_line: below` the standing line makes the same room
        self.page.evaluate("document.body.dataset.lsCardState = 'below'")
        self.page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        below = self._state_of(_NEXT)
        self.assertNotEqual(below["room"], "")
        self._assert_inside(below)

    def test_a_closed_cards_state_breaks_between_its_parts_too(self):
        self.tree.upsert(_NEXT, StatusCode.ERROR, "the run failed")
        self.tree.set_run_facts(_NEXT, wall_seconds=12.0,
                                next_run_at=_NOON + timedelta(minutes=5))
        self._wall()
        self.page.click('.ls-band__mode[data-mode="closed"]')
        self._narrow(_NEXT, 700)
        whole = self._state_of(_NEXT)
        line = whole["state"]["height"]
        self._narrow(_NEXT, whole["time"]["width"] + whole["word"]["width"] / 2 + 40)
        parts = self._state_of(_NEXT)
        self.assertGreater(parts["word"]["y"], parts["time"]["y"] + line / 2)
        state, head = parts["state"], parts["head"]
        self.assertGreaterEqual(state["x"], head["x"] - 0.5)
        self.assertLessEqual(state["right"], head["right"] + 0.5)
        self.assertLessEqual(state["bottom"], head["bottom"] + 0.5)
        self.assertAlmostEqual(parts["word"]["right"], state["right"], delta=1)

    def test_a_closed_cards_state_keeps_a_line_of_its_own_under_below(self):
        # under `card_status_line: below` a closed card's state takes its line in the
        # head's flow, beneath the name, at the right, and as many lines as it breaks
        # into: the room the card had open goes with its opening
        self.tree.upsert(_NEXT, StatusCode.ERROR, "the run failed")
        self.tree.set_run_facts(_NEXT, wall_seconds=12.0,
                                next_run_at=_NOON + timedelta(minutes=5))
        self._wall()
        self.page.mouse.move(2, 2)
        self.page.evaluate("document.body.dataset.lsCardState = 'below'")
        self._narrow(_NEXT, 700)
        whole = self._state_of(_NEXT)
        line = whole["state"]["height"]
        narrow = whole["time"]["width"] + whole["word"]["width"] / 2 + 40
        self._narrow(_NEXT, narrow)
        self.assertNotEqual(self._state_of(_NEXT)["room"], "")
        self.page.click('.ls-band__mode[data-mode="closed"]')
        for width in (700, narrow):
            self._narrow(_NEXT, width)
            parts = self._state_of(_NEXT)
            state, head = parts["state"], parts["head"]
            with self.subTest(width=width):
                self.assertEqual(parts["room"], "")
                self.assertGreaterEqual(state["y"], parts["name"]["bottom"] - 1)
                self.assertGreaterEqual(state["x"], head["x"] - 0.5)
                self.assertAlmostEqual(state["bottom"], head["bottom"], delta=1)
                self.assertAlmostEqual(parts["word"]["right"], head["right"],
                                       delta=2.5)
        self.assertGreater(parts["word"]["y"], parts["time"]["y"] + line / 2)

    def test_the_room_holds_through_a_refresh(self):
        # the card drawn narrow by a stylesheet, which a refresh keeps: once a refresh
        # has read the row as the server drew it, the next draws it from what was
        # read, its room with it
        self._wall()
        self.page.add_style_tag(content=(
            f'.status-card[data-node="{_WEB}"] {{ width: 220px; min-width: 0;'
            " justify-self: start; }"))
        self._swap()
        drawn = self._state_of(_GATE)
        self.assertNotEqual(drawn["room"], "")
        self.page.evaluate(_WATCH_READS)
        self._swap()
        self.assertEqual(self.page.evaluate(_READS), [])
        self.assertEqual(self._state_of(_GATE), drawn)
        # and when the page reads every row again, as a resize does
        self.page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        self.assertEqual(self._state_of(_GATE), drawn)

    def test_the_stale_mark_breaks_only_where_it_alone_is_wider_than_the_line(self):
        # a reading past its tolerance says so first, in a mark of its own: on a line
        # too narrow for the state the mark keeps its words together, and on one
        # narrower than the mark alone it breaks at its spaces, within the box
        self.tree.upsert(_CDN, StatusCode.OK, "served", frequency_seconds=60)
        self.server_now = _NOON + timedelta(hours=2)
        self._wall()
        self.page.mouse.move(2, 2)
        self._narrow(_WEB, 220)
        mark = self._head(_CDN).locator(":scope > .status-node__state > .status-stale")
        self.assertIn("ago", mark.inner_text().lower())
        self.assertEqual(mark.evaluate(_LINES), 1)
        parts = self._state_of(_CDN)
        self._assert_inside(parts)
        box = mark.bounding_box()
        assert box is not None
        self._narrow(_WEB, 220 - (parts["head"]["width"] - box["width"]) - 8)
        self.assertEqual(mark.evaluate(_LINES), 2)
        self._assert_inside(self._state_of(_CDN))


#: What a surface wears, as the browser computes it: its shadow, its ink and its words'
#: halo; and a token resolved to the color the browser paints it as.
_LOOK = """selector => {
    const element = document.querySelector(selector);
    if (!element) return null;
    const style = getComputedStyle(element);
    return {shadow: style.boxShadow, color: style.color, halo: style.textShadow};
}"""
_RESOLVED = """token => {
    const probe = document.createElement('span');
    probe.style.color = `var(${token})`;
    document.body.appendChild(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
}"""


_BAR = "head => getComputedStyle(head.querySelector(':scope > .node-controls')).opacity"


class PointerHeadTests(_HeadRowCase):
    """The head's buttons under the look `head_buttons: pointer`, the library's
    (ADR-0029): seen while the pointer is on the head, the keyboard's focus is in it or
    its menu is open; taking no room in the row, the title right after the name and the
    buttons over it when shown, but where the name gives way."""

    def test_the_title_keeps_to_the_name_and_the_buttons_lie_over_it(self):
        # at rest the toolbar has no width in the row and the title follows the name;
        # under the pointer the squares stand over the title's start on the card's
        # own fill, so what they cover does not read through, and nothing moves
        self.tree.upsert(_QUEUE, StatusCode.ERROR, ["the queue's last job failed"])
        self._wall()
        self.page.mouse.move(2, 2)
        rest = self._parts(_WEB)
        self.assertEqual(rest["toolbar"]["width"], 0)
        self.assertLess(rest["title"]["x"] - rest["name"]["right"], 16)
        self.assertLess(rest["icons"]["x"], rest["title"]["right"])
        self.assertGreater(rest["icons"]["right"], rest["title"]["x"])
        self._point_at(self._head(_WEB).locator('[data-control="toggle"]'))
        self.assertEqual(self._head(_WEB).evaluate(_BAR), "1")
        shown = self._parts(_WEB)
        for side in ("x", "y", "width", "height"):
            place = shown["title"][side] - (shown["head"][side] if side in "xy" else 0)
            was = rest["title"][side] - (rest["head"][side] if side in "xy" else 0)
            self.assertAlmostEqual(place, was, delta=0.5, msg=f"title {side}")
        on_top = self._head(_WEB).evaluate("""head => {
            const icon = head.querySelector('.node-icons > .node-icon');
            const r = icon.getBoundingClientRect();
            const hit = document.elementFromPoint(r.x + r.width / 2,
                                                  r.y + r.height / 2);
            const fill = el => getComputedStyle(el).backgroundColor;
            return {hit: !!hit && hit.closest('.node-icon') === icon,
                    icons: fill(head.querySelector('.node-icons')),
                    card: fill(head.closest('.status-card'))};
        }""")
        self.assertTrue(on_top["hit"])
        self.assertEqual(on_top["icons"], on_top["card"])
        # where the name gives way, the toolbar keeps its room, so that the name
        # breaks beside it rather than the shown buttons running past the row
        _one, broken = self._breaking(_QUEUE, _WEB)
        self.assertGreater(broken["toolbar"]["width"], 0)
        self.assertTrue(self._head(_QUEUE).evaluate(
            "head => head.classList.contains('is-crowded')"))

    def test_a_click_leaves_no_buttons_shown_once_the_pointer_leaves(self):
        # a click's focus stays where it landed, and the buttons showed for any
        # focus in the head, so they stood shown after the pointer left: they show for
        # the keyboard's focus, as they always said
        self._wall()
        chips = self._head(_WEB).locator('[data-control="chips"]')
        self._point_at(chips)
        chips.click()
        self.assertTrue(self._head(_WEB).evaluate(
            "head => head.matches(':focus-within')"))
        self.page.mouse.move(2, 2)
        self.assertEqual(self._head(_WEB).evaluate(_BAR), "0")
        # the keyboard moving along the toolbar shows them again
        self.page.keyboard.press("ArrowLeft")
        self.assertEqual(self._head(_WEB).evaluate(_BAR), "1")

    def test_the_buttons_show_under_the_pointer_and_nothing_moves(self):
        self._wall()
        self.page.mouse.move(2, 2)
        rest = self._parts(_DNS)
        self.assertEqual(self._head(_DNS).evaluate(_BAR), "0")
        self.assertEqual(self._head(_WEB).evaluate(_BAR), "0")
        # anywhere on the head, its own buttons and no other head's
        self._point_at(self._head(_DNS).locator(":scope > .status-node__state"))
        self.assertEqual(self._head(_DNS).evaluate(_BAR), "1")
        self.assertEqual(self._head(_WEB).evaluate(_BAR), "0")
        shown = self._parts(_DNS)
        for part in ("name", "icons", "state"):
            for side in ("x", "y", "width", "height"):
                place = shown[part][side] - (shown["head"][side] if side in "xy" else 0)
                was = rest[part][side] - (rest["head"][side] if side in "xy" else 0)
                self.assertAlmostEqual(place, was, delta=0.5, msg=f"{part} {side}")
        # the keyboard's focus in the head shows them too, the name's as a button's
        self.page.mouse.move(2, 2)
        self._head(_DNS).locator('[data-control="toggle"]').focus()
        self.assertEqual(self._head(_DNS).evaluate(_BAR), "1")
        self.page.keyboard.press("Tab")
        self.assertEqual(self._head(_DNS).evaluate(_BAR), "1")
        self.assertEqual(self.page.evaluate(
            "document.activeElement.closest('.node-controls') !== null"), True)

    def test_an_open_menu_keeps_its_buttons_shown(self):
        self._wall()
        self._narrow(_WEB, 700)
        wide = self._as_read(_WEB)
        self._overflowing(_WEB, wide["widths"][-1] + wide["gap"] + 4)
        more = self._head(_WEB).locator(".node-more")
        more.click()
        self.assertEqual(more.get_attribute("aria-expanded"), "true")
        self.page.mouse.move(2, 2)
        self.page.evaluate("document.activeElement.blur()")
        self.assertEqual(self._head(_WEB).evaluate(_BAR), "1")
        self.page.keyboard.press("Escape")


class LineHeadTests(_HeadRowCase):
    """The head's buttons under the look `head_buttons: line` (ADR-0029): a line of
    their own beneath the row, from under the name."""

    look = "line"

    def test_the_buttons_have_a_line_beneath_the_row(self):
        self._wall()
        self.page.mouse.move(2, 2)
        for path in (_WEB, _DNS):
            parts = self._parts(path)
            with self.subTest(path=path):
                self.assertEqual(self._head(path).evaluate(_BAR), "1")
                self.assertTrue(self._on_one_line(parts, "name", "state"))
                self.assertAlmostEqual(parts["state"]["right"], parts["head"]["right"],
                                       delta=3)
                self.assertGreaterEqual(parts["icons"]["y"],
                                        parts["name"]["bottom"] - 1)
                self.assertTrue(self._on_one_line(parts, "icons") and abs(
                    parts["icons"]["y"] - parts["actions"][0]["y"]) < 8)
                # from under the name, past a box's cue, ↗ the first
                self.assertAlmostEqual(parts["page"]["x"], parts["name"]["x"],
                                       delta=4)
                self.assertLess(parts["icons"]["right"], parts["actions"][0]["x"])
                self.assertEqual((parts["shown"], parts["folded"], parts["more"]),
                                 (3, 0, None))
                self.assertFalse(parts["below"])
                # the state's words clear of the room the title may fill, by 0.4em
                head = self._head(path)
                middle = head.locator(":scope > .status-head__middle").bounding_box()
                padding = head.locator(
                    ":scope > .status-card__state, :scope > .status-node__state"
                ).evaluate("el => parseFloat(getComputedStyle(el).paddingLeft)")
                self.assertGreaterEqual(
                    parts["state"]["x"] + padding - (middle["x"] + middle["width"]), 5)

    def test_a_narrow_row_wraps_its_state_beneath_and_folds_nothing(self):
        # a name the row holds, but not with its state beside it
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        self._narrow(_LONG_NAME, 700)
        wide = self._parts(_LONG_NAME)
        # the row as wide as the name, and half the state, beside its padding
        self._narrow(_LONG_NAME, wide["name"]["right"] - wide["head"]["x"]
                     + wide["state"]["width"] / 2 + 24)
        parts = self._parts(_LONG_NAME)
        self.assertEqual(parts["nameLines"], 1)
        self.assertEqual((parts["folded"], parts["more"]), (0, None))
        self.assertGreaterEqual(parts["state"]["y"], parts["name"]["bottom"] - 1)
        self.assertAlmostEqual(parts["state"]["right"], parts["head"]["right"],
                               delta=3)
        self.assertGreaterEqual(parts["actions"][0]["y"], parts["state"]["bottom"] - 1)
        self.assertFalse(parts["below"])

    def test_a_state_wider_than_its_line_stays_in_the_box(self):
        # the row wraps the state beneath at the right, and where even that line is
        # narrower than the state, it breaks between its parts there too — in the
        # gateway's box, open where its level is the built-in look's, as
        # StateBreakTests draws it
        self.estate_look = _WEB_BUILT_IN
        for code in (StatusCode.OK, StatusCode.ERROR):
            self.tree.upsert(_GATE, code, f"it reads {code.name.lower()}",
                             escalate_after=2)
        self._wall()
        self.page.mouse.move(2, 2)
        self._narrow(_WEB, 220)
        parts = self._head(_GATE).evaluate(_STATE_PARTS)
        state, head = parts["state"], parts["head"]
        self.assertGreaterEqual(state["x"], head["x"] - 0.5)
        self.assertLessEqual(state["right"], head["right"] + 0.5)
        self.assertGreater(parts["suffix"]["y"], parts["time"]["y"] + 4)
        self.assertEqual(parts["suffixLines"], 1)

    def test_under_below_a_cards_state_takes_the_buttons_line(self):
        # `card_status_line: below` gives a card's state a second line, which here
        # is the buttons': at its right, and no third line for it
        self.tree.upsert(_LONG_NAME, StatusCode.ERROR, ["the nightly run failed"])
        self._wall()
        self.page.mouse.move(2, 2)
        drawn = {path: self._parts(path) for path in (_NAS, _WEB)}
        self.page.evaluate("document.body.dataset.lsCardState = 'below'")
        self.page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        for path in (_NAS, _WEB):
            parts = self._parts(path)
            state, icons = parts["state"], parts["icons"]
            with self.subTest(path=path):
                self.assertAlmostEqual(state["y"] + state["height"] / 2,
                                       icons["y"] + icons["height"] / 2, delta=2)
                self.assertGreater(state["x"], icons["right"])
                self.assertAlmostEqual(state["right"], parts["head"]["right"], delta=3)
                # the head as tall as without the deployment's word, the buttons'
                # line where it was
                was = drawn[path]
                self.assertAlmostEqual(parts["head"]["height"], was["head"]["height"],
                                       delta=0.5)
                self.assertAlmostEqual(icons["y"] - parts["head"]["y"],
                                       was["icons"]["y"] - was["head"]["y"], delta=0.5)
        # where that line has no room for it, it wraps beneath, at the right
        self._narrow(_LONG_NAME, 300)
        parts = self._parts(_LONG_NAME)
        self.assertGreaterEqual(parts["state"]["y"], parts["icons"]["bottom"] - 1)
        self.assertAlmostEqual(parts["state"]["right"], parts["head"]["right"], delta=3)
        self.assertLessEqual(parts["state"]["bottom"], parts["head"]["bottom"] + 1)


class _NameOpensThePage:
    """What the looks `name` and `pointer-name` share (ADR-0029): the pointer's click
    on an open head's name opens the node's page, the keyboard's Enter and Space on it
    open and close the node, and ↗, the toolbar's first control, is the keyboard's
    alone. A mixin of the two classes below, so that each look is held to it."""

    def test_the_pointer_opens_the_page_by_the_name_and_the_keyboard_the_node(self):
        self._wall()
        name = self._head(_DNS).locator('[data-control="toggle"]')
        # the keyboard's Enter and Space on the name open and close the node
        name.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(self._state(_DNS), "closed")
        self._chip(_DNS).click()                    # a chip opens by the pointer
        self.assertEqual(self._state(_DNS), "open")
        name.focus()
        self.page.keyboard.press(" ")
        self.assertEqual(self._state(_DNS), "closed")
        self._chip(_DNS).click()
        # the rest of the row closes the node under the pointer, as ever
        self._head(_DNS).locator(":scope > .status-node__state").click()
        self.assertEqual(self._state(_DNS), "closed")
        self._chip(_DNS).click()
        # a closed card's name opens the card
        self._head(_NAS).locator(":scope > .status-card__state").click()
        self.assertEqual(self._state(_NAS), "closed")
        self._head(_NAS).locator(".status-card__name").click()
        self.assertEqual(self._state(_NAS), "open")
        # and the pointer's click on an open head's name opens the node's page
        with self.page.expect_navigation():
            name.click()
        self.assertTrue(self.page.url.endswith(f"/status{_DNS}"), self.page.url)

    def test_the_arrow_shows_when_the_keyboard_reaches_it(self):
        # ↗ is the toolbar's first control: out of sight, taking no room, until the
        # keyboard's Tab from the name lands on it
        self._wall()
        arrow = self._head(_DNS).locator('.node-icons > [data-control="page"]')
        self.assertLessEqual(arrow.bounding_box()["width"], 1)
        self._head(_DNS).locator('[data-control="toggle"]').focus()
        self.page.keyboard.press("Tab")
        self.assertEqual(self._focused(), "page")
        self.assertGreater(arrow.bounding_box()["width"], 20)

    def test_the_name_says_it_is_a_link_under_the_pointer(self):
        self._wall()
        name = self._head(_DNS).locator('[data-control="toggle"]')
        self._point_at(name)
        self.assertEqual(name.evaluate("n => getComputedStyle(n).textDecorationLine"),
                         "underline")
        on_name = self._look(_DNS)
        self._point_at(self._head(_DNS).locator(":scope > .status-node__state"))
        on_row = self._look(_DNS)
        self.assertEqual(on_name["fill"][3], 0)
        self.assertGreater(on_row["fill"][3], 0)
        self.assertEqual(name.evaluate("n => getComputedStyle(n).textDecorationLine"),
                         "none")


class NameHeadTests(_NameOpensThePage, _HeadRowCase):
    """The head's buttons under the look `head_buttons: name` (ADR-0029): at the
    row's end, the pointer's click on the name opening the node's page and ↗ the
    keyboard's alone."""

    look = "name"

    def test_the_title_and_the_state_follow_the_name_and_the_buttons_end_the_row(self):
        self._wall()
        self.page.mouse.move(2, 2)
        parts = self._parts(_DNS)
        self.assertEqual(self._head(_DNS).evaluate(_BAR), "1")
        # the head's icons first, then the node's actions, which end the row
        self.assertLess(parts["state"]["right"], parts["icons"]["x"])
        self.assertLess(parts["icons"]["right"], parts["actions"][0]["x"])
        self.assertAlmostEqual(parts["actions"][-1]["right"], parts["head"]["right"],
                               delta=3)
        self.assertTrue(self._on_one_line(parts, "name", "state", "icons"))
        # ↗ out of sight, and no room taken in the row
        self.assertLessEqual(parts["page"]["width"], 1)

    def test_a_state_that_would_touch_the_buttons_keeps_a_line_of_its_own(self):
        # at the row's end the buttons stand above the state's place beside the
        # name's last line: where they reach down to it, the state keeps its own line
        self._choose(theme="plain")
        self.tree.upsert(_QUEUE, StatusCode.ERROR, ["the queue's last job failed"])
        self._wall()
        _one, two = self._breaking(_QUEUE, _WEB)
        self.assertTrue(two["beside"])
        self._head(_QUEUE).evaluate(
            "head => { head.querySelector('.node-actions').style.minHeight ="
            " head.getBoundingClientRect().height + 'px'; }")
        self.page.evaluate("window.lsTree.apply(document.getElementById('status-grid'))")
        parts = self._parts(_QUEUE)
        self.assertEqual(parts["nameLines"], 2)
        self.assertTrue(parts["below"])
        self.assertFalse(parts["beside"])


class PointerNameHeadTests(_NameOpensThePage, _HeadRowCase):
    """The head's buttons under the look `head_buttons: pointer-name` (ADR-0029): where
    `pointer` puts them, right after the name and shown under the pointer, without ↗ —
    the name is the link to the node's page, and the rest of the head opens and closes
    the node."""

    look = "pointer-name"

    def test_the_buttons_follow_the_name_without_the_arrow_and_nothing_moves(self):
        self._wall()
        self.page.mouse.move(2, 2)
        rest = self._parts(_DNS)
        self.assertEqual(self._head(_DNS).evaluate(_BAR), "0")
        # ↗ takes no room, so the first square after the name is the next of the
        # head's icons, then the node's actions, over the title, and the state
        self.assertLessEqual(rest["page"]["width"], 1)
        self.assertAlmostEqual(rest["icons"]["x"], rest["name"]["right"], delta=8)
        self.assertGreater(rest["icons"]["width"], 20)
        self.assertLess(rest["icons"]["right"], rest["actions"][0]["x"])
        self.assertLess(rest["actions"][-1]["right"], rest["state"]["x"])
        self.assertAlmostEqual(rest["state"]["right"], rest["head"]["right"], delta=3)
        self.assertTrue(self._on_one_line(rest, "name", "icons", "state"))
        # under the pointer they show, and nothing moves
        self._point_at(self._head(_DNS).locator(":scope > .status-node__state"))
        self.assertEqual(self._head(_DNS).evaluate(_BAR), "1")
        shown = self._parts(_DNS)
        for part in ("name", "icons", "state"):
            for side in ("x", "y", "width", "height"):
                place = shown[part][side] - (shown["head"][side] if side in "xy" else 0)
                was = rest[part][side] - (rest["head"][side] if side in "xy" else 0)
                self.assertAlmostEqual(place, was, delta=0.5, msg=f"{part} {side}")


class CyberpunkCulpritTests(_BrowserCase):
    """In cyberpunk a culprit is a neon tube — every vivid surface ringed and glowing
    in its state's neon, the ink its state's words wear in the theme, its words
    white-hot and haloed in it — and a dimmed box is none (ADR-0028)."""

    def setUp(self) -> None:
        super().setUp()
        self.context.add_cookies([{"name": "ls_prefs", "url": self.base,
                                   "value": "theme=cyberpunk"}])
        # a culprit of every kind: a failing box, a warning's, a container's own pin
        # and the scheduler's heartbeat
        self.tree.set_maintenance(f"{_NAS}/alpha", "a shelf swap", set_by="lex",
                                  expires_at=_NOON + timedelta(days=2))
        self.tree.upsert(HEARTBEAT_PATH, StatusCode.ERROR,
                         "the scheduler has not run for four minutes")

    def _look(self, selector: str) -> dict[str, str]:
        look = self.page.evaluate(_LOOK, selector)
        self.assertIsNotNone(look, f"nothing at {selector}")
        return look

    def _assert_tube(self, surface: str, words: tuple[str, ...], state: str) -> None:
        neon = self.page.evaluate(_RESOLVED, f"--ls-tint-{state}-ink")
        ink = self.page.evaluate(_RESOLVED, f"--ls-{state}-ink")
        look = self._look(surface)
        with self.subTest(surface=surface):
            self.assertTrue(look["shadow"].startswith(f"{neon} 0px 0px 0px 1px"),
                            look["shadow"])
            self.assertIn(" inset", look["shadow"])
        for word in words:
            seen = self._look(f"{surface} > {word}")
            with self.subTest(surface=surface, word=word):
                self.assertEqual(seen["color"], ink)
                self.assertIn(neon, seen["halo"])

    def _box(self, path: str) -> str:
        return f'.tree-node[data-node="{path}"] > .tree-hold > .tree-box'

    def test_every_failing_box_and_the_heartbeat_are_tubes(self):
        self._wall()
        name = ".status-node__self > .status-node__name"
        state = ".status-node__self > .status-node__state"
        self._assert_tube(self._box(_FLAKY), (name, state), "error")
        self._assert_tube(self._box(_DNS), (name, state), "warn")
        self._assert_tube(self._box(f"{_NAS}/alpha"), (name, state), "maintenance")
        self._assert_tube(".ls-strip", (".ls-strip__name", ".ls-strip__state"), "error")

    def test_a_failing_card_a_closed_card_and_a_failing_chip_are_tubes(self):
        # a node's page draws its failing children as cards
        self._wall(f"/status{_WEB}")
        card = f'.status-card.tree-node[data-node="{_FLAKY}"]'
        name = ".status-card__head > .status-card__name"
        state = ".status-card__head > .status-card__state"
        self._assert_tube(card, (name, state), "error")
        # the wall closed, its failing cards closed with it
        self._wall()
        self.page.click('.ls-band__mode[data-mode="closed"]')
        self.assertEqual(self._state(_NAS), "closed")
        self._assert_tube(f'.status-card.tree-node[data-node="{_NAS}"]', (name, state),
                          "error")
        # and a failing box closed to its chip
        self.page.click('.ls-band__mode[data-mode="open"]')
        self._head(_FLAKY).locator(".status-node__name").click()
        self.assertEqual(self._state(_FLAKY), "closed")
        self._assert_tube(f'.tree-node[data-node="{_FLAKY}"] > .tree-chip',
                          (".tree-chip__name",), "error")

    def test_a_dimmed_card_is_no_tube(self):
        # the web card rolls its children's error up, dimmed: no tube, no halo
        self._wall()
        neon = self.page.evaluate(_RESOLVED, "--ls-tint-error-ink")
        card = self._look(f'.status-card.tree-node[data-node="{_WEB}"]')
        self.assertNotIn(neon, card["shadow"])
        self.assertNotIn("inset", card["shadow"])
        name = self._look(f'.status-card.tree-node[data-node="{_WEB}"]'
                          " > .status-card__head > .status-card__name")
        self.assertEqual(name["halo"], "none")

    def test_the_tube_is_cyberpunks_alone(self):
        self.context.add_cookies([{"name": "ls_prefs", "url": self.base,
                                   "value": "theme=plain"}])
        self._wall()
        box = self._look(self._box(_FLAKY))
        self.assertNotIn("inset", box["shadow"])
        name = self._look(f"{self._box(_FLAKY)} > .status-node__self"
                          " > .status-node__name")
        self.assertEqual(name["halo"], "none")


_FILL = """selector => {
    const element = document.querySelector(selector);
    return element ? getComputedStyle(element).backgroundColor : null;
}"""


class SteppedFillTests(_BrowserCase):
    """Every other level of box steps its pale fill (ADR-0028): a card's own boxes step,
    the boxes in them step back, so a box stands apart from the box around it — a
    failing host's in its failing card as a healthy one's in its healthy box — while a
    culprit keeps its vivid fill; in the library's theme and the plain one."""

    def _fill(self, selector: str) -> str:
        fill = self.page.evaluate(_FILL, selector)
        self.assertIsNotNone(fill, f"nothing at {selector}")
        return fill

    @staticmethod
    def _box(path: str) -> str:
        return f'.tree-node[data-node="{path}"] > .tree-hold > .tree-box'

    @staticmethod
    def _card(path: str) -> str:
        return f'.status-card.tree-node[data-node="{path}"]'

    def test_a_cards_boxes_step_and_the_boxes_in_them_step_back(self):
        for theme in ("cyberpunk", "plain"):
            with self.subTest(theme=theme):
                self.context.add_cookies([looks(self.base, theme=theme)])
                self._wall()
                self.page.click('.ls-band__mode[data-mode="open"]')
                card = self._fill(self._card(_DEEP))
                self.assertNotEqual(self._fill(self._box(f"{_DEEP}/a")), card)
                self.assertEqual(self._fill(self._box(_DEEP_LEAF)), card)
                # a failing box in its failing card
                self.assertNotEqual(self._fill(self._box(f"{_NAS}/zeta")),
                                    self._fill(self._card(_NAS)))
                # a culprit keeps its vivid fill wherever it stands
                self.assertEqual(self._fill(self._box(_FLAKY)),
                                 self.page.evaluate(_RESOLVED, "--ls-error"))

    def test_a_nodes_page_counts_its_levels_from_its_cards(self):
        # on the deep card's page its children are the cards, so their boxes step
        self._wall(f"/status{_DEEP}")
        self.page.click('.ls-band__mode[data-mode="open"]')
        self.assertNotEqual(self._fill(self._box(_DEEP_LEAF)),
                            self._fill(self._card(f"{_DEEP}/a")))

    def test_a_chip_steps_with_its_level(self):
        # A chip in a card steps as the card's own boxes do, its words with it, and a
        # chip in a stepped box does not, so a chip stands apart from the box it stands
        # in; a failing chip is vivid and never steps
        for theme in ("cyberpunk", "plain"):
            with self.subTest(theme=theme):
                self.context.add_cookies([looks(self.base, theme=theme)])
                self._wall()
                # quiet, a chip in the web card and a box in the nas card, each a
                # card's own
                chip = self._paint(self._chip(_API))
                box = self._paint(self.page.locator(self._box(f"{_NAS}/alpha")))
                self.assertEqual(chip, box)
                # and a chip in that box, a level further, as the healthy card
                inner = self._paint(self._chip(f"{_NAS}/alpha/probe"))
                self.assertNotEqual(inner["fill"], box["fill"])
                self.assertEqual(inner["fill"], self._fill(self._card(_DEEP)))
                # a failing chip in a card: closed, as vivid as where nothing steps
                self._head(_FLAKY).locator(".status-node__state").click()
                flaky = self._chip(_FLAKY)
                vivid = self._paint(flaky)
                flaky.evaluate(
                    "chip => chip.parentElement.classList.remove('is-stepped')")
                self.assertEqual(vivid, self._paint(flaky))
                flaky.click()       # open again, as the next theme's wall starts

    @staticmethod
    def _paint(element: Any) -> dict[str, str]:
        """What ``element`` is filled with and the color its words take."""
        return element.evaluate("""el => {
            const style = getComputedStyle(el);
            return {fill: style.backgroundColor, ink: style.color};
        }""")


class KioskTests(_BrowserCase):
    """On the kiosk a tap opens and closes a node, and no head carries icons."""

    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1000, "height": 700}, "has_touch": True,
        "reduced_motion": "reduce"}

    def setUp(self) -> None:
        super().setUp()
        self.context.add_cookies([{"name": "ls_prefs", "url": self.base,
                                   "value": "layout=kiosk"}])

    def test_a_tap_toggles_and_no_head_carries_icons(self):
        self._wall()
        self.assertEqual(self.page.locator(".node-icons").count(), 0)
        self.assertEqual(self.page.locator(".ls-band__modes").count(), 0)
        self._chip(_CDN).tap()
        self.assertEqual(self._state(_CDN), "open")
        self.assertIsNone(self._map())                          # in memory alone
        self._head(_CDN).locator(".status-node__state").tap()
        self.assertEqual(self._state(_CDN), "closed")


class PhoneTests(_BrowserCase):
    """A phone's tap toggles, and the hover card is not offered."""

    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 375, "height": 667}, "device_scale_factor": 2,
        "is_mobile": True, "has_touch": True, "reduced_motion": "reduce"}

    def test_a_tap_opens_and_closes_a_node(self):
        self._wall()
        self._chip(_CDN).tap()
        self.assertEqual(self._state(_CDN), "open")
        self.assertTrue(self.page.locator("#inspect-card").evaluate("c => c.hidden"))
        self._head(_CDN).locator(".status-node__state").tap()
        self.assertEqual(self._state(_CDN), "closed")
        self._head(_WEB).locator(".status-card__name").tap()
        self.assertEqual(self._state(_WEB), "closed")
        self.assertTrue(self.page.locator("#inspect-card").evaluate("c => c.hidden"))

    def test_a_tap_on_a_name_with_a_card_brings_none_after_the_pause(self):
        # a tap sends the mouse's events after its own, a move onto the name among
        # them, as a pointer that came to rest there would — after the touch is
        # lifted, which is the moment just after a click: no card comes up once the
        # pause is over either — where the card opens on a pause, a viewer's choice
        self.context.add_cookies([looks(self.base, inspection_card="pause")])
        self.tree.set_title(_CDN, "Assets")
        self._wall()
        for name, state in ((self._chip(_CDN), "open"),
                            (self._head(_WEB).locator(".status-card__name"), "closed")):
            with self.subTest(state=state):
                self.assertTrue(name.evaluate(
                    "name => name.classList.contains('inspect-trigger')"))
                name.tap()
                self.page.clock.run_for(1500)
                self.assertTrue(self.page.locator("#inspect-card").evaluate(
                    "c => c.hidden"))
        self.assertEqual((self._state(_CDN), self._state(_WEB)), ("open", "closed"))



#: A level's runs as the browser lays them out: its `--chip-w`, and for each chip in a
#: run its node's name, its box, how many lines its name takes and where its counts
#: stand against its name's last line and its right edge.
_RUNS = """branch => {
    const level = document.querySelector('.tree-kids[data-branch="' + branch + '"]');
    const lines = el => new Set(Array.from(el.getClientRects(),
                                           r => Math.round(r.top))).size;
    const chips = Array.from(level.querySelectorAll(
        ':scope > .tree-run > .tree-node > .tree-chip')).map(chip => {
      const box = chip.getBoundingClientRect();
      const name = chip.querySelector('.tree-chip__name');
      const rects = Array.from(name.getClientRects());
      const counts = chip.querySelector(':scope > .tree-counts');
      const style = getComputedStyle(chip);
      const at = counts ? counts.getBoundingClientRect() : null;
      return {node: chip.closest('.tree-node').dataset.node,
              x: box.x, y: box.y, width: box.width, height: box.height,
              lines: lines(name), cut: chip.scrollWidth > chip.clientWidth + 1,
              counts: at === null ? null : {
                beside: Math.abs(at.top - rects[rects.length - 1].top) < 4,
                right: box.right - parseFloat(style.paddingRight)
                       - parseFloat(style.borderRightWidth) - at.right}};
    });
    return {width: level.style.getPropertyValue('--chip-w'),
            display: getComputedStyle(level.querySelector('.tree-run')).display,
            chips: chips};
}"""

#: What a level's widest chip needs on one line: its edge and padding, its cue, its
#: name and, where it has them, its counts — read off the chip as drawn.
_NEEDS = """chip => {
    const style = getComputedStyle(chip);
    const cue = chip.querySelector(':scope > .status-cue');
    const range = document.createRange();
    range.selectNodeContents(chip.querySelector('.tree-chip__name'));
    const counts = chip.querySelector(':scope > .tree-counts');
    return parseFloat(style.paddingLeft) + parseFloat(style.paddingRight)
        + parseFloat(style.borderLeftWidth) + parseFloat(style.borderRightWidth)
        + cue.getBoundingClientRect().width
        + parseFloat(getComputedStyle(cue).marginRight)
        + Array.from(range.getClientRects()).reduce((sum, r) => sum + r.width, 0)
        + (counts ? parseFloat(getComputedStyle(counts).marginLeft)
                    + counts.getBoundingClientRect().width : 0);
}"""


#: A level's column as the server estimates it, in pixels as its run's font resolves
#: it, with its count of characters and that font's `0`.
_ESTIMATE = """branch => {
    const level = document.querySelector('.tree-kids[data-branch="' + branch + '"]');
    const run = level.querySelector(':scope > .tree-run');
    const probe = document.createElement('span');
    probe.style.cssText = 'position: absolute; visibility: hidden; display: block;'
        + ' width: var(--chip-w)';
    run.appendChild(probe);
    const px = probe.getBoundingClientRect().width;
    probe.style.cssText = 'position: absolute; visibility: hidden';
    probe.textContent = '0';
    const zero = probe.getBoundingClientRect().width;
    probe.remove();
    const chars = parseInt(level.style.getPropertyValue('--chip-w')
                           .replace('calc(', ''), 10);
    return {px: px, zero: zero, chars: chars};
}"""

#: How far the server's estimate of a level's column may stand from what the script
#: measures, in pixels, in the container's fonts.
ESTIMATE_SLACK = 15


class ChipRunTests(_BrowserCase):
    """A run of chips lines up in the columns its level shares (ADR-0127 decision
    12), the look `chip_runs: aligned`, the library's own: one width for the level,
    from its names measured in the chip's own font and room for its branches' largest
    count — which neither a click, a count nor a reload in another state moves — each
    chip stretched to its column with its counts at the right, and no name cut; a
    name past the level's bound wraps inside its column, and counts that do not fit
    beside a name stand beneath it. Wrapped runs draw each chip at its own width, and
    without script the server's estimate stands."""

    #: The zoo's, the grove's and the mix's children as chips, since a level nobody
    #: speaks for starts open.
    estate_look: Mapping[str, NodeMeta] = {
        **_ESTATE_LOOK, "/zoo": NodeMeta(look=Stated(chips=True)),
        "/grove": NodeMeta(look=Stated(chips=True)),
        "/mix": NodeMeta(look=Stated(chips=True))}

    def setUp(self) -> None:
        super().setUp()
        # a level of short names and one far past them, a run of one-leaf branches
        # and a branch whose leaves mix
        for name in ("ant", "bee", "cat", "dog", "eel", "fox", "gnu", "hen", "jay",
                     "koi"):
            self.tree.upsert(f"/zoo/{name}_house", StatusCode.OK)
        self.tree.upsert("/zoo/an_animal_whose_name_goes_on_past_the_rest",
                         StatusCode.OK)
        for name in ("alpha", "bravo", "delta", "hotel"):
            self.tree.upsert(f"/mix/{name}", StatusCode.OK)
        # and a name with no place where its words meet, past its level's columns
        for name in ("oak", "elm", "ash", "yew", "fir", "box", "bay", "fig", "lime",
                     "pear"):
            self.tree.upsert(f"/grove/{name}", StatusCode.OK)
        self.tree.upsert("/grove/supercalifragilistictree", StatusCode.OK)
        for number in range(3):
            self.tree.upsert(f"/mix/group/ok{number}", StatusCode.OK)
        # a warning its damping counter still holds back, which the failure budget
        # passes over (ADR-0128), so its branch stays a chip with its counts mixed
        self.tree.upsert("/mix/group/slow", StatusCode.OK, escalate_after=3)
        self.tree.upsert("/mix/group/slow", StatusCode.WARN, "slow")

    def _runs(self, branch: str, page: Any | None = None) -> dict[str, Any]:
        return (page or self.page).evaluate(_RUNS, branch)

    def _chip_at(self, runs: dict[str, Any], path: str) -> dict[str, Any]:
        return next(chip for chip in runs["chips"] if chip["node"] == path)

    def test_the_runs_on_either_side_of_an_open_child_line_up(self):
        self._wall()
        runs = self._runs(_WEB)
        self.assertEqual(runs["display"], "flex")
        self.assertTrue(runs["width"].endswith("px"), runs["width"])
        api, cdn, mail = (self._chip_at(runs, path) for path in (_API, _CDN, _MAIL))
        # one `x` down a column, and every chip stretched to it
        self.assertEqual(round(mail["x"]), round(api["x"]))
        self.assertEqual({round(api["width"]), round(cdn["width"]),
                          round(mail["width"])}, {round(api["width"])})
        self.assertGreater(cdn["x"], api["x"])                  # two columns here
        for chip in runs["chips"]:
            with self.subTest(chip=chip["node"]):
                self.assertFalse(chip["cut"])
                self.assertEqual(chip["lines"], 1)

    def test_a_levels_width_is_what_its_widest_name_and_largest_count_need(self):
        self._wall("/status?depth=2")
        runs = self._runs(_NAS)
        width = float(runs["width"].removesuffix("px"))
        # five branches of one leaf each and `epsilon`, the widest name, with its
        # count: on one line, its count beside it, in a column no wider than it needs
        epsilon = self._node(f"{_NAS}/epsilon").locator(":scope > .tree-chip")
        needs = epsilon.evaluate(_NEEDS)
        self.assertLessEqual(needs, width)
        self.assertGreater(needs, width - 4)
        chip = self._chip_at(runs, f"{_NAS}/epsilon")
        self.assertEqual(chip["lines"], 1)
        self.assertTrue(chip["counts"]["beside"])
        self.assertLess(abs(chip["counts"]["right"]), 1)        # at the right

    def test_neither_a_click_nor_a_count_nor_a_reload_moves_a_levels_width(self):
        self._wall("/status?depth=2")
        width = self._runs(_NAS)["width"]
        # the chip of the level's widest name opens where it stood, and its first:
        # their names are the level's still, whatever face they show
        self._chip(f"{_NAS}/epsilon").click()
        self._chip(f"{_NAS}/alpha").click()
        self.assertEqual((self._state(f"{_NAS}/epsilon"), self._state(f"{_NAS}/alpha")),
                         ("open", "open"))
        self.assertEqual(self._runs(_NAS)["width"], width)
        # a status, which changes a chip's counts, and the refresh that brings it
        self.tree.upsert(f"{_NAS}/alpha/probe", StatusCode.WARN, ["slow", "slower"])
        self._swap()
        self.assertEqual(self._runs(_NAS)["width"], width)
        # and a reload in another state draws the same columns, measured afresh off
        # chips that stand in no run
        self._reload()
        self.assertEqual(self._state(f"{_NAS}/epsilon"), "open")
        self.assertEqual(self._runs(_NAS)["width"], width)

    def test_a_name_far_past_the_rest_wraps_inside_its_column(self):
        self._wall()
        runs = self._runs("/zoo")
        long = self._chip_at(runs, "/zoo/an_animal_whose_name_goes_on_past_the_rest")
        short = self._chip_at(runs, "/zoo/ant_house")
        # the level's columns are sized for its typical names, nine characters, at
        # most one and a half times them, and stretched to fill the row, never to
        # twice that: the long name, of forty-two, wraps in a column of theirs,
        # where its words meet, and nothing is cut
        self.assertEqual(round(long["width"]), round(short["width"]))
        self.assertGreater(long["lines"], 1)
        self.assertEqual(short["lines"], 1)
        self.assertFalse(long["cut"])
        # its row stands taller than a line, every chip in it stretched to it
        one_line = self._chip_at(self._runs(_WEB), _API)["height"]
        row = [chip for chip in runs["chips"] if round(chip["y"]) == round(long["y"])]
        self.assertEqual({round(chip["height"]) for chip in row},
                         {round(long["height"])})
        self.assertGreater(long["height"], one_line + 10)
        name = self._chip("/zoo/an_animal_whose_name_goes_on_past_the_rest") \
            .locator(".tree-chip__name")
        breaks = name.evaluate("""name => {
            const range = document.createRange();
            const text = name.textContent;
            const lines = [];
            let top = null;
            for (const node of name.childNodes) {
              if (node.nodeType !== 3) { continue; }
              range.selectNodeContents(node);
              const rect = range.getClientRects()[0];
              if (top === null || Math.round(rect.top) !== top) {
                top = Math.round(rect.top);
                lines.push(node.textContent);
              }
            }
            return lines;
        }""")
        # each line starts at a word: where the name broke, it broke after `_`
        self.assertGreater(len(breaks), 1)
        self.assertTrue(all(line[:1].isalpha() for line in breaks), breaks)
        # and one with no such place breaks where it must, nothing cut
        grove = self._runs("/grove")
        tree = self._chip_at(grove, "/grove/supercalifragilistictree")
        self.assertGreater(tree["lines"], 1)
        self.assertFalse(tree["cut"])
        self.assertEqual(round(tree["width"]),
                         round(self._chip_at(grove, "/grove/oak")["width"]))

    def test_every_line_of_a_run_keeps_its_columns(self):
        # the grove's eleven chips in as many of its narrow columns as fit a desk's
        # card: the last line's chips stand under the columns above, as wide as theirs
        self._wall()
        level = self._runs("/grove")
        columns = sorted({round(chip["x"]) for chip in level["chips"]})
        self.assertGreater(len(columns), 2)
        lines = sorted({round(chip["y"]) for chip in level["chips"]})
        last = [chip for chip in level["chips"] if round(chip["y"]) == lines[-1]]
        self.assertLess(len(last), len(columns))
        self.assertEqual({round(chip["width"]) for chip in level["chips"]},
                         {round(last[0]["width"])})
        self.assertLessEqual({round(chip["x"]) for chip in last}, set(columns))

    def test_counts_that_do_not_fit_beside_a_name_stand_beneath_it(self):
        self._wall("/status?depth=2")
        runs = self._runs("/mix")
        group = self._chip_at(runs, "/mix/group")
        # ✓3 ⚠1: wider than the room the level keeps for one digit, beneath the
        # name at the right; a single total beside its name
        self.assertFalse(group["counts"]["beside"])
        self.assertLess(abs(group["counts"]["right"]), 1)
        self.assertEqual(group["lines"], 1)
        self.assertIsNone(self._chip_at(runs, "/mix/alpha")["counts"])

    def test_before_the_script_the_estimate_stands_near_what_it_measures(self):
        # The server counts a name's and a count's characters at 0.85 of the chip's
        # `0` and the chip's chrome at its size (backlog #91's note, §2, 2026-10-17):
        # in the container's fonts within a few pixels of what the script measures,
        # and on the whole nearer than every character a `0` and the chrome four
        # more, as it was — not on every level, a level of wide letters among them.
        context = self.browser.new_context(java_script_enabled=False, **self.drawn_in)
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        before = self._signed_in(context)
        before.goto(f"{self.base}/status")
        self._wall()
        now, was = [], []
        for branch in ("/zoo", "/grove", "/mix", _WEB):
            with self.subTest(branch=branch):
                served = before.evaluate(_ESTIMATE, branch)
                measured = float(self._runs(branch)["width"].removesuffix("px"))
                now.append(abs(served["px"] - measured))
                was.append(abs((served["chars"] + 4) * served["zero"] - measured))
                self.assertLessEqual(now[-1], ESTIMATE_SLACK, (served, measured))
        self.assertLess(sum(now), sum(was), (now, was))

    def test_wrapped_runs_draw_each_chip_at_its_own_width(self):
        self.context.add_cookies([{"name": "ls_prefs", "value": "chip_runs=wrapped",
                                   "url": self.base}])
        self._wall()
        runs = self._runs(_WEB)
        self.assertEqual(runs["width"], "")
        self.assertEqual(runs["display"], "block")
        api, cdn = self._chip_at(runs, _API), self._chip_at(runs, _CDN)
        self.assertNotEqual(round(api["width"]), round(cdn["width"]))
        self.assertEqual(round(api["y"]), round(cdn["y"]))

    def test_without_script_the_servers_estimate_sizes_the_columns(self):
        context = self.browser.new_context(java_script_enabled=False, **self.drawn_in)
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        page = self._signed_in(context)
        page.goto(f"{self.base}/status")
        runs = self._runs(_WEB, page)
        self.assertRegex(
            runs["width"],
            r"^calc\(\d+ \* var\(--ls-chip-letter\) \* 1ch \+ 20px \+ 1\.(15|65)em\)$")
        # the theme's letter, which the stylesheet resolves without the script: a
        # whole `0` in cyberpunk's monospace face, the library's theme
        self.assertEqual(page.evaluate(
            "getComputedStyle(document.body).getPropertyValue('--ls-chip-letter')"
            ".trim()"), "1")
        self.assertEqual(runs["display"], "flex")
        api, cdn = self._chip_at(runs, _API), self._chip_at(runs, _CDN)
        self.assertEqual(round(api["width"]), round(cdn["width"]))
        # in characters of the chip's own font, which the run takes
        run_font, chip_font = page.evaluate("""() => {
            const run = document.querySelector('.tree-run');
            const font = el => [getComputedStyle(el).fontSize,
                                getComputedStyle(el).fontWeight];
            return [font(run), font(run.querySelector('.tree-chip'))];
        }""")
        self.assertEqual(run_font, chip_font)


#: A level's first run as drawn: its width and its bound — two of its level's columns
#: as the browser draws them and their gap, the run's line height being one column
#: and the gap — the column the level's runs share, and each chip's place and width.
_ONE_COLUMN = """branch => {
    const level = document.querySelector('.tree-kids[data-branch="' + branch + '"]');
    const run = level.querySelector(':scope > .tree-run');
    const gap = 0.3 * parseFloat(getComputedStyle(document.documentElement).fontSize);
    const chips = Array.from(run.querySelectorAll(':scope > .tree-node > .tree-chip'))
        .map(chip => {
            const box = chip.getBoundingClientRect();
            return {node: chip.closest('.tree-node').dataset.node, x: box.x,
                    y: box.y, width: box.width,
                    cut: chip.scrollWidth > chip.clientWidth + 1};
        });
    const node = getComputedStyle(run.querySelector(':scope > .tree-node'));
    return {width: run.getBoundingClientRect().width,
            bound: 2 * parseFloat(getComputedStyle(run).lineHeight) - gap,
            gap: gap,
            column: level.style.getPropertyValue('--chip-w'),
            nodeLine: parseFloat(node.lineHeight) / parseFloat(node.fontSize),
            chips: chips};
}"""


class OneColumnRunTests(_BrowserCase):
    """A run with room for one of its level's columns only wraps as it comes (backlog
    #91's note, §2, 2026-10-17): its chips at their own widths, drawn as a column's
    chips are, sharing lines, where a level with room for two keeps its columns
    (ADR-0127 decision 12). What decides is the column as the browser draws it — the
    server's estimate before the script and without it, what the script measured
    after — read by the stylesheet off the run itself, so a run wraps or stands in
    columns from the first paint."""

    #: The pier's children as chips, and those of the level of narrow letters one
    #: test adds, since a level nobody speaks for starts open.
    estate_look: Mapping[str, NodeMeta] = {
        **_ESTATE_LOOK, "/pier": NodeMeta(look=Stated(chips=True)),
        "/lilt": NodeMeta(look=Stated(chips=True))}

    def setUp(self) -> None:
        super().setUp()
        # eight short names and two of thirty-nine: the 90th percentile is a long
        # one, so the level's column is as wide as a long name and its chrome, and
        # two of them more than a card has at a thousand pixels
        for letter in "abcdefgh":
            self.tree.upsert(f"/pier/dock_{letter}", StatusCode.OK)
        for number in (1, 2):
            self.tree.upsert(f"/pier/the_long_quay_where_the_ferries_berth_{number}",
                             StatusCode.OK)

    def _run(self, branch: str, page: Any | None = None) -> dict[str, Any]:
        return (page or self.page).evaluate(_ONE_COLUMN, branch)

    def _page(self, script: bool, *, theme: str | None = None,
              **drawn_in: Any) -> Any:
        context = self.browser.new_context(java_script_enabled=script,
                                           **(drawn_in or self.drawn_in))
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        if theme is not None:
            context.add_cookies([looks(self.base, theme=theme)])
        page = self._signed_in(context)
        page.goto(f"{self.base}/status")
        if script:
            page.wait_for_selector("html.ls-tree-ready", state="attached")
        return page

    def assert_as_it_comes(self, run: dict[str, Any]) -> None:
        self.assertLess(run["width"], run["bound"])
        docks = [chip for chip in run["chips"] if "/dock_" in chip["node"]]
        quays = [chip for chip in run["chips"] if "_quay_" in chip["node"]]
        # the docks share lines, each at its own width, narrower than a quay's
        self.assertEqual((len(docks), len(quays)), (8, 2))
        self.assertLess(len({round(chip["y"]) for chip in docks}), len(docks))
        self.assertLess(max(chip["width"] for chip in docks),
                        min(chip["width"] for chip in quays))
        self.assertFalse(any(chip["cut"] for chip in run["chips"]))

    def assert_in_columns(self, run: dict[str, Any]) -> None:
        self.assertGreaterEqual(run["width"], run["bound"])
        # as many columns of the measured width as fit, sharing the run's width as
        # a grid's tracks do, and every chip stretched to one, a last line's too
        column = float(run["column"].removesuffix("px"))
        count = int((run["width"] + run["gap"]) // (column + run["gap"]))
        each = (run["width"] - (count - 1) * run["gap"]) / count
        self.assertGreaterEqual(count, 2)
        for chip in run["chips"]:
            with self.subTest(chip=chip["node"]):
                self.assertAlmostEqual(chip["width"], each, delta=1)
        self.assertLess(len({round(chip["y"]) for chip in run["chips"]}),
                        len(run["chips"]))
        self.assertFalse(any(chip["cut"] for chip in run["chips"]))

    def test_a_run_with_room_for_one_column_only_wraps_as_it_comes(self):
        self._wall()
        run = self._run("/pier")
        self.assertTrue(run["column"].endswith("px"), run["column"])  # measured
        self.assert_as_it_comes(run)
        # a level with room for two of its columns keeps them
        self.assert_in_columns(self._run(_WEB))

    def test_without_script_the_estimate_decides_the_same(self):
        run = self._run("/pier", self._page(script=False))
        self.assertEqual(run["column"],
                         "calc(39 * var(--ls-chip-letter) * 1ch + 20px + 1.15em)")
        self.assert_as_it_comes(run)
        # the run's line height is its bound, which nothing in it is set by: a node,
        # whose box a find reveals before any script, takes the page's 1.5 back
        self.assertAlmostEqual(run["nodeLine"], 1.5, places=3)

    def test_the_column_the_browser_draws_decides_before_the_script_and_after(self):
        # names of narrow letters: the estimate counts each at 0.85 of the chip's
        # `0`, the script measures them at about half that in the plain theme's
        # proportional face, so on a phone the estimate's two columns do not fit the
        # card where the measured two do — the run comes as it comes until the
        # script has measured its level, and in columns after
        for number in range(6):
            self.tree.upsert(f"/lilt/illicit_lilt_till_ill_{number}", StatusCode.OK)
        phone = {"viewport": {"width": 390, "height": 844}, "reduced_motion": "reduce"}
        before = self._run("/lilt", self._page(script=False, theme="plain", **phone))
        after = self._run("/lilt", self._page(script=True, theme="plain", **phone))
        self.assertEqual(before["column"],
                         "calc(23 * var(--ls-chip-letter) * 1ch + 20px + 1.15em)")
        self.assertLess(before["width"], before["bound"])
        half = (before["width"] - before["gap"]) / 2
        for chip in before["chips"]:
            with self.subTest(chip=chip["node"]):
                self.assertLess(chip["width"], half - 10)       # its own width
        self.assertLess(len({round(chip["y"]) for chip in before["chips"]}), 6)
        self.assertTrue(after["column"].endswith("px"), after["column"])
        self.assert_in_columns(after)

    def test_the_run_decides_again_as_its_width_changes(self):
        # at 760 pixels the grid is one track, the card as wide as it, two of the
        # level's columns in the plain theme's face fitting it
        self.context.add_cookies([looks(self.base, theme="plain")])
        self._wall()
        self.page.set_viewport_size({"width": 760, "height": 700})
        self.assert_in_columns(self._run("/pier"))
        self.page.set_viewport_size({"width": 1000, "height": 700})
        self.assert_as_it_comes(self._run("/pier"))

#: What the hover card reads off the page: whether it is shown, its heading, its
#: first block, and its line to the node's page.
_CARD = """() => {
    const card = document.getElementById('inspect-card');
    const part = name => card.querySelector('.inspect-card__' + name) || null;
    const said = (name, read) => part(name) ? read(part(name)) : '';
    return {shown: !card.hidden,
            heading: said('title', el => el.textContent),
            about: said('about', el => el.innerHTML),
            more: said('more', el => el.textContent),
            to: said('more', el => el.getAttribute('href'))};
}"""

#: Each name the hover card answers to, and the cursor it and its row wear.
_CURSORS = """() => Array.from(document.querySelectorAll(
        '.tree-chip, [data-control="toggle"]')).filter(name => name.offsetParent)
    .map(name => [name.closest('[data-path]').dataset.path,
                  name.classList.contains('tree-chip') ? 'chip' : 'head',
                  getComputedStyle(name).cursor])"""


class HoverCardTests(_BrowserCase):
    """The hover card (ADR-0019 decision 3, backlog #91 §3.1): on a pause of about two
    thirds of a second on a node's name alone — a chip, the name in an open head —
    and on the keyboard's focus at once; never over the rest of a head's row, while a
    click is under way or just after one, or under the look `inspection_card: off`.
    It says the node's name and title as its head draws them and its `about`'s first
    block, with a line to its page where more follows, from the map the fragment
    carries, so a node a run names after the load has its card."""

    def setUp(self) -> None:
        super().setUp()
        # the card on a pause, a viewer's choice since the library's look is `off`
        self.context.add_cookies([looks(self.base, inspection_card="pause")])
        self.tree.set_about(_WEB, "The **front** of the shop.\n\nIt serves the pages."
                                  "\n\n- one\n- two")
        self.tree.set_title(_CDN, "Assets")
        self.tree.set_about(_CDN, "Static files.")

    def _card(self) -> dict[str, Any]:
        return self.page.evaluate(_CARD)

    def _in_view(self, target: Any) -> dict[str, float]:
        """Where ``target`` stands once it is on the screen: a pointer moved past
        the window's edge moves nothing in it."""
        target.scroll_into_view_if_needed()
        return target.bounding_box()

    def _rest_on(self, target: Any, ms: int) -> None:
        box = self._in_view(target)
        self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.page.clock.run_for(ms)

    def _away(self) -> None:
        self.page.mouse.move(2, 2)
        self.page.clock.run_for(300)

    def test_a_pause_on_a_chips_name_opens_its_card_and_nothing_sooner(self):
        self._wall()
        chip = self._chip(_CDN)
        self._rest_on(chip, 550)
        self.assertFalse(self._card()["shown"])
        self.page.clock.run_for(150)
        card = self._card()
        self.assertEqual((card["shown"], card["heading"], card["more"]),
                         (True, "cdn Assets", ""))
        self.assertEqual(card["about"], "<p>Static files.</p>\n")
        self.assertEqual(chip.get_attribute("aria-describedby"), "inspect-card")
        self._away()
        self.assertFalse(self._card()["shown"])
        self.assertIsNone(chip.get_attribute("aria-describedby"))

    def test_on_a_head_the_name_alone_answers(self):
        self._wall()
        head = self._head(_WEB)
        for part in (".status-card__state", ".node-title",
                     '.node-icons > [data-control="chips"]'):
            with self.subTest(part=part):
                # past the pause, and short of the wall's refresh at ten seconds
                self._rest_on(head.locator(part), 1000)
                self.assertFalse(self._card()["shown"])
        self._rest_on(head.locator(".status-card__name"), 700)
        card = self._card()
        self.assertEqual((card["shown"], card["heading"]), (True, "web The web tier"))
        self.assertEqual(card["about"],
                         "<p>The <strong>front</strong> of the shop.</p>\n")
        self.assertEqual((card["more"], card["to"]),
                         ("\u2026 2 more paragraphs on its page", "/status/web"))
        # leaving the name for the rest of the row takes it down
        self._rest_on(head.locator(".status-card__state"), 300)
        self.assertFalse(self._card()["shown"])

    def test_moving_on_the_name_starts_the_pause_again(self):
        self._wall()
        box = self._in_view(self._chip(_CDN))
        y = box["y"] + box["height"] / 2
        self.page.mouse.move(box["x"] + 4, y)
        self.page.clock.run_for(450)
        self.page.mouse.move(box["x"] + box["width"] - 4, y, steps=3)
        self.page.clock.run_for(450)
        self.assertFalse(self._card()["shown"])
        self.page.clock.run_for(250)
        self.assertTrue(self._card()["shown"])

    def test_no_card_while_a_click_is_under_way_or_just_after_one(self):
        # (each wait past the pause, all of them short of the refresh at ten
        # seconds, which draws the name again; in the plain theme's face, where the
        # name the click closed still stands under the pointer, in a window the whole
        # wall fits, so that the card the click closes shortens no scrolled page)
        self.context.add_cookies([looks(self.base, inspection_card="pause",
                                        theme="plain")])
        self.page.set_viewport_size({"width": 1000, "height": 1400})
        self._wall()
        name = self._head(_WEB).locator(".status-card__name")
        box = self._in_view(name)
        at = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        # a press held, the hand that holds the button moving on the name
        self.page.mouse.move(*at)
        self.page.mouse.down()
        self.page.mouse.move(at[0] + 1, at[1])
        self.page.clock.run_for(1000)
        self.assertFalse(self._card()["shown"])
        self.page.mouse.up()                      # the click closes the card in place
        self.assertEqual(self._state(_WEB), "closed")
        # the hand that clicked, moving on the name just after, starts no pause
        self.page.clock.run_for(200)
        self.page.mouse.move(at[0] + 2, at[1])
        self.page.clock.run_for(1000)
        self.assertFalse(self._card()["shown"])
        # the pointer moving on the name once that has passed is a new pause
        self.page.mouse.move(at[0] + 3, at[1])
        self.page.clock.run_for(700)
        self.assertTrue(self._card()["shown"])
        # and a pause under way when a click comes ends with it: the click opens
        # the card, which brings it into view, and the pointer stays where it was
        self._away()
        self.page.mouse.move(*at)
        self.page.clock.run_for(300)
        self.page.mouse.down()
        self.page.mouse.up()
        self.assertEqual(self._state(_WEB), "open")
        self.page.clock.run_for(1000)
        self.assertFalse(self._card()["shown"])

    def test_a_nodes_page_has_no_card_for_its_own_head(self):
        # whose `about` stands open in the band above it, and which is no toggle
        self._wall("/status/web")
        name = self.page.locator(".viewed-head .status-node__name")
        self._rest_on(name, 1000)
        self.assertFalse(self._card()["shown"])
        self.assertEqual(name.evaluate("name => getComputedStyle(name).cursor"),
                         "default")
        # while the names of the nodes it frames answer as on the wall
        self._rest_on(self._head(_CDN).locator('[data-control="toggle"]'), 700)
        self.assertEqual(self._card()["heading"], "cdn Assets")

    def test_a_refresh_during_the_pause_opens_the_card_on_the_name_it_drew(self):
        self._wall()
        chip = self._chip(_CDN)
        self._rest_on(chip, 300)
        old = chip.element_handle()
        # the grid drawn again under the resting pointer, as a refresh draws it
        self.page.evaluate("() => { const grid = document.getElementById("
                           "'status-grid'); grid.innerHTML = grid.innerHTML; }")
        self.assertFalse(old.evaluate("chip => chip.isConnected"))
        self.page.clock.run_for(400)
        self.assertEqual(self._card()["heading"], "cdn Assets")
        self.assertEqual(chip.get_attribute("aria-describedby"), "inspect-card")

    def test_the_keyboard_opens_it_at_once_and_escape_closes_it(self):
        self._wall()
        chip = self._chip(_CDN)
        self.page.keyboard.press("Shift")
        chip.focus()
        self.assertEqual(self._card()["heading"], "cdn Assets")
        self.page.keyboard.press("Escape")
        self.assertFalse(self._card()["shown"])

    def test_off_keeps_it_closed_for_the_pointer_and_the_keyboard(self):
        self.context.add_cookies([{"name": "ls_prefs", "value": "inspection_card=off",
                                   "url": self.base}])
        self._wall()
        self.assertEqual(self.page.evaluate(
            "document.body.getAttribute('data-ls-inspection-card')"), "off")
        self._rest_on(self._chip(_CDN), 2000)
        self.assertFalse(self._card()["shown"])
        self.page.keyboard.press("Shift")
        self._chip(_CDN).focus()
        self.assertFalse(self._card()["shown"])
        self.assertEqual(self.page.locator(".inspect-trigger").count(), 0)

    def test_a_node_that_arrives_after_the_load_has_its_card_after_the_next_swap(self):
        self._wall()
        self.tree.upsert("/web/edge", StatusCode.OK)
        self.tree.set_about("/web/edge", "The edge cache.")
        self.tree.set_about(_CDN, "Static files, now behind the edge.")
        self._swap()
        self._rest_on(self._chip("/web/edge"), 700)
        self.assertEqual((self._card()["heading"], self._card()["about"]),
                         ("edge", "<p>The edge cache.</p>\n"))
        self._away()
        self._rest_on(self._chip(_CDN), 700)
        self.assertEqual(self._card()["about"],
                         "<p>Static files, now behind the edge.</p>\n")

    def test_the_help_cursor_marks_the_names_that_have_a_card(self):
        self._wall()
        cursors = {(path, kind): cursor for path, kind, cursor
                   in self.page.evaluate(_CURSORS)}
        self.assertEqual(cursors[(_WEB, "head")], "help")     # a title and an about
        self.assertEqual(cursors[(_CDN, "chip")], "help")
        self.assertEqual(cursors[(_MAIL, "chip")], "pointer")  # neither: no card
        self.assertEqual(cursors[(_NAS, "head")], "pointer")
        # and the rest of a head's row is the toggle's
        self.assertEqual(self._head(_WEB).locator(".status-card__state").evaluate(
            "state => getComputedStyle(state).cursor"), "pointer")

    def test_a_name_is_text_and_a_glyph_title_stands_beside_it(self):
        self.tree.upsert("/web/*lit*", StatusCode.OK)
        self.tree.set_title("/web/*lit*", "🔴")
        self._wall()
        self._rest_on(self._chip("/web/*lit*"), 700)
        self.assertEqual(self._card()["heading"], "*lit* 🔴")


if __name__ == "__main__":
    unittest.main()
