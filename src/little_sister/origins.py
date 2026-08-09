"""Where an import package came from — the distribution, the version, the file.

One question, asked by two seams. A check type answers *which code is answering for
`type: github`, at which version* (ADR-0051); a surface extension — slot fillers, an
asset, a configuration aspect — answers the same thing about a package that
registers no type at all, and until ``/system`` grew a package inventory it could
not answer it anywhere. Both read it off the running process, because once a
contribution can arrive from a separately released package neither is derivable from
this repository.

The lookup lives here rather than in ``checks/base.py`` so the answer does not
depend on the asker being a check.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, packages_distributions
from importlib.metadata import version as metadata_version


@dataclass(frozen=True)
class PackageOrigin:
    """What answers for one import package, as the running process sees it."""
    package: str
    distribution: str
    version: str
    #: Where the package was actually **loaded from**. The version beside it is the
    #: installed *metadata's* claim, and the two can disagree — a source copy on the
    #: path shadows an installed distribution of the same name, and the metadata
    #: keeps answering for code that is not running. That case is the one an
    #: operator comes to this page for, so the page shows both.
    path: str

    @property
    def builtin(self) -> bool:
        """Whether this is the library itself."""
        return self.package == "little_sister"


@lru_cache(maxsize=1)
def _distribution_of() -> dict[str, str]:
    """Import package -> the distribution that installed it (first, if several).

    Cached: registration happens at startup and nothing installs a package into a
    running process.
    """
    return {package: dists[0]
            for package, dists in packages_distributions().items() if dists}


def release_of(package: str) -> tuple[str, str]:
    """``(distribution, version)`` for an import package, or two empty strings.

    Two lookups, because the first one has a hole. ``packages_distributions()``
    reads the installed metadata, which an editable src-layout install may not carry
    — and a development checkout is exactly where somebody debugging a plugin sits.
    So a miss falls back to the naming convention this family follows anyway
    (``little_sister_x`` is shipped as ``little-sister-x``), and a package that is
    genuinely not installed — a deployment's own module on the path — answers with
    nothing, which the page shows as *source*.
    """
    for distribution in (_distribution_of().get(package, ""),
                         package.replace("_", "-")):
        if not distribution:
            continue
        try:
            return distribution, metadata_version(distribution)
        except PackageNotFoundError:
            continue
    return "", ""


def calling_package(depth: int = 2) -> str:
    """The top-level package ``depth`` frames up the stack, or ``""``.

    Registration seams that record *who registered* infer it rather than asking for
    it: the one-line call site in a package's ``__init__`` already says who it is,
    and a name the caller had to repeat is a name the caller can get wrong. Default
    ``depth`` 2 is the caller of the function that calls this.

    ``__main__`` answers ``""``. A deployment that registers from its own entry
    module is a real case and keeps its name — under gunicorn that module is
    ``wsgi``, which points at a file somebody can open — but ``__main__`` names
    nothing: it is what *any* script is called when run directly, so it changes with
    the launcher and identifies no installation. An honest blank beats a name that
    cannot be looked up.
    """
    frame = sys._getframe(depth) if hasattr(sys, "_getframe") else None
    name = str(frame.f_globals.get("__name__", "")) if frame is not None else ""
    return "" if name == "__main__" else name.split(".")[0]


def package_origin(package: str) -> PackageOrigin:
    """Everything ``/system`` prints about one registering package.

    The path is the **package's own** file (its ``__init__``), not the module a
    particular contribution was defined in: a package that fills two slots from two
    modules is still one installation, and one row.
    """
    distribution, version = release_of(package)
    loaded = sys.modules.get(package)
    return PackageOrigin(package=package, distribution=distribution,
                         version=version,
                         path=getattr(loaded, "__file__", "") or "")
