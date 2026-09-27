"""One run of a check, the way the engine does it.

The engine calls :meth:`~little_sister.checks.Check.measure` and then
:meth:`~little_sister.checks.Check.grade` (ADR-0086), and a test that wants *the
result of running this check* wants both. Written once here rather than four
lines in sixty tests, and deliberately **not** a method on ``Check``: a
convenience that ran the two halves together would be the thing every author
reached for, and the seam would quietly stop being a seam.

:func:`measured` is the other half of the same idea, for a test whose subject is
the record rather than the verdict.
"""
from __future__ import annotations

import os
import shlex
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from unittest import mock

from little_sister import process
from little_sister.checks import Check, CheckResult, Measurement


def measured(check: Check) -> tuple[Measurement, ...]:
    """What one ``measure()`` handed back, normalized the way the engine does."""
    answer = check.measure()
    if isinstance(answer, Measurement):
        return (answer,)
    return tuple(answer)


def record_of(check: Check) -> dict[str, object]:
    """The record of a check that reads one object — the common case."""
    return dict(measured(check)[0].record)


def run_check(check: Check, *, now: datetime | None = None,
              measurements: Sequence[Measurement] | None = None) -> CheckResult:
    """Measure, then grade, and answer the result the engine would store.

    ``now`` is the instant the grading is handed; ``measurements`` replaces the
    measuring half, for a test that grades a reading it wrote itself — which is
    the whole point of the split and so worth being easy to do.
    """
    taken = measured(check) if measurements is None else tuple(measurements)
    return check.grade(taken, now or datetime.now(UTC))


def pid_gone(pid: int, seconds: float = 4.0) -> bool:
    """Whether process ``pid`` has ended within ``seconds`` — a zombie waiting for its
    reaper counts as ended, since it runs nothing (ADR-0089)."""
    end = time.monotonic() + seconds
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        try:
            with open(f"/proc/{pid}/stat", encoding="ascii") as stat:
                if stat.read().split(") ", 1)[1][0] == "Z":
                    return True
        except OSError:
            pass
        if time.monotonic() >= end:
            return False
        time.sleep(0.02)


#: What an ``ssh`` run's client goes through, for a test that stands in for it.
SSH_RUN = "little_sister.checks.ssh.connection.process.run"


def finished(stdout: str = "", returncode: int = 0, stderr: str = "", *,
             ended: process.Ended = process.Ended.EXITED) -> process.Finished:
    """What the process function answers for one run, from text — the stand-in a test
    hands back for an ``ssh`` client it does not start."""
    return process.Finished(status=returncode, stdout=stdout.encode(),
                            stderr=stderr.encode(), ended=ended, stdout_cut=False,
                            stderr_cut=False, seconds=0.0)


def remote_parts(run: mock.Mock) -> tuple[str, str | None]:
    """The command an ``ssh`` run sent and the script it carried (or ``None``): the
    command read back out of the remote wrapper's arguments, the script out of what
    the run sent ahead of the hang-up line, without the line that gives it its
    arguments (ADR-0089 decision 4; :func:`remote_args` reads those)."""
    words = shlex.split(run.call_args.args[0][-1])
    assert words[:3] == ["exec", "sh", "-c"] and words[4] == "little-sister", words[:5]
    assert len(words) == 6, "the command line carries the wrapper and the command alone"
    return words[5], _script_sent(run)[1]


def remote_args(run: mock.Mock) -> list[str]:
    """The arguments an ``ssh`` run gave the script it carried."""
    arguments, _ = _script_sent(run)
    assert arguments is not None, "the run carried no script"
    return arguments


def _script_sent(run: mock.Mock) -> tuple[list[str] | None, str | None]:
    """What a run sent ahead of the hang-up line — its length in lines, then the
    script, whose first command is a ``set --`` — as the arguments and the rest."""
    count, _, sent = run.call_args.kwargs["send"].decode("utf-8").partition("\n")
    assert sent.count("\n") == int(count), (count, sent[:80])
    if not int(count):
        return None, None
    lines = sent.split("\n")
    for end in range(1, len(lines)):
        try:
            words = shlex.split("\n".join(lines[:end]))
        except ValueError:      # a quoted argument goes on past this line
            continue
        assert words[:2] == ["set", "--"], words[:2]
        return words[2:], "\n".join(lines[end:])
    raise AssertionError(f"the script sent sets no arguments: {sent[:80]!r}")


def subprocess_env() -> dict[str, str]:
    """An environment for a test's child interpreter that imports the library: this
    suite's configuration roots — whatever an earlier test did to the variable — and
    a log file that goes nowhere, so the child writes nothing into a checkout."""
    tests = os.path.dirname(os.path.abspath(__file__))
    roots = os.pathsep.join((os.path.join(tests, "fixtures", "config"),
                             os.path.join(os.path.dirname(tests), "config")))
    return {**os.environ, "LITTLE_SISTER_CONFIG_DIR": roots, "LOG_FILE": os.devnull}
