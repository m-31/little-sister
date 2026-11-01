"""A card's door, ◇, counts everything handled at and beneath it, and its *Notes* tab
lists it (ADR-0147 decision 2); a branch's *why* card lists what is seen (ADR-0135
decision 7).

The door stands on every open head for every reader, lit wherever something is
handled at or beneath its node — a pin, a part marked seen (ADR-0142), a part a
configured rule changes the count of (ADR-0137) — with the number of parts, each
once, its words saying how many of each; the node's own part among them, and what a
pin of its own holds beneath it. The tab it opens lists the same parts beneath the
node, part by part, in every state. It took the place of the card's diamond, the pip,
and of its list (ADR-0135 decision 6).

What the band's pill lists is `tests/test_web.py`'s and `tests/test_web_pins.py`'s.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.aggregation import RuleSet
from little_sister.pins import SEEN
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, parse
from tests.test_aggregation_tree import CAP, rule

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK


def _said(element: Element) -> str:
    return " ".join(element.text().split())


class _Wall(TestCase):
    """Three cards: `stress`, with a pin and a node seen for itself beneath it;
    `quality`, with seen lines alone — two on one node, one on another; and `aws`,
    with a node a configured rule counts otherwise. Signed in as the suite's admin."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        self.tree.use_aggregation(RuleSet((rule("develop advises", "/aws/develop",
                                                CAP),)))
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        tree = self.tree
        tree.upsert("/stress/aws", ERROR, "no usable AWS credentials")
        tree.upsert("/stress/loadtest", ERROR, "cannot be read")
        tree.upsert("/stress/wiz", OK)
        tree.set_maintenance("/stress/loadtest", "no loadtests here",
                             expires_at=datetime.now(UTC) + timedelta(days=30),
                             set_by="lex")
        self.seen("/stress/aws", note="the profile is on order")
        tree.upsert("/quality/github/pull_requests", ERROR, [
            Entry("pr-1", "web-shop #59: bump pillow", code=ERROR),
            Entry("pr-2", "web-shop #64: bump brotli", code=WARN),
            Entry("pr-3", "web-shop #71: bump ruff", code=WARN)], members=True)
        tree.upsert("/quality/github/actions", ERROR, [
            Entry("run-1", "stress_backup failed", code=ERROR)], members=True)
        for slug in ("pr-1", "pr-2"):
            self.seen("/quality/github/pull_requests", slug)
        self.seen("/quality/github/actions", "run-1", note="a flaky runner")
        tree.upsert("/aws/develop/lambda", ERROR, "timed out")

    def seen(self, path: str, slug: str = "", note: str = "looked into") -> None:
        self.tree.set_acknowledgment(path, slug, SEEN, note, expires_at=None,
                                     set_by="ada")

    def page(self, url: str = "/status") -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def door(page: Element, card: str) -> Element:
        """The door on ``card``'s head."""
        (head,) = [head for head in page.all("status-card__head")
                   if head.attrs.get("data-path") == card]
        (found,) = [link for link in head.all(tag="a")
                    if link.attrs.get("data-control") == "door"]
        return found


class TheDoorTests(_Wall):
    """Lit wherever something is handled at or beneath a card, with how many parts."""

    def test_a_card_with_only_something_seen_beneath_it_is_lit_with_its_parts(self):
        door = self.door(self.page(), "/quality")
        # three lines seen on two nodes: three parts, each its own
        self.assertTrue(door.has("is-lit"))
        self.assertEqual(_said(door.one("door__count")), "3")
        self.assertEqual(door.attrs.get("title"), "Handle it — 3 handled: 3 seen")
        self.assertEqual(door.attrs.get("aria-label"),
                         "handle /quality — 3 handled: 3 seen")
        self.assertEqual(door.attrs.get("href"), "/notes/quality")

    def test_a_card_with_only_a_part_a_rule_counts_otherwise_beneath_it_is_lit(self):
        self.assertEqual(self.door(self.page(), "/aws").attrs.get("title"),
                         "Handle it — 1 handled: 1 by a rule")

    def test_its_jobs_come_in_handled_s_order(self):
        self.assertEqual(self.door(self.page(), "/stress").attrs.get("title"),
                         "Handle it — 2 handled: 1 node in maintenance, 1 seen")

    def test_what_stands_on_the_card_itself_is_counted_too(self):
        self.tree.upsert("/host", ERROR, "the host itself fails")
        self.tree.upsert("/host/disk", OK)
        self.seen("/host")
        self.assertEqual(self.door(self.page(), "/host").attrs.get("title"),
                         "Handle it — 1 handled: 1 seen")

    def test_a_card_in_maintenance_counts_what_stands_beneath_its_pin(self):
        # its pin holds everything beneath it, and what stands there still stands
        self.tree.set_maintenance("/stress", "rewiring",
                                  expires_at=datetime.now(UTC) + timedelta(days=1))
        self.assertEqual(self.door(self.page(), "/stress").attrs.get("title"),
                         "Handle it — 3 handled: 2 nodes in maintenance, 1 seen")

    def test_a_card_with_nothing_handled_beneath_it_is_plain(self):
        self.tree.upsert("/calm/disk", OK)
        door = self.door(self.page(), "/calm")
        self.assertFalse(door.has("is-lit"))
        self.assertEqual(door.all("door__count"), [])
        self.assertEqual(door.attrs.get("title"), "Handle it")

    def test_a_shallow_depth_changes_nothing_a_door_says(self):
        # what a depth closes is still counted: the route counts every door from the
        # tree before anything is left out of what it draws
        self.assertEqual(self.door(self.page("/status?depth=1"), "/quality").attrs,
                         self.door(self.page(), "/quality").attrs)

    def test_a_viewer_reads_the_same_door_in_their_words(self):
        with self.client.session_transaction() as sess:
            sess["admin"] = False
        door = self.door(self.page(), "/quality")
        self.assertEqual(door.attrs.get("title"), "Notes — 3 handled: 3 seen")
        self.assertEqual(door.attrs.get("aria-label"),
                         "the notes of /quality — 3 handled: 3 seen")

    def test_the_tab_it_opens_says_its_count_and_lists_as_many_parts(self):
        page = self.page("/notes/quality")
        # the door's number, in the chip's form, over what stands
        stands = page.one("ls-tab__stands")
        self.assertEqual(_said(stands.one("ls-tab__handled")), "3 handled")
        beneath = page.one("ls-tab__beneath")
        self.assertEqual(beneath.all("why-card__handled"), [])
        self.assertEqual(len(beneath.all(tag="li")), 3)

    def test_the_pip_is_gone(self):
        page = self.page()
        self.assertEqual(page.all("maintenance-pip"), [])
        self.assertEqual([template.attrs.get("data-pop-for")
                          for template in page.all("maintenance-pop-src")],
                         ["__all__"])


class WhyCardTests(_Wall):
    """A branch's *why* card lists what is seen beneath it under *Accepted*, as
    *Handled* and the Copy document do."""

    @staticmethod
    def handled(why: Element) -> list[str]:
        """The rows of what is handled beneath, after what counts."""
        begins = why.one("why-card__handled").order
        return [_said(row) for row in why.all(tag="li") if row.order > begins]

    def test_it_lists_every_part_it_counts(self):
        why = self.page("/status/stress").with_id("why")
        self.assertEqual(_said(why.one("why-card__handled")), "2 handled beneath it")
        self.assertEqual([_said(job) for job in why.all("why-card__job")],
                         ["In maintenance", "Accepted"])
        rows = self.handled(why)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1], "aws, reads error · seen by ada at error · until it "
                                  "changes")

    def test_a_seen_line_is_listed_with_its_line(self):
        why = self.page("/status/quality/github").with_id("why")
        self.assertEqual([_said(job) for job in why.all("why-card__job")],
                         ["Accepted"])
        self.assertEqual(_said(why.one("why-card__handled")), "3 handled beneath it")
        rows = self.handled(why)
        self.assertEqual(len(rows), 3)
        self.assertIn("a line of actions — stress_backup failed, reads error · seen by "
                      "ada at error · until it changes", rows)
