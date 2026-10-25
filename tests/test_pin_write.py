"""Where a pin's write comes back to, and what a save that changes nothing writes.

Three things a walk of the pin block on a running deployment found (backlog #89):

* A line's set, edit and clear from its node's own page came back to the top of
  that page — on a node with 150 lines, a long way from the line. They come back
  to the line, at the address that names one (`?reason=<slug>#pinned-reason`,
  ADR-0036 decision 12), as a write from *Handled* comes back to its
  node (ADR-0104 decisions 3, 4 and 6).
* A save that changed neither the note nor the expiry rebuilt the pin all the
  same: it took the saver's name and a new token, and another open editor of it
  went stale. Such a save is answered as saved and writes nothing (ADR-0104
  decision 5). `tests/test_tree.py` holds the write itself; this is the page's
  form, posted as it was filled.
* A refused write headed its page with the node's path as the form had spelled
  it. It heads it as every page writes a path.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.pins import Pin
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, parse

PATH = "/ci/actions"
#: The node as its own page's forms name it: the route's `branch`, which has no
#: leading slash. *Handled* and the wall post the absolute path.
FORM_PATH = "ci/actions"
#: Slugs as checks write them: a declared one, the natural one of a discovered
#: entry, which holds a slash, and one with what a fragment would mis-read.
LINES = {
    "web-build": "web build failed on main",
    "acme/api-pr-412": "api pull request 412 is waiting on review",
    "disk#2-at-90%": "the second disk is nearly full",
    "mobile-build": "mobile build is disabled",
}


class _CountingStore:
    """A maintenance store that counts what the tree writes through (no file)."""

    def __init__(self) -> None:
        self.saves = 0

    def load(self) -> dict[str, Pin]:
        return {}

    def load_entries(self) -> dict[tuple[str, str], Pin]:
        return {}

    def save(self, entries: Any, entry_pins: Any = None, acknowledged: Any = None,
             lines_acknowledged: Any = None) -> None:
        self.saves += 1


class _WriteCase(TestCase):
    """A node whose lines can be pinned one by one, written to by an admin."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.store = _CountingStore()
        self.tree = StatusTree(pin_store=self.store)
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert(PATH, StatusCode.ERROR, dict(LINES))

    def _pin_node(self, note: str = "the runners are being replaced",
                  by: str = "ada") -> Pin:
        write = self.tree.set_maintenance(
            PATH, note, set_by=by,
            expires_at=datetime.now(UTC) + timedelta(days=2, hours=3))
        assert write.current is not None
        return write.current

    def _pin_line(self, slug: str = "mobile-build",
                  note: str = "until the signing key is renewed",
                  by: str = "ada") -> Pin:
        write = self.tree.set_entry_maintenance(
            PATH, slug, note, set_by=by,
            expires_at=datetime.now(UTC) + timedelta(hours=5, minutes=30))
        assert write.current is not None
        return write.current

    def _post(self, **fields: str) -> Any:
        """A write, addressed as the node's own page addresses it."""
        return self.client.post("/pins/maintenance",
                                data={"path": FORM_PATH, **fields})

    def _get(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def _hidden(form: Element) -> dict[str, str]:
        return {box.attrs["name"]: box.attrs.get("value", "")
                for box in form.all(tag="input")
                if box.attrs.get("type") == "hidden"}

    def _as_filled(self, form: Element) -> dict[str, str]:
        """What a browser posts for ``form`` with nothing in it touched."""
        fields = self._hidden(form)
        fields["note"] = form.one(tag="textarea").source()
        [expiry] = [box for box in form.all(tag="input")
                    if box.attrs.get("name") == "duration"]
        fields["duration"] = expiry.attrs.get("value", "")
        return fields

    @staticmethod
    def _stated(page: Element, scope: str) -> Element:
        """The one block on ``page`` that states a pin of ``scope``."""
        [block] = [block for block in page.all(f"rule-block--{scope}")
                   if not block.has("rule-block--new")]
        return block

    def _edit_form(self, url: str, scope: str) -> Element:
        return self._stated(self._get(url), scope).one(
            "rule-block__edit").one(tag="form")


class ReturnTests(_WriteCase):
    """A line's write from its node's page comes back to the line."""

    def assert_leads_to_line(self, url: str, slug: str) -> None:
        """``url`` is the node's page with the line of ``slug`` named in the
        query — never in a path segment or a fragment, which a slug's own
        characters would break — and the one fixed anchor the page gives it."""
        parts = urlsplit(url)
        self.assertEqual(parts.path, "/status/ci/actions")
        self.assertEqual(parse_qs(parts.query), {"reason": [slug]})
        self.assertEqual(parts.fragment, "pinned-reason")

    def _marked(self, url: str) -> Element:
        """The line the page at ``url`` marks: one, and the only one ringed."""
        page = self._get(url.split("#")[0])
        marked = page.with_id("pinned-reason")
        self.assertEqual(page.all("is-focused"), [marked])
        return marked

    def test_setting_a_lines_pin_comes_back_to_the_line(self):
        response = self._post(slug="web-build", action="set", set_at="",
                              note="on it", duration="2h")
        self.assertEqual(response.status_code, 302)
        there = response.headers["Location"]
        self.assert_leads_to_line(there, "web-build")
        marked = self._marked(there)
        self.assertEqual(marked.one("check-reason__body").text(),
                         LINES["web-build"])
        self.assertEqual(self._stated(marked, "line").one(
            "rule-block__note").text(), "on it")

    def test_editing_and_clearing_a_lines_pin_come_back_to_it(self):
        entry = self._pin_line()
        edit = self._post(slug="mobile-build", action="set",
                          set_at=entry.token, note="longer", duration="3d")
        self.assertEqual(edit.status_code, 302)
        self.assert_leads_to_line(edit.headers["Location"], "mobile-build")
        now = self.tree.entry_maintenance(PATH, "mobile-build")
        assert now is not None
        self.assertEqual(now.note, "longer")
        clear = self._post(slug="mobile-build", action="clear",
                           set_at=now.token)
        self.assertEqual(clear.status_code, 302)
        there = clear.headers["Location"]
        self.assert_leads_to_line(there, "mobile-build")
        self.assertIsNone(self.tree.entry_maintenance(PATH, "mobile-build"))
        # the line it comes back to stands unpinned, and is the one marked
        marked = self._marked(there)
        self.assertEqual(marked.one("check-reason__body").text(),
                         LINES["mobile-build"])
        self.assertFalse(marked.has("is-quiet"))

    def test_a_slug_travels_in_the_query_whatever_it_holds(self):
        # a discovered entry's slug holds a slash and a declared one may hold a
        # hash or a percent (ADR-0036 decision 12): each comes back whole
        for slug in ("acme/api-pr-412", "disk#2-at-90%"):
            with self.subTest(slug=slug):
                response = self._post(slug=slug, action="set", set_at="",
                                      note="noted", duration="2h")
                there = response.headers["Location"]
                self.assert_leads_to_line(there, slug)
                self.assertEqual(
                    self._marked(there).one("check-reason__body").text(),
                    LINES[slug])

    def test_the_line_is_named_however_the_form_spelled_the_path(self):
        # a client of its own may post the absolute path and no way back
        response = self.client.post("/pins/maintenance", data={
            "path": PATH, "slug": "web-build", "action": "set", "set_at": "",
            "note": "on it", "duration": "2h"})
        self.assertEqual(response.status_code, 302)
        self.assert_leads_to_line(response.headers["Location"], "web-build")

    def test_a_nodes_own_pin_comes_back_to_its_page_as_it_did(self):
        # its block stands at the top of the page, where the page opens
        response = self._post(action="set", set_at="", note="the fleet",
                              duration="2h")
        self.assertEqual(response.status_code, 302)
        parts = urlsplit(response.headers["Location"])
        self.assertEqual((parts.path, parts.query, parts.fragment),
                         ("/status/ci/actions", "", ""))

    def test_a_write_that_says_where_it_came_from_goes_back_there(self):
        # *Handled* and the wall name their own way back (`next`);
        # a line's write from there returns there, not to the node's page
        back = "/handled?node=/ci/actions#pinned-node"
        response = self.client.post("/pins/maintenance", data={
            "path": PATH, "slug": "web-build", "action": "set", "set_at": "",
            "note": "on it", "duration": "2h", "next": back})
        self.assertEqual(response.status_code, 302)
        parts, wanted = urlsplit(response.headers["Location"]), urlsplit(back)
        self.assertEqual((parts.path, parts.query, parts.fragment),
                         (wanted.path, wanted.query, wanted.fragment))

    def _ways_back(self, page: Element) -> list[str]:
        """Every way off a refusal's page: its plain links back, and the `next`
        of each form that names the pin."""
        links = [link.attrs["href"] for link in page.all(tag="a")
                 if link.has("btn")]
        carried = [hidden["next"] for hidden in map(self._hidden,
                                                    page.all(tag="form"))
                   if "path" in hidden]
        self.assertGreater(len(links), 0)
        self.assertGreater(len(carried), 0)
        return links + carried

    def test_a_refused_lines_write_leads_back_to_the_line(self):
        entry = self._pin_line()
        self.tree.set_entry_maintenance(
            PATH, "mobile-build", "somebody else's words", set_by="ben",
            expires_at=datetime.now(UTC) + timedelta(days=1),
            expected_set_at=entry.token)
        stale = self._post(slug="mobile-build", action="set",
                           set_at=entry.token, note="mine", duration="1d")
        self.assertEqual(stale.status_code, 200)
        page = parse(stale.get_data(as_text=True))
        for way in self._ways_back(page):
            self.assert_leads_to_line(way, "mobile-build")
        # and saving from the refusal's own form takes that way
        [form] = [form for form in page.all(tag="form")
                  if form.all(tag="textarea")]
        saved = self.client.post("/pins/maintenance", data=self._as_filled(form))
        self.assertEqual(saved.status_code, 302)
        self.assert_leads_to_line(saved.headers["Location"], "mobile-build")
        # an expiry the route will not read is refused onto the same page
        now = self.tree.entry_maintenance(PATH, "mobile-build")
        assert now is not None
        unread = self._post(slug="mobile-build", action="set",
                            set_at=now.token, note="mine",
                            duration="yesterday")
        self.assertEqual(unread.status_code, 200)
        for way in self._ways_back(parse(unread.get_data(as_text=True))):
            self.assert_leads_to_line(way, "mobile-build")


class NothingChangedTests(_WriteCase):
    """A save that changes neither the note nor the expiry writes nothing."""

    def test_a_nodes_pin_saved_as_it_was_filled_writes_nothing(self):
        entry = self._pin_node(by="ada")
        saves = self.store.saves
        fields = self._as_filled(self._edit_form("/status" + PATH, "node"))
        self.assertEqual(fields["note"], entry.note)
        self.assertNotEqual(fields["duration"], "")
        response = self.client.post("/pins/maintenance", data=fields)
        # answered as a save is
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.headers["Location"]).path,
                         "/status/ci/actions")
        # the pin is the one that stood: its token, its authors, all of it
        self.assertEqual(self.tree.maintenance_entry(PATH), entry)
        self.assertEqual(self.store.saves, saves)
        # so it still reads as ada's, and as never changed
        block = self._stated(self._get("/status" + PATH), "node")
        self.assertIn("is in maintenance by ada until",
                      block.one("rule-block__what").text())
        record = block.one("rule-block__edit").one("rule-block__record").text()
        self.assertEqual(
            record, f"Pinned by ada {app_module._localtime(entry.created_at)}.")

    def test_a_lines_pin_saved_as_it_was_filled_writes_nothing(self):
        entry = self._pin_line(by="ada")
        saves = self.store.saves
        fields = self._as_filled(self._edit_form("/status" + PATH, "line"))
        self.assertEqual(fields["slug"], "mobile-build")
        response = self.client.post("/pins/maintenance", data=fields)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.tree.entry_maintenance(PATH, "mobile-build"),
                         entry)
        self.assertEqual(self.store.saves, saves)

    def test_the_maintenance_pages_form_too(self):
        entry = self._pin_node(by="ada")
        saves = self.store.saves
        fields = self._as_filled(self._edit_form("/handled", "node"))
        self.assertEqual(fields["path"], PATH)
        response = self.client.post("/pins/maintenance", data=fields)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.headers["Location"]).path,
                         "/handled")
        self.assertEqual(self.tree.maintenance_entry(PATH), entry)
        self.assertEqual(self.store.saves, saves)
        # the page's own record of the pin gains no second sentence
        block = self._stated(self._get("/handled"), "node")
        [record] = [child for child in block.children
                    if isinstance(child, Element)
                    and child.has("rule-block__record")]
        self.assertEqual(
            record.text(),
            f"Pinned by ada {app_module._localtime(entry.created_at)}.")

    def test_a_note_left_blank_with_the_expiry_kept_changes_nothing(self):
        # a blank note on an edit keeps the stored one (ADR-0014 decision 15),
        # so a form that says nothing new in either field says nothing
        entry = self._pin_node(by="ada")
        saves = self.store.saves
        fields = self._as_filled(self._edit_form("/status" + PATH, "node"))
        fields["note"] = ""
        self.assertEqual(
            self.client.post("/pins/maintenance", data=fields).status_code, 302)
        self.assertEqual(self.tree.maintenance_entry(PATH), entry)
        self.assertEqual(self.store.saves, saves)

    def test_another_open_editor_stays_usable(self):
        # two editors of one pin, drawn from the same pin: the first is saved
        # as it was, and the second's real change is not refused as stale
        self._pin_node(by="ada")
        first = self._as_filled(self._edit_form("/status" + PATH, "node"))
        second = dict(first, note="the runners are back on Monday")
        self.assertEqual(
            self.client.post("/pins/maintenance", data=first).status_code, 302)
        answer = self.client.post("/pins/maintenance", data=second)
        self.assertEqual(answer.status_code, 302)       # not the refusal's 200
        now = self.tree.maintenance_entry(PATH)
        assert now is not None
        self.assertEqual((now.note, now.set_by, now.created_by),
                         ("the runners are back on Monday", "pan", "ada"))

    def test_a_changed_note_or_a_typed_expiry_is_saved_as_before(self):
        entry = self._pin_node(by="ada")
        saves = self.store.saves
        fields = self._as_filled(self._edit_form("/status" + PATH, "node"))
        self.client.post("/pins/maintenance",
                         data=dict(fields, note=entry.note + " (again)"))
        noted = self.tree.maintenance_entry(PATH)
        assert noted is not None
        self.assertEqual((noted.note, noted.set_by, noted.expires_at),
                         (entry.note + " (again)", "pan", entry.expires_at))
        self.assertNotEqual(noted.set_at, entry.set_at)
        self.assertEqual(self.store.saves, saves + 1)
        fields = self._as_filled(self._edit_form("/status" + PATH, "node"))
        self.client.post("/pins/maintenance", data=dict(fields, duration="3d"))
        moved = self.tree.maintenance_entry(PATH)
        assert moved is not None
        self.assertEqual(moved.note, noted.note)
        self.assertNotEqual(moved.expires_at, noted.expires_at)
        self.assertNotEqual(moved.set_at, noted.set_at)
        self.assertEqual(self.store.saves, saves + 2)


class RefusalHeadingTests(_WriteCase):
    """A refused write is headed by the node's path as every page writes it."""

    def _heading(self, **fields: str) -> str:
        response = self.client.post("/pins/maintenance", data={
            "action": "set", "set_at": "", "duration": "yesterday", **fields})
        self.assertEqual(response.status_code, 200)
        return parse(response.get_data(as_text=True)).one(tag="h1").text()

    def test_it_reads_the_same_however_the_form_spelled_the_path(self):
        # a node's own page posts the route's `branch`, *Handled* and
        # the wall the absolute path
        for posted in (FORM_PATH, PATH):
            with self.subTest(path=posted):
                self.assertEqual(self._heading(path=posted),
                                 "Maintenance — /ci/actions")
                self.assertEqual(
                    self._heading(path=posted, slug="web-build"),
                    "Maintenance — /ci/actions · one reason")
