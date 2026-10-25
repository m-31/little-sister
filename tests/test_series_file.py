"""The series file (ADR-0087): ``series.json.gz`` joins the state writer, so a
restarted instance shows yesterday's records, a keeper carries them with the rest,
and a file of another shape is a load failure and never a refusal to start.

The claims are ADR-0071's for every kept file, said of this one: written on the
interval and at shutdown, read back whole at startup or not at all, adopted through
the same ``restore`` a takeover and *take the backups* use — and, the part only a
series has, met by this configuration's retention on the first tick after it was
read.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase

from little_sister import app as app_module
from little_sister.checks import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.state import BACKUP_SUFFIX, SERIES_FILE, StateLayer
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.state_files import encoded, on_disk

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _record(minutes: int, identity: str = "", code: StatusCode | None = None,
            texts: tuple[str, ...] = (), **data: Any) -> SeriesRecord:
    return SeriesRecord(data, _at(minutes), identity, code, texts)


def _as_read(record: SeriesRecord) -> tuple[Any, ...]:
    """Everything a kept reading carries — what a round trip must give back."""
    return (dict(record.data), record.observed_at, record.identity, record.code,
            record.texts, record.state)


def _through_the_file(store: MemoryStore) -> MemoryStore:
    """The store as a restarted process sees it: its payload through JSON, as the
    state layer writes and reads it, into a fresh store."""
    restored = MemoryStore()
    restored.restore(json.loads(json.dumps(store.payload(), indent=2,
                                           sort_keys=True)))
    return restored


class _Probe(Check):
    """A check that reads one host and says what the test tells it to."""

    type_name = "probe"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.load = 0.4

    def measure(self) -> Sequence[Measurement]:
        return (Measurement(record={"load": self.load}),)

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        load = measurements[0].record["load"]
        return CheckResult(StatusCode.OK if load < 1 else StatusCode.WARN,
                           [f"load {load}"])


class RoundTripTests(TestCase):
    """What the payload holds is what a restore gives back — every field, and the
    order."""

    KEY = SeriesKey("batch", "/jobs/nightly", "export")
    OTHER = SeriesKey("http", "/web", "https://example.org")
    STANDING = SeriesKey("aws", "/aws/ec2", "i-0abc")

    def test_every_field_of_every_record_comes_back(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, "run-7", StatusCode.ERROR,
                                    ("run 7: failed after 8m",),
                                    at="2026-09-19T03:00:00Z", size_gb=1.5),
                  keep=5)
        store.add(self.KEY, _record(1, "run-8", StatusCode.OK, ("run 8: passed",),
                                    at="2026-09-20T03:00:00Z", size_gb=1.6),
                  keep=5)
        store.add(self.OTHER, _record(2, "", None, (), response_ms=412), keep=5)
        store.add(self.STANDING, SeriesRecord({"state": "stopped"}, _at(3),
                                              code=StatusCode.WARN,
                                              state="stopped"), keep=5)
        restored = _through_the_file(store)
        for key in (self.KEY, self.OTHER, self.STANDING):
            with self.subTest(key=key):
                self.assertEqual([_as_read(r) for r in restored.window(key)],
                                 [_as_read(r) for r in store.window(key)])

    def test_a_replaced_record_keeps_its_place_across_a_restart(self) -> None:
        # no time of its own: the place is where the record was first observed
        store = MemoryStore()
        store.add(self.KEY, _record(0, "run-40", seen=1), keep=5)
        store.add(self.KEY, _record(1, "run-41", seen=1), keep=5)
        store.add(self.KEY, _record(9, "run-40", seen=2), keep=5)
        restored = _through_the_file(store)
        window = restored.window(self.KEY)
        self.assertEqual([record.identity for record in window],
                         ["run-40", "run-41"])
        self.assertEqual((window[0].data["seen"], window[0].observed_at),
                         (2, _at(9)))

    def test_an_identity_still_replaces_after_a_restart(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, "run-40", state="running"), keep=5)
        restored = _through_the_file(store)
        restored.add(self.KEY, _record(7, "run-40", state="finished"), keep=5)
        record, = restored.window(self.KEY)
        self.assertEqual(record.data["state"], "finished")

    def test_a_state_still_continues_its_spell_after_a_restart(self) -> None:
        # and the spell keeps where it began, which only the file can tell
        store = MemoryStore()
        store.add(self.STANDING, SeriesRecord({"n": 1}, _at(0), state="running"),
                  keep=5)
        store.add(self.STANDING, SeriesRecord({"n": 2}, _at(4), state="running"),
                  keep=5)
        restored = _through_the_file(store)
        restored.add(self.STANDING, SeriesRecord({"n": 3}, _at(9), state="running"),
                     keep=5)
        record, = restored.window(self.STANDING)
        self.assertEqual((record.data["n"], record.observed_at), (3, _at(9)))
        item, = restored.payload()["series"][0]["records"]
        self.assertEqual(item["first_observed_at"], "2026-09-20T12:00:00Z")

    def test_a_state_is_written_only_where_a_reading_names_one(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, "run-7"), keep=5)
        store.add(self.STANDING, SeriesRecord({}, _at(0), state="running"), keep=5)
        written = {item["subject"]: item["records"][0]
                   for item in store.payload()["series"]}
        self.assertNotIn("state", written["export"])
        self.assertEqual(written["i-0abc"]["state"], "running")

    def test_the_weight_comes_back_with_the_records(self) -> None:
        store = MemoryStore()
        for minute in range(3):
            store.add(self.KEY, _record(minute, texts=("t",), n=minute), keep=5)
        self.assertEqual(_through_the_file(store).held(), store.held())

    def test_a_store_that_did_not_change_writes_the_same_text(self) -> None:
        store = MemoryStore()
        store.add(self.OTHER, _record(0, response_ms=412), keep=5)
        store.add(self.KEY, _record(0, n=1), keep=5)
        first = json.dumps(store.payload(), indent=2, sort_keys=True)
        self.assertEqual(json.dumps(store.payload(), indent=2, sort_keys=True),
                         first)

    def test_a_file_of_another_shape_is_refused_and_changes_nothing(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, n=1), keep=5)
        good = store.payload()
        record = good["series"][0]["records"][0]
        damaged = [
            {"events": []},
            {"series": [{"type": "batch", "mount": "/jobs/nightly"}]},
            {"series": [{**good["series"][0], "records": []}]},
            {"series": [good["series"][0], good["series"][0]]},
            {"series": [{**good["series"][0],
                         "records": [{**record, "code": "NOPE"}]}]},
            {"series": [{**good["series"][0],
                         "records": [{**record,
                                      "observed_at": "2026-09-20T12:00:00"}]}]},
            {"series": [{**good["series"][0],
                         "records": [{**record, "state": 7}]}]},
            {"series": [{**good["series"][0],
                         "records": [{**record, "identity": "run-7",
                                      "state": "running"}]}]},
        ]
        for payload in damaged:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                store.restore(payload)
            self.assertEqual(len(store.window(self.KEY)), 1)

    def test_a_time_utc_cannot_hold_is_refused_like_any_other_bad_time(self) -> None:
        # An offset can carry an instant at the edge of the calendar past it: the
        # first hour of the year 1 at +01:00 is the year 0 in UTC. The conversion
        # raised OverflowError, which no reader of the file catches.
        store = MemoryStore()
        store.add(self.KEY, _record(0, n=1), keep=5)
        good = store.payload()
        record = good["series"][0]["records"][0]
        for value in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:30:00-01:00"):
            payload = {"series": [{**good["series"][0],
                                   "records": [{**record, "observed_at": value}]}]}
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    store.restore(payload)
                self.assertIn(f".observed_at lies outside the years 1 to 9999 once "
                              f"it is read in UTC: {value!r}", str(caught.exception))
                self.assertEqual(len(store.window(self.KEY)), 1)


class RestartTests(TestCase):
    """The stage's *done when*: a restarted instance shows yesterday's records —
    through ``app._restore_series``, the state layer's own file discipline, and a
    fresh engine on the same configuration."""

    KEY = SeriesKey("probe", "/hosts/macmini", "macmini")

    def _engine(self, series_keep: int = 5) -> Engine:
        return Engine([_Probe(path="/hosts/macmini", subject="macmini",
                              series_keep=series_keep)], StatusTree())

    def test_a_restarted_instance_shows_yesterdays_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            yesterday = self._engine()
            app_module._restore_series(yesterday, state)
            yesterday.run_once()
            yesterday._scheduled[0].check.load = 1.5   # type: ignore[attr-defined]
            yesterday.run_once()
            state.flush()                  # the interval's write, or the last one
            kept = [_as_read(record) for record in yesterday.series.window(self.KEY)]

            today = self._engine()
            app_module._restore_series(today, StateLayer(directory))
            self.assertEqual([_as_read(r) for r in today.series.window(self.KEY)],
                             kept)
            self.assertEqual([record.code for record in today.series.window(
                self.KEY)], [StatusCode.OK, StatusCode.WARN])

    def test_this_process_keeps_writing_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            engine = self._engine()
            app_module._restore_series(engine, state)
            self.assertFalse(state.path(SERIES_FILE).exists())
            engine.run_once()
            state.flush()
            written = on_disk(state.path(SERIES_FILE))
            self.assertEqual([item["subject"] for item in written["series"]],
                             ["macmini"])

    def test_an_unreadable_file_starts_empty_and_is_a_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path(SERIES_FILE).parent.mkdir(parents=True, exist_ok=True)
            state.path(SERIES_FILE).write_bytes(
                encoded(SERIES_FILE, {"series": [{"torn": True}]}))
            engine = self._engine()
            with self.assertLogs(level="ERROR"):
                app_module._restore_series(engine, state)
            self.assertEqual(engine.series.held(), 0)
            (line,) = state.lines()
            self.assertEqual(line.slug, f"load.{SERIES_FILE}")
            # refused for its shape, past the decoding (ADR-0134)
            self.assertIn("does not name its type", line.text)

    def test_a_time_utc_cannot_hold_starts_empty_and_is_a_line_too(self) -> None:
        # The one damage that got past the load failure: startup catches the
        # refusal of a file, and this one was raised as OverflowError instead —
        # so the instance did not start, where the series should start empty.
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            store = MemoryStore()
            store.add(self.KEY, _record(0, load=0.4), keep=5)
            payload = store.payload()
            payload["series"][0]["records"][0]["observed_at"] = (
                "0001-01-01T00:00:00+01:00")
            state.path(SERIES_FILE).parent.mkdir(parents=True, exist_ok=True)
            state.path(SERIES_FILE).write_bytes(encoded(SERIES_FILE, payload))
            engine = self._engine()
            with self.assertLogs(level="ERROR"):
                app_module._restore_series(engine, state)
            self.assertEqual(engine.series.held(), 0)
            (line,) = state.lines()
            self.assertEqual(line.slug, f"load.{SERIES_FILE}")
            self.assertIn("outside the years 1 to 9999", line.text)

    def test_the_first_tick_meets_the_file_with_this_configurations_retention(
            self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            yesterday = MemoryStore()
            gone = SeriesKey("probe", "/hosts/retired", "retired")
            for minute in range(5):
                yesterday.add(self.KEY, _record(minute, n=minute), keep=5)
                yesterday.add(gone, _record(minute, n=minute), keep=5)
            state.write(SERIES_FILE, yesterday.payload())
            today = self._engine(series_keep=2)
            with self.assertLogs(level="INFO"):
                app_module._restore_series(today, state)
            self.assertEqual(len(today.series.window(gone)), 5)
            swept = today._sweep_series()
            assert swept is not None
            self.assertEqual([r.data["n"] for r in today.series.window(self.KEY)],
                             [3, 4])
            self.assertEqual((today.series.window(gone), swept.dropped),
                             ((), (gone,)))

    def test_a_backup_swapped_back_replaces_the_series(self) -> None:
        # the kept file is registered with its other direction (ADR-0077)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600)
            engine = self._engine()
            app_module._restore_series(engine, state)
            engine.run_once()
            state.flush()
            older = MemoryStore()
            older.add(self.KEY, _record(0, code=StatusCode.ERROR,
                                        texts=("unreachable",), load=None),
                      keep=5)
            backup = state.path(SERIES_FILE + BACKUP_SUFFIX)
            backup.write_bytes(encoded(SERIES_FILE, older.payload()))
            os.utime(backup, (1, 1))
            state.take_stock()
            state.take_backups()
            record, = engine.series.window(self.KEY)
            self.assertEqual((record.code, record.texts),
                             (StatusCode.ERROR, ("unreachable",)))
