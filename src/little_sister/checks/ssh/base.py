"""Shared bases for the SSH check family.

:class:`SshCheckBase` parses the connection block every SSH check shares and turns
it into an :class:`SshConnection`; :class:`SshScriptCheck` adds piping a bundled
script to the host. The connectivity / command / script / metrics checks build on
these. Output interpretation lives here too: ``_connection_failure`` (when ssh
itself couldn't deliver output) and ``_output_result`` (a command's captured
output as a single leaf), both shared so the family behaves consistently.
"""
from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path
from typing import Any

from little_sister.checks.base import Check, CheckError, CheckResult, code, plain
from little_sister.checks.ssh.metrics import oneline, strip_ssh_notices
from little_sister.checks.ssh.transport import RemoteResult, SshConnection
from little_sister.status import StatusCode

DEFAULT_MAX_CHARS = 1000

# The generic measurement scripts ship inside the package (ADR-0021); a built-in
# check's default script is resolved from here unless overridden or shadowed.
_PACKAGED_SCRIPTS = Path(str(files("little_sister"))) / "scripts"


class SshCheckBase(Check):
    """Base for every SSH check: owns the shared connection block.

    Parses ``host`` / ``user`` / ``port`` / ``sudo`` / ``identity_file`` /
    ``options`` / ``debug`` and exposes them as an :class:`SshConnection`.
    ``BatchMode`` is forced (non-interactive, key-based auth; host key already
    known); ``sudo: true`` runs the remote command under ``sudo -n``.
    """

    def __init__(self, *, host: str, user: str | None = None,
                 port: int | None = None, sudo: bool = False,
                 identity_file: str | None = None, debug: bool = False,
                 options: tuple[str, ...] = (), **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.host = host
        self.user = user
        self.port = port
        self.sudo = sudo
        self.identity_file = identity_file
        self.debug = debug
        self.options = options

    @classmethod
    def _base_connection_config(cls, config: dict[str, Any]) -> dict[str, Any]:
        """Parse the connection fields every SSH check shares."""
        host = config.get("host")
        if not host:
            raise CheckError(f"{cls.type_name} check requires a 'host'")
        identity = config.get("identity_file")
        options = config.get("options", [])
        if not isinstance(options, list):
            raise CheckError("'options' must be a list of ssh arguments")
        return {
            "host": str(host),
            "user": str(config["user"]) if config.get("user") else None,
            "port": int(config["port"]) if config.get("port") else None,
            "sudo": bool(config.get("sudo", False)),
            "identity_file": (str(Path(str(identity)).expanduser())
                              if identity else None),
            "debug": bool(config.get("debug", False)),
            "options": tuple(str(option) for option in options),
        }

    @property
    def connection(self) -> SshConnection:
        """The transport for this check, built from its connection fields."""
        return SshConnection(
            host=self.host, user=self.user, port=self.port, sudo=self.sudo,
            identity_file=self.identity_file, options=self.options,
            timeout_seconds=self.timeout_seconds)

    @property
    def _target(self) -> str:
        return self.connection.target

    def _connection_fields(self) -> dict[str, str | None]:
        """The connection params to surface on a detail page — host / user / port,
        no secrets (ADR-0013). Shared by the leaf SSH checks and the
        ``host-metrics`` ``ssh`` leaf; optional fields stay ``None`` and are
        dropped by :func:`config_markdown`."""
        return {
            "host": self.host,
            "user": self.user,
            "port": str(self.port) if self.port else None,
        }

    def _connection_failure(self, result: RemoteResult) -> str | None:
        """A reason when ssh couldn't deliver usable output — a dead transport
        (timeout / spawn) or a non-zero exit — else ``None``. The advisory banner
        is stripped so it doesn't crowd out the real error."""
        if result.error is not None:
            return result.error
        if result.exit_code != 0:
            detail = oneline(strip_ssh_notices(result.stderr)
                             or result.stdout) or "no output"
            return (f"ssh to {self._target} failed "
                    f"(exit {result.exit_code}): {detail}")
        return None

    def _debug_reason(self, result: RemoteResult,
                      metrics: dict[str, str] | None = None) -> list[str]:
        """When ``debug`` is set, extra reason lines exposing the raw (unstripped)
        ssh stderr, the exit code and any ``debug_*`` lines a script emitted — so a
        missing warning or odd metric can be diagnosed from the dashboard."""
        if not self.debug:
            return []
        if result.exit_code is None:
            return ["debug: ssh did not complete (timeout or spawn failure)"]
        lines = [f"debug: exit={result.exit_code}",
                 f"debug stderr: {plain(oneline(result.stderr, 800)) or '(empty)'}"]
        lines += [f"debug {plain(key)}: {plain(value)}"
                  for key, value in sorted((metrics or {}).items())
                  if key.startswith("debug")]
        return lines

    def _output_result(self, result: RemoteResult, *, capture: str,
                       max_chars: int, keep: str) -> CheckResult:
        """A command/script outcome as a single leaf: OK on exit 0 (reason = the
        captured output), ERROR otherwise. A successful run still **WARN**s when ssh
        flagged an advisory (e.g. a non-post-quantum key exchange)."""
        if result.error is not None:
            return CheckResult(StatusCode.ERROR, [plain(result.error)])
        # The captured remote output is untrusted — fence it (ADR-0018).
        captured = _shorten(_capture(result, capture), max_chars, keep)
        if result.exit_code == 0:
            reasons = [code(captured)] if captured else []
            if result.notice:
                return CheckResult(StatusCode.WARN, [*reasons, plain(result.notice)])
            return CheckResult(StatusCode.OK, reasons)
        detail = (code(captured) if captured
                  else plain(oneline(result.stderr)) or f"exit code {result.exit_code}")
        return CheckResult(StatusCode.ERROR, [detail])


class SshScriptCheck(SshCheckBase):
    """Base for checks that pipe a bundled script to a host over SSH.

    Adds the ``script_path`` piped to the host's shell via ``interpreter``.
    Subclasses add their own config and parse the script's ``key=value`` stdout (the
    metrics checks) or return its raw output (``ssh-script``).
    """

    def __init__(self, *, script_path: str, interpreter: str = "bash",
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.script_path = script_path
        self.interpreter = interpreter

    @classmethod
    def _connection_from_config(cls, config: dict[str, Any], base_dir: Path,
                                default_script: str) -> dict[str, Any]:
        """The shared connection block plus the resolved ``script_path`` (ADR-0021).

        An explicit ``script:`` resolves relative to the config file's own
        directory (absolute / ``~`` paths as given). A built-in check's *default*
        script is looked up on a search path — ``LITTLE_SISTER_SCRIPTS_DIR``, then
        the config's own directory (shadowing), then the scripts bundled in the
        package — first hit wins.
        """
        explicit = config.get("script")
        if explicit is not None:
            script = Path(str(explicit)).expanduser()
            if not script.is_absolute():
                script = base_dir / script
            if not script.is_file():
                raise CheckError(
                    f"{cls.type_name} check script not found: {script}")
            resolved = script
        else:
            found = _find_default_script(base_dir, default_script)
            if found is None:
                raise CheckError(
                    f"{cls.type_name} check default script "
                    f"{default_script!r} not found")
            resolved = found
        return {
            **cls._base_connection_config(config),
            "script_path": str(resolved),
        }

    def _script_args(self) -> list[str]:
        """Positional args for the remote script, before the ``debug`` flag."""
        return []

    def _run(self) -> RemoteResult:
        """Pipe the script to the host, appending the ``debug`` flag when set."""
        args = list(self._script_args())
        if self.debug:
            args.append("debug")
        return self.connection.run_script(self.script_path, self.interpreter, args)


def _capture(result: RemoteResult, which: str) -> str:
    if which == "stdout":
        text = result.stdout
    elif which == "stderr":
        text = result.stderr
    else:
        text = (result.stdout or "") + (result.stderr or "")
    return text.strip()


def _shorten(text: str, max_chars: int, keep: str) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] if keep == "head" else text[-max_chars:]


def _find_default_script(base_dir: Path, name: str) -> Path | None:
    """Locate a built-in check's default script (ADR-0021): search the override
    directory (``LITTLE_SISTER_SCRIPTS_DIR``), then the config's own directory (a
    same-named file shadows the bundled one), then the packaged scripts. The first
    existing file wins; ``None`` if it is nowhere."""
    search: list[Path] = []
    override = os.environ.get("LITTLE_SISTER_SCRIPTS_DIR")
    if override:
        search.append(Path(override).expanduser())
    search.append(base_dir)
    search.append(_PACKAGED_SCRIPTS)
    for directory in search:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def parse_descriptions(raw: Any) -> dict[str, str]:
    """Parse a branch check's optional ``descriptions:`` map — a leaf name (``disk``,
    ``temperature``, …) to its Markdown description (ADR-0012). Shared by the metrics
    checks; the shared container node's own description stays empty."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CheckError("'descriptions' must be a mapping of leaf name to text")
    return {str(name): str(text) for name, text in raw.items()}


def parse_output_config(config: dict[str, Any]) -> dict[str, Any]:
    """Parse the ``capture`` / ``max_chars`` / ``keep`` output options shared by
    ``ssh-command`` and ``ssh-script`` (mirroring the local ``command`` check)."""
    capture = str(config.get("capture", "stdout")).lower()
    if capture not in ("stdout", "stderr", "both"):
        raise CheckError(f"invalid 'capture': {capture!r} (stdout|stderr|both)")
    keep = str(config.get("keep", "tail")).lower()
    if keep not in ("tail", "head"):
        raise CheckError(f"invalid 'keep': {keep!r} (tail|head)")
    return {
        "capture": capture,
        "max_chars": int(config.get("max_chars", DEFAULT_MAX_CHARS)),
        "keep": keep,
    }
