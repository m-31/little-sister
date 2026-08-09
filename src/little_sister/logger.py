"""Logging setup — a **default**, never a seizure.

little-sister logs through the standard hierarchy and nothing else: its records
propagate to the **root** logger, so whoever configures that owns where they go.
This module configures root itself only when the application has **not** — no
handlers on it by the time we import — which is the ordinary case for
``./start.sh`` and gives the console (a ``StreamHandler``, so **stderr**) plus
``var/little-sister.log`` (``LOG_FILE`` overrides the path).

A deployment or a plugin that wants its own logging therefore just sets it up
**before** importing ``little_sister.app``, in the same import-before-app block it
registers check types in: its handlers stay, its level stays, and little-sister's
own records arrive there too. That is the promise (architecture.md §11,
ADR-0049) — not this module's name. A plugin never imports ``logger`` from here;
it calls ``logging.getLogger(__name__)`` like any Python library, and the records
land wherever the application decided.

The level and the third-party noise caps below sit **inside** the guard for the
same reason: a `setLevel` outside it would override the level an application had
already chosen, which is the one thing a library must not do to logging.
"""
import logging
import os

_LOG_FILE = os.environ.get("LOG_FILE", "var/little-sister.log")
_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

root_logger = logging.getLogger()

# Nobody has configured logging (also the guard against duplicate handlers when
# this module is imported more than once, e.g. under a reloading server).
if not root_logger.handlers:
    root_logger.setLevel(logging.DEBUG)

    _formatter = logging.Formatter(_FORMAT)

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_formatter)
    root_logger.addHandler(_stream_handler)

    _log_dir = os.path.dirname(_LOG_FILE)
    if _log_dir:
        os.makedirs(_log_dir, exist_ok=True)
    _file_handler = logging.FileHandler(_LOG_FILE)
    _file_handler.setFormatter(_formatter)
    root_logger.addHandler(_file_handler)

    # Noise caps that belong to *our* DEBUG default and to nobody else's setup:
    # httpx logs an INFO line per request, and markdown-it-py a DEBUG line per
    # block rule per render — far too chatty when we render node text on every
    # page. An application that configured its own logging makes this call itself.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("markdown_it").setLevel(logging.INFO)

logger = logging.getLogger(__name__)
