"""What a configured rule does to a count (ADR-0137): every part keeps its true color,
and only what it counts as one level up changes — what a node passes to its parent,
how a node's children count in it, or how its lines count in its own status — the
table last at a node's boundary, on what damping publishes, and never beneath what a
stale reading counts. The snapshot, the event log and the bookkeeping read one
derivation, so a branch's period is of what its snapshot says.

What a rule is, and where it acts, is `tests/test_aggregation.py`'s.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

from little_sister import instants
from little_sister.aggregation import ALL, AggregationRule, RuleSet, Table, day_begins
from little_sister.reasons import Entry
from little_sister.status import StatusCode, split_path, worst_of
from little_sister.tree import (
    AGGREGATION_RULE,
    CAUSE_RULE,
    DAMPING_RULE,
    MAINTENANCE_RULE,
    Event,
    StatusSnapshot,
    StatusTree,
    events_from_payload,
    nodes_from_payload,
    own_failure,
)

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED
CAP = {ERROR: WARN}
HEAL = {WARN: OK}
QUIET = {WARN: OK, ERROR: OK}
FLOOR = {WARN: ERROR}


def rule(name: str, under: str, counts_as: dict[StatusCode, StatusCode] | None, *,
         lines: Sequence[str] | None = None, children: Sequence[str] | None = None,
         count: int | None = None) -> AggregationRule:
    """A rule as a start accepts it; ``counts_as`` ``None`` is ``nothing``."""
    table = (Table(left_out=True) if counts_as is None
             else Table(tuple(sorted(counts_as.items(),
                                     key=lambda item: item[0].value))))
    return AggregationRule(
        name=name, under=under, segments=tuple(split_path(under)), table=table,
        note=f"{name}'s note", since=date(2026, 10, 1),
        file=Path("config/aggregation.yaml"), root=Path("config"),
        lines=None if lines is None else tuple(lines),
        children=None if children is None else tuple(children), count=count)


def ruled(*rules: AggregationRule) -> StatusTree:
    tree = StatusTree()
    tree.use_aggregation(RuleSet(rule_ for rule_ in rules))
    return tree


def coded(tree: StatusTree, path: str, **codes: StatusCode) -> None:
    """One run of a check whose lines carry codes, the worst of them its node's —
    what the engine stores for such a node (ADR-0042)."""
    tree.upsert(path, worst_of(codes.values()),
                [Entry(slug, f"{slug} reads {code.name.lower()}", code=code)
                 for slug, code in codes.items()], members=True)


def node(tree: StatusTree, path: str) -> StatusSnapshot:
    found = tree.snapshot(path)
    assert found is not None, path
    return found


def child(parent: StatusSnapshot, name: str) -> StatusSnapshot:
    found = [part for part in parent.children if part.name == name]
    assert len(found) == 1, name
    return found[0]


class NodeRuleTests(TestCase):
    """A rule on a node acts on what the top of its part passes up."""

    def test_the_cap_keeps_the_part_s_color_and_its_parent_sees_amber(self):
        tree = ruled(rule("develop advises", "/aws/develop", CAP))
        tree.upsert("/aws/develop/lambda/fn", ERROR, "timed out")
        tree.upsert("/aws/prod/ec2", OK)
        develop = node(tree, "/aws/develop")
        self.assertIs(develop.code, ERROR)
        self.assertIs(develop.counted, WARN)
        self.assertEqual(develop.contribution.by, AGGREGATION_RULE)
        at = develop.rule
        self.assertEqual((at.reads, at.counts, at.changes), (ERROR, WARN, True))
        # what is beneath the top passes up as it is: the function and lambda red
        self.assertIs(node(tree, "/aws/develop/lambda").counted, ERROR)
        self.assertIsNone(node(tree, "/aws/develop/lambda").rule)
        self.assertIs(node(tree, "/aws").code, WARN)
        self.assertIs(node(tree, "/").code, WARN)

    def test_a_rule_that_changes_nothing_now_says_so(self):
        tree = ruled(rule("develop advises", "/aws/develop", CAP))
        tree.upsert("/aws/develop/lambda/fn", WARN, "slow")
        develop = node(tree, "/aws/develop")
        self.assertIsNone(develop.contribution)
        self.assertFalse(develop.rule.changes)
        self.assertEqual((develop.rule.reads, develop.rule.counts), (WARN, WARN))

    def test_a_star_acts_at_each_part_s_top(self):
        tree = ruled(rule("accounts advise", "/aws/*", CAP))
        tree.upsert("/aws/develop/fn", ERROR, "x")
        tree.upsert("/aws/prod/fn", ERROR, "y")
        for account in ("develop", "prod"):
            self.assertIs(node(tree, f"/aws/{account}").counted, WARN)
        self.assertIs(node(tree, "/aws").code, WARN)

    def test_the_floor_counts_a_warning_as_an_error(self):
        tree = ruled(rule("payments", "/pay", {WARN: ERROR}))
        tree.upsert("/pay/api", WARN, "slow")
        self.assertIs(node(tree, "/pay").counted, ERROR)
        self.assertIs(node(tree, "/").code, ERROR)

    def test_a_failure_a_rule_lowers_spends_no_budget_and_a_floor_s_does(self):
        # the failure budget asks `own_failure` (ADR-0135 decision 9): a leaf a cap
        # lets count as a warning is handled, and the wall need not open its way;
        # a warning a floor makes an error is the failure it is to be taken for
        tree = ruled(rule("nightly advises", "/ci/nightly", CAP),
                     rule("payments", "/pay", {WARN: ERROR}))
        tree.upsert("/ci/nightly", ERROR, "twelve jobs failed")
        tree.upsert("/ci/build", ERROR, "the build failed")
        tree.upsert("/pay", WARN, "slow")
        self.assertIsNone(own_failure(node(tree, "/ci/nightly")))
        self.assertEqual(own_failure(node(tree, "/ci/build")), "error")
        self.assertEqual(own_failure(node(tree, "/pay")), "warn")
        # and a child a count over its parent's children lets count as ok
        quorum = ruled(rule("replicas", "/web", QUIET, children=[ALL], count=2))
        quorum.upsert("/web/a", ERROR, "down")
        quorum.upsert("/web/b", OK)
        self.assertIsNone(own_failure(child(node(quorum, "/web"), "a")))

    def test_a_part_left_out_counts_nothing(self):
        tree = ruled(rule("lab", "/lab", None))
        tree.upsert("/lab/box", ERROR, "fan")
        tree.upsert("/web", OK)
        lab = node(tree, "/lab")
        self.assertIs(lab.code, ERROR)
        self.assertIs(lab.counted, UNDEFINED)
        self.assertEqual((lab.contribution.code, lab.contribution.by),
                         (None, AGGREGATION_RULE))
        self.assertIsNone(lab.rule.counts)
        self.assertIs(node(tree, "/").code, OK)

    def test_a_parent_of_parts_all_left_out_counts_nothing_beneath_it(self):
        tree = ruled(rule("lab", "/lab/*", None))
        tree.upsert("/lab/a", ERROR, "x")
        tree.upsert("/lab/b", OK)
        self.assertIs(node(tree, "/lab").code, UNDEFINED)

    def test_the_first_rule_at_a_place_decides_whole(self):
        # an exception written above the rule it excepts
        tree = ruled(rule("sandbox out", "/aws/sandbox", None),
                     rule("accounts advise", "/aws/*", CAP))
        tree.upsert("/aws/sandbox/fn", ERROR, "x")
        tree.upsert("/aws/prod/fn", ERROR, "y")
        self.assertIs(node(tree, "/aws/sandbox").counted, UNDEFINED)
        self.assertIs(node(tree, "/aws/prod").counted, WARN)
        # and the empty table: every status as itself
        tree = ruled(rule("prod as it is", "/aws/prod", {}),
                     rule("accounts advise", "/aws/*", CAP))
        tree.upsert("/aws/prod/fn", ERROR, "y")
        self.assertIs(node(tree, "/aws/prod").counted, ERROR)
        self.assertEqual(node(tree, "/aws/prod").rule.rule.name, "prod as it is")

    def test_nested_parts_each_act_at_their_own_top(self):
        tree = ruled(rule("aws advises", "/aws", CAP),
                     rule("sandbox out", "/aws/sandbox", None))
        tree.upsert("/aws/sandbox/fn", ERROR, "x")
        tree.upsert("/aws/prod/fn", ERROR, "y")
        self.assertIs(node(tree, "/aws/sandbox").counted, UNDEFINED)
        self.assertIs(node(tree, "/aws").code, ERROR)
        self.assertIs(node(tree, "/aws").counted, WARN)

    def test_a_pin_is_named_first_and_the_table_has_nothing_to_map(self):
        tree = ruled(rule("develop advises", "/aws/develop", CAP))
        tree.upsert("/aws/develop/fn", ERROR, "x")
        tree.set_maintenance("/aws/develop", "rewiring",
                             expires_at=datetime.now(UTC) + timedelta(hours=1),
                             set_by="lex")
        develop = node(tree, "/aws/develop")
        self.assertEqual(develop.contribution.by, MAINTENANCE_RULE)
        self.assertFalse(develop.rule.changes)

    def test_the_instance_s_own_branch_is_out_of_reach(self):
        tree = ruled(rule("everything advises", "/*", CAP))
        tree.upsert("/little-sister", ERROR, "the engine is behind")
        tree.upsert("/aws/fn", ERROR, "x")
        self.assertIsNone(node(tree, "/little-sister").rule)
        self.assertIs(node(tree, "/little-sister").counted, ERROR)
        self.assertIs(node(tree, "/").code, ERROR)


class StaleTests(TestCase):
    """No rule makes a stale part count less than a warning above (ADR-0032 rule
    6): healing or leaving out a part over a dead check still escalates."""

    @staticmethod
    def _stale(tree: StatusTree, path: str) -> None:
        tree.upsert(path, OK, frequency_seconds=60)
        tree._find_node(path).timestamp = datetime.now(UTC) - timedelta(hours=1)

    def test_a_part_left_out_still_counts_a_warning(self):
        tree = ruled(rule("lab", "/lab", None))
        self._stale(tree, "/lab/box")
        lab = node(tree, "/lab")
        self.assertTrue(lab.stale)
        self.assertIs(lab.counted, WARN)

    def test_healing_a_stale_part_still_counts_a_warning(self):
        tree = ruled(rule("lab heals", "/lab", QUIET))
        self._stale(tree, "/lab/box")
        self.assertIs(node(tree, "/lab").counted, WARN)

    def test_a_cap_over_a_stale_error_is_still_the_cap(self):
        tree = ruled(rule("lab advises", "/lab", CAP))
        tree.upsert("/lab/box", ERROR, "x", frequency_seconds=60)
        tree._find_node("/lab/box").timestamp = datetime.now(UTC) - timedelta(hours=1)
        self.assertIs(node(tree, "/lab").counted, WARN)


class DampingTests(TestCase):
    """The table maps what damping publishes, and ``contribution.by`` names the
    first rule whose change still reaches the parent (decision 5)."""

    @staticmethod
    def _held(table: dict[StatusCode, StatusCode]) -> StatusSnapshot:
        tree = ruled(rule("lab", "/lab/box", table))
        tree.upsert("/lab/box", WARN, "slow", escalate_after=3)
        tree.upsert("/lab/box", ERROR, "down", escalate_after=3)
        return node(tree, "/lab/box")

    def test_an_error_held_at_a_warning_heals_by_damping(self):
        box = self._held(HEAL)
        self.assertIsNotNone(box.damping)
        self.assertEqual((box.contribution.code, box.contribution.by),
                         (OK, DAMPING_RULE))

    def test_an_error_held_at_a_warning_under_the_cap_is_the_table_s(self):
        box = self._held(CAP)
        self.assertEqual((box.contribution.code, box.contribution.by),
                         (WARN, AGGREGATION_RULE))


class LinesTests(TestCase):
    """A rule on lines changes what their node shows, as a line's pin does — each
    line keeps its true color under the rule's mark."""

    def test_yellow_lines_heal_and_keep_their_color(self):
        tree = ruled(rule("ec2 heals", "/aws/*/ec2", HEAL, lines=[ALL]))
        coded(tree, "/aws/prod/ec2", **{"i-1": WARN, "i-2": OK})
        ec2 = node(tree, "/aws/prod/ec2")
        self.assertIs(ec2.reported_code, WARN)
        self.assertIs(ec2.own_code, OK)
        self.assertIs(ec2.code, OK)
        warned, fine = ec2.reasons
        self.assertIs(warned.code, WARN)
        self.assertEqual((warned.rule.reads, warned.rule.counts, warned.rule.changes),
                         (WARN, OK, True))
        self.assertFalse(fine.rule.changes)

    def test_a_red_line_still_makes_its_node_red(self):
        tree = ruled(rule("ec2 heals", "/aws/*/ec2", HEAL, lines=[ALL]))
        coded(tree, "/aws/prod/ec2", **{"i-1": WARN, "i-2": ERROR})
        self.assertIs(node(tree, "/aws/prod/ec2").code, ERROR)

    def test_named_lines_alone(self):
        tree = ruled(rule("replica heals", "/db/pool", HEAL, lines=["replica"]))
        coded(tree, "/db/pool", primary=WARN, replica=WARN)
        pool = node(tree, "/db/pool")
        self.assertIs(pool.code, WARN)
        primary, replica = pool.reasons
        self.assertIsNone(primary.rule)
        self.assertTrue(replica.rule.changes)

    def test_a_line_is_decided_by_the_first_rule_that_names_it(self):
        tree = ruled(rule("primary as it is", "/db/pool", {}, lines=["primary"]),
                     rule("pool heals", "/db", HEAL, lines=[ALL]))
        coded(tree, "/db/pool", primary=WARN, replica=WARN)
        primary, replica = node(tree, "/db/pool").reasons
        self.assertEqual(primary.rule.rule.name, "primary as it is")
        self.assertEqual(replica.rule.rule.name, "pool heals")
        self.assertIs(node(tree, "/db/pool").code, WARN)

    def test_a_count_over_lines_holds_while_fewer_than_its_number_fail(self):
        tree = ruled(rule("wiz ten", "/wiz/medium", CAP, lines=[ALL], count=3))
        coded(tree, "/wiz/medium", c1=ERROR, c2=ERROR, c3=OK)
        medium = node(tree, "/wiz/medium")
        self.assertIs(medium.code, WARN)
        self.assertEqual([line.rule.failing for line in medium.reasons], [2, 2, 2])
        coded(tree, "/wiz/medium", c1=ERROR, c2=ERROR, c3=ERROR)
        medium = node(tree, "/wiz/medium")
        self.assertIs(medium.code, ERROR)
        self.assertEqual([(line.rule.failing, line.rule.changes)
                          for line in medium.reasons], [(3, False)] * 3)

    def test_lines_left_out_count_nothing(self):
        tree = ruled(rule("findings out", "/wiz/low", None, lines=[ALL]))
        coded(tree, "/wiz/low", c1=ERROR, c2=WARN)
        low = node(tree, "/wiz/low")
        self.assertIs(low.own_code, UNDEFINED)
        self.assertIsNone(low.reasons[0].rule.counts)

    def test_a_pinned_line_is_the_pin_s(self):
        tree = ruled(rule("pool heals", "/db/pool", HEAL, lines=[ALL]))
        coded(tree, "/db/pool", primary=ERROR, replica=WARN)
        tree.set_entry_maintenance(
            "/db/pool", "primary", "swapping it",
            expires_at=datetime.now(UTC) + timedelta(hours=1), set_by="ada",
            expected_set_at=None)
        primary, replica = node(tree, "/db/pool").reasons
        self.assertIsNone(primary.rule)
        self.assertTrue(primary.quiet)
        self.assertTrue(replica.rule.changes)
        self.assertIs(node(tree, "/db/pool").code, OK)

    def test_a_prose_node_s_lines_are_no_rule_s(self):
        tree = ruled(rule("pool heals", "/db/pool", HEAL, lines=[ALL]))
        tree.upsert("/db/pool", WARN, ["the pool is slow", "and its log says why"])
        pool = node(tree, "/db/pool")
        self.assertIs(pool.code, WARN)
        self.assertTrue(all(line.rule is None for line in pool.reasons))


class ChildrenTests(TestCase):
    """A count over children: the table while fewer than N children report a status
    it names — quorum."""

    def test_one_replica_down_of_three_is_expected(self):
        tree = ruled(rule("replicas", "/web", QUIET, children=[ALL], count=2))
        tree.upsert("/web/a", ERROR, "down")
        tree.upsert("/web/b", OK)
        tree.upsert("/web/c", OK)
        web = node(tree, "/web")
        self.assertIs(web.code, OK)
        self.assertEqual((web.children_rule.failing, web.children_rule.changes),
                         (1, True))
        down = child(web, "a")
        self.assertIs(down.code, ERROR)
        self.assertEqual((down.contribution.code, down.contribution.by),
                         (OK, AGGREGATION_RULE))
        self.assertEqual((down.parent_rule.reads, down.parent_rule.counts),
                         (ERROR, OK))
        # a child the count names and does not change stands under it all the same
        self.assertFalse(child(web, "b").parent_rule.changes)

    def test_two_down_is_an_outage(self):
        tree = ruled(rule("replicas", "/web", QUIET, children=[ALL], count=2))
        tree.upsert("/web/a", ERROR, "down")
        tree.upsert("/web/b", ERROR, "down")
        tree.upsert("/web/c", OK)
        web = node(tree, "/web")
        self.assertIs(web.code, ERROR)
        self.assertEqual((web.children_rule.failing, web.children_rule.changes),
                         (2, False))
        self.assertFalse(child(web, "a").parent_rule.changes)
        self.assertIsNone(child(web, "a").contribution)

    def test_named_children_alone(self):
        tree = ruled(rule("replicas", "/web", CAP, children=["a", "b"], count=2))
        tree.upsert("/web/a", ERROR, "down")
        tree.upsert("/web/db", ERROR, "down")
        web = node(tree, "/web")
        self.assertIs(child(web, "a").counted, WARN)
        self.assertIs(child(web, "db").counted, ERROR)

    def test_the_instance_s_own_branch_is_no_child_a_rule_counts(self):
        tree = ruled(rule("tops quiet", "/", QUIET, children=[ALL], count=5))
        tree.upsert("/little-sister", ERROR, "behind")
        tree.upsert("/aws", ERROR, "x")
        root = node(tree, "/")
        self.assertIs(child(root, "little-sister").counted, ERROR)
        self.assertIs(child(root, "aws").counted, OK)
        self.assertIs(root.code, ERROR)


class EventTests(TestCase):
    """What the log says: a row of what a node showed that a rule kept from its
    parent is marked by it, as damping's are, and a reading a rule on lines kept from
    its node is a row of its own, marked, that its node did not show."""

    def test_a_change_the_cap_holds_back_is_marked(self):
        tree = ruled(rule("develop advises", "/aws/develop/fn", CAP))
        tree.upsert("/aws/develop/fn", OK)
        tree.upsert("/aws/develop/fn", ERROR, "timed out")
        tree.upsert("/aws/develop/fn", WARN, "slow")
        rows = [(event.old, event.new, event.suppressed_by, event.shown)
                for event in tree.recent_events()][1:]
        self.assertEqual(rows, [(OK, ERROR, AGGREGATION_RULE, True),
                                (ERROR, WARN, "", True)])

    def test_a_child_a_count_holds_back_is_marked(self):
        tree = ruled(rule("replicas", "/web", QUIET, children=[ALL], count=2))
        tree.upsert("/web/b", OK)
        tree.upsert("/web/a", OK)
        tree.upsert("/web/a", ERROR, "down")
        self.assertEqual(tree.recent_events()[-1].suppressed_by, AGGREGATION_RULE)

    def test_a_reading_a_lines_rule_keeps_from_its_node_is_a_row_it_did_not_show(self):
        tree = ruled(rule("ec2 heals", "/aws/*/ec2", HEAL, lines=[ALL]))
        coded(tree, "/aws/prod/ec2", **{"i-1": OK})
        coded(tree, "/aws/prod/ec2", **{"i-1": WARN})
        last = tree.recent_events()[-1]
        self.assertEqual((last.old, last.new, last.suppressed_by, last.shown),
                         (OK, WARN, AGGREGATION_RULE, False))
        # History counts only what the node showed
        self.assertEqual([period.code for period in tree.history("/aws/prod/ec2")],
                         [OK])

    def test_the_row_that_ends_a_reading_a_rule_kept_back_is_the_rule_s_too(self):
        # an error a cap on the lines kept at a warning, and then the warning the
        # node showed all along: the reading changed and what the node showed did
        # not, and with no pin on the node that is the rule's to say
        tree = ruled(rule("findings advise", "/wiz/low", CAP, lines=[ALL]))
        coded(tree, "/wiz/low", c1=ERROR)
        coded(tree, "/wiz/low", c1=WARN)
        last = tree.recent_events()[-1]
        self.assertEqual((last.old, last.new, last.suppressed_by, last.shown),
                         (ERROR, WARN, AGGREGATION_RULE, False))

    def test_a_change_a_floor_raises_reaches_its_parent(self):
        # held back is what a rule makes count for less, and a floor makes a warning
        # count for the error it is to be taken for
        tree = ruled(rule("the gateway has no amber", "/services/api", FLOOR))
        tree.upsert("/services/api", OK)
        tree.upsert("/services/api", WARN, "slow")
        last = tree.recent_events()[-1]
        self.assertEqual((last.old, last.new, last.suppressed_by, last.shown),
                         (OK, WARN, "", True))

    def test_a_reading_a_floor_on_lines_raises_is_no_rule_s(self):
        # the node's row reaches, as the error the floor makes of a warning; the
        # check's own reading stays in the log for what it said, a row of no rule's
        # that its node did not show, and so does the one that catches up with it
        tree = ruled(rule("the gateway has no amber", "/gw", FLOOR, lines=[ALL]))
        coded(tree, "/gw", a=OK, b=OK)
        coded(tree, "/gw", a=WARN, b=OK)
        coded(tree, "/gw", a=WARN, b=ERROR)
        rows = [(event.old, event.new, event.suppressed_by, event.shown)
                for event in tree.recent_events()][1:]
        self.assertEqual(rows, [(OK, ERROR, "", True), (OK, WARN, "", False),
                                (WARN, ERROR, "", False)])
        # and it says so in the kept log and back
        back = events_from_payload(json.loads(json.dumps(tree.events_payload())))
        self.assertEqual([(event.suppressed_by, event.shown) for event in back][2:],
                         [("", False), ("", False)])

    def test_a_row_says_it_was_not_shown_in_the_kept_log_and_back(self):
        tree = ruled(rule("ec2 heals", "/aws/*/ec2", HEAL, lines=[ALL]))
        coded(tree, "/aws/prod/ec2", **{"i-1": OK})
        coded(tree, "/aws/prod/ec2", **{"i-1": WARN})
        payload = tree.events_payload()
        raw = payload["events"][-1]
        self.assertIs(raw["shown"], False)
        # a pin's row says nothing new: its mark says it
        back = events_from_payload(payload)
        self.assertFalse(back[-1].shown)
        self.assertFalse(Event.from_dict({**raw, "suppressed_by": "maintenance",
                                          "shown": None}).shown)


class BookkeepingTests(TestCase):
    """The period of what a branch shows is of what its snapshot says (ADR-0132),
    the rules read alike."""

    def test_a_branch_s_period_is_what_the_cap_makes_it(self):
        tree = ruled(rule("develop advises", "/aws/develop", CAP))
        tree.upsert("/aws/develop/fn", ERROR, "timed out")
        tree.upsert("/aws/prod/fn", OK)
        for path in ("/aws", "/aws/develop"):
            snapshot = node(tree, path)
            self.assertIsNotNone(snapshot.period, path)
            self.assertIs(snapshot.period.code, snapshot.code, path)
        self.assertIs(tree.period("/aws").code, WARN)

    def test_the_count_over_children_moves_the_period_where_it_reaches_its_number(self):
        tree = ruled(rule("replicas", "/web", QUIET, children=[ALL], count=2))
        tree.upsert("/web/a", ERROR, "down")
        tree.upsert("/web/b", OK)
        self.assertIs(tree.period("/web").code, OK)
        tree.upsert("/web/b", ERROR, "down")
        self.assertIs(tree.period("/web").code, ERROR)
        self.assertIs(node(tree, "/web").period.code, ERROR)
        ended, current = tree.shown_history("/web")
        self.assertIs(current.code, ERROR)
        self.assertEqual([period.code for period in ended], [OK])


class ReplayTests(TestCase):
    """Where a rule the deployment configures began to count (ADR-0137 decision 11). A
    start that brings a rule begins the period of each branch it moves at that start,
    naming the rule and the node whose count it changed — not at the run that ends the
    kept entries' count, named by whichever unit ran last. A branch's past is read with
    each rule from where it began: the start that brought it while a kept period says
    so, and the start of the day its ``since:`` names after that, a period beginning
    there that names it too. The log holds what the instance showed before the rule."""

    since = date(2026, 10, 22)

    def setUp(self) -> None:
        self.wall = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
        patched = mock.patch.object(instants, "now", lambda: self.wall)
        patched.start()
        self.addCleanup(patched.stop)

    def restarted(self, tree: StatusTree, *rules: AggregationRule) -> StatusTree:
        payload = json.loads(json.dumps(tree.events_payload()))
        new = StatusTree()
        new.use_aggregation(RuleSet(rules))
        new.restore_events(events_from_payload(payload),
                           nodes_from_payload(payload))
        return new

    def advises(self) -> AggregationRule:
        return replace(rule("develop advises", "/aws/develop", CAP), since=self.since)

    def red_develop(self) -> tuple[StatusTree, datetime, datetime]:
        """An instance without the rule that saw develop go red, and the two
        instants: its first reading and the failure."""
        tree = StatusTree()
        first = self.wall
        tree.upsert("/aws/develop", OK)
        tree.upsert("/aws/prod", OK)
        self.wall = broke = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
        tree.upsert("/aws/develop", ERROR, "timed out")
        return tree, first, broke

    def test_a_start_that_brings_a_rule_begins_the_period_it_makes(self):
        tree, first, broke = self.red_develop()
        # the rule is written two days later, and the instance restarted on it
        self.wall = start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        new = self.restarted(tree, self.advises())
        # before any unit has run, and after
        for _ in range(2):
            for branch in ("/aws", "/"):
                period = new.period(branch)
                assert period is not None
                self.assertEqual(
                    (period.code, period.began.at, period.began.was,
                     period.began.cause, period.by, period.rule),
                    (WARN, start, ERROR, CAUSE_RULE, "/aws/develop",
                     "develop advises"), branch)
            new.upsert("/aws/develop", ERROR, "timed out")
            new.upsert("/aws/prod", OK)
        # History says red until the start that brought the rule, as the wall did
        ended, _current = new.shown_history("/aws")
        self.assertEqual([(period.code, period.began.at, period.until)
                          for period in ended],
                         [(ERROR, broke, start), (OK, first, broke)])
        # and the kept file says it, and back
        again = self.restarted(new, self.advises())
        period = again.period("/aws")
        assert period is not None
        self.assertEqual((period.began.cause, period.by, period.rule),
                         (CAUSE_RULE, "/aws/develop", "develop advises"))

    def test_a_rule_begins_in_the_past_at_its_day_where_no_period_keeps_its_start(self):
        tree, first, broke = self.red_develop()
        self.wall = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        new = self.restarted(tree, self.advises())
        new.upsert("/aws/develop", ERROR, "timed out")
        new.upsert("/aws/prod", OK)
        # develop recovers: no period the tree keeps says where the rule began
        self.wall = fixed = datetime(2026, 10, 22, 13, 0, tzinfo=UTC)
        new.upsert("/aws/develop", OK)
        began = day_begins(self.since)
        self.assertLess(broke, began)
        ended, current = new.shown_history("/aws")
        assert current is not None
        self.assertEqual((current.code, current.began.at), (OK, fixed))
        self.assertEqual([(period.code, period.began.at, period.until)
                          for period in ended],
                         [(WARN, began, fixed), (ERROR, broke, began),
                          (OK, first, broke)])
        self.assertEqual((ended[0].began.was, ended[0].began.cause, ended[0].by,
                          ended[0].rule),
                         (ERROR, CAUSE_RULE, "/aws/develop", "develop advises"))

    def test_a_floor_a_start_brings_names_the_node_it_raised(self):
        tree = StatusTree()
        tree.upsert("/svc/api", WARN, "slow")
        tree.upsert("/svc/db", OK)
        self.wall = start = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        new = self.restarted(tree, replace(
            rule("the gateway has no amber", "/svc/api", FLOOR), since=self.since))
        period = new.period("/svc")
        assert period is not None
        self.assertEqual((period.code, period.began.at, period.began.was,
                          period.by, period.rule),
                         (ERROR, start, WARN, "/svc/api", "the gateway has no amber"))

    def test_a_start_names_the_node_whose_count_moved_the_branch(self):
        # two rules beneath one branch: the cap that lowered its red, not the healing
        # of an amber drawn before it, which moved nothing the branch shows
        tree = StatusTree()
        tree.upsert("/aws/beta", WARN, "slow")
        tree.upsert("/aws/develop", ERROR, "down")
        self.wall = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        new = self.restarted(
            tree, replace(rule("beta heals", "/aws/beta", HEAL), since=self.since),
            self.advises())
        period = new.period("/aws")
        assert period is not None
        self.assertEqual((period.code, period.by, period.rule),
                         (WARN, "/aws/develop", "develop advises"))

    def test_a_count_a_start_brings_names_the_child_it_counts(self):
        tree = StatusTree()
        tree.upsert("/web/a", ERROR, "down")
        tree.upsert("/web/b", OK)
        tree.upsert("/web/c", OK)
        self.wall = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        new = self.restarted(tree, replace(
            rule("replicas", "/web", QUIET, children=[ALL], count=2),
            since=self.since))
        period = new.period("/web")
        assert period is not None
        self.assertEqual((period.code, period.by, period.rule),
                         (OK, "/web/a", "replicas"))

    def test_a_start_whose_rules_change_nothing_keeps_the_periods(self):
        tree, _first, broke = self.red_develop()
        self.wall = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        new = self.restarted(tree, replace(
            rule("lab is out", "/lab", None), since=self.since))
        period = new.period("/aws")
        assert period is not None
        self.assertEqual((period.code, period.began.at, period.began.cause,
                          period.rule), (ERROR, broke, "reading", ""))

    def test_a_rule_that_stood_before_the_log_reads_throughout(self):
        tree = ruled(rule("develop advises", "/aws/develop", CAP))
        tree.upsert("/aws/develop", OK)
        tree.upsert("/aws/prod", OK)
        self.wall = broke = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
        tree.upsert("/aws/develop", ERROR, "timed out")
        self.wall = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        tree.upsert("/aws/develop", OK)
        ended, _current = tree.shown_history("/aws")
        self.assertEqual([(period.code, period.began.at) for period in ended][:1],
                         [(WARN, broke)])

    def test_a_kept_period_names_a_rule_only_where_one_began_it(self):
        raw = {"code": "WARN", "since": "2026-10-22T12:00:00Z", "was": "ERROR",
               "cause": "reading", "by": "/aws/develop", "rule": "develop advises"}
        payload = {"events": [], "nodes": {"/aws": {
            "shows": "WARN", "reported": "UNDEFINED", "period": raw}}}
        with self.assertRaisesRegex(ValueError, "names a rule, and no rule began it"):
            nodes_from_payload(payload)
        # the same with a rule's cause is what a start keeps
        raw["cause"] = CAUSE_RULE
        kept = nodes_from_payload(payload)
        assert kept is not None and kept["/aws"].period is not None
        self.assertEqual(kept["/aws"].period.rule, "develop advises")
