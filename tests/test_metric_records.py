"""The library's metric types, as ADR-0096 has them record and declare: a thing a
record counts is keyed by the name of the node it becomes (decision 2); a reading
that did not measure says so in its `error` (decision 4); `host-metrics` writes the
load it grades (decision 5); and each type declares the numbers it grades, each
standing on the node that grades it (decision 6).

Every reading here is taken the way the type takes one — ssh answered by a fake —
or written by hand and graded, which is what a series hands the grading later.
"""
from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import TestCase, mock

from little_sister import process
from little_sister.checks import Check, CheckResult, Measurement
from little_sister.checks.file import FileFreshnessCheck
from little_sister.checks.ssh import HostMetricsCheck
from little_sister.checks.ssh.macos_memory import MacosMemoryCheck
from little_sister.checks.ssh.qnap_metrics import QnapMetricsCheck
from little_sister.curves import draw
from little_sister.limits import RECORD_LIMIT
from little_sister.measures import Measure
from little_sister.series import Placed, SeriesRecord
from little_sister.status import StatusCode
from tests.running import SSH_RUN, finished, record_of, run_check

HOST_SAMPLE = """\
os=Linux
hostname=alpha
ncpu=8
uptime_seconds=90061
disk_path=/
disk_total_kb=239362496
disk_avail_kb=45985188
disk_pct=79
mem_total_kb=8388608
mem_used_kb=5767168
mem_pct=69
cpu_pct=22
load1=2.20
"""

VOLUMES_SAMPLE = (
    "disk_count=3\n"
    "disk1_path=/\ndisk1_total_kb=1000000\ndisk1_avail_kb=480000\ndisk1_pct=52\n"
    "disk2_path=/srv/data\ndisk2_total_kb=971319676\ndisk2_avail_kb=83082424\n"
    "disk2_pct=91\n"
    "disk3_path=/mnt/ext\ndisk3_total_kb=379888\ndisk3_avail_kb=3972\ndisk3_pct=99\n"
    "mem_pct=30\ncpu_pct=5\nload1=0.5\nncpu=2\n")

NAS_SAMPLE = (
    "model=TS-419P\nsys_temp_c=41\n"
    "drive1_bay=1\ndrive1_temp_c=42\ndrive1_smart=GOOD\n"
    "drive2_bay=3\ndrive2_temp_c=44\ndrive2_smart=Warning\n"
    "drive_count=2\n")

MAC_SAMPLE = (
    "os=Darwin\npressure_level=1\nfree_pct=62\n"
    "swap_total_mb=3072\nswap_used_mb=1419\n"
    "mem_total_kb=8388608\ncompressor_kb=1258291\ncompressor_pct=15\n"
    "proc1_pattern=Mail.app\nproc1_count=1\nproc1_rss_kb=421888\n"
    "proc1_elapsed_seconds=7980\n"
    "proc2_pattern=collector\nproc2_count=0\n"
    "proc_count=2\n")

PROCESSES = [{"name": "mail", "pattern": "Mail.app"},
             {"name": "collector", "pattern": "collector",
              "max_rss_warn": "512 MiB", "max_rss_error": "1 GiB"}]

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)


@contextmanager
def _checks() -> Iterator[dict[str, Any]]:
    """A factory for each metric type, with a script to send beside it."""
    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        (base / "metrics.sh").write_text("echo hi\n")

        def host(**extra: Any) -> Check:
            return HostMetricsCheck.from_config(
                {"type": "host-metrics", "path": "/alpha", "host": "alpha.example",
                 "script": "metrics.sh", **extra}, base)

        def nas(**extra: Any) -> Check:
            return QnapMetricsCheck.from_config(
                {"type": "qnap-metrics", "path": "/nas1/hardware", "host": "nas1",
                 "script": "metrics.sh", **extra}, base)

        def mac(**extra: Any) -> Check:
            return MacosMemoryCheck.from_config(
                {"type": "macos-memory", "path": "/mac1/system", "host": "mac1",
                 "script": "metrics.sh", "processes": PROCESSES, **extra}, base)

        yield {"host": host, "nas": nas, "mac": mac}


def _read(check: Check, stdout: str = "", *, returncode: int = 0,
          stderr: str = "", ended: process.Ended | None = None) -> dict[str, Any]:
    """One reading, as the type takes it from what ssh answered."""
    answered = (finished(stdout, returncode, stderr) if ended is None
                else finished(returncode=returncode, ended=ended))
    with mock.patch(SSH_RUN, return_value=answered):
        return record_of(check)


def _graded(check: Check, record: dict[str, Any]) -> dict[str, CheckResult]:
    """The children the grading derives from ``record``, by name."""
    result = run_check(check, measurements=(Measurement(record=record),))
    return {child.name: child for child in result.children}


def _paths(result: CheckResult, above: str = "") -> set[str]:
    """Every node the grading writes beneath the check's own, as a relative path."""
    found: set[str] = set()
    for child in result.children:
        path = f"{above}/{child.name}" if above else child.name
        found.add(path)
        found |= _paths(child, path)
    return found


class LoadPerCoreTests(TestCase):
    """The record gains `load1_per_core` — `load1` over the CPUs the host had at that
    reading, at least one, as the grading has always divided it — and the load node
    grades that field. `load1` and `ncpu` stay (decision 5)."""

    def test_the_reading_carries_the_load_per_core(self) -> None:
        with _checks() as make:
            record = _read(make["host"](), HOST_SAMPLE)
        self.assertEqual(record["load1_per_core"], 0.275)
        self.assertEqual((record["load1"], record["ncpu"]), (2.2, 8))

    def test_each_reading_is_divided_by_the_cores_it_had(self) -> None:
        with _checks() as make:
            four = _read(make["host"](), HOST_SAMPLE.replace("ncpu=8", "ncpu=4"))
            eight = _read(make["host"](), HOST_SAMPLE)
        self.assertEqual((four["load1_per_core"], eight["load1_per_core"]),
                         (0.55, 0.275))

    def test_a_host_that_counts_no_cpus_is_divided_by_one(self) -> None:
        with _checks() as make:
            record = _read(make["host"](), HOST_SAMPLE.replace("ncpu=8\n", ""))
        self.assertEqual(record["load1_per_core"], 2.2)

    def test_no_load_is_no_load_per_core(self) -> None:
        # one shape for every reading: the key stands, as null
        with _checks() as make:
            record = _read(make["host"](), HOST_SAMPLE.replace("load1=2.20\n", ""))
        self.assertIn("load1_per_core", record)
        self.assertIsNone(record["load1_per_core"])

    def test_the_load_node_grades_the_field(self) -> None:
        # a record written by hand, whose field disagrees with its own load1: the
        # node reads the field, and the sentence says it
        with _checks() as make:
            host = make["host"]()
            record = _read(host, HOST_SAMPLE)
        record["load1_per_core"] = 2.5
        load = _graded(host, record)["load"]
        self.assertEqual(load.code, StatusCode.ERROR)
        self.assertEqual(load.reason_texts, ["2.50 per core — load1 2.20 over 8 CPUs"])


class ThingsByNameTests(TestCase):
    """A type that reports several things of one kind keys each by the name of the
    node it becomes, in one mapping, its identity kept inside; the positional index
    leaves the record, and with it a curve that swaps one thing for another when a
    run reports them in another order (decision 2)."""

    def test_volumes_are_keyed_by_their_nodes_names(self) -> None:
        with _checks() as make:
            record = _read(make["host"](disk_path="all"), VOLUMES_SAMPLE)
        self.assertEqual(record["volumes"], {
            "root": {"path": "/", "pct": 52, "avail_kb": 480000, "total_kb": 1000000},
            "data": {"path": "/srv/data", "pct": 91, "avail_kb": 83082424,
                     "total_kb": 971319676},
            "ext": {"path": "/mnt/ext", "pct": 99, "avail_kb": 3972,
                    "total_kb": 379888}})
        self.assertFalse([key for key in record
                          if key.startswith("disk") and key != "disk_path"], record)

    def test_the_volumes_nodes_are_those_keys(self) -> None:
        with _checks() as make:
            host = make["host"](disk_path="all")
            disk = _graded(host, _read(host, VOLUMES_SAMPLE))["disk"]
        self.assertEqual({child.name for child in disk.children},
                         {"root", "data", "ext"})
        data, = (child for child in disk.children if child.name == "data")
        self.assertEqual(data.code, StatusCode.ERROR)             # 91 %
        self.assertIn("on /srv/data", data.reason_texts[0])

    def test_a_volume_keeps_its_curve_when_the_order_moves(self) -> None:
        swapped = (VOLUMES_SAMPLE.replace("disk1_", "diskX_")
                   .replace("disk2_", "disk1_").replace("diskX_", "disk2_"))
        with _checks() as make:
            host = make["host"](disk_path="all")
            readings = [_read(host, VOLUMES_SAMPLE), _read(host, swapped)]
        root, *_ = Measure("volumes.*.pct", "%", "Space used on *",
                           "disk/*").expand(readings)
        self.assertEqual(root.node, "disk/root")
        self.assertEqual([root.read(reading) for reading in readings], [52, 52])

    def test_a_reading_that_failed_counts_no_volume(self) -> None:
        with _checks() as make:
            record = _read(make["host"](disk_path="all"), returncode=255,
                           stderr="ssh: connect to host alpha.example: refused")
        self.assertEqual(record["volumes"], {})
        self.assertNotIn("disk_pct", record)

    def test_drives_are_keyed_by_their_nodes_names(self) -> None:
        with _checks() as make:
            record = _read(make["nas"](), NAS_SAMPLE)
        self.assertEqual(record["drives"], {
            "drive1": {"bay": "1", "temp_c": 42, "smart": "GOOD"},
            "drive3": {"bay": "3", "temp_c": 44, "smart": "Warning"}})
        self.assertFalse([key for key in record if key.startswith("drive")
                          and key != "drives"], record)

    def test_the_drives_nodes_are_those_keys(self) -> None:
        with _checks() as make:
            nas = make["nas"]()
            kids = _graded(nas, _read(nas, NAS_SAMPLE))
        self.assertEqual({child.name for child in kids["temperature"].children},
                         {"system", "drive1", "drive3"})
        self.assertEqual({child.name for child in kids["smart"].children},
                         {"drive1", "drive3"})

    def test_watched_processes_are_keyed_by_their_names(self) -> None:
        with _checks() as make:
            record = _read(make["mac"](), MAC_SAMPLE)
        self.assertEqual(record["processes"], {
            "mail": {"count": 1, "rss_kb": 421888, "elapsed_seconds": 7980},
            "collector": {"count": 0, "rss_kb": None, "elapsed_seconds": None}})
        self.assertFalse([key for key in record if key.startswith("proc")
                          and key != "processes"], record)

    def test_the_processes_nodes_are_those_keys(self) -> None:
        with _checks() as make:
            mac = make["mac"]()
            processes = _graded(mac, _read(mac, MAC_SAMPLE))["processes"]
        self.assertEqual({child.name for child in processes.children},
                         {"mail", "collector"})


class FailedReadingTests(TestCase):
    """A reading failed where its record carries an `error` that is not null; every
    type writes it where a reading did not measure, and the SSH types write it for a
    script that failed and an answer they could not read as well as for a connection
    that died — while the sentences the grading writes stay what they were
    (decision 4)."""

    def test_a_reading_that_measured_carries_no_error(self) -> None:
        with _checks() as make:
            for kind, sample in (("host", HOST_SAMPLE), ("nas", NAS_SAMPLE),
                                 ("mac", MAC_SAMPLE)):
                with self.subTest(kind=kind):
                    self.assertNotIn("error", _read(make[kind](), sample))

    def test_a_connection_that_died_keeps_its_own_error(self) -> None:
        with _checks() as make:
            record = _read(make["host"](timeout="2s"), returncode=-15,
                           ended=process.Ended.BOUND)
        self.assertIn("timed out", record["error"])

    def test_a_script_that_failed_says_so(self) -> None:
        stderr = "bash: scripts/metrics.sh: No such file or directory\n"
        with _checks() as make:
            host = make["host"]()
            record = _read(host, returncode=127, stderr=stderr)
            ssh = _graded(host, record)["ssh"]
        self.assertEqual(record["error"], "ssh to alpha.example failed (exit 127): "
                         "bash: scripts/metrics.sh: No such file or directory")
        self.assertNotIn("detail", record)
        self.assertEqual(ssh.code, StatusCode.ERROR)
        self.assertEqual(ssh.reason[0], "ssh to alpha.example failed (exit 127): "
                         "bash: scripts/metrics.sh: No such file or directory")

    def test_an_answer_it_could_not_read_says_so(self) -> None:
        with _checks() as make:
            host = make["host"]()
            record = _read(host, "some unexpected banner\n")
            ssh = _graded(host, record)["ssh"]
        self.assertEqual(record["error"], "connected, but no metrics from "
                         "alpha.example: some unexpected banner")
        self.assertNotIn("output", record)
        self.assertEqual(ssh.reason[0], "connected, but no metrics from "
                         "alpha.example: some unexpected banner")

    def test_so_do_the_nas_and_the_mac(self) -> None:
        with _checks() as make:
            nas = _read(make["nas"](), "garbage\n")
            mac = _read(make["mac"](), "garbage\n")
        self.assertEqual(nas["error"], "connected, but no QNAP data from nas1: garbage")
        self.assertEqual(mac["error"],
                         "connected, but no memory data from mac1: garbage")

    def test_a_profile_mismatch_is_no_failed_reading(self) -> None:
        # a configuration the host refused: it answered, and its WARN says why
        stdout = ("os=Linux\nhostname=h\nprofile_error=macos profile expects a "
                  "Darwin host but uname reports 'Linux'\n")
        with _checks() as make:
            host = make["host"](profile="macos")
            record = _read(host, stdout)
            ssh = _graded(host, record)["ssh"]
        self.assertNotIn("error", record)
        self.assertEqual(ssh.code, StatusCode.WARN)
        self.assertIn("profile mismatch", ssh.reason[0])

    def test_a_failed_reading_still_weighs_what_the_check_declares(self) -> None:
        emoji = "\U0001F600"
        self.assertEqual(len(emoji), 1)
        with _checks() as make:
            for kind in ("host", "mac"):
                with self.subTest(kind=kind):
                    check = make[kind]()
                    failed = _read(check, returncode=1, stderr=emoji * 400)
                    garbled = _read(check, emoji * 400)
                    for record in (failed, garbled):
                        self.assertLessEqual(
                            len(json.dumps(record).encode("utf-8")),
                            check.expected_record())
                    self.assertLessEqual(check.expected_record(), RECORD_LIMIT)

    def test_a_curve_marks_the_failure_and_not_the_mismatch(self) -> None:
        with _checks() as make:
            host = make["host"]()
            readings = [_read(host, HOST_SAMPLE),
                        _read(host, returncode=255, stderr="ssh: refused"),
                        _read(host, "os=Linux\nprofile_error=wrong profile\n"),
                        _read(host, HOST_SAMPLE)]
        placed = [Placed(SeriesRecord(record, T0 + timedelta(minutes=2 * index)),
                         T0 + timedelta(minutes=2 * index))
                  for index, record in enumerate(readings)]
        curve = draw(host.measures["mem_pct"], placed, tolerance=None)
        mark, = curve.marks
        self.assertEqual(mark.at, T0 + timedelta(minutes=2))
        self.assertEqual((curve.failed, curve.unvalued, curve.valued), (1, 1, 2))


class DefaultsTests(TestCase):
    """A type's defaults are the fields its nodes are graded on, each standing on the
    node it grades; `file` declares none (decision 6)."""

    def test_host_metrics_declares_what_it_grades(self) -> None:
        with _checks() as make:
            measures = make["host"]().measures
        self.assertEqual(measures, {
            "mem_pct": Measure("mem_pct", "%", "Memory in use", "memory", 100),
            "cpu_pct": Measure("cpu_pct", "%", "CPU busy", "cpu", 100),
            "load1_per_core": Measure("load1_per_core", "per core", "Load per core",
                                      "load"),
            "disk_pct": Measure("disk_pct", "%", "Disk space used", "disk", 100),
            "volumes.*.pct": Measure("volumes.*.pct", "%", "Disk space used on *",
                                     "disk/*", 100)})

    def test_qnap_metrics_declares_what_it_grades(self) -> None:
        with _checks() as make:
            measures = make["nas"]().measures
        self.assertEqual(measures, {
            "sys_temp_c": Measure("sys_temp_c", "°C", "System temperature",
                                  "temperature/system"),
            "cpu_temp_c": Measure("cpu_temp_c", "°C", "CPU temperature",
                                  "temperature/cpu"),
            "drives.*.temp_c": Measure("drives.*.temp_c", "°C", "Temperature of *",
                                       "temperature/*")})

    def test_macos_memory_declares_what_it_grades(self) -> None:
        with _checks() as make:
            measures = make["mac"]().measures
        self.assertEqual(measures, {
            "pressure_level": Measure("pressure_level", "",
                                      "Memory pressure level", "pressure"),
            "compressor_pct": Measure("compressor_pct", "%", "Compressed memory",
                                      "compressor", 100),
            "swap_used_mb": Measure("swap_used_mb", "MiB", "Swap used", "swap"),
            "processes.*.rss_kb": Measure("processes.*.rss_kb", "KiB",
                                          "Resident memory of *", "processes/*")})

    def test_file_declares_none(self) -> None:
        check = FileFreshnessCheck.from_config(
            {"type": "file", "path": "/beat", "file": "/tmp/beat",
             "max_age_error": "5m"}, Path("."))
        self.assertEqual(check.measures, {})

    def test_every_default_reads_a_number_out_of_its_type_s_reading(self) -> None:
        # a default that named a field the record does not have would draw nothing
        with _checks() as make:
            cases = ((make["host"](), HOST_SAMPLE, {"volumes.*.pct"}),
                     (make["host"](disk_path="all"), VOLUMES_SAMPLE, {"disk_pct"}),
                     (make["nas"](), NAS_SAMPLE, {"cpu_temp_c"}),
                     (make["mac"](), MAC_SAMPLE, set()))
            for check, sample, absent in cases:
                record = _read(check, sample)
                for name, measure in check.measures.items():
                    picked = measure.expand([record])
                    with self.subTest(type=check.type_name, measure=name):
                        if name in absent:
                            self.assertFalse([m for m in picked
                                              if isinstance(m.read(record),
                                                            (int, float))])
                        else:
                            self.assertTrue(picked)
                            for one in picked:
                                if one.field == "processes.collector.rss_kb":
                                    continue          # not running: no RSS to read
                                self.assertIsInstance(one.read(record), (int, float),
                                                      one.field)

    def test_every_default_stands_on_a_node_its_grading_writes(self) -> None:
        with _checks() as make:
            for check, sample in ((make["host"](), HOST_SAMPLE),
                                  (make["host"](disk_path="all"), VOLUMES_SAMPLE),
                                  (make["nas"](), NAS_SAMPLE),
                                  (make["mac"](), MAC_SAMPLE)):
                record = _read(check, sample)
                written = _paths(run_check(
                    check, measurements=(Measurement(record=record),)))
                for measure in check.measures.values():
                    for one in measure.expand([record]):
                        if not isinstance(one.read(record), (int, float)):
                            continue
                        with self.subTest(type=check.type_name, node=one.node):
                            self.assertIn(one.node, written)


class SentenceTests(TestCase):
    """The swap and process sentences write their sizes through `format_weight`, so
    that a node and its curve write one figure one way (decision 6)."""

    def test_swap_reads_in_the_curve_s_units(self) -> None:
        with _checks() as make:
            mac = make["mac"]()
            swap = _graded(mac, _read(mac, MAC_SAMPLE))["swap"]
        self.assertEqual(swap.reason_texts, ["1.4 GiB used of 3.0 GiB allocated"])
        self.assertEqual(mac.measures["swap_used_mb"].write(1419), "1.4 GiB")

    def test_a_process_reads_in_the_curve_s_units(self) -> None:
        with _checks() as make:
            mac = make["mac"]()
            processes = _graded(mac, _read(mac, MAC_SAMPLE))["processes"]
        mail, = (child for child in processes.children if child.name == "mail")
        self.assertEqual(mail.reason_texts,
                         ["412.0 MiB RSS over 1 process, oldest up 2h 13m"])
        self.assertEqual(mac.measures["processes.*.rss_kb"]
                         .expand([{"processes": {"mail": {}}}])[0].write(421888),
                         "412.0 MiB")
