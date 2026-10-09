"""Who a request is from, and the one place that decides what happens when nobody is.

Until now the answer to *who is this request* was ``session['username']``, read at
fourteen redirect sites, two admin gates, one authorship field and every page's
template arguments. Fourteen copies of one rule is fourteen chances for a route to
be written without it, and there was no way to look at the application and see
which routes are open — the set was an accident of which views happened to check.

This module makes both of those explicit, and it takes the answer from outside:
**deciding who somebody is is not this library's job**, because it is different in
every organization, and the built-in login list is the fallback for the case that
needs no implementation at all — one person, one machine, fifteen seconds
(ADR-0069).

Five rules carry the whole design:

* **The gate is a refusal by default.** :func:`needs_identity` says *yes* for every
  endpoint that is not on a named list, so a route added tomorrow is closed until
  somebody says otherwise. The opposite polarity — a decorator each view opts into —
  reads the same on the page and fails the other way, silently.
* **What an unidentified request gets is one function.** :func:`challenge` is what a
  provider replaces to send somebody to an identity provider instead, and there is
  exactly one of it.
* **Several ways in are allowed; an ordered list of them to try is not.** Each
  registered provider is a **door** (:func:`use`) with a name and a route of its own,
  entered deliberately. Nothing is ever tried in turn, so there is no order to get
  wrong, no first-positive-match, and no rule needed for what happens when two
  directories know one name. The mechanism that guarantees it is that
  :func:`sign_in` records **which door produced the session** and :func:`current_user`
  asks *that* provider and no other.
* **Every door an installation has, that installation registered** — the built-in
  login list included (:func:`little_sister.local_login.use_local`). The library
  adds none on anybody's behalf, so the ways into a running instance are exactly
  what one file of its own says they are, and an install that registers nothing
  starts, says so, and lets nobody in (:func:`announce_doors`).
* **A provider that raises is nobody**, logged and never let through: containment is
  right for a broken slot filler (ADR-0034) and wrong for a gate, and a failing
  provider takes down its own door and no other.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

from flask import (
    abort,
    g,
    has_request_context,
    redirect,
    render_template,
    request,
    session,
)
from flask.typing import ResponseReturnValue

from little_sister import self_report
from little_sister.codes import StatusCode
from little_sister.logger import logger
from little_sister.origins import calling_package
from little_sister.reasons import plain, slug
from little_sister.secrets import UNIDENTIFIED

#: Endpoints that answer **without any identity at all**, and why each one has to.
#:
#: ``login`` and ``static`` are the login page and the stylesheet it is drawn with;
#: ``logout`` has to work when the session is already gone; ``csp_report`` receives
#: violations from a page that may have had no session (ADR-0048 §6); ``health``
#: and ``ready`` are read by a load balancer holding no credential of ours
#: (ADR-0066, ADR-0073) — a probe that has to authenticate measures nothing. The two
#: redirects are open for two different reasons: ``index`` sends a visitor to
#: ``/status``, which refuses on its own account, so opening the redirect gives
#: nothing away; ``favicon`` sends a browser to the packaged icon under ``static``,
#: which is already open for the same reason the login page's stylesheet is.
#:
#: This is the list ADR-0066 said would have to become explicit. Adding to it is how a
#: route is opened, and it is deliberately an edit somebody has to justify.
#: ``login_door`` and ``login_callback`` are the per-door halves of the same login
#: (:data:`LOGIN_PATH` and :data:`CALLBACK_PATH`): a request arriving at one of them
#: is by definition a request with no identity yet, and a gate in front of a login
#: page is a redirect loop.
OPEN_ENDPOINTS = frozenset({
    "index", "login", "login_door", "login_callback", "logout", "static", "favicon",
    "csp_report", "health", "ready",
})

#: Endpoints that **choose their own credential** and are therefore not gated here.
#:
#: The routes the JSON API reads: ``/status`` serves the dashboard to a session *and*
#: the status read to a bearer token, deciding which by content negotiation
#: (ADR-0008), and ``/series`` and ``/series/<path>`` serve the Series index and a
#: node's Series view to a session and the series read to a token (ADR-0122
#: decision 8). A gate in front of one would redirect an API client to a login page.
#: None is open — each refuses both ways — and they are named
#: separately from :data:`OPEN_ENDPOINTS` so that nobody reads them as open.
SELF_AUTHENTICATING_ENDPOINTS = frozenset({"status", "series", "series_index"})


#: The library's own login routes, and the whole of the URL space a door occupies.
#: A door gets its place here by being **registered** — it never brings a route of
#: its own — so an identity provider needs no general route seam, and a name it
#: claims cannot collide with a route the library adds later (ADR-0069 §4).
LOGIN_PATH = "/login"
CALLBACK_PATH = "/auth/callback"
LOGOUT_PATH = "/logout"

#: The one door the **library** ships, as opposed to registers on a deployment's
#: behalf: the system-admin account (:mod:`little_sister.system_admin`). The name
#: lives here because the read path knows it — :func:`is_system_admin_session` is a
#: question about a session, and a session is this module's business — while
#: everything that account *does* lives in its own module.
SYSTEM_ADMIN_DOOR = "system-admin"

#: What a door may be called. A name is a **path segment** — ``/login/keycloak`` —
#: so a space, a slash or an upper-case letter would produce either a route nobody
#: can type or two spellings of one door; and it is what a runbook says out loud, so
#: it is held to the shape every other name in this family has (ADR-0052).
_DOOR_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

#: The session key recording **which door produced this session** — the mechanism
#: that makes the read path unable to be a chain (:func:`session_door`).
DOOR_KEY = "door"

#: Where :func:`current_user` keeps the answer for the rest of the request. The gate
#: asks, a view asks again through :func:`signed_in`, and the avatar context
#: processor asks a third time; for a header-verifying provider that would be three
#: signature checks of one header (ADR-0069 §8).
_ANSWER_KEY = "identity_answer"

#: Where a dispatching route records the door it is dispatching to, so that
#: :func:`sign_in` — which a provider calls with an :class:`Identity` and nothing
#: else — knows which door to record without every provider having to repeat its own
#: name back to us.
_ENTERING_KEY = "identity_door"


class _Unset:
    """The "nothing cached yet" marker, distinct from a cached ``None``."""


_UNSET = _Unset()


@dataclass(frozen=True)
class Identity:
    """Who is making this request.

    ``name`` is the stable identifier a pin, an event and an authorship line are
    recorded against, so it is the one field that must never be a display choice.
    ``admin`` is the only role there is, because two is what the routes actually
    gate; anything finer would be a guess about a deployment's own vocabulary.

    Four fields and no raw-claims bag: a deployment that needs more already has it,
    in its own provider code, and a claims dictionary on the library's type is a
    surface owed forever for a convenience nobody asked for (ADR-0069 §9).
    """
    name: str
    firstname: str = ""
    lastname: str = ""
    admin: bool = False


class IdentityProvider(Protocol):
    """What a deployment hands :func:`use`.

    **Two required methods, and the primitive is *who is this request* rather than
    *the login flow*** (ADR-0069 §1). That is what lets the same contract carry both
    environments in front of us: an application that performs an authorization-code
    redirect, and one behind a load balancer that has already completed the whole
    exchange and injects a signed assertion into a header — the second performs no
    login at all, and a flow-shaped contract would have had nothing to say about it.

    * ``identify()`` — the :class:`Identity` behind this request, or ``None``. Called
      once per request (:func:`current_user`). Raising is *nobody*, never *let them
      through*.
    * ``challenge()`` — what a request with no identity gets: a redirect to a login
      page, a redirect to an identity provider, or a bare ``401`` where there is no
      flow to send anybody into.

    Four optional hooks, and a provider implements only the ones it has. Each is
    reached at a **fixed route** the library owns, and an unimplemented one answers
    ``404`` — it is a way in this deployment does not have, and a redirect there
    risks a loop:

    * ``login_page()`` — ``GET /login/<door>`` (and ``GET /login`` for the default).
    * ``submit_login()`` — ``POST`` to the same, for a door with a local form.
    * ``complete_login()`` — ``GET /auth/callback/<door>``, where a redirect flow
      comes back.
    * ``end_session()`` — ``GET /logout``, *before* the session is cleared, so a
      provider can send the visitor on to an identity provider's end-session
      endpoint. Answering ``None`` (or not implementing it) is the ordinary case and
      is **not** a 404: logging out must work whatever the provider does.

    A fifth optional method is not a route and answers a question instead:

    * ``enterable()`` — whether this door can take a credential **right now**. Not
      implementing it means *yes*, which is right for every provider whose
      ``login_page`` always answers; the system-admin account implements it because
      its own page is a ``404`` while its password has not resolved. It is what
      :attr:`Door.enterable` asks and what keeps a chooser from offering a way in
      that is not there.

    A provider with a login step calls :func:`sign_in` and :func:`sign_out`; a
    header-verifying one never does, and writes no session at all.
    """

    def identify(self) -> Identity | None: ...

    def challenge(self) -> ResponseReturnValue: ...


#: The hooks a provider *may* implement, named here rather than only in the protocol
#: because the dispatch below looks them up by name.
OPTIONAL_HOOKS = ("login_page", "submit_login", "complete_login", "end_session")


class DoorConflictError(Exception):
    """Two claims that cannot both hold: one door name claimed by two packages, or
    a second provider claiming to be *the* default. Raised from :func:`use` — that
    is, from the application's import-before-app block, so the process does not
    start (ADR-0069 §2), the way a second claim on a ``type:`` name or a secret
    scheme does not (ADR-0051, ADR-0064)."""


@dataclass(frozen=True)
class Door:
    """One registered way in: a name, a provider, and who put it there.

    The provider travels **with** its provenance in one record rather than beside it
    in a second table that can disagree with the registry it describes — the same
    shape the secret-resolver registry settled on (ADR-0064).
    """
    name: str
    provider: IdentityProvider
    #: The package that registered it, inferred from the call site — ``""`` where the
    #: caller could not be identified (see
    #: :data:`~little_sister.secrets.UNIDENTIFIED`).
    package: str
    #: Whether this is the door ``/login`` and :func:`challenge` go to. Exactly one
    #: door may say so.
    default: bool = False
    #: What a page calls this door out loud. :attr:`name` is a path segment, chosen
    #: to be typed and to appear in a runbook; *Sign in with keycloak* is not a
    #: sentence anybody wants on a login page. Defaults to the name at registration,
    #: so it is never empty and a caller never has to fall back.
    label: str = ""

    @property
    def enterable(self) -> bool:
        """Whether somebody could go through this door **right now**.

        Two facts, and they are asked here together so that nothing has to ask them
        apart. A door with no ``login_page`` has no page to send anybody to — the
        header-verifying provider is the whole of that case, and it is not a defect.
        And a door may be registered and temporarily unable to take a credential:
        the system-admin account whose password did not resolve is registered so
        that ``/system`` can say *configured but unavailable*, and answers ``404``
        meanwhile (ADR-0069 §5).

        A provider says the second part by implementing ``enterable()``; not
        implementing it means *yes*, which is right for every provider that has a
        page at all. The alternative — each caller deciding for itself — is two
        rules that can disagree about whether a way in exists, which is the shape
        ADR-0064 warns about in the small.

        **A hook that raises is *not enterable*, and takes down its own door only**
        (:func:`_ask` makes the same trade for ``identify``). The question invites an
        answer that can fail — *can this door take a credential right now* is a
        reachability probe if a provider wants it to be — and the thing it probes is
        exactly what has stopped answering on the morning a chooser is being read.
        Letting that raise would take the page down for every **other** door too,
        which is the one failure ADR-0069 §7 promises cannot happen.
        """
        if _optional(self, "login_page") is None:
            return False
        answering = getattr(self.provider, "enterable", None)
        if answering is None:
            return True
        try:
            return bool(answering())
        except Exception as error:
            logger.exception("Identity door %r (%s) failed to say whether it can "
                             "be entered", self.name, self.owner)
            self_report.runtime.see(
                slug("door", self.name),
                plain(f"the identity door {self.name!r} ({self.owner}) raised "
                      f"({error!r}) when asked whether it can be entered; it is "
                      f"left off the page"), log=False)
            return False

    @property
    def route(self) -> str:
        """The door's own login route — always reachable, whatever ``/login`` does.

        This is the part that matters mechanically rather than stylistically: under
        a provider that redirects, ``/login`` never renders a local form, so a door
        that must stay usable when that provider has stopped answering needs an
        address of its own.
        """
        return f"{LOGIN_PATH}/{self.name}"

    @property
    def callback(self) -> str:
        """Where a redirect flow at this door comes back to."""
        return f"{CALLBACK_PATH}/{self.name}"

    @property
    def owner(self) -> str:
        """The registering package as a page or a message should say it."""
        return self.package or UNIDENTIFIED

    @property
    def provider_name(self) -> str:
        """The class answering for this door, as ``/system`` names it. The package
        beside it says *whose* class, so the bare name is the whole of what is left
        to say."""
        return type(self.provider).__name__


_doors: dict[str, Door] = {}


def use(name: str, provider: IdentityProvider, *, default: bool = False,
        label: str = "") -> None:
    """Register ``provider`` as the door called ``name`` (ADR-0069 §2).

    Called by the application before ``little_sister.app`` is imported — the same
    import-before-app slot check types, slot fillers, assets, configuration aspects
    and secret resolvers already use. The registering **package** is inferred from
    the call site, as a resolver's is: a name the caller had to repeat is a name the
    caller can get wrong.

    A door name is claimed **once**. A second claim from a *different* package
    raises :class:`DoorConflictError` naming both, because a name is how a person
    and a runbook refer to a way in, and import order must not decide what it means.
    Re-registering from the **same** package replaces silently, for the reason the
    neighboring seams do: a registration module may be imported twice under a
    reloading server, and refusing that would refuse the server.

    Exactly one door is the **default** — the one ``/login`` and :func:`challenge`
    go to when nothing else is said. A second ``default=True`` from another door
    raises likewise: it is a question with one answer, and answering it by import
    order is the thing this whole design removes.

    ``label`` is what a page calls this door out loud — ``"Company SSO"`` beside the
    path segment ``keycloak``. It defaults to the name, which is the right answer
    for a door nobody has to introduce, and it is the only display field a door has
    (:func:`door_chooser`).
    """
    name = name.strip().lower()
    if not _DOOR_NAME.fullmatch(name):
        raise ValueError(
            f"{name!r} is not a usable door name: a door is a path segment "
            f"({LOGIN_PATH}/<door>), so it is lower-case letters, digits and "
            f"single hyphens — 'keycloak', 'system-admin'.")
    package = calling_package()
    claimed = _doors.get(name)
    if claimed is not None and claimed.package != package:
        raise DoorConflictError(
            f"two packages claim the identity door {name!r}: {claimed.owner} "
            f"registered it and {package or UNIDENTIFIED} claims it too. A door "
            f"name is how a person and a runbook refer to a way in, so import "
            f"order must not be what decides it — rename one of them, or register "
            f"only one (ADR-0069).")
    if default:
        standing = default_door()
        if standing is not None and standing.name != name:
            raise DoorConflictError(
                f"two identity doors claim to be the default: {standing.name!r} "
                f"from {standing.owner} and {name!r} from "
                f"{package or UNIDENTIFIED}. The default is where {LOGIN_PATH} and "
                f"an unidentified request are sent, which is a question with one "
                f"answer — leave default=True on exactly one of them; the other "
                f"keeps its own route at {LOGIN_PATH}/<door> (ADR-0069).")
    _doors[name] = Door(name=name, provider=provider, package=package,
                        default=default, label=label.strip() or name)


def registered_doors() -> tuple[Door, ...]:
    """Every registered door with the package that answers for it, by name.

    For ``/system``: a way into an application must not be knowable only by reading
    the source, and a registration nobody can see from the running instance is
    indistinguishable from one that silently did not take (ADR-0064, ADR-0069 §6).
    """
    return tuple(_doors[name] for name in sorted(_doors))


def door(name: str) -> Door | None:
    """The door called ``name``, or ``None`` where nothing claims it."""
    return _doors.get(name.strip().lower())


def default_door() -> Door | None:
    """The door ``/login`` and :func:`challenge` go to, or ``None`` — which means
    either that nothing is registered or that nothing claimed it, both of which an
    installation can be in and neither of which stops it (:func:`announce_doors`)."""
    return next((registered for registered in registered_doors()
                 if registered.default), None)


#: Whether :data:`LOGIN_PATH` offers the doors instead of going to the default one
#: (:func:`choose_at_login`).
_choose_at_login = False


def choose_at_login() -> None:
    """Make ``/login`` **offer the doors** rather than go straight to the default.

    An installation-level line, written in the import-before-app block beside the
    registrations it is about::

        identity.use("keycloak", Keycloak(), default=True, label="Company SSO")
        identity.use_system_admin(reference="env://LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD")
        identity.choose_at_login()

    **What it does not touch is the point of it.** While there is a door to ask,
    :func:`challenge` is unchanged, so an unidentified request still goes wherever
    the provider sends it — and where that is stays the provider's decision, not this
    call's. A provider whose identity provider settles the whole question redirects
    straight there, silently, and is right to; one that also *authorizes* — a
    directory group deciding who may use the application at all — may prefer to send
    an unidentified request here instead, since a redirect would sign somebody in
    only to refuse them, on every visit (ADR-0069 §1).

    The one case where this line does reach :func:`challenge` is the one where there
    is **no** provider to ask: a default door that closed leaves nothing to send an
    unidentified request to, and this page is then the only address of ours that
    still means something. That is a fallback for an installation that already asked
    for the page, not a second way of choosing what ``/login`` is.

    What this call changes either way is the address somebody **types**, or is sent
    to: ``/login`` renders :func:`door_chooser`, which is a page *we* serve and
    therefore a page that still answers when the identity provider does not.

    Each door keeps its own ``/login/<door>`` and that is where the chooser's links
    go, so the provider that owns the default door is untouched — it is still the
    one thing ``/login/keycloak`` reaches. That separation is also what keeps this
    from being a loop: were the chooser something a provider returned from its own
    ``login_page()``, the two routes that reach that method would both render it,
    and the entry for its own door would lead back to the page it was on.

    A statement rather than an inference, like every other registration here: an
    installation with two enterable doors is not thereby asking for a menu, and
    working out which ones would want one is the kind of guess §3 exists to refuse.
    """
    global _choose_at_login
    _choose_at_login = True


def choosing_at_login() -> bool:
    """Whether this installation asked for :func:`choose_at_login`. For ``/system``,
    which says what ``/login`` does rather than leaving it to be discovered."""
    return _choose_at_login


def forget_doors() -> None:
    """Drop every registration — the doors and the choice at ``/login`` alike, since
    both are registrations. For tests: a door one case registers must not decide
    another case's identity."""
    global _choose_at_login
    _doors.clear()
    _choose_at_login = False


def session_door() -> str:
    """The door that produced this session, or ``""``.

    Written by :func:`sign_in` and read by :func:`current_user`, and that pairing is
    the whole of why the read path cannot become a chain: there is never a list of
    providers to try, only the one that already answered for this session. A
    header-verifying provider writes no session and so answers for requests carrying
    no door, which is unambiguous for the same reason — exactly one provider is ever
    asked.

    Deliberately **not** a fifth field on :class:`Identity` and never what ``set_by``
    records: how somebody got in is a property of the session, while the name a pin
    is stored against outlives every mechanism that produced it (ADR-0069 §5).
    """
    if not has_request_context():
        return ""
    return str(session.get(DOOR_KEY, ""))


def is_system_admin_session() -> bool:
    """Whether this session came through the library's own system-admin door.

    The named convenience over :func:`session_door`, and deliberately **not** a fifth
    field on :class:`Identity`: how somebody got in is a property of the session,
    while ``Identity.name`` is a stored key that maintenance pins and event
    authorship are held against and outlives every mechanism that produced it
    (ADR-0069 §5). The chrome asks this to show a distinct avatar; nothing routes
    on it.
    """
    return session_door() == SYSTEM_ADMIN_DOOR


def session_identity() -> Identity | None:
    """The identity :func:`sign_in` wrote, or ``None``.

    The read half of this module's own session format, so that every provider with a
    login step shares one — the built-in list and the system-admin account both use
    it, and a third would be the point at which two of them disagreed about what
    ``admin`` is stored as.

    It reads the **session**, never a directory: a login that has since been removed
    keeps the session it was granted until that session expires, which is the
    promise every session-based login makes and is not this module's to change.
    """
    name = session.get("username")
    if not name:
        return None
    return Identity(name=str(name),
                    firstname=str(session.get("firstname", "")),
                    lastname=str(session.get("lastname", "")),
                    admin=bool(session.get("admin", False)))


def use_system_admin(*, reference: str = "", password: str = "") -> None:
    """Configure the library's own system-admin account (ADR-0069 §5).

    The call site a deployment writes — beside :func:`use`, in the same
    import-before-app block — so the whole of identity registration reads from one
    module. The account itself lives in :mod:`little_sister.system_admin`, which is
    imported here rather than at the top of this module because it imports *this*
    one: a provider is written against the seam, and the seam knows only that one
    door is the library's own.

    See :func:`little_sister.system_admin.use_system_admin` for the rules — exactly
    one keyword, each refusing the other's shape, resolved once at registration, and
    a failed resolution that closes the door rather than the application.
    """
    from little_sister import system_admin
    system_admin.use_system_admin(reference=reference, password=password)


def sign_in(user: Identity) -> None:
    """Open a web session for ``user`` — what a provider with a login step calls.

    The session stays the web-session mechanism whatever produced the identity,
    because that is what a browser needs; what changes is that it now records the
    **door**, taken from the route that is dispatching rather than from a name the
    provider had to pass back. A provider that verifies a header on every request
    never calls this.
    """
    session["username"] = user.name
    session["firstname"] = user.firstname
    session["lastname"] = user.lastname
    session["admin"] = user.admin
    entering = str(g.get(_ENTERING_KEY, "")) if has_request_context() else ""
    if entering:
        session[DOOR_KEY] = entering
    else:
        session.pop(DOOR_KEY, None)
    _forget_answer()


def sign_out() -> None:
    """Close the web session. The whole session, not the identity fields: what is
    left behind after a logout is exactly what nobody audits."""
    session.clear()
    _forget_answer()


def _forget_answer() -> None:
    """Drop this request's cached answer, after something changed who is asking."""
    if has_request_context():
        g.pop(_ANSWER_KEY, None)


def current_user() -> Identity | None:
    """Who this request is from, or ``None`` when nobody is.

    Outside a request there is nobody to be, which is not an error: a context
    processor or a template helper may run without one.

    **One provider is asked, and which one is not a search.** A session names the
    door that opened it and that door answers; a request carrying no door goes to
    the default, which is the only door that could have answered for it. A session
    naming a door that is no longer registered is **nobody** — asking a different
    provider would be precisely the chain this design exists to remove, and it would
    resolve a stored name against a directory that never issued it.

    Answered once per request, because the gate, a view and the avatar context
    processor each ask, and for a header-verifying provider each ask is a signature
    check.
    """
    if not has_request_context():
        return None
    cached = g.get(_ANSWER_KEY, _UNSET)
    if not isinstance(cached, _Unset):
        return cast("Identity | None", cached)
    answer = _identify()
    setattr(g, _ANSWER_KEY, answer)
    return answer


def _identify() -> Identity | None:
    """Ask the one provider that can answer for this request.

    Through a **registered provider, always** — no session-reading path survives
    beside the doors, which is what makes *the built-in list is a provider like any
    other* true of the code rather than only of the documentation. Nothing
    registered means nobody is identified, which is a state an installation can be
    in: registering a door is the deployment's line to write, and one that has not
    written it starts anyway and says so (:func:`announce_doors`).
    """
    name = session_door()
    if name:
        opened = _doors.get(name)
        return None if opened is None else _ask(opened)
    fallback = default_door()
    return None if fallback is None else _ask(fallback)


def _ask(opened: Door) -> Identity | None:
    """``opened.identify()``, with a raise treated as **nobody**.

    ADR-0034 contains a broken slot filler on the principle that monitoring must not
    go dark because a button broke. The same instinct here would be a hole: a
    provider that raises has told us nothing about who this is, and *nothing* is not
    permission. Containment is right for a decoration and wrong for a gate — and the
    door that failed takes down itself and no other, which is the whole reason the
    doors are separate.
    """
    try:
        return opened.provider.identify()
    except Exception as error:
        logger.exception("Identity door %r (%s) failed to answer", opened.name,
                         opened.owner)
        self_report.runtime.see(
            slug("door", opened.name),
            plain(f"the identity door {opened.name!r} ({opened.owner}) raised "
                  f"({error!r}) when asked who this is; the request is treated as "
                  f"unidentified"), log=False)
        return None


def announce_doors() -> None:
    """Say what this instance can be signed in through — the startup line.

    Called once, after the deployment's import-before-app block has run, and the
    rule it applies is the whole of what this module does about a registration that
    is not right: **a contradiction refuses, an omission logs.**

    A contradiction is two statements that cannot both hold — one door name claimed
    by two packages, a second door claiming to be *the* default — and :func:`use`
    stops the process over it where it happens, because import order must not be
    what decides which one wins (ADR-0069 §2). An **omission** is different in kind:
    no door registered at all, or doors registered and none marked default. Nobody
    has said anything contradictory; somebody has not yet said a line. Refusing to
    start over that would take a monitoring application down for a mistake it is
    perfectly able to describe — and it would refuse the *more* usable of the two
    configurations, since an instance with doors but no default still lets anybody
    who knows the address in at ``/login/<door>``.

    So both omissions are a ``WARNING`` naming the missing line, and the instance
    serves: ``/health`` answers for the load balancer (ADR-0066), ``/system`` shows
    the door table, and every gated page refuses with a ``401`` until somebody
    registers one. The warning is not quite the only place that says so any more —
    an instance with **no door at all** never becomes ready, and ``/ready`` says
    ``doors`` for as long as that holds (ADR-0073); doors without a default are an
    instance anybody who knows the address can enter, so readiness is silent about
    them and this warning stays the only word. It says what to add rather than only
    what is wrong, for the same reason.
    """
    doors = registered_doors()
    if not doors:
        # ERROR, by the loss principle: an instance nobody can sign in to has
        # lost its readers, which is the one thing a dashboard is for.
        self_report.startup.note(
            "doors",
            plain(f"no identity door is registered, so nobody can sign in: every "
                  f"gated page answers 401 and {LOGIN_PATH} answers 404. Register "
                  f"one before importing little_sister.app — "
                  f"local_login.use_local() for the built-in login list, or "
                  f"identity.use('<name>', <provider>, default=True) for a "
                  f"provider of your own (ADR-0069)"),
            code=StatusCode.ERROR)
        return
    listed = ", ".join(f"{one.name!r} ({one.owner})" for one in doors)
    fallback = default_door()
    if fallback is None and _choose_at_login:
        # An unidentified request has somewhere to land, and nothing says which door
        # this installation expects: a configuration left half-written, which is
        # what WARN is for.
        #
        # **It no longer says the instance is usable**, which it said until
        # 2026-09-24 and could not check. Registration is what this function knows;
        # whether any of those doors can take a credential is
        # :attr:`Door.enterable`, asked per request and allowed to probe. A
        # deployment whose doors resolve their credentials from a parameter store it
        # cannot reach registers them all and admits nobody — and this line was
        # calling that instance usable a few lines from the system-admin note saying
        # its door was shut. The paragraph below already says why that is the worse
        # error: an operator reads a startup line once and believes it for months.
        # What is missing is still a default, so that is still what it asks for.
        self_report.startup.note(
            "doors",
            plain(f"identity doors are registered and none of them is the "
                  f"default: {listed}. {LOGIN_PATH} still offers the choice and an "
                  f"unidentified request is sent there, so nobody is turned away "
                  f"for want of a default — but nothing says which door this "
                  f"instance expects anybody to use. Mark exactly one registration "
                  f"default=True (ADR-0069)"))
        return
    if fallback is None:
        self_report.startup.note(
            "doors",
            plain(f"identity doors are registered and none of them is the "
                  f"default: {listed}. Each is still reachable at its own "
                  f"{LOGIN_PATH}/<door>, but {LOGIN_PATH} answers 404 and an "
                  f"unidentified request gets a 401 with nowhere to be sent — mark "
                  f"exactly one registration default=True (ADR-0069)"))
        return
    # **Handed to, not "goes to".** What answers an unidentified request is the
    # default door's own ``challenge()`` (:func:`_unidentified`), and that method is
    # the provider's to write: §1 describes three legitimate shapes of it, and one of
    # them deliberately does not send anybody to that door at all — a provider whose
    # authenticating is not admitting answers ``/login`` so a person it will refuse
    # is not walked into a redirect loop. So the destination is not ours to announce.
    # Naming the door we hand to is the whole of what this line actually knows, and
    # a startup line that overstates its knowledge is worse than a shorter one: an
    # operator reads it once and believes it for months.
    if _choose_at_login:
        logger.info("Identity doors: %s. %s offers a choice of them; an "
                    "unidentified request is handed to %r, whose challenge() "
                    "decides where it lands.", listed, LOGIN_PATH, fallback.name)
        return
    logger.info("Identity doors: %s. %s goes to %r, and so does every unidentified "
                "request, whose challenge() decides where it lands.",
                listed, LOGIN_PATH, fallback.name)


def signed_in() -> Identity:
    """The identity behind the gate, for a view that needs to name it.

    Only reachable from a view :func:`needs_identity` covers, so ``None`` here is a
    route that got onto one of the lists above by mistake rather than a visitor who
    is not logged in. It answers ``401`` rather than redirecting, because a redirect
    would send a person to a login form that will not fix it.
    """
    user = current_user()
    if user is None:
        abort(401)
    return user


def needs_identity(endpoint: str | None) -> bool:
    """Whether the gate applies to *endpoint* — true for everything not listed.

    ``None`` is a request that matched no route at all; it gets the ordinary 404
    rather than a login page, because sending somebody to log in before telling them
    the address does not exist helps nobody and answers a question they did not ask.
    """
    if endpoint is None:
        return False
    return (endpoint not in OPEN_ENDPOINTS
            and endpoint not in SELF_AUTHENTICATING_ENDPOINTS)


def challenge() -> ResponseReturnValue:
    """What a request with no identity gets.

    One function, called from one place, so that what happens to an unidentified
    request is a single decision rather than fourteen — and the one function a
    provider replaces to send somebody to an identity provider, or to answer a bare
    ``401`` where there is no flow to send them into.

    Which door answers: the one this session came through if it is still registered,
    because a session that has merely expired is best sent back where it came from;
    otherwise the default, which is what *how do I get in* means when nothing else
    is known. Either way exactly one provider is asked.

    **A default door can stop being there, and that is nobody's omission.** A
    credential that fails to resolve closes its own door and the application keeps
    serving (ADR-0069 §5), so an installation whose provider was the default can be
    left with doors that work and none of them marked. Where that installation asked
    for :func:`choose_at_login` there is still an address of **ours** to send
    somebody to, and this does not give up: ``/login`` renders whatever is still
    enterable, and being a page we serve it renders when the identity provider does
    not. Only the **registry** is consulted to decide that, never
    :attr:`Door.enterable` — a provider is allowed to answer *can this door be
    entered* by probing, and this runs on every unidentified request.

    Without the chooser there is genuinely nowhere to send anybody, and ``401`` is
    the honest answer rather than a shrug: ``/login`` is then the default door's own
    step and answers ``404`` while there is no default, so a redirect would lead into
    a dead end. The same holds for an installation that registered no door at all.
    **Which of those two states it is in is what the message says**, at ``DEBUG``,
    because :func:`announce_doors` owns the line an operator is meant to read — once,
    at startup — and this branch is reached once per request.
    """
    opened = _doors.get(session_door()) or default_door()
    if opened is not None:
        return opened.provider.challenge()
    if _doors and _choose_at_login:
        return redirect(LOGIN_PATH)
    logger.debug(
        "Refusing an unidentified request with 401: %s (ADR-0069).",
        "identity doors are registered and none of them is the default"
        if _doors else "no identity door is registered")
    abort(401)


def door_chooser() -> ResponseReturnValue:
    """The page that offers the doors — what ``/login`` renders under
    :func:`choose_at_login`.

    Only the doors that can be **entered right now** (:attr:`Door.enterable`), each
    as a link to its own route: a header-verifying door has no page to offer, and a
    system-admin door whose credential did not resolve would be a link to the
    ``404`` it answers with — offered, of all moments, to somebody standing in front
    of a login that is not working.

    **A redirecting provider needs a ``login_page`` to appear here**, and that is
    the one method such a deployment adds: ``challenge()`` is not an address, so a
    provider that only implements it has nothing a link can point at. The method it
    adds is the redirect it was already performing, started from its own route —
    which is also what makes the link go somewhere other than back to this page.

    One entry is still a page rather than a redirect. That is the load-balancer
    installation, where the only enterable door is the system admin, and sending
    somebody straight through would be this module choosing for them — which is the
    one thing the doors exist not to do.

    **The default door first**, because on an ordinary day it is the answer and the
    others are not; the rest keep the registry's order, which is by name. That is
    the only ranking here, and it is a presentation order rather than anything the
    read path knows about — nothing is ever *tried* in this order, or in any.

    Public, because it is also what a provider with a login page of its own can
    return; the ordinary installation reaches it through ``/login`` and never names
    it.
    """
    offered = [one for one in registered_doors() if one.enterable]
    offered.sort(key=lambda one: not one.default)
    return render_template("choose_door.html", doors=offered,
                           shut="" if offered else _no_way_in())


def _no_way_in() -> str:
    """What the chooser says when it has **nothing to offer**.

    Without it the page is a heading over an empty list: the brand, the tagline,
    and a `for` loop that never runs. Measured on a developer machine on
    2026-09-24, where a deployment whose two doors both take their credentials
    from a parameter store had neither, and the person in front of it was told
    nothing at all.

    That state was already diagnosed **everywhere except here** —
    :func:`announce_doors` writes the startup line, ``/ready`` reports ``doors``,
    ``/system`` shows the table, and :func:`challenge` distinguishes the two cases
    at ``DEBUG``. Every one of those is somewhere a reader has to already know to
    look. This is the one surface somebody is standing in front of at the moment
    it matters, and it was the only one that stayed silent.

    **Three states get three sentences**, because they need three different
    actions — and because two of them are not faults at all:

    * nothing registered: somebody has to add a line;
    * a door that has no ``login_page``: the header-verifying provider and the
      redirect flow that never renders anything of its own. Sign-in happens on
      the way in rather than here, so the reader is in the wrong place, and
      **nothing is broken**. Said whenever *any* door is of that kind, because
      one such door is a way in whatever the others are doing;
    * every door has a page and none can take a credential: something has to
      resolve, and until it does nobody gets in at all.

    What it deliberately does **not** do is name the doors or say why each failed.
    That is ``/system``'s, and ``/system`` is behind an admin session on purpose
    (ADR-0069 §5) — so this page says *that* there is no way in and where the
    answer is, and leaves *which door and why* to a page that knows who is asking.

    **It does not send anybody to ``/system``.** Measured on 2026-09-24: the
    third state is exactly the state in which ``/system`` cannot be reached, since
    reaching it needs an admin session and no door can issue one — the system-admin
    door included, which is the door that state is usually about. Naming it there
    offers a page nobody in front of this one can open. The instance has already
    written which door and why into its startup output (:func:`announce_doors`, and
    :mod:`system_admin` for its own), which is somewhere the person who can fix
    this can actually read. ``/ready`` is named only in the case it reports.
    """
    doors = registered_doors()
    if not doors:
        return ("This instance has no identity door registered, so there is "
                "nothing to sign in through. /ready says the same, and the "
                "instance's startup line says what to add.")
    if any(_optional(one, "login_page") is None for one in doors):
        return ("A door on this instance signs people in without a page of its "
                "own: this deployment identifies a request on its way in, at a "
                "proxy or an identity provider. Open the application itself "
                "rather than this address and it will take you the way it "
                "expects.")
    return ("Every door this instance has is configured and none of them can "
            "take a credential right now — a door whose credential has not "
            "resolved answers 404 until it does. Nobody can sign in while that "
            "holds, so the answer is not on any page here: the instance wrote "
            "which door and why into its startup output, on the machine where "
            "it runs.")


def login_response(name: str = "") -> ResponseReturnValue:
    """``GET``/``POST`` for ``/login/<door>``, and for ``/login`` with no name.

    A door name nothing claims is a ``404`` rather than a redirect to a door that
    does exist: it is a way in this deployment does not have, and answering with a
    different one would make the address a suggestion.

    Under :func:`choose_at_login`, the bare ``/login`` is the chooser and **is not a
    door**: it renders on ``GET`` and answers ``404`` to a ``POST``, because a
    credential is taken at a door's own route and nowhere else. A door's own route
    is untouched either way, which is what lets the chooser link to the default door
    without arriving back at itself.
    """
    if not name and _choose_at_login:
        if request.method == "POST":
            abort(404)
        return door_chooser()
    opened = door(name) if name else default_door()
    if opened is None:
        abort(404)
    return _hook(opened, "submit_login" if request.method == "POST"
                 else "login_page")


def callback_response(name: str) -> ResponseReturnValue:
    """``GET /auth/callback/<door>`` — where a redirect flow comes back."""
    opened = door(name)
    if opened is None:
        abort(404)
    return _hook(opened, "complete_login")


def logout_response() -> ResponseReturnValue:
    """``GET /logout`` — the door's own end-session step, then the session cleared.

    ``end_session`` is the one optional hook whose absence is **not** a ``404``:
    ``/logout`` has to work when the session is already gone and whatever the
    provider does, so an unimplemented one simply means there is nothing to do
    beyond clearing the session. Its answer wins when it has one, which is how a
    provider sends the visitor on to an identity provider's own end-session
    endpoint; and it runs *before* the session is cleared, because that is where
    whatever it needs to say goodbye with still is.

    **A hook that raises does not keep somebody logged in.** *Whatever the provider
    does* has to include *fails*: an end-session redirect is built from whatever the
    provider knows about the identity provider, and building it can throw. Unguarded,
    that turns ``/logout`` into a ``500`` with the session still open — the one
    outcome nobody would notice, because the page they get back is an error page
    either way. The provider's goodbye is best-effort and logged; clearing the local
    session is not optional and happens regardless.
    """
    opened = _doors.get(session_door())
    answer: ResponseReturnValue | None = None
    if opened is not None:
        handler = _optional(opened, "end_session")
        if handler is not None:
            setattr(g, _ENTERING_KEY, opened.name)
            try:
                answer = cast("ResponseReturnValue | None", handler())
            except Exception as error:
                logger.exception("Identity door %r (%s) failed to end its own "
                                 "session", opened.name, opened.owner)
                self_report.runtime.see(
                    slug("door", opened.name),
                    plain(f"the identity door {opened.name!r} ({opened.owner}) "
                          f"raised ({error!r}) ending its own session; the local "
                          f"session is cleared anyway"), log=False)
    sign_out()
    return answer if answer is not None else redirect(LOGIN_PATH)


def _optional(opened: Door, hook: str) -> Callable[[], ResponseReturnValue] | None:
    """One of :data:`OPTIONAL_HOOKS` on a provider, or ``None`` where it has none."""
    return cast("Callable[[], ResponseReturnValue] | None",
                getattr(opened.provider, hook, None))


def _hook(opened: Door, hook: str) -> ResponseReturnValue:
    """Dispatch to one of a provider's optional hooks, or ``404``.

    The door being entered is recorded first, so that a provider calling
    :func:`sign_in` from inside the hook records the session against *this* door
    without having to name itself.
    """
    handler = _optional(opened, hook)
    if handler is None:
        abort(404)
    setattr(g, _ENTERING_KEY, opened.name)
    return handler()
