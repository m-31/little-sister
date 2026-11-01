"""The wall and a branch's page state a pin where it stands (ADR-0104 decisions 2, 3
and 7, as ADR-0147 amends them).

The third of the pin block's three surfaces. A card on the wall states its node's pin
as a block while *◇ details* is on — one link that opens the node's *Notes* tab in the
drawer at that pin, where it is changed (ADR-0147 decisions 6 and 7) — and a branch's
page states its node's pin whole in its head and changes it there, as the card a page
draws at depth 0 does. A new pin is set on the node's Notes tab, which every head's
door opens (ADR-0147 decision 1). With them the dialog that floated over the wall, its
script, the card at the foot of a branch's page, and ‖ and the editor it cloned into a
card are gone.

The editors stand inside the part of the page the ten-second refresh swaps, so the
refresh waits while one is open, as it waits while the drawer is. That half is the
browser's to show (`tests/test_pin_browser.py`, `tests/test_drawer_browser.py`); what
the gate holds of it is that the fragment carries the same blocks as the page, every
editor with the page's own address to come back to, and what the script and the sheet
go by: the shape of an editor, the stamp's words, the minute, and the rules that keep
a mark on its seat.

The pages are read as trees (`tests/page_tree.py`) wherever the claim is about
*where* something stands.
"""
from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.pins import Pin
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

    def _details(self) -> None:
        """*◇ details* on, as the band's switch leaves it in a cookie (ADR-0147
        decision 6): the wall draws the blocks of what handles a part."""
        self.client.set_cookie("handled_details", "1")

    def _pin(self, path: str, note: str | None = NOTE, by: str = "lex",
             left: timedelta = LEFT) -> Pin:
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
    def _door(head: Element) -> Element | None:
        """The door, ◇, on the head — among its icons, or lit in its state cluster under
        the looks whose toolbar shows only under the pointer — or None (ADR-0147)."""
        found = [link for link in head.all(tag="a")
                 if link.attrs.get("data-control") == "door"]
        assert len(found) <= 1
        return found[0] if found else None

    def _until(self, entry: Pin) -> str:
        return str(app_module._localtime(entry.expires_at))


class CardBlockTests(_WallCase):
    """Decisions 1 and 2, as ADR-0147 decisions 6 and 7 amend them: on the wall the
    block stands in the card while *◇ details* is on, one link that opens the drawer at
    it; off, the library's default, the card says its pin by its color and its door."""

    def test_a_pinned_card_states_its_pin_as_the_block(self):
        entry = self._pin("/gaffsie")
        self._details()
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
            f"In maintenance by lex until {self._until(entry)} · 1d 23h left")
        # and it is stated once: the strip that said it before is gone
        self.assertNotIn("pin-banner", raw)
        self.assertEqual(raw.count("In maintenance by"), 1)

    def test_without_details_a_card_says_its_pin_by_its_door(self):
        # ADR-0147 decision 6: off, the library's default, no block stands on the
        # wall and the server draws none — and nothing that counts goes with it
        self._pin("/gaffsie")
        self._pin("/nexus/qnap", note="disk swap")
        raw = self._body()
        page = parse(raw)
        self.assertEqual(self._stated(page), [])
        self.assertNotIn("In maintenance by", raw)
        self.assertNotIn("rule-block", raw)
        for head, title in (
                (self._card(page, "/gaffsie").one("status-card__head"),
                 "Handle it — 1 handled: 1 node in maintenance"),
                (self._row(page, "/nexus/qnap"),
                 "Handle it — 1 handled: 1 node in maintenance")):
            door = self._door(head)
            assert door is not None
            self.assertEqual(door.attrs.get("title"), title)

    def test_a_cards_expiry_keeps_its_date_and_its_time_whole(self):
        # Seen in a card: *until 2026-10-*, and the day and the time on
        # the next line. A card is the narrowest place a block stands in.
        entry = self._pin("/gaffsie")
        boxed = self._pin("/nexus/qnap", left=timedelta(hours=5, minutes=30))
        self._details()
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

    def test_the_block_is_one_link_to_the_drawer_at_its_pin(self):
        # ADR-0147 decision 7: its sentence its name, a chevron at its end, a door
        # as every mark is — and nothing inside it to click, nor the note, its mark,
        # its card or the pencil that went
        self._pin("/gaffsie")
        self._details()
        block = self._stated(self._card(self._page(), "/gaffsie"))[0]
        self.assertEqual(block.tag, "a")
        self.assertTrue(block.has("rule-block--wall"))
        self.assertTrue(block.has("rule-block--door"))
        self.assertEqual(block.attrs.get("href"), "/notes/gaffsie?at=maintenance#at")
        self.assertIn("data-door", block.attrs)
        chevron = block.one("rule-block__chevron")
        self.assertEqual((chevron.attrs.get("aria-hidden"), chevron.text()),
                         ("true", "›"))
        self.assertEqual(block.all(tag="a") + block.all(tag="form")
                         + block.all(tag="button") + block.all(tag="details")
                         + block.all(tag="template"), [])
        for gone in ("rule-block__note", "rule-note-mark", "rule-note-src",
                     "block-button", "rule-block__clear-now", "rule-block__edit"):
            with self.subTest(gone=gone):
                self.assertEqual(block.all(gone), [])

    def test_the_drawer_it_opens_states_the_block_whole_its_editor_open(self):
        # what the link opens is the node's Notes tab at that pin: the note whole,
        # who set it, its editor open for an admin, and Clear — and a Clear there
        # ends the pin as the wall's did
        entry = self._pin("/gaffsie")
        self._details()
        block = self._stated(self._card(self._page(), "/gaffsie"))[0]
        tab = self._page(block.attrs["href"].split("#")[0])
        at = tab.with_id("at")
        self.assertTrue(at.has("rule-block"))
        self.assertEqual(len(at.one("rule-block__note").all(tag="p")), 3)
        edit = at.one("rule-block__edit")
        self.assertIn("open", edit.attrs)
        self.assertEqual(edit.one(tag="textarea").source(), NOTE)
        clear = at.one("rule-block__clear")
        self.assertEqual(self._hidden(clear)["set_at"], entry.token)
        response = self.client.post("/pins/maintenance", data=self._hidden(clear))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.tree.maintenance_entry("/gaffsie"))

    def test_a_viewer_reads_the_block_and_its_drawer(self):
        # the note is a viewer's to read too: the block is the same link
        self._pin("/gaffsie")
        self._viewer()
        self._details()
        block = self._stated(self._card(self._page(), "/gaffsie"))[0]
        self.assertEqual(block.attrs.get("href"), "/notes/gaffsie?at=maintenance#at")
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])
        at = self._page("/notes/gaffsie?at=maintenance").with_id("at")
        self.assertEqual(len(at.one("rule-block__note").all(tag="p")), 3)
        self.assertEqual(at.all(tag="form"), [])

    def test_the_kiosk_follows_the_deployment_and_its_block_is_plain(self):
        # the kiosk has no band to say it with, so a browser's cookie says nothing
        # there; the deployment's default does, and its block is the sentence alone
        self._pin("/gaffsie")
        self._kiosk()
        self._details()
        self.assertEqual(self._stated(self._page()), [])
        with patch.object(app_module, "config",
                          replace(app_module.config, handled_details=True)):
            self.client.set_cookie("handled_details", "0")
            block = self._stated(self._card(self._page(), "/gaffsie"))[0]
        self.assertEqual(block.tag, "div")
        self.assertEqual(block.all(tag="form") + block.all(tag="details")
                         + block.all(tag="a") + block.all("rule-block__chevron"), [])
        self.assertNotIn("href", block.attrs)

    def test_the_deployments_default_stands_until_a_browser_says_otherwise(self):
        # `settings.yaml`'s handled_details gives the switch's default; the switch,
        # set, is kept in a cookie as hide ok and hide idle are
        self._pin("/gaffsie")
        with patch.object(app_module, "config",
                          replace(app_module.config, handled_details=True)):
            self.assertEqual(len(self._stated(self._card(self._page(), "/gaffsie"))),
                             1)
            response = self.client.get("/status?view=1")
            self.assertIn("handled_details=0",
                          " ".join(response.headers.getlist("Set-Cookie")))
            self.assertEqual(self._stated(self._page()), [])

    def test_a_box_inside_a_card_states_its_pin_as_the_block_too(self):
        entry = self._pin("/nexus/qnap")
        self._details()
        raw = self._body()
        box = self._box(parse(raw), "/nexus/qnap")
        blocks = self._stated(box)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(
            blocks[0].one("rule-block__what").text(),
            f"In maintenance by lex until {self._until(entry)} · 1d 23h left")
        self.assertEqual(blocks[0].attrs.get("href"),
                         "/notes/nexus/qnap?at=maintenance#at")
        self.assertNotIn("pin-banner", raw)

    def test_a_box_deeper_down_states_its_pin_as_its_link(self):
        # a box inside a box is drawn by the same hand, one level further in
        self._pin("/nexus/qnap", note="shelf swap")
        self._pin("/nexus/qnap/smart", note="firmware")
        self._details()
        page = self._page()
        blocks = {path: self._stated(self._box(page, path))
                  for path in ("/nexus/qnap", "/nexus/qnap/smart")}
        # the outer box holds the inner one, and so its block too
        self.assertEqual([len(found) for found in blocks.values()], [2, 1])
        self.assertEqual([block.attrs.get("href") for block in blocks["/nexus/qnap"]],
                         ["/notes/nexus/qnap?at=maintenance#at",
                          "/notes/nexus/qnap/smart?at=maintenance#at"])
        ids = [element.attrs["id"] for element in page.walk()
               if "id" in element.attrs]
        self.assertEqual(sorted(ids), sorted(set(ids)))

    def test_the_card_of_a_page_at_depth_zero_states_its_pin(self):
        # the node's own head at depth 0, which states its blocks whole either way
        entry = self._pin("/gaffsie")
        page = self._page("/status/gaffsie?depth=0")
        card = self._card(page, "/gaffsie")
        block, = self._stated(card)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"In maintenance by lex until {self._until(entry)} · 1d 23h left")
        self.assertEqual(self._hidden(block.one("rule-block__clear"))["next"],
                         "/status/gaffsie?depth=0")
        # the card is the node there: no head says it a second time, and its door
        # counts the pin (ADR-0147 decision 2)
        self.assertEqual(page.all("viewed-head"), [])
        self.assertEqual(len(self._stated(page)), 1)
        door = self._door(card.one("status-card__head"))
        assert door is not None
        self.assertEqual(door.attrs.get("title"),
                         "Handle it — 1 handled: 1 node in maintenance")

    def test_a_pin_on_everything_is_stated_on_the_overviews_own_card(self):
        # At depth 0 the overview is one card, every node there is, the root's head.
        # A pin on it is not set from the wall, but one that stands is stated whole
        # like any other, whichever way *◇ details* is set, and changed there, as on
        # *Handled*: the root has no Notes tab for a drawer to frame.
        write = self.tree.set_maintenance(
            "", "datacenter move", expires_at=datetime.now(UTC) + LEFT, set_by="lex")
        entry = write.current
        assert entry is not None
        page = self._page("/status?depth=0")
        block, = self._stated(page)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"In maintenance by lex until {self._until(entry)} · 1d 23h left")
        # an open one-off's editor says so (`open_once`, ADR-0150, landing 4), its
        # month, which it asks for when it is wanted, keeping none (decision 17)
        self.assertEqual(
            self._hidden(block.one("rule-block__edit").one(tag="form")),
            {"path": "/", "action": "set", "set_at": entry.token,
             "next": "/status?depth=0",
             "expiry_was": app_module._expiry_input(entry.expires_at),
             "open_once": "1"})
        self.assertEqual(self._hidden(block.one("rule-block__clear"))["action"],
                         "clear")
        self.assertEqual(page.one("status-grid").all("rule-block--new"), [])
        # the root has no Notes tab, so its card has no door
        self.assertIsNone(self._door(page.one("status-card__head")))


class CardSetterTests(_WallCase):
    """Decision 3, as ADR-0147 decision 1 amends it: nothing new is set on the wall.
    The last of a head's icons is its door, ◇, a link to the node's Notes tab, where a
    pin is set, for every reader; a pin that stands is changed where its block
    stands."""

    def test_a_cards_door_is_its_last_icon_and_the_page_holds_no_editor(self):
        page = self._page()
        card = self._card(page, "/hemulen")
        door = self._door(card.one("status-card__head"))
        assert door is not None
        self.assertEqual(door.tag, "a")
        self.assertEqual(door.attrs.get("href"), "/notes/hemulen")
        self.assertEqual(door.attrs.get("aria-label"), "handle /hemulen")
        self.assertEqual(door.attrs.get("title"), "Handle it")
        icons = [icon.attrs.get("data-control") for icon in
                 card.one("status-card__head").one("node-icons").all("node-icon")]
        self.assertEqual(icons[-1], "door")
        # no editor of a new pin, in the card or on the page
        self.assertEqual(card.all("maintenance-editor-form"), [])
        self.assertEqual([t for t in page.all(tag="template")
                          if t.attrs.get("id") == "pin-editor"], [])
        self.assertEqual(page.all("rule-block--new"), [])

    def test_a_pinned_card_s_door_counts_its_pin(self):
        # its block carries Edit and Clear; its door counts it
        self._pin("/gaffsie")
        card = self._card(self._page(), "/gaffsie")
        door = self._door(card.one("status-card__head"))
        assert door is not None
        self.assertEqual(door.attrs.get("title"),
                         "Handle it — 1 handled: 1 node in maintenance")
        self.assertEqual(card.all("rule-block--new"), [])

    def test_a_viewer_gets_the_door_and_no_editor(self):
        self._viewer()
        # on the wall, and on a node's own card at depth 0
        for url in ("/status", "/status/hemulen?depth=0"):
            with self.subTest(url=url):
                raw = self._body(url)
                self.assertIn('data-control="door"', raw)
                self.assertNotIn('data-control="pin"', raw)
                self.assertNotIn("pin-editor", raw)
                self.assertNotIn("maintenance-editor-form", raw)

    def test_the_kiosk_gets_none_either(self):
        self._kiosk()
        for url in ("/status", "/status/hemulen?depth=0"):
            with self.subTest(url=url):
                raw = self._body(url)
                self.assertNotIn('data-control="door"', raw)
                self.assertNotIn('data-control="pin"', raw)
                self.assertNotIn("pin-editor", raw)
                self.assertNotIn("maintenance-editor-form", raw)

    def test_a_box_inside_a_card_carries_its_door_too(self):
        # every open head, a box's as well as a card's (ADR-0127 decision 3)
        page = self._page()
        box = self._door(self._row(page, "/nexus/qnap"))
        assert box is not None
        self.assertEqual((box.attrs.get("href"), box.attrs.get("title")),
                         ("/notes/nexus/qnap", "Handle it"))
        self._pin("/nexus/qnap", note="disk swap")
        box = self._door(self._row(self._page(), "/nexus/qnap"))
        assert box is not None
        self.assertEqual(box.attrs.get("title"),
                         "Handle it — 1 handled: 1 node in maintenance")

    def test_every_editor_has_ids_of_its_own(self):
        # a node's page carries an editor for each block it states whole, and a label
        # finds its field by id; the wall, every block on it a link, carries none, and
        # its ids are its own as well
        self._pin("/gaffsie")
        self._pin("/nexus/qnap", note="disk swap")
        self._details()
        for url, editors in (("/status", 0), ("/status/nexus/qnap", 1),
                             ("/status/gaffsie?depth=0", 1)):
            with self.subTest(url=url):
                page = self._page(url)
                ids = [element.attrs["id"] for element in page.walk()
                       if "id" in element.attrs]
                self.assertEqual(sorted(ids), sorted(set(ids)))
                labels = [label.attrs["for"] for label in page.all(tag="label")
                          if "for" in label.attrs]
                self.assertLessEqual(set(labels), set(ids))
                self.assertEqual(len(page.all("maintenance-editor-form")), editors)

    def test_the_way_back_keeps_the_page_s_filters(self):
        # a node's page states its pin whole, and its editor and Clear come back to the
        # page as it was asked, filters and all; the second names a switch twice, as
        # the filters' own form submits one
        self._pin("/nexus")
        for url in ("/status/nexus?hide_idle=1&depth=3",
                    "/status/nexus?view=1&hide_idle=0&hide_idle=1&depth=3"):
            with self.subTest(url=url):
                page = self._page(url)
                ways = {self._hidden(form).get("next")
                        for form in page.all(tag="form")
                        if form.attrs.get("action") == "/pins/maintenance"}
                self.assertEqual(ways, {url})
        # the wall has none to come back from: its block opens the drawer
        self._details()
        wall = self._page("/status?hide_idle=1")
        self.assertEqual([form for form in wall.all(tag="form")
                          if form.attrs.get("action") == "/pins/maintenance"], [])

    def test_the_refresh_s_fragment_carries_the_blocks_and_the_doors(self):
        # what the switch draws stands in what the refresh swaps: the fragment brings
        # the blocks as the page did, links with no form in them, or none — and the
        # doors, as every head's icons, either way
        self._pin("/gaffsie")
        fragment = self._page("/status?depth=3&fragment=1")
        self.assertEqual(self._stated(fragment), [])
        self.assertIsNotNone(self._door(self._card(fragment, "/hemulen")
                                        .one("status-card__head")))
        self._details()
        fragment = self._page("/status?depth=3&fragment=1")
        block, = self._stated(self._card(fragment, "/gaffsie"))
        self.assertEqual(block.attrs.get("href"), "/notes/gaffsie?at=maintenance#at")
        self.assertIsNotNone(self._door(self._card(fragment, "/hemulen")
                                        .one("status-card__head")))
        self.assertEqual(fragment.all("rule-block--new"), [])
        self.assertEqual([form for form in fragment.all(tag="form")
                          if form.attrs.get("action", "").startswith("/pins/")], [])

    def test_a_set_from_a_card_s_door_comes_back_to_its_tab(self):
        # the door's tab, whose form a pin is set from, and to which the write
        # comes back
        tab = self._page("/notes/hemulen")
        (form,) = [form for form in tab.all("ls-kind-form")
                   if form.attrs.get("data-kind") == "maintenance"]
        hidden = self._hidden(form)
        self.assertEqual(
            hidden, {"path": "/hemulen", "action": "set", "set_at": "",
                     "next": "/notes/hemulen", "from": "notes"})
        response = self.client.post("/pins/maintenance", data={
            **hidden, "note": "new fans", "duration": "2h"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/notes/hemulen")
        entry = self.tree.maintenance_entry("/hemulen")
        assert entry is not None
        self.assertEqual((entry.note, entry.set_by), ("new fans", "pan"))

    def test_an_edit_in_a_card_keeps_the_expiry_it_showed(self):
        # decision 5 holds for every editor of a pin: a node's, a line's, and that of
        # the card a node's page draws at depth 0
        entry = self._pin("/gaffsie")
        form = self._stated(self._card(self._page("/status/gaffsie?depth=0"),
                                       "/gaffsie"))[0].one(
            "rule-block__edit").one(tag="form")
        shown, = [box.attrs["value"] for box in form.all(tag="input")
                  if box.attrs.get("name") == "duration"]
        self.assertEqual(shown, self._hidden(form)["expiry_was"])
        response = self.client.post("/pins/maintenance", data={
            **self._hidden(form), "note": "Back by midnight.",
            "duration": shown})
        self.assertEqual(response.status_code, 302)
        now = self.tree.maintenance_entry("/gaffsie")
        assert now is not None
        self.assertEqual((now.note, now.expires_at),
                         ("Back by midnight.", entry.expires_at))


class BranchHeadTests(_WallCase):
    """Decisions 2 and 3: a branch's page states its node's pin in its head, above
    the children it covers, and changes it there; a new one is set on the node's Notes
    tab, which the head's door opens (ADR-0147 decision 1)."""

    def test_the_head_states_the_pin_as_the_block(self):
        entry = self._pin("/gaffsie")
        raw = self._body("/status/gaffsie")
        page = parse(raw)
        head = page.one("viewed-head")
        block, = self._stated(head)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"This node is in maintenance by lex until {self._until(entry)} "
            "· 1d 23h left")
        self.assertEqual(len(block.one("rule-block__note").all(tag="p")), 3)
        # above the children it covers
        self.assertLess(block.order, page.one("status-grid").order)
        self.assertNotIn("pin-banner", raw)
        self.assertEqual(raw.count("in maintenance by"), 1)

    def test_an_admin_edits_and_clears_it_there(self):
        entry = self._pin("/gaffsie")
        block, = self._stated(self._page("/status/gaffsie").one("viewed-head"))
        edit = block.one("rule-block__edit")
        self.assertEqual(
            self._hidden(edit.one(tag="form")),
            {"path": "gaffsie", "action": "set", "set_at": entry.token,
             "next": "/status/gaffsie",
             "expiry_was": app_module._expiry_input(entry.expires_at),
             "open_once": "1"})
        self.assertEqual(
            self._hidden(block.one("rule-block__clear")),
            {"path": "gaffsie", "action": "clear", "set_at": entry.token,
             "next": "/status/gaffsie"})

    def test_a_viewer_reads_it_without_buttons(self):
        self._pin("/gaffsie")
        self._viewer()
        block, = self._stated(self._page("/status/gaffsie").one("viewed-head"))
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])

    def test_the_head_sets_nothing_its_door_opens_the_tab(self):
        page = self._page("/status/hemulen")
        head = page.one("viewed-head")
        self.assertEqual(head.all("rule-setter") + head.all("rule-block--new"), [])
        door = self._door(head)
        assert door is not None
        self.assertEqual(door.attrs.get("href"), "/notes/hemulen")
        self.assertEqual(page.all("rule-block--new"), [])

    def test_a_head_that_everybody_reads_carries_its_door_for_every_reader(self):
        # a node with something of its own to say heads its page for every reader,
        # and its door with it — none on the kiosk, which has nothing to click
        self.tree.upsert("/hemulen", StatusCode.WARN, "the fan is loud")
        door = self._door(self._page("/status/hemulen").one("viewed-head"))
        assert door is not None
        self.assertEqual(door.attrs.get("title"), "Handle it")
        self._kiosk()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertEqual(head.all(tag="details") + head.all(tag="form"), [])
        self.assertIsNone(self._door(head))
        self.client.delete_cookie("ls_prefs")
        self._viewer()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertEqual(head.all(tag="details") + head.all(tag="form"), [])
        door = self._door(head)
        assert door is not None
        self.assertEqual(door.attrs.get("title"), "Notes")

    def test_a_plain_containers_head_is_there_for_every_reader(self):
        # a page frames its node (ADR-0127 decision 8), and the head is the frame's top
        # for every reader, the kiosk's too; its door for every reader but the kiosk
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertIsNotNone(self._door(head))
        self.assertEqual(head.all("rule-setter"), [])
        self._kiosk()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertIsNone(self._door(head))
        self.client.delete_cookie("ls_prefs")
        self._viewer()
        head = self._page("/status/hemulen").one("viewed-head")
        self.assertIsNotNone(self._door(head))
        self.assertEqual(head.all("rule-setter"), [])

    def test_the_way_back_survives_a_name_a_url_has_to_quote(self):
        # A node's name is its check's to choose, and `#` unquoted would cut the
        # way back short: the write would land on another page.
        self.tree.upsert("/rack #2/psu", StatusCode.OK)
        door = self._door(self._page("/status/rack%20%232").one("viewed-head"))
        assert door is not None
        self.assertEqual(door.attrs.get("href"), "/notes/rack%20%232")
        (form,) = [form for form in self._page("/notes/rack%20%232").all("ls-kind-form")
                   if form.attrs.get("data-kind") == "maintenance"]
        self.assertEqual(
            self._hidden(form),
            {"path": "/rack #2", "action": "set", "set_at": "",
             "next": "/notes/rack%20%232", "from": "notes"})
        response = self.client.post("/pins/maintenance", data={
            **self._hidden(form), "note": "a supply is swapped",
            "duration": "2h"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/notes/rack%20%232")
        self.assertIsNotNone(self.tree.maintenance_entry("/rack #2"))

    def test_what_the_head_shows_the_cards_beneath_it_leave_out(self):
        # The head of a node with nothing to say is still the topmost node in view
        # (ADR-0044): its time is said once, there — for every reader, since every
        # page frames its node (ADR-0127 decision 8).
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
        # the API's: no head, no door on the overview's own card at depth 0 — the
        # root has no Notes tab — and no editor in the grid whose path is the root's
        for url in ("/status", "/status?depth=0"):
            page = self._page(url)
            self.assertEqual(page.all("viewed-head"), [], url)
            paths = {self._hidden(form).get("path")
                     for form in page.one("status-grid").all(tag="form")
                     if form.attrs.get("action") == "/pins/maintenance"}
            self.assertNotIn("", paths, url)
            self.assertNotIn("/", paths, url)
            doors = {door.attrs.get("href") for door in page.all("node-icon")
                     if door.attrs.get("data-control") == "door"}
            self.assertNotIn("/notes/", doors, url)
            self.assertNotIn("/notes", doors, url)
        self.assertIsNone(self._door(self._page("/status?depth=0")
                                     .one("status-card__head")))

    def test_the_head_is_in_what_the_refresh_swaps(self):
        self._pin("/gaffsie")
        fragment = self._page("/status/gaffsie?fragment=1")
        block, = self._stated(fragment.one("viewed-head"))
        self.assertEqual(self._hidden(block.one("rule-block__clear"))["next"],
                         "/status/gaffsie")

    def test_at_depth_zero_a_branch_s_card_carries_its_door(self):
        page = self._page("/status/hemulen?depth=0")
        door = self._door(self._card(page, "/hemulen").one("status-card__head"))
        assert door is not None
        self.assertEqual(door.attrs.get("href"), "/notes/hemulen")
        self.assertEqual(page.all("rule-block--new"), [])

class PinAboveHeadTests(_WallCase):
    """ADR-0104 decision 2 on a branch's page: a pin set on a node above it
    is stated in the head, where it acts, as the pin's block without buttons,
    naming and linking the node it stands on."""

    @classmethod
    def _above(cls, where: Element) -> list[Element]:
        """The blocks in ``where`` that state a pin set above it."""
        return [block for block in cls._stated(where)
                if "maintenance from" in block.one("rule-block__what").text()]

    def test_the_head_states_a_pin_above_as_its_block(self):
        entry = self._pin("/nexus")
        page = self._page("/status/nexus/qnap")
        block, = self._above(page.one("viewed-head"))
        what = block.one("rule-block__what")
        self.assertEqual(
            what.text(),
            f"This node is in maintenance from /nexus by lex until "
            f"{self._until(entry)} · 1d 23h left")
        link, = what.all(tag="a")
        self.assertEqual(link.attrs.get("href"), "/status/nexus")
        self.assertEqual(len(block.one("rule-block__note").all(tag="p")), 3)
        self.assertEqual(block.all(tag="form") + block.all(tag="details"), [])
        # above the children it covers
        self.assertLess(block.order, page.one("status-grid").order)

    def test_a_viewer_reads_it_in_the_head(self):
        # every page's head is drawn now (ADR-0127 decision 8); a pin above silencing
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

    def test_a_pin_above_is_no_part_of_the_node_s_door(self):
        # it is counted on the door of the node it stands on, and stands in this
        # node's tab so that a reader sees why the node is blue (ADR-0147 decision 2)
        self._pin("/nexus")
        door = self._door(self._page("/status/nexus/qnap").one("viewed-head"))
        assert door is not None
        self.assertEqual(door.attrs.get("title"), "Handle it")
        above = self._door(self._card(self._page(), "/nexus").one("status-card__head"))
        assert above is not None
        self.assertEqual(above.attrs.get("title"),
                         "Handle it — 1 handled: 1 node in maintenance")
        self.assertIn("in maintenance from", self._body("/notes/nexus/qnap"))

    def test_the_node_s_own_pin_under_one_is_also_in_maintenance_on_its_own(self):
        self._pin("/nexus", by="anna")
        own = self._pin("/nexus/qnap")
        head = self._page("/status/nexus/qnap").one("viewed-head")
        above, mine = self._stated(head)
        self.assertIn("in maintenance from /nexus by anna",
                      above.one("rule-block__what").text())
        self.assertEqual(
            mine.one("rule-block__what").text(),
            f"This node is also in maintenance on its own by lex until "
            f"{self._until(own)} · 1d 23h left")
        self.assertTrue(mine.all("rule-block__clear"))

    def test_at_depth_zero_the_node_s_card_states_it(self):
        entry = self._pin("/nexus")
        card = self._page("/status/nexus/qnap?depth=0").one("status-card")
        block, = self._above(card)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"In maintenance from /nexus by lex until {self._until(entry)} "
            "· 1d 23h left")

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

    #: The editor's own open disclosure around its form — named by its class, so
    #: that no other disclosure the grid may hold matches it (ADR-0127's stage 2
    #: narrowed it from any `details[open]`): a block's, the one editor the wall and a
    #: node's page carry since a line's pause mark and its ringed check went with the
    #: door (ADR-0147).
    EDITOR = "details.maintenance-editor-disclosure[open] form.maintenance-editor-form"

    def test_every_editor_on_these_pages_is_what_the_refresh_looks_for(self):
        # the editor's own open disclosure around a `form.maintenance-editor-form`
        self.assertIn(f"var EDITOR = '{self.EDITOR}';", self._script("poll.js"))
        self._pin("/gaffsie")
        self._pin("/nexus/qnap", note="disk swap")
        self._pin("/hemulen", note="new fans")
        self._details()
        # the wall's blocks are links that open the drawer, which the refresh waits
        # for in a test of its own (ADR-0147 decisions 4 and 7): none is an editor
        for url in ("/status", "/status?depth=3&fragment=1"):
            self.assertEqual([form for form in self._page(url).all(tag="form")
                              if form.all(tag="textarea")], [], url)
        for url in ("/status/gaffsie", "/status/hemulen", "/status/hemulen?depth=0",
                    "/status/nexus/qnap"):
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
                self.assertTrue(around.has("maintenance-editor-disclosure"),
                                (url, around.attrs))

    def test_the_editor_says_it_and_the_page_dims_after_a_minute(self):
        # the pause is said where its cause is, the stamp keeping its width, on Lex's
        # word of 2026-10-30 (ADR-0147 decision 4): an open editor's form says
        # *updates paused* at its top, and the stamp says nothing more than at rest
        script = self._script("poll.js")
        self.assertNotIn("paused while", script)
        # the stylesheet shows the line in an editor open in what the poll marks
        self.assertIn("container.setAttribute('data-ls-poll-target', '');", script)
        self.assertIn("[data-ls-poll-target] .maintenance-editor-disclosure[open]"
                      " .ls-paused", self._css())
        self.assertIn("var WAIT_DIMS_AFTER_MS = 60000;", script)
        self.assertIn("setTimeout(dim, WAIT_DIMS_AFTER_MS)", script)
        self._pin("/gaffsie")
        page = self._page("/status/gaffsie")
        (editor,) = page.one("viewed-head").all("rule-block__editor", tag="form")
        first = editor.all(tag="p")[0]
        self.assertEqual((first.attrs.get("class"), first.text()),
                         ("ls-paused", "updates paused"))
        self.assertNotIn("paused", page.with_id("status-updated").text())

    def test_the_sheet_dims_all_but_what_holds_the_open_editor(self):
        css = self._css()
        waiting, = css_rules_naming(css, ".poll-waiting")
        # as a page that lost its server dims
        dim, = re.findall(r"opacity:\s*([\d.]+)", css_rule(css, ".poll-stale"))
        self.assertIn(f"opacity: {dim};", waiting)
        sheet = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
        # the editor's own disclosure, as the scripts name it
        holds = (r":not\(:has\(details\.maintenance-editor-disclosure\[open\] "
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

    def test_no_editor_is_cloned_and_one_door_stands_on_each_head(self):
        # ‖ cloned the page's one editor into a card's panel or a box; with the door
        # nothing is set on the wall (ADR-0147 decision 1), so the stylesheet keeps
        # nothing of the clone, the blocks keep their padding and size, and none of
        # the head's row holds a seat for a mark
        css = self._css()
        for gone in (".pin-setter", ".ack-setter", ".rule-setter", ".reason-pin",
                     ".reason-ack", ".maintenance-pip", ".status-card__state--seat",
                     ".pin-control"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, css)
        for where in (".status-panel", ".tree-box"):
            with self.subTest(where=where):
                rule = css_rule(css, f"{where} > .rule-block")
                self.assertIn("padding: 0.35rem 0.55rem;", rule)
                self.assertIn("font-size: 0.8rem;", rule)
        # and the doors stand one a head: on the wall's cards and boxes, pinned or
        # not, and on a node's own card at depth 0
        self._pin("/gaffsie")
        heads = [head for url in ("/status", "/status/hemulen?depth=0",
                                  "/status/gaffsie?depth=0")
                 for head in self._page(url).all("status-card__head")
                 + self._page(url).all("status-node__self")]
        self.assertGreater(len(heads), 5)
        for head in heads:
            doors = [link for link in head.all(tag="a")
                     if link.attrs.get("data-control") == "door"]
            self.assertEqual(len(doors), 1, head)
            # plain among the icons; lit in the state cluster, under the library's
            # look, whose toolbar shows only under the pointer
            lit = doors[0].has("is-lit")
            self.assertEqual(doors[0].parent.has("node-icons"), not lit, head)
            self.assertEqual(doors[0].has("state-door"), lit, head)

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
                           if icon.attrs.get("data-control") == "door"]]
            self.assertGreater(len(controls), 0, url)
            for control in controls:
                node = control
                while node is not None:
                    self.assertFalse(a_name(node), (url, control))
                    node = node.parent

    def test_the_inspection_card_stays_away_from_a_row_whose_editor_is_open(self):
        # The mark that opened an editor has given way to it, so the
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
        # a page's head keeps its pin's block, and the block's editor, beneath its
        # row, in the frame, which is the node the script asks of the head's row
        self._pin("/hemulen")
        page = self._page("/status/hemulen")
        edit = page.one("viewed-head").one("rule-block__edit")
        frame = page.one("node-frame")
        self.assertTrue(frame.has("tree-node"))
        self.assertTrue(edit.within(frame))
        self.assertTrue(page.one("viewed-head").one("status-node__self").within(frame))
        self.assertGreater(edit.order,
                           page.one("viewed-head").one("status-node__self").order)
        self.assertEqual(len(edit.all("maintenance-editor-form")), 1)
        # on the wall a stated pin is a link in the box, outside the row and inside the
        # node, with no editor in it to stay away from (ADR-0147 decision 7)
        self._pin("/nexus/qnap", note="disk swap")
        self._details()
        page = self._page()
        box = self._box(page, "/nexus/qnap")
        block = next(block for block in box.all("rule-block") if block.parent is box)
        self.assertEqual(block.all("rule-block__edit"), [])
        self.assertEqual(self._row(page, "/nexus/qnap").all("rule-block"), [])
        around = block.parent
        while around is not None and "data-node" not in around.attrs:
            around = around.parent
        assert around is not None
        self.assertEqual(around.attrs["data-node"], "/nexus/qnap")
