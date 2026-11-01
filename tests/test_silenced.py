"""A failure silenced keeps its true color and counts above at most at the level the
silence holds it at — as ``OK``, or at most as ``WARN`` — through every recovery, until
its deadline or a person's hand (ADR-0144).

The tree's half of *silenced*: what a line's and a node's own silence do to what is
counted, and beside a configured rule, where the stricter counts; what ends one and
what does not; the row each act writes, a kind changed in one write among them; where
a silence may be set — any part that could fail, failing or not, but one in
maintenance or held already; and the pins file, the event log, the replay and the
envelope that carry it.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase

from little_sister import api, instants
from little_sister.aggregation import ALL, AggregationRule, RuleSet
from little_sister.pins import MAINTENANCE, SEEN, SILENCED, Pin, PinStore
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import (
    ACKNOWLEDGMENT_CAUSES,
    AGGREGATION_RULE,
    CAUSE_LINE_SEEN_ENDED,
    CAUSE_LINE_SILENCED_ENDED,
    CAUSE_LINE_SILENCED_SET,
    CAUSE_SEEN_SET,
    CAUSE_SILENCED_EDITED,
    CAUSE_SILENCED_ENDED,
    CAUSE_SILENCED_SET,
    ENDED_CLOCK,
    ENDED_HAND,
    ENDED_MADE,
    SILENCED_RULE,
    Contribution,
    Event,
    ReasonLine,
    StatusSnapshot,
    StatusTree,
    acknowledgeable_parts,
    chip_counts,
    failing_first,
    handled_beneath,
    line_contribution,
    line_healthy,
    rules_beneath,
)
from tests.test_aggregation_tree import CAP, FLOOR, HEAL, QUIET, coded, rule

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
WEEK = timedelta(days=7)


def estate(*rules: AggregationRule) -> StatusTree:
    """A host whose disk fails for itself, a build whose lines are members, and a
    healthy neighbour, under one site — with ``rules`` configured."""
    tree = StatusTree()
    if rules:
        tree.use_aggregation(RuleSet(rules))
    tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
    tree.upsert("/site/web/cpu", OK)
    coded(tree, "/site/ci/build", test=ERROR, lint=WARN, docs=OK)
    return tree


class _Estate(TestCase):

    def setUp(self) -> None:
        self.tree = estate()
        self.deadline = datetime.now(UTC) + WEEK

    def silence(self, path: str, slug: str = "", *, level: StatusCode = OK,
                note: str = "it flaps", deadline: datetime | None = None,
                by: str = "ada") -> Pin:
        write = self.tree.set_acknowledgment(
            path, slug, SILENCED, note, expires_at=deadline or self.deadline,
            set_by=by, level=level)
        self.assertTrue(write.applied, write.problem)
        assert write.current is not None
        return write.current

    def seen(self, path: str, slug: str = "") -> Pin:
        write = self.tree.set_acknowledgment(path, slug, SEEN, "looked into",
                                             expires_at=None, set_by="ada")
        self.assertTrue(write.applied, write.problem)
        assert write.current is not None
        return write.current

    def node(self, path: str) -> StatusSnapshot:
        found = self.tree.snapshot(path)
        assert found is not None, path
        return found

    def code(self, path: str) -> StatusCode:
        return self.node(path).code

    @staticmethod
    def line(node: StatusSnapshot, slug: str) -> ReasonLine:
        return next(line for line in node.reasons if line.slug == slug)

    @staticmethod
    def child(node: StatusSnapshot, name: str) -> StatusSnapshot:
        return next(child for child in node.children if child.name == name)

    def rows(self, path: str) -> list[Event]:
        return [event for event in self.tree.recent_events() if event.path == path]

    def ended(self, path: str) -> list[Event]:
        return [row for row in self.rows(path) if row.ended]


class LineTests(_Estate):
    """A line's silence: the line keeps its color, its node counts it at the level."""

    def test_a_line_silenced_at_ok_keeps_its_color_and_its_node_counts_it_ok(self):
        pin = self.silence("/site/ci/build", "test")
        build = self.node("/site/ci/build")
        test = self.line(build, "test")
        self.assertIs(test.code, ERROR)
        self.assertTrue(test.accepted)
        self.assertEqual(line_contribution(test, build),
                         Contribution(OK, SILENCED_RULE, pin.id))
        self.assertIs(build.own_code, WARN)      # lint's, which nobody silenced
        self.assertIs(self.code("/site/ci"), WARN)

    def test_at_most_amber_counts_an_error_amber_and_a_warning_as_it_is(self):
        coded(self.tree, "/site/ci/build", test=ERROR, lint=OK)
        pin = self.silence("/site/ci/build", "test", level=WARN)
        build = self.node("/site/ci/build")
        self.assertIs(build.own_code, WARN)
        self.assertEqual(line_contribution(self.line(build, "test"), build),
                         Contribution(WARN, SILENCED_RULE, pin.id))
        coded(self.tree, "/site/ci/build", test=WARN, lint=OK)
        build = self.node("/site/ci/build")
        self.assertIsNone(line_contribution(self.line(build, "test"), build))
        self.assertIs(build.own_code, WARN)

    def test_it_comes_after_the_failures_nobody_has_acknowledged(self):
        self.silence("/site/ci/build", "test")
        build = self.node("/site/ci/build")
        self.assertEqual([line.slug for line in failing_first(build.reasons)],
                         ["lint", "test", "docs"])

    def test_a_silenced_line_that_recovered_is_no_healthy_one_while_it_stands(self):
        self.silence("/site/ci/build", "test")
        coded(self.tree, "/site/ci/build", test=OK, lint=WARN, docs=OK)
        build = self.node("/site/ci/build")
        self.assertFalse(line_healthy(build, self.line(build, "test")))
        self.assertTrue(line_healthy(build, self.line(build, "docs")))


class NodeTests(_Estate):
    """A node's own silence: it keeps its color, its parent counts it at the level."""

    def test_a_node_silenced_at_most_amber_keeps_its_color_and_counts_amber(self):
        pin = self.silence("/site/web/disk", level=WARN)
        disk = self.node("/site/web/disk")
        self.assertIs(disk.code, ERROR)
        self.assertEqual(disk.acknowledgment, pin)
        self.assertEqual(disk.contribution, Contribution(WARN, SILENCED_RULE, pin.id))
        self.assertIs(self.code("/site/web"), WARN)

    def test_a_node_silenced_at_ok_counts_ok(self):
        self.silence("/site/web/disk")
        self.assertIs(self.code("/site/web"), OK)

    def test_a_failure_beneath_a_silenced_branch_still_climbs(self):
        self.tree.upsert("/site/web", ERROR, "the web tier is slow")
        self.silence("/site/web")
        web = self.node("/site/web")
        self.assertIs(web.code, ERROR)
        self.assertIsNone(web.contribution)
        self.tree.upsert("/site/web/disk", OK)
        web = self.node("/site/web")
        self.assertEqual((web.code, web.counted), (ERROR, OK))

    def test_a_stale_reading_counts_at_least_a_warning(self):
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full",
                         frequency_seconds=60)
        self.silence("/site/web/disk")
        later = datetime.now(UTC) + timedelta(minutes=10)
        web = self.tree.snapshot("/site/web", now=later)
        assert web is not None
        self.assertIs(web.code, WARN)

    def test_maintenance_on_it_wins_and_is_the_rule_named_beside_a_cap(self):
        # the pin withholds the node, so neither the silence nor the configured rule
        # at its boundary has anything to count, and the pin is the one named
        self.tree = estate(rule("disk advises", "/site/web/disk", CAP))
        self.silence("/site/web/disk")
        self.tree.set_maintenance("/site/web/disk", "swap", expires_at=self.deadline)
        pin = self.tree.maintenance_entry("/site/web/disk")
        assert pin is not None
        disk = self.node("/site/web/disk")
        self.assertEqual(disk.contribution, Contribution(None, MAINTENANCE, pin.id))
        assert disk.rule is not None
        self.assertFalse(disk.rule.changes)


class HoldTests(_Estate):
    """A silence holds through what ends a *seen*, and ends at its deadline or by a
    person's hand alone — each end a row of its node saying why."""

    def test_it_holds_through_every_recovery_and_every_return(self):
        pin = self.silence("/site/ci/build", "test", level=WARN)
        for code in (OK, ERROR, WARN, OK, ERROR):
            coded(self.tree, "/site/ci/build", test=code, lint=WARN, docs=OK)
            self.assertEqual(self.tree.acknowledgment("/site/ci/build", "test"), pin)
        self.assertEqual(self.ended("/site/ci/build"), [])
        self.assertIs(self.node("/site/ci/build").own_code, WARN)

    def test_a_node_s_holds_through_its_recovery_and_its_worsening(self):
        self.tree.upsert("/site/web/disk", WARN, "disk 90 % full")
        pin = self.silence("/site/web/disk")
        for code in (OK, ERROR, WARN):
            self.tree.upsert("/site/web/disk", code, f"disk reads {code.name}")
            self.assertEqual(self.tree.acknowledgment("/site/web/disk"), pin)
            self.assertIs(self.code("/site/web"), OK)
        self.assertEqual(self.ended("/site/web/disk"), [])

    def test_a_new_occurrence_ends_none(self):
        self.tree.upsert("/site/ci/build", ERROR, [
            Entry("test", "test failed", code=ERROR, occurrence="run 7/1")],
            members=True)
        pin = self.silence("/site/ci/build", "test")
        self.assertEqual(pin.occurrence, "")
        self.tree.upsert("/site/ci/build", ERROR, [
            Entry("test", "test failed", code=ERROR, occurrence="run 8/1")],
            members=True)
        self.assertEqual(self.tree.acknowledgment("/site/ci/build", "test"), pin)

    def test_a_line_no_longer_reported_leaves_it_suspended(self):
        pin = self.silence("/site/ci/build", "test", level=WARN)
        coded(self.tree, "/site/ci/build", lint=WARN)
        self.assertEqual(self.tree.acknowledgment("/site/ci/build", "test"), pin)
        self.assertEqual(self.ended("/site/ci/build"), [])
        coded(self.tree, "/site/ci/build", test=ERROR, lint=OK)
        self.assertIs(self.node("/site/ci/build").own_code, WARN)

    def test_a_removal_keeps_it_against_the_path_until_its_deadline(self):
        pin = self.silence("/site/web/disk", level=WARN)
        self.tree.prune("/site/web", ())
        self.assertIsNone(self.tree.snapshot("/site/web/disk"))
        self.assertEqual(self.tree.acknowledgment("/site/web/disk"), pin)
        self.assertEqual(self.ended("/site/web/disk"), [])
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.assertIs(self.code("/site/web"), WARN)

    def test_its_deadline_ends_it(self):
        soon = datetime.now(UTC) + timedelta(minutes=5)
        self.silence("/site/web/disk", level=WARN, deadline=soon)
        self.tree.sweep_expired(soon + timedelta(seconds=1))
        self.assertIsNone(self.tree.acknowledgment("/site/web/disk"))
        (row,) = self.ended("/site/web/disk")
        self.assertEqual((row.cause, row.ended, row.level),
                         (CAUSE_SILENCED_ENDED, ENDED_CLOCK, WARN))
        self.assertIs(self.code("/site/web"), ERROR)

    def test_a_hand_ends_it(self):
        pin = self.silence("/site/ci/build", "test")
        write = self.tree.clear_acknowledgment("/site/ci/build", "test",
                                               expected_set_at=pin.token)
        self.assertTrue(write.applied)
        row = self.rows("/site/ci/build")[-1]
        self.assertEqual((row.old, row.new, row.cause, row.ended, row.level),
                         (WARN, ERROR, CAUSE_LINE_SILENCED_ENDED, ENDED_HAND, OK))

    def test_a_restart_ends_one_whose_deadline_passed_while_it_was_down(self):
        tree = StatusTree()
        old = datetime(2026, 10, 24, 9, tzinfo=UTC)
        ran_out = Pin(SILENCED, "it flaps", old, old + timedelta(days=1), "ada",
                      level=WARN)
        stands = Pin(SILENCED, "it flaps", old, datetime.now(UTC) + WEEK, "ada",
                     level=OK)
        tree.restore_acknowledgments({"/a": ran_out}, {("/b", "x"): stands})
        self.assertEqual(tree.acknowledgments(), ({}, {("/b", "x"): stands}))
        (row,) = tree.recent_events()
        self.assertEqual((row.path, row.cause, row.ended, row.timestamp, row.level),
                         ("/a", CAUSE_SILENCED_ENDED, ENDED_CLOCK,
                          old + timedelta(days=1), WARN))


class SetTests(_Estate):
    """Where a silence may be set, what it is bound to, and its edit."""

    def test_it_is_bound_to_its_deadline_and_its_level_and_to_no_failure(self):
        pin = self.silence("/site/ci/build", "lint", level=WARN)
        self.assertEqual(
            (pin.kind, pin.level, pin.expires_at, pin.status, pin.occurrence),
            (SILENCED, WARN, self.deadline, None, ""))

    def test_an_ok_part_takes_one_that_counts_from_its_next_failure(self):
        # bound to no failure (decision 1): a line and a leaf that read ok take one,
        # which changes nothing while they do
        line = self.silence("/site/ci/build", "docs", level=WARN)
        leaf = self.silence("/site/web/cpu")
        build, web = self.node("/site/ci/build"), self.node("/site/web")
        self.assertIsNone(line_contribution(self.line(build, "docs"), build))
        self.assertIsNone(self.child(web, "cpu").contribution)
        self.assertIs(build.own_code, ERROR)          # test's, which nobody silenced
        self.assertIs(web.code, ERROR)                # disk's
        # a later failure counts at the silence's level, nothing ending it
        coded(self.tree, "/site/ci/build", test=OK, lint=OK, docs=ERROR)
        self.tree.upsert("/site/web/disk", OK, "disk 60 % full")
        self.tree.upsert("/site/web/cpu", ERROR, "load 40")
        build, web = self.node("/site/ci/build"), self.node("/site/web")
        self.assertEqual(line_contribution(self.line(build, "docs"), build),
                         Contribution(WARN, SILENCED_RULE, line.id))
        self.assertIs(build.own_code, WARN)
        cpu = self.child(web, "cpu")
        self.assertEqual((cpu.code, cpu.contribution),
                         (ERROR, Contribution(OK, SILENCED_RULE, leaf.id)))
        self.assertIs(web.code, OK)
        self.assertEqual(self.tree.acknowledgments(),
                         ({"/site/web/cpu": leaf}, {("/site/ci/build", "docs"): line}))
        self.assertEqual(self.ended("/site/ci/build") + self.ended("/site/web/cpu"),
                         [])

    def test_a_part_held_already_or_in_maintenance_takes_none(self):
        # the refusals that stay: a part in maintenance — its own pin, one above it,
        # its check's word — one a person holds already, a node read by its lines,
        # and a path no node stands at
        self.tree.upsert("/site/db", OK, "up")
        self.tree.upsert("/site/vendor", StatusCode.MAINTENANCE, "the vendor's window")
        self.tree.set_maintenance("/site/db", "moving it", expires_at=self.deadline)
        self.tree.set_maintenance("/site/web", "new racks", expires_at=self.deadline)
        self.tree.set_entry_maintenance("/site/ci/build", "docs", "",
                                        expires_at=self.deadline)
        seen = self.seen("/site/ci/build", "test")
        silence = self.silence("/site/ci/build", "lint")
        for path, slug, why in (
                ("/site/db", "", "/site/db is in maintenance"),
                ("/site/web/cpu", "", "/site/web/cpu is in maintenance from /site/web"),
                ("/site/vendor", "", "/site/vendor reads maintenance now"),
                ("/site/ci/build", "docs", "its line docs is in maintenance"),
                ("/site/ci/build", "test", "its line test is seen already"),
                ("/site/ci/build", "lint", "its line lint is silenced already"),
                ("/site/ci/build", "", "/site/ci/build reads by its lines"),
                ("/nowhere", "", "nothing reports /nowhere now")):
            with self.subTest(path=path, slug=slug):
                self.assertTrue(self.tree.acknowledgeable(path, slug, SILENCED)
                                .startswith(why))
                written = self.tree.set_acknowledgments(
                    [(path, slug)], SILENCED, "", expires_at=self.deadline, level=OK)
                self.assertEqual([(pin, problem[:len(why)])
                                  for _path, _slug, pin, problem in written],
                                 [(None, why)])
        self.assertEqual(self.tree.acknowledgments(),
                         ({}, {("/site/ci/build", "test"): seen,
                               ("/site/ci/build", "lint"): silence}))

    def test_a_silence_without_a_deadline_or_a_level_writes_nothing(self):
        for deadline, level in ((None, WARN), (self.deadline, None),
                                (self.deadline, ERROR)):
            with self.subTest(deadline=deadline, level=level), \
                    self.assertRaises(ValueError):
                self.tree.set_acknowledgment("/site/web/disk", "", SILENCED, "",
                                             expires_at=deadline, level=level)
        with self.assertRaises(ValueError):
            self.tree.set_acknowledgments(
                [("/site/ci/build", "test"), ("/site/web/disk", "")], SILENCED, "",
                expires_at=None, level=OK)
        with self.assertRaises(ValueError):
            self.tree.set_acknowledgment("/site/web/disk", "", SEEN, "",
                                         expires_at=None, level=WARN)
        self.assertEqual(self.tree.acknowledgments(), ({}, {}))
        self.assertEqual([row for row in self.tree.recent_events()
                          if row.cause in ACKNOWLEDGMENT_CAUSES], [])

    def test_its_set_is_a_row_that_says_its_level(self):
        self.silence("/site/web/disk", level=WARN, note="the vendor patches friday")
        row = self.rows("/site/web/disk")[-1]
        self.assertEqual((row.old, row.new, row.cause, row.reason, row.level),
                         (ERROR, ERROR, CAUSE_SILENCED_SET,
                          ("the vendor patches friday",), WARN))
        period = self.tree.period("/site/web")
        assert period is not None
        self.assertEqual((period.code, period.began.cause, period.by),
                         (WARN, CAUSE_SILENCED_SET, "/site/web/disk"))

    def test_a_line_s_set_moves_what_its_node_shows(self):
        self.silence("/site/ci/build", "test", note="a flaky runner")
        row = self.rows("/site/ci/build")[-1]
        self.assertEqual((row.old, row.new, row.cause, row.level),
                         (ERROR, WARN, CAUSE_LINE_SILENCED_SET, OK))
        self.assertEqual(row.reason, ("test reads error", "a flaky runner"))

    def test_an_edit_moves_its_level_or_its_deadline_and_keeps_its_id(self):
        pin = self.silence("/site/web/disk")
        self.assertIs(self.code("/site/web"), OK)
        write = self.tree.set_acknowledgment(
            "/site/web/disk", "", SILENCED, "it flaps", expires_at=self.deadline,
            set_by="ben", expected_set_at=pin.token, level=WARN)
        self.assertTrue(write.applied, write.problem)
        amber = write.current
        assert amber is not None
        self.assertEqual((amber.id, amber.created_by, amber.set_by, amber.level),
                         (pin.id, "ada", "ben", WARN))
        row = self.rows("/site/web/disk")[-1]
        self.assertEqual((row.cause, row.level), (CAUSE_SILENCED_EDITED, WARN))
        self.assertIs(self.code("/site/web"), WARN)
        later = self.deadline + WEEK
        write = self.tree.set_acknowledgment(
            "/site/web/disk", "", SILENCED, "it flaps", expires_at=later,
            set_by="cy", expected_set_at=amber.token, level=WARN)
        self.assertTrue(write.applied, write.problem)
        extended = write.current
        assert extended is not None
        self.assertEqual((extended.id, extended.expires_at), (pin.id, later))
        again = self.tree.set_acknowledgment(
            "/site/web/disk", "", SILENCED, "it flaps", expires_at=later,
            set_by="cy", expected_set_at=extended.token, level=WARN)
        self.assertEqual((again.applied, again.refused), (False, False))

    def test_a_head_s_check_silences_every_failing_part_each_its_own(self):
        parts = acknowledgeable_parts(self.node("/site"))
        answers = self.tree.set_acknowledgments(
            [(part.path, part.slug) for part in parts], SILENCED, "a noisy week",
            expires_at=self.deadline, set_by="ada", level=WARN)
        pins = [pin for _path, _slug, pin, _problem in answers]
        self.assertEqual([(path, slug) for path, slug, _pin, _problem in answers],
                         [("/site/ci/build", "test"), ("/site/ci/build", "lint"),
                          ("/site/web/disk", "")])
        self.assertEqual([(pin.kind, pin.level) for pin in pins if pin is not None],
                         [(SILENCED, WARN)] * 3)
        self.assertEqual(len({pin.id for pin in pins if pin is not None}), 3)
        self.assertIs(self.code("/site"), WARN)
        self.assertEqual(acknowledgeable_parts(self.node("/site")), ())


class KindTests(_Estate):
    """A block's pencil that changes the kind ends the one standing and sets another
    in its place, in one write: the end's row says it was made the other kind, and the
    new one has an id and a creation of its own, bound to what its kind needs."""

    def test_a_seen_made_a_silence_is_ended_and_a_new_one_set(self):
        coded(self.tree, "/site/ci/build", test=ERROR, lint=OK)
        seen = self.seen("/site/ci/build", "test")
        self.assertIs(self.node("/site/ci/build").own_code, OK)
        write = self.tree.set_acknowledgment(
            "/site/ci/build", "test", SILENCED, "it flaps", expires_at=self.deadline,
            set_by="ben", expected_set_at=seen.token, level=WARN)
        self.assertTrue(write.applied, write.problem)
        made = write.current
        assert made is not None
        self.assertNotEqual(made.id, seen.id)
        self.assertEqual((made.kind, made.level, made.created_by, made.created_at,
                          made.status, made.occurrence),
                         (SILENCED, WARN, "ben", made.set_at, None, ""))
        self.assertNotEqual(made.created_at, seen.created_at)
        self.assertEqual(self.tree.acknowledgment("/site/ci/build", "test"), made)
        ended, now = self.rows("/site/ci/build")[-2:]
        self.assertEqual((ended.cause, ended.ended, ended.old, ended.new),
                         (CAUSE_LINE_SEEN_ENDED, ENDED_MADE[SILENCED], OK, OK))
        self.assertEqual((now.cause, now.old, now.new, now.level),
                         (CAUSE_LINE_SILENCED_SET, OK, WARN, WARN))
        self.assertEqual(ended.timestamp, now.timestamp)

    def test_a_silence_made_seen_is_bound_to_the_failure_as_it_stands(self):
        silence = self.silence("/site/web/disk", level=WARN)
        self.assertIs(self.code("/site/web"), WARN)
        write = self.tree.set_acknowledgment(
            "/site/web/disk", "", SEEN, "on order", expires_at=None, set_by="ben",
            expected_set_at=silence.token)
        self.assertTrue(write.applied, write.problem)
        seen = write.current
        assert seen is not None
        self.assertNotEqual(seen.id, silence.id)
        self.assertEqual((seen.kind, seen.status, seen.level, seen.expires_at),
                         (SEEN, ERROR, None, None))
        ended, now = self.rows("/site/web/disk")[-2:]
        self.assertEqual((ended.cause, ended.ended, ended.level),
                         (CAUSE_SILENCED_ENDED, ENDED_MADE[SEEN], WARN))
        self.assertEqual((now.cause, now.level), (CAUSE_SEEN_SET, None))
        self.assertIs(self.code("/site/web"), OK)

    def test_a_silence_made_seen_is_refused_where_nothing_fails(self):
        silence = self.silence("/site/ci/build", "test")
        coded(self.tree, "/site/ci/build", test=OK, lint=WARN, docs=OK)
        write = self.tree.set_acknowledgment(
            "/site/ci/build", "test", SEEN, "x", expires_at=None, set_by="ben",
            expected_set_at=silence.token)
        self.assertFalse(write.applied)
        self.assertIn("nothing fails", write.problem)
        self.assertEqual(write.current, silence)
        self.assertEqual(self.tree.acknowledgment("/site/ci/build", "test"), silence)
        self.assertEqual(self.ended("/site/ci/build"), [])

    def test_a_stale_token_refuses_the_change(self):
        self.silence("/site/web/disk")
        write = self.tree.set_acknowledgment("/site/web/disk", "", SEEN, "x",
                                             expires_at=None, expected_set_at="")
        self.assertTrue(write.refused)


class StricterTests(_Estate):
    """Where a person's silence and a configured rule meet on one part, the stricter
    counts — whichever counts it for less, the rule's where both count it the same —
    and ``contribution.by`` names the one that decided. Where the silence decided, the
    rule's own standing says it changes nothing."""

    def test_at_a_boundary_a_silence_beneath_the_cap_decides(self):
        self.tree = estate(rule("disk advises", "/site/web/disk", CAP))
        pin = self.silence("/site/web/disk")
        disk = self.node("/site/web/disk")
        self.assertEqual(disk.contribution, Contribution(OK, SILENCED_RULE, pin.id))
        assert disk.rule is not None
        self.assertEqual((disk.rule.reads, disk.rule.counts, disk.rule.changes),
                         (ERROR, ERROR, False))
        self.assertEqual(handled_beneath(self.node("/site")), {SILENCED: 1})

    def test_at_a_boundary_a_rule_beneath_the_silence_decides(self):
        self.tree = estate(rule("disk rests", "/site/web/disk", QUIET))
        self.silence("/site/web/disk", level=WARN)
        disk = self.node("/site/web/disk")
        self.assertEqual(disk.contribution,
                         Contribution(OK, AGGREGATION_RULE, "disk rests"))
        assert disk.rule is not None
        self.assertEqual((disk.rule.reads, disk.rule.counts, disk.rule.changes),
                         (ERROR, OK, True))
        site = self.node("/site")
        self.assertEqual(handled_beneath(site), {SILENCED: 1, "rule": 1})
        self.assertEqual([handled.job for handled in rules_beneath(site)],
                         [SILENCED, AGGREGATION_RULE])

    def test_where_both_count_it_the_same_the_rule_decides(self):
        self.tree = estate(rule("disk advises", "/site/web/disk", CAP))
        self.silence("/site/web/disk", level=WARN)
        self.assertEqual(self.node("/site/web/disk").contribution,
                         Contribution(WARN, AGGREGATION_RULE, "disk advises"))

    def test_a_floor_never_lifts_a_silenced_part_above_its_level(self):
        self.tree = estate(rule("disk matters", "/site/web/disk", FLOOR))
        self.tree.upsert("/site/web/disk", WARN, "disk 90 % full")
        self.assertIs(self.node("/site/web/disk").counted, ERROR)
        self.silence("/site/web/disk", level=WARN)
        disk = self.node("/site/web/disk")
        self.assertIs(disk.counted, WARN)
        self.assertIsNone(disk.contribution)
        assert disk.rule is not None
        self.assertFalse(disk.rule.changes)
        self.assertIs(self.code("/site/web"), WARN)

    def test_on_a_line_the_stricter_counts_and_the_rule_s_mark_says_which(self):
        self.tree = estate(rule("build advises", "/site/ci/build", CAP, lines=[ALL]))
        coded(self.tree, "/site/ci/build", test=ERROR, lint=OK)
        pin = self.silence("/site/ci/build", "test")
        build = self.node("/site/ci/build")
        test = self.line(build, "test")
        self.assertEqual(line_contribution(test, build),
                         Contribution(OK, SILENCED_RULE, pin.id))
        assert test.rule is not None
        self.assertEqual((test.rule.reads, test.rule.counts, test.rule.changes),
                         (ERROR, ERROR, False))
        self.assertIs(build.own_code, OK)
        # where the rule counts the line for less, the rule decides, and says so
        self.tree = estate(rule("build rests", "/site/ci/build", QUIET, lines=[ALL]))
        coded(self.tree, "/site/ci/build", test=ERROR, lint=OK)
        self.silence("/site/ci/build", "test", level=WARN)
        build = self.node("/site/ci/build")
        test = self.line(build, "test")
        self.assertEqual(line_contribution(test, build),
                         Contribution(OK, AGGREGATION_RULE, "build rests"))
        assert test.rule is not None
        self.assertTrue(test.rule.changes)
        self.assertIs(build.own_code, OK)
        self.assertEqual([(handled.slug, handled.job)
                          for handled in rules_beneath(self.node("/site"))],
                         [("test", SILENCED), ("test", AGGREGATION_RULE)])
        self.assertEqual(handled_beneath(self.node("/site")),
                         {SILENCED: 1, "rule": 1})

    def test_a_rule_over_a_node_s_children_meets_a_silence_the_same_way(self):
        # a rule healing web's warnings is no rule healing the error the silence
        # holds at amber: the stricter of the two counts, the silence's
        self.tree = estate(rule("web heals", "/site/web", HEAL, children=[ALL]))
        pin = self.silence("/site/web/disk", level=WARN)
        disk = self.child(self.node("/site/web"), "disk")
        self.assertEqual(disk.contribution, Contribution(WARN, SILENCED_RULE, pin.id))
        assert disk.parent_rule is not None
        self.assertFalse(disk.parent_rule.changes)
        self.assertIs(self.code("/site/web"), WARN)
        period = self.tree.period("/site/web")
        assert period is not None
        self.assertIs(period.code, WARN)
        # and a floor over web's children lifts it above its level no more than one
        # at its own boundary does
        self.tree = estate(rule("web matters", "/site/web", FLOOR, children=[ALL]))
        self.tree.upsert("/site/web/disk", WARN, "disk 90 % full")
        self.assertIs(self.code("/site/web"), ERROR)
        self.silence("/site/web/disk", level=WARN)
        self.assertIs(self.code("/site/web"), WARN)
        period = self.tree.period("/site/web")
        assert period is not None
        self.assertIs(period.code, WARN)


class QuorumTests(_Estate):
    """A rule counting how many of a node's children fail counts a part a person
    holds toward its count as it reads, and the part itself still counts as held: a
    replica silenced while it flaps does not let a second one fail unseen. A node's
    lines are counted so too."""

    def pool(self) -> None:
        """Five replicas under one pool, of which one may be down: while fewer than
        two fail, an error counts as a warning."""
        self.tree = StatusTree()
        self.tree.use_aggregation(RuleSet((rule("one may be down", "/pool", CAP,
                                                children=[ALL], count=2),)))
        for name in ("r1", "r2", "r3", "r4", "r5"):
            self.tree.upsert(f"/pool/{name}", OK)

    def test_a_silenced_replica_counts_toward_the_quorum_as_it_reads(self):
        self.pool()
        self.tree.upsert("/pool/r1", ERROR, "down")
        pin = self.silence("/pool/r1")
        self.assertIs(self.code("/pool"), OK)
        self.tree.upsert("/pool/r2", ERROR, "down too")
        pool = self.node("/pool")
        self.assertIs(pool.code, ERROR)
        assert pool.children_rule is not None
        self.assertEqual(pool.children_rule.failing, 2)
        # the silenced replica itself still counts as its silence holds it
        self.assertEqual(self.child(pool, "r1").contribution,
                         Contribution(OK, SILENCED_RULE, pin.id))
        period = self.tree.period("/pool")
        assert period is not None
        self.assertIs(period.code, ERROR)

    def test_one_held_at_most_amber_counts_as_it_reads_too(self):
        self.pool()
        self.tree.upsert("/pool/r1", ERROR, "down")
        self.silence("/pool/r1", level=WARN)
        self.assertIs(self.code("/pool"), WARN)
        self.tree.upsert("/pool/r2", ERROR, "down too")
        self.assertIs(self.code("/pool"), ERROR)

    def test_a_node_s_lines_are_counted_so_too(self):
        self.tree = estate(rule("one may fail", "/site/ci/build", CAP, lines=[ALL],
                                count=2))
        coded(self.tree, "/site/ci/build", test=ERROR, lint=OK, docs=OK)
        pin = self.silence("/site/ci/build", "test")
        self.assertIs(self.node("/site/ci/build").own_code, OK)
        coded(self.tree, "/site/ci/build", test=ERROR, lint=ERROR, docs=OK)
        build = self.node("/site/ci/build")
        self.assertIs(build.own_code, ERROR)
        self.assertEqual(line_contribution(self.line(build, "test"), build),
                         Contribution(OK, SILENCED_RULE, pin.id))


class HeldBackTests(_Estate):
    """What a silence keeps from climbing is marked with its kind, as damping's
    rows are."""

    def test_a_reading_a_silenced_node_kept_from_its_parent_is_marked(self):
        self.silence("/site/web/disk")
        self.tree.upsert("/site/web/disk", OK)
        self.tree.upsert("/site/web/disk", WARN, "disk 90 % full")
        recovery, reading = self.rows("/site/web/disk")[-2:]
        self.assertEqual((recovery.old, recovery.new, recovery.suppressed_by),
                         (ERROR, OK, ""))
        self.assertEqual((reading.old, reading.new, reading.suppressed_by,
                          reading.shown), (OK, WARN, SILENCED, True))

    def test_a_reading_beneath_a_silenced_line_is_its_kind_s(self):
        self.silence("/site/ci/build", "test", level=WARN)
        coded(self.tree, "/site/ci/build", test=OK, lint=WARN, docs=OK)
        coded(self.tree, "/site/ci/build", test=ERROR, lint=WARN, docs=OK)
        row = self.rows("/site/ci/build")[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by, row.shown),
                         (WARN, ERROR, SILENCED, False))


class TreatmentTests(_Estate):
    """What a chip and a branch's *why* say of a silenced part."""

    def test_a_chip_says_what_is_seen_and_what_is_silenced(self):
        self.seen("/site/web/disk")
        self.silence("/site/ci/build", "test")
        site = self.node("/site")
        self.assertEqual(handled_beneath(site), {SEEN: 1, SILENCED: 1})
        self.assertIn("2 handled: 1 seen, 1 silenced", chip_counts(site).words)

    def test_the_why_card_lists_each_by_its_job(self):
        self.silence("/site/web/disk", level=WARN)
        self.silence("/site/ci/build", "test")
        self.assertEqual([(handled.path, handled.slug, handled.job, handled.reads)
                          for handled in rules_beneath(self.node("/site"))],
                         [("/site/ci/build", "test", SILENCED, ERROR),
                          ("/site/web/disk", "", SILENCED, ERROR)])


class ReplayTests(_Estate):
    """A branch's history, replayed from the rows, reads each silence at the level
    its rows say."""

    def test_each_period_is_counted_at_the_level_that_stood(self):
        pin = self.silence("/site/web/disk")
        write = self.tree.set_acknowledgment(
            "/site/web/disk", "", SILENCED, "it flaps", expires_at=self.deadline,
            set_by="ada", expected_set_at=pin.token, level=WARN)
        assert write.current is not None
        self.tree.clear_acknowledgment("/site/web/disk",
                                       expected_set_at=write.current.token)
        ended, current = self.tree.shown_history("/site/web")
        assert current is not None
        self.assertIs(current.code, ERROR)
        self.assertEqual([(period.code, period.began.cause) for period in ended][:2],
                         [(WARN, CAUSE_SILENCED_EDITED), (OK, CAUSE_SILENCED_SET)])


class KeptTests(TestCase):
    """The pins file keeps a silence as it keeps a pin, and the log its level."""

    def test_a_silence_round_trips_with_its_deadline_and_its_level(self):
        pin = Pin(SILENCED, "it flaps", datetime(2026, 10, 24, 9, tzinfo=UTC),
                  datetime(2026, 10, 31, 9, tzinfo=UTC), "ada", level=WARN)
        said = pin.to_dict()
        self.assertEqual((said["level"], said["expires_at"]),
                         ("WARN", "2026-10-31T09:00:00Z"))
        self.assertNotIn("status", said)
        self.assertNotIn("occurrence", said)
        self.assertEqual(Pin.from_dict(said), pin)

    def test_a_silence_is_bound_to_a_deadline_and_a_level_alone(self):
        at = datetime(2026, 10, 24, 9, tzinfo=UTC)
        for expires, said in ((None, {"level": WARN}), (at, {}),
                              (at, {"level": ERROR}),
                              (at, {"level": WARN, "status": ERROR}),
                              (at, {"level": OK, "occurrence": "7/1"})):
            with self.subTest(expires=expires, said=said), \
                    self.assertRaises(ValueError):
                Pin(SILENCED, "", at, expires, **said)
        with self.assertRaises(ValueError):
            Pin(SEEN, "", at, None, status=ERROR, level=WARN)
        with self.assertRaises(ValueError):
            Pin(MAINTENANCE, "x", at, at, level=OK)

    def test_a_level_that_is_no_status_is_refused(self):
        said = Pin(SILENCED, "", datetime(2026, 10, 24, 9, tzinfo=UTC),
                   datetime(2026, 10, 31, 9, tzinfo=UTC), level=OK).to_dict()
        with self.assertRaisesRegex(ValueError, "level 'LOUD'"):
            Pin.from_dict({**said, "level": "LOUD"})

    def test_a_place_holds_one_acknowledgment_of_either_kind(self):
        at = "2026-10-24T09:00:00Z"
        seen = {"path": "/a", "slug": "", "id": "1", "kind": SEEN, "note": "",
                "set_at": at, "status": "ERROR"}
        silenced = {"path": "/a", "slug": "", "id": "2", "kind": SILENCED,
                    "note": "", "set_at": at, "expires_at": "2026-10-31T09:00:00Z",
                    "level": "OK"}
        self.assertEqual(list(PinStore.tables({"pins": [silenced]}).acknowledged),
                         ["/a"])
        with self.assertRaisesRegex(ValueError, "two acknowledgments on /a"):
            PinStore.tables({"pins": [seen, silenced]})

    def test_a_row_s_level_round_trips(self):
        row = Event("/a", "a", ERROR, ERROR, (), datetime(2026, 10, 24, tzinfo=UTC),
                    cause=CAUSE_SILENCED_SET, reported=ERROR, level=WARN)
        self.assertEqual(row.to_dict()["level"], "WARN")
        self.assertEqual(Event.from_dict(row.to_dict()), row)
        self.assertNotIn("level", replace(row, level=None).to_dict())
        with self.assertRaises(ValueError):
            Event.from_dict({**row.to_dict(), "level": "LOUD"})


class EnvelopeTests(_Estate):
    """The envelope lists a silence among what handles its part: its deadline, and
    what it makes its part count as in a configured rule's notation — one table per
    level — and nothing a *seen* is bound to."""

    def test_a_silence_is_listed_with_its_deadline_and_its_level_s_table(self):
        amber = self.silence("/site/web/disk", level=WARN)
        disk = api.snapshot_to_dict(self.node("/site/web/disk"))
        (item,) = disk["handled"]
        self.assertEqual(
            {key: item[key] for key in ("id", "kind", "source", "note", "counts_as",
                                        "expires_at")},
            {"id": amber.id, "kind": "silenced", "source": "person",
             "note": "it flaps", "counts_as": {"ERROR": "WARN"},
             "expires_at": instants.stamp(self.deadline)})
        self.assertNotIn("status", item)
        self.assertNotIn("occurrence", item)
        self.assertEqual(disk["contribution"],
                         {"code": "WARN", "by": "silenced", "rule": amber.id})
        green = self.silence("/site/ci/build", "test")
        build = api.snapshot_to_dict(self.node("/site/ci/build"))
        test = next(entry for entry in build["entries"]["items"]
                    if entry["slug"] == "test")
        (line_item,) = test["handled"]
        self.assertEqual(line_item["counts_as"], {"WARN": "OK", "ERROR": "OK"})
        self.assertEqual(test["contribution"],
                         {"code": "OK", "by": "silenced", "rule": green.id})
