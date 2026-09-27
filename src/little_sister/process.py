"""A process a check starts, run to its end and ended with the run (ADR-0089).

:mod:`little_sister.fetch` is the request a check makes; this is the process it
starts, and it settles the same kind of questions once, for every caller:

* **An argument vector, never a guess about a shell.** A shell command is
  ``["/bin/sh", "-c", command]``, said by the caller.
* **A session and a process group of its own, and ``/dev/null`` for stdin**, so that
  what the command starts is in one group the run can end, and nothing it runs waits
  on a terminal or reads somebody else's input. ``send`` puts bytes on stdin instead,
  written while the output is read, and stdin is closed after them. With
  ``hang_up=True`` stdin is a pipe held open for the whole run, after whatever was
  sent, and closed when the run ends — which is what an ``ssh`` client carries to the
  remote side as the connection closing.
* **A bound.** ``timeout`` is required, and a run's :class:`Deadline` clamps it to
  what the run has left — the way ``fetch`` clamps a socket timeout.
* **Both streams read here**, each up to ``max_bytes`` and the rest read and dropped,
  so a child never blocks on a full pipe and a run never holds more than the caps.
* **The whole group ends** — TERM, a grace, KILL — at the bound, at the instance's
  stop, and at a normal end for whatever the command left behind, so nothing a run
  started outlives it.
* **The answer is a fact**: the status, both streams, how the process ended and
  whether a stream was cut. It raises only where the command could not start, as
  ``fetch`` raises only where no status came back.

POSIX only: a session of its own and a signal to a whole group are what this is.
"""
from __future__ import annotations

import enum
import os
import selectors
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from little_sister.transport import Deadline, DeadlineExceeded

#: Each stream is kept up to this many bytes; the rest is read and dropped.
DEFAULT_MAX_BYTES = 1 << 20

#: Between the TERM to a group and the KILL: long enough for a process to write what
#: it was writing and leave, short enough that a stop is not held by one that will not.
GRACE_SECONDS = 2.0

#: After the command itself has exited, how long what it left behind may still hold
#: a stream open before it is ended as well.
_DRAIN_SECONDS = 0.5

_CHUNK = 65536


class Ended(enum.Enum):
    """How a process ended."""

    #: It exited by itself, and its status is its own.
    EXITED = "exited"
    #: Its bound — the timeout, or what the run's deadline had left — ended it.
    BOUND = "bound"
    #: The instance's stop ended it.
    STOP = "stop"


@dataclass(frozen=True)
class Finished:
    """What one process came to — a fact, whatever the status."""

    #: The exit status, or the negative number of the signal that ended the process.
    status: int
    stdout: bytes
    stderr: bytes
    ended: Ended
    #: Whether a stream was longer than the cap, so that this is only its beginning.
    stdout_cut: bool
    stderr_cut: bool
    #: How long the process ran, on the monotonic clock.
    seconds: float


class NotStarted(Exception):
    """The command could not be started — the one case :func:`run` raises. The
    ``OSError`` that said so is its ``__cause__``; while the instance is stopping there
    is none, and the message says that instead."""


class _Group:
    """One running process group, as the stop sees it."""

    def __init__(self, popen: subprocess.Popen[bytes]) -> None:
        self.popen = popen
        # With a session of its own, the child leads its group.
        self.pgid = popen.pid
        self.stopped = threading.Event()

    def signal(self, number: int) -> None:
        try:
            os.killpg(self.pgid, number)
        except (ProcessLookupError, PermissionError):
            pass

    def alive(self) -> bool:
        try:
            os.killpg(self.pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


_lock = threading.Lock()
_running: set[_Group] = set()
_stopping = threading.Event()


def run(argv: Sequence[str], *, timeout: float, deadline: Deadline | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES, env: Mapping[str, str] | None = None,
        cwd: str | os.PathLike[str] | None = None, send: bytes = b"",
        hang_up: bool = False) -> Finished:
    """Run ``argv`` to its end and answer what it came to.

    ``env``, when given, is the whole environment; ``None`` inherits this process's.
    ``send`` is written to stdin as the command takes it, and stdin is closed after
    it; what the command leaves unread is dropped. ``hang_up`` holds stdin open for
    the rest of the run instead, after whatever was sent. With neither, stdin is
    ``/dev/null``.

    :raises NotStarted: the command could not be started, or the instance is stopping.
    :raises DeadlineExceeded: the run's budget was already spent.
    """
    if isinstance(argv, (str, bytes)) or not argv:
        raise TypeError("run() takes an argument vector, never a command string; a "
                        "shell command is ['/bin/sh', '-c', command]")
    if deadline is not None and deadline.expired():
        raise DeadlineExceeded(
            f"the run's budget of {deadline.seconds:g}s ran out after "
            f"{deadline.elapsed():.1f}s, before {argv[0]} was started")
    budget = deadline.budget(timeout) if deadline is not None else float(timeout)
    started = time.monotonic()
    with _lock:
        if _stopping.is_set():
            raise NotStarted(f"{argv[0]} was not started: the instance is stopping")
        try:
            popen = subprocess.Popen(
                list(argv),
                stdin=subprocess.PIPE if send or hang_up else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True,
                env=dict(env) if env is not None else None, cwd=cwd)
        except OSError as error:
            raise NotStarted(f"{argv[0]} could not be started: {error}") from error
        group = _Group(popen)
        _running.add(group)
    try:
        stdout, stderr, ended = _collect(group, started + budget, max_bytes, send,
                                         hang_up)
    finally:
        with _lock:
            _running.discard(group)
        if popen.stdin is not None:
            popen.stdin.close()
    status = popen.returncode if popen.returncode is not None else popen.wait()
    return Finished(status=status, stdout=bytes(stdout.data), stderr=bytes(stderr.data),
                    ended=ended, stdout_cut=stdout.cut, stderr_cut=stderr.cut,
                    seconds=time.monotonic() - started)


class _Stream:
    """One stream's bytes, up to the cap."""

    def __init__(self, cap: int) -> None:
        self.data = bytearray()
        self.cap = cap
        self.cut = False

    def take(self, chunk: bytes) -> None:
        room = self.cap - len(self.data)
        if len(chunk) > room:
            self.cut = True
            chunk = chunk[:max(room, 0)]
        self.data += chunk


def _collect(group: _Group, end: float, cap: int, send: bytes,
             hang_up: bool) -> tuple[_Stream, _Stream, Ended]:
    """Read both streams until the process and whatever holds them are done, writing
    ``send`` to stdin as it goes, and ending the group at the bound; the stop ends
    it from outside."""
    popen = group.popen
    assert popen.stdout is not None and popen.stderr is not None
    out_fd, err_fd = popen.stdout.fileno(), popen.stderr.fileno()
    streams = {out_fd: _Stream(cap), err_fd: _Stream(cap)}
    selector = selectors.DefaultSelector()
    for fd in streams:
        os.set_blocking(fd, False)
        selector.register(fd, selectors.EVENT_READ)
    unsent = memoryview(send)
    if unsent and popen.stdin is not None:
        os.set_blocking(popen.stdin.fileno(), False)
        selector.register(popen.stdin.fileno(), selectors.EVENT_WRITE)
    ended = Ended.EXITED
    drain_until: float | None = None
    try:
        while any(fd in streams for fd in selector.get_map()):
            now = time.monotonic()
            if group.stopped.is_set():
                break
            if now >= end:
                ended = Ended.BOUND
                break
            if drain_until is None and popen.poll() is not None:
                # The command has exited; what it left behind may still hold a
                # stream open, and gets a moment to finish writing.
                drain_until = now + _DRAIN_SECONDS
            if drain_until is not None and now >= drain_until:
                break
            wait = min(end, drain_until if drain_until is not None else end) - now
            for key, _ in selector.select(timeout=min(max(wait, 0.0), 0.1)):
                if key.fd not in streams:
                    unsent = _write(popen, unsent, selector, hang_up)
                    continue
                try:
                    chunk = os.read(key.fd, _CHUNK)
                except BlockingIOError:
                    continue
                if chunk:
                    streams[key.fd].take(chunk)
                else:
                    selector.unregister(key.fd)
    finally:
        selector.close()
    if group.stopped.is_set():
        # The streams may have closed because the stop's TERM ended the command,
        # which is the stop's end and not the command's own. The stop signals the
        # group; this only waits for the leader, so its status is the signal's.
        _reap(popen, GRACE_SECONDS + 1.0)
        ended = Ended.STOP
    else:
        # At the bound the command is ended; at a normal end, whatever it left
        # behind is. Either way nothing it started outlives the run.
        _end(group)
    popen.stdout.close()
    popen.stderr.close()
    return streams[out_fd], streams[err_fd], ended


def _write(popen: subprocess.Popen[bytes], unsent: memoryview,
           selector: selectors.BaseSelector, hang_up: bool) -> memoryview:
    """As much of ``unsent`` as stdin takes now; answers what is left. Once nothing
    is, stdin is left to the run — closed at once, or held open as the hang-up line.
    A command that went away without taking all of it leaves the rest unsent."""
    assert popen.stdin is not None
    try:
        unsent = unsent[os.write(popen.stdin.fileno(), unsent[:_CHUNK]):]
    except BlockingIOError:
        return unsent
    except OSError:     # the command closed its stdin, or is gone
        unsent = unsent[:0]
    if not unsent:
        selector.unregister(popen.stdin.fileno())
        if not hang_up:
            popen.stdin.close()
    return unsent


def _end(group: _Group, grace: float = GRACE_SECONDS) -> None:
    """TERM to the whole group, the grace, then KILL to whatever is left."""
    group.signal(signal.SIGTERM)
    until = time.monotonic() + grace
    while time.monotonic() < until and group.alive():
        group.popen.poll()
        time.sleep(0.02)
    if group.alive():
        group.signal(signal.SIGKILL)
    _reap(group.popen, grace)


def _reap(popen: subprocess.Popen[bytes], seconds: float) -> None:
    try:
        popen.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        pass


def end_all(grace: float = GRACE_SECONDS) -> int:
    """The instance's stop: nothing starts from here on, and every group that is
    running is ended — TERM, the grace, KILL. Answers how many there were.

    For the engine's stop (ADR-0088 decision 2); not part of the promised surface.
    """
    with _lock:
        _stopping.set()
        groups = list(_running)
    for group in groups:
        group.stopped.set()
        group.signal(signal.SIGTERM)
    until = time.monotonic() + grace
    for group in groups:
        while time.monotonic() < until and group.alive():
            group.popen.poll()
            time.sleep(0.02)
    for group in groups:
        if group.alive():
            group.signal(signal.SIGKILL)
    return len(groups)


def forget_stop() -> None:
    """Undo :func:`end_all` in a process that goes on — a test suite's, never an
    instance's."""
    _stopping.clear()


__all__ = ["Ended", "Finished", "NotStarted", "run"]
