"""What this installation registers before the app — `wsgi.py` (ADR-0069 §5).

This repository serves its own `wsgi.py` now, like every other installation in the
family, and the file exists to do one thing: register the system-admin account
*before* `little_sister.app` is imported. Nothing in the ordinary suite can hold that
claim, because the suite imports the application directly; so these run the real
sequence in a subprocess, from a directory `setup.sh` has just prepared.

The end-to-end one is `test_a_fresh_setup_serves_a_viewer_login_and_an_admin_door`,
and it is the whole of the slice in one assertion pass: after `./setup.sh`, the
everyday login is `viewer` and is **not** an admin, while the admin of the install is
`admin` behind `/login/system-admin`, with a generated password nobody has to type
twice a day.

It also pins the ordering trap it found. `.env` used to be read while
`little_sister.app` was being imported, which is in time for everything the app reads
and **too late for a registration** — `wsgi.py` resolves `env://…` before that import,
so the account's credential would have been reported as unresolvable on every real
start, in the one place a shut door is least likely to be noticed. The load moved to
`little_sister.secrets`, and the second test below is what says so.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

_REPO = Path(__file__).resolve().parents[1]

#: Enough configuration to start: a `checks` aspect is the one thing that is fatal
#: without (ADR-0031). Everything else this test cares about, `setup.sh` writes.
_CHECK = "name: one\ntype: http\nurl: http://localhost:1/\nfrequency: 1h\n"

#: Run the real entrypoint, then ask the questions through the app it built.
_PROBE = """
import wsgi

from little_sister import identity, system_admin

app = wsgi.app
app.config["TESTING"] = True
client = app.test_client()

account = system_admin.registered()
print("CONFIGURED", account is not None)
print("AVAILABLE", account is not None and account.available)
print("KEYWORD", account.keyword if account else "-")
print("DEFAULT-DOOR", (identity.default_door() or "-") and identity.default_door().name)
print("ADMIN-FORM", client.get("/login/system-admin").status_code)
print("LOGIN-FORM", client.get("/login").status_code)

with open(".env", encoding="utf-8") as handle:
    password = next(line.split("=", 1)[1].strip().strip('"')
                    for line in handle
                    if line.startswith("LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD="))
signed_in = client.post("/login/system-admin",
                        data={"username": "admin", "password": password})
print("ADMIN-LOGIN", signed_in.status_code, signed_in.headers.get("Location"))
print("ADMIN-PAGE", client.get("/system").status_code)
client.get("/logout")

viewer = client.post("/login", data={"username": "viewer",
                                     "password": "change-me"})
print("VIEWER-LOGIN", viewer.status_code, viewer.headers.get("Location"))
print("VIEWER-SEES-EVENTS", client.get("/events").status_code)
print("VIEWER-SEES-SYSTEM", client.get("/system").status_code)
"""


class _Case(TestCase):
    def _installation(self, directory: str) -> Path:
        """A checkout-shaped directory: this repository's entrypoint and setup
        script, and a configuration root with the one aspect that is required."""
        root = Path(directory)
        shutil.copy(_REPO / "wsgi.py", root / "wsgi.py")
        shutil.copy(_REPO / "setup.sh", root / "setup.sh")
        (root / "config" / "checks").mkdir(parents=True)
        (root / "config" / "checks" / "one.yaml").write_text(_CHECK,
                                                             encoding="utf-8")
        return root

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["LITTLE_SISTER_CONFIG_DIR"] = "config"
        # The point of the exercise: everything this installation needs comes from
        # the `.env` `setup.sh` wrote, so the process is given none of it.
        for name in ("SECRET_KEY", "LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD",
                     "LITTLE_SISTER_API_TOKENS", "LITTLE_SISTER_USERS"):
            environment.pop(name, None)
        return environment

    def _setup(self, root: Path) -> subprocess.CompletedProcess:
        return subprocess.run(["./setup.sh"], cwd=root, env=self._environment(),
                              capture_output=True, text=True, timeout=120)

    def _probe(self, root: Path, script: str = _PROBE) -> dict[str, str]:
        done = subprocess.run([sys.executable, "-c", script], cwd=root,
                              env=self._environment(), capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, f"{done.stdout}\n{done.stderr}")
        return {line.split(" ", 1)[0]: line.split(" ", 1)[1]
                for line in done.stdout.splitlines() if " " in line}


class FreshInstallTests(_Case):
    def test_a_fresh_setup_serves_a_viewer_login_and_an_admin_door(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._installation(directory)
            written = self._setup(root)
            self.assertEqual(written.returncode, 0, written.stderr)
            answers = self._probe(root)

        # The powerful account has real entropy and lives behind its own door…
        self.assertEqual(answers["CONFIGURED"], "True")
        self.assertEqual(answers["AVAILABLE"], "True")
        self.assertEqual(answers["KEYWORD"], "reference")
        self.assertEqual(answers["ADMIN-FORM"], "200")
        self.assertEqual(answers["ADMIN-LOGIN"], "302 /status")
        self.assertEqual(answers["ADMIN-PAGE"], "200")

        # …and the everyday one is the weak editable placeholder, which is not an
        # admin: it reaches the dashboard and is refused the admin page.
        self.assertEqual(answers["DEFAULT-DOOR"], "local")
        self.assertEqual(answers["LOGIN-FORM"], "200")
        self.assertEqual(answers["VIEWER-LOGIN"], "302 /status")
        self.assertEqual(answers["VIEWER-SEES-EVENTS"], "200")
        self.assertEqual(answers["VIEWER-SEES-SYSTEM"], "403")

    def test_the_env_file_is_read_before_the_registration_resolves(self):
        # The trap this file was written to catch: `wsgi.py` resolves `env://…`
        # *before* `little_sister.app` is imported, so a `.env` read during that
        # import would arrive after the only reader of it.
        with tempfile.TemporaryDirectory() as directory:
            root = self._installation(directory)
            self._setup(root)
            answers = self._probe(root, """
import os
print("PRESENT-BEFORE-IMPORT",
      "LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD" in os.environ)
import wsgi  # noqa: F401
print("PRESENT-AFTER-IMPORT",
      "LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD" in os.environ)
from little_sister import system_admin
account = system_admin.registered()
print("AVAILABLE", account is not None and account.available)
""")
        self.assertEqual(answers["PRESENT-BEFORE-IMPORT"], "False")
        self.assertEqual(answers["PRESENT-AFTER-IMPORT"], "True")
        self.assertEqual(answers["AVAILABLE"], "True")

    def test_an_installation_that_never_ran_setup_still_starts(self):
        # A fresh checkout has no `.env`, so the account's credential does not
        # resolve — that door is shut and the application serves anyway, which is
        # the whole of ADR-0069's *keeps serving* rule met on the first day.
        with tempfile.TemporaryDirectory() as directory:
            root = self._installation(directory)
            (root / "config" / "users").mkdir(parents=True)
            (root / "config" / "users" / "users.yaml").write_text(
                'viewer:\n  firstname: "V"\n  lastname: "R"\n'
                '  password: "change-me"\n', encoding="utf-8")
            answers = self._probe(root, """
import wsgi

from little_sister import system_admin

app = wsgi.app
app.config["TESTING"] = True
client = app.test_client()
account = system_admin.registered()
print("CONFIGURED", account is not None)
print("AVAILABLE", account is not None and account.available)
print("ADMIN-FORM", client.get("/login/system-admin").status_code)
print("LOGIN-FORM", client.get("/login").status_code)
print("HEALTH", client.get("/health").status_code)
""")
        self.assertEqual(answers["CONFIGURED"], "True")
        self.assertEqual(answers["AVAILABLE"], "False")
        self.assertEqual(answers["ADMIN-FORM"], "404")
        self.assertEqual(answers["LOGIN-FORM"], "200")
        self.assertEqual(answers["HEALTH"], "200")


class SetupScriptTests(_Case):
    """What `setup.sh` does to an `.env` that is already there, and what it does
    when it cannot generate a password at all.

    Both are about one account. The script mints the credential of the most powerful
    login in the application, so *silently produced something weak* and *silently
    produced nothing* are the two ways it can be wrong, and neither announces itself.
    """

    #: Enough externals for the script to run with `python3` and `openssl` absent
    #: from `PATH`. Resolved at run time rather than assumed at `/bin`, since this
    #: suite runs in a container and on a Mac.
    NEEDED = ("bash", "sh", "dirname", "mkdir", "cat", "grep", "tr", "cut", "rm")

    def _run(self, root: Path, answer: str = "n",
             environment: dict[str, str] | None = None):
        return subprocess.run(["./setup.sh"], cwd=root,
                              env=environment or self._environment(),
                              input=answer + "\n", capture_output=True, text=True,
                              timeout=120)

    def _key(self, written: str) -> str:
        return next(line.split("=", 1)[1].strip().strip('"')
                    for line in written.splitlines()
                    if line.startswith("LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD="))

    def test_an_existing_env_gains_the_one_key_it_is_missing(self):
        # The upgrade path every installation in this family takes: an `.env` written
        # before the system-admin account existed. Answering "no" to the overwrite
        # prompt used to leave that door registered and shut, which is a state nobody
        # discovers until the morning it is needed.
        with tempfile.TemporaryDirectory() as directory:
            root = self._installation(directory)
            (root / ".env").write_text('SECRET_KEY="keep-me"\n'
                                       'LITTLE_SISTER_API_TOKENS="client=mine"\n',
                                       encoding="utf-8")
            done = self._run(root)
            written = (root / ".env").read_text(encoding="utf-8")
        self.assertEqual(done.returncode, 0, done.stderr)
        # The line arrived, with a real password rather than a placeholder…
        password = self._key(written)
        self.assertGreater(len(password), 20)
        self.assertNotEqual(password, "change-me")
        # …and nothing the deployment had is disturbed. Regenerating the signing key
        # would have ended every open session; the tokens are its own.
        self.assertIn('SECRET_KEY="keep-me"', written)
        self.assertIn('LITTLE_SISTER_API_TOKENS="client=mine"', written)

    def test_an_env_that_already_has_the_key_is_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._installation(directory)
            before = ('SECRET_KEY="keep-me"\n'
                      'LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD="already-here"\n')
            (root / ".env").write_text(before, encoding="utf-8")
            self._run(root)
            after = (root / ".env").read_text(encoding="utf-8")
        self.assertEqual(after, before)

    def test_with_no_way_to_generate_a_password_it_refuses(self):
        # It used to fall back to the constant `change-me` while still printing
        # "random", which hands the most powerful account a well-known password.
        with tempfile.TemporaryDirectory() as directory:
            root = self._installation(directory)
            binaries = Path(directory) / "bin"
            binaries.mkdir()
            for name in self.NEEDED:
                found = shutil.which(name)
                if found:
                    (binaries / name).symlink_to(found)
            environment = self._environment()
            environment["PATH"] = str(binaries)
            done = self._run(root, environment=environment)
            wrote_anything = (root / ".env").exists()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("need python3 or openssl", done.stderr)
        self.assertFalse(wrote_anything)


class EntrypointTests(TestCase):
    """The file itself, read as text: what `instance.sh` serves and what `mypy`
    covers are claims about `wsgi.py` that no import can make."""

    def test_the_run_scripts_serve_this_entrypoint(self):
        instance = (_REPO / "instance.sh").read_text(encoding="utf-8")
        self.assertIn('APP="wsgi:app"', instance)

    def test_mypy_is_pointed_at_it_by_name(self):
        # `files = ["src"]` would type-check everything except the one file that
        # carries the registration order.
        pyproject = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('files = ["src", "wsgi.py"]', pyproject)

    def test_the_password_is_named_and_never_carried(self):
        source = (_REPO / "wsgi.py").read_text(encoding="utf-8")
        self.assertIn(
            'use_system_admin(reference="env://LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD")',
            source)
        self.assertNotIn("password=", source)


if __name__ == "__main__":
    unittest.main()
