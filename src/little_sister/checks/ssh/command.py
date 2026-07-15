"""ssh-command: run a remote command over SSH.

The over-SSH twin of the local ``command`` check — the host's shell runs the
``command``; OK on exit 0, ERROR otherwise, the reason taken from the captured
output (``capture``: ``stdout`` | ``stderr`` | ``both``, shortened to ``max_chars``
from the ``tail`` or ``head``). A successful run still **WARN**s on an ssh advisory
such as a non-post-quantum key exchange.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from little_sister.checks.base import (
    CheckError,
    CheckResult,
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

    def run(self) -> CheckResult:
        result = self.connection.run(self.command)
        return self._output_result(result, capture=self.capture,
                                   max_chars=self.max_chars, keep=self.keep)
