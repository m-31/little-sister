"""A configured rule on the pages (ADR-0137): every part keeps its true color, and the
rule is said wherever it changes a count — its block on the wall's box while it acts,
its mark on a line, the ringed diamond's words and the band's pill, a node's own page
always, *Handled*'s *By a rule*, a branch's *why* card and its Copy document, and the
envelope. No block of it carries a button: a configured rule is changed in the
configuration.

What a rule does to a count is `tests/test_aggregation_tree.py`'s.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.aggregation import ALL, RuleSet
from little_sister.reasons import Entry
from little_sister.rule_words import condition_said
from little_sister.status import StatusCode
from little_sister.tree import StatusTree, events_from_payload, nodes_from_payload
from tests.page_tree import Element, parse
from tests.test_aggregation_tree import CAP, FLOOR, HEAL, QUIET, coded, rule

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
TOKEN = "rules-token"


class _RulesCase(TestCase):
    """An estate with a develop account under a cap, every account's ec2 healing,
    three replicas counted, and a lab left out."""

    RULES = (rule("develop advises", "/aws/develop", CAP),
             rule("ec2 heals", "/aws/*/ec2", HEAL, lines=[ALL]),
             rule("replicas", "/web", QUIET, children=[ALL], count=2),
             rule("lab is out", "/lab", None))

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        self.tree.use_aggregation(RuleSet(self.RULES))
        app_module.status_tree = self.tree
        app_module.api_tokens = {"tester": TOKEN}
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/aws/develop/lambda/billing", ERROR, "timed out")
        self.tree.upsert("/aws/prod/ec2", WARN, [
            Entry("i-1", "web-1 cpu credits low", code=WARN),
            Entry("i-2", "web-2 running", code=OK)], members=True)
        self.tree.upsert("/web/a", ERROR, "replica a is down")
        self.tree.upsert("/web/b", OK, "answers")
        self.tree.upsert("/web/c", OK, "answers")

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def blocks(page: Element, name: str = "") -> list[Element]:
        return [block for block in page.all("rule-block")
                if block.attrs.get("data-rule") == "aggregation"
                and (not name or block.attrs.get("data-rule-name") == name)]

    @staticmethod
    def box(page: Element, path: str) -> Element:
        found = [node for node in page.all("tree-node")
                 if node.attrs.get("data-node") == path]
        assert len(found) == 1, path
        return found[0]


class WallTests(_RulesCase):
    """On the wall a rule's block stands while it changes a count, without buttons,
    its note behind its mark."""

    def test_the_cap_s_block_stands_on_the_part_it_changes(self):
        page = self.page("/status")
        block, = self.blocks(page, "develop advises")
        self.assertTrue(block.within(self.box(page, "/aws/develop")))
        self.assertEqual(
            block.one("rule-block__what").text(),
            "error counts as warn above, by the rule develop advises")
        # no buttons: a configured rule is changed in the configuration
        self.assertEqual(block.all("rule-block__edit"), [])
        self.assertEqual(block.all(tag="form"), [])
        mark = block.one("rule-note-mark")
        self.assertEqual(mark.attrs.get("data-note-key"), "rule:develop advises|node")
        self.assertIn("develop advises's note",
                      block.one(tag="template").text())
        self.assertIn("Configured in config/aggregation.yaml since 2026-10-01.",
                      block.one(tag="template").text())

    def test_a_rule_that_changes_nothing_now_has_no_block_on_the_wall(self):
        self.tree.upsert("/aws/develop/lambda/billing", WARN, "slow")
        self.assertEqual(self.blocks(self.page("/status"), "develop advises"), [])

    def test_a_healed_line_keeps_its_color_under_the_rule_s_mark(self):
        page = self.page("/status/aws/prod")
        line = [line for line in page.all("status-node__reason")
                if line.has("is-ruled")]
        self.assertEqual(len(line), 1)
        self.assertTrue(line[0].has("s-warn"))
        self.assertEqual(line[0].one("line-rule").attrs.get("title"),
                         "Counts as ok by the rule ec2 heals")
        block, = self.blocks(page, "ec2 heals")
        self.assertEqual(block.one("rule-block__what").text(),
                         "On its lines, warn counts as ok, by the rule ec2 heals")

    def test_a_count_over_children_stands_on_the_node_it_counts(self):
        page = self.page("/status")
        block, = self.blocks(page, "replicas")
        card = next(card for card in page.all("status-card")
                    if card.one("status-card__head").attrs.get("data-path") == "/web")
        self.assertTrue(block.within(self.box(page, "/web")) or block.within(card))
        self.assertIn("while fewer than 2 fail — 1 does",
                      block.one("rule-block__what").text())

    def test_a_chip_says_what_a_rule_handles(self):
        page = self.page("/status?depth=1")
        chips = {chip.attrs.get("data-path"): chip for chip in page.all("tree-chip")}
        # the replica the count changes keeps its red, and says it is handled
        self.assertEqual(chips["/web/a"].attrs.get("title"),
                         "1 error, 1 handled: 1 by a rule")

    def test_the_band_s_pill_counts_what_a_rule_handles(self):
        pill = self.page("/status").one("maintenance-pill")
        # the capped account, the healed line and the counted replica
        self.assertEqual(pill.attrs.get("aria-label"), "3 handled: 3 by a rule")
        self.assertIn("#handled-rule", pill.parent.source() + "".join(
            element.attrs.get("href", "") for element in pill.parent.walk()))

    def test_a_node_a_rule_changes_is_not_folded_as_healthy(self):
        page = self.page("/status")
        ec2 = [node for node in page.all() if node.attrs.get("data-node")
               == "/aws/prod/ec2" or node.attrs.get("data-path") == "/aws/prod/ec2"]
        self.assertTrue(ec2)
        self.assertFalse(any("data-healthy" in node.attrs for node in ec2))


class NodePageTests(_RulesCase):
    """A node's page states every rule that picks a place at it, whether it acts or
    not, with what it decides over."""

    def test_the_node_s_own_rule_is_stated_whole(self):
        page = self.page("/status/aws/develop")
        block, = self.blocks(page, "develop advises")
        self.assertEqual(
            block.one("rule-block__what").text(),
            "This node: error counts as warn above, by the rule develop advises")
        self.assertEqual(block.one("rule-block__record").text(),
                         "Configured in config/aggregation.yaml since 2026-10-01.")

    def test_a_rule_that_changes_nothing_now_says_so(self):
        self.tree.upsert("/aws/develop/lambda/billing", WARN, "slow")
        block, = self.blocks(self.page("/status/aws/develop"), "develop advises")
        self.assertTrue(block.one("rule-block__what").text().endswith(
            "· changes nothing now"))

    def test_a_child_says_how_its_parent_counts_it(self):
        block, = self.blocks(self.page("/status/web/a"), "replicas")
        self.assertEqual(
            block.one("rule-block__what").text(),
            "Among /web's children, warn and error count as ok while fewer than 2 "
            "fail — 1 does, by the rule replicas")

    def test_the_rules_it_decides_over_are_named(self):
        self.tree.use_aggregation(RuleSet((
            *self.RULES, rule("develop counts nothing", "/aws/develop", None))))
        block, = self.blocks(self.page("/status/aws/develop"), "develop advises")
        self.assertIn("develop counts nothing",
                      block.one("rule-block__record").text())


class HandledTests(_RulesCase):
    """*Handled* lists every configured rule under *By a rule*, the longest standing
    first, with what it changes now or what it missed."""

    def _rows(self) -> dict[str, str]:
        page = self.page("/handled")
        section = page.with_id("handled-rule").parent
        return {row.one(tag="h3").text(): row.one("by-rule__now").text()
                for row in section.all("by-rule")}

    def test_each_rule_with_what_it_changes_now(self):
        rows = self._rows()
        self.assertEqual(list(rows), ["develop advises", "ec2 heals", "replicas",
                                      "lab is out"])
        self.assertEqual(rows["develop advises"],
                         "It changes the count of 1 part now: /aws/develop.")
        self.assertEqual(rows["ec2 heals"],
                         "It changes the count of 1 part now: /aws/prod/ec2 — 1 line.")
        self.assertEqual(rows["replicas"],
                         "It changes the count of 1 part now: /web/a.")

    def test_what_a_rule_missed(self):
        self.tree.upsert("/Lab/box", ERROR, "loud")
        self.assertEqual(self._rows()["lab is out"],
                         "It picks nothing now. With case folded it would pick /Lab.")
        self.tree.use_aggregation(RuleSet((
            rule("develop as it is", "/aws/develop", {}), *self.RULES)))
        self.assertEqual(
            self._rows()["develop advises"],
            "It picks 1 place now and changes no count there: at /aws/develop the "
            "rule develop as it is, written before it, decides.")

    def test_the_longest_standing_first_whatever_the_file_s_order(self):
        # the index's order means something only where every rule has an age: the
        # rule written last, standing longest, comes first
        older = replace(rule("lab is out", "/lab", None), since=date(2026, 3, 7),
                        order=4)
        self.tree.use_aggregation(RuleSet((*self.RULES[:3], older)))
        self.assertEqual(list(self._rows()), ["lab is out", "develop advises",
                                              "ec2 heals", "replicas"])

    def test_its_block_has_no_buttons(self):
        page = self.page("/handled")
        for block in self.blocks(page):
            self.assertEqual(block.all(tag="form"), [])


class WhyAndCopyTests(_RulesCase):
    """A branch's *why* card and its Copy document list what a rule handles beneath
    it under its own job."""

    def test_the_why_card_groups_by_job(self):
        self.tree.upsert("/aws/prod/lambda/api", ERROR, "deploying")
        self.tree.set_maintenance("/aws/prod/lambda", "deploying",
                                  expires_at=datetime.now(UTC) + timedelta(hours=1),
                                  set_by="lex")
        why = self.page("/status/aws").with_id("why")
        jobs = [job.text() for job in why.all("why-card__job")]
        self.assertEqual(jobs, ["In maintenance", "By a rule"])
        rows = [item.text() for item in why.all("why-list")[-1].all(tag="li")]
        self.assertTrue(any(row.startswith(
            "develop, reads error, counts warn · by the rule develop advises since "
            "2026-10-01") for row in rows), rows)

    def test_the_copy_document_writes_the_same(self):
        source = self.page("/copy/aws").with_id("ls-copy-source").source()
        self.assertIn("- § By a rule\n  - develop, reads error ⛔, counts warn ⚠️ — "
                      "by the rule develop advises, since 2026-10-01", source)


class EnvelopeTests(_RulesCase):
    """The envelope says it as the page does: ``aggregation`` in a node's
    ``contribution.by``, and a line's own ``contribution`` — each with the rule that
    decided, which ``handled`` lists while it acts (ADR-0141 decision 3)."""

    def _json(self, path: str = "") -> dict:
        response = self.client.get(f"/status{path}", headers={
            "Accept": "application/json", "Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()["status"]

    def test_a_capped_node_says_what_its_parent_counts(self):
        develop = self._json("/aws/develop")
        self.assertEqual(develop["code"], "ERROR")
        self.assertEqual(develop["contribution"], {
            "code": "WARN", "by": "aggregation", "rule": "develop advises"})
        (said,) = develop["handled"]
        self.assertEqual(said, {
            "id": "develop advises", "kind": "aggregation",
            "source": "configuration", "note": said["note"],
            "file": said["file"], "since": said["since"], "level": "node",
            "counts_as": {"ERROR": "WARN"}})

    def test_a_line_says_what_its_node_counts_of_it(self):
        self.tree.upsert("/db/pool", ERROR, [
            Entry("primary", "unreachable", code=ERROR),
            Entry("replica", "in step", code=OK)], members=True)
        self.tree.set_entry_maintenance(
            "/db/pool", "primary", "swapping it",
            expires_at=datetime.now(UTC) + timedelta(hours=1), set_by="ada",
            expected_set_at=None)
        healed, fine = self._json("/aws/prod/ec2")["entries"]["items"]
        self.assertEqual(healed["contribution"], {
            "code": "OK", "by": "aggregation", "rule": "ec2 heals"})
        self.assertEqual([said["id"] for said in healed["handled"]], ["ec2 heals"])
        self.assertIsNone(fine["contribution"])
        self.assertEqual(fine["handled"], [])
        # the rule on the node's lines stands on the node too, as its block does
        self.assertEqual([(said["id"], said["level"], said["lines"]) for said
                          in self._json("/aws/prod/ec2")["handled"]],
                         [("ec2 heals", "lines", ["*"])])
        pinned, kept = self._json("/db/pool")["entries"]["items"]
        pin = self.tree.entry_maintenance("/db/pool", "primary")
        self.assertEqual(pinned["contribution"], {
            "code": None, "by": "maintenance", "rule": pin.id})
        self.assertEqual([said["id"] for said in pinned["handled"]], [pin.id])
        self.assertIsNone(kept["contribution"])

    def test_a_counted_child_says_it_on_its_own_subtree_too(self):
        counted = self._json("/web/a")
        self.assertEqual(counted["contribution"],
                         {"code": "OK", "by": "aggregation", "rule": "replicas"})
        (said,) = counted["handled"]
        self.assertEqual((said["id"], said["level"], said["children"],
                          said["while_fewer_than"], said["failing"]),
                         ("replicas", "children", ["*"], 2, 1))


class EventsTests(_RulesCase):
    """The Events page marks a row a rule held back as it marks damping's."""

    def test_a_held_row_carries_the_rule_s_word(self):
        self.tree.upsert("/aws/develop/lambda/billing", OK, "fine")
        self.tree.upsert("/aws/develop", ERROR, "the account's own check fails")
        body = self.client.get("/events").get_data(as_text=True)
        self.assertTrue(re.search(r'class="event-suppressed">aggregation<', body))

    def test_a_reading_a_floor_raised_is_not_listed(self):
        # the page lists a row its node showed or one a rule held back, and the warning
        # a floor made an error is neither — the log keeps it for what the check said
        self.tree.use_aggregation(RuleSet((*self.RULES, rule(
            "the gateway has no amber", "/gw", FLOOR, lines=[ALL]))))
        coded(self.tree, "/gw", a=OK)
        coded(self.tree, "/gw", a=WARN)
        self.assertIn((OK, WARN), [(event.old, event.new)
                                   for event in self.tree.recent_events()])
        page = self.page("/events?under=%2Fgw")
        self.assertEqual([status.text() for status in page.all("ls-log__status")],
                         ["error", "ok"])
        # and every count is of the rows it lists: all the log's but that one
        self.assertIn(f"2 of {len(self.tree.recent_events()) - 1} events match",
                      page.text())


class WordsTests(TestCase):
    """A count's tally says how many fail — never *of* its number, since *7 of 10* on a
    node of eight lines read as a share of them, and *12 of 10* where the count was
    reached."""

    def test_the_tally_says_how_many_fail(self):
        counted = rule("wiz counts ten", "/wiz/medium", CAP, lines=[ALL], count=10)
        self.assertEqual(
            {failing: condition_said(counted, failing)
             for failing in (0, 1, 7, 12, None)},
            {0: " while fewer than 10 fail — none does",
             1: " while fewer than 10 fail — 1 does",
             7: " while fewer than 10 fail — 7 do",
             12: " while fewer than 10 fail — 12 do",
             None: " while fewer than 10 fail"})
        self.assertEqual(condition_said(rule("lab", "/lab", None), 3), "")


class RuleBeganTests(TestCase):
    """A period a rule's beginning began says so (ADR-0137 decision 11): History's
    *What* and *From*, the Copy document's clause and the envelope's ``period`` name the
    rule and the node whose count it changed. The instance saw develop go red without
    the rule, and restarted on it."""

    def setUp(self) -> None:
        wall = [datetime(2026, 10, 20, 9, 0, tzinfo=UTC)]
        patched = mock.patch.object(instants, "now", lambda: wall[0])
        patched.start()
        self.addCleanup(patched.stop)
        before = StatusTree()
        before.upsert("/aws/develop", OK)
        before.upsert("/aws/prod", OK)
        wall[0] = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
        before.upsert("/aws/develop", ERROR, "timed out")
        wall[0] = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
        payload = json.loads(json.dumps(before.events_payload()))
        self.tree = StatusTree()
        self.tree.use_aggregation(RuleSet([replace(
            rule("develop advises", "/aws/develop", CAP), since=date(2026, 10, 22))]))
        self.tree.restore_events(events_from_payload(payload),
                                 nodes_from_payload(payload))
        self.tree.upsert("/aws/develop", ERROR, "timed out")
        self.tree.upsert("/aws/prod", OK)
        app_module.app.config["TESTING"] = True
        app_module.status_tree = self.tree
        app_module.api_tokens = {"tester": TOKEN}
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def test_history_says_what_began_it_and_where(self):
        shown = self.page("/history/aws").all("ls-history__shown")[0]
        rows = [[cell.text() for cell in row.all(tag="td")]
                for row in shown.all(tag="tr")[1:]]
        self.assertEqual([(row[0], row[3], row[4]) for row in rows],
                         [("warn", "develop", "the rule develop advises began"),
                          ("error", "develop", "a reading"),
                          ("ok", "", "")])

    def test_the_copy_document_names_the_rule(self):
        source = self.page("/copy/aws").with_id("ls-copy-source").source()
        self.assertIn(", begun by the rule develop advises beginning to count "
                      "develop beneath it", source)

    def test_the_envelope_names_the_rule(self):
        response = self.client.get("/status/aws", headers={
            "Accept": "application/json", "Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(response.status_code, 200)
        period = response.get_json()["status"]["period"]
        said = {key: period.get(key) for key in ("was", "cause", "by", "rule")}
        self.assertEqual(said, {"was": "ERROR", "cause": "rule", "by": "/aws/develop",
                                "rule": "develop advises"})
