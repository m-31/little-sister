"""ssh-script: run a local script on a host over SSH.

Pipe a local ``script`` to the host's shell via ``interpreter`` (default ``bash``)
and report its output, like ``ssh-command``: OK on exit 0, ERROR otherwise, the
reason from the captured output (``capture`` / ``max_chars`` / ``keep``), and
**WARN** on an ssh advisory such as a non-post-quantum key exchange. This is the
base the metrics checks specialize — they parse the script's output instead of
returning it raw.
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
from little_sister.checks.ssh.base import SshScriptCheck, parse_output_config


@register("ssh-script")
class ScriptCheck(SshScriptCheck):
    """Run a local script on a host over SSH; OK on exit code 0."""

    def __init__(self, *, capture: str, max_chars: int, keep: str,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.capture = capture
        self.max_chars = max_chars
        self.keep = keep

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        if not config.get("script"):
            raise CheckError("ssh-script check requires a 'script'")
        return {
            **cls._connection_from_config(config, base_dir, str(config["script"])),
            "interpreter": str(config.get("interpreter", "bash")),
            **parse_output_config(config),
        }

    def config_summary(self) -> str:
        return config_markdown({**self._connection_fields(),
                                "script": Path(self.script_path).name,
                                "interpreter": self.interpreter})

    def measure(self) -> Measurement:
        """Pipe the script to the host and keep what it printed. The **host** is
        the object; the script is how this check reads it."""
        return self._output_measurement(
            self._run(), capture=self.capture, max_chars=self.max_chars,
            keep=self.keep)

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """OK on exit 0, ERROR otherwise, WARN on an ssh advisory — all of it out
        of the record. `measure` above always hands back exactly one reading."""
        return self._output_result(measurements[0].record)

    def expected_record(self) -> int:
        return self._output_record_bytes(self.max_chars)
