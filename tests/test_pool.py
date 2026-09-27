"""``little_sister.pool`` — daemon threads the interpreter does not join (ADR-0088)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from concurrent.futures import CancelledError, as_completed

import pytest

from little_sister.pool import DaemonPool
from tests.running import subprocess_env


def test_submitted_work_runs_and_answers_through_a_future() -> None:
    pool = DaemonPool(2, "test")
    futures = [pool.submit(pow, 2, n) for n in range(5)]
    assert sorted(future.result(timeout=5) for future in as_completed(futures)) == [
        1, 2, 4, 8, 16]
    pool.shutdown()


def test_a_raising_task_carries_its_exception() -> None:
    pool = DaemonPool(1, "test")
    future = pool.submit(int, "not a number")
    with pytest.raises(ValueError):
        future.result(timeout=5)
    pool.shutdown()


def test_shutdown_cancels_what_is_queued_and_does_not_wait() -> None:
    running = threading.Event()
    held = threading.Event()

    def hold() -> bool:
        running.set()
        return held.wait(10)

    pool = DaemonPool(1, "test")
    busy = pool.submit(hold)
    # The one thread has taken it before anything queues behind it. A task no thread
    # has taken yet is queued too, and the shutdown cancels it — which on 3.11, whose
    # submitting thread kept the GIL through both submits and the shutdown, was
    # every run.
    assert running.wait(5)
    queued = pool.submit(pow, 2, 3)
    started = time.monotonic()
    pool.shutdown(wait=False, cancel_futures=True)
    assert time.monotonic() - started < 1.0
    assert queued.cancelled()
    with pytest.raises(CancelledError):
        queued.result(timeout=1)
    held.set()
    assert busy.result(timeout=5) is True


def test_nothing_is_taken_after_shutdown() -> None:
    pool = DaemonPool(1, "test")
    pool.shutdown()
    with pytest.raises(RuntimeError):
        pool.submit(pow, 2, 3)


def test_a_task_in_flight_does_not_hold_the_interpreter_s_exit() -> None:
    """The standard pool's exit hook joins every thread it started, whatever its
    daemon flag; this one's threads are left to the interpreter."""
    script = textwrap.dedent("""
        import threading, time
        from little_sister.pool import DaemonPool
        pool = DaemonPool(2, "test")
        pool.submit(threading.Event().wait)
        pool.submit(threading.Event().wait)
        pool.submit(print, "queued work does not run at exit either")
        time.sleep(0.5)
        print("leaving", flush=True)
        """)
    with tempfile.TemporaryDirectory() as directory:
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-c", script], cwd=directory,
                              env=subprocess_env(),
                              capture_output=True, text=True, timeout=20)
    assert done.stdout == "leaving\n", done.stderr[-3000:]
    assert time.monotonic() - started < 6.0
