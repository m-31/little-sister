"""HTTP(S) health check."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    config_markdown,
    plain,
    register,
)
from little_sister.fetch import fetch
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.transport import RemoteError

#: This check reads one thing, so its line needs no identity of its own to be told
#: apart from a sibling — the addressing a slug exists for (ADR-0036) has nothing to
#: disambiguate here. What it does need is to be the **same slug across readings**,
#: because a pin holds one: a derived slug would hash the sentence and mint a new
#: one every poll, as the number in it moves.
RESPONSE_SLUG = "response"

#: What one record of this check costs, declared for the startup sum (ADR-0075): a
#: status and a duration, with room. Measured at 36 bytes for a three-digit status
#: and a four-digit time; the declaration is the ceiling, not the average.
RECORD_BYTES = 64


def _flag(value: object, field: str) -> bool:
    """A configuration boolean that must actually be one.

    ``bool("false")`` is ``True``, so a quoted YAML boolean — ``follow_redirects:
    "false"`` — would switch redirect-following **on** while the config says off, and
    nothing downstream could notice: the check would simply keep reporting the reading
    it was told not to take. A switch is worth less than nothing when it can silently
    mean its opposite, and this one decides whether a login wall counts as health.
    """
    if not isinstance(value, bool):
        raise CheckError(f"http '{field}' must be true or false")
    return value


@register("http")
class HttpCheck(Check):
    """GET a URL; OK when the response status is one of ``expected_status``."""

    # `follow_redirects` is **required and has no default here**, deliberately. Every
    # instance is built through `from_config`, which always supplies it, so a default on
    # this line would be unreachable — a second place stating the policy, free to drift
    # out of step with `_extra_from_config` while no test could tell. The default lives
    # once, where the config is read.
    def __init__(self, *, url: str, expected_status: set[int],
                 follow_redirects: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.expected_status = expected_status
        self.follow_redirects = follow_redirects

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        url = config.get("url")
        if not url:
            raise CheckError("http check requires a 'url'")
        expected = config.get("expected_status", 200)
        if isinstance(expected, int):
            expected = [expected]
        return {
            "url": str(url),
            "expected_status": {int(s) for s in expected},
            # Defaulted to **today's behavior**, because the alternative is a silent
            # regrade: a check written against a URL that answers `200` after a `301`
            # would turn red on upgrade, on a config nobody edited (ADR-0058).
            "follow_redirects": (
                True if config.get("follow_redirects") is None
                else _flag(config.get("follow_redirects"), "follow_redirects")),
        }

    def config_summary(self) -> str:
        expected = ", ".join(str(s) for s in sorted(self.expected_status))
        return config_markdown({
            "url": self.url,
            "expected status": expected,
            # Named on the node because the two readings differ on the same URL, so an
            # operator looking at an unexpected verdict needs to know which was taken.
            "redirects": "followed" if self.follow_redirects else "reported",
        })

    def run(self) -> CheckResult:
        try:
            # **The endpoint is the subject of this measurement**, so a failure to
            # answer is the reading rather than an obstacle to it — which is why this
            # check maps a transport failure straight to ERROR and needs nothing from
            # the fault vocabulary (ADR-0058). The body is not read; this check asks a
            # status and stops.
            #
            # `follow_redirects` is the config's, defaulting to following — which is
            # what this check always did. The two readings genuinely differ and both
            # are right somewhere: following is how a login wall answering `200` at the
            # end of a chain reads as health, and reporting is how a `301` reads as
            # *alive and moved*. Which one a deployment wants is not something a library
            # can know, which is why `fetch` refuses to assume it either.
            #
            # **And no `deadline=`, deliberately.** It was proposed — this check has a
            # `timeout_seconds` and building a `Deadline` from it looks obviously right
            # — and measuring it settled the other way. A `Deadline` does three things
            # inside `fetch`: it refuses a request whose budget is already spent, it
            # clamps the per-request timeout to what the run has left, and it bounds
            # the **body read**. This check makes one request, so the first two have
            # nothing to act on: the budget is untouched and the clamp is `min(t, t)`.
            # And `read_body=False` means there is no body read to bound — against a
            # server dribbling a body, this check already returns at once, because it
            # never asks for one. So the argument would have bought a line of code and
            # no bound at all, and a bound that does nothing is worse than none: the
            # next reader believes it.
            #
            # What is genuinely unbounded here is a server trickling the **status line
            # and headers**, which urllib reads inside `opener.open` where no deadline
            # of ours can reach (see `fetch`'s module docstring). A `Deadline` does not
            # help with that either. Closing it means owning the header parse or
            # running the request on a thread — the shape the link prober already has,
            # for the same reason, in its pass abandonment (ADR-0030).
            #
            # **The timer wraps the call and nothing else** (backlog #76). What is
            # measured is the subject — the time until this endpoint answered — and
            # not our run, which the engine already times as `run.wall_seconds`
            # (ADR-0044). Keeping the two apart is the whole distinction: one says
            # how the world is, the other how we are.
            started = perf_counter()
            status = fetch(self.url, timeout=self.timeout_seconds,
                           follow_redirects=self.follow_redirects,
                           read_body=False).status
            elapsed_ms = round((perf_counter() - started) * 1000)
        except RemoteError as error:
            # **A failed reading is a reading**, and it is recorded as one. The check
            # did learn something — that it could not get there, and why — and that is
            # data about this attempt rather than nothing at all. Left out, the series
            # would carry a *hole*, and a hole cannot be told apart from a restart, a
            # pause or a poll that never happened; with it, availability is in the
            # data itself: how many readings answered, over how many there were.
            #
            # `status` and `response_ms` stand as `None` rather than being omitted, so
            # every reading of this check has the same shape and a curve draws a real
            # gap from a null. What they must *not* hold is how long we waited before
            # giving up: that is the timeout's number, not the endpoint's, and under
            # `response_ms` it would seed a series with values that are not the thing
            # it measures.
            return CheckResult(
                StatusCode.ERROR,
                [Entry(RESPONSE_SLUG, f"request failed: {plain(str(error))}")],
                subject=self.url,
                record={"status": None, "response_ms": None,
                        "error": plain(str(error))})
        if status in self.expected_status:
            return self._read(StatusCode.OK, status, elapsed_ms)
        expected = ", ".join(str(s) for s in sorted(self.expected_status))
        return self._read(StatusCode.ERROR, status, elapsed_ms,
                          note=f" (expected {expected})")

    def _read(self, code: StatusCode, status: int, elapsed_ms: int,
              note: str = "") -> CheckResult:
        """One reading of this endpoint: the measurement at the **run**, and the
        sentence that retells it.

        The record hangs on the result rather than on the line, because this check
        reads **one object and its node stands for it** — the line is a rendering,
        not the thing measured (ADR-0085). `subject` is the URL rather than the node
        path, since the path is the deployment's label and may be moved or renamed.

        The line carries **no code of its own**: with a single line the node's own
        reading is already the verdict, and a coded entry beside a declared result
        code is the shape `CheckResult` refuses (ADR-0042).

        `response_ms` names its unit because a record renders as its keys (ADR-0082's
        untyped rendering), so the name is what a reader sees; a **curve's** unit
        belongs to the projection that draws it, not here.
        """
        return CheckResult(
            code, [Entry(RESPONSE_SLUG, f"HTTP {status}{note} in {elapsed_ms} ms")],
            subject=self.url,
            record={"status": status, "response_ms": elapsed_ms})

    def expected_entries(self) -> int:
        """One line, always: this check reads one endpoint (ADR-0075)."""
        return 1

    def expected_record(self) -> int:
        return RECORD_BYTES
