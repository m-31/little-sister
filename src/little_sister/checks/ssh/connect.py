"""ssh-connect: can we reach a host over SSH?

The reachability probe of the family — connect (``BatchMode``, key auth) and run a
trivial remote ``true``. OK when it returns, ERROR when the connection fails, and
**WARN** when ssh flags an advisory such as a non-post-quantum key exchange — the
warning every SSH check built on the transport carries.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from little_sister.checks.base import CheckResult, config_markdown, plain, register
from little_sister.checks.ssh.base import SshCheckBase
from little_sister.checks.ssh.metrics import oneline, strip_ssh_notices
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

    def run(self) -> CheckResult:
        result = self.connection.run("true")
        if result.error is not None:
            return CheckResult(StatusCode.ERROR,
                               [plain(result.error), *self._debug_reason(result)])
        if result.exit_code != 0:
            detail = oneline(strip_ssh_notices(result.stderr)
                             or result.stdout) or "no output"
            return CheckResult(
                StatusCode.ERROR,
                [f"cannot reach {plain(self._target)}: {plain(detail)}",
                 *self._debug_reason(result)])
        reasons = [f"{plain(self.host)} reachable"]
        if result.notice:
            reasons.append(plain(result.notice))
        reasons += self._debug_reason(result)
        return CheckResult(StatusCode.WARN if result.notice else StatusCode.OK,
                           reasons)
