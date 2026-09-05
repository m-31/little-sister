"""The self-report seam (ADR-0071): contributors, and the four rules the beat
keeps — recorded state read never probed, a raising contributor caught and named,
stable namespaced slugs, and a report that clears."""
import unittest
from unittest import TestCase, mock

from little_sister import self_report
from little_sister.codes import StatusCode
from little_sister.reasons import Entry
from little_sister.self_report import (
    RAISED_SLUG,
    ContributorConflictError,
    Held,
    Standing,
    current_lines,
    register_contributor,
    registered_contributors,
)


class RegistrationTests(TestCase):
    def test_a_registration_records_the_calling_package(self):
        register_contributor("disk", lambda: [])
        (registration,) = registered_contributors()
        self.assertEqual(registration.name, "disk")
        self.assertEqual(registration.package, "tests")

    def test_a_name_is_one_slug_segment(self):
        for bad in ("", "state.layer", "a b", ".x", "x/y"):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                register_contributor(bad, lambda: [])

    def test_the_same_package_replaces_silently(self):
        # a registration module imported twice must not refuse a reloading server
        register_contributor("disk", lambda: [Entry("a", "one")])
        register_contributor("disk", lambda: [Entry("a", "two")])
        (registration,) = registered_contributors()
        self.assertEqual(registration.contributor()[0].text, "two")

    def test_another_package_refuses_unless_replacing_is_the_point(self):
        register_contributor("disk", lambda: [])
        # Stand in for a second package: the registry keys on the inferred
        # caller, so substitute the inference for one call.
        original = self_report.calling_package
        self_report.calling_package = lambda depth=2: "other_package"
        try:
            with self.assertRaises(ContributorConflictError) as caught:
                register_contributor("disk", lambda: [])
            self.assertIn("tests", str(caught.exception))
            self.assertIn("other_package", str(caught.exception))
            register_contributor("disk", lambda: [], replace=True)
        finally:
            self_report.calling_package = original
        (registration,) = registered_contributors()
        self.assertEqual(registration.package, "other_package")
        self.assertEqual(registration.replaced, "tests")


class LinesTests(TestCase):
    def test_lines_are_namespaced_by_contributor_in_registration_order(self):
        register_contributor("state", lambda: [
            Entry("save.events.json", "the last save failed", code=StatusCode.WARN)])
        register_contributor("pool", lambda: [
            Entry("saturated", "all busy", code=StatusCode.WARN)])
        slugs = [line.slug for line in current_lines()]
        self.assertEqual(slugs, ["state.save.events.json", "pool.saturated"])
        self.assertIs(current_lines()[0].code, StatusCode.WARN)

    def test_a_contributor_that_raises_is_caught_and_named(self):
        def broken():
            raise RuntimeError("probe *exploded*")

        register_contributor("keeper", broken)
        register_contributor("pool", lambda: [Entry("ok", "fine")])
        with self.assertLogs(level="ERROR"):
            lines = current_lines()
        self.assertEqual([line.slug for line in lines],
                         [f"keeper.{RAISED_SLUG}", "pool.ok"])
        self.assertIs(lines[0].code, StatusCode.WARN)
        self.assertIn("keeper", lines[0].text)
        # the message is external text and rides escaped (ADR-0018)
        self.assertIn(r"\*exploded\*", lines[0].text)

    def test_an_answer_that_is_not_lines_is_named_too(self):
        register_contributor("odd", lambda: ["a bare string"])  # type: ignore[list-item]
        with self.assertLogs(level="ERROR"):
            (line,) = current_lines()
        self.assertEqual(line.slug, f"odd.{RAISED_SLUG}")
        self.assertIs(line.code, StatusCode.WARN)

    def test_a_report_clears(self):
        holding: list[Entry] = [Entry("late", "a run outgrew its period",
                                      code=StatusCode.WARN)]
        register_contributor("engine2", lambda: list(holding))
        self.assertEqual([line.slug for line in current_lines()], ["engine2.late"])
        holding.clear()
        self.assertEqual(current_lines(), ())

    def test_no_contributors_no_lines(self):
        self.assertEqual(current_lines(), ())

    def test_a_report_per_contributor_carries_its_labels_and_its_own_slugs(self):
        """ADR-0076: the path carries the name, so a report's slugs are the
        contributor's own; the flat `current_lines` view keeps the prefix."""
        register_contributor("state", lambda: [Entry("load.x", "gone",
                                                     code=StatusCode.ERROR)],
                             title="State", about="what a restart keeps")
        register_contributor("quiet", lambda: [])
        reports = self_report.current_reports()
        self.assertEqual([(r.name, r.title, r.about) for r in reports],
                         [("state", "State", "what a restart keeps"),
                          ("quiet", "", "")])
        self.assertEqual([line.slug for line in reports[0].lines], ["load.x"])
        self.assertEqual(reports[1].lines, ())
        self.assertEqual([line.slug for line in current_lines()], ["state.load.x"])

    def test_a_raising_contributor_stands_in_its_own_report(self):
        def broken():
            raise RuntimeError("no")
        register_contributor("keeper", broken)
        with self.assertLogs("little_sister", level="ERROR"):
            (report,) = self_report.current_reports()
        self.assertEqual([line.slug for line in report.lines], [RAISED_SLUG])
        self.assertIn("raised", report.lines[0].text)


class ReportTests(TestCase):
    """A contributor's facts are its **report** (ADR-0044 decision 6, ADR-0076): a
    second callable answering Markdown, carried beside the lines and written on the
    child's `report`. Every line on a child carries a code; an uncoded line is a
    fact in the wrong place and is refused into a WARN that says so."""

    def test_a_contributor_may_answer_a_report_beside_its_lines(self):
        register_contributor("aws-keeper", lambda: [
            Entry("standby", "somebody else holds it", code=StatusCode.WARN)],
            report=lambda: "this instance holds the lease on s3://b/p\n\nlast: …")
        register_contributor("quiet", lambda: [])
        keeper, quiet = self_report.current_reports()
        self.assertEqual(keeper.report,
                         "this instance holds the lease on s3://b/p\n\nlast: …")
        self.assertEqual([line.slug for line in keeper.lines], ["standby"])
        self.assertEqual(quiet.report, "")

    def test_a_raising_report_is_a_stand_in_line_and_an_empty_report(self):
        def broken() -> str:
            raise RuntimeError("no")
        register_contributor("keeper", lambda: [], report=broken)
        with self.assertLogs("little_sister", level="ERROR"):
            (report,) = self_report.current_reports()
        self.assertEqual(report.report, "")
        self.assertEqual([line.slug for line in report.lines], [RAISED_SLUG])
        self.assertIn("report raised", report.lines[0].text)
        self.assertIs(report.lines[0].code, StatusCode.WARN)

    def test_a_report_that_is_not_text_is_a_stand_in_too(self):
        register_contributor(  # type: ignore[arg-type,return-value]
            "keeper", lambda: [], report=lambda: ["not", "text"])
        with self.assertLogs("little_sister", level="ERROR"):
            (report,) = self_report.current_reports()
        self.assertEqual(report.report, "")
        self.assertEqual([line.slug for line in report.lines], [RAISED_SLUG])

    def test_an_uncoded_line_is_refused_into_a_warn_under_its_own_slug(self):
        register_contributor("keeper", lambda: [
            Entry("holder", "this instance holds the lease"),
            Entry("standby", "somebody else is here", code=StatusCode.WARN)])
        with self.assertLogs("little_sister", level="ERROR"):
            (report,) = self_report.current_reports()
        self.assertEqual([line.slug for line in report.lines], ["holder", "standby"])
        holder = report.lines[0]
        self.assertIs(holder.code, StatusCode.WARN)
        self.assertIn("without a code", holder.text)
        self.assertIn("this instance holds the lease", holder.text)
        self.assertIn("report", holder.text)


class ActionTests(TestCase):
    """The action seam (ADR-0076): claimed once, found by contributor and slug."""

    def setUp(self):
        self_report.forget_actions()

    def tearDown(self):
        self_report.forget_actions()

    def test_an_action_is_offered_on_its_contributor_in_registration_order(self):
        self_report.register_action("aws-keeper", "release", "Release", lambda: "")
        self_report.register_action("aws-keeper", "take-over", "Take over",
                                    lambda: "")
        self_report.register_action("state", "flush", "Flush now", lambda: "")
        self.assertEqual([a.slug for a in self_report.actions_for("aws-keeper")],
                         ["release", "take-over"])
        found = self_report.find_action("state", "flush")
        assert found is not None
        self.assertEqual(found.label, "Flush now")
        self.assertIsNone(self_report.find_action("state", "nothing"))
        self.assertEqual(self_report.actions_for("nobody"), ())

    def test_the_same_package_replaces_and_another_refuses(self):
        self_report.register_action("aws-keeper", "release", "Release", lambda: "a")
        self_report.register_action("aws-keeper", "release", "Give up", lambda: "b")
        found = self_report.find_action("aws-keeper", "release")
        assert found is not None
        self.assertEqual(found.label, "Give up")
        # another package's claim is refused unless replacing is the point
        with mock.patch("little_sister.self_report.calling_package",
                        return_value="other_package"):
            with self.assertRaises(self_report.ActionConflictError):
                self_report.register_action("aws-keeper", "release", "Mine",
                                            lambda: "c")
            self_report.register_action("aws-keeper", "release", "Mine", lambda: "c",
                                        replace=True)
        found = self_report.find_action("aws-keeper", "release")
        assert found is not None
        self.assertEqual(found.label, "Mine")

    def test_a_name_a_slug_and_a_label_are_checked(self):
        with self.assertRaises(ValueError):
            self_report.register_action("a/b", "x", "X", lambda: "")
        with self.assertRaises(ValueError):
            self_report.register_action("a", "x y", "X", lambda: "")
        with self.assertRaises(ValueError):
            self_report.register_action("a", "x", "   ", lambda: "")


class StandingTests(TestCase):
    """`Standing` — what the process learned at startup and cannot undo: one line
    per slug, for the life of the process, logged in the same call."""

    def test_a_note_is_a_line_and_a_log_entry_in_one_call(self):
        record = Standing()
        with self.assertLogs("little_sister", level="WARNING") as logged:
            record.note("secret-key",
                        "SECRET_KEY did not resolve; a random key is in use")
        self.assertEqual(record.lines(), (
            Entry("secret-key", "SECRET_KEY did not resolve; a random key is in use",
                  code=StatusCode.WARN),))
        self.assertIn("secret-key: SECRET_KEY did not resolve", logged.output[0])
        self.assertTrue(logged.output[0].startswith("WARNING"))

    def test_the_log_level_is_the_lines_own_severity(self):
        record = Standing()
        with self.assertLogs("little_sister", level="INFO") as logged:
            record.note("shut", "the JSON API is shut", code=StatusCode.ERROR)
            record.note("moved", "the maintenance file moved", code=StatusCode.OK)
        self.assertTrue(logged.output[0].startswith("ERROR"))
        self.assertTrue(logged.output[1].startswith("INFO"))
        self.assertEqual([line.code for line in record.lines()],
                         [StatusCode.ERROR, StatusCode.OK])

    def test_it_stands_and_a_second_note_on_the_slug_replaces_the_first(self):
        record = Standing()
        record.note("a", "first", log=False)
        record.note("b", "other", log=False)
        record.note("a", "re-measured", log=False)
        self.assertEqual([(line.slug, line.text) for line in record.lines()],
                         [("a", "re-measured"), ("b", "other")])

    def test_the_library_keeps_one_and_it_reports_as_startup(self):
        self_report.startup.forget()
        try:
            self_report.startup.note("door", "nobody can sign in", log=False)
            register_contributor("startup", self_report.startup.lines, replace=True)
            self.assertEqual([line.slug for line in current_lines()],
                             ["startup.door"])
        finally:
            self_report.startup.forget()


class HeldTests(TestCase):
    """`Held` — what recurs, kept for a window after each occurrence: the line
    stands while the condition does, clears when it stops, counts rather than
    repeats, and reports the worst inside the window where there is a measure."""

    def _held(self, hold=30.0):
        return Held(hold, clock=lambda: 0.0)

    def test_an_occurrence_is_a_line_and_a_log_entry_in_one_call(self):
        held = self._held()
        with self.assertLogs("little_sister", level="WARNING") as logged:
            held.see("render", "the filler for node.actions raised", now=10.0)
        self.assertEqual(held.lines(now=10.0), (
            Entry("render", "the filler for node.actions raised",
                  code=StatusCode.WARN),))
        self.assertIn("render: the filler for node.actions raised", logged.output[0])

    def test_the_line_stands_for_the_window_and_then_clears(self):
        held = self._held(30.0)
        held.see("render", "raised", now=10.0, log=False)
        self.assertEqual(held.count("render", now=40.0), 1)      # 30 s on: still
        self.assertEqual(held.lines(now=41.0), ())               # 31 s on: gone

    def test_it_counts_rather_than_repeats(self):
        held = self._held(600.0)
        for second in range(17):
            held.see("render", "raised", now=float(second), log=False)
        (line,) = held.lines(now=20.0)
        self.assertEqual(line.text, "raised — 17 times in the last 10m")
        self.assertEqual(held.count("render", now=20.0), 17)

    def test_one_occurrence_carries_no_count(self):
        held = self._held()
        held.see("render", "raised", now=1.0, log=False)
        (line,) = held.lines(now=2.0)
        self.assertEqual(line.text, "raised")

    def test_the_worst_inside_the_window_is_reported_and_ages_out(self):
        held = self._held(30.0)
        held.see("lag", "came 20 s late", measure=19.0, now=120.0, log=False)
        held.see("lag", "came 11 s late", measure=10.0, now=140.0, log=False)
        worst = held.worst("lag", now=141.0)
        assert worst is not None
        self.assertEqual(worst.text, "came 20 s late")
        later = held.worst("lag", now=151.0)              # the 20 s one aged out
        assert later is not None
        self.assertEqual(later.text, "came 11 s late")

    def test_without_a_measure_the_worst_is_the_latest(self):
        held = self._held()
        held.see("a", "first", now=1.0, log=False)
        held.see("a", "second", now=2.0, log=False)
        worst = held.worst("a", now=3.0)
        assert worst is not None
        self.assertEqual(worst.text, "second")

    def test_slugs_are_kept_apart_and_ordered_by_first_sight(self):
        held = self._held()
        held.see("b", "b1", now=1.0, log=False)
        held.see("a", "a1", now=2.0, log=False)
        held.see("b", "b2", now=3.0, log=False)
        self.assertEqual(held.slugs(now=4.0), ("b", "a"))
        self.assertEqual([line.text for line in held.lines(now=4.0)],
                         ["b2 — 2 times in the last 30s", "a1"])

    def test_the_clock_is_the_injected_one_when_now_is_not_given(self):
        ticks = iter([5.0, 6.0, 100.0])
        held = Held(30.0, clock=lambda: next(ticks))
        held.see("a", "seen", log=False)                          # at 5
        self.assertEqual(held.count("a"), 1)                      # at 6
        self.assertEqual(held.count("a"), 0)                      # at 100

    def test_a_clock_that_went_backwards_keeps_the_window(self):
        held = self._held(30.0)
        held.see("a", "seen", now=100.0, log=False)
        self.assertEqual(held.count("a", now=50.0), 1)


class SecurityLinesTests(TestCase):
    """`security_lines` — failed logins as a rate, everything else as it is."""

    def setUp(self):
        self_report.security.forget()

    def tearDown(self):
        self_report.security.forget()

    def test_a_few_failed_logins_are_the_report_and_a_burst_is_a_warn_line(self):
        # Below the rate a failed login is a fact: it is the contributor's report
        # and no line (ADR-0076); from the rate it is the WARN line, and the
        # report is empty of it.
        for _ in range(self_report.FAILED_LOGINS_WARN - 1):
            self_report.security.see(self_report.FAILED_LOGIN,
                                     "for 'pan' at the built-in login list",
                                     log=False)
        self.assertEqual(self_report.security_lines(), ())
        report = self_report.security_report()
        self.assertIn("4 failed logins in the last 10m", report)
        self.assertIn("the last for 'pan'", report)

        self_report.security.see(self_report.FAILED_LOGIN,
                                 "for 'nobody' at the built-in login list",
                                 log=False)
        (line,) = self_report.security_lines()
        self.assertIs(line.code, StatusCode.WARN)
        self.assertIn("5 failed logins", line.text)
        self.assertIn("the last for 'nobody'", line.text)
        self.assertEqual(self_report.security_report(), "")

    def test_other_events_pass_through_as_the_record_writes_them(self):
        self_report.security.see("system-admin.used", "the local account signed in",
                                 log=False)
        (line,) = self_report.security_lines()
        self.assertEqual((line.slug, line.code), ("system-admin.used",
                                                  StatusCode.WARN))

    def test_nothing_seen_is_no_line_and_no_report(self):
        self.assertEqual(self_report.security_lines(), ())
        self.assertEqual(self_report.security_report(), "")


if __name__ == "__main__":
    unittest.main()
