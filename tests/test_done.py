"""An event looked into and over is closed as done: its line shows OK with the failure
it closed beside it and counts as OK above, until the line reads anything other than
that failure (ADR-0146).

The tree's half of *done*: what it does to its line, its node and what is counted above;
what ends it — another event, the same one recovered or worse, no line, a person's hand,
and never the clock — and the row each end writes; where one may be set and what a form
drawn on another event gets; the healthy fold, which takes it as the OK it shows; a kind
changed in one write; and the pins file and the envelope that carry it.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import TestCase

from little_sister import api
from little_sister.aggregation import ALL, RuleSet
from little_sister.pins import DONE, SEEN, SILENCED, Pin, PinStore
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import (
    CAUSE_LINE_DONE_ENDED,
    CAUSE_LINE_DONE_SET,
    CAUSE_READING,
    DONE_RULE,
    ENDED_GONE,
    ENDED_HAND,
    ENDED_MADE,
    ENDED_OCCURRENCE,
    ENDED_RECOVERY,
    ENDED_WORDS,
    ENDED_WORSENING,
    Event,
    ReasonLine,
    StatusSnapshot,
    StatusTree,
    chip_counts,
    failing_first,
    handled_beneath,
    healthy,
    line_contribution,
    line_counts_as,
    line_healthy,
    line_rail,
    line_shows,
    own_failure,
    pin_beneath,
    rules_beneath,
)
from tests.test_aggregation_tree import CAP, QUIET, rule

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
BUILD = "/site/ci/build"


def _lines(**codes: StatusCode | tuple[StatusCode, str]) -> list[Entry]:
    """A node's lines by slug, each its code — or its code and its occurrence."""
    lines = []
    for slug, said in codes.items():
        code, occurrence = said if isinstance(said, tuple) else (said, "")
        lines.append(Entry(slug, f"{slug} reads {code.name.lower()}", code=code,
                           occurrence=occurrence))
    return lines


class _Estate(TestCase):
    """A build whose lines are members — ``test`` a run with an occurrence of its own,
    ``lint`` a failing stretch nothing tells apart — and a healthy neighbour, under one
    site."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.tree.upsert("/site/web/cpu", OK)
        self.read(test=(ERROR, "run 7/1"), lint=WARN, docs=OK)

    def read(self, **codes: StatusCode | tuple[StatusCode, str]) -> None:
        worst = max((said if isinstance(said, StatusCode) else said[0]
                     for said in codes.values()),
                    key=lambda code: {OK: 0, WARN: 1, ERROR: 2}[code])
        self.tree.upsert(BUILD, worst, _lines(**codes), members=True)

    def done(self, slug: str = "test", note: str = "looked into: a flaky runner",
             occurrence: str | None = None) -> Pin:
        write = self.tree.set_acknowledgment(BUILD, slug, DONE, note,
                                             expires_at=None, set_by="ada",
                                             occurrence=occurrence)
        self.assertTrue(write.applied, write.problem)
        assert write.current is not None
        return write.current

    def node(self, path: str = BUILD) -> StatusSnapshot:
        found = self.tree.snapshot(path)
        assert found is not None, path
        return found

    def line(self, slug: str = "test") -> ReasonLine:
        return next(line for line in self.node().reasons if line.slug == slug)

    def rows(self) -> list[Event]:
        return [event for event in self.tree.recent_events() if event.path == BUILD]

    def ended(self) -> list[Event]:
        return [row for row in self.rows() if row.ended]


class LineTests(_Estate):
    """A done line shows OK with the failure it closed beside it, and counts as OK."""

    def test_it_is_bound_to_the_event_and_the_failure_it_closed(self):
        pin = self.done()
        self.assertEqual((pin.kind, pin.occurrence, pin.status, pin.expires_at),
                         (DONE, "run 7/1", ERROR, None))

    def test_the_line_shows_ok_and_still_reads_the_failure(self):
        self.done()
        node, line = self.node(), self.line()
        self.assertIs(line.code, ERROR)
        self.assertIs(line_shows(node, line), OK)
        self.assertEqual(line_counts_as(node, line), "ok")

    def test_its_node_counts_it_ok_by_done(self):
        self.done()
        node, line = self.node(), self.line()
        self.assertIs(node.own_code, WARN)
        contribution = line_contribution(line, node)
        assert contribution is not None and line.acknowledgment is not None
        self.assertEqual((contribution.code, contribution.by, contribution.rule),
                         (OK, DONE_RULE, line.acknowledgment.id))

    def test_a_node_whose_only_failure_is_done_reads_ok_above(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        self.assertIs(self.node().code, OK)
        self.assertIs(self.node("/site").code, OK)

    def test_it_draws_no_rail(self):
        self.done()
        self.assertIsNone(line_rail(self.node(), self.line()))

    def test_it_stands_among_what_shows_ok_in_a_box(self):
        self.done()
        order = [line.slug for line in failing_first(self.node().reasons)]
        self.assertEqual(order, ["lint", "test", "docs"])

    def test_a_stale_reading_counts_what_its_check_reported(self):
        # staleness escalates under every rule (ADR-0032 rule 6): a node whose
        # reading went stale counts its raw reading, the failure the done closed
        self.tree.upsert(BUILD, ERROR, _lines(test=(ERROR, "run 7/1"), docs=OK),
                         members=True, frequency_seconds=60)
        self.done()
        self.assertIs(self.node("/site").code, OK)
        later = datetime.now(UTC) + timedelta(minutes=10)
        site = self.tree.snapshot("/site", now=later)
        assert site is not None
        self.assertIs(site.code, ERROR)

    def test_it_spends_no_failure_budget(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.assertEqual(own_failure(self.node()), "error")
        self.done()
        self.assertIsNone(own_failure(self.node()))


class CountTests(_Estate):
    """A rule with a count counts a done as the OK it shows, on Lex's word of
    2026-10-29 (ADR-0146 decision 4): a seen or a silence holds a state that is still
    true and is counted as it reads, but a done's event is over. Counted as it reads,
    one done and one real failure would escalate under *one of five may fail*, and a
    workflow that never runs again would use up the allowance for good."""

    def ruled(self, *rules: object) -> None:
        """The estate anew, under ``rules``, its build failing in ``test`` and
        ``lint`` alike."""
        self.tree = StatusTree()
        self.tree.use_aggregation(RuleSet(rules))
        self.tree.upsert("/site/web/cpu", OK)
        self.read(test=(ERROR, "run 7/1"), lint=ERROR, docs=OK)

    def test_a_count_over_its_node_s_lines_takes_it_as_the_ok_it_shows(self):
        # one of the build's lines may fail: while fewer than two fail, an error
        # counts as a warning
        self.ruled(rule("one may fail", BUILD, CAP, lines=[ALL], count=2))
        self.assertIs(self.node().own_code, ERROR)
        self.done()
        build, lint = self.node(), self.line("lint")
        self.assertIs(build.own_code, WARN)
        assert lint.rule is not None
        self.assertEqual((lint.rule.failing, lint.rule.counts), (1, WARN))
        # what the node shows is one derivation: its row, and the period above it
        row = self.rows()[-1]
        self.assertEqual((row.old, row.new, row.cause),
                         (ERROR, WARN, CAUSE_LINE_DONE_SET))
        period = self.tree.period("/site/ci")
        assert period is not None
        self.assertIs(period.code, WARN)

    def test_a_done_a_reading_ended_is_counted_as_it_stood_by_the_row_it_moved(self):
        # while fewer than two lines fail, a failure counts as ok: the done line and
        # lint read ok together, and the done's end is what moves the node
        self.ruled(rule("one may fail", BUILD, QUIET, lines=[ALL], count=2))
        self.read(test=(WARN, "run 7/1"), lint=ERROR, docs=OK)
        self.done()
        self.assertIs(self.node().own_code, OK)
        self.read(test=(ERROR, "run 7/1"), lint=ERROR, docs=OK)
        self.assertIs(self.node().own_code, ERROR)
        moved = next(row for row in self.rows() if row.ended)
        self.assertEqual((moved.old, moved.new, moved.cause, moved.ended),
                         (OK, ERROR, CAUSE_LINE_DONE_ENDED, ENDED_WORSENING))

    def test_a_count_over_children_takes_a_node_whose_one_failure_is_done_as_ok(self):
        # one replica of five may be down: the one whose failure is done reads ok,
        # and is counted so — which the count did before this word as well, a done
        # standing on a line alone and its node showing what its lines count as
        self.tree = StatusTree()
        self.tree.use_aggregation(RuleSet((rule("one may be down", "/pool", CAP,
                                                children=[ALL], count=2),)))
        for name in ("r2", "r3", "r4", "r5"):
            self.tree.upsert(f"/pool/{name}", OK)
        self.tree.upsert("/pool/r1", ERROR,
                         _lines(probe=(ERROR, "run 7/1"), disk=OK), members=True)
        write = self.tree.set_acknowledgment("/pool/r1", "probe", DONE, "",
                                             expires_at=None, set_by="ada")
        self.assertTrue(write.applied, write.problem)
        self.tree.upsert("/pool/r2", ERROR, "down")
        pool = self.node("/pool")
        assert pool.children_rule is not None
        self.assertEqual((pool.code, pool.children_rule.failing), (WARN, 1))
        period = self.tree.period("/pool")
        assert period is not None
        self.assertIs(period.code, WARN)


class EndTests(_Estate):
    """A done ends when it no longer covers anything, judged on what its line reads."""

    def test_the_next_run_that_fails_is_a_new_occurrence_and_alarms_as_a_reading(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        self.assertIs(self.node().code, OK)
        self.read(test=(ERROR, "run 8/1"), docs=OK)
        self.assertIsNone(self.tree.acknowledgment(BUILD, "test"))
        *_, moved, end = self.rows()
        self.assertEqual((moved.old, moved.new, moved.cause, moved.ended),
                         (OK, ERROR, CAUSE_READING, ""))
        self.assertEqual((end.old, end.new, end.cause, end.ended),
                         (ERROR, ERROR, CAUSE_LINE_DONE_ENDED, ENDED_OCCURRENCE))

    def test_the_next_run_that_passes_is_a_new_occurrence_too(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        self.read(test=(OK, "run 8/1"), docs=OK)
        (end,) = self.ended()
        self.assertEqual((end.old, end.new, end.cause, end.ended),
                         (OK, OK, CAUSE_LINE_DONE_ENDED, ENDED_OCCURRENCE))

    def test_the_same_event_read_ok_recovered(self):
        self.done()
        self.read(test=(OK, "run 7/1"), lint=WARN, docs=OK)
        (end,) = self.ended()
        self.assertEqual(end.ended, ENDED_RECOVERY)

    def test_the_same_event_read_worse_got_worse_and_its_end_moves_the_node(self):
        self.read(test=(WARN, "run 7/1"), docs=OK)
        self.done()
        self.assertIs(self.node().code, OK)
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        (end,) = self.ended()
        self.assertEqual((end.old, end.new, end.cause, end.ended),
                         (OK, ERROR, CAUSE_LINE_DONE_ENDED, ENDED_WORSENING))

    def test_the_same_event_read_the_same_or_milder_holds(self):
        pin = self.done()
        for code in (ERROR, WARN, ERROR):
            self.read(test=(code, "run 7/1"), lint=WARN, docs=OK)
            self.assertEqual(self.tree.acknowledgment(BUILD, "test"), pin)
        self.assertEqual(self.ended(), [])

    def test_a_reading_of_it_the_node_did_not_show_is_marked_done(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        self.read(test=(WARN, "run 7/1"), docs=OK)
        row = self.rows()[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by, row.shown),
                         (ERROR, WARN, DONE, False))

    def test_the_reading_beside_its_end_at_a_worsening_is_marked_done(self):
        # beside the end's row is the check's own change, which the done hid until
        # this reading: the done's, where nothing was ever in maintenance
        self.read(test=(WARN, "run 7/1"), docs=OK)
        self.done()
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        end, beside = self.rows()[-2:]
        self.assertEqual((end.cause, end.ended),
                         (CAUSE_LINE_DONE_ENDED, ENDED_WORSENING))
        self.assertEqual((beside.old, beside.new, beside.cause, beside.suppressed_by,
                          beside.shown), (WARN, ERROR, CAUSE_READING, DONE, False))

    def test_the_reading_beside_its_end_at_a_run_that_passed_is_marked_done(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        self.read(test=(OK, "run 8/1"), docs=OK)
        end, beside = self.rows()[-2:]
        self.assertEqual((end.cause, end.ended),
                         (CAUSE_LINE_DONE_ENDED, ENDED_OCCURRENCE))
        self.assertEqual((beside.old, beside.new, beside.cause, beside.suppressed_by,
                          beside.shown), (ERROR, OK, CAUSE_READING, DONE, False))

    def test_no_line_at_all_is_no_longer_reported(self):
        self.done()
        self.read(lint=WARN, docs=OK)
        (end,) = self.ended()
        self.assertEqual(end.ended, ENDED_GONE)

    def test_a_check_error_leaves_it_suspended(self):
        pin = self.done()
        self.tree.upsert(BUILD, ERROR, ["check error: timed out"])
        self.assertEqual(self.tree.acknowledgment(BUILD, "test"), pin)
        self.assertEqual(self.ended(), [])

    def test_a_hand_ends_it(self):
        pin = self.done()
        write = self.tree.clear_acknowledgment(BUILD, "test",
                                               expected_set_at=pin.token, by="bob")
        self.assertTrue(write.applied)
        (end,) = self.ended()
        self.assertEqual((end.cause, end.ended), (CAUSE_LINE_DONE_ENDED, ENDED_HAND))

    def test_never_the_clock(self):
        pin = self.done()
        tree = StatusTree()
        tree.restore_acknowledgments({}, {(BUILD, "test"): pin},
                                     now=datetime.now(UTC) + timedelta(days=400))
        self.assertEqual(tree.acknowledgments(), ({}, {(BUILD, "test"): pin}))
        self.assertEqual(tuple(tree.recent_events()), ())
        with self.assertRaisesRegex(ValueError, "a done has no end"):
            Pin(DONE, "", datetime.now(UTC), datetime.now(UTC) + timedelta(days=1),
                occurrence="run 7/1", status=ERROR)


class SetTests(_Estate):
    """A done is set on a failing line whose failure is an event, and closes the one
    that was looked at."""

    def test_its_set_is_a_row_of_its_line(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        row = self.rows()[-1]
        self.assertEqual((row.old, row.new, row.cause),
                         (ERROR, OK, CAUSE_LINE_DONE_SET))

    def test_a_line_nothing_tells_apart_takes_none(self):
        self.assertIn("names no event",
                      self.tree.acknowledgeable(BUILD, "lint", kind=DONE))
        write = self.tree.set_acknowledgment(BUILD, "lint", DONE, "", expires_at=None)
        self.assertFalse(write.applied)
        self.assertIn("names no event", write.problem)

    def test_a_node_s_own_failure_takes_none(self):
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.assertEqual(self.tree.acknowledgeable("/site/web/disk", kind=DONE),
                         "/site/web/disk's own failure is a failing stretch, not an "
                         "event: a done closes an event on one of its lines")
        self.assertEqual(self.tree.acknowledgeable("/site/web/disk"), "")

    def test_a_line_that_fails_no_more_takes_none(self):
        self.read(test=(OK, "run 8/1"), lint=WARN)
        self.assertIn("nothing fails there",
                      self.tree.acknowledgeable(BUILD, "test", kind=DONE))

    def test_a_line_in_maintenance_takes_none(self):
        self.tree.set_entry_maintenance(BUILD, "test", "swap",
                                        expires_at=datetime.now(UTC)
                                        + timedelta(hours=1))
        self.assertIn("maintenance",
                      self.tree.acknowledgeable(BUILD, "test", kind=DONE))

    def test_a_form_drawn_on_another_event_closes_nothing(self):
        self.read(test=(ERROR, "run 8/1"), lint=WARN)
        write = self.tree.set_acknowledgment(BUILD, "test", DONE, "it was 7",
                                             expires_at=None, occurrence="run 7/1")
        self.assertFalse(write.applied)
        self.assertEqual(write.problem, "its line test now reads a different event "
                                        "from the one this was opened on")
        self.assertIsNone(self.tree.acknowledgment(BUILD, "test"))
        self.done(occurrence="run 8/1")

    def test_an_edit_keeps_what_it_closed(self):
        pin = self.done()
        write = self.tree.set_acknowledgment(BUILD, "test", DONE, "the runner died",
                                             expires_at=None, set_by="bob",
                                             expected_set_at=pin.token)
        assert write.current is not None
        self.assertEqual((write.current.id, write.current.occurrence,
                          write.current.status, write.current.note),
                         (pin.id, "run 7/1", ERROR, "the runner died"))


class KindTests(_Estate):
    """A done is made another kind, and another kind made done, in one write."""

    def test_a_seen_made_done(self):
        seen = self.tree.set_acknowledgment(BUILD, "test", SEEN, "looking",
                                            expires_at=None).current
        assert seen is not None
        write = self.tree.set_acknowledgment(BUILD, "test", DONE, "over",
                                             expires_at=None,
                                             expected_set_at=seen.token,
                                             occurrence="run 7/1")
        assert write.current is not None
        self.assertEqual(write.current.kind, DONE)
        end, done = self.rows()[-2:]
        self.assertEqual((end.ended, done.cause),
                         (ENDED_MADE[DONE], CAUSE_LINE_DONE_SET))
        self.assertEqual(ENDED_WORDS[ENDED_MADE[DONE]], "made done")

    def test_a_done_made_seen_or_a_silence(self):
        pin = self.done()
        write = self.tree.set_acknowledgment(BUILD, "test", SEEN, "not over",
                                             expires_at=None, expected_set_at=pin.token)
        assert write.current is not None
        self.assertEqual(write.current.kind, SEEN)
        self.assertEqual(self.ended()[-1].ended, ENDED_MADE[SEEN])
        silence = self.tree.set_acknowledgment(
            BUILD, "test", SILENCED, "it flaps",
            expires_at=datetime.now(UTC) + timedelta(days=7), level=OK,
            expected_set_at=write.current.token)
        self.assertTrue(silence.applied, silence.problem)

    def test_a_silence_on_a_line_nothing_tells_apart_is_not_made_done(self):
        silence = self.tree.set_acknowledgment(
            BUILD, "lint", SILENCED, "it flaps",
            expires_at=datetime.now(UTC) + timedelta(days=7), level=OK).current
        assert silence is not None
        write = self.tree.set_acknowledgment(BUILD, "lint", DONE, "",
                                             expires_at=None,
                                             expected_set_at=silence.token)
        self.assertIn("names no event", write.problem)
        self.assertEqual(self.tree.acknowledgment(BUILD, "lint"), silence)


class FoldTests(_Estate):
    """The healthy fold takes a done as what it shows, OK, and nothing else changes."""

    def test_a_done_line_folds_with_the_healthy(self):
        self.done()
        self.assertTrue(line_healthy(self.node(), self.line()))

    def test_its_node_and_those_above_it_fold_where_nothing_else_stands(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        self.assertFalse(pin_beneath(self.node("/site")))
        self.assertTrue(healthy(self.node()))
        self.assertTrue(healthy(self.node("/site/ci")))

    def test_a_seen_beside_it_still_keeps_them_out(self):
        self.read(test=(ERROR, "run 7/1"), lint=WARN, docs=OK)
        self.done()
        self.tree.set_acknowledgment(BUILD, "lint", SEEN, "", expires_at=None)
        self.assertFalse(line_healthy(self.node(), self.line("lint")))
        self.assertFalse(healthy(self.node("/site/ci")))

    def test_a_stale_reading_unfolds_it(self):
        self.tree.upsert(BUILD, ERROR, _lines(test=(ERROR, "run 7/1"), docs=OK),
                         members=True, frequency_seconds=60)
        self.done()
        later = datetime.now(UTC) + timedelta(minutes=10)
        site = self.tree.snapshot("/site", now=later)
        assert site is not None
        self.assertFalse(healthy(site))


class TreatmentTests(_Estate):
    """What a chip, a branch's *why* and the handled count say of a done line."""

    def test_a_chip_counts_it_ok_and_says_it_is_done(self):
        self.read(test=(ERROR, "run 7/1"), docs=OK)
        self.done()
        site = self.node("/site")
        self.assertEqual(handled_beneath(site), {DONE: 1})
        counts = chip_counts(site)
        self.assertEqual((counts.counts["error"], counts.counts["ok"]), (0, 2))
        self.assertIn("1 handled: 1 done", counts.words)

    def test_the_why_card_lists_it_with_the_failure_it_closed(self):
        self.done()
        # a done does the accepted job a seen does, grouped with it
        (rule,) = rules_beneath(self.node("/site"))
        assert rule.entry is not None
        self.assertEqual((rule.path, rule.slug, rule.job, rule.entry.kind, rule.reads),
                         (BUILD, "test", SEEN, DONE, ERROR))


class EnvelopeTests(_Estate):
    """The envelope lists a done with the event and the failure it closed."""

    def test_its_line_lists_it_and_says_by_done(self):
        pin = self.done()
        said = api.snapshot_to_dict(self.node())
        entry = next(item for item in said["entries"]["items"]
                     if item["slug"] == "test")
        self.assertEqual(entry["code"], "ERROR")
        self.assertEqual(entry["contribution"],
                         {"code": "OK", "by": DONE, "rule": pin.id})
        (item,) = entry["handled"]
        self.assertEqual(
            {key: item[key] for key in ("kind", "source", "counts_as", "expires_at",
                                        "status", "occurrence")},
            {"kind": DONE, "source": "person",
             "counts_as": {"WARN": "OK", "ERROR": "OK"}, "expires_at": None,
             "status": "ERROR", "occurrence": "run 7/1"})


class KeptTests(TestCase):
    """The pins file keeps a done, bound to its event, and nothing without one."""

    def test_a_done_round_trips_without_an_end(self):
        pin = Pin(DONE, "over", datetime(2026, 10, 24, 9, tzinfo=UTC), None, "ada",
                  occurrence="run 7/1", status=ERROR)
        said = pin.to_dict()
        self.assertNotIn("expires_at", said)
        self.assertEqual(Pin.from_dict(said), pin)

    def test_a_done_without_its_event_refuses_the_file(self):
        at = "2026-10-24T09:00:00Z"
        done = {"path": BUILD, "slug": "test", "id": "1", "kind": DONE, "note": "",
                "set_at": at, "status": "ERROR"}
        with self.assertRaisesRegex(ValueError, "names no occurrence"):
            PinStore.tables({"pins": [done]})
        held = PinStore.tables({"pins": [{**done, "occurrence": "run 7/1"}]})
        self.assertEqual(list(held.lines_acknowledged), [(BUILD, "test")])

    def test_a_line_holds_one_acknowledgment_whatever_its_kind(self):
        at = "2026-10-24T09:00:00Z"
        done = {"path": BUILD, "slug": "test", "id": "1", "kind": DONE, "note": "",
                "set_at": at, "status": "ERROR", "occurrence": "run 7/1"}
        seen = {**done, "id": "2", "kind": SEEN}
        with self.assertRaisesRegex(ValueError, "two acknowledgments"):
            PinStore.tables({"pins": [done, seen]})

    def test_it_holds_through_a_restart_and_ends_at_the_first_reading_of_another(self):
        pin = Pin(DONE, "over", datetime(2026, 10, 24, 9, tzinfo=UTC), None, "ada",
                  occurrence="run 7/1", status=ERROR)
        tree = StatusTree()
        tree.restore_pins({}, {}, {}, {(BUILD, "test"): pin})
        self.assertEqual(tree.acknowledgment(BUILD, "test"), pin)
        tree.upsert(BUILD, ERROR, _lines(test=(ERROR, "run 9/1")), members=True)
        self.assertIsNone(tree.acknowledgment(BUILD, "test"))
        (end,) = [row for row in tree.recent_events() if row.ended]
        self.assertEqual(end.ended, ENDED_OCCURRENCE)
