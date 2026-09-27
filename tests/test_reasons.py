"""Addressable reasons: the keyed-entry model (ADR-0036).

Prose is the default and members are declared — the rule the whole feature turns
on, and the one most likely to be forgotten.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

from little_sister.checks.base import CheckResult, Measurement
from little_sister.errors import CheckError
from little_sister.limits import RECORD_LIMIT
from little_sister.reasons import (
    MAX_SLUG_LENGTH,
    MAX_SUBJECT_LENGTH,
    Entry,
    ReasonEntry,
    ReasonError,
    clip,
    derive_code,
    derived_slug,
    normalize,
    normalize_record,
)
from little_sister.status import Status, StatusCode


class NormalizeTests(TestCase):
    def test_none_and_empty_are_nothing(self):
        self.assertEqual(normalize(None), ((), False))
        self.assertEqual(normalize([]), ((), False))
        self.assertEqual(normalize({}), ((), False))

    def test_a_bare_string_is_one_prose_entry(self):
        entries, members = normalize("disk at 86%")
        self.assertEqual([e.text for e in entries], ["disk at 86%"])
        self.assertFalse(members)

    def test_the_flag_is_meaningless_beside_a_bare_string(self):
        # one condition is one condition; there is nothing to address inside it
        self.assertFalse(normalize("boom", True)[1])

    def test_a_list_of_strings_is_prose_by_default(self):
        # the engine's failure path returns exactly this shape and must not change
        entries, members = normalize(["check error: boom", "Traceback…"])
        self.assertFalse(members)
        self.assertEqual(len(entries), 2)

    def test_entries_true_declares_members_beside_a_list(self):
        entries, members = normalize(["PR-1 fix", "PR-2 bump"], True)
        self.assertTrue(members)
        self.assertEqual([e.text for e in entries], ["PR-1 fix", "PR-2 bump"])

    def test_a_mapping_declares_members_by_its_shape(self):
        entries, members = normalize({"pr-412": "waiting", "pr-77": "stale"})
        self.assertTrue(members)
        self.assertEqual([e.slug for e in entries], ["pr-412", "pr-77"])

    def test_pairs_declare_members_too(self):
        entries, members = normalize([("a", "one"), ("b", "two")])
        self.assertTrue(members)
        self.assertEqual([(e.slug, e.text) for e in entries],
                         [("a", "one"), ("b", "two")])

    def test_order_is_the_checks_order_not_the_slugs(self):
        # a check's order carries information (severity, API order); an opaque slug
        # would scramble it
        entries, _ = normalize({"zz": "first", "aa": "second"})
        self.assertEqual([e.slug for e in entries], ["zz", "aa"])

    def test_already_normalized_entries_pass_through(self):
        given = [ReasonEntry("x", "one")]
        entries, members = normalize(given, True)
        self.assertEqual(entries, tuple(given))
        self.assertTrue(members)

    def test_a_mixed_sequence_is_refused(self):
        with self.assertRaises(ReasonError):
            normalize(["a string", ("a", "pair")])


class SlugTests(TestCase):
    def test_a_derived_slug_is_the_wording(self):
        first = derived_slug("finding one")
        self.assertTrue(first.startswith("h-"))
        self.assertEqual(first, derived_slug("finding one"))
        self.assertNotEqual(first, derived_slug("finding two"))

    def test_a_derived_slug_does_not_move_when_an_entry_is_inserted_above(self):
        # the whole reason it is not an index: a pin must not slide onto a
        # *different* finding when the list grows
        before, _ = normalize(["alpha", "beta"], True)
        after, _ = normalize(["new one", "alpha", "beta"], True)
        by_text = {e.text: e.slug for e in after}
        self.assertEqual(before[0].slug, by_text["alpha"])
        self.assertEqual(before[1].slug, by_text["beta"])

    def test_a_repeated_text_gets_its_own_slug(self):
        # a real list can carry the same sentence three times, for three findings
        entries, _ = normalize(["same", "same", "same"], True)
        self.assertEqual(len({e.slug for e in entries}), 3)
        self.assertTrue(entries[1].slug.endswith("-2"))
        self.assertTrue(entries[2].slug.endswith("-3"))

    def test_a_declared_slug_survives_a_rewording(self):
        first, _ = normalize({"acme/api-pr-412": "waiting on review"})
        second, _ = normalize({"acme/api-pr-412": "waiting on review from Ada"})
        self.assertEqual(first[0].slug, second[0].slug)
        self.assertNotEqual(first[0].text, second[0].text)

    def test_declared_and_derived_are_tellable_apart(self):
        declared, _ = normalize({"pr-412": "waiting"})
        derived, _ = normalize(["waiting"], True)
        self.assertFalse(declared[0].derived)
        self.assertTrue(derived[0].derived)

    def test_a_slug_must_be_usable_in_a_url_or_a_form(self):
        for bad in ("", "  ", "has space", "tab\there", "line\nbreak",
                    "x" * (MAX_SLUG_LENGTH + 1)):
            with self.subTest(slug=bad):
                with self.assertRaises(ReasonError):
                    normalize({bad: "text"})

    def test_a_slug_with_a_slash_is_fine(self):
        # the natural slug for a discovered entry contains one, which is exactly
        # why addressing is a query parameter and never a path segment
        entries, _ = normalize({"acme/api-pr-412": "waiting"})
        self.assertEqual(entries[0].slug, "acme/api-pr-412")


class CheckResultTests(TestCase):
    def test_a_disk_check_keeps_writing_what_it_always_wrote(self):
        result = CheckResult(StatusCode.WARN, ["disk at 86%"])
        self.assertEqual(result.reason_texts, ["disk at 86%"])
        self.assertFalse(result.members)

    def test_a_mapping_result_declares_members(self):
        result = CheckResult(StatusCode.ERROR, {"f-1": "one", "f-2": "two"})
        self.assertTrue(result.members)
        self.assertEqual([e.slug for e in result.reason_entries], ["f-1", "f-2"])

    def test_entries_true_declares_members(self):
        result = CheckResult(StatusCode.WARN, ["a", "b"], entries=True)
        self.assertTrue(result.members)

    def test_a_malformed_slug_is_the_check_authors_error(self):
        # surfaces as a failing check, not as a silent re-key
        with self.assertRaises(CheckError):
            CheckResult(StatusCode.WARN, {"has space": "text"})


class StatusReasonTests(TestCase):
    def test_reason_stays_the_texts_every_surface_reads(self):
        node = Status("/db", code=StatusCode.WARN, reason={"a": "one", "b": "two"})
        self.assertEqual(node.reason, ["one", "two"])
        self.assertEqual([e.slug for e in node.reason_entries], ["a", "b"])
        self.assertTrue(node.members)

    def test_update_replaces_the_whole_map(self):
        node = Status("/db")
        node.update(StatusCode.WARN, {"a": "one"}, True)
        node.update(StatusCode.ERROR, ["check error: boom"])
        self.assertEqual(node.reason, ["check error: boom"])
        self.assertFalse(node.members)      # a failure is prose again


if __name__ == '__main__':
    unittest.main()


class CodedEntryTests(TestCase):
    """Entries that carry their own claim (ADR-0042)."""

    def test_an_entry_may_not_claim_maintenance(self):
        # a pin is recorded beside the reading, never reported by a check
        with self.assertRaises(ReasonError):
            Entry("w1", "down on purpose", StatusCode.MAINTENANCE)

    def test_entry_and_reasonentry_are_one_class(self):
        # two spellings, zero migration: ADR-0036-era code keeps working
        self.assertIs(Entry, ReasonEntry)

    def test_a_code_or_running_declares_members_by_shape(self):
        self.assertTrue(normalize([Entry("w", "x", StatusCode.OK)])[1])
        self.assertTrue(normalize([Entry("w", "x", running=True)])[1])

    def test_a_plain_entry_sequence_keeps_the_flag_semantics(self):
        self.assertFalse(normalize([Entry("w", "x")])[1])
        self.assertTrue(normalize([Entry("w", "x")], True)[1])

    def test_entry_slugs_are_validated_like_declared_pairs(self):
        with self.assertRaises(ReasonError):
            normalize([Entry("has space", "x")])
        with self.assertRaises(ReasonError):
            normalize([Entry("", "x")])

    def test_a_taken_slug_bumps_and_the_claim_travels_with_it(self):
        entries, _ = normalize([Entry("w", "a", StatusCode.OK),
                                Entry("w", "b", StatusCode.ERROR, running=True)])
        self.assertEqual([e.slug for e in entries], ["w", "w-2"])
        self.assertEqual(entries[1].code, StatusCode.ERROR)
        self.assertTrue(entries[1].running)


class SubjectTests(TestCase):
    """What a line is about (backlog #32), carried and bounded."""

    def test_a_subject_travels_and_declares_nothing(self):
        # data about a claim is not a claim: prose carrying a subject stays prose
        entries, members = normalize([Entry("w", "x", subject="1296269")])
        self.assertEqual(entries[0].subject, "1296269")
        self.assertFalse(members)

    def test_an_over_long_subject_is_refused(self):
        with self.assertRaises(ReasonError):
            Entry("w", "x", subject="r" * (MAX_SUBJECT_LENGTH + 1))

    def test_a_control_character_is_refused(self):
        with self.assertRaises(ReasonError):
            Entry("w", "x", subject="repo\x01")


class RecordTests(TestCase):
    """The record on an entry: what the check read, kept (backlog #32).

    The seam is `CheckResult`, so the tests that matter go through it — a record
    that travels only as far as `Entry` has not been validated at all.
    """

    def test_a_record_reaches_the_entry_and_the_text_does_not_move(self):
        result = CheckResult(reason=[
            Entry("w", "CI: failed (#41)", StatusCode.ERROR,
                  subject="1296269",
                  data={"workflow": "CI", "run_number": 41})])
        self.assertEqual(result.reason_texts, ["CI: failed (#41)"])
        self.assertEqual(result.reason_entries[0].data,
                         {"workflow": "CI", "run_number": 41})

    def test_a_record_alone_declares_no_members(self):
        # `code`/`running` declare members by shape; a record deliberately does not
        result = CheckResult(StatusCode.WARN, [Entry("w", "x", data={"a": 1})])
        self.assertFalse(result.members)

    def test_no_record_is_the_default_and_stays_none(self):
        result = CheckResult(StatusCode.OK, ["nothing to say"])
        self.assertIsNone(result.reason_entries[0].data)

    def test_a_time_is_converted_to_utc_wherever_it_sits(self):
        # RECORD_TIMESTAMP_KEYS are read at any depth — the first emitter's own
        # times are nested under the run they belong to
        result = CheckResult(StatusCode.OK, [Entry(
            "w", "x", data={"at": "2026-09-19T11:12:00+02:00",
                            "completed": {"ended": "2026-09-19T11:30:00+02:00"},
                            "runs": [{"started": "2026-09-19T11:40:00+02:00"}]})])
        record = result.reason_entries[0].data
        assert record is not None
        self.assertEqual(record["at"], "2026-09-19T09:12:00Z")
        self.assertEqual(record["completed"]["ended"], "2026-09-19T09:30:00Z")
        self.assertEqual(record["runs"][0]["started"], "2026-09-19T09:40:00Z")

    def test_a_null_time_is_a_fact_and_is_kept(self):
        result = CheckResult(StatusCode.OK,
                             [Entry("w", "x", data={"ended": None})])
        record = result.reason_entries[0].data
        assert record is not None
        self.assertIsNone(record["ended"])

    def test_a_naive_time_is_refused_and_the_field_is_named(self):
        # an instant from somebody else's clock, read by a viewer in a third zone
        with self.assertRaises(CheckError) as caught:
            CheckResult(StatusCode.OK,
                        [Entry("w", "x", data={"completed": {"at": "2026-09-19"}})])
        self.assertIn("completed.at", str(caught.exception))

    def test_a_bad_time_is_reported_as_a_bad_time(self):
        # The walk that converts the times ran inside the handler for a value JSON
        # cannot hold, so a time without an offset read as a record that "must be
        # JSON-serializable" — which it was, and which sent a reader looking for
        # the wrong thing before the real sentence.
        with self.assertRaises(CheckError) as caught:
            CheckResult(StatusCode.OK,
                        [Entry("w", "x", data={"completed": {"at": "2026-09-19"}})])
        message = str(caught.exception)
        self.assertIn("record field 'completed.at' names a time", message)
        self.assertNotIn("JSON-serializable", message)

    def test_a_time_utc_cannot_hold_is_refused_as_a_bad_time(self):
        # An offset can carry an instant at the edge of the calendar past it: the
        # first hour of the year 1 at +01:00 is the year 0 in UTC. The conversion
        # raised OverflowError out of the check, where every other bad time is a
        # CheckError that names the field.
        for value in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:30:00-01:00"):
            with self.subTest(value=value):
                with self.assertRaises(CheckError) as caught:
                    CheckResult(StatusCode.OK,
                                [Entry("w", "x", data={"updated": {"at": value}})])
                self.assertIn(
                    f"record field 'updated.at' names a time that lies outside the "
                    f"years 1 to 9999 once it is read in UTC: {value!r}",
                    str(caught.exception))
                with self.assertRaises(CheckError):
                    Measurement(subject="w", record={"updated": {"at": value}})

    def test_a_value_that_is_not_a_time_under_a_timed_name_is_refused(self):
        with self.assertRaises(CheckError):
            CheckResult(StatusCode.OK, [Entry("w", "x", data={"at": 1758276720})])

    def test_a_record_that_is_not_json_is_refused(self):
        with self.assertRaises(CheckError):
            CheckResult(StatusCode.OK,
                        [Entry("w", "x", data={"when": object()})])

    def test_a_record_must_be_a_mapping(self):
        with self.assertRaises(CheckError):
            CheckResult(StatusCode.OK, [Entry("w", "x", data=["a", "b"])])

    def test_an_over_heavy_record_refuses_the_whole_result(self):
        # the cost of the loud refusal, stated: the healthy line does not survive
        # the heavy one, because a silently dropped record would be believed missing
        with self.assertRaises(CheckError) as caught:
            CheckResult(reason=[
                Entry("light", "fine", StatusCode.OK, data={"a": 1}),
                Entry("heavy", "also fine", StatusCode.OK,
                      data={"dump": "x" * (RECORD_LIMIT + 1)})])
        self.assertIn("bytes", str(caught.exception))

    def test_clip_bounds_characters_and_then_bytes(self):
        """The two bounds and their order. A record is weighed as `json.dumps`
        writes it, which escapes to ASCII, so a character is a byte only while the
        text is ASCII — measured: 1000 characters cost 1002 bytes in ASCII, 2002
        in newlines, 6002 in umlauts and 12002 in emoji, which JSON writes as
        surrogate pairs."""
        self.assertEqual(clip("abcdef", chars=3, budget=1000), "abc")
        for filler in ("a", "\n", "ä", "\U0001f600"):
            with self.subTest(filler=filler):
                kept = clip(filler * 1000, chars=1000, budget=2000)
                self.assertLessEqual(
                    len(json.dumps(kept).encode("utf-8")), 2000)
        # and the byte bound is what bites, not the character one
        self.assertLess(len(clip("ä" * 1000, chars=1000, budget=2000)), 1000)
        self.assertEqual(len(clip("a" * 1000, chars=1000, budget=2000)), 1000)

    def test_clip_cuts_both_bounds_off_the_same_end(self):
        """A tail kept by characters and then trimmed at the front by bytes would
        be neither end of anything — and, worse, would be measured at the wrong
        end. The text below is cheap at the front and expensive at the back, so a
        byte bound applied to the *head* would let through six times the budget
        while still answering with a tail that looks right."""
        self.assertEqual(clip("abcdef", chars=3, budget=1000, keep="tail"), "def")
        lopsided = "a" * 500 + "ä" * 500
        tail = clip(lopsided, chars=1000, budget=200, keep="tail")
        self.assertTrue(tail.endswith("ä"), tail[-8:])
        self.assertLessEqual(len(json.dumps(tail).encode("utf-8")), 200)
        head = clip("START" + "ä" * 100, chars=105, budget=64, keep="head")
        self.assertTrue(head.startswith("START"), head)
        self.assertLessEqual(len(json.dumps(head).encode("utf-8")), 64)

    def test_clip_is_exact_rather_than_conservative(self):
        """One byte more would not fit, which is what makes a declaration built on
        it a ceiling rather than a guess."""
        kept = clip("ä" * 500, chars=500, budget=100)
        self.assertLessEqual(len(json.dumps(kept).encode("utf-8")), 100)
        self.assertGreater(
            len(json.dumps(kept + "ä").encode("utf-8")), 100)

    def test_a_measurement_meets_the_same_seam(self):
        """A record is a record wherever it hangs (ADR-0085): the measurement goes
        through the same validation and the same limit as a line's, so a check
        author who learned one rule does not meet a second."""
        with self.assertRaises(CheckError) as caught:
            Measurement(record={"dump": "x" * (RECORD_LIMIT + 1)})
        self.assertIn("bytes", str(caught.exception))
        with self.assertRaises(CheckError):
            Measurement(record={"at": "not a time"})

    def test_a_measurements_record_is_read_back_as_plain_json(self):
        # the same ADR-0002 safety the line's record has: a check that kept its
        # mapping must not be able to change a value while a page renders it
        handed = {"cpu_pct": 7, "nested": {"load": 0.4}}
        taken = Measurement(record=handed, subject="host-a")
        handed["cpu_pct"] = 99
        handed["nested"]["load"] = 9.9
        self.assertEqual(taken.record["cpu_pct"], 7)
        self.assertEqual(taken.record["nested"]["load"], 0.4)

    def test_a_measurements_subject_is_bounded_like_a_lines(self):
        with self.assertRaises(CheckError):
            Measurement(record={}, subject="x" * 4096)
        with self.assertRaises(CheckError):
            Measurement(record={}, subject="host\x00a")

    def test_the_limit_is_the_json_bytes_not_the_characters(self):
        # a euro sign is one character and three bytes: what a record costs is what
        # goes on the wire
        wide = {"note": "\u20ac" * RECORD_LIMIT}
        with self.assertRaises(ReasonError):
            normalize_record(wide, limit=RECORD_LIMIT)

    def test_the_stored_record_is_a_copy_the_check_no_longer_owns(self):
        # a snapshot is read outside the lock (ADR-0002); a check that kept its
        # mapping must not be able to change a value while a page renders it
        handed = {"verdict": "failure", "nested": {"run": 41}}
        result = CheckResult(StatusCode.OK, [Entry("w", "x", data=handed)])
        handed["verdict"] = "success"
        handed["nested"]["run"] = 99
        record = result.reason_entries[0].data
        assert record is not None
        self.assertEqual(record["verdict"], "failure")
        self.assertEqual(record["nested"]["run"], 41)

    def test_what_is_stored_is_what_a_client_receives(self):
        # read back from JSON, so a tuple is already a list and a non-string key a
        # string — rather than something that merely serializes to them
        result = CheckResult(StatusCode.OK,
                             [Entry("w", "x", data={"tags": ("a", "b"), 41: "run"})])
        record = result.reason_entries[0].data
        self.assertEqual(record, {"tags": ["a", "b"], "41": "run"})


class WithoutADeploymentTests(TestCase):
    """A result is built in plenty of places where there is no deployment, and a
    record must not change that.

    The seam reads `record_limit` from the configuration, and **importing** the
    configuration resolves a configuration directory and refuses when there is none
    (ADR-0031). A plugin's own test suite has none — that is the ordinary case, not
    an exotic one — so this runs in a child process pointed at a directory that does
    not exist, which is what a plugin looks like from here. Run in-process it would
    prove nothing: this suite has a configuration beside it.
    """

    def _run(self, body: str) -> str:
        with tempfile.TemporaryDirectory() as empty:
            env = dict(os.environ)
            env["LITTLE_SISTER_CONFIG_DIR"] = str(Path(empty) / "nowhere")
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            done = subprocess.run([sys.executable, "-c", body], env=env,
                                  capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0,
                         f"stdout={done.stdout!r} stderr={done.stderr!r}")
        return done.stdout

    def test_a_record_is_carried_and_bounded_with_no_configuration(self):
        out = self._run(
            "from little_sister.checks.base import CheckResult, CheckError\n"
            "from little_sister.limits import RECORD_LIMIT\n"
            "from little_sister.reasons import Entry\n"
            "from little_sister.status import StatusCode\n"
            "kept = CheckResult(reason=[Entry('w', 'x', StatusCode.OK,\n"
            "                                 data={'at': '2026-09-19T09:00:00Z'})])\n"
            "assert kept.reason_entries[0].data == {'at': '2026-09-19T09:00:00Z'}\n"
            "try:\n"
            "    CheckResult(reason=[Entry('w', 'x', StatusCode.OK,\n"
            "                              data={'d': 'x' * (RECORD_LIMIT + 1)})])\n"
            "except CheckError as error:\n"
            "    assert 'bytes' in str(error), error\n"
            "else:\n"
            "    raise AssertionError('the default limit did not apply')\n"
            "print('ok')\n")
        self.assertEqual(out.strip(), "ok")


class DeriveCodeTests(TestCase):
    """The node code a coded entry set derives to (ADR-0042)."""

    def test_worst_of_the_declared_codes(self):
        entries = (Entry("a", "x", StatusCode.OK),
                   Entry("b", "y", StatusCode.ERROR),
                   Entry("c", "z", StatusCode.WARN))
        self.assertEqual(derive_code(entries), StatusCode.ERROR)

    def test_undefined_is_ignored_and_wins_only_alone(self):
        self.assertEqual(
            derive_code((Entry("a", "x", StatusCode.UNDEFINED),
                         Entry("b", "y", StatusCode.OK))),
            StatusCode.OK)
        # a job list where nothing has ever concluded has not reported
        self.assertEqual(derive_code((Entry("a", "x", StatusCode.UNDEFINED),)),
                         StatusCode.UNDEFINED)

    def test_an_empty_set_reads_ok(self):
        # the check ran, enumerated, and found nothing — "nothing to report"
        # is not "nothing reported"
        self.assertEqual(derive_code(()), StatusCode.OK)

    def test_an_uncoded_entry_contributes_nothing_here(self):
        # it carries the node's code — which is the value being derived
        self.assertEqual(
            derive_code((Entry("a", "x"), Entry("b", "y", StatusCode.WARN))),
            StatusCode.WARN)
