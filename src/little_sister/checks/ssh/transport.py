"""SSH transport: a connection value object that runs commands and scripts.

:class:`SshConnection` carries one host's connection parameters and is the single
place they become an ``ssh`` argv (``BatchMode`` forced — non-interactive,
key-based auth, host key already known; the legacy SHA-1 ``ssh-rsa`` algorithm off
by default). It can run a remote command (``run``) or pipe a local script to the
host's shell (``run_script``); each returns a :class:`RemoteResult`.

The transport reports **facts**, not verdicts: it sets ``error`` only when ssh
could not run at all (a timeout, a spawn failure, an unreadable script), leaving a
completed run — whatever its exit code — for the *check* to interpret. ``notice``
carries any ssh advisory banner (e.g. a non-post-quantum key exchange) for a check
to surface as WARN.
"""
from __future__ import annotations

import shlex
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from little_sister.checks.base import DEFAULT_TIMEOUT_SECONDS
from little_sister.checks.ssh.metrics import ssh_notices

DEFAULT_CONNECT_TIMEOUT = 10

# Turn the legacy SHA-1 RSA algorithm off by default for every host (modern
# rsa-sha2-256/512 keys are unaffected). Applied as a command-line `-o` *after*
# the user's own ``options`` so a host that still needs it can override with
# ``options: ["-o", "PubkeyAcceptedAlgorithms=+ssh-rsa"]`` (ssh uses the first
# value it sees for each option).
DEFAULT_OPTIONS = ("-o", "PubkeyAcceptedAlgorithms=-ssh-rsa")


@dataclass(frozen=True)
class RemoteResult:
    """The outcome of one SSH invocation.

    ``error`` is set **only** when ssh could not run — a timeout, a spawn failure,
    or an unreadable script — and ``exit_code`` is then ``None``. A completed run
    has ``error is None`` regardless of its exit code; the check decides what a
    non-zero exit means. ``notice`` is the text of any ssh advisory banner (e.g. a
    non-post-quantum key exchange), to surface as WARN; ``""`` when there is none.
    """
    stdout: str
    stderr: str
    exit_code: int | None
    error: str | None
    notice: str = ""


@dataclass(frozen=True)
class SshConnection:
    """One host's SSH connection parameters, and how to run over them.

    ``options`` are passed before little-sister's own defaults so a host can
    override them; ``sudo`` runs the remote command under ``sudo -n``.
    """
    host: str
    user: str | None = None
    port: int | None = None
    sudo: bool = False
    identity_file: str | None = None
    options: tuple[str, ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def target(self) -> str:
        return f"{self.user}@{self.host}" if self.user else self.host

    def run(self, command: str) -> RemoteResult:
        """Run a remote command (the host's shell runs it); no stdin. ``sudo -n``
        is prepended when set."""
        remote = f"sudo -n {command}" if self.sudo else command
        return self._invoke(remote, stdin="")

    def run_script(self, script_path: str, interpreter: str,
                   args: Sequence[str] = ()) -> RemoteResult:
        """Pipe a local script to the host's ``interpreter`` (read from stdin via
        ``<interpreter> -s --``); ``args`` become the script's positional
        arguments. Returns a failed :class:`RemoteResult` if the script is
        unreadable, the ssh spawn fails or it times out."""
        try:
            script = Path(script_path).read_text(encoding="utf-8")
        except OSError as error:
            return RemoteResult("", "", None, f"cannot read script: {error}")
        parts = [interpreter, "-s", "--", *args]
        if self.sudo:
            parts = ["sudo", "-n", *parts]
        remote = " ".join(shlex.quote(part) for part in parts)
        return self._invoke(remote, stdin=script)

    def _argv(self, remote_command: str) -> list[str]:
        connect_timeout = max(1, min(DEFAULT_CONNECT_TIMEOUT,
                                     int(self.timeout_seconds)))
        argv = ["ssh", "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={connect_timeout}"]
        if self.identity_file:
            argv += ["-i", self.identity_file]
        if self.port:
            argv += ["-p", str(self.port)]
        # User options first so they win over the soft defaults that follow.
        argv += list(self.options)
        argv += list(DEFAULT_OPTIONS)
        argv += [self.target, remote_command]
        return argv

    def _invoke(self, remote_command: str, *, stdin: str) -> RemoteResult:
        try:
            completed = subprocess.run(
                self._argv(remote_command), input=stdin, capture_output=True,
                text=True, timeout=self.timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            return RemoteResult(
                "", "", None, f"ssh timed out after {self.timeout_seconds:g}s")
        except OSError as error:
            return RemoteResult("", "", None, f"failed to run ssh: {error}")
        return RemoteResult(completed.stdout, completed.stderr,
                            completed.returncode, None, ssh_notices(completed.stderr))
