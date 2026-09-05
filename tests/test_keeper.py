"""The keeper seam (ADR-0071 §5): the file store that carries ``var/state/``
somewhere durable, and the state layer's two ends of it — a restore before
anything reads, and a mirror after the writer.

Written from the claims in :mod:`little_sister.keeper` and
:mod:`little_sister.state`: one keeper per instance, claimed once under ADR-0064's
rules; a keeper that cannot be reached leaves the local files as they are and is a
line; a save that fails is a line until one lands. The last classes are the
takeover (ADR-0077): authority follows the lease, so what the store changed while
somebody else held it is adopted before the new holder's first save.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase

from little_sister.codes import StatusCode
from little_sister.keeper import (
    KeeperConflictError,
    forget_keeper,
    register_keeper,
    registered_keeper,
)
from little_sister.state import BACKUP_SUFFIX, EVENTS_FILE, MAINTENANCE_FILE, StateLayer


class _Store:
    """A keeper that holds bytes in a dict and can be told to fail."""

    def __init__(self, held: dict[str, bytes] | None = None) -> None:
        self.held: dict[str, bytes] = dict(held or {})
        self.saved: list[tuple[str, bytes]] = []
        self.listing: list[str] | None = None
        self.raise_on_list: Exception | None = None
        self.raise_on_load: dict[str, Exception] = {}
        self.raise_on_save: dict[str, Exception] = {}

    def load(self, name: str) -> bytes | None:
        if name in self.raise_on_load:
            raise self.raise_on_load[name]
        return self.held.get(name)

    def save(self, name: str, data: bytes) -> None:
        if name in self.raise_on_save:
            raise self.raise_on_save[name]
        self.saved.append((name, data))
        self.held[name] = data

    def list(self) -> list[str]:
        if self.raise_on_list is not None:
            raise self.raise_on_list
        return self.listing if self.listing is not None else sorted(self.held)


class _KeeperTest(TestCase):
    def setUp(self):
        forget_keeper()

    def tearDown(self):
        forget_keeper()

    def _layer(self, directory: str) -> StateLayer:
        return StateLayer(directory, interval_seconds=3600)

    def _slugs(self, state: StateLayer) -> list[str]:
        return [line.slug for line in state.lines()]

    def _coded(self, state: StateLayer) -> list[str]:
        """The slugs of the lines that grade — a ``.bak`` beside a live file is
        listed as a fact (ADR-0077) and claims nothing."""
        return [line.slug for line in state.lines() if line.code is not None]

    def _line(self, state: StateLayer, slug: str):
        found = [line for line in state.lines() if line.slug == slug]
        assert len(found) == 1, f"{slug!r} not exactly once in {self._slugs(state)}"
        return found[0]


class RegistrationTests(_KeeperTest):
    """ADR-0064's rules, for a seam with **one** slot rather than one per name."""

    def test_a_local_installation_has_none_and_that_is_a_shape_not_a_gap(self):
        self.assertIsNone(registered_keeper())

    def test_the_registered_keeper_records_the_name_and_the_calling_package(self):
        register_keeper("s3", _Store())
        keeping = registered_keeper()
        assert keeping is not None
        self.assertEqual(keeping.name, "s3")
        # This test module is the caller, so the inferred package is `tests`.
        self.assertEqual(keeping.package, "tests")
        self.assertEqual(keeping.replaced, "")

    def test_the_same_package_replaces_silently_because_a_module_reloads(self):
        first, second = _Store(), _Store()
        register_keeper("s3", first)
        register_keeper("s3", second)
        keeping = registered_keeper()
        assert keeping is not None
        self.assertIs(keeping.keeper, second)
        self.assertEqual(keeping.replaced, "")

    def test_another_package_refuses_and_names_both(self):
        register_keeper("s3", _Store())
        keeping = registered_keeper()
        assert keeping is not None
        object.__setattr__(keeping, "package", "little_sister_aws")
        with self.assertRaises(KeeperConflictError) as caught:
            register_keeper("nfs", _Store())
        message = str(caught.exception)
        self.assertIn("little_sister_aws", message)
        self.assertIn("'s3'", message)
        self.assertIn("'nfs'", message)
        # nothing moved: the refusal is at startup, before anything ran
        self.assertIs(registered_keeper(), keeping)

    def test_replace_is_how_it_is_done_on_purpose_and_is_recorded(self):
        register_keeper("s3", _Store())
        keeping = registered_keeper()
        assert keeping is not None
        object.__setattr__(keeping, "package", "little_sister_aws")
        register_keeper("nfs", _Store(), replace=True)
        now = registered_keeper()
        assert now is not None
        self.assertEqual(now.name, "nfs")
        self.assertEqual(now.replaced, "little_sister_aws")

    def test_a_name_that_is_not_one_identifier_is_refused(self):
        for name in ("", "s 3", "s3/backup", "s3.backup", "-s3"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                register_keeper(name, _Store())


class RestoreTests(_KeeperTest):
    """The keeper loads **first**, and a failure never refuses to start."""

    def test_every_file_it_holds_arrives_in_the_directory(self):
        store = _Store({"events.json": b'{"events": []}',
                        "store.sqlite3": b"\x00binary"})
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.restore_from_keeper()
            self.assertEqual(state.path("events.json").read_bytes(),
                             b'{"events": []}')
            # it never knows what a file means: a package's own file rides along
            self.assertEqual(state.path("store.sqlite3").read_bytes(), b"\x00binary")
            self.assertEqual(state.lines(), ())

    def test_what_the_keeper_holds_wins_over_a_local_file(self):
        register_keeper("s3", _Store({"a.json": b"from the keeper"}))
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.path("a.json").parent.mkdir(parents=True, exist_ok=True)
            state.path("a.json").write_bytes(b"from this machine")
            state.restore_from_keeper()
            self.assertEqual(state.path("a.json").read_bytes(), b"from the keeper")

    def test_no_keeper_is_a_no_op_and_says_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.restore_from_keeper()
            self.assertEqual(state.lines(), ())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_a_keeper_that_cannot_be_reached_leaves_the_local_files_alone(self):
        store = _Store({"a.json": b"from the keeper"})
        store.raise_on_list = OSError("no credentials")
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"local": True})
            with self.assertLogs(level="ERROR"):
                state.restore_from_keeper()
            self.assertIn(b"local", state.path("a.json").read_bytes())
            line = self._line(state, "keeper.load")
            self.assertIs(line.code, StatusCode.ERROR)
            self.assertIn("the s3 keeper", line.text)
            self.assertIn("no credentials", line.text)
            self.assertIn("not in force", line.text)

    def test_one_file_that_cannot_be_fetched_leaves_the_others_arriving(self):
        store = _Store({"a.json": b"a", "b.json": b"b"})
        store.raise_on_load = {"a.json": TimeoutError("too slow")}
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            with self.assertLogs(level="ERROR"):
                state.restore_from_keeper()
            self.assertFalse(state.path("a.json").exists())
            self.assertEqual(state.path("b.json").read_bytes(), b"b")
            self.assertIn("a.json", self._line(state, "keeper.load").text)

    def test_a_name_it_holds_nothing_for_is_not_a_failure(self):
        store = _Store()
        store.listing = ["gone.json"]
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            with self.assertLogs(level="INFO"):
                state.restore_from_keeper()
            self.assertFalse(state.path("gone.json").exists())
            self.assertEqual(state.lines(), ())

    def test_a_name_that_would_escape_the_directory_is_refused(self):
        # The escape target is inside a directory of this test's own, so what the
        # assertion reads is what this test did and not what the machine holds:
        # against the shared temporary directory it passes or fails by what some
        # other run left there, which is how it first passed for the wrong reason.
        store = _Store({"../escaped.json": b"x", "/etc/passwd": b"x",
                        "sub/dir.json": b"x", "..": b"x"})
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as outer:
            directory = Path(outer) / "state"
            state = self._layer(str(directory))
            with self.assertLogs(level="ERROR"):
                state.restore_from_keeper()
            self.assertEqual(sorted(path.name for path in Path(outer).iterdir()), [])
            self.assertIn("not a state file name",
                          self._line(state, "keeper.load").text)


class SaveTests(_KeeperTest):
    """The mirror: every file, after the writer, on the same interval."""

    def test_the_flush_sends_every_file_in_the_directory(self):
        store = _Store()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("maintenance.json", {"nodes": {}})
            state.keep("events.json", lambda: {"events": [1]})
            # a file no producer here registered — a package's own store
            state.path("store.sqlite3").write_bytes(b"\x00binary")
            state.flush()
            self.assertEqual(sorted(name for name, _data in store.saved),
                             ["events.json", "maintenance.json", "store.sqlite3"])
            self.assertEqual(state.lines(), ())

    def test_it_takes_what_this_flush_wrote_not_the_flush_before(self):
        store = _Store()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            payload = {"events": [1]}
            state.keep("events.json", lambda: payload)
            state.flush()
            payload["events"].append(2)
            state.flush()
            sent = [data for name, data in store.saved if name == "events.json"]
            self.assertEqual(len(sent), 2)
            self.assertIn(b"2", sent[-1])

    def test_an_unchanged_file_is_not_sent_again(self):
        store = _Store()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.flush()
            state.flush()
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_a_half_written_file_is_not_state_and_is_not_mirrored(self):
        store = _Store()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.path("a.json.tmp").write_bytes(b"half")
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_a_failed_save_is_a_line_that_names_the_file_and_the_keeper(self):
        store = _Store()
        store.raise_on_save = {"a.json": OSError("bucket is not there")}
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.write("b.json", {"k": 2})
            with self.assertLogs(level="WARNING"):
                state.flush()
            # the other file still went
            self.assertEqual([name for name, _ in store.saved], ["b.json"])
            line = self._line(state, "keeper.save.a.json")
            self.assertIs(line.code, StatusCode.WARN)
            self.assertIn("the last save of a.json to the s3 keeper failed",
                          line.text)
            self.assertIn("bucket is not there", line.text)
            self.assertIn("nothing is lost yet", line.text)
            # and the local file is untouched by any of it
            self.assertIn(b'"k": 1', state.path("a.json").read_bytes())

    def test_the_line_clears_when_a_save_of_that_file_lands(self):
        store = _Store()
        store.raise_on_save = {"a.json": OSError("nope")}
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            with self.assertLogs(level="WARNING"):
                state.flush()
            self.assertEqual(self._slugs(state), ["keeper.save.a.json"])
            store.raise_on_save = {}
            state.flush()
            self.assertEqual(state.lines(), ())

    def test_a_keeper_that_raises_never_reaches_the_caller(self):
        store = _Store()
        store.raise_on_save = {"a.json": RuntimeError("boom")}
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            with self.assertLogs(level="WARNING"):
                state.flush()      # the tick survives it, which is the claim
            self.assertEqual(self._slugs(state), ["keeper.save.a.json"])

    def test_the_tick_carries_it_on_the_interval(self):
        store = _Store()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            clock = _Clock()
            state = StateLayer(directory, interval_seconds=60, clock=clock)
            state.write("a.json", {"k": 1})
            state.tick()                       # the first tick starts the interval
            self.assertEqual(store.saved, [])
            clock.now += 61
            state.tick()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class OnTheHeartbeatTests(_KeeperTest):
    """The keeper's failures reach the same node as the layer's own, through the
    same contributor, and are pinnable the same way."""

    def test_the_load_line_stands_above_the_per_file_ones(self):
        store = _Store()
        store.raise_on_list = OSError("no bucket")
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.path("a.json").parent.mkdir(parents=True, exist_ok=True)
            state.path("a.json").write_text("{torn")
            with self.assertLogs(level="ERROR"):
                state.restore_from_keeper()
            with self.assertLogs(level="ERROR"):
                state.read("a.json")
            self.assertEqual(self._slugs(state), ["keeper.load", "load.a.json"])

    def test_the_instance_restored_from_a_keeper_says_nothing_at_all(self):
        # A working keeper is silent everywhere but /system: nothing claims
        # anything, so the heartbeat stays OK.
        register_keeper("s3", _Store({"events.json": b'{"events": []}'}))
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.restore_from_keeper()
            state.flush()
            self.assertEqual(state.lines(), ())

    def test_the_first_flush_after_a_restore_does_not_send_back_what_arrived(self):
        """What the keeper handed over at startup is what it holds: a file is sent
        again only once it has changed, not once per start."""
        store = _Store({"events.json": b'{"events": []}', "a.json": b'{"k": 1}'})
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.restore_from_keeper()
            state.flush()
            self.assertEqual(store.saved, [])
            state.write("a.json", {"k": 2})
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])


class _Roots:
    def __init__(self, *roots: str) -> None:
        self._roots = list(roots)

    def check_roots(self) -> list[str]:
        return self._roots


class AFreshMachineTests(_KeeperTest):
    """The phase's *done when*, end to end: an instance started on a fresh machine
    with a keeper registered comes up with the state it left on the old one."""

    def setUp(self):
        super().setUp()
        from little_sister import app as app_module
        from little_sister.tree import StatusTree
        self._app = app_module
        self._original = app_module.status_tree
        self.tree = StatusTree()
        app_module.status_tree = self.tree

    def tearDown(self):
        self._app.status_tree = self._original
        super().tearDown()

    def _the_old_machine(self) -> _Store:
        """What the instance that stopped left in the bucket: its event log and
        one pin, written by a state layer of its own."""
        from little_sister.maintenance import MaintenanceEntry, MaintenanceStore
        from little_sister.tree import StatusTree
        store = _Store()
        with tempfile.TemporaryDirectory() as directory:
            old = StateLayer(directory)
            MaintenanceStore(old).save({"/x": MaintenanceEntry(
                "planned", "2026-01-01T00:00:00", "2999-01-01T00:00:00", "ada")})
            written = StatusTree()
            written.upsert("/x", StatusCode.OK)
            written.upsert("/x", StatusCode.ERROR, "down")
            old.write("events.json", written.events_payload())
            for name in ("maintenance.json", "events.json"):
                store.held[name] = old.path(name).read_bytes()
        return store

    def test_a_fresh_machine_comes_up_as_the_instance_that_stopped(self):
        register_keeper("s3", self._the_old_machine())
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)     # an empty machine
            self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            self.assertEqual(self.tree.maintenance_entry("/x").reason, "planned")
            self.assertEqual([event.new for event in self.tree.recent_events()
                              if event.path == "/x"],
                             [StatusCode.OK, StatusCode.ERROR,
                              StatusCode.MAINTENANCE])
            self.assertEqual(state.lines(), ())

    def test_a_keeper_that_cannot_be_reached_starts_the_instance_anyway(self):
        store = self._the_old_machine()
        store.raise_on_list = OSError("no network")
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            with self.assertLogs(level="ERROR"):
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            # started, with nothing — and saying so rather than silently green
            self.assertIsNone(self.tree.maintenance_entry("/x"))
            self.assertEqual(self.tree.recent_events(), ())
            self.assertEqual([line.slug for line in state.lines()], ["keeper.load"])


class _LeaseStore(_Store):
    """A keeper that answers ``tick`` and ``close`` — the shape a store holding a
    lease on its prefix has. ``wanted`` is what the next tick answers."""

    def __init__(self) -> None:
        super().__init__()
        self.wanted = True
        self.ticks: list[float] = []
        self.raise_on_tick: Exception | None = None
        self.closed = 0

    def tick(self, interval_seconds: float) -> bool:
        self.ticks.append(interval_seconds)
        if self.raise_on_tick is not None:
            raise self.raise_on_tick
        return self.wanted

    def close(self) -> None:
        self.closed += 1


class TickTests(_KeeperTest):
    """The two optional methods: a tick before every save, a close at the end."""

    def test_a_keeper_without_tick_takes_every_save_as_before(self):
        store = _Store()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_the_tick_comes_once_per_flush_with_the_interval_and_before_the_save(self):
        store = _LeaseStore()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.flush()
            self.assertEqual(store.ticks, [3600])
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_a_tick_that_declines_sends_nothing_and_is_no_line(self):
        """A keeper that is not the holder this interval: no save, no failure —
        it says why through its own contributor, not the layer's."""
        store = _LeaseStore()
        store.wanted = False
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.flush()
            self.assertEqual(store.saved, [])
            self.assertEqual(state.lines(), ())

    def test_what_a_declined_interval_did_not_send_goes_when_the_next_one_takes(self):
        store = _LeaseStore()
        store.wanted = False
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.flush()
            store.wanted = True
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_a_tick_that_raises_is_a_line_and_no_save_behind_it(self):
        store = _LeaseStore()
        store.raise_on_tick = ConnectionError("bucket unreachable")
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.flush()
            self.assertEqual(store.saved, [])
            line = self._line(state, "keeper.tick")
            self.assertEqual(line.code, StatusCode.WARN)
            self.assertIn("s3", line.text)
            self.assertIn("bucket unreachable", line.text)
            self.assertIn("nothing is lost yet", line.text)
            # and it clears when a tick returns
            store.raise_on_tick = None
            state.flush()
            self.assertEqual(state.lines(), ())
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_shutdown_flushes_and_then_closes(self):
        store = _LeaseStore()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.shutdown()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])
            self.assertEqual(store.closed, 1)

    def test_a_keeper_without_close_is_shut_down_all_the_same(self):
        store = _Store()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"k": 1})
            state.shutdown()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_a_close_that_raises_never_reaches_the_caller(self):
        store = _LeaseStore()
        register_keeper("s3", store)

        def close() -> None:
            raise RuntimeError("no")
        store.close = close  # type: ignore[method-assign]
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.shutdown()


class _TakeoverStore(_LeaseStore):
    """A keeper that also answers ``changed_since_sync`` — the shape of a store
    that remembers a version token per file and compares it with a listing.
    ``changed`` is what the next ask answers; every ask is counted."""

    def __init__(self, held: dict[str, bytes] | None = None) -> None:
        super().__init__()
        self.held = dict(held or {})
        self.changed: list[str] = []
        self.asked = 0
        self.raise_on_ask: Exception | None = None

    def changed_since_sync(self) -> list[str]:
        self.asked += 1
        if self.raise_on_ask is not None:
            raise self.raise_on_ask
        return list(self.changed)


def _far() -> datetime:
    return datetime.now() + timedelta(days=1)


class TakeoverTests(_KeeperTest):
    """Authority follows the lease (ADR-0077): when the keeper's ``tick`` turns
    from *not taking saves* to *taking them*, what the store changed since this
    instance last synced with it is adopted — the process first, the local file
    set aside as ``.bak`` — before the interval's first save."""

    def _standby(self, directory: str, store: _TakeoverStore) -> StateLayer:
        """An instance that came up while somebody else held the lease: it has
        one file of its own, a keeper that declines, and one flush behind it."""
        register_keeper("s3", store)
        state = self._layer(directory)
        state.write("a.json", {"who": "me"})
        store.wanted = False
        state.flush()
        self.assertEqual(store.saved, [])
        return state

    def test_a_keeper_without_the_method_behaves_exactly_as_before(self):
        store = _LeaseStore()
        store.held["a.json"] = b'{"who": "them"}'
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"who": "me"})
            store.wanted = False
            state.flush()
            store.wanted = True
            state.flush()
            # the new holder continues with its own data, and the store takes it
            self.assertEqual(state.read("a.json"), {"who": "me"})
            self.assertFalse(state.path("a.json" + BACKUP_SUFFIX).exists())
            self.assertEqual([name for name, _ in store.saved], ["a.json"])
            self.assertEqual(state.lines(), ())

    def test_a_keeper_that_names_nothing_is_a_silent_takeover(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            state.flush()
            self.assertEqual(store.asked, 1)
            self.assertEqual(state.read("a.json"), {"who": "me"})
            self.assertEqual([name for name, _ in store.saved], ["a.json"])
            self.assertEqual(state.lines(), ())

    def test_the_flip_adopts_what_the_store_changed_before_the_first_save(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]
        taken: list[object] = []
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.restore_with("a.json", taken.append)
            store.wanted = True
            with self.assertLogs(level="INFO") as captured:
                state.flush()
            # the process holds the store's copy, the disk has it, and what was
            # there is beside it as .bak
            self.assertEqual(taken, [{"who": "them"}])
            self.assertEqual(state.read("a.json"), {"who": "them"})
            self.assertEqual(json.loads(state.path("a.json" + BACKUP_SUFFIX)
                                        .read_text()), {"who": "me"})
            # nothing overwrote the store: it holds what it held, and the copy
            # that arrived from it is not sent back until it changes
            self.assertEqual(store.held["a.json"], b'{"who": "them"}')
            self.assertEqual(store.saved, [])
            self.assertTrue(any("took over" in line and "a.json" in line
                                for line in captured.output))
            self.assertEqual(self._slugs(state), [])
            self.assertIn("a.json.bak", state.report())
            # saving resumes from there: one save once it changes
            state.write("a.json", {"who": "me again"})
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_the_first_interval_a_keeper_takes_is_asked_too(self):
        # The successor of a holder that died before anybody wrote again answers
        # nothing and takes over silently; one that wrote meanwhile is adopted.
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            state.write("a.json", {"who": "me"})
            state.flush()
            self.assertEqual(store.asked, 1)
            self.assertEqual(state.read("a.json"), {"who": "them"})

    def test_a_demoted_holder_that_takes_the_lease_back_is_asked_again(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            state.flush()                  # took over, nothing changed
            store.wanted = False
            state.flush()                  # demoted
            store.held["a.json"] = b'{"who": "the interim holder"}'
            store.changed = ["a.json"]
            store.wanted = True
            state.flush()                  # took the lease back
            self.assertEqual(store.asked, 2)
            self.assertEqual(state.read("a.json"), {"who": "the interim holder"})

    def test_a_kept_file_is_adopted_in_memory_and_its_older_backup_overwritten(self):
        # The holder wrote the file with the layer's own serializer, as a holder
        # does: what the producer yields after the adoption is then the text on
        # disk, and the file is neither rewritten nor sent until the state moves.
        store = _TakeoverStore({"log.json": json.dumps({"n": 3}, indent=2,
                                                       sort_keys=True).encode()})
        store.changed = ["log.json"]
        held = {"n": 1}
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.keep("log.json", lambda: held, restore=held.update)
            state.path("log.json" + BACKUP_SUFFIX).write_text('{"n": 0}')
            store.wanted = True
            state.flush()
            self.assertEqual(held, {"n": 3})
            self.assertEqual(json.loads(state.path("log.json" + BACKUP_SUFFIX)
                                        .read_text()), {"n": 1})
            # the adopted text is what the producer now yields: not rewritten,
            # not sent, until the state changes
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])
            held["n"] = 4
            state.flush()
            self.assertEqual([name for name, _ in store.saved],
                             ["a.json", "log.json"])

    def test_a_file_with_no_restore_is_swapped_on_disk_only_and_says_so(self):
        store = _TakeoverStore({"store.sqlite3": b"\x00theirs"})
        store.changed = ["store.sqlite3"]
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.path("store.sqlite3").write_bytes(b"\x00mine")
            store.wanted = True
            state.flush()
            self.assertEqual(state.path("store.sqlite3").read_bytes(), b"\x00theirs")
            self.assertEqual(state.path("store.sqlite3" + BACKUP_SUFFIX).read_bytes(),
                             b"\x00mine")
            line = self._line(state, "load.store.sqlite3")
            self.assertIs(line.code, StatusCode.WARN)
            self.assertIn("nothing in this process is registered to take it",
                          line.text)
            self.assertIn("until a restart", line.text)

    def test_a_copy_the_process_cannot_take_changes_nothing_and_holds_its_save(self):
        store = _TakeoverStore({"a.json": b"{torn", "b.json": b'{"b": 2}'})
        store.changed = ["a.json", "b.json"]
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.write("b.json", {"b": 1})
            state.restore_with("a.json", lambda payload: None)
            store.wanted = True
            with self.assertLogs(level="ERROR"):
                state.flush()
            self.assertEqual(state.read("a.json"), {"who": "me"})
            self.assertFalse(state.path("a.json" + BACKUP_SUFFIX).exists())
            line = self._line(state, "load.a.json")
            self.assertIs(line.code, StatusCode.ERROR)
            self.assertIn("could not be adopted", line.text)
            self.assertIn("not JSON", line.text)
            self.assertIn("held out of the mirror", line.text)
            # the interval's saves ran — this instance is the holder — but not
            # a.json's: its local copy is the shadow the rule forbids saving over
            # the store, and it stays out of the mirror until an adoption lands
            self.assertEqual(store.saved, [])
            self.assertEqual(state.read("b.json"), {"b": 2})
            state.write("b.json", {"b": 3})
            state.write("a.json", {"who": "me still"})
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["b.json"])
            self.assertEqual(store.held["a.json"], b"{torn")

    def test_a_copy_that_cannot_be_fetched_is_held_and_retried_until_it_lands(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]
        store.raise_on_load = {"a.json": TimeoutError("one key of three")}
        taken: list[object] = []
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.restore_with("a.json", taken.append)
            store.wanted = True
            with self.assertLogs(level="ERROR"):
                state.flush()
            self.assertEqual(store.saved, [])
            self.assertIn("held out of the mirror",
                          self._line(state, "load.a.json").text)
            # the next interval — no flip — retries the file by name, without
            # asking what changed, and the hold lifts when it lands
            store.raise_on_load = {}
            with self.assertLogs(level="INFO") as captured:
                state.flush()
            self.assertEqual(store.asked, 1)
            self.assertEqual(taken, [{"who": "them"}])
            self.assertEqual(state.read("a.json"), {"who": "them"})
            self.assertTrue(any("on retry" in line for line in captured.output))
            self.assertEqual(self._coded(state), [])
            self.assertEqual(store.saved, [])
            state.write("a.json", {"who": "me again"})
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_a_held_file_the_store_no_longer_holds_is_released(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]
        store.raise_on_load = {"a.json": TimeoutError("blip")}
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            with self.assertLogs(level="ERROR"):
                state.flush()
            self.assertEqual(store.saved, [])
            store.raise_on_load = {}
            del store.held["a.json"]
            with self.assertLogs(level="INFO"):
                state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])

    def test_the_swap_writes_the_temporary_file_before_anything_moves(self):
        """A disk that refuses fails at the temporary file, before the live file
        has been set aside: nothing moved, the process holds the copy, and the
        retry lands it once the disk allows."""
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]
        held: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.restore_with("a.json", held.update)
            # a directory where the temporary file goes refuses the write
            state.path("a.json.tmp").mkdir()
            store.wanted = True
            with self.assertLogs(level="ERROR"):
                state.flush()
            self.assertEqual(held, {"who": "them"})
            self.assertEqual(state.read("a.json"), {"who": "me"})
            self.assertFalse(state.path("a.json" + BACKUP_SUFFIX).exists())
            line = self._line(state, "load.a.json")
            self.assertIn("could not be put in place", line.text)
            self.assertIn("held out of the mirror", line.text)
            self.assertEqual(store.saved, [])
            state.path("a.json.tmp").rmdir()
            state.flush()
            self.assertEqual(state.read("a.json"), {"who": "them"})
            self.assertEqual(json.loads(state.path("a.json" + BACKUP_SUFFIX)
                                        .read_text()), {"who": "me"})
            self.assertEqual(self._coded(state), [])

    def test_the_last_rename_failing_puts_the_live_file_back(self):
        """The one step that can fail after the file moved: the live file is
        back from ``.bak`` before the failure is raised, and the adoption is the
        line and the hold like any other."""
        import os as _os
        from unittest import mock
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]
        held: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.restore_with("a.json", held.update)
            real_replace = _os.replace

            def failing(src, dst):
                if str(src).endswith(".tmp"):
                    raise OSError("disk full at the last rename")
                real_replace(src, dst)
            store.wanted = True
            with mock.patch("little_sister.state.os.replace", failing), \
                    self.assertLogs(level="ERROR"):
                state.flush()
            self.assertEqual(held, {"who": "them"})
            self.assertEqual(state.read("a.json"), {"who": "me"}, "put back")
            self.assertFalse(state.path("a.json" + BACKUP_SUFFIX).exists())
            self.assertFalse(state.path("a.json.tmp").exists())
            self.assertIn("could not be put in place",
                          self._line(state, "load.a.json").text)
            self.assertEqual(store.saved, [], "held")
            # nothing about the stamps says the file is a backup now
            self.assertEqual(self._slugs(state), ["load.a.json"])
            state.flush()                          # the retry lands
            self.assertEqual(state.read("a.json"), {"who": "them"})
            self.assertEqual(self._coded(state), [])

    def test_a_copy_that_is_the_local_file_already_is_nothing_to_adopt(self):
        """A token that moved without its bytes moving — a versioned or an
        encrypted PUT of the same bytes — makes no ``.bak`` of a file for its
        own copy, and seeds the digest so it is not sent back either."""
        local = json.dumps({"who": "me"}, indent=2, sort_keys=True).encode()
        store = _TakeoverStore({"a.json": local})
        store.changed = ["a.json"]
        taken: list[object] = []
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.restore_with("a.json", taken.append)
            store.wanted = True
            with self.assertLogs(level="INFO") as captured:
                state.flush()
            self.assertEqual(taken, [])
            self.assertFalse(state.path("a.json" + BACKUP_SUFFIX).exists())
            self.assertEqual(state.lines(), ())
            self.assertEqual(store.saved, [])
            self.assertTrue(any("byte for byte" in line for line in captured.output))

    def test_a_backup_or_a_half_written_file_is_not_a_state_file_name(self):
        # A store that offers `a.json.bak` is not offering a state file, at
        # startup and at a takeover alike: the rule that refuses a walk upwards.
        store = _TakeoverStore({"a.json.bak": b"x", "a.json.tmp": b"y"})
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = self._layer(directory)
            with self.assertLogs(level="ERROR"):
                state.restore_from_keeper()
            self.assertEqual(sorted(path.name for path in Path(directory).iterdir()),
                             [])
            self.assertIn("not a state file name",
                          self._line(state, "keeper.load").text)
        store = _TakeoverStore({"a.json.bak": b"x"})
        store.changed = ["a.json.bak"]
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            with self.assertLogs(level="WARNING"):
                state.flush()
            self.assertEqual(store.saved, [])
            self.assertIn("not a state file name",
                          self._line(state, "keeper.tick").text)

    def test_a_restore_that_raises_is_the_same_error_line(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]

        def refuse(payload: object) -> None:
            raise RuntimeError("no room")
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.restore_with("a.json", refuse)
            store.wanted = True
            with self.assertLogs(level="ERROR"):
                state.flush()
            self.assertEqual(state.read("a.json"), {"who": "me"})
            line = self._line(state, "load.a.json")
            self.assertIs(line.code, StatusCode.ERROR)
            self.assertIn("no room", line.text)

    def test_an_adoption_that_succeeds_clears_what_stood_against_the_file(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            state.restore_with("a.json", lambda payload: None)
            with self.assertLogs(level="ERROR"):
                state.report_load_failure("a.json", "torn at startup")
            self.assertEqual(self._slugs(state), ["load.a.json"])
            store.changed = ["a.json"]
            store.wanted = True
            state.flush()
            self.assertEqual(self._coded(state), [])

    def test_a_copy_that_cannot_be_fetched_is_a_line_and_stops_nothing_else(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}', "b.json": b'{"b": 2}'})
        store.changed = ["a.json", "b.json"]
        store.raise_on_load = {"a.json": TimeoutError("too slow")}
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            with self.assertLogs(level="ERROR"):
                state.flush()
            self.assertEqual(state.read("b.json"), {"b": 2})
            self.assertIn("too slow", self._line(state, "load.a.json").text)

    def test_a_name_the_store_holds_nothing_for_is_not_a_failure(self):
        store = _TakeoverStore()
        store.changed = ["gone.json"]
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            with self.assertLogs(level="INFO"):
                state.flush()
            self.assertFalse(state.path("gone.json").exists())
            self.assertEqual(state.lines(), ())

    def test_an_ask_that_raises_is_the_tick_line_with_no_save_behind_it(self):
        store = _TakeoverStore()
        store.raise_on_ask = ConnectionError("listing failed")
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            with self.assertLogs(level="WARNING"):
                state.flush()
            self.assertEqual(store.saved, [])
            line = self._line(state, "keeper.tick")
            self.assertIs(line.code, StatusCode.WARN)
            self.assertIn("listing failed", line.text)
            # asked again next interval, and the saves run once it answers
            store.raise_on_ask = None
            state.flush()
            self.assertEqual(store.asked, 2)
            self.assertEqual([name for name, _ in store.saved], ["a.json"])
            self.assertEqual(state.lines(), ())

    def test_a_name_that_would_escape_the_directory_refuses_the_takeover(self):
        store = _TakeoverStore({"../escaped.json": b"x"})
        store.changed = ["../escaped.json"]
        with tempfile.TemporaryDirectory() as outer:
            directory = Path(outer) / "state"
            state = self._standby(str(directory), store)
            store.wanted = True
            with self.assertLogs(level="WARNING"):
                state.flush()
            self.assertEqual(store.saved, [])
            self.assertEqual(sorted(path.name for path in Path(outer).iterdir()),
                             ["state"])
            self.assertIn("not a state file name",
                          self._line(state, "keeper.tick").text)

    def test_a_backup_never_leaves_the_machine(self):
        store = _TakeoverStore({"a.json": b'{"who": "them"}'})
        store.changed = ["a.json"]
        with tempfile.TemporaryDirectory() as directory:
            state = self._standby(directory, store)
            store.wanted = True
            state.flush()
            self.assertTrue(state.path("a.json" + BACKUP_SUFFIX).exists())
            state.write("a.json", {"who": "me again"})
            state.flush()
            self.assertEqual([name for name, _ in store.saved], ["a.json"])
            self.assertNotIn("a.json" + BACKUP_SUFFIX, store.held)


class AStandbyTakesOverTests(_KeeperTest):
    """The phase's *done when*, on the real tree through ``app._restore_state``:
    an instance that stood by while another held the lease takes over with the
    store's pins and events and not its own, keeps what it had as ``.bak``, and
    saves each file once afterwards."""

    def setUp(self):
        super().setUp()
        from little_sister import app as app_module
        from little_sister import self_report
        from little_sister.tree import StatusTree
        self._app = app_module
        self._original = app_module.status_tree
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.addCleanup(self_report.forget_actions)

    def tearDown(self):
        self._app.status_tree = self._original
        super().tearDown()

    @staticmethod
    def _written_by_the_holder() -> dict[str, bytes]:
        """What the holder wrote to the store while this instance stood by: a pin
        on ``/x`` and two transitions of it."""
        from little_sister.maintenance import MaintenanceEntry, MaintenanceStore
        from little_sister.tree import StatusTree
        with tempfile.TemporaryDirectory() as directory:
            theirs = StateLayer(directory)
            MaintenanceStore(theirs).save({"/x": MaintenanceEntry(
                "theirs", "2026-01-01T00:00:00", "2999-01-01T00:00:00", "ada")})
            written = StatusTree()
            written.upsert("/x", StatusCode.OK)
            written.upsert("/x", StatusCode.ERROR, "down")
            theirs.write(EVENTS_FILE, written.events_payload())
            return {name: theirs.path(name).read_bytes()
                    for name in (MAINTENANCE_FILE, EVENTS_FILE)}

    def test_a_standby_takes_over_with_the_stores_state_and_keeps_its_own_as_bak(self):
        store = _TakeoverStore()
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600)
            self._app._restore_state(_Roots("/x", "/y"), state)  # type: ignore[arg-type]
            # while standing by, this instance pinned /y and observed /y
            self.tree.set_maintenance("/y", "mine", expires_at=_far(), set_by="bob")
            store.wanted = False
            state.flush()
            self.assertEqual(store.saved, [])
            # the holder wrote meanwhile; then its lease lapsed
            store.held.update(self._written_by_the_holder())
            store.changed = [MAINTENANCE_FILE, EVENTS_FILE]
            store.wanted = True

            state.flush()

            # the process holds the store's pins: /x pinned as the holder left
            # it, this instance's own /y cleared with a real transition
            self.assertEqual(self.tree.maintenance_entry("/x").reason, "theirs")
            self.assertIsNone(self.tree.maintenance_entry("/y"))
            # and the store's events, followed by the transitions the adoption
            # itself made — the log was adopted first
            self.assertEqual([(event.path, event.new)
                              for event in self.tree.recent_events()],
                             [("/x", StatusCode.OK), ("/x", StatusCode.ERROR),
                              ("/y", StatusCode.UNDEFINED),
                              ("/x", StatusCode.MAINTENANCE)])
            # what it had is beside the live files as .bak
            mine = json.loads(state.path(MAINTENANCE_FILE + BACKUP_SUFFIX).read_text())
            self.assertEqual(list(mine["nodes"]), ["/y"])
            log = json.loads(state.path(EVENTS_FILE + BACKUP_SUFFIX).read_text())
            self.assertEqual([raw["path"] for raw in log["events"]], ["/y"])
            # nothing was sent back this interval, and one save of each follows
            # once each changes
            self.assertEqual(store.saved, [])
            self.tree.set_maintenance("/y", "again", expires_at=_far(), set_by="bob")
            state.flush()
            self.assertEqual([name for name, _ in store.saved],
                             [EVENTS_FILE, MAINTENANCE_FILE])
            self.assertEqual(state.lines(), ())
            self.assertIn(f"{EVENTS_FILE}{BACKUP_SUFFIX}", state.report())
            self.assertIn(f"{MAINTENANCE_FILE}{BACKUP_SUFFIX}", state.report())

    def test_the_successor_of_a_dead_holder_continues_with_its_own_state(self):
        store = _TakeoverStore(self._written_by_the_holder())
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600)
            self._app._restore_state(_Roots("/x", "/y"), state)  # type: ignore[arg-type]
            self.assertEqual(self.tree.maintenance_entry("/x").reason, "theirs")
            self.tree.set_maintenance("/y", "mine", expires_at=_far(), set_by="bob")
            state.flush()      # the first interval it takes; nothing changed
            self.assertEqual(store.asked, 1)
            self.assertEqual(self.tree.maintenance_entry("/y").reason, "mine")
            self.assertFalse(state.path(MAINTENANCE_FILE + BACKUP_SUFFIX).exists())
            self.assertEqual([name for name, _ in store.saved],
                             [EVENTS_FILE, MAINTENANCE_FILE])
            self.assertEqual(state.lines(), ())


if __name__ == "__main__":
    unittest.main()
