"""The ssh remote wrapper, run without ssh: its stdin stands in for the connection
(ADR-0089 decision 4). Local shells only; nothing here opens a connection.

The wrapper learns where it stands — the leader of its group, as OpenSSH starts a
command, or inside the server's, as Dropbear does — from /proc's stat, or from ps
where there is no /proc. The tests that are about that put a fake of either in front
of the wrapper, as shell functions, so that each case is the one the test names and
not the one this machine happens to give. A fake names its group by ``$$``, the
wrapper's own, or by ``$PPID``, the stand-in server's: a wrong signal can reach
nothing but this test's processes."""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from little_sister.checks.ssh.connection import REMOTE_WRAPPER, _stdin_for
from tests.running import pid_gone

SHELLS = [shell for shell in (["/bin/sh"], ["dash"], ["bash"], ["busybox", "sh"])
          if shutil.which(shell[0])]

#: Whether this machine has a setsid for the wrapper to find; macOS has none.
HAS_SETSID = shutil.which("setsid") is not None


def _proc(group: str) -> str:
    """A /proc whose stat names ``group`` as this shell's, in the form the router's
    printed: the group is the third field after the name."""
    return ("cat() { case $1 in /proc/*/stat) "
            'echo "$$ (sh) S $PPID ' + group + " " + group + ' 0 -1 4194560 136 0";; '
            '*) command cat "$@";; esac; }\n')


def _ps(group: str) -> str:
    """No /proc, and a ps that answers for this shell as macOS's does — only when it
    is asked for this shell's group the way the wrapper asks."""
    return ('cat() { case $1 in /proc/*) return 1;; *) command cat "$@";; esac; }\n'
            'ps() { [ "$*" = "-o pgid= -p $$" ] && echo "  ' + group + '"; }\n')


#: Neither /proc nor ps says anything.
_NOTHING_ANSWERS = ('cat() { case $1 in /proc/*) return 1;; *) command cat "$@";; '
                    "esac; }\n"
                    "ps() { return 1; }\n")

#: A host without setsid, BusyBox's included.
_NO_SETSID = "setsid() { return 127; }\nbusybox() { return 127; }\n"


def _pid_in(marker: Path, seconds: float = 3.0) -> int:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if marker.exists() and marker.read_text().strip():
            return int(marker.read_text())
        time.sleep(0.02)
    raise AssertionError(f"nothing wrote a pid into {marker}")


def _wrapped(shell: list[str], command: str,
             prelude: str = "") -> tuple[list[str], dict[str, str]]:
    """The wrapper run by ``shell``, with ``shell`` as the login shell that runs the
    command — what a server would hand it — and ``prelude`` ahead of it."""
    login = shutil.which(shell[0]) or shell[0]
    if len(shell) > 1:   # busybox's shell is an applet, with no path of its own
        login = "/bin/sh"
    return ([*shell, "-c", prelude + REMOTE_WRAPPER, "little-sister", command],
            {**os.environ, "SHELL": login})


def _start(shell: list[str], command: str, script: str | None = None,
           prelude: str = "") -> subprocess.Popen[bytes]:
    """The wrapper as the leader of its group, the way OpenSSH starts a command, with
    what the client sends ahead of the hang-up line already sent."""
    argv, env = _wrapped(shell, command, prelude)
    run = subprocess.Popen(argv, env=env, stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           start_new_session=True)
    assert run.stdin is not None
    run.stdin.write(_stdin_for(script))
    run.stdin.flush()
    return run


def _inside_a_server(shell: list[str], command: str,
                     prelude: str = "") -> subprocess.Popen[bytes]:
    """The wrapper inside another's group, the way Dropbear starts a command: a shell
    that leads the group runs it and stays behind, as the server would."""
    argv, env = _wrapped(shell, command, prelude)
    inner = " ".join(shlex.quote(word) for word in argv)
    server = subprocess.Popen(["/bin/sh", "-c", f"{inner}; sleep 30"], env=env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, start_new_session=True)
    assert server.stdin is not None
    server.stdin.write(_stdin_for(None))
    server.stdin.flush()
    return server


def _server_survives(server: subprocess.Popen[bytes]) -> bytes:
    """That nothing signaled the server's group, and what the run said on stderr."""
    time.sleep(0.3)
    alive = server.poll() is None
    os.killpg(server.pid, signal.SIGKILL)
    server.wait()
    assert alive, "the wrapper signaled the server's group"
    assert server.stderr is not None
    return server.stderr.read()


def test_the_wrapper_travels_without_comments_indentation_or_single_quotes() -> None:
    """What every run pays for in its command line is the code alone, and no single
    quote that the quoting would turn into five bytes."""
    lines = REMOTE_WRAPPER.splitlines()
    assert lines and all(line and line == line.strip() and not line.startswith("#")
                         for line in lines)
    assert "'" not in REMOTE_WRAPPER


@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_a_hang_up_ends_the_command_and_what_it_started(shell: list[str],
                                                        tmp_path: Path) -> None:
    marker = tmp_path / "pid"
    run = _start(shell, f"sleep 51 & echo $! > {marker}; sleep 52")
    child = _pid_in(marker)
    assert run.stdin is not None
    run.stdin.close()          # the connection goes
    assert pid_gone(child), "the command's child outlived the connection"
    run.wait(5)


@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_a_normal_end_keeps_the_command_s_status_and_streams(shell: list[str],
                                                             tmp_path: Path) -> None:
    marker = tmp_path / "pid"
    started = time.monotonic()
    command = f"echo out; echo err >&2; sleep 53 & echo $! > {marker}; exit 5"
    run = _start(shell, command)
    assert run.stdout is not None and run.stderr is not None and run.stdin is not None
    out = run.stdout.read()      # the connection's stdin stays open until the end
    status = run.wait(10)
    err = run.stderr.read()
    run.stdin.close()
    assert status == 5
    assert (out, err) == (b"out\n", b"err\n")
    assert time.monotonic() - started < 3
    assert pid_gone(_pid_in(marker)), "a background child the command left outlived it"


#: A script with what a line-by-line reading could lose: quotes, a backslash, a line
#: continued by one, a blank line, and lines whose leading and trailing blanks count.
_SCRIPT = ("set -- a 'b c'\n"
           'echo "sees $#: $*"\n'
           "printf '%s\\n' \"quote ' and \\\\ backslash\"\n"
           "echo one \\\n"
           "two\n"
           "\n"
           "cat <<'END'\n"
           "   three blanks\n"
           "\ta tab\n"
           "trailing   \n"
           "END\n"
           "exit 4\n")


@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_a_script_travels_on_stdin_ahead_of_the_hang_up_line(shell: list[str]) -> None:
    """The script arrives as it was sent, and the command runs it while the
    connection is still open: the wrapper reads the script's length and no further."""
    run = _start(shell, "sh -s", _SCRIPT)
    assert run.stdout is not None and run.stdin is not None
    out = run.stdout.read()
    status = run.wait(10)
    run.stdin.close()
    assert status == 4
    assert out == (b"sees 2: a b c\nquote ' and \\ backslash\none two\n"
                   b"   three blanks\n\ta tab\ntrailing   \n")


@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_a_hang_up_after_the_script_still_ends_the_command(shell: list[str],
                                                          tmp_path: Path) -> None:
    """Taking the script leaves the hang-up line where it was, for the watcher."""
    marker = tmp_path / "pid"
    run = _start(shell, "sh -s", f"sleep 51 & echo $! > {marker}\nsleep 52\n")
    child = _pid_in(marker)
    assert run.stdin is not None
    run.stdin.close()
    assert pid_gone(child), "the script's child outlived the connection"
    run.wait(5)


@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_the_command_reads_dev_null_and_never_the_hang_up_line(
        shell: list[str]) -> None:
    """The command's stdin is /dev/null and the connection's stdin is none of its
    descriptors, so it reads to its end at once while the connection stays open."""
    command = ("cat; echo read-to-its-end; "
               "if (: <&3) 2>/dev/null; then echo 3-open; else echo 3-closed; fi")
    run = _start(shell, command)
    assert run.stdout is not None and run.stdin is not None
    out = run.stdout.read()
    run.wait(10)
    run.stdin.close()
    assert out == b"read-to-its-end\n3-closed\n"


@pytest.mark.parametrize("fake", [_proc("$$"), _ps("$$")], ids=["proc", "ps"])
@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_a_shell_that_leads_its_group_keeps_the_command_in_it(
        shell: list[str], fake: str, tmp_path: Path) -> None:
    """Where the wrapper leads its group, as under OpenSSH, the command runs in that
    group, and a hang-up ends it: the command and what it started."""
    own, child = tmp_path / "command", tmp_path / "child"
    run = _start(shell, f"echo $$ > {own}; sleep 51 & echo $! > {child}; exec sleep 52",
                 prelude=fake)
    command = _pid_in(own)
    assert os.getpgid(command) == run.pid, "the command left its wrapper's group"
    assert run.stdin is not None and run.stderr is not None
    run.stdin.close()
    assert pid_gone(command), "the command outlived the connection"
    assert pid_gone(_pid_in(child)), "what the command started outlived the connection"
    run.wait(5)
    assert b"no group" not in run.stderr.read()


@pytest.mark.skipif(not HAS_SETSID, reason="this machine has no setsid")
@pytest.mark.parametrize("fake", [_proc("$PPID"), _ps("$PPID")], ids=["proc", "ps"])
@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_a_shell_inside_the_servers_group_gives_the_command_one_of_its_own(
        shell: list[str], fake: str, tmp_path: Path) -> None:
    """Where the server keeps the wrapper in its own group, as Dropbear does, setsid
    gives the command a group, and a hang-up ends that one — never the server's."""
    own, child = tmp_path / "command", tmp_path / "child"
    server = _inside_a_server(
        shell, f"echo $$ > {own}; sleep 53 & echo $! > {child}; exec sleep 54",
        prelude=fake)
    command = _pid_in(own)
    assert os.getpgid(command) == command, "the command got no group of its own"
    assert server.stdin is not None
    server.stdin.close()
    assert pid_gone(command), "the command outlived the connection"
    assert pid_gone(_pid_in(child)), "what the command started outlived the connection"
    assert b"no group" not in _server_survives(server)


@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_without_setsid_only_the_command_ends_and_the_run_says_so(
        shell: list[str], tmp_path: Path) -> None:
    """Inside the server's group on a host without setsid, the wrapper ends the one
    process it started, says so on the run's stderr, and signals no group at all."""
    own = tmp_path / "command"
    server = _inside_a_server(shell, f"echo $$ > {own}; exec sleep 55",
                              prelude=_proc("$PPID") + _NO_SETSID)
    command = _pid_in(own)
    assert os.getpgid(command) == server.pid, "the command left the server's group"
    assert server.stdin is not None
    server.stdin.close()
    assert pid_gone(command), "the command outlived the connection"
    assert (b"no group of its own and no setsid: only the command ends with the "
            b"connection") in _server_survives(server)


@pytest.mark.skipif(not HAS_SETSID, reason="this machine has no setsid")
@pytest.mark.parametrize("shell", SHELLS, ids=" ".join)
def test_where_nothing_says_the_wrapper_leads_it_counts_on_no_group(
        shell: list[str], tmp_path: Path) -> None:
    """With neither /proc nor ps to ask, the wrapper takes itself to lead nothing: even
    as a leader it gives the command a group of its own rather than signal one it
    cannot see."""
    own, child = tmp_path / "command", tmp_path / "child"
    run = _start(shell, f"echo $$ > {own}; sleep 51 & echo $! > {child}; exec sleep 52",
                 prelude=_NOTHING_ANSWERS)
    command = _pid_in(own)
    assert os.getpgid(command) == command, "the command got no group of its own"
    assert run.stdin is not None
    run.stdin.close()
    assert pid_gone(command), "the command outlived the connection"
    assert pid_gone(_pid_in(child)), "what the command started outlived the connection"
    run.wait(5)
