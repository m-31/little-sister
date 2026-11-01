"""A pin is one block on what it silences, and it is edited there (ADR-0104).

The leaf page's half of that decision: the node's block a row at the head of the
frame the page draws the node in, which runs round its lines (decision 8), a line's
block beneath its line, the doors that open the node's *Notes*
tab, where a pin is set (decision 3 as ADR-0147 amends it), the editor that opens in
the block, and the expiry an edit shows and keeps. A card on the wall and a branch's
head are `tests/test_wall_pins.py`'s; what every editor of a pin shares is the expiry
rule, and that is here.

The page is read as a tree (`tests/page_tree.py`) wherever the claim is about
*where* something stands.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.checks import Unit
from little_sister.pins import MAINTENANCE, Pin
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, css_rule, css_rules_naming, parse

PATH = "/ci/actions"
#: The node as the page's own forms name it: the route's `branch`, which has no
#: leading slash. A test that posts the absolute path instead is not posting what
#: an admin's browser does.
FORM_PATH = "ci/actions"
LINES = {
    "web-build": "web build failed on main",
    "api-build": "api build failed on main",
    "mobile-build": "mobile build is disabled",
    "docs-deploy": "docs deploy is queued",
    "nightly": "nightly e2e timed out",
    "lint": "lint took 11 minutes",
}
NOTE = ("Runner fleet is being replaced this **weekend**, ticket "
        "[OPS-1432](https://tickets.example.org/OPS-1432).\n\n"
        "The spare runners are in the rack.\n\n"
        "Builds queue until Sunday night.")
LINE_NOTE = "Switched off until the signing key is renewed."


def _noon_ahead(days: int = 40) -> datetime:
    """An expiry as the tree stores one — an instant, with a fraction of a
    second — at noon in the configured zone. No clock change touches noon, so the
    text a field shows for it always reads back as the same minute."""
    noon = (datetime.now(app_module.config.tzinfo)
            + timedelta(days=days)).replace(hour=12, minute=0, second=7,
                                            microsecond=123456)
    return noon.astimezone(UTC)


class _Scheduled:
    """What the floor reads off a configured check: its path and, as its one
    unit's, its frequency (ADR-0130)."""

    def __init__(self, path: str, frequency_seconds: int) -> None:
        self.path = path
        self.frequency_seconds = frequency_seconds

    def units(self) -> tuple[Unit, ...]:
        return (Unit("", self.frequency_seconds, ""),)


class _LeafCase(TestCase):
    """A node shaped like a workflow check — six lines that can be pinned one by
    one — read by an admin unless a test says otherwise."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _viewer(self) -> None:
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    def _workflows(self, lines: dict[str, str] | None = None) -> None:
        self.tree.upsert(PATH, StatusCode.ERROR, dict(lines or LINES))

    def _pin_node(self, note: str | None = NOTE, by: str = "lex",
                  left: timedelta = timedelta(days=1, hours=23, minutes=30),
                  ) -> Pin:
        write = self.tree.set_maintenance(
            PATH, note, expires_at=datetime.now(UTC) + left, set_by=by)
        assert write.current is not None
        return write.current

    def _pin_line(self, slug: str = "mobile-build", note: str = LINE_NOTE,
                  by: str = "anna",
                  left: timedelta = timedelta(hours=5, minutes=30),
                  ) -> Pin:
        write = self.tree.set_entry_maintenance(
            PATH, slug, note, expires_at=datetime.now(UTC) + left, set_by=by)
        assert write.current is not None
        return write.current

    def _body(self, path: str = PATH) -> str:
        response = self.client.get("/status" + path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def _page(self, path: str = PATH) -> Element:
        return parse(self._body(path))

    def _css(self) -> str:
        return self.client.get(
            "/static/css/overview.css").get_data(as_text=True)

    @staticmethod
    def _card(page: Element) -> Element:
        """The page's head: what says how the node is — its row, the rules acting
        on it, its lines — atop the frame the page draws the node in."""
        return page.one("viewed-head")

    @staticmethod
    def _row(page: Element) -> Element:
        """The head's row: the node's name, its actions and its state."""
        return page.one("viewed-head").one("status-node__self")

    @staticmethod
    def _stated(page: Element, scope: str = "") -> list[Element]:
        """The blocks that state a pin — not the editors of one still to be set,
        which stand where the block will."""
        return [block for block in page.all("rule-block")
                if not block.has("rule-block--new")
                and (not scope or block.has(f"rule-block--{scope}"))]

    @staticmethod
    def _line(page: Element, slug: str) -> Element:
        """The line of the node that reports ``slug``."""
        for line in page.all("check-reason"):
            if line.one("check-reason__body").text() == LINES[slug]:
                return line
        raise AssertionError(f"no line for {slug}")

    @staticmethod
    def _hidden(form: Element) -> dict[str, str]:
        return {box.attrs["name"]: box.attrs.get("value", "")
                for box in form.all(tag="input")
                if box.attrs.get("type") == "hidden"}

    @staticmethod
    def _expiry_field(form: Element) -> Element:
        fields = [box for box in form.all(tag="input")
                  if box.attrs.get("name") == "duration"]
        assert len(fields) == 1
        return fields[0]

    @staticmethod
    def _note_form(page: Element) -> Element:
        """The one form on a refusal's page that holds the admin's own words."""
        forms = [form for form in page.all(tag="form")
                 if form.all(tag="textarea")]
        assert len(forms) == 1, f"{len(forms)} forms with a note, wanted one"
        return forms[0]

    def _post(self, **fields: str):
        """A set, addressed as the page's forms address it."""
        return self.client.post(
            "/pins/maintenance",
            data={"path": FORM_PATH, "action": "set", **fields})


class PinBlockTests(_LeafCase):
    """Decisions 1 and 2: one block states a pin, and where the block stands
    says what it covers."""

    def test_a_nodes_pin_is_one_block_at_the_head_of_its_page(self):
        self._workflows()
        entry = self._pin_node()
        raw = self._body()
        page = parse(raw)
        blocks = self._stated(page)
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertTrue(block.has("rule-block--node"))
        card = self._card(page)
        self.assertTrue(block.within(card))
        until = app_module._localtime(entry.expires_at)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"This node is in maintenance by lex until {until} · 1d 23h left")
        # at the head: under the head's row and above the first line
        self.assertLess(self._row(page).order, block.order)
        self.assertLess(block.order, card.all("check-reason")[0].order)
        # and stated once: neither the strip nor the card at the foot says it again
        self.assertNotIn("pin-banner", raw)
        self.assertEqual(raw.count("is in maintenance by"), 1)
        # and maintenance says its own words, *silenced* being a later kind's
        # (ADR-0135 decision 2)
        self.assertNotIn("silenced by", raw)

    def test_the_note_stands_in_full(self):
        # the strip it replaces was cut off after two lines
        self._workflows()
        self._pin_node()
        note = self._stated(self._page())[0].one("rule-block__note")
        self.assertEqual(len(note.all(tag="p")), 3)
        self.assertTrue(note.text().endswith("Builds queue until Sunday night."))
        self.assertEqual(note.one(tag="strong").text(), "weekend")
        self.assertEqual(note.one(tag="a").attrs["href"],
                         "https://tickets.example.org/OPS-1432")
        for body in css_rules_naming(self._css(), ".rule-block"):
            self.assertNotIn("line-clamp", body)
            self.assertNotIn("text-overflow", body)

    def test_what_is_left_reads_as_a_bound(self):
        now = datetime.now(UTC)
        for left, said in (
                (timedelta(days=2, minutes=5), "2d left"),
                (timedelta(days=1, hours=23, minutes=30), "1d 23h left"),
                (timedelta(hours=5, minutes=30, seconds=30), "5h 30m left"),
                (timedelta(minutes=12, seconds=30), "12m left"),
                (timedelta(seconds=30), "< 1m left"),
                (timedelta(seconds=-5), "expired")):
            with self.subTest(left=str(left)):
                self.assertEqual(app_module._time_left(now + left), said)
        self.assertEqual(app_module._time_left(None), "expired")

    def test_a_pin_past_its_end_is_ended_by_the_page_that_asks(self):
        # open and closed are decided at the moment a snapshot is asked (ADR-0150):
        # the page that asks after the end ends the pin, as the tick would have a
        # moment later, and says nothing of it
        self._workflows()
        entry = self._pin_node(left=timedelta(minutes=5))
        assert entry.expires_at is not None
        later = entry.expires_at + timedelta(seconds=30)
        with mock.patch.object(instants, "now", lambda: later):
            stated = self._stated(self._page())
        self.assertEqual(stated, [])
        self.assertIsNone(self.tree.maintenance_entry(PATH))
        self.assertEqual(self.tree.recent_events()[-1].cause, "pin-ended")

    @staticmethod
    def _whole(said: Element) -> list[str]:
        """What a sentence keeps on one line each, in the order it says them."""
        return [span.text() for span in said.all("text-nowrap")]

    def test_the_expiry_keeps_its_date_and_its_time_whole(self):
        # Where a card was narrow the sentence ended a line after a
        # hyphen of the date — *until 2026-10-* — and the day stood on the next
        # one with the time.
        self._workflows()
        for scope, entry in (("node", self._pin_node()),
                             ("line", self._pin_line())):
            with self.subTest(scope=scope):
                said = self._stated(self._page(), scope)[0].one("rule-block__what")
                date, time = app_module._localtime(entry.expires_at).split(" ")
                # the date is what a line ends in: a hyphen is a place to
                self.assertEqual(date.count("-"), 2)
                left = app_module._time_left(entry.expires_at)
                self.assertEqual(self._whole(said), [date, time, f"· {left}"])
                # and between the two a line may end, as between any two words
                parts = [child if isinstance(child, str) else child.text()
                         for child in said.children]
                at = parts.index(date)
                self.assertEqual(parts[at:at + 3], [date, " ", time])

    def test_every_word_of_a_longer_time_format_is_kept_whole(self):
        # a deployment writes its instants as it likes, and a date with the
        # month's name ends a line nowhere but between its words
        self._workflows()
        entry = self._pin_node()
        settings = mock.patch(
            "little_sister.config.config",
            replace(app_module.config, time_format="%d %b %Y, %H:%M"))
        with settings:
            said = self._stated(self._page())[0].one("rule-block__what")
            until = str(app_module._localtime(entry.expires_at))
        words = until.split(" ")
        self.assertEqual(len(words), 4)
        self.assertEqual(self._whole(said), [*words, "· 1d 23h left"])
        self.assertEqual(
            said.text(),
            f"This node is in maintenance by lex until {until} · 1d 23h left")

    def test_the_nodes_block_frames_every_line(self):
        # the page's frame is the border running round every line the pin covers:
        # the block heads it and the lines stand inside it, with no second border
        self._workflows()
        self._pin_node()
        page = self._page()
        frame = page.one("node-frame")
        self.assertEqual(page.all("rule-frame"), [])
        self.assertTrue(self._stated(page)[0].within(frame))
        lines = page.all("check-reason")
        self.assertEqual(len(lines), len(LINES))
        for line in lines:
            self.assertTrue(line.within(frame))

    def test_a_node_without_a_pin_has_no_block_and_no_border_of_its_own(self):
        self._workflows()
        self._pin_line()
        page = self._page()
        self.assertEqual(page.all("rule-frame"), [])
        self.assertEqual(self._stated(page, "node"), [])

    def test_the_head_of_the_frame_is_the_list_of_the_nodes_rules(self):
        # decision 8: a second rule on the node is a second row of this list
        self._workflows()
        self._pin_node()
        head = self._card(self._page()).one("rule-list")
        self.assertEqual(head.tag, "ul")
        rows = [child for child in head.children
                if isinstance(child, Element)]
        self.assertEqual(
            [(row.tag, row.has("rule-block"), row.attrs.get("data-rule"))
             for row in rows],
            [("li", True, "maintenance")])

    def test_a_pinned_line_carries_its_block_beneath_it(self):
        self._workflows()
        entry = self._pin_line("mobile-build")
        page = self._page()
        blocks = self._stated(page)
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertTrue(block.has("rule-block--line"))
        line = self._line(page, "mobile-build")
        self.assertTrue(block.within(line))
        self.assertLess(line.one("check-reason__body").order, block.order)
        until = app_module._localtime(entry.expires_at)
        self.assertEqual(
            block.one("rule-block__what").text(),
            f"This line is in maintenance by anna until {until} · 5h 29m left")
        self.assertEqual(block.one("rule-block__note").text(), LINE_NOTE)

    def test_under_a_nodes_pin_a_line_says_it_is_also_in_maintenance_on_its_own(self):
        # it stays quiet when the node's pin ends, which is why it says so
        self._workflows()
        self._pin_node()
        entry = self._pin_line()
        page = self._page()
        until = app_module._localtime(entry.expires_at)
        self.assertEqual(
            self._stated(page, "line")[0].one("rule-block__what").text(),
            f"This line is also in maintenance on its own by anna until {until} "
            f"· 5h 29m left")
        self.assertNotIn(
            "also", self._stated(page, "node")[0].one("rule-block__what").text())

    def test_a_block_says_its_kind_as_data(self):
        # decision 8: the kind is data, and maintenance is the first
        self._workflows()
        self._pin_node()
        self._pin_line()
        blocks = self._page().all("rule-block")
        # the node's and the line's: no editor of a new pin stands here (ADR-0147)
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertEqual(block.attrs.get("data-rule"), "maintenance")

    def test_the_block_paints_its_own_tint_and_the_frame_is_a_border(self):
        # so both stand on a node of any color (decision 8)
        css = self._css()
        block = css_rule(css, '.rule-block[data-rule="maintenance"]')
        self.assertIn("background: var(--ls-tint-maintenance)", block)
        self.assertIn("color: var(--ls-tint-maintenance-ink)", block)
        frame = css_rule(css, ".node-frame")
        self.assertIn("border:", frame)
        self.assertNotIn("background", frame)

    def test_a_viewer_reads_the_blocks_and_gets_no_buttons(self):
        self._workflows()
        self._pin_node()
        self._pin_line()
        self._viewer()
        raw = self._body()
        page = parse(raw)
        blocks = self._stated(page)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(len(page.all("rule-block")), 2)   # and no editor of one
        for block in blocks:
            self.assertRegex(block.one("rule-block__what").text(),
                             r"^This (node|line) is (also )?in maintenance")
            self.assertTrue(block.all("rule-block__note"))
            self.assertEqual(block.all(tag="form") + block.all(tag="details")
                             + block.all(tag="button"), [])
        card = self._card(page)
        self.assertEqual(card.all(tag="form") + card.all(tag="details")
                         + card.all(tag="summary"), [])
        self.assertNotIn('name="set_at"', raw)

    def test_the_card_at_the_foot_is_gone_from_a_leafs_page(self):
        self._workflows()
        for pinned in (False, True):
            with self.subTest(pinned=pinned):
                if pinned:
                    self._pin_node()
                raw = self._body()
                self.assertNotIn('text-uppercase">Maintenance<', raw)
                self.assertNotIn("maintenance-card__actions", raw)


class SetControlTests(_LeafCase):
    """Decision 3, as ADR-0147 decision 1 amends it: a pin is set on the node's *Notes*
    tab, which the head's door opens, and each member line's own ◇ with its form on
    that line — and nothing new is set on the node's page."""

    def _setters(self, page: Element) -> list[Element]:
        return [summary for summary in page.all(tag="summary")
                if summary.text(shown=True) == "Set maintenance"]

    def test_the_page_s_head_sets_nothing_its_door_opens_the_tab(self):
        self._workflows()
        page = self._page()
        self.assertEqual(self._setters(page), [])
        self.assertEqual(page.all("rule-setter"), [])
        (door,) = [link for link in self._row(page).all(tag="a")
                   if link.attrs.get("data-control") == "door"]
        self.assertEqual(door.attrs.get("href"), "/notes/ci/actions")

    def test_a_pinned_node_has_edit_and_clear_instead(self):
        self._workflows()
        self._pin_node()
        self.assertEqual(self._setters(self._page()), [])

    def test_each_member_line_ends_in_its_door(self):
        self._workflows()
        self._pin_line("mobile-build")
        page = self._page()
        doors = page.all("line-door")
        self.assertEqual(len(doors), len(LINES) - 1)
        for door in doors:
            # a mark, with its name for a reader who cannot see it
            self.assertEqual(door.tag, "a")
            self.assertTrue(door.all(tag="svg"))
            self.assertEqual(door.text(shown=True), "")
            self.assertEqual(door.attrs.get("title"), "Handle this line")
            self.assertEqual(door.attrs.get("aria-label"),
                             "handle this line of /ci/actions")
        for slug in LINES:
            with self.subTest(line=slug):
                found = self._line(page, slug).all("line-door")
                if slug == "mobile-build":
                    # where something handles the line its mark is its door
                    self.assertEqual(found, [])
                    continue
                self.assertEqual([door.attrs.get("href") for door in found],
                                 [f"/notes/ci/actions?reason={slug}#add-note"])

    def test_a_door_has_its_seat_in_the_rail(self):
        # the rail it shares with the line's other actions keeps the place the
        # door is drawn in, so no action sits under it and no text runs into it —
        # on a pinned line too, whose ‖ stands in the seat ◇ stood in (ADR-0143)
        self._workflows()
        self._pin_line("mobile-build")
        page = self._page()
        for slug in LINES:
            with self.subTest(line=slug):
                line = self._line(page, slug)
                rail = line.one("check-reason__rail")
                self.assertTrue(rail.has("check-reason__rail--seat"))
                self.assertEqual(len(line.all("line-pin")),
                                 1 if slug == "mobile-build" else 0)
        # a margin as wide as the door, and a height the rail has even when no
        # action fills it: a float of no height would let the text run under
        css = self._css()
        seat = css_rule(css, ".check-reason__rail--seat")
        self.assertIn("margin-right", seat)
        self.assertIn("min-height", seat)
        self.assertIn("position: absolute",
                      css_rule(css, ".check-reason__box > .line-door"))

    def test_a_line_s_door_opens_the_form_on_the_line(self):
        self._workflows()
        tab = parse(self.client.get("/notes/ci/actions?reason=web-build")
                    .get_data(as_text=True))
        (form,) = [form for form in tab.all("ls-kind-form")
                   if form.attrs.get("data-kind") == MAINTENANCE]
        (on,) = [select for select in form.all(tag="select")
                 if select.attrs.get("name") == "slug"]
        chosen = [option.attrs.get("value") for option in on.all(tag="option")
                  if "selected" in option.attrs]
        self.assertEqual(chosen, ["web-build"])
        self.assertEqual(form.attrs.get("action"), "/pins/maintenance")

    def test_prose_and_a_viewer_get_no_seat(self):
        self.tree.upsert("/db", StatusCode.ERROR,
                         ["check error: unreachable", "Traceback…"])
        self.assertEqual(self._page("/db").all("line-door"), [])
        self._workflows()
        self._viewer()
        page = self._page()
        self.assertEqual(page.all("line-door"), [])
        self.assertEqual(page.all("check-reason__rail--seat"), [])
        self.assertEqual(self._setters(page), [])


class PinAboveTests(_LeafCase):
    """ADR-0104 decision 2: a pin set on a node above this one silences it
    with everything else beneath that node (ADR-0041), and the node's own page
    states it where it acts — the pin's block, without buttons, naming and linking
    the node it stands on — one row of the frame's list for each, outermost first."""

    def _pin_at(self, path: str, note: str | None = NOTE, by: str = "lex",
                left: timedelta = timedelta(days=1, hours=23, minutes=30),
                ) -> Pin:
        write = self.tree.set_maintenance(
            path, note, expires_at=datetime.now(UTC) + left, set_by=by)
        assert write.current is not None
        return write.current

    @staticmethod
    def _rows(page: Element) -> list[Element]:
        """The rows of the list at the head of the node's frame."""
        return [child for child in page.one("viewed-head").one("rule-list").children
                if isinstance(child, Element)]

    def _until(self, entry: Pin) -> str:
        return str(app_module._localtime(entry.expires_at))

    def test_a_pin_above_is_stated_as_its_block_where_it_acts(self):
        self._workflows()
        entry = self._pin_at("/ci")
        page = self._page()
        row, = self._rows(page)
        self.assertEqual((row.tag, row.has("rule-block--node"),
                          row.attrs.get("data-rule")), ("li", True, "maintenance"))
        what = row.one("rule-block__what")
        self.assertEqual(
            what.text(),
            f"This node is in maintenance from /ci by lex until {self._until(entry)} "
            "· 1d 23h left")
        # linked to where it stands, which is where it is edited
        link, = what.all(tag="a")
        self.assertEqual((link.attrs.get("href"), link.text()), ("/status/ci", "/ci"))
        # the note whole, as decision 1 states a pin everywhere it shows
        self.assertEqual(len(row.one("rule-block__note").all(tag="p")), 3)
        # and nothing to press: not even an admin edits it from here
        self.assertEqual(row.all(tag="form") + row.all(tag="details")
                         + row.all(tag="button"), [])
        # it heads the frame round every line, since it silences every one
        for line in page.all("check-reason"):
            self.assertTrue(line.within(page.one("node-frame")))
            self.assertGreater(line.order, row.order)

    def test_each_pin_above_is_a_row_outermost_first(self):
        self.tree.upsert("/ci/fleet/runner7", StatusCode.ERROR, "disk is full")
        outer = self._pin_at("/ci", "rack move", by="anna")
        inner = self._pin_at("/ci/fleet", "fleet swap")
        rows = self._rows(self._page("/ci/fleet/runner7"))
        self.assertEqual(
            [row.one("rule-block__what").text() for row in rows],
            [f"This node is in maintenance from /ci by anna until {self._until(outer)} "
             "· 1d 23h left",
             f"This node is in maintenance from /ci/fleet by lex until "
             f"{self._until(inner)} · 1d 23h left"])

    def test_the_nodes_own_pin_under_one_is_also_in_maintenance_on_its_own(self):
        # it stays quiet when the pin above ends, as a line's does under its node's
        self._workflows()
        self._pin_at("/ci", by="anna")
        own = self._pin_node()
        above, mine = self._rows(self._page())
        self.assertIn("in maintenance from /ci", above.one("rule-block__what").text())
        self.assertEqual(
            mine.one("rule-block__what").text(),
            f"This node is also in maintenance on its own by lex until "
            f"{self._until(own)} · 1d 23h left")
        # the node's own is edited here, as ever
        self.assertTrue(mine.all("rule-block__edit"))
        self.assertTrue(mine.all("rule-block__clear"))

    def test_a_lines_pin_under_one_is_also_in_maintenance_on_its_own(self):
        self._workflows()
        self._pin_at("/ci", by="anna")
        entry = self._pin_line()
        page = self._page()
        self.assertEqual(
            self._stated(page, "line")[0].one("rule-block__what").text(),
            f"This line is also in maintenance on its own by anna until "
            f"{self._until(entry)} · 5h 29m left")


    def test_a_viewer_reads_it_too(self):
        self._workflows()
        self._pin_at("/ci")
        self._viewer()
        raw = self._body()
        page = parse(raw)
        row, = self._rows(page)
        self.assertIn("in maintenance from /ci by lex",
                      row.one("rule-block__what").text())
        self.assertTrue(row.all("rule-block__note"))
        self.assertNotIn('name="set_at"', raw)

    def test_a_pin_on_a_line_above_silences_that_line_alone(self):
        # a node's own pin covers what is beneath it; a line's covers its line
        # (ADR-0124), so it is no row here
        self.tree.upsert("/ci", StatusCode.WARN, {"quota": "runner quota at 90 %"})
        self._workflows()
        self.tree.set_entry_maintenance(
            "/ci", "quota", "raised on Monday",
            expires_at=datetime.now(UTC) + timedelta(hours=5), set_by="anna")
        page = self._page()
        self.assertEqual(page.one("viewed-head").all("rule-list"), [])
        self.assertNotIn("silenced from", self._body())

    def test_a_pin_beside_the_node_is_no_row_of_it(self):
        self._workflows()
        self.tree.upsert("/ci/runners", StatusCode.OK)
        self._pin_at("/ci/runners")
        self.assertEqual(self._page().one("viewed-head").all("rule-list"), [])

    def test_a_pin_on_everything_links_to_the_overview(self):
        # the overview's own pin is not set from a form, and one that stands is
        # stated like any other
        self._workflows()
        self._pin_at("/")
        row, = self._rows(self._page())
        link, = row.one("rule-block__what").all(tag="a")
        self.assertEqual((link.attrs.get("href"), link.text()), ("/status", "/"))


class EditorTests(_LeafCase):
    """Decision 4: Edit opens the block where it stands."""

    def _editor(self, block: Element) -> Element:
        editor = block.one("rule-block__edit")
        self.assertEqual(editor.tag, "details")     # the browser's own
        self.assertNotIn("open", editor.attrs)      # pinned is a read state
        return editor

    def test_edit_turns_the_note_into_its_source(self):
        self._workflows()
        entry = self._pin_node(by="ada")
        block = self._stated(self._page())[0]
        editor = self._editor(block)
        button = editor.first()
        self.assertEqual(button.tag, "summary")
        self.assertEqual(button.text(shown=True), "Edit")
        self.assertEqual(button.text(), "Edit this node's maintenance")
        form = editor.one(tag="form")
        self.assertEqual(form.attrs.get("method"), "post")
        hidden = self._hidden(form)
        self.assertEqual(
            (hidden["path"], hidden["action"], hidden["set_at"]),
            (FORM_PATH, "set", entry.token))
        self.assertNotIn("slug", hidden)
        self.assertEqual(form.one(tag="textarea").source(), NOTE)
        # the editor's own buttons stand before its two, behind the hidden one Enter
        # in a field presses, which sets (ADR-0150, landing 4)
        buttons = form.all(tag="button")
        self.assertTrue(buttons[0].has("ls-default-submit"))
        self.assertEqual([button.text() for button in buttons[-2:]],
                         ["Save changes", "Cancel"])

    @staticmethod
    def _shown_first(form: Element) -> Element:
        """The first element of an editor's form that every page shows: above it only
        the line that says the page waits for the editor, *updates paused*, which the
        stylesheet shows on a page that refreshes alone (ADR-0147 decision 4)."""
        line = form.first()
        if not line.has("ls-paused"):
            return line
        assert line.text() == "updates paused", line
        return next(child for child in form.children
                    if isinstance(child, Element) and child is not line
                    and child.tag != "input")

    def test_who_pinned_it_stands_at_the_top_of_the_editor(self):
        self._workflows()
        entry = self._pin_node(by="ada")

        def record() -> str:
            block = self._stated(self._page())[0]
            said = self._shown_first(self._editor(block).one(tag="form"))
            self.assertTrue(said.has("rule-block__record"))
            return said.text()

        pinned = app_module._localtime(entry.created_at)
        self.assertEqual(record(), f"Pinned by ada {pinned}.")
        # after somebody else's edit it names both, as the card at the foot did
        self._post(note="longer", duration="3d", set_at=entry.token)
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        changed = app_module._localtime(after.set_at)
        self.assertEqual(
            record(), f"Pinned by ada {pinned}. Last changed by pan {changed}.")
        # and the block's own sentence names the last writer: the note it shows
        # and the expiry it states are theirs
        self.assertIn(
            "is in maintenance by pan until",
            self._stated(self._page())[0].one("rule-block__what").text())

    def test_the_record_keeps_its_instants_whole(self):
        # The record stands in an editor, which in a card is as narrow as the card.
        # A pin somebody changed two days after it was set states two instants.
        self._workflows()
        now = datetime.now(UTC)
        pinned, changed = now - timedelta(days=2), now - timedelta(hours=1)
        self.tree.restore_maintenance({PATH: Pin(MAINTENANCE,
            note=NOTE, set_at=changed, set_by="pan",
            expires_at=now + timedelta(days=1),
            created_at=pinned, created_by="ada")})
        block = self._stated(self._page())[0]
        said = self._shown_first(self._editor(block).one(tag="form"))
        self.assertTrue(said.has("rule-block__record"))
        first = str(app_module._localtime(pinned))
        last = str(app_module._localtime(changed))
        self.assertNotEqual(first.split(" ")[0], last.split(" ")[0])
        self.assertEqual(
            said.text(), f"Pinned by ada {first}. Last changed by pan {last}.")
        self.assertEqual([span.text() for span in said.all("text-nowrap")],
                         [*first.split(" "), *last.split(" ")])

    def test_clear_stands_beside_edit_and_names_the_pin_it_clears(self):
        self._workflows()
        entry = self._pin_node()
        block = self._stated(self._page())[0]
        clear = block.one("rule-block__clear")
        self.assertEqual(clear.tag, "form")
        self.assertTrue(clear.within(block.one("rule-block__head")))
        self.assertEqual(self._hidden(clear),
                         {"path": FORM_PATH, "action": "clear",
                          "set_at": entry.token})
        button = clear.one(tag="button")
        self.assertEqual((button.text(shown=True), button.text()),
                         ("Clear", "Clear this node's maintenance"))

    def test_a_lines_block_is_edited_and_cleared_the_same_way(self):
        self._workflows()
        entry = self._pin_line("mobile-build")
        block = self._stated(self._page(), "line")[0]
        editor = self._editor(block)
        self.assertEqual(editor.first().text(), "Edit this line's maintenance")
        form = editor.one(tag="form")
        hidden = self._hidden(form)
        self.assertEqual(
            (hidden["path"], hidden["slug"], hidden["action"], hidden["set_at"]),
            (FORM_PATH, "mobile-build", "set", entry.token))
        self.assertEqual(form.one(tag="textarea").source(), LINE_NOTE)
        clear = block.one("rule-block__clear")
        self.assertEqual(self._hidden(clear),
                         {"path": FORM_PATH, "slug": "mobile-build",
                          "action": "clear", "set_at": entry.token})
        self.assertEqual(clear.one(tag="button").text(),
                         "Clear this line's maintenance")

    def test_the_editors_text_is_the_pins_note(self):
        # decision 8: a pin has a note; a check's lines are its reasons
        self._workflows()
        self._pin_node()
        raw = self._body()
        form = self._stated(parse(raw))[0].one(tag="form", name="rule-block__editor")
        box = form.one(tag="textarea")
        labels = [label.text() for label in form.all(tag="label")
                  if label.attrs.get("for") == box.attrs["id"]]
        self.assertEqual(labels, ["Note"])
        self.assertEqual(box.attrs.get("name"), "note")     # the route's field
        self.assertNotIn(">Reason</label>", raw)

    def test_a_pin_without_a_note_shows_none_and_edits_an_empty_field(self):
        # the stored placeholder is not a note anybody wrote
        self._workflows()
        entry = self._pin_node(note=None)
        self.assertEqual(entry.note, "maintenance")
        block = self._stated(self._page())[0]
        self.assertEqual(block.all("rule-block__note"), [])
        self.assertEqual(
            self._editor(block).one(tag="textarea").source(), "")

    def test_an_open_editor_stands_in_for_the_note_and_the_buttons(self):
        # what Edit *turns into* is the stylesheet's: the note and Clear give way
        # while the editor is open, and the editor takes the block's width
        css = self._css()
        self.assertIn(
            "display: none",
            css_rule(css, ".rule-block:has(.rule-block__edit[open]) "
                       "> .rule-block__note"))
        self.assertIn(
            "display: none",
            css_rule(css, ".rule-block__head:has(> .rule-block__edit[open]) "
                       "> .rule-block__clear"))
        # full width and no wider: a flex item keeps the width of its fields
        # unless told otherwise, and that widened a phone's page
        rule = css_rule(css, ".rule-block__edit[open]")
        self.assertIn("flex-basis: 100%", rule)
        self.assertIn("min-width: 0", rule)

    def test_the_notes_field_shows_the_whole_note(self):
        # where the browser sizes a field by its content; a field sized that way
        # ignores its rows, so the floor an empty one keeps is stated beside it
        rule = css_rule(self._css(),
                     "textarea.form-control.maintenance-reason-source")
        self.assertIn("field-sizing: content", rule)
        self.assertIn("min-height", rule)

    def test_opening_an_editor_starts_in_its_note(self):
        # the expiry is selected only when its own field is entered, so the first
        # keystroke meant for the note lands in the note
        script = self.client.get(
            "/static/js/maintenance-edit.js").get_data(as_text=True)
        self.assertIn('document.addEventListener("toggle"', script)
        self.assertIn('textarea[name="note"]', script)


class KeptExpiryTests(_LeafCase):
    """Decision 5: an edit shows the expiry it would keep."""

    def _form(self, page: Element | None = None) -> Element:
        block = self._stated(page or self._page(), "node")[0]
        return block.one("rule-block__edit").one(tag="form")

    def test_an_edit_shows_the_stored_expiry(self):
        self._workflows()
        entry = self._pin_node()
        was = app_module._expiry_input(entry.expires_at)
        self.assertRegex(was, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        form = self._form()
        self.assertEqual(self._expiry_field(form).attrs.get("value"), was)
        # and the form carries what the field was filled with
        self.assertEqual(self._hidden(form)["expiry_was"], was)
        self.assertIn(
            "Unchanged, the pin keeps this expiry; emptied, it runs for the "
            "default, 7d, from now.", form.text())

    def test_the_expiry_is_written_in_the_configured_timezone(self):
        # as the field reads one: unzoned input is the configured zone's
        stored = datetime(2026, 12, 24, 18, 0, 5, tzinfo=UTC)
        with mock.patch.object(
                app_module, "config",
                replace(app_module.config, timezone="Pacific/Auckland")):
            self.assertEqual(app_module._expiry_input(stored),
                             "2026-12-25 07:00:05")
        with mock.patch.object(
                app_module, "config",
                replace(app_module.config, timezone="Europe/Berlin")):
            self.assertEqual(app_module._expiry_input(stored),
                             "2026-12-24 19:00:05")
        self.assertEqual(app_module._expiry_input(None), "")

    def test_a_new_pins_field_is_empty_and_keeps_nothing(self):
        # a new pin is set on the node's Notes tab (ADR-0147 decision 1): the node's
        # page carries no field of one, and the tab's are empty
        self._workflows()
        self.assertNotIn('name="duration"', self._body())
        raw = self.client.get("/notes/ci/actions").get_data(as_text=True)
        self.assertNotIn('name="expiry_was"', raw)
        self.assertNotIn("the pin keeps this expiry", raw)
        fields: dict[str, list[Element]] = {}
        for form in parse(raw).all(tag="form"):
            for box in form.all(tag="input"):
                if box.attrs.get("name") == "duration":
                    fields.setdefault(form.attrs.get("action", ""), []).append(box)
        # one form of each kind, its *On* the node, a line, or every failure
        self.assertEqual({action: len(boxes) for action, boxes in fields.items()},
                         {"/pins/maintenance": 1, "/pins/seen": 1})
        for box in [box for boxes in fields.values() for box in boxes]:
            self.assertEqual(box.attrs.get("value"), "")

    def test_a_field_left_as_it_was_filled_keeps_the_instant_exactly(self):
        self._workflows()
        expires = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=123456)
        entry = self.tree.set_maintenance(
            PATH, "the first words", expires_at=expires, set_by="ada").current
        assert entry is not None
        was = self._expiry_field(self._form()).attrs["value"]
        response = self._post(note="reworded", duration=was, expiry_was=was,
                              set_at=entry.token)
        self.assertEqual(response.status_code, 302)
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        # to the microsecond: the field's text is not read again
        self.assertEqual(after.expires_at, entry.expires_at)
        self.assertEqual(after.expires_at.microsecond, 123456)
        self.assertEqual((after.note, after.set_by, after.created_by),
                         ("reworded", "pan", "ada"))
        self.assertNotEqual(after.set_at, entry.set_at)      # it was a write

    def test_the_floor_cannot_refuse_an_edit_that_left_the_window_alone(self):
        # ADR-0014 decision 13 holds a *typed* expiry to the slowest covered
        # check's interval; a pin with forty days left under a check that runs
        # every three hundred is below it, and correcting a word in its note
        # must still save
        self._workflows()
        app_module.engine = mock.Mock(checks=[_Scheduled(PATH, 300 * 86400)])
        self.addCleanup(setattr, app_module, "engine", None)
        entry = self.tree.set_maintenance(
            PATH, "forty days left", expires_at=_noon_ahead(40),
            set_by="ada").current
        assert entry is not None
        was = app_module._expiry_input(entry.expires_at)
        kept = self._post(note="reworded", duration=was, expiry_was=was,
                          set_at=entry.token)
        self.assertEqual(kept.status_code, 302)
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        self.assertEqual((after.note, after.expires_at),
                         ("reworded", entry.expires_at))
        # the same text typed — nothing says the field was filled with it — is
        # an expiry like any other, and meets the floor
        typed = self._post(note="again", duration=was, set_at=after.token)
        self.assertEqual(typed.status_code, 200)
        self.assertIn(f"ends before {PATH} (every 300d) runs again",
                      typed.get_data(as_text=True))
        self.assertEqual(self.tree.maintenance_entry(PATH), after)

    def test_the_hour_a_clock_change_repeats_cannot_refuse_it(self):
        # 02:30 on the night the clocks go back happens twice in Berlin, and the
        # field's text cannot say which; the stored instant can
        # the day before, so that the window holds (ADR-0150)
        self.enterContext(mock.patch.object(
            instants, "now", lambda: datetime(2026, 10, 24, 12, tzinfo=UTC)))
        self._workflows()
        second = datetime(2026, 10, 25, 2, 30, fold=1,
                          tzinfo=ZoneInfo("Europe/Berlin"))
        entry = self.tree.set_maintenance(
            PATH, "over the clock change", expires_at=second,
            set_by="ada").current
        assert entry is not None
        with mock.patch.object(
                app_module, "config",
                replace(app_module.config, timezone="Europe/Berlin")):
            was = app_module._expiry_input(entry.expires_at)
            self.assertEqual(was, "2026-10-25 02:30:00")
            kept = self._post(note="reworded", duration=was, expiry_was=was,
                              set_at=entry.token)
            after = self.tree.maintenance_entry(PATH)
            assert after is not None
            typed = self._post(note="again", duration=was,
                               set_at=after.token)
        self.assertEqual(kept.status_code, 302)
        self.assertEqual((after.note, after.expires_at),
                         ("reworded", entry.expires_at))
        self.assertIn("is not an unambiguous local time",
                      typed.get_data(as_text=True))

    def test_an_emptied_field_means_the_default_from_now(self):
        self._workflows()
        entry = self._pin_node(left=timedelta(hours=3))
        was = app_module._expiry_input(entry.expires_at)
        before = datetime.now(UTC)
        response = self._post(note="", duration="", expiry_was=was,
                              set_at=entry.token)
        self.assertEqual(response.status_code, 302)
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        window = after.expires_at - before
        self.assertLess(abs(window - timedelta(days=7)), timedelta(minutes=1))
        self.assertEqual(after.note, NOTE)        # a blank note still keeps

    def test_a_changed_field_is_read_as_it_is_typed(self):
        self._workflows()
        entry = self._pin_node(left=timedelta(hours=3))
        was = app_module._expiry_input(entry.expires_at)
        before = datetime.now(UTC)
        response = self._post(note="", duration="3d", expiry_was=was,
                              set_at=entry.token)
        self.assertEqual(response.status_code, 302)
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        window = after.expires_at - before
        self.assertLess(abs(window - timedelta(days=3)), timedelta(minutes=1))

    def test_keeping_needs_the_pin_the_form_was_drawn_from(self):
        # somebody else moved the pin meanwhile: nothing is written, and the
        # refusal's form is filled with the expiry the pin has *now*, so saving
        # the admin's words keeps that one — they never asked to move it
        self._workflows()
        stale = self._pin_node(note="ada wrote this", by="ada",
                               left=timedelta(hours=3))
        fresh = self._pin_node(note="ben wrote this", by="ben",
                               left=timedelta(days=5))
        was = app_module._expiry_input(stale.expires_at)
        now = app_module._expiry_input(fresh.expires_at)
        self.assertNotEqual(was, now)
        response = self._post(note="pan wrote this", duration=was,
                              expiry_was=was, set_at=stale.token)
        self.assertEqual(response.status_code, 200)
        raw = response.get_data(as_text=True)
        self.assertIn("Nothing was saved", raw)
        self.assertEqual(self.tree.maintenance_entry(PATH), fresh)
        mine = self._note_form(parse(raw))
        self.assertEqual(mine.one(tag="textarea").source(), "pan wrote this")
        self.assertEqual(self._expiry_field(mine).attrs.get("value"), now)
        hidden = self._hidden(mine)
        self.assertEqual((hidden["expiry_was"], hidden["set_at"]),
                         (now, fresh.token))
        # there is no expiry of the admin's own to carry over the stored note
        self.assertNotIn("use my expiry", raw)
        # and saving from there keeps the pin's expiry as it stands
        saved = self._post(note="pan wrote this", duration=now,
                           expiry_was=now, set_at=fresh.token)
        self.assertEqual(saved.status_code, 302)
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        self.assertEqual((after.note, after.expires_at),
                         ("pan wrote this", fresh.expires_at))

    def test_a_typed_expiry_on_a_stale_form_stays_the_admins(self):
        self._workflows()
        stale = self._pin_node(note="ada wrote this", by="ada")
        self._pin_node(note="ben wrote this", by="ben", left=timedelta(days=5))
        was = app_module._expiry_input(stale.expires_at)
        raw = self._post(note="mine", duration="2h", expiry_was=was,
                         set_at=stale.token).get_data(as_text=True)
        self.assertIn("Nothing was saved", raw)
        self.assertEqual(raw.count('name="duration" value="2h"'), 2)
        self.assertIn("Keep the stored note, use my expiry", raw)
        # the refusal's page calls the pin's text what its editor does
        self.assertIn(">The stored note<", raw)
        self.assertIn(">Your note<", raw)
        self.assertIn("Save mine, replacing the stored note", raw)
        self.assertNotIn("the pin keeps this expiry", raw)

    def test_keeping_the_expiry_of_a_pin_that_is_gone_starts_a_new_one(self):
        # there is nothing left to keep, so the field is a new pin's: empty
        self._workflows()
        entry = self._pin_node()
        was = app_module._expiry_input(entry.expires_at)
        self.tree.clear_maintenance(PATH)
        response = self._post(note="mine", duration=was, expiry_was=was,
                              set_at=entry.token)
        self.assertEqual(response.status_code, 200)
        raw = response.get_data(as_text=True)
        self.assertIn("gone — someone cleared it", raw)
        self.assertIsNone(self.tree.maintenance_entry(PATH))
        form = self._note_form(parse(raw))
        self.assertEqual(self._expiry_field(form).attrs.get("value"), "")
        hidden = self._hidden(form)
        self.assertEqual(hidden["set_at"], "")
        self.assertNotIn("expiry_was", hidden)

    def test_a_refused_expiry_still_knows_what_the_field_was_filled_with(self):
        # nothing about the stored pin moved, so the token and the filled value
        # both come back; typing the filled value again would keep it
        self._workflows()
        entry = self._pin_node()
        was = app_module._expiry_input(entry.expires_at)
        raw = self._post(note="mine", duration="32", expiry_was=was,
                         set_at=entry.token).get_data(as_text=True)
        self.assertIn("is not a duration or expiry", raw)
        form = self._note_form(parse(raw))
        self.assertEqual(self._expiry_field(form).attrs.get("value"), "32")
        hidden = self._hidden(form)
        self.assertEqual((hidden["expiry_was"], hidden["set_at"]),
                         (was, entry.token))
        # the sentence under the field is true only of a field as it was filled
        self.assertNotIn("the pin keeps this expiry", raw)

    def test_a_form_that_claims_nothing_is_pinned_keeps_nothing(self):
        # the kept value belongs to the pin the token names; without one the
        # field is read like any other
        self._workflows()
        stored = _noon_ahead(40)
        entry = self.tree.set_maintenance(
            PATH, "the first words", expires_at=stored, set_by="ada").current
        assert entry is not None
        was = app_module._expiry_input(entry.expires_at)
        self.tree.clear_maintenance(PATH)
        response = self._post(note="new", duration=was, expiry_was=was,
                              set_at="")
        self.assertEqual(response.status_code, 302)
        after = self.tree.maintenance_entry(PATH)
        assert after is not None
        # read as typed: the second the text names, and no fraction of one
        self.assertEqual(after.expires_at, stored.replace(microsecond=0))
        self.assertEqual(after.created_by, "pan")


class EveryEditorTests(_LeafCase):
    """Decision 5's last sentence: this holds for every editor of a pin — a
    node's, a line's and a card's."""

    def test_a_lines_editor_shows_and_keeps_its_expiry(self):
        self._workflows()
        expires = (datetime.now(UTC) + timedelta(hours=5)).replace(microsecond=654321)
        entry = self.tree.set_entry_maintenance(
            PATH, "mobile-build", LINE_NOTE, expires_at=expires,
            set_by="anna").current
        assert entry is not None
        was = app_module._expiry_input(entry.expires_at)
        block = self._stated(self._page(), "line")[0]
        form = block.one("rule-block__edit").one(tag="form")
        self.assertEqual(self._expiry_field(form).attrs.get("value"), was)
        self.assertEqual(self._hidden(form)["expiry_was"], was)
        response = self._post(slug="mobile-build", note="reworded",
                              duration=was, expiry_was=was, set_at=entry.token)
        self.assertEqual(response.status_code, 302)
        after = self.tree.entry_maintenance(PATH, "mobile-build")
        assert after is not None
        self.assertEqual((after.note, after.expires_at),
                         ("reworded", entry.expires_at))
        # and the node, which has no pin, got none
        self.assertIsNone(self.tree.maintenance_entry(PATH))

    def test_a_lines_kept_expiry_needs_the_lines_own_pin(self):
        self._workflows()
        stale = self._pin_line("mobile-build", note="anna wrote this")
        fresh = self._pin_line("mobile-build", note="ben wrote this", by="ben",
                               left=timedelta(days=4))
        was = app_module._expiry_input(stale.expires_at)
        response = self._post(slug="mobile-build", note="mine", duration=was,
                              expiry_was=was, set_at=stale.token)
        self.assertEqual(response.status_code, 200)
        raw = response.get_data(as_text=True)
        self.assertIn("Nothing was saved", raw)
        self.assertIn('name="slug" value="mobile-build"', raw)
        self.assertEqual(self.tree.entry_maintenance(PATH, "mobile-build"),
                         fresh)
        self.assertIn(
            f'name="expiry_was" value="'
            f'{app_module._expiry_input(fresh.expires_at)}"', raw)

    def test_a_branchs_head_shows_the_expiry_it_keeps(self):
        self.tree.upsert("/system/alpha/disk", StatusCode.OK)
        entry = self.tree.set_maintenance(
            "/system/alpha", "rebuild",
            expires_at=datetime.now(UTC) + timedelta(days=1), set_by="ada").current
        assert entry is not None
        was = app_module._expiry_input(entry.expires_at)
        raw = self._body("/system/alpha")
        self.assertIn(
            f'id="head-maintenance-duration" name="duration" value="{was}"', raw)
        self.assertIn(f'name="expiry_was" value="{was}"', raw)
        self.assertIn("the pin keeps this expiry", raw)

    def test_a_cards_editor_is_filled_with_the_expiry_it_keeps(self):
        # the card a node's page draws at depth 0, its own head, has an editor of its
        # own, drawn with its pin: the field, what the field was filled with and the
        # sentence that says so are the server's — the wall's card has none, its block
        # the link that opens the drawer at it (ADR-0147 decision 7)
        self.tree.upsert("/db/ping", StatusCode.OK)
        entry = self.tree.set_maintenance(
            "/db", "planned", expires_at=datetime.now(UTC) + timedelta(hours=2),
            set_by="ada").current
        assert entry is not None
        was = app_module._expiry_input(entry.expires_at)
        card = parse(self.client.get("/status/db?depth=0").get_data(as_text=True)).one(
            "status-card")
        form = card.one("rule-block__edit").one(tag="form")
        self.assertEqual(self._expiry_field(form).attrs.get("value"), was)
        self.assertEqual(self._hidden(form)["expiry_was"], was)
        self.assertIn("the pin keeps this expiry", form.text())

    def test_an_unpinned_card_carries_no_expiry(self):
        # a pin still to be set is set on the node's Notes tab, which the card's door
        # opens (ADR-0147 decision 1): the wall carries no field, and the tab's is
        # empty, which is the default, with no expiry to keep
        self.tree.upsert("/db/ping", StatusCode.OK)
        self.assertNotIn('name="duration"',
                         self.client.get("/status").get_data(as_text=True))
        tab = parse(self.client.get("/notes/db").get_data(as_text=True))
        (form,) = [form for form in tab.all("ls-kind-form")
                   if form.attrs.get("data-kind") == MAINTENANCE]
        self.assertEqual(self._expiry_field(form).attrs.get("value"), "")
        self.assertNotIn("expiry_was", self._hidden(form))
        self.assertNotIn("the pin keeps this expiry", form.text())

    def test_script_selects_an_untouched_expiry_when_it_takes_focus(self):
        # so one keystroke replaces it; a field somebody changed keeps its caret
        script = self.client.get(
            "/static/js/maintenance-edit.js").get_data(as_text=True)
        self.assertIn('document.addEventListener("focusin"', script)
        # an expiry's kept value by its field, and a silence's deadline's (ADR-0144)
        self.assertIn('duration: "expiry_was"', script)
        self.assertIn('deadline: "deadline_was"', script)
        self.assertIn("namedItem(KEPT[field.name])", script)
        self.assertIn("field.value === was.value", script)
        self.assertIn("field.select()", script)
