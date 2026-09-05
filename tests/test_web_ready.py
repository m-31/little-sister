"""``/ready`` answers *has this instance finished coming up* (ADR-0073).

``test_web_health.py`` is the sibling of this file and the two are deliberately
alike, because the routes are: both answer a machine that holds no credential of
ours, and the test that matters on each is the one asserting the **whole key set**
rather than the presence of the keys wanted.

What is this file's own is the composition — that a deployment which switched the
engine off is ready and one whose configuration would not load is not — and the
latch, which is asserted here through the route because that is where a load
balancer meets it.
"""
import json
import os
import unittest
from unittest import TestCase, mock

# Import the app with the background engine disabled (no threads/network).
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import readiness
from little_sister.readiness import Outcomes, Readiness, TrustStore

FULL = TrustStore(certificates=142)
EMPTY = TrustStore(certificates=0)


def _readiness(*, doors=True, trust=FULL, first_pass=True, outcomes=None):
    return Readiness(doors=lambda: doors, trust=lambda: trust,
                     first_pass=lambda: first_pass, outcomes=lambda: outcomes)


class ReadyRouteTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _ready(self, report=None):
        # A fresh report per call: the real one is a module-level object that
        # latches, and a test that latched it would hand the next test a ready
        # instance it never asked for.
        with mock.patch.object(app_module, "instance_readiness",
                               report if report is not None else _readiness()):
            response = self.client.get("/ready")
        return response, json.loads(response.get_data(as_text=True))

    def test_a_ready_instance_answers_200_and_says_one_thing(self):
        response, payload = self._ready()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/json")
        # The whole key set: this route is unauthenticated, so a field arriving
        # here by accident is a field published to whoever can reach the port.
        self.assertEqual(set(payload), {"status"})
        self.assertEqual(payload["status"], readiness.READY)

    def test_an_unready_instance_answers_503_and_says_what_it_waits_for(self):
        response, payload = self._ready(_readiness(doors=False))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(set(payload), {"status", "waiting_for"})
        self.assertEqual(payload["status"], readiness.NOT_READY)
        self.assertEqual(payload["waiting_for"], ["doors"])

    def test_it_publishes_only_the_closed_vocabulary(self):
        _, payload = self._ready(
            _readiness(doors=False, trust=EMPTY, first_pass=False))
        self.assertEqual(payload["waiting_for"], list(readiness.WAITING_FOR))

    def test_a_ready_answer_carries_no_empty_waiting_list(self):
        # Absent and empty would be the same fact said two ways, and one of them
        # would invite a caller to test the wrong thing.
        _, payload = self._ready()
        self.assertNotIn("waiting_for", payload)

    def test_it_is_not_cached(self):
        response, _ = self._ready()
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_it_answers_without_a_session_or_a_token(self):
        self.assertFalse(app_module.identity.needs_identity("ready"))
        response, _ = self._ready(_readiness(doors=False))
        self.assertEqual(response.status_code, 503,
                         "an unready instance must answer 503, never a redirect "
                         "to the login page")

    def test_once_ready_a_later_failure_does_not_withdraw_the_instance(self):
        doors = {"registered": True}
        report = Readiness(doors=lambda: doors["registered"], trust=lambda: FULL,
                           first_pass=lambda: True, outcomes=lambda: None)
        with mock.patch.object(app_module, "instance_readiness", report):
            self.assertEqual(self.client.get("/ready").status_code, 200)
            doors["registered"] = False
            self.assertEqual(self.client.get("/ready").status_code, 200)

    def test_nothing_about_this_deployment_reaches_the_body(self):
        secret = "/srv/deploy/config/checks/payments.yaml"
        report = _readiness(doors=False, trust=EMPTY, first_pass=False,
                            outcomes=Outcomes(9, 9, 9))
        with mock.patch.object(app_module, "engine_error", secret):
            response, _ = self._ready(report)
        body = response.get_data(as_text=True)
        self.assertNotIn("payments", body)
        self.assertNotIn("srv", body)
        # Not the check count either — the words carry no number.
        self.assertNotIn("9", body)


class CompositionTests(TestCase):
    """What the application feeds the first-pass condition (ADR-0073), which is
    where a deliberate quiet and a broken configuration stop being one answer."""

    def test_an_engine_switched_off_has_no_pass_to_wait_for(self):
        with mock.patch.object(app_module, "engine", None), \
                mock.patch.object(app_module, "engine_error", None):
            self.assertTrue(app_module._first_pass_done())

    def test_an_engine_that_could_not_load_its_config_never_finishes_one(self):
        with mock.patch.object(app_module, "engine", None), \
                mock.patch.object(app_module, "engine_error", "boom"):
            self.assertFalse(app_module._first_pass_done())

    def test_a_running_engine_answers_from_its_own_outcomes(self):
        engine = mock.Mock(outcomes=Outcomes(configured=3, completed=2, erroring=0))
        with mock.patch.object(app_module, "engine", engine):
            self.assertFalse(app_module._first_pass_done())
        engine.outcomes = Outcomes(configured=3, completed=3, erroring=0)
        with mock.patch.object(app_module, "engine", engine):
            self.assertTrue(app_module._first_pass_done())

    def test_an_instance_with_no_engine_reports_no_outcomes(self):
        with mock.patch.object(app_module, "engine", None):
            self.assertIsNone(app_module._check_outcomes())

    def test_a_running_engine_reports_its_outcomes(self):
        outcomes = Outcomes(configured=2, completed=2, erroring=2)
        with mock.patch.object(app_module, "engine", mock.Mock(outcomes=outcomes)):
            self.assertEqual(app_module._check_outcomes(), outcomes)

    def test_the_instance_lines_are_pinnable_under_the_readiness_name(self):
        # The suite empties the contributor registry before every test (conftest),
        # so the application's import-time registration cannot be observed from
        # here; what is asserted is the other half — that what it registers answers
        # with slugs the seam then prefixes, so `readiness.trust` is an address a
        # pin can be written against (ADR-0036).
        report = _readiness(trust=EMPTY, outcomes=Outcomes(4, 4, 4))
        app_module.self_report.register_contributor("readiness", report.lines)
        slugs = [line.slug for line in app_module.self_report.current_lines()]
        self.assertEqual(slugs, ["readiness.trust", "readiness.all-erroring"])


if __name__ == "__main__":
    unittest.main()
