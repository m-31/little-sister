"""The built-in login list, as an identity provider like any other (ADR-0069 §3).

A list of logins in ``config/users/users.yaml`` is exactly right for one thing, and
it is not the thing this application grows into: a personal dashboard on a
developer's machine, running in fifteen seconds with no services behind it. That is
the install this project protects, and a file with two logins in it serves it
perfectly. It is not a login system for a team — **authentication is different in
every organization** — so it is the *fallback for the case that needs no
implementation at all* rather than the shape everybody else has to fit.

Which is why this list is not special — including in how it gets there. It is a
provider on a door (:data:`DOOR_NAME`) that **the installation registers for
itself** (:func:`use_local`), exactly as it would register Keycloak, and everything
the login gate does with it, it does through the same two methods it would call on
Keycloak. Two consequences are the whole point of the move:

* **A deployment with its own provider needs no ``users.yaml`` at all.** The aspect
  is read *here*, at registration, so it is read only when this door is in use.
  Until this module existed the list was loaded when ``little_sister.app`` was
  imported, and a deployment with an identity provider of its own could not start
  without a user list it would never consult.
* **The avatars follow the list.** They belong to the ``users`` aspect
  (ADR-0045), so under another provider there are none and every viewer gets the
  packaged neutral image — which is correct rather than a gap
  (:func:`registered_avatars`).

**Passwords are compared as they are stored: in plain text.** That is ADR-0020's
decision and this module does not quietly change it — a hashed list would be a
better local file and a worse *lie*, because it would look like the answer to a
question this list is not the answer to.
"""
from __future__ import annotations

from flask import redirect, render_template, request
from flask.typing import ResponseReturnValue

from little_sister import identity, self_report, system_admin
from little_sister.identity import Identity
from little_sister.logger import logger
from little_sister.reasons import plain
from little_sister.users import AvatarFile, UsersConfig, load_users

#: The door the built-in list is registered on. It is `local` because that is what
#: it is — the accounts this installation keeps itself — and it is fixed rather than
#: configurable for the reason every other name in this family is: a name a runbook
#: can be wrong about is worse than a name nobody chose.
DOOR_NAME = "local"

#: What a chooser calls this door out loud, since `local` is a path segment and not
#: a sentence (ADR-0069 §1). *Account* rather than *password* because that is what
#: the person has; how it is checked is this list's business and not theirs. A
#: deployment offering it beside a directory may want its own word for it, which is
#: what ``use_local(label=…)`` is for.
LABEL = "Local account"


class LocalUsers:
    """An :class:`~little_sister.identity.IdentityProvider` over the user list.

    It has a login step, so it implements ``login_page`` and ``submit_login`` and
    calls :func:`~little_sister.identity.sign_in`; it has no redirect flow and no
    remote session, so it implements neither ``complete_login`` nor ``end_session``
    and both answer ``404`` — a way in this deployment does not have.

    :meth:`challenge` sends an unidentified visitor to ``/login``, which is the
    right answer for the ordinary registration — this list as the **default** door.
    A deployment registering it as a *second* door beside another default
    (``use_local(default=False)``) wants a challenge that goes to its own route,
    which is a one-line subclass overriding this method — deliberately not a
    constructor knob, since the case has no user yet.
    """

    def __init__(self, config: UsersConfig) -> None:
        self.users = config.users
        #: The avatar selected for each account at startup, read per request from
        #: the file it names (ADR-0045).
        self.avatars = config.avatars
        self.document = config.document

    def identify(self) -> Identity | None:
        """Who this session is, read from the session this provider itself wrote.

        Through :func:`little_sister.identity.session_identity`, which is the one
        reader of this module's session format — the system-admin door writes the
        same fields, and two readers would eventually disagree about one of them.
        """
        return identity.session_identity()

    def challenge(self) -> ResponseReturnValue:
        """Send an unidentified visitor to the login form."""
        return redirect(identity.LOGIN_PATH)

    def login_page(self) -> ResponseReturnValue:
        """The form, and — while there is one to offer — the way to the other door.

        :func:`little_sister.system_admin.usable_route` answers ``""`` unless that
        account is configured *and* its credential resolved, so the link is absent
        rather than pointing at a ``404``. What it buys is honest and small: this
        page is rendered by the built-in list, so the link reaches the install whose
        default door is a local form and never the Keycloak install the emergency
        account mostly exists for — under a provider that redirects, ``/login`` is a
        redirect and this template is not rendered at all. There the address stays
        what it has always been: fixed, on ``/system``, and in the runbook.
        """
        return render_template('login.html', error=None,
                               admin_door=system_admin.usable_route())

    def submit_login(self) -> ResponseReturnValue:
        """Check a submitted login and open a session for it.

        One message for both halves of a wrong answer — an unknown name and a wrong
        password are answered identically — because telling them apart tells a
        stranger which logins exist. The log line names the attempted login and
        never the password.
        """
        username = request.form['username']
        password = request.form['password']
        entry = self.users.get(username)
        if entry is not None and entry["password"] == password:
            identity.sign_in(Identity(
                name=username,
                firstname=str(entry["firstname"]),
                lastname=str(entry["lastname"]),
                admin=bool(entry.get("admin", False))))
            return redirect('/status')
        # WARN for the log entry; the line's own grade is the rate's
        # (`security_lines`), and one failed login is a fact there.
        self_report.security.see(
            self_report.FAILED_LOGIN,
            plain(f"for {username!r} at the built-in login list"))
        return render_template('login.html', error='Invalid username or password',
                               admin_door=system_admin.usable_route())


#: The loaded aspect, kept so that re-registering does not re-read the file. The
#: read itself stays **eager** — a broken user list must fail at startup, the way it
#: always has (ADR-0020), not at the first login attempt.
_config: UsersConfig | None = None


def use_local(*, default: bool = True, label: str = LABEL) -> LocalUsers:
    """Register the built-in list as the ``local`` door — **the deployment's line**.

    ::

        from little_sister import local_login
        local_login.use_local()

    Written in the import-before-app block beside every other registration
    (ADR-0069 §2), which is the point of it: *the library adds no door on anybody's
    behalf*. It used to add this one whenever a deployment had registered none of
    its own, and that rule was the last implicit thing in a design whose whole claim
    is that the ways in are the ones somebody named. What you got depended on what
    else had been registered and on the library's own doors not counting — two
    conditions to hold in your head to answer *can anyone log in here*, where the
    answer is one line in one file (ADR-0069 §3).

    The ``users`` aspect is read **here**, so it is read only by an installation that
    asks for this door: a deployment with an identity provider of its own carries no
    ``users.yaml`` at all, which is the promise that survives the change unaltered.
    A broken list still fails at startup rather than at the first login (ADR-0020) —
    the read is eager and this is the eager moment.

    ``label`` is what a chooser prints (:data:`LABEL`); ``default=False`` registers
    it as a second door beside somebody else's default,
    reachable at ``/login/local`` and never at ``/login``. That is the shape for a
    deployment keeping a small local list beside its directory; such a provider
    usually also wants a :meth:`LocalUsers.challenge` of its own, which is the
    one-line subclass that method describes.
    """
    global _config
    if _config is None:
        _config = load_users()
    provider = LocalUsers(_config)
    identity.use(DOOR_NAME, provider, default=default, label=label)
    logger.info("The built-in login list answers %s%s with %d configured user(s).",
                f"{identity.LOGIN_PATH}/{DOOR_NAME}",
                f" and {identity.LOGIN_PATH}" if default else "",
                len(provider.users))
    return provider


def registered() -> LocalUsers | None:
    """This list's provider if it is one of the doors in use, else ``None``.

    Read off the door registry rather than remembered beside it: a second table is a
    table that can disagree with the registry it describes (ADR-0064), and this one
    would disagree in the direction that matters — claiming a user list is answering
    for logins after a deployment replaced it.
    """
    for door in identity.registered_doors():
        if isinstance(door.provider, LocalUsers):
            return door.provider
    return None


def registered_avatars() -> dict[str, AvatarFile]:
    """The avatars of the built-in list if it is in use, else none.

    Under another provider this is empty and every viewer gets the packaged neutral
    avatar, which is the honest answer rather than a gap: the map belongs to the
    ``users`` aspect, and such a deployment has no ``users`` aspect to read
    (ADR-0045, ADR-0069).
    """
    provider = registered()
    return provider.avatars if provider is not None else {}
