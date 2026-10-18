"""The wall and a branch's page edit a pin in place (ADR-0104 decisions 2, 3 and 7).

The third of the pin block's three surfaces. A card on the wall states its node's pin
as the block a node's own page states it in, and an unpinned card's pause mark opens
the pin's editor in the card; a branch's page states its node's pin in its head and
sets one from there. With them the dialog that floated over the wall, its script and
the card at the foot of a branch's page are gone.

The editors stand inside the part of the page the ten-second refresh swaps, so the
refresh waits while one is open. That half is the browser's to show
(`tests/test_pin_browser.py`); what the gate holds of it is that the fragment carries
the same editors as the page, each with the page's own address to come back to, and
what the script and the sheet go by: the shape of an editor, the stamp's words, the
minute, and the rules that keep a mark on its seat.

The pages are read as trees (`tests/page_tree.py`) wherever the claim is about
*where* something stands.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.maintenance import MaintenanceEntry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, css_rule, css_rules_naming, parse

NOTE = ("Kernel update and reboot, ticket "
        "[OPS-1511](https://tickets.example.org/OPS-1511).\n\n"
        "The spare is in the rack.\n\n"
        "Back by 23:30.")
LEFT = timedelta(days=1, hours=23, minutes=30)


class _WallCase(TestCase):
    """A small estate on the wall — two hosts, a leaf of its own and a deeper
    branch — read by an admin unless a test says otherwise."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        for host in ("gaffsie", "hemulen"):
            for part in ("cpu", "disk", "memory"):
                self.tree.upsert(f"/{host}/{part}", StatusCode.OK)
        self.tree.upsert("/uplink", StatusCode.OK)
        for drive in ("drive1", "drive2"):
            self.tree.upsert(f"/nexus/qnap/smart/{drive}", StatusCode.OK)
        self.tree.upsert("/nexus/load", StatusCode.WARN, "load is 9.2")

    def _viewer(self) -> None:
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    def _kiosk(self) -> None:
        self.client.set_cookie("ls_prefs", "layout=kiosk")

    def _pin(self, path: str, note: str | None = NOTE, by: str = "lex",
             left: timedelta = LEFT) -> MaintenanceEntry:
        write = self.tree.set_maintenance(
            path, note, expires_at=datetime.now(UTC) + left, set_by=by)
        assert write.current is not None
        return write.current

    def _body(self, url: str = "/status") -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def _page(self, url: str = "/status") -> Element:
        return parse(self._body(url))

    @staticmethod
    def _card(page: Element, path: str) -> Element:
        """The wall's card of the node at ``path``."""
        cards = [card for card in page.all("status-card")
                 if card.one("status-card__head").attrs.get("data-path") == path]
        assert len(cards) == 1, f"{len(cards)} cards for {path}, wanted one"
        return cards[0]

    @staticmethod
    def _row(page: Element, path: str) -> Element:
        """The head's row of the box that stands for the node at ``path``."""
        rows = [row for row in page.all("status-node__self")
                if row.attrs.get("data-path") == path]
        assert len(rows) == 1
        return rows[0]

    @classmethod
    def _box(cls, page: Element, path: str) -> Element:
        """The box inside a card that stands for the node at ``path``."""
        box = cls._row(page, path).parent
        assert box is not None
        return box

    @staticmethod
    def _stated(where: Element) -> list[Element]:
        """The blocks that state a pin — not the editors of one still to be set."""
        return [block for block in where.all("rule-block")
                if not block.has("rule-block--new")]

    @staticmethod
    def _hidden(form: Element) -> dict[str, str]:
        return {box.attrs["name"]: box.attrs.get("value", "")
                for box in form.all(tag="input")
                if box.attrs.get("type") == "hidden"}

    @staticmethod
    def _setter(where: Element) -> Element:
        """The one disclosure in ``where`` that sets a pin still to be set."""
        found = [details for details in where.all(tag="details")
                 if details.all("rule-block--new")]
        assert len(found) == 1, f"{len(found)} setters, wanted one"
        return found[0]

    @staticmethod
    def _mark(head: Element) -> Element | None:
        """An admin's ‖ among the head's icons, or None."""
        found = [icon for icon in head.all("node-icon")
                 if icon.attrs.get("data-control") == "pin"]
        assert len(found) <= 1
        return found[0] if found else None

    @staticmethod
    def _editor(page: Element) -> Element:
        """The page's one editor of a pin still to be set, in its template."""
        found = [t for t in page.all(tag="template")
                 if t.attrs.get("id") == "pin-editor"]
        assert len(found) == 1, f"{len(found)} pin editors on the page, wanted one"
        return found[0].one("pin-setter")

    def _until(self, entry: MaintenanceEntry) -> str:
        return str(app_module._localtime(entry.expires_at))


class CardBlockTests(_WallCase):
    """Decisions 1 and 2: on the wall the block stands in the card."""

    def test_a_pinned_card_states_its_pin_as_the_block(self):
        entry = self._pin("/gaffsie")
        raw = self._body()
        card = self._card(parse(raw), "/gaffsie")
        blocks = self._stated(card)
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block.attrs.get("data-rule"), "maintenance")
        self.assertTrue(block.has("rule-block--node"))
        # in the card's body, under its head and above what the card holds
        self.assertTrue(block.within(card.one("status-panel")))
        self.assertLess(card.one("status-card__head").order, block.order)
        self.assertLess(block.order, card.one("node-children").order)
        # the card names the node, so the sentence opens with what was done to it
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"Silenced by lex until {self._until(entry)} · 1d 23h left")
        # and it is stated once: the strip that said it before is gone
        self.assertNotIn("pin-banner", raw)
        self.assertEqual(raw.count("Silenced by"), 1)

    def test_a_cards_expiry_keeps_its_date_and_its_time_whole(self):
        # #89's B12, seen in a card: *until 2026-10-*, and the day and the time on
        # the next line. A card is the narrowest place a block stands in.
        entry = self._pin("/gaffsie")
        boxed = self._pin("/nexus/qnap", left=timedelta(hours=5, minutes=30))
        page = self._page()
        for where, pin, left in (
                (self._card(page, "/gaffsie"), entry, "1d 23h left"),
                (self._box(page, "/nexus/qnap"), boxed, "5h 29m left")):
            with self.subTest(left=left):
                said = self._stated(where)[0].one("rule-block__what")
                date, time = self._until(pin).split(" ")
                self.assertEqual(date.count("-"), 2)
                self.assertEqual(
                    [span.text() for span in said.all("text-nowrap")],
                    [date, time, f"· {left}"])

    def test_the_note_stands_in_full(self):
        # the strip it replaces was cut off after two lines
        self._pin("/gaffsie")
        note = self._stated(self._card(self._page(), "/gaffsie"))[0].one(
            "rule-block__note")
        self.assertEqual(len(note.all(tag="p")), 3)
        self.assertEqual(note.all(tag="a")[0].attrs["href"],
                         "https://tickets.example.org/OPS-1511")

    def test_an_admin_s_block_carries_edit_and_clear(self):
        entry = self._pin("/gaffsie")
        block = self._stated(self._card(self._page(), "/gaffsie"))[0]
        edit = block.one("rule-block__edit")
        self.assertEqual(edit.tag, "details")
        self.assertEqual(edit.first().tag, "summary")
        self.assertEqual(edit.first().text(),
                         "Edit this node's maintenance, /gaffsie")
        kept = app_module._expiry_input(entry.expires_at)
        self.assertEqual(
            self._hidden(edit.one(tag="form")),
            {"path": "/gaffsie", "action": "set", "set_at": entry.token,
             "next": "/status", "expiry_was": kept})
        self.assertEqual(edit.one(tag="textarea").source(), NOTE)
        clear = block.one("rule-block__clear")
        self.assertEqual(
            self._hidden(clear),
            {"path": "/gaffsie", "action": "clear", "set_at": entry.token,
             "next": "/status"})
        self.assertEqual(clear.one(tag="button").text(),
                         "Clear this node's maintenance, /gaffsie")

    def test_a_viewer_reads_the_block_without_buttons(self):
        self._pin("/gaffsie")
        self._viewer()
        block = self._stated(self._card(self._page(), "/gaffsie"))[0]
        self.assertEqual(len(block.one("rule-block__note").all(tag="p")), 3)
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])

    def test_the_kiosk_s_block_has_no_buttons(self):
        # the kiosk is the wall display: nothing on it is to be clicked
        self._pin("/gaffsie")
        self._kiosk()
        block = self._stated(self._card(self._page(), "/gaffsie"))[0]
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])

    def test_a_box_inside_a_card_states_its_pin_as_the_block_too(self):
        entry = self._pin("/nexus/qnap")
        raw = self._body()
        box = self._box(parse(raw), "/nexus/qnap")
        blocks = self._stated(box)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(
            blocks[0].one("rule-block__what").text(),
            f"Silenced by lex until {self._until(entry)} · 1d 23h left")
        self.assertEqual(
            self._hidden(blocks[0].one("rule-block__clear"))["path"],
            "/nexus/qnap")
        self.assertNotIn("pin-banner", raw)

    def test_a_box_deeper_down_states_its_pin_with_its_buttons(self):
        # a box inside a box is drawn by the same hand, one level further in
        outer = self._pin("/nexus/qnap", note="shelf swap")
        inner = self._pin("/nexus/qnap/smart", note="firmware")
        page = self._page()
        blocks = {path: self._stated(self._box(page, path))
                  for path in ("/nexus/qnap", "/nexus/qnap/smart")}
        # the outer box holds the inner one, and so its block too
        self.assertEqual([len(found) for found in blocks.values()], [2, 1])
        block, = blocks["/nexus/qnap/smart"]
        self.assertEqual(
            self._hidden(block.one("rule-block__clear")),
            {"path": "/nexus/qnap/smart", "action": "clear",
             "set_at": inner.token, "next": "/status"})
        self.assertEqual(
            self._hidden(blocks["/nexus/qnap"][0].one("rule-block__clear"))["set_at"],
            outer.token)
        ids = [element.attrs["id"] for element in page.walk()
               if "id" in element.attrs]
        self.assertEqual(sorted(ids), sorted(set(ids)))

    def test_the_card_of_a_page_at_depth_zero_states_its_pin(self):
        entry = self._pin("/gaffsie")
        page = self._page("/status/gaffsie?depth=0")
        card = self._card(page, "/gaffsie")
        block, = self._stated(card)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"Silenced by lex until {self._until(entry)} · 1d 23h left")
        self.assertEqual(self._hidden(block.one("rule-block__clear"))["next"],
                         "/status/gaffsie?depth=0")
        # the card is the node there: no head says it a second time, and a
        # pinned card has no mark
        self.assertEqual(page.all("viewed-head"), [])
        self.assertEqual(len(self._stated(page)), 1)
        self.assertIsNone(self._mark(card.one("status-card__head")))

    def test_a_pin_on_everything_is_stated_on_the_overviews_own_card(self):
        # At depth 0 the overview is one card, every node there is. A pin on it
        # is not set from the wall, but one that stands is stated like any other
        # and changed there, as on the Maintenance page.
        write = self.tree.set_maintenance(
            "", "datacenter move", expires_at=datetime.now(UTC) + LEFT, set_by="lex")
        entry = write.current
        assert entry is not None
        page = self._page("/status?depth=0")
        block, = self._stated(page)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"Silenced by lex until {self._until(entry)} · 1d 23h left")
        self.assertEqual(
            self._hidden(block.one("rule-block__clear")),
            {"path": "/", "action": "clear", "set_at": entry.token,
             "next": "/status?depth=0"})
        self.assertEqual(page.one("status-grid").all("pin-setter"), [])
        self.assertIsNone(self._mark(page.one("status-card__head")))


class CardSetterTests(_WallCase):
    """Decision 3, as the head's row has it (ADR-0127 decision 3): a pin is set
    where its block will stand — on the wall in the card's panel or a box — by ‖
    among the head's icons, which clones the page's one editor there; without
    script ‖ is a link to the node's page."""

    def test_a_cards_mark_is_the_pin_icon_and_the_page_holds_one_editor(self):
        page = self._page()
        card = self._card(page, "/hemulen")
        mark = self._mark(card.one("status-card__head"))
        assert mark is not None
        # the last of the head's icons: a link to the node's page without script
        self.assertEqual(mark.tag, "a")
        self.assertEqual(mark.attrs.get("href"), "/status/hemulen")
        self.assertEqual(mark.attrs.get("aria-label"), "set maintenance for /hemulen")
        self.assertEqual(mark.attrs.get("title"), "Set maintenance")
        self.assertIn("data-beneath", mark.attrs)     # the pin would cover others
        icons = [icon.attrs.get("data-control") for icon in
                 card.one("status-card__head").one("node-icons").all("node-icon")]
        self.assertEqual(icons[-1], "pin")
        # the card carries no editor; the page holds one, outside the grid, which
        # the script clones into the card's panel, where the pin's block stands
        self.assertEqual(card.all("maintenance-editor-form"), [])
        self.assertEqual(page.one("status-grid").all("pin-setter"), [])
        setter = self._editor(page)
        self.assertTrue(setter.has("maintenance-editor-disclosure"))
        editor = setter.one("rule-block--new")
        self.assertEqual(editor.one("rule-block__scope").text(),
                         "Maintenance for this node.")
        self.assertTrue(editor.one("pin-editor__what"))
        form = editor.one(tag="form")
        self.assertEqual(form.attrs.get("action"), "/maintenance")
        self.assertEqual(
            self._hidden(form),
            {"path": "", "action": "set", "set_at": "", "next": "/status"})
        self.assertEqual(form.one(tag="textarea").attrs.get("name"), "reason")
        expiry, = [box for box in form.all(tag="input")
                   if box.attrs.get("name") == "duration"]
        self.assertEqual(expiry.attrs.get("value"), "")
        self.assertIn("default 7d", expiry.attrs.get("placeholder", ""))
        self.assertEqual([button.text() for button in form.all(tag="button")],
                         ["Set maintenance", "Cancel"])

    def test_a_leafs_mark_says_the_pin_covers_the_node_alone(self):
        mark = self._mark(self._card(self._page(), "/uplink").one("status-card__head"))
        assert mark is not None
        self.assertNotIn("data-beneath", mark.attrs)

    def test_a_card_the_filter_emptied_still_covers_what_is_beneath_it(self):
        # hide ok drops gaffsie's three children from the page. A pin on gaffsie
        # covers them all the same, and its mark says so.
        self.tree.upsert("/gaffsie", StatusCode.WARN, "the fan is loud")
        page = self._page("/status?hide_ok=1")
        card = self._card(page, "/gaffsie")
        self.assertEqual(card.all("node-children"), [])
        mark = self._mark(card.one("status-card__head"))
        assert mark is not None
        self.assertIn("data-beneath", mark.attrs)
        # and so does the node's own card, on its page at depth 0
        card = self._card(self._page("/status/gaffsie?depth=0"), "/gaffsie")
        mark = self._mark(card.one("status-card__head"))
        assert mark is not None
        self.assertIn("data-beneath", mark.attrs)

    def test_a_pinned_card_has_no_mark_to_set_another(self):
        # its block carries Edit and Clear instead
        self._pin("/gaffsie")
        card = self._card(self._page(), "/gaffsie")
        self.assertIsNone(self._mark(card.one("status-card__head")))
        self.assertEqual(card.all("pin-setter"), [])

    def test_a_viewer_gets_no_mark(self):
        self._viewer()
        # on the wall, and on a node's own card at depth 0
        for url in ("/status", "/status/hemulen?depth=0"):
            with self.subTest(url=url):
                raw = self._body(url)
                self.assertNotIn('data-control="pin"', raw)
                self.assertNotIn("pin-editor", raw)
                self.assertNotIn("maintenance-editor-form", raw)

    def test_the_kiosk_gets_none_either(self):
        self._kiosk()
        for url in ("/status", "/status/hemulen?depth=0"):
            with self.subTest(url=url):
                raw = self._body(url)
                self.assertNotIn('data-control="pin"', raw)
                self.assertNotIn("pin-editor", raw)
                self.assertNotIn("maintenance-editor-form", raw)

    def test_a_box_inside_a_card_carries_the_mark_too(self):
        # every open head of a node with no pin of its own, a box's as well as a
        # card's (ADR-0127 decision 3): the editor is cloned into the box, where the
        # pin's block will stand, as a card's into its panel
        page = self._page()
        box = self._mark(self._row(page, "/nexus/qnap"))
        assert box is not None
        self.assertEqual(box.attrs.get("href"), "/status/nexus/qnap")
        self.assertIn("data-beneath", box.attrs)
        leaf = self._mark(self._row(page, "/nexus/load"))
        assert leaf is not None
        self.assertNotIn("data-beneath", leaf.attrs)
        # a pinned box has none
        self._pin("/nexus/qnap", note="disk swap")
        self.assertIsNone(self._mark(self._row(self._page(), "/nexus/qnap")))

    def test_every_editor_has_ids_of_its_own(self):
        # a wall carries an editor for each card, and a label finds its field by id
        self._pin("/gaffsie")
        self._pin("/nexus/qnap", note="disk swap")
        page = self._page()
        ids = [element.attrs["id"] for element in page.walk()
               if "id" in element.attrs]
        self.assertEqual(sorted(ids), sorted(set(ids)))
        labels = [label.attrs["for"] for label in page.all(tag="label")
                  if "for" in label.attrs]
        self.assertGreater(len(labels), 6)
        self.assertLessEqual(set(labels), set(ids))

    def test_the_way_back_keeps_the_wall_s_filters(self):
        self._pin("/gaffsie")
        # the second names a switch twice, as the filters' own form submits one
        for url in ("/status?hide_idle=1&depth=3",
                    "/status?view=1&hide_idle=0&hide_idle=1&depth=3"):
            with self.subTest(url=url):
                page = self._page(url)
                ways = {self._hidden(form).get("next")
                        for form in page.all(tag="form")
                        if form.attrs.get("action") == "/maintenance"}
                self.assertEqual(ways, {url})

    def test_the_refresh_s_fragment_carries_the_blocks_and_marks_but_no_editor(self):
        # the blocks and their editors stand in what the refresh swaps: the fragment
        # has to bring them as the page did, with the page's address and not its
        # own; the editor of a pin still to be set is the page's, outside the swap
        self._pin("/gaffsie")
        fragment = self._page("/status?depth=3&fragment=1")
        self.assertEqual(len(self._stated(self._card(fragment, "/gaffsie"))), 1)
        self.assertIsNotNone(self._mark(self._card(fragment, "/hemulen")
                                        .one("status-card__head")))
        self.assertEqual(fragment.all("rule-block--new"), [])
        self.assertEqual([t for t in fragment.all(tag="template")
                          if t.attrs.get("id") == "pin-editor"], [])
        ways = {self._hidden(form).get("next")
                for form in fragment.all(tag="form")
                if form.attrs.get("action") == "/maintenance"}
        self.assertEqual(ways, {"/status?depth=3"})
        # the page's editor prints the deployment's default and its timezone, as
        # every editor of a pin does
        setter = self._editor(self._page("/status?depth=3"))
        expiry, = [box for box in setter.all(tag="input")
                   if box.attrs.get("name") == "duration"]
        self.assertIn("default 7d", expiry.attrs.get("placeholder", ""))
        self.assertIn("Timezone: Europe/Berlin", setter.text())

    def test_a_set_from_a_card_comes_back_to_the_wall(self):
        # the page's editor, its path the one the script fills in from the card
        form = self._editor(self._page("/status?depth=3")).one(tag="form")
        response = self.client.post("/maintenance", data={
            **self._hidden(form), "path": "/hemulen", "reason": "new fans",
            "duration": "2h"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/status?depth=3")
        entry = self.tree.maintenance_entry("/hemulen")
        assert entry is not None
        self.assertEqual((entry.reason, entry.set_by), ("new fans", "pan"))

    def test_an_edit_in_a_card_keeps_the_expiry_it_showed(self):
        # decision 5 holds for every editor of a pin: a node's, a line's, a card's
        entry = self._pin("/gaffsie")
        form = self._stated(self._card(self._page(), "/gaffsie"))[0].one(
            "rule-block__edit").one(tag="form")
        shown, = [box.attrs["value"] for box in form.all(tag="input")
                  if box.attrs.get("name") == "duration"]
        self.assertEqual(shown, self._hidden(form)["expiry_was"])
        response = self.client.post("/maintenance", data={
            **self._hidden(form), "reason": "Back by midnight.",
            "duration": shown})
        self.assertEqual(response.status_code, 302)
        now = self.tree.maintenance_entry("/gaffsie")
        assert now is not None
        self.assertEqual((now.reason, now.expires_at),
                         ("Back by midnight.", entry.expires_at))


class BranchHeadTests(_WallCase):
    """Decisions 2 and 3: a branch's page states its node's pin in its head,
    above the children it covers, and sets one from there."""

    def test_the_head_states_the_pin_as_the_block(self):
        entry = self._pin("/gaffsie")
        raw = self._body("/status/gaffsie")
        page = parse(raw)
        head = page.one("viewed-head")
        block, = self._stated(head)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"This node is silenced by lex until {self._until(entry)} "
            "· 1d 23h left")
        self.assertEqual(len(block.one("rule-block__note").all(tag="p")), 3)
        # above the children it covers
        self.assertLess(block.order, page.one("status-grid").order)
        self.assertNotIn("pin-banner", raw)
        self.assertEqual(raw.count("silenced by"), 1)

    def test_an_admin_edits_and_clears_it_there(self):
        entry = self._pin("/gaffsie")
        block, = self._stated(self._page("/status/gaffsie").one("viewed-head"))
        edit = block.one("rule-block__edit")
        self.assertEqual(
            self._hidden(edit.one(tag="form")),
            {"path": "gaffsie", "action": "set", "set_at": entry.token,
             "next": "/status/gaffsie",
             "expiry_was": app_module._expiry_input(entry.expires_at)})
        self.assertEqual(
            self._hidden(block.one("rule-block__clear")),
            {"path": "gaffsie", "action": "clear", "set_at": entry.token,
             "next": "/status/gaffsie"})

    def test_a_viewer_reads_it_without_buttons(self):
        self._pin("/gaffsie")
        self._viewer()
        block, = self._stated(self._page("/status/gaffsie").one("viewed-head"))
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])

    def test_an_admin_sets_a_pin_from_the_head(self):
        page = self._page("/status/hemulen")
        head = page.one("viewed-head")
        setter = self._setter(head)
        self.assertTrue(setter.has("rule-setter"))
        self.assertEqual(setter.first().tag, "summary")
        self.assertEqual(setter.first().text(), "Set maintenance")
        editor = setter.one("rule-block--new")
        said = editor.one("rule-block__scope").text()
        self.assertTrue(said.startswith("Maintenance for this node. "), said)
        self.assertIn("everything beneath it", said)
        self.assertIn("nothing under here will alarm", said)
        self.assertEqual(
            self._hidden(editor.one(tag="form")),
            {"path": "hemulen", "action": "set", "set_at": "",
             "next": "/status/hemulen"})
        # one way to set it among the nodes, and it stands above the children it
        # will cover; the page's one editor for the cards' marks stands outside
        # the grid, after them
        new = page.all("rule-block--new")
        self.assertEqual(len(new), 2)
        self.assertLess(setter.order, page.one("status-grid").order)
        self.assertGreater(self._editor(page).order, page.one("status-grid").order)

    def test_a_head_that_everybody_reads_carries_the_control_for_an_admin_only(self):
        # a node with something of its own to say heads its page for every reader
        self.tree.upsert("/hemulen", StatusCode.WARN, "the fan is loud")
        self.assertEqual(
            len(self._page("/status/hemulen").one("viewed-head").all("rule-setter")),
            1)
        self._kiosk()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertEqual(head.all(tag="details") + head.all(tag="form"), [])
        self.client.delete_cookie("ls_prefs")
        self._viewer()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertEqual(head.all(tag="details") + head.all(tag="form"), [])

    def test_a_plain_containers_head_is_there_for_every_reader(self):
        # a container with nothing of its own to say opened with its children, its
        # head drawn for the admin alone, whose control it carried; a page frames
        # its node now (backlog #91 §3.5), and the head is the frame's top for every
        # reader, the kiosk's too — the control still the admin's alone
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertEqual(len(head.all("rule-setter")), 1)
        self._kiosk()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertEqual(head.all("rule-setter"), [])
        self.client.delete_cookie("ls_prefs")
        self._viewer()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertEqual(head.all("rule-setter"), [])

    def test_the_way_back_survives_a_name_a_url_has_to_quote(self):
        # A node's name is its check's to choose, and `#` unquoted would cut the
        # way back short: the write would land on another page.
        self.tree.upsert("/rack #2/psu", StatusCode.OK)
        form = self._setter(
            self._page("/status/rack%20%232").one("viewed-head")).one(tag="form")
        self.assertEqual(
            self._hidden(form),
            {"path": "rack #2", "action": "set", "set_at": "",
             "next": "/status/rack%20%232"})
        response = self.client.post("/maintenance", data={
            **self._hidden(form), "reason": "a supply is swapped",
            "duration": "2h"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/status/rack%20%232")
        self.assertIsNotNone(self.tree.maintenance_entry("/rack #2"))

    def test_what_the_head_shows_the_cards_beneath_it_leave_out(self):
        # The head of a node with nothing to say is still the topmost node in view
        # (ADR-0044): its time is said once, there — for every reader, since every
        # page frames its node (backlog #91 §3.5).
        self.tree.upsert("/moomin", StatusCode.UNDEFINED)
        self.tree.upsert("/moomin/valley", StatusCode.OK)
        self.tree.upsert("/moomin/house", StatusCode.OK)
        for path in ("/moomin", "/moomin/valley", "/moomin/house"):
            node = self.tree._find_node(path)
            assert node is not None
            node.timestamp = datetime(2026, 8, 6, 11, 30, 1, tzinfo=UTC)
        raw = self._body("/status/moomin")
        self.assertEqual(len(parse(raw).all("viewed-head")), 1)
        self.assertEqual(raw.count('class="status-card__time"'), 1)
        self._viewer()
        raw = self._body("/status/moomin")
        self.assertEqual(len(parse(raw).all("viewed-head")), 1)
        self.assertEqual(raw.count('class="status-card__time"'), 1)

    def test_the_card_at_the_foot_is_gone(self):
        self._pin("/gaffsie")
        for url in ("/status/gaffsie", "/status/hemulen"):
            raw = self._body(url)
            self.assertNotIn('text-uppercase">Maintenance<', raw, url)
            self.assertNotIn("maintenance-card__actions", raw, url)
            self.assertNotIn("This node is in maintenance", raw, url)
            self.assertNotIn("Clear maintenance", raw, url)

    def test_the_overview_offers_no_pin_on_everything(self):
        # silencing the whole tree from a form is a foot-gun; the root stays
        # the API's: no head, no mark on the overview's own card at depth 0, and
        # no editor in the grid whose path is the root's
        for url in ("/status", "/status?depth=0"):
            page = self._page(url)
            self.assertEqual(page.all("viewed-head"), [], url)
            paths = {self._hidden(form).get("path")
                     for form in page.one("status-grid").all(tag="form")
                     if form.attrs.get("action") == "/maintenance"}
            self.assertNotIn("", paths, url)
            self.assertNotIn("/", paths, url)
            marks = {mark.attrs.get("aria-label") for mark in page.all("node-icon")
                     if mark.attrs.get("data-control") == "pin"}
            self.assertNotIn("set maintenance for ", marks, url)
            self.assertNotIn("set maintenance for /", marks, url)
        self.assertIsNone(self._mark(self._page("/status?depth=0")
                                     .one("status-card__head")))

    def test_the_head_is_in_what_the_refresh_swaps(self):
        self._pin("/gaffsie")
        fragment = self._page("/status/gaffsie?fragment=1")
        block, = self._stated(fragment.one("viewed-head"))
        self.assertEqual(self._hidden(block.one("rule-block__clear"))["next"],
                         "/status/gaffsie")

    def test_at_depth_zero_a_branch_s_card_sets_it(self):
        page = self._page("/status/hemulen?depth=0")
        mark = self._mark(self._card(page, "/hemulen").one("status-card__head"))
        assert mark is not None
        self.assertIn("data-beneath", mark.attrs)
        # the page's editor comes back to the page as it was asked for
        self.assertEqual(
            self._hidden(self._editor(page).one(tag="form")),
            {"path": "", "action": "set", "set_at": "",
             "next": "/status/hemulen?depth=0"})
        # the card's panel is there for the editor to be cloned into, though the
        # node has nothing of its own to say
        self.assertTrue(self._card(page, "/hemulen").all("status-panel"))


class PinAboveHeadTests(_WallCase):
    """ADR-0104 decision 2 on a branch's page: a pin set on a node above it
    is stated in the head, where it acts, as the pin's block without buttons,
    naming and linking the node it stands on."""

    @classmethod
    def _above(cls, where: Element) -> list[Element]:
        """The blocks in ``where`` that state a pin set above it."""
        return [block for block in cls._stated(where)
                if "ilenced from" in block.one("rule-block__what").text()]

    def test_the_head_states_a_pin_above_as_its_block(self):
        entry = self._pin("/nexus")
        page = self._page("/status/nexus/qnap")
        block, = self._above(page.one("viewed-head"))
        what = block.one("rule-block__what")
        self.assertEqual(
            what.text(),
            f"This node is silenced from /nexus by lex until {self._until(entry)} "
            "· 1d 23h left")
        link, = what.all(tag="a")
        self.assertEqual(link.attrs.get("href"), "/status/nexus")
        self.assertEqual(len(block.one("rule-block__note").all(tag="p")), 3)
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])
        # above the children it covers
        self.assertLess(block.order, page.one("status-grid").order)

    def test_a_viewer_reads_it_in_the_head(self):
        # every page's head is drawn now (backlog #91 §3.5); a pin above silencing
        # the node is a row at its head, without buttons for a viewer
        self._viewer()
        head = self._page("/status/nexus/qnap").one("viewed-head")
        self.assertEqual(head.all("rule-list"), [])
        self._pin("/nexus")
        head = self._page("/status/nexus/qnap").one("viewed-head")
        block, = self._above(head)
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])

    def test_the_refresh_s_fragment_carries_it(self):
        self._pin("/nexus")
        frag = parse(self._body("/status/nexus/qnap?fragment=1"))
        self.assertEqual(len(self._above(frag.one("viewed-head"))), 1)

    def test_the_head_s_editor_says_its_pin_outlasts_the_one_above(self):
        self._pin("/nexus")
        said = self._setter(self._page("/status/nexus/qnap").one("viewed-head")).one(
            "rule-block__scope").text()
        self.assertTrue(said.startswith(
            "Maintenance for this node. It keeps everything beneath it silenced when "
            "the pin above it ends: nothing under here will alarm before this pin "
            "expires."), said)

    def test_the_node_s_own_pin_under_one_is_also_silenced_on_its_own(self):
        self._pin("/nexus", by="anna")
        own = self._pin("/nexus/qnap")
        head = self._page("/status/nexus/qnap").one("viewed-head")
        above, mine = self._stated(head)
        self.assertIn("silenced from /nexus by anna",
                      above.one("rule-block__what").text())
        self.assertEqual(
            mine.one("rule-block__what").text(),
            f"This node is also silenced on its own by lex until {self._until(own)} "
            "· 1d 23h left")
        self.assertTrue(mine.all("rule-block__clear"))

    def test_at_depth_zero_the_node_s_card_states_it(self):
        entry = self._pin("/nexus")
        card = self._page("/status/nexus/qnap?depth=0").one("status-card")
        block, = self._above(card)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"Silenced from /nexus by lex until {self._until(entry)} · 1d 23h left")

    def test_the_wall_and_the_pinned_node_s_own_page_have_none(self):
        self._pin("/nexus")
        for url in ("/status", "/status/nexus"):
            with self.subTest(url=url):
                self.assertNotIn("silenced from", self._body(url))


class DialogGoneTests(_WallCase):
    """Decision 7: the pin dialog goes, and with it its script and its styles."""

    def test_the_wall_ships_no_dialog_and_no_script_of_one(self):
        for url in ("/status", "/status/hemulen"):
            raw = self._body(url)
            self.assertNotIn("pin-card", raw, url)
            self.assertNotIn("js/pin.js", raw, url)
            self.assertNotIn('aria-haspopup="dialog"', raw, url)
        self.assertEqual(self.client.get("/static/js/pin.js").status_code, 404)

    def test_the_stylesheet_keeps_nothing_of_what_went(self):
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        for gone in (".pin-card", ".pin-banner", ".maintenance-card__actions"):
            self.assertEqual(css_rules_naming(css, gone), [], gone)



class RefreshWaitsTests(_WallCase):
    """Decision 7: the refresh waits for an open editor. That it does is the
    browser's to show (`tests/test_pin_browser.py`); here is what the script and
    the sheet go by, which a page drawn another way would break without a
    browser to say so."""

    def _script(self, name: str) -> str:
        return self.client.get(f"/static/js/{name}").get_data(as_text=True)

    def _css(self) -> str:
        return self.client.get("/static/css/overview.css").get_data(as_text=True)

    #: The editor's own open disclosure around its form — named by its class, a
    #: node's or a line's, so that no other disclosure the grid may hold matches it
    #: (ADR-0127's stage 2 narrowed it from any `details[open]`).
    EDITOR = ("details.maintenance-editor-disclosure[open] form.maintenance-editor-form"
              ", details.reason-pin[open] form.maintenance-editor-form")

    def test_every_editor_on_these_pages_is_what_the_refresh_looks_for(self):
        # the editor's own open disclosure around a `form.maintenance-editor-form`
        self.assertIn(f"var EDITOR = '{self.EDITOR}';", self._script("poll.js"))
        self._pin("/gaffsie")
        self._pin("/nexus/qnap", note="disk swap")
        for url in ("/status", "/status?depth=3&fragment=1", "/status/gaffsie",
                    "/status/hemulen", "/status/hemulen?depth=0"):
            editors = [form for form in self._page(url).all(tag="form")
                       if form.all(tag="textarea")]
            self.assertGreater(len(editors), 0, url)
            for form in editors:
                self.assertTrue(form.has("maintenance-editor-form"), url)
                around = form.parent
                while around is not None and around.tag != "details":
                    around = around.parent
                self.assertIsNotNone(around, url)
                assert around is not None
                self.assertTrue(around.has("maintenance-editor-disclosure")
                                or around.has("reason-pin"), (url, around.attrs))

    def test_the_stamp_says_it_and_the_page_dims_after_a_minute(self):
        script = self._script("poll.js")
        self.assertIn("sayUpdated(' — paused while editing');", script)
        self.assertIn("var WAIT_DIMS_AFTER_MS = 60000;", script)
        self.assertIn("setTimeout(dim, WAIT_DIMS_AFTER_MS)", script)

    def test_the_sheet_dims_all_but_what_holds_the_open_editor(self):
        css = self._css()
        waiting, = css_rules_naming(css, ".poll-waiting")
        # as a page that lost its server dims
        dim, = re.findall(r"opacity:\s*([\d.]+)", css_rule(css, ".poll-stale"))
        self.assertIn(f"opacity: {dim};", waiting)
        sheet = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        # the editor's own disclosure, as the scripts name it
        holds = (r":not\(:has\(details\.maintenance-editor-disclosure\[open\] "
                 r"\.maintenance-editor-form, details\.reason-pin\[open\] "
                 r"\.maintenance-editor-form\)\)")
        # on the wall the grid's cards and what stands beside the grid; on a node's
        # page the same inside its frame: its head, its cards, its facts
        self.assertRegex(
            sheet, r"\.poll-waiting > \.status-grid > " + holds + r",")
        self.assertRegex(
            sheet, r"\.poll-waiting \.node-frame__box > \.status-grid > "
                   + holds + r"\s*\{")
        self.assertRegex(
            sheet,
            r"\.poll-waiting > :not\(\.status-grid, \.node-frame\)" + holds + r",")
        self.assertRegex(
            sheet, r"\.poll-waiting \.node-frame__box > :not\(\.status-grid\)"
                   + holds + r",")

    def test_the_cloned_editor_takes_the_blocks_place_and_measure(self):
        # the editor ‖ clones into a card's panel or a box stands where the pin's
        # block will, with the block's padding and size there, and none of the
        # head's row holds a seat for a mark any more
        css = self._css()
        for where in (".status-panel", ".tree-box"):
            with self.subTest(where=where):
                rule = css_rule(css, f"{where} > .pin-setter > .rule-block")
                self.assertIn("padding: 0.35rem 0.55rem;", rule)
                self.assertIn("font-size: 0.8rem;", rule)
                self.assertIn("display: block;",
                              css_rule(css, f"{where} > .pin-setter"))
        self.assertNotIn(".status-card__state--seat", css)
        self.assertNotIn(".pin-control", css)
        # and the marks stand in the heads' icons alone: on the wall's cards and
        # boxes, pinned or not, and on a node's own card at depth 0
        self._pin("/gaffsie")
        heads = [head for url in ("/status", "/status/hemulen?depth=0",
                                  "/status/gaffsie?depth=0")
                 for head in self._page(url).all("status-card__head")
                 + self._page(url).all("status-node__self")]
        self.assertGreater(len(heads), 5)
        for head in heads:
            self.assertEqual(head.all("pin-setter"), [], head)
            marks = [icon for icon in head.all("node-icon")
                     if icon.attrs.get("data-control") == "pin"]
            self.assertLessEqual(len(marks), 1, head)
            for mark in marks:
                self.assertTrue(mark.parent.has("node-icons"))
        self.assertEqual(
            sorted({len([icon for icon in head.all("node-icon")
                         if icon.attrs.get("data-control") == "pin"])
                    for head in heads}), [0, 1])

    def test_a_note_keeps_its_links_and_a_head_its_measure(self):
        css = self._css()
        # a box's links are plain until hovered; a note's are not a box's
        self.assertIn("text-decoration: underline;",
                      css_rule(css, ".status-node .rule-block__note a"))
        # a branch's head runs the page's width; what stands in it does not
        for part in (".viewed-head .rule-block__head",
                     ".viewed-head .rule-block__note",
                     ".viewed-head .rule-block__editor"):
            self.assertRegex(css_rule(css, part), r"max-width:\s*\d+rem;", part)

    def test_a_cards_buttons_wait_for_hover_or_focus(self):
        sheet = re.sub(r"/\*.*?\*/", "", self._css(), flags=re.S)
        for button in (r"\.rule-block__edit > summary",
                       r"\.rule-block__clear > button"):
            with self.subTest(button=button):
                self.assertRegex(sheet, r"\.status-card " + button
                                 + r"[^{}]*\{\s*opacity: 0;")
                self.assertRegex(sheet, r"\.status-card:hover " + button)
                self.assertRegex(
                    sheet, r"\.status-card \.rule-block__head:focus-within > "
                    + button)

    def test_the_inspection_card_leaves_a_pins_controls_alone(self):
        # the inspection card answers a node's name alone (`NAMES`, `inspect.js`),
        # and a pin's mark stands in a head's row among its icons, outside the
        # name; a block and its editor stand in the node's box, outside the row,
        # since the head's row was rebuilt (ADR-0127 decision 3) — a branch's head
        # keeps them beneath its row
        found = re.search(r"var NAMES = '([^']+)';", self._script("inspect.js"))
        assert found is not None
        self.assertEqual(found.group(1).split(", "),
                         [".tree-chip", '[data-control="toggle"]', ".ls-strip__name"])

        def a_name(node: Element) -> bool:
            return (node.has("tree-chip") or node.has("ls-strip__name")
                    or node.attrs.get("data-control") == "toggle")
        self._pin("/nexus/qnap", note="disk swap")
        for url in ("/status", "/status/hemulen", "/status/nexus/qnap"):
            page = self._page(url)
            rows = [row for row in page.walk() if "data-path" in row.attrs]
            controls = [control for row in rows
                        for control in row.all(tag="form") + row.all(tag="summary")
                        + [icon for icon in row.all("node-icon")
                           if icon.attrs.get("data-control") == "pin"]]
            self.assertGreater(len(controls), 0, url)
            for control in controls:
                node = control
                while node is not None:
                    self.assertFalse(a_name(node), (url, control))
                    node = node.parent

    def test_the_inspection_card_stays_away_from_a_row_whose_editor_is_open(self):
        # #89's B12: the mark that opened an editor has given way to it, so the
        # pointer that clicked is left on the node's own row, and the row's card
        # came up over the one above. That it stays away is the browser's to show;
        # what the script goes by is the refresh's shape of an open editor, asked
        # of the row — one editor is one node's.
        shape = r"""var EDITOR = (["'])([^"']+)\1;"""
        waits = re.search(shape, self._script("poll.js"))
        stays = re.search(shape, self._script("inspect.js"))
        assert waits is not None and stays is not None
        self.assertEqual(stays.group(2), waits.group(2))
        self.assertIn("if (node.querySelector(EDITOR)) { return null; }",
                      self._script("inspect.js"))
        self.assertIn('var node = row.closest(".tree-node") || row;',
                      self._script("inspect.js"))
        # the editor a head's button opens stands in the node that answers to the
        # card — its box, after the row — which is where the script looks for it;
        # a page's head keeps its editor beneath its row, in the frame, which is
        # the node the script asks of the head's row
        page = self._page("/status/hemulen")
        setter = self._setter(page.one("viewed-head"))
        frame = page.one("node-frame")
        self.assertTrue(frame.has("tree-node"))
        self.assertTrue(setter.within(frame))
        self.assertTrue(page.one("viewed-head").one("status-node__self").within(frame))
        self.assertGreater(setter.order,
                           page.one("viewed-head").one("status-node__self").order)
        self.assertEqual(len(setter.all("maintenance-editor-form")), 1)
        # a stated pin's editor stands in the box, outside the row and inside the node
        self._pin("/nexus/qnap", note="disk swap")
        page = self._page()
        box = self._box(page, "/nexus/qnap")
        edit = next(block for block in box.all("rule-block")
                    if block.parent is box).one("rule-block__edit")
        self.assertEqual(self._row(page, "/nexus/qnap").all("rule-block__edit"), [])
        around = edit.parent
        while around is not None and "data-node" not in around.attrs:
            around = around.parent
        assert around is not None
        self.assertEqual(around.attrs["data-node"], "/nexus/qnap")
