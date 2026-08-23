"""The monitoring engine: schedule checks and write their results to the tree.

One process runs one engine (ADR-0001). A scheduler thread submits *due* checks
to a bounded thread pool; each run produces a result that is upserted into the
shared status tree. A check that raises or times out becomes ``ERROR``
(ADR-0040); one whose secret references failed to resolve at construction is
**pinned** to ERROR without running (ADR-0023). Threads are daemons;
``start``/``stop`` are idempotent.
"""
from __future__ import annotations

import threading
import time
import traceback
import zlib
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta

from little_sister.checks import (
    Check,
    CheckError,
    CheckResult,
    checks_dirs,
    code,
    load_checks,
    parse_duration,
    plain,
)
from little_sister.config import config
from little_sister.logger import logger
from little_sister.status import HEARTBEAT_PATH, StatusCode, join_path, leaf_name
from little_sister.tree import StatusTree, status_tree

# Innermost frames kept when a failing check's trace goes onto its node
# (`stacktrace` in config/settings.yaml). The cause is almost always in the last
# few, and a node reason is not a log file — the whole trace stays in the log.
TRACEBACK_FRAMES = 5

#: How much of a run's reasons the per-run log line carries.
#:
#: It used to be the **first reason, cut at 120 characters**, and both halves of
#: that were wrong at the one moment the line is read. A check that could not
#: measure at all words its refusal in two reasons on purpose — what went wrong,
#: then what to do about it — because the second half is the actionable one and a
#: cloud provider's error is long enough to push it off the edge of a card. The
#: log kept the first and dropped the second, then cut the first mid-sentence: a
#: real `AssumeRole` refusal ended at "…when calling the AssumeRole operation:",
#: exactly before the part naming who was refused and for what.
#:
#: So: every reason, and a cap generous enough that a provider's message arrives
#: whole. It is still a cap — a check with a hundred coded lines must not put all
#: of them on one line — and what it truncates now is a *roster*, where the first
#: entries are representative, rather than a single sentence's tail.
DETAIL_LIMIT = 1200

#: What joins the reasons of one run into that line. Not a newline: one run is
#: one record, and a log a reader greps by check path must not have its answer
#: split across lines that no longer carry it.
DETAIL_SEPARATOR = " | "

DEFAULT_MAX_WORKERS = 8
DEFAULT_POLL_INTERVAL = 1.0
# The spread window for check start times: every check still runs in the first
# sweep, but its schedule is phase-shifted once, at the first re-arm, by a
# stable per-check offset within min(frequency, this) — so equal-frequency
# checks don't fire in one tick forever (all SSH sessions at once, every LCM
# beat), and a fast check never waits longer than its own period.
STAGGER_WINDOW_SECONDS = 60.0

# The engine's self-monitoring node: it heartbeats HEARTBEAT_PATH (reserved —
# see status.py; the dashboard renders it as the status strip, ADR-0024) every
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


def _retry_settings(check: Check) -> tuple[int, int]:
    """The effective failure-retry settings for ``check`` (ADR-0033): the
    per-check fields when set, else the ``settings.yaml`` defaults. The
    settings-level interval is a duration string parsed here, where a bad value
    can fall back with a warning instead of failing engine construction —
    ``config.py`` stays free of the duration parser on purpose."""
    interval = check.retry_interval_seconds
    if interval is None:
        try:
            interval = parse_duration(config.retry_interval or None, 0)
        except CheckError:
            logger.warning(
                "config: invalid retry_interval %r; the failure retry stays "
                "off", config.retry_interval)
            interval = 0
    attempts = (check.retry_attempts if check.retry_attempts is not None
                else config.retry_attempts)
    return max(0, interval), max(0, attempts)


def _detail(result: CheckResult) -> str:
    """What one run's log line says after the code and the elapsed time.

    Every reason, joined, bounded by :data:`DETAIL_LIMIT` — see that constant for
    why it is no longer the first reason cut at 120. Newlines are flattened
    because this is one log record, and truncation says so with an ellipsis
    rather than stopping silently: a line that ends mid-word looks exactly like a
    message that ended there, which is how a refusal was read as truncated by AWS
    rather than by us.
    """
    texts = [text.replace("\n", " ") for text in result.reason_texts if text]
    if not texts:
        return ""
    joined = DETAIL_SEPARATOR.join(texts)
    if len(joined) > DETAIL_LIMIT:
        joined = joined[:DETAIL_LIMIT] + " …"
    return " — " + joined


@dataclass
class _Scheduled:
    check: Check
    next_due: float
    running: bool = False
    # One-time schedule offset (see _stagger), spent at the first re-arm.
    stagger: float = 0.0
    # The budgeted failure retry (ADR-0033, amended by ADR-0060), resolved per
    # check at engine construction: the fast interval (0 = off) and the
    # per-episode budget. `retry_used` counts the fast attempts of the current
    # episode and `last_code` is what ends one — **any** change of the stored
    # code, not only an OK, because a check whose ordinary state is non-OK would
    # otherwise spend its budget once and never get it back. It starts at
    # `UNDEFINED` because that is the code a node carries before its first run —
    # nothing observable turns on the choice, since a first reading either matches
    # it or is news, but any other value would be a lie to whoever reads it in a
    # debugger. `retrying` marks that the currently armed
    # slot is a retry slot, for the system page. In-memory only — a restart
    # forgets an episode, like the rest of the schedule.
    retry_interval_seconds: int = 0
    retry_attempts: int = 0
    retry_used: int = 0
    last_code: StatusCode = StatusCode.UNDEFINED
    retrying: bool = False
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
    secret-pinned check (it never runs). ``retrying`` marks a check whose armed
    slot is a failure-retry slot (ADR-0033) — fast attempt ``retry_attempt`` of
    ``retry_attempts`` — so the system page can explain a next run that
    contradicts the frequency column.
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
    retrying: bool = False
    retry_attempt: int = 0
    retry_attempts: int = 0


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
                 clock: Callable[[], float] = time.monotonic,
                 heartbeat_warning: list[str] | None = None) -> None:
        self._tree = tree
        # A configured-but-empty deployment: the engine runs, and every beat
        # carries these reasons at WARN instead of OK (see _tick / ADR-0031 §7).
        self._heartbeat_warning = heartbeat_warning
        # Make the self-monitor legible before it ever beats: the strip's
        # hover card can always say what /little-sister is (the nodes.yaml
        # pass runs later at startup and overrides this default).
        tree.set_about(HEARTBEAT_PATH, HEARTBEAT_ABOUT)
        # Tell the tree where each check writes its result root, so a container above
        # exactly one of them can publish that check's run time as its own observation
        # (ADR-0027). Registration only — a node still appears when its result does.
        # The heartbeat above is deliberately *not* a mount: it is the engine's own
        # liveness rather than a check, so it neither blocks nor feeds that roll-up
        # (and the dashboard lifts it out of the grid anyway, ADR-0024).
        for check in checks:
            tree.set_check_mount(check.path)
        self._clock = clock
        self._poll_interval = poll_interval
        self._max_workers = max(1, min(max_workers, max(1, len(checks))))
        now = clock()
        # Every check is due immediately, so the first sweep populates the
        # tree; the stagger then phase-shifts each schedule once so the
        # lockstep doesn't outlive the start. The failure-retry settings
        # (ADR-0033) resolve per check here — the per-check fields first, then
        # the settings defaults — so _execute reads two ints, never the config.
        self._scheduled: list[_Scheduled] = []
        for check in checks:
            retry_interval, retry_attempts = _retry_settings(check)
            self._scheduled.append(_Scheduled(
                check, now, stagger=_stagger(check),
                retry_interval_seconds=retry_interval,
                retry_attempts=retry_attempts))
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
                          elapsed_seconds=item.elapsed_seconds,
                          retrying=item.retrying,
                          retry_attempt=item.retry_used,
                          retry_attempts=item.retry_attempts)
                for item in self._scheduled)
            running = sum(1 for item in self._scheduled if item.running)
        uptime = (now - self._started_monotonic
                  if self._started_monotonic is not None else 0.0)
        return EngineInfo(
            started_at=self._started_at, uptime_seconds=uptime,
            max_workers=self._max_workers, check_count=len(self._scheduled),
            running=running, checks=checks)

    def start(self) -> None:
        """Start the scheduler and worker pool (idempotent).

        Started even with **no checks scheduled**: the scheduler still has its own
        heartbeat to publish, and that beat is the whole point of the empty case —
        a deployment configured to watch nothing yet must say so on the dashboard,
        not only in the log (ADR-0005 / ADR-0031 §7). A loop with nothing due does
        exactly one thing per tick, which is what it is there for.
        """
        if self._scheduler is not None:
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
        not call this. A one-shot run has no live schedule, so the run facts it
        writes carry no next slot (ADR-0044).
        """
        for item in self._scheduled:
            self._execute(item, once=True)

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
                # the armed slot is the nominal one again; a non-OK completion
                # may pull it earlier (ADR-0033)
                item.retrying = False
                executor.submit(self._execute, item)
        # The engine reports its own liveness as the heartbeat node (the
        # dashboard's status strip); if the scheduler stalls it goes stale and
        # degrades to at least WARN (ADR-0005). With nothing configured to watch,
        # the beat itself carries the WARN: the tree is *only* the heartbeat then,
        # so an OK here would roll up to an all-green root while nothing at all is
        # being monitored — the exact lie ADR-0005 exists to prevent.
        self._tree.upsert(
            HEARTBEAT_PATH,
            StatusCode.OK if self._heartbeat_warning is None else StatusCode.WARN,
            self._heartbeat_warning,
            description=HEARTBEAT_DESCRIPTION,
            frequency_seconds=max(1, round(self._poll_interval)))
        # Expire maintenance pins past their window (ADR-0014); a real transition,
        # so the next check refills the node.
        self._tree.sweep_expired()

    def _execute(self, item: _Scheduled, once: bool = False) -> None:
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
        except Exception as error:  # any failure becomes an ERROR (ADR-0040)
            logger.exception("engine: check %s raised", check.path)
            # The message is untrusted — it routinely carries a captured line, a
            # path or an API error body — so it is escaped like any other folded-in
            # text (ADR-0018). The trace is a code block: verbatim and inert.
            reason = [plain(f"check error: {error}")]
            if config.stacktrace:
                reason.append(code("".join(traceback.format_exception(
                    error, limit=-TRACEBACK_FRAMES)).rstrip()))
            result = CheckResult(StatusCode.ERROR, reason)
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
        logger.info("check %s: %s (%.0f ms)%s", check.path,
                    result.stored_code.name, elapsed_ms, _detail(result))
        # A faster second look on failure (ADR-0033): a non-OK completion pulls
        # the armed slot earlier — never later — to the retry interval, at most
        # `retry_attempts` times per episode. A secret-pinned check (`ran` False)
        # is excluded: it is pinned until restart (ADR-0023), so a fast retry
        # would burn the pool confirming a result that cannot change.
        #
        # **An episode ends on any change of the reading** (ADR-0060 decision 4),
        # not only on an OK as ADR-0033 first had it. That record assumed a non-OK
        # check was a failing one; ADR-0042 then made a node's code derive from its
        # lines, so a check can sit at WARN for weeks as its ordinary state — and
        # under the old rule it spent its retries in the first few cycles and had
        # none left on the day its reading actually changed. Confirmation is worth
        # paying for when there is news, which is what a change is.
        #
        # **A completed UNDEFINED arms nothing.** A line that makes no claim is not
        # a failure to confirm, and the case that reaches here is structural — a
        # resource the provider gives no budget for — where asking again in ten
        # seconds cannot change the answer.
        if ran and item.retry_interval_seconds > 0 and item.retry_attempts > 0:
            with self._lock:
                # not `code`: that name is the Markdown fence helper in this
                # module, and shadowing it here breaks the traceback branch above.
                stored = result.stored_code
                if stored is not item.last_code:
                    item.retry_used = 0
                    item.last_code = stored
                if stored is StatusCode.OK or stored is StatusCode.UNDEFINED:
                    pass
                elif item.retry_used < item.retry_attempts:
                    pulled = self._clock() + item.retry_interval_seconds
                    if pulled < item.next_due:
                        item.retry_used += 1
                        item.retrying = True
                        item.next_due = pulled
        # The run's facts ride beside the result (ADR-0044): the wall time this
        # run took, and the armed slot projected onto the wall clock **once,
        # here** — the same projection info() makes, frozen at write time so a
        # failed poll later shows an honest absolute receding into the past.
        # After the retry block above, `next_due` is final for this run —
        # nominal re-arm or pulled-in slot, whichever won (ADR-0033) — never
        # `timestamp + frequency`. A one-shot run has no live schedule and
        # writes no next; a secret-pinned check never ran and writes no wall.
        if once:
            next_run_at = None
        else:
            with self._lock:
                next_due = item.next_due
            next_run_at = (datetime.now() + timedelta(
                seconds=max(0.0, next_due - self._clock()))).isoformat()
        self._tree.set_run_facts(check.path,
                                 wall_seconds=elapsed if ran else None,
                                 next_run_at=next_run_at)
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
        the check's ``config_summary`` (empty where the container is shared, so it
        stays bare); each child carries its own slice. ``report`` — what the run
        *found*, beside config's what it ran *with* (ADR-0044) — rides the result
        on the root as on **every** child, because only the run can produce it,
        and writes through including the empty string: a roster the current run no
        longer finds must not outlive it. Every node inherits
        the check's ``frequency`` so freshness (ADR-0005) applies uniformly.
        Identity, observation time, maintenance and event-on-change stay the tree's
        concern (ADR-0007).

        A branch check's ``about`` / ``title`` for its subnodes ride the same way,
        but only on **children** (ADR-0025): the root's labels keep their startup
        sources (``nodes.yaml`` / the inline check), so its result labels are
        ignored like its ``name``; each child's fill an empty node field only, so a
        ``nodes.yaml`` override still wins. Their **first** source is not the
        result at all but ``check.subnode_labels`` — the deployment's ``subnodes:``
        block resolved over what the type declared, keyed by subnode *name* at any
        depth, exactly like the flag below (ADR-0025's 2026-08-19 update). Per
        field: a resolved ``title`` and a stamped ``about`` coexist on one node,
        because that is how every other precedence in this pair works. The result's
        label is read where that map is silent for the name — the dynamically named
        child, which no declaration could have anticipated.

        ``order`` (ADR-0055) fills an unset field the same way but is read on the
        **root too**, deliberately unlike the labels: a rank is not identity, and
        the reason the labels are root-ignored — the root has its own inline source
        in the check's YAML — does not hold for a rank, which has none. Zero is
        passed as ``None`` because ``0`` *is* what a check declaring nothing means,
        so it must not count as a declaration and shut out ``nodes.yaml``.

        ``show_when_quiet`` (ADR-0063) rides with the **labels**, not with the
        rank: it is root-ignored, because unlike ``order`` it *does* have an
        inline source of its own in the check's YAML — the root's declaration is
        that key, and a result overruling it would put a check's code ahead of the
        file the deployment edits. On a child, **two sources meet here**, and the
        same rule decides: the deployment's ``subnodes:`` declaration
        (``check.subnode_show_when_quiet``, parsed by the library so no type has
        to relay it, keyed by subnode *name* at any depth) beats the value the
        child result carries — the type's shipped default — because the
        deployment's file beats the check's code. What survives fills an unset
        field only, so a ``nodes.yaml`` entry, seeded before the first tick,
        still beats both. Nothing is coerced on the way: a stated ``False``
        travels as ``False``, because here it is a statement and not the "said
        nothing" that ``order``'s zero is.
        """
        description = (check.description or None) if is_root else result.description
        config = (check.config_summary() or None) if is_root else result.config
        # One guard per field, below: this lookup is harmless on a root (whose
        # name is a node path's last segment like any other) and the root's
        # exemption is stated where it is applied, once per label.
        labels: Mapping[str, str] = check.subnode_labels.get(leaf_name(path), {})
        about = None if is_root else (labels.get("about") or result.about or None)
        title = None if is_root else (labels.get("title") or result.title or None)
        order = result.order or None
        declared = None if is_root else check.subnode_show_when_quiet.get(
            leaf_name(path))
        show_when_quiet = None if is_root else (
            declared if declared is not None else result.show_when_quiet)
        # The pre-normalized entries travel, not the raw input: the check has
        # already been through the one normalization (ADR-0036), and re-deriving
        # slugs here would be the same work done twice. `stored_code` is the
        # declared code, or the one derived from coded entries (ADR-0042).
        self._tree.upsert(path, result.stored_code, result.reason_entries,
                          members=result.members,
                          description=description,
                          frequency_seconds=check.frequency_seconds,
                          config=config, report=result.report,
                          about=about, title=title, order=order,
                          show_when_quiet=show_when_quiet)
        for child in result.children:
            self._store(join_path(path, child.name), child, check)


def create_engine(config_dir: str | None = None, *,
                  tree: StatusTree = status_tree,
                  max_workers: int = DEFAULT_MAX_WORKERS) -> Engine:
    """Load checks from the ``checks`` aspect of ``config_dir`` (default
    ``config``, ADR-0031) into a new engine bound to ``tree`` (the shared
    :data:`status_tree` by default).

    A configuration tree with **no checks in it yet** is a real and temporary
    state — a fresh install, a deployment mid-bring-up — so the engine starts, a
    warning names the directories it searched, and that same sentence rides the
    heartbeat at WARN so the dashboard says it too, not just the log. (Having
    nowhere to *look* is a different thing entirely and already refused, in
    :func:`~little_sister.checks.loader.checks_dirs`.)
    """
    checks = load_checks(config_dir)
    warning: list[str] | None = None
    if not checks:
        searched = [str(directory.resolve())
                    for directory in checks_dirs(config_dir)]
        logger.warning("engine: no checks configured — nothing is being watched. "
                       "Searched: %s", ", ".join(searched))
        # A reason is Markdown (ADR-0018): a path is external text and must not be
        # read as emphasis — `/srv/ls_prod/config_dir/checks` would italicize
        # between its underscores. Same shape the check-error path two functions
        # up uses: the sentence through `plain`, the captured text through `code`.
        warning = [plain("no checks configured — nothing is being watched. "
                         "Searched:"),
                   code("\n".join(searched))]
    return Engine(checks, tree, max_workers=max_workers,
                  heartbeat_warning=warning)
