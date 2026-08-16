"""One HTTP request, with this project's policy applied to it.

:mod:`little_sister.transport` decides what a *failure* means; this module decides
what a *request* is — and it is the only place in the library that opens a socket to
a URL. Four call sites used to answer the same handful of HTTP questions differently,
so each of them is settled here, once:

* **Redirects are the caller's decision, and there is no default.** ``follow_redirects``
  is a required argument. Silently following is how a login wall answering ``200`` at
  the end of a chain reads as health; refusing to follow is how a ``301`` reads as
  *alive and moved*. Both are right somewhere, so neither is assumed.
* **One `User-Agent`.** ``little-sister/<version>``, because the default
  ``Python-urllib`` is exactly the string a corporate filter is most likely to answer
  with a ``403`` nobody can interpret. A caller may override it — the link prober adds
  which subsystem is knocking — and a caller-supplied header always wins.
* **Proxies and TLS trust are the environment's.** The opener is a default one
  otherwise, so ``http_proxy`` / ``https_proxy`` are honored, as is the system trust
  store (``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` for an internal CA). There is
  deliberately **no way to switch certificate verification off**: a monitoring tool
  that can be told to ignore a bad certificate eventually is.
* **A body is read in bounded chunks**, against a byte cap *and* the run's deadline.
  That is what closes the hole ``urlopen(timeout=…)`` leaves open — its bound is one
  socket operation, so a server dribbling a byte at a time never times out. The clock
  only bites when a ``deadline`` is given; without one, the cap is the only bound and
  that is worth knowing. See :func:`_read` for why it reads with ``read1``: with plain
  ``read`` this paragraph was false, and measurably so.

  **Two limits of it, stated rather than implied.** A caller passing
  ``read_body=False`` is not exposed to a slow body at all, because none is read — so
  a deadline buys such a caller nothing *here*. And the clock does not reach the
  **status line and headers**, which urllib reads inside ``opener.open`` before this
  module gets a stream: a server trickling those is bounded only by the socket timeout
  per read and by urllib's own header limits, which together are not a bound worth the
  name. Closing that would mean owning the header parse or running the request on a
  thread, and neither is taken on here.

* **A service that says *not now* is believed, but not obeyed blindly.**
  :func:`retry_after` reads the standard header; what to do with the number is the
  caller's, and `ask` will only spend it inside the budget the check granted.

**An HTTP status is an answer, not an exception.** :func:`fetch` returns a
:class:`Response` for *every* status, ``500`` included, and raises only when the
request never got one. This is the same rule the SSH connection follows — report
facts, leave verdicts to the check — and it is what lets the two callers whose
*measurement is the status* use this at all. A caller that wants the family's reading
of a status it considers a failure asks :func:`fault_for`.
"""
from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import IO, Any, Protocol

from little_sister import __version__
from little_sister.transport import Deadline, DeadlineExceeded, Fault, RemoteError

__all__ = ["Response", "fault_for", "fetch", "retry_after"]

#: Who is knocking. See the module docstring for why the default is not good enough.
USER_AGENT = f"little-sister/{__version__}"

#: How much of a response body will be read before it is treated as unusable. Large
#: enough for a paginated API answer, small enough that one confused endpoint cannot
#: spend the process's memory: a check runs unattended, on a schedule, forever.
DEFAULT_MAX_BYTES = 16 * 1024 * 1024

#: One socket read at a time, so the deadline below is checked often enough to matter
#: without turning a large body into a million loop iterations.
_CHUNK = 64 * 1024

#: Everything one request may fail with before it has an HTTP status, so a caller
#: catches *one* class instead of guessing. ``URLError`` is an ``OSError``, and so are
#: the transport failures underneath it; ``ValueError`` is what a URL urllib cannot
#: open at all raises. ``http.client.HTTPException`` is the one that is **neither** —
#: ``urlopen`` re-raises ``BadStatusLine`` and ``InvalidURL`` unwrapped out of
#: ``getresponse()``, so a server answering garbage (an SSH port named as
#: ``http://host:22/``, a typo'd port) once escaped a whole link-probe sweep and left
#: every remaining target without an answer.
_TRANSPORT_FAILURES = (OSError, ValueError, http.client.HTTPException)


class _Chunked(Protocol):
    """What :func:`_read` needs of a body stream, which is ``read1`` and nothing else.

    Spelled as a protocol because ``typing.IO`` does not declare ``read1`` — it is
    :class:`io.BufferedIOBase`'s, and both objects this module reads from have it:
    ``http.client.HTTPResponse`` on the success path and ``HTTPError`` on the answered
    one. Naming the one method narrowly is also a note to whoever writes the next test
    double: modelling ``read`` is modelling the version of this that could not be
    bounded, which is the mistake that hid the defect ``read1`` fixes (ADR-0058, amended
    2026-08-16). Nothing mechanical enforces that — ``mypy`` runs over ``src`` only — so
    it is said here, where a double's author is most likely to look.
    """

    def read1(self, size: int = ..., /) -> bytes: ...


@dataclass(frozen=True)
class Response:
    """What came back, whatever it was.

    :attr:`status` is the HTTP status — a fact, not a verdict, and present for a
    ``500`` exactly as for a ``200``. :attr:`url` is the URL the answer came from,
    which differs from the one asked for when a redirect was followed.
    :attr:`headers` is urllib's own :class:`~email.message.Message`, so a lookup is
    case-insensitive (``headers.get("Link", "")``). :attr:`body` is empty when the
    caller asked not to read one.
    """

    status: int
    url: str
    headers: Message
    body: bytes

    def text(self, encoding: str = "utf-8") -> str:
        """The body as text, replacing anything undecodable rather than raising.

        A check reporting on a service does not get to fail because that service's
        error page was mislabeled; whatever came back is what the reason line should
        be able to quote.
        """
        return self.body.decode(encoding, "replace")


def fault_for(status: int) -> Fault:
    """This family's reading of a status the caller considers a failure.

    A **5xx** is `Fault.TRANSIENT` — the service failed to answer, and asking again
    could change that. Anything else is `Fault.ANSWERED`: a ``4xx`` *is* an answer
    (absent, or not visible to this credential) and asking again gets it faster.

    Deliberately by status and never by message text. `Fault.MALFORMED` is not
    reachable from a status at all — it is what a caller raises when the answer
    arrived and could not be used.
    """
    return Fault.TRANSIENT if 500 <= status < 600 else Fault.ANSWERED


def retry_after(headers: Message, *, now: datetime | None = None) -> float | None:
    """Seconds the service asked us to wait, from the standard ``Retry-After`` header.

    ``None`` when the header is absent or unreadable — a service that sends nonsense
    here must not be able to break a check that was only being polite about it.

    Both forms RFC 9110 allows are accepted, because a service picks one and the
    caller should not have to care: **delta-seconds** (``Retry-After: 120``) and an
    **HTTP-date** (``Retry-After: Wed, 21 Oct 2026 07:28:00 GMT``). A date already in
    the past yields ``0.0`` rather than a negative number — the honest reading of
    *you may retry from then* is *now*. Note that ``0.0`` is falsy, so a caller tests
    ``is not None`` rather than truthiness, which is what
    :class:`~little_sister.transport.RemoteError` and
    :func:`~little_sister.transport.ask` do.

    ``now`` is the instant a date form is measured against, defaulting to this
    machine's. Pass the response's own ``Date`` header instead when you would rather
    not trust the two clocks to agree — the difference is what a skewed server costs.

    This reads **only** the standard header. A service that expresses the same thing
    its own way — a reset timestamp, a vendor-specific counter — is speaking a dialect,
    and reading a dialect belongs to the package that speaks it.
    """
    raw = headers.get("Retry-After")
    if not isinstance(raw, str) or not raw.strip():
        return None
    value = raw.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:                       # an HTTP-date is GMT by definition
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


class _KeepRedirects(urllib.request.HTTPRedirectHandler):
    """A handler that reports a redirect instead of following it."""

    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes],
                         code: int, msg: str, headers: Message,
                         newurl: str) -> urllib.request.Request | None:
        return None


def _build(follow_redirects: bool) -> urllib.request.OpenerDirector:
    """One opener per redirect policy, built once. Default handlers otherwise, which
    is what honors the outbound proxy a deployment already configures."""
    opener = (urllib.request.build_opener() if follow_redirects
              else urllib.request.build_opener(_KeepRedirects))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


_FOLLOWING = _build(follow_redirects=True)
_REPORTING = _build(follow_redirects=False)


def _read(stream: _Chunked, *, max_bytes: int,
          deadline: Deadline | None) -> bytes:
    """A body, in chunks, bounded by ``max_bytes`` and by the run's clock.

    The deadline is read **between** chunks, so a server sending one byte at a time is
    cut off at the budget rather than at whatever length it chooses — the hole
    ``urlopen(timeout=…)`` leaves open, whose bound is one socket operation.

    **It reads with ``read1``, and that is what makes the sentence above true rather
    than merely well-intentioned.** ``read(n)`` blocks until it has all *n* bytes or
    reaches the end, so against a trickle the first call does not return until the
    whole body has arrived — and the clock is then consulted once, after the overrun it
    was there to prevent. Measured against a real socket dribbling one byte every
    200 ms, a 1.5-second budget raised `DeadlineExceeded` after **7.8 seconds**.
    ``read1(n)`` hands back what has actually arrived, so the loop turns often enough
    for the budget to mean something; the same measurement stops at 1.6 seconds. The
    chunk size is unchanged — with ``read1`` it is a ceiling on one read rather than a
    target, so a fast large body still costs one iteration per 64 KiB.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        if deadline is not None and deadline.expired():
            raise DeadlineExceeded(
                f"the run's budget of {deadline.seconds:g}s ran out after "
                f"{deadline.elapsed():.1f}s, reading a response body")
        chunk = stream.read1(_CHUNK)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise RemoteError(
                f"response body exceeded {max_bytes} bytes",
                fault=Fault.MALFORMED)
        chunks.append(chunk)


def fetch(url: str, *, timeout: float, follow_redirects: bool,
          method: str = "GET", data: bytes | None = None,
          headers: Mapping[str, str] | None = None,
          deadline: Deadline | None = None, read_body: bool = True,
          max_bytes: int = DEFAULT_MAX_BYTES) -> Response:
    """Make one request and return what came back, whatever its status.

    ``timeout`` and ``follow_redirects`` are required. A request with no timeout is
    the defect this family keeps rediscovering, and a redirect policy assumed rather
    than chosen is the one above it.

    ``deadline``, when given, does two things: it **clamps** ``timeout`` to what the
    run has left (:meth:`~little_sister.transport.Deadline.budget`), and it bounds the
    body read. A caller with a spent budget gets `DeadlineExceeded` rather than a
    request issued with a non-blocking socket.

    A failure that never reached a status raises: `RemoteError` with
    `Fault.TRANSIENT`, and **the originating exception attached as ``__cause__``** —
    which is what a caller that words a failure in its own vocabulary reads, rather
    than showing a user the proxy paths and certificate directories urllib's messages
    carry. A body over ``max_bytes`` is `Fault.MALFORMED`: it arrived, and it cannot
    be used.

    :raises RemoteError: the request never got an answer, or the answer was too big.
    :raises DeadlineExceeded: the run's budget was already spent, or ran out mid-body.
    """
    if deadline is not None and deadline.expired():
        raise DeadlineExceeded(
            f"the run's budget of {deadline.seconds:g}s ran out after "
            f"{deadline.elapsed():.1f}s, before {method} {url}")
    budget = deadline.budget(timeout) if deadline is not None else timeout
    request = urllib.request.Request(url, data=data, method=method)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    opener = _FOLLOWING if follow_redirects else _REPORTING
    try:
        # The URL is operator-configured (trusted), the standing assumption every
        # check in this project works under.
        with opener.open(request, timeout=budget) as answer:
            body = (_read(answer, max_bytes=max_bytes, deadline=deadline)
                    if read_body else b"")
            return Response(status=int(answer.status), url=str(answer.url),
                            headers=answer.headers, body=body)
    except urllib.error.HTTPError as error:
        # **The inversion this module exists for.** urllib raises a status it
        # dislikes; for a check the status is the reading. Note this clause must stay
        # above the next one: `HTTPError` is a `URLError` is an `OSError`.
        return _answered(error, url, read_body=read_body, max_bytes=max_bytes,
                         deadline=deadline)
    except _TRANSPORT_FAILURES as error:
        raise RemoteError(f"request failed for {method} {url}: {error}",
                          fault=Fault.TRANSIENT) from error


def _answered(error: urllib.error.HTTPError, url: str, *, read_body: bool,
              max_bytes: int, deadline: Deadline | None) -> Response:
    """An error status, as the answer it is.

    ``HTTPError`` is only file-like when urllib gave it a body to carry, so
    everything read off it is guarded on that — an error raised with no ``fp`` (a
    handler's own, or a test's) still has a status, and the status is the point.
    """
    body = b""
    if read_body and error.fp is not None:
        try:
            body = _read(error, max_bytes=max_bytes, deadline=deadline)
        finally:
            error.close()
    final: Any = getattr(error, "url", None)
    carried: Any = getattr(error, "headers", None)
    return Response(status=int(error.code), url=str(final or url),
                    headers=carried if isinstance(carried, Message) else Message(),
                    body=body)
