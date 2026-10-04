"""A measure says where its axis reaches (ADR-0117): ``axis_to``, a key of its entry in
``measures:`` and in a type's ``measure_defaults``, read against the record's
decisions — what is declared, what a curve and its sparkline do with it, what a
reading above it does, what is refused, and which of the library's own measures
declare it.
"""
from __future__ import annotations

from typing import ClassVar
from unittest import TestCase

from little_sister.checks import CheckError
from little_sister.checks.ssh import host_metrics, macos_memory, qnap_metrics
from little_sister.curves import BOTTOM, TOP, draw
from little_sister.measures import Measure
from tests.test_curves import TOLERANCE, _placed
from tests.test_measures import _declaring, _loaded, _probe

PCT = Measure("pct", "%", "Memory in use", axis_to=100)
BARE = Measure("pct", "%", "Memory in use")


def _readings(*values: float) -> list:
    return [_placed(3 * index, pct=value) for index, value in enumerate(values)]


def _ticks(measure: Measure, *values: float, small: bool = False) -> list[str]:
    curve = draw(measure, _readings(*values), tolerance=TOLERANCE, small=small)
    return [tick.text for tick in curve.ticks]


class DeclaredTests(TestCase):
    """Decision 1: a key of a measure's entry, in a deployment's block and in a
    type's defaults, merged per field as the rest is."""

    def test_a_measure_declares_none_unless_it_says_so(self) -> None:
        self.assertIsNone(_probe(measures={"pct": "%"}).measures["pct"].axis_to)
        self.assertIsNone(
            _probe(measures={"pct": {"unit": "%"}}).measures["pct"].axis_to)

    def test_an_entry_declares_it(self) -> None:
        check = _probe(measures={"pct": {"unit": "%", "axis_to": 100}})
        self.assertEqual(check.measures["pct"].axis_to, 100.0)
        check = _probe(measures={"ratio": {"unit": "", "axis_to": 0.5}})
        self.assertEqual(check.measures["ratio"].axis_to, 0.5)

    def test_a_types_default_declares_it(self) -> None:
        check = _declaring({"pct": {"unit": "%", "axis_to": 100}})
        self.assertEqual(check.measures["pct"].axis_to, 100.0)

    def test_an_entry_the_configuration_names_is_taken_whole(self) -> None:
        # as a relabeled default restates its unit (ADR-0092 decision 2)
        defaults = {"pct": {"unit": "%", "axis_to": 100}}
        relabeled = _declaring(defaults, measures={"pct": {"unit": "%",
                                                           "label": "Used"}})
        self.assertIsNone(relabeled.measures["pct"].axis_to)
        moved = _declaring(defaults, measures={"pct": {"unit": "%", "axis_to": 400}})
        self.assertEqual(moved.measures["pct"].axis_to, 400.0)
        self.assertEqual(_declaring(defaults, measures={"pct": None}).measures, {})

    def test_every_key_a_star_stands_for_carries_it(self) -> None:
        declared = Measure("volumes.*.pct", "%", "Used on *", "disk/*", axis_to=100)
        root, data = declared.expand([{"volumes": {"root": {"pct": 5},
                                                   "data": {"pct": 6}}}])
        self.assertEqual((root.axis_to, data.axis_to), (100, 100))


class RefusedTests(TestCase):
    """Decision 4: a value that is not a positive number refuses the load, naming
    the file, as a bad ``measures:`` block does."""

    VALUES: ClassVar[dict[str, str]] = {
        "zero": "0", "a negative number": "-5", "text": "'100'", "a boolean": "true",
        "infinity": ".inf", "not a number": ".nan", "a list": "[100]",
        "nothing": "null",
    }

    def test_every_other_value_is_refused_naming_the_file_and_the_key(self) -> None:
        for name, value in self.VALUES.items():
            with self.subTest(value=name):
                with self.assertRaises(CheckError) as caught:
                    _loaded("type: http\npath: /web\nurl: https://example.org\n"
                            f"measures:\n  pct: {{unit: '%', axis_to: {value}}}\n")
                message = str(caught.exception)
                self.assertTrue(message.startswith("web.yaml: "), message)
                self.assertIn("measures.pct.axis_to", message)

    def test_no_lower_end_is_declarable(self) -> None:
        with self.assertRaises(CheckError):
            _probe(measures={"pct": {"unit": "%", "axis_from": 20}})


class DrawnTests(TestCase):
    """Decisions 2 and 3: the axis reaches the declared end whatever the readings
    are below it, grows past it for a reading above, and starts where it did."""

    def test_without_it_the_axis_ends_a_step_past_the_highest_reading(self) -> None:
        self.assertEqual(_ticks(BARE, 17, 18), ["0", "5", "10", "15", "20"])

    def test_with_it_the_axis_ends_there(self) -> None:
        self.assertEqual(_ticks(PCT, 17, 18), ["0", "25", "50", "75", "100"])
        self.assertEqual(_ticks(PCT, 72, 81), ["0", "25", "50", "75", "100"])

    def test_two_curves_of_one_kind_compare(self) -> None:
        low = draw(PCT, _readings(18, 18), tolerance=TOLERANCE).runs[0][0]
        high = draw(PCT, _readings(81, 81), tolerance=TOLERANCE).runs[0][0]
        self.assertAlmostEqual(low.y, BOTTOM - 0.18 * (BOTTOM - TOP), places=1)
        self.assertAlmostEqual(high.y, BOTTOM - 0.81 * (BOTTOM - TOP), places=1)

    def test_a_sparkline_stands_on_the_same_scale(self) -> None:
        small = draw(PCT, _readings(18, 18), tolerance=TOLERANCE, small=True)
        large = draw(PCT, _readings(18, 18), tolerance=TOLERANCE)
        self.assertAlmostEqual(
            (small.bottom - small.runs[0][0].y) / (small.bottom - small.top), 0.18,
            places=2)
        self.assertAlmostEqual(
            (large.bottom - large.runs[0][0].y) / (large.bottom - large.top), 0.18,
            places=2)

    def test_a_reading_above_it_grows_the_axis_as_one_without_it_would(self) -> None:
        self.assertEqual(_ticks(PCT, 40, 130), _ticks(BARE, 40, 130))
        self.assertEqual(_ticks(PCT, 40, 130)[-1], "150")
        # and nothing is cut off: the reading is on the plot, beneath its top
        point = draw(PCT, _readings(40, 130), tolerance=TOLERANCE).runs[0][1]
        self.assertGreater(point.y, TOP)

    def test_the_axis_still_starts_at_zero_or_below_where_a_reading_is(self) -> None:
        self.assertEqual(_ticks(PCT, -10, 18)[0], "-50")
        self.assertEqual(_ticks(PCT, -10, 18)[-1], "100")

    def test_an_end_between_steps_is_reached_by_the_next_whole_step(self) -> None:
        to_90 = Measure("pct", "%", "Used", axis_to=90)
        self.assertEqual(_ticks(to_90, 5, 6), ["0", "25", "50", "75", "100"])

    def test_the_numbers_beside_a_curve_are_its_readings(self) -> None:
        curve = draw(PCT, _readings(17, 18), tolerance=TOLERANCE)
        self.assertEqual((curve.lowest, curve.highest), ("17 %", "18 %"))


class OwnMeasuresTests(TestCase):
    """Decision 5: a measure of the library's own that is a percent of a whole
    declares 100, and no other declares an end."""

    def test_the_percents_of_a_whole_reach_100(self) -> None:
        declared = {
            f"{module.__name__.rsplit('.', 1)[1]}:{name}": entry.get("axis_to")
            for module in (host_metrics, macos_memory, qnap_metrics)
            for name, entry in module.MEASURES.items()
            if isinstance(entry, dict)}
        self.assertEqual(
            {name for name, end in declared.items() if end is not None},
            {"host_metrics:mem_pct", "host_metrics:cpu_pct",
             "host_metrics:disk_pct", "host_metrics:volumes.*.pct",
             "macos_memory:compressor_pct"})
        self.assertEqual({end for end in declared.values() if end is not None},
                         {100})
        self.assertGreater(len(declared), 5)
