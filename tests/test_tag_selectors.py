"""What a tag selects (ADR-0139 decisions 5 and 7): `tag:` beside `under:` in a
configured rule and in an action, `?tag=` on the Events page, and the wall filtered
by a tag.

A selector is `under:`, `tag:` or both, both holding: a rule picks by `tag:` alone
where it writes no `under:`, and acts as before at the top of each part it picks —
where the tag begins. A `tag:` the configuration writes for no node is refused at the
start, a rule's and an action's alike. An event whose node is gone is matched by the
tags of the nearest node the tree still holds. A wall filtered by a tag draws each
topmost node that carries it as a card, the path above it before its name, names
above the cards the tag, what it means and the parts it hides that fail, and keeps
the filter in its address alone.

What a tag is, where it is written and how it comes down is `tests/test_tags.py`'s.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from werkzeug.datastructures import MultiDict

from little_sister import actions as actions_module
from little_sister import app as app_module
from little_sister import instants, self_report
from little_sister.actions import forget_actions, load_actions
from little_sister.aggregation import ALL, RuleSet, day_begins, read_rules
from little_sister.event_filter import FilterRefused, read_filter
from little_sister.rule_words import rule_said
from little_sister.status import StatusCode
from little_sister.tags import Vocabulary
from little_sister.tree import (
    Event,
    StatusTree,
    events_from_payload,
    nodes_from_payload,
)
from tests.page_tree import Element, parse
from tests.test_aggregation import GOOD, TODAY, _RulesCase
from tests.test_aggregation_tree import CAP, HEAL, QUIET, child, coded, node, rule

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
UNDEFINED = StatusCode.UNDEFINED


def tagged(name: str, tag: str, counts_as: dict[StatusCode, StatusCode] | None, *,
           under: str = "", **kwargs: object):
    """A rule as a start accepts one that writes ``tag:``, and ``under:`` beside it
    where one is given."""
    return replace(rule(name, under, counts_as, **kwargs), tag=tag)  # type: ignore


def ruled(*rules, tags: dict[str, tuple[str, ...]]) -> StatusTree:
    """A tree that reads ``rules`` and writes ``tags`` by path, as a start hands
    them over — the tags first."""
    tree = StatusTree()
    tree.use_tags(Vocabulary({}), tags)
    tree.use_aggregation(RuleSet(rules))
    return tree


# --- a rule's `tag:` as the start reads it -------------------------------------------


class RuleReadTests(_RulesCase):
    """`tag:` joins the selector: a rule writes `under:`, `tag:` or both."""

    def test_a_rule_may_pick_by_a_tag_alone_capitals_read_as_lower_case(self):
        rule_, = self.read(GOOD.replace("under: /aws/develop", "tag: Develop")).rules
        self.assertEqual((rule_.tag, rule_.under, rule_.segments, rule_.level),
                         ("develop", "", (), "node"))
        self.assertEqual(rule_.selector, "what carries develop")
        self.assertEqual(self.noted(), [])

    def test_under_and_tag_together(self):
        rule_, = self.read(GOOD.replace("under: /aws/develop",
                                        "under: /aws\n    tag: develop")).rules
        self.assertEqual((rule_.tag, rule_.under), ("develop", "/aws"))
        self.assertEqual(rule_.selector, "what carries develop under /aws")
        # and one that writes no tag is said by its path, as before
        self.assertEqual(rule("plain", "/aws/develop", CAP).selector, "/aws/develop")

    def test_neither_is_refused_as_picking_nothing(self):
        self.refused(GOOD.replace("    under: /aws/develop\n", ""),
                     "has no `under:` and no `tag:`, so it picks nothing")

    def test_a_tag_that_is_no_tag_is_refused_and_asks_for_no_under(self):
        self.refused(GOOD.replace("under: /aws/develop", "tag: rack 4"),
                     "writes `tag: rack 4`, which is no tag: one tag, lowercase "
                     "letters and digits with hyphens between them")
        self.assertNotIn("under:", self.noted()[0])

    def test_a_tag_the_configuration_writes_for_no_node_is_refused(self):
        text = "rules:\n" + GOOD.replace("under: /aws/develop", "tag: develop")
        root = self.root(text)
        files = [(root / "aggregation.yaml", root)]
        refused = read_rules(files, tags={"production"}, today=TODAY)
        self.assertEqual(refused.rules, ())
        line, = self.noted()
        self.assertIn("picks what carries develop, a tag the configuration writes "
                      "for no node — a typo in the tag, or a tag no longer written",
                      line)
        self_report.startup.forget()
        # held to the tags written, and to none where the start hands over none
        self.assertEqual(len(read_rules(files, tags={"develop"}, today=TODAY).rules),
                         1)
        self.assertEqual(len(read_rules(files, today=TODAY).rules), 1)
        self.assertEqual(self.noted(), [])

    def test_a_tag_alone_is_held_to_no_checks_mount(self):
        rules = self.read(GOOD.replace("under: /aws/develop", "tag: develop"),
                          check_roots=("/web",))
        self.assertEqual(len(rules.rules), 1)
        self.assertEqual(self.noted(), [])

    def test_children_without_a_count_by_a_tag_alone_says_what_is_meant(self):
        self.refused(GOOD.replace("under: /aws/develop",
                                  'tag: develop\n    children: "*"'),
                     "writes `children:` without `while_fewer_than:`; without a count "
                     "a rule acts on what each part it picks passes up, and writes no "
                     "`children:`")

    def test_a_rule_by_a_tag_is_no_rule_on_the_root(self):
        # a rule with `under: /` alone acts on what the root passes up, and is
        # refused; one by a tag acts where the tag begins, which is never the root
        # unless the root carries it
        rules = self.read(GOOD.replace("under: /aws/develop", "under: /\n    tag: dev"))
        self.assertEqual(len(rules.rules), 1)


# --- what a rule by a tag does to a count --------------------------------------------


class RuleTreeTests(TestCase):
    """A rule by a tag acts at the top of each part it picks: where the tag begins."""

    def test_it_acts_where_the_tag_begins_and_only_there(self):
        tree = ruled(tagged("develop advises", "develop", CAP),
                     tags={"/aws/develop": ("develop",)})
        tree.upsert("/aws/develop/lambda/fn", ERROR, "timed out")
        tree.upsert("/aws/live/ec2", OK)
        develop = node(tree, "/aws/develop")
        self.assertIs(develop.code, ERROR)
        self.assertIs(develop.counted, WARN)
        self.assertEqual(develop.rule.rule.name, "develop advises")
        # beneath where it begins every node carries it, and passes up as it is
        self.assertIsNone(node(tree, "/aws/develop/lambda").rule)
        self.assertIs(node(tree, "/aws/develop/lambda").counted, ERROR)
        self.assertIs(node(tree, "/aws").code, WARN)

    def test_each_part_the_tag_is_written_for_is_a_part_of_its_own(self):
        tree = ruled(tagged("develop advises", "develop", CAP),
                     tags={"/aws/develop": ("develop",), "/gcp/sandbox": ("develop",)})
        tree.upsert("/aws/develop/fn", ERROR, "x")
        tree.upsert("/gcp/sandbox/vm", ERROR, "y")
        for path in ("/aws/develop", "/gcp/sandbox"):
            self.assertIs(node(tree, path).counted, WARN, path)
        self.assertIs(node(tree, "/").code, WARN)

    def test_under_and_tag_both_hold(self):
        tree = ruled(tagged("aws develop advises", "develop", CAP, under="/aws"),
                     tags={"/aws/develop": ("develop",), "/gcp/sandbox": ("develop",)})
        tree.upsert("/aws/develop/fn", ERROR, "x")
        tree.upsert("/gcp/sandbox/vm", ERROR, "y")
        self.assertIs(node(tree, "/aws/develop").counted, WARN)
        self.assertIsNone(node(tree, "/gcp/sandbox").rule)
        self.assertIs(node(tree, "/gcp/sandbox").counted, ERROR)
        self.assertIs(node(tree, "/").code, ERROR)

    def test_a_tag_written_above_the_node_under_names_tops_it_there(self):
        tree = ruled(tagged("ec2 advises", "develop", CAP, under="/aws/develop/ec2"),
                     tags={"/aws": ("develop",)})
        tree.upsert("/aws/develop/ec2/i-1", ERROR, "x")
        self.assertIs(node(tree, "/aws/develop/ec2").counted, WARN)
        self.assertIsNone(node(tree, "/aws/develop/ec2/i-1").rule)
        self.assertIsNone(node(tree, "/aws").rule)

    def test_on_the_lines_of_every_node_that_carries_it(self):
        tree = ruled(tagged("weather", "develop", HEAL, lines=[ALL]),
                     tags={"/aws/develop": ("develop",)})
        coded(tree, "/aws/develop/ec2", i1=WARN, i2=OK)
        coded(tree, "/aws/live/ec2", i1=WARN)
        self.assertIs(node(tree, "/aws/develop/ec2").code, OK)
        self.assertIs(node(tree, "/aws/live/ec2").code, WARN)

    def test_a_count_over_the_children_where_the_tag_begins(self):
        tree = ruled(tagged("replicas", "web", QUIET, children=[ALL], count=2),
                     tags={"/web": ("web",)})
        tree.upsert("/web/a", ERROR, "down")
        tree.upsert("/web/b", OK)
        web = node(tree, "/web")
        self.assertIs(web.code, OK)
        self.assertIs(child(web, "a").code, ERROR)
        self.assertEqual(web.children_rule.failing, 1)

    def test_tags_a_run_writes_start_the_answers_over(self):
        tree = ruled(tagged("serverless advises", "serverless", CAP),
                     tags={})
        tree.upsert("/aws/live/lambda/fn", ERROR, "timed out")
        self.assertIsNone(node(tree, "/aws/live/lambda").rule)   # asked, remembered
        # an aspect's name given tags under `subnodes:`, written as the run writes it
        tree.upsert("/aws/live/lambda", UNDEFINED, named_tags=("serverless",))
        lambda_ = node(tree, "/aws/live/lambda")
        self.assertIs(lambda_.counted, WARN)
        self.assertEqual(lambda_.rule.rule.name, "serverless advises")

    def test_a_path_written_for_is_picked_before_its_node_stands(self):
        tree = ruled(tagged("develop advises", "develop", CAP),
                     tags={"/aws/develop": ("develop",)})
        # asked before a run makes the node — as the past a restart reads asks
        self.assertIsNotNone(tree.rules.boundary("/aws/develop"))
        self.assertEqual(tree.tags_of("/aws/develop/fn"), ("develop",))
        tree.upsert("/aws/develop/fn", ERROR, "x")
        self.assertIs(node(tree, "/aws/develop").counted, WARN)

    def test_a_node_given_tags_by_its_name_takes_them_when_it_leaves(self):
        tree = ruled(tagged("serverless advises", "serverless", CAP), tags={})
        tree.upsert("/aws/live/lambda", UNDEFINED, named_tags=("serverless",))
        tree.upsert("/aws/live/lambda/fn", ERROR, "timed out")
        self.assertIs(node(tree, "/aws/live/lambda").counted, WARN)
        tree.prune("/aws/live", keep=())
        # a node at its path again, no aspect's name giving it the tag
        tree.upsert("/aws/live/lambda/fn", ERROR, "timed out")
        self.assertIsNone(node(tree, "/aws/live/lambda").rule)
        self.assertIs(node(tree, "/aws/live/lambda").counted, ERROR)

    def test_the_tags_handed_over_after_the_rules_start_them_over_too(self):
        tree = StatusTree()
        tree.use_aggregation(RuleSet([tagged("develop advises", "develop", CAP)]))
        tree.upsert("/aws/develop/fn", ERROR, "x")
        self.assertIsNone(node(tree, "/aws/develop").rule)
        tree.use_tags(Vocabulary({}), {"/aws/develop": ("develop",)})
        self.assertIs(node(tree, "/aws/develop").counted, WARN)

    def test_one_set_two_trees_each_by_its_own_tags(self):
        rules = RuleSet([tagged("develop advises", "develop", CAP)])
        first, second = StatusTree(), StatusTree()
        first.use_tags(Vocabulary({}), {"/a": ("develop",)})
        for tree in (first, second):
            tree.use_aggregation(rules)
            tree.upsert("/a/fn", ERROR, "x")
        self.assertIs(node(first, "/a").counted, WARN)
        self.assertIs(node(second, "/a").counted, ERROR)

    def test_an_answer_worked_out_across_a_change_is_not_remembered(self):
        carried = {"/aws/develop": {"develop"}}
        asked: list[str] = []

        def tags_of(path: str) -> frozenset[str]:
            asked.append(path)
            if len(asked) == 1:
                # what a node carries changes while the answer is worked out
                bound.forget()
            return frozenset(carried.get(path, ()))

        bound = RuleSet([tagged("develop advises", "develop", CAP)]).bound(tags_of)
        self.assertIsNotNone(bound.boundary("/aws/develop"))
        carried.clear()
        self.assertIsNone(bound.boundary("/aws/develop"))
        # and an answer worked out with nothing changing is remembered
        asked.clear()
        self.assertIsNone(bound.boundary("/aws/develop"))
        self.assertEqual(asked, [])


class ReplayTests(TestCase):
    """The past is read with a rule by a tag as with any rule, from its day
    (ADR-0137 decision 11), by what the restarted tree's nodes carry."""

    def setUp(self) -> None:
        self.wall = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
        patched = mock.patch.object(instants, "now", lambda: self.wall)
        patched.start()
        self.addCleanup(patched.stop)

    def test_a_rule_by_a_tag_begins_in_the_past_at_its_day(self):
        tree = StatusTree()
        first = self.wall
        tree.upsert("/aws/develop", OK)
        tree.upsert("/aws/prod", OK)
        tree.upsert("/lab/rig", OK)
        self.wall = broke = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
        tree.upsert("/aws/develop", ERROR, "timed out")
        # the instance restarts on two rules two days later, its tags handed over
        # first, as a start hands them: one rule standing since the day after the
        # failure, the other since the day after that
        self.wall = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        payload = json.loads(json.dumps(tree.events_payload()))
        new = StatusTree()
        new.use_tags(Vocabulary({}), {"/aws/develop": ("develop",), "/lab": ("lab",)})
        advises = replace(tagged("develop advises", "develop", CAP),
                          since=date(2026, 10, 21))
        new.use_aggregation(RuleSet([advises, replace(
            tagged("lab is out", "lab", None), since=date(2026, 10, 22))]))
        new.restore_events(events_from_payload(payload), nodes_from_payload(payload))
        new.upsert("/aws/develop", ERROR, "timed out")
        new.upsert("/aws/prod", OK)
        new.upsert("/lab/rig", OK)
        self.wall = fixed = datetime(2026, 10, 22, 13, 0, tzinfo=UTC)
        new.upsert("/aws/develop", OK)
        began = day_begins(advises.since)
        ended, current = new.shown_history("/aws")
        assert current is not None
        self.assertEqual((current.code, current.began.at), (OK, fixed))
        self.assertEqual([(period.code, period.began.at, period.until)
                          for period in ended],
                         [(WARN, began, fixed), (ERROR, broke, began),
                          (OK, first, broke)])


class RuleWordsTests(TestCase):
    """*Handled* names what a rule by a tag picks by its tag."""

    def test_a_selector_owns_nothing(self):
        heals = tagged("weather", "develop", HEAL, under="/aws", lines=[ALL])
        self.assertEqual(rule_said(heals, "lines", failing=None, path=heals.selector),
                         "On the lines of **what carries develop under /aws**, "
                         "{warn} counts as {ok}, by the rule **weather**")
        caps = tagged("develop advises", "develop", CAP)
        self.assertEqual(rule_said(caps, "node", failing=None, path=caps.selector),
                         "**What carries develop**: {error} counts as {warn} above, "
                         "by the rule **develop advises**")
        quorum = tagged("replicas", "web", QUIET, children=[ALL], count=2)
        self.assertEqual(
            rule_said(quorum, "children", failing=None, path=quorum.selector),
            "Of the children of **what carries web**, {warn} and {error} count as "
            "{ok} while fewer than 2 fail, by the rule **replicas**")
        # a path still owns what it picks
        plain_ = rule("develop advises", "/aws/develop", CAP)
        self.assertEqual(rule_said(plain_, "node", failing=None, path=plain_.selector),
                         "**/aws/develop**: {error} counts as {warn} above, by the "
                         "rule **develop advises**")


# --- an action's `tag:` --------------------------------------------------------------


def _actions_root(directory: str, body: str) -> Path:
    root = Path(directory)
    (root / "checks").mkdir(parents=True, exist_ok=True)
    (root / "actions.yaml").write_text(body, encoding="utf-8")
    return root


def _action(*extra: str) -> str:
    return ("actions:\n  - label: Page the owner\n    slot: node.actions\n"
            "    url: https://pager.example.org/new?n={path}\n"
            + "".join(f"    {line}\n" for line in extra))


class ActionTests(TestCase):
    """An action is offered on what carries its tag, and under `under:` where both
    are written."""

    def setUp(self) -> None:
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        actions_module.use_tags(None)
        self.addCleanup(actions_module.use_tags, None)

    def _load(self, body: str):
        with tempfile.TemporaryDirectory() as directory:
            return load_actions(_actions_root(directory, body))

    @staticmethod
    def noted() -> list[str]:
        """The startup record's lines on the actions, as they read: the record holds
        them as plain text escaped for Markdown."""
        return [re.sub(r"\\(.)", r"\1", line.text)
                for line in self_report.startup.lines()
                if line.slug.startswith("actions")]

    def test_offered_on_what_carries_the_tag(self):
        action, = self._load(_action("tag: Production"))
        self.assertEqual(action.tag, "production")
        self.assertTrue(action.applies_to("/web/api", ("production", "edge")))
        self.assertFalse(action.applies_to("/web/api", ("edge",)))
        self.assertFalse(action.applies_to("/web/api"))

    def test_under_and_tag_both_hold(self):
        action, = self._load(_action("under: /web", "tag: production"))
        self.assertTrue(action.applies_to("/web/api", ("production",)))
        self.assertFalse(action.applies_to("/db", ("production",)))
        self.assertFalse(action.applies_to("/web/api", ()))

    def test_a_tag_that_is_no_tag_drops_the_action_and_says_why(self):
        self.assertEqual(self._load(_action("tag: rack 4")), ())
        line, = self.noted()
        self.assertIn("action #1 writes tag: rack 4, which is no tag", line)

    def test_a_tag_the_configuration_writes_for_no_node_drops_the_action(self):
        actions_module.use_tags({"production"})
        self.assertEqual(self._load(_action("tag: develop")), ())
        line, = self.noted()
        self.assertIn("is offered on what carries develop, a tag the configuration "
                      "writes for no node", line)
        self.assertEqual(len(self._load(_action("tag: production"))), 1)

    def test_the_page_offers_it_on_the_nodes_that_carry_it(self):
        app_module.app.config["TESTING"] = True
        original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", original)
        tree = StatusTree()
        app_module.status_tree = tree
        tree.upsert("/web/api", ERROR, "down")
        tree.upsert("/db", ERROR, "refused")
        tree.use_tags(Vocabulary({}), {"/web": ("production",)})
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = _actions_root(directory.name, _action("tag: production"))
        with mock.patch.dict(os.environ, {"LITTLE_SISTER_CONFIG_DIR": str(root)}):
            forget_actions()
            client = app_module.app.test_client()
            client.post("/login", data={"username": "pan", "password": "12345678"})
            self.assertIn("Page the owner", client.get("/status/web/api").get_data(
                as_text=True))
            self.assertNotIn("Page the owner", client.get("/status/db").get_data(
                as_text=True))
        forget_actions()


# --- the start: what a selector's tag is held to -------------------------------------


class StartupTests(TestCase):
    """The start hands the rules and the actions the tags the configuration writes,
    and a selector of a tag nobody writes is a line on the startup record."""

    def setUp(self) -> None:
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        self.addCleanup(actions_module.use_tags, None)
        original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", original)
        self.tree = StatusTree()
        app_module.status_tree = self.tree

    def test_a_rule_and_an_action_of_a_tag_nobody_writes_are_named(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nodes.yaml").write_text("/web:\n  tags: [production]\n")
            (root / "aggregation.yaml").write_text(
                "rules:\n" + GOOD.replace("under: /aws/develop", "tag: develop")
                + GOOD.replace("develop advises", "production advises").replace(
                    "under: /aws/develop", "tag: production"))
            _actions_root(directory, _action("tag: develop"))
            engine = mock.Mock(checks=[], check_roots=mock.Mock(return_value=()))
            with mock.patch.dict(os.environ, {"LITTLE_SISTER_CONFIG_DIR": directory}):
                app_module._seed_tags(engine, app_module._read_nodes())
                app_module._load_aggregation(engine)
                forget_actions()
                self.assertEqual(actions_module.current_actions(), ())
            forget_actions()
        self.assertEqual([rule_.name for rule_ in self.tree.rules.rules],
                         ["production advises"])
        said = "\n".join(re.sub(r"\\(.)", r"\1", line.text)
                         for line in self_report.startup.lines())
        self.assertIn("picks what carries develop, a tag the configuration writes for "
                      "no node", said)
        self.assertIn("is offered on what carries develop", said)


# --- the Events page's `?tag=` -------------------------------------------------------

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)


def _event(minutes: float, path: str, new: StatusCode, reason: str) -> Event:
    return Event(path=path, name=path.rsplit("/", 1)[-1], old=OK, new=new,
                 reason=(reason,), timestamp=T0 + timedelta(minutes=minutes))


class EventsTests(TestCase):
    """`?tag=` lists the changes of the nodes that carry it, beside `?under=`."""

    def setUp(self) -> None:
        original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", original)
        self.tree = StatusTree()
        for path in ("/hosts/nas/disk", "/hosts/web", "/svc/backup"):
            self.tree.upsert(path, OK)
        self.tree.use_tags(Vocabulary({"storage": "Keeps the files.", "lab": ""}),
                           {"/hosts": ("lab",), "/hosts/nas": ("storage",),
                            "/hosts/nas/old": ("archive",)})
        self.tree.restore_events((
            _event(0, "/hosts/nas", ERROR, "nas down"),
            _event(10, "/hosts/nas/disk", WARN, "disk filling"),
            _event(20, "/hosts/nas/old", UNDEFINED, "old share removed"),
            _event(30, "/hosts/web", ERROR, "web down"),
            _event(40, "/svc/backup", WARN, "backup slow"),
        ))
        app_module.status_tree = self.tree
        clock = mock.patch.object(app_module, "_now",
                                  return_value=T0 + timedelta(minutes=60))
        clock.start()
        self.addCleanup(clock.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def reasons(self, url: str) -> list[str]:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        page = parse(response.get_data(as_text=True))
        return [row.all(tag="td")[3].text() for row in page.all(tag="tr")
                if row.attrs.get("class", "").startswith("row-")]

    def test_the_changes_of_the_nodes_that_carry_it(self):
        # a node gone is matched by the nearest node above it the tree holds
        self.assertEqual(self.reasons("/events?tag=storage"),
                         ["old share removed", "disk filling", "nas down"])
        self.assertEqual(self.reasons("/events?tag=lab"),
                         ["web down", "old share removed", "disk filling",
                          "nas down"])
        self.assertEqual(self.reasons("/events?tag=storage&under=/hosts/nas/disk"),
                         ["disk filling"])
        # and by what is written for its own path
        self.assertEqual(self.reasons("/events?tag=archive"), ["old share removed"])
        self.assertEqual(self.reasons("/events?tag=Storage"),
                         self.reasons("/events?tag=storage"))
        self.assertEqual(len(self.reasons("/events?tag=")), 5)

    def test_a_word_that_is_no_tag_is_refused(self):
        response = self.client.get("/events?tag=rack+4")
        self.assertEqual(response.status_code, 400)
        self.assertIn("filter takes one tag", response.get_data(as_text=True))
        with self.assertRaises(FilterRefused):
            read_filter(MultiDict({"tag": "rack 4"}))

    def test_the_form_offers_the_known_then_the_rest_and_submits_as_it_changes(self):
        page = parse(self.client.get("/events?tag=storage").get_data(as_text=True))
        select, = [element for element in page.all(tag="select")
                   if element.attrs.get("name") == "tag"]
        self.assertIn("data-ls-submit", select.attrs)
        self.assertEqual([(option.attrs.get("value"), option.attrs.get("title"),
                           "selected" in option.attrs)
                          for option in select.all(tag="option")],
                         [("", None, False), ("storage", "Keeps the files.", True),
                          ("lab", None, False), ("archive", None, False)])
        # one asked for that the configuration does not write is the one chosen
        page = parse(self.client.get("/events?tag=gone").get_data(as_text=True))
        select, = [element for element in page.all(tag="select")
                   if element.attrs.get("name") == "tag"]
        self.assertEqual([option.attrs.get("value") for option
                          in select.all(tag="option") if "selected" in option.attrs],
                         ["gone"])

    def test_the_bars_links_carry_it_and_nothing_remembers_it(self):
        response = self.client.get("/events?tag=storage")
        self.assertFalse([cookie for cookie in response.headers.getlist("Set-Cookie")
                          if cookie.startswith("tag=")])
        page = parse(response.get_data(as_text=True))
        bar = page.one("ls-window")
        hrefs = [link.attrs["href"] for link in bar.all(tag="a")
                 if "href" in link.attrs]
        self.assertTrue(hrefs)
        for href in hrefs:
            self.assertIn("tag=storage", href)
        self.assertEqual(len(self.reasons("/events")), 5)


# --- the wall filtered by a tag ------------------------------------------------------


class WallTests(TestCase):
    """`?tag=` draws each topmost node that carries the tag as a card."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", original)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.tree.upsert("/aws/live/ec2", OK)
        self.tree.upsert("/aws/live/lambda", ERROR, "timed out")
        self.tree.upsert("/aws/develop/ec2", ERROR, "stopped")
        self.tree.upsert("/web/api", OK)
        self.tree.upsert("/web/www", WARN, "slow")
        self.tree.upsert("/db", ERROR, "refused")
        self.tree.use_tags(
            Vocabulary({"production": "Serves customers.", "staging": "The candidate",
                        "edge": "Faces the internet?"}),
            {"/aws/live": ("production",), "/web/api": ("production", "berlin"),
             "/web/www": ("edge",)},
            written=("production", "berlin", "edge"))
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def cards(page: Element) -> list[tuple[str, str]]:
        """Each card the grid draws, by its path, with the path above it as its head
        says it."""
        return [(head.attrs["data-path"],
                 " ".join(context.text() for context
                          in head.all("status-card__context")))
                for head in page.all("status-card__head")]

    @staticmethod
    def line(page: Element) -> str:
        return page.one("ls-tag-line").text()

    def test_the_tagged_parts_are_the_cards_the_path_above_each_before_its_name(self):
        page = self.page("/status?tag=production")
        self.assertEqual(self.cards(page),
                         [("/aws/live", "aws ›"), ("/web/api", "web ›")])
        head = page.all("status-card__head")[0]
        self.assertLess(head.one("status-card__context").order,
                        head.one("status-card__name").order)

    def test_the_line_names_the_tag_what_it_means_and_the_failures_it_hides(self):
        page = self.page("/status?tag=production")
        self.assertEqual(self.line(page),
                         "Only what carries production — Serves customers. The filter "
                         "hides 3 parts that fail: /aws/develop, /db, /web/www. Every "
                         "node")
        line = page.one("ls-tag-line")
        self.assertEqual([link.attrs["href"] for link in line.all(tag="a")],
                         ["/status/aws/develop", "/status/db", "/status/web/www",
                          "/status"])
        # and it stands inside what the refresh redraws
        self.assertIn('class="ls-tag-line"', self.client.get(
            "/status?tag=production&fragment=1").get_data(as_text=True))

    def test_a_node_above_a_tagged_part_whose_own_lines_fail_is_named(self):
        self.tree.upsert("/web", WARN, "certificate expires soon")
        self.assertIn("The filter hides 4 parts that fail: /aws/develop, /db, /web, "
                      "/web/www.", self.line(self.page("/status?tag=production")))

    def test_a_line_ends_once(self):
        self.assertTrue(self.line(self.page("/status?tag=staging")).startswith(
            "Only what carries staging — The candidate. "))
        self.assertTrue(self.line(self.page("/status?tag=edge")).startswith(
            "Only what carries edge — Faces the internet? "))
        self.assertTrue(self.line(self.page("/status?tag=berlin")).startswith(
            "Only what carries berlin. "))

    def test_a_node_page_filters_what_is_beneath_it(self):
        page = self.page("/status/aws?tag=production")
        self.assertEqual(self.cards(page), [("/aws/live", "")])
        self.assertIn("The filter hides 1 part that fails: /aws/develop.",
                      self.line(page))
        self.assertEqual(page.one("ls-tag-line__all").attrs["href"], "/status/aws")

    def test_a_node_that_carries_it_keeps_everything_beneath_it(self):
        page = self.page("/status/aws/live?tag=production")
        self.assertEqual(self.cards(page), [("/aws/live/ec2", ""),
                                            ("/aws/live/lambda", "")])
        self.assertNotIn("The filter hides", self.line(page))

    def test_nothing_carries_it(self):
        self.assertIn("No node carries staging.",
                      self.client.get("/status?tag=staging").get_data(as_text=True))
        self.assertIn("Nothing beneath aws carries edge.",
                      self.client.get("/status/aws?tag=edge").get_data(as_text=True))
        # a word that is no tag is kept as written: nothing carries it, and the band
        # says it is the one chosen
        page = self.page("/status?tag=rack%204")
        self.assertEqual(self.cards(page), [])
        self.assertTrue(self.line(page).startswith("Only what carries rack 4."))
        select, = [element for element in page.all(tag="select")
                   if element.attrs.get("name") == "tag"]
        self.assertEqual([option.attrs.get("value") for option
                          in select.all(tag="option") if "selected" in option.attrs],
                         ["rack 4"])

    def test_a_word_in_the_address_is_only_ever_text(self):
        body = self.client.get("/status?tag=%3Cb%3Ex%3C/b%3E").get_data(as_text=True)
        self.assertNotIn("<b>x</b>", body)
        self.assertIn("No node carries &lt;b&gt;x&lt;/b&gt;.", body)

    def test_hide_ok_applies_within_it(self):
        page = self.page("/status?tag=Production&hide_ok=1")
        self.assertEqual(self.cards(page), [("/aws/live", "aws ›")])

    def test_the_band_offers_one_tag_at_a_time(self):
        page = self.page("/status?tag=production")
        select, = [element for element in page.all(tag="select")
                   if element.attrs.get("name") == "tag"]
        self.assertIn("data-ls-submit", select.attrs)
        self.assertEqual([(option.attrs.get("value"), option.attrs.get("title"),
                           "selected" in option.attrs)
                          for option in select.all(tag="option")],
                         [("", None, False), ("production", "Serves customers.", True),
                          ("staging", "The candidate", False),
                          ("edge", "Faces the internet?", False),
                          ("berlin", None, False)])
        # unfiltered, every node is chosen
        select, = [element for element in self.page("/status").all(tag="select")
                   if element.attrs.get("name") == "tag"]
        self.assertIn("selected", select.all(tag="option")[0].attrs)

    def test_the_filter_is_the_address_and_never_a_cookie(self):
        response = self.client.get("/status?tag=production")
        self.assertFalse([cookie for cookie in response.headers.getlist("Set-Cookie")
                          if cookie.startswith("tag=")])
        page = self.page("/status")
        self.assertEqual(page.all("ls-tag-line"), [])
        self.assertIn(("/db", ""), self.cards(page))

    def test_the_kiosk_says_it_and_has_no_way_back(self):
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        line = self.page("/status?tag=production").one("ls-tag-line")
        self.assertEqual(line.all("ls-tag-line__all"), [])
        self.assertIn("Only what carries production", line.text())

    def test_a_tag_on_the_about_card_leads_to_the_wall_filtered(self):
        chips = self.page("/status/web/api").one("ls-node-about__tags")
        self.assertEqual([link.attrs["href"] for link in chips.all(tag="a")],
                         ["/status?tag=production", "/status?tag=berlin"])

    def test_a_deployment_that_writes_no_tag_offers_none(self):
        self.tree.use_tags(Vocabulary({}), {})
        page = self.page("/status")
        self.assertEqual([element for element in page.all(tag="select")
                          if element.attrs.get("name") == "tag"], [])


class HandledTests(TestCase):
    """*Handled* names a rule by a tag by what it picks, counts the places it picks
    where the tag begins, and says so of one that picks nothing now."""

    def test_by_a_rule(self):
        app_module.app.config["TESTING"] = True
        original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", original)
        tree = ruled(tagged("live advises", "live", CAP),
                     tagged("develop advises", "develop", CAP),
                     tagged("staging advises", "staging", CAP),
                     tags={"/aws/live": ("live",), "/aws/develop": ("develop",),
                           "/later": ("staging",)})
        app_module.status_tree = tree
        tree.upsert("/aws/live/fn", ERROR, "x")
        tree.upsert("/aws/develop/fn", WARN, "y")
        client = app_module.app.test_client()
        client.post("/login", data={"username": "pan", "password": "12345678"})
        page = parse(client.get("/handled").get_data(as_text=True))
        rows = {section.one(tag="h3").text(): section
                for section in page.all("by-rule")}
        self.assertIn("What carries live:", rows["live advises"].text())
        self.assertEqual(rows["live advises"].one("by-rule__now").text(),
                         "It changes the count of 1 part now: /aws/live.")
        self.assertEqual(rows["develop advises"].one("by-rule__now").text(),
                         "It picks 1 place now and changes no count there.")
        # a tag written for a path no node stands at yet picks nothing now
        self.assertEqual(rows["staging advises"].one("by-rule__now").text(),
                         "It picks nothing now.")
