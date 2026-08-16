"""Transport policy: what a check does about a request that might not answer.

Four questions face every check that reads a remote service, and until this module
existed each of them answered all four for itself (ADR-0058): how long may **one
request** take, what bounds **the whole run** when one ``run()`` asks fifty times,
what is worth **asking again**, and what a failure **means**.

What lives here is the *policy*, not the transport. There is **no I/O** in this
module and nothing about HTTP: :class:`Deadline` bounds a run whatever it talks to,
:class:`Fault` classifies a failure whatever raised it, and :func:`ask` retries a
callable. A check whose transport is a vendor SDK wears all of it while the SDK does
the socket work — which is the whole reason the vocabulary and the client are
separate things here.

It also imports nothing from ``little_sister``, for the reason
:mod:`little_sister.errors` gives for its own existence: importing the ``checks``
package registers every built-in check type as a side effect, and this module is used
by a built-in check, by the link prober and by installed packages, none of which has
any business triggering that.

What is deliberately **not** here is any mapping from a :class:`Fault` to a
``StatusCode``. For an ``http`` check the endpoint *is* the subject of the
measurement, so failing to answer is the measurement; for a check that reads an API
in order to grade something else the endpoint is the *instrument*, and grading the
subject for the instrument's outage is the bug this vocabulary exists to prevent.
That mapping is one line at the call site, where the check knows which it has.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TypeVar

__all__ = ["Deadline", "DeadlineExceeded", "Fault", "RemoteError", "ask"]

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class Fault(Enum):
    """What went wrong, told **by status and never by message text** (ADR-0058).

    Three members, because two cannot hold the third case: a payload of the wrong
    shape and a ``404`` are both "not transient", and they are not the same fact.
    A ``404`` is about the thing being measured; a list arriving where an object was
    promised is about the reading, or about the API.

    **Not the link prober's** :class:`~little_sister.link_probe.Verdict`, which is also
    three-valued and is about something else. That one answers *what is true of the
    target* — alive, gone, or no answer — and it is a reading a page shows.
    This one answers *what happened when we asked*, and nothing here says whether the
    subject is healthy: for an ``http`` check a failure to answer **is** the
    measurement, while for a check reading an API to grade something else the same
    failure says nothing about the subject (ADR-0058, `implementing-checks.md` §7). Two
    three-valued types in one process is deliberate, not duplication — and if either
    grows a member, this paragraph is where the distinction is written down.
    """

    #: We could not ask — a 5xx, a timeout, a transport failure. Asking again could
    #: change the answer, and this is the only member :func:`ask` retries.
    TRANSIENT = auto()
    #: They answered, and the answer was no — a 4xx: absent, or not visible to this
    #: credential. Asking again would get the same answer faster.
    ANSWERED = auto()
    #: They answered, and the answer was unusable. Asking again returns the same
    #: shape, so this is not retried either — but it is a different report from
    #: `ANSWERED`, and a check whose error type cannot tell them apart cannot say so.
    MALFORMED = auto()


class RemoteError(Exception):
    """A request to a remote service failed, with what went wrong attached.

    ``fault`` is **required and has no default**. The classification is the decision
    this module exists to make consistent, and a default would be that decision
    taken by whoever forgot to pass it — in one direction spurious retries, in the
    other a node graded for somebody else's outage.

    ``status`` is the response status where there was a response, and ``None`` where
    the failure never reached one. It is not a substitute for the fault: a malformed
    payload has no status and a ``404`` has one, and neither is `TRANSIENT`.

    ``retry_after`` is **seconds the service itself asked us to wait**, when it said
    so, and ``None`` when it did not. It is not a fourth kind of failure: a throttle is
    `TRANSIENT` — asking again could change the answer — and this is only the number.
    Setting it is the **caller's** job, because no status identifies a throttle: a
    service may answer ``403`` or ``429`` for it, and a bare ``403`` may equally mean
    *this credential may not see it*. Only code that speaks a particular service's
    dialect can read its headers and tell. :func:`ask` spends this in place of its own
    backoff; nothing else in this module looks at it.

    **Subclass it.** A package that reads one service keeps its own error class, its
    own message prefixes and every ``except`` clause it already has; :func:`ask`
    reads :attr:`fault` and :attr:`retry_after`, and nothing else.
    """

    def __init__(self, message: str, *, status: int | None = None,
                 fault: Fault, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.fault = fault
        self.retry_after = retry_after


class DeadlineExceeded(Exception):
    """The run's own budget ran out — and this is **not** a :class:`RemoteError`.

    Deliberately outside that hierarchy, so a per-item handler cannot swallow it. A
    check reporting one child per repository catches its own error per repository and
    turns it into a line; if the deadline arrived as that class, one run-level fact
    would be spelled as forty item-level ones. Raised past those handlers, a run
    keeps the children that finished and says **once** that it was cut short.

    Its message names the budget and what was spent, not the request that was about
    to be made, for the same reason: the fact is about the run.
    """


@dataclass
class Deadline:
    """When this run must stop, and how much of it is left.

    A check builds one from its own ``timeout_seconds`` at the top of ``run()``, and
    that is what makes `timeout:` a bound rather than a wish: the engine does not
    bound ``run()`` and never claimed to (architecture.md §4.6), so a check that
    spends the value as a socket timeout has one budget per request and none at all
    for the run.

    ``clock`` is injected so a test can drive a budget without spending one, and so
    the whole run reads **one** clock — mixing wall and monotonic time makes the
    budget jump the moment the machine's clock is corrected.
    """

    seconds: float
    clock: Callable[[], float] = time.monotonic
    started: float = field(init=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    def elapsed(self) -> float:
        """How long this run has been going."""
        return self.clock() - self.started

    def remaining(self) -> float:
        """What is left of the budget — negative once it has been overspent."""
        return self.seconds - self.elapsed()

    def expired(self) -> bool:
        """Whether the budget is gone."""
        return self.remaining() <= 0

    def budget(self, timeout: float) -> float:
        """A per-request timeout, **clamped to what is left of the run**.

        The clamp is the point of this class. Without it a fifteen-second request
        may start with two seconds of budget left and overrun the run by thirteen,
        which makes a deadline a suggestion rather than a bound.

        On an overspent budget it returns ``0.0`` — which most socket APIs read as
        *non-blocking* rather than as *no time left*, so a caller asks
        :meth:`expired` first, the way :func:`ask` does, instead of issuing a
        request that cannot succeed and reporting whatever that produces.
        """
        return min(timeout, max(0.0, self.remaining()))

    def affords(self, wait: float) -> bool:
        """Whether pausing for ``wait`` leaves the run able to do anything after it.

        A retry certain to be cut off spends its backoff to learn nothing.
        """
        return self.remaining() > wait


def ask(operation: Callable[[], _T], *, deadline: Deadline | None = None,
        retries: int = 1, backoff: float = 1.0,
        sleep: Callable[[float], None] = time.sleep) -> _T:
    """Call ``operation``, retrying only what asking again could change.

    ``retries`` counts attempts **after** the first, so the default of one is a
    single extra try — enough to tell a hiccup from a bad ten minutes, where a
    second would only buy a sharper answer at the cost of the run's remaining time.

    A retry happens when all three hold: the fault is `Fault.TRANSIENT`, attempts
    remain, and the deadline can still afford the wait. Anything else re-raises
    the error the operation raised, so the caller's own subclass, status and message
    reach the caller untouched.

    **The wait is the service's when the service named one.** A `RemoteError` carrying
    a `retry_after` is asking to be left alone for that many seconds, and that number
    replaces ``backoff`` — pressing a service that has just said *not yet* is how an
    integration gets itself blocked. The veto is unchanged, which is what keeps this
    inside the budget the check granted: a two-second wait is absorbed, and a
    ten-minute one is refused and the error re-raised, because **a wait outliving the
    check's budget is not this function's to take.** What the check does about that is
    the check's business; a request layer does not reschedule anything.

    ``sleep`` is injected for the same reason ``Deadline.clock`` is: the policy is
    testable without spending real seconds.

    :raises DeadlineExceeded: before an attempt, when the budget is already spent —
        which in practice means **on entry**, and that is how a run of many requests
        meets it: the request that finds the budget gone is never issued. Once inside
        a retry sequence the backoff veto fires first, so a caller whose retries run
        out of time gets the service's own transient error instead. That is the
        better report of the two — the service is what went wrong, and the run-level
        fact belongs to the next request.
    """
    left = retries
    while True:
        if deadline is not None and deadline.expired():
            raise DeadlineExceeded(
                f"the run's budget of {deadline.seconds:g}s ran out after "
                f"{deadline.elapsed():.1f}s")
        try:
            return operation()
        except RemoteError as error:
            if error.fault is not Fault.TRANSIENT or left <= 0:
                raise
            asked = error.retry_after
            wait = backoff if asked is None else asked
            if deadline is not None and not deadline.affords(wait):
                raise
            left -= 1
            logger.info("transient failure (%s), retrying in %.1fs (%s)", error, wait,
                        "the service asked" if asked is not None else "our backoff")
            sleep(wait)
