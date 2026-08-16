"""The transport policy keeps the sentences ADR-0058 wrote down.

Each test below is one claim from that record, tested with the values the claim is
about rather than with whatever exercises the code — the clamp is asserted at
*fifteen seconds with two left*, because that is the arithmetic the doc promises.

Nothing here waits: the clock and the sleep are injected, which is the reason
`Deadline` takes a `clock` and `ask` takes a `sleep` at all.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from little_sister.transport import (
    Deadline,
    DeadlineExceeded,
    Fault,
    RemoteError,
    ask,
)


class _Clock:
    """A clock a test drives by hand, so a budget is spent without waiting."""

    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Sleep:
    """A stand-in for `time.sleep` that records what it was asked to spend."""

    def __init__(self, clock: _Clock | None = None) -> None:
        self.waits: list[float] = []
        self._clock = clock

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        if self._clock is not None:
            self._clock.advance(seconds)


def _failing(fault: Fault, *, status: int | None = None,
             calls: list[int] | None = None) -> object:
    """An operation that always fails with one fault, counting its attempts."""
    def operation() -> str:
        if calls is not None:
            calls.append(1)
        raise RemoteError(f"boom ({fault.name})", status=status, fault=fault)
    return operation


# --- Deadline: the clamp is the point ----------------------------------------


def test_budget_clamps_a_request_timeout_to_what_the_run_has_left() -> None:
    """ADR-0058: "a 15-second timeout with 2 seconds left yields 2"."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(8.0)
    assert deadline.remaining() == pytest.approx(2.0)
    assert deadline.budget(15.0) == pytest.approx(2.0)


def test_budget_is_the_requests_own_timeout_when_the_run_can_afford_it() -> None:
    """The clamp is a ceiling, not a replacement: a short request stays short."""
    deadline = Deadline(300.0, clock=_Clock())
    assert deadline.budget(15.0) == pytest.approx(15.0)


def test_budget_is_never_negative_on_an_overspent_run() -> None:
    """A negative socket timeout is an error, not a bound — the floor is 0.0, and
    `expired()` is how a caller learns not to ask at all."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(25.0)
    assert deadline.remaining() < 0
    assert deadline.budget(15.0) == 0.0
    assert deadline.expired()


def test_a_fresh_deadline_has_not_expired_and_has_its_whole_budget() -> None:
    deadline = Deadline(30.0, clock=_Clock())
    assert not deadline.expired()
    assert deadline.elapsed() == 0.0
    assert deadline.remaining() == pytest.approx(30.0)


def test_a_deadline_expires_exactly_at_zero_remaining() -> None:
    """`expired()` is `remaining() <= 0`: a budget spent to the last microsecond has
    nothing left to spend, so the boundary belongs on the expired side."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(10.0)
    assert deadline.remaining() == 0.0
    assert deadline.expired()


def test_affords_refuses_a_wait_that_leaves_the_run_nothing_afterward() -> None:
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(9.0)
    assert deadline.affords(0.5)      # a second of work left after the pause
    assert not deadline.affords(1.0)  # the pause *is* the rest of the run
    assert not deadline.affords(5.0)


# --- ask: retry only what asking again could change ---------------------------


def test_ask_returns_the_operations_value_and_calls_it_once() -> None:
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        return "answered"

    assert ask(operation, sleep=_Sleep()) == "answered"
    assert len(calls) == 1


def test_ask_retries_a_transient_fault_exactly_once_by_default() -> None:
    """`retries` counts attempts *after* the first, so the default is two calls."""
    calls: list[int] = []
    sleep = _Sleep()
    with pytest.raises(RemoteError):
        ask(_failing(Fault.TRANSIENT, status=503, calls=calls),  # type: ignore[arg-type]
            sleep=sleep)
    assert len(calls) == 2
    assert sleep.waits == [1.0]


def test_ask_honors_a_larger_retry_budget() -> None:
    calls: list[int] = []
    with pytest.raises(RemoteError):
        ask(_failing(Fault.TRANSIENT, calls=calls),  # type: ignore[arg-type]
            retries=3, sleep=_Sleep())
    assert len(calls) == 4


def test_ask_stops_retrying_as_soon_as_the_operation_answers() -> None:
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RemoteError("hiccup", status=502, fault=Fault.TRANSIENT)
        return "answered"

    assert ask(operation, sleep=_Sleep()) == "answered"
    assert len(calls) == 2


@pytest.mark.parametrize("fault", [Fault.ANSWERED, Fault.MALFORMED])
def test_ask_does_not_retry_what_asking_again_cannot_change(fault: Fault) -> None:
    """A 4xx *is* an answer and a bad payload will be the same shape next time."""
    calls: list[int] = []
    sleep = _Sleep()
    with pytest.raises(RemoteError):
        ask(_failing(fault, calls=calls), sleep=sleep)  # type: ignore[arg-type]
    assert len(calls) == 1
    assert sleep.waits == []


def test_ask_re_raises_the_callers_own_subclass_untouched() -> None:
    """A package keeps its own error class, its message and its status."""
    class ServiceError(RemoteError):
        pass

    def operation() -> str:
        raise ServiceError("service says no", status=404, fault=Fault.ANSWERED)

    with pytest.raises(ServiceError) as raised:
        ask(operation, sleep=_Sleep())
    assert str(raised.value) == "service says no"
    assert raised.value.status == 404
    assert raised.value.fault is Fault.ANSWERED


def test_ask_refuses_a_backoff_the_deadline_cannot_afford() -> None:
    """A retry certain to be cut off spends its backoff to learn nothing: the
    transient error is raised instead, and no time is spent."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(9.5)          # 0.5s left, less than the 1.0s backoff
    calls: list[int] = []
    sleep = _Sleep()
    with pytest.raises(RemoteError):
        ask(_failing(Fault.TRANSIENT, calls=calls),  # type: ignore[arg-type]
            deadline=deadline, sleep=sleep)
    assert len(calls) == 1
    assert sleep.waits == []


def test_ask_retries_when_the_deadline_can_still_afford_the_backoff() -> None:
    """The counterpart of the test above, so a deadline that always refused would
    not pass both."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(5.0)          # 5s left, comfortably more than the backoff
    calls: list[int] = []
    sleep = _Sleep(clock)
    with pytest.raises(RemoteError):
        ask(_failing(Fault.TRANSIENT, calls=calls),  # type: ignore[arg-type]
            deadline=deadline, sleep=sleep)
    assert len(calls) == 2
    assert sleep.waits == [1.0]


def test_ask_raises_deadline_exceeded_before_an_attempt_on_a_spent_budget() -> None:
    """It does not issue the request: `budget()` would be 0.0, which a socket API
    reads as non-blocking, and the failure would be reported as the service's."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(11.0)
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        return "should never run"

    with pytest.raises(DeadlineExceeded) as raised:
        ask(operation, deadline=deadline)
    assert calls == []
    assert "10s" in str(raised.value)


def test_a_later_request_in_the_same_run_is_refused_once_the_budget_is_spent() -> None:
    """How a check actually meets this: `ask` is called once per request, and the
    budget is read on entry — so the request that finds it spent is never issued."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    answered: list[str] = []

    def request(name: str) -> str:
        clock.advance(6.0)
        answered.append(name)
        return name

    assert ask(lambda: request("first"), deadline=deadline) == "first"
    assert ask(lambda: request("second"), deadline=deadline) == "second"
    with pytest.raises(DeadlineExceeded):
        ask(lambda: request("third"), deadline=deadline)
    assert answered == ["first", "second"]


def test_a_retry_sequence_out_of_time_reports_the_service_not_the_clock() -> None:
    """Pinned deliberately, because the first draft of this test assumed the
    opposite. Inside a retry sequence the backoff veto fires *before* the loop can
    re-read the budget — `affords` is what notices there is no time left — so the
    caller gets the transient `RemoteError` the service raised. That is the better
    report: the service is what went wrong, and the run-level fact belongs to the
    next request, which `DeadlineExceeded` refuses on entry.
    """
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        clock.advance(6.0)      # each attempt eats most of the run
        raise RemoteError("slow and sad", status=500, fault=Fault.TRANSIENT)

    with pytest.raises(RemoteError) as raised:
        ask(operation, deadline=deadline, retries=5, sleep=_Sleep(clock))
    assert not isinstance(raised.value, DeadlineExceeded)
    assert raised.value.status == 500
    assert len(calls) == 2      # 6s, sleep 1s, 6s — and then no time to try again


def test_deadline_exceeded_escapes_a_per_item_except_remote_error() -> None:
    """The sentence: a check that turns its own error into a line per repository
    must not turn one run-level fact into forty item-level ones."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(11.0)

    def aspect() -> str:
        try:
            return ask(lambda: "unreachable", deadline=deadline)
        except RemoteError as error:      # the per-item handler
            return f"line: {error}"

    with pytest.raises(DeadlineExceeded):
        aspect()
    assert not issubclass(DeadlineExceeded, RemoteError)


# --- RemoteError: the classification cannot be forgotten ----------------------


def test_a_remote_error_without_a_fault_is_a_type_error() -> None:
    """`fault` has no default on purpose: a default is the decision this module
    exists to make consistent, taken by whoever forgot to pass it."""
    with pytest.raises(TypeError):
        RemoteError("boom")  # type: ignore[call-arg]


# --- a service that says "not now" --------------------------------------------


def test_ask_spends_the_wait_the_service_asked_for_instead_of_its_own() -> None:
    """A throttle is `TRANSIENT` — asking again could change the answer — and the only
    new thing is the number. Pressing a service that has just said *not yet* is how an
    integration gets itself blocked, so the service's number wins over our backoff."""
    clock = _Clock()
    deadline = Deadline(60.0, clock=clock)
    sleep = _Sleep(clock)
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        raise RemoteError("slow down", status=429, fault=Fault.TRANSIENT,
                          retry_after=7.0)

    with pytest.raises(RemoteError):
        ask(operation, deadline=deadline, sleep=sleep)
    assert sleep.waits == [7.0]          # not the 1.0s default
    assert len(calls) == 2


def test_ask_falls_back_to_its_own_backoff_when_no_wait_was_named() -> None:
    """The counterpart, so a version that always used `retry_after` would not pass
    both: an error with no number gets the backoff it always got."""
    sleep = _Sleep()
    with pytest.raises(RemoteError):
        ask(_failing(Fault.TRANSIENT, status=503),  # type: ignore[arg-type]
            sleep=sleep)
    assert sleep.waits == [1.0]


def test_a_named_wait_the_budget_cannot_afford_is_refused() -> None:
    """The line the request layer does not cross: a wait outliving the budget the
    check granted is not this function's to take. The service's own error is raised,
    and **nothing is slept** — what the check then does is the check's business."""
    clock = _Clock()
    deadline = Deadline(30.0, clock=clock)
    sleep = _Sleep(clock)
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        raise RemoteError("come back in ten minutes", status=403,
                          fault=Fault.TRANSIENT, retry_after=600.0)

    with pytest.raises(RemoteError) as raised:
        ask(operation, deadline=deadline, sleep=sleep)
    assert raised.value.status == 403
    assert not isinstance(raised.value, DeadlineExceeded)
    assert sleep.waits == []
    assert len(calls) == 1


def test_a_named_wait_of_zero_is_honored_as_no_wait_at_all() -> None:
    """`0.0` is falsy, which is why the code asks `is not None` — a service saying
    *you may retry now* must not silently fall back to our backoff."""
    clock = _Clock()
    sleep = _Sleep(clock)
    calls: list[int] = []

    def operation() -> str:
        calls.append(1)
        raise RemoteError("now is fine", status=429, fault=Fault.TRANSIENT,
                          retry_after=0.0)

    with pytest.raises(RemoteError):
        ask(operation, deadline=Deadline(60.0, clock=clock), sleep=sleep)
    assert sleep.waits == [0.0]
    assert len(calls) == 2


def test_a_named_wait_does_not_make_an_answered_fault_retryable() -> None:
    """The number is not a licence: `retry_after` on something that is not
    `TRANSIENT` changes nothing, because the fault is what decides."""
    calls: list[int] = []
    sleep = _Sleep()

    def operation() -> str:
        calls.append(1)
        raise RemoteError("not for you", status=403, fault=Fault.ANSWERED,
                          retry_after=5.0)

    with pytest.raises(RemoteError):
        ask(operation, sleep=sleep)
    assert len(calls) == 1
    assert sleep.waits == []


def test_a_remote_error_names_no_wait_unless_a_caller_sets_one() -> None:
    """Defaulted, so every existing subclass and call site is untouched — and setting
    it is the caller's job, because no status identifies a throttle."""
    assert RemoteError("boom", fault=Fault.TRANSIENT).retry_after is None
    assert RemoteError("slow down", status=429, fault=Fault.TRANSIENT,
                       retry_after=30.0).retry_after == 30.0


def test_a_remote_error_carries_its_status_and_fault() -> None:
    error = RemoteError("HTTP 503 for /repos", status=503, fault=Fault.TRANSIENT)
    assert str(error) == "HTTP 503 for /repos"
    assert error.status == 503
    assert error.fault is Fault.TRANSIENT


def test_a_malformed_payload_has_no_status_and_is_not_transient() -> None:
    """The case a boolean could not hold: no status, like a transport failure, but
    not retryable, like a 404 — and a different report from either."""
    error = RemoteError("expected a list", fault=Fault.MALFORMED)
    assert error.status is None
    assert error.fault is not Fault.TRANSIENT
    assert error.fault is not Fault.ANSWERED


def test_the_three_faults_are_distinct_members() -> None:
    assert len({Fault.TRANSIENT, Fault.ANSWERED, Fault.MALFORMED}) == 3


# --- the module's own promise about itself ------------------------------------


def test_transport_imports_nothing_from_little_sister() -> None:
    """Its docstring says so, and the reason is a real one: importing `checks`
    registers every built-in check type as a side effect, and this module is used by
    a built-in check, by the link prober and by installed packages."""
    import little_sister.transport as module

    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    offenders = [name for name in imported if name.startswith("little_sister")]
    assert not offenders, (
        f"little_sister.transport imports {', '.join(offenders)} — it is used by "
        f"modules that must not pull the checks package in as a side effect.")
