"""Secret references: name where a secret comes from, resolve it once (ADR-0023).

A reference is a string in a check's config, and it always has the same shape:
``scheme://address``. ``env://GITHUB_TOKEN`` reads that environment variable —
ADR-0003's behavior, now spelled out loud; ``aws-sm://team/github-token`` goes to
the resolver the **application registered** for that scheme: a deployment calls
:func:`register_resolver` in its own code before importing ``little_sister.app``
— the same slot its WSGI wrapper uses to register check types — and owns the
resolver's dependencies; the library ships no store client (``env`` is the one
built-in).

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
from collections.abc import Callable

# A resolver maps the address part of a ``scheme://address`` reference to the
# secret value; it may raise anything on failure (wrapped into SecretError).
Resolver = Callable[[str], str]

_SCHEME_SEPARATOR = "://"


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


_resolvers: dict[str, Resolver] = {}


def register_resolver(scheme: str, resolver: Resolver) -> None:
    """Register ``resolver`` for ``scheme`` (e.g. ``aws-sm``).

    Called by the application before ``little_sister.app`` is imported.
    Schemes are case-insensitive; re-registering a scheme replaces the previous
    resolver (registration modules may be imported more than once) — including
    ``env``, which this module registers for itself at import and which a
    deployment therefore *can* replace, deliberately, like any other.
    """
    scheme = scheme.strip().lower()
    if not scheme:
        raise ValueError("a resolver scheme must be non-empty")
    _resolvers[scheme] = resolver


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
    resolver = _resolvers.get(scheme.strip().lower())
    if resolver is None:
        known = ", ".join(sorted(_resolvers)) or "none"
        raise UnknownSchemeError(
            f"no secret resolver registered for scheme {scheme!r} "
            f"(reference {reference!r}; registered: {known})")
    try:
        value = resolver(address)
    except SecretError:
        raise                      # a resolver that phrased its own failure
    except Exception as error:
        raise SecretError(
            f"could not resolve secret {reference!r}: {error}") from error
    if not value:
        raise SecretError(
            f"resolver for {scheme!r} returned no value for {reference!r}")
    return value


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
    if _SCHEME_SEPARATOR in value:
        return resolve(value)
    return value
