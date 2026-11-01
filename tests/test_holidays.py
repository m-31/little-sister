"""The deployment's holidays: ``config/holidays.yaml`` (ADR-0149).

A deployment writes the days nobody works as named lists — a region's public holidays, a
company's own days off — each keyed by the name an entry keeps (``not_on: DE-BY``), with
a ``name`` that reads after *not on*, the years it is complete for, stated and never
inferred, and its dates, each with its name; ``default`` names the list an editor
offers first. Every configuration root's file is read, a list named in two of them
being the later root's, whole. What cannot be read does not apply (ADR-0032 rule 7):
within a list, any mistake leaves that list unreadable whole; outside the lists, the
file, and a file that cannot be read leaves every list unreadable — each named once on
the instance's node at the start, and nothing here stopping the monitor. Maintenance's
*Not on* reads the lists (#35).
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import date
from pathlib import Path
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import config_dir, holidays, self_report
from little_sister.codes import StatusCode
from little_sister.holidays import NO_HOLIDAYS, HolidayList, Holidays
from little_sister.reasons import Entry

_TESTS = Path(__file__).resolve().parent
_DEMO_CONFIG_DIR = _TESTS / "demo_config"
_SHIPPED_CONFIG_DIR = _TESTS.parent / "config"

BAVARIA = """\
lists:
  DE-BY:
    name: holidays in Bavaria
    complete: [2026, 2027]
    dates:
      2026-11-01: All Saints' Day
      2026-12-25: Christmas Day
      2027-01-06: Epiphany
"""

ACME = """\
  acme:
    name: ACME's company holidays
    complete: [2026]
    dates:
      2026-12-24: Christmas Eve
      2026-12-31: New Year's Eve
"""


def _said() -> str:
    """Every line the startup record holds of the holidays, unescaped, one a line."""
    return "\n".join(re.sub(r"\\(.)", r"\1", line.text)
                     for line in self_report.startup.lines()
                     if line.slug.startswith("holidays"))


def _lines() -> list[Entry]:
    return [line for line in self_report.startup.lines()
            if line.slug.startswith("holidays")]


class _Startup(TestCase):
    """A test that reads what the startup record says, from a clean record."""

    def setUp(self) -> None:
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)

    def _read(self, *texts: str) -> tuple[Holidays, list[Path]]:
        """``texts`` as the holidays.yaml of as many roots, in path-list order."""
        roots = [tempfile.TemporaryDirectory() for _ in texts]
        for root in roots:
            self.addCleanup(root.cleanup)
        files = []
        for root, text in zip(roots, texts, strict=True):
            file = Path(root.name) / "holidays.yaml"
            file.write_text(text, encoding="utf-8")
            files.append(file)
        spec = os.pathsep.join(root.name for root in roots)
        return holidays.load_holidays(spec), files


class ListTests(_Startup):
    """A list: its key, its name, the years it is complete for and its dates."""

    def test_a_list_says_its_name_its_years_and_its_dates(self):
        read, files = self._read(BAVARIA + ACME + "default: DE-BY\n")
        self.assertEqual(list(read.lists), ["DE-BY", "acme"])
        bavaria = read.lists["DE-BY"]
        self.assertEqual(bavaria.key, "DE-BY")
        self.assertEqual(bavaria.name, "holidays in Bavaria")
        self.assertEqual(bavaria.complete, frozenset({2026, 2027}))
        self.assertEqual(dict(bavaria.dates), {
            date(2026, 11, 1): "All Saints' Day",
            date(2026, 12, 25): "Christmas Day",
            date(2027, 1, 6): "Epiphany"})
        self.assertEqual(bavaria.file, files[0])
        self.assertEqual(read.lists["acme"].name, "ACME's company holidays")
        self.assertEqual(read.default, "DE-BY")
        self.assertEqual(read.files, (files[0],))
        self.assertEqual(read.unreadable, {})
        self.assertEqual(read.broken, "")
        self.assertEqual(_lines(), [])

    def test_a_day_is_named_where_the_list_names_it(self):
        read, _ = self._read(BAVARIA)
        bavaria = read.lists["DE-BY"]
        self.assertEqual(bavaria.holiday(date(2026, 11, 1)), "All Saints' Day")
        self.assertEqual(bavaria.holiday(date(2026, 11, 2)), "")

    def test_the_years_it_is_complete_for_are_stated_never_inferred(self):
        # a company list that rightly has no days in a year is complete for it, and
        # a day written in a year the list does not state makes the year no more
        # complete (#35's note, decision 6)
        read, _ = self._read(
            "lists:\n"
            "  acme:\n"
            "    name: ACME's company holidays\n"
            "    complete: [2027]\n"
            "  DE-BY:\n"
            "    name: holidays in Bavaria\n"
            "    complete: [2026]\n"
            "    dates:\n"
            "      2028-01-06: Epiphany\n")
        self.assertTrue(read.lists["acme"].covers(2027))
        self.assertEqual(dict(read.lists["acme"].dates), {})
        self.assertFalse(read.lists["acme"].covers(2026))
        self.assertFalse(read.lists["DE-BY"].covers(2028))
        self.assertTrue(read.lists["DE-BY"].covers(2026))
        self.assertEqual(_lines(), [])

    def test_one_year_alone_is_the_one_year_it_is_complete_for(self):
        read, _ = self._read(BAVARIA.replace("[2026, 2027]", "2026"))
        self.assertEqual(read.lists["DE-BY"].complete, frozenset({2026}))

    def test_a_name_written_over_several_lines_is_one(self):
        read, _ = self._read(BAVARIA.replace(
            "name: holidays in Bavaria", "name: |\n      holidays\n      in Bavaria"))
        self.assertEqual(read.lists["DE-BY"].name, "holidays in Bavaria")


class UnreadableListTests(_Startup):
    """Within a list, any mistake leaves that list unreadable whole — a day missing
    from it would put a window on that day — and the others stand."""

    def _unreadable(self, text: str, *said: str) -> Holidays:
        read, files = self._read(text + ACME)
        self.assertNotIn("DE-BY", read.lists)
        self.assertIn("DE-BY", read.unreadable)
        self.assertIsNone(read.get("DE-BY"))
        self.assertIn("acme", read.lists)
        self.assertEqual(read.broken, "")
        lines = _said()
        self.assertIn(f"{files[0]}: the holiday list DE-BY cannot be read", lines)
        for words in said:
            self.assertIn(words, lines)
            self.assertIn(words, read.why_not("DE-BY"))
        self.assertEqual(len(_lines()), 1)
        return read

    def test_a_date_written_twice(self):
        self._unreadable(BAVARIA + "      2026-11-01: Allerheiligen\n",
                         "it writes 2026-11-01 twice")

    def test_a_date_that_is_no_date(self):
        self._unreadable(BAVARIA + "      2026-13-01: Never\n",
                         "it names 2026-13-01, which is no date: a day is written "
                         "YYYY-MM-DD")

    def test_a_date_with_a_time(self):
        self._unreadable(BAVARIA + "      2026-12-26T10:00:00: Boxing Day\n",
                         "it names 2026-12-26 10:00:00, which carries a time: a day is "
                         "written YYYY-MM-DD")

    def test_a_date_with_no_name(self):
        self._unreadable(BAVARIA + "      2026-12-26:\n",
                         "it gives 2026-12-26 no name")

    def test_a_date_whose_name_is_no_text(self):
        self._unreadable(BAVARIA + "      2026-12-26: 26\n",
                         "it gives 2026-12-26 the name 26, which YAML reads as an int "
                         "— put it in quotes")

    def test_no_name(self):
        self._unreadable(BAVARIA.replace("    name: holidays in Bavaria\n", ""),
                         "it has no name, which reads after *not on*")

    def test_a_name_that_is_no_text(self):
        self._unreadable(BAVARIA.replace("name: holidays in Bavaria", "name: 2026"),
                         "its name is 2026, which YAML reads as an int — put it in "
                         "quotes")

    def test_a_blank_name(self):
        self._unreadable(BAVARIA.replace("name: holidays in Bavaria", "name: ' '"),
                         "it has no name, which reads after *not on*")

    def test_no_year_it_is_complete_for(self):
        self._unreadable(BAVARIA.replace("    complete: [2026, 2027]\n", ""),
                         "it states no year it is complete for")
        self_report.startup.forget()
        self._unreadable(BAVARIA.replace("[2026, 2027]", "[]"),
                         "it states no year it is complete for")

    def test_a_year_that_is_no_year(self):
        for written, shown in (("'2026'", "'2026'"), ("2026.5", "2026.5"),
                               ("true", "True"), ("0", "0"), ("10000", "10000")):
            with self.subTest(written=written):
                self_report.startup.forget()
                self._unreadable(BAVARIA.replace("[2026, 2027]", f"[2026, {written}]"),
                                 f"it states {shown} complete, which is no year")

    def test_a_key_a_list_does_not_know(self):
        self._unreadable(BAVARIA.replace("    complete:", "    region: Bavaria\n"
                                                        "    complete:"),
                         "it writes region, which a list does not know")

    def test_a_list_that_is_no_mapping(self):
        self._unreadable("lists:\n  DE-BY: [2026-11-01, 2026-12-25]\n",
                         "it is a list, where it maps name, complete and dates")

    def test_dates_that_are_no_mapping(self):
        self._unreadable(BAVARIA.split("    dates:\n")[0]
                         + "    dates: [2026-11-01, 2026-12-25]\n",
                         "its dates are a list, where they map each day to its name")

    def test_a_list_written_twice_in_one_file(self):
        self._unreadable(BAVARIA + BAVARIA.removeprefix("lists:\n"),
                         "it is written twice in one file")

    def test_a_key_that_is_no_word(self):
        read, files = self._read(BAVARIA.replace("DE-BY:", "DE BY:"))
        self.assertEqual(dict(read.lists), {})
        self.assertIn("DE BY", read.unreadable)
        self.assertIn(f"{files[0]}: the holiday list DE BY cannot be read — a list's "
                      f"key is letters and digits, with hyphens, dots or underscores "
                      f"between them", _said())

    def test_a_key_yaml_reads_as_no_text(self):
        read, files = self._read(BAVARIA.replace("DE-BY:", "2026:"))
        self.assertEqual(dict(read.lists), {})
        self.assertIn(f"{files[0]} names the holiday list 2026, which YAML reads as an "
                      f"int; a list's key is text — put it in quotes", _said())

    def test_a_dated_day_in_a_year_it_does_not_state_is_no_mistake(self):
        read, _ = self._read(BAVARIA + "      2028-01-06: Epiphany\n")
        self.assertIn("DE-BY", read.lists)
        self.assertEqual(_lines(), [])


class UnreadableFileTests(_Startup):
    """Outside the lists, a mistake leaves the file unreadable, and a file that cannot
    be read leaves every list unreadable: any of them may be written in it."""

    def _broken(self, text: str, said: str, *, before: str = "") -> None:
        texts = (before, text) if before else (text,)
        read, files = self._read(*texts)
        self.assertTrue(read.broken)
        self.assertIsNone(read.get("DE-BY"))
        self.assertIsNone(read.get("acme"))
        expected = f"{files[-1]}{said}, so no holiday list can be read"
        self.assertIn(expected, _said())
        self.assertEqual(read.why_not("DE-BY"), expected)
        self.assertEqual(read.why_not("acme"), expected)

    def test_a_file_that_does_not_parse(self):
        read, files = self._read(BAVARIA + "  broken: [\n")
        self.assertTrue(read.broken.startswith(f"{files[0]} cannot be read ("))
        self.assertTrue(read.broken.endswith("), so no holiday list can be read"))
        self.assertIsNone(read.get("DE-BY"))
        self.assertEqual(len(_lines()), 1)

    def test_a_file_that_is_no_mapping(self):
        self._broken("- DE-BY\n- acme\n",
                     " is a list, where it maps lists and default")

    def test_a_key_the_file_does_not_know(self):
        self._broken(BAVARIA + ACME + "regions: {}\n",
                     " writes regions, which it does not know")

    def test_a_key_written_twice(self):
        self._broken(BAVARIA + ACME + "lists: {}\n", " writes lists twice")

    def test_lists_that_are_no_mapping(self):
        self._broken("lists: [DE-BY, acme]\n",
                     "'s lists are a list, where they map each list's key to the list")

    def test_a_broken_file_leaves_every_root_s_lists_unreadable(self):
        # an earlier root's list stands no more: the later root may have written it
        self._broken("- nothing\n", " is a list, where it maps lists and default",
                     before=BAVARIA + ACME)

    def test_an_empty_file_is_no_list_and_no_mistake(self):
        read, files = self._read("# nothing here yet\n")
        self.assertEqual(dict(read.lists), {})
        self.assertEqual(read.broken, "")
        self.assertEqual(read.files, (files[0],))
        self.assertEqual(_lines(), [])


class RootsTests(_Startup):
    """Every root's file is read, in path-list order: a list named in two roots is the
    later root's, whole, keeping the place it was first named in."""

    def test_a_later_roots_list_is_taken_whole(self):
        read, files = self._read(
            BAVARIA + ACME,
            "lists:\n  DE-BY:\n    name: holidays in Bavaria\n    complete: [2026]\n"
            "    dates:\n      2026-12-26: Saint Stephen's Day\n")
        self.assertEqual(list(read.lists), ["DE-BY", "acme"])
        self.assertEqual(dict(read.lists["DE-BY"].dates),
                         {date(2026, 12, 26): "Saint Stephen's Day"})
        self.assertEqual(read.lists["DE-BY"].complete, frozenset({2026}))
        self.assertEqual(read.lists["DE-BY"].file, files[1])
        self.assertEqual(read.files, tuple(files))

    def test_a_later_roots_unreadable_list_is_unreadable(self):
        read, _ = self._read(BAVARIA + ACME,
                             BAVARIA + "      2026-11-01: Allerheiligen\n")
        self.assertNotIn("DE-BY", read.lists)
        self.assertIn("it writes 2026-11-01 twice", read.why_not("DE-BY"))
        self.assertIn("acme", read.lists)

    def test_a_later_roots_readable_list_mends_an_earlier_one(self):
        read, _ = self._read(BAVARIA + "      2026-11-01: Allerheiligen\n", BAVARIA)
        self.assertIn("DE-BY", read.lists)
        self.assertEqual(read.why_not("DE-BY"), "")
        self.assertNotIn("DE-BY", read.unreadable)
        # the earlier file's mistake is still a mistake in that file
        self.assertIn("it writes 2026-11-01 twice", _said())

    def test_the_default_is_the_later_roots(self):
        read, _ = self._read(BAVARIA + ACME + "default: DE-BY\n", "default: acme\n")
        self.assertEqual(read.default, "acme")


class DefaultTests(_Startup):
    """``default`` names the list an editor offers first; one that names no list is
    named and no list is offered first — it hides nothing, so it stops nothing."""

    def test_a_default_that_names_no_list(self):
        read, files = self._read(BAVARIA + "default: DE-BE\n")
        self.assertEqual(read.default, "")
        self.assertIn("DE-BY", read.lists)
        self.assertIn(f"{files[0]}: default names DE-BE, which no holiday list is; no "
                      f"list is offered first", _said())

    def test_a_default_that_is_no_text(self):
        read, files = self._read(BAVARIA + "default: [DE-BY]\n")
        self.assertEqual(read.default, "")
        self.assertIn(f"{files[0]}: default is a list, where it names a holiday list; "
                      f"no list is offered first", _said())

    def test_a_default_may_name_a_list_that_cannot_be_read(self):
        read, _ = self._read(BAVARIA + "      2026-11-01: Allerheiligen\n"
                             + "default: DE-BY\n")
        self.assertEqual(read.default, "DE-BY")
        self.assertIsNone(read.get("DE-BY"))


class WhyNotTests(_Startup):
    """What a reader asks: a list by its key, or why it cannot have it."""

    def test_a_list_that_can_be_read_has_no_why(self):
        read, _ = self._read(BAVARIA)
        self.assertIsInstance(read.get("DE-BY"), HolidayList)
        self.assertEqual(read.why_not("DE-BY"), "")

    def test_a_list_no_file_lists(self):
        read, files = self._read(BAVARIA)
        self.assertIsNone(read.get("DE-BE"))
        self.assertEqual(read.why_not("DE-BE"), f"{files[0]} lists no DE-BE")

    def test_a_list_where_no_root_has_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            read = holidays.load_holidays(Path(directory))
        self.assertEqual(read, NO_HOLIDAYS)
        self.assertIsNone(read.get("DE-BY"))
        self.assertEqual(read.why_not("DE-BY"),
                         "no configuration root has a holidays.yaml")
        self.assertEqual(_lines(), [])


class StartupRecordTests(_Startup):
    """What cannot be read is a warning on the instance's node, for the life of the
    process — never a refusal to start."""

    def test_a_line_is_a_warning_keyed_by_the_file_and_the_list(self):
        self._read(BAVARIA + "      2026-11-01: Allerheiligen\n"
                   + ACME.replace("[2026]", "[]"))
        lines = _lines()
        self.assertEqual(len(lines), 2)
        self.assertEqual({line.code for line in lines}, {StatusCode.WARN})
        self.assertEqual(len({line.slug for line in lines}), 2)

    def test_the_aspect_is_the_librarys_own(self):
        self.assertIn("holidays", config_dir.BUILTIN_ASPECTS)
        aspect = config_dir.BUILTIN_ASPECTS["holidays"]
        self.assertTrue(aspect.as_file)
        self.assertFalse(aspect.as_directory)
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "holidays.yaml").write_text(BAVARIA, encoding="utf-8")
            with self.assertNoLogs(level="WARNING"):
                config_dir.announce_aspects(directory)


class StartTests(_Startup):
    """The start reads the file once, before the state is restored, which maintenance
    will read it in (#35), and keeps what it read for the life of the process."""

    def setUp(self) -> None:
        super().setUp()
        original = app_module.holiday_lists
        self.addCleanup(setattr, app_module, "holiday_lists", original)

    def test_the_start_reads_every_root_s_file(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "holidays.yaml").write_text(BAVARIA, encoding="utf-8")
            with mock.patch.dict(os.environ, {"LITTLE_SISTER_CONFIG_DIR": directory}):
                app_module._load_holidays()
        self.assertEqual(list(app_module.holiday_lists.lists), ["DE-BY"])

    def test_the_start_reads_it_before_the_state_is_restored(self):
        order = mock.Mock()
        for name in ("_read_nodes", "_seed_tags", "_load_aggregation",
                     "_load_holidays", "_restore_state", "_retain_notes",
                     "_restore_series", "_seed_node_metadata"):
            patcher = mock.patch.object(app_module, name)
            order.attach_mock(patcher.start(), name)
            self.addCleanup(patcher.stop)
        for name in ("engine", "engine_error", "state_layer", "lease"):
            self.addCleanup(setattr, app_module, name, getattr(app_module, name))
        with mock.patch.object(app_module, "create_engine"), \
                mock.patch.object(app_module, "open_log_file"), \
                mock.patch.object(app_module, "_resolve_settings"):
            app_module._start_engine(mock.Mock(), mock.Mock(), "a test")
        called = [each[0] for each in order.mock_calls if "." not in each[0]]
        self.assertLess(called.index("_load_aggregation"),
                        called.index("_load_holidays"))
        self.assertLess(called.index("_load_holidays"),
                        called.index("_restore_state"))


class ShippedTests(_Startup):
    """The library's own copy is an example and inert; the demo's reads clean."""

    def test_the_shipped_copy_lists_nothing(self):
        read = holidays.load_holidays(_SHIPPED_CONFIG_DIR)
        self.assertEqual(dict(read.lists), {})
        self.assertEqual(read.broken, "")
        self.assertEqual(len(read.files), 1)
        self.assertEqual(_lines(), [])

    def test_the_demos_list_reads_clean(self):
        read = holidays.load_holidays(_DEMO_CONFIG_DIR)
        self.assertIn("DE-BY", read.lists)
        self.assertTrue(read.lists["DE-BY"].dates)
        self.assertEqual(read.default, "DE-BY")
        self.assertEqual(_lines(), [])
