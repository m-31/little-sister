"""Command/script check: OK when the command exits 0."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    code,
    config_markdown,
    register,
)
from little_sister.status import StatusCode

DEFAULT_MAX_CHARS = 1000


@register("command")
class CommandCheck(Check):
    """Run a command (a shell string) or argv (a list); OK on exit code 0.

    The reason/message is taken from the captured output (``capture``:
    ``stdout`` | ``stderr`` | ``both``) and shortened to ``max_chars`` characters
    kept from the ``tail`` (default) or ``head``. Scripts may live in the repo and
    be referenced relative to the checks directory.
    """

    def __init__(self, *, command: str | list[str], working_dir: str,
                 capture: str, max_chars: int, keep: str,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
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

        capture = str(config.get("capture", "stdout")).lower()
        if capture not in ("stdout", "stderr", "both"):
            raise CheckError(f"invalid 'capture': {capture!r} (stdout|stderr|both)")
        keep = str(config.get("keep", "tail")).lower()
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

    def run(self) -> CheckResult:
        use_shell = isinstance(self.command, str)
        # The command is operator-configured and trusted; a string runs via the
        # shell, a list runs directly.
        try:
            completed = subprocess.run(
                self.command, shell=use_shell, cwd=self.working_dir,
                capture_output=True, text=True, timeout=self.timeout_seconds,
                check=False)
        except subprocess.TimeoutExpired:
            return CheckResult(
                StatusCode.ERROR, [f"timed out after {self.timeout_seconds:g}s"])
        except OSError as error:
            return CheckResult(StatusCode.ERROR, [f"failed to run: {error}"])

        output = self._captured(completed.stdout, completed.stderr)
        if completed.returncode == 0:
            return CheckResult(StatusCode.OK, [code(output)] if output else [])
        return CheckResult(StatusCode.ERROR, [
            code(output) if output else f"exit code {completed.returncode}"])

    def _captured(self, stdout: str, stderr: str) -> str:
        if self.capture == "stdout":
            text = stdout
        elif self.capture == "stderr":
            text = stderr
        else:
            text = (stdout or "") + (stderr or "")
        text = text.strip()
        if len(text) <= self.max_chars:
            return text
        if self.keep == "head":
            return text[:self.max_chars]
        return text[-self.max_chars:]
