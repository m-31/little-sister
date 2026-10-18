"""The window (ADR-0131 decisions 7 and 8): ``max_since_ok``, which the library
declares on every check, grades how long before a reading its subject last stood OK,
over the readings the check keeps up to and including that one, handed to the check
rather than read from the store; where it fires it writes a line of its own from one
of the library's two forms, which a deployment re-words in the check's ``display:``
block as it re-words a type's. A level the readings kept can never reach is said in
the log as the check is built."""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from little_sister.checks import Check, CheckError, CheckResult, Measurement
from little_sister.checks.file import FileFreshnessCheck
from little_sister.grading import since_ok
from little_sister.status import StatusCode

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
HERE = Path(".")
AT = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
Kept = list[tuple[datetime, StatusCode | None]]


class _Kept(Check):
    """A type that declares no grading and no form of its own, as many do: the window
    is the library's, on every check."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(subject="the export", **kwargs)

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {}

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(OK)


class _Formed(_Kept):
    """A type with a form of its own, beside which the library's are re-worded."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(line_forms={"export.done": {
            "sentence": "An export that finished.", "text": "exported"}}, **kwargs)


class _Clashing(_Kept):
    """A type whose form takes a name the library writes the window's line from."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(line_forms={"since_ok.last": {
            "sentence": "Its own.", "text": "quiet"}}, **kwargs)


def _kept(cls: type[_Kept] = _Kept, **config: object) -> _Kept:
    check = cls.from_config({"path": "/export", "series_keep": 48, "frequency": "1h",
                             **config}, HERE)
    assert isinstance(check, _Kept)
    return check


def _hourly(*codes: StatusCode | None) -> Kept:
    """Readings an hour apart, oldest first, the last of them taken at ``AT``."""
    return [(AT - (len(codes) - 1 - at) * HOUR, code) for at, code in enumerate(codes)]


def _said(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [message for message in caplog.messages if "'max_since_ok'" in message]


# --- the time since, a pure function of what it is handed ---------------------------


def test_since_is_the_time_from_the_newest_reading_kept_that_stood_ok() -> None:
    assert since_ok(AT, _hourly(OK, ERROR, OK, WARN, ERROR)) == (2 * 3600.0, True)
    assert since_ok(AT, _hourly(ERROR, OK)) == (0.0, True)


def test_where_no_reading_kept_stood_ok_since_reaches_back_to_the_oldest() -> None:
    assert since_ok(AT, _hourly(ERROR, WARN, None, ERROR)) == (3 * 3600.0, False)


def test_a_reading_after_the_one_graded_is_not_its_window_nor_is_order_read() -> None:
    later: Kept = [(AT + HOUR, OK)]
    assert since_ok(AT, [*later, *reversed(_hourly(OK, ERROR, ERROR))]) == (
        2 * 3600.0, True)
    assert since_ok(AT, later) == (0.0, False)
    assert since_ok(AT, []) == (0.0, False)


# --- the line it writes, from the library's forms ------------------------------------


def test_a_check_that_writes_no_level_of_its_window_says_nothing_of_it() -> None:
    long_quiet = _hourly(OK, *[ERROR] * 40)
    assert _kept().window_line(AT, long_quiet) is None
    assert _kept(max_since_ok=None).window_line(AT, long_quiet) is None
    switched_off = _Kept.from_config({"path": "/export", "max_since_ok": None}, HERE)
    assert switched_off.window_line(AT, long_quiet) is None


def test_the_window_passes_at_its_level_and_fires_beyond_it() -> None:
    check = _kept(max_since_ok_error="26h")
    assert check.window_line(AT, _hourly(OK, *[ERROR] * 26)) is None
    line = check.window_line(
        AT, [(AT - timedelta(hours=26, seconds=1), OK), (AT, ERROR)])
    assert line is not None
    assert (line.slug, line.code, line.grading, line.form, line.subject, line.data) == (
        "since-ok", ERROR, "max_since_ok", "since_ok.last", "the export", None)
    assert line.text == "last stood OK 1d 2h ago (max 26h)"
    handed = check.window_line(AT, _hourly(OK, *[ERROR] * 27), subject="the archive")
    assert handed is not None and handed.subject == "the archive"


def test_each_level_says_itself_and_the_sentence_written_for_the_window() -> None:
    check = _kept(max_since_ok_warn="12h", max_since_ok_error="1d",
                  max_since_ok_reason="The export runs *nightly*.")
    warned = check.window_line(AT, _hourly(OK, *[ERROR] * 13))
    assert warned is not None and warned.code == WARN
    assert warned.text == (
        "last stood OK 13h ago (max 12h) — The export runs \\*nightly\\*.")
    failed = check.window_line(AT, _hourly(OK, *[ERROR] * 25))
    assert failed is not None and failed.code == ERROR
    assert failed.text == (
        "last stood OK 1d 1h ago (max 1d) — The export runs \\*nightly\\*.")


def test_where_nothing_kept_stood_ok_the_line_says_how_far_back_it_saw() -> None:
    check = _kept(max_since_ok_error="1d")
    line = check.window_line(AT, _hourly(*[ERROR] * 30))
    assert line is not None and (line.form, line.code) == ("since_ok.none", ERROR)
    assert line.text == "no reading kept stood OK, over 1d 5h (max 1d)"
    assert check.window_line(AT, _hourly(*[ERROR] * 24)) is None


def test_a_deployment_re_words_the_window_in_its_display_block() -> None:
    check = _kept(_Formed, max_since_ok_error="1d", max_since_ok_reason="Nightly.",
                  display={
                      "export.done": "done",
                      "since_ok.last": "quiet for {line.since}, over {line.level}"
                                       "{? ({line.reason})}",
                      "since_ok.none": "{line.default}; see the runbook"})
    last = check.window_line(AT, _hourly(OK, *[ERROR] * 25))
    assert last is not None and last.text == "quiet for 1d 1h, over 1d (Nightly.)"
    none = check.window_line(AT, _hourly(*[ERROR] * 30))
    assert none is not None and none.text == (
        "no reading kept stood OK, over 1d 5h (max 1d) — Nightly.; see the runbook")


def test_every_check_takes_the_window_a_library_type_too() -> None:
    check = FileFreshnessCheck.from_config({
        "path": "/heartbeat", "file": "/var/heartbeat", "series_keep": 48,
        "max_since_ok_error": "1d",
        "display": {"since_ok.last": "no fresh file for {line.since}"}}, HERE)
    line = check.window_line(AT, _hourly(OK, *[ERROR] * 25))
    assert line is not None and line.text == "no fresh file for 1d 1h"
    assert line.subject == "/var/heartbeat"


def test_a_template_of_the_window_names_no_field_and_no_type_takes_its_names(
) -> None:
    with pytest.raises(CheckError, match=r"^display\.since_ok\.last names the field "
                                         r"'completed\.url'"):
        _kept(max_since_ok_error="1d", display={"since_ok.last": "{completed.url}"})
    with pytest.raises(CheckError, match=r"^line_forms declares 'since_ok\.last', "
                                         r"which the library writes the window's line "
                                         r"from on every check: a type's form takes "
                                         r"another name$"):
        _kept(_Clashing)


def test_a_name_that_is_no_form_of_the_check_is_refused_naming_both_kinds() -> None:
    with pytest.raises(CheckError, match=r"^display re-words 'since_ok\.lst', and "
                                         r"this type declares no form for a template "
                                         r"to re-word; the library's, on every "
                                         r"check, are since_ok\.last, since_ok\.none$"):
        _kept(display={"since_ok.lst": "quiet"})
    with pytest.raises(CheckError, match=r"^display re-words 'export\.dne', which is "
                                         r"no form of this type; its forms are "
                                         r"export\.done; the library's, on every "
                                         r"check, are since_ok\.last"):
        _kept(_Formed, display={"export.dne": "done"})


# --- what the readings kept can reach ------------------------------------------------


def test_a_level_the_readings_kept_never_reach_is_said_as_the_check_is_built(
        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="little_sister.checks.base")
    _kept(series_keep=24, max_since_ok_warn="12h", max_since_ok_error="26h")
    assert _said(caplog) == [
        "/export: 'max_since_ok' asks about 26h, and the 24 readings this check "
        "keeps, one every 1h, reach back 23h at most: that level is never gone past"]
    caplog.clear()
    _kept(series_keep=27, max_since_ok_error="26h")
    assert len(_said(caplog)) == 1
    caplog.clear()
    _kept(series_keep=28, max_since_ok_error="26h")
    _kept(series_keep=1)
    assert _said(caplog) == []
    _kept(series_keep=1, max_since_ok_warn="2h")
    assert _said(caplog) == [
        "/export: 'max_since_ok' asks about 2h, and the one reading this check keeps "
        "is the one graded: no level of it is ever gone past"]


def test_a_level_on_a_check_that_keeps_nothing_stops_the_start() -> None:
    with pytest.raises(CheckError, match=r"^'max_since_ok' grades what a check keeps "
                                         r"of a subject, and this check keeps "
                                         r"nothing: set series_keep"):
        _Kept.from_config({"path": "/export", "max_since_ok_warn": "1d"}, HERE)
