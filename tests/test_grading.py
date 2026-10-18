"""What a type grades and how a deployment writes it (ADR-0131), as the grading
module reads and judges it: the declarations, one block of a configuration, a rule
of it, and the code each kind gives a value."""
from __future__ import annotations

import logging

import pytest

from little_sister.errors import CheckError
from little_sister.grading import (
    Accepted,
    Grading,
    GradingBlock,
    GradingError,
    Levels,
    Sentence,
    Verdict,
    Words,
    declare,
    judge,
    worst,
)
from little_sister.reasons import derived_slug
from little_sister.status import StatusCode

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR


def _one(name: str, **entry: object) -> Grading:
    """One grading, declared as a type declares it."""
    [grading] = declare({name: entry})
    return grading


def _pair(name: str = "max_disk", unit: str = "share", **levels: object) -> Grading:
    return _one(name, sentence="How full the disk may be.", kind="pair",
                field="disk_pct", unit=unit, **levels)


def _block(*gradings: Grading, name: str = "") -> GradingBlock:
    return GradingBlock(name, gradings, said_by="/hosts/alpha")


SEVERITY = {"critical": "ERROR", "high": "ERROR", "medium": "WARN", "low": "OK"}


def _map(name: str = "severity_map", words: object = None,
         **entry: object) -> Grading:
    return _one(name, sentence="What a band's severity grades.", kind="map",
                field="severity", words=SEVERITY if words is None else words,
                **entry)


# --- what a type declares -----------------------------------------------------------


def test_a_grading_is_a_key_behind_the_block_it_lives_in() -> None:
    grading = _pair("ec2.max_age", unit="duration")
    assert (grading.block, grading.key) == ("ec2", "max_age")
    assert grading.keys == ("max_age", "max_age_warn", "max_age_error",
                            "max_age_reason")
    assert (_pair().block, _pair().key) == ("", "max_disk")


def test_a_pairs_name_says_which_way_it_grades() -> None:
    with pytest.raises(GradingError, match=r"says which way it grades — max_… "
                                           r"fails above its levels and min_… "
                                           r"below them — and 'disk' does not$"):
        _pair("disk")
    assert _pair("max_disk").most
    assert not _pair("min_repos", unit="count").most


def test_a_default_level_is_read_as_a_deployments_level_is() -> None:
    with pytest.raises(GradingError, match=r"^gradings\.max_disk\.warn must be a "
                                           r"share written with its percent sign, "
                                           r"as 80%, not 80$"):
        _pair(warn=80)
    grading = _pair(warn="80%", error="90%")
    assert (grading.warn, grading.error) == (80.0, 90.0)


@pytest.mark.parametrize(("name", "warn", "error"), [
    ("max_disk", "90%", "80%"), ("max_disk", "90%", "90%"),
    ("min_disk", "10%", "20%"), ("min_disk", "10%", "10%")])
def test_default_levels_in_which_the_warning_could_never_be_said_are_refused(
        name: str, warn: str, error: str) -> None:
    with pytest.raises(GradingError, match=r"or the warning could never be said$"):
        _pair(name, warn=warn, error=error)


def test_a_declaration_takes_what_its_kind_takes() -> None:
    with pytest.raises(GradingError, match=r"does not take 'levels' \(a pair takes "):
        _pair(levels="80%")
    with pytest.raises(GradingError, match=r"^gradings\.max_disk needs 'field'$"):
        _one("max_disk", sentence="How full.", kind="pair", unit="share")
    with pytest.raises(GradingError, match=r"\.kind is one of map, pair, set, "
                                           r"judgment, since, not 'band'$"):
        _one("severity_map", sentence="x.", kind="band", field="severity")


def test_a_maps_words_are_its_vocabulary_with_their_default_codes() -> None:
    grading = _map(words={"critical": "error", "low": "Ok"})
    assert grading.words == (("critical", ERROR), ("low", OK))
    with pytest.raises(GradingError, match=r"\.words\.critical is OK, WARN or ERROR, "
                                           r"not 'MAINTENANCE'$"):
        _map(words={"critical": "MAINTENANCE"})
    with pytest.raises(GradingError, match=r"maps each word of the source's "):
        _map(words={})


def test_a_window_is_a_maximum() -> None:
    with pytest.raises(GradingError, match=r"time since is a maximum"):
        _one("min_since_ok", sentence="x.", kind="since")
    assert _one("max_since_ok", sentence="x.", kind="since").unit == "duration"


def test_a_set_holds_whole_numbers_or_words_and_fails_with_a_code() -> None:
    with pytest.raises(GradingError, match=r"holds whole numbers or words, not both"):
        _one("expected_status", sentence="x.", kind="set", field="status",
             accepted=[200, "ok"])
    with pytest.raises(GradingError, match=r"and OK would grade every value alike$"):
        _one("expected_status", sentence="x.", kind="set", field="status",
             accepted=[200], code="OK")


# --- what one block grades with -----------------------------------------------------


def test_a_block_nothing_is_written_in_grades_with_the_defaults() -> None:
    graded = _block(_pair(warn="80%", error="90%")).read(None)
    assert graded.settings == {"max_disk": Levels(80.0, 90.0)}
    assert graded.written == frozenset()


def test_a_pair_is_written_whole_and_a_level_left_out_is_not_compared() -> None:
    grading = _pair(warn="80%", error="90%")
    graded = _block(grading).read({"max_disk_warn": "85%"})
    assert graded.settings["max_disk"] == Levels(85.0, None)
    assert graded.written == frozenset({"max_disk"})
    assert judge(grading, graded.settings["max_disk"], 99.0) == WARN


def test_null_switches_the_judgment_off() -> None:
    grading = _pair(warn="80%", error="90%")
    graded = _block(grading).read({"max_disk": None})
    assert judge(grading, graded.settings["max_disk"], 100.0) == OK
    assert graded.summary("max_disk", grading) is None


def test_null_beside_a_level_and_a_value_under_the_bare_key_are_refused() -> None:
    block = _block(_pair())
    with pytest.raises(GradingError, match=r"^'max_disk': null switches the judgment "
                                           r"off, so it cannot be written beside "
                                           r"'max_disk_warn'$"):
        block.read({"max_disk": None, "max_disk_warn": "80%"})
    with pytest.raises(GradingError, match=r"^'max_disk' accepts only null, which "
                                           r"switches the judgment off — set a level "
                                           r"with 'max_disk_warn' or "
                                           r"'max_disk_error'$"):
        block.read({"max_disk": "90%"})


def test_a_sentence_without_a_level_could_never_be_said_and_is_refused() -> None:
    with pytest.raises(GradingError, match=r"^ec2 'max_disk_reason' is set but "
                                           r"neither 'max_disk_warn' nor "
                                           r"'max_disk_error' is"):
        _block(_pair()).read({"max_disk_reason": "Room for a dump."}, "ec2")


def test_levels_in_which_the_warning_could_never_be_said_are_refused() -> None:
    with pytest.raises(GradingError, match=r"^'max_disk_error' \(90%\) must be above "
                                           r"'max_disk_warn' \(90%\), or the warning "
                                           r"could never be said$"):
        _block(_pair()).read({"max_disk_warn": "90%", "max_disk_error": "90%"})


@pytest.mark.parametrize(("unit", "written", "read"), [
    ("count", 0, 0.0), ("count", 8, 8.0),
    ("number", 0.8, 0.8), ("number", -5, -5.0),
    ("duration", "26h", 93600.0), ("duration", 90, 90.0),
    ("size", "512 MiB", 512.0 * 1024 ** 2), ("size", "1 GB", 1e9),
    ("amount", 50, 50.0), ("amount", 12.5, 12.5),
    ("share", "80%", 80.0), ("share", " 92.5 % ", 92.5)])
def test_each_unit_reads_a_level_as_written(unit: str, written: object,
                                            read: float) -> None:
    graded = _block(_pair("max_level", unit=unit)).read({"max_level_warn": written})
    assert graded.settings["max_level"] == Levels(read, None)


@pytest.mark.parametrize(("unit", "written", "says"), [
    ("count", "3", "a whole number of 0 or more"),
    ("count", True, "a whole number of 0 or more"),
    ("count", -1, "a whole number of 0 or more"),
    ("number", "0.8", "a number"),
    ("number", float("nan"), "a number"),
    ("duration", "0s", "a duration of at least 1s"),
    ("duration", "5H", "invalid duration"),
    ("size", "500G", "G alone is not a unit"),
    ("amount", -1, "an amount of 0 or more"),
    ("share", 80, "a share written with its percent sign"),
    ("share", "80", "a share written with its percent sign")])
def test_a_level_its_unit_cannot_read_is_refused_naming_the_key(
        unit: str, written: object, says: str) -> None:
    with pytest.raises(CheckError, match=r"^'max_level_warn'") as raised:
        _block(_pair("max_level", unit=unit)).read({"max_level_warn": written})
    assert says in str(raised.value)


def test_a_map_folds_case_and_the_spaces_around_a_word() -> None:
    grading = _map(words={"ALARM": "ERROR", "OK": "OK"})
    graded = _block(grading).read({"severity_map": {" alarm ": "WARN"}})
    words = graded.settings["severity_map"]
    assert judge(grading, words, "ALARM") == WARN
    assert judge(grading, words, "Alarm") == WARN
    assert judge(grading, words, "ok") == OK
    assert judge(grading, words, "  Ok\t") == OK


def test_two_keys_that_fold_to_one_word_are_refused() -> None:
    with pytest.raises(GradingError, match=r"^'severity_map' names 'High' and 'high', "
                                           r"which are one word"):
        _block(_map()).read({"severity_map": {"High": "WARN", "high": "ERROR"}})


def test_a_map_written_changes_the_default_word_by_word() -> None:
    grading = _map()
    graded = _block(grading).read({"severity_map": {"low": "WARN"}})
    words = graded.settings["severity_map"]
    assert [judge(grading, words, word) for word in SEVERITY] == [
        ERROR, ERROR, WARN, WARN]


def test_a_word_no_key_names_grades_warn_so_that_it_is_seen() -> None:
    grading = _map()
    words = _block(grading).read(None).settings["severity_map"]
    assert judge(grading, words, "catastrophic") == WARN
    assert judge(grading, words, None) == WARN


def test_a_key_that_names_no_declared_word_is_said_once_and_grades_as_written(
        caplog: pytest.LogCaptureFixture) -> None:
    grading = _map()
    with caplog.at_level(logging.INFO, logger="little_sister.grading"):
        graded = _block(grading).read(
            {"severity_map": {"urgent": "ERROR", "low": "WARN"}}, "advisories")
    assert [record.getMessage() for record in caplog.records] == [
        "/hosts/alpha: advisories 'severity_map' names 'urgent', which is none of the "
        "words declared for it (critical, high, medium, low); graded as written"]
    assert judge(grading, graded.settings["severity_map"], "Urgent") == ERROR


def test_a_set_reads_one_value_or_a_list_of_the_kind_it_declares() -> None:
    grading = _one("expected_status", sentence="The statuses that pass.",
                   kind="set", field="status", accepted=[200])
    block = _block(grading)
    assert block.read(None).settings["expected_status"] == Accepted((200,))
    assert block.read({"expected_status": 204}).settings[
        "expected_status"] == Accepted((204,))
    assert block.read({"expected_status": ["200", 301]}).settings[
        "expected_status"] == Accepted((200, 301))
    with pytest.raises(GradingError, match=r"holds 'ok', and its values are whole "
                                           r"numbers$"):
        block.read({"expected_status": ["ok"]})
    with pytest.raises(GradingError, match=r"is set but 'expected_status' is not: a "
                                           r"set is written whole"):
        block.read({"expected_status_reason": "Only a 200 is health."})


def test_a_rule_writes_only_what_it_names_and_only_what_a_rule_may_write() -> None:
    ruled = _pair("ec2.max_age", unit="duration", rules=True)
    blocked = _pair("ec2.max_per_name", unit="count")
    block = _block(ruled, blocked, name="ec2")
    graded = block.read_rule({"max_age_warn": "2h"}, "ec2 rules[1] ('load tests')")
    assert graded.settings == {"ec2.max_age": Levels(7200.0, None)}
    assert graded.written == frozenset({"ec2.max_age"})
    with pytest.raises(GradingError, match=r"a rule does not write "
                                           r"'max_per_name_warn'"):
        block.read_rule({"max_per_name_warn": 2}, "ec2 rules[1] ('load tests')")


# --- what a grading says of a value -------------------------------------------------


def test_a_maximum_passes_at_its_level_and_fails_above_it() -> None:
    grading = _pair("max_per_name", unit="count")
    setting = Levels(1.0, 8.0)
    assert [judge(grading, setting, count) for count in (0, 1, 2, 8, 9)] == [
        OK, OK, WARN, WARN, ERROR]


def test_a_minimum_passes_at_its_level_and_fails_below_it() -> None:
    grading = _pair("min_repos", unit="count")
    setting = Levels(20.0, 5.0)
    assert [judge(grading, setting, count) for count in (21, 20, 19, 5, 4)] == [
        OK, OK, WARN, WARN, ERROR]


def test_a_pair_grades_a_number_and_a_judgment_its_code() -> None:
    with pytest.raises(GradingError, match=r"^max_disk grades a number, and was "
                                           r"handed None$"):
        judge(_pair(), Levels(80.0, 90.0), None)
    judged = _one("silent", sentence="Never invoked.", kind="judgment",
                  field="invocations")
    assert judge(judged, Sentence("It runs nightly."), None, WARN) == WARN
    with pytest.raises(GradingError, match=r"is handed its code"):
        judge(judged, Sentence(), None)


def test_worst_takes_the_worse_code_and_every_sentence_that_fired() -> None:
    count = Verdict("ec2.max_per_name", WARN, "One box per name.")
    age = Verdict("ec2.max_age", ERROR, "Patch it.", rule="load tests")
    calm = Verdict("ec2.max_age", OK)
    assert worst(count, age) == Verdict("ec2.max_age", ERROR,
                                        "One box per name. Patch it.", "load tests")
    assert worst(calm, count) == Verdict("ec2.max_per_name", WARN,
                                         "One box per name.", "")
    with pytest.raises(GradingError, match=r"was handed none$"):
        worst()


def test_a_verdicts_line_ends_with_its_sentence_escaped() -> None:
    verdict = Verdict("max_disk", WARN, "Keep *room* for a dump.")
    entry = verdict.entry("91% used")
    assert entry.text == "91% used — Keep \\*room\\* for a dump."
    assert (entry.slug, entry.grading, entry.code) == (
        derived_slug(entry.text), "max_disk", None)
    assert verdict.entry("91% used", slug="disk", coded=True).code == WARN
    assert Verdict("max_disk", OK).entry("50% used").text == "50% used"


def test_a_block_says_what_it_grades_with_as_a_card_writes_it() -> None:
    pair = _pair(warn="80%", error="90%")
    words = _map()
    block = _block(pair, words)
    graded = block.read({"max_disk_warn": "85%"})
    assert graded.summary("max_disk", pair) == "warn above 85%"
    assert block.read(None).summary("max_disk", pair) == (
        "warn above 80%, error above 90%")
    assert graded.summary("severity_map", words) == (
        "critical → ERROR, high → ERROR, medium → WARN, low → OK; any other word "
        "→ WARN")
    assert Words(()).code_of("x") is None
