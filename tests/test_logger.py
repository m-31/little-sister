"""Logging is a default, not a seizure (architecture.md §11, ADR-0049).

A dependent project — a deployment, or a check type in a package of its own — must
be able to run its **own** logging setup and get little-sister's records in it. That
works for free through the standard hierarchy, on one condition: the library must
not reconfigure what the application already configured. These tests hold that
condition, because it is invisible until somebody's log file is silently empty.

The setup is import-time, so each test reloads the module against a root logger it
has arranged, and restores the real one afterwards. Reloading is safe to repeat:
``logging.getLogger`` hands back the same objects, so the module-level ``logger``
every other module already holds does not change identity.
"""
from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import little_sister.logger


class _Recorder(logging.Handler):
    """An application's own handler, standing in for its file or its aggregator."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def application_logging() -> Iterator[_Recorder]:
    """Root as a dependent project would leave it: one handler of its own, its own
    level. Everything is restored, so the suite's own logging is untouched."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    recorder = _Recorder()
    root.handlers = [recorder]
    root.setLevel(logging.WARNING)
    try:
        yield recorder
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    """Where the default's file handler writes during these tests — anywhere but the
    working tree's own `var/little-sister.log`, which a suite has no business
    appending to."""
    return tmp_path / "little-sister.log"


@pytest.fixture
def as_the_default(
        log_file: Path,
        monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], None]]:
    """Import the module the way `./start.sh` does — with root unconfigured, so the
    default is what runs and `LOG_LEVEL` is consulted.

    Emptying root is what the returned callable is *for*: pytest's own capture
    handler joins root once the **test body** starts, so a fixture that cleared the
    handlers during setup would hand the module a configured root and watch it
    correctly skip its default — a test that then proves the opposite of what it
    reads like. `LOG_LEVEL` is cleared here so a developer who exports one for an
    afternoon does not turn these tests red.
    """
    monkeypatch.setenv("LOG_FILE", str(log_file))
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level

    def reload_with_root_unconfigured() -> None:
        root.handlers = []
        importlib.reload(little_sister.logger)

    try:
        yield reload_with_root_unconfigured
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def test_an_application_that_configured_logging_keeps_it(
        application_logging: _Recorder) -> None:
    """No handler added, no level overridden. A `setLevel` outside the guard would
    quietly turn a deployment's INFO logging into DEBUG.

    The comparison is *before against after* rather than against a literal list:
    pytest's own capture handler joins root once the test body starts, and it is no
    more ours than the application's is.
    """
    root = logging.getLogger()
    before = root.handlers[:]
    assert application_logging in before

    importlib.reload(little_sister.logger)

    assert root.handlers == before
    assert root.level == logging.WARNING


def test_little_sisters_own_records_reach_the_application_handler(
        application_logging: _Recorder) -> None:
    """The other half of the promise: propagation is never switched off, so the
    library's records land wherever the application logs."""
    importlib.reload(little_sister.logger)

    little_sister.logger.logger.warning("a library record")

    assert [record.getMessage() for record in application_logging.records] == [
        "a library record"]


def test_a_plugins_own_logger_lands_there_too(
        application_logging: _Recorder) -> None:
    """What a check type in its own package does — `logging.getLogger(__name__)`,
    importing nothing from little-sister."""
    importlib.reload(little_sister.logger)

    logging.getLogger("little_sister_example.checks.example").warning("a plugin record")

    assert [record.name for record in application_logging.records] == [
        "little_sister_example.checks.example"]


def test_with_no_application_setup_the_library_configures_the_default(
        as_the_default: Callable[[], None]) -> None:
    """The ordinary `./start.sh` case still gets stderr plus the log file — the
    default is only skipped when somebody else got there first — and its level is
    **INFO**: nothing in the library logs below it, so a DEBUG root would collect
    no line of ours and every line of every dependency's."""
    as_the_default()

    root = logging.getLogger()
    kinds = {type(handler) for handler in root.handlers}
    assert logging.FileHandler in kinds
    assert root.level == logging.INFO


def test_log_level_names_the_level_of_that_default(
        as_the_default: Callable[[], None],
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The knob the INFO default needs: a deployment debugging a dependency asks
    for the old behavior by name, without owning root logging to get it. Spelled
    in lower case here because an environment variable typed by hand is."""
    monkeypatch.setenv("LOG_LEVEL", "debug")

    as_the_default()

    assert logging.getLogger().level == logging.DEBUG


def test_log_level_does_not_reach_an_application_that_configured_logging(
        application_logging: _Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """The variable is part of the *default*, so it stops where the default does.
    A `setLevel` outside the guard would let a stray `LOG_LEVEL` in a deployment's
    environment silently overrule the level that deployment chose in code — which
    is the same defect as the old unconditional `setLevel`, wearing a knob."""
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    importlib.reload(little_sister.logger)

    assert logging.getLogger().level == logging.WARNING


def test_an_unknown_log_level_falls_back_to_info_and_says_so(
        as_the_default: Callable[[], None], log_file: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A typo in an environment is not a reason to refuse to log. It is a reason to
    say which value was not understood, in the log the default just opened — read
    back from the file, because a warning nobody receives is the failure here."""
    monkeypatch.setenv("LOG_LEVEL", "chatty")

    as_the_default()

    assert logging.getLogger().level == logging.INFO
    assert ("logger: LOG_LEVEL 'chatty' is not a level name; using INFO\n"
            in log_file.read_text())
