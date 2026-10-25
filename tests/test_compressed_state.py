"""The state compressed and stamped, and the keeper in two cadences (ADR-0134).

Written from the record's sentences, decision by decision: the event log and the
series are compact JSON under gzip at level 1 with ``mtime=0``, under names of their
own, and the pins stay plain (1); ``events.json`` and ``series.json`` are retired
names that nothing reads and that a start and a takeover say so of (2);
a compressed copy that does not decode is a file that cannot be read, wherever it
is read (3); every file the layer writes carries its generation, and the count
moves with the content and never alone (4); at a start a local copy newer by the
same writer, written holding, wins over the store's (5); and the keeper takes the
pins at the next scheduler tick and the observed state every ``keeper_interval``
while nobody stands by, every interval while anyone does, and at once at a flip, a
stop and the flush after an action (6).
"""
from __future__ import annotations

import gzip
import json
import tempfile
import zlib
from pathlib import Path
from typing import Any
from unittest import TestCase

from little_sister.codes import StatusCode
from little_sister.keeper import forget_keeper, register_keeper
from little_sister.pins import PinStore, PinTables
from little_sister.state import (
    BACKUP_SUFFIX,
    EVENTS_FILE,
    GENERATION,
    PINS_FILE,
    SERIES_FILE,
    StateLayer,
)
from little_sister.tree import StatusTree
from tests.state_files import decoded, encoded, on_disk, tables
from tests.test_keeper import _LeaseStore, _Store, _TakeoverStore

#: Two writers' marks, as two processes would have them (ADR-0074).
A = "web-1:4711:20261022T081500Z:2b7de044"
B = "web-1:4712:20261022T090000Z:9c1f00aa"


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Cadenced(_TakeoverStore):
    """A keeper with the two answers ADR-0134 adds: ``push`` between its ticks, and
    ``standing_by`` — ``watched`` is what it answers next."""

    def __init__(self, held: dict[str, bytes] | None = None) -> None:
        super().__init__(held)
        self.pushed: list[tuple[str, bytes]] = []
        self.raise_on_push: dict[str, Exception] = {}
        self.watched = False
        self.raise_on_standing_by: Exception | None = None

    def push(self, name: str, data: bytes) -> None:
        if name in self.raise_on_push:
            raise self.raise_on_push[name]
        self.pushed.append((name, data))
        self.held[name] = data

    def standing_by(self) -> bool:
        if self.raise_on_standing_by is not None:
            raise self.raise_on_standing_by
        return self.watched


class _Loading(_Store):
    """A keeper that records every name it was asked to load — what the S3 keeper
    notes a token for."""

    def __init__(self, held: dict[str, bytes] | None = None) -> None:
        super().__init__(held)
        self.loaded: list[str] = []

    def load(self, name: str) -> bytes | None:
        self.loaded.append(name)
        return super().load(name)


def _stamped(payload: dict[str, Any], writer: str, count: int,
             held: bool) -> dict[str, Any]:
    return {**payload, GENERATION: {"writer": writer, "count": count, "held": held}}


class _Test(TestCase):
    def setUp(self) -> None:
        forget_keeper()
        self.addCleanup(forget_keeper)

    def _line(self, state: StateLayer, slug: str):
        found = [line for line in state.lines() if line.slug == slug]
        self.assertEqual(len(found), 1, [line.slug for line in state.lines()])
        return found[0]


class TheFilesTests(_Test):
    """Decision 1: the name says the encoding."""

    def test_the_log_and_the_series_are_compact_json_under_gzip_at_level_one(self):
        log, series = {"events": [{"path": "/x"}], "nodes": {}}, {"series": []}
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.keep(EVENTS_FILE, lambda: log)
            state.keep(SERIES_FILE, lambda: series)
            state.flush()
            for name, payload in ((EVENTS_FILE, log), (SERIES_FILE, series)):
                with self.subTest(name=name):
                    data = state.path(name).read_bytes()
                    text = json.dumps(_stamped(payload, A, 1, True),
                                      separators=(",", ":"), sort_keys=True)
                    # gzip at level 1 with mtime 0, byte for byte: the header's
                    # four bytes of time are nought, its extra flag says fastest
                    self.assertEqual(data, gzip.compress(text.encode(),
                                                         compresslevel=1, mtime=0))
                    self.assertEqual(data[:2], b"\x1f\x8b")
                    self.assertEqual(data[4:8], b"\x00\x00\x00\x00")
                    self.assertEqual(data[8], 4)
                    # reading one by hand is gzip -dc
                    self.assertEqual(gzip.decompress(data).decode(), text)

    def test_the_same_state_gives_the_same_bytes(self):
        with tempfile.TemporaryDirectory() as one, \
                tempfile.TemporaryDirectory() as two:
            files = []
            for directory in (one, two):
                state = StateLayer(directory, writer=A)
                state.keep(SERIES_FILE, lambda: {"series": [{"b": 2, "a": 1}]})
                state.flush()
                files.append(state.path(SERIES_FILE).read_bytes())
            self.assertEqual(files[0], files[1])

    def test_the_pins_stay_plain_json_under_their_name(self):
        pins = {"nodes": {}, "entries": {}}
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.write(PINS_FILE, pins)
            self.assertEqual(state.path(PINS_FILE).read_text(),
                             json.dumps(_stamped(pins, A, 1, True), indent=2,
                                        sort_keys=True))

    def test_every_restore_path_reads_the_compressed_files_alike(self):
        """The start, a takeover and *take the backups* hand the same tables."""
        log = {"events": ["theirs"]}
        taken: list[object] = []
        store = _TakeoverStore({EVENTS_FILE: encoded(EVENTS_FILE, log)})
        store.changed = [EVENTS_FILE]
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.restore_from_keeper()
            self.assertEqual(state.read(EVENTS_FILE), log)      # the start
            state.keep(EVENTS_FILE, lambda: {"events": ["mine"]},
                       restore=taken.append)
            store.wanted = False
            state.flush()
            store.wanted = True
            state.flush()                                       # the takeover
            state.path(EVENTS_FILE + BACKUP_SUFFIX).write_bytes(
                encoded(EVENTS_FILE, {"events": ["backed up"]}))
            state.take_stock()
            state.take_backups()                                # the way back
            self.assertEqual(taken, [log, {"events": ["backed up"]}])


class GenerationTests(_Test):
    """Decision 4: a generation in every file the layer writes."""

    def test_every_file_the_layer_writes_carries_one_beside_its_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.write(PINS_FILE, {"nodes": {}})
            state.keep(EVENTS_FILE, lambda: {"events": []})
            state.keep(SERIES_FILE, lambda: {"series": []})
            state.flush()
            for name in (PINS_FILE, EVENTS_FILE, SERIES_FILE):
                with self.subTest(name=name):
                    whole = decoded(name, state.path(name).read_bytes())
                    # no keeper registered: what the layer writes is held
                    self.assertEqual(whole[GENERATION],
                                     {"writer": A, "count": 1, "held": True})

    def test_a_reader_and_a_restore_are_handed_the_tables_without_it(self):
        taken: list[object] = []
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.restore_with(PINS_FILE, taken.append)
            state.write(PINS_FILE, {"nodes": {}, "entries": {}})
            self.assertEqual(state.read(PINS_FILE),
                             {"nodes": {}, "entries": {}})
            backup = state.path(PINS_FILE + BACKUP_SUFFIX)
            backup.write_bytes(state.path(PINS_FILE).read_bytes())
            state.take_stock()
            state.take_backups()
            self.assertEqual(taken, [{"nodes": {}, "entries": {}}])

    def test_the_pins_reader_takes_its_list_by_name_beside_the_stamp(self):
        # it takes the list by name and passes over the key: a stamp wrapped
        # around it would have cost the pins of a file a reader is handed whole
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.write(PINS_FILE, {"pins": []})
            whole = decoded(PINS_FILE,
                            state.path(PINS_FILE).read_bytes())
            self.assertIn(GENERATION, whole)
            self.assertEqual(PinStore.tables(whole), PinTables({}, {}, {}, {}))

    def test_the_count_is_this_writers_writes_of_that_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            for number in (1, 2, 3):
                state.write(PINS_FILE, {"nodes": {"n": number}})
            state.keep(EVENTS_FILE, lambda: {"events": []})
            state.flush()
            counts = {name: decoded(name, state.path(name).read_bytes())
                      [GENERATION]["count"] for name in (PINS_FILE,
                                                         EVENTS_FILE)}
            self.assertEqual(counts, {PINS_FILE: 3, EVENTS_FILE: 1})

    def test_the_count_moves_with_the_content_and_never_alone(self):
        """An unchanged state is not rewritten to move a count — the same inode,
        since every real write lands a new one — whether it is kept or written
        through, and whatever its generation would say now."""
        store = _LeaseStore()
        register_keeper("s3", store)
        log = {"events": [1]}
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.keep(EVENTS_FILE, lambda: log)
            state.write(PINS_FILE, {"nodes": {}})
            state.flush()                  # a start's first write: held false
            inodes = {name: state.path(name).stat().st_ino
                      for name in (EVENTS_FILE, PINS_FILE)}
            state.flush()                  # the keeper took saves; nothing changed
            state.write(PINS_FILE, {"nodes": {}})
            self.assertEqual({name: state.path(name).stat().st_ino
                              for name in inodes}, inodes)
            self.assertEqual(decoded(EVENTS_FILE, state.path(EVENTS_FILE)
                                     .read_bytes())[GENERATION],
                             {"writer": A, "count": 1, "held": False})
            log["events"].append(2)
            state.flush()
            self.assertEqual(decoded(EVENTS_FILE, state.path(EVENTS_FILE)
                                     .read_bytes())[GENERATION],
                             {"writer": A, "count": 2, "held": True})

    def test_held_is_what_the_keeper_answered_the_interval_before(self):
        store = _LeaseStore()
        register_keeper("s3", store)
        log = {"events": [0]}

        def held_after_a_change() -> bool:
            log["events"].append(len(log["events"]))
            state.flush()
            stamp = decoded(EVENTS_FILE, state.path(EVENTS_FILE).read_bytes())
            return bool(stamp[GENERATION]["held"])
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=A)
            state.keep(EVENTS_FILE, lambda: log)
            # a start's first write says false: written before the first tick
            self.assertFalse(held_after_a_change())
            self.assertTrue(held_after_a_change())
            store.wanted = False
            # written before the tick that demotes it, then as a standby
            self.assertTrue(held_after_a_change())
            self.assertFalse(held_after_a_change())


class RetiredNamesTests(_Test):
    """Decision 2: a clean break — the plain names are never read, and said so."""

    def setUp(self) -> None:
        super().setUp()
        from little_sister import app as app_module
        self._app = app_module
        self._original = app_module.status_tree
        self.tree = StatusTree()
        app_module.status_tree = self.tree

    def tearDown(self) -> None:
        self._app.status_tree = self._original

    def test_a_plain_copy_without_a_compressed_one_is_named_and_never_read(self):
        written = StatusTree()
        written.upsert("/x", StatusCode.OK)
        written.upsert("/x", StatusCode.ERROR, "down")
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=B)
            state.path("events.json").write_text(json.dumps(
                written.events_payload()))
            state.path("series.json").write_text('{"series": []}')
            with self.assertLogs(level="WARNING") as logged:
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            # never read: the history begins at the upgrade
            self.assertEqual(self.tree.recent_events(), ())
            for name, what in (("events.json", "the event log"),
                               ("series.json", "the series")):
                with self.subTest(name=name):
                    line = self._line(state, f"load.{name}")
                    self.assertIs(line.code, StatusCode.WARN)
                    self.assertIn(f"{name} is no longer read", line.text)
                    self.assertIn(f"keeps {what} as {name}.gz", line.text)
                    self.assertTrue(any(f"{name} is no longer read" in said
                                        and "WARNING" in said
                                        for said in logged.output))
            # it stands for the life of the process, the plain copy beside it
            self.tree.upsert("/x", StatusCode.OK)
            state.flush()
            self.assertTrue(state.path(EVENTS_FILE).exists())
            self.assertTrue(state.path("events.json").exists())
            self.assertIn("load.events.json", [line.slug for line in state.lines()])

    def test_beside_its_successor_a_plain_copy_says_nothing(self):
        # after a rollback and a roll-forward both are there, and the plain one
        # is only a rollback's
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=B)
            state.path("events.json").write_text('{"events": []}')
            state.path(EVENTS_FILE).write_bytes(encoded(EVENTS_FILE, {"events": []}))
            state.take_stock()
            self.assertEqual(state.lines(), ())

    def test_the_plain_copies_stay_and_ride_with_the_mirror(self):
        store = _Store({"events.json": b'{"events": []}'})
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=B)
            state.restore_from_keeper()
            with self.assertLogs(level="WARNING"):
                state.take_stock()
            state.keep(EVENTS_FILE, lambda: {"events": []})
            state.flush()
            # nothing sent back what arrived; the new name went up beside it
            self.assertEqual([name for name, _ in store.saved], [EVENTS_FILE])
            self.assertEqual(sorted(store.held), ["events.json", EVENTS_FILE])

    def test_a_takeover_that_adopts_one_writes_it_in_place_under_the_same_line(self):
        plain = b'{"events": []}'
        store = _TakeoverStore({"events.json": plain})
        store.changed = ["events.json"]
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600, writer=B)
            store.wanted = False
            state.flush()
            store.wanted = True
            with self.assertLogs(level="WARNING"):
                state.flush()
            self.assertEqual(state.path("events.json").read_bytes(), plain)
            line = self._line(state, "load.events.json")
            self.assertIs(line.code, StatusCode.WARN)
            self.assertIn("events.json is no longer read", line.text)
            self.assertNotIn("until a restart", line.text)


class _Roots:
    def __init__(self, *roots: str) -> None:
        self._roots = list(roots)

    def check_roots(self) -> list[str]:
        return self._roots


def _undecodable() -> dict[str, tuple[bytes, str]]:
    """A compressed copy that does not decode, each way decision 3 names, with the
    error Python's gzip raises for it — checked here, so that each case is what its
    name says before any test leans on it."""
    whole = gzip.compress(json.dumps({"events": [{"n": n} for n in range(200)]})
                          .encode(), compresslevel=1, mtime=0)
    damaged = bytearray(whole)
    damaged[len(whole) // 2] ^= 0xFF          # inside the deflate stream
    crc = bytearray(whole)
    crc[-6] ^= 0xFF                           # inside the trailer's CRC
    cases = {
        "not gzip": (b'{"events": []}', "BadGzipFile: Not a gzipped file"),
        "cut short": (whole[:len(whole) // 2], "EOFError"),
        "damaged": (bytes(damaged), "error: Error -3 while decompressing"),
        "a CRC that disagrees": (bytes(crc), "CRC check failed"),
        "not JSON inside": (gzip.compress(b"{torn"), "it is not JSON"),
    }
    raised: dict[str, type[BaseException]] = {
        "not gzip": gzip.BadGzipFile, "cut short": EOFError,
        "damaged": zlib.error, "a CRC that disagrees": gzip.BadGzipFile}
    for case, kind in raised.items():
        try:
            gzip.decompress(cases[case][0])
        except kind:
            continue
        raise AssertionError(f"{case}: decompressed without {kind.__name__}")
    return cases


class UndecodableTests(_Test):
    """Decision 3: a compressed copy that does not decode is a file that cannot be
    read, wherever it is read."""

    def test_at_a_start_it_is_the_error_line_and_the_state_starts_empty(self):
        for case, (data, said) in _undecodable().items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                state = StateLayer(directory, writer=A)
                state.path(EVENTS_FILE).write_bytes(data)
                with self.assertLogs(level="ERROR"):
                    self.assertIsNone(state.read(EVENTS_FILE))
                line = self._line(state, f"load.{EVENTS_FILE}")
                self.assertIs(line.code, StatusCode.ERROR)
                self.assertIn("could not be loaded at startup", line.text)
                self.assertIn(said, line.text)

    def test_at_a_takeover_the_adoption_is_refused_and_held_out_of_the_mirror(self):
        for case, (data, _said) in _undecodable().items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                forget_keeper()
                store = _TakeoverStore({EVENTS_FILE: data})
                store.changed = [EVENTS_FILE]
                register_keeper("s3", store)
                held = {"events": ["mine"]}
                state = StateLayer(directory, interval_seconds=3600, writer=A)
                state.keep(EVENTS_FILE, lambda held=held: held, restore=held.update)
                store.wanted = False
                state.flush()
                store.wanted = True
                with self.assertLogs(level="ERROR"):
                    state.flush()
                self.assertEqual(held, {"events": ["mine"]})
                self.assertEqual(on_disk(state.path(EVENTS_FILE)), held)
                line = self._line(state, f"load.{EVENTS_FILE}")
                self.assertIs(line.code, StatusCode.ERROR)
                self.assertIn("could not be adopted", line.text)
                self.assertIn("held out of the mirror", line.text)
                self.assertEqual(store.saved, [])

    def test_at_take_the_backups_it_is_refused_and_what_is_live_stands(self):
        for case, (data, _said) in _undecodable().items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                taken: list[object] = []
                state = StateLayer(directory, writer=A)
                state.keep(EVENTS_FILE, lambda: {"events": ["live"]},
                           restore=taken.append)
                state.flush()
                state.path(EVENTS_FILE + BACKUP_SUFFIX).write_bytes(data)
                state.take_stock()
                with self.assertLogs(level="ERROR"):
                    said = state.take_backups()
                self.assertIn(f"could not take the backup of {EVENTS_FILE}", said)
                self.assertEqual(taken, [])
                self.assertEqual(on_disk(state.path(EVENTS_FILE)),
                                 {"events": ["live"]})


class NewestCopyAtAStartTests(_Test):
    """Decision 5: the store's copy wins at a start, but for a local copy newer by
    the same writer, written holding."""

    def _restored(self, mine: dict[str, Any] | None, theirs: dict[str, Any],
                  name: str = EVENTS_FILE) -> tuple[bytes, bytes, StateLayer,
                                                    _Loading]:
        store = _Loading({name: encoded(name, theirs)})
        register_keeper("s3", store)
        directory = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(directory))
        state = StateLayer(directory, writer=B)
        if mine is not None:
            state.path(name).write_bytes(encoded(name, mine))
        with self.assertLogs(level="INFO"):
            state.restore_from_keeper()
        return (state.path(name).read_bytes(), store.held[name], state, store)

    def test_a_local_copy_by_the_same_writer_later_and_held_stays(self):
        mine = _stamped({"events": ["newer"]}, A, 5, True)
        theirs = _stamped({"events": ["older"]}, A, 3, True)
        local, _store_copy, state, store = self._restored(mine, theirs)
        self.assertEqual(tables(EVENTS_FILE, local), {"events": ["newer"]})
        # the store's copy was fetched all the same — a keeper notes its token
        self.assertEqual(store.loaded, [EVENTS_FILE])
        self.assertEqual(state.lines(), ())

    def test_any_other_local_copy_gives_way_to_the_stores(self):
        theirs = _stamped({"events": ["the store's"]}, A, 3, True)
        for case, mine in {
            "written as a standby": _stamped({"events": ["mine"]}, A, 5, False),
            "another writer's": _stamped({"events": ["mine"]}, B, 9, True),
            "the same count": _stamped({"events": ["mine"]}, A, 3, True),
            "an older count": _stamped({"events": ["mine"]}, A, 2, True),
            "no generation": {"events": ["mine"]},
        }.items():
            with self.subTest(case=case):
                forget_keeper()
                local, store_copy, _state, _store = self._restored(mine, theirs)
                self.assertEqual(local, store_copy)

    def test_a_store_copy_without_a_generation_wins_as_it_always_did(self):
        mine = _stamped({"events": ["mine"]}, A, 5, True)
        local, store_copy, _state, _store = self._restored(mine,
                                                           {"events": ["theirs"]})
        self.assertEqual(local, store_copy)

    def test_the_pins_follow_the_same_rule(self):
        mine = _stamped({"nodes": {"/x": "set after the upload"}}, A, 8, True)
        theirs = _stamped({"nodes": {}}, A, 7, True)
        local, _store_copy, _state, _store = self._restored(mine, theirs,
                                                            PINS_FILE)
        self.assertEqual(tables(PINS_FILE, local)["nodes"],
                         {"/x": "set after the upload"})

    def test_a_file_the_layer_does_not_write_keeps_the_rule(self):
        # known by its name, never by its bytes: a package's file is not read for a
        # generation, even one whose bytes would look stamped and newer
        name = "store.sqlite3"
        mine = json.dumps(_stamped({}, A, 5, True)).encode()
        theirs = json.dumps(_stamped({}, A, 3, True)).encode()
        store = _Loading({name: theirs})
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=B)
            state.path(name).write_bytes(mine)
            state.restore_from_keeper()
            self.assertEqual(state.path(name).read_bytes(), theirs)

    def test_the_flip_after_it_names_nothing_and_sends_the_newer_copy_up(self):
        """The dead worker's successor stands by until the lease lapses, then takes
        it; its keeper noted the store's token at the load, so it names nothing,
        and the flip's save sends what the dead worker wrote last."""
        theirs = encoded(EVENTS_FILE, _stamped({"events": ["older"]}, A, 3, True))
        store = _TakeoverStore({EVENTS_FILE: theirs})
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, writer=B)
            state.path(EVENTS_FILE).write_bytes(encoded(
                EVENTS_FILE, _stamped({"events": ["newer"]}, A, 5, True)))
            state.restore_from_keeper()
            log = state.read(EVENTS_FILE)
            state.keep(EVENTS_FILE, lambda: log, restore=log.update)
            store.wanted = True
            state.flush()
            self.assertEqual(store.asked, 1)
            self.assertEqual(tables(EVENTS_FILE, store.held[EVENTS_FILE]),
                             {"events": ["newer"]})

    def test_a_second_end_before_the_lease_is_taken_falls_back_to_the_store(self):
        # the successor writes as a standby meanwhile, so the next start meets
        # another writer's copy, not held, and takes the store's
        theirs = encoded(EVENTS_FILE, _stamped({"events": ["the store's"]}, A, 3,
                                               True))
        with tempfile.TemporaryDirectory() as directory:
            store = _LeaseStore()
            store.held[EVENTS_FILE] = theirs
            store.wanted = False
            register_keeper("s3", store)
            successor = StateLayer(directory, writer=B)
            successor.keep(EVENTS_FILE, lambda: {"events": ["the successor's"]})
            successor.flush()
            self.assertFalse(decoded(EVENTS_FILE, successor.path(EVENTS_FILE)
                                     .read_bytes())[GENERATION]["held"])
            third = StateLayer(directory, writer="web-1:4713:t:c")
            third.restore_from_keeper()
            self.assertEqual(third.path(EVENTS_FILE).read_bytes(), theirs)


class TwoCadencesTests(_Test):
    """Decision 6: the pins as they change; the observed state every
    ``keeper_interval`` while nobody stands by, every interval while anyone does,
    and at once at a flip, a stop and the flush after an action."""

    def _holder(self, directory: str, store: _TakeoverStore,
                clock: _Clock) -> StateLayer:
        """An instance that took its keeper's first interval — the flip, whose save
        sent the observed state at once — with what that sent cleared away."""
        register_keeper("s3", store)
        state = StateLayer(directory, interval_seconds=60,
                           keeper_interval_seconds=900, clock=clock, writer=A)
        self.log: dict[str, list[int]] = {"events": [0]}
        state.keep(EVENTS_FILE, lambda: self.log)
        state.tick()                       # the first tick starts the interval
        clock.now += 60
        self.assertTrue(state.tick())      # the flip
        self.assertEqual(self._sent(store), [EVENTS_FILE])
        store.saved.clear()
        return state

    @staticmethod
    def _sent(store: _TakeoverStore) -> list[str]:
        return [name for name, _data in store.saved]

    def _a_minute_with_a_change(self, state: StateLayer, clock: _Clock) -> None:
        self.log["events"].append(len(self.log["events"]))
        clock.now += 60
        self.assertTrue(state.tick())

    def test_a_pin_goes_to_the_store_at_the_next_scheduler_tick(self):
        store, clock = _Cadenced(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            state.write(PINS_FILE, {"nodes": {"/x": "pinned"}})
            self.assertEqual(store.pushed, [])   # the disk at once, the store next
            clock.now += 1                       # a scheduler tick, no interval
            self.assertFalse(state.tick())
            self.assertEqual(store.pushed, [(PINS_FILE, state.path(
                PINS_FILE).read_bytes())])
            self.assertEqual(store.saved, [])
            clock.now += 59                      # and the interval sends it no more
            state.tick()
            self.assertNotIn(PINS_FILE, self._sent(store))

    def test_a_standby_pushes_nothing(self):
        store, clock = _Cadenced(), _Clock()
        store.wanted = False
        register_keeper("s3", store)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=60, clock=clock, writer=A)
            state.tick()
            clock.now += 60
            state.tick()
            state.write(PINS_FILE, {"nodes": {"/x": "pinned"}})
            clock.now += 1
            state.tick()
            self.assertEqual((store.pushed, store.saved), ([], []))

    def test_a_keeper_without_push_is_handed_the_pin_with_the_interval(self):
        store, clock = _TakeoverStore(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            state.write(PINS_FILE, {"nodes": {"/x": "pinned"}})
            clock.now += 1
            state.tick()
            self.assertEqual(store.saved, [])
            clock.now += 59
            state.tick()
            self.assertEqual(self._sent(store), [PINS_FILE])

    def test_a_push_that_raises_is_the_save_line_and_the_interval_sends_it(self):
        store, clock = _Cadenced(), _Clock()
        store.raise_on_push = {PINS_FILE: ConnectionError("lease refused")}
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            state.write(PINS_FILE, {"nodes": {"/x": "pinned"}})
            clock.now += 1
            with self.assertLogs(level="WARNING"):
                state.tick()
            line = self._line(state, f"keeper.save.{PINS_FILE}")
            self.assertIs(line.code, StatusCode.WARN)
            self.assertIn("lease refused", line.text)
            clock.now += 59
            state.tick()
            self.assertEqual(self._sent(store), [PINS_FILE])
            self.assertEqual(state.lines(), ())

    def test_the_observed_state_waits_its_interval_while_nobody_stands_by(self):
        store, clock = _Cadenced(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            ticks = len(store.ticks)
            for minute in range(1, 15):          # up to 840 s after the flip's send
                self._a_minute_with_a_change(state, clock)
                # the disk keeps state_interval
                self.assertEqual(on_disk(state.path(EVENTS_FILE))["events"][-1],
                                 minute)
            self.assertEqual(store.saved, [])
            # the keeper's tick — the heartbeat — still came every interval
            self.assertEqual(len(store.ticks), ticks + 14)
            self._a_minute_with_a_change(state, clock)   # 900 s: due
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            self.assertEqual(tables(EVENTS_FILE, store.held[EVENTS_FILE]),
                             self.log)

    def test_the_interval_counts_from_each_send(self):
        store, clock = _Cadenced(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            for _minute in range(15):
                self._a_minute_with_a_change(state, clock)
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            for _minute in range(14):
                self._a_minute_with_a_change(state, clock)
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            self._a_minute_with_a_change(state, clock)
            self.assertEqual(self._sent(store), [EVENTS_FILE, EVENTS_FILE])

    def test_every_interval_while_another_instance_stands_by(self):
        store, clock = _Cadenced(), _Clock()
        store.watched = True
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            for _minute in range(3):
                self._a_minute_with_a_change(state, clock)
            self.assertEqual(self._sent(store), [EVENTS_FILE] * 3)

    def test_a_keeper_without_standing_by_counts_as_always_watched(self):
        store, clock = _TakeoverStore(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            for _minute in range(3):
                self._a_minute_with_a_change(state, clock)
            self.assertEqual(self._sent(store), [EVENTS_FILE] * 3)

    def test_a_standing_by_that_raises_counts_as_watched_and_is_a_line(self):
        store, clock = _Cadenced(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            store.raise_on_standing_by = TimeoutError("no listing")
            with self.assertLogs(level="WARNING"):
                self._a_minute_with_a_change(state, clock)
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            line = self._line(state, "keeper.standing_by")
            self.assertIs(line.code, StatusCode.WARN)
            self.assertIn("no listing", line.text)
            store.raise_on_standing_by = None
            self._a_minute_with_a_change(state, clock)
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            self.assertEqual(state.lines(), ())

    def test_the_flip_sends_the_observed_state_at_once(self):
        store, clock = _Cadenced(), _Clock()
        store.wanted = False
        register_keeper("s3", store)
        log = {"events": [0]}
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=60,
                               keeper_interval_seconds=900, clock=clock, writer=A)
            state.keep(EVENTS_FILE, lambda: log)
            state.tick()
            for minute in range(1, 4):           # standing by
                log["events"].append(minute)
                clock.now += 60
                state.tick()
            self.assertEqual(store.saved, [])
            store.wanted = True
            log["events"].append(4)
            clock.now += 60
            state.tick()
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            self.assertEqual(tables(EVENTS_FILE, store.held[EVENTS_FILE]), log)

    def test_a_holder_that_takes_the_lease_back_sends_at_once(self):
        """The flip forces the send, not merely an unsent file: a holder demoted
        and back within ``keeper_interval`` of its last send sends at its flip."""
        store, clock = _Cadenced(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            store.wanted = False
            self._a_minute_with_a_change(state, clock)       # demoted
            store.wanted = True
            self._a_minute_with_a_change(state, clock)       # 120 s on: the flip
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            self.assertEqual(tables(EVENTS_FILE, store.held[EVENTS_FILE]), self.log)

    def test_the_stop_sends_everything_before_the_close(self):
        store, clock = _Cadenced(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            self._a_minute_with_a_change(state, clock)
            self.assertEqual(store.saved, [])
            state.shutdown()
            self.assertEqual(self._sent(store), [EVENTS_FILE])
            self.assertEqual(tables(EVENTS_FILE, store.held[EVENTS_FILE]), self.log)
            self.assertEqual(store.closed, 1)

    def test_the_flush_after_an_action_sends_everything(self):
        # an action's flush owes the store what the action changed now (ADR-0076)
        store, clock = _Cadenced(), _Clock()
        with tempfile.TemporaryDirectory() as directory:
            state = self._holder(directory, store, clock)
            self._a_minute_with_a_change(state, clock)
            self.assertEqual(store.saved, [])
            self.assertTrue(state.flush())
            self.assertEqual(self._sent(store), [EVENTS_FILE])

    def test_without_a_keeper_the_files_are_written_as_before(self):
        clock = _Clock()
        log = {"events": [0]}
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(Path(directory), interval_seconds=60,
                               keeper_interval_seconds=900, clock=clock, writer=A)
            state.keep(EVENTS_FILE, lambda: log)
            state.tick()
            for minute in range(1, 3):
                log["events"].append(minute)
                clock.now += 60
                self.assertTrue(state.tick())
                self.assertEqual(on_disk(state.path(EVENTS_FILE)), log)
