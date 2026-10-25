"""One request, and the five HTTP questions this project had answered four ways.

No test here touches the network. Each case patches the **opener** — the one object
that owns a socket — which keeps the seam at the boundary the module is about: what is
built, what policy is applied, and what comes back out.

Every test is one sentence from `fetch`'s docstring or from ADR-0058's record, tested
with the values the sentence is about.
"""
from __future__ import annotations

import contextlib
import http.client
import io
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from email.message import Message
from typing import Any
from unittest import mock

import pytest

from little_sister.fetch import (
    DEFAULT_MAX_BYTES,
    USER_AGENT,
    Response,
    fault_for,
    fetch,
    retry_after,
)
from little_sister.transport import Deadline, DeadlineExceeded, Fault, RemoteError

URL = "https://service.example.org/things"
PROXY = "http://proxy.example.org:3128"


class _Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Answer:
    """What an opener hands back: a status, headers and a readable body."""

    def __init__(self, status: int = 200, body: bytes = b"",
                 headers: dict[str, str] | None = None,
                 url: str = URL) -> None:
        self.status = status
        self.url = url
        self.headers = Message()
        for name, value in (headers or {}).items():
            self.headers[name] = value
        self._stream = io.BytesIO(body)

    def read1(self, size: int = -1) -> bytes:
        """What `_read` calls. `io.BytesIO` has it and it behaves the same there;
        naming it here rather than `read` is what keeps this double honest about the
        method under test."""
        return self._stream.read1(size)

    def read(self, size: int = -1) -> bytes:
        """Not used by `_read` any more. Kept because `_answered` closes an error
        stream through the file protocol, and a double that dropped it would fail for
        a reason unrelated to what a test is asking."""
        return self._stream.read(size)

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *_: object) -> None:
        self._stream.close()


class _Opener:
    """A stand-in opener that records the request it was given."""

    def __init__(self, answer: Any = None, raises: BaseException | None = None,
                 body_stream: Any = None) -> None:
        self.answer = answer if answer is not None else _Answer()
        self.raises = raises
        self.body_stream = body_stream
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def open(self, request: urllib.request.Request,
             timeout: float | None = None) -> Any:
        self.requests.append(request)
        self.timeouts.append(timeout if timeout is not None else -1.0)
        if self.raises is not None:
            raise self.raises
        if self.body_stream is not None:
            self.answer._stream = self.body_stream
        return self.answer


def _fetch(opener: _Opener, **kwargs: Any) -> Response:
    """Run `fetch` against a stand-in opener, defaulting the required arguments."""
    following = kwargs.pop("follow_redirects", True)
    target = "_FOLLOWING" if following else "_REPORTING"
    with mock.patch(f"little_sister.fetch.{target}", opener):
        return fetch(URL, timeout=kwargs.pop("timeout", 10.0),
                     follow_redirects=following, **kwargs)


# --- a status is an answer, not an exception ----------------------------------


def test_a_success_comes_back_as_a_response() -> None:
    opener = _Opener(_Answer(status=204, body=b"", headers={"Link": "<next>"}))
    response = _fetch(opener, read_body=False)
    assert response.status == 204
    assert response.headers.get("link") == "<next>"    # case-insensitive, urllib's own


@pytest.mark.parametrize("status", [301, 404, 429, 500, 503])
def test_every_status_comes_back_as_a_response_and_never_raises(status: int) -> None:
    """The inversion this module exists for: urllib raises a status it dislikes, and
    for a check the status *is* the reading."""
    error = urllib.error.HTTPError(URL, status, "no", Message(), None)
    response = _fetch(_Opener(raises=error))
    assert response.status == status
    assert response.body == b""       # no `fp`, so there was nothing to read


def test_an_error_status_still_carries_its_body() -> None:
    """A service that explains itself in the body of a 422 is worth quoting."""
    error = urllib.error.HTTPError(
        URL, 422, "no", Message(), io.BytesIO(b'{"message":"bad field"}'))
    response = _fetch(_Opener(raises=error))
    assert response.status == 422
    assert "bad field" in response.text()


def test_the_body_is_decoded_replacing_what_it_cannot_read() -> None:
    """A check must not fail because a service mislabeled its own error page."""
    response = _fetch(_Opener(_Answer(body=b"caf\xff")))
    assert response.text() == "caf�"


# --- only a failure with no status raises ------------------------------------


@pytest.mark.parametrize("reason", [
    urllib.error.URLError(socket.gaierror("nodename nor servname")),
    urllib.error.URLError(ConnectionRefusedError()),
    urllib.error.URLError(TimeoutError()),
    http.client.BadStatusLine("this is not http"),
    http.client.InvalidURL("nonnumeric port"),
    ValueError("unknown url type"),
])
def test_a_request_that_never_reached_a_status_is_a_transient_remote_error(
        reason: BaseException) -> None:
    """The exception set that cost an incident: `BadStatusLine` and `InvalidURL` are
    neither `OSError` nor `ValueError`, and urllib re-raises them unwrapped."""
    with pytest.raises(RemoteError) as raised:
        _fetch(_Opener(raises=reason))
    assert raised.value.fault is Fault.TRANSIENT
    assert raised.value.status is None


def test_the_originating_exception_is_attached_as_the_cause() -> None:
    """The channel a caller reads to word a failure in its own vocabulary, instead of
    showing a reader the proxy paths and certificate directories urllib names."""
    reason = urllib.error.URLError(socket.gaierror("nodename nor servname"))
    with pytest.raises(RemoteError) as raised:
        _fetch(_Opener(raises=reason))
    assert raised.value.__cause__ is reason


# --- the request that gets built ----------------------------------------------


def test_both_openers_say_who_is_knocking() -> None:
    """`Python-urllib` is the string a corporate filter is most likely to answer with
    a 403 nobody can interpret, so no request this library makes sends it."""
    from little_sister.fetch import _FOLLOWING, _REPORTING

    for opener in (_FOLLOWING, _REPORTING):
        assert opener.addheaders == [("User-Agent", USER_AGENT)]
    assert USER_AGENT.startswith("little-sister/")
    assert "urllib" not in USER_AGENT


def test_a_caller_may_say_which_subsystem_is_knocking() -> None:
    """A caller-supplied header reaches the request, and urllib only fills in the
    opener's defaults for names the request does not already carry — which is how a
    caller keeps a suffix of its own."""
    opener = _Opener()
    _fetch(opener, headers={"User-Agent": f"{USER_AGENT} (sweep)"})
    assert opener.requests[0].get_header("User-agent") == f"{USER_AGENT} (sweep)"


def test_a_caller_supplied_header_reaches_the_request() -> None:
    opener = _Opener()
    _fetch(opener, headers={"Authorization": "Bearer x", "Accept": "application/json"})
    request = opener.requests[0]
    assert request.get_header("Authorization") == "Bearer x"
    assert request.get_header("Accept") == "application/json"


def test_the_method_and_body_reach_the_request() -> None:
    opener = _Opener()
    _fetch(opener, method="POST", data=b'{"query":"{ x }"}')
    request = opener.requests[0]
    assert request.get_method() == "POST"
    assert request.data == b'{"query":"{ x }"}'


def test_following_redirects_and_reporting_them_are_different_openers() -> None:
    """The one policy with no default: both are right somewhere, so neither is
    assumed. An `http` check told not to follow needs a 301 to *stay* a 301; one
    told to follow needs the answer at the end of the chain."""
    from little_sister.fetch import _FOLLOWING, _REPORTING

    assert _FOLLOWING is not _REPORTING
    followers = [type(h).__name__ for h in _FOLLOWING.handlers]
    reporters = [type(h).__name__ for h in _REPORTING.handlers]
    assert "_KeepRedirects" in reporters
    assert "_KeepRedirects" not in followers


@pytest.mark.parametrize("following", [True, False])
def test_an_outbound_proxy_from_the_environment_is_honored(following: bool) -> None:
    """A deployment behind an outbound proxy already sets `https_proxy`, and the opener
    is a default one apart from the redirect policy, which is what picks that up.

    **Asserted with a proxy in the environment on purpose.** urllib installs a
    `ProxyHandler` only for the schemes it actually found — `ProxyHandler({})` gains no
    `*_open` methods and is never added to `handlers` — so asserting the handler's
    presence against the ambient environment asserts nothing on a machine without a
    proxy, and quietly *passes* on one with a proxy set. Set the variable, then ask.
    """
    from little_sister.fetch import _build

    with mock.patch.dict(os.environ, {"https_proxy": PROXY}, clear=True):
        opener = _build(follow_redirects=following)
    proxies = [handler.proxies for handler in opener.handlers
               if isinstance(handler, urllib.request.ProxyHandler)]
    assert proxies, "the proxy handler was stripped, so `https_proxy` is ignored"
    assert proxies[0].get("https") == PROXY


def test_redirect_following_is_refused_by_returning_no_new_request() -> None:
    """urllib follows a redirect by building the next request; returning `None` is how
    a handler says *report it instead*."""
    from little_sister.fetch import _KeepRedirects

    handler = _KeepRedirects()
    assert handler.redirect_request(
        urllib.request.Request(URL), io.BytesIO(b""), 301, "moved", Message(),
        "https://elsewhere.example.org/") is None


# --- the deadline -------------------------------------------------------------


def test_the_socket_timeout_is_clamped_to_what_the_run_has_left() -> None:
    """The clamp, at the boundary that spends it: without this the deadline is a
    suggestion, because urllib is handed the request's own timeout."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(8.0)
    opener = _Opener()
    _fetch(opener, timeout=15.0, deadline=deadline)
    assert opener.timeouts == [pytest.approx(2.0)]


def test_a_request_is_not_issued_on_a_spent_budget() -> None:
    """`budget()` would be 0.0, which most socket APIs read as *non-blocking* — the
    request would fail and the service would be blamed for the clock."""
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)
    clock.advance(11.0)
    opener = _Opener()
    with pytest.raises(DeadlineExceeded):
        _fetch(opener, deadline=deadline)
    assert opener.requests == []


def test_a_dribbling_body_is_cut_off_by_the_run_clock() -> None:
    """The hole `urlopen(timeout=…)` leaves open: its bound is one socket operation,
    so a server sending one byte at a time never times out. The clock is read between
    chunks, which is where this is caught.

    **The double models both methods the way a socket does**, and the earlier version
    of it did not — it answered `read` with one byte immediately, so the loop turned
    freely and the test proved only that the clock was consulted, never that it was
    consulted in time. A real `read(n)` blocks until it has *n* bytes; that difference
    is the whole of the defect this now pins, and
    `test_a_real_dribbling_socket_is_cut_off_at_the_budget` measures it for real.
    """
    clock = _Clock()
    deadline = Deadline(10.0, clock=clock)

    class Dribble:
        """One byte every three seconds, with `read` and `read1` telling the truth
        about themselves."""

        def read1(self, size: int = -1) -> bytes:
            clock.advance(3.0)                  # what has arrived: one byte
            return b"x"

        def read(self, size: int = -1) -> bytes:  # pragma: no cover - see below
            # A real `read` blocks for the full `size`, which at a byte every three
            # seconds is a little over two days. Spelled as the refusal it is, so that
            # a `_read` reverted to `read` fails loudly here instead of passing.
            raise AssertionError(
                "`_read` must use `read1`: a blocking `read` cannot be bounded")

        def close(self) -> None:
            pass

    with pytest.raises(DeadlineExceeded):
        _fetch(_Opener(body_stream=Dribble()), deadline=deadline)


def test_a_body_read_without_a_deadline_is_bounded_only_by_the_cap() -> None:
    """Stated because it is a limit of the design, not an oversight: the clock closes
    the dribble hole *when a deadline is given*."""
    stream = io.BytesIO(b"x" * 100)
    response = _fetch(_Opener(body_stream=stream), max_bytes=1000)
    assert len(response.body) == 100


# --- the size cap -------------------------------------------------------------


def test_a_body_over_the_cap_is_malformed_not_transient() -> None:
    """It arrived; it cannot be used. Asking again returns the same too-large answer,
    which is exactly what `MALFORMED` means and `TRANSIENT` does not."""
    with pytest.raises(RemoteError) as raised:
        _fetch(_Opener(body_stream=io.BytesIO(b"x" * 5000)), max_bytes=1000)
    assert raised.value.fault is Fault.MALFORMED
    assert raised.value.status is None


def test_a_body_at_the_cap_is_still_read() -> None:
    """The boundary belongs on the allowed side: the cap is what may be read, not
    what may not."""
    response = _fetch(_Opener(body_stream=io.BytesIO(b"x" * 1000)), max_bytes=1000)
    assert len(response.body) == 1000


def test_the_default_cap_is_large_enough_for_an_api_page_and_bounded() -> None:
    assert 1024 * 1024 <= DEFAULT_MAX_BYTES <= 64 * 1024 * 1024


class _Counting:
    """A body that records whether anybody actually pulled on it."""

    def __init__(self, body: bytes) -> None:
        self.reads = 0
        self._stream = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        self.reads += 1
        return self._stream.read(size)

    def close(self) -> None:
        self._stream.close()


def test_a_body_nobody_asked_for_is_not_read() -> None:
    """Two callers measure a status and stop; reading a page they ignore would be
    bandwidth spent on nothing, every cycle, forever."""
    stream = _Counting(b"x" * 5000)
    response = _fetch(_Opener(body_stream=stream), read_body=False)
    assert response.body == b""
    assert stream.reads == 0


# --- fault_for ----------------------------------------------------------------


@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_a_server_error_is_transient(status: int) -> None:
    assert fault_for(status) is Fault.TRANSIENT


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 429, 200, 301])
def test_anything_else_is_an_answer(status: int) -> None:
    """A 4xx *is* an answer, and asking again gets it faster."""
    assert fault_for(status) is Fault.ANSWERED


# --- retry_after: what a service asked for ------------------------------------


def _headers(**fields: str) -> Message:
    message = Message()
    for name, value in fields.items():
        message[name.replace("_", "-")] = value
    return message


def test_delta_seconds_is_read_as_seconds() -> None:
    """The common form, and the one every rate limiter sends."""
    assert retry_after(_headers(Retry_After="120")) == 120.0


def test_an_http_date_is_read_as_the_seconds_until_then() -> None:
    """The other form RFC 9110 allows. A caller should not have to care which a
    service picked, which is the whole reason this is not four lines at a call site."""
    now = datetime(2026, 10, 21, 7, 26, 0, tzinfo=UTC)
    header = _headers(Retry_After="Wed, 21 Oct 2026 07:28:00 GMT")
    assert retry_after(header, now=now) == pytest.approx(120.0)


def test_an_http_date_already_past_reads_as_no_wait_rather_than_a_negative() -> None:
    """*You may retry from then* where *then* has gone is *now*, and a negative wait
    is not a thing anybody can sleep for."""
    now = datetime(2026, 10, 21, 9, 0, 0, tzinfo=UTC)
    header = _headers(Retry_After="Wed, 21 Oct 2026 07:28:00 GMT")
    assert retry_after(header, now=now) == 0.0


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="no tzset on this platform")
def test_a_date_without_a_zone_is_read_as_gmt() -> None:
    """An HTTP-date is GMT by definition; a server that omits the zone has not
    invented a local one.

    **Asserted under a non-UTC local zone on purpose.** In a UTC container, reading a
    zoneless date as GMT and reading it as *local* give the same answer, so this test
    would pass while proving nothing — and a mutation that swapped the two went
    undetected until it was run this way. Under Berlin the mutated reading lands two
    hours early and the wait collapses to zero.
    """
    now = datetime(2026, 10, 21, 7, 26, 0, tzinfo=UTC)
    header = _headers(Retry_After="Wed, 21 Oct 2026 07:28:00")
    try:
        with mock.patch.dict(os.environ, {"TZ": "Europe/Berlin"}):
            time.tzset()
            assert retry_after(header, now=now) == pytest.approx(120.0)
    finally:
        time.tzset()          # back to whatever the real environment says


@pytest.mark.parametrize("value", ["", "   ", "soon", "-30", "12.5", "later please"])
def test_an_unreadable_value_is_no_wait_at_all(value: str) -> None:
    """A service sending nonsense here must not break a check that was only being
    polite about it. `-30` and `12.5` are not `delta-seconds`, which RFC 9110 defines
    as digits — and a negative wait is meaningless anyway."""
    assert retry_after(_headers(Retry_After=value)) is None


def test_a_missing_header_is_no_wait_at_all() -> None:
    assert retry_after(Message()) is None


def test_the_header_is_found_whatever_its_case() -> None:
    """urllib's own `Message` is case-insensitive, and a service picks its own
    spelling."""
    assert retry_after(_headers(retry_after="60")) == 60.0


def test_a_response_hands_its_headers_straight_to_the_parser() -> None:
    """How a caller actually meets this: the status says the request failed, and the
    headers say when to come back."""
    error = urllib.error.HTTPError(
        URL, 429, "slow down", _headers(Retry_After="45"), None)
    response = _fetch(_Opener(raises=error))
    assert response.status == 429
    assert fault_for(response.status) is Fault.ANSWERED   # by status alone: 429 is 4xx
    assert retry_after(response.headers) == 45.0          # ...and this is the dialect


def test_only_the_standard_header_is_read() -> None:
    """A vendor's own reset counter is a dialect, and reading a dialect belongs to the
    package that speaks it — not here, where it would be a guess."""
    header = _headers(X_RateLimit_Reset="1793577600", X_RateLimit_Remaining="0")
    assert retry_after(header) is None


def test_a_date_form_can_be_measured_against_the_servers_own_clock() -> None:
    """Passing the response's `Date` instead of ours is what a caller does when it
    would rather not trust two machines to agree."""
    served_at = datetime(2026, 10, 21, 7, 26, 0, tzinfo=UTC)
    header = _headers(Retry_After="Wed, 21 Oct 2026 07:28:00 GMT")
    assert retry_after(header, now=served_at) == pytest.approx(120.0)
    assert retry_after(header, now=served_at + timedelta(minutes=5)) == 0.0


# --- the one claim a double cannot settle -------------------------------------
#
# Everything above runs against stand-in openers, which is the right trade for
# 1,900 hermetic tests. It is the wrong trade for exactly one sentence: *the chunked
# read bounds a dribbling server*. That sentence was false for as long as `_read`
# called `read`, and the double said otherwise because it answered immediately where
# a socket blocks. So this one talks to a real socket on localhost.

class _Dribbler:
    """A one-shot HTTP server on localhost that trickles a body one byte at a time.

    It counts what it managed to send, which is what makes the assertion below
    independent of wall-clock luck: a bound that works hangs up early, so the count
    stays well under the whole body. A bound that does not work reads to the end,
    and the count is the whole body every time.
    """

    STEP = 0.02          # seconds between bytes
    SIZE = 250           # ...so the whole body takes ~5s

    def __init__(self) -> None:
        self._listener = socket.socket()
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.sent = 0
        self.url = f"http://127.0.0.1:{self._listener.getsockname()[1]}/"
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:                       # pragma: no cover - closed while idle
            return
        with conn:
            try:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n"
                             % self.SIZE)
                for _ in range(self.SIZE):
                    conn.sendall(b"x")
                    self.sent += 1
                    time.sleep(self.STEP)
            except OSError:                   # the reader hung up, which is the point
                pass

    def close(self) -> None:
        self._listener.close()


@contextlib.contextmanager
def _direct() -> Any:
    """`fetch`, with an opener that will not consult a proxy for this request.

    The shipped openers are built at import time from the environment's proxy
    settings, so a machine whose `no_proxy` does not cover the loopback address would
    send these requests to a proxy instead of to the server under test. Skipping on
    "any proxy is set" was the first attempt and was worse than useless: this
    container *does* set `https_proxy`, and its `no_proxy` *does* cover 127.0.0.1, so
    the skip disabled the one test that proves the claim in exactly the place the gate
    runs. Building the opener proxy-free instead makes the outcome the same everywhere,
    and costs nothing that matters here — what is under test is `_read`, not which
    handler stack got us a socket.
    """
    with mock.patch("little_sister.fetch._FOLLOWING",
                    urllib.request.build_opener(urllib.request.ProxyHandler({}))):
        yield


def test_a_real_dribbling_socket_is_cut_off_at_the_budget() -> None:
    """The measurement, against a real socket, with **no clock injected**.

    A body of 250 bytes at 20 ms each is about five seconds of trickle; the budget is a
    third of a second. The per-request timeout is generous on purpose — 30 seconds — so
    nothing here is the socket timeout doing the work: every individual read succeeds
    promptly, which is precisely the shape `urlopen(timeout=…)` cannot bound.

    Asserted on **how much the server got to send** rather than on elapsed time, so a
    slow machine cannot fail it: whatever the timings, a working bound hangs up long
    before the body is done. With `_read` calling `read` instead of `read1` the first
    read does not return until all 250 bytes have arrived, and this fails on the count.
    """
    server = _Dribbler()
    try:
        with _direct(), pytest.raises(DeadlineExceeded):
            fetch(server.url, timeout=30.0, follow_redirects=True,
                  deadline=Deadline(0.3))
        assert server.sent < _Dribbler.SIZE
    finally:
        server.close()


def test_a_real_socket_that_answers_promptly_is_read_whole() -> None:
    """The other side of the line, so the test above cannot pass by cutting off
    everything: the same real socket, answering at once, is read to the end and the
    deadline never fires."""
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    body = b"y" * 5000

    def serve() -> None:
        try:
            conn, _ = listener.accept()
        except OSError:                       # pragma: no cover - closed while idle
            return
        with conn:
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body))
            conn.sendall(body)

    threading.Thread(target=serve, daemon=True).start()
    try:
        with _direct():
            response = fetch(f"http://127.0.0.1:{listener.getsockname()[1]}/",
                             timeout=30.0, follow_redirects=True,
                             deadline=Deadline(10.0))
        assert response.body == body
    finally:
        listener.close()
