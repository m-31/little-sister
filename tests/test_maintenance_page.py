"""The Maintenance page is the same blocks (ADR-0104 decision 6).

Every pin stands under its node's path — the node's own first, then its lines' in
the check's order — as the block a node's own page states it in, read by everyone
and changed there by an admin. The page it replaces was a table to read: one row a
pin, and a link to follow to change one.

What the strip's pill and its popover count is untouched, and `test_web_pins.py`
holds it.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.maintenance import MaintenanceEntry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, css_rule, css_rules_naming, parse

PATH = "/ci/actions"
LINES = {
    "web-build": "web build failed on main",
    "api-build": "api build failed on main",
    "mobile-build": "[mobile build](https://ci.example.org/mobile) is disabled",
    "docs-deploy": "docs deploy is queued",
}
NOTE = ("Runner fleet is being replaced this **weekend**, ticket "
        "[OPS-1432](https://tickets.example.org/OPS-1432).\n\n"
        "Builds queue until Sunday night.")
LINE_NOTE = "Switched off until the signing key is renewed."


class _PageCase(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert(PATH, StatusCode.ERROR, dict(LINES))

    def _viewer(self) -> None:
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    def _pin_node(self, path: str = PATH, note: str | None = NOTE,
                  by: str = "lex",
                  left: timedelta = timedelta(days=1, hours=23, minutes=30),
                  ) -> MaintenanceEntry:
        write = self.tree.set_maintenance(
            path, note, expires_at=datetime.now(UTC) + left, set_by=by)
        assert write.current is not None
        return write.current

    def _pin_line(self, slug: str = "mobile-build", note: str = LINE_NOTE,
                  by: str = "anna",
                  left: timedelta = timedelta(hours=5, minutes=30),
                  path: str = PATH) -> MaintenanceEntry:
        write = self.tree.set_entry_maintenance(
            path, slug, note, expires_at=datetime.now(UTC) + left, set_by=by)
        assert write.current is not None
        return write.current

    def _body(self) -> str:
        response = self.client.get("/maintenance")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def _page(self) -> Element:
        return parse(self._body())

    @staticmethod
    def _path(node: Element) -> str:
        """The path a section of the page is headed by."""
        return node.first().one(tag="a").text()

    def _node(self, page: Element, path: str = PATH) -> Element:
        """The section of the page that holds one node's pins."""
        found = [node for node in page.all("pin-node")
                 if self._path(node) == path]
        self.assertEqual(len(found), 1)
        return found[0]

    def assert_leads_back(self, url: str, path: str = PATH) -> None:
        """``url`` is the Maintenance page with ``path``'s section marked, which
        the page scrolls to.

        The node is named in the **query** and the fragment is one fixed id — the
        shape `?reason=<slug>#pinned-reason` has on a node's own page. A fragment
        alone would not do: a refused write is answered *at* `/maintenance`, and
        a link from there to `/maintenance#…` is a jump within that answer, which
        loads nothing."""
        parts = urlsplit(url)
        self.assertEqual(parts.path, "/maintenance")
        self.assertEqual(parse_qs(parts.query), {"node": [path]})
        self.assertEqual(parts.fragment, "pinned-node")

    @staticmethod
    def _hidden(form: Element) -> dict[str, str]:
        return {box.attrs["name"]: box.attrs.get("value", "")
                for box in form.all(tag="input")
                if box.attrs.get("type") == "hidden"}


class GroupingTests(_PageCase):
    """Grouped under each node's path, the whole node first and then its lines
    in the check's order."""

    def test_pins_stand_under_their_nodes_path(self):
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        self._pin_node("/db", note="cutover", by="ada")
        self._pin_node()
        self._pin_line()
        page = self._page()
        nodes = page.all("pin-node")
        self.assertEqual([self._path(node) for node in nodes], [PATH, "/db"])
        for node, path in zip(nodes, (PATH, "/db"), strict=True):
            heading = node.first()
            self.assertEqual(heading.tag, "h2")
            self.assertEqual(heading.one(tag="a").attrs.get("href"),
                             "/status" + path)
        self.assertEqual([len(node.all("rule-block")) for node in nodes], [2, 1])
        # and nothing of the table it was
        self.assertEqual(page.all("maintenance-page"), [])
        self.assertEqual(page.all("row-maintenance"), [])

    def test_the_whole_node_stands_first_then_its_lines_in_the_checks_order(self):
        # the order a check writes its lines in is information; the order they
        # were pinned in is not
        self._pin_line("docs-deploy")
        self._pin_line("web-build")
        self._pin_node()
        blocks = self._node(self._page()).all("rule-block")
        self.assertEqual(
            [("node" if block.has("rule-block--node") else "line")
             for block in blocks], ["node", "line", "line"])
        said = [block.one("rule-block__what").text() for block in blocks]
        self.assertTrue(said[0].startswith("The whole node is silenced by lex"))
        self.assertTrue(said[1].startswith("web build failed on main — this line"))
        self.assertTrue(said[2].startswith("docs deploy is queued — this line"))

    def test_a_node_with_only_its_lines_pinned_has_no_whole_node_block(self):
        self._pin_line()
        blocks = self._node(self._page()).all("rule-block")
        self.assertEqual(len(blocks), 1)
        self.assertTrue(blocks[0].has("rule-block--line"))

    def test_the_heading_carries_the_nodes_title(self):
        self.tree.upsert("/db", StatusCode.ERROR, "boom",
                         title="The orders database")
        self._pin_node("/db", by="ada")
        heading = self._node(self._page(), "/db").first()
        self.assertEqual(heading.one("node-title").text(), "The orders database")

    def test_the_page_says_how_many_pins_stand_on_how_many_nodes(self):
        self._pin_line()
        self.assertEqual(self._page().one("pin-count").text(),
                         "1 pin on 1 node.")
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        self._pin_node("/db", by="ada")
        self._pin_node()
        self.assertEqual(self._page().one("pin-count").text(),
                         "3 pins on 2 nodes.")

    def test_the_node_a_change_came_from_is_marked(self):
        # a saved edit comes back with its node named, and the page marks that
        # section and no other: one anchor on the page, and only when asked for
        self.tree.upsert("/db", StatusCode.ERROR, "boom")
        self._pin_node("/db", by="ada")
        self._pin_node()

        def marked(url: str) -> list[str]:
            page = parse(self.client.get(url).get_data(as_text=True))
            nodes = page.all("pin-node")
            self.assertEqual(len(nodes), 2)
            named = [node for node in nodes
                     if node.attrs.get("id") == "pinned-node"]
            self.assertEqual(named, [node for node in nodes
                                     if node.has("is-focused")])
            self.assertEqual([node for node in nodes if "id" in node.attrs],
                             named)
            return [self._path(node) for node in named]

        self.assertEqual(marked("/maintenance"), [])
        self.assertEqual(marked("/maintenance?node=/db"), ["/db"])
        self.assertEqual(marked("/maintenance?node=/ci/actions"), [PATH])
        self.assertEqual(marked("/maintenance?node=/nowhere"), [])

    def test_nothing_pinned_says_so(self):
        raw = self._body()
        self.assertIn("No nodes are in maintenance.", raw)
        page = parse(raw)
        self.assertEqual(page.all("pin-node") + page.all("pin-count"), [])


class BlockTests(_PageCase):
    """Each pin is the block a node's own page states it in."""

    def test_a_nodes_pin_reads_as_on_its_own_page(self):
        entry = self._pin_node()
        block = self._node(self._page()).one("rule-block")
        self.assertEqual(block.attrs.get("data-rule"), "maintenance")
        until = app_module._localtime(entry.expires_at)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"The whole node is silenced by lex until {until} · 1d 23h left")
        note = block.one("rule-block__note")
        self.assertEqual(len(note.all(tag="p")), 2)
        self.assertEqual(note.one(tag="strong").text(), "weekend")
        self.assertTrue(note.text().endswith("Builds queue until Sunday night."))

    def test_a_lines_pin_names_the_line_it_silences(self):
        entry = self._pin_line()
        block = self._node(self._page()).one("rule-block")
        until = app_module._localtime(entry.expires_at)
        said = block.one("rule-block__what")
        self.assertEqual(
            said.text(),
            f"mobile build is disabled — this line is silenced by anna until "
            f"{until} · 5h 29m left")
        # the line as its node writes it, its own link kept
        self.assertEqual(
            [link.attrs.get("href") for link in said.all(tag="a")
             if link.text() == "mobile build"],
            ["https://ci.example.org/mobile"])
        self.assertEqual(block.one("rule-block__note").text(), LINE_NOTE)

    def test_under_its_nodes_pin_a_line_says_it_is_also_silenced_on_its_own(self):
        self._pin_node()
        self._pin_line()
        blocks = self._node(self._page()).all("rule-block")
        self.assertIn("this line is also silenced on its own by anna until",
                      blocks[1].one("rule-block__what").text())
        self.assertNotIn("also", blocks[0].one("rule-block__what").text())

    def test_a_lines_block_leads_to_its_line_on_the_nodes_page(self):
        # on a node with 150 lines the right page is not yet the right line
        self._pin_line()
        said = self._node(self._page()).one("rule-block").one("rule-block__what")
        links = [link for link in said.all(tag="a") if link.text() == "this line"]
        self.assertEqual(len(links), 1)
        href = links[0].attrs["href"]
        self.assertEqual(href, "/status/ci/actions?reason=mobile-build#pinned-reason")
        marked = self.client.get(href.split("#")[0]).get_data(as_text=True)
        self.assertIn('id="pinned-reason"', marked)

    def test_the_slug_is_never_written_as_text(self):
        # ADR-0036 makes it opaque: it travels in a link and in a form's field
        self._pin_line()
        self.assertNotIn("mobile-build", self._page().text())

    def test_who_pinned_it_stands_in_the_block_for_everyone(self):
        # the page has room for the pin's whole reading, and a viewer has no
        # editor to find it in
        entry = self._pin_node(by="ada")
        pinned = app_module._localtime(entry.created_at)

        def record() -> str:
            block = self._node(self._page()).one("rule-block")
            records = [child for child in block.children
                       if isinstance(child, Element)
                       and child.has("rule-block__record")]
            self.assertEqual(len(records), 1)
            return records[0].text()

        self.assertEqual(record(), f"Pinned by ada {pinned}.")
        self.client.post("/maintenance", data={
            "path": PATH, "action": "set", "reason": "longer", "duration": "3d",
            "set_at": entry.token})
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        changed = app_module._localtime(after.set_at)
        said = f"Pinned by ada {pinned}. Last changed by pan {changed}."
        self.assertEqual(record(), said)
        self._viewer()
        self.assertEqual(record(), said)

    def test_the_blocks_instants_are_kept_whole_here_too(self):
        # the sentence's expiry, and under the note who pinned it and when
        entry = self._pin_node(by="ada")
        self._viewer()                    # one record: a viewer has no editor
        block = self._node(self._page()).one("rule-block")
        until = app_module._localtime(entry.expires_at).split(" ")
        pinned = app_module._localtime(entry.created_at).split(" ")
        self.assertEqual(
            [span.text() for span in block.one("rule-block__what").all("text-nowrap")],
            [*until, "· 1d 23h left"])
        self.assertEqual(
            [span.text()
             for span in block.one("rule-block__record").all("text-nowrap")],
            pinned)

    def test_a_nodes_own_page_keeps_the_record_in_its_editor(self):
        # there the block's place says what it covers and the editor names its
        # authors; the read state is the sentence and the note
        self._pin_node(by="ada")
        page = parse(self.client.get("/status" + PATH).get_data(as_text=True))
        block = next(block for block in page.all("rule-block--node")
                     if not block.has("rule-block--new"))
        self.assertEqual(
            [child for child in block.children if isinstance(child, Element)
             and child.has("rule-block__record")], [])
        self.assertEqual(len(block.all("rule-block__record")), 1)

    def test_a_viewer_reads_the_blocks_and_gets_no_buttons(self):
        self._pin_node()
        self._pin_line()
        self._viewer()
        raw = self._body()
        node = self._node(parse(raw))
        blocks = node.all("rule-block")
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertTrue(block.all("rule-block__note"))
            self.assertTrue(block.all("rule-block__record"))
        self.assertEqual(node.all(tag="form") + node.all(tag="details")
                         + node.all(tag="button") + node.all(tag="summary"), [])
        self.assertNotIn('name="set_at"', raw)


class ChangedThereTests(_PageCase):
    """Each read and changed there: Edit and Clear for an admin, in place."""

    def _forms(self, block: Element) -> tuple[Element, Element]:
        editor = block.one("rule-block__edit")
        self.assertEqual(editor.tag, "details")
        self.assertNotIn("open", editor.attrs)
        return editor.one(tag="form"), block.one("rule-block__clear")

    def test_a_nodes_pin_is_edited_and_cleared_from_the_page(self):
        entry = self._pin_node(by="ada")
        block = self._node(self._page()).one("rule-block")
        edit, clear = self._forms(block)
        was = app_module._expiry_input(entry.expires_at)
        hidden = self._hidden(edit)
        self.assert_leads_back(hidden.pop("next"))
        self.assertEqual(
            hidden,
            {"path": PATH, "action": "set", "set_at": entry.token,
             "expiry_was": was})
        self.assertEqual(edit.one(tag="textarea").source(), NOTE)
        self.assertEqual([button.text() for button in edit.all(tag="button")],
                         ["Save changes", "Cancel"])
        hidden = self._hidden(clear)
        self.assert_leads_back(hidden.pop("next"))
        self.assertEqual(
            hidden, {"path": PATH, "action": "clear", "set_at": entry.token})

    def test_a_lines_pin_is_edited_and_cleared_from_the_page(self):
        entry = self._pin_line()
        block = self._node(self._page()).one("rule-block")
        edit, clear = self._forms(block)
        hidden = self._hidden(edit)
        self.assert_leads_back(hidden["next"])
        self.assertEqual(
            (hidden["path"], hidden["slug"], hidden["action"], hidden["set_at"]),
            (PATH, "mobile-build", "set", entry.token))
        self.assertEqual(edit.one(tag="textarea").source(), LINE_NOTE)
        hidden = self._hidden(clear)
        self.assert_leads_back(hidden.pop("next"))
        self.assertEqual(
            hidden,
            {"path": PATH, "slug": "mobile-build", "action": "clear",
             "set_at": entry.token})

    def test_saving_an_edit_comes_back_to_the_nodes_place_on_the_page(self):
        entry = self._pin_node(by="ada")
        edit, _ = self._forms(self._node(self._page()).one("rule-block"))
        posted = self._hidden(edit)
        posted["reason"] = "reworded"
        posted["duration"] = posted["expiry_was"]
        response = self.client.post("/maintenance", data=posted)
        self.assertEqual(response.status_code, 302)
        self.assert_leads_back(response.headers["Location"])
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        self.assertEqual((after.reason, after.expires_at, after.set_by),
                         ("reworded", entry.expires_at, "pan"))
        # and the page it comes back to shows it, on the node it was changed on
        landed = parse(self.client.get(
            response.headers["Location"]).get_data(as_text=True))
        node = landed.with_id("pinned-node")
        self.assertEqual(self._path(node), PATH)
        self.assertEqual(node.one("rule-block").one("rule-block__note").text(),
                         "reworded")

    def test_clearing_comes_back_to_the_page(self):
        self._pin_node()
        self._pin_line()
        blocks = self._node(self._page()).all("rule-block")
        _, clear = self._forms(blocks[1])
        response = self.client.post("/maintenance", data=self._hidden(clear))
        self.assertEqual(response.status_code, 302)
        self.assert_leads_back(response.headers["Location"])
        self.assertIsNone(self.tree.entry_maintenance(PATH, "mobile-build"))
        self.assertIsNotNone(self.tree.maintenance_entry(PATH))
        self.assertEqual(len(self._node(self._page()).all("rule-block")), 1)

    def test_a_refused_edit_leads_back_to_the_page(self):
        stale = self._pin_node(note="ada wrote this", by="ada")
        edit, _ = self._forms(self._node(self._page()).one("rule-block"))
        posted = self._hidden(edit)
        self._pin_node(note="ben wrote this", by="ben", left=timedelta(days=5))
        posted["reason"] = "pan wrote this"
        posted["duration"] = posted["expiry_was"]
        response = self.client.post("/maintenance", data=posted)
        self.assertEqual(response.status_code, 200)
        raw = response.get_data(as_text=True)
        self.assertIn("Nothing was saved", raw)
        self.assertEqual(posted["set_at"], stale.token)
        refusal = parse(raw)
        back = [link.attrs["href"] for link in refusal.all(tag="a")
                if link.text() == "Change nothing"]
        self.assertEqual(len(back), 1)
        self.assert_leads_back(back[0])
        # the refusal is answered at /maintenance, so a way back that differed
        # from that only by its fragment would load nothing
        self.assertNotEqual(back[0].split("#")[0], "/maintenance")
        # and each of the refusal's own forms carries the same way back
        forms = [self._hidden(form) for form in refusal.all(tag="form")]
        carried = [hidden["next"] for hidden in forms if "path" in hidden]
        self.assertGreater(len(carried), 0)
        self.assertEqual(set(carried), {back[0]})

    def test_the_controls_say_which_pin_they_change(self):
        # a page of many blocks is a page of many Edits: each names its node,
        # and is described by the sentence it belongs to
        # two nodes pinned alike, whole and one line each: a block's place
        # under its own node is then the same number on both
        self.tree.upsert("/db", StatusCode.ERROR, {"replica": "lagging"})
        self._pin_node("/db", by="ada")
        self._pin_line("replica", path="/db")
        self._pin_node()
        self._pin_line()
        page = self._page()
        blocks = self._node(page).all("rule-block")
        names = []
        for block, scope in zip(blocks, ("node", "line"), strict=True):
            said = block.one("rule-block__what")
            edit = block.one("rule-block__edit").first()
            clear = block.one("rule-block__clear").one(tag="button")
            self.assertEqual(edit.text(shown=True), "Edit")
            self.assertEqual(edit.text(),
                             f"Edit this {scope}'s maintenance, {PATH}")
            self.assertEqual(clear.text(shown=True), "Clear")
            self.assertEqual(clear.text(),
                             f"Clear this {scope}'s maintenance, {PATH}")
            for control in (edit, clear):
                self.assertEqual(control.attrs.get("aria-describedby"),
                                 said.attrs.get("id"))
            names.append(said.attrs["id"])
        self.assertEqual(len(set(names)), 2)
        # and no id on the page stands twice, whichever node a block is under:
        # a label reaches its field by it, and a button its sentence
        others = self._node(page, "/db").all("rule-block")
        self.assertEqual(
            [other.one("rule-block__edit").first().text() for other in others],
            ["Edit this node's maintenance, /db",
             "Edit this line's maintenance, /db"])
        ids = [element.attrs["id"] for element in page.walk()
               if "id" in element.attrs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_id_stands_twice_however_many_pins_there_are(self):
        # a block's ids are built from its node's place on the page and its own
        # place under the node; with eleven of each, the two numbers written
        # without a mark between them would read alike — 1 and 11, 11 and 1
        jobs = {f"job-{number:02d}": "failed" for number in range(1, 11)}
        self.tree.upsert("/a", StatusCode.ERROR, dict(jobs))
        self._pin_node("/a")
        for slug in jobs:
            self._pin_line(slug, path="/a")
        for number in range(1, 10):
            self.tree.upsert(f"/b{number:02d}", StatusCode.ERROR, "boom")
            self._pin_node(f"/b{number:02d}")
        self.tree.upsert("/b10", StatusCode.ERROR, {"replica": "lagging"})
        self._pin_line("replica", path="/b10")
        page = self._page()
        nodes = page.all("pin-node")
        self.assertEqual(
            [len(node.all("rule-block")) for node in nodes],
            [11, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1])
        ids = [element.attrs["id"] for element in page.walk()
               if "id" in element.attrs]
        self.assertEqual(len(ids), len(set(ids)))
        # and each control still points at the sentence of its own block
        for block in page.all("rule-block"):
            said = block.one("rule-block__what").attrs["id"]
            self.assertEqual(
                block.one("rule-block__edit").first().attrs["aria-describedby"],
                said)

    def test_the_editors_script_is_on_the_page(self):
        # Cancel and Escape, the note first, the expiry selected in its field
        self._pin_node()
        self.assertRegex(
            self._body(), r'src="/static/js/maintenance-edit\.js\?v=[0-9a-f]{8}"')

    def test_an_open_editor_stands_in_for_what_the_block_read(self):
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        self.assertIn(
            "display: none",
            css_rule(css, ".rule-block:has(.rule-block__edit[open]) "
                          "> .rule-block__record"))
        # the table's own rules went with the table
        self.assertEqual(css_rules_naming(css, ".maintenance-page"), [])

    def test_a_block_keeps_to_the_pages_width(self):
        # the blocks are children of a grid, which gives each the width of what
        # it holds unless told otherwise — an open editor's fields, on a phone
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        self.assertIn("min-width: 0",
                      css_rule(css, ".pin-node__pins > .rule-block"))
        # and what the sentence links to wears the block's ink, not a link's:
        # the pair the block is measured in
        for selector in (".rule-block__what a", ".rule-block__what code"):
            with self.subTest(rule=selector):
                self.assertIn("color: inherit", css_rule(css, selector))
