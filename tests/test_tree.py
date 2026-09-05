import threading
import unittest
from datetime import datetime, timedelta
from typing import ClassVar
from unittest import TestCase

from little_sister.maintenance import MaintenanceEntry
from little_sister.reasons import Entry
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import Event, StatusTree


class _RecordingStore:
    """A maintenance store that just remembers the last table saved (no file)."""

    def __init__(self) -> None:
        self.saved: dict[str, MaintenanceEntry] = {}
        self.saved_entries: dict[tuple[str, str], MaintenanceEntry] = {}

    def load(self) -> dict[str, MaintenanceEntry]:
        return {}

    def load_entries(self) -> dict[tuple[str, str], MaintenanceEntry]:
        return {}

    def save(self, entries, entry_pins=None):
        self.saved = dict(entries)
        self.saved_entries = dict(entry_pins or {})


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
                             expires_at=datetime.now() + timedelta(days=1))
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
                             expires_at=datetime.now() + timedelta(days=7))
        snap = tree.snapshot("/db")
        assert snap is not None
        self.assertTrue(snap.maintenance)
        self.assertEqual(tree.effective("/db"), StatusCode.MAINTENANCE)
        self.assertEqual(snap.own_code, StatusCode.MAINTENANCE)  # what it shows
        self.assertEqual(snap.reported_code, StatusCode.OK)      # what the check said
        self.assertEqual(snap.reason, ("all good",))             # kept, not replaced
        entry = tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.reason, "planned")   # the pin's own text lives here

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
                             expires_at=datetime.now() + timedelta(days=7))
        fresh = tree.snapshot("/system/db")
        assert fresh is not None
        self.assertFalse(fresh.stale)
        # The pinned child contributes nothing, and it is the only one — so its
        # parent has nothing counted, and reads MAINTENANCE rather than UNDEFINED.
        # That was the open edge case ADR-0032 left for the ADR-0004
        # split; this line asserted UNDEFINED while it was open, and changed with it.
        self.assertEqual(tree.effective("/system"), StatusCode.MAINTENANCE)

        # nobody writes it again; the clock moves past two intervals
        later = datetime.now() + timedelta(seconds=200)
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
                             expires_at=datetime.now() + timedelta(days=7))
        later = datetime.now() + timedelta(seconds=200)
        parent = tree.snapshot("/system", now=later)
        assert parent is not None
        self.assertEqual(parent.code, StatusCode.ERROR)

    def test_a_check_reported_maintenance_is_exempt_from_staleness(self):
        # the guard that replaced the pin exemption is on the **code**, and it closes
        # a latent crash of its own: a check may report MAINTENANCE itself, and that
        # carries no severity for the stale degrade to take the worst of.
        tree = StatusTree()
        tree.upsert("/db", StatusCode.MAINTENANCE, frequency_seconds=60)
        later = datetime.now() + timedelta(seconds=200)
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
                             expires_at=datetime.now() + timedelta(days=7))
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
                             expires_at=datetime.now() + timedelta(days=7))
        tree.upsert("/db", StatusCode.ERROR, "disk full")
        broke = tree.recent_events()[-1]
        self.assertEqual((broke.old, broke.new), (StatusCode.OK, StatusCode.ERROR))
        self.assertEqual(broke.suppressed_by, "maintenance")

    def test_the_pin_and_its_release_are_never_marked(self):
        # they are what everybody saw; marking them would falsify the sentence
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, "boom")
        tree.set_maintenance("/db", "cutover",
                             expires_at=datetime.now() + timedelta(days=7))
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
                             expires_at=datetime.now() + timedelta(days=7))
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
                             expires_at=datetime.now() + timedelta(hours=2))
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
        future = datetime.now() + timedelta(hours=1)
        stale = tree.snapshot("/db", now=future)
        assert stale is not None
        self.assertTrue(stale.stale)
        self.assertEqual(stale.code, StatusCode.WARN)     # degraded
        self.assertEqual(stale.own_code, StatusCode.OK)   # raw code unchanged

    def test_stale_rolls_up(self):
        tree = StatusTree()
        tree.upsert("/svc/a", StatusCode.OK, frequency_seconds=60)
        svc = tree.snapshot("/svc", now=datetime.now() + timedelta(hours=1))
        assert svc is not None
        self.assertEqual(svc.code, StatusCode.WARN)
        self.assertTrue(svc.stale)

    def test_stale_does_not_downgrade_error(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, "boom", frequency_seconds=60)
        snap = tree.snapshot("/db", now=datetime.now() + timedelta(hours=1))
        assert snap is not None
        self.assertTrue(snap.stale)
        self.assertEqual(snap.code, StatusCode.ERROR)

    def test_maintenance_is_not_stale(self):
        tree = StatusTree()
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now() + timedelta(days=7))
        snap = tree.snapshot("/db", now=datetime.now() + timedelta(hours=1))
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
                                  now=datetime.now() + timedelta(hours=1))
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
                           next_run_at="2026-08-06T09:20:00")
        facts = self._run(tree, "/svc/github")
        assert facts is not None
        self.assertEqual(facts.wall_seconds, 1.25)
        self.assertEqual(facts.next_run_at, "2026-08-06T09:20:00")

    def test_unwritten_ancestors_inherit_the_facts_with_the_stamp(self):
        # Safe for the same reason the inherited stamp is: above a sole mount,
        # one check owns everything below, so the facts can only be that run's.
        tree = StatusTree()
        tree.set_check_mount("/svc/github")
        tree.upsert("/svc/github", StatusCode.OK)
        tree.set_run_facts("/svc/github", wall_seconds=0.5,
                           next_run_at="2026-08-06T09:20:00")
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
                           next_run_at="2026-08-06T09:20:00")
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
                           next_run_at="2026-08-06T09:20:00")
        self.assertIsNone(self._run(tree, "/system/node_a/metrics"))
        self.assertIsNone(self._run(tree, "/system/node_a"))
        self.assertIsNone(self._run(tree))

    def test_two_sole_mounts_keep_their_own_and_block_the_root(self):
        tree = StatusTree()
        for path, next_at in (("/a/check_1", "2026-08-06T09:20:00"),
                              ("/b/check_2", "2026-08-06T09:25:00")):
            tree.set_check_mount(path)
            tree.upsert(path, StatusCode.OK)
            tree.set_run_facts(path, wall_seconds=0.1, next_run_at=next_at)
        side_a = self._run(tree, "/a")
        side_b = self._run(tree, "/b")
        assert side_a is not None and side_b is not None
        self.assertEqual(side_a.next_run_at, "2026-08-06T09:20:00")
        self.assertEqual(side_b.next_run_at, "2026-08-06T09:25:00")
        self.assertIsNone(self._run(tree))

    def test_rewriting_replaces_the_facts(self):
        tree = StatusTree()
        tree.set_check_mount("/svc/github")
        tree.upsert("/svc/github", StatusCode.OK)
        tree.set_run_facts("/svc/github", wall_seconds=1.0,
                           next_run_at="2026-08-06T09:20:00")
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
                             expires_at=datetime.now() + timedelta(days=1),
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
    def _entry(self, expires_at, *, reason="planned", set_by="ada"):
        now = datetime.now().isoformat()
        return MaintenanceEntry(reason=reason, set_at=now,
                                expires_at=expires_at.isoformat(), set_by=set_by)

    def test_set_and_clear_write_through(self):
        store = _RecordingStore()
        tree = StatusTree(maintenance_store=store)
        tree.set_maintenance("/db", "planned", set_by="ada",
                             expires_at=datetime.now() + timedelta(days=1))
        self.assertEqual(set(store.saved), {"/db"})
        self.assertEqual(store.saved["/db"].set_by, "ada")
        snap = tree.snapshot("/db")
        assert snap is not None and snap.maintenance_entry is not None
        self.assertEqual(snap.maintenance_entry.reason, "planned")
        tree.clear_maintenance("/db")
        self.assertEqual(store.saved, {})

    def test_restore_replays_non_expired_and_drops_expired(self):
        store = _RecordingStore()
        tree = StatusTree(maintenance_store=store)
        now = datetime.now()
        entries = {
            "db": self._entry(now + timedelta(days=1)),
            "cache": self._entry(now - timedelta(days=1), reason="old"),
        }
        tree.restore_maintenance(entries, now=now)
        db = tree.snapshot("/db")
        assert db is not None
        self.assertTrue(db.maintenance)
        self.assertIsNone(tree.snapshot("/cache"))     # expired: no node created
        self.assertEqual(set(store.saved), {"/db"})     # file rewritten without it

    def test_adopt_replaces_the_table_in_a_running_process(self):
        """ADR-0077: the side-table's ``restore`` — what the new table lacks is
        cleared with a real transition, what it carries is applied, expired pins
        are dropped, per-entry pins are replaced whole, nothing is written."""
        store = _RecordingStore()
        tree = StatusTree(maintenance_store=store)
        now = datetime.now()
        tree.upsert("/db", StatusCode.OK)
        tree.upsert("/cache", StatusCode.OK)
        tree.set_maintenance("/db", "mine", expires_at=now + timedelta(days=1))
        tree.set_maintenance("/cache", "mine too", expires_at=now + timedelta(days=1))
        tree.set_entry_maintenance("/db", "slow", "old pin",
                                   expires_at=now + timedelta(days=1))
        written = dict(store.saved)
        adopted = {
            "/db": self._entry(now + timedelta(days=2), reason="theirs"),
            "/web": self._entry(now + timedelta(days=2), reason="new"),
            "/gone": self._entry(now - timedelta(days=1), reason="expired"),
        }
        entry_pins = {("/web", "a"): self._entry(now + timedelta(days=2)),
                      ("/web", "b"): self._entry(now - timedelta(days=1))}

        tree.adopt_maintenance(adopted, entry_pins=entry_pins, now=now)

        # /cache is cleared back to its reading, /db is edited, /web is pinned,
        # the expired /gone never lands
        self.assertEqual(tree.effective("/cache"), StatusCode.OK)
        self.assertIsNone(tree.maintenance_entry("/cache"))
        self.assertEqual(tree.maintenance_entry("/db").reason, "theirs")
        self.assertEqual(tree.effective("/web"), StatusCode.MAINTENANCE)
        self.assertIsNone(tree.snapshot("/gone"))
        self.assertEqual([(event.path, event.old, event.new)
                          for event in tree.recent_events()][-3:],
                         [("/cache", StatusCode.MAINTENANCE, StatusCode.OK),
                          ("/db", StatusCode.MAINTENANCE, StatusCode.MAINTENANCE),
                          ("/web", StatusCode.UNDEFINED, StatusCode.MAINTENANCE)])
        self.assertIsNone(tree.entry_maintenance("/db", "slow"))
        self.assertIsNotNone(tree.entry_maintenance("/web", "a"))
        self.assertIsNone(tree.entry_maintenance("/web", "b"))
        # nothing written through: the file on disk is the copy being adopted
        self.assertEqual(store.saved, written)

    def test_sweep_expired_clears_and_emits(self):
        tree = StatusTree(maintenance_store=_RecordingStore())
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now() - timedelta(minutes=1))
        self.assertEqual(tree.effective("/db"), StatusCode.MAINTENANCE)
        self.assertEqual(tree.sweep_expired(), ["/db"])
        self.assertEqual(tree.effective("/db"), StatusCode.UNDEFINED)
        self.assertTrue(any(e.path == "/db" and e.new == StatusCode.UNDEFINED
                            for e in tree.recent_events()))

    def test_reap_drops_uncovered_keeps_covered(self):
        tree = StatusTree(maintenance_store=_RecordingStore())
        far = datetime.now() + timedelta(days=1)
        tree.set_maintenance("/payments", "release", expires_at=far)   # a subsystem
        tree.set_maintenance("/gone/node", "stale", expires_at=far)    # an orphan
        # a check root beneath `payments` covers it; nothing covers `gone.node`
        self.assertEqual(tree.reap_uncovered(["/payments/api", "/system/alpha"]),
                         ["/gone/node"])
        self.assertEqual(tree.effective("/payments"), StatusCode.MAINTENANCE)
        self.assertEqual(tree.effective("/gone/node"), StatusCode.UNDEFINED)


class MaintenanceEditTests(TestCase):
    """Editing a pin in place, and the compare-and-set guard that keeps two admins
    from silently overwriting one another (ADR-0014)."""

    def setUp(self):
        self.tree = StatusTree(maintenance_store=_RecordingStore())
        self.far = datetime.now() + timedelta(days=1)

    def _pin(self, reason="planned", by="ada", expires_at=None, token=None):
        return self.tree.set_maintenance(
            "/db", reason, expires_at=expires_at or self.far, set_by=by,
            expected_set_at=token)

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
                           token=first.set_at).current
        assert second is not None
        self.assertEqual(second.created_at, first.created_at)
        self.assertEqual(second.created_by, "ada")     # who pinned it
        self.assertEqual(second.set_by, "ben")         # who last touched it
        self.assertNotEqual(second.set_at, first.set_at)

    def test_clear_and_repin_starts_a_new_creation(self):
        first = self._pin(by="ada").current
        assert first is not None
        self.tree.clear_maintenance("/db", expected_set_at=first.set_at)
        again = self._pin(by="ben", token="").current
        assert again is not None
        self.assertEqual(again.created_by, "ben")
        self.assertEqual(again.created_at, again.set_at)

    # ----- the compare-and-set guard -----

    def test_a_stale_token_writes_nothing(self):
        first = self._pin("ada's words", by="ada").current
        assert first is not None
        self._pin("ben's words", by="ben", token=first.set_at)
        # carla still holds the token she was served before ben wrote
        refused = self._pin("carla's words", by="carla", token=first.set_at)
        self.assertFalse(refused.applied)
        self.assertTrue(refused.refused)
        assert refused.current is not None
        self.assertEqual(refused.current.reason, "ben's words")
        self.assertEqual(refused.current.set_by, "ben")
        # nothing was written: the stored pin is untouched
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        self.assertEqual(entry.reason, "ben's words")

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
        refused = self._pin("mine", by="ben", token=first.set_at)
        self.assertTrue(refused.refused)
        self.assertIsNone(refused.current)      # nothing to reckon with

    def test_clearing_carries_the_same_guard(self):
        first = self._pin(by="ada").current
        assert first is not None
        self._pin("ben's words", by="ben", token=first.set_at)
        refused = self.tree.clear_maintenance("/db",
                                              expected_set_at=first.set_at)
        self.assertTrue(refused.refused)
        self.assertEqual(self.tree.effective("/db"), StatusCode.MAINTENANCE)
        # with the fresh token it goes through
        current = self.tree.maintenance_entry("/db")
        assert current is not None
        ok = self.tree.clear_maintenance("/db", expected_set_at=current.set_at)
        self.assertTrue(ok.applied)
        self.assertEqual(self.tree.effective("/db"), StatusCode.UNDEFINED)

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
        self.assertEqual(write.current.reason, "ben's words")

    # ----- the edit event -----

    def _maintenance_events(self):
        return [e for e in self.tree.recent_events() if e.path == "/db"]

    def test_a_real_edit_emits_an_event(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        self._pin("planned, one more day", by="ben", token=first.set_at)
        events = self._maintenance_events()
        self.assertEqual(len(events), 2)
        # MAINTENANCE -> MAINTENANCE: the code cannot tell, the entry can
        self.assertEqual(events[-1].old, StatusCode.MAINTENANCE)
        self.assertEqual(events[-1].new, StatusCode.MAINTENANCE)
        self.assertEqual(events[-1].reason, ("planned, one more day",))

    def test_extending_the_window_alone_emits_an_event(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        self._pin("planned", by="ada", token=first.set_at,
                  expires_at=self.far + timedelta(days=1))
        self.assertEqual(len(self._maintenance_events()), 2)

    def test_a_no_op_resubmit_emits_nothing(self):
        first = self._pin("planned", by="ada").current
        assert first is not None
        self._pin("planned", by="ada", token=first.set_at,
                  expires_at=datetime.fromisoformat(first.expires_at))
        self.assertEqual(len(self._maintenance_events()), 1)


class EntryMaintenanceTests(TestCase):
    """Per-entry pins and the virtual-children roll-up (ADR-0036, ADR-0032)."""

    def setUp(self):
        self.tree = StatusTree(maintenance_store=_RecordingStore())
        self.far = datetime.now() + timedelta(days=1)

    def _findings(self, *slugs):
        return {slug: f"finding {slug}" for slug in slugs}

    def _pin(self, slug, path="/wiz", reason="working on it", token=None):
        return self.tree.set_entry_maintenance(
            path, slug, reason, expires_at=self.far, set_by="ada",
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
            "/wiz", "a", "brief", expires_at=datetime.now() - timedelta(seconds=1))
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
        later = datetime.now() + timedelta(hours=1)
        snap = self._snap(now=later)
        self.assertTrue(snap.stale)
        self.assertEqual(snap.own_code, StatusCode.MAINTENANCE)  # nothing reports
        self.assertEqual(snap.code, StatusCode.WARN)             # but it escalates

    def test_a_pinned_entry_does_not_exempt_the_node_from_staleness(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a", "b"),
                         frequency_seconds=60)
        self._pin("a")
        self.assertTrue(self._snap(now=datetime.now() + timedelta(hours=1)).stale)

    # ----- the guard, one key deeper -----

    def test_an_entry_pin_carries_the_compare_and_set_token(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        first = self._pin("a").current
        assert first is not None
        self._pin("a", reason="ben's turn", token=first.set_at)
        refused = self._pin("a", reason="mine", token=first.set_at)
        self.assertTrue(refused.refused)
        assert refused.current is not None
        self.assertEqual(refused.current.reason, "ben's turn")

    def test_clearing_an_entry_pin(self):
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        entry = self._pin("a").current
        assert entry is not None
        self.assertTrue(
            self.tree.clear_entry_maintenance(
                "/wiz", "a", expected_set_at=entry.set_at).applied)
        self.assertEqual(self._snap().quiet_reasons, 0)

    def test_an_entry_pin_writes_no_status_and_emits_no_event(self):
        # the pin was never in the tree; the node's own code is derived at
        # snapshot time (ADR-0032 rule 3), so there is no transition to record
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        before = len(self.tree.recent_events())
        self._pin("a")
        self.assertEqual(len(self.tree.recent_events()), before)
        # "nothing was written" is now a statement about `reported_code` — the
        # check's own answer, untouched. `effective` reads what the node *shows*,
        # and with its one member pinned there is nothing left reporting.
        snap = self.tree.snapshot("/wiz")
        assert snap is not None
        self.assertEqual(snap.reported_code, StatusCode.ERROR)
        self.assertEqual(snap.own_code, StatusCode.MAINTENANCE)

    def test_entry_pins_are_written_through(self):
        store = self.tree._maintenance_store
        self.tree.upsert("/wiz", StatusCode.ERROR, self._findings("a"))
        self._pin("a")
        self.assertIn(("/wiz", "a"), store.saved_entries)

    def test_restore_replays_entry_pins_without_touching_the_tree(self):
        tree = StatusTree()
        live = MaintenanceEntry("working on it", datetime.now().isoformat(),
                                (datetime.now() + timedelta(days=1)).isoformat())
        dead = MaintenanceEntry("stale", datetime.now().isoformat(),
                                (datetime.now() - timedelta(days=1)).isoformat())
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
        self.tree = StatusTree(maintenance_store=_RecordingStore())
        self.far = datetime.now() + timedelta(days=1)

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
                      timestamp="2026-09-01T10:00:00", suppressed_by="maintenance")
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
