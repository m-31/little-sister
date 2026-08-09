"""Addressable reasons: the keyed-entry model (ADR-0036).

Prose is the default and members are declared — the rule the whole feature turns
on, and the one most likely to be forgotten.
"""

import unittest
from unittest import TestCase

from little_sister.checks.base import CheckResult
from little_sister.errors import CheckError
from little_sister.reasons import (
    MAX_SLUG_LENGTH,
    Entry,
    ReasonEntry,
    ReasonError,
    derive_code,
    derived_slug,
    normalize,
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
