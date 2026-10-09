"""Noise caps a package declares, and ``LOG_LEVEL`` by name (ADR-0121).

The rules of the record's decisions 2 to 5 were run against a prototype before a
line of this was built, and its scenarios are the first tests here: each is named
after the sentence it runs, and runs it against **real** `logging` loggers, since
what a level does is `logging`'s to say and not a table's. ``written`` is what a
handler without a level on the root receives, which is what the default's handlers
are.

A :class:`World` is one process as far as its levels go — what ``LOG_LEVEL`` says,
whether the default is in charge, and the rows — played in the order a deployment
starts in: the default is installed (:func:`start`), packages declare and the code
of the import-before-app slot sets what it sets, and the application's import sets
the rows (``settle``).
"""
from __future__ import annotations

import html
import itertools
import logging
import os
import random
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType
from typing import Any

import pytest

from little_sister import logger as default
from little_sister import noise, self_report
from little_sister.logger import Entries, above, level_on
from little_sister.noise import Caps
from little_sister.status import StatusCode
from tests.running import subprocess_env


class _Written(logging.Handler):
    """A handler without a level on the root: every line that is written."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"{record.name}:{record.levelname}")


def _loggers() -> list[logging.Logger]:
    return [standing for standing in logging.Logger.manager.loggerDict.values()
            if isinstance(standing, logging.Logger)]


def _reset() -> None:
    """No logger carries a level, as in a process before anything set one."""
    for standing in _loggers():
        standing.setLevel(logging.NOTSET)


@pytest.fixture(autouse=True)
def written() -> Iterator[list[str]]:
    """Every test starts where no logger carries a level and leaves every level
    as it found it, the root's included. It yields the lines written while the
    test ran, each as ``name:LEVEL``."""
    root = logging.getLogger()
    saved = {standing: standing.level for standing in _loggers()}
    saved_root = root.level
    _reset()
    handler = _Written()
    root.addHandler(handler)
    try:
        yield handler.lines
    finally:
        root.removeHandler(handler)
        _reset()
        for standing, level in saved.items():
            standing.setLevel(level)
        root.setLevel(saved_root)


@dataclass
class World:
    """One process, as far as its log levels go."""
    entries: Entries
    in_charge: bool
    caps: Caps = field(default_factory=Caps)
    refused: list[str] = field(default_factory=list)

    def cap(self, logger: object, level: object, *, hides: object = "x",
            package: str = "p") -> None:
        """A package's declaration; what was refused is kept, as a sentence."""
        refused = self.caps.declare(logger, level, hides=hides, package=package)
        if refused is not None:
            self.refused.append(refused)

    def settle(self) -> None:
        """The application's import."""
        self.caps.settle(in_charge=self.in_charge, entries=self.entries)

    @property
    def rows(self) -> list[tuple[str, str]]:
        return [(row.logger, row.package) for row in self.caps.rows()]

    @property
    def outcome(self) -> dict[str, str]:
        """What became of each logger a row names: ``set``, or why not."""
        return {verdict.logger: verdict.reason or "set"
                for verdict in self.caps.verdicts()}

    @property
    def taken_off(self) -> list[tuple[str, str, str]]:
        return [(taken.logger, taken.level_name, taken.entry)
                for taken in self.entries.taken_off]

    @property
    def unreadable(self) -> list[str]:
        return [skipped.entry for skipped in self.entries.unreadable]


def start(env: str = "", *, in_charge: bool = True) -> World:
    """A process up to its first import of the library: ``LOG_LEVEL`` read, and
    the default's levels set where the application configured no logging."""
    entries = Entries.read(env)
    if in_charge:
        default._set_levels(entries)
    return World(entries, in_charge)


def aws(world: World, level: int = logging.WARNING,
        name: str = "botocore.credentials",
        package: str = "little_sister_aws") -> None:
    """What a package that brings the AWS SDK declares."""
    world.cap(name, level, hides="x", package=package)


def code(name: str, level: int) -> None:
    """A level the code of the slot sets, or a dependency itself; ``""`` is the
    root."""
    logging.getLogger(name).setLevel(level)


def eff(name: str) -> str:
    """The level the logger is at, its own or the nearest above it."""
    return str(logging.getLevelName(logging.getLogger(name).getEffectiveLevel()))


def own(name: str) -> str:
    """The level that stands on the logger itself; ``""`` is the root."""
    level = level_on(name) if name else logging.getLogger().level
    return str(logging.getLevelName(level))


APPLICATION = "the application configured logging itself"


def named(entry: str) -> str:
    return f"LOG_LEVEL names {entry}"


def chosen(logger: str, level: str) -> str:
    return (f"{logger} is at {level}, set by the application's code or by the "
            f"dependency itself")


def no_line(level: str, through: str = "the root") -> str:
    return (f"it would take no line away — without it the logger is at {level} "
            f"already, through {through}")


# --- decision 2: a package declares a cap, and sets no level --------------------

def test_a_declaration_records_a_row_and_touches_no_logger() -> None:
    world = start()
    world.cap("sdk_never_seen.credentials", logging.WARNING, package="pkg")
    assert world.rows == [("sdk_never_seen.credentials", "pkg")]
    assert "sdk_never_seen.credentials" not in logging.Logger.manager.loggerDict
    world.settle()
    assert own("sdk_never_seen.credentials") == "WARNING"
    assert eff("sdk_never_seen") == "INFO"
    assert world.outcome == {"sdk_never_seen.credentials": "set"}


# --- decision 3: what a package may declare is bounded ---------------------------

@pytest.mark.parametrize(("logger", "said"), [
    ("", "'', which names no logger "),
    (" ", "' ', which names no logger "),
    (".", "'.', which names no logger "),
    ("a..b", "'a..b', which names no logger "),
    ("botocore.", "'botocore.', which names no logger "),
    (None, "None, which names no logger "),
    (7, "7, which names no logger "),
    ("root", "the root logger — "),
    ("little_sister", "little_sister, the library's own logger — "),
    ("little_sister.logger", "little_sister.logger, the library's own logger — "),
])
def test_a_cap_names_a_dependencys_logger(logger: object, said: str) -> None:
    """Never the root, and never ``little_sister`` or a logger beneath it."""
    world = start("DEBUG")
    world.cap(logger, logging.WARNING)
    assert not world.rows
    (refused,) = world.refused
    assert refused.startswith(f"p declares a noise cap on {said}")
    world.settle()
    assert world.outcome == {} and eff("little_sister.logger") == "DEBUG"
    assert own("") == "DEBUG"


def test_a_package_of_another_name_is_not_the_librarys_own() -> None:
    world = start("DEBUG")
    world.cap("little_sister_aws.keeper", logging.WARNING)
    world.cap("little_sisterly", logging.INFO)
    assert world.refused == []
    world.settle()
    assert own("little_sister_aws.keeper") == "WARNING"
    assert own("little_sisterly") == "INFO"


@pytest.mark.parametrize(("level", "shown"), [
    (logging.ERROR, "ERROR"), (logging.CRITICAL, "CRITICAL"),
    (logging.DEBUG, "DEBUG"), (logging.NOTSET, "NOTSET"), (25, "Level 25"),
    (30.0, "30.0"), (True, "True"), ("WARNING", "'WARNING'"), (None, "None"),
])
def test_a_cap_is_at_info_or_warning_by_loggings_constant(level: object,
                                                          shown: str) -> None:
    world = start()
    world.cap("dep", level)
    assert not world.rows
    (refused,) = world.refused
    assert refused.startswith(f"p declares a noise cap on dep at {shown} — ")
    world.settle()
    assert eff("dep") == "INFO"


@pytest.mark.parametrize("level", [logging.INFO, logging.WARNING])
def test_info_and_warning_are_the_two_a_package_may_declare(level: int) -> None:
    world = start("DEBUG")
    world.cap("dep", level)
    world.settle()
    assert world.refused == [] and level_on("dep") == level


@pytest.mark.parametrize("hides", ["", " ", " \n\t", None, 3])
def test_a_cap_says_what_it_hides(hides: object) -> None:
    world = start("DEBUG")
    world.cap("dep", logging.WARNING, hides=hides)
    assert not world.rows
    (refused,) = world.refused
    assert refused.startswith(
        "p declares a noise cap on dep and does not say what it hides")
    world.settle()
    assert eff("dep") == "DEBUG"


def test_a_sentence_wrapped_in_its_source_is_one_line() -> None:
    world = start()
    world.cap(" dep ", logging.WARNING,
              hides="  where each new session\n      found its credentials ")
    (row,) = world.caps.rows()
    assert (row.logger, row.hides) == (
        "dep", "where each new session found its credentials")


def test_a_refused_declaration_leaves_the_row_before_it() -> None:
    world = start()
    aws(world)
    world.cap("botocore.credentials", logging.ERROR, package="little_sister_aws")
    world.settle()
    assert own("botocore.credentials") == "WARNING" and len(world.refused) == 1


def test_a_declaration_after_the_application_was_imported_is_refused() -> None:
    world = start()
    world.settle()
    aws(world)
    assert own("botocore.credentials") == "NOTSET" and not world.rows
    (refused,) = world.refused
    assert refused.startswith(
        "little_sister_aws declares a noise cap on botocore.credentials after "
        "the application was imported — ")


def test_unless_it_repeats_a_row_as_it_stands() -> None:
    world = start()
    aws(world)
    world.settle()
    aws(world)                                    # the module, imported again
    assert world.refused == [] and own("botocore.credentials") == "WARNING"
    aws(world, level=logging.INFO)                # the same row, changed
    aws(world, package="another")                 # the same row, another's
    world.cap("botocore.credentials", logging.WARNING, hides="other words",
              package="little_sister_aws")        # the same row, said otherwise
    world.cap("botocore.credentials", 30.0, package="little_sister_aws")
    assert len(world.refused) == 4 and own("botocore.credentials") == "WARNING"
    assert world.rows == [("botocore.credentials", "little_sister_aws")]


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_where_two_rows_name_one_logger_the_higher_level_stands(
        order: tuple[str, str]) -> None:
    """Whichever was declared first — and both are named."""
    world = start()
    levels = {"a": logging.WARNING, "b": logging.INFO}
    for package in order:
        world.cap("dep", levels[package], package=package)
    world.settle()
    assert own("dep") == "WARNING"
    (verdict,) = world.caps.verdicts()
    assert verdict.capped and verdict.level == logging.WARNING
    assert [(row.package, row.level_name) for row in verdict.rows] == [
        ("a", "WARNING"), ("b", "INFO")]


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_a_row_beneath_a_higher_row_brings_no_line_back(
        order: tuple[str, str], written: list[str]) -> None:
    world = start()
    declare: dict[str, Callable[[], None]] = {
        "a": lambda: world.cap("botocore", logging.WARNING, package="a"),
        "b": lambda: world.cap("botocore.credentials", logging.INFO, package="b")}
    for package in order:
        declare[package]()
    world.settle()
    logging.getLogger("botocore.credentials").info("Found credentials")
    assert written == [] and own("botocore.credentials") == "NOTSET"
    assert world.outcome["botocore.credentials"] == no_line(
        "WARNING", "the cap on botocore")


def test_three_packages_on_three_names_in_every_order() -> None:
    declarations = [("dep", logging.INFO, "a"), ("dep.x", logging.WARNING, "b"),
                    ("dep.x.y", logging.INFO, "c")]
    seen = set()
    for order in itertools.permutations(declarations):
        _reset()
        world = start("DEBUG")
        for name, level, package in order:
            world.cap(name, level, package=package)
        world.settle()
        seen.add((own("dep"), own("dep.x"), own("dep.x.y"), eff("dep.x.y")))
    assert seen == {("INFO", "WARNING", "NOTSET", "WARNING")}


def test_a_row_above_a_lower_row_leaves_it_set() -> None:
    world = start()
    world.cap("botocore", logging.INFO, package="little_sister_aws")
    aws(world)
    world.settle()
    assert own("botocore") == "NOTSET"            # the root is at INFO already
    assert own("botocore.credentials") == "WARNING"
    _reset()
    world = start("DEBUG")                        # and under a DEBUG root both are set
    world.cap("botocore", logging.INFO, package="little_sister_aws")
    aws(world)
    world.settle()
    assert own("botocore") == "INFO" and own("botocore.credentials") == "WARNING"
    assert set(world.outcome.values()) == {"set"}


def test_a_row_sees_the_nearest_row_above_it() -> None:
    """The rows are judged from the top of the names down, so that the fourth
    reason sees the rows above — and what a logger is at without its own row is
    the nearest level above it, not the first one a name was capped at."""
    world = start("DEBUG")
    world.cap("dep", logging.INFO, package="a")
    world.cap("dep.x", logging.WARNING, package="b")
    world.cap("dep.x.y", logging.WARNING, package="c")
    world.settle()
    assert (own("dep"), own("dep.x"), own("dep.x.y")) == (
        "INFO", "WARNING", "NOTSET")
    assert world.outcome["dep.x.y"] == no_line("WARNING", "the cap on dep.x")


def test_the_same_package_declaring_again_replaces_its_row() -> None:
    world = start("DEBUG")
    world.cap("dep", logging.WARNING, package="a")
    world.cap("dep", logging.INFO, package="a")
    assert len(world.rows) == 1
    world.settle()
    assert own("dep") == "INFO"


# --- decision 4: the rows are set once, where the application is imported ------

def test_a_cap_takes_lines_away_and_adds_none(written: list[str]) -> None:
    world = start("ERROR")
    aws(world)
    world.settle()
    logging.getLogger("botocore.credentials").warning("refresh failed")
    logging.getLogger("botocore.endpoint").warning("a sibling's")
    assert written == [] and eff("botocore.credentials") == "ERROR"
    assert world.outcome["botocore.credentials"] == no_line("ERROR")


def test_the_librarys_own_row_adds_none_under_a_higher_root(
        written: list[str]) -> None:
    world = start("WARNING")
    world.cap("markdown_it", logging.INFO, package="little_sister")
    world.settle()
    logging.getLogger("markdown_it").info("an INFO line")
    assert written == [] and own("markdown_it") == "NOTSET"


def test_the_order_of_a_deployments_imports_decides_nothing() -> None:
    world = start()
    code("botocore.credentials", logging.DEBUG)
    aws(world)
    world.settle()
    first = eff("botocore.credentials")
    _reset()
    world = start()
    aws(world)
    code("botocore.credentials", logging.DEBUG)
    world.settle()
    assert first == eff("botocore.credentials") == "DEBUG"
    assert world.outcome["botocore.credentials"] == chosen(
        "botocore.credentials", "DEBUG")


@pytest.mark.parametrize("code_first", [True, False])
def test_a_level_on_a_logger_above_speaks_for_the_one_beneath(
        code_first: bool) -> None:
    world = start()
    if code_first:
        code("botocore", logging.DEBUG)
        aws(world)
    else:
        aws(world)
        code("botocore", logging.DEBUG)
    world.settle()
    assert eff("botocore.credentials") == "DEBUG"
    assert world.outcome["botocore.credentials"] == chosen("botocore", "DEBUG")


def test_a_deployment_that_capped_in_the_slot_keeps_its_levels() -> None:
    world = start()
    code("botocore", logging.WARNING)
    code("urllib3", logging.WARNING)
    aws(world)
    world.settle()
    assert eff("botocore.credentials") == "WARNING"
    assert own("botocore.credentials") == "NOTSET"
    assert own("botocore") == "WARNING" and own("urllib3") == "WARNING"


def test_a_dependency_that_sets_its_own_level_reads_as_a_choice() -> None:
    code("dep", logging.INFO)                     # the dependency, at its import
    world = start("DEBUG")
    world.cap("dep", logging.WARNING)
    world.settle()
    assert own("dep") == "INFO" and world.outcome["dep"] == chosen("dep", "INFO")


def test_the_application_configured_logging_itself() -> None:
    """No level is the library's to set then, and the variable does nothing."""
    logging.getLogger().setLevel(logging.ERROR)
    code("dep.sub", logging.DEBUG)
    world = start("DEBUG,dep=WARNING", in_charge=False)
    aws(world)
    world.settle()
    assert own("") == "ERROR" and own("dep") == "NOTSET"
    assert own("dep.sub") == "DEBUG"
    assert own("botocore.credentials") == "NOTSET" and world.taken_off == []
    assert world.outcome["botocore.credentials"] == APPLICATION


def test_the_first_reason_that_holds_is_the_one_given() -> None:
    world = start("INFO,botocore=WARNING")
    aws(world)
    code("botocore.credentials", logging.DEBUG)   # a choice, beneath an entry
    world.settle()
    assert world.outcome["botocore.credentials"] == named("botocore")
    _reset()
    world = start("ERROR")
    aws(world)
    code("botocore", logging.CRITICAL)
    world.settle()
    assert world.outcome["botocore.credentials"] == chosen("botocore", "CRITICAL")
    _reset()
    logging.getLogger().setLevel(logging.ERROR)
    world = start("INFO,botocore=WARNING", in_charge=False)
    aws(world)
    world.settle()
    assert world.outcome["botocore.credentials"] == APPLICATION


def test_what_code_sets_after_the_import_it_sets(written: list[str]) -> None:
    # on a logger above a row it does not reach the row, lower ...
    world = start()
    aws(world)
    world.settle()
    code("botocore", logging.DEBUG)
    assert eff("botocore.credentials") == "WARNING"
    # ... or higher, where the row's logger then writes a line its siblings do not
    code("botocore", logging.ERROR)
    logging.getLogger("botocore.credentials").warning("x")
    logging.getLogger("botocore.endpoint").warning("x")
    assert written == ["botocore.credentials:WARNING"]
    # and on a logger the variable names it is the later word
    _reset()
    world = start("INFO,botocore.credentials=DEBUG")
    aws(world)
    world.settle()
    code("botocore.credentials", logging.WARNING)
    assert eff("botocore.credentials") == "WARNING"


def test_the_rows_are_set_once() -> None:
    """A second call does nothing: no row is judged again, and no level the code
    set since is taken off."""
    world = start("INFO,botocore=WARNING")
    world.cap("dep", logging.WARNING)
    world.settle()
    before = world.caps.verdicts()
    code("dep", logging.DEBUG)
    code("botocore.credentials", logging.DEBUG)
    world.settle()
    assert own("dep") == "DEBUG" and own("botocore.credentials") == "DEBUG"
    assert world.caps.verdicts() == before and world.taken_off == []


def test_judging_a_row_makes_no_logger() -> None:
    """Neither the row's own, where it is not set, nor one above it."""
    world = start("ERROR")
    world.cap("sdk_unmade.auth.tokens", logging.WARNING)
    world.settle()
    assert world.outcome == {"sdk_unmade.auth.tokens": no_line("ERROR")}
    made = logging.Logger.manager.loggerDict
    assert not {"sdk_unmade", "sdk_unmade.auth", "sdk_unmade.auth.tokens"} & set(made)
    assert level_on("sdk_unmade.auth") == logging.NOTSET
    assert "sdk_unmade.auth" not in made


# --- decision 5: LOG_LEVEL names loggers beside the level -----------------------

def test_log_level_names_a_logger() -> None:
    world = start("INFO,botocore.credentials=DEBUG")
    aws(world)
    assert eff("botocore.credentials") == "DEBUG"          # with the default
    world.settle()
    assert eff("botocore.credentials") == "DEBUG" and eff("botocore") == "INFO"
    assert world.outcome["botocore.credentials"] == named("botocore.credentials")


def test_an_entry_speaks_for_every_name_beneath_it() -> None:
    world = start("INFO,botocore=DEBUG")
    aws(world)
    world.settle()
    assert eff("botocore.credentials") == "DEBUG"
    assert world.outcome["botocore.credentials"] == named("botocore")


def test_a_level_standing_beneath_an_entry_is_taken_off_with_the_default(
        written: list[str]) -> None:
    code("botocore.credentials", logging.WARNING)          # a dependency, before us
    world = start("INFO,botocore=DEBUG")
    logging.getLogger("botocore.credentials").debug("Looking for credentials")
    assert written == ["botocore.credentials:DEBUG"]       # from the first line
    assert world.taken_off == [("botocore.credentials", "WARNING", "botocore")]


def test_and_again_where_the_rows_are_set(written: list[str]) -> None:
    world = start("INFO,botocore=DEBUG")
    aws(world)
    code("botocore.credentials", logging.WARNING)          # the code of the slot
    logging.getLogger("botocore.credentials").debug("in the slot")
    assert written == []                                   # in the slot the later
    world.settle()                                         # `setLevel` stands
    logging.getLogger("botocore.credentials").debug("at a run")
    assert written == ["botocore.credentials:DEBUG"]
    assert own("botocore.credentials") == "NOTSET"
    assert world.taken_off == [("botocore.credentials", "WARNING", "botocore")]


def test_in_the_slot_the_later_setlevel_stands_over_an_entry_until_then() -> None:
    world = start("INFO,botocore.credentials=DEBUG")
    code("botocore.credentials", logging.WARNING)
    assert eff("botocore.credentials") == "WARNING"
    world.settle()
    assert eff("botocore.credentials") == "DEBUG"


def test_down_to_the_next_name_the_variable_has_an_entry_for() -> None:
    world = start("INFO,botocore=DEBUG,botocore.credentials=WARNING")
    aws(world)
    code("botocore.auth", logging.ERROR)
    code("botocore.credentials.x", logging.DEBUG)
    world.settle()
    assert eff("botocore") == "DEBUG" and own("botocore.credentials") == "WARNING"
    assert own("botocore.auth") == "NOTSET"
    assert eff("botocore.credentials.x") == "WARNING"


def test_a_name_that_only_begins_alike_is_not_beneath() -> None:
    world = start("INFO,botocore=DEBUG")
    code("botocorex.y", logging.ERROR)
    world.cap("botocorex", logging.WARNING)
    world.settle()
    assert own("botocorex.y") == "ERROR" and own("botocorex") == "WARNING"
    assert above("botocorex.y") == ["botocorex"]


def test_the_variable_stands_over_the_code_of_the_slot() -> None:
    world = start("INFO,botocore=DEBUG")
    aws(world)
    code("botocore", logging.WARNING)             # after the default, in the slot
    world.settle()
    assert own("botocore") == "DEBUG" and eff("botocore.credentials") == "DEBUG"


def test_the_bare_level_is_set_once_with_the_default() -> None:
    world = start("DEBUG,dep=DEBUG")
    code("", logging.INFO)                        # the code of the slot
    code("dep", logging.WARNING)
    world.settle()
    assert own("") == "INFO" and own("dep") == "DEBUG"


def test_a_named_entry_may_name_the_librarys_own_and_carry_any_level() -> None:
    start("INFO,little_sister=ERROR,dep=CRITICAL")
    assert eff("little_sister.logger") == "ERROR" and own("dep") == "CRITICAL"


def test_a_bare_debug_lowers_the_root_and_lifts_no_cap() -> None:
    world = start("DEBUG")
    aws(world)
    world.settle()
    assert eff("urllib3") == "DEBUG" and eff("botocore.credentials") == "WARNING"


def test_the_root_has_no_name_in_the_variable() -> None:
    world = start("INFO,root=DEBUG")
    aws(world)
    world.settle()
    assert own("") == "INFO" and world.unreadable == ["root=DEBUG"]
    assert eff("botocore.credentials") == "WARNING"        # and no cap was lifted


def test_notset_names_no_level() -> None:
    code("dep", logging.ERROR)
    world = start("NOTSET,dep=NOTSET,other=notset")
    world.settle()
    assert world.unreadable == ["NOTSET", "dep=NOTSET", "other=notset"]
    assert own("") == "INFO" and own("dep") == "ERROR"


def test_a_later_entry_replaces_an_earlier_one_the_bare_level_too() -> None:
    world = start("DEBUG,dep=ERROR,INFO,dep=WARNING")
    world.settle()
    assert own("dep") == "WARNING" and own("") == "INFO"


def test_a_level_is_written_by_its_name_in_logging_in_either_case() -> None:
    world = start("warning,Dep=debug, other = Error ,,third=WARN")
    world.settle()
    assert own("") == "WARNING" and own("Dep") == "DEBUG"
    assert own("other") == "ERROR" and own("third") == "WARNING"
    assert own("dep") == "NOTSET" and world.unreadable == []   # a name keeps its case


def test_an_entry_that_cannot_be_read_is_skipped_and_the_rest_stands() -> None:
    world = start("INFO,dep=LOUD,=DEBUG,dep.sub=,a=b=DEBUG,chatty,dep2=10,"
                  "urllib3=ERROR")
    world.settle()
    assert [(skipped.entry, skipped.why) for skipped in world.entries.unreadable] == [
        ("dep=LOUD", "'LOUD' is not a level name"),
        ("=DEBUG", "it names no logger"),
        ("dep.sub=", "it names no level"),
        ("a=b=DEBUG", "'b=DEBUG' is not a level name"),
        ("chatty", "'chatty' is not a level name"),
        ("dep2=10", "'10' is not a level name")]
    assert own("urllib3") == "ERROR" and own("dep") == "NOTSET"
    assert own("") == "INFO" and own("a") == "NOTSET"


def test_with_no_bare_level_that_can_be_read_the_root_is_at_info() -> None:
    world = start("chatty,dep=DEBUG")
    world.settle()
    assert own("") == "INFO" and own("dep") == "DEBUG"


# --- five properties the record claims, over random small worlds ----------------

NAMES = ["a", "a.b", "a.b.c", "a.x", "d", "d.e"]
ANY = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR]
ROWS = [logging.INFO, logging.WARNING]


def _play(env: str, code_sets: list[tuple[str, int]],
          order: list[tuple[str, int, str]], early: set[tuple[str, int]], *,
          with_rows: bool = True) -> tuple[dict[str, int], World]:
    """One world in one order: each level of the slot's code before or after the
    declarations, the declarations as shuffled."""
    _reset()
    world = start(env)
    for name, level in code_sets:
        if (name, level) in early:
            code(name, level)
    if with_rows:
        for name, level, package in order:
            world.cap(name, level, package=package)
    for name, level in code_sets:
        if (name, level) not in early:
            code(name, level)
    world.settle()
    return ({name: logging.getLogger(name).getEffectiveLevel() for name in NAMES},
            world)


def test_five_properties_hold_over_random_worlds() -> None:
    """A world is a ``LOG_LEVEL``, some levels the code of the slot sets, and some
    rows from several packages; each is played in several orders.

    1. The order decides nothing: every order of one world ends at the same levels.
    2. A cap takes lines away and adds none: no logger ends lower than without the
       rows.
    3. The variable is read by itself: a logger at or beneath an entry ends at the
       level of the nearest entry at or above it.
    4. A choice stands: at or beneath a level the slot's code set, where no entry
       speaks, a logger ends where it would without the rows.
    5. Every cap holds: where neither an entry nor a choice speaks, a logger with a
       row at or above it ends at the highest such row, or at the root's level
       where that is higher.
    """
    rng = random.Random(121)
    verdicts = {"set": 0, "not set": 0}
    for _ in range(1500):
        entries = {name: rng.choice(ANY)
                   for name in rng.sample(NAMES, rng.randint(0, 2))}
        bare = rng.choice(ANY)
        chose = {name: rng.choice(ANY)
                 for name in rng.sample(NAMES, rng.randint(0, 2))}
        drawn = [(rng.choice(NAMES), rng.choice(ROWS), rng.choice("pqr"))
                 for _ in range(rng.randint(1, 4))]
        rows = list({(name, package): (name, level, package)
                     for name, level, package in drawn}.values())
        env = ",".join([logging.getLevelName(bare)] + [
            f"{name}={logging.getLevelName(level)}"
            for name, level in entries.items()])
        code_sets = list(chose.items())
        without, _ = _play(env, code_sets, rows, set(code_sets), with_rows=False)
        highest: dict[str, int] = {}
        for name, level, _package in rows:
            highest[name] = max(level, highest.get(name, level))
        endings = set()
        for _ in range(6):
            order = rows[:]
            rng.shuffle(order)
            early = {pair for pair in code_sets if rng.random() < 0.5}
            levels, world = _play(env, code_sets, order, early)
            endings.add(tuple(sorted(levels.items())))
            for name in NAMES:
                reach = [name, *above(name)]
                spoken = next((at for at in reach if at in entries), None)
                choice = next((at for at in reach if at in chose), None)
                what = (env, code_sets, order, sorted(early), name, levels[name])
                assert levels[name] >= without[name], ("2", what)
                if spoken is not None:
                    assert levels[name] == entries[spoken], ("3", what)
                elif choice is not None:
                    assert levels[name] == without[name], ("4", what)
                else:
                    capped = [highest[at] for at in reach if at in highest]
                    assert levels[name] == max([bare, *capped]), ("5", what)
            for said in world.outcome.values():
                verdicts["set" if said == "set" else "not set"] += 1
        assert len(endings) == 1, ("1", env, code_sets, rows, endings)
    # Both ways out were taken often: a property that held over worlds in which
    # no row was ever set would have said nothing.
    assert verdicts["set"] > 2000 and verdicts["not set"] > 2000, verdicts


# --- the module's own table: the call a package makes, and the application's ----

def _declare(logger: Any, level: Any, **said: Any) -> None:
    """The one line an installed package's registration module runs. Only its
    globals travel: :func:`_from_package` rebinds this body to a namespace named
    after some other package, which is what the table reads — the calling frame's
    ``__name__``."""
    cap(logger, level, **said)  # noqa: F821  (bound by `_from_package`)


def _from_package(package: str) -> Callable[..., None]:
    """:func:`_declare` as ``package``'s own registration submodule would call
    it."""
    return FunctionType(_declare.__code__,
                        {"__name__": f"{package}.registrations", "cap": noise.cap})


@pytest.fixture
def table() -> Iterator[None]:
    """The module's table as a process has it before any package declared — the
    library's own row, nothing set — with the default in charge and a
    ``LOG_LEVEL`` that says nothing, and an empty startup record. All of it is
    put back."""
    saved = (noise._caps, default.in_charge, default.entries)
    self_report.startup.forget()
    noise.forget_caps()
    default.in_charge, default.entries = True, Entries()
    try:
        yield
    finally:
        noise._caps, default.in_charge, default.entries = saved
        self_report.startup.forget()


def test_the_librarys_rows_are_one(table: None) -> None:
    """``markdown_it`` at ``INFO``; the cap on ``httpx`` left."""
    assert [(row.logger, row.level_name, row.package, row.hides)
            for row in noise.rows()] == [
        ("markdown_it", "INFO", "little_sister",
         "a DEBUG line for each block rule of every render")]


def test_the_package_is_inferred_from_the_call_site(table: None) -> None:
    _from_package("little_sister_example")(
        "example_sdk.credentials", logging.WARNING, hides="a line a run")
    noise.cap("example_sdk.retries", logging.INFO, hides="a line a retry")
    FunctionType(_declare.__code__, {"__name__": "__main__", "cap": noise.cap})(
        "example_sdk.wire", logging.INFO, hides="a line a request")
    assert [(row.logger, row.package, row.owner) for row in noise.rows()
            if row.logger != "markdown_it"] == [
        ("example_sdk.credentials", "little_sister_example", "little_sister_example"),
        ("example_sdk.retries", "tests", "tests"),
        ("example_sdk.wire", "", "an unidentified caller (__main__)")]


def test_a_refused_declaration_is_a_warning_a_skip_and_a_startup_line(
        table: None, caplog: pytest.LogCaptureFixture) -> None:
    """As on the neighboring seams: a mistake in a default never costs a
    deployment its monitoring, so nothing raises — a call that says nothing of
    what it hides included."""
    declare = _from_package("little_sister_example")
    with caplog.at_level(logging.WARNING, logger="little_sister"):
        declare("example_sdk.credentials", logging.ERROR, hides="its errors")
        declare("example_sdk.wire", logging.WARNING)
        declare(None, logging.WARNING, hides="x")
    assert [row.logger for row in noise.rows()] == ["markdown_it"]
    lines = {line.slug: line for line in self_report.startup.lines()}
    assert sorted(lines) == ["noise-little_sister_example-None",
                             "noise-little_sister_example-example_sdk.credentials",
                             "noise-little_sister_example-example_sdk.wire"]
    assert {line.code for line in lines.values()} == {StatusCode.WARN}
    said = lines["noise-little_sister_example-example_sdk.credentials"].text
    assert said.startswith("little_sister_example declares a noise cap on "
                           "example_sdk.credentials at ERROR — ")
    assert [record.levelname for record in caplog.records] == ["WARNING"] * 3
    assert all(record.getMessage().startswith("noise-little_sister_example-")
               for record in caplog.records)


def test_the_application_sets_the_rows_and_the_log_names_those_it_set(
        table: None, caplog: pytest.LogCaptureFixture) -> None:
    """An ``INFO`` line for each row that was set — one for each package that
    declared it — which names the entry of ``LOG_LEVEL`` that shows its lines:
    the logger at the level it is at without the cap, ``INFO`` under this root.
    The library's own row takes no line away under a root at ``INFO``: it is not
    set, it leaves nothing out, and the log says nothing of it."""
    logging.getLogger().setLevel(logging.INFO)
    _from_package("little_sister_example")(
        "example_sdk.credentials", logging.WARNING,
        hides="where each new session found its credentials, a line a run")
    _from_package("another_package")(
        "example_sdk.credentials", logging.INFO, hides="how it looked for them")
    with caplog.at_level(logging.INFO, logger="little_sister"):
        noise.settle()
    assert level_on("example_sdk.credentials") == logging.WARNING
    assert level_on("markdown_it") == logging.NOTSET
    assert [record.getMessage() for record in caplog.records] == [
        "noise: example_sdk.credentials is capped at WARNING, above the INFO "
        "another_package declared — it hides how it looked for them; "
        "example_sdk.credentials=INFO in LOG_LEVEL shows its lines",
        "noise: example_sdk.credentials is capped at WARNING for "
        "little_sister_example — it hides where each new session found its "
        "credentials, a line a run; example_sdk.credentials=INFO in LOG_LEVEL "
        "shows its lines"]
    assert {record.levelname for record in caplog.records} == {"INFO"}
    assert [(verdict.logger, verdict.reason)
            for verdict in noise.report().not_set] == [
        ("markdown_it", no_line("INFO"))]


@pytest.mark.parametrize("held_back_by", [
    "the level the root is at", "a level the startup file set",
    "an entry of LOG_LEVEL", "an application that configured logging"])
def test_a_row_that_was_not_set_is_not_in_the_log(
        table: None, caplog: pytest.LogCaptureFixture, held_back_by: str) -> None:
    """A log that leaves lines out says which, and a row that was not set leaves
    none out. So a start with nothing to cap writes no line of this, a deployment
    that set its own level reads none at every start, and nothing is written into
    the log of an application that configured logging itself. The page has every
    such row, with the reason."""
    _reset()
    logging.getLogger().setLevel(logging.INFO)
    _from_package("little_sister_example")(
        "example_sdk.credentials", logging.WARNING, hides="a line a run")
    if held_back_by == "the level the root is at":
        code("", logging.WARNING)                          # LOG_LEVEL=WARNING
        reason = no_line("WARNING")
    elif held_back_by == "a level the startup file set":
        code("example_sdk", logging.WARNING)               # as one deployment does
        reason = chosen("example_sdk", "WARNING")
    elif held_back_by == "an entry of LOG_LEVEL":
        default.entries = Entries.read("INFO,example_sdk.credentials=DEBUG")
        default._set_levels(default.entries)
        reason = named("example_sdk.credentials")
    else:
        default.in_charge = False
        reason = APPLICATION
    with caplog.at_level(logging.INFO, logger="little_sister"):
        noise.settle()
    assert caplog.records == []
    assert ("example_sdk.credentials", reason) in [
        (verdict.logger, verdict.reason) for verdict in noise.report().not_set]


# --- the entry that shows a capped logger's lines (decision 7) --------------------

@pytest.mark.parametrize(("root", "entry"), [
    (logging.INFO, "example_sdk.credentials=INFO"),        # the default's root
    (logging.DEBUG, "example_sdk.credentials=DEBUG"),
    (25, "example_sdk.credentials=INFO"),          # no name: the nearest beneath it
    (15, "example_sdk.credentials=DEBUG"),
    (logging.NOTSET, "example_sdk.credentials=DEBUG"),     # every line passes it
])
def test_a_set_cap_is_shown_by_the_level_the_logger_is_at_without_it(
        root: int, entry: str) -> None:
    """What the cap hid comes back, and nothing below it: under the default's
    root a cap at ``WARNING`` hid the ``INFO`` lines, and ``INFO`` shows them —
    ``DEBUG`` would be more than was hidden. An entry is written by a level's
    name, so a level `logging` has no name for is the nearest named one beneath
    it."""
    world = start()
    code("", root)
    world.cap("example_sdk.credentials", logging.WARNING)
    world.settle()
    (verdict,) = world.caps.verdicts()
    assert verdict.capped and verdict.without == root
    assert verdict.shown_by == entry


def test_a_cap_beneath_another_is_shown_by_the_level_the_one_above_left() -> None:
    """Under a root at ``DEBUG`` the SDK's own cap at ``INFO`` hides its
    ``DEBUG`` lines, and ``DEBUG`` shows them. The cap beneath it, at
    ``WARNING``, hides the ``INFO`` lines the one above left: ``INFO`` shows
    those, and the wire stays out."""
    world = start("DEBUG")
    world.cap("example_sdk", logging.INFO)
    world.cap("example_sdk.credentials", logging.WARNING)
    world.settle()
    assert {verdict.logger: verdict.shown_by
            for verdict in world.caps.verdicts()} == {
        "example_sdk": "example_sdk=DEBUG",
        "example_sdk.credentials": "example_sdk.credentials=INFO"}


def test_the_entry_brings_back_what_the_cap_hid_and_nothing_below_it(
        written: list[str]) -> None:
    """The entry a start names, written into the variable for the next one."""
    world = start()
    world.cap("example_sdk.credentials", logging.WARNING)
    world.settle()
    (verdict,) = world.caps.verdicts()
    sdk = logging.getLogger("example_sdk.credentials")
    sdk.info("Found credentials in shared credentials file")
    assert written == []                                   # the cap holds
    _reset()

    again = start(f"INFO,{verdict.shown_by}")              # the next start
    again.cap("example_sdk.credentials", logging.WARNING)
    again.settle()
    sdk.info("Found credentials in shared credentials file")
    sdk.debug("Looking for credentials via: env")
    assert written == ["example_sdk.credentials:INFO"]
    assert again.outcome == {
        "example_sdk.credentials": named("example_sdk.credentials")}


def test_the_application_sets_them_once_and_what_arrives_later_is_refused(
        table: None, caplog: pytest.LogCaptureFixture) -> None:
    declare = _from_package("little_sister_example")
    declare("example_sdk.credentials", logging.WARNING, hides="a line a run")
    noise.settle()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="little_sister"):
        noise.settle()                                     # imported twice
        declare("example_sdk.credentials", logging.WARNING, hides="a line a run")
    assert caplog.records == [] and self_report.startup.lines() == ()
    declare("example_sdk.wire", logging.WARNING, hides="a line a request")
    assert level_on("example_sdk.wire") == logging.NOTSET
    (line,) = self_report.startup.lines()
    assert line.slug == "noise-little_sister_example-example_sdk.wire"
    assert "after the application was imported" in line.text


def test_the_table_reads_what_the_process_decided(table: None) -> None:
    """Whether the default is in charge, and what ``LOG_LEVEL`` says, are the
    logger module's to know, read where the rows are set."""
    declare = _from_package("little_sister_example")
    declare("example_sdk.credentials", logging.WARNING, hides="a line a run")
    declare("example_sdk.wire", logging.WARNING, hides="a line a request")
    default.entries = Entries.read("INFO,example_sdk.credentials=DEBUG")
    code("example_sdk.credentials", logging.ERROR)         # the code of the slot
    noise.settle()
    assert level_on("example_sdk.credentials") == logging.DEBUG
    assert level_on("example_sdk.wire") == logging.WARNING
    noise.forget_caps()
    _reset()
    declare("example_sdk.wire", logging.WARNING, hides="a line a request")
    default.in_charge = False
    noise.settle()
    assert level_on("example_sdk.wire") == logging.NOTSET
    assert level_on("example_sdk.credentials") == logging.NOTSET


# --- what /system/installed is handed (decision 7) -------------------------------

def test_the_report_says_where_every_level_comes_from(table: None) -> None:
    """A row, with the packages that declared it and what it hides; an entry of
    ``LOG_LEVEL``; or neither — the application's code, or the dependency
    itself. Then every row that was not set, with the reason, every level an
    entry took off, and every entry that could not be read."""
    _reset()
    declare = _from_package("little_sister_example")
    declare("example_sdk.credentials", logging.WARNING, hides="a line a run")
    declare("example_sdk.wire", logging.WARNING, hides="a line a request")
    declare("example_http", logging.WARNING, hides="a line a connection")
    default.entries = Entries.read(
        "DEBUG,example_sdk.credentials=DEBUG,example_orm=ERROR,loud=LOUD")
    default._set_levels(default.entries)
    code("example_http", logging.ERROR)                    # the code of the slot
    code("example_orm.pool", logging.INFO)
    noise.settle()
    report = noise.report()
    assert (report.in_charge, report.root, report.root_source) == (
        True, "DEBUG", "variable")
    ours = [(level.logger, level.level_name, level.source,
             [row.package for row in level.rows])
            for level in report.levels if level.logger.startswith(
                ("example_", "markdown_it"))]
    assert ours == [
        ("example_http", "ERROR", "code", []),
        ("example_orm", "ERROR", "variable", []),
        ("example_sdk.credentials", "DEBUG", "variable", []),
        ("example_sdk.wire", "WARNING", "cap", ["little_sister_example"]),
        ("markdown_it", "INFO", "cap", ["little_sister"])]
    # the variable as it was read — without the entry that could not be — and for
    # each cap the entry that shows its lines: the page's example is the two
    assert report.variable == "DEBUG,example_sdk.credentials=DEBUG,example_orm=ERROR"
    assert [(level.logger, level.shown_by) for level in report.levels
            if level.shown_by] == [("example_sdk.wire", "example_sdk.wire=DEBUG"),
                                   ("markdown_it", "markdown_it=DEBUG")]
    assert [(verdict.logger, verdict.level_name, verdict.reason)
            for verdict in report.not_set] == [
        ("example_http", "WARNING", chosen("example_http", "ERROR")),
        ("example_sdk.credentials", "WARNING",
         named("example_sdk.credentials"))]
    assert [(taken.logger, taken.level_name, taken.entry)
            for taken in report.taken_off] == [
        ("example_orm.pool", "INFO", "example_orm")]
    assert [(skipped.entry, skipped.why) for skipped in report.unreadable] == [
        ("loud=LOUD", "'LOUD' is not a level name")]


def test_the_report_says_what_stands_now(table: None) -> None:
    """What code sets after the application was imported, it sets, and the page
    says what stands: a level a row set and code moved is the code's."""
    _reset()
    default.entries = Entries.read("DEBUG,example_orm=ERROR")
    default._set_levels(default.entries)
    _from_package("little_sister_example")(
        "example_sdk.wire", logging.WARNING, hides="a line a request")
    noise.settle()
    assert [(level.logger, level.source) for level in noise.report().levels
            if level.logger.startswith("example_")] == [
        ("example_orm", "variable"), ("example_sdk.wire", "cap")]
    code("example_sdk.wire", logging.DEBUG)
    code("example_orm", logging.INFO)
    code("", logging.WARNING)
    report = noise.report()
    assert (report.root, report.root_source) == ("WARNING", "code")
    assert [(level.logger, level.level_name, level.source)
            for level in report.levels if level.logger.startswith("example_")] == [
        ("example_orm", "INFO", "code"), ("example_sdk.wire", "DEBUG", "code")]
    assert [verdict.logger for verdict in report.not_set] == []


def test_a_level_taken_off_at_both_moments_is_listed_once(table: None) -> None:
    """The entries are said twice — with the default, and where the rows are set
    — so a level that stood beneath an entry before the library was imported, and
    was set again in the slot, is taken off twice. The page lists what was taken
    off, and that is one thing. Another level the second time is another."""
    _reset()
    code("example_sdk.credentials", logging.WARNING)       # before the library
    code("example_sdk.wire", logging.WARNING)
    default.entries = Entries.read("INFO,example_sdk=DEBUG")
    default._set_levels(default.entries)                   # said with the default
    code("example_sdk.credentials", logging.WARNING)       # the slot, again
    code("example_sdk.wire", logging.ERROR)                # … and otherwise
    noise.settle()                                         # said a second time
    assert len(default.entries.taken_off) == 4
    assert sorted((taken.logger, taken.level_name, taken.entry)
                  for taken in noise.report().taken_off) == [
        ("example_sdk.credentials", "WARNING", "example_sdk"),
        ("example_sdk.wire", "ERROR", "example_sdk"),
        ("example_sdk.wire", "WARNING", "example_sdk")]


@pytest.mark.parametrize(("variable", "root", "source"), [
    ("", logging.INFO, "default"),
    ("loud", logging.INFO, "default"),
    ("WARNING", logging.WARNING, "variable"),
    ("INFO", logging.INFO, "variable"),
])
def test_the_report_says_where_the_roots_level_comes_from(
        table: None, variable: str, root: int, source: str) -> None:
    default.entries = Entries.read(variable)
    default._set_levels(default.entries)
    noise.settle()
    report = noise.report()
    assert (report.root, report.root_source) == (logging.getLevelName(root), source)


@pytest.mark.parametrize("variable", ["", "WARNING"])
def test_the_roots_level_is_the_codes_once_code_moved_it(table: None,
                                                         variable: str) -> None:
    """The bare level is set once, with the default: what the deployment's code
    sets on the root afterwards stands, and the page does not go on calling it
    the variable's, or the default."""
    default.entries = Entries.read(variable)
    default._set_levels(default.entries)
    code("", logging.ERROR)
    noise.settle()
    report = noise.report()
    assert (report.root, report.root_source) == ("ERROR", "code")


def test_where_the_application_configured_logging_the_report_says_so(
        table: None) -> None:
    """The root's level is the application's, no row is set, and the variable
    does nothing: nothing of it is listed."""
    _reset()
    logging.getLogger().setLevel(logging.ERROR)
    default.in_charge = False
    default.entries = Entries.read("DEBUG,example_orm=DEBUG,loud=LOUD")
    code("example_orm", logging.DEBUG)                     # the application's own
    _from_package("little_sister_example")(
        "example_sdk.wire", logging.WARNING, hides="a line a request")
    noise.settle()
    report = noise.report()
    assert (report.in_charge, report.root, report.root_source) == (
        False, "ERROR", "application")
    assert [(level.level_name, level.source) for level in report.levels
            if level.logger == "example_orm"] == [("DEBUG", "code")]
    assert {verdict.reason for verdict in report.not_set} == {APPLICATION}
    assert [verdict.logger for verdict in report.not_set] == [
        "example_sdk.wire", "markdown_it"]
    assert report.taken_off == () and report.unreadable == ()
    assert report.variable == ""


# --- a deployment, in a process of its own: the plan's *done when* ---------------
#
# An instance that installs a package which declares a cap writes none of that
# logger's INFO lines at a run, without a line of its own code;
# `LOG_LEVEL=INFO,<logger>=DEBUG` brings them back from `.env` as from the
# environment; and `/system/installed` says which of the two holds. The package is
# a stand-in — `little-sister-aws` declares what its SDK writes in a release of its
# own — and what its dependency logs is the SDK's own sentence.

_A_PACKAGE = """
import logging

from little_sister import noise

noise.cap("example_sdk.credentials", logging.WARNING,
          hides="where each new session found its credentials, a line a run")
"""

_A_DEPLOYMENT = """
import logging

import example_package                   # a check package, as a `wsgi.py` imports it
from little_sister import local_login

local_login.use_local()

from little_sister import app            # the caps are set here

app.start()
logging.getLogger("example_sdk.credentials").info(
    "Found credentials in shared credentials file: ~/.aws/credentials")
logging.getLogger("example_sdk.endpoint").info("a line of its sibling")
client = app.app.test_client()
client.post("/login", data={"username": "pan", "password": "12345678"})
print(client.get("/system/installed").get_data(as_text=True))
"""


@dataclass
class _Ran:
    """What one start of the deployment left: its log, and what its page says of
    the stand-in dependency's logger."""
    log: list[str]
    page: str

    def said_of(self, logger: str) -> list[str]:
        """Every table row of the page's Logging section that names ``logger``,
        as a reader reads it."""
        section = self.page.split('id="logging">', 1)[1]
        rows = re.findall(r"<tr>(.*?)</tr>", section, re.S)
        return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", row)).split())
                for row in rows if f"<code>{logger}</code>" in row]


def _a_deployment_starts(directory: Path, *, script: str = _A_DEPLOYMENT,
                         env_file: str = "", **environment: str) -> _Ran:
    """Start the deployment once, in ``directory``: its package on the path, its
    ``.env`` as given, its log in a file of its own."""
    (directory / "example_package.py").write_text(_A_PACKAGE)
    if env_file:
        (directory / ".env").write_text(env_file)
    log = directory / "instance.log"
    handed = subprocess_env()
    handed.pop("LOG_LEVEL", None)
    path = os.pathsep.join(filter(None, [str(directory),
                                         handed.get("PYTHONPATH", "")]))
    done = subprocess.run(
        [sys.executable, "-c", script], cwd=directory,
        env={**handed, "PYTHONPATH": path, "LOG_FILE": str(log),
             "LITTLE_SISTER_ENGINE": "0", **environment},
        capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return _Ran([line.split(" - ", 1)[1] for line in log.read_text().splitlines()],
                done.stdout)


CREDENTIALS = ("example_sdk.credentials - INFO - Found credentials in shared "
               "credentials file: ~/.aws/credentials")
SIBLING = "example_sdk.endpoint - INFO - a line of its sibling"


def test_a_package_that_declares_a_cap_is_quiet_without_a_line_of_the_deployments(
        tmp_path: Path) -> None:
    ran = _a_deployment_starts(tmp_path)

    assert CREDENTIALS not in ran.log and SIBLING in ran.log
    # the log says it where it begins, and names the entry that shows the lines
    assert ("little_sister.logger - INFO - noise: example_sdk.credentials is "
            "capped at WARNING for example_package — it hides where each new "
            "session found its credentials, a line a run; "
            "example_sdk.credentials=INFO in LOG_LEVEL shows its lines") in ran.log
    assert ran.said_of("example_sdk.credentials") == [
        "example_sdk.credentials WARNING cap, declared by example_package — hides "
        "where each new session found its credentials, a line a run"]


@pytest.mark.parametrize("written_in", [".env", "the environment"])
def test_log_level_brings_the_lines_back_by_name(tmp_path: Path,
                                                 written_in: str) -> None:
    """From ``.env`` as from the environment, and the page says which holds."""
    variable = "INFO,example_sdk.credentials=DEBUG"
    if written_in == ".env":
        ran = _a_deployment_starts(tmp_path, env_file=f"LOG_LEVEL={variable}\n")
    else:
        ran = _a_deployment_starts(tmp_path, LOG_LEVEL=variable)

    assert CREDENTIALS in ran.log and SIBLING in ran.log
    # no cap was set, so the log leaves nothing out and says nothing of one: not of
    # the package's row, which the variable names, nor of the library's own
    assert [line for line in ran.log
            if line.startswith("little_sister.logger - INFO - noise: ")] == []
    assert ran.said_of("example_sdk.credentials") == [
        "example_sdk.credentials DEBUG LOG_LEVEL entry "
        "example_sdk.credentials=DEBUG",
        "example_sdk.credentials WARNING example_package — hides where each new "
        "session found its credentials, a line a run LOG_LEVEL names "
        "example_sdk.credentials"]


def test_a_deployment_that_capped_in_the_slot_keeps_its_level_at_a_start(
        tmp_path: Path) -> None:
    """Its own `setLevel` between its packages and the application, as one
    deployment writes it, stands against the package's row — here a level that
    lets the lines through, which no row may overrule."""
    slot = _A_DEPLOYMENT.replace(
        "local_login.use_local()\n",
        "local_login.use_local()\n"
        "logging.getLogger('example_sdk').setLevel(logging.INFO)\n")
    assert slot != _A_DEPLOYMENT

    ran = _a_deployment_starts(tmp_path, script=slot, LOG_LEVEL="WARNING")

    assert CREDENTIALS in ran.log and SIBLING in ran.log
    assert ran.said_of("example_sdk.credentials") == [
        "example_sdk.credentials WARNING example_package — hides where each new "
        "session found its credentials, a line a run example_sdk is at INFO, set "
        "by the application's code or by the dependency itself"]
