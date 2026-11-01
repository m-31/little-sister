"""What stands on a node not reported now.

A node its check no longer reports — one its parent left out of children it said were
complete (ADR-0109) — or has not written since the start keeps what stands on it, held
against its path and holding nothing until a node is reported there again (ADR-0109
decision 4). Time decides what stands, and whether its part is reported now does not:
so the snapshot carries such a node beside the nearest node above it that stands and
never among that node's children, ``StatusSnapshot.nodes_not_reported``, joined once
for every surface (ADR-0080 decision 1), as it carries a line not reported now. The one
function behind a door and a *Notes* tab holds it (ADR-0147 decision 2): that node's
door counts it and its tab lists it, a closed chip's ◇ and the band's pill count it,
*Handled* reads it from the snapshot, a branch's *why* card and its Copy document say
it, *not reported now*, and the envelope gives it beside the node's children,
``nodes_not_reported`` (ADR-0141 decision 3).
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
from little_sister.status import StatusCode
from little_sister.tree import (
    StatusSnapshot,
    StatusTree,
    door_counts,
    handled_beneath,
    handled_parts,
)
from tests.page_tree import Element, parse
from tests.test_pruning import EU, EXPORT, IMPORT, JOBS, US, _grown, _pin

ERROR, OK, UNDEFINED = StatusCode.ERROR, StatusCode.OK, StatusCode.UNDEFINED
TOKEN = "secret-token"
SOON = timedelta(hours=1)
#: A path nothing has ever written, whose whole branch is gone.
RETIRED = "/retired/runner"


def said(element: Element) -> str:
    return " ".join(element.text().split())


def snapshot(tree: StatusTree, path: str) -> StatusSnapshot:
    found = tree.snapshot(path)
    assert found is not None, path
    return found


class _Gone(TestCase):
    """The jobs' branch as its runs left it — a container that declares nothing, a job
    that passes, and one that fails above two regions — and what a person sets on
    it."""

    def setUp(self) -> None:
        self.tree = _grown(StatusTree())

    def line_pin(self, path: str = EXPORT, slug: str = "newest") -> Pin:
        write = self.tree.set_entry_maintenance(
            path, slug, "the step is rewritten", set_by="anna",
            expires_at=datetime.now(UTC) + SOON)
        assert write.current is not None
        return write.current

    def silence(self, path: str) -> Pin:
        write = self.tree.set_acknowledgment(
            path, "", SILENCED, "it flaps", set_by="ada",
            expires_at=datetime.now(UTC) + timedelta(days=7), level=OK)
        assert write.current is not None, write.problem
        return write.current

    def remove_export(self) -> None:
        """A run of the jobs' check that says its children are complete and returns
        the import alone: the export goes, and its regions with it."""
        self.tree.prune(JOBS, {"import"})

    def node(self, path: str) -> StatusSnapshot:
        return snapshot(self.tree, path)


class SnapshotTests(_Gone):
    """The snapshot carries it beside the nearest node that stands, and never among
    that node's children."""

    def test_it_stands_beside_the_nearest_node_that_stands(self) -> None:
        pin = _pin(self.tree, EXPORT)
        self.remove_export()
        jobs = self.node(JOBS)
        self.assertEqual([child.path for child in jobs.children], [IMPORT])
        self.assertEqual([(gone.path, gone.maintenance_entry, gone.acknowledgment,
                           gone.not_reported) for gone in jobs.nodes_not_reported],
                         [(EXPORT, pin, None, ())])
        # and beside no other node: not the ones above, not the one beside it
        for path in ("/", "/ci", IMPORT):
            with self.subTest(path=path):
                self.assertEqual(self.node(path).nodes_not_reported, ())

    def test_what_stands_on_its_lines_goes_with_it(self) -> None:
        pin = self.line_pin()
        self.remove_export()
        (gone,) = self.node(JOBS).nodes_not_reported
        self.assertEqual(gone.path, EXPORT)
        self.assertIsNone(gone.maintenance_entry)
        self.assertEqual([(line.slug, line.text, line.maintenance)
                          for line in gone.not_reported], [("newest", "", pin)])

    def test_one_beneath_a_node_that_is_gone_too_stands_beside_the_one_that_stands(
            self) -> None:
        pin = _pin(self.tree, EU)
        self.remove_export()
        self.assertEqual([(gone.path, gone.maintenance_entry)
                          for gone in self.node(JOBS).nodes_not_reported],
                         [(EU, pin)])

    def test_a_node_whose_whole_branch_is_gone_stands_beside_the_root(self) -> None:
        pin = _pin(self.tree, RETIRED)
        self.assertEqual([(gone.path, gone.maintenance_entry)
                          for gone in self.node("/").nodes_not_reported],
                         [(RETIRED, pin)])

    def test_several_stand_in_the_order_what_stands_on_them_was_set(self) -> None:
        _pin(self.tree, US)
        _pin(self.tree, EXPORT)
        self.remove_export()
        self.assertEqual([gone.path for gone in self.node(JOBS).nodes_not_reported],
                         [US, EXPORT])

    def test_a_silence_stands_on_it(self) -> None:
        silence = self.silence(US)
        self.remove_export()
        (gone,) = self.node(JOBS).nodes_not_reported
        self.assertEqual((gone.path, gone.maintenance_entry, gone.acknowledgment),
                         (US, None, silence))

    def test_a_node_reported_again_is_a_node_once_more(self) -> None:
        pin = _pin(self.tree, EXPORT)
        self.remove_export()
        self.tree.upsert(EXPORT, ERROR, "run 5 failed")
        self.assertEqual(self.node(JOBS).nodes_not_reported, ())
        self.assertIs(self.node(EXPORT).maintenance_entry, pin)

    def test_one_not_written_since_a_start_stands_beside_the_nearest_node_above(
            self) -> None:
        # a start leaves every node for its next run to write: the pins come back
        # first, held against their paths, and the run writes the nodes after them
        held = _pin(self.tree, EXPORT)
        started = StatusTree()
        started.restore_maintenance({EXPORT: held})
        self.assertEqual([gone.path for gone
                          in snapshot(started, "/").nodes_not_reported], [EXPORT])
        started.upsert(JOBS, UNDEFINED, "watches two jobs")
        started.upsert(IMPORT, OK, "run 7 succeeded")
        self.assertEqual(snapshot(started, "/").nodes_not_reported, ())
        self.assertEqual([gone.path for gone
                          in snapshot(started, JOBS).nodes_not_reported], [EXPORT])
        started.upsert(EXPORT, ERROR, "run 3 failed")
        self.assertEqual(snapshot(started, JOBS).nodes_not_reported, ())
        self.assertIs(snapshot(started, EXPORT).maintenance_entry, held)


class PartsTests(_Gone):
    """The one function holds it, and every count of what is handled counts it."""

    def setUp(self) -> None:
        super().setUp()
        _pin(self.tree, EXPORT)
        self.line_pin()
        self.remove_export()

    def test_each_part_on_it_says_it_is_gone_and_reads_nothing(self) -> None:
        parts = handled_parts(self.node(JOBS))
        self.assertEqual([(part.path, part.slug, part.job) for part in parts],
                         [(EXPORT, "", "node"), (EXPORT, "newest", "line")])
        for part in parts:
            (rule,) = part.rules
            self.assertEqual((rule.name, rule.slug, rule.line, rule.reads, rule.gone),
                             ("export", part.slug, "", None, True))

    def test_its_door_counts_them_and_so_does_every_door_above(self) -> None:
        doors = door_counts(self.node("/"))
        for path in (JOBS, "/ci", "/"):
            with self.subTest(path=path):
                self.assertEqual(doors[path].by_job, {"node": 1, "line": 1})

    def test_a_closed_chip_counts_it_as_a_branch_its_lines_pins_with_its_own(
            self) -> None:
        for path in (JOBS, "/ci"):
            with self.subTest(path=path):
                self.assertEqual(handled_beneath(self.node(path)), {"node": 1})


class CountsTests(_Gone):
    """A node not reported now with no pin of its own, and one silenced."""

    def test_a_closed_chip_counts_its_lines_pins_as_lines(self) -> None:
        self.line_pin()
        self.remove_export()
        self.assertEqual(handled_beneath(self.node("/ci")), {"line": 1})

    def test_a_silence_on_it_is_counted_by_its_kind(self) -> None:
        self.silence(US)
        self.remove_export()
        self.assertEqual(handled_beneath(self.node("/ci")), {SILENCED: 1})
        self.assertEqual(door_counts(self.node("/"))[JOBS].by_job, {SILENCED: 1})


class _Pages(_Gone):
    """The branch's pages, read by the suite's admin."""

    def setUp(self) -> None:
        super().setUp()
        app_module.app.config["TESTING"] = True
        saved = (app_module.status_tree, app_module.engine, app_module.api_tokens)
        self.addCleanup(self._restore, saved)
        app_module.status_tree = self.tree
        app_module.engine = None
        app_module.notes_book.forget()
        self.addCleanup(app_module.notes_book.forget)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    @staticmethod
    def _restore(saved: tuple[object, object, object]) -> None:
        (app_module.status_tree, app_module.engine,  # type: ignore[assignment]
         app_module.api_tokens) = saved

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))


class SurfacesTests(_Pages):
    """Every surface that says what is handled says it, from the one snapshot."""

    def setUp(self) -> None:
        super().setUp()
        _pin(self.tree, EXPORT)
        self.line_pin()
        self.remove_export()

    def test_the_tab_beside_it_lists_it_under_its_door_s_number(self) -> None:
        stands = self.page(f"/notes{JOBS}").one("ls-tab__stands")
        self.assertEqual(said(stands.one("ls-tab__handled")), "2 handled")
        rows = [said(row) for row in stands.one("ls-tab__beneath").all(tag="li")]
        self.assertEqual(len(rows), 2, rows)
        self.assertTrue(rows[0].startswith("export not reported now · by lex until"),
                        rows)
        self.assertTrue(rows[1].startswith(
            "a line of export not reported now · by anna until"), rows)

    def test_the_door_on_the_wall_is_lit_with_them(self) -> None:
        doors = [link.attrs.get("title") for link in self.page("/status").walk()
                 if link.attrs.get("href") == f"/notes{JOBS}"
                 and link.attrs.get("data-control") == "door"]
        self.assertIn("Handle it — 2 handled: 1 node in maintenance, 1 line in "
                      "maintenance", doors)

    def test_the_pill_counts_them_and_its_row_says_the_node_is_not_reported_now(
            self) -> None:
        pill = self.page("/status").one("maintenance-pill")
        self.assertEqual(pill.attrs.get("title"),
                         "2 handled: 1 node in maintenance, 1 line in maintenance")
        source = self.client.get("/status").get_data(as_text=True)
        row = re.search(r'<li class="maintenance-pop__item">.*?</li>', source)
        assert row is not None
        item = parse(row.group(0))
        self.assertEqual(said(item.one("maintenance-pop__path")), EXPORT)
        self.assertEqual(said(item.one("maintenance-pop__lines")), "not reported now")

    def test_a_branch_s_why_card_and_its_copy_document_say_them(self) -> None:
        card = self.page("/status/ci").with_id("why")
        # without the comma it is the node that is not reported now, and a line of
        # it with it — where *a line of …, not reported now* is a line of a node
        # that stands
        self.assertIn("jobs/export not reported now · by lex until", said(card))
        self.assertIn("a line of jobs/export not reported now · by anna until",
                      said(card))
        document = format_node_markdown(self.node("/ci"),
                                        TimeStyle(ZoneInfo("Europe/Berlin")))
        self.assertIn("jobs/export not reported now — by lex, until", document)
        self.assertIn("a line of jobs/export not reported now — by anna, until",
                      document)

    def test_the_page_of_its_path_lists_its_pins(self) -> None:
        response = self.client.get(f"/status{EXPORT}")
        self.assertEqual(response.status_code, 404)
        blocks = parse(response.get_data(as_text=True)).all("rule-block")
        self.assertEqual(len(blocks), 2)

    def test_the_envelope_gives_them_beside_the_children(self) -> None:
        app_module.api_tokens = {"tester": TOKEN}
        response = self.client.get(f"/status{JOBS}", headers={
            "Accept": "application/json", "Authorization": f"Bearer {TOKEN}"})
        status = response.get_json()["status"]
        self.assertEqual([child["path"] for child in status["children"]], [IMPORT])
        (gone,) = status["nodes_not_reported"]
        self.assertEqual(gone["path"], EXPORT)
        self.assertEqual([(each["kind"], each["set_by"]) for each in gone["handled"]],
                         [(MAINTENANCE, "lex")])
        self.assertEqual(
            [(line["slug"], [(each["kind"], each["set_by"])
                             for each in line["handled"]])
             for line in gone["not_reported"]],
            [("newest", [(MAINTENANCE, "anna")])])
        # a node it does not stand beside lists none
        self.assertEqual(status["children"][0]["nodes_not_reported"], [])


class HandledTests(_Pages):
    """*Handled* reads what stands on a node not reported now from the snapshot, its
    block and *Clear* where it stood."""

    def test_its_pin_stands_under_its_path_marked_so(self) -> None:
        _pin(self.tree, EXPORT)
        self.remove_export()
        heading = self.page("/handled").with_id("handled-maintenance")
        assert heading.parent is not None
        (section,) = heading.parent.all("pin-node--suspended")
        self.assertEqual(said(section.one("pin-node__path")), EXPORT)

    def test_a_silence_on_it_stands_under_silenced_with_its_block_and_clear(
            self) -> None:
        silence = self.silence(US)
        self.remove_export()
        heading = self.page("/handled").with_id("handled-silenced")
        assert heading.parent is not None
        section = heading.parent
        self.assertIn("1 silenced on 1 node", said(section))
        (block,) = section.all("rule-block")
        fields = {field.attrs["name"]: field.attrs.get("value", "")
                  for field in block.one("rule-block__clear").all(tag="input")
                  if field.attrs.get("type") == "hidden"}
        # a node's own block names no line
        self.assertEqual((fields["path"], fields.get("slug", ""), fields["set_at"]),
                         (US, "", silence.token))
