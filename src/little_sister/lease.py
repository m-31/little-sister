"""One state directory, one writer: a lease file with a heartbeat, and a kernel lock for
the machine the kernel sees (ADR-0090).

The lease is a file **beside** the state directory — ``var/state.lease`` — so that no
keeper mirrors it and no restore reads it. It names its holder: the instance mark, and,
as fields of their own because the mark is never parsed, the host, the pid and the
kernel the holder runs under. The holder rewrites it every beat from a thread of its
own, and a lease whose last beat is older than its ``ttl_seconds`` has lapsed.

Two fields say two different things, and they are kept apart on purpose. ``taken`` is
how the holder came by the lease — ``free``, ``released``, ``gone`` or ``lapsed`` — and
``state`` is whether it still holds it: ``held``, or ``released`` once its holder let it
go. Only ``state`` decides anything. A graceful restart takes a released lease, so its
``taken`` says ``released`` while it holds and beats; read as a release, that is a live
lease another kernel would take at once.

Beside it, ``var/state.lock`` is an empty file the holder keeps an exclusive ``flock``
on for its whole life. The kernel lets go of that lock however the process ends, and it
is the kernel's alone — a lock taken on the Mac is not seen from the device VM that
reaches the same checkout through a FUSE mount. So the two decide different things:

* **under the same kernel, the lock decides** — a process that can take it knows no
  process under this kernel holds the lease, and a lease this kernel wrote belongs to a
  holder that is gone, whatever its heartbeat says;
* **under another kernel, the heartbeat decides** — a fresh beat is a live holder, and a
  lapsed one is watched for one more beat before it is taken, so that a holder that has
  just woken keeps it.

A process that cannot take the lease refuses, and :class:`LeaseRefused` says whose it
is. A holder asks :meth:`Lease.still_ours` before every save; once the answer is no, it
is no for the rest of the process, and :attr:`Lease.lost` says who holds the directory
now.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import fcntl
import json
import os
import socket
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from little_sister.logger import logger

#: How often the holder rewrites the lease.
BEAT_SECONDS = 10.0
#: How many beats may be missed before the lease has lapsed.
LAPSE_BEATS = 3
#: How many claims the lease remembers, newest first.
KEPT_CLAIMS = 4

LEASE_SUFFIX = ".lease"
LOCK_SUFFIX = ".lock"

#: The lease's ``state``: its holder holds it, or has let it go.
HELD = "held"
RELEASED = "released"


class LeaseRefused(Exception):
    """The state directory is held by another process; the message names it."""


def kernel_identity() -> str:
    """The kernel this process runs under, as a string two processes can compare:
    Linux's ``boot_id`` — which the containers on one host share — the macOS boot
    session, or the host name where neither answers."""
    try:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        boot = ""
    if boot:
        return f"boot:{boot}"
    if sys.platform == "darwin":
        session = _sysctl_string(b"kern.bootsessionuuid")
        if session:
            return f"boot:{session}"
    return f"host:{socket.gethostname()}"


def _sysctl_string(name: bytes) -> str | None:
    """One string-valued ``sysctl`` on macOS, or ``None``."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        size = ctypes.c_size_t(0)
        if libc.sysctlbyname(name, None, ctypes.byref(size), None, 0) != 0:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if libc.sysctlbyname(name, buffer, ctypes.byref(size), None, 0) != 0:
            return None
        return buffer.value.decode("ascii", "replace").strip() or None
    except (OSError, AttributeError):
        return None


def _now_stamp(wall: float) -> str:
    return datetime.fromtimestamp(wall, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Lease:
    """The lease on one state directory, as one process holds it."""

    def __init__(self, directory: str | os.PathLike[str], *, mark: str,
                 host: str | None = None, pid: int | None = None,
                 kernel: str | None = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep,
                 beat_seconds: float = BEAT_SECONDS,
                 lapse_beats: int = LAPSE_BEATS) -> None:
        directory = Path(directory)
        self._path = directory.with_name(directory.name + LEASE_SUFFIX)
        self._lock_path = directory.with_name(directory.name + LOCK_SUFFIX)
        self.mark = mark
        self.host = host if host is not None else socket.gethostname()
        self.pid = pid if pid is not None else os.getpid()
        self.kernel = kernel if kernel is not None else kernel_identity()
        self._clock = clock
        self._sleep = sleep
        self._beat_seconds = beat_seconds
        self._ttl = beat_seconds * lapse_beats
        self._lock_fd: int | None = None
        self._body: dict[str, Any] | None = None
        self._lost: str | None = None
        self._previous_beat: float | None = None
        self._stop = threading.Event()
        self._beater: threading.Thread | None = None
        self._guard = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def lost(self) -> str | None:
        """Who holds the directory now, once this process has lost the lease."""
        return self._lost

    @property
    def previous_beat(self) -> float | None:
        """When the lease file was last written before this process took it, as the
        wall clock's seconds — ``None`` where there was none. A holder rewrites it
        every beat and once more when it lets go, so this is when the previous
        holder was **last alive**, whether it stopped or crashed: the start of the
        gap the instance's own node records (ADR-0094 decision 4)."""
        return self._previous_beat

    # --- taking ---------------------------------------------------------------------
    def take(self) -> str:
        """Take the lease or raise :class:`LeaseRefused`. Answers how it was come by:
        ``free``, ``released``, ``gone`` (a holder under this kernel that has ended) or
        ``lapsed`` (a holder under another kernel that stopped beating)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            holder = self._read()
            who = (self._describe(holder) if holder
                   else "a process whose lease is unreadable")
            raise LeaseRefused(
                f"the state directory is held under this kernel by {who}") from None
        # Read before anything this process writes: the previous holder's last word.
        self._previous_beat = self._mtime()
        try:
            how = self._decide()
        except BaseException:
            os.close(fd)
            raise
        self._lock_fd = fd
        self._write(how)
        self._beater = threading.Thread(target=self._beat, name="ls-lease", daemon=True)
        self._beater.start()
        return how

    def _decide(self) -> str:
        holder = self._read()
        if holder is None:
            return "free"
        # Only its holder's own release: a lease that says nothing of it is held.
        if holder.get("state") == RELEASED:
            return "released"
        if holder.get("kernel") == self.kernel:
            # This process holds the kernel's lock, so nothing under this kernel does:
            # the holder named here has ended, whatever its heartbeat says.
            logger.info("state: took over the state directory from %s, whose process "
                        "under this kernel is gone", self._describe(holder))
            return "gone"
        before = self._mtime()
        if before is None:
            return "free"
        ttl = float(holder.get("ttl_seconds") or self._ttl)
        age = self._clock() - before
        if age < ttl:
            raise LeaseRefused(
                f"the state directory is held by {self._describe(holder)}")
        # Lapsed — watched for one more beat, so a holder that has just woken keeps it.
        self._sleep(self._beat_seconds)
        after = self._mtime()
        if after is not None and after != before:
            holder = self._read() or holder
            raise LeaseRefused(
                f"the state directory is held by {self._describe(holder)}, which beat "
                f"again while it was watched")
        logger.warning("state: took over the state directory from %s, under another "
                       "kernel, whose lease had lapsed", self._describe(holder))
        return "lapsed"

    # --- holding --------------------------------------------------------------------
    def still_ours(self) -> bool:
        """Whether this process still holds the lease — asked before every save. Once
        the answer is no, it stays no."""
        if self._lost is not None:
            return False
        if self._body is None:
            return False
        holder = self._read()
        if holder is not None and holder.get("mark") == self.mark:
            return True
        now_held = self._describe(holder) if holder else "nobody — its lease is gone"
        with self._guard:
            if self._lost is None:
                self._lost = now_held
                logger.error("state: this instance no longer saves — the state "
                             "directory's lease is held by %s", now_held)
        self._stop.set()
        return False

    def _beat(self) -> None:
        while not self._stop.wait(self._beat_seconds):
            if not self.still_ours():
                return
            self._rewrite()

    def release(self) -> None:
        """Give the lease up — after the final save. A release is a write: the lease's
        ``state`` says it was released — how it was taken stays what it was — and the
        kernel lock is let go."""
        self._stop.set()
        beater, self._beater = self._beater, None
        if beater is not None and beater is not threading.current_thread():
            beater.join(timeout=self._beat_seconds + 1.0)
        if self._body is not None and self._lost is None:
            holder = self._read()
            if holder is not None and holder.get("mark") == self.mark:
                self._body["state"] = RELEASED
                self._rewrite()
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    # --- the file ---------------------------------------------------------------------
    def _write(self, taken: str) -> None:
        previous = self._read() or {}
        wall = self._clock()
        claims = [{"mark": self.mark, "taken": taken, "at": _now_stamp(wall)}]
        for claim in previous.get("claims") or []:
            if isinstance(claim, dict) and len(claims) < KEPT_CLAIMS:
                claims.append(claim)
        self._body = {"mark": self.mark, "host": self.host, "pid": self.pid,
                      "kernel": self.kernel, "ttl_seconds": self._ttl,
                      "beat_seconds": self._beat_seconds, "taken": taken,
                      "state": HELD, "since": _now_stamp(wall), "claims": claims}
        self._rewrite()

    def _rewrite(self) -> None:
        assert self._body is not None
        temporary = self._path.with_name(f"{self._path.name}.{self.pid}.tmp")
        temporary.write_text(json.dumps(self._body, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)

    def _read(self) -> dict[str, Any] | None:
        try:
            body = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return body if isinstance(body, dict) else None

    def _mtime(self) -> float | None:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None

    def _describe(self, holder: dict[str, Any]) -> str:
        mtime = self._mtime()
        beat = (f", last beat {max(0, round(self._clock() - mtime))} s ago"
                if mtime is not None else "")
        return (f"{holder.get('mark', '?')} on {holder.get('host', '?')}, "
                f"pid {holder.get('pid', '?')}{beat}")


__all__ = ["BEAT_SECONDS", "LAPSE_BEATS", "Lease", "LeaseRefused", "kernel_identity"]
