"""A node whose lines are all silenced still counts the nodes beneath it (ADR-0124),
read against the record's sentences.

The estate is `tests/test_one_status.py`'s: one check that reads an account's
pipelines, an aspect whose one line is its scope, coded `OK`, and beneath it a node for
every pipeline, named by the run, one of which fails from the second run on. Here the
aspect's one line is pinned after the two runs — the shape a pin set on a leaf's page
comes to once the leaf has nodes beneath it — and what says the aspect's status is
read: the tree, the head of its page, its box on the page above, its Time card, its
Copy document and the API. A pin on the node itself still cancels what is beneath it,
and that is read here too; a check's own word for its node, and a leaf, are read on
the tree in `tests/test_tree.py`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import CAUSE_LINE_PIN_SET, StatusSnapshot
from tests.page_tree import Element
from tests.test_one_status import (
    ACCOUNT,
    ASPECT,
    FAILS,
    INSTANT,
    JSON,
    PIPELINES,
    _branch,
    _color,
    _drawn,
    _Estate,
    _word,
)

#: What the aspect's Copy document says it shows, and where that comes from.
SHOWN_AS = ("- **Shown as:** error ⛔ — rolled up from the 3 nodes beneath it. Every "
            "line of its own is silenced.")


def _beside(box: Element) -> list[str]:
    """What a card, a box or a head says beside its status word in the line that
    names it — the reading a *maintenance* stands over, a counter's wait."""
    return [" ".join(element.text().split()) for element in box.first().walk()
            if element.has("status-reported")]


class _Silenced(_Estate):
    """The estate after two runs, the aspect's one line pinned."""

    def setUp(self) -> None:
        super().setUp()
        self.far = datetime.now(UTC) + timedelta(days=1)
        written = self.tree.set_entry_maintenance(
            ASPECT, "scope", "a region we know about", expires_at=self.far,
            set_by="pan")
        self.assertTrue(written.applied)

    def _snap(self, path: str) -> StatusSnapshot:
        snap = self.tree.snapshot(path)
        assert snap is not None
        return snap


class TheNodesBeneathStillCountTests(_Silenced):
    """Its own part counts nothing and cancels nothing; the nodes beneath it count
    as they would without it (decision 1)."""

    def test_it_shows_what_the_nodes_beneath_it_roll_up_to(self) -> None:
        snap = self._snap(ASPECT)
        self.assertEqual((snap.own_code, snap.code, snap.reported_code),
                         (StatusCode.MAINTENANCE, StatusCode.ERROR, StatusCode.OK))
        self.assertTrue(snap.counts_beneath)
        self.assertTrue(snap.lines_silenced)
        self.assertTrue(snap.derived)

    def test_the_nodes_above_it_count_the_failure(self) -> None:
        for path in (ACCOUNT, "/cloud/aws"):
            with self.subTest(path=path):
                self.assertIs(self._snap(path).code, StatusCode.ERROR)

    def test_over_nodes_that_are_all_well_it_shows_ok(self) -> None:
        self.check.mended = True
        app_module.engine.run_once()
        snap = self._snap(ASPECT)
        self.assertEqual((snap.own_code, snap.code),
                         (StatusCode.MAINTENANCE, StatusCode.OK))
        self.assertTrue(snap.derived)

    def test_over_nodes_that_are_all_silenced_it_shows_maintenance(self) -> None:
        # nothing beneath it counts either, which is when the whole node reads
        # `MAINTENANCE` (ADR-0039 rule 5)
        for name in PIPELINES:
            self.tree.set_maintenance(f"{ASPECT}/{name}", "planned",
                                      expires_at=self.far, set_by="pan")
        snap = self._snap(ASPECT)
        self.assertEqual((snap.own_code, snap.code),
                         (StatusCode.MAINTENANCE, StatusCode.MAINTENANCE))
        self.assertFalse(snap.derived)
        self.assertIs(self._snap(ACCOUNT).code, StatusCode.OK)

    def test_a_pin_on_the_node_still_cancels_what_is_beneath_it(self) -> None:
        self.tree.set_maintenance(ASPECT, "planned", expires_at=self.far, set_by="pan")
        snap = self._snap(ASPECT)
        self.assertIs(snap.code, StatusCode.MAINTENANCE)
        self.assertFalse(snap.counts_beneath)
        self.assertFalse(snap.lines_silenced)
        self.assertIs(self._snap(ACCOUNT).code, StatusCode.OK)

    def test_a_leaf_whose_lines_are_all_pinned_still_shows_maintenance(self) -> None:
        leaf = f"{ASPECT}/{FAILS}"
        self.tree.set_entry_maintenance(leaf, "pipeline", "known", expires_at=self.far,
                                        set_by="pan")
        snap = self._snap(leaf)
        self.assertEqual((snap.own_code, snap.code),
                         (StatusCode.MAINTENANCE, StatusCode.MAINTENANCE))
        self.assertFalse(snap.counts_beneath)
        self.assertFalse(snap.derived)
        # and the aspect above counts the two pipelines that are left
        self.assertIs(self._snap(ASPECT).code, StatusCode.OK)

    def test_the_pin_is_a_row_of_the_node_alone(self) -> None:
        # it changed what the aspect shows of its own; nothing above it wrote one
        rows = [(event.path, event.old, event.new)
                for event in self.tree.recent_events()
                if event.cause == CAUSE_LINE_PIN_SET]
        self.assertEqual(rows, [(ASPECT, StatusCode.OK, StatusCode.MAINTENANCE)])


class WhatItSaysTests(_Silenced):
    """Every surface says what the node rolls up to; the ones that say what the node
    is of its own say that its lines are silenced (decisions 2 and 3)."""

    def test_its_head_is_pale_and_says_what_it_rolls_up_to(self) -> None:
        for query in ("depth=1", "depth=2", "depth=1&fragment=1"):
            with self.subTest(query=query):
                head = self._head(ASPECT, query)
                self.assertEqual((_color(head), _word(head)), ("error", "error"))
                self.assertTrue(head.has("dim"))
                self.assertEqual(_beside(head), [])

    def test_its_box_on_the_pages_above_says_it(self) -> None:
        # pale where the nodes beneath it are drawn with it, as any card is
        # (ADR-0123 decision 2) — and the tree draws them with it at every depth,
        # open or closed (ADR-0127 decision 1); a `depth=` closes the box, but the
        # failure beneath it opens its way within its card's budget (ADR-0128), so
        # the box stands open where the depth closed it
        for url, closed in ((f"/status/{_branch(ACCOUNT)}?depth=2", False),
                            (f"/status/{_branch(ACCOUNT)}?depth=1", True),
                            ("/status/cloud/aws?depth=2", True)):
            with self.subTest(url=url):
                page = self._page(url)
                box = _drawn(page, ASPECT)
                self.assertEqual((_color(box), _word(box)), ("error", "error"))
                self.assertTrue(box.has("dim"))
                self.assertEqual(_beside(box), [])
                node = next(node for node in page.all("tree-node")
                            if node.attrs.get("data-node") == ASPECT)
                self.assertEqual(node.attrs.get("data-state"), "open")
                self.assertEqual("data-budget" in node.attrs, closed)

    def test_its_time_card_says_where_its_status_comes_from(self) -> None:
        # the node beneath it that makes it so, with that node's own *since*
        # (ADR-0123 decision 3)
        card = self._time_card(ASPECT)
        self.assertEqual(card[0], f"Status error, from {FAILS} beneath it, "
                                  f"{self._period_said(f'{ASPECT}/{FAILS}')}")
        self.assertRegex(card[1],
                         rf"^Its own status maintenance since (before )?{INSTANT}$")

    def test_its_copy_document_says_where_what_it_shows_comes_from(self) -> None:
        lines = self._copy(ASPECT)
        self.assertIn(SHOWN_AS, lines)
        own = [line for line in lines if line.startswith("- **Its own status")]
        self.assertEqual(len(own), 1, lines)
        self.assertRegex(
            own[0], rf"^- \*\*Its own status maintenance\*\* since (before )?{INSTANT}")

    def test_the_api_says_it_and_names_the_two_beside_it(self) -> None:
        answer = self.client.get(f"/status/{_branch(ASPECT)}", headers=JSON)
        self.assertEqual(answer.status_code, 200)
        status = answer.get_json()["status"]
        self.assertEqual(
            {key: status[key] for key in ("code", "own", "reported")},
            {"code": "ERROR", "own": "MAINTENANCE", "reported": "OK"})

    def test_a_pin_on_the_node_says_maintenance_and_what_it_stands_over(self) -> None:
        self.tree.set_maintenance(ASPECT, "planned", expires_at=self.far, set_by="pan")
        head = self._head(ASPECT)
        self.assertEqual((_color(head), _word(head)), ("maintenance", "maintenance"))
        self.assertEqual(_beside(head), ["· ok"])
        self.assertRegex(self._time_card(ASPECT)[0],
                         rf"^Status maintenance since (before )?{INSTANT}$")
