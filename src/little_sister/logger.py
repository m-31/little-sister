# Configure logging: stream to stdout and to an explicit log file.
import logging
import os

_LOG_FILE = os.environ.get("LOG_FILE", "var/little-sister.log")
_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Guard against duplicate handlers if this module is imported more than once
# (e.g. under a reloading server).
if not root_logger.handlers:
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

# Suppress noisy INFO logging from httpx.
logging.getLogger("httpx").setLevel(logging.WARNING)

# markdown-it-py logs a DEBUG line per block rule per render — far too chatty for
# our DEBUG root level (it renders node text on every page). Cap it at INFO.
logging.getLogger("markdown_it").setLevel(logging.INFO)

logger = logging.getLogger(__name__)
