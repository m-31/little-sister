"""Errors shared across the package.

:class:`CheckError` lives here rather than in ``checks.base`` so that low-level
helpers (:mod:`little_sister.values`) and top-level modules (``config``,
``maintenance``) can raise it without importing the ``checks`` package — importing
``checks`` registers every built-in check type as a side effect (see
``checks/__init__.py``), which those layers have no business triggering.
``checks.base`` re-exports it, so ``from little_sister.checks.base import
CheckError`` keeps working.

The two are deliberately **unrelated** classes rather than a hierarchy, because the
application treats them differently: a :class:`CheckError` is caught at startup and
becomes the header's ``engine_error`` banner — one file is wrong and the rest of the
dashboard still tells the truth — while a :class:`ConfigError` is never caught, so
the process refuses to start (ADR-0031). Making one a subclass of the other would
put that difference one ``except`` clause away from disappearing.
"""
from __future__ import annotations


class CheckError(Exception):
    """Raised for invalid check configuration, or for a config/payload value that
    cannot be read as the type the caller asked for (see :mod:`little_sister.values`).
    """


class ConfigError(Exception):
    """Raised when the deployment's configuration *tree* is unusable (ADR-0031) —
    no configuration directory, a named root that does not exist, no ``checks``
    aspect anywhere, or an aspect stored in a form it does not have.

    Fatal by design and **not** caught anywhere: every case here is one where the
    instance cannot be right and has no useful degraded mode, so serving a
    reassuring page would be the worst answer. Each message names the resolved
    path it looked at.
    """
