"""The configured rules as a start reads them (ADR-0137): ``config/aggregation.yaml``
in every configuration root, the root named last first, each file in its order; what
a rule is, where it acts, and every way a rule fails to apply — named on the startup
record, one line a rule, the monitor going on without it.

What a rule does to a count is the tree's, and `tests/test_aggregation_tree.py`'s.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import textwrap
from datetime import date
from pathlib import Path
from unittest import TestCase

from little_sister import self_report
from little_sister.aggregation import (
    ALL,
    AggregationRule,
    RuleSet,
    Table,
    load_rules,
    read_rules,
)
from little_sister.codes import StatusCode
from little_sister.config_dir import ASPECTS

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
TODAY = date(2026, 10, 24)

#: A rule every test may start from: it applies as it stands.
GOOD = """
  - name: develop advises
    under: /aws/develop
    counts_as: {ERROR: WARN}
    note: The develop account is no production; it advises.
    since: 2026-10-24
"""


class _RulesCase(TestCase):
    """Rule files in temporary roots, and the startup record emptied around each
    test."""

    def setUp(self) -> None:
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        self.roots: list[Path] = []

    def root(self, text: str | None) -> Path:
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        if text is not None:
            (directory / "aggregation.yaml").write_text(textwrap.dedent(text))
        self.roots.append(directory)
        return directory

    def read(self, *texts: str, check_roots: tuple[str, ...] = ()) -> RuleSet:
        for text in texts:
            self.root("rules:\n" + text)
        return read_rules([(root / "aggregation.yaml", root) for root in self.roots
                           if (root / "aggregation.yaml").exists()],
                          check_roots=check_roots, today=TODAY)

    @staticmethod
    def noted() -> list[str]:
        """The startup record's lines on the rules, as they read: the record holds
        them as plain text escaped for Markdown."""
        return [re.sub(r"\\(.)", r"\1", line.text)
                for line in self_report.startup.lines()
                if line.slug.startswith("aggregation")]

    def refused(self, rule: str, *words: str) -> None:
        """The rule does not apply, and its one line names every word."""
        rules = self.read(rule)
        self.assertEqual(rules.rules, ())
        lines = self.noted()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("does not apply", lines[0])
        for word in words:
            self.assertIn(word, lines[0])


class AcceptedTests(_RulesCase):
    """What a rule writes, read as it is meant."""

    def test_the_cap_on_a_part(self):
        rule, = self.read(GOOD).rules
        self.assertEqual((rule.name, rule.under, rule.segments, rule.level),
                         ("develop advises", "/aws/develop", ("aws", "develop"),
                          "node"))
        self.assertEqual(rule.table.counts(ERROR), WARN)
        self.assertEqual(rule.table.counts(WARN), WARN)
        self.assertEqual(rule.table.counts(OK), OK)
        self.assertEqual(rule.since, date(2026, 10, 24))
        self.assertEqual(rule.note, "The develop account is no production; it advises.")
        self.assertEqual(self.noted(), [])

    def test_the_table_reads_codes_in_either_case(self):
        rule, = self.read("""
  - name: ec2 heals
    under: /aws/*/ec2
    lines: "*"
    counts_as: {warn: Ok}
    note: Yellow instances are the day's weather.
    since: 2026-10-01
""").rules
        self.assertEqual(rule.level, "lines")
        self.assertEqual(rule.lines, (ALL,))
        self.assertEqual(rule.table.spelled, "{WARN: OK}")

    def test_nothing_leaves_the_part_out_whatever_it_reports(self):
        rule, = self.read(GOOD.replace("{ERROR: WARN}", "Nothing")).rules
        self.assertTrue(rule.table.left_out)
        for code in (OK, WARN, ERROR):
            self.assertIsNone(rule.table.counts(code))
        # maintenance and a part not yet reported count nothing already
        self.assertIs(rule.table.counts(StatusCode.MAINTENANCE),
                      StatusCode.MAINTENANCE)

    def test_the_empty_table_is_every_status_as_itself(self):
        rule, = self.read(GOOD.replace("{ERROR: WARN}", "{}")).rules
        self.assertEqual([rule.table.counts(code) for code in (OK, WARN, ERROR)],
                         [OK, WARN, ERROR])

    def test_a_count_over_lines_and_one_over_children(self):
        lines, children = self.read("""
  - name: wiz counts ten
    under: /wiz/medium
    lines: "*"
    counts_as: {ERROR: WARN}
    while_fewer_than: 10
    note: A band counts once it holds ten.
    since: 2026-10-20
  - name: replicas
    under: /web
    children: [a, b, c]
    counts_as: {WARN: OK, ERROR: OK}
    while_fewer_than: 2
    note: One replica down is expected.
    since: 2026-10-20
""").rules
        self.assertEqual((lines.level, lines.count), ("lines", 10))
        self.assertEqual((children.level, children.children, children.count),
                         ("children", ("a", "b", "c"), 2))

    def test_named_lines_keep_their_order_once(self):
        rule, = self.read("""
  - name: two lines
    under: /db/pool
    lines: [primary, replica, primary]
    counts_as: {WARN: OK}
    note: n
    since: 2026-10-20
""").rules
        self.assertEqual(rule.lines, ("primary", "replica"))
        self.assertTrue(rule.names_line("replica"))
        self.assertFalse(rule.names_line("arbiter"))

    def test_the_last_named_root_first_then_each_file_in_order(self):
        rules = self.read(GOOD + """
  - name: base second
    under: /aws
    counts_as: {ERROR: WARN}
    note: n
    since: 2026-10-01
""", """
  - name: site first
    under: /aws/sandbox
    counts_as: nothing
    note: n
    since: 2026-10-01
""")
        self.assertEqual([rule.name for rule in rules.rules],
                         ["site first", "develop advises", "base second"])
        self.assertEqual([rule.order for rule in rules.rules], [0, 1, 2])
        self.assertEqual(rules.rules[0].root, self.roots[1])

    def test_load_rules_reads_every_root_of_the_path_list(self):
        base = self.root("rules:\n" + GOOD)
        site = self.root(None)
        rules = load_rules(f"{base}:{site}", today=TODAY)
        self.assertEqual([rule.name for rule in rules.rules], ["develop advises"])
        self.assertEqual(rules.rules[0].file, base / "aggregation.yaml")

    def test_it_is_an_aspect_of_one_file(self):
        aspect = ASPECTS["aggregation"]
        self.assertTrue(aspect.as_file)
        self.assertFalse(aspect.as_directory)

    def test_an_empty_or_missing_file_applies_nothing(self):
        self.root("")
        self.root("rules: []\n")
        self.assertEqual(self.read().rules, ())
        self.assertEqual(self.noted(), [])

    def test_a_rule_names_its_name_case_folded(self):
        rules = self.read(GOOD)
        self.assertIs(rules.named("DEVELOP Advises"), rules.rules[0])


class WhereTests(_RulesCase):
    """Where a rule acts: a node rule and a count over children at each part's top,
    a rule on lines at every node it picks, ``*`` one whole segment, and never the
    instance's own branch."""

    def test_a_node_rule_acts_at_the_top_of_its_part(self):
        rules = self.read(GOOD)
        self.assertIsNotNone(rules.boundary("/aws/develop"))
        self.assertIsNone(rules.boundary("/aws/develop/lambda"))
        self.assertIsNone(rules.boundary("/aws"))
        self.assertIsNone(rules.boundary("/aws/developer"))

    def test_a_star_is_one_segment_and_picks_each_part(self):
        rules = self.read(GOOD.replace("/aws/develop", "/aws/*"))
        for path in ("/aws/develop", "/aws/prod"):
            self.assertIsNotNone(rules.boundary(path), path)
        self.assertIsNone(rules.boundary("/aws"))
        self.assertIsNone(rules.boundary("/aws/prod/ec2"))

    def test_a_lines_rule_acts_on_every_node_it_picks(self):
        rules = self.read("""
  - name: ec2 heals
    under: /aws/*/ec2
    lines: "*"
    counts_as: {WARN: OK}
    note: n
    since: 2026-10-01
""")
        self.assertEqual(len(rules.on_lines("/aws/prod/ec2")), 1)
        self.assertEqual(len(rules.on_lines("/aws/prod/ec2/i-1")), 1)
        self.assertEqual(rules.on_lines("/aws/prod"), ())

    def test_the_instance_s_own_branch_is_left_out_by_a_broad_rule(self):
        rules = self.read(GOOD.replace("/aws/develop", "/*") + """
  - name: every line
    under: /
    lines: "*"
    counts_as: {WARN: OK}
    note: n
    since: 2026-10-01
""")
        self.assertIsNotNone(rules.boundary("/aws"))
        self.assertIsNone(rules.boundary("/little-sister"))
        self.assertEqual(rules.on_lines("/little-sister/state"), ())
        self.assertEqual(len(rules.on_lines("/aws/prod")), 1)
        self.assertEqual(self.noted(), [])

    def test_what_picks_a_place_is_listed_in_order(self):
        rules = self.read(GOOD + """
  - name: develop counts nothing
    under: /aws/develop
    counts_as: nothing
    note: n
    since: 2026-10-01
  - name: develop lines
    under: /aws
    lines: "*"
    counts_as: {WARN: OK}
    note: n
    since: 2026-10-01
""")
        self.assertEqual([rule.name for rule in rules.picking("/aws/develop")],
                         ["develop advises", "develop counts nothing",
                          "develop lines"])
        self.assertEqual(rules.boundary("/aws/develop").name, "develop advises")

    def test_a_path_with_case_folded_is_a_near_miss(self):
        rule, = self.read(GOOD).rules
        self.assertTrue(rule.would_pick_folded(("aws", "Develop")))
        self.assertFalse(rule.would_pick_folded(("aws", "develop")))
        self.assertFalse(rule.would_pick_folded(("aws", "prod")))


class RefusedTests(_RulesCase):
    """Every way a rule fails to apply: it does not, and the startup record says why
    — one line a rule, every reason in it (ADR-0032 rule 7)."""

    def test_a_key_a_rule_does_not_know(self):
        self.refused(GOOD + "    whilefewerthan: 10\n", "whilefewerthan")

    def test_each_key_a_rule_must_write(self):
        for key in ("name", "under", "counts_as", "note", "since"):
            with self.subTest(key):
                self_report.startup.forget()
                self.roots.clear()
                text = "\n".join(line for line in GOOD.splitlines()
                                 if not line.strip().startswith(f"{key}:")
                                 and not line.strip().startswith(f"- {key}:"))
                if key == "name":
                    text = text.replace("    under:", "  - under:", 1)
                self.refused(text + "\n", f"has no `{key}:`")

    def test_a_day_still_to_come_a_moment_and_no_date(self):
        for since, words in (("2026-10-25", "a day still to come"),
                             ("2026-10-24T10:00:00", "a moment"),
                             ("'yesterday'", "which is no date")):
            with self.subTest(since):
                self_report.startup.forget()
                self.roots.clear()
                self.refused(GOOD.replace("2026-10-24", since), words)

    def test_a_table_that_reorders(self):
        self.refused(GOOD.replace("{ERROR: WARN}", "{ERROR: OK}"),
                     "a worse status counts for less than a milder one")
        self_report.startup.forget()
        self.roots.clear()
        self.refused(GOOD.replace("{ERROR: WARN}", "{WARN: ERROR, ERROR: WARN}"),
                     "a worse status counts for less")

    def test_a_table_maps_warn_and_error_to_ok_warn_or_error(self):
        for table, words in (("{OK: WARN}", "a table maps WARN and ERROR"),
                             ("{ERROR: MAINTENANCE}", "a status counts as OK"),
                             ("{ERROR: nothing}", "`counts_as: nothing`"),
                             ("[ERROR, WARN]", "it is a table such as")):
            with self.subTest(table):
                self_report.startup.forget()
                self.roots.clear()
                self.refused(GOOD.replace("{ERROR: WARN}", table), words)

    def test_a_count_needs_lines_or_children_a_table_and_two(self):
        self.refused(GOOD + "    while_fewer_than: 3\n", "nothing to count")
        for extra, words in (
                ('    lines: "*"\n    while_fewer_than: 1\n', "at least 2"),
                ('    lines: "*"\n    while_fewer_than: true\n', "at least 2")):
            with self.subTest(extra):
                self_report.startup.forget()
                self.roots.clear()
                self.refused(GOOD + extra, words)
        self_report.startup.forget()
        self.roots.clear()
        self.refused(GOOD.replace("{ERROR: WARN}", "nothing")
                     + '    lines: "*"\n    while_fewer_than: 3\n',
                     "`{WARN: OK, ERROR: OK}` says what is meant")

    def test_children_stand_only_beside_a_count(self):
        self.refused(GOOD + '    children: "*"\n', "under: /aws/develop/*")

    def test_one_rule_acts_at_one_level(self):
        self.refused(GOOD + '    lines: "*"\n    children: "*"\n'
                            '    while_fewer_than: 2\n', "one rule acts at one level")

    def test_a_line_s_address_is_the_one_its_check_gives(self):
        for lines, words in (("[h-0123456789]", "made from the line's own words"),
                             ("[web-*]", "reads as a pattern"),
                             ("primary", "\"*\" or a list of addresses"),
                             ("[]", "\"*\" or a list of addresses")):
            with self.subTest(lines):
                self_report.startup.forget()
                self.roots.clear()
                self.refused(GOOD + f"    lines: {lines}\n", words)

    def test_a_star_is_a_whole_segment(self):
        self.refused(GOOD.replace("/aws/develop", "/aws/dev*"),
                     "`*` stands for one whole segment")

    def test_the_instance_s_own_branch(self):
        self.refused(GOOD.replace("/aws/develop", "/little-sister/state"),
                     "the instance's own branch")

    def test_a_node_rule_on_the_root(self):
        self.refused(GOOD.replace("/aws/develop", "/"),
                     "the root passes nothing up")

    def test_a_name_two_rules_have_applies_for_neither(self):
        rules = self.read(GOOD, GOOD.replace("develop advises", "Develop Advises"))
        self.assertEqual(rules.rules, ())
        lines = self.noted()
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("shares its name with another rule", line)
            for root in self.roots:
                self.assertIn(str(root / "aggregation.yaml"), line)

    def test_a_part_no_check_reaches(self):
        rules = self.read(GOOD, check_roots=("/github", "/wiz"))
        self.assertEqual(rules.rules, ())
        self.assertIn("which no configured check's mount reaches", self.noted()[0])
        # a mount above the part, at it or beneath it reaches it
        for mount in ("/aws", "/aws/develop", "/aws/develop/lambda"):
            with self.subTest(mount):
                self_report.startup.forget()
                self.roots.clear()
                self.assertEqual(len(self.read(GOOD, check_roots=(mount,)).rules), 1)

    def test_every_reason_stands_in_one_line(self):
        self.refused(GOOD.replace("{ERROR: WARN}", "{ERROR: OK}").replace(
            "2026-10-24", "2027-01-01"), "a worse status", "a day still to come")

    def test_a_file_that_is_no_list_of_rules(self):
        for text, words in (("rules: {a: 1}\n", "no list"),
                            ("- a\n", "is no mapping"),
                            ("rules: [\n", "could not be read")):
            with self.subTest(text):
                self_report.startup.forget()
                self.roots.clear()
                self.root(text)
                self.assertEqual(self.read().rules, ())
                self.assertIn(words, " ".join(self.noted()))

    def test_one_bad_rule_leaves_the_others_standing(self):
        rules = self.read(GOOD + """
  - name: bad
    under: /aws
    counts_as: {ERROR: OK}
    note: n
    since: 2026-10-01
""")
        self.assertEqual([rule.name for rule in rules.rules], ["develop advises"])


class TableTests(TestCase):
    """The table alone: what a count counts."""

    def test_a_table_names_the_statuses_it_maps(self):
        cap = Table(((ERROR, WARN),))
        self.assertTrue(cap.names(ERROR))
        self.assertFalse(cap.names(WARN))
        left_out = Table(left_out=True)
        self.assertTrue(left_out.names(OK))
        self.assertFalse(left_out.names(StatusCode.UNDEFINED))

    def test_a_rule_s_key_is_its_name_folded(self):
        rule = AggregationRule(name="Develop", under="/a", segments=("a",),
                               table=Table(), note="n", since=TODAY,
                               file=Path("a.yaml"), root=Path("."))
        self.assertEqual(rule.key, "develop")


class ShippedRulesTests(_RulesCase):
    """The two rule files the repository ships: the example, which applies nothing,
    and the demo's, which applies every rule it writes against the demo's checks."""

    def test_the_example_applies_nothing_and_says_nothing(self):
        example = Path(__file__).resolve().parent.parent / "config"
        self.assertEqual(read_rules([(example / "aggregation.yaml", example)],
                                    today=TODAY).rules, ())
        self.assertEqual(self.noted(), [])

    def test_every_rule_the_example_shows_applies_once_uncommented(self):
        # the commented rules are what a deployment copies: each must apply as written
        example = Path(__file__).resolve().parent.parent / "config" / "aggregation.yaml"
        shown = [line[2:] if line.startswith("# ") else line[1:]
                 for line in example.read_text().splitlines()
                 if line.startswith("#   ") or line == "# rules:"]
        start = shown.index("rules:")
        rules = self.read("\n".join(shown[start + 1:]) + "\n")
        self.assertEqual(self.noted(), [])
        self.assertEqual(len(rules.rules), 5)
        self.assertEqual({rule.level for rule in rules.rules},
                         {"node", "lines", "children"})

    def test_the_demo_s_rules_all_apply_to_its_checks(self):
        # testing-the-gui.md, Mode 2: one rule of each kind, read as a deployment's
        # are — every part reachable from a demo check's mount, nothing on the record
        import tests.demo_check  # noqa: F401  (registers the `demo` type)
        from little_sister.checks import load_checks
        demo = Path(__file__).resolve().parent / "demo_config"
        mounts = [check.path for check in load_checks(demo)]
        rules = read_rules([(demo / "aggregation.yaml", demo)], check_roots=mounts,
                           today=TODAY)
        self.assertEqual(self.noted(), [])
        self.assertEqual([rule.name for rule in rules.rules], [
            "nightly advises", "the gateway has no amber",
            "a waiting gate is no failure", "a short review queue",
            "one host may be down", "backfill is a one-off"])
        self.assertEqual([rule.table.spelled for rule in rules.rules], [
            "{ERROR: WARN}", "{WARN: ERROR}", "{WARN: OK}", "{WARN: OK}",
            "{ERROR: WARN}", "nothing"])
