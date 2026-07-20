"""The monitoring engine: schedule checks and write their results to the tree.

One process runs one engine (ADR-0001). A scheduler thread submits *due* checks
to a bounded thread pool; each run produces a result that is upserted into the
shared status tree. A check that raises or times out becomes ``ERROR``
(ADR-0004); one whose secret references failed to resolve at construction is
**pinned** to ERROR without running (ADR-0023). Threads are daemons;
``start``/``stop`` are idempotent.
"""
from __future__ import annotations

import threading
import time
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

from little_sister.checks import Check, CheckResult, load_checks, plain
from little_sister.logger import logger
from little_sister.status import HEARTBEAT_PATH, StatusCode, join_path
from little_sister.tree import StatusTree, status_tree

DEFAULT_MAX_WORKERS = 8
DEFAULT_POLL_INTERVAL = 1.0
# The spread window for check start times: every check still runs in the first
# sweep, but its schedule is phase-shifted once, at the first re-arm, by a
# stable per-check offset within min(frequency, this) — so equal-frequency
# checks don't fire in one tick forever (all SSH sessions at once, every LCM
# beat), and a fast check never waits longer than its own period.
STAGGER_WINDOW_SECONDS = 60.0

# The engine's self-monitoring node: it heartbeats HEARTBEAT_PATH (reserved —
# see status.py; the dashboard renders it as the status strip, #24) every
# scheduler tick, so a dead scheduler shows up stale and degraded (ADR-0005).
HEARTBEAT_DESCRIPTION = "little-sister monitoring engine — beats every scheduler tick"
# Default `about` for the heartbeat, so the dashboard strip explains itself in
# the hover card (ADR-0019) out of the box. Seeded at engine construction —
# before the startup nodes.yaml pass, whose declaration simply overwrites it
# (ADR-0012 precedence).
HEARTBEAT_ABOUT = (
    "The engine's own heartbeat — re-asserted every scheduler tick. "
    "**Stale** here means the scheduler itself has stalled (ADR-0005)."
)


def _stagger(check: Check) -> float:
    """The check's personal schedule phase within
    ``min(frequency, STAGGER_WINDOW_SECONDS)``, applied once at the first
    re-arm. Derived from a digest of path *and* type — two checks may share a
    root node (e.g. host-metrics + macos-memory on one host) and those want
    separating most — and deterministic across restarts (crc32, not the
    per-process-salted ``hash``), so the relative spread is reproducible."""
    window = min(float(check.frequency_seconds), STAGGER_WINDOW_SECONDS)
    digest = zlib.crc32(f"{check.path}\0{check.type_name}".encode())
    return (digest % 1000) / 1000.0 * window


@dataclass
class _Scheduled:
    check: Check
    next_due: float
    running: bool = False
    # One-time schedule offset (see _stagger), spent at the first re-arm.
    stagger: float = 0.0
    # The in-flight run: its wall-clock start and the monotonic mate, set when
    # execution begins (queue wait excluded), cleared when it finishes.
    run_started_at: str | None = None
    run_started_mono: float | None = None
    # The last completed run() attempt: when it started and how long it took —
    # a raising (or timed-out) run records its full wait; a secret-pinned check
    # never runs, so both stay None. Read under the engine lock.
    last_run_at: str | None = None
    elapsed_seconds: float | None = None


@dataclass(frozen=True)
class CheckInfo:
    """A check's scheduling state, for the system page.

    ``running_since`` / ``running_seconds`` describe the in-flight run (``None``
    while idle, and while a submitted run still waits for a pool worker);
    ``next_run_at`` / ``next_in_seconds`` the armed next slot (a running check's
    next slot is already scheduled); ``last_run_at`` / ``elapsed_seconds`` the
    last completed run — ``None`` until one finishes, and always for a
    secret-pinned check (it never runs).
    """
    path: str
    type_name: str
    frequency_seconds: int
    running: bool
    running_since: str | None
    running_seconds: float | None
    next_run_at: str
    next_in_seconds: float
    last_run_at: str | None
    elapsed_seconds: float | None


@dataclass(frozen=True)
class EngineInfo:
    """A snapshot of the engine's runtime state."""
    started_at: str | None
    uptime_seconds: float
    max_workers: int
    check_count: int
    running: int
    checks: tuple[CheckInfo, ...]


class Engine:
    """Runs a set of checks on their own schedules against a status tree."""

    def __init__(self, checks: list[Check], tree: StatusTree, *,
                 max_workers: int = DEFAULT_MAX_WORKERS,
                 poll_interval: float = DEFAULT_POLL_INTERVAL,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._tree = tree
        # Make the self-monitor legible before it ever beats: the strip's
        # hover card can always say what /little-sister is (the nodes.yaml
        # pass runs later at startup and overrides this default).
        tree.set_about(HEARTBEAT_PATH, HEARTBEAT_ABOUT)
        self._clock = clock
        self._poll_interval = poll_interval
        self._max_workers = max(1, min(max_workers, max(1, len(checks))))
        now = clock()
        # Every check is due immediately, so the first sweep populates the
        # tree; the stagger then phase-shifts each schedule once so the
        # lockstep doesn't outlive the start.
        self._scheduled = [_Scheduled(check, now, stagger=_stagger(check))
                           for check in checks]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._scheduler: threading.Thread | None = None
        self._started_at: str | None = None
        self._started_monotonic: float | None = None

    @property
    def check_count(self) -> int:
        return len(self._scheduled)

    def check_roots(self) -> list[str]:
        """Each configured check's node path — the static roots the maintenance
        reaper reconciles against at startup (ADR-0014/0015)."""
        return [item.check.path for item in self._scheduled]

    @property
    def checks(self) -> list[Check]:
        """The configured checks (for startup node-metadata seeding, ADR-0012)."""
        return [item.check for item in self._scheduled]

    def info(self) -> EngineInfo:
        """A snapshot of the engine's runtime state (for the system page)."""
        now = self._clock()
        # The schedule runs on the monotonic clock; project each next-due onto
        # the wall clock once, here, so the system page can show a time of day.
        wall = datetime.now()
        with self._lock:
            checks = tuple(
                CheckInfo(path=item.check.path,
                          type_name=item.check.type_name,
                          frequency_seconds=item.check.frequency_seconds,
                          running=item.running,
                          running_since=item.run_started_at,
                          running_seconds=(now - item.run_started_mono
                                           if item.run_started_mono is not None
                                           else None),
                          next_run_at=(wall + timedelta(
                              seconds=max(0.0, item.next_due - now))
                          ).isoformat(),
                          next_in_seconds=max(0.0, item.next_due - now),
                          last_run_at=item.last_run_at,
                          elapsed_seconds=item.elapsed_seconds)
                for item in self._scheduled)
            running = sum(1 for item in self._scheduled if item.running)
        uptime = (now - self._started_monotonic
                  if self._started_monotonic is not None else 0.0)
        return EngineInfo(
            started_at=self._started_at, uptime_seconds=uptime,
            max_workers=self._max_workers, check_count=len(self._scheduled),
            running=running, checks=checks)

    def start(self) -> None:
        """Start the scheduler and worker pool (idempotent)."""
        if self._scheduler is not None:
            return
        if not self._scheduled:
            logger.info("engine: no checks configured; nothing to run")
            return
        self._started_at = datetime.now().isoformat()
        self._started_monotonic = self._clock()
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers, thread_name_prefix="ls-check")
        self._scheduler = threading.Thread(
            target=self._loop, name="ls-scheduler", daemon=True)
        self._scheduler.start()
        logger.info("engine: started %d check(s) on %d worker(s)",
                    len(self._scheduled), self._max_workers)

    def stop(self, timeout: float | None = 5.0) -> None:
        """Signal the scheduler to stop and shut down the pool (idempotent)."""
        self._stop.set()
        scheduler, self._scheduler = self._scheduler, None
        if scheduler is not None:
            scheduler.join(timeout=timeout)
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def run_once(self) -> None:
        """Run every check once, synchronously, and upsert results.

        Used for tests and a potential one-shot refresh; the background loop does
        not call this.
        """
        for item in self._scheduled:
            self._execute(item)

    def _loop(self) -> None:
        while not self._stop.is_set():
            # Harden the loop: a transient fault in one tick must not kill the
            # scheduler thread and stop all monitoring.
            try:
                self._tick()
            except Exception:
                logger.exception("engine: scheduler tick failed")
            self._stop.wait(timeout=self._poll_interval)

    def _tick(self) -> None:
        executor = self._executor
        assert executor is not None
        now = self._clock()
        with self._lock:
            for item in self._scheduled:
                if item.running or item.next_due > now:
                    continue
                item.running = True
                item.next_due = (now + item.check.frequency_seconds
                                 + item.stagger)
                item.stagger = 0.0
                executor.submit(self._execute, item)
        # The engine reports its own liveness as the heartbeat node (the
        # dashboard's status strip); if the scheduler stalls it goes stale and
        # degrades to at least WARN (ADR-0005).
        self._tree.upsert(HEARTBEAT_PATH, StatusCode.OK,
                          description=HEARTBEAT_DESCRIPTION,
                          frequency_seconds=max(1, round(self._poll_interval)))
        # Expire maintenance pins past their window (ADR-0014); a real transition,
        # so the next check refills the node.
        self._tree.sweep_expired()

    def _execute(self, item: _Scheduled) -> None:
        check = item.check
        ran = not check.secret_errors
        started = time.monotonic()
        with self._lock:
            item.run_started_at = datetime.now().isoformat()
            item.run_started_mono = started
        try:
            if not ran:
                # Pinned (ADR-0023): a secret reference failed to resolve at
                # construction — report it, never call run(), never retry.
                result = CheckResult(StatusCode.ERROR, [
                    plain(f"secret unresolvable: {error}")
                    for error in check.secret_errors])
            else:
                result = check.run()
                if not isinstance(result, CheckResult):
                    result = CheckResult(
                        StatusCode.ERROR, ["check returned no result"])
        except Exception as error:  # any failure becomes an ERROR (ADR-0004)
            logger.exception("engine: check %s raised", check.path)
            result = CheckResult(StatusCode.ERROR, [f"check error: {error}"])
        finally:
            elapsed = time.monotonic() - started
            with self._lock:
                item.running = False
                if ran:
                    # Keep the runtime even when run() raised — a hanging check
                    # that hit its timeout should show the full wait.
                    item.last_run_at = item.run_started_at
                    item.elapsed_seconds = elapsed
                item.run_started_at = None
                item.run_started_mono = None
        elapsed_ms = elapsed * 1000
        detail = ""
        if result.reason:
            detail = " — " + result.reason[0].replace("\n", " ")[:120]
        logger.info("check %s: %s (%.0f ms)%s", check.path,
                    result.code.name, elapsed_ms, detail)
        try:
            self._store(check.path, result, check, is_root=True)
        except Exception:
            logger.exception("engine: failed to upsert %s", check.path)

    def _store(self, path: str, result: CheckResult, check: Check,
               *, is_root: bool = False) -> None:
        """Upsert a result and its subtree into the status tree.

        The root node inherits the check's ``description``; child nodes carry
        their own. A root with no description leaves the node's description
        untouched (``None``) so a second check contributing to the same host node
        doesn't clobber it. ``config`` rides the same way (ADR-0013): the root takes
        the check's ``config_summary`` (empty for a branch check, so the shared
        container stays bare); each child carries its own slice. Every node inherits
        the check's ``frequency`` so freshness (ADR-0005) applies uniformly.
        Identity, observation time, maintenance and event-on-change stay the tree's
        concern (ADR-0007).
        """
        description = (check.description or None) if is_root else result.description
        config = (check.config_summary() or None) if is_root else result.config
        self._tree.upsert(path, result.code, result.reason,
                          description=description,
                          frequency_seconds=check.frequency_seconds,
                          config=config)
        for child in result.children:
            self._store(join_path(path, child.name), child, check)


def create_engine(checks_dir: str | None = None, *,
                  tree: StatusTree = status_tree,
                  max_workers: int = DEFAULT_MAX_WORKERS) -> Engine:
    """Load checks from ``checks_dir`` (default ``checks/``) into a new engine
    bound to ``tree`` (the shared :data:`status_tree` by default)."""
    checks = load_checks(checks_dir)
    return Engine(checks, tree, max_workers=max_workers)
