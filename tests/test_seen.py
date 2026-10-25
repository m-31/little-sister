"""A failure seen keeps its true color and counts as OK above, until it changes
(ADR-0142).

The tree's half of *seen*: what a line's and a node's own acknowledgment do to what is
counted, what ends each — a recovery, a worsening, a new occurrence, the part no longer
reported, the end it was given, a person's hand — the row each act writes, where a
ringed check may set one, and the pins file that keeps them. The page's half is
`tests/test_seen_pages.py`'s.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase

from little_sister.aggregation import Table
from little_sister.pins import MAINTENANCE, SEEN, Pin, PinStore
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import (
    ACCEPTED,
    CAUSE_LINE_SEEN_ENDED,
    CAUSE_LINE_SEEN_SET,
    CAUSE_READING,
    CAUSE_REMOVED,
    CAUSE_SEEN_EDITED,
    CAUSE_SEEN_ENDED,
    CAUSE_SEEN_SET,
    ENDED_CLOCK,
    ENDED_GONE,
    ENDED_HAND,
    ENDED_OCCURRENCE,
    ENDED_RECOVERY,
    ENDED_WORSENING,
    SEEN_RULE,
    Event,
    StatusTree,
    acknowledgeable_parts,
    chip_counts,
    failing_first,
    handled_beneath,
    own_failure,
    parts_digest,
    rules_beneath,
)

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
LATER = timedelta(days=2)


def _lines(**codes: StatusCode | tuple[StatusCode, str]) -> list[Entry]:
    """A node's lines by slug, each its code — or its code and its occurrence."""
    lines = []
    for slug, said in codes.items():
        code, occurrence = said if isinstance(said, tuple) else (said, "")
        lines.append(Entry(slug, f"{slug} reads {code.name.lower()}", code=code,
                           occurrence=occurrence))
    return lines


class _Estate(TestCase):
    """A host whose disk fails for itself, a build whose lines are members, and a
    healthy neighbour, under one site."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.tree.upsert("/site/web/cpu", OK)
        self.tree.upsert("/site/ci/build", ERROR,
                         _lines(test=ERROR, lint=WARN, docs=OK), members=True)

    def seen(self, path: str, slug: str = "", note: str = "looked into",
             expires_at: datetime | None = None) -> Pin:
        write = self.tree.set_acknowledgment(path, slug, SEEN, note,
                                             expires_at=expires_at, set_by="ada")
        self.assertTrue(write.applied, write.problem)
        assert write.current is not None
        return write.current

    def code(self, path: str) -> StatusCode:
        node = self.tree.snapshot(path)
        assert node is not None
        return node.code

    def rows(self, path: str) -> list[Event]:
        return [event for event in self.tree.recent_events() if event.path == path]


class LineTests(_Estate):
    """A line's acknowledgment: the line keeps its color, its node counts it OK."""

    def test_a_seen_line_keeps_its_color_and_its_node_counts_it_ok(self):
        self.seen("/site/ci/build", "test")
        node = self.tree.snapshot("/site/ci/build")
        assert node is not None
        line = next(line for line in node.reasons if line.slug == "test")
        self.assertIs(line.code, ERROR)
        self.assertTrue(line.accepted)
        self.assertIs(node.own_code, WARN)
        self.assertIs(self.code("/site/ci"), WARN)

    def test_every_failing_line_seen_turns_the_node_ok(self):
        self.seen("/site/ci/build", "test")
        self.seen("/site/ci/build", "lint")
        self.assertIs(self.code("/site/ci/build"), OK)
        self.assertIs(self.code("/site/ci"), OK)

    def test_a_pinned_line_is_the_pin_s(self):
        self.seen("/site/ci/build", "test")
        self.tree.set_entry_maintenance("/site/ci/build", "test", "swap",
                                        expires_at=datetime.now(UTC) + LATER)
        node = self.tree.snapshot("/site/ci/build")
        assert node is not None
        line = next(line for line in node.reasons if line.slug == "test")
        self.assertTrue(line.quiet)
        self.assertFalse(line.accepted)

    def test_it_comes_after_the_failures_nobody_has_seen(self):
        self.seen("/site/ci/build", "test")
        node = self.tree.snapshot("/site/ci/build")
        assert node is not None
        self.assertEqual([line.slug for line in failing_first(node.reasons)],
                         ["lint", "test", "docs"])

    def test_the_accepted_table_counts_a_failure_ok(self):
        self.assertIs(ACCEPTED.counts(ERROR), OK)
        self.assertIs(ACCEPTED.counts(WARN), OK)
        self.assertIs(ACCEPTED.counts(OK), OK)
        self.assertEqual(ACCEPTED, Table(((WARN, OK), (ERROR, OK))))


class NodeTests(_Estate):
    """A node's own acknowledgment: it keeps its color, its parent counts it OK."""

    def test_a_seen_node_keeps_its_color_and_its_parent_counts_it_ok(self):
        pin = self.seen("/site/web/disk")
        node = self.tree.snapshot("/site/web/disk")
        assert node is not None
        self.assertIs(node.code, ERROR)
        self.assertEqual(node.acknowledgment, pin)
        assert node.contribution is not None
        self.assertEqual((node.contribution.code, node.contribution.by,
                          node.contribution.rule), (OK, SEEN_RULE, pin.id))
        self.assertIs(self.code("/site/web"), OK)

    def test_a_failure_beneath_a_seen_branch_still_climbs(self):
        self.tree.upsert("/site/web", ERROR, "the web tier is slow")
        self.seen("/site/web")
        web = self.tree.snapshot("/site/web")
        assert web is not None
        self.assertIs(web.code, ERROR)
        self.assertIsNone(web.contribution)
        self.tree.upsert("/site/web/disk", OK)
        web = self.tree.snapshot("/site/web")
        assert web is not None and web.contribution is not None
        self.assertEqual((web.code, web.contribution.code), (ERROR, OK))

    def test_a_stale_reading_counts_at_least_a_warning(self):
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full",
                         frequency_seconds=60)
        self.seen("/site/web/disk")
        later = datetime.now(UTC) + timedelta(minutes=10)
        node = self.tree.snapshot("/site/web", now=later)
        assert node is not None
        self.assertIs(node.code, WARN)

    def test_it_names_itself_over_a_wait(self):
        self.tree.upsert("/site/web/disk", WARN, "disk 90 % full", escalate_after=3)
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full", escalate_after=3)
        held = self.tree.snapshot("/site/web/disk")
        assert held is not None and held.contribution is not None
        self.assertEqual(held.contribution.by, "damping")
        self.seen("/site/web/disk")
        node = self.tree.snapshot("/site/web/disk")
        assert node is not None and node.contribution is not None
        self.assertEqual((node.contribution.code, node.contribution.by), (OK, SEEN))

    def test_maintenance_on_it_wins(self):
        self.seen("/site/web/disk")
        self.tree.set_maintenance("/site/web/disk", "swap",
                                  expires_at=datetime.now(UTC) + LATER)
        node = self.tree.snapshot("/site/web/disk")
        assert node is not None and node.contribution is not None
        self.assertEqual(node.contribution.by, MAINTENANCE)

    def test_it_spends_no_failure_budget(self):
        node = self.tree.snapshot("/site/web/disk")
        assert node is not None
        self.assertEqual(own_failure(node), "error")
        self.seen("/site/web/disk")
        node = self.tree.snapshot("/site/web/disk")
        assert node is not None
        self.assertIsNone(own_failure(node))


class EndTests(_Estate):
    """What ends a seen, each a row of its node saying why."""

    def ended(self, path: str) -> list[Event]:
        return [row for row in self.rows(path) if row.ended]

    def test_a_recovery_ends_a_line_s(self):
        self.seen("/site/ci/build", "test")
        self.tree.upsert("/site/ci/build", WARN, _lines(test=OK, lint=WARN, docs=OK),
                         members=True)
        self.assertIsNone(self.tree.acknowledgment("/site/ci/build", "test"))
        (row,) = self.ended("/site/ci/build")
        self.assertEqual((row.cause, row.ended), (CAUSE_LINE_SEEN_ENDED,
                                                  ENDED_RECOVERY))
        self.assertIs(row.old, row.new)

    def test_an_improvement_holds_and_a_return_to_it_too(self):
        self.seen("/site/ci/build", "test")
        for code in (WARN, ERROR, WARN):
            self.tree.upsert("/site/ci/build", ERROR,
                             _lines(test=code, lint=WARN, docs=OK), members=True)
            self.assertIsNotNone(self.tree.acknowledgment("/site/ci/build", "test"))

    def test_a_worsening_ends_it_and_the_change_is_its_end(self):
        self.seen("/site/ci/build", "lint")
        self.seen("/site/ci/build", "test")
        self.assertIs(self.code("/site/ci/build"), OK)
        self.tree.upsert("/site/ci/build", ERROR,
                         _lines(test=ERROR, lint=ERROR, docs=OK), members=True)
        self.assertIsNone(self.tree.acknowledgment("/site/ci/build", "lint"))
        row = self.rows("/site/ci/build")[-1]
        self.assertEqual((row.old, row.new, row.cause, row.ended),
                         (OK, ERROR, CAUSE_LINE_SEEN_ENDED, ENDED_WORSENING))

    def test_a_new_occurrence_ends_it(self):
        self.tree.upsert("/site/ci/build", ERROR, _lines(test=(ERROR, "run 7/1")),
                         members=True)
        pin = self.seen("/site/ci/build", "test")
        self.assertEqual(pin.occurrence, "run 7/1")
        self.tree.upsert("/site/ci/build", ERROR, _lines(test=(ERROR, "run 7/1")),
                         members=True)
        self.assertIsNotNone(self.tree.acknowledgment("/site/ci/build", "test"))
        self.tree.upsert("/site/ci/build", ERROR, _lines(test=(ERROR, "run 8/1")),
                         members=True)
        (row,) = self.ended("/site/ci/build")
        self.assertEqual(row.ended, ENDED_OCCURRENCE)
        self.assertEqual((row.old, row.new), (OK, ERROR))

    def test_a_failing_stretch_has_no_occurrence_to_end(self):
        pin = self.seen("/site/ci/build", "test")
        self.assertEqual(pin.occurrence, "")
        self.tree.upsert("/site/ci/build", ERROR,
                         _lines(test=(ERROR, "now one"), lint=WARN), members=True)
        self.assertIsNotNone(self.tree.acknowledgment("/site/ci/build", "test"))

    def test_a_line_no_longer_reported_ends_it(self):
        self.seen("/site/ci/build", "test")
        self.tree.upsert("/site/ci/build", WARN, _lines(lint=WARN), members=True)
        (row,) = self.ended("/site/ci/build")
        self.assertEqual(row.ended, ENDED_GONE)

    def test_a_check_error_leaves_it_suspended(self):
        self.seen("/site/ci/build", "test")
        self.tree.upsert("/site/ci/build", ERROR, ["check error: timed out"])
        self.assertIsNotNone(self.tree.acknowledgment("/site/ci/build", "test"))
        self.assertEqual(self.ended("/site/ci/build"), [])

    def test_its_end_ends_it_by_the_clock(self):
        soon = datetime.now(UTC) + timedelta(minutes=5)
        self.seen("/site/web/disk", expires_at=soon)
        self.tree.sweep_expired(soon + timedelta(seconds=1))
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))
        (row,) = self.ended("/site/web/disk")
        self.assertEqual((row.cause, row.ended), (CAUSE_SEEN_ENDED, ENDED_CLOCK))
        self.assertIs(self.code("/site/web"), ERROR)

    def test_a_hand_ends_it(self):
        pin = self.seen("/site/ci/build", "test")
        write = self.tree.clear_acknowledgment("/site/ci/build", "test",
                                               expected_set_at=pin.token)
        self.assertTrue(write.applied)
        row = self.rows("/site/ci/build")[-1]
        self.assertEqual((row.old, row.new, row.cause, row.ended),
                         (WARN, ERROR, CAUSE_LINE_SEEN_ENDED, ENDED_HAND))

    def test_a_node_s_own_ends_at_its_recovery_and_its_worsening(self):
        self.tree.upsert("/site/web/disk", WARN, "disk 90 % full")
        self.seen("/site/web/disk")
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))
        reading, end = self.rows("/site/web/disk")[-2:]
        self.assertEqual((reading.cause, reading.old, reading.new),
                         (CAUSE_READING, WARN, ERROR))
        self.assertEqual((end.cause, end.ended, end.old, end.new),
                         (CAUSE_SEEN_ENDED, ENDED_WORSENING, ERROR, ERROR))
        # The branch above took the alarm by the end, not by the reading.
        period = self.tree.period("/site/web")
        assert period is not None
        self.assertEqual((period.code, period.began.cause, period.by),
                         (ERROR, CAUSE_SEEN_ENDED, "/site/web/disk"))
        self.seen("/site/web/disk")
        self.tree.upsert("/site/web/disk", OK)
        self.assertEqual(self.ended("/site/web/disk")[-1].ended, ENDED_RECOVERY)

    def test_a_removal_ends_what_stood_on_the_node(self):
        self.seen("/site/ci/build", "test")
        self.tree.prune("/site/ci", ())
        rows = self.rows("/site/ci/build")
        self.assertEqual([(row.cause, row.ended) for row in rows[-2:]],
                         [(CAUSE_LINE_SEEN_ENDED, ENDED_GONE), (CAUSE_REMOVED, "")])
        self.assertEqual(self.tree.acknowledgments(), ({}, {}))


class SetTests(_Estate):
    """Where a seen may be set, what it is bound to, and its edit."""

    def test_it_is_bound_to_the_failure_it_accepts(self):
        pin = self.seen("/site/ci/build", "lint")
        self.assertEqual((pin.kind, pin.status, pin.expires_at), (SEEN, WARN, None))

    def test_nothing_failing_takes_none(self):
        for path, slug in (("/site/web/cpu", ""), ("/site/ci/build", "docs"),
                           ("/site/ci/build", ""), ("/site/ci/build", "gone"),
                           ("/nowhere", "")):
            write = self.tree.set_acknowledgment(path, slug, SEEN, "",
                                                 expires_at=None)
            self.assertFalse(write.applied, (path, slug))
            self.assertTrue(write.problem, (path, slug))
        self.assertEqual(self.tree.acknowledgments(), ({}, {}))

    def test_maintenance_takes_none(self):
        self.tree.set_maintenance("/site/web", "rewiring",
                                  expires_at=datetime.now(UTC) + LATER)
        self.assertIn("from /site/web",
                      self.tree.acknowledgeable("/site/web/disk"))
        self.tree.set_entry_maintenance("/site/ci/build", "test", "swap",
                                        expires_at=datetime.now(UTC) + LATER)
        self.assertIn("maintenance",
                      self.tree.acknowledgeable("/site/ci/build", "test"))
        self.assertEqual(self.tree.acknowledgeable("/site/ci/build", "lint"), "")

    def test_its_set_is_a_row_and_a_node_s_changes_nothing_it_shows(self):
        self.seen("/site/web/disk", note="the disk is on order")
        row = self.rows("/site/web/disk")[-1]
        self.assertEqual((row.old, row.new, row.cause, row.reason, row.shown),
                         (ERROR, ERROR, CAUSE_SEEN_SET, ("the disk is on order",),
                          True))
        period = self.tree.period("/site/web")
        assert period is not None
        self.assertEqual((period.code, period.began.cause, period.by),
                         (OK, CAUSE_SEEN_SET, "/site/web/disk"))
        self.assertEqual([one.code for one in self.tree.history("/site/web/disk")],
                         [ERROR])

    def test_a_line_s_set_moves_what_its_node_shows(self):
        self.seen("/site/ci/build", "test", note="flaky, ticket 12")
        row = self.rows("/site/ci/build")[-1]
        self.assertEqual((row.old, row.new, row.cause),
                         (ERROR, WARN, CAUSE_LINE_SEEN_SET))
        self.assertEqual(row.reason, ("test reads error", "flaky, ticket 12"))

    def test_an_edit_keeps_what_it_is_bound_to(self):
        pin = self.seen("/site/web/disk", note="first")
        write = self.tree.set_acknowledgment(
            "/site/web/disk", "", SEEN, "second", expires_at=None, set_by="ben",
            expected_set_at=pin.token)
        assert write.current is not None
        self.assertTrue(write.applied)
        self.assertEqual((write.current.id, write.current.status,
                          write.current.created_by, write.current.set_by),
                         (pin.id, ERROR, "ada", "ben"))
        self.assertEqual(self.rows("/site/web/disk")[-1].cause, CAUSE_SEEN_EDITED)
        again = self.tree.set_acknowledgment(
            "/site/web/disk", "", SEEN, "second", expires_at=None, set_by="cy",
            expected_set_at=write.current.token)
        self.assertFalse(again.applied)
        self.assertFalse(again.refused)

    def test_a_stale_token_is_refused(self):
        self.seen("/site/web/disk")
        write = self.tree.set_acknowledgment("/site/web/disk", "", SEEN, "x",
                                             expires_at=None, expected_set_at="")
        self.assertTrue(write.refused)

    def test_many_parts_at_once_each_its_own(self):
        node = self.tree.snapshot("/site")
        assert node is not None
        parts = acknowledgeable_parts(node)
        self.assertEqual([(part.path, part.slug) for part in parts],
                         [("/site/ci/build", "test"), ("/site/ci/build", "lint"),
                          ("/site/web/disk", "")])
        self.tree.upsert("/site/ci/build", WARN, _lines(test=OK, lint=WARN),
                         members=True)
        answers = self.tree.set_acknowledgments(
            [(part.path, part.slug) for part in parts], SEEN, "all of it",
            expires_at=None, set_by="ada")
        self.assertEqual([(path, slug, pin is not None)
                          for path, slug, pin, _problem in answers],
                         [("/site/ci/build", "test", False),
                          ("/site/ci/build", "lint", True),
                          ("/site/web/disk", "", True)])
        self.assertIs(self.code("/site"), OK)

    def test_the_parts_leave_out_what_maintenance_or_a_seen_holds(self):
        self.tree.set_maintenance("/site/web", "rewiring",
                                  expires_at=datetime.now(UTC) + LATER)
        self.seen("/site/ci/build", "test")
        node = self.tree.snapshot("/site")
        assert node is not None
        self.assertEqual([(part.path, part.slug)
                          for part in acknowledgeable_parts(node)],
                         [("/site/ci/build", "lint")])
        self.assertEqual(parts_digest(acknowledgeable_parts(node)),
                         parts_digest([("/site/ci/build", "lint")]))

    def test_a_stale_reading_alone_is_no_failure_to_accept(self):
        self.tree.upsert("/site/web/cpu", OK, frequency_seconds=60)
        later = datetime.now(UTC) + timedelta(minutes=10)
        node = self.tree.snapshot("/site/web", now=later)
        assert node is not None
        self.assertNotIn("/site/web/cpu",
                         [part.path for part in acknowledgeable_parts(node)])


class HeldBackTests(_Estate):
    """What a seen keeps from climbing is marked with its kind, as damping's rows."""

    def test_a_reading_a_seen_node_kept_from_its_parent_is_marked(self):
        self.seen("/site/web/disk")
        self.tree.upsert("/site/web/disk", WARN, "disk 90 % full")
        row = self.rows("/site/web/disk")[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by, row.shown),
                         (ERROR, WARN, SEEN, True))

    def test_a_reading_beneath_a_seen_line_is_its_kind_s(self):
        self.seen("/site/ci/build", "test")
        self.seen("/site/ci/build", "lint")
        self.tree.upsert("/site/ci/build", WARN, _lines(test=WARN, lint=WARN),
                         members=True)
        row = self.rows("/site/ci/build")[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by, row.shown),
                         (ERROR, WARN, SEEN, False))


class TreatmentTests(_Estate):
    """What a chip, a branch's *why* and the handled count say of a seen part."""

    def test_a_chip_counts_its_true_color_and_says_it_is_seen(self):
        self.seen("/site/web/disk")
        self.seen("/site/ci/build", "test")
        site = self.tree.snapshot("/site")
        assert site is not None
        self.assertEqual(handled_beneath(site), {SEEN: 2})
        counts = chip_counts(site)
        self.assertEqual(counts.counts["error"], 1)
        self.assertIn("2 handled: 2 seen", counts.words)

    def test_the_why_card_lists_each_by_its_job(self):
        self.seen("/site/web/disk")
        self.seen("/site/ci/build", "test")
        site = self.tree.snapshot("/site")
        assert site is not None
        handled = rules_beneath(site)
        self.assertEqual([(rule.path, rule.slug, rule.job, rule.reads)
                          for rule in handled],
                         [("/site/ci/build", "test", SEEN, ERROR),
                          ("/site/web/disk", "", SEEN, ERROR)])


class KeptTests(TestCase):
    """The pins file keeps a seen as it keeps a pin."""

    def test_a_seen_round_trips_without_an_end(self):
        pin = Pin(SEEN, "", datetime(2026, 10, 24, 9, tzinfo=UTC), None, "ada",
                  occurrence="run 7/1", status=ERROR)
        said = pin.to_dict()
        self.assertNotIn("expires_at", said)
        self.assertEqual((said["occurrence"], said["status"]), ("run 7/1", "ERROR"))
        self.assertEqual(Pin.from_dict(said), pin)
        self.assertEqual(Pin.from_dict(said).note, "")

    def test_a_seen_is_set_at_a_failure(self):
        with self.assertRaises(ValueError):
            Pin(SEEN, "", datetime(2026, 10, 24, tzinfo=UTC), None, status=OK)
        with self.assertRaises(ValueError):
            Pin(MAINTENANCE, "x", datetime(2026, 10, 24, tzinfo=UTC), None)

    def test_a_place_holds_one_of_each(self):
        at = "2026-10-24T09:00:00Z"
        seen = {"path": "/a", "slug": "", "id": "1", "kind": SEEN, "note": "",
                "set_at": at, "status": "ERROR"}
        pin = {"path": "/a", "slug": "", "id": "2", "kind": MAINTENANCE,
               "note": "x", "set_at": at, "expires_at": "2026-10-25T09:00:00Z"}
        held = PinStore.tables({"pins": [seen, pin]})
        self.assertEqual((list(held.nodes), list(held.acknowledged)), (["/a"], ["/a"]))
        with self.assertRaisesRegex(ValueError, "two acknowledgments on /a"):
            PinStore.tables({"pins": [seen, {**seen, "id": "3"}]})

    def test_an_end_s_why_round_trips(self):
        row = Event("/a", "a", ERROR, ERROR, (), datetime(2026, 10, 24, tzinfo=UTC),
                    cause=CAUSE_SEEN_ENDED, reported=ERROR, ended=ENDED_WORSENING)
        self.assertEqual(Event.from_dict(row.to_dict()), row)
        self.assertNotIn("ended", replace(row, ended="").to_dict())

    def test_a_restart_ends_one_that_reached_its_end_there(self):
        tree = StatusTree()
        old = datetime(2026, 10, 24, 9, tzinfo=UTC)
        ran_out = Pin(SEEN, "", old, old + timedelta(hours=1), "ada", status=ERROR)
        stands = Pin(SEEN, "", old, None, "ada", status=WARN)
        tree.restore_acknowledgments({"/a": ran_out}, {("/b", "x"): stands})
        self.assertEqual(tree.acknowledgments(), ({}, {("/b", "x"): stands}))
        (row,) = tree.recent_events()
        self.assertEqual((row.path, row.cause, row.ended, row.timestamp),
                         ("/a", CAUSE_SEEN_ENDED, ENDED_CLOCK,
                          old + timedelta(hours=1)))


class OccurrenceTests(TestCase):
    """What tells one occurrence from the next, as a line carries it."""

    def test_an_entry_s_occurrence_travels_and_is_bounded(self):
        self.assertEqual(Entry("a", "a", occurrence="run 1/1").occurrence, "run 1/1")
        with self.assertRaises(ValueError):
            Entry("a", "a", occurrence="x\ny")
        self.assertEqual(CAUSE_LINE_SEEN_SET, "line-seen-set")
