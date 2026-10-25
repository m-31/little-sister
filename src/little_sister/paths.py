"""A loaded-from path, printed against a root the reader already has.

``/system`` prints where each check type's module and each registering package
were **loaded from**, and on a real deployment that is an absolute path into the
virtualenv::

    /Users/someone/Projects/deployment/.venv/lib/python3.14/site-packages/little_sister_github/github.py

Nine tenths of that string is the same prefix on every row; the tenth that
differs is the module, which is printed directly above it; and the leading part
is somebody's home directory on a page that is read over a shoulder and pasted
into tickets.

**What the path is for survives the shortening.** It exists for one diagnostic
and it is a good one: a source copy earlier on ``sys.path`` shadows an installed
distribution of the same name, and then the version printed beside it is
answering for code that is not running. That is a question about *which root* the
module came from, not about the absolute string — so the answer is the root,
named:

* ``./my_deployment/checks.py`` — under the working directory, which is
  the case that matters: a checkout shadowing an install;
* ``site-packages/little_sister_github/github.py`` — an ordinary installation
  into the environment (or into the user's, which is a ``site-packages`` too);
* anything under neither root stays long, which is itself the signal.

**The longest matching root wins**, and that is not a tie-break detail: a venv
normally sits *inside* the project it belongs to, so both roots match an
installed package and only the longer one — ``site-packages`` — says anything the
reader did not already know.

**This is a view rule, not a data one.** :class:`~little_sister.origins.PackageOrigin`
and :class:`~little_sister.checks.base.TypeOrigin` keep the absolute path, and so
does anything reading them; what changes is what a page draws. The full string is
still one hover away in the rendered ``title``, for the reader who wants it.
"""
from __future__ import annotations

import sysconfig
from collections.abc import Iterable
from pathlib import Path


def _environment_roots() -> list[str]:
    """Every ``site-packages`` this interpreter installs into.

    Two schemes, because there are two ordinary ways to be installed and only one
    of them is the environment's own. A ``pip install --user`` package lands under
    the user's home directory, so leaving that scheme out would not merely print a
    longer path — it would print the operator's home directory on the one page
    most likely to be screenshotted.
    """
    schemes = (sysconfig.get_default_scheme(),
               sysconfig.get_preferred_scheme("user"))
    roots = [sysconfig.get_paths(scheme).get(key, "")
             for scheme in schemes for key in ("purelib", "platlib")]
    return [root for root in dict.fromkeys(roots) if root]


def shown_path(path: str, *, environment: Iterable[str] | None = None,
               project: str | None = None) -> str:
    """``path`` written against the nearest root the reader has, or unchanged.

    ``environment`` and ``project`` default to this process's answers — the
    interpreter's ``site-packages`` directories and the working directory a
    deployment is started from (ADR-0031). They are arguments at all so that the
    rule can be exercised against roots a test chooses, rather than against
    whichever machine happens to run the suite.

    An empty ``path`` — a module with no ``__file__``, which the origin records as
    the empty string — comes back empty, so the templates keep the plain truth
    test they already had around it.
    """
    if not path:
        return path
    roots = [(root, Path(root).name) for root
             in (_environment_roots() if environment is None else environment)]
    roots.append((str(Path.cwd()) if project is None else project, "."))
    shown, matched = path, ""
    for root, label in roots:
        if not root or len(root) < len(matched):
            continue
        try:
            rest = Path(path).relative_to(root)
        except ValueError:
            continue
        shown, matched = f"{label}/{rest.as_posix()}", root
    return shown
