"""What stands on a line its node does not report now.

A finding that comes and goes takes a pin, or a silence, while it is reported, and what
stands on it holds when it goes — suspended, not deleted (ADR-0036 decision 6,
ADR-0144 decision 5) — until its line comes back or it ends. The snapshot carries such
a line beside the lines its node reports and never among them,
``StatusSnapshot.not_reported``, joined once for every surface (ADR-0080 decision 1):
so the one function behind a door and a *Notes* tab holds it (ADR-0147 decision 2),
the door counts it, the tab lists it under that number, *Handled* states it with its
block and *Clear* for whoever may, *A line not reported now* (ADR-0135 decision 8),
and a *Clear* there ends it; the band's pill and a closed chip count it, a branch's
*why* card and its Copy document say it, and the envelope lists it in
``entries.not_reported`` (ADR-0141 decision 3).
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.copy_status import TimeStyle, format_node_markdown
from little_sister.pins import MAINTENANCE, SILENCED, Pin
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import (
    StatusSnapshot,
    StatusTree,
    door_counts,
    handled_beneath,
    handled_parts,
)
from tests.page_tree import Element, parse

ERROR, OK = StatusCode.ERROR, StatusCode.OK
PATH = "/sec/audit"
FINDINGS = {"f-1": "a bucket is public", "f-2": "a key is older than a year",
            "f-3": "a role trusts every account"}
NOT_REPORTED = "A line not reported now"
TOKEN = "secret-token"


def said(element: Element) -> str:
    return " ".join(element.text().split())


class _Audit(TestCase):
    """An audit whose findings are members, all three reported at first, beneath a
    branch of its own."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.report(*FINDINGS)

    def report(self, *slugs: str) -> None:
        """A run of the audit that reports ``slugs`` and none of the others."""
        self.tree.upsert(PATH, ERROR if slugs else OK, [
            Entry(slug, FINDINGS[slug], code=ERROR) for slug in slugs], members=True)

    def pin(self, slug: str) -> Pin:
        write = self.tree.set_entry_maintenance(
            PATH, slug, "the vendor fixes it", set_by="anna",
            expires_at=datetime.now(UTC) + timedelta(days=2))
        assert write.current is not None
        return write.current

    def silence(self, slug: str) -> Pin:
        write = self.tree.set_acknowledgment(
            PATH, slug, SILENCED, "it comes and goes", set_by="ada",
            expires_at=datetime.now(UTC) + timedelta(days=7), level=OK)
        assert write.current is not None, write.problem
        return write.current

    def node(self, path: str = PATH) -> StatusSnapshot:
        found = self.tree.snapshot(path)
        assert found is not None
        return found


class SnapshotTests(_Audit):
    """The snapshot carries them beside the lines and never among them."""

    def test_each_stands_beside_the_lines_in_the_order_it_was_set(self):
        silence = self.silence("f-2")
        pin = self.pin("f-1")
        self.report("f-3")
        node = self.node()
        self.assertEqual([(line.slug, line.text, line.maintenance, line.acknowledgment)
                          for line in node.not_reported],
                         [("f-2", "", None, silence), ("f-1", "", pin, None)])
        # never among the lines: the node counts what it reports, and only that
        self.assertEqual([line.slug for line in node.reasons], ["f-3"])
        self.assertIs(node.own_code, ERROR)

    def test_a_line_two_things_stand_on_is_placed_by_the_first_set(self):
        silence = self.silence("f-1")
        self.pin("f-2")
        pin = self.pin("f-1")
        self.report("f-3")
        node = self.node()
        self.assertEqual([line.slug for line in node.not_reported], ["f-1", "f-2"])
        first = node.not_reported[0]
        self.assertEqual((first.maintenance, first.acknowledgment), (pin, silence))

    def test_a_node_whose_lines_are_no_members_holds_every_one_so(self):
        pin = self.pin("f-1")
        self.tree.upsert(PATH, ERROR, "check error: the audit could not be read")
        node = self.node()
        self.assertFalse(node.members)
        self.assertEqual([(line.slug, line.maintenance) for line in node.not_reported],
                         [("f-1", pin)])

    def test_a_line_reported_again_is_a_line_once_more(self):
        pin = self.pin("f-1")
        self.report("f-3")
        self.report("f-1", "f-3")
        node = self.node()
        self.assertEqual(node.not_reported, ())
        self.assertIs(node.reasons[0].maintenance, pin)


class PartsTests(_Audit):
    """The one function holds them, and every count of what is handled counts them."""

    def setUp(self) -> None:
        super().setUp()
        self.pin("f-1")
        self.silence("f-2")
        self.report("f-3")

    def test_each_is_a_part_of_its_own_reading_nothing(self):
        parts = handled_parts(self.node())
        self.assertEqual([(part.slug, part.job) for part in parts],
                         [("f-1", "line"), ("f-2", SILENCED)])
        for part in parts:
            (rule,) = part.rules
            self.assertEqual((rule.slug, rule.line, rule.reads), (part.slug, "", None))

    def test_its_door_counts_them_and_so_does_every_door_above(self):
        doors = door_counts(self.node("/"))
        for path in (PATH, "/sec"):
            with self.subTest(path=path):
                self.assertEqual(doors[path].by_job, {"line": 1, SILENCED: 1})

    def test_a_closed_chip_counts_them_its_own_leaf_s_among_them(self):
        # no chip's counts show a line its node does not report: beneath a branch
        # and on the leaf's own chip alike
        for path in (PATH, "/sec"):
            with self.subTest(path=path):
                self.assertEqual(handled_beneath(self.node(path)),
                                 {"line": 1, SILENCED: 1})

    def test_a_leaf_in_maintenance_as_a_whole_holds_its_line_s_pin_with_it(self):
        self.tree.set_maintenance(PATH, "the audit is being rebuilt", set_by="anna",
                                  expires_at=datetime.now(UTC) + timedelta(days=1))
        self.assertNotIn("line", handled_beneath(self.node("/sec")))


class _Pages(_Audit):
    """The audit's pages, read by the suite's admin."""

    def setUp(self) -> None:
        super().setUp()
        app_module.app.config["TESTING"] = True
        app_module.status_tree = self.tree
        app_module.notes_book.forget()
        self.addCleanup(app_module.notes_book.forget)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def job(self, job: str) -> Element:
        """*Handled*'s section of one job, by its heading's id."""
        heading = self.page("/handled").with_id(job)
        assert heading.parent is not None
        return heading.parent

    def jobs(self) -> list[str]:
        """The ids of the sections *Handled* has."""
        return [found.attrs["id"] for found in self.page("/handled").walk()
                if found.attrs.get("id", "").startswith("handled-")]

    @staticmethod
    def hidden(form: Element) -> dict[str, str]:
        return {field.attrs["name"]: field.attrs.get("value", "")
                for field in form.all(tag="input")
                if field.attrs.get("type") == "hidden"}


class HandledTests(_Pages):
    """*Handled* lists a line's maintenance pin while its node does not report the
    line, with its block and *Clear*, as the tab does — and the *Clear* ends it."""

    def test_it_stands_in_maintenance_with_its_block_and_clear(self):
        pin = self.pin("f-1")
        self.report("f-2", "f-3")
        section = self.job("handled-maintenance")
        self.assertIn("1 pin on 1 node", said(section))
        (block,) = section.all("rule-block")
        what = block.one("rule-block__what")
        self.assertTrue(said(what).startswith(
            f"{NOT_REPORTED} is in maintenance by anna until"), said(what))
        # the slug is no text and the line no link: it is not on its node's page now
        self.assertNotIn("f-1", said(block))
        self.assertEqual(what.all(tag="a"), [])
        self.assertEqual(self.hidden(block.one("rule-block__clear")), {
            "path": PATH, "slug": "f-1", "action": "clear", "set_at": pin.token,
            "next": f"/handled?node={PATH}#pinned-node"})

    def test_its_clear_ends_it(self):
        self.pin("f-1")
        self.report("f-2", "f-3")
        (block,) = self.job("handled-maintenance").all("rule-block")
        response = self.client.post("/pins/maintenance",
                                    data=self.hidden(block.one("rule-block__clear")))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.tree.entry_maintenance(PATH, "f-1"))
        self.assertNotIn("handled-maintenance", self.jobs())

    def test_it_stands_after_the_lines_the_node_reports(self):
        self.pin("f-1")
        self.pin("f-2")
        self.report("f-2", "f-3")
        blocks = [said(block.one("rule-block__what"))
                  for block in self.job("handled-maintenance").all("rule-block")]
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].startswith(f"{FINDINGS['f-2']} — this line is in"),
                        blocks)
        self.assertTrue(blocks[1].startswith(f"{NOT_REPORTED} is in"), blocks)

    def test_a_silence_on_one_stands_under_silenced_with_its_block_and_clear(self):
        silence = self.silence("f-2")
        self.report("f-1", "f-3")
        section = self.job("handled-silenced")
        self.assertIn("1 silenced on 1 node", said(section))
        (block,) = section.all("rule-block")
        what = block.one("rule-block__what")
        self.assertTrue(said(what).startswith(f"{NOT_REPORTED} is silenced by ada"),
                        said(what))
        self.assertNotIn("f-2", said(block))
        self.assertEqual(what.all(tag="a"), [])
        self.assertEqual(self.hidden(block.one("rule-block__clear")), {
            "path": PATH, "slug": "f-2", "action": "clear", "set_at": silence.token,
            "next": f"/handled?node={PATH}#pinned-node"})

    def test_a_silence_s_clear_ends_it(self):
        self.silence("f-2")
        self.report("f-1", "f-3")
        (block,) = self.job("handled-silenced").all("rule-block")
        response = self.client.post("/pins/silenced",
                                    data=self.hidden(block.one("rule-block__clear")))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.tree.acknowledgment(PATH, "f-2"))
        self.assertNotIn("handled-silenced", self.jobs())


class SurfacesTests(_Pages):
    """Every other surface that says what is handled says them, from the one
    snapshot."""

    def setUp(self) -> None:
        super().setUp()
        self.pin("f-1")
        self.silence("f-2")
        self.report("f-3")

    def test_the_tab_lists_them_under_its_door_s_number(self):
        stands = self.page(f"/notes{PATH}").one("ls-tab__stands")
        self.assertEqual(said(stands.one("ls-tab__handled")), "2 handled")
        blocks = [said(block.one("rule-block__what")) for block in
                  stands.all("rule-block")]
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(block.startswith(NOT_REPORTED) for block in blocks),
                        blocks)

    def test_a_branch_s_tab_lists_them_beneath_it(self):
        beneath = self.page("/notes/sec").one("ls-tab__beneath")
        rows = [said(row) for row in beneath.all(tag="li")]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.startswith("a line of audit, not reported now")
                            for row in rows), rows)

    def test_the_door_on_the_wall_is_lit_with_them(self):
        doors = [link.attrs.get("title") for link in self.page("/status").walk()
                 if link.attrs.get("href") == f"/notes{PATH}"
                 and link.attrs.get("data-control") == "door"]
        self.assertIn("Handle it — 2 handled: 1 line in maintenance, 1 silenced",
                      doors)

    def test_the_pill_counts_them_and_its_row_says_the_pin_apart(self):
        wall = self.page("/status")
        pill = wall.one("maintenance-pill")
        self.assertEqual(pill.attrs.get("title"),
                         "2 handled: 1 line in maintenance, 1 silenced")
        source = self.client.get("/status").get_data(as_text=True)
        row = re.search(r'<li class="maintenance-pop__item">.*?</li>', source)
        assert row is not None
        lines = parse(row.group(0)).one("maintenance-pop__lines")
        self.assertEqual(said(lines), "1 line not reported now")

    def test_a_row_says_the_lines_it_reports_and_the_one_it_does_not_apart(self):
        self.pin("f-3")
        self.report("f-2", "f-3")
        source = self.client.get("/status").get_data(as_text=True)
        row = re.search(r'<li class="maintenance-pop__item">.*?</li>', source)
        assert row is not None
        self.assertEqual(said(parse(row.group(0)).one("maintenance-pop__lines")),
                         "1 of 2 reasons, 1 line not reported now")

    def test_a_branch_s_why_card_and_its_copy_document_say_them(self):
        card = self.page("/status/sec").with_id("why")
        # the comma keeps it a line's: *a line of audit not reported now* reads as a
        # node that is gone, the one case this must not be taken for
        self.assertIn("a line of audit, not reported now · by anna until", said(card))
        self.assertIn("a line of audit, not reported now · silenced by ada", said(card))
        document = format_node_markdown(self.node("/sec"),
                                        TimeStyle(ZoneInfo("Europe/Berlin")))
        self.assertIn("a line of audit, not reported now — by anna, until", document)
        self.assertIn("a line of audit, not reported now — silenced by ada", document)

    def test_the_envelope_lists_them_beside_the_entries(self):
        app_module.api_tokens = {"tester": TOKEN}
        response = self.client.get(f"/status{PATH}", headers={
            "Accept": "application/json", "Authorization": f"Bearer {TOKEN}"})
        entries = response.get_json()["status"]["entries"]
        self.assertEqual([item["slug"] for item in entries["items"]], ["f-3"])
        self.assertEqual(
            [(away["slug"], [(each["kind"], each["set_by"])
                             for each in away["handled"]])
             for away in entries["not_reported"]],
            [("f-1", [(MAINTENANCE, "anna")]), ("f-2", [(SILENCED, "ada")])])
