"""The SSH connection: a value object that runs commands and scripts over ``ssh``.

Named for what it holds rather than for the layer it sits in. It was ``transport.py``
until ADR-0058 gave that word to :mod:`little_sister.transport`, the vocabulary a
check uses to bound and classify a request — two modules called `transport`, meaning
different things, is how divergence starts.

:class:`SshConnection` carries one host's connection parameters and is the single
place they become an ``ssh`` argv (``BatchMode`` forced — non-interactive,
key-based auth, host key already known; the legacy SHA-1 ``ssh-rsa`` algorithm off
by default). It can run a remote command (``run``) or hand a local script to the
host's shell (``run_script``); each returns a :class:`RemoteResult`.

**A remote command ends with its connection** (ADR-0089). The command is run by a
small POSIX wrapper, ``remote-wrapper.sh`` beside this file, sent as the remote
command itself: it keeps the connection's stdin as a hang-up line and ends the
command's group when the connection closes — at the run's bound, at the instance's
stop — and whatever the command left behind at a normal end. The client runs through
:func:`little_sister.process.run` with that stdin held open, so its own group ends
with the run too. A script travels on the same stdin, ahead of the hang-up line: a
line with its length in lines, then the script, which begins with a ``set --`` that
gives it its arguments. The command line carries the wrapper and the command and
nothing else, so a command the library builds stays within the 1,024 bytes even
Dropbear 2012.55 takes (ADR-0089 decision 4), however long its script.

The transport reports **facts**, not verdicts: it sets ``error`` only when ssh
could not run at all (a timeout, a spawn failure, an unreadable script), leaving a
completed run — whatever its exit code — for the *check* to interpret. ``notice``
carries any ssh advisory banner (e.g. a non-post-quantum key exchange) for a check
to surface as WARN.
"""
from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from little_sister import process
from little_sister.checks.base import DEFAULT_TIMEOUT_SECONDS
from little_sister.checks.ssh.metrics import ssh_notices

DEFAULT_CONNECT_TIMEOUT = 10

# Turn the legacy SHA-1 RSA algorithm off by default for every host (modern
# rsa-sha2-256/512 keys are unaffected). Applied as a command-line `-o` *after*
# the user's own ``options`` so a host that still needs it can override with
# ``options: ["-o", "PubkeyAcceptedAlgorithms=+ssh-rsa"]`` (ssh uses the first
# value it sees for each option).
DEFAULT_OPTIONS = ("-o", "PubkeyAcceptedAlgorithms=-ssh-rsa")

def _wrapper() -> str:
    """The remote wrapper as it is sent: the file beside this module without its
    comments and its indentation, which are for a reader and cost every run bytes."""
    text = Path(__file__).with_name("remote-wrapper.sh").read_text(encoding="utf-8")
    return "\n".join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.lstrip().startswith("#")) + "\n"


#: The remote wrapper, as it travels.
REMOTE_WRAPPER = _wrapper()


def _stdin_for(script: str | None) -> bytes:
    """What a run sends ahead of the hang-up line: a line with the script's length in
    lines, then the script, its last line ended — or ``0`` alone, with no script."""
    if script is None:
        return b"0\n"
    if not script.endswith("\n"):
        script += "\n"
    lines = script.count("\n")
    return f"{lines}\n{script}".encode()


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
        """Run a remote command (the host's login shell runs it, through the
        wrapper); its stdin is ``/dev/null``. ``sudo -n`` is prepended when set."""
        remote = f"sudo -n {command}" if self.sudo else command
        return self._invoke(remote)

    def run_script(self, script_path: str, interpreter: str,
                   args: Sequence[str] = ()) -> RemoteResult:
        """Run a local script with the host's ``interpreter``, which reads it from
        its stdin (``<interpreter> -s``); ``args`` become the script's positional
        arguments. The script travels on the connection's stdin, ahead of the
        hang-up line, and the wrapper pipes it to the interpreter; ``args`` travel
        with it, as a ``set --`` ahead of its first line, so that the command line
        is the same whatever they are. Returns a failed :class:`RemoteResult` if the
        script is unreadable, the ssh spawn fails or it times out."""
        try:
            script = Path(script_path).read_text(encoding="utf-8")
        except OSError as error:
            return RemoteResult("", "", None, f"cannot read script: {error}")
        arguments = " ".join(["set", "--", *(shlex.quote(arg) for arg in args)])
        parts = [interpreter, "-s"]
        if self.sudo:
            parts = ["sudo", "-n", *parts]
        remote = " ".join(shlex.quote(part) for part in parts)
        return self._invoke(remote, script=f"{arguments}\n{script}")

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

    def _invoke(self, remote_command: str, *,
                script: str | None = None) -> RemoteResult:
        words = ["exec", "sh", "-c", REMOTE_WRAPPER, "little-sister", remote_command]
        wrapped = " ".join(shlex.quote(word) for word in words)
        try:
            done = process.run(self._argv(wrapped), timeout=self.timeout_seconds,
                               send=_stdin_for(script), hang_up=True)
        except process.NotStarted as error:
            return RemoteResult("", "", None,
                                f"failed to run ssh: {error.__cause__ or error}")
        if done.ended is process.Ended.BOUND:
            return RemoteResult(
                "", "", None, f"ssh timed out after {self.timeout_seconds:g}s")
        if done.ended is process.Ended.STOP:
            return RemoteResult("", "", None, "ssh was ended by the instance's stop")
        stdout = done.stdout.decode("utf-8", "replace")
        stderr = done.stderr.decode("utf-8", "replace")
        return RemoteResult(stdout, stderr, done.status, None, ssh_notices(stderr))
