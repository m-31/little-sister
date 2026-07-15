"""The monitoring engine: schedule checks and write their results to the tree.

One process runs one engine (ADR-0001). A scheduler thread submits *due* checks
to a bounded thread pool; each run produces a result that is upserted into the
shared status tree. A check that raises or times out becomes ``ERROR``
(ADR-0004). Threads are daemons; ``start``/``stop`` are idempotent.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from little_sister.checks import Check, CheckResult, load_checks
from little_sister.logger import logger
from little_sister.status import StatusCode, join_path
from little_sister.tree import StatusTree, status_tree

DEFAULT_MAX_WORKERS = 8
DEFAULT_POLL_INTERVAL = 1.0

# The engine's self-monitoring tile: it heartbeats this node every scheduler tick,
# so a dead scheduler shows up as a stale (red) tile (ADR-0005).
HEARTBEAT_PATH = "/little-sister"
HEARTBEAT_DESCRIPTION = "little-sister monitoring engine — beats every scheduler tick"


@dataclass
class _Scheduled:
    check: Check
    next_due: float
    running: bool = False


@dataclass(frozen=True)
class CheckInfo:
    """A check's scheduling state, for the system page."""
    path: str
    frequency_seconds: int
    running: bool
    next_in_seconds: float


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
        self._clock = clock
        self._poll_interval = poll_interval
        self._max_workers = max(1, min(max_workers, max(1, len(checks))))
        now = clock()
        # Every check is due immediately, so the first sweep populates the tree.
        self._scheduled = [_Scheduled(check, now) for check in checks]
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
        with self._lock:
            checks = tuple(
                CheckInfo(path=item.check.path,
                          frequency_seconds=item.check.frequency_seconds,
                          running=item.running,
                          next_in_seconds=max(0.0, item.next_due - now))
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
                item.next_due = now + item.check.frequency_seconds
                executor.submit(self._execute, item)
        # The engine reports its own liveness as a tile; if the scheduler stalls
        # this node goes stale and turns red (ADR-0005).
        self._tree.upsert(HEARTBEAT_PATH, StatusCode.OK,
                          description=HEARTBEAT_DESCRIPTION,
                          frequency_seconds=max(1, round(self._poll_interval)))
        # Expire maintenance pins past their window (ADR-0014); a real transition,
        # so the next check refills the node.
        self._tree.sweep_expired()

    def _execute(self, item: _Scheduled) -> None:
        check = item.check
        started = time.monotonic()
        try:
            result = check.run()
            if not isinstance(result, CheckResult):
                result = CheckResult(
                    StatusCode.ERROR, ["check returned no result"])
        except Exception as error:  # any failure becomes an ERROR (ADR-0004)
            logger.exception("engine: check %s raised", check.path)
            result = CheckResult(StatusCode.ERROR, [f"check error: {error}"])
        finally:
            with self._lock:
                item.running = False
        elapsed_ms = (time.monotonic() - started) * 1000
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
