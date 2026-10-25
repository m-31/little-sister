"""The page's half of *seen* (ADR-0142): the ringed check on what fails now, its
editors, the block of what a person accepted, `POST /pins/seen` and its refusals, the
rows' chips, *Handled*'s *Accepted*, the Copy document and the envelope's items.

The tree's half is `tests/test_seen.py`'s. What a browser does with the ringed check —
the clone of the page's one editor, the head's own — is
`tests/test_seen_browser.py`'s.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.api import status_envelope
from little_sister.copy_status import (
    Origin,
    TimeStyle,
    format_node_markdown,
    format_tree_markdown,
)
from little_sister.pins import SEEN, Pin
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree, acknowledgeable_parts, parts_digest
from tests.page_tree import Element, parse

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
LATER = timedelta(days=1)


class _Pages(TestCase):
    """A host whose disk fails for itself and a build whose lines are members, under
    one site; signed in as the suite's admin."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.tree.upsert("/site/web/cpu", OK)
        self.tree.upsert("/site/ci/build", ERROR, [
            Entry("test", "test fails", code=ERROR),
            Entry("lint", "lint warns", code=WARN),
            Entry("docs", "docs build", code=OK)], members=True)

    def page(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def tree_of(self, url: str) -> Element:
        return parse(self.page(url))

    def post(self, **form: str) -> str:
        response = self.client.post("/pins/seen", data=form)
        return response.headers.get("Location", "") or response.get_data(as_text=True)

    def seen(self, path: str, slug: str = "", note: str = "looked into") -> Pin:
        write = self.tree.set_acknowledgment(path, slug, SEEN, note, expires_at=None,
                                             set_by="ada")
        assert write.current is not None
        return write.current


class ControlTests(_Pages):
    """The ringed check stands where something fails now, and nowhere else."""

    def test_a_failing_head_carries_it_with_what_it_marks(self):
        page = self.page("/status")
        found = re.search(r'aria-label="mark seen what fails at /site/ci/build" '
                          r'data-ack-parts="([0-9a-f]+)" data-ack-count="(\d+)"', page)
        assert found is not None
        node = self.tree.snapshot("/site/ci/build")
        assert node is not None
        self.assertEqual(found.groups(), (parts_digest(acknowledgeable_parts(node)),
                                          "2"))

    def test_a_green_head_and_one_in_maintenance_carry_none(self):
        self.tree.set_maintenance("/site/web", "rewiring",
                                  expires_at=datetime.now(UTC) + LATER)
        page = self.page("/status")
        self.assertNotIn("mark seen what fails at /site/web/cpu", page)
        self.assertNotIn("mark seen what fails at /site/web\"", page)
        self.assertNotIn("mark seen what fails at /site/web/disk", page)

    def test_a_node_s_page_keeps_an_editor_of_its_own_listing_each(self):
        page = self.tree_of("/status/site/ci/build")
        setter = page.with_id("head-ack-setter")
        self.assertIn("test fails", setter.text())
        self.assertIn("lint warns", setter.text())
        self.assertNotIn("docs build", setter.text())
        self.assertEqual(len(page.all("reason-ack")), 2)

    def test_the_wall_carries_the_one_editor_to_clone(self):
        page = self.page("/status")
        self.assertEqual(page.count('id="ack-editor"'), 1)
        self.assertIn('class="ack-editor__what"', page)


class WriteTests(_Pages):
    """`POST /pins/seen`: one part, a head's parts, an edit, a clear, a refusal."""

    def test_a_line_marked_from_its_page(self):
        where = self.post(path="site/ci/build", slug="test", action="set", set_at="",
                          note="flaky since the runner move", duration="")
        self.assertTrue(where.endswith("?reason=test#pinned-reason"), where)
        pin = self.tree.acknowledgment("/site/ci/build", "test")
        assert pin is not None
        self.assertEqual((pin.kind, pin.status, pin.set_by, pin.expires_at),
                         (SEEN, ERROR, "pan", None))

    def test_a_head_marks_each_failure_beneath_it(self):
        node = self.tree.snapshot("/site")
        assert node is not None
        digest = parts_digest(acknowledgeable_parts(node))
        self.post(path="/site", parts=digest, action="set", set_at="",
                  note="all of it", duration="2h", next="/status")
        nodes, lines = self.tree.acknowledgments()
        self.assertEqual((sorted(nodes), sorted(lines)),
                         (["/site/web/disk"],
                          [("/site/ci/build", "lint"), ("/site/ci/build", "test")]))
        self.assertTrue(all(pin.expires_at is not None
                            for pin in [*nodes.values(), *lines.values()]))

    def test_a_head_whose_failures_changed_marks_nothing_and_lists_them(self):
        node = self.tree.snapshot("/site")
        assert node is not None
        digest = parts_digest(acknowledgeable_parts(node))
        self.tree.upsert("/site/web/cpu", WARN, "load 9")
        answer = self.post(path="/site", parts=digest, action="set", set_at="",
                           note="all of it", duration="")
        self.assertIn("What fails here changed", answer)
        self.assertIn("/site/web/cpu", answer)
        self.assertEqual(self.tree.acknowledgments(), ({}, {}))

    def test_nothing_failing_is_refused_with_why(self):
        answer = self.post(path="/site/web/cpu", action="set", set_at="", note="x",
                           duration="")
        self.assertIn("reads ok now", answer)
        self.assertEqual(self.tree.acknowledgments(), ({}, {}))

    def test_an_end_out_of_bounds_is_refused(self):
        answer = self.post(path="/site/web/disk", action="set", set_at="", note="x",
                           duration="2y")
        self.assertIn("Nothing was saved", answer)
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))

    def test_an_edit_keeps_its_end_and_a_blank_note_keeps_its_note(self):
        self.post(path="/site/web/disk", action="set", set_at="", note="ordered",
                  duration="3d")
        pin = self.tree.acknowledgment("/site/web/disk")
        assert pin is not None and pin.expires_at is not None
        filled = app_module._expiry_input(pin.expires_at)
        self.post(path="/site/web/disk", action="set", set_at=pin.token, note="",
                  duration=filled, expiry_was=filled)
        after = self.tree.acknowledgment("/site/web/disk")
        assert after is not None
        self.assertEqual((after.note, after.expires_at, after.id),
                         ("ordered", pin.expires_at, pin.id))

    def test_a_stale_token_shows_both_texts(self):
        pin = self.seen("/site/web/disk", note="theirs")
        self.tree.set_acknowledgment("/site/web/disk", "", SEEN, "changed",
                                     expires_at=None, set_by="ben",
                                     expected_set_at=pin.token)
        answer = self.post(path="/site/web/disk", action="set", set_at=pin.token,
                           note="mine", duration="")
        self.assertIn("changed this seen", answer)
        self.assertIn("mine", answer)

    def test_a_clear_ends_it_by_hand(self):
        pin = self.seen("/site/ci/build", "test")
        self.post(path="/site/ci/build", slug="test", action="clear",
                  set_at=pin.token)
        self.assertIsNone(self.tree.acknowledgment("/site/ci/build", "test"))

    def test_its_note_enters_the_node_s_notes(self):
        self.post(path="/site/web/disk", action="set", set_at="",
                  note="the disk is on order", duration="")
        notes = app_module.notes_book.of("/site/web/disk")
        self.assertEqual([note.text for note in notes][-1:], ["the disk is on order"])

    def test_a_viewer_may_not(self):
        self.client.get("/logout")
        response = self.client.post("/pins/seen", data={"path": "/site/web/disk"})
        self.assertIn(response.status_code, (302, 401, 403))
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))


class BlockTests(_Pages):
    """What a person accepted, stated where it stands."""

    def test_a_line_s_block_and_its_mark_on_its_page(self):
        self.seen("/site/ci/build", "test", note="flaky, ticket 12")
        page = self.tree_of("/status/site/ci/build")
        blocks = [block for block in page.all("rule-block")
                  if block.attrs.get("data-rule") == SEEN
                  and not block.has("rule-block--new")]
        self.assertEqual(len(blocks), 1)
        self.assertIn("This line is marked seen by ada", blocks[0].text())
        self.assertIn("until it changes", blocks[0].text())
        self.assertIn("flaky, ticket 12", blocks[0].text())
        self.assertEqual(len(page.all("line-ack")), 1)

    def test_a_node_s_block_heads_its_page(self):
        self.seen("/site/web/disk", note="on order")
        page = self.tree_of("/status/site/web/disk")
        blocks = [block for block in page.all("rule-block")
                  if block.attrs.get("data-rule") == SEEN]
        self.assertTrue(blocks)
        self.assertIn("This node is marked seen by ada", blocks[0].text())

    def test_the_wall_states_a_node_s_seen_in_its_box(self):
        self.seen("/site/web/disk", note="on order")
        page = self.tree_of("/status")
        blocks = [block for block in page.all("rule-block")
                  if block.attrs.get("data-rule") == SEEN
                  and not block.has("rule-block--new")]
        self.assertEqual(len(blocks), 1)
        self.assertIn("Seen by ada at", blocks[0].text())
        self.assertIn("until it changes", blocks[0].text())

    def test_the_wall_marks_a_line_seen(self):
        self.seen("/site/ci/build", "test")
        page = self.tree_of("/status")
        marks = page.all("line-ack")
        self.assertEqual(len(marks), 1)
        self.assertEqual(marks[0].attrs.get("title"),
                         "Seen by ada, until it changes")

    def test_the_band_s_pill_counts_each_seen(self):
        self.seen("/site/web/disk")
        self.seen("/site/ci/build", "test")
        page = self.page("/status")
        found = re.search(r'class="maintenance-pill"[^>]*aria-label="([^"]+)"', page)
        assert found is not None
        self.assertEqual(found.group(1), "2 handled: 2 seen")
        self.assertIn("#handled-accepted", page)

    def test_handled_lists_it_under_accepted(self):
        self.seen("/site/web/disk", note="on order")
        self.seen("/site/ci/build", "test")
        page = self.tree_of("/handled")
        section = page.with_id("handled-accepted").parent
        assert section is not None
        self.assertIn("2 seen on 2 nodes", section.text())
        self.assertIn("Its own failure", section.text())
        self.assertIn("test fails", section.text())

    def test_the_events_chips_name_the_act_and_why_it_ended(self):
        self.seen("/site/web/disk")
        self.tree.upsert("/site/web/disk", OK)
        page = self.page("/events")
        chips = re.findall(r'class="event-cause[^"]*">([^<]+)<', page)
        self.assertIn("seen", chips)
        self.assertIn("seen ended · recovered", chips)


class ElsewhereTests(_Pages):
    """The Copy document and the envelope say it as the page does."""

    def test_the_copy_documents_state_it(self):
        self.seen("/site/web/disk", note="on order")
        self.seen("/site/ci/build", "test")
        node = self.tree.snapshot("/site/web/disk")
        assert node is not None
        style = TimeStyle(ZoneInfo("Europe/Berlin"))
        document = format_node_markdown(node, style)
        self.assertIn("☑️ Seen — by ada at error ⛔, until it changes", document)
        whole = format_tree_markdown(self.tree.snapshot(""), style,
                                     Origin("https://example.org/status",
                                            datetime.now(UTC)))
        self.assertIn("☑️ Seen — by ada", whole)

    def test_the_envelope_lists_it_with_what_it_is_bound_to(self):
        pin = self.seen("/site/ci/build", "test")
        node = self.tree.snapshot("/site/ci/build")
        assert node is not None
        envelope = status_envelope(node)
        (line,) = [item for item in envelope["status"]["entries"]["items"]
                   if item["slug"] == "test"]
        (item,) = line["handled"]
        self.assertEqual((item["id"], item["kind"], item["source"], item["status"],
                          item["occurrence"], item["expires_at"], item["counts_as"]),
                         (pin.id, SEEN, "person", "ERROR", None, None,
                          {"WARN": "OK", "ERROR": "OK"}))
        self.assertEqual(line["contribution"], {"code": "OK", "by": SEEN,
                                                "rule": pin.id})
