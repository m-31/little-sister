"""``little_sister.process`` — a process a check starts ends with it (ADR-0089).

Every process here is a local ``/bin/sh`` or this interpreter; nothing reaches the
network.
"""
from __future__ import annotations

import itertools
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from little_sister import process
from little_sister.process import Ended, NotStarted, run
from little_sister.transport import Deadline, DeadlineExceeded


def _alive(pid: int) -> bool:
    """Whether ``pid`` is a running process — a zombie waiting for its reaper is not."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii") as stat:
            return stat.read().split(") ", 1)[1][0] != "Z"
    except OSError:
        return True


def _gone(pid: int, seconds: float = 4.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not _alive(pid):
            return True
        time.sleep(0.02)
    return not _alive(pid)


def _pid_in(marker: Path, seconds: float = 3.0) -> int:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if marker.exists() and marker.read_text().strip():
            return int(marker.read_text())
        time.sleep(0.02)
    raise AssertionError(f"nothing wrote a pid into {marker}")


def test_an_exit_is_a_fact_with_both_streams() -> None:
    done = run(["/bin/sh", "-c", "echo out; echo err >&2; exit 3"], timeout=5)
    assert done.ended is Ended.EXITED
    assert done.status == 3
    assert (done.stdout, done.stderr) == (b"out\n", b"err\n")
    assert not done.stdout_cut and not done.stderr_cut
    assert done.seconds >= 0


def test_stdin_is_dev_null() -> None:
    done = run(["/bin/sh", "-c", "cat; echo done"], timeout=5)
    assert (done.ended, done.stdout) == (Ended.EXITED, b"done\n")


def test_the_bound_ends_the_whole_group(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    started = time.monotonic()
    done = run(["/bin/sh", "-c", f"sleep 41 & echo $! > {marker}; wait"], timeout=0.5)
    assert done.ended is Ended.BOUND
    assert time.monotonic() - started < 4
    assert _gone(_pid_in(marker)), "the shell's child outlived the bound"


def test_what_the_command_leaves_behind_ends_with_it(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    command = f"sleep 42 & echo $! > {marker}; echo left"
    done = run(["/bin/sh", "-c", command], timeout=5)
    assert (done.ended, done.stdout) == (Ended.EXITED, b"left\n")
    assert _gone(_pid_in(marker)), "a background child outlived the run"


def test_a_stream_over_the_cap_is_cut_and_says_so() -> None:
    done = run(["/bin/sh", "-c", "head -c 300000 /dev/zero"], timeout=5, max_bytes=1000)
    assert done.ended is Ended.EXITED
    assert len(done.stdout) == 1000
    assert done.stdout_cut and not done.stderr_cut


def test_a_deadline_clamps_the_timeout() -> None:
    started = time.monotonic()
    done = run(["/bin/sh", "-c", "sleep 30"], timeout=30, deadline=Deadline(0.4))
    assert done.ended is Ended.BOUND
    assert time.monotonic() - started < 4


def test_a_spent_deadline_starts_nothing() -> None:
    clock = itertools.chain([0.0], itertools.repeat(5.0))
    spent = Deadline(1.0, clock=clock.__next__)
    with pytest.raises(DeadlineExceeded):
        run(["/bin/sh", "-c", "true"], timeout=5, deadline=spent)


def test_a_command_that_cannot_start_raises_not_started() -> None:
    with pytest.raises(NotStarted) as caught:
        run(["/nonexistent/little-sister-no-such-command"], timeout=5)
    assert isinstance(caught.value.__cause__, OSError)


def test_a_command_string_is_refused() -> None:
    with pytest.raises(TypeError):
        run("echo hi", timeout=5)  # type: ignore[arg-type]


def test_the_stop_ends_every_running_group(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    answers: list[process.Finished] = []
    worker = threading.Thread(target=lambda: answers.append(
        run(["/bin/sh", "-c", f"sleep 43 & echo $! > {marker}; wait"], timeout=60)))
    worker.start()
    child = _pid_in(marker)
    assert process.end_all() == 1
    worker.join(5)
    assert answers and answers[0].ended is Ended.STOP
    assert _gone(child)


def test_nothing_starts_once_the_stop_has_come() -> None:
    process.end_all()
    with pytest.raises(NotStarted, match="stopping"):
        run(["/bin/sh", "-c", "true"], timeout=5)


def test_a_hang_up_line_is_a_pipe_held_for_the_run() -> None:
    """What an ``ssh`` client needs: stdin a pipe that stays open while the run lasts,
    so that the remote side sees the connection close when the run ends
    (ADR-0089); without it, stdin is ``/dev/null``."""
    probe = ["/bin/sh", "-c",
             "if [ -p /dev/stdin ]; then echo pipe; else echo other; fi"]
    assert run(probe, timeout=5, hang_up=True).stdout == b"pipe\n"
    assert run(probe, timeout=5).stdout == b"other\n"


def test_what_is_sent_reaches_stdin_and_stdin_then_closes() -> None:
    """``send`` is written to the command's stdin, and stdin is closed after it, so a
    command that reads to the end finishes."""
    done = run(["/bin/sh", "-c", "cat; echo end"], timeout=5, send=b"sent\n")
    assert (done.ended, done.stdout) == (Ended.EXITED, b"sent\nend\n")


def test_more_than_a_pipe_holds_is_sent_while_the_output_is_read() -> None:
    """Sending and reading go on together, so a command that answers as it reads
    never waits on a full pipe while the run waits on it."""
    data = bytes(range(256)) * 1024     # 256 KiB, four times a Linux pipe
    done = run(["/bin/sh", "-c", "cat"], timeout=10, send=data)
    assert done.ended is Ended.EXITED
    assert done.stdout == data


#: Reads four bytes, then says whether stdin is still open half a second later.
_OPEN_AFTER_FOUR = (
    "import os, select\n"
    "got = b''\n"
    "while len(got) < 4:\n"
    "    got += os.read(0, 4 - len(got))\n"
    "ready = select.select([0], [], [], 0.5)[0]\n"
    "print(got.decode(), 'closed' if ready and not os.read(0, 1) else 'open')\n")


def test_with_a_hang_up_line_what_is_sent_comes_first_and_stdin_stays_open() -> None:
    """What an ``ssh`` run needs: its script ahead of the hang-up line, which then
    stays open for the rest of the run (ADR-0089 decision 4)."""
    probe = [sys.executable, "-c", _OPEN_AFTER_FOUR]
    assert run(probe, timeout=5, send=b"head", hang_up=True).stdout == b"head open\n"
    assert run(probe, timeout=5, send=b"head").stdout == b"head closed\n"


def test_a_command_that_reads_nothing_of_what_is_sent_ends_as_itself() -> None:
    """Whatever it did not read is dropped: its end is its own, not a broken pipe's."""
    done = run(["/bin/sh", "-c", "exit 3"], timeout=5, send=b"x" * (1 << 20))
    assert (done.ended, done.status) == (Ended.EXITED, 3)
