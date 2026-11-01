"""The page's half of *done* (ADR-0146): the Notes tab's *Done*, offered on a failing
line whose failure is an event; `POST /pins/done` and its refusals; a block's editor,
which makes a seen or a silence done and a done another kind; the line that shows ok
with the failure it closed beside it, on the wall and on its page; *Handled*'s
*Accepted*, the band's pill and a chip's ringed diamond; the rows' chips, History and
the Time card; the Copy document, the envelope and the help.

The tree's half is `tests/test_done.py`'s.
"""
from __future__ import annotations

import html
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import identity
from little_sister.copy_status import (
    Origin,
    TimeStyle,
    format_node_markdown,
    format_tree_markdown,
)
from little_sister.notes import NoteBook
from little_sister.notes_tab import NOTE
from little_sister.pins import DONE, MAINTENANCE, SEEN, SILENCED, Pin
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, css_rule, parse

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
BUILD = "/site/ci/build"
TAB = "/notes/site/ci/build"


class _Pages(TestCase):
    """A build whose lines are members — ``test`` a run's, which names its event,
    ``lint`` a failing stretch nothing tells apart, ``docs`` a run's that passed — and
    a host failing by its own reading, under one site; signed in as the suite's
    admin, the tree telling the notes of every pin it ends, as the start wires it."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        self.book = NoteBook()
        self.tree.on_pin_end(self.book.pin_ended)
        for patched in (mock.patch.object(app_module, "status_tree", self.tree),
                        mock.patch.object(app_module, "notes_book", self.book)):
            patched.start()
            self.addCleanup(patched.stop)
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.ran(7)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def ran(self, number: int, *, test: StatusCode = ERROR,
            lint: StatusCode = WARN) -> None:
        """The build's run ``number``: ``test`` as it read in it, its event the run's,
        and ``lint`` as it reads."""
        worst = max((test, lint), key=[OK, WARN, ERROR].index)
        said = "failed" if test is ERROR else "passed"
        self.tree.upsert(BUILD, worst, [
            Entry("test", f"test {said} in run {number}", code=test,
                  occurrence=f"run {number}/1"),
            Entry("lint", "lint warns" if lint is WARN else "lint is clean",
                  code=lint),
            Entry("docs", f"docs built in run {number}", code=OK,
                  occurrence=f"run {number}/1")], members=True)

    def html(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def page(self, url: str) -> Element:
        return parse(self.html(url))

    def post(self, route: str = "/pins/done", **form: str) -> Any:
        return self.client.post(route, data=form)

    def set(self, kind: str, slug: str = "test", note: str = "a flaky runner", *,
            path: str = BUILD) -> Pin:
        """``kind`` on the build's line ``slug``, or on the node at ``path`` itself,
        as ada set it."""
        silence = kind == SILENCED
        write = self.tree.set_acknowledgment(
            path, slug, kind, note, set_by="ada",
            expires_at=datetime.now(UTC) + timedelta(days=1) if silence else None,
            level=OK if silence else None)
        self.assertTrue(write.applied, write.problem)
        assert write.current is not None
        return write.current

    def stands(self, slug: str = "test") -> Pin | None:
        return self.tree.acknowledgment(BUILD, slug)

    def chips(self) -> list[str]:
        """The chips of the Events page's rows, newest first."""
        return [html.unescape(chip) for chip in
                re.findall(r'class="event-cause[^"]*">([^<]+)<', self.html("/events"))]

    def block(self, page: Element, kind: str) -> Element:
        """The one block of ``kind`` that stands on ``page``."""
        (found,) = [block for block in page.all("rule-block")
                    if block.attrs.get("data-rule") == kind
                    and not block.has("rule-block--new")]
        return found

    @staticmethod
    def kinds(editor: Element) -> list[str]:
        """The kinds an editor offers, in its order, each a form of its own."""
        return [form.attrs["data-kind"] for form in editor.all("ack-form")]

    @staticmethod
    def form_of(editor: Element, kind: str) -> Element:
        (found,) = [form for form in editor.all("ack-form")
                    if form.attrs["data-kind"] == kind]
        return found

    @staticmethod
    def hidden(form: Element) -> dict[str, str]:
        return {box.attrs["name"]: box.attrs.get("value", "")
                for box in form.all(tag="input") if box.attrs.get("type") == "hidden"}

    @staticmethod
    def checked(editor: Element) -> list[str]:
        """The kind an editor's choice has chosen."""
        return [box.attrs["value"] for choice in editor.all("ack-kinds")
                for box in choice.all(tag="input") if "checked" in box.attrs]


class TabTests(_Pages):
    """The Notes tab offers *Done* on a failing line of the node whose failure is an
    event, and nowhere else, carrying the event each line reads as the tab was drawn;
    a line acknowledged already is made done where its block stands."""

    def test_done_is_offered_on_the_failing_line_that_names_its_event(self):
        page = self.page(TAB)
        self.assertEqual(self.kinds(page.one("ls-kind-choice")),
                         [NOTE, DONE, SEEN, SILENCED, MAINTENANCE])
        done = self.form_of(page.one("ls-kind-choice"), DONE)
        self.assertEqual(done.attrs["action"], "/pins/done")
        # lint fails, but nothing tells its failure from the next; docs passed
        self.assertEqual([(option.attrs["value"], option.text())
                          for option in done.one(tag="select").all(tag="option")],
                         [("test", "its line: test failed in run 7")])
        sent = self.hidden(done)
        self.assertEqual((sent["path"], sent["occurrence:test"], sent["from"],
                          sent["next"], sent["set_at"]),
                         (BUILD, "run 7/1", "notes", TAB, ""))
        self.assertIn("until it reads anything else: its next run ends it, and "
                      "alarms as new if it fails.",
                      done.one("ack-form__does").text())
        self.assertEqual(done.one(tag="button").text(), "Mark done")

    def test_where_no_failure_is_an_event_no_done_is_offered(self):
        self.ran(8, test=OK)
        self.assertEqual(self.kinds(self.page(TAB).one("ls-kind-choice")),
                         [NOTE, SEEN, SILENCED, MAINTENANCE])
        # a node failing by its own reading: its failure is a stretch
        self.assertEqual(
            self.kinds(self.page("/notes/site/web/disk").one("ls-kind-choice")),
            [NOTE, SEEN, SILENCED, MAINTENANCE])

    def test_asked_for_it_opens_on_it(self):
        page = self.page(f"{TAB}?kind=done&reason=test")
        self.assertEqual(self.checked(page.one("ls-kind-choice")), [DONE])

    def test_a_line_acknowledged_already_is_made_done_where_its_block_stands(self):
        self.set(SEEN)
        page = self.page(TAB)
        self.assertNotIn(DONE, self.kinds(page.one("ls-kind-choice")))
        block = self.block(page.one("ls-tab__stands"), SEEN)
        self.assertEqual(self.kinds(block), [DONE, SEEN, SILENCED])
        self.assertEqual(self.checked(block), [SEEN])
        sent = self.hidden(self.form_of(block, DONE))
        self.assertEqual((sent["occurrence"], sent["next"]), ("run 7/1", TAB))

    def test_what_came_before_lists_it_and_its_end(self):
        self.post(path=BUILD, slug="test", action="set", set_at="",
                  note="a flaky runner, ticket 12", occurrence="run 7/1")
        self.ran(8)
        (entry,) = self.page(TAB).all("ls-entry")
        self.assertIn("Done", entry.one("ls-entry__head").text())
        said = entry.one("ls-note__said").text()
        self.assertIn("a new occurrence", said)
        self.assertIn("a flaky runner, ticket 12", entry.text())


class WriteTests(_Pages):
    """`POST /pins/done`: set from the tab, refused where its line reads another
    event since the tab was drawn or names none, and on a node's own failure; an
    edit; a stale token; a clear; and who may."""

    def from_tab(self, **form: str) -> Any:
        sent = {"path": BUILD, "slug": "test", "action": "set", "set_at": "",
                "next": TAB, "from": "notes", "occurrence:test": "run 7/1",
                "note": "a flaky runner, ticket 12"}
        return self.client.post("/pins/done", data={**sent, **form})

    def test_set_on_the_tab_it_closes_the_event_and_comes_back_there(self):
        response = self.from_tab()
        self.assertEqual(response.headers["Location"], TAB)
        pin = self.stands()
        assert pin is not None
        self.assertEqual((pin.kind, pin.status, pin.occurrence, pin.expires_at,
                          pin.set_by),
                         (DONE, ERROR, "run 7/1", None, "pan"))
        self.assertEqual([note.text for note in self.book.of(BUILD)][-1:],
                         ["a flaky runner, ticket 12"])

    def test_a_line_that_read_another_event_since_closes_nothing(self):
        self.ran(8)
        response = self.from_tab(note="mine")
        self.assertEqual(response.status_code, 200)
        page = parse(response.get_data(as_text=True))
        self.assertIn("Its line test now reads a different event from the one this "
                      "was opened on. Nothing was saved: your words are below.",
                      page.one("ls-notes__refused").text())
        done = self.form_of(page.one("ls-kind-choice"), DONE)
        self.assertEqual(self.checked(page.one("ls-kind-choice")), [DONE])
        self.assertEqual(done.one(tag="textarea").source(), "mine")
        # drawn anew, on the event the line reads now
        self.assertEqual(self.hidden(done)["occurrence:test"], "run 8/1")
        self.assertIsNone(self.stands())

    def test_a_line_that_names_no_event_is_refused_with_why(self):
        response = self.post(path=BUILD, slug="lint", action="set", set_at="",
                             note="mine")
        self.assertEqual(response.status_code, 200)
        page = parse(response.get_data(as_text=True))
        self.assertIn("Nothing was saved. Its line lint names no event: nothing tells "
                      "its failure from the next, so a done has nothing to close.",
                      page.text())
        self.assertEqual(page.one(tag="textarea").source(), "mine")
        self.assertIsNone(self.stands("lint"))

    def test_a_node_s_own_failure_is_no_event(self):
        response = self.post(path="/site/web/disk", action="set", set_at="",
                             note="x")
        self.assertIn("/site/web/disk's own failure is a failing stretch, not an "
                      "event: a done closes an event on one of its lines.",
                      parse(response.get_data(as_text=True)).text())
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))

    def test_an_edit_keeps_its_event_and_a_blank_note_keeps_its_note(self):
        pin = self.set(DONE)
        self.ran(7)
        self.post(path=BUILD, slug="test", action="set", set_at=pin.token, note="",
                  occurrence="run 7/1")
        unchanged = self.stands()
        assert unchanged is not None
        self.assertEqual(unchanged.token, pin.token)
        self.post(path=BUILD, slug="test", action="set", set_at=pin.token,
                  note="the runner was replaced", occurrence="run 7/1")
        after = self.stands()
        assert after is not None
        self.assertEqual((after.id, after.occurrence, after.status, after.note),
                         (pin.id, "run 7/1", ERROR, "the runner was replaced"))

    def test_a_stale_token_shows_both_texts_and_sends_the_event_again(self):
        pin = self.set(DONE, note="theirs")
        self.tree.set_acknowledgment(BUILD, "test", DONE, "changed", expires_at=None,
                                     set_by="ben", expected_set_at=pin.token)
        response = self.post(path=BUILD, slug="test", action="set", set_at=pin.token,
                             note="mine", occurrence="run 7/1")
        page = parse(response.get_data(as_text=True))
        self.assertIn("ben changed this done", page.text())
        self.assertIn("changed", page.one("maintenance-explanation").text())
        self.assertEqual(page.one(tag="textarea").source(), "mine")
        (form,) = [form for form in page.all(tag="form")
                   if form.attrs.get("action") == "/pins/done"]
        stored = self.stands()
        assert stored is not None
        self.assertEqual((self.hidden(form)["set_at"], self.hidden(form)["occurrence"]),
                         (stored.token, "run 7/1"))

    def test_clear_ends_it_by_hand(self):
        pin = self.set(DONE)
        self.post(path=BUILD, slug="test", action="clear", set_at=pin.token)
        self.assertIsNone(self.stands())
        self.assertIn("line's done ended · by hand", self.chips())

    def test_a_viewer_may_not(self):
        self.client.get("/logout")
        response = self.post(path=BUILD, slug="test", action="set", set_at="",
                             occurrence="run 7/1")
        self.assertIn(response.status_code, (302, 401, 403))
        self.assertIsNone(self.stands())

    def test_making_a_seen_done_asks_the_seen_permission_as_well(self):
        # ADR-0144 decision 8: ending an acknowledgment is an act on its kind
        seen = self.set(SEEN)
        with mock.patch.object(identity.Identity, "may",
                               lambda _self, permission: permission == DONE):
            response = self.post(path=BUILD, slug="test", action="set",
                                 set_at=seen.token, note="", occurrence="run 7/1")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.stands(), seen)


class KindTests(_Pages):
    """A block's editor offers *Done* where its part takes one — a line whose
    failure is an event that fails now — and changes an acknowledgment's kind in one
    write; the ringed check's new act keeps *Seen* and *Silence*."""

    def line_block(self, kind: str) -> Element:
        return self.block(self.page(f"/status{BUILD}"), kind)

    def test_a_seen_s_block_offers_done_and_makes_it_done(self):
        seen = self.set(SEEN, note="known")
        block = self.line_block(SEEN)
        self.assertEqual(self.kinds(block), [DONE, SEEN, SILENCED])
        done = self.form_of(block, DONE)
        self.assertEqual(done.attrs["action"], "/pins/done")
        sent = self.hidden(done)
        self.assertEqual((sent["occurrence"], sent["set_at"]), ("run 7/1", seen.token))
        self.assertIn("Marked done instead, the seen ends and a done stands in its "
                      "place", done.one("ack-form__does").text())
        self.post(**sent, note="")
        pin = self.stands()
        assert pin is not None
        self.assertEqual((pin.kind, pin.occurrence, pin.status, pin.note),
                         (DONE, "run 7/1", ERROR, "known"))
        self.assertNotEqual(pin.id, seen.id)
        self.assertIn("line's seen ended · made done", self.chips())

    def test_a_done_s_block_offers_seen_and_a_silence_beside_it(self):
        self.set(DONE)
        block = self.line_block(DONE)
        self.assertEqual(self.kinds(block), [DONE, SEEN, SILENCED])
        self.assertEqual(self.checked(block), [DONE])
        seen = self.form_of(block, SEEN)
        self.assertIn("Marked seen instead, the done ends and a seen stands in its "
                      "place", seen.one("ack-form__does").text())
        self.post("/pins/seen", **self.hidden(seen), note="", duration="")
        pin = self.stands()
        assert pin is not None
        self.assertEqual((pin.kind, pin.status, pin.occurrence),
                         (SEEN, ERROR, "run 7/1"))
        self.assertIn("line's done ended · made seen", self.chips())

    def test_a_line_that_names_no_event_is_offered_no_done(self):
        self.set(SEEN, "lint")
        self.assertEqual(self.kinds(self.line_block(SEEN)), [SEEN, SILENCED])

    def test_a_silence_offers_done_while_its_line_fails_and_its_kind_alone_after(self):
        self.set(SILENCED)
        self.ran(8)
        block = self.line_block(SILENCED)
        self.assertEqual(self.kinds(block), [DONE, SEEN, SILENCED])
        self.assertEqual(self.hidden(self.form_of(block, DONE))["occurrence"],
                         "run 8/1")
        self.ran(9, test=OK)
        self.assertEqual(self.kinds(self.line_block(SILENCED)), [SILENCED])

    def test_a_new_act_is_set_on_the_tab_alone(self):
        # ‖ and the ringed check went with the door, ◇ (ADR-0147 decision 1): no
        # editor of a new act stands on the wall or on a node's page, and a new done
        # is set where every kind is
        for url in ("/status", f"/status{BUILD}"):
            with self.subTest(url=url):
                page = self.page(url)
                self.assertEqual([block for block in page.all("rule-block")
                                  if block.has("rule-block--new")], [])
                self.assertEqual([element for element in page.walk()
                                  if element.attrs.get("id") in (
                                      "ack-editor", "head-ack-setter")], [])
        self.assertIn(DONE, self.kinds(self.page(TAB).one("ls-kind-choice")))

    def test_the_chosen_kind_s_form_alone_is_in_view(self):
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        self.assertEqual(css_rule(css, '.ack-choice:has(> .ack-kinds input'
                                       '[value="done"]:checked) > .ack-form:not('
                                       '[data-kind="done"])').strip(),
                         "display: none;")


class LookTests(_Pages):
    """A line marked done shows ok, with the failure it closed beside its cue, counts
    as ok above and folds with the healthy lines; its block says who closed which
    failure; *Handled*, the band's pill and a chip's ringed diamond count it."""

    def test_its_page_draws_the_line_ok_with_the_failure_it_closed(self):
        self.set(DONE)
        page = self.page(f"/status{BUILD}")
        (line,) = [line for line in page.all("check-reason")
                   if "test failed in run 7" in line.text()]
        self.assertTrue(line.has("s-ok") and line.has("is-done"))
        self.assertFalse(line.has("s-error") or line.has("has-rail"))
        self.assertIn("data-healthy", line.attrs)
        # the failure it closed, set off from the line's own words on both sides
        self.assertEqual(line.one("line-closed").text(), "· error ·")
        self.assertEqual(line.one("line-ack").attrs["title"],
                         "Done by ada, closing an error · counts as ok")

    def test_its_block_says_who_closed_which_failure_and_until_when(self):
        self.set(DONE, note="a flaky runner, ticket 12")
        block = self.block(self.page(f"/status{BUILD}"), DONE)
        said = block.one("rule-block__what").text()
        self.assertIn("This line is marked done by ada, closing", said)
        self.assertIn("error", said)
        self.assertIn("· until it reads anything else", said)
        self.assertIn("a flaky runner, ticket 12", block.text())

    def test_the_wall_draws_it_so_and_its_node_counts_it_ok(self):
        self.ran(7, lint=OK)
        self.set(DONE)
        page = self.page("/status")
        (line,) = [line for line in page.all("status-node__reason")
                   if "test failed in run 7" in line.text()]
        self.assertTrue(line.has("s-ok") and line.has("is-done"))
        self.assertIn("data-healthy", line.attrs)
        self.assertEqual(line.one("line-closed").text(), "· error ·")
        # its mark is its door: the node's Notes tab at the done (ADR-0147
        # decision 7)
        self.assertEqual(line.one("line-ack").attrs["href"],
                         "/notes/site/ci/build?reason=test&at=done#at")
        chips = {chip.attrs["data-path"]: chip for chip in page.all("tree-chip")}
        self.assertTrue(chips[BUILD].has("s-ok"))
        self.assertEqual(chips[BUILD].attrs["title"], "3 ok, 1 handled: 1 done")
        self.assertTrue(chips["/site/ci"].has("s-ok"))
        self.assertEqual(chips["/site/ci"].attrs["title"], "1 ok, 1 handled: 1 done")

    def test_the_band_s_pill_and_a_chip_s_diamond_count_it(self):
        self.set(DONE)
        page = self.html("/status")
        found = re.search(r'class="maintenance-pill"[^>]*aria-label="([^"]+)"', page)
        assert found is not None
        self.assertEqual(found.group(1), "1 handled: 1 done")
        self.assertIn('<a href="/handled#handled-accepted">1 done…</a>', page)
        self.assertIn('<span class="tree-handled" title="1 handled: 1 done">', page)

    def test_handled_lists_it_under_accepted_with_its_editor(self):
        self.set(DONE, note="a flaky runner, ticket 12")
        page = self.page("/handled")
        section = page.with_id("handled-accepted").parent
        assert section is not None
        self.assertIn("1 done on 1 node", section.text())
        self.assertIn("test failed in run 7", section.text())
        self.assertIn("a flaky runner, ticket 12", section.text())
        self.assertEqual(self.kinds(self.block(section, DONE)), [DONE, SEEN, SILENCED])
        self.set(SEEN, "", path="/site/web/disk")
        section = self.page("/handled").with_id("handled-accepted").parent
        assert section is not None
        self.assertIn("1 done and 1 seen on 2 nodes", section.text())


class RowsTests(_Pages):
    """Each set and end is a row of its node, its chip naming the act and why it
    ended; History and the Time card say a line marked done began a period."""

    def test_the_events_chips_name_the_act_and_why_it_ended(self):
        self.set(DONE)
        self.ran(8)
        chips = self.chips()
        self.assertIn("line done", chips)
        self.assertIn("line's done ended · a new occurrence", chips)

    def test_history_and_the_time_card_say_a_line_marked_done_began_its_period(self):
        self.set(DONE)
        time = self.page(f"/status{BUILD}").text()
        self.assertIn("Status warn since", time)
        self.assertIn(", when a line was marked done", time)
        self.assertIn("a line marked done", self.page("/history/site/ci").text())


class ElsewhereTests(_Pages):
    """The Copy document, the envelope and the help say it as the page does."""

    def test_the_copy_documents_state_it(self):
        self.set(DONE)
        node = self.tree.snapshot(BUILD)
        assert node is not None
        style = TimeStyle(ZoneInfo("Europe/Berlin"))
        document = format_node_markdown(node, style)
        self.assertIn("- ✅ test failed in run 7\n"
                      "  - ☑️ Done — by ada, closing error ⛔, until it reads anything "
                      "else\n"
                      "    - a flaky runner\n", document)
        self.assertIn("rolled up from its lines, of which 1 is done", document)
        whole = format_tree_markdown(self.tree.snapshot(""), style,
                                     Origin("https://example.org/status",
                                            datetime.now(UTC)))
        self.assertIn("☑️ Done — by ada, closing error ⛔", whole)

    def test_the_envelope_counts_it_by_done_and_lists_it_with_its_event(self):
        pin = self.set(DONE)
        with mock.patch.object(app_module, "api_tokens", {"tester": "tok"}):
            response = self.client.get(f"/status{BUILD}", headers={
                "Accept": "application/json", "Authorization": "Bearer tok"})
        self.assertEqual(response.status_code, 200)
        (line,) = [item for item in response.get_json()["status"]["entries"]["items"]
                   if item["slug"] == "test"]
        self.assertEqual((line["code"], line["contribution"]),
                         ("ERROR", {"code": "OK", "by": DONE, "rule": pin.id}))
        (item,) = line["handled"]
        self.assertEqual((item["id"], item["kind"], item["source"], item["status"],
                          item["occurrence"], item["expires_at"], item["counts_as"]),
                         (pin.id, DONE, "person", "ERROR", "run 7/1", None,
                          {"WARN": "OK", "ERROR": "OK"}))

    def test_the_help_says_what_a_done_is_and_where_it_is_set(self):
        said = self.page("/help").text()
        self.assertIn("can be marked done where its line says which event it is", said)
        self.assertIn("A done is set on the node's Notes tab", said)
