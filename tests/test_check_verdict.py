"""A type declares what it grades, and the library grades it (ADR-0131): the check
reads what a deployment wrote of its gradings as it is built and refuses what does
not fit, naming the file; ``Check.verdict`` answers the code a grading gives a value,
with the sentence written for it where it fired and the rule whose keys judged it;
a rule of a block writes the block's gradings; and ``Check.line`` takes a line's code,
its grading and the words ``reason`` and ``rule`` from the verdict it is handed."""
from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from little_sister.checks import (
    CHECK_TYPES,
    Check,
    CheckError,
    Measurement,
    load_checks,
    register,
)
from little_sister.checks.base import CheckResult
from little_sister.grading import Verdict, worst
from little_sister.rules import Axis, RuleList
from little_sister.status import StatusCode

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
HERE = Path(".")
HOUR, DAY = 3600.0, 86400.0

GRADINGS: dict[str, object] = {
    "max_disk": {"sentence": "How full the disk may be.", "kind": "pair",
                 "field": "disk_pct", "unit": "share", "warn": "80%",
                 "error": "90%"},
    "severity_map": {"sentence": "What a finding's severity grades.", "kind": "map",
                     "field": "finding.severity",
                     "words": {"critical": "ERROR", "high": "ERROR",
                               "medium": "WARN", "low": "OK"}},
    "expected_status": {"sentence": "The statuses that pass.", "kind": "set",
                        "field": "status", "accepted": [200]},
    "ec2.max_age": {"sentence": "How long an instance may run.", "kind": "pair",
                    "field": "launched.at", "unit": "duration", "rules": True},
    "ec2.max_per_name": {"sentence": "How many instances one name may carry.",
                         "kind": "pair", "field": "count", "unit": "count",
                         "rules": True},
    "ec2.state_map": {"sentence": "What an instance's state grades.", "kind": "map",
                      "field": "state", "words": {"running": "OK",
                                                  "stopped": "WARN"},
                      "rules": True},
    "lambda.silent": {"sentence": "A function nobody invoked.", "kind": "judgment",
                      "field": "invocations"},
}
FORMS: dict[str, object] = {
    "group": {"sentence": "One name's instances.",
              "text": "{name}: {count}{? — {line.reason}}{? ({line.rule})}"},
}
FIELDS: dict[str, object] = {
    "name": {"sentence": "The instances' name.", "example": "loadtest-7"},
    "count": {"sentence": "How many carry it.", "example": 3},
}


class _Graded(Check):
    """A type that grades through the seam: some of its own keys, and two blocks it
    reads — ``ec2:`` with rules, as ``little-sister-aws`` has, and ``lambda:``."""

    def __init__(self, *, blocks: Mapping[str, Any] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(gradings=GRADINGS, line_forms=FORMS, line_fields=FIELDS,
                         **kwargs)
        blocks = blocks or {}
        ec2 = blocks.get("ec2") or {}
        self.ec2 = self.grading_block("ec2").read(ec2, "ec2")
        self.rules = RuleList(ec2.get("rules"), "ec2",
                              (Axis("name", absent=True, on_rule=True),),
                              grading=self.grading_block("ec2"))
        self.functions = self.grading_block("lambda").read(blocks.get("lambda"),
                                                           "lambda")

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {"blocks": {name: config.get(name) for name in ("ec2", "lambda")}}

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _graded(**config: object) -> _Graded:
    check = _Graded.from_config({"path": "/graded", **config}, HERE)
    assert isinstance(check, _Graded)
    return check


def _loaded(text: str) -> list[Check]:
    """The checks a configuration root holding one file, ``graded.yaml``, loads."""
    saved = dict(CHECK_TYPES)
    try:
        register("graded")(_Graded)
        with tempfile.TemporaryDirectory() as directory:
            checks = Path(directory) / "checks"
            checks.mkdir()
            (checks / "graded.yaml").write_text(text, encoding="utf-8")
            return load_checks(Path(directory))
    finally:
        CHECK_TYPES.clear()
        CHECK_TYPES.update(saved)


# --- the check's own keys, read as it is built --------------------------------------


def test_with_nothing_written_a_grading_grades_with_its_default() -> None:
    check = _graded()
    assert [check.verdict("max_disk", value=pct).code
            for pct in (80, 81, 90, 91)] == [OK, WARN, WARN, ERROR]


def test_the_checks_own_keys_are_read_as_it_is_built_a_pair_whole() -> None:
    check = _graded(max_disk_warn="85%")
    assert check.verdict("max_disk", value=86).code == WARN
    assert check.verdict("max_disk", value=99).code == WARN


def test_a_key_that_does_not_fit_stops_the_start_naming_the_file() -> None:
    with pytest.raises(CheckError, match=r"^graded\.yaml: 'max_disk_warn' must be a "
                                         r"share written with its percent sign, as "
                                         r"80%, not 85$"):
        _loaded("type: graded\npath: /graded\nmax_disk_warn: 85\n")
    [check] = _loaded("type: graded\npath: /graded\nmax_disk_warn: 85%\n")
    assert check.verdict("max_disk", value=86).code == WARN


def test_a_block_its_type_reads_is_refused_naming_the_block() -> None:
    with pytest.raises(CheckError, match=r"^ec2 'max_age_warn': invalid duration: "
                                         r"'soon'$"):
        _graded(ec2={"max_age_warn": "soon"})


# --- what Check.verdict answers -----------------------------------------------------


def test_a_verdict_reads_the_declared_field_of_the_reading() -> None:
    check = _graded()
    reading = Measurement(record={"disk_pct": 95, "finding": {"severity": "HIGH"}})
    assert check.verdict("max_disk", reading) == Verdict("max_disk", ERROR,
                                                         against="90%")
    assert check.verdict("severity_map", reading) == Verdict("severity_map", ERROR)
    assert check.verdict("severity_map", {"finding": {}}).code == WARN
    assert check.verdict("expected_status", {"status": 503}).code == ERROR


def test_a_verdict_says_what_a_value_that_did_not_pass_was_held_against() -> None:
    check = _graded(max_disk_warn="80%", max_disk_error="90%",
                    expected_status=[200, 204])
    assert [check.verdict("max_disk", value=pct).against
            for pct in (80, 81, 91)] == ["", "80%", "90%"]
    assert check.verdict("expected_status", {"status": 503}).against == "200, 204"
    assert check.verdict("expected_status", {"status": 204}).against == ""


def test_what_a_check_grades_by_is_said_as_its_card_writes_it() -> None:
    check = _graded(max_disk_warn="85%", expected_status=[200, 204],
                    ec2={"max_age": None})
    assert check.grading_summary("max_disk") == "warn above 85%"
    assert check.grading_summary("expected_status") == (
        "200, 204; any other → ERROR")
    assert check.grading_summary("ec2.max_age", check.ec2) is None
    with pytest.raises(CheckError, match=r"hand grading_summary\(\) what that block"):
        check.grading_summary("ec2.max_age")


def test_a_grading_is_asked_for_by_the_name_its_type_declares() -> None:
    with pytest.raises(CheckError, match=r"declares no grading 'max_dsk'; its "
                                         r"gradings are max_disk, severity_map, "):
        _graded().verdict("max_dsk", value=1)
    with pytest.raises(CheckError, match=r"hand verdict\(\) the reading, or the value"):
        _graded().verdict("max_disk")


def test_a_grading_in_a_block_is_handed_what_that_block_grades_with() -> None:
    check = _graded()
    with pytest.raises(CheckError, match=r"^'ec2.max_age' is graded in the block "
                                         r"'ec2': hand verdict\(\) what that block "):
        check.verdict("ec2.max_age", value=HOUR)
    with pytest.raises(CheckError, match=r"^'max_disk' is graded in the check's own "
                                         r"keys, and was handed what 'ec2' grade "
                                         r"with$"):
        check.verdict("max_disk", value=1, graded=check.ec2)


def test_the_sentence_rides_a_verdict_that_fired_and_no_other() -> None:
    check = _graded(max_disk_warn="80%", max_disk_reason="Keep room for a dump.")
    assert check.verdict("max_disk", value=81).reason == "Keep room for a dump."
    assert check.verdict("max_disk", value=50).reason == ""


def test_a_rule_writes_a_pair_whole_and_owns_the_line_its_keys_judged() -> None:
    check = _graded(ec2={
        "max_age_warn": "31d", "max_age_error": "40d", "max_age_reason": "Patch it.",
        "max_per_name_warn": 1,
        "rules": [{"name": "load tests", "prefixes": ["loadtest-"],
                   "max_age_warn": "2h"}]})
    rule = check.rules.first(name="loadtest-7")
    assert rule is not None and rule.graded is not None

    def age(seconds: float, by: Any = rule) -> Verdict:
        return check.verdict("ec2.max_age", value=seconds, graded=check.ec2, rule=by)

    assert age(3 * HOUR) == Verdict("ec2.max_age", WARN, "", "load tests", "2h")
    assert age(50 * DAY).code == WARN          # the block's error is not inherited
    assert age(HOUR) == Verdict("ec2.max_age", OK, "", "load tests")
    assert age(41 * DAY, None) == Verdict("ec2.max_age", ERROR, "Patch it.", "",
                                          "40d")
    count = check.verdict("ec2.max_per_name", value=2, graded=check.ec2, rule=rule)
    assert count == Verdict("ec2.max_per_name", WARN, "", "", "1")


def test_a_rule_writes_a_map_word_by_word() -> None:
    check = _graded(ec2={
        "state_map": {"stopped": "ERROR"},
        "rules": [{"name": "dev boxes", "prefixes": ["dev-"],
                   "state_map": {"Stopped": "OK"}}]})
    rule = check.rules.first(name="dev-1")

    def state(word: str, by: Any = rule) -> Verdict:
        return check.verdict("ec2.state_map", value=word, graded=check.ec2, rule=by)

    assert state("stopped") == Verdict("ec2.state_map", OK, "", "dev boxes")
    assert state("running") == Verdict("ec2.state_map", OK, "", "")
    assert state("stopped", None) == Verdict("ec2.state_map", ERROR, "", "")
    assert state("terminated") == Verdict("ec2.state_map", WARN, "", "")


def test_ignore_beside_a_grading_and_a_grading_no_rule_writes_are_refused() -> None:
    with pytest.raises(CheckError, match=r"'ignore' drops what the rule matches, "
                                         r"which then has no line for "
                                         r"'max_age_warn' to say anything on$"):
        _graded(ec2={"rules": [{"name": "gone", "prefixes": ["old-"],
                                "ignore": True, "max_age_warn": "1h"}]})


def test_a_judgment_is_handed_its_code_and_says_its_sentence() -> None:
    check = _graded(**{"lambda": {"silent_reason": "It runs nightly."}})
    verdict = check.verdict("lambda.silent", code=WARN, graded=check.functions)
    assert verdict == Verdict("lambda.silent", WARN, "It runs nightly.", "")
    with pytest.raises(CheckError, match=r"is a judgment .* and is handed its code$"):
        check.verdict("lambda.silent", graded=check.functions)
    with pytest.raises(CheckError, match=r"only a judgment is handed its code$"):
        check.verdict("max_disk", value=1, code=WARN)


# --- what Check.line takes from a verdict -------------------------------------------


def test_a_line_takes_its_code_grading_reason_and_rule_from_its_verdict() -> None:
    check = _graded()
    reading = Measurement(record={"name": "loadtest-7", "count": 3})
    entry = check.line("group", reading, slug="loadtest-7", verdict=Verdict(
        "ec2.max_per_name", WARN, "Too many.", "load tests"))
    assert (entry.text, entry.code, entry.grading, entry.form) == (
        "loadtest-7: 3 — Too many. (load tests)", WARN, "ec2.max_per_name", "group")
    calm = check.line("group", reading, slug="calm",
                      verdict=Verdict("ec2.max_per_name", OK))
    assert (calm.text, calm.code) == ("loadtest-7: 3", OK)
    assert check.line("group", reading, slug="plain").grading == ""


def test_a_pair_that_holds_no_level_names_no_grading() -> None:
    """A pair switched off, or never given a level, compares nothing: its verdict
    names no grading, so the line it decides says no *graded by* — as the check's
    card says *not graded* — while one that holds a level names its own."""
    check = _graded(max_disk=None)
    off = check.verdict("max_disk", value=99)
    assert (off.code, off.grading) == (OK, "")
    reading = Measurement(record={"name": "a", "count": 3})
    assert check.line("group", reading, slug="a", verdict=off).grading == ""
    assert off.entry("disk: 99% used").grading == ""
    unset = check.verdict("ec2.max_age", value=50 * DAY, graded=check.ec2)
    assert (unset.code, unset.grading) == (OK, "")
    assert _graded().verdict("max_disk", value=99).grading == "max_disk"


def test_worst_is_named_by_a_grading_that_graded() -> None:
    age = Verdict("ec2.max_age", OK)
    assert worst(Verdict("", OK), age).grading == "ec2.max_age"
    assert worst(Verdict("", OK), Verdict("", OK)).grading == ""
    assert worst(Verdict("", OK), Verdict("ec2.max_per_name", WARN, "x")) == Verdict(
        "ec2.max_per_name", WARN, "x")


def test_a_code_or_a_verdicts_word_beside_a_verdict_is_refused() -> None:
    check = _graded()
    reading = Measurement(record={"name": "a", "count": 1})
    verdict = Verdict("ec2.max_per_name", WARN)
    with pytest.raises(CheckError, match=r"from its verdict, or from code=, never "):
        check.line("group", reading, slug="a", verdict=verdict, code=WARN)
    with pytest.raises(CheckError, match=r"^the word 'rule' is the verdict's"):
        check.line("group", reading, slug="a", verdict=verdict,
                   words={"rule": "mine"})


def test_a_type_that_grades_through_the_seam_is_handed_reason_and_rule() -> None:
    words = [word.name for word in _graded().line_declarations.words]
    assert words == ["reason", "rule"]

    class _OwnRule(Check):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(gradings=GRADINGS, line_forms=FORMS, line_fields=FIELDS,
                             line_words={"rule": {"sentence": "x.", "example": "y"}},
                             **kwargs)

        def measure(self) -> Sequence[Measurement]:
            return ()

        def grade(self, measurements: Sequence[Measurement],
                  now: datetime) -> CheckResult:
            return CheckResult(StatusCode.OK)

    with pytest.raises(CheckError, match=r"^line_words declares 'rule', which the "
                                         r"library hands a line its verdict decided"):
        _OwnRule.from_config({"path": "/own"}, HERE)


# --- the window, and what may be declared -------------------------------------------


def test_since_on_a_check_that_keeps_nothing_stops_the_start() -> None:
    with pytest.raises(CheckError, match=r"^'max_since_ok' grades what a check keeps "
                                         r"of a subject, and this check keeps "
                                         r"nothing: set series_keep"):
        _graded(max_since_ok_error="26h")
    check = _graded(max_since_ok_error="26h", series_keep=30)
    with pytest.raises(CheckError, match=r"by the library, once a run's readings are "
                                         r"kept; a type asks no verdict of it$"):
        check.verdict("max_since_ok", value=HOUR)


def test_what_the_library_declares_and_two_gradings_under_one_key_are_refused(
) -> None:
    since = {"sentence": "x.", "kind": "since"}
    with pytest.raises(CheckError, match=r"'max_since_ok', which the library "
                                         r"declares on every check$"):
        _Clashing.build({"max_since_ok": since})
    with pytest.raises(CheckError, match=r"^gradings declares 'max_age' and "
                                         r"'max_age_warn', and both are written as "
                                         r"'max_age_warn'$"):
        _Clashing.build({
            "max_age": {"sentence": "x.", "kind": "pair", "field": "age",
                        "unit": "duration"},
            "max_age_warn": {"sentence": "y.", "kind": "set", "field": "age",
                             "accepted": [1]}})


def test_grading_block_names_the_blocks_its_type_has() -> None:
    with pytest.raises(CheckError, match=r"declares no grading in the block 'ec3'; "
                                         r"its blocks are ec2, lambda$"):
        _graded().grading_block("ec3")
    assert "max_age_warn" in _graded().grading_block("ec2").keys


class _Clashing(Check):
    """A type whose declarations the check refuses."""

    declared: Mapping[str, object] = {}

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(gradings=self.declared, **kwargs)

    @classmethod
    def build(cls, declared: Mapping[str, object]) -> Check:
        class _One(cls):  # type: ignore[valid-type,misc]
            pass
        _One.declared = declared
        return _One.from_config({"path": "/clash"}, HERE)

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)
