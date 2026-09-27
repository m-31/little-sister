"""A check declares its measures (ADR-0092): which fields of its record are drawn,
in which unit, and how many of its readings its node shows.

Each class holds one sentence of the record to account: `measures:` is a common
field of every check's YAML, read by the library; a type declares its default the
way it declares its subnodes, and the configuration merges over it per field; a
block of another shape is refused at startup, naming the file; a unit is free text,
and the family's own units are written the way the page writes a span; the measure
is read out of the record by the name its record list spells; and `reading_cap` is
the check's own answer to how many readings its node shows.
"""
from __future__ import annotations

import json
import tempfile
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar
from unittest import TestCase

import yaml

from little_sister import app as app_module
from little_sister.checks import (
    CHECK_TYPES,
    Check,
    CheckError,
    Measurement,
    load_checks,
)
from little_sister.checks.base import CheckResult
from little_sister.checks.http import HttpCheck
from little_sister.measures import Measure
from little_sister.status import StatusCode

HERE = Path(".")
TEMPLATES = Path(__file__).resolve().parent.parent / "config" / "checks" / "examples"


class _Probe(Check):
    """A type that declares nothing: its YAML is only the common fields."""

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _probe(**config: object) -> Check:
    return _Probe.from_config({"path": "/svc", **config}, HERE)


def _declaring(defaults: object, **config: object) -> Check:
    """A check whose type declares ``defaults``, built from ``config`` like any
    other — a factory, because a declaration is a fact about a type and not a
    value a configuration can set."""
    class _Declared(Check):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(measure_defaults=defaults, **kwargs)

        def measure(self) -> Sequence[Measurement]:
            return ()

        def grade(self, measurements: Sequence[Measurement],
                  now: datetime) -> CheckResult:
            return CheckResult(StatusCode.OK)

    return _Declared.from_config({"path": "/svc", **config}, HERE)


def _loaded(text: str) -> list[Check]:
    """The checks a configuration root holding one file, ``web.yaml``, loads."""
    with tempfile.TemporaryDirectory() as directory:
        checks = Path(directory) / "checks"
        checks.mkdir()
        (checks / "web.yaml").write_text(text, encoding="utf-8")
        return load_checks(Path(directory))


class MeasuresFieldTests(TestCase):
    """`measures:` is a common field of every check's YAML, beside `series_keep`,
    read by the library for every type (decision 1)."""

    def test_absent_is_no_measure(self) -> None:
        self.assertEqual(_probe().measures, {})

    def test_a_field_maps_to_its_unit(self) -> None:
        check = _probe(measures={"response_ms": "ms"})
        self.assertEqual(check.measures,
                         {"response_ms": Measure("response_ms", "ms", "response_ms")})

    def test_or_to_its_unit_and_a_label(self) -> None:
        check = _probe(measures={"response_ms": {"unit": "ms",
                                                 "label": "Response time"}})
        self.assertEqual(check.measures["response_ms"],
                         Measure("response_ms", "ms", "Response time"))

    def test_a_nested_field_is_named_as_its_record_list_spells_it(self) -> None:
        check = _probe(measures={"timing.total_ms": "ms"})
        self.assertEqual(list(check.measures), ["timing.total_ms"])

    def test_an_empty_unit_is_a_number_without_one(self) -> None:
        self.assertEqual(_probe(measures={"retries": ""}).measures["retries"].unit,
                         "")

    def test_an_empty_block_is_no_measure(self) -> None:
        self.assertEqual(_probe(measures={}).measures, {})

    def test_a_removal_with_nothing_to_remove_is_no_measure(self) -> None:
        self.assertEqual(_probe(measures={"response_ms": None}).measures, {})

    def test_every_type_reads_it(self) -> None:
        check, = _loaded("type: http\npath: /web\nurl: https://example.org\n"
                         "measures:\n  status: code\n")
        self.assertEqual(check.measures["status"], Measure("status", "code", "status"))


class MeasuresRefusedTests(TestCase):
    """A block of another shape — a unit that is not a string, a name that is not a
    field's — is refused at startup, naming the file, as a bad `series_keep` is
    (decision 2)."""

    SHAPES: ClassVar[dict[str, str]] = {
        "a list": "measures:\n  - response_ms\n",
        "a string": "measures: response_ms\n",
        "a number for a unit": "measures:\n  response_ms: 5\n",
        "a boolean for a unit": "measures:\n  response_ms: true\n",
        "no unit in the mapping": "measures:\n  response_ms: {label: Time}\n",
        "a unit that is not text": "measures:\n  response_ms: {unit: 5}\n",
        "a label that is not text": "measures:\n  response_ms: {unit: ms, label: 5}\n",
        "a key it does not take": "measures:\n  response_ms: {unit: ms, lable: T}\n",
        "an empty name": "measures:\n  '': ms\n",
        "an empty segment": "measures:\n  timing..total_ms: ms\n",
        "a leading dot": "measures:\n  .total_ms: ms\n",
        "a trailing dot": "measures:\n  total_ms.: ms\n",
        "a name that is a number": "measures:\n  5: ms\n",
        "a name with spaces around it": "measures:\n  ' response_ms': ms\n",
    }

    def test_every_other_shape_is_refused_naming_the_file(self) -> None:
        for shape, block in self.SHAPES.items():
            with self.subTest(shape=shape):
                with self.assertRaises(CheckError) as caught:
                    _loaded("type: http\npath: /web\nurl: https://example.org\n"
                            + block)
                message = str(caught.exception)
                self.assertTrue(message.startswith("web.yaml: "), message)
                self.assertIn("measures", message)

    def test_the_refusal_names_the_field(self) -> None:
        with self.assertRaises(CheckError) as caught:
            _probe(measures={"response_ms": 5})
        self.assertIn("measures.response_ms", str(caught.exception))


class MeasureDefaultsTests(TestCase):
    """A type passes the same mapping to its constructor as `measure_defaults`,
    and the configuration merges over it per field: a field it names takes its
    entry, every other keeps the default, `null` removes one, and an absent or
    empty block leaves the defaults standing (decisions 1 and 2)."""

    DEFAULTS: ClassVar[dict[str, object]] = {
        "response_ms": {"unit": "ms", "label": "Response time"},
        "queue_depth": "jobs"}

    def test_a_declaration_alone_reaches_the_check(self) -> None:
        check = _declaring(self.DEFAULTS)
        self.assertEqual(check.measures, {
            "response_ms": Measure("response_ms", "ms", "Response time"),
            "queue_depth": Measure("queue_depth", "jobs", "queue_depth")})

    def test_an_absent_or_empty_block_leaves_the_defaults_standing(self) -> None:
        for block in (None, {}):
            with self.subTest(block=block):
                config = {} if block is None else {"measures": block}
                self.assertEqual(list(_declaring(self.DEFAULTS, **config).measures),
                                 ["response_ms", "queue_depth"])

    def test_adding_a_measure_restates_nothing(self) -> None:
        check = _declaring(self.DEFAULTS, measures={"body_bytes": "B"})
        self.assertEqual(list(check.measures),
                         ["response_ms", "queue_depth", "body_bytes"])
        self.assertEqual(check.measures["response_ms"].label, "Response time")

    def test_a_field_the_configuration_names_takes_its_entry(self) -> None:
        check = _declaring(self.DEFAULTS, measures={"response_ms": "s"})
        self.assertEqual(check.measures["response_ms"],
                         Measure("response_ms", "s", "response_ms"))
        self.assertEqual(check.measures["queue_depth"].unit, "jobs")

    def test_null_removes_a_default(self) -> None:
        check = _declaring(self.DEFAULTS, measures={"queue_depth": None})
        self.assertEqual(list(check.measures), ["response_ms"])

    def test_a_declaration_of_another_shape_is_refused_by_its_name(self) -> None:
        # read at load like any other configuration error, though it comes from
        # code, as a subnode declaration's flag is
        for declared in ({"response_ms": 5}, {"response_ms": None},
                         {"response_ms": {"label": "Time"}}, ["response_ms"]):
            with self.subTest(declared=declared):
                with self.assertRaises(CheckError) as caught:
                    _declaring(declared)
                self.assertIn("measure_defaults", str(caught.exception))

    def test_the_http_type_declares_its_response_time(self) -> None:
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "https://example.org"}, HERE)
        self.assertEqual(check.measures, {
            "response_ms": Measure("response_ms", "ms", "Response time")})

    def test_so_a_deployment_can_take_it_back(self) -> None:
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "https://example.org",
             "measures": {"response_ms": None}}, HERE)
        self.assertEqual(check.measures, {})


class ReadingCapFieldTests(TestCase):
    """`reading_cap` in a check's own YAML, beside `series_keep`: it wins over the
    setting for that check, and a bad value is refused at startup, naming the file
    (decision 7)."""

    def test_absent_leaves_the_setting_in_force(self) -> None:
        self.assertIsNone(_probe().reading_cap)

    def test_a_count_is_read_as_a_count(self) -> None:
        self.assertEqual(_probe(reading_cap=25).reading_cap, 25)
        self.assertEqual(_probe(reading_cap="3").reading_cap, 3)
        self.assertEqual(_probe(reading_cap=0).reading_cap, 0)

    def test_junk_is_refused_naming_the_file(self) -> None:
        for junk in ("-1", "many", "true", "2.5", "''"):
            with self.subTest(reading_cap=junk):
                with self.assertRaises(CheckError) as caught:
                    _loaded("type: http\npath: /web\nurl: https://example.org\n"
                            f"reading_cap: {junk}\n")
                message = str(caught.exception)
                self.assertTrue(message.startswith("web.yaml: "), message)
                self.assertIn("reading_cap", message)


class TemplateTests(TestCase):
    """Every copy-me template shows the two keys where a deployment reaches for them:
    `reading_cap` beside `series_keep`, commented out, and in `http`'s the `measures:`
    block the type already declares."""

    def _loaded(self, body: str) -> Check:
        config = yaml.safe_load(body)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "my-check.sh").write_text("true\n")   # ssh-script's script
            return CHECK_TYPES[config["type"]].from_config(config, base)

    def test_every_template_carries_the_cap_beside_the_series(self) -> None:
        for template in sorted(TEMPLATES.glob("*.yaml")):
            with self.subTest(template=template.name):
                text = template.read_text(encoding="utf-8")
                lines = text.splitlines()
                index = next(number for number, line in enumerate(lines)
                             if line.startswith("# series_keep: 60"))
                self.assertTrue(lines[index + 1].startswith("# reading_cap: 10 "))
                self.assertIsNone(self._loaded(text).reading_cap)
                self.assertEqual(self._loaded(text.replace(
                    "# reading_cap: 10", "reading_cap: 10")).reading_cap, 10)

    def test_the_http_block_restates_what_the_type_declares(self) -> None:
        text = (TEMPLATES / "http.yaml").read_text(encoding="utf-8")
        block = ("# measures:\n"
                 "#   response_ms: {unit: ms, label: Response time}\n")
        self.assertIn(block, text)
        uncommented = text.replace(block, block.replace("# ", "").replace("#", ""))
        self.assertEqual(self._loaded(uncommented).measures,
                         self._loaded(text).measures)


class WrittenTests(TestCase):
    """A unit is free text, printed beside a value; `ms` and `s` are written
    through `format_span`, so 1,850 ms reads 1.9 s (decision 3). `B` reads as a
    plain label until a curve needs it formatted."""

    def test_milliseconds_read_as_a_span(self) -> None:
        measure = Measure("response_ms", "ms", "Response time")
        self.assertEqual(measure.write(1850), "1.9 s")
        self.assertEqual(measure.write(412), "412 ms")
        self.assertEqual(measure.write(115_000), "1m 55s")

    def test_seconds_read_as_a_span(self) -> None:
        measure = Measure("took_s", "s", "took_s")
        self.assertEqual(measure.write(3.14159), "3.1 s")
        self.assertEqual(measure.write(7620), "2h 7m")

    def test_a_span_below_zero_keeps_its_sign(self) -> None:
        # a clock offset can be negative, and `format_span` writes any negative
        # span as `0 s`: the measure writes the size and keeps the sign
        self.assertEqual(Measure("offset_ms", "ms", "offset").write(-12), "-12 ms")

    def test_any_other_unit_is_printed_beside_the_number(self) -> None:
        self.assertEqual(Measure("rate", "req/s", "rate").write(3), "3 req/s")
        self.assertEqual(Measure("rate", "req/s", "rate").write(1234), "1,234 req/s")
        self.assertEqual(Measure("rate", "req/s", "rate").write(2.5), "2.5 req/s")
        self.assertEqual(Measure("size", "B", "size").write(2048), "2,048 B")

    def test_no_unit_is_the_number_alone(self) -> None:
        self.assertEqual(Measure("retries", "", "retries").write(42), "42")

    def test_a_fraction_keeps_three_figures(self) -> None:
        measure = Measure("load", "", "load")
        self.assertEqual(measure.write(0.00123), "0.00123")
        self.assertEqual(measure.write(12.345), "12.3")
        self.assertEqual(measure.write(-0.5), "-0.5")

    def test_bare_leaves_the_unit_to_the_axis(self) -> None:
        # an axis prints a free-text unit once, as its label; a span names its
        # own unit in every tick, because `1.9 s` beside `ms` would contradict it
        self.assertEqual(Measure("rate", "req/s", "rate").write(20, bare=True), "20")
        self.assertEqual(Measure("t", "ms", "t").write(1500, bare=True), "1.5 s")
        self.assertEqual(Measure("rate", "req/s", "rate").axis_unit, "req/s")
        self.assertEqual(Measure("t", "ms", "t").axis_unit, "")
        self.assertEqual(Measure("t", "s", "t").axis_unit, "")


class ReadTests(TestCase):
    """A measure is a projection over the record (ADR-0085), read by the dotted
    name the node's record list spells the field with (decision 1)."""

    RECORD: ClassVar[dict[str, object]] = {
        "status": 200, "response_ms": 412,
        "timing": {"connect_ms": 38, "total_ms": 412},
        "tags": [1, 2], "ok": True, "error": None}

    def test_a_field_reads_its_value(self) -> None:
        self.assertEqual(Measure("response_ms", "ms", "t").read(self.RECORD), 412)

    def test_a_nested_field_reads_by_its_dotted_name(self) -> None:
        self.assertEqual(Measure("timing.connect_ms", "ms", "t").read(self.RECORD), 38)

    def test_a_missing_field_reads_as_null(self) -> None:
        # a projection treats a missing key as an empty one (ADR-0085 decision 3)
        self.assertIsNone(Measure("body_bytes", "B", "b").read(self.RECORD))
        self.assertIsNone(Measure("timing", "ms", "t").read(self.RECORD))

    def test_every_name_the_record_list_shows_reads_its_value(self) -> None:
        # the two spell a field alike, so what a reader sees listed on the page is
        # what they write in `measures:`
        for row in app_module._record_fields(self.RECORD):
            with self.subTest(name=row.name):
                value = Measure(row.name, "", row.name).read(self.RECORD)
                shown = value if isinstance(value, str) else json.dumps(value)
                self.assertEqual(shown, row.stored)
