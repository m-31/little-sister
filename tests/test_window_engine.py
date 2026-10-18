"""The window in the engine (ADR-0131 decisions 7 and 8): once a run is graded, the
engine reads what the check kept of each subject and hands the check that and this
run's reading — each at its own time, and at the code it stands at — and the line the
window writes where it fires stands on the subject's node before the node is stored,
so that its code is the node's too. A check that writes no level of the window is
never judged, and a window that could not be judged is said on the instance's node,
the run's own result standing as it was graded."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import TestCase, mock

from little_sister import self_report
from little_sister.checks import Check, CheckResult, Entry, Measurement, Unit
from little_sister.engine import Engine
from little_sister.series import SeriesKey
from little_sister.status import StatusCode
from little_sister.tree import ReasonLine, StatusTree

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
HERE = Path(".")
START = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


class _Clock:
    """The wall clock a test moves."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


class _Job(Check):
    """A job's last run, read every hour, at the code a test sets — said as a
    sentence of the check's own, on a node that declares its code; or, ``coded``,
    as a line that carries its own."""

    type_name = "job"

    def __init__(self, *, coded: bool = False, **kwargs: Any) -> None:
        super().__init__(subject="the job", **kwargs)
        self.coded = coded
        self.code = OK
        #: The record's own time, where the test gives the run one.
        self.at: datetime | None = None

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {"coded": bool(config.get("coded"))}

    def measure(self) -> Measurement:
        record: dict[str, Any] = {"code": self.code.name}
        if self.at is not None:
            record["at"] = self.at.isoformat()
        return Measurement(record=record)

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        reading = measurements[0]
        code = StatusCode[str(reading.record["code"])]
        if self.coded:
            return CheckResult(reason=[Entry("run", f"the job: {code.name}",
                                             code=code, data=dict(reading.record))])
        return CheckResult(code, [] if code == OK else [f"the job: {code.name}"])


class _Fleet(Check):
    """Services read in one run, each on a node of its own with the line that
    carries its reading — but ``db``, which no line carries, so that it stands
    nowhere."""

    type_name = "fleet"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(subject="the fleet", **kwargs)
        self.codes = {"api": OK, "web": OK, "db": OK}

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {}

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(record={"service": name, "code": code.name},
                            subject=name) for name, code in self.codes.items()]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        children = tuple(
            CheckResult(StatusCode[str(reading.record["code"])],
                        [Entry(f"svc-{reading.subject}",
                               f"{reading.subject}: {reading.record['code']}",
                               subject=reading.subject, data=dict(reading.record))],
                        name=reading.subject)
            for reading in measurements if reading.subject != "db")
        return CheckResult(StatusCode.UNDEFINED, children=children,
                           children_complete=True)


class _Host(_Job):
    """The job read as a host is: one reading, its node a container that grades
    nothing, and the job a child beneath it."""

    type_name = "host"

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.UNDEFINED,
                           children=(_named(super().grade(measurements, now),
                                            "job"),),
                           children_complete=True)


class _Nightly(_Job):
    """The job read as a unit of its own, answering for the node ``nightly`` — or
    raising, ``raises``, as a unit whose reading failed."""

    type_name = "nightly"
    raises = False

    def units(self) -> tuple[Unit, ...]:
        return (Unit("nightly", 3600, "nightly"),)

    def measure_unit(self, key: str) -> Measurement:
        if self.raises:
            raise RuntimeError("the job's log is unreadable")
        return self.measure()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.UNDEFINED,
                           children=(_named(super().grade(measurements, now),
                                            "nightly"),),
                           children_complete=True)


class _Nested(_Nightly):
    """The unit answering for ``jobs/nightly``, beneath a container of its own."""

    type_name = "nested"

    def units(self) -> tuple[Unit, ...]:
        return (Unit("nightly", 3600, "jobs/nightly"),)

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        nightly = _named(_Job.grade(self, measurements, now), "nightly")
        jobs = CheckResult(StatusCode.UNDEFINED, name="jobs", children=(nightly,),
                           children_complete=True)
        return CheckResult(StatusCode.UNDEFINED, children=(jobs,),
                           children_complete=True)


def _named(result: CheckResult, name: str) -> CheckResult:
    """``result`` as the node ``name`` beneath the check's own."""
    return CheckResult(result.code, list(result.reason_entries), name=name)


def _built(cls: type[Check], **config: object) -> Any:
    return cls.from_config({"path": "/job", "series_keep": 48, "frequency": "1h",
                            **config}, HERE)


def _engine(check: Check) -> tuple[Engine, StatusTree, _Clock]:
    tree, clock = StatusTree(), _Clock()
    return Engine([check], tree, wall=clock), tree, clock


def _runs(engine: Engine, clock: _Clock, check: Any, *codes: StatusCode) -> None:
    """One run an hour at each code, the clock moved an hour after each."""
    for code in codes:
        if isinstance(check, _Fleet):
            check.codes["api"] = code
        else:
            check.code = code
        engine.run_once()
        clock.now += HOUR


def _lines(tree: StatusTree, path: str, clock: _Clock) -> tuple[ReasonLine, ...]:
    snapshot = tree.snapshot(path, now=clock.now)
    assert snapshot is not None
    return snapshot.reasons


def _windows(tree: StatusTree, path: str, clock: _Clock) -> list[ReasonLine]:
    return [line for line in _lines(tree, path, clock) if line.slug == "since-ok"]


class TheWindowInTheEngineTests(TestCase):

    def test_it_fires_beyond_its_level_and_raises_the_node(self) -> None:
        check = _built(_Job, max_since_ok_error="26h")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK, *[WARN] * 26)
        self.assertEqual(_windows(tree, "/job", clock), [])
        _runs(engine, clock, check, WARN)
        snapshot = tree.snapshot("/job", now=clock.now)
        assert snapshot is not None
        self.assertEqual(snapshot.own_code, ERROR)
        self.assertEqual(snapshot.reason, ("the job: WARN",
                                           "last stood OK 1d 3h ago (max 26h)"))
        (line,) = _windows(tree, "/job", clock)
        self.assertEqual((line.code, line.grading, line.form, line.subject),
                         (None, "max_since_ok", "since_ok.last", "the job"))

    def test_a_reading_that_stands_ok_ends_it_and_is_kept_as_it_stood(self) -> None:
        check = _built(_Job, max_since_ok_error="26h")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK, *[ERROR] * 27)
        self.assertEqual(len(_windows(tree, "/job", clock)), 1)
        newest = engine.series.window(SeriesKey("job", "/job", "the job"))[-1]
        self.assertEqual((newest.code, newest.texts),
                         (ERROR, ("the job: ERROR",
                                  "last stood OK 1d 3h ago (max 26h)")))
        _runs(engine, clock, check, OK)
        self.assertEqual(_windows(tree, "/job", clock), [])
        self.assertEqual(tree.snapshot("/job", now=clock.now).own_code, OK)

    def test_where_nothing_kept_stood_ok_it_says_how_far_back_it_saw(self) -> None:
        check = _built(_Job, max_since_ok_error="1d")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, *[WARN] * 26)
        (line,) = _windows(tree, "/job", clock)
        self.assertEqual((line.text, line.form),
                         ("no reading kept stood OK, over 1d 1h (max 1d)",
                          "since_ok.none"))

    def test_a_check_that_writes_no_level_of_it_reads_nothing(self) -> None:
        check = _built(_Job)
        engine, tree, clock = _engine(check)
        with mock.patch.object(engine.series, "window",
                               wraps=engine.series.window) as read:
            _runs(engine, clock, check, OK, *[ERROR] * 30)
        read.assert_not_called()
        self.assertEqual(_windows(tree, "/job", clock), [])

    def test_where_the_lines_carry_their_codes_the_windows_does(self) -> None:
        check = _built(_Job, coded=True, max_since_ok_warn="2h",
                       max_since_ok_error="1d")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK, *[WARN] * 3)
        (line,) = _windows(tree, "/job", clock)
        self.assertEqual((line.code, line.text),
                         (WARN, "last stood OK 3h ago (max 2h)"))
        _runs(engine, clock, check, *[WARN] * 22)
        (line,) = _windows(tree, "/job", clock)
        self.assertEqual(line.code, ERROR)
        self.assertEqual(tree.snapshot("/job", now=clock.now).own_code, ERROR)

    def test_each_subject_of_several_is_judged_on_its_own_node(self) -> None:
        check = _built(_Fleet, max_since_ok_error="26h")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK)
        check.codes["web"] = check.codes["db"] = ERROR
        _runs(engine, clock, check, *[WARN] * 27)
        for name in ("api", "web"):
            (line,) = _windows(tree, f"/job/{name}", clock)
            self.assertEqual((line.text, line.subject),
                             ("last stood OK 1d 3h ago (max 26h)", name))
            self.assertEqual(tree.snapshot(f"/job/{name}", now=clock.now).own_code,
                             ERROR)
        # `db` stood nowhere — no line carried it — so no window is judged for it
        self.assertEqual(_windows(tree, "/job", clock), [])

    def test_a_reading_on_a_container_raises_the_container(self) -> None:
        check = _built(_Host, max_since_ok_error="26h")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK, *[WARN] * 27)
        (line,) = _windows(tree, "/job", clock)
        self.assertEqual(line.text, "last stood OK 1d 3h ago (max 26h)")
        self.assertEqual(tree.snapshot("/job", now=clock.now).own_code, ERROR)
        self.assertEqual(_windows(tree, "/job/job", clock), [])

    def test_a_unit_is_judged_on_the_node_it_answers_for(self) -> None:
        check = _built(_Nightly, max_since_ok_error="26h")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK, *[WARN] * 27)
        self.assertEqual(
            [line.text for line in _windows(tree, "/job/nightly", clock)],
            ["last stood OK 1d 3h ago (max 26h)"])
        self.assertEqual(_windows(tree, "/job", clock), [])

    def test_a_unit_whose_reading_failed_is_judged_on_its_failure(self) -> None:
        check = _built(_Nightly, max_since_ok_error="26h")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK)
        check.raises = True
        _runs(engine, clock, check, *[OK] * 27)
        (line,) = _windows(tree, "/job/nightly", clock)
        self.assertEqual(line.text, "last stood OK 1d 3h ago (max 26h)")
        self.assertTrue(any("unreadable" in text for text in tree.snapshot(
            "/job/nightly", now=clock.now).reason))

    def test_each_reading_is_judged_at_its_own_time(self) -> None:
        """The record's own ``at`` where it gives one, as a run's record does:
        a run that stood OK at midnight and was read at eight in the evening is
        twenty-one hours behind one that failed at nine and was read at ten."""
        check = _built(_Job, max_since_ok_error="21h")
        engine, tree, clock = _engine(check)
        clock.now, check.at = START + 20 * HOUR, START
        _runs(engine, clock, check, OK)
        clock.now, check.at = START + 22 * HOUR, START + 21 * HOUR
        _runs(engine, clock, check, ERROR)
        self.assertEqual(_windows(tree, "/job", clock), [])
        check.at = START + 22 * HOUR
        _runs(engine, clock, check, ERROR)
        (line,) = _windows(tree, "/job", clock)
        self.assertEqual(line.text, "last stood OK 22h ago (max 21h)")

    def test_a_unit_deeper_down_is_judged_on_its_own_node(self) -> None:
        check = _built(_Nested, max_since_ok_error="26h")
        engine, tree, clock = _engine(check)
        _runs(engine, clock, check, OK, *[WARN] * 27)
        self.assertEqual(
            [line.text for line in _windows(tree, "/job/jobs/nightly", clock)],
            ["last stood OK 1d 3h ago (max 26h)"])
        self.assertEqual(_windows(tree, "/job/jobs", clock), [])

    def test_a_window_that_could_not_be_judged_is_said_on_the_instances_node(
            self) -> None:
        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)
        check = _built(_Job, max_since_ok_error="1h")
        engine, tree, clock = _engine(check)
        with mock.patch.object(engine.series, "window",
                               side_effect=RuntimeError("the store is gone")):
            _runs(engine, clock, check, OK, *[WARN] * 3)
        snapshot = tree.snapshot("/job", now=clock.now)
        assert snapshot is not None
        self.assertEqual((snapshot.own_code, snapshot.reason),
                         (WARN, ("the job: WARN",)))
        said = [line.text for line in self_report.runtime.lines()]
        self.assertTrue(any(text.startswith(
            "the window of /job could not be judged (RuntimeError('the store is "
            "gone')); its node says this run without it") for text in said), said)

    def test_a_window_judged_for_one_subject_and_not_another_says_neither(
            self) -> None:
        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)
        check = _built(_Fleet, max_since_ok_error="1h")
        engine, tree, clock = _engine(check)
        check.codes["web"] = WARN
        read = engine.series.window

        def window(key: SeriesKey) -> tuple[Any, ...]:
            if key.subject == "web":
                raise RuntimeError("the store is gone")
            return read(key)

        with mock.patch.object(engine.series, "window", side_effect=window):
            _runs(engine, clock, check, OK, *[WARN] * 3)
        self.assertEqual(_windows(tree, "/job/api", clock), [])
        self.assertEqual(_windows(tree, "/job/web", clock), [])
