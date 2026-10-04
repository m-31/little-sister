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
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from little_sister import values
from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    Measurement,
    code,
    plain,
)
from little_sister.checks.output import (
    captured_output,
    output_reading,
    output_record_bytes,
)
from little_sister.checks.ssh.connection import RemoteResult, SshConnection
from little_sister.checks.ssh.metrics import oneline, strip_ssh_notices
from little_sister.reasons import clip
from little_sister.status import StatusCode

#: What the free-text fields of an SSH record are clipped to — **characters
#: first, then bytes** (:func:`~little_sister.reasons.clip`), because a record is
#: weighed as `json.dumps` writes it and a German or Japanese error message costs
#: six bytes a character there. Clipping in bytes as well is what makes the
#: declaration below a ceiling that can never be exceeded, so the seam cannot
#: refuse a reading at runtime.
TRANSPORT_TEXT_CHARS = 300
TRANSPORT_TEXT_BYTES = 320
NOTICE_CHARS = 200
NOTICE_BYTES = 220

#: How much of ssh's stderr a **debug** run keeps in its record, so the
#: ``debug stderr:`` line can be rebuilt from the reading rather than from a
#: `RemoteResult` the grading is not allowed to see (ADR-0086). It was 800
#: characters while it lived only in a reason; a record is kept per reading and
#: shares its 2 KB with whatever else the check read — a host's volumes — so the
#: diagnostic line is the thing that gives way, not the measurement.
DEBUG_STDERR_CHARS = 300
DEBUG_STDERR_BYTES = 320

#: What one transport half is expected — and guaranteed — to need, in the bytes
#: the seam counts: the keys and syntax (~64), an `exit_code` (~20), the longer of
#: `error` and `detail` (never both), and a `notice`. A **debug** run adds its
#: clipped stderr and that key.
TRANSPORT_RECORD_BYTES = 64 + 20 + TRANSPORT_TEXT_BYTES + NOTICE_BYTES
DEBUG_RECORD_BYTES = 16 + DEBUG_STDERR_BYTES

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
        # The **host** is the object every check in this family reads, whichever
        # of them it is: `/hosts/nas/system` measures `nas01`. Not `user@host:port`
        # — that is how we got there, and a login moved to another account is the
        # same machine — and not the node's path, which is the deployment's label.
        # Two methods on one host are still two series, because a series is keyed
        # by the check as well as the object.
        super().__init__(subject=host, **kwargs)
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

    def _transport_record(self, result: RemoteResult) -> dict[str, Any]:
        """How the connection itself went, as the part of a record every check in
        this family reads (ADR-0086).

        It is the measurement's half of what ``_connection_failure`` below used to
        read off a live :class:`RemoteResult`: the grading never sees one, because
        a `RemoteResult` is the check's working state and is gone by the time a
        series is graded again. So what the sentences need is kept, and nothing
        else — the raw stdout stays inside the check.

        ``exit_code`` is always there and stands as ``None`` when ssh never
        completed, which is the null-not-absent rule (ADR-0085 decision 3). The
        three that follow are present **only where there was one**, because a null
        reason on every healthy reading would lengthen every record for nothing:
        ``error`` where the transport died, ``detail`` where it answered with a
        non-zero exit, ``notice`` where ssh flagged an advisory. The advisory
        banner is stripped out of ``detail`` so it does not crowd out the real
        error.
        """
        record: dict[str, Any] = {"exit_code": result.exit_code}
        if result.error is not None:
            record["error"] = clip(result.error, chars=TRANSPORT_TEXT_CHARS,
                                   budget=TRANSPORT_TEXT_BYTES)
        elif result.exit_code != 0:
            # What the host said about the failure, and **only where it said
            # something**: *no output* is a sentence a grading writes when the
            # record is silent, not a reading. Storing it would make "the host
            # printed nothing" indistinguishable from "the host printed the words
            # no output", and would hide the `exit code N` fallback a command
            # check falls back to.
            detail = oneline(strip_ssh_notices(result.stderr) or result.stdout)
            if detail:
                record["detail"] = clip(detail, chars=TRANSPORT_TEXT_CHARS,
                                        budget=TRANSPORT_TEXT_BYTES)
        if result.notice:
            record["notice"] = clip(result.notice, chars=NOTICE_CHARS,
                                    budget=NOTICE_BYTES)
        if self.debug:
            record["ssh_stderr"] = clip(
                oneline(result.stderr, DEBUG_STDERR_CHARS),
                chars=DEBUG_STDERR_CHARS, budget=DEBUG_STDERR_BYTES)
        return record

    def _transport_record_bytes(self) -> int:
        """What the transport half of one record needs, in the JSON it is measured
        in (ADR-0075) — a **ceiling that cannot be exceeded**, because every
        free-text field above is clipped in the same bytes this counts.

        That is worth stating, because ADR-0075 asks for an estimate of a normal
        run and not a bound: a type declaring its `timeout_seconds` there would
        refuse deployments that work. The difference is the clip. A bound nothing
        enforces is a guess about the worst case and is pessimistic; a bound the
        measurement enforces is the exact answer, and declaring anything smaller
        would be declaring a number the check itself can beat.

        Shared, because every check in this family carries that half and none of
        them should have to re-derive the same number (F28)."""
        return TRANSPORT_RECORD_BYTES + (
            DEBUG_RECORD_BYTES if self.debug else 0)

    def _say_it_failed(self, record: dict[str, Any], stdout: str, *,
                       readable: bool, nothing: str) -> None:
        """Say in the record's ``error`` that this reading did not measure — the key
        a curve marks a failed reading by (ADR-0096 decision 4) — in the sentence
        the grading has always written for it: the connection's own error where it
        died, the script's failure where it exited non-zero, and ``nothing`` from
        the host where it answered with nothing this type can read.

        For a metrics type only: a command's exit code is the command's reading, not
        its failure. The detail the sentence carries is not kept beside it as well,
        so a failed reading weighs what it always did (ADR-0075). A profile the host
        refused is no failed reading: it answered, and the grading's ``WARN`` says
        why."""
        if record.get("error") is not None:
            return
        exit_code = record.get("exit_code")
        if exit_code != 0:
            detail = record.pop("detail", None) or "no output"
            sentence = f"ssh to {self._target} failed (exit {exit_code}): {detail}"
        elif not readable and not record.get("profile_error"):
            said = oneline(stdout) or "empty output"
            sentence = f"{nothing} from {self._target}: {said}"
        else:
            return
        record["error"] = clip(sentence, chars=TRANSPORT_TEXT_CHARS,
                               budget=TRANSPORT_TEXT_BYTES)

    def _connection_failure(self, record: Mapping[str, Any]) -> str | None:
        """A reason when ssh couldn't deliver usable output — a dead transport
        (timeout / spawn) or a non-zero exit — else ``None``. Read out of the
        record, so the same sentence comes back from a reading this process did
        not take."""
        error = record.get("error")
        if error is not None:
            return str(error)
        exit_code = record.get("exit_code")
        if exit_code != 0:
            detail = str(record.get("detail") or "no output")
            return f"ssh to {self._target} failed (exit {exit_code}): {detail}"
        return None

    def _debug_lines(self, record: Mapping[str, Any]) -> list[str]:
        """When ``debug`` is set, extra reason lines exposing the raw (unstripped)
        ssh stderr, the exit code and any ``debug_*`` lines a script emitted — so a
        missing warning or odd metric can be diagnosed from the dashboard.

        Rebuilt from the record rather than from the run, like every other line
        this family writes. The stderr rides under ``ssh_stderr`` and not under a
        ``debug`` name, so a script that emits a ``debug_*`` key of its own can
        never collide with it."""
        if not self.debug:
            return []
        if record.get("exit_code") is None:
            return ["debug: ssh did not complete (timeout or spawn failure)"]
        stderr = plain(str(record.get("ssh_stderr") or ""))
        lines = [f"debug: exit={record['exit_code']}",
                 f"debug stderr: {stderr or '(empty)'}"]
        lines += [f"debug {plain(key)}: {plain(str(value))}"
                  for key, value in sorted(record.items())
                  if key.startswith("debug")]
        return lines

    def _output_measurement(self, result: RemoteResult, *, capture: str,
                            max_chars: int, keep: str) -> Measurement:
        """A command/script run, as a reading: how the connection went, plus the
        captured output clipped **once** — to ``max_chars``, then into the byte
        budget a record has (`checks/output.py` says why the second bound is in
        bytes, and why one clip rather than two).

        The output stands as ``None`` where ssh never delivered any, so every
        reading of one of these checks has the same shape."""
        record = self._transport_record(result)
        record["output"] = (
            None if result.error is not None
            else captured_output(result.stdout, result.stderr, capture=capture,
                                 max_chars=max_chars, keep=keep))
        return Measurement(record=record)

    def _output_result(self, record: Mapping[str, Any]) -> CheckResult:
        """A command/script outcome as a single leaf: OK on exit 0 (reason = the
        captured output), ERROR otherwise. A successful run still **WARN**s when ssh
        flagged an advisory (e.g. a non-post-quantum key exchange).

        Read out of the record, so the same sentence comes back from a reading
        this process did not take."""
        exit_code, output, failure = output_reading(record)
        if failure:
            return CheckResult(StatusCode.ERROR, [plain(failure)])
        # The captured remote output is untrusted — fence it (ADR-0018).
        if exit_code == 0:
            reasons = [code(output)] if output else []
            notice = record.get("notice")
            if notice:
                return CheckResult(StatusCode.WARN,
                                   [*reasons, plain(str(notice))])
            return CheckResult(StatusCode.OK, reasons)
        detail = (code(output) if output
                  else plain(str(record.get("detail") or ""))
                  or f"exit code {exit_code}")
        return CheckResult(StatusCode.ERROR, [detail])

    def _output_record_bytes(self, max_chars: int) -> int:
        """The transport half and the captured output together — a ceiling that
        cannot be exceeded, because both halves are clipped in these same bytes
        (ADR-0075)."""
        return self._transport_record_bytes() + output_record_bytes(max_chars)


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
    capture = values.text(config, "capture", default="stdout").lower()
    if capture not in ("stdout", "stderr", "both"):
        raise CheckError(f"invalid 'capture': {capture!r} (stdout|stderr|both)")
    keep = values.text(config, "keep", default="tail").lower()
    if keep not in ("tail", "head"):
        raise CheckError(f"invalid 'keep': {keep!r} (tail|head)")
    return {
        "capture": capture,
        "max_chars": values.number(config, "max_chars",
                                   default=DEFAULT_MAX_CHARS),
        "keep": keep,
    }
