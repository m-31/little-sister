"""The grading seam held against the family's vocabularies (ADR-0131): verdicts asked
through ``Check.verdict``, over gradings a type could declare for what
``little-sister-aws`` 0.1.6, ``little-sister-github`` 0.1.11 and ``little-sister-wiz``
0.1.3 grade today, from configurations shaped like the ones they read — and compared
with what each of them says today.

None of those packages is a dependency of the library, so what each grades by today is
copied here as it stands in that release (the ``_today_*`` functions and
``_Threshold``), each reading the configuration in its own spelling, and the seam reads
the same values in the one spelling of decision 2. The gradings are this suite's and
not those packages': each declares its own when it adopts, in a release of its own.
What the comparison holds is the design: that ``little-sister-aws``'s pairs and the
rules that write them, its two maps and its minimum, ``little-sister-github``'s four
maps and its minimum, and ``little-sister-wiz``'s band map give through the one seam
the code each gives today — and the sentence, and the rule that owns the line — for
every value a grid of them reaches. Where decision 4 folds a map's words, every value
is handed as its source spells it, and a deployment's key in another case is read the
way the package reads it today.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest

from little_sister.checks import Check, Measurement, parse_duration
from little_sister.checks.base import CheckResult
from little_sister.grading import Graded, Verdict, worst
from little_sister.rules import Axis, Rule, RuleList
from little_sister.status import StatusCode

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
HERE = Path(".")
HOUR, DAY = 3600, 86400


def _declared(entries: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    return {name: {"sentence": f"What {name} grades.", **entry}
            for name, entry in entries.items()}


class _Shaped(Check):
    """A check of a type declaring ``GRADINGS``, reading each block it names — and a
    rule list for each block named in ``RULED`` — as a package's type would."""

    GRADINGS: ClassVar[Mapping[str, object]] = {}
    BLOCKS: ClassVar[tuple[str, ...]] = ()
    RULED: ClassVar[Mapping[str, Axis]] = {}

    def __init__(self, *, blocks: Mapping[str, Any] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(gradings=self.GRADINGS, **kwargs)
        blocks = blocks or {}
        self.graded: dict[str, Graded] = {
            name: self.grading_block(name).read(blocks.get(name), name)
            for name in self.BLOCKS}
        self.rules: dict[str, RuleList[None]] = {
            name: RuleList((blocks.get(name) or {}).get("rules"), name, (axis,),
                           grading=self.grading_block(name))
            for name, axis in self.RULED.items()}

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        return {"blocks": {name: config.get(name) for name in cls.BLOCKS}}

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


# --- little-sister-aws 0.1.6: pairs, rules, two maps and a minimum ------------------


@dataclass(frozen=True)
class _Threshold:
    """``little_sister_aws._rules.Threshold``, as it stands."""

    warn: float | None = None
    error: float | None = None
    reason: str = ""

    def code_for(self, value: float) -> StatusCode:
        if self.error is not None and value > self.error:
            return ERROR
        if self.warn is not None and value > self.warn:
            return WARN
        return OK


def _today_pair(block: Mapping[str, Any], name: str,
                kind: str) -> _Threshold | None:
    """``parse_pair``, as it stands, for the counts and the durations read here:
    ``None`` where the block writes none of the pair's keys, the ungraded pair where
    ``name: null`` switches it off, and the pair as written otherwise."""
    keys = {name, f"{name}_warn", f"{name}_error", f"{name}_reason"}
    if not any(key in block for key in keys):
        return None
    if name in block:
        return _Threshold()

    def level(key: str) -> float | None:
        value = block.get(key)
        if value is None:
            return None
        return parse_duration(value, 0) if kind == "duration" else value

    return _Threshold(level(f"{name}_warn"), level(f"{name}_error"),
                      str(block.get(f"{name}_reason") or "").strip())


def _today_resolved(rule: Mapping[str, Any] | None, block: Mapping[str, Any],
                    name: str, kind: str,
                    default: _Threshold | None = None) -> _Threshold:
    """``resolved``, as it stands: the rule's pair whole where it wrote one, else the
    block's — which takes the one default pair as written where it writes it."""
    own = None if rule is None else _today_pair(rule, name, kind)
    if own is not None:
        return own
    top = _today_pair(block, name, kind)
    return top if top is not None else (default or _Threshold())


#: ``DEFAULT_STATE_MAP``, ``DEFAULT_PIPELINE_STATE_MAP``, as they stand.
_TODAY_ALARM_STATES = {"ALARM": ERROR, "INSUFFICIENT_DATA": WARN, "OK": OK}
_TODAY_PIPELINE_STATES = {"succeeded": OK, "inprogress": OK, "failed": ERROR,
                          "stopped": ERROR, "stopping": ERROR, "cancelled": ERROR,
                          "superseded": ERROR}


def _today_alarm_state(block: Mapping[str, Any], state: str) -> StatusCode:
    """``CloudWatchSettings.code_for``: the keys uppercased over the defaults, and
    a state looked up uppercased, WARN where none is mapped."""
    state_map = dict(_TODAY_ALARM_STATES)
    state_map.update({str(key).upper(): StatusCode[str(code).upper()]
                      for key, code in (block.get("state_map") or {}).items()})
    return state_map.get(state.upper(), WARN)


def _today_pipeline_status(block: Mapping[str, Any], status: str) -> StatusCode:
    """``PipelineSettings.code_for``: the keys stripped and lowercased over the
    defaults, a status looked up the same way, WARN where none is mapped."""
    state_map = dict(_TODAY_PIPELINE_STATES)
    state_map.update({str(key).strip().lower(): StatusCode[str(code).upper()]
                      for key, code in (block.get("state_map") or {}).items()})
    return state_map.get(status.strip().lower(), WARN)


def _today_alarms_counted(minimum: int, counted: int) -> StatusCode:
    """``_coverage``'s two verdicts: none counted, or fewer than the minimum, warn."""
    return WARN if not counted or counted < minimum else OK


class _Aws(_Shaped):
    GRADINGS = _declared({
        "ec2.max_per_name": {"kind": "pair", "field": "count", "unit": "count",
                             "rules": True},
        "ec2.max_age": {"kind": "pair", "field": "launched.at", "unit": "duration",
                        "rules": True},
        "codepipeline.max_age": {"kind": "pair", "field": "succeeded.at",
                                 "unit": "duration", "rules": True},
        "codepipeline.max_run_time": {"kind": "pair", "field": "running.started",
                                      "unit": "duration", "warn": "30m",
                                      "rules": True},
        "codepipeline.state_map": {
            "kind": "map", "field": "status", "rules": True,
            "words": {"Succeeded": "OK", "InProgress": "OK", "Failed": "ERROR",
                      "Stopped": "ERROR", "Stopping": "ERROR",
                      "Cancelled": "ERROR", "Superseded": "ERROR"}},
        "cloudwatch.state_map": {
            "kind": "map", "field": "state",
            "words": {"ALARM": "ERROR", "INSUFFICIENT_DATA": "WARN", "OK": "OK"}},
        "cloudwatch.min_alarms": {"kind": "pair", "field": "alarms",
                                  "unit": "count", "warn": 1},
    })
    BLOCKS = ("ec2", "codepipeline", "cloudwatch")
    RULED: ClassVar[Mapping[str, Axis]] = {
        "ec2": Axis("name", absent=True, on_rule=True),
        "codepipeline": Axis("name", on_rule=True)}


#: An `ec2:` block shaped like the package's annotated example, its rules among them.
EC2: dict[str, Any] = {
    "max_per_name_warn": 1, "max_per_name_error": 8,
    "max_per_name_reason": "A second box under this name is usually a deploy that "
                           "did not clean up.",
    "max_age_warn": "31d", "max_age_error": "40d",
    "max_age_reason": "The instance is too old to have the latest patch levels.",
    "rules": [
        {"name": "scratch", "prefixes": ["tmp-", "scratch-"], "ignore": True},
        {"name": "load tests", "prefixes": ["loadtest-"], "max_per_name_warn": 15,
         "max_age_warn": "2h", "max_age_error": "4h",
         "max_age_reason": "A load test nobody tore down is the expensive kind of "
                           "leftover."},
        {"name": "grafana", "prefixes": ["grafana-"], "max_per_name_warn": 1,
         "max_per_name_error": 2,
         "max_per_name_reason": "A second one can come from an autostart."},
        {"name": "the single-volume boxes", "names": ["db-primary"],
         "max_per_name_error": 1,
         "max_per_name_reason": "This name owns a single block device.",
         "max_age": None},
        {"name": "unnamed instances", "unnamed": True, "max_per_name_error": 1,
         "max_per_name_reason": "An instance with no Name tag belongs to nobody."},
        {"name": "the build agents", "prefixes": ["jenkins-agent"],
         "max_per_name_error": 6},
    ],
}

#: A `codepipeline:` block shaped like the example: a staleness clock, the one pair
#: with a default re-set, and rules that loosen, switch off and leave alone.
PIPELINES: dict[str, Any] = {
    "max_age_warn": "31d", "max_age_error": "90d",
    "max_age_reason": "Nobody has released through this pipeline in months.",
    "max_run_time_warn": "30m", "max_run_time_error": "4h",
    "max_run_time_reason": "A deployment here takes ten minutes.",
    "state_map": {"InProgress": "WARN", "superseded": "OK"},
    "rules": [
        {"name": "sandboxes", "prefixes": ["sandbox-"]},
        {"name": "nightly builds", "prefixes": ["nightly-"], "max_age_warn": "36h"},
        {"name": "release pipelines", "prefixes": ["release-"], "max_age": None,
         "max_run_time": None},
    ],
}

ALARMS: dict[str, Any] = {"state_map": {"insufficient_data": "OK"}}


def _aws(ec2: Mapping[str, Any] = EC2, pipelines: Mapping[str, Any] = PIPELINES,
         alarms: Mapping[str, Any] = ALARMS) -> _Aws:
    check = _Aws.from_config({"path": "/aws", "ec2": ec2, "codepipeline": pipelines,
                              "cloudwatch": alarms}, HERE)
    assert isinstance(check, _Aws)
    return check


def _raw(block: Mapping[str, Any], rule: Rule[None] | None) -> Mapping[str, Any] | None:
    """The rule as the configuration wrote it, for today's reader to read."""
    if rule is None:
        return None
    return next(item for item in block["rules"] if item["name"] == rule.name)


def _today(threshold: _Threshold, value: float, owner: str) -> Verdict:
    """What the package says of a value, in the seam's terms: the code, the sentence
    where the judgment fired, and the rule where the rule wrote the pair."""
    code = threshold.code_for(value)
    return Verdict("", code, threshold.reason if code != OK else "", owner)


EC2_NAMES = ("web-1", "loadtest-7", "grafana-main", "db-primary", None,
             "jenkins-agent-3")


@pytest.mark.parametrize("name", EC2_NAMES)
def test_aws_ec2_pairs_and_rules_grade_through_the_seam_as_today(
        name: str | None) -> None:
    check = _aws()
    rule = check.rules["ec2"].first(name=name)
    raw = _raw(EC2, rule)
    graded = check.graded["ec2"]
    for pair, kind, values in (
            ("max_per_name", "count", range(13)),
            ("max_age", "duration",
             (HOUR, 2 * HOUR, 2 * HOUR + 1, 5 * HOUR, 31 * DAY, 31 * DAY + 1,
              40 * DAY, 41 * DAY))):
        threshold = _today_resolved(raw, EC2, pair, kind)
        owner = rule.name if rule is not None and raw is not None and _today_pair(
            raw, pair, kind) is not None else ""
        for value in values:
            seam = check.verdict(f"ec2.{pair}", value=value, graded=graded, rule=rule)
            # named where the pair holds a level, and where it holds none it decided
            # nothing and names nothing
            holds = threshold.warn is not None or threshold.error is not None
            assert seam.grading == (f"ec2.{pair}" if holds else "")
            assert _fields(seam) == _fields(_today(threshold, value, owner)), (
                name, pair, value)


def _fields(verdict: Verdict) -> tuple[StatusCode, str, str]:
    return verdict.code, verdict.reason, verdict.rule


def test_aws_an_ignored_name_never_reaches_a_grading() -> None:
    rule = _aws().rules["ec2"].first(name="tmp-runner")
    assert rule is not None and rule.ignore and rule.graded is None


def test_aws_two_judgments_on_one_line_take_the_worse_and_both_sentences() -> None:
    check = _aws()
    graded = check.graded["ec2"]
    count = check.verdict("ec2.max_per_name", value=3, graded=graded)
    age = check.verdict("ec2.max_age", value=41 * DAY, graded=graded)
    line = worst(count, age)
    assert (line.code, line.grading) == (ERROR, "ec2.max_age")
    assert line.reason == (
        "A second box under this name is usually a deploy that did not clean up. "
        "The instance is too old to have the latest patch levels.")


@pytest.mark.parametrize("name", ("deploy-shop", "sandbox-1", "nightly-tests",
                                  "release-shop"))
def test_aws_pipeline_pairs_and_rules_grade_through_the_seam_as_today(
        name: str) -> None:
    check = _aws()
    rule = check.rules["codepipeline"].first(name=name)
    raw = _raw(PIPELINES, rule)
    graded = check.graded["codepipeline"]
    for pair, default, values in (
            ("max_age", None,
             (HOUR, 36 * HOUR, 36 * HOUR + 1, 31 * DAY, 31 * DAY + 1, 91 * DAY)),
            ("max_run_time", _Threshold(warn=1800),
             (60, 1800, 1801, 4 * HOUR, 4 * HOUR + 1, DAY))):
        threshold = _today_resolved(raw, PIPELINES, pair, "duration", default)
        owner = rule.name if rule is not None and raw is not None and _today_pair(
            raw, pair, "duration") is not None else ""
        for value in values:
            seam = check.verdict(f"codepipeline.{pair}", value=value, graded=graded,
                                 rule=rule)
            assert _fields(seam) == _fields(_today(threshold, value, owner)), (
                name, pair, value)


def test_aws_the_one_default_pair_is_taken_as_written() -> None:
    """A block that writes no ``max_run_time`` keeps the type's default — thirty
    minutes, warning — and one that writes a level takes the pair as written."""
    bare = _aws(pipelines={})
    graded = bare.graded["codepipeline"]
    assert [bare.verdict("codepipeline.max_run_time", value=value,
                         graded=graded).code for value in (1800, 1801, DAY)] == [
        OK, WARN, WARN]
    errors_only = _aws(pipelines={"max_run_time_error": "1h"})
    graded = errors_only.graded["codepipeline"]
    assert [errors_only.verdict("codepipeline.max_run_time", value=value,
                                graded=graded).code
            for value in (1801, HOUR + 1)] == [OK, ERROR]
    assert _today_resolved(None, {"max_run_time_error": "1h"}, "max_run_time",
                           "duration", _Threshold(warn=1800)).code_for(1801) == OK


@pytest.mark.parametrize("status", ("Succeeded", "InProgress", "Failed", "Stopped",
                                    "Stopping", "Cancelled", "Superseded",
                                    "Abandoned"))
def test_aws_a_pipelines_status_map_grades_through_the_seam_as_today(
        status: str) -> None:
    check = _aws()
    seam = check.verdict("codepipeline.state_map", value=status,
                         graded=check.graded["codepipeline"])
    assert seam.code == _today_pipeline_status(PIPELINES, status)


@pytest.mark.parametrize("state", ("ALARM", "INSUFFICIENT_DATA", "OK",
                                   "SOMETHING_NEW"))
def test_aws_an_alarms_state_map_grades_through_the_seam_as_today(
        state: str) -> None:
    check = _aws()
    seam = check.verdict("cloudwatch.state_map", value=state,
                         graded=check.graded["cloudwatch"])
    assert seam.code == _today_alarm_state(ALARMS, state)


@pytest.mark.parametrize("minimum", (1, 3))
def test_aws_expect_min_alarms_is_a_minimum_that_means_what_it_meant(
        minimum: int) -> None:
    check = _aws(alarms={"min_alarms_warn": minimum})
    graded = check.graded["cloudwatch"]
    for counted in range(8):
        seam = check.verdict("cloudwatch.min_alarms", value=counted, graded=graded)
        assert seam.code == _today_alarms_counted(minimum, counted), counted


# --- little-sister-github 0.1.11: four maps and a minimum ---------------------------

#: The four maps' defaults, as they stand.
_TODAY_GITHUB_MAPS: dict[str, dict[str, StatusCode]] = {
    "security_advisories": {"critical": ERROR, "high": ERROR, "medium": WARN,
                            "low": WARN},
    "code_scanning_security": {"critical": ERROR, "high": ERROR, "medium": ERROR,
                               "low": ERROR},
    "code_scanning_quality": {"error": WARN, "warning": WARN, "note": OK},
    "actions": {"disabled_manually": WARN, "disabled_inactivity": WARN,
                "disabled_fork": OK},
}


def _today_github(block: str, written: Mapping[str, Any], word: str | None
                  ) -> StatusCode:
    """``_severity_map`` merged over its default, the keys lowercased, and a word
    looked up as GitHub sends it, WARN where none is mapped."""
    merged = dict(_TODAY_GITHUB_MAPS[block])
    merged.update({str(key).lower(): StatusCode[str(code).upper()]
                   for key, code in written.items()})
    return merged.get(word, WARN)  # type: ignore[arg-type]


def _key(block: str) -> str:
    return "disabled_severity_map" if block == "actions" else "severity_map"


class _Github(_Shaped):
    GRADINGS = _declared({
        **{f"{block}.{_key(block)}": {
            "kind": "map", "field": "severity",
            "words": {word: code.name for word, code in words.items()},
            **({"rules": True} if block == "actions" else {})}
           for block, words in _TODAY_GITHUB_MAPS.items()},
        "min_repos": {"kind": "pair", "field": "repositories", "unit": "count",
                      "warn": 1},
    })
    BLOCKS = tuple(_TODAY_GITHUB_MAPS)
    RULED: ClassVar[Mapping[str, Axis]] = {"actions": Axis("repositories")}


#: Blocks shaped like a deployment's, each map re-grading a band, one key in capitals.
GITHUB: dict[str, Any] = {
    "security_advisories": {"severity_map": {"LOW": "OK"}},
    "code_scanning_security": {},
    "code_scanning_quality": {"severity_map": {"error": "ERROR"}},
    "actions": {"disabled_severity_map": {"disabled_inactivity": "OK"},
                "rules": [{"name": "watched forks", "repositories": ["shop"],
                           "disabled_severity_map": {"disabled_fork": "WARN"}}]},
}


@pytest.mark.parametrize("block", tuple(_TODAY_GITHUB_MAPS))
def test_github_maps_grade_through_the_seam_as_today(block: str) -> None:
    check = _Github.from_config({"path": "/github", **GITHUB}, HERE)
    assert isinstance(check, _Github)
    written = GITHUB[block].get(_key(block)) or {}
    for word in (*_TODAY_GITHUB_MAPS[block], "a_word_github_adds", None):
        seam = check.verdict(f"{block}.{_key(block)}", value=word,
                             graded=check.graded[block])
        assert seam.code == _today_github(block, written, word), word


def test_github_a_rule_of_actions_writes_its_map_word_by_word() -> None:
    """What ``actions.rules:`` gains at no cost of its own (decision 6): a rule that
    re-grades a switched-off fork in the repositories it names, and leaves every other
    state the block's."""
    check = _Github.from_config({"path": "/github", **GITHUB}, HERE)
    assert isinstance(check, _Github)
    rule = check.rules["actions"].first(repositories="shop")
    graded = check.graded["actions"]

    def state(word: str, by: Rule[None] | None) -> Verdict:
        return check.verdict("actions.disabled_severity_map", value=word,
                             graded=graded, rule=by)

    assert _fields(state("disabled_fork", rule)) == (WARN, "", "watched forks")
    assert _fields(state("disabled_inactivity", rule)) == (OK, "", "")
    assert _fields(state("disabled_fork", None)) == (OK, "", "")


@pytest.mark.parametrize("minimum", (1, 20))
def test_github_expect_min_repos_is_a_minimum_that_means_what_it_meant(
        minimum: int) -> None:
    """``expect_min_repos: 20`` is ``min_repos_warn: 20``: what was in scope passes at
    the number and warns below it. None in scope is the type's own judgment, and
    stays so."""
    check = _Github.from_config({"path": "/github", "min_repos_warn": minimum}, HERE)
    for count in range(1, 31):
        today = OK if count >= minimum else WARN
        assert check.verdict("min_repos", value=count).code == today, count


# --- little-sister-wiz 0.1.3: the band map ------------------------------------------

#: ``DEFAULT_SEVERITY_MAP``, as it stands.
_TODAY_WIZ_BANDS = {"critical": ERROR, "high": ERROR, "medium": ERROR, "low": WARN,
                    "informational": OK}


def _today_wiz(written: Mapping[str, Any], severity: str | None) -> StatusCode:
    """The keys lowercased over the default, a band named as ``_band`` names it —
    WIZ's severity lowercased, ``unknown`` where it sent none — WARN where the map
    names no such band."""
    merged = dict(_TODAY_WIZ_BANDS)
    merged.update({str(key).lower(): StatusCode[str(code).upper()]
                   for key, code in written.items()})
    band = str(severity or "unknown").lower()
    mapped = merged.get(band)
    return WARN if mapped is None else mapped


class _Wiz(_Shaped):
    GRADINGS = _declared({
        "severity_map": {"kind": "map", "field": "severity",
                         "words": {band: code.name
                                   for band, code in _TODAY_WIZ_BANDS.items()}},
    })


@pytest.mark.parametrize("written", (
    {}, {"medium": "WARN", "informational": "WARN"}, {"HIGH": "WARN"}))
def test_wiz_the_band_map_grades_through_the_seam_as_today(
        written: Mapping[str, Any]) -> None:
    check = _Wiz.from_config({"path": "/wiz", "severity_map": dict(written)}, HERE)
    for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL",
                     "SEVERE", None):
        seam = check.verdict("severity_map", value=severity)
        assert seam.code == _today_wiz(written, severity), severity
