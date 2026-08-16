"""HTTP(S) health check."""
from __future__ import annotations

from pathlib import Path
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
from little_sister.status import StatusCode
from little_sister.transport import RemoteError


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
            status = fetch(self.url, timeout=self.timeout_seconds,
                           follow_redirects=self.follow_redirects,
                           read_body=False).status
        except RemoteError as error:
            return CheckResult(StatusCode.ERROR,
                               [f"request failed: {plain(str(error))}"])
        if status in self.expected_status:
            return CheckResult(StatusCode.OK)
        expected = ", ".join(str(s) for s in sorted(self.expected_status))
        return CheckResult(
            StatusCode.ERROR, [f"HTTP {status} (expected {expected})"])
