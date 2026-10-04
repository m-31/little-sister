"""The one door the library ships: the system-admin account (ADR-0069 §5).

The claim this file exists for is the last one in the *Done when* list of the slice
that built it: **somebody can still get in through a door of their own when the
provider has stopped answering.** That is
``TheAccountExistsForThisTests.test_a_provider_that_raises_on_every_request_leaves_this_door_open``,
and everything else here is the machinery that has to hold for it to be true — a
credential registered rather than configured, resolved once, and a door that is shut
rather than fake when the resolution failed.

The rest is refusals. This is the one credential in the application an attacker can
guess at without a directory in the way, so each keyword refuses the other's shape,
and a password that arrives looking like a reference (or the reverse) is a startup
error rather than a surprise on the day the account is needed.
"""
import os
import unittest
from types import FunctionType
from typing import Any
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from flask import redirect

from little_sister import app as app_module
from little_sister import identity, local_login, secrets, system_admin
from little_sister.identity import Identity
from little_sister.secrets import UnknownSchemeError
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from little_sister.users import AvatarFile

PASSWORD = "a-real-password"
PASSWORD_ENV = "LS_TEST_SYSTEM_ADMIN_PASSWORD"
PASSWORD_REFERENCE = f"env://{PASSWORD_ENV}"
MISSING_REFERENCE = "env://LS_TEST_SYSTEM_ADMIN_ABSENT"

#: What the ordinary login page offers, and where it goes. Both are asserted as
#: written rather than built from `DOOR_NAME`: the page already carries that string
#: in an avatar filename, so a substring test on the name alone passes on a page
#: with no link at all.
LINK_TEXT = "System administrator sign-in"
LINK_HREF = f"{identity.LOGIN_PATH}/{system_admin.DOOR_NAME}"


def _claim(name: str, provider: Any, **kwargs: Any) -> None:
    """The one line a deployment's registration module runs (see
    `test_identity_doors.py`, where this trick is explained)."""
    identity.use(name, provider, **kwargs)


def _from_package(package: str):
    return FunctionType(_claim.__code__,
                        {"__name__": f"{package}.registrations",
                         "identity": identity})


class Unreachable:
    """A deployment provider that has stopped answering — the event this whole
    account is shaped around, since *the directory is down* and *something is
    wrong* are not independent."""

    def identify(self) -> Identity | None:
        raise RuntimeError("the directory is unreachable")

    def challenge(self):
        return redirect("https://idp.example/authorize")


class _Case(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.environment = mock.patch.dict(os.environ,
                                           {PASSWORD_ENV: PASSWORD})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _configure(self, **kwargs: str) -> None:
        """Configure the account the way a deployment's `wsgi.py` does."""
        identity.use_system_admin(**kwargs)

    def _login(self, password: str = PASSWORD, username: str = "admin"):
        return self.client.post(f"/login/{system_admin.DOOR_NAME}",
                                data={"username": username,
                                      "password": password})


class RegistrationTests(_Case):
    """Exactly one keyword, and each refuses the other's shape."""

    def test_a_reference_is_resolved_once_at_registration(self):
        self._configure(reference=PASSWORD_REFERENCE)
        account = system_admin.registered()
        assert account is not None
        self.assertTrue(account.available)
        self.assertEqual(account.keyword, system_admin.BY_REFERENCE)
        self.assertEqual(account.reference, PASSWORD_REFERENCE)
        self.assertEqual(account.problem, "")
        # Resolved *once*: the environment can go away and the door stays open.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self._login().status_code, 302)

    def test_the_registration_is_a_door_and_never_the_default(self):
        self._configure(reference=PASSWORD_REFERENCE)
        door = identity.door(system_admin.DOOR_NAME)
        assert door is not None
        self.assertFalse(door.default)
        self.assertEqual(door.package, "little_sister")
        self.assertEqual(door.route, "/login/system-admin")
        standing = identity.default_door()
        assert standing is not None
        self.assertEqual(standing.name, local_login.DOOR_NAME)

    def test_which_keyword_configured_it_is_logged_at_startup(self):
        with self.assertLogs("little_sister", level="INFO") as caught:
            self._configure(reference=PASSWORD_REFERENCE)
        self.assertIn(PASSWORD_REFERENCE, "\n".join(caught.output))

    def test_a_literal_password_is_taken_and_named_as_such(self):
        with self.assertLogs("little_sister", level="INFO") as caught:
            self._configure(password=PASSWORD)
        account = system_admin.registered()
        assert account is not None
        self.assertEqual(account.keyword, system_admin.BY_PASSWORD)
        self.assertEqual(account.reference, "")
        self.assertTrue(account.available)
        message = "\n".join(caught.output)
        self.assertIn("discouraged", message)
        # The one thing that must never be logged is the credential itself.
        self.assertNotIn(PASSWORD, message)

    def test_neither_keyword_refuses_and_names_both(self):
        with self.assertRaises(ValueError) as caught:
            self._configure()
        message = str(caught.exception)
        self.assertIn("reference=", message)
        self.assertIn("password=", message)
        self.assertIn("neither", message)
        self.assertIsNone(system_admin.registered())

    def test_both_keywords_refuse(self):
        with self.assertRaises(ValueError) as caught:
            self._configure(reference=PASSWORD_REFERENCE, password=PASSWORD)
        self.assertIn("both", str(caught.exception))
        self.assertIsNone(system_admin.registered())

    def test_a_reference_handed_to_password_is_refused(self):
        # Handed over as the password, the *address* would become the credential,
        # and nothing would say so until the account was needed.
        with self.assertRaises(ValueError) as caught:
            self._configure(password=PASSWORD_REFERENCE)
        self.assertIn("reference=", str(caught.exception))
        self.assertIsNone(system_admin.registered())

    def test_a_literal_handed_to_reference_is_refused_by_the_resolver(self):
        # ADR-0023's own words — a config field names a secret, it never carries
        # one — so a password hard-coded in a committed `wsgi.py` fails at startup.
        with self.assertRaises(UnknownSchemeError):
            self._configure(reference=PASSWORD)
        self.assertIsNone(system_admin.registered())

    def test_an_unregistered_scheme_fails_startup_rather_than_shutting_the_door(self):
        # Malformed is a typo in the deployment's own code, not a fact about the
        # world today: it is the other half of ADR-0023's split and stays loud.
        with self.assertRaises(UnknownSchemeError):
            self._configure(reference="nowhere://little-sister/admin")
        self.assertIsNone(system_admin.registered())


class UnresolvableCredentialTests(_Case):
    """A failed resolution closes that door and the application keeps serving."""

    def setUp(self):
        super().setUp()
        with self.assertLogs("little_sister", level="WARNING") as caught:
            self._configure(reference=MISSING_REFERENCE)
        self.logged = "\n".join(caught.output)

    def test_the_door_is_registered_but_shut(self):
        account = system_admin.registered()
        assert account is not None
        self.assertFalse(account.available)
        self.assertEqual(account.keyword, system_admin.BY_REFERENCE)
        self.assertNotEqual(account.problem, "")

    def test_the_application_keeps_serving(self):
        # An unreachable parameter store must not take the dashboard down during
        # exactly the kind of event it is watching.
        self.client.post("/login", data={"username": "pan",
                                         "password": "12345678"})
        self.assertEqual(self.client.get("/events").status_code, 200)

    def test_the_shut_door_answers_404_both_ways(self):
        self.assertEqual(
            self.client.get(f"/login/{system_admin.DOOR_NAME}").status_code, 404)
        self.assertEqual(self._login().status_code, 404)

    def test_the_startup_warning_names_the_reference(self):
        self.assertIn(MISSING_REFERENCE, self.logged)

    def test_the_login_page_does_not_link_to_a_door_that_cannot_answer(self):
        # Registered is not the same as usable, and the link follows *usable*: a
        # link to the 404 above would be offered at the moment somebody is least
        # able to shrug it off.
        self.assertEqual(system_admin.usable_route(), "")
        page = self.client.get(identity.LOGIN_PATH).get_data(as_text=True)
        self.assertNotIn(LINK_TEXT, page)

    def test_the_shut_door_says_so_to_the_seam_and_the_chooser_omits_it(self):
        # One question, asked of the door, and both callers ask it — the link
        # above and the chooser. Two rules about whether a way in exists is the
        # pair that drifts and then disagrees.
        door = identity.door(system_admin.DOOR_NAME)
        assert door is not None
        self.assertFalse(door.enterable)
        identity.choose_at_login()
        self.assertNotIn(LINK_HREF,
                         self.client.get(identity.LOGIN_PATH).get_data(as_text=True))

    def test_system_says_configured_but_unavailable(self):
        self.client.post("/login", data={"username": "pan",
                                         "password": "12345678"})
        page = self.client.get("/system/installed").get_data(as_text=True)
        self.assertIn("credential unavailable", page)
        self.assertIn(MISSING_REFERENCE, page)


class TheDoorTests(_Case):
    def setUp(self):
        super().setUp()
        self._configure(reference=PASSWORD_REFERENCE)

    def test_an_unconfigured_account_has_no_door_at_all(self):
        identity.forget_doors()
        local_login.use_local()
        self.assertIsNone(system_admin.registered())
        self.assertEqual(
            self.client.get(f"/login/{system_admin.DOOR_NAME}").status_code, 404)

    def test_the_form_says_which_door_this_is(self):
        page = self.client.get(f"/login/{system_admin.DOOR_NAME}")
        self.assertEqual(page.status_code, 200)
        self.assertIn("System administrator", page.get_data(as_text=True))

    def test_the_ordinary_login_page_offers_the_way_here(self):
        page = self.client.get(identity.LOGIN_PATH).get_data(as_text=True)
        self.assertIn(LINK_TEXT, page)
        self.assertIn(f'href="{LINK_HREF}"', page)

    def test_a_refused_login_offers_it_too(self):
        # The page somebody is actually looking at while they work out that the
        # login they usually use is not going to work today.
        with self.assertLogs("little_sister", level="WARNING"):
            page = self.client.post(identity.LOGIN_PATH,
                                    data={"username": "pan", "password": "nope"})
        self.assertIn(f'href="{LINK_HREF}"', page.get_data(as_text=True))

    def test_this_door_s_own_form_does_not_link_to_itself(self):
        # Same document, both forms — and a page offering a link to itself is a
        # page that has stopped meaning anything.
        page = self.client.get(LINK_HREF).get_data(as_text=True)
        self.assertNotIn(LINK_TEXT, page)
        self.assertNotIn(f'href="{LINK_HREF}"', page)

    def test_a_usable_account_is_a_door_that_can_be_entered(self):
        door = identity.door(system_admin.DOOR_NAME)
        assert door is not None
        self.assertTrue(door.enterable)
        self.assertEqual(system_admin.usable_route(), LINK_HREF)

    def test_the_chooser_offers_it_beside_the_everyday_door(self):
        # The whole point of the account on a redirecting install, and the reason
        # this door is never the default: it is the second entry, not the first.
        identity.choose_at_login()
        body = self.client.get(identity.LOGIN_PATH).get_data(as_text=True)
        self.assertIn(f'href="{LINK_HREF}"', body)
        self.assertIn(f'href="{identity.LOGIN_PATH}/{local_login.DOOR_NAME}"', body)
        # In words, not as the path segment `system-admin`.
        self.assertIn(system_admin.LABEL, body)
        door = identity.door(system_admin.DOOR_NAME)
        assert door is not None
        self.assertEqual(door.label, "System administrator")

    def test_no_configured_account_is_no_link(self):
        identity.forget_doors()
        local_login.use_local()
        self.assertEqual(system_admin.usable_route(), "")
        self.assertNotIn(
            LINK_TEXT,
            self.client.get(identity.LOGIN_PATH).get_data(as_text=True))

    def test_the_right_password_signs_the_account_in(self):
        with self.assertLogs("little_sister", level="WARNING") as caught:
            page = self._login()
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/status")
        self.assertIn("system-admin.used: the local 'admin' account signed in",
                      "\n".join(caught.output))
        self.assertNotIn(PASSWORD, "\n".join(caught.output))
        self.assertEqual(self.client.get("/events").status_code, 200)

    def test_the_session_records_this_door(self):
        self._login()
        with self.client.session_transaction() as stored:
            self.assertEqual(stored[identity.DOOR_KEY],
                             system_admin.DOOR_NAME)

    def test_a_wrong_password_is_refused_and_logged(self):
        with self.assertLogs("little_sister", level="WARNING") as caught:
            page = self._login(password="not-it")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Invalid username or password", page.get_data(as_text=True))
        self.assertIn("login.failed: for 'admin' at the system-admin door",
                      "\n".join(caught.output))
        self.assertEqual(self.client.get("/events").status_code, 302)

    def test_an_umlaut_is_a_wrong_password_and_not_a_500(self):
        # What anybody with a German keyboard types, and what the standard library's
        # own `compare_digest` raises `TypeError` over when handed as text. An
        # anonymous visitor at the emergency door got a server error instead of
        # *invalid password* — a difference somebody probing can read.
        with self.assertLogs("little_sister", level="WARNING"):
            page = self._login(password="pässwort")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Invalid username or password", page.get_data(as_text=True))

    def test_a_non_ascii_password_in_the_env_still_lets_the_admin_in(self):
        # The worse half: a deployment that hand-edited a non-ASCII password into
        # `.env` had a door that raised on *every* attempt, right password included
        # — found during the incident it exists for.
        password = "Straßenbahn-Grün"
        identity.forget_doors()
        with mock.patch.dict(os.environ, {PASSWORD_ENV: password}):
            self._configure(reference=PASSWORD_REFERENCE)
        with self.assertLogs("little_sister", level="WARNING"):
            page = self._login(password=password)
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/status")

    def test_another_login_name_is_refused_however_right_the_password(self):
        # One account, and its name is not configurable.
        with self.assertLogs("little_sister", level="WARNING"):
            page = self._login(username="root")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(self.client.get("/events").status_code, 302)

    def test_it_is_an_admin(self):
        self._login()
        self.assertEqual(self.client.get("/system").status_code, 200)

    def test_it_has_no_callback_and_no_end_session_of_its_own(self):
        self.assertEqual(
            self.client.get(f"/auth/callback/{system_admin.DOOR_NAME}").status_code,
            404)
        self._login()
        page = self.client.get("/logout")
        self.assertEqual(page.headers["Location"], identity.LOGIN_PATH)
        with self.client.session_transaction() as stored:
            self.assertEqual(dict(stored), {})

    def test_an_expired_session_is_challenged_by_this_door_not_the_default(self):
        self._login()
        with self.client.session_transaction() as stored:
            stored.pop("username")
        page = self.client.get("/events")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"],
                         f"/login/{system_admin.DOOR_NAME}")

    def test_the_stored_authorship_is_the_name_alone(self):
        # `set_by` is a stored key that outlives the mechanism that produced it, so
        # *which door* must not leak into it (ADR-0069 §5). The pin page is where
        # that stored name is shown back — a leaf's, on a tree of this test's own:
        # a branch an earlier test left at this path would be another page.
        app_module.status_tree = StatusTree()
        app_module.status_tree.upsert("/db", StatusCode.OK, "in step")
        self._login()
        self.client.post("/maintenance",
                         data={"path": "db", "action": "set",
                               "reason": "during an incident", "duration": "2h"})
        body = " ".join(
            self.client.get("/status/db").get_data(as_text=True).split())
        # The stored name, whole and alone — anchored on both sides, since a
        # substring assertion cannot tell `admin` from `admin@system-admin`.
        self.assertIn("Pinned by <strong>admin</strong>", body)
        self.assertIn("silenced by <strong>admin</strong>", body)


class VisibleInUseTests(_Case):
    """Three channels, and deliberately not a fourth: no page banner."""

    def setUp(self):
        super().setUp()
        self._configure(reference=PASSWORD_REFERENCE)

    def test_the_session_wears_the_packaged_avatar(self):
        self._login()
        page = self.client.get("/events").get_data(as_text=True)
        self.assertIn("/static/system-admin-avatar.svg", page)
        self.assertIn(system_admin.DISPLAY_NAME, page)

    def test_it_wears_it_even_where_the_user_list_has_an_admin_of_its_own(self):
        # The account's name is `admin`, which a deployment's own list may also
        # have. The one session that must never wear somebody else's picture is
        # this one.
        avatar = AvatarFile(path=__file__, content_type="image/png",  # type: ignore[arg-type]
                            root=__file__)  # type: ignore[arg-type]
        with mock.patch.dict(local_login.registered_avatars(),
                             {"admin": avatar}, clear=True):
            self._login()
            page = self.client.get("/events").get_data(as_text=True)
            self.assertIn("/static/system-admin-avatar.svg", page)
            self.assertNotIn('src="/user/avatar"', page)
            self.assertEqual(self.client.get("/user/avatar").headers["Location"],
                             "/static/system-admin-avatar.svg")

    def test_an_ordinary_session_is_untouched_by_any_of_it(self):
        self.client.post("/login", data={"username": "pan",
                                         "password": "12345678"})
        page = self.client.get("/events").get_data(as_text=True)
        self.assertNotIn("system-admin-avatar", page)
        self.assertNotIn(system_admin.DISPLAY_NAME, page)
        self.assertFalse(identity.is_system_admin_session())

    def test_no_page_banner(self):
        # Three channels are enough; the fourth would be shouting, and this one
        # would sit on every page of a dashboard somebody is trying to read.
        self._login()
        page = self.client.get("/events").get_data(as_text=True)
        self.assertNotIn("alert-warning", page)


class SystemPageTests(_Case):
    """A way into an application must not be knowable only by reading the source."""

    def _system(self) -> str:
        self.client.post("/login", data={"username": "pan",
                                         "password": "12345678"})
        return " ".join(
            self.client.get("/system/installed").get_data(as_text=True).split())

    def test_every_door_has_a_row_of_its_own(self):
        self._configure(reference=PASSWORD_REFERENCE)
        _from_package("deployment_x")("keycloak", Unreachable())
        page = self._system()
        # The whole row, whitespace-collapsed: a per-cell assertion passes just as
        # well when a value lands one column over (ADR-0064's lesson).
        self.assertIn("<td><code>local</code> "
                      '<span class="text-muted">(Local account)</span></td> '
                      '<td class="text-muted"><code>/login/local</code></td> '
                      "<td>LocalUsers</td> "
                      '<td class="text-muted">little_sister</td> '
                      '<td class="text-muted">default</td>', page)
        self.assertIn("<td><code>system-admin</code> "
                      '<span class="text-muted">(System administrator)</span></td> '
                      '<td class="text-muted"><code>/login/system-admin</code></td> '
                      "<td>SystemAdmin</td> "
                      '<td class="text-muted">little_sister</td> '
                      '<td class="text-muted">—</td>', page)
        # And the control for the rule: `keycloak` was registered without a label,
        # so its label *is* its name and the row prints it once rather than twice.
        self.assertIn("<td><code>keycloak</code></td> "
                      '<td class="text-muted"><code>/login/keycloak</code></td> '
                      "<td>Unreachable</td> "
                      '<td class="text-muted">deployment_x</td> '
                      '<td class="text-muted">—</td>', page)

    def test_the_page_says_what_login_itself_does(self):
        # The table cannot say it, and it is part of the way in: under
        # `choose_at_login()` that address is a page offering these doors rather
        # than the default one's login step.
        self._configure(reference=PASSWORD_REFERENCE)
        self.assertIn("<code>/login</code> is the default door's own login step.",
                      " ".join(self._system().split()))
        identity.choose_at_login()
        self.assertIn("<code>/login</code> offers a choice of the doors above",
                      " ".join(self._system().split()))

    def test_it_says_which_keyword_configured_the_account(self):
        self._configure(password=PASSWORD)
        page = self._system()
        self.assertIn("System admin: configured by <code>password=</code>", page)
        self.assertIn("credential resolved", page)
        self.assertNotIn(PASSWORD, page)

    def test_a_reference_is_printed_and_a_password_is_not(self):
        self._configure(reference=PASSWORD_REFERENCE)
        page = self._system()
        self.assertIn("<code>reference=</code>", page)
        self.assertIn(f"<code>{PASSWORD_REFERENCE}</code>", page)
        self.assertNotIn(PASSWORD, page)

    def test_it_says_when_no_account_is_configured(self):
        page = self._system()
        self.assertIn("No system-admin account is configured", page)


class TheAccountExistsForThisTests(_Case):
    """The scenario, end to end."""

    def test_a_provider_that_raises_on_every_request_leaves_this_door_open(self):
        identity.forget_doors()
        _from_package("deployment_x")("keycloak", Unreachable(), default=True)
        self._configure(reference=PASSWORD_REFERENCE)
        # Nothing else registered: no user list is read at all in this deployment.
        self.assertIsNone(local_login.registered())
        identity.announce_doors()

        with self.assertLogs("little_sister", level="ERROR"):
            unreachable = self.client.get("/events")
        self.assertEqual(unreachable.status_code, 302)
        self.assertEqual(unreachable.headers["Location"],
                         "https://idp.example/authorize")

        form = self.client.get(f"/login/{system_admin.DOOR_NAME}")
        self.assertEqual(form.status_code, 200)
        with self.assertLogs("little_sister", level="WARNING"):
            self.assertEqual(self._login().status_code, 302)
        self.assertEqual(self.client.get("/events").status_code, 200)
        self.assertEqual(self.client.get("/system").status_code, 200)

    def test_this_account_registers_happily_beside_the_built_in_list(self):
        # This repository's own deployment: a user list *and* a system admin, both
        # named by its own `wsgi.py`. This door never claims the default, which is
        # what leaves the everyday one free to.
        identity.forget_doors()
        self._configure(reference=PASSWORD_REFERENCE)
        self.assertIsNotNone(local_login.use_local())
        identity.announce_doors()
        standing = identity.default_door()
        assert standing is not None
        self.assertEqual(standing.name, local_login.DOOR_NAME)
        self.assertEqual([door.name for door in identity.registered_doors()],
                         ["local", "system-admin"])


class SecretShapeTests(TestCase):
    """The shape test both callers share (`secrets.looks_like_reference`)."""

    def test_a_reference_is_recognized_by_its_scheme(self):
        for value in ("env://NAME", "aws-sm://team/key", "x:// spaced"):
            with self.subTest(value=value):
                self.assertTrue(secrets.looks_like_reference(value))

    def test_a_credential_is_not(self):
        for value in ("hunter2", "", "  ", "a/b/c", "http:/almost"):
            with self.subTest(value=value):
                self.assertFalse(secrets.looks_like_reference(value))


if __name__ == "__main__":
    unittest.main()
