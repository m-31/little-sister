"""Shared test setup.

The web/api tests import ``little_sister.app``, which loads the user list at
import time (ADR-0046 decision 3) — and importing ``little_sister.config`` resolves the
configuration directory (ADR-0031). Point them at committed paths so the suite is
self-contained: independent of any deployment's files and of the current working
directory. These run at collection time, before the test modules import the app,
and use ``setdefault`` so an explicit override still wins.

One path-list does both. ``tests/fixtures/config`` comes **first** and carries only
the ``users`` aspect (in the ADR-0045 directory form, so the fixture avatar resolves
too); the repo's own ``config`` follows with the checks, settings, links and actions.
That order *is* the single-file user override: ``users`` is the one aspect that does
not layer — the first root declaring it wins whole (ADR-0031) — so a developer's own
git-ignored ``config/users/`` can never decide what the suite logs in as.

Nothing here switches the engine off, and nothing has to: importing the application
is not an instance (ADR-0091). The suite imports it and never starts it, so every test
begins with no engine and the banner that says it was never started; a test that
wants another state sets it, and one that starts the application does so in a child
interpreter of its own (``test_start.py``, ``test_gunicorn_hooks.py``).

**The level the suite logs at is said before the library is imported**, and it is the
one line that has to come first. In the suite the logging default is in charge —
the first import below happens before pytest installs a handler — and the default
reads ``.env`` before it reads ``LOG_LEVEL`` (ADR-0121 decision 6). So a ``LOG_LEVEL``
line in the ``.env`` of the directory the suite runs in, a developer's own, decided
what the suite logs at, and the tests that read the log failed on ``WARNING`` and
above. ``setdefault`` is enough for that: the file never replaces what the
environment holds. A level exported in the shell still stands, as an override does.
"""

import os

# Ahead of every import of the library, the first of which is below: it reads `.env`
# and then `LOG_LEVEL` (the docstring's last paragraph). An import sorter leaves a
# line that sets the environment where it stands; nothing of ours may move above it.
os.environ.setdefault("LOG_LEVEL", "INFO")

import pytest

from little_sister.actions import forget_actions
from little_sister.config_dir import forget_aspects
from little_sister.csp import forget_contributions
from little_sister.handbooks import forget as forget_handbooks
from little_sister.icons import forget_packs
from little_sister.identity import forget_doors
from little_sister.keeper import forget_keeper
from little_sister.links import forget_cached_links
from little_sister.local_login import use_local
from little_sister.notes import forget_notes
from little_sister.process import forget_stop
from little_sister.self_report import forget_contributors
from little_sister.slots import forget_fillers

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_USERS_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "config")

os.environ.setdefault(
    "LITTLE_SISTER_CONFIG_DIR",
    os.pathsep.join((_USERS_ROOT, os.path.join(_REPO_ROOT, "config"))),
)
os.environ.setdefault("SECRET_KEY", "test-key")


@pytest.fixture(autouse=True)
def _forget_process_caches():
    """Reset the caches a running process keeps and a test suite must not share.

    The links parse cache
    (:func:`little_sister.links.forget_cached_links`) is keyed on size and mtime,
    which a test rewriting a file within one filesystem tick can defeat; the
    handbooks a statement named (:func:`little_sister.handbooks.forget`) would let
    one test's read file pass for named in another's startup pass; the icon
    registry (:func:`little_sister.icons.forget_packs`) would otherwise let a pack
    one test registers decide another test's resolution; the slot registry
    (:func:`little_sister.slots.forget_fillers`) and the registered configuration
    aspects (:func:`little_sister.config_dir.forget_aspects`) are the same story for
    the two extension seams (ADR-0034 / ADR-0035) — a filler one test registers
    would otherwise put its button on every later test's page — and so are the
    Content-Security-Policy contributions
    (:func:`little_sister.csp.forget_contributions`), which are the third seam a
    package registers into (ADR-0048). So are the self-report contributors
    (:func:`little_sister.self_report.forget_contributors`), whose lines one test
    registers would otherwise ride every later test's heartbeat; and the keeper
    (:func:`little_sister.keeper.forget_keeper`), the one seam whose leftover
    registration would have a later test's state layer writing into somebody
    else's store; and the notes (:func:`little_sister.notes.forget_notes`), which a
    pin one test sets writes into the process's book, and whose count would
    otherwise stand on a later test's tabs. The instance's stop
    (:func:`little_sister.process.forget_stop`) is one more: after an engine's stop
    no process starts in this interpreter (ADR-0088), which in a test suite would
    be every later test's command check. The identity doors
    (:func:`little_sister.identity.forget_doors`) are the sharpest case of it: a
    door one test registers decides *who every later test is*, and a default one
    makes ``/login`` somebody else's page (ADR-0069). They are also the one registry
    that is **put back** rather than merely emptied, and the line below is this
    suite standing in for the ``wsgi.py`` it does not run: an installation registers
    its own doors now, so leaving the registry empty would leave every later test on
    an instance nobody can log into. A case that wants that state asks for it, by
    calling :func:`~little_sister.identity.forget_doors` itself.
    """
    forget_actions()
    forget_cached_links()
    forget_handbooks()
    forget_packs()
    forget_fillers()
    forget_aspects()
    forget_contributions()
    forget_doors()
    forget_contributors()
    forget_keeper()
    forget_notes()
    forget_stop()
    use_local()
