"""Shared test setup.

The web/api tests import ``little_sister.app``, which loads the user list at
import time (ADR-0020). Point it at a committed fixture so the suite is
self-contained — independent of any deployment ``users.yaml`` and of the current
working directory. These run at collection time, before the test modules import
the app, and use ``setdefault`` so an explicit override still wins.
"""

import os

os.environ.setdefault(
    "LITTLE_SISTER_USERS",
    os.path.join(os.path.dirname(__file__), "fixtures", "users.yaml"),
)
os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")
