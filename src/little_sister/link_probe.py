"""Reachability probing for the links page — is what this file names still there?

A curated link list rots quietly: the tool moves, the wiki page is renamed, the
dashboard is retired, and nothing says so until somebody clicks it mid-incident.
ADR-0030 §9–10 answers that **here**, beside the entry, and never on the status
tree: a moved Confluence page is a fact about this deployment's `links.yaml`, not
about a monitored subject, and it must not turn the dashboard amber for everyone.

Three rules shape this module:

* **A pass is started by somebody opening the page**, and only when the newest
  answer is older than the configured ``interval:`` (ADR-0030).
  The engine's tick looked like the obvious home and is deliberately not used: it is
  a scheduler built for checks, skipped wherever ``LITTLE_SISTER_ENGINE=0`` — which
  is exactly where this page still works — and in most deployments it would wake to
  probe an **empty set**, since every icon that is not remote is already settled at
  load.
* **The open never blocks.** :func:`refresh_if_due` starts a daemon thread and
  returns; the page renders from what is already in memory, each verdict carrying
  its own age, and the answers one open triggers land on the next.
* **One pass at a time, and no pass runs forever.** Ten readers arriving together
  cost one sweep, not ten: :func:`start_pass` hands every caller the same event.
  Nothing here queues a second pass behind the running one — a page this cheap to
  open must never become a way to spend the instance's outbound bandwidth. But a
  pass also carries a **deadline**, because :data:`REQUEST_TIMEOUT` bounds one
  socket operation and not one request: a server that dribbles a byte every four
  seconds never times out, and under the old shape that single host held the
  *only* pass slot for as long as it cared to, so reachability froze until restart.
  At the deadline the pass **abandons** what has not answered rather than
  canceling it — a request already on the wire cannot be recalled — records what
  did come back, and gets out of the way of the next one (ADR-0030).

Answers live in **module state**, keyed by URL so a dozen Grafana entries and their
one icon cost one probe (ADR-0030 §3). That is the same single-process assumption
the parse cache in :mod:`little_sister.links` and the in-memory history already make
(ADR-0001): ``start.sh`` runs gunicorn with one worker and eight threads. If that
ever becomes two workers, this and the history break together, which is the right
coupling.

A verdict is deliberately three-valued. ADR-0030 §10 counts only ``404`` / ``410``,
a DNS failure and a refused connection as **dead**, because a corporate ``401`` or
``403`` says "not signed in" at least as often as it says "gone"; everything else
that is not an agreed *alive* code — a ``500``, a timeout, a TLS error — is **no
answer**, which the page reports in its own muted words rather than as a death.
"""
from __future__ import annotations

import math
import socket
import ssl
import threading
from collections.abc import Mapping
from concurrent.futures import Future, as_completed
from dataclasses import dataclass, field
from datetime import datetime

from little_sister import self_report
from little_sister.checks import CheckError, parse_duration
from little_sister.fetch import USER_AGENT, fetch
from little_sister.links import DEFAULT_PROBE_INTERVAL, LinksConfig
from little_sister.logger import logger
from little_sister.pool import DaemonPool
from little_sister.reasons import plain
from little_sister.transport import RemoteError

#: How long one request may take. A probe pass now starts from a **request**
#: thread's daemon child rather than from the engine's pool, so a hung internal host
#: must cost seconds, not minutes.
REQUEST_TIMEOUT = 5.0

#: How many probes run at once. Sixty entries must never leave as sixty
#: simultaneous requests — from the instance's point of view that is a burst nobody
#: asked for, and from a corporate proxy's it looks like one.
CONCURRENCY = 6

#: Fallback when ``interval:`` is not a duration this can read. The loader keeps the
#: key as the raw string it was written as (so it need not import the ``checks``
#: package); parsing it is this module's job, and a typo falls back to the documented
#: default rather than probing on every open.
DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60

#: The statuses that mean **gone** rather than *guarded*. Everything else that is
#: not in the deployment's ``alive:`` list is *no answer* (ADR-0030 §10).
DEAD_STATUS = (404, 410)

#: Statuses that are a server's opinion about **methods**, not about existence — so
#: the probe asks again with ``GET`` before believing them.
RETRY_WITH_GET = (405, 501)

#: How long a deliberate *check now* waits before rendering what came back. It is a
#: ceiling on the **wait**, not on the pass: whatever has not answered by then keeps
#: its previous verdict and age while the pass finishes in the background. Long
#: enough for a page of healthy hosts to come back whole, short enough that a hung
#: internal host costs one of gunicorn's eight threads ten seconds and no more.
CHECK_NOW_DEADLINE = 10.0

#: How soon a forced pass may follow the last one. This control is the only thing on
#: the instance that lets a reader spend outbound requests on purpose, so it has a
#: floor — and the floor is short, because the case it exists for is somebody who
#: just fixed a URL and wants to watch it go green. A press inside the gap **joins**
#: a running pass and otherwise changes nothing, which is what the ages already say.
MIN_FORCED_GAP = 15.0

#: The shortest a pass's deadline may be, whatever the arithmetic below says. It sits
#: comfortably above :data:`CHECK_NOW_DEADLINE` on purpose: *check now* promises that
#: "the pass carries on without me", and a pass that expired before the press it came
#: from stopped waiting would make that sentence false.
PASS_DEADLINE_FLOOR = 30.0

#: How much longer than the arithmetic a pass may take before it is abandoned. Two,
#: not one-and-a-bit, for two reasons that compound: one probe may cost **two**
#: requests (``HEAD``, then ``GET`` for a ``405``), and :data:`REQUEST_TIMEOUT` bounds
#: a socket *operation*, so even one request can honestly exceed it. This is a bound
#: on the pass, not a prediction of it — every healthy page finishes far inside it.
PASS_DEADLINE_SLACK = 2.0

#: How much beyond its own deadline a pass may sit in :data:`_running` before a new
#: one supersedes it. A pass enforces its own deadline, so this should never fire; it
#: is here because "one wedged pass cannot freeze reachability" should be a property
#: of the structure rather than of an argument about where a thread can block.
PASS_ABANDON_GRACE = 5.0

#: How many abandoned passes may still be waiting on a host before this stops
#: starting new ones. Each one holds worker threads and sockets that a host is
#: refusing to release, and a page that started a fresh pass every six hours against
#: a target that never answers would accumulate them without bound. Three is a
#: judgment: enough that a single slow morning does not pause probing, few enough
#: that the leak is small and the page can say so honestly.
MAX_STUCK_PASSES = 3


@dataclass(frozen=True)
class Verdict:
    """One target's last answer, and when it was given.

    ``alive`` is ``True`` (an agreed status), ``False`` (gone) or ``None`` (no
    answer). :attr:`detail` is short plain text for the page — never Markdown, and
    never the transport exception's full text, which names paths and proxies.

    **Three-valued like** :class:`~little_sister.transport.Fault`, **and about a
    different thing.** This is a claim about the *target*: whether the URL on the page
    still leads somewhere. A `Fault` is a claim about the *asking* — whether a request
    got an answer and what kind — and one does not derive the other, which is why
    :func:`_transport_verdict` maps between them by hand rather than sharing a type.
    Deliberate, and stated here so the next reader of both does not have to work it out.
    """
    url: str
    alive: bool | None
    detail: str
    checked_at: datetime

    @property
    def failed(self) -> bool:
        """Whether this answer is worth showing beside the entry it belongs to."""
        return self.alive is not True


@dataclass(frozen=True)
class IconFailure:
    """A remote icon URL that did not answer, named by the mark it draws.

    An icon is not a row on this page, so its verdict has nowhere to sit beside;
    it joins the configuration problems instead, which is the same audience —
    whoever maintains the file.
    """
    name: str
    verdict: Verdict


@dataclass(frozen=True)
class ProbeView:
    """Everything one render of ``/links`` needs to know about reachability.

    :attr:`active` separates *nothing was asked* from *nothing answered yet*: a
    deployment that probes nothing shows no freshness line at all, rather than a
    permanent "nothing checked yet" for a question it never asked.

    :attr:`running` is a pass still in flight as this response was built — after a
    *check now* that hit its deadline, or beside an open that started one. The page
    does not poll, so saying it is the difference between a control that looks
    broken and one whose remaining answers are a reload away.

    :attr:`stuck` counts passes that reached their deadline and walked away from a
    host that had still not answered. It is on the page rather than only in the log
    because it is the one condition under which the ages stop meaning what they say:
    somebody pressing *check now* and seeing nothing move deserves to be told that
    a target is holding the door, not left to conclude the button is broken.
    """
    active: bool = False
    checked_at: datetime | None = None
    verdicts: Mapping[str, Verdict] = field(default_factory=dict)
    icon_failures: tuple[IconFailure, ...] = ()
    running: bool = False
    stuck: int = 0

    @property
    def paused(self) -> bool:
        """Whether enough passes are stuck that no new one will start.

        Distinct from :attr:`stuck` being non-zero: one abandoned pass costs a few
        threads and nothing else, while :data:`MAX_STUCK_PASSES` of them is the
        point at which the page stops refreshing at all — a different sentence,
        and the only one that is really an apology.
        """
        return self.stuck >= MAX_STUCK_PASSES

    @property
    def failures(self) -> int:
        """How many held answers are not alive — links and icons alike.

        The page draws each of those where it belongs (a row, or the problems
        block); this is the one number the freshness line needs, because *all
        clear* is a fact about the page rather than about any one entry.
        """
        return sum(1 for verdict in self.verdicts.values() if verdict.failed)


def targets(config: LinksConfig) -> tuple[str, ...]:
    """Every URL this configuration asks to be probed, deduped, in page order.

    Links are opt-in per entry and icons by the ``check:`` block, and only a
    **remote** icon can be a target at all: a local file and a pack member are
    settled offline at load (ADR-0030 §8), so ``icons: true`` probes an empty set in
    any deployment whose marks are built-in or its own. Only the names entries
    actually use are asked about — a map that defines twenty marks for six entries
    costs six.

    The entry's own origin favicon is **not** probed. It is the fallback for an
    entry that named no mark at all, and probing it would turn every open into one
    request per distinct host on the page.
    """
    seen: dict[str, None] = {}
    for group in config.groups:
        for link in group.links:
            if config.probe.links and link.check:
                seen.setdefault(link.url, None)
            if config.probe.icons and link.icon:
                for url in _remote_icon_urls(config, link.icon):
                    seen.setdefault(url, None)
    return tuple(seen)


def refresh_if_due(config: LinksConfig) -> threading.Event | None:
    """Start a pass when the newest answer is older than ``interval:``.

    The whole of the trigger (ADR-0030), and it **returns
    immediately** in every branch: this is called from the request that renders the
    page. A target nothing has ever asked about counts as infinitely old, so an
    entry added to the file is probed on the next open rather than up to an interval
    later — every probe stores a verdict, including a failed one, so that clause
    settles after one pass instead of firing forever.

    The pass's event comes back for a caller that has a reason to know when it
    finished; the page is not one of them, and ``None`` means nothing was owed.
    """
    urls = targets(config)
    if not urls:
        return None
    if not _is_due(urls, _interval_seconds(config)):
        return None
    return start_pass(config)


def refresh_now(config: LinksConfig,
                deadline: float = CHECK_NOW_DEADLINE) -> bool:
    """Probe on demand and **wait** for it, up to ``deadline``.

    *Never block* is a rule about the open, not about the reader (ADR-0030): the
    person who has just fixed a URL is the one case the time gate gets wrong, and
    they are waiting on purpose. So this one waits — but only for the deadline, and
    the pass carries on without it: whatever has not answered keeps its previous
    verdict and its age, so a hung internal host costs one stale row rather than a
    stuck request thread.

    A press that lands **mid-pass joins that pass** rather than starting a second,
    so ten readers cost one sweep and two presses two seconds apart return together.
    A press inside :data:`MIN_FORCED_GAP` of the last forced pass, with none
    running, does nothing at all — the answers it would refresh are seconds old, and
    the page already says how old.

    Returns whether a pass finished inside the deadline, which is what the render
    needs in order to say that one is still going.
    """
    global _last_forced
    if not targets(config):
        return True
    with _lock:
        running = _running
        if running is not None and running.overdue():
            # Joining a pass that has stopped honoring its own deadline is joining
            # nothing, and the gap does not apply either: the gap exists to stop a
            # reader spending requests on answers that are seconds old, and these
            # are not going to arrive at all. Fall through, and let `start_pass`
            # supersede it.
            running = None
            _last_forced = datetime.now()
        elif running is None:
            if _last_forced is not None and (
                    datetime.now() - _last_forced).total_seconds() < MIN_FORCED_GAP:
                return True
            _last_forced = datetime.now()
    if running is not None:
        return running.done.wait(deadline)
    # Outside the lock on purpose: `start_pass` takes it, and it either starts the
    # pass or hands back one another thread started in the meantime — which is the
    # same joining behavior, one instant later.
    return start_pass(config).wait(deadline)


def is_running() -> bool:
    """Whether a pass is in flight right now."""
    with _lock:
        return _running is not None


def stuck_passes() -> int:
    """How many abandoned passes are still waiting on a host that never answered.

    Pruned as it is read: a leftover stops counting the moment its last probe
    finishes, however long after the pass that started it gave up.
    """
    with _lock:
        _prune_stuck()
        return len(_stuck)


def start_pass(config: LinksConfig) -> threading.Event:
    """Run one pass on a daemon thread; join the running one if there is one.

    The returned event is set when that pass finishes — the seam a deliberate
    *check now* waits on. A caller who only wants the pass started ignores it.

    Three things can happen instead of a new pass. A pass is **running** and inside
    its deadline: every caller gets its event, which is the joining behavior ten
    simultaneous readers rely on. A pass is running and **overdue** past its grace:
    it has failed to enforce its own deadline, so this one supersedes it — the old
    generation's writes are refused from that moment, and it is not waited for. Or
    :data:`MAX_STUCK_PASSES` passes are already stuck on a host: nothing is started,
    and the event comes back already set, because the honest answer to "wait for the
    pass" is that there is not going to be one. The page says so in words; a caller
    that only wanted it started is unharmed either way.
    """
    global _running, _generation
    try:
        count = len(targets(config))
    except Exception:
        # The deadline is sized from the target count, and this runs on the request
        # thread that only asked for a pass to be started. A configuration this
        # cannot read must not be raised *here* — `_run_pass` reaches the same call
        # a moment later and logs it where a failed pass belongs.
        count = 0
    with _lock:
        if _stopped:
            # The instance has stopped: the honest answer to "wait for the pass" is
            # that there is not going to be one.
            stopped = threading.Event()
            stopped.set()
            return stopped
        running = _running
        if running is not None:
            if not running.overdue():
                return running.done
            self_report.runtime.see(
                "links.overrun",
                plain(f"a reachability pass started "
                      f"{running.started_at.isoformat(timespec='seconds')} has "
                      f"not honored its own {running.deadline:.0f}s deadline — a "
                      f"new one was started (ADR-0030)"))
        _prune_stuck()
        if len(_stuck) >= MAX_STUCK_PASSES:
            self_report.runtime.see(
                "links.stuck",
                plain(f"{len(_stuck)} reachability passes are still waiting on a "
                      f"host that has not answered — no new one is started until "
                      f"one of them lets go (ADR-0030)"))
            refused = threading.Event()
            refused.set()
            return refused
        _generation += 1
        current = _Pass(generation=_generation, done=threading.Event(),
                        started_at=datetime.now(),
                        deadline=_pass_deadline(count))
        _running = current
    thread = threading.Thread(target=_run_pass, args=(config, current),
                             name="links-probe", daemon=True)
    thread.start()
    return current.done


def page_view(config: LinksConfig) -> ProbeView:
    """What ``/links`` renders from: the answers, their age, the icon failures.

    Read-only and cheap — it takes a copy of the store under the lock and leaves the
    trigger to :func:`refresh_if_due`, so the template's data and the decision to go
    probe are not the same call.
    """
    urls = targets(config)
    if not urls:
        return ProbeView(verdicts={})
    known = {url: verdict for url, verdict in results().items() if url in urls}
    checked_at = max((v.checked_at for v in known.values()), default=None)
    return ProbeView(active=True, checked_at=checked_at, verdicts=known,
                     icon_failures=_icon_failures(config, known),
                     running=is_running(), stuck=stuck_passes())


def results() -> Mapping[str, Verdict]:
    """A snapshot of every answer held, keyed by URL."""
    with _lock:
        return dict(_results)


def forget_probe_results() -> None:
    """Drop every answer and the forced-pass clock, so the next open probes again.

    Needed by tests: module state that outlives one test is state one test can
    decide another's outcome with — and a forced pass one test made would silence
    the next test's *check now* for fifteen seconds.

    It also **disowns any pass still running**. Clearing :data:`_running` is safe
    precisely because of the generation guard: a pass whose record is no longer the
    current one writes nothing, so a test that deliberately wedged a probe cannot
    leak a verdict into the next test's store when its host finally answers. What
    this cannot do is unblock the socket, which is why the wedging tests release
    their own event rather than relying on this.
    """
    global _last_forced, _running, _pool, _stopped
    with _lock:
        _results.clear()
        _stuck.clear()
        _running = None
        _last_forced = None
        _pool = None
        _stopped = False


def stop_probing() -> None:
    """The instance's stop (ADR-0088 decision 6): the pass in flight is abandoned
    the way it is at its own deadline — what it has queued is canceled, and what it
    delivers later is refused by the generation guard — and no pass starts after it.
    What the probe knows lives in memory only, so there is nothing here to save."""
    global _running, _stopped
    with _lock:
        _stopped = True
        _running = None
        pool = _pool
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


@dataclass(frozen=True)
class _Pass:
    """One sweep's identity, so a later one can tell whether it is still the one.

    The **generation** is the whole point. Abandonment means a pass can still be
    holding sockets after a newer pass has started, and two passes writing verdicts
    into one store interleave into a set of answers with no single age. So every
    write, the stale prune and the clearing of :data:`_running` all ask first
    whether this pass is still the current one, under the lock; a superseded pass
    stops writing and leaves quietly.

    :attr:`deadline` travels with the record rather than being recomputed, so the
    thread that might supersede this pass can tell when it is overdue without
    knowing how many targets it was given.
    """
    generation: int
    done: threading.Event
    started_at: datetime
    deadline: float

    def overdue(self) -> bool:
        """Whether this pass is so far past its own deadline that it has stopped
        enforcing it — the only case in which a new pass takes the slot by force."""
        return (datetime.now() - self.started_at).total_seconds() > (
            self.deadline + PASS_ABANDON_GRACE)


@dataclass(frozen=True)
class _Stuck:
    """An abandoned pass's leftovers: the probes that were still on the wire.

    Held so the page can count them and :func:`start_pass` can refuse to add a
    fourth. The futures are kept rather than a plain number because *finished* is
    the only honest way to stop counting one — the worker thread ends when its
    socket does, and nothing else tells us when that was.
    """
    generation: int
    started_at: datetime
    pending: tuple[Future[Verdict], ...]

    def stuck(self) -> bool:
        """Whether anything from this pass is still waiting on a host."""
        return any(not future.done() for future in self.pending)


_lock = threading.Lock()
_results: dict[str, Verdict] = {}
_running: _Pass | None = None
#: The current sweep's pool, so the instance's stop can cancel what it has queued.
_pool: DaemonPool | None = None
#: Set by the instance's stop (ADR-0088 decision 6): no pass starts after it.
_stopped = False
_generation = 0
_stuck: list[_Stuck] = []
_last_forced: datetime | None = None


def _interval_seconds(config: LinksConfig) -> int:
    """``interval:`` as seconds — how stale an answer may be before an open
    refreshes it. The key keeps the name it had when it meant *how often a timer
    fires*; what changed is what it measures.

    A value this cannot read **falls back**, as the constant beside it has always
    promised. It did not: ``parse_duration`` uses its default only for an absent
    value and *raises* on a malformed one, so `interval: '6 hours'` — a plausible
    thing to type — took the whole page to a 500. The loader keeps the key as raw
    text and does not validate it, so nothing warned first either.

    A non-positive value falls back too: it would make every open due, which is the
    stampede the interval exists to prevent.
    """
    raw = config.probe.interval or DEFAULT_PROBE_INTERVAL
    try:
        seconds = parse_duration(raw, DEFAULT_INTERVAL_SECONDS)
    except (CheckError, OverflowError, ValueError):
        self_report.startup.note(
            "links.interval",
            plain(f"links: {raw!r} is not a duration this can read — the default "
                  f"of {DEFAULT_PROBE_INTERVAL} between reachability passes is in "
                  f"use (ADR-0030)"))
        return DEFAULT_INTERVAL_SECONDS
    if seconds <= 0:
        self_report.startup.note(
            "links.interval",
            plain(f"links: an interval of {raw!r} would make every open due — the "
                  f"default of {DEFAULT_PROBE_INTERVAL} is in use instead "
                  f"(ADR-0030)"))
        return DEFAULT_INTERVAL_SECONDS
    return seconds


def _is_due(urls: tuple[str, ...], interval: int) -> bool:
    """Whether a pass is owed: something has never been asked, or every answer is
    older than the interval."""
    with _lock:
        answers = [_results[url].checked_at for url in urls if url in _results]
    if len(answers) < len(urls):
        return True
    return (datetime.now() - max(answers)).total_seconds() >= interval


def _pass_deadline(count: int) -> float:
    """How long a sweep of ``count`` targets may take before it is abandoned.

    Derived rather than fixed, because a page of six links and a page of sixty are
    not the same sweep: :data:`CONCURRENCY` probes run at once, so the honest unit is
    **rounds**, each of which may cost a full :data:`REQUEST_TIMEOUT` (and, with the
    ``GET`` retry, more — which is what the slack is for). The floor keeps a small
    page's deadline above :data:`CHECK_NOW_DEADLINE`, so *check now* never outlives
    the pass it started.
    """
    rounds = math.ceil(max(count, 1) / CONCURRENCY)
    return max(PASS_DEADLINE_FLOOR, rounds * REQUEST_TIMEOUT * PASS_DEADLINE_SLACK)


def _is_current(current: _Pass) -> bool:
    """Whether this pass still owns the store. Callers must hold :data:`_lock`."""
    return _running is not None and _running.generation == current.generation


def _store(current: _Pass, verdict: Verdict) -> bool:
    """Write one answer, unless this pass has been superseded.

    The return value is the signal to **stop**: a pass that finds itself no longer
    current has nothing useful left to do, because everything it would write is
    older than what the pass that replaced it is writing.
    """
    with _lock:
        if not _is_current(current):
            return False
        _results[verdict.url] = verdict
        return True


def _prune_stuck() -> None:
    """Drop leftovers whose probes have all finished. Callers hold :data:`_lock`."""
    _stuck[:] = [leftover for leftover in _stuck if leftover.stuck()]


def _run_pass(config: LinksConfig, current: _Pass) -> None:
    """One sweep of every target, then prune what the file no longer names.

    Verdicts are stored **as they genuinely arrive**: :func:`concurrent.futures.
    as_completed` yields in completion order, where ``map`` yielded in submission
    order and so made a slow first target hold every later answer out of the store
    until it finished. The docstring here claimed the former while the code did the
    latter, which mattered exactly when it was load-bearing — under a deadline,
    where "keep what came back" is the whole promise.
    """
    try:
        urls = targets(config)
        alive = frozenset(config.probe.alive)
        if urls and not _sweep(current, urls, alive):
            return
        with _lock:
            if _is_current(current):
                for stale in set(_results) - set(urls):
                    del _results[stale]
    except Exception as error:
        # A links page must never be the reason an instance looks broken, and this
        # runs on a thread nobody is waiting on for correctness.
        logger.exception("links: reachability pass failed")
        self_report.runtime.see(
            "links.pass",
            plain(f"a reachability pass raised ({error!r}); the links keep what "
                  f"they had"), log=False)
    finally:
        _finish(current)


def _sweep(current: _Pass, urls: tuple[str, ...],
           alive: frozenset[int]) -> bool:
    """Probe every target, storing answers as they land. ``False`` if superseded.

    The pool is **not** a context manager any more, and that is the fix rather than
    a style choice: ``with ThreadPoolExecutor(...)`` calls ``shutdown(wait=True)`` on
    the way out, so the pass could not end while a worker was wedged — the deadline
    would have been a deadline on nothing. Leaving the block by hand is what lets
    this walk away.
    """
    global _pool
    # Daemon threads the interpreter does not join (ADR-0088 decision 6): a pass in
    # flight at the instance's stop is left, never waited for.
    pool = DaemonPool(min(CONCURRENCY, len(urls)), "links-probe")
    with _lock:
        _pool = pool
    futures: dict[Future[Verdict], str] = {
        pool.submit(_probe, url, alive): url for url in urls}
    try:
        for future in as_completed(futures, timeout=current.deadline):
            try:
                verdict = future.result()
            except Exception as error:
                # `_probe` catches what a probe is expected to fail with; anything
                # left is a bug, and one target's bug must not cost the other
                # fifty-nine their answers — that is the shape of the bug this
                # module has already been bitten by once (ADR-0030).
                logger.exception("links: probing %s failed", futures[future])
                self_report.runtime.see(
                    "links.probe",
                    plain(f"probing {futures[future]} raised ({error!r}); that "
                          f"link keeps what it had"), log=False)
                continue
            if not _store(current, verdict):
                pool.shutdown(wait=False, cancel_futures=True)
                return False
    except TimeoutError:
        _abandon(current, pool, futures)
        return True
    pool.shutdown(wait=False)
    return True


def _abandon(current: _Pass, pool: DaemonPool,
             futures: Mapping[Future[Verdict], str]) -> None:
    """Give up on a pass that reached its deadline, keeping what did come back.

    Three fates, and the difference between them is the point of doing this by hand
    rather than letting the pool sort it out:

    * **Answered** — the verdict, stored as it arrived. Some of these landed between
      the last :func:`as_completed` yield and the timeout, so they are collected
      here too; a probe that succeeded a millisecond too late is still an answer.
    * **Never started** — canceled out of the queue, so nothing was asked and
      nothing is known. Its previous verdict and age stand, which is the truth: this
      pass never got to it.
    * **Started and unfinished** — a verdict of *no answer*, which is exactly what
      the reader needs to see. It is not a death (ADR-0030 §10 reserves that for a
      refusal or a name that does not resolve) and it must not be silence, because
      silence would leave an hours-old *alive* beside an entry whose host has been
      swallowing requests all morning.

    The probes in that third group cannot be recalled — they are on the wire — so
    what is left is a leftover the page counts and :func:`start_pass` refuses to add
    a fourth of.
    """
    now = datetime.now()
    canceled = {future for future in futures if future.cancel()}
    for future, url in futures.items():
        if future in canceled:
            continue
        if future.done():
            try:
                verdict = future.result()
            except Exception as error:
                logger.exception("links: probing %s failed", url)
                self_report.runtime.see(
                    "links.probe",
                    plain(f"probing {url} raised ({error!r}); that link keeps "
                          f"what it had"), log=False)
                continue
        else:
            verdict = Verdict(url, None, f"no answer in {current.deadline:.0f}s",
                              now)
        if not _store(current, verdict):
            break
    pending = tuple(future for future in futures
                    if future not in canceled and not future.done())
    pool.shutdown(wait=False, cancel_futures=True)
    self_report.runtime.see(
        "links.gave-up",
        plain(f"the reachability pass gave up after {current.deadline:.0f}s with "
              f"{len(pending)} target(s) still unanswered and {len(canceled)} never "
              f"asked — they keep what they had (ADR-0030)"))
    if pending:
        with _lock:
            _prune_stuck()
            _stuck.append(_Stuck(generation=current.generation,
                                 started_at=current.started_at, pending=pending))


def _finish(current: _Pass) -> None:
    """Release the pass slot — **only if this pass still holds it**.

    An abandoned pass that comes back to life would otherwise clear a slot its
    successor is using, and the successor's ``finally`` would then find nothing to
    clear; the page would report no pass running while one was, and the next open
    would start a third. The event is set either way: whoever waited on *this* pass
    is owed the news that it is over, whether or not it still counted.
    """
    global _running
    with _lock:
        if _is_current(current):
            _running = None
    current.done.set()


def _probe(url: str, alive: frozenset[int]) -> Verdict:
    """Ask one URL whether it is still there.

    ``HEAD`` first — a probe has no use for the body — falling back to ``GET`` when
    the server's answer is about the *method* rather than about the resource.
    """
    now = datetime.now()
    try:
        status = _request(url, "HEAD")
        if status in RETRY_WITH_GET:
            status = _request(url, "GET")
    except RemoteError as error:
        return _transport_verdict(url, error, now)

    if status in alive:
        return Verdict(url, True, f"HTTP {status}", now)
    if status in DEAD_STATUS:
        return Verdict(url, False, f"HTTP {status}", now)
    return Verdict(url, None, f"HTTP {status}", now)


#: Which subsystem is knocking, appended to the library's own agent — a server log
#: that shows a probe every quarter hour is entitled to say what is probing it.
_AGENT = f"{USER_AGENT} (link probe)"


def _request(url: str, method: str) -> int:
    """One request's status code, whatever that status is.

    **Redirects are reported, not followed.** ``301`` and ``302`` are in the default
    ``alive:`` list, which they could never reach if urllib quietly followed them —
    the reader would be told about the page at the end of the chain, which may be a
    login wall or a homepage that answers ``200`` for everything. A moved entry is
    alive **and** worth seeing as moved.

    No body is read: a probe has no use for one, and this is the only reader on the
    page's own clock. The URL is operator-configured (trusted), the same standing this
    project's ``http`` check works under.

    **And no ``deadline=``, which is right here for a different reason than in the
    ``http`` check.** ``fetch``'s deadline bounds a *body* read, and with
    ``read_body=False`` there is no body read to bound. What bounds a probe that never
    comes back is the mechanism this module already has: the pass reaches its own
    deadline, **abandons** what has not answered, records what did, and gets out of the
    way (ADR-0030). Passing a ``Deadline`` as well would put a
    second, weaker clock beside a working one — weaker because it could only fire
    between chunks of a body nobody asks for.
    """
    return fetch(url, timeout=REQUEST_TIMEOUT, follow_redirects=False,
                 method=method, headers={"User-Agent": _AGENT},
                 read_body=False).status


def _transport_verdict(url: str, error: Exception, now: datetime) -> Verdict:
    """A failure that never reached HTTP, classified by ADR-0030 §10.

    A name that does not resolve and a port that refuses are **gone** — both are
    what a retired host looks like. A timeout is **not**: an internal host behind a
    slow VPN answers eventually, and calling that dead is how a page starts crying
    wolf. The wording is ours rather than the exception's, which names proxies and
    certificate paths a page has no business showing.
    """
    original = error.__cause__ if isinstance(error, RemoteError) else error
    reason = getattr(original, "reason", original)
    if isinstance(reason, socket.gaierror):
        return Verdict(url, False, "host not found", now)
    if isinstance(reason, ConnectionRefusedError):
        return Verdict(url, False, "connection refused", now)
    if isinstance(reason, TimeoutError):
        return Verdict(url, None, "no answer in time", now)
    if isinstance(reason, ssl.SSLError):
        return Verdict(url, None, "TLS handshake failed", now)
    return Verdict(url, None, "no answer", now)


def _remote_icon_urls(config: LinksConfig, name: str) -> tuple[str, ...]:
    """The remote URLs one icon name resolves to, both backgrounds, deduped.

    A pair whose two files are one URL is one target; a local file or a pack member
    is none at all.
    """
    icon = config.icon_for(name)
    if icon is None or icon.suppressed:
        return ()
    urls: dict[str, None] = {}
    for variant in ("on-light", "on-dark"):
        source = icon.file_for(variant)
        if source is not None and source.url:
            urls.setdefault(source.url, None)
    return tuple(urls)


def _icon_failures(config: LinksConfig,
                   known: Mapping[str, Verdict]) -> tuple[IconFailure, ...]:
    """Every used icon name whose remote URL did not answer, once per name."""
    failures: list[IconFailure] = []
    seen: set[str] = set()
    for group in config.groups:
        for link in group.links:
            if not link.icon or link.icon in seen:
                continue
            seen.add(link.icon)
            for url in _remote_icon_urls(config, link.icon):
                verdict = known.get(url)
                if verdict is not None and verdict.failed:
                    failures.append(IconFailure(name=link.icon, verdict=verdict))
    return tuple(failures)
