"""Every page on a phone: laid out at the phone's width, and no wider than it.

``tests/test_phone_layout.py`` holds what a response can show. What a phone makes
of a response is the browser's: a document that does not declare its viewport is
laid out 980 pixels wide and scaled to the screen, and one that does is laid out
at the screen's width and is wider only where something in it is. Both are read
here off an **emulated phone** — a touch device with a phone's user agent, which
is what makes Chromium treat the viewport as a phone does. A narrow window, which
the other browser tests set, is laid out at its width whatever the document says.

Served by a real server to headless Chromium. Skipped wherever Playwright or a
Chromium binary is unavailable, so the ordinary gate does not grow a browser
dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.reasons import Entry
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusTree
from tests.browser_looks import looks
from tests.browser_server import PageServer
from tests.test_links_guide import FILLED
from tests.test_series_window import HOST, estate

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

#: The phone: its width is the one the review measured at. The smaller one is as
#: narrow as a phone in use gets, bar the oldest.
_WIDTH, _HEIGHT = 390, 844
_SMALL = 360
_PHONE = {
    "viewport": {"width": _WIDTH, "height": _HEIGHT},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"),
}

#: Text that a narrow column cannot break: a host's name, a URL, a time written
#: in full — what makes a table wider than a phone.
_LAG = ("replication lag of 512 seconds on replica-2.db.internal.example.org since "
        "2026-10-02T03:14:15Z, threshold 30 seconds — see "
        "[the runbook](https://runbooks.example.org/db/replication-lag-and-what-to-do)")
_REVIEWS = {
    f"acme/api-pr-{number}": (
        f"[#{number}](https://forge.example.org/acme/api/pulls/{number}) "
        f"Bump the dependency that has been waiting for a reviewer — waiting "
        f"{number % 9 + 2}h for review")
    for number in range(4810, 4822)
}
#: A node four levels down, whose trail is wider than a phone, and one whose name
#: has nowhere to break and is wider than a phone alone — and than a leaf's column on
#: a desk, 772 pixels, in a narrow face as much as in a wide one: its trail is some
#: 1050 pixels in Liberation Sans and in Inter. At half the length it was wider than
#: that column in DejaVu Sans only.
_DEEP = "/security/scanner/production/informational-findings"
_UNBROKEN = ("/storage/backup_of_the_primary_database_cluster_nightly"
             "_with_its_write_ahead_log_segments")
_TITLE = "Findings nobody has to act on today"
#: A line whose words have nowhere to break either — a digest, an identifier — and
#: the name of who pinned it.
_DIGEST = "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
_IMAGE = "storefront_api_gateway_service_production_eu_central_1"
_SOMEBODY = "a.very.long.user.name@accounts.example.org"


def _wide_estate() -> tuple[StatusTree, Any]:
    """The estate ``tests/test_series_window.py`` reads — a host with curves and
    readings, an engine whose checks give System a schedule — and around it what
    a wall holds: hosts with their aspects, a queue of findings, and a node that
    has changed its mind in long sentences, so Events and History have rows that
    a phone is narrower than. Two nodes have a trail that a phone is narrower than,
    and a line says a word that it is narrower than; each of them is pinned, as one
    more node and one more line are."""
    tree, engine = estate()
    tree.upsert(_DEEP, StatusCode.WARN, "14 findings are open",
                frequency_seconds=3600)
    tree.set_title(_DEEP, _TITLE)
    tree.upsert(_UNBROKEN, StatusCode.OK, "written last night",
                frequency_seconds=3600)
    tree.upsert("/registry/images", StatusCode.ERROR,
                [Entry(_IMAGE, f"image digest {_DIGEST} does not match the signed "
                               f"one", StatusCode.ERROR)],
                members=True, frequency_seconds=300)
    tree.set_title("/alpha", "The first of three hosts")
    # the engine's own node, which the wall lifts into the strip above its cards
    tree.upsert(f"{HEARTBEAT_PATH}/engine", StatusCode.WARN,
                "the last tick took 4.2 seconds", frequency_seconds=60)
    for host in ("alpha", "beta", "gamma"):
        for aspect in ("cpu", "disk", "load", "memory", "ssh"):
            tree.upsert(f"/{host}/{aspect}", StatusCode.OK, "within its limits",
                        frequency_seconds=120)
    tree.upsert("/ci/reviews", StatusCode.WARN, dict(_REVIEWS),
                frequency_seconds=300)
    tree.upsert("/db/replica", StatusCode.OK, "in step with the primary")
    tree.upsert("/db/replica", StatusCode.ERROR, _LAG)
    tree.upsert("/db/replica", StatusCode.WARN, _LAG.replace("512", "64"))
    tree.upsert("/db/replica", StatusCode.ERROR, _LAG.replace("512", "2048"))
    soon = datetime.now(UTC) + timedelta(days=2)
    tree.set_maintenance("/alpha/disk", "The volume is being grown, ticket "
                         "[OPS-1701](https://tickets.example.org/OPS-1701).",
                         expires_at=soon, set_by="lex")
    tree.set_entry_maintenance("/ci/reviews", "acme/api-pr-4812",
                               "Waiting on the vendor's release.",
                               expires_at=soon, set_by="anna")
    tree.set_maintenance(_DEEP, "Triage is on Thursday.", expires_at=soon,
                         set_by="lex")
    tree.set_maintenance(_UNBROKEN, "The cluster is being moved.",
                         expires_at=soon, set_by="anna")
    tree.set_entry_maintenance("/registry/images", _IMAGE,
                               f"Known: {_DIGEST} is the rebuilt image.",
                               expires_at=soon, set_by=_SOMEBODY)
    return tree, engine


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class PhoneLayoutTests(unittest.TestCase):
    """Each page on an emulated phone — in Chromium."""

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
        cls.saved = (app_module.status_tree, app_module.engine)
        app_module.status_tree, app_module.engine = _wide_estate()
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        app_module.status_tree, app_module.engine = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.context = self.browser.new_context(**_PHONE, reduced_motion="reduce")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.route("https://cdn.jsdelivr.net/**", self._vendored)

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

    def _sign_in(self) -> None:
        self.page.goto(f"{self.base}/login")
        self.page.fill("#username", "pan")
        self.page.fill("#password", "12345678")
        with self.page.expect_navigation():
            self.page.click("button[type=submit]")

    def _measure(self) -> dict[str, Any]:
        """How wide the browser laid the page out, how wide the page is, and what
        in it reaches past the screen without a box of its own to scroll in."""
        return self.page.evaluate(
            """
            () => {
              const screenWidth = window.screen.width;
              const past = [];
              for (const el of document.querySelectorAll('body *')) {
                const box = el.getBoundingClientRect();
                if (box.width === 0 || box.right <= screenWidth + 0.5) continue;
                if (!el.checkVisibility()) continue;   // inside a closed <details>
                let boxed = false;
                for (let up = el.parentElement; up && up !== document.body;
                     up = up.parentElement) {
                  if (/(auto|scroll|hidden|clip)/.test(getComputedStyle(up).overflowX)
                      && up.getBoundingClientRect().right <= screenWidth + 0.5) {
                    boxed = true;
                    break;
                  }
                }
                if (!boxed) {
                  past.push(el.tagName.toLowerCase() + '.' + String(el.className)
                            + ' ends at ' + Math.round(box.right));
                }
              }
              return {
                screen: screenWidth,
                laidOutAt: window.innerWidth,
                page: document.documentElement.scrollWidth,
                scale: window.visualViewport.scale,
                past: past.slice(0, 4),
              };
            }
            """)

    def assert_fits_the_phone(self, what: str, width: int = _WIDTH) -> None:
        seen = self._measure()
        self.assertEqual(seen["screen"], width, (what, seen))
        # laid out at the phone's own width, at its own scale: the declaration
        self.assertEqual(seen["laidOutAt"], width, (what, seen))
        self.assertEqual(seen["scale"], 1, (what, seen))
        # and nothing in it is wider than that
        self.assertLessEqual(seen["page"], width, (what, seen))
        self.assertEqual(seen["past"], [], (what, seen))

    # --- every page -------------------------------------------------------------------

    def test_the_login_page_fits_a_phone(self):
        self.page.goto(f"{self.base}/login")
        self.page.wait_for_selector("#username")
        self.assert_fits_the_phone("/login")

    _ROUTES = (
        "/status", "/status?view=1&hide_ok=1", "/status/alpha", "/status/db",
        "/status/alpha/disk", "/status/db/replica", "/status/ci/reviews",
        f"/status{HOST}", "/events", "/system", "/system/installed",
        "/series", f"/series{HOST}", f"/history{HOST}", "/history/db/replica",
        "/maintenance", "/links", "/copy", "/copy/db", "/about",
        # a trail wider than the phone: a leaf's page, its branch's with the
        # filters beside it, and its other views
        f"/status{_DEEP}", f"/status{_DEEP.rsplit('/', 1)[0]}",
        f"/history{_DEEP}", f"/copy{_DEEP}",
        f"/status{_UNBROKEN}", f"/history{_UNBROKEN}", f"/copy{_UNBROKEN}",
        # a name with nowhere to break on the wall's cards, at every depth, and
        # a line with a word like it, on its node's page
        "/status/storage", "/status?depth=8",
        "/status/registry", "/status/registry/images")

    def test_every_page_fits_a_phone(self):
        self._sign_in()
        for route in self._ROUTES:
            with self.subTest(route=route):
                self.page.goto(f"{self.base}{route}")
                self.page.wait_for_load_state("load")
                self.assert_fits_the_phone(route)

    def test_every_page_fits_a_smaller_phone(self):
        small = self.browser.new_context(**{
            **_PHONE, "viewport": {"width": _SMALL, "height": 780}},
            reduced_motion="reduce")
        self.addCleanup(small.close)
        self.page = small.new_page()
        self.page.route("https://cdn.jsdelivr.net/**", self._vendored)
        self._sign_in()
        for route in self._ROUTES:
            with self.subTest(route=route):
                self.page.goto(f"{self.base}{route}")
                self.page.wait_for_load_state("load")
                self.assert_fits_the_phone(route, _SMALL)

    def test_the_other_layouts_fit_a_phone_too(self):
        # the sections in the bar, where the page has the rail's width as well,
        # and the wall display, which has neither bar nor band
        self._sign_in()
        for layout in ("topbar", "kiosk"):
            self.context.add_cookies([{"name": "ls_prefs", "url": self.base,
                                       "value": f"layout={layout}"}])
            for route in ("/status", "/status?depth=8", f"/status{_DEEP}",
                          f"/status{_UNBROKEN}", "/events", "/system",
                          "/system/installed", "/history/db/replica",
                          "/maintenance", f"/copy{_DEEP}"):
                with self.subTest(layout=layout, route=route):
                    self.page.goto(f"{self.base}{route}")
                    self.page.wait_for_load_state("load")
                    self.assertEqual(
                        self.page.evaluate("document.body.dataset.lsLayout"),
                        layout)
                    self.assert_fits_the_phone(f"{route}, {layout}")

    # --- what was wider ---------------------------------------------------------------

    def test_the_bands_filters_wrap_and_stay_in_reach(self):
        # the two filters and the three buttons that set every node (ADR-0127
        # decision 7) — the chips switch and the depth control went with dense mode
        self._sign_in()
        self.page.goto(f"{self.base}/status")
        self.page.wait_for_selector(".status-filters")
        self.page.wait_for_selector(".ls-band__modes:not([hidden])")
        controls = self.page.evaluate(
            """
            () => [...document.querySelectorAll(
                '.status-filters .form-check, .ls-band__mode')].map(el => {
              const box = el.getBoundingClientRect();
              return {left: box.left, right: box.right, top: Math.round(box.top)};
            })
            """)
        self.assertEqual(len(controls), 5)
        for control in controls:
            self.assertGreaterEqual(control["left"], 0, controls)
            self.assertLessEqual(control["right"], _WIDTH, controls)
        # five controls do not fit one line of a phone: they take a second
        self.assertGreater(len({control["top"] for control in controls}), 1,
                           controls)
        # beneath the stamp, which then has nothing beside it to be ruled off from
        self.assertEqual(
            self.page.evaluate("getComputedStyle(document.querySelector("
                               "'#status-updated')).borderRightWidth"), "0px")

    def test_the_walls_strip_stands_in_its_column(self):
        # the count of pins and the engine's own node, kept to the right above
        # the cards: where a phone has no room for the two side by side the
        # second takes the next line — neither is pushed out at the left, and
        # neither is squeezed into a column of its own words
        self._sign_in()
        self.page.goto(f"{self.base}/status")
        self.page.wait_for_selector(".strip-band .ls-strip")
        band = self.page.evaluate(
            """
            () => {
              const band = document.querySelector('.strip-band');
              const edge = band.getBoundingClientRect();
              return {
                left: edge.left, right: edge.right,
                parts: [...band.children].filter(el => el.checkVisibility())
                  .map(el => {
                    const box = el.getBoundingClientRect();
                    return {left: box.left, right: box.right,
                            top: Math.round(box.top)};
                  }),
                name: document.querySelector('.ls-strip__name')
                              .getClientRects().length,
              };
            }
            """)
        self.assertEqual(len(band["parts"]), 2, band)
        for part in band["parts"]:
            self.assertGreaterEqual(part["left"], band["left"] - 0.5, band)
            self.assertLessEqual(part["right"], band["right"] + 0.5, band)
        self.assertEqual(band["name"], 1, band)                 # on one line
        self.assertGreater(band["parts"][1]["top"], band["parts"][0]["top"], band)

    _BAND = """
        () => {
          const edge = el => {
            const box = el.getBoundingClientRect();
            return {left: box.left, right: box.right, width: box.width,
                    top: Math.round(box.top), bottom: Math.round(box.bottom)};
          };
          const trail = document.querySelector('.ls-band__title .ls-crumbs');
          if (trail === null) return null;
          const title = document.querySelector('.ls-band__title .node-title--header');
          // a separator and the name before it, where that name is on one line
          const top = el => Math.round(el.getClientRects()[0].top);
          const kept = [...trail.children]
            .filter(el => el.textContent.trim() === '/'
                    && el.previousElementSibling.getClientRects().length === 1)
            .map(el => top(el) === top(el.previousElementSibling));
          // what a part would take on one line of its own, wherever it stands
          const natural = el => {
            const copy = el.cloneNode(true);
            copy.style.position = 'absolute';
            copy.style.visibility = 'hidden';
            copy.style.width = 'max-content';
            el.parentElement.appendChild(copy);
            const width = copy.getBoundingClientRect().width;
            copy.remove();
            return width;
          };
          return {
            trail: edge(trail), title: title === null ? null : edge(title),
            band: edge(document.querySelector('.ls-band')),
            cut: title !== null && title.scrollWidth > title.clientWidth,
            trailOwn: natural(trail),
            titleOwn: title === null ? null : title.scrollWidth,
            gap: parseFloat(getComputedStyle(trail.parentElement).columnGap),
            names: [...trail.children].filter(el => el.textContent.trim() !== '/')
                                      .map(el => edge(el)),
            // the lines the trail's parts stand on, a name that wraps counted on
            // each of its lines
            lines: new Set([...trail.children].flatMap(el => [...el.getClientRects()])
                                              .map(r => Math.round(r.top))).size,
            kept,
          };
        }
        """

    def test_a_trail_wider_than_a_phone_takes_more_lines(self):
        self._sign_in()
        self.page.goto(f"{self.base}/status{_DEEP}")
        band = self.page.evaluate(self._BAND)
        self.assertIsNotNone(band)
        # inside the screen, on more than one line
        self.assertGreaterEqual(band["trail"]["left"], 0, band)
        self.assertLessEqual(band["trail"]["right"], _WIDTH, band)
        self.assertGreater(len({name["top"] for name in band["names"]}), 1, band)
        # each line ends in a separator: none begins the next
        self.assertEqual(band["kept"], [True] * _DEEP.count("/"), band)
        # and the node's title is still read: on a line of its own beneath, and
        # all of that line
        self.assertGreaterEqual(band["title"]["top"], band["trail"]["bottom"] - 2,
                                band)
        self.assertLessEqual(band["title"]["right"], _WIDTH, band)
        self.assertGreater(band["title"]["width"], 0.9 * band["band"]["width"],
                           band)

    def test_a_title_keeps_the_trails_line_where_a_word_of_it_fits(self):
        self._sign_in()
        self.page.goto(f"{self.base}/status/alpha")
        band = self.page.evaluate(self._BAND)
        self.assertIsNotNone(band)
        self.assertLess(band["title"]["top"], band["trail"]["bottom"], band)
        self.assertGreaterEqual(band["title"]["left"], band["trail"]["right"], band)
        self.assertLessEqual(band["title"]["right"], _WIDTH, band)
        self.assertGreater(band["title"]["width"], 60, band)

    def test_a_title_with_less_room_than_a_word_takes_the_next_line(self):
        # how much a trail leaves of its line is the font's to say, so the line is
        # made as long here as the claim needs: with room for a word beside the
        # trail the title stays, and with less it goes
        self._sign_in()
        self.page.goto(f"{self.base}/status/alpha")
        beside = """
            room => {
              const heading = document.querySelector('.ls-band__title');
              const trail = heading.querySelector('.ls-crumbs');
              const title = heading.querySelector('.node-title--header');
              // eight characters, each about half the font's size
              const word = 8 * parseFloat(getComputedStyle(title).fontSize) / 2;
              const gap = parseFloat(getComputedStyle(heading).columnGap);
              heading.style.width =
                (trail.getBoundingClientRect().width + gap + room * word) + 'px';
              return title.getBoundingClientRect().top
                     < trail.getBoundingClientRect().bottom;
            }
            """
        self.assertTrue(self.page.evaluate(beside, 1.6))
        self.assertFalse(self.page.evaluate(beside, 0.5))

    def test_no_line_of_the_trail_begins_with_a_separator(self):
        # where a line ends is the font's to say, so the heading is made every
        # width here from a few names' to a phone's, in steps narrower than a
        # slash: at some of them a line has room for a name and none for the
        # slash after it, and the slash stays with its name, on the next line
        self._sign_in()
        self.page.goto(f"{self.base}/status{_DEEP}")
        wrapped = 0
        for width in range(150, 331, 4):
            self.page.evaluate(
                "width => { document.querySelector('.ls-band__title')"
                ".style.width = width + 'px'; }", width)
            band = self.page.evaluate(self._BAND)
            wrapped += len({name["top"] for name in band["names"]}) > 1
            # every slash whose name stands on one line stands on that line
            self.assertGreaterEqual(len(band["kept"]), 2, (width, band))
            self.assertEqual(set(band["kept"]), {True}, (width, band))
        self.assertEqual(wrapped, len(range(150, 331, 4)))

    def test_a_name_wider_than_a_phone_breaks_inside_itself(self):
        self._sign_in()
        self.page.goto(f"{self.base}/status{_UNBROKEN}")
        band = self.page.evaluate(self._BAND)
        self.assertIsNotNone(band)
        name = band["names"][-1]
        self.assertGreaterEqual(name["left"], 0, band)
        self.assertLessEqual(name["right"], _WIDTH, band)
        self.assertGreater(name["bottom"] - name["top"], 40, band)   # two lines

    def test_on_a_desk_the_band_reads_as_it_did(self):
        # what gives way on a phone does not where the band has the room: the
        # trail keeps one line, and the title the rest of that line — all of it,
        # or cut short where the band is narrower than the two. Which of the two a
        # page is depends on the face it is drawn in — History's band is 980 pixels
        # here, and the trail and the title need 890 of them on a Mac, 917 in
        # Liberation Sans and 1072 in DejaVu Sans — so the band says which it is;
        # a short page and a leaf's narrow column are far from the edge in any of
        # the plain theme's proportional faces. Cyberpunk's monospace one is wider
        # still: there the deep trail is wider than the band, and wraps inside it
        # as the test after this one holds
        desk = self.browser.new_context(viewport={"width": 1189, "height": 900},
                                        reduced_motion="reduce")
        self.addCleanup(desk.close)
        desk.add_cookies([looks(self.base, theme="plain")])
        self.page = desk.new_page()
        self.page.route("https://cdn.jsdelivr.net/**", self._vendored)
        self._sign_in()
        read = set()
        for route in ("/status/alpha", f"/history{_DEEP}", f"/status{_DEEP}"):
            with self.subTest(route=route):
                self.page.goto(f"{self.base}{route}")
                band = self.page.evaluate(self._BAND)
                self.assertIsNotNone(band)
                self.assertEqual(len({name["top"] for name in band["names"]}), 1,
                                 band)
                self.assertGreaterEqual(band["title"]["left"],
                                        band["trail"]["right"], band)
                self.assertLess(band["title"]["top"], band["trail"]["bottom"], band)
                self.assertLessEqual(band["title"]["right"],
                                     band["band"]["right"] + 0.5, band)
                needs = band["trail"]["width"] + band["gap"] + band["titleOwn"]
                self.assertEqual(band["cut"], needs > band["band"]["width"] + 0.5,
                                 band)
                read.add(band["cut"])
        # both halves of the sentence: a title whole, and one cut short
        self.assertEqual(read, {False, True})
        # and the stamp is ruled off from the filters beside it
        self.page.goto(f"{self.base}/status")
        self.assertEqual(
            self.page.evaluate("getComputedStyle(document.querySelector("
                               "'#status-updated')).borderRightWidth"), "1px")

    def test_on_a_desk_a_trail_wider_than_its_band_wraps_inside_it(self):
        # a leaf's page is a column narrower than a desk's window, and a name can
        # be wider than that: the trail stays inside the column, as on a phone, the
        # name breaking where its words meet
        desk = self.browser.new_context(viewport={"width": 1189, "height": 900},
                                        reduced_motion="reduce")
        self.addCleanup(desk.close)
        self.page = desk.new_page()
        self.page.route("https://cdn.jsdelivr.net/**", self._vendored)
        self._sign_in()
        self.page.goto(f"{self.base}/status{_UNBROKEN}")
        band = self.page.evaluate(self._BAND)
        self.assertIsNotNone(band)
        # the premise: on one line of its own the trail is wider than the column
        self.assertGreater(band["trailOwn"], band["band"]["width"], band)
        self.assertLessEqual(band["trail"]["right"], band["band"]["right"] + 0.5,
                             band)
        self.assertGreater(band["lines"], 1, band)

    def test_a_wide_table_scrolls_inside_its_box(self):
        self._sign_in()
        for route, table in (("/events", "table"), ("/history/db/replica", "table"),
                             ("/system", ".ls-schedule")):
            with self.subTest(route=route):
                self.page.goto(f"{self.base}{route}")
                self.page.wait_for_selector(table)
                box = self.page.evaluate(
                    """
                    selector => {
                      const table = document.querySelector(selector);
                      const box = table.closest('.table-responsive');
                      if (box === null) return null;
                      const edge = box.getBoundingClientRect();
                      return {holds: box.scrollWidth, shows: box.clientWidth,
                              right: edge.right};
                    }
                    """, table)
                self.assertIsNotNone(box)
                self.assertGreater(box["holds"], box["shows"], box)   # it is wide
                self.assertLessEqual(box["right"], _WIDTH, box)       # its box is not

    def test_a_reason_in_a_scrolled_table_keeps_a_width_to_be_read_at(self):
        # every column of a table wider than its box is as narrow as it can be,
        # and a reason can be as narrow as its longest word: the column keeps
        # most of a phone's width instead, so its rows are not a screen tall
        self._sign_in()
        for route in ("/events", "/history/db/replica"):
            with self.subTest(route=route):
                self.page.goto(f"{self.base}{route}")
                self.page.wait_for_selector("td.md-body")
                widths = self.page.evaluate(
                    "() => [...document.querySelectorAll('td.md-body')]"
                    ".map(cell => cell.getBoundingClientRect().width)")
                self.assertGreaterEqual(min(widths), 250, widths)

    def test_on_a_desk_a_reason_takes_the_width_its_table_gives_it(self):
        # a desk's table shares its width out by what its columns hold: a floor
        # under the reason's would move the others
        desk = self.browser.new_context(viewport={"width": 1189, "height": 900},
                                        reduced_motion="reduce")
        self.addCleanup(desk.close)
        self.page = desk.new_page()
        self.page.route("https://cdn.jsdelivr.net/**", self._vendored)
        self._sign_in()
        for route in ("/events", "/history/db/replica"):
            with self.subTest(route=route):
                self.page.goto(f"{self.base}{route}")
                self.page.wait_for_selector("td.md-body")
                # no floor: what a cell has where nothing sets one
                self.assertIn(
                    self.page.evaluate("getComputedStyle(document.querySelector("
                                       "'td.md-body')).minWidth"), ("0px", "auto"))

    def test_the_schedule_keeps_its_place_when_it_is_fetched_again(self):
        # System's Running page swaps its schedule in on every poll, box and all: a
        # reader who has scrolled to the columns at its right stays at them
        self._sign_in()
        self.page.goto(f"{self.base}/system")
        self.page.wait_for_selector(".ls-schedule")
        box = "document.querySelector('.ls-schedule').closest('.table-responsive')"
        place = self.page.evaluate(
            f"""
            () => {{
              const box = {box};
              box.dataset.before = 'the poll';    // the box the poll replaces
              box.scrollLeft = Math.floor((box.scrollWidth - box.clientWidth) / 2);
              return box.scrollLeft;
            }}
            """)
        self.assertGreater(place, 20)
        # a tab that comes back into view polls at once
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        self.page.wait_for_function(f"{box}.dataset.before === undefined")
        self.assertEqual(self.page.evaluate(f"{box}.scrollLeft"), place)

    def test_the_links_guide_opened_fits_a_phone(self):
        # the sample file, the path it goes to and the roster's table, each in a
        # card that is narrower than the page
        self._sign_in()
        self.page.goto(f"{self.base}/links")
        folds = self.page.locator("details.ls-links__fold")
        self.assertEqual(folds.count(), 2)
        for index in range(2):
            folds.nth(index).locator("summary").click()
            self.assertTrue(folds.nth(index).evaluate("fold => fold.open"))
            self.assert_fits_the_phone(f"/links, {index + 1} of its folds open")
        self.page.set_viewport_size({"width": _SMALL, "height": 780})
        self.assert_fits_the_phone("/links, both folds open", _SMALL)

    def test_the_icon_names_under_a_page_of_links_fit_a_phone(self):
        # the same roster, at the foot of a page that has links
        self._sign_in()
        with (mock.patch.object(app_module, "current_links", return_value=FILLED),
              mock.patch.object(app_module.link_probe, "refresh_if_due")):
            self.page.goto(f"{self.base}/links")
        fold = self.page.locator(".ls-links__foot details.ls-links__fold")
        self.assertEqual(fold.count(), 1)
        fold.locator("summary").click()
        self.assertTrue(fold.evaluate("fold => fold.open"))
        self.assert_fits_the_phone("/links with links, its icon names open")

    def test_an_open_editor_fits_a_phone(self):
        self._sign_in()
        for route, opener in (
                ("/maintenance", ".rule-block__edit > summary"),
                ("/status/alpha/disk", ".rule-block--node .rule-block__edit > summary"),
                ("/status/ci/reviews", ".reason-pin > summary")):
            with self.subTest(route=route):
                self.page.goto(f"{self.base}{route}")
                self.page.locator(opener).first.click()
                self.page.wait_for_function(
                    "document.activeElement !== null"
                    " && document.activeElement.name === 'reason'")
                self.assert_fits_the_phone(f"{route}, an editor open")
                # and with the list of formats its expiry field takes
                self.page.locator(
                    "details[open] .maintenance-expiry-help > summary").first.click()
                self.assert_fits_the_phone(f"{route}, the formats open")
