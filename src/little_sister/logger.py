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

The level, the level ``LOG_LEVEL`` asks for, and the third-party noise caps below
all sit **inside** the guard for the same reason: a `setLevel` outside it would
override the level an application had already chosen, which is the one thing a
library must not do to logging. So ``LOG_LEVEL`` names the level of *this*
default and of nothing else — set it against an application that configured its
own logging and it does nothing, because the level is then that application's to
choose.

The default is **INFO**, and what makes it the right one is that no module here
calls ``logger.debug``: little-sister's own records start at INFO, so a DEBUG
root adds none of our lines and every dependency's. One deployment's log ran two
thirds ``botocore`` request detail nobody had asked for. ``LOG_LEVEL=DEBUG`` asks
for that on purpose — which is also when the caps below earn their place, since
they are what keeps a deliberate DEBUG session readable.
"""
import logging
import os

_LOG_FILE = os.environ.get("LOG_FILE", "var/little-sister.log")
_DEFAULT_LEVEL = "INFO"
_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Resolved before the guard because it is only *read* here — nothing is decided
# until the guard is taken. An unknown name is a typo in a deployment's
# environment, not a reason to refuse to log: fall back and say so, once the
# handlers that carry the warning exist.
_LEVEL_NAME = os.environ.get("LOG_LEVEL", _DEFAULT_LEVEL)
_level = logging.getLevelNamesMapping().get(_LEVEL_NAME.strip().upper())

root_logger = logging.getLogger()
logger = logging.getLogger(__name__)

# Nobody has configured logging (also the guard against duplicate handlers when
# this module is imported more than once, e.g. under a reloading server).
if not root_logger.handlers:
    root_logger.setLevel(_level if _level is not None else logging.INFO)

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

    # Noise caps that belong to *our* default and to nobody else's setup: httpx
    # logs an INFO line per request, so it is chatty at the default level itself,
    # and markdown-it-py a DEBUG line per block rule per render — far too chatty
    # when we render node text on every page — so it is what a `LOG_LEVEL=DEBUG`
    # session would drown in. An application that configured its own logging
    # makes this call itself, for these two and for its own dependencies: a cap
    # on somebody else's logger is a decision about somebody else's log.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("markdown_it").setLevel(logging.INFO)

    if _level is None:
        logger.warning("logger: LOG_LEVEL %r is not a level name; using %s",
                       _LEVEL_NAME, _DEFAULT_LEVEL)
