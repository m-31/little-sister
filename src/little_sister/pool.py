"""A thread pool whose threads the interpreter does not join (ADR-0088 decision 1).

``concurrent.futures`` registers an exit hook that runs before ``atexit`` and joins
every thread a ``ThreadPoolExecutor`` started — whatever its daemon flag — draining
the work already queued: measured on CPython 3.14.6, thirty queued one-second tasks
on six threads all ran, and the exit waited five seconds. For the engine that meant
a check in flight held the stop for as long as it ran; for the links probe, a pass
held it for as long as its hosts took to answer.

:class:`DaemonPool` is the same interface — a :class:`concurrent.futures.Executor`,
so :func:`~concurrent.futures.as_completed`, ``cancel`` and ``result`` work on what
it hands back — over a fixed number of **daemon** threads nothing joins. A task in
flight at the interpreter's exit is left there, and what it started ends with the
instance's stop (:func:`little_sister.process.end_all`); a task still queued never
runs.
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any, TypeVar

_T = TypeVar("_T")

_Task = tuple[Future[Any], Callable[..., Any], tuple[Any, ...], dict[str, Any]]


class DaemonPool(Executor):
    """``workers`` daemon threads, named ``<name>_<n>``, fed from one queue."""

    def __init__(self, workers: int, name: str) -> None:
        self._queue: queue.SimpleQueue[_Task | None] = queue.SimpleQueue()
        self._shut = False
        self._guard = threading.Lock()
        self._threads = [threading.Thread(target=self._work, name=f"{name}_{number}",
                                          daemon=True)
                         for number in range(max(1, workers))]
        for thread in self._threads:
            thread.start()

    def submit(self, fn: Callable[..., _T], /, *args: Any,
               **kwargs: Any) -> Future[_T]:
        with self._guard:
            if self._shut:
                raise RuntimeError("cannot schedule new work after the pool's shutdown")
            future: Future[_T] = Future()
            self._queue.put((future, fn, args, kwargs))
        return future

    def _work(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                return
            future, fn, args, kwargs = task
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = fn(*args, **kwargs)
            except BaseException as error:
                future.set_exception(error)
            else:
                future.set_result(result)

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        """Take nothing more; with ``cancel_futures``, cancel what is queued, and
        let each thread leave once it is idle. ``wait`` is taken for the
        :class:`~concurrent.futures.Executor` interface and changes nothing: this
        pool never waits for a task in flight, which is the point of it."""
        with self._guard:
            if self._shut:
                return
            self._shut = True
        if cancel_futures:
            while True:
                try:
                    task = self._queue.get_nowait()
                except queue.Empty:
                    break
                if task is not None:
                    task[0].cancel()
        for _ in self._threads:
            self._queue.put(None)


__all__ = ["DaemonPool"]
