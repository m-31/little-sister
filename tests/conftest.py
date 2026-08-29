"""Shared test setup.

The web/api tests import ``little_sister.app``, which loads the user list at
import time (ADR-0020) — and importing ``little_sister.config`` resolves the
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
"""

import os

import pytest

from little_sister.actions import forget_actions
from little_sister.config_dir import forget_aspects
from little_sister.csp import forget_contributions
from little_sister.icons import forget_packs
from little_sister.identity import forget_doors
from little_sister.link_probe import forget_probe_results
from little_sister.links import forget_cached_links
from little_sister.local_login import use_local
from little_sister.slots import forget_fillers

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_USERS_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "config")

os.environ.setdefault(
    "LITTLE_SISTER_CONFIG_DIR",
    os.pathsep.join((_USERS_ROOT, os.path.join(_REPO_ROOT, "config"))),
)
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")


@pytest.fixture(autouse=True)
def _forget_process_caches():
    """Reset the caches a running process keeps and a test suite must not share.

    The links parse cache
    (:func:`little_sister.links.forget_cached_links`) is keyed on size and mtime,
    which a test rewriting a file within one filesystem tick can defeat; the icon
    registry (:func:`little_sister.icons.forget_packs`) would otherwise let a pack
    one test registers decide another test's resolution; the slot registry
    (:func:`little_sister.slots.forget_fillers`) and the registered configuration
    aspects (:func:`little_sister.config_dir.forget_aspects`) are the same story for
    the two extension seams (ADR-0034 / ADR-0035) — a filler one test registers
    would otherwise put its button on every later test's page — and so are the
    Content-Security-Policy contributions
    (:func:`little_sister.csp.forget_contributions`), which are the third seam a
    package registers into (ADR-0048). The reachability
    answers (:func:`little_sister.link_probe.forget_probe_results`) are the same
    story once more: a verdict one test seeded is a verdict the next test's page
    would render. The identity doors
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
    forget_packs()
    forget_fillers()
    forget_aspects()
    forget_contributions()
    forget_probe_results()
    forget_doors()
    use_local()
