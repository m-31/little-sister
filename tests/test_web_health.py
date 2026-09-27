"""``/health`` answers *should traffic go here*, and says almost nothing (ADR-0066).

Two claims are worth a test each and neither is about the happy path. The first is
that a **failed engine still answers 200** — a probe that took the instance out of
service over a bad check config would remove the dashboard whose banner explains it.
The second is that the route **discloses nothing**: it has no login gate, so every
field on it is readable by whatever can reach the port, and the test that matters is
the one asserting the whole set of keys rather than the presence of the two wanted.
"""
import json
import os
import unittest
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module


class HealthTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _health(self):
        response = self.client.get("/health")
        return response, json.loads(response.get_data(as_text=True))

    def test_it_answers_without_a_session_or_a_token(self):
        response, _ = self._health()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")

    def test_it_says_exactly_two_things(self):
        # The whole key set, not the presence of the two wanted: this route is
        # unauthenticated, so a field added here is a field published to whoever can
        # reach the port. A version, a config path or an error message arriving by
        # accident has to fail here.
        _, payload = self._health()
        self.assertEqual(set(payload), {"status", "engine"})

    def test_it_is_not_cached(self):
        response, _ = self._health()
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_a_running_engine_is_reported_running(self):
        with mock.patch.object(app_module, "engine", object()):
            _, payload = self._health()
        self.assertEqual(payload["engine"], "running")

    def test_an_engine_switched_off_is_disabled_not_failed(self):
        # A server started with LITTLE_SISTER_ENGINE=0 got what it asked for, and
        # must not read as broken (ADR-0091 decision 7).
        with mock.patch.object(app_module, "engine", None), \
                mock.patch.object(app_module, "engine_error", None):
            _, payload = self._health()
        self.assertEqual(payload["engine"], "disabled")

    def test_an_engine_that_could_not_load_its_config_is_failed(self):
        with mock.patch.object(app_module, "engine", None), \
                mock.patch.object(app_module, "engine_error", "boom"):
            response, payload = self._health()
        self.assertEqual(payload["engine"], "failed")
        self.assertEqual(response.status_code, 200,
                         "a failed engine must not take the instance out of service")

    def test_a_server_that_never_started_the_engine_is_failed_and_still_200(self):
        # A gunicorn line without the hooks module serves the application and never
        # starts it (ADR-0091 decision 5). A liveness probe that restarts on failure
        # must meet a live instance there, never a restart loop (decision 6).
        with mock.patch.object(app_module, "engine", None), \
                mock.patch.object(app_module, "engine_error", app_module.NOT_STARTED):
            response, payload = self._health()
        self.assertEqual(payload["engine"], "failed")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("gunicorn_hooks", response.get_data(as_text=True))

    def test_an_imported_application_that_was_never_started_says_so(self):
        # This suite imports the application and never starts it, which is the
        # state every test here begins in unless it says otherwise.
        self.assertIsNone(app_module.engine)
        self.assertEqual(app_module.engine_error, app_module.NOT_STARTED)
        self.assertIn("--config python:little_sister.gunicorn_hooks",
                      app_module.NOT_STARTED)

    def test_the_reason_an_engine_failed_is_never_in_the_body(self):
        secret = "/srv/deploy/config/checks/payments.yaml: no such key 'ap1_url'"
        with mock.patch.object(app_module, "engine", None), \
                mock.patch.object(app_module, "engine_error", secret):
            response, payload = self._health()
        body = response.get_data(as_text=True)
        self.assertEqual(payload["engine"], "failed")
        self.assertNotIn("payments", body)
        self.assertNotIn("srv", body)

    def test_the_engine_word_comes_from_the_closed_vocabulary(self):
        for engine, error in ((object(), None), (None, None), (None, "boom")):
            with self.subTest(engine=engine is not None, error=error), \
                    mock.patch.object(app_module, "engine", engine), \
                    mock.patch.object(app_module, "engine_error", error):
                _, payload = self._health()
            self.assertIn(payload["engine"], app_module.ENGINE_STATES)


if __name__ == "__main__":
    unittest.main()
