"""The login gate is one gate, it refuses by default, and every route is classified.

The gate used to be two lines repeated in thirteen views plus a fourteenth that wrote
its own. Nothing could say which routes were open, because the answer was whichever
views happened to check — so the test that matters here is not "a logged-out visitor is
redirected", which was always true; it is that **the set of routes answering without an
identity is closed, named, and equal to what somebody decided**.

That is why the roster is asserted against `app.url_map` rather than against a list of
paths typed out here: a route added tomorrow fails this file until its endpoint is put
on one of the lists, which is exactly the moment to decide whether it should be open.
"""
import os
import unittest
from unittest import TestCase, mock

# Import the app with the background engine disabled (no threads/network).
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from flask import url_for

from little_sister import app as app_module
from little_sister import identity, local_login

#: Every endpoint that requires an identity. Written out rather than derived, because
#: the value of this file is that adding a route makes a test fail until somebody has
#: said which of the three sets it belongs in.
GATED_ENDPOINTS = frozenset({
    "about", "copy", "events", "extension_asset", "history", "link_icon", "links",
    "links_check", "maintenance", "maintenance_overview", "preferences", "system",
    "user_avatar",
})

#: The one method each endpoint is exercised with, where GET is not it.
POST_ENDPOINTS = frozenset({"preferences", "maintenance", "links_check", "csp_report"})


def endpoints():
    return {rule.endpoint for rule in app_module.app.url_map.iter_rules()}


class RosterTests(TestCase):
    def test_every_route_in_the_application_is_classified(self):
        self.assertEqual(
            endpoints(),
            set(identity.OPEN_ENDPOINTS)
            | set(identity.SELF_AUTHENTICATING_ENDPOINTS)
            | set(GATED_ENDPOINTS),
            "a route is neither open, self-authenticating nor gated — classify it",
        )

    def test_the_two_lists_name_only_routes_that_exist(self):
        listed = (set(identity.OPEN_ENDPOINTS)
                  | set(identity.SELF_AUTHENTICATING_ENDPOINTS))
        self.assertEqual(listed - endpoints(), set(),
                         "a name on a list matches no route — a rename left it behind")

    def test_the_gate_applies_to_everything_not_on_a_list(self):
        for endpoint in sorted(endpoints()):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(identity.needs_identity(endpoint),
                                 endpoint in GATED_ENDPOINTS)

    def test_a_request_that_matched_no_route_is_not_sent_to_the_login_page(self):
        # It gets the ordinary 404: telling somebody to log in before telling them the
        # address does not exist answers a question they did not ask.
        self.assertFalse(identity.needs_identity(None))


class GateTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _url(self, endpoint):
        rule = next(r for r in app_module.app.url_map.iter_rules()
                    if r.endpoint == endpoint)
        with app_module.app.test_request_context():
            return url_for(endpoint, **dict.fromkeys(rule.arguments, "x"))

    def _call(self, endpoint):
        url = self._url(endpoint)
        if endpoint in POST_ENDPOINTS:
            return self.client.post(url)
        return self.client.get(url)

    def _login(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def test_every_gated_route_sends_a_stranger_to_the_login_page(self):
        for endpoint in sorted(GATED_ENDPOINTS):
            with self.subTest(endpoint=endpoint):
                response = self._call(endpoint)
                self.assertEqual(response.status_code, 302, endpoint)
                self.assertEqual(response.headers["Location"], "/login", endpoint)

    def test_no_open_route_is_answered_by_the_gate(self):
        # `logout` redirects to /login itself, so "did the gate fire" cannot be read
        # off the location alone: it is checked against the gate's own predicate, and
        # the rest are checked by what they actually answer.
        for endpoint in sorted(identity.OPEN_ENDPOINTS):
            with self.subTest(endpoint=endpoint):
                self.assertFalse(identity.needs_identity(endpoint))
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/").headers["Location"], "/status")

    def test_status_refuses_a_stranger_both_ways(self):
        page = self.client.get("/status")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/login")
        api = self.client.get("/status", headers={"Accept": "application/json"})
        self.assertEqual(api.status_code, 401)

    def test_a_signed_in_visitor_reaches_a_gated_page(self):
        self._login()
        self.assertEqual(self.client.get("/events").status_code, 200)


class IdentityTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def test_outside_a_request_there_is_nobody(self):
        self.assertIsNone(identity.current_user())

    def test_the_session_becomes_an_identity(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        with self.client.session_transaction():
            pass
        with self.client:
            self.client.get("/events")
            user = identity.current_user()
        self.assertIsNotNone(user)
        self.assertEqual(user.name, "pan")
        self.assertEqual(user.firstname, "Peter")
        self.assertEqual(user.lastname, "Pan")
        self.assertTrue(user.admin)

    def test_signed_in_refuses_rather_than_redirecting_when_nobody_is(self):
        # Reachable only from a view the gate covers, so nobody here means the route
        # is misclassified — and a redirect would send a person to a login form that
        # will not fix it.
        with app_module.app.test_request_context("/events"):
            with self.assertRaises(Exception) as caught:
                identity.signed_in()
        self.assertEqual(getattr(caught.exception, "code", None), 401)

    def test_a_viewer_is_refused_the_admin_pages(self):
        with mock.patch.dict(local_login.registered().users,
                             {"viewer": {"firstname": "V", "lastname": "R",
                                         "password": "pw", "admin": False}}):
            self.client.post("/login", data={"username": "viewer", "password": "pw"})
            self.assertEqual(self.client.get("/system").status_code, 403)
            self.assertEqual(self.client.post("/maintenance").status_code, 403)

    def test_an_admin_is_not_refused_them(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.assertEqual(self.client.get("/system").status_code, 200)


class NavRoleTests(TestCase):
    """The nav's admin-only entry follows the *identity*, not the session.

    The pages that include the shared header mostly pass no role of their own, and
    the nav partial used to read ``session['admin']`` to decide — correct today,
    because that is where `current_user()` reads it too, and therefore invisible to
    every test that logs in through the form. So these log nobody in: they hand the
    application an identity that did not come from this session, which is what an
    identity supplied from outside will look like, and ask what the nav drew. Against
    a session read, the admin case renders no `/system` link at all.
    """

    SYSTEM_LINK = 'href="/system"'

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _nav_for(self, user):
        with mock.patch.object(identity, "current_user", lambda: user):
            response = self.client.get("/events")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_an_admin_identity_is_offered_the_system_page(self):
        body = self._nav_for(identity.Identity(name="from-a-provider", admin=True))
        self.assertIn(self.SYSTEM_LINK, body)

    def test_a_viewer_identity_is_not(self):
        body = self._nav_for(identity.Identity(name="from-a-provider", admin=False))
        self.assertNotIn(self.SYSTEM_LINK, body)


if __name__ == "__main__":
    unittest.main()
