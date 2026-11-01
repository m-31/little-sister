"""The page's half of *silenced* (ADR-0144): the ringed check's one editor offering
*Seen* and *Silence*, `POST /pins/silenced` — its deadline, its level, an extension
that says what changed, a kind changed from a block's pencil — and its refusals; the
block, the marks, *Handled*'s *Silenced*, a branch's *why*, the rows' words, the Copy
document and the help.

The tree's half is `tests/test_silenced.py`'s.
"""
from __future__ import annotations

import html
import os
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import copy_status, identity
from little_sister.copy_status import (
    Origin,
    TimeStyle,
    format_node_markdown,
    format_tree_markdown,
)
from little_sister.pins import SEEN, SILENCED, Pin
from little_sister.reasons import Entry
from little_sister.spans import local_time
from little_sister.status import StatusCode
from little_sister.tree import (
    CAUSE_LINE_SILENCED_SET,
    StatusTree,
    acknowledgeable_parts,
    parts_digest,
)
from tests.page_tree import Element, parse

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
DAY = timedelta(days=1)


class _Pages(TestCase):
    """A host whose disk fails for itself and a build whose lines are members, under
    one site; signed in as the suite's admin."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        app_module.notes_book.forget()
        self.addCleanup(app_module.notes_book.forget)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.tree.upsert("/site/web/cpu", OK)
        self.build(test=ERROR, lint=WARN, docs=OK)

    def build(self, **codes: StatusCode) -> None:
        words = {ERROR: "fails", WARN: "warns", OK: "builds"}
        worst = max(codes.values(), key=lambda code: (OK, WARN, ERROR).index(code))
        self.tree.upsert("/site/ci/build", worst, [
            Entry(slug, f"{slug} {words[code]}", code=code)
            for slug, code in codes.items()], members=True)

    def page(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def tree_of(self, url: str) -> Element:
        return parse(self.page(url))

    def post(self, route: str = "/pins/silenced", **form: str) -> str:
        response = self.client.post(route, data=form)
        return response.headers.get("Location", "") or response.get_data(as_text=True)

    def silence(self, path: str, slug: str = "", *, level: StatusCode = OK,
                note: str = "it flaps", days: int = 7) -> Pin:
        write = self.tree.set_acknowledgment(
            path, slug, SILENCED, note, expires_at=datetime.now(UTC) + days * DAY,
            set_by="ada", level=level)
        assert write.current is not None, write.problem
        return write.current

    def seen(self, path: str, slug: str = "") -> Pin:
        write = self.tree.set_acknowledgment(path, slug, SEEN, "looked into",
                                             expires_at=None, set_by="ada")
        assert write.current is not None, write.problem
        return write.current

    def stored(self, path: str, slug: str = "") -> Pin:
        pin = self.tree.acknowledgment(path, slug)
        assert pin is not None, (path, slug)
        return pin


class EditorTests(_Pages):
    """A node's *Notes* tab offers *Silence* beside *Seen*, each its own act's form —
    the tab its door opens, the ringed check having gone with the door (ADR-0147) — and
    a block's pencil opens the same two, the standing kind chosen."""

    @staticmethod
    def forms(editor: Element) -> dict[str, Element]:
        return {form.attrs["action"]: form for form in editor.all(tag="form")}

    @staticmethod
    def chosen(editor: Element, name: str) -> list[tuple[str, bool]]:
        """The radios of a choice named ``name``, each its value and whether it is
        checked."""
        return [(radio.attrs.get("value", ""), "checked" in radio.attrs)
                for radio in editor.all(tag="input")
                if radio.attrs.get("type") == "radio"
                and radio.attrs.get("name", "").endswith(name)]

    @staticmethod
    def fields(form: Element) -> set[str]:
        return {field.attrs.get("name", "") for field in form.walk()
                if field.tag in ("input", "textarea")}

    def test_the_tab_offers_both_kinds_on_a_failing_line_seen_chosen(self):
        choice = self.tree_of("/notes/site/ci/build?reason=test").one("ls-kind-choice")
        forms = self.forms(choice)
        self.assertLessEqual({"/pins/seen", "/pins/silenced"}, set(forms))
        self.assertIn(("seen", True), self.chosen(choice, "tab-kind"))
        self.assertIn(("silenced", False), self.chosen(choice, "tab-kind"))
        self.assertEqual(self.chosen(forms["/pins/silenced"], "level"),
                         [("ok", True), ("warn", False)])
        self.assertIn("deadline", self.fields(forms["/pins/silenced"]))
        self.assertIn("duration", self.fields(forms["/pins/seen"]))
        # a new silence asks nothing of what changed: there is nothing to extend
        self.assertNotIn("changed", self.fields(forms["/pins/silenced"]))

    def test_the_wall_carries_no_editor_of_a_new_one(self):
        page = self.page("/status")
        self.assertNotIn('<template id="ack-editor">', page)
        self.assertNotIn('action="/pins/silenced"', page)

    def test_a_silence_s_pencil_chooses_it_and_asks_what_changed(self):
        self.silence("/site/web/disk", level=WARN)
        (editor,) = [found for found in
                     self.tree_of("/status/site/web/disk").all("rule-block__edit")
                     if found.parent is not None and found.parent.parent is not None
                     and found.parent.parent.attrs.get("data-rule") == SILENCED]
        forms = self.forms(editor)
        self.assertEqual(self.chosen(editor, "-kind"),
                         [("seen", False), ("silenced", True)])
        self.assertEqual(self.chosen(forms["/pins/silenced"], "level"),
                         [("ok", False), ("warn", True)])
        self.assertLessEqual({"changed", "deadline", "deadline_was"},
                             self.fields(forms["/pins/silenced"]))
        # the seen's form makes it seen instead, the silence ending
        self.assertIn("Marked seen instead, the silence ends",
                      forms["/pins/seen"].text())

    def editors(self, url: str) -> list[Element]:
        """The editors of the silences ``url`` states whole."""
        return [found for found in self.tree_of(url).all("rule-block__edit")
                if found.parent is not None and found.parent.parent is not None
                and found.parent.parent.attrs.get("data-rule") == SILENCED]

    def test_one_that_fails_no_longer_offers_no_seen(self):
        # a seen takes a part that fails now: on a silence that held through a
        # recovery, the block's editor offers the silence's own form alone, and no
        # choice — on the pages that state it whole; the wall's block is a link
        # (ADR-0147 decision 7)
        self.silence("/site/ci/build", "test")
        self.silence("/site/web/disk")
        self.build(test=OK, lint=WARN, docs=OK)
        self.tree.upsert("/site/web/disk", OK, "disk 60 % full")
        self.client.set_cookie("handled_details", "1")
        self.assertEqual(self.editors("/status"), [])
        for url, count in (("/status/site/ci/build", 1), ("/status/site/web/disk", 1),
                           ("/notes/site/web/disk", 1), ("/handled", 2)):
            editors = self.editors(url)
            self.assertEqual(len(editors), count, url)
            for editor in editors:
                self.assertEqual(list(self.forms(editor)), ["/pins/silenced"], url)
                self.assertEqual(self.chosen(editor, "-kind"), [], url)
        # where it fails again, the editor offers both
        self.build(test=ERROR, lint=WARN, docs=OK)
        (editor,) = self.editors("/status/site/ci/build")
        self.assertEqual(list(self.forms(editor)), ["/pins/seen", "/pins/silenced"])

    def test_a_blank_deadline_s_placeholder_names_the_default(self):
        with mock.patch.object(app_module, "config",
                               replace(app_module.config,
                                       silence_default_expiry="3d")):
            page = self.page("/notes/site/ci/build")
        self.assertIn("default 3d, at most 30 days", page)


class WriteTests(_Pages):
    """`POST /pins/silenced`: one part, a head's parts, an edit, an extension, a kind
    changed, a clear, a refusal."""

    def test_a_line_silenced_from_its_page(self):
        before = datetime.now(UTC)
        where = self.post(path="site/ci/build", slug="test", action="set", set_at="",
                          note="flaky since the runner move", level="warn",
                          deadline="")
        self.assertTrue(where.endswith("?reason=test#pinned-reason"), where)
        pin = self.stored("/site/ci/build", "test")
        self.assertEqual((pin.kind, pin.level, pin.set_by, pin.status),
                         (SILENCED, WARN, "pan", None))
        assert pin.expires_at is not None
        # a blank deadline is the deployment's default, a week
        self.assertTrue(before + 7 * DAY <= pin.expires_at
                        <= datetime.now(UTC) + 7 * DAY)

    def test_a_blank_deadline_takes_the_deployment_s_default(self):
        with mock.patch.object(app_module, "config",
                               replace(app_module.config,
                                       silence_default_expiry="3d")):
            self.post(path="/site/web/disk", action="set", set_at="", note="",
                      level="ok", deadline="")
        expires = self.stored("/site/web/disk").expires_at
        assert expires is not None
        self.assertAlmostEqual((expires - datetime.now(UTC)).total_seconds(),
                               3 * 86400, delta=60)

    def test_a_default_past_thirty_days_is_not_honored(self):
        with mock.patch.object(app_module, "config",
                               replace(app_module.config,
                                       silence_default_expiry="60d")):
            page = self.page("/notes/site/ci/build")
            self.post(path="/site/web/disk", action="set", set_at="", note="",
                      level="ok", deadline="")
        expires = self.stored("/site/web/disk").expires_at
        assert expires is not None
        self.assertAlmostEqual((expires - datetime.now(UTC)).total_seconds(),
                               7 * 86400, delta=60)
        # and the form names the week a blank deadline runs for, not the 60d
        self.assertIn("default 7d, at most 30 days", page)
        self.assertNotIn("60d", page)

    def test_a_default_that_is_not_honored_is_said_at_start(self):
        for value in ("60d", "6w", "soon", "0d"):
            with self.subTest(value=value), self.assertLogs(
                    "little_sister.logger", "WARNING") as logged:
                named = app_module._warn_unhonored_defaults(
                    replace(app_module.config, silence_default_expiry=value))
            self.assertEqual(named, ["silence_default_expiry"])
            self.assertIn(f"silence_default_expiry {value!r} is not a duration",
                          logged.output[0])
        # a window's bound is a year: what is too long for a silence is not for it
        with self.assertNoLogs("little_sister.logger", "WARNING"):
            named = app_module._warn_unhonored_defaults(
                replace(app_module.config, maintenance_default_expiry="6w",
                        silence_default_expiry="2w"))
        self.assertEqual(named, [])

    def test_a_deadline_is_at_most_thirty_days_away(self):
        answer = self.post(path="/site/web/disk", action="set", set_at="", note="x",
                           level="ok", deadline="721h")
        self.assertIn("Nothing was saved", answer)
        self.assertIn("more than thirty days away", answer)
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))
        self.post(path="/site/web/disk", action="set", set_at="", note="x",
                  level="ok", deadline="720h")
        self.assertEqual(self.stored("/site/web/disk").kind, SILENCED)

    def test_a_deadline_lasts_until_the_slowest_check_runs_again(self):
        daily = app_module._IntervalFloor(86400, "/site/web")
        with mock.patch.object(app_module, "_interval_floor", return_value=daily):
            answer = self.post(path="/site/web/disk", action="set", set_at="",
                               note="x", level="ok", deadline="2h")
        self.assertIn("ends before /site/web (every 1d) runs again", answer)
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))
        # a check slower than the thirty days sets no floor: no deadline covers it
        slow = app_module._IntervalFloor(40 * 86400, "/site/web")
        with mock.patch.object(app_module, "_interval_floor", return_value=slow):
            self.post(path="/site/web/disk", action="set", set_at="", note="x",
                      level="ok", deadline="2h")
        self.assertEqual(self.stored("/site/web/disk").kind, SILENCED)

    def test_a_level_is_chosen_or_nothing_is_saved(self):
        for level in ("", "error", "loud"):
            answer = self.post(path="/site/web/disk", action="set", set_at="",
                               note="x", level=level, deadline="")
            self.assertIn("counts above as ok or at most as a warning", answer)
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))

    def test_a_head_silences_each_failure_beneath_it(self):
        node = self.tree.snapshot("/site")
        assert node is not None
        digest = parts_digest(acknowledgeable_parts(node))
        self.post(path="/site", parts=digest, action="set", set_at="",
                  note="a noisy week", level="warn", deadline="2d", next="/status")
        nodes, lines = self.tree.acknowledgments()
        self.assertEqual((sorted(nodes), sorted(lines)),
                         (["/site/web/disk"],
                          [("/site/ci/build", "lint"), ("/site/ci/build", "test")]))
        held = [*nodes.values(), *lines.values()]
        self.assertEqual({(pin.kind, pin.level) for pin in held}, {(SILENCED, WARN)})
        self.assertEqual(len({pin.id for pin in held}), 3)

    def test_a_head_whose_failures_changed_silences_nothing_and_lists_them(self):
        node = self.tree.snapshot("/site")
        assert node is not None
        digest = parts_digest(acknowledgeable_parts(node))
        self.tree.upsert("/site/web/cpu", WARN, "load 9")
        answer = self.post(path="/site", parts=digest, action="set", set_at="",
                           note="all of it", level="ok", deadline="")
        self.assertIn("What fails here changed", answer)
        self.assertIn("/site/web/cpu", answer)
        self.assertEqual(self.tree.acknowledgments(), ({}, {}))

    def test_a_head_s_set_refused_for_its_words_keeps_its_parts(self):
        # the head fails itself too, so a form that forgot the digest would silence
        # its own failure alone: what is sent again silences each part listed
        self.tree.upsert("/site/web", ERROR, "the web tier is slow")
        node = self.tree.snapshot("/site/web")
        assert node is not None
        digest = parts_digest(acknowledgeable_parts(node))
        answer = parse(self.post(path="/site/web", parts=digest, action="set",
                                 set_at="", note="a vendor patch", level="ok",
                                 deadline="45d"))
        self.assertIn("more than thirty days away", answer.text())
        self.assertIn("/site/web/disk", answer.one("ack-parts").text())
        (form,) = [form for form in answer.all(tag="form")
                   if form.attrs.get("action") == "/pins/silenced"]
        sent = {field.attrs["name"]: field.attrs.get("value", "")
                for field in form.walk() if field.tag == "input"
                and field.attrs.get("type") == "hidden"}
        self.assertEqual(sent["parts"], digest)
        self.post(**sent, note="a vendor patch", level="ok", deadline="14d")
        nodes, lines = self.tree.acknowledgments()
        self.assertEqual((sorted(nodes), lines), (["/site/web", "/site/web/disk"], {}))

    def test_a_part_that_reads_ok_is_silenced_and_one_in_maintenance_is_not(self):
        # bound to no failure (decision 1): a leaf that reads ok takes one ...
        where = self.post(path="/site/web/cpu", action="set", set_at="",
                          note="it flaps at night", level="warn", deadline="")
        self.assertEqual(where, "/status/site/web/cpu")
        pin = self.stored("/site/web/cpu")
        self.assertEqual((pin.kind, pin.level, pin.status), (SILENCED, WARN, None))
        # ... and a line in maintenance is refused with why, nothing written
        self.tree.set_entry_maintenance("/site/ci/build", "docs", "",
                                        expires_at=datetime.now(UTC) + DAY)
        answer = self.post(path="/site/ci/build", slug="docs", action="set",
                           set_at="", note="x", level="ok", deadline="")
        self.assertIn("Not silenced", answer)
        self.assertIn("Its line docs is in maintenance.", answer)
        self.assertIsNone(self.tree.acknowledgment("/site/ci/build", "docs"))

    def test_an_edit_keeps_its_deadline_and_a_blank_note_keeps_its_note(self):
        self.post(path="/site/web/disk", action="set", set_at="", note="patching",
                  level="ok", deadline="3d")
        pin = self.stored("/site/web/disk")
        assert pin.expires_at is not None
        filled = app_module._expiry_input(pin.expires_at)
        self.post(path="/site/web/disk", action="set", set_at=pin.token, note="",
                  level="warn", deadline=filled, deadline_was=filled)
        after = self.stored("/site/web/disk")
        self.assertEqual((after.note, after.expires_at, after.id, after.level),
                         ("patching", pin.expires_at, pin.id, WARN))

    def test_an_extension_says_what_changed_in_a_note_of_its_own(self):
        self.post(path="/site/web/disk", action="set", set_at="", note="patching",
                  level="ok", deadline="3d")
        pin = self.stored("/site/web/disk")
        answer = self.post(path="/site/web/disk", action="set", set_at=pin.token,
                           note="", level="ok", deadline="10d", changed="")
        self.assertIn("an extension says what changed", answer)
        self.assertEqual(self.stored("/site/web/disk").expires_at, pin.expires_at)
        self.post(path="/site/web/disk", action="set", set_at=pin.token, note="",
                  level="ok", deadline="10d",
                  changed="The vendor moved the patch to Friday.")
        after = self.stored("/site/web/disk")
        assert after.expires_at is not None and pin.expires_at is not None
        self.assertGreater(after.expires_at, pin.expires_at)
        notes = app_module.notes_book.of("/site/web/disk")
        own = [note for note in notes if not note.pin]
        self.assertEqual([note.text for note in own],
                         [f"Silence extended until {local_time(after.expires_at)}. "
                          f"The vendor moved the patch to Friday."])
        self.assertEqual(own[0].created_by, "pan")
        # beside the silence's own note, which keeps saying what is being done
        self.assertEqual([note.text for note in notes if note.pin], ["patching"])

    def test_a_shorter_deadline_or_another_level_asks_nothing(self):
        self.post(path="/site/web/disk", action="set", set_at="", note="patching",
                  level="ok", deadline="5d")
        pin = self.stored("/site/web/disk")
        self.post(path="/site/web/disk", action="set", set_at=pin.token, note="",
                  level="warn", deadline="2d")
        after = self.stored("/site/web/disk")
        assert after.expires_at is not None and pin.expires_at is not None
        self.assertLess(after.expires_at, pin.expires_at)
        self.assertEqual(after.level, WARN)
        self.assertEqual([note for note in app_module.notes_book.of("/site/web/disk")
                          if not note.pin], [])

    def test_what_changed_is_kept_on_any_edit_that_says_it(self):
        self.post(path="/site/web/disk", action="set", set_at="", note="patching",
                  level="ok", deadline="5d")
        pin = self.stored("/site/web/disk")
        self.post(path="/site/web/disk", action="set", set_at=pin.token, note="",
                  level="warn", deadline="2d", changed="It fails more often now.")
        after = self.stored("/site/web/disk")
        assert after.expires_at is not None
        until = local_time(after.expires_at)
        own = [note.text for note in app_module.notes_book.of("/site/web/disk")
               if not note.pin]
        self.assertEqual(own, [f"Silence changed: until {until}, counting as a "
                               f"warning at most. It fails more often now."])
        # and on a save that changes nothing else, the deadline kept as it was
        filled = app_module._expiry_input(after.expires_at)
        self.post(path="/site/web/disk", action="set", set_at=after.token, note="",
                  level="warn", deadline=filled, deadline_was=filled,
                  changed="The vendor answered.")
        own = [note.text for note in app_module.notes_book.of("/site/web/disk")
               if not note.pin]
        self.assertIn(f"Silence changed: until {until}, counting as a warning at "
                      f"most. The vendor answered.", own)
        self.assertEqual(len(own), 2)

    def test_a_seen_made_a_silence_from_its_pencil(self):
        seen = self.seen("/site/ci/build", "test")
        self.post(path="/site/ci/build", slug="test", action="set", set_at=seen.token,
                  note="", level="warn", deadline="")
        made = self.stored("/site/ci/build", "test")
        self.assertEqual((made.kind, made.level, made.note), (SILENCED, WARN,
                                                             "looked into"))
        self.assertNotEqual(made.id, seen.id)

    def test_a_silence_made_seen_from_its_pencil(self):
        silence = self.silence("/site/web/disk", level=WARN)
        self.post(route="/pins/seen", path="/site/web/disk", action="set",
                  set_at=silence.token, note="", duration="")
        made = self.stored("/site/web/disk")
        self.assertEqual((made.kind, made.status, made.expires_at, made.note),
                         (SEEN, ERROR, None, "it flaps"))

    def test_a_stale_token_shows_both_texts(self):
        pin = self.silence("/site/web/disk", note="theirs")
        self.tree.set_acknowledgment("/site/web/disk", "", SILENCED, "changed",
                                     expires_at=pin.expires_at, set_by="ben",
                                     expected_set_at=pin.token, level=WARN)
        answer = self.post(path="/site/web/disk", action="set", set_at=pin.token,
                           note="mine", level="ok", deadline="")
        self.assertIn("changed this silence ", answer)
        self.assertIn("mine", answer)
        self.assertEqual(self.stored("/site/web/disk").note, "changed")

    def test_a_clear_ends_it_by_hand(self):
        pin = self.silence("/site/ci/build", "test")
        self.post(path="/site/ci/build", slug="test", action="clear",
                  set_at=pin.token)
        self.assertIsNone(self.tree.acknowledgment("/site/ci/build", "test"))

    def test_its_note_enters_the_node_s_notes(self):
        self.tree.on_pin_end(app_module.notes_book.pin_ended)
        self.post(path="/site/web/disk", action="set", set_at="",
                  note="the vendor patches friday", level="ok", deadline="")
        notes = app_module.notes_book.of("/site/web/disk")
        self.assertEqual([note.text for note in notes], ["the vendor patches friday"])
        # while the silence stands its note is its block's, under what stands, an
        # acknowledgment standing as a maintenance pin does, and it joins what came
        # before as it ends (ADR-0145 decision 6)
        page = self.tree_of("/notes/site/web/disk")
        self.assertIn("the vendor patches friday", page.one("ls-tab__stands").text())
        self.assertEqual(page.all("ls-entry"), [])
        pin = self.stored("/site/web/disk")
        self.tree.clear_acknowledgment("/site/web/disk", expected_set_at=pin.token,
                                       by="ada")
        (entry,) = self.tree_of("/notes/site/web/disk").all("ls-entry")
        self.assertIn("Silenced · on the node", entry.one("ls-entry__head").text())
        self.assertIn("ended: by hand, by ada", entry.one("ls-note__said").text())

    def test_a_viewer_may_not(self):
        self.client.get("/logout")
        response = self.client.post("/pins/silenced", data={"path": "/site/web/disk"})
        self.assertIn(response.status_code, (302, 401, 403))
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))

    def test_ending_one_asks_the_permission_of_its_kind(self):
        # who may mark seen but not silence ends no silence, by hand or by making it
        # seen — nor the silence permission alone a seen; each ends its own kind
        silence = self.silence("/site/web/disk")
        seen = self.seen("/site/ci/build", "test")

        def only(granted: str) -> Any:
            return mock.patch.object(identity.Identity, "may",
                                     lambda _self, permission: permission == granted)

        with only(SEEN):
            for form in ({"action": "clear"}, {"action": "set", "duration": ""}):
                response = self.client.post("/pins/seen", data={
                    "path": "/site/web/disk", "set_at": silence.token, **form})
                self.assertEqual(response.status_code, 403, form)
        self.assertEqual(self.stored("/site/web/disk").token, silence.token)
        with only(SILENCED):
            for form in ({"action": "clear"},
                         {"action": "set", "level": "ok", "deadline": ""}):
                response = self.client.post("/pins/silenced", data={
                    "path": "/site/ci/build", "slug": "test", "set_at": seen.token,
                    **form})
                self.assertEqual(response.status_code, 403, form)
        self.assertEqual(self.stored("/site/ci/build", "test").token, seen.token)
        with only(SILENCED):
            self.post(path="/site/web/disk", action="clear", set_at=silence.token)
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))


class BlockTests(_Pages):
    """A silence, stated where it stands, and marked where it acts."""

    def blocks(self, url: str) -> list[Element]:
        return [block for block in self.tree_of(url).all("rule-block")
                if block.attrs.get("data-rule") == SILENCED
                and not block.has("rule-block--new")]

    def test_a_line_s_block_and_its_mark_on_its_page(self):
        pin = self.silence("/site/ci/build", "test", note="flaky, ticket 12")
        (block,) = self.blocks("/status/site/ci/build")
        self.assertIn("This line is silenced by ada, counting as", block.text())
        self.assertIn("flaky, ticket 12", block.text())
        self.assertIn("Silenced by ada", block.text())
        assert pin.expires_at is not None
        page = self.tree_of("/status/site/ci/build")
        (mark,) = page.all("line-ack")
        self.assertEqual(mark.attrs.get("title"),
                         f"Silenced by ada until {local_time(pin.expires_at)} "
                         f"· counts as ok")

    def test_a_node_s_block_heads_its_page(self):
        self.silence("/site/web/disk", level=WARN)
        (block,) = self.blocks("/status/site/web/disk")
        self.assertIn("This node is silenced by ada, counting as", block.text())
        self.assertIn("at most until", block.text())

    def test_the_wall_states_it_in_its_box(self):
        # while *◇ details* is on, the link that opens the drawer at it
        self.silence("/site/web/disk")
        self.assertEqual(self.blocks("/status"), [])
        self.client.set_cookie("handled_details", "1")
        (block,) = self.blocks("/status")
        self.assertIn("Silenced by ada, counting as", block.text())
        self.assertEqual(block.attrs.get("href"),
                         "/notes/site/web/disk?at=silenced#at")

    def test_a_line_s_mark_is_drawn_in_the_color_it_counts_as(self):
        self.silence("/site/ci/build", "test", level=WARN)
        (mark,) = self.tree_of("/status").all("line-ack")
        self.assertTrue(mark.has("mark-warn"), mark.attrs)
        self.assertTrue(mark.attrs.get("title", "").endswith("· counts as warn"))
        # one that reads a warning counts as it reads, and draws no rail: its mark
        # is the warning's, not a seen's green
        self.build(test=WARN, lint=WARN, docs=OK)
        page = self.tree_of("/status")
        (mark,) = page.all("line-ack")
        self.assertTrue(mark.has("mark-warn"), mark.attrs)
        self.assertEqual([line for line in page.all("rail-warn")
                          if "test warns" in line.text()], [])
        # a recovered one counts as it reads, ok, and draws no rail
        self.build(test=OK, lint=WARN, docs=OK)
        (mark,) = self.tree_of("/status").all("line-ack")
        self.assertTrue(mark.has("mark-ok"), mark.attrs)

    def test_the_head_marks_a_node_silenced(self):
        self.silence("/site/web/disk", level=WARN)
        page = self.tree_of("/status/site/web/disk")
        marks = page.all("head-ack")
        self.assertTrue(marks)
        self.assertTrue(marks[0].has("ls-sign--warn"), marks[0].attrs)
        self.assertIn("its own part counts as warn above",
                      marks[0].attrs.get("title", ""))

    def test_the_head_marks_a_stale_node_a_warning_recovered_or_not(self):
        # staleness escalates whatever holds a reading: a silenced node that
        # recovered and then stopped reporting counts as a warning above
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full",
                         frequency_seconds=60)
        self.silence("/site/web/disk")
        self.tree.upsert("/site/web/disk", OK, frequency_seconds=60)
        later = datetime.now(UTC) + timedelta(minutes=10)
        with mock.patch("little_sister.instants.now", return_value=later):
            disk = self.tree.snapshot("/site/web/disk")
            marks = self.tree_of("/status/site/web/disk").all("head-ack")
        assert disk is not None
        self.assertIs(disk.counted, WARN)
        self.assertTrue(marks)
        self.assertTrue(marks[0].has("ls-sign--warn"), marks[0].attrs)
        self.assertIn("its own part counts as warn above",
                      marks[0].attrs.get("title", ""))

    def test_the_band_s_pill_counts_each_silence(self):
        self.seen("/site/web/disk")
        self.silence("/site/ci/build", "test")
        page = self.page("/status")
        found = re.search(r'class="maintenance-pill"[^>]*aria-label="([^"]+)"', page)
        assert found is not None
        self.assertEqual(found.group(1), "2 handled: 1 seen, 1 silenced")
        self.assertIn("#handled-silenced", page)

    def test_a_card_s_door_counts_it_and_the_tab_says_its_level_and_what_is_left(self):
        self.silence("/site/ci/build", "test", level=WARN, days=3)
        self.assertIn('title="Handle it — 1 handled: 1 silenced"',
                      self.page("/status"))
        tab = self.page("/notes/site")
        self.assertIn("silenced by <strong>ada</strong>, counting as warn at most", tab)
        self.assertRegex(tab, r"· 2d 2\dh left")

    def test_handled_lists_it_under_silenced(self):
        self.silence("/site/web/disk", note="the vendor patches friday")
        self.silence("/site/ci/build", "test", level=WARN)
        page = self.tree_of("/handled")
        section = page.with_id("handled-silenced").parent
        assert section is not None
        self.assertIn("2 silenced on 2 nodes", section.text())
        self.assertIn("Its own part", section.text())
        self.assertIn("test fails", section.text())
        self.assertEqual([found for found in page.walk()
                          if found.attrs.get("id") == "handled-accepted"], [])

    def test_a_branch_s_why_lists_it_under_silenced(self):
        self.silence("/site/web/disk", level=WARN)
        page = self.tree_of("/status/site/web")
        card = page.with_id("why")
        assert card is not None
        self.assertIn("Silenced", card.text())
        self.assertIn("silenced by ada, counting as warn at most", card.text())


class WordsTests(_Pages):
    """What the rows, History and the Time card say of a silence."""

    def chips(self) -> list[str]:
        return [html.unescape(chip) for chip in
                re.findall(r'class="event-cause[^"]*">([^<]+)<', self.page("/events"))]

    def test_the_events_chips_name_the_act(self):
        pin = self.silence("/site/web/disk")
        self.tree.set_acknowledgment("/site/web/disk", "", SILENCED, "it flaps",
                                     expires_at=pin.expires_at, set_by="ada",
                                     expected_set_at=pin.token, level=WARN)
        changed = self.stored("/site/web/disk")
        self.tree.clear_acknowledgment("/site/web/disk",
                                       expected_set_at=changed.token)
        chips = self.chips()
        for chip in ("silenced", "silence changed", "silence ended · by hand"):
            self.assertIn(chip, chips)

    def test_a_kind_changed_says_which_ended_and_why(self):
        seen = self.seen("/site/ci/build", "test")
        self.tree.set_acknowledgment(
            "/site/ci/build", "test", SILENCED, "it flaps",
            expires_at=datetime.now(UTC) + DAY, set_by="ada",
            expected_set_at=seen.token, level=OK)
        chips = self.chips()
        self.assertIn("line's seen ended · made a silence", chips)
        self.assertIn("line silenced", chips)

    def test_history_says_what_moved_the_branch(self):
        self.silence("/site/web/disk")
        page = self.page("/history/site/web")
        self.assertIn('<td class="text-nowrap">silenced</td>', page)

    def test_the_time_card_says_when_a_line_was_silenced(self):
        self.build(test=ERROR, lint=OK)
        self.silence("/site/ci/build", "test", level=WARN)
        period = self.tree.history("/site/ci/build")[-1]
        self.assertEqual(period.cause, CAUSE_LINE_SILENCED_SET)
        self.assertEqual(app_module._began(period), "when a line was silenced")


class ElsewhereTests(_Pages):
    """The Copy document and the help say it as the page does."""

    def test_the_copy_documents_state_it(self):
        pin = self.silence("/site/web/disk", level=WARN, note="patching")
        node = self.tree.snapshot("/site/web/disk")
        assert node is not None and pin.expires_at is not None
        style = TimeStyle(ZoneInfo("Europe/Berlin"))
        document = format_node_markdown(node, style)
        self.assertIn("🔕 Silenced — by ada, counting as warn ⚠️ at most, until "
                      f"{style.at(pin.expires_at)}", document)
        whole = format_tree_markdown(self.tree.snapshot("/site"), style,
                                     Origin("https://example.org/status",
                                            datetime.now(UTC)))
        self.assertIn("🔕 Silenced — by ada", whole)
        # a branch's own document lists it under what is handled beneath it, by job
        web = self.tree.snapshot("/site/web")
        assert web is not None
        branch = format_node_markdown(web, style)
        self.assertIn("- 🔕 Silenced\n", branch)
        self.assertIn("— silenced by ada, counting as warn ⚠️ at most, until", branch)

    def test_the_sign_is_the_bell_with_its_stroke(self):
        sign = copy_status._SILENCED_SIGN
        self.assertEqual((len(sign), ord(sign)), (1, 0x1F515))

    def test_the_help_says_how_to_silence(self):
        page = self.page("/help")
        self.assertIn("can be <strong>silenced</strong> until a", page)
        self.assertIn("thirty days at most", page)
