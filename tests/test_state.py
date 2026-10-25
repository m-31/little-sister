"""The state layer (ADR-0071): what a restart keeps, as files under ``var/state/``.

Tests are written from the claims in :mod:`little_sister.state` — the atomic
write, the two disciplines, a startup that never refuses, and the two lines the
heartbeat carries for a load that failed and a save that failed — and, at the
end, what was set aside by an adoption and the way back (ADR-0077): the ``.bak``
files listed beside the live copies, and *take the backups*.
"""
import gzip
import json
import os
import stat
import tempfile
import tracemalloc
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

from little_sister.codes import StatusCode
from little_sister.lease import Lease
from little_sister.reasons import Entry
from little_sister.state import BACKUP_SUFFIX, EVENTS_FILE, SERIES_FILE, StateLayer
from little_sister.status import HEARTBEAT_PATH
from tests.state_files import encoded, on_disk


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ReadingTests(TestCase):
    def test_a_missing_file_is_none_and_no_failure(self):
        # A first start, or a state never written: nothing to report.
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            self.assertIsNone(state.read("nope.json"))
            self.assertEqual(state.lines(), ())

    def test_a_readable_file_comes_back_parsed(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path("a.json").write_text(json.dumps({"k": [1, 2]}))
            self.assertEqual(state.read("a.json"), {"k": [1, 2]})

    def test_a_file_that_is_not_json_is_a_load_failure_that_stands(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path("a.json").write_text("{half a file")
            with self.assertLogs(level="ERROR") as captured:
                self.assertIsNone(state.read("a.json"))
            self.assertTrue(any("could not be loaded at startup" in line
                                for line in captured.output))
            (line,) = state.lines()
            self.assertEqual(line.slug, "load.a.json")
            self.assertIs(line.code, StatusCode.ERROR)
            self.assertIn("not in force", line.text)
            # A later successful write does not clear it: what the file held
            # before the restart is still not in force.
            self.assertTrue(state.write("a.json", {"fresh": True}))
            self.assertEqual([entry.slug for entry in state.lines()],
                             ["load.a.json"])

    def test_a_reader_may_report_a_shape_it_cannot_use(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            with self.assertLogs(level="ERROR"):
                state.report_load_failure("b.json", "no 'nodes' table")
            (line,) = state.lines()
            self.assertEqual(line.slug, "load.b.json")
            self.assertIn("no 'nodes' table", line.text)


class WriteThroughTests(TestCase):
    def test_a_write_is_atomic_and_creates_the_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(Path(directory) / "var" / "state")
            self.assertTrue(state.write("a.json", {"x": 1}))
            self.assertEqual(on_disk(state.path("a.json")), {"x": 1})
            self.assertEqual(list(state.directory.glob("*.tmp")), [])

    def test_a_failed_write_is_a_line_until_a_write_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / "state"
            blocked.write_text("a file where the directory should be")
            state = StateLayer(blocked)
            with self.assertLogs(level="WARNING"):
                self.assertFalse(state.write("a.json", {"x": 1}))
            (line,) = state.lines()
            self.assertEqual(line.slug, "save.a.json")
            self.assertIs(line.code, StatusCode.WARN)
            self.assertIn("nothing is lost yet", line.text)
            # The report clears: the next write that succeeds takes the line with it.
            blocked.unlink()
            self.assertTrue(state.write("a.json", {"x": 2}))
            self.assertEqual(state.lines(), ())

    @unittest.skipIf(os.geteuid() == 0, "root writes anywhere")
    def test_an_unwritable_directory_is_the_same_line(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            os.chmod(directory, stat.S_IRUSR | stat.S_IXUSR)
            try:
                with self.assertLogs(level="WARNING"):
                    self.assertFalse(state.write("a.json", {}))
                self.assertEqual([entry.slug for entry in state.lines()],
                                 ["save.a.json"])
            finally:
                os.chmod(directory, stat.S_IRWXU)


class KeptFileTests(TestCase):
    """The periodic discipline: a producer, the interval, the shutdown flush."""

    def test_the_first_tick_starts_the_interval_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = _Clock()
            state = StateLayer(directory, interval_seconds=60, clock=clock)
            calls = []
            state.keep(EVENTS_FILE, lambda: calls.append(1) or {"events": []})
            state.tick()
            self.assertEqual(calls, [])
            self.assertFalse(state.path(EVENTS_FILE).exists())
            clock.now += 59
            state.tick()
            self.assertEqual(calls, [])
            clock.now += 1
            state.tick()
            self.assertEqual(calls, [1])
            self.assertEqual(on_disk(state.path(EVENTS_FILE)), {"events": []})

    def test_an_unchanged_state_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = _Clock()
            state = StateLayer(directory, interval_seconds=1, clock=clock)
            payload = {"events": [{"path": "/a"}]}
            state.keep(EVENTS_FILE, lambda: payload)
            state.tick()
            clock.now += 1
            state.tick()
            first = state.path(EVENTS_FILE).stat().st_ino
            clock.now += 1
            state.tick()
            # os.replace lands a new inode on every real write; the same inode
            # says the file was left alone.
            self.assertEqual(state.path(EVENTS_FILE).stat().st_ino, first)
            payload["events"].append({"path": "/b"})
            clock.now += 1
            state.tick()
            self.assertNotEqual(state.path(EVENTS_FILE).stat().st_ino, first)

    def test_a_save_leaves_no_copy_of_the_file_s_text_in_the_process(self):
        """The layer knows an unchanged state by what it last wrote, and what it
        keeps of that is a digest, never the text: a kept file's text — the
        series' megabytes among them — held for the life of the process only to be
        compared with the next one is memory the process carries for nothing.
        Measured, as the process holds it after the save."""
        payload = {"series": [f"reading {number:06d} " + "x" * 90
                              for number in range(20_000)]}
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, clock=_Clock())
            state.keep(SERIES_FILE, lambda: payload)
            tracemalloc.start()
            try:
                before, _peak = tracemalloc.get_traced_memory()
                state.flush()
                after, _peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            # the text is the JSON inside the gzip (ADR-0134), megabytes still
            size = len(gzip.decompress(state.path(SERIES_FILE).read_bytes()))
            self.assertGreater(size, 2 * 1024 ** 2)
            self.assertLess(after - before, size // 100)
            self.assertEqual(on_disk(state.path(SERIES_FILE)), payload)

    def test_flush_writes_what_changed_regardless_of_the_interval(self):
        # The graceful-shutdown write.
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600, clock=_Clock())
            state.keep("a.json", lambda: {"a": 1})
            state.keep("b.json", lambda: {"b": 2})
            state.flush()
            self.assertEqual(on_disk(state.path("a.json")), {"a": 1})
            self.assertEqual(on_disk(state.path("b.json")), {"b": 2})

    def test_a_producer_that_raises_is_a_failed_save_of_its_file_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, clock=_Clock())

            def broken():
                raise RuntimeError("no copy today")

            state.keep("a.json", broken)
            state.keep("b.json", lambda: {"b": 2})
            with self.assertLogs(level="ERROR"):
                state.flush()
            (line,) = state.lines()
            self.assertEqual(line.slug, "save.a.json")
            self.assertIn("no copy today", line.text)
            self.assertTrue(state.path("b.json").exists())

    def test_a_kept_file_that_cannot_be_written_is_retried_next_time(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / "state"
            blocked.write_text("in the way")
            state = StateLayer(blocked, clock=_Clock())
            state.keep("a.json", lambda: {"a": 1})
            with self.assertLogs(level="WARNING"):
                state.flush()
            self.assertEqual([entry.slug for entry in state.lines()],
                             ["save.a.json"])
            blocked.unlink()
            state.flush()
            self.assertEqual(state.lines(), ())
            self.assertEqual(on_disk(state.path("a.json")), {"a": 1})


class OneWriterTests(TestCase):
    """What the layer does with the directory's lease (ADR-0090) and after the stop's
    one save (ADR-0088 decision 3)."""

    def _held(self, directory: str) -> tuple[StateLayer, Lease]:
        where = Path(directory) / "var" / "state"
        state = StateLayer(where)
        lease = Lease(where, mark="me:1:t:a", kernel="kernel-A", sleep=lambda _: None)
        lease.take()
        state.hold(lease)
        return state, lease

    def test_a_layer_whose_lease_was_taken_writes_nothing_more(self):
        with tempfile.TemporaryDirectory() as directory:
            state, lease = self._held(directory)
            self.assertTrue(state.write("pins.json", {"a": 1}))
            (Path(directory) / "var" / "state.lease").write_text(json.dumps(
                {"mark": "thief:2:t:b", "host": "elsewhere", "pid": 2}))
            self.assertFalse(state.write("pins.json", {"a": 2}))
            self.assertEqual(on_disk(state.path("pins.json")), {"a": 1})
            state.keep("kept.json", lambda: {"b": 1})
            state.flush()
            self.assertFalse(state.path("kept.json").exists())
            self.assertIn("thief:2:t:b", lease.lost or "")
            lease.release()

    def test_the_layer_says_who_holds_the_directory_once_its_lease_was_taken(self):
        # What the engine asks on every tick, to stop running checks as well as
        # writing them down (ADR-0090 decision 7).
        with tempfile.TemporaryDirectory() as directory:
            state, lease = self._held(directory)
            self.assertIsNone(state.lost)
            (Path(directory) / "var" / "state.lease").write_text(json.dumps(
                {"mark": "thief:2:t:b", "host": "elsewhere", "pid": 2}))
            self.assertFalse(state.write("pins.json", {"a": 2}))
            self.assertIn("thief:2:t:b on elsewhere, pid 2", state.lost or "")
            lease.release()

    def test_a_layer_without_a_lease_has_none_to_lose(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(StateLayer(directory).lost)

    def test_the_stop_saves_once_releases_the_lease_and_nothing_writes_after_it(self):
        with tempfile.TemporaryDirectory() as directory:
            state, _ = self._held(directory)
            held = {"n": 1}
            state.keep("kept.json", lambda: dict(held))
            state.shutdown()
            self.assertEqual(on_disk(state.path("kept.json")), {"n": 1})
            lease = json.loads((Path(directory) / "var" / "state.lease").read_text())
            self.assertEqual(lease["state"], "released")
            held["n"] = 2
            state.flush()
            self.assertFalse(state.write("late.json", {"late": True}))
            self.assertEqual(on_disk(state.path("kept.json")), {"n": 1})
            self.assertFalse(state.path("late.json").exists())
            state.shutdown()          # a second stop writes nothing either
            self.assertEqual(on_disk(state.path("kept.json")), {"n": 1})

    def test_a_layer_without_a_lease_still_writes_until_its_stop(self):
        """A layer nobody handed a lease to — every test's, and a server's before the
        start — writes as it always did; only the stop closes it."""
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            self.assertTrue(state.write("pins.json", {"a": 1}))
            state.shutdown()
            self.assertFalse(state.write("pins.json", {"a": 2}))


class LinesTests(TestCase):
    def test_the_lines_are_entries_with_stable_slugs_in_file_order(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            with self.assertLogs(level="ERROR"):
                state.report_load_failure("z.json", "bad")
                state.report_load_failure("a.json", "worse")
            lines = state.lines()
            self.assertTrue(all(isinstance(line, Entry) for line in lines))
            self.assertEqual([line.slug for line in lines],
                             ["load.a.json", "load.z.json"])

    def test_an_error_text_is_escaped_as_external_text(self):
        # A reason is Markdown (ADR-0018): an OS error carrying a path with
        # asterisks must not turn bold.
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            with self.assertLogs(level="ERROR"):
                state.report_load_failure("a.json", "/srv/**prod**/state")
            (line,) = state.lines()
            self.assertIn(r"\*\*prod\*\*", line.text)


class _Roots:
    """Stands in for the engine at startup: the restore asks it one thing."""

    def __init__(self, *roots: str) -> None:
        self._roots = list(roots)

    def check_roots(self) -> list[str]:
        return self._roots


class RestoreAtStartupTests(TestCase):
    """``app._restore_state``: a restarted instance shows yesterday's events and
    its pins, this process keeps writing the log, and a failure never refuses."""

    def setUp(self):
        from little_sister import app as app_module
        from little_sister.tree import StatusTree
        self._app = app_module
        self._original = app_module.status_tree
        self.tree = StatusTree()
        app_module.status_tree = self.tree

    def tearDown(self):
        self._app.status_tree = self._original

    def _yesterday(self, directory: str) -> StateLayer:
        from little_sister.pins import MAINTENANCE, Pin, PinStore
        from little_sister.tree import StatusTree
        state = StateLayer(directory)
        PinStore(state).save({"/x": Pin(MAINTENANCE,
            "planned", datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2999, 1, 1, tzinfo=UTC), "ada")})
        written = StatusTree()
        written.upsert("/x", StatusCode.OK)
        written.upsert("/x", StatusCode.ERROR, "down")
        state.write(EVENTS_FILE, written.events_payload())
        return state

    def test_a_restarted_instance_shows_yesterdays_events_and_pins(self):
        from little_sister.self_report import registered_contributors
        with tempfile.TemporaryDirectory() as directory:
            state = self._yesterday(directory)
            self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            self.assertEqual(self.tree.maintenance_entry("/x").note, "planned")
            # yesterday's transitions first, then this process's own — the pin
            # replayed onto the node
            self.assertEqual([event.new for event in self.tree.recent_events()
                              if event.path == "/x"],
                             [StatusCode.OK, StatusCode.ERROR,
                              StatusCode.MAINTENANCE])
            self.assertEqual([r.name for r in registered_contributors()], ["state"])
            self.assertEqual(state.lines(), ())
            # this process keeps the log: the flush writes what happened since
            self.tree.upsert("/x", StatusCode.OK)
            state.flush()
            codes = [raw["new"] for raw in on_disk(state.path(EVENTS_FILE))["events"]]
            self.assertEqual(codes[-1], "OK")
            self.assertGreater(len(codes), 2)

    def _pinned_yesterday(self, directory: str) -> StateLayer:
        """Yesterday's pins: on a check's node and on a path that no check covers,
        and on the instance's own line — its node, a child of it, and a line of
        another child — each with a line's pin beside the node's."""
        from little_sister.pins import MAINTENANCE, Pin, PinStore
        state = StateLayer(directory)
        pin = Pin(MAINTENANCE, "planned", datetime(2026, 1, 1, tzinfo=UTC),
                               datetime(2999, 1, 1, tzinfo=UTC), "ada")
        PinStore(state).save(
            {"/x": pin, "/gone": pin, HEARTBEAT_PATH: pin,
             f"{HEARTBEAT_PATH}/keeper": pin},
            {(f"{HEARTBEAT_PATH}/state", "keeper-behind"): pin,
             ("/x", "line"): pin, ("/gone", "line"): pin})
        return state

    def test_a_pin_on_the_instances_own_line_is_no_orphan(self):
        # the instance's own node and its children are no check's, so a pin on one
        # of them, a node's or a line's, was restored and then reaped at every
        # start, the log naming it an orphaned pin
        from little_sister.pins import PinStore
        state_child = f"{HEARTBEAT_PATH}/state"
        keeper = f"{HEARTBEAT_PATH}/keeper"
        with tempfile.TemporaryDirectory() as directory:
            state = self._pinned_yesterday(directory)
            with self.assertLogs(level="INFO") as logged:
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            for path in (HEARTBEAT_PATH, keeper):
                with self.subTest(path=path):
                    held = self.tree.maintenance_entry(path)
                    assert held is not None, path
                    self.assertEqual(held.note, "planned")
            self.assertEqual(sorted(self.tree.entry_maintenance_at(state_child)),
                             ["keeper-behind"])
            # what the file holds after the start is what the tree holds
            held = PinStore(state).load_all()
            nodes, lines = held.nodes, held.lines
            self.assertEqual(sorted(nodes), sorted(["/x", HEARTBEAT_PATH, keeper]))
            self.assertEqual(sorted(lines),
                             sorted([("/x", "line"), (state_child, "keeper-behind")]))
            # and the log names no pin of the instance's as orphaned
            for line in logged.output:
                if "orphaned pin" in line:
                    self.assertNotIn(HEARTBEAT_PATH, line)

    def test_a_pin_that_no_check_covers_is_still_reaped(self):
        # the other half: the instance's own line is the one exception
        with tempfile.TemporaryDirectory() as directory:
            state = self._pinned_yesterday(directory)
            with self.assertLogs(level="INFO") as logged:
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            self.assertIsNone(self.tree.maintenance_entry("/gone"))
            self.assertEqual(self.tree.entry_maintenance_at("/gone"), {})
            self.assertIsNotNone(self.tree.maintenance_entry("/x"))
            self.assertEqual(sorted(self.tree.entry_maintenance_at("/x")), ["line"])
            reaped = [line for line in logged.output if "orphaned pin" in line]
            self.assertEqual(len(reaped), 1, logged.output)
            self.assertTrue(reaped[0].endswith("reaped 1 orphaned pin(s): /gone"),
                            reaped[0])

    def test_an_unreadable_log_starts_empty_and_is_a_line_and_the_pins_still_load(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._yesterday(directory)
            state.path(EVENTS_FILE).write_text("{torn")
            with self.assertLogs(level="ERROR"):
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            self.assertEqual(self.tree.maintenance_entry("/x").note, "planned")
            self.assertEqual([line.slug for line in state.lines()],
                             [f"load.{EVENTS_FILE}"])

    def test_a_log_of_another_shape_is_a_line_too(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._yesterday(directory)
            state.write(EVENTS_FILE, {"events": [{"old": "OK", "new": "NOPE"}]})
            with self.assertLogs(level="ERROR"):
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            # nothing of the file was read; the replayed pin is the only event
            self.assertEqual([event.new for event in self.tree.recent_events()],
                             [StatusCode.MAINTENANCE])
            (line,) = state.lines()
            self.assertEqual(line.slug, f"load.{EVENTS_FILE}")
            self.assertIn("unknown code", line.text)


class BackupTests(TestCase):
    """What was set aside, and the way back (ADR-0077): the ``state`` child
    lists every ``.bak`` with its age beside the live copy's — both local files,
    one clock — and *take the backups* swaps them through the same adoption."""

    def _layer(self, directory: str, wall: _Clock) -> StateLayer:
        return StateLayer(directory, interval_seconds=3600, wall=wall)

    @staticmethod
    def _aged(path: Path, text: str | bytes, stamp: float) -> None:
        path.write_bytes(text if isinstance(text, bytes) else text.encode())
        os.utime(path, (stamp, stamp))

    def test_a_backup_is_listed_beside_the_live_copy_with_both_ages(self):
        with tempfile.TemporaryDirectory() as directory:
            wall = _Clock(100_000.0)
            state = self._layer(directory, wall)
            # an earlier process set a.json.bak aside two hours ago and wrote the
            # live copy five minutes ago; the stock is read once at startup
            self._aged(state.path("a.json" + BACKUP_SUFFIX), '{"k": 0}',
                       wall.now - 7200)
            self._aged(state.path("a.json"), '{"k": 1}', wall.now - 300)
            state.take_stock()
            state.restore_with("a.json", lambda payload: None)
            # a backup is a fact, not a claim: it is the layer's report, never a
            # line (ADR-0044 decision 6, ADR-0076)
            self.assertEqual(state.lines(), ())
            report = state.report()
            self.assertIn("a.json.bak", report)
            self.assertIn("2h", report)
            self.assertIn("the live a.json was written 5m ago", report)
            self.assertIn("take the backups", report)
            # the report reads the stock, not the disk: the ages move with the
            # clock and not with a stat
            wall.now += 3600
            report = state.report()
            self.assertIn("3h", report)
            self.assertIn("1h 5m ago", report)

    def test_a_backup_nothing_here_keeps_is_listed_and_not_taken(self):
        with tempfile.TemporaryDirectory() as directory:
            wall = _Clock(100_000.0)
            state = self._layer(directory, wall)
            self._aged(state.path("old.json" + BACKUP_SUFFIX), '{"old": true}',
                       wall.now - 60)
            state.take_stock()
            self.assertEqual(state.lines(), ())
            report = state.report()
            self.assertIn("old.json.bak", report)
            self.assertIn("nothing here keeps", report)
            self.assertIn("there is no live old.json", report)
            self.assertIn("listed, not taken", report)
            self.assertEqual(state.take_backups(), "no backup to take")
            self.assertEqual(state.path("old.json" + BACKUP_SUFFIX).read_text(),
                             '{"old": true}')
            self.assertFalse(state.path("old.json").exists())

    def test_take_the_backups_swaps_the_files_and_hands_the_backup_to_restore(self):
        """The *done when*: the swap read as the pins before and after."""
        with tempfile.TemporaryDirectory() as directory:
            wall = _Clock(100_000.0)
            state = self._layer(directory, wall)
            pins: dict[str, object] = {"nodes": {"/x": "theirs"}}
            log = {"events": ["theirs"]}
            state.restore_with("pins.json", pins.update)
            state.keep(EVENTS_FILE, lambda: log, restore=log.update)
            state.write("pins.json", pins)
            state.flush()
            self._aged(state.path("pins.json" + BACKUP_SUFFIX),
                       json.dumps({"nodes": {"/y": "mine"}}), wall.now - 600)
            self._aged(state.path(EVENTS_FILE + BACKUP_SUFFIX),
                       encoded(EVENTS_FILE, {"events": ["mine"]}), wall.now - 600)
            state.take_stock()

            said = state.take_backups()

            self.assertEqual(pins, {"nodes": {"/y": "mine"}})
            self.assertEqual(log, {"events": ["mine"]})
            self.assertEqual(state.read("pins.json"),
                             {"nodes": {"/y": "mine"}})
            self.assertEqual(on_disk(state.path("pins.json" + BACKUP_SUFFIX)),
                             {"nodes": {"/x": "theirs"}})
            self.assertEqual(on_disk(state.path(EVENTS_FILE + BACKUP_SUFFIX)),
                             {"events": ["theirs"]})
            # taken in registration order, the same order an adoption uses
            self.assertIn("took the backup of pins.json, events.json", said)
            self.assertIn(BACKUP_SUFFIX, said)
            # the stamps moved with the files: what is live now was written now
            # and the .bak is as old as the copy it holds
            wall.now += 60
            report = state.report()
            self.assertIn("pins.json.bak holds what was set aside, last "
                          "written 1m ago", report)
            self.assertIn("the live pins.json was written 1m ago", report)
            self.assertEqual(state.lines(), ())

    def test_the_way_back_is_taken_by_the_keeper(self):
        """The undo is a second caller of the adoption, and the keeper then takes
        what came back — the store holds what was live, not the backup."""
        from little_sister.keeper import forget_keeper, register_keeper
        self.addCleanup(forget_keeper)
        saved: list[str] = []

        class _Keeper:
            def load(self, name: str) -> bytes | None:
                return None

            def save(self, name: str, data: bytes) -> None:
                saved.append(name)

            def list(self) -> list[str]:
                return []
        register_keeper("fake", _Keeper())
        with tempfile.TemporaryDirectory() as directory:
            wall = _Clock(100_000.0)
            state = self._layer(directory, wall)
            held = {"k": "theirs"}
            state.restore_with("a.json", held.update)
            state.write("a.json", held)
            state.flush()
            self.assertEqual(saved, ["a.json"])
            self._aged(state.path("a.json" + BACKUP_SUFFIX), '{"k": "mine"}',
                       wall.now - 600)
            state.take_stock()
            state.take_backups()
            self.assertEqual(held, {"k": "mine"})
            state.flush()
            self.assertEqual(saved, ["a.json", "a.json"])

    def test_a_backup_that_cannot_be_taken_is_a_line_and_the_rest_are_taken(self):
        with tempfile.TemporaryDirectory() as directory:
            wall = _Clock(100_000.0)
            state = self._layer(directory, wall)
            taken: list[object] = []
            state.restore_with("a.json", taken.append)
            state.restore_with("b.json", taken.append)
            state.write("a.json", {"a": "live"})
            state.write("b.json", {"b": "live"})
            self._aged(state.path("a.json" + BACKUP_SUFFIX), "{torn", wall.now - 60)
            self._aged(state.path("b.json" + BACKUP_SUFFIX), '{"b": "old"}',
                       wall.now - 60)
            state.take_stock()
            with self.assertLogs(level="ERROR"):
                said = state.take_backups()
            self.assertEqual(taken, [{"b": "old"}])
            self.assertIn("took the backup of b.json", said)
            self.assertIn("could not take the backup of a.json", said)
            self.assertEqual(state.read("a.json"), {"a": "live"})
            self.assertEqual(self._coded(state), ["load.a.json"])
            line = next(line for line in state.lines() if line.slug == "load.a.json")
            self.assertIs(line.code, StatusCode.ERROR)
            self.assertIn("the backup of a.json could not be adopted", line.text)

    def _coded(self, state: StateLayer) -> list[str]:
        return [line.slug for line in state.lines() if line.code is not None]


if __name__ == "__main__":
    unittest.main()
