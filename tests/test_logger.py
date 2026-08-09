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
from collections.abc import Iterator

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


def test_with_no_application_setup_the_library_configures_the_default() -> None:
    """The ordinary `./start.sh` case still gets stdout plus the log file — the
    default is only skipped when somebody else got there first."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    root.handlers = []
    try:
        importlib.reload(little_sister.logger)
        kinds = {type(handler) for handler in root.handlers}
        assert logging.FileHandler in kinds
        assert root.level == logging.DEBUG
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)
