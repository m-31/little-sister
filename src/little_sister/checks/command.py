"""Command/script check: OK when the command exits 0."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from little_sister import instance, process, values
from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    Measurement,
    code,
    config_markdown,
    plain,
    register,
)
from little_sister.checks.output import (
    captured_output,
    failure_text,
    output_reading,
    output_record_bytes,
)
from little_sister.status import StatusCode

DEFAULT_MAX_CHARS = 1000


@register("command")
class CommandCheck(Check):
    """Run a command (a shell string) or argv (a list); OK on exit code 0.

    The reason/message is taken from the captured output (``capture``:
    ``stdout`` | ``stderr`` | ``both``) and shortened to ``max_chars`` characters
    kept from the ``tail`` (default) or ``head``. Scripts may live in the repo and
    be referenced relative to the check config's own directory.
    """

    def __init__(self, *, command: str | list[str], working_dir: str,
                 capture: str, max_chars: int, keep: str,
                 **kwargs: Any) -> None:
        # **The object is the machine, and the command is the instrument.** The
        # same distinction the rest of the project already turns on: an `http`
        # check's object is its URL and not `GET`, an `ssh-command`'s is the host
        # and not the command it ran there. This is that check's local twin, so
        # its object is the machine little-sister itself runs on — which the
        # library already names (ADR-0074): `instance:` in `settings.yaml`, the
        # hostname where that says nothing.
        #
        # Reading it here is safe and deliberate: `this_instance()` resolves on
        # first use and memoises, and a check is constructed after the
        # configuration root exists.
        super().__init__(subject=instance.this_instance().name, **kwargs)
        self.command = command
        self.working_dir = working_dir
        self.capture = capture
        self.max_chars = max_chars
        self.keep = keep

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        command = config.get("command")
        if not command:
            raise CheckError("command check requires a 'command'")
        if not isinstance(command, (str, list)):
            raise CheckError("'command' must be a string or a list of strings")

        capture = values.text(config, "capture", default="stdout").lower()
        if capture not in ("stdout", "stderr", "both"):
            raise CheckError(f"invalid 'capture': {capture!r} (stdout|stderr|both)")
        keep = values.text(config, "keep", default="tail").lower()
        if keep not in ("tail", "head"):
            raise CheckError(f"invalid 'keep': {keep!r} (tail|head)")

        raw_dir = config.get("working_dir")
        if raw_dir:
            working = Path(raw_dir)
            if not working.is_absolute():
                working = base_dir / working
        else:
            working = base_dir
        return {
            "command": command,
            "working_dir": str(working),
            "capture": capture,
            "max_chars": int(config.get("max_chars", DEFAULT_MAX_CHARS)),
            "keep": keep,
        }

    def config_summary(self) -> str:
        command = (self.command if isinstance(self.command, str)
                   else " ".join(self.command))
        return config_markdown({
            "command": command,
            "capture": self.capture,
            "working dir": self.working_dir,
        })

    def measure(self) -> Measurement:
        """Run the command and keep what it said: an exit code, and the captured
        output clipped **once** — to `max_chars`, then into the byte budget a
        record has — so that one string is both the reading and the line the
        grading writes from it (`checks/output.py` says why the second bound is
        in bytes).

        A run that produced no exit code at all — a timeout, a command that could
        not be started — is still a reading: the two values stand as `None` and
        the reason rides beside them, so a history of this check can answer *how
        often did this run at all*.
        """
        # The command is operator-configured and trusted; a string runs via the
        # shell, a list runs directly — and either way through the library's
        # process function, so the whole group ends with the bound and with the
        # instance's stop, and nothing the shell started outlives the run
        # (ADR-0089).
        argv = (["/bin/sh", "-c", self.command] if isinstance(self.command, str)
                else list(self.command))
        try:
            done = process.run(argv, timeout=self.timeout_seconds, cwd=self.working_dir)
        except process.NotStarted as error:
            return self._failed(f"failed to run: {error.__cause__ or error}")
        if done.ended is process.Ended.BOUND:
            return self._failed(f"timed out after {self.timeout_seconds:g}s")
        if done.ended is process.Ended.STOP:
            return self._failed("ended by the instance's stop")
        return Measurement(record={
            "exit_code": done.status,
            "output": captured_output(done.stdout.decode("utf-8", "replace"),
                                      done.stderr.decode("utf-8", "replace"),
                                      capture=self.capture,
                                      max_chars=self.max_chars,
                                      keep=self.keep)})

    @staticmethod
    def _failed(reason: str) -> Measurement:
        """A run that never got as far as an exit code. Raw, not `plain()`-ed: a
        record's values are escaped where they are rendered."""
        return Measurement(record={"exit_code": None, "output": None,
                                   "error": failure_text(reason)})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """OK on exit 0, ERROR otherwise, with the captured output as the reason
        — read out of the record and nothing else. `measure` above always hands
        back exactly one reading."""
        exit_code, output, failure = output_reading(measurements[0].record)
        if failure:
            return CheckResult(StatusCode.ERROR, [plain(failure)])
        if exit_code == 0:
            return CheckResult(StatusCode.OK, [code(output)] if output else [])
        return CheckResult(StatusCode.ERROR, [
            code(output) if output else f"exit code {exit_code}"])

    def expected_record(self) -> int:
        """An exit code and the captured output, bounded by what this check was
        configured to keep — a ceiling the clip in `measure` cannot exceed
        (ADR-0075)."""
        return output_record_bytes(self.max_chars)
