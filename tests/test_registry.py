"""What startup refuses at the plugin boundary (ADR-0051).

Two failures become possible the moment a check type can arrive from a separately
released package, and both are silent by default:

* two packages claiming one ``type:`` name — import order picks the winner, and the
  losing package's checks then run somebody else's code against the losing
  package's configuration;
* a plugin built against a check API epoch this library no longer speaks — which
  surfaces, if at all, as an `ImportError` deep inside the plugin.

Both are turned into refusals with the two parties named. The registry is process
global, so every test here restores it.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest

from little_sister.checks import CHECK_TYPES, CheckError, register, require_api
from little_sister.checks.base import API_VERSION, Check, CheckResult, registered_types
from little_sister.status import StatusCode

TYPE_NAME = "test-registry-example"


@pytest.fixture(autouse=True)
def clean_registry() -> Iterator[None]:
    """The registry is module state; hand it back exactly as it was."""
    saved = dict(CHECK_TYPES)
    try:
        yield
    finally:
        CHECK_TYPES.clear()
        CHECK_TYPES.update(saved)


def _a_check_class(name: str) -> type[Check]:
    """A minimal registrable check, built fresh so each has its own identity.

    ``__module__`` is set explicitly: a class built through ``type()`` on an
    ``ABCMeta`` base otherwise reports ``abc`` as its module, which would make these
    tests agree with a refusal message no real class could produce.
    """
    return type(name, (_Example,), {"__module__": __name__,
                                    "__qualname__": f"_a_check_class.<locals>.{name}"})


class _Example(Check):
    def run(self) -> CheckResult:                # pragma: no cover - never run
        return CheckResult(code=StatusCode.OK)


def test_a_type_name_is_claimed_once() -> None:
    register(TYPE_NAME)(_a_check_class("First"))

    with pytest.raises(CheckError) as refusal:
        register(TYPE_NAME)(_a_check_class("Second"))

    message = str(refusal.value)
    assert TYPE_NAME in message
    # Both parties named: a refusal that says only "already registered" leaves the
    # operator to find which two packages are fighting.
    assert "First" in message and "Second" in message
    assert CHECK_TYPES[TYPE_NAME].__name__ == "First"


def test_re_registering_the_same_class_is_not_a_conflict() -> None:
    """A module re-imported under a reloading server re-runs its decorators."""
    cls = _a_check_class("Same")

    register(TYPE_NAME)(cls)
    register(TYPE_NAME)(cls)

    assert CHECK_TYPES[TYPE_NAME] is cls


def test_two_classes_from_one_factory_are_still_a_conflict() -> None:
    """The reload exemption matches on module and qualified name, which two classes
    built by the same factory *share*. A package that generates its check classes in
    a loop would otherwise overwrite itself silently — the exact outcome the refusal
    exists to prevent, arriving through the exemption meant to allow reloads."""
    first, second = _a_check_class("Twin"), _a_check_class("Twin")
    assert first is not second
    assert first.__qualname__ == second.__qualname__

    register(TYPE_NAME)(first)
    with pytest.raises(CheckError):
        register(TYPE_NAME)(second)


def test_registration_sets_the_type_name() -> None:
    cls = register(TYPE_NAME)(_a_check_class("Named"))

    assert cls.type_name == TYPE_NAME
    assert CHECK_TYPES[TYPE_NAME] is cls


def test_require_api_passes_on_the_epoch_this_library_speaks() -> None:
    require_api(API_VERSION)


def test_require_api_refuses_an_older_plugin() -> None:
    with pytest.raises(CheckError) as refusal:
        require_api(API_VERSION - 1, by="little_sister_example")

    message = str(refusal.value)
    assert "little_sister_example" in message
    assert f"v{API_VERSION - 1}" in message and f"v{API_VERSION}" in message
    assert "older than" in message


def test_require_api_refuses_a_plugin_from_the_future() -> None:
    """A library too old for the plugin. The install-time floor should have caught
    this one, so the message points the other way."""
    with pytest.raises(CheckError) as refusal:
        require_api(API_VERSION + 1, by="little_sister_example")

    assert "newer than" in str(refusal.value)


def test_a_refusal_names_the_calling_module_when_nobody_says_who() -> None:
    """The ordinary call site is a bare `require_api(1)` in a package's __init__."""
    with pytest.raises(CheckError) as refusal:
        require_api(API_VERSION + 1)

    assert __name__ in str(refusal.value)


def test_the_roster_reports_where_each_type_came_from() -> None:
    """`/system` answers 'which code is answering for this type name'."""
    roster = {origin.type_name: origin for origin in registered_types()}

    http = roster["http"]
    assert http.builtin
    assert http.module == "little_sister.checks.http"
    assert http.package == "little_sister"
    # Installed as a distribution in any environment that can run this suite.
    assert http.distribution == "little-sister"
    assert http.version
    # The version above is the installed metadata's claim; the path is what is
    # actually loaded, and the two disagreeing is the thing worth seeing.
    assert http.path.endswith("little_sister/checks/http.py")


def test_a_type_from_outside_the_library_is_not_builtin() -> None:
    register(TYPE_NAME)(_a_check_class("Outside"))

    origin = next(o for o in registered_types() if o.type_name == TYPE_NAME)

    assert not origin.builtin
    assert origin.package == __name__.split(".")[0]
