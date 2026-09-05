"""Identity comes from outside, through doors that are never a chain (ADR-0069).

The claim this file exists for is not "a provider can be registered" — that much any
seam does. It is the **property the whole design rests on**: several ways in are
allowed, and there is no ordered list of them to try. So the test that matters most is
``ReadPathTests.test_a_second_door_is_never_consulted_for_a_session_it_did_not_open``,
and the reason the providers below are *three* rather than one is that the shape is
only proved by the third: a local form, a redirect flow, and a header-verifying
provider that implements the two required methods and nothing else. That last one is
the case a flow-shaped contract would have made the awkward one, so it is the one
that has to be easy here.

The registration half follows the secret-resolver registry (ADR-0064) and its tests:
a claim is made by a **module of some other package's name**, so the inference itself
is under test rather than a patched answer to it.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import FunctionType
from typing import Any
from unittest import TestCase

# Import the app with the background engine disabled (no threads/network).
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from flask import redirect, request, session

from little_sister import app as app_module
from little_sister import identity, local_login, self_report, system_admin
from little_sister.codes import StatusCode
from little_sister.identity import Identity

_REPO = Path(__file__).resolve().parents[1]

#: This test module's own package, which is what the registry infers for a bare
#: :func:`identity.use` call from here.
HERE = __name__.split(".")[0]


def _claim(name: str, provider: Any, **kwargs: Any) -> None:
    """The one line an installed package's registration module runs.

    Only its **globals** travel: :func:`_from_package` rebinds this body to a
    namespace named after some other package, which is exactly what the registry
    reads — the calling frame's ``__name__``. Faking the module rather than the
    answer keeps the inference itself under test; a test that patched
    ``calling_package`` would pass against a registry that never called it.
    """
    identity.use(name, provider, **kwargs)


def _from_module(module: str):
    """:func:`_claim` as a module of that exact name would call it."""
    return FunctionType(_claim.__code__,
                        {"__name__": module, "identity": identity})


def _from_package(package: str):
    """:func:`_claim` as *package*'s own registration submodule would call it."""
    return _from_module(f"{package}.registrations")


class Recorder:
    """A provider that counts what was asked of it.

    Every provider below is one, because half the claims here are about a call that
    **did not happen** — and a call that did not happen is only visible against a
    provider that would have recorded it.
    """

    def __init__(self) -> None:
        self.asked = 0

    def identify(self) -> Identity | None:
        self.asked += 1
        return None

    def challenge(self):
        return redirect("/nowhere")


class LocalForm(Recorder):
    """The built-in shape: a local form, a session, a redirect challenge."""

    def __init__(self, name: str = "local") -> None:
        super().__init__()
        self.name = name

    def identify(self) -> Identity | None:
        self.asked += 1
        who = session.get("username")
        return None if not who else Identity(name=str(who), admin=True)

    def challenge(self):
        return redirect(f"/login/{self.name}")

    def login_page(self):
        return f"form for {self.name}", 200

    def submit_login(self):
        identity.sign_in(Identity(name=request.form["username"], admin=True))
        return redirect("/status")


class RedirectFlow(Recorder):
    """The Keycloak shape: the challenge leaves, and a callback comes back."""

    AUTHORIZE = "https://idp.example/authorize"
    END_SESSION = "https://idp.example/logout"

    def identify(self) -> Identity | None:
        self.asked += 1
        who = session.get("username")
        return None if not who else Identity(name=str(who), admin=True)

    def challenge(self):
        return redirect(self.AUTHORIZE)

    def complete_login(self):
        identity.sign_in(Identity(name=request.args["as"], admin=True))
        return redirect("/status")

    def end_session(self):
        return redirect(self.END_SESSION)


class Offered(RedirectFlow):
    """Keycloak once the deployment wants it on a chooser (ADR-0069 §1).

    The one method a redirecting provider adds: its flow starts at its **own**
    route as well as from a challenge. Without it there is no address to offer —
    `challenge()` is not an address — and the door is not enterable.
    """

    def login_page(self):
        return redirect(self.AUTHORIZE)


class SignedHeader(Recorder):
    """The load-balancer shape: `identify` and `challenge`, and *nothing else*.

    It performs no login at all — the exchange happened in front of this process —
    so it writes no session, has no page to render and no callback to receive.
    """

    HEADER = "X-Assertion"

    def identify(self) -> Identity | None:
        self.asked += 1
        who = request.headers.get(self.HEADER, "")
        return Identity(name=who, admin=True) if who else None

    def challenge(self):
        return "unauthorized", 401


class Broken(Recorder):
    """A provider that has stopped answering, which is the event this design is
    shaped around: it happens at the same moment everything else is going wrong."""

    def identify(self) -> Identity | None:
        self.asked += 1
        raise RuntimeError("the directory is unreachable")


class _Case(TestCase):
    """The state a running instance is in: the built-in login list on the `local`
    door, put there by the fixture in `conftest.py` exactly as importing the
    application puts it there. The client is what carries a session across
    requests."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()


class _DeploymentCase(_Case):
    """A deployment that registers a provider of its own.

    `forget_doors()` is how that state is reached here, and it is the *same* state:
    a deployment registers what it wants in the import-before-app block and the
    library adds nothing beside it, so an install with a Keycloak provider and no
    `use_local()` line has exactly one door. Clearing what conftest put back is the
    only way to reproduce that in a process where the application is imported once.
    """

    def setUp(self):
        super().setUp()
        identity.forget_doors()


class RegistrationTests(_DeploymentCase):
    def test_a_door_records_the_package_that_registered_it(self):
        _from_package("deployment_x")("keycloak", RedirectFlow())
        claimed = identity.door("keycloak")
        assert claimed is not None
        self.assertEqual(claimed.package, "deployment_x")
        self.assertEqual(claimed.owner, "deployment_x")
        self.assertFalse(claimed.default)

    def test_a_bare_call_records_the_calling_package(self):
        identity.use("local", LocalForm())
        claimed = identity.door("local")
        assert claimed is not None
        self.assertEqual(claimed.package, HERE)

    def test_a_door_carries_its_own_route_and_callback(self):
        identity.use("keycloak", RedirectFlow())
        claimed = identity.door("keycloak")
        assert claimed is not None
        self.assertEqual(claimed.route, "/login/keycloak")
        self.assertEqual(claimed.callback, "/auth/callback/keycloak")

    def test_another_package_claiming_one_door_name_refuses(self):
        _from_package("first_package")("local", LocalForm())
        with self.assertRaises(identity.DoorConflictError):
            _from_package("second_package")("local", LocalForm())

    def test_the_refusal_names_both_packages_and_the_door(self):
        _from_package("first_package")("local", LocalForm())
        with self.assertRaises(identity.DoorConflictError) as caught:
            _from_package("second_package")("local", LocalForm())
        message = str(caught.exception)
        self.assertIn("first_package", message)
        self.assertIn("second_package", message)
        self.assertIn("'local'", message)

    def test_a_refused_claim_leaves_the_first_provider_answering(self):
        first = LocalForm()
        _from_package("first_package")("local", first)
        with self.assertRaises(identity.DoorConflictError):
            _from_package("second_package")("local", LocalForm())
        claimed = identity.door("local")
        assert claimed is not None
        self.assertIs(claimed.provider, first)
        self.assertEqual(claimed.package, "first_package")

    def test_case_and_padding_do_not_dodge_the_claim(self):
        _from_package("first_package")("local", LocalForm())
        with self.assertRaises(identity.DoorConflictError):
            _from_package("second_package")("  LOCAL  ", LocalForm())

    def test_the_same_package_registering_again_is_a_reload_and_not_a_conflict(self):
        # A registration module imported twice under a reloading server must not
        # refuse the server.
        again = _from_package("deployment_x")
        again("local", LocalForm())
        second = LocalForm()
        again("local", second)
        claimed = identity.door("local")
        assert claimed is not None
        self.assertIs(claimed.provider, second)

    def test_a_second_default_refuses_and_names_both_doors(self):
        _from_package("first_package")("local", LocalForm(), default=True)
        with self.assertRaises(identity.DoorConflictError) as caught:
            _from_package("second_package")("keycloak", RedirectFlow(),
                                            default=True)
        message = str(caught.exception)
        self.assertIn("'local'", message)
        self.assertIn("'keycloak'", message)
        self.assertIn("first_package", message)
        self.assertIn("second_package", message)

    def test_a_refused_default_leaves_the_first_default_standing(self):
        _from_package("first_package")("local", LocalForm(), default=True)
        with self.assertRaises(identity.DoorConflictError):
            _from_package("second_package")("keycloak", RedirectFlow(),
                                            default=True)
        standing = identity.default_door()
        assert standing is not None
        self.assertEqual(standing.name, "local")

    def test_the_default_door_may_be_re_registered_by_its_own_package(self):
        again = _from_package("deployment_x")
        again("local", LocalForm(), default=True)
        again("local", LocalForm(), default=True)
        standing = identity.default_door()
        assert standing is not None
        self.assertEqual(standing.name, "local")

    def test_a_provider_registered_after_the_built_in_list_is_refused(self):
        # An install cannot have it both ways, and the refusal is what says so. A
        # `wsgi.py` calling `use_local()` has claimed the default door; a provider
        # of its own registered afterwards finds the question answered rather than
        # quietly winning or quietly losing by import order. Both lines are now in
        # the deployment's own file, which is what makes this one fixable by
        # reading it.
        local_login.use_local()
        with self.assertRaises(identity.DoorConflictError) as caught:
            _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        self.assertIn("'local'", str(caught.exception))
        standing = identity.default_door()
        assert standing is not None
        self.assertEqual(standing.name, local_login.DOOR_NAME)

    def test_a_second_door_without_default_is_welcome(self):
        _from_package("first_package")("local", LocalForm(), default=True)
        _from_package("second_package")("keycloak", RedirectFlow())
        self.assertEqual([row.name for row in identity.registered_doors()],
                         ["keycloak", "local"])
        standing = identity.default_door()
        assert standing is not None
        self.assertEqual(standing.name, "local")

    def test_a_name_that_is_not_a_path_segment_is_refused(self):
        for name in ("", "  ", "system admin", "system/admin", "system_admin",
                     "-local", "local-", "Ünicode"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                identity.use(name, LocalForm())

    def test_a_name_is_normalized_the_way_the_refusal_compares_it(self):
        identity.use("  Keycloak  ", RedirectFlow())
        claimed = identity.door("keycloak")
        assert claimed is not None
        self.assertEqual(claimed.name, "keycloak")
        self.assertEqual(claimed.route, "/login/keycloak")

    def test_an_unidentified_caller_is_named_rather_than_left_blank(self):
        # `__main__` is what *any* script is called when run directly, so it
        # identifies no installation and the registry keeps nothing (origins.py).
        # The page and the refusal still have to call it something.
        claim = _from_module("__main__")
        claim("local", LocalForm())
        claimed = identity.door("local")
        assert claimed is not None
        self.assertEqual(claimed.package, "")
        self.assertEqual(claimed.owner, identity.UNIDENTIFIED)
        with self.assertRaises(identity.DoorConflictError) as caught:
            _from_package("second_package")("local", LocalForm())
        self.assertIn(identity.UNIDENTIFIED, str(caught.exception))

    def test_registered_doors_is_empty_where_nothing_registered(self):
        self.assertEqual(identity.registered_doors(), ())
        self.assertIsNone(identity.default_door())
        self.assertIsNone(identity.door("local"))


class ReadPathTests(_DeploymentCase):
    """One provider is asked, and which one is not a search."""

    def test_a_second_door_is_never_consulted_for_a_session_it_did_not_open(self):
        # The property the design rests on. Two doors stand; a session is opened at
        # one; the other is not asked — not asked *second*, not asked at all — so
        # there is no order for anybody to get wrong and no rule needed for two
        # directories that know one name.
        entered = LocalForm()
        other = LocalForm(name="other")
        _from_package("first_package")("local", entered, default=True)
        _from_package("second_package")("other", other)
        self.client.post("/login/local", data={"username": "pan"})
        other.asked = 0
        entered.asked = 0
        self.assertEqual(self.client.get("/events").status_code, 200)
        self.assertEqual(other.asked, 0)
        self.assertGreater(entered.asked, 0)

    def test_outside_a_request_there_is_nobody_and_no_door(self):
        # A context processor or a template helper may run without a request, and
        # neither is an error.
        self.assertEqual(identity.session_door(), "")
        self.assertIsNone(identity.current_user())

    def test_the_door_that_opened_the_session_is_recorded(self):
        _from_package("first_package")("local", LocalForm(), default=True)
        _from_package("second_package")("other", LocalForm(name="other"))
        self.client.post("/login/other", data={"username": "pan"})
        with self.client.session_transaction() as stored:
            self.assertEqual(stored[identity.DOOR_KEY], "other")

    def test_a_session_whose_door_is_gone_is_nobody_rather_than_somebody_else(self):
        # A door can be unregistered between restarts. Falling through to another
        # provider would resolve a stored name against a directory that never
        # issued it — the one failure a `set_by` cannot be repaired from.
        _from_package("first_package")("local", LocalForm(), default=True)
        _from_package("second_package")("other", LocalForm(name="other"))
        self.client.post("/login/other", data={"username": "pan"})
        identity.forget_doors()
        survivor = LocalForm()
        _from_package("first_package")("local", survivor, default=True)
        page = self.client.get("/events")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(survivor.asked, 0)

    def test_a_request_carrying_no_door_goes_to_the_default(self):
        # The header-verifying provider's whole case: it writes no session, so it
        # answers for requests that carry no door — and it is the only door that
        # could have, which is what makes that unambiguous too.
        _from_package("balancer")("header", SignedHeader(), default=True)
        page = self.client.get("/events",
                               headers={SignedHeader.HEADER: "pan"})
        self.assertEqual(page.status_code, 200)
        with self.client.session_transaction() as stored:
            self.assertNotIn("username", stored)

    def test_the_provider_is_asked_once_per_request(self):
        # The gate asks, `signed_in()` asks again inside the view, and the avatar
        # context processor asks a third time. For this provider that would be three
        # signature checks of one header.
        provider = SignedHeader()
        _from_package("balancer")("header", provider, default=True)
        self.client.get("/events", headers={SignedHeader.HEADER: "pan"})
        self.assertEqual(provider.asked, 1)

    def test_a_provider_that_raises_is_nobody_and_says_so_in_the_log(self):
        broken = Broken()
        _from_package("deployment_x")("keycloak", broken, default=True)
        with self.assertLogs("little_sister", level="ERROR") as caught:
            page = self.client.get("/events")
        self.assertEqual(page.status_code, 302)
        self.assertGreater(broken.asked, 0)
        self.assertIn("keycloak", "\n".join(caught.output))

    def test_a_broken_door_does_not_take_the_others_with_it(self):
        # Which is the whole reason the doors are separate: the provider stopping
        # is not independent of everything else going wrong.
        _from_package("deployment_x")("keycloak", Broken(), default=True)
        _from_package("first_package")("local", LocalForm())
        with self.assertLogs("little_sister", level="ERROR"):
            self.client.get("/events")
        self.assertEqual(self.client.get("/login/local").status_code, 200)

    def test_signing_in_answers_the_same_request_as_the_new_identity(self):
        # `sign_in` drops the request's cached answer; without that a provider that
        # renders a page after signing somebody in would render it as a stranger.
        _from_package("first_package")("local", LocalForm(), default=True)
        with app_module.app.test_request_context("/login/local"):
            self.assertIsNone(identity.current_user())
            identity.sign_in(Identity(name="pan", admin=True))
            answered = identity.current_user()
            assert answered is not None
            self.assertEqual(answered.name, "pan")


class RouteShapeTests(_DeploymentCase):
    """A fixed route shape the library owns, dispatching on the name in the path —
    so a provider never registers a route of its own."""

    def test_the_default_doors_form_answers_at_the_bare_login_path(self):
        _from_package("first_package")("local", LocalForm(), default=True)
        page = self.client.get(identity.LOGIN_PATH)
        self.assertEqual(page.status_code, 200)
        self.assertIn("form for local", page.get_data(as_text=True))

    def test_each_door_answers_at_its_own_route(self):
        _from_package("first_package")("local", LocalForm(), default=True)
        _from_package("second_package")("other", LocalForm(name="other"))
        page = self.client.get("/login/other")
        self.assertEqual(page.status_code, 200)
        self.assertIn("form for other", page.get_data(as_text=True))

    def test_a_door_name_nothing_claims_is_a_404(self):
        _from_package("first_package")("local", LocalForm(), default=True)
        self.assertEqual(self.client.get("/login/nowhere").status_code, 404)
        self.assertEqual(
            self.client.get("/auth/callback/nowhere").status_code, 404)

    def test_an_unimplemented_hook_answers_404(self):
        # A way in this deployment does not have. A redirect there risks a loop.
        self.assertEqual([hook for hook in identity.OPTIONAL_HOOKS
                          if hasattr(SignedHeader, hook)], [])
        _from_package("balancer")("header", SignedHeader(), default=True)
        self.assertEqual(self.client.get("/login/header").status_code, 404)
        self.assertEqual(self.client.post("/login/header").status_code, 404)
        self.assertEqual(self.client.get("/auth/callback/header").status_code,
                         404)
        self.assertEqual(self.client.get(identity.LOGIN_PATH).status_code, 404)

    def test_a_callback_completes_a_login_and_records_its_own_door(self):
        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        page = self.client.get("/auth/callback/keycloak?as=pan")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/status")
        with self.client.session_transaction() as stored:
            self.assertEqual(stored[identity.DOOR_KEY], "keycloak")
        self.assertEqual(self.client.get("/events").status_code, 200)

    def test_a_stranger_is_challenged_by_the_default_door(self):
        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        page = self.client.get("/events")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], RedirectFlow.AUTHORIZE)

    def test_a_challenge_may_be_a_bare_401_where_there_is_no_flow(self):
        _from_package("balancer")("header", SignedHeader(), default=True)
        self.assertEqual(self.client.get("/events").status_code, 401)

    def test_an_expired_session_is_challenged_by_its_own_door(self):
        # Sent back where it came from, rather than to the default — still exactly
        # one provider asked.
        _from_package("balancer")("header", SignedHeader(), default=True)
        _from_package("first_package")("local", LocalForm())
        self.client.post("/login/local", data={"username": "pan"})
        with self.client.session_transaction() as stored:
            stored.pop("username")
        page = self.client.get("/events")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/login/local")

    def test_logout_runs_the_doors_end_session_and_clears_the_session(self):
        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        self.client.get("/auth/callback/keycloak?as=pan")
        page = self.client.get(identity.LOGOUT_PATH)
        self.assertEqual(page.headers["Location"], RedirectFlow.END_SESSION)
        with self.client.session_transaction() as stored:
            self.assertEqual(dict(stored), {})

    def test_logout_works_at_a_door_with_no_end_session_of_its_own(self):
        # `/logout` has to work whatever the provider does, so an unimplemented
        # `end_session` is the one optional hook that is not a 404.
        _from_package("first_package")("local", LocalForm(), default=True)
        self.client.post("/login/local", data={"username": "pan"})
        page = self.client.get(identity.LOGOUT_PATH)
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], identity.LOGIN_PATH)
        with self.client.session_transaction() as stored:
            self.assertEqual(dict(stored), {})

    def test_the_login_routes_need_no_identity(self):
        for endpoint in ("login", "login_door", "login_callback", "logout"):
            with self.subTest(endpoint=endpoint):
                self.assertFalse(identity.needs_identity(endpoint))


class BuiltInDoorTests(_Case):
    """The built-in login list is a provider like any other (ADR-0069 §3).

    An install that calls ``use_local()`` keeps the login it always had — the case
    that needs no implementation at all, which is the install this project protects
    — and what these hold is that *nothing a visitor sees changed* while the
    mechanism underneath became a door somebody registers.
    """

    def test_registering_it_makes_it_the_default_door(self):
        door = identity.default_door()
        assert door is not None
        self.assertEqual(door.name, local_login.DOOR_NAME)
        self.assertIsInstance(door.provider, local_login.LocalUsers)
        # `little_sister` because `use_local()` is the caller the registry sees —
        # it is the library's provider on the library's door, however many
        # deployments write the line.
        self.assertEqual(door.package, "little_sister")

    def test_it_can_be_a_second_door_beside_somebody_elses_default(self):
        # `default=False` is the shape for a small local list kept beside a
        # directory: its own route, never `/login`.
        identity.forget_doors()
        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        local_login.use_local(default=False)
        standing = identity.default_door()
        assert standing is not None
        self.assertEqual(standing.name, "keycloak")
        self.assertEqual(
            self.client.get(f"/login/{local_login.DOOR_NAME}").status_code, 200)

    def test_it_signs_somebody_in_at_the_address_every_install_has(self):
        page = self.client.post("/login",
                                data={"username": "pan", "password": "12345678"})
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/status")
        self.assertEqual(self.client.get("/events").status_code, 200)

    def test_the_session_now_records_the_door_it_came_through(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        with self.client.session_transaction() as stored:
            self.assertEqual(stored[identity.DOOR_KEY], local_login.DOOR_NAME)

    def test_it_also_answers_at_its_own_route(self):
        page = self.client.get(f"/login/{local_login.DOOR_NAME}")
        self.assertEqual(page.status_code, 200)
        signed_in = self.client.post(f"/login/{local_login.DOOR_NAME}",
                                     data={"username": "pan",
                                           "password": "12345678"})
        self.assertEqual(signed_in.headers["Location"], "/status")

    def test_a_stranger_is_still_sent_to_the_login_form(self):
        page = self.client.get("/events")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], identity.LOGIN_PATH)

    def test_a_wrong_password_is_refused_the_way_it_always_was(self):
        with self.assertLogs("little_sister", level="WARNING") as caught:
            page = self.client.post("/login",
                                    data={"username": "pan", "password": "nope"})
        self.assertEqual(page.status_code, 200)
        self.assertIn("Invalid username or password", page.get_data(as_text=True))
        self.assertIn("pan", "\n".join(caught.output))
        self.assertNotIn("nope", "\n".join(caught.output))
        self.assertEqual(self.client.get("/events").status_code, 302)

    def test_an_unknown_login_is_refused_in_the_same_words(self):
        # Telling the two apart tells a stranger which logins exist.
        page = self.client.post("/login",
                                data={"username": "nobody", "password": "nope"})
        self.assertIn("Invalid username or password", page.get_data(as_text=True))

    def test_logout_still_clears_the_session(self):
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        page = self.client.get(identity.LOGOUT_PATH)
        self.assertEqual(page.headers["Location"], identity.LOGIN_PATH)
        with self.client.session_transaction() as stored:
            self.assertEqual(dict(stored), {})

    def test_it_has_no_callback_of_its_own(self):
        self.assertEqual(
            self.client.get(f"/auth/callback/{local_login.DOOR_NAME}").status_code,
            404)

    def test_the_avatars_are_the_aspect_s_and_follow_the_provider(self):
        self.assertIn("pan", local_login.registered_avatars())
        identity.forget_doors()
        _from_package("balancer")("header", SignedHeader(), default=True)
        self.assertEqual(local_login.registered_avatars(), {})
        self.assertIsNone(local_login.registered())

    def test_the_library_adds_no_door_beside_a_deployments_own(self):
        # The rule §3 replaced an inference with: an install
        # gets the doors it registered and not one more, so a deployment with a
        # provider of its own has exactly one — no password door appearing beside
        # it, which would be the door nobody asked for and nobody watches.
        identity.forget_doors()
        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        self.assertEqual([door.name for door in identity.registered_doors()],
                         ["keycloak"])
        self.assertIsNone(local_login.registered())


class ChoosingAtLoginTests(_DeploymentCase):
    """`/login` may offer the doors instead of going to the default one.

    The claim of the slice is a **pair**, and the test that matters most here is
    `test_the_choice_is_offered_while_the_challenge_still_redirects`: what somebody
    who *types* `/login` gets changed, and what an unidentified request gets did
    not. Asserting those apart would let either half pass alone, and the half that
    would fail silently is the second — a chooser in the challenge path costs a
    click on every visit forever and nothing about the page would look wrong.
    """

    def _keycloak(self) -> Offered:
        provider = Offered()
        _from_package("deployment_x")("keycloak", provider, default=True,
                                      label="Company SSO")
        return provider

    def test_the_choice_is_offered_while_the_challenge_still_redirects(self):
        self._keycloak()
        local_login.use_local(default=False)
        identity.choose_at_login()

        page = self.client.get(identity.LOGIN_PATH)
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertIn('href="/login/keycloak"', body)
        self.assertIn("Company SSO", body)
        self.assertIn('href="/login/local"', body)

        # …and the other half, against the same provider: an unidentified request
        # is still sent straight to the identity provider, so a live SSO session
        # still arrives logged in having seen no page at all.
        gated = self.client.get("/events")
        self.assertEqual(gated.status_code, 302)
        self.assertEqual(gated.headers["Location"], RedirectFlow.AUTHORIZE)

    def test_a_doors_own_route_starts_its_flow_so_the_page_is_not_a_loop(self):
        # The trap this shape exists to avoid: were the chooser something a
        # provider returned from `login_page()`, both routes that reach that method
        # would render it, and the entry for its own door would lead back to the
        # page it was on. `/login` is the chooser and `/login/<door>` is the
        # provider's, which is what makes the link go somewhere.
        self._keycloak()
        identity.choose_at_login()
        own = self.client.get("/login/keycloak")
        self.assertEqual(own.status_code, 302)
        self.assertEqual(own.headers["Location"], RedirectFlow.AUTHORIZE)

    def test_a_provider_with_no_login_page_of_its_own_cannot_be_offered(self):
        # What `Offered` adds and why. A redirecting provider that only implements
        # `challenge()` has no address of its own to send anybody to, so it is not
        # in the chooser and `/login/<door>` is a 404 — the one method a deployment
        # adds to appear on that page is a `login_page()` that starts its flow.
        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        claimed = identity.door("keycloak")
        assert claimed is not None
        self.assertFalse(claimed.enterable)
        self.assertEqual(self.client.get("/login/keycloak").status_code, 404)

    def test_the_bare_login_takes_no_credential(self):
        # A door takes a credential at its own route. `/login` is a page now, not a
        # door, so a form posting there is refused rather than quietly reaching the
        # default door's `submit_login`.
        local_login.use_local()
        identity.choose_at_login()
        self.assertEqual(
            self.client.post(identity.LOGIN_PATH,
                             data={"username": "pan",
                                   "password": "12345678"}).status_code, 404)
        signed_in = self.client.post(f"{identity.LOGIN_PATH}/local",
                                     data={"username": "pan",
                                           "password": "12345678"})
        self.assertEqual(signed_in.headers["Location"], "/status")

    def test_without_the_line_login_is_the_default_doors_own_step(self):
        # Opt-in, and this is what says so: two enterable doors are not by
        # themselves a request for a menu.
        local_login.use_local()
        self.assertFalse(identity.choosing_at_login())
        body = self.client.get(identity.LOGIN_PATH).get_data(as_text=True)
        self.assertIn('name="password"', body)

    def test_forgetting_the_doors_forgets_the_choice(self):
        identity.choose_at_login()
        identity.forget_doors()
        self.assertFalse(identity.choosing_at_login())


class OfferedDoorTests(_DeploymentCase):
    """Which doors the chooser offers: the ones that can be entered right now."""

    def test_a_door_with_no_login_page_is_not_offered(self):
        # The load-balancer provider, which performs no login at all. It is not a
        # defect and not a shut door — there is simply no page to send anybody to.
        _from_package("balancer")("header", SignedHeader(), default=True)
        claimed = identity.door("header")
        assert claimed is not None
        self.assertFalse(claimed.enterable)
        identity.choose_at_login()
        self.assertNotIn("/login/header",
                         self.client.get(identity.LOGIN_PATH).get_data(as_text=True))

    def test_a_door_that_says_it_cannot_be_entered_is_not_offered(self):
        class Shut(LocalForm):
            def enterable(self) -> bool:
                return False

        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        _from_package("deployment_x")("closed", Shut("closed"))
        claimed = identity.door("closed")
        assert claimed is not None
        self.assertFalse(claimed.enterable)
        identity.choose_at_login()
        self.assertNotIn("/login/closed",
                         self.client.get(identity.LOGIN_PATH).get_data(as_text=True))

    def test_a_provider_that_says_nothing_can_be_entered(self):
        local_login.use_local()
        claimed = identity.door(local_login.DOOR_NAME)
        assert claimed is not None
        self.assertTrue(claimed.enterable)

    def test_the_default_door_is_offered_first(self):
        _from_package("deployment_x")("aaa", LocalForm("aaa"))
        local_login.use_local()
        identity.choose_at_login()
        body = self.client.get(identity.LOGIN_PATH).get_data(as_text=True)
        # `aaa` sorts before `local` in the registry, and the default still leads.
        self.assertLess(body.index('href="/login/local"'),
                        body.index('href="/login/aaa"'))

    def test_one_offered_door_is_still_a_page(self):
        # The load-balancer installation: nothing to type a password into except
        # the library's own door. Sending somebody straight through would be this
        # module choosing for them.
        _from_package("balancer")("header", SignedHeader(), default=True)
        _from_package("deployment_x")("rescue", LocalForm("rescue"))
        identity.choose_at_login()
        page = self.client.get(identity.LOGIN_PATH)
        self.assertEqual(page.status_code, 200)
        self.assertIn('href="/login/rescue"', page.get_data(as_text=True))


class FailingHookTests(_DeploymentCase):
    """A provider that raises takes down **its own door and no other** (ADR-0069 §7).

    `identify()` has said so since 5a. These are the two hooks that grew later and
    did not, and both fail in the same direction: they are asked at the moment the
    thing behind them has stopped answering.
    """

    def test_a_raising_enterable_leaves_the_page_standing_for_the_others(self):
        # The likely shape of it: `enterable()` invites *can this door take a
        # credential right now*, which a provider author will write as a probe of
        # the identity provider — the thing that is down on the morning somebody is
        # reading this page.
        class Unreachable(LocalForm):
            def enterable(self) -> bool:
                raise RuntimeError("the directory is unreachable")

        _from_package("deployment_x")("keycloak", Unreachable("keycloak"),
                                      default=True)
        local_login.use_local(default=False)
        identity.choose_at_login()
        with self.assertLogs("little_sister", level="ERROR") as caught:
            page = self.client.get(identity.LOGIN_PATH)
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertNotIn('href="/login/keycloak"', body)
        self.assertIn('href="/login/local"', body)
        self.assertIn("keycloak", "\n".join(caught.output))

    def test_a_raising_end_session_still_logs_somebody_out(self):
        # The worst outcome is the quiet one: a 500 from `/logout` with the session
        # intact looks like an error page either way, and nobody checks.
        class Rude(LocalForm):
            def end_session(self):
                raise RuntimeError("cannot reach the end-session endpoint")

        _from_package("deployment_x")("rude", Rude("rude"), default=True)
        self.client.post("/login/rude", data={"username": "pan"})
        self.assertEqual(self.client.get("/events").status_code, 200)

        with self.assertLogs("little_sister", level="ERROR") as caught:
            page = self.client.get(identity.LOGOUT_PATH)
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], identity.LOGIN_PATH)
        self.assertIn("rude", "\n".join(caught.output))
        with self.client.session_transaction() as stored:
            self.assertEqual(dict(stored), {})
        self.assertEqual(self.client.get("/events").status_code, 302)


class DoorLabelTests(_DeploymentCase):
    def test_a_label_defaults_to_the_name(self):
        _from_package("deployment_x")("keycloak", RedirectFlow())
        claimed = identity.door("keycloak")
        assert claimed is not None
        self.assertEqual(claimed.label, "keycloak")

    def test_a_label_is_what_a_page_prints(self):
        _from_package("deployment_x")("keycloak", RedirectFlow(),
                                      label="  Company SSO  ")
        claimed = identity.door("keycloak")
        assert claimed is not None
        self.assertEqual(claimed.label, "Company SSO")

    def test_a_blank_label_falls_back_rather_than_printing_nothing(self):
        _from_package("deployment_x")("keycloak", RedirectFlow(), label="   ")
        claimed = identity.door("keycloak")
        assert claimed is not None
        self.assertEqual(claimed.label, "keycloak")

    def test_the_librarys_own_doors_bring_words_rather_than_path_segments(self):
        # The default is the name, which is right for a door the deployment named
        # and wrong for the two the library ships: a chooser reading `local` and
        # `system-admin` is a page printing its own URL structure at somebody.
        local_login.use_local()
        claimed = identity.door(local_login.DOOR_NAME)
        assert claimed is not None
        self.assertEqual(claimed.label, "Local account")


class MissingDoorTests(_DeploymentCase):
    """An omission logs and the instance serves; only a contradiction refuses.

    Two states are covered, and the reason neither stops the process is the same:
    nobody has said two things that cannot both be true, somebody has not yet
    written a line. Refusing to start over that takes a monitoring application down
    for a configuration mistake it can describe instead — and it would refuse the
    *more* usable of the two, since doors-without-a-default still admits anybody
    who knows ``/login/<door>``.
    """

    def test_the_system_admin_door_alone_is_a_door_and_the_line_is_warn(self):
        """The ERROR on the node is for an instance *nobody* can sign in to. The
        system-admin door is a way in, so an installation with only that door — an
        identity provider not yet wired, say — is WARN like any door set without a
        default, never ERROR."""
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        system_admin.use_system_admin(password="only-for-this-test")
        with self.assertLogs("little_sister", level="WARNING"):
            identity.announce_doors()
        (line,) = [line for line in self_report.startup.lines()
                   if line.slug == "doors"]
        self.assertIs(line.code, StatusCode.WARN)
        self.assertIn("'system-admin'", line.text)
        self.assertNotIn("nobody can sign in", line.text)

    def test_doors_without_a_default_warn_and_name_what_was_found(self):
        _from_package("deployment_x")("keycloak", RedirectFlow())
        with self.assertLogs("little_sister", level="WARNING") as caught:
            identity.announce_doors()
        message = "\n".join(caught.output)
        self.assertIn("'keycloak'", message)
        self.assertIn("deployment_x", message)
        self.assertIn("default=True", message)

    def test_no_door_at_all_warns_and_says_which_line_is_missing(self):
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        with self.assertLogs("little_sister", level="WARNING") as caught:
            identity.announce_doors()
        message = "\n".join(caught.output)
        self.assertIn("nobody can sign in", message)
        self.assertIn("local_login.use_local()", message)
        self.assertIn("identity.use(", message)
        # And on the node, at ERROR: an instance nobody can sign in to has lost
        # its readers (backlog #70).
        (line,) = self_report.startup.lines()
        self.assertEqual(line.slug, "doors")
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertIn("nobody can sign in", line.text)

    def test_a_default_door_is_announced_at_info_and_warns_about_nothing(self):
        _from_package("deployment_x")("keycloak", RedirectFlow(), default=True)
        with self.assertLogs("little_sister", level="INFO") as caught:
            identity.announce_doors()
        message = "\n".join(caught.output)
        self.assertIn("'keycloak'", message)
        self.assertNotIn("WARNING", message)

    def test_the_line_names_the_door_it_hands_to_and_not_where_anybody_lands(self):
        """The default door is what answers an unidentified request; **where that
        request ends up** is its `challenge()`, which is the provider's to write.

        This line used to say the request *goes to* the default door, and on the
        installation that found it that was false: its provider answers `/login`
        on purpose, because authenticating there is not the same as being admitted
        and a redirect would wall a non-member on every visit. §1 allows three
        shapes of `challenge()` and the library cannot see which one it has — so
        the line says what it knows, which is the door, and hands the destination
        back to the method that decides it."""
        _from_package("deployment_x")("keycloak", Offered(), default=True)
        identity.choose_at_login()
        with self.assertLogs("little_sister", level="INFO") as caught:
            identity.announce_doors()

        message = "\n".join(caught.output)
        self.assertIn("handed to 'keycloak'", message)
        self.assertIn("challenge()", message)
        self.assertNotIn("goes to 'keycloak'", message)

    def test_a_door_without_a_default_still_admits_anybody_who_knows_its_route(self):
        # Why this state is a warning rather than a refusal: it is *more* usable
        # than the one below, not less.
        local_login.use_local(default=False)
        self.assertEqual(self.client.get(identity.LOGIN_PATH).status_code, 404)
        signed_in = self.client.post(f"/login/{local_login.DOOR_NAME}",
                                     data={"username": "pan",
                                           "password": "12345678"})
        self.assertEqual(signed_in.headers["Location"], "/status")
        self.assertEqual(self.client.get("/events").status_code, 200)

    def test_no_default_but_a_chooser_says_the_instance_is_still_usable(self):
        # The same omission on an installation where it costs less: `/login` is a
        # page we serve, so an unidentified request has somewhere to land. The line
        # still asks for the missing `default=True` — nothing says which door this
        # installation expects anybody to use — but it must not go on claiming a
        # `404` and a request with nowhere to be sent, both of which are false here.
        _from_package("deployment_x")("keycloak", Offered())
        identity.choose_at_login()
        with self.assertLogs("little_sister", level="WARNING") as caught:
            identity.announce_doors()
        message = "\n".join(caught.output)
        self.assertIn("'keycloak'", message)
        self.assertIn("default=True", message)
        self.assertNotIn("nowhere to be sent", message)

    def test_an_unidentified_request_is_refused_where_no_door_exists_at_all(self):
        # Not a redirect to a login page that is itself a 404: nothing can take a
        # credential, so there is nowhere to send anybody.
        #
        # The **level** is half the claim. `announce_doors()` said this once at
        # startup, which is where §2 puts the line an operator reads; per request
        # it is diagnostic detail, and an ERROR on every gated hit of an instance
        # that is merely unconfigured is the kind of loudness that trains somebody
        # to stop reading the log.
        with self.assertLogs("little_sister", level="DEBUG") as caught:
            page = self.client.get("/events")
        self.assertEqual(page.status_code, 401)
        refusal = [line for line in caught.output
                   if "Refusing an unidentified request" in line]
        self.assertEqual(len(refusal), 1, caught.output)
        self.assertTrue(refusal[0].startswith("DEBUG:"), refusal[0])


class ClosedDefaultTests(_DeploymentCase):
    """A default door can **stop being there**, and that is nobody's omission.

    §5 closes a door whose credential did not resolve and keeps the application
    serving; §2 treats *doors with none of them the default* as a line somebody has
    not written yet. Together they describe an instance nobody misconfigured — doors
    that work, no default — and what that used to cost was out of all proportion to
    it: a `401` on every gated request while `/login` was rendering a chooser
    listing the door that would have let somebody in.

    **The pair that matters is the first two cases.** Sending an unidentified
    request to `/login` is right only where `/login` is a page *we* serve. Without
    `choose_at_login()` that address is the default door's own step and answers
    `404` while there is no default, so the same redirect would lead into a dead
    end and the refusal is the honest answer. Asserting either case alone would let
    a fix that simply always redirects pass.
    """

    def test_a_closed_default_sends_an_unidentified_request_to_the_chooser(self):
        local_login.use_local(default=False)
        identity.choose_at_login()
        page = self.client.get("/events")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], identity.LOGIN_PATH)
        # …and the address it names is a page carrying the door that still works,
        # which is the whole of what the redirect is worth.
        offered = self.client.get(identity.LOGIN_PATH)
        self.assertEqual(offered.status_code, 200)
        self.assertIn(f'href="{identity.LOGIN_PATH}/{local_login.DOOR_NAME}"',
                      offered.get_data(as_text=True))

    def test_without_the_chooser_a_closed_default_is_still_refused(self):
        local_login.use_local(default=False)
        self.assertEqual(self.client.get(identity.LOGIN_PATH).status_code, 404)
        self.assertEqual(self.client.get("/events").status_code, 401)

    def test_the_chooser_alone_does_not_make_a_doorless_instance_answer(self):
        # `choose_at_login()` with nothing registered would offer a page with no
        # entries on it. Nothing can take a credential, so 401 stays the answer and
        # the redirect is decided by the registry rather than by the line alone.
        identity.choose_at_login()
        self.assertEqual(self.client.get("/events").status_code, 401)

    def test_the_refusal_names_which_of_the_two_states_it_is_in(self):
        # It used to say "No identity door is registered" in both, which is false
        # in the second and is the sentence somebody debugging would act on.
        with self.assertLogs("little_sister", level="DEBUG") as caught:
            self.client.get("/events")
        self.assertIn("no identity door is registered", "\n".join(caught.output))

        identity.forget_doors()
        local_login.use_local(default=False)
        with self.assertLogs("little_sister", level="DEBUG") as caught:
            self.client.get("/events")
        message = "\n".join(caught.output)
        self.assertIn("none of them is the default", message)
        self.assertNotIn("no identity door is registered", message)

    def test_where_to_send_an_unidentified_request_is_never_a_probe(self):
        # `enterable()` is allowed to reach the identity provider — §7 guards it
        # against raising for exactly that reason — and this branch runs on every
        # unidentified request. So the **registry** answers it: the door is asked
        # once, when the page it is offered on is rendered, and not at all on the
        # way there.
        class Probing(Offered):
            def __init__(self) -> None:
                super().__init__()
                self.probes = 0

            def enterable(self) -> bool:
                self.probes += 1
                return True

        provider = Probing()
        _from_package("deployment_x")("keycloak", provider, label="Company SSO")
        identity.choose_at_login()
        self.assertEqual(self.client.get("/events").status_code, 302)
        self.assertEqual(provider.probes, 0)
        self.client.get(identity.LOGIN_PATH)
        self.assertEqual(provider.probes, 1)


def _start(script: str, root: Path) -> subprocess.CompletedProcess:
    """Run *script* as its own process against a configuration root of its own."""
    environment = os.environ.copy()
    environment["LITTLE_SISTER_CONFIG_DIR"] = str(root)
    environment["LITTLE_SISTER_ENGINE"] = "0"
    environment["SECRET_KEY"] = "identity-doors"
    environment.pop("LITTLE_SISTER_USERS", None)
    return subprocess.run([sys.executable, "-c", script], cwd=_REPO,
                          env=environment, capture_output=True, text=True,
                          timeout=120)


def _config_without_users(directory: str) -> Path:
    """A configuration root carrying checks and no ``users`` aspect at all."""
    root = Path(directory) / "config"
    (root / "checks").mkdir(parents=True)
    (root / "checks" / "one.yaml").write_text(
        "name: one\ntype: http\nurl: http://localhost:1/\nfrequency: 1h\n",
        encoding="utf-8")
    return root


class NoUsersAspectTests(TestCase):
    """The promise 5b exists for: a deployment with a provider of its own needs no
    ``users.yaml`` — and until the list moved behind a door it could not start.

    In a subprocess, because what has to be pinned is the **import**: the user list
    used to be read while ``little_sister.app`` was being imported, so a deployment
    without one died there, before any of this could be asked a question. The same
    reason covers the cases below it, where what is under test is that importing the
    application registers nothing and refuses nothing.
    """

    def test_an_instance_with_a_provider_and_no_user_list_serves_and_logs_in(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = _start(_PROVIDER_ONLY, _config_without_users(directory))
        self.assertEqual(completed.returncode, 0,
                         f"{completed.stdout}\n{completed.stderr}")
        self.assertIn("SERVED", completed.stdout)
        self.assertIn("SIGNED-IN", completed.stdout)

    def test_importing_the_app_registers_no_door_and_reads_no_user_list(self):
        # The heart of §3, and only a subprocess can hold it: an
        # install that registers nothing has nothing, rather than the built-in list
        # the library used to add on its behalf — and *therefore* never looks for a
        # `users.yaml`, which is why this passes against a config root with none.
        with tempfile.TemporaryDirectory() as directory:
            completed = _start(_NOTHING_REGISTERED,
                               _config_without_users(directory))
        self.assertEqual(completed.returncode, 0,
                         f"{completed.stdout}\n{completed.stderr}")
        self.assertIn("DOORS []", completed.stdout)
        self.assertIn("SERVED", completed.stdout)
        # It serves, and it lets nobody in — both halves, or "it starts" would be
        # a claim about a process rather than about an application.
        self.assertIn("GATED 401", completed.stdout)
        self.assertIn("LOGIN 404", completed.stdout)
        self.assertIn("nobody can sign in", completed.stderr)
        # And `/system` with it, which is what lets the identity card on that page
        # carry no empty state: reading the door table means a row of it answered
        # for you, so there is no such thing as looking at it with no doors.
        self.assertIn("SYSTEM 401", completed.stdout)

    def test_a_provider_registered_without_a_default_starts_and_warns(self):
        # The omission rule is only worth anything if the application performs it,
        # which is a claim about `app.py` rather than about `identity`.
        with tempfile.TemporaryDirectory() as directory:
            completed = _start(_PROVIDER_ONLY.replace(", default=True", ""),
                               _config_without_users(directory))
        self.assertEqual(completed.returncode, 0,
                         f"{completed.stdout}\n{completed.stderr}")
        self.assertIn("SERVED", completed.stdout)
        self.assertIn("none of them is the default", completed.stderr)
        self.assertIn("'header'", completed.stderr)


#: Registered before the app is imported, which is the whole point of the slot.
_PROVIDER_ONLY = """
from flask import request
from little_sister import identity


class SignedHeader:
    def identify(self):
        who = request.headers.get("X-Assertion", "")
        return identity.Identity(name=who, admin=True) if who else None

    def challenge(self):
        return "unauthorized", 401


identity.use("header", SignedHeader(), default=True)

import little_sister.app as app_module

client = app_module.app.test_client()
if client.get("/health").status_code == 200:
    print("SERVED")
if client.get("/events", headers={"X-Assertion": "pan"}).status_code == 200:
    print("SIGNED-IN")
"""

#: An installation that registers nothing at all — the state the library used to
#: make impossible by adding the built-in list itself.
_NOTHING_REGISTERED = """
import little_sister.app as app_module

from little_sister import identity

print("DOORS", [door.name for door in identity.registered_doors()])

client = app_module.app.test_client()
if client.get("/health").status_code == 200:
    print("SERVED")
print("GATED", client.get("/events").status_code)
print("LOGIN", client.get("/login").status_code)
print("SYSTEM", client.get("/system").status_code)
"""


if __name__ == "__main__":
    unittest.main()
