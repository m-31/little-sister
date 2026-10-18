"""A series is read over the API as it stands (ADR-0106 decision 6, ADR-0122), read
against the records' sentences.

Two estates. One host read by two checks that share its node — its metrics and its
memory, as a Mac is — with a website mounted beneath it and a heartbeat file beside
that, whose series declares no measure: their kept readings are written into the store
the engine reads, at instants this file fixes. And a queue whose check keeps its own
state and a run of each job name, two of the job names on nodes of their own and two
sharing one, as three runs of the engine leave them.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.checks.file import FileFreshnessCheck
from little_sister.checks.http import HttpCheck
from little_sister.checks.ssh import HostMetricsCheck
from little_sister.checks.ssh.macos_memory import MacosMemoryCheck
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_subject_nodes import RUN_TIME, _Functions, _Queue

TOKEN = "secret-token"
JSON = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
#: What the server's clock reads while a test asks: after every kept reading.
NOW = T0 + timedelta(minutes=45)
HOST = "/hosts/alpha"
SITE = "https://www.example.org"

READING_FIELDS = {"at", "observed_at", "code", "texts", "identity", "state", "record"}


def stamp(moment: datetime) -> str:
    """An instant as the API spells one (ADR-0120): UTC, with a ``Z``."""
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def flatten(record: dict[str, Any], above: str = "") -> dict[str, Any]:
    """A record as a reader flattens it (ADR-0122 decision 4): the keys from the top
    down to each value, joined with ``.``."""
    found: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{above}.{key}" if above else str(key)
        if isinstance(value, dict):
            found.update(flatten(value, name))
        else:
            found[name] = value
    return found


def _host_reading(step: int, *, failed: bool = False) -> dict[str, Any]:
    if failed or step == 7:
        return {"exit_code": 255, "error": "ssh to alpha.example failed (exit 255): "
                "refused", "mem_pct": None, "cpu_pct": None, "load1": None,
                "load1_per_core": None, "ncpu": None, "disk_pct": None}
    return {"exit_code": 0, "mem_pct": 60 + step % 5, "mem_used_kb": 5_000_000,
            "mem_total_kb": 8_388_608, "cpu_pct": 10 + step, "load1": 0.4,
            "ncpu": 4, "load1_per_core": 0.1, "disk_pct": 51,
            "disk_avail_kb": 45_000_000, "disk_total_kb": 90_000_000,
            "disk_path": "/", "os": "Linux", "hostname": "alpha"}


def _mac_reading(step: int) -> dict[str, Any]:
    """A Mac's memory at one step. `sync` is a process the readings hold from the
    eleventh on: a key a window of the first few does not hold."""
    processes = {"mail": {"count": 1, "rss_kb": 400_000 + 1000 * step,
                          "elapsed_seconds": 60 * step}}
    if step >= 10:
        processes["sync"] = {"count": 2, "rss_kb": 90_000, "elapsed_seconds": 30}
    return {"exit_code": 0, "pressure_level": 1, "compressor_pct": 15 + step % 3,
            "swap_used_mb": 0, "swap_total_mb": 0, "processes": processes}


class _Read(TestCase):
    """What both estates share: the token, a session beside it, and the clock."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine,
                       app_module.api_tokens)
        self.addCleanup(self._restore)
        app_module.app.config["TESTING"] = True
        app_module.api_tokens = {"tester": TOKEN}
        for patch in (
                mock.patch("little_sister.config.config",
                           replace(app_module.config, timezone="Europe/Berlin",
                                   time_format="%Y-%m-%d %H:%M:%S")),
                mock.patch.object(app_module, "_now", lambda: NOW)):
            patch.start()
            self.addCleanup(patch.stop)
        #: A reader that holds the token and no session.
        self.client = app_module.app.test_client()

    def _restore(self) -> None:
        (app_module.status_tree, app_module.engine,
         app_module.api_tokens) = self._saved

    def _signed_in(self) -> Any:
        """A browser with a session and no token."""
        browser = app_module.app.test_client()
        browser.post("/login", data={"username": "pan", "password": "12345678"})
        return browser

    def _answer(self, url: str) -> dict[str, Any]:
        response = self.client.get(url, headers=JSON)
        self.assertEqual(response.status_code, 200, url)
        self.assertEqual(response.mimetype, "application/json", url)
        body: dict[str, Any] = response.get_json()
        return body

    def _series(self, url: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = self._answer(url)["series"]
        return found

    @staticmethod
    def _keys(series: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
        """Each series by its key, in the answer's order."""
        return [(one["key"]["type"], one["key"]["mount"], one["key"]["subject"])
                for one in series]

    def _refused(self, url: str, status: int, **headers: str) -> dict[str, Any]:
        """A refusal: its status, as Problem JSON (ADR-0080 decision 8)."""
        response = self.client.get(url, headers={**JSON, **headers})
        self.assertEqual(response.status_code, status, url)
        self.assertEqual(response.mimetype, "application/problem+json", url)
        body: dict[str, Any] = json.loads(response.get_data(as_text=True))
        self.assertEqual(body["status"], status)
        return body


class HostEstate(_Read):
    """The host, its website and its heartbeat."""

    def setUp(self) -> None:
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self._deploy()

    def _deploy(self, *, host: dict[str, Any] | None = None, failed: bool = False,
                idle: bool = False, mac: Any = _mac_reading,
                memory_first: bool = False) -> None:
        base = Path(self.directory.name)
        (base / "metrics.sh").write_text("echo hi\n")
        metrics = HostMetricsCheck.from_config(
            {"type": "host-metrics", "path": HOST, "host": "alpha.example",
             "script": "metrics.sh", "frequency": "2m", "series_keep": 720,
             **(host or {})}, base)
        memory = MacosMemoryCheck.from_config(
            {"type": "macos-memory", "path": HOST, "host": "alpha.example",
             "script": "metrics.sh", "frequency": "2m", "series_keep": 720,
             "processes": [{"name": "mail", "pattern": "Mail.app"}]}, base)
        site = HttpCheck.from_config(
            {"type": "http", "path": f"{HOST}/web", "url": SITE, "frequency": "3m",
             "series_keep": 480}, base)
        beat = FileFreshnessCheck.from_config(
            {"type": "file", "path": f"{HOST}/beat", "file": "/tmp/beat",
             "max_age_error": "5m", "frequency": "3m", "series_keep": 480}, base)
        checks = [metrics, memory, site, beat]
        if memory_first:
            # the order the configuration happens to load the two checks in
            checks = [memory, metrics, beat, site]
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        if idle:
            # a check that keeps a series and has read nothing yet
            checks.append(HttpCheck.from_config(
                {"type": "http", "path": f"{HOST}/idle", "url": f"{SITE}/idle",
                 "frequency": "3m", "series_keep": 480}, base))
            self.tree.upsert(f"{HOST}/idle", StatusCode.UNDEFINED)
        store = MemoryStore()
        for step in range(20):
            at = T0 + timedelta(minutes=2 * step)
            broke = failed or step == 7
            store.add(SeriesKey("host-metrics", HOST, "alpha.example"),
                      SeriesRecord(_host_reading(step, failed=failed), at,
                                   code=StatusCode.ERROR if broke else StatusCode.OK,
                                   texts=("unreachable",) if broke
                                   else ("memory fine", "disk fine")), keep=720)
            store.add(SeriesKey("macos-memory", HOST, "alpha.example"),
                      SeriesRecord(mac(step), at, code=StatusCode.OK,
                                   texts=("memory fine",)), keep=720)
        for step in range(10):
            at = T0 + timedelta(minutes=1 + 3 * step)
            store.add(SeriesKey("http", f"{HOST}/web", SITE),
                      SeriesRecord({"status": 200, "response_ms": 200 + step}, at,
                                   code=StatusCode.OK,
                                   texts=(f"HTTP 200 in {200 + step} ms",)),
                      keep=480)
            store.add(SeriesKey("file", f"{HOST}/beat", "/tmp/beat"),
                      SeriesRecord({"modified": {"at": "2026-09-26T14:00:00Z"}}, at,
                                   code=StatusCode.OK, texts=("fresh",)), keep=480)
        self.store = store
        app_module.engine = Engine(checks, self.tree, series=store)
        self.tree.upsert(HOST, StatusCode.UNDEFINED, frequency_seconds=120,
                         subject="alpha.example")
        for name in ("memory", "cpu", "load", "disk", "ssh", "pressure",
                     "compressor", "swap", "processes/mail", "processes/sync"):
            self.tree.upsert(f"{HOST}/{name}", StatusCode.OK, [Entry("x", "fine")],
                             frequency_seconds=120)
        self.tree.upsert(f"{HOST}/web", StatusCode.OK,
                         [Entry("response", "HTTP 200 in 209 ms")],
                         frequency_seconds=180, subject=SITE,
                         record={"status": 200, "response_ms": 209})
        self.tree.upsert(f"{HOST}/beat", StatusCode.OK, [Entry("x", "fresh")],
                         frequency_seconds=180, subject="/tmp/beat")
        self.tree.upsert("/other/thing", StatusCode.OK, frequency_seconds=60)

    METRICS = ("host-metrics", HOST, "alpha.example")
    MEMORY = ("macos-memory", HOST, "alpha.example")
    WEB = ("http", f"{HOST}/web", SITE)
    BEAT = ("file", f"{HOST}/beat", "/tmp/beat")

    def _one(self, url: str, key: tuple[str, str, str]) -> dict[str, Any]:
        """The one series of ``key`` in the answer at ``url``."""
        found, = [one for one in self._series(url)
                  if (one["key"]["type"], one["key"]["mount"],
                      one["key"]["subject"]) == key]
        return found

    # --- ADR-0106 decision 6: the Series view's own URL, answered as JSON ----------

    def test_the_read_answers_json_behind_the_bearer_token(self) -> None:
        answer = self._answer("/series/hosts/alpha")
        self.assertEqual(answer["schema_version"], 2)
        self.assertEqual(set(answer["instance"]), {"version", "engine"})
        self.assertEqual(answer["instance"]["engine"], "running")

    def test_it_needs_no_session_and_echoes_a_flow_id(self) -> None:
        response = self.client.get("/series/hosts/alpha",
                                   headers={**JSON, "X-Flow-Id": "abc-123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Flow-Id"), "abc-123")

    def test_the_page_at_that_url_is_what_a_browser_still_gets(self) -> None:
        """One URL, the representation chosen by `Accept`."""
        browser = self._signed_in()
        for url in ("/series/hosts/alpha", "/series"):
            with self.subTest(url=url):
                page = browser.get(url)
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.mimetype, "text/html")
        self.assertIn('class="ls-curve__plot"',
                      browser.get("/series/hosts/alpha").get_data(as_text=True))

    # --- decision 2: the root is read as a node is ---------------------------------

    def test_the_root_answers_every_series_the_instance_keeps(self) -> None:
        answer = self._answer("/series")
        self.assertEqual(answer["path"], "/")
        self.assertEqual(sorted(self._keys(answer["series"])),
                         sorted([self.METRICS, self.MEMORY, self.WEB, self.BEAT]))
        self.assertEqual(
            sum(len(one["readings"]) for one in answer["series"]), 60)

    def test_the_root_reads_its_window_as_a_node_does(self) -> None:
        answer = self._answer(
            f"/series?from={stamp(T0)}&to={stamp(T0 + timedelta(minutes=2))}")
        self.assertEqual(answer["window"],
                         {"from": stamp(T0), "to": stamp(T0 + timedelta(minutes=2))})
        self.assertEqual({key: len(one["readings"]) for key, one
                          in zip(self._keys(answer["series"]), answer["series"],
                                 strict=True)},
                         {self.METRICS: 2, self.MEMORY: 2, self.WEB: 1, self.BEAT: 1})

    # --- decision 3: which series are in the answer --------------------------------

    def test_a_node_answers_every_series_shown_at_or_beneath_it(self) -> None:
        series = self._series("/series/hosts/alpha")
        self.assertEqual(sorted(self._keys(series)),
                         sorted([self.METRICS, self.MEMORY, self.WEB, self.BEAT]))
        self.assertEqual({one["key"]["type"]: one["node"] for one in series},
                         {"host-metrics": HOST, "macos-memory": HOST,
                          "http": f"{HOST}/web", "file": f"{HOST}/beat"})

    def test_a_series_says_its_node_and_the_key_it_is_kept_under(self) -> None:
        one, = self._series("/series/hosts/alpha/web")
        self.assertEqual(set(one), {"node", "key", "measures", "readings"})
        self.assertEqual(one["node"], f"{HOST}/web")
        self.assertEqual(one["key"], {"type": "http", "mount": f"{HOST}/web",
                                      "subject": SITE})

    def test_a_series_from_above_answers_by_the_measure_that_stands_there(
            self) -> None:
        """A host's series answers at the host's `memory` node by the measure that
        stands there — and the memory check's, which shares the mount and names no
        node there, does not."""
        one, = self._series("/series/hosts/alpha/memory")
        self.assertEqual(self._keys([one]), [self.METRICS])
        self.assertEqual(one["node"], HOST, "the node it is shown on, above")
        self.assertEqual([measure["field"] for measure in one["measures"]],
                         ["mem_pct"])
        self.assertEqual(len(one["readings"]), 20)

    def test_a_series_above_with_no_measure_there_is_not_in_the_answer(self) -> None:
        self.assertEqual(self._keys(self._series("/series/hosts/alpha/web")),
                         [self.WEB])

    def test_which_series_stand_is_never_read_from_a_readings_numbers(self) -> None:
        """Every reading of the host failed, so no reading gives its memory a number
        and the page draws no curve of it; the series stands there all the same."""
        self._deploy(failed=True)
        one, = self._series("/series/hosts/alpha/memory")
        self.assertEqual(self._keys([one]), [self.METRICS])
        self.assertEqual([measure["field"] for measure in one["measures"]],
                         ["mem_pct"])
        self.assertTrue(all(reading["record"]["mem_pct"] is None
                            for reading in one["readings"]))

    def test_a_series_with_no_reading_in_the_window_keeps_its_place(self) -> None:
        end = stamp(T0 + timedelta(seconds=30))
        series = self._series(f"/series/hosts/alpha?from={stamp(T0)}&to={end}")
        self.assertEqual(sorted(self._keys(series)),
                         sorted([self.METRICS, self.MEMORY, self.WEB, self.BEAT]))
        self.assertEqual({one["key"]["type"]: len(one["readings"]) for one in series},
                         {"host-metrics": 1, "macos-memory": 1, "http": 0, "file": 0})

    # --- decision 4: a measure, as the page draws it -------------------------------

    def test_a_measure_says_its_field_unit_label_node_and_axis(self) -> None:
        one = self._one("/series/hosts/alpha", self.WEB)
        self.assertEqual(one["measures"], [
            {"field": "response_ms", "unit": "ms", "label": "Response time",
             "node": f"{HOST}/web", "axis_to": None}])
        memory = self._one("/series/hosts/alpha", self.METRICS)["measures"][0]
        self.assertEqual(memory, {"field": "mem_pct", "unit": "%",
                                  "label": "Memory in use", "node": f"{HOST}/memory",
                                  "axis_to": 100.0})

    def test_there_is_one_measure_for_every_key_the_kept_readings_hold(self) -> None:
        measures = self._one("/series/hosts/alpha", self.MEMORY)["measures"]
        picked = [measure for measure in measures
                  if measure["field"].startswith("processes.")]
        self.assertEqual(picked, [
            {"field": "processes.mail.rss_kb", "unit": "KiB",
             "label": "Resident memory of mail",
             "node": f"{HOST}/processes/mail", "axis_to": None},
            {"field": "processes.sync.rss_kb", "unit": "KiB",
             "label": "Resident memory of sync",
             "node": f"{HOST}/processes/sync", "axis_to": None}])
        self.assertFalse(any("*" in json.dumps(measure) for measure in measures))

    def test_measures_are_expanded_over_everything_kept_whatever_the_window(
            self) -> None:
        """`sync` runs from the eleventh reading on; a window of the first three
        holds none of its readings and lists its measure."""
        one = self._one(
            f"/series/hosts/alpha?to={stamp(T0 + timedelta(minutes=4))}", self.MEMORY)
        self.assertEqual(len(one["readings"]), 3)
        self.assertFalse(any("sync" in reading["record"]["processes"]
                             for reading in one["readings"]))
        self.assertIn("processes.sync.rss_kb",
                      [measure["field"] for measure in one["measures"]])

    def test_only_the_measures_at_or_beneath_the_node_asked_are_listed(self) -> None:
        one, = self._series("/series/hosts/alpha/processes")
        self.assertEqual(self._keys([one]), [self.MEMORY])
        self.assertEqual([measure["node"] for measure in one["measures"]],
                         [f"{HOST}/processes/mail", f"{HOST}/processes/sync"])
        whole = self._one("/series/hosts/alpha", self.MEMORY)["measures"]
        self.assertEqual([measure["field"] for measure in whole],
                         ["pressure_level", "compressor_pct", "swap_used_mb",
                          "processes.mail.rss_kb", "processes.sync.rss_kb"])

    def test_a_declaration_no_kept_reading_holds_a_key_for_lists_nothing(
            self) -> None:
        """The host type declares `volumes.*.pct`, and this host reports one disk."""
        self.assertIn("volumes.*.pct", app_module.engine.checks[0].measures)
        fields = [measure["field"] for measure
                  in self._one("/series/hosts/alpha", self.METRICS)["measures"]]
        self.assertEqual(fields,
                         ["mem_pct", "cpu_pct", "load1_per_core", "disk_pct"])

    def test_a_measures_node_need_not_be_a_node_of_the_tree(self) -> None:
        """One reading counts a volume, so the measure declared over volumes stands
        for it on a node no grading wrote: listed where it is asked from above, and
        at its own path there is no node to ask."""
        self.store.add(SeriesKey(*self.METRICS), SeriesRecord(
            {**_host_reading(0), "volumes": {"root": {"path": "/", "pct": 51}}},
            T0 + timedelta(minutes=40), code=StatusCode.OK, texts=("fine",)),
            keep=720)
        for url, fields in (
                ("/series/hosts/alpha/disk", ["disk_pct", "volumes.root.pct"]),
                ("/series/hosts/alpha",
                 ["mem_pct", "cpu_pct", "load1_per_core", "disk_pct",
                  "volumes.root.pct"])):
            with self.subTest(url=url):
                measures = self._one(url, self.METRICS)["measures"]
                self.assertEqual([one["field"] for one in measures], fields)
                self.assertEqual(measures[-1], {
                    "field": "volumes.root.pct", "unit": "%",
                    "label": "Disk space used on root",
                    "node": f"{HOST}/disk/root", "axis_to": 100.0})
        self._refused("/series/hosts/alpha/disk/root", 404)
        self.assertEqual(
            self._signed_in().get("/series/hosts/alpha/disk/root").status_code, 404)

    def test_a_reader_reads_a_field_by_flattening_and_never_by_splitting(
            self) -> None:
        """A process whose name holds a `.` is a key that holds one."""
        def dotted(step: int) -> dict[str, Any]:
            reading = _mac_reading(step)
            reading["processes"]["backup.daily"] = {"count": 1, "rss_kb": 7 + step}
            return reading
        self._deploy(mac=dotted)
        one = self._one("/series/hosts/alpha", self.MEMORY)
        measure, = [measure for measure in one["measures"]
                    if measure["label"] == "Resident memory of backup.daily"]
        self.assertEqual(measure["field"], "processes.backup.daily.rss_kb")
        self.assertEqual(measure["node"], f"{HOST}/processes/backup.daily")
        newest = one["readings"][-1]["record"]
        self.assertEqual(flatten(newest)[measure["field"]], 26)
        self.assertNotIn("backup", newest["processes"], "the name does not split")
        # and every measure of every series is read the same way
        for series in self._series("/series/hosts/alpha"):
            for declared in series["measures"]:
                self.assertTrue(
                    any(declared["field"] in flatten(reading["record"])
                        for reading in series["readings"]), declared["field"])

    # --- decision 5: a reading -----------------------------------------------------

    def test_a_reading_says_when_how_it_stood_and_what_was_read(self) -> None:
        readings = self._one("/series/hosts/alpha", self.WEB)["readings"]
        self.assertEqual(len(readings), 10)
        first = readings[0]
        self.assertEqual(set(first), READING_FIELDS)
        self.assertEqual(first, {
            "at": "2026-09-26T15:01:00Z", "observed_at": "2026-09-26T15:01:00Z",
            "code": "OK", "texts": ["HTTP 200 in 200 ms"], "identity": "",
            "state": "", "record": {"status": 200, "response_ms": 200}})

    def test_readings_are_listed_oldest_first(self) -> None:
        for series in self._series("/series/hosts/alpha"):
            times = [reading["at"] for reading in series["readings"]]
            self.assertEqual(times, sorted(times), series["key"])
            self.assertGreater(len(times), 1)

    def test_a_reading_placed_on_a_node_keeps_that_nodes_lines(self) -> None:
        readings = self._one("/series/hosts/alpha", self.METRICS)["readings"]
        self.assertEqual(readings[0]["texts"], ["memory fine", "disk fine"])

    def test_a_reading_that_failed_keeps_its_code_and_its_record(self) -> None:
        failed = self._one("/series/hosts/alpha", self.METRICS)["readings"][7]
        self.assertEqual(failed["code"], "ERROR")
        self.assertEqual(failed["texts"], ["unreachable"])
        self.assertIn("refused", failed["record"]["error"])
        self.assertIsNone(failed["record"]["mem_pct"])

    def test_a_record_is_whole_and_its_typed_times_are_utc(self) -> None:
        reading = self._one("/series/hosts/alpha", self.BEAT)["readings"][0]
        self.assertEqual(reading["record"],
                         {"modified": {"at": "2026-09-26T14:00:00Z"}})
        # a time nested deeper is a value the record carries, and orders nothing
        self.assertEqual(reading["at"], "2026-09-26T15:01:00Z")
        whole = self._one("/series/hosts/alpha/memory", self.METRICS)["readings"][0]
        self.assertEqual(whole["record"], _host_reading(0),
                         "an aspect's node answers every field of the reading")

    def test_a_reading_that_stood_nowhere_keeps_neither_code_nor_sentence(
            self) -> None:
        """A subject no line names: shown on its check's node, with what it kept —
        and an absence is never an `OK`."""
        other = ("http", f"{HOST}/web", "https://other.example")
        self.store.add(SeriesKey(*other),
                       SeriesRecord({"status": 200, "response_ms": 5}, T0), keep=480)
        one = self._one("/series/hosts/alpha/web", other)
        self.assertEqual(one["node"], f"{HOST}/web")
        reading, = one["readings"]
        self.assertIsNone(reading["code"])
        self.assertEqual(reading["texts"], [])
        self.assertEqual((reading["identity"], reading["state"]), ("", ""))

    def test_a_run_stands_at_its_own_time_and_says_when_it_was_read(self) -> None:
        """A record with a time of its own is placed by it, and the event it is of
        is its identity."""
        runs = ("http", f"{HOST}/web", "https://runs.example")
        for number, ran, minutes in ((41, "14:30", 0), (42, "14:40", 6)):
            self.store.add(SeriesKey(*runs), SeriesRecord(
                {"at": f"2026-09-26T{ran}:00Z", "seconds": 61},
                T0 + timedelta(minutes=minutes), identity=f"run-{number}",
                code=StatusCode.ERROR if number == 42 else StatusCode.OK,
                texts=(f"run {number}",)), keep=480)
        first, second = self._one("/series/hosts/alpha/web", runs)["readings"]
        self.assertEqual((first["at"], first["observed_at"]),
                         ("2026-09-26T14:30:00Z", "2026-09-26T15:00:00Z"))
        self.assertEqual((second["at"], second["observed_at"]),
                         ("2026-09-26T14:40:00Z", "2026-09-26T15:06:00Z"))
        self.assertEqual([(one["identity"], one["state"], one["code"])
                          for one in (first, second)],
                         [("run-41", "", "OK"), ("run-42", "", "ERROR")])
        self.assertEqual(first["record"],
                         {"at": "2026-09-26T14:30:00Z", "seconds": 61})

    def test_a_state_read_again_keeps_when_it_began_and_says_when_it_was_last_read(
            self) -> None:
        switch = ("http", f"{HOST}/web", "https://switch.example")
        for minutes in (0, 6):
            self.store.add(SeriesKey(*switch), SeriesRecord(
                {"enabled": False}, T0 + timedelta(minutes=minutes), state="off",
                code=StatusCode.WARN, texts=("switched off",)), keep=480)
        reading, = self._one("/series/hosts/alpha/web", switch)["readings"]
        self.assertEqual((reading["at"], reading["observed_at"]),
                         ("2026-09-26T15:00:00Z", "2026-09-26T15:06:00Z"))
        self.assertEqual((reading["identity"], reading["state"], reading["code"]),
                         ("", "off", "WARN"))

    def test_a_reading_is_in_the_window_where_its_at_is_both_ends_included(
            self) -> None:
        start, end = T0 + timedelta(minutes=4), T0 + timedelta(minutes=8)
        readings = self._one(
            f"/series/hosts/alpha?from={stamp(start)}&to={stamp(end)}",
            self.METRICS)["readings"]
        self.assertEqual([reading["at"] for reading in readings],
                         ["2026-09-26T15:04:00Z", "2026-09-26T15:06:00Z",
                          "2026-09-26T15:08:00Z"])

    # --- decision 6: what was asked, and the order ---------------------------------

    def test_the_answer_says_the_node_asked_and_holds_nothing_else(self) -> None:
        answer = self._answer("/series/hosts/alpha/web")
        self.assertEqual(set(answer), {"schema_version", "generated_at", "instance",
                                       "path", "window", "series"})
        self.assertEqual(answer["path"], f"{HOST}/web")
        self.assertEqual(answer["generated_at"], stamp(NOW))

    def test_a_url_without_a_window_leaves_both_ends_to_what_is_kept(self) -> None:
        answer = self._answer("/series/hosts/alpha/web")
        self.assertEqual(answer["window"], {"from": None, "to": None})
        self.assertEqual(len(answer["series"][0]["readings"]), 10)

    def test_a_window_back_from_now_is_read_by_the_servers_clock(self) -> None:
        answer = self._answer("/series/hosts/alpha/web?from=now-10m")
        self.assertEqual(answer["window"],
                         {"from": stamp(NOW - timedelta(minutes=10)),
                          "to": stamp(NOW)})
        self.assertEqual(answer["window"]["to"], answer["generated_at"])
        # the website was last read at 15:28, seventeen minutes before now
        self.assertEqual(answer["series"][0]["readings"], [])
        self.assertEqual(
            [reading["at"] for reading in self._series(
                "/series/hosts/alpha/web?from=now-20m")[0]["readings"]],
            ["2026-09-26T15:25:00Z", "2026-09-26T15:28:00Z"])

    def test_an_instant_without_an_offset_is_read_in_the_configured_zone(
            self) -> None:
        answer = self._answer(
            "/series/hosts/alpha/web?from=2026-09-26T17:10&to=2026-09-26T17:20")
        self.assertEqual(answer["window"], {"from": "2026-09-26T15:10:00Z",
                                            "to": "2026-09-26T15:20:00Z"})
        self.assertEqual([reading["at"] for reading
                          in answer["series"][0]["readings"]],
                         ["2026-09-26T15:10:00Z", "2026-09-26T15:13:00Z",
                          "2026-09-26T15:16:00Z", "2026-09-26T15:19:00Z"])

    def test_a_window_may_leave_its_start_to_what_is_kept(self) -> None:
        answer = self._answer(f"/series/hosts/alpha/web?to={stamp(T0)}")
        self.assertEqual(answer["window"], {"from": None, "to": stamp(T0)})
        self.assertEqual(answer["series"][0]["readings"], [])

    def test_a_series_from_above_the_node_asked_comes_first(self) -> None:
        """The host's own measure may name the node its website is mounted on."""
        self._deploy(host={"measures": {
            "mem_used_kb": {"unit": "KiB", "label": "Memory", "node": "web"}}})
        series = self._series("/series/hosts/alpha/web")
        self.assertEqual(self._keys(series), [self.METRICS, self.WEB])
        self.assertEqual([one["node"] for one in series], [HOST, f"{HOST}/web"])
        self.assertEqual([measure["field"] for measure in series[0]["measures"]],
                         ["mem_used_kb"])

    def test_series_on_one_node_are_ordered_by_their_key(self) -> None:
        """By their type first — whichever of two checks on one mount the
        configuration happened to load first."""
        for memory_first in (False, True):
            with self.subTest(memory_first=memory_first):
                self._deploy(memory_first=memory_first)
                series = self._series("/series/hosts/alpha")
                self.assertEqual(
                    self._keys(series),
                    [self.METRICS, self.MEMORY, self.BEAT, self.WEB],
                    "the host's node, then beat and web beneath it by name")

    def test_series_follow_a_declared_rank_before_a_name(self) -> None:
        """Siblings stand in the tree's order — a declared rank first, then the
        name — and so do the series on them."""
        self.tree.upsert(f"{HOST}/beat", StatusCode.OK, [Entry("x", "fresh")],
                         frequency_seconds=180, subject="/tmp/beat", order=5)
        status = self.client.get("/status/hosts/alpha", headers=JSON).get_json()
        names = [child["name"] for child in status["status"]["children"]]
        self.assertLess(names.index("web"), names.index("beat"), "the tree's order")
        self.assertEqual(self._keys(self._series("/series/hosts/alpha")),
                         [self.METRICS, self.MEMORY, self.WEB, self.BEAT])

    # --- decision 7: a list, and three refusals ------------------------------------

    def test_a_node_no_check_keeps_a_series_of_answers_an_empty_list(self) -> None:
        for url in ("/series/hosts/alpha/ssh", "/series/other/thing", "/series/other"):
            with self.subTest(url=url):
                answer = self._answer(url)
                self.assertEqual(answer["series"], [])
                self.assertEqual(answer["path"], url.removeprefix("/series"))
                # where the page says that no curve can stand
                self.assertEqual(self._signed_in().get(url).status_code, 404)

    def test_a_check_that_has_read_nothing_yet_answers_an_empty_list(self) -> None:
        self._deploy(idle=True)
        self.assertEqual(self._series("/series/hosts/alpha/idle"), [])
        self.assertEqual(
            self._signed_in().get("/series/hosts/alpha/idle").status_code, 200)

    def test_an_instance_that_runs_no_engine_answers_an_empty_list_and_says_so(
            self) -> None:
        app_module.engine = None
        with mock.patch.object(app_module, "engine_error", None):
            for url in ("/series/hosts/alpha", "/series"):
                with self.subTest(url=url):
                    answer = self._answer(url)
                    self.assertEqual(answer["series"], [])
                    self.assertEqual(answer["instance"]["engine"], "disabled")
            self.assertEqual(
                self._signed_in().get("/series/hosts/alpha").status_code, 404)

    def test_without_a_valid_token_it_is_401(self) -> None:
        for url in ("/series/hosts/alpha", "/series"):
            for sent in ({}, {"Authorization": "Bearer nope"},
                         {"Authorization": "Basic c2VjcmV0"}):
                with self.subTest(url=url, sent=sent):
                    response = self.client.get(
                        url, headers={"Accept": "application/json", **sent})
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.mimetype, "application/problem+json")
                    self.assertEqual(response.get_json(force=True)["title"],
                                     "Unauthorized")

    def test_a_path_no_node_stands_at_is_404_and_nothing_else_is(self) -> None:
        body = self._refused("/series/hosts/beta", 404)
        self.assertEqual(body["title"], "Not Found")
        self.assertIn("hosts/beta", body["detail"])
        # a node a measure names and no check has written is no node either
        self._refused("/series/hosts/alpha/disk/root", 404)

    def test_a_window_the_server_cannot_read_is_400_with_the_pages_sentence(
            self) -> None:
        for url in ("/series/hosts/alpha?from=yesterday", "/series?from=yesterday"):
            with self.subTest(url=url):
                body = self._refused(url, 400)
                self.assertEqual(body["title"], "Bad Request")
                self.assertEqual(
                    body["detail"],
                    "The window's from cannot be read as yesterday: write now, "
                    "now-6h or an instant such as 2026-09-30T14:00.")
        page = self._signed_in().get("/series/hosts/alpha?from=yesterday")
        self.assertEqual(page.status_code, 400)
        self.assertIn("cannot be read as yesterday", page.get_data(as_text=True))

    def test_a_from_that_is_not_before_its_to_is_400(self) -> None:
        body = self._refused(
            f"/series/hosts/alpha?from={stamp(T0)}&to={stamp(T0)}", 400)
        self.assertEqual(body["detail"],
                         "The window's from has to come before its to.")

    def test_the_refusals_come_in_the_pages_order(self) -> None:
        """The token, then the node, then the window."""
        stranger = self.client.get("/series/hosts/beta?from=yesterday",
                                   headers={"Accept": "application/json"})
        self.assertEqual(stranger.status_code, 401)
        self._refused("/series/hosts/beta?from=yesterday", 404)
        self._refused("/series/hosts/alpha?from=yesterday", 400)

    # --- decision 8: the two routes choose their own credential --------------------

    def test_each_route_refuses_a_stranger_both_ways(self) -> None:
        stranger = app_module.app.test_client()
        for url in ("/series/hosts/alpha", "/series"):
            with self.subTest(url=url):
                page = stranger.get(url)
                self.assertEqual(page.status_code, 302)
                self.assertEqual(page.headers["Location"], "/login")
                read = stranger.get(url, headers={"Accept": "application/json"})
                self.assertEqual(read.status_code, 401)

    def test_a_session_is_no_token(self) -> None:
        browser = self._signed_in()
        for url in ("/series/hosts/alpha", "/series"):
            with self.subTest(url=url):
                read = browser.get(url, headers={"Accept": "application/json"})
                self.assertEqual(read.status_code, 401)
                self.assertEqual(read.mimetype, "application/problem+json")

    def test_a_token_is_no_session(self) -> None:
        for url in ("/series/hosts/alpha", "/series"):
            with self.subTest(url=url):
                page = self.client.get(
                    url, headers={"Authorization": f"Bearer {TOKEN}"})
                self.assertEqual(page.status_code, 302)
                self.assertEqual(page.headers["Location"], "/login")


class QueueEstate(_Read):
    """A queue's check — its own state, and a run of each job name — and the
    functions whose runs are written for the record alone."""

    def setUp(self) -> None:
        super().setUp()
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        queue = _Queue(path="/batch", subject="queue/live", series_keep=5,
                       measures=RUN_TIME)
        functions = _Functions(path="/fn", series_keep=5)
        app_module.engine = Engine([queue, functions], self.tree)
        for _ in range(3):
            app_module.engine.run_once()

    def _subjects(self, url: str) -> list[tuple[str, str]]:
        """Each series of the answer: its subject, and the node it stands on."""
        return [(one["key"]["subject"], one["node"]) for one in self._series(url)]

    def test_a_subject_with_a_node_of_its_own_is_shown_on_it(self) -> None:
        one, = self._series("/series/batch/nightly/import")
        self.assertEqual(one["key"], {"type": "queue", "mount": "/batch",
                                      "subject": "job/import"})
        self.assertEqual(one["node"], "/batch/nightly/import")
        self.assertEqual([reading["identity"] for reading in one["readings"]],
                         ["import-1", "import-2", "import-3"])
        self.assertEqual([reading["record"] for reading in one["readings"]],
                         [{"job": "import", "seconds": 61 + run}
                          for run in (1, 2, 3)])

    def test_a_subject_no_node_stands_for_is_shown_on_its_checks_node(self) -> None:
        """Two job names' lines share a node, which stands for neither."""
        self.assertEqual(dict(self._subjects("/series/batch")), {
            "queue/live": "/batch", "job/a": "/batch", "job/b": "/batch",
            "job/export": "/batch/nightly/export",
            "job/import": "/batch/nightly/import"})
        self.assertEqual(self._series("/series/batch/adhoc"), [])

    def test_series_follow_the_trees_order_of_the_nodes_they_stand_on(self) -> None:
        """The node asked first, then what is beneath it — a node before its
        children, siblings by name — and by the key where several stand on one."""
        self.assertEqual(
            [subject for subject, _node in self._subjects("/series/batch")],
            ["job/a", "job/b", "queue/live", "job/export", "job/import"])
        self.assertEqual(
            self._subjects("/series/batch/nightly"),
            [("job/export", "/batch/nightly/export"),
             ("job/import", "/batch/nightly/import")])

    def test_a_measure_is_the_checks_and_names_its_node_from_the_series_own(
            self) -> None:
        """Each of the check's series lists its measure, the series of its own state
        too, and a subject's stands on the subject's node."""
        measures = {one["key"]["subject"]: one["measures"]
                    for one in self._series("/series/batch")}
        self.assertEqual(set(measures), {"queue/live", "job/a", "job/b",
                                         "job/export", "job/import"})
        for subject, node in (("queue/live", "/batch"), ("job/a", "/batch"),
                              ("job/import", "/batch/nightly/import")):
            with self.subTest(subject=subject):
                self.assertEqual(measures[subject], [
                    {"field": "seconds", "unit": "s", "label": "Run time",
                     "node": node, "axis_to": None}])

    def test_a_check_s_own_state_is_one_reading_from_when_it_began(self) -> None:
        own, = [one for one in self._series("/series/batch")
                if one["key"]["subject"] == "queue/live"]
        reading, = own["readings"]
        self.assertEqual((reading["state"], reading["identity"]), ("open", ""))
        self.assertEqual(reading["record"], {"jobs": 4})
        self.assertLess(datetime.fromisoformat(reading["at"]),
                        datetime.fromisoformat(reading["observed_at"]),
                        "three runs read it: it began at the first")

    def test_a_run_written_for_the_record_alone_keeps_how_it_stood(self) -> None:
        nightly, = self._series("/series/fn/nightly")
        self.assertEqual(nightly["node"], "/fn/nightly")
        self.assertEqual(nightly["measures"], [])
        reading, = nightly["readings"]
        self.assertEqual(reading["at"], "2026-10-01T03:00:00Z")
        self.assertEqual((reading["code"], reading["texts"]),
                         ("ERROR", ["ran with 2 errors"]))
        self.assertEqual(reading["record"]["at"], "2026-10-01T03:00:00Z")
        self.assertEqual(
            [(one["at"], one["code"]) for one
             in self._series("/series/fn/hourly")[0]["readings"]],
            [("2026-10-01T02:00:00Z", "OK"), ("2026-10-01T03:00:00Z", "OK")])
