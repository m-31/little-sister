"""HTTP(S) health check."""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    Measurement,
    config_markdown,
    plain,
    register,
)
from little_sister.checks.output import FAILURE_BYTES, failure_text
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

#: What one record of this check costs, declared for the startup sum (ADR-0075) —
#: a **ceiling**, which it can be because nothing in either shape is unbounded. The
#: failed reading is the larger one: its two nulls and its keys, as `json.dumps`
#: writes them, plus the error at the most :func:`failure_text` lets it cost —
#: `FAILURE_BYTES`, which already counts the string's own quotes, so the skeleton's
#: empty `""` comes off. An answered reading is a status and a duration, some forty
#: bytes, and fits under it with room.
RECORD_BYTES = (len(json.dumps({"status": None, "response_ms": None, "error": ""}))
                - len('""') + FAILURE_BYTES)

#: What this check's readings are drawn by, declared for the library to merge a
#: deployment's `measures:` over (ADR-0092): the response time, in milliseconds —
#: which the page writes as a span, so 1,850 reads `1.9 s`. `status` is not here: it
#: is a code, and a curve of codes is a mistake a deployment can still make itself.
MEASURES = {"response_ms": {"unit": "ms", "label": "Response time"}}

#: What this type grades (ADR-0131): the statuses an answer may carry — a set of
#: accepted values, `200` where the configuration names none, any other an error.
GRADINGS: dict[str, object] = {
    "expected_status": {
        "sentence": "The statuses an answer may carry; any other is an error.",
        "kind": "set", "field": "status", "accepted": [200],
    },
}


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
    """GET a URL; OK when the response status is one of ``expected_status``, a set
    of accepted values the library reads and grades by (ADR-0131)."""

    # `follow_redirects` is **required and has no default here**, deliberately. Every
    # instance is built through `from_config`, which always supplies it, so a default on
    # this line would be unreachable — a second place stating the policy, free to drift
    # out of step with `_extra_from_config` while no test could tell. The default lives
    # once, where the config is read.
    def __init__(self, *, url: str, follow_redirects: bool, **kwargs: Any) -> None:
        # The URL **is** the object this check reads, so it is what the reading is
        # about — not the node's path, which is the deployment's label for where
        # the node hangs and may be renamed without the endpoint moving.
        super().__init__(subject=url, measure_defaults=MEASURES, gradings=GRADINGS,
                         **kwargs)
        self.url = url
        self.follow_redirects = follow_redirects

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        url = config.get("url")
        if not url:
            raise CheckError("http check requires a 'url'")
        return {
            "url": str(url),
            # Defaulted to **today's behavior**, because the alternative is a silent
            # regrade: a check written against a URL that answers `200` after a `301`
            # would turn red on upgrade, on a config nobody edited (ADR-0058).
            "follow_redirects": (
                True if config.get("follow_redirects") is None
                else _flag(config.get("follow_redirects"), "follow_redirects")),
        }

    def config_summary(self) -> str:
        return config_markdown({
            "url": self.url,
            "expected status": self.grading_summary("expected_status"),
            # Named on the node because the two readings differ on the same URL, so an
            # operator looking at an unexpected verdict needs to know which was taken.
            "redirects": "followed" if self.follow_redirects else "reported",
        })

    def measure(self) -> Measurement:
        """Read the endpoint: the status it answered with, and how long it took.

        This half touches the world and decides nothing. What it hands back is
        one reading of one object — the URL — and every path through it produces
        the **same shape**, so a curve over the series draws a real gap from a
        null instead of inferring one from a key that is not there.
        """
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
            # running the request on a thread that is abandoned at a deadline.
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
            #
            # The reason rides beside them, and **only where there was one**: carried
            # as a null on every successful reading it would lengthen every record for
            # nothing, since a projection treats a missing key as an empty one
            # (ADR-0085 decision 3, which is why this one key is the exception to the
            # null-not-absent rule above it).
            # The message goes in **raw**: a record's values are escaped where they
            # are rendered, so folding it through `plain()` here would store the
            # escaping and show it (`&amp;`, a literal `\_`). The line below is
            # where it is folded into Markdown, which is the one place it has to be.
            #
            # And **clipped once, in bytes** (ADR-0086 decision 7): it is free text
            # entering a record, and an error can carry a URL, a server's body or a
            # stack of causes. Unclipped it made `RECORD_BYTES` a hope rather than
            # a ceiling; the grading writes the line from exactly this text.
            return Measurement(record={"status": None, "response_ms": None,
                                       "error": failure_text(str(error))})
        # `response_ms` names its unit because a record renders as its keys (ADR-0082's
        # untyped rendering), so the name is what a reader sees; a **curve's** unit
        # belongs to the projection that draws it, not here.
        return Measurement(record={"status": status, "response_ms": elapsed_ms})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """Say what that reading means: a code, and the sentence that retells it.

        Pure over the record and this check's own `expected_status` — nothing here
        looks at the world, or at anything `measure` left behind, which is what
        lets the same verdict be reached again later over a record out of the
        series. The status is graded through the seam (ADR-0131): an answer outside
        the set says which it expected, and the sentence the deployment wrote for
        it after that. `measure` above always hands back exactly one reading.

        The line carries **no code of its own**: with a single line the node's own
        reading is already the verdict, and a coded entry beside a declared result
        code is the shape `CheckResult` refuses (ADR-0042).
        """
        record = measurements[0].record
        status = record.get("status")
        if status is None:
            reason = plain(str(record.get("error") or "no answer"))
            return CheckResult(
                StatusCode.ERROR,
                [Entry(RESPONSE_SLUG, f"request failed: {reason}")])
        elapsed_ms = record.get("response_ms")
        verdict = self.verdict("expected_status", measurements[0])
        note = f" (expected {verdict.against})" if verdict.against else ""
        return CheckResult(verdict.code, [verdict.entry(
            f"HTTP {status}{note} in {elapsed_ms} ms", slug=RESPONSE_SLUG)])

    def expected_entries(self) -> int:
        """One line, always: this check reads one endpoint (ADR-0075)."""
        return 1

    def expected_record(self) -> int:
        return RECORD_BYTES
