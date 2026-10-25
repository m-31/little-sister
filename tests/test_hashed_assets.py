"""Our own stylesheet and scripts carry their content hash (ADR-0112).

A page that is open keeps the stylesheet and the scripts it was loaded with: the
refresh swaps a part of the document and fetches nothing else. So after an upgrade a
wall display ran the old ``poll.js`` against the new markup until somebody reloaded
it, and nobody reloads a wall. Three claims are held here, from what a response says:

* every first-party stylesheet and script a page links is addressed by a URL that
  carries the first eight hex digits of the file's SHA-256, and that URL is answered
  as something a browser may keep for good — while a URL with no hash, or with
  another file's, is not;
* a page that refreshes itself and every part it fetches say one digest of the whole
  set, the registered packages' assets among them, so a page can tell that the
  process it is reading from links other files than it holds;
* the fixture sheet still finds the stylesheet beside it.

What an open page then does about a digest that differs is a browser's to show
(``tests/test_assets_browser.py``).
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import slots
from little_sister.assets import Assets
from tests.render_ui_fixtures import _localize_static, render_page
from tests.test_series_window import HOST, estate
from tests.ui_fixtures import FIXTURES

_STATIC = Path(app_module.__file__).resolve().parent / "static"
_TEMPLATES = Path(app_module.__file__).resolve().parent / "templates"

#: Every stylesheet and script a document links, in the two forms the templates write.
_LINKED = re.compile(r'<(?:link|script)\b[^>]*?\b(?:href|src)="([^"]+)"')

#: What a browser may keep for good: a year, and never asked for again.
_FOR_GOOD = "public, max-age=31536000, immutable"

#: The pages a signed-in admin reads, each of which takes the shared head.
_PAGES = ("/status", f"/status{HOST}", f"/series{HOST}", "/series", "/events",
          "/handled", "/links", "/system", "/system/installed", "/about",
          f"/history{HOST}", "/copy")


def _own(html: str) -> list[str]:
    """The first-party stylesheets and scripts ``html`` links: what lives under
    ``/static/`` and ends in ``.css`` or ``.js``, each as the URL the page wrote."""
    return [url for url in _LINKED.findall(html)
            if urlsplit(url).path.startswith("/static/")
            and urlsplit(url).path.endswith((".css", ".js"))]


def _hash_of(url: str) -> str:
    """The first eight hex digits of the SHA-256 of the file ``url`` addresses."""
    member = urlsplit(url).path[len("/static/"):]
    return hashlib.sha256((_STATIC / member).read_bytes()).hexdigest()[:8]


class _SignedIn(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(lambda: setattr(app_module, "status_tree", saved[0]))
        self.addCleanup(lambda: setattr(app_module, "engine", saved[1]))
        app_module.status_tree, app_module.engine = estate()
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _page(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)


class EveryLinkCarriesItsHashTests(_SignedIn):
    def test_a_page_links_its_stylesheet_and_scripts_by_their_hash(self) -> None:
        for page in _PAGES:
            urls = _own(self._page(page))
            # Every page takes the stylesheet and at least the settings script.
            self.assertGreaterEqual(len(urls), 2, page)
            for url in urls:
                with self.subTest(page=page, url=url):
                    self.assertEqual(parse_qs(urlsplit(url).query).get("v"),
                                     [_hash_of(url)])

    def test_the_page_before_the_login_does_too(self) -> None:
        signed_out = app_module.app.test_client()
        html = signed_out.get("/login").get_data(as_text=True)
        urls = _own(html)
        self.assertEqual([urlsplit(url).path for url in urls],
                         ["/static/css/overview.css"])
        self.assertEqual(parse_qs(urlsplit(urls[0]).query).get("v"),
                         [_hash_of(urls[0])])

    def test_no_template_writes_such_a_url_by_hand(self) -> None:
        # A URL written out carries no hash, and a page nobody renders here — the
        # chooser between two doors — would link one unseen.
        written = re.compile(r"""["']/static/(?:css|js)/""")
        by_hand = [path.name for path in sorted(_TEMPLATES.glob("*.html"))
                   if written.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(by_hand, [])

    def test_every_script_and_stylesheet_we_ship_is_linked_somewhere(self) -> None:
        # The claim is about every file: one no page links would pass the tests above
        # by never being looked at.
        linked = {urlsplit(url).path[len("/static/"):]
                  for page in _PAGES for url in _own(self._page(page))}
        shipped = {path.relative_to(_STATIC).as_posix()
                   for kind in ("css", "js") for path in (_STATIC / kind).iterdir()}
        # What only a wall or a leaf's page links is asked for where it stands.
        linked |= {urlsplit(url).path[len("/static/"):]
                   for url in _own(render_page(FIXTURES[0]))}
        self.assertEqual(shipped - linked, set())


class AHashedUrlIsKeptForGoodTests(_SignedIn):
    def _answer(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        cache = response.headers.get("Cache-Control", "")
        response.close()
        return cache

    def test_the_url_a_page_wrote_may_be_kept_for_good(self) -> None:
        for url in _own(self._page("/status")):
            with self.subTest(url=url):
                self.assertEqual(self._answer(url), _FOR_GOOD)

    def test_it_is_answered_before_the_login(self) -> None:
        signed_out = app_module.app.test_client()
        url = _own(signed_out.get("/login").get_data(as_text=True))[0]
        response = signed_out.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], _FOR_GOOD)
        response.close()

    def test_a_url_with_no_hash_is_not(self) -> None:
        self.assertNotIn("immutable", self._answer("/static/js/poll.js"))

    def test_a_url_with_another_hash_is_asked_for_again(self) -> None:
        # A page loaded before an upgrade asks for the file by the hash it had. It
        # gets the file there is, and must not keep it under the old name.
        self.assertEqual(self._answer("/static/js/poll.js?v=00000000"), "no-cache")

    def test_a_picture_is_left_as_it_was(self) -> None:
        self.assertNotIn("immutable", self._answer("/static/favicon.svg?v=00000000"))
        html = self._page("/status")
        self.assertIn('href="/static/favicon.svg"', html)


class OneDigestOfTheSetTests(_SignedIn):
    _STAMP = re.compile(
        r'<script\b[^>]*\bjs/poll\.js[^>]*\bdata-assets="([0-9a-f]{8})"')

    def _digest(self) -> str:
        return app_module.assets_digest()

    def test_a_page_that_refreshes_says_the_digest_where_its_refresh_reads_it(
            self) -> None:
        for page in ("/status", f"/status{HOST}", "/system"):
            with self.subTest(page=page):
                found = self._STAMP.search(self._page(page))
                assert found is not None, page
                self.assertEqual(found.group(1), self._digest())

    def test_every_part_it_fetches_says_the_same(self) -> None:
        for page in ("/status", f"/status{HOST}", "/system"):
            with self.subTest(page=page):
                response = self.client.get(page, query_string={"fragment": "1"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("X-Assets"), self._digest())

    def test_a_registered_packages_asset_is_part_of_it(self) -> None:
        before = self._digest()
        asset = slots.Asset(package="tests.demo_extension", member="demo.css",
                            digest="0123abcd")
        with self.subTest("the set grew"):
            real = slots.assets
            slots.assets = lambda: (*real(), asset)  # type: ignore[assignment]
            self.addCleanup(lambda: setattr(slots, "assets", real))
            self.assertNotEqual(self._digest(), before)


class AssetsTests(TestCase):
    """The set itself, over a directory of the test's own."""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve() / "static"
        self.root.mkdir()
        (self.root / "css").mkdir()
        (self.root / "js").mkdir()
        (self.root / "css" / "a.css").write_bytes(b"a { color: red }\n")
        (self.root / "js" / "b.js").write_bytes(b"var b = 1;\n")
        (self.root / "picture.svg").write_bytes(b"<svg/>")
        self.assets = Assets(self.root)

    def test_a_file_is_named_by_eight_hex_digits_of_its_sha256(self) -> None:
        self.assertEqual(
            self.assets.digest("css/a.css"),
            hashlib.sha256(b"a { color: red }\n").hexdigest()[:8])

    def test_only_a_stylesheet_and_a_script_have_one(self) -> None:
        self.assertIsNone(self.assets.digest("picture.svg"))
        self.assertIsNone(self.assets.digest("js/missing.js"))
        # A script that is there, beside the directory and not beneath it.
        (self.root.parent / "outside.js").write_bytes(b"var out = 1;\n")
        self.addCleanup((self.root.parent / "outside.js").unlink)
        self.assertIsNone(self.assets.digest("../outside.js"))

    def test_the_set_is_every_stylesheet_and_script_beneath_the_root(self) -> None:
        self.assertEqual(self.assets.names(), ("css/a.css", "js/b.js"))

    def test_a_changed_file_is_a_changed_hash_and_a_changed_set(self) -> None:
        was, set_was = self.assets.digest("js/b.js"), self.assets.set_digest()
        # Past the clock's grain, so the change is one the file's times show.
        time.sleep(0.05)
        (self.root / "js" / "b.js").write_bytes(b"var b = 22;\n")
        self.assertEqual(self.assets.digest("js/b.js"),
                         hashlib.sha256(b"var b = 22;\n").hexdigest()[:8])
        self.assertNotEqual(self.assets.digest("js/b.js"), was)
        self.assertNotEqual(self.assets.set_digest(), set_was)

    def test_the_set_says_the_same_until_something_in_it_moves(self) -> None:
        self.assertEqual(self.assets.set_digest(), self.assets.set_digest())
        self.assertRegex(self.assets.set_digest(), r"\A[0-9a-f]{8}\Z")

    def test_what_a_package_registered_moves_it(self) -> None:
        plain = self.assets.set_digest()
        self.assertNotEqual(self.assets.set_digest(("0123abcd",)), plain)
        self.assertNotEqual(self.assets.set_digest(("0123abcd",)),
                            self.assets.set_digest(("0123abce",)))

    def test_a_new_file_moves_it(self) -> None:
        was = self.assets.set_digest()
        (self.root / "js" / "c.js").write_bytes(b"")
        self.assertNotEqual(self.assets.set_digest(), was)


class TheFixtureSheetTests(TestCase):
    def test_its_stylesheet_is_still_a_file_beside_it(self) -> None:
        with tempfile.TemporaryDirectory() as out:
            out_dir = Path(out).resolve()
            html = _localize_static(render_page(FIXTURES[0]), out_dir)
            sheets = [url for url in _LINKED.findall(html)
                      if urlsplit(url).path.endswith("overview.css")]
            self.assertEqual(len(sheets), 1)
            # A browser reading a file drops the query; what is left is a path.
            self.assertTrue((out_dir / urlsplit(sheets[0]).path).resolve().is_file())
