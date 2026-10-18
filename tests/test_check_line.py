"""The grading asks the library for the line (ADR-0126 decision 7), and a deployment
re-words it in the check's own file, over what its type declares (decision 5).

Each class holds one sentence of the record to account. ``Check.line`` renders the
form the grading names — the deployment's ``display:`` over the type's default — over
the reading's record and the words handed to the call, and returns the line with its
text, the record as its data, the reading's subject and the form it was written from.
``display:`` is a common field of every check's YAML, keyed flat by a form's full
name, and one that names what the type does not declare stops the start, naming the
file. A type declares its forms, its words and its fields, and its own defaults are
checked against them when a check is built, so that a typo in a default fails the
type's own tests.
"""
from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from little_sister import app as app_module
from little_sister.checks import (
    CHECK_TYPES,
    Check,
    CheckError,
    Measurement,
    load_checks,
    register,
)
from little_sister.checks.base import CheckResult
from little_sister.engine import Engine
from little_sister.line_template import Declarations
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

HERE = Path(".")
NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
URL = "https://ci.example.org/acme/shop/runs/41"

FORMS: dict[str, object] = {
    "run.verdict": {
        "sentence": "The newest completed run, and its verdict.",
        "text": "[{workflow}]({completed.url}): {verdict}"
                "{? (#{completed.run_number})}"},
    "run.none": {
        "sentence": "No run of the workflow has completed.",
        "text": "{workflow}: no completed run"},
    "run.stale": {
        "sentence": "The newest run passed, longer ago than a rule allows.",
        "text": "{workflow}: passed, but that run started {line.age} ago"
                "{? — {line.why}}"},
}
WORDS: dict[str, object] = {
    "age": {"sentence": "How long ago the run started, as the grading measured it.",
            "example": "2d"},
    "why": {"sentence": "The rule's own sentence, where it has one.",
            "example": "Deploys run nightly."},
}
FIELDS: dict[str, object] = {
    "workflow": {"sentence": "The workflow's name.", "example": "CI"},
    "verdict": {"sentence": "The word the line says for the run's outcome.",
                "example": "passed"},
    "completed.url": {"sentence": "The run's page.", "example": URL},
    "completed.run_number": {"sentence": "The run's number.", "example": 41},
    "completed.started": {"sentence": "When the run started.",
                          "example": "2026-10-11T08:00:00Z"},
}
RECORD: dict[str, Any] = {
    "workflow": "CI", "verdict": "passed",
    "completed": {"url": URL, "run_number": 41, "started": "2026-10-11T08:00:00Z"}}


class _Runs(Check):
    """A type that says its lines through forms, as a package would."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(line_forms=FORMS, line_words=WORDS, line_fields=FIELDS,
                         **kwargs)

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(reason=[
            self.line("run.verdict", reading, slug=f"run-{index}",
                      code=StatusCode.OK)
            for index, reading in enumerate(measurements)])


class _Probe(Check):
    """A type that declares nothing: its lines are its own sentences."""

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _runs(**config: object) -> Check:
    return _Runs.from_config({"path": "/ci", **config}, HERE)


def _reading(record: Mapping[str, Any] | None = None) -> Measurement:
    return Measurement(record=dict(RECORD if record is None else record),
                       subject="acme/shop:ci")


def _loaded(text: str) -> list[Check]:
    """The checks a configuration root holding one file, ``ci.yaml``, loads — with
    ``_Runs`` registered as ``line-runs`` for the while."""
    saved = dict(CHECK_TYPES)
    try:
        register("line-runs")(_Runs)
        with tempfile.TemporaryDirectory() as directory:
            checks = Path(directory) / "checks"
            checks.mkdir()
            (checks / "ci.yaml").write_text(text, encoding="utf-8")
            return load_checks(Path(directory))
    finally:
        CHECK_TYPES.clear()
        CHECK_TYPES.update(saved)


def _berlin() -> Any:
    return mock.patch("little_sister.config.config",
                      mock.Mock(tzinfo=ZoneInfo("Europe/Berlin"),
                                time_format="%Y-%m-%d %H:%M"))


class LineTests(TestCase):
    """``Check.line(form, reading, …)`` renders the form's text over the reading's
    record and the words, and returns the ``Entry`` with its text, the record as its
    ``data``, the reading's subject and the form (decision 7)."""

    def test_it_renders_the_types_default(self) -> None:
        entry = _runs().line("run.verdict", _reading(), slug="run")
        self.assertEqual(entry.text, f"[CI]({URL}): passed (#41)")

    def test_it_hands_back_the_line_with_its_record_subject_and_form(self) -> None:
        reading = _reading()
        entry = _runs().line("run.verdict", reading, slug="run",
                             code=StatusCode.WARN, running=True)
        self.assertEqual(
            (entry.slug, entry.code, entry.running, entry.subject, entry.form),
            ("run", StatusCode.WARN, True, "acme/shop:ci", "run.verdict"))
        self.assertEqual(entry.data, dict(reading.record))

    def test_the_grading_chooses_the_form(self) -> None:
        reading = _reading({"workflow": "CI", "verdict": None, "completed": None})
        entry = _runs().line("run.none", reading, slug="run")
        self.assertEqual((entry.text, entry.form),
                         ("CI: no completed run", "run.none"))

    def test_the_words_are_handed_over_with_the_call(self) -> None:
        entry = _runs().line("run.stale", _reading(), slug="run",
                             words={"age": "2d", "why": "Deploys run nightly."})
        self.assertEqual(entry.text,
                         "CI: passed, but that run started 2d ago — Deploys run "
                         "nightly.")

    def test_and_live_for_the_call_alone(self) -> None:
        check, reading = _runs(), _reading()
        entry = check.line("run.stale", reading, slug="run", words={"age": "2d"})
        self.assertEqual(entry.text, "CI: passed, but that run started 2d ago")
        self.assertEqual(entry.data, dict(reading.record))
        self.assertEqual(check.line("run.stale", reading, slug="run").text,
                         "CI: passed, but that run started — ago")

    def test_graded_again_it_says_the_same(self) -> None:
        check, reading = _runs(), _reading()
        self.assertEqual(check.line("run.verdict", reading, slug="run"),
                         check.line("run.verdict", reading, slug="run"))

    def test_through_the_grading_and_the_seam(self) -> None:
        reading = _reading()
        (entry,) = _runs().grade([reading], NOW).reason_entries
        self.assertEqual((entry.text, entry.form, entry.subject),
                         (f"[CI]({URL}): passed (#41)", "run.verdict",
                          "acme/shop:ci"))
        self.assertEqual(entry.data, dict(reading.record))

    def test_a_line_for_the_record_alone_is_asked_for_the_same_way(self) -> None:
        line = _runs().line("run.verdict", _reading(), slug="run",
                            code=StatusCode.ERROR)
        result = CheckResult(StatusCode.OK, for_record=[line])
        (kept,) = result.for_record
        self.assertEqual((kept.text, kept.code, kept.form),
                         (f"[CI]({URL}): passed (#41)", StatusCode.ERROR,
                          "run.verdict"))

    def test_a_form_the_type_does_not_declare_is_refused(self) -> None:
        with self.assertRaises(CheckError) as caught:
            _runs().line("run.verdcit", _reading(), slug="run")
        self.assertIn("'run.verdcit'", str(caught.exception))
        self.assertIn("run.verdict, run.none, run.stale", str(caught.exception))

    def test_so_is_a_word_it_does_not_declare(self) -> None:
        with self.assertRaises(CheckError) as caught:
            _runs().line("run.stale", _reading(), slug="run", words={"agee": "2d"})
        self.assertIn("'agee'", str(caught.exception))

    def test_a_word_is_text_a_number_or_a_flag(self) -> None:
        check = _runs()
        for value in ("2d", 2, 2.5, True, False, None):
            with self.subTest(value=value):
                check.line("run.stale", _reading(), slug="run", words={"age": value})
        for value in (NOW, ["2d"], {"days": 2}, b"2d"):
            with self.subTest(value=value):
                with self.assertRaises(CheckError) as caught:
                    check.line("run.stale", _reading(), slug="run",
                               words={"age": value})
                self.assertIn("'age'", str(caught.exception))

    def test_a_type_that_declares_no_form_has_none_to_name(self) -> None:
        check = _Probe.from_config({"path": "/svc"}, HERE)
        self.assertEqual(check.line_declarations, Declarations())
        with self.assertRaises(CheckError) as caught:
            check.line("run.verdict", _reading(), slug="run")
        self.assertIn("declares no form", str(caught.exception))


class DisplayTests(TestCase):
    """A deployment re-words a form in the check's own YAML, in ``display:`` beside
    ``subnodes:`` and ``measures:``, keyed flat by the form's full name; and
    ``{line.default}`` is the type's default (decision 5)."""

    def test_a_display_block_rewords_a_form(self) -> None:
        check = _runs(display={"run.verdict": "{workflow} {verdict}"})
        self.assertEqual(check.line("run.verdict", _reading(), slug="run").text,
                         "CI passed")

    def test_the_other_forms_keep_their_default(self) -> None:
        check = _runs(display={"run.verdict": "{workflow} {verdict}"})
        self.assertEqual(check.line("run.none", _reading(), slug="run").text,
                         "CI: no completed run")

    def test_line_default_is_the_types_text(self) -> None:
        check = _runs(display={"run.verdict": "{line.default} — call the on-call"})
        self.assertEqual(check.line("run.verdict", _reading(), slug="run").text,
                         f"[CI]({URL}): passed (#41) — call the on-call")

    def test_and_over_the_same_words(self) -> None:
        check = _runs(display={"run.stale": "**{line.default}**"})
        self.assertEqual(
            check.line("run.stale", _reading(), slug="run", words={"age": "2d"}).text,
            "**CI: passed, but that run started 2d ago**")

    def test_a_deployment_may_say_when_the_run_started(self) -> None:
        check = _runs(display={
            "run.verdict": "{line.default}{? — started {completed.started}}"})
        reading = _reading()
        with _berlin():
            text = check.line("run.verdict", reading, slug="run").text
        self.assertEqual(text, f"[CI]({URL}): passed (#41) — started 2026-10-11 10:00")

    def test_it_is_read_from_the_checks_own_file(self) -> None:
        (check,) = _loaded("type: line-runs\npath: /ci\ndisplay:\n"
                           "  run.verdict: '{workflow}: {verdict} — see the runbook'\n")
        self.assertEqual(check.line("run.verdict", _reading(), slug="run").text,
                         "CI: passed — see the runbook")

    def test_an_absent_or_empty_block_rewords_nothing(self) -> None:
        for display in (None, {}):
            with self.subTest(display=display):
                check = _runs(display=display)
                self.assertEqual(check.line("run.verdict", _reading(), slug="run").text,
                                 f"[CI]({URL}): passed (#41)")

    def test_every_type_reads_it(self) -> None:
        check = _Probe.from_config({"path": "/svc", "display": {}}, HERE)
        self.assertEqual(check.line_declarations, Declarations())
        with self.assertRaises(CheckError) as caught:
            _Probe.from_config({"path": "/svc", "display": {"run.verdict": "x"}}, HERE)
        self.assertIn("declares no form", str(caught.exception))


class DisplayRefusedTests(TestCase):
    """A ``display:`` block that names a form, a field or a word the type does not
    declare, or that the notation cannot read, stops the start naming the file, as
    every other configuration error does (decision 5)."""

    SHAPES: ClassVar[dict[str, tuple[str, str]]] = {
        "a form the type does not have": (
            "display:\n  run.verdcit: '{workflow}'\n", "run.verdcit"),
        "a field it does not declare": (
            "display:\n  run.verdict: '{workflw}'\n", "workflw"),
        "a word it does not declare": (
            "display:\n  run.verdict: '{line.whyy}'\n", "line.whyy"),
        "a segment that never ends": (
            "display:\n  run.verdict: '{? {workflow}'\n", "never ends"),
        "a brace that closes nothing": (
            "display:\n  run.verdict: 'a } b'\n", "closes nothing"),
        "a list": ("display:\n  - run.verdict\n", "list"),
        "a name that is a number": ("display:\n  5: '{workflow}'\n", "names 5"),
        "text": ("display: '{workflow}'\n", "str"),
        "a template that is no text": ("display:\n  run.verdict: 5\n", "run.verdict"),
        "an empty template": ("display:\n  run.verdict: ''\n", "run.verdict"),
        "a null template": ("display:\n  run.verdict:\n", "run.verdict"),
        "a block nested by the name's parts": (
            "display:\n  run:\n    verdict: '{workflow}'\n", "as 'run.verdict'"),
    }

    def test_every_one_stops_the_start_naming_the_file(self) -> None:
        for shape, (block, named) in self.SHAPES.items():
            with self.subTest(shape):
                with self.assertRaises(CheckError) as caught:
                    _loaded("type: line-runs\npath: /ci\n" + block)
                message = str(caught.exception)
                self.assertTrue(message.startswith("ci.yaml: "), message)
                self.assertIn("display", message)
                self.assertIn(named, message)

    def test_the_refusal_says_what_the_type_declares(self) -> None:
        with self.assertRaises(CheckError) as caught:
            _runs(display={"run.verdict": "{workflw}"})
        message = str(caught.exception)
        self.assertIn("display.run.verdict", message)
        self.assertIn("completed.run_number, completed.started, completed.url, "
                      "verdict, workflow", message)

    def test_and_where_in_the_template_it_stopped(self) -> None:
        with self.assertRaises(CheckError) as caught:
            _runs(display={"run.verdict": "{workflow} {? on {branch"})
        self.assertIn("display.run.verdict", str(caught.exception))
        self.assertIn("character 18", str(caught.exception))


class DeclarationTests(TestCase):
    """A type declares its forms — each a name, one sentence and its default text —
    and the words and fields a template may name — each a name, one sentence and an
    example — and its defaults are checked against them when a check is built
    (decisions 5 and 7)."""

    @staticmethod
    def _declaring(forms: object = None, words: object = None,
                   fields: object = None) -> Check:
        class _Declared(Check):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(line_forms=forms, line_words=words,
                                 line_fields=fields, **kwargs)

            def measure(self) -> Sequence[Measurement]:
                return ()

            def grade(self, measurements: Sequence[Measurement],
                      now: datetime) -> CheckResult:
                return CheckResult(StatusCode.OK)

        return _Declared.from_config({"path": "/svc"}, HERE)

    def _refused(self, **declared: object) -> str:
        with self.assertRaises(CheckError) as caught:
            self._declaring(**declared)
        return str(caught.exception)

    def test_the_declarations_reach_the_check_in_their_order(self) -> None:
        declared = _runs().line_declarations
        self.assertEqual([form.name for form in declared.forms],
                         ["run.verdict", "run.none", "run.stale"])
        self.assertEqual(declared.forms[1].sentence,
                         "No run of the workflow has completed.")
        self.assertEqual(declared.forms[1].text, "{workflow}: no completed run")
        self.assertEqual([(word.name, word.example) for word in declared.words],
                         [("age", "2d"), ("why", "Deploys run nightly.")])
        self.assertEqual([field.name for field in declared.fields], list(FIELDS))

    def test_an_example_is_written_as_the_page_writes_a_value(self) -> None:
        fields = {"count": {"sentence": "A count.", "example": 41},
                  "flag": {"sentence": "A flag.", "example": True},
                  "names": {"sentence": "Names.", "example": ["a", "b"]}}
        declared = self._declaring(fields=fields).line_declarations
        self.assertEqual([field.example for field in declared.fields],
                         ["41", "true", '["a", "b"]'])

    def test_a_default_that_names_an_undeclared_field_is_refused(self) -> None:
        message = self._refused(
            forms={"a.b": {"sentence": "S.", "text": "{nope}"}},
            fields={"yes": {"sentence": "S.", "example": "x"}})
        self.assertIn("line_forms.a.b", message)
        self.assertIn("'nope'", message)
        self.assertIn("yes", message)

    def test_or_an_undeclared_word(self) -> None:
        message = self._refused(
            forms={"a.b": {"sentence": "S.", "text": "{line.nope}"}})
        self.assertIn("line_forms.a.b", message)
        self.assertIn("line.nope", message)

    def test_a_default_has_nothing_beneath_it(self) -> None:
        message = self._refused(
            forms={"a.b": {"sentence": "S.", "text": "{line.default} more"}})
        self.assertIn("line_forms.a.b", message)
        self.assertIn("{line.default}", message)

    def test_a_default_the_notation_cannot_read_is_refused(self) -> None:
        message = self._refused(forms={"a.b": {"sentence": "S.", "text": "{? never"}})
        self.assertIn("line_forms.a.b", message)
        self.assertIn("never ends", message)

    def test_no_word_is_called_default(self) -> None:
        message = self._refused(words={"default": {"sentence": "S.", "example": "x"}})
        self.assertIn("line_words", message)
        self.assertIn("'default'", message)

    def test_no_field_is_named_in_the_words_namespace(self) -> None:
        for name in ("line", "line.why"):
            with self.subTest(name=name):
                message = self._refused(
                    fields={name: {"sentence": "S.", "example": "x"}})
                self.assertIn("line_fields", message)
                self.assertIn(repr(name), message)

    SHAPES: ClassVar[dict[str, tuple[dict[str, object], str]]] = {
        "forms that are a list": ({"forms": ["a"]}, "line_forms"),
        "a form that is text": ({"forms": {"a": "{x}"}}, "line_forms.a"),
        "a form without its text": ({"forms": {"a": {"sentence": "S."}}},
                                    "line_forms.a"),
        "a form without its sentence": ({"forms": {"a": {"text": "x"}}},
                                        "line_forms.a"),
        "a form with a key it does not take": (
            {"forms": {"a": {"sentence": "S.", "text": "x", "txt": "y"}}},
            "line_forms.a"),
        "a form whose sentence is empty": (
            {"forms": {"a": {"sentence": " ", "text": "x"}}}, "line_forms.a"),
        "a form whose text is no text": (
            {"forms": {"a": {"sentence": "S.", "text": 5}}}, "line_forms.a"),
        "a form whose text is empty": (
            {"forms": {"a": {"sentence": "S.", "text": ""}}}, "line_forms.a"),
        "a form named with an empty part": (
            {"forms": {"a..b": {"sentence": "S.", "text": "x"}}}, "line_forms"),
        "a form named with a space": (
            {"forms": {"a b": {"sentence": "S.", "text": "x"}}}, "line_forms"),
        "a form named by a number": (
            {"forms": {5: {"sentence": "S.", "text": "x"}}}, "line_forms"),
        "a word without its example": (
            {"words": {"why": {"sentence": "S."}}}, "line_words.why"),
        "a word whose example is null": (
            {"words": {"why": {"sentence": "S.", "example": None}}},
            "line_words.why"),
        "a word with a dotted name": (
            {"words": {"a.b": {"sentence": "S.", "example": "x"}}}, "line_words"),
        "a field without its sentence": (
            {"fields": {"a": {"example": "x"}}}, "line_fields.a"),
        "a field with a key it does not take": (
            {"fields": {"a": {"sentence": "S.", "example": "x", "unit": "ms"}}},
            "line_fields.a"),
        "words that are text": ({"words": "why"}, "line_words"),
    }

    def test_every_other_shape_is_refused_by_its_name(self) -> None:
        for shape, (declared, named) in self.SHAPES.items():
            with self.subTest(shape):
                self.assertIn(named, self._refused(**declared))


class _Measured(_Runs):
    """``_Runs``, reading one workflow's runs, as the engine would run it."""

    def measure(self) -> Sequence[Measurement]:
        return [_reading()]


class WhereTheFormIsShownTests(TestCase):
    """The entry records the form that wrote it, and the node's page shows it beside
    the line — the key a deployment writes to make that line say more; and the
    engine hands the page each check's declarations (ADR-0126 decision 7)."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.addCleanup(setattr, app_module, "status_tree", app_module.status_tree)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def test_the_form_reaches_the_node_through_the_engine(self) -> None:
        check = _Measured.from_config({"path": "/ci"}, HERE)
        Engine([check], self.tree).run_once()
        snapshot = self.tree.snapshot("/ci")
        assert snapshot is not None
        (line,) = snapshot.reasons
        self.assertEqual((line.text, line.form),
                         (f"[CI]({URL}): passed (#41)", "run.verdict"))

    def test_the_nodes_page_shows_it_beside_the_line(self) -> None:
        Engine([_Measured.from_config({"path": "/ci"}, HERE)], self.tree).run_once()
        body = self.client.get("/status/ci").get_data(as_text=True)
        self.assertIn('Written from the form <code>run.verdict</code>', body)
        line = body.split('class="small check-reason', 1)[1]
        self.assertLess(line.index("reason-form"), line.index("reason-record"))

    def test_a_line_written_as_a_sentence_names_no_form(self) -> None:
        self.tree.upsert("/db", StatusCode.ERROR, [
            Entry("down", "db: down", code=StatusCode.ERROR, data={"host": "db1"})],
            members=True)
        body = self.client.get("/status/db").get_data(as_text=True)
        self.assertIn("reason-record", body)
        self.assertNotIn("reason-form", body)

    def test_the_engine_hands_on_each_checks_declarations(self) -> None:
        check = _runs()
        (info,) = Engine([check], StatusTree()).info().checks
        self.assertEqual(info.line_declarations, check.line_declarations)
        self.assertEqual([form.name for form in info.line_declarations.forms],
                         ["run.verdict", "run.none", "run.stale"])
