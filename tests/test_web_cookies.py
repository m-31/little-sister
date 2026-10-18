"""Every cookie this application sets is ``Secure`` when the connection was (ADR-0065).

Three cookies leave this application and they are set in three different places — the
session cookie through Flask's session interface, the presentation preferences from
``/preferences``, and the view switches from ``/status``. The rule is one rule, so the
tests are written from the *sentence* rather than from each mechanism: take everything
a response sets and ask whether the flag matches the scheme the request arrived on.

Each test has a counterpart over plain HTTP. A test that only proved the flag appears
over TLS would pass just as happily against a hard-coded ``True``, which is the bug the
rule exists to avoid — a ``Secure`` cookie on a plain-HTTP instance is one the browser
never sends back, and the symptom is a login page that will not stay logged in.
"""
import os
import unittest
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module

HTTPS = "https://localhost"
HTTP = "http://localhost"

#: The session cookie's name is Flask's default; the tests name it rather than
#: importing it so a rename is visible here as a failure rather than as agreement.
SESSION_COOKIE = "session"


def attributes(header: str) -> set[str]:
    """A ``Set-Cookie`` header's attributes, lower-cased, without its ``name=value``.

    Split rather than searched: the session cookie's value is base64 of a signed
    payload and could contain the letters ``Secure`` by chance, so a substring test
    would pass for the wrong reason on some unlucky run.
    """
    return {part.strip().lower() for part in header.split(";")[1:]}


def cookie(response, name: str) -> str | None:
    """The one ``Set-Cookie`` header for *name*, or ``None`` if it was not set."""
    for header in response.headers.getlist("Set-Cookie"):
        if header.split("=", 1)[0] == name:
            return header
    return None


class CookieSecurityTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def _login(self, base_url):
        return self.client.post(
            "/login", data={"username": "pan", "password": "12345678"},
            base_url=base_url)

    # --- the session cookie -------------------------------------------------

    def test_the_login_cookie_is_secure_over_tls(self):
        header = cookie(self._login(HTTPS), SESSION_COOKIE)
        self.assertIsNotNone(header, "logging in set no session cookie")
        self.assertIn("secure", attributes(header))

    def test_the_login_cookie_is_not_secure_over_plain_http(self):
        header = cookie(self._login(HTTP), SESSION_COOKIE)
        self.assertIsNotNone(header, "logging in set no session cookie")
        self.assertNotIn("secure", attributes(header))

    def test_a_deployment_that_configured_the_flag_still_wins_without_tls(self):
        with mock.patch.dict(app_module.app.config,
                             {"SESSION_COOKIE_SECURE": True}):
            header = cookie(self._login(HTTP), SESSION_COOKIE)
        self.assertIsNotNone(header, "logging in set no session cookie")
        self.assertIn("secure", attributes(header))

    def test_the_login_cookie_says_samesite_lax(self):
        # It was the one cookie left to whatever the browser defaults to this year,
        # while `ls_prefs` and the fold-depth cookie — a theme and a disclosure
        # state — both said `Lax` outright. On an application whose state-changing
        # POSTs carry no CSRF token, `Lax` is what withholds this cookie from a
        # cross-site form post, which is the whole of that attack. And `Lax` rather
        # than `Strict`: a door's callback is a top-level navigation back from an
        # identity provider (ADR-0069 §4), which `Strict` would arrive at with no
        # cookie, breaking the redirect flow that seam exists to allow.
        header = cookie(self._login(HTTPS), SESSION_COOKIE)
        self.assertIsNotNone(header, "logging in set no session cookie")
        self.assertIn("samesite=lax", attributes(header))

    def test_logging_out_clears_the_cookie_the_same_way(self):
        self._login(HTTPS)
        header = cookie(self.client.get("/logout", base_url=HTTPS), SESSION_COOKIE)
        self.assertIsNotNone(header, "logging out cleared no session cookie")
        self.assertIn("secure", attributes(header))

    def test_outside_a_request_there_is_no_connection_to_ask_about(self):
        # The helper is reached from Flask's session machinery as well as from the
        # routes, and the docstring promises it answers rather than raises when there
        # is no request to ask about. Nothing marks a cookie there, so False is the
        # only safe answer.
        self.assertFalse(app_module._connection_is_secure())

    # --- the presentation preferences ---------------------------------------

    def test_the_presentation_cookie_is_secure_over_tls(self):
        self._login(HTTPS)
        response = self.client.post(
            "/preferences", data={"theme": "dark", "layout": "rail"},
            base_url=HTTPS)
        header = cookie(response, "ls_prefs")
        self.assertIsNotNone(header, "/preferences set no cookie")
        self.assertIn("secure", attributes(header))

    def test_the_presentation_cookie_is_not_secure_over_plain_http(self):
        self._login(HTTP)
        response = self.client.post(
            "/preferences", data={"theme": "dark", "layout": "rail"},
            base_url=HTTP)
        header = cookie(response, "ls_prefs")
        self.assertIsNotNone(header, "/preferences set no cookie")
        self.assertNotIn("secure", attributes(header))

    # --- the view switches, and the sentence as a whole ---------------------

    def test_every_cookie_the_dashboard_sets_is_secure_over_tls(self):
        self._login(HTTPS)
        response = self.client.get("/status?depth=3&view=1", base_url=HTTPS)
        headers = response.headers.getlist("Set-Cookie")
        # hide_ok + hide_idle: the two filters. The depth and density cookies went
        # with dense mode (ADR-0127 decision 7) — a `depth=` is the viewer's word
        # for one load and writes none. The count is asserted so that a route
        # which quietly stopped setting them cannot make this test pass by covering
        # nothing at all.
        self.assertEqual(len(headers), 2, headers)
        self.assertEqual(sorted(header.split("=", 1)[0] for header in headers),
                         ["hide_idle", "hide_ok"])
        for header in headers:
            self.assertIn("secure", attributes(header), header)

    def test_every_cookie_the_dashboard_sets_is_plain_over_plain_http(self):
        self._login(HTTP)
        response = self.client.get("/status?depth=3&view=1", base_url=HTTP)
        headers = response.headers.getlist("Set-Cookie")
        self.assertEqual(len(headers), 2, headers)
        for header in headers:
            self.assertNotIn("secure", attributes(header), header)

    def test_the_retired_view_cookies_are_expired_with_the_same_attributes(self):
        # The first answer that finds a `depth` or `dense` cookie expires it, once
        # (ADR-0127 decision 7): a deletion is a Set-Cookie too, and carries the
        # same flags as the cookies the page sets, so a browser matches and drops it.
        self._login(HTTPS)
        self.client.set_cookie("depth", "3", domain="localhost")
        self.client.set_cookie("dense", "1", domain="localhost")
        response = self.client.get("/status", base_url=HTTPS)
        headers = response.headers.getlist("Set-Cookie")
        self.assertEqual(sorted(header.split("=", 1)[0] for header in headers),
                         ["dense", "depth"])
        for header in headers:
            self.assertIn("max-age=0", header.lower(), header)
            self.assertIn("secure", attributes(header), header)
            self.assertIn("samesite=lax", header.lower(), header)


if __name__ == "__main__":
    unittest.main()
