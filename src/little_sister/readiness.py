"""Whether this instance has finished coming up, and what it can see (ADR-0073).

``/health`` answers *is this process serving* and deliberately nothing else
(ADR-0066). This module answers the other half — *has this instance finished
coming up* — and holds, beside it, the two lines the instance says about its own
ability to observe anything at all.

Three rules carry the design:

* **Readiness is a startup question, and the answer latches.** Every condition
  below is true or false from the moment the process starts; once all three hold,
  this instance is ready for the life of the process and no later failure takes it
  back. That is what keeps ``/ready`` from being a second, sharper ``/health``: a
  route that could withdraw a serving instance would remove the very dashboard
  whose banner explains what broke, which is the whole argument of ADR-0066, and
  a latch cannot.
* **What it publishes is a closed vocabulary.** ``/ready`` has no login gate, so
  everything it says is said to whoever can reach the port. The three words in
  :data:`WAITING_FOR` name none of this deployment's paths, counts, versions or
  configuration; they are the difference between *wait* and *roll back*, which is
  the one thing the caller of an unready instance cannot work out for itself.
* **The lines are recorded state, read** (ADR-0072). The trust store is measured
  **once**, at startup, and the check outcomes are the engine's own record read on
  the tick. Nothing here opens a socket or stats a file to answer.
"""
from __future__ import annotations

import os
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass

from little_sister.codes import StatusCode
from little_sister.logger import logger
from little_sister.reasons import Entry

#: No identity door is registered, so nobody can sign in to this instance.
DOORS = "doors"
#: The machine's trust store holds no CA certificates, so nothing this instance
#: connects to over TLS can be verified.
TRUST = "trust"
#: The engine has not yet run every configured check once.
FIRST_PASS = "first-pass"

#: Everything ``/ready`` may say it is waiting for — a **closed vocabulary**, and
#: that is the point rather than a tidiness (ADR-0073), exactly as
#: ``ENGINE_STATES`` is for ``/health``. In this order, which is the order the
#: conditions are asked in and the order a reader will see them.
WAITING_FOR = (DOORS, TRUST, FIRST_PASS)

#: The two values of ``status``. A ready answer carries no ``waiting_for`` at all
#: rather than an empty list: absent and empty would be the same fact said two
#: ways, and one of them would invite a caller to test the wrong thing.
READY = "ready"
NOT_READY = "not ready"


@dataclass(frozen=True)
class TrustStore:
    """Whether the default TLS verification paths held a usable trust source
    when they were measured.

    ``usable`` is ``None`` where the measurement itself failed, which is **not**
    the same fact as an empty store and is never reported as one: an instance
    whose trust store could not be measured is not thereby known to be unable to
    verify anything, and refusing readiness over what we could not measure would
    be a guess with a load balancer behind it.
    """

    usable: bool | None

    @property
    def empty(self) -> bool:
        """Whether the machine is known to hold no usable trust source at all."""
        return self.usable is False


#: A certificate in an OpenSSL hash directory: eight hex digits of the subject
#: hash, a dot and a sequence number — ``4042bcee.0``. A CRL sits beside it as
#: ``4042bcee.r0`` and anchors nothing.
_HASHED_ENTRY = re.compile(r"[0-9a-f]{8}\.[0-9]+")


def measure_trust_store() -> TrustStore:
    """Whether the default TLS verification paths hold a usable trust source —
    asked **once**, at startup, because this is the one thing here that touches
    the machine.

    Asked of the paths, never of a context. ``cert_store_stats()`` counts what a
    context has **loaded**, and OpenSSL never loads a hash directory — a
    ``capath`` is consulted by subject hash when a chain is verified — so a
    populated ``/etc/ssl/certs`` beside a ``cafile`` the distribution does not
    create counted zero on an instance that verified every connection, and the
    latch kept it there (ADR-0073). A source is usable when OpenSSL
    would read something from it: a ``cafile`` that exists and is not empty, or
    a ``capath`` holding at least one hashed entry that resolves to a file.

    A container built without its distribution's CA certificates has neither,
    and then every TLS connection this instance makes fails to verify — every
    ``http`` check, and an identity provider's discovery document besides. Each
    failure looks like its own subject being unreachable, and nothing says the
    cause is local. This is the measurement that lets it be said once, in one
    line, about the instance.
    """
    try:
        paths = ssl.get_default_verify_paths()
        return TrustStore(_usable_file(paths.cafile)
                          or _usable_directory(paths.capath))
    except Exception:
        logger.exception("readiness: the trust store could not be measured")
        return TrustStore(None)


def _usable_file(cafile: str | None) -> bool:
    """Present — ``get_default_verify_paths()`` answers ``None`` otherwise — and
    not empty."""
    return cafile is not None and os.path.getsize(cafile) > 0


def _usable_directory(capath: str | None) -> bool:
    """Holding at least one hashed entry OpenSSL could open — a link ``c_rehash``
    left dangling is a name, not a certificate."""
    if capath is None:
        return False
    with os.scandir(capath) as entries:
        return any(_HASHED_ENTRY.fullmatch(entry.name) is not None
                   and entry.is_file() for entry in entries)


@dataclass(frozen=True)
class Outcomes:
    """What the engine's checks have done so far, as its schedule records it.

    ``configured`` is every check this engine runs, ``completed`` those that have
    stored a result at least once — a secret-pinned check included, since it
    stores its ``ERROR`` without ever calling ``run()`` — and ``erroring`` those
    whose **last** stored result was an ``ERROR``.
    """

    configured: int
    completed: int
    erroring: int

    @property
    def first_pass(self) -> bool:
        """Whether every configured check has stored a result.

        A configuration holding no checks has completed its (empty) first pass and
        is ready: the heartbeat already carries a ``WARN`` saying nothing is
        watched (ADR-0005), and keeping traffic away as well would answer a
        configuration mistake by hiding the page that describes it.
        """
        return self.completed >= self.configured

    @property
    def all_erroring(self) -> bool:
        """Whether every check this instance runs last stored an ``ERROR``.

        The counts satisfy ``erroring <= completed <= configured`` — a check is
        counted as erroring only once it has stored something — so
        ``erroring == configured`` already says the first pass finished, and a
        second guard for it would be a condition that cannot be false. What is a
        real guard is the **more than one**: with a single check, *every check is
        erroring* says nothing its own node does not already say, and a line that
        adds nothing is a line somebody learns to skip.
        """
        return self.configured > 1 and self.erroring == self.configured


@dataclass(frozen=True)
class Answer:
    """What ``/ready`` says: ready, or the words it is waiting for."""

    ready: bool
    waiting_for: tuple[str, ...] = ()


class Readiness:
    """This instance's readiness, latched, and the lines beside it.

    Each condition is a callable rather than a value, because two of the three are
    only settled after the application has finished importing — an engine starts
    at the end of that import, and a door is registered before it — and because a
    test can then hold each one still on its own.

    The latch is a plain flag with no lock around it: two threads that arrive at
    the moment the last condition turns true both compute the same answer and both
    set the same flag, which is why the race is not worth the contention on a route
    a load balancer calls every few seconds.
    """

    def __init__(self, *, doors: Callable[[], bool],
                 trust: Callable[[], TrustStore],
                 first_pass: Callable[[], bool],
                 outcomes: Callable[[], Outcomes | None]) -> None:
        self._doors = doors
        self._trust = trust
        self._first_pass = first_pass
        self._outcomes = outcomes
        self._latched = False

    def answer(self) -> Answer:
        """Ready, or the vocabulary words this instance is still waiting for.

        Once ready, always ready — the conditions are not asked again, so an
        instance that has come up is never withdrawn by this route.
        """
        if self._latched:
            return Answer(True)
        waiting = []
        if not self._doors():
            waiting.append(DOORS)
        if self._trust().empty:
            waiting.append(TRUST)
        if not self._first_pass():
            waiting.append(FIRST_PASS)
        if waiting:
            return Answer(False, tuple(waiting))
        self._latched = True
        return Answer(True)

    def lines(self) -> tuple[Entry, ...]:
        """The two lines this instance says about what it can see (ADR-0073).

        Both are read from what is already recorded, and both **clear** when their
        condition does, like every line on the seam. Neither is the readiness
        answer: an instance that never becomes ready says so at ``/ready``, and
        the reasons it did not are a startup log and the ``/system`` page, where a
        reader has said who they are.
        """
        lines: list[Entry] = []
        if self._trust().empty:
            lines.append(Entry(
                "trust",
                "the machine's trust store holds no CA certificates, so nothing "
                "this instance connects to over TLS can be verified — every "
                "check that reads an https address will fail on the certificate "
                "rather than on the subject",
                code=StatusCode.ERROR))
        outcomes = self._outcomes()
        if outcomes is not None and outcomes.all_erroring:
            lines.append(Entry(
                "all-erroring",
                f"every check this instance runs is erroring, all "
                f"{outcomes.configured} of them, so the cause is more likely to "
                f"be here than in {outcomes.configured} different places",
                code=StatusCode.WARN))
        return tuple(lines)
