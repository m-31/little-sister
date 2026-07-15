import threading
import unittest
from datetime import datetime, timedelta
from unittest import TestCase

from little_sister.maintenance import MaintenanceEntry
from little_sister.status import StatusCode
from little_sister.tree import Event, StatusTree


class _RecordingStore:
    """A maintenance store that just remembers the last table saved (no file)."""

    def __init__(self) -> None:
        self.saved: dict[str, MaintenanceEntry] = {}

    def load(self) -> dict[str, MaintenanceEntry]:
        return {}

    def save(self, entries):
        self.saved = dict(entries)


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

    def test_maintenance_is_sticky(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now() + timedelta(days=7))
        self.assertEqual(tree.effective("/db"), StatusCode.MAINTENANCE)
        snap = tree.snapshot("/db")
        assert snap is not None
        self.assertTrue(snap.maintenance)
        self.assertEqual(snap.reason, ("planned",))
        # the engine's upsert must not override maintenance
        self.assertFalse(tree.upsert("/db", StatusCode.ERROR, "boom"))
        self.assertEqual(tree.effective("/db"), StatusCode.MAINTENANCE)
        # clearing reverts to UNDEFINED
        self.assertTrue(tree.clear_maintenance("/db"))
        self.assertEqual(tree.effective("/db"), StatusCode.UNDEFINED)
        after = tree.snapshot("/db")
        assert after is not None
        self.assertFalse(after.maintenance)

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


if __name__ == '__main__':
    unittest.main()
