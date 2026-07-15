"""little-sister — a small status-monitoring web application."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("little-sister")
except PackageNotFoundError:  # running from a source tree with no install
    __version__ = "0+unknown"

__all__ = ["__version__"]
