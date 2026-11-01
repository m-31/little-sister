"""A ticket filed from a node's *Notes* tab (ADR-0148).

The library declares the slot ``notes.actions`` in the tab's form — after the kind's
own button in every kind's row, and in the small form a reader who may set no kind is
given — and calls, from a route of its own, the draft function its filler registers
beside it: handed the node's path, the kind, the part chosen under *On*, what that
part reads, the words written out and the Notes tab's address, it answers with the
address the function returns, a 303 to an http(s) one, and never with an address the
request carries; where it cannot, a page of its own says why in the new tab. The suite's
own filler drafts from the words with the promise alone. Every slot is handed the Notes
tab's address, ``tests/test_slots.py``'s; what the drawer does with a button that opens
another tab, ``tests/test_drawer_browser.py``'s.
"""
from __future__ import annotations

import os
from typing import Any
from unittest import TestCase, mock
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import identity, slots
from little_sister.notes import NoteBook
from little_sister.reasons import Entry as Line
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.demo_extension import draft_issue
from tests.page_tree import Element, parse

DEMO = "tests.demo_extension"
BUTTON = "notes_action.html"
OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
#: What the recording draft function answers unless a test says otherwise.
ADDRESS = "https://tracker.example.org/new?title=drafted"


def _nobody_may(_self: object, _permission: str) -> bool:
    return False


class _Filing(TestCase):
    """``/ci`` over a node whose lines are members, three of them failing, and a node
    failing by its own reading, as the Notes tab's own tests have it; signed in as the
    suite's admin; the suite's button registered for the tab's slot, its draft function
    one that records what it is handed."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        self.book = NoteBook()
        for patched in (mock.patch.object(app_module, "status_tree", self.tree),
                        mock.patch.object(app_module, "notes_book", self.book)):
            patched.start()
            self.addCleanup(patched.stop)
        self.addCleanup(slots.forget_fillers)
        self.tree.upsert("/ci/pipelines", ERROR, [
            Line("build", "build failed: {error}", code=ERROR),
            Line("lint", "lint failed", code=ERROR),
            Line("gate", "the gate waits", code=WARN),
            Line("docs", "docs built", code=OK)], members=True)
        self.tree.upsert("/ci/jobs", ERROR,
                         ["export failed", "Traceback (most recent call last)"])
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.handed: list[dict[str, Any]] = []
        self.answer: Any = ADDRESS
        slots.register("notes.actions", DEMO, BUTTON, draft=self.recording)

    def recording(self, **handed: Any) -> Any:
        # the Notes tab's address is the request's: read while it is answered
        self.handed.append({**handed, "notes_said": handed["notes_url"]()})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def file(self, path: str = "ci/pipelines", *, kind: str = "note",
             package: str = DEMO, **form: str) -> Any:
        """A press of the button: the kind's form, posted to the route its button
        names, the button naming its package."""
        query = f"?kind={kind}" if kind else ""
        return self.client.post(f"/draft/{path}{query}",
                                data={"draft": package, **form})

    def parts(self) -> list[tuple[str, str, tuple[str, ...]]]:
        (handed,) = self.handed
        return [(part.path, part.slug, part.lines) for part in handed["parts"]]


class ButtonTests(_Filing):
    """Decision 2 of #120's pass, as the tab draws it: the filler's button after the
    kind's own in every kind's row, a line beneath the row saying what it does, and for
    a reader who may set no kind a small form of its own."""

    def test_every_kind_s_row_ends_in_the_filler_s_button_after_the_kind_s_own(self):
        page = self.page("/notes/ci/pipelines")
        forms = page.all("ls-kind-form")
        self.assertEqual([form.attrs["data-kind"] for form in forms],
                         ["note", "seen", "silenced", "maintenance"])
        for form in forms:
            kind = form.attrs["data-kind"]
            with self.subTest(kind=kind):
                row = form.one("maintenance-editor-form__actions")
                buttons = form.all(tag="button")
                (own,) = [button for button in buttons
                          if button.has("btn-primary") and button.within(row)]
                # the form's first submit button, its default, does the kind's act, so
                # that Enter in a field still does the act and never opens a draft:
                # the kind's own, or — before a maintenance editor's own buttons — a
                # hidden one that names no button of the editor's (ADR-0150, landing 4)
                default = buttons[0]
                self.assertTrue(default is own or (
                    default.has("ls-default-submit") and "name" not in default.attrs),
                    buttons)
                filed = form.one("notes-actions").one(tag="button")
                self.assertIs(filed, buttons[buttons.index(own) + 1])
                self.assertTrue(filed.within(row))
                self.assertEqual(
                    (filed.attrs["formaction"], filed.attrs["formtarget"],
                     filed.attrs["name"], filed.attrs["value"]),
                    (f"/draft/ci/pipelines?kind={kind}", "_blank", "draft", DEMO))
                said = form.one("ls-file-hint").text()
                for words in ("new tab", "first line", "link"):
                    self.assertIn(words, said)

    def test_without_a_filler_a_row_is_as_it_was(self):
        slots.forget_fillers()
        page = self.page("/notes/ci/pipelines")
        self.assertEqual(page.all("notes-actions"), [])
        self.assertEqual(page.all("ls-file-hint"), [])

    def test_a_reader_who_may_set_no_kind_files_from_a_small_form(self):
        with mock.patch.object(identity.Identity, "may", _nobody_may):
            page = self.page("/notes/ci/pipelines")
        self.assertEqual(page.all("ls-kind-form"), [])
        form = page.one("ls-tab__file").one(tag="form")
        self.assertEqual(
            (form.attrs["method"], form.attrs["action"], form.attrs["target"]),
            ("post", "/draft/ci/pipelines", "_blank"))
        self.assertEqual(
            [option.attrs["value"]
             for option in form.one(tag="select").all(tag="option")],
            ["", "build", "lint", "gate", "docs"])
        self.assertEqual(form.one("notes-actions").one(tag="button")
                         .attrs["formaction"], "/draft/ci/pipelines")
        self.assertEqual(form.all(tag="textarea"), [], "no words: the part drafts")
        # where nothing fills the slot there is nothing to file with, and no form
        slots.forget_fillers()
        with mock.patch.object(identity.Identity, "may", _nobody_may):
            page = self.page("/notes/ci/pipelines")
        self.assertEqual(page.all("ls-tab__file"), [])

    def test_the_panel_s_reader_form_leaves_the_frame_as_the_button_does(self):
        with mock.patch.object(identity.Identity, "may", _nobody_may):
            page = self.page("/notes/ci/pipelines?panel=1")
        form = page.one("ls-tab__file").one(tag="form")
        self.assertEqual(form.attrs["target"], "_blank")


class RouteTests(_Filing):
    """The route the button posts to: it calls the filler's draft function with what a
    draft is written with, and answers with the address it returns."""

    def test_a_draft_is_the_address_the_function_returns(self):
        response = self.file(text="the runners lost their disk\nmoved to the spare")
        self.assertEqual((response.status_code, response.headers["Location"]),
                         (303, ADDRESS))

    def test_the_function_is_handed_what_a_draft_is_written_with(self):
        self.file(kind="seen", note="{error} since the runner moved\nsecond line")
        (handed,) = self.handed
        self.assertEqual((handed["path"], handed["kind"], handed["slug"]),
                         ("/ci/pipelines", "seen", ""))
        # the words written out, as a line is: a status's braces as its word and sign
        self.assertEqual(handed["words"],
                         "error ⛔ since the runner moved\nsecond line")
        self.assertEqual(handed["notes_said"], "http://localhost/notes/ci/pipelines")
        self.assertEqual(handed["node"].path, "/ci/pipelines")
        self.assertTrue(callable(handed["written_out"]))
        self.assertTrue(callable(handed["details"]))
        # the head's act: what fails at and beneath the node, as the tab lists it
        self.assertEqual(self.parts(), [
            ("/ci/pipelines", "build", ("build failed: error ⛔",)),
            ("/ci/pipelines", "lint", ("lint failed",)),
            ("/ci/pipelines", "gate", ("the gate waits",))])

    def test_the_words_line_breaks_are_newlines_whatever_the_browser_sent(self):
        # a browser sends a textarea's line breaks as CRLF
        self.file(text="the runners lost their disk\r\nmoved to the spare\rfor now")
        (handed,) = self.handed
        self.assertEqual(handed["words"],
                         "the runners lost their disk\nmoved to the spare\nfor now")

    def test_a_part_failing_by_its_own_reading_reads_every_line_of_its_node(self):
        self.file("ci", kind="seen", note="")
        self.assertEqual(self.parts(), [
            ("/ci/jobs", "", ("export failed", "Traceback (most recent call last)")),
            ("/ci/pipelines", "build", ("build failed: error ⛔",)),
            ("/ci/pipelines", "lint", ("lint failed",)),
            ("/ci/pipelines", "gate", ("the gate waits",))])

    def test_a_line_chosen_is_the_one_part_written_out(self):
        self.file(slug="build", text="")
        self.assertEqual(self.parts(),
                         [("/ci/pipelines", "build", ("build failed: error ⛔",))])

    def test_where_nothing_fails_the_part_is_the_node_and_what_it_reads(self):
        self.tree.upsert("/ci/jobs", OK, "export done")
        self.file("ci/jobs", text="")
        self.assertEqual(self.parts(), [("/ci/jobs", "", ("export done",))])

    def test_a_reader_who_may_set_nothing_is_drafted_for(self):
        # the route writes nothing, and the tracker decides who files
        with mock.patch.object(identity.Identity, "may", _nobody_may):
            response = self.file(kind="", slug="build")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.handed[0]["kind"], "")

    def test_nobody_signed_in_is_drafted_for_by_nobody(self):
        anonymous = app_module.app.test_client()
        response = anonymous.post("/draft/ci/pipelines?kind=note",
                                  data={"draft": DEMO, "text": "x"})
        self.assertNotEqual(response.headers.get("Location"), ADDRESS)
        self.assertEqual(self.handed, [])

    def test_it_never_sends_the_browser_where_the_request_says(self):
        response = self.file(text="x", next="https://elsewhere.example.org/")
        self.assertEqual(response.headers["Location"], ADDRESS)
        for answer in ("javascript:alert(1)", "/status/ci", "tracker.example.org/new",
                       "ftp://tracker.example.org/new", "https://", ""):
            with self.subTest(answer=answer):
                self.answer = answer
                response = self.file(text="x")
                self.assertEqual(response.status_code, 502)
                self.assertNotIn("Location", response.headers)
                self.assertIn("not an http or https address",
                              parse(response.get_data(as_text=True)).text())

    def test_what_cannot_be_drafted_is_said_in_the_new_tab(self):
        def said(response: Any) -> str:
            self.assertNotIn("Location", response.headers)
            return parse(response.get_data(as_text=True)).text()

        response = self.file(package="no.such.package", text="x")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no.such.package", said(response))
        response = self.file("ci/nothing", text="x")
        self.assertEqual(response.status_code, 404)
        self.assertIn("No node stands at /ci/nothing", said(response))
        response = self.file(kind="sorted", text="x")
        self.assertEqual(response.status_code, 400)
        response = self.file(slug="gone", text="x")
        self.assertEqual(response.status_code, 409)
        self.assertIn("no longer reported", said(response))
        self.answer = None
        response = self.file(text="x")
        self.assertEqual(response.status_code, 200)
        self.assertIn("nothing to draft", said(response))
        self.answer = RuntimeError("the tracker's form moved")
        with self.assertLogs("little_sister", level="ERROR"):
            response = self.file(text="x")
        self.assertEqual(response.status_code, 502)
        self.assertIn("could not draft this", said(response))

    def test_a_refusal_leads_back_to_the_notes_tab(self):
        response = self.file(slug="gone", text="x")
        links = [link.attrs["href"]
                 for link in parse(response.get_data(as_text=True)).all(tag="a")]
        self.assertIn("/notes/ci/pipelines", links)


class SuiteFillerTests(_Filing):
    """The suite's filler drafts from the words with the promise alone: the keywords a
    draft function is handed, nothing read off the node."""

    def setUp(self) -> None:
        super().setUp()
        slots.forget_fillers()
        slots.register("notes.actions", DEMO, BUTTON, draft=draft_issue)

    def drafted(self, response: Any) -> dict[str, str]:
        self.assertEqual(response.status_code, 303)
        address = urlsplit(response.headers["Location"])
        self.assertEqual((address.scheme, address.netloc, address.path),
                         ("https", "tracker.example.org", "/new"))
        return {key: value[0] for key, value in parse_qs(address.query).items()}

    def test_its_title_is_the_path_and_the_words_first_line_its_body_the_words(self):
        draft = self.drafted(self.file(
            kind="seen", note="The runners lost their disk\nMoved to the spare."))
        self.assertEqual(draft["title"], "/ci/pipelines: The runners lost their disk")
        self.assertTrue(draft["body"].startswith(
            "The runners lost their disk\nMoved to the spare.\n\n"), draft["body"])
        self.assertIn("build failed: error ⛔", draft["body"])
        self.assertTrue(draft["body"].endswith("http://localhost/notes/ci/pipelines"))

    def test_without_words_its_title_says_what_the_part_reads(self):
        draft = self.drafted(self.file(slug="lint", text=""))
        self.assertEqual(draft["title"], "/ci/pipelines: lint failed")
        draft = self.drafted(self.file("ci", kind="seen", note=""))
        self.assertEqual(draft["title"],
                         "/ci: 4 failures — /ci/jobs: export failed")
