"""A handled part keeps its true color, and every surface says by what (ADR-0135).

What the record adds on the rules built today, read off the pages: a closed chip's
ringed diamond and its number where a rule handles something its counts do not show
(decision 6), the band's pill in the same short form (decision 6), a branch's *why*
card after Time and what its Copy document writes of it (decision 7), and the note's
card on the wall's page (decision 3). The block's own form on the wall is
`tests/test_wall_pins.py`'s, *Handled* is `tests/test_maintenance_page.py`'s, and the
chip's arithmetic `tests/test_tree.py`'s. What a browser does with the note's mark is
`tests/test_pin_browser.py`'s.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.app import WHY_OPEN
from little_sister.pins import Pin
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, parse

LEFT = timedelta(days=1, hours=23, minutes=30)


class _HandledCase(TestCase):
    """An estate with a host whose disk fails, a database whose primary is pinned on
    its own line, and a lab that is in maintenance with a failing box beneath it."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/site/web/cpu", StatusCode.OK)
        self.tree.upsert("/site/web/disk", StatusCode.ERROR, "disk 97 % full")
        self.tree.upsert("/site/db/pool", StatusCode.ERROR, [
            Entry("primary", "primary unreachable", code=StatusCode.ERROR),
            Entry("replica", "replica in step", code=StatusCode.OK)], members=True)
        self.tree.upsert("/site/lab/box", StatusCode.WARN, "fan is loud")
        self.tree.upsert("/site/lab/rack", StatusCode.OK)

    def _pin_line(self) -> Pin:
        write = self.tree.set_entry_maintenance(
            "/site/db/pool", "primary", "being replaced",
            expires_at=datetime.now(UTC) + LEFT, set_by="ada",
            expected_set_at=None)
        assert write.current is not None
        return write.current

    def _pin_lab(self) -> Pin:
        write = self.tree.set_maintenance(
            "/site/lab", "rewiring", expires_at=datetime.now(UTC) + LEFT,
            set_by="lex")
        assert write.current is not None
        return write.current

    def _page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def _chip(page: Element, path: str) -> Element:
        found = [chip for chip in page.all("tree-chip")
                 if chip.attrs.get("data-path") == path]
        assert len(found) == 1, path
        return found[0]


class ChipTests(_HandledCase):
    """Decision 6: a closed chip's ringed diamond and its number, and its words."""

    def test_a_lines_pin_out_of_sight_is_a_diamond_and_a_number(self):
        self._pin_line()
        chip = self._chip(self._page("/status"), "/site/db")
        handled = chip.one("tree-handled")
        self.assertEqual(handled.text(), "1")
        self.assertTrue(handled.all("handled-mark"))
        self.assertEqual(handled.attrs.get("title"),
                         "1 handled: 1 line in maintenance")
        # the chip's own words say it too, as they say its counts
        self.assertEqual(chip.attrs.get("title"),
                         "1 ok, 1 handled: 1 line in maintenance")
        self.assertEqual(chip.attrs.get("aria-label"),
                         "db: 1 ok, 1 handled: 1 line in maintenance")

    def test_a_pinned_branch_beneath_is_one_node_in_maintenance(self):
        self._pin_lab()
        page = self._page("/status")
        card = [name for name in page.all("status-card__name")
                if name.attrs.get("href") == "/status/site"]
        self.assertEqual(len(card), 1)
        # the box beneath it counts for itself, and the pin that holds it is
        # said beside the counts
        self.assertEqual(card[0].attrs.get("title"),
                         "2 errors, 1 warning, 2 ok, "
                         "1 handled: 1 node in maintenance")

    def test_a_pinned_leaf_is_among_the_counts_and_not_handled_twice(self):
        self.tree.set_maintenance("/site/web/disk", "swapping it",
                                  expires_at=datetime.now(UTC) + LEFT,
                                  set_by="lex")
        chip = self._chip(self._page("/status"), "/site/web")
        self.assertEqual(chip.attrs.get("title"), "1 in maintenance, 1 ok")
        self.assertEqual(chip.all("tree-handled"), [])

    def test_a_pinned_leaf_s_line_pins_are_not_handled_out_of_sight(self):
        # the pool's primary pinned on its own and the pool whole: the pool is ‖
        # among its parent's counts, its line with it
        self._pin_line()
        self.tree.set_maintenance("/site/db/pool", "replacing the primary",
                                  expires_at=datetime.now(UTC) + LEFT,
                                  set_by="lex")
        chip = self._chip(self._page("/status"), "/site/db")
        self.assertEqual(chip.attrs.get("title"), "1 in maintenance")
        self.assertEqual(chip.all("tree-handled"), [])

    def test_nothing_handled_draws_no_diamond(self):
        page = self._page("/status")
        self.assertEqual(page.all("tree-handled"), [])
        self.assertEqual(page.all("tree-rule"), [])


class PillTests(_HandledCase):
    """Decision 6: the band's pill counts the pins that stand, in the chip's short
    form, and leads to *Handled*."""

    def test_the_pill_says_what_is_handled_and_leads_to_handled(self):
        self._pin_line()
        self._pin_lab()
        page = self._page("/status")
        pill = page.one("maintenance-pill")
        self.assertEqual(pill.attrs.get("href"), "/handled")
        self.assertEqual(pill.one("maintenance-pill__count").text(), "2")
        self.assertTrue(pill.text().endswith("handled"))
        self.assertEqual(pill.attrs.get("aria-label"),
                         "2 handled: 1 node in maintenance, 1 line in maintenance")
        self.assertTrue(pill.all(tag="circle"))     # the ringed diamond's dot

    def test_the_rail_leads_to_handled(self):
        page = self._page("/status")
        entries = [link for link in page.all("ls-rail__item")
                   if link.attrs.get("href") == "/handled"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].attrs.get("title"), "Handled")
        self.assertEqual([link for link in page.all("ls-rail__item")
                          if link.attrs.get("href") == "/maintenance"], [])


class WhyTests(_HandledCase):
    """Decision 7: a branch says why it has its color in a card after Time."""

    @staticmethod
    def _why(page: Element) -> Element:
        found = page.all("why-card")
        assert len(found) == 1
        return found[0]

    def test_a_failing_branch_says_what_counts_and_what_is_handled(self):
        self._pin_line()
        self._pin_lab()
        page = self._page("/status/site")
        why = self._why(page)
        self.assertEqual(why.attrs.get("id"), "why")
        self.assertEqual(why.one(tag="h3").text(), "Why error")
        counting, handled = why.all("why-list")
        # what counts: the disk, which fails and passes it up — not the lab's
        # box, which the lab's pin holds, nor the pinned primary
        self.assertEqual([item.all(tag="a")[0].text() for item in counting.children
                          if isinstance(item, Element)], ["web/disk"])
        # what is handled: every rule beneath, with what its part reads
        rows = [item.text() for item in handled.children if isinstance(item, Element)]
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(row.startswith("a line of db/pool — primary unreachable"
                                           ", reads error · by ada until")
                            for row in rows), rows)
        self.assertTrue(any(row.startswith("lab · by lex until") for row in rows),
                        rows)
        self.assertEqual(why.one("why-card__handled").text(), "2 handled beneath it")
        self.assertEqual(why.one("why-card__job").text(), "In maintenance")

    def test_it_stands_right_after_time(self):
        page = self._page("/status/site")
        cards = [card for card in page.all("card")
                 if card.all(tag="h3")]
        titles = [card.one(tag="h3").text() for card in cards]
        self.assertEqual(titles[:2], ["Time", "Why error"])

    def test_an_ok_branch_holding_something_handled_says_why_ok(self):
        self._pin_line()
        self.tree.upsert("/site/web/disk", StatusCode.OK)
        why = self._why(self._page("/status/site/db"))
        self.assertEqual(why.one(tag="h3").text(), "Why ok")
        self.assertEqual(why.all("why-list")[0].all(tag="li")[0].text().split(" · ")[0],
                         "a line of pool — primary unreachable, reads error")

    def test_an_ok_branch_with_nothing_handled_has_none(self):
        self.tree.upsert("/site/web/disk", StatusCode.OK)
        self.tree.upsert("/site/db/pool", StatusCode.OK, "all in step")
        page = self._page("/status/site/web")
        self.assertEqual(page.all("why-card"), [])

    def test_a_leaf_has_none(self):
        self.assertEqual(self._page("/status/site/web/disk").all("why-card"), [])

    def test_what_counts_comes_errors_first(self):
        # the pool's primary fails and is not pinned here: two errors and the lab's
        # box, a warning, which comes last although it has stood the longest
        self.tree.upsert("/site/web/disk", StatusCode.OK)
        self.tree.upsert("/site/web/disk", StatusCode.ERROR, "disk 97 % full")
        self.tree.upsert("/site/db/pool", StatusCode.OK, "all in step")
        self.tree.upsert("/site/db/pool", StatusCode.ERROR, [
            Entry("primary", "primary unreachable", code=StatusCode.ERROR),
            Entry("replica", "replica in step", code=StatusCode.OK)], members=True)
        why = self._why(self._page("/status/site"))
        rows = [item.all(tag="a")[0].text()
                for item in why.all("why-list")[0].all(tag="li")]
        self.assertEqual(rows[-1], "lab/box")
        self.assertEqual(sorted(rows[:2]), ["db/pool", "web/disk"])

    def test_a_long_list_shows_its_first_rows_and_folds_the_rest(self):
        for name in ("a", "b", "c", "d", "e", "f"):
            self.tree.upsert(f"/site/farm/{name}", StatusCode.ERROR, "down")
        why = self._why(self._page("/status/site"))
        counting = why.all("why-list")[0]
        self.assertEqual(len(counting.all(tag="li")), WHY_OPEN)
        folded = why.one("why-more")
        self.assertEqual(folded.one(tag="summary").text(),
                         f"{9 - WHY_OPEN} more")
        # the disk, the pool, the lab's box and the six farm nodes: every part, the
        # folded ones behind the browser's own disclosure
        self.assertEqual(len(folded.all(tag="li")), 9 - WHY_OPEN)
        self.assertIn("What counts, 9 parts:", why.text())

    def test_times_more_links_to_it(self):
        self.tree.upsert("/site/web/cpu", StatusCode.ERROR, "throttled")
        page = self._page("/status/site")
        more = [link for link in page.all(tag="a") if link.attrs.get("href") == "#why"]
        self.assertEqual(len(more), 1)
        self.assertTrue(more[0].text().endswith("more"))


class CopyTests(_HandledCase):
    """Decision 7: a branch's Copy document writes what is handled as its *why*
    card lists it."""

    def _source(self, path: str) -> str:
        return self._page("/copy" + path).with_id("ls-copy-source").source()

    def test_the_document_lists_every_rule_beneath(self):
        line = self._pin_line()
        lab = self._pin_lab()
        style = app_module._copy_style()
        source = self._source("/site")
        self.assertIn(
            "**Handled beneath it** — 2\n\n"
            "- 🛠️ In maintenance\n"
            f"  - a line of db/pool, reads error ⛔ — by ada, until "
            f"{style.at(line.expires_at)}\n"
            "    - primary unreachable\n"
            f"  - lab — by lex, until {style.at(lab.expires_at)}", source)
        # after what needs attention, as the card follows what counts
        self.assertLess(source.index("**Beneath it**"),
                        source.index("**Handled beneath it**"))

    def test_nothing_handled_writes_nothing(self):
        self.assertNotIn("Handled beneath it", self._source("/site"))

    def test_a_branch_in_maintenance_says_it_under_its_pin(self):
        self._pin_line()
        self.tree.set_maintenance("/site", "moving racks",
                                  expires_at=datetime.now(UTC) + LEFT, set_by="lex")
        self.assertNotIn("Handled beneath it", self._source("/site"))


class NoteCardTests(_HandledCase):
    """Decision 3: the note's card stands outside the grid the refresh swaps, and
    its script beside it."""

    def test_the_page_carries_the_card_and_its_script(self):
        body = self.client.get("/status").get_data(as_text=True)
        page = parse(body)
        card = page.one("note-card")
        self.assertEqual(card.attrs.get("role"), "dialog")
        self.assertTrue(card.has("inspect-card"))
        self.assertFalse(card.within(page.one("status-grid")))
        self.assertIn("js/note-card.js", body)
