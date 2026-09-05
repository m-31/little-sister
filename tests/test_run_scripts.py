"""What the run scripts promise, asked of the shell that makes the promise.

Two contracts live here. The **user-list preflight** mirrors the users aspect, so
`start.sh` refuses the same documents the application would. The **TLS half**
(ADR-0067) had no test at all: the scheme and port move together, a certificate is
supplied *or* minted and never both-and-neither, and none of the scripts ever
verifies what they are talking to. Every one of those is a sentence somebody could
quietly reverse in shell, where neither `mypy` nor `ruff` is watching — and one of
them already had been, in a comment claiming a verification the code does not do.

The functions are exercised by sourcing `lib.sh` in a real `bash`, because that is
what the scripts do and because a re-implementation in Python would be a test of the
re-implementation.
"""

import contextlib
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import TestCase, skipUnless

_REPO = Path(__file__).resolve().parents[1]

#: Everything the TLS half reads, cleared before each run so a developer who exported
#: one of them in their own shell cannot change what these tests mean.
_TLS_ENVIRONMENT = (
    "LITTLE_SISTER_TLS", "LITTLE_SISTER_TLS_CERT", "LITTLE_SISTER_TLS_KEY",
    "LITTLE_SISTER_PORT", "LITTLE_SISTER_PROBE_PATH", "TLS", "TLS_CERT", "TLS_KEY",
)


def _bash(script: str, **environment: str) -> subprocess.CompletedProcess[str]:
    """Source `lib.sh` in a real bash and run *script* after it."""
    env = os.environ.copy()
    for name in _TLS_ENVIRONMENT:
        env.pop(name, None)
    env.update(environment)
    return subprocess.run(
        ["bash", "-c", f". ./lib.sh; {script}"],
        cwd=_REPO, env=env, capture_output=True, text=True, timeout=60,
    )


def _mint_into(directory: Path, script: str = "mint_certificate",
               **environment: str) -> subprocess.CompletedProcess[str]:
    """Run *script* with the minted pair redirected out of the repository's `var/`.

    `TLS_DIR` is a plain variable, so pointing it at a temporary directory keeps a
    test from overwriting the certificate a developer's own `./start.sh --tls` is
    serving -- which it would, that being the whole point of overwriting in place.
    """
    return _bash(
        f'TLS_DIR="{directory}"; '
        f'TLS_MINTED_CERT="$TLS_DIR/cert.pem"; TLS_MINTED_KEY="$TLS_DIR/key.pem"; '
        f'{script}',
        **environment,
    )


def _resolve(spec: str,
             retired: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LITTLE_SISTER_CONFIG_DIR"] = spec
    environment.pop("LITTLE_SISTER_USERS", None)
    if retired is not None:
        environment["LITTLE_SISTER_USERS"] = retired
    return subprocess.run(
        ["bash", "-c", ". ./lib.sh; resolve_users_document"],
        cwd=_REPO,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )


class StartScriptUsersTests(TestCase):
    def test_accepts_the_flat_file_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "users.yaml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(document))

    def test_accepts_the_directory_form(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            aspect.mkdir()
            document = aspect / "users.yml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(document))

    def test_the_first_root_declaring_users_wins(self):
        with (tempfile.TemporaryDirectory() as first_directory,
              tempfile.TemporaryDirectory() as second_directory):
            first = Path(first_directory)
            second = Path(second_directory)
            document = second / "users.yaml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(os.pathsep.join((str(first), str(second))))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), str(document))

    def test_refuses_the_retired_override(self):
        """Even when it names the very file the roots would have chosen (ADR-0046)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "users.yaml"
            document.write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root), str(document))

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("no longer read", completed.stderr)

    def test_rejects_a_root_that_is_not_there(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = _resolve(str(Path(directory) / "missing-config"))

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("not found", completed.stderr)

    def test_rejects_both_aspect_forms_in_one_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "users").mkdir()
            (root / "users" / "users.yaml").write_text(
                "pan: {}\n", encoding="utf-8")
            (root / "users.yaml").write_text("pan: {}\n", encoding="utf-8")

            completed = _resolve(str(root))

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("occurs more than once", completed.stderr)

    def test_rejects_a_directory_without_exactly_one_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aspect = root / "users"
            aspect.mkdir()

            missing = _resolve(str(root))
            (aspect / "users.yaml").write_text("pan: {}\n", encoding="utf-8")
            (aspect / "users.yml").write_text("pan: {}\n", encoding="utf-8")
            duplicate = _resolve(str(root))

            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("needs users.yaml or users.yml", missing.stderr)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("contains both", duplicate.stderr)


class SchemeAndPortTests(TestCase):
    """The port moves with the scheme, and the two are one decision (ADR-0067 §2).

    `https://host:8888` and `http://host:8888` would be one address wearing two
    costumes, so what is asserted here is not only that each run resolves *a* port
    but that the two runs resolve **different** ones.
    """

    def _bind(self, flags: str = "", **environment: str) -> tuple[str, str]:
        completed = _bash(f'parse_flags {flags}; resolve_bind; '
                          f'printf "%s %s\\n" "$SCHEME" "$PORT"', **environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        scheme, port = completed.stdout.split()
        return scheme, port

    def test_a_plain_run_is_http_on_the_plain_port(self):
        self.assertEqual(self._bind(), ("http", "8888"))

    def test_the_flag_moves_both_the_scheme_and_the_port(self):
        self.assertEqual(self._bind("--tls"), ("https", "8443"))

    def test_the_two_schemes_never_resolve_to_one_address(self):
        # The sentence §2 is about. A future `instance.sh` that set TLS_PORT to PORT
        # would pass both tests above and lose the whole point of having two.
        self.assertNotEqual(self._bind()[1], self._bind("--tls")[1])

    def test_the_environment_variable_serves_a_script_that_cannot_pass_a_flag(self):
        self.assertEqual(self._bind(LITTLE_SISTER_TLS="1"), ("https", "8443"))

    def test_an_explicit_port_wins_under_either_scheme(self):
        # Somebody naming a port has already answered the question.
        self.assertEqual(self._bind(LITTLE_SISTER_PORT="9001"), ("http", "9001"))
        self.assertEqual(self._bind("--tls", LITTLE_SISTER_PORT="9001"),
                         ("https", "9001"))


class FlagTests(TestCase):
    def test_an_unknown_option_is_refused_and_names_the_one_that_exists(self):
        completed = _bash("parse_flags --tsl")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--tsl", completed.stderr)
        self.assertIn("--tls", completed.stderr)

    def test_help_is_not_an_error(self):
        completed = _bash("parse_flags --help")
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--tls", completed.stderr)
        self.assertIn("--any-instance", completed.stderr)

    def test_the_escape_hatch_is_a_flag_and_not_an_exported_variable(self):
        # Deliberately unlike LITTLE_SISTER_TLS: the value of the refusal is that
        # somebody read it and answered, and a variable exported three days ago
        # answers nothing. An exported one must not decide it either.
        for name in ("ANY_INSTANCE", "LITTLE_SISTER_ANY_INSTANCE"):
            with self.subTest(variable=name):
                completed = _bash('printf "%s\\n" "$ANY_INSTANCE"', **{name: "1"})
                self.assertEqual(completed.stdout.strip(), "0")
        self.assertEqual(
            _bash('parse_flags --any-instance; printf "%s\\n" "$ANY_INSTANCE"'
                  ).stdout.strip(), "1")


class NeverVerifyTests(TestCase):
    """The scripts never verify the certificate, whichever kind it is (ADR-0067 §4).

    This is the sentence that had already gone wrong once: `test_api.sh` claimed a
    *supplied* certificate was verified normally and only a minted one was not, while
    `tls_curl_args` returned `--insecure` for both. A comment cannot be type-checked,
    so the behavior is pinned here instead.
    """

    def _curl_args(self, flags: str = "", **environment: str) -> str:
        completed = _bash(f'parse_flags {flags}; resolve_bind; tls_curl_args',
                          **environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout

    def _argument_count(self, flags: str = "") -> int:
        """How many *arguments* the words become once a caller reads them.

        The count, not the string: `tls_curl_args` echoes words and every caller
        reads them with `read -ra`, because splicing the bare string through
        `${x:+"$x"}` collapses a future second flag into one argument with a space
        in it. Asserting the count is what makes that visible if it ever regresses.
        """
        completed = _bash(f'parse_flags {flags}; resolve_bind; '
                          f'declare -a args; read -ra args <<< "$(tls_curl_args)"; '
                          f'printf "%s\\n" "${{#args[@]}}"')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return int(completed.stdout.strip())

    def test_a_plain_run_asks_curl_for_nothing(self):
        self.assertEqual(self._curl_args(), "")
        self.assertEqual(self._argument_count(), 0)

    def test_the_words_become_one_argument_each(self):
        self.assertEqual(self._argument_count("--tls"), 1)

    def test_a_second_flag_would_reach_curl_as_a_second_argument(self):
        """The reason the callers use `read -ra`, proved rather than reasoned about.

        `tls_curl_args` returns one word today, so the shape it is spliced with makes
        no difference *today* -- which is exactly how a string that collapses two
        flags into one argument survives review. A stub returning two words and a
        `curl` that records its own argv settle it.
        """
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory)
            recorded = fake / "argv"
            (fake / "curl").write_text(
                '#!/usr/bin/env bash\n'
                f'for arg in "$@"; do printf "%s\\n" "$arg" >> "{recorded}"; done\n'
                'printf 200\n',
                encoding="utf-8")
            (fake / "curl").chmod(0o755)

            completed = _bash(
                f'PATH="{fake}:$PATH"; parse_flags --tls; resolve_bind; '
                f'tls_curl_args() {{ printf "%s" "--insecure --second-flag"; }}; '
                f'responds')
            self.assertEqual(completed.returncode, 0, completed.stderr)

            argv = recorded.read_text().splitlines()
            self.assertIn("--insecure", argv)
            self.assertIn("--second-flag", argv)
            self.assertNotIn("--insecure --second-flag", argv,
                             "two flags arrived as one argument")

    def test_a_minted_certificate_is_not_verified(self):
        self.assertEqual(self._curl_args("--tls"), "--insecure")

    def test_a_supplied_certificate_is_not_verified_either(self):
        self.assertEqual(
            self._curl_args("--tls", LITTLE_SISTER_TLS_CERT="/tmp/c.pem",
                            LITTLE_SISTER_TLS_KEY="/tmp/k.pem"),
            "--insecure")

    def test_trust_is_not_even_asked_about_on_a_plain_run(self):
        # `certificate_verifies` reports; it does not gate. Off a TLS run there is
        # nothing to report, and start.sh must not print a warning about it.
        self.assertEqual(_bash("resolve_bind; certificate_verifies").returncode, 0)

    def test_trust_is_not_asked_about_a_minted_certificate(self):
        # Unverifiable by construction, so asking would be theatre.
        self.assertEqual(
            _bash("parse_flags --tls; resolve_bind; certificate_verifies").returncode,
            0)


class ProbeTests(TestCase):
    def test_the_readiness_probe_aims_at_the_liveness_route(self):
        # §6: it used to aim at /login, a login page standing in for a statement
        # about whether the process was serving.
        completed = _bash('printf "%s\\n" "$PROBE_PATH"')
        self.assertEqual(completed.stdout.strip(), "/health")

    def test_a_deployment_can_still_aim_it_somewhere_else(self):
        completed = _bash('printf "%s\\n" "$PROBE_PATH"',
                          LITTLE_SISTER_PROBE_PATH="/ping")
        self.assertEqual(completed.stdout.strip(), "/ping")


class SuppliedCertificateTests(TestCase):
    """Both halves or neither, and used exactly as given (ADR-0067 §3)."""

    def test_a_certificate_without_its_key_is_refused(self):
        completed = _bash("mint_certificate", LITTLE_SISTER_TLS_CERT="/tmp/c.pem")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("both TLS_CERT and TLS_KEY", completed.stderr)

    def test_a_key_without_its_certificate_is_refused(self):
        completed = _bash("mint_certificate", LITTLE_SISTER_TLS_KEY="/tmp/k.pem")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("both TLS_CERT and TLS_KEY", completed.stderr)

    def test_half_a_pair_is_never_quietly_completed_by_minting(self):
        # The refusal above matters because the alternative -- minting the missing
        # half -- would serve a certificate nobody asked for and say nothing.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            completed = _mint_into(target, LITTLE_SISTER_TLS_CERT="/tmp/c.pem")
            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(sorted(p.name for p in target.iterdir()), [])

    def test_an_unreadable_certificate_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as directory:
            absent = Path(directory) / "nowhere.pem"
            completed = _bash("mint_certificate",
                              LITTLE_SISTER_TLS_CERT=str(absent),
                              LITTLE_SISTER_TLS_KEY=str(absent))
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(str(absent), completed.stderr)

    def test_a_supplied_pair_is_echoed_one_path_per_line(self):
        completed = _bash("mint_certificate",
                          LITTLE_SISTER_TLS_CERT=str(_REPO / "README.md"),
                          LITTLE_SISTER_TLS_KEY=str(_REPO / "LICENSE"))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(),
                         [str(_REPO / "README.md"), str(_REPO / "LICENSE")])

    def test_a_path_with_a_space_in_it_reaches_gunicorn_whole(self):
        # The separator has to be the character a path cannot contain by accident.
        # Space-separated, `start.sh`'s read put "Certificates/my" in cert_path and
        # "cert.pem" in key_path, and gunicorn reported a missing file for a pair
        # that was on disk. The read below is the one start.sh performs.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "My Certificates"
            root.mkdir()
            certificate, key = root / "cert.pem", root / "key.pem"
            certificate.write_text("x", encoding="utf-8")
            key.write_text("x", encoding="utf-8")

            completed = _bash(
                'tls_paths="$(mint_certificate)"; '
                '{ IFS= read -r cert_path; IFS= read -r key_path; } <<< "$tls_paths"; '
                'printf "[%s]\\n[%s]\\n" "$cert_path" "$key_path"',
                LITTLE_SISTER_TLS_CERT=str(certificate),
                LITTLE_SISTER_TLS_KEY=str(key))

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.splitlines(),
                             [f"[{certificate}]", f"[{key}]"])


@skipUnless(shutil.which("openssl"), "openssl is required only by a minting TLS start")
class MintedCertificateTests(TestCase):
    """What `--tls` mints when the installation supplies nothing (ADR-0067 §3).

    The mint command was developed against OpenSSL 3, and the LibreSSL that macOS
    ships as `/usr/bin/openssl` was the one place it was expected to be able to
    surprise us. It has now been run against both and **mints the same certificate**:
    P-384, the instance's name, the same file modes. What differs is only how the two
    *print* a subject — OpenSSL 3 renders `CN = little-sister`, LibreSSL
    `CN=little-sister` — so the assertions below read the value out rather than match
    a rendering. That is the difference between testing the certificate and testing
    whichever openssl this machine happens to have, and the first version of this
    file got it wrong in exactly that way.
    """

    def _read(self, path: Path, *arguments: str) -> str:
        return subprocess.run(["openssl", "x509", "-in", str(path), "-noout",
                               *arguments],
                              capture_output=True, text=True, timeout=30).stdout

    def _common_name(self, path: Path) -> str:
        """The certificate's CN, however this machine's openssl spells a subject."""
        subject = self._read(path, "-subject")
        found = re.search(r"CN\s*=\s*([^,/\n]+)", subject)
        self.assertIsNotNone(found, f"no CN in {subject!r}")
        assert found is not None
        return found.group(1).strip()

    def test_the_certificate_beside_it_is_what_the_umask_tightens(self):
        # The umask's only observable effect: a certificate is public material, so
        # this is a floor rather than a secret, and asserting it is how the line
        # stops being a comment nobody can check.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(_mint_into(target).returncode, 0)
            mode = stat.S_IMODE((target / "cert.pem").stat().st_mode)
            self.assertEqual(mode & 0o077, 0, oct(mode))

    def test_it_mints_a_pair_where_it_said_it_would(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            completed = _mint_into(target)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.splitlines(),
                             [str(target / "cert.pem"), str(target / "key.pem")])
            self.assertTrue((target / "cert.pem").exists())
            self.assertTrue((target / "key.pem").exists())

    def test_the_key_is_not_readable_by_anybody_else(self):
        # The property, not its provider: `openssl` writes the key `0600` itself and
        # the `umask 077` beside it turns out to tighten only the certificate. Both
        # were measured. This asserts the outcome anyway, because it is the outcome
        # that matters and a future mint command need not keep openssl's habit.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(_mint_into(target).returncode, 0)
            mode = stat.S_IMODE((target / "key.pem").stat().st_mode)
            self.assertEqual(mode & 0o077, 0, oct(mode))

    def test_it_names_the_instance_rather_than_a_host(self):
        # CN=<instance name>. There is deliberately no subject alternative name:
        # nothing verifies this certificate, and a name nobody checks is decoration.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(_mint_into(target).returncode, 0)
            self.assertEqual(self._common_name(target / "cert.pem"), "little-sister")

    def test_it_is_an_elliptic_curve_key_on_p384(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(_mint_into(target).returncode, 0)
            described = self._read(target / "cert.pem", "-text")
            self.assertIn("id-ecPublicKey", described)
            self.assertIn("secp384r1", described)

    def test_the_directory_it_mints_into_is_made_under_the_umask(self):
        # The umask has to cover the `mkdir` as well as the files, or `var/tls` is
        # created at whatever the developer's shell happens to be set to. Forced to
        # 022 here so the assertion still means something on a machine whose own
        # umask is already tight.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "tls"
            completed = _bash(
                f'umask 022; TLS_DIR="{target}"; '
                f'TLS_MINTED_CERT="$TLS_DIR/cert.pem"; '
                f'TLS_MINTED_KEY="$TLS_DIR/key.pem"; mint_certificate')
            self.assertEqual(completed.returncode, 0, completed.stderr)
            mode = stat.S_IMODE(target.stat().st_mode)
            self.assertEqual(mode & 0o077, 0, oct(mode))

    def test_a_refused_mint_carries_openssls_own_words(self):
        # The failure this command was expected to have one day -- the LibreSSL macOS
        # ships refusing the P-384 flags -- is exactly the one where openssl's message
        # *is* the diagnosis. A bare "could not mint a certificate" would throw the
        # answer away, so the words are captured and printed under it.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "unwritable"
            target.mkdir(mode=0o500)
            try:
                if os.access(target, os.W_OK):
                    self.skipTest("this user can write to a read-only directory")
                completed = _mint_into(target)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("could not mint a certificate", completed.stderr)
                said = [line for line in completed.stderr.splitlines()
                        if line.strip()]
                self.assertGreater(len(said), 1,
                                   f"openssl said nothing the operator can act on: "
                                   f"{completed.stderr!r}")
            finally:
                # Restored inside the block: the temporary directory is removed on
                # the way out of it, well before any addCleanup would run.
                target.chmod(0o700)

    def test_the_next_start_overwrites_it_rather_than_removing_it(self):
        # gunicorn builds its SSL context per accepted connection and reads both
        # files each time, so a mint that cleaned up after itself would serve the
        # first request and fail the second.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.assertEqual(_mint_into(target).returncode, 0)
            first = (target / "cert.pem").read_bytes()
            self.assertEqual(_mint_into(target).returncode, 0)
            second = (target / "cert.pem").read_bytes()
            self.assertTrue((target / "cert.pem").exists())
            self.assertTrue((target / "key.pem").exists())
            self.assertNotEqual(first, second, "the pair was reused, not re-minted")


#: A process that binds a port and waits. `is_ours` recognizes our gunicorn by the
#: *command line* -- `*gunicorn*<APP>*` -- so a listener launched with those two words
#: among its arguments is indistinguishable from the real thing to every function
#: under test here, and needs neither gunicorn nor the application to run.
#:
#: It **double-forks**, which is not incidental: a child of the test process would
#: stay a zombie after `stop.sh` sends it `TERM`, because nothing here reaps it while
#: the script runs -- and `kill -0` succeeds for a zombie, so `stop_master` waited out
#: its entire graceful-stop timeout for a process that had already gone. Re-parenting
#: to init makes the test measure the script rather than the harness (11.3s to 0.3s).
_LISTENER = """
import os, socket, sys, time
ready, where = sys.argv[-1], sys.argv[-2]
os.chdir(where)
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(1)
port = s.getsockname()[1]
if os.fork():
    os._exit(0)
os.setsid()
with open(ready + ".tmp", "w") as handle:
    handle.write("%d %d" % (port, os.getpid()))
os.rename(ready + ".tmp", ready)   # atomic: the file exists only once it is whole
time.sleep(300)
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _free_ports(count: int) -> list[int]:
    """*count* ports nothing is listening on, so a test never fights a real instance.

    Only ever used for a port that must stay **empty**. Handing one of these to a
    process to bind would be a race -- ask the OS for a free port, close it, bind it
    again a moment later and something else may have taken it in between, which loses
    as an unexplained "never bound" rather than as anything a reader can act on.
    :func:`_listening` therefore lets the process that binds choose its own.
    """
    sockets = [socket.socket() for _ in range(count)]
    try:
        for opened in sockets:
            opened.bind(("127.0.0.1", 0))
        return [opened.getsockname()[1] for opened in sockets]
    finally:
        for opened in sockets:
            opened.close()


#: The WSGI target `instance.sh` names. Two checkouts of the family can carry the
#: same one -- which is exactly why the pidfile path, and not this, is what identifies
#: an instance.
_APP = "little_sister.app:app"


def _instance_words(checkout: Path) -> list[str]:
    """The argv words a gunicorn serving *checkout* carries.

    Only the `gunicorn` word decides anything -- `own_instance` asks the process for
    its working directory rather than reading its arguments -- but the rest is here so
    the fake reads like the real command line in a refusal.
    """
    return ["gunicorn", "--pid", str(checkout / "var" / "gunicorn.pid"), _APP]


@contextlib.contextmanager
def _listening(*, checkout: Path | None = None, ours: bool = True,
               words: list[str] | None = None):
    """A listener that looks like a gunicorn serving *checkout* when *ours*.

    It **runs in that directory**, which is what identifies it: the default is this
    repository, so a plain `_listening()` is this checkout's own instance, and passing
    another directory is how a test conjures **another checkout serving the same
    application** -- the case `$APP` could not tell apart.

    Yields ``(port, pid)``: the port because the listener picks its own, and the pid
    so a test can ask whether the script stopped it -- or, for something that is not
    ours, whether it correctly did not.
    """
    where = checkout or _REPO
    marker = words if words is not None else (
        _instance_words(where) if ours else ["something-else"])
    with tempfile.TemporaryDirectory() as scratch:
        ready = Path(scratch) / "bound"
        subprocess.run([sys.executable, "-c", _LISTENER, *marker,
                        str(where), str(ready)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=30)
        # Wait for the bind rather than sleeping a guessed amount: an `lsof` that ran
        # first would make a test pass for the wrong reason.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.02)
        if not ready.exists():                    # pragma: no cover - a stuck bind
            raise AssertionError("the test listener never reported a bound port")
        # Whole by construction: the listener renames it into place, so its existence
        # and its completeness are one event. Polling `exists()` on a file being
        # written would see it empty -- which it did, the first time this was tried
        # by hand outside the suite.
        port, pid = (int(part) for part in ready.read_text().split())
    try:
        yield port, pid
    finally:
        if _alive(pid):
            os.kill(pid, 9)


class OtherPortTests(TestCase):
    """A checkout serves one instance, so the scripts look at both of its ports.

    `PORT` and `TLS_PORT` are set *after* sourcing rather than through
    `LITTLE_SISTER_PORT`, because that variable deliberately collapses the two
    numbers into one -- which is the very thing these tests need two of.
    """

    def _resolve(self, flags: str = "", **environment: str) -> tuple[str, str]:
        completed = _bash(f'parse_flags {flags}; resolve_bind; '
                          f'printf "%s|%s\\n" "$PORT" "$OTHER_PORT"', **environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        port, other = completed.stdout.strip().split("|")
        return port, other

    def _our_port(self, plain: int, tls: int, flags: str = "") -> str:
        completed = _bash(f'PORT={plain}; TLS_PORT={tls}; '
                          f'parse_flags {flags}; resolve_bind; our_port')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def test_a_plain_run_knows_where_a_tls_instance_would_be(self):
        self.assertEqual(self._resolve(), ("8888", "8443"))

    def test_a_tls_run_knows_where_a_plain_instance_would_be(self):
        self.assertEqual(self._resolve("--tls"), ("8443", "8888"))

    def test_resolving_twice_gives_the_same_answer(self):
        # `PORT` is both the input from `instance.sh` and the output, so a second
        # call used to read a TLS run's 8443 back as the plain default and report
        # the two schemes as one address.
        completed = _bash('parse_flags --tls; resolve_bind; resolve_bind; '
                          'printf "%s|%s\n" "$PORT" "$OTHER_PORT"')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "8443|8888")

    def test_an_explicit_port_leaves_no_second_place_to_look(self):
        # It wins under either scheme, so the two schemes resolve to one number and
        # there is no other port -- not the plain default, which is now unused.
        self.assertEqual(self._resolve(LITTLE_SISTER_PORT="9001"), ("9001", ""))
        self.assertEqual(self._resolve("--tls", LITTLE_SISTER_PORT="9001"),
                         ("9001", ""))


@skipUnless(shutil.which("lsof"), "the run scripts find an instance with lsof")
class OurInstanceTests(TestCase):
    """`our_port` answers *where is this checkout's instance*, over both ports."""

    def _our_port(self, plain: int, tls: int, flags: str = "") -> str:
        completed = _bash(f'PORT={plain}; TLS_PORT={tls}; '
                          f'parse_flags {flags}; resolve_bind; our_port')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def test_nothing_of_ours_anywhere_is_answered_with_nothing(self):
        # And answered with *nothing* rather than a non-zero return: the callers
        # assign this under `set -e`, where a failure would abort the script.
        plain, tls = _free_ports(2)
        self.assertEqual(self._our_port(plain, tls), "")

    def test_an_instance_on_this_run_s_own_port_is_found(self):
        with _listening() as (plain, _):
            self.assertEqual(self._our_port(plain, _free_ports(1)[0]), str(plain))

    def test_an_instance_on_the_other_scheme_s_port_is_found(self):
        # The defect this exists for. A plain `./start.sh` used to see nothing on
        # :8888, start a second gunicorn beside the TLS one, and truncate the log the
        # first was still writing to; a plain `./stop.sh` used to report "not
        # running" and then delete the running instance's pidfile.
        with _listening() as (tls, _):
            self.assertEqual(self._our_port(_free_ports(1)[0], tls), str(tls))
        with _listening() as (plain, _):
            self.assertEqual(self._our_port(plain, _free_ports(1)[0], "--tls"),
                             str(plain))

    def test_this_run_s_port_is_preferred_when_both_are_serving(self):
        # It should not happen once a start replaces what it finds, but if it does,
        # the one this run would have bound is the one to report.
        with _listening() as (plain, _), _listening() as (tls, _):
            self.assertEqual(self._our_port(plain, tls), str(plain))
            self.assertEqual(self._our_port(plain, tls, "--tls"), str(tls))

    def test_another_checkout_serving_the_same_application_is_not_ours(self):
        # The reason ownership moved off `$APP`. Both checkouts serve
        # `little_sister.app:app`; only the absolute pidfile path tells them apart,
        # and without it these scripts would have stopped each other's instance.
        with tempfile.TemporaryDirectory() as elsewhere:
            with _listening(checkout=Path(elsewhere)) as (port, _):
                self.assertEqual(self._our_port(port, _free_ports(1)[0]), "")

    def test_the_flag_takes_another_checkout_s_instance_deliberately(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            with _listening(checkout=Path(elsewhere)) as (port, _):
                self.assertEqual(
                    self._our_port(port, _free_ports(1)[0], "--any-instance"),
                    str(port))

    def test_the_flag_still_does_not_reach_something_that_is_not_an_instance(self):
        # It relaxes ownership as far as "a gunicorn" and no further: a refusal
        # naming somebody's database is worth keeping, and no flag relaxes it.
        with _listening(ours=False) as (port, _):
            self.assertEqual(
                self._our_port(port, _free_ports(1)[0], "--any-instance"), "")

    def test_ownership_survives_gunicorn_rewriting_its_command_line(self):
        """The reason ownership is not read out of the command line.

        With `setproctitle` installed -- which nothing here installs today and any
        deployment may -- gunicorn replaces its own argv with
        `gunicorn: master [<app>]`, and the `--pid` path is simply gone. macOS `ps`
        does the same damage by truncating. Either one would turn ownership into a
        silent "not running" for an instance that is serving, so this pins that the
        answer comes from the process rather than from the string.
        """
        with _listening(words=["gunicorn:", "master", "[wsgi:app]"]) as (port, _):
            self.assertEqual(self._our_port(port, _free_ports(1)[0]), str(port))

    def test_a_stranger_is_never_adopted_on_either_port(self):
        # The whole reason `is_ours` exists: the scripts must never stop, or claim
        # to be, a service that merely happens to sit on one of these numbers.
        with _listening(ours=False) as (plain, _), \
                _listening(ours=False) as (tls, _):
            self.assertEqual(self._our_port(plain, tls), "")
            self.assertEqual(self._our_port(plain, tls, "--tls"), "")

    def test_an_explicit_port_stops_the_search_at_that_one_port(self):
        # With LITTLE_SISTER_PORT there is no other port, so an instance on the
        # default TLS number is deliberately not this run's business.
        plain = _free_ports(1)[0]
        with _listening() as (tls, _):
            completed = _bash(f'PORT={plain}; TLS_PORT={tls}; '
                              f'parse_flags; resolve_bind; our_port',
                              LITTLE_SISTER_PORT=str(plain))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "")


@skipUnless(shutil.which("lsof"), "stop.sh finds an instance with lsof")
class StopScriptTests(TestCase):
    """`./stop.sh` end to end, against an instance it is not told the scheme of.

    The scripts are run out of a temporary directory holding `stop.sh`, `lib.sh` and
    an `instance.sh` naming two free ports -- which is the whole of what `stop.sh`
    reads, because `instance.sh` is the one file among them that differs per
    installation. That is what lets this drive the real script without gunicorn, the
    application, or the two numbers a developer's own instance is using.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        for script in ("stop.sh", "lib.sh"):
            shutil.copy(_REPO / script, root / script)
        (root / "stop.sh").chmod(0o755)
        (root / "var").mkdir()
        self.root = root
        self.pidfile = root / "var" / "gunicorn.pid"
        self.plain, self.tls = _free_ports(2)
        self._install(self.plain, self.tls)

    def _install(self, plain: int, tls: int) -> None:
        """Write the `instance.sh` this run is about to read.

        Called after any listener has bound, because a listener picks its own port --
        so the two numbers are known only once it is up.
        """
        self.plain, self.tls = plain, tls
        (self.root / "instance.sh").write_text(
            'NAME="little-sister"\n'
            f"PORT={plain}\n"
            f"TLS_PORT={tls}\n"
            'APP="little_sister.app:app"\n',
            encoding="utf-8")

    def _stop(self, *flags: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        for name in _TLS_ENVIRONMENT:
            env.pop(name, None)
        return subprocess.run(["./stop.sh", *flags], cwd=self.root, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_it_stops_a_tls_instance_without_being_told_it_is_one(self):
        # The defect, end to end. `./stop.sh` with no flag used to look at the plain
        # port, announce "not running", and then delete this instance's pidfile
        # while it went on serving.
        self.pidfile.write_text("1\n", encoding="utf-8")
        with _listening(checkout=self.root) as (tls, pid):
            self._install(_free_ports(1)[0], tls)
            completed = self._stop()
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("stopped", completed.stdout)
            self.assertNotIn("not running", completed.stdout)
            self.assertFalse(_alive(pid), "the instance was left running")
        self.assertFalse(self.pidfile.exists())

    def test_it_says_which_port_it_found_the_instance_on(self):
        # Not cosmetic: somebody who typed `./stop.sh` and gets "stopped" deserves
        # to know it stopped something that was not on the port they had in mind.
        with _listening(checkout=self.root) as (tls, _):
            self._install(_free_ports(1)[0], tls)
            completed = self._stop()
        self.assertIn(str(tls), completed.stdout)

    def test_the_flag_is_accepted_and_changes_nothing_about_what_is_found(self):
        # `--tls` is vestigial here now, and saying so in a test is how it stays
        # true: the instance is found from either direction.
        with _listening(checkout=self.root) as (plain, pid):
            self._install(plain, _free_ports(1)[0])
            completed = self._stop("--tls")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(_alive(pid), "the instance was left running")

    def test_nothing_running_clears_a_stale_pidfile_and_is_not_an_error(self):
        self.pidfile.write_text("999999\n", encoding="utf-8")
        completed = self._stop()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("not running", completed.stdout)
        self.assertFalse(self.pidfile.exists())

    def test_it_names_both_ports_when_it_found_nothing(self):
        completed = self._stop()
        self.assertIn(str(self.plain), completed.stdout)
        self.assertIn(str(self.tls), completed.stdout)

    def test_a_stranger_on_our_port_is_refused_rather_than_reported_absent(self):
        self.pidfile.write_text("999999\n", encoding="utf-8")
        with _listening(ours=False) as (plain, pid):
            self._install(plain, _free_ports(1)[0])
            completed = self._stop()
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("refusing to stop it", completed.stderr)
            self.assertTrue(_alive(pid), "it stopped somebody else's process")
        # And it left the pidfile alone, having established nothing about ours.
        self.assertTrue(self.pidfile.exists())

    def test_another_checkout_on_our_port_is_refused_and_the_flag_is_named(self):
        # The collision this exists for: two checkouts of the same application on one
        # port. It refuses, says what is in the way, and says what to do about it.
        elsewhere = self.root.parent / "other-checkout"
        elsewhere.mkdir(exist_ok=True)
        with _listening(checkout=elsewhere) as (plain, pid):
            self._install(plain, _free_ports(1)[0])
            completed = self._stop()
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("refusing to stop it", completed.stderr)
            self.assertIn("--any-instance", completed.stderr)
            self.assertTrue(_alive(pid), "it stopped another checkout's instance")

    def test_the_flag_stops_it_and_says_that_is_what_happened(self):
        elsewhere = self.root.parent / "other-checkout"
        elsewhere.mkdir(exist_ok=True)
        with _listening(checkout=elsewhere) as (plain, pid):
            self._install(plain, _free_ports(1)[0])
            completed = self._stop("--any-instance")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("did not start", completed.stdout)
            self.assertFalse(_alive(pid), "the instance was left running")

    def test_a_stranger_on_the_other_port_is_simply_not_ours(self):
        # We are not going to bind that port and nothing of ours is on it, so there
        # is nothing to refuse over -- only nothing to do.
        with _listening(ours=False) as (tls, pid):
            self._install(_free_ports(1)[0], tls)
            completed = self._stop()
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("not running", completed.stdout)
            self.assertTrue(_alive(pid), "it stopped somebody else's process")
