"""gunicorn's hooks for a little-sister application: the start right after the worker's
import, and the stop when the worker leaves (ADR-0091, ADR-0088 decision 5).

The first half asks the module itself — what it calls, what it never imports, what
gunicorn reads from it. The second serves the real application under a real gunicorn
in a directory of its own, because the claims that matter are about that pairing: the
engine starts after the import and before anything is served, it stops at
``worker_exit`` with its one save, and a start the lease refuses halts the server with
the holder named.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from gunicorn.config import Config

from little_sister import gunicorn_hooks
from little_sister.lease import Lease
from tests.running import subprocess_env

APPLICATION = "little_sister.app"
HOLDER = "beside:4242:20260926T000000Z:0b5e55ed"


class HookTests(unittest.TestCase):
    def _application(self) -> types.SimpleNamespace:
        return types.SimpleNamespace(start=mock.Mock(), stop=mock.Mock())

    def test_post_worker_init_starts_the_application_the_worker_imported(
            self) -> None:
        application = self._application()
        with mock.patch.dict(sys.modules, {APPLICATION: application}):
            gunicorn_hooks.post_worker_init(mock.Mock())
        application.start.assert_called_once_with()
        application.stop.assert_not_called()

    def test_worker_exit_stops_it_and_names_itself_as_the_trigger(self) -> None:
        application = self._application()
        with mock.patch.dict(sys.modules, {APPLICATION: application}):
            gunicorn_hooks.worker_exit(mock.Mock(), mock.Mock())
        application.stop.assert_called_once_with(trigger="worker_exit")
        application.start.assert_not_called()

    def test_a_worker_that_never_imported_it_imports_nothing(self) -> None:
        # A worker whose import failed runs worker_exit on its way out; starting an
        # instance there would be the one thing worse than the failure.
        with mock.patch.dict(sys.modules):
            sys.modules.pop(APPLICATION, None)
            gunicorn_hooks.post_worker_init(mock.Mock())
            gunicorn_hooks.worker_exit(mock.Mock(), mock.Mock())
            self.assertNotIn(APPLICATION, sys.modules)

    def test_loading_the_module_does_not_import_the_application(self) -> None:
        # gunicorn loads it in the master, where an import of the application would
        # be an instance.
        done = subprocess.run(
            [sys.executable, "-c",
             "import sys, little_sister.gunicorn_hooks; "
             f"print({APPLICATION!r} in sys.modules)"],
            env=subprocess_env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.strip(), "False", done.stderr[-3000:])

    def test_gunicorn_reads_the_two_hooks_and_nothing_else(self) -> None:
        # What `--config python:little_sister.gunicorn_hooks` sets, read the way
        # gunicorn reads it: every name the module has that is a setting. A setting
        # arriving here by accident would change every server that loads it, out of
        # sight of its command line.
        config = Config()
        read = {name: value for name, value in vars(gunicorn_hooks).items()
                if name in config.settings}
        self.assertEqual(sorted(read), ["post_worker_init", "worker_exit"])
        for name, value in read.items():
            config.set(name, value)       # gunicorn checks each hook's arity here
        self.assertIs(config.post_worker_init, gunicorn_hooks.post_worker_init)
        self.assertIs(config.worker_exit, gunicorn_hooks.worker_exit)


class ServedTests(unittest.TestCase):
    """The real application under a real gunicorn, loaded with the hooks module."""

    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.var = self.directory / "var"
        self.output = self.directory / "gunicorn.log"

    @contextlib.contextmanager
    def _gunicorn(self) -> Iterator[subprocess.Popen[bytes]]:
        env = subprocess_env()
        env.pop("LOG_FILE", None)
        env.pop("LITTLE_SISTER_ENGINE", None)
        with self.output.open("wb") as output:
            server = subprocess.Popen(
                [sys.executable, "-m", "gunicorn", "--workers", "1", "--threads", "2",
                 "--keep-alive", "0", "--graceful-timeout", "10",
                 "--config", "python:little_sister.gunicorn_hooks",
                 "--bind", "127.0.0.1:0", f"{APPLICATION}:app"],
                cwd=self.directory, env=env, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True)
        try:
            yield server
        finally:
            if server.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(server.pid, signal.SIGKILL)
            server.wait(timeout=10)

    def _said(self) -> str:
        return self.output.read_text(encoding="utf-8", errors="replace")

    def _port(self, server: subprocess.Popen[bytes]) -> int:
        end = time.monotonic() + 30
        while time.monotonic() < end and server.poll() is None:
            found = re.search(r"Listening at: http://127\.0\.0\.1:(\d+)", self._said())
            if found:
                return int(found.group(1))
            time.sleep(0.05)
        self.fail(f"gunicorn did not listen:\n{self._said()[-3000:]}")

    def _health(self, port: int) -> dict[str, object]:
        end = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health",
                                            timeout=5) as response:
                    answer = json.loads(response.read())
                    assert isinstance(answer, dict)
                    return answer
            except OSError:
                if time.monotonic() > end:
                    raise
                time.sleep(0.1)

    def _log(self) -> str:
        return (self.var / "little-sister.log").read_text(encoding="utf-8")

    def test_the_worker_starts_the_engine_and_stops_it_when_it_leaves(self) -> None:
        with self._gunicorn() as server:
            port = self._port(server)
            # The start ran before the worker served anything: the first answer
            # already has a running engine behind it.
            self.assertEqual(self._health(port)["engine"], "running")
            lease = json.loads((self.var / "state.lease").read_text(encoding="utf-8"))
            self.assertEqual(lease["state"], "held")
            server.send_signal(signal.SIGTERM)
            self.assertEqual(server.wait(timeout=30), 0, self._said()[-3000:])
        stopped = [line for line in self._log().splitlines()
                   if "engine: stopped" in line]
        self.assertEqual(len(stopped), 1, self._log()[-3000:])
        self.assertIn("reached by worker_exit;", stopped[0])
        lease = json.loads((self.var / "state.lease").read_text(encoding="utf-8"))
        self.assertEqual(lease["state"], "released")

    def test_a_start_the_lease_refuses_halts_the_server_naming_the_holder(
            self) -> None:
        holder = Lease(self.var / "state", mark=HOLDER, host="elsewhere", pid=4242)
        holder.take()
        try:
            with self._gunicorn() as server:
                code = server.wait(timeout=60)
        finally:
            holder.release()
        said = self._said()
        self.assertNotEqual(code, 0, said[-3000:])
        self.assertIn("Worker failed to boot", said)
        self.assertIn(f"{HOLDER} on elsewhere, pid 4242", said)
        # A refused process touched nothing in the directory it does not hold.
        self.assertFalse((self.var / "little-sister.log").exists())
        self.assertFalse((self.var / "state").exists())


if __name__ == "__main__":
    unittest.main()
