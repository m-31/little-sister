"""ssh-command: run a remote command over SSH.

The over-SSH twin of the local ``command`` check — the host's shell runs the
``command``; OK on exit 0, ERROR otherwise, the reason taken from the captured
output (``capture``: ``stdout`` | ``stderr`` | ``both``, shortened to ``max_chars``
from the ``tail`` or ``head``). A successful run still **WARN**s on an ssh advisory
such as a non-post-quantum key exchange.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from little_sister.checks.base import (
    CheckError,
    CheckResult,
    Measurement,
    config_markdown,
    register,
)
from little_sister.checks.ssh.base import SshCheckBase, parse_output_config


@register("ssh-command")
class RemoteCommandCheck(SshCheckBase):
    """Run a command on a host over SSH; OK on exit code 0."""

    def __init__(self, *, command: str, capture: str, max_chars: int,
                 keep: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.command = command
        self.capture = capture
        self.max_chars = max_chars
        self.keep = keep

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        command = config.get("command")
        if not command:
            raise CheckError("ssh-command check requires a 'command'")
        if not isinstance(command, str):
            raise CheckError("'command' must be a string (the remote shell runs it)")
        return {
            **cls._base_connection_config(config),
            "command": command,
            **parse_output_config(config),
        }

    def config_summary(self) -> str:
        return config_markdown({**self._connection_fields(),
                                "command": self.command,
                                "capture": self.capture})

    def measure(self) -> Measurement:
        """Run the command on the host and keep what it said. The **host** is the
        object — the command is how this check reads it, the way an `http` check's
        object is its URL and not `GET`."""
        return self._output_measurement(
            self.connection.run(self.command), capture=self.capture,
            max_chars=self.max_chars, keep=self.keep)

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """OK on exit 0, ERROR otherwise, WARN on an ssh advisory — all of it out
        of the record. `measure` above always hands back exactly one reading."""
        return self._output_result(measurements[0].record)

    def expected_record(self) -> int:
        return self._output_record_bytes(self.max_chars)
