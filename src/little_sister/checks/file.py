"""File-freshness check: OK while a file keeps being updated."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
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
from little_sister.spans import format_span
from little_sister.status import StatusCode

#: What one record of this check costs, declared for the startup comparison
#: (ADR-0075) — a **ceiling**. The failed read is the larger shape: `modified.at`
#: standing as a null beside the reason, as `json.dumps` writes them, plus the
#: reason at the most :func:`failure_text` lets it cost — `FAILURE_BYTES`, which
#: already counts the string's own quotes, so the skeleton's empty `""` comes off.
#: The reason names the file and the OS error, and a path is as long as somebody
#: made it, which is why it is clipped rather than trusted. A read that succeeded
#: is one ISO-8601 instant with its offset, some fifty bytes.
RECORD_BYTES = (len(json.dumps({"modified": {"at": None}, "error": ""}))
                - len('""') + FAILURE_BYTES)

#: What this type grades (ADR-0131): how long ago its file changed, a maximum — an
#: error above twenty minutes where the configuration writes no level of its own.
GRADINGS: dict[str, object] = {
    "max_age": {
        "sentence": "How long ago the file may have changed.",
        "kind": "pair", "field": "modified.at", "unit": "duration",
        "error": "20m",
    },
}


@register("file")
class FileFreshnessCheck(Check):
    """OK while the file changed within ``max_age``'s levels — a maximum, written
    ``max_age_warn`` and ``max_age_error`` among the check's own keys and an error
    above twenty minutes where neither is (ADR-0131); WARN or ERROR beyond them.

    Use it as a heartbeat: a process that writes/touches a file regularly is
    healthy while the file stays fresh, and unhealthy once it goes stale. A
    relative ``file`` path resolves against the executing user's ``$HOME``.
    """

    def __init__(self, *, file_path: str, **kwargs: Any) -> None:
        # The file **is** the object this check reads — the local twin of the
        # `http` check's URL. Not the node's path, which is where the deployment
        # chose to hang the node and says nothing about which file went stale.
        super().__init__(subject=file_path, gradings=GRADINGS, **kwargs)
        self.file_path = file_path

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        raw = config.get("file")
        if not raw:
            raise CheckError("file check requires a 'file' path")
        _refuse_the_retired_age(config)
        # File paths are relative to the executing user's $HOME ('~' expands too).
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = Path.home() / path
        return {"file_path": str(path)}

    def config_summary(self) -> str:
        return config_markdown({
            "file": self.file_path,
            "max age": self.grading_summary("max_age") or "not graded",
        })

    def measure(self) -> Measurement:
        """Read the file's modification time, and nothing about whether it is old.

        How old is too old is `max_age` — configuration, read by the grading —
        and *how old* is a fact about `now`, which the grading is handed. Neither
        belongs here, and this is the clearest case in the library of why: this
        half must produce the same record whenever it is replayed, and an age
        would be stale the moment it was written.

        The time carries an **offset**: `at` is a name the surfaces read as an
        instant, and the seam converts it to UTC. A naive stamp is an instant
        only to whoever wrote it.
        """
        try:
            mtime = os.path.getmtime(self.file_path)
        except FileNotFoundError:
            # The failure names the file, because a series of failures that does
            # not is a column of "could not read" nobody can act on. Raw, not
            # `plain()`-ed: a record's values are escaped where they are rendered,
            # and the grading folds this one into Markdown itself. Clipped once, in
            # bytes, like any free text entering a record (ADR-0086 decision 7):
            # the path is as long as somebody made it.
            return Measurement(record={
                "modified": {"at": None},
                "error": failure_text(f"file not found: {self.file_path}")})
        except OSError as error:
            return Measurement(record={
                "modified": {"at": None},
                "error": failure_text(f"cannot read file: {error}")})
        return Measurement(record={
            "modified": {"at": datetime.fromtimestamp(
                mtime, tz=UTC).isoformat()}})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """Is that reading fresh enough? Pure over the record, `max_age` and the
        clock it is given — which is exactly the three this seam promises, and why
        this check can be graded again next year over a record out of the series.

        The age is derived here, from the record's time and the clock, and handed
        to the grading as the value it judges (ADR-0131 decision 1); a stale line
        says the level it went beyond, and the sentence the deployment wrote for the
        judgment after it. `measure` above always hands back exactly one reading.
        """
        reading = measurements[0]
        moment = reading.record.get("modified", {}).get("at")
        if moment is None:
            failure = str(reading.record.get("error") or "cannot read file")
            return CheckResult(StatusCode.ERROR, [plain(failure)])
        age = (now - datetime.fromisoformat(moment)).total_seconds()
        verdict = self.verdict("max_age", reading, value=age)
        if verdict.code == StatusCode.OK:
            return CheckResult(StatusCode.OK)
        # The age is a measured span and the level a configured interval, each in
        # the library's words for it (ADR-0099 decision 4): past a day in days and
        # the hour beside them, where "1987h14m" was eighty-two days — and the level
        # as it was written, where a week read "168h00m".
        return CheckResult(verdict.code, [verdict.entry(
            f"stale: last changed {format_span(age)} ago (max {verdict.against})")])

    def expected_record(self) -> int:
        """A timestamp and, on a bad read, a short reason (ADR-0075)."""
        return RECORD_BYTES


def _refuse_the_retired_age(config: Mapping[str, Any]) -> None:
    """Refuse the spelling the age had before it was a pair (ADR-0131 decision 2):
    ``max_age`` with a level, and ``stale_code``, the code it took — naming what
    replaces them, since a level passes at itself now."""
    if "stale_code" not in config and config.get("max_age") is None:
        return
    level = config.get("max_age") or "20m"
    code = str(config.get("stale_code") or "ERROR").strip().upper()
    write = ("max_age: null, which switches the judgment off" if code == "OK"
             else f"max_age_{'warn' if code == 'WARN' else 'error'}: {level}")
    raise CheckError(
        f"'max_age' with a level, and 'stale_code', are retired: the file check's "
        f"age is a pair now, whose level is the last age that passes — write "
        f"{write}, and drop 'stale_code' (ADR-0131)")
