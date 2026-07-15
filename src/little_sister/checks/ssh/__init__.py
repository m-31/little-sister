"""SSH checks: a shared transport, a pure toolkit and a family of checks.

One transport — :class:`~little_sister.checks.ssh.transport.SshConnection` — and a
family of checks by what they do over it: ``ssh-connect`` (reachability),
``ssh-command`` (a remote command), ``ssh-script`` (a local script on the host),
``host-metrics`` (a parsed ``ssh-script``: disk/memory/CPU/load), ``qnap-metrics``
(QNAP hardware health) and ``macos-memory`` (macOS memory pressure / swap /
compressor / process RSS). The shared bases live in :mod:`.base`, the connection
in :mod:`.transport`, and the pure parsing/grading toolkit in :mod:`.metrics`.
Importing this package registers the check types.
"""
# Import the family modules for their registration side effects.
from little_sister.checks.ssh import (  # noqa: F401
    command,
    connect,
    host_metrics,
    macos_memory,
    qnap_metrics,
    script,
)
from little_sister.checks.ssh.base import SshCheckBase, SshScriptCheck
from little_sister.checks.ssh.host_metrics import HostMetricsCheck, _parse_disk_path
from little_sister.checks.ssh.macos_memory import MacosMemoryCheck
from little_sister.checks.ssh.qnap_metrics import QnapMetricsCheck
from little_sister.checks.ssh.transport import RemoteResult, SshConnection

__all__ = [
    "HostMetricsCheck",
    "MacosMemoryCheck",
    "QnapMetricsCheck",
    "RemoteResult",
    "SshCheckBase",
    "SshConnection",
    "SshScriptCheck",
    "_parse_disk_path",
]
