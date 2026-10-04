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
import io
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

import little_sister.logger
from little_sister import instants
from tests.running import subprocess_env


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
    """The ordinary `./start.sh` case still gets stderr, and the log file once the
    server's start opens it — the default is only skipped when somebody else got
    there first — and its level is **INFO**: nothing in the library logs below it,
    so a DEBUG root would collect no line of ours and every line of every
    dependency's."""
    as_the_default()
    little_sister.logger.open_log_file()

    root = logging.getLogger()
    kinds = {type(handler) for handler in root.handlers}
    assert logging.FileHandler in kinds
    assert logging.StreamHandler in kinds
    assert root.level == logging.INFO


def test_an_import_opens_no_log_file(as_the_default: Callable[[], None],
                                     log_file: Path) -> None:
    """An import is not an instance (ADR-0091 decision 1): it logs to stderr, and
    creates neither the log file nor the directory it would live in."""
    as_the_default()
    logging.getLogger("little_sister.test").warning("said at the import")

    assert not any(isinstance(handler, logging.FileHandler)
                   for handler in logging.getLogger().handlers)
    assert not log_file.exists()


def test_the_start_opens_the_log_with_what_the_import_logged_first(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    """A run's log still begins with its configuration (ADR-0091 decision 4)."""
    as_the_default()
    said = logging.getLogger("little_sister.test")
    said.info("configuration, first")
    said.info("configuration, second")
    little_sister.logger.open_log_file()
    said.info("after the start")

    lines = log_file.read_text().splitlines()
    assert [line.rsplit(" - ", 1)[1] for line in lines] == [
        "configuration, first", "configuration, second", "after the start"]


def test_what_the_import_logged_past_the_bound_is_counted(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    as_the_default()
    buffer = little_sister.logger._buffer
    assert buffer is not None
    buffer.capacity = 3
    said = logging.getLogger("little_sister.test")
    for number in range(5):
        said.info("line %d", number)
    little_sister.logger.open_log_file()

    text = log_file.read_text()
    assert "line 2" in text and "line 3" not in text
    assert "2 more lines" in text


def test_a_second_start_opens_nothing_more(as_the_default: Callable[[], None],
                                           log_file: Path) -> None:
    as_the_default()
    little_sister.logger.open_log_file()
    little_sister.logger.open_log_file()
    files = [handler for handler in logging.getLogger().handlers
             if isinstance(handler, logging.FileHandler)]
    assert len(files) == 1


def test_an_application_that_configured_logging_gets_no_file_from_the_start(
        application_logging: _Recorder, log_file: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_FILE", str(log_file))
    importlib.reload(little_sister.logger)
    little_sister.logger.open_log_file()

    handlers = logging.getLogger().handlers
    assert application_logging in handlers
    assert not any(isinstance(handler, logging.FileHandler) for handler in handlers)
    assert not log_file.exists()


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
    say which value was not understood, in the log the start opens with what the
    import said — read back from the file, because a warning nobody receives is the
    failure here."""
    monkeypatch.setenv("LOG_LEVEL", "chatty")

    as_the_default()
    little_sister.logger.open_log_file()

    assert logging.getLogger().level == logging.INFO
    assert ("logger: LOG_LEVEL 'chatty' is not a level name; using INFO\n"
            in log_file.read_text())


# --- the stamp (ADR-0120 decision 9) --------------------------------------------

needs_tzset = pytest.mark.skipif(not hasattr(time, "tzset"),
                                 reason="no tzset on this platform")

BERLIN = ZoneInfo("Europe/Berlin")
#: One moment, which a clock in Berlin shows as 13:02:35, one in New York as
#: 07:02:35 and one in Paris as Berlin does.
MOMENT = datetime(2026, 10, 4, 11, 2, 35, 893000, tzinfo=UTC)
#: What the start says where the machine's clock is another, up to its details.
SAID = "- WARNING - logger: this log is stamped in "


@contextmanager
def _machine_in(zone: str) -> Iterator[None]:
    """Run the block on a machine whose own clock is in ``zone``."""
    try:
        with mock.patch.dict(os.environ, {"TZ": zone}):
            time.tzset()
            yield
    finally:
        time.tzset()          # back to whatever the real environment says


@contextmanager
def _said_at(moment: datetime) -> Iterator[None]:
    """Every record made in the block was made at ``moment``."""
    made = logging.getLogRecordFactory()

    def at_that_moment(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = made(*args, **kwargs)
        record.created = moment.timestamp()
        record.msecs = moment.microsecond // 1000
        return record

    logging.setLogRecordFactory(at_that_moment)
    try:
        yield
    finally:
        logging.setLogRecordFactory(made)


@needs_tzset
def test_a_line_is_stamped_in_the_configured_zone_with_its_offset(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    """The stamp keeps its shape and gains the offset, and the zone is the one the
    configuration handed over — whatever zone the machine is in."""
    with _machine_in("America/New_York"):
        as_the_default()
        little_sister.logger.stamp_in(BERLIN)
        little_sister.logger.open_log_file()
        with _said_at(MOMENT):
            logging.getLogger("little_sister.test").info("said")

    assert log_file.read_text().splitlines()[-1] == (
        "2026-10-04 13:02:35,893 +0200 - little_sister.test - INFO - said")


@needs_tzset
def test_the_log_file_is_in_that_zone_from_its_first_line(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    """What the import logged is written when the start opens the file, and is
    stamped then: a line logged before the configuration had read the zone stands
    in the file like every line after it."""
    with _machine_in("America/New_York"), _said_at(MOMENT), \
            mock.patch.object(instants, "now", return_value=MOMENT):
        as_the_default()
        said = logging.getLogger("little_sister.test")
        said.info("before the zone was read")
        little_sister.logger.stamp_in(BERLIN)
        said.info("after it")
        little_sister.logger.open_log_file()
        said.info("after the start")

    lines = log_file.read_text().splitlines()
    assert {line.split(" - ")[0] for line in lines} == {
        "2026-10-04 13:02:35,893 +0200"}
    assert [line.rsplit(" - ", 1)[1] for line in lines if SAID not in line] == [
        "before the zone was read", "after it", "after the start"]


@needs_tzset
def test_on_stderr_a_line_from_before_the_zone_was_read_is_on_the_machines_clock(
        as_the_default: Callable[[], None],
        capsys: pytest.CaptureFixture[str]) -> None:
    """It was written before the zone was known, and it carries its offset like
    every line: the two clocks on stderr are told apart by what follows the stamp."""
    with _machine_in("America/New_York"), _said_at(MOMENT):
        as_the_default()
        said = logging.getLogger("little_sister.test")
        said.info("before the zone was read")
        little_sister.logger.stamp_in(BERLIN)
        said.info("after it")

    assert capsys.readouterr().err.splitlines() == [
        "2026-10-04 07:02:35,893 -0400 - little_sister.test - INFO - "
        "before the zone was read",
        "2026-10-04 13:02:35,893 +0200 - little_sister.test - INFO - after it"]


@needs_tzset
def test_an_application_that_configured_logging_keeps_its_own_stamp(
        application_logging: _Recorder, log_file: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The stamp is the default's, as the file and the level are: a handler the
    application set up formats a record its own way, and the start says nothing
    of clocks in a log that is not the default's."""
    monkeypatch.setenv("LOG_FILE", str(log_file))
    written = io.StringIO()
    theirs = logging.StreamHandler(written)
    theirs.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%H:%M"))
    logging.getLogger().addHandler(theirs)
    with _machine_in("America/New_York"), _said_at(MOMENT):
        importlib.reload(little_sister.logger)
        little_sister.logger.stamp_in(BERLIN)
        little_sister.logger.open_log_file()
        little_sister.logger.logger.warning("a library record")

    assert written.getvalue() == "07:02 | a library record\n"
    assert [record.getMessage() for record in application_logging.records] == [
        "a library record"]


def _started(as_the_default: Callable[[], None], log_file: Path, *, machine: str,
             zone: str | None, now: datetime = MOMENT, starts: int = 1) -> list[str]:
    """What a start says of the two clocks: the default's log on a machine in
    ``machine``, stamped in ``zone`` where the configuration handed one over."""
    with _machine_in(machine), mock.patch.object(instants, "now", return_value=now):
        as_the_default()
        if zone is not None:
            little_sister.logger.stamp_in(ZoneInfo(zone))
        for _ in range(starts):
            little_sister.logger.open_log_file()
    return [line.split(SAID, 1)[1] for line in log_file.read_text().splitlines()
            if SAID in line]


@needs_tzset
def test_the_start_says_once_where_the_machines_clock_is_another(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    said = _started(as_the_default, log_file, machine="America/New_York",
                    zone="Europe/Berlin", starts=2)

    assert said == [
        "Europe/Berlin, the configured timezone, at +0200 now; the machine's clock "
        "is at -0400, so a line stamped on it, as gunicorn's own are, shows another "
        "time for the same moment"]


@needs_tzset
def test_a_machine_whose_clock_agrees_through_the_year_is_told_nothing(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    """The two are compared by what they show, since a process cannot ask its
    machine for its zone's name: Paris and Berlin show the same time all year."""
    assert _started(as_the_default, log_file, machine="Europe/Paris",
                    zone="Europe/Berlin") == []


@needs_tzset
def test_a_machine_on_utc_is_told_from_a_configured_london_in_december(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    """They show the same time on the day of the start and not through the year
    ahead: the line names the day they part."""
    said = _started(as_the_default, log_file, machine="UTC", zone="Europe/London",
                    now=datetime(2026, 12, 1, 12, 0, tzinfo=UTC))

    assert said == [
        "Europe/London, the configured timezone, which shows the machine's time now "
        "and not from 2027-03-28 on, at +0100 against the machine's +0000; a line "
        "stamped on the machine's clock, as gunicorn's own are, shows another time "
        "from then on"]


@needs_tzset
def test_a_year_is_as_far_as_the_start_looks(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    """Asked of a pair of clocks that part once: Moscow kept UTC+4 through every
    season from 2011 and left it for good on 2014-10-26, at 22:00 UTC the day
    before. A start a year and two days before that says nothing, on a machine
    that keeps UTC+4; one a year before says it, and names the day."""
    parted = datetime(2014, 10, 25, 22, 0, tzinfo=UTC)
    assert _started(as_the_default, log_file, machine="Etc/GMT-4",
                    zone="Europe/Moscow", now=parted - timedelta(days=367)) == []
    (said,) = _started(as_the_default, log_file, machine="Etc/GMT-4",
                       zone="Europe/Moscow", now=parted - timedelta(days=365))
    assert "and not from 2014-10-26 on, at +0300 against the machine's +0400" in said


@needs_tzset
def test_nothing_is_said_where_no_zone_was_handed_over(
        as_the_default: Callable[[], None], log_file: Path) -> None:
    """The stamp is then the machine's own clock, and there is nothing to tell
    apart."""
    assert _started(as_the_default, log_file, machine="America/New_York",
                    zone=None) == []


@needs_tzset
def test_an_import_says_nothing_of_the_clocks(
        as_the_default: Callable[[], None],
        capsys: pytest.CaptureFixture[str]) -> None:
    """It is the start that says it (ADR-0091): an import that read a zone the
    machine's clock does not show has opened no log."""
    with _machine_in("America/New_York"):
        as_the_default()
        little_sister.logger.stamp_in(BERLIN)

    assert "this log is stamped" not in capsys.readouterr().err


_STAMPED = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d{3} ([+-]\d{4}) - ")


def _a_start(tmp_path: Path, *, machine: str, zone: str) -> list[str]:
    """The log file of a process of its own that imports the application and
    starts it, on a machine in ``machine`` whose settings name ``zone``."""
    settings, log = tmp_path / "settings.yaml", tmp_path / f"{machine[-5:]}.log"
    settings.write_text(f"timezone: {zone}\n")
    environment = {**subprocess_env(), "TZ": machine, "LOG_FILE": str(log),
                   "LITTLE_SISTER_CONFIG": str(settings),
                   "LITTLE_SISTER_ENGINE": "0", "SECRET_KEY": "test-key"}
    environment.pop("LOG_LEVEL", None)
    done = subprocess.run(
        [sys.executable, "-c", "from little_sister import app; app.start()"],
        env=environment, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return log.read_text().splitlines()


@needs_tzset
def test_a_process_in_another_zone_writes_its_log_in_the_configured_one(
        tmp_path: Path) -> None:
    """The whole of it, in a process of its own: on a machine in New York whose
    settings name Berlin, every line of the log file — what the import logged
    among them — is stamped on Berlin's clock with its offset, and the start says
    once that the machine's clock is another."""
    before = datetime.now(UTC)
    lines = _a_start(tmp_path, machine="America/New_York", zone="Europe/Berlin")
    after = datetime.now(UTC)

    assert any(" - INFO - config: loaded " in line for line in lines), lines
    for line in lines:
        stamp = _STAMPED.match(line)
        assert stamp is not None, line
        written = datetime.strptime(" ".join(stamp.groups()), "%Y-%m-%d %H:%M:%S %z")
        assert written.utcoffset() == written.astimezone(BERLIN).utcoffset(), line
        assert before - timedelta(seconds=1) <= written <= after, line
    assert len([line for line in lines if SAID + "Europe/Berlin" in line]) == 1


@needs_tzset
def test_a_process_whose_machine_agrees_says_nothing_of_it(tmp_path: Path) -> None:
    lines = _a_start(tmp_path, machine="Europe/Paris", zone="Europe/Berlin")

    assert any(" - INFO - config: loaded " in line for line in lines), lines
    assert not [line for line in lines if "this log is stamped" in line]
