"""gunicorn's server hooks for a little-sister application (ADR-0091, ADR-0088).

Loaded with ``--config python:little_sister.gunicorn_hooks`` on the gunicorn line —
the run scripts carry the flag, and a deployment that runs gunicorn itself carries it
too. Two hooks, the two ends of an instance:

* ``post_worker_init`` is the **start**, in the worker right after it has imported the
  application and before it serves anything: the state directory's lease, the log
  file, the engine (ADR-0091 decision 2). A start the lease refuses raises, which
  gunicorn turns into its worker boot error and a halted server (decision 3).
* ``worker_exit`` is the **stop**, once the worker has left its loop and before the
  interpreter finalizes: the runs in flight abandoned, one save, the lease let go
  (ADR-0088 decision 5). ``atexit`` is its backstop for every other way of serving.

The module **never imports the application**, not even inside a hook. gunicorn loads
it in the master, where an import of the application would be an instance, and a
worker whose import failed must not start one on its way out. It finds the application
in ``sys.modules``, where the worker's import of its WSGI target — a deployment's
``wsgi.py`` or the application itself — put it.

It defines nothing else gunicorn reads: every other setting is the command line's.
"""
from __future__ import annotations

import sys
from typing import Any

#: The module a worker's import puts in ``sys.modules`` whatever WSGI target it serves.
_APPLICATION = "little_sister.app"


def post_worker_init(worker: Any) -> None:
    """The server's start, in the worker, right after its import (ADR-0091)."""
    application = sys.modules.get(_APPLICATION)
    if application is not None:
        application.start()


def worker_exit(server: Any, worker: Any) -> None:
    """The instance's stop, when the worker leaves (ADR-0088 decision 5)."""
    application = sys.modules.get(_APPLICATION)
    if application is not None:
        application.stop(trigger="worker_exit")
