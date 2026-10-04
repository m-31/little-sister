"""The one door the library ships, and it is not a provider's (ADR-0069 §5).

A monitoring application that becomes unreachable when the identity provider is down
is missing in the one hour it exists for — and *the identity provider is down* and
*something is wrong* are not independent events. So there is one account this
application keeps itself: login name ``admin``, on a door of its own, with a password
the deployment **registers in code** beside everything else it registers.

**A door of its own matters mechanically rather than stylistically.** Under a provider
that redirects, ``/login`` never renders a local form — when Keycloak is down there is
nothing to type a password into. ``/login/system-admin`` is always a local form while
the account is usable, and ``404`` when it is not.

**What keeps it narrow**, stated here so the next person asking has an answer: one
account, no second; a fixed name; no role beyond ``admin``; and no configuration for
adding another. A deployment that wants a second population wants a provider on a door
of its own, which :func:`little_sister.identity.use` already gives it.

**It is visible while it is in use** — a distinct packaged avatar and a display name
in the chrome of every page, a ``WARNING`` per login, and a row on ``/system``.
Deliberately no page banner: three channels are enough and the fourth is shouting.
The risk this guards is not the login, it is the session left open for a week after
the incident.
"""
from __future__ import annotations

from flask import abort, redirect, render_template, request
from flask.typing import ResponseReturnValue

from little_sister import identity, self_report
from little_sister.identity import Identity
from little_sister.logger import logger
from little_sister.reasons import plain
from little_sister.secrets import (
    SecretError,
    looks_like_reference,
    resolve,
    same_secret,
)

#: The door's name in the URL space, and what a runbook calls it. Hard-coded, like
#: the login name: a configurable one is a knob whose only effect is to make a
#: runbook and an instance disagree.
DOOR_NAME = identity.SYSTEM_ADMIN_DOOR

#: The one login name this account has.
LOGIN_NAME = "admin"

#: What the chrome shows beside the distinct avatar. The settings menu prints the
#: identity's ``firstname`` on every page, so this is the cheapest place to say
#: *which door you came through* in words as well as in a picture.
DISPLAY_NAME = "System admin"

#: What a chooser calls this door out loud (ADR-0069 §1), since ``system-admin`` is
#: a path segment. The full word rather than :data:`DISPLAY_NAME`'s abbreviation:
#: the chrome is naming a signed-in person in a narrow menu, while this is a button
#: somebody reads once, under pressure, deciding whether it is the one they want.
LABEL = "System administrator"

#: Which keyword configured the account — shown on ``/system`` and logged at
#: startup, so a deployment that took the discouraged shortcut can be seen to have
#: taken it by somebody who is not reading ``wsgi.py``.
BY_REFERENCE = "reference"
BY_PASSWORD = "password"


class SystemAdmin:
    """The provider behind ``/login/system-admin``.

    It has a local form and nothing else: no callback, no end-session step, and no
    directory to ask. What it holds is one resolved password and whether the
    resolution worked.
    """

    def __init__(self, password: str, *, keyword: str, reference: str = "",
                 problem: str = "") -> None:
        self._password = password
        #: Which keyword the deployment used — :data:`BY_REFERENCE` or
        #: :data:`BY_PASSWORD`.
        self.keyword = keyword
        #: The address, when the credential was named rather than handed over. Shown
        #: on ``/system``, because *the address is wrong* is the failure this account
        #: has, and a reference is not a secret ("a config field names a secret, it
        #: never carries one", ADR-0023). Empty for :data:`BY_PASSWORD`, where the
        #: only thing there is to print would be the password itself.
        self.reference = reference
        #: Why the credential could not be resolved, or ``""``.
        self.problem = problem

    @property
    def available(self) -> bool:
        """Whether the door can actually take a password right now.

        ``False`` when the credential did not resolve: the store was unreachable, or
        the secret is not there. The door stays **registered** in that case, so
        ``/system`` can say *configured but unavailable* rather than looking like a
        deployment that never configured one — and it answers ``404`` like an
        unconfigured door, because there is nothing to check a password against and a
        form that refuses everything would be a crueller way of saying the same thing.
        """
        return bool(self._password)

    def enterable(self) -> bool:
        """Whether this door can take a password right now — the seam's optional
        question (ADR-0069 §1), and the only provider in the library that answers
        it, because it is the only one whose ``login_page`` can be a ``404`` while
        the door is registered."""
        return self.available

    def identify(self) -> Identity | None:
        """The session this door opened, if this request carries one.

        Read from the session rather than re-checked against the password, like
        every other session-based provider: reached only for a request whose session
        names this door (:func:`little_sister.identity.current_user`), so a session
        signed before a restart stays valid exactly as long as the signing key does
        — including when the credential has since stopped resolving.
        """
        return identity.session_identity()

    def challenge(self) -> ResponseReturnValue:
        """Back to this door's own form.

        Reached only for a session this door opened and that has since expired, so
        *its own* route is the right answer and the default door is not: the whole
        point of this account is to be usable when the default cannot answer.
        """
        return redirect(f"{identity.LOGIN_PATH}/{DOOR_NAME}")

    def login_page(self) -> ResponseReturnValue:
        """The small local form, or ``404`` while the account is unusable."""
        if not self.available:
            abort(404)
        return render_template('login.html', error=None, door_note=_NOTE)

    def submit_login(self) -> ResponseReturnValue:
        """Check a submitted password, in constant time, and open a session.

        :func:`~little_sister.secrets.same_secret` rather than ``==``, following the
        API tokens: this is the one credential in the application that an attacker
        can guess at without a directory in the way. The login name is compared the
        same way and to a literal — there is one account and it is not configurable.
        Both sides of both comparisons come off a form, so both may be anything a
        keyboard produces, which is exactly the case that helper exists for.

        Every outcome is a ``WARNING``. A successful login here is an event somebody
        should be able to reconstruct afterwards, and a failed one is somebody
        knocking on the emergency door.
        """
        if not self.available:
            abort(404)
        username = request.form['username']
        password = request.form['password']
        if (same_secret(username, LOGIN_NAME)
                and same_secret(password, self._password)):
            identity.sign_in(Identity(name=LOGIN_NAME, firstname=DISPLAY_NAME,
                                      admin=True))
            # Held rather than standing: a fact for the window, not a condition —
            # and WARN, because this account exists for an incident.
            self_report.security.see(
                "system-admin.used",
                plain(f"the local {LOGIN_NAME!r} account signed in at "
                      f"{identity.LOGIN_PATH}/{DOOR_NAME}. This account exists for "
                      f"when the identity provider cannot answer — close the "
                      f"session when the incident is over"))
            return redirect('/status')
        # WARN for the log entry; the line's own grade is the rate's
        # (`security_lines`), and one failed login is a fact there.
        self_report.security.see(
            self_report.FAILED_LOGIN,
            plain(f"for {username!r} at the system-admin door"))
        return render_template('login.html', door_note=_NOTE,
                               error='Invalid username or password')


#: What the form says about where you are. The ordinary login page and this one are
#: the same document, and a person who typed their usual login name into the wrong
#: one deserves to be told which door this is before they wonder why it refused.
_NOTE = ("System administrator — the local account for when the identity provider "
         "cannot answer.")


def use_system_admin(*, reference: str = "", password: str = "") -> None:
    """Configure the system-admin account. **Exactly one keyword** (ADR-0069 §5).

    ::

        identity.use_system_admin(reference="aws-ssm-live:///little-sister/admin")
        identity.use_system_admin(password=fetched_elsewhere)   # discouraged

    The password is a **registration, not a setting**, and it is resolved **once, at
    registration**: a wrong address is then a startup message rather than a discovery
    during an incident.

    **Each keyword refuses the other's shape.** ``reference=`` goes through
    :func:`little_sister.secrets.resolve`, which already refuses a string with no
    scheme in the words *a config field names a secret, it never carries one* — so a
    password hard-coded in a committed ``wsgi.py`` fails at startup rather than
    quietly working. ``password=`` refuses anything shaped like ``scheme://…``,
    because a reference passed there would silently make the *address* the password.

    ``password=`` exists at all because a deployment whose secret store has no
    little-sister resolver would otherwise be shut out of a feature that exists for
    emergencies — a poor trade. It is discouraged **operationally rather than only in
    prose**: which keyword was used is logged here and shown on ``/system``.

    **A failed resolution closes the door and the application keeps serving.**
    Refusing to start would mean an unreachable parameter store takes the dashboard
    down during exactly the kind of event it is watching — and if the store is
    unreachable, the operator cannot read the password either. A **malformed**
    reference is the other case and still fails startup loudly, because that is a
    typo in the deployment's own code rather than a fact about the world today
    (ADR-0023's split, kept).

    There is **no generation**, ever: a generated password has to be readable by the
    operator, which means the log or a file — a live admin credential on the
    instance's disk, in service of a path nobody uses.
    """
    if bool(reference) == bool(password):
        raise ValueError(
            "use_system_admin() takes exactly one of reference= (a secret "
            "reference such as 'env://LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD', "
            "resolved once at startup) or password= (a value fetched by the "
            "deployment itself, discouraged) — "
            + ("both were given." if reference else "neither was given."))
    if password:
        if looks_like_reference(password):
            raise ValueError(
                "use_system_admin(password=…) was given something shaped like a "
                "secret reference. Pass it as reference= instead: handed over as "
                "the password, the address itself would become the credential, "
                "and nothing would say so until the account was needed.")
        _register(SystemAdmin(password, keyword=BY_PASSWORD))
        logger.info("System-admin account configured with a literal password "
                    "(discouraged; reference= names it in a store instead).")
        return

    try:
        value = resolve(reference)
    except SecretError as error:
        _register(SystemAdmin("", keyword=BY_REFERENCE, reference=reference,
                              problem=str(error)))
        self_report.startup.note(
            "system-admin",
            plain(f"the system-admin password {reference!r} did not resolve "
                  f"({error}); that door is shut and the application keeps "
                  f"serving — /system/installed says so too"))
        return
    _register(SystemAdmin(value, keyword=BY_REFERENCE, reference=reference))
    logger.info("System-admin account configured from %r.", reference)


def _register(provider: SystemAdmin) -> None:
    """Claim the door for ``provider`` — never as the default.

    The default is where ``/login`` and an unidentified request go, and this account
    is neither the way in nor a population: it is the way in *when the way in is not
    answering*. Registering it therefore leaves the built-in login list free to
    register itself as the default afterwards, which is what an install with a user
    list and a system admin gets.
    """
    identity.use(DOOR_NAME, provider, label=LABEL)


def usable_route() -> str:
    """This door's address while it can actually take a password, else ``""``.

    What the built-in login page links to, and the emptiness is the whole reason it
    is a function rather than a constant: :data:`DOOR_NAME` is fixed, but the route
    answers ``404`` on an install that configured no account, and on one whose
    credential did not resolve. A link to either is a link to a dead end, offered at
    the moment somebody is least able to shrug it off.

    **The question is the door's**, not a second copy of it here
    (:attr:`little_sister.identity.Door.enterable`): the chooser asks it too, and two
    rules about whether a way in exists is exactly the sort of pair that drifts and
    then disagrees in the direction nobody tests.

    It says nothing about *this* request — a page that is itself the system-admin
    form must not link to itself, and that is the caller's business to know rather
    than something to work out from the session (:meth:`SystemAdmin.login_page`
    passes nothing).
    """
    door = identity.door(DOOR_NAME)
    return door.route if door is not None and door.enterable else ""


def registered() -> SystemAdmin | None:
    """The configured account if there is one, read off the door registry.

    Off the registry rather than remembered beside it (ADR-0064): a second table is
    a table that can disagree, and here it would disagree about whether a way into
    the application exists.
    """
    door = identity.door(DOOR_NAME)
    provider = door.provider if door is not None else None
    return provider if isinstance(provider, SystemAdmin) else None
