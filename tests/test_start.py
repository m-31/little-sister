"""The server's start makes an imported application an instance, and nothing else
does (ADR-0091).

Each test runs a child interpreter in a directory of its own, because what is asserted
is what a process does to its working directory: an import that writes nothing, a
start that takes the state directory's lease before anything else and opens the log
with what the import logged, a start the lease refuses that touches nothing, and a stop
that lets go of what the start took. This suite's own interpreter imported the
application long ago and is never started.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from little_sister.lease import Lease
from tests.running import subprocess_env

#: A mark for a holder the test stands in for; the child must name it.
HOLDER = "beside:4242:20260926T000000Z:0b5e55ed"


def _child(directory: Path, script: str,
           **environment: str) -> subprocess.CompletedProcess[str]:
    """Run ``script`` in a fresh interpreter in ``directory``, with this suite's
    configuration roots and the default log file — ``var/little-sister.log`` of that
    directory — so that whatever the child writes is there to be seen."""
    env = subprocess_env()
    env.pop("LOG_FILE", None)
    env.pop("LITTLE_SISTER_ENGINE", None)
    env.update(environment)
    return subprocess.run([sys.executable, "-c", textwrap.dedent(script)],
                          cwd=directory, env=env, capture_output=True, text=True,
                          timeout=60)


def _last_json(done: subprocess.CompletedProcess[str]) -> dict[str, object]:
    lines = done.stdout.strip().splitlines()
    assert lines, f"the child printed nothing; its stderr:\n{done.stderr[-3000:]}"
    answer = json.loads(lines[-1])
    assert isinstance(answer, dict)
    return answer


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_an_import_writes_nothing_into_its_directory(self) -> None:
        done = _child(self.directory, """
            import json
            import little_sister.app as app
            print(json.dumps({"engine": app.engine is None, "lease": app.lease is None,
                              "error": app.engine_error == app.NOT_STARTED}))
        """)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(_last_json(done),
                         {"engine": True, "lease": True, "error": True})
        self.assertEqual(sorted(self.directory.iterdir()), [],
                         "an import is not an instance: no var/, no log, no lease")

    def test_what_an_import_logs_goes_to_stderr(self) -> None:
        done = _child(self.directory, "import little_sister.app")
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertIn("csp: Content-Security-Policy-Report-Only", done.stderr)

    def test_a_literal_setting_is_read_at_the_import(self) -> None:
        done = _child(self.directory, """
            import json
            import little_sister.app as app
            print(json.dumps({"key": app.app.secret_key, "tokens": app.api_tokens}))
        """, SECRET_KEY="lit3ral", LITTLE_SISTER_API_TOKENS="tester=t0ken")
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(_last_json(done),
                         {"key": "lit3ral", "tokens": {"tester": "t0ken"}})

    def test_a_malformed_reference_still_refuses_at_the_import(self) -> None:
        # A typo in a scheme reaches nothing, so the import still says so rather
        # than leaving it for a start that may come much later (ADR-0023).
        done = _child(self.directory, "import little_sister.app",
                      SECRET_KEY="nope://app/session-key")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("UnknownSchemeError", done.stderr)
        self.assertIn("'nope'", done.stderr)

    def test_a_reference_resolves_at_the_start_and_not_at_the_import(self) -> None:
        done = _child(self.directory, """
            import json
            from little_sister import secrets
            asked = []
            def fake(address):
                asked.append(address)
                return {"key": "k3y", "tokens": "tester=t0ken"}[address]
            secrets.register_resolver("fake", fake)
            import little_sister.app as app
            def said():
                print(json.dumps({"asked": sorted(asked),
                                  "key": app.app.secret_key == "k3y",
                                  "tokens": app.api_tokens}))
            said()
            app.start()
            said()
            app.stop(trigger="the test")
        """, SECRET_KEY="fake://key", LITTLE_SISTER_API_TOKENS="fake://tokens",
            LITTLE_SISTER_ENGINE="0")
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        at_import, at_start = (json.loads(line)
                               for line in done.stdout.strip().splitlines()[-2:])
        self.assertEqual(at_import, {"asked": [], "key": False, "tokens": {}})
        self.assertEqual(at_start, {"asked": ["key", "tokens"], "key": True,
                                    "tokens": {"tester": "t0ken"}})


class StartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.var = self.directory / "var"

    def _log(self) -> list[str]:
        return (self.var / "little-sister.log").read_text(encoding="utf-8").splitlines()

    def _lease(self) -> dict[str, object]:
        body = json.loads((self.var / "state.lease").read_text(encoding="utf-8"))
        assert isinstance(body, dict)
        return body

    def test_the_start_takes_the_lease_opens_the_log_and_starts_the_engine(
            self) -> None:
        done = _child(self.directory, """
            import json
            import little_sister.app as app
            app.start()
            first = app.engine
            app.start()
            print(json.dumps({"engine": first is not None,
                              "again": app.engine is first,
                              "error": app.engine_error,
                              "lease": app.lease is not None}))
            app.stop(trigger="the test")
            app.stop(trigger="the test, again")
        """)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(_last_json(done), {"engine": True, "again": True,
                                            "error": None, "lease": True})
        log = self._log()
        # The log begins with what the import logged, then the start's own lines.
        imported = next(i for i, line in enumerate(log)
                        if "csp: Content-Security-Policy-Report-Only" in line)
        took = next(i for i, line in enumerate(log) if "state: took the lease" in line)
        # How the lease was taken, in words that cannot be read as a release.
        self.assertIn("from a free directory", log[took])
        started = next(i for i, line in enumerate(log) if "engine: started" in line)
        self.assertLess(imported, took)
        self.assertLess(took, started)
        # One start and one stop, however often they were reached.
        self.assertEqual(sum("engine: started" in line for line in log), 1)
        stopped = [line for line in log if "engine: stopped" in line]
        self.assertEqual(len(stopped), 1, stopped)
        self.assertIn("reached by the test;", stopped[0])
        # The stop's one save let go of the lease.
        self.assertEqual(self._lease()["state"], "released")

    def test_a_start_the_lease_refuses_names_the_holder_and_touches_nothing(
            self) -> None:
        holder = Lease(self.var / "state", mark=HOLDER, host="elsewhere", pid=4242)
        holder.take()
        try:
            done = _child(self.directory, """
                import json
                import little_sister.app as app
                from little_sister.lease import LeaseRefused
                try:
                    app.start()
                except LeaseRefused as refused:
                    print(json.dumps({"refused": str(refused), "engine": app.engine,
                                      "lease": app.lease is None}))
            """)
        finally:
            holder.release()
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        answer = _last_json(done)
        self.assertIn(f"{HOLDER} on elsewhere, pid 4242", str(answer["refused"]))
        self.assertEqual((answer["engine"], answer["lease"]), (None, True))
        # Said on stderr, since the log file is not a refused process's to open…
        errors = [line for line in done.stderr.splitlines() if " - ERROR - " in line]
        self.assertTrue(any(HOLDER in line and "start:" in line for line in errors),
                        done.stderr[-3000:])
        # …and nothing in the directory is touched: no log, no state, no claim.
        self.assertFalse((self.var / "little-sister.log").exists())
        self.assertFalse((self.var / "state").exists())
        self.assertEqual(sorted(path.name for path in self.var.iterdir()),
                         ["state.lease", "state.lock"])
        self.assertEqual(self._lease()["mark"], HOLDER)

    def test_a_restart_is_recorded_once_on_the_instances_own_node(self) -> None:
        # ADR-0094: the first run beats and stops, and its one save stamps the stop;
        # the second restores the log, closes /little-sister's period when the first
        # was last alive, and its first beat is a transition from there
        first = _child(self.directory, """
            import json, time
            import little_sister.app as app
            from little_sister.status import HEARTBEAT_PATH
            from little_sister.tree import status_tree
            app.start()
            for _ in range(200):
                if status_tree.history(HEARTBEAT_PATH):
                    break
                time.sleep(0.05)
            beat = bool(status_tree.history(HEARTBEAT_PATH))
            app.stop(trigger="the test")
            print(json.dumps({"beat": beat}))
        """)
        self.assertEqual(first.returncode, 0, first.stderr[-3000:])
        self.assertEqual(_last_json(first), {"beat": True})
        saved = json.loads((self.var / "state" / "events.json").read_text(
            encoding="utf-8"))
        stopped = saved["stopped_at"]
        second = _child(self.directory, """
            import json, time
            import little_sister.app as app
            from little_sister.status import HEARTBEAT_PATH
            from little_sister.tree import status_tree
            app.start()
            for _ in range(200):
                if len(status_tree.history(HEARTBEAT_PATH)) >= 3:
                    break
                time.sleep(0.05)
            periods = [[period.code.name, period.since, period.until,
                        list(period.reason)]
                       for period in status_tree.history(HEARTBEAT_PATH)]
            app.stop(trigger="the test")
            print(json.dumps({"periods": periods}))
        """)
        self.assertEqual(second.returncode, 0, second.stderr[-3000:])
        periods = _last_json(second)["periods"]
        assert isinstance(periods, list)
        self.assertEqual([period[0] for period in periods],
                         ["OK", "UNDEFINED", "OK"])
        running, down, again = periods
        # the gap opens when the first process was last alive — its stop's stamp or
        # its lease's release, whichever is later — and closes at the first beat
        self.assertGreaterEqual(down[1], stopped)
        self.assertEqual(running[2], down[1])
        self.assertEqual(down[2], again[1])
        self.assertEqual(down[3], ["the instance was not running"])

    def test_a_server_without_an_engine_takes_no_lease(self) -> None:
        done = _child(self.directory, """
            import json
            import little_sister.app as app
            app.start()
            print(json.dumps({"engine": app.engine, "error": app.engine_error,
                              "lease": app.lease is None}))
            app.stop(trigger="the test")
        """, LITTLE_SISTER_ENGINE="0")
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(_last_json(done),
                         {"engine": None, "error": None, "lease": True})
        self.assertFalse((self.var / "state.lease").exists())
        self.assertTrue(any("engine disabled via LITTLE_SISTER_ENGINE" in line
                            for line in self._log()))

    def test_a_configuration_that_does_not_load_serves_with_its_reason(self) -> None:
        checks = self.directory / "conf" / "checks"
        checks.mkdir(parents=True)
        (checks / "web.yaml").write_text(
            "type: htttp\npath: /web\nfrequency: 1m\n", encoding="utf-8")
        roots = subprocess_env()["LITTLE_SISTER_CONFIG_DIR"]
        done = _child(self.directory, """
            import json
            import little_sister.app as app
            app.start()
            print(json.dumps({"engine": app.engine, "error": app.engine_error,
                              "lease": app.lease is not None}))
            app.stop(trigger="the test")
        """, LITTLE_SISTER_CONFIG_DIR=os.pathsep.join((roots, str(checks.parent))))
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        answer = _last_json(done)
        self.assertIsNone(answer["engine"])
        self.assertIn("htttp", str(answer["error"]))
        # It is still the instance: it held the directory, and let go at the stop.
        self.assertTrue(answer["lease"])
        self.assertEqual(self._lease()["state"], "released")
        self.assertTrue(any("engine not started:" in line for line in self._log()))


if __name__ == "__main__":
    unittest.main()
