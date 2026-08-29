"""Secret references: name where a secret comes from, resolve it once (ADR-0023).

A reference is a string in a check's config, and it always has the same shape:
``scheme://address``. ``env://GITHUB_TOKEN`` reads that environment variable —
ADR-0003's behavior, now spelled out loud; ``aws-sm://team/github-token`` goes to
the resolver the **application registered** for that scheme: a deployment calls
:func:`register_resolver` in its own code before importing ``little_sister.app``
— the same slot its WSGI wrapper uses to register check types — and owns the
resolver's dependencies; the library ships no store client (``env`` is the one
built-in).

Registering is a **claim**, and it is held to the rules the neighboring seams are
held to (ADR-0064): the registry records which package made it, ``/system`` prints
it, and a second claim on one scheme from a *different* package **refuses** at
startup naming both — because a scheme says where a credential is read from, and
import order must not be what decides that. Replacing somebody else's scheme stays
available to whoever means it, by saying ``replace=True`` at the call site.

There is deliberately **no bare-name form** (ADR-0023's 2026-07-27 update):
requiring the scheme is what makes a secret *value* pasted where a reference
belongs a structural config error, caught by the grammar rather than by guessing
from the shape of the string — and it keeps one syntax to learn instead of a
special case plus a general rule.

Secrets resolve **once, at check construction** (``Check.resolve_secret``), and
never during runs — cloud stores bill per read; rotation is a restart, like any
other config change (ADR-0015). The error split is deliberate (ADR-0023): a
**malformed** reference (no scheme, or an unknown one) is a config error the
check base turns into a loud ``CheckError``, failing the load like any config
typo; a well-formed reference that **fails to resolve** (store unreachable,
secret absent) raises :class:`SecretError`, which the check base records so the
engine pins that one check to a visible ERROR while everything else keeps
monitoring.
"""
from __future__ import annotations

import os
import secrets as stdlib
from collections.abc import Callable
from dataclasses import dataclass

from little_sister.origins import calling_package

# A resolver maps the address part of a ``scheme://address`` reference to the
# secret value; it may raise anything on failure (wrapped into SecretError).
Resolver = Callable[[str], str]

_SCHEME_SEPARATOR = "://"

#: What a caller that cannot be identified is called on the page and in a refusal.
#: :func:`~little_sister.origins.calling_package` answers ``""`` for ``__main__``
#: on purpose — it is what *any* script is called when run directly, so it names no
#: installation — and a blank in a message naming two claimants would read as a bug.
UNIDENTIFIED = "an unidentified caller (__main__)"


def same_secret(presented: str, stored: str) -> bool:
    """Compare a presented credential with a stored one, in constant time.

    Every credential comparison in this library goes through here, and the reason
    it is one function rather than a line at each site is a trap in the standard
    library that a reviewer had to find twice. ``secrets.compare_digest`` accepts
    ``str`` **only while both sides are ASCII** and raises ``TypeError`` otherwise —
    so a comparison written the obvious way works against every password anybody
    tests it with and raises a ``500`` the first time somebody types an umlaut.

    Both failure modes are worse than they look. An anonymous visitor gets a server
    error instead of *invalid password*, which is a difference an attacker can read;
    and a deployment that put a non-ASCII password in its ``.env`` — in a German
    organization, entirely plausible — has an emergency door that raises on **every**
    attempt, discovered during the incident it exists for.

    Encoding both sides sidesteps it: the comparison is over bytes, where the
    function has no such restriction. Length still leaks, as it does for any
    ``compare_digest`` call, which is why this compares credentials and not the
    presence of a credential.
    """
    return stdlib.compare_digest(presented.encode(), stored.encode())


class SecretError(Exception):
    """A well-formed reference failed to **resolve** — the store was unreachable
    or the secret is absent. The engine pins the owning check to ERROR
    (ADR-0023); contrast :class:`UnknownSchemeError` for a malformed reference.
    """


class UnknownSchemeError(Exception):
    """A reference is malformed — empty, carrying no ``scheme://`` at all, or
    naming a scheme no resolver is registered for. A config error:
    ``Check.resolve_secret`` raises it on as a ``CheckError``, so the load fails
    loudly like any config typo."""


class SchemeConflictError(Exception):
    """Two packages claim one scheme, and neither said it meant to replace the
    other. Raised from :func:`register_resolver` — that is, from the application's
    import-before-app block, so the process does not start (ADR-0064), the way a
    second claim on a ``type:`` name does not (little-sister ADR-0051)."""


@dataclass(frozen=True)
class Registration:
    """One claimed scheme: who answers for it, and whom that displaced.

    The resolver travels *with* its provenance rather than beside it in a second
    table, so there is one thing to register, one thing to look up and one thing a
    test substitutes — a parallel dict of owners is a dict that can disagree with
    the registry it describes.
    """
    scheme: str
    resolver: Resolver
    #: The package that registered it, inferred from the call site — ``""`` where
    #: the caller could not be identified (see :data:`UNIDENTIFIED`).
    package: str
    #: The package this claim deliberately replaced, or ``""``. Kept because a
    #: replacement is the one thing on this seam that an operator cannot deduce
    #: from the outcome: the page would otherwise show a scheme owned by whoever
    #: happens to own it, with nothing to say somebody else used to.
    replaced: str = ""

    @property
    def builtin(self) -> bool:
        """Whether the library itself claimed this scheme (``env``)."""
        return self.package == "little_sister"

    @property
    def owner(self) -> str:
        """The registering package as a page or a message should say it."""
        return self.package or UNIDENTIFIED


_resolvers: dict[str, Registration] = {}


def register_resolver(scheme: str, resolver: Resolver, *,
                      replace: bool = False) -> None:
    """Register ``resolver`` for ``scheme`` (e.g. ``aws-sm``).

    Called by the application before ``little_sister.app`` is imported. Schemes
    are case-insensitive. The registering **package** is inferred from the call
    site — a name the caller had to repeat is a name the caller can get wrong —
    and ``/system`` prints it, so a scheme that arrives from a separately released
    package can be traced to the code that answers for it.

    A scheme is claimed **once** (ADR-0064). Re-registering from the *same*
    package replaces the resolver silently, because a registration module may be
    imported more than once and refusing that would refuse a reloading server. A
    claim on a scheme **another** package holds raises
    :class:`SchemeConflictError` naming both, for the reason a duplicate ``type:``
    name does (little-sister ADR-0051): a scheme is where a credential is read
    from, so a silent last-wins would let import order decide which store a check
    authenticates against, and the loser's checks would read somebody else's
    secrets — or fail to, at a machine nobody is looking at.

    ``replace=True`` is how that is done on purpose, and it is the only way. A
    deployment overriding the built-in ``env`` with an implementation of its own is
    using a feature (ADR-0023) and keeps it; what it no longer does is happen by
    accident, and the replacement it made is recorded and shown rather than
    silently indistinguishable from a first claim.
    """
    scheme = scheme.strip().lower()
    if not scheme:
        raise ValueError("a resolver scheme must be non-empty")
    package = calling_package()
    claimed = _resolvers.get(scheme)
    replaced = ""
    if claimed is not None:
        if claimed.package == package:
            # The same package again: a reload, or a registration function a
            # deployment called twice. Carry any earlier replacement forward —
            # re-importing the module that overrode `env` must not quietly
            # un-say that it overrode anything.
            replaced = claimed.replaced
        elif not replace:
            raise SchemeConflictError(
                f"two packages claim the secret scheme '{scheme}://': "
                f"{claimed.owner} registered it and {package or UNIDENTIFIED} "
                f"claims it too. A scheme says where a credential is read from, "
                f"so import order must not be what decides it — rename the "
                f"scheme in one of them, install only one of the packages, or "
                f"pass replace=True where replacing the other is the point "
                f"(ADR-0064).")
        else:
            replaced = claimed.package
    _resolvers[scheme] = Registration(scheme=scheme, resolver=resolver,
                                      package=package, replaced=replaced)


def registered_resolvers() -> tuple[Registration, ...]:
    """Every claimed scheme with the package that answers for it, by scheme.

    For ``/system``, which shows this seam beside the others: a registration
    nobody can see from the running instance is indistinguishable from one that
    silently did not take, and — since the schemes are additive — the list is also
    the only answer to *what may I write in this config field*.
    """
    return tuple(_resolvers[scheme] for scheme in sorted(_resolvers))


def load_dotenv(path: str = ".env") -> None:
    """Populate ``os.environ`` from a simple ``KEY=VALUE`` ``.env`` file (ADR-0003).

    Dependency-free. Values already present in the environment take precedence, and
    a missing file is fine — a deployment that exports its variables another way, or
    a container that has none of this, is a legitimate install rather than a broken
    one.

    **It runs when this module is imported**, which is earlier than it looks and
    deliberately so. It used to run while ``little_sister.app`` was being imported,
    which was in time for everything the *app* reads and too late for anything a
    deployment resolves **before** that import: a registration that names a secret —
    the system-admin password is the first (ADR-0069 §5) — would have resolved
    against an environment the file had not reached yet, and been reported as a
    credential that does not resolve. The module that owns ``env://`` is the right
    one to have filled it, and importing anything that can resolve a reference now
    implies the file has been read.
    """
    try:
        with open(path, encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(
                    key.strip(), value.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


load_dotenv()


def _environment(name: str) -> str:
    """The built-in ``env`` resolver: a secret from the process environment,
    which ``.env`` feeds (ADR-0003). Registered below, so it travels the same
    path as every other scheme — no special case inside :func:`resolve`."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SecretError(f"environment variable {name!r} is not set (.env)")
    return value


register_resolver("env", _environment)


def resolve(reference: str) -> str:
    """Resolve a secret reference to its value.

    ``env://NAME`` reads that environment variable (fed by ``.env``, ADR-0003);
    any other scheme calls the resolver registered for it. Raises
    :class:`UnknownSchemeError` for a malformed reference — no scheme at all
    (a pasted secret value, typically), an empty address, or a scheme nothing is
    registered for — and :class:`SecretError` when a well-formed reference fails
    to resolve.
    """
    reference = reference.strip()
    if not reference:
        raise UnknownSchemeError("empty secret reference")
    if _SCHEME_SEPARATOR not in reference:
        # No scheme. Say what was expected without quoting what we got: an
        # unschemed string is most often a secret pasted where its *reference*
        # belongs, and this message travels into a visible error reason.
        raise UnknownSchemeError(
            "malformed secret reference: expected 'scheme://address' — "
            "'env://GITHUB_TOKEN' for an environment variable, or a scheme a "
            "resolver is registered for. The value is withheld from this "
            "message in case it is the secret itself: a config field names a "
            "secret, it never carries one.")
    scheme, _, address = reference.partition(_SCHEME_SEPARATOR)
    if not address.strip():
        raise UnknownSchemeError(
            f"secret reference {reference!r} has no address after {scheme!r}://")
    registration = _resolvers.get(scheme.strip().lower())
    if registration is None:
        known = ", ".join(sorted(_resolvers)) or "none"
        raise UnknownSchemeError(
            f"no secret resolver registered for scheme {scheme!r} "
            f"(reference {reference!r}; registered: {known})")
    try:
        value = registration.resolver(address)
    except SecretError:
        raise                      # a resolver that phrased its own failure
    except Exception as error:
        raise SecretError(
            f"could not resolve secret {reference!r}: {error}") from error
    if not value:
        raise SecretError(
            f"resolver for {scheme!r} returned no value for {reference!r}")
    return value


def looks_like_reference(value: str) -> bool:
    """Whether ``value`` is shaped like ``scheme://address`` rather than a secret.

    The **shape** test, in one place because two callers need the same answer for
    opposite reasons. :func:`resolve_setting` asks in order to *resolve* a setting
    that may carry either; a caller taking a literal credential asks in order to
    **refuse** one — a reference handed to a field that wants the value itself
    would quietly make the address the password, and that failure is invisible
    until the day the credential is needed (ADR-0069 §5).

    A shape, not a promise: a scheme nothing has registered still looks like a
    reference here and fails in :func:`resolve`, which is where the registered
    schemes are known.
    """
    return _SCHEME_SEPARATOR in value.strip()


def resolve_setting(value: str) -> str:
    """Resolve an application *setting* whose value may itself be a reference.

    Unlike :func:`resolve` — where every reference carries a scheme — the input
    here already **is** the value (it came from the environment): only a
    ``scheme://address`` shape is treated as a reference and resolved; anything
    else is returned as the literal setting. Used for
    ``SECRET_KEY`` and ``LITTLE_SISTER_API_TOKENS`` (see the ADR-0023 update
    note). The reference case raises exactly like :func:`resolve`.
    """
    value = value.strip()
    if looks_like_reference(value):
        return resolve(value)
    return value
