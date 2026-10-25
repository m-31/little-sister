import threading
import unittest
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from unittest import TestCase

from little_sister.pins import MAINTENANCE, Pin
from little_sister.reasons import Entry
from little_sister.status import HEARTBEAT_PATH, StatusCode, effective_code
from little_sister.tree import (
    CHANGE_WINDOW_SECONDS,
    COUNTED_STATES,
    ChipCounts,
    Event,
    StatusTree,
    chip_counts,
    counts_as,
    failing,
    failing_first,
    healthy,
    line_counts_as,
    line_healthy,
    own_failure,
    pin_beneath,
)


class _RecordingStore:
    """A maintenance store that just remembers the last table saved, and how often
    one was (no file)."""

    def __init__(self) -> None:
        self.saved: dict[str, Pin] = {}
        self.saved_entries: dict[tuple[str, str], Pin] = {}
        self.saves = 0

    def load(self) -> dict[str, Pin]:
        return {}

    def load_entries(self) -> dict[tuple[str, str], Pin]:
        return {}

    def save(self, entries, entry_pins=None, acknowledged=None,
             lines_acknowledged=None):
        self.saved = dict(entries)
        self.saved_entries = dict(entry_pins or {})
        self.saves += 1


class DampingTests(TestCase):
    """The confidence counter at the node boundary (backlog #38 B).

    The claim under test throughout: **the leaf is honest immediately and only the
    escalation waits.** A test that checked the node's own code went quiet would be
    testing the mechanism 1.5 rejected, not this one.
    """

    def _tree(self, needed: int = 3) -> StatusTree:
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK, escalate_after=needed)
        return tree

    def _snap(self, tree: StatusTree, path: str = "/svc/api"):
        snap = tree.snapshot(path)
        assert snap is not None
        return snap

    def test_the_node_is_red_at_once_and_the_parent_is_not(self):
        tree = self._tree()
        tree.upsert("/svc/api", StatusCode.ERROR)
        leaf = self._snap(tree)
        self.assertIs(leaf.code, StatusCode.ERROR, "the leaf never lies")
        self.assertIs(leaf.contribution.code, StatusCode.OK)
        self.assertEqual(leaf.contribution.by, "damping")
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.OK)

    def test_it_escalates_on_the_reading_the_deployment_asked_for(self):
        tree = self._tree(3)
        for expected in (StatusCode.OK, StatusCode.OK):
            tree.upsert("/svc/api", StatusCode.ERROR)
            self.assertIs(self._snap(tree, "/svc").code, expected)
        tree.upsert("/svc/api", StatusCode.ERROR)      # the third reading
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)
        self.assertIsNone(self._snap(tree).contribution)
        self.assertIsNone(self._snap(tree).damping)

    def test_a_reading_that_changed_nothing_still_counts(self):
        # three consecutive readings of ERROR is three readings, and only the first
        # of them is a transition — a counter that advanced on transitions alone
        # would never reach two
        tree = self._tree(2)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertEqual(self._snap(tree).damping.seen, 1)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_recovery_is_immediate_and_clears_the_count(self):
        tree = self._tree(3)
        tree.upsert("/svc/api", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.OK)
        self.assertIsNone(self._snap(tree).damping)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.OK)

    def test_a_different_worse_code_restarts_the_count(self):
        # two readings that disagree are not two votes for either
        tree = self._tree(3)
        tree.upsert("/svc/api", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.WARN)
        marker = self._snap(tree).damping
        self.assertIs(marker.pending, StatusCode.WARN)
        self.assertEqual(marker.seen, 1)

    def test_the_held_value_is_the_last_published_and_not_ok(self):
        # a node that was already WARN publishes WARN while it holds back ERROR —
        # publishing OK would invent a reading nobody made
        tree = self._tree(2)
        tree.upsert("/svc/api", StatusCode.WARN)   # published at once: 1st reading
        tree.upsert("/svc/api", StatusCode.WARN)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertIs(self._snap(tree).contribution.code, StatusCode.WARN)

    def test_the_first_reading_of_a_node_is_never_delayed(self):
        tree = StatusTree()
        tree.upsert("/svc/new", StatusCode.ERROR, escalate_after=5)
        self.assertIsNone(self._snap(tree, "/svc/new").damping)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_a_move_through_undefined_is_not_an_escalation(self):
        # a parent counts no `UNDEFINED` at all, so the first countable reading
        # after one is the same case as a node's very first: there is nothing to
        # escalate *from*, and holding it back would delay the only claim anybody
        # has made. The state-is-new branch does not cover this — the node has
        # damping state by now — so the ranking rule has to.
        tree = self._tree(3)
        tree.upsert("/svc/api", StatusCode.UNDEFINED)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertIsNone(self._snap(tree).damping)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_staleness_escalates_past_the_counter(self):
        # a check that stopped running produces no new readings, so the count would
        # never advance and the hold would never end (ADR-0032 rule 6)
        tree = self._tree(3)
        tree.upsert("/svc/api", StatusCode.ERROR, frequency_seconds=60)
        stale = datetime.now(UTC) - timedelta(seconds=3600)
        tree.snapshot("/svc/api")
        node = tree._ensure_node("/svc/api")           # age it by hand
        node.timestamp = stale
        leaf = self._snap(tree)
        self.assertTrue(leaf.stale)
        self.assertIsNone(leaf.damping, "the hold is not in force on a stale node")
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_the_default_publishes_at_once(self):
        # `escalate_after` 1 is exactly the behavior every deployment had before
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertIsNone(self._snap(tree).damping)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_a_damped_transition_is_a_period_of_the_nodes_own_history(self):
        """The one claim damping makes is that the leaf is honest, and its history is
        a surface like any other. A pinned node's hidden transition is a different
        case — it really did not change what anybody saw — and the two must not be
        filtered by one test of *was this suppressed*."""
        tree = self._tree(3)
        tree.upsert("/svc/api", StatusCode.ERROR)
        periods = tree.history("/svc/api")
        self.assertEqual([period.code for period in periods],
                         [StatusCode.OK, StatusCode.ERROR])

    def test_a_pinned_nodes_hidden_transition_is_still_not_a_period(self):
        # the case the filter exists for, kept working
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK)
        tree.set_maintenance("/svc/api", "window",
                             expires_at=datetime(2999, 1, 1, tzinfo=UTC), set_by="ada")
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertNotIn(StatusCode.ERROR,
                         [period.code for period in tree.history("/svc/api")])

    def test_the_changes_count_is_what_says_a_subject_is_flapping(self):
        """The counter deliberately does not catch flap — every recovery clears it —
        so without this number nothing anywhere says so."""
        tree = self._tree(3)
        for code in (StatusCode.ERROR, StatusCode.OK,
                     StatusCode.ERROR, StatusCode.OK):
            tree.upsert("/svc/api", code)
        self.assertEqual(self._snap(tree).changes, 4)
        self.assertIsNone(self._snap(tree).damping, "a flapper never holds")

    def test_the_first_reading_is_not_a_change_of_mind(self):
        # every node does `UNDEFINED` to something once at startup; counting it
        # would put a 1 beside every node on the dashboard for an hour
        tree = StatusTree()
        tree.upsert("/svc/new", StatusCode.OK)
        self.assertEqual(self._snap(tree, "/svc/new").changes, 0)

    def test_a_transition_that_alarmed_nobody_still_counts(self):
        # the difference from the history: this is the subject's behavior, so a
        # check flapping underneath a pin is exactly what is worth seeing
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK)
        tree.set_maintenance("/svc/api", "window",
                             expires_at=datetime(2999, 1, 1, tzinfo=UTC), set_by="ada")
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertEqual(self._snap(tree).changes, 1)
        self.assertEqual(tree.history("/svc/api")[-1].code, StatusCode.MAINTENANCE,
                         "the history says what the node showed, which was the pin")

    def test_a_change_older_than_the_window_drops_out(self):
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK)
        tree.upsert("/svc/api", StatusCode.ERROR)
        later = datetime.now(UTC) + timedelta(seconds=CHANGE_WINDOW_SECONDS + 60)
        snap = tree.snapshot("/svc/api", now=later)
        assert snap is not None
        self.assertEqual(snap.changes, 0)

    def test_the_held_transition_is_marked_in_the_event_log(self):
        tree = self._tree(3)
        tree.upsert("/svc/api", StatusCode.ERROR)
        event = tree.recent_events()[-1]
        self.assertIs(event.new, StatusCode.ERROR, "the log is honest")
        self.assertEqual(event.suppressed_by, "damping")


class ShieldingTests(TestCase):
    """Dependency shielding (backlog #38 A).

    The claim under test throughout: **the node that could not be reached keeps its
    own reading and stops reaching its parent, and the dependency raises the one
    alarm.** A test that checked the dependent went green would be testing a
    mechanism this rejected — nobody is claiming the unit is well.
    """

    def _tree(self) -> StatusTree:
        """A gateway and a unit behind it, mounted apart on purpose: a dependency
        may sit anywhere in the tree, and a test that put both under one parent
        would pass even if the shield were resolved inside the recursion."""
        tree = StatusTree()
        tree.upsert("/net/vpn", StatusCode.OK)
        tree.upsert("/svc/api", StatusCode.OK)
        tree.set_dependency("/svc/api", "/net/vpn")
        return tree

    def _snap(self, tree: StatusTree, path: str = "/svc/api"):
        snap = tree.snapshot(path)
        assert snap is not None
        return snap

    def _age(self, tree: StatusTree, path: str, seconds: float = 3600.0) -> None:
        node = tree._ensure_node(path)
        node.frequency_seconds = 60
        node.timestamp = datetime.now(UTC) - timedelta(seconds=seconds)

    def test_the_unit_keeps_its_reading_and_stops_reaching_its_parent(self):
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        leaf = self._snap(tree)
        self.assertIs(leaf.code, StatusCode.ERROR, "the leaf never lies")
        self.assertEqual(leaf.shielded_by, "/net/vpn")
        self.assertEqual(leaf.contribution.by, "dependency")
        self.assertIsNone(leaf.contribution.code, "nothing was counted")
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.UNDEFINED)

    def test_a_shielded_node_does_not_drag_a_healthy_sibling_down(self):
        # the payoff the whole rule exists for: one alarm at the gateway, and the
        # rest of the container still says what it knows
        tree = self._tree()
        tree.upsert("/svc/db", StatusCode.OK)
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.OK)

    def test_the_dependency_itself_still_escalates(self):
        # shielding silences the consequence, never the cause — a rule that quieted
        # both would turn a failed gateway into an all-green dashboard
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertIs(self._snap(tree, "/net").code, StatusCode.ERROR)
        self.assertIsNone(self._snap(tree, "/net/vpn").shielded_by)

    def test_a_dependency_that_is_merely_amber_does_not_shield(self):
        # `WARN` has not stopped anybody reaching anything, and shielding on it
        # would silence a subtree because something was amber
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.WARN)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertIsNone(self._snap(tree).shielded_by)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_a_dependency_that_has_never_reported_does_not_shield(self):
        # silence is the state a naive implementation would read as permission
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.ERROR)
        tree.set_dependency("/svc/api", "/net/vpn")
        self.assertIsNone(self._snap(tree).shielded_by)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_a_stale_dependency_does_not_shield(self):
        # a gateway whose check stopped running is not evidence about anything;
        # its own `ERROR` may be an hour old
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self._age(tree, "/net/vpn")
        self.assertIsNone(self._snap(tree).shielded_by)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_a_stale_dependent_is_not_shielded(self):
        # ADR-0032 rule 6: a check that stopped running escalates whatever else is
        # true of it, or a permanent shield becomes a permanent blindfold
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self._age(tree, "/svc/api")
        leaf = self._snap(tree)
        self.assertTrue(leaf.stale)
        self.assertIsNone(leaf.shielded_by)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_a_dependency_that_is_itself_shielded_does_not_shield_on(self):
        # two hops would let one red root quiet half a tree with nothing saying
        # why: the middle node is already withholding, so it is not evidence
        tree = self._tree()
        tree.upsert("/net/wan", StatusCode.ERROR)
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        tree.set_dependency("/net/vpn", "/net/wan")
        self.assertEqual(self._snap(tree, "/net/vpn").shielded_by, "/net/wan")
        self.assertIsNone(self._snap(tree).shielded_by,
                          "the unit is two hops from the only thing that failed")
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_a_pin_outranks_the_shield_in_naming_the_node(self):
        # one rule names each node, and an admin's pin is the most specific thing
        # anybody said about this one
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        tree.set_maintenance("/svc/api", "window",
                             expires_at=datetime(2999, 1, 1, tzinfo=UTC), set_by="ada")
        leaf = self._snap(tree)
        self.assertEqual(leaf.contribution.by, "maintenance")
        self.assertEqual(leaf.shielded_by, "/net/vpn",
                         "the shield is still a fact about the node")

    def test_the_mark_sits_at_the_mount_and_not_on_every_child(self):
        # a check emitting a subtree declares one dependency, and the marker belongs
        # where the declaration was made; the children are withheld because their
        # mount is, which is the roll-up doing its ordinary job
        tree = self._tree()
        tree.upsert("/svc/api/pool", StatusCode.ERROR)
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertEqual(self._snap(tree).shielded_by, "/net/vpn")
        self.assertIsNone(self._snap(tree, "/svc/api/pool").shielded_by)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.UNDEFINED)

    def test_the_shield_lifts_the_moment_the_dependency_recovers(self):
        # derived per snapshot, never stored: nothing has to remember to unshield
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertEqual(self._snap(tree).shielded_by, "/net/vpn")
        tree.upsert("/net/vpn", StatusCode.OK)
        self.assertIsNone(self._snap(tree).shielded_by)
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.ERROR)

    def test_an_ok_reading_behind_a_failed_dependency_is_withheld_too(self):
        """The shield is a statement about **evidence**, not a filter on bad news.

        Letting an `OK` through because it alarms nobody would be the exact failure
        a monitor exists to prevent: green on the dashboard for a unit we could not
        reach, on the strength of a reading taken through a broken path. `UNDEFINED`
        — *nothing here is reporting* — is the true sentence, and the gateway's own
        `ERROR` is what the operator is meant to be looking at.
        """
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        self.assertIs(self._snap(tree).code, StatusCode.OK, "the leaf never lies")
        self.assertEqual(self._snap(tree).shielded_by, "/net/vpn")
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.UNDEFINED)

    def test_the_held_transition_is_marked_in_the_event_log(self):
        # the log is honest and says which rule kept the reading from reaching
        # anybody — the same treatment a pin and the counter already get
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        event = tree.recent_events()[-1]
        self.assertIs(event.new, StatusCode.ERROR)
        self.assertEqual(event.suppressed_by, "dependency")

    def test_a_shielded_transition_is_still_a_period_of_the_nodes_history(self):
        """The history filters out transitions that were *hidden* — a check going red
        underneath a pin did not change what the node showed. A shielded node did: it
        is red on its own page from the first reading, and only its parent's count is
        withheld. So the filter turns on which rules hide the reading, and this is not
        one of them."""
        tree = self._tree()
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        self.assertEqual([period.code for period in tree.history("/svc/api")],
                         [StatusCode.OK, StatusCode.ERROR])

    def test_the_shield_outranks_the_counter(self):
        """Both rules are about a reading, and the order between them is not
        cosmetic: the counter would put a *code* on the contribution and the parent
        would accumulate it, so a shielded node evaluated counter-first would reach
        its parent after all — with the value it published before the outage."""
        tree = StatusTree()
        tree.upsert("/net/vpn", StatusCode.OK)
        tree.upsert("/svc/api", StatusCode.OK, escalate_after=3)
        tree.set_dependency("/svc/api", "/net/vpn")
        tree.upsert("/net/vpn", StatusCode.ERROR)
        tree.upsert("/svc/api", StatusCode.ERROR)
        leaf = self._snap(tree)
        self.assertEqual(leaf.contribution.by, "dependency")
        self.assertIsNone(leaf.contribution.code)
        self.assertIsNone(leaf.damping, "the counter is not what is speaking")
        self.assertIs(self._snap(tree, "/svc").code, StatusCode.UNDEFINED)

    def test_the_graph_is_visible_from_both_ends(self):
        # one dependency shields dozens of dependents — that is its risk, so the
        # node's page has to be able to say how many
        tree = self._tree()
        tree.upsert("/svc/web", StatusCode.OK)
        tree.set_dependency("/svc/web", "/net/vpn")
        self.assertEqual(tree.dependents("/net/vpn"), ("/svc/api", "/svc/web"))
        self.assertEqual(tree.dependents("/svc/api"), (),
                         "a dependent is not itself depended on")


class MeasurementTests(TestCase):
    """The run's own measurement on the node (ADR-0085).

    The claim under test: **what a check measured reaches the node it measured**,
    and it is the object's identity that travels, not the path the deployment chose.
    """

    def test_the_node_holds_what_its_check_measured(self):
        tree = StatusTree()
        tree.upsert("/hosts/web01", StatusCode.OK, subject="web01.example",
                    record={"cpu_pct": 7, "mem_pct": 63})
        snap = tree.snapshot("/hosts/web01")
        assert snap is not None
        self.assertEqual(snap.subject, "web01.example")
        self.assertEqual(snap.record["cpu_pct"], 7)

    def test_the_object_is_not_the_path(self):
        # `/hosts/web01` measures `web01.example`, `/hosts/nas/system` measures `nas01`:
        # the path is the deployment's label and may be moved or renamed, and an
        # identity not written down at the reading cannot be added afterwards
        tree = StatusTree()
        tree.upsert("/hosts/web01", StatusCode.OK, subject="web01.example")
        snap = tree.snapshot("/hosts/web01")
        assert snap is not None
        self.assertNotEqual(snap.subject, snap.path)

    def test_a_later_reading_replaces_the_one_before_it(self):
        # written through like the report: a measurement that outlives its run is
        # yesterday's numbers mistaken for today's
        tree = StatusTree()
        tree.upsert("/hosts/web01", StatusCode.OK, subject="web01.example",
                    record={"cpu_pct": 7})
        tree.upsert("/hosts/web01", StatusCode.OK, subject="web01.example",
                    record={"cpu_pct": 91})
        snap = tree.snapshot("/hosts/web01")
        assert snap is not None
        self.assertEqual(snap.record["cpu_pct"], 91)

    def test_a_run_that_read_nothing_clears_the_last_reading(self):
        tree = StatusTree()
        tree.upsert("/hosts/web01", StatusCode.OK, subject="web01.example",
                    record={"cpu_pct": 7})
        tree.upsert("/hosts/web01", StatusCode.ERROR, "ssh: connection refused",
                    subject="web01.example")
        snap = tree.snapshot("/hosts/web01")
        assert snap is not None
        self.assertEqual(snap.subject, "web01.example",
                         "we know what we could not read")
        self.assertIsNone(snap.record)

    def test_a_node_nobody_measures_carries_neither(self):
        tree = StatusTree()
        tree.upsert("/hosts/web01/website", StatusCode.OK, subject="http://web01.example",
                    record={"status": 200})
        parent = tree.snapshot("/hosts/web01")
        assert parent is not None
        self.assertEqual(parent.subject, "")
        self.assertIsNone(parent.record)

    def test_a_mount_two_checks_share_withholds_the_measurement(self):
        """`/hosts/nas/system` carries `host-metrics` and `macos-memory` by design
        (ADR-0015), and the container belongs to neither — so the last writer must
        not be believed there, exactly as it is not for the text and the run facts."""
        tree = StatusTree()
        tree.set_check_mount("/hosts/nas/system")
        tree.set_check_mount("/hosts/nas/system")
        tree.upsert("/hosts/nas/system", StatusCode.OK, subject="nas01",
                    record={"cpu_pct": 7})
        snap = tree.snapshot("/hosts/nas/system")
        assert snap is not None
        self.assertEqual(snap.subject, "")
        self.assertIsNone(snap.record)


class StatusTreeTests(TestCase):
    def test_upsert_creates_nodes_and_snapshot_reads_them(self):
        tree = StatusTree()
        tree.upsert("/payments/gateway", StatusCode.OK)
        snap = tree.snapshot("/payments/gateway")
        assert snap is not None
        self.assertEqual(snap.name, "gateway")
        self.assertEqual(snap.own_code, StatusCode.OK)
        # the intermediate container node was created too
        self.assertIsNotNone(tree.snapshot("/payments"))

    def test_snapshot_and_effective_of_missing_path_is_none(self):
        tree = StatusTree()
        self.assertIsNone(tree.snapshot("/nope"))
        self.assertIsNone(tree.effective("/nope"))

    def test_upsert_returns_true_only_on_change(self):
        tree = StatusTree()
        self.assertTrue(tree.upsert("/db", StatusCode.OK))     # UNDEFINED -> OK
        self.assertFalse(tree.upsert("/db", StatusCode.OK))    # no change
        self.assertTrue(tree.upsert("/db", StatusCode.ERROR))  # OK -> ERROR

    def test_config_is_metadata_not_a_transition(self):
        tree = StatusTree()
        self.assertTrue(tree.upsert("/svc", StatusCode.OK,
                                    config="- **url:** http://x"))
        snap = tree.snapshot("/svc")
        assert snap is not None
        self.assertEqual(snap.config, "- **url:** http://x")
        events = len(tree.recent_events())
        # same code, changed config: stored, but never a transition (ADR-0013)
        self.assertFalse(tree.upsert("/svc", StatusCode.OK,
                                     config="- **url:** http://y"))
        self.assertEqual(len(tree.recent_events()), events)
        snap = tree.snapshot("/svc")
        assert snap is not None
        self.assertEqual(snap.config, "- **url:** http://y")

    def test_set_about_seeds_metadata_without_status(self):
        tree = StatusTree()
        tree.set_about("/system/alpha", "A NUC in the cupboard.")
        snap = tree.snapshot("/system/alpha")
        assert snap is not None
        self.assertEqual(snap.about, "A NUC in the cupboard.")
        # about is subject metadata, not status: node stays UNDEFINED, no event
        self.assertEqual(snap.own_code, StatusCode.UNDEFINED)
        self.assertEqual(tree.recent_events(), ())

    def test_set_title_seeds_metadata_without_status(self):
        tree = StatusTree()
        tree.set_title("/nexus", "Nexus NAS")
        snap = tree.snapshot("/nexus")
        assert snap is not None
        self.assertEqual(snap.title, "Nexus NAS")
        self.assertEqual(snap.own_code, StatusCode.UNDEFINED)   # not status, no event
        self.assertEqual(tree.recent_events(), ())

    def test_upsert_fills_empty_about_and_title(self):
        # A check-provided label (ADR-0025) seeds a node whose field is empty; it
        # is metadata, not status, so it never emits an event.
        tree = StatusTree()
        self.assertTrue(tree.upsert("/host/disk", StatusCode.OK,
                                    about="Free space on the data volume.",
                                    title="Disk"))            # the OK is the event
        snap = tree.snapshot("/host/disk")
        assert snap is not None
        self.assertEqual(snap.about, "Free space on the data volume.")
        self.assertEqual(snap.title, "Disk")
        self.assertEqual(len(tree.recent_events()), 1)        # only the status one

    def test_upsert_about_and_title_fill_empty_per_field(self):
        # nodes.yaml is seeded first (set_about/set_title); a check-provided value
        # must not overwrite one already set, and each field resolves on its own —
        # here yaml gave `about` but left `title`, so the check fills only `title`.
        tree = StatusTree()
        tree.set_about("/host/disk", "Declared in nodes.yaml.")
        tree.upsert("/host/disk", StatusCode.OK,
                    about="From the check.", title="From the check")
        snap = tree.snapshot("/host/disk")
        assert snap is not None
        self.assertEqual(snap.about, "Declared in nodes.yaml.")   # seeded value wins
        self.assertEqual(snap.title, "From the check")            # empty field filled

    def test_upsert_about_and_title_freeze_at_first_fill(self):
        # Once a check fills a label it is frozen — a later tick never rewrites it,
        # even as the status itself transitions (stable identity, not live status).
        tree = StatusTree()
        tree.upsert("/host/disk", StatusCode.OK, about="First.", title="Disk")
        tree.upsert("/host/disk", StatusCode.WARN, ["85% used"],
                    about="Second.", title="Volume")
        snap = tree.snapshot("/host/disk")
        assert snap is not None
        self.assertEqual((snap.about, snap.title), ("First.", "Disk"))
        self.assertEqual(snap.own_code, StatusCode.WARN)          # status still moved

    def test_a_handbook_is_a_label_a_snapshot_only_says_is_there(self):
        # ADR-0133 decision 3: seeded from the configuration and filled once by a
        # run, as the labels are, so its tab never comes and goes with a reading;
        # its text stays on the node, for its tab, and a snapshot says only that
        # there is one
        tree = StatusTree()
        tree.set_handbook("/host", "## Sign in\n\nThrough the bastion.")
        tree.upsert("/host", StatusCode.OK, handbook="From a run.")
        tree.upsert("/host/disk", StatusCode.OK, handbook="Replace the drive.")
        tree.upsert("/host/disk", StatusCode.WARN, ["85% used"],
                    handbook="Something else.")
        tree.upsert("/host/memory", StatusCode.OK)
        self.assertEqual(tree.handbook("/host"),
                         "## Sign in\n\nThrough the bastion.")
        self.assertEqual(tree.handbook("/host/disk"), "Replace the drive.")
        self.assertEqual((tree.handbook("/host/memory"), tree.handbook("/none")),
                         ("", ""))
        host = tree.snapshot("/host")
        assert host is not None
        self.assertTrue(host.has_handbook)
        self.assertEqual({child.name: child.has_handbook for child in host.children},
                         {"disk": True, "memory": False})
        self.assertFalse(hasattr(host, "handbook"))
        # metadata, not status: the seed is no event
        self.assertEqual([event.path for event in tree.recent_events()],
                         ["/host", "/host/disk", "/host/disk", "/host/memory"])

    def test_events_recorded_on_change_only(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        tree.upsert("/db", StatusCode.OK)                      # no event
        tree.upsert("/db", StatusCode.ERROR, "down")
        events = tree.recent_events()
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], Event)
        self.assertEqual((events[0].old, events[0].new),
                         (StatusCode.UNDEFINED, StatusCode.OK))
        self.assertEqual((events[1].old, events[1].new),
                         (StatusCode.OK, StatusCode.ERROR))
        self.assertEqual(events[1].reason, ("down",))
        self.assertEqual(events[1].path, "/db")

    def test_effective_rolls_up_per_adr_0004(self):
        tree = StatusTree()
        tree.upsert("/svc/a", StatusCode.OK)
        tree.upsert("/svc/b", StatusCode.ERROR)
        self.assertEqual(tree.effective("/svc"), StatusCode.ERROR)
        svc = tree.snapshot("/svc")
        assert svc is not None
        self.assertEqual(svc.code, StatusCode.ERROR)            # effective
        self.assertEqual(svc.own_code, StatusCode.UNDEFINED)    # container

    def test_maintenance_branch_hidden_from_effective(self):
        tree = StatusTree()
        tree.upsert("/svc/a", StatusCode.OK)
        tree.upsert("/svc/b", StatusCode.MAINTENANCE)
        tree.upsert("/svc/b/x", StatusCode.ERROR)               # hidden by maint.
        self.assertEqual(tree.effective("/svc"), StatusCode.OK)

    def test_snapshot_is_independent_of_later_mutation(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        snap = tree.snapshot("/db")
        assert snap is not None
        tree.upsert("/db", StatusCode.ERROR)
        self.assertEqual(snap.own_code, StatusCode.OK)         # snapshot frozen

    def test_entry_count_follows_what_the_nodes_hold(self):
        # The count the engine measures against its entry limit (ADR-0072):
        # kept on the write path, so it moves with every upsert and never walks.
        tree = StatusTree()
        self.assertEqual(tree.entry_count, 0)
        tree.upsert("/a", StatusCode.WARN, {"x": "one", "y": "two"})
        tree.upsert("/b", StatusCode.OK, ["prose line"])
        self.assertEqual(tree.entry_count, 3)
        tree.upsert("/a", StatusCode.OK, {"x": "one"})       # one entry gone
        self.assertEqual(tree.entry_count, 2)
        tree.upsert("/b", StatusCode.OK)                       # none left
        self.assertEqual(tree.entry_count, 1)
        tree.set_about("/c", "a container")                    # metadata: no entry
        tree.upsert("/a", StatusCode.OK, {"x": "one"}, config="- k: v")
        self.assertEqual(tree.entry_count, 1)

    def test_event_log_is_bounded(self):
        tree = StatusTree(event_log_size=3)
        for code in (StatusCode.OK, StatusCode.WARN, StatusCode.ERROR,
                     StatusCode.OK, StatusCode.WARN):
            tree.upsert("/db", code)
        events = tree.recent_events()
        self.assertEqual(len(events), 3)
        self.assertEqual(events[-1].new, StatusCode.WARN)

    def test_concurrent_upserts_are_consistent(self):
        tree = StatusTree()
        n_threads, per_thread = 8, 50

        def worker(tid: int) -> None:
            for i in range(per_thread):
                tree.upsert(f"/svc/node{tid}_{i}", StatusCode.OK)

        threads = [threading.Thread(target=worker, args=(t,))
                   for t in range(n_threads)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        svc = tree.snapshot("/svc")
        assert svc is not None
        self.assertEqual(len(svc.children), n_threads * per_thread)
        self.assertEqual(tree.effective("/svc"), StatusCode.OK)

    def test_upsert_stores_description_and_frequency(self):
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK, description="the API",
                    frequency_seconds=300)
        snap = tree.snapshot("/svc/api")
        assert snap is not None
        self.assertEqual(snap.description, "the API")
        self.assertEqual(snap.frequency_seconds, 300)

    def test_written_node_is_stamped_unwritten_container_is_not(self):
        # ADR-0027: a timestamp means a check wrote the node. The container the
        # upsert created on the way down was never written, so it has none — and no
        # age either (the process start time can no longer pose as an observation).
        # No mount is registered here, so nothing is inherited either
        # (MountTimestampTests covers that).
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK)
        leaf = tree.snapshot("/svc/api")
        container = tree.snapshot("/svc")
        root = tree.snapshot()
        assert leaf is not None and container is not None and root is not None
        self.assertIsNotNone(leaf.timestamp)
        self.assertIsNone(container.timestamp)
        self.assertIsNone(root.timestamp)
        self.assertEqual(container.age_seconds, 0.0)
        self.assertFalse(container.stale)

    def test_maintenance_touch_stamps_an_otherwise_unwritten_node(self):
        # The maintenance guard refreshes the check time without changing the code,
        # so a pinned node keeps reporting a real observation.
        tree = StatusTree()
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now(UTC) + timedelta(days=1))
        tree.upsert("/db", StatusCode.OK)
        snap = tree.snapshot("/db")
        assert snap is not None
        self.assertIsNotNone(snap.timestamp)

    def test_history_periods(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        tree.upsert("/db", StatusCode.ERROR, "down")
        tree.upsert("/db", StatusCode.OK, "recovered")
        periods = tree.history("/db")
        self.assertEqual([p.code for p in periods],
                         [StatusCode.OK, StatusCode.ERROR, StatusCode.OK])
        self.assertEqual(periods[-1].reason, ("recovered",))
        snap = tree.snapshot("/db")
        assert snap is not None
        self.assertEqual(periods[-1].until, snap.timestamp)

    def test_a_pin_silences_a_node_without_overwriting_its_reading(self):
        """The keystone (ADR-0032 rule 3): a pin is **recorded, never written**.

        Point for point the inverse of what this case asserted before, when the pin
        was stamped into ``Status.code`` — it used to check that the node's reason
        *became* the pin's text and that the engine could no longer write. Both were
        the deviation. The last block is the bug that made the slice urgent: clearing
        used to drop the node to ``UNDEFINED`` with an empty reason list, so it sat
        blank for up to a full check interval, and on the un-polled leaf page it came
        back only on a reload.
        """
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK, "all good")
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        snap = tree.snapshot("/db")
        assert snap is not None
        self.assertTrue(snap.maintenance)
        self.assertEqual(tree.effective("/db"), StatusCode.MAINTENANCE)
        self.assertEqual(snap.own_code, StatusCode.MAINTENANCE)  # what it shows
        self.assertEqual(snap.reported_code, StatusCode.OK)      # what the check said
        self.assertEqual(snap.reason, ("all good",))             # kept, not replaced
        entry = tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.note, "planned")     # the pin's own text lives here

        # the check keeps reporting underneath the pin, and the tree keeps it
        self.assertTrue(tree.upsert("/db", StatusCode.ERROR, "boom"))
        during = tree.snapshot("/db")
        assert during is not None
        self.assertEqual(during.own_code, StatusCode.MAINTENANCE)   # still silenced
        self.assertEqual(during.reported_code, StatusCode.ERROR)    # and still legible
        self.assertEqual(during.reason, ("boom",))

        # clearing restores the last known state *at once* — there is no blank window
        # because there was never anything to restore
        self.assertTrue(tree.clear_maintenance("/db").applied)
        after = tree.snapshot("/db")
        assert after is not None
        self.assertFalse(after.maintenance)
        self.assertEqual(after.own_code, StatusCode.ERROR)
        self.assertEqual(after.reason, ("boom",))

    def test_a_pinned_check_that_dies_still_escalates(self):
        """ADR-0032 rule 6: a suppression may not switch off the freshness path.

        The one test that fails on either half of this slice alone. With the pin
        still written into the node, ``_is_stale``'s ``node.maintenance`` exemption
        was load-bearing — removing it sent a ``MAINTENANCE`` code into
        ``worst_of``, which knows only OK/WARN/ERROR, and the snapshot raised. The
        two deviations propped each other up; correcting rule 3 is what makes rule 6
        free.
        """
        tree = StatusTree()
        tree.upsert("/system/db", StatusCode.OK, frequency_seconds=60)
        tree.set_maintenance("/system/db", "planned",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        fresh = tree.snapshot("/system/db")
        assert fresh is not None
        self.assertFalse(fresh.stale)
        # The pinned child contributes nothing, and it is the only one — so its
        # parent has nothing counted, and reads MAINTENANCE rather than UNDEFINED.
        # That was the open edge case ADR-0032 left for the roll-up's split, which
        # ADR-0039 rule 5 answers; this line asserted UNDEFINED while it was open, and
        # changed with it.
        self.assertEqual(tree.effective("/system"), StatusCode.MAINTENANCE)

        # nobody writes it again; the clock moves past two intervals
        later = datetime.now(UTC) + timedelta(seconds=200)
        stale = tree.snapshot("/system/db", now=later)
        assert stale is not None
        self.assertTrue(stale.stale)
        # it still *shows* maintenance — the card explains — but it stops
        # contributing nothing: a dead check escalates past the pin that silenced it
        self.assertEqual(stale.own_code, StatusCode.MAINTENANCE)
        parent = tree.snapshot("/system", now=later)
        assert parent is not None
        self.assertEqual(parent.code, StatusCode.WARN)

    def test_the_stale_escape_never_softens_a_known_failure(self):
        # `worst_of(reported, WARN)`, not a flat WARN: a real ERROR under a pin that
        # then goes stale must not be softened to amber because we stopped watching.
        tree = StatusTree()
        tree.upsert("/system/db", StatusCode.ERROR, "boom", frequency_seconds=60)
        tree.set_maintenance("/system/db", "planned",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        later = datetime.now(UTC) + timedelta(seconds=200)
        parent = tree.snapshot("/system", now=later)
        assert parent is not None
        self.assertEqual(parent.code, StatusCode.ERROR)

    def test_a_check_reported_maintenance_is_exempt_from_staleness(self):
        # the guard that replaced the pin exemption is on the **code**, and it closes
        # a latent crash of its own: a check may report MAINTENANCE itself, and that
        # carries no severity for the stale degrade to take the worst of.
        tree = StatusTree()
        tree.upsert("/db", StatusCode.MAINTENANCE, frequency_seconds=60)
        later = datetime.now(UTC) + timedelta(seconds=200)
        snap = tree.snapshot("/db", now=later)
        assert snap is not None
        self.assertFalse(snap.stale)

    def test_pinning_and_clearing_are_recorded_as_transitions(self):
        # A pin no longer changes `Status.code`, so these events are emitted
        # deliberately rather than falling out of a write. They stay transitions of
        # what the node *shows*, because that is the question history answers.
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, "boom")
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        pinned = tree.recent_events()[-1]
        self.assertEqual((pinned.old, pinned.new),
                         (StatusCode.ERROR, StatusCode.MAINTENANCE))
        self.assertEqual(pinned.reason, ("planned",))   # why it moved, not the reading
        tree.clear_maintenance("/db")
        cleared = tree.recent_events()[-1]
        self.assertEqual((cleared.old, cleared.new),
                         (StatusCode.MAINTENANCE, StatusCode.ERROR))
        self.assertEqual(cleared.reason, ("boom",))     # what it shows again

    def test_a_transition_under_a_pin_is_recorded_and_marked(self):
        """*An unmarked event is one that alarmed; a marked one is one that didn't.*

        Before the keystone there was no event here at all — `upsert` returned early
        under a pin — so *did it break during the window?* had no answer anywhere.
        """
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK, "all good")
        tree.set_maintenance("/db", "cutover",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        tree.upsert("/db", StatusCode.ERROR, "disk full")
        broke = tree.recent_events()[-1]
        self.assertEqual((broke.old, broke.new), (StatusCode.OK, StatusCode.ERROR))
        self.assertEqual(broke.suppressed_by, "maintenance")

    def test_the_pin_and_its_release_are_never_marked(self):
        # they are what everybody saw; marking them would falsify the sentence
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, "boom")
        tree.set_maintenance("/db", "cutover",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        self.assertEqual(tree.recent_events()[-1].suppressed_by, "")
        tree.clear_maintenance("/db")
        self.assertEqual(tree.recent_events()[-1].suppressed_by, "")

    def test_an_ordinary_transition_carries_no_marker(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        tree.upsert("/db", StatusCode.ERROR, "boom")
        self.assertEqual(tree.recent_events()[-1].suppressed_by, "")

    def test_a_check_that_reports_maintenance_itself_is_not_marked(self):
        # nothing suppressed it — it said so. The marker names a *rule* that acted.
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        tree.upsert("/db", StatusCode.MAINTENANCE)
        self.assertEqual(tree.recent_events()[-1].suppressed_by, "")

    def test_history_does_not_break_a_maintenance_window_into_phantoms(self):
        """What the node *showed* was maintenance, the whole time.

        The suppressed transitions stay in the event log — that is where *did it
        break during the window?* is answered — but counting them as periods would
        chop one window into ERROR stretches no surface ever displayed.
        """
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK, "all good")
        tree.set_maintenance("/db", "cutover",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        tree.upsert("/db", StatusCode.ERROR, "disk full")
        tree.upsert("/db", StatusCode.OK, "recovered")
        codes = [period.code for period in tree.history("/db")]
        self.assertEqual(codes, [StatusCode.OK, StatusCode.MAINTENANCE])
        # …and the breakage is still on the record
        marked = [e for e in tree.recent_events() if e.suppressed_by]
        self.assertEqual([e.new for e in marked],
                         [StatusCode.ERROR, StatusCode.OK])

    def test_a_pin_on_a_node_no_check_has_written_still_records(self):
        # `_apply_maintenance` used to stamp the node through `update`; now it does
        # not, so an event on a container that has never been observed has no
        # observation time to borrow and carries the moment the admin acted.
        tree = StatusTree()
        tree.set_maintenance("/planned/window", "cutover",
                             expires_at=datetime.now(UTC) + timedelta(hours=2))
        event = tree.recent_events()[-1]
        self.assertEqual(event.new, StatusCode.MAINTENANCE)
        self.assertTrue(event.timestamp)

    def test_stale_node_degrades(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK, frequency_seconds=60)
        fresh = tree.snapshot("/db")
        assert fresh is not None
        self.assertFalse(fresh.stale)
        self.assertEqual(fresh.code, StatusCode.OK)
        future = datetime.now(UTC) + timedelta(hours=1)
        stale = tree.snapshot("/db", now=future)
        assert stale is not None
        self.assertTrue(stale.stale)
        self.assertEqual(stale.code, StatusCode.WARN)     # degraded
        self.assertEqual(stale.own_code, StatusCode.OK)   # raw code unchanged

    def test_a_branch_says_whether_the_stale_reading_is_its_own(self):
        # `stale` is the alarm, and a branch carries it for every node beneath it;
        # `own_stale` is the fact about the node's own reading
        tree = StatusTree()
        tree.upsert("/gateway", StatusCode.OK, "answers", frequency_seconds=60)
        tree.upsert("/gateway/backend", StatusCode.OK, "fine")
        tree.upsert("/hosts", StatusCode.OK, "all reachable")
        tree.upsert("/hosts/nexus", StatusCode.OK, "fine", frequency_seconds=60)
        later = datetime.now(UTC) + timedelta(hours=1)

        def said(path: str) -> tuple[bool, bool]:
            node = tree.snapshot(path, now=later)
            assert node is not None
            return node.stale, node.own_stale

        self.assertEqual(said("/gateway"), (True, True))
        self.assertEqual(said("/gateway/backend"), (False, False))
        self.assertEqual(said("/hosts"), (True, False))     # a node beneath it is
        self.assertEqual(said("/hosts/nexus"), (True, True))
        self.assertEqual(said(""), (True, False))
        fresh = tree.snapshot("/gateway")
        assert fresh is not None
        self.assertEqual((fresh.stale, fresh.own_stale), (False, False))

    def test_a_stated_tolerance_is_what_freshness_measures(self):
        # ADR-0081: a node may be read on no check's schedule and still have to go
        # stale — the engine re-asserts its own branch every tick, and the stamp is
        # what makes a dead scheduler visible (ADR-0005). It states the tolerance
        # outright instead of stamping the tick as a period, so nothing downstream
        # has a period to report as a check's.
        tree = StatusTree()
        tree.upsert("/little-sister/startup", StatusCode.OK, stale_after=31.0)
        snap = tree.snapshot("/little-sister/startup")
        assert snap is not None
        self.assertIsNone(snap.frequency_seconds, "no period to misreport")
        self.assertEqual(snap.stale_after_seconds, 31.0)
        self.assertFalse(snap.stale)
        fresh = tree.snapshot("/little-sister/startup",
                              now=datetime.now(UTC) + timedelta(seconds=30))
        assert fresh is not None
        self.assertFalse(fresh.stale)
        gone = tree.snapshot("/little-sister/startup",
                             now=datetime.now(UTC) + timedelta(seconds=32))
        assert gone is not None
        self.assertTrue(gone.stale)
        self.assertEqual(gone.code, StatusCode.WARN)

    def test_a_stated_tolerance_wins_over_the_one_a_period_implies(self):
        # Two sources, one answer, and the stated one is the answer — a deployment
        # that says how fresh a reading has to be is not overruled by arithmetic
        # over a period (ADR-0079 decision 1).
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK, frequency_seconds=60, stale_after=45.0)
        snap = tree.snapshot("/db")
        assert snap is not None
        self.assertEqual(snap.stale_after_seconds, 45.0)
        self.assertEqual(snap.frequency_seconds, 60, "the period is still shown")
        self.assertTrue(tree.snapshot(
            "/db", now=datetime.now(UTC) + timedelta(seconds=50)).stale)

    def test_stale_rolls_up(self):
        tree = StatusTree()
        tree.upsert("/svc/a", StatusCode.OK, frequency_seconds=60)
        svc = tree.snapshot("/svc", now=datetime.now(UTC) + timedelta(hours=1))
        assert svc is not None
        self.assertEqual(svc.code, StatusCode.WARN)
        self.assertTrue(svc.stale)

    def test_stale_does_not_downgrade_error(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, "boom", frequency_seconds=60)
        snap = tree.snapshot("/db", now=datetime.now(UTC) + timedelta(hours=1))
        assert snap is not None
        self.assertTrue(snap.stale)
        self.assertEqual(snap.code, StatusCode.ERROR)

    def test_maintenance_is_not_stale(self):
        # a node its deployment declared and no check has written yet: a pin makes
        # no node (ADR-0109 decision 4), so the declaration is what it stands on
        tree = StatusTree()
        tree.set_title("/db", "Database")
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now(UTC) + timedelta(days=7))
        snap = tree.snapshot("/db", now=datetime.now(UTC) + timedelta(hours=1))
        assert snap is not None
        self.assertFalse(snap.stale)
        self.assertEqual(snap.code, StatusCode.MAINTENANCE)


class MountTimestampTests(TestCase):
    """Sole-mount resolution of the published observation time (ADR-0027)."""

    @staticmethod
    def _stamp(tree, path=""):
        snap = tree.snapshot(path)
        assert snap is not None
        return snap.timestamp

    def test_sole_mount_stamps_every_unwritten_ancestor(self):
        # The ADR's example: a deployment whose only check mounts at
        # /system/node_a/host_metrics reports that check's run time on
        # /system/node_a, /system and / alike.
        tree = StatusTree()
        tree.set_check_mount("/system/node_a/host_metrics")
        tree.upsert("/system/node_a/host_metrics", StatusCode.OK)
        mount = self._stamp(tree, "/system/node_a/host_metrics")
        self.assertIsNotNone(mount)
        self.assertEqual(self._stamp(tree, "/system/node_a"), mount)
        self.assertEqual(self._stamp(tree, "/system"), mount)
        self.assertEqual(self._stamp(tree), mount)

    def test_second_mount_clears_the_shared_ancestors_only(self):
        # A second mount makes any single value on a shared ancestor attribute one
        # check's run time to another check's data, so the value disappears rather
        # than changing meaning. Ancestors that still cover exactly one mount keep it.
        tree = StatusTree()
        for path in ("/system/node_a/host_metrics", "/system/node_b/host_metrics"):
            tree.set_check_mount(path)
            tree.upsert(path, StatusCode.OK)
        self.assertIsNone(self._stamp(tree, "/system"))
        self.assertIsNone(self._stamp(tree))
        for host in ("/system/node_a", "/system/node_b"):
            self.assertEqual(self._stamp(tree, host),
                             self._stamp(tree, host + "/host_metrics"))

    def test_two_checks_on_one_mount_block_the_ancestors(self):
        # host-metrics + a hardware probe on one host node (the ADR-0044
        # of ADR-0027, reversing the earlier reading): the shared node's own last
        # write answers for *itself* (rule 2), but inherited upward that single
        # value would present one check's run time as both checks' — rule 4's
        # ambiguity, now enforced by counting checks per path rather than paths.
        tree = StatusTree()
        tree.set_check_mount("/system/node_a/metrics")
        tree.set_check_mount("/system/node_a/metrics")
        tree.upsert("/system/node_a/metrics", StatusCode.OK)
        self.assertIsNotNone(self._stamp(tree, "/system/node_a/metrics"))
        self.assertIsNone(self._stamp(tree, "/system/node_a"))
        self.assertIsNone(self._stamp(tree))

    def test_a_shared_mount_beside_a_sole_one_still_blocks_the_root(self):
        # Two checks on one path count as two: the root covers three checks in
        # total, so nothing is inherited anywhere above the mounts themselves.
        tree = StatusTree()
        tree.set_check_mount("/shared/host")
        tree.set_check_mount("/shared/host")
        tree.set_check_mount("/site/disk")
        tree.upsert("/shared/host", StatusCode.OK)
        tree.upsert("/site/disk", StatusCode.OK)
        self.assertIsNone(self._stamp(tree))
        self.assertIsNone(self._stamp(tree, "/shared"))
        # the sole-check side keeps its own inheritance
        self.assertEqual(self._stamp(tree, "/site"),
                         self._stamp(tree, "/site/disk"))

    def test_never_run_sole_mount_yields_none(self):
        # Registration alone is not an observation — and it does not create the node
        # either; the tree's visible shape still grows only with results.
        tree = StatusTree()
        tree.set_check_mount("/system/node_a/host_metrics")
        self.assertIsNone(self._stamp(tree))
        self.assertIsNone(tree.snapshot("/system"))
        self.assertEqual(tree.snapshot().children, ())

    def test_heartbeat_neither_blocks_nor_feeds_the_rollup(self):
        # The engine's heartbeat node is written every tick but is not a check
        # mount: it must not count as a second mount (which would clear the root),
        # and on its own it must not feed the root a stamp either.
        tree = StatusTree()
        tree.upsert(HEARTBEAT_PATH, StatusCode.OK)
        self.assertIsNone(self._stamp(tree))
        tree.set_check_mount("/system/node_a/host_metrics")
        tree.upsert("/system/node_a/host_metrics", StatusCode.OK)
        self.assertEqual(self._stamp(tree),
                         self._stamp(tree, "/system/node_a/host_metrics"))

    def test_branch_snapshot_resolves_from_its_own_subtree(self):
        # A branch snapshot sees only its own subtree, so /a inherits from the one
        # mount below it even though the whole tree holds two.
        tree = StatusTree()
        for path in ("/a/check_1", "/b/check_2"):
            tree.set_check_mount(path)
            tree.upsert(path, StatusCode.OK)
        self.assertIsNone(self._stamp(tree))
        self.assertEqual(self._stamp(tree, "/a"), self._stamp(tree, "/a/check_1"))
        self.assertEqual(self._stamp(tree, "/b"), self._stamp(tree, "/b/check_2"))

    def test_written_node_keeps_its_own_stamp_over_an_inherited_one(self):
        # A branch check writes its container too, so that node answers for itself;
        # the sole-mount value is only ever a fallback.
        tree = StatusTree()
        tree.set_check_mount("/system/node_a/host_metrics")
        tree.upsert("/system/node_a/host_metrics", StatusCode.OK)
        tree.upsert("/system/node_a/host_metrics/disk", StatusCode.OK)
        tree.upsert("/system/node_a", StatusCode.OK)
        node_a = tree.snapshot("/system/node_a")
        assert node_a is not None
        self.assertIsNotNone(node_a.timestamp)
        mount = self._stamp(tree, "/system/node_a/host_metrics")
        self.assertNotEqual(node_a.timestamp, mount)
        # ... while the container that was *not* written inherits the **mount's**
        # stamp — not the nearest written descendant's. Only a mount answers the
        # question "when did the check behind this node run?".
        self.assertEqual(self._stamp(tree, "/system"), mount)

    def test_inheritance_does_not_leak_into_staleness_or_age(self):
        # `stale` and `age_seconds` keep measuring the node's own stamp: an
        # inherited time is a display value, not an observation of this node.
        tree = StatusTree()
        tree.set_check_mount("/system/node_a/host_metrics")
        tree.upsert("/system/node_a/host_metrics", StatusCode.OK,
                    frequency_seconds=60)
        container = tree.snapshot("/system/node_a",
                                  now=datetime.now(UTC) + timedelta(hours=1))
        assert container is not None
        self.assertIsNotNone(container.timestamp)
        self.assertEqual(container.age_seconds, 0.0)
        # The mount itself is long overdue, and that *does* roll up as `stale`.
        self.assertTrue(container.stale)


class RunFactsTests(TestCase):
    """Resolution of the owning check's last-run facts (ADR-0044): present
    exactly where the subtree holds **one** check — the sole mount and the
    unwritten ancestors above it — and withheld everywhere the timestamp
    roll-up refuses a stamp, by the same count."""

    @staticmethod
    def _run(tree, path=""):
        snap = tree.snapshot(path)
        assert snap is not None
        return snap.run

    def test_the_sole_mount_carries_its_facts(self):
        tree = StatusTree()
        tree.set_check_mount("/svc/github")
        tree.upsert("/svc/github", StatusCode.OK)
        tree.set_run_facts("/svc/github", wall_seconds=1.25,
                           next_run_at=datetime(2026, 8, 6, 9, 20, tzinfo=UTC))
        facts = self._run(tree, "/svc/github")
        assert facts is not None
        self.assertEqual(facts.wall_seconds, 1.25)
        self.assertEqual(facts.next_run_at, datetime(2026, 8, 6, 9, 20, tzinfo=UTC))

    def test_unwritten_ancestors_inherit_the_facts_with_the_stamp(self):
        # Safe for the same reason the inherited stamp is: above a sole mount,
        # one check owns everything below, so the facts can only be that run's.
        tree = StatusTree()
        tree.set_check_mount("/svc/github")
        tree.upsert("/svc/github", StatusCode.OK)
        tree.set_run_facts("/svc/github", wall_seconds=0.5,
                           next_run_at=datetime(2026, 8, 6, 9, 20, tzinfo=UTC))
        mount = self._run(tree, "/svc/github")
        self.assertIsNotNone(mount)
        self.assertEqual(self._run(tree, "/svc"), mount)
        self.assertEqual(self._run(tree), mount)

    def test_a_leaf_below_a_branch_mount_carries_none(self):
        # The leaf's next update belongs to the node where the check is named,
        # one level up — nothing rolls *down*.
        tree = StatusTree()
        tree.set_check_mount("/svc/github")
        tree.upsert("/svc/github", StatusCode.OK)
        tree.upsert("/svc/github/actions", StatusCode.OK)
        tree.set_run_facts("/svc/github", wall_seconds=0.5,
                           next_run_at=datetime(2026, 8, 6, 9, 20, tzinfo=UTC))
        self.assertIsNotNone(self._run(tree, "/svc/github"))
        self.assertIsNone(self._run(tree, "/svc/github/actions"))

    def test_a_shared_mount_and_its_ancestors_carry_none(self):
        # Two checks on one path: facts were written (last writer wins in the
        # registry), and the count is what keeps them off every snapshot — a
        # value that flips between two checks' runs is rule 4's ambiguity,
        # run-facts edition (ADR-0044 decision 1).
        tree = StatusTree()
        tree.set_check_mount("/system/node_a/metrics")
        tree.set_check_mount("/system/node_a/metrics")
        tree.upsert("/system/node_a/metrics", StatusCode.OK)
        tree.set_run_facts("/system/node_a/metrics", wall_seconds=0.2,
                           next_run_at=datetime(2026, 8, 6, 9, 20, tzinfo=UTC))
        self.assertIsNone(self._run(tree, "/system/node_a/metrics"))
        self.assertIsNone(self._run(tree, "/system/node_a"))
        self.assertIsNone(self._run(tree))

    def test_two_sole_mounts_keep_their_own_and_block_the_root(self):
        tree = StatusTree()
        for path, next_at in (("/a/check_1", datetime(2026, 8, 6, 9, 20, tzinfo=UTC)),
                              ("/b/check_2", datetime(2026, 8, 6, 9, 25, tzinfo=UTC))):
            tree.set_check_mount(path)
            tree.upsert(path, StatusCode.OK)
            tree.set_run_facts(path, wall_seconds=0.1, next_run_at=next_at)
        side_a = self._run(tree, "/a")
        side_b = self._run(tree, "/b")
        assert side_a is not None and side_b is not None
        self.assertEqual(side_a.next_run_at, datetime(2026, 8, 6, 9, 20, tzinfo=UTC))
        self.assertEqual(side_b.next_run_at, datetime(2026, 8, 6, 9, 25, tzinfo=UTC))
        self.assertIsNone(self._run(tree))

    def test_rewriting_replaces_the_facts(self):
        tree = StatusTree()
        tree.set_check_mount("/svc/github")
        tree.upsert("/svc/github", StatusCode.OK)
        tree.set_run_facts("/svc/github", wall_seconds=1.0,
                           next_run_at=datetime(2026, 8, 6, 9, 20, tzinfo=UTC))
        tree.set_run_facts("/svc/github", wall_seconds=2.0, next_run_at=None)
        facts = self._run(tree, "/svc/github")
        assert facts is not None
        self.assertEqual(facts.wall_seconds, 2.0)
        self.assertIsNone(facts.next_run_at)


class ReportTests(TestCase):
    """`report` — what the run **found** (ADR-0044 decision 6) — beside `config`'s
    what it ran **with**, and the ownership rule both answer to: the check's own
    text belongs to the check that owns the node **alone** (decision 1)."""

    @staticmethod
    def _node(tree, path):
        snap = tree.snapshot(path)
        assert snap is not None
        return snap

    def test_report_writes_through_every_run(self):
        tree = StatusTree()
        tree.upsert("/svc/github", StatusCode.OK, report="- alpha\n- beta")
        self.assertEqual(self._node(tree, "/svc/github").report,
                         "- alpha\n- beta")
        tree.upsert("/svc/github", StatusCode.OK, report="- alpha")
        self.assertEqual(self._node(tree, "/svc/github").report, "- alpha")

    def test_an_empty_report_clears_the_last_one(self):
        # The distinguishing property against `about` (seeded once) and against
        # config's don't-clobber guard: a roster the current run no longer finds
        # must not outlive the run that found it.
        tree = StatusTree()
        tree.upsert("/svc/github", StatusCode.OK, report="- alpha")
        tree.upsert("/svc/github", StatusCode.OK, report="")
        self.assertEqual(self._node(tree, "/svc/github").report, "")

    def test_an_omitted_report_leaves_the_stored_one_alone(self):
        # `None` is "no opinion" for every upsert field; only the engine's
        # per-run call, which always passes the result's value, clears.
        tree = StatusTree()
        tree.upsert("/svc/github", StatusCode.OK, report="- alpha")
        tree.upsert("/svc/github", StatusCode.WARN, "slow")
        self.assertEqual(self._node(tree, "/svc/github").report, "- alpha")

    def test_report_is_not_a_transition(self):
        # Display metadata, like config: changing it emits no event (ADR-0044
        # decision 6 — anything that should alarm is a reason).
        tree = StatusTree()
        tree.upsert("/svc/github", StatusCode.OK, report="- alpha")
        self.assertFalse(tree.upsert("/svc/github", StatusCode.OK,
                                     report="- beta"))

    def test_a_sole_mount_publishes_its_config_and_report(self):
        tree = StatusTree()
        tree.set_check_mount("/svc/github")
        tree.upsert("/svc/github", StatusCode.OK,
                    config="- **scope:** org", report="- alpha")
        node = self._node(tree, "/svc/github")
        self.assertEqual(node.config, "- **scope:** org")
        self.assertEqual(node.report, "- alpha")

    def test_a_shared_mount_publishes_neither(self):
        # One rule over four facts (decision 1): where two checks share a node,
        # the run time and the run facts are already withheld, and the check's
        # own **text** goes the same way — a value that flips between two
        # checks' runs is worse than no value at all.
        tree = StatusTree()
        tree.set_check_mount("/system/node_a")
        tree.set_check_mount("/system/node_a")
        tree.upsert("/system/node_a", StatusCode.OK,
                    config="- **host:** a", report="- alpha")
        node = self._node(tree, "/system/node_a")
        self.assertEqual(node.config, "")
        self.assertEqual(node.report, "")

    def test_a_child_below_a_shared_mount_keeps_its_own_text(self):
        # The withholding condition is the node's **own** mount count, not the
        # subtree's: per-child text is exactly where a shared container's checks
        # are told to put it (decision 7), so it must survive there.
        tree = StatusTree()
        tree.set_check_mount("/system/node_a")
        tree.set_check_mount("/system/node_a")
        tree.upsert("/system/node_a", StatusCode.OK, report="- shared")
        tree.upsert("/system/node_a/disk", StatusCode.OK,
                    config="- **threshold:** 90%", report="- /dev/sda1")
        child = self._node(tree, "/system/node_a/disk")
        self.assertEqual(child.config, "- **threshold:** 90%")
        self.assertEqual(child.report, "- /dev/sda1")

    def test_the_stored_text_survives_the_withholding(self):
        # Withheld at the snapshot, not destroyed in the tree: drop one of the
        # two checks and the surviving owner's text answers again (the ADR-0032
        # rule-3 shape — a policy is not implemented by writing a different
        # value into the tree).
        tree = StatusTree()
        tree.set_check_mount("/system/node_a")
        tree.upsert("/system/node_a", StatusCode.OK, report="- alpha")
        self.assertEqual(self._node(tree, "/system/node_a").report, "- alpha")
        tree.set_check_mount("/system/node_a")
        self.assertEqual(self._node(tree, "/system/node_a").report, "")


class UnwrittenNodeHistoryTests(TestCase):
    """A pin can land on a container **no check has ever written** — `_emit` says
    so outright and stamps the event with the moment the admin acted. History then
    has a real transition and no observation to bound it, which used to trip an
    `assert node.timestamp is not None`: `/history/<that container>` was a 500,
    and the branch page asking for its own period would have been another."""

    def test_a_pinned_unwritten_container_has_an_unbounded_period(self):
        tree = StatusTree()
        tree.upsert("/system/alpha/disk", StatusCode.OK)
        tree.set_maintenance("/system/alpha", "rebuild",
                             expires_at=datetime.now(UTC) + timedelta(days=1),
                             set_by="pan")
        periods = tree.history("/system/alpha")
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[-1].code, StatusCode.MAINTENANCE)
        self.assertIsNotNone(periods[-1].since)
        self.assertIsNone(periods[-1].until)

    def test_an_observed_node_still_ends_at_its_last_check(self):
        tree = StatusTree()
        tree.upsert("/svc/api", StatusCode.OK)
        tree.upsert("/svc/api", StatusCode.ERROR, "down")
        snap = tree.snapshot("/svc/api")
        assert snap is not None
        self.assertEqual(tree.history("/svc/api")[-1].until, snap.timestamp)


class SiblingOrderingTests(TestCase):
    @staticmethod
    def _names(snap):
        return [child.name for child in snap.children]

    def test_children_sorted_natural_case_insensitive(self):
        tree = StatusTree()
        for name in ("node10", "node2", "Node1", "beta", "Alpha"):
            tree.upsert(f"/p/{name}", StatusCode.OK)
        snap = tree.snapshot("/p")
        assert snap is not None
        # case-insensitive, and node2 before node10 (natural, not lexicographic)
        self.assertEqual(self._names(snap),
                         ["Alpha", "beta", "Node1", "node2", "node10"])

    def test_numbered_nodes_order_numerically(self):
        tree = StatusTree()
        for name in ("drive10", "drive2", "drive1"):
            tree.upsert(f"/bay/{name}", StatusCode.OK)
        snap = tree.snapshot("/bay")
        assert snap is not None
        self.assertEqual(self._names(snap), ["drive1", "drive2", "drive10"])

    def test_every_level_is_sorted(self):
        tree = StatusTree()
        tree.upsert("/p/b/y", StatusCode.OK)
        tree.upsert("/p/b/x", StatusCode.OK)
        tree.upsert("/p/a", StatusCode.OK)
        snap = tree.snapshot("/p")
        assert snap is not None
        self.assertEqual(self._names(snap), ["a", "b"])           # top level
        branch = next(c for c in snap.children if c.name == "b")
        self.assertEqual([c.name for c in branch.children], ["x", "y"])  # nested


class DeclaredRankTests(TestCase):
    """A check (or a deployment) may rank its own siblings — ADR-0055."""

    @staticmethod
    def _names(snap):
        return [child.name for child in snap.children]

    def _bands(self, tree, path="/wiz"):
        snap = tree.snapshot(path)
        assert snap is not None
        return self._names(snap)

    def test_saying_nothing_is_exactly_todays_order(self):
        # The whole safety of the mechanism: an undeclared rank reads 0, so a set
        # of siblings nobody ranked interleaves by name as it always did.
        tree = StatusTree()
        for name in ("critical", "high", "informational", "low", "medium"):
            tree.upsert(f"/wiz/{name}", StatusCode.OK)
        self.assertEqual(
            self._bands(tree),
            ["critical", "high", "informational", "low", "medium"])

    def test_a_declared_rank_moves_the_node(self):
        # The motivating case: `informational` means *nothing to do* and the name
        # sort puts it third, between `high` and `low`.
        tree = StatusTree()
        for name in ("critical", "high", "informational", "low", "medium"):
            tree.upsert(f"/wiz/{name}", StatusCode.OK)
        tree.set_order("/wiz/critical", -2)
        tree.set_order("/wiz/high", -1)
        tree.set_order("/wiz/informational", 1)
        self.assertEqual(
            self._bands(tree),
            ["critical", "high", "low", "medium", "informational"])

    def test_ties_still_break_by_name(self):
        tree = StatusTree()
        for name in ("delta", "alpha", "charlie", "bravo"):
            tree.upsert(f"/wiz/{name}", StatusCode.OK)
        tree.set_order("/wiz/delta", 1)
        tree.set_order("/wiz/charlie", 1)
        self.assertEqual(self._bands(tree),
                         ["alpha", "bravo", "charlie", "delta"])

    def test_an_unranked_sibling_keeps_the_zero_baseline(self):
        # One ranked node moves relative to the others; the rest do not reshuffle.
        tree = StatusTree()
        for name in ("b", "c", "d"):
            tree.upsert(f"/wiz/{name}", StatusCode.OK)
        tree.set_order("/wiz/d", -1)
        self.assertEqual(self._bands(tree), ["d", "b", "c"])

    def test_the_rank_is_the_check_s_until_a_deployment_says_otherwise(self):
        # upsert fills an *unset* field only, so a startup seed always wins — and
        # a later tick never rewrites what it filled.
        tree = StatusTree()
        tree.set_order("/wiz/critical", 5)
        tree.upsert("/wiz/critical", StatusCode.OK, order=-1)
        tree.upsert("/wiz/high", StatusCode.OK, order=-1)
        tree.upsert("/wiz/high", StatusCode.OK, order=9)   # a later tick
        self.assertEqual(tree.snapshot("/wiz/critical").order, 5)
        self.assertEqual(tree.snapshot("/wiz/high").order, -1)

    #: The `wiz` bands as the check ranks them — severity order, 1..5. Nothing here
    #: is 0, which is what makes it the right model for the escape hatch below: a
    #: set where every sibling carries a positive rank is exactly where "put this
    #: one back" is tempting to write and easy to get wrong.
    _WIZ_RANKS: ClassVar[dict[str, int]] = {
        "critical": 1, "high": 2, "medium": 3, "low": 4, "informational": 5}

    def _wiz_ranked_by_the_check(self, tree):
        """The `wiz` bands with the check's own severity ranking on every one."""
        for name, rank in self._WIZ_RANKS.items():
            tree.upsert(f"/wiz/{name}", StatusCode.OK, order=rank)
        return tree

    def test_a_zeroed_node_sits_between_the_negative_and_the_positive(self):
        tree = StatusTree()
        tree.set_order("/wiz/zeta", 0)
        tree.upsert("/wiz/zeta", StatusCode.OK)
        tree.upsert("/wiz/above", StatusCode.OK, order=-1)
        tree.upsert("/wiz/below", StatusCode.OK, order=1)
        tree.upsert("/wiz/aaa", StatusCode.OK)          # unranked, so also 0
        self.assertEqual(self._bands(tree),
                         ["above", "aaa", "zeta", "below"])

    def test_a_configured_zero_overrules_the_check_by_naming_the_default(self):
        # `0` from the configuration is a real declaration, not silence — which is
        # why the node's field is nullable. Without it a deployment could push a
        # node around but never lower it back to the baseline.
        ranked = self._wiz_ranked_by_the_check(StatusTree())
        self.assertEqual(
            self._bands(ranked),
            ["critical", "high", "medium", "low", "informational"])

        overruled = StatusTree()
        overruled.set_order("/wiz/informational", 0)      # the configured half
        self._wiz_ranked_by_the_check(overruled)
        self.assertEqual(overruled.snapshot("/wiz/informational").order, 0)

    def test_a_zeroed_node_sorts_with_the_unranked_not_at_its_alphabetical_place(self):
        """The escape hatch is per node, not per set — and the difference is exactly
        what the prose used to get wrong, so it is pinned rather than described.

        `0` is the rank the *unranked* carry, so zeroing one child of a ranked set
        moves it to the **front** of that set. Only zeroing every sibling restores
        plain alphabetical order.
        """
        one = StatusTree()
        one.set_order("/wiz/informational", 0)
        self._wiz_ranked_by_the_check(one)
        self.assertEqual(
            self._bands(one),
            ["informational", "critical", "high", "medium", "low"])
        self.assertNotEqual(self._bands(one), sorted(self._bands(one)))

        every = StatusTree()
        for band in self._WIZ_RANKS:
            every.set_order(f"/wiz/{band}", 0)
        self._wiz_ranked_by_the_check(every)
        self.assertEqual(self._bands(every), sorted(self._bands(every)))
        self.assertEqual(
            self._bands(every),
            ["critical", "high", "informational", "low", "medium"])

    def test_a_rank_is_never_a_status_event(self):
        tree = StatusTree()
        tree.upsert("/wiz/critical", StatusCode.OK)
        before = len(tree.recent_events())
        tree.set_order("/wiz/critical", 3)
        self.assertEqual(len(tree.recent_events()), before)

    def test_ranks_apply_at_every_level(self):
        tree = StatusTree()
        tree.upsert("/p/a/y", StatusCode.OK)
        tree.upsert("/p/a/x", StatusCode.OK)
        tree.upsert("/p/b", StatusCode.OK)
        tree.set_order("/p/b", -1)
        tree.set_order("/p/a/y", -1)
        snap = tree.snapshot("/p")
        assert snap is not None
        self.assertEqual(self._names(snap), ["b", "a"])
        branch = next(c for c in snap.children if c.name == "a")
        self.assertEqual([c.name for c in branch.children], ["y", "x"])


class ShowWhenQuietTests(TestCase):
    """A node may decline the density trade — ADR-0063, in the tree.

    Display metadata like `about` / `title` / `order`: seeded at startup from the
    configuration, filled from a running `CheckResult` only where nothing is set,
    and never a status event. What is its own is the **tri-state**, which every
    test here turns on: `None` is nobody-said and `False` is a statement.
    """

    def test_unstated_is_none_not_false(self):
        # The distinction the whole field rests on. Collapsing it to a bool would
        # make every node a declaration of "ordinary", which nothing could fill.
        tree = StatusTree()
        tree.upsert("/aws/ec2", StatusCode.OK)
        self.assertIsNone(tree.snapshot("/aws/ec2").show_when_quiet)

    def test_a_check_fills_an_unset_field(self):
        tree = StatusTree()
        tree.upsert("/aws/ec2", StatusCode.OK, show_when_quiet=True)
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)

    def test_a_check_may_state_false_and_it_is_stored_as_a_statement(self):
        tree = StatusTree()
        tree.upsert("/aws/batch", StatusCode.OK, show_when_quiet=False)
        self.assertIs(tree.snapshot("/aws/batch").show_when_quiet, False)

    def test_a_seeded_false_is_not_filled_over_by_a_check_s_true(self):
        # The sentence the tri-state exists for: a deployment writing
        # `show_when_quiet: false` in nodes.yaml declines a claim the check type
        # ships, and the next tick must not take it back.
        tree = StatusTree()
        tree.set_show_when_quiet("/aws/ec2", False)
        tree.upsert("/aws/ec2", StatusCode.OK, show_when_quiet=True)
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, False)

    def test_a_seeded_true_survives_a_check_saying_nothing(self):
        tree = StatusTree()
        tree.set_show_when_quiet("/aws/ec2", True)
        tree.upsert("/aws/ec2", StatusCode.OK)
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)

    def test_the_fill_freezes_at_the_first_tick(self):
        # Seed-time, like the labels: a changed declaration is a restart.
        tree = StatusTree()
        tree.upsert("/aws/ec2", StatusCode.OK, show_when_quiet=True)
        tree.upsert("/aws/ec2", StatusCode.OK, show_when_quiet=False)
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)

    def test_seeding_auto_creates_the_node(self):
        # Like set_about: a declaration may name a container no check has built.
        tree = StatusTree()
        tree.set_show_when_quiet("/aws/ec2", True)
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)

    def test_declaring_it_is_never_a_status_event(self):
        # Display metadata, not status (ADR-0013's grammar).
        tree = StatusTree()
        tree.upsert("/aws/ec2", StatusCode.OK)
        before = len(tree.recent_events())
        tree.set_show_when_quiet("/aws/ec2", True)
        tree.upsert("/aws/ec2", StatusCode.OK, show_when_quiet=False)
        self.assertEqual(len(tree.recent_events()), before)

    def test_it_changes_no_status_anywhere(self):
        tree = StatusTree()
        tree.upsert("/aws/ec2", StatusCode.OK, show_when_quiet=True)
        tree.upsert("/aws/batch", StatusCode.WARN, "queue backed up")
        self.assertEqual(tree.snapshot("/aws").code, StatusCode.WARN)
        self.assertEqual(tree.snapshot("/aws/ec2").code, StatusCode.OK)

    def test_the_declaration_does_not_cascade_to_children(self):
        # Per node, deliberately (ADR-0063): a declared container keeps its own
        # box and its quiet leaves chip as usual unless declared themselves.
        tree = StatusTree()
        tree.upsert("/aws/ec2", StatusCode.OK, show_when_quiet=True)
        tree.upsert("/aws/ec2/eu-west-1", StatusCode.OK)
        child = tree.snapshot("/aws/ec2").children[0]
        self.assertEqual(child.name, "eu-west-1")
        self.assertIsNone(child.show_when_quiet)


class MaintenancePersistenceTests(TestCase):
    def _entry(self, expires_at, *, note="planned", set_by="ada"):
        now = datetime.now(UTC)
        return Pin(MAINTENANCE, note=note, set_at=now,
                                expires_at=expires_at, set_by=set_by)

    def test_set_and_clear_write_through(self):
        store = _RecordingStore()
        tree = StatusTree(pin_store=store)
        tree.upsert("/db", StatusCode.OK)
        tree.set_maintenance("/db", "planned", set_by="ada",
                             expires_at=datetime.now(UTC) + timedelta(days=1))
        self.assertEqual(set(store.saved), {"/db"})
        self.assertEqual(store.saved["/db"].set_by, "ada")
        snap = tree.snapshot("/db")
        assert snap is not None and snap.maintenance_entry is not None
        self.assertEqual(snap.maintenance_entry.note, "planned")
        tree.clear_maintenance("/db")
        self.assertEqual(store.saved, {})

    def test_restore_replays_non_expired_and_drops_expired(self):
        store = _RecordingStore()
        tree = StatusTree(pin_store=store)
        now = datetime.now(UTC)
        entries = {
            "db": self._entry(now + timedelta(days=1)),
            "cache": self._entry(now - timedelta(days=1), note="old"),
        }
        tree.restore_maintenance(entries, now=now)
        # the pin is held against its path, and a replay makes no node for it
        # (ADR-0109 decision 4): the node its check writes is pinned from the first
        self.assertIsNotNone(tree.maintenance_entry("/db"))
        self.assertIsNone(tree.snapshot("/db"))
        tree.upsert("/db", StatusCode.OK)
        db = tree.snapshot("/db")
        assert db is not None
        self.assertTrue(db.maintenance)
        self.assertEqual(db.code, StatusCode.MAINTENANCE)
        self.assertIsNone(tree.maintenance_entry("/cache"))   # expired: dropped
        self.assertIsNone(tree.snapshot("/cache"))
        self.assertEqual(set(store.saved), {"/db"})     # file rewritten without it

    def test_adopt_replaces_the_table_in_a_running_process(self):
        """ADR-0077: the side-table's ``restore`` — what the new table lacks is
        cleared with a real transition, what it carries is applied, expired pins
        are dropped, per-entry pins are replaced whole, nothing is written."""
        store = _RecordingStore()
        tree = StatusTree(pin_store=store)
        now = datetime.now(UTC)
        tree.upsert("/db", StatusCode.OK)
        tree.upsert("/cache", StatusCode.OK)
        tree.upsert("/web", StatusCode.OK)
        tree.set_maintenance("/db", "mine", expires_at=now + timedelta(days=1))
        tree.set_maintenance("/cache", "mine too", expires_at=now + timedelta(days=1))
        tree.set_entry_maintenance("/db", "slow", "old pin",
                                   expires_at=now + timedelta(days=1))
        written = dict(store.saved)
        adopted = {
            "/db": self._entry(now + timedelta(days=2), note="theirs"),
            "/web": self._entry(now + timedelta(days=2), note="new"),
            "/gone": self._entry(now - timedelta(days=1), note="expired"),
        }
        entry_pins = {("/web", "a"): self._entry(now + timedelta(days=2)),
                      ("/web", "b"): self._entry(now - timedelta(days=1))}

        tree.adopt_maintenance(adopted, entry_pins=entry_pins, now=now)

        # /cache is cleared back to its reading, /db is edited, /web is pinned,
        # the expired /gone never lands
        self.assertEqual(tree.effective("/cache"), StatusCode.OK)
        self.assertIsNone(tree.maintenance_entry("/cache"))
        self.assertEqual(tree.maintenance_entry("/db").note, "theirs")
        self.assertEqual(tree.effective("/web"), StatusCode.MAINTENANCE)
        self.assertIsNone(tree.snapshot("/gone"))
        self.assertEqual([(event.path, event.old, event.new)
                          for event in tree.recent_events()][-3:],
                         [("/cache", StatusCode.MAINTENANCE, StatusCode.OK),
                          ("/db", StatusCode.MAINTENANCE, StatusCode.MAINTENANCE),
                          ("/web", StatusCode.OK, StatusCode.MAINTENANCE)])
        self.assertIsNone(tree.entry_maintenance("/db", "slow"))
        self.assertIsNotNone(tree.entry_maintenance("/web", "a"))
        self.assertIsNone(tree.entry_maintenance("/web", "b"))
        # nothing written through: the file on disk is the copy being adopted
        self.assertEqual(store.saved, written)

    def test_sweep_expired_clears_and_emits(self):
        tree = StatusTree(pin_store=_RecordingStore())
        tree.upsert("/db", StatusCode.OK)
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now(UTC) - timedelta(minutes=1))
        self.assertEqual(tree.effective("/db"), StatusCode.MAINTENANCE)
        self.assertEqual(tree.sweep_expired(), ["/db"])
        self.assertEqual(tree.effective("/db"), StatusCode.OK)
        last = tree.recent_events()[-1]
        self.assertEqual((last.path, last.old, last.new, last.cause),
                         ("/db", StatusCode.MAINTENANCE, StatusCode.OK,
                          "pin-ended"))

    def test_reap_drops_uncovered_keeps_covered(self):
        tree = StatusTree(pin_store=_RecordingStore())
        far = datetime.now(UTC) + timedelta(days=1)
        tree.set_maintenance("/payments", "release", expires_at=far)   # a subsystem
        tree.set_maintenance("/gone/node", "stale", expires_at=far)    # an orphan
        # a check root beneath `payments` covers it; nothing covers `gone.node`
        self.assertEqual(tree.reap_uncovered(["/payments/api", "/system/alpha"]),
                         ["/gone/node"])
        # a startup reaps before any check has run: the pins are held against
        # their paths, and no node stands at either (ADR-0109 decision 4)
        self.assertIsNotNone(tree.maintenance_entry("/payments"))
        self.assertIsNone(tree.maintenance_entry("/gone/node"))
        self.assertIsNone(tree.snapshot("/gone"))
        last = tree.recent_events()[-1]
        self.assertEqual((last.path, last.old, last.new, last.cause),
                         ("/gone/node", StatusCode.MAINTENANCE,
                          StatusCode.UNDEFINED, "pin-ended"))
        # and the one that is covered silences its node from the first reading
        tree.upsert("/payments/api", StatusCode.ERROR, "down")
        self.assertEqual(tree.effective("/payments"), StatusCode.MAINTENANCE)


class MaintenanceEditTests(TestCase):
    """Editing a pin in place, and the compare-and-set guard that keeps two admins
    from silently overwriting one another (ADR-0014)."""

    def setUp(self):
        self.tree = StatusTree(pin_store=_RecordingStore())
        self.far = datetime.now(UTC) + timedelta(days=1)

    def _pin(self, note="planned", by="ada", expires_at=None, token=None):
        return self.tree.set_maintenance(
            "/db", note, expires_at=expires_at or self.far, set_by=by,
            expected_set_at=token)

    # ----- the read -----

    def test_a_pin_is_read_at_the_path_it_was_written_to_however_it_is_spelled(self):
        # the write, the clear and the per-entry read all take a path with or
        # without its leading slash; the read of a node's pin took only the
        # absolute one, so a form that posts the route's `branch` found nothing
        entry = self._pin().current
        assert entry is not None
        for spelled in ("/db", "db", "db/", "//db"):
            with self.subTest(path=spelled):
                self.assertEqual(self.tree.maintenance_entry(spelled), entry)
        self.assertIsNone(self.tree.maintenance_entry("d"))
        self.assertIsNone(self.tree.maintenance_entry("/db/x"))

    # ----- both dates -----

    def test_a_fresh_pin_creates_and_sets_at_the_same_moment(self):
        entry = self._pin().current
        assert entry is not None
        self.assertEqual(entry.created_at, entry.set_at)
        self.assertEqual(entry.created_by, "ada")
        self.assertEqual(entry.set_by, "ada")

    def test_an_edit_keeps_the_creation_and_moves_the_set(self):
        first = self._pin(by="ada").current
        assert first is not None
        second = self._pin("planned, extended", by="ben",
                           token=first.token).current
        assert second is not None
        self.assertEqual(second.created_at, first.created_at)
        self.assertEqual(second.created_by, "ada")     # who pinned it
        self.assertEqual(second.set_by, "ben")         # who last touched it
        self.assertNotEqual(second.set_at, first.set_at)

    def test_clear_and_repin_starts_a_new_creation(self):
        first = self._pin(by="ada").current
        assert first is not None
        self.tree.clear_maintenance("/db", expected_set_at=first.token)
        again = self._pin(by="ben", token="").current
        assert again is not None
        self.assertEqual(again.created_by, "ben")
        self.assertEqual(again.created_at, again.set_at)

    # ----- the compare-and-set guard -----

    def test_a_stale_token_writes_nothing(self):
        first = self._pin("ada's words", by="ada").current
        assert first is not None
        self._pin("ben's words", by="ben", token=first.token)
        # carla still holds the token she was served before ben wrote
        refused = self._pin("carla's words", by="carla", token=first.token)
        self.assertFalse(refused.applied)
        self.assertTrue(refused.refused)
        assert refused.current is not None
        self.assertEqual(refused.current.note, "ben's words")
        self.assertEqual(refused.current.set_by, "ben")
        # nothing was written: the stored pin is untouched
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.note, "ben's words")

    def test_believing_nothing_is_pinned_when_something_is_is_refused(self):
        self._pin(by="ada")
        refused = self._pin("mine", by="ben", token="")
        self.assertTrue(refused.refused)
        assert refused.current is not None
        self.assertEqual(refused.current.set_by, "ada")

    def test_believing_a_pin_exists_when_it_is_gone_is_refused(self):
        first = self._pin(by="ada").current
        assert first is not None
        self.tree.clear_maintenance("/db")
        refused = self._pin("mine", by="ben", token=first.token)
        self.assertTrue(refused.refused)
        self.assertIsNone(refused.current)      # nothing to reckon with

    def test_clearing_carries_the_same_guard(self):
        first = self._pin(by="ada").current
        assert first is not None
        self._pin("ben's words", by="ben", token=first.token)
        refused = self.tree.clear_maintenance("/db",
                                              expected_set_at=first.token)
        self.assertTrue(refused.refused)
        # with the fresh token it goes through
        current = self.tree.maintenance_entry("/db")
        assert current is not None
        self.assertEqual(current.note, "ben's words")
        ok = self.tree.clear_maintenance("/db", expected_set_at=current.token)
        self.assertTrue(ok.applied)
        self.assertIsNone(self.tree.maintenance_entry("/db"))

    def test_clearing_nothing_is_not_a_conflict(self):
        # the belief ("nothing is pinned") is correct, so there is no one to
        # reckon with — it simply changed nothing
        write = self.tree.clear_maintenance("/db", expected_set_at="")
        self.assertFalse(write.applied)
        self.assertFalse(write.refused)

    def test_an_absent_token_writes_unguarded(self):
        self._pin("ada's words", by="ada")
        write = self._pin("ben's words", by="ben")     # expected_set_at=None
        self.assertTrue(write.applied)
        assert write.current is not None
        self.assertEqual(write.current.note, "ben's words")

    # ----- the edit event -----

    def _maintenance_events(self):
        return [e for e in self.tree.recent_events() if e.path == "/db"]

    def test_a_real_edit_emits_an_event(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        self._pin("planned, one more day", by="ben", token=first.token)
        events = self._maintenance_events()
        self.assertEqual(len(events), 2)
        # MAINTENANCE -> MAINTENANCE: the code cannot tell, the entry can
        self.assertEqual(events[-1].old, StatusCode.MAINTENANCE)
        self.assertEqual(events[-1].new, StatusCode.MAINTENANCE)
        self.assertEqual(events[-1].reason, ("planned, one more day",))

    def test_extending_the_window_alone_emits_an_event(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        self._pin("planned", by="ada", token=first.token,
                  expires_at=self.far + timedelta(days=1))
        self.assertEqual(len(self._maintenance_events()), 2)

    def test_a_no_op_resubmit_emits_nothing(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        self._pin("planned", by="ada", token=first.token,
                  expires_at=first.expires_at)
        self.assertEqual(len(self._maintenance_events()), 1)

    # ----- a save that changes nothing -----

    def _same_again(self, first, by="ben", token=None):
        """The pin as it stands, set once more: the same note, the same expiry."""
        return self._pin(first.note, by=by, token=token,
                         expires_at=first.expires_at)

    def test_a_save_that_changes_nothing_writes_nothing(self):
        # the pin keeps its token, so another open editor of it is not made stale,
        # and it stays its last author's: nobody changed it (ADR-0104 decision 5)
        first = self._pin("planned", by="ada").current
        assert first is not None
        store = self.tree._pin_store
        saves = store.saves
        write = self._same_again(first, by="ben", token=first.token)
        self.assertFalse(write.refused)         # nobody to reckon with
        self.assertFalse(write.applied)         # and the table did not change
        self.assertEqual(write.current, first)
        self.assertEqual(self.tree.maintenance_entry("/db"), first)
        self.assertEqual(store.saves, saves)    # nor was the file written

    def test_an_unguarded_save_that_changes_nothing_writes_nothing_either(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        saves = self.tree._pin_store.saves
        write = self._same_again(first, by="ben")       # expected_set_at=None
        self.assertFalse(write.applied)
        self.assertEqual(self.tree.maintenance_entry("/db"), first)
        self.assertEqual(self.tree._pin_store.saves, saves)

    def test_the_token_decides_before_anything_is_compared(self):
        # a stale form is refused even where its fields say what is stored now:
        # the token names a pin, and that pin has been written over since
        first = self._pin("planned", by="ada").current
        assert first is not None
        moved = self._pin("moved", by="ben", token=first.token).current
        assert moved is not None
        back = self._same_again(first, by="ben", token=moved.token).current
        assert back is not None
        self.assertTrue(back.same_pin_as(first))
        stale = self._same_again(first, by="carla", token=first.token)
        self.assertTrue(stale.refused)
        self.assertEqual(stale.current, back)

    def test_a_changed_note_alone_and_a_changed_expiry_alone_are_writes(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        store = self.tree._pin_store
        saves = store.saves
        note = self._pin("planned, with a ticket", by="ben", token=first.token,
                         expires_at=first.expires_at)
        assert note.current is not None
        self.assertTrue(note.applied)
        self.assertNotEqual(note.current.set_at, first.set_at)
        self.assertEqual(note.current.set_by, "ben")
        self.assertEqual(store.saves, saves + 1)
        window = self._pin("planned, with a ticket", by="carla",
                           token=note.current.token,
                           expires_at=self.far + timedelta(minutes=1))
        assert window.current is not None
        self.assertTrue(window.applied)
        self.assertNotEqual(window.current.set_at, note.current.set_at)
        self.assertEqual(window.current.set_by, "carla")
        self.assertEqual(store.saves, saves + 2)


class EntryMaintenanceTests(TestCase):
    """Per-entry pins and the virtual-children roll-up (ADR-0036, ADR-0032)."""

    def setUp(self):
        self.tree = StatusTree(pin_store=_RecordingStore())
        self.far = datetime.now(UTC) + timedelta(days=1)

    def _findings(self, *slugs):
        return {slug: f"finding {slug}" for slug in slugs}

    def _pin(self, slug, path="/wiz", note="working on it", token=None):
        return self.tree.set_entry_maintenance(
            path, slug, note, expires_at=self.far, set_by="ada",
            expected_set_at=token)

    def _snap(self, path="/wiz", now=None):
        snap = self.tree.snapshot(path, now=now)
        assert snap is not None
        return snap

    # ----- the point of the whole feature -----

    def test_pinning_one_finding_leaves_the_others_alarming(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b", "c"))
        self._pin("b")
        snap = self._snap()
        self.assertEqual(snap.own_code, StatusCode.ERROR)     # nineteen others
        self.assertEqual(snap.quiet_reasons, 1)
        quiet = [line.slug for line in snap.reasons if line.quiet]
        self.assertEqual(quiet, ["b"])

    def test_a_node_whose_members_are_all_pinned_reads_maintenance(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b"))
        self._pin("a")
        self._pin("b")
        snap = self._snap()
        self.assertEqual(snap.own_code, StatusCode.MAINTENANCE)
        self.assertEqual(snap.code, StatusCode.MAINTENANCE)
        self.assertFalse(snap.maintenance)      # no *node* pin was ever set

    def test_a_fully_pinned_node_contributes_nothing_to_its_parent(self):
        self.tree.upsert("/site/wiz", StatusCode.ERROR, self._findings("a"))
        self.tree.upsert("/site/disk", StatusCode.OK)
        self._pin("a", path="/site/wiz")
        self.assertEqual(self.tree.snapshot("/site").code, StatusCode.OK)

    # ----- prose is the default -----

    def test_prose_is_not_individually_suppressible(self):
        # a failing check's `check error:` line and its stack trace are one
        # condition in several paragraphs
        self.tree.upsert("/db", StatusCode.ERROR,
                         ["check error: boom", "Traceback…"])
        slug = self._snap("/db").reasons[0].slug
        self._pin(slug, path="/db")            # the side-table accepts it…
        snap = self._snap("/db")
        self.assertEqual(snap.own_code, StatusCode.ERROR)   # …the join ignores it
        self.assertEqual(snap.quiet_reasons, 0)

    def test_a_node_with_no_reasons_is_outside_the_rule(self):
        self.tree.upsert("/db", StatusCode.OK)
        self.assertEqual(self._snap("/db").own_code, StatusCode.OK)

    # ----- absence suspends, only expiry disposes -----

    def test_a_slug_the_run_did_not_report_simply_does_not_apply(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b"))
        self._pin("a")
        # the finding is fixed and vanishes from the next run
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("b"))
        snap = self._snap()
        self.assertEqual(snap.quiet_reasons, 0)
        self.assertEqual(snap.own_code, StatusCode.ERROR)
        # but the pin is still there, so it applies again if the finding returns
        self.assertIsNotNone(self.tree.entry_maintenance("/wiz", "a"))
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b"))
        self.assertEqual(self._snap().quiet_reasons, 1)

    def test_a_failing_check_does_not_throw_away_every_pin(self):
        # the whole reason absence suspends rather than deletes: one bad minute
        # replaces the map with `check error: …`
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b"))
        self._pin("a")
        self._pin("b")
        self.tree.upsert("/wiz", StatusCode.ERROR, ["check error: unreachable"])
        self.assertEqual(self._snap().own_code, StatusCode.ERROR)
        self.assertEqual(len(self.tree.entry_maintenance_at("/wiz")), 2)

    def test_expiry_disposes_of_an_entry_pin(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        self.tree.set_entry_maintenance(
            "/wiz", "a", "brief", expires_at=datetime.now(UTC) - timedelta(seconds=1))
        self.assertEqual(self._snap().quiet_reasons, 1)
        self.tree.sweep_expired()
        self.assertIsNone(self.tree.entry_maintenance("/wiz", "a"))
        self.assertEqual(self._snap().own_code, StatusCode.ERROR)

    def test_reap_drops_entry_pins_no_check_covers(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        self._pin("a")
        self._pin("x", path="/gone")
        self.tree.reap_uncovered(["/wiz"])
        self.assertIsNotNone(self.tree.entry_maintenance("/wiz", "a"))
        self.assertIsNone(self.tree.entry_maintenance("/gone", "x"))

    # ----- liveness is not switched off -----

    def test_a_dead_check_escalates_even_when_every_entry_is_pinned(self):
        # otherwise the suppression meant to quiet a known state silently covers
        # a check that stopped running (ADR-0032 rule 6, ADR-0036 decision 9)
        self.tree.upsert("/wiz", StatusCode.OK, self._findings("a"),
                         frequency_seconds=60)
        self._pin("a")
        later = datetime.now(UTC) + timedelta(hours=1)
        snap = self._snap(now=later)
        self.assertTrue(snap.stale)
        self.assertEqual(snap.own_code, StatusCode.MAINTENANCE)  # nothing reports
        self.assertEqual(snap.code, StatusCode.WARN)             # but it escalates

    def test_a_pinned_entry_does_not_exempt_the_node_from_staleness(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b"),
                         frequency_seconds=60)
        self._pin("a")
        self.assertTrue(self._snap(now=datetime.now(UTC) + timedelta(hours=1)).stale)

    # ----- the guard, one key deeper -----

    def test_an_entry_pin_carries_the_compare_and_set_token(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        first = self._pin("a").current
        assert first is not None
        self._pin("a", note="ben's turn", token=first.token)
        refused = self._pin("a", note="mine", token=first.token)
        self.assertTrue(refused.refused)
        assert refused.current is not None
        self.assertEqual(refused.current.note, "ben's turn")

    def test_an_entry_save_that_changes_nothing_writes_nothing(self):
        # the same rule one key deeper (ADR-0104 decision 5): the same note and
        # the same expiry leave the pin, its token and the file as they were
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b"))
        first = self._pin("a").current
        other = self._pin("b").current
        assert first is not None and other is not None
        store = self.tree._pin_store
        saves = store.saves
        again = self._pin("a", token=first.token)
        self.assertFalse(again.refused)
        self.assertFalse(again.applied)
        self.assertEqual(again.current, first)
        self.assertEqual(self.tree.entry_maintenance("/wiz", "a"), first)
        self.assertEqual(store.saves, saves)
        # a changed note is a write, and it is this line's alone
        edited = self._pin("a", note="waiting on a review", token=first.token)
        assert edited.current is not None
        self.assertTrue(edited.applied)
        self.assertNotEqual(edited.current.set_at, first.set_at)
        self.assertEqual(store.saves, saves + 1)
        self.assertEqual(self.tree.entry_maintenance("/wiz", "b"), other)
        # and the token decides first here too: a stale form is refused even
        # where it says what is stored now
        stale = self._pin("a", note="waiting on a review", token=first.token)
        self.assertTrue(stale.refused)
        self.assertEqual(stale.current, edited.current)
        self.assertEqual(store.saves, saves + 1)

    def test_clearing_an_entry_pin(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        entry = self._pin("a").current
        assert entry is not None
        self.assertTrue(
            self.tree.clear_entry_maintenance(
                "/wiz", "a", expected_set_at=entry.token).applied)
        self.assertEqual(self._snap().quiet_reasons, 0)

    def test_an_entry_pin_writes_no_status_and_its_event_is_what_the_node_shows(self):
        # the pin was never in the tree, and the node's own code is derived
        # (ADR-0032 rule 3). What is recorded is the change of what the node
        # shows, as a node's own pin records one (ADR-0107 decision 1)
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        before = len(self.tree.recent_events())
        self._pin("a")
        event, = self.tree.recent_events()[before:]
        self.assertEqual((event.old, event.new),
                         (StatusCode.ERROR, StatusCode.MAINTENANCE))
        # "nothing was written" is now a statement about `reported_code` — the
        # check's own answer, untouched. `effective` reads what the node *shows*,
        # and with its one member pinned there is nothing left reporting.
        snap = self.tree.snapshot("/wiz")
        assert snap is not None
        self.assertEqual(snap.reported_code, StatusCode.ERROR)
        self.assertEqual(snap.own_code, StatusCode.MAINTENANCE)

    def test_entry_pins_are_written_through(self):
        store = self.tree._pin_store
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        self._pin("a")
        self.assertIn(("/wiz", "a"), store.saved_entries)

    def test_restore_replays_entry_pins_without_touching_the_tree(self):
        tree = StatusTree()
        live = Pin(MAINTENANCE, "working on it", datetime.now(UTC),
                                datetime.now(UTC) + timedelta(days=1))
        dead = Pin(MAINTENANCE, "stale", datetime.now(UTC),
                                datetime.now(UTC) - timedelta(days=1))
        tree.restore_maintenance({}, entry_pins={("/wiz", "a"): live,
                                                 ("/wiz", "b"): dead})
        self.assertIsNotNone(tree.entry_maintenance("/wiz", "a"))
        self.assertIsNone(tree.entry_maintenance("/wiz", "b"))
        self.assertIsNone(tree.snapshot("/wiz"))     # no node was created


if __name__ == '__main__':
    unittest.main()


class CodedEntryRollupTests(TestCase):
    """Coded entries (ADR-0042): the virtual-children roll-up, made literal.

    The stored code is what the engine derived at the seam and passed in; what
    these tests exercise is the snapshot's *own* derivation over the lines —
    pins applied, each unsuppressed line contributing its own code where it has
    one and the reported code where it does not."""

    def setUp(self):
        self.tree = StatusTree(pin_store=_RecordingStore())
        self.far = datetime.now(UTC) + timedelta(days=1)

    def _jobs(self, **codes):
        return [Entry(slug, f"job {slug}", code) for slug, code in codes.items()]

    def _pin(self, slug, path="/ci/actions"):
        return self.tree.set_entry_maintenance(
            path, slug, "rerunning", expires_at=self.far, set_by="ada",
            expected_set_at=None)

    def _snap(self, path="/ci/actions"):
        snap = self.tree.snapshot(path)
        assert snap is not None
        return snap

    def test_the_lines_carry_their_codes_into_the_snapshot(self):
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         self._jobs(build=StatusCode.ERROR, test=StatusCode.OK))
        snap = self._snap()
        self.assertEqual({line.slug: line.code for line in snap.reasons},
                         {"build": StatusCode.ERROR, "test": StatusCode.OK})
        self.assertEqual(snap.own_code, StatusCode.ERROR)

    def test_pinning_the_one_red_line_turns_the_node_ok(self):
        # the point of the feature: silence the failing finding and the node
        # reads the worst of what is left — here, the healthy remainder
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         self._jobs(build=StatusCode.ERROR, test=StatusCode.OK,
                                    deploy=StatusCode.OK))
        self._pin("build")
        snap = self._snap()
        self.assertEqual(snap.own_code, StatusCode.OK)
        self.assertEqual(snap.code, StatusCode.OK)
        self.assertEqual(snap.reported_code, StatusCode.ERROR)  # kept beside it

    def test_pinning_every_coded_line_reads_maintenance(self):
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         self._jobs(build=StatusCode.ERROR, test=StatusCode.OK))
        self._pin("build")
        self._pin("test")
        self.assertEqual(self._snap().own_code, StatusCode.MAINTENANCE)

    def test_an_undefined_line_is_ignored_when_siblings_report(self):
        self.tree.upsert("/ci/actions", StatusCode.OK,
                         self._jobs(new=StatusCode.UNDEFINED,
                                    test=StatusCode.OK))
        self.assertEqual(self._snap().own_code, StatusCode.OK)

    def test_an_uncoded_line_still_carries_the_reported_code(self):
        # mixed set: the uncoded line contributes the node's reported status,
        # which keeps every pre-ADR-0042 check bit-for-bit unchanged
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [Entry("ok-job", "passed", StatusCode.OK),
                          Entry("note", "advisory text")])
        self.assertEqual(self._snap().own_code, StatusCode.ERROR)
        self._pin("note")
        self.assertEqual(self._snap().own_code, StatusCode.OK)

    def test_running_travels_to_the_snapshot_and_stays_display(self):
        self.tree.upsert("/ci/actions", StatusCode.ERROR,
                         [Entry("build", "failed after 8m · #4216 running 2m",
                                StatusCode.ERROR, running=True),
                          Entry("test", "passed", StatusCode.OK)])
        snap = self._snap()
        running = {line.slug: line.running for line in snap.reasons}
        self.assertEqual(running, {"build": True, "test": False})
        # display only: the red line's rerun changes nothing about the roll-up
        self.assertEqual(snap.own_code, StatusCode.ERROR)


class FailingFirstTests(TestCase):
    """A box's lines in the order its budget shows them (ADR-0127 decision 6): the
    errors, then the warnings, then the rest, each group in the order the check wrote
    them, and a pinned line among the rest whatever its code."""

    def setUp(self):
        self.tree = StatusTree(pin_store=_RecordingStore())
        self.far = datetime.now(UTC) + timedelta(days=1)

    def _lines(self, path="/db"):
        snap = self.tree.snapshot(path)
        assert snap is not None
        return snap.reasons

    def test_errors_then_warnings_then_the_rest_each_in_the_checks_order(self):
        self.tree.upsert("/db", StatusCode.ERROR, [
            Entry("ok-1", "replica one in step", StatusCode.OK),
            Entry("warn-1", "replica two lagging", StatusCode.WARN),
            Entry("ok-2", "replica three in step", StatusCode.OK),
            Entry("error-1", "primary unreachable", StatusCode.ERROR),
            Entry("warn-2", "replica four lagging", StatusCode.WARN),
            Entry("error-2", "standby unreachable", StatusCode.ERROR),
            Entry("ok-3", "replica five in step", StatusCode.OK)], members=True)
        self.assertEqual([line.slug for line in failing_first(self._lines())],
                         ["error-1", "error-2", "warn-1", "warn-2",
                          "ok-1", "ok-2", "ok-3"])

    def test_a_pinned_line_counts_among_the_rest_whatever_its_code(self):
        # what a pin silences is not the reason for the box's color (ADR-0041)
        self.tree.upsert("/db", StatusCode.ERROR, [
            Entry("ok-1", "replica one in step", StatusCode.OK),
            Entry("error-1", "primary unreachable", StatusCode.ERROR),
            Entry("error-2", "standby unreachable", StatusCode.ERROR),
            Entry("ok-2", "replica two in step", StatusCode.OK)], members=True)
        self.tree.set_entry_maintenance("/db", "error-1", "being replaced",
                                        expires_at=self.far, set_by="ada",
                                        expected_set_at=None)
        self.assertEqual([line.slug for line in failing_first(self._lines())],
                         ["error-2", "ok-1", "error-1", "ok-2"])

    def test_a_line_with_no_code_of_its_own_is_the_rest(self):
        # a sentence without a code says nothing for itself (ADR-0042), whatever the
        # node reports, so it keeps its place among the rest
        self.tree.upsert("/db", StatusCode.ERROR, [
            Entry("note", "the failover is being rehearsed"),
            Entry("error-1", "primary unreachable", StatusCode.ERROR),
            Entry("unread", "replica three not polled", StatusCode.UNDEFINED)])
        self.assertEqual([line.slug for line in failing_first(self._lines())],
                         ["error-1", "note", "unread"])

    def test_nothing_failing_leaves_the_checks_order(self):
        self.tree.upsert("/db", StatusCode.OK, [
            Entry("b", "replica two in step", StatusCode.OK),
            Entry("a", "replica one in step", StatusCode.OK)])
        self.assertEqual([line.slug for line in failing_first(self._lines())],
                         ["b", "a"])
        self.assertEqual(failing_first(()), [])


class WhoseStatusTests(TestCase):
    """Whose a node's status is (ADR-0123): what the node counts for itself, whether
    what it shows comes from beneath it, and whether it counts what is beneath it
    at all — three derivations on the snapshot, each read against its sentence."""

    def setUp(self):
        self.tree = StatusTree(pin_store=_RecordingStore())
        self.far = datetime.now(UTC) + timedelta(days=1)
        self.later = datetime.now(UTC) + timedelta(seconds=200)

    def _snap(self, path, now=None):
        snap = self.tree.snapshot(path, now=now)
        assert snap is not None
        return snap

    def _whose(self, path, now=None):
        snap = self._snap(path, now)
        return snap.own_counted, snap.code, snap.derived

    def test_a_status_from_beneath_it_is_derived(self):
        # the node warns of its own and a node beneath it fails
        self.tree.upsert("/gw", StatusCode.WARN, "slow")
        self.tree.upsert("/gw/backend", StatusCode.ERROR, "down")
        self.assertEqual(self._whose("/gw"),
                         (StatusCode.WARN, StatusCode.ERROR, True))

    def test_a_failure_of_its_own_is_not_derived(self):
        # above a node that is well, and above one that fails too
        for beneath in (StatusCode.OK, StatusCode.ERROR):
            with self.subTest(beneath=beneath):
                self.tree.upsert("/gw", StatusCode.ERROR, "503")
                self.tree.upsert("/gw/backend", beneath, "its own line")
                self.assertEqual(self._whose("/gw"),
                                 (StatusCode.ERROR, StatusCode.ERROR, False))

    def test_a_node_with_nothing_beneath_it_is_never_derived(self):
        for code in (StatusCode.OK, StatusCode.WARN, StatusCode.ERROR,
                     StatusCode.UNDEFINED, StatusCode.MAINTENANCE):
            with self.subTest(code=code):
                self.tree.upsert("/leaf", code, "a line")
                self.assertEqual(self._whose("/leaf"), (code, code, False))
        self.tree.upsert("/pinned", StatusCode.ERROR, "boom")
        self.tree.set_maintenance("/pinned", "planned", expires_at=self.far)
        self.assertEqual(
            self._whose("/pinned"),
            (StatusCode.MAINTENANCE, StatusCode.MAINTENANCE, False))

    def test_a_node_that_declares_nothing_derives_whatever_it_shows(self):
        self.tree.upsert("/host/disk", StatusCode.OK)
        self.assertEqual(self._whose("/host"),
                         (StatusCode.UNDEFINED, StatusCode.OK, True))
        # with its one child silenced it shows maintenance, and that is the child's
        self.tree.set_maintenance("/host/disk", "swap", expires_at=self.far)
        self.assertEqual(self._whose("/host"),
                         (StatusCode.UNDEFINED, StatusCode.MAINTENANCE, True))

    def test_what_nothing_beneath_it_reports_is_its_own_undefined(self):
        # the roll-up of nothing is nothing: the word is the node's own again
        self.tree.upsert("/host/disk", StatusCode.UNDEFINED)
        self.assertEqual(self._whose("/host"),
                         (StatusCode.UNDEFINED, StatusCode.UNDEFINED, False))

    def test_a_stale_reading_of_its_own_counts_degraded_and_is_not_derived(self):
        # its check stopped, above a node that nothing ages: the warning is the
        # node's own (ADR-0005), though its own status still says ok
        self.tree.upsert("/gw", StatusCode.OK, "answers", frequency_seconds=60)
        self.tree.upsert("/gw/backend", StatusCode.OK)
        stale = self._snap("/gw", self.later)
        self.assertTrue(stale.own_stale)
        self.assertIs(stale.own_code, StatusCode.OK)
        self.assertEqual((stale.own_counted, stale.code, stale.derived),
                         (StatusCode.WARN, StatusCode.WARN, False))

    def test_a_stale_failure_of_its_own_is_never_softened(self):
        self.tree.upsert("/gw", StatusCode.ERROR, "503", frequency_seconds=60)
        self.tree.upsert("/gw/backend", StatusCode.OK)
        self.assertEqual(self._whose("/gw", self.later),
                         (StatusCode.ERROR, StatusCode.ERROR, False))

    def test_a_stale_node_beneath_it_is_what_it_derives(self):
        # the node is read on no schedule and cannot age; the one beneath it can
        self.tree.upsert("/gw", StatusCode.OK, "answers")
        self.tree.upsert("/gw/backend", StatusCode.OK, frequency_seconds=60)
        self.assertEqual(self._whose("/gw", self.later),
                         (StatusCode.OK, StatusCode.WARN, True))

    def test_it_is_what_the_roll_up_counts_for_the_node(self):
        # the sentence the property makes: what a node shows is the roll-up of
        # what it counts for itself and what each node beneath it hands up
        self.tree.upsert("/a", StatusCode.OK, "fine", frequency_seconds=60)
        self.tree.upsert("/a/b", StatusCode.WARN, "slow")
        self.tree.upsert("/a/b/c", StatusCode.ERROR, "down", frequency_seconds=60)
        self.tree.upsert("/a/d", StatusCode.OK)
        self.tree.upsert("/e/f", StatusCode.OK)
        self.tree.set_maintenance("/a/b/c", "planned", expires_at=self.far)
        for now in (None, self.later):
            pending = [self._snap("", now)]
            while pending:
                snap = pending.pop()
                pending.extend(snap.children)
                with self.subTest(path=snap.path, stale=now is not None):
                    self.assertIs(snap.code, effective_code(
                        snap.own_counted,
                        (child.counted for child in snap.children)))

    def test_a_node_counts_what_is_beneath_it(self):
        self.tree.upsert("/gw", StatusCode.OK, "answers")
        self.tree.upsert("/gw/backend", StatusCode.OK)
        self.tree.upsert("/host/disk", StatusCode.OK)
        self.assertTrue(self._snap("/gw").counts_beneath)
        # one that declares nothing counts nothing else
        self.assertTrue(self._snap("/host").counts_beneath)
        # and one with nothing beneath it has nothing to count
        self.assertFalse(self._snap("/gw/backend").counts_beneath)

    def test_a_node_in_maintenance_counts_nothing_beneath_it(self):
        # a pin on it, its check's own word, and lines that carry that word: each
        # cancels what is beneath it (ADR-0039 rule 3, ADR-0124 decision 1)
        self.tree.upsert("/gw", StatusCode.OK, "answers")
        self.tree.upsert("/gw/backend", StatusCode.ERROR, "down")
        self.tree.set_maintenance("/gw", "planned", expires_at=self.far)
        self.tree.upsert("/said", StatusCode.MAINTENANCE, "its own word")
        self.tree.upsert("/said/backend", StatusCode.ERROR, "down")
        self.tree.upsert("/carried", StatusCode.MAINTENANCE,
                         {"scope": "3 in scope", "region": "eu-central-1"})
        self.tree.upsert("/carried/backend", StatusCode.ERROR, "down")
        for path in ("/gw", "/said", "/carried"):
            with self.subTest(path=path):
                snap = self._snap(path)
                self.assertIs(snap.own_code, StatusCode.MAINTENANCE)
                self.assertIs(snap.code, StatusCode.MAINTENANCE)
                self.assertFalse(snap.counts_beneath)
                self.assertFalse(snap.lines_silenced)
                self.assertFalse(snap.derived)

    def test_a_node_whose_lines_are_all_silenced_counts_what_is_beneath_it(self):
        # its lines are its children too: silenced, they count nothing and cancel
        # nothing, and the nodes beneath it count (ADR-0124 decision 1)
        self.tree.upsert("/lines", StatusCode.OK,
                         [Entry("scope", "3 in scope", StatusCode.OK),
                          Entry("region", "eu-west-3 cannot be read", StatusCode.WARN)])
        self.tree.upsert("/lines/backend", StatusCode.ERROR, "down")
        for slug in ("scope", "region"):
            self.tree.set_entry_maintenance(
                "/lines", slug, "quiet", expires_at=self.far, set_by="ada",
                expected_set_at=None)
        snap = self._snap("/lines")
        self.assertEqual((snap.own_code, snap.own_counted, snap.code),
                         (StatusCode.MAINTENANCE, StatusCode.MAINTENANCE,
                          StatusCode.ERROR))
        self.assertTrue(snap.counts_beneath)
        self.assertTrue(snap.lines_silenced)
        self.assertTrue(snap.derived)
        self.assertIs(self.tree.effective("/"), StatusCode.ERROR)

    def test_lines_all_silenced_over_nothing_counted_read_maintenance(self):
        # the node reads `MAINTENANCE` whole only where nothing beneath it counts
        # either: beneath a node not reported yet, and with nothing beneath it at all
        # (ADR-0039 rule 5)
        self.tree.upsert("/waits", StatusCode.OK,
                         [Entry("scope", "1 in scope", StatusCode.OK)])
        self.tree.upsert("/waits/backend", StatusCode.UNDEFINED)
        self.tree.upsert("/leaf", StatusCode.OK,
                         [Entry("scope", "1 in scope", StatusCode.OK)])
        for path in ("/waits", "/leaf"):
            self.tree.set_entry_maintenance(
                path, "scope", "quiet", expires_at=self.far, set_by="ada",
                expected_set_at=None)
        for path, beneath in (("/waits", True), ("/leaf", False)):
            with self.subTest(path=path):
                snap = self._snap(path)
                self.assertIs(snap.code, StatusCode.MAINTENANCE)
                self.assertIs(snap.counts_beneath, beneath)
                self.assertFalse(snap.derived)

    def test_a_pinned_node_whose_own_reading_went_stale_counts_what_is_beneath_it(
            self):
        # staleness is not silenced (ADR-0041 decision 5): the node counts its
        # reading degraded, which cancels nothing, and its period is named its own
        self.tree.upsert("/gw", StatusCode.ERROR, "503", frequency_seconds=60)
        self.tree.upsert("/gw/backend", StatusCode.OK)
        self.tree.set_maintenance("/gw", "planned", expires_at=self.far)
        snap = self._snap("/gw", self.later)
        self.assertTrue(snap.own_stale)
        self.assertEqual((snap.own_code, snap.own_counted, snap.code),
                         (StatusCode.MAINTENANCE, StatusCode.ERROR, StatusCode.ERROR))
        self.assertTrue(snap.counts_beneath)
        self.assertFalse(snap.lines_silenced)


class AdoptedEventLogTests(TestCase):
    """ADR-0077: the log's ``restore`` direction takes the file's payload."""

    def test_adopt_events_puts_the_payload_in_place_of_the_log(self):
        written = StatusTree()
        written.upsert("/x", StatusCode.OK)
        written.upsert("/x", StatusCode.ERROR, "down")
        running = StatusTree()
        running.upsert("/y", StatusCode.OK)
        running.adopt_events(written.events_payload())
        self.assertEqual([(event.path, event.new) for event in running.recent_events()],
                         [("/x", StatusCode.OK), ("/x", StatusCode.ERROR)])

    def test_a_payload_of_another_shape_raises_and_leaves_the_log_alone(self):
        running = StatusTree()
        running.upsert("/y", StatusCode.OK)
        with self.assertRaises(ValueError):
            running.adopt_events({"events": [{"old": "OK", "new": "NOPE"}]})
        self.assertEqual([event.path for event in running.recent_events()], ["/y"])


class EventLogAsAStateFileTests(TestCase):
    """The event log survives a restart as a state file (ADR-0071): the payload the
    layer keeps, and the restore that puts it back before anything has written."""

    def test_an_event_round_trips_through_its_dict(self):
        event = Event(path="/db", name="db", old=StatusCode.OK,
                      new=StatusCode.ERROR, reason=("down", "for real"),
                      timestamp=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
                      suppressed_by="maintenance")
        self.assertEqual(Event.from_dict(event.to_dict()), event)
        # codes travel by name, so the file reads without this module
        self.assertEqual(event.to_dict()["new"], "ERROR")

    def test_the_payload_is_the_log_oldest_first(self):
        tree = StatusTree()
        tree.upsert("/a", StatusCode.OK)
        tree.upsert("/a", StatusCode.ERROR, "down")
        payload = tree.events_payload()
        self.assertEqual([raw["new"] for raw in payload["events"]],
                         ["OK", "ERROR"])
        self.assertEqual(payload["events"][1]["reason"], ["down"])

    def test_restore_puts_yesterdays_events_back_and_keeps_the_bound(self):
        from little_sister.tree import events_from_payload
        written = StatusTree()
        for code in (StatusCode.OK, StatusCode.ERROR, StatusCode.OK):
            written.upsert("/a", code)
        restarted = StatusTree(event_log_size=2)
        kept = restarted.restore_events(events_from_payload(written.events_payload()))
        self.assertEqual(kept, 2)
        self.assertEqual([event.new for event in restarted.recent_events()],
                         [StatusCode.ERROR, StatusCode.OK])
        # nodes are untouched: nothing has reported yet
        self.assertIsNone(restarted.snapshot("/a"))

    def test_history_reads_the_restored_log_once_the_node_is_written_again(self):
        written = StatusTree()
        written.upsert("/a", StatusCode.OK)
        written.upsert("/a", StatusCode.ERROR, "down")
        restarted = StatusTree()
        restarted.restore_events(written.recent_events())
        self.assertEqual(restarted.history("/a"), [])
        restarted.upsert("/a", StatusCode.OK)
        codes = [period.code for period in restarted.history("/a")]
        self.assertEqual(codes, [StatusCode.OK, StatusCode.ERROR, StatusCode.OK])

    def test_a_payload_of_another_shape_is_refused_whole(self):
        from little_sister.tree import events_from_payload
        for payload in ([], {"events": "no"}, {"events": [1]},
                        {"events": [{"old": "OK", "new": "NOPE"}]},
                        {"events": [{"old": "OK", "new": "OK", "reason": "x"}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                events_from_payload(payload)


class ContributionVocabularyTests(TestCase):
    """What each node contributes to the wall's tree (ADR-0127, backlog #91 §7.9):
    what a chip counts, what the healthy fold folds, and what a close's incident
    reads — one vocabulary beside ``own_counted``, so that the round on maintenance
    and aggregation changes them once."""

    def setUp(self):
        self.tree = StatusTree(pin_store=_RecordingStore())
        self.far = datetime.now(UTC) + timedelta(days=1)

    def _snap(self, path="", now=None):
        snap = self.tree.snapshot(path, now=now)
        assert snap is not None
        return snap

    def _aged(self, path, seconds=3600):
        self.tree.snapshot(path)
        self.tree._ensure_node(path).timestamp = (
            datetime.now(UTC) - timedelta(seconds=seconds))

    # --- what a node counts for itself ---

    def test_each_state_counts_as_its_own_word(self):
        self.tree.upsert("/a/error", StatusCode.ERROR, "x")
        self.tree.upsert("/a/warn", StatusCode.WARN, "x")
        self.tree.upsert("/a/ok", StatusCode.OK)
        self.tree.set_about("/a/idle", "declared, never reported")
        self.tree.upsert("/a/pinned", StatusCode.ERROR, "x")
        self.tree.set_maintenance("/a/pinned", "planned", expires_at=self.far,
                                  set_by="ada")
        said = {child.name: counts_as(child) for child in self._snap("/a").children}
        self.assertEqual(said, {"error": "error", "warn": "warn", "ok": "ok",
                                "idle": "idle", "pinned": "maintenance"})

    def test_a_stale_leaf_counts_as_the_warning_it_is_degraded_to(self):
        self.tree.upsert("/a/leaf", StatusCode.OK, frequency_seconds=60)
        self._aged("/a/leaf")
        leaf = self._snap("/a/leaf")
        self.assertTrue(leaf.stale)
        self.assertEqual(counts_as(leaf), "warn")
        self.assertTrue(failing(leaf))                    # drawn as that warning
        self.assertFalse(healthy(leaf))

    def test_a_line_counts_by_its_own_code_or_its_nodes_and_pinned_as_maintenance(self):
        self.tree.upsert("/db", StatusCode.WARN, [
            Entry("coded", "primary unreachable", StatusCode.ERROR),
            Entry("plain", "a note"),
            Entry("pinned", "standby unreachable", StatusCode.ERROR)], members=True)
        self.tree.set_entry_maintenance("/db", "pinned", "being replaced",
                                        expires_at=self.far, set_by="ada",
                                        expected_set_at=None)
        node = self._snap("/db")
        said = {line.slug: line_counts_as(node, line) for line in node.reasons}
        # the plain line takes the code its node rolls up to — error, by the coded
        # line beside it, not the warning the check reported for the node
        self.assertIs(node.code, StatusCode.ERROR)
        self.assertEqual(said, {"coded": "error", "plain": "error",
                                "pinned": "maintenance"})

    # --- failing, and healthy ---

    def test_failing_is_drawn_as_an_error_or_a_warning_whatever_the_pins_beneath(self):
        self.tree.upsert("/a/red", StatusCode.ERROR, "x")
        self.tree.upsert("/a/quiet", StatusCode.ERROR, "x")
        self.tree.set_maintenance("/a/quiet", "planned", expires_at=self.far,
                                  set_by="ada")
        self.tree.upsert("/b/fine", StatusCode.OK)
        self.assertTrue(failing(self._snap("/a")))         # red by /a/red
        self.assertTrue(failing(self._snap("/a/red")))
        self.assertFalse(failing(self._snap("/a/quiet")))  # blue, not red
        self.assertFalse(failing(self._snap("/b")))

    def test_healthy_is_ok_with_nothing_stale_and_no_pin_on_or_beneath(self):
        self.tree.upsert("/a/one", StatusCode.OK)
        self.tree.upsert("/a/two", StatusCode.OK)
        self.assertTrue(healthy(self._snap("/a")))
        self.assertTrue(healthy(self._snap("/a/one")))
        # a pin beneath withholds it, though the node still reads OK
        self.tree.upsert("/b/one", StatusCode.OK)
        self.tree.upsert("/b/two", StatusCode.OK)
        self.tree.set_maintenance("/b/two", "planned", expires_at=self.far,
                                  set_by="ada")
        branch = self._snap("/b")
        self.assertIs(branch.code, StatusCode.OK)
        self.assertTrue(pin_beneath(branch))
        self.assertFalse(healthy(branch))
        self.assertTrue(healthy(self._snap("/b/one")))
        # a pinned line beneath, too
        self.tree.upsert("/c/one", StatusCode.OK, [
            Entry("a", "in step", StatusCode.OK), Entry("b", "in step", StatusCode.OK)],
            members=True)
        self.tree.set_entry_maintenance("/c/one", "b", "rehearsal", expires_at=self.far,
                                        set_by="ada", expected_set_at=None)
        self.assertTrue(pin_beneath(self._snap("/c")))
        self.assertFalse(healthy(self._snap("/c")))
        self.assertFalse(healthy(self._snap("/c/one")))

    def test_a_stale_node_beneath_withholds_healthy_from_its_branch(self):
        self.tree.upsert("/a/one", StatusCode.OK, frequency_seconds=60)
        self.tree.upsert("/a/two", StatusCode.OK)
        self._aged("/a/one")
        self.assertFalse(healthy(self._snap("/a")))
        self.assertTrue(healthy(self._snap("/a/two")))

    def test_a_line_is_healthy_by_its_own_code_or_its_nodes_rolled_up_one(self):
        self.tree.upsert("/a/one", StatusCode.OK, [
            Entry("coded", "in step", StatusCode.OK),
            Entry("plain", "a note"),
            Entry("bad", "lagging", StatusCode.WARN)], members=True)
        node = self._snap("/a/one")
        said = {line.slug: line_healthy(node, line) for line in node.reasons}
        self.assertEqual(said, {"coded": True, "plain": False, "bad": False})
        # the plain line follows what its node rolls up to — `code`, never its
        # own reading — so a branch's own line stays while anything beneath fails
        self.tree.upsert("/b", StatusCode.OK, [Entry("own", "the branch's own line")])
        self.tree.upsert("/b/child", StatusCode.ERROR, "x")
        branch = self._snap("/b")
        self.assertIs(branch.own_code, StatusCode.OK)
        self.assertFalse(line_healthy(branch, branch.reasons[0]))
        self.tree.upsert("/b/child", StatusCode.OK)
        branch = self._snap("/b")
        self.assertTrue(line_healthy(branch, branch.reasons[0]))

    def test_a_pin_on_the_line_or_on_its_node_withholds_healthy(self):
        self.tree.upsert("/a/one", StatusCode.OK, [
            Entry("a", "in step", StatusCode.OK),
            Entry("b", "in step", StatusCode.OK)], members=True)
        self.tree.set_entry_maintenance("/a/one", "b", "rehearsal", expires_at=self.far,
                                        set_by="ada", expected_set_at=None)
        node = self._snap("/a/one")
        self.assertEqual({line.slug: line_healthy(node, line) for line in node.reasons},
                         {"a": True, "b": False})
        self.tree.upsert("/c/one", StatusCode.OK,
                         [Entry("a", "in step", StatusCode.OK)])
        self.tree.set_maintenance("/c/one", "planned", expires_at=self.far,
                                  set_by="ada")
        node = self._snap("/c/one")
        self.assertFalse(line_healthy(node, node.reasons[0]))

    # --- what the failure budget opens ---

    def test_a_failure_is_what_a_node_fails_with_for_itself(self):
        # a leaf by its reading, a stale one as the warning it counts as; a branch
        # by its own reading, whatever its children say
        self.tree.upsert("/a/error", StatusCode.ERROR, "x")
        self.tree.upsert("/a/warn", StatusCode.WARN, "x")
        self.tree.upsert("/a/ok", StatusCode.OK)
        self.tree.upsert("/a/late", StatusCode.OK, frequency_seconds=60)
        self._aged("/a/late")
        said = {child.name: own_failure(child) for child in self._snap("/a").children}
        self.assertEqual(said, {"error": "error", "warn": "warn", "ok": None,
                                "late": "warn"})
        self.assertIsNone(own_failure(self._snap("/a")))     # red only by its leaves
        self.tree.upsert("/repo", StatusCode.ERROR, "the webhook is gone")
        self.tree.upsert("/repo/build", StatusCode.OK)
        self.assertEqual(own_failure(self._snap("/repo")), "error")

    def test_a_damped_or_a_pinned_failure_spends_no_budget(self):
        self.tree.upsert("/svc/api", StatusCode.OK, escalate_after=3)
        self.tree.upsert("/svc/api", StatusCode.ERROR, "down")
        api = self._snap("/svc/api")
        self.assertIs(api.code, StatusCode.ERROR)            # red, and held back
        self.assertIsNotNone(api.damping)
        self.assertIsNone(own_failure(api))
        self.tree.upsert("/svc/api", StatusCode.ERROR, "down")
        self.tree.upsert("/svc/api", StatusCode.ERROR, "down")  # it escalates
        self.assertIsNone(self._snap("/svc/api").damping)
        self.assertEqual(own_failure(self._snap("/svc/api")), "error")
        self.tree.upsert("/b/quiet", StatusCode.ERROR, "x")
        self.tree.set_maintenance("/b/quiet", "planned", expires_at=self.far,
                                  set_by="ada")
        self.assertIsNone(own_failure(self._snap("/b/quiet")))

    # --- what a chip counts ---

    def test_a_branch_counts_each_leaf_beneath_once_by_what_it_counts_for_itself(self):
        self.tree.upsert("/a/x/error", StatusCode.ERROR, "x")
        self.tree.upsert("/a/x/warn", StatusCode.WARN, "x")
        self.tree.upsert("/a/y/ok1", StatusCode.OK)
        self.tree.upsert("/a/y/ok2", StatusCode.OK)
        self.tree.set_about("/a/y/idle", "declared, never reported")
        self.tree.upsert("/a/z", StatusCode.OK, frequency_seconds=60)
        self._aged("/a/z")                                 # a stale leaf: warn
        counts = chip_counts(self._snap("/a"))
        self.assertEqual(counts.counts, {"error": 1, "warn": 2, "maintenance": 0,
                                         "ok": 2, "idle": 1})
        self.assertEqual(counts.total, 6)
        self.assertEqual(counts.states, ("error", "warn", "ok", "idle"))
        self.assertTrue(counts.mixed)
        self.assertEqual(counts.handled, 0)
        self.assertEqual(counts.words, "1 error, 2 warnings, 2 ok, 1 idle")

    def test_a_branch_that_fails_for_itself_counts_once_the_chips_own_node_too(self):
        # a repository whose own reading failed above healthy workflows reads
        # ● 1 ✓ 2, where counting its leaves alone drew it red over nothing red
        self.tree.upsert("/repo", StatusCode.ERROR, "the webhook is gone")
        self.tree.upsert("/repo/build", StatusCode.OK)
        self.tree.upsert("/repo/test", StatusCode.OK)
        counts = chip_counts(self._snap("/repo"))
        self.assertEqual((counts.counts["error"], counts.counts["ok"]), (1, 2))
        self.assertEqual(counts.words, "1 error, 2 ok")
        # and a failing branch beneath the chip's node counts once as well
        self.tree.upsert("/team/repo", StatusCode.WARN, "rate limited")
        self.tree.upsert("/team/repo/build", StatusCode.OK)
        counts = chip_counts(self._snap("/team"))
        self.assertEqual((counts.counts["warn"], counts.counts["ok"]), (1, 1))
        # a healthy branch beneath counts nothing for itself
        self.tree.upsert("/calm/repo/build", StatusCode.OK)
        self.assertEqual(chip_counts(self._snap("/calm")).counts["ok"], 1)
        self.assertEqual(chip_counts(self._snap("/calm")).total, 1)

    def test_a_leafs_chip_counts_its_lines_and_a_line_of_one_shows_no_count(self):
        self.tree.upsert("/db", StatusCode.ERROR, [
            Entry("a", "primary unreachable", StatusCode.ERROR),
            Entry("b", "replica in step", StatusCode.OK),
            Entry("c", "replica in step", StatusCode.OK),
            Entry("d", "pinned", StatusCode.ERROR)], members=True)
        self.tree.set_entry_maintenance("/db", "d", "being replaced",
                                        expires_at=self.far, set_by="ada",
                                        expected_set_at=None)
        counts = chip_counts(self._snap("/db"))
        self.assertEqual(counts.counts, {"error": 1, "warn": 0, "maintenance": 1,
                                         "ok": 2, "idle": 0})
        self.assertTrue(counts.mixed)
        # the pinned line is ‖ among a leaf's own counts: nothing is handled out of
        # sight (ADR-0135 decision 6)
        self.assertEqual(counts.handled, 0)
        self.assertEqual(counts.words, "1 error, 1 in maintenance, 2 ok")
        # one line: the chip is that line
        self.tree.upsert("/one", StatusCode.WARN, "slow")
        counts = chip_counts(self._snap("/one"))
        self.assertEqual((counts.total, counts.mixed), (1, False))
        self.assertEqual(counts.words, "1 warning")
        # no lines at all: the leaf counts itself
        self.tree.upsert("/bare", StatusCode.OK)
        self.assertEqual(chip_counts(self._snap("/bare")).words, "1 ok")

    def test_one_state_is_one_total_and_what_is_handled_is_a_diamond_and_a_number(self):
        self.tree.upsert("/a/one", StatusCode.OK)
        self.tree.upsert("/a/two", StatusCode.OK)
        self.tree.upsert("/a/three", StatusCode.OK)
        counts = chip_counts(self._snap("/a"))
        self.assertEqual((counts.total, counts.mixed, counts.handled), (3, False, 0))
        self.assertEqual(counts.words, "3 ok")
        # a pinned leaf is ‖ among the counts, so nothing is handled out of sight
        self.tree.set_maintenance("/a/two", "planned", expires_at=self.far,
                                  set_by="ada")
        counts = chip_counts(self._snap("/a"))
        self.assertEqual(counts.handled, 0)
        self.assertEqual(counts.words, "1 in maintenance, 2 ok")
        # a pin on the chip's own node: the leaves still count as themselves, and the
        # diamond says the node the counts pass over (ADR-0135 decision 6)
        self.tree.set_maintenance("/a", "planned", expires_at=self.far, set_by="ada")
        counts = chip_counts(self._snap("/a"))
        self.assertEqual((counts.handled, counts.handled_by), (1, {"node": 1}))
        self.assertEqual(counts.handled_words, "1 handled: 1 node in maintenance")
        self.assertEqual(counts.words,
                         "1 in maintenance, 2 ok, 1 handled: 1 node in maintenance")
        bare = ChipCounts(counts=dict.fromkeys(COUNTED_STATES, 0),
                          handled_by={"line": 2})
        self.assertEqual(bare.words, "2 handled: 2 lines in maintenance")
        self.assertEqual(bare.states, ())

    def test_a_lines_pin_beneath_a_branch_is_handled_out_of_sight(self):
        # a leaf whose one failing line is pinned counts ok for itself: the chip
        # above it says the line is handled, beside the counts
        self.tree.upsert("/db/pool", StatusCode.ERROR, [
            Entry("a", "primary unreachable", StatusCode.ERROR),
            Entry("b", "replica in step", StatusCode.OK)], members=True)
        self.tree.set_entry_maintenance("/db/pool", "a", "being replaced",
                                        expires_at=self.far, set_by="ada",
                                        expected_set_at=None)
        self.tree.upsert("/db/cache", StatusCode.OK)
        counts = chip_counts(self._snap("/db"))
        self.assertEqual(counts.counts["ok"], 2)
        self.assertEqual(counts.handled_by, {"line": 1})
        self.assertEqual(counts.words, "2 ok, 1 handled: 1 line in maintenance")
        # a pinned branch beneath counts as one node, its lines' pins with it
        self.tree.upsert("/db/pool/extra", StatusCode.WARN, "lagging")
        self.tree.set_maintenance("/db/pool", "migration", expires_at=self.far,
                                  set_by="ada")
        counts = chip_counts(self._snap("/db"))
        self.assertEqual(counts.handled_by, {"node": 1})

    def test_damping_and_running_stand_in_the_words(self):
        self.tree.upsert("/svc/api", StatusCode.OK, escalate_after=3)
        self.tree.upsert("/svc/api", StatusCode.ERROR, "down")
        self.tree.upsert("/svc/api", StatusCode.ERROR, "down")
        self.tree.upsert("/ci/actions", StatusCode.ERROR, [
            Entry("build", "failed · #4216 running", StatusCode.ERROR, running=True),
            Entry("test", "passed", StatusCode.OK)])
        api = self._snap("/svc/api")
        self.assertIsNotNone(api.damping)
        self.assertEqual(chip_counts(api).words, "1 error, damped: 2 of 3 to escalate")
        self.assertEqual(chip_counts(self._snap("/svc")).words,
                         "1 error, damped: 2 of 3 to escalate")
        self.assertEqual(chip_counts(self._snap("/ci/actions")).words,
                         "1 error, 1 ok, 1 running")
        self.assertEqual(chip_counts(self._snap("/ci")).words,
                         "1 error, 1 running")        # the leaf, not its lines
