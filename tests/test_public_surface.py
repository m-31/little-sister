"""The check-authoring surface is exactly what the contract says it is.

`architecture.md` §11 promises a list of names to check types written outside this
repository (ADR-0049). A promise nobody measures decays the first time a name is
renamed in a refactor that looks local — so this test **reads the doc** and holds
the code against it. The doc stays the single source of truth; there is no second
list here to keep in step with it.

Two directions, and the second is the one that needs a mechanism:

* **doc → code** — every promised name imports, for every promised module. A name
  that leaves the surface fails here.
* **code → doc** — a module that declares ``__all__`` must declare *exactly* what
  the doc promises. That is what stops a name from quietly joining the surface:
  ``little_sister.checks`` is a facade whose ``__all__`` is its public face, and a
  name added there but not promised would be a contract nobody wrote down.
  Modules without ``__all__`` (``reasons``, ``status``) carry public internals on
  purpose and are checked one way only.
* **epoch → doc** — the surface an epoch promised is snapshotted in
  ``fixtures/check_api_v<n>.txt``, and the block must still contain all of it.
  Neither direction above can catch a rename that edits the code *and* the doc in
  one commit; this one can, because the snapshot is what a *released* plugin was
  built against and a same-commit edit does not touch it. Removing a name means
  bumping ``API_VERSION`` and writing the next snapshot — which is exactly the
  decision ADR-0051 wants somebody to make deliberately.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from little_sister.checks import API_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
SNAPSHOTS = Path(__file__).resolve().parent / "fixtures"

#: The bullet whose fenced block is the promise. Kept as prose rather than a
#: heading so the doc reads as a list of promises, not as a generated appendix.
BULLET = "**Check-authoring surface**"

FENCE = "```"


def _promised() -> dict[str, list[str]]:
    """The surface as the doc states it: ``module -> [name, ...]``.

    The block's shape is a module on its own line, its names indented beneath it
    and free to wrap onto further lines — readable in the doc, unambiguous here.
    """
    lines = ARCHITECTURE.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if BULLET in line), None)
    assert start is not None, f"{ARCHITECTURE.name} no longer has a {BULLET} bullet"
    opening = next(i for i in range(start, len(lines))
                   if lines[i].strip().startswith(FENCE))
    closing = next(i for i in range(opening + 1, len(lines))
                   if lines[i].strip().startswith(FENCE))
    surface: dict[str, list[str]] = {}
    module = ""
    for line in lines[opening + 1:closing]:
        text = line.strip()
        if not text:
            continue
        if text.startswith("little_sister"):
            module = text
            surface[module] = []
            continue
        assert module, f"names before any module in the {BULLET} block: {text!r}"
        surface[module].extend(text.split())
    return surface


SURFACE = _promised()


def test_the_promise_block_parses_into_modules_and_names() -> None:
    """A guard on the parser itself: a doc edit that broke the block's shape would
    otherwise leave every assertion below trivially satisfied."""
    assert set(SURFACE) == {
        "little_sister.checks",
        "little_sister.reasons",
        "little_sister.status",
        "little_sister.values",
    }, ("the promised modules changed — if that is deliberate, this guard moves with "
        "the doc; it exists so a broken block cannot leave every check below "
        "trivially satisfied.")
    assert all(names for names in SURFACE.values())


@pytest.mark.parametrize("module", sorted(SURFACE))
def test_every_promised_name_is_importable(module: str) -> None:
    """doc → code: the promise is kept, name by name."""
    imported = importlib.import_module(module)
    missing = [name for name in SURFACE[module] if not hasattr(imported, name)]
    assert not missing, (
        f"{module} no longer exports {', '.join(missing)} — promised in "
        f"architecture.md §11. Restore the name, or bump the version and write "
        f"the ADR that retires it.")


@pytest.mark.parametrize("module", sorted(SURFACE))
def test_a_module_with_all_promises_exactly_it(module: str) -> None:
    """code → doc: where a module declares its public face, the doc states the
    same face. This is the direction that catches a name joining the surface
    without anybody promising it."""
    imported = importlib.import_module(module)
    declared = getattr(imported, "__all__", None)
    if declared is None:
        pytest.skip(f"{module} declares no __all__ — checked doc → code only")
    assert sorted(declared) == sorted(SURFACE[module]), (
        f"{module}.__all__ and architecture.md §11 disagree: a public name here "
        f"is a promise, so the two lists move together or neither does.")


def test_no_promised_name_is_private() -> None:
    """An underscore name in the block would promise an internal by accident."""
    for module, names in SURFACE.items():
        for name in names:
            assert not name.startswith("_"), f"{module}.{name} is not public"


def test_the_epoch_snapshot_is_still_promised() -> None:
    """Everything epoch `API_VERSION` promised is still on the surface.

    The snapshot is what a plugin released against this epoch was built to import.
    Dropping a name from it is not a refactor, it is a new epoch — and the failure
    here says so, because the alternative is an `ImportError` inside somebody
    else's package at their process start.
    """
    snapshot = SNAPSHOTS / f"check_api_v{API_VERSION}.txt"
    assert snapshot.exists(), (
        f"API_VERSION is {API_VERSION} but {snapshot.name} does not exist — a new "
        f"epoch takes a snapshot of what it promises (ADR-0051).")
    promised = {f"{module} {name}"
                for module, names in SURFACE.items() for name in names}
    recorded = [line.strip()
                for line in snapshot.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]
    assert len(recorded) > 20, f"{snapshot.name} parsed to almost nothing"
    missing = sorted(line for line in recorded if line not in promised)
    assert not missing, (
        f"check API v{API_VERSION} promised these and the surface no longer has "
        f"them: {', '.join(missing)}. Restore them, or bump API_VERSION and write "
        f"the snapshot for the new epoch (ADR-0051).")


def test_the_doc_states_the_epoch_the_code_speaks() -> None:
    """§11 tells a plugin author which number to pass to `require_api`.

    Whitespace-insensitive on purpose: the surrounding prose is re-wrapped every
    time the surface grows, and a test that failed on a reflow would be a false
    accusation about the one fact it is meant to protect.
    """
    text = ARCHITECTURE.read_text(encoding="utf-8")
    stated = re.search(r"`API_VERSION`,\s+currently\s+\*\*(\d+)\*\*", text)
    assert stated is not None, (
        "architecture.md §11 no longer states the current check API epoch.")
    assert int(stated.group(1)) == API_VERSION, (
        f"architecture.md §11 says the check API epoch is {stated.group(1)}, the "
        f"code speaks v{API_VERSION}.")


def test_the_import_point_is_the_package_not_the_module() -> None:
    """§11 promises `little_sister.checks`, not the module a name happens to live
    in today. The facade has to be the real object, or a plugin following the doc
    would get a different class than the registry holds."""
    from little_sister.checks import Check, CheckError, register
    from little_sister.checks.base import Check as BaseCheck
    from little_sister.checks.base import CheckError as BaseCheckError
    from little_sister.checks.base import register as base_register

    assert Check is BaseCheck
    assert CheckError is BaseCheckError
    assert register is base_register
