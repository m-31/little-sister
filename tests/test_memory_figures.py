"""The instance's memory in its own words (ADR-0095), tested from the record's
sentences with the values they are about: the two figures a platform has, where they
stand — `/system` and the engine's report — the ten-minute line, and what a run's
line, and the tick's own, says rose while it was in flight. The `memory` line that
grades the figures is ``test_limits.py``'s."""
from __future__ import annotations

import builtins
import gc
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import TestCase, skipIf
from unittest.mock import patch

from little_sister import engine as engine_module
from little_sister import limits as limits_module
from little_sister.checks import Check, CheckResult, Measurement
from little_sister.config import config
from little_sister.engine import Engine, _asks_for_a_collection
from little_sister.limits import (
    COLLECTION_SPACING,
    MEMORY_LINE_MINUTES,
    RISE_LOGGED,
    STALL_SECONDS,
    EngineReport,
    Left,
    Limits,
    Resident,
    killed_text,
    machine_left,
    machine_memory,
    machine_text,
    resident_size,
    rise_text,
)
from little_sister.series import MemoryStore
from little_sister.state import StateLayer
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

MIB = 1024 ** 2
GIB = 1024 ** 3
LOGGER = "little_sister.logger"
#: The minus sign a collection's fall is written with, and not a hyphen.
MINUS = "\u2212"


class _Meter:
    """What the process holds, as a test scripts it: the size now — ``None`` on a
    platform that has none, as macOS — and the peak. Called from the engine's worker
    and scheduler threads alike, so it answers under a lock."""

    def __init__(self, *, now: int | None, peak: int) -> None:
        self._lock = threading.Lock()
        self.now = now
        self.peak = peak

    def __call__(self) -> Resident:
        with self._lock:
            return Resident(peak=self.peak, now=self.now)

    def move(self, *, now: int | None = None, peak: int | None = None) -> None:
        with self._lock:
            if now is not None:
                self.now = now
            if peak is not None:
                self.peak = peak


class _Moving(Check):
    """A check whose run moves the meter the way an allocation would: to ``now``
    and ``peak`` where given, after ``started`` is set and ``release`` opens."""

    def __init__(self, *, meter: _Meter, now: int | None = None,
                 peak: int | None = None, started: threading.Event | None = None,
                 release: threading.Event | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._meter = meter
        self._now = now
        self._peak = peak
        self._started = started
        self._release = release

    def measure(self) -> Sequence[Measurement]:
        if self._started is not None:
            self._started.set()
        if self._release is not None:
            self._release.wait(timeout=5)
        self._meter.move(now=self._now, peak=self._peak)
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class _Alpha(_Moving):
    type_name = "alpha"


class _Beta(_Moving):
    type_name = "beta"


def _engine(checks: Sequence[Check], meter: _Meter, **kwargs: Any) -> Engine:
    """An engine on ``meter``, saying nothing of what the machine has left and
    collecting nothing after a run unless a test gives it a ``left`` or a
    ``collect`` of its own."""
    kwargs.setdefault("limits", Limits(memory_limit=None))
    kwargs.setdefault("left", lambda: None)
    kwargs.setdefault("collect", None)
    return Engine(list(checks), StatusTree(), resident=meter, **kwargs)


def _messages(caught: Any, prefix: str) -> list[str]:
    return [record.getMessage() for record in caught.records
            if record.getMessage().startswith(prefix)]


def _run_line(caught: Any, path: str) -> str:
    lines = _messages(caught, f"check {path}: ")
    assert len(lines) == 1, lines
    return lines[0]


class ResidentSizeTests(TestCase):
    """`resident_size()` answers the size now where the kernel keeps one and the
    peak on every platform that has it, raised to the size now where the two, read
    a moment apart, disagree; macOS answers with the peak alone."""

    def test_this_machine_answers_with_what_its_platform_keeps(self) -> None:
        measured = resident_size()
        assert measured is not None
        if Path("/proc/self/statm").exists():
            assert measured.now is not None
            self.assertGreater(measured.now, 0)
            self.assertGreaterEqual(measured.peak, measured.now)
        else:
            self.assertIsNone(measured.now)
            self.assertGreater(measured.peak, 0)

    def test_without_proc_the_peak_is_all_there_is(self) -> None:
        real_open = builtins.open

        def no_proc(path: Any, *args: Any, **kwargs: Any) -> Any:
            if str(path) == "/proc/self/statm":
                raise OSError("no /proc here")
            return real_open(path, *args, **kwargs)

        with patch.object(builtins, "open", no_proc):
            measured = resident_size()
        assert measured is not None
        self.assertIsNone(measured.now)
        self.assertGreater(measured.peak, 0)

    def test_the_peak_is_raised_to_the_size_now_where_they_disagree(self) -> None:
        with patch.object(limits_module, "_statm_resident", return_value=200 * MIB), \
                patch.object(limits_module, "peak_resident", return_value=150 * MIB):
            self.assertEqual(resident_size(), Resident(peak=200 * MIB, now=200 * MIB))

    def test_a_size_without_a_peak_is_its_own_peak(self) -> None:
        with patch.object(limits_module, "_statm_resident", return_value=200 * MIB), \
                patch.object(limits_module, "peak_resident", return_value=None):
            self.assertEqual(resident_size(), Resident(peak=200 * MIB, now=200 * MIB))

    def test_nothing_readable_is_none(self) -> None:
        with patch.object(limits_module, "_statm_resident", return_value=None), \
                patch.object(limits_module, "peak_resident", return_value=None):
            self.assertIsNone(resident_size())


def _meminfo(available_kib: int) -> str:
    """``/proc/meminfo`` as the kernel writes it, around the one line read."""
    return ("MemTotal:         938796 kB\n"
            "MemFree:           32372 kB\n"
            f"MemAvailable:   {available_kib:>9} kB\n"
            "Buffers:               8 kB\n"
            "Cached:            69460 kB\n")


def _events(kills: int) -> str:
    """A v2 cgroup's ``memory.events``, as the instance's read."""
    return (f"low 0\nhigh 0\nmax 0\noom {kills}\noom_kill {kills}\n"
            "oom_group_kill 0\n")


#: ``/proc/pressure/memory`` as the instance had it at its second reading: the
#: ``some`` line's counter is 32.274242 seconds, the ``full`` line's another.
PRESSURE = ("some avg10=0.87 avg60=1.59 avg300=1.45 total=32274242\n"
            "full avg10=0.85 avg60=1.50 avg300=1.38 total=30815820\n")


class MachineLeftTests(TestCase):
    """What the machine has left (ADR-0095 decision 7): `MemAvailable` and, under a
    memory limit, what the limit leaves — the limit less the usage, with the two
    lists of file pages counted back — the smaller of the two; the kernel's counter
    of the time some task stalled on memory; and, under the limit, how often the
    kernel has ended a process of the cgroup. Read from the files the reader reads,
    rooted in a directory of the test's and written as the kernel writes them —
    ``/proc/self/cgroup`` among them, which names the cgroup the process runs in."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def _at(self, path: Path) -> Path:
        return self.root / path.relative_to("/")

    def _write(self, path: str, text: str) -> None:
        where = self._at(Path(path))
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_text(text, encoding="utf-8")

    def _machine(self, physical: int | None) -> ExitStack:
        """The reader pointed at this test's files, the physical memory as given."""
        controllers = tuple(replace(controller, mount=self._at(controller.mount))
                            for controller in limits_module._CONTROLLERS)
        stack = ExitStack()
        for name, value in (
                ("_MEMINFO", self._at(limits_module._MEMINFO)),
                ("_PRESSURE", self._at(limits_module._PRESSURE)),
                ("_SELF_CGROUP", self._at(limits_module._SELF_CGROUP)),
                ("_CONTROLLERS", controllers)):
            stack.enter_context(patch.object(limits_module, name, value))
        stack.enter_context(patch.object(limits_module, "_physical_memory",
                                         return_value=physical))
        return stack

    def _read(self, *, physical: int | None = 916 * MIB) -> Left | None:
        with self._machine(physical):
            return machine_left()

    def _given(self, *, physical: int | None = 916 * MIB) -> int | None:
        """What the machine gives the process, as :func:`machine_memory` reads it."""
        with self._machine(physical):
            return machine_memory()

    def _v2(self, cgroup: str = "/", *, limit: str | None = "max", usage: int = 0,
            inactive: int = 0, active: int = 0, shmem: int = 0, kills: int = 0,
            own: bool = True) -> None:
        """A v2 cgroup at ``cgroup`` beneath the mount — ``/``, its root, as a
        container sees its own — the one ``/proc/self/cgroup`` names where ``own``.
        ``file`` counts the shared memory, which neither list holds; a cgroup at
        the true root has no limit file, which ``limit=None`` writes."""
        base = "/sys/fs/cgroup" + ("" if cgroup == "/" else cgroup)
        self._write("/sys/fs/cgroup/cgroup.controllers", "cpuset cpu io memory pids\n")
        if limit is not None:
            self._write(f"{base}/memory.max", f"{limit}\n")
        self._write(f"{base}/memory.current", f"{usage}\n")
        self._write(f"{base}/memory.stat",
                    f"anon {max(0, usage - inactive - active - shmem)}\n"
                    f"file {inactive + active + shmem}\nshmem {shmem}\n"
                    "inactive_anon 0\nactive_anon 0\n"
                    f"inactive_file {inactive}\nactive_file {active}\n")
        self._write(f"{base}/memory.events", _events(kills))
        if own:
            self._write("/proc/self/cgroup", f"0::{cgroup}\n")

    def _v1(self, cgroup: str = "/", *, limit: int = 9223372036854771712,
            usage: int = 0, inactive: int = 0, active: int = 0,
            kills: int = 0) -> None:
        """A v1 memory cgroup at ``cgroup`` beneath the mount. Its own lists hold
        nothing, as where the cache is the cgroups' beneath it; the hierarchical
        ones hold ``inactive`` and ``active``."""
        base = "/sys/fs/cgroup/memory" + ("" if cgroup == "/" else cgroup)
        self._write(f"{base}/memory.limit_in_bytes", f"{limit}\n")
        self._write(f"{base}/memory.usage_in_bytes", f"{usage}\n")
        self._write(f"{base}/memory.stat",
                    "cache 0\nrss 0\ninactive_file 0\nactive_file 0\n"
                    f"total_cache {inactive + active}\n"
                    f"total_inactive_file {inactive}\ntotal_active_file {active}\n")
        self._write(f"{base}/memory.oom_control",
                    f"oom_kill_disable 0\nunder_oom 0\noom_kill {kills}\n")

    # What is left, and the two figures beside it

    def test_under_no_limit_it_is_the_machine_s_figure(self) -> None:
        """The deployment's container as it was read: `memory.max` says ``max``, and
        its `/proc/meminfo` is the machine's."""
        self._write("/proc/meminfo", _meminfo(40968))
        self._v2(limit="max", usage=497 * MIB, inactive=3 * MIB, active=MIB)
        self.assertEqual(self._read(), Left(available=40968 * 1024))

    def test_a_limit_leaves_the_limit_less_the_usage_with_the_file_lists_counted_back(
            self) -> None:
        """Under a limit of 48 MiB with 32 MiB of a file in the cache, the usage
        33.4 MiB: the limit less the usage says 14.6 MiB, and what the kernel then
        gave was the limit less the usage with the two lists counted back, 46.6 —
        which with the multi-generational LRU off stood on the active list."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        usage = 33 * MIB + 400 * 1024
        self._v2(limit=str(48 * MIB), usage=usage, inactive=0, active=32 * MIB)
        left = self._read()
        assert left is not None
        self.assertEqual(left.available, 48 * MIB - usage + 32 * MIB)
        self.assertEqual(round(left.available / MIB, 1), 46.6)

    def test_shared_memory_is_not_counted_back(self) -> None:
        """`file` counts `shmem`, which is not given up; the two lists do not."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        usage = 40 * MIB
        self._v2(limit=str(48 * MIB), usage=usage, inactive=4 * MIB,
                 active=12 * MIB, shmem=8 * MIB)
        left = self._read()
        assert left is not None
        self.assertEqual(left.available, 48 * MIB - usage + 16 * MIB)

    def test_under_cgroup_v1_the_hierarchical_lists_are_counted_back(self) -> None:
        """A v1 cgroup limited to 200 MiB whose usage of 198 MiB was 193 MiB of file
        cache: its own lists hold none of it where the cache is its children's."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._write("/proc/self/cgroup", "9:memory:/docker/0123abcd\n0::/\n")
        self._v1(limit=200 * MIB, usage=198 * MIB, inactive=150 * MIB,
                 active=43 * MIB, kills=2)
        self.assertEqual(self._read(), Left(available=195 * MIB, killed=2))

    def test_the_smaller_of_the_two_is_what_is_left(self) -> None:
        """A container of 512 MiB on a machine whose agents hold the rest: the
        machine has less left than the limit leaves, and that is the figure."""
        self._write("/proc/meminfo", _meminfo(41 * 1024))
        self._v2(limit=str(512 * MIB), usage=440 * MIB, inactive=2 * MIB,
                 active=2 * MIB)
        left = self._read()
        assert left is not None
        self.assertEqual(left.available, 41 * MIB)
        # and the other way round: the limit leaves less than the machine has
        self._write("/proc/meminfo", _meminfo(58 * 1024))
        self._v2(limit=str(512 * MIB), usage=482 * MIB, inactive=2 * MIB,
                 active=2 * MIB)
        left = self._read()
        assert left is not None
        self.assertEqual(left.available, 34 * MIB)

    def test_a_limit_the_machine_cannot_reach_is_no_limit(self) -> None:
        """What :func:`machine_memory` takes: a limit counts where it is smaller than
        the physical memory — v1 says a very large number where there is none."""
        self._write("/proc/meminfo", _meminfo(129 * 1024))
        self._write("/proc/self/cgroup", "9:memory:/\n")
        self._v1(usage=600 * MIB, kills=1)
        self.assertEqual(self._read(), Left(available=129 * MIB))
        self._v2(limit=str(2 * GIB), usage=600 * MIB, kills=1)
        self.assertEqual(self._read(), Left(available=129 * MIB))

    def test_a_limit_counts_where_the_physical_memory_cannot_be_read(self) -> None:
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=str(512 * MIB), usage=500 * MIB)
        self.assertEqual(self._read(physical=None),
                         Left(available=12 * MIB, killed=0))

    def test_under_a_limit_the_kernel_s_kills_are_counted(self) -> None:
        """`oom_kill` in `memory.events`, and not `oom_group_kill` beside it."""
        self._write("/proc/meminfo", _meminfo(306 * 1024))
        self._v2(limit=str(512 * MIB), usage=200 * MIB, kills=1)
        left = self._read()
        assert left is not None
        self.assertEqual(left.killed, 1)

    def test_under_no_limit_nothing_is_counted(self) -> None:
        self._write("/proc/meminfo", _meminfo(129 * 1024))
        self._v2(limit="max", usage=497 * MIB, kills=3)
        left = self._read()
        assert left is not None
        self.assertIsNone(left.killed)

    def test_a_limit_whose_lists_cannot_be_read_leaves_the_machine_s_figure(
            self) -> None:
        """The usage alone counts the cache as taken and says less is left than is,
        so without both lists the limit says nothing and the machine's figure
        stands."""
        self._write("/proc/meminfo", _meminfo(129 * 1024))
        self._v2(limit=str(512 * MIB), usage=500 * MIB)
        self._write("/sys/fs/cgroup/memory.stat", f"anon {490 * MIB}\n"
                                                  f"inactive_file {MIB}\n")
        self.assertEqual(self._read(), Left(available=129 * MIB, killed=0))

    def test_the_stall_counter_is_the_some_line_s_total_in_seconds(self) -> None:
        self._write("/proc/meminfo", _meminfo(51300))
        self._write("/proc/pressure/memory", PRESSURE)
        left = self._read()
        assert left is not None
        self.assertEqual(left.stalled, 32.274242)

    def test_without_the_counter_the_figure_stands_alone(self) -> None:
        self._write("/proc/meminfo", _meminfo(51300))
        self.assertEqual(self._read(), Left(available=51300 * 1024))

    def test_without_memavailable_the_counter_stands_alone(self) -> None:
        """A kernel older than `MemAvailable` says nothing of what is left."""
        self._write("/proc/meminfo", "MemTotal:  938796 kB\nMemFree:  32372 kB\n")
        self._write("/proc/pressure/memory", PRESSURE)
        self.assertEqual(self._read(), Left(stalled=32.274242))

    def test_a_platform_with_neither_file_says_nothing(self) -> None:
        """macOS has neither file, and there is no figure — and nothing limits what
        the machine gives the process but its memory."""
        self.assertIsNone(self._read())
        self.assertEqual(self._given(physical=16 * GIB), 16 * GIB)

    # Which cgroup: the process's own, and each above it

    def test_on_a_bare_host_a_service_s_own_limit_is_found(self) -> None:
        """A service with `MemoryMax=512M`, beneath a slice with none, on a host
        whose root cgroup has no limit file: what the machine gives the process is
        the service's limit, and what is left is what that leaves."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=None, own=False)
        self._v2("/system.slice", own=False)
        self._v2("/system.slice/little-sister.service", limit=str(512 * MIB),
                 usage=300 * MIB, inactive=6 * MIB, active=4 * MIB)
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)
        self.assertEqual(self._read(physical=4 * GIB),
                         Left(available=222 * MIB, killed=0))
        # v2's line is the one with no controller named, whatever stands before it
        self._v2("/init.scope", limit=str(64 * MIB), own=False)
        self._write("/proc/self/cgroup", "1:name=systemd:/init.scope\n"
                                         "0::/system.slice/little-sister.service\n")
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)

    def test_a_limit_on_the_slice_above_binds_as_well(self) -> None:
        """The slice's limit of 1 GiB, its usage 900 MiB with the services beside
        this one: that is what the machine gives the process, and what is left."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=None, own=False)
        self._v2("/system.slice", limit=str(GIB), usage=900 * MIB,
                 inactive=12 * MIB, active=8 * MIB, own=False)
        self._v2("/system.slice/little-sister.service", usage=300 * MIB)
        self.assertEqual(self._given(physical=4 * GIB), GIB)
        left = self._read(physical=4 * GIB)
        assert left is not None
        self.assertEqual(left.available, 144 * MIB)

    def test_what_is_left_is_the_least_any_limit_leaves(self) -> None:
        """The service's limit leaves 222 MiB and the slice's, shared, 60: the
        process can have 60. What the machine gives it is the smaller limit."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=None, own=False)
        self._v2("/system.slice", limit=str(GIB), usage=964 * MIB, own=False)
        self._v2("/system.slice/little-sister.service", limit=str(512 * MIB),
                 usage=300 * MIB, inactive=6 * MIB, active=4 * MIB)
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)
        left = self._read(physical=4 * GIB)
        assert left is not None
        self.assertEqual(left.available, 60 * MIB)

    def test_the_count_is_of_the_process_s_own_cgroup(self) -> None:
        """A slice's count is of every service beneath it; the process's is its own."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=None, own=False)
        self._v2("/system.slice", limit=str(GIB), usage=500 * MIB, kills=4,
                 own=False)
        self._v2("/system.slice/little-sister.service", usage=300 * MIB, kills=1)
        left = self._read(physical=4 * GIB)
        assert left is not None
        self.assertEqual(left.killed, 1)

    def test_under_v1_on_a_bare_host_the_named_cgroup_is_found(self) -> None:
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._write("/proc/self/cgroup",
                    "12:pids:/user.slice\n"
                    "9:memory:/system.slice/little-sister.service\n"
                    "1:name=systemd:/system.slice/little-sister.service\n0::/\n")
        self._v1()
        self._v1("/user.slice", limit=64 * MIB)
        self._v1("/system.slice")
        self._v1("/system.slice/little-sister.service", limit=512 * MIB,
                 usage=300 * MIB, inactive=6 * MIB, active=4 * MIB, kills=1)
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)
        self.assertEqual(self._read(physical=4 * GIB),
                         Left(available=222 * MIB, killed=1))

    def test_memory_is_found_among_the_controllers_of_a_v1_line(self) -> None:
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._write("/proc/self/cgroup", "4:cpu,cpuacct,memory:/jobs/one\n")
        self._v1()
        self._v1("/jobs/one", limit=256 * MIB, usage=100 * MIB)
        self.assertEqual(self._given(physical=4 * GIB), 256 * MIB)

    def test_a_v1_container_names_the_host_s_path_and_sees_its_own_at_the_root(
            self) -> None:
        """Docker on v1 mounts the container's own cgroup at the root and names the
        host's path for it, which is no directory there."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._write("/proc/self/cgroup", "9:memory:/docker/0123abcd\n")
        self._v1(limit=512 * MIB, usage=300 * MIB)
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)
        self.assertEqual(self._read(physical=4 * GIB),
                         Left(available=212 * MIB, killed=0))

    def test_a_host_that_mounts_v1_s_memory_beside_v2_reads_v1(self) -> None:
        """Where `/sys/fs/cgroup` is not v2's root, the memory controller is v1's,
        whatever `/proc/self/cgroup` says of the hierarchy beside it."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._write("/proc/self/cgroup", "9:memory:/user.slice/session.scope\n"
                                         "0::/user.slice/session.scope\n")
        self._write("/sys/fs/cgroup/unified/cgroup.controllers", "\n")
        self._v1()
        self._v1("/user.slice/session.scope", limit=6 * GIB, usage=GIB)
        self.assertEqual(self._given(physical=8 * GIB), 6 * GIB)

    def test_a_path_that_climbs_out_of_the_mount_is_not_followed(self) -> None:
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=str(512 * MIB), usage=300 * MIB, own=False)
        self._write("/sys/etc/memory.max", f"{64 * MIB}\n")
        self._write("/proc/self/cgroup", "0::/../../etc\n")
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)

    def test_a_v1_list_that_names_no_memory_line_leaves_the_root(self) -> None:
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._write("/proc/self/cgroup", "12:pids:/jobs/one\n0::/jobs/one\n")
        self._v1(limit=512 * MIB, usage=100 * MIB)
        self._v1("/jobs/one", limit=64 * MIB)
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)

    def test_what_a_limit_leaves_is_never_more_than_it_nor_less_than_nothing(
            self) -> None:
        """Read a moment apart, the usage can stand below the cache it counts, or
        above the limit."""
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=str(48 * MIB), usage=10 * MIB, inactive=20 * MIB,
                 active=20 * MIB)
        self.assertEqual(self._read(), Left(available=48 * MIB, killed=0))
        self._v2(limit=str(48 * MIB), usage=60 * MIB, inactive=MIB, active=MIB)
        self.assertEqual(self._read(), Left(available=0, killed=0))

    def test_a_pressure_file_without_its_counter_says_nothing_of_it(self) -> None:
        self._write("/proc/meminfo", _meminfo(51300))
        self._write("/proc/pressure/memory", "full avg10=0.85 total=30815820\n"
                                             "some avg10=0.87 avg60=1.59\n")
        self.assertEqual(self._read(), Left(available=51300 * 1024))

    def test_without_proc_self_cgroup_the_root_of_the_mount_is_the_process_s(
            self) -> None:
        self._write("/proc/meminfo", _meminfo(3_500_000))
        self._v2(limit=str(512 * MIB), usage=300 * MIB, own=False)
        self.assertEqual(self._given(physical=4 * GIB), 512 * MIB)


def _stalls(readings: Sequence[tuple[float, float | None]]) -> EngineReport:
    """A report that observed one tick at each ``(now, counter)`` in turn, the
    counter ``None`` where that tick could not read it — at a poll interval no gap
    between two of them makes a late tick of, since the `lag` line is not what is
    read here."""
    counters = iter([Left(available=MIB, stalled=counter)
                     for _now, counter in readings])
    report = EngineReport((), workers=1, poll_interval=3600.0,
                          limits=Limits(memory_limit=None),
                          resident=lambda: None, left=lambda: next(counters))
    for now, _counter in readings:
        report.observe(now, entries=0, waiting=[], late=[])
    return report


class StallShareTests(TestCase):
    """The share of the last ten minutes in which the machine stalled on memory:
    two readings of the kernel's counter, the tick's own and the latest that is ten
    minutes old or older, by the engine's clock (ADR-0095 decision 7)."""

    def test_the_window_is_the_ten_minutes_between_two_memory_lines(self) -> None:
        self.assertEqual(STALL_SECONDS, MEMORY_LINE_MINUTES * 60)

    def test_the_share_of_the_last_ten_minutes(self) -> None:
        """1.3 % of ten minutes: the counter rose by 7.8 seconds in them."""
        report = _stalls([(float(second), 100.0 + 0.013 * second)
                          for second in range(0, 901)])
        assert report.stalled is not None
        share, span = report.stalled
        self.assertAlmostEqual(share, 0.013)
        self.assertEqual(span, STALL_SECONDS)

    def test_what_is_older_than_ten_minutes_is_not_counted(self) -> None:
        """Twenty seconds of stall in the first five minutes, and none after: ten
        minutes from the start they are inside, five minutes later they are not."""
        readings = [(float(second), 100.0 + min(second, 300) / 15)
                    for second in range(0, 901)]
        report = _stalls(readings[:601])
        assert report.stalled is not None
        self.assertAlmostEqual(report.stalled[0], 20 / 600)
        report = _stalls(readings)
        self.assertEqual(report.stalled, (0.0, STALL_SECONDS))

    def test_a_young_process_says_the_share_of_what_it_has_read(self) -> None:
        report = _stalls([(float(second), 100.0 + 0.017 * second)
                          for second in range(0, 241)])
        assert report.stalled is not None
        share, span = report.stalled
        self.assertAlmostEqual(share, 0.017)
        self.assertEqual(span, 240.0)

    def test_one_reading_is_no_share(self) -> None:
        self.assertIsNone(_stalls([(0.0, 100.0)]).stalled)

    def test_a_tick_that_cannot_read_the_counter_keeps_the_share(self) -> None:
        report = _stalls([(0.0, 100.0), (60.0, 101.2), (61.0, None)])
        assert report.stalled is not None
        share, span = report.stalled
        self.assertAlmostEqual(share, 0.02)
        self.assertEqual(span, 60.0)

    def test_a_counter_read_lower_than_before_is_no_share_below_nothing(
            self) -> None:
        self.assertEqual(_stalls([(0.0, 100.0), (60.0, 99.0)]).stalled, (0.0, 60.0))

    def test_the_report_keeps_what_the_last_tick_read(self) -> None:
        report = _stalls([(0.0, 100.0), (1.0, 100.5)])
        self.assertEqual(report.left, Left(available=MIB, stalled=100.5))


class ReportFactTests(TestCase):
    """The engine child's `report` carries the figures as a fact, rewritten every
    tick beside the series', in the `memory` line's own words — and never a line."""

    def _report(self, resident: Resident | None, limits: Limits) -> EngineReport:
        report = EngineReport((), workers=1, poll_interval=1.0, limits=limits,
                              resident=lambda: resident, left=lambda: None)
        report.observe(0.0, entries=0, waiting=[], late=[])
        return report

    def test_both_figures_against_the_limit_and_the_machine(self) -> None:
        report = self._report(Resident(peak=369 * MIB, now=312 * MIB),
                              Limits(memory_limit=8 * GIB, machine_memory=16 * GIB))
        self.assertIn("- resident size 312 MiB, peak 369 MiB, of a limit of 8.0 GiB "
                      "(of the 16.0 GiB the machine gives the process)",
                      report.report().splitlines())
        self.assertNotIn("memory", [line.slug for line in report.lines()])

    def test_the_peak_alone_is_marked_as_the_peak(self) -> None:
        report = self._report(Resident(peak=369 * MIB),
                              Limits(memory_limit=8 * GIB, machine_memory=16 * GIB))
        self.assertIn("- peak resident size 369 MiB, of a limit of 8.0 GiB (of the "
                      "16.0 GiB the machine gives the process)",
                      report.report().splitlines())

    def test_no_limit_leaves_the_figures_alone(self) -> None:
        report = self._report(Resident(peak=369 * MIB, now=312 * MIB),
                              Limits(memory_limit=None))
        self.assertIn("- resident size 312 MiB, peak 369 MiB",
                      report.report().splitlines())

    def test_before_the_first_tick_there_is_no_figure(self) -> None:
        report = EngineReport((), workers=1, poll_interval=1.0,
                              limits=Limits(memory_limit=None),
                              resident=lambda: Resident(peak=MIB, now=MIB))
        self.assertNotIn("resident", report.report())

    def test_what_the_machine_has_left_stands_beside_the_process_s_figures(
            self) -> None:
        """A fact of its own after the process's, in the words of `/system` and the
        log — the second part joined as a sentence of a list of its own."""
        counters = iter([100.0, 100.0 + 0.017 * 600])
        report = EngineReport(
            (), workers=1, poll_interval=3600.0,
            limits=Limits(memory_limit=461 * MIB, machine_memory=512 * MIB),
            resident=lambda: Resident(peak=451 * MIB, now=445 * MIB),
            left=lambda: Left(available=41 * MIB, stalled=next(counters), killed=0))
        report.observe(0.0, entries=0, waiting=[], late=[])
        report.observe(600.0, entries=0, waiting=[], late=[])
        self.assertEqual(report.report().splitlines(), [
            "- resident size 445 MiB, peak 451 MiB, of a limit of 461 MiB (of the "
            "512 MiB the machine gives the process)",
            "- the machine has 41 MiB left; it stalled on memory for 1.7 % of the "
            "last 10m, and the kernel has ended no process of this cgroup"])
        # a fact and never a line: the one line here is the process's own
        self.assertEqual([line.slug for line in report.lines()], ["memory"])

    def test_where_the_platform_says_nothing_there_is_no_fact(self) -> None:
        report = EngineReport((), workers=1, poll_interval=1.0,
                              limits=Limits(memory_limit=None),
                              resident=lambda: Resident(peak=MIB),
                              left=lambda: None)
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertNotIn("machine has", report.report())


class MachineTextTests(TestCase):
    """What the machine has left in words, one implementation for the three places
    it stands (ADR-0095 decision 7): what is left, how long the machine stalled on
    memory, and under a limit how often the kernel has ended a process of this
    cgroup — each where there is one to say."""

    def test_the_three_parts_in_one_sentence(self) -> None:
        self.assertEqual(
            machine_text(Left(available=41 * MIB, killed=0), (0.017, 600.0)),
            "the machine has 41 MiB left, stalled on memory for 1.7 % of the last "
            "10m, and the kernel has ended no process of this cgroup")

    def test_under_no_limit_there_is_no_count(self) -> None:
        self.assertEqual(
            machine_text(Left(available=129 * MIB), (0.018, 600.0), joint="; it "),
            "the machine has 129 MiB left; it stalled on memory for 1.8 % of the "
            "last 10m")

    def test_before_a_second_reading_there_is_no_share(self) -> None:
        self.assertEqual(machine_text(Left(available=129 * MIB, stalled=32.0), None),
                         "the machine has 129 MiB left")
        self.assertEqual(machine_text(Left(available=41 * MIB, killed=0), None),
                         "the machine has 41 MiB left, and the kernel has ended no "
                         "process of this cgroup")

    def test_a_young_process_names_what_it_has_read(self) -> None:
        self.assertEqual(machine_text(Left(available=GIB), (0.012, 240.0)),
                         "the machine has 1.0 GiB left, stalled on memory for 1.2 % "
                         "of the last 4m")

    def test_ten_minutes_read_are_named_as_ten_minutes(self) -> None:
        """The oldest reading kept is the latest that is ten minutes old or older,
        so the span is a part of a tick past them — and named as the window."""
        self.assertEqual(machine_text(Left(available=GIB), (0.018, 600.9)),
                         "the machine has 1.0 GiB left, stalled on memory for 1.8 % "
                         "of the last 10m")

    def test_without_memavailable_the_machine_stalled_is_said(self) -> None:
        self.assertEqual(machine_text(Left(stalled=40.0), (0.018, 600.0)),
                         "the machine stalled on memory for 1.8 % of the last 10m")

    def test_nothing_to_say_is_none(self) -> None:
        self.assertIsNone(machine_text(None, None))
        self.assertIsNone(machine_text(Left(stalled=40.0), None))

    def test_the_count_in_words(self) -> None:
        self.assertEqual(killed_text(0),
                         "the kernel has ended no process of this cgroup")
        self.assertEqual(killed_text(1),
                         "the kernel has ended 1 process of this cgroup")
        self.assertEqual(killed_text(3),
                         "the kernel has ended 3 processes of this cgroup")


class RiseTextTests(TestCase):
    """What a rise says: the size's and the peak's, each only from 1 MiB, a fall
    never, and every run beside it named — five and a count."""

    def test_both_rises_in_one_phrase(self) -> None:
        self.assertEqual(
            rise_text(int(38.2 * MIB), int(12.1 * MIB), (), during="while it ran"),
            "resident +38.2 MiB, peak +12.1 MiB while it ran")

    def test_each_is_said_only_from_the_threshold(self) -> None:
        self.assertEqual(RISE_LOGGED, MIB)
        self.assertEqual(rise_text(MIB - 1, MIB, (), during="while it ran"),
                         "peak +1.0 MiB while it ran")
        self.assertEqual(rise_text(MIB, MIB - 1, (), during="while it ran"),
                         "resident +1.0 MiB while it ran")
        self.assertEqual(rise_text(MIB - 1, MIB - 1, ("/a",), during="while it ran"),
                         "")

    def test_a_fall_is_never_said(self) -> None:
        self.assertEqual(rise_text(-40 * MIB, 0, ("/a",), during="while it ran"), "")

    def test_the_runs_beside_it_are_named_five_and_a_count(self) -> None:
        self.assertEqual(rise_text(2 * MIB, 0, ("/b",), during="while it ran"),
                         "resident +2.0 MiB while it ran, beside /b")
        self.assertEqual(rise_text(2 * MIB, 0, ("/c", "/b"), during="while it ran"),
                         "resident +2.0 MiB while it ran, beside /b and /c")
        self.assertEqual(
            rise_text(2 * MIB, 0, ("/g", "/f", "/e", "/d", "/c", "/b", "/a"),
                      during="while it ran"),
            "resident +2.0 MiB while it ran, beside /a, /b, /c, /d, /e and 2 more")


class RunLineTests(TestCase):
    """A run's log line carries what rose while it ran, inside the parentheses
    beside the elapsed time: on Linux the size's rise and the peak's, on macOS the
    peak's — each from 1 MiB, a fall never."""

    def _line(self, meter: _Meter, **moves: int) -> str:
        check = _Moving(path="/web", meter=meter, **moves)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            _engine([check], meter).run_once()
        return _run_line(caught, "/web")

    def test_a_run_whose_size_rises_beneath_an_earlier_peak_carries_its_figure(
            self) -> None:
        """The Linux case: the process reached its high long ago, and a run that
        still holds 40 MiB when it ends moves no peak at all."""
        line = self._line(_Meter(now=350 * MIB, peak=400 * MIB), now=390 * MIB)
        self.assertRegex(line, r"^check /web: OK \(\d+ ms; resident \+40\.0 MiB "
                               r"while it ran\)$")

    def test_a_run_below_one_mebibyte_adds_nothing_to_its_line(self) -> None:
        line = self._line(_Meter(now=350 * MIB, peak=400 * MIB),
                          now=350 * MIB + RISE_LOGGED - 1)
        self.assertRegex(line, r"^check /web: OK \(\d+ ms\)$")

    def test_a_new_high_on_linux_carries_both(self) -> None:
        line = self._line(_Meter(now=350 * MIB, peak=400 * MIB),
                          now=450 * MIB, peak=450 * MIB)
        self.assertRegex(line, r"\(\d+ ms; resident \+100\.0 MiB, peak \+50\.0 MiB "
                               r"while it ran\)$")

    def test_a_fall_adds_nothing(self) -> None:
        line = self._line(_Meter(now=390 * MIB, peak=400 * MIB), now=350 * MIB)
        self.assertRegex(line, r"^check /web: OK \(\d+ ms\)$")

    def test_on_macos_the_peak_s_rise_is_the_figure(self) -> None:
        line = self._line(_Meter(now=None, peak=400 * MIB),
                          peak=400 * MIB + int(18.4 * MIB))
        self.assertRegex(line, r"\(\d+ ms; peak \+18\.4 MiB while it ran\)$")

    def test_on_macos_a_run_beneath_the_peak_shows_nothing(self) -> None:
        line = self._line(_Meter(now=None, peak=400 * MIB))
        self.assertRegex(line, r"^check /web: OK \(\d+ ms\)$")


class BesideTests(TestCase):
    """The rise is the process's: a run names every other run that was in flight at
    any point of it, and the same step stands on each of their lines."""

    def _overlap(self, first: _Moving, second: _Moving, meter: _Meter,
                 before: Sequence[Check] = ()) -> Callable[[str], str]:
        engine = _engine([*before, first, second], meter)
        items = {id(item.check): item for item in engine._scheduled}
        with self.assertLogs(LOGGER, level="INFO") as caught:
            for check in before:
                engine._execute(items[id(check)], once=True)
            runner = threading.Thread(
                target=engine._execute, args=(items[id(first)],),
                kwargs={"once": True})
            runner.start()
            assert first._started is not None and first._release is not None
            self.assertTrue(first._started.wait(timeout=5))
            engine._execute(items[id(second)], once=True)
            first._release.set()
            runner.join(timeout=5)
        return lambda path: _run_line(caught, path)

    def test_two_runs_in_flight_name_each_other_and_share_the_step(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        early = _Moving(path="/early", meter=meter)
        waiting = _Moving(path="/a", meter=meter, started=threading.Event(),
                          release=threading.Event())
        allocating = _Moving(path="/b", meter=meter, now=370 * MIB)
        line = self._overlap(waiting, allocating, meter, before=[early])
        self.assertRegex(line("/b"), r"; resident \+20\.0 MiB while it ran, "
                                     r"beside /a\)$")
        self.assertRegex(line("/a"), r"; resident \+20\.0 MiB while it ran, "
                                     r"beside /b\)$")
        self.assertRegex(line("/early"), r"^check /early: OK \(\d+ ms\)$")

    def test_two_checks_on_one_mount_are_told_apart_by_their_type(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        waiting = _Alpha(path="/host", meter=meter, started=threading.Event(),
                         release=threading.Event())
        allocating = _Beta(path="/host", meter=meter, now=370 * MIB)
        engine = _engine([waiting, allocating], meter)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            runner = threading.Thread(target=engine._execute,
                                      args=(engine._scheduled[0],),
                                      kwargs={"once": True})
            runner.start()
            assert waiting._started is not None and waiting._release is not None
            self.assertTrue(waiting._started.wait(timeout=5))
            engine._execute(engine._scheduled[1], once=True)
            waiting._release.set()
            runner.join(timeout=5)
        lines = _messages(caught, "check /host: ")
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(any(line.endswith("beside /host (alpha))") for line in lines),
                        lines)
        self.assertTrue(any(line.endswith("beside /host (beta))") for line in lines),
                        lines)


class _Rising(Check):
    """A check whose every run leaves the meter's size ``by`` higher than it found
    it, and its peak raised to match."""

    type_name = "rising"

    def __init__(self, *, meter: _Meter, by: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._meter = meter
        self._by = by

    def measure(self) -> Sequence[Measurement]:
        assert self._meter.now is not None
        size = self._meter.now + self._by
        self._meter.move(now=size, peak=max(self._meter.peak, size))
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class _Collector:
    """The cycle collector as a test scripts it: every call takes ``took`` seconds
    on the engine's clock and gives back ``frees`` of the meter's size, and is
    counted. With ``hold``, the first call waits for it, having set ``started``."""

    def __init__(self, clock: list[float], meter: _Meter, *, took: float = 0.018,
                 frees: int = 0, hold: threading.Event | None = None) -> None:
        self.calls = 0
        self._clock = clock
        self._meter = meter
        self._took = took
        self._frees = frees
        self._hold = hold
        self.started = threading.Event()

    def __call__(self) -> int:
        self.calls += 1
        if self._hold is not None and self.calls == 1:
            self.started.set()
            self._hold.wait(timeout=5)
        self._clock[0] += self._took
        if self._frees and self._meter.now is not None:
            self._meter.move(now=self._meter.now - self._frees)
        return 0


class CollectionTests(TestCase):
    """A run that rose by 1 MiB or more is followed by a collection, said on that
    run's line after the rise, and never for more than a hundredth of the time: one
    that took *p* is followed by none for a hundred times *p* (ADR-0095 decision 8)."""

    def _one(self, check: Check, meter: _Meter, collector: _Collector,
             clock: list[float]) -> str:
        engine = _engine([check], meter, clock=lambda: clock[0], collect=collector)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine.run_once()
        return _run_line(caught, check.path)

    def test_the_spacing_is_a_hundred_times_the_collection(self) -> None:
        self.assertEqual(COLLECTION_SPACING, 100)
        self.assertEqual(len(MINUS), 1)

    def test_the_engine_collects_with_the_cycle_collector(self) -> None:
        self.assertIs(Engine([], StatusTree())._collect, gc.collect)

    def test_a_run_that_rose_is_followed_by_one_said_on_its_line(self) -> None:
        clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)
        collector = _Collector(clock, meter, frees=31 * MIB)
        line = self._one(_Moving(path="/aws", meter=meter, now=390 * MIB), meter,
                         collector, clock)
        self.assertEqual(collector.calls, 1)
        self.assertEqual(line, "check /aws: OK (0 ms; resident +40.0 MiB while it "
                               "ran; collected after it in 18 ms, resident "
                               f"{MINUS}31.0 MiB)")

    def test_a_rise_from_a_mebibyte_asks_for_one_and_below_it_none(self) -> None:
        for rise, calls in ((RISE_LOGGED, 1), (RISE_LOGGED - 1, 0)):
            clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)
            collector = _Collector(clock, meter)
            line = self._one(_Moving(path="/aws", meter=meter, now=350 * MIB + rise),
                             meter, collector, clock)
            self.assertEqual(collector.calls, calls, rise)
            self.assertEqual("collected after it" in line, calls == 1, line)

    def test_a_fall_below_a_mebibyte_is_not_said(self) -> None:
        clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)
        collector = _Collector(clock, meter, frees=RISE_LOGGED - 1)
        line = self._one(_Moving(path="/aws", meter=meter, now=390 * MIB), meter,
                         collector, clock)
        self.assertTrue(line.endswith("; collected after it in 18 ms)"), line)

    def test_on_macos_a_run_that_raised_the_peak_is_followed_by_one(self) -> None:
        """The peak's rise is a run's rise there, and the time is all the clause
        can say: no size now falls."""
        clock, meter = [0.0], _Meter(now=None, peak=400 * MIB)
        collector = _Collector(clock, meter)
        line = self._one(_Moving(path="/aws", meter=meter,
                                 peak=400 * MIB + int(18.4 * MIB)),
                         meter, collector, clock)
        self.assertEqual(collector.calls, 1)
        self.assertEqual(line, "check /aws: OK (0 ms; peak +18.4 MiB while it ran; "
                               "collected after it in 18 ms)")

    def test_on_macos_a_run_beneath_the_peak_is_followed_by_none(self) -> None:
        clock, meter = [0.0], _Meter(now=None, peak=400 * MIB)
        collector = _Collector(clock, meter)
        self._one(_Moving(path="/aws", meter=meter), meter, collector, clock)
        self.assertEqual(collector.calls, 0)

    def test_on_linux_a_peak_the_run_gave_back_asks_for_none(self) -> None:
        """The size where it was and the peak 50 MiB higher: a spike freed before
        the run ended, which left nothing for the collector."""
        clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)
        collector = _Collector(clock, meter)
        line = self._one(_Moving(path="/aws", meter=meter, peak=450 * MIB), meter,
                         collector, clock)
        self.assertEqual(collector.calls, 0)
        self.assertTrue(line.endswith("(0 ms; peak +50.0 MiB while it ran)"), line)

    def test_none_follows_another_sooner_than_a_hundred_times_its_length(
            self) -> None:
        """One that took 20 ms at 0 s is followed by none until 2.02 s."""
        clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)
        collector = _Collector(clock, meter, took=0.02)
        check = _Rising(path="/aws", meter=meter, by=40 * MIB)
        engine = _engine([check], meter, clock=lambda: clock[0], collect=collector)
        lines = []
        for moment in (0.0, 2.0, 2.0199, 2.0201):
            clock[0] = moment
            with self.assertLogs(LOGGER, level="INFO") as caught:
                engine.run_once()
            lines.append(_run_line(caught, "/aws"))
        self.assertEqual(collector.calls, 2)
        self.assertEqual(["collected after it" in line for line in lines],
                         [True, False, False, True])

    def test_none_starts_while_one_runs(self) -> None:
        """Two runs that rose end together: the second finds the first's collection
        under way and is followed by none."""
        clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)
        hold = threading.Event()
        collector = _Collector(clock, meter, hold=hold)
        first = _Rising(path="/first", meter=meter, by=40 * MIB)
        second = _Rising(path="/second", meter=meter, by=40 * MIB)
        engine = _engine([first, second], meter, clock=lambda: clock[0],
                         collect=collector)
        items = {item.check.path: item for item in engine._scheduled}
        with self.assertLogs(LOGGER, level="INFO") as caught:
            runner = threading.Thread(target=engine._execute,
                                      args=(items["/first"],), kwargs={"once": True})
            runner.start()
            self.assertTrue(collector.started.wait(timeout=5))
            engine._execute(items["/second"], once=True)
            hold.set()
            runner.join(timeout=5)
        self.assertEqual(collector.calls, 1)
        self.assertIn("collected after it", _run_line(caught, "/first"))
        self.assertNotIn("collected", _run_line(caught, "/second"))

    def test_a_run_the_stop_abandoned_is_followed_by_none(self) -> None:
        clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)
        collector = _Collector(clock, meter)
        check = _Moving(path="/aws", meter=meter, now=390 * MIB)
        engine = _engine([check], meter, clock=lambda: clock[0], collect=collector)
        engine._stop.set()
        engine._execute(engine._scheduled[0], once=True)
        self.assertEqual(collector.calls, 0)

    def test_a_read_that_failed_asks_for_none(self) -> None:
        size, peak = Resident(peak=400 * MIB, now=350 * MIB), Resident(peak=450 * MIB)
        self.assertFalse(_asks_for_a_collection(None, size))
        self.assertFalse(_asks_for_a_collection(size, None))
        self.assertFalse(_asks_for_a_collection(size, peak))
        self.assertFalse(_asks_for_a_collection(peak, size))

    def test_a_collector_that_raises_leaves_the_run_as_it_was(self) -> None:
        clock, meter = [0.0], _Meter(now=350 * MIB, peak=400 * MIB)

        def broken() -> int:
            raise RuntimeError("no")

        check = _Moving(path="/aws", meter=meter, now=390 * MIB)
        engine = _engine([check], meter, clock=lambda: clock[0], collect=broken)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine.run_once()
        self.assertEqual(_run_line(caught, "/aws"),
                         "check /aws: OK (0 ms; resident +40.0 MiB while it ran)")
        self.assertEqual(_messages(caught, "engine: the collection after a run"),
                         ["engine: the collection after a run raised"])
        node = engine._tree.snapshot("/aws")
        assert node is not None
        self.assertEqual(node.own_code, StatusCode.OK)


class _Sweeping(MemoryStore):
    """A series store whose sweep, on the tick, moves the meter."""

    def __init__(self, meter: _Meter, now: int) -> None:
        super().__init__()
        self._meter = meter
        self._now = now

    def sweep(self, keep: Any, *, ceiling: int | None = None) -> Any:
        self._meter.move(now=self._now)
        return super().sweep(keep, ceiling=ceiling)


class TickLineTests(TestCase):
    """The tick is measured the same way, and a tick that raised either figure by
    1 MiB or more says so on a line of its own — whether it ran the state layer's
    interval save, and which runs were in flight."""

    def test_a_tick_s_state_save_is_said(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        clock = [0.0]
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=60,
                               clock=lambda: clock[0])

            def produce() -> object:
                meter.move(now=362 * MIB + int(0.3 * MIB), peak=412 * MIB)
                return {"a": 1}

            state.keep("a.json", produce)
            engine = _engine([], meter, state=state)
            with self.assertLogs(LOGGER, level="INFO") as caught:
                engine._guarded_tick(submit=False)
                clock[0] = 61.0
                engine._guarded_tick(submit=False)
        self.assertEqual(_messages(caught, "engine: resident"),
                         ["engine: resident +12.3 MiB, peak +12.0 MiB during the tick, "
                          "including a state save"])

    def test_a_tick_without_a_save_is_said_as_the_tick(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        engine = _engine([], meter, series=_Sweeping(meter, 355 * MIB))
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine._guarded_tick(submit=False)
        self.assertEqual(_messages(caught, "engine: resident"),
                         ["engine: resident +5.0 MiB during the tick"])

    def test_a_quiet_tick_says_nothing(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        engine = _engine([], meter)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine._guarded_tick(submit=False)
        self.assertEqual(_messages(caught, "engine: resident"), [])
        self.assertEqual(_messages(caught, "engine: peak"), [])


def _on_the_logs_clock(hour: int, minute: int, second: int = 0) -> datetime:
    """The instant at which the clock the log is stamped in — the configured
    zone's — reads that time of 27 September 2026: the clock whose ten-minute marks
    the line keeps."""
    return datetime(2026, 9, 27, hour, minute, second, tzinfo=config.tzinfo)


class TenMinuteLineTests(TestCase):
    """The log carries the card's figures on the first tick past each ten-minute
    mark of the clock the log is stamped in, once at the first tick as the baseline
    and once at the stop."""

    def test_the_baseline_the_marks_and_the_stop(self) -> None:
        self.assertEqual(MEMORY_LINE_MINUTES, 10)
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        wall = [_on_the_logs_clock(10, 3, 0)]
        engine = _engine([], meter, wall=lambda: wall[0],
                         limits=Limits(memory_limit=8 * GIB))
        with self.assertLogs(LOGGER, level="INFO") as caught:
            for moment in [(10, 3, 0), (10, 7, 0), (10, 10, 1), (10, 19, 59),
                           (10, 20, 0)]:
                wall[0] = _on_the_logs_clock(*moment)
                engine._guarded_tick(submit=False)
            meter.move(now=360 * MIB)
            engine.stop(trigger="test")
        lines = _messages(caught, "engine: memory")
        expected = ("resident size {} MiB, peak 400 MiB, of a limit of 8.0 GiB; the "
                    "series hold 0 B, the tree ")
        self.assertEqual(len(lines), 4, lines)
        self.assertTrue(lines[0].startswith(
            "engine: memory at the start — " + expected.format(350)), lines[0])
        self.assertTrue(lines[1].startswith(
            "engine: memory — " + expected.format(350)), lines[1])
        self.assertTrue(lines[2].startswith("engine: memory — "), lines[2])
        self.assertTrue(lines[3].startswith(
            "engine: memory at the stop — " + expected.format(360)), lines[3])
        self.assertRegex(lines[0], r"the tree [\d,]+ entr(y|ies)$")

    def _two_ticks(self, *, configured: str, machine: str) -> list[str]:
        """The memory lines of two ticks either side of 04:25:00 UTC, on a machine
        in ``machine`` whose settings name ``configured``."""
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        wall = [datetime(2026, 9, 27, 4, 24, 59, tzinfo=UTC)]
        engine = _engine([], meter, wall=lambda: wall[0])
        try:
            with patch.dict(os.environ, {"TZ": machine}), \
                    patch.object(engine_module, "config",
                                 replace(config, timezone=configured)):
                time.tzset()
                with self.assertLogs(LOGGER, level="INFO") as caught:
                    engine._guarded_tick(submit=False)
                    wall[0] = datetime(2026, 9, 27, 4, 25, 1, tzinfo=UTC)
                    engine._guarded_tick(submit=False)
        finally:
            time.tzset()          # back to whatever the real environment says
        return _messages(caught, "engine: memory")

    @skipIf(not hasattr(time, "tzset"), "no tzset on this platform")
    def test_the_marks_are_those_of_the_clock_the_log_is_stamped_in(self) -> None:
        """The engine's clock answers an instant, and the marks are those of the
        configured zone, in which the log is stamped (ADR-0120 decision 9) — not of
        the machine's clock.

        **Asserted where the two clocks' marks differ, on purpose**: in a zone whose
        offset is a multiple of ten minutes — UTC, Berlin — a mark of that clock is
        a mark of UTC as well, so reading the instant on any of them would pass
        there. In Kathmandu, at +05:45, 10:09:59 and 10:10:01 are one mark apart,
        and both fall in one ten minutes of UTC: 04:24:59 and 04:25:01.
        """
        lines = self._two_ticks(configured="Asia/Kathmandu", machine="UTC")
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith("engine: memory at the start — "),
                        lines[0])
        self.assertTrue(lines[1].startswith("engine: memory — "), lines[1])
        # and a machine in Kathmandu whose log is stamped in UTC passes no mark
        lines = self._two_ticks(configured="UTC", machine="Asia/Kathmandu")
        self.assertEqual(len(lines), 1, lines)

    def test_macos_begins_with_the_peak(self) -> None:
        meter = _Meter(now=None, peak=369 * MIB)
        engine = _engine([], meter,
                         wall=lambda: datetime(2026, 9, 27, 10, 3, tzinfo=UTC))
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine._guarded_tick(submit=False)
        lines = _messages(caught, "engine: memory")
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(
            "engine: memory at the start — peak resident size 369 MiB; the series "
            "hold 0 B"), lines[0])

    def test_what_the_machine_has_left_follows_the_process_s_figures(self) -> None:
        """At the start there is one reading of the stall counter and no share; at
        the next mark, ten minutes on, the share of them."""
        meter = _Meter(now=445 * MIB, peak=451 * MIB)
        clock, wall = [0.0], [_on_the_logs_clock(10, 3, 0)]
        counter = [100.0]
        engine = _engine([], meter, clock=lambda: clock[0], wall=lambda: wall[0],
                         limits=Limits(memory_limit=461 * MIB,
                                       machine_memory=512 * MIB),
                         left=lambda: Left(available=41 * MIB, stalled=counter[0],
                                           killed=0))
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine._guarded_tick(submit=False)
            clock[0], wall[0] = 600.0, _on_the_logs_clock(10, 13, 0)
            counter[0] = 100.0 + 0.017 * 600
            engine._guarded_tick(submit=False)
        lines = _messages(caught, "engine: memory")
        self.assertEqual(len(lines), 2, lines)
        process = ("resident size 445 MiB, peak 451 MiB, of a limit of 461 MiB; ")
        self.assertTrue(lines[0].startswith(
            "engine: memory at the start — " + process + "the machine has 41 MiB "
            "left, and the kernel has ended no process of this cgroup; the series "
            "hold 0 B, the tree "), lines[0])
        self.assertTrue(lines[1].startswith(
            "engine: memory — " + process + "the machine has 41 MiB left, stalled "
            "on memory for 1.7 % of the last 10m, and the kernel has ended no "
            "process of this cgroup; the series hold 0 B, the tree "), lines[1])


class SystemRowTests(TestCase):
    """`/system`'s engine block carries the figures as the fourth row of the card
    that holds the entries and the series against their limits."""

    @staticmethod
    def _render(info: Any) -> str:
        from flask import render_template

        from little_sister import app as app_module
        with app_module.app.test_request_context():
            return render_template("_system_info.html", info=info)

    def _row(self, meter: _Meter | None, limits: Limits, label: str) -> str:
        engine = Engine([], StatusTree(), resident=meter or (lambda: None),
                        limits=limits, left=lambda: None)
        if meter is not None:
            engine._observe(1.0)
        body = self._render(engine.info())
        self.assertIn(label, body)
        return re.sub(r"\s+", " ", body.split(label, 1)[1].split("</div></div>")[0])

    def test_the_size_its_peak_the_limit_and_the_machine(self) -> None:
        row = self._row(_Meter(now=312 * MIB, peak=369 * MIB),
                        Limits(memory_limit=8 * GIB, machine_memory=16 * GIB),
                        "Resident size")
        self.assertIn("312 MiB", row)
        self.assertIn("of 8.0 GiB · peak 369 MiB · the machine gives the process "
                      "16.0 GiB", row)

    def test_the_peak_alone_is_labelled_as_the_peak(self) -> None:
        row = self._row(_Meter(now=None, peak=369 * MIB),
                        Limits(memory_limit=8 * GIB, machine_memory=16 * GIB),
                        "Peak resident size")
        self.assertIn("369 MiB", row)
        self.assertNotIn("peak 369", row)

    def test_before_the_first_tick_the_row_says_nothing_is_known(self) -> None:
        row = self._row(None, Limits(memory_limit=None), "Resident size")
        self.assertIn("—", row)

    def test_the_page_names_what_the_last_tick_measured(self) -> None:
        meter = _Meter(now=312 * MIB, peak=369 * MIB)
        engine = Engine([], StatusTree(), resident=meter,
                        limits=Limits(memory_limit=8 * GIB, machine_memory=16 * GIB))
        engine._observe(1.0)
        meter.move(now=500 * MIB, peak=500 * MIB)
        info = engine.info()
        self.assertEqual((info.resident, info.resident_peak, info.memory_limit,
                          info.machine_memory),
                         (312 * MIB, 369 * MIB, 8 * GIB, 16 * GIB))

    def _left_row(self, readings: Sequence[Left]) -> str:
        """The fifth row after one tick observed per reading, ten minutes apart."""
        given = iter(readings)
        engine = Engine([], StatusTree(), resident=_Meter(now=445 * MIB,
                                                         peak=451 * MIB),
                        limits=Limits(memory_limit=461 * MIB,
                                      machine_memory=512 * MIB),
                        left=lambda: next(given))
        for tick in range(len(readings)):
            engine._observe(600.0 * tick)
        body = self._render(engine.info())
        self.assertIn("Left on the machine", body)
        return re.sub(r"\s+", " ", body.split("Left on the machine", 1)[1]
                      .split("</div></div>")[0])

    def test_what_the_machine_has_left_is_the_fifth_row(self) -> None:
        row = self._left_row([Left(available=41 * MIB, stalled=100.0, killed=0),
                              Left(available=41 * MIB, stalled=110.2, killed=0)])
        self.assertIn("41 MiB", row)
        # set off from the figure, which nothing beside it qualifies
        self.assertIn('<span class="text-muted">· stalled on memory for 1.7 % of the '
                      "last 10m · the kernel has ended no process of this cgroup", row)

    def test_before_a_second_reading_the_row_has_no_share(self) -> None:
        row = self._left_row([Left(available=41 * MIB, stalled=100.0, killed=1)])
        self.assertIn("41 MiB", row)
        self.assertIn('<span class="text-muted">· the kernel has ended 1 process of '
                      "this cgroup", row)
        self.assertNotIn("stalled", row)

    def test_with_nothing_beside_the_figure_nothing_sets_it_off(self) -> None:
        row = self._left_row([Left(available=129 * MIB)])
        self.assertIn('129 MiB <span class="text-muted"></span>', row)

    def test_where_the_platform_says_nothing_there_is_no_row(self) -> None:
        engine = Engine([], StatusTree(), resident=_Meter(now=None, peak=369 * MIB),
                        limits=Limits(memory_limit=8 * GIB), left=lambda: None)
        engine._observe(1.0)
        self.assertNotIn("Left on the machine", self._render(engine.info()))
        self.assertIsNone(engine.info().machine_left)


class StateTickTests(TestCase):
    """`StateLayer.tick()` says whether it ran the interval save, so the tick's line
    can."""

    def test_only_the_tick_that_saves_says_so(self) -> None:
        clock = [0.0]
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=60,
                               clock=lambda: clock[0])
            state.keep("a.json", lambda: {"a": 1})
            self.assertFalse(state.tick())      # the first only starts the interval
            clock[0] = 30.0
            self.assertFalse(state.tick())
            clock[0] = 61.0
            self.assertTrue(state.tick())
            self.assertFalse(state.tick())

