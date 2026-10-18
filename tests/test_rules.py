"""A rule list is the library's, and a value matches it exactly (ADR-0129).

Each class holds one decision to account, in its own sentences: the list consulted in
order, the first rule that matches deciding whole (decision 1); the axes a package
declares, and the absent value (2); a value compared exactly (3); the keys of a
package's own and the reader it hands over (4); the log line about the rules that
matched nothing (5); and the word a line a rule owns carries (6).
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest import TestCase

from little_sister.checks import Check, CheckError, Measurement
from little_sister.checks.base import CheckResult
from little_sister.rules import RULE_WORD, Axis, Matcher, RuleList
from little_sister.status import StatusCode

LOGGER = "little_sister.rules"
PATH = "checks/estate"

#: One axis, written on the rule itself, whose values can be absent — as an
#: instance's Name tag can be.
NAMES = (Axis("name", absent=True, on_rule=True),)
#: The same axis where a value is always there — a pipeline is named by existing.
ALWAYS = (Axis("name", on_rule=True),)
#: Two named axes, as a workflow is addressed by its repository and its file.
WORKFLOWS = (Axis("repositories"), Axis("files"))
#: A named axis whose values can be absent, beside one whose values cannot.
OWNED = (Axis("owners", absent=True), Axis("files"))


def _rules(value: object, axes: Sequence[Axis] = NAMES,
           **declared: Any) -> RuleList[Any]:
    return RuleList(value, "estate", axes, **declared)


def _refusal(value: object, axes: Sequence[Axis] = NAMES, **declared: Any) -> str:
    """What reading ``value`` is refused with — a refusal being the point."""
    try:
        _rules(value, axes, **declared)
    except CheckError as error:
        return str(error)
    raise AssertionError(f"{value!r} was read, and should have been refused")


def _decides(rules: RuleList[Any], **values: str | None) -> str | None:
    """The name of the rule that decides ``values``, or ``None``."""
    rule = rules.first(**values)
    return None if rule is None else rule.name


def _own(rule: Mapping[str, Any], where: str) -> dict[str, Any]:
    """A package's reader that carries what it was handed, and where."""
    return {"keys": dict(rule), "where": where}


class FirstMatchDecidesTests(TestCase):
    """Decision 1: the list is consulted in order and the first rule that matches
    decides, whole; every rule carries a name, unique in its list; ``ignore: true`` is
    refused beside any key of the package's own; a rule naming nothing to match, and
    a key nobody takes, are refused at the start."""

    def test_an_exception_is_a_rule_written_above_the_rule_it_excepts(self) -> None:
        rules = _rules([{"name": "keep-web-1", "names": ["web-1"]},
                        {"name": "drop-web", "prefixes": ["web-"], "ignore": True}])
        kept, dropped = rules.first(name="web-1"), rules.first(name="web-2")
        assert kept is not None and dropped is not None
        self.assertEqual((kept.name, kept.ignore), ("keep-web-1", False))
        self.assertEqual((dropped.name, dropped.ignore), ("drop-web", True))
        self.assertIsNone(rules.first(name="db-1"))

    def test_the_first_rule_decides_whole(self) -> None:
        # Not the first rule that sets each key: what the second rule writes adds
        # nothing to a value the first decides.
        rules = _rules([{"name": "fleet", "prefixes": ["web-"], "limit": 1},
                        {"name": "all", "regexes": [".*"], "limit": 2, "note": "x"}],
                       own_keys=("limit", "note"), read_own=_own)
        rule = rules.first(name="web-1")
        assert rule is not None
        self.assertEqual((rule.name, rule.own["keys"]), ("fleet", {"limit": 1}))

    def test_the_list_holds_its_rules_in_the_order_they_were_written(self) -> None:
        rules = _rules([{"name": "keep-web-1", "names": ["web-1"]},
                        {"name": " drop-web ", "prefixes": ["web-"], "ignore": True}])
        self.assertEqual([rule.name for rule in rules], ["keep-web-1", "drop-web"])
        self.assertEqual(len(rules), 2)

    def test_every_rule_carries_a_name(self) -> None:
        for rule in ({"prefixes": ["web-"]}, {"name": " ", "prefixes": ["web-"]},
                     {"name": 7, "prefixes": ["web-"]}):
            self.assertIn("estate rules[1] needs a 'name'", _refusal([rule]))

    def test_a_name_is_unique_in_its_list(self) -> None:
        self.assertIn("rules[2] ('web'): another rule is already called that",
                      _refusal([{"name": "web", "prefixes": ["web-"]},
                                {"name": "web", "prefixes": ["api-"]}]))
        # Told apart without case, since the log line and a refusal name both.
        self.assertIn("rules[2] ('Web'): another rule is already called 'web'",
                      _refusal([{"name": "web", "prefixes": ["web-"]},
                                {"name": "Web", "prefixes": ["api-"]}]))

    def test_ignore_drops_what_the_rule_matches(self) -> None:
        rule = _rules([{"name": "tmp", "prefixes": ["tmp-"], "ignore": True}]
                      ).first(name="tmp-1")
        assert rule is not None
        self.assertTrue(rule.ignore)

    def test_ignore_is_refused_beside_a_key_of_the_packages_own(self) -> None:
        refusal = _refusal([{"name": "tmp", "prefixes": ["tmp-"], "ignore": True,
                             "limit": 3}], own_keys=("limit",), read_own=_own)
        self.assertIn("estate rules[1] ('tmp'): 'ignore' drops what the rule matches",
                      refusal)
        self.assertIn("'limit'", refusal)
        # A null is a key written, which says something: an explicitly ungraded
        # judgment is not nothing.
        self.assertIn("'ignore' drops", _refusal(
            [{"name": "tmp", "prefixes": ["tmp-"], "ignore": True, "limit": None}],
            own_keys=("limit",), read_own=_own))
        # Beside `ignore: false` the rule is an ordinary one.
        rule = _rules([{"name": "tmp", "prefixes": ["tmp-"], "ignore": False,
                        "limit": 3}], own_keys=("limit",), read_own=_own
                      ).first(name="tmp-1")
        assert rule is not None
        self.assertEqual((rule.ignore, rule.own["keys"]), (False, {"limit": 3}))

    def test_ignore_is_true_or_false(self) -> None:
        self.assertIn("'ignore' must be true or false", _refusal(
            [{"name": "tmp", "prefixes": ["tmp-"], "ignore": "true"}]))

    def test_a_rule_that_names_nothing_to_match_is_refused(self) -> None:
        for rule in ({"name": "web"}, {"name": "web", "names": []},
                     {"name": "web", "unnamed": False}):
            self.assertIn("estate rules[1] ('web'): a rule needs at least one of "
                          "'names', 'prefixes', 'regexes' or 'unnamed'",
                          _refusal([rule]))
        self.assertIn("a rule needs at least one of 'repositories' or 'files'",
                      _refusal([{"name": "ci", "ignore": True}], WORKFLOWS))
        for files in ([], {}, {"names": [], "regexes": []}):
            self.assertIn("estate rules[1] ('ci'): 'files' names nothing to match",
                          _refusal([{"name": "ci", "files": files}], WORKFLOWS))

    def test_a_key_nobody_takes_is_refused_naming_the_keys_a_rule_takes(self) -> None:
        self.assertIn(
            "unknown key(s) in estate rules[1] ('web'): prefix (a rule takes: ignore, "
            "limit, name, names, prefixes, regexes, unnamed)",
            _refusal([{"name": "web", "prefix": ["web-"]}],
                     own_keys=("limit",), read_own=_own))
        self.assertIn(
            "unknown key(s) in estate rules[1] ('ci'): repository (a rule takes: "
            "files, ignore, name, repositories)",
            _refusal([{"name": "ci", "repository": ["shop"]}], WORKFLOWS))
        self.assertIn(
            "unknown key(s) in estate rules[1] ('ci') 'files': name ('files' takes: "
            "names, prefixes, regexes)",
            _refusal([{"name": "ci", "files": {"name": ["ci.yml"]}}], WORKFLOWS))

    def test_rules_are_a_list_of_mappings(self) -> None:
        self.assertIn("estate 'rules' must be a list of mappings",
                      _refusal({"name": "web", "prefixes": ["web-"]}))
        self.assertIn("estate rules[1] must be a mapping", _refusal(["web-"]))

    def test_no_rules_is_a_list_that_decides_nothing(self) -> None:
        for value in (None, []):
            rules = _rules(value)
            self.assertEqual((len(rules), rules.first(name="web-1")), (0, None))


class AxesTests(TestCase):
    """Decision 2: a named axis is a key on the rule, a list of names or a block of
    names, prefixes and regexes, and the one axis of an aspect may be written on the
    rule itself; a rule matches when every axis it writes matches, an axis it leaves
    out matches any value, and any form of an axis is enough; ``unnamed: true``
    matches the absent value and nothing else does, and is refused where a value
    cannot be absent."""

    def test_a_named_axis_is_a_list_of_names(self) -> None:
        rules = _rules([{"name": "shop", "repositories": ["shop"]}], WORKFLOWS)
        self.assertEqual(_decides(rules, repositories="shop", files="ci.yml"), "shop")
        self.assertIsNone(_decides(rules, repositories="shop-api", files="ci.yml"))

    def test_or_a_block_of_names_prefixes_and_regexes(self) -> None:
        rules = _rules([{"name": "deploys", "files": {
            "names": ["deploy.yml"], "prefixes": ["release-"],
            "regexes": ["nightly-.*\\.yml"]}}], WORKFLOWS)
        for file in ("deploy.yml", "release-eu.yml", "nightly-build.yml"):
            self.assertEqual(_decides(rules, repositories="shop", files=file),
                             "deploys")
        self.assertIsNone(_decides(rules, repositories="shop", files="ci.yml"))

    def test_the_one_axis_of_an_aspect_may_be_written_on_the_rule_itself(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]}])
        self.assertEqual(_decides(rules, name="web-1"), "web")
        rule = rules.first(name="web-1")
        assert rule is not None
        self.assertEqual(rule.matchers, (("name", Matcher(prefixes=("web-",))),))

    def test_a_rule_matches_when_every_axis_it_writes_matches(self) -> None:
        # The one workflow file of the one repository: what started this record.
        rules = _rules([{"name": "load-test", "repositories": ["load-tests"],
                         "files": ["pipeline.yml"], "ignore": True}], WORKFLOWS)
        self.assertEqual(
            _decides(rules, repositories="load-tests", files="pipeline.yml"),
            "load-test")
        self.assertIsNone(_decides(rules, repositories="load-tests",
                                   files="ci.yml"))
        self.assertIsNone(_decides(rules, repositories="shop", files="pipeline.yml"))

    def test_an_axis_a_rule_leaves_out_matches_any_value(self) -> None:
        rules = _rules([{"name": "pipelines", "files": ["pipeline.yml"]}], OWNED)
        for owners in ("ops", "", None):
            self.assertEqual(_decides(rules, owners=owners, files="pipeline.yml"),
                             "pipelines")

    def test_within_an_axis_any_of_its_forms_matching_is_enough(self) -> None:
        rules = _rules([{"name": "mixed", "names": ["db"], "prefixes": ["web-"],
                         "regexes": ["api-[0-9]+"]}])
        for name in ("db", "web-1", "api-12"):
            self.assertEqual(_decides(rules, name=name), "mixed")
        self.assertIsNone(_decides(rules, name="cache"))

    def test_unnamed_matches_the_absent_value(self) -> None:
        rules = _rules([{"name": "nameless", "unnamed": True}])
        self.assertEqual(_decides(rules, name=None), "nameless")
        self.assertIsNone(_decides(rules, name="web-1"))
        self.assertIsNone(_decides(rules, name=""))

    def test_and_nothing_else_does(self) -> None:
        rules = _rules([{"name": "everything", "regexes": [".*"]},
                        {"name": "web", "names": ["web"], "prefixes": ["w"]}])
        self.assertEqual(_decides(rules, name=""), "everything")
        self.assertIsNone(_decides(rules, name=None))

    def test_unnamed_is_read_in_the_block_of_an_axis_that_can_be_absent(self) -> None:
        rules = _rules([{"name": "unowned", "owners": {"unnamed": True}}], OWNED)
        self.assertEqual(_decides(rules, owners=None, files="ci.yml"), "unowned")
        self.assertIsNone(_decides(rules, owners="ops", files="ci.yml"))

    def test_unnamed_is_true_or_false(self) -> None:
        self.assertIn("estate rules[1] ('nameless'): 'unnamed' must be true or false",
                      _refusal([{"name": "nameless", "unnamed": "true"}]))
        self.assertIn("'owners.unnamed' must be true or false",
                      _refusal([{"name": "o", "owners": {"unnamed": 1}}], OWNED))

    def test_unnamed_is_refused_where_a_value_cannot_be_absent(self) -> None:
        self.assertIn(
            "estate rules[1] ('nameless'): 'unnamed' matches only an absent value, and "
            "no name is absent here: the rule could never match",
            _refusal([{"name": "nameless", "unnamed": True}], ALWAYS))
        self.assertIn(
            "estate rules[1] ('ci'): 'files.unnamed' matches only an absent value",
            _refusal([{"name": "ci", "files": {"unnamed": True}}], OWNED))

    def test_a_value_is_handed_over_for_each_axis_by_its_name(self) -> None:
        rules = _rules(None, WORKFLOWS)
        with self.assertRaisesRegex(
                CheckError, "^estate rules match along repositories, files, and were "
                            "handed files, repository$"):
            rules.first(repository="shop", files="ci.yml")
        with self.assertRaisesRegex(CheckError, "were handed files$"):
            rules.see(files="ci.yml")

    def test_an_axis_on_the_rule_is_its_lists_only_axis(self) -> None:
        with self.assertRaisesRegex(CheckError, "only axis"):
            _rules(None, (Axis("name", on_rule=True), Axis("files")))

    def test_a_list_matches_along_one_axis_at_least_each_its_own(self) -> None:
        with self.assertRaisesRegex(CheckError, "one axis at least"):
            _rules(None, ())
        with self.assertRaisesRegex(CheckError, "two axes are called the same"):
            _rules(None, (Axis("files"), Axis("files")))


class ExactTests(TestCase):
    """Decision 3: a name matches a value equal to it as the source returned it; a
    prefix, a value that begins with it; a regex, a value it matches whole. Nothing
    folds case, and no flag on a rule changes what its entries mean."""

    def test_a_name_matches_a_value_equal_to_it(self) -> None:
        rules = _rules([{"name": "web", "names": ["web"]}])
        self.assertEqual(_decides(rules, name="web"), "web")
        for name in ("Web", "web-1", "my-web", "web "):
            self.assertIsNone(_decides(rules, name=name), name)

    def test_a_prefix_matches_a_value_that_begins_with_it(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]}])
        self.assertEqual(_decides(rules, name="web-1"), "web")
        for name in ("Web-1", "my-web-1", "web"):
            self.assertIsNone(_decides(rules, name=name), name)

    def test_a_regex_matches_a_value_whole(self) -> None:
        rules = _rules([{"name": "web", "regexes": ["web"]}])
        self.assertEqual(_decides(rules, name="web"), "web")
        for name in ("web-1", "my-web"):
            self.assertIsNone(_decides(rules, name=name), name)

    def test_a_pattern_meaning_less_than_the_whole_says_so_with_dot_star(self) -> None:
        rules = _rules([{"name": "web", "regexes": ["web-.*"]},
                        {"name": "anchored", "regexes": ["^db$"]}])
        self.assertEqual(_decides(rules, name="web-1"), "web")
        self.assertEqual(_decides(rules, name="db"), "anchored")

    def test_nothing_folds_case(self) -> None:
        rules = _rules([{"name": "web", "names": ["Web"], "prefixes": ["Api-"],
                         "regexes": ["Db-.*"]}])
        for name in ("web", "api-1", "db-1"):
            self.assertIsNone(_decides(rules, name=name), name)

    def test_a_pattern_that_wants_case_folded_says_so_itself(self) -> None:
        rules = _rules([{"name": "web", "regexes": ["(?i)web-.*"]}])
        for name in ("web-1", "WEB-1", "Web-1"):
            self.assertEqual(_decides(rules, name=name), "web", name)

    def test_no_flag_on_a_rule_changes_what_its_entries_mean(self) -> None:
        for flag in ("ignore_case", "regex", "case_sensitive"):
            self.assertIn(f"unknown key(s) in estate rules[1] ('web'): {flag} ",
                          _refusal([{"name": "web", "names": ["web"], flag: True}]))

    def test_an_entry_is_a_non_empty_string(self) -> None:
        self.assertIn("estate rules[1] ('web'): 'names' must be a list",
                      _refusal([{"name": "web", "names": "web"}]))
        for entries in ([7], [""], ["  "]):
            self.assertIn("every 'prefixes' entry must be a non-empty string",
                          _refusal([{"name": "web", "prefixes": entries}]))
        self.assertIn("every 'files' entry must be a non-empty string",
                      _refusal([{"name": "ci", "files": [7]}], WORKFLOWS))
        self.assertIn("'files' must be a list of names or a block",
                      _refusal([{"name": "ci", "files": "ci.yml"}], WORKFLOWS))

    def test_a_regex_that_does_not_compile_is_refused(self) -> None:
        self.assertIn("estate rules[1] ('web'): 'regexes' entry 'web-(' is not a "
                      "regular expression",
                      _refusal([{"name": "web", "regexes": ["web-("]}]))
        self.assertIn("'files.regexes' entry '(' is not a regular expression",
                      _refusal([{"name": "ci", "files": {"regexes": ["("]}}],
                               WORKFLOWS))


class OwnKeysTests(TestCase):
    """Decision 4: a package hands the library the keys of a rule that are its own
    and a reader for them, and the rule carries what the reader returned."""

    def test_the_rule_carries_what_the_reader_returned(self) -> None:
        rules = _rules([{"name": "fleet", "prefixes": ["web-"], "limit": 4}],
                       own_keys=("limit", "note"), read_own=_own)
        rule = rules.first(name="web-1")
        assert rule is not None
        self.assertEqual(rule.own, {"keys": {"limit": 4},
                                    "where": "estate rules[1] ('fleet')"})

    def test_the_reader_is_handed_the_keys_of_the_packages_own_alone(self) -> None:
        handed: list[Mapping[str, Any]] = []

        def read(rule: Mapping[str, Any], where: str) -> None:
            handed.append(rule)

        _rules([{"name": "fleet", "prefixes": ["web-"], "limit": None, "note": "n"}],
               own_keys=("limit", "note"), read_own=read)
        self.assertEqual(handed, [{"limit": None, "note": "n"}])

    def test_a_rule_that_writes_none_of_them_carries_nothing(self) -> None:
        handed: list[Mapping[str, Any]] = []

        def read(rule: Mapping[str, Any], where: str) -> str:
            handed.append(rule)
            return "read"

        rule = _rules([{"name": "fleet", "prefixes": ["web-"]}],
                      own_keys=("limit",), read_own=read).first(name="web-1")
        assert rule is not None
        self.assertEqual((rule.own, handed), (None, []))

    def test_what_the_reader_refuses_stops_the_read(self) -> None:
        def read(rule: Mapping[str, Any], where: str) -> None:
            raise CheckError(f"{where}: 'limit' must be a number")

        self.assertEqual(
            _refusal([{"name": "fleet", "prefixes": ["web-"], "limit": "x"}],
                     own_keys=("limit",), read_own=read),
            "estate rules[1] ('fleet'): 'limit' must be a number")

    def test_the_keys_and_their_reader_come_together(self) -> None:
        with self.assertRaisesRegex(CheckError, "come together"):
            _rules(None, own_keys=("limit",))
        with self.assertRaisesRegex(CheckError, "come together"):
            _rules(None, read_own=_own)
        with self.assertRaisesRegex(CheckError, "not the string 'limit'"):
            _rules(None, own_keys="limit", read_own=_own)

    def test_a_key_of_the_packages_own_is_no_word_of_the_librarys(self) -> None:
        for key in ("names", "unnamed", "ignore"):
            with self.assertRaisesRegex(CheckError, "the library reads on every rule"):
                _rules(None, own_keys=(key,), read_own=_own)
        with self.assertRaisesRegex(CheckError, "the library reads on every rule"):
            _rules(None, (Axis("name"),))
        with self.assertRaisesRegex(CheckError, "an axis and a key of the package"):
            _rules(None, WORKFLOWS, own_keys=("files",), read_own=_own)


class ReportTests(TestCase):
    """Decision 5: a rule that matched nothing is a line at INFO, one per check and
    rule list, naming the rules, when that set changes and once more when it empties;
    to each rule it adds what it missed — the rule above it that decided a value its
    matcher matches, or else a value the run saw that its matcher would have matched
    with case folded; the list keeps the run's tally because the grading keeps none;
    and a run that could not read the whole of its scope leaves the set as it
    was."""

    def _logged(self, rules: RuleList[Any], *,
                whole: bool = True) -> list[logging.LogRecord]:
        """The records one report writes — none, where it writes nothing."""
        with self.assertLogs(LOGGER, logging.DEBUG) as logs:
            rules.report(PATH, whole=whole)
            # A record of the test's own, since a report may rightly write none.
            logging.getLogger(LOGGER).debug("the report is over")
        return logs.records[:-1]

    def _report(self, rules: RuleList[Any], *, whole: bool = True) -> list[str]:
        return [record.getMessage() for record in self._logged(rules, whole=whole)]

    def test_the_rules_that_matched_nothing_are_named_at_info(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]},
                        {"name": "db", "prefixes": ["db-"]},
                        {"name": "api", "prefixes": ["api-"]}])
        rules.see(name="web-1")
        self.assertEqual(
            [(record.levelno, record.getMessage()) for record in self._logged(rules)],
            [(logging.INFO, f"{PATH}: 2 estate rule(s) matched nothing: db, api")])

    def test_once_per_change(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]},
                        {"name": "db", "prefixes": ["db-"]}])
        rules.see(name="web-1")
        self.assertEqual(self._report(rules),
                         [f"{PATH}: 1 estate rule(s) matched nothing: db"])
        rules.see(name="web-2")
        self.assertEqual(self._report(rules), [])
        rules.see(name="db-1")
        self.assertEqual(self._report(rules),
                         [f"{PATH}: 1 estate rule(s) matched nothing: web"])

    def test_and_once_more_when_it_empties(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]},
                        {"name": "db", "prefixes": ["db-"]}])
        rules.see(name="web-1")
        self._report(rules)
        rules.see(name="web-1")
        rules.see(name="db-1")
        self.assertEqual(self._report(rules),
                         [f"{PATH}: every estate rule now matches something"])
        rules.see(name="web-1")
        rules.see(name="db-1")
        self.assertEqual(self._report(rules), [])

    def test_a_first_run_whose_every_rule_matched_says_nothing(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]}])
        rules.see(name="web-1")
        self.assertEqual(self._report(rules), [])

    def test_a_rule_that_dropped_what_it_matched_has_matched(self) -> None:
        rules = _rules([{"name": "tmp", "prefixes": ["tmp-"], "ignore": True}])
        rules.see(name="tmp-1")
        self.assertEqual(self._report(rules), [])

    def test_a_value_the_rule_would_match_with_case_folded_is_named(self) -> None:
        rules = _rules([{"name": "web", "names": ["Web"]},
                        {"name": "api", "prefixes": ["API-"]},
                        {"name": "db", "regexes": ["db-[a-z]+"]},
                        {"name": "cache", "prefixes": ["cache-"]}])
        for name in ("web", "api-1", "DB-EU", "queue-1", "WEB"):
            rules.see(name=name)
        self.assertEqual(self._report(rules), [
            f"{PATH}: 4 estate rule(s) matched nothing: "
            "web (would match 'web' with case folded), "
            "api (would match 'api-1' with case folded), "
            "db (would match 'DB-EU' with case folded), cache"])

    def test_an_absent_value_is_no_near_miss(self) -> None:
        rules = _rules([{"name": "web", "names": ["Web"]}])
        rules.see(name=None)
        rules.see(name="web")
        self.assertEqual(self._report(rules), [
            f"{PATH}: 1 estate rule(s) matched nothing: web (would match 'web' with "
            "case folded)"])

    def test_on_each_axis_the_rule_writes(self) -> None:
        rules = _rules([{"name": "load-test", "repositories": ["load-tests"],
                         "files": ["pipeline.yml"]},
                        {"name": "deploys", "files": ["Deploy.yml"]}], WORKFLOWS)
        rules.see(repositories="load-tests", files="Pipeline.yml")
        rules.see(repositories="shop", files="deploy.yml")
        self.assertEqual(self._report(rules), [
            f"{PATH}: 2 estate rule(s) matched nothing: load-test (would match "
            "repositories 'load-tests', files 'Pipeline.yml' with case folded), "
            "deploys (would match files 'deploy.yml' with case folded)"])

    def test_only_where_every_axis_the_rule_writes_would_match(self) -> None:
        rules = _rules([{"name": "shop-deploys", "repositories": ["shop"],
                         "files": ["Deploy.yml"]}], WORKFLOWS)
        rules.see(repositories="api", files="deploy.yml")
        self.assertEqual(self._report(rules),
                         [f"{PATH}: 1 estate rule(s) matched nothing: shop-deploys"])

    def test_a_value_the_rule_matches_names_the_rule_above_that_decided_it(
            self) -> None:
        # An exception written below the rule it excepts: its value goes to the rule
        # above, and the limit the exception carries never applies.
        rules = _rules([{"name": "web", "prefixes": ["web-"]},
                        {"name": "web-1", "names": ["web-1"]}])
        rules.see(name="web-1")
        self.assertEqual(self._report(rules), [
            f"{PATH}: 1 estate rule(s) matched nothing: web-1 (matches 'web-1', "
            "decided by 'web' above it)"])

    def test_which_goes_before_a_near_miss_in_case(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]},
                        {"name": "pinned", "names": ["WEB-2", "web-1"]}])
        rules.see(name="web-2")
        rules.see(name="web-1")
        self.assertEqual(self._report(rules), [
            f"{PATH}: 1 estate rule(s) matched nothing: pinned (matches 'web-1', "
            "decided by 'web' above it)"])

    def test_naming_each_axis_the_rule_writes(self) -> None:
        rules = _rules([{"name": "shop", "repositories": ["shop"]},
                        {"name": "deploys", "files": ["deploy.yml"]}], WORKFLOWS)
        rules.see(repositories="shop", files="deploy.yml")
        self.assertEqual(self._report(rules), [
            f"{PATH}: 1 estate rule(s) matched nothing: deploys (matches files "
            "'deploy.yml', decided by 'shop' above it)"])

    def test_an_absent_value_is_said_as_absent(self) -> None:
        # A second rule for the instances nobody named can never decide one.
        rules = _rules([{"name": "nameless", "unnamed": True},
                        {"name": "orphans", "unnamed": True}])
        rules.see(name=None)
        self.assertEqual(self._report(rules), [
            f"{PATH}: 1 estate rule(s) matched nothing: orphans (matches an absent "
            "name, decided by 'nameless' above it)"])

    def test_on_a_named_axis_beside_the_others(self) -> None:
        rules = _rules([{"name": "orphans", "owners": {"unnamed": True}},
                        {"name": "orphan deploys", "owners": {"unnamed": True},
                         "files": ["deploy.yml"]},
                        {"name": "orphan builds", "owners": {"unnamed": True},
                         "files": ["Build.yml"]}], OWNED)
        rules.see(owners=None, files="deploy.yml")
        rules.see(owners=None, files="build.yml")
        self.assertEqual(self._report(rules), [
            f"{PATH}: 2 estate rule(s) matched nothing: orphan deploys (matches owners "
            "absent, files 'deploy.yml', decided by 'orphans' above it), orphan builds "
            "(would match owners absent, files 'build.yml' with case folded)"])

    def test_the_grading_keeps_no_tally(self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]}])
        self.assertIsNotNone(rules.first(name="web-1"))
        self.assertEqual(self._report(rules),
                         [f"{PATH}: 1 estate rule(s) matched nothing: web"])

    def test_the_tally_is_the_runs_and_is_dropped_when_it_is_reported(self) -> None:
        rules = _rules([{"name": "web", "names": ["Web"]}])
        rules.see(name="web")
        self.assertEqual(self._report(rules), [
            f"{PATH}: 1 estate rule(s) matched nothing: web (would match 'web' with "
            "case folded)"])
        rules.see(name="Web")
        self.assertEqual(self._report(rules),
                         [f"{PATH}: every estate rule now matches something"])
        # Nothing seen this run: last run's values are gone, and so is the hint.
        self.assertEqual(self._report(rules),
                         [f"{PATH}: 1 estate rule(s) matched nothing: web"])

    def test_a_run_that_read_part_of_its_scope_leaves_the_set_as_it_was(
            self) -> None:
        rules = _rules([{"name": "web", "prefixes": ["web-"]},
                        {"name": "db", "prefixes": ["db-"]}])
        rules.see(name="web-1")
        self._report(rules)
        # The source that holds the web instances did not answer.
        self.assertEqual(self._report(rules, whole=False), [])
        rules.see(name="web-1")
        self.assertEqual(self._report(rules), [])
        # Nor does a part read carry its tally into the next run.
        rules.see(name="db-1")
        self.assertEqual(self._report(rules, whole=False), [])
        rules.see(name="web-1")
        self.assertEqual(self._report(rules), [])

    def test_a_list_with_no_rules_says_nothing(self) -> None:
        rules = _rules(None)
        self.assertIsNone(rules.see(name="web-1"))
        self.assertEqual(self._report(rules), [])


FORMS: dict[str, object] = {
    "instances.name": {
        "sentence": "The instances under one name, and how many there are.",
        "text": "{name}: {count} instance(s){? — rule {line.rule}}"}}
WORDS: dict[str, object] = {
    RULE_WORD: {"sentence": "The rule whose own keys judged the line, where one did.",
                "example": "web-fleet"}}
FIELDS: dict[str, object] = {
    "name": {"sentence": "The instances' Name tag.", "example": "web-1"},
    "count": {"sentence": "How many instances carry it.", "example": 2}}


class _Estate(Check):
    """A type whose rules judge, declaring the word as a package would."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(line_forms=FORMS, line_words=WORDS, line_fields=FIELDS,
                         **kwargs)

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class RuleWordTests(TestCase):
    """Decision 6: the owning rule's name is the word ``rule``; a type whose rules can
    judge declares it and hands it over on every line a rule owns, and on a line no
    rule owns the word is absent and the segment that prints it leaves itself out."""

    def setUp(self) -> None:
        self.check = _Estate.from_config({"path": "/estate"}, Path("."))
        self.reading = Measurement(record={"name": "web-1", "count": 2},
                                   subject="web-1")

    def test_the_owning_rules_name_is_the_word_rule(self) -> None:
        self.assertEqual(RULE_WORD, "rule")
        rule = _rules([{"name": "web-fleet", "prefixes": ["web-"]}]
                      ).first(name="web-1")
        assert rule is not None
        entry = self.check.line("instances.name", self.reading, slug="web-1",
                                words={RULE_WORD: rule.name})
        self.assertEqual(entry.text, "web-1: 2 instance(s) — rule web-fleet")

    def test_on_a_line_no_rule_owns_the_segment_leaves_itself_out(self) -> None:
        entry = self.check.line("instances.name", self.reading, slug="web-1")
        self.assertEqual(entry.text, "web-1: 2 instance(s)")
