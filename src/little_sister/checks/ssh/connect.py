"""ssh-connect: can we reach a host over SSH?

The reachability probe of the family — connect (``BatchMode``, key auth) and run a
trivial remote ``true``. OK when it returns, ERROR when the connection fails, and
**WARN** when ssh flags an advisory such as a non-post-quantum key exchange — the
warning every SSH check built on the transport carries.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from little_sister.checks.base import (
    CheckResult,
    Measurement,
    config_markdown,
    plain,
    register,
)
from little_sister.checks.ssh.base import SshCheckBase
from little_sister.status import StatusCode


@register("ssh-connect")
class ConnectCheck(SshCheckBase):
    """Connectivity: OK if the host is reachable over SSH, ERROR if not."""

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return cls._base_connection_config(config)

    def config_summary(self) -> str:
        return config_markdown(self._connection_fields())

    def measure(self) -> Measurement:
        """Open the connection and run a trivial ``true``. What is read is how the
        connection itself went, which for this check is the whole reading: the
        host is the object, and failing to answer *is* the measurement."""
        return Measurement(
            record=self._transport_record(self.connection.run("true")))

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """Reachable, reachable-with-an-advisory, or not — read out of the record
        and out of this check's own connection fields, and nothing else."""
        record = measurements[0].record
        debug = self._debug_lines(record)
        error = record.get("error")
        if error is not None:
            return CheckResult(StatusCode.ERROR, [plain(str(error)), *debug])
        if record.get("exit_code") != 0:
            detail = str(record.get("detail") or "no output")
            return CheckResult(
                StatusCode.ERROR,
                [f"cannot reach {plain(self._target)}: {plain(detail)}", *debug])
        reasons = [f"{plain(self.host)} reachable"]
        notice = record.get("notice")
        if notice:
            reasons.append(plain(str(notice)))
        reasons += debug
        return CheckResult(StatusCode.WARN if notice else StatusCode.OK,
                           reasons)

    def expected_record(self) -> int:
        """Just the transport half: this check reads nothing else (ADR-0075)."""
        return self._transport_record_bytes()
