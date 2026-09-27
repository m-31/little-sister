"""Logging setup — a **default**, never a seizure.

little-sister logs through the standard hierarchy and nothing else: its records
propagate to the **root** logger, so whoever configures that owns where they go.
This module configures root itself only when the application has **not** — no
handlers on it by the time we import — which is the ordinary case for
``./start.sh`` and gives the console (a ``StreamHandler``, so **stderr**) plus,
once the server's start calls :func:`open_log_file`, ``var/little-sister.log``
(``LOG_FILE`` overrides the path).

**An import opens no log file** (ADR-0091): importing the application is not an
instance, and a file in the working directory is the instance's. What the import
logs goes to stderr and into a bounded buffer — the first :data:`START_BUFFER`
records — which :func:`open_log_file` writes into the file before anything else, so
a run's log still begins with its configuration; past the bound it writes one line
counting what went to stderr only. A plain import leaves its lines on stderr.

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
_formatter = logging.Formatter(_FORMAT)

#: How many records an import may log before the start writes them into the log
#: file it opens (ADR-0091 decision 4); the rest reach stderr only, and are counted.
START_BUFFER = 1000


class _StartBuffer(logging.Handler):
    """What the import logs, kept for the log file the server's start opens."""

    def __init__(self, capacity: int) -> None:
        super().__init__()
        self.capacity = capacity
        self.records: list[logging.LogRecord] = []
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        if len(self.records) < self.capacity:
            self.records.append(record)
        else:
            self.dropped += 1


#: The buffer, while the default is in charge and no file is open yet.
_buffer: _StartBuffer | None = None
#: The log file's handler, once the start has opened it.
_file_handler: logging.FileHandler | None = None

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

    _stream_handler = logging.StreamHandler()
    _stream_handler.setFormatter(_formatter)
    root_logger.addHandler(_stream_handler)

    # No file yet, and not even its directory: that is the start's (ADR-0091).
    _buffer = _StartBuffer(START_BUFFER)
    root_logger.addHandler(_buffer)

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
        # Log only, and on purpose: this runs while the logger is being built,
        # beneath every module that could record a self-report line — and a note
        # about the log level belongs where the level was set, which is here.
        logger.warning("logger: LOG_LEVEL %r is not a level name; using %s",
                       _LEVEL_NAME, _DEFAULT_LEVEL)


def open_log_file() -> None:
    """The server's start (ADR-0091 decision 4): open the log file — ``LOG_FILE``, or
    ``var/little-sister.log`` of the working directory — and write into it first what
    the import logged, so that a run's log begins with its configuration.

    Where the application configured logging itself this does nothing: the file is
    the default's, and the default did not run. A second call does nothing either.
    """
    global _buffer, _file_handler
    buffer = _buffer
    if buffer is None or _file_handler is not None:
        return
    directory = os.path.dirname(_LOG_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handler = logging.FileHandler(_LOG_FILE)
    handler.setFormatter(_formatter)
    for record in buffer.records:
        handler.handle(record)
    root_logger.removeHandler(buffer)
    root_logger.addHandler(handler)
    _file_handler, _buffer = handler, None
    if buffer.dropped:
        logger.info("logger: %d more lines were logged before the start opened this "
                    "file, and went to stderr only", buffer.dropped)
