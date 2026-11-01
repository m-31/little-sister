"""A node's Notes tab as the place to act (ADR-0145): what fails, the line on what
came before, what stands, the form — a kind chosen, set on what it may be set on, its
words carried across, a refusal coming back to the tab — and what came before, an act
one entry wherever it was made; and the Copy document's newest note with words."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import identity, instants
from little_sister.notes import Context, Entry, Note, NoteBook
from little_sister.notes_tab import (
    KINDS,
    KINDS_BY_NAME,
    NOTE,
    OWN_PART,
    Shown,
    Target,
    before,
    opens_each_on,
    opens_on,
    shown,
    targets,
)
from little_sister.pins import DONE, MAINTENANCE, SEEN, SILENCED
from little_sister.reasons import Entry as Line
from little_sister.reasons import ReasonError, _check_declared
from little_sister.render import links_of
from little_sister.status import StatusCode
from little_sister.tree import ENDED_HAND, ENDED_RECOVERY, StatusTree
from tests.page_tree import Element, parse

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR


def _utc(*moment: int) -> datetime:
    return datetime(*moment, tzinfo=UTC)


def _note(path: str, text: str, at: datetime, *, slug: str = "", pin: str = "",
          kind: str = "", ended: datetime | None = None, why: str = "",
          made: str = "", by: str = "ada") -> Note:
    return Note(path=path, slug=slug, text=text, created_at=at, created_by=by,
                set_at=at, set_by=by, pin=pin, kind=kind, ended_at=ended,
                ended=why, at=made)


class KindsTests(TestCase):
    """Decision 2: the form's kinds are a list, in the choice's order, each its route,
    its permission and its words — *Done* one more entry, between *Note* and *Seen*
    (ADR-0146)."""

    def test_the_kinds_in_their_order_each_asking_the_permission_of_its_name(self):
        self.assertEqual([kind.name for kind in KINDS],
                         [NOTE, DONE, SEEN, SILENCED, MAINTENANCE])
        self.assertEqual({kind.permission for kind in KINDS}, identity.PERMISSIONS)
        self.assertEqual([kind.name for kind in KINDS if kind.on_failures],
                         [SEEN, SILENCED])
        # ADR-0144 decision 1: a silence is set on any part that could take it later
        self.assertEqual([kind.name for kind in KINDS if kind.on_parts], [SILENCED])
        # and maintenance holds while a window of it is open, which ends too
        # (ADR-0150): no pin of it expires
        maintenance = KINDS_BY_NAME[MAINTENANCE].does
        self.assertIn("while a window of it is open", maintenance)
        self.assertNotIn("expires", maintenance)
        self.assertIn("from its next failure", KINDS_BY_NAME[SILENCED].does)
        self.assertEqual(KINDS_BY_NAME[NOTE].endpoint, "notes")


class TargetsTests(TestCase):
    """What each kind is set on (decision 2): a note and maintenance on the node or
    any of its lines, maintenance but where a pin of its stands; *Seen* on what fails
    now — the head's act, and each failing line of the node; *Silence* on the head's
    act and, beside it, on every part that could take one later (ADR-0144 decision
    1)."""

    LINES: ClassVar = [("build", "build failed"), ("docs", "docs built")]

    def test_a_note_and_maintenance_on_the_node_or_a_line(self):
        note = targets(KINDS_BY_NAME[NOTE], self.LINES, [], here="/ci/pipelines")
        self.assertEqual(note, (Target(), Target("build", "build failed"),
                                Target("docs", "docs built")))
        held = targets(KINDS_BY_NAME[MAINTENANCE], self.LINES, [],
                       here="/ci/pipelines", held=["", "docs"])
        self.assertEqual(held, (Target("build", "build failed"),))

    def test_seen_on_the_head_s_act_and_each_failing_line(self):
        fails = [("/ci/pipelines", "build"), ("/ci/jobs", "")]
        seen = targets(KINDS_BY_NAME[SEEN], self.LINES, fails, here="/ci/pipelines")
        self.assertEqual(seen, (Target(act=2), Target("build", "build failed")))
        # one failure, a line of the node: the line alone
        self.assertEqual(targets(KINDS_BY_NAME[SEEN], self.LINES,
                                 [("/ci/pipelines", "build")], here="/ci/pipelines"),
                         (Target("build", "build failed"),))
        # its own failure alone
        self.assertEqual(targets(KINDS_BY_NAME[SILENCED], [], [("/ci/jobs", "")],
                                 here="/ci/jobs"), (Target(act=1, own=True),))
        # nothing fails: nothing to set it on
        self.assertEqual(targets(KINDS_BY_NAME[SEEN], self.LINES, [],
                                 here="/ci/pipelines"), ())

    def test_silence_on_every_part_that_could_take_one_beside_the_head_s_act(self):
        silence = KINDS_BY_NAME[SILENCED]
        fails = [("/ci/pipelines", "build"), ("/ci/jobs", "")]
        # every line but those held — docs, which builds, among them — the node's
        # own part held where its lines are members
        self.assertEqual(
            targets(silence, self.LINES, fails, here="/ci/pipelines", held=[""]),
            (Target(act=2), Target("build", "build failed"),
             Target("docs", "docs built")))
        self.assertEqual(targets(silence, self.LINES, [], here="/ci/pipelines",
                                 held=["", "build"]), (Target("docs", "docs built"),))
        # a node that reads by itself: the node where nothing fails, the act alone
        # where the act is its own failure, and its own part beside any other act,
        # sending a value no slug can be
        self.assertEqual(targets(silence, [], [], here="/ci/jobs"), (Target(),))
        self.assertEqual(targets(silence, [], [("/ci/jobs", "")], here="/ci/jobs"),
                         (Target(act=1, own=True),))
        beside = targets(silence, [], [("/ci/jobs/export", "")], here="/ci/jobs")
        self.assertEqual(beside, (Target(act=1), Target(own=True)))
        self.assertEqual([target.value for target in beside], ["", OWN_PART])
        with self.assertRaises(ReasonError):
            _check_declared(OWN_PART)
        self.assertEqual(targets(silence, [], [("/ci/jobs/export", "")],
                                 here="/ci/jobs", held=[""]), (Target(act=1),))
        # a refused choice of its own part stays a choice, held since or not
        self.assertEqual(targets(silence, [], [], here="/ci/jobs", held=[""],
                                 keep=OWN_PART), (Target(own=True),))


class OpensOnTests(TestCase):
    """Which kind the form opens on (decision 2): the one asked, where offered;
    *Seen* where something the ringed check would mark fails at the part it opens on,
    *Note* elsewhere; the first offered where that is not — and every kind's *On* on
    the line it opens on, where the kind may be set on it."""

    OFFERED: ClassVar = {NOTE: (Target(), Target("build", "b"), Target("docs", "d")),
                         SEEN: (Target(act=2), Target("build", "b")),
                         MAINTENANCE: (Target(), Target("build", "b"))}

    def test_seen_where_something_fails_at_the_part_and_note_elsewhere(self):
        self.assertEqual(opens_on(self.OFFERED, failing=True), (SEEN, ""))
        self.assertEqual(opens_on(self.OFFERED, line="build", failing=True),
                         (SEEN, "build"))
        self.assertEqual(opens_on(self.OFFERED, line="docs"), (NOTE, "docs"))
        self.assertEqual(opens_on(self.OFFERED), (NOTE, ""))

    def test_the_kind_asked_where_it_is_offered(self):
        self.assertEqual(opens_on(self.OFFERED, asked=NOTE, line="build",
                                  failing=True), (NOTE, "build"))
        self.assertEqual(opens_on(self.OFFERED, asked=MAINTENANCE, line="docs"),
                         (MAINTENANCE, ""), "a line it may not be set on: its first")
        self.assertEqual(opens_on(self.OFFERED, asked=SILENCED, failing=True),
                         (SEEN, ""), "one not offered is not asked")

    def test_the_first_offered_where_the_one_it_would_open_on_is_not(self):
        no_seen = {NOTE: self.OFFERED[NOTE], MAINTENANCE: self.OFFERED[MAINTENANCE]}
        self.assertEqual(opens_on(no_seen, failing=True), (NOTE, ""))
        only = {MAINTENANCE: self.OFFERED[MAINTENANCE]}
        self.assertEqual(opens_on(only), (MAINTENANCE, ""))
        self.assertEqual(opens_on({}), ("", ""))

    def test_the_line_it_opens_on_is_every_kind_s_choice_that_may_be_set_on_it(self):
        # so that a change of kind keeps it, as it keeps a part chosen after
        self.assertEqual(opens_each_on(self.OFFERED, line="build"),
                         {NOTE: "build", SEEN: "build", MAINTENANCE: "build"})
        self.assertEqual(opens_each_on(self.OFFERED, line="docs"),
                         {NOTE: "docs", SEEN: "", MAINTENANCE: ""},
                         "a kind that may not be set on it: its first")
        self.assertEqual(opens_each_on(self.OFFERED),
                         {NOTE: "", SEEN: "", MAINTENANCE: ""})
        held = {MAINTENANCE: (Target("build", "b"),)}
        self.assertEqual(opens_each_on(held, line="docs"), {MAINTENANCE: "build"})
        self.assertEqual(opens_each_on({}), {})
        # a node's own part beside a head's act is chosen by what its choice sends
        beside = {SILENCED: (Target(act=2), Target(own=True))}
        self.assertEqual(opens_each_on(beside, line=OWN_PART), {SILENCED: OWN_PART})
        self.assertEqual(opens_on(beside, asked=SILENCED, line=OWN_PART),
                         (SILENCED, OWN_PART))


class ShownTests(TestCase):
    """What an entry says (decision 6): its kind and word, its parts by their lines,
    how many the act had, from when to when and why it ended."""

    def _shown(self, *entries: Entry, stands: Any = lambda note: False,
               act_size: Any = lambda pin: 0) -> tuple[Shown, ...]:
        return shown(entries, here="/ci/pipelines",
                     line_now=lambda at, slug: {"build": "build failed"}.get(slug),
                     stands=stands, editable=lambda note: True, act_size=act_size)

    def test_a_note_of_its_own(self):
        (one,) = self._shown(Entry((_note("/ci/pipelines", "hi", _utc(2026, 1, 1),
                                          slug="build"),)))
        self.assertEqual((one.kind, one.word, one.alone.line, one.alone.reported,
                          one.editable, one.in_all), (NOTE, "Note", "build failed",
                                                     True, True, 1))

    def test_an_act_its_parts_its_size_and_its_last_end(self):
        pin = instants.stamp(_utc(2026, 1, 1))
        first = _note("/ci/pipelines", "We know", _utc(2026, 1, 1), slug="build",
                      pin=pin, kind=SEEN, ended=_utc(2026, 1, 1, 2), why=ENDED_HAND)
        second = _note("/ci/pipelines", "We know", _utc(2026, 1, 1, 0, 0, 0, 1),
                       slug="gone", pin=pin, kind=SEEN, ended=_utc(2026, 1, 1, 5),
                       why=ENDED_RECOVERY)
        (act,) = self._shown(Entry((first, second)), act_size=lambda _pin: 3)
        self.assertEqual((act.kind, act.word, act.in_all, act.alone), (SEEN, "Seen", 3,
                                                                       None))
        self.assertEqual((act.ended_at, act.ended, act.lasted),
                         (_utc(2026, 1, 1, 5), ENDED_RECOVERY, "5h"))
        self.assertEqual([(part.line, part.reported) for part in act.parts],
                         [("build failed", True), ("", False)])
        self.assertFalse(act.editable, "a pin's record is changed with its pin")

    def test_standing_while_any_of_its_pins_stands_and_an_end_unknown(self):
        pin = instants.stamp(_utc(2026, 1, 1))
        notes = (_note("/ci/pipelines", "", _utc(2026, 1, 1), slug="build", pin=pin,
                       kind=MAINTENANCE, ended=_utc(2026, 1, 2), why=ENDED_HAND),
                 _note("/ci/pipelines", "", _utc(2026, 1, 1, 0, 0, 0, 1),
                       slug="docs", pin=pin, kind=MAINTENANCE))
        (act,) = self._shown(Entry(notes), stands=lambda note: note.slug == "docs")
        self.assertTrue(act.standing)
        self.assertIsNone(act.ended_at, "its end is the last of its pins'")

    def test_a_pin_s_note_written_before_it_kept_its_kind_says_what_it_said(self):
        (old,) = self._shown(Entry((_note("/ci/pipelines", "old", _utc(2025, 1, 1),
                                          pin="2025-01-01T00:00:00Z"),)))
        self.assertEqual((old.kind, old.word), ("", "Note"))


class BeforeTests(TestCase):
    """The line on what came before (decision 7)."""

    def test_counts_since_the_oldest_the_last_pin_and_the_links(self):
        pin = instants.stamp(_utc(2026, 3, 1))
        entries = (
            Entry((_note("/db", "a [runbook](https://wiki/run) and "
                               "[OPS-1](https://t/OPS-1)", _utc(2026, 4, 1)),)),
            Entry((_note("/db", "see https://t/OPS-1 again", _utc(2026, 3, 1),
                         pin=pin, kind=SEEN, ended=_utc(2026, 3, 2),
                         why=ENDED_RECOVERY),)),
            Entry((_note("/db", "[old](https://t/OLD) [four](https://t/4)",
                         _utc(2026, 2, 1)),)),
        )
        said = shown(entries, here="/db", line_now=lambda at, slug: None,
                     stands=lambda note: False, editable=lambda note: False,
                     act_size=lambda pin: 1)
        line = before(said, said)
        self.assertEqual((line.handled, line.noted, line.since),
                         (1, 2, _utc(2026, 2, 1)))
        assert line.last is not None
        self.assertEqual(line.last.kind, SEEN)
        self.assertEqual(line.links, (("https://wiki/run", "runbook"),
                                      ("https://t/OPS-1", "OPS-1"),
                                      ("https://t/OLD", "old")),
                         "newest first, each once, three at most")

    def test_nothing_before_says_nothing(self):
        line = before((), ())
        self.assertEqual((line.handled, line.noted, line.since, line.last,
                          line.links), (0, 0, None, None, ()))


class LinksOfTests(TestCase):
    """Decision 7's tickets: every link a note's words carry, by its own words; a key
    written without a link is none."""

    def test_a_link_a_bare_address_and_what_is_none(self):
        self.assertEqual(
            links_of("Filed [OPS-4411](https://t.example/OPS-4411), see "
                     "https://ci.example/run/7 — and OPS-12, `https://in.code`, "
                     "[the handbook](handbook#restore) and [above](#top)."),
            [("https://t.example/OPS-4411", "OPS-4411"),
             ("https://ci.example/run/7", "https://ci.example/run/7")])


class _Tab(TestCase):
    """A branch, `/ci`, over a node whose lines are members, three of them failing,
    and a node failing by its own reading; signed in as the suite's admin, the tree
    telling the notes of every pin it ends, as the start wires it."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        self.book = NoteBook()
        self.tree.on_pin_end(self.book.pin_ended)
        for patched in (mock.patch.object(app_module, "status_tree", self.tree),
                        mock.patch.object(app_module, "notes_book", self.book)):
            patched.start()
            self.addCleanup(patched.stop)
        self.tree.upsert("/ci/pipelines", ERROR, [
            Line("build", "build failed", code=ERROR),
            Line("lint", "lint failed", code=ERROR),
            Line("gate", "the gate waits", code=WARN),
            Line("docs", "docs built", code=OK)], members=True)
        self.tree.upsert("/ci/jobs", ERROR, "export failed")
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def kinds(self, page: Element) -> list[str]:
        return [form.attrs["data-kind"] for form in page.all("ls-kind-form")]

    def form(self, page: Element, kind: str) -> Element:
        (found,) = [form for form in page.all("ls-kind-form")
                    if form.attrs["data-kind"] == kind]
        return found

    def chosen(self, page: Element) -> list[str]:
        return [box.attrs["value"] for box in page.all(tag="input")
                if box.attrs.get("name") == "tab-kind" and "checked" in box.attrs]

    def options(self, form: Element) -> dict[str, bool]:
        (on,) = [select for select in form.all(tag="select")
                 if select.attrs.get("name") == "slug"]
        return {box.attrs["value"]: "selected" in box.attrs
                for box in on.all(tag="option")}

    def fields(self, form: Element) -> dict[str, str]:
        return {box.attrs["name"]: box.attrs.get("value", "")
                for box in form.all(tag="input") if box.attrs.get("type") == "hidden"}


class WhatFailsAndStandsTests(_Tab):
    """Decision 1: what fails at and beneath the node, each part linked, and what
    stands — the pins above it, its own blocks and its lines', and on a branch what
    is handled beneath it — with *Edit* and *Clear* for whoever may."""

    def test_what_fails_lists_the_parts_the_ringed_check_would_mark(self):
        fails = self.page("/notes/ci").one("ls-tab__fails")
        self.assertEqual([link.attrs["href"] for link in fails.all(tag="a")],
                         ["/status/ci/jobs",
                          "/status/ci/pipelines?reason=build#pinned-reason",
                          "/status/ci/pipelines?reason=lint#pinned-reason",
                          "/status/ci/pipelines?reason=gate#pinned-reason"])
        self.tree.upsert("/ci/jobs", OK, "export done")
        self.tree.upsert("/ci/pipelines", OK, [Line("build", "build ok", code=OK)],
                         members=True)
        self.assertEqual(self.page("/notes/ci").all("ls-tab__fails"), [])

    def test_what_stands_states_each_block_where_it_is_changed(self):
        later = datetime.now(UTC) + timedelta(days=1)
        seen = self.tree.set_acknowledgment("/ci/pipelines", "build", SEEN, "known",
                                            expires_at=None, set_by="ada")
        self.assertTrue(seen.applied, seen.problem)
        self.tree.set_maintenance("/ci", "moving the runners", expires_at=later,
                                  set_by="ada")
        self.tree.set_entry_maintenance("/ci/pipelines", "lint", "a new linter",
                                        expires_at=later, set_by="ben")
        stands = self.page("/notes/ci/pipelines").one("ls-tab__stands")
        blocks = stands.all("rule-block")
        said = [block.one("rule-block__what").text() for block in blocks]
        # the pins above, then its lines' in the check's order, each as Handled
        # words it away from its line
        self.assertIn("This node is in maintenance from /ci by ada", said[0])
        self.assertIn("build failed — this line is marked seen by ada", said[1])
        self.assertIn("lint failed — this line is also in maintenance on its own",
                      said[2])
        # a pin above is changed where it stands; the node's own are changed here,
        # and come back here
        self.assertEqual(blocks[0].all("rule-block__edit"), [])
        for block in blocks[1:]:
            self.assertEqual(len(block.all("rule-block__edit")), 1)
            self.assertEqual({box.attrs["value"] for box in block.all(tag="input")
                              if box.attrs.get("name") == "next"},
                             {"/notes/ci/pipelines"})

    def test_a_branch_lists_what_is_handled_beneath_it(self):
        later = datetime.now(UTC) + timedelta(days=1)
        self.tree.set_entry_maintenance("/ci/pipelines", "lint", "", expires_at=later,
                                        set_by="ben")
        page = self.page("/notes/ci")
        self.assertEqual(page.one("ls-tab__handled").text(), "1 handled")
        beneath = page.one("ls-tab__beneath")
        self.assertIn("a line of pipelines — lint failed", beneath.text())

    def test_every_id_names_one_element(self):
        # the blocks' editors and the form's fields stand on one page
        later = datetime.now(UTC) + timedelta(days=1)
        self.tree.set_maintenance("/ci/pipelines", "", expires_at=later, set_by="ada")
        self.tree.set_entry_maintenance("/ci/pipelines", "lint", "", expires_at=later,
                                        set_by="ada")
        page = self.page("/notes/ci/pipelines")
        self.assertIn(MAINTENANCE, self.kinds(page))
        ids = [element.attrs["id"] for element in page.walk() if "id" in element.attrs]
        self.assertEqual(len(ids), len(set(ids)),
                         sorted({ident for ident in ids if ids.count(ident) > 1}))

    def test_nothing_stands_says_so(self):
        stands = self.page("/notes/ci/jobs").one("ls-tab__stands")
        self.assertIn("Nothing stands here now", stands.text())


class FormTests(_Tab):
    """Decision 2: one form a kind, under one choice; each kind set on what it may be
    set on; the kind it opens on; and its words carried across."""

    def test_the_kinds_where_something_fails_opening_on_the_head_s_act(self):
        page = self.page("/notes/ci/pipelines")
        self.assertEqual(self.kinds(page), [NOTE, SEEN, SILENCED, MAINTENANCE])
        self.assertEqual(self.chosen(page), [SEEN])
        seen = self.form(page, SEEN)
        self.assertEqual(self.options(seen), {"": True, "build": False, "lint": False,
                                              "gate": False})
        self.assertEqual(seen.attrs["action"], "/pins/seen")
        fields = self.fields(seen)
        self.assertEqual((fields["path"], fields["next"], fields["from"],
                          fields["set_at"]),
                         ("/ci/pipelines", "/notes/ci/pipelines", "notes", ""))
        self.assertEqual(fields["parts"], app_module.parts_digest(
            app_module._failing_parts("/ci/pipelines")))
        self.assertEqual(self.options(self.form(page, NOTE)),
                         {"": True, "build": False, "lint": False, "gate": False,
                          "docs": False})
        # a silence on every line it reports, docs, which builds, among them
        # (ADR-0144 decision 1)
        self.assertEqual(self.options(self.form(page, SILENCED)),
                         {"": True, "build": False, "lint": False, "gate": False,
                          "docs": False})

    def test_silence_and_no_seen_or_done_on_a_part_that_reads_ok(self):
        # ADR-0144 decision 1: a leaf that reads ok is silenced as the node, and a
        # line that does among its node's lines; seen and done stay on what fails
        self.tree.upsert("/ci/jobs", OK, "export done")
        page = self.page("/notes/ci/jobs")
        self.assertEqual(self.kinds(page), [NOTE, SILENCED, MAINTENANCE])
        self.assertEqual(self.chosen(page), [NOTE], "nothing fails: a note")
        silence = self.form(page, SILENCED)
        self.assertEqual(self.options(silence), {"": True})
        self.assertEqual(silence.one(tag="option").text(), "the node")
        self.assertNotIn("parts", self.fields(silence))
        pipelines = self.page("/notes/ci/pipelines?reason=docs")
        self.assertTrue(self.options(self.form(pipelines, SILENCED))["docs"])
        self.assertNotIn("docs", self.options(self.form(pipelines, SEEN)))
        self.assertNotIn(DONE, self.kinds(pipelines))
        # a part in maintenance, or held already, is not offered
        later = datetime.now(UTC) + timedelta(days=1)
        self.tree.set_entry_maintenance("/ci/pipelines", "docs", "", expires_at=later,
                                        set_by="ada")
        self.tree.set_acknowledgment("/ci/pipelines", "gate", SEEN, "",
                                     expires_at=None, set_by="ada")
        self.assertEqual(
            set(self.options(self.form(self.page("/notes/ci/pipelines"), SILENCED))),
            {"", "build", "lint"})

    def test_a_node_that_reads_by_itself_beside_failures_beneath_it(self):
        # its own part, beside the head's act over what fails beneath, sends a value
        # of its own: the act takes the empty one and the digest
        self.tree.upsert("/ci", OK, "both pipelines ran")
        page = self.page("/notes/ci")
        silence = self.form(page, SILENCED)
        self.assertEqual(self.options(silence), {"": True, OWN_PART: False})
        self.assertEqual([option.text() for option in silence.all(tag="option")],
                         ["all 4 failures listed above, each its own", "its own part"])
        self.assertEqual(set(self.options(self.form(page, SEEN))), {""})

    def test_a_line_and_a_kind_asked_open_it(self):
        page = self.page("/notes/ci/pipelines?reason=lint")
        self.assertEqual(self.chosen(page), [SEEN])
        # the line it opens on is every kind's choice, so a change of kind keeps it
        for kind in (NOTE, SEEN, SILENCED, MAINTENANCE):
            self.assertTrue(self.options(self.form(page, kind))["lint"], kind)
        page = self.page("/notes/ci/pipelines?reason=docs")
        self.assertEqual(self.chosen(page), [NOTE], "docs fails not: a note")
        self.assertTrue(self.options(self.form(page, NOTE))["docs"])
        self.assertTrue(self.options(self.form(page, MAINTENANCE))["docs"])
        self.assertTrue(self.options(self.form(page, SEEN))[""],
                        "a kind that may not be set on it: its first, the head's act")
        page = self.page("/notes/ci/pipelines?kind=maintenance&reason=gate")
        self.assertEqual(self.chosen(page), [MAINTENANCE])
        self.assertTrue(self.options(self.form(page, MAINTENANCE))["gate"])

    def test_nothing_failing_offers_no_seen_and_a_pinned_part_a_window_that_joins(self):
        later = datetime.now(UTC) + timedelta(days=1)
        self.tree.upsert("/ci/jobs", OK, "export done")
        entry = self.tree.set_maintenance("/ci/jobs", "", expires_at=later,
                                          set_by="ada").current
        assert entry is not None
        page = self.page("/notes/ci/jobs")
        # ADR-0150, landing 4: a window set on a part an entry stands on joins it,
        # so maintenance is offered there, carrying the entry's token
        self.assertEqual(self.kinds(page), [NOTE, MAINTENANCE])
        self.assertEqual(self.chosen(page), [NOTE], "nothing fails: a note")
        jobs = self.form(page, MAINTENANCE)
        self.assertEqual(self.fields(jobs)["set_at:"], entry.token)
        self.tree.set_entry_maintenance("/ci/pipelines", "lint", "", expires_at=later,
                                        set_by="ada")
        maintenance = self.form(self.page("/notes/ci/pipelines"), MAINTENANCE)
        self.assertEqual(set(self.options(maintenance)),
                         {"", "build", "lint", "gate", "docs"})
        self.assertIn("set_at:lint", self.fields(maintenance))

    def test_whoever_may_set_nothing_reads_without_the_form(self):
        # decision 3: a note is an act with a permission of its own
        with mock.patch.object(identity.Identity, "may",
                               lambda _self, permission: permission == SEEN):
            page = self.page("/notes/ci/pipelines")
            self.assertEqual(self.kinds(page), [SEEN])
            self.assertEqual(self.client.post("/notes/ci/pipelines", data={
                "action": "add", "text": "x"}).status_code, 403)
        with mock.patch.object(identity.Identity, "may",
                               lambda _self, permission: False):
            page = self.page("/notes/ci/pipelines")
            self.assertEqual(page.all("ls-tab__form"), [])
            self.assertEqual(len(page.all("ls-tab__stands")), 1)


class WritesTests(_Tab):
    """Decision 2: a write from the form comes back to the tab, and one it refuses
    comes back with why above the form and the words in it, the kind and the part
    chosen as they were; a head's act whose parts changed lists them anew."""

    def post(self, route: str, **form: str) -> Any:
        return self.client.post(route, data={"action": "set", "set_at": "",
                                             "from": "notes", **form})

    def test_a_line_marked_seen_comes_back_to_the_tab(self):
        digest = app_module.parts_digest(app_module._failing_parts("/ci/pipelines"))
        response = self.post("/pins/seen", path="/ci/pipelines", slug="lint",
                             parts=digest, note="a new rule", duration="",
                             next="/notes/ci/pipelines")
        self.assertEqual(response.headers["Location"], "/notes/ci/pipelines")
        # the line chosen is the act: one seen, not every failure's
        self.assertIsNotNone(self.tree.acknowledgment("/ci/pipelines", "lint"))
        self.assertIsNone(self.tree.acknowledgment("/ci/pipelines", "build"))

    def test_the_head_s_act_from_a_branch_marks_each_part_and_is_one_entry(self):
        digest = app_module.parts_digest(app_module._failing_parts("/ci"))
        self.post("/pins/silenced", path="/ci", slug="", parts=digest,
                  note="GitHub is down", level="ok", deadline="", next="/notes/ci")
        for path, slug in (("/ci/pipelines", "build"), ("/ci/pipelines", "lint"),
                           ("/ci/pipelines", "gate"), ("/ci/jobs", "")):
            self.assertIsNotNone(self.tree.acknowledgment(path, slug), (path, slug))
        # it stands, so its tabs state it among what stands; it ends by hand
        for path, slug in (("/ci/pipelines", "build"), ("/ci/pipelines", "lint"),
                           ("/ci/pipelines", "gate"), ("/ci/jobs", "")):
            self.tree.clear_acknowledgment(path, slug, by="ben")
        (entry,) = self.page("/notes/ci").all("ls-entry")
        self.assertIn("Silenced · 4 parts in one act",
                      entry.one("ls-entry__head").text())
        self.assertEqual(len(entry.one("ls-entry__part-list").all(tag="li")), 4)
        self.assertIn("ended: by hand, by ben", entry.one("ls-note__said").text())
        (part,) = self.page("/notes/ci/jobs").all("ls-entry")
        self.assertIn("Silenced · on the node, one of 4 parts of one act, made on /ci",
                      part.one("ls-entry__head").text())
        (lines,) = self.page("/notes/ci/pipelines").all("ls-entry")
        self.assertIn("3 parts of 4 in one act, made on /ci",
                      lines.one("ls-entry__head").text())

    def test_an_act_says_each_part_s_status_in_its_list(self):
        digest = app_module.parts_digest(app_module._failing_parts("/ci"))
        self.post("/pins/seen", path="/ci", slug="", parts=digest, note="",
                  duration="", next="/notes/ci")
        for path, slug in (("/ci/pipelines", "build"), ("/ci/pipelines", "lint"),
                           ("/ci/pipelines", "gate"), ("/ci/jobs", "")):
            self.tree.clear_acknowledgment(path, slug, by="ben")
        (entry,) = self.page("/notes/ci").all("ls-entry")
        self.assertNotIn(" at ", entry.one("ls-note__said").text(),
                         "each part was seen at its own status")
        parts = [item.text() for item in
                 entry.one("ls-entry__part-list").all(tag="li")]
        self.assertTrue(any("the gate waits at" in part and "warn" in part
                            for part in parts), parts)
        self.assertTrue(any("build failed at" in part and "error" in part
                            for part in parts), parts)

    def test_an_ok_part_silenced_from_the_tab_beside_a_head_s_act(self):
        # ADR-0144 decision 1: the node's own part, which reads ok, alone — though
        # the form carries the head's digest — and a line that builds
        self.tree.upsert("/ci", OK, "both pipelines ran")
        digest = app_module.parts_digest(app_module._failing_parts("/ci"))
        response = self.post("/pins/silenced", path="/ci", slug=OWN_PART,
                             parts=digest, note="the runners flap", level="warn",
                             deadline="2d", next="/notes/ci")
        self.assertEqual(response.headers["Location"], "/notes/ci")
        own = self.tree.acknowledgment("/ci")
        assert own is not None
        self.assertEqual((own.kind, own.level), (SILENCED, WARN))
        self.assertEqual(self.tree.acknowledgments()[1], {})
        self.post("/pins/silenced", path="/ci/pipelines", slug="docs", parts=digest,
                  note="", level="ok", deadline="", next="/notes/ci/pipelines")
        docs = self.tree.acknowledgment("/ci/pipelines", "docs")
        assert docs is not None
        self.assertEqual((docs.kind, docs.status), (SILENCED, None))
        nodes, lines = self.tree.acknowledgments()
        self.assertEqual((set(nodes), set(lines)), ({"/ci"},
                                                    {("/ci/pipelines", "docs")}))
        # a refused one comes back with its own part chosen, not the head's act
        self.tree.clear_acknowledgment("/ci", by="pan")
        response = self.post("/pins/silenced", path="/ci", slug=OWN_PART,
                             parts=digest, note="the runners flap", level="warn",
                             deadline="45d", next="/notes/ci")
        silence = self.form(parse(response.get_data(as_text=True)), SILENCED)
        self.assertEqual([part for part, on in self.options(silence).items() if on],
                         [OWN_PART])
        self.assertIsNone(self.tree.acknowledgment("/ci"))

    def test_a_refusal_comes_back_with_why_and_the_words_as_they_were(self):
        response = self.post("/pins/silenced", path="/ci/pipelines", slug="lint",
                             note="it flaps", level="warn", deadline="31d",
                             next="/notes/ci/pipelines")
        self.assertEqual(response.status_code, 200)
        page = parse(response.get_data(as_text=True))
        refused = page.one("ls-notes__refused")
        self.assertIn("Nothing was saved: your words are below.", refused.text())
        self.assertTrue(refused.within(page.with_id("add-note")))
        self.assertEqual(self.chosen(page), [SILENCED])
        silence = self.form(page, SILENCED)
        self.assertEqual(silence.one(tag="textarea").source(), "it flaps")
        self.assertTrue(self.options(silence)["lint"])
        self.assertEqual([box.attrs.get("value") for box in silence.all(tag="input")
                          if box.attrs.get("name") == "deadline"], ["31d"])
        self.assertEqual([box.attrs["value"] for box in silence.all(tag="input")
                          if box.attrs.get("name") == "level"
                          and "checked" in box.attrs], ["warn"])
        self.assertIsNone(self.tree.acknowledgment("/ci/pipelines", "lint"))

    def test_a_head_s_act_whose_parts_changed_lists_them_anew(self):
        listed = app_module.parts_digest(app_module._failing_parts("/ci"))
        self.tree.upsert("/ci/jobs", OK, "export done")
        response = self.post("/pins/seen", path="/ci", slug="", parts=listed,
                             note="all known", duration="", next="/notes/ci")
        page = parse(response.get_data(as_text=True))
        self.assertIn("What fails here changed since this was opened.",
                      page.one("ls-notes__refused").text())
        self.assertNotIn("/status/ci/jobs", page.one("ls-tab__fails").source() +
                         " ".join(link.attrs["href"]
                                  for link in page.one("ls-tab__fails").all(tag="a")))
        self.assertEqual(self.fields(self.form(page, SEEN))["parts"],
                         app_module.parts_digest(app_module._failing_parts("/ci")))
        self.assertEqual(self.form(page, SEEN).one(tag="textarea").source(),
                         "all known")

    def test_a_pin_set_since_the_tab_was_drawn_is_said_where_it_stands(self):
        later = datetime.now(UTC) + timedelta(days=1)
        self.tree.set_maintenance("/ci/jobs", "", expires_at=later, set_by="ada")
        response = self.post("/pins/maintenance", path="/ci/jobs", slug="",
                             note="mine", duration="2h", next="/notes/ci/jobs")
        page = parse(response.get_data(as_text=True))
        self.assertIn("This node was put in maintenance since this tab was drawn",
                      page.one("ls-notes__refused").text())
        # the part stays chosen, so that sending it again is refused again rather
        # than pinning another part
        chosen = self.options(self.form(page, MAINTENANCE))
        self.assertEqual([slug for slug, on in chosen.items() if on], [""])

    def test_a_line_marked_since_stays_chosen_and_is_refused_again(self):
        later = datetime.now(UTC) + timedelta(days=1)
        self.tree.set_entry_maintenance("/ci/pipelines", "docs", "", expires_at=later,
                                        set_by="ada")
        response = self.post("/pins/maintenance", path="/ci/pipelines", slug="docs",
                             note="mine", duration="2h", next="/notes/ci/pipelines")
        page = parse(response.get_data(as_text=True))
        self.assertIn("This line was put in maintenance since this tab was drawn",
                      page.one("ls-notes__refused").text())
        maintenance = self.form(page, MAINTENANCE)
        self.assertEqual([slug for slug, chosen in self.options(maintenance).items()
                          if chosen], ["docs"])
        self.assertEqual(maintenance.one(tag="textarea").source(), "mine")
        # a seen set on the line since: the line stays chosen, not every failure
        self.tree.set_acknowledgment("/ci/pipelines", "lint", SEEN, "",
                                     expires_at=None, set_by="ada")
        response = self.post("/pins/seen", path="/ci/pipelines", slug="lint",
                             parts="any", note="mine", duration="",
                             next="/notes/ci/pipelines")
        seen = self.form(parse(response.get_data(as_text=True)), SEEN)
        self.assertEqual([slug for slug, chosen in self.options(seen).items()
                          if chosen], ["lint"])


class HistoryLineTests(_Tab):
    """Decision 7, on the page: how often the part was handled and noted since the
    oldest entry, the last time, and the links its notes carry."""

    def test_the_line_on_what_came_before(self):
        self.book.add("/ci/pipelines", "", "Filed [OPS-4411](https://t/OPS-4411)",
                      by="ada", context=Context(), now=_utc(2026, 1, 1))
        write = self.tree.set_acknowledgment("/ci/pipelines", "build", SEEN, "known",
                                             expires_at=None, set_by="ben")
        assert write.current is not None
        self.book.pinned("/ci/pipelines", "build", write.current, Context())
        self.tree.clear_acknowledgment("/ci/pipelines", "build", by="ben")
        line = self.page("/notes/ci/pipelines").one("ls-tab__before")
        self.assertIn("Handled once and noted once here since", line.text())
        self.assertIn("Last time: seen on its line: build failed, by ben", line.text())
        self.assertIn("ended: by hand, by ben", line.text())
        self.assertEqual([(link.attrs["href"], link.text())
                          for link in line.all("ls-before__link")],
                         [("https://t/OPS-4411", "OPS-4411 ↗")])

    def test_nothing_before_draws_no_line(self):
        page = self.page("/notes/ci/pipelines")
        self.assertEqual(page.all("ls-tab__before"), [])
        self.assertIn("Nothing was handled or noted here before.",
                      page.one("ls-notes__none").text())


class CopyTests(_Tab):
    """Decision 8: the Copy document hands over the newest note with words, its pin
    said as the tab's entry says it, and how many entries more the tab lists."""

    def test_the_newest_note_with_words_and_its_pin(self):
        self.book.add("/ci/jobs", "", "older words", by="ada", context=Context(),
                      now=_utc(2026, 1, 1))
        write = self.tree.set_acknowledgment("/ci/jobs", "", SEEN, "We know",
                                             expires_at=None, set_by="ben")
        assert write.current is not None
        self.book.pinned("/ci/jobs", "", write.current, Context())
        self.tree.clear_acknowledgment("/ci/jobs", "", by="ben")
        later = datetime.now(UTC) + timedelta(days=1)
        self.tree.upsert("/ci/jobs", OK, "export done")
        pin = self.tree.set_maintenance("/ci/jobs", "", expires_at=later,
                                        set_by="ada").current
        assert pin is not None
        self.book.pinned("/ci/jobs", "", pin, Context())  # a record without words
        body = self.client.get("/copy/ci/jobs").get_data(as_text=True)
        self.assertIn("☑️ Seen — by ben at error ⛔, from ", body)
        self.assertIn(", ended: by hand, by ben", body)
        self.assertNotIn("on the node", body, "a lone pin of the node says none")
        self.assertIn("We know", body)
        self.assertNotIn("older words", body)
        self.assertIn("2 more on its Notes tab", body)

    def test_an_act_is_on_what_the_tab_s_entry_says_it_is_on(self):
        digest = app_module.parts_digest(app_module._failing_parts("/ci"))
        self.client.post("/pins/seen", data={
            "action": "set", "set_at": "", "from": "notes", "path": "/ci", "slug": "",
            "parts": digest, "note": "Release week", "duration": "",
            "next": "/notes/ci"})
        for path, slug in (("/ci/pipelines", "build"), ("/ci/pipelines", "lint"),
                           ("/ci/pipelines", "gate"), ("/ci/jobs", "")):
            self.tree.clear_acknowledgment(path, slug, by="ben")
        lines = self.client.get("/copy/ci/pipelines").get_data(as_text=True)
        self.assertIn("ended: by hand, by ben — 3 parts of 4 in one act, made on /ci",
                      lines)
        self.assertNotIn("on its line", lines, "no one line stands for three")
        node = self.client.get("/copy/ci/jobs").get_data(as_text=True)
        self.assertIn("ended: by hand, by ben — on the node, one of 4 parts of one "
                      "act, made on /ci", node)
        made = self.client.get("/copy/ci").get_data(as_text=True)
        self.assertIn("ended: by hand, by ben — 4 parts in one act", made)
        self.assertNotIn("made on", made, "made here")


class EventsWordsTests(TestCase):
    """A line's pin's edit is a row of its node (ADR-0145 decision 9), and the Events
    page's chip says it."""

    def test_the_chip_of_an_edit(self):
        row = mock.Mock(cause="line-pin-edited", ended="")
        self.assertEqual(app_module._cause_chip(row), "line's pin edited")
        ended = mock.Mock(cause="pin-ended", ended="clock")
        self.assertEqual(app_module._cause_chip(ended),
                         "maintenance ended · at its end")

